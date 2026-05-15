#!/usr/bin/env python3
"""Phase 33 regression checks for kanban v0.3.28 — Jira mutation
primitives (#55).

PR adds five new jira_setup subcommands wired through new driver
methods so agents stop bypassing to direct Jira REST calls. Cases:

  (a) cmd_update_description happy path emits a PUT with an ADF body.
  (b) cmd_update_description --body-file - reads stdin.
  (c) cmd_update_description with a different repo AP surfaces
      `warnings: ["ap-mismatch"]` and still proceeds (non-blocking).
  (d) cmd_update_summary writes a PUT with the new summary.
  (e) cmd_add_label merges, then PUTs the union of existing + new
      labels (preserves order, dedupes).
  (f) cmd_add_label with backend.jira.labels.allowed rejects unknown
      labels.
  (g) cmd_remove_label drops only the requested labels.
  (h) cmd_delete_issue refuses without --confirm (kind=needs-confirm).
  (i) cmd_delete_issue with --confirm writes the audit snapshot, then
      DELETEs. The audit file survives the deletion as the only trail.
  (j) cmd_delete_issue refuses a card APPROVED within 7d
      (kind=recent-approved); --force lets it through.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
from datetime import datetime, timedelta, timezone

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"
sys.path.insert(0, str(REPO / "plugins" / "kanban"))

from lib.jira_client import JiraClient, _Response  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "jira_setup_mod", str(PLUGIN / "scripts" / "jira_setup.py")
)
_jira_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_jira_setup)  # type: ignore[union-attr]


# --- mock infra ---------------------------------------------------------


def _capture(fn, args, *, stdin: str | None = None):
    from io import StringIO
    old_out, old_err, old_in = sys.stdout, sys.stderr, sys.stdin
    sys.stdout = StringIO()
    sys.stderr = StringIO()
    if stdin is not None:
        sys.stdin = StringIO(stdin)
    try:
        try:
            rc = fn(args)
        except SystemExit as e:
            rc = e.code
        out = sys.stdout.getvalue()
        err = sys.stderr.getvalue()
    finally:
        sys.stdout, sys.stderr, sys.stdin = old_out, old_err, old_in
    return rc, out, err


def _mock_client(queue, calls):
    def t(method, url, headers, body):
        calls.append({
            "method": method,
            "url": url,
            "body": json.loads(body.decode()) if body else None,
        })
        if not queue:
            raise AssertionError(f"queue empty for {method} {url}")
        return queue.pop(0)
    return JiraClient("https://x", "a@b", "tok",
                      transport=t, sleep=lambda _: None)


def _patch_driver_client(client):
    """Force JiraDriver._client_or_raise to return our mocked client."""
    from drivers import jira as _jira_mod
    orig = _jira_mod.JiraDriver._client_or_raise
    _jira_mod.JiraDriver._client_or_raise = lambda self: client  # type: ignore[method-assign]
    return orig


def _restore_driver_client(orig):
    from drivers import jira as _jira_mod
    _jira_mod.JiraDriver._client_or_raise = orig  # type: ignore[method-assign]


def _seed_kanban(td: pathlib.Path, *, labels_allowed=None, ap_field=True) -> pathlib.Path:
    p = td / "kanban.json"
    jira_cfg = {
        "boardUrl": "https://x/jira/projects/BZK/boards/1",
        "boardId": 1, "projectKey": "BZK",
        "transitions": {
            "TODO": {"status": "To Do"},
            "DOING": {"status": "In Progress"},
            "APPROVED": {"status": "Done"},
        },
    }
    if ap_field:
        jira_cfg["ap"] = {
            "fieldId": "customfield_10042",
            "fieldName": "Claude Agent",
            "registered": ["alice-bot", "bob-bot"],
        }
    if labels_allowed is not None:
        jira_cfg["labels"] = {"allowed": labels_allowed}
    p.write_text(json.dumps({
        "version": "0.2",
        "backend": {"driver": "jira", "jira": jira_cfg},
        "meta": {"priorities": ["P0"], "categories": [],
                 "columns": ["TODO", "DOING", "BLOCKED", "REVIEW",
                             "APPROVED", "CANCELLED"],
                 "created_at": "x", "updated_at": "x"},
        "tasks": [],
    }))
    return p


def _seed_agent(td: pathlib.Path, ap: str) -> None:
    """Write .claude/kanban-agent.json so _read_repo_ap picks up `ap`."""
    agent_dir = td / ".claude"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "kanban-agent.json").write_text(json.dumps({"ap": ap}))


def _issue(key: str, *, status="In Progress", labels=None,
           ap=None, completed=None) -> dict:
    fields = {
        "summary": "test card",
        "status": {"name": status, "statusCategory": {"key": "indeterminate"}},
        "priority": {"name": "P0"},
        "assignee": None,
        "labels": list(labels or []),
        "created": "2026-05-01T00:00:00.000+0000",
        "updated": completed or "2026-05-01T00:00:00.000+0000",
        "description": None,
        "issuelinks": [],
    }
    if ap is not None:
        fields["customfield_10042"] = {"value": ap}
    return {"key": key, "fields": fields}


# --- (a) update-description happy path ----------------------------------


def test_update_description_happy_path():
    queue = [
        # driver.update_description -> client.update_issue (PUT)
        _Response(204, b"", {}),
        # driver.update_description -> get_task (GET) at end of method
        _Response(200, json.dumps(_issue("BZK-1")).encode(), {}),
    ]
    calls: list[dict] = []
    client = _mock_client(queue, calls)
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_kanban(td)
        orig = _patch_driver_client(client)
        try:
            class A:
                kanban_path = str(kp)
                key = "BZK-1"
                body = "new description text"
                body_file = None
                format = "text"
                override_ap = False
            rc, out, err = _capture(_jira_setup.cmd_update_description, A())
        finally:
            _restore_driver_client(orig)
        assert rc == 0, (out, err)
        j = json.loads(out)
        assert j == {"ok": True, "key": "BZK-1", "warnings": []}
        # First call is the PUT carrying the ADF description
        put_call = calls[0]
        assert put_call["method"] == "PUT"
        assert put_call["url"].endswith("/rest/api/3/issue/BZK-1")
        adf = put_call["body"]["fields"]["description"]
        assert adf["type"] == "doc"
        # Text round-trip through ADF preserves the body
        flat = json.dumps(adf)
        assert "new description text" in flat


# --- (b) --body-file - reads stdin --------------------------------------


def test_update_description_from_stdin():
    queue = [
        _Response(204, b"", {}),
        _Response(200, json.dumps(_issue("BZK-1")).encode(), {}),
    ]
    calls: list[dict] = []
    client = _mock_client(queue, calls)
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_kanban(td)
        orig = _patch_driver_client(client)
        try:
            class A:
                kanban_path = str(kp)
                key = "BZK-1"
                body = None
                body_file = "-"
                format = "text"
                override_ap = False
            rc, out, err = _capture(
                _jira_setup.cmd_update_description, A(),
                stdin="piped body from stdin",
            )
        finally:
            _restore_driver_client(orig)
        assert rc == 0, (out, err)
        flat = json.dumps(calls[0]["body"])
        assert "piped body from stdin" in flat


# --- (c) ap-mismatch warning is surfaced but non-blocking ---------------


def test_update_description_ap_mismatch_warning():
    queue = [
        # _ap_mismatch_warning -> driver.get_task (GET)
        _Response(200, json.dumps(_issue("BZK-1", ap="alice-bot")).encode(), {}),
        # driver.update_description -> PUT
        _Response(204, b"", {}),
        # driver.update_description -> final get_task GET
        _Response(200, json.dumps(_issue("BZK-1", ap="alice-bot")).encode(), {}),
    ]
    calls: list[dict] = []
    client = _mock_client(queue, calls)
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_kanban(td)
        _seed_agent(td, "bob-bot")
        orig = _patch_driver_client(client)
        try:
            class A:
                kanban_path = str(kp)
                key = "BZK-1"
                body = "edit by bob"
                body_file = None
                format = "text"
                override_ap = False
            rc, out, err = _capture(_jira_setup.cmd_update_description, A())
        finally:
            _restore_driver_client(orig)
        assert rc == 0, (out, err)
        j = json.loads(out)
        assert j["warnings"] == ["ap-mismatch"]
        # PUT still happened — warning is non-blocking
        methods = [c["method"] for c in calls]
        assert "PUT" in methods


# --- (d) update-summary -------------------------------------------------


def test_update_summary_happy_path():
    queue = [
        _Response(204, b"", {}),
        _Response(200, json.dumps(_issue("BZK-1")).encode(), {}),
    ]
    calls: list[dict] = []
    client = _mock_client(queue, calls)
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_kanban(td)
        orig = _patch_driver_client(client)
        try:
            class A:
                kanban_path = str(kp)
                key = "BZK-1"
                summary = "renamed title"
                override_ap = False
            rc, out, err = _capture(_jira_setup.cmd_update_summary, A())
        finally:
            _restore_driver_client(orig)
        assert rc == 0, (out, err)
        put_call = calls[0]
        assert put_call["method"] == "PUT"
        assert put_call["body"]["fields"]["summary"] == "renamed title"


# --- (e) add-label merges --------------------------------------------------


def test_add_label_merges_with_existing():
    queue = [
        # driver.update_labels -> get_task (read existing)
        _Response(200,
                  json.dumps(_issue("BZK-1", labels=["existing"])).encode(),
                  {}),
        # driver.update_labels -> update_issue PUT (merged list)
        _Response(204, b"", {}),
        # driver.update_labels -> final get_task
        _Response(200,
                  json.dumps(_issue("BZK-1",
                                    labels=["existing", "kanban:cancelled"])).encode(),
                  {}),
    ]
    calls: list[dict] = []
    client = _mock_client(queue, calls)
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_kanban(td)
        orig = _patch_driver_client(client)
        try:
            class A:
                kanban_path = str(kp)
                key = "BZK-1"
                label = ["kanban:cancelled"]
                override_ap = False
            rc, out, err = _capture(_jira_setup.cmd_add_label, A())
        finally:
            _restore_driver_client(orig)
        assert rc == 0, (out, err)
        # PUT body has merged label list (existing preserved, new appended)
        put = next(c for c in calls if c["method"] == "PUT")
        assert put["body"]["fields"]["labels"] == ["existing", "kanban:cancelled"]
        # Response surfaces the post-update labels
        j = json.loads(out)
        assert j["labels"] == ["existing", "kanban:cancelled"]


# --- (f) allowlist rejects unknown labels --------------------------------


def test_add_label_allowlist_rejects_unknown():
    queue: list = []  # no Jira calls expected
    calls: list[dict] = []
    client = _mock_client(queue, calls)
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_kanban(td, labels_allowed=["kanban:cancelled", "wontfix"])
        orig = _patch_driver_client(client)
        try:
            class A:
                kanban_path = str(kp)
                key = "BZK-1"
                label = ["random-tag"]
                override_ap = False
            rc, out, err = _capture(_jira_setup.cmd_add_label, A())
        finally:
            _restore_driver_client(orig)
        assert rc != 0
        # _fail emits JSON to stdout
        j = json.loads(out)
        assert j["ok"] is False
        assert j.get("kind") == "label-not-allowed"
        assert calls == []  # no Jira call attempted


# --- (g) remove-label preserves other labels -----------------------------


def test_remove_label_preserves_others():
    queue = [
        _Response(200,
                  json.dumps(_issue("BZK-1",
                                    labels=["alpha", "beta", "gamma"])).encode(),
                  {}),
        _Response(204, b"", {}),
        _Response(200,
                  json.dumps(_issue("BZK-1",
                                    labels=["alpha", "gamma"])).encode(),
                  {}),
    ]
    calls: list[dict] = []
    client = _mock_client(queue, calls)
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_kanban(td)
        orig = _patch_driver_client(client)
        try:
            class A:
                kanban_path = str(kp)
                key = "BZK-1"
                label = ["beta"]
                override_ap = False
            rc, out, err = _capture(_jira_setup.cmd_remove_label, A())
        finally:
            _restore_driver_client(orig)
        assert rc == 0, (out, err)
        put = next(c for c in calls if c["method"] == "PUT")
        assert put["body"]["fields"]["labels"] == ["alpha", "gamma"]


# --- (h) delete refuses without --confirm --------------------------------


def test_delete_refuses_without_confirm():
    queue: list = []
    calls: list[dict] = []
    client = _mock_client(queue, calls)
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_kanban(td)
        orig = _patch_driver_client(client)
        try:
            class A:
                kanban_path = str(kp)
                key = "BZK-1"
                confirm = False
                cascade_subtasks = False
                force = False
            rc, out, err = _capture(_jira_setup.cmd_delete_issue, A())
        finally:
            _restore_driver_client(orig)
        assert rc != 0
        j = json.loads(out)
        assert j["ok"] is False
        assert j.get("kind") == "needs-confirm"
        assert calls == []


# --- (i) delete happy path: audit written, DELETE called -----------------


def test_delete_writes_audit_then_calls_delete():
    queue = [
        # cmd_delete_issue's get_task for snapshot
        _Response(200,
                  json.dumps(_issue("BZK-1",
                                    labels=["alpha"])).encode(),
                  {}),
        # driver.delete_issue -> client.delete_issue (DELETE)
        _Response(204, b"", {}),
    ]
    calls: list[dict] = []
    client = _mock_client(queue, calls)
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_kanban(td)
        _seed_agent(td, "alice-bot")
        orig = _patch_driver_client(client)
        try:
            class A:
                kanban_path = str(kp)
                key = "BZK-1"
                confirm = True
                cascade_subtasks = False
                force = False
            rc, out, err = _capture(_jira_setup.cmd_delete_issue, A())
        finally:
            _restore_driver_client(orig)
        assert rc == 0, (out, err)
        j = json.loads(out)
        assert j["ok"] is True
        # DELETE happened second (after the GET for snapshot)
        assert calls[1]["method"] == "DELETE"
        assert "deleteSubtasks=false" in calls[1]["url"]
        # Audit file present and structured
        audit = pathlib.Path(j["audit_path"])
        assert audit.exists()
        snap = json.loads(audit.read_text())
        assert snap["key"] == "BZK-1"
        assert snap["labels"] == ["alpha"]
        assert snap["deleted_by_ap"] == "alice-bot"
        assert snap["cascade_subtasks"] is False


# --- (j) recent-APPROVED guard ------------------------------------------


def test_delete_refuses_recent_approved_then_force_proceeds():
    recent_iso = (
        datetime.now(timezone.utc) - timedelta(days=2)
    ).strftime("%Y-%m-%dT%H:%M:%S.000+0000")

    # First pass: --force off, should refuse
    queue_1 = [
        _Response(200,
                  json.dumps(_issue("BZK-1", status="Done",
                                    completed=recent_iso)).encode(),
                  {}),
    ]
    calls_1: list[dict] = []
    client_1 = _mock_client(queue_1, calls_1)
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_kanban(td)
        orig = _patch_driver_client(client_1)
        try:
            class A:
                kanban_path = str(kp)
                key = "BZK-1"
                confirm = True
                cascade_subtasks = False
                force = False
            rc, out, err = _capture(_jira_setup.cmd_delete_issue, A())
        finally:
            _restore_driver_client(orig)
        assert rc != 0
        j = json.loads(out)
        assert j.get("kind") == "recent-approved"
        # Only the GET fired; no DELETE
        assert [c["method"] for c in calls_1] == ["GET"]

    # Second pass: --force on, should proceed
    queue_2 = [
        _Response(200,
                  json.dumps(_issue("BZK-1", status="Done",
                                    completed=recent_iso)).encode(),
                  {}),
        _Response(204, b"", {}),
    ]
    calls_2: list[dict] = []
    client_2 = _mock_client(queue_2, calls_2)
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_kanban(td)
        orig = _patch_driver_client(client_2)
        try:
            class A:
                kanban_path = str(kp)
                key = "BZK-1"
                confirm = True
                cascade_subtasks = False
                force = True
            rc, out, err = _capture(_jira_setup.cmd_delete_issue, A())
        finally:
            _restore_driver_client(orig)
        assert rc == 0, (out, err)
        assert [c["method"] for c in calls_2] == ["GET", "DELETE"]


def main() -> int:
    cases = [
        ("update_description_happy_path",
         test_update_description_happy_path),
        ("update_description_from_stdin",
         test_update_description_from_stdin),
        ("update_description_ap_mismatch_warning",
         test_update_description_ap_mismatch_warning),
        ("update_summary_happy_path", test_update_summary_happy_path),
        ("add_label_merges_with_existing",
         test_add_label_merges_with_existing),
        ("add_label_allowlist_rejects_unknown",
         test_add_label_allowlist_rejects_unknown),
        ("remove_label_preserves_others",
         test_remove_label_preserves_others),
        ("delete_refuses_without_confirm",
         test_delete_refuses_without_confirm),
        ("delete_writes_audit_then_calls_delete",
         test_delete_writes_audit_then_calls_delete),
        ("delete_refuses_recent_approved_then_force_proceeds",
         test_delete_refuses_recent_approved_then_force_proceeds),
    ]
    failed = 0
    for name, fn in cases:
        try:
            fn()
        except Exception as e:
            print(f"FAIL  {name}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            failed += 1
        else:
            print(f"ok    {name}")
    if failed:
        print(f"phase33: {failed} failure(s)", file=sys.stderr)
        return 1
    print("phase33: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
