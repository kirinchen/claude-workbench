#!/usr/bin/env python3
"""Phase 34 regression checks for kanban v0.3.29 — versioned board
config (#57).

PR adds `_meta` (version, content hash, pushedAt, pushedByAccountId)
to every push of the `kanban-config` Jira project property, and uses
the hash as an optimistic-concurrency fence (`push --if-match`). Pull
captures `_meta` into the local cache so subsequent pushes can
auto-fill `--if-match` without manual book-keeping.

Cases:
  (a) `canonical_hash` is order- and whitespace-stable: two configs
      that differ only in key order produce the same hash; the hash
      excludes `_meta`.
  (b) First push (remote 404) initializes `_meta.version = 1` and
      attaches a hash + pushedAt; `pushedByAccountId` carries
      account_id when provided.
  (c) Second push (remote has v1) bumps to `_meta.version = 2`.
  (d) Push with `if_match=<wrong>` is refused with
      `if_match_mismatch=True` and `remote_meta` populated; no PUT
      goes through.
  (e) Push with `if_match=<wrong>` and `force=True` clobbers anyway.
  (f) Push with no `_meta` cache on remote AND `if_match=None`
      proceeds without a fence (first push).
  (g) `cmd_push_board_config` auto-fills `--if-match` from local
      cached `_meta.hash`; a mismatch with remote is reported with
      `ifMatchMismatch=True` in the JSON output and a non-zero rc.
  (h) `cmd_push_board_config` writes the just-pushed `_meta` back
      into local `kanban.json#backend.jira._meta` so the *next* push
      on this machine carries that hash forward.
  (i) `cmd_pull_board_config` captures remote `_meta` into local
      `backend.jira._meta` verbatim.
  (j) `cmd_read_board_config_cache` reports `meta`, `localHash`, and
      `localMatchesMeta=True` when the local config hasn't been
      edited since the last pull.
  (k) `cmd_read_board_config` with --kanban-path emits a `diff` block
      whose `state` correctly identifies in-sync / remote-ahead /
      local-edits / diverged.
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


def _patch_client_from_env(client):
    orig = _jira_setup._client_from_env
    _jira_setup._client_from_env = lambda: client
    return orig


def _restore_client_from_env(orig):
    _jira_setup._client_from_env = orig


def _seed_jira_kanban(td: pathlib.Path, *, meta: dict | None = None,
                      transitions: dict | None = None) -> pathlib.Path:
    cfg = {
        "boardUrl": "https://x.atlassian.net/jira/projects/AGENT/boards/1",
        "boardId": 1,
        "projectKey": "AGENT",
        "transitions": transitions or {
            "TODO": {"status": "To Do"},
            "DOING": {"status": "In Progress"},
            "APPROVED": {"status": "Done"},
        },
        "ap": {"fieldId": "customfield_10042",
               "fieldName": "Claude Agent",
               "registered": ["agent-fin"]},
        "agentAccountId": "5e-bot",
        "conventions": {"notes": [], "blockedRequiresLink": False},
    }
    if meta is not None:
        cfg["_meta"] = meta
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


# --- (a) canonical_hash --------------------------------------------------


def test_canonical_hash_is_order_stable_and_strips_meta():
    a = {
        "transitions": {"DOING": {"status": "In Progress"}, "TODO": {"status": "To Do"}},
        "projectKey": "AGENT",
        "_meta": {"version": 7, "hash": "sha256:old"},
    }
    b = {
        "_meta": {"version": 999, "hash": "sha256:totally-different"},
        "projectKey": "AGENT",
        "transitions": {"TODO": {"status": "To Do"}, "DOING": {"status": "In Progress"}},
    }
    h_a = _bc.canonical_hash(a)
    h_b = _bc.canonical_hash(b)
    assert h_a == h_b, (h_a, h_b)
    assert h_a.startswith("sha256:") and len(h_a) == 7 + 64

    # Different content → different hash.
    c = dict(a)
    c["projectKey"] = "OTHER"
    assert _bc.canonical_hash(c) != h_a


# --- (b) (c) (f) version bump + first-push behavior ---------------------


def test_push_first_time_initializes_v1():
    queue = [
        _Response(404, b'{"errorMessages":["not found"]}', {}),
        _Response(204, b"", {}),
    ]
    calls: list[dict] = []
    client = _mock_client(queue, calls)

    config = {
        "projectKey": "AGENT",
        "transitions": {"DOING": {"status": "In Progress"}},
    }
    meta = _bc.push(client, "AGENT", config, account_id="5e-bot")
    assert meta["version"] == 1
    assert meta["hash"] == _bc.canonical_hash(config)
    assert meta["pushedByAccountId"] == "5e-bot"
    assert "pushedAt" in meta

    put = next(c for c in calls if c["method"] == "PUT")
    body = json.loads((put["body"] or b"").decode())
    assert body["_meta"] == meta


def test_push_second_time_bumps_version():
    # Remote already has v3.
    remote = {
        "key": "kanban-config",
        "value": {
            "projectKey": "AGENT",
            "transitions": {"DOING": {"status": "In Progress"}},
            "_meta": {"version": 3, "hash": "sha256:old",
                      "pushedAt": "2026-05-01T00:00:00+00:00"},
        },
    }
    queue = [
        _Response(200, json.dumps(remote).encode(), {}),
        _Response(204, b"", {}),
    ]
    calls: list[dict] = []
    client = _mock_client(queue, calls)

    config = {
        "projectKey": "AGENT",
        "transitions": {"DOING": {"status": "In Review"}},
    }
    meta = _bc.push(client, "AGENT", config, force=True)
    assert meta["version"] == 4


def test_push_first_time_no_fence_check():
    """Remote 404 + caller passed `if_match=None` ⇒ no fence, push
    proceeds normally. Covers the bootstrap path."""
    queue = [
        _Response(404, b'{"errorMessages":["not found"]}', {}),
        _Response(204, b"", {}),
    ]
    calls: list[dict] = []
    client = _mock_client(queue, calls)
    meta = _bc.push(client, "AGENT",
                    {"projectKey": "AGENT", "transitions": {}},
                    if_match=None)
    assert meta["version"] == 1


# --- (d) (e) --if-match fence -------------------------------------------


def test_push_if_match_mismatch_refused_without_force():
    remote = {
        "key": "kanban-config",
        "value": {
            "projectKey": "AGENT",
            "transitions": {"DOING": {"status": "In Progress"}},
            "_meta": {"version": 5, "hash": "sha256:remote-current",
                      "pushedAt": "2026-05-10T00:00:00+00:00",
                      "pushedByAccountId": "alice-id"},
        },
    }
    queue = [_Response(200, json.dumps(remote).encode(), {})]
    calls: list[dict] = []
    client = _mock_client(queue, calls)

    try:
        _bc.push(client, "AGENT",
                 {"projectKey": "AGENT", "transitions": {}},
                 if_match="sha256:i-pulled-this-stale-one")
    except _bc.BoardConfigError as e:
        assert getattr(e, "if_match_mismatch", False) is True
        rm = getattr(e, "remote_meta", None) or {}
        assert rm.get("version") == 5
        assert rm.get("pushedByAccountId") == "alice-id"
        # No PUT was issued — only the GET to read remote meta.
        assert all(c["method"] != "PUT" for c in calls)
        return
    raise AssertionError("expected BoardConfigError(if_match_mismatch)")


def test_push_if_match_mismatch_force_clobbers():
    remote = {
        "key": "kanban-config",
        "value": {
            "projectKey": "AGENT",
            "transitions": {"DOING": {"status": "In Progress"}},
            "_meta": {"version": 5, "hash": "sha256:remote-current"},
        },
    }
    queue = [
        _Response(200, json.dumps(remote).encode(), {}),
        _Response(204, b"", {}),
    ]
    calls: list[dict] = []
    client = _mock_client(queue, calls)

    meta = _bc.push(client, "AGENT",
                    {"projectKey": "AGENT", "transitions": {}},
                    if_match="sha256:wrong-on-purpose", force=True)
    assert meta["version"] == 6
    # PUT did fire.
    assert any(c["method"] == "PUT" for c in calls)


# --- (g) (h) cmd_push_board_config auto-fills --if-match ----------------


def test_cmd_push_auto_fills_if_match_from_local_meta_and_refuses_mismatch():
    """Local `_meta.hash` (= what this machine last pulled) is passed as
    `--if-match` automatically. Remote returns a different hash ⇒ push
    refuses; no PUT occurs."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        local_meta = {
            "version": 5,
            "hash": "sha256:my-cached-stale-hash",
            "pushedAt": "2026-05-10T00:00:00+00:00",
        }
        kp = _seed_jira_kanban(td, meta=local_meta)
        # Remote moved since: hash differs.
        remote = {
            "key": "kanban-config",
            "value": {
                "projectKey": "AGENT",
                "transitions": {"DOING": {"status": "In Progress"}},
                "_meta": {"version": 7, "hash": "sha256:remote-moved",
                          "pushedAt": "2026-05-15T00:00:00+00:00",
                          "pushedByAccountId": "alice-id"},
            },
        }
        queue = [_Response(200, json.dumps(remote).encode(), {})]
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

        assert rc != 0, out
        j = json.loads(out)
        assert j["ok"] is False
        assert j.get("ifMatchMismatch") is True
        assert j.get("expectedHash") == "sha256:my-cached-stale-hash"
        assert (j.get("remoteMeta") or {}).get("version") == 7
        # No PUT.
        assert all(c["method"] != "PUT" for c in calls)
        # Local file untouched.
        on_disk = json.loads(kp.read_text())
        assert on_disk["backend"]["jira"]["_meta"] == local_meta


