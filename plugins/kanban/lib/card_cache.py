"""Per-project, time-bounded cache for Jira card lookups.

SPEC §5.4: scope = Claude Code session, TTL = 30 s, invalidated on any
plugin-issued write (transition / post_comment / assign).

Implementation: a `.kanban-cache/` directory under the project's `.claude/`,
with one JSON file per cached key (e.g. `AGENT-42.json`). Hooks and slash
commands run in separate Python processes, so a file-backed store is the
only practical choice. The TTL is enforced per-entry by parsing the embedded
`fetched_at` timestamp.

Public surface:
    cache_dir(project_root) -> Path
    get(project_root, key, ttl=30) -> dict | None
    put(project_root, key, data) -> None
    invalidate(project_root, key) -> None
    clear(project_root) -> None
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


DEFAULT_TTL_SECONDS = 30


def cache_dir(project_root: str | os.PathLike[str]) -> Path:
    return Path(project_root) / ".claude" / ".kanban-cache"


def _entry_path(project_root: str | os.PathLike[str], key: str) -> Path:
    safe = key.replace("/", "_").replace("..", "_")
    return cache_dir(project_root) / f"{safe}.json"


def get(
    project_root: str | os.PathLike[str],
    key: str,
    ttl: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any] | None:
    """Return cached data for `key` if fresh, else None."""
    p = _entry_path(project_root, key)
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        # Corrupt entry — drop it.
        try:
            p.unlink()
        except OSError:
            pass
        return None
    fetched_at = raw.get("fetched_at_unix")
    if not isinstance(fetched_at, (int, float)):
        return None
    if (time.time() - fetched_at) > ttl:
        return None
    return raw.get("data")


def put(
    project_root: str | os.PathLike[str], key: str, data: dict[str, Any]
) -> None:
    p = _entry_path(project_root, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fetched_at_unix": time.time(), "key": key, "data": data}
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def invalidate(project_root: str | os.PathLike[str], key: str) -> None:
    p = _entry_path(project_root, key)
    try:
        p.unlink()
    except FileNotFoundError:
        pass


def clear(project_root: str | os.PathLike[str]) -> None:
    d = cache_dir(project_root)
    if not d.exists():
        return
    for entry in d.iterdir():
        try:
            entry.unlink()
        except OSError:
            pass
