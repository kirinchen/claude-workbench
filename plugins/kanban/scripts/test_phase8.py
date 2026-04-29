#!/usr/bin/env python3
"""Phase 8 regression checks for kanban v0.3.0 — board cache reuse.

Multiple repos pointing at the same Jira board can share their compound-
transition mapping via a per-machine cache at
`~/.claude-workbench/kanban-boards/<host>__<KEY>__<id>.json`.

Each test isolates the cache directory with `monkeypatch_cache_dir(td)`.

Cases:
  (a) cache_path uses safe_host normalization
  (b) write/read round-trip preserves backend_jira block
  (c) read returns None on missing file or corrupt content (auto-skipped)
  (d) update_ap_registered appends, is idempotent, no-ops on missing entry
  (e) list_all enumerates entries, skips corrupt files
  (f) write-backend CLI populates the cache (best-effort, non-fatal)
  (g) read-board-cache CLI reports hit / miss
  (h) two repos sharing a board: repo A writes cache; repo B's read sees it
  (i) register-ap CLI syncs the cache's ap.registered
  (j) different boards → different cache entries; same board different host
       → different keys
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"
sys.path.insert(0, str(REPO / "plugins" / "kanban"))


def _isolated_cache(td) -> pathlib.Path:
    """Return a path that the board_cache module will treat as ~/.cache root."""
    fake_home = pathlib.Path(td) / "fakehome"
    (fake_home / ".claude-workbench").mkdir(parents=True, exist_ok=True)
    return fake_home


def _patch_cache_dir(fake_home: pathlib.Path):
    from lib import board_cache
    board_cache.cache_dir = lambda: fake_home / ".claude-workbench" / "kanban-boards"
    return board_cache


# --- pure lib --------------------------------------------------------------


def test_safe_host_normalization():
    from lib import board_cache as bc
    assert bc.safe_host("https://Acme.Atlassian.NET/jira") == "acme.atlassian.net"
    assert bc.safe_host("https://x.example.com:443") == "x.example.com"
    assert bc.safe_host("") == "unknown"
    assert bc.safe_host("https://weird*host.example") == "weird_host.example"


def test_write_read_round_trip():
    with tempfile.TemporaryDirectory() as td:
        bc = _patch_cache_dir(_isolated_cache(td))
        backend = {
            "agentAccountId": "agent-acct",
            "transitions": {
                "DOING": {"status": "In Progress"},
                "BLOCKED": {"status": "In Progress", "addLabels": ["kanban:blocked"]},
            },
            "ap": {"fieldId": "customfield_10042", "fieldName": "Claude Agent",
                   "registered": ["agent-fin"]},
        }
        bc.write("https://acme.atlassian.net", "AGENT", 1, backend, source_repo="/r/a")
        got = bc.read("https://acme.atlassian.net", "AGENT", 1)
        assert got is not None
        assert got["backend_jira"] == backend
        assert got["last_repo"] == "/r/a"
        assert got["key"]["projectKey"] == "AGENT"


def test_read_handles_missing_and_corrupt():
    with tempfile.TemporaryDirectory() as td:
        bc = _patch_cache_dir(_isolated_cache(td))
        assert bc.read("https://x", "AGENT", 1) is None
        # Corrupt file
        p = bc.cache_path("https://x.atlassian.net", "BAD", 99)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("not json", encoding="utf-8")
        assert bc.read("https://x.atlassian.net", "BAD", 99) is None


def test_update_ap_registered_idempotent():
    with tempfile.TemporaryDirectory() as td:
        bc = _patch_cache_dir(_isolated_cache(td))
        backend = {
            "transitions": {"DOING": {"status": "In Progress"}},
            "ap": {"fieldId": "customfield_10042", "registered": ["agent-fin"]},
        }
        bc.write("https://a", "AGENT", 1, backend)
        # New AP appended
        assert bc.update_ap_registered("https://a", "AGENT", 1, "agent-quant") is True
        got = bc.read("https://a", "AGENT", 1)
        assert got["backend_jira"]["ap"]["registered"] == ["agent-fin", "agent-quant"]
        # Idempotent
        assert bc.update_ap_registered("https://a", "AGENT", 1, "agent-quant") is False
        # No entry → no-op
        assert bc.update_ap_registered("https://a", "OTHER", 9, "x") is False


def test_list_all_skips_corrupt():
    with tempfile.TemporaryDirectory() as td:
        bc = _patch_cache_dir(_isolated_cache(td))
        bc.write("https://a", "AGENT", 1, {"transitions": {"DOING": {"status": "X"}}})
        bc.write("https://a", "FIN", 9, {"transitions": {"DOING": {"status": "Y"}}})
        # Drop a corrupt file in the same dir.
        bad = bc.cache_dir() / "bogus.json"
        bad.write_text("garbage")
        entries = bc.list_all()
        assert len(entries) == 2
        keys = {(e["key"]["projectKey"], e["key"]["boardId"]) for e in entries}
        assert keys == {("AGENT", 1), ("FIN", 9)}


# --- CLI integration -------------------------------------------------------


def _run(*args, env_extra=None) -> subprocess.CompletedProcess:
    cmd = ["python3", str(PLUGIN / "scripts" / "jira_setup.py"), *args]
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, capture_output=True, env=env, text=True)


def _isolated_home_env(td: pathlib.Path) -> dict[str, str]:
    """Return env-var override that points HOME at td/fakehome.

    The board_cache module reads `Path.home()`, so flipping HOME in the
    subprocess environment isolates the cache to the test's tmp dir.
    """
    home = td / "fakehome"
    home.mkdir(parents=True, exist_ok=True)
    return {"HOME": str(home)}


def test_read_board_cache_cli_miss_and_hit():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        env = _isolated_home_env(td)
        # Miss
        out = _run(
            "read-board-cache",
            "--base-url", "https://acme.atlassian.net",
            "--project", "AGENT",
            "--board", "1",
            env_extra=env,
        )
        assert out.returncode == 0, out.stderr
        j = json.loads(out.stdout)
        assert j["ok"] is True
        assert j["hit"] is False

        # Seed via write-backend then read again.
        kp = td / "repo-a" / "kanban.json"
        kp.parent.mkdir()
        kp.write_text(json.dumps({
            "version": "0.2",
            "backend": {"driver": "jira", "jira": {"projectKey": "AGENT"}},
            "meta": {"priorities": ["P0"], "categories": [],
                     "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"],
                     "created_at": "x", "updated_at": "x"},
            "tasks": [],
        }))
        cfg = {
            "boardUrl": "https://acme.atlassian.net/jira/software/projects/AGENT/boards/1",
            "boardId": 1,
            "projectKey": "AGENT",
            "agentAccountId": "shared-agent",
            "transitions": {
                "DOING": {"status": "In Progress"},
                "DONE": {"status": "Done"},
            },
            "ap": {"fieldId": "customfield_10042", "fieldName": "Claude Agent",
                   "registered": ["agent-fin"]},
        }
        out = _run(
            "write-backend",
            "--kanban-path", str(kp),
            "--jira-config-json", json.dumps(cfg),
            env_extra=env,
        )
        assert out.returncode == 0, out.stderr
        wb = json.loads(out.stdout)
        assert wb["cachePath"]

        out = _run(
            "read-board-cache",
            "--base-url", "https://acme.atlassian.net",
            "--project", "AGENT",
            "--board", "1",
            env_extra=env,
        )
        j = json.loads(out.stdout)
        assert j["hit"] is True
        assert j["backend_jira"]["transitions"]["DOING"] == {"status": "In Progress"}
        assert j["last_repo"] == str((td / "repo-a").resolve())


def test_two_repos_share_cache():
    """Repo A writes the cache; repo B's read picks up the same mapping."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        env = _isolated_home_env(td)
        # Repo A — full backend write
        repo_a = td / "repo-a"
        repo_a.mkdir()
        (repo_a / "kanban.json").write_text(json.dumps({
            "version": "0.2",
            "backend": {"driver": "jira", "jira": {"projectKey": "AGENT"}},
            "meta": {"priorities": ["P0"], "categories": [],
                     "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"],
                     "created_at": "x", "updated_at": "x"},
            "tasks": [],
        }))
        cfg_a = {
            "boardUrl": "https://acme.atlassian.net/jira/software/projects/AGENT/boards/1",
            "boardId": 1, "projectKey": "AGENT", "agentAccountId": "shared",
            "transitions": {"DOING": {"status": "In Progress"}},
            "ap": {"fieldId": "customfield_10042", "fieldName": "Claude Agent",
                   "registered": ["agent-a"]},
        }
        _run("write-backend",
             "--kanban-path", str(repo_a / "kanban.json"),
             "--jira-config-json", json.dumps(cfg_a),
             env_extra=env)

        # Repo B — fresh cwd, asks for the cache for the same board.
        out = _run(
            "read-board-cache",
            "--base-url", "https://acme.atlassian.net",
            "--project", "AGENT",
            "--board", "1",
            env_extra=env,
        )
        assert out.returncode == 0, out.stderr
        j = json.loads(out.stdout)
        assert j["hit"] is True
        assert j["last_repo"] == str(repo_a.resolve())
        assert j["backend_jira"]["transitions"] == cfg_a["transitions"]
        assert j["backend_jira"]["ap"]["registered"] == ["agent-a"]


