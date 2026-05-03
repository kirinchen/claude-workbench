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
import os
import re
import sys
from pathlib import Path
from typing import Any

# Plugin layout: scripts/ is a sibling of lib/ and drivers/. Adding the
# plugin root (the directory containing lib/ and drivers/) to sys.path lets
# us use absolute imports `from lib import …` and `from drivers import …`,
# which works under both:
#   1. Source layout:           plugins/kanban/scripts/jira_setup.py
#   2. Marketplace install:     <cache>/<repo>/kanban/<version>/scripts/jira_setup.py
# In both cases `parents[1]` resolves to the directory holding lib/ + drivers/.
HERE = Path(__file__).resolve()
PLUGIN_ROOT = HERE.parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import ap_registry, card_cache, credentials, kanban_io  # noqa: E402
from lib import conventions as _cv  # noqa: E402
from lib import mcp_conflict_scan, transitions as _tr  # noqa: E402
from lib.jira_client import JiraClient, JiraError, adf_extract_mentions  # noqa: E402


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


def _read_token(*, prompt: bool = False) -> str:
    """Read the Jira API token. Default path is stdin (caller pipes the
    token in — used by automation / CI). When `prompt=True`, the token
    is captured interactively via `getpass.getpass`, which:

      - reads from /dev/tty (or the platform equivalent) directly,
      - never echoes typed characters to the terminal,
      - never enters argv, stdin, or any caller's process tree.

    The prompt path is the secret-safe way to capture a token in a
    Claude-Code-style flow: the agent prints the command for the user
    to run in their *own* terminal (NOT through the agent's Bash tool),
    so the token literal never appears in the conversation log. See
    SPEC §10 / the 0.3.18 changelog entry for the full rationale.
    """
    if prompt:
        import getpass
        try:
            return getpass.getpass("Jira API token: ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.stderr.write("\nerror: token prompt aborted\n")
            sys.exit(2)
    if sys.stdin.isatty():
        sys.stderr.write(
            "error: token expected on stdin "
            "(or use --prompt-token to enter it interactively)\n"
        )
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


def _client_from_env_or_none() -> JiraClient | None:
    """Non-fatal variant: return None if credentials are missing, instead of
    exiting the process. Callers that can fall back to a local hint use this.
    """
    env = credentials.read("JIRA_")
    base = env.get("JIRA_BASE_URL")
    email = env.get("JIRA_AGENT_EMAIL")
    tok = env.get("JIRA_API_TOKEN")
    if not (base and email and tok):
        return None
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
    token = _read_token(prompt=getattr(args, "prompt_token", False))
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
    token = _read_token(prompt=getattr(args, "prompt_token", False))
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
    if getattr(args, "from_env", False):
        # Read token from `~/.claude-workbench/.env` (where step 1's
        # store-credentials wrote it). Avoids agents having to pipe the
        # token through stdin during initjira's step 2 — see #42.
        env = credentials.read("JIRA_")
        token = env.get("JIRA_API_TOKEN", "")
        if not token:
            _fail(
                "no JIRA_API_TOKEN in ~/.claude-workbench/.env — "
                "run /kanban:reset-credentials first",
            )
            return 1
    else:
        token = _read_token(prompt=getattr(args, "prompt_token", False))
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

    # Delegate to lib.transitions which understands non-English names (via
    # statusCategory) and ambiguity tracking.
    sugg = _tr.suggest_from_jira(found)
    _emit(
        {
            "found": found,
            "suggestions": sugg.suggestions,
            "unmapped": sugg.unmapped,
            "ambiguous": sugg.ambiguous,
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
    # Run any legacy fields through the migrator so callers can hand us either
    # v0.2 (statusMap+labelFallback) or v0.3 (transitions) shape.
    cfg = _tr.migrate_legacy(cfg)
    data["backend"] = {"driver": "jira", "jira": cfg}
    # Adjust columns metadata to match SPEC: jira mode permits all 6.
    meta = data.setdefault("meta", {})
    meta["columns"] = list(CANONICAL_COLUMNS)
    kanban_io.save(p, data)

    _emit({"ok": True, "version": data.get("version", "0.2")})
    return 0


def cmd_parse_transitions_dsl(args: argparse.Namespace) -> int:
    """Parse a DSL block into a backend.jira.transitions dict.

    DSL grammar (per line):
        CANONICAL > status [+ Label[ name]] [+ Assignee to me|<displayName>]

    Input is taken from --dsl-text only. We deliberately do NOT accept a
    file path: the parser's error messages would otherwise reflect file
    line content back into the slash-command transcript, which would leak
    secrets if the path were ever pointed at a token / credential file.
    """
    text = args.dsl_text
    if not text:
        return _fail("DSL is empty (pass --dsl-text)")

    user_lookup = None
    if not args.no_user_lookup:
        # Make /user/search available so 'Assignee to <displayName>' resolves.
        try:
            client = _client_from_env()
        except SystemExit:
            client = None  # _client_from_env _fail-exited; user_lookup unavailable
        if client is not None:
            def lookup(name: str) -> str | None:
                try:
                    res = client._request(
                        "GET", "/rest/api/3/user/search", query={"query": name}
                    )
                except JiraError:
                    return None
                if isinstance(res, list) and res:
                    return (res[0] or {}).get("accountId")
                return None
            user_lookup = lookup

    try:
        out = _tr.parse_dsl(
            text,
            current_user_account_id=args.current_user_account_id,
            user_lookup=user_lookup,
        )
    except ValueError as e:
        return _fail(str(e))
    _emit({"ok": True, "transitions": out})
    return 0


def cmd_set_transitions(args: argparse.Namespace) -> int:
    """Persist `backend.jira.transitions` to kanban.json."""
    p = Path(args.kanban_path)
    if not p.exists():
        return _fail(f"kanban.json not found at {p}")
    transitions = json.loads(args.transitions_json)
    if not isinstance(transitions, dict):
        return _fail("--transitions-json must be a JSON object")

    data = kanban_io.load(p)
    backend = data.setdefault("backend", {"driver": "jira"})
    if backend.get("driver") != "jira":
        return _fail("backend.driver must be 'jira'")
    jira_cfg = backend.setdefault("jira", {})
    # Drop any legacy fields — transitions supersedes them.
    for k in ("statusMap", "labelFallback", "partial"):
        jira_cfg.pop(k, None)

    available = []
    if args.available_statuses:
        available = json.loads(args.available_statuses)
    errs = _tr.validate(transitions, available)
    if errs and not args.force:
        return _fail(
            "validation failed; pass --force to write anyway",
            errors=errs,
        )

    jira_cfg["transitions"] = transitions
    kanban_io.save(p, data)
    _emit({"ok": True, "transitions": transitions, "warnings": errs})
    return 0


def cmd_list_tasks(args: argparse.Namespace) -> int:
    p = Path(args.kanban_path)
    if not p.exists():
        _fail(f"kanban.json not found at {p}")
        return 1
    data = kanban_io.load(p)
    from drivers import get_driver
    from drivers.base import TaskFilter

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


def _candidate_screens(
    client: JiraClient, project_key: str
) -> list[dict[str, Any]]:
    """Return screens likely to need the AP field.

    Strategy:
    1. Query screens whose name contains the project key (Jira's
       project-scoped screens conventionally embed the key in the name,
       e.g. "DMI: Kanban Default Issue Screen").
    2. Always include the default screen (id=1) as a global fallback.
    3. Dedupe by id.
    """
    screens: dict[int, dict[str, Any]] = {}
    try:
        listing = client.list_screens(query=project_key) or {}
        for s in listing.get("values") or []:
            sid = s.get("id")
            if isinstance(sid, int):
                screens[sid] = s
    except JiraError:
        pass
    # Default screen — almost always present, used by simple project schemes.
    screens.setdefault(
        1, {"id": 1, "name": "Default Screen", "_default_fallback": True}
    )
    return list(screens.values())


def _associate_field_with_screens(
    client: JiraClient, field_id: str, project_key: str
) -> dict[str, Any]:
    """Attach `field_id` to the first tab of every candidate screen.

    Returns:
        {
          "attempted": [...screens tried...],
          "attached":  [...succeeded or already-present...],
          "denied":    [...403s — admin needed...],
          "errors":    [...other failures...],
        }
    """
    out: dict[str, Any] = {
        "attempted": [],
        "attached": [],
        "denied": [],
        "errors": [],
    }
    for screen in _candidate_screens(client, project_key):
        sid = screen.get("id")
        sname = screen.get("name", "")
        out["attempted"].append({"id": sid, "name": sname})
        try:
            tabs = client.list_screen_tabs(sid) or []
        except JiraError as e:
            if e.status_code in (403, 404):
                # 404 on the default screen is not unusual — some workflow
                # schemes don't share screen 1 with the project.
                if e.status_code == 403:
                    out["denied"].append({"id": sid, "name": sname, "phase": "list_tabs"})
                else:
                    out["errors"].append({"id": sid, "name": sname,
                                          "phase": "list_tabs", "detail": e.detail or str(e)})
                continue
            out["errors"].append(
                {"id": sid, "name": sname, "phase": "list_tabs",
                 "detail": e.detail or str(e), "status": e.status_code}
            )
            continue
        if not tabs:
            out["errors"].append({"id": sid, "name": sname,
                                  "phase": "list_tabs", "detail": "no tabs"})
            continue
        tab = tabs[0]
        tid = tab.get("id")

        # Idempotency: skip if the field is already on this tab.
        try:
            existing = client.list_screen_tab_fields(sid, tid) or []
            if any((f or {}).get("id") == field_id for f in existing):
                out["attached"].append({"id": sid, "name": sname,
                                        "tab": tab.get("name", ""),
                                        "alreadyPresent": True})
                continue
        except JiraError:
            pass  # if listing fields fails, fall through to add and let it 200/error

        try:
            client.add_field_to_screen_tab(sid, tid, field_id)
            out["attached"].append({"id": sid, "name": sname,
                                    "tab": tab.get("name", "")})
        except JiraError as e:
            if e.status_code == 403:
                out["denied"].append({"id": sid, "name": sname, "phase": "add_field"})
            else:
                out["errors"].append(
                    {"id": sid, "name": sname, "phase": "add_field",
                     "detail": e.detail or str(e), "status": e.status_code}
                )
    return out


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

    field_id = result.get("id")
    field_name = result.get("name")

    # Fixes #6: a freshly-created custom field is not on any screen, so
    # `customfield_X cannot be set` for create/edit. Attach to project
    # screens immediately. Best-effort — admin perms may be needed; if
    # any individual screen association fails the user can run
    # /kanban:fix-ap-screen manually.
    screens_summary: dict[str, Any] | None = None
    if field_id and args.project:
        try:
            screens_summary = _associate_field_with_screens(
                client, field_id, args.project
            )
        except Exception as e:  # noqa: BLE001 — last-resort net catch
            screens_summary = {"error": f"{type(e).__name__}: {e}"}

    _emit(
        {
            "ok": True,
            "fieldId": field_id,
            "fieldName": field_name,
            "screens": screens_summary,
        }
    )
    return 0


def cmd_associate_ap_field_screens(args: argparse.Namespace) -> int:
    """Re-run screen association for an existing AP field.

    Useful when /kanban:initjira ran on 0.3.1 (which didn't associate
    screens) or when the user adds new project-scoped screens later.
    """
    p = Path(args.kanban_path)
    if not p.exists():
        return _fail(f"kanban.json not found at {p}")
    data = kanban_io.load(p)
    backend = data.get("backend") or {}
    if backend.get("driver") != "jira":
        return _fail("backend.driver must be 'jira'")
    cfg = backend.get("jira") or {}
    project_key = cfg.get("projectKey")
    field_id = ((cfg.get("ap") or {}).get("fieldId"))
    if not project_key or not field_id:
        return _fail(
            "kanban.json is missing projectKey or backend.jira.ap.fieldId — "
            "run /kanban:initjira first"
        )
    client = _client_from_env()
    summary = _associate_field_with_screens(client, field_id, project_key)
    _emit({"ok": True, "fieldId": field_id, "screens": summary})
    return 0


def cmd_verify_ap_field_screens(args: argparse.Namespace) -> int:
    """Report which candidate screens currently carry the AP field.

    Read-only. Returns:
        {
          "ok": true,
          "fieldId": "customfield_X",
          "present": [{id, name}, ...],
          "missing": [{id, name}, ...],
        }
    """
    p = Path(args.kanban_path)
    if not p.exists():
        return _fail(f"kanban.json not found at {p}")
    data = kanban_io.load(p)
    backend = data.get("backend") or {}
    if backend.get("driver") != "jira":
        return _fail("backend.driver must be 'jira'")
    cfg = backend.get("jira") or {}
    project_key = cfg.get("projectKey")
    field_id = ((cfg.get("ap") or {}).get("fieldId"))
    if not project_key or not field_id:
        return _fail("kanban.json is missing projectKey or ap.fieldId")
    client = _client_from_env()

    present: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for screen in _candidate_screens(client, project_key):
        sid, sname = screen.get("id"), screen.get("name", "")
        try:
            tabs = client.list_screen_tabs(sid) or []
        except JiraError:
            missing.append({"id": sid, "name": sname, "reason": "tabs unreachable"})
            continue
        found = False
        for tab in tabs:
            try:
                fields = client.list_screen_tab_fields(sid, tab.get("id")) or []
            except JiraError:
                continue
            if any((f or {}).get("id") == field_id for f in fields):
                found = True
                break
        if found:
            present.append({"id": sid, "name": sname})
        else:
            missing.append({"id": sid, "name": sname})

    _emit({"ok": True, "fieldId": field_id, "present": present, "missing": missing})
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


def _fetch_jira_ap_options(client: JiraClient, field_id: str) -> list[str]:
    """Return the live list of AP custom-field option values from Jira.

    Source of truth for AP membership lives on the Jira side (the field's
    options list). The local `kanban.json#registered` is just a stale hint.
    Callers should use this for validation; on network failure they may fall
    back to the local list with a warning.
    """
    try:
        ctx_id = _resolve_default_context(client, field_id)
    except Exception:
        return []
    payload = client.list_field_options(field_id, ctx_id) or {}
    out: list[str] = []
    for opt in payload.get("values", []) or []:
        v = opt.get("value")
        if isinstance(v, str) and v:
            out.append(v)
    return out


def cmd_live_list_aps(args: argparse.Namespace) -> int:
    """Live-query Jira for the AP field's current options. Used by
    /kanban:whoami and /kanban:assign-ap as the source of truth (the local
    cached `registered` list is informational only).
    """
    p = Path(args.kanban_path)
    if not p.exists():
        return _fail(f"kanban.json not found at {p}")
    data = kanban_io.load(p)
    backend = data.get("backend") or {}
    if backend.get("driver") != "jira":
        return _fail("backend.driver must be 'jira'")
    field_id = ((backend.get("jira") or {}).get("ap") or {}).get("fieldId")
    if not field_id:
        return _fail("AP field unconfigured — run /kanban:initjira step 4")

    client = _client_from_env()
    try:
        live = _fetch_jira_ap_options(client, field_id)
    except JiraError as e:
        # Best-effort fall back to the local hint list.
        local = list(((backend.get("jira") or {}).get("ap") or {}).get("registered") or [])
        _emit(
            {
                "ok": False,
                "error": f"jira: {e.detail or e}",
                "statusCode": e.status_code,
                "fallback": local,
            }
        )
        return 1
    _emit({"ok": True, "registered": live, "fieldId": field_id})
    return 0


# --- doc-link resolution (kanban × mentor integration, SPEC §13) -------


_GITHUB_HTTPS_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?/?$"
)
_GITHUB_SSH_RE = re.compile(
    r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?$"
)


def _parse_github_origin(origin: str) -> tuple[str, str] | None:
    """Return (owner, repo) when `origin` is a GitHub URL, else None."""
    if not origin:
        return None
    for rx in (_GITHUB_HTTPS_RE, _GITHUB_SSH_RE):
        m = rx.match(origin.strip())
        if m:
            return m.group("owner"), m.group("repo")
    return None


def _git_origin(repo_root: Path) -> str:
    """Return `git remote get-url origin` from repo_root, or '' on error."""
    import subprocess
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return ""
    if out.returncode != 0:
        return ""
    return (out.stdout or "").strip()


def _git_current_branch(repo_root: Path) -> str:
    """Return current git branch from repo_root, or '' on error."""
    import subprocess
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "branch", "--show-current"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return ""
    if out.returncode != 0:
        return ""
    return (out.stdout or "").strip()


def cmd_resolve_doc_link(args: argparse.Namespace) -> int:
    """Resolve a repo-relative doc path to a clickable GitHub URL.

    Used when posting Jira comments that reference repo docs (mentor's
    Epic / Sprint / Issue / ADR docs in particular). Without this, the
    agent would write "see epic/AGENT-001-foo.md" — not clickable in
    Jira; the human has to navigate to GitHub manually.

    Detects host from `git remote get-url origin`. Only GitHub
    (`github.com`) is supported in this version; other hosts return
    `ok=false` so the LLM can fall back to a relative path with an
    explanation.
    """
    repo_root = Path(args.kanban_path).parent.resolve()
    origin = _git_origin(repo_root)
    if not origin:
        return _fail(
            "no git origin — repo must be cloned from a remote for "
            "links to resolve"
        )

    parsed = _parse_github_origin(origin)
    if parsed is None:
        return _fail(
            f"only github.com origins are supported (got origin={origin!r}); "
            "fall back to a relative path or paste the URL manually",
            host="other",
            origin=origin,
        )
    owner, repo = parsed

    # Strip any leading `/` or `./`; reject `..` to avoid traversal-style
    # URLs even though GitHub itself would 404 them.
    doc = (args.doc_path or "").strip().lstrip("./").lstrip("/")
    if not doc:
        return _fail("--doc-path is required and must be non-empty")
    if ".." in doc.split("/"):
        return _fail("--doc-path cannot contain '..' segments")

    # Branch resolution: explicit > current > "main"
    branch = (args.branch or _git_current_branch(repo_root) or "main").strip()
    # /blob/ renders markdown nicely in browser; /raw/ would serve plain text.
    url = f"https://github.com/{owner}/{repo}/blob/{branch}/{doc}"

    file_path = repo_root / doc
    exists = file_path.is_file()

    _emit({
        "ok": True,
        "url": url,
        "exists": exists,
        "branch": branch,
        "host": "github",
        "owner": owner,
        "repo": repo,
        "docPath": doc,
    })
    return 0


def cmd_emit_jira_code(args: argparse.Namespace) -> int:
    """Print the shareable backend.jira block as compact JSON.

    Strips per-machine / per-repo specifics (`registered` AP roster,
    `agentAccountId` if --include-agent-account is not set). The output is
    safe to share via Slack / wiki / pasted into another machine's
    /kanban:initjira-by-code.
    """
    p = Path(args.kanban_path)
    if not p.exists():
        return _fail(f"kanban.json not found at {p}")
    data = kanban_io.load(p)
    backend = data.get("backend") or {}
    if backend.get("driver") != "jira":
        return _fail("backend.driver must be 'jira'")
    cfg = dict(backend.get("jira") or {})
    if not cfg.get("transitions"):
        return _fail("no transitions defined — run /kanban:initjira first")

    code: dict[str, Any] = {
        "schema": "kanban-jira-code/2",
        "boardUrl": cfg.get("boardUrl"),
        "boardId": cfg.get("boardId"),
        "projectKey": cfg.get("projectKey"),
        "transitions": cfg.get("transitions"),
    }
    if args.include_agent_account and cfg.get("agentAccountId"):
        code["agentAccountId"] = cfg["agentAccountId"]
    ap = cfg.get("ap") or {}
    if ap.get("fieldId"):
        code["ap"] = {"fieldId": ap["fieldId"], "fieldName": ap.get("fieldName", "")}
        # `registered` deliberately omitted — that's live state on Jira.
    # Always include the conventions block (empty by default — the slot
    # itself nudges teams to write their rules down). v1 receivers ignore it.
    code["conventions"] = _cv.normalize(cfg.get("conventions"))

    _emit({"ok": True, "code": code})
    return 0


def cmd_import_jira_code(args: argparse.Namespace) -> int:
    """Import a shareable code into this repo's kanban.json."""
    p = Path(args.kanban_path)
    if not p.exists():
        return _fail(f"kanban.json not found at {p}")
    try:
        code = json.loads(args.code_json)
    except json.JSONDecodeError as e:
        return _fail(f"code is not valid JSON: {e}")
    if not isinstance(code, dict):
        return _fail("code must be a JSON object")
    schema = code.get("schema")
    if schema not in ("kanban-jira-code/1", "kanban-jira-code/2"):
        return _fail(
            f"unsupported code schema {schema!r}; "
            "expected kanban-jira-code/1 or /2"
        )

    transitions = code.get("transitions")
    if not isinstance(transitions, dict) or not transitions:
        return _fail("code is missing `transitions`")
    errs = _tr.validate(transitions)
    if errs:
        return _fail("transitions invalid", errors=errs)

    project_key = code.get("projectKey")
    board_id = code.get("boardId")
    if not project_key or not isinstance(board_id, int):
        return _fail("code is missing `projectKey` or `boardId`")

    # Build the new backend.jira. Pull agentAccountId from the existing
    # kanban.json if not present in the code (the agentAccountId is shared
    # per-Atlassian-account, not per-board, but a fresh repo may already
    # have it from /kanban:initjira-by-code's credential step).
    data = kanban_io.load(p)
    existing_cfg = (data.get("backend") or {}).get("jira") or {}
    cfg: dict[str, Any] = {
        "boardUrl": code.get("boardUrl") or existing_cfg.get("boardUrl"),
        "boardId": board_id,
        "projectKey": project_key,
        "agentAccountId": code.get("agentAccountId") or existing_cfg.get("agentAccountId"),
        "transitions": transitions,
    }
    if code.get("ap") and isinstance(code["ap"], dict) and code["ap"].get("fieldId"):
        cfg["ap"] = {
            "fieldId": code["ap"]["fieldId"],
            "fieldName": code["ap"].get("fieldName", ""),
            "registered": [],   # populated live via cmd_live_list_aps when needed
        }
    # Conventions arrive only on /2 codes. Normalize so unknown future
    # fields are dropped and `notes` is always a list.
    incoming_conv = code.get("conventions") if schema == "kanban-jira-code/2" else None
    cfg["conventions"] = _cv.normalize(incoming_conv)
    cfg = {k: v for k, v in cfg.items() if v is not None}

    data["backend"] = {"driver": "jira", "jira": cfg}
    meta = data.setdefault("meta", {})
    meta["columns"] = list(CANONICAL_COLUMNS)
    kanban_io.save(p, data)
    _emit({
        "ok": True,
        "imported": cfg,
        "schema": schema,
        "conventions": cfg["conventions"],
        "ackRequired": not _cv.is_empty(cfg["conventions"])
                       and not _cv.has_recent_ack(p.parent, cfg["conventions"]),
    })
    return 0


def cmd_set_conventions(args: argparse.Namespace) -> int:
    """Persist `backend.jira.conventions` to kanban.json.

    Two modes (mutually exclusive):

      Full replace — `--conventions-json '{"notes": [...], ...}'`. The
      block is replaced wholesale.

      Incremental — `--append-note`, `--remove-note`, `--set-toggle
      KEY=VAL`. The existing block is loaded, the requested mutations
      applied (append is idempotent: exact-text dups skipped), then
      saved. Useful for slash commands that want to add a single rule
      without faithfully reproducing the rest (which an LLM might
      paraphrase on round-trip — exactly the kind of subtle drift that
      causes "why did this rule disappear" mysteries). See #36.

    Validation is advisory — guardrails surface as `warnings`, never
    block the write.
    """
    p = Path(args.kanban_path)
    if not p.exists():
        return _fail(f"kanban.json not found at {p}")

    incremental = bool(
        args.append_note or args.remove_note or args.set_toggle
    )
    if args.conventions_json and incremental:
        return _fail(
            "--conventions-json cannot be combined with --append-note / "
            "--remove-note / --set-toggle (full replace vs. incremental "
            "mutate are different modes — pick one)"
        )
    if not args.conventions_json and not incremental:
        return _fail(
            "set-conventions requires either --conventions-json (full "
            "replace) or one of --append-note / --remove-note / "
            "--set-toggle (incremental mutate)"
        )

    data = kanban_io.load(p)
    backend = data.setdefault("backend", {"driver": "jira"})
    if backend.get("driver") != "jira":
        return _fail("backend.driver must be 'jira'")
    jira_cfg = backend.setdefault("jira", {})

    if args.conventions_json:
        try:
            incoming = json.loads(args.conventions_json)
        except json.JSONDecodeError as e:
            return _fail(f"--conventions-json is not valid JSON: {e}")
        if not isinstance(incoming, dict):
            return _fail("--conventions-json must be a JSON object")
    else:
        # Incremental: start from the current normalized block, mutate.
        incoming = dict(_cv.normalize(jira_cfg.get("conventions")))
        notes = list(incoming.get("notes") or [])
        # Append (idempotent — skip exact-text duplicates)
        for n in args.append_note:
            if n not in notes:
                notes.append(n)
        # Remove (no-op if absent)
        if args.remove_note:
            removeset = set(args.remove_note)
            notes = [n for n in notes if n not in removeset]
        incoming["notes"] = notes
        # Toggles (KEY=VAL; boolean detection is case-insensitive)
        for spec in args.set_toggle:
            if "=" not in spec:
                return _fail(
                    f"--set-toggle expects KEY=VALUE form, got {spec!r}"
                )
            k, _, v = spec.partition("=")
            if v.lower() in ("true", "false"):
                incoming[k] = (v.lower() == "true")
            else:
                incoming[k] = v

    normalized = _cv.normalize(incoming)
    warnings = _cv.validate(normalized)
    jira_cfg["conventions"] = normalized
    kanban_io.save(p, data)
    _emit({"ok": True, "conventions": normalized, "warnings": warnings})
    return 0


def cmd_read_conventions(args: argparse.Namespace) -> int:
    """Read backend.jira.conventions from kanban.json. Includes `ackHash`
    so callers can decide whether to re-prompt.
    """
    p = Path(args.kanban_path)
    if not p.exists():
        return _fail(f"kanban.json not found at {p}")
    data = kanban_io.load(p)
    cfg = (data.get("backend") or {}).get("jira") or {}
    norm = _cv.normalize(cfg.get("conventions"))
    _emit(
        {
            "ok": True,
            "conventions": norm,
            "isEmpty": _cv.is_empty(norm),
            "ackHash": _cv.hash_conventions(norm),
            "alreadyAcked": _cv.has_recent_ack(p.parent, norm),
        }
    )
    return 0


def cmd_record_conventions_ack(args: argparse.Namespace) -> int:
    """Record that the user has acknowledged the current conventions.

    Reads conventions from kanban.json so the slash command can't pass
    a forged ack for a different convention set.
    """
    p = Path(args.kanban_path)
    if not p.exists():
        return _fail(f"kanban.json not found at {p}")
    data = kanban_io.load(p)
    cfg = (data.get("backend") or {}).get("jira") or {}
    norm = _cv.normalize(cfg.get("conventions"))
    target = _cv.record_ack(p.parent, norm)
    _emit({"ok": True, "ackHash": _cv.hash_conventions(norm), "path": str(target)})
    return 0


def _read_kanban_agent_field(p: Path, field: str) -> Any:
    """Read a top-level field from .claude/kanban-agent.json next to `p`.
    Returns None if file missing / unparseable / field absent.
    """
    target = p.parent / ".claude" / "kanban-agent.json"
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data.get(field)


def _write_kanban_agent_field(p: Path, field: str, value: Any) -> Path:
    """Set a top-level field in .claude/kanban-agent.json, preserving the
    rest of the file. Used for `lastMentionSeenAt` advancement.
    """
    target = p.parent / ".claude" / "kanban-agent.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
    else:
        data = {}
    data[field] = value
    target.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def cmd_find_mentions(args: argparse.Namespace) -> int:
    """List Jira comments / descriptions that @-mention the agent account
    since `--since` (defaults to .claude/kanban-agent.json#lastMentionSeenAt).

    Strategy:
      1. JQL: project=<KEY> AND updated >= "<since>" — bounded candidates
      2. For each issue, fetch description + comments
      3. Walk ADF for mention nodes whose accountId == agentAccountId
      4. Filter out self-mentions (author == agentAccountId — bot
         mentioning itself in its own comment doesn't count)
    """
    p = Path(args.kanban_path)
    if not p.exists():
        return _fail(f"kanban.json not found at {p}")
    data = kanban_io.load(p)
    backend = data.get("backend") or {}
    if backend.get("driver") != "jira":
        return _fail("backend.driver must be 'jira'")
    jcfg = backend.get("jira") or {}
    project_key = jcfg.get("projectKey")
    agent_acct = jcfg.get("agentAccountId")
    if not project_key or not agent_acct:
        return _fail(
            "kanban.json missing projectKey or agentAccountId — "
            "run /kanban:initjira first"
        )

    since = args.since or _read_kanban_agent_field(p, "lastMentionSeenAt")
    if not since:
        # First run — surface only "very recent" stuff (last 1d). Avoids
        # surfacing every old comment ever.
        from datetime import datetime, timedelta, timezone
        since = (
            datetime.now(timezone.utc).astimezone() - timedelta(days=1)
        ).isoformat(timespec="seconds")

    client = _client_from_env()
    # JQL: bounded candidate set. The `text ~ "[~accountId]"` operator is
    # unreliable across Jira Cloud configurations, so we filter only by
    # `updated` and walk the ADF ourselves to verify the mention.
    jql = f'project = "{project_key}" AND updated >= "{_jql_quote_ts(since)}"'
    try:
        resp = client.search_jql(jql, fields=["updated"], max_results=100)
    except JiraError as e:
        return _fail(f"jira: {e.detail or e}", statusCode=e.status_code)

    issues = (resp or {}).get("issues", []) or []
    mentions: list[dict[str, Any]] = []
    latest_seen = since

    for issue in issues:
        key = issue.get("key", "")
        # Pull description + comments in one fetch.
        try:
            full = client.get_issue(key, fields=["description", "comment", "updated"])
        except JiraError:
            continue
        f = full.get("fields") or {}
        upd = f.get("updated") or ""
        if upd > latest_seen:
            latest_seen = upd

        # Description mentions
        desc = f.get("description")
        for m in adf_extract_mentions(desc, target_account_id=agent_acct):
            mentions.append({
                "key": key,
                "location": "description",
                "ts": f.get("created") or upd,
                "author": "(unknown)",  # description authorship isn't a
                                        # straightforward field in Jira
                "text": m.get("text", ""),
            })

        # Comment mentions
        comments = ((f.get("comment") or {}).get("comments")) or []
        for c in comments:
            cts = c.get("created") or ""
            if since and cts < since:
                # Older than the since cutoff — already seen
                continue
            author = (c.get("author") or {}).get("accountId")
            # Skip self-mentions (the bot mentioning itself in a comment
            # it authored).
            if author == agent_acct:
                continue
            body_adf = c.get("body")
            for m in adf_extract_mentions(body_adf, target_account_id=agent_acct):
                mentions.append({
                    "key": key,
                    "location": "comment",
                    "commentId": c.get("id"),
                    "ts": cts,
                    "author": (c.get("author") or {}).get("displayName") or "?",
                    "authorAccountId": author,
                    "text": m.get("text", ""),
                })
                break  # one record per comment, even if multi-mentioned

    _emit({
        "ok": True,
        "since": since,
        "latestSeen": latest_seen,
        "mentions": mentions,
        "agentAccountId": agent_acct,
    })
    return 0


def _jql_quote_ts(ts: str) -> str:
    """Format a timestamp for safe inclusion in a JQL string literal.

    Jira JQL accepts `yyyy-MM-dd HH:mm`, `yyyy/MM/dd HH:mm`, and the
    date-only forms. It silently rejects full ISO-8601 with a timezone
    offset (e.g. `2026-05-02T11:44:37+08:00`) — query returns 0 results
    with no error (#26). When the input parses as ISO-8601, normalize to
    `yyyy-MM-dd HH:mm` (Jira interprets the bare timestamp in the project's
    configured zone, which is what callers want for "recent activity"
    queries). Otherwise pass through (already canonical short form).
    """
    if '"' in ts:
        raise ValueError(f"invalid timestamp {ts!r}")
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return ts  # already canonical (yyyy-MM-dd or yyyy/MM/dd HH:mm)
    return dt.strftime("%Y-%m-%d %H:%M")


def cmd_mark_mentions_read(args: argparse.Namespace) -> int:
    """Advance `.claude/kanban-agent.json#lastMentionSeenAt`. Idempotent;
    refuses to move the timestamp backwards.
    """
    p = Path(args.kanban_path)
    if not p.exists():
        return _fail(f"kanban.json not found at {p}")
    until = args.until or _now_iso()
    current = _read_kanban_agent_field(p, "lastMentionSeenAt") or ""
    if current and until < current:
        _emit({
            "ok": True,
            "advanced": False,
            "lastMentionSeenAt": current,
            "reason": "given timestamp is older than current — no-op",
        })
        return 0
    target = _write_kanban_agent_field(p, "lastMentionSeenAt", until)
    _emit({"ok": True, "advanced": True, "lastMentionSeenAt": until, "path": str(target)})
    return 0


def cmd_post_reply(args: argparse.Namespace) -> int:
    """Post a comment on an issue, optionally @-mentioning a recipient.

    --to-account-id and --display-name come from the surfaced mention's
    `authorAccountId` and `author` fields, so the reply notifies the
    person who originally pinged the bot.
    """
    p = Path(args.kanban_path)
    if not p.exists():
        return _fail(f"kanban.json not found at {p}")
    data = kanban_io.load(p)
    from drivers import get_driver
    from drivers.base import CommentKind

    driver = get_driver(data, p.parent)
    try:
        c = driver.post_comment(
            args.key,
            args.body,
            kind=CommentKind.COMMENT,
            mention_account_id=args.to_account_id,
            mention_display=args.display_name,
        )
    except Exception as e:  # noqa: BLE001
        return _fail(f"{type(e).__name__}: {e}")
    _emit({
        "ok": True,
        "key": args.key,
        "ts": c.ts,
        "mentioned": args.to_account_id,
    })
    return 0


def cmd_create_sub(args: argparse.Namespace) -> int:
    """Create N sub-cards linked back to a parent via `Relates`.

    Each sub-card inherits the parent's project (via driver) and is
    optionally tagged with the current repo's AP so /kanban:next picks
    them up.
    """
    p = Path(args.kanban_path)
    if not p.exists():
        return _fail(f"kanban.json not found at {p}")
    data = kanban_io.load(p)
    from drivers import get_driver
    from drivers.base import AgentRef, TaskInput

    driver = get_driver(data, p.parent)
    repo_ap = _read_repo_ap(p)
    if not args.titles:
        return _fail("at least one --title is required")

    created: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for title in args.titles:
        try:
            t = driver.create_task(TaskInput(
                title=title,
                description=args.description or "",
                priority=args.priority,
                parent_key=args.parent,
                link_type=args.link_type,
            ))
        except Exception as e:  # noqa: BLE001
            failed.append({"title": title, "error": f"{type(e).__name__}: {e}"})
            continue
        # Best-effort: assign the new sub-card to this repo's AP so the
        # claiming agent picks it up via /kanban:next.
        if repo_ap:
            try:
                driver.assign(t.id, AgentRef(ap=repo_ap))
            except Exception:
                pass  # surfaced via final read; non-fatal
        created.append({"key": t.id, "title": t.title})

    _emit({
        "ok": True,
        "parent": args.parent,
        "linkType": args.link_type,
        "created": created,
        "failed": failed,
    })
    return 0


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

    # Live-query Jira's options as the source of truth for collision detection.
    # Falls back to the local hint list if creds are missing or the network is down.
    live_options = list(ap_block.get("registered") or [])
    client = _client_from_env_or_none()
    if client is not None:
        try:
            live_options = _fetch_jira_ap_options(client, field_id)
        except JiraError:
            pass  # keep local fallback

    if ap_registry.is_exact_collision(args.name, live_options):
        _emit({"ok": True, "alreadyRegistered": True, "name": args.name})
        return 0

    hits = ap_registry.fuzzy_collisions(args.name, live_options)
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

    if client is None:
        # We did the fuzzy/collision check against local data, but the
        # actual write requires Jira. Fail explicitly so the user knows
        # to run /kanban:reset-credentials.
        return _fail(
            "Jira credentials missing — fuzzy check passed against local "
            "hint, but the new option must be added in Jira. Run "
            "/kanban:initjira or /kanban:reset-credentials first."
        )
    try:
        ctx_id = _resolve_default_context(client, field_id)
        client.add_field_option(field_id, ctx_id, args.name)
    except JiraError as e:
        _fail(f"jira: {e.detail or e}", statusCode=e.status_code)
        return 1

    # Update the local hint list (read-only mirror of Jira's options).
    registered = list(ap_block.get("registered") or [])
    if args.name not in registered:
        registered.append(args.name)
    ap_block["registered"] = registered
    jira_cfg["ap"] = ap_block
    backend["jira"] = jira_cfg
    data["backend"] = backend
    kanban_io.save(p, data)

    _emit({
        "ok": True,
        "name": args.name,
        "registered": registered,
    })
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
    field_id = ((backend.get("jira") or {}).get("ap") or {}).get("fieldId")
    if not field_id:
        _fail("AP field unconfigured — run /kanban:initjira step 4")
        return 1

    # Live-query Jira options as the source of truth. The local
    # `registered` list is a stale hint and must not be relied on for
    # access control — a sibling repo on another machine may have
    # registered new APs since this kanban.json was last touched.
    fallback_used = False
    client = _client_from_env_or_none()
    if client is None:
        live_options = list(((backend.get("jira") or {}).get("ap") or {}).get("registered") or [])
        fallback_used = True
    else:
        try:
            live_options = _fetch_jira_ap_options(client, field_id)
        except JiraError as e:
            live_options = list(((backend.get("jira") or {}).get("ap") or {}).get("registered") or [])
            fallback_used = True
            sys.stderr.write(
                f"warning: Jira live query failed ({e.detail or e}); "
                f"falling back to local hint list\n"
            )

    if args.name not in live_options:
        _fail(
            f"AP {args.name!r} is not registered. Register it first via "
            f"/kanban:register-ap {args.name}",
            registered=list(live_options),
            fallbackUsed=fallback_used,
        )
        return 1

    # Refresh the local hint list with the live values for visibility in
    # /kanban:whoami and so future invocations have a current snapshot.
    if not fallback_used:
        ap_block = (backend.get("jira") or {}).get("ap") or {}
        ap_block["registered"] = sorted(set(live_options))
        backend.setdefault("jira", {})["ap"] = ap_block
        data["backend"] = backend
        kanban_io.save(p, data)

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


def cmd_list_doing(args: argparse.Namespace) -> int:
    """List my-AP cards currently in DOING. Read-only — does NOT pull
    from TODO and does NOT transition. Backs `/kanban:doing` (#33).

    Returns: {ok, ap, doing: [{id, title, priority, started, ...}, ...]}
    The slash-command then reads the list and decides execution order
    across the (small) DOING set without scanning the wider backlog.
    """
    p = Path(args.kanban_path)
    if not p.exists():
        _fail(f"kanban.json not found at {p}")
        return 1
    data = kanban_io.load(p)
    backend = data.get("backend") or {}
    if backend.get("driver") != "jira":
        _fail("backend.driver must be 'jira'")
        return 1
    ap = _read_repo_ap(p)
    if not ap:
        _fail(
            "this repo has no AP set — run /kanban:assign-ap <name> first",
        )
        return 1

    from drivers import get_driver
    from drivers.base import TaskFilter

    driver = get_driver(data, p.parent)
    try:
        cards = driver.list_tasks(TaskFilter(column="DOING", ap=ap))
    except Exception as e:  # noqa: BLE001
        _fail(f"{type(e).__name__}: {e}")
        return 1
    out: list[dict[str, Any]] = []
    for t in cards:
        out.append({
            "id": t.id,
            "title": t.title,
            "priority": t.priority,
            "started": t.started,
            "ap": t.ap,
        })
    _emit({"ok": True, "ap": ap, "doing": out})
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

    from drivers import get_driver
    from drivers.base import CommentKind, TaskFilter

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
    from drivers import get_driver
    from drivers.base import CommentKind
    from drivers.jira import SelfApproveRefused

    driver = get_driver(data, p.parent)
    kwargs: dict[str, Any] = {}
    if args.reason:
        kwargs["reason"] = args.reason

    # Comma-separated list of Jira keys; trim whitespace, drop empties.
    blockers: list[str] = []
    if args.blocked_by:
        blockers = [k.strip() for k in args.blocked_by.split(",") if k.strip()]
        if args.to != "BLOCKED" and blockers:
            _fail(
                "--blocked-by is only valid when --to=BLOCKED; transitioning "
                f"to {args.to!r} won't create links",
            )
            return 1
        kwargs["blocked_by"] = blockers

    # Per-team convention: blockedRequiresLink. When opted in by the team
    # (set via /kanban:edit-conventions), refuse to transition to BLOCKED
    # without --blocked-by. The flag lives on the team's shared mapping
    # so the rule travels with the kanban-jira-code/2 payload.
    if args.to == "BLOCKED":
        cfg = (data.get("backend") or {}).get("jira") or {}
        if _cv.blocked_requires_link(cfg.get("conventions")) and not blockers:
            _fail(
                "team convention `blockedRequiresLink` is enabled — pass "
                "--blocked-by KEY[,KEY,...] when transitioning to BLOCKED. "
                "(see /kanban:show-conventions; the team can disable this "
                "via /kanban:edit-conventions)",
                code=1,
                kind="convention",
            )
            return 1
    try:
        t = driver.transition(args.key, args.to, **kwargs)
    except SelfApproveRefused as e:
        _fail(str(e), code=2, kind="self-approve")
        return 2
    except Exception as e:  # noqa: BLE001
        _fail(f"{type(e).__name__}: {e}")
        return 1
    _emit({
        "ok": True,
        "key": t.id,
        "column": t.column,
        "raw_status": t.custom.get("raw_status"),
        "depends": list(t.depends or []),
    })
    return 0


def _read_repo_ap(p: Path) -> str | None:
    """Return AP value from .claude/kanban-agent.json next to `p`, else None."""
    target = p.parent / ".claude" / "kanban-agent.json"
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text()).get("ap")
    except Exception:
        return None


def _build_precheck_block(
    key: str,
    task_data: dict[str, Any] | None,
    repo_ap: str | None,
) -> tuple[list[str], str]:
    """Return (warnings, context_block_text) per SPEC §5.3."""
    warnings: list[str] = []
    if task_data is None:
        return (
            ["card not found in this project"],
            f"[kanban context for {key}]\n  Status: not found in this project — ignore",
        )

    column = task_data.get("column") or "?"
    raw_status = (task_data.get("custom") or {}).get("raw_status") or column
    ap = task_data.get("ap")
    title = task_data.get("title") or ""

    rows: list[str] = []
    rows.append(f"[kanban context for {key}]")
    rows.append(f'  Title:        {title}')
    rows.append(f"  Status:       {raw_status}")

    if not ap:
        rows.append("  AP:           (unassigned)")
    elif repo_ap and ap == repo_ap:
        rows.append(f"  AP:           {ap}  (you)")
    else:
        rows.append(f"  AP:           {ap}   ⚠ NOT YOU (you are {repo_ap or 'unassigned'})")
        warnings.append("ap-mismatch")

    if column in {"DONE", "CANCELLED"}:
        rows.append(f"  ⚠ This card is closed ({column}). Do not modify it.")
        warnings.append(f"closed-{column.lower()}")

    if column == "REVIEW" and repo_ap and ap == repo_ap:
        rows.append(
            "  ⚠ This card is awaiting human review and is owned by you. "
            "Do not push it to DONE — anti-self-approve will refuse."
        )
        warnings.append("awaiting-review-self")

    last_q = task_data.get("last_open_question")
    if last_q:
        rows.append(f'  Open question: "{last_q}"')
        rows.append("  Consider answering before continuing.")
        warnings.append("open-question")

    if "ap-mismatch" in warnings:
        rows.append(
            "  Suggested action: do NOT modify this card. To take it over, "
            f"reassign in Jira UI or run /kanban:assign-ap to switch your AP."
        )

    return warnings, "\n".join(rows)


def _detect_open_question(comments: list) -> str | None:
    """Latest unanswered Q-kind comment text, or None.

    Walks backwards: a Q is "open" if the last comment after it (if any) is
    not an A.
    """
    last_q_text: str | None = None
    last_q_index = -1
    for i, c in enumerate(comments):
        if getattr(c.kind, "value", None) == "Q":
            last_q_text = c.text
            last_q_index = i
    if last_q_index == -1:
        return None
    # Scan after last_q for an A.
    for c in comments[last_q_index + 1 :]:
        if getattr(c.kind, "value", None) == "A":
            return None
    return last_q_text


def cmd_precheck_card(args: argparse.Namespace) -> int:
    """Fetch (with cache) + render context block per SPEC §5.3."""
    p = Path(args.kanban_path)
    if not p.exists():
        _fail(f"kanban.json not found at {p}")
        return 1
    data = kanban_io.load(p)
    backend = data.get("backend") or {}
    if backend.get("driver") != "jira":
        _emit({"key": args.key, "found": False, "context_block": ""})
        return 0

    project_key = (backend.get("jira") or {}).get("projectKey") or ""
    if project_key and not args.key.startswith(f"{project_key}-"):
        # Not in this project — silently ignore.
        _emit({"key": args.key, "found": False, "context_block": "", "ignored": True})
        return 0

    repo_ap = _read_repo_ap(p)
    cached = card_cache.get(p.parent, args.key)
    if cached is not None:
        warnings, block = _build_precheck_block(args.key, cached, repo_ap)
        _emit(
            {
                "key": args.key,
                "found": True,
                "warnings": warnings,
                "context_block": block,
                "from_cache": True,
            }
        )
        return 0

    from drivers import get_driver

    driver = get_driver(data, p.parent)
    try:
        task = driver.get_task(args.key)
    except JiraError as e:
        if e.status_code == 404:
            warnings, block = _build_precheck_block(args.key, None, repo_ap)
            _emit({"key": args.key, "found": False, "warnings": warnings, "context_block": block})
            return 0
        _fail(f"jira: {e.detail or e}", statusCode=e.status_code)
        return 1
    except Exception as e:  # noqa: BLE001
        _fail(f"{type(e).__name__}: {e}")
        return 1

    open_q: str | None = None
    if not args.skip_comments:
        try:
            comments = driver.list_comments(args.key)
            open_q = _detect_open_question(comments)
        except Exception:
            open_q = None

    task_data = {
        "id": task.id,
        "title": task.title,
        "column": task.column,
        "ap": task.ap,
        "priority": task.priority,
        "custom": task.custom,
        "last_open_question": open_q,
    }
    card_cache.put(p.parent, args.key, task_data)
    warnings, block = _build_precheck_block(args.key, task_data, repo_ap)
    _emit(
        {
            "key": args.key,
            "found": True,
            "warnings": warnings,
            "context_block": block,
            "from_cache": False,
        }
    )
    return 0


_STALE_DOING_THRESHOLD_DAYS = 2
_UNANSWERED_Q_THRESHOLD_HOURS = 24


def _parse_iso(ts: str | None):
    """Tolerant ISO-8601 parse. Returns datetime or None."""
    if not ts or not isinstance(ts, str):
        return None
    from datetime import datetime
    try:
        # fromisoformat handles "2026-04-30T10:00:00+08:00" + offset variants
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        # Jira sometimes emits trailing "Z" or millis with weird offsets
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None


def _detect_stale_doing(
    driver, repo_ap: str | None, *, threshold_days: int = _STALE_DOING_THRESHOLD_DAYS
) -> list[dict[str, Any]]:
    """Return DOING cards belonging to repo_ap whose `updated` is older
    than `threshold_days`. Each entry: {key, title, updated, days_idle}.

    The agent might have forgotten the card sat in DOING; surfacing it
    on /kanban:sync nudges them to either resume, BLOCKED + question, or
    transition to REVIEW.
    """
    from datetime import datetime, timedelta, timezone
    from drivers.base import TaskFilter

    try:
        tasks = driver.list_tasks(
            TaskFilter(column="DOING", ap=repo_ap, limit=20)
            if repo_ap
            else TaskFilter(column="DOING", limit=20)
        )
    except Exception:
        return []
    now = datetime.now(timezone.utc).astimezone()
    cutoff = now - timedelta(days=threshold_days)
    out: list[dict[str, Any]] = []
    for t in tasks:
        ts = _parse_iso(t.updated)
        if ts is None:
            continue
        if ts >= cutoff:
            continue
        idle_days = (now - ts).days
        out.append(
            {
                "key": t.id,
                "title": t.title,
                "updated": t.updated,
                "days_idle": idle_days,
                "priority": t.priority,
            }
        )
    return out


def _detect_unanswered_questions(
    driver,
    repo_ap: str | None,
    *,
    threshold_hours: int = _UNANSWERED_Q_THRESHOLD_HOURS,
) -> list[dict[str, Any]]:
    """For BLOCKED cards belonging to repo_ap, find ones where this AP
    posted a Q-prefix comment and no other party has commented since,
    older than `threshold_hours` (so the human has had time to reply).

    Each entry: {key, title, asked_at, hours_idle, question}.

    Implementation reads comments via driver.list_comments which already
    parses the SPEC §9 prefix grammar. A Q-comment authored by repo_ap
    is "ours"; any later comment from a different author counts as a
    reply (whether human or another agent).
    """
    from datetime import datetime, timezone
    from drivers.base import TaskFilter

    if not repo_ap:
        return []
    try:
        tasks = driver.list_tasks(
            TaskFilter(column="BLOCKED", ap=repo_ap, limit=20)
        )
    except Exception:
        return []

    now = datetime.now(timezone.utc).astimezone()
    out: list[dict[str, Any]] = []
    for t in tasks:
        try:
            comments = driver.list_comments(t.id)
        except Exception:
            continue
        latest_q_ts: str | None = None
        latest_q_text: str | None = None
        latest_other_ts: str | None = None
        for c in comments:
            ts = c.ts or ""
            if not ts:
                continue
            kind = getattr(c.kind, "value", None)
            if c.author == repo_ap and kind == "Q":
                if latest_q_ts is None or ts > latest_q_ts:
                    latest_q_ts = ts
                    latest_q_text = c.text
            elif c.author != repo_ap:
                if latest_other_ts is None or ts > latest_other_ts:
                    latest_other_ts = ts
        if latest_q_ts is None:
            continue  # no own questions
        if latest_other_ts is not None and latest_other_ts > latest_q_ts:
            continue  # someone replied
        q_dt = _parse_iso(latest_q_ts)
        if q_dt is None:
            continue
        idle_hours = (now - q_dt).total_seconds() / 3600.0
        if idle_hours < threshold_hours:
            continue  # too recent — give the human time
        out.append(
            {
                "key": t.id,
                "title": t.title,
                "asked_at": latest_q_ts,
                "hours_idle": int(idle_hours),
                "question": (latest_q_text or "")[:200],
            }
        )
    return out


def cmd_sync_summary(args: argparse.Namespace) -> int:
    """Render an open-cards summary for the current repo's AP."""
    p = Path(args.kanban_path)
    if not p.exists():
        _fail(f"kanban.json not found at {p}")
        return 1
    data = kanban_io.load(p)
    backend = data.get("backend") or {}
    if backend.get("driver") != "jira":
        _emit({"summary": "", "skip": "not in jira mode"})
        return 0

    repo_ap = _read_repo_ap(p)
    cfg = backend.get("jira") or {}
    project_key = cfg.get("projectKey") or ""

    from drivers import get_driver
    from drivers.base import TaskFilter

    driver = get_driver(data, p.parent)
    open_columns = ("TODO", "DOING", "BLOCKED", "REVIEW")
    rows: list[str] = []
    counts: dict[str, int] = {c: 0 for c in open_columns}
    try:
        for col in open_columns:
            tasks = driver.list_tasks(
                TaskFilter(column=col, ap=repo_ap, limit=20) if repo_ap else TaskFilter(column=col, limit=20)
            )
            counts[col] = len(tasks)
            for t in tasks:
                raw = (t.custom or {}).get("raw_status") or t.column
                rows.append(f"  {t.id:<14}{raw:<14}{t.title}")
    except Exception as e:  # noqa: BLE001
        _fail(f"{type(e).__name__}: {e}")
        return 1

    # Mentions block (issue #11 follow-up). Best-effort — if mention
    # detection fails we still surface the open-cards summary.
    mention_rows: list[str] = []
    mentions_count = 0
    new_latest_seen: str | None = None
    agent_acct = (backend.get("jira") or {}).get("agentAccountId")
    if agent_acct:
        try:
            since = _read_kanban_agent_field(p, "lastMentionSeenAt")
            if not since:
                from datetime import datetime, timedelta, timezone
                since = (
                    datetime.now(timezone.utc).astimezone() - timedelta(days=1)
                ).isoformat(timespec="seconds")
            client = _client_from_env_or_none()
            if client is not None:
                jql = (
                    f'project = "{project_key}" AND '
                    f'updated >= "{_jql_quote_ts(since)}"'
                )
                resp = client.search_jql(jql, fields=["updated"], max_results=50)
                latest = since
                for issue in (resp or {}).get("issues", []) or []:
                    key = issue.get("key", "")
                    try:
                        full = client.get_issue(
                            key, fields=["description", "comment", "updated"]
                        )
                    except JiraError:
                        continue
                    f = full.get("fields") or {}
                    upd = f.get("updated") or ""
                    if upd > latest:
                        latest = upd
                    # description mentions
                    for m in adf_extract_mentions(
                        f.get("description"), target_account_id=agent_acct
                    ):
                        mention_rows.append(
                            f"  {key:<14}description    {m.get('text','')}"
                        )
                        mentions_count += 1
                    # comment mentions (filter self-mentions)
                    for c in ((f.get("comment") or {}).get("comments")) or []:
                        cts = c.get("created") or ""
                        if since and cts < since:
                            continue
                        author_acct = (c.get("author") or {}).get("accountId")
                        if author_acct == agent_acct:
                            continue
                        body_adf = c.get("body")
                        for m in adf_extract_mentions(
                            body_adf, target_account_id=agent_acct
                        ):
                            who = (c.get("author") or {}).get("displayName") or "?"
                            mention_rows.append(
                                f"  {key:<14}comment        @{who}: "
                                f"{adf_to_text(body_adf)[:80]}"
                            )
                            mentions_count += 1
                            break
                new_latest_seen = latest
        except Exception:
            # Don't let mention failures block the sync — log via the
            # `mentionsError` field for diagnostics.
            mention_rows = []

    if not rows:
        summary = (
            f"[kanban Jira sync — {project_key} · ap={repo_ap or '(unset)'}]\n"
            f"  No open cards."
        )
    else:
        header = (
            f"[kanban Jira sync — {project_key} · ap={repo_ap or '(unset)'}]\n"
            f"  TODO {counts['TODO']} · DOING {counts['DOING']} · "
            f"BLOCKED {counts['BLOCKED']} · REVIEW {counts['REVIEW']}\n"
        )
        summary = header + "\n".join(rows)

    if mention_rows:
        summary += (
            f"\n\n[mentions — {mentions_count} since "
            f"{_read_kanban_agent_field(p, 'lastMentionSeenAt') or 'session start'}]\n"
            + "\n".join(mention_rows)
            + "\n  (run /kanban:mentions to mark these read)"
        )

    # Stale DOING + unanswered questions — the "things a human checks
    # when they open Jira" beyond just open-card counts. Best-effort:
    # detector failures don't block the rest of the sync.
    stale_rows: list[dict[str, Any]] = []
    unanswered_rows: list[dict[str, Any]] = []
    try:
        stale_rows = _detect_stale_doing(driver, repo_ap)
    except Exception:
        stale_rows = []
    try:
        unanswered_rows = _detect_unanswered_questions(driver, repo_ap)
    except Exception:
        unanswered_rows = []

    if stale_rows:
        summary += (
            f"\n\n[stale DOING — {len(stale_rows)} card(s) idle ≥ "
            f"{_STALE_DOING_THRESHOLD_DAYS} day(s)]\n"
            + "\n".join(
                f"  {r['key']:<14}{r['days_idle']}d idle    "
                f"{r['title']}"
                for r in stale_rows
            )
            + "\n  (resume, /kanban:question, or /kanban:done to clear)"
        )

    if unanswered_rows:
        summary += (
            f"\n\n[unanswered questions — {len(unanswered_rows)} BLOCKED "
            f"card(s) waiting on human, ≥{_UNANSWERED_Q_THRESHOLD_HOURS}h]\n"
            + "\n".join(
                f"  {r['key']:<14}{r['hours_idle']}h waiting    "
                f"{r['question'][:60]}"
                for r in unanswered_rows
            )
            + "\n  (consider nudging the owner or escalating)"
        )

    # Reconcile reminder — one-liner so SessionStart surfaces drift
    # without forcing the user to remember /kanban:reconcile. Closes
    # the visibility gap from #21. Best-effort: failures don't break
    # the rest of the sync.
    reconcile_unmapped: dict[str, list[str]] = {}
    reconcile_missing_ap: list[str] = []
    try:
        rec_client = _client_from_env_or_none()
        if rec_client is not None:
            transitions_map = (cfg or {}).get("transitions") or {}
            ap_field_id = ((cfg or {}).get("ap") or {}).get("fieldId")
            reconcile_unmapped, reconcile_missing_ap, _errs = _detect_reconcile(
                rec_client, project_key, transitions_map, ap_field_id, repo_ap
            )
    except Exception:
        pass

    total_drift = (
        sum(len(v) for v in reconcile_unmapped.values())
        + len(reconcile_missing_ap)
    )
    if total_drift:
        unmapped_count = sum(len(v) for v in reconcile_unmapped.values())
        bits = []
        if unmapped_count:
            bits.append(
                f"{unmapped_count} in unmapped status"
                + ("es" if len(reconcile_unmapped) > 1 else "")
            )
        if reconcile_missing_ap:
            bits.append(f"{len(reconcile_missing_ap)} with no AP")
        summary += (
            f"\n\n[drift — run /kanban:reconcile for details] "
            + ", ".join(bits)
        )

    _emit({
        "summary": summary,
        "counts": counts,
        "ap": repo_ap,
        "projectKey": project_key,
        "mentions": mentions_count,
        "latestSeen": new_latest_seen,
        "staleDoing": stale_rows,
        "unansweredQuestions": unanswered_rows,
    })
    return 0


def _ap_cf_jql_id(ap_field_id: str | None) -> str | None:
    """Return the numeric portion of a `customfield_NNNNN` id for use in
    `cf[NNNNN]` JQL clauses. None if the field id is malformed or absent.
    """
    if not ap_field_id or not ap_field_id.startswith("customfield_"):
        return None
    suffix = ap_field_id[len("customfield_"):]
    return suffix if suffix.isdigit() else None


def _detect_reconcile(
    client: "JiraClient",
    project_key: str,
    transitions: dict[str, dict[str, Any]],
    ap_field_id: str | None,
    repo_ap: str | None,
) -> tuple[dict[str, list[str]], list[str], list[str]]:
    """Return (unmapped_by_status, missing_ap_keys, errors).

    Two read-only JQL queries:
      1. project=X AND cf[ap]=repo_ap AND statusCategory!=Done
                  AND status not in (mapped_statuses)
         → my-AP cards whose Jira status isn't covered by the DSL.
         Filtering server-side via `status not in (...)` is locale-immune:
         JQL accepts canonical English status names regardless of the
         account's UI locale, so a zh-TW account whose API responses
         translate "REVIEW" to "審查" still won't false-flag mapped cards
         (#17). The status name in the response is used only for grouping
         in the diagnostic output (cosmetic — matches what the user sees
         in their Jira UI).
      2. project=X AND cf[ap] is EMPTY AND statusCategory!=Done
         → cards in the project with no AP set (invisible to
         /kanban:next which always filters by AP).

    Best-effort: each query failure goes into `errors[]` and the
    other still runs.
    """
    unmapped: dict[str, list[str]] = {}
    missing_ap: list[str] = []
    errors: list[str] = []

    # Distinct mapped status names for the JQL `status not in (...)` filter.
    # Skip any name containing `"` (would break the JQL string literal —
    # Jira status names never contain quotes in normal configurations).
    mapped_statuses: list[str] = []
    seen: set[str] = set()
    for spec in (transitions or {}).values():
        st = (spec or {}).get("status")
        if isinstance(st, str) and st and '"' not in st and st not in seen:
            mapped_statuses.append(st)
            seen.add(st)

    cf_id = _ap_cf_jql_id(ap_field_id)

    # 1. My-AP cards in unmapped statuses (server-side filter — locale immune)
    if repo_ap and cf_id and mapped_statuses:
        in_clause = ", ".join(f'"{s}"' for s in mapped_statuses)
        jql = (
            f'project = "{project_key}" '
            f'AND cf[{cf_id}] = "{repo_ap}" '
            f'AND statusCategory != Done '
            f'AND status not in ({in_clause})'
        )
        try:
            resp = client.search_jql(
                jql, fields=["status"], max_results=200
            )
        except JiraError as e:
            errors.append(f"my-AP search: {e.detail or e}")
        else:
            for issue in (resp or {}).get("issues", []) or []:
                key = issue.get("key", "")
                status_name = (
                    ((issue.get("fields") or {}).get("status") or {}).get("name")
                ) or "(unknown)"
                if key:
                    unmapped.setdefault(status_name, []).append(key)

    # 2. Missing-AP cards (regardless of which AP would have owned them)
    if cf_id:
        jql = (
            f'project = "{project_key}" '
            f'AND cf[{cf_id}] is EMPTY '
            f'AND statusCategory != Done'
        )
        try:
            resp = client.search_jql(
                jql, fields=["status"], max_results=200
            )
        except JiraError as e:
            errors.append(f"missing-AP search: {e.detail or e}")
        else:
            for issue in (resp or {}).get("issues", []) or []:
                key = issue.get("key", "")
                if key:
                    missing_ap.append(key)

    return unmapped, missing_ap, errors


def cmd_reconcile(args: argparse.Namespace) -> int:
    """Surface cards invisible to the canonical kanban view.

    Two diagnostic checks:
      - Unmapped status: card's status not in any DSL transition spec.
        Cause: workflow has more statuses than DSL maps; cards drift
        there via UI / automation / mistake.
      - Missing AP: open card whose AP custom field is null. Cause:
        manual creation in Jira UI, broken /kanban:initjira step 5
        on a per-machine setup, etc.

    Closes #21. Read-only — never modifies anything.
    """
    p = Path(args.kanban_path)
    if not p.exists():
        return _fail(f"kanban.json not found at {p}")
    data = kanban_io.load(p)
    backend = data.get("backend") or {}
    if backend.get("driver") != "jira":
        return _fail("backend.driver must be 'jira'")
    cfg = backend.get("jira") or {}
    project_key = cfg.get("projectKey")
    if not project_key:
        return _fail("backend.jira.projectKey unconfigured")
    transitions = cfg.get("transitions") or {}
    ap_field_id = (cfg.get("ap") or {}).get("fieldId")
    repo_ap = _read_repo_ap(p)

    client = _client_from_env()
    unmapped, missing_ap, errors = _detect_reconcile(
        client, project_key, transitions, ap_field_id, repo_ap
    )

    total_unmapped = sum(len(v) for v in unmapped.values())
    total_missing = len(missing_ap)

    if total_unmapped == 0 and total_missing == 0:
        hint = "All cards visible to the canonical kanban view. No drift detected."
    else:
        bits = []
        if total_unmapped:
            bits.append(
                f"{total_unmapped} card(s) in {len(unmapped)} unmapped status(es) — "
                "either map them via /kanban:initjira (re-run step 3 with extra "
                "DSL lines) or move them back to a mapped status in Jira UI"
            )
        if total_missing:
            bits.append(
                f"{total_missing} card(s) with no AP set — assign via "
                "Jira UI or via /kanban:next once you've claimed them"
            )
        hint = "; ".join(bits)

    _emit({
        "ok": True,
        "projectKey": project_key,
        "ap": repo_ap,
        "unmapped": unmapped,
        "missingAp": missing_ap,
        "totalUnmapped": total_unmapped,
        "totalMissingAp": total_missing,
        "errors": errors,
        "hint": hint,
    })
    return 0


def cmd_mcp_conflict_scan(args: argparse.Namespace) -> int:
    """SPEC §18.2: surface any Jira-flavoured MCP servers in scope."""
    p = Path(args.kanban_path) if args.kanban_path else Path.cwd()
    project_root = p.parent if p.name == "kanban.json" else p
    hits = mcp_conflict_scan.scan(project_root)
    _emit(
        {
            "ok": True,
            "conflicts": [
                {"server": h.server_name, "source": h.source, "matchedOn": h.matched_on}
                for h in hits
            ],
        }
    )
    return 0


# P0..P4 → Atlassian default-scheme names. Closes #18: most local-mode
# users use the industry-standard P0..P3 convention, while Jira's default
# priority scheme is named Highest/High/Medium/Low/Lowest.
_PRIORITY_AUTOMAP: dict[str, str] = {
    "P0": "Highest",
    "P1": "High",
    "P2": "Medium",
    "P3": "Low",
    "P4": "Lowest",
}


def _resolve_priority(
    p: str | None, valid_names: set[str]
) -> str | None | bool:
    """Resolve a local priority string against a set of valid Jira names.

    Returns:
        - the priority name to use (str)
        - None if `p` was None (no priority set on the task)
        - False if `p` could not be mapped to a valid Jira name
          (caller should treat as unmappable and fail-fast)

    When `valid_names` is empty (e.g., no credentials), the input
    passes through unchanged — the caller has no way to validate, so
    the error surfaces at create time as before.
    """
    if p is None:
        return None
    if not valid_names:
        return p  # pre-flight unavailable; pass through
    if p in valid_names:
        return p
    mapped = _PRIORITY_AUTOMAP.get(p)
    if mapped and mapped in valid_names:
        return mapped
    return False


def cmd_import_tasks(args: argparse.Namespace) -> int:
    """Migrate local kanban.json#tasks into Jira issues. Idempotent.

    Skip strategy:
      - tasks already in `.claude/.migration-map.json` → skip (mapped)
      - column in {DONE, CANCELLED} and not --include-done → skip

    Per-task work (when not --dry-run):
      1. driver.create_task(TaskInput) — base issue
      2. driver.assign(AgentRef(ap=repo_ap)) — sets AP custom field
         + agent assignee so /kanban:next can see the imported card
      3. driver.transition(key, "TODO") — moves out of project default
         status (typically Backlog) into the canonical TODO status
      4. For BLOCKED-origin tasks, post audit comment preserving the
         original `blocked_reason` (the imported card lands in TODO
         per the unified target; the blocked context isn't lost)

    Steps 2-4 are best-effort — failure is recorded per-task in
    skippedDetail/imported entries (apSet, transitioned flags) but
    doesn't abort the whole batch. Closes #16.
    """
    p = Path(args.kanban_path)
    if not p.exists():
        _fail(f"kanban.json not found at {p}")
        return 1
    data = kanban_io.load(p)
    if (data.get("backend") or {}).get("driver") != "jira":
        _fail("backend.driver must be 'jira' to import — run /kanban:initjira first")
        return 1
    legacy_tasks = data.get("tasks") or []
    if not legacy_tasks:
        _emit({"ok": True, "imported": 0, "skipped": 0, "tasks": []})
        return 0

    map_path = p.parent / ".claude" / ".migration-map.json"
    map_path.parent.mkdir(parents=True, exist_ok=True)
    if map_path.exists():
        try:
            mapping = json.loads(map_path.read_text())
        except Exception:
            mapping = {}
    else:
        mapping = {}

    # --- Pre-flight: priority validation (closes #18) -----------------
    # Fetch live priority list once, fail-fast if any task has an
    # unmappable priority — better than 22 individual create-time 400s.
    valid_priority_names: set[str] = set()
    pre_flight_client = _client_from_env_or_none()
    if pre_flight_client is not None:
        try:
            ps = pre_flight_client.get_priorities() or []
            valid_priority_names = {
                str(x.get("name")) for x in ps if isinstance(x, dict) and x.get("name")
            }
        except (JiraError, Exception):  # noqa: BLE001
            valid_priority_names = set()

    unmappable: list[dict[str, Any]] = []
    resolved: dict[str, str | None] = {}
    for t in legacy_tasks:
        local_id = t.get("id")
        if not local_id or local_id in mapping:
            continue
        col = t.get("column")
        if col in {"DONE", "CANCELLED"} and not args.include_done:
            continue
        result = _resolve_priority(t.get("priority"), valid_priority_names)
        if result is False:
            unmappable.append({"id": local_id, "priority": t.get("priority")})
        else:
            resolved[local_id] = result

    if unmappable and valid_priority_names:
        return _fail(
            f"unmappable priorities (auto-map covers P0..P4 → Highest/High/Medium/Low/Lowest): "
            f"{[u['priority'] for u in unmappable[:5]]}{' …' if len(unmappable) > 5 else ''}; "
            f"valid Jira priorities = {sorted(valid_priority_names)}",
            unmappable=unmappable,
            validPriorities=sorted(valid_priority_names),
        )

    from drivers import get_driver
    from drivers.base import AgentRef, CommentKind, TaskInput

    driver = get_driver(data, p.parent)
    repo_ap = _read_repo_ap(p)

    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for t in legacy_tasks:
        local_id = t.get("id")
        if not local_id:
            continue
        if local_id in mapping:
            skipped.append({"id": local_id, "reason": "already-mapped",
                            "key": mapping[local_id]})
            continue
        col = t.get("column")
        if col in {"DONE", "CANCELLED"} and not args.include_done:
            skipped.append({"id": local_id, "reason": f"closed-{col.lower()}"})
            continue
        if args.dry_run:
            imported.append({
                "id": local_id, "would_create": True,
                "resolvedPriority": resolved.get(local_id),
                "originalColumn": col,
            })
            continue

        # 1. Create the base issue (resolved priority).
        try:
            new_task = driver.create_task(
                TaskInput(
                    title=t.get("title") or local_id,
                    description=t.get("description") or "",
                    priority=resolved.get(local_id),
                    tags=list(t.get("tags") or []) + ["migrated-from-local"],
                    category=t.get("category"),
                )
            )
        except Exception as e:  # noqa: BLE001
            skipped.append({"id": local_id,
                            "reason": f"create failed: {type(e).__name__}: {e}"})
            continue

        # 2. Set AP custom field + agent assignee (best-effort).
        ap_set = False
        ap_error: str | None = None
        if repo_ap:
            try:
                driver.assign(new_task.id, AgentRef(ap=repo_ap))
                ap_set = True
            except Exception as e:  # noqa: BLE001
                ap_error = f"{type(e).__name__}: {e}"

        # 3. Transition out of project-default status into canonical TODO
        # (best-effort).
        transitioned = False
        transition_error: str | None = None
        try:
            driver.transition(new_task.id, "TODO")
            transitioned = True
        except Exception as e:  # noqa: BLE001
            transition_error = f"{type(e).__name__}: {e}"

        # 4. BLOCKED-origin: preserve the reason via audit comment so the
        # imported card (now in TODO) doesn't lose context.
        if col == "BLOCKED":
            reason = (t.get("custom") or {}).get("blocked_reason") or "(no reason recorded)"
            try:
                driver.post_comment(
                    new_task.id,
                    f"Originally BLOCKED in local kanban: {reason}",
                    kind=CommentKind.SYSTEM,
                )
            except Exception:
                pass  # audit-only; non-fatal

        mapping[local_id] = new_task.id
        imported.append({
            "id": local_id,
            "key": new_task.id,
            "title": new_task.title,
            "resolvedPriority": resolved.get(local_id),
            "originalColumn": col,
            "apSet": ap_set,
            "apError": ap_error,
            "transitioned": transitioned,
            "transitionError": transition_error,
        })

    if not args.dry_run:
        tmp = map_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, map_path)

    _emit(
        {
            "ok": True,
            "dryRun": bool(args.dry_run),
            "imported": len(imported),
            "skipped": len(skipped),
            "tasks": imported,
            "skippedDetail": skipped,
            "mapPath": str(map_path),
            "preFlightPriorities": sorted(valid_priority_names),
        }
    )
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    p = Path(args.kanban_path)
    if not p.exists():
        _fail(f"kanban.json not found at {p}")
        return 1
    data = kanban_io.load(p)
    from drivers import get_driver

    driver = get_driver(data, p.parent)
    h = driver.health()
    detail = h.detail
    # `LocalDriver.health()` is unconditionally ok — it has nothing
    # Jira-related to check. Callers that use `health` to gate "are Jira
    # credentials set up?" silently bypass credential capture when the
    # backend is still local (the by-code init flow before #31 fix).
    # Append a hint so any caller who prints `detail` self-diagnoses.
    # `ok` stays true because the local driver IS healthy in its own
    # right — flipping it would break /kanban:init's legitimate
    # post-init health check.
    if driver.name == "local":
        hint = "local driver — Jira credentials not checked; use read-credentials"
        detail = f"{detail}; {hint}" if detail else hint
    _emit({"ok": h.status.value == "ok", "status": h.status.value, "detail": detail})
    return 0


