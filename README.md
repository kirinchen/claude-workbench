# claude-workbench

*[繁體中文](./README_zhtw.md)*

A family of Claude Code plugins that turn the CLI into a persistent, event-driven AI workspace. Install one, two, or all of them — each plugin is useful on its own, and they reinforce each other when combined.

> **Status**: v0.1.0 (Draft). `kanban`, `notify`, and `docsync` are shipped; `memory` is the remaining core stub. See [`SPEC.md`](./SPEC.md) for the full design and [`current_state.md`](./current_state.md) for the live implementation snapshot.
>
> **Quickstarts**: [`kanban`](./kanban_quickstart.md) · [`notify`](./notify_quickstart.md) · [`docsync`](./docsync_quickstart.md)

## Plugins

| Plugin | Profile | Solves | Status |
|---|---|---|---|
| [`kanban`](./plugins/kanban) | core | Task state persistence + shared human/AI work queue via `kanban.json` | **v0.1.0 ready** |
| [`notify`](./plugins/notify) | core | Push notifications (Pushover) when Claude needs your attention | **v0.1.0 ready** |
| [`memory`](./plugins/memory) | core | Cross-session RAG memory (SQLite + embeddings, local only) | v0.0.1 stub |
| [`docsync`](./plugins/docsync) | dev | Code ↔ documentation drift prevention via `.claude/docsync.yaml` | **v0.1.0 ready** |
| [`workbench`](./plugins/workbench) | — | ★ Core bundle (kanban + notify + memory) | meta, stub |
| [`workbench-dev`](./plugins/workbench-dev) | — | ★ Dev bundle (workbench + docsync) | meta, stub |

Install individually for progressive adoption, or install the meta-bundles once `memory` v0.1.0 also lands.

## Why

Typical Claude Code usage is session-scoped: open session → give instructions → wait → close. Context evaporates, there is no persistent task queue, no event-driven triggers, no shared state across machines, no accumulated knowledge.

Workbench solves these four pains as three independent plugins that compose:

1. **State persists** — `kanban.json` at the project root is the single source of truth.
2. **Events trigger Claude** — cron / git hooks / webhooks drive headless `claude -p`.
3. **Claude can reach you** — Pushover (et al.) push when decisions are needed.
4. **Knowledge accumulates** — per-project RAG memory, auto-injected on session start.

## Install

```bash
# 0. On your shell rc (~/.bashrc / ~/.zshrc) — required so sibling plugins
#    can discover each other's CLIs (workbench-notify, workbench-docsync, ...).
export PATH="$HOME/.claude-workbench/bin:$PATH"

# 1. Start Claude Code in any project
cd my-project
claude

# 2. Add the marketplace (public repo; use the SSH URL for private)
> /plugin marketplace add kirinchen/claude-workbench

# 3. Install what you need
> /plugin install kanban@claude-workbench       # ready
> /plugin install notify@claude-workbench       # ready (Pushover)
> /plugin install docsync@claude-workbench      # ready (dev profile)
> /plugin install memory@claude-workbench       # coming soon
> /plugin install workbench@claude-workbench    # bundle (when memory ships)
```

Then jump into the quickstart for each plugin you installed — see the links at the top of this file.

### Two identifiers, one letter apart

The install flow uses two separate names that happen to look similar. Getting them mixed up is the most common new-user mistake:

| Step | What it references | Where it comes from |
|---|---|---|
| `/plugin marketplace add `**`kirinchen/claude-workbench`** | GitHub **repo** (auto-expands to `https://github.com/kirinchen/claude-workbench`) | Your GitHub `owner/repo` path |
| `/plugin install kanban@`**`claude-workbench`** | **Marketplace name** — the `"name"` field inside `.claude-plugin/marketplace.json` | Set in the marketplace metadata, not the repo name |

They're equal today by choice. If the repo were ever renamed to `cwb`, the add command would become `kirinchen/cwb` but install would still be `kanban@claude-workbench` (until the marketplace.json's `name` field is also changed). Other accepted `add` sources: full HTTPS URL, SSH URL (for private), local path — see [Claude Code plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces).

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

## Composition

Capability detection (SPEC §8.7): each plugin checks for sibling CLIs (`workbench-notify`, `workbench-memory`, `workbench-docsync`) via `--health` and gracefully degrades when absent.

| Pair | Effect | Status |
|---|---|---|
| `kanban × notify` | State transitions trigger push notifications (BLOCKED → high priority). | wired, not E2E tested |
| `kanban × memory` | `/kanban:next` queries past sessions; `/kanban:done` saves completion notes. | awaits memory |
| `kanban × docsync` | DONE gate: when `enforcement=block`, `workbench-docsync check` blocks premature DONE transitions. | wired, awaits E2E test |
| `notify × memory` | Decision prompts carry "last time you chose X". | awaits memory |
| `docsync × memory` | Doc-change summaries persisted at session end. | wired, awaits memory |

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
├── .claude-plugin/marketplace.json     # 6 plugin entries
├── plugins/
│   ├── kanban/                         # v0.1.0 (ready)
│   ├── notify/                         # v0.1.0 (ready — Pushover)
│   ├── memory/                         # v0.0.1 (stub)
│   ├── docsync/                        # v0.1.0 (ready — dev profile)
│   ├── workbench/                      # v0.0.1 (meta stub)
│   └── workbench-dev/                  # v0.0.1 (meta stub)
└── schema/
    ├── kanban.schema.json              # canonical schema
    └── docsync.schema.json             # canonical schema
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
- Quickstarts: [`kanban`](./kanban_quickstart.md) · [`notify`](./notify_quickstart.md) · [`docsync`](./docsync_quickstart.md)
- [Claude Code plugins docs](https://code.claude.com/docs/en/plugins)
- [Claude Code hooks reference](https://code.claude.com/docs/en/hooks)
- [Model Context Protocol](https://modelcontextprotocol.io)
