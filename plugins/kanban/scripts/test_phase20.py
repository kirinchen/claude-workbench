#!/usr/bin/env python3
"""Phase 20 regression checks for kanban v0.3.13 — `cmd_health` hint
when the active driver is local.

Closes #31. The `health` helper was being used as the oracle for "are
Jira credentials present?" in `/kanban:initjira-by-code` step 1 — but at
that point `kanban.json#backend.driver` is still `"local"`, so health
runs against `LocalDriver` (which has nothing Jira-related to check)
and unconditionally returns ok. Callers silently bypassed credential
capture and only failed multiple steps later.

The fix on the slash-command side is a doc change (use `read-credentials`
+ `tokenPresent`). On the helper side we can't safely flip `ok` to false
for the local driver — `/kanban:init`'s legitimate post-init health
check would break. Instead we append a hint to the `detail` field so
any caller that prints it self-diagnoses the misuse.

Cases:
  (a) `cmd_health` with `backend.driver == "local"` keeps `ok=true` but
      `detail` mentions `local driver` and `read-credentials`.
  (b) `cmd_health` with `backend.driver == "jira"` (and missing creds —
      i.e. unauthenticated) returns the underlying driver detail
      unchanged — the local-driver hint is NOT appended.
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


_spec = importlib.util.spec_from_file_location(
    "jira_setup_mod", str(PLUGIN / "scripts" / "jira_setup.py")
)
_jira_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_jira_setup)  # type: ignore[union-attr]


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


def _seed_local_kanban(td: pathlib.Path) -> pathlib.Path:
    p = td / "kanban.json"
    p.write_text(json.dumps({
        "version": "0.2",
        "backend": {"driver": "local"},
        "meta": {"priorities": ["P0"], "categories": [],
                 "columns": ["TODO", "DOING", "BLOCKED", "REVIEW",
                             "DONE", "CANCELLED"],
                 "created_at": "x", "updated_at": "x"},
        "tasks": [],
    }))
    return p


def _seed_jira_kanban(td: pathlib.Path) -> pathlib.Path:
    p = td / "kanban.json"
    p.write_text(json.dumps({
        "version": "0.2",
        "backend": {"driver": "jira", "jira": {
            "boardUrl": "https://x/jira/projects/AGENT/boards/1",
            "boardId": 1, "projectKey": "AGENT",
            "transitions": {"TODO": {"status": "To Do"}},
        }},
        "meta": {"priorities": ["P0"], "categories": [],
                 "columns": ["TODO", "DOING", "BLOCKED", "REVIEW",
                             "DONE", "CANCELLED"],
                 "created_at": "x", "updated_at": "x"},
        "tasks": [],
    }))
    return p


def test_health_local_driver_appends_hint():
    """LocalDriver is fine on its own (ok=true) but health is the wrong
    oracle for 'are Jira creds set up?' — detail must self-document so
    any caller that prints it spots the misuse."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_local_kanban(td)

        class A:
            kanban_path = str(kp)

        rc, out = _capture(_jira_setup.cmd_health, A())
        assert rc == 0
        j = json.loads(out)
        assert j["ok"] is True
        # Status from LocalDriver is still "ok"
        assert j["status"] == "ok"
        # Hint surfaces in detail
        detail = j["detail"] or ""
        assert "local driver" in detail.lower()
        assert "read-credentials" in detail


def test_health_jira_driver_no_local_hint():
    """When backend is `jira`, the local-driver hint must NOT contaminate
    the detail field — that would mislead users on real auth failures."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td)
        # Force unauthenticated state by clearing credential env vars
        # AND pointing credentials.read at an empty payload.
        from lib import credentials
        orig = credentials.read
        credentials.read = lambda prefix=None: {}
        try:
            class A:
                kanban_path = str(kp)
            rc, out = _capture(_jira_setup.cmd_health, A())
        finally:
            credentials.read = orig
        assert rc == 0
        j = json.loads(out)
        # Whatever the underlying status is, the local-driver hint must
        # not appear here.
        detail = j["detail"] or ""
        assert "local driver" not in detail.lower(), detail


def main() -> int:
    cases = [
        ("health_local_driver_appends_hint",
         test_health_local_driver_appends_hint),
        ("health_jira_driver_no_local_hint",
         test_health_jira_driver_no_local_hint),
    ]
    failed = 0
    for name, fn in cases:
        try:
            fn()
        except Exception as e:
            print(f"FAIL  {name}: {e}", file=sys.stderr)
            failed += 1
        else:
            print(f"ok    {name}")
    if failed:
        print(f"phase20: {failed} failure(s)", file=sys.stderr)
        return 1
    print("phase20: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
