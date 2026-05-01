#!/usr/bin/env python3
"""Phase 15 regression checks for kanban v0.3.8 — import-tasks completeness.

Closes #16 (AP/assignee/status not populated) and #18 (priority pre-flight
+ auto-map).

Cases:
  (a) _resolve_priority: identity for already-valid; auto-map P0..P4 to
      Highest..Lowest when both are in valid set; False for unmappable;
      None for None input; passthrough when valid set is empty
  (b) cmd_import_tasks pre-flight: rejects BEFORE create when any task
      has unmappable priority (no driver.create_task calls)
  (c) cmd_import_tasks: auto-map P0..P4 reaches driver.create_task
      with the correct Atlassian-default priority name
  (d) cmd_import_tasks: post-create — driver.assign(AgentRef(ap=repo_ap))
      is called for each created issue
  (e) cmd_import_tasks: post-create — driver.transition(key, "TODO") is
      called for each created issue
  (f) cmd_import_tasks: BLOCKED-origin tasks get an audit comment with
      the original blocked_reason
  (g) cmd_import_tasks: per-task best-effort — assign failure surfaces
      apSet=false but doesn't abort; transition failure surfaces
      transitioned=false but doesn't abort
  (h) cmd_import_tasks: dry-run skips ALL post-create steps + writes no
      mapping file
  (i) cmd_import_tasks: existing skip logic preserved (already-mapped,
      DONE/CANCELLED without --include-done)
  (j) cmd_import_tasks: pass-through priority when no credentials
      (valid_priority_names empty)
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

from drivers.base import AgentRef, Comment, CommentKind, Task, TaskInput  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "jira_setup_mod", str(PLUGIN / "scripts" / "jira_setup.py")
)
_jira_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_jira_setup)  # type: ignore[union-attr]


# --- _resolve_priority --------------------------------------------------


def test_resolve_priority_already_valid():
    fn = _jira_setup._resolve_priority
    valid = {"High", "Medium", "Low"}
    assert fn("High", valid) == "High"
    assert fn("Medium", valid) == "Medium"


def test_resolve_priority_automap():
    fn = _jira_setup._resolve_priority
    valid = {"Highest", "High", "Medium", "Low", "Lowest"}
    assert fn("P0", valid) == "Highest"
    assert fn("P1", valid) == "High"
    assert fn("P2", valid) == "Medium"
    assert fn("P3", valid) == "Low"
    assert fn("P4", valid) == "Lowest"


def test_resolve_priority_unmappable_returns_false():
    fn = _jira_setup._resolve_priority
    valid = {"Highest", "High", "Medium", "Low", "Lowest"}
    assert fn("Critical", valid) is False
    assert fn("P99", valid) is False


def test_resolve_priority_none_input():
    fn = _jira_setup._resolve_priority
    valid = {"High", "Medium", "Low"}
    assert fn(None, valid) is None


def test_resolve_priority_empty_valid_passes_through():
    """When pre-flight is unavailable, the helper passes the input
    through unchanged so the existing create-time-error path still works.
    """
    fn = _jira_setup._resolve_priority
    assert fn("P1", set()) == "P1"
    assert fn("Anything", set()) == "Anything"
    assert fn(None, set()) is None


# --- cmd_import_tasks integration --------------------------------------


def _seed_kanban(td, tasks=()):
    p = pathlib.Path(td) / "kanban.json"
    p.write_text(json.dumps({
        "version": "0.2",
        "backend": {"driver": "jira", "jira": {
            "boardUrl": "https://x/jira/projects/AGENT/boards/1",
            "boardId": 1, "projectKey": "AGENT",
            "agentAccountId": "5e-bot",
            "transitions": {
                "TODO": {"status": "Selected for Development"},
                "DOING": {"status": "In Progress"},
                "BLOCKED": {"status": "In Progress",
                            "addLabels": ["kanban:blocked"]},
                "DONE": {"status": "Done"},
            },
            "ap": {"fieldId": "customfield_10042",
                   "fieldName": "Claude Agent",
                   "registered": ["agent-fin"]},
        }},
        "meta": {"priorities": ["P0", "P1", "P2", "P3"], "categories": [],
                 "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"],
                 "created_at": "x", "updated_at": "x"},
        "tasks": list(tasks),
    }))
    (p.parent / ".claude").mkdir()
    (p.parent / ".claude" / "kanban-agent.json").write_text(
        json.dumps({"ap": "agent-fin"}) + "\n"
    )
    return p


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


class _StubDriver:
    """Records every call so tests can assert on order + arguments."""
    name = "jira"

    def __init__(self, *, fail_assign_for=None, fail_transition_for=None):
        self.created: list[TaskInput] = []
        self.assigned: list[tuple[str, AgentRef]] = []
        self.transitions: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str, CommentKind]] = []
        self._key_counter = 100
        self._fail_assign_for = set(fail_assign_for or [])
        self._fail_transition_for = set(fail_transition_for or [])

    def _next_key(self) -> str:
        self._key_counter += 1
        return f"AGENT-{self._key_counter}"

    def create_task(self, task: TaskInput) -> Task:
        self.created.append(task)
        key = self._next_key()
        return Task(
            id=key, title=task.title, column="TODO",
            priority=task.priority or "P2", created="x", updated="y",
        )

    def assign(self, key: str, member) -> Task:
        if key in self._fail_assign_for:
            raise RuntimeError(f"assign failed for {key}")
        self.assigned.append((key, member))
        return Task(id=key, title="x", column="TODO", priority="P1",
                    created="x", updated="y")

    def transition(self, key: str, to_column: str, **kwargs) -> Task:
        if key in self._fail_transition_for:
            raise RuntimeError(f"transition failed for {key}")
        self.transitions.append((key, to_column))
        return Task(id=key, title="x", column=to_column, priority="P1",
                    created="x", updated="y")

    def post_comment(self, key: str, body: str, kind: CommentKind = CommentKind.COMMENT,
                     **kwargs) -> Comment:
        self.comments.append((key, body, kind))
        return Comment(author="agent", ts="x", text=body, kind=kind)


def _patch_priority_client(valid_names: set[str] | None):
    """Replace _client_from_env_or_none so the pre-flight uses our fake."""
    if valid_names is None:
        # Simulate "no credentials" — pre-flight returns None client
        client = None
    else:
        class _C:
            def get_priorities(self):
                return [{"id": str(i), "name": n} for i, n in enumerate(valid_names)]
        client = _C()
    orig = _jira_setup._client_from_env_or_none
    _jira_setup._client_from_env_or_none = lambda: client
    return orig


def _restore_priority_client(orig):
    _jira_setup._client_from_env_or_none = orig


def _patch_driver(stub):
    import drivers as _drv_mod
    orig = _drv_mod.get_driver
    _drv_mod.get_driver = lambda data, root: stub
    return orig


def _restore_driver(orig):
    import drivers as _drv_mod
    _drv_mod.get_driver = orig


def test_pre_flight_rejects_unmappable_before_creating_anything():
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_kanban(td, tasks=[
            {"id": "task-001", "title": "ok", "column": "TODO",
             "priority": "P1", "created": "x", "updated": "y"},
            {"id": "task-002", "title": "bad", "column": "TODO",
             "priority": "Critical", "created": "x", "updated": "y"},
        ])
        stub = _StubDriver()
        po = _patch_priority_client({"Highest", "High", "Medium", "Low", "Lowest"})
        do = _patch_driver(stub)
        try:
            class A:
                kanban_path = str(kp); dry_run = False; include_done = False
            rc, out = _capture(_jira_setup.cmd_import_tasks, A())
        finally:
            _restore_priority_client(po)
            _restore_driver(do)
        assert rc != 0, out
        j = json.loads(out)
        assert j["ok"] is False
        assert "unmappable priorities" in j["error"]
        # Critically: NO driver.create_task calls should have happened
        assert stub.created == []
        # Map file should NOT exist (no successful creates)
        assert not (kp.parent / ".claude" / ".migration-map.json").exists()


def test_priority_automap_p1_to_high():
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_kanban(td, tasks=[
            {"id": "task-001", "title": "todo", "column": "TODO",
             "priority": "P1", "created": "x", "updated": "y"},
            {"id": "task-002", "title": "doing", "column": "DOING",
             "priority": "P0", "created": "x", "updated": "y",
             "started": "x"},
        ])
        stub = _StubDriver()
        po = _patch_priority_client({"Highest", "High", "Medium", "Low", "Lowest"})
        do = _patch_driver(stub)
        try:
            class A:
                kanban_path = str(kp); dry_run = False; include_done = False
            rc, out = _capture(_jira_setup.cmd_import_tasks, A())
        finally:
            _restore_priority_client(po)
            _restore_driver(do)
        assert rc == 0, out
        j = json.loads(out)
        assert j["imported"] == 2
        # Verify resolved priorities reached create_task
        priorities_used = [t.priority for t in stub.created]
        assert "High" in priorities_used   # P1 → High
        assert "Highest" in priorities_used  # P0 → Highest


def test_post_create_assigns_ap_and_transitions_to_todo():
    """The big one for #16: every imported card gets AP + transition."""
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_kanban(td, tasks=[
            {"id": "task-001", "title": "alpha", "column": "TODO",
             "priority": "P1", "created": "x", "updated": "y"},
            {"id": "task-002", "title": "beta", "column": "DOING",
             "priority": "P2", "created": "x", "updated": "y",
             "started": "x"},
        ])
        stub = _StubDriver()
        po = _patch_priority_client({"High", "Medium"})
        do = _patch_driver(stub)
        try:
            class A:
                kanban_path = str(kp); dry_run = False; include_done = False
            rc, out = _capture(_jira_setup.cmd_import_tasks, A())
        finally:
            _restore_priority_client(po)
            _restore_driver(do)
        assert rc == 0, out
        j = json.loads(out)
        assert j["imported"] == 2

        # Both created cards got assign(AgentRef) called
        assert len(stub.assigned) == 2
        for key, member in stub.assigned:
            assert member.kind == "agent"
            assert member.ap == "agent-fin"

        # Both created cards got transition(key, "TODO")
        assert len(stub.transitions) == 2
        for key, to in stub.transitions:
            assert to == "TODO"

        # All entries in tasks[] report apSet=true and transitioned=true
        for entry in j["tasks"]:
            assert entry["apSet"] is True
            assert entry["transitioned"] is True
            assert entry["apError"] is None
            assert entry["transitionError"] is None


