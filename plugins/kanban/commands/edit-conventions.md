---
description: Author or edit the team's `conventions` block — narrative notes + per-team toggles.
allowed-tools: Read, Bash(python3:*), AskUserQuestion
---

# /kanban:edit-conventions

Interactive editor for `backend.jira.conventions`. After editing, push
to the Jira project so teammates see the new rules on their next
`/kanban:sync` (passive sync, ≤ 8h) or immediate
`/kanban:pull-board-config`.

## 0. Pre-flight

- `kanban.json` exists and `backend.driver == "jira"`.

## 1. Show current state

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py read-conventions \
  --kanban-path '<kanban.json path>'
```

Render the existing `notes` (numbered) and toggles (`blockedRequiresLink`).

## 2. Notes editor (interactive)

For each existing note (in order), ask via `AskUserQuestion`:

> Note <N>: "<existing text>"
>   [k]eep / [e]dit / [d]elete

On `e`: capture the new text. Validate length ≤ 1024 chars. If longer,
warn and ask whether to truncate or re-enter.

After cycling through existing notes, ask:

> Add a new note? (y/N)
>   When yes, capture text. Repeat until the user says no, or until 10
>   notes total (the guardrail).

If the user tries to add an 11th note:

> Convention notes guardrail is 10. Long-form material belongs in an
> ADR or wiki — link it from a note instead. Skip this addition.

## 3. Toggles

Show current state of each toggle and ask whether to flip:

```
blockedRequiresLink: <current value>
  When ON, /kanban:block refuses calls without --blocked-by KEY.
  This is per-team — don't enable it unless your team has agreed.

  Change? (y/N)
```

## 4. Persist

Build the new conventions JSON and write:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py set-conventions \
  --kanban-path '<kanban.json path>' \
  --conventions-json '<json>'
```

Surface any `warnings[]` from the response (notes too long, etc.).

## 5. Suggest push to Jira

After a successful edit, the local cache is updated but the Jira
project property (`kanban-config`) still has the old conventions.
Remind the user to publish:

```
✓ Conventions updated locally.

To make these rules live for teammates, push to Jira:

  /kanban:push-board-config   (requires Jira project-admin role)

After push, teammates pick up the new conventions automatically on
their next /kanban:sync (within 8h) or immediately via
/kanban:pull-board-config. The ack flow re-fires for everyone because
the conventions hash changed.

If you don't have admin role, ask the project admin to push, or
share the diff via Slack and let them edit + push from their repo.
```

## Absolute rules

- Never invent notes or toggle values — every change comes from the user.
- Never bypass the length guardrails silently — warn and re-prompt.
- Never write conventions on behalf of another repo. The user is the
  source of truth for what their team agreed; other repos receive the
  conventions via `/kanban:pull-board-config` (or passive sync).
