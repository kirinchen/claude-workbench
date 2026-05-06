#!/usr/bin/env python3
"""Phase 17 regression checks for kanban v0.3.10 — assignee-aware
anti-self-approve (#19).

The original anti-self-approve rule (refuse DONE if `card.ap == repo_ap`)
was too strict in the common case where the agent records work
completed by a human teammate (assignee = the human). v0.3.10 loosens
the rule: refuse only when the card's assignee is the agent itself
(or null). This phase covers the four canonical cases:

  | card.ap     | assignee                          | DONE allowed?  |
  |-------------|-----------------------------------|----------------|
  | mine        | agent's own account               | NO (refuse)    |
  | mine        | None (unassigned)                 | NO (refuse)    |
  | mine        | a different account (e.g. human)  | YES (allow)    |
  | other / nil | anything                          | YES (allow)    |
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"
sys.path.insert(0, str(REPO / "plugins" / "kanban"))

from lib.jira_client import JiraClient, _Response  # noqa: E402


def _seed():
    return {
        "version": "0.2",
        "backend": {"driver": "jira", "jira": {
            "boardUrl": "https://x/jira/projects/AGENT/boards/1",
            "boardId": 1, "projectKey": "AGENT",
            "agentAccountId": "5e-agent",
            "transitions": {
                "TODO": {"status": "To Do"},
                "DOING": {"status": "In Progress"},
                "APPROVED": {"status": "Done"},
            },
            "ap": {"fieldId": "customfield_10042",
                   "fieldName": "Claude Agent",
                   "registered": ["agent-fin"]},
        }},
        "meta": {"priorities": ["P0"], "categories": [],
                 "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "APPROVED", "CANCELLED"],
                 "created_at": "x", "updated_at": "x"},
        "tasks": [],
    }


def _patched_driver(data, project_root):
    from drivers.jira import JiraDriver
    from lib import credentials

    orig = credentials.read
    credentials.read = lambda prefix=None: {
        "JIRA_BASE_URL": "https://x", "JIRA_AGENT_EMAIL": "a@b",
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
        drv.base_url, drv.email, drv._token,
        transport=t, sleep=lambda _: None,
    )
    # Pre-seed the status-category cache so anti-self-approve doesn't
    # need a separate Jira API hit during these tests (#50). Phase 17's
    # DSL maps APPROVED → "Done" (statusCategory=done), so the guard
    # paths exercised here remain the strict-block path.
    drv._status_categories = {
        "To Do": "new",
        "In Progress": "indeterminate",
        "Done": "done",
        "REVIEW": "indeterminate",
    }


def _seed_repo_ap(repo: pathlib.Path, ap: str = "agent-fin"):
    (repo / ".claude").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "kanban-agent.json").write_text(
        json.dumps({"ap": ap}) + "\n"
    )


def _issue(key, *, status="In Progress", assignee_acct=None,
           ap_value="agent-fin", labels=()):
    f = {
        "summary": "x",
        "status": {"name": status},
        "priority": {"name": "P1"},
        "assignee": {"accountId": assignee_acct} if assignee_acct else None,
        "labels": list(labels),
        "created": "x", "updated": "y",
        "issuelinks": [],
    }
    if ap_value is not None:
        f["customfield_10042"] = {"value": ap_value}
    return {"key": key, "fields": f}


# --- the four canonical cases -------------------------------------------


def test_refuse_when_assignee_is_agent_account():
    """AP=mine + assignee=agent → still refuse (classic self-approve)."""
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)
        drv = _patched_driver(_seed(), proj)
        pre = _issue("AGENT-1", assignee_acct="5e-agent",
                     ap_value="agent-fin")
        queue = [_Response(200, json.dumps(pre).encode(), {})]
        calls = []
        _attach_mock(drv, queue, calls)

        from drivers.jira import SelfApproveRefused
        try:
            drv.transition("AGENT-1", "APPROVED")
            assert False, "should have refused"
        except SelfApproveRefused as e:
            assert "agent-fin" in str(e)
        # Only the pre-flight read happened — no transition POST attempt
        assert len(calls) == 1


def test_refuse_when_assignee_is_none():
    """AP=mine + assignee=None → still refuse. Without proof of human
    ownership we err on the strict side."""
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)
        drv = _patched_driver(_seed(), proj)
        pre = _issue("AGENT-2", assignee_acct=None, ap_value="agent-fin")
        queue = [_Response(200, json.dumps(pre).encode(), {})]
        calls = []
        _attach_mock(drv, queue, calls)

        from drivers.jira import SelfApproveRefused
        try:
            drv.transition("AGENT-2", "APPROVED")
            assert False, "should have refused"
        except SelfApproveRefused:
            pass
        assert len(calls) == 1


def test_allow_when_assignee_is_different_human():
    """AP=mine + assignee=different account → allow (recording on
    behalf of the human who actually did the work — issue #19)."""
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)
        drv = _patched_driver(_seed(), proj)
        # Card belongs to my AP but is assigned to Kirin (a different
        # account from the bot).
        pre = _issue("AGENT-3", assignee_acct="5e-kirin",
                     ap_value="agent-fin", status="In Progress")
        post = _issue("AGENT-3", assignee_acct="5e-kirin",
                      ap_value="agent-fin", status="Done")
        # Full transition flow: get_task → get_transitions → POST → final get_task
        queue = [
            _Response(200, json.dumps(pre).encode(), {}),
            _Response(200, json.dumps(
                {"transitions": [{"id": "31", "to": {"name": "Done"}}]}
            ).encode(), {}),
            _Response(204, b"", {}),
            _Response(200, json.dumps(post).encode(), {}),
        ]
        calls = []
        _attach_mock(drv, queue, calls)

        result = drv.transition("AGENT-3", "APPROVED")
        assert result.column == "APPROVED"
        # We hit the transition POST — proves the new code allowed it.
        posts = [c for c in calls if c["method"] == "POST"
                 and c["url"].endswith("/transitions")]
        assert len(posts) == 1


