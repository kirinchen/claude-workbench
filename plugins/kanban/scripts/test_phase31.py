#!/usr/bin/env python3
"""Phase 31 regression checks for kanban v0.3.26 — board-config slash
commands + passive sync (PR 2 of 3).

Builds on PR 1 (phase 30, helper layer). PR 2 wires:
- `_maybe_passive_sync_board_config` into `cmd_sync_summary` so
  SessionStart-triggered `/kanban:sync` opportunistically refreshes
  the cache when stale (≥ 8h since last pull)
- `cmd_read_board_config_cache` for `/kanban:whoami` to render a
  cache-age row without making any Jira call
- Three slash commands: `push-board-config`, `pull-board-config`,
  `show-board-config` (specs only — already exercised at the helper
  layer in phase 30)

Cases:
  (a) `_maybe_passive_sync_board_config` no-ops on local-mode
      kanban.json (passive sync is jira-only)
  (b) Fresh cache (< 8h) — no Jira API call, no warnings, no kanban.json
      mutation
  (c) Stale cache + successful pull — overwrites local backend.jira
      with the pulled config; preserves per-machine fields;
      records cachedAt
  (d) Stale cache + 404 (no config on Jira yet) — silent skip (no
      warning to stderr; expected condition for fresh boards)
  (e) Stale cache + 403 (permission denied) — warning to stderr; no
      mutation; caller continues with stale cache
  (f) Stale cache + missing credentials — silent skip (whoami's token
      row already surfaces this; passive sync stays out of the way)
  (g) `cmd_read_board_config_cache` — never-synced state
  (h) `cmd_read_board_config_cache` — synced state with fresh cache
  (i) `cmd_read_board_config_cache` — synced state past TTL → stale=true
  (j) `cmd_sync_summary` end-to-end with stale cache: pulls fresh
      config + then renders summary using the new transitions
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
from datetime import datetime, timedelta, timezone

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"
sys.path.insert(0, str(REPO / "plugins" / "kanban"))

from lib import board_config as _bc  # noqa: E402
from lib.jira_client import JiraClient, _Response  # noqa: E402

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


def _seed_jira_kanban(td: pathlib.Path, *, project_key="AGENT") -> pathlib.Path:
    p = td / "kanban.json"
    p.write_text(json.dumps({
        "version": "0.2",
        "backend": {"driver": "jira", "jira": {
            "boardUrl": f"https://x/jira/projects/{project_key}/boards/1",
            "boardId": 1, "projectKey": project_key,
            "agentAccountId": "5e-bot",
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
                 "columns": ["TODO", "DOING", "BLOCKED", "REVIEW",
                             "APPROVED", "CANCELLED"],
                 "created_at": "x", "updated_at": "x"},
        "tasks": [],
    }))
    return p


def _seed_local_kanban(td: pathlib.Path) -> pathlib.Path:
    p = td / "kanban.json"
    p.write_text(json.dumps({
        "version": "0.2",
        "backend": {"driver": "local"},
        "meta": {"priorities": ["P0"], "categories": [],
                 "columns": ["TODO", "DOING", "APPROVED", "BLOCKED"],
                 "created_at": "x", "updated_at": "x"},
        "tasks": [],
    }))
    return p


def _patch_client(client):
    orig_full = _jira_setup._client_from_env
    orig_opt = _jira_setup._client_from_env_or_none
    _jira_setup._client_from_env = lambda: client
    _jira_setup._client_from_env_or_none = lambda: client
    return (orig_full, orig_opt)


def _restore_client(originals):
    _jira_setup._client_from_env, _jira_setup._client_from_env_or_none = originals


# --- (a) local-mode no-op -----------------------------------------------


def test_passive_sync_local_mode_noop():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_local_kanban(td)
        original = kp.read_bytes()

        from lib import kanban_io
        data = kanban_io.load(kp)
        out = _jira_setup._maybe_passive_sync_board_config(kp, data)
        assert out is data  # same dict, no rewrite
        # Should NOT have created .claude/kanban-agent.json
        assert not (td / ".claude" / "kanban-agent.json").exists()
        # File untouched
        assert kp.read_bytes() == original


# --- (b) fresh cache no-op ----------------------------------------------


def test_passive_sync_fresh_cache_noop():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td)
        # Mark synced 1h ago — fresh
        _bc.mark_synced(td, datetime.now(timezone.utc) - timedelta(hours=1))
        original = kp.read_bytes()

        # No client should be needed because is_cache_stale returns False
        # before reaching _client_from_env_or_none. Verify by patching
        # the client to one that errors if called.
        called = []
        class _ExplodingClient:
            def get_project_property(self, *a, **kw):
                called.append("yes")
                raise AssertionError("should not have been called")

        orig = _patch_client(_ExplodingClient())
        try:
            from lib import kanban_io
            data = kanban_io.load(kp)
            _jira_setup._maybe_passive_sync_board_config(kp, data)
        finally:
            _restore_client(orig)

        assert called == []
        assert kp.read_bytes() == original


# --- (c) stale cache + successful pull ----------------------------------


def test_passive_sync_stale_pulls_and_overwrites():
    remote = {
        "key": "kanban-config",
        "value": {
            "boardId": 1, "projectKey": "AGENT",
            "boardUrl": "https://x/jira/projects/AGENT/boards/1",
            "transitions": {
                "TODO": {"status": "Backlog"},  # <- changed!
                "DOING": {"status": "In Progress"},
                "APPROVED": {"status": "Done"},
                "REVIEW": {"status": "REVIEW"},  # <- new
            },
            "ap": {"fieldId": "customfield_10042",
                   "fieldName": "Claude Agent"},
            "conventions": {"notes": ["new rule"], "blockedRequiresLink": True},
        },
    }
    queue = [_Response(200, json.dumps(remote).encode(), {})]
    calls: list[dict] = []
    client = _mock_client(queue, calls)

    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td)
        # Mark synced 10h ago — stale
        _bc.mark_synced(td, datetime.now(timezone.utc) - timedelta(hours=10))

        orig = _patch_client(client)
        try:
            from lib import kanban_io
            data = kanban_io.load(kp)
            out = _jira_setup._maybe_passive_sync_board_config(kp, data)
        finally:
            _restore_client(orig)

        # New transitions reflected in data
        cfg = (out.get("backend") or {}).get("jira") or {}
        assert cfg["transitions"]["TODO"]["status"] == "Backlog"
        assert "REVIEW" in cfg["transitions"]
        # Per-machine preserved
        assert cfg["agentAccountId"] == "5e-bot"
        assert cfg["ap"]["registered"] == ["agent-fin"]
        # On-disk
        on_disk = json.loads(kp.read_text())
        assert on_disk["backend"]["jira"]["transitions"]["TODO"]["status"] == "Backlog"
        # cachedAt updated
        agent_data = json.loads((td / ".claude" / "kanban-agent.json").read_text())
        assert "boardConfigCachedAt" in agent_data
        # Recent (within last minute)
        recorded = datetime.fromisoformat(agent_data["boardConfigCachedAt"])
        if recorded.tzinfo is None:
            recorded = recorded.replace(tzinfo=timezone.utc)
        assert (datetime.now(timezone.utc) - recorded).total_seconds() < 60


# --- (d) stale + 404 silent skip ---------------------------------------


def test_passive_sync_404_silent_skip():
    """No `kanban-config` property on Jira yet — that's the common
    state for fresh projects. Don't nag the user."""
    queue = [_Response(404, b'{"errorMessages":["nope"]}', {})]
    calls: list[dict] = []
    client = _mock_client(queue, calls)

    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td)
        _bc.mark_synced(td, datetime.now(timezone.utc) - timedelta(hours=10))
        original = kp.read_bytes()

        orig = _patch_client(client)
        try:
            from io import StringIO
            old_err = sys.stderr
            sys.stderr = StringIO()
            try:
                from lib import kanban_io
                data = kanban_io.load(kp)
                _jira_setup._maybe_passive_sync_board_config(kp, data)
                err = sys.stderr.getvalue()
            finally:
                sys.stderr = old_err
        finally:
            _restore_client(orig)

        # 404 is silent — no warning
        assert err == "", err
        # No mutation
        assert kp.read_bytes() == original


