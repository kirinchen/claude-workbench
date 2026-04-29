---
description: Mark a task (default: current DOING) as DONE.
argument-hint: [<task-id>] [--note=<text>]
allowed-tools: Read, Write, Bash(date:*), Bash(jq:*)
---

# /kanban:done

Arguments: `$ARGUMENTS`

Close out a task. The Skill `kanban-workflow` governs the rules.

## 0. Driver check

Read `kanban.json`. Look at `backend.driver`. If absent, treat as `"local"`. If `"jira"`, follow the Jira flow at the end of this file.

## 1. Resolve target task (local driver)

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

## Jira flow

In Jira mode, `/kanban:done` transitions DOING → REVIEW. The actual DONE
transition is reserved for a human reviewer (or another agent) — anti-self-
approve will refuse if the same AP tries to push to DONE.

Identify the target key from `$ARGUMENTS`. If absent, find the single DOING
card with this repo's AP set (use `/kanban:status` to enumerate; if there is
not exactly one, ask the user to specify).

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py transition \
  --kanban-path '<kanban.json path>' --key '<KEY>' --to REVIEW
```

On success print `✓ <KEY> → In Review (awaiting reviewer)`.

If the user explicitly asks to mark DONE — for example a one-person team
where the human owner uses Jira UI normally — they should approve via the
Jira UI from a different account, not via this slash command. The plugin
deliberately refuses self-approval; do not search for workarounds.

If the helper exits with `kind: self-approve`, surface the error verbatim
and explain that another reviewer is required.

## Absolute rules

- Never close a task that isn't DOING (local mode).
- Never retroactively edit `created` or `started`.
- Never close multiple tasks in one invocation — one at a time keeps the commit log clean.
- Jira mode: never push REVIEW → DONE for a card whose AP equals this repo's AP. The plugin refuses; do not retry with `--force` or hand-rolled API calls.
