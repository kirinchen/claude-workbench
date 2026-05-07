"""Board-side config storage on Jira project properties (#after-50).

Background: pre-0.3.25, multi-machine teams shared the kanban
`backend.jira` block (transitions DSL, AP field id, conventions notes,
etc.) by emitting a JSON payload via `/kanban:showjira-code` and
manually pasting it into `/kanban:import-jira-code` on every receiver.
That hand-paste flow drifts: changes on the source repo silently fail
to propagate; new repos/machines have to be told the steps; nothing
prevents two receivers from ending up on different versions.

The 0.3.25+ replacement: the canonical config lives **on the Jira
project itself** under property key `kanban-config`. Receivers pull;
admins push. The local kanban.json is a per-machine cache.

Storage model:
- **Jira project property** `kanban-config` — authoritative JSON; written
  by `push()` (requires project-admin Jira role); read by `pull()`.
- **`kanban.json#backend.jira`** — per-machine cache. Mirrors the Jira
  property's value. Git-tracked so the cache is auditable and survives
  fresh clones.
- **`.claude/kanban-agent.json#boardConfigCachedAt`** — per-machine
  ISO 8601 timestamp of the last successful pull. Drives passive sync:
  when the cache is older than `CACHE_TTL_HOURS`, the next operation
  triggers a refresh.

Public surface:
    push(client, project_key, config)         -> None
    pull(client, project_key)                 -> dict[str, Any]
    cache_age_hours(repo_root)                -> float | None
    is_cache_stale(repo_root, ttl=None)       -> bool
    mark_synced(repo_root, ts=None)           -> Path
    PROPERTY_KEY                              -> "kanban-config"
    CACHE_TTL_HOURS                           -> 8
    BoardConfigError                          -> exception type

Concurrency: project property writes are last-writer-wins (Jira does
not expose ETag versioning on properties). Two admins pushing
simultaneously is a real but rare edge — `push()` does not attempt
optimistic concurrency.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


# Jira project property key — this string is part of the on-Jira
# contract. Don't rename without a migration step.
PROPERTY_KEY = "kanban-config"

# Passive-sync threshold. After this many hours since the last pull,
# the next driver operation refreshes the cache. Tunable via
# /kanban:sync-board-config which forces a pull regardless of TTL.
CACHE_TTL_HOURS = 8

# .claude/kanban-agent.json field that stores the per-machine timestamp
# of the most recent successful pull.
_CACHED_AT_FIELD = "boardConfigCachedAt"


class BoardConfigError(RuntimeError):
    """Raised when a push/pull operation fails in a way the caller
    should surface to the user (permission denied, malformed payload,
    Jira unreachable). Distinct from JiraError so callers can
    differentiate config-layer failures from underlying HTTP errors.
    """


def push(client: Any, project_key: str, config: dict[str, Any]) -> None:
    """Write `config` to the Jira project's `kanban-config` property.

    `config` is the canonical JSON the team agrees on — typically the
    `backend.jira` block from a fully-configured kanban.json minus
    per-machine fields (`agentAccountId` is per-Atlassian-account, but
    the rest of the block is per-board and should round-trip).

    Raises BoardConfigError on permission failure (403) or other
    non-retryable issues with a readable message. Other HTTP errors
    surface from the underlying client.
    """
    if not isinstance(config, dict) or not config:
        raise BoardConfigError("config must be a non-empty JSON object")
    if not project_key:
        raise BoardConfigError("project_key is required")

    # Local import to avoid making board_config depend on jira_client at
    # module load time (callers that only need cache helpers shouldn't
    # pay that import cost).
    from lib.jira_client import JiraError

    try:
        client.set_project_property(project_key, PROPERTY_KEY, config)
    except JiraError as e:
        if e.status_code == 403:
            raise BoardConfigError(
                f"permission denied writing project property "
                f"{PROPERTY_KEY!r} on {project_key!r}: agent's Jira "
                f"account needs project-admin role to push board config. "
                f"Ask a project admin to push, or grant the agent admin "
                f"role on this project."
            ) from e
        raise BoardConfigError(
            f"jira: {e.detail or e} (status={e.status_code})"
        ) from e


def pull(client: Any, project_key: str) -> dict[str, Any]:
    """Read the Jira project's `kanban-config` property and return the
    config dict.

    Raises BoardConfigError(404-marker) when the property hasn't been
    set yet — caller distinguishes "no config on board" from "Jira
    unreachable" by checking `BoardConfigError.not_found` (set on the
    raised instance for the 404 case only).
    """
    if not project_key:
        raise BoardConfigError("project_key is required")

    from lib.jira_client import JiraError

    try:
        envelope = client.get_project_property(project_key, PROPERTY_KEY)
    except JiraError as e:
        if e.status_code == 404:
            err = BoardConfigError(
                f"no board config set yet on Jira project {project_key!r} "
                f"(property {PROPERTY_KEY!r} does not exist). "
                f"Run /kanban:push-board-config from a repo whose "
                f"backend.jira block carries the team's canonical config."
            )
            err.not_found = True  # type: ignore[attr-defined]
            raise err from e
        if e.status_code == 403:
            raise BoardConfigError(
                f"permission denied reading project property "
                f"{PROPERTY_KEY!r} on {project_key!r}: agent's Jira "
                f"account doesn't have permission to read project "
                f"entity properties on this project. Ask a project "
                f"admin to grant project-read access."
            ) from e
        raise BoardConfigError(
            f"jira: {e.detail or e} (status={e.status_code})"
        ) from e

    if not isinstance(envelope, dict):
        raise BoardConfigError(
            "project property response was not a JSON object"
        )
    value = envelope.get("value")
    if not isinstance(value, dict):
        raise BoardConfigError(
            "project property `value` is not a JSON object — "
            "the property may have been set by a non-kanban writer"
        )
    return value


def cache_age_hours(repo_root: Path) -> float | None:
    """Return how many hours have elapsed since the last successful
    pull on this machine, or None if no pull has ever been recorded.
    """
    ts_str = _read_cached_at(repo_root)
    if not ts_str:
        return None
    parsed = _parse_iso(ts_str)
    if parsed is None:
        return None
    delta = _utcnow() - parsed
    return max(delta.total_seconds() / 3600.0, 0.0)


def is_cache_stale(repo_root: Path, *, ttl_hours: float | None = None) -> bool:
    """True when the cache is older than TTL (or has never been
    populated). Used by the driver layer to decide whether to trigger
    a passive sync before the next operation.
    """
    ttl = ttl_hours if ttl_hours is not None else CACHE_TTL_HOURS
    age = cache_age_hours(repo_root)
    if age is None:
        return True
    return age >= ttl


def mark_synced(repo_root: Path, ts: datetime | None = None) -> Path:
    """Record `ts` (default: now) as the latest successful pull
    timestamp. Returns the .claude/kanban-agent.json path.
    """
    when = (ts or _utcnow()).isoformat(timespec="seconds")
    return _write_cached_at(repo_root, when)


# --- private helpers ----------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: str) -> datetime | None:
    if not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _agent_path(repo_root: Path) -> Path:
    return Path(repo_root) / ".claude" / "kanban-agent.json"


def _read_cached_at(repo_root: Path) -> str | None:
    target = _agent_path(repo_root)
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    val = data.get(_CACHED_AT_FIELD)
    return val if isinstance(val, str) else None


def _write_cached_at(repo_root: Path, when: str) -> Path:
    target = _agent_path(repo_root)
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
    data[_CACHED_AT_FIELD] = when
    target.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
