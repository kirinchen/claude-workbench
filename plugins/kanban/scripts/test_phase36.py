#!/usr/bin/env python3
"""Phase 36 regression checks for kanban v0.3.31 — list_tasks JQL honours
addLabels on columns that share a Jira status.

Closes #63. Pre-fix, `JiraDriver.list_tasks(column=BLOCKED)` and
`list_tasks(column=DOING)` produced identical JQL when BLOCKED/DOING both
mapped to "In Progress" (BLOCKED disambiguated by `kanban:blocked`):

    project = "BZK" AND status = "In Progress"

That made `/kanban:sync` count every In-Progress card twice and list it
under both DOING and BLOCKED. `disambiguate()` was already label-aware on
the read-back side, but the JQL on the fetch side was status-only.

The fix routes column filtering through `_column_jql_clauses`, which
mirrors `disambiguate`'s semantics:

  * AND-includes `labels = "X"` for each of the column's `addLabels`.
  * AND-excludes `labels = "X"` for each of the column's `removeLabels`.
  * AND-excludes same-status siblings whose `addLabels` is a strict
    superset of ours — those cards belong to the more-specific sibling.

Cases:
  (a) BLOCKED JQL includes its addLabels positively.
  (b) DOING (bare on shared status) excludes every more-specific sibling's
      label, so it never returns BLOCKED or REVIEW cards.
  (c) REVIEW only includes its own addLabel — BLOCKED's label is NOT a
      strict superset of REVIEW's (they are disjoint), so it is not
      excluded.
  (d) A column whose status no other column shares emits exactly the
      legacy status-only clause — no spurious `labels` clauses (backward
      compatibility).
  (e) removeLabels surface as `NOT labels = "X"` clauses.
  (f) An unmapped column (no transitions entry) falls back to legacy
      label_fallback behaviour and does NOT inject status / labels
      clauses on its own.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "plugins" / "kanban"))

from drivers.base import TaskFilter  # noqa: E402
from drivers.jira import JiraDriver  # noqa: E402
from lib.jira_client import JiraClient, _Response  # noqa: E402


def _build_driver(transitions: dict, *, project_key: str = "BZK") -> tuple[JiraDriver, list]:
    """Construct a JiraDriver with a mocked transport that records the
    JSON body of every request and replies with an empty issue list.

    Returns (driver, calls). `calls[-1]["body"]["jql"]` is the JQL of the
    most recent `search_jql`.
    """
    calls: list[dict] = []

    def transport(method, url, headers, body):
        calls.append({
            "method": method,
            "url": url,
            "body": json.loads(body) if body else None,
        })
        return _Response(200, b'{"issues": []}', {})

    kanban_data = {
        "backend": {
            "driver": "jira",
            "jira": {
                "projectKey": project_key,
                "transitions": transitions,
            },
        }
    }
    with tempfile.TemporaryDirectory() as td:
        drv = JiraDriver(kanban_data, pathlib.Path(td))

    # Inject the mock client. _client_or_raise gates on truthy
    # base_url/email/_token before returning the cached client.
    drv.base_url = "https://x.atlassian.net"
    drv.email = "agent@example.com"
    drv._token = "tok"
    drv._client = JiraClient(
        drv.base_url, drv.email, drv._token,
        transport=transport, sleep=lambda _: None,
    )
    return drv, calls


# The canonical shared-status setup from the issue report.
SHARED = {
    "TODO":     {"status": "Selected for Development"},
    "DOING":    {"status": "In Progress"},
    "BLOCKED":  {"status": "In Progress", "addLabels": ["kanban:blocked"]},
    "REVIEW":   {"status": "In Progress", "addLabels": ["kanban:review"]},
    "APPROVED": {"status": "Done"},
}


def _jql_for(transitions: dict, column: str) -> str:
    drv, calls = _build_driver(transitions)
    drv.list_tasks(TaskFilter(column=column))
    return calls[-1]["body"]["jql"]


def test_blocked_jql_includes_addlabels():
    jql = _jql_for(SHARED, "BLOCKED")
    assert 'status = "In Progress"' in jql, jql
    assert 'labels = "kanban:blocked"' in jql, jql


def test_doing_jql_excludes_every_competing_label():
    """The bug case from #63 — bare DOING must not return BLOCKED or
    REVIEW cards just because they all live on "In Progress"."""
    jql = _jql_for(SHARED, "DOING")
    assert 'status = "In Progress"' in jql, jql
    assert 'NOT labels = "kanban:blocked"' in jql, jql
    assert 'NOT labels = "kanban:review"' in jql, jql


def test_review_jql_only_includes_own_addlabel():
    """REVIEW's addLabels = {kanban:review} is disjoint from BLOCKED's
    {kanban:blocked} — neither is a strict superset of the other, so
    REVIEW must not exclude BLOCKED's label. Disambiguate's
    alphabetical tie-break handles cards carrying both labels."""
    jql = _jql_for(SHARED, "REVIEW")
    assert 'status = "In Progress"' in jql, jql
    assert 'labels = "kanban:review"' in jql, jql
    assert 'NOT labels = "kanban:blocked"' not in jql, jql


def test_unshared_status_emits_only_status_clause():
    """Backward-compatibility: a column whose status no other column
    shares produces exactly the legacy status-only JQL — no spurious
    `labels` clauses."""
    jql = _jql_for(SHARED, "TODO")
    assert 'status = "Selected for Development"' in jql, jql
    assert "labels" not in jql, jql


def test_remove_labels_become_not_clauses():
    """`removeLabels` surface as `NOT labels = "X"` clauses."""
    transitions = {
        "DOING":   {"status": "In Progress",
                    "removeLabels": ["kanban:archived"]},
        "BLOCKED": {"status": "In Progress",
                    "addLabels": ["kanban:blocked"]},
    }
    jql = _jql_for(transitions, "DOING")
    assert 'NOT labels = "kanban:archived"' in jql, jql
    # Sibling exclusion still applies on top of removeLabels.
    assert 'NOT labels = "kanban:blocked"' in jql, jql


def test_unmapped_column_falls_through_without_clauses():
    """A column not in `transitions` produces no clauses from the helper;
    list_tasks then falls back to the legacy label_fallback path (which
    is a no-op for v0.3 configs)."""
    transitions = {"DOING": {"status": "In Progress"}}
    drv, calls = _build_driver(transitions)
    drv.list_tasks(TaskFilter(column="CANCELLED"))
    jql = calls[-1]["body"]["jql"]
    # Only the `project = ...` and ORDER BY clauses remain — no
    # status/labels filter for the unmapped column.
    assert 'status' not in jql, jql
    assert 'labels' not in jql, jql
    assert 'project = "BZK"' in jql, jql


def test_legacy_single_status_per_column_unchanged():
    """A pre-#63 transitions map (every column on its own status) emits
    exactly one `status = ...` clause per column. No regressions."""
    transitions = {
        "TODO":     {"status": "To Do"},
        "DOING":    {"status": "In Progress"},
        "APPROVED": {"status": "Done"},
    }
    jql = _jql_for(transitions, "DOING")
    assert 'status = "In Progress"' in jql, jql
    assert "labels" not in jql, jql


def main() -> None:
    tests = [
        ("blocked_jql_includes_addlabels",
         test_blocked_jql_includes_addlabels),
        ("doing_jql_excludes_every_competing_label",
         test_doing_jql_excludes_every_competing_label),
        ("review_jql_only_includes_own_addlabel",
         test_review_jql_only_includes_own_addlabel),
        ("unshared_status_emits_only_status_clause",
         test_unshared_status_emits_only_status_clause),
        ("remove_labels_become_not_clauses",
         test_remove_labels_become_not_clauses),
        ("unmapped_column_falls_through_without_clauses",
         test_unmapped_column_falls_through_without_clauses),
        ("legacy_single_status_per_column_unchanged",
         test_legacy_single_status_per_column_unchanged),
    ]
    for name, fn in tests:
        fn()
        print(f"ok    {name}")
    print("phase36: all checks passed")


if __name__ == "__main__":
    main()
