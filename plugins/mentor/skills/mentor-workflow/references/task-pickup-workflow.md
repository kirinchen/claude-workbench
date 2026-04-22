# Task pickup workflow (development mode)

How to start a task without stepping on wrong intent. Follow this every time in development mode — it takes less than a minute.

## The flow

```
task-042 chosen
    │
    ▼
┌───────────────────────────┐
│ 1. Trace task → Issue     │  workbench-mentor trace task-042
└────────────┬──────────────┘
             │  orphan → stop, ask user
             ▼
┌───────────────────────────┐
│ 2. Read the Issue fully   │  Issue/ISSUE-042.md
│    — Acceptance Criteria  │
│    — Investigation notes  │
│    — Existing comments    │
└────────────┬──────────────┘
             │
             ▼
┌───────────────────────────┐
│ 3. Read the Epic          │  Epic/EPIC-001.md
│    — Why                  │
│    — Success Criteria     │
│    — Out of Scope         │
└────────────┬──────────────┘
             │  misaligned → stop, ask user
             ▼
┌───────────────────────────┐
│ 4. Check the Sprint       │  Is this task in the active Sprint?
└────────────┬──────────────┘
             │  no → stop, ask whether this is priority-worthy
             ▼
┌───────────────────────────┐
│ 5. Look for past context  │  Optional: workbench-memory search ...
└────────────┬──────────────┘
             │
             ▼
      Start the task
```

## Step-by-step details

### 1. Trace

```bash
workbench-mentor trace task-042 --format json
```

Returns:
```json
{
  "task_id": "task-042",
  "issue": {"id": "ISSUE-017", "path": "doc/Issue/ISSUE-017.md", "status": "open", "title": "..."},
  "epic":  {"id": "EPIC-003", "path": "doc/Epic/EPIC-003.md", "status": "active", "title": "..."},
  "sprint": {"id": "2026-W17", "path": "doc/Sprint/SPRINT-2026-W17.md"}
}
```

Possible bad states:
- `issue: null` → **orphan task**. Stop. The task exists in kanban but no Issue references it. Ask the user: did they mean to add this task directly? Should it be attached to an Issue first?
- `issue.status: closed` or `resolved` → **stale task**. The Issue is done but the task wasn't crossed off. Flag it, ask.
- `epic: null` → **orphan issue**. The Issue references an Epic that doesn't exist. Flag it.
- `epic.status: done` or `cancelled` → the Epic is over. Ask why this task still matters.

### 2. Read the Issue

Open `Issue/<id>.md`. Key sections:

- **Problem** — quick context check
- **Acceptance Criteria** — **this is the real spec for your work**. If a criterion is unchecked and the task description doesn't address it, something's off.
- **Investigation / Notes** — past exploration. Might save you hours. Read it.
- **Resolution** — if present and non-empty, the Issue may already be done. Stop and verify.

### 3. Read the Epic

Open `Epic/<id>.md`. Key sections:

- **Why** — is this still true?
- **Success Criteria** — what "done" looks like for the whole Epic
- **Out of Scope** — things explicitly NOT being done. If your task drifts into this list, stop.

### 4. Check the Sprint

Is the task's Issue listed in the active Sprint's `Committed Issues`?
- Yes → green light
- No → the task is out-of-band work. Ask the user:
  - Is this more important than what's in the Sprint?
  - Should it be added to the Sprint (bumping something else)?
  - Or does it belong in backlog?

Don't just silently do out-of-sprint work — that's how Sprints stop meaning anything.

### 5. (Optional) Memory recall

If memory plugin is installed:
```bash
workbench-memory search --query "<issue title keywords>" --limit 3
```

Surface past decisions that touch the same area. Highlight them to the user before you start: "Found past memory: 2025-12 we chose token bucket for similar work."

### 6. Start

Once the chain checks out:
1. `/kanban:next` to formally transition task to DOING (if it wasn't already)
2. Append an Issue note: `2026-04-23: Started work on this.`
3. Work.

## When to STOP and ask

Summary of all stop conditions:

| Signal | Reason | Action |
|---|---|---|
| trace returns `issue: null` | Orphan task | Ask: attach to existing Issue, or create new one? |
| Issue `status: closed/resolved` | Stale task | Ask whether to reopen or close the task |
| Epic `status: done/cancelled` | Direction over | Ask why this still matters |
| Task not in active Sprint | Out-of-band | Ask about priority vs Sprint commitment |
| Task description conflicts with Issue Acceptance Criteria | Ambiguity | Ask which is authoritative; don't silently pick |
| Epic Out-of-Scope lists something the task touches | Scope creep | Ask whether to revise the Epic or narrow the task |

## Performance note

This whole flow is cheap. All files are small Markdown with YAML frontmatter; the CLI call is sub-second. Don't skip it to save time — the cost of one hour of wrong-direction work dwarfs the cost of 30 seconds of tracing.
