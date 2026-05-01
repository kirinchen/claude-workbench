#!/usr/bin/env python3
"""Phase 13 regression checks for kanban v0.3.6 — sync stale + unanswered detectors.

`/kanban:sync` (and the SessionStart hook) gain two checks beyond the
existing open-cards + mentions blocks:

  - Stale DOING: cards in DOING for ≥ 2 days haven't moved
  - Unanswered questions: this AP posted a Q-comment on a BLOCKED card,
    no other party has commented since, and ≥24h have passed

These are the "things a human checks when they open Jira" — surfaced so
the agent doesn't forget cards that have been quietly aging.

Cases:
  (a) _parse_iso handles +08:00, Z, and bad input
  (b) _detect_stale_doing flags cards updated > 2d ago
  (c) _detect_stale_doing skips cards updated recently
  (d) _detect_stale_doing returns [] when no DOING cards
  (e) _detect_unanswered_questions: own Q + later non-self comment → not flagged
  (f) _detect_unanswered_questions: own Q + no reply + > 24h → flagged
  (g) _detect_unanswered_questions: own Q + no reply but recent → not flagged
  (h) _detect_unanswered_questions: only counts BLOCKED cards
  (i) _detect_unanswered_questions: skips cards with no own Q
  (j) cmd_sync_summary integration: returns staleDoing[] + unansweredQuestions[]
       in JSON; summary text contains the blocks when non-empty
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timedelta, timezone

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"
sys.path.insert(0, str(REPO / "plugins" / "kanban"))

from drivers.base import Comment, CommentKind, Task, TaskFilter  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "jira_setup_mod", str(PLUGIN / "scripts" / "jira_setup.py")
)
_jira_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_jira_setup)  # type: ignore[union-attr]


def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


# --- _parse_iso --------------------------------------------------------


def test_parse_iso_variants():
    fn = _jira_setup._parse_iso
    assert fn("2026-04-30T10:00:00+08:00") is not None
    assert fn("2026-04-30T10:00:00Z") is not None
    assert fn(None) is None
    assert fn("") is None
    assert fn("garbage") is None


# --- _detect_stale_doing -----------------------------------------------


class _StubDriver:
    """Minimal driver stub for the detectors. Lets tests inject task and
    comment lists per call."""

    def __init__(self, *, doing=(), blocked=(), comments=None):
        self._doing = list(doing)
        self._blocked = list(blocked)
        self._comments_by_key = comments or {}

    def list_tasks(self, filter: TaskFilter | None = None) -> list[Task]:
        if filter and filter.column == "DOING":
            return list(self._doing)
        if filter and filter.column == "BLOCKED":
            return list(self._blocked)
        return []

    def list_comments(self, key: str) -> list[Comment]:
        return list(self._comments_by_key.get(key, []))


def _mk_task(key: str, *, column: str = "DOING", updated_iso: str = "",
             title: str = "x", priority: str = "P1") -> Task:
    return Task(
        id=key, title=title, column=column, priority=priority,
        created="x", updated=updated_iso,
    )


def test_stale_doing_flags_old_cards():
    old = _now() - timedelta(days=3)
    fresh = _now() - timedelta(hours=4)
    drv = _StubDriver(doing=[
        _mk_task("AGENT-1", updated_iso=_iso(old), title="dusty"),
        _mk_task("AGENT-2", updated_iso=_iso(fresh), title="fresh"),
    ])
    out = _jira_setup._detect_stale_doing(drv, repo_ap="agent-fin")
    assert len(out) == 1
    assert out[0]["key"] == "AGENT-1"
    assert out[0]["days_idle"] >= 2
    assert "fresh" not in (out[0].get("title") or "")


def test_stale_doing_empty_when_no_cards():
    drv = _StubDriver(doing=[])
    assert _jira_setup._detect_stale_doing(drv, repo_ap="agent-fin") == []


def test_stale_doing_handles_bad_timestamps():
    drv = _StubDriver(doing=[
        _mk_task("AGENT-3", updated_iso="not-a-date", title="bad ts"),
    ])
    # Doesn't crash, just skips
    assert _jira_setup._detect_stale_doing(drv, repo_ap="agent-fin") == []


# --- _detect_unanswered_questions --------------------------------------


def _mk_comment(author: str, kind: CommentKind, ts_iso: str,
                text: str = "") -> Comment:
    return Comment(author=author, ts=ts_iso, text=text, kind=kind)


def test_unanswered_q_replied_skipped():
    """Own Q at T1, human reply at T2 > T1 → not flagged."""
    long_ago = _now() - timedelta(days=2)
    after = _now() - timedelta(days=2, hours=-1)  # later
    drv = _StubDriver(
        blocked=[_mk_task("AGENT-99", column="BLOCKED",
                          updated_iso=_iso(_now() - timedelta(days=2)))],
        comments={
            "AGENT-99": [
                _mk_comment("agent-fin", CommentKind.QUESTION, _iso(long_ago),
                            text="should I use library X?"),
                _mk_comment("Kirin", CommentKind.COMMENT, _iso(after),
                            text="use Y."),
            ],
        },
    )
    out = _jira_setup._detect_unanswered_questions(drv, repo_ap="agent-fin")
    assert out == []


def test_unanswered_q_old_no_reply_flagged():
    """Own Q from 2d ago, no later comment → flagged."""
    long_ago = _now() - timedelta(days=2)
    drv = _StubDriver(
        blocked=[_mk_task("AGENT-99", column="BLOCKED",
                          updated_iso=_iso(long_ago))],
        comments={
            "AGENT-99": [
                _mk_comment("agent-fin", CommentKind.QUESTION, _iso(long_ago),
                            text="should I use library X?"),
            ],
        },
    )
    out = _jira_setup._detect_unanswered_questions(drv, repo_ap="agent-fin")
    assert len(out) == 1
    assert out[0]["key"] == "AGENT-99"
    assert "should I use library X?" in out[0]["question"]
    assert out[0]["hours_idle"] >= 24


def test_unanswered_q_recent_not_flagged():
    """Own Q from 2h ago — too recent, give the human time."""
    recent = _now() - timedelta(hours=2)
    drv = _StubDriver(
        blocked=[_mk_task("AGENT-99", column="BLOCKED",
                          updated_iso=_iso(recent))],
        comments={
            "AGENT-99": [
                _mk_comment("agent-fin", CommentKind.QUESTION, _iso(recent),
                            text="thoughts?"),
            ],
        },
    )
    out = _jira_setup._detect_unanswered_questions(drv, repo_ap="agent-fin")
    assert out == []


def test_unanswered_q_skips_cards_with_no_own_q():
    """BLOCKED card with only human / other-AP comments — skip."""
    long_ago = _now() - timedelta(days=2)
    drv = _StubDriver(
        blocked=[_mk_task("AGENT-99", column="BLOCKED",
                          updated_iso=_iso(long_ago))],
        comments={
            "AGENT-99": [
                _mk_comment("Kirin", CommentKind.COMMENT, _iso(long_ago),
                            text="please block on infra"),
                _mk_comment("agent-other", CommentKind.QUESTION, _iso(long_ago),
                            text="from a different agent"),
            ],
        },
    )
    out = _jira_setup._detect_unanswered_questions(drv, repo_ap="agent-fin")
    assert out == []


def test_unanswered_q_no_repo_ap_returns_empty():
    drv = _StubDriver()
    assert _jira_setup._detect_unanswered_questions(drv, repo_ap=None) == []


# --- cmd_sync_summary integration --------------------------------------


def _seed_kanban(td) -> pathlib.Path:
    p = pathlib.Path(td) / "kanban.json"
    p.write_text(json.dumps({
        "version": "0.2",
        "backend": {"driver": "jira", "jira": {
            "boardUrl": "https://x/jira/projects/AGENT/boards/1",
            "boardId": 1, "projectKey": "AGENT",
            "agentAccountId": "5e-bot",
            "transitions": {
                "TODO": {"status": "To Do"},
                "DOING": {"status": "In Progress"},
                "BLOCKED": {"status": "In Progress",
                            "addLabels": ["kanban:blocked"]},
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
        rc = fn(args)
        out = sys.stdout.getvalue()
    finally:
        sys.stdout = old
    return rc, out


def test_sync_summary_includes_stale_and_unanswered():
    long_ago = _now() - timedelta(days=3)
    older_q = _now() - timedelta(days=2)

    class _SyncStub:
        name = "jira"
        def list_tasks(self, filter=None):
            if filter and filter.column == "DOING":
                return [_mk_task("AGENT-1", column="DOING",
                                 updated_iso=_iso(long_ago),
                                 title="grid pricing")]
            if filter and filter.column == "BLOCKED":
                return [_mk_task("AGENT-9", column="BLOCKED",
                                 updated_iso=_iso(older_q),
                                 title="blocked thing")]
            return []
        def list_comments(self, key):
            if key == "AGENT-9":
                return [_mk_comment("agent-fin", CommentKind.QUESTION,
                                    _iso(older_q),
                                    text="library X or Y?")]
            return []

    with tempfile.TemporaryDirectory() as td:
        kp = _seed_kanban(td)
        # No credentials => mentions block fails silently. We only care
        # about the stale + unanswered blocks for this test.
        import drivers as _drv_mod
        orig = _drv_mod.get_driver
        _drv_mod.get_driver = lambda data, root: _SyncStub()
        try:
            class A:
                kanban_path = str(kp)
            rc, out = _capture(_jira_setup.cmd_sync_summary, A())
        finally:
            _drv_mod.get_driver = orig
        assert rc == 0, out
        j = json.loads(out)
        assert len(j["staleDoing"]) == 1
        assert j["staleDoing"][0]["key"] == "AGENT-1"
        assert len(j["unansweredQuestions"]) == 1
        assert j["unansweredQuestions"][0]["key"] == "AGENT-9"
        # The summary text contains both blocks
        assert "[stale DOING" in j["summary"]
        assert "[unanswered questions" in j["summary"]
        assert "AGENT-1" in j["summary"]
        assert "AGENT-9" in j["summary"]


def test_sync_summary_omits_blocks_when_clean():
    """When nothing is stale / unanswered, the blocks don't appear."""
    class _CleanStub:
        name = "jira"
        def list_tasks(self, filter=None): return []
        def list_comments(self, key): return []

    with tempfile.TemporaryDirectory() as td:
        kp = _seed_kanban(td)
        import drivers as _drv_mod
        orig = _drv_mod.get_driver
        _drv_mod.get_driver = lambda data, root: _CleanStub()
        try:
            class A:
                kanban_path = str(kp)
            rc, out = _capture(_jira_setup.cmd_sync_summary, A())
        finally:
            _drv_mod.get_driver = orig
        assert rc == 0
        j = json.loads(out)
        assert j["staleDoing"] == []
        assert j["unansweredQuestions"] == []
        assert "[stale DOING" not in j["summary"]
        assert "[unanswered questions" not in j["summary"]


def main() -> int:
    cases = [
        ("parse_iso_variants", test_parse_iso_variants),
        ("stale_doing_flags_old_cards", test_stale_doing_flags_old_cards),
        ("stale_doing_empty_when_no_cards", test_stale_doing_empty_when_no_cards),
        ("stale_doing_handles_bad_timestamps", test_stale_doing_handles_bad_timestamps),
        ("unanswered_q_replied_skipped", test_unanswered_q_replied_skipped),
        ("unanswered_q_old_no_reply_flagged", test_unanswered_q_old_no_reply_flagged),
        ("unanswered_q_recent_not_flagged", test_unanswered_q_recent_not_flagged),
        ("unanswered_q_skips_cards_with_no_own_q",
         test_unanswered_q_skips_cards_with_no_own_q),
        ("unanswered_q_no_repo_ap_returns_empty", test_unanswered_q_no_repo_ap_returns_empty),
        ("sync_summary_includes_stale_and_unanswered",
         test_sync_summary_includes_stale_and_unanswered),
        ("sync_summary_omits_blocks_when_clean", test_sync_summary_omits_blocks_when_clean),
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
    print("phase13: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
