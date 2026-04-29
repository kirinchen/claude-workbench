"""Detect Jira card references (keys + URLs) in arbitrary text.

SPEC §5.1 patterns:
    KEY:    \\b[A-Z][A-Z0-9_]+-[0-9]+\\b           e.g. AGENT-42, FIN-103
    URL:    https?://.../browse/<KEY>
    URL:    https?://.../?selectedIssue=<KEY>

Project key prefix must match `backend.jira.projectKey` to avoid false
positives from past chats and unrelated repos. We dedupe results, preserve
first-occurrence order, and do not normalise case (keys are uppercase by
construction).
"""
from __future__ import annotations

import re
from collections.abc import Iterable


# A Jira issue key. Allows underscore in the project portion (e.g. AGENT_BOT-12).
_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9_]+)-(\d+)\b")
_URL_KEY_RE = re.compile(
    r"https?://[^/\s]+/(?:browse/|.*?[?&]selectedIssue=)([A-Z][A-Z0-9_]+-\d+)"
)


def extract_keys(text: str) -> list[str]:
    """Return all KEY-N references in `text`, deduped, in document order."""
    if not text:
        return []
    matches: list[tuple[int, str]] = []
    consumed_ranges: list[tuple[int, int]] = []
    for m in _URL_KEY_RE.finditer(text):
        matches.append((m.start(), m.group(1)))
        consumed_ranges.append(m.span())

    def _within_url(pos: int) -> bool:
        return any(start <= pos < end for start, end in consumed_ranges)

    for m in _KEY_RE.finditer(text):
        if _within_url(m.start()):
            continue  # the URL pass already captured this
        matches.append((m.start(), f"{m.group(1)}-{m.group(2)}"))

    matches.sort(key=lambda pair: pair[0])

    seen: set[str] = set()
    out: list[str] = []
    for _, key in matches:
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def filter_by_project(keys: Iterable[str], project_key: str) -> list[str]:
    """Keep only KEYs whose project portion equals `project_key`."""
    if not project_key:
        return list(keys)
    prefix = f"{project_key}-"
    return [k for k in keys if k.startswith(prefix)]


def extract_for_project(text: str, project_key: str) -> list[str]:
    """Convenience: extract + filter in one call."""
    return filter_by_project(extract_keys(text), project_key)
