---
description: Set the current repo's Agent Property (AP) — written to .claude/kanban-agent.json.
argument-hint: <ap-name>
allowed-tools: Read, Bash(python3:*), AskUserQuestion
---

# /kanban:assign-ap

Arguments: `$ARGUMENTS`

Persist this repo's AP identity to `.claude/kanban-agent.json`. Subsequent
slash commands and hooks read from there to know which AP this repo's agent
operates as. The AP must already be in `kanban.json#backend.jira.ap.registered`
— if not, run `/kanban:register-ap <name>` first.

## 0. Pre-flight

- Confirm `kanban.json#backend.driver == "jira"`. If `local`, tell the user
  AP is meaningful only in Jira mode.
- Parse `$ARGUMENTS` for the AP name. If absent, ask via `AskUserQuestion`.

## 1. Persist

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py \
  assign-ap --kanban-path '<kanban.json path>' --name '<ap-name>'
```

On `{ok: true, ap, path}`: print:

```
✓ this repo is now operating as AP "<name>".
  Written to: <path>
```

On `{ok: false, error: ..., registered: [...]}`: surface the error and the
list of registered APs verbatim. Suggest `/kanban:register-ap <name>` if the
user wants to add the AP.

## 2. Git-policy reminder

If the user has not already committed `.claude/kanban-agent.json`, tell them
this file is intended to be committed (per SPEC §3.4 / §16.2 default — team
sees per-repo agent identity). They can override by adding it to `.gitignore`
manually if multiple humans run different agents in the same repo.

## Absolute rules

- Refuse if the AP is not registered — never silently create both registry
  entry and assignment in one call. Registration must be deliberate.
- Never edit `kanban.json` from this command — only `.claude/kanban-agent.json`.
