---
description: Move a task to BLOCKED with a required reason.
argument-hint: <task-id> --reason=<text>
allowed-tools: Read, Write, Bash(date:*)
---

# /kanban:block

Arguments: `$ARGUMENTS`

Move a task out of the active flow into `BLOCKED` with a mandatory reason. The Skill `kanban-workflow` governs the rules.

## 1. Parse arguments

Required:
- `<task-id>` — a bare `task-NNN` token.
- `--reason=<text>` — non-empty explanation. Quoted values allowed.

If either is missing or empty, stop and ask the user. Do NOT synthesise a reason.

## 2. Validate

Read `kanban.json` fresh. Confirm:
- Task exists.
- Current column is `TODO` or `DOING`. If already `BLOCKED`, report and stop. If `DONE`, refuse — DONE is immutable.

## 3. Transition

1. `date -Iseconds` → now.
2. Produce new kanban.json:
   - Target task: `column = "BLOCKED"`, `updated = <now>`.
   - If the task was `DOING`, keep `started` — do NOT clear it. The task retains its started time for when it returns to DOING.
   - Ensure `custom` exists; set `custom.blocked_reason = <reason>` (verbatim).
   - Append a comment: `{author: "claude-code", ts: <now>, text: "Blocked: <reason>"}`.
   - `meta.updated_at = <now>`.
3. Write.

## 4. Report

> ⛔ task-042 "<title>" → BLOCKED
> Reason: <reason>

If any other task's `depends` references the blocked task, list them (downstream impact).

## Absolute rules

- Never move a task to BLOCKED without a reason.
- Never move from DONE to BLOCKED — DONE is terminal.
- Never silently drop the old `started` timestamp.
- To return a task to active work, use an edit through `/kanban:*` commands that clear `custom.blocked_reason` and move back to TODO (today: manual fix via a future `/kanban:unblock` command; v0.2.0).
