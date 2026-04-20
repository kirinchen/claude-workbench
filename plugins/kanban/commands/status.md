---
description: Show a summary of the current kanban state.
allowed-tools: Read
---

# /kanban:status

Print a concise snapshot of `kanban.json`. Read-only — do not write anything.

## 1. Load

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
Kanban status (kanban.json · schema v1)

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

## Absolute rules

- Do NOT write to `kanban.json`.
- Do NOT launch tasks — this is read-only.
- If the file fails schema validation, say so explicitly and point at the offending field.
