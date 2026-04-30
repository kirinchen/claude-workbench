#!/usr/bin/env python3
"""Phase 8 regression checks for kanban v0.3.x — code-based sharing + live AP query.

A board's compound-transition mapping travels between machines as a
shareable JSON code (no per-machine credentials, no stale AP roster).
Cases:

  (a) emit-jira-code returns the schema-tagged code; defaults strip
      `agentAccountId` and `ap.registered`
  (b) emit-jira-code with --include-agent-account preserves the field
  (c) import-jira-code rejects non-matching schema; rejects bad transitions
  (d) emit + import roundtrip: repo B's kanban.json mirrors repo A's
      transitions exactly, with a fresh empty `ap.registered`
  (e) live-list-aps falls back to local hint when credentials are missing
  (f) cmd_assign_ap fallback path still works when Jira is unreachable
       (validates against local hint with fallbackUsed: true)
  (g) cmd_register_ap collision check uses live options when available;
       falls back gracefully without credentials
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


def _seed_jira(td, *, registered=("agent-fin", "agent-quant"),
               include_agent=True) -> pathlib.Path:
    p = pathlib.Path(td) / "kanban.json"
    cfg = {
        "boardUrl": "https://acme.atlassian.net/jira/software/projects/AGENT/boards/1",
        "boardId": 1,
        "projectKey": "AGENT",
        "transitions": {
            "TODO": {"status": "Selected for Development"},
            "DOING": {"status": "In Progress"},
            "BLOCKED": {"status": "In Progress", "addLabels": ["kanban:blocked"]},
            "DONE": {"status": "Done"},
        },
        "ap": {
            "fieldId": "customfield_10042",
            "fieldName": "Claude Agent",
            "registered": list(registered),
        },
    }
    if include_agent:
        cfg["agentAccountId"] = "shared-agent-acct"
    p.write_text(json.dumps({
        "version": "0.2",
        "backend": {"driver": "jira", "jira": cfg},
        "meta": {
            "priorities": ["P0"], "categories": [],
            "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"],
            "created_at": "x", "updated_at": "x",
        },
        "tasks": [],
    }))
    return p


def _isolated_home(td: pathlib.Path) -> dict[str, str]:
    """HOME override so the subprocess sees an empty ~/.claude-workbench/.env."""
    home = td / "fakehome"
    home.mkdir(parents=True, exist_ok=True)
    return {"HOME": str(home)}


def _run(*args, env_extra=None) -> subprocess.CompletedProcess:
    cmd = ["python3", str(PLUGIN / "scripts" / "jira_setup.py"), *args]
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, capture_output=True, env=env, text=True)


# --- emit-jira-code ------------------------------------------------------


def test_emit_strips_agent_and_registered():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td, registered=["agent-fin"], include_agent=True)
        out = _run("emit-jira-code", "--kanban-path", str(kp),
                   env_extra=_isolated_home(td))
        assert out.returncode == 0, out.stderr
        j = json.loads(out.stdout)
        assert j["ok"] is True
        code = j["code"]
        # 0.3.4+ writers emit /2 by default; reader still accepts /1 (forward-compat).
        assert code["schema"] == "kanban-jira-code/2"
        assert code["projectKey"] == "AGENT"
        assert code["boardId"] == 1
        # Defaults strip these:
        assert "agentAccountId" not in code
        assert "registered" not in code["ap"]
        # Always-included:
        assert code["transitions"]["BLOCKED"]["addLabels"] == ["kanban:blocked"]
        assert code["ap"]["fieldId"] == "customfield_10042"


def test_emit_preserves_agent_with_flag():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td, include_agent=True)
        out = _run("emit-jira-code", "--kanban-path", str(kp),
                   "--include-agent-account",
                   env_extra=_isolated_home(td))
        assert out.returncode == 0, out.stderr
        j = json.loads(out.stdout)
        assert j["code"]["agentAccountId"] == "shared-agent-acct"


def test_emit_refuses_local_driver():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = pathlib.Path(td) / "kanban.json"
        kp.write_text(json.dumps({
            "version": "0.2",
            "backend": {"driver": "local"},
            "meta": {"priorities": ["P0"], "categories": [],
                     "columns": ["TODO", "DOING", "DONE", "BLOCKED"],
                     "created_at": "x", "updated_at": "x"},
            "tasks": [],
        }))
        out = _run("emit-jira-code", "--kanban-path", str(kp),
                   env_extra=_isolated_home(td))
        assert out.returncode != 0
        j = json.loads(out.stdout)
        assert j["ok"] is False


# --- import-jira-code ----------------------------------------------------


def test_import_rejects_bad_schema():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = pathlib.Path(td) / "kanban.json"
        kp.write_text(json.dumps({
            "version": "0.2",
            "backend": {"driver": "jira", "jira": {"projectKey": "X"}},
            "meta": {"priorities": ["P0"], "categories": [],
                     "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"],
                     "created_at": "x", "updated_at": "x"},
            "tasks": [],
        }))
        bad_codes = [
            json.dumps({"schema": "kanban-jira-code/0"}),
            json.dumps({"schema": "kanban-jira-code/1"}),  # missing transitions
            json.dumps({"schema": "kanban-jira-code/1",
                        "transitions": {"FOO": {"status": "X"}},  # bad canonical
                        "projectKey": "X", "boardId": 1}),
            "not-json-at-all",
        ]
        for bad in bad_codes:
            out = _run("import-jira-code",
                       "--kanban-path", str(kp),
                       "--code-json", bad,
                       env_extra=_isolated_home(td))
            assert out.returncode != 0, f"should reject: {bad[:80]}"
            j = json.loads(out.stdout)
            assert j["ok"] is False


def test_emit_import_roundtrip_two_repos():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        # Repo A — fully configured
        repo_a = td / "repo-a"
        repo_a.mkdir()
        kp_a = _seed_jira(repo_a, registered=["agent-fin", "agent-quant"])

        # Repo B — fresh kanban.json with jira backend but no transitions yet
        repo_b = td / "repo-b"
        repo_b.mkdir()
        kp_b = repo_b / "kanban.json"
        kp_b.write_text(json.dumps({
            "version": "0.2",
            "backend": {"driver": "jira", "jira": {"projectKey": "AGENT"}},
            "meta": {"priorities": ["P0"], "categories": [],
                     "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"],
                     "created_at": "x", "updated_at": "x"},
            "tasks": [],
        }))

        env = _isolated_home(td)

        # Emit from A
        out = _run("emit-jira-code", "--kanban-path", str(kp_a), env_extra=env)
        assert out.returncode == 0, out.stderr
        code = json.loads(out.stdout)["code"]

        # Import to B
        out = _run("import-jira-code",
                   "--kanban-path", str(kp_b),
                   "--code-json", json.dumps(code),
                   env_extra=env)
        assert out.returncode == 0, out.stderr

        # Verify repo B's kanban.json mirrors A's transitions (and ap.fieldId)
        # but starts with empty ap.registered (live-queried later).
        cfg_b = json.loads(kp_b.read_text())["backend"]["jira"]
        cfg_a = json.loads(kp_a.read_text())["backend"]["jira"]
        assert cfg_b["transitions"] == cfg_a["transitions"]
        assert cfg_b["projectKey"] == cfg_a["projectKey"]
        assert cfg_b["boardId"] == cfg_a["boardId"]
        assert cfg_b["ap"]["fieldId"] == cfg_a["ap"]["fieldId"]
        assert cfg_b["ap"]["registered"] == []   # cleared by import


# --- live-list-aps + assign-ap fallback ---------------------------------


def test_live_list_aps_no_credentials():
    """Without credentials, live-list-aps fails fast (the helper requires
    creds to talk to Jira). The slash command surfaces the error so the
    user runs /kanban:reset-credentials. We just check it errors cleanly,
    not silently."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td)
        out = _run("live-list-aps", "--kanban-path", str(kp),
                   env_extra=_isolated_home(td))
        assert out.returncode != 0
        j = json.loads(out.stdout)
        assert j["ok"] is False
        assert "credentials missing" in j["error"].lower() or "jira" in j["error"].lower()


