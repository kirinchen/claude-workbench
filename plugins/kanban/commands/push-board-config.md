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

**Single source of truth on Jira**; receivers don't have to be told
the steps — they get the latest config automatically on `/kanban:sync`
(8h passive-sync TTL) or via `/kanban:pull-board-config` on demand.

(0.3.27 retired the older `kanban-jira-code` paste flow. Older repos
that never published board config can do so via this command — see
the migration guide in CHANGELOG 0.3.27.)

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
- Each push attaches a `_meta` block (version, content hash, pushedAt,
  pushedByAccountId — #57) so future pushes can detect "remote moved
  since I pulled" without Atlassian-side ETag support. By default the
  push is **fenced**: it refuses when remote's content hash doesn't
  match the hash this machine last pulled or pushed. Pass `--force`
  to bypass.

## 1. Push

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py push-board-config \
  --kanban-path '<kanban.json path>' \
  [--force]
```

Behavior:
- The helper auto-fills `--if-match` from the local cached
  `_meta.hash` (set by the last successful pull or push). First push
  on a project with no remote `_meta` yet has no fence — it just
  initializes `version: 1`.
- If a teammate pushed since your last pull, the push is refused and
  the response carries the remote's current `_meta` so you can see
  who pushed, when, and at what hash. Resolve by running
  `/kanban:pull-board-config`, reconciling any local edits, then
  pushing again.
- `--force` skips the fence — use only when intentionally clobbering.

| Response | Action |
|---|---|
| `{ok: true, projectKey, propertyKey, fieldsPushed, meta}` | print `✓ Pushed <fieldsPushed.length> fields to Jira project <projectKey> properties.<propertyKey> (v<meta.version>)`; mention all teammates' next `/kanban:sync` will pick this up |
| `{ok: false, error, ifMatchMismatch: true, remoteMeta, expectedHash}` | surface verbatim; recommend `/kanban:pull-board-config` to fetch the new version, reconcile any local edits, then re-push |
| `{ok: false, error}` mentioning `permission denied` | surface verbatim; explain admin role is required |
| `{ok: false, error}` mentioning network / 4xx / 5xx | surface verbatim |

## 2. What gets pushed

The agent strips per-machine fields before pushing:
- `agentAccountId` — per-Atlassian-account, not per-board
- `ap.registered` — local hint for the AP roster; Jira itself is the
  source of truth (read live via `/kanban:live-list-aps`)
- `_meta` from local — push always regenerates `_meta` from the
  freshly-fetched remote version + the new content hash.

Pushed fields: `boardUrl`, `boardId`, `projectKey`, `transitions`,
`ap.fieldId`, `ap.fieldName`, `conventions`, plus a fresh `_meta`.

## Absolute rules

- **Never** push without explicit user intent — this overwrites the
  team's shared config. If a teammate just made changes you'd be
  clobbering theirs.
- Never mock up the config — only push the actual `backend.jira`
  block from this repo's `kanban.json`.
- The command writes the just-pushed `_meta` back into local
  `kanban.json#backend.jira._meta` so the next push on this machine
  can auto-fill `--if-match` without an intervening pull. Nothing
  else in the local cache is mutated.
- If push fails on permission, do NOT retry with a different account
  or workaround — the right move is to ask a project admin.
- If push fails with `ifMatchMismatch: true`, do NOT auto-retry with
  `--force` — that's the clobber path. Pull first, reconcile, push.
