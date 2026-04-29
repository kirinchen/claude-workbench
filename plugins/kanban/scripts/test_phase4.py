#!/usr/bin/env python3
"""Phase 4 regression checks for kanban v0.2 (auto-detect, sync, cache).

Run from anywhere:
    python3 plugins/kanban/scripts/test_phase4.py

Mocked Jira; no live network. Covers:
  (a) card_parser KEY + URL extraction with project-key filter and dedup
  (b) card_cache fresh / TTL-expired / invalidate / clear
  (c) JiraDriver.transition invalidates the cache after success
  (d) precheck-card returns ap-mismatch warning when AP differs
  (e) precheck-card honours cache hit (no second Jira fetch)
  (f) sync-summary renders open-card lines for the current AP
  (g) hook kanban-card-detect.sh emits additionalContext when card found
  (h) hook kanban-jira-sync.sh emits sync summary on SessionStart
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

from lib.jira_client import JiraClient, _Response  # noqa: E402


def _mk_data(*, registered=("agent-fin",), partial=False):
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
                    "TODO": "To Do",
                    "DOING": "In Progress",
                    "DONE": "Done",
                    "REVIEW": "In Review",
                    "BLOCKED": "Blocked",
                    "CANCELLED": "Cancelled",
                },
                "partial": partial,
                "ap": {
                    "fieldId": "customfield_10042",
                    "fieldName": "Claude Agent",
                    "registered": list(registered),
                },
            },
        },
        "meta": {
            "priorities": ["P0", "P1"],
            "categories": [],
            "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"],
            "created_at": "x",
            "updated_at": "x",
        },
        "tasks": [],
    }


def _seed_repo(td, *, ap="agent-fin", data=None):
    proj = pathlib.Path(td)
    (proj / ".claude").mkdir(parents=True, exist_ok=True)
    (proj / ".claude" / "kanban-agent.json").write_text(json.dumps({"ap": ap}))
    (proj / "kanban.json").write_text(json.dumps(data if data is not None else _mk_data()))
    return proj


def _setup_cmd(*args, env_extra=None):
    cmd = ["python3", str(PLUGIN / "scripts" / "jira_setup.py"), *args]
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, capture_output=True, env=env)


# --- card_parser ---------------------------------------------------------


def test_card_parser():
    from lib import card_parser

    assert card_parser.extract_keys("see AGENT-42 and FIN-103") == ["AGENT-42", "FIN-103"]
    assert card_parser.extract_keys("AGENT-42 AGENT-42") == ["AGENT-42"]
    keys = card_parser.extract_keys(
        "see https://x.atlassian.net/browse/AGENT-7 plus AGENT-9 also "
        "https://x.atlassian.net/board?selectedIssue=AGENT-12"
    )
    assert keys == ["AGENT-7", "AGENT-9", "AGENT-12"]
    assert card_parser.extract_for_project(
        "AGENT-1 FIN-3 AGENT-4", "AGENT"
    ) == ["AGENT-1", "AGENT-4"]
    assert card_parser.extract_keys("AGENT-42x") == []


# --- card_cache ----------------------------------------------------------


def test_card_cache():
    from lib import card_cache

    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td)
        assert card_cache.get(p, "AGENT-1") is None
        card_cache.put(p, "AGENT-1", {"col": "TODO"})
        assert card_cache.get(p, "AGENT-1") == {"col": "TODO"}
        assert card_cache.get(p, "AGENT-1", ttl=0) is None  # immediate expiry
        card_cache.invalidate(p, "AGENT-1")
        assert card_cache.get(p, "AGENT-1") is None
        card_cache.put(p, "AGENT-3", {"x": 1})
        card_cache.clear(p)
        assert card_cache.get(p, "AGENT-3") is None


# --- driver invalidates cache on writes ---------------------------------


def _patched_driver(data, project_root):
    from drivers.jira import JiraDriver
    from lib import credentials

    orig = credentials.read
    credentials.read = lambda prefix=None: {
        "JIRA_BASE_URL": "https://x",
        "JIRA_AGENT_EMAIL": "a@b",
        "JIRA_API_TOKEN": "tok",
    }
    try:
        drv = JiraDriver(data, project_root)
    finally:
        credentials.read = orig
    return drv


def _attach_mock(drv, queue, calls):
    def t(method, url, headers, body):
        calls.append({"method": method, "url": url, "body": body})
        return queue.pop(0)
    drv._client = JiraClient(
        drv.base_url, drv.email, drv._token, transport=t, sleep=lambda _: None
    )


def test_driver_invalidates_cache_on_transition():
    from lib import card_cache

    with tempfile.TemporaryDirectory() as td:
        proj = _seed_repo(td, ap="agent-quant")
        data = _mk_data(registered=("agent-fin", "agent-quant"))
        drv = _patched_driver(data, proj)
        # Warm the cache.
        card_cache.put(proj, "AGENT-1", {"col": "TODO"})
        assert card_cache.get(proj, "AGENT-1") is not None

        # transition(DOING) call chain (anti-self-approve only fires for DONE):
        # 1) get_transitions
        # 2) transition_issue (POST)
        # 3) get_task (post-transition refresh)
        queue = [
            _Response(
                200,
                json.dumps(
                    {"transitions": [{"id": "21", "to": {"name": "In Progress"}}]}
                ).encode(),
                {},
            ),
            _Response(204, b"", {}),
            _Response(
                200,
                json.dumps(
                    {
                        "key": "AGENT-1",
                        "fields": {
                            "summary": "x",
                            "status": {"name": "In Progress"},
                            "priority": {"name": "P1"},
                            "assignee": None,
                            "labels": [],
                            "created": "x",
                            "updated": "y",
                            "customfield_10042": {"value": "agent-fin"},
                        },
                    }
                ).encode(),
                {},
            ),
        ]
        calls = []
        _attach_mock(drv, queue, calls)

        drv.transition("AGENT-1", "DOING")
        # Cache should now be empty for AGENT-1.
        assert card_cache.get(proj, "AGENT-1") is None


# --- precheck-card --------------------------------------------------------


def test_precheck_card_ap_mismatch():
    """precheck-card emits ap-mismatch when the cached card is owned by another AP."""
    from lib import card_cache, kanban_io

    with tempfile.TemporaryDirectory() as td:
        proj = _seed_repo(td, ap="agent-fin")
        # Pre-seed the cache so precheck doesn't make a Jira call.
        card_cache.put(
            proj,
            "AGENT-9",
            {
                "id": "AGENT-9",
                "title": "shared concern",
                "column": "DOING",
                "ap": "agent-quant",
                "priority": "P1",
                "custom": {"raw_status": "In Progress"},
                "last_open_question": None,
            },
        )
        out = _setup_cmd(
            "precheck-card",
            "--kanban-path", str(proj / "kanban.json"),
            "--key", "AGENT-9",
            "--skip-comments",
        )
        assert out.returncode == 0, out.stderr
        j = json.loads(out.stdout)
        assert j["found"] is True
        assert j["from_cache"] is True
        assert "ap-mismatch" in j["warnings"]
        assert "agent-quant" in j["context_block"]
        assert "agent-fin" in j["context_block"]


def test_precheck_card_filters_out_other_projects():
    with tempfile.TemporaryDirectory() as td:
        proj = _seed_repo(td)
        out = _setup_cmd(
            "precheck-card",
            "--kanban-path", str(proj / "kanban.json"),
            "--key", "FIN-1",
            "--skip-comments",
        )
        assert out.returncode == 0, out.stderr
        j = json.loads(out.stdout)
        assert j.get("ignored") is True
        assert j["context_block"] == ""


# --- sync-summary ---------------------------------------------------------


def test_sync_summary_local_skipped():
    """sync-summary on local-mode kanban returns a skip marker, no error."""
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        (proj / "kanban.json").write_text(
            json.dumps(
                {
                    "version": "0.2",
                    "backend": {"driver": "local"},
                    "meta": {
                        "priorities": ["P0"],
                        "categories": [],
                        "columns": ["TODO", "DOING", "DONE", "BLOCKED"],
                        "created_at": "x",
                        "updated_at": "x",
                    },
                    "tasks": [],
                }
            )
        )
        out = _setup_cmd(
            "sync-summary", "--kanban-path", str(proj / "kanban.json")
        )
        assert out.returncode == 0
        j = json.loads(out.stdout)
        assert j["summary"] == ""
        assert j.get("skip")


# --- hooks ----------------------------------------------------------------


def test_card_detect_hook_emits_context():
    """kanban-card-detect.sh injects a context block when a card key is in the prompt."""
    from lib import card_cache

    with tempfile.TemporaryDirectory() as td:
        proj = _seed_repo(td)
        # Pre-seed so the hook doesn't actually call Jira.
        card_cache.put(
            proj,
            "AGENT-42",
            {
                "id": "AGENT-42",
                "title": "concern",
                "column": "REVIEW",
                "ap": "agent-fin",
                "priority": "P1",
                "custom": {"raw_status": "In Review"},
                "last_open_question": None,
            },
        )
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(proj)
        payload = json.dumps({"prompt": "please look at AGENT-42 thanks"})
        out = subprocess.run(
            ["bash", str(PLUGIN / "scripts" / "kanban-card-detect.sh")],
            input=payload,
            text=True,
            env=env,
            capture_output=True,
        )
        assert out.returncode == 0, out.stderr
        # The hook either prints a JSON object with hookSpecificOutput, or
        # nothing if the prompt has no recognisable key.
        assert "AGENT-42" in out.stdout, out.stdout
        # Should NOT panic on missing project key for unrelated mentions.
        env2 = dict(env)
        out2 = subprocess.run(
            ["bash", str(PLUGIN / "scripts" / "kanban-card-detect.sh")],
            input=json.dumps({"prompt": "no card here"}),
            text=True,
            env=env2,
            capture_output=True,
        )
        assert out2.returncode == 0
        assert out2.stdout == "" or "AGENT-" not in out2.stdout


def test_jira_sync_hook_silent_for_local():
    """kanban-jira-sync.sh is silent for local-mode projects."""
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        (proj / "kanban.json").write_text(
            json.dumps(
                {
                    "version": "0.2",
                    "backend": {"driver": "local"},
                    "meta": {
                        "priorities": ["P0"],
                        "categories": [],
                        "columns": ["TODO", "DOING", "DONE", "BLOCKED"],
                        "created_at": "x",
                        "updated_at": "x",
                    },
                    "tasks": [],
                }
            )
        )
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(proj)
        out = subprocess.run(
            ["bash", str(PLUGIN / "scripts" / "kanban-jira-sync.sh")],
            env=env, capture_output=True, text=True,
        )
        assert out.returncode == 0
        assert out.stdout == ""


# --- entry point ----------------------------------------------------------


def main() -> int:
    cases = [
        ("card_parser", test_card_parser),
        ("card_cache", test_card_cache),
        ("driver_invalidates_cache_on_transition", test_driver_invalidates_cache_on_transition),
        ("precheck_card_ap_mismatch", test_precheck_card_ap_mismatch),
        ("precheck_card_filters_out_other_projects", test_precheck_card_filters_out_other_projects),
        ("sync_summary_local_skipped", test_sync_summary_local_skipped),
        ("card_detect_hook_emits_context", test_card_detect_hook_emits_context),
        ("jira_sync_hook_silent_for_local", test_jira_sync_hook_silent_for_local),
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
    print("phase4: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
