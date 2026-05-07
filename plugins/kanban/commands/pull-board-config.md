---
description: Pull the Jira project's `kanban-config` property and refresh the local kanban.json cache. Runs automatically on /kanban:sync when cache > 8h old; this command forces an immediate sync.
allowed-tools: Read, Bash(python3:*)
---

# /kanban:pull-board-config

Fetch the Jira project's `kanban-config` property and overwrite this
repo's `backend.jira` block with it. Records the sync timestamp so
the 8h passive-sync TTL clock resets.

**You don't usually need this command.** `/kanban:sync` (which runs at
SessionStart) already pulls automatically when the cache is stale
(≥ 8h since last pull). Run this command when:

- You know the team just pushed new config and want the update now
  (don't want to wait for the next session)
- Your local `backend.jira` looks wrong / drifted and you want to
  reset to the canonical Jira-side version
- Bootstrapping a fresh repo on a new machine — see
  `/kanban:initjira` for the guided flow that includes a pull

## 0. Pre-flight

- Confirm `kanban.json` exists. If missing, run `/kanban:init` first.
- The command needs a `projectKey` to know which project's property
  to read. Resolved in this order:
  1. `kanban.json#backend.jira.projectKey` (most common path)
  2. `--project-key` CLI arg (used when local cache hasn't been
     populated yet — e.g. fresh-machine bootstrap)

## 1. Pull

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py pull-board-config \
  --kanban-path '<kanban.json path>' \
  [--project-key '<KEY>']
```

| Response | Action |
|---|---|
| `{ok: true, projectKey, propertyKey, transitionsCount}` | print `✓ Pulled board config from Jira project <projectKey> (<transitionsCount> transitions)`; mention `/kanban:whoami` to verify cache freshness |
| `{ok: false, notFound: true, error}` | print the error verbatim; suggest `/kanban:push-board-config` to publish this repo's config (if user has admin role) |
| `{ok: false, error}` mentioning permission / network | surface verbatim; cache stays stale |

## 2. What gets overwritten + what's preserved

**Overwritten** (Jira-side wins):
- `transitions` (the DSL — full block)
- `boardUrl`, `boardId`, `projectKey`
- `ap.fieldId`, `ap.fieldName`
- `conventions`

**Preserved** (per-machine state):
- `agentAccountId` — your local Atlassian account binding
- `ap.registered` — local AP roster hint (refresh separately via
  `/kanban:live-list-aps` if it looks stale)

## Absolute rules

- Never write to Jira from this command — it's a one-way download.
- Never echo or mutate any token-related field.
- If pull fails, the existing local `kanban.json` stays untouched —
  you continue using the previous cache.
