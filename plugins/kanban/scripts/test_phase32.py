#!/usr/bin/env python3
"""Phase 32 regression checks for kanban v0.3.27 — paste-flow removal +
/kanban:initjira auto-detect (PR 3 of 3).

PR 3 finishes the showjira-code → board-config replacement. The
kanban-jira-code paste subcommands (`emit-jira-code`, `import-jira-
code`) are gone; their slash commands (`showjira-code`,
`import-jira-code`, `initjira-by-code`) too. `/kanban:initjira` gains
a Step 2.5 that probes for board-config and skips DSL/AP-discovery
when found.

Cases:
  (a) cmd_emit_jira_code is gone — module attribute lookup fails.
  (b) cmd_import_jira_code is gone.
  (c) The corresponding slash command markdown files no longer exist
      under plugins/kanban/commands/.
  (d) emit-jira-code / import-jira-code subcommands are not in the
      argparse parser (running them with --help fails fast on the
      "unknown subcommand" path).
  (e) `cmd_pull_board_config --project-key K` against a project where
      the property exists returns the config — this is the helper
      `/kanban:initjira` step 2.5 calls when probing.
  (f) `cmd_pull_board_config --project-key K` against a project where
      the property does NOT exist returns ok=false with notFound=true,
      which is the signal `/kanban:initjira` step 2.5 uses to fall
      through to interactive Steps 3 + 4.
  (g) `cmd_pull_board_config` works via the explicit --project-key
      arg even when local kanban.json doesn't yet have a projectKey
      configured (the bootstrap-on-fresh-repo path).
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile

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


def _patch_client(client):
    orig_full = _jira_setup._client_from_env
    orig_opt = _jira_setup._client_from_env_or_none
    _jira_setup._client_from_env = lambda: client
    _jira_setup._client_from_env_or_none = lambda: client
    return (orig_full, orig_opt)


def _restore_client(originals):
    _jira_setup._client_from_env, _jira_setup._client_from_env_or_none = originals


# --- (a) (b) (c) (d) removal -------------------------------------------


def test_cmd_emit_jira_code_is_gone():
    assert not hasattr(_jira_setup, "cmd_emit_jira_code"), \
        "cmd_emit_jira_code should have been removed in 0.3.27"


def test_cmd_import_jira_code_is_gone():
    assert not hasattr(_jira_setup, "cmd_import_jira_code"), \
        "cmd_import_jira_code should have been removed in 0.3.27"


def test_old_command_markdowns_are_gone():
    cmd_dir = PLUGIN / "commands"
    for name in ("showjira-code", "import-jira-code", "initjira-by-code"):
        assert not (cmd_dir / f"{name}.md").exists(), \
            f"commands/{name}.md should have been removed in 0.3.27"


def test_argparse_no_longer_accepts_emit_or_import_subcommand():
    """Running `python3 jira_setup.py emit-jira-code --help` must fail
    because the subparser was removed. argparse exits with rc=2 and a
    'invalid choice' error on stderr."""
    cmd = ["python3", str(PLUGIN / "scripts" / "jira_setup.py"),
           "emit-jira-code", "--kanban-path", "/tmp/x"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    assert out.returncode != 0
    combined = (out.stderr + out.stdout).lower()
    assert "invalid choice" in combined or "unrecognized" in combined, combined

    cmd = ["python3", str(PLUGIN / "scripts" / "jira_setup.py"),
           "import-jira-code", "--kanban-path", "/tmp/x", "--code-json", "{}"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    assert out.returncode != 0


# --- (e) (f) (g) initjira step 2.5 probe paths --------------------------


def _seed_jira_kanban(td: pathlib.Path, *, project_key="AGENT") -> pathlib.Path:
    p = td / "kanban.json"
    p.write_text(json.dumps({
        "version": "0.2",
        "backend": {"driver": "jira", "jira": {
            "boardUrl": f"https://x/jira/projects/{project_key}/boards/1",
            "boardId": 1, "projectKey": project_key,
            "transitions": {
                "TODO": {"status": "To Do"},
                "DOING": {"status": "In Progress"},
                "APPROVED": {"status": "Done"},
            },
            "ap": {"fieldId": "customfield_10042",
                   "fieldName": "Claude Agent",
                   "registered": []},
        }},
        "meta": {"priorities": ["P0"], "categories": [],
                 "columns": ["TODO", "DOING", "BLOCKED", "REVIEW",
                             "APPROVED", "CANCELLED"],
                 "created_at": "x", "updated_at": "x"},
        "tasks": [],
    }))
    return p


def _seed_local_kanban(td: pathlib.Path) -> pathlib.Path:
    """A fresh repo where /kanban:init has been run but /kanban:initjira
    hasn't yet — backend is local, no projectKey. Step 2.5 probe needs
    --project-key passed explicitly."""
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


def test_initjira_step25_probe_finds_board_config():
    """Existing repo: kanban.json has projectKey populated. Step 2.5
    pulls without `--project-key` (uses the local one) and gets the
    config — initjira proceeds to Step 5 (assign AP), skipping DSL +
    AP-discovery."""
    remote = {
        "key": "kanban-config",
        "value": {
            "boardId": 1, "projectKey": "AGENT",
            "boardUrl": "https://x/jira/projects/AGENT/boards/1",
            "transitions": {
                "TODO": {"status": "Backlog"},
                "DOING": {"status": "In Progress"},
                "APPROVED": {"status": "Done"},
                "REVIEW": {"status": "REVIEW"},  # extra entry survived
            },
            "ap": {"fieldId": "customfield_10042",
                   "fieldName": "Claude Agent"},
            "conventions": {"notes": [], "blockedRequiresLink": False},
        },
    }
    queue = [_Response(200, json.dumps(remote).encode(), {})]
    calls: list[dict] = []
    client = _mock_client(queue, calls)

    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td)
        orig = _patch_client(client)
        try:
            class A:
                kanban_path = str(kp)
                project_key = None
            rc, out, err = _capture(_jira_setup.cmd_pull_board_config, A())
        finally:
            _restore_client(orig)

        assert rc == 0, (out, err)
        j = json.loads(out)
        assert j["ok"] is True
        assert j["projectKey"] == "AGENT"
        # The pulled config landed on disk
        on_disk = json.loads(kp.read_text())
        assert "REVIEW" in on_disk["backend"]["jira"]["transitions"]


def test_initjira_step25_probe_404_signals_fallback():
    """Step 2.5 probe against a project that has no `kanban-config`
    yet: the helper returns ok=false with notFound=true. The slash
    command treats that as "fall through to interactive DSL setup."
    """
    queue = [_Response(404, b'{"errorMessages":["nope"]}', {})]
    calls: list[dict] = []
    client = _mock_client(queue, calls)

    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira_kanban(td)
        orig = _patch_client(client)
        try:
            class A:
                kanban_path = str(kp)
                project_key = None
            rc, out, err = _capture(_jira_setup.cmd_pull_board_config, A())
        finally:
            _restore_client(orig)

        assert rc != 0, out
        j = json.loads(out)
        assert j["ok"] is False
        assert j.get("notFound") is True


def test_initjira_step25_bootstrap_with_explicit_project_key():
    """Bootstrap-on-fresh-repo: kanban.json is local-mode (no projectKey
    yet). Step 2.5 passes --project-key explicitly and pulls — this
    is what /kanban:initjira's auto-detect probe does after Step 2
    parses the board URL into a projectKey."""
    remote = {
        "key": "kanban-config",
        "value": {
            "boardId": 1, "projectKey": "AGENT",
            "boardUrl": "https://x/jira/projects/AGENT/boards/1",
            "transitions": {
                "TODO": {"status": "To Do"},
                "DOING": {"status": "In Progress"},
                "APPROVED": {"status": "Done"},
            },
            "ap": {"fieldId": "customfield_10042",
                   "fieldName": "Claude Agent"},
            "conventions": {"notes": [], "blockedRequiresLink": False},
        },
    }
    queue = [_Response(200, json.dumps(remote).encode(), {})]
    calls: list[dict] = []
    client = _mock_client(queue, calls)

    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_local_kanban(td)
        orig = _patch_client(client)
        try:
            class A:
                kanban_path = str(kp)
                project_key = "AGENT"   # explicit — kanban.json doesn't
                                        # carry it yet
            rc, out, err = _capture(_jira_setup.cmd_pull_board_config, A())
        finally:
            _restore_client(orig)

        assert rc == 0, (out, err)
        # backend.driver flipped to jira and config landed on disk
        on_disk = json.loads(kp.read_text())
        assert on_disk["backend"]["driver"] == "jira"
        assert on_disk["backend"]["jira"]["projectKey"] == "AGENT"
        assert on_disk["backend"]["jira"]["transitions"]


def main() -> int:
    cases = [
        ("cmd_emit_jira_code_is_gone", test_cmd_emit_jira_code_is_gone),
        ("cmd_import_jira_code_is_gone", test_cmd_import_jira_code_is_gone),
        ("old_command_markdowns_are_gone",
         test_old_command_markdowns_are_gone),
        ("argparse_no_longer_accepts_emit_or_import_subcommand",
         test_argparse_no_longer_accepts_emit_or_import_subcommand),
        ("initjira_step25_probe_finds_board_config",
         test_initjira_step25_probe_finds_board_config),
        ("initjira_step25_probe_404_signals_fallback",
         test_initjira_step25_probe_404_signals_fallback),
        ("initjira_step25_bootstrap_with_explicit_project_key",
         test_initjira_step25_bootstrap_with_explicit_project_key),
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
        print(f"phase32: {failed} failure(s)", file=sys.stderr)
        return 1
    print("phase32: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
