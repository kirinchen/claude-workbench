---
description: Create a single top-level card (no parent) on the board, auto-tagged with this repo's AP.
argument-hint: --title "..." [--description "..."] [--priority P1] [--issue-type Task]
allowed-tools: Read, Bash(python3:*)
---

# /kanban:create

Create one top-level card in the project's default state and auto-tag it
with this repo's AP, so it shows up on the next `/kanban:doing`. This is the
sibling of `/kanban:create-sub` for the common case where a card has **no
natural parent epic** — drop an issue on the board directly instead of being
forced to invent a parent or go around the plugin.

The card is created via `POST /rest/api/3/issue` and lands in the project's
**default status** (no transition). Use `/kanban:transition` afterwards if it
needs to move.

## 0. Pre-flight

- `kanban.json#backend.driver == "jira"`.
- Parse `$ARGUMENTS`:
  - `--title "..."` (or `--summary "..."`) — **required**, the card summary.
  - `--description "..."` — optional body.
  - `--priority P0|P1|...` — optional.
  - `--issue-type Task|Story|Bug|...` — default `Task`. Must be an issue
    type enabled in your project's workflow.

## 1. Run the helper

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py create \
  --kanban-path '<kanban.json path>' \
  --title '<title>' \
  [--description '<text>'] \
  [--priority P1] \
  [--issue-type Task]
```

Response:

```json
{
  "ok": true,
  "key": "DMI-1100",
  "url": "https://acme.atlassian.net/browse/DMI-1100",
  "title": "standalone card",
  "ap": "agent-fin",
  "apSet": true
}
```

The card is auto-assigned this repo's AP. If `apSet` is `false` (network /
permission / AP field unconfigured), the card still exists — surface that in
the report so the user can fix the AP manually.

## 2. Render

```
✓ Created DMI-1100 (Task): standalone card
    https://acme.atlassian.net/browse/DMI-1100
    AP: agent-fin
```

On `ok: false`, show the `error` verbatim.

## Absolute rules

- This command **never sets a parent** — for breakdown cards under an epic,
  use `/kanban:create-sub`.
- Creation and transition stay separate: the new card lands in the project's
  default status. Don't auto-move it.
- Never invent a title — it must come from the user's request.
