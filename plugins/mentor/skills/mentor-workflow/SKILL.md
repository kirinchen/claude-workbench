---
name: mentor-workflow
description: Use whenever `.claude/mentor.yaml` exists in the project, or when the user mentions epic, sprint, issue, retrospective, ADR, or asks about project workflow / conventions / onboarding / how to start a task. This skill governs the config-driven framework that prescribes what Claude should read, fill, and produce.
---

# Mentor Workflow

You operate alongside `.claude/mentor.yaml`, a project-local config that declares a **framework mode** (basic or development). Mentor is the onboarding consultant — it doesn't enforce code↔doc sync rules; it prescribes *how* you work:

1. What to read first (bootstrap_docs)
2. How to fill each document type (templates)
3. What order to work in (task pickup workflow)
4. Where to record which kind of information (SPEC vs Wiki vs Epic vs Issue)

## 0. Absolute rules

1. **Never self-edit `.claude/mentor.yaml`.** The user owns it. Edits go through `/mentor:init --reset`.
2. **Never skip `bootstrap_docs`.** The SessionStart hook lists them — open them before your first code change in a session. If a listed doc is missing, flag that (it's a config drift, not an excuse to skip).
3. **Never mix document layers.** Epic is **why**; Issue is **what**; Task is **how**. Don't write implementation details in an Epic, don't write strategy in an Issue.
4. **Never modify a document without keeping its frontmatter valid.** Required frontmatter fields per type are in `references/` — always preserve `id`, `status`, and date fields.
5. **Never bypass the template.** Use `/mentor:new <type>` to generate new Epic/Sprint/Issue/ADR. Hand-rolled docs that miss frontmatter will be flagged by `/mentor:review`.
6. **Never fabricate `status` transitions.** Document states (`planning | active | done` for Epic/Sprint; `open | in_progress | resolved | closed` for Issue; `proposed | accepted | deprecated` for ADR) have clear semantics — don't invent intermediates.

## 1. Modes

`.claude/mentor.yaml` has `mode: basic | development`. Your behaviour branches sharply.

### Basic mode
One doc (`doc/SPEC.md`) and a task list (kanban.json OR `doc/task.md`). Session start → read SPEC. Pick a task, execute it, update state, done. **Do NOT introduce Epic/Sprint/Issue concepts** — the user picked basic because they don't want that overhead.

Full behavioural guide: `references/basic-mode-guide.md`.

### Development mode
Full hierarchy: SPEC + Wiki + Epic + Sprint + Issue + Task. Session start → read SPEC + the active Sprint document. Before picking a task, trace: task → Issue → Epic, verify direction, then start. Session end → update Issue status if all its tasks are done; draft retro if Sprint is ending.

Full behavioural guide: `references/development-mode-guide.md`.

## 2. Bootstrap reading order

The SessionStart hook surfaces `bootstrap_docs` + (development mode) the active Sprint as `additionalContext`. Open them in this order:

1. `doc/SPEC.md` — project truth. Read first, cite when you quote invariants.
2. `doc/Sprint/<active>.md` (development only) — this week's goal and committed issues.
3. Any other `bootstrap_docs` entry — background you need.

Do NOT defer reading these until you hit ambiguity. Read before the first code change.

## 3. Picking a task

### Basic mode
1. Read the task list (kanban.json top unfinished, or `doc/task.md` top unchecked).
2. Confirm the description makes sense given SPEC.
3. Start.

### Development mode (`task-pickup-workflow.md` covers this in depth)
1. Identify the task's parent Issue — use `workbench-mentor trace <task-id>` or read the Issue frontmatter.
2. Read the Issue. Understand its Acceptance Criteria.
3. Read the parent Epic's Success Criteria. Does the task fit the Epic's direction?
4. Start only if yes. If the task feels misaligned, **don't silently reinterpret** — surface the conflict to the user first.

## 4. Finishing work

### Basic mode
- Update task state (kanban `/kanban:done` or cross off `doc/task.md`).
- If SPEC was affected, update the relevant section in the same session.

### Development mode
- Update task state.
- If all tasks on the Issue are done → update Issue `status: resolved` + fill the Resolution section.
- If the work introduced a non-trivial decision → write an ADR in `doc/Wiki/architecture-decisions/` via `/mentor:new adr`.
- If the Sprint is ending (check Sprint's `end` date) → draft the Retrospective section in the Sprint doc via `/mentor:sprint-end` (when available in v0.2).

## 5. When to create what

| Situation | Create |
|---|---|
| New major direction or feature-set | Epic (`/mentor:new epic`) |
| Concrete problem / bug / request | Issue (`/mentor:new issue`) |
| Technical decision worth recording | ADR (`/mentor:new adr`) |
| Background knowledge / how-to / reference | Wiki page (hand-written in `doc/Wiki/`) |
| Unit of work to execute | kanban task (`/kanban:*`) — not a mentor doc |

Wrong choices to avoid:
- Don't create an Epic for a bug fix (use Issue)
- Don't create an Issue for a one-line research question (comment on an existing Issue, or ask the user)
- Don't write "why" in an Issue — that's Epic territory. Issue says what to do.

## 6. Integration with siblings

Controlled by `.claude/mentor.yaml` `integration.*`:

- `kanban × mentor` — new Issue may auto-create a kanban task (see config). Never the other direction.
- `memory × mentor` — session-end Stop hook writes Sprint retros + accepted ADRs into memory, if memory is installed and enabled.
- `notify × mentor` — Sprint-end and Epic-done may push, if notify is installed and enabled.

You don't invoke these directly — the hooks and commands handle the fan-out.

## 7. Kanban fallback

Mentor never co-exists with both `kanban.json` and `doc/task.md`. Check `workbench-mentor config --format json`:
- `kanban` CLI on PATH → `kanban.json` is the task store; don't touch `doc/task.md`.
- No kanban → `doc/task.md` is the task store; update with Markdown checkboxes.

## 8. References

- `references/basic-mode-guide.md` — detailed behaviour in basic mode
- `references/development-mode-guide.md` — detailed behaviour in development mode
- `references/task-pickup-workflow.md` — the trace → read → verify → start flow for development mode

The spec in `epic/mentor-plugin-spec.md` at the repo root is the authoritative design document.
