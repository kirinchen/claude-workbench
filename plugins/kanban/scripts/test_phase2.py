#!/usr/bin/env python3
"""Phase 2 regression checks for kanban v0.2.0-dev (Jira driver core).

Run from anywhere:
    python3 plugins/kanban/scripts/test_phase2.py

All Jira interactions are mocked — no live network. Covers:
  (a) jira_client retry behaviour: 429 with Retry-After, 5xx exponential
  (b) jira_client raises immediately on 401 / non-retryable 4xx
  (c) JiraDriver dispatch: get_driver(data with driver=jira) → JiraDriver
  (d) JiraDriver.list_tasks builds correct JQL and parses issues
  (e) JiraDriver.transition resolves transition_id from statusMap
  (f) JiraDriver.post_comment prefixes per SPEC §9
  (g) JiraDriver.list_comments parses prefix back to (ap, kind, text)
  (h) jira_setup.parse-board-url handles both URL shapes
  (i) jira_setup.write-backend persists backend.jira block to kanban.json
"""
from __future__ import annotations

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
    JiraError,
    _Response,
    text_to_adf,
    adf_to_text,
)


def _mock_transport(queue, calls):
    def t(method, url, headers, body):
        calls.append({"method": method, "url": url, "headers": headers, "body": body})
        if not queue:
            raise AssertionError("transport queue empty")
        return queue.pop(0)
    return t


# --- jira_client tests --------------------------------------------------


def test_client_429_retry_after():
    queue = [
        _Response(429, b"", {"retry-after": "0.01"}),
        _Response(200, b'{"accountId":"abc"}', {}),
    ]
    calls = []
    sleeps: list[float] = []
    c = JiraClient("https://x", "a@b", "tok", transport=_mock_transport(queue, calls), sleep=sleeps.append)
    assert c.get_myself()["accountId"] == "abc"
    assert sleeps == [0.01]
    assert len(calls) == 2


def test_client_5xx_exponential():
    queue = [
        _Response(503, b"", {}),
        _Response(503, b"", {}),
        _Response(200, b'{"id":1}', {}),
    ]
    calls = []
    sleeps: list[float] = []
    c = JiraClient("https://x", "a@b", "tok", transport=_mock_transport(queue, calls), sleep=sleeps.append)
    assert c.get_board(1)["id"] == 1
    assert sleeps == [0.5, 1.0]


def test_client_401_immediate():
    queue = [_Response(401, b'{"errorMessages":["bad token"]}', {})]
    calls = []
    c = JiraClient("https://x", "a@b", "tok", transport=_mock_transport(queue, calls), sleep=lambda _: None)
    try:
        c.get_myself()
        assert False
    except JiraError as e:
        assert e.status_code == 401
        assert "bad token" in e.detail
    assert len(calls) == 1


def test_client_max_retries_exhausted():
    queue = [_Response(500, b"", {}) for _ in range(5)]
    calls = []
    c = JiraClient("https://x", "a@b", "tok", transport=_mock_transport(queue, calls), sleep=lambda _: None)
    try:
        c.get_myself()
        assert False
    except JiraError as e:
        assert e.status_code == 500
    assert len(calls) == 4


def test_adf_round_trip():
    adf = text_to_adf("hello")
    assert adf_to_text(adf) == "hello"


# --- JiraDriver tests ---------------------------------------------------


def _mk_kanban_data(*, partial=False, label_fallback=None, ap_field=None):
    backend = {
        "driver": "jira",
        "jira": {
            "boardUrl": "https://x/boards/1",
            "boardId": 1,
            "projectKey": "AGENT",
            "agentAccountId": "agent-acct",
            "statusMap": {
                "TODO": "To Do",
                "DOING": "In Progress",
                "APPROVED": "Done",
            },
            "partial": partial,
            "labelFallback": label_fallback or {},
        },
    }
    if ap_field:
        backend["jira"]["ap"] = {"fieldId": ap_field, "fieldName": "Claude Agent", "registered": []}
    return {
        "version": "0.2",
        "backend": backend,
        "meta": {
            "priorities": ["P0", "P1", "P2"],
            "categories": [],
            "columns": ["TODO", "DOING", "APPROVED", "BLOCKED", "REVIEW", "CANCELLED"],
            "created_at": "2026-04-29T00:00:00+08:00",
            "updated_at": "2026-04-29T00:00:00+08:00",
        },
        "tasks": [],
    }


def _patched_driver(data, monkeypatch_creds=None):
    """Build a JiraDriver with credentials mocked in via monkey-patch on
    credentials.read."""
    from lib import credentials
    from drivers.jira import JiraDriver

    orig_read = credentials.read
    creds = monkeypatch_creds or {
        "JIRA_BASE_URL": "https://x",
        "JIRA_AGENT_EMAIL": "a@b",
        "JIRA_API_TOKEN": "tok",
    }
    credentials.read = lambda prefix=None: {k: v for k, v in creds.items() if not prefix or k.startswith(prefix)}
    try:
        with tempfile.TemporaryDirectory() as td:
            drv = JiraDriver(data, pathlib.Path(td))
            return drv
    finally:
        credentials.read = orig_read


