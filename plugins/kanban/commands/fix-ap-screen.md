---
description: Attach the AP custom field to project screens so issues can carry its value (recovers from issue #6).
allowed-tools: Read, Bash(python3:*)
---

# /kanban:fix-ap-screen

Recover from the issue #6 failure mode where the AP custom field was
created (e.g. by an older `/kanban:initjira` on 0.3.1) but never
associated with any Jira screen. Symptom: `/kanban:next` returns nothing
even though there are TODO cards, because `customfield_X cannot be set`
on any issue, so no card carries an AP value.

This command:

1. Finds candidate screens (project-scoped + global default).
2. Attaches `backend.jira.ap.fieldId` to each screen's first tab.
3. Reports per-screen result so the user knows what worked, what was
   already in place, and where admin permission was missing.

It is also safe to run on a healthy install — adding a field to a screen
that already has it is a no-op.

## 0. Pre-flight

- Confirm `kanban.json#backend.driver == "jira"`. Otherwise stop.
- Confirm `backend.jira.ap.fieldId` exists. If not, the user needs
  `/kanban:initjira` first.

## 1. Verify current state

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py verify-ap-field-screens \
  --kanban-path '<kanban.json path>'
```

Returns `{ok, fieldId, present: [...], missing: [...]}`.

If `missing` is empty, print:

```
✓ AP field is already attached to all candidate screens. Nothing to do.
```

…and stop.

Otherwise, list the missing screens before doing anything mutating:

```
AP field "<fieldName>" (<fieldId>) is missing from:
  • <screen-1>
  • <screen-2>

Attach now? (y/N)
```

## 2. Associate

If the user accepts:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py associate-ap-field-screens \
  --kanban-path '<kanban.json path>'
```

Returns `{ok: true, fieldId, screens: {attempted, attached, denied, errors}}`.

Render:

```
Screen association summary:
  ✓ Attached to <N> screen(s):
      • <name> (id=<id>)         (or "(already present)")
  ⚠ Denied (admin permission needed):
      • <name> (id=<id>)
  ✗ Errors:
      • <name> — <detail>
```

If `denied` is non-empty, suggest:

> Ask a Jira global admin to add `<fieldName>` to:
>   <list of denied screen names>
> via Project Settings → Screens → <screen> → "Add field".

## 3. Verify after fix

Re-run step 1's `verify-ap-field-screens`. Confirm `missing` shrank or is
now empty.

## Absolute rules

- Read `backend.jira.ap.fieldId` and `projectKey` from `kanban.json` —
  never accept them via CLI args (avoids accidental writes against the
  wrong field).
- Do not retry on 403 — surface as `denied` and let the user route to admin.
- Do not write to `kanban.json` (this command is purely Jira-side).
