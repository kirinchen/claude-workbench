#!/usr/bin/env python3
"""Phase 35 regression checks for kanban v0.3.30 — markdown → ADF
(bug filed after #57).

Background: agents emit markdown freely (headings, lists, code,
links), but `text_to_adf` used to wrap everything as one flat
paragraph — Jira UI then showed the literal markdown (`## Heading`
instead of a styled h2). This phase verifies the new
`lib/markdown_adf.py` parser produces the right ADF shapes for each
markdown construct, that the existing call sites (`text_to_adf`,
`text_to_adf_with_mention`) now route through it, and that plain-text
payloads stay equivalent to the old single-paragraph + URL-auto-link
behavior so callers that don't use markdown see no regression.

Cases:
  (a) Heading levels 1–6 → `heading` nodes with the matching `level`.
  (b) Bold (`**x**` and `__x__`) → text with a `strong` mark.
  (c) Italic (`*x*` and `_x_`) → text with an `em` mark.
  (d) Inline code (`\`x\``) → text with a `code` mark.
  (e) Fenced code block, with and without language tag.
  (f) Bullet list (mixed `-`, `*`, `+` markers across items).
  (g) Ordered list (1. 2. 3.).
  (h) Blockquote, including multi-line.
  (i) Inline link `[text](url)` and bare-URL auto-link inside a
      paragraph coexist.
  (j) Plain-text input round-trips: no markdown markers ⇒ a single
      paragraph with the original text (same shape as the pre-fix
      `text_to_adf`).
  (k) Mixed multi-block document: heading + paragraph + bullet list
      + code block produces blocks in document order.
  (l) `text_to_adf_with_mention` single-line body inlines next to the
      mention chip (preserves chat-bubble look).
  (m) `text_to_adf_with_mention` multi-block body splits: mention sits
      alone in its paragraph, body blocks come after as siblings.
  (n) `text_to_adf_with_mention` prefix is NOT markdown-parsed —
      `**...**` in the prefix would render verbatim, so the prefix
      stays whole + carries a `strong` mark (preserves #27 behavior).
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"
sys.path.insert(0, str(REPO / "plugins" / "kanban"))

from lib.jira_client import text_to_adf, text_to_adf_with_mention  # noqa: E402
from lib.markdown_adf import markdown_to_adf, inline_to_adf  # noqa: E402


def _blocks(doc):
    return doc.get("content") or []


def _first_block(doc):
    blocks = _blocks(doc)
    assert blocks, doc
    return blocks[0]


def _text_in(node):
    """Concatenate all text nodes inside `node` (recursive)."""
    out = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "text":
                out.append(n.get("text", ""))
            for c in n.get("content", []) or []:
                walk(c)
        elif isinstance(n, list):
            for c in n:
                walk(c)
    walk(node)
    return "".join(out)


def _has_mark(node, mark_type):
    return any(m.get("type") == mark_type for m in (node.get("marks") or []))


# --- (a) headings --------------------------------------------------------


def test_headings_levels_1_to_6():
    for lvl in range(1, 7):
        md = "#" * lvl + " Title " + str(lvl)
        doc = markdown_to_adf(md)
        b = _first_block(doc)
        assert b["type"] == "heading", b
        assert b["attrs"]["level"] == lvl, (lvl, b)
        assert _text_in(b) == f"Title {lvl}"


def test_heading_requires_space_after_hashes():
    """`#foo` (no space) is NOT a heading — would otherwise mis-parse
    issue refs like ``#123`` as h1."""
    doc = markdown_to_adf("#123 is the issue")
    b = _first_block(doc)
    assert b["type"] == "paragraph", b


# --- (b) (c) (d) inline marks -------------------------------------------


def test_bold_star_and_underscore():
    for md in ("**bold**", "__bold__"):
        doc = markdown_to_adf(md)
        b = _first_block(doc)
        assert b["type"] == "paragraph"
        inline = b["content"][0]
        assert inline["text"] == "bold"
        assert _has_mark(inline, "strong"), (md, inline)


def test_italic_star_and_underscore():
    for md in ("*italic*", "_italic_"):
        doc = markdown_to_adf(md)
        inline = _first_block(doc)["content"][0]
        assert inline["text"] == "italic"
        assert _has_mark(inline, "em"), (md, inline)


def test_inline_code():
    doc = markdown_to_adf("see `foo.bar()` here")
    inline = _first_block(doc)["content"]
    code_node = next(n for n in inline if n.get("text") == "foo.bar()")
    assert _has_mark(code_node, "code")
    # Surrounding text stays plain.
    others = [n for n in inline if not _has_mark(n, "code")]
    assert any("see " in n["text"] for n in others)
    assert any(" here" in n["text"] for n in others)


def test_bold_inside_text():
    """Bold sandwiched between plain text: plain + strong + plain."""
    doc = markdown_to_adf("plain **bold** plain")
    nodes = _first_block(doc)["content"]
    assert nodes[0]["text"] == "plain "
    assert not nodes[0].get("marks")
    assert nodes[1]["text"] == "bold"
    assert _has_mark(nodes[1], "strong")
    assert nodes[2]["text"] == " plain"


