#!/usr/bin/env python3
"""Phase 28 regression checks for kanban v0.3.23 — DONE → APPROVED rename
(#48) and back-compat alias paths.

The canonical state DONE was renamed to APPROVED to disambiguate from
the Jira workflow status `Done`. Existing setups (kanban.json,
kanban-jira-code/2 payloads, legacy `--to DONE` invocations, DSL keys
in JSON form) continue to work via aliases that normalize on the way in.
This phase verifies every alias path stays correct.

Cases:
  (a) `transitions._alias_done_to_approved` renames `DONE` → `APPROVED`;
      idempotent on already-renamed input; conflict-skip when both keys
      exist (explicit APPROVED wins).
  (b) `kanban_io.load` auto-migrates a kanban.json with task.column =
      "DONE" and meta.columns containing "DONE" → "APPROVED" in-memory.
  (c) `transitions.parse_dsl` accepts `DONE > Done` on input and
      writes the spec under the canonical APPROVED key.
  (d) `transitions.parse_dsl` accepts the legacy reference
      `CANCELLED > DONE + label` (UPPERCASE self-reference); aliased
      to APPROVED on the RHS too, so the existing canonical-share
      pattern keeps working.
  (e) `migrate_legacy` on a v0.2 jira_cfg with `statusMap.DONE`
      writes `transitions.APPROVED`.
  (f) `migrate_legacy` on a v0.3 jira_cfg with `transitions.DONE`
      auto-renames to `transitions.APPROVED`.
  (g) `cmd_set_transitions` accepts a JSON block with `"DONE"`,
      auto-renames to `APPROVED`, returns deprecation warning, persists
      the canonical form.
  (h) `cmd_set_transitions` rejects a JSON block carrying BOTH `DONE`
      and `APPROVED` (ambiguous).
  (i) `cmd_import_jira_code` accepts a v2 payload with
      `transitions.DONE` and upgrades to APPROVED on persist; emits
      `kanban-jira-code/3` on subsequent emit.
  (j) `cmd_emit_jira_code` outputs schema `kanban-jira-code/3`.
  (k) `cmd_transition --to DONE` accepts the alias, emits a stderr
      deprecation warning, normalises to APPROVED before delegating
      to driver.
"""
from __future__ import annotations

import importlib.util
import io
import json
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"
sys.path.insert(0, str(REPO / "plugins" / "kanban"))

from lib import transitions as _tr  # noqa: E402
from lib import kanban_io  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "jira_setup_mod", str(PLUGIN / "scripts" / "jira_setup.py")
)
_jira_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_jira_setup)  # type: ignore[union-attr]


def _capture(fn, args):
    """Capture stdout + stderr of a helper subcommand call."""
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        try:
            rc = fn(args)
        except SystemExit as e:
            rc = e.code
        out = sys.stdout.getvalue()
        err = sys.stderr.getvalue()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out, err


# --- (a) alias helper ---------------------------------------------------


def test_alias_done_to_approved_basic():
    out = _tr._alias_done_to_approved({"DONE": {"status": "Done"}})
    assert out == {"APPROVED": {"status": "Done"}}


def test_alias_done_to_approved_idempotent():
    """Already-renamed input passes through unchanged."""
    src = {"APPROVED": {"status": "Done"}}
    out = _tr._alias_done_to_approved(src)
    assert out == src
    # And run twice — still no change
    assert _tr._alias_done_to_approved(out) == src


def test_alias_done_to_approved_conflict_explicit_wins():
    """When BOTH keys exist, the explicit APPROVED wins; DONE is dropped.
    First write afterwards persists the canonical shape."""
    out = _tr._alias_done_to_approved({
        "DONE": {"status": "Old Done"},
        "APPROVED": {"status": "New Done"},
    })
    assert out == {"APPROVED": {"status": "New Done"}}


# --- (b) kanban_io load auto-migrates -----------------------------------


