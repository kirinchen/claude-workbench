#!/usr/bin/env python3
"""Phase 19 regression checks for kanban v0.3.12 — locale-immune workflow,
JQL timestamp normalization, ADF strong-mark prefix.

Closes #17 (re-opened), #26, #27.

Cases:
  (a) transition() falls back to matching by transition action name when
      the destination status name is locale-translated (#17).
  (b) transition() still works when only the destination status name
      matches (English locale, action name differs).
  (c) _detect_reconcile builds locale-immune `status not in (...)` JQL
      and, when no DSL transitions are configured, skips query 1 entirely
      (#17 — server-side filter cannot be expressed without a mapped set).
  (d) _jql_quote_ts converts ISO-8601 with offset to JQL canonical
      `yyyy-MM-dd HH:mm` (#26).
  (e) _jql_quote_ts passes through already-canonical short forms (#26).
  (f) cmd_find_mentions sends the rewritten timestamp in its JQL (#26).
  (g) post_comment with @-mention emits a strong-marked prefix paragraph
      (no markdown literals) followed by the mention paragraph (#27).
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

from lib.jira_client import JiraClient, _Response  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "jira_setup_mod", str(PLUGIN / "scripts" / "jira_setup.py")
)
_jira_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_jira_setup)  # type: ignore[union-attr]


def _mock_client(queue, calls):
    def t(method, url, headers, body):
        calls.append({"method": method, "url": url, "body": body})
        if not queue:
            raise AssertionError(f"queue empty for {method} {url}")
        return queue.pop(0)
    return JiraClient(
        "https://x", "a@b", "tok",
        transport=t, sleep=lambda _: None,
    )


def _capture(fn, args):
    from io import StringIO
    old = sys.stdout
    sys.stdout = StringIO()
    try:
        try:
            rc = fn(args)
        except SystemExit as e:
            rc = e.code
        out = sys.stdout.getvalue()
    finally:
        sys.stdout = old
    return rc, out


# --- (a) (b) transition lookup OR-fallback ------------------------------


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
                "REVIEW": {"status": "REVIEW"},
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
    # Pre-seed status-category cache (#50) so transition tests skip
    # the lookup hop. Phase 19's locale tests use 審查 / 完成 etc.
    drv._status_categories = {
        "To Do": "new",
        "In Progress": "indeterminate",
        "REVIEW": "indeterminate",
        "Done": "done",
        "Resolved": "done",
        "進行中": "indeterminate",
        "審查": "indeterminate",
        "完成": "done",
    }


def _seed_repo_ap(repo: pathlib.Path, ap: str = "agent-fin"):
    (repo / ".claude").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "kanban-agent.json").write_text(
        json.dumps({"ap": ap}) + "\n"
    )


def _issue_response(key, *, status_name="In Progress", labels=(),
                    assignee_acct="some-human", ap_value="agent-fin"):
    """Minimal `get_issue` response used by transition()'s pre-flight read."""
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


def test_transition_matches_by_action_name_when_status_localized():
    """zh-TW workflow: action.name='REVIEW' (English), to.name='審查'
    (locale-translated). DSL says status='REVIEW'. Old code matched only
    on to.name and failed; new code matches on the action name."""
    data = _seed_jira_data()
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)
        drv = _patched_driver(data, proj)
        queue = [
            # Pre-flight read for status check (TODO → REVIEW transition)
            _issue_response("AGENT-1", status_name="To Do"),
            # get_transitions: only zh-TW localized to.name available;
            # action name stays canonical English.
            _Response(200, json.dumps({"transitions": [
                {"id": "11", "name": "Start Progress",
                 "to": {"id": "10001", "name": "進行中"}},
                {"id": "21", "name": "REVIEW",
                 "to": {"id": "10115", "name": "審查"}},
                {"id": "31", "name": "Done",
                 "to": {"id": "10004", "name": "完成"}},
            ]}).encode(), {}),
            # transition_issue acceptance (no body)
            _Response(204, b"", {}),
            # Post-transition refresh read (driver.get_task)
            _issue_response("AGENT-1", status_name="REVIEW"),
        ]
        calls: list[dict] = []
        _attach_mock(drv, queue, calls)

        drv.transition("AGENT-1", "REVIEW")
        # The accepted transition must have id=21 (matched via action name)
        transition_call = next(
            c for c in calls
            if c["url"].endswith("/transitions") and c["method"] == "POST"
        )
        sent = json.loads(transition_call["body"])
        assert sent["transition"]["id"] == "21", sent


