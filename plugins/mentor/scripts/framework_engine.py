"""framework_engine.py — pure-logic core of the mentor plugin.

Loads ``.claude/mentor.yaml``, resolves the active framework mode (basic |
development), enumerates bootstrap docs, traces task ↔ issue ↔ epic links,
and validates frontmatter on Epic / Sprint / Issue / ADR documents.

Importable by hook scripts and the CLI. No side-effects at import time.

YAML loading: PyYAML preferred; falls back to a small subset parser so the
plugin works in minimal Python environments without pip deps.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

# -----------------------------------------------------------------------------
# YAML load — PyYAML preferred; fallback handles the shapes we ship.
# -----------------------------------------------------------------------------

def _try_pyyaml():
    try:
        import yaml  # type: ignore
        return yaml
    except Exception:
        return None


def load_yaml(path: str | os.PathLike) -> dict:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    yaml = _try_pyyaml()
    if yaml is not None:
        return yaml.safe_load(text) or {}
    return _fallback_yaml_load(text)


def _fallback_yaml_load(text: str) -> dict:
    """Narrow YAML subset parser — mappings, lists, list-of-dicts, scalars,
    `#` comments, `export KEY=VAL` ignored (not valid YAML). Raises on
    anchors, flow syntax, block scalars, tags. Enough for mentor config +
    frontmatter in our templates.
    """
    lines = []
    for raw in text.splitlines():
        if "#" in raw:
            hi = -1
            for i, ch in enumerate(raw):
                if ch == "#" and (i == 0 or raw[i - 1] in " \t"):
                    hi = i
                    break
            if hi >= 0:
                raw = raw[:hi]
        if not raw.strip():
            continue
        lines.append(raw.rstrip())

    def _coerce(v: str):
        v = v.strip()
        if v == "" or v == "~" or v.lower() == "null":
            return None
        if v.lower() == "true":
            return True
        if v.lower() == "false":
            return False
        if v.startswith('"') and v.endswith('"'):
            return v[1:-1]
        if v.startswith("'") and v.endswith("'"):
            return v[1:-1]
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            if not inner:
                return []
            return [_coerce(x.strip()) for x in inner.split(",")]
        try:
            if "." not in v:
                return int(v)
        except Exception:
            pass
        try:
            return float(v)
        except Exception:
            pass
        return v

    root: dict = {}
    stack: list = [("dict", -1, root)]

    def _close_pending(indent: int, kind: str):
        if not stack:
            return
        top = stack[-1]
        if top[0] != "pending_key":
            return
        _, pind, parent, key = top
        if indent <= pind:
            stack.pop()
            if parent.get(key) is None:
                parent[key] = [] if kind == "list" else {}
            return
        child = [] if kind == "list" else {}
        parent[key] = child
        stack.pop()
        stack.append((kind, pind, child))

    for line in lines:
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()
        is_li = content.startswith("- ")

        if stack and stack[-1][0] == "pending_key" and indent > stack[-1][1]:
            _close_pending(indent, "list" if is_li else "dict")

        while stack:
            top = stack[-1]
            kind, pind = top[0], top[1]
            if kind == "pending_key":
                _, pind, parent, key = top
                if indent <= pind:
                    stack.pop()
                    if parent.get(key) is None:
                        parent[key] = None
                    continue
                break
            if kind == "list" and is_li and indent == pind:
                break
            if indent > pind:
                break
            stack.pop()

        if not stack:
            raise ValueError(f"stack underflow at {line!r}")
        top = stack[-1]
        pkind, parent = top[0], top[2]

        if is_li:
            if pkind != "list":
                raise ValueError(f"list item in non-list context at {line!r}")
            body = content[2:].strip()
            if ":" in body and not (body.startswith('"') or body.startswith("'")):
                k, _, v = body.partition(":")
                k, v = k.strip(), v.strip()
                d: dict = {}
                parent.append(d)
                if v == "":
                    stack.append(("dict", indent, d))
                    stack.append(("pending_key", indent + 2, d, k))
                else:
                    d[k] = _coerce(v)
                    stack.append(("dict", indent, d))
            else:
                parent.append(_coerce(body))
            continue

        if ":" not in content:
            raise ValueError(f"cannot parse line: {line!r}")
        key, _, value = content.partition(":")
        key, value = key.strip(), value.strip()
        if pkind != "dict":
            raise ValueError(f"mapping entry in non-dict at {line!r}")
        if value == "":
            parent[key] = None
            stack.append(("pending_key", indent, parent, key))
        else:
            parent[key] = _coerce(value)

    while stack and stack[-1][0] == "pending_key":
        stack.pop()
    return root


# -----------------------------------------------------------------------------
# Data classes
# -----------------------------------------------------------------------------

@dataclass
class Paths:
    spec: str = "doc/SPEC.md"
    wiki: str = "doc/Wiki/"
    epic: str = "doc/Epic/"
    sprint: str = "doc/Sprint/"
    issue: str = "doc/Issue/"
    task_fallback: str = "doc/task.md"


@dataclass
class IntegrationFlags:
    kanban_enabled: str = "auto"               # auto | force | disable
    kanban_sync_issue_to_task: bool = True
    kanban_block_done_if_issue_incomplete: bool = False
    memory_enabled: str = "auto"
    memory_save_sprint_retro: bool = True
    memory_save_adr: bool = True
    notify_enabled: str = "auto"
    notify_sprint_end: bool = True
    notify_epic_done: bool = True


@dataclass
class AgentBehavior:
    bootstrap_docs: list = field(default_factory=list)
    require_issue_context: bool = True
    auto_retrospective: bool = True
    require_adr_on_decision: bool = True


@dataclass
class MentorConfig:
    schema_version: int = 1
    mode: str = "basic"                        # basic | development
    paths: Paths = field(default_factory=Paths)
    id_patterns: dict = field(default_factory=lambda: {
        "epic": "EPIC-{seq:03d}",
        "sprint": "SPRINT-{year}-W{week:02d}",
        "issue": "ISSUE-{seq:03d}",
        "task": "task-{seq:03d}",
    })
    agent_behavior: AgentBehavior = field(default_factory=AgentBehavior)
    templates_source: str = "builtin"          # builtin | custom
    templates_custom_path: str = ".claude/mentor-templates/"
    integration: IntegrationFlags = field(default_factory=IntegrationFlags)

    @classmethod
    def from_dict(cls, raw: dict) -> "MentorConfig":
        paths_raw = raw.get("paths") or {}
        paths = Paths(
            spec=paths_raw.get("spec", "doc/SPEC.md"),
            wiki=paths_raw.get("wiki", "doc/Wiki/"),
            epic=paths_raw.get("epic", "doc/Epic/"),
            sprint=paths_raw.get("sprint", "doc/Sprint/"),
            issue=paths_raw.get("issue", "doc/Issue/"),
            task_fallback=paths_raw.get("task_fallback", "doc/task.md"),
        )
        ab_raw = raw.get("agent_behavior") or {}
        ab = AgentBehavior(
            bootstrap_docs=list(ab_raw.get("bootstrap_docs") or []),
            require_issue_context=bool(ab_raw.get("require_issue_context", True)),
            auto_retrospective=bool(ab_raw.get("auto_retrospective", True)),
            require_adr_on_decision=bool(ab_raw.get("require_adr_on_decision", True)),
        )
        tpl = raw.get("templates") or {}
        integ_raw = raw.get("integration") or {}
        k_raw = (integ_raw.get("kanban") or {}) if isinstance(integ_raw, dict) else {}
        m_raw = (integ_raw.get("memory") or {}) if isinstance(integ_raw, dict) else {}
        n_raw = (integ_raw.get("notify") or {}) if isinstance(integ_raw, dict) else {}
        integ = IntegrationFlags(
            kanban_enabled=str(k_raw.get("enabled", "auto")),
            kanban_sync_issue_to_task=bool(k_raw.get("sync_issue_to_task", True)),
            kanban_block_done_if_issue_incomplete=bool(
                k_raw.get("block_done_if_issue_incomplete", False)
            ),
            memory_enabled=str(m_raw.get("enabled", "auto")),
            memory_save_sprint_retro=bool(m_raw.get("save_sprint_retro", True)),
            memory_save_adr=bool(m_raw.get("save_adr", True)),
            notify_enabled=str(n_raw.get("enabled", "auto")),
            notify_sprint_end=bool(n_raw.get("notify_sprint_end", True)),
            notify_epic_done=bool(n_raw.get("notify_epic_done", True)),
        )
        return cls(
            schema_version=int(raw.get("schema_version", 1)),
            mode=str(raw.get("mode", "basic")),
            paths=paths,
            id_patterns=dict(raw.get("id_patterns") or {}),
            agent_behavior=ab,
            templates_source=str(tpl.get("source", "builtin")),
            templates_custom_path=str(tpl.get("custom_path", ".claude/mentor-templates/")),
            integration=integ,
        )


# -----------------------------------------------------------------------------
# Config discovery
# -----------------------------------------------------------------------------

def find_config(start: Path | None = None) -> Path | None:
    cwd = Path(start or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    for d in [cwd, *cwd.parents]:
        candidate = d / ".claude" / "mentor.yaml"
        if candidate.is_file():
            return candidate
    return None


def load_config(start: Path | None = None) -> tuple[MentorConfig | None, Path | None]:
    path = find_config(start)
    if path is None:
        return None, None
    try:
        raw = load_yaml(path)
    except Exception:
        return None, path
    return MentorConfig.from_dict(raw or {}), path


# -----------------------------------------------------------------------------
# Frontmatter parsing (for Epic/Sprint/Issue/ADR .md files)
# -----------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(text: str) -> dict | None:
    """Return the frontmatter dict or None if no frontmatter is present."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        return _fallback_yaml_load(m.group(1))
    except Exception:
        return None


