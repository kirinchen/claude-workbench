#!/usr/bin/env python3
"""Phase 16 regression checks for kanban v0.3.9 — locale-stable Jira responses.

Closes #17. Adding `Accept-Language: en-US` to every Jira API request
forces English responses regardless of the agent account's UI locale.
The plugin's DSL stores status / priority / issue-type names in English;
without this header, a zh-TW (or any non-English) account caused Jira
to return localized names and transition lookup silently failed.

Cases:
  (a) Accept-Language: en-US header is present on GET requests
  (b) Same header on POST requests (with body)
  (c) Same header on PUT requests
  (d) Header doesn't displace existing Authorization / Accept / Content-Type
  (e) Even on retried requests (429), the header rides along on each retry
  (f) End-to-end: a transition lookup that would have failed with a
      localized to.name response works because the production server now
      returns English (we can only verify our request shape; the server
      behaviour is its responsibility)
"""
from __future__ import annotations

import json
import sys
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"
sys.path.insert(0, str(REPO / "plugins" / "kanban"))

from lib.jira_client import JiraClient, _Response  # noqa: E402


def _mock(queue, calls):
    def t(method, url, headers, body):
        # Snapshot the headers dict — caller may mutate it on retry path
        calls.append({
            "method": method,
            "url": url,
            "body": body,
            "headers": dict(headers),
        })
        if not queue:
            raise AssertionError(f"queue empty for {method} {url}")
        return queue.pop(0)
    return t


def _client(queue, calls):
    return JiraClient(
        "https://x.atlassian.net", "a@b", "tok",
        transport=_mock(queue, calls), sleep=lambda _: None,
    )


# --- header presence ----------------------------------------------------


def test_get_sends_accept_language_en_us():
    queue = [_Response(200, b'{"accountId":"x"}', {})]
    calls = []
    c = _client(queue, calls)
    c.get_myself()
    assert calls[0]["headers"].get("Accept-Language") == "en-US"


def test_post_sends_accept_language():
    queue = [_Response(200, b'{"issues":[]}', {})]
    calls = []
    c = _client(queue, calls)
    c.search_jql("project = X")
    assert calls[0]["method"] == "POST"
    assert calls[0]["headers"].get("Accept-Language") == "en-US"


def test_put_sends_accept_language():
    queue = [_Response(204, b"", {})]
    calls = []
    c = _client(queue, calls)
    # update_issue uses PUT internally
    c.update_issue("X-1", {"labels": ["foo"]})
    assert calls[0]["method"] == "PUT"
    assert calls[0]["headers"].get("Accept-Language") == "en-US"


def test_existing_headers_unchanged():
    """Adding Accept-Language must not displace Authorization / Accept /
    Content-Type."""
    queue = [_Response(200, b"{}", {})]
    calls = []
    c = _client(queue, calls)
    c.search_jql("project = X")
    h = calls[0]["headers"]
    assert h["Accept-Language"] == "en-US"
    assert h["Accept"] == "application/json"
    assert h["Content-Type"] == "application/json"  # POST has body
    assert h["Authorization"].startswith("Basic ")


def test_get_no_content_type_but_accept_language():
    """A GET (no body) shouldn't carry Content-Type, but should carry
    Accept-Language."""
    queue = [_Response(200, b"{}", {})]
    calls = []
    c = _client(queue, calls)
    c.get_myself()
    h = calls[0]["headers"]
    assert h.get("Content-Type") is None or h.get("Content-Type") == "application/json"
    # Note: the client only sets Content-Type when body is non-None.
    # When body is None, Content-Type is absent; verify that.
    assert "Content-Type" not in h
    assert h["Accept-Language"] == "en-US"


# --- header rides along on retry ---------------------------------------


def test_accept_language_on_each_retry():
    """A 429 retry sequence sends the header on every attempt — the
    locale assumption mustn't break under retry pressure."""
    queue = [
        _Response(429, b"", {"retry-after": "0.01"}),
        _Response(429, b"", {"retry-after": "0.01"}),
        _Response(200, b'{"accountId":"x"}', {}),
    ]
    calls = []
    c = _client(queue, calls)
    c.get_myself()
    assert len(calls) == 3
    for call in calls:
        assert call["headers"].get("Accept-Language") == "en-US"


# --- end-to-end transition lookup with the header ----------------------


def test_transition_lookup_works_with_english_response():
    """Documents the contract: assuming Jira honours Accept-Language: en-US
    (which it does on Cloud), `to.name` comes back as `In Progress`
    rather than `進行中`, and the existing string-match in
    JiraDriver.transition succeeds. We can't drive a real localized
    server in a unit test, but we can verify the request carries the
    header that triggers English behaviour.
    """
    queue = [
        _Response(200, json.dumps({
            "transitions": [
                {"id": "21", "to": {"name": "In Progress"}},
                {"id": "31", "to": {"name": "Done"}},
            ]
        }).encode(), {}),
    ]
    calls = []
    c = _client(queue, calls)
    resp = c.get_transitions("AGENT-1")
    assert resp["transitions"][0]["to"]["name"] == "In Progress"
    # Header check: any production zh-TW user would have got 進行中
    # without the header. The fix is the header.
    assert calls[0]["headers"].get("Accept-Language") == "en-US"


def main() -> int:
    cases = [
        ("get_sends_accept_language_en_us", test_get_sends_accept_language_en_us),
        ("post_sends_accept_language", test_post_sends_accept_language),
        ("put_sends_accept_language", test_put_sends_accept_language),
        ("existing_headers_unchanged", test_existing_headers_unchanged),
        ("get_no_content_type_but_accept_language",
         test_get_no_content_type_but_accept_language),
        ("accept_language_on_each_retry", test_accept_language_on_each_retry),
        ("transition_lookup_works_with_english_response",
         test_transition_lookup_works_with_english_response),
    ]
    for name, fn in cases:
        try:
            fn()
        except AssertionError as e:
            print(f"FAIL  {name}: {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"ERROR {name}: {type(e).__name__}: {e}", file=sys.stderr)
            return 2
        print(f"ok    {name}")
    print("phase16: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
