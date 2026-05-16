#!/usr/bin/env python3
"""Phase 30 regression checks for kanban v0.3.25 — board-config helpers.

Background (PR 1 of the showjira-code → board-config replacement):

The canonical shared kanban config (transitions DSL, AP field id,
conventions) is moving off per-receiver paste-flows and onto the Jira
project itself, stored under property key `kanban-config`. This phase
covers the helper layer:

- `lib/board_config.py` primitives (push / pull / cache TTL)
- `cmd_push_board_config` (kanban.json → Jira)
- `cmd_pull_board_config` (Jira → kanban.json + cachedAt)
- `cmd_read_board_config` (read-only snapshot)

Slash commands and driver-level passive sync land in PR 2; the old
showjira-code/import-jira-code commands stay (no behavior change in
this PR — additive only).

Cases:
  (a) _bc.push happy path — calls set_project_property with the right
      property key + payload.
  (b) _bc.push translates 403 into a permission-denied
      BoardConfigError mentioning "project-admin role".
  (c) _bc.pull happy path — returns the unwrapped `value` dict from
      the project-property envelope.
  (d) _bc.pull translates 404 into BoardConfigError with .not_found
      attribute set, distinct message mentioning push-board-config.
  (e) _bc.cache_age_hours returns None when no cachedAt exists; a
      sensible float when one does.
  (f) _bc.is_cache_stale returns True when no cache, True past TTL,
      False within TTL.
  (g) _bc.mark_synced writes ISO timestamp to
      .claude/kanban-agent.json#boardConfigCachedAt without clobbering
      other fields.
  (h) cmd_push_board_config strips per-machine fields (agentAccountId,
      ap.registered) from the pushed payload.
  (i) cmd_pull_board_config preserves per-machine fields
      (agentAccountId, ap.registered) on the local kanban.json after
      the overwrite.
  (j) cmd_read_board_config emits the config without touching local
      kanban.json or .claude/kanban-agent.json.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timedelta, timezone

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"
sys.path.insert(0, str(REPO / "plugins" / "kanban"))

from lib import board_config as _bc  # noqa: E402
from lib.jira_client import JiraClient, JiraError, _Response  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "jira_setup_mod", str(PLUGIN / "scripts" / "jira_setup.py")
)
_jira_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_jira_setup)  # type: ignore[union-attr]


def _capture(fn, args):
    from io import StringIO
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = StringIO()
    sys.stderr = StringIO()
    try:
        try:
            rc = fn(args)
        except SystemExit as e:
            rc = e.code
        out = sys.stdout.getvalue()
        err = sys.stderr.getvalue()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out, err


def _mock_client(queue, calls):
    def t(method, url, headers, body):
        calls.append({"method": method, "url": url, "body": body})
        if not queue:
            raise AssertionError(f"queue empty for {method} {url}")
        return queue.pop(0)
    return JiraClient("https://x", "a@b", "tok", transport=t,
                      sleep=lambda _: None)


def _seed_jira_kanban(td: pathlib.Path, *,
                      project_key="AGENT", with_ap_registered=True,
                      with_agent_account=True) -> pathlib.Path:
    cfg = {
        "boardUrl": f"https://x.atlassian.net/jira/projects/{project_key}/boards/1",
        "boardId": 1,
        "projectKey": project_key,
        "transitions": {
            "TODO": {"status": "To Do"},
            "DOING": {"status": "In Progress"},
            "APPROVED": {"status": "Done"},
        },
        "ap": {"fieldId": "customfield_10042",
               "fieldName": "Claude Agent"},
        "conventions": {"notes": [], "blockedRequiresLink": False},
    }
    if with_ap_registered:
        cfg["ap"]["registered"] = ["agent-fin", "narrative-fin-agent"]
    if with_agent_account:
        cfg["agentAccountId"] = "5e-bot"
    p = td / "kanban.json"
    p.write_text(json.dumps({
        "version": "0.2",
        "backend": {"driver": "jira", "jira": cfg},
        "meta": {"priorities": ["P0"], "categories": [],
                 "columns": ["TODO", "DOING", "BLOCKED", "REVIEW",
                             "APPROVED", "CANCELLED"],
                 "created_at": "x", "updated_at": "x"},
        "tasks": [],
    }))
    return p


# --- (a) (b) push primitive ---------------------------------------------


def test_push_happy_path_calls_set_project_property():
    # push() reads the remote _meta first (404 → first push), then PUTs.
    queue = [
        _Response(404, b'{"errorMessages":["not found"]}', {}),
        _Response(204, b"", {}),
    ]
    calls: list[dict] = []
    client = _mock_client(queue, calls)

    config = {
        "projectKey": "AGENT",
        "boardId": 1,
        "transitions": {"DOING": {"status": "In Progress"}},
    }
    _bc.push(client, "AGENT", config)

    assert len(calls) == 2
    assert calls[0]["method"] == "GET"
    c = calls[1]
    assert c["method"] == "PUT"
    assert "/rest/api/3/project/AGENT/properties/kanban-config" in c["url"]
    body = json.loads((c["body"] or b"").decode())
    # Caller's config is preserved verbatim, plus push() attaches _meta.
    meta = body.pop("_meta")
    assert body == config
    assert meta["version"] == 1
    assert meta["hash"].startswith("sha256:") and len(meta["hash"]) == 7 + 64
    assert meta["pushedAt"]
    # No pushedByAccountId when not provided.
    assert "pushedByAccountId" not in meta


def test_push_403_raises_permission_denied_with_admin_hint():
    # GET (read remote meta) -> 404, then PUT -> 403.
    queue = [
        _Response(404, b'{"errorMessages":["not found"]}', {}),
        _Response(403, b'{"errorMessages":["nope"]}', {}),
    ]
    calls: list[dict] = []
    client = _mock_client(queue, calls)

    try:
        _bc.push(client, "AGENT", {"transitions": {}})
    except _bc.BoardConfigError as e:
        msg = str(e)
        assert "permission denied" in msg.lower()
        assert "project-admin role" in msg
        return
    raise AssertionError("expected BoardConfigError")


# --- (c) (d) pull primitive ---------------------------------------------


def test_pull_happy_path_returns_unwrapped_value():
    envelope = {
        "key": "kanban-config",
        "value": {
            "projectKey": "AGENT",
            "transitions": {"DOING": {"status": "In Progress"}},
        },
    }
    queue = [_Response(200, json.dumps(envelope).encode(), {})]
    calls: list[dict] = []
    client = _mock_client(queue, calls)

    out = _bc.pull(client, "AGENT")
    assert out == envelope["value"]
    assert calls[0]["method"] == "GET"
    assert "/rest/api/3/project/AGENT/properties/kanban-config" in calls[0]["url"]


def test_pull_404_raises_not_found_distinct_error():
    queue = [_Response(404, b'{"errorMessages":["not found"]}', {})]
    calls: list[dict] = []
    client = _mock_client(queue, calls)

    try:
        _bc.pull(client, "AGENT")
    except _bc.BoardConfigError as e:
        assert getattr(e, "not_found", False) is True
        msg = str(e)
        assert "no board config set yet" in msg
        assert "push-board-config" in msg
        return
    raise AssertionError("expected BoardConfigError")


# --- (e) (f) (g) cache TTL helpers --------------------------------------


def test_cache_age_returns_none_when_unset():
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        # No .claude/kanban-agent.json yet
        assert _bc.cache_age_hours(proj) is None


def test_cache_age_returns_float_when_set():
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        # Mark synced 3h ago
        three_h_ago = datetime.now(timezone.utc) - timedelta(hours=3)
        _bc.mark_synced(proj, three_h_ago)
        age = _bc.cache_age_hours(proj)
        assert age is not None
        # Allow tolerance for clock skew between mark and read
        assert 2.9 <= age <= 3.1, age


def test_is_cache_stale_logic():
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        # No cache at all → stale
        assert _bc.is_cache_stale(proj) is True

        # Recent cache (1h ago) with default TTL=8 → fresh
        one_h_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        _bc.mark_synced(proj, one_h_ago)
        assert _bc.is_cache_stale(proj) is False

        # Old cache (10h ago) with default TTL=8 → stale
        ten_h_ago = datetime.now(timezone.utc) - timedelta(hours=10)
        _bc.mark_synced(proj, ten_h_ago)
        assert _bc.is_cache_stale(proj) is True

        # Custom TTL: 1h cache + ttl_hours=0.5 → stale
        _bc.mark_synced(proj, one_h_ago)
        assert _bc.is_cache_stale(proj, ttl_hours=0.5) is True


def test_mark_synced_preserves_other_fields():
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        agent_path = proj / ".claude" / "kanban-agent.json"
        agent_path.parent.mkdir()
        agent_path.write_text(json.dumps({
            "ap": "agent-fin",
            "lastMentionSeenAt": "2026-05-01T00:00:00+00:00",
        }))

        _bc.mark_synced(proj)

        data = json.loads(agent_path.read_text())
        assert data["ap"] == "agent-fin"
        assert data["lastMentionSeenAt"] == "2026-05-01T00:00:00+00:00"
        assert "boardConfigCachedAt" in data
        # Parses as ISO
        from datetime import datetime
        datetime.fromisoformat(data["boardConfigCachedAt"])


# --- (h) push command strips per-machine fields -------------------------


def _patch_client_from_env(client):
    orig = _jira_setup._client_from_env
    _jira_setup._client_from_env = lambda: client
    return orig


def _restore_client_from_env(orig):
    _jira_setup._client_from_env = orig


def test_cmd_push_strips_per_machine_fields():
    """`agentAccountId` and `ap.registered` are per-machine state and
    must not appear in the pushed payload — two machines pushing
    shouldn't fight over them."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td, with_ap_registered=True,
                               with_agent_account=True)
        # push() does a GET first to read remote _meta (404 ⇒ first
        # push, no fence), then PUTs the payload.
        queue = [
            _Response(404, b'{"errorMessages":["not found"]}', {}),
            _Response(204, b"", {}),
        ]
        calls: list[dict] = []
        client = _mock_client(queue, calls)
        orig = _patch_client_from_env(client)
        try:
            class A:
                kanban_path = str(kp)
                if_match = None
                force = False
            rc, out, err = _capture(_jira_setup.cmd_push_board_config, A())
        finally:
            _restore_client_from_env(orig)

        assert rc == 0, (out, err)
        put_call = next(c for c in calls if c["method"] == "PUT")
        body = json.loads((put_call["body"] or b"").decode())
        # Per-machine fields stripped
        assert "agentAccountId" not in body
        assert "registered" not in (body.get("ap") or {})
        # Shared fields present
        assert body["projectKey"] == "AGENT"
        assert body["transitions"]
        assert body["ap"]["fieldId"] == "customfield_10042"
        # _meta block attached
        assert body["_meta"]["version"] == 1
        # pushedByAccountId carries the seeded agentAccountId (5e-bot).
        assert body["_meta"]["pushedByAccountId"] == "5e-bot"