def test_kanban_io_load_migrates_task_column():
    with tempfile.TemporaryDirectory() as td:
        kp = pathlib.Path(td) / "kanban.json"
        kp.write_text(json.dumps({
            "version": "0.2",
            "backend": {"driver": "local"},
            "meta": {"priorities": ["P1"], "categories": [],
                     "columns": ["TODO", "DOING", "DONE", "BLOCKED"],
                     "created_at": "x", "updated_at": "x"},
            "tasks": [
                {"id": "task-001", "title": "x", "column": "DONE",
                 "priority": "P1", "created": "x", "updated": "y",
                 "started": "x", "completed": "x"},
                {"id": "task-002", "title": "y", "column": "DOING",
                 "priority": "P1", "created": "x", "updated": "y",
                 "started": "x"},
            ],
        }))
        data = kanban_io.load(kp)
        assert data["tasks"][0]["column"] == "APPROVED"
        assert data["tasks"][1]["column"] == "DOING"
        assert "DONE" not in data["meta"]["columns"]
        assert "APPROVED" in data["meta"]["columns"]


# --- (c) (d) parse_dsl accepts DONE on LHS + RHS ------------------------


def test_parse_dsl_accepts_legacy_done_lhs():
    """`DONE > Done` is accepted; spec stored under canonical APPROVED."""
    out = _tr.parse_dsl(
        "TODO > To Do\n"
        "DOING > In Progress\n"
        "DONE > Done\n"
    )
    assert "APPROVED" in out
    assert "DONE" not in out
    assert out["APPROVED"]["status"] == "Done"


def test_parse_dsl_accepts_legacy_done_rhs_self_reference():
    """`CANCELLED > DONE + label` keeps working — DONE resolves to
    APPROVED's status (Done) on the RHS."""
    out = _tr.parse_dsl(
        "TODO > To Do\n"
        "DOING > In Progress\n"
        "DONE > Done\n"
        "CANCELLED > DONE + Label\n"
    )
    assert "APPROVED" in out
    assert "CANCELLED" in out
    assert out["CANCELLED"]["status"] == "Done"
    assert "kanban:cancelled" in out["CANCELLED"]["addLabels"]


# --- (e) (f) migrate_legacy -------------------------------------------


def test_migrate_legacy_v02_with_done_in_status_map():
    """v0.2 statusMap with `DONE` key migrates straight to v0.3
    transitions.APPROVED."""
    legacy = {
        "statusMap": {
            "TODO": "To Do",
            "DOING": "In Progress",
            "DONE": "Done",
        },
    }
    out = _tr.migrate_legacy(legacy)
    assert "APPROVED" in out["transitions"]
    assert out["transitions"]["APPROVED"]["status"] == "Done"
    assert "DONE" not in out["transitions"]


def test_migrate_legacy_v03_with_done_renames():
    """v0.3 transitions block with literal `DONE` key (a kanban-jira-code/2
    payload from before the rename) auto-renames on the way through."""
    legacy = {
        "transitions": {
            "TODO": {"status": "To Do"},
            "DOING": {"status": "In Progress"},
            "DONE": {"status": "Done"},
        },
    }
    out = _tr.migrate_legacy(legacy)
    assert "APPROVED" in out["transitions"]
    assert "DONE" not in out["transitions"]


# --- (g) (h) cmd_set_transitions deprecation + ambiguity ----------------


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
                             "APPROVED", "CANCELLED"],
                 "created_at": "x", "updated_at": "x"},
        "tasks": [],
    }))
    return p


def test_set_transitions_accepts_done_with_warning():
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_jira_kanban(pathlib.Path(td))

        class A:
            kanban_path = str(kp)
            transitions_json = json.dumps({
                "TODO": {"status": "To Do"},
                "DOING": {"status": "In Progress"},
                "DONE": {"status": "Done"},
                "CANCELLED": {"status": "Done", "addLabels": ["kanban:cancelled"]},
            })
            available_statuses = None
            force = False

        rc, out, err = _capture(_jira_setup.cmd_set_transitions, A())
        assert rc == 0, (out, err)
        # Stderr deprecation warning surfaced
        assert "deprecated" in err.lower()
        j = json.loads(out)
        # Persisted transitions carry APPROVED, not DONE
        assert "APPROVED" in j["transitions"]
        assert "DONE" not in j["transitions"]
        # Warning included in the JSON `warnings` list too
        assert any("DONE" in w for w in j["warnings"])
        # And on disk
        on_disk = json.loads(kp.read_text())
        assert "APPROVED" in on_disk["backend"]["jira"]["transitions"]


