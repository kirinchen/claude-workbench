---
description: Rename a Jira card (replace its summary / title).
argument-hint: <KEY> "<new summary>" [--override-ap]
allowed-tools: Read, Bash(python3:*)
---

# /kanban:rename

Replace a Jira card's summary (title). The Jira changelog records the
before/after, so no separate audit log is written.

Use cases:
- Renaming after scope clarification ("foo bar" → "foo bar (cache
  layer only)").
- Fixing a typo or wrong key prefix in the title.
- Renormalising the title to match the team's naming convention.

## 0. Pre-flight

- `kanban.json#backend.driver == "jira"`.
- Parse `$ARGUMENTS`:
  - `<KEY>` — Jira issue key.
  - `"<new summary>"` — quoted string, becomes the card's new title.
    Must be non-empty (whitespace-only is rejected).
  - `--override-ap` — acknowledge AP-mismatch warning when editing a
    teammate's card. Surfaced but non-blocking.

## 1. Run the helper

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py update-summary \
  --kanban-path '<kanban.json path>' \
  --key '<KEY>' \
  --summary '<new summary>' \
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

## 2. Render

```
✓ Renamed BZK-645 to "<new summary>"
```

If `warnings: ["ap-mismatch"]`, add a one-line callout — the user
should know they just edited a teammate's card.

## Absolute rules

- Never rename a closed (APPROVED / CANCELLED) card unless the user
  explicitly asked. Closed-card titles are meant to be stable for
  search / linking.
- Never invent a "better" title on the agent's own initiative. Renames
  must come from the user's request or a clear scope clarification
  in the card's comments.
- Don't strip the team's title conventions (key prefixes, area tags)
  unless the user specifically asked you to.