def test_transition_still_matches_by_destination_status_name():
    """English locale: action.name='Resolve Issue', to.name='Done',
    DSL='Done'. Match falls through to the to.name branch."""
    data = _seed_jira_data()
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj)
        drv = _patched_driver(data, proj)
        queue = [
            _issue_response("AGENT-1", status_name="In Progress"),
            _Response(200, json.dumps({"transitions": [
                {"id": "11", "name": "Send Back",
                 "to": {"id": "10000", "name": "To Do"}},
                {"id": "31", "name": "Resolve Issue",
                 "to": {"id": "10004", "name": "Done"}},
            ]}).encode(), {}),
            _Response(204, b"", {}),
            _issue_response("AGENT-1", status_name="Done"),
        ]
        calls: list[dict] = []
        _attach_mock(drv, queue, calls)

        drv.transition("AGENT-1", "APPROVED")
        transition_call = next(
            c for c in calls
            if c["url"].endswith("/transitions") and c["method"] == "POST"
        )
        sent = json.loads(transition_call["body"])
        # Must match id=31 (via to.name="Done"), NOT id=11 (which would
        # match neither field). Old behavior is preserved.
        assert sent["transition"]["id"] == "31", sent


# --- (c) reconcile skips query 1 when no DSL transitions ----------------


def test_detect_reconcile_skips_when_no_transitions():
    """No DSL → no mapped_statuses → no `status not in (...)` filter to
    construct → query 1 must not fire (we'd otherwise build invalid JQL
    or return every open card as 'unmapped'). Only missing-AP runs."""
    queue = [
        # Only the missing-AP query
        _Response(200, json.dumps({"issues": [
            {"key": "A-9", "fields": {"status": {"name": "x"}}},
        ]}).encode(), {}),
    ]
    calls: list[dict] = []
    c = _mock_client(queue, calls)
    unmapped, missing, errs = _jira_setup._detect_reconcile(
        c, "AGENT", transitions={},
        ap_field_id="customfield_10042", repo_ap="agent-fin",
    )
    assert unmapped == {}
    assert missing == ["A-9"]
    assert errs == []
    assert len(calls) == 1, calls
    # Single call must be the missing-AP query
    payload = json.loads((calls[0]["body"] or b"{}").decode())
    assert "is EMPTY" in payload.get("jql", "")


# --- (d) (e) _jql_quote_ts ----------------------------------------------


def test_jql_quote_ts_normalizes_iso_with_offset():
    """ISO-8601 with timezone offset is what `cmd_find_mentions` produces
    by default. Jira JQL silently rejects this format (#26) — must be
    converted to canonical `yyyy-MM-dd HH:mm`."""
    fn = _jira_setup._jql_quote_ts
    # The exact input that broke production (per #26)
    assert fn("2026-05-02T11:44:37+08:00") == "2026-05-02 11:44"
    # UTC offset
    assert fn("2026-05-02T00:00:00+00:00") == "2026-05-02 00:00"
    # No-offset ISO (still a `T` separator) → also normalized
    assert fn("2026-05-02T11:44:37") == "2026-05-02 11:44"


def test_jql_quote_ts_handles_canonical_short_forms():
    """Already-canonical formats produce JQL-friendly output: ISO date-only
    parses and gets normalized to `yyyy-MM-dd 00:00` (still JQL-canonical);
    slash-form (which fromisoformat can't parse) passes through unchanged.
    Either way the result is something JQL accepts."""
    fn = _jira_setup._jql_quote_ts
    # Date-only ISO parses; emerges as yyyy-MM-dd 00:00 (JQL accepts this).
    assert fn("2026-05-02") == "2026-05-02 00:00"
    # Slash-form is not ISO — fromisoformat raises, falls through unchanged.
    assert fn("2026/05/02 00:00") == "2026/05/02 00:00"


def test_jql_quote_ts_rejects_quote_injection():
    """Defensive — protects against any caller-side `since` containing
    a `"` that would break the JQL string literal."""
    try:
        _jira_setup._jql_quote_ts('2026-05-02"; OR 1=1 --')
    except ValueError:
        return
    raise AssertionError("expected ValueError on quoted timestamp")


# --- (f) cmd_find_mentions sends rewritten timestamp --------------------


