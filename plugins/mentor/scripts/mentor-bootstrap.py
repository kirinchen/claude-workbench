#!/usr/bin/env python3
"""mentor-bootstrap.py — SessionStart hook.

Emits `additionalContext` that tells Claude:
  - which bootstrap docs to read before any code change
  - the current active sprint (development mode) and its open issues
  - the framework mode in effect

Never blocks the session. Always exits 0.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# Prepend workbench bin so subprocess-less sibling detection works.
_WB_BIN = os.path.expanduser("~/.claude-workbench/bin")
if os.path.isdir(_WB_BIN):
    _p = os.environ.get("PATH", "")
    if _WB_BIN not in _p.split(os.pathsep):
        os.environ["PATH"] = _WB_BIN + os.pathsep + _p

from framework_engine import (  # noqa: E402
    active_sprint,
    kanban_installed,
    list_files,
    load_config,
    read_frontmatter,
)


def main() -> int:
    cfg, path = load_config()
    if cfg is None or path is None:
        return 0  # no mentor config — silent
    proj = path.parent.parent

    lines: list[str] = []
    lines.append(f"mentor: framework mode is `{cfg.mode}`.")
    lines.append("")

    # Bootstrap docs
    bootstrap = list(cfg.agent_behavior.bootstrap_docs or [])
    present, missing = [], []
    for d in bootstrap:
        full = proj / d if not d.startswith("doc/Sprint/active") else None
        if full and full.is_file():
            present.append(d)
        elif full is None:
            # doc/Sprint/active is a synthesised marker — resolved below
            continue
        else:
            missing.append(d)

    if cfg.mode == "development":
        sprint_p = active_sprint(proj, cfg)
        if sprint_p:
            present.append(str(sprint_p.relative_to(proj)) + "  [active sprint]")
        else:
            lines.append(
                "No sprint is marked `status: active` in the Sprint/ directory. "
                "Run `/mentor:sprint-start` (when available) or mark one active by hand."
            )
            lines.append("")

    if present:
        lines.append("Before making non-trivial code changes, read these:")
        for d in present:
            lines.append(f"  - {d}")
        lines.append("")
    if missing:
        lines.append("Config references these docs but they're missing on disk:")
        for d in missing:
            lines.append(f"  - {d}")
        lines.append("")

    # Development-mode context: open issues count
    if cfg.mode == "development":
        idir = proj / cfg.paths.issue
        if idir.is_dir():
            issues = list_files(idir)
            open_count = 0
            for p in issues:
                fm = read_frontmatter(p) or {}
                status = str(fm.get("status", "open")).lower()
                if status in ("open", "in_progress"):
                    open_count += 1
            lines.append(f"Open issues: {open_count} of {len(issues)} total.")

        # Before picking a task, verify issue context
        if cfg.agent_behavior.require_issue_context:
            lines.append("")
            lines.append(
                "When picking a task, first trace its parent Issue and Epic "
                "(check Issue/<issue-id>.md frontmatter). "
                "Confirm the work aligns with the Epic's Success Criteria before starting."
            )

    # Kanban coexistence note
    if not kanban_installed(proj):
        lines.append("")
        lines.append(
            f"Kanban plugin not detected. Mentor is using `{cfg.paths.task_fallback}` "
            "as the task list. Install the kanban plugin for richer task state."
        )

    if not lines:
        return 0

    out = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(lines).strip(),
        }
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
