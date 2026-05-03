#!/usr/bin/env python3
"""Phase 24 regression checks for kanban v0.3.18 — secret-safe token
capture via `--prompt-token` and `validate-project --from-env`.

Background (#42): the original `store-credentials` flow had the agent
construct `echo "<TOKEN>" | python3 ... store-credentials ...` and run
it through Claude Code's Bash tool. Claude Code prints every Bash
command to the conversation transcript for transparency, so the token
literal ends up in the conversation log. The plugin's own leak detector
then warned the user to rotate — a self-inflicted loop the user has to
work around.

The fix:

1. `_read_token(prompt=True)` uses `getpass.getpass`, which reads from
   the controlling terminal (never argv, never stdin pipe, never the
   parent process's view of the file descriptors). Used by the user
   themselves in their own terminal; the agent prints the command and
   waits for the user to confirm.
2. `validate-project --from-env` reads the token from
   `~/.claude-workbench/.env` instead of stdin, so step 2 of
   `/kanban:initjira` doesn't need the agent to pipe the token through
   a Bash command either.

Cases:
  (a) `_read_token(prompt=True)` calls `getpass.getpass` and returns
      the stripped result.
  (b) `_read_token(prompt=True)` aborts cleanly on EOFError /
      KeyboardInterrupt rather than crashing the helper.
  (c) `cmd_store_credentials` with `--prompt-token` writes the token
      from the prompt into `.env` (no stdin needed).
  (d) `cmd_validate_project` with `--from-env` reads the token from
      `~/.claude-workbench/.env` and never touches stdin.
  (e) `cmd_validate_project` with `--from-env` and missing token in
      `.env` fails with a clear "run reset-credentials" hint.
  (f) Back-compat: `cmd_store_credentials` without `--prompt-token`
      still reads from stdin (existing automation paths must keep
      working).
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"
sys.path.insert(0, str(REPO / "plugins" / "kanban"))

_spec = importlib.util.spec_from_file_location(
    "jira_setup_mod", str(PLUGIN / "scripts" / "jira_setup.py")
)
_jira_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_jira_setup)  # type: ignore[union-attr]


def _capture(fn, args, *, stdin_bytes: bytes | None = None):
    """Run `fn(args)` capturing stdout. Optionally feed `stdin_bytes`
    on stdin (replaces sys.stdin)."""
    old_out = sys.stdout
    old_in = sys.stdin
    sys.stdout = io.StringIO()
    if stdin_bytes is not None:
        sys.stdin = io.StringIO(stdin_bytes.decode())
    try:
        try:
            rc = fn(args)
        except SystemExit as e:
            rc = e.code
        out = sys.stdout.getvalue()
    finally:
        sys.stdout = old_out
        sys.stdin = old_in
    return rc, out


# --- (a) (b) _read_token prompt path ------------------------------------


def test_read_token_prompt_reads_from_getpass():
    """When called with prompt=True, _read_token uses getpass.getpass —
    never falls through to stdin (which would prompt for token via the
    leaky path)."""
    import getpass
    orig = getpass.getpass
    getpass.getpass = lambda prompt="": "  super-secret-token  "
    try:
        token = _jira_setup._read_token(prompt=True)
    finally:
        getpass.getpass = orig
    # Whitespace stripped so trailing newlines from paste don't poison
    # the env file.
    assert token == "super-secret-token", repr(token)


def test_read_token_prompt_handles_user_abort():
    """Ctrl-C / EOF at the prompt exits cleanly, not with an unhandled
    exception."""
    import getpass
    orig = getpass.getpass

    def raises(prompt=""):
        raise EOFError()

    getpass.getpass = raises
    try:
        try:
            _jira_setup._read_token(prompt=True)
        except SystemExit as e:
            assert e.code == 2
            return
        raise AssertionError("expected SystemExit on EOF")
    finally:
        getpass.getpass = orig


# --- (c) (f) store-credentials prompt + stdin paths ---------------------


def _isolated_credentials(td: pathlib.Path):
    """Point credentials.ENV_DIR / ENV_FILE at a sandbox so we don't
    touch the user's real .env. The constants are evaluated at module
    load via Path.home(), so changing HOME at runtime is too late —
    monkey-patch the constants directly. Returns originals to restore."""
    from lib import credentials
    home = td / "fakehome"
    cw = home / ".claude-workbench"
    cw.mkdir(parents=True, exist_ok=True)
    orig_dir = credentials.ENV_DIR
    orig_file = credentials.ENV_FILE
    credentials.ENV_DIR = cw
    credentials.ENV_FILE = cw / ".env"
    return (orig_dir, orig_file)


def _restore_credentials(originals):
    from lib import credentials
    credentials.ENV_DIR, credentials.ENV_FILE = originals


def _read_env_token(td: pathlib.Path) -> str | None:
    env_file = td / "fakehome" / ".claude-workbench" / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text().splitlines():
        if line.startswith("JIRA_API_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def test_store_credentials_prompt_token_writes_env_no_stdin():
    """Happy path for the secret-safe capture: --prompt-token gets the
    token from getpass, writes it to .env, never touches stdin."""
    import getpass
    orig_getpass = getpass.getpass
    getpass.getpass = lambda prompt="": "tk-from-prompt-12345"

    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        originals = _isolated_credentials(td)
        try:
            class A:
                base_url = "https://x.atlassian.net"
                email = "a@b.com"
                prompt_token = True

            # NOTE: stdin is a real TTY here; without --prompt-token the
            # helper would sys.exit(2). Verify --prompt-token bypasses
            # that path entirely.
            rc, out = _capture(_jira_setup.cmd_store_credentials, A())
            assert rc == 0, out
            j = json.loads(out)
            assert j["ok"] is True
            assert _read_env_token(td) == "tk-from-prompt-12345"
        finally:
            _restore_credentials(originals)
            getpass.getpass = orig_getpass


def test_store_credentials_stdin_path_still_works():
    """Back-compat: existing automation that pipes the token via stdin
    must keep working (CI, scripts, etc.)."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        originals = _isolated_credentials(td)
        try:
            class A:
                base_url = "https://x.atlassian.net"
                email = "a@b.com"
                prompt_token = False

            rc, out = _capture(
                _jira_setup.cmd_store_credentials, A(),
                stdin_bytes=b"tk-from-stdin-67890\n",
            )
            assert rc == 0, out
            assert _read_env_token(td) == "tk-from-stdin-67890"
        finally:
            _restore_credentials(originals)