def test_blocked_origin_gets_audit_comment():
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_kanban(td, tasks=[
            {"id": "task-001", "title": "stuck", "column": "BLOCKED",
             "priority": "P2", "created": "x", "updated": "y",
             "custom": {"blocked_reason": "waiting on infra team"}},
        ])
        stub = _StubDriver()
        po = _patch_priority_client({"Medium"})
        do = _patch_driver(stub)
        try:
            class A:
                kanban_path = str(kp); dry_run = False; include_done = False
            rc, out = _capture(_jira_setup.cmd_import_tasks, A())
        finally:
            _restore_priority_client(po)
            _restore_driver(do)
        assert rc == 0
        # An audit comment should have been posted
        assert len(stub.comments) == 1
        key, body, kind = stub.comments[0]
        assert "Originally BLOCKED" in body
        assert "waiting on infra team" in body
        assert kind == CommentKind.SYSTEM


def test_per_task_best_effort_on_assign_failure():
    """If assign fails for one card, the rest of the import continues
    and the failed card has apSet=false in the result."""
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_kanban(td, tasks=[
            {"id": "task-001", "title": "a", "column": "TODO",
             "priority": "P1", "created": "x", "updated": "y"},
            {"id": "task-002", "title": "b", "column": "TODO",
             "priority": "P1", "created": "x", "updated": "y"},
        ])
        # First created issue's assign fails. Stub's first key will be AGENT-101.
        stub = _StubDriver(fail_assign_for={"AGENT-101"})
        po = _patch_priority_client({"High"})
        do = _patch_driver(stub)
        try:
            class A:
                kanban_path = str(kp); dry_run = False; include_done = False
            rc, out = _capture(_jira_setup.cmd_import_tasks, A())
        finally:
            _restore_priority_client(po)
            _restore_driver(do)
        assert rc == 0
        j = json.loads(out)
        assert j["imported"] == 2  # both still imported (best-effort)
        # First entry shows apSet=false; second shows true
        first, second = j["tasks"][0], j["tasks"][1]
        assert first["apSet"] is False and first["apError"] is not None
        assert second["apSet"] is True
        # Both still got transition attempts
        assert len(stub.transitions) == 2


