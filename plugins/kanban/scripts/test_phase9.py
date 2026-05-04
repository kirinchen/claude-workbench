#!/usr/bin/env python3
"""Phase 9 regression checks for kanban v0.3.2 — AP-field screen association.

Closes issue #6: a custom field created via `create-ap-field` was never
attached to any Jira screen, leaving the plugin in a broken-by-design
state where `/kanban:next` returned nothing because no card could carry
an AP value.

Cases:
  (a) jira_client: list_screens / list_screen_tabs / list_screen_tab_fields
       / add_field_to_screen_tab — endpoints + payloads
  (b) _candidate_screens — picks project-named screens + always-include
       default screen id=1; deduped
  (c) _associate_field_with_screens — happy path: attaches field to all
       candidate screens' first tab, returns clean attached list
  (d) _associate_field_with_screens — idempotent: when field is already on
       a screen, reports alreadyPresent without making the POST
  (e) _associate_field_with_screens — 403 on add_field is captured under
       `denied`, not `errors`; flow continues to the next screen
  (f) cmd_create_ap_field with --project triggers screen association and
       returns screens summary
  (g) cmd_create_ap_field without --project skips association
       (back-compat for explicit callers)
  (h) cmd_associate_ap_field_screens reads kanban.json for projectKey +
       fieldId; exits ok with summary
  (i) cmd_verify_ap_field_screens returns present[]/missing[] correctly
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"
sys.path.insert(0, str(REPO / "plugins" / "kanban"))

from lib.jira_client import JiraClient, _Response, JiraError  # noqa: E402


# Load jira_setup as a module so we can call its internal helpers directly.
_spec = importlib.util.spec_from_file_location(
    "jira_setup_mod", str(PLUGIN / "scripts" / "jira_setup.py")
)
_jira_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_jira_setup)  # type: ignore[union-attr]


def _mock_transport(queue, calls):
    def t(method, url, headers, body):
        calls.append({"method": method, "url": url, "body": body})
        if not queue:
            raise AssertionError(f"queue empty for {method} {url}")
        return queue.pop(0)
    return t


def _mk_client(queue, calls):
    return JiraClient(
        "https://x.atlassian.net", "a@b", "tok",
        transport=_mock_transport(queue, calls), sleep=lambda _: None,
    )


# --- jira_client endpoints -----------------------------------------------


def test_list_screens_with_query():
    queue = [_Response(200, b'{"values":[{"id":42,"name":"DMI: Kanban Default Issue Screen"}]}', {})]
    calls = []
    c = _mk_client(queue, calls)
    out = c.list_screens(query="DMI")
    assert out["values"][0]["id"] == 42
    assert "queryString=DMI" in calls[0]["url"]


def test_list_screen_tabs_and_fields():
    queue = [
        _Response(200, b'[{"id":1,"name":"Field Tab"}]', {}),
        _Response(200, b'[{"id":"customfield_10325","name":"Claude Agent"},'
                       b'{"id":"summary","name":"Summary"}]', {}),
    ]
    calls = []
    c = _mk_client(queue, calls)
    tabs = c.list_screen_tabs(42)
    assert tabs[0]["id"] == 1
    fields = c.list_screen_tab_fields(42, 1)
    field_ids = {f["id"] for f in fields}
    assert "customfield_10325" in field_ids
    assert calls[1]["url"].endswith("/screens/42/tabs/1/fields")


def test_add_field_to_screen_tab_payload():
    queue = [_Response(200, b'{"id":"customfield_10325","name":"Claude Agent"}', {})]
    calls = []
    c = _mk_client(queue, calls)
    c.add_field_to_screen_tab(42, 1, "customfield_10325")
    sent = json.loads(calls[0]["body"])
    assert sent == {"fieldId": "customfield_10325"}
    assert calls[0]["method"] == "POST"


# --- _candidate_screens --------------------------------------------------


def test_candidate_screens_includes_default():
    queue = [_Response(200, b'{"values":[{"id":42,"name":"DMI: Kanban Default Issue Screen"}]}', {})]
    calls = []
    c = _mk_client(queue, calls)
    screens = _jira_setup._candidate_screens(c, "DMI")
    ids = sorted(s["id"] for s in screens)
    assert 1 in ids        # default screen always added
    assert 42 in ids       # project-named screen kept
    assert len(set(ids)) == len(ids)  # deduped


def test_candidate_screens_handles_query_failure():
    queue = [_Response(403, b'{"errorMessages":["forbidden"]}', {})]
    calls = []
    c = _mk_client(queue, calls)
    screens = _jira_setup._candidate_screens(c, "DMI")
    # Falls back to just the default screen
    assert [s["id"] for s in screens] == [1]


# --- _associate_field_with_screens --------------------------------------


def _seed_screen_responses(field_id, present_on=()):
    """Build a queue mocking responses for two screens (default=1 + DMI=42).

    `present_on` is an iterable of screen ids where the field is already
    attached — those skip the POST and use list_screen_tab_fields instead.
    """
    queue: list[_Response] = []

    # 1. _candidate_screens calls list_screens(query="DMI")
    queue.append(_Response(
        200, b'{"values":[{"id":42,"name":"DMI: Kanban Default Issue Screen"}]}', {}))

    # 2. _associate iterates screens (id=1, id=42 — depending on ordering)
    # We need to support both orderings since dict iteration order is
    # insertion order. _candidate_screens adds queried screens first then
    # defaults — but `screens.setdefault(1, ...)` runs after, so 1 may
    # come last. The function order is: queried first (42), then default 1.
    for sid in (42, 1):
        # list_screen_tabs
        queue.append(_Response(200, b'[{"id":' + str(sid * 10).encode() + b',"name":"Tab"}]', {}))
        # list_screen_tab_fields (presence check)
        if sid in present_on:
            body = b'[{"id":"' + field_id.encode() + b'"}]'
            queue.append(_Response(200, body, {}))
            # No POST — already present
        else:
            queue.append(_Response(200, b"[]", {}))
            # POST add_field
            queue.append(_Response(200, b'{"id":"' + field_id.encode() + b'"}', {}))
    return queue


def test_associate_happy_path():
    queue = _seed_screen_responses("customfield_10325")
    calls = []
    c = _mk_client(queue, calls)
    out = _jira_setup._associate_field_with_screens(c, "customfield_10325", "DMI")
    assert len(out["attempted"]) == 2
    assert len(out["attached"]) == 2
    assert out["denied"] == []
    assert out["errors"] == []
    # POST was made for both screens (no alreadyPresent shortcut)
    posts = [x for x in calls if x["method"] == "POST"]
    assert len(posts) == 2


def test_associate_idempotent_already_present():
    queue = _seed_screen_responses("customfield_10325", present_on=(1, 42))
    calls = []
    c = _mk_client(queue, calls)
    out = _jira_setup._associate_field_with_screens(c, "customfield_10325", "DMI")
    assert len(out["attached"]) == 2
    assert all(s.get("alreadyPresent") for s in out["attached"])
    # No POSTs — pure read operations
    posts = [x for x in calls if x["method"] == "POST"]
    assert posts == []


def test_associate_403_on_add_is_denied_not_error():
    queue: list[_Response] = []
    queue.append(_Response(200, b'{"values":[{"id":42,"name":"DMI"}]}', {}))
    # screen 42 — list tabs ok, list fields empty, add 403
    queue.append(_Response(200, b'[{"id":420,"name":"Tab"}]', {}))
    queue.append(_Response(200, b"[]", {}))
    queue.append(_Response(403, b'{"errorMessages":["denied"]}', {}))
    # screen 1 — succeed normally
    queue.append(_Response(200, b'[{"id":10,"name":"Tab"}]', {}))
    queue.append(_Response(200, b"[]", {}))
    queue.append(_Response(200, b'{"id":"customfield_10325"}', {}))

    calls = []
    c = _mk_client(queue, calls)
    out = _jira_setup._associate_field_with_screens(c, "customfield_10325", "DMI")
    assert len(out["denied"]) == 1
    assert out["denied"][0]["id"] == 42
    assert len(out["attached"]) == 1
    assert out["attached"][0]["id"] == 1
    assert out["errors"] == []


# --- cmd_create_ap_field --------------------------------------------------


def _patch_client_for_cmd(client_factory):
    """Replace _client_from_env with a factory returning the test client."""
    orig = _jira_setup._client_from_env
    _jira_setup._client_from_env = client_factory
    return orig


def _restore_client(orig):
    _jira_setup._client_from_env = orig


def test_cmd_create_ap_field_with_project_attaches_screens(capsys=None):
    queue = [
        # create_custom_field
        _Response(200, b'{"id":"customfield_10325","name":"Claude Agent"}', {}),
        # _associate flow
        *_seed_screen_responses("customfield_10325"),
    ]
    calls = []
    c = _mk_client(queue, calls)
    orig = _patch_client_for_cmd(lambda: c)
    try:
        from io import StringIO
        old = sys.stdout
        sys.stdout = StringIO()
        try:
            class A: name = "Claude Agent"; project = "DMI"
            rc = _jira_setup.cmd_create_ap_field(A())
            out = sys.stdout.getvalue()
        finally:
            sys.stdout = old
    finally:
        _restore_client(orig)
    assert rc == 0
    j = json.loads(out)
    assert j["ok"] is True
    assert j["fieldId"] == "customfield_10325"
    assert j["screens"]["attached"]
    assert len(j["screens"]["attached"]) == 2


def test_cmd_create_ap_field_without_project_skips_screens():
    queue = [_Response(200, b'{"id":"customfield_10325","name":"Claude Agent"}', {})]
    calls = []
    c = _mk_client(queue, calls)
    orig = _patch_client_for_cmd(lambda: c)
    try:
        from io import StringIO
        old = sys.stdout
        sys.stdout = StringIO()
        try:
            class A: name = "Claude Agent"; project = None
            rc = _jira_setup.cmd_create_ap_field(A())
            out = sys.stdout.getvalue()
        finally:
            sys.stdout = old
    finally:
        _restore_client(orig)
    assert rc == 0
    j = json.loads(out)
    assert j["screens"] is None  # association skipped
    # Only one HTTP call total — the field create
    assert len(calls) == 1


# --- cmd_associate_ap_field_screens + cmd_verify_ap_field_screens -------


def _seed_v03_kanban(td) -> pathlib.Path:
    p = pathlib.Path(td) / "kanban.json"
    p.write_text(json.dumps({
        "version": "0.2",
        "backend": {
            "driver": "jira",
            "jira": {
                "projectKey": "DMI",
                "boardId": 1,
                "boardUrl": "https://x.atlassian.net/jira/software/projects/DMI/boards/1",
                "transitions": {"DOING": {"status": "In Progress"}},
                "ap": {"fieldId": "customfield_10325", "fieldName": "Claude Agent",
                       "registered": []},
            },
        },
        "meta": {
            "priorities": ["P0"], "categories": [],
            "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "APPROVED", "CANCELLED"],
            "created_at": "x", "updated_at": "x",
        },
        "tasks": [],
    }))
    return p


def test_cmd_associate_reads_kanban():
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_v03_kanban(td)
        queue = _seed_screen_responses("customfield_10325")
        calls = []
        c = _mk_client(queue, calls)
        orig = _patch_client_for_cmd(lambda: c)
        try:
            from io import StringIO
            old = sys.stdout
            sys.stdout = StringIO()
            try:
                class A: kanban_path = str(kp)
                rc = _jira_setup.cmd_associate_ap_field_screens(A())
                out = sys.stdout.getvalue()
            finally:
                sys.stdout = old
        finally:
            _restore_client(orig)
        assert rc == 0
        j = json.loads(out)
        assert j["ok"] is True
        assert j["fieldId"] == "customfield_10325"
        assert len(j["screens"]["attached"]) == 2


def test_cmd_verify_reports_present_and_missing():
    """Default screen has the field; project screen does not."""
    with tempfile.TemporaryDirectory() as td:
        kp = _seed_v03_kanban(td)
        queue: list[_Response] = []
        # _candidate_screens query
        queue.append(_Response(200, b'{"values":[{"id":42,"name":"DMI"}]}', {}))
        # iter screens — ordering: queried (42) first, then default (1)
        # screen 42 → tabs → fields (no field present)
        queue.append(_Response(200, b'[{"id":420,"name":"T"}]', {}))
        queue.append(_Response(200, b"[]", {}))
        # screen 1 → tabs → fields (field present)
        queue.append(_Response(200, b'[{"id":10,"name":"T"}]', {}))
        queue.append(_Response(200, b'[{"id":"customfield_10325"}]', {}))

        calls = []
        c = _mk_client(queue, calls)
        orig = _patch_client_for_cmd(lambda: c)
        try:
            from io import StringIO
            old = sys.stdout
            sys.stdout = StringIO()
            try:
                class A: kanban_path = str(kp)
                rc = _jira_setup.cmd_verify_ap_field_screens(A())
                out = sys.stdout.getvalue()
            finally:
                sys.stdout = old
        finally:
            _restore_client(orig)
        assert rc == 0
        j = json.loads(out)
        assert {s["id"] for s in j["present"]} == {1}
        assert {s["id"] for s in j["missing"]} == {42}


def main() -> int:
    cases = [
        ("list_screens_with_query", test_list_screens_with_query),
        ("list_screen_tabs_and_fields", test_list_screen_tabs_and_fields),
        ("add_field_to_screen_tab_payload", test_add_field_to_screen_tab_payload),
        ("candidate_screens_includes_default", test_candidate_screens_includes_default),
        ("candidate_screens_handles_query_failure", test_candidate_screens_handles_query_failure),
        ("associate_happy_path", test_associate_happy_path),
        ("associate_idempotent_already_present", test_associate_idempotent_already_present),
        ("associate_403_on_add_is_denied_not_error", test_associate_403_on_add_is_denied_not_error),
        ("cmd_create_ap_field_with_project_attaches_screens",
         test_cmd_create_ap_field_with_project_attaches_screens),
        ("cmd_create_ap_field_without_project_skips_screens",
         test_cmd_create_ap_field_without_project_skips_screens),
        ("cmd_associate_reads_kanban", test_cmd_associate_reads_kanban),
        ("cmd_verify_reports_present_and_missing", test_cmd_verify_reports_present_and_missing),
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
    print("phase9: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
