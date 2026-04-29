#!/usr/bin/env python3
"""Jira-mode setup helper invoked by /kanban:initjira and friends.

Subcommands print JSON to stdout (one object per call). Errors print to
stderr and return non-zero. Tokens are read from --token-stdin (FD 0) so
they never appear in argv.

Subcommands:
  validate-credentials --base-url URL --email E
       (token on stdin)
       -> {"ok": true, "displayName": "...", "accountId": "..."}

  parse-board-url --url URL
       -> {"projectKey": "AGENT", "boardId": 1}

  validate-project --base-url URL --email E --project K --board ID
       (token on stdin)
       -> {"projectName": "...", "boardName": "...", "boardType": "scrum"}

  build-status-map --base-url URL --email E --project K
       (token on stdin)
       -> {"found": [{"name": "To Do"}, ...],
           "map": {"TODO": "To Do", "DOING": "In Progress", "DONE": "Done"},
           "missing": ["BLOCKED", "REVIEW", "CANCELLED"],
           "partial": true}

  write-backend --kanban-path P --jira-config-json '{...}'
       -> {"ok": true, "version": "0.2"}

  store-credentials --base-url URL --email E
       (token on stdin)
       -> {"ok": true}

  read-credentials
       -> {"baseUrl": "...", "email": "...", "tokenPresent": true}

  health
       -> driver-health JSON for current project

  list-tasks --kanban-path P [--column COL] [--limit N]
       -> {"tasks": [{...}, ...]}   # driver-dispatched, no token argv
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Import package modules with relative path. Plugin layout: scripts/ is a
# sibling of lib/ and drivers/. Python doesn't auto-import "kanban" in this
# layout, so we resolve plugins/ as the path root and import as
# `kanban.lib.*` etc.
HERE = Path(__file__).resolve()
PLUGINS_ROOT = HERE.parents[2]   # .../plugins
sys.path.insert(0, str(PLUGINS_ROOT))

from kanban.lib import credentials, kanban_io  # noqa: E402
from kanban.lib.jira_client import JiraClient, JiraError  # noqa: E402


# --- helpers --------------------------------------------------------------


CANONICAL_COLUMNS = ("TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED")

# Liberal name → canonical match, case-insensitive, ignoring whitespace and
# punctuation. Keys are compared as the lowercase normalised form.
_NAME_RULES: dict[str, str] = {
    "todo": "TODO",
    "to do": "TODO",
    "to-do": "TODO",
    "open": "TODO",
    "doing": "DOING",
    "in progress": "DOING",
    "inprogress": "DOING",
    "wip": "DOING",
    "blocked": "BLOCKED",
    "on hold": "BLOCKED",
    "review": "REVIEW",
    "in review": "REVIEW",
    "code review": "REVIEW",
    "done": "DONE",
    "closed": "DONE",
    "resolved": "DONE",
    "cancelled": "CANCELLED",
    "canceled": "CANCELLED",
    "wontfix": "CANCELLED",
    "won't fix": "CANCELLED",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def _read_token() -> str:
    if sys.stdin.isatty():
        sys.stderr.write("error: token expected on stdin\n")
        sys.exit(2)
    return sys.stdin.read().strip()


def _client(base_url: str, email: str, token: str) -> JiraClient:
    return JiraClient(base_url, email, token)


def _emit(obj: dict[str, Any]) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def _fail(msg: str, code: int = 1, **extra: Any) -> None:
    payload = {"ok": False, "error": msg, **extra}
    _emit(payload)
    sys.exit(code)


# --- subcommands ----------------------------------------------------------


def cmd_validate_credentials(args: argparse.Namespace) -> int:
    token = _read_token()
    try:
        me = _client(args.base_url, args.email, token).get_myself()
    except JiraError as e:
        _fail(f"jira: {e.detail or e}", code=1, statusCode=e.status_code)
        return 1
    except Exception as e:  # noqa: BLE001 — surface network errors clearly
        _fail(f"network: {e}", code=1)
        return 1
    _emit(
        {
            "ok": True,
            "displayName": me.get("displayName", ""),
            "accountId": me.get("accountId", ""),
            "emailAddress": me.get("emailAddress", ""),
        }
    )
    return 0


def cmd_store_credentials(args: argparse.Namespace) -> int:
    token = _read_token()
    if not token:
        _fail("empty token")
    credentials.write(
        {
            "JIRA_BASE_URL": args.base_url,
            "JIRA_AGENT_EMAIL": args.email,
            "JIRA_API_TOKEN": token,
        },
        prefix="JIRA_",
    )
    _emit({"ok": True})
    return 0


def cmd_read_credentials(_args: argparse.Namespace) -> int:
    env = credentials.read("JIRA_")
    _emit(
        {
            "baseUrl": env.get("JIRA_BASE_URL", ""),
            "email": env.get("JIRA_AGENT_EMAIL", ""),
            "tokenPresent": bool(env.get("JIRA_API_TOKEN")),
        }
    )
    return 0


_BOARD_URL_RE = re.compile(
    r"https?://[^/]+/jira/(?:software/(?:c/)?)?projects/(?P<key>[A-Z][A-Z0-9_]+)/boards/(?P<id>\d+)"
)


def cmd_parse_board_url(args: argparse.Namespace) -> int:
    m = _BOARD_URL_RE.search(args.url)
    if not m:
        _fail("could not parse board URL — expected /jira/.../projects/<KEY>/boards/<ID>")
        return 1
    _emit({"projectKey": m.group("key"), "boardId": int(m.group("id"))})
    return 0


def cmd_validate_project(args: argparse.Namespace) -> int:
    token = _read_token()
    client = _client(args.base_url, args.email, token)
    try:
        proj = client.get_project(args.project)
        board = client.get_board(args.board)
    except JiraError as e:
        _fail(f"jira: {e.detail or e}", statusCode=e.status_code)
        return 1
    _emit(
        {
            "ok": True,
            "projectName": proj.get("name", ""),
            "projectKey": proj.get("key", ""),
            "boardName": board.get("name", ""),
            "boardType": board.get("type", ""),
        }
    )
    return 0


def cmd_build_status_map(args: argparse.Namespace) -> int:
    token = _read_token()
    client = _client(args.base_url, args.email, token)
    try:
        types = client.get_project_statuses(args.project)
    except JiraError as e:
        _fail(f"jira: {e.detail or e}", statusCode=e.status_code)
        return 1

    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for issue_type in types or []:
        for status in issue_type.get("statuses", []) or []:
            n = status.get("name") or ""
            if n and n not in seen:
                seen.add(n)
                found.append({"name": n, "category": (status.get("statusCategory") or {}).get("key")})

    canonical_map: dict[str, str] = {}
    for s in found:
        canonical = _NAME_RULES.get(_norm(s["name"]))
        if canonical and canonical not in canonical_map:
            canonical_map[canonical] = s["name"]

    missing = [c for c in CANONICAL_COLUMNS if c not in canonical_map]
    label_fallback = {c: f"kanban:{c.lower()}" for c in missing}
    _emit(
        {
            "found": found,
            "map": canonical_map,
            "missing": missing,
            "partial": bool(missing),
            "labelFallback": label_fallback,
        }
    )
    return 0


def cmd_write_backend(args: argparse.Namespace) -> int:
    cfg = json.loads(args.jira_config_json)
    p = Path(args.kanban_path)
    if not p.exists():
        _fail(f"kanban.json not found at {p}")
        return 1
    data = kanban_io.load(p)
    data["backend"] = {"driver": "jira", "jira": cfg}
    # Adjust columns metadata to match SPEC: jira mode permits all 6.
    meta = data.setdefault("meta", {})
    meta["columns"] = list(CANONICAL_COLUMNS)
    kanban_io.save(p, data)
    _emit({"ok": True, "version": data.get("version", "0.2")})
    return 0


def cmd_list_tasks(args: argparse.Namespace) -> int:
    p = Path(args.kanban_path)
    if not p.exists():
        _fail(f"kanban.json not found at {p}")
        return 1
    data = kanban_io.load(p)
    from kanban.drivers import get_driver
    from kanban.drivers.base import TaskFilter

    driver = get_driver(data, p.parent)
    flt = TaskFilter(column=args.column, limit=args.limit)
    try:
        tasks = driver.list_tasks(flt)
    except Exception as e:  # noqa: BLE001
        _fail(f"{type(e).__name__}: {e}")
        return 1
    out: list[dict[str, Any]] = []
    for t in tasks:
        out.append(
            {
                "id": t.id,
                "title": t.title,
                "column": t.column,
                "priority": t.priority,
                "assignee": (
                    getattr(t.assignee, "accountId", None) or getattr(t.assignee, "ap", None)
                    if t.assignee
                    else None
                ),
                "ap": t.ap,
                "started": t.started,
                "completed": t.completed,
            }
        )
    _emit({"tasks": out})
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    p = Path(args.kanban_path)
    if not p.exists():
        _fail(f"kanban.json not found at {p}")
        return 1
    data = kanban_io.load(p)
    from kanban.drivers import get_driver

    driver = get_driver(data, p.parent)
    h = driver.health()
    _emit({"ok": h.status.value == "ok", "status": h.status.value, "detail": h.detail})
    return 0


# --- entry point ----------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jira_setup", add_help=True)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("validate-credentials")
    s.add_argument("--base-url", required=True)
    s.add_argument("--email", required=True)
    s.set_defaults(func=cmd_validate_credentials)

    s = sub.add_parser("store-credentials")
    s.add_argument("--base-url", required=True)
    s.add_argument("--email", required=True)
    s.set_defaults(func=cmd_store_credentials)

    s = sub.add_parser("read-credentials")
    s.set_defaults(func=cmd_read_credentials)

    s = sub.add_parser("parse-board-url")
    s.add_argument("--url", required=True)
    s.set_defaults(func=cmd_parse_board_url)

    s = sub.add_parser("validate-project")
    s.add_argument("--base-url", required=True)
    s.add_argument("--email", required=True)
    s.add_argument("--project", required=True)
    s.add_argument("--board", required=True, type=int)
    s.set_defaults(func=cmd_validate_project)

    s = sub.add_parser("build-status-map")
    s.add_argument("--base-url", required=True)
    s.add_argument("--email", required=True)
    s.add_argument("--project", required=True)
    s.set_defaults(func=cmd_build_status_map)

    s = sub.add_parser("write-backend")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--jira-config-json", required=True)
    s.set_defaults(func=cmd_write_backend)

    s = sub.add_parser("health")
    s.add_argument("--kanban-path", required=True)
    s.set_defaults(func=cmd_health)

    s = sub.add_parser("list-tasks")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--column")
    s.add_argument("--limit", type=int)
    s.set_defaults(func=cmd_list_tasks)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
