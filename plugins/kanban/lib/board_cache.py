"""Per-machine cache of compound-transition mappings keyed by Jira board.

Multiple project repos pointing at the same `(baseUrl, projectKey, boardId)`
share the same `backend.jira` mapping (transitions, AP field config, AP
roster, agent account). This cache lets a fresh `/kanban:initjira` reuse
mappings already established by a prior repo on the same machine — no
re-prompting for the DSL.

Storage:
    ~/.claude-workbench/kanban-boards/<safe-host>__<KEY>__<id>.json

Each file:
    {
      "version": "0.3",
      "key": {"baseUrl": "...", "projectKey": "AGENT", "boardId": 1},
      "backend_jira": {
        "agentAccountId": "...",
        "transitions": {...},
        "ap": {"fieldId": "customfield_10042", "fieldName": "Claude Agent",
               "registered": ["agent-fin", "agent-quant"]}
      },
      "fetched_at_unix": 1729...,
      "last_repo": "/abs/path/to/repo-that-wrote-this"
    }

The cache is **convenience only**. The per-repo `kanban.json#backend.jira`
is the source of truth. If the cache file is deleted/corrupt, init still
works (the user just has to re-enter the DSL).

Public surface:
    cache_dir() -> Path
    cache_path(base_url, project_key, board_id) -> Path
    read(base_url, project_key, board_id) -> dict | None
    write(base_url, project_key, board_id, backend_jira, source_repo) -> None
    invalidate(base_url, project_key, board_id) -> None
    list_all() -> list[dict]
    safe_host(base_url) -> str    # exposed for tests + display
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


CACHE_DIR_NAME = "kanban-boards"
CACHE_VERSION = "0.3"

_HOST_SAFE = re.compile(r"[^a-z0-9.-]")


def cache_dir() -> Path:
    return Path.home() / ".claude-workbench" / CACHE_DIR_NAME


def safe_host(base_url: str) -> str:
    """Lowercased hostname with anything outside [a-z0-9.-] replaced by `_`."""
    host = urlparse(base_url or "").hostname or "unknown"
    return _HOST_SAFE.sub("_", host.lower())


def cache_path(base_url: str, project_key: str, board_id: int | str) -> Path:
    return (
        cache_dir()
        / f"{safe_host(base_url)}__{project_key}__{int(board_id)}.json"
    )


def read(
    base_url: str, project_key: str, board_id: int | str
) -> dict[str, Any] | None:
    """Return the cached payload, or None if the file is missing / corrupt."""
    p = cache_path(base_url, project_key, board_id)
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict) or "backend_jira" not in raw:
        return None
    return raw


def write(
    base_url: str,
    project_key: str,
    board_id: int | str,
    backend_jira: dict[str, Any],
    source_repo: str | os.PathLike[str] | None = None,
) -> Path:
    """Atomically write the cache entry. Returns the path written.

    `backend_jira` should be the resolved (post-migration, v0.3) form —
    callers must not pass legacy statusMap/labelFallback shape.
    """
    d = cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = cache_path(base_url, project_key, board_id)

    payload = {
        "version": CACHE_VERSION,
        "key": {
            "baseUrl": base_url,
            "projectKey": project_key,
            "boardId": int(board_id),
        },
        "backend_jira": backend_jira,
        "fetched_at_unix": int(time.time()),
        "last_repo": str(source_repo) if source_repo else "",
    }
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    return p


def invalidate(base_url: str, project_key: str, board_id: int | str) -> None:
    p = cache_path(base_url, project_key, board_id)
    try:
        p.unlink()
    except FileNotFoundError:
        pass


def list_all() -> list[dict[str, Any]]:
    """Return every cached entry. Skips corrupt files silently."""
    d = cache_dir()
    if not d.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(d.iterdir()):
        if p.suffix != ".json":
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(raw, dict) and "backend_jira" in raw:
            out.append(raw)
    return out


def update_ap_registered(
    base_url: str,
    project_key: str,
    board_id: int | str,
    new_ap: str,
) -> bool:
    """Append `new_ap` to a cached entry's ap.registered. Returns True if
    the cache was updated, False if the entry was missing or already had it.
    Used by /kanban:register-ap so other repos see the same roster.
    """
    payload = read(base_url, project_key, board_id)
    if payload is None:
        return False
    ap_block = (payload.get("backend_jira") or {}).get("ap") or {}
    registered = list(ap_block.get("registered") or [])
    if new_ap in registered:
        return False
    registered.append(new_ap)
    ap_block["registered"] = registered
    payload["backend_jira"]["ap"] = ap_block
    payload["fetched_at_unix"] = int(time.time())
    p = cache_path(base_url, project_key, board_id)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp, p)
    return True
