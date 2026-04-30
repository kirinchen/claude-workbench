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
from lib import mcp_conflict_scan, transitions as _tr  # noqa: E402
from lib.jira_client import JiraClient, JiraError  # noqa: E402


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
        "schema": "kanban-jira-code/1",
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
    if code.get("schema") != "kanban-jira-code/1":
        return _fail(
            f"unsupported code schema {code.get('schema')!r}; expected kanban-jira-code/1"
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
    cfg = {k: v for k, v in cfg.items() if v is not None}

    data["backend"] = {"driver": "jira", "jira": cfg}
    meta = data.setdefault("meta", {})
    meta["columns"] = list(CANONICAL_COLUMNS)
    kanban_io.save(p, data)
    _emit({"ok": True, "imported": cfg})
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
    project_key = (backend.get("jira") or {}).get("projectKey") or ""

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

    _emit({"summary": summary, "counts": counts, "ap": repo_ap, "projectKey": project_key})
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


def cmd_import_tasks(args: argparse.Namespace) -> int:
    """Migrate local kanban.json#tasks into Jira issues. Idempotent.

    Skip strategy:
      - tasks already in `.claude/.migration-map.json` → skip (mapped)
      - column in {DONE, CANCELLED} and not --include-done → skip
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

    from drivers import get_driver
    from drivers.base import TaskInput

    driver = get_driver(data, p.parent)

    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for t in legacy_tasks:
        local_id = t.get("id")
        if not local_id:
            continue
        if local_id in mapping:
            skipped.append({"id": local_id, "reason": "already-mapped", "key": mapping[local_id]})
            continue
        col = t.get("column")
        if col in {"DONE", "CANCELLED"} and not args.include_done:
            skipped.append({"id": local_id, "reason": f"closed-{col.lower()}"})
            continue
        if args.dry_run:
            imported.append({"id": local_id, "would_create": True})
            continue
        try:
            new_task = driver.create_task(
                TaskInput(
                    title=t.get("title") or local_id,
                    description=t.get("description") or "",
                    priority=t.get("priority"),
                    tags=list(t.get("tags") or []) + ["migrated-from-local"],
                    category=t.get("category"),
                )
            )
        except Exception as e:  # noqa: BLE001
            skipped.append({"id": local_id, "reason": f"error: {type(e).__name__}: {e}"})
            continue
        mapping[local_id] = new_task.id
        imported.append({"id": local_id, "key": new_task.id, "title": new_task.title})

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

    s = sub.add_parser("transition")
    s.add_argument("--kanban-path", required=True)
    s.add_argument("--key", required=True)
    s.add_argument("--to", required=True, choices=("TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"))
    s.add_argument("--reason")
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
