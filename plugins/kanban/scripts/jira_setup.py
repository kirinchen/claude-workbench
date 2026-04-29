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

  Phase 3 — AP routing:

  find-ap-field
       -> {"candidates": [{"id": "customfield_10042", "name": "Claude Agent"}, ...]}

  create-ap-field [--name "Claude Agent"]
       -> {"ok": true, "fieldId": "customfield_10042", "fieldName": "Claude Agent"}
       (requires Jira admin; surfaces 403 with a clear hint)

  set-ap-field --kanban-path P --field-id customfield_X --field-name N
       -> {"ok": true, ...}   # writes backend.jira.ap to kanban.json

  register-ap --kanban-path P --name N [--force]
       -> {"ok": true, "registered": [...]}                # success
       -> {"ok": false, "fuzzyMatch": true, "similar": [...]}   # caller must --force

  assign-ap --kanban-path P --name N
       -> {"ok": true, "ap": N, "path": ".../.claude/kanban-agent.json"}

  read-agent-ap --kanban-path P
       -> {"ap": N | null, "path": "..."}

  claim-next --kanban-path P
       -> {"ok": true, "claimed": {"id":..., "title":..., "priority":..., "ap":...}}

  transition --kanban-path P --key K --to COLUMN [--reason R]
       -> {"ok": true, "key": K, "column": COLUMN, "raw_status": "..."}
       -> exit 2 with kind=self-approve when SPEC §8 anti-self-approve fires
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

from kanban.lib import ap_registry, credentials, kanban_io  # noqa: E402
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


def _client_from_env() -> JiraClient:
    env = credentials.read("JIRA_")
    base = env.get("JIRA_BASE_URL")
    email = env.get("JIRA_AGENT_EMAIL")
    tok = env.get("JIRA_API_TOKEN")
    if not (base and email and tok):
        _fail("Jira credentials missing — run /kanban:initjira or /kanban:reset-credentials")
    return JiraClient(base, email, tok)


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


def cmd_find_ap_field(_args: argparse.Namespace) -> int:
    """List custom fields whose name suggests an agent property."""
    client = _client_from_env()
    try:
        fields = client.list_fields() or []
    except JiraError as e:
        _fail(f"jira: {e.detail or e}", statusCode=e.status_code)
        return 1
    candidates = []
    for f in fields:
        if not f.get("custom"):
            continue
        name = (f.get("name") or "").lower()
        if "agent" in name or "claude" in name or "ap" == name:
            candidates.append({"id": f.get("id"), "name": f.get("name")})
    _emit({"candidates": candidates})
    return 0


def cmd_create_ap_field(args: argparse.Namespace) -> int:
    client = _client_from_env()
    try:
        result = client.create_custom_field(
            name=args.name,
            description="Distinguishes which AI agent owns this card. Managed by claude-workbench kanban plugin.",
        )
    except JiraError as e:
        if e.status_code == 403:
            _fail(
                "permission denied — creating a custom field requires Jira admin. "
                "Ask an admin to create a single-select field once, then re-run "
                "/kanban:initjira and pick [a] use existing field.",
                statusCode=e.status_code,
            )
            return 1
        _fail(f"jira: {e.detail or e}", statusCode=e.status_code)
        return 1
    _emit({"ok": True, "fieldId": result.get("id"), "fieldName": result.get("name")})
    return 0


def cmd_set_ap_field(args: argparse.Namespace) -> int:
    p = Path(args.kanban_path)
    if not p.exists():
        _fail(f"kanban.json not found at {p}")
        return 1
    data = kanban_io.load(p)
    backend = data.setdefault("backend", {"driver": "jira"})
    if backend.get("driver") != "jira":
        _fail("backend.driver must be 'jira' before configuring AP")
        return 1
    jira_cfg = backend.setdefault("jira", {})
    ap_block = jira_cfg.setdefault("ap", {})
    ap_block["fieldId"] = args.field_id
    ap_block["fieldName"] = args.field_name
    ap_block.setdefault("registered", [])
    kanban_io.save(p, data)
    _emit({"ok": True, "fieldId": args.field_id, "fieldName": args.field_name})
    return 0