def test_find_mentions_sends_normalized_timestamp_in_jql():
    """The default-since ISO-with-offset path is the regression that
    masked production mentions. Verify the resulting JQL uses the
    canonical short form."""
    queue = [
        # search_jql response — empty issues, but we only care about the
        # outgoing JQL.
        _Response(200, json.dumps({"issues": []}).encode(), {}),
    ]
    calls: list[dict] = []
    c = _mock_client(queue, calls)

    with tempfile.TemporaryDirectory() as td:
        kp = pathlib.Path(td) / "kanban.json"
        kp.write_text(json.dumps({
            "version": "0.2",
            "backend": {"driver": "jira", "jira": {
                "projectKey": "AGENT",
                "agentAccountId": "5e-agent",
                "ap": {"fieldId": "customfield_10042"},
            }},
            "meta": {"priorities": ["P0"], "categories": [],
                     "columns": ["TODO", "DOING", "BLOCKED", "REVIEW",
                                 "APPROVED", "CANCELLED"],
                     "created_at": "x", "updated_at": "x"},
            "tasks": [],
        }))
        orig_client = _jira_setup._client_from_env
        _jira_setup._client_from_env = lambda: c
        try:
            class A:
                kanban_path = str(kp)
                since = "2026-05-02T11:44:37+08:00"
            rc, out = _capture(_jira_setup.cmd_find_mentions, A())
        finally:
            _jira_setup._client_from_env = orig_client

    assert rc == 0, out
    payload = json.loads((calls[0]["body"] or b"{}").decode())
    jql = payload.get("jql", "")
    # Canonical form embedded in the JQL string
    assert '"2026-05-02 11:44"' in jql, jql
    # The broken ISO+offset form must NOT appear
    assert "+08:00" not in jql, jql


# --- (g) ADF strong-mark prefix in @-mention path -----------------------


def test_post_comment_with_mention_uses_adf_strong_prefix():
    """The mention path used to embed `**[ap] [C]**` as a literal text
    node in the prefix paragraph — Jira UI rendered raw `**` plus broken
    `<span class="error">` around the brackets (#27). Verify the prefix
    paragraph now carries an ADF `strong` mark and contains no `*`."""
    data = _seed_jira_data()
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        _seed_repo_ap(proj, ap="narrative-fin-agent")
        drv = _patched_driver(data, proj)
        queue = [_Response(201, b'{"created":"2026-05-02T00:00:00+08:00"}', {})]
        calls: list[dict] = []
        _attach_mock(drv, queue, calls)

        from drivers.base import CommentKind
        drv.post_comment(
            "AGENT-1", "hello",
            CommentKind.COMMENT,
            mention_account_id="kirin-account-id",
            mention_display="Kirin Chen",
        )
        sent = json.loads(calls[0]["body"])
        adf = sent["body"]
        paras = adf["content"]
        # Prefix paragraph: bold, no markdown asterisks
        prefix_para = paras[0]
        assert prefix_para["type"] == "paragraph"
        prefix_node = prefix_para["content"][0]
        assert prefix_node["type"] == "text"
        assert prefix_node["text"] == "[narrative-fin-agent] [C]"
        assert "*" not in prefix_node["text"]
        assert {"type": "strong"} in prefix_node["marks"]
        # Mention paragraph: starts with the @-mention node
        mention_para = paras[1]
        first = mention_para["content"][0]
        assert first["type"] == "mention"
        assert first["attrs"]["id"] == "kirin-account-id"


# --- driver -------------------------------------------------------------


def main() -> int:
    cases = [
        ("transition_matches_by_action_name_when_status_localized",
         test_transition_matches_by_action_name_when_status_localized),
        ("transition_still_matches_by_destination_status_name",
         test_transition_still_matches_by_destination_status_name),
        ("detect_reconcile_skips_when_no_transitions",
         test_detect_reconcile_skips_when_no_transitions),
        ("jql_quote_ts_normalizes_iso_with_offset",
         test_jql_quote_ts_normalizes_iso_with_offset),
        ("jql_quote_ts_handles_canonical_short_forms",
         test_jql_quote_ts_handles_canonical_short_forms),
        ("jql_quote_ts_rejects_quote_injection",
         test_jql_quote_ts_rejects_quote_injection),
        ("find_mentions_sends_normalized_timestamp_in_jql",
         test_find_mentions_sends_normalized_timestamp_in_jql),
        ("post_comment_with_mention_uses_adf_strong_prefix",
         test_post_comment_with_mention_uses_adf_strong_prefix),
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
        print(f"phase19: {failed} failure(s)", file=sys.stderr)
        return 1
    print("phase19: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
