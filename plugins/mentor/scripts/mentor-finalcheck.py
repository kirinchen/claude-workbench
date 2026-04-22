#!/usr/bin/env python3
"""mentor-finalcheck.py — Stop hook.

Aggregates compliance state at session end:
  - violations from framework_engine.review()
  - counts of edited Epic/Sprint/Issue/ADR docs this session
  - memory fan-out for Sprint retros + new ADRs (when memory integration on)

Never blocks the session.
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

# Auto-prepend bin dir so sibling CLI calls work.
_WB_BIN = os.path.expanduser("~/.claude-workbench/bin")
if os.path.isdir(_WB_BIN):
    _p = os.environ.get("PATH", "")
    if _WB_BIN not in _p.split(os.pathsep):
        os.environ["PATH"] = _WB_BIN + os.pathsep + _p

from framework_engine import (  # noqa: E402
    changed_files_since,
    load_config,
    read_frontmatter,
    review,
)


def _has_memory() -> bool:
    return shutil.which("workbench-memory") is not None


def _categorise(paths: list[str], cfg) -> dict[str, list[str]]:
    cats = {"epic": [], "sprint": [], "issue": [], "adr": [], "other_md": []}
    prefixes = {
        "epic": cfg.paths.epic.rstrip("/") + "/",
        "sprint": cfg.paths.sprint.rstrip("/") + "/",
        "issue": cfg.paths.issue.rstrip("/") + "/",
        "adr": cfg.paths.wiki.rstrip("/") + "/architecture-decisions/",
    }
    for p in paths:
        q = p.replace("\\", "/")
        matched = False
        for k, prefix in prefixes.items():
            if q.startswith(prefix) and q.endswith(".md"):
                cats[k].append(q)
                matched = True
                break
        if not matched and q.endswith(".md"):
            cats["other_md"].append(q)
    return cats


def _fanout_memory(proj: Path, cfg, touched: dict):
    if not _has_memory():
        return
    session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown")

    if cfg.integration.memory_save_sprint_retro:
        for sp_rel in touched.get("sprint", []):
            full = proj / sp_rel
            fm = read_frontmatter(full) or {}
            if str(fm.get("status", "")).lower() in ("review", "done"):
                try:
                    subprocess.run([
                        "workbench-memory", "save",
                        "--topic", f"Sprint {fm.get('id') or Path(sp_rel).stem} retrospective",
                        "--content", (full.read_text(encoding='utf-8')[:2000]
                                      if full.is_file() else ""),
                        "--tags", "sprint,retro,mentor",
                        "--source", f"mentor:sprint:{fm.get('id') or 'unknown'}",
                    ], capture_output=True, timeout=5)
                except Exception:
                    pass

    if cfg.integration.memory_save_adr:
        for adr_rel in touched.get("adr", []):
            full = proj / adr_rel
            fm = read_frontmatter(full) or {}
            if str(fm.get("status", "")).lower() == "accepted":
                try:
                    subprocess.run([
                        "workbench-memory", "save",
                        "--topic", f"ADR {fm.get('id', '?')}: {fm.get('title', '')}",
                        "--content", (full.read_text(encoding='utf-8')[:1500]
                                      if full.is_file() else ""),
                        "--tags", "adr,decision,mentor",
                        "--source", f"mentor:adr:{fm.get('id', 'unknown')}",
                    ], capture_output=True, timeout=5)
                except Exception:
                    pass


def main() -> int:
    try:
        event = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        event = {}

    cfg, cfg_path = load_config()
    if cfg is None or cfg_path is None:
        return 0
    proj = cfg_path.parent.parent

    changed = changed_files_since(proj, "HEAD~20")
    touched = _categorise(changed, cfg)
    violations = review(proj, cfg)

    lines: list[str] = []
    lines.append(f"mentor: session-end summary (mode: {cfg.mode}).")

    total_touched = sum(len(v) for v in touched.values())
    if total_touched:
        lines.append("")
        lines.append(f"Documents touched this session ({total_touched}):")
        for k in ("epic", "sprint", "issue", "adr", "other_md"):
            if touched[k]:
                lines.append(f"  {k}: {len(touched[k])}")
                for p in touched[k][:5]:
                    lines.append(f"    - {p}")

    if violations:
        lines.append("")
        lines.append(f"Compliance issues ({len(violations)}):")
        for v in violations[:10]:
            lines.append(f"  - [{v.kind}] {v.path}: {v.detail}")
        if len(violations) > 10:
            lines.append(f"  … {len(violations) - 10} more; run `workbench-mentor review` to see all.")

    # Memory fan-out (best-effort, never fatal)
    try:
        _fanout_memory(proj, cfg, touched)
    except Exception:
        pass

    if len(lines) == 1:  # only the header — nothing interesting
        return 0

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": "\n".join(lines),
        }
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
