"""Team-convention block (kanban-jira-code/2).

The plugin distinguishes two layers of team configuration:

1. **Hard wiring** — `transitions`, `ap.fieldId`, `boardUrl`. The plugin
   needs these to function. Lives in `backend.jira.{transitions,ap,...}`.

2. **Soft agreements** — narrative notes ("Review 一律 assign kirin",
   "service@ has no Delete permission, use CANCELLED") plus a couple of
   per-team opt-in toggles. Lives in `backend.jira.conventions`.

This module owns the conventions block: validation, hashing for ack, and
the small public surface needed by the slash commands and helper CLI.

Public surface:
    DEFAULT_NOTES_MAX_LEN          # 1024 chars per note
    DEFAULT_NOTES_MAX_COUNT        # 10 notes total
    validate(conventions) -> list[str]            # warnings, never errors
    hash_conventions(conventions) -> str          # stable for ack tracking
    record_ack(repo_root, conventions) -> Path    # writes timestamp to .claude/kanban-agent.json
    has_recent_ack(repo_root, conventions) -> bool
    blocked_requires_link(conventions) -> bool    # convenience accessor
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_NOTES_MAX_LEN = 1024
DEFAULT_NOTES_MAX_COUNT = 10


def normalize(conventions: dict[str, Any] | None) -> dict[str, Any]:
    """Return a fresh dict with required defaults filled in.

    `conventions` may be None (no block at all) or a partial dict. The
    output always has `notes` (list, possibly empty) and never carries
    keys this version doesn't recognise — forward-incompatible fields
    from a future plugin version are dropped on purpose so this version
    doesn't render half-understood data.
    """
    src = conventions or {}
    out: dict[str, Any] = {"notes": []}
    if isinstance(src.get("notes"), list):
        out["notes"] = [n for n in src["notes"] if isinstance(n, str)]
    if "blockedRequiresLink" in src:
        out["blockedRequiresLink"] = bool(src["blockedRequiresLink"])
    return out


def validate(conventions: dict[str, Any] | None) -> list[str]:
    """Return advisory warnings. Empty list = clean."""
    warnings: list[str] = []
    if conventions is None:
        return warnings
    notes = conventions.get("notes")
    if notes is None:
        return warnings
    if not isinstance(notes, list):
        warnings.append("conventions.notes must be a list of strings")
        return warnings
    if len(notes) > DEFAULT_NOTES_MAX_COUNT:
        warnings.append(
            f"conventions.notes has {len(notes)} entries — guardrail is "
            f"{DEFAULT_NOTES_MAX_COUNT}; consider moving long-form material "
            "to an ADR or wiki"
        )
    for i, n in enumerate(notes):
        if not isinstance(n, str):
            warnings.append(f"conventions.notes[{i}] is not a string")
            continue
        if len(n) > DEFAULT_NOTES_MAX_LEN:
            warnings.append(
                f"conventions.notes[{i}] is {len(n)} chars — guardrail is "
                f"{DEFAULT_NOTES_MAX_LEN}; trim or move to an ADR"
            )
        if not n.strip():
            warnings.append(f"conventions.notes[{i}] is empty / whitespace")
    return warnings


def is_empty(conventions: dict[str, Any] | None) -> bool:
    """A convention block is "empty" if it has no notes and no other
    actionable settings worth surfacing. Used by the receiver UX to
    decide whether to skip the ack flow entirely.
    """
    if conventions is None:
        return True
    if conventions.get("notes"):
        return False
    if "blockedRequiresLink" in conventions:
        return False
    return True


def blocked_requires_link(conventions: dict[str, Any] | None) -> bool:
    if not conventions:
        return False
    return bool(conventions.get("blockedRequiresLink"))


# --- ack tracking --------------------------------------------------------


def hash_conventions(conventions: dict[str, Any] | None) -> str:
    """Stable hash over the canonical-json form of `conventions`.

    Used to detect "user already ack'd this exact set" so the receiver UX
    doesn't re-prompt on every command. Sorting keys is required; trailing
    whitespace differences in notes count as different content (intentional
    — even cosmetic edits should be re-acknowledged).
    """
    canon = normalize(conventions)
    blob = json.dumps(canon, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _agent_path(repo_root: str | os.PathLike[str]) -> Path:
    return Path(repo_root) / ".claude" / "kanban-agent.json"


def record_ack(
    repo_root: str | os.PathLike[str],
    conventions: dict[str, Any] | None,
) -> Path:
    """Persist an acknowledgement of `conventions` into `.claude/kanban-agent.json`.

    Adds the field `acknowledgedConventions` with the hash and an ISO
    timestamp. Other fields in the file (notably `ap`) are preserved.
    """
    p = _agent_path(repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        try:
            existing = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except Exception:
            existing = {}
    else:
        existing = {}
    existing["acknowledgedConventions"] = {
        "hash": hash_conventions(conventions),
        "at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    p.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return p


def has_recent_ack(
    repo_root: str | os.PathLike[str],
    conventions: dict[str, Any] | None,
) -> bool:
    """Return True iff `.claude/kanban-agent.json` records an ack whose
    hash matches `conventions`. Allows /kanban:import-jira-code to skip
    the friction prompt when the user has already acknowledged this exact
    convention set in this repo.
    """
    p = _agent_path(repo_root)
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    ack = (data or {}).get("acknowledgedConventions") or {}
    if not isinstance(ack, dict):
        return False
    return ack.get("hash") == hash_conventions(conventions)