def _resolve_default_context(client: JiraClient, field_id: str) -> int:
    ctxs = client.list_field_contexts(field_id) or {}
    values = ctxs.get("values") or []
    for v in values:
        if v.get("isGlobalContext") or v.get("default") or len(values) == 1:
            return int(v["id"])
    if values:
        return int(values[0]["id"])
    raise RuntimeError("no contexts found for AP field — Jira config is unusual")


def cmd_register_ap(args: argparse.Namespace) -> int:
    """Add `--name` to the AP field's options + cache in kanban.json#registered."""
    p = Path(args.kanban_path)
    if not p.exists():
        _fail(f"kanban.json not found at {p}")
        return 1
    try:
        ap_registry.validate_ap_name(args.name)
    except ap_registry.APValidationError as e:
        _fail(str(e))
        return 1

    data = kanban_io.load(p)
    backend = data.get("backend") or {}
    if backend.get("driver") != "jira":
        _fail("backend.driver must be 'jira'")
        return 1
    jira_cfg = backend.get("jira") or {}
    ap_block = jira_cfg.get("ap") or {}
    field_id = ap_block.get("fieldId")
    if not field_id:
        _fail("AP field unconfigured — run /kanban:initjira step 4")
        return 1
    registered = list(ap_block.get("registered") or [])

    if ap_registry.is_exact_collision(args.name, registered):
        _emit({"ok": True, "alreadyRegistered": True, "name": args.name})
        return 0

    hits = ap_registry.fuzzy_collisions(args.name, registered)
    if hits and not args.force:
        _emit(
            {
                "ok": False,
                "fuzzyMatch": True,
                "name": args.name,
                "similar": [{"name": h.name, "distance": h.distance} for h in hits],
            }
        )
        return 0  # caller decides; not an error

    client = _client_from_env()
    try:
        ctx_id = _resolve_default_context(client, field_id)
        client.add_field_option(field_id, ctx_id, args.name)
    except JiraError as e:
        _fail(f"jira: {e.detail or e}", statusCode=e.status_code)
        return 1

    registered.append(args.name)
    ap_block["registered"] = registered
    jira_cfg["ap"] = ap_block
    backend["jira"] = jira_cfg
    data["backend"] = backend
    kanban_io.save(p, data)
    _emit({"ok": True, "name": args.name, "registered": registered})
    return 0