# --- (e) code blocks ----------------------------------------------------


def test_code_block_with_language():
    md = "```python\nprint('x')\n```"
    doc = markdown_to_adf(md)
    b = _first_block(doc)
    assert b["type"] == "codeBlock"
    assert b["attrs"]["language"] == "python"
    assert _text_in(b) == "print('x')"


def test_code_block_without_language():
    md = "```\nplain\n```"
    doc = markdown_to_adf(md)
    b = _first_block(doc)
    assert b["type"] == "codeBlock"
    # `attrs` may be omitted when no language tag.
    assert "language" not in (b.get("attrs") or {})
    assert _text_in(b) == "plain"


# --- (f) (g) lists ------------------------------------------------------


def test_bullet_list_mixed_markers():
    md = "- one\n* two\n+ three"
    doc = markdown_to_adf(md)
    b = _first_block(doc)
    assert b["type"] == "bulletList"
    items = b["content"]
    assert [_text_in(it) for it in items] == ["one", "two", "three"]
    # Each item is a listItem wrapping a paragraph.
    for it in items:
        assert it["type"] == "listItem"
        assert it["content"][0]["type"] == "paragraph"


def test_ordered_list():
    md = "1. first\n2. second\n3. third"
    doc = markdown_to_adf(md)
    b = _first_block(doc)
    assert b["type"] == "orderedList"
    items = b["content"]
    assert [_text_in(it) for it in items] == ["first", "second", "third"]


def test_list_items_carry_inline_marks():
    """`- **bold** item` ⇒ listItem > paragraph > [strong("bold"),
    " item"]."""
    doc = markdown_to_adf("- **bold** item")
    item_para = _first_block(doc)["content"][0]["content"][0]
    nodes = item_para["content"]
    assert nodes[0]["text"] == "bold"
    assert _has_mark(nodes[0], "strong")
    assert nodes[1]["text"] == " item"


# --- (h) blockquote -----------------------------------------------------


def test_blockquote_single_line():
    doc = markdown_to_adf("> a quote")
    b = _first_block(doc)
    assert b["type"] == "blockquote"
    assert _text_in(b) == "a quote"


def test_blockquote_multi_line():
    doc = markdown_to_adf("> line one\n> line two")
    b = _first_block(doc)
    assert b["type"] == "blockquote"
    # The two lines should be joined into one paragraph inside the quote.
    inner = b["content"]
    assert inner[0]["type"] == "paragraph"
    assert _text_in(b) == "line one line two"


# --- (i) links and URLs -------------------------------------------------


def test_explicit_link_and_bare_url_coexist():
    md = "click [here](https://example.com) or see https://other.com/x"
    doc = markdown_to_adf(md)
    nodes = _first_block(doc)["content"]
    # Explicit link
    link_nodes = [n for n in nodes if _has_mark(n, "link")]
    assert any(n["text"] == "here" for n in link_nodes)
    here = next(n for n in link_nodes if n["text"] == "here")
    href = next(m for m in here["marks"] if m["type"] == "link")["attrs"]["href"]
    assert href == "https://example.com"
    # Bare URL auto-linkified
    assert any(n["text"] == "https://other.com/x" for n in link_nodes)


def test_url_with_trailing_punctuation_stripped():
    """A trailing `.` belongs to the sentence, not the URL — pre-fix
    behavior preserved (#57's _text_to_inline_nodes logic carried into
    the markdown parser)."""
    doc = markdown_to_adf("see https://x.com.")
    nodes = _first_block(doc)["content"]
    url_node = next(n for n in nodes if _has_mark(n, "link"))
    assert url_node["text"] == "https://x.com"


# --- (j) plain-text round-trip ------------------------------------------


def test_plain_text_unchanged_shape():
    """Input with no markdown markers produces one paragraph with the
    original text — equivalent to pre-fix `text_to_adf`."""
    doc = text_to_adf("just plain words here")
    blocks = _blocks(doc)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "paragraph"
    assert _text_in(doc) == "just plain words here"


def test_empty_input_yields_empty_paragraph():
    doc = text_to_adf("")
    blocks = _blocks(doc)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "paragraph"


# --- (k) mixed document --------------------------------------------------


def test_mixed_document_block_order():
    md = """# Title

Intro paragraph with **bold**.

- one
- two

```sh
echo hi
```"""
    doc = markdown_to_adf(md)
    blocks = _blocks(doc)
    types = [b["type"] for b in blocks]
    assert types == ["heading", "paragraph", "bulletList", "codeBlock"], types
    assert blocks[0]["attrs"]["level"] == 1
    assert _text_in(blocks[1]) == "Intro paragraph with bold."
    assert [_text_in(it) for it in blocks[2]["content"]] == ["one", "two"]
    assert _text_in(blocks[3]) == "echo hi"


# --- (l) (m) text_to_adf_with_mention body parsing ----------------------


