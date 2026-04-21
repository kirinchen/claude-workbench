#!/usr/bin/env python3
"""docsync-finalcheck.py — Stop hook (§6.8).

Runs when the session ends. Aggregates code edits since the session started,
reports any pending doc syncs, and (if configured) fans out a summary into the
memory plugin via ``workbench-memory save``.

Always exits 0.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from rule_engine import (  # noqa: E402
    changed_files_since,
    load_config,
    pending_syncs,
)

SINCE_DEFAULT = "HEAD~20"


def _has_workbench_memory() -> bool:
    return shutil.which("workbench-memory") is not None


def _session_id(event: dict) -> str:
    return (
        event.get("session_id")
        or os.environ.get("CLAUDE_SESSION_ID")
        or "unknown"
    )


def main() -> int:
    try:
        event = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        event = {}

    cfg, cfg_path = load_config()
    if cfg is None or cfg_path is None:
        return 0

    proj = cfg_path.parent.parent
    changed = changed_files_since(proj, SINCE_DEFAULT)
    if not changed:
        return 0

    pending = pending_syncs(cfg, changed)

    lines = [f"docsync: session-end summary ({len(changed)} changed files)."]
    if pending:
        lines.append("")
        lines.append("Pending doc updates:")
        for p in pending:
            required_hint = "" if p.required and not p.required_if else f" ({p.required_if or 'optional'})"
            lines.append(f"  - {p.doc_path}"
                         f"{' §' + p.doc_section if p.doc_section else ''}"
                         f"{required_hint}   ← {p.code_path}")
    else:
        lines.append("No pending syncs — all rules satisfied.")

    msg = "\n".join(lines)
    out = {"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": msg}}
    print(json.dumps(out))

    # Sibling fan-out: memory summary (§8.5)
    integration = cfg.integration or {}
    mem = (integration.get("memory") or {}) if isinstance(integration, dict) else {}
    if mem.get("summarize_doc_changes") and _has_workbench_memory():
        touched_docs = {p.doc_path for p in pending}
        # Also include docs that WERE updated in this diff.
        touched_docs.update(
            c for c in changed if c.lower().endswith((".md", ".rst", ".mdx"))
        )
        for doc in sorted(touched_docs):
            try:
                subprocess.run(
                    [
                        "workbench-memory", "save",
                        "--topic", f"Doc update: {doc}",
                        "--content", msg[:500],
                        "--tags", f"docsync,{Path(doc).stem}",
                        "--source", f"docsync:{_session_id(event)}",
                    ],
                    capture_output=True, timeout=5,
                )
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
