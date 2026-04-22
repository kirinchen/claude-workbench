# Basic mode — behavioural guide

Basic mode is deliberately minimal. It answers three questions: where's the truth, what's next, and did anything in the truth just change?

## When basic mode is right

- Solo project, one person making decisions
- Prototype or throwaway experiment
- Maintenance-mode project (no planning cycles, just tickets as they come)
- Tool / library with a narrow remit

If you find yourself wanting to separate "why" from "what" routinely, you've outgrown basic — suggest upgrading to development.

## Files

```
<project>/
├── doc/
│   └── SPEC.md          ← the one source of truth
├── kanban.json          ← (if kanban plugin installed)
└── doc/task.md          ← (otherwise)
```

Exactly one of `kanban.json` / `doc/task.md` exists. Never both.

## Agent behaviour per lifecycle phase

### Session start
1. Read `doc/SPEC.md` before any code change. The SessionStart hook reminds you — don't ignore the reminder.
2. Check the task list (kanban top unfinished or `doc/task.md` top unchecked).

### Picking a task
1. Read the task description.
2. Cross-reference against SPEC if the description touches something the SPEC promised.
3. Start.

Nothing fancier. There is no Issue, no Epic — the task description and the SPEC together are the whole context.

### During execution
1. If the work affects SPEC (a new invariant, a changed behaviour, a renamed concept), update SPEC **in the same session** as the code change.
2. Don't write a status report inside SPEC. SPEC describes the current system, not recent changes.

### Ending a task
1. Update task state (kanban or `doc/task.md`).
2. Commit. (Kanban handles its own commits.)

### Session end
The Stop hook summarises which documents were touched. If anything's weird, it surfaces. Otherwise silent.

## What basic mode does NOT have

- **No Epic / Sprint / Issue documents.** Don't create them. If you feel you need to structure work that way, tell the user to `/mentor:init --reset` and pick development.
- **No ADRs.** Technical decisions go into SPEC prose (or git commit messages, for narrower choices).
- **No acceptance criteria formalism.** Tasks have a description; that's the criterion.
- **No retrospectives.** This is maintenance-mode.

## `task.md` format (when kanban isn't installed)

Plain Markdown checklist:

```markdown
# Tasks

## Active

- [ ] task-003  Implement token bucket rate limiter
- [ ] task-004  Add unit tests for bucket

## Done

- [x] task-001  Stand up CI
- [x] task-002  Deploy to staging
```

New tasks go under "Active". Finishing a task moves its line from "Active" to "Done" with `[x]`. No state between open and done.

## Why this restraint matters

The mentor plugin's earlier draft (docsync) tried to solve per-project rule sets. It overflowed into prescribing things people didn't need. Basic mode is the antidote: less structure, less ceremony, same "what's the truth" discipline. Respect it — adding ceremony where the user chose not to have it is the opposite of helpful.