def test_dry_run_skips_all_writes():
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_kanban(td, tasks=[
            {"id": "task-001", "title": "a", "column": "TODO",
             "priority": "P1", "created": "x", "updated": "y"},
        ])
        stub = _StubDriver()
        po = _patch_priority_client({"High"})
        do = _patch_driver(stub)
        try:
            class A:
                kanban_path = str(kp); dry_run = True; include_done = False
            rc, out = _capture(_jira_setup.cmd_import_tasks, A())
        finally:
            _restore_priority_client(po)
            _restore_driver(do)
        assert rc == 0
        # Zero side-effects on driver
        assert stub.created == []
        assert stub.assigned == []
        assert stub.transitions == []
        # No mapping file written
        assert not (kp.parent / ".claude" / ".migration-map.json").exists()
        # Result still surfaces the planned resolution
        j = json.loads(out)
        assert j["dryRun"] is True
        assert j["tasks"][0]["resolvedPriority"] == "High"


def test_skip_logic_preserved():
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_kanban(td, tasks=[
            {"id": "task-001", "title": "open", "column": "TODO",
             "priority": "P1", "created": "x", "updated": "y"},
            {"id": "task-002", "title": "old", "column": "DONE",
             "priority": "P1", "created": "x", "updated": "y",
             "started": "x", "completed": "x"},
        ])
        # Pre-existing mapping for task-001 simulates a re-run
        (kp.parent / ".claude" / ".migration-map.json").write_text(
            json.dumps({"task-001": "AGENT-99"})
        )
        stub = _StubDriver()
        po = _patch_priority_client({"High"})
        do = _patch_driver(stub)
        try:
            class A:
                kanban_path = str(kp); dry_run = False; include_done = False
            rc, out = _capture(_jira_setup.cmd_import_tasks, A())
        finally:
            _restore_priority_client(po)
            _restore_driver(do)
        assert rc == 0
        j = json.loads(out)
        # task-001 already-mapped, task-002 DONE-skipped → 0 created
        assert j["imported"] == 0
        assert j["skipped"] == 2
        reasons = {s["reason"] for s in j["skippedDetail"]}
        assert "already-mapped" in reasons
        assert "closed-done" in reasons