def test_cmd_push_writes_new_meta_back_into_local():
    """A successful push lands the just-pushed `_meta` back on disk so
    the next push from this machine auto-fills `--if-match` correctly."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        local_meta = {
            "version": 5,
            "hash": "sha256:my-cached-hash",
            "pushedAt": "2026-05-10T00:00:00+00:00",
        }
        kp = _seed_jira_kanban(td, meta=local_meta)
        # Remote at the same hash (no drift) — push proceeds, increments
        # to v6.
        remote = {
            "key": "kanban-config",
            "value": {
                "projectKey": "AGENT",
                "transitions": {"DOING": {"status": "In Progress"}},
                "_meta": {"version": 5, "hash": "sha256:my-cached-hash"},
            },
        }
        # Make remote's hash match what local _canonical_share will
        # compute, so if_match auto-fill succeeds.
        # Build local payload and compute its canonical hash first.
        data = json.loads(kp.read_text())
        local_cfg = data["backend"]["jira"]
        canonical = _jira_setup._canonical_share(local_cfg)
        canonical_hash = _bc.canonical_hash(canonical)
        # Patch local meta + remote meta to that hash.
        local_meta["hash"] = canonical_hash
        local_cfg["_meta"] = local_meta
        kp.write_text(json.dumps(data))
        remote["value"]["_meta"]["hash"] = canonical_hash

        queue = [
            _Response(200, json.dumps(remote).encode(), {}),
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
        j = json.loads(out)
        assert j["meta"]["version"] == 6

        on_disk = json.loads(kp.read_text())
        cfg = on_disk["backend"]["jira"]
        assert cfg["_meta"]["version"] == 6
        assert cfg["_meta"]["hash"] == canonical_hash
        # Per-machine fields survived.
        assert cfg["agentAccountId"] == "5e-bot"
        assert cfg["ap"]["registered"] == ["agent-fin"]


# --- (i) cmd_pull_board_config captures remote _meta into local --------


def test_cmd_pull_captures_remote_meta():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td)  # local has no _meta yet
        remote = {
            "key": "kanban-config",
            "value": {
                "projectKey": "AGENT",
                "boardId": 1,
                "boardUrl": "https://x.atlassian.net/jira/projects/AGENT/boards/1",
                "transitions": {
                    "TODO": {"status": "To Do"},
                    "DOING": {"status": "In Progress"},
                    "APPROVED": {"status": "Done"},
                },
                "ap": {"fieldId": "customfield_10042",
                       "fieldName": "Claude Agent"},
                "conventions": {"notes": [], "blockedRequiresLink": False},
                "_meta": {
                    "version": 12,
                    "hash": "sha256:remote-hash-1234",
                    "pushedAt": "2026-05-15T11:22:33+00:00",
                    "pushedByAccountId": "alice-id",
                },
            },
        }
        queue = [_Response(200, json.dumps(remote).encode(), {})]
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
        on_disk = json.loads(kp.read_text())
        cfg = on_disk["backend"]["jira"]
        assert cfg["_meta"]["version"] == 12
        assert cfg["_meta"]["hash"] == "sha256:remote-hash-1234"
        assert cfg["_meta"]["pushedByAccountId"] == "alice-id"


# --- (j) cmd_read_board_config_cache reports meta + localHash ----------


def test_cmd_read_cache_reports_local_matches_meta_after_pull():
    """Right after a pull, `localHash == cachedHash` (no edits) ⇒
    `localMatchesMeta=True`."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        # Seed a kanban.json whose local _meta.hash equals the
        # canonical_hash of its content — i.e. "just pulled, untouched."
        kp = _seed_jira_kanban(td)
        data = json.loads(kp.read_text())
        canonical = _jira_setup._canonical_share(data["backend"]["jira"])
        h = _bc.canonical_hash(canonical)
        data["backend"]["jira"]["_meta"] = {
            "version": 4, "hash": h,
            "pushedAt": "2026-05-15T00:00:00+00:00",
        }
        kp.write_text(json.dumps(data))

        class A: kanban_path = str(kp)
        rc, out, err = _capture(_jira_setup.cmd_read_board_config_cache, A())
        assert rc == 0, (out, err)
        j = json.loads(out)
        assert j["meta"]["version"] == 4
        assert j["localHash"] == h
        assert j["localMatchesMeta"] is True


