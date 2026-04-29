---
description: Pick the next kanban task and move it to DOING.
argument-hint: [--category=X] [--priority=Y]
allowed-tools: Read, Write, Bash(date:*), Bash(jq:*)
---

# /kanban:next

Arguments: `$ARGUMENTS`

Pick the next eligible TODO task, move it to DOING, then begin executing it. The Skill `kanban-workflow` (loaded automatically) governs the rules.

## 0. Driver check

Read `kanban.json` first. Look at `backend.driver`. If absent, treat as `"local"`. If `"jira"`, follow the Jira flow at the end of this file.

## 1. Load state (local driver)

Read `kanban.json` fresh. Do not rely on earlier reads from this session.

## 2. Parse filters from `$ARGUMENTS`

Support:
- `--category=<cat>` → only consider tasks with that category.
- `--priority=<prio>` → only consider tasks at or above that priority (i.e. `priorityIndex ≤ index_of(<prio>)`).
- No argument → no filter.

## 3. Build candidate set

Apply, in order:
1. `column == "TODO"`.
2. Every id in `depends` exists **and** is in column `DONE`.
3. User filters from step 2.

## 4. Rank

Sort by:
1. `meta.priorities.indexOf(task.priority)` ascending.
2. `created` ascending.
3. `id` ascending.

## 5. Handle the result

- **0 candidates**: report why (no TODO? all blocked by deps? filtered out?) and stop. Do NOT start anything.
- **1 candidate**: proceed to step 6.
- **≥ 2 candidates in the same top priority**: show the top 3 with id / title / priority / category and ask the user to pick. Stop until they answer.

## 6. Move to DOING

1. Re-read `kanban.json` (concurrency guard). Confirm the chosen task is still in TODO with deps satisfied. If not, abort and report.
2. Get current timestamp: `date -Iseconds`.
3. Produce a new kanban.json with:
   - Chosen task: `column = "DOING"`, `started = <now>`, `updated = <now>`, `assignee = "claude-code"` if unset.
   - `meta.updated_at = <now>`.
   - All other tasks unchanged.
4. Write the file. (The `kanban-guard.sh` hook blocks ad-hoc edits, but this command is explicitly allowed.)

## 7. Announce and begin

Briefly report:

> Starting task-042 "<title>" (P1, category=trading).
> Deps satisfied: task-038, task-040.

Then begin executing the task described in `description`. Treat `description` as the brief — ask the user for clarification if anything is ambiguous rather than guessing.

## Jira flow

Pick the highest-priority TODO card scoped to this repo's AP, transition it
to `In Progress`, and post a `[<ap>] [S] claimed` system comment. The driver
honours the `statusMap` configured at init time.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py claim-next \
  --kanban-path '<kanban.json path>'
```

Parse the response:

| Shape | Action |
|---|---|
| `{ok: true, claimed: {id, title, priority, ap}}` | print `Claiming <id> "<title>" (P<n>, ap=<ap>)`, then begin executing the card |
| `{ok: true, claimed: null, reason}` | print `No TODO cards for AP <ap>` and stop |
| `{ok: false, error}` | surface verbatim and stop. If error mentions `kanban-agent.json`, suggest `/kanban:assign-ap`. |

Then read the card details if you need them (`get_task` via the helper or by
asking Jira directly through `/kanban:status`) — the description there is
your brief.

## Absolute rules

- Never start a task whose deps are not all DONE (local mode).
- Never start a task in DONE or BLOCKED.
- Never start more than one task at a time in the same session. If a DOING task already exists with assignee `claude-code`, confirm with the user before starting a new one.
- Jira mode: never bypass `claim-next` — it enforces AP routing.
