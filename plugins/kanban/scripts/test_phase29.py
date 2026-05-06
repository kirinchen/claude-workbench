#!/usr/bin/env python3
"""Phase 29 regression checks for kanban v0.3.24 — anti-self-approve
keyed on Jira `statusCategory`, not on the canonical state name.

Closes #50. Pre-fix: anti-self-approve fired for any transition where
`to_column == "APPROVED"` AND the agent owned the card. Teams whose
DSL maps canonical APPROVED to a non-terminal Jira status (e.g.
`status: "REVIEW"` + `addLabels: ["kanban_awaiting_approval"]` for
"agent done, awaiting human review") got blocked on a path that's
semantically NOT a self-approval — the agent is just signalling
completion; the human still has to push REVIEW → Done.

The fix queries Jira's `statusCategory` for the target status (lazy
cache via `get_project_statuses`):
  - `category == "done"`     → fire the strict guard (true approval)
  - `category in {indeterminate, new}` → allow (intermediate stage)
  - `category is None`       → distinct error refusing for safety
                              (lookup failed; user can retry)

Cases:
  (a) APPROVED → status with category=done + agent owns + assignee=
      agent → blocked with the existing SelfApproveRefused message.
      (Existing strict-guard behavior preserved when DSL maps to a
      true terminal Done.)
  (b) APPROVED → status with category=indeterminate + agent owns +
      assignee=agent → allowed (the actual #50 fix). The compound
      transition runs as normal: status change, label add, assignee.
  (c) APPROVED → status with category=new + agent owns → also allowed
      (intermediate stage, just on the other side).
  (d) APPROVED → status whose category lookup returns None → fail
      with a DISTINCT error message (not SelfApproveRefused) so the
      caller can tell "Jira API hiccup" apart from "self-approve".
  (e) APPROVED → done category, but assignee is a different human →
      allowed (recording for someone else; existing #19 #20 behavior
      preserved).
  (f) `_get_status_category` is lazy — only one `get_project_statuses`
      call regardless of how many transitions happen on the same
      driver instance.
  (g) When the driver-level lookup fails the first time, the second
      transition does NOT retry (cache an empty map; per-process
      cost is bounded).
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


# --- helpers ------------------------------------------------------------


def _seed_jira_data(*, approved_status="Done"):
    """Seed kanban.json data with `transitions.APPROVED.status` taken
    from the `approved_status` param — lets each test exercise the
    guard against done / indeterminate / new categories."""
    return {
        "version": "0.2",
        "backend": {"driver": "jira", "jira": {
            "boardUrl": "https://x/jira/projects/AGENT/boards/1",
            "boardId": 1, "projectKey": "AGENT",
            "agentAccountId": "5e-agent",
            "transitions": {
                "TODO": {"status": "To Do"},
                "DOING": {"status": "In Progress"},
                "REVIEW": {"status": "REVIEW"},
                "APPROVED": {
                    "status": approved_status,
                    "addLabels": ["kanban_awaiting_approval"]
                    if approved_status != "Done" else [],
                },
            },
            "ap": {"fieldId": "customfield_10042",
                   "fieldName": "Claude Agent",
                   "registered": ["agent-fin"]},
        }},
        "meta": {"priorities": ["P0"], "categories": [],
                 "columns": ["TODO", "DOING", "BLOCKED", "REVIEW",
                             "APPROVED", "CANCELLED"],
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
        if not queue:
            raise AssertionError(f"queue empty for {method} {url}")
        return queue.pop(0)
    drv._client = JiraClient(
        drv.base_url, drv.email, drv._token,
        transport=t, sleep=lambda _: None,
    )


def _seed_repo_ap(repo: pathlib.Path, ap: str = "agent-fin"):
    (repo / ".claude").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "kanban-agent.json").write_text(
        json.dumps({"ap": ap}) + "\n"
    )


def _issue(key, *, status="In Progress", assignee_acct="5e-agent",
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


def _project_statuses_response(*, mapping):
    """Build a `/rest/api/3/project/{key}/statuses` response — single
    issue type whose `statuses` array enumerates the given
    name → category-key pairs."""
    statuses = [
        {"id": str(i),
         "name": name,
         "statusCategory": {"key": cat, "name": cat.title()}}
        for i, (name, cat) in enumerate(mapping.items(), start=10000)
    ]
    return _Response(200, json.dumps([
        {"id": "10001", "name": "Story", "statuses": statuses},
    ]).encode(), {})


# --- (a) strict guard preserved when category=done ----------------------


def test_block_when_target_category_is_done():
    """APPROVED → "Done" (category=done) + AP=mine + assignee=agent →
    SelfApproveRefused (existing behavior preserved)."""
    data = _seed_jira_data(approved_status="Done")
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)
        drv = _patched_driver(data, proj)
        queue = [
            # statusCategory lookup
            _project_statuses_response(mapping={
                "To Do": "new",
                "In Progress": "indeterminate",
                "Done": "done",
            }),
            # pre-flight read
            _Response(200, json.dumps(
                _issue("AGENT-1", status="In Progress",
                       assignee_acct="5e-agent",
                       ap_value="agent-fin")
            ).encode(), {}),
        ]
        calls: list[dict] = []
        _attach_mock(drv, queue, calls)

        from drivers.jira import SelfApproveRefused
        try:
            drv.transition("AGENT-1", "APPROVED")
            assert False, "expected SelfApproveRefused"
        except SelfApproveRefused as e:
            assert "agent-fin" in str(e)


# --- (b) (c) intermediate categories now allowed ------------------------


def test_allow_when_target_category_is_indeterminate():
    """APPROVED → "REVIEW" (category=indeterminate) + AP=mine →
    transition runs (the actual #50 fix). Agent is signalling
    completion, not approving — human still has to push REVIEW → Done.
    """
    data = _seed_jira_data(approved_status="REVIEW")
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)
        drv = _patched_driver(data, proj)
        queue = [
            _project_statuses_response(mapping={
                "In Progress": "indeterminate",
                "REVIEW": "indeterminate",
                "Done": "done",
            }),
            # pre-flight read (status="In Progress")
            _Response(200, json.dumps(
                _issue("AGENT-1", status="In Progress",
                       assignee_acct="5e-agent",
                       ap_value="agent-fin")
            ).encode(), {}),
            # client.get_transitions
            _Response(200, json.dumps({"transitions": [
                {"id": "21", "name": "REVIEW",
                 "to": {"id": "10115", "name": "REVIEW"}},
            ]}).encode(), {}),
            # transition_issue
            _Response(204, b"", {}),
            # PUT labels
            _Response(204, b"", {}),
            # post-transition refresh
            _Response(200, json.dumps(
                _issue("AGENT-1", status="REVIEW",
                       assignee_acct="5e-agent",
                       ap_value="agent-fin",
                       labels=["kanban_awaiting_approval"])
            ).encode(), {}),
        ]
        calls: list[dict] = []
        _attach_mock(drv, queue, calls)

        # Should NOT raise — this is the regression #50 fixes.
        result = drv.transition("AGENT-1", "APPROVED")
        assert result.id == "AGENT-1"


def test_allow_when_target_category_is_new():
    """APPROVED → some status with category=new (rare; would mean
    APPROVED maps back to a TODO-like state) — also allowed.
    Anti-self-approve only fires on `done`."""
    data = _seed_jira_data(approved_status="Backlog")
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)
        drv = _patched_driver(data, proj)
        queue = [
            _project_statuses_response(mapping={
                "Backlog": "new",
                "In Progress": "indeterminate",
            }),
            _Response(200, json.dumps(
                _issue("AGENT-1", status="In Progress",
                       assignee_acct="5e-agent",
                       ap_value="agent-fin")
            ).encode(), {}),
            _Response(200, json.dumps({"transitions": [
                {"id": "31", "name": "Backlog",
                 "to": {"id": "1", "name": "Backlog"}},
            ]}).encode(), {}),
            _Response(204, b"", {}),
            _Response(204, b"", {}),
            _Response(200, json.dumps(
                _issue("AGENT-1", status="Backlog",
                       assignee_acct="5e-agent",
                       ap_value="agent-fin",
                       labels=["kanban_awaiting_approval"])
            ).encode(), {}),
        ]
        calls: list[dict] = []
        _attach_mock(drv, queue, calls)

        result = drv.transition("AGENT-1", "APPROVED")
        assert result.id == "AGENT-1"


# --- (d) lookup failure → distinct error --------------------------------


def test_lookup_failure_yields_distinct_error_not_self_approve():
    """When `get_project_statuses` returns 404 / fails to surface the
    target status, the helper returns None and the driver refuses
    with a DISTINCT error message — caller can tell 'API hiccup'
    apart from 'you tried to self-approve'."""
    data = _seed_jira_data(approved_status="Done")
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)
        drv = _patched_driver(data, proj)
        queue = [
            # statusCategory lookup fails
            _Response(404, b'{"errorMessages":["nope"]}', {}),
        ]
        calls: list[dict] = []
        _attach_mock(drv, queue, calls)

        from drivers.jira import SelfApproveRefused
        try:
            drv.transition("AGENT-1", "APPROVED")
            assert False, "expected RuntimeError"
        except SelfApproveRefused:
            assert False, "should NOT be SelfApproveRefused"
        except RuntimeError as e:
            msg = str(e)
            assert "lookup failed" in msg
            assert "anti-self-approve cannot be skipped" in msg
            # Mention the user-actionable next step
            assert "Retry" in msg or "retry" in msg


# --- (e) recording-for-other still works for done category --------------


def test_done_category_allows_when_assignee_is_other_human():
    """APPROVED → "Done" (category=done) + AP=mine + assignee=different
    human → allowed (existing #19 / #20 behavior preserved). Agent is
    recording on someone else's behalf, not approving its own work."""
    data = _seed_jira_data(approved_status="Done")
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)
        drv = _patched_driver(data, proj)
        queue = [
            _project_statuses_response(mapping={
                "In Progress": "indeterminate",
                "Done": "done",
            }),
            _Response(200, json.dumps(
                _issue("AGENT-1", status="In Progress",
                       assignee_acct="some-human",  # not agent
                       ap_value="agent-fin")
            ).encode(), {}),
            _Response(200, json.dumps({"transitions": [
                {"id": "31", "name": "Done",
                 "to": {"id": "10004", "name": "Done"}},
            ]}).encode(), {}),
            _Response(204, b"", {}),
            _Response(200, json.dumps(
                _issue("AGENT-1", status="Done",
                       assignee_acct="some-human",
                       ap_value="agent-fin")
            ).encode(), {}),
        ]
        calls: list[dict] = []
        _attach_mock(drv, queue, calls)

        result = drv.transition("AGENT-1", "APPROVED")
        assert result.id == "AGENT-1"


# --- (f) (g) lazy cache, no retry on failure ----------------------------


def test_status_category_cache_is_lazy_and_reused():
    """Two transitions on the same driver instance trigger
    `get_project_statuses` only once. The second call reuses the
    cached map."""
    data = _seed_jira_data(approved_status="REVIEW")
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)
        drv = _patched_driver(data, proj)
        queue = [
            # First transition: statusCategory lookup
            _project_statuses_response(mapping={
                "In Progress": "indeterminate",
                "REVIEW": "indeterminate",
                "Done": "done",
            }),
            # First transition: pre-flight + transitions list + apply +
            # labels PUT + refresh
            _Response(200, json.dumps(
                _issue("A-1", status="In Progress",
                       assignee_acct="5e-agent",
                       ap_value="agent-fin")
            ).encode(), {}),
            _Response(200, json.dumps({"transitions": [
                {"id": "21", "name": "REVIEW",
                 "to": {"id": "10115", "name": "REVIEW"}},
            ]}).encode(), {}),
            _Response(204, b"", {}),
            _Response(204, b"", {}),
            _Response(200, json.dumps(
                _issue("A-1", status="REVIEW", labels=["kanban_awaiting_approval"])
            ).encode(), {}),
            # Second transition: NO statusCategory lookup. Just
            # pre-flight + ... etc.
            _Response(200, json.dumps(
                _issue("A-2", status="In Progress",
                       assignee_acct="5e-agent",
                       ap_value="agent-fin")
            ).encode(), {}),
            _Response(200, json.dumps({"transitions": [
                {"id": "21", "name": "REVIEW",
                 "to": {"id": "10115", "name": "REVIEW"}},
            ]}).encode(), {}),
            _Response(204, b"", {}),
            _Response(204, b"", {}),
            _Response(200, json.dumps(
                _issue("A-2", status="REVIEW", labels=["kanban_awaiting_approval"])
            ).encode(), {}),
        ]
        calls: list[dict] = []
        _attach_mock(drv, queue, calls)

        drv.transition("A-1", "APPROVED")
        drv.transition("A-2", "APPROVED")

        # Exactly one call to /rest/api/3/project/AGENT/statuses
        cat_calls = [
            c for c in calls if "/project/AGENT/statuses" in c["url"]
        ]
        assert len(cat_calls) == 1, [c["url"] for c in calls]


