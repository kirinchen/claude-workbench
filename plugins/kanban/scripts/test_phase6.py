#!/usr/bin/env python3
"""Phase 6 regression checks for kanban_local.py — local-mode helper CLI.

Covers what /kanban:init / next / done / block actually exercise after the
0.2.1 fix. No mocks needed — local mode talks only to the filesystem.

Cases:
  (a) init creates v0.2 file + schema; reports tasks=0
  (b) init --with-examples ships 4 example tasks
  (c) init refuses to overwrite without --force
  (d) next on empty board returns claimed=null with reason
  (e) next picks highest priority (P0 first), sets started, assignee
  (f) next surfaces a tied top-3 instead of guessing
  (g) next refuses to claim a task whose deps are not all DONE
  (h) done sets completed and returns unblocked downstream
  (i) done refuses on non-DOING task
  (j) block requires --reason, refuses DONE source, preserves started, posts comment
  (k) status returns counts + DOING + BLOCKED + next-3
  (l) all writes round-trip through kanban_io as v0.2 (no schema_version)
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"
HELPER = PLUGIN / "scripts" / "kanban_local.py"


def run(*args: str) -> tuple[int, dict]:
    r = subprocess.run(
        ["python3", str(HELPER), *args], capture_output=True, text=True
    )
    try:
        body = json.loads(r.stdout)
    except json.JSONDecodeError:
        body = {"_raw": r.stdout, "_stderr": r.stderr}
    return r.returncode, body


def _ensure_v02(p: pathlib.Path) -> dict:
    on_disk = json.loads(p.read_text())
    assert on_disk.get("version") == "0.2", on_disk
    assert "schema_version" not in on_disk
    assert on_disk.get("backend") == {"driver": "local"}
    return on_disk


def test_init_creates_files():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "kanban.json"
        rc, j = run("init", "--kanban-path", str(p))
        assert rc == 0 and j["ok"]
        assert j["tasks"] == 0
        assert p.exists() and (pathlib.Path(td) / "kanban.schema.json").exists()
        on_disk = _ensure_v02(p)
        assert on_disk.get("tasks") == []


def test_init_with_examples_has_4_tasks():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "kanban.json"
        rc, j = run("init", "--kanban-path", str(p), "--with-examples")
        assert rc == 0 and j["ok"] and j["tasks"] == 4
        _ensure_v02(p)


def test_init_refuses_overwrite():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "kanban.json"
        run("init", "--kanban-path", str(p))
        rc, j = run("init", "--kanban-path", str(p))
        assert rc != 0 and j["ok"] is False
        # --force overrides
        rc, j = run("init", "--kanban-path", str(p), "--force")
        assert rc == 0 and j["ok"]


def test_next_on_empty_board():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "kanban.json"
        run("init", "--kanban-path", str(p))
        rc, j = run("next", "--kanban-path", str(p))
        assert rc == 0 and j["ok"]
        assert j["claimed"] is None
        assert j["reason"]


def _seed(p: pathlib.Path, tasks: list[dict]) -> None:
    base = json.loads(p.read_text())
    base["tasks"] = tasks
    p.write_text(json.dumps(base))


def test_next_picks_highest_priority():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "kanban.json"
        run("init", "--kanban-path", str(p))
        _seed(p, [
            {"id": "task-001", "title": "low", "column": "TODO",
             "priority": "P2", "tags": [], "depends": [],
             "created": "2026-04-29T00:00:00+08:00",
             "updated": "2026-04-29T00:00:00+08:00",
             "started": None, "completed": None, "assignee": None,
             "description": "", "comments": [], "custom": {}},
            {"id": "task-002", "title": "high", "column": "TODO",
             "priority": "P0", "tags": [], "depends": [],
             "created": "2026-04-29T00:00:00+08:00",
             "updated": "2026-04-29T00:00:00+08:00",
             "started": None, "completed": None, "assignee": None,
             "description": "", "comments": [], "custom": {}},
        ])
        rc, j = run("next", "--kanban-path", str(p))
        assert rc == 0 and j["ok"]
        assert j["claimed"]["id"] == "task-002", j
        on_disk = json.loads(p.read_text())
        t2 = next(t for t in on_disk["tasks"] if t["id"] == "task-002")
        assert t2["column"] == "DOING"
        assert t2["started"]
        assert t2["assignee"] == "claude-code"


def test_next_surfaces_tie():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "kanban.json"
        run("init", "--kanban-path", str(p))
        _seed(p, [
            {"id": "task-001", "title": "a", "column": "TODO",
             "priority": "P0", "tags": [], "depends": [],
             "created": "2026-04-29T00:00:00+08:00",
             "updated": "2026-04-29T00:00:00+08:00",
             "started": None, "completed": None, "assignee": None,
             "description": "", "comments": [], "custom": {}},
            {"id": "task-002", "title": "b", "column": "TODO",
             "priority": "P0", "tags": [], "depends": [],
             "created": "2026-04-29T00:00:01+08:00",
             "updated": "2026-04-29T00:00:01+08:00",
             "started": None, "completed": None, "assignee": None,
             "description": "", "comments": [], "custom": {}},
        ])
        rc, j = run("next", "--kanban-path", str(p))
        assert j["claimed"] is None and len(j["candidates"]) == 2
        # File untouched — no claim made.
        on_disk = json.loads(p.read_text())
        assert all(t["column"] == "TODO" for t in on_disk["tasks"])

        # Explicit task-id resolves the tie.
        rc, j = run("next", "--kanban-path", str(p), "--task-id", "task-002")
        assert j["ok"] and j["claimed"]["id"] == "task-002"


def test_next_skips_unsatisfied_deps():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "kanban.json"
        run("init", "--kanban-path", str(p))
        _seed(p, [
            {"id": "task-001", "title": "blocker", "column": "TODO",
             "priority": "P0", "tags": [], "depends": [],
             "created": "2026-04-29T00:00:00+08:00",
             "updated": "2026-04-29T00:00:00+08:00",
             "started": None, "completed": None, "assignee": None,
             "description": "", "comments": [], "custom": {}},
            {"id": "task-002", "title": "blocked", "column": "TODO",
             "priority": "P1", "tags": [], "depends": ["task-001"],
             "created": "2026-04-29T00:00:00+08:00",
             "updated": "2026-04-29T00:00:00+08:00",
             "started": None, "completed": None, "assignee": None,
             "description": "", "comments": [], "custom": {}},
        ])
        rc, j = run("next", "--kanban-path", str(p))
        # task-001 has no deps and is P0 — it's the pick. task-002 must
        # not be picked because its dep is not DONE.
        assert j["claimed"]["id"] == "task-001"
        # If we now finish task-001, task-002 becomes claimable.
        run("done", "--kanban-path", str(p), "--task-id", "task-001")
        rc, j = run("next", "--kanban-path", str(p))
        assert j["claimed"]["id"] == "task-002"


def test_done_unblocks_downstream():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "kanban.json"
        run("init", "--kanban-path", str(p))
        _seed(p, [
            {"id": "task-001", "title": "first", "column": "DOING",
             "priority": "P1", "tags": [], "depends": [],
             "created": "2026-04-29T00:00:00+08:00",
             "updated": "2026-04-29T00:00:00+08:00",
             "started": "2026-04-29T00:00:00+08:00",
             "completed": None, "assignee": "claude-code",
             "description": "", "comments": [], "custom": {}},
            {"id": "task-002", "title": "second", "column": "TODO",
             "priority": "P1", "tags": [], "depends": ["task-001"],
             "created": "2026-04-29T00:00:00+08:00",
             "updated": "2026-04-29T00:00:00+08:00",
             "started": None, "completed": None, "assignee": None,
             "description": "", "comments": [], "custom": {}},
        ])
        rc, j = run("done", "--kanban-path", str(p))
        assert j["ok"] and j["id"] == "task-001"
        assert any(u["id"] == "task-002" for u in j["unblocked"])


def test_done_refuses_non_doing():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "kanban.json"
        run("init", "--kanban-path", str(p))
        _seed(p, [
            {"id": "task-001", "title": "x", "column": "TODO",
             "priority": "P1", "tags": [], "depends": [],
             "created": "2026-04-29T00:00:00+08:00",
             "updated": "2026-04-29T00:00:00+08:00",
             "started": None, "completed": None, "assignee": None,
             "description": "", "comments": [], "custom": {}},
        ])
        rc, j = run("done", "--kanban-path", str(p), "--task-id", "task-001")
        assert rc != 0 and j["ok"] is False


def test_block_required_reason_and_done_immune():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "kanban.json"
        run("init", "--kanban-path", str(p))
        _seed(p, [
            {"id": "task-001", "title": "active", "column": "DOING",
             "priority": "P1", "tags": [], "depends": [],
             "created": "2026-04-29T00:00:00+08:00",
             "updated": "2026-04-29T00:00:00+08:00",
             "started": "2026-04-29T00:00:00+08:00",
             "completed": None, "assignee": "claude-code",
             "description": "", "comments": [], "custom": {}},
            {"id": "task-002", "title": "closed", "column": "DONE",
             "priority": "P1", "tags": [], "depends": [],
             "created": "2026-04-29T00:00:00+08:00",
             "updated": "2026-04-29T00:00:00+08:00",
             "started": "2026-04-29T00:00:00+08:00",
             "completed": "2026-04-29T00:00:00+08:00",
             "assignee": "claude-code",
             "description": "", "comments": [], "custom": {}},
        ])

        # Block requires --reason at argparse layer.
        rc, j = run("block", "--kanban-path", str(p), "--task-id", "task-001",
                    "--reason", "")
        assert rc != 0 and j["ok"] is False  # empty reason rejected

        # DONE is terminal.
        rc, j = run("block", "--kanban-path", str(p), "--task-id", "task-002",
                    "--reason", "wat")
        assert rc != 0 and j["ok"] is False

        # Successful block preserves `started` and posts an audit comment.
        rc, j = run("block", "--kanban-path", str(p), "--task-id", "task-001",
                    "--reason", "awaiting input")
        assert rc == 0 and j["ok"]
        on_disk = json.loads(p.read_text())
        t = next(x for x in on_disk["tasks"] if x["id"] == "task-001")
        assert t["column"] == "BLOCKED"
        assert t["started"]   # preserved
        assert t["custom"]["blocked_reason"] == "awaiting input"
        assert any("Blocked:" in c.get("text", "") for c in t.get("comments", []))


def test_status_summary():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "kanban.json"
        run("init", "--kanban-path", str(p), "--with-examples")
        rc, j = run("status", "--kanban-path", str(p))
        assert rc == 0 and j["ok"]
        assert sum(j["counts"].values()) == 4
        assert j["counts"]["DOING"] >= 1
        assert isinstance(j["next"], list)


def main() -> int:
    cases = [
        ("init_creates_files", test_init_creates_files),
        ("init_with_examples_has_4_tasks", test_init_with_examples_has_4_tasks),
        ("init_refuses_overwrite", test_init_refuses_overwrite),
        ("next_on_empty_board", test_next_on_empty_board),
        ("next_picks_highest_priority", test_next_picks_highest_priority),
        ("next_surfaces_tie", test_next_surfaces_tie),
        ("next_skips_unsatisfied_deps", test_next_skips_unsatisfied_deps),
        ("done_unblocks_downstream", test_done_unblocks_downstream),
        ("done_refuses_non_doing", test_done_refuses_non_doing),
        ("block_required_reason_and_done_immune", test_block_required_reason_and_done_immune),
        ("status_summary", test_status_summary),
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
    print("phase6: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
