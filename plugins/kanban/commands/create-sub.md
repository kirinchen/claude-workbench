---
description: Spawn N sub-cards from a parent issue, linked back via Jira issue link.
argument-hint: <parent-KEY> --title "..." [--title "..."] [--link-type Relates|Sub-task]
allowed-tools: Read, Bash(python3:*)
---

# /kanban:create-sub

Create one or more sub-cards under a parent issue. Each new card is
created via `POST /rest/api/3/issue` and then linked back to the parent
with a Jira issue link of type `--link-type` (default: `Relates`).

This is the "large workload" arm of the @-mention reply flow:

> Human: `@AgentBot 評估一下這個可行性 就開始動工`
> Bot: (decides work is too big for one card) →
>   `/kanban:create-sub DMI-1099 --title "design schema" --title "wire endpoint" --title "wire UI"` →
>   then `/kanban:reply DMI-1099 --to <kirin> --body "Spawned 3 sub-cards: ..."`

## 0. Pre-flight

- `kanban.json#backend.driver == "jira"`.
- Parse `$ARGUMENTS`:
  - `<parent-KEY>` — bare token, must match `^[A-Z][A-Z0-9_]+-\d+$`.
  - `--title "..."` — repeatable. **At least one required.** Each
    becomes one sub-card's summary.
  - `--description "..."` — optional shared description for all spawned
    cards. (Per-card descriptions need separate calls.)
  - `--priority P0|P1|...` — optional, applied to every spawned card.
  - `--link-type Relates|Sub-task|Blocks` — default `Relates`. Use
    `Sub-task` only if your project's workflow has the Sub-task issue
    type enabled (varies per project).

## 1. Run the helper

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py create-sub \
  --kanban-path '<kanban.json path>' \
  --parent '<parent-KEY>' \
  --title '<t1>' [--title '<t2>' ...] \
  [--description '<text>'] \
  [--priority P1] \
  [--link-type Relates]
```

Response:

```json
{
  "ok": true,
  "parent": "DMI-1099",
  "linkType": "Relates",
  "created": [
    {"key": "DMI-1100", "title": "design schema"},
    {"key": "DMI-1101", "title": "wire endpoint"}
  ],
  "failed": []
}
```

Each created card is auto-assigned this repo's AP (so it shows up on
the next `/kanban:doing`). If the AP assignment fails (network /
permission), the card still exists — surface in the report.

## 2. Render

```
✓ Spawned 3 sub-cards under DMI-1099 (linked via Relates):
    DMI-1100  design schema
    DMI-1101  wire endpoint
    DMI-1102  wire UI
```

If `failed` is non-empty, list the failures and continue (the user can
retry just the missing titles).

## 3. Recommended next steps (LLM)

After spawning sub-cards, the LLM typically:

1. `/kanban:reply <parent> --to <commenter-accountId> --body "..."`
   — notify the human about the breakdown.
2. Owner reviews the sub-cards and moves the first one to DOING
   (TODO → DOING is the owner's call — see #33). When the @-mention
   from the owner explicitly authorizes start, the agent may instead
   call `/kanban:transition <first-sub> --to DOING`.
3. `/kanban:doing` — read the DOING pool and pick up the first sub-card.
4. Work on it, complete via `/kanban:done`.
5. Move to the next sub-card.

Don't work all sub-cards in parallel — the kanban-workflow skill says
"never start more than one task at a time in the same session."

## Absolute rules

- Never spawn sub-cards without the human's explicit ask (or in
  response to an @-mention with clear "do it" intent). Don't proactively
  break down cards that look big.
- Never omit the parent — sub-cards without a parent should just be
  created via `/kanban:create` and worked through `/kanban:doing`.
- Never invent titles — they must come from the user's request or the
  LLM's classified breakdown of the parent's description.
