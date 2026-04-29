---
description: Show current kanban driver state — project, board, AP, token validity.
allowed-tools: Read, Bash(python3:*), Bash(git:*)
---

# /kanban:whoami

Read-only summary of the kanban configuration in this repo. Never displays
the API token value — only `present` / `missing` / `valid` / `invalid`.

## 1. Resolve repo

`$CLAUDE_PROJECT_DIR` if set, else `git rev-parse --show-toplevel`, else
current working directory.

## 2. Inspect kanban.json

Read `kanban.json`. If missing: print `Repo: <path>\nDriver: (no kanban.json — run /kanban:init)` and stop.

Pull `version` (default `0.1`), `backend.driver` (default `local`).

## 3. Branch on driver

### Local driver

```
Repo:     <path>
Driver:   local
Schema:   <version>
Tasks:    <count of tasks[]>  (DOING <n> · BLOCKED <n>)
```

Stop here.

### Jira driver

Pull `backend.jira.{boardUrl, boardId, projectKey}`. Then:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py read-credentials
```

For token validity, run health (will hit /myself):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py health \
  --kanban-path '<kanban.json path>'
```

Token row maps from health.status:
- `ok` → `✓ valid`
- `unauthenticated` → `✗ invalid (re-run /kanban:reset-credentials)`
- `unreachable` → `? unknown (network)`
- `degraded` → `? degraded — <detail>`

Read this repo's AP via the helper (it parses `.claude/kanban-agent.json`):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py read-agent-ap \
  --kanban-path '<kanban.json path>'
```

Also pull `backend.jira.ap.registered` from `kanban.json` for the AP roster.

Render:

```
Repo:             <path>
Driver:           jira
Base URL:         <baseUrl>
Email:            <email>
Project:          <projectKey>
Board:            #<boardId>
AP field:         <fieldName> (<fieldId> — or "(unconfigured — run /kanban:initjira)")
AP (this repo):   <ap or "(unset — run /kanban:assign-ap <name>)">
AP (registered):  <comma-list or "(empty — run /kanban:register-ap <name>)">
Token:            <validity row>
Workflow:         full | partial (fallback: BLOCKED, REVIEW, CANCELLED)
```

## Absolute rules

- Never display the token value, only its validity.
- Never write to `kanban.json` or `.env` from this command.
- If health returns a network error, print the row and continue — do not abort.
