#!/usr/bin/env python3
"""notify-dispatch.py — claude-workbench notify plugin (§4).

Two entry contracts:

  1. Hook mode (default): invoked by Claude Code's ``Notification`` hook with
     event JSON on stdin. Resolves a routing rule, dispatches to each matching
     provider. Always exits 0 — notifications are never allowed to block.

  2. CLI mode (--cli): invoked by the ``workbench-notify`` shim. Argv carries
     --title/--message/--priority/--provider. Used by sibling plugins for
     cross-plugin integration (kanban, docsync, memory).

Plus a cheap ``--health`` sub-mode used by capability detection.

Design notes:
- Config at ~/.claude-workbench/notify-config.json. ``${…}`` env-var expansion.
- Messages are scrubbed of token-shaped substrings before send.
- Throttle state lives at ~/.claude-workbench/state/notify-throttle.json.
- Failures append to ~/.claude-workbench/logs/notify-failures.log; hook still
  exits 0. Log lines NEVER contain the full message body (avoid secret leak).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# Make ``providers`` importable whether this script is run standalone or
# installed elsewhere (CLI wrapper sets PYTHONPATH).
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from providers import pushover  # noqa: E402

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

WORKBENCH_HOME = Path(os.path.expanduser("~/.claude-workbench"))
CONFIG_PATH = WORKBENCH_HOME / "notify-config.json"
ENV_FILE = WORKBENCH_HOME / ".env"
LOG_DIR = WORKBENCH_HOME / "logs"
STATE_DIR = WORKBENCH_HOME / "state"
FAILURE_LOG = LOG_DIR / "notify-failures.log"
THROTTLE_STATE = STATE_DIR / "notify-throttle.json"

PROVIDERS = {"pushover": pushover}


# -----------------------------------------------------------------------------
# .env auto-load
# -----------------------------------------------------------------------------
# Without this, users would have to `export PUSHOVER_USER_KEY=…` in their shell
# rc — painful on Windows GUI-launched shells and anywhere env isn't inherited.
# The dispatcher reads ~/.claude-workbench/.env at import time, filling in any
# variables not already present in os.environ. Process env always wins, so
# users who DO set shell exports are unaffected.

def _load_env_file(path: Path) -> None:
    """Populate os.environ from a KEY=VALUE file. Silent on missing/unreadable.

    Accepted line shapes:
        KEY=value
        KEY="value"
        KEY='value'
        export KEY=value
        # comment line (skipped)
    Existing process env keys are NEVER overwritten — shell exports win.
    """
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file(ENV_FILE)

# -----------------------------------------------------------------------------
# Secret scrubber
# -----------------------------------------------------------------------------

# Token-shaped substrings we replace with `[REDACTED]` before dispatch. The list
# is intentionally conservative — false positives are better than a leak.
_TOKEN_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),          # OpenAI-style
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),      # Anthropic
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),            # GitHub PAT
    re.compile(r"gho_[A-Za-z0-9]{20,}"),            # GitHub OAuth
    re.compile(r"xox[abpr]-[A-Za-z0-9-]{10,}"),     # Slack
    re.compile(r"AKIA[0-9A-Z]{16}"),                # AWS access key id
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),         # Google API key
    re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),  # JWT
    re.compile(r"\b[A-Fa-f0-9]{40,}\b"),            # bare hex >= 40
]


def scrub(text: str) -> str:
    if not text:
        return text
    for pat in _TOKEN_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


# -----------------------------------------------------------------------------
# Config loading
# -----------------------------------------------------------------------------

_ENV_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _expand_env(value):
    """Recursively expand ``${VAR}`` references inside strings."""
    if isinstance(value, str):
        return _ENV_VAR_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_config():
    if not CONFIG_PATH.exists():
        return None
    try:
        with CONFIG_PATH.open() as f:
            raw = json.load(f)
    except Exception as e:
        _log_failure(f"config parse error: {e}")
        return None
    return _expand_env(raw)


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

def _log_failure(msg: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with FAILURE_LOG.open("a") as f:
            ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Throttle
# -----------------------------------------------------------------------------

def _throttle_key(event: str, provider: str) -> str:
    return f"{event}:{provider}"


def should_throttle(event: str, provider: str, window: int) -> bool:
    """Return True if a notification for ``(event, provider)`` was sent inside
    the trailing ``window`` seconds."""
    if window <= 0:
        return False
    try:
        with THROTTLE_STATE.open() as f:
            state = json.load(f)
    except Exception:
        state = {}
    last = state.get(_throttle_key(event, provider), 0)
    return (time.time() - last) < window


def record_sent(event: str, provider: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with THROTTLE_STATE.open() as f:
                state = json.load(f)
        except Exception:
            state = {}
        state[_throttle_key(event, provider)] = int(time.time())
        with THROTTLE_STATE.open("w") as f:
            json.dump(state, f)
    except Exception as e:
        _log_failure(f"throttle state write error: {e}")


# -----------------------------------------------------------------------------
# Rule resolution
# -----------------------------------------------------------------------------

def resolve_rule(config, event_type: str):
    """Find the first matching rule, or synth a default from default_provider."""
    rules = (config or {}).get("rules") or []
    for rule in rules:
        match = rule.get("match") or {}
        if match.get("notification_type") == event_type:
            return rule
    default = (config or {}).get("default_provider")
    if default:
        return {"match": {"notification_type": event_type},
                "providers": [default],
                "priority": 0}
    return None


# -----------------------------------------------------------------------------
# Dispatch
# -----------------------------------------------------------------------------

def dispatch(title: str, message: str, priority: int, event_type: str,
             providers_list, config, url=None):
    """Send to each configured provider. Returns number of successful sends."""
    title = scrub(title or "Claude Code")
    message = scrub(message or "")
    url = scrub(url) if url else None

    sent = 0
    for pname in providers_list or []:
        mod = PROVIDERS.get(pname)
        if mod is None:
            _log_failure(f"unknown provider: {pname}")
            continue
        pconf = (config or {}).get("providers", {}).get(pname) or {}
        if not pconf.get("enabled"):
            continue
        try:
            ok = mod.send(
                config=pconf,
                title=title,
                message=message,
                priority=priority,
                event_type=event_type,
                url=url,
            )
            if ok:
                sent += 1
                record_sent(event_type, pname)
            else:
                _log_failure(f"{pname}: send returned falsy")
        except Exception as e:
            _log_failure(f"{pname}: {type(e).__name__}: {e}")
    return sent


_PRIORITY_WORDS = {"low": -1, "normal": 0, "high": 1, "emergency": 2}


def _normalise_priority(p):
    if p is None:
        return 0
    if isinstance(p, int):
        return p
    return _PRIORITY_WORDS.get(str(p).lower(), 0)


# -----------------------------------------------------------------------------
# Hook mode
# -----------------------------------------------------------------------------

def run_hook(args):
    """Read Claude Code Notification event JSON from stdin, dispatch."""
    try:
        payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        payload = {}

    event_type = (
        payload.get("notification_type")
        or payload.get("hook_event_name")
        or payload.get("type")
        or "idle_prompt"
    )
    message = payload.get("message") or payload.get("text") or ""
    title = payload.get("title") or "Claude Code"

    config = load_config()
    if not config:
        # No config — silent no-op. /notify:setup hasn't been run yet.
        return 0

    rule = resolve_rule(config, event_type)
    if rule is None:
        return 0

    throttle = rule.get("throttle_seconds") or args.throttle or 0
    priority = _normalise_priority(rule.get("priority"))

    for pname in rule.get("providers", []):
        if should_throttle(event_type, pname, throttle):
            continue
        dispatch(title=title, message=message, priority=priority,
                 event_type=event_type, providers_list=[pname],
                 config=config)
    return 0


# -----------------------------------------------------------------------------
# CLI mode (used by workbench-notify shim)
# -----------------------------------------------------------------------------

def run_cli(args):
    config = load_config()
    if not config:
        print("notify: config not found; run /notify:setup", file=sys.stderr)
        return 1

    providers_list = [args.provider] if args.provider else \
        ([config.get("default_provider")] if config.get("default_provider") else [])
    if not providers_list:
        print("notify: no provider resolved", file=sys.stderr)
        return 1

    priority = _normalise_priority(args.priority)
    sent = dispatch(
        title=args.title,
        message=args.message,
        priority=priority,
        event_type="cli",
        providers_list=providers_list,
        config=config,
        url=args.url,
    )
    return 0 if sent > 0 else 1


def run_health(_args):
    """Exit 0 iff config exists, parses, and at least one provider enabled."""
    config = load_config()
    if not config:
        print("notify: unconfigured", file=sys.stderr)
        return 1
    providers = (config.get("providers") or {})
    if any(p.get("enabled") for p in providers.values()):
        print("notify: ok")
        return 0
    print("notify: no enabled provider", file=sys.stderr)
    return 1


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--cli", action="store_true",
                    help="Run in CLI mode (invoked by workbench-notify shim).")
    ap.add_argument("--health", action="store_true",
                    help="Exit 0 iff notify is configured and has an enabled provider.")
    ap.add_argument("--throttle", type=int, default=0,
                    help="Hook-mode fallback throttle in seconds (used when rule has none).")

    # CLI-mode args (ignored in hook mode)
    ap.add_argument("--title", default="Claude Code")
    ap.add_argument("--message", default="")
    ap.add_argument("--priority", default="normal",
                    help="low | normal | high | emergency (or integer -2..2)")
    ap.add_argument("--provider", default=None)
    ap.add_argument("--url", default=None)

    args = ap.parse_args()

    try:
        if args.health:
            return run_health(args)
        if args.cli:
            return run_cli(args)
        return run_hook(args)
    except Exception as e:
        _log_failure(f"uncaught: {type(e).__name__}: {e}")
        return 0  # never block the hook


if __name__ == "__main__":
    sys.exit(main())