# --- (i) pull command preserves per-machine fields ----------------------


def test_cmd_pull_preserves_per_machine_fields():
    """After a pull, the local kanban.json's `agentAccountId` and
    `ap.registered` must survive even though the Jira-side payload
    doesn't carry them."""
    remote_payload = {
        "key": "kanban-config",
        "value": {
            "projectKey": "AGENT",
            "boardId": 1,
            "boardUrl": "https://x.atlassian.net/jira/projects/AGENT/boards/1",
            "transitions": {
                "TODO": {"status": "To Do"},
                "DOING": {"status": "In Progress"},
                "APPROVED": {"status": "Done"},
                "REVIEW": {"status": "REVIEW"},  # extra: pulled adds new entry
            },
            "ap": {
                "fieldId": "customfield_10042",
                "fieldName": "Claude Agent",
            },
            "conventions": {"notes": ["new team rule"], "blockedRequiresLink": True},
        },
    }
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td, with_ap_registered=True,
                               with_agent_account=True)
        queue = [_Response(200, json.dumps(remote_payload).encode(), {})]
        calls: list[dict] = []
        client = _mock_client(queue, calls)
        orig = _patch_client_from_env(client)
        try:
            class A:
                kanban_path = str(kp)
                project_key = None
            rc, out, err = _capture(_jira_setup.cmd_pull_board_config, A())
        finally:
            _restore_client_from_env(orig)

        assert rc == 0, (out, err)
        # On-disk kanban.json: shared fields overwritten, per-machine kept
        on_disk = json.loads(kp.read_text())
        cfg = on_disk["backend"]["jira"]
        # New transition pulled in
        assert "REVIEW" in cfg["transitions"]
        # Conventions overwrite worked
        assert cfg["conventions"]["blockedRequiresLink"] is True
        # Per-machine preserved
        assert cfg["agentAccountId"] == "5e-bot"
        assert cfg["ap"]["registered"] == ["agent-fin", "narrative-fin-agent"]
        assert cfg["ap"]["fieldId"] == "customfield_10042"

        # cachedAt was recorded
        agent_data = json.loads(
            (td / ".claude" / "kanban-agent.json").read_text()
        )
        assert "boardConfigCachedAt" in agent_data


