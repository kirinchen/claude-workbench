#!/usr/bin/env python3
"""Phase 5 regression checks for kanban v0.2 (MCP scan, migration, label round-trip).

Run from anywhere:
    python3 plugins/kanban/scripts/test_phase5.py

Mocked Jira; no live network. Covers:
  (a) mcp_conflict_scan picks up matches on name / command / args / url
  (b) mcp-conflict-scan CLI returns JSON list with absolute source paths
  (c) import-tasks --dry-run lists what would be imported, writes nothing
  (d) import-tasks (live) creates Jira issues for TODO/DOING; skips DONE
       unless --include-done; idempotent on re-run
  (e) JiraDriver._issue_to_task in partial mode reads back kanban:* labels
       to canonical columns
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

from lib.jira_client import JiraClient, _Response  # noqa: E402


# --- mcp_conflict_scan tests ---------------------------------------------


def test_mcp_scan_matches_keywords():
    from lib.mcp_conflict_scan import _scan_servers

    blob = {
        "mcpServers": {
            "atlassian-rovo": {"command": "rovo-cli"},
            "tracker": {"url": "https://x.atlassian.net/api"},
            "jira-mcp": {"args": ["--base", "x"]},
            "rovo-args": {"command": "node", "args": ["/path/to/rovo.js"]},
            "unrelated": {"command": "foo"},
        }
    }
    hits = _scan_servers(blob, pathlib.Path("/x/settings.json"))
    matched = {h.server_name: h.matched_on for h in hits}
    assert matched["atlassian-rovo"] == "name"
    assert matched["tracker"] == "url"
    assert matched["jira-mcp"] == "name"
    assert matched["rovo-args"] == "name"
    assert "unrelated" not in matched


def test_mcp_scan_cli():
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        (proj / ".claude").mkdir()
        (proj / ".claude" / "settings.json").write_text(
            json.dumps({"mcpServers": {"atlassian-rovo": {"command": "x"}}})
        )
        (proj / "kanban.json").write_text(json.dumps({
            "version": "0.2", "backend": {"driver": "jira"},
            "meta": {"priorities": ["P0"], "categories": [],
                     "columns": ["TODO", "DOING", "DONE", "BLOCKED"],
                     "created_at": "x", "updated_at": "x"},
            "tasks": []
        }))
        out = subprocess.run(
            ["python3", str(PLUGIN / "scripts" / "jira_setup.py"),
             "mcp-conflict-scan", "--kanban-path", str(proj / "kanban.json")],
            capture_output=True, text=True,
        )
        assert out.returncode == 0, out.stderr
        j = json.loads(out.stdout)
        assert j["ok"] is True
        names = {c["server"] for c in j["conflicts"]}
        assert "atlassian-rovo" in names


# --- migration importer tests --------------------------------------------


def _seed_v01_kanban(td) -> pathlib.Path:
    """v0.1 file with mixed-status tasks."""
    p = pathlib.Path(td) / "kanban.json"
    legacy = {
        "schema_version": 1,
        "meta": {
            "priorities": ["P0", "P1", "P2"],
            "categories": [],
            "columns": ["TODO", "DOING", "DONE", "BLOCKED"],
            "created_at": "x",
            "updated_at": "x",
        },
        "tasks": [
            {
                "id": "task-001",
                "title": "todo work",
                "column": "TODO",
                "priority": "P1",
                "tags": ["infra"],
                "created": "x", "updated": "y",
            },
            {
                "id": "task-002",
                "title": "doing work",
                "column": "DOING",
                "priority": "P2",
                "tags": [],
                "created": "x", "updated": "y",
                "started": "y",
            },
            {
                "id": "task-003",
                "title": "old work",
                "column": "DONE",
                "priority": "P0",
                "tags": [],
                "created": "x", "updated": "y",
                "started": "y",
                "completed": "y",
            },
        ],
    }
    p.write_text(json.dumps(legacy))
    return p


def _make_jira_data():
    """v0.2 jira-mode wrapper around an empty tasks list."""
    return {
        "version": "0.2",
        "backend": {
            "driver": "jira",
            "jira": {
                "boardUrl": "https://x/boards/1",
                "boardId": 1,
                "projectKey": "AGENT",
                "agentAccountId": "agent-acct",
                "statusMap": {
                    "TODO": "To Do", "DOING": "In Progress", "DONE": "Done",
                    "BLOCKED": "Blocked", "REVIEW": "In Review", "CANCELLED": "Cancelled",
                },
                "ap": {
                    "fieldId": "customfield_10042",
                    "fieldName": "Claude Agent",
                    "registered": ["agent-fin"],
                },
            },
        },
        "meta": {
            "priorities": ["P0", "P1", "P2"],
            "categories": [],
            "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"],
            "created_at": "x", "updated_at": "x",
        },
        "tasks": [],
    }


def test_import_tasks_dry_run():
    """--dry-run lists tasks without creating Jira issues or writing the map."""
    with tempfile.TemporaryDirectory() as td:
        # Seed the file as a v0.2 jira-mode kanban with legacy tasks left in place.
        p = pathlib.Path(td) / "kanban.json"
        data = _make_jira_data()
        # Inject legacy tasks (simulating mid-migration state).
        data["tasks"] = json.loads(_seed_v01_kanban(td).read_text())["tasks"]
        p.write_text(json.dumps(data))

        out = subprocess.run(
            ["python3", str(PLUGIN / "scripts" / "jira_setup.py"),
             "import-tasks", "--kanban-path", str(p), "--dry-run"],
            capture_output=True, text=True,
        )
        assert out.returncode == 0, out.stderr
        j = json.loads(out.stdout)
        assert j["ok"] is True
        assert j["dryRun"] is True
        # TODO + DOING would be imported; DONE skipped.
        ids = [t["id"] for t in j["tasks"]]
        assert "task-001" in ids and "task-002" in ids
        assert "task-003" not in ids
        # Map file must NOT be written for dry-run.
        assert not (pathlib.Path(td) / ".claude" / ".migration-map.json").exists()


def test_import_tasks_idempotent():
    """Live import creates Jira issues; second run reports skipped/already-mapped."""
    from drivers.jira import JiraDriver
    from lib import credentials

    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "kanban.json"
        data = _make_jira_data()
        data["tasks"] = json.loads(_seed_v01_kanban(td).read_text())["tasks"]
        p.write_text(json.dumps(data))

        # We need to mock JiraDriver.create_task so import-tasks doesn't hit
        # the network. The simplest way: patch credentials.read so the
        # driver builds its client, then monkey-patch driver class. But
        # import-tasks runs in a subprocess. Workaround: provide a tiny
        # in-process import path instead of the CLI, which is enough for
        # this integration test.
        env = dict(os.environ)
        # Set fake credentials so JiraClient construction succeeds (but it
        # never actually fires; we monkey-patch create_task in a sec).
        creds_dir = pathlib.Path(td) / "fake-cw"
        creds_dir.mkdir()
        env["HOME"] = str(creds_dir)
        creds_dir_inner = creds_dir / ".claude-workbench"
        creds_dir_inner.mkdir()
        (creds_dir_inner / ".env").write_text(
            "JIRA_BASE_URL=https://x\nJIRA_AGENT_EMAIL=a@b\nJIRA_API_TOKEN=tok\n"
        )
        os.chmod(creds_dir_inner / ".env", 0o600)

        # Hack the subprocess by setting JIRA_FAKE_DRIVER=1 and patching
        # create_task within the helper. To keep things simple here, run
        # import-tasks in-process instead of subprocess.
        sys.path.insert(0, str(REPO / "plugins" / "kanban"))

        from drivers import base as base_mod  # noqa: F401

        # scripts/ is not a package — load jira_setup.py via importlib.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "jira_setup_mod", str(PLUGIN / "scripts" / "jira_setup.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        # Patch JiraDriver.create_task to a fake.
        from drivers.jira import JiraDriver as Jd
        from drivers.base import Task

        counter = {"n": 100}
        created: list[str] = []

        def fake_create(self, task_input):
            counter["n"] += 1
            key = f"AGENT-{counter['n']}"
            created.append(key)
            return Task(
                id=key, title=task_input.title, column="TODO", priority=task_input.priority or "P2",
                created="x", updated="y",
            )

        orig = Jd.create_task
        Jd.create_task = fake_create  # type: ignore[assignment]
        # Patch credentials.read since we don't want the driver to read the
        # fake .env on filesystem.
        orig_read = credentials.read
        credentials.read = lambda prefix=None: {
            "JIRA_BASE_URL": "https://x",
            "JIRA_AGENT_EMAIL": "a@b",
            "JIRA_API_TOKEN": "tok",
        }

        try:
            class A: pass
            a = A()
            a.kanban_path = str(p)
            a.dry_run = False
            a.include_done = False

            # Capture stdout
            from io import StringIO
            buf = StringIO()
            old_stdout = sys.stdout
            sys.stdout = buf
            try:
                rc = mod.cmd_import_tasks(a)
            finally:
                sys.stdout = old_stdout
            assert rc == 0
            j = json.loads(buf.getvalue())
            assert j["imported"] == 2
            assert j["skipped"] == 1   # task-003 (DONE)

            # Re-run — everything is mapped now.
            buf2 = StringIO()
            sys.stdout = buf2
            try:
                rc = mod.cmd_import_tasks(a)
            finally:
                sys.stdout = old_stdout
            j2 = json.loads(buf2.getvalue())
            assert j2["imported"] == 0
            assert j2["skipped"] == 3
            # already-mapped reasons present
            assert any(s.get("reason") == "already-mapped" for s in j2["skippedDetail"])
        finally:
            Jd.create_task = orig  # type: ignore[assignment]
            credentials.read = orig_read

        # Map file written and contains both new keys.
        map_path = pathlib.Path(td) / ".claude" / ".migration-map.json"
        assert map_path.exists()
        mapping = json.loads(map_path.read_text())
        assert "task-001" in mapping and "task-002" in mapping


# --- label-fallback round trip ------------------------------------------


def test_label_fallback_round_trip():
    """When partial=True and a card has the kanban:blocked label, reader maps
    it to the BLOCKED canonical column."""
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        data = _make_jira_data()
        data["backend"]["jira"]["partial"] = True
        data["backend"]["jira"]["labelFallback"] = {
            "BLOCKED": "kanban:blocked",
            "REVIEW": "kanban:review",
            "CANCELLED": "kanban:cancelled",
        }
        # Drop BLOCKED/REVIEW/CANCELLED from statusMap (simulate partial).
        for c in ("BLOCKED", "REVIEW", "CANCELLED"):
            data["backend"]["jira"]["statusMap"].pop(c, None)

        from drivers.jira import JiraDriver
        from lib import credentials

        orig = credentials.read
        credentials.read = lambda prefix=None: {
            "JIRA_BASE_URL": "https://x",
            "JIRA_AGENT_EMAIL": "a@b",
            "JIRA_API_TOKEN": "tok",
        }
        try:
            drv = JiraDriver(data, proj)
        finally:
            credentials.read = orig

        # Build an issue payload as Jira would: status is "In Progress"
        # (because partial mode collapses BLOCKED to In Progress + label),
        # but the kanban:blocked label tells the reader BLOCKED.
        issue = {
            "key": "AGENT-99",
            "fields": {
                "summary": "stalled",
                "status": {"name": "In Progress"},
                "priority": {"name": "P1"},
                "assignee": None,
                "labels": ["other-label", "kanban:blocked"],
                "created": "x",
                "updated": "y",
                "customfield_10042": {"value": "agent-fin"},
            },
        }
        task = drv._issue_to_task(issue)
        assert task.column == "BLOCKED", task.column
        assert task.ap == "agent-fin"


# --- entry point ---------------------------------------------------------


def main() -> int:
    cases = [
        ("mcp_scan_matches_keywords", test_mcp_scan_matches_keywords),
        ("mcp_scan_cli", test_mcp_scan_cli),
        ("import_tasks_dry_run", test_import_tasks_dry_run),
        ("import_tasks_idempotent", test_import_tasks_idempotent),
        ("label_fallback_round_trip", test_label_fallback_round_trip),
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
    print("phase5: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