def _attach_mock(drv, queue, calls):
    drv._client = JiraClient(
        drv.base_url, drv.email, drv._token,
        transport=_mock_transport(queue, calls),
        sleep=lambda _: None,
    )


def test_dispatch_to_jira_driver():
    from drivers import get_driver
    from drivers.jira import JiraDriver

    data = _mk_kanban_data()
    with tempfile.TemporaryDirectory() as td:
        drv = _patched_driver(data)
        # _patched_driver builds a fresh driver with td root; here we just
        # verify get_driver returns the right class.
        from lib import credentials
        orig = credentials.read
        credentials.read = lambda prefix=None: {"JIRA_BASE_URL": "https://x", "JIRA_AGENT_EMAIL": "a@b", "JIRA_API_TOKEN": "tok"}
        try:
            d2 = get_driver(data, td)
            assert isinstance(d2, JiraDriver)
            assert d2.name == "jira"
        finally:
            credentials.read = orig


def test_list_tasks_builds_jql():
    data = _mk_kanban_data()
    drv = _patched_driver(data)
    queue = [
        _Response(
            200,
            json.dumps(
                {
                    "issues": [
                        {
                            "key": "AGENT-1",
                            "fields": {
                                "summary": "first",
                                "status": {"name": "To Do"},
                                "priority": {"name": "P1"},
                                "assignee": {"accountId": "u-1"},
                                "labels": [],
                                "created": "2026-04-29T00:00:00+08:00",
                                "updated": "2026-04-29T00:00:00+08:00",
                            },
                        }
                    ]
                }
            ).encode(),
            {},
        )
    ]
    calls = []
    _attach_mock(drv, queue, calls)

    from drivers.base import TaskFilter

    tasks = drv.list_tasks(TaskFilter(column="TODO", limit=10))
    assert len(tasks) == 1
    t = tasks[0]
    assert t.id == "AGENT-1" and t.column == "TODO" and t.title == "first"
    sent = json.loads(calls[0]["body"])
    assert 'project = "AGENT"' in sent["jql"]
    assert 'status = "To Do"' in sent["jql"]
    assert sent["maxResults"] == 10


def test_transition_resolves_id():
    data = _mk_kanban_data()
    drv = _patched_driver(data)
    # v0.3 flow: 1) pre-flight get_task; 2) get_transitions;
    # 3) transition_issue (POST); 4) post-transition get_task refresh.
    pre_issue = {
        "key": "AGENT-1",
        "fields": {
            "summary": "first",
            "status": {"name": "To Do"},
            "priority": {"name": "P1"},
            "assignee": None,
            "labels": [],
            "created": "x",
            "updated": "y",
        },
    }
    post_issue = {
        "key": "AGENT-1",
        "fields": {
            "summary": "first",
            "status": {"name": "In Progress"},
            "priority": {"name": "P1"},
            "assignee": None,
            "labels": [],
            "created": "x",
            "updated": "y",
        },
    }
    queue = [
        _Response(200, json.dumps(pre_issue).encode(), {}),
        _Response(
            200,
            json.dumps(
                {
                    "transitions": [
                        {"id": "21", "to": {"name": "In Progress"}},
                        {"id": "31", "to": {"name": "Done"}},
                    ]
                }
            ).encode(),
            {},
        ),
        _Response(204, b"", {}),
        _Response(200, json.dumps(post_issue).encode(), {}),
    ]
    calls = []
    _attach_mock(drv, queue, calls)

    t = drv.transition("AGENT-1", "DOING")
    assert t.column == "DOING"
    # Third call must be the transition POST with id=21 (after pre-flight + transitions list).
    assert calls[2]["method"] == "POST"
    sent = json.loads(calls[2]["body"])
    assert sent["transition"]["id"] == "21"


def test_transition_unknown_column_raises():
    data = _mk_kanban_data()
    drv = _patched_driver(data)
    try:
        drv.transition("AGENT-1", "NOPE")
        assert False
    except ValueError:
        pass


def test_post_comment_prefixes():
    data = _mk_kanban_data()
    drv = _patched_driver(data)
    queue = [_Response(201, b'{"created":"2026-04-29T00:00:00+08:00"}', {})]
    calls = []
    _attach_mock(drv, queue, calls)

    from drivers.base import CommentKind

    drv.post_comment("AGENT-1", "Body of question?", CommentKind.QUESTION)
    sent = json.loads(calls[0]["body"])
    # v0.3.12 (#27): prefix is now an ADF strong-marked text node in its
    # own paragraph — emitting `**...**` markdown literals broke Jira UI
    # rendering. adf_to_text drops the marks and returns canonical text.
    body_text = adf_to_text(sent["body"])
    # No repo_ap configured in the temp project → fallback "agent" is used.
    assert body_text.startswith("[agent] [Q]"), body_text
    assert "Body of question?" in body_text
    # Verify the actual ADF shape so a regression to markdown-string mode
    # is caught loudly: first paragraph has the prefix as a strong text
    # node, second paragraph is the body as plain text.
    paras = sent["body"]["content"]
    assert paras[0]["type"] == "paragraph"
    p0 = paras[0]["content"][0]
    assert p0["type"] == "text"
    assert p0["text"] == "[agent] [Q]"
    assert {"type": "strong"} in p0["marks"]
    assert paras[1]["content"][0]["text"] == "Body of question?"


