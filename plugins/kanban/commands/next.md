---
description: Pick the next kanban task and move it to DOING.
argument-hint: [--category=X] [--priority=Y] [<task-id>]
allowed-tools: Read, Bash(python3:*), Bash(date:*)
---

# /kanban:next

Arguments: `$ARGUMENTS`

Pick the next eligible TODO task and transition it to DOING. The Skill
`kanban-workflow` (loaded automatically) governs the rules.

## 0. Driver check

Read `kanban.json` first. Look at `backend.driver`. If absent, treat as
`"local"`. If `"jira"`, follow the Jira flow at the end of this file.

## 1. Parse arguments (local driver)

Support:
- `--category=<cat>` — only consider tasks with that category.
- `--priority=<prio>` — only consider tasks at or above that priority.
- A bare `task-NNN` token — claim that specific task instead of auto-picking.
- No argument — auto-pick.

## 2. Run the helper

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/kanban_local.py next \
  --kanban-path '<kanban.json path>' \
  [--category <cat>] [--priority <prio>] [--task-id task-NNN]
```

The helper enforces all dependency / priority / DONE-immutability rules and
writes the file via atomic `os.replace`, sidestepping the kanban-guard
PreToolUse hook. **Do not** call the Write or Edit tool on `kanban.json`.

## 3. Handle the response

| Shape | Action |
|---|---|
| `{ok: true, claimed: {id, title, priority, deps, ...}}` | print the claim line and begin executing the task |
| `{ok: true, claimed: null, candidates: [...top-3...], reason}` | the top priority is tied — list the candidates and ask the user to pick by `task-id`, then re-run with `--task-id` |
| `{ok: true, claimed: null, candidates: [], reason}` | nothing to claim (no TODOs / all blocked / filters too strict). Print the reason verbatim and stop. |
| `{ok: false, error}` | surface the error and stop |

When you have a successful claim, briefly report:

> Starting <id> "<title>" (P<n>, category=<cat>).
> Deps satisfied: <list>.

Then begin executing the task described in `description`. Treat
`description` as the brief — ask the user for clarification if anything is
ambiguous rather than guessing.

## Jira flow

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py claim-next \
  --kanban-path '<kanban.json path>'
```

| Shape | Action |
|---|---|
| `{ok: true, claimed: {id, title, priority, ap}}` | print `Claiming <id> "<title>" (P<n>, ap=<ap>)`, begin executing |
| `{ok: true, claimed: null, reason}` | print `No TODO cards for AP <ap>` and stop |
| `{ok: false, error}` | surface verbatim. If error mentions `kanban-agent.json`, suggest `/kanban:assign-ap`. |

## Absolute rules

- Never start a task whose deps are not all DONE (local mode — helper enforces).
- Never start a task in DONE or BLOCKED.
- Never start more than one task at a time in the same session. If a DOING
  task already exists with assignee `claude-code`, confirm with the user
  before starting a new one.
- Never call the Write/Edit tool on `kanban.json` — go through the helper.
- Jira mode: never bypass `claim-next` — it enforces AP routing.