def test_cmd_read_cache_detects_local_edits():
    """A local edit makes `localHash != cachedHash` ⇒
    `localMatchesMeta=False`."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td)
        data = json.loads(kp.read_text())
        canonical = _jira_setup._canonical_share(data["backend"]["jira"])
        h = _bc.canonical_hash(canonical)
        data["backend"]["jira"]["_meta"] = {"version": 4, "hash": h,
                                            "pushedAt": "x"}
        # Mutate transitions ⇒ local hash drifts from cached hash.
        data["backend"]["jira"]["transitions"]["DOING"] = {"status": "Reviewing"}
        kp.write_text(json.dumps(data))

        class A: kanban_path = str(kp)
        rc, out, err = _capture(_jira_setup.cmd_read_board_config_cache, A())
        assert rc == 0, (out, err)
        j = json.loads(out)
        assert j["localMatchesMeta"] is False
        assert j["localHash"] != j["meta"]["hash"]


# --- (k) cmd_read_board_config emits diff with correct state -----------


def _run_show_diff(kp, remote_value):
    """Invoke cmd_read_board_config with a single remote response and
    return the parsed JSON output. The slash command always sends
    `--kanban-path`, which triggers the diff block."""
    remote = {"key": "kanban-config", "value": remote_value}
    queue = [_Response(200, json.dumps(remote).encode(), {})]
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
    return json.loads(out)


def _diff_setup(td: pathlib.Path):
    """Returns (kp, local_cfg_view, baseline_hash) where local_cfg_view
    is the canonical-shared view of the seeded `backend.jira` block,
    and baseline_hash is its canonical hash.

    Callers then mutate kp and/or build a remote payload from
    local_cfg_view to drive the four diff-state cases."""
    kp = _seed_jira_kanban(td)
    data = json.loads(kp.read_text())
    canonical = _jira_setup._canonical_share(data["backend"]["jira"])
    baseline_hash = _bc.canonical_hash(canonical)
    # Set local `_meta.hash` to baseline → "just pulled, untouched."
    data["backend"]["jira"]["_meta"] = {
        "version": 3, "hash": baseline_hash, "pushedAt": "2026-05-15T00:00:00+00:00",
    }
    kp.write_text(json.dumps(data))
    return kp, canonical, baseline_hash


def test_cmd_read_diff_state_in_sync():
    """local untouched + remote content equals baseline ⇒ in-sync."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp, canonical, baseline_hash = _diff_setup(td)
        # Remote payload = baseline canonical content + _meta.
        remote_value = {**canonical, "_meta": {
            "version": 3, "hash": baseline_hash, "pushedAt": "x"}}
        j = _run_show_diff(kp, remote_value)
        assert j["diff"]["state"] == "in-sync", j["diff"]


