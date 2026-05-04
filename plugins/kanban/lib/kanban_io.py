"""kanban.json reader/writer with v0.1↔v0.2 compatibility.

Reader policy: accept v0.1 (`schema_version: 1`) and v0.2 (`version: "0.2"`).
Writer policy: always emit v0.2 form.

Public surface:
    load(path) -> dict       # normalized v0.2 shape, with default `backend`
    save(path, data) -> None # atomic write, v0.2 form
    detect_version(data) -> "0.1" | "0.2"
    default_backend() -> dict
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


CURRENT_VERSION = "0.2"
LEGACY_SCHEMA_VERSION = 1


def default_backend() -> dict[str, Any]:
    return {"driver": "local"}


def detect_version(data: dict[str, Any]) -> str:
    """Return '0.2' if v0.2 form, '0.1' for legacy. Heuristic, not strict."""
    if isinstance(data.get("version"), str):
        return data["version"]
    if data.get("schema_version") == LEGACY_SCHEMA_VERSION:
        return "0.1"
    # No marker — treat as legacy and let downstream decide.
    return "0.1"


def normalize(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `data` in canonical v0.2 shape.

    - Adds `version: "0.2"` if absent.
    - Drops legacy `schema_version` (writer policy is single-source).
    - Adds `backend: {driver: local}` if absent (v0.1 implicit local).
    - For jira backends: auto-migrates legacy `statusMap`/`labelFallback`/
      `partial` (v0.2.x) into the v0.3 `transitions` block. Lossless on the
      writer's intent — see lib/transitions.py.
    - Leaves `meta`, `tasks` untouched.
    """
    out = dict(data)
    out["version"] = CURRENT_VERSION
    out.pop("schema_version", None)
    if "backend" not in out or not isinstance(out["backend"], dict):
        out["backend"] = default_backend()
    elif "driver" not in out["backend"]:
        out["backend"]["driver"] = "local"

    backend = out["backend"]
    if backend.get("driver") == "jira" and isinstance(backend.get("jira"), dict):
        try:
            from lib import transitions as _tr  # local import — avoid cycles
        except ImportError:
            _tr = None
        if _tr is not None:
            backend["jira"] = _tr.migrate_legacy(backend["jira"])

    # Local + Jira both share the canonical column rename (#48): legacy
    # `DONE` task entries become `APPROVED` in-memory. `meta.columns`
    # (the local-mode column whitelist) gets the same treatment so
    # validators / displays don't keep showing `DONE`.
    tasks = out.get("tasks")
    if isinstance(tasks, list):
        for t in tasks:
            if isinstance(t, dict) and t.get("column") == "DONE":
                t["column"] = "APPROVED"
    meta = out.get("meta")
    if isinstance(meta, dict) and isinstance(meta.get("columns"), list):
        meta["columns"] = [
            "APPROVED" if c == "DONE" else c for c in meta["columns"]
        ]
    return out


def load(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read kanban.json and return normalized v0.2 dict.

    Raises FileNotFoundError if missing, json.JSONDecodeError if malformed.
    """
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level must be an object")
    return normalize(data)


def save(path: str | os.PathLike[str], data: dict[str, Any]) -> None:
    """Atomically write kanban.json in v0.2 form.

    Strategy: write to tempfile in same directory, fsync, rename. Survives
    partial writes and concurrent reads.
    """
    p = Path(path)
    out = normalize(data)
    parent = p.parent if p.parent != Path("") else Path(".")
    parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix=".kanban.", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, p)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    """CLI for hooks/scripts. Usage: python -m lib.kanban_io <path>"""
    import sys
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: kanban_io <path>", file=sys.stderr)
        return 2
    try:
        data = load(args[0])
    except FileNotFoundError:
        return 1
    json.dump(data, __import__("sys").stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
