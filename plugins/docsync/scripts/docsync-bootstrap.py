#!/usr/bin/env python3
"""docsync-bootstrap.py — SessionStart hook (§6.8).

Reads ``.claude/docsync.yaml`` and emits a ``systemMessage``/``additionalContext``
reminder listing the bootstrap docs Claude should read before making code
changes. Never blocks the session — always exits 0.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from rule_engine import load_config  # noqa: E402


def main() -> int:
    cfg, path = load_config()
    if cfg is None or path is None:
        return 0  # no docsync config — silent

    proj = path.parent.parent  # .claude/docsync.yaml → project root

    present = []
    missing = []
    for doc in cfg.bootstrap_docs:
        full = proj / doc
        (present if full.is_file() else missing).append(doc)

    if not present and not missing:
        return 0

    lines = ["docsync: at session start, read these bootstrap docs before "
             "making non-trivial code changes."]
    if present:
        lines.append("")
        lines.append("Present:")
        for d in present:
            lines.append(f"  - {d}")
    if missing:
        lines.append("")
        lines.append("Referenced but missing (config may be stale):")
        for d in missing:
            lines.append(f"  - {d}")
    lines.append("")
    lines.append(f"Enforcement: {cfg.enforcement}. "
                 f"Config: {path.relative_to(proj) if path.is_relative_to(proj) else path}")

    msg = "\n".join(lines)
    out = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": msg,
        }
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Never allow a SessionStart hook to break the session.
        sys.exit(0)
