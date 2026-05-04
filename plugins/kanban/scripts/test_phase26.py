#!/usr/bin/env python3
"""Phase 26 regression checks for kanban v0.3.21 — clickable URLs in
ADF comment / description bodies.

User-reported (session, no GitHub issue): URLs that the agent posts in
a Jira comment or description render as plain text, not clickable
links. ADF doesn't auto-linkify — text nodes need an explicit
`marks: [{type: "link", attrs: {href: "..."}}]` to be clickable.

The fix: a `_text_to_inline_nodes(text)` helper splits the body on a
conservative URL regex, wraps URL spans in link-marked text nodes,
keeps non-URL spans as plain text. All three ADF builders
(`text_to_adf`, `text_to_adf_with_mention`, `_agent_comment_body`)
use it.

Cases:
  (a) `_text_to_inline_nodes` with a single URL produces 1 link-marked
      node when the entire string is the URL.
  (b) URL in the middle splits into [text, link, text] nodes.
  (c) URL at end-of-sentence strips trailing punctuation off the URL —
      "see https://x.com." → URL "https://x.com" + plain ".".
  (d) URL inside parens / brackets doesn't pull the closing bracket
      into the link.
  (e) Multiple URLs in one string each get their own link mark.
  (f) Empty / no-URL text returns plain text nodes (or empty list).
  (g) `text_to_adf("see https://x.com")` produces a doc whose paragraph
      contains a link-marked node for the URL.
  (h) `text_to_adf_with_mention(..., body_text="reply at https://x.com")`
      keeps the mention chip + a plain space + a link-marked URL node.
  (i) `_agent_comment_body` (driver-level) emits a 2-paragraph doc
      whose body paragraph carries link marks for URLs (and the prefix
      paragraph keeps its strong mark, untouched).
  (j) `adf_to_text` round-trips the link-marked output back to a plain
      string (lossy on marks but text content preserved).
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"
sys.path.insert(0, str(REPO / "plugins" / "kanban"))

from lib.jira_client import (  # noqa: E402
    _text_to_inline_nodes,
    adf_to_text,
    text_to_adf,
    text_to_adf_with_mention,
)


# --- (a)..(f) helper unit tests -----------------------------------------


def _link_href(node):
    for m in node.get("marks") or []:
        if m.get("type") == "link":
            return (m.get("attrs") or {}).get("href")
    return None


def test_inline_nodes_single_url():
    nodes = _text_to_inline_nodes("https://example.com/path")
    assert len(nodes) == 1
    assert nodes[0]["text"] == "https://example.com/path"
    assert _link_href(nodes[0]) == "https://example.com/path"


def test_inline_nodes_url_in_middle():
    nodes = _text_to_inline_nodes("see https://example.com for details")
    texts = [n["text"] for n in nodes]
    assert texts == ["see ", "https://example.com", " for details"]
    assert _link_href(nodes[1]) == "https://example.com"
    # Surrounding nodes are plain (no link mark)
    assert _link_href(nodes[0]) is None
    assert _link_href(nodes[2]) is None


def test_inline_nodes_strips_trailing_punctuation():
    """A URL at end-of-sentence shouldn't pull the period into the link."""
    nodes = _text_to_inline_nodes("see https://x.com.")
    texts = [n["text"] for n in nodes]
    assert texts == ["see ", "https://x.com", "."]
    assert _link_href(nodes[1]) == "https://x.com"
    # Trailing "." is plain text, not part of the link
    assert _link_href(nodes[2]) is None


def test_inline_nodes_does_not_swallow_close_bracket():
    """URL in parens shouldn't include the close-paren in the link."""
    nodes = _text_to_inline_nodes("(see https://x.com) for more")
    texts = [n["text"] for n in nodes]
    # The regex stops at the close-paren via the `[^...)]+` exclusion
    assert texts[0] == "(see "
    assert texts[1] == "https://x.com"
    assert _link_href(nodes[1]) == "https://x.com"
    # The closing ")" is in the trailing plain-text span
    assert ")" in "".join(n["text"] for n in nodes[2:])


def test_inline_nodes_multiple_urls():
    nodes = _text_to_inline_nodes(
        "first https://a.example then https://b.example end"
    )
    link_nodes = [n for n in nodes if _link_href(n)]
    assert len(link_nodes) == 2
    assert _link_href(link_nodes[0]) == "https://a.example"
    assert _link_href(link_nodes[1]) == "https://b.example"


def test_inline_nodes_no_url_or_empty():
    # Plain text with no URL → single plain-text node
    nodes = _text_to_inline_nodes("just words")
    assert nodes == [{"type": "text", "text": "just words"}]
    # Empty string → empty list (caller decides how to fill an empty
    # paragraph; usually with a single empty text node)
    assert _text_to_inline_nodes("") == []


# --- (g) text_to_adf wraps in a doc + link mark survives ----------------


