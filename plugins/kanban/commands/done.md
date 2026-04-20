---
description: Mark a task (default: current DOING) as DONE.
argument-hint: [<task-id>] [--note=<text>]
allowed-tools: Read, Write, Bash(date:*), Bash(jq:*)
---

# /kanban:done

Arguments: `$ARGUMENTS`

Close out a task. The Skill `kanban-workflow` governs the rules.

## 1. Resolve target task

Parse `$ARGUMENTS`:
- If an explicit `task-NNN` is present: target is that task.
- Otherwise: find the single task with `column == "DOING"` and `assignee == "claude-code"`. If there are 0 or multiple, list them and ask the user which one.

Parse `--note=<text>`: optional closing comment. Support quoted values.

## 2. Validate

Re-read `kanban.json` fresh. Confirm:
- Target task exists.
- `column == "DOING"`. If it's already DONE, say so and stop. If TODO/BLOCKED, refuse and explain.

## 3. Move to DONE

1. `date -Iseconds` → now.
2. Produce new kanban.json:
   - Target task: `column = "DONE"`, `completed = <now>`, `updated = <now>`.
   - If `--note=<text>` was passed: append a comment `{author: "claude-code", ts: <now>, text: <note>}` to `comments`.
   - `meta.updated_at = <now>`.
3. Write.

## 4. Report

> ✓ task-042 "<title>" → DONE.
> Unblocked: task-050 (was waiting on task-042).

Compute "unblocked" by finding any task in TODO whose `depends` included the closed task and are now fully satisfied. List their ids.

## Absolute rules

- Never close a task that isn't DOING.
- Never retroactively edit `created` or `started`.
- Never close multiple tasks in one invocation — one at a time keeps the commit log clean.
