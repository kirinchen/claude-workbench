#!/usr/bin/env python3
"""Phase 21 regression checks for kanban v0.3.14 — `create_task` fixup
PUT for fields silently dropped by the Create Screen scheme.

Closes #35. Jira filters the POST `/rest/api/3/issue` body against the
project's Create Screen for the target issuetype: fields not on that
screen (commonly `labels` and AP custom fields on Story/Sub-task/Task)
are silently elided. The API returns 201 with a key, the plugin treats
that as success, and the requested fields don't stick. In one reporter's
session, 26 of 28 created issues lost their labels this way.

The fix POSTs as before, then fires a follow-up PUT to the same key
with the same `labels`. Edit Screen is generally more permissive than
Create Screen, so the PUT typically succeeds even when the POST silently
dropped the field. Best-effort: a fixup failure leaves an audit comment
but doesn't roll back the create.

Cases:
  (a) POST 201 + non-empty tags → follow-up PUT carries `labels`
      matching the requested tags; no system comment.
  (b) POST 201 + empty tags → NO fixup PUT (we'd just be PUTting an
      empty dict — wasteful and would still surface as a request).
  (c) POST 201 + tags + PUT 404 → system comment is posted, the
      create still returns successfully (user gets the card; the
      comment surfaces the missing fields).
  (d) Fixup PUT fires BEFORE the parent-link POST when both apply, so
      a later link failure can't mask a prior fixup failure.
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


def _seed_jira_data():
    return {
        "version": "0.2",
        "backend": {"driver": "jira", "jira": {
            "boardUrl": "https://x/jira/projects/AGENT/boards/1",
            "boardId": 1, "projectKey": "AGENT",
            "agentAccountId": "5e-agent",
            "transitions": {
                "TODO": {"status": "To Do"},
                "DOING": {"status": "In Progress"},
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


def _refresh_response(key, *, labels=()):
    """Response shape for the post-create driver.get_task() refresh."""
    return _Response(200, json.dumps({
        "key": key,
        "fields": {
            "summary": "x",
            "status": {"name": "To Do"},
            "priority": {"name": "P1"},
            "assignee": None,
            "labels": list(labels),
            "created": "x", "updated": "y",
            "issuelinks": [],
            "customfield_10042": None,
        },
    }).encode(), {})


def test_create_task_fixup_put_carries_labels():
    """POST returns key; subsequent PUT must include `labels` matching
    the requested tags — this is the actual #35 fix."""
    data = _seed_jira_data()
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        drv = _patched_driver(data, proj)
        queue = [
            # POST /issue → 201 (Jira may have silently filtered labels)
            _Response(201, json.dumps({"key": "AGENT-100"}).encode(), {}),
            # PUT /issue/AGENT-100 → 204 (fixup succeeds)
            _Response(204, b"", {}),
            # Final get_task refresh
            _refresh_response("AGENT-100", labels=["alpha", "beta"]),
        ]
        calls: list[dict] = []
        _attach_mock(drv, queue, calls)

        from drivers.base import TaskInput
        drv.create_task(TaskInput(title="x", tags=["alpha", "beta"]))

        # Find the PUT
        put = next(
            (c for c in calls if c["method"] == "PUT" and "/issue/AGENT-100" in c["url"]),
            None,
        )
        assert put is not None, [c["method"] + " " + c["url"] for c in calls]
        sent = json.loads(put["body"])
        assert sent["fields"]["labels"] == ["alpha", "beta"], sent


def test_create_task_no_fixup_when_no_tags():
    """No tags → nothing to re-assert → no PUT fires (avoid pointless
    extra request)."""
    data = _seed_jira_data()
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        drv = _patched_driver(data, proj)
        queue = [
            _Response(201, json.dumps({"key": "AGENT-101"}).encode(), {}),
            # NO PUT in the queue — if create_task fires one, queue
            # underflow raises IndexError.
            _refresh_response("AGENT-101"),
        ]
        calls: list[dict] = []
        _attach_mock(drv, queue, calls)

        from drivers.base import TaskInput
        drv.create_task(TaskInput(title="x"))  # no tags

        # No PUT against the new key
        put_calls = [c for c in calls if c["method"] == "PUT"]
        assert put_calls == [], put_calls


def test_create_task_fixup_failure_posts_system_comment_and_continues():
    """If the fixup PUT fails, the create must still succeed — better
    "labels silently missing" than "no card at all". An audit comment
    surfaces the failure for the user."""
    data = _seed_jira_data()
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        drv = _patched_driver(data, proj)
        queue = [
            # POST → 201
            _Response(201, json.dumps({"key": "AGENT-102"}).encode(), {}),
            # PUT → 404 (non-retryable; simulates permission filter)
            _Response(404, b'{"errorMessages":["forbidden"]}', {}),
            # System comment POST (best-effort audit trail)
            _Response(201, b'{"created":"2026-05-03T00:00:00+08:00"}', {}),
            # Final refresh
            _refresh_response("AGENT-102"),
        ]
        calls: list[dict] = []
        _attach_mock(drv, queue, calls)

        from drivers.base import TaskInput
        # Create succeeds — does NOT raise
        result = drv.create_task(TaskInput(title="x", tags=["lost-label"]))
        assert result.id == "AGENT-102"

        # System comment posted with our specific marker text
        comment_call = next(
            (c for c in calls
             if c["method"] == "POST" and "/comment" in c["url"]),
            None,
        )
        assert comment_call is not None, [c["method"] + " " + c["url"] for c in calls]
        sent = json.loads(comment_call["body"])
        # adf_to_text drops marks but keeps text content
        from lib.jira_client import adf_to_text
        body_text = adf_to_text(sent["body"])
        assert "fixup failed" in body_text, body_text
        assert "labels" in body_text, body_text


def test_create_task_fixup_runs_before_parent_link():
    """Order matters: fixup PUT must fire BEFORE parent-link POST so a
    later link failure can't hide a prior fixup failure (the audit trail
    surfaces both independently)."""
    data = _seed_jira_data()
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        drv = _patched_driver(data, proj)
        queue = [
            _Response(201, json.dumps({"key": "AGENT-103"}).encode(), {}),
            _Response(204, b"", {}),  # fixup PUT
            _Response(201, b'{"id":"99"}', {}),  # issueLink POST
            _refresh_response("AGENT-103", labels=["x"]),
        ]
        calls: list[dict] = []
        _attach_mock(drv, queue, calls)

        from drivers.base import TaskInput
        drv.create_task(TaskInput(
            title="x", tags=["x"],
            parent_key="AGENT-1", link_type="Relates",
        ))

        # Find indices of the fixup PUT and the issueLink POST
        idx_put = next(
            i for i, c in enumerate(calls)
            if c["method"] == "PUT" and "/issue/AGENT-103" in c["url"]
        )
        idx_link = next(
            i for i, c in enumerate(calls)
            if c["method"] == "POST" and "issueLink" in c["url"]
        )
        assert idx_put < idx_link, (idx_put, idx_link, calls)


def main() -> int:
    cases = [
        ("create_task_fixup_put_carries_labels",
         test_create_task_fixup_put_carries_labels),
        ("create_task_no_fixup_when_no_tags",
         test_create_task_no_fixup_when_no_tags),
        ("create_task_fixup_failure_posts_system_comment_and_continues",
         test_create_task_fixup_failure_posts_system_comment_and_continues),
        ("create_task_fixup_runs_before_parent_link",
         test_create_task_fixup_runs_before_parent_link),
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
        print(f"phase21: {failed} failure(s)", file=sys.stderr)
        return 1
    print("phase21: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
