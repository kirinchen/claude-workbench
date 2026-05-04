#!/usr/bin/env python3
"""Phase 27 regression checks for kanban v0.3.22 — REVIEW flavors in
transitions DSL.

Closes #45. The transitions DSL gains an optional `flavors` block per
canonical state plus an optional `defaultFlavor` fallback. When the
caller invokes `transition --flavor NAME`, the chosen flavor's
addLabels / removeLabels / assignee merge atomically with the parent
spec onto the compound write. Lifecycle stage (canonical state) and
within-stage sub-classification (flavor) stay separate concepts; this
keeps `/kanban:status`, anti-self-approve, and reconcile from
ballooning.

Cases:
  (a) `transitions.validate` accepts a well-formed flavors block.
  (b) `transitions.validate` rejects: non-dict flavors, empty flavors
      object, non-string flavor name, flavor with bad addLabels,
      flavor with bad assignee, defaultFlavor not in flavors,
      defaultFlavor without flavors block.
  (c) Driver `transition()` with `flavor=` merges that flavor's
      addLabels onto the parent spec's addLabels (the heart of the
      atomic write — status + parent labels + flavor labels go in one
      compound transition).
  (d) Driver `transition()` with no `flavor=` BUT spec has
      `defaultFlavor` falls back to the default.
  (e) Driver `transition()` with no `flavor=` AND no `defaultFlavor`
      AND spec has flavors → raise with the available flavor list in
      the message.
  (f) Driver `transition()` with an invalid flavor name → raise with
      the available list.
  (g) Driver `transition()` with `flavor=` on a state that has no
      flavors block → silently ignore (forward compat — callers can
      pass it unconditionally without per-spec branching).
  (h) `cmd_transition` argparse threads `--flavor` into kwargs.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"
sys.path.insert(0, str(REPO / "plugins" / "kanban"))

from lib import transitions as _tr  # noqa: E402
from lib.jira_client import JiraClient, _Response  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "jira_setup_mod", str(PLUGIN / "scripts" / "jira_setup.py")
)
_jira_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_jira_setup)  # type: ignore[union-attr]


# --- (a) (b) validator ---------------------------------------------------


def test_validate_accepts_well_formed_flavors():
    cfg = {
        "REVIEW": {
            "status": "REVIEW",
            "flavors": {
                "awaiting_approval": {"addLabels": ["kanban_awaiting_approval"]},
                "needs_decision": {"addLabels": ["kanban_needs_decision"]},
            },
            "defaultFlavor": "awaiting_approval",
        },
        "DOING": {"status": "In Progress"},
    }
    errs = _tr.validate(cfg)
    assert errs == [], errs


def test_validate_rejects_malformed_flavors():
    fn = _tr.validate

    # flavors not a dict
    e = fn({"REVIEW": {"status": "REVIEW", "flavors": []}})
    assert any("flavors must be" in x for x in e), e

    # empty flavors
    e = fn({"REVIEW": {"status": "REVIEW", "flavors": {}}})
    assert any("flavors must be" in x for x in e), e

    # flavor body not a dict
    e = fn({"REVIEW": {"status": "REVIEW", "flavors": {"x": 42}}})
    assert any("flavors.x: must be an object" in x for x in e), e

    # bad addLabels inside flavor
    e = fn({"REVIEW": {"status": "REVIEW",
                       "flavors": {"x": {"addLabels": [None]}}}})
    assert any("flavors.x: addLabels must be" in x for x in e), e

    # bad assignee inside flavor
    e = fn({"REVIEW": {"status": "REVIEW",
                       "flavors": {"x": {"assignee": "bad"}}}})
    assert any("flavors.x: assignee must be" in x for x in e), e

    # defaultFlavor not in flavors
    e = fn({"REVIEW": {"status": "REVIEW",
                       "flavors": {"a": {}},
                       "defaultFlavor": "b"}})
    assert any("defaultFlavor 'b' is not in flavors keys" in x for x in e), e

    # defaultFlavor without flavors block
    e = fn({"REVIEW": {"status": "REVIEW", "defaultFlavor": "x"}})
    assert any("defaultFlavor set but no flavors block" in x for x in e), e


# --- (c)..(g) driver transition() flavor wiring -------------------------


def _seed_jira_data_with_flavors(*, default_flavor=None):
    review_spec = {
        "status": "REVIEW",
        "flavors": {
            "awaiting_approval": {"addLabels": ["kanban_awaiting_approval"]},
            "needs_decision": {"addLabels": ["kanban_needs_decision"]},
        },
    }
    if default_flavor is not None:
        review_spec["defaultFlavor"] = default_flavor
    return {
        "version": "0.2",
        "backend": {"driver": "jira", "jira": {
            "boardUrl": "https://x/jira/projects/AGENT/boards/1",
            "boardId": 1, "projectKey": "AGENT",
            "agentAccountId": "5e-agent",
            "transitions": {
                "TODO": {"status": "To Do"},
                "DOING": {"status": "In Progress"},
                "REVIEW": review_spec,
                "APPROVED": {"status": "Done"},
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


def _seed_jira_data_no_flavors():
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
                "APPROVED": {"status": "Done"},
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


def _seed_repo_ap(repo, ap="agent-fin"):
    (repo / ".claude").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "kanban-agent.json").write_text(
        json.dumps({"ap": ap}) + "\n"
    )


def _issue_response(key, *, status_name="In Progress", labels=(),
                    assignee_acct="some-human", ap_value="agent-fin"):
    return _Response(200, json.dumps({
        "key": key,
        "fields": {
            "summary": "x",
            "status": {"name": status_name},
            "priority": {"name": "P1"},
            "assignee": {"accountId": assignee_acct} if assignee_acct else None,
            "labels": list(labels),
            "created": "x", "updated": "y",
            "issuelinks": [],
            "customfield_10042": {"value": ap_value},
        },
    }).encode(), {})


def test_transition_with_flavor_merges_addlabels():
    """The compound write must PUT labels including the flavor's
    addLabels — that's the atomicity guarantee #45 buys."""
    data = _seed_jira_data_with_flavors()
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)
        drv = _patched_driver(data, proj)
        queue = [
            _issue_response("AGENT-1", status_name="In Progress"),
            _Response(200, json.dumps({"transitions": [
                {"id": "21", "name": "REVIEW",
                 "to": {"id": "10115", "name": "REVIEW"}},
            ]}).encode(), {}),
            _Response(204, b"", {}),  # transition_issue
            _Response(204, b"", {}),  # PUT labels
            _issue_response("AGENT-1", status_name="REVIEW",
                            labels=["kanban_awaiting_approval"]),
        ]
        calls: list[dict] = []
        _attach_mock(drv, queue, calls)

        drv.transition("AGENT-1", "REVIEW", flavor="awaiting_approval")

        # Find the PUT to /issue/AGENT-1 (label sync)
        put_call = next(
            c for c in calls
            if c["method"] == "PUT"
            and "/issue/AGENT-1" in c["url"]
            and "labels" in (c["body"] or b"").decode("utf-8", errors="replace")
        )
        sent = json.loads(put_call["body"])
        assert "kanban_awaiting_approval" in sent["fields"]["labels"], sent


