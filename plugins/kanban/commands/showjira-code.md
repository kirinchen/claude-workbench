---
description: Print the current repo's Jira mapping as a shareable JSON code.
argument-hint: [--include-agent-account]
allowed-tools: Read, Bash(python3:*), Bash(git:*)
---

# /kanban:showjira-code

Emit the current `kanban.json#backend.jira` block as a compact JSON code
suitable for pasting into another repo / another machine via
`/kanban:initjira-by-code`. Use this to share a board's compound-transition
mapping across teammates' machines without re-running the DSL setup
everywhere.

## What's in the code

- `boardUrl`, `boardId`, `projectKey`
- `transitions` (the entire compound mapping from
  `/kanban:initjira` step 3)
- `ap.fieldId`, `ap.fieldName` (so the receiver maps to the same Jira
  custom field)

## What's deliberately excluded

- `ap.registered` — this is a stale local mirror; the receiving machine
  will live-query Jira's actual options on first `/kanban:assign-ap`.
- `agentAccountId` — only included with `--include-agent-account`. Skip
  by default because the receiving team / machine may use a different
  shared agent Atlassian account.
- API token, base URL credentials — never. Those live in
  `~/.claude-workbench/.env` and are per-machine; the receiver runs
  `/kanban:reset-credentials` (or step 1 of `/kanban:initjira-by-code`).

## 0. Pre-flight

- `$CLAUDE_PROJECT_DIR` (or `git rev-parse --show-toplevel`) → kanban.json
  path. If missing, suggest `/kanban:init` then `/kanban:initjira`.
- Check `backend.driver == "jira"`. If `local`, tell the user this command
  is jira-only and suggest `/kanban:initjira` first.

## 1. Run the helper

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py emit-jira-code \
  --kanban-path '<kanban.json path>' \
  [--include-agent-account]   # only if user explicitly asked
```

The helper returns `{ok: true, code: {...}}`.

## 2. Render

Print the code as a fenced JSON block, then a one-line hint:

```
Share this code with your teammates. They paste it into
/kanban:initjira-by-code and skip the DSL setup.

```json
{
  "schema": "kanban-jira-code/1",
  "boardUrl": "https://acme.atlassian.net/jira/software/projects/AGENT/boards/1",
  "boardId": 1,
  "projectKey": "AGENT",
  "transitions": { ... },
  "ap": { "fieldId": "customfield_10042", "fieldName": "Claude Agent" }
}
\```

(Each receiver still needs their own Jira credentials — the code does
NOT contain tokens. Run `/kanban:initjira-by-code` on the receiver
side; if they don't yet have credentials saved, the command will
capture them up-front.)
```

## Absolute rules

- Never include the API token or any credential material in the code.
- Never include `ap.registered` — this is live state on Jira, not part
  of the shareable mapping.
- Default to omitting `agentAccountId`; only include with the explicit
  `--include-agent-account` flag.
- The code is plain JSON. Do not transform it (base64, hex, etc.) — the
  user must be able to inspect it before pasting.