def read_frontmatter(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    return parse_frontmatter(text)


# -----------------------------------------------------------------------------
# Document discovery
# -----------------------------------------------------------------------------

def list_files(dir_path: Path, suffix: str = ".md") -> list[Path]:
    if not dir_path.is_dir():
        return []
    out = []
    for p in sorted(dir_path.iterdir()):
        if p.is_file() and p.name.endswith(suffix) and p.name != "README.md":
            out.append(p)
    return out


def active_sprint(proj: Path, cfg: MentorConfig) -> Path | None:
    """Return the path of the first Sprint/*.md whose frontmatter status is
    'active'. Returns None if none found or config paths missing."""
    sdir = proj / cfg.paths.sprint
    if not sdir.is_dir():
        return None
    for p in list_files(sdir):
        fm = read_frontmatter(p) or {}
        if str(fm.get("status", "")).lower() == "active":
            return p
    return None


# -----------------------------------------------------------------------------
# Tracing: task → issue → epic
# -----------------------------------------------------------------------------

@dataclass
class TraceResult:
    task_id: str
    issue_path: Path | None = None
    issue_id: str | None = None
    issue_fm: dict = field(default_factory=dict)
    epic_path: Path | None = None
    epic_id: str | None = None
    epic_fm: dict = field(default_factory=dict)
    sprint_path: Path | None = None
    sprint_id: str | None = None


def trace_task(proj: Path, cfg: MentorConfig, task_id: str) -> TraceResult:
    """Find Issue whose frontmatter.tasks contains ``task_id``, then its Epic
    and Sprint. All fields may be None if the chain is broken."""
    r = TraceResult(task_id=task_id)

    idir = proj / cfg.paths.issue
    for p in list_files(idir):
        fm = read_frontmatter(p) or {}
        tasks = fm.get("tasks") or []
        if isinstance(tasks, list) and task_id in tasks:
            r.issue_path = p
            r.issue_id = fm.get("id")
            r.issue_fm = fm
            break

    if r.issue_fm:
        epic_id = r.issue_fm.get("epic")
        sprint_id = r.issue_fm.get("sprint")
        if epic_id:
            r.epic_id = epic_id
            edir = proj / cfg.paths.epic
            for p in list_files(edir):
                fm = read_frontmatter(p) or {}
                if fm.get("id") == epic_id:
                    r.epic_path = p
                    r.epic_fm = fm
                    break
        if sprint_id:
            r.sprint_id = sprint_id
            sdir = proj / cfg.paths.sprint
            for p in list_files(sdir):
                fm = read_frontmatter(p) or {}
                if fm.get("id") == sprint_id or sprint_id in p.name:
                    r.sprint_path = p
                    break
    return r


# -----------------------------------------------------------------------------
# Compliance review
# -----------------------------------------------------------------------------

@dataclass
class Violation:
    kind: str       # missing_doc | no_frontmatter | orphan_issue | drift | etc.
    path: str
    detail: str


def review(proj: Path, cfg: MentorConfig) -> list[Violation]:
    """Walk the configured document tree, return structural violations.

    Never crashes: unreadable files are reported, not raised.
    """
    out: list[Violation] = []

    # SPEC must exist
    spec = proj / cfg.paths.spec
    if not spec.is_file():
        out.append(Violation("missing_doc", str(spec.relative_to(proj)),
                             "SPEC file declared in paths.spec is missing"))

    if cfg.mode == "basic":
        return out

    # development mode — verify Epic/Sprint/Issue directories + frontmatter
    for subdir_key, required_fm_fields in [
        ("epic", {"id", "title", "status"}),
        ("sprint", {"id", "start", "end", "status"}),
        ("issue", {"id", "title", "status"}),
    ]:
        subdir = proj / getattr(cfg.paths, subdir_key)
        if not subdir.is_dir():
            out.append(Violation("missing_doc", str(subdir.relative_to(proj)),
                                 f"{subdir_key} directory does not exist"))
            continue
        for p in list_files(subdir):
            fm = read_frontmatter(p)
            if fm is None:
                out.append(Violation("no_frontmatter",
                                     str(p.relative_to(proj)),
                                     "file has no YAML frontmatter"))
                continue
            missing = required_fm_fields - set(fm.keys())
            if missing:
                out.append(Violation("drift",
                                     str(p.relative_to(proj)),
                                     f"frontmatter missing: {', '.join(sorted(missing))}"))

    # Orphan issue detection (issue.epic points to non-existent epic)
    epic_ids = set()
    edir = proj / cfg.paths.epic
    if edir.is_dir():
        for p in list_files(edir):
            fm = read_frontmatter(p) or {}
            if fm.get("id"):
                epic_ids.add(fm["id"])

    idir = proj / cfg.paths.issue
    if idir.is_dir():
        for p in list_files(idir):
            fm = read_frontmatter(p) or {}
            ep = fm.get("epic")
            if ep and ep not in epic_ids:
                out.append(Violation("orphan_issue",
                                     str(p.relative_to(proj)),
                                     f"references non-existent epic {ep}"))
    return out


# -----------------------------------------------------------------------------
# Git helpers
# -----------------------------------------------------------------------------

def _git(cwd: Path, *args) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), check=False,
                           capture_output=True, text=True, timeout=10)
        return r.stdout
    except Exception:
        return ""


