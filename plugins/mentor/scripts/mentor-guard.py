#!/usr/bin/env python3
"""mentor-guard.py — PreToolUse hook.

Fires on Edit/Write/MultiEdit. When the target is an Epic/Sprint/Issue/ADR
document, checks that the file has valid YAML frontmatter matching the
document type. **Warn-only** — never exits non-zero, just injects
`additionalContext` reminding Claude to follow the template.

This is deliberately gentle. The authoritative compliance check is
`/mentor:review` / `workbench-mentor review`, which can exit 2 and is used
by CI / kanban DONE-gate etc.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from framework_engine import (  # noqa: E402
    load_config,
    parse_frontmatter,
)

REQUIRED_BY_TYPE = {
    "epic":   {"id", "title", "status"},
    "sprint": {"id", "start", "end", "status"},
    "issue":  {"id", "title", "status"},
    "adr":    {"id", "title", "status", "date"},
}


def _read_event() -> dict:
    try:
        if sys.stdin.isatty():
            return {}
        return json.load(sys.stdin)
    except Exception:
        return {}


def _edited_path(event: dict) -> str | None:
    ti = event.get("tool_input") or {}
    p = ti.get("file_path") or ti.get("path")
    if not p:
        return None
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    if proj and p.startswith(proj + "/"):
        return p[len(proj) + 1:]
    try:
        return str(Path(p).resolve().relative_to(Path.cwd().resolve()))
    except Exception:
        return p


def _classify(path_rel: str, cfg) -> str | None:
    """Return document type (epic|sprint|issue|adr) or None if not a mentor-
    governed path."""
    pr = path_rel.replace("\\", "/")
    epic_dir = cfg.paths.epic.rstrip("/")
    sprint_dir = cfg.paths.sprint.rstrip("/")
    issue_dir = cfg.paths.issue.rstrip("/")
    wiki_dir = cfg.paths.wiki.rstrip("/") + "/architecture-decisions"

    if pr.startswith(epic_dir + "/") and pr.endswith(".md") and "README" not in pr:
        return "epic"
    if pr.startswith(sprint_dir + "/") and pr.endswith(".md") and "README" not in pr:
        return "sprint"
    if pr.startswith(issue_dir + "/") and pr.endswith(".md") and "README" not in pr:
        return "issue"
    if pr.startswith(wiki_dir + "/") and pr.endswith(".md"):
        return "adr"
    return None


def _read_proposed_body(event: dict) -> str | None:
    """Best-effort extraction of the new content about to be written.

    Claude Code's PreToolUse event carries either:
      - tool_input.content (for Write)
      - tool_input.new_string (for Edit)
    We cannot fully reconstruct MultiEdit here — for those we skip the
    frontmatter pre-check and trust the post-write Stop-hook compliance run.
    """
    ti = event.get("tool_input") or {}
    tool = event.get("tool_name")
    if tool == "Write":
        return ti.get("content")
    if tool == "Edit":
        return ti.get("new_string")
    return None


def main() -> int:
    event = _read_event()
    edited = _edited_path(event)
    if not edited:
        return 0

    cfg, _path = load_config()
    if cfg is None:
        return 0

    doc_type = _classify(edited, cfg)
    if doc_type is None:
        return 0

    required = REQUIRED_BY_TYPE.get(doc_type, set())
    proposed = _read_proposed_body(event)
    fm = parse_frontmatter(proposed) if proposed else None

    problems: list[str] = []
    if fm is None:
        problems.append("no YAML frontmatter block found at top of file")
    else:
        missing = required - set(fm.keys())
        if missing:
            problems.append("frontmatter missing fields: " + ", ".join(sorted(missing)))

    if not problems:
        return 0

    hint = (
        f"mentor: `{edited}` looks like a {doc_type} document but {'; '.join(problems)}.\n"
        f"Follow the {doc_type} template (see "
        f"`${{CLAUDE_PLUGIN_ROOT}}/frameworks/development/templates/`) — required "
        f"frontmatter fields: {', '.join(sorted(required))}."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": hint,
        }
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
