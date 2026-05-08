---
description: Display the team's `conventions` block — notes + per-team toggles, no edits.
allowed-tools: Read, Bash(python3:*)
---

# /kanban:show-conventions

Read-only display of the current repo's `backend.jira.conventions` —
team rules that travel with the board mapping (issue #10).

## 0. Pre-flight

- Confirm `kanban.json` exists and `backend.driver == "jira"`. If local
  mode, tell the user this is a Jira-mode-only feature.

## 1. Read

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py read-conventions \
  --kanban-path '<kanban.json path>'
```

Returns `{ok, conventions, isEmpty, ackHash, alreadyAcked}`.

## 2. Render

If `isEmpty: true`:

```
This board has no team conventions defined yet.

Conventions are short notes the team agrees on (e.g. "use CANCELLED, not
DELETE", "[@Kirin]-tagged tasks aren't claimed by agents") plus a couple
of per-team toggles. They live on the Jira project's `kanban-config`
property so teammates on other repos / machines see the same rules
automatically on `/kanban:sync`.

Author them via /kanban:edit-conventions, then publish via
/kanban:push-board-config (requires Jira project-admin role).
```

Otherwise:

```
Team conventions:

Notes (<N>):
  1. <note 1>
  2. <note 2>
  ...

Toggles:
  blockedRequiresLink: <true | false (default)>

Acknowledgement: <✓ acknowledged | ⚠ not acknowledged in this repo>
```

If `alreadyAcked` is false, append:

> Run `/kanban:pull-board-config` to refresh and re-acknowledge, or
> just type `I have read these` next time you re-init.

## Absolute rules

- Read-only. Never write.
- Never reveal the ack hash to the user — it's an implementation
  detail used to detect convention drift.
