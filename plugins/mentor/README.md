# mentor

Part of the [claude-workbench](../../README.md) family — **dev profile**. See [`epic/mentor-plugin-spec.md`](../../epic/mentor-plugin-spec.md) for the full design.

**Mentor is the onboarding consultant your project never had.** It tells Claude (and any human contributor) *what to read first*, *what templates to fill*, *what order to work in*, and *where to record decisions*. Install it and your repo acquires a working discipline, not just a doc folder.

Replaces the earlier `docsync` plugin — broader scope, framework-driven.

## Two modes, pick one

Run `/mentor:init` and choose:

| Mode | Good for | Doc hierarchy |
|---|---|---|
| **basic** | Personal projects, prototypes, tools, maintenance mode | `doc/SPEC.md` + tasks |
| **development** | Multi-feature, planning cycles, multi-agent collab | `SPEC + Wiki + Epic + Sprint + Issue` + tasks |

Basic is deliberately minimal — upgrade to `development` later when planning pressure shows up.

## Install

```
> /plugin install mentor@claude-workbench
> /mentor:init            # interactive — scan, pick mode, generate structure
```

## Slash commands (v0.1.0 MVP)

| Command | Purpose |
|---|---|
| `/mentor:init` | Interactive mode selection + structure generation |
| `/mentor:status` | Current mode, active sprint, open issues |
| `/mentor:new` `<epic\|sprint\|issue\|adr>` | Generate a new document from the mode's template |
| `/mentor:review` | Compliance check — missing docs, orphan issues, template drift |
| `/mentor:migrate-from-docsync` | Read `.claude/docsync.yaml` → write `.claude/mentor.yaml` |

Deferred to v0.2: `/mentor:sprint-start`, `/mentor:sprint-end` (sprint lifecycle with auto-retro).

## Hooks

- **SessionStart** — inject bootstrap docs + active-sprint pointer as `additionalContext`.
- **PreToolUse** (Edit/Write/MultiEdit) — warn on documents missing frontmatter or violating template shape.
- **Stop** — session-end compliance summary.

## CLI

`workbench-mentor` — stable integration surface for sibling plugins:

```bash
workbench-mentor --health
workbench-mentor config --format json
workbench-mentor active-sprint --format json
workbench-mentor trace task-042 --format json       # task → issue → epic
workbench-mentor review --format json               # exit 0 clean, 2 on violations
```

## Kanban fallback

- Kanban installed → `kanban.json` owns task state; mentor reads `tasks: [...]` in Issue frontmatter to trace
- Kanban not installed → mentor writes `doc/task.md` as minimal task list

They never coexist.

## Sibling integration

All opt-in via `.claude/mentor.yaml`:

- **mentor × kanban** — new Issue auto-creates kanban task entry; optional DONE gate on Acceptance Criteria
- **mentor × memory** — sprint retros + ADRs saved as memory entries
- **mentor × notify** — sprint-end / epic-done push notifications

## File layout

```
plugins/mentor/
├── .claude-plugin/plugin.json
├── skills/mentor-workflow/
│   ├── SKILL.md
│   └── references/
│       ├── basic-mode-guide.md
│       ├── development-mode-guide.md
│       └── task-pickup-workflow.md
├── commands/{init,status,new,review,migrate-from-docsync}.md
├── hooks/hooks.json
├── scripts/
│   ├── framework_engine.py        # config loader + mode resolution
│   ├── mentor-bootstrap.py        # SessionStart
│   ├── mentor-guard.py            # PreToolUse
│   ├── mentor-finalcheck.py       # Stop
│   ├── workbench-mentor.py        # CLI
│   ├── workbench-mentor           # bash shim
│   └── install-cli.sh
├── frameworks/
│   ├── basic/     — framework.yaml + SPEC template
│   └── development/ — framework.yaml + SPEC/Wiki/Epic/Sprint/Issue/ADR templates
└── templates/mentor.example.yaml
```
