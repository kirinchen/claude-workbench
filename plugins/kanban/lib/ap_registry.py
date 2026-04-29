"""Agent Property (AP) registry helpers.

AP is the value of a single-select Jira custom field that distinguishes
which AI agent owns a card (humans use the native `assignee`; agents share
one Atlassian account and disambiguate via this property).

This module is pure stdlib so it is trivially unit-testable. It does NOT
talk to Jira — that lives in jira_client + jira_setup.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# SPEC §3.4: AP names are lowercase alnum + hyphens, must start with a letter,
# 3–41 chars total (^[a-z][a-z0-9-]{2,40}$).
AP_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,40}$")

# Default fuzzy-collision threshold (Levenshtein distance). SPEC §16.1
# acknowledges this is noisy for very short names; we ship 2 and revisit.
DEFAULT_FUZZY_THRESHOLD = 2


class APValidationError(ValueError):
    """Raised when an AP name does not match the spec regex."""


def validate_ap_name(name: str) -> None:
    """Raise APValidationError if `name` is not a valid AP."""
    if not isinstance(name, str) or not AP_NAME_RE.match(name):
        raise APValidationError(
            f"invalid AP name {name!r}: must match {AP_NAME_RE.pattern} "
            "(start with a-z, then [a-z0-9-], length 3–41)"
        )


def levenshtein(a: str, b: str) -> int:
    """Classic dynamic-programming Levenshtein distance.

    O(len(a)*len(b)) time, O(len(b)) space. Stable, deterministic.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                curr[j - 1] + 1,        # insertion
                prev[j] + 1,            # deletion
                prev[j - 1] + cost,     # substitution
            )
        prev = curr
    return prev[-1]


@dataclass
class FuzzyHit:
    name: str
    distance: int


def fuzzy_collisions(
    candidate: str,
    existing: list[str] | tuple[str, ...],
    threshold: int = DEFAULT_FUZZY_THRESHOLD,
) -> list[FuzzyHit]:
    """Return existing names within Levenshtein distance `threshold` of
    `candidate`, sorted by distance ascending then name ascending.

    Exact matches (distance 0) are returned — the caller decides whether to
    treat them as a hard duplicate (refuse) or a near-duplicate (warn).
    """
    hits: list[FuzzyHit] = []
    cand = candidate.lower()
    for ex in existing:
        d = levenshtein(cand, ex.lower())
        if d <= threshold:
            hits.append(FuzzyHit(name=ex, distance=d))
    hits.sort(key=lambda h: (h.distance, h.name))
    return hits


def is_exact_collision(candidate: str, existing: list[str] | tuple[str, ...]) -> bool:
    """Case-insensitive exact match against `existing`."""
    cand = candidate.lower()
    return any(cand == ex.lower() for ex in existing)
