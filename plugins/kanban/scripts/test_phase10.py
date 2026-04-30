#!/usr/bin/env python3
"""Phase 10 regression checks for kanban v0.3.3 — `--blocked-by` issue links.

Closes issue #8: `/kanban:block` now accepts `--blocked-by KEY[,KEY,...]`
and creates Jira "Blocks" issue links before applying the status
transition. The link points from the blocker (inwardIssue) to the card
being blocked (outwardIssue), so Jira's "Linked work items" panel and
JQL `issueLinkType` queries see the dependency.

Cases:
  (a) jira_client.create_issue_link payload + endpoint
  (b) _issue_to_task surfaces "Blocks" inwardIssue keys as Task.depends
  (c) _link_blockers validates key format (rejects bad shapes)
  (d) _link_blockers rejects self-block (key blocks itself)
  (e) _link_blockers idempotent: skips already-linked blockers (no POST)
  (f) _link_blockers raises before transition when create_issue_link fails
       (issue #8 invariant: don't leave the card half-blocked)
  (g) transition(BLOCKED, blocked_by=[...]) creates links + transitions
  (h) transition(BLOCKED) without blocked_by doesn't touch issueLink endpoint
       (back-compat with v0.3.1)
  (i) cmd_transition with --blocked-by parses comma list, passes to driver
  (j) cmd_transition rejects --blocked-by when --to != BLOCKED
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"
sys.path.insert(0, str(REPO / "plugins" / "kanban"))

from lib.jira_client import JiraClient, _Response, JiraError  # noqa: E402

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


def _seed_jira_data():
    return {
        "version": "0.2",
        "backend": {
            "driver": "jira",
            "jira": {
                "projectKey": "AGENT",
                "boardId": 1,
                "agentAccountId": "shared-agent",
                "transitions": {
                    "TODO":      {"status": "Selected for Development"},
                    "DOING":     {"status": "In Progress"},
                    "BLOCKED":   {"status": "In Progress",
                                  "addLabels": ["kanban:blocked"]},
                    "DONE":      {"status": "Done"},
                },
            },
        },
        "meta": {"priorities": ["P0"], "categories": [],
                 "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"],
                 "created_at": "x", "updated_at": "x"},
        "tasks": [],
    }


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
    drv._client = JiraClient(
        drv.base_url, drv.email, drv._token,
        transport=_mock_transport(queue, calls), sleep=lambda _: None,
    )


def _issue(key, status="In Progress", labels=(), issuelinks=None):
    return {
        "key": key,
        "fields": {
            "summary": key,
            "status": {"name": status},
            "priority": {"name": "P1"},
            "assignee": None,
            "labels": list(labels),
            "created": "x", "updated": "y",
            "issuelinks": list(issuelinks or []),
        },
    }


# --- jira_client ---------------------------------------------------------


def test_create_issue_link_payload():
    queue = [_Response(201, b"", {})]
    calls = []
    c = JiraClient("https://x.atlassian.net", "a@b", "tok",
                   transport=_mock_transport(queue, calls), sleep=lambda _: None)
    c.create_issue_link(type_name="Blocks",
                        inward_key="DMI-1099", outward_key="DMI-200")
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/rest/api/3/issueLink")
    sent = json.loads(calls[0]["body"])
    assert sent == {
        "type": {"name": "Blocks"},
        "inwardIssue": {"key": "DMI-1099"},
        "outwardIssue": {"key": "DMI-200"},
    }


# --- _issue_to_task surfaces depends from issuelinks --------------------


def test_issue_to_task_extracts_depends_from_blocks():
    with tempfile.TemporaryDirectory() as td:
        drv = _patched_driver(_seed_jira_data(), pathlib.Path(td))
        issue = _issue("AGENT-200", issuelinks=[
            # Blocks link, inwardIssue = blocker
            {"type": {"name": "Blocks"},
             "inwardIssue": {"key": "AGENT-100"}},
            # Same type, second blocker
            {"type": {"name": "Blocks"},
             "inwardIssue": {"key": "INFRA-7"}},
            # Outward direction (we block another) — not a depends
            {"type": {"name": "Blocks"},
             "outwardIssue": {"key": "AGENT-300"}},
            # Different link type — ignored
            {"type": {"name": "Relates"},
             "inwardIssue": {"key": "AGENT-50"}},
        ])
        t = drv._issue_to_task(issue)
        assert t.depends == ["AGENT-100", "INFRA-7"]


# --- _link_blockers validation -------------------------------------------


def test_link_blockers_rejects_invalid_format():
    with tempfile.TemporaryDirectory() as td:
        drv = _patched_driver(_seed_jira_data(), pathlib.Path(td))
        existing = drv._issue_to_task(_issue("AGENT-1"))
        for bad in ("agent-1", "AGENT-", "-1", "agent 1", "", None):
            try:
                drv._link_blockers(
                    drv._client_or_raise() if drv._token else None,  # never reached
                    "AGENT-1", [bad] if bad is not None else [None],  # type: ignore
                    existing,
                )
                assert False, f"should reject {bad!r}"
            except RuntimeError as e:
                assert "invalid blocker key" in str(e)


def test_link_blockers_rejects_self():
    with tempfile.TemporaryDirectory() as td:
        drv = _patched_driver(_seed_jira_data(), pathlib.Path(td))
        existing = drv._issue_to_task(_issue("AGENT-1"))
        try:
            drv._link_blockers(None, "AGENT-1", ["AGENT-1"], existing)  # type: ignore
            assert False
        except RuntimeError as e:
            assert "self-block" in str(e)


def test_link_blockers_idempotent_skips_existing():
    """When a card is already linked to a blocker, no POST is made."""
    with tempfile.TemporaryDirectory() as td:
        drv = _patched_driver(_seed_jira_data(), pathlib.Path(td))
        existing = drv._issue_to_task(_issue("AGENT-1", issuelinks=[
            {"type": {"name": "Blocks"}, "inwardIssue": {"key": "AGENT-99"}}
        ]))
        queue = []  # No requests should be made if everything is already linked
        calls = []
        _attach_mock(drv, queue, calls)
        drv._link_blockers(drv._client, "AGENT-1", ["AGENT-99"], existing)
        assert calls == []


def test_link_blockers_creates_only_new_ones():
    with tempfile.TemporaryDirectory() as td:
        drv = _patched_driver(_seed_jira_data(), pathlib.Path(td))
        existing = drv._issue_to_task(_issue("AGENT-1", issuelinks=[
            {"type": {"name": "Blocks"}, "inwardIssue": {"key": "AGENT-99"}}
        ]))
        # AGENT-99 already linked, AGENT-100 new
        queue = [_Response(201, b"", {})]
        calls = []
        _attach_mock(drv, queue, calls)
        drv._link_blockers(drv._client, "AGENT-1",
                           ["AGENT-99", "AGENT-100"], existing)
        assert len(calls) == 1
        sent = json.loads(calls[0]["body"])
        assert sent["inwardIssue"]["key"] == "AGENT-100"
        assert sent["outwardIssue"]["key"] == "AGENT-1"


def test_link_blockers_404_raises_before_transition():
    with tempfile.TemporaryDirectory() as td:
        drv = _patched_driver(_seed_jira_data(), pathlib.Path(td))
        existing = drv._issue_to_task(_issue("AGENT-1"))
        queue = [_Response(404, b'{"errorMessages":["Issue does not exist"]}', {})]
        calls = []
        _attach_mock(drv, queue, calls)
        try:
            drv._link_blockers(drv._client, "AGENT-1", ["TYPO-9999"], existing)
            assert False, "should have raised"
        except RuntimeError as e:
            assert "TYPO-9999" in str(e)
            assert "could not be linked" in str(e)


# --- transition() integration --------------------------------------------


def test_transition_blocked_creates_links_then_transitions():
    """transition(BLOCKED, blocked_by=[...]) order: pre-flight read →
    create issue links → status transition (if needed) → label add → comment."""
    with tempfile.TemporaryDirectory() as td:
        drv = _patched_driver(_seed_jira_data(), pathlib.Path(td))
        # Pre-flight: card in 'Selected for Development', no labels, no links
        pre = _issue("AGENT-1", status="Selected for Development")
        # Final read post-transition: now in 'In Progress' + kanban:blocked
        post = _issue("AGENT-1", status="In Progress",
                      labels=["kanban:blocked"],
                      issuelinks=[{"type": {"name": "Blocks"},
                                   "inwardIssue": {"key": "AGENT-99"}}])
        # Mid-flight: also list_comments will be called by post_comment for the
        # Blocked: <reason> system comment. The driver fires add_comment.

        queue = [
            # 1) pre-flight get_task
            _Response(200, json.dumps(pre).encode(), {}),
            # 2) create_issue_link for AGENT-99
            _Response(201, b"", {}),
            # 3) get_transitions (needed because pre status != target)
            _Response(200, json.dumps(
                {"transitions": [{"id": "21", "to": {"name": "In Progress"}}]}
            ).encode(), {}),
            # 4) transition_issue
            _Response(204, b"", {}),
            # 5) PUT labels (add kanban:blocked)
            _Response(204, b"", {}),
            # 6) post_comment (add_comment) — for the Blocked: <reason>
            _Response(201, b'{"created":"x"}', {}),
            # 7) final get_task refresh
            _Response(200, json.dumps(post).encode(), {}),
        ]
        calls = []
        _attach_mock(drv, queue, calls)
        t = drv.transition("AGENT-1", "BLOCKED",
                           reason="Waiting on schema decision",
                           blocked_by=["AGENT-99"])
        assert t.column == "BLOCKED"
        assert "AGENT-99" in t.depends

        # Order check: issueLink POST happens BEFORE transition POST.
        link_idx = next(i for i, c in enumerate(calls)
                        if c["url"].endswith("/issueLink"))
        trans_idx = next(i for i, c in enumerate(calls)
                         if "/transitions" in c["url"]
                         and c["method"] == "POST")
        assert link_idx < trans_idx, "issueLink must precede transition"


def test_transition_blocked_without_blocked_by_skips_links():
    """When --blocked-by is absent, no /issueLink call is made."""
    with tempfile.TemporaryDirectory() as td:
        drv = _patched_driver(_seed_jira_data(), pathlib.Path(td))
        pre = _issue("AGENT-1", status="In Progress")  # already at target
        post = _issue("AGENT-1", status="In Progress",
                      labels=["kanban:blocked"])
        queue = [
            _Response(200, json.dumps(pre).encode(), {}),    # pre-flight
            # No issueLink, no get_transitions (status already correct)
            _Response(204, b"", {}),                         # PUT labels
            _Response(201, b'{"created":"x"}', {}),          # comment
            _Response(200, json.dumps(post).encode(), {}),   # final get
        ]
        calls = []
        _attach_mock(drv, queue, calls)
        t = drv.transition("AGENT-1", "BLOCKED",
                           reason="Waiting on input")
        assert t.column == "BLOCKED"
        assert all("/issueLink" not in c["url"] for c in calls)


def test_transition_link_failure_aborts_before_status_change():
    """If create_issue_link fails, the status transition is NOT attempted."""
    with tempfile.TemporaryDirectory() as td:
        drv = _patched_driver(_seed_jira_data(), pathlib.Path(td))
        pre = _issue("AGENT-1", status="Selected for Development")
        queue = [
            _Response(200, json.dumps(pre).encode(), {}),         # pre-flight
            _Response(404, b'{"errorMessages":["Issue does not exist"]}', {}),  # link 404
        ]
        calls = []
        _attach_mock(drv, queue, calls)
        try:
            drv.transition("AGENT-1", "BLOCKED",
                           reason="x", blocked_by=["TYPO-9999"])
            assert False, "should have raised"
        except RuntimeError as e:
            assert "TYPO-9999" in str(e)
        # No transitions endpoint hit, no PUT labels, no comment add — the
        # card stays in its previous state.
        assert all("/transitions" not in c["url"] for c in calls)
        assert all(c["method"] != "PUT" for c in calls)


# --- cmd_transition CLI integration --------------------------------------


def test_cmd_transition_passes_blocked_by_to_driver():
    """End-to-end: --blocked-by goes through the helper into driver kwargs."""
    with tempfile.TemporaryDirectory() as td:
        kp = pathlib.Path(td) / "kanban.json"
        kp.write_text(json.dumps(_seed_jira_data()))

        # Patch get_driver to a stub that records kwargs
        captured = {}
        from drivers.base import Task

        class StubDriver:
            name = "jira"

            def transition(self, key, to_column, **kwargs):
                captured["key"] = key
                captured["to"] = to_column
                captured["kwargs"] = kwargs
                return Task(id=key, title="x", column=to_column,
                            priority="P1", created="x", updated="y",
                            depends=["DMI-1099"],
                            custom={"raw_status": "In Progress"})

        # cmd_transition does `from drivers import get_driver` inside, so
        # we monkey-patch the loaded module
        import drivers as _drv_mod
        _orig_get = _drv_mod.get_driver
        _drv_mod.get_driver = lambda data, root: StubDriver()
        try:
            from io import StringIO
            old = sys.stdout
            sys.stdout = StringIO()
            try:
                class A:
                    kanban_path = str(kp)
                    key = "DMI-200"
                    to = "BLOCKED"
                    reason = "waiting on AuditPort"
                    blocked_by = "DMI-1099, INFRA-7"
                rc = _jira_setup.cmd_transition(A())
                out = sys.stdout.getvalue()
            finally:
                sys.stdout = old
        finally:
            _drv_mod.get_driver = _orig_get
        assert rc == 0, out
        j = json.loads(out)
        assert j["ok"] is True
        assert j["depends"] == ["DMI-1099"]
        assert captured["kwargs"]["blocked_by"] == ["DMI-1099", "INFRA-7"]
        assert captured["kwargs"]["reason"] == "waiting on AuditPort"


def test_cmd_transition_rejects_blocked_by_without_blocked_target():
    """--blocked-by --to=DOING is a usage error."""
    with tempfile.TemporaryDirectory() as td:
        kp = pathlib.Path(td) / "kanban.json"
        kp.write_text(json.dumps(_seed_jira_data()))
        from io import StringIO
        old = sys.stdout
        sys.stdout = StringIO()
        try:
            class A:
                kanban_path = str(kp); key = "DMI-200"
                to = "DOING"; reason = None
                blocked_by = "DMI-1099"
            try:
                _jira_setup.cmd_transition(A())
                rc = 0
            except SystemExit as e:
                rc = e.code
            out = sys.stdout.getvalue()
        finally:
            sys.stdout = old
        assert rc != 0
        j = json.loads(out)
        assert j["ok"] is False
        assert "BLOCKED" in j["error"]


# --- entry point ---------------------------------------------------------


def main() -> int:
    cases = [
        ("create_issue_link_payload", test_create_issue_link_payload),
        ("issue_to_task_extracts_depends_from_blocks",
         test_issue_to_task_extracts_depends_from_blocks),
        ("link_blockers_rejects_invalid_format",
         test_link_blockers_rejects_invalid_format),
        ("link_blockers_rejects_self", test_link_blockers_rejects_self),
        ("link_blockers_idempotent_skips_existing",
         test_link_blockers_idempotent_skips_existing),
        ("link_blockers_creates_only_new_ones",
         test_link_blockers_creates_only_new_ones),
        ("link_blockers_404_raises_before_transition",
         test_link_blockers_404_raises_before_transition),
        ("transition_blocked_creates_links_then_transitions",
         test_transition_blocked_creates_links_then_transitions),
        ("transition_blocked_without_blocked_by_skips_links",
         test_transition_blocked_without_blocked_by_skips_links),
        ("transition_link_failure_aborts_before_status_change",
         test_transition_link_failure_aborts_before_status_change),
        ("cmd_transition_passes_blocked_by_to_driver",
         test_cmd_transition_passes_blocked_by_to_driver),
        ("cmd_transition_rejects_blocked_by_without_blocked_target",
         test_cmd_transition_rejects_blocked_by_without_blocked_target),
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
    print("phase10: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
