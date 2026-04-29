"""Detect Jira-related MCP servers configured at user / project / .mcp.json scope.

SPEC §18.2 rationale: when the kanban plugin is the sanctioned path for an
agent to touch Jira, a separate Jira MCP server (Atlassian Rovo,
mcp-atlassian, ...) bypasses AP routing, anti-self-approve, and the comment
prefix grammar. This module surfaces such servers as a warning so the user
can decide whether to scope them to user-only or remove them.

Public surface:
    scan(project_root) -> list[Conflict]

Conflict.source is the absolute path of the settings file the entry came from.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


_KEYWORD_RE = re.compile(r"(?i)atlassian|jira|rovo|mcp-atlassian")


@dataclass
class Conflict:
    server_name: str
    source: str       # absolute path to the settings file
    matched_on: str   # short reason ("name", "command", "args", "url")


def _candidate_paths(project_root: str | os.PathLike[str]) -> list[Path]:
    project_root = Path(project_root)
    return [
        Path.home() / ".claude" / "settings.json",
        project_root / ".claude" / "settings.json",
        project_root / ".mcp.json",
    ]


def _scan_servers(blob: dict, source: Path) -> list[Conflict]:
    servers = blob.get("mcpServers")
    if not isinstance(servers, dict):
        return []
    out: list[Conflict] = []
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            continue
        if _KEYWORD_RE.search(name or ""):
            out.append(Conflict(name, str(source), "name"))
            continue
        for field in ("command", "url"):
            v = cfg.get(field)
            if isinstance(v, str) and _KEYWORD_RE.search(v):
                out.append(Conflict(name, str(source), field))
                break
        else:
            args = cfg.get("args")
            if isinstance(args, list):
                joined = " ".join(str(a) for a in args)
                if _KEYWORD_RE.search(joined):
                    out.append(Conflict(name, str(source), "args"))
    return out


def scan(project_root: str | os.PathLike[str]) -> list[Conflict]:
    """Walk all candidate settings files; return any matches.

    Missing files / parse errors are silently skipped — this is best-effort
    surfacing, not a validator.
    """
    out: list[Conflict] = []
    for path in _candidate_paths(project_root):
        if not path.exists():
            continue
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(blob, dict):
            continue
        out.extend(_scan_servers(blob, path))
    return out
