#!/usr/bin/env python3
"""Phase 1 regression checks for the kanban v0.2 driver-abstraction milestone.

Run from anywhere:
    python3 plugins/kanban/scripts/test_phase1.py

Covers:
  (a) v0.1 (`schema_version: 1`) → reader produces normalized v0.2 dict
  (b) v0.2 → writer round-trip stable, no `schema_version` leak
  (c) missing `backend` → defaults to {driver: local}
  (d) credentials atomic write preserves unrelated prefixes byte-for-byte
  (e) LocalDriver smoke test: create / transition / block / done lifecycle
  (f) session-check.sh: surfaces local-mode tasks; emits nothing in jira mode
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


def _seed_meta() -> dict:
    return {
        "priorities": ["P0", "P1", "P2"],
        "categories": [],
        "columns": ["TODO", "DOING", "DONE", "BLOCKED"],
        "created_at": "2026-04-29T00:00:00+08:00",
        "updated_at": "2026-04-29T00:00:00+08:00",
    }


def test_kanban_io():
    from lib import kanban_io

    # (a) v0.1 normalize
    v01 = {
        "$schema": "./kanban.schema.json",
        "schema_version": 1,
        "meta": _seed_meta(),
        "tasks": [],
    }
    norm = kanban_io.normalize(v01)
    assert norm["version"] == "0.2"
    assert norm["backend"] == {"driver": "local"}
    assert "schema_version" not in norm

    # (b) v0.2 round-trip
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "kanban.json"
        p.write_text(json.dumps(v01))
        loaded = kanban_io.load(p)
        kanban_io.save(p, loaded)
        written = json.loads(p.read_text())
        assert written["version"] == "0.2"
        assert "schema_version" not in written
        assert written["backend"] == {"driver": "local"}

    # (c) missing backend defaults
    bare = {"schema_version": 1, "meta": _seed_meta(), "tasks": []}
    norm = kanban_io.normalize(bare)
    assert norm["backend"] == {"driver": "local"}

    # jira backend preserved
    j = {
        "version": "0.2",
        "backend": {"driver": "jira", "jira": {"projectKey": "AGENT"}},
        "meta": _seed_meta(),
        "tasks": [],
    }
    norm = kanban_io.normalize(j)
    assert norm["backend"]["driver"] == "jira"
    assert norm["backend"]["jira"]["projectKey"] == "AGENT"


def test_credentials_isolation():
    from lib import credentials

    with tempfile.TemporaryDirectory() as td:
        # Override module-level paths.
        credentials.ENV_DIR = pathlib.Path(td)
        credentials.ENV_FILE = pathlib.Path(td) / ".env"

        # Existing PUSHOVER_* lines must survive a JIRA_* write.
        credentials.write(
            {"PUSHOVER_USER_KEY": "uABC", "PUSHOVER_APP_TOKEN": "aXYZ"},
            prefix="PUSHOVER_",
        )
        credentials.write(
            {"JIRA_BASE_URL": "https://x.atlassian.net", "JIRA_API_TOKEN": "tok"},
            prefix="JIRA_",
        )
        all_keys = credentials.read()
        assert all_keys["PUSHOVER_USER_KEY"] == "uABC"
        assert all_keys["PUSHOVER_APP_TOKEN"] == "aXYZ"
        assert all_keys["JIRA_BASE_URL"] == "https://x.atlassian.net"

        # Rewriting JIRA_* must not touch PUSHOVER_*.
        credentials.write(
            {"JIRA_BASE_URL": "https://new.atlassian.net"}, prefix="JIRA_"
        )
        all_keys = credentials.read()
        assert all_keys["PUSHOVER_USER_KEY"] == "uABC"
        assert all_keys["JIRA_BASE_URL"] == "https://new.atlassian.net"

        # Wrong prefix is refused.
        try:
            credentials.write({"PUSHOVER_USER_KEY": "y"}, prefix="JIRA_")
            assert False, "should have raised"
        except ValueError:
            pass

        # Mode tightening.
        credentials.ENV_FILE.chmod(0o644)
        assert credentials.ensure_mode() is False
        assert (credentials.ENV_FILE.stat().st_mode & 0o777) == 0o600


def test_local_driver():
    from drivers import get_driver
    from drivers.base import HumanRef, NotSupported, TaskFilter, TaskInput

    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        seed = {
            "version": "0.2",
            "backend": {"driver": "local"},
            "meta": _seed_meta(),
            "tasks": [],
        }
        (proj / "kanban.json").write_text(json.dumps(seed))
        drv = get_driver(seed, proj)
        assert drv.name == "local"

        t = drv.create_task(TaskInput(title="hello", priority="P1"))
        assert t.id == "task-001" and t.column == "TODO"
        assert len(drv.list_tasks(TaskFilter(column="TODO"))) == 1

        drv.transition("task-001", "DOING")
        drv.assign("task-001", HumanRef(accountId="kirin"))
        assert drv.get_task("task-001").assignee.accountId == "kirin"

        drv.create_task(TaskInput(title="x", priority="P2"))
        try:
            drv.transition("task-002", "BLOCKED")
            assert False
        except ValueError:
            pass
        drv.transition("task-002", "BLOCKED", reason="waiting on infra")
        assert drv.get_task("task-002").custom["blocked_reason"] == "waiting on infra"

        drv.transition("task-001", "DONE")
        try:
            drv.transition("task-001", "TODO")
            assert False
        except ValueError:
            pass

        try:
            drv.list_aps()
            assert False
        except NotSupported:
            pass

        # File still in v0.2 form after all writes.
        on_disk = json.loads((proj / "kanban.json").read_text())
        assert on_disk["version"] == "0.2"
        assert on_disk["backend"] == {"driver": "local"}


def test_session_check_hook():
    script = PLUGIN / "scripts" / "kanban-session-check.sh"
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        data = {
            "version": "0.2",
            "backend": {"driver": "local"},
            "meta": _seed_meta(),
            "tasks": [
                {
                    "id": "task-001",
                    "title": "doing thing",
                    "column": "DOING",
                    "priority": "P1",
                    "created": "2026-04-29T00:00:00+08:00",
                    "updated": "2026-04-29T00:00:00+08:00",
                    "started": "2026-04-29T01:00:00+08:00",
                }
            ],
        }
        (proj / "kanban.json").write_text(json.dumps(data))
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(proj)
        out = subprocess.run(
            ["bash", str(script)], env=env, capture_output=True, text=True
        )
        assert out.returncode == 0, out.stderr
        assert "task-001" in out.stdout

        # jira mode → no surfacing
        data["backend"] = {"driver": "jira"}
        (proj / "kanban.json").write_text(json.dumps(data))
        out = subprocess.run(
            ["bash", str(script)], env=env, capture_output=True, text=True
        )
        assert out.returncode == 0
        assert "task-001" not in out.stdout

        # v0.1 legacy file
        (proj / "kanban.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "meta": _seed_meta(),
                    "tasks": [
                        {
                            "id": "task-001",
                            "title": "legacy",
                            "column": "DOING",
                            "priority": "P0",
                            "created": "2026-04-29T00:00:00+08:00",
                            "updated": "2026-04-29T00:00:00+08:00",
                            "started": "2026-04-29T00:00:00+08:00",
                        }
                    ],
                }
            )
        )
        out = subprocess.run(
            ["bash", str(script)], env=env, capture_output=True, text=True
        )
        assert out.returncode == 0
        assert "task-001" in out.stdout


def main() -> int:
    cases = [
        ("kanban_io", test_kanban_io),
        ("credentials_isolation", test_credentials_isolation),
        ("local_driver", test_local_driver),
        ("session_check_hook", test_session_check_hook),
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
    print("phase1: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
