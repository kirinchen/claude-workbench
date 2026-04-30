---
description: Author or edit the team's `conventions` block — narrative notes + per-team toggles.
allowed-tools: Read, Bash(python3:*), AskUserQuestion
---

# /kanban:edit-conventions

Interactive editor for `backend.jira.conventions`. Use this on the team's
**source-of-truth repo** (the one whose `/kanban:showjira-code` other
machines paste from). After editing, regenerate the share code so
teammates see the new rules on their next import.

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

On `e`: capture the new text. Validate length ≤ 200 chars. If longer,
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

## 5. Suggest re-share

After a successful edit, remind the user:

```
✓ Conventions updated.

Teammates on other repos / machines will see the new rules the next
time they re-import. To push the update now:

  1. Run /kanban:showjira-code in this repo
  2. Share the printed JSON with your team
  3. Each teammate runs /kanban:initjira-by-code on their repo and
     pastes the new code (the ack flow re-fires because the hash changed)
```

## Absolute rules

- Never invent notes or toggle values — every change comes from the user.
- Never bypass the length guardrails silently — warn and re-prompt.
- Never write conventions on behalf of another repo. The source-of-truth
  is wherever the user is running this command. Other repos pull via
  `/kanban:initjira-by-code`.
