"""Compound transition specs (kanban v0.3+).

Replaces the v0.2 `statusMap` + `labelFallback` flat mapping with a richer
per-canonical record:

    {
      "TODO":      { "status": "Selected for Development" },
      "BLOCKED":   { "status": "進行中", "addLabels": ["kanban:blocked"] },
      "REVIEW":    { "status": "進行中", "addLabels": ["kanban:review"],
                     "assignee": { "accountId": "5e..." } },
      "CANCELLED": { "status": "完成", "addLabels": ["kanban:cancelled"] }
    }

Multiple canonicals may share the same Jira status (e.g. DOING/BLOCKED/
REVIEW all on `進行中`); reader disambiguation uses labels (most-specific
match wins).

Public surface:
    parse_dsl(text, *, current_user_account_id=None,
              user_lookup=None) -> dict[CANONICAL, TransitionSpec]
    suggest_from_jira(found) -> SuggestionResult
    migrate_legacy(jira_cfg) -> dict
    validate(transitions, available_statuses) -> list[str]
    canonical_default_label(canonical) -> str
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


CANONICAL_COLUMNS = ("TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED")


# --- DSL -----------------------------------------------------------------


_LABEL_KW = re.compile(r"^(?:label)\b\s*(?P<name>.*)$", re.IGNORECASE)
_ASSIGNEE_KW = re.compile(
    r"^(?:assignee)\s+to\s+(?P<who>.+?)\s*(?:\(\s*(?P<hint>[^)]*)\s*\))?\s*$",
    re.IGNORECASE,
)


def canonical_default_label(canonical: str) -> str:
    return f"kanban:{canonical.lower()}"


def _parse_components(rest: str) -> tuple[str, list[str], dict[str, Any]]:
    """Split the `+`-joined right-hand side into (status, labels, assignee_raw)."""
    parts = [p.strip() for p in rest.split("+")]
    if not parts or not parts[0]:
        raise ValueError("missing status (left of +)")
    status_token = parts[0]
    add_labels: list[str] = []
    assignee: dict[str, Any] | None = None

    for tok in parts[1:]:
        if not tok:
            continue
        m_label = _LABEL_KW.match(tok)
        m_assignee = _ASSIGNEE_KW.match(tok)
        if m_assignee:
            who = m_assignee.group("who").strip()
            assignee = {"_who": who}
        elif m_label:
            name = (m_label.group("name") or "").strip()
            add_labels.append(name)  # empty → fill default later
        else:
            raise ValueError(f"unknown component {tok!r} (expected `label` or `assignee to ...`)")

    return status_token, add_labels, ({} if assignee is None else assignee)


def parse_dsl(
    text: str,
    *,
    current_user_account_id: str | None = None,
    user_lookup: Callable[[str], str | None] | None = None,
) -> dict[str, dict[str, Any]]:
    """Parse a multi-line DSL block. Each non-blank line:
        CANONICAL > status [+ Label[ name]] [+ Assignee to me|<name>]

    `CANONICAL` is one of TODO, DOING, BLOCKED, REVIEW, DONE, CANCELLED.

    The status field on the right may be an UPPERCASE canonical name
    referring to another canonical's resolved status (e.g.
    `CANCELLED > DONE + label` reuses canonical DONE's Jira status).

    Returns a dict ready to write into `backend.jira.transitions`.
    Raises ValueError on syntax error / unknown canonical / cycle / missing
    user lookup when needed.
    """
    pre: dict[str, dict[str, Any]] = {}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ">" not in line:
            raise ValueError(f"missing `>` separator: {raw_line!r}")
        head, sep, tail = line.partition(">")
        canonical = head.strip().upper()
        if canonical not in CANONICAL_COLUMNS:
            raise ValueError(
                f"unknown canonical {canonical!r}; expected one of {CANONICAL_COLUMNS}"
            )
        if canonical in pre:
            raise ValueError(f"duplicate entry for {canonical!r}")
        try:
            status_tok, labels, assignee = _parse_components(tail.strip())
        except ValueError as e:
            raise ValueError(f"line {raw_line!r}: {e}") from e
        pre[canonical] = {
            "status_raw": status_tok,
            "addLabels": labels,
            "assignee_raw": assignee,
        }

    out: dict[str, dict[str, Any]] = {}

    def resolve_status(col: str, seen: set[str]) -> str:
        if col in seen:
            raise ValueError(
                f"circular self-reference involving {col!r}: {' -> '.join(sorted(seen))}"
            )
        info = pre.get(col)
        if info is None:
            raise ValueError(
                f"{col!r} is referenced as another canonical's status but is "
                "not defined in this DSL"
            )
        st = info["status_raw"]
        ref = st.upper() if st.isupper() else None
        if ref and ref in CANONICAL_COLUMNS:
            return resolve_status(ref, seen | {col})
        return st

    for col, info in pre.items():
        spec: dict[str, Any] = {"status": resolve_status(col, set())}
        if info["addLabels"]:
            resolved = []
            for lbl in info["addLabels"]:
                resolved.append(lbl if lbl else canonical_default_label(col))
            spec["addLabels"] = resolved
        if info["assignee_raw"]:
            who = info["assignee_raw"].get("_who", "").strip()
            account_id = None
            if who.lower() == "me":
                account_id = current_user_account_id
                if not account_id:
                    raise ValueError(
                        f"{col}: 'Assignee to me' requires the current "
                        "user's accountId — pass --current-user-account-id"
                    )
            elif user_lookup:
                account_id = user_lookup(who)
            if not account_id:
                raise ValueError(
                    f"{col}: cannot resolve assignee {who!r} to an accountId; "
                    "pass --current-user-account-id (for 'me') or use a "
                    "user_lookup callable"
                )
            spec["assignee"] = {"accountId": account_id}
        out[col] = spec
    return out


# --- Auto-suggester ------------------------------------------------------


_LIBERAL_NAME_RULES: dict[str, str] = {
    "todo": "TODO",
    "to do": "TODO",
    "to-do": "TODO",
    "open": "TODO",
    "doing": "DOING",
    "in progress": "DOING",
    "inprogress": "DOING",
    "wip": "DOING",
    "blocked": "BLOCKED",
    "on hold": "BLOCKED",
    "review": "REVIEW",
    "in review": "REVIEW",
    "code review": "REVIEW",
    "done": "DONE",
    "closed": "DONE",
    "resolved": "DONE",
    "cancelled": "CANCELLED",
    "canceled": "CANCELLED",
    "wontfix": "CANCELLED",
    "won't fix": "CANCELLED",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


@dataclass
class Suggestion:
    canonical: str
    status: str
    confidence: float
    reason: str


@dataclass
class SuggestionResult:
    suggestions: dict[str, dict[str, Any]] = field(default_factory=dict)
    unmapped: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    raw_found: list[dict[str, Any]] = field(default_factory=list)


def suggest_from_jira(
    found: Iterable[dict[str, Any]],
) -> SuggestionResult:
    """Return a best-effort canonical→status suggestion from a project's
    Jira statuses. Each `found` entry must have at least `name`; `category`
    (Atlassian's statusCategory.key) is used when present.
    """
    found_list = list(found)
    candidates: dict[str, list[Suggestion]] = {c: [] for c in CANONICAL_COLUMNS}

    for entry in found_list:
        name = entry.get("name") or ""
        category = (entry.get("category") or "").lower()
        norm = _norm(name)

        # 1. Liberal name match (English-flavoured).
        if norm in _LIBERAL_NAME_RULES:
            cat = _LIBERAL_NAME_RULES[norm]
            candidates[cat].append(
                Suggestion(cat, name, 1.0, f"name match ({norm})")
            )
            continue

        # 2. statusCategory hint.
        if category == "indeterminate":
            candidates["DOING"].append(
                Suggestion("DOING", name, 0.95, "statusCategory=indeterminate")
            )
        elif category == "done":
            candidates["DONE"].append(
                Suggestion("DONE", name, 0.95, "statusCategory=done")
            )
        elif category == "new":
            candidates["TODO"].append(
                Suggestion("TODO", name, 0.6, "statusCategory=new (ambiguous)")
            )

    out = SuggestionResult(raw_found=found_list)
    for canonical in CANONICAL_COLUMNS:
        cands = sorted(candidates[canonical], key=lambda s: -s.confidence)
        if not cands:
            out.unmapped.append(canonical)
            continue
        best = cands[0]
        out.suggestions[canonical] = {
            "status": best.status,
            "confidence": best.confidence,
            "reason": best.reason,
        }
        # Mark ambiguous if multiple high-confidence candidates exist.
        same_high = [c for c in cands if c.confidence >= 0.6]
        if len(same_high) > 1:
            out.ambiguous.append(canonical)
    return out


# --- Legacy migration ----------------------------------------------------


_LEGACY_LABEL_FALLBACK_DEFAULTS = {
    # If the legacy file lacks an explicit fallback, infer reasonable status reuse.
    "BLOCKED": "DOING",
    "REVIEW": "DOING",
    "CANCELLED": "DONE",
}


def migrate_legacy(jira_cfg: dict[str, Any]) -> dict[str, Any]:
    """Convert a v0.2-shaped backend.jira block (statusMap + labelFallback +
    partial) into a v0.3 transitions block. Returns the input unchanged when
    `transitions` is already populated.

    Lossless on the writer's intent — preserves what the user had:
    - statusMap entries become bare-status transitions.
    - labelFallback entries become transitions sharing another canonical's
      status (per `_LEGACY_LABEL_FALLBACK_DEFAULTS`) with `addLabels`.
    """
    cfg = dict(jira_cfg or {})
    if cfg.get("transitions"):
        cfg.pop("statusMap", None)
        cfg.pop("labelFallback", None)
        cfg.pop("partial", None)
        return cfg

    status_map = cfg.get("statusMap") or {}
    label_fb = cfg.get("labelFallback") or {}
    if not status_map and not label_fb:
        return cfg

    transitions: dict[str, dict[str, Any]] = {}
    for col, status in status_map.items():
        if col in CANONICAL_COLUMNS and isinstance(status, str) and status:
            transitions[col] = {"status": status}

    for col, label in label_fb.items():
        if col not in CANONICAL_COLUMNS or not isinstance(label, str):
            continue
        if col in transitions:
            transitions[col].setdefault("addLabels", []).append(label)
            continue
        share = _LEGACY_LABEL_FALLBACK_DEFAULTS.get(col)
        if share and share in transitions:
            transitions[col] = {
                "status": transitions[share]["status"],
                "addLabels": [label],
            }
        # else: orphan — drop, surface in validate()

    cfg["transitions"] = transitions
    cfg.pop("statusMap", None)
    cfg.pop("labelFallback", None)
    cfg.pop("partial", None)
    return cfg


# --- Validation ----------------------------------------------------------


def validate(
    transitions: dict[str, Any],
    available_statuses: Iterable[str] | None = None,
) -> list[str]:
    """Return a list of human-readable validation errors. Empty list = OK."""
    errs: list[str] = []
    if not isinstance(transitions, dict):
        return ["transitions must be an object"]
    avail = {s for s in (available_statuses or [])}
    for col, spec in transitions.items():
        if col not in CANONICAL_COLUMNS:
            errs.append(f"unknown canonical {col!r}")
            continue
        if not isinstance(spec, dict):
            errs.append(f"{col}: spec must be an object")
            continue
        status = spec.get("status")
        if not isinstance(status, str) or not status:
            errs.append(f"{col}: missing or empty `status`")
        elif avail and status not in avail:
            errs.append(
                f"{col}: status {status!r} not present in the project's "
                f"workflow ({sorted(avail)})"
            )
        for key in ("addLabels", "removeLabels"):
            v = spec.get(key)
            if v is not None and not (
                isinstance(v, list) and all(isinstance(x, str) and x for x in v)
            ):
                errs.append(f"{col}: {key} must be a list of non-empty strings")
        a = spec.get("assignee")
        if a is not None:
            if not isinstance(a, dict) or not a.get("accountId"):
                errs.append(f"{col}: assignee must be {{accountId: ...}}")
    return errs


# --- Read-back disambiguation -------------------------------------------


def disambiguate(
    transitions: dict[str, dict[str, Any]],
    issue_status: str,
    issue_labels: Iterable[str],
) -> str | None:
    """Given a Jira issue's status + labels, pick the canonical column whose
    transition spec best matches.

    Algorithm (most-specific wins):
      1. Filter to specs whose `status == issue_status`.
      2. Drop any whose `addLabels` are not all in `issue_labels`, or whose
         `removeLabels` overlap `issue_labels`.
      3. Among remaining, pick the spec with the most labels matched
         (i.e. specificity). Tie-break by canonical alphabetical order.
      4. Fallback: a spec with no `addLabels`/`removeLabels` at all.
    Returns canonical name, or None if nothing matches.
    """
    labels = set(issue_labels or [])
    matching: list[tuple[str, dict[str, Any], int]] = []
    bare_fallback: str | None = None
    for col, spec in transitions.items():
        if spec.get("status") != issue_status:
            continue
        add = set(spec.get("addLabels") or [])
        remove = set(spec.get("removeLabels") or [])
        if add and not add.issubset(labels):
            continue
        if remove and remove & labels:
            continue
        matching.append((col, spec, len(add)))
        if not add and not remove:
            bare_fallback = bare_fallback or col
    if not matching:
        return None
    matching.sort(key=lambda t: (-t[2], t[0]))
    best = matching[0]
    if best[2] == 0 and bare_fallback:
        return bare_fallback
    return best[0]