def cmd_assign_ap(args: argparse.Namespace) -> int:
    p = Path(args.kanban_path)
    if not p.exists():
        _fail(f"kanban.json not found at {p}")
        return 1
    data = kanban_io.load(p)
    backend = data.get("backend") or {}
    if backend.get("driver") != "jira":
        _fail("backend.driver must be 'jira'")
        return 1
    registered = ((backend.get("jira") or {}).get("ap") or {}).get("registered") or []
    if args.name not in registered:
        _fail(
            f"AP {args.name!r} is not registered. Register it first via "
            f"/kanban:register-ap {args.name}",
            registered=list(registered),
        )
        return 1

    repo_root = p.parent
    claude_dir = repo_root / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    target = claude_dir / "kanban-agent.json"
    target.write_text(
        json.dumps({"ap": args.name}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _emit({"ok": True, "ap": args.name, "path": str(target)})
    return 0


def cmd_read_agent_ap(args: argparse.Namespace) -> int:
    p = Path(args.kanban_path)
    repo_root = p.parent
    target = repo_root / ".claude" / "kanban-agent.json"
    if not target.exists():
        _emit({"ap": None})
        return 0
    try:
        ap = json.loads(target.read_text()).get("ap")
    except Exception as e:  # noqa: BLE001
        _fail(f"corrupt kanban-agent.json: {e}")
        return 1
    _emit({"ap": ap, "path": str(target)})
    return 0


def cmd_claim_next(args: argparse.Namespace) -> int:
    p = Path(args.kanban_path)
    if not p.exists():
        _fail(f"kanban.json not found at {p}")
        return 1
    data = kanban_io.load(p)
    backend = data.get("backend") or {}
    if backend.get("driver") != "jira":
        _fail("backend.driver must be 'jira'")
        return 1
    target = repo_root_ap = ((p.parent / ".claude" / "kanban-agent.json"))
    if not target.exists():
        _fail("this repo has no AP set — run /kanban:assign-ap <name> first")
        return 1
    try:
        ap = json.loads(target.read_text()).get("ap")
    except Exception as e:  # noqa: BLE001
        _fail(f"corrupt kanban-agent.json: {e}")
        return 1
    if not ap:
        _fail("kanban-agent.json present but `ap` is empty")
        return 1

    from kanban.drivers import get_driver
    from kanban.drivers.base import CommentKind, TaskFilter

    driver = get_driver(data, p.parent)
    todos = driver.list_tasks(TaskFilter(column="TODO", ap=ap, limit=1))
    if not todos:
        _emit({"ok": True, "claimed": None, "reason": "no TODO cards for this AP"})
        return 0
    pick = todos[0]
    try:
        driver.transition(pick.id, "DOING")
    except Exception as e:  # noqa: BLE001
        _fail(f"transition: {type(e).__name__}: {e}")
        return 1
    driver.post_comment(pick.id, "claimed", kind=CommentKind.SYSTEM)
    refreshed = driver.get_task(pick.id)
    _emit(
        {
            "ok": True,
            "claimed": {
                "id": refreshed.id,
                "title": refreshed.title,
                "priority": refreshed.priority,
                "ap": refreshed.ap,
            },
        }
    )
    return 0


def cmd_transition(args: argparse.Namespace) -> int:
    p = Path(args.kanban_path)
    if not p.exists():
        _fail(f"kanban.json not found at {p}")
        return 1
    data = kanban_io.load(p)
    from kanban.drivers import get_driver
    from kanban.drivers.base import CommentKind
    from kanban.drivers.jira import SelfApproveRefused

    driver = get_driver(data, p.parent)
    kwargs: dict[str, Any] = {}
    if args.reason:
        kwargs["reason"] = args.reason
    try:
        t = driver.transition(args.key, args.to, **kwargs)
    except SelfApproveRefused as e:
        _fail(str(e), code=2, kind="self-approve")
        return 2
    except Exception as e:  # noqa: BLE001
        _fail(f"{type(e).__name__}: {e}")
        return 1
    _emit({"ok": True, "key": t.id, "column": t.column, "raw_status": t.custom.get("raw_status")})
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

    s = sub.add_parser("find-ap-field")
    s.set_defaults(func=cmd_find_ap_field)

    s = sub.add_parser("create-ap-field")
    s.add_argument("--name", default="Claude Agent")
    s.set_defaults(func=cmd_create_ap_field)

    s = sub.add_parser("set-ap-field")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--field-id", required=True)
    s.add_argument("--field-name", required=True)
    s.set_defaults(func=cmd_set_ap_field)

    s = sub.add_parser("register-ap")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--name", required=True)
    s.add_argument(
        "--force",
        action="store_true",
        help="acknowledge fuzzy-similar names and proceed with registration",
    )
    s.set_defaults(func=cmd_register_ap)

    s = sub.add_parser("assign-ap")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--name", required=True)
    s.set_defaults(func=cmd_assign_ap)

    s = sub.add_parser("read-agent-ap")
    s.add_argument("--kanban-path", required=True)
    s.set_defaults(func=cmd_read_agent_ap)

    s = sub.add_parser("claim-next")
    s.add_argument("--kanban-path", required=True)
    s.set_defaults(func=cmd_claim_next)

    s = sub.add_parser("transition")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--key", required=True)
    s.add_argument("--to", required=True, choices=("TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"))
    s.add_argument("--reason")
    s.set_defaults(func=cmd_transition)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
