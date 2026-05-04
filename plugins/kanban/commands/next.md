---
description: DEPRECATED — use /kanban:doing (Jira mode) or /kanban:next is still the local-mode pick-one helper.
argument-hint: [--category=X] [--priority=Y] [<task-id>]
allowed-tools: Read, Bash(python3:*), Bash(date:*)
---

# /kanban:next  *(deprecated for Jira mode — see /kanban:doing)*

Arguments: `$ARGUMENTS`

## 0. Driver check + deprecation nudge

Read `kanban.json#backend.driver`. If absent, treat as `"local"`.

- **Jira mode**: this command is **deprecated**. Print a deprecation
  notice and stop:

  ```
  /kanban:next is deprecated for Jira mode (kanban@0.3.16 — see #33).
  Use /kanban:doing instead — it works the cards already in DOING
  rather than pulling from TODO. Owner curates TODO → DOING; agent
  executes DOING.
  ```

  Do **not** auto-pick. The agent must not be the one moving cards
  from TODO into DOING.

- **Local mode**: continue with the existing flow below. Local mode
  has no AP / curation distinction, so the pick-one semantics are
  still correct here.

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

The helper enforces all dependency / priority / APPROVED-immutability rules and
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

## Absolute rules

- **Jira mode**: never auto-pick from TODO. The deprecation nudge above
  is the only correct behavior. See #33 for the rationale.
- Never start a task whose deps are not all APPROVED (local mode — helper enforces).
- Never start a task in APPROVED or BLOCKED.
- Never call the Write/Edit tool on `kanban.json` — go through the helper.
