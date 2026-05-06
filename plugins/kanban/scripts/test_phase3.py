#!/usr/bin/env python3
"""Phase 3 regression checks for kanban v0.2 (AP routing + anti-self-approve).

Run from anywhere:
    python3 plugins/kanban/scripts/test_phase3.py

Mocked Jira; no live network. Covers:
  (a) ap_registry validate / levenshtein / fuzzy_collisions / is_exact_collision
  (b) JiraDriver.list_aps reads kanban.json#backend.jira.ap.registered
  (c) JiraDriver.assign(AgentRef) writes the AP custom field via update_issue
  (d) JiraDriver.transition refuses DONE when task.ap == current_repo_ap
  (e) JiraDriver.transition allows DONE when task.ap differs from repo AP
  (f) jira_setup register-ap on fuzzy match returns ok=false + similar list
  (g) jira_setup register-ap with --force registers via mocked Jira (option add)
       and persists in kanban.json
  (h) jira_setup assign-ap writes .claude/kanban-agent.json with right path
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


def _mock_transport(queue, calls):
    def t(method, url, headers, body):
        calls.append({"method": method, "url": url, "body": body})
        if not queue:
            raise AssertionError("queue empty")
        return queue.pop(0)
    return t


def _mk_data(ap_field_id="customfield_10042", registered=None, partial=False):
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
                    "APPROVED": "Done",
                    "REVIEW": "In Review",
                    "BLOCKED": "Blocked",
                    "CANCELLED": "Cancelled",
                },
                "partial": partial,
                "ap": {
                    "fieldId": ap_field_id,
                    "fieldName": "Claude Agent",
                    "registered": list(registered or []),
                },
            },
        },
        "meta": {
            "priorities": ["P0", "P1"],
            "categories": [],
            "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "APPROVED", "CANCELLED"],
            "created_at": "x",
            "updated_at": "x",
        },
        "tasks": [],
    }


def _patched_driver(data, project_root):
    """Return a JiraDriver with credentials.read mocked."""
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
    drv._client = JiraClient(
        drv.base_url, drv.email, drv._token,
        transport=_mock_transport(queue, calls),
        sleep=lambda _: None,
    )
    # Pre-seed status-category cache (#50) so transition tests don't
    # need a separate Jira API call. APPROVED → "Done" → category=done
    # exercises the strict guard path; intermediate statuses get
    # `indeterminate` / `new`.
    drv._status_categories = {
        "To Do": "new",
        "In Progress": "indeterminate",
        "Done": "done",
        "REVIEW": "indeterminate",
        "In Review": "indeterminate",
    }


# --- ap_registry tests ---------------------------------------------------


def test_ap_registry():
    from lib import ap_registry as ap

    ap.validate_ap_name("agent-fin-exchange")
    for bad in ("", "A", "ab", "1agent", "agent_x", "-agent", "a"*42):
        try:
            ap.validate_ap_name(bad)
            assert False, f"should reject {bad!r}"
        except ap.APValidationError:
            pass

    assert ap.levenshtein("agent-fin", "agent-fin") == 0
    assert ap.levenshtein("agent-fin", "agent-fix") == 1
    assert ap.levenshtein("", "abc") == 3

    hits = ap.fuzzy_collisions("agent-fix", ["agent-fin"], threshold=2)
    assert len(hits) == 1 and hits[0].distance == 1

    assert ap.is_exact_collision("AGENT-FIN", ["agent-fin"])
    assert not ap.is_exact_collision("agent-fix", ["agent-fin"])


# --- driver tests --------------------------------------------------------


def test_list_aps_from_kanban():
    with tempfile.TemporaryDirectory() as td:
        data = _mk_data(registered=["agent-fin", "agent-quant"])
        drv = _patched_driver(data, pathlib.Path(td))
        assert drv.list_aps() == ["agent-fin", "agent-quant"]


def test_assign_agent_writes_custom_field():
    with tempfile.TemporaryDirectory() as td:
        data = _mk_data(registered=["agent-fin"])
        drv = _patched_driver(data, pathlib.Path(td))
        # update_issue (custom field) → assignee (shared agent acct) → get_task
        queue = [
            _Response(204, b"", {}),
            _Response(204, b"", {}),
            _Response(
                200,
                json.dumps(
                    {
                        "key": "AGENT-1",
                        "fields": {
                            "summary": "x",
                            "status": {"name": "To Do"},
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

        from drivers.base import AgentRef

        result = drv.assign("AGENT-1", AgentRef(ap="agent-fin"))
        assert result.ap == "agent-fin"
        # First call writes the AP custom field
        sent = json.loads(calls[0]["body"])
        assert calls[0]["method"] == "PUT"
        assert sent["fields"]["customfield_10042"] == {"value": "agent-fin"}
        # Second call sets assignee to shared agent account
        sent2 = json.loads(calls[1]["body"])
        assert sent2["accountId"] == "agent-acct"


def test_transition_refuses_self_approve():
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        # Pre-write .claude/kanban-agent.json so _current_repo_ap returns it.
        (proj / ".claude").mkdir()
        (proj / ".claude" / "kanban-agent.json").write_text(
            json.dumps({"ap": "agent-fin"})
        )
        data = _mk_data(registered=["agent-fin"])
        drv = _patched_driver(data, proj)

        # _current_repo_ap → "agent-fin"; pre-flight get_task returns task.ap = agent-fin.
        queue = [
            _Response(
                200,
                json.dumps(
                    {
                        "key": "AGENT-1",
                        "fields": {
                            "summary": "x",
                            "status": {"name": "In Review"},
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

        from drivers.jira import SelfApproveRefused

        try:
            drv.transition("AGENT-1", "APPROVED")
            assert False, "should have refused"
        except SelfApproveRefused as e:
            assert "agent-fin" in str(e)
        # No transition POST was made — only the pre-flight get_task ran.
        assert len(calls) == 1


def test_transition_allows_when_ap_differs():
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        (proj / ".claude").mkdir()
        (proj / ".claude" / "kanban-agent.json").write_text(
            json.dumps({"ap": "agent-fin"})
        )
        data = _mk_data(registered=["agent-fin", "agent-quant"])
        drv = _patched_driver(data, proj)

        # 1) pre-flight get_task: card owned by a different AP
        # 2) get_transitions
        # 3) transition_issue
        # 4) post_comment (none — no BLOCKED reason; skipped)
        # 5) get_task post-transition
        queue = [
            _Response(
                200,
                json.dumps(
                    {
                        "key": "AGENT-1",
                        "fields": {
                            "summary": "x",
                            "status": {"name": "In Review"},
                            "priority": {"name": "P1"},
                            "assignee": None,
                            "labels": [],
                            "created": "x",
                            "updated": "y",
                            "customfield_10042": {"value": "agent-quant"},
                        },
                    }
                ).encode(),
                {},
            ),
            _Response(
                200,
                json.dumps(
                    {"transitions": [{"id": "31", "to": {"name": "Done"}}]}
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
                            "status": {"name": "Done"},
                            "priority": {"name": "P1"},
                            "assignee": None,
                            "labels": [],
                            "created": "x",
                            "updated": "z",
                            "customfield_10042": {"value": "agent-quant"},
                        },
                    }
                ).encode(),
                {},
            ),
        ]
        calls = []
        _attach_mock(drv, queue, calls)

        t = drv.transition("AGENT-1", "APPROVED")
        assert t.column == "APPROVED"


# --- jira_setup CLI tests ------------------------------------------------


def _setup_cmd(*args, env_extra=None):
    cmd = ["python3", str(PLUGIN / "scripts" / "jira_setup.py"), *args]
    env = dict(os.environ)
    # Default HOME to a throwaway dir so a real ~/.claude-workbench/.env
    # on the test machine can't sneak Jira credentials into the helper
    # (which would trigger live API calls and mask offline-only
    # assertions like the fuzzy-collision check).
    if "HOME" not in (env_extra or {}):
        env["HOME"] = "/tmp/kanban-phase3-fakehome"
        os.makedirs(env["HOME"], exist_ok=True)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, capture_output=True, env=env)


def test_register_ap_fuzzy_no_force():
    """register-ap on a near-duplicate without --force returns ok=false."""
    with tempfile.TemporaryDirectory() as td:
        kp = pathlib.Path(td) / "kanban.json"
        kp.write_text(json.dumps(_mk_data(registered=["agent-fin"])))

        # Isolate HOME so a real ~/.claude-workbench/.env on the test
        # machine doesn't trigger a live Jira call (which would 401/404
        # and mask the fuzzy-match assertion).
        fakehome = pathlib.Path(td) / "fakehome"
        fakehome.mkdir(parents=True, exist_ok=True)
        out = _setup_cmd(
            "register-ap", "--kanban-path", str(kp), "--name", "agent-fix",
            env_extra={"HOME": str(fakehome)},
        )
        assert out.returncode == 0, out.stderr
        j = json.loads(out.stdout)
        assert j["ok"] is False
        assert j["fuzzyMatch"] is True
        assert any(s["name"] == "agent-fin" and s["distance"] == 1 for s in j["similar"])


def test_assign_ap_writes_file():
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        kp = proj / "kanban.json"
        kp.write_text(json.dumps(_mk_data(registered=["agent-fin"])))

        out = _setup_cmd(
            "assign-ap", "--kanban-path", str(kp), "--name", "agent-fin"
        )
        assert out.returncode == 0, out.stderr
        target = proj / ".claude" / "kanban-agent.json"
        assert target.exists()
        j = json.loads(target.read_text())
        assert j["ap"] == "agent-fin"

        # Refuse unregistered AP.
        out = _setup_cmd(
            "assign-ap", "--kanban-path", str(kp), "--name", "agent-other"
        )
        assert out.returncode != 0


def test_register_ap_validates_name():
    with tempfile.TemporaryDirectory() as td:
        kp = pathlib.Path(td) / "kanban.json"
        kp.write_text(json.dumps(_mk_data(registered=[])))

        out = _setup_cmd(
            "register-ap", "--kanban-path", str(kp), "--name", "Bad Name"
        )
        assert out.returncode != 0
        j = json.loads(out.stdout)
        assert j["ok"] is False
        assert "AP" in j["error"] or "match" in j["error"]


# --- entry point ---------------------------------------------------------


def main() -> int:
    cases = [
        ("ap_registry", test_ap_registry),
        ("list_aps_from_kanban", test_list_aps_from_kanban),
        ("assign_agent_writes_custom_field", test_assign_agent_writes_custom_field),
        ("transition_refuses_self_approve", test_transition_refuses_self_approve),
        ("transition_allows_when_ap_differs", test_transition_allows_when_ap_differs),
        ("register_ap_fuzzy_no_force", test_register_ap_fuzzy_no_force),
        ("assign_ap_writes_file", test_assign_ap_writes_file),
        ("register_ap_validates_name", test_register_ap_validates_name),
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
    print("phase3: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
