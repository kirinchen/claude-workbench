# claude-kanban

Kanban-driven workflow for Claude Code. Manage a project's task lifecycle through a single `kanban.json` file that both humans and AI can read and write.

> **Status**: v0.1.0 (Draft MVP) — plugin + schema only. Viewer and automation components land in later milestones. See [`SPEC.md`](./SPEC.md) for the full design.

## Why

Traditional Claude Code usage is session-scoped: open session → give instructions → wait → close. Context evaporates. There is no persistent task queue, no event-driven triggers, no shared state across machines.

`claude-kanban` treats **`kanban.json` as the single source of truth**. Humans edit it via an editor or viewer; Claude edits it via `/kanban:*` commands. Everyone stays in sync, tasks persist across sessions, and state is observable from any tool that can read JSON.

## Components

| Component | Users | Status |
|---|---|---|
| **Plugin** (`plugins/kanban/`) | Claude Code (AI) | v0.1.0 ✓ |
| **Viewer** (`viewer/`) | Humans | v0.2.0 (planned) |
| **Automation** (`automation/`) | Cron / git hooks / webhooks | v0.2.0 (planned) |

Each component is independent — install only what you need.

## Install (3 steps)

Inside any existing project:

```bash
# 1. Start Claude Code in your project
cd my-project
claude

# 2. Add the marketplace + install the plugin
> /plugin marketplace add kirin/claude-kanban
> /plugin install kanban@claude-kanban

# 3. Initialise kanban.json
> /kanban:init                 # empty board
# or
> /kanban:init --with-examples # seeded with a few example tasks
```

Two files appear in your project root:

- `kanban.json` — your task board (commit this)
- `kanban.schema.json` — JSON Schema for editor autocomplete (commit this)

## Daily use

| Command | What it does |
|---|---|
| `/kanban:status` | Show a summary (read-only) |
| `/kanban:next` | Pick the next eligible TODO task and move it to DOING |
| `/kanban:done` | Close the current DOING task |
| `/kanban:init` | Scaffold kanban.json (first-time only) |

Common flags:

```
/kanban:next --category=trading --priority=P1
/kanban:done task-042 --note="deployed to prod"
```

## What Claude will and will not do

**Will**:
- Read `kanban.json` when asked about tasks.
- Respect `depends` — never start a task with unresolved dependencies.
- Follow priority order (`meta.priorities`, P0 first by default).
- Append comments on the task instead of guessing when requirements are ambiguous.
- Auto-commit kanban.json changes as standalone commits.

**Will not**:
- Directly `Edit`/`Write` `kanban.json` (blocked by `kanban-guard.sh`).
- Modify tasks in the `DONE` column.
- Silently skip dependencies or reprioritise without asking.

## File layout

```
claude-kanban/
├── SPEC.md                            # full design doc
├── .claude-plugin/marketplace.json    # Claude Code marketplace entry
├── plugins/kanban/                    # the plugin itself
│   ├── .claude-plugin/plugin.json
│   ├── skills/kanban-workflow/        # skill + references
│   ├── commands/                      # /kanban:init, :next, :done, :status
│   ├── hooks/hooks.json
│   ├── scripts/                       # kanban-guard.sh, kanban-autocommit.sh
│   └── templates/                     # kanban.empty.json, kanban.example.json, kanban.schema.json
└── schema/kanban.schema.json          # canonical schema (synced to plugin/templates/)
```

## Uninstall

```bash
> /plugin uninstall kanban@claude-kanban
> /plugin marketplace remove claude-kanban
```

Your `kanban.json` and `kanban.schema.json` remain untouched.

## License

MIT — see [`LICENSE`](./LICENSE) (to be added).

## Further reading

- [`SPEC.md`](./SPEC.md) — complete specification
- [Claude Code plugins docs](https://code.claude.com/docs/en/plugins)
- [Claude Code hooks reference](https://code.claude.com/docs/en/hooks)