def test_set_transitions_rejects_both_keys():
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_jira_kanban(pathlib.Path(td))

        class A:
            kanban_path = str(kp)
            transitions_json = json.dumps({
                "TODO": {"status": "To Do"},
                "DONE": {"status": "Done"},
                "APPROVED": {"status": "Done v2"},
            })
            available_statuses = None
            force = False

        rc, out, err = _capture(_jira_setup.cmd_set_transitions, A())
        assert rc != 0
        j = json.loads(out)
        assert j["ok"] is False
        assert "cannot carry both" in j["error"]


# --- (i) (j) emit / import jira-code subcommands removed in 0.3.27 ------
# The kanban-jira-code paste flow was retired in favour of board-config
# storage on Jira project properties. Migration semantics for legacy
# transitions.DONE keys are now exercised via:
#   - lib.transitions._alias_done_to_approved (covered above)
#   - cmd_pull_board_config / cmd_push_board_config in phases 30 + 31
# (no test stub here; the old emit/import tests were removed alongside
# their underlying subcommands.)


# --- (k) cmd_transition --to DONE alias ---------------------------------


def test_cmd_transition_to_done_aliases_with_warning():
    """--to DONE emits stderr deprecation, normalises to APPROVED,
    then delegates to driver. Verify via stub driver capturing the
    to_column it received."""
    received = {}

    class _StubDrv:
        name = "jira"
        def transition(self, key, to_column, **kwargs):
            received["to_column"] = to_column
            received["kwargs"] = kwargs
            from drivers.base import Task
            return Task(
                id=key, title="x", column=to_column, priority="P1",
                created="x", updated="y", custom={"raw_status": to_column},
            )

    import drivers as _drv_mod
    d_orig = _drv_mod.get_driver
    _drv_mod.get_driver = lambda data, root: _StubDrv()

    try:
        with tempfile.TemporaryDirectory() as td:
            kp = _seed_jira_kanban(pathlib.Path(td))

            class A:
                kanban_path = str(kp)
                key = "AGENT-1"
                to = "DONE"
                reason = None
                blocked_by = None
                flavor = None

            rc, out, err = _capture(_jira_setup.cmd_transition, A())
    finally:
        _drv_mod.get_driver = d_orig

    assert rc == 0, (out, err)
    # The driver received the canonical name, not the deprecated alias
    assert received["to_column"] == "APPROVED"
    # Deprecation surfaced on stderr
    assert "deprecated" in err.lower()
    assert "APPROVED" in err


def main() -> int:
    cases = [
        ("alias_done_to_approved_basic", test_alias_done_to_approved_basic),
        ("alias_done_to_approved_idempotent",
         test_alias_done_to_approved_idempotent),
        ("alias_done_to_approved_conflict_explicit_wins",
         test_alias_done_to_approved_conflict_explicit_wins),
        ("kanban_io_load_migrates_task_column",
         test_kanban_io_load_migrates_task_column),
        ("parse_dsl_accepts_legacy_done_lhs",
         test_parse_dsl_accepts_legacy_done_lhs),
        ("parse_dsl_accepts_legacy_done_rhs_self_reference",
         test_parse_dsl_accepts_legacy_done_rhs_self_reference),
        ("migrate_legacy_v02_with_done_in_status_map",
         test_migrate_legacy_v02_with_done_in_status_map),
        ("migrate_legacy_v03_with_done_renames",
         test_migrate_legacy_v03_with_done_renames),
        ("set_transitions_accepts_done_with_warning",
         test_set_transitions_accepts_done_with_warning),
        ("set_transitions_rejects_both_keys",
         test_set_transitions_rejects_both_keys),
        ("cmd_transition_to_done_aliases_with_warning",
         test_cmd_transition_to_done_aliases_with_warning),
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
        print(f"phase28: {failed} failure(s)", file=sys.stderr)
        return 1
    print("phase28: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