def changed_files_since(cwd: Path, ref: str) -> list[str]:
    out = set()
    for line in (_git(cwd, "diff", "--name-only", f"{ref}...HEAD").splitlines()
                 + _git(cwd, "diff", "--name-only").splitlines()
                 + _git(cwd, "diff", "--cached", "--name-only").splitlines()
                 + _git(cwd, "ls-files", "--others", "--exclude-standard").splitlines()):
        n = line.strip()
        if n:
            out.add(n)
    return sorted(out)


# -----------------------------------------------------------------------------
# Sibling detection
# -----------------------------------------------------------------------------

def has_sibling(name: str) -> bool:
    import shutil
    return shutil.which(f"workbench-{name}") is not None


def kanban_installed(proj: Path) -> bool:
    """Kanban is 'installed' if the CLI is on PATH OR kanban.json exists."""
    if has_sibling("kanban"):
        return True
    return (proj / "kanban.json").is_file()


# -----------------------------------------------------------------------------
# JSON serialisation helpers
# -----------------------------------------------------------------------------

def config_to_dict(cfg: MentorConfig) -> dict:
    return {
        "schema_version": cfg.schema_version,
        "mode": cfg.mode,
        "paths": {
            "spec": cfg.paths.spec,
            "wiki": cfg.paths.wiki,
            "epic": cfg.paths.epic,
            "sprint": cfg.paths.sprint,
            "issue": cfg.paths.issue,
            "task_fallback": cfg.paths.task_fallback,
        },
        "id_patterns": cfg.id_patterns,
        "agent_behavior": {
            "bootstrap_docs": cfg.agent_behavior.bootstrap_docs,
            "require_issue_context": cfg.agent_behavior.require_issue_context,
            "auto_retrospective": cfg.agent_behavior.auto_retrospective,
            "require_adr_on_decision": cfg.agent_behavior.require_adr_on_decision,
        },
        "templates": {
            "source": cfg.templates_source,
            "custom_path": cfg.templates_custom_path,
        },
        "integration": {
            "kanban": {
                "enabled": cfg.integration.kanban_enabled,
                "sync_issue_to_task": cfg.integration.kanban_sync_issue_to_task,
                "block_done_if_issue_incomplete": cfg.integration.kanban_block_done_if_issue_incomplete,
            },
            "memory": {
                "enabled": cfg.integration.memory_enabled,
                "save_sprint_retro": cfg.integration.memory_save_sprint_retro,
                "save_adr": cfg.integration.memory_save_adr,
            },
            "notify": {
                "enabled": cfg.integration.notify_enabled,
                "notify_sprint_end": cfg.integration.notify_sprint_end,
                "notify_epic_done": cfg.integration.notify_epic_done,
            },
        },
    }
