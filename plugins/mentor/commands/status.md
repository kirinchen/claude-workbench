---
description: Show the current mentor mode, active sprint, and open issues.
allowed-tools: Read, Bash(workbench-mentor:*), Bash(export:*)
---

# /mentor:status

## 1. Resolve config

Prepend PATH so `workbench-mentor` is findable without shell rc setup:

```bash
export PATH="$HOME/.claude-workbench/bin:$PATH"
workbench-mentor --health
```

- Exit 0 → continue.
- Non-zero → tell the user to run `/mentor:init` and stop.

## 2. Gather state

```bash
export PATH="$HOME/.claude-workbench/bin:$PATH"
workbench-mentor config --format json
workbench-mentor active-sprint --format json    # development mode only
workbench-mentor review --format json
```

## 3. Render

Basic mode — short report:

```
mentor (basic)
  SPEC: doc/SPEC.md  (exists)
  tasks: kanban.json (n tasks) OR doc/task.md

Compliance: ✓ clean  |  ⚠ N issues
```

Development mode — fuller report:

```
mentor (development)
  SPEC: doc/SPEC.md
  Active sprint: SPRINT-2026-W17
    Goal: "..."
    Ends: 2026-04-27
    Committed issues: 4

  Open issues: 3 of 12
    - ISSUE-042  Rate limit handling         [P1, in_progress]
    - ISSUE-044  Session token refresh       [P2, open]
    - ISSUE-050  Refactor auth middleware    [P1, open]

  Active epics: 2
    - EPIC-001 User authentication system  [active]
    - EPIC-002 Payment integration         [planning]

Compliance: ✓ clean  |  ⚠ N violations (use /mentor:review for details)
```

## Absolute rules

- Read-only. Never modify files.
- Never trace specific task→issue→epic chains here (use `workbench-mentor trace` for that). This is a high-level overview.
