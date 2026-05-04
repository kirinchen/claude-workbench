#!/usr/bin/env python3
"""Phase 12 regression checks for kanban v0.3.5 — @-mention detection
and reply / sub-card primitives (issue-followup).

Wave 1: detection — find-mentions JQL+ADF flow, mark-mentions-read
        ack timestamp roundtrip, self-mention filter.
Wave 2: primitives — post-reply with @-mention ADF, create-sub batch
        create + parent issue link, ADF helpers (extract + build).

Cases:
  (a) adf_extract_mentions: returns all mention nodes; filters by
      target accountId; handles nested ADF
  (b) text_to_adf_with_mention: produces a doc with prefix paragraph
      + mention paragraph; round-trips through adf_to_text
  (c) JiraDriver.post_comment with mention_account_id sends ADF that
      includes the mention node; without it, plain-text path unchanged
  (d) JiraDriver.create_task with parent_key creates the issue, then
      issue link parent←child via Relates
  (e) cmd_find_mentions: JQL filters by updated >= since; ADF walked
      for mentions; self-mentions (author == agent) filtered out
  (f) cmd_find_mentions: when lastMentionSeenAt absent, defaults to
      ~24h ago (sane first-run behaviour)
  (g) cmd_mark_mentions_read: writes lastMentionSeenAt to
      .claude/kanban-agent.json; preserves other fields; refuses to
      move backwards
  (h) cmd_post_reply: routes through driver.post_comment with mention
      kwargs; emits the right event shape
  (i) cmd_create_sub: creates N issues + N issue links; failed titles
      tracked separately; AP auto-assigned to spawned cards (via mock)
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"
sys.path.insert(0, str(REPO / "plugins" / "kanban"))

from lib.jira_client import (  # noqa: E402
    JiraClient,
    _Response,
    adf_extract_mentions,
    text_to_adf_with_mention,
    adf_to_text,
)

_spec = importlib.util.spec_from_file_location(
    "jira_setup_mod", str(PLUGIN / "scripts" / "jira_setup.py")
)
_jira_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_jira_setup)  # type: ignore[union-attr]


def _mock_transport(queue, calls):
    def t(method, url, headers, body):
        calls.append({"method": method, "url": url, "body": body})
        if not queue:
            raise AssertionError(f"queue empty for {method} {url}")
        return queue.pop(0)
    return t


def _mk_client(queue, calls):
    return JiraClient(
        "https://x.atlassian.net", "a@b", "tok",
        transport=_mock_transport(queue, calls), sleep=lambda _: None,
    )


# --- ADF helpers --------------------------------------------------------


def test_adf_extract_mentions_unfiltered():
    adf = {"type": "doc", "content": [
        {"type": "paragraph", "content": [
            {"type": "mention", "attrs": {"id": "5e1", "text": "@Bot"}},
            {"type": "text", "text": " hello"},
            {"type": "mention", "attrs": {"id": "5e2", "text": "@Other"}},
        ]},
    ]}
    out = adf_extract_mentions(adf)
    ids = [m["accountId"] for m in out]
    assert ids == ["5e1", "5e2"]


def test_adf_extract_mentions_target_filter():
    adf = {"type": "doc", "content": [
        {"type": "paragraph", "content": [
            {"type": "mention", "attrs": {"id": "5e1", "text": "@Bot"}},
            {"type": "mention", "attrs": {"id": "5e2", "text": "@Other"}},
        ]},
        {"type": "paragraph", "content": [
            {"type": "mention", "attrs": {"id": "5e1", "text": "@Bot"}},
        ]},
    ]}
    out = adf_extract_mentions(adf, target_account_id="5e1")
    assert len(out) == 2
    assert all(m["accountId"] == "5e1" for m in out)
    assert adf_extract_mentions(None) == []
    assert adf_extract_mentions({}) == []


def test_text_to_adf_with_mention_shape():
    doc = text_to_adf_with_mention(
        prefix_text="**[ap] [C]**",
        mention_account_id="5e9",
        mention_display="kirin",
        body_text="評估完成",
    )
    assert doc["type"] == "doc" and doc["version"] == 1
    # Two paragraphs: prefix, then mention+body
    assert len(doc["content"]) == 2
    pre = doc["content"][0]
    assert pre["content"][0]["text"] == "**[ap] [C]**"
    body = doc["content"][1]
    assert body["content"][0]["type"] == "mention"
    assert body["content"][0]["attrs"]["id"] == "5e9"
    assert body["content"][0]["attrs"]["text"] == "@kirin"
    assert body["content"][1]["text"] == " 評估完成"
    # Round-trip via adf_to_text — mention nodes don't carry text by
    # design; text contains prefix + " 評估完成"
    flat = adf_to_text(doc)
    assert "**[ap] [C]**" in flat
    assert "評估完成" in flat


# --- Driver-level integration ------------------------------------------


def _seed_jira(td) -> pathlib.Path:
    p = pathlib.Path(td) / "kanban.json"
    cfg = {
        "boardUrl": "https://acme.atlassian.net/jira/software/projects/AGENT/boards/1",
        "boardId": 1,
        "projectKey": "AGENT",
        "agentAccountId": "5e-bot",
        "transitions": {
            "TODO": {"status": "To Do"},
            "DOING": {"status": "In Progress"},
            "BLOCKED": {"status": "In Progress", "addLabels": ["kanban:blocked"]},
            "APPROVED": {"status": "Done"},
        },
        "ap": {"fieldId": "customfield_10042", "fieldName": "Claude Agent",
               "registered": ["agent-fin"]},
    }
    p.write_text(json.dumps({
        "version": "0.2",
        "backend": {"driver": "jira", "jira": cfg},
        "meta": {"priorities": ["P0"], "categories": [],
                 "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "APPROVED", "CANCELLED"],
                 "created_at": "x", "updated_at": "x"},
        "tasks": [],
    }))
    return p


def _patched_driver(data, project_root):
    from drivers.jira import JiraDriver
    from lib import credentials

    orig = credentials.read
    credentials.read = lambda prefix=None: {
        "JIRA_BASE_URL": "https://x", "JIRA_AGENT_EMAIL": "a@b",
        "JIRA_API_TOKEN": "tok",
    }
    try:
        drv = JiraDriver(data, project_root)
    finally:
        credentials.read = orig
    return drv


def _attach_mock(drv, queue, calls):
    drv._client = _mk_client(queue, calls)


def test_post_comment_with_mention_includes_node():
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_jira(td)
        data = json.loads(kp.read_text())
        drv = _patched_driver(data, kp.parent)
        queue = [_Response(201, b'{"created":"x"}', {})]
        calls = []
        _attach_mock(drv, queue, calls)

        drv.post_comment(
            "AGENT-1", "verdict + next step",
            mention_account_id="5e-kirin", mention_display="Kirin",
        )
        sent = json.loads(calls[0]["body"])
        body = sent["body"]
        # Walk content for a mention node
        found_mention = False
        for para in body["content"]:
            for node in para.get("content", []):
                if node.get("type") == "mention":
                    if node["attrs"]["id"] == "5e-kirin":
                        found_mention = True
        assert found_mention, body


def test_post_comment_without_mention_unchanged():
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_jira(td)
        data = json.loads(kp.read_text())
        drv = _patched_driver(data, kp.parent)
        queue = [_Response(201, b'{"created":"x"}', {})]
        calls = []
        _attach_mock(drv, queue, calls)
        drv.post_comment("AGENT-1", "plain comment")
        sent = json.loads(calls[0]["body"])
        # No mention nodes anywhere
        for para in sent["body"]["content"]:
            for node in para.get("content", []):
                assert node.get("type") != "mention"


def test_create_task_with_parent_links():
    from drivers.base import TaskInput

    with tempfile.TemporaryDirectory() as td:
        kp = _seed_jira(td)
        data = json.loads(kp.read_text())
        drv = _patched_driver(data, kp.parent)
        # 1) POST /issue creates the new card
        # 2) POST /issueLink links parent <- child
        # 3) GET /issue/{key} (final get_task in create_task)
        queue = [
            _Response(201, b'{"key":"AGENT-200","id":"100"}', {}),
            _Response(201, b"", {}),
            _Response(200, json.dumps({
                "key": "AGENT-200",
                "fields": {"summary": "child",
                           "status": {"name": "To Do"},
                           "priority": {"name": "P1"},
                           "assignee": None, "labels": [],
                           "created": "x", "updated": "y",
                           "issuelinks": []},
            }).encode(), {}),
        ]
        calls = []
        _attach_mock(drv, queue, calls)
        t = drv.create_task(TaskInput(
            title="child",
            parent_key="AGENT-100",
            link_type="Relates",
        ))
        assert t.id == "AGENT-200"
        # Second call must be the issue-link POST
        assert calls[1]["url"].endswith("/rest/api/3/issueLink")
        sent = json.loads(calls[1]["body"])
        assert sent == {
            "type": {"name": "Relates"},
            "inwardIssue": {"key": "AGENT-100"},
            "outwardIssue": {"key": "AGENT-200"},
        }


# --- CLI: find-mentions / mark-mentions-read ---------------------------


def _patch_client_factory(client_factory):
    orig = _jira_setup._client_from_env
    _jira_setup._client_from_env = client_factory
    return orig


def _restore_client(orig):
    _jira_setup._client_from_env = orig


def _capture_cmd(fn, args_obj):
    from io import StringIO
    old = sys.stdout
    sys.stdout = StringIO()
    try:
        rc = fn(args_obj)
        out = sys.stdout.getvalue()
    finally:
        sys.stdout = old
    return rc, out


def test_find_mentions_filters_self():
    """Self-mentions (author == agent account) are dropped."""
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_jira(td)
        # Write a recent lastMentionSeenAt so the JQL boundary is sane
        (kp.parent / ".claude").mkdir()
        (kp.parent / ".claude" / "kanban-agent.json").write_text(
            json.dumps({"ap": "agent-fin",
                        "lastMentionSeenAt": "2026-04-29T00:00:00+08:00"})
        )

        # Mock: search_jql returns 1 issue → get_issue returns 2 comments
        # — one by the bot (self-mention, dropped), one by a human (kept).
        queue = [
            # search_jql
            _Response(200, json.dumps({
                "issues": [{"key": "AGENT-1", "fields": {"updated": "2026-04-30T01:00:00+08:00"}}],
            }).encode(), {}),
            # get_issue for AGENT-1
            _Response(200, json.dumps({
                "key": "AGENT-1",
                "fields": {
                    "description": None,
                    "updated": "2026-04-30T01:00:00+08:00",
                    "comment": {"comments": [
                        {  # self-mention by bot (filtered)
                            "id": "c1",
                            "created": "2026-04-30T00:30:00+08:00",
                            "author": {"accountId": "5e-bot",
                                       "displayName": "Bot"},
                            "body": {"type": "doc", "content": [
                                {"type": "paragraph", "content": [
                                    {"type": "mention",
                                     "attrs": {"id": "5e-bot", "text": "@Bot"}},
                                ]},
                            ]},
                        },
                        {  # human mention (kept)
                            "id": "c2",
                            "created": "2026-04-30T00:45:00+08:00",
                            "author": {"accountId": "5e-kirin",
                                       "displayName": "Kirin"},
                            "body": {"type": "doc", "content": [
                                {"type": "paragraph", "content": [
                                    {"type": "mention",
                                     "attrs": {"id": "5e-bot", "text": "@Bot"}},
                                    {"type": "text", "text": " please"},
                                ]},
                            ]},
                        },
                    ]},
                },
            }).encode(), {}),
        ]
        calls = []
        c = _mk_client(queue, calls)
        orig = _patch_client_factory(lambda: c)
        try:
            class A:
                kanban_path = str(kp); since = None
            rc, out = _capture_cmd(_jira_setup.cmd_find_mentions, A())
        finally:
            _restore_client(orig)
        assert rc == 0
        j = json.loads(out)
        assert j["ok"] is True
        assert len(j["mentions"]) == 1
        assert j["mentions"][0]["author"] == "Kirin"
        assert j["mentions"][0]["authorAccountId"] == "5e-kirin"


def test_mark_mentions_read_advances_and_preserves_fields():
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_jira(td)
        (kp.parent / ".claude").mkdir()
        (kp.parent / ".claude" / "kanban-agent.json").write_text(json.dumps({
            "ap": "agent-fin",
            "acknowledgedConventions": {"hash": "abc", "at": "2026-04-29T00:00:00+08:00"},
        }))
        class A:
            kanban_path = str(kp); until = "2026-04-30T10:00:00+08:00"
        rc, out = _capture_cmd(_jira_setup.cmd_mark_mentions_read, A())
        assert rc == 0
        j = json.loads(out)
        assert j["ok"] is True and j["advanced"] is True
        # File should now have BOTH lastMentionSeenAt AND ap AND acknowledgedConventions
        on_disk = json.loads((kp.parent / ".claude" / "kanban-agent.json").read_text())
        assert on_disk["ap"] == "agent-fin"
        assert on_disk["acknowledgedConventions"]["hash"] == "abc"
        assert on_disk["lastMentionSeenAt"] == "2026-04-30T10:00:00+08:00"


def test_mark_mentions_read_refuses_backwards():
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_jira(td)
        (kp.parent / ".claude").mkdir()
        (kp.parent / ".claude" / "kanban-agent.json").write_text(json.dumps({
            "lastMentionSeenAt": "2026-04-30T10:00:00+08:00",
        }))
        class A:
            kanban_path = str(kp); until = "2026-04-29T00:00:00+08:00"
        rc, out = _capture_cmd(_jira_setup.cmd_mark_mentions_read, A())
        assert rc == 0
        j = json.loads(out)
        assert j["advanced"] is False


# --- CLI: post-reply / create-sub --------------------------------------


def test_post_reply_routes_with_mention():
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_jira(td)

        class StubDriver:
            name = "jira"
            def __init__(self): self.calls = []
            def post_comment(self, key, body, kind=None,
                             mention_account_id=None, mention_display=None):
                self.calls.append((key, body, mention_account_id, mention_display))
                from drivers.base import Comment
                from drivers.base import CommentKind
                return Comment(author="agent", ts="2026-04-30T11:00:00+08:00",
                               text=body, kind=CommentKind.COMMENT)

        stub = StubDriver()
        import drivers as _drv_mod
        orig = _drv_mod.get_driver
        _drv_mod.get_driver = lambda data, root: stub
        try:
            class A:
                kanban_path = str(kp); key = "AGENT-1"
                body = "verdict"; to_account_id = "5e-kirin"
                display_name = "Kirin"
            rc, out = _capture_cmd(_jira_setup.cmd_post_reply, A())
        finally:
            _drv_mod.get_driver = orig
        assert rc == 0
        j = json.loads(out)
        assert j["ok"] is True and j["mentioned"] == "5e-kirin"
        assert stub.calls[0] == ("AGENT-1", "verdict", "5e-kirin", "Kirin")


def test_create_sub_creates_n_cards_with_links():
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_jira(td)
        # Stub driver: count create_task calls, ignore assign failures
        class StubDriver:
            name = "jira"
            def __init__(self): self.created = []; self.assigned = []
            def create_task(self, task):
                self.created.append(task)
                from drivers.base import Task
                key = f"AGENT-{200 + len(self.created)}"
                return Task(id=key, title=task.title, column="TODO",
                            priority=task.priority or "P2",
                            created="x", updated="y")
            def assign(self, key, member):
                self.assigned.append((key, member))
                from drivers.base import Task
                return Task(id=key, title="x", column="TODO",
                            priority="P1", created="x", updated="y")

        stub = StubDriver()
        # Pre-set repo AP so create_sub assigns
        (kp.parent / ".claude").mkdir()
        (kp.parent / ".claude" / "kanban-agent.json").write_text(
            json.dumps({"ap": "agent-fin"})
        )
        import drivers as _drv_mod
        orig = _drv_mod.get_driver
        _drv_mod.get_driver = lambda data, root: stub
        try:
            class A:
                kanban_path = str(kp); parent = "AGENT-100"
                titles = ["design", "wire endpoint", "wire UI"]
                description = ""; priority = "P1"
                link_type = "Relates"
            rc, out = _capture_cmd(_jira_setup.cmd_create_sub, A())
        finally:
            _drv_mod.get_driver = orig
        assert rc == 0
        j = json.loads(out)
        assert j["ok"] is True
        assert len(j["created"]) == 3
        assert j["failed"] == []
        # Each create_task got the parent + Relates link type
        for task in stub.created:
            assert task.parent_key == "AGENT-100"
            assert task.link_type == "Relates"
        # Each spawned card got an AP assignment
        assert len(stub.assigned) == 3


def main() -> int:
    cases = [
        ("adf_extract_mentions_unfiltered", test_adf_extract_mentions_unfiltered),
        ("adf_extract_mentions_target_filter", test_adf_extract_mentions_target_filter),
        ("text_to_adf_with_mention_shape", test_text_to_adf_with_mention_shape),
        ("post_comment_with_mention_includes_node", test_post_comment_with_mention_includes_node),
        ("post_comment_without_mention_unchanged", test_post_comment_without_mention_unchanged),
        ("create_task_with_parent_links", test_create_task_with_parent_links),
        ("find_mentions_filters_self", test_find_mentions_filters_self),
        ("mark_mentions_read_advances_and_preserves_fields", test_mark_mentions_read_advances_and_preserves_fields),
        ("mark_mentions_read_refuses_backwards", test_mark_mentions_read_refuses_backwards),
        ("post_reply_routes_with_mention", test_post_reply_routes_with_mention),
        ("create_sub_creates_n_cards_with_links", test_create_sub_creates_n_cards_with_links),
    ]
    for name, fn in cases:
        try:
            fn()
        except AssertionError as e:
            print(f"FAIL  {name}: {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"ERROR {name}: {type(e).__name__}: {e}", file=sys.stderr)
            return 2
        print(f"ok    {name}")
    print("phase12: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
