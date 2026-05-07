---
description: Push the local backend.jira block to the Jira project's `kanban-config` property — admin-only, makes this team's config the canonical source for all receivers.
allowed-tools: Read, Bash(python3:*), AskUserQuestion
---

# /kanban:push-board-config

Write this repo's `backend.jira` block (transitions DSL, AP field id,
boardId/Url, projectKey, conventions) to the Jira project property
`kanban-config`. After this push, **anyone running `/kanban:sync` on
the same Jira project** will receive your config on their next stale-
cache refresh (within 8 hours), or immediately on `/kanban:pull-
board-config`.

This replaces the older `/kanban:showjira-code` → paste →
`/kanban:import-jira-code` round-trip flow. **Single source of truth
on Jira**; receivers don't have to be told the steps.

## Permission requirement

Writing project entity properties requires the agent's Jira account
to have **project-admin role** on this project. If you get
`permission denied`, ask a project admin to push (or grant the agent
admin role on this project — Jira UI: Project Settings → Permissions
→ Administrators).

## 0. Pre-flight

- Confirm `kanban.json` exists. If missing, run `/kanban:init` then
  `/kanban:initjira` first.
- Confirm `backend.driver == "jira"` and `backend.jira.transitions`
  is non-empty. The push payload comes from those local fields.
- Warn the user this overwrites whatever's currently on the Jira
  project property (last-writer-wins; Atlassian doesn't do ETag
  versioning on properties). For routine pushes from a single source
  repo this is the expected flow; for "sync from teammate" cases
  consider `/kanban:pull-board-config` instead.

## 1. Push

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py push-board-config \
  --kanban-path '<kanban.json path>'
```

| Response | Action |
|---|---|
| `{ok: true, projectKey, propertyKey, fieldsPushed}` | print `✓ Pushed <fieldsPushed.length> fields to Jira project <projectKey> properties.<propertyKey>`; mention all teammates' next `/kanban:sync` will pick this up |
| `{ok: false, error}` mentioning `permission denied` | surface verbatim; explain admin role is required |
| `{ok: false, error}` mentioning network / 4xx / 5xx | surface verbatim |

## 2. What gets pushed

The agent strips per-machine fields before pushing:
- `agentAccountId` — per-Atlassian-account, not per-board
- `ap.registered` — local hint for the AP roster; Jira itself is the
  source of truth (read live via `/kanban:live-list-aps`)

Pushed fields: `boardUrl`, `boardId`, `projectKey`, `transitions`,
`ap.fieldId`, `ap.fieldName`, `conventions`.

## Absolute rules

- **Never** push without explicit user intent — this overwrites the
  team's shared config. If a teammate just made changes you'd be
  clobbering theirs.
- Never mock up the config — only push the actual `backend.jira`
  block from this repo's `kanban.json`.
- Never write to `kanban.json` from this command (push is a one-way
  upload to Jira; doesn't mutate the local cache except marking it
  freshly synced).
- If push fails on permission, do NOT retry with a different account
  or workaround — the right move is to ask a project admin.
