"""Convert a markdown subset to Atlassian Document Format (ADF) — fix
for the "agent writes markdown, Jira shows raw `##`" bug filed after
#57.

Why this exists
---------------

Jira Cloud renders the Atlassian Document Format (ADF), not markdown.
Posting ``"## Heading"`` as the body of a comment or description shows
literal ``"## Heading"`` text — the user sees the markdown source
instead of a styled heading. Claude-Code agents emit markdown freely
(headings, lists, code fences), so the kanban plugin needs to translate
that to ADF before posting.

Earlier flows side-stepped this by ADF-encoding only specific known
chunks — for example, the SPEC §9 prefix on replies was wrapped in
``strong`` marks server-side (#27) precisely because ``**...**``
literals would render verbatim. This module generalizes that fix to
the entire body.

Supported subset
----------------

* Headings: ``#`` … ``######`` (h1–h6). The hash chars + a single
  required space, then the heading text.
* Paragraphs (default for any non-block text).
* Inline marks:

  - Bold: ``**text**`` or ``__text__``
  - Italic: ``*text*`` or ``_text_``
  - Inline code: ``\`text\``` (single backticks)
  - Links: ``[text](https://url)``
  - Bare URLs in text are still auto-linkified (so ``"see
    https://x.com"`` produces a clickable link, matching pre-bugfix
    behavior).

* Fenced code blocks: triple backticks, optional language tag on the
  opener (``` ```python ``` ``` … ``` ``` ``` ```).
* Bullet lists: lines starting with ``- ``, ``* ``, or ``+ ``.
* Ordered lists: lines starting with ``N. ``.
* Blockquotes: lines starting with ``> ``.

Out of scope (would require a real CommonMark parser)
-----------------------------------------------------

* Tables, setext-style headings, reference links, HTML passthrough,
  escape sequences (``\\*``), thematic breaks (``---``).
* Nested lists — a sub-list indents back to top level. Agents that
  need indented structure should use multi-paragraph items.
* Hard breaks via trailing whitespace — newlines inside a paragraph
  are joined with a single space (matches how most markdown renderers
  treat a soft break).

Inputs that contain no markdown markers fall through as a single
paragraph with URL auto-linkification — the same shape ``text_to_adf``
emitted before this module existed, so the upgrade is invisible to
plain-text callers.
"""
from __future__ import annotations

import re
from typing import Any


# URL detector — identical to the one in jira_client._text_to_inline_nodes
# so bare-URL auto-linkification stays consistent across both module
# boundaries. Conservative on tail punctuation: a URL at end of sentence
# ("see https://x.com.") doesn't swallow the period; a URL inside parens
# or quotes doesn't pull the closing bracket in.
_URL_RE = re.compile(r"https?://[^\s<>\"\)\]]+")

# Heading: 1–6 leading hashes, then a space, then content. The trailing
# `\s*` lets us tolerate a stray training space on the line. Skipping
# the "no space after hashes" form (`#foo`) is intentional — it matches
# CommonMark and avoids treating `#1` (which agents use as an issue
# anchor) as a heading.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

# List markers. Bullet markers accept any of `-`, `*`, `+`; ordered
# markers accept `N.` for any positive integer (we don't preserve the
# starting number in the rendered list — ADF orderedList re-numbers
# from 1 anyway).
_BULLET_RE = re.compile(r"^(\s*)([-*+])\s+(.*)$")
_ORDERED_RE = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")

# Blockquote: `>` optionally followed by a space and content. Empty `>`
# is allowed (paragraph separator inside a quote).
_BLOCKQUOTE_RE = re.compile(r"^>\s?(.*)$")

# Fenced code block opener / closer. We accept three or more backticks
# and an optional language tag. The closing fence must match the same
# fence char and have at least as many of them.
_FENCE_RE = re.compile(r"^(```+)\s*([^\s`]*)\s*$")