def test_assign_ap_falls_back_without_credentials():
    """assign-ap must still work when there are no credentials yet — fall
    back to the local hint list and mark fallbackUsed: true."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td, registered=["agent-fin"])
        out = _run("assign-ap", "--kanban-path", str(kp), "--name", "agent-fin",
                   env_extra=_isolated_home(td))
        assert out.returncode == 0, out.stderr
        j = json.loads(out.stdout)
        assert j["ok"] is True
        assert (kp.parent / ".claude" / "kanban-agent.json").exists()


def test_assign_ap_unregistered_refused():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td, registered=["agent-fin"])
        out = _run("assign-ap", "--kanban-path", str(kp), "--name", "agent-other",
                   env_extra=_isolated_home(td))
        assert out.returncode != 0
        j = json.loads(out.stdout)
        assert j["ok"] is False
        assert j["fallbackUsed"] is True
        assert "agent-fin" in j["registered"]


def test_register_ap_fuzzy_falls_back_without_creds():
    """register-ap surfaces the fuzzy collision against local hint when
    credentials are missing — same UX as before, no live query needed for
    the fuzzy check itself."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td, registered=["agent-fin"])
        out = _run("register-ap", "--kanban-path", str(kp),
                   "--name", "agent-fix",
                   env_extra=_isolated_home(td))
        assert out.returncode == 0, out.stderr
        j = json.loads(out.stdout)
        assert j["ok"] is False
        assert j["fuzzyMatch"] is True


def test_register_ap_no_creds_fails_at_write():
    """register-ap with --force needs Jira to add the option. Without
    credentials, fail explicitly with a clear hint instead of silently
    skipping the Jira write."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td, registered=["agent-fin"])
        out = _run("register-ap", "--kanban-path", str(kp),
                   "--name", "agent-brand-new",
                   "--force",
                   env_extra=_isolated_home(td))
        assert out.returncode != 0, f"expected fail, got {out.stdout!r}"
        j = json.loads(out.stdout)
        assert j["ok"] is False
        assert "credentials missing" in j["error"].lower()


# --- entry point ---------------------------------------------------------


def main() -> int:
    cases = [
        ("emit_strips_agent_and_registered", test_emit_strips_agent_and_registered),
        ("emit_preserves_agent_with_flag", test_emit_preserves_agent_with_flag),
        ("emit_refuses_local_driver", test_emit_refuses_local_driver),
        ("import_rejects_bad_schema", test_import_rejects_bad_schema),
        ("emit_import_roundtrip_two_repos", test_emit_import_roundtrip_two_repos),
        ("live_list_aps_no_credentials", test_live_list_aps_no_credentials),
        ("assign_ap_falls_back_without_credentials", test_assign_ap_falls_back_without_credentials),
        ("assign_ap_unregistered_refused", test_assign_ap_unregistered_refused),
        ("register_ap_fuzzy_falls_back_without_creds", test_register_ap_fuzzy_falls_back_without_creds),
        ("register_ap_no_creds_fails_at_write", test_register_ap_no_creds_fails_at_write),
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
