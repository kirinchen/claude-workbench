#!/usr/bin/env python3
"""Phase 23 regression checks for kanban v0.3.16 — `list-doing` helper
backing /kanban:doing.

Closes #33. /kanban:doing replaces the single-step "auto-pick from
TODO" model with "agent works the cards already in DOING for its AP."
The owner curates TODO → DOING; the agent's job is to execute, not
play PM. The new helper subcommand is read-only: it never transitions
a card and never pulls from TODO.

Cases:
  (a) Happy path — DOING has cards: returns them with id/title/
      priority/started/ap fields, and the JQL hitting Jira filters by
      both column=DOING and ap=<repo_ap>.
  (b) Empty DOING — returns ok=true with doing=[] (slash command then
      tells the user "owner needs to move a TODO into DOING").
  (c) No repo AP set in .claude/kanban-agent.json — fail with the
      assign-ap nudge.
  (d) Local backend — fail (jira-only command).
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


def _seed_jira_kanban(td: pathlib.Path, *, with_ap: bool = True) -> pathlib.Path:
    p = td / "kanban.json"
    p.write_text(json.dumps({
        "version": "0.2",
        "backend": {"driver": "jira", "jira": {
            "boardUrl": "https://x/jira/projects/AGENT/boards/1",
            "boardId": 1, "projectKey": "AGENT",
            "agentAccountId": "5e-agent",
            "transitions": {
                "TODO": {"status": "To Do"},
                "DOING": {"status": "In Progress"},
                "DONE": {"status": "Done"},
            },
            "ap": {"fieldId": "customfield_10042",
                   "fieldName": "Claude Agent",
                   "registered": ["agent-fin"]},
        }},
        "meta": {"priorities": ["P0"], "categories": [],
                 "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"],
                 "created_at": "x", "updated_at": "x"},
        "tasks": [],
    }))
    if with_ap:
        (td / ".claude").mkdir()
        (td / ".claude" / "kanban-agent.json").write_text(
            json.dumps({"ap": "agent-fin"}) + "\n"
        )
    return p


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


def _stub_driver(cards: list, *, captured_filter: list):
    """Return a stub driver whose list_tasks() captures the TaskFilter
    it was called with and returns the prepared cards. Used to verify
    cmd_list_doing passes the right column+ap to the driver layer
    without having to mock the full HTTP path."""
    from drivers.base import Task

    class _StubDrv:
        name = "jira"

        def list_tasks(self, filter=None):
            captured_filter.append(filter)
            return cards

    return _StubDrv()


def _mk_task(*, id, title, priority="P1", started=None, ap="agent-fin"):
    from drivers.base import Task
    return Task(
        id=id, title=title, column="DOING",
        priority=priority, category=None, tags=[], depends=[],
        assignee=None, description="", comments=[],
        created="x", updated="y",
        started=started, completed=None,
        ap=ap,
    )


def test_list_doing_returns_doing_cards_filtered_by_ap():
    """list_tasks must be called with TaskFilter(column=DOING, ap=<repo_ap>);
    the response is shaped as {ok, ap, doing: [...]}.
    """
    captured: list = []
    cards = [
        _mk_task(id="AGENT-101", title="first doing", priority="P0"),
        _mk_task(id="AGENT-102", title="second doing", priority="P1"),
    ]

    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td)
        import drivers as _drv_mod
        d_orig = _drv_mod.get_driver
        _drv_mod.get_driver = lambda data, root: _stub_driver(cards, captured_filter=captured)
        try:
            class A: kanban_path = str(kp)
            rc, out = _capture(_jira_setup.cmd_list_doing, A())
        finally:
            _drv_mod.get_driver = d_orig

    assert rc == 0, out
    j = json.loads(out)
    assert j["ok"] is True
    assert j["ap"] == "agent-fin"
    assert len(j["doing"]) == 2
    assert {c["id"] for c in j["doing"]} == {"AGENT-101", "AGENT-102"}

    # The TaskFilter passed to driver.list_tasks must constrain BOTH
    # column AND ap — that's the heart of #33 (don't scan the whole
    # backlog; only the DOING set for this repo's AP).
    assert len(captured) == 1
    f = captured[0]
    assert f.column == "DOING", f
    assert f.ap == "agent-fin", f


def test_list_doing_empty_returns_ok_with_empty_list():
    """Empty DOING is ok=true (the slash command then tells the user
    'owner needs to move a TODO into DOING'); never auto-fall-through."""
    captured: list = []

    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td)
        import drivers as _drv_mod
        d_orig = _drv_mod.get_driver
        _drv_mod.get_driver = lambda data, root: _stub_driver([], captured_filter=captured)
        try:
            class A: kanban_path = str(kp)
            rc, out = _capture(_jira_setup.cmd_list_doing, A())
        finally:
            _drv_mod.get_driver = d_orig

    assert rc == 0, out
    j = json.loads(out)
    assert j["ok"] is True
    assert j["doing"] == []


def test_list_doing_without_repo_ap_fails():
    """Missing .claude/kanban-agent.json → fail, hint at /kanban:assign-ap."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td, with_ap=False)

        class A: kanban_path = str(kp)
        rc, out = _capture(_jira_setup.cmd_list_doing, A())

    assert rc != 0, out
    j = json.loads(out)
    assert j.get("ok") is False
    assert "assign-ap" in (j.get("error") or ""), j


def test_list_doing_against_local_backend_fails():
    """Jira-only command — refuse on local backend."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_local_kanban(td)

        class A: kanban_path = str(kp)
        rc, out = _capture(_jira_setup.cmd_list_doing, A())

    assert rc != 0, out
    j = json.loads(out)
    assert j.get("ok") is False
    assert "jira" in (j.get("error") or "").lower(), j


def main() -> int:
    cases = [
        ("list_doing_returns_doing_cards_filtered_by_ap",
         test_list_doing_returns_doing_cards_filtered_by_ap),
        ("list_doing_empty_returns_ok_with_empty_list",
         test_list_doing_empty_returns_ok_with_empty_list),
        ("list_doing_without_repo_ap_fails",
         test_list_doing_without_repo_ap_fails),
        ("list_doing_against_local_backend_fails",
         test_list_doing_against_local_backend_fails),
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
        print(f"phase23: {failed} failure(s)", file=sys.stderr)
        return 1
    print("phase23: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