# Inline patterns. Tried in priority order; first match (closest to the
# scan cursor) wins. Code is highest priority because backticks suppress
# all other formatting inside them. Link beats emphasis because `[**x**]`
# should still produce a link, not bold-then-bracketed.
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_INLINE_LINK_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
_INLINE_STRONG_RE = re.compile(r"\*\*([^*\n]+?)\*\*")
_INLINE_STRONG_US_RE = re.compile(r"__([^_\n]+?)__")
_INLINE_EM_RE = re.compile(r"(?<![*\w])\*([^*\n]+?)\*(?!\w)")
_INLINE_EM_US_RE = re.compile(r"(?<![_\w])_([^_\n]+?)_(?!\w)")


# --- public surface -----------------------------------------------------


def markdown_to_adf(text: str) -> dict[str, Any]:
    """Parse `text` as a markdown subset and return a full ADF doc.

    Always returns a well-formed doc — empty input produces a doc with
    a single empty paragraph (matches the pre-bugfix shape so the API
    surface is consistent).
    """
    blocks = _parse_blocks(text or "")
    content = [_block_to_adf(b) for b in blocks]
    if not content:
        content = [{"type": "paragraph", "content": [{"type": "text", "text": ""}]}]
    return {"type": "doc", "version": 1, "content": content}


def inline_to_adf(text: str) -> list[dict[str, Any]]:
    """Parse `text` as inline-only markdown and return a list of ADF
    inline nodes (text + link/strong/em/code marks).

    Used when the caller has already built the surrounding block
    structure — for example, the body of a /kanban:reply lives in the
    same paragraph as the @mention chip, so it can't introduce its own
    block-level nodes. Newlines collapse to spaces in this mode.
    """
    flat = " ".join(line.strip() for line in (text or "").splitlines() if line.strip())
    return _inline_to_nodes(flat)


# --- block parsing ------------------------------------------------------


def _parse_blocks(text: str) -> list[tuple[str, Any]]:
    """Walk `text` line-by-line, grouping lines into block descriptors.

    Each descriptor is a tuple ``(kind, payload)`` consumed by
    `_block_to_adf`. We do block parsing as a separate pass from ADF
    generation so the inline parser doesn't have to re-discover block
    boundaries.
    """
    lines = text.split("\n")
    i = 0
    blocks: list[tuple[str, Any]] = []
    while i < len(lines):
        line = lines[i]

        # Blank lines are paragraph/block separators — skip them.
        if not line.strip():
            i += 1
            continue

        # Fenced code block. Capture until the matching closer; if no
        # closer found, treat all remaining text as the block (matches
        # how renderers behave on truncated fences).
        fence = _FENCE_RE.match(line)
        if fence:
            fence_chars, lang = fence.group(1), fence.group(2)
            i += 1
            code_lines: list[str] = []
            while i < len(lines):
                if lines[i].startswith(fence_chars):
                    i += 1
                    break
                code_lines.append(lines[i])
                i += 1
            blocks.append(("code_block", {"lang": lang, "code": "\n".join(code_lines)}))
            continue

        # Heading (single line).
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            blocks.append(("heading", {"level": level, "text": m.group(2)}))
            i += 1
            continue

        # Blockquote — gather contiguous `>`-prefixed lines.
        if _BLOCKQUOTE_RE.match(line):
            quote_lines: list[str] = []
            while i < len(lines):
                qm = _BLOCKQUOTE_RE.match(lines[i])
                if not qm:
                    break
                quote_lines.append(qm.group(1))
                i += 1
            blocks.append(("blockquote", "\n".join(quote_lines)))
            continue

        # Bullet list — gather contiguous bullet items at the same
        # (top-level) indent. Indented sub-items get folded into the
        # parent item's text (we don't model nested lists in v1).
        if _BULLET_RE.match(line):
            items, i = _collect_list(lines, i, _BULLET_RE)
            blocks.append(("bullet_list", items))
            continue

        # Ordered list — same logic as bullet, different marker.
        if _ORDERED_RE.match(line):
            items, i = _collect_list(lines, i, _ORDERED_RE)
            blocks.append(("ordered_list", items))
            continue

        # Paragraph — consume contiguous non-blank lines that don't
        # start another block. Soft newlines join with a single space.
        para_lines: list[str] = []
        while i < len(lines):
            cur = lines[i]
            if not cur.strip():
                break
            if _starts_new_block(cur):
                break
            para_lines.append(cur.strip())
            i += 1
        if para_lines:
            blocks.append(("paragraph", " ".join(para_lines)))

    return blocks