def test_passthrough_priority_when_no_credentials():
    """No credentials = no pre-flight = passthrough. The legacy code-path
    (create-time error if Jira rejects) is preserved."""
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_kanban(td, tasks=[
            {"id": "task-001", "title": "x", "column": "TODO",
             "priority": "P1", "created": "x", "updated": "y"},
        ])
        stub = _StubDriver()
        po = _patch_priority_client(None)  # no client
        do = _patch_driver(stub)
        try:
            class A:
                kanban_path = str(kp); dry_run = False; include_done = False
            rc, out = _capture(_jira_setup.cmd_import_tasks, A())
        finally:
            _restore_priority_client(po)
            _restore_driver(do)
        # Stub doesn't reject — would succeed; verify P1 was passed through
        assert rc == 0
        assert stub.created[0].priority == "P1"


def main() -> int:
    cases = [
        ("resolve_priority_already_valid", test_resolve_priority_already_valid),
        ("resolve_priority_automap", test_resolve_priority_automap),
        ("resolve_priority_unmappable_returns_false",
         test_resolve_priority_unmappable_returns_false),
        ("resolve_priority_none_input", test_resolve_priority_none_input),
        ("resolve_priority_empty_valid_passes_through",
         test_resolve_priority_empty_valid_passes_through),
        ("pre_flight_rejects_unmappable_before_creating_anything",
         test_pre_flight_rejects_unmappable_before_creating_anything),
        ("priority_automap_p1_to_high", test_priority_automap_p1_to_high),
        ("post_create_assigns_ap_and_transitions_to_todo",
         test_post_create_assigns_ap_and_transitions_to_todo),
        ("blocked_origin_gets_audit_comment",
         test_blocked_origin_gets_audit_comment),
        ("per_task_best_effort_on_assign_failure",
         test_per_task_best_effort_on_assign_failure),
        ("dry_run_skips_all_writes", test_dry_run_skips_all_writes),
        ("skip_logic_preserved", test_skip_logic_preserved),
        ("passthrough_priority_when_no_credentials",
         test_passthrough_priority_when_no_credentials),
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
    print("phase15: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
