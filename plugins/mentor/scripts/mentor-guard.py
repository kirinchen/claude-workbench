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

FEAT_MAP_REL = "doc/feat_map.md"


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
    """Return document type (epic|sprint|issue|adr|feat_map) or None if not a
    mentor-governed path."""
    pr = path_rel.replace("\\", "/")
    epic_dir = cfg.paths.epic.rstrip("/")
    sprint_dir = cfg.paths.sprint.rstrip("/")
    issue_dir = cfg.paths.issue.rstrip("/")
    wiki_dir = cfg.paths.wiki.rstrip("/") + "/architecture-decisions"

    # feat_map.md lives at a fixed path per spec (kirinchen/claude-workbench#60
    # §2) — only meaningful in development mode.
    if pr == FEAT_MAP_REL and cfg.mode == "development":
        return "feat_map"
    if pr.startswith(epic_dir + "/") and pr.endswith(".md") and "README" not in pr:
        return "epic"
    if pr.startswith(sprint_dir + "/") and pr.endswith(".md") and "README" not in pr:
        return "sprint"
    if pr.startswith(issue_dir + "/") and pr.endswith(".md") and "README" not in pr:
        return "issue"
    if pr.startswith(wiki_dir + "/") and pr.endswith(".md"):
        return "adr"
    return None


def _resulting_content(event: dict) -> str | None:
    """Best-effort reconstruction of the file content *after* this tool call.

    The frontmatter check must see the whole resulting file, not just an edit
    fragment. Claude Code's PreToolUse event carries:
      - tool_input.content                    (Write — the full new file)
      - tool_input.old_string / .new_string   (Edit — a replacement fragment)
      - tool_input.edits[]                     (MultiEdit — many fragments)

    The previous implementation returned Edit's ``new_string`` verbatim. When an
    edit touched the *body* of an Epic/Sprint/Issue/ADR (the common case), that
    fragment contained no ``---`` block, so ``parse_frontmatter`` returned None
    and the guard falsely warned "no YAML frontmatter block found at top of
    file" — even though the file on disk has valid frontmatter. Untracked git
    state and non-ASCII (e.g. Chinese) titles are irrelevant; the bug was purely
    that we inspected the fragment instead of the file.

    We now start from the current on-disk content and apply the replacement(s),
    which fixes the false positive *and* lets us correctly flag an edit that
    removes a required frontmatter field. Returns None when the resulting content
    cannot be determined (unreadable file, MultiEdit on an absent file); the
    caller then skips the pre-check and trusts the Stop-hook compliance run.
    """
    ti = event.get("tool_input") or {}
    tool = event.get("tool_name")

    if tool == "Write":
        return ti.get("content")

    if tool in ("Edit", "MultiEdit"):
        abs_path = ti.get("file_path") or ti.get("path")
        try:
            base = Path(abs_path).read_text(encoding="utf-8") if abs_path else None
        except Exception:
            base = None
        if base is None:
            return None
        edits = ti.get("edits") if tool == "MultiEdit" else [ti]
        for e in edits or []:
            old = e.get("old_string")
            new = e.get("new_string") or ""
            if not old:
                continue
            if e.get("replace_all"):
                base = base.replace(old, new)
            else:
                base = base.replace(old, new, 1)
        return base

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

    proposed = _resulting_content(event)

    # feat_map.md has its own grammar (issue #60) — delegate to feat_map.py.
    if doc_type == "feat_map":
        if not proposed:
            # MultiEdit / unknown shape — skip; Stop-hook review() will catch it.
            return 0
        from feat_map import validate as fm_validate  # local import
        fm_issues = fm_validate(proposed)
        if not fm_issues:
            return 0
        bullets = [f"  - {i.code} (line {i.line}): {i.detail}" for i in fm_issues[:10]]
        more = f"\n  …{len(fm_issues) - 10} more" if len(fm_issues) > 10 else ""
        hint = (
            f"mentor: `{edited}` would violate the feat_map.md spec "
            f"(kirinchen/claude-workbench#60):\n"
            + "\n".join(bullets)
            + more
            + "\nSee `${CLAUDE_PLUGIN_ROOT}/frameworks/development/templates/feat_map.md` "
            "for the canonical shape, or run `/mentor:renewtree` to regenerate."
        )
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": hint,
            }
        }))
        return 0

    required = REQUIRED_BY_TYPE.get(doc_type, set())
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