def test_cmd_read_diff_state_remote_ahead():
    """local untouched + remote content differs ⇒ remote-ahead."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp, canonical, _ = _diff_setup(td)
        # Mutate remote so its canonical content differs.
        remote_content = dict(canonical)
        remote_content["transitions"] = {
            **remote_content["transitions"],
            "REVIEW": {"status": "REVIEW"},
        }
        remote_value = {**remote_content,
                        "_meta": {"version": 4, "hash": "sha256:remote-newer", "pushedAt": "y"}}
        j = _run_show_diff(kp, remote_value)
        assert j["diff"]["state"] == "remote-ahead", j["diff"]


def test_cmd_read_diff_state_local_edits():
    """local edited + remote unchanged from baseline ⇒ local-edits."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp, canonical, baseline_hash = _diff_setup(td)
        # Mutate local content; cached _meta.hash stays at baseline.
        data = json.loads(kp.read_text())
        data["backend"]["jira"]["transitions"]["DOING"] = {"status": "Reviewing"}
        kp.write_text(json.dumps(data))
        # Remote stays at baseline.
        remote_value = {**canonical,
                        "_meta": {"version": 3, "hash": baseline_hash, "pushedAt": "x"}}
        j = _run_show_diff(kp, remote_value)
        assert j["diff"]["state"] == "local-edits", j["diff"]


