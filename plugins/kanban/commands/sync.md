---
description: Pull the open-card summary for the current AP. Driver-aware.
allowed-tools: Read, Bash(python3:*), Bash(git:*)
---

# /kanban:sync

Refresh the agent's view of the kanban state.

- **Local mode**: re-read `kanban.json` and surface DOING + BLOCKED tasks
  (same content the SessionStart hook would print).
- **Jira mode**: pull open cards (TODO / DOING / BLOCKED / REVIEW) for the
  current repo's AP and render the summary block.

This command is also invoked automatically on `SessionStart` (jira mode)
via `kanban-jira-sync.sh`. Run it explicitly when you suspect the cached
state is stale or you just resumed the session after a break.

## 0. Resolve repo

`$CLAUDE_PROJECT_DIR` if set, else `git rev-parse --show-toplevel`, else cwd.
Kanban file at `<repo>/kanban.json` — if missing, suggest `/kanban:init`.

## 1. Driver branch

Read `kanban.json#backend.driver` (default `local`).

### Local

Read `kanban.json`. Render:

```
Kanban sync (local · v0.2)

DOING:
  task-042  [P1 trading]  重寫 grid pricing dynamic classifier  (since 2026-04-20)

BLOCKED:
  task-004  [P1 bug]      Investigate flaky test on macOS — Need access to macOS runner logs.

(No DOING/BLOCKED → "All clear.")
```

### Jira

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py sync-summary \
  --kanban-path '<kanban.json path>'
```

Returns `{summary, counts, ap, projectKey}`. Print the `summary` field
verbatim. If `summary` is empty, print `(no open cards for ap=<ap>)`.

If the helper exits non-zero, surface its `error` field. Common causes:
- `Jira credentials missing` → suggest `/kanban:reset-credentials`
- `kanban-agent.json` missing → suggest `/kanban:assign-ap <name>`

## Absolute rules

- Read-only. Never write to `kanban.json`, the cache, or Jira.
- Never invent data — if the helper says no cards, say no cards.
