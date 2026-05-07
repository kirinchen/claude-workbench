#!/usr/bin/env python3
"""Phase 18 regression checks for kanban v0.3.11 — reconcile + sync drift reminder.

Closes #21. New diagnostic surfaces cards invisible to the canonical
kanban view: unmapped Jira statuses (cards drifted to a status not in
DSL transitions) + missing AP (open cards with no AP custom field).

Cases:
  (a) _ap_cf_jql_id strips `customfield_` and validates digits-only
  (b) _detect_reconcile happy path: groups my-AP cards by unmapped
      status; missing-AP query collects keys
  (c) _detect_reconcile: cards with mapped status are NOT flagged
  (d) _detect_reconcile: graceful degrade when no repo_ap (skip query 1)
      or no ap_field_id (skip both)
  (e) cmd_reconcile: returns clean hint when no drift
  (f) cmd_reconcile: hint mentions both kinds when both present
  (g) cmd_sync_summary: appends drift one-liner when reconcile finds
      issues; absent when clean
  (h) cmd_sync_summary: drift detection failure is silent (best-effort)
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"
sys.path.insert(0, str(REPO / "plugins" / "kanban"))

from lib.jira_client import JiraClient, _Response  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "jira_setup_mod", str(PLUGIN / "scripts" / "jira_setup.py")
)
_jira_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_jira_setup)  # type: ignore[union-attr]


def _mock_client(queue, calls):
    def t(method, url, headers, body):
        calls.append({"method": method, "url": url, "body": body})
        if not queue:
            raise AssertionError(f"queue empty for {method} {url}")
        return queue.pop(0)
    return JiraClient(
        "https://x", "a@b", "tok",
        transport=t, sleep=lambda _: None,
    )


def _capture(fn, args):
    from io import StringIO
    old = sys.stdout
    sys.stdout = StringIO()
    try:
        try:
            rc = fn(args)
        except SystemExit as e:
            rc = e.code
        out = sys.stdout.getvalue()
    finally:
        sys.stdout = old
    return rc, out


# --- _ap_cf_jql_id -----------------------------------------------------


def test_ap_cf_jql_id():
    fn = _jira_setup._ap_cf_jql_id
    assert fn("customfield_10042") == "10042"
    assert fn("customfield_99") == "99"
    assert fn(None) is None
    assert fn("") is None
    assert fn("not-a-customfield") is None
    assert fn("customfield_abc") is None
    assert fn("customfield_") is None


# --- _detect_reconcile -------------------------------------------------


_TRANSITIONS = {
    "TODO": {"status": "Selected for Development"},
    "DOING": {"status": "In Progress"},
    "APPROVED": {"status": "Done"},
}


def test_detect_reconcile_groups_unmapped():
    """My-AP cards with status outside the mapped set are flagged.

    v0.3.12: filtering moved server-side via JQL `status not in (...)`
    (locale-immune — see #17), so the mock only returns the unmapped
    cards. Mapped cards never reach the client.
    """
    queue = [
        # Query 1: my-AP cards in unmapped statuses (server-side filter)
        _Response(200, json.dumps({
            "issues": [
                {"key": "AGENT-201",
                 "fields": {"status": {"name": "TO PROGRESS"}}},
                {"key": "AGENT-202",
                 "fields": {"status": {"name": "TO PROGRESS"}}},
                {"key": "AGENT-300",
                 "fields": {"status": {"name": "Backlog"}}},
            ],
        }).encode(), {}),
        # Query 2: missing-AP
        _Response(200, json.dumps({"issues": [
            {"key": "AGENT-401", "fields": {"status": {"name": "Backlog"}}},
            {"key": "AGENT-402", "fields": {"status": {"name": "Done"}}},
        ]}).encode(), {}),
    ]
    calls = []
    c = _mock_client(queue, calls)
    unmapped, missing, errs = _jira_setup._detect_reconcile(
        c, "AGENT", _TRANSITIONS,
        ap_field_id="customfield_10042",
        repo_ap="agent-fin",
    )
    assert errs == []
    assert sorted(unmapped.keys()) == ["Backlog", "TO PROGRESS"]
    assert unmapped["TO PROGRESS"] == ["AGENT-201", "AGENT-202"]
    assert unmapped["Backlog"] == ["AGENT-300"]
    assert missing == ["AGENT-401", "AGENT-402"]
    # Query 1 must include the locale-immune `status not in (...)` filter
    # listing every DSL-mapped status name (the heart of #17 fix).
    q1_payload = json.loads((calls[0]["body"] or b"{}").decode())
    q1_jql = q1_payload.get("jql", "")
    assert "status not in (" in q1_jql, q1_jql
    for st in ("Selected for Development", "In Progress", "Done"):
        assert f'"{st}"' in q1_jql, q1_jql


def test_detect_reconcile_skips_when_no_repo_ap():
    """Without a repo_ap, the my-AP query is skipped (we don't know
    whose cards to look for); missing-AP still runs."""
    queue = [
        # Only the missing-AP query
        _Response(200, json.dumps({"issues": [
            {"key": "AGENT-100", "fields": {"status": {"name": "x"}}},
        ]}).encode(), {}),
    ]
    calls = []
    c = _mock_client(queue, calls)
    unmapped, missing, errs = _jira_setup._detect_reconcile(
        c, "AGENT", _TRANSITIONS,
        ap_field_id="customfield_10042",
        repo_ap=None,
    )
    assert unmapped == {}
    assert missing == ["AGENT-100"]
    assert errs == []
    # Only one JQL fired
    assert len(calls) == 1


def test_detect_reconcile_skips_when_no_ap_field_id():
    """Without a configured AP field, both queries are skipped — there's
    no way to filter by AP at all."""
    queue: list[_Response] = []  # no requests expected
    calls = []
    c = _mock_client(queue, calls)
    unmapped, missing, errs = _jira_setup._detect_reconcile(
        c, "AGENT", _TRANSITIONS,
        ap_field_id=None, repo_ap="agent-fin",
    )
    assert unmapped == {} and missing == [] and errs == []
    assert calls == []


def test_detect_reconcile_collects_query_errors():
    """Either query failing goes into errors[] but the other still
    runs. Use 404 (non-retryable) to avoid the JiraClient backoff loop."""
    queue = [
        _Response(404, b'{"errorMessages":["boom"]}', {}),
        # missing-AP query still runs
        _Response(404, b'{"errorMessages":["boom2"]}', {}),
    ]
    calls = []
    c = _mock_client(queue, calls)
    unmapped, missing, errs = _jira_setup._detect_reconcile(
        c, "AGENT", _TRANSITIONS,
        ap_field_id="customfield_10042",
        repo_ap="agent-fin",
    )
    assert unmapped == {} and missing == []
    assert len(errs) == 2


# --- cmd_reconcile ------------------------------------------------------


def _seed_kanban(td, *, with_agent_account=True):
    """Seed kanban.json. By default includes agentAccountId. Tests that
    exercise cmd_sync_summary's reconcile path pass with_agent_account=False
    so the mention-detection branch (which also uses _client_from_env_or_none)
    is skipped — keeps the queue accounting clean."""
    jira_cfg = {
        "boardUrl": "https://x/jira/projects/AGENT/boards/1",
        "boardId": 1, "projectKey": "AGENT",
        "transitions": _TRANSITIONS,
        "ap": {"fieldId": "customfield_10042",
               "fieldName": "Claude Agent",
               "registered": ["agent-fin"]},
    }
    if with_agent_account:
        jira_cfg["agentAccountId"] = "5e-bot"
    p = pathlib.Path(td) / "kanban.json"
    p.write_text(json.dumps({
        "version": "0.2",
        "backend": {"driver": "jira", "jira": jira_cfg},
        "meta": {"priorities": ["P0"], "categories": [],
                 "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "APPROVED", "CANCELLED"],
                 "created_at": "x", "updated_at": "x"},
        "tasks": [],
    }))
    (p.parent / ".claude").mkdir()
    (p.parent / ".claude" / "kanban-agent.json").write_text(
        json.dumps({"ap": "agent-fin"}) + "\n"
    )
    return p


def _patch_client(client):
    orig = _jira_setup._client_from_env
    _jira_setup._client_from_env = lambda: client
    return orig


def _restore_client(orig):
    _jira_setup._client_from_env = orig


def _patch_client_or_none(client):
    orig = _jira_setup._client_from_env_or_none
    _jira_setup._client_from_env_or_none = lambda: client
    return orig


def _restore_client_or_none(orig):
    _jira_setup._client_from_env_or_none = orig


def test_reconcile_clean():
    """When no drift, hint is positive. (v0.3.12: server-side JQL filter
    means a clean state returns empty in query 1.)"""
    queue = [
        # Query 1 — server filter `status not in (mapped)` excludes everything
        _Response(200, json.dumps({"issues": []}).encode(), {}),
        # Query 2 — empty
        _Response(200, json.dumps({"issues": []}).encode(), {}),
    ]
    calls = []
    c = _mock_client(queue, calls)
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_kanban(td)
        orig = _patch_client(c)
        try:
            class A: kanban_path = str(kp)
            rc, out = _capture(_jira_setup.cmd_reconcile, A())
        finally:
            _restore_client(orig)
        assert rc == 0
        j = json.loads(out)
        assert j["ok"] is True
        assert j["totalUnmapped"] == 0
        assert j["totalMissingAp"] == 0
        assert "No drift" in j["hint"]


def test_reconcile_hint_mentions_both_kinds():
    """Hint mentions both unmapped and missing when both present."""
    queue = [
        # 2 in unmapped status
        _Response(200, json.dumps({"issues": [
            {"key": "A-1", "fields": {"status": {"name": "TO PROGRESS"}}},
            {"key": "A-2", "fields": {"status": {"name": "TO PROGRESS"}}},
        ]}).encode(), {}),
        # 3 missing AP
        _Response(200, json.dumps({"issues": [
            {"key": "A-9", "fields": {"status": {"name": "x"}}},
            {"key": "A-10", "fields": {"status": {"name": "y"}}},
            {"key": "A-11", "fields": {"status": {"name": "z"}}},
        ]}).encode(), {}),
    ]
    calls = []
    c = _mock_client(queue, calls)
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_kanban(td)
        orig = _patch_client(c)
        try:
            class A: kanban_path = str(kp)
            rc, out = _capture(_jira_setup.cmd_reconcile, A())
        finally:
            _restore_client(orig)
        assert rc == 0
        j = json.loads(out)
        assert j["totalUnmapped"] == 2
        assert j["totalMissingAp"] == 3
        # Hint mentions both
        assert "unmapped" in j["hint"]
        assert "no AP" in j["hint"]


# --- cmd_sync_summary one-line drift reminder --------------------------


def test_sync_summary_appends_drift_reminder_when_present():
    """sync's reconcile-via-_client_from_env_or_none surfaces a single
    summary line so SessionStart users see the drift signal without
    needing to remember /kanban:reconcile."""
    # We need the sync to:
    # 1. Run its existing flow (open cards via driver) — handled by stub driver
    # 2. Call _detect_reconcile via _client_from_env_or_none — patch a mock
    queue = [
        # reconcile query 1 — 1 unmapped
        _Response(200, json.dumps({"issues": [
            {"key": "A-9", "fields": {"status": {"name": "TO PROGRESS"}}},
        ]}).encode(), {}),
        # reconcile query 2 — empty
        _Response(200, json.dumps({"issues": []}).encode(), {}),
    ]
    calls = []
    rec_client = _mock_client(queue, calls)

    # Stub driver returns no open cards (sync's main loop is a no-op for
    # this test — we're focused on the reminder line)
    class _StubDrv:
        name = "jira"
        def list_tasks(self, filter=None):
            return []
        def list_comments(self, key):
            return []

    with tempfile.TemporaryDirectory() as td:
        kp = _seed_kanban(td, with_agent_account=False)
        # Mark board-config cache as freshly synced so cmd_sync_summary's
        # passive-sync entry (added in 0.3.26) skips and the queue we
        # set up below is consumed exactly by the reconcile path.
        from datetime import datetime, timezone
        from lib import board_config as _bc
        _bc.mark_synced(pathlib.Path(td), datetime.now(timezone.utc))
        import drivers as _drv_mod
        d_orig = _drv_mod.get_driver
        _drv_mod.get_driver = lambda data, root: _StubDrv()
        rc_orig = _patch_client_or_none(rec_client)
        try:
            class A: kanban_path = str(kp)
            rc, out = _capture(_jira_setup.cmd_sync_summary, A())
        finally:
            _drv_mod.get_driver = d_orig
            _restore_client_or_none(rc_orig)
        assert rc == 0, out
        j = json.loads(out)
        # The summary text should contain the drift reminder one-liner
        assert "[drift" in j["summary"]
        assert "/kanban:reconcile" in j["summary"]


def test_sync_summary_omits_drift_reminder_when_clean():
    queue = [
        _Response(200, json.dumps({"issues": []}).encode(), {}),
        _Response(200, json.dumps({"issues": []}).encode(), {}),
    ]
    calls = []
    rec_client = _mock_client(queue, calls)

    class _StubDrv:
        name = "jira"
        def list_tasks(self, filter=None): return []
        def list_comments(self, key): return []

    with tempfile.TemporaryDirectory() as td:
        kp = _seed_kanban(td, with_agent_account=False)
        from datetime import datetime, timezone
        from lib import board_config as _bc
        _bc.mark_synced(pathlib.Path(td), datetime.now(timezone.utc))
        import drivers as _drv_mod
        d_orig = _drv_mod.get_driver
        _drv_mod.get_driver = lambda data, root: _StubDrv()
        rc_orig = _patch_client_or_none(rec_client)
        try:
            class A: kanban_path = str(kp)
            rc, out = _capture(_jira_setup.cmd_sync_summary, A())
        finally:
            _drv_mod.get_driver = d_orig
            _restore_client_or_none(rc_orig)
        j = json.loads(out)
        assert "[drift" not in j["summary"]


def test_sync_summary_drift_detection_silent_on_failure():
    """If reconcile detection fails (network, permission, etc.), the
    sync summary still prints the existing blocks — no exception leaks.
    Use 404 (non-retryable) to keep the test deterministic."""
    queue = [
        _Response(404, b'{"errorMessages":["fail"]}', {}),
        _Response(404, b'{"errorMessages":["fail"]}', {}),
    ]
    calls = []
    rec_client = _mock_client(queue, calls)

    class _StubDrv:
        name = "jira"
        def list_tasks(self, filter=None): return []
        def list_comments(self, key): return []

    with tempfile.TemporaryDirectory() as td:
        kp = _seed_kanban(td, with_agent_account=False)
        from datetime import datetime, timezone
        from lib import board_config as _bc
        _bc.mark_synced(pathlib.Path(td), datetime.now(timezone.utc))
        import drivers as _drv_mod
        d_orig = _drv_mod.get_driver
        _drv_mod.get_driver = lambda data, root: _StubDrv()
        rc_orig = _patch_client_or_none(rec_client)
        try:
            class A: kanban_path = str(kp)
            rc, out = _capture(_jira_setup.cmd_sync_summary, A())
        finally:
            _drv_mod.get_driver = d_orig
            _restore_client_or_none(rc_orig)
        # Should not crash; drift line absent
        assert rc == 0
        j = json.loads(out)
        assert "[drift" not in j["summary"]


def main() -> int:
    cases = [
        ("ap_cf_jql_id", test_ap_cf_jql_id),
        ("detect_reconcile_groups_unmapped", test_detect_reconcile_groups_unmapped),
        ("detect_reconcile_skips_when_no_repo_ap",
         test_detect_reconcile_skips_when_no_repo_ap),
        ("detect_reconcile_skips_when_no_ap_field_id",
         test_detect_reconcile_skips_when_no_ap_field_id),
        ("detect_reconcile_collects_query_errors",
         test_detect_reconcile_collects_query_errors),
        ("reconcile_clean", test_reconcile_clean),
        ("reconcile_hint_mentions_both_kinds",
         test_reconcile_hint_mentions_both_kinds),
        ("sync_summary_appends_drift_reminder_when_present",
         test_sync_summary_appends_drift_reminder_when_present),
        ("sync_summary_omits_drift_reminder_when_clean",
         test_sync_summary_omits_drift_reminder_when_clean),
        ("sync_summary_drift_detection_silent_on_failure",
         test_sync_summary_drift_detection_silent_on_failure),
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
    print("phase18: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
