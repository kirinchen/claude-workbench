#!/usr/bin/env python3
"""docsync-guard.py — PostToolUse hook (§6.8).

Fires after Edit/Write/MultiEdit. Detects pending doc sync for the file that
was just edited. Behaviour is gated on ``enforcement``:

  - silent: no output.
  - warn:   print a ``systemMessage`` reminding Claude of the pending doc(s).
  - block:  same warning, but exit 2 (tool-call blocking) ONLY when the kanban
            DONE gate is active and this edit is part of a task close. We do
            NOT block ordinary code edits — that's what ``warn`` is for; the
            gate lives in kanban-autocommit via ``workbench-docsync check``.

Exit 0 on any unexpected failure — hooks never crash Claude sessions.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from rule_engine import load_config, match_rules  # noqa: E402


def _read_event() -> dict:
    try:
        if sys.stdin.isatty():
            return {}
        return json.load(sys.stdin)
    except Exception:
        return {}


def _edited_path(event: dict) -> str | None:
    # Claude Code hook schema: ``tool_input`` holds the tool args.
    ti = event.get("tool_input") or {}
    p = ti.get("file_path") or ti.get("path")
    if not p:
        return None
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    if proj and p.startswith(proj + "/"):
        return p[len(proj) + 1:]
    # Try to make it project-relative via cwd.
    try:
        return str(Path(p).resolve().relative_to(Path.cwd().resolve()))
    except Exception:
        return p


def main() -> int:
    event = _read_event()
    edited = _edited_path(event)
    if not edited:
        return 0

    cfg, cfg_path = load_config()
    if cfg is None or cfg_path is None:
        return 0
    if cfg.enforcement == "silent":
        return 0

    matches = match_rules(cfg, [edited])
    if not matches:
        return 0

    # Build the warning body.
    lines = [f"docsync: `{edited}` matched {len({r.id for _, r in matches})} "
             f"rule(s). Consider updating the mapped doc(s) in this session:"]
    for _, rule in matches:
        for doc in rule.docs:
            if doc.required or doc.required_if:
                hint = ""
                if doc.required_if:
                    hint = f"  (required_if: {doc.required_if})"
                section = f" · §{doc.section}" if doc.section else ""
                lines.append(f"  - {doc.path}{section}{hint}   (rule: {rule.id})")

    msg = "\n".join(lines)
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": msg,
        }
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