def test_text_to_adf_preserves_link_mark():
    adf = text_to_adf("see https://x.com")
    assert adf["type"] == "doc"
    para = adf["content"][0]
    assert para["type"] == "paragraph"
    # Find the link-marked node
    link_nodes = [n for n in para["content"] if _link_href(n)]
    assert len(link_nodes) == 1
    assert _link_href(link_nodes[0]) == "https://x.com"


# --- (h) text_to_adf_with_mention keeps URL clickable in body -----------


def test_text_to_adf_with_mention_keeps_link_in_body():
    adf = text_to_adf_with_mention(
        prefix_text="[ap] [C]",
        mention_account_id="user-123",
        mention_display="Kirin",
        body_text="reply at https://example.com later",
    )
    # Doc has 2 paragraphs: prefix + (mention + body)
    assert len(adf["content"]) == 2
    body_para = adf["content"][1]
    types = [n["type"] for n in body_para["content"]]
    assert types[0] == "mention"
    # Subsequent body nodes include the link-marked URL
    link_nodes = [n for n in body_para["content"]
                  if n.get("type") == "text" and _link_href(n)]
    assert len(link_nodes) == 1
    assert _link_href(link_nodes[0]) == "https://example.com"


# --- (i) _agent_comment_body keeps strong prefix + link in body ---------


def test_agent_comment_body_preserves_prefix_and_links():
    """Driver-level builder. Prefix paragraph keeps its strong mark
    (the #27 fix), body paragraph gets URLs as link-marked nodes."""
    from drivers.jira import JiraDriver
    from drivers.base import CommentKind
    from lib import credentials

    orig = credentials.read
    credentials.read = lambda prefix=None: {
        "JIRA_BASE_URL": "https://x", "JIRA_AGENT_EMAIL": "a@b",
        "JIRA_API_TOKEN": "tok",
    }
    try:
        with tempfile.TemporaryDirectory() as td:
            data = {
                "version": "0.2",
                "backend": {"driver": "jira", "jira": {
                    "boardUrl": "https://x/projects/A/boards/1",
                    "boardId": 1, "projectKey": "A",
                    "transitions": {"DONE": {"status": "Done"}},
                }},
                "meta": {"priorities": ["P0"], "categories": [],
                         "columns": ["TODO", "DOING", "BLOCKED",
                                     "REVIEW", "DONE", "CANCELLED"],
                         "created_at": "x", "updated_at": "x"},
                "tasks": [],
            }
            drv = JiraDriver(data, pathlib.Path(td))

            adf = drv._agent_comment_body(
                "details at https://docs.example.com — please review",
                CommentKind.COMMENT,
                ap="agent-fin",
            )
    finally:
        credentials.read = orig

    # Prefix paragraph: single text node with strong mark, no link
    prefix_para = adf["content"][0]
    assert prefix_para["type"] == "paragraph"
    p0 = prefix_para["content"][0]
    assert p0["text"] == "[agent-fin] [C]"
    assert {"type": "strong"} in p0["marks"]
    assert _link_href(p0) is None  # prefix has NO link mark

    # Body paragraph: contains a link-marked node for the URL
    body_para = adf["content"][1]
    link_nodes = [n for n in body_para["content"] if _link_href(n)]
    assert len(link_nodes) == 1
    assert _link_href(link_nodes[0]) == "https://docs.example.com"


# --- (j) adf_to_text round-trip ------------------------------------------


def test_adf_to_text_roundtrip_preserves_text_drops_marks():
    """adf_to_text concatenates text nodes regardless of marks — so
    URL-marked output flattens back to a plain string with the URL
    inline. Confirms the link mark is non-destructive to existing
    text-extraction callers."""
    adf = text_to_adf("see https://x.com later")
    flat = adf_to_text(adf)
    assert flat == "see https://x.com later"


def main() -> int:
    cases = [
        ("inline_nodes_single_url", test_inline_nodes_single_url),
        ("inline_nodes_url_in_middle", test_inline_nodes_url_in_middle),
        ("inline_nodes_strips_trailing_punctuation",
         test_inline_nodes_strips_trailing_punctuation),
        ("inline_nodes_does_not_swallow_close_bracket",
         test_inline_nodes_does_not_swallow_close_bracket),
        ("inline_nodes_multiple_urls", test_inline_nodes_multiple_urls),
        ("inline_nodes_no_url_or_empty", test_inline_nodes_no_url_or_empty),
        ("text_to_adf_preserves_link_mark",
         test_text_to_adf_preserves_link_mark),
        ("text_to_adf_with_mention_keeps_link_in_body",
         test_text_to_adf_with_mention_keeps_link_in_body),
        ("agent_comment_body_preserves_prefix_and_links",
         test_agent_comment_body_preserves_prefix_and_links),
        ("adf_to_text_roundtrip_preserves_text_drops_marks",
         test_adf_to_text_roundtrip_preserves_text_drops_marks),
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
        print(f"phase26: {failed} failure(s)", file=sys.stderr)
        return 1
    print("phase26: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
