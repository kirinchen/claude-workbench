---
description: Show a summary of the current kanban state.
allowed-tools: Read
---

# /kanban:status

Print a concise snapshot of `kanban.json`. Read-only — do not write anything.

## 0. Driver check

Read `kanban.json`. Look at `backend.driver`.
- Absent or `"local"`: continue with the local flow below (steps 1–3).
- `"jira"`: skip steps 1–3 and use the Jira flow (step 4).

## 1. Load (local driver)

Read `kanban.json` at the project root. If missing, tell the user to run `/kanban:init`.

## 2. Compute

- Count tasks per column.
- Current DOING tasks (id, title, priority, assignee, started).
- Top 3 TODO candidates (ready: deps all DONE), ranked by priority then created.
- BLOCKED tasks with their `custom.blocked_reason`.
- Any TODO task whose `depends` reference a non-existent id (data integrity issue).

## 3. Render

Format (keep it tight — monospace-friendly):

```
Kanban status (kanban.json · v0.2 · local)

Columns: TODO 7 · DOING 1 · DONE 12 · BLOCKED 2

DOING:
  task-042  [P1 trading]  重寫 grid pricing dynamic classifier
            started 2026-04-20T09:12:00+08:00 (claude-code)

Next up (ready):
  task-045  [P0 infra]    Wire CI pipeline
  task-043  [P1 trading]  Add unit tests for classifier
  task-050  [P2 docs]     Document kanban workflow

BLOCKED:
  task-004  [P1 bug]      Investigate flaky test on macOS
            reason: Need access to macOS runner logs.

(No integrity issues.)
```

If counts are zero or a section is empty, omit it rather than printing `(empty)`.

## 4. Jira flow (when backend.driver == "jira")

Use the helper to read live state without going through Edit/Write:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py health \
  --kanban-path '<kanban.json path>'
```

If health is not `ok` (especially `unauthenticated`), surface the detail and
suggest `/kanban:reset-credentials`. Stop.

Otherwise pull two lists for the snapshot:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py list-tasks \
  --kanban-path '<kanban.json path>' --column DOING --limit 20
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py list-tasks \
  --kanban-path '<kanban.json path>' --column BLOCKED --limit 20
```

Render in the same compact format as the local flow:

```
Kanban status (Jira · project=<KEY> · board #<id>)

DOING:
  <KEY>-12  [P1]  <summary>  (assignee=<displayName>, ap=<ap or "—">)

BLOCKED:
  <KEY>-9   [P2]  <summary>  (raw status: <jira status>)
```

If `partial` mode is in effect (read from `backend.jira.partial`), append a
one-line note: `Workflow: partial — REVIEW/BLOCKED/CANCELLED collapse via labels`.

## Absolute rules

- Do NOT write to `kanban.json`.
- Do NOT launch tasks — this is read-only.
- If the file fails schema validation, say so explicitly and point at the offending field.
