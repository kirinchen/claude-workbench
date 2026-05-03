---
description: Surface Jira cards that are invisible to the canonical kanban view (unmapped statuses, missing AP).
allowed-tools: Read, Bash(python3:*)
---

# /kanban:reconcile

Read-only diagnostic. Finds cards that are present in Jira but invisible
to `/kanban:status` / `/kanban:doing` / `cmd_sync_summary` because they
don't satisfy the AP + status filter the plugin uses.

Two checks:

1. **Unmapped status** — card belongs to this AP but its Jira status
   isn't mapped by the DSL. Cause: workflow has more statuses than
   `/kanban:initjira` step 3 mapped, and a card has drifted (manually
   moved, automation rule, mistake) into an unmapped one.
2. **Missing AP** — open card in the project with no AP custom field
   set. Cause: manual creation in Jira UI, an old import that pre-dates
   0.3.8, broken `/kanban:initjira` step 5, etc. Such cards never
   appear in `/kanban:doing` regardless of their status.

`/kanban:sync` (auto on `SessionStart`) already prints a one-line drift
reminder when this command would surface anything. This command is the
deep dive.

## 0. Pre-flight

- `kanban.json#backend.driver == "jira"` — local-mode has no concept of
  unmapped Jira statuses; tell the user this is jira-only.

## 1. Run the helper

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py reconcile \
  --kanban-path '<kanban.json path>'
```

Returns `{ok, projectKey, ap, unmapped, missingAp, totalUnmapped, totalMissingAp, errors, hint}`.

## 2. Render

If both `totalUnmapped == 0` AND `totalMissingAp == 0`:

```
✓ All cards visible to the canonical kanban view. No drift detected.
```

Otherwise render two sections (skip the section if its count is zero):

```
[unmapped statuses — N card(s) across M status(es)]
  TO PROGRESS:
    BZK-614  BZK-617
  Backlog:
    BZK-700

[missing AP — N card(s) with no AP set, invisible to /kanban:doing]
  BZK-820  BZK-821  ...

Suggested next steps:
  • For unmapped statuses: re-run /kanban:initjira (step 3) and add DSL
    lines mapping `TO PROGRESS` and `Backlog` to canonical columns —
    OR move the cards back to a mapped status in the Jira UI.
  • For missing AP: claim them via /kanban:doing (per repo) or set the
    AP field directly in Jira UI for cards owned by other agents.
```

If `errors[]` is non-empty, list them after the sections — these are
network / permission failures from the diagnostic queries themselves
(distinct from "no drift found").

## Absolute rules

- Read-only. **Never** transition cards or modify the AP field. The
  user decides what to do based on the report.
- Never invent a fix path. If unmapped statuses look like genuine new
  workflow stages the team has adopted, the right fix is to re-run
  `/kanban:initjira` and extend the DSL — not to silently remap.
- Pair-mode reminder: this command is the **diagnostic**, not the
  remediation. Keep them separate.