def _starts_new_block(line: str) -> bool:
    """Cheap check: would this line open a new block (and so terminate
    the current paragraph)? Mirrors the dispatch order in
    `_parse_blocks` so a paragraph stops at the first block-starter."""
    if _FENCE_RE.match(line):
        return True
    if _HEADING_RE.match(line):
        return True
    if _BLOCKQUOTE_RE.match(line):
        return True
    if _BULLET_RE.match(line):
        return True
    if _ORDERED_RE.match(line):
        return True
    return False


def _collect_list(lines: list[str], start: int, marker_re: re.Pattern) -> tuple[list[str], int]:
    """Gather contiguous list items starting at `lines[start]` until a
    line breaks the list (blank, different marker, or another block).

    Returns (item_texts, next_index). Each item's text is what follows
    the marker on its line; continuation lines that are indented (≥ 2
    spaces) are folded into the previous item with a leading space.
    """
    items: list[str] = []
    i = start
    while i < len(lines):
        line = lines[i]
        m = marker_re.match(line)
        if m:
            items.append(m.group(3))
            i += 1
            continue
        # Continuation: indented line attached to the previous item.
        if items and line.startswith(("  ", "\t")) and line.strip():
            items[-1] += " " + line.strip()
            i += 1
            continue
        break
    return items, i


# --- block → ADF node ---------------------------------------------------


def _block_to_adf(block: tuple[str, Any]) -> dict[str, Any]:
    kind, payload = block
    if kind == "heading":
        return {
            "type": "heading",
            "attrs": {"level": payload["level"]},
            "content": _inline_to_nodes(payload["text"]),
        }
    if kind == "paragraph":
        return {"type": "paragraph", "content": _inline_to_nodes(payload)}
    if kind == "code_block":
        # ADF codeBlock requires at least one text child even when
        # empty. The `language` attr is optional; we only set it when
        # the fence carried a tag, so renderers default sensibly.
        attrs: dict[str, Any] = {}
        if payload.get("lang"):
            attrs["language"] = payload["lang"]
        node: dict[str, Any] = {
            "type": "codeBlock",
            "content": [{"type": "text", "text": payload.get("code", "")}],
        }
        if attrs:
            node["attrs"] = attrs
        return node
    if kind == "blockquote":
        # Blockquote wraps an inner paragraph (or paragraphs, when the
        # quoted text contains blank lines). We re-run block parsing on
        # the inner text to handle the multi-paragraph case.
        inner_blocks = _parse_blocks(payload)
        if not inner_blocks:
            inner_blocks = [("paragraph", "")]
        return {
            "type": "blockquote",
            "content": [_block_to_adf(b) for b in inner_blocks],
        }
    if kind in ("bullet_list", "ordered_list"):
        adf_kind = "bulletList" if kind == "bullet_list" else "orderedList"
        return {
            "type": adf_kind,
            "content": [
                {
                    "type": "listItem",
                    "content": [{"type": "paragraph", "content": _inline_to_nodes(item)}],
                }
                for item in payload
            ],
        }
    # Defensive — unknown block kind. Drop to a plain paragraph so we
    # never emit a malformed ADF tree that fails server-side validation.
    return {"type": "paragraph", "content": [{"type": "text", "text": str(payload)}]}


# --- inline parsing -----------------------------------------------------


def _inline_to_nodes(text: str) -> list[dict[str, Any]]:
    """Parse `text` as inline markdown and return ADF text nodes with
    appropriate marks. Always returns at least one node (an empty text
    node) so consumers can rely on a non-empty list."""
    if not text:
        return [{"type": "text", "text": ""}]
    out: list[dict[str, Any]] = []
    _scan_inline(text, [], out)
    if not out:
        out = [{"type": "text", "text": ""}]
    return out


