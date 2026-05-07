---
description: Read the Jira project's `kanban-config` property and print it — read-only inspection without touching local kanban.json.
allowed-tools: Read, Bash(python3:*)
---

# /kanban:show-board-config

Fetch the Jira project's `kanban-config` property and print it as
JSON. Read-only — does NOT update the local cache, does NOT change
any local files. Use this to:

- Inspect what's currently published on Jira (e.g. compare against
  your local `kanban.json` to spot drift)
- Verify a recent `/kanban:push-board-config` actually wrote what
  you expected
- Triage when a teammate's pulled config looks wrong — confirm the
  source-of-truth Jira-side payload before debugging further

## 0. Pre-flight

The command needs a `projectKey`. Resolved in this order:
1. `kanban.json#backend.jira.projectKey` (most common path; pass
   `--kanban-path`)
2. `--project-key` CLI arg directly (e.g. inspecting a project not
   currently configured locally)

## 1. Read

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py read-board-config \
  --kanban-path '<kanban.json path>'
```

Or with explicit project key:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py read-board-config \
  --project-key 'AGENT'
```

| Response | Action |
|---|---|
| `{ok: true, projectKey, propertyKey, config}` | pretty-print the `config` block (transitions, ap, conventions, etc.). Optionally diff against the local `backend.jira` from `kanban.json` and call out any drifted fields. |
| `{ok: false, notFound: true, error}` | print "no board config published on Jira project <projectKey> yet"; if the user has the canonical config locally, suggest `/kanban:push-board-config` |
| `{ok: false, error}` mentioning permission / network | surface verbatim |

## Absolute rules

- Read-only. Never mutate local kanban.json or `.claude/kanban-agent.json`
  from this command. Cache TTL is unaffected — this isn't counted as
  a "successful pull" for passive-sync purposes (use
  `/kanban:pull-board-config` if you actually want to refresh the cache).
- Never echo tokens or any credentials field.