def test_allow_when_ap_does_not_match():
    """AP=other (a different agent's card) — never triggered the refuse
    path under the old rule either; verify still allowed."""
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)  # repo AP = "agent-fin"
        drv = _patched_driver(_seed(), proj)
        # Card's AP is a different agent
        pre = _issue("AGENT-4", assignee_acct="5e-agent",
                     ap_value="agent-quant", status="In Progress")
        post = _issue("AGENT-4", assignee_acct="5e-agent",
                      ap_value="agent-quant", status="Done")
        queue = [
            _Response(200, json.dumps(pre).encode(), {}),
            _Response(200, json.dumps(
                {"transitions": [{"id": "31", "to": {"name": "Done"}}]}
            ).encode(), {}),
            _Response(204, b"", {}),
            _Response(200, json.dumps(post).encode(), {}),
        ]
        calls = []
        _attach_mock(drv, queue, calls)

        result = drv.transition("AGENT-4", "APPROVED")
        assert result.column == "APPROVED"


# --- error message preserved --------------------------------------------


def test_refused_error_message_mentions_workaround():
    """The new refusal message hints at the workaround (assign to human
    first if recording on their behalf)."""
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)
        drv = _patched_driver(_seed(), proj)
        pre = _issue("AGENT-5", assignee_acct="5e-agent",
                     ap_value="agent-fin")
        queue = [_Response(200, json.dumps(pre).encode(), {})]
        calls = []
        _attach_mock(drv, queue, calls)

        from drivers.jira import SelfApproveRefused
        try:
            drv.transition("AGENT-5", "APPROVED")
            assert False, "should have refused"
        except SelfApproveRefused as e:
            msg = str(e)
            assert "anti-self-approve" in msg
            assert "agent-fin" in msg
            # New hint about the recording-on-behalf workaround
            assert "assign" in msg.lower() and "human" in msg.lower()


def main() -> int:
    cases = [
        ("refuse_when_assignee_is_agent_account",
         test_refuse_when_assignee_is_agent_account),
        ("refuse_when_assignee_is_none",
         test_refuse_when_assignee_is_none),
        ("allow_when_assignee_is_different_human",
         test_allow_when_assignee_is_different_human),
        ("allow_when_ap_does_not_match",
         test_allow_when_ap_does_not_match),
        ("refused_error_message_mentions_workaround",
         test_refused_error_message_mentions_workaround),
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
    print("phase17: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