def _scan_inline(text: str, marks: list[dict[str, Any]], out: list[dict[str, Any]]) -> None:
    """Recursive-descent inline scanner. `marks` is the stack of marks
    currently in effect (passed down when we enter a strong/em region);
    matched leaves (text spans, code, links) are appended to `out`.

    The algorithm: find the earliest match across all inline patterns.
    Whatever's before that match is plain text (subject to URL
    auto-linkification). The match itself is converted to a node
    (or recursed-into for strong/em), then we continue from the end of
    the match.
    """
    pos = 0
    while pos < len(text):
        match = _find_earliest_inline(text, pos)
        if match is None:
            _emit_text_span(text[pos:], marks, out)
            return
        kind, span_start, span_end, payload = match
        if span_start > pos:
            _emit_text_span(text[pos:span_start], marks, out)
        if kind == "code":
            out.append({
                "type": "text",
                "text": payload,
                "marks": [*marks, {"type": "code"}],
            })
        elif kind == "link":
            label, href = payload
            # Link contents go through inline parsing too (so
            # `[**bold**](u)` renders a bold-inside-link). The link
            # mark stacks on top of any inherited marks.
            _scan_inline(label, [*marks, {"type": "link", "attrs": {"href": href}}], out)
        elif kind == "strong":
            _scan_inline(payload, [*marks, {"type": "strong"}], out)
        elif kind == "em":
            _scan_inline(payload, [*marks, {"type": "em"}], out)
        pos = span_end


def _find_earliest_inline(text: str, start: int) -> tuple[str, int, int, Any] | None:
    """Look for the earliest inline marker at-or-after `start`. Ties
    are broken by priority (code > link > strong > em) so e.g.
    ``**\`foo\`**`` parses as strong(code(foo)), not code-with-stars.
    """
    candidates: list[tuple[int, int, str, int, int, Any]] = []
    for prio, (kind, pattern, extractor) in enumerate([
        ("code", _INLINE_CODE_RE, lambda m: m.group(1)),
        ("link", _INLINE_LINK_RE, lambda m: (m.group(1), m.group(2))),
        ("strong", _INLINE_STRONG_RE, lambda m: m.group(1)),
        ("strong", _INLINE_STRONG_US_RE, lambda m: m.group(1)),
        ("em", _INLINE_EM_RE, lambda m: m.group(1)),
        ("em", _INLINE_EM_US_RE, lambda m: m.group(1)),
    ]):
        m = pattern.search(text, start)
        if m:
            candidates.append((m.start(), prio, kind, m.start(), m.end(), extractor(m)))
    if not candidates:
        return None
    candidates.sort()  # earliest match wins; ties broken by priority
    _, _, kind, s, e, payload = candidates[0]
    return kind, s, e, payload


def _emit_text_span(text: str, marks: list[dict[str, Any]], out: list[dict[str, Any]]) -> None:
    """Emit a plain-text span (possibly carrying inherited marks) with
    bare URLs split out into link-marked sub-nodes. Empty spans are
    dropped — ADF doesn't reject them, but they bulk up the tree
    needlessly."""
    if not text:
        return
    pos = 0
    for m in _URL_RE.finditer(text):
        if m.start() > pos:
            out.append(_text_node(text[pos:m.start()], marks))
        url = m.group(0)
        trailer = ""
        while url and url[-1] in ".,;:!?":
            trailer = url[-1] + trailer
            url = url[:-1]
        if url:
            # The auto-linkified URL stacks a link mark on top of any
            # inherited marks (so a bare URL inside **bold** stays
            # bold-and-linked).
            out.append(_text_node(url, [*marks, {"type": "link", "attrs": {"href": url}}]))
        if trailer:
            out.append(_text_node(trailer, marks))
        pos = m.end()
    if pos < len(text):
        out.append(_text_node(text[pos:], marks))


def _text_node(text: str, marks: list[dict[str, Any]]) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": text}
    if marks:
        node["marks"] = list(marks)
    return node