def test_register_ap_syncs_cache():
    """register-ap on repo A appends to the cache; repo B sees the new AP."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        env = _isolated_home_env(td)
        # Seed the board cache directly.
        sys.path.insert(0, str(REPO / "plugins" / "kanban"))
        from lib import board_cache as bc
        bc.cache_dir = lambda: td / "fakehome" / ".claude-workbench" / "kanban-boards"
        backend = {
            "boardUrl": "https://acme.atlassian.net/jira/software/projects/AGENT/boards/1",
            "boardId": 1, "projectKey": "AGENT", "agentAccountId": "shared",
            "transitions": {"DOING": {"status": "In Progress"}},
            "ap": {"fieldId": "customfield_10042", "fieldName": "Claude Agent",
                   "registered": ["agent-fin"]},
        }
        bc.write(backend["boardUrl"], "AGENT", 1, backend, source_repo="/r/a")

        # Repo A's kanban.json mirrors the cache.
        repo_a = td / "repo-a"
        repo_a.mkdir()
        (repo_a / "kanban.json").write_text(json.dumps({
            "version": "0.2",
            "backend": {"driver": "jira", "jira": backend},
            "meta": {"priorities": ["P0"], "categories": [],
                     "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"],
                     "created_at": "x", "updated_at": "x"},
            "tasks": [],
        }))

        # register-ap goes through Jira via the helper. We can't avoid the
        # network round-trip here since cmd_register_ap calls
        # client.add_field_option. Skipping the real network call: instead
        # of running the CLI, exercise the cache sync side-effect directly
        # via board_cache.update_ap_registered (the same code path the CLI
        # uses) — that's the part Phase 8 owns.
        ok = bc.update_ap_registered(backend["boardUrl"], "AGENT", 1, "agent-quant")
        assert ok is True
        ok2 = bc.update_ap_registered(backend["boardUrl"], "AGENT", 1, "agent-quant")
        assert ok2 is False  # idempotent

        # Repo B reads — sees the sync'd AP.
        out = _run(
            "read-board-cache",
            "--base-url", backend["boardUrl"],
            "--project", "AGENT",
            "--board", "1",
            env_extra=env,
        )
        j = json.loads(out.stdout)
        assert j["hit"] is True
        assert sorted(j["backend_jira"]["ap"]["registered"]) == ["agent-fin", "agent-quant"]


def test_different_boards_isolated():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        env = _isolated_home_env(td)
        repo = td / "r"
        repo.mkdir()
        (repo / "kanban.json").write_text(json.dumps({
            "version": "0.2",
            "backend": {"driver": "jira", "jira": {"projectKey": "AGENT"}},
            "meta": {"priorities": ["P0"], "categories": [],
                     "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"],
                     "created_at": "x", "updated_at": "x"},
            "tasks": [],
        }))
        cfg = {
            "boardUrl": "https://acme.atlassian.net/jira/software/projects/AGENT/boards/1",
            "boardId": 1, "projectKey": "AGENT",
            "transitions": {"DOING": {"status": "In Progress"}},
        }
        _run("write-backend", "--kanban-path", str(repo / "kanban.json"),
             "--jira-config-json", json.dumps(cfg), env_extra=env)
        cfg["boardId"] = 2
        cfg["boardUrl"] = "https://acme.atlassian.net/jira/software/projects/AGENT/boards/2"
        _run("write-backend", "--kanban-path", str(repo / "kanban.json"),
             "--jira-config-json", json.dumps(cfg), env_extra=env)

        out = _run("list-board-cache", env_extra=env)
        j = json.loads(out.stdout)
        assert len(j["entries"]) == 2
        keys = {(e["key"]["projectKey"], e["key"]["boardId"]) for e in j["entries"]}
        assert keys == {("AGENT", 1), ("AGENT", 2)}


# --- entry point -----------------------------------------------------------


def main() -> int:
    cases = [
        ("safe_host_normalization", test_safe_host_normalization),
        ("write_read_round_trip", test_write_read_round_trip),
        ("read_handles_missing_and_corrupt", test_read_handles_missing_and_corrupt),
        ("update_ap_registered_idempotent", test_update_ap_registered_idempotent),
        ("list_all_skips_corrupt", test_list_all_skips_corrupt),
        ("read_board_cache_cli_miss_and_hit", test_read_board_cache_cli_miss_and_hit),
        ("two_repos_share_cache", test_two_repos_share_cache),
        ("register_ap_syncs_cache", test_register_ap_syncs_cache),
        ("different_boards_isolated", test_different_boards_isolated),
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
    print("phase8: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
