# Development mode — behavioural guide

Development mode is for projects that plan ahead. Multiple features in parallel, explicit time windows, and a multi-layer document hierarchy that separates *why* (Epic), *what* (Issue), *how* (Task), *decisions* (ADR), and *background* (Wiki).

## When development mode is right

- Multi-feature parallel work
- Meaningful planning cadence (weekly / biweekly sprints)
- Multi-agent or multi-human collaboration
- Mid-to-large project where the cost of losing context > the cost of writing docs

## The document hierarchy

```
SPEC         — what the system is (stable, slowly changing)
  └─ Wiki    — background, decisions, how-tos
       └─ architecture-decisions/  — ADRs, one decision per file

Epic         — long-lived goal; answers "why"
  └─ Issue   — concrete problem/feature; answers "what"
       └─ Task  — unit of execution (kanban.json or task.md)

Sprint       — time window; contains committed Issues
```

Each layer has required frontmatter (see `epic/mentor-plugin-spec.md`):

| Type | Required frontmatter |
|---|---|
| Epic | `id, title, status, owner, created, issues` |
| Sprint | `id, start, end, goal, issues, status` |
| Issue | `id, title, epic, sprint, status, priority, tasks` |
| ADR | `id, title, status, date, deciders, related_issues` |

`mentor-guard.py` will warn when you edit a file with missing frontmatter. `workbench-mentor review` exit-2's on drift.

## Agent behaviour per lifecycle phase

### Session start
1. Read `doc/SPEC.md`.
2. Read the active Sprint document (the one with `status: active`). The SessionStart hook surfaces it. If there are multiple, that's a config bug — flag it.
3. Skim the Sprint's `Committed Issues` list. Get a feel for what's in play.

Don't start picking tasks before these three reads complete.

### Picking a task (the important part)

See `task-pickup-workflow.md` for the step-by-step. Summary:
1. `workbench-mentor trace <task-id>` — find the Issue, then the Epic.
2. Read the Issue's `Acceptance Criteria`. **These are the real success conditions**, not the task description.
3. Read the Epic's `Success Criteria` and `Out of Scope`. Is the task still aligned?
4. Only then start.

If trace returns no Issue → the task is orphan. **Stop and ask** — don't execute orphan tasks.

### During execution

1. Update the Issue's "Investigation / Notes" section as you learn things. Future you (or another agent) will re-read this.
2. If the work forces a non-trivial decision (a library choice, an algorithm change, a timing/concurrency choice), write an ADR via `/mentor:new adr` **at the moment you make the decision**, not at the end. That way the next person has the reasoning.
3. If SPEC was affected, update SPEC in the same session. Same rule as basic mode.

### Ending a task

1. Update task state in kanban (`/kanban:done`) or `doc/task.md`.
2. Re-read the Issue. If all its tasks are DONE:
   - Update Issue `status: resolved`
   - Fill the Resolution section
3. If the Issue's Acceptance Criteria turned out to be wrong or incomplete, edit them — but explain in the commit message why.

### Ending a sprint

Usually triggered by `/mentor:sprint-end` (v0.2 — for v0.1.0, do it manually):
1. Update Sprint `status: review` then `status: done`.
2. Write the Retrospective section (What went well / What could be improved / Action items).
3. If `integration.memory.save_sprint_retro` is on, the Stop hook persists this to memory automatically.

## Wiki vs ADR — when to use which

**Wiki** — reference material.
- Setup guides, architecture overviews, glossary, onboarding docs.
- Evergreen. Updated as the system changes.
- Example: `Wiki/guides/local-dev-setup.md`.

**ADR** — a decision.
- One choice, one file.
- Immutable once `status: accepted`. Superseded via a new ADR that references the old one.
- Example: `Wiki/architecture-decisions/ADR-007-postgres-over-mysql.md`.

Rule of thumb: if someone in 6 months will ask "why did we do X?", that's an ADR. If they'll ask "how do I X?", that's a Wiki page.

## Boundaries — what NOT to put where

- **Don't put "why" in an Issue.** Issue = what to do. Why goes in the parent Epic.
- **Don't put "how" in an Issue.** Issue = acceptance criteria. Implementation goes in the Task and code.
- **Don't put strategy in an ADR.** ADR = one narrow decision. Strategy goes in Epic or SPEC.
- **Don't put unresolved questions in SPEC.** SPEC = what IS. Unresolved → Wiki or an Issue.

## Compliance is a lightweight discipline

The framework is scaffolding, not law. If you feel it's getting in the way:
1. First check: are you trying to do development-mode work without having filled in the Issue?
2. Then: is the Issue acceptance criteria too narrow? Revise it first.
3. Only then: if the framework itself feels wrong, tell the user — maybe basic mode is a better fit.

The goal isn't to fill forms. It's to make "what are we doing and why" obvious six months later.