def test_transition_without_flavor_uses_default():
    """When the spec carries `defaultFlavor`, omitting --flavor falls
    back to it — convenience for the most-common path."""
    data = _seed_jira_data_with_flavors(default_flavor="awaiting_approval")
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)
        drv = _patched_driver(data, proj)
        queue = [
            _issue_response("AGENT-1", status_name="In Progress"),
            _Response(200, json.dumps({"transitions": [
                {"id": "21", "name": "REVIEW",
                 "to": {"id": "10115", "name": "REVIEW"}},
            ]}).encode(), {}),
            _Response(204, b"", {}),
            _Response(204, b"", {}),
            _issue_response("AGENT-1", status_name="REVIEW",
                            labels=["kanban_awaiting_approval"]),
        ]
        calls: list[dict] = []
        _attach_mock(drv, queue, calls)

        drv.transition("AGENT-1", "REVIEW")  # no flavor=

        put_call = next(
            c for c in calls
            if c["method"] == "PUT"
            and "/issue/AGENT-1" in c["url"]
            and "labels" in (c["body"] or b"").decode("utf-8", errors="replace")
        )
        sent = json.loads(put_call["body"])
        assert "kanban_awaiting_approval" in sent["fields"]["labels"]


def test_transition_missing_flavor_no_default_raises():
    data = _seed_jira_data_with_flavors()  # no defaultFlavor
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)
        drv = _patched_driver(data, proj)
        # Pre-flight read still fires; no transition_issue / PUT should
        # happen before the flavor check rejects.
        # Actually our code resolves flavor BEFORE the get_task call,
        # so the queue should be empty (or just the resolution raises
        # before reading anything).
        _attach_mock(drv, [], [])

        try:
            drv.transition("AGENT-1", "REVIEW")
        except RuntimeError as e:
            msg = str(e)
            assert "requires --flavor" in msg, msg
            assert "awaiting_approval" in msg
            assert "needs_decision" in msg
            return
        raise AssertionError("expected RuntimeError on missing flavor")