# --- entry point ----------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jira_setup", add_help=True)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("validate-credentials")
    s.add_argument("--base-url", required=True)
    s.add_argument("--email", required=True)
    s.add_argument(
        "--prompt-token", action="store_true",
        help=(
            "Capture the token interactively via getpass (no echo, no "
            "argv, no stdin pipe). Use this when running the command "
            "yourself in a terminal — keeps the token out of any "
            "Claude Code Bash-tool conversation log. Without this flag "
            "the token is read from stdin."
        ),
    )
    s.set_defaults(func=cmd_validate_credentials)

    s = sub.add_parser("store-credentials")
    s.add_argument("--base-url", required=True)
    s.add_argument("--email", required=True)
    s.add_argument(
        "--prompt-token", action="store_true",
        help=(
            "Capture the token interactively via getpass (no echo, no "
            "argv, no stdin pipe). Recommended path for human-driven "
            "setup; keeps the token out of any agent's conversation "
            "log. Without this flag the token is read from stdin."
        ),
    )
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
    s.add_argument(
        "--from-env", action="store_true",
        help=(
            "Read the token from ~/.claude-workbench/.env instead of "
            "stdin. Recommended in agent-driven flows so the token "
            "doesn't have to traverse stdin via a Bash-tool command "
            "(which would log to the conversation transcript). Step 1's "
            "store-credentials populates the .env file."
        ),
    )
    s.add_argument(
        "--prompt-token", action="store_true",
        help="Capture the token interactively via getpass (no echo).",
    )
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
    s.add_argument(
        "--project",
        help="project key — used to find project-scoped screens for "
             "automatic field association (fixes #6). When omitted, "
             "the field is created but not attached to any screen.",
    )
    s.set_defaults(func=cmd_create_ap_field)

    s = sub.add_parser("associate-ap-field-screens")
    s.add_argument("--kanban-path", required=True,
                   help="reads projectKey + ap.fieldId from this kanban.json")
    s.set_defaults(func=cmd_associate_ap_field_screens)

    s = sub.add_parser("verify-ap-field-screens")
    s.add_argument("--kanban-path", required=True)
    s.set_defaults(func=cmd_verify_ap_field_screens)

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

    s = sub.add_parser(
        "list-doing",
        help="List my-AP cards currently in DOING. Read-only; does not "
             "pull from TODO. Used by /kanban:doing (#33).",
    )
    s.add_argument("--kanban-path", required=True)
    s.set_defaults(func=cmd_list_doing)

    s = sub.add_parser("transition")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--key", required=True)
    s.add_argument("--to", required=True, choices=("TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"))
    s.add_argument("--reason")
    s.add_argument(
        "--blocked-by",
        help="(BLOCKED only) comma-separated list of Jira keys (e.g. "
             "DMI-1099,INFRA-7) to attach as `is blocked by` issue links "
             "before applying the transition. Idempotent — already-linked "
             "blockers are skipped.",
    )
    s.set_defaults(func=cmd_transition)

    s = sub.add_parser("precheck-card")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--key", required=True)
    s.add_argument("--skip-comments", action="store_true",
                   help="skip the open-question scan (saves an API call)")
    s.set_defaults(func=cmd_precheck_card)

    s = sub.add_parser("sync-summary")
    s.add_argument("--kanban-path", required=True)
    s.set_defaults(func=cmd_sync_summary)

    s = sub.add_parser("mcp-conflict-scan")
    s.add_argument("--kanban-path", default=None,
                   help="optional; defaults to current working directory")
    s.set_defaults(func=cmd_mcp_conflict_scan)

    s = sub.add_parser("reconcile")
    s.add_argument("--kanban-path", required=True)
    s.set_defaults(func=cmd_reconcile)

    s = sub.add_parser("import-tasks")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--dry-run", action="store_true",
                   help="report what would be imported without creating Jira issues")
    s.add_argument("--include-done", action="store_true",
                   help="also import DONE / CANCELLED tasks (default: skip)")
    s.set_defaults(func=cmd_import_tasks)

    s = sub.add_parser("parse-transitions-dsl")
    s.add_argument("--dsl-text", required=True,
                   help="DSL block as a string (file paths are deliberately "
                        "not accepted — the parser surfaces errors verbatim "
                        "and a file path would risk leaking secrets)")
    s.add_argument("--current-user-account-id",
                   help="accountId to use when DSL says 'Assignee to me'")
    s.add_argument("--no-user-lookup", action="store_true",
                   help="skip /user/search resolution for non-'me' assignees")
    s.set_defaults(func=cmd_parse_transitions_dsl)

    s = sub.add_parser("resolve-doc-link")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--doc-path", required=True,
                   help="repo-relative path, e.g. 'epic/AGENT-001-foo.md'")
    s.add_argument("--branch",
                   help="git branch for the URL; defaults to current branch then 'main'")
    s.set_defaults(func=cmd_resolve_doc_link)

    s = sub.add_parser("emit-jira-code")
    s.add_argument("--kanban-path", required=True)
    s.add_argument(
        "--include-agent-account",
        action="store_true",
        help="include `agentAccountId` in the code (only meaningful when "
             "the receiving machine uses the same shared agent Atlassian account)",
    )
    s.set_defaults(func=cmd_emit_jira_code)

    s = sub.add_parser("import-jira-code")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--code-json", required=True,
                   help="the JSON code emitted by /kanban:showjira-code on the source machine")
    s.set_defaults(func=cmd_import_jira_code)

    s = sub.add_parser("live-list-aps")
    s.add_argument("--kanban-path", required=True)
    s.set_defaults(func=cmd_live_list_aps)

    s = sub.add_parser("find-mentions")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--since",
                   help="ISO timestamp; defaults to .claude/kanban-agent.json#lastMentionSeenAt or 1d ago")
    s.set_defaults(func=cmd_find_mentions)

    s = sub.add_parser("mark-mentions-read")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--until",
                   help="ISO timestamp; defaults to now")
    s.set_defaults(func=cmd_mark_mentions_read)

    s = sub.add_parser("post-reply")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--key", required=True, help="Jira issue key (e.g. DMI-1099)")
    s.add_argument("--body", required=True)
    s.add_argument("--to-account-id",
                   help="accountId to @-mention; if omitted, posts a plain comment")
    s.add_argument("--display-name", default="user",
                   help="display name for the @-mention text (default: 'user')")
    s.set_defaults(func=cmd_post_reply)

    s = sub.add_parser("create-sub")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--parent", required=True, help="parent issue key")
    s.add_argument("--title", action="append", dest="titles", default=[],
                   help="title for one sub-card; repeat for multiple")
    s.add_argument("--description", default="")
    s.add_argument("--priority")
    s.add_argument("--link-type", default="Relates",
                   help="Jira issue-link type for parent←child relation; "
                        "common values: Relates, Blocks, Sub-task")
    s.set_defaults(func=cmd_create_sub)

    s = sub.add_parser("set-conventions")
    s.add_argument("--kanban-path", required=True)
    s.add_argument(
        "--conventions-json",
        help=(
            'Full replace mode. JSON object: {"notes": ["..."], '
            '"blockedRequiresLink": bool}. Mutually exclusive with the '
            'incremental flags below.'
        ),
    )
    s.add_argument(
        "--append-note", action="append", default=[],
        help=(
            "Incremental mode: append a note to conventions.notes. "
            "Idempotent — exact-text duplicates of existing notes are "
            "silently skipped. Repeat the flag to append several notes "
            "in one call. May not be combined with --conventions-json."
        ),
    )
    s.add_argument(
        "--remove-note", action="append", default=[],
        help=(
            "Incremental mode: remove a note from conventions.notes by "
            "exact-text match. Notes that don't exist are a no-op. May "
            "not be combined with --conventions-json."
        ),
    )
    s.add_argument(
        "--set-toggle", action="append", default=[],
        help=(
            "Incremental mode: set a single toggle as KEY=VALUE (e.g. "
            "blockedRequiresLink=false). Booleans are recognised "
            "case-insensitively; everything else is stored as a string. "
            "Repeat the flag to set several toggles. May not be combined "
            "with --conventions-json."
        ),
    )
    s.set_defaults(func=cmd_set_conventions)

    s = sub.add_parser("read-conventions")
    s.add_argument("--kanban-path", required=True)
    s.set_defaults(func=cmd_read_conventions)

    s = sub.add_parser("record-conventions-ack")
    s.add_argument("--kanban-path", required=True)
    s.set_defaults(func=cmd_record_conventions_ack)

    s = sub.add_parser("set-transitions")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--transitions-json", required=True,
                   help="JSON object mapping CANONICAL -> {status, addLabels?, removeLabels?, assignee?}")
    s.add_argument("--available-statuses",
                   help="JSON array of Jira status names; rejects writes whose `status` isn't in the list (unless --force)")
    s.add_argument("--force", action="store_true",
                   help="write even if validation reports issues")
    s.set_defaults(func=cmd_set_transitions)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
