# claude-workbench

A family of Claude Code plugins that turn the CLI into a persistent, event-driven AI workspace. Install one, two, or all three — each plugin is useful on its own, and they reinforce each other when combined.

> **Status**: v0.1.0 (Draft). `kanban` is ready; `notify` and `memory` are stubs pending v0.1.0. See [`SPEC.md`](./SPEC.md) for the full design and [`current_state.md`](./current_state.md) for the live implementation snapshot.

## The three plugins

| Plugin | Solves | Status |
|---|---|---|
| [`kanban`](./plugins/kanban) | Task state persistence + shared human/AI work queue via `kanban.json` | **v0.1.0 ready** |
| [`notify`](./plugins/notify) | Push notifications (Pushover, ntfy, …) when Claude needs your attention | v0.0.1 stub |
| [`memory`](./plugins/memory) | Cross-session RAG memory (SQLite + embeddings, local only) | v0.0.1 stub |
| [`workbench`](./plugins/workbench) | ★ Meta-bundle that installs all three | v0.0.1 stub |

Install individually for progressive adoption, or install the `workbench` bundle once v0.1.0 of all three lands.

## Why

Typical Claude Code usage is session-scoped: open session → give instructions → wait → close. Context evaporates, there is no persistent task queue, no event-driven triggers, no shared state across machines, no accumulated knowledge.

Workbench solves these four pains as three independent plugins that compose:

1. **State persists** — `kanban.json` at the project root is the single source of truth.
2. **Events trigger Claude** — cron / git hooks / webhooks drive headless `claude -p`.
3. **Claude can reach you** — Pushover (et al.) push when decisions are needed.
4. **Knowledge accumulates** — per-project RAG memory, auto-injected on session start.

## Install

```bash
# 1. Start Claude Code in any project
cd my-project
claude

# 2. Add the marketplace
> /plugin marketplace add kirin/claude-workbench

# 3. Install what you need
> /plugin install kanban@claude-workbench       # ready today
> /plugin install notify@claude-workbench       # coming soon
> /plugin install memory@claude-workbench       # coming soon
> /plugin install workbench@claude-workbench    # bundle (when all three ship)
```

## Quickstart — `kanban`

```bash
> /kanban:init --with-examples      # seed kanban.json + schema
> /kanban:status                    # read-only summary
> /kanban:next                      # pick a TODO and move it to DOING
> /kanban:done --note="deployed"    # close the DOING task
```

What Claude will and will not do with `kanban.json`:

**Will**:
- Respect `depends` — never start a task with unresolved dependencies.
- Follow priority order (`meta.priorities`, P0 first by default).
- Append comments on the task rather than guessing when ambiguous.
- Auto-commit kanban transitions as standalone commits.

**Will not**:
- Directly `Edit`/`Write` `kanban.json` (blocked by `kanban-guard.sh`).
- Modify tasks in the `DONE` column.

## Composition (coming in v0.1.0 of notify + memory)

Capability detection (§6.5 in SPEC): each plugin checks for sibling CLIs (`workbench-notify`, `workbench-memory`) and gracefully degrades when they're absent.

| Pair | Effect |
|---|---|
| `kanban × notify` | State transitions trigger push notifications (BLOCKED → high priority). |
| `kanban × memory` | `/kanban:next` queries past sessions for related work; `/kanban:done` saves completion notes. |
| `notify × memory` | Decision prompts carry "last time you chose X". |

## Roadmap

Per [`SPEC.md §13`](./SPEC.md):

- **Phase 0** ✓ — skeleton, marketplace, schema
- **Phase 1** ✓ — `kanban` v0.1.0 (this release)
- **Phase 2** — `notify` v0.1.0 (Pushover)
- **Phase 3** — `kanban × notify` integration
- **Phase 4** — `memory` v0.1.0 (SQLite + embeddings + MCP)
- **Phase 5** — three-way integration
- **Phase 6** — `workbench` bundle release

## File layout

```
claude-workbench/
├── SPEC.md                             # design doc (workbench family)
├── current_state.md                    # implementation snapshot
├── .claude-plugin/marketplace.json     # 4 plugin entries
├── plugins/
│   ├── kanban/                         # v0.1.0 (ready)
│   ├── notify/                         # v0.0.1 (stub)
│   ├── memory/                         # v0.0.1 (stub)
│   └── workbench/                      # v0.0.1 (meta stub)
└── schema/kanban.schema.json           # canonical schema
```

## Uninstall

```bash
> /plugin uninstall kanban@claude-workbench
> /plugin marketplace remove claude-workbench
```

Your `kanban.json` and `kanban.schema.json` remain untouched.

## License

MIT — see [`LICENSE`](./LICENSE) (to be added).

## Further reading

- [`SPEC.md`](./SPEC.md) — full spec
- [`current_state.md`](./current_state.md) — implementation snapshot
- [Claude Code plugins docs](https://code.claude.com/docs/en/plugins)
- [Claude Code hooks reference](https://code.claude.com/docs/en/hooks)
- [Model Context Protocol](https://modelcontextprotocol.io)
