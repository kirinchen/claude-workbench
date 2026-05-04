---
description: Work the DOING pool — read every card you currently own (status=DOING) and execute them in a sensible order.
allowed-tools: Read, Bash(python3:*), Bash(date:*)
---

# /kanban:doing

Work through every card the owner has placed in `DOING` for this AP.
The Skill `kanban-workflow` (loaded automatically) governs the rules.

This command is **read-then-execute**, not pick-from-TODO. The state
machine the plugin enforces:

```
TODO  ──(owner moves)──▶  DOING  ──(/kanban:doing executes)──▶  APPROVED
                            │                                    ▲
                            └──(/kanban:block REVIEW)──▶ REVIEW ──┘
                                                          │
                                                          └──(owner moves back)──▶  DOING
```

- **TODO → DOING** is the **owner's** call (Jira UI, or whatever
  intake flow the team uses). The agent must never pull a card from
  TODO into DOING — that's curation, not execution.
- **DOING → APPROVED** is yours, after executing successfully.
- **DOING → REVIEW** is yours when blocked / needs owner judgement.
- **REVIEW → DOING** is the owner's ("keep going") or **REVIEW →
  APPROVED** ("good enough").

## 0. Pre-flight

- Read `kanban.json#backend.driver`. Local-mode does not have AP
  routing; this command is jira-only — tell the user to use
  `/kanban:next` if they're in local mode (still works there).
- `$CLAUDE_PROJECT_DIR` (or `git rev-parse --show-toplevel`) → kanban
  path.

## 1. Fetch the DOING set

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py list-doing \
  --kanban-path '<kanban.json path>'
```

Returns `{ok, ap, doing: [{id, title, priority, started, ap}, ...]}`.

| Shape | Action |
|---|---|
| `{ok: true, doing: [...]}` (non-empty) | proceed to step 2 |
| `{ok: true, doing: []}` | print `No DOING cards for AP <ap>; owner needs to move a TODO into DOING (Jira UI or ask the owner).` Stop. Do **not** auto-pick from TODO. |
| `{ok: false, error}` | surface the error verbatim. If it mentions `kanban-agent.json`, suggest `/kanban:assign-ap`. |

## 2. Decide execution order

When `doing` has more than one card, read each card's title +
description (via `/kanban:show <id>` or whatever you need) and decide
the order based on:

- explicit `Blocks`/`is-blocked-by` issue links — predecessors first
- shared module / file affinity — batch cards that touch the same code
- priority field as a tie-breaker (P0 > P1 > ...)

Print the chosen order in one line, e.g.:

```
DOING (3): BZK-625 → BZK-626 → BZK-627 (linked chain; same module)
```

## 3. Execute one at a time

Work the cards sequentially — actively executing one at a time
(WIP=1). For the active card:

- Read its full description and any prior comments (`/kanban:show`).
- Make the changes the description calls for.
- When done: `/kanban:done <id>` (or whatever your team calls the
  DOING → APPROVED move).
- When stuck and need owner input: `/kanban:block <id> --to REVIEW
  --reason "..."`.

After finishing one card, self-loop into the next without requiring
the user to re-invoke `/kanban:doing`.

## Absolute rules

- **Never** transition a card from TODO into DOING. That belongs to
  the owner. If the owner asks you to "start working on BZK-NN",
  ask them to move it to DOING first — or document an explicit
  per-team agreement (in `conventions.notes` via
  `/kanban:edit-conventions`) that authorizes the agent to pull.
- **Never** decide what's "important enough" to start. Priority
  curation is the owner's responsibility; the agent's job is to
  execute what's already curated.
- Read-then-execute. This command itself does not transition any
  cards — `/kanban:done` and `/kanban:block` do.
