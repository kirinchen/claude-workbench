---
description: Replace the description (body) of a Jira card.
argument-hint: <KEY> [--body "..." | --from-file <path>|-] [--format text|adf] [--override-ap]
allowed-tools: Read, Bash(python3:*)
---

# /kanban:edit-description

Replace a Jira card's description in place. Default format is plain
text (rendered to Jira's ADF). Pass `--format adf` to send a literal
ADF JSON document instead.

Use cases:
- Consolidating sub-card content back into a parent after the
  breakdown work finishes.
- Rewriting a stale TODO list in the description so the next agent
  reading the card sees current scope.
- Fixing a typo or clarifying acceptance criteria.

The Jira changelog records the before/after, so this command does NOT
write its own audit log — `delete` is the only mutating primitive that
does (the card itself disappears, taking the changelog with it).

## 0. Pre-flight

- `kanban.json#backend.driver == "jira"`.
- Parse `$ARGUMENTS`:
  - `<KEY>` — Jira issue key (`^[A-Z][A-Z0-9_]+-\d+$`).
  - Exactly one of:
    - `--body "<text>"` — inline body. Quote literals.
    - `--from-file <path>` — read body from a file. Pass `-` to read
      from stdin (useful for piping LLM-generated content).
  - `--format text|adf` — default `text`. Use `adf` only if you have a
    pre-built ADF document; otherwise the helper renders text → ADF.
  - `--override-ap` — acknowledge the AP-mismatch warning when the
    card belongs to a different agent. Currently surfaced but
    non-blocking; the flag exists so future strict mode can refuse
    without it.

## 1. Run the helper

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py update-description \
  --kanban-path '<kanban.json path>' \
  --key '<KEY>' \
  --body '<text>'       # or: --body-file <path-or-->
  [--format adf] \
  [--override-ap]
```

Response:

```json
{
  "ok": true,
  "key": "BZK-645",
  "warnings": []
}
```

`warnings: ["ap-mismatch"]` appears when the card's AP differs from
yours — proceed only if the user explicitly asked you to edit a
teammate's card. The slash command does NOT refuse on its own.

## 2. Render

```
✓ Updated description on BZK-645
```

If `warnings` is non-empty, include a one-line callout:

```
✓ Updated description on BZK-645
⚠ ap-mismatch — this card is owned by a different agent
```

## Absolute rules

- Never edit a closed (APPROVED / CANCELLED) card's description without
  the user explicitly asking. The card is meant to be a frozen record.
- Never overwrite a description with placeholder content (`TBD`,
  empty, "wip"). If you don't have the new body, ask the user.
- Don't bundle this with a transition — keep edits and status changes
  separate so the changelog reads cleanly.