# --- (e) stale + 403 → warn but continue --------------------------------


def test_passive_sync_403_warns_continues():
    queue = [_Response(403, b'{"errorMessages":["denied"]}', {})]
    calls: list[dict] = []
    client = _mock_client(queue, calls)

    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td)
        _bc.mark_synced(td, datetime.now(timezone.utc) - timedelta(hours=10))
        original = kp.read_bytes()

        orig = _patch_client(client)
        try:
            from io import StringIO
            old_err = sys.stderr
            sys.stderr = StringIO()
            try:
                from lib import kanban_io
                data = kanban_io.load(kp)
                _jira_setup._maybe_passive_sync_board_config(kp, data)
                err = sys.stderr.getvalue()
            finally:
                sys.stderr = old_err
        finally:
            _restore_client(orig)

        # Warning emitted
        assert "passive board-config sync failed" in err
        assert "permission denied" in err.lower()
        # No mutation
        assert kp.read_bytes() == original


# --- (f) stale + no creds → silent ---------------------------------------


def test_passive_sync_no_credentials_silent():
    """Whoami's token row already surfaces missing creds; passive sync
    stays out of the way."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td)
        _bc.mark_synced(td, datetime.now(timezone.utc) - timedelta(hours=10))
        original = kp.read_bytes()

        # Patch client_from_env_or_none → None (the normal "no creds" path)
        orig_opt = _jira_setup._client_from_env_or_none
        _jira_setup._client_from_env_or_none = lambda: None
        try:
            from io import StringIO
            old_err = sys.stderr
            sys.stderr = StringIO()
            try:
                from lib import kanban_io
                data = kanban_io.load(kp)
                _jira_setup._maybe_passive_sync_board_config(kp, data)
                err = sys.stderr.getvalue()
            finally:
                sys.stderr = old_err
        finally:
            _jira_setup._client_from_env_or_none = orig_opt

        assert err == "", err  # no nag
        assert kp.read_bytes() == original


# --- (g) (h) (i) read-board-config-cache states -------------------------


def test_read_cache_never_synced():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td)

        class A: kanban_path = str(kp)
        rc, out, err = _capture(_jira_setup.cmd_read_board_config_cache, A())
        assert rc == 0, (out, err)
        j = json.loads(out)
        assert j["ok"] is True
        assert j["projectKey"] == "AGENT"
        assert j["propertyKey"] == "kanban-config"
        assert j["cachedAt"] is None
        assert j["cacheAgeHours"] is None
        assert j["stale"] is True
        assert j["ttlHours"] == 8


def test_read_cache_fresh():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td)
        _bc.mark_synced(td, datetime.now(timezone.utc) - timedelta(hours=2))

        class A: kanban_path = str(kp)
        rc, out, err = _capture(_jira_setup.cmd_read_board_config_cache, A())
        assert rc == 0, (out, err)
        j = json.loads(out)
        assert j["ok"] is True
        assert j["cachedAt"] is not None
        assert 1.9 <= j["cacheAgeHours"] <= 2.1
        assert j["stale"] is False


def test_read_cache_stale():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td)
        _bc.mark_synced(td, datetime.now(timezone.utc) - timedelta(hours=12))

        class A: kanban_path = str(kp)
        rc, out, err = _capture(_jira_setup.cmd_read_board_config_cache, A())
        assert rc == 0, (out, err)
        j = json.loads(out)
        assert j["stale"] is True
        assert j["cacheAgeHours"] >= 11.9


# --- (j) cmd_sync_summary integration with passive sync -----------------


def test_sync_summary_pulls_when_stale_then_renders():
    """End-to-end: cmd_sync_summary on a stale kanban.json triggers
    a board-config pull; subsequent driver construction uses the
    fresh transitions; the summary still renders normally."""
    remote = {
        "key": "kanban-config",
        "value": {
            "boardId": 1, "projectKey": "AGENT",
            "boardUrl": "https://x/jira/projects/AGENT/boards/1",
            "transitions": {
                "TODO": {"status": "Backlog"},
                "DOING": {"status": "In Progress"},
                "BLOCKED": {"status": "In Progress",
                            "addLabels": ["kanban:blocked"]},
                "REVIEW": {"status": "REVIEW"},
                "APPROVED": {"status": "Done"},
            },
            "ap": {"fieldId": "customfield_10042",
                   "fieldName": "Claude Agent"},
        },
    }
    queue = [
        # (1) passive-sync pull
        _Response(200, json.dumps(remote).encode(), {}),
        # (2..5) driver.list_tasks for each open column
        _Response(200, json.dumps({"issues": []}).encode(), {}),
        _Response(200, json.dumps({"issues": []}).encode(), {}),
        _Response(200, json.dumps({"issues": []}).encode(), {}),
        _Response(200, json.dumps({"issues": []}).encode(), {}),
        # (6) reconcile query 1 (my-AP unmapped)
        _Response(200, json.dumps({"issues": []}).encode(), {}),
        # (7) reconcile query 2 (missing-AP)
        _Response(200, json.dumps({"issues": []}).encode(), {}),
    ]
    calls: list[dict] = []
    client = _mock_client(queue, calls)

    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td)
        # Seed repo AP so list_tasks adds the AP filter
        (td / ".claude").mkdir()
        (td / ".claude" / "kanban-agent.json").write_text(
            json.dumps({"ap": "agent-fin"})
        )
        # Stale cache → triggers passive sync
        _bc.mark_synced(td, datetime.now(timezone.utc) - timedelta(hours=10))

        orig = _patch_client(client)
        try:
            class A: kanban_path = str(kp)
            rc, out, err = _capture(_jira_setup.cmd_sync_summary, A())
        finally:
            _restore_client(orig)

        assert rc == 0, (out, err)
        # The first call must be the board-config property GET
        assert "/properties/kanban-config" in calls[0]["url"]
        # Pulled config persisted
        on_disk = json.loads(kp.read_text())
        assert on_disk["backend"]["jira"]["transitions"]["TODO"]["status"] == "Backlog"


def main() -> int:
    cases = [
        ("passive_sync_local_mode_noop",
         test_passive_sync_local_mode_noop),
        ("passive_sync_fresh_cache_noop",
         test_passive_sync_fresh_cache_noop),
        ("passive_sync_stale_pulls_and_overwrites",
         test_passive_sync_stale_pulls_and_overwrites),
        ("passive_sync_404_silent_skip",
         test_passive_sync_404_silent_skip),
        ("passive_sync_403_warns_continues",
         test_passive_sync_403_warns_continues),
        ("passive_sync_no_credentials_silent",
         test_passive_sync_no_credentials_silent),
        ("read_cache_never_synced", test_read_cache_never_synced),
        ("read_cache_fresh", test_read_cache_fresh),
        ("read_cache_stale", test_read_cache_stale),
        ("sync_summary_pulls_when_stale_then_renders",
         test_sync_summary_pulls_when_stale_then_renders),
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
        print(f"phase31: {failed} failure(s)", file=sys.stderr)
        return 1
    print("phase31: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