def test_status_category_lookup_failure_not_retried():
    """Two transitions where the first fails statusCategory lookup —
    the second should NOT re-call (avoid retry storms). Both refuse
    with the distinct error."""
    data = _seed_jira_data(approved_status="Done")
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)
        drv = _patched_driver(data, proj)
        queue = [
            # First call: failure (404 — non-retryable so not consumed
            # by the JiraClient retry loop)
            _Response(404, b'{"errorMessages":["nope"]}', {}),
        ]
        calls: list[dict] = []
        _attach_mock(drv, queue, calls)

        # First transition fails
        try:
            drv.transition("AGENT-1", "APPROVED")
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass

        # Second transition — should NOT call get_project_statuses
        # again (queue is empty; if it tried we'd hit AssertionError).
        try:
            drv.transition("AGENT-2", "APPROVED")
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass

        # Total HTTP calls = 1 (just the first lookup)
        cat_calls = [
            c for c in calls if "/project/AGENT/statuses" in c["url"]
        ]
        assert len(cat_calls) == 1, [c["url"] for c in calls]


def main() -> int:
    cases = [
        ("block_when_target_category_is_done",
         test_block_when_target_category_is_done),
        ("allow_when_target_category_is_indeterminate",
         test_allow_when_target_category_is_indeterminate),
        ("allow_when_target_category_is_new",
         test_allow_when_target_category_is_new),
        ("lookup_failure_yields_distinct_error_not_self_approve",
         test_lookup_failure_yields_distinct_error_not_self_approve),
        ("done_category_allows_when_assignee_is_other_human",
         test_done_category_allows_when_assignee_is_other_human),
        ("status_category_cache_is_lazy_and_reused",
         test_status_category_cache_is_lazy_and_reused),
        ("status_category_lookup_failure_not_retried",
         test_status_category_lookup_failure_not_retried),
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
        print(f"phase29: {failed} failure(s)", file=sys.stderr)
        return 1
    print("phase29: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
