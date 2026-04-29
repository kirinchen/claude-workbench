---
description: Move a task to BLOCKED with a required reason.
argument-hint: <task-id> --reason=<text>
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

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py transition \
  --kanban-path '<kanban.json path>' --key '<KEY>' --to BLOCKED \
  --reason '<reason text>'
```

The driver posts a `[<ap>] [S] Blocked: <reason>` system comment alongside
the transition. In `partial` mode, the plugin substitutes the
`kanban:blocked` label and posts the same audit comment.

## Absolute rules

- Never move a task to BLOCKED without a reason (local mode — helper enforces).
- Never move from DONE to BLOCKED — DONE is terminal.
- Never silently drop the old `started` timestamp (local mode — helper preserves).
- Never call Write/Edit on `kanban.json` — go through the helper.
- To return a task to active work: today, manual fix via a future
  `/kanban:unblock` command (v0.2.x).
