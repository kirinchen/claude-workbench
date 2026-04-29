---
description: Mark a task (default: current DOING) as DONE.
argument-hint: [<task-id>] [--note=<text>]
allowed-tools: Read, Bash(python3:*), Bash(date:*)
---

# /kanban:done

Arguments: `$ARGUMENTS`

Close out a task. The Skill `kanban-workflow` governs the rules.

## 0. Driver check

Read `kanban.json`. Look at `backend.driver`. If absent, treat as `"local"`.
If `"jira"`, follow the Jira flow at the end of this file.

## 1. Parse arguments (local driver)

- `<task-id>` — explicit task to close. If omitted, the helper finds the
  single DOING task with `assignee == "claude-code"`. If 0 or >1, the
  helper returns an error listing the candidates; ask the user which one.
- `--note=<text>` — optional closing comment. Quoted values supported.

## 2. Run the helper

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/kanban_local.py done \
  --kanban-path '<kanban.json path>' \
  [--task-id task-NNN] [--note '<text>']
```

The helper enforces DONE-only-from-DOING, sets `completed`, appends the
note as a comment, and writes atomically. **Do not** call Write/Edit on
`kanban.json`.

## 3. Report

| Shape | Action |
|---|---|
| `{ok: true, id, title, completed, unblocked: [...]}` | print done line; if `unblocked` is non-empty, list those task ids |
| `{ok: false, error, doing: [...]}` | the user has multiple DOING tasks. Show the list and ask which one. |
| `{ok: false, error}` | surface and stop |

Format:

> ✓ <id> "<title>" → DONE.
> Unblocked: <id-1>, <id-2> (was waiting on <id>).

Omit the "Unblocked" line when none.

## Jira flow

In Jira mode, `/kanban:done` transitions DOING → REVIEW. The DONE step is
reserved for a human reviewer — anti-self-approve refuses if the same AP
tries to push to DONE.

Identify the target key from `$ARGUMENTS`. If absent, find the single DOING
card with this repo's AP set (use `/kanban:status` to enumerate; if there
is not exactly one, ask the user).

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py transition \
  --kanban-path '<kanban.json path>' --key '<KEY>' --to REVIEW
```

On success print `✓ <KEY> → In Review (awaiting reviewer)`.

If the helper exits with `kind: self-approve`, surface the error verbatim
and explain another reviewer is required. Do NOT search for workarounds.

## Absolute rules

- Never close a task that isn't DOING (local mode — helper enforces).
- Never retroactively edit `created` or `started`.
- Never close multiple tasks in one invocation.
- Never call Write/Edit on `kanban.json` — go through the helper.
- Jira mode: never push REVIEW → DONE for a card whose AP equals this
  repo's AP. The plugin refuses; do not retry.
