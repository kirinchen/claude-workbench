"""feat_map.py — parser & validator for ``doc/feat_map.md``.

Implements the v1 spec from kirinchen/claude-workbench#60. Pure logic, no
side effects at import time. The caller (mentor-guard.py for warn-only
PreToolUse, framework_engine.review() for the authoritative compliance
exit code) wraps the returned issues into its own Violation shape.

Violation codes follow the spec table verbatim (FM-01..FM-12). FM-01
(file absent) is the caller's concern; this module operates on text that
has already been read.

Cross-repo `repo` slug deduplication (the second half of FM-04) is also
out of scope here — that check belongs to the kelp viewer when it scans
a whole `project/` folder.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from framework_engine import _fallback_yaml_load  # noqa: E402

# -----------------------------------------------------------------------------
# Spec constants
# -----------------------------------------------------------------------------

FEAT_MAP_REL_PATH = "doc/feat_map.md"
SCHEMA_VERSION = 1
VALID_STATUSES = {"@done", "@wip", "@todo", "@blocked"}
DONE_STATUS = "@done"
BLOCKED_STATUS = "@blocked"

JIRA_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]+-[0-9]+$")
JIRA_REF_RE = re.compile(r"\(jira:([^)]+)\)")
STATUS_TOKEN_RE = re.compile(r"`(@[a-zA-Z]+)`")
_BULLET_RE = re.compile(r"^( *)- (.*)$")
_FRONTMATTER_BLOCK_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


# -----------------------------------------------------------------------------
# Data classes
# -----------------------------------------------------------------------------

@dataclass
class Issue:
    """A single spec violation. `line` is 1-based in the original file
    (0 means file-level, frontmatter-level, or unknown)."""
    code: str
    line: int
    detail: str


@dataclass
class Node:
    title: str
    statuses: list[str] = field(default_factory=list)
    jira: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    children: list["Node"] = field(default_factory=list)
    line: int = 0

    @property
    def is_leaf(self) -> bool:
        return not self.children

    @property
    def status(self) -> str | None:
        """Convenience for the common 'exactly one' case. None when missing
        OR when multiple status tokens were parsed — callers that care about
        the malformed case look at `statuses` directly."""
        return self.statuses[0] if len(self.statuses) == 1 else None


@dataclass
class ParsedFeatMap:
    frontmatter: dict
    roots: list[Node]
    issues: list[Issue]


# -----------------------------------------------------------------------------
# Parser
# -----------------------------------------------------------------------------

def _split_frontmatter(text: str) -> tuple[dict | None, str, int, str | None]:
    """Return (fm_dict, body, body_start_line, fm_error).

    `body_start_line` is the 1-based line number where the body begins
    (after the closing `---` line). `fm_error` is non-None if the
    frontmatter block is structurally broken (→ FM-02).
    """
    if not text.lstrip().startswith("---"):
        return None, text, 1, "frontmatter block not found at top of file"
    m = _FRONTMATTER_BLOCK_RE.match(text)
    if not m:
        return None, text, 1, "frontmatter block unterminated or malformed"
    try:
        fm = _fallback_yaml_load(m.group(1)) or {}
    except Exception as e:
        body = text[m.end():]
        body_line = text[: m.end()].count("\n") + 1
        return None, body, body_line, f"unparseable YAML frontmatter: {e}"
    body = text[m.end():]
    body_line = text[: m.end()].count("\n") + 1
    return fm, body, body_line, None


def _parse_node_content(content: str) -> tuple[str, list[str], list[str], list[Issue]]:
    """Decompose the content after `- ` into (title, statuses, jira_keys, parse_issues).

    Multiple status tokens are returned as a list — leaf-vs-parent context
    decides whether that's FM-07 or FM-08, so the choice is deferred to
    `validate()`.
    """
    parse_issues: list[Issue] = []
    statuses = STATUS_TOKEN_RE.findall(content)
    jira_keys: list[str] = []
    for m in JIRA_REF_RE.finditer(content):
        key = m.group(1).strip()
        jira_keys.append(key)
        if not JIRA_KEY_RE.match(key):
            parse_issues.append(Issue("FM-10", 0, f"invalid Jira key {key!r}"))
    title = STATUS_TOKEN_RE.sub("", content)
    title = JIRA_REF_RE.sub("", title)
    title = title.strip()
    return title, statuses, jira_keys, parse_issues


def _parse_tree(body: str, line_offset: int) -> tuple[list[Node], list[Issue]]:
    """Build the forest from `body`.

    `line_offset` is the 1-based line of `body`'s first line in the
    original file (so issue.line is reported in file coordinates, not body
    coordinates). Stops at the first non-blank, non-bullet line once the
    tree has begun (→ FM-12). Prose before the tree is silently ignored
    per spec §3.
    """
    issues: list[Issue] = []
    roots: list[Node] = []
    # Stack of (indent, node). Sentinel root entry has indent=-2 so children
    # at indent=0 satisfy `indent == parent_indent + 2`.
    stack: list[tuple[int, Node | None]] = [(-2, None)]

    lines = body.splitlines()
    in_tree = False

    for i, raw in enumerate(lines):
        file_line = line_offset + i

        if "\t" in raw:
            issues.append(Issue("FM-05", file_line, "tab character is not allowed in the tree"))
            continue

        stripped = raw.strip()
        if stripped == "":
            continue

        if not stripped.startswith("- "):
            if stripped.startswith("* ") or stripped.startswith("+ "):
                issues.append(Issue(
                    "FM-05", file_line,
                    f"wrong bullet marker {stripped[0]!r}; must be '- '"
                ))
                continue
            if in_tree:
                issues.append(Issue(
                    "FM-12", file_line,
                    "content after the feature tree (only trailing whitespace permitted)"
                ))
                break
            # Pre-tree prose — silently ignored per §3.
            continue

        m = _BULLET_RE.match(raw)
        if not m:
            issues.append(Issue("FM-05", file_line, "bullet line not in `- ` form"))
            continue

        indent_spaces, content = m.group(1), m.group(2)
        indent = len(indent_spaces)

        if indent % 2 != 0:
            issues.append(Issue(
                "FM-06", file_line,
                f"indent {indent} is not a non-negative multiple of 2"
            ))
            continue

        in_tree = True

        # Note rows are metadata for their parent, not nodes (§5.5).
        if content.startswith("note:"):
            note_text = content[len("note:"):].strip()
            parent_for_note: Node | None = None
            for ind, node in reversed(stack):
                if node is None:
                    continue
                if ind < indent:
                    parent_for_note = node
                    break
            if parent_for_note is None:
                issues.append(Issue(
                    "FM-06", file_line,
                    "`note:` bullet has no ancestor node to attach to"
                ))
                continue
            parent_for_note.notes.append(note_text)
            continue

        # Pop stack until the top is a strict parent (indent < this indent).
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent_indent, parent_node = (stack[-1] if stack else (-2, None))

        expected = parent_indent + 2
        if indent != expected:
            issues.append(Issue(
                "FM-06", file_line,
                f"indent jumped from {max(parent_indent, 0)} to {indent}; "
                f"expected {expected} (children must be exactly 2 spaces deeper than parent)"
            ))
            # Best-effort: keep parsing using the actual indent so cascading
            # FM-06s don't drown the report.

        title, statuses, jira_keys, parse_issues = _parse_node_content(content)
        for pi in parse_issues:
            issues.append(Issue(pi.code, file_line, pi.detail))

        node = Node(title=title, statuses=statuses, jira=jira_keys, line=file_line)
        if parent_node is None:
            roots.append(node)
        else:
            parent_node.children.append(node)
        stack.append((indent, node))

    return roots, issues


def parse(text: str) -> ParsedFeatMap:
    """Parse the file text. Surfaces FM-02 / FM-05 / FM-06 / FM-10 / FM-12
    issues found during parsing — semantic checks happen in `validate()`."""
    fm, body, body_line, fm_err = _split_frontmatter(text)
    issues: list[Issue] = []
    if fm_err:
        issues.append(Issue("FM-02", 1, fm_err))
    roots, tree_issues = _parse_tree(body, body_line)
    issues.extend(tree_issues)
    return ParsedFeatMap(frontmatter=fm or {}, roots=roots, issues=issues)


# -----------------------------------------------------------------------------
# Validator
# -----------------------------------------------------------------------------

def _walk(nodes: Iterable[Node]):
    for n in nodes:
        yield n
        yield from _walk(n.children)


def validate(text: str) -> list[Issue]:
    """Run FM-02..FM-12 over `text`.

    FM-01 (file absent) is the caller's job — by the time we have text in
    hand, the file exists. Returns an empty list when the file is valid.
    """
    parsed = parse(text)
    issues = list(parsed.issues)
    fm = parsed.frontmatter

    # FM-02 — already emitted by parse() when the block is malformed.
    if not fm and not any(i.code == "FM-02" for i in issues):
        issues.append(Issue("FM-02", 1, "frontmatter is empty"))

    # FM-03 — schema_version must be exactly 1.
    if fm:
        sv = fm.get("schema_version")
        if sv != SCHEMA_VERSION:
            issues.append(Issue(
                "FM-03", 1,
                f"schema_version must be {SCHEMA_VERSION}, got {sv!r}"
            ))

    # FM-04 — `repo` slug is required (cross-folder dedup is out of scope here).
    if fm and not fm.get("repo"):
        issues.append(Issue("FM-04", 1, "frontmatter.repo is required"))

    # FM-11 — jira_base_url required iff any leaf carries a Jira key.
    has_any_jira = any(n.jira for n in _walk(parsed.roots))
    if has_any_jira and fm and not fm.get("jira_base_url"):
        issues.append(Issue(
            "FM-11", 1,
            "frontmatter.jira_base_url is required when any leaf carries a Jira key"
        ))

    # FM-07 / FM-08 / FM-09 — per-node leaf/parent rules.
    for n in _walk(parsed.roots):
        if n.is_leaf:
            if len(n.statuses) == 0:
                issues.append(Issue(
                    "FM-07", n.line,
                    f"leaf {n.title!r} is missing a status token "
                    f"(`@done` | `@wip` | `@todo` | `@blocked`)"
                ))
            elif len(n.statuses) > 1:
                issues.append(Issue(
                    "FM-07", n.line,
                    f"leaf {n.title!r} has {len(n.statuses)} status tokens, "
                    f"expected exactly 1: {n.statuses}"
                ))
            else:
                s = n.statuses[0]
                if s not in VALID_STATUSES:
                    issues.append(Issue(
                        "FM-09", n.line,
                        f"unknown status token {s!r} on leaf {n.title!r}; "
                        f"allowed: {sorted(VALID_STATUSES)}"
                    ))
        else:
            if n.statuses:
                issues.append(Issue(
                    "FM-08", n.line,
                    f"parent {n.title!r} carries status {n.statuses!r}; "
                    "parent status is derived — remove the token"
                ))
            if n.jira:
                issues.append(Issue(
                    "FM-08", n.line,
                    f"parent {n.title!r} carries Jira ref(s) {n.jira!r}; "
                    "Jira refs are allowed on leaves only"
                ))

    return issues


# -----------------------------------------------------------------------------
# Rollup helpers (consumed by /mentor:renewtree introspection; the kelp
# viewer reimplements these per spec §6 — defined here for parity with
# §6.1 / §6.2 so a single source of truth ships in this repo.)
# -----------------------------------------------------------------------------

def _leaves(node: Node) -> list[Node]:
    if node.is_leaf:
        return [node]
    out: list[Node] = []
    for c in node.children:
        out.extend(_leaves(c))
    return out


def percent(node: Node) -> float | None:
    """§6.1: done-leaves / total-leaves. None when the leaf set is empty."""
    ls = _leaves(node)
    if not ls:
        return None
    done = sum(1 for leaf in ls if leaf.status == DONE_STATUS)
    return done / len(ls)


def blocked(node: Node) -> bool:
    """§6.2: True iff any descendant leaf is @blocked."""
    return any(leaf.status == BLOCKED_STATUS for leaf in _leaves(node))