# --- (d) (e) validate-project --from-env --------------------------------


def _seed_env_with_token(td: pathlib.Path, token: str):
    """Pre-populate ~/.claude-workbench/.env with a token so
    validate-project --from-env has something to read. Match the
    unquoted format that credentials.write produces (no surrounding
    double quotes)."""
    home = td / "fakehome"
    cw = home / ".claude-workbench"
    cw.mkdir(parents=True, exist_ok=True)
    (cw / ".env").write_text(
        f"JIRA_BASE_URL=https://x.atlassian.net\n"
        f"JIRA_AGENT_EMAIL=a@b.com\n"
        f"JIRA_API_TOKEN={token}\n"
    )


def test_validate_project_from_env_reads_token_not_stdin():
    """The from-env path should pick up the token from .env and call
    Jira with it; stdin is irrelevant. We can't actually hit Jira in
    tests, so monkey-patch the JiraClient to assert the token reaches
    it without ever passing through stdin."""
    received: dict[str, str] = {}

    class _StubClient:
        def __init__(self, base_url, email, token):
            received["base_url"] = base_url
            received["email"] = email
            received["token"] = token

        def get_project(self, key):
            return {"name": "Project X", "key": key}

        def get_board(self, board_id):
            return {"name": "Board Y", "type": "scrum"}

    orig_client = _jira_setup._client
    _jira_setup._client = _StubClient

    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        originals = _isolated_credentials(td)
        try:
            _seed_env_with_token(td, "tk-from-env-XYZ")

            class A:
                base_url = "https://x.atlassian.net"
                email = "a@b.com"
                project = "AGENT"
                board = 1
                from_env = True
                prompt_token = False

            # stdin is empty/TTY — without --from-env this would fail.
            rc, out = _capture(_jira_setup.cmd_validate_project, A())
            assert rc == 0, out
            j = json.loads(out)
            assert j["ok"] is True
            assert received["token"] == "tk-from-env-XYZ"
        finally:
            _restore_credentials(originals)
            _jira_setup._client = orig_client


def test_validate_project_from_env_missing_token_fails_with_hint():
    """When .env exists but has no JIRA_API_TOKEN, fail with an actionable
    message — don't proceed with an empty token (which would 401)."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        originals = _isolated_credentials(td)
        try:
            # Create empty .env (no JIRA_API_TOKEN line)
            home = td / "fakehome"
            cw = home / ".claude-workbench"
            cw.mkdir(parents=True, exist_ok=True)
            (cw / ".env").write_text("")

            class A:
                base_url = "https://x.atlassian.net"
                email = "a@b.com"
                project = "AGENT"
                board = 1
                from_env = True
                prompt_token = False

            rc, out = _capture(_jira_setup.cmd_validate_project, A())
            assert rc != 0, out
            j = json.loads(out)
            assert j.get("ok") is False
            err = (j.get("error") or "").lower()
            assert "no jira_api_token" in err, j
            assert "reset-credentials" in err, j
        finally:
            _restore_credentials(originals)


def main() -> int:
    cases = [
        ("read_token_prompt_reads_from_getpass",
         test_read_token_prompt_reads_from_getpass),
        ("read_token_prompt_handles_user_abort",
         test_read_token_prompt_handles_user_abort),
        ("store_credentials_prompt_token_writes_env_no_stdin",
         test_store_credentials_prompt_token_writes_env_no_stdin),
        ("store_credentials_stdin_path_still_works",
         test_store_credentials_stdin_path_still_works),
        ("validate_project_from_env_reads_token_not_stdin",
         test_validate_project_from_env_reads_token_not_stdin),
        ("validate_project_from_env_missing_token_fails_with_hint",
         test_validate_project_from_env_missing_token_fails_with_hint),
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
        print(f"phase24: {failed} failure(s)", file=sys.stderr)
        return 1
    print("phase24: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