# --- (j) read command doesn't touch local state -------------------------


def test_cmd_read_does_not_touch_local():
    remote_payload = {
        "key": "kanban-config",
        "value": {"projectKey": "AGENT", "transitions": {"DOING": {"status": "In Progress"}}},
    }
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td)
        kp_before = kp.read_bytes()
        agent_path = td / ".claude" / "kanban-agent.json"
        agent_before = agent_path.read_bytes() if agent_path.exists() else None

        queue = [_Response(200, json.dumps(remote_payload).encode(), {})]
        calls: list[dict] = []
        client = _mock_client(queue, calls)
        orig = _patch_client_from_env(client)
        try:
            class A:
                kanban_path = str(kp)
                project_key = None
            rc, out, err = _capture(_jira_setup.cmd_read_board_config, A())
        finally:
            _restore_client_from_env(orig)

        assert rc == 0, (out, err)
        j = json.loads(out)
        assert j["ok"] is True
        assert j["config"] == remote_payload["value"]

        # Local files untouched
        assert kp.read_bytes() == kp_before
        if agent_before is not None:
            assert agent_path.read_bytes() == agent_before
        else:
            assert not agent_path.exists()


def main() -> int:
    cases = [
        ("push_happy_path_calls_set_project_property",
         test_push_happy_path_calls_set_project_property),
        ("push_403_raises_permission_denied_with_admin_hint",
         test_push_403_raises_permission_denied_with_admin_hint),
        ("pull_happy_path_returns_unwrapped_value",
         test_pull_happy_path_returns_unwrapped_value),
        ("pull_404_raises_not_found_distinct_error",
         test_pull_404_raises_not_found_distinct_error),
        ("cache_age_returns_none_when_unset",
         test_cache_age_returns_none_when_unset),
        ("cache_age_returns_float_when_set",
         test_cache_age_returns_float_when_set),
        ("is_cache_stale_logic", test_is_cache_stale_logic),
        ("mark_synced_preserves_other_fields",
         test_mark_synced_preserves_other_fields),
        ("cmd_push_strips_per_machine_fields",
         test_cmd_push_strips_per_machine_fields),
        ("cmd_pull_preserves_per_machine_fields",
         test_cmd_pull_preserves_per_machine_fields),
        ("cmd_read_does_not_touch_local",
         test_cmd_read_does_not_touch_local),
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
        print(f"phase30: {failed} failure(s)", file=sys.stderr)
        return 1
    print("phase30: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