def test_list_comments_parses_prefix():
    data = _mk_kanban_data()
    drv = _patched_driver(data)
    # Compose a Jira response with one prefixed agent comment + one human reply
    queue = [
        _Response(
            200,
            json.dumps(
                {
                    "comments": [
                        {
                            "author": {"displayName": "Agent Bot"},
                            "created": "2026-04-29T00:00:00+08:00",
                            "body": text_to_adf("**[agent-fin] [Q]**\n\nIs the API stable?"),
                        },
                        {
                            "author": {"displayName": "Alice"},
                            "created": "2026-04-29T00:01:00+08:00",
                            "body": text_to_adf("Yes, locked in."),
                        },
                    ]
                }
            ).encode(),
            {},
        )
    ]
    calls = []
    _attach_mock(drv, queue, calls)

    comments = drv.list_comments("AGENT-1")
    assert len(comments) == 2
    assert comments[0].author == "agent-fin"
    assert comments[0].kind.value == "Q"
    assert "Is the API stable?" in comments[0].text
    assert comments[1].author == "Alice"


# --- jira_setup CLI tests -----------------------------------------------


def _setup_cmd(*args, stdin: bytes = b"") -> subprocess.CompletedProcess:
    cmd = ["python3", str(PLUGIN / "scripts" / "jira_setup.py"), *args]
    return subprocess.run(cmd, input=stdin, capture_output=True)


def test_parse_board_url():
    out = _setup_cmd("parse-board-url", "--url", "https://x/jira/software/projects/AGENT/boards/1")
    assert out.returncode == 0, out.stderr
    j = json.loads(out.stdout)
    assert j == {"projectKey": "AGENT", "boardId": 1}

    out = _setup_cmd("parse-board-url", "--url", "https://x/jira/software/c/projects/FIN/boards/42")
    j = json.loads(out.stdout)
    assert j == {"projectKey": "FIN", "boardId": 42}

    out = _setup_cmd("parse-board-url", "--url", "https://example.com/garbage")
    assert out.returncode != 0


def test_write_backend():
    with tempfile.TemporaryDirectory() as td:
        kp = pathlib.Path(td) / "kanban.json"
        seed = {
            "version": "0.2",
            "backend": {"driver": "local"},
            "meta": {
                "priorities": ["P0", "P1"],
                "categories": [],
                "columns": ["TODO", "DOING", "APPROVED", "BLOCKED"],
                "created_at": "x",
                "updated_at": "x",
            },
            "tasks": [],
        }
        kp.write_text(json.dumps(seed))

        cfg = {
            "boardUrl": "https://x/boards/1",
            "boardId": 1,
            "projectKey": "AGENT",
            "agentAccountId": "acct-x",
            "statusMap": {"TODO": "To Do", "DOING": "In Progress", "APPROVED": "Done"},
            "partial": True,
            "labelFallback": {"BLOCKED": "kanban:blocked"},
        }
        out = _setup_cmd(
            "write-backend",
            "--kanban-path",
            str(kp),
            "--jira-config-json",
            json.dumps(cfg),
        )
        assert out.returncode == 0, out.stderr
        on_disk = json.loads(kp.read_text())
        assert on_disk["backend"]["driver"] == "jira"
        assert on_disk["backend"]["jira"]["projectKey"] == "AGENT"
        # columns extended to canonical 6
        assert set(on_disk["meta"]["columns"]) == {
            "TODO", "DOING", "BLOCKED", "REVIEW", "APPROVED", "CANCELLED"
        }


# --- entry point --------------------------------------------------------


def main() -> int:
    cases = [
        ("client_429_retry_after", test_client_429_retry_after),
        ("client_5xx_exponential", test_client_5xx_exponential),
        ("client_401_immediate", test_client_401_immediate),
        ("client_max_retries_exhausted", test_client_max_retries_exhausted),
        ("adf_round_trip", test_adf_round_trip),
        ("dispatch_to_jira_driver", test_dispatch_to_jira_driver),
        ("list_tasks_builds_jql", test_list_tasks_builds_jql),
        ("transition_resolves_id", test_transition_resolves_id),
        ("transition_unknown_column_raises", test_transition_unknown_column_raises),
        ("post_comment_prefixes", test_post_comment_prefixes),
        ("list_comments_parses_prefix", test_list_comments_parses_prefix),
        ("parse_board_url", test_parse_board_url),
        ("write_backend", test_write_backend),
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
    print("phase2: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