def test_mention_single_line_body_inlines_with_chip():
    """Common case: short reply inlines next to the @mention chip in
    a single paragraph (preserves chat-bubble look)."""
    doc = text_to_adf_with_mention(
        prefix_text="SPEC §9: agent reply",
        mention_account_id="alice-id",
        mention_display="Alice",
        body_text="thanks for the heads-up",
    )
    blocks = _blocks(doc)
    # prefix paragraph + body paragraph
    assert len(blocks) == 2
    body_para = blocks[1]
    assert body_para["type"] == "paragraph"
    types = [n["type"] for n in body_para["content"]]
    assert types[0] == "mention"
    # Body text follows the mention as plain text nodes (no separate
    # leading-space node since we merged the space into the first text).
    assert _text_in(body_para).replace("@Alice", "").strip() == "thanks for the heads-up"


def test_mention_multi_block_body_splits():
    """Body with a heading + list ⇒ mention sits alone, body blocks
    follow as siblings so each renders with its proper ADF shape."""
    body = "## Plan\n\n- step one\n- step two"
    doc = text_to_adf_with_mention(
        prefix_text="",
        mention_account_id="alice-id",
        mention_display="Alice",
        body_text=body,
    )
    blocks = _blocks(doc)
    # Mention paragraph + heading + bulletList = 3 blocks (no prefix).
    types = [b["type"] for b in blocks]
    assert types == ["paragraph", "heading", "bulletList"], types
    # The mention paragraph contains ONLY the mention chip (no inline
    # body text), since the body was multi-block.
    mention_para = blocks[0]
    assert len(mention_para["content"]) == 1
    assert mention_para["content"][0]["type"] == "mention"
    # Heading carries the level.
    assert blocks[1]["attrs"]["level"] == 2


def test_mention_prefix_stays_literal_not_markdown_parsed():
    """The SPEC §9 prefix is intentionally NOT markdown-parsed — it's
    a fixed-shape label that renders as bold via an explicit ADF
    `strong` mark (#27). Markdown in prefix_text would render literally
    (and that's correct: the prefix shouldn't contain markdown)."""
    doc = text_to_adf_with_mention(
        prefix_text="**not parsed as bold**",
        mention_account_id="alice-id",
        mention_display="Alice",
        body_text="hi",
    )
    prefix_para = _blocks(doc)[0]
    assert prefix_para["type"] == "paragraph"
    # The literal asterisks survive; the whole thing carries one strong mark.
    inline = prefix_para["content"][0]
    assert inline["text"] == "**not parsed as bold**"
    assert _has_mark(inline, "strong")


# --- (n) inline_to_adf helper -------------------------------------------


def test_inline_to_adf_returns_inline_nodes_only():
    """`inline_to_adf` is the entry point for callers that already
    have their own block structure (e.g. when building a paragraph
    that should sit next to a mention chip)."""
    nodes = inline_to_adf("plain **bold** and `code`")
    # Three nodes: "plain ", strong("bold"), " and ", code("code")
    # (depending on tokenizer's text-merging behavior; assert by mark
    # rather than exact node count).
    assert any(_has_mark(n, "strong") and n["text"] == "bold" for n in nodes)
    assert any(_has_mark(n, "code") and n["text"] == "code" for n in nodes)


def main() -> int:
    cases = [
        ("headings_levels_1_to_6", test_headings_levels_1_to_6),
        ("heading_requires_space_after_hashes",
         test_heading_requires_space_after_hashes),
        ("bold_star_and_underscore", test_bold_star_and_underscore),
        ("italic_star_and_underscore", test_italic_star_and_underscore),
        ("inline_code", test_inline_code),
        ("bold_inside_text", test_bold_inside_text),
        ("code_block_with_language", test_code_block_with_language),
        ("code_block_without_language", test_code_block_without_language),
        ("bullet_list_mixed_markers", test_bullet_list_mixed_markers),
        ("ordered_list", test_ordered_list),
        ("list_items_carry_inline_marks",
         test_list_items_carry_inline_marks),
        ("blockquote_single_line", test_blockquote_single_line),
        ("blockquote_multi_line", test_blockquote_multi_line),
        ("explicit_link_and_bare_url_coexist",
         test_explicit_link_and_bare_url_coexist),
        ("url_with_trailing_punctuation_stripped",
         test_url_with_trailing_punctuation_stripped),
        ("plain_text_unchanged_shape", test_plain_text_unchanged_shape),
        ("empty_input_yields_empty_paragraph",
         test_empty_input_yields_empty_paragraph),
        ("mixed_document_block_order", test_mixed_document_block_order),
        ("mention_single_line_body_inlines_with_chip",
         test_mention_single_line_body_inlines_with_chip),
        ("mention_multi_block_body_splits",
         test_mention_multi_block_body_splits),
        ("mention_prefix_stays_literal_not_markdown_parsed",
         test_mention_prefix_stays_literal_not_markdown_parsed),
        ("inline_to_adf_returns_inline_nodes_only",
         test_inline_to_adf_returns_inline_nodes_only),
    ]
    failed = 0
    for name, fn in cases:
        try:
            fn()
        except Exception as e:
            print(f"FAIL  {name}: {e}", file=sys.stderr)
            failed += 1
        else:
            print(f"ok    {name}")
    if failed:
        print(f"phase35: {failed} failure(s)", file=sys.stderr)
        return 1
    print("phase35: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
