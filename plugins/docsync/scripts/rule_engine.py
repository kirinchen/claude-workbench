"""rule_engine.py — pure-logic core of the docsync plugin (§6).

This module has no I/O beyond reading git state and the YAML config. Hook
scripts and the CLI both import it; keeping it importable (not executable)
means hooks can run under ``python3 scripts/docsync-bootstrap.py`` etc.

YAML loading: if PyYAML is absent, falls back to a tiny subset parser that
handles the shapes our config uses. We deliberately avoid bringing pip deps
into a Claude Code plugin hook.
"""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# -----------------------------------------------------------------------------
# YAML load — PyYAML preferred; fallback parser handles our subset.
# -----------------------------------------------------------------------------

def _try_pyyaml():
    try:
        import yaml  # type: ignore
        return yaml
    except Exception:
        return None


def load_yaml(path: str | os.PathLike) -> dict:
    """Load a YAML file. Uses PyYAML if available; otherwise a narrow fallback
    parser that handles keys, scalars, lists, and nested mappings with the
    indentation / syntax used by docsync templates. Raises ValueError on a
    shape the fallback can't handle — in which case the user needs PyYAML."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    yaml = _try_pyyaml()
    if yaml is not None:
        return yaml.safe_load(text) or {}
    return _fallback_yaml_load(text)


def _fallback_yaml_load(text: str) -> dict:
    """Very small YAML subset parser. Handles mappings, lists, and list-of-dicts
    at arbitrary indent levels — enough for docsync templates. Raises
    ValueError on shapes it can't handle (tags, anchors, flow syntax,
    block scalars, etc.).
    """
    # Normalise: strip comments, drop blank lines, but keep indent.
    lines = []
    for raw in text.splitlines():
        if "#" in raw:
            hash_idx = -1
            for i, ch in enumerate(raw):
                if ch == "#" and (i == 0 or raw[i - 1] in " \t"):
                    hash_idx = i
                    break
            if hash_idx >= 0:
                raw = raw[:hash_idx]
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

    # Stack frames:
    #   ("dict", indent, container)          — parent is a mapping
    #   ("list", indent, container)          — parent is a list
    #   ("pending_key", indent, parent_dict, key)
    #       — saw `key:` with no value; child container will be created when
    #         the next deeper line arrives (dict if it's `key:…`, list if `- `).
    root: dict = {}
    stack: list = [("dict", -1, root)]

    def _close_pending(new_indent: int, as_kind: str):
        """If the top of the stack is a pending key at indent < new_indent,
        materialise the child container as ``as_kind`` and replace the frame
        with the real container frame."""
        if not stack:
            return
        top = stack[-1]
        if top[0] != "pending_key":
            return
        _, pind, parent_dict, key = top
        if new_indent <= pind:
            # The pending key never got a child — promote to an empty list for
            # "key:\n" at end-of-file; otherwise to None. Here we can't know
            # without lookahead, so leave the dict value as None if it's still
            # unset. Callers shouldn't emit such YAML for docsync configs.
            stack.pop()
            if parent_dict.get(key) is None:
                parent_dict[key] = [] if as_kind == "list" else {}
            return
        # Otherwise materialise the container.
        child: object
        if as_kind == "list":
            child = []
        else:
            child = {}
        parent_dict[key] = child
        stack.pop()
        stack.append(("list" if as_kind == "list" else "dict", pind, child))

    for line in lines:
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()

        # Decide whether this line is a list item or a mapping entry.
        is_list_item = content.startswith("- ")

        # If the top frame is a pending key and this line is at deeper indent,
        # materialise the child now (list vs dict depends on this line's shape).
        if stack and stack[-1][0] == "pending_key" and indent > stack[-1][1]:
            _close_pending(indent, "list" if is_list_item else "dict")

        # Pop frames whose indent is >= current indent (we've left their scope).
        # Exception: a list item at indent == list's indent is STILL in the list.
        while stack:
            top = stack[-1]
            kind, pind, _ = top[0], top[1], top[2] if len(top) >= 3 else None
            if kind == "pending_key":
                # If this line is at or shallower than the pending key, it
                # means the key has no nested children. Close it as an empty
                # value (list/dict) — choose list since most of our optional
                # keys default to arrays, but prefer None to stay honest.
                _, pind, parent_dict, key = top
                if indent <= pind:
                    stack.pop()
                    if parent_dict.get(key) is None:
                        parent_dict[key] = None
                    continue
                break
            if kind == "list" and is_list_item and indent == pind:
                break  # same-level list item continues the list
            if indent > pind:
                break
            stack.pop()

        if not stack:
            raise ValueError(f"stack underflow at {line!r}")

        top = stack[-1]
        parent_kind = top[0]
        parent = top[2]

        if is_list_item:
            if parent_kind != "list":
                raise ValueError(f"list item in non-list context at {line!r}")
            item_body = content[2:].strip()
            if ":" in item_body and not (item_body.startswith('"') or
                                          item_body.startswith("'")):
                k, _, v = item_body.partition(":")
                k = k.strip()
                v_stripped = v.strip()
                d: dict = {}
                parent.append(d)
                if v_stripped == "":
                    # `- key:` with nested children coming at deeper indent.
                    stack.append(("dict", indent, d))
                    stack.append(("pending_key", indent + 2, d, k))
                    # Using indent+2 as a heuristic — any child with indent
                    # strictly greater than the item will materialise via
                    # _close_pending on the next line.
                else:
                    d[k] = _coerce(v_stripped)
                    stack.append(("dict", indent, d))
            else:
                parent.append(_coerce(item_body))
            continue

        # Mapping entry
        if ":" not in content:
            raise ValueError(f"cannot parse line: {line!r}")
        key, _, value = content.partition(":")
        key = key.strip()
        value = value.strip()

        if parent_kind != "dict":
            raise ValueError(f"mapping entry in non-dict context at {line!r}")

        if value == "":
            parent[key] = None  # placeholder; _close_pending may overwrite
            stack.append(("pending_key", indent, parent, key))
        else:
            parent[key] = _coerce(value)

    # Clean up any lingering pending_key frames (end of file).
    while stack and stack[-1][0] == "pending_key":
        stack.pop()

    return root


# -----------------------------------------------------------------------------
# Data classes
# -----------------------------------------------------------------------------

@dataclass
class DocEntry:
    path: str
    section: str | None = None
    required: bool = True
    required_if: str | None = None  # semantic condition label


@dataclass
class Rule:
    id: str
    pattern: str
    docs: list[DocEntry] = field(default_factory=list)


@dataclass
class DocsyncConfig:
    schema_version: int = 1
    bootstrap_docs: list[str] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    skip_conditions: list[str] = field(default_factory=list)
    enforcement: str = "warn"
    integration: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict) -> "DocsyncConfig":
        rules = []
        for r in (raw.get("rules") or []):
            docs = []
            for d in (r.get("docs") or []):
                if isinstance(d, str):
                    docs.append(DocEntry(path=d))
                else:
                    docs.append(DocEntry(
                        path=d["path"],
                        section=d.get("section"),
                        required=bool(d.get("required", True)),
                        required_if=d.get("required_if"),
                    ))
            rules.append(Rule(
                id=r.get("id") or r.get("pattern", "?"),
                pattern=r.get("pattern", ""),
                docs=docs,
            ))
        return cls(
            schema_version=int(raw.get("schema_version", 1)),
            bootstrap_docs=list(raw.get("bootstrap_docs") or []),
            rules=rules,
            skip_conditions=list(raw.get("skip_conditions") or []),
            enforcement=str(raw.get("enforcement", "warn")),
            integration=dict(raw.get("integration") or {}),
        )


# -----------------------------------------------------------------------------
# Config discovery
# -----------------------------------------------------------------------------

def find_config(start: Path | None = None) -> Path | None:
    cwd = Path(start or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    for d in [cwd, *cwd.parents]:
        candidate = d / ".claude" / "docsync.yaml"
        if candidate.is_file():
            return candidate
    return None


def load_config(start: Path | None = None) -> tuple[DocsyncConfig | None, Path | None]:
    path = find_config(start)
    if path is None:
        return None, None
    try:
        raw = load_yaml(path)
    except Exception:
        return None, path
    return DocsyncConfig.from_dict(raw or {}), path


# -----------------------------------------------------------------------------
# Matching
# -----------------------------------------------------------------------------

def match_rules(cfg: DocsyncConfig, file_paths: Iterable[str]) -> list[tuple[str, Rule]]:
    """Return [(path, rule), …] for every (path, rule) that matches."""
    out = []
    paths = list(file_paths)
    for rule in cfg.rules:
        if not rule.pattern:
            continue
        for p in paths:
            # Accept both fnmatch globs (** simulated via recursive match) and
            # simple prefix patterns like ``common/**``.
            if _glob_match(rule.pattern, p):
                out.append((p, rule))
    return out


def _glob_match(pattern: str, path: str) -> bool:
    # Convert ``**`` → fnmatch's implicit recursion (fnmatch doesn't natively
    # handle ``**``). Treat ``common/**`` as ``common/*`` OR any deeper match.
    if "**" in pattern:
        prefix = pattern.split("**", 1)[0].rstrip("/")
        suffix = pattern.split("**", 1)[1].lstrip("/")
        if prefix and not (path == prefix or path.startswith(prefix + "/")):
            return False
        if suffix:
            return fnmatch.fnmatch(path, f"*{suffix}") or fnmatch.fnmatch(path, f"*/{suffix}")
        return True
    return fnmatch.fnmatch(path, pattern)


# -----------------------------------------------------------------------------
# Git helpers
# -----------------------------------------------------------------------------

def _git(cwd: Path, *args) -> str:
    try:
        r = subprocess.run(
            ["git", *args], cwd=str(cwd), check=False,
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout
    except Exception:
        return ""


def changed_files_since(cwd: Path, ref: str) -> list[str]:
    """Files changed between ``ref`` and HEAD, plus uncommitted."""
    out = set()
    tracked = _git(cwd, "diff", "--name-only", f"{ref}...HEAD").splitlines()
    dirty = _git(cwd, "diff", "--name-only").splitlines()
    staged = _git(cwd, "diff", "--cached", "--name-only").splitlines()
    untracked = _git(cwd, "ls-files", "--others", "--exclude-standard").splitlines()
    for n in tracked + dirty + staged + untracked:
        n = n.strip()
        if n:
            out.add(n)
    return sorted(out)


def changed_files_in_commit(cwd: Path, rev: str) -> list[str]:
    return [
        n.strip() for n in
        _git(cwd, "show", "--name-only", "--pretty=format:", rev).splitlines()
        if n.strip()
    ]


def recent_commits(cwd: Path, n: int = 20) -> list[tuple[str, str]]:
    """Return [(short_sha, subject), …]."""
    raw = _git(cwd, "log", f"-n{n}", "--pretty=format:%h\t%s")
    out = []
    for line in raw.splitlines():
        if "\t" in line:
            sha, _, subj = line.partition("\t")
            out.append((sha.strip(), subj.strip()))
    return out


# -----------------------------------------------------------------------------
# Pending-sync computation
# -----------------------------------------------------------------------------

@dataclass
class Pending:
    code_path: str
    rule_id: str
    doc_path: str
    doc_section: str | None
    required: bool
    required_if: str | None


def pending_syncs(cfg: DocsyncConfig, changed: list[str]) -> list[Pending]:
    """Return required doc updates that haven't been touched in ``changed``."""
    changed_set = set(changed)
    pending: list[Pending] = []

    for code_path, rule in match_rules(cfg, changed):
        # Skip if it's actually a doc file that happened to match a code pattern.
        if _looks_like_doc(code_path):
            continue
        for doc in rule.docs:
            if doc.path in changed_set:
                continue  # doc was updated this diff — considered synced
            if doc.required is False and doc.required_if is None:
                continue  # opt-out without a semantic condition
            pending.append(Pending(
                code_path=code_path,
                rule_id=rule.id,
                doc_path=doc.path,
                doc_section=doc.section,
                required=doc.required,
                required_if=doc.required_if,
            ))
    return _dedupe_pending(pending)


def _dedupe_pending(items: list[Pending]) -> list[Pending]:
    seen = set()
    out = []
    for p in items:
        key = (p.doc_path, p.doc_section or "", p.rule_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


_DOC_EXTENSIONS = {".md", ".mdx", ".rst", ".txt", ".adoc"}


def _looks_like_doc(path: str) -> bool:
    p = Path(path)
    return p.suffix.lower() in _DOC_EXTENSIONS


# -----------------------------------------------------------------------------
# JSON serialisation for CLI output
# -----------------------------------------------------------------------------

def pending_to_json(pending: list[Pending]) -> str:
    return json.dumps({
        "pending": [
            {
                "code_path": p.code_path,
                "rule_id": p.rule_id,
                "doc_path": p.doc_path,
                "doc_section": p.doc_section,
                "required": p.required,
                "required_if": p.required_if,
            } for p in pending
        ]
    })
