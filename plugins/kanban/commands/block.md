---
description: Move a task to BLOCKED with a required reason.
argument-hint: <task-id> --reason=<text> [--blocked-by=<KEY>[,<KEY>...]]
allowed-tools: Read, Bash(python3:*), Bash(date:*)
---

# /kanban:block

Arguments: `$ARGUMENTS`

Move a task into `BLOCKED` with a mandatory reason. The Skill
`kanban-workflow` governs the rules.

## 0. Driver check

Read `kanban.json`. Look at `backend.driver`. If absent, treat as `"local"`.
If `"jira"`, follow the Jira flow at the end of this file.

## 1. Parse arguments (local driver)

Required:
- `<task-id>` — bare `task-NNN` token.
- `--reason=<text>` — non-empty explanation. Quoted values allowed.

If either is missing or empty, stop and ask the user. Do NOT synthesise a
reason.

## 2. Run the helper

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/kanban_local.py block \
  --kanban-path '<kanban.json path>' \
  --task-id task-NNN --reason '<text>'
```

The helper enforces:
- DONE is terminal (refuses)
- only TODO or DOING can be moved to BLOCKED
- `--reason` is required and must be non-empty
- preserves `started` if the task was DOING
- appends a `Blocked: <reason>` comment for the audit trail

It writes atomically. **Do not** call Write/Edit on `kanban.json`.

## 3. Report

| Shape | Action |
|---|---|
| `{ok: true, id, title, reason, downstream: [...]}` | print the block line; if `downstream` non-empty, list the impacted task ids |
| `{ok: false, error}` | surface and stop |

Format:

> ⛔ <id> "<title>" → BLOCKED
> Reason: <reason>

If `downstream` is non-empty, append: `Downstream impact: <id-1>, <id-2>`.

## Jira flow

Parse `$ARGUMENTS` — accept the same `--reason` as local mode, plus an
optional `--blocked-by=<KEY>[,<KEY>...]` to attach proper Jira "is blocked
by" issue links. Format must match `^[A-Z][A-Z0-9_]+-\d+$` (e.g.
`DMI-1099`). Cross-project blockers are fine (Jira links cross projects
natively).

If the user gives prose like "blocked by DMI-1099 because…", offer to
extract the key — but **don't auto-link silently**. Confirm via
`AskUserQuestion`, then pass the confirmed key as `--blocked-by`.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py transition \
  --kanban-path '<kanban.json path>' --key '<KEY>' --to BLOCKED \
  --reason '<reason text>' \
  [--blocked-by 'DMI-1099,INFRA-7']
```

Order of operations (matters for atomicity):

1. **Validate + create issue links first.** A typoed blocker key (404)
   aborts before the status transition, so the card stays in its current
   state instead of half-blocked. Idempotent — already-linked blockers
   are skipped.
2. Apply the status transition + label add per the canonical mapping.
3. Post the `[<ap>] [S] Blocked: <reason>` audit comment.

Response includes a `depends` list reflecting the issue's "is blocked by"
links after the operation. Surface it in the report:

> ⛔ <KEY> "<title>" → BLOCKED
> Reason: <reason>
> Blocked by: DMI-1099, INFRA-7   (omit if empty)

In `partial` mode (legacy v0.2.x configs that still have `partial: true`),
the plugin substitutes the `kanban:blocked` label and posts the same
audit comment.

## Absolute rules

- Never move a task to BLOCKED without a reason (local mode — helper enforces).
- Never move from DONE to BLOCKED — DONE is terminal.
- Never silently drop the old `started` timestamp (local mode — helper preserves).
- Never call Write/Edit on `kanban.json` — go through the helper.
- Jira mode: never invent a blocker key. The user must explicitly state
  it (or confirm extraction from their prose).
- Jira mode: never block a card by itself (`--blocked-by <self>` is rejected).
- To return a task to active work: today, manual fix via a future
  `/kanban:unblock` command (v0.2.x).