def test_cmd_read_diff_state_diverged():
    """local edited + remote also moved ⇒ diverged."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp, canonical, _ = _diff_setup(td)
        # Mutate local.
        data = json.loads(kp.read_text())
        data["backend"]["jira"]["transitions"]["DOING"] = {"status": "Reviewing"}
        kp.write_text(json.dumps(data))
        # Mutate remote differently.
        remote_content = dict(canonical)
        remote_content["transitions"] = {
            **remote_content["transitions"],
            "DOING": {"status": "On Hold"},
        }
        remote_value = {**remote_content,
                        "_meta": {"version": 4, "hash": "sha256:remote-different", "pushedAt": "y"}}
        j = _run_show_diff(kp, remote_value)
        assert j["diff"]["state"] == "diverged", j["diff"]


def main() -> int:
    cases = [
        ("canonical_hash_is_order_stable_and_strips_meta",
         test_canonical_hash_is_order_stable_and_strips_meta),
        ("push_first_time_initializes_v1",
         test_push_first_time_initializes_v1),
        ("push_second_time_bumps_version",
         test_push_second_time_bumps_version),
        ("push_first_time_no_fence_check",
         test_push_first_time_no_fence_check),
        ("push_if_match_mismatch_refused_without_force",
         test_push_if_match_mismatch_refused_without_force),
        ("push_if_match_mismatch_force_clobbers",
         test_push_if_match_mismatch_force_clobbers),
        ("cmd_push_auto_fills_if_match_from_local_meta_and_refuses_mismatch",
         test_cmd_push_auto_fills_if_match_from_local_meta_and_refuses_mismatch),
        ("cmd_push_writes_new_meta_back_into_local",
         test_cmd_push_writes_new_meta_back_into_local),
        ("cmd_pull_captures_remote_meta",
         test_cmd_pull_captures_remote_meta),
        ("cmd_read_cache_reports_local_matches_meta_after_pull",
         test_cmd_read_cache_reports_local_matches_meta_after_pull),
        ("cmd_read_cache_detects_local_edits",
         test_cmd_read_cache_detects_local_edits),
        ("cmd_read_diff_state_in_sync", test_cmd_read_diff_state_in_sync),
        ("cmd_read_diff_state_remote_ahead", test_cmd_read_diff_state_remote_ahead),
        ("cmd_read_diff_state_local_edits", test_cmd_read_diff_state_local_edits),
        ("cmd_read_diff_state_diverged", test_cmd_read_diff_state_diverged),
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
        print(f"phase34: {failed} failure(s)", file=sys.stderr)
        return 1
    print("phase34: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