def test_transition_invalid_flavor_raises():
    data = _seed_jira_data_with_flavors()
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)
        drv = _patched_driver(data, proj)
        _attach_mock(drv, [], [])

        try:
            drv.transition("AGENT-1", "REVIEW", flavor="bogus")
        except RuntimeError as e:
            msg = str(e)
            assert "unknown flavor 'bogus'" in msg
            assert "awaiting_approval" in msg
            return
        raise AssertionError("expected RuntimeError on unknown flavor")


def test_transition_flavor_ignored_when_state_has_no_flavors():
    """Forward compat: callers can pass --flavor unconditionally;
    states without a flavors block ignore it (no failure, no label)."""
    data = _seed_jira_data_no_flavors()
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)
        drv = _patched_driver(data, proj)
        queue = [
            _issue_response("AGENT-1", status_name="In Progress"),
            _Response(200, json.dumps({"transitions": [
                {"id": "21", "name": "REVIEW",
                 "to": {"id": "10115", "name": "REVIEW"}},
            ]}).encode(), {}),
            _Response(204, b"", {}),
            _issue_response("AGENT-1", status_name="REVIEW"),
        ]
        calls: list[dict] = []
        _attach_mock(drv, queue, calls)

        # Should NOT raise; the spurious flavor is silently dropped.
        drv.transition("AGENT-1", "REVIEW", flavor="anything")

        # No label PUT fires (no addLabels in the parent spec, no flavor
        # block to merge from). Tally should not include a /issue/AGENT-1
        # PUT with a labels payload.
        leaked_label_put = any(
            c["method"] == "PUT"
            and "/issue/AGENT-1" in c["url"]
            and "labels" in (c["body"] or b"").decode("utf-8", errors="replace")
            for c in calls
        )
        assert not leaked_label_put, calls


# --- (h) cmd_transition wires --flavor through ---------------------------


def test_cmd_transition_threads_flavor_into_driver():
    """Verify the argparse-supplied --flavor reaches driver.transition's
    kwargs."""
    received: dict = {}

    class _StubDrv:
        name = "jira"
        def transition(self, key, to_column, **kwargs):
            received["key"] = key
            received["to_column"] = to_column
            received["kwargs"] = kwargs
            from drivers.base import Task
            return Task(
                id=key, title="x", column="REVIEW", priority="P1",
                created="x", updated="y", custom={"raw_status": "REVIEW"},
            )

    import drivers as _drv_mod
    d_orig = _drv_mod.get_driver
    _drv_mod.get_driver = lambda data, root: _StubDrv()

    try:
        with tempfile.TemporaryDirectory() as td:
            kp = pathlib.Path(td) / "kanban.json"
            kp.write_text(json.dumps(_seed_jira_data_with_flavors()))

            class A:
                kanban_path = str(kp)
                key = "AGENT-1"
                to = "REVIEW"
                reason = None
                blocked_by = None
                flavor = "needs_decision"
            from io import StringIO
            old = sys.stdout
            sys.stdout = StringIO()
            try:
                try:
                    rc = _jira_setup.cmd_transition(A())
                except SystemExit as e:
                    rc = e.code
            finally:
                sys.stdout = old
    finally:
        _drv_mod.get_driver = d_orig

    assert rc == 0
    assert received["kwargs"].get("flavor") == "needs_decision", received


def main() -> int:
    cases = [
        ("validate_accepts_well_formed_flavors",
         test_validate_accepts_well_formed_flavors),
        ("validate_rejects_malformed_flavors",
         test_validate_rejects_malformed_flavors),
        ("transition_with_flavor_merges_addlabels",
         test_transition_with_flavor_merges_addlabels),
        ("transition_without_flavor_uses_default",
         test_transition_without_flavor_uses_default),
        ("transition_missing_flavor_no_default_raises",
         test_transition_missing_flavor_no_default_raises),
        ("transition_invalid_flavor_raises",
         test_transition_invalid_flavor_raises),
        ("transition_flavor_ignored_when_state_has_no_flavors",
         test_transition_flavor_ignored_when_state_has_no_flavors),
        ("cmd_transition_threads_flavor_into_driver",
         test_cmd_transition_threads_flavor_into_driver),
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
        print(f"phase27: {failed} failure(s)", file=sys.stderr)
        return 1
    print("phase27: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
