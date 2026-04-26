# claude-workbench

*[繁體中文](./README_zhtw.md)*

A family of Claude Code plugins that turn the CLI into a persistent, event-driven AI workspace. Install one, two, or all of them — each plugin is useful on its own, and they reinforce each other when combined.

> **Status**: v0.1.0 (Draft). `kanban`, `notify`, and `docsync` are shipped; `memory` is the remaining core stub. See [`SPEC.md`](./SPEC.md) for the full design and [`current_state.md`](./current_state.md) for the live implementation snapshot.
>
> **Quickstarts**: [`kanban`](./kanban_quickstart.md) · [`notify`](./notify_quickstart.md) · [`mentor`](./mentor_quickstart.md) *(docsync was replaced by mentor — see [`epic/mentor-plugin-spec.md`](./epic/mentor-plugin-spec.md))*

## Plugins

| Plugin | Profile | Solves | Status |
|---|---|---|---|
| [`kanban`](./plugins/kanban) | core | Task state persistence + shared human/AI work queue via `kanban.json` | **v0.1.1 ready** |
| [`notify`](./plugins/notify) | core | Push notifications (Pushover) when Claude needs your attention | **v0.1.1 ready** |
| [`memory`](./plugins/memory) | core | Cross-session RAG memory (SQLite + embeddings, local only) | v0.0.1 stub |
| [`mentor`](./plugins/mentor) | dev | Onboarding mentor — prescribes bootstrap docs, Epic/Sprint/Issue/ADR hierarchy, agent workflow (replaces `docsync`) | **v0.1.1 ready** |
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
# 1. Start Claude Code in any project
cd my-project
claude

# 2. Add the marketplace (public repo; use the SSH URL for private)
> /plugin marketplace add kirinchen/claude-workbench

# 3. Install what you need
> /plugin install kanban@claude-workbench       # ready
> /plugin install notify@claude-workbench       # ready (Pushover)
> /plugin install mentor@claude-workbench       # ready (dev profile, replaces docsync)
> /plugin install memory@claude-workbench       # coming soon
> /plugin install workbench@claude-workbench    # bundle (when memory ships)
```

Then jump into the quickstart for each plugin you installed — see the links at the top of this file.

> **No shell rc editing required.** Hook scripts and slash commands auto-prepend `~/.claude-workbench/bin` to `PATH` when they run, and notify reads tokens from `~/.claude-workbench/.env` (written by `/notify:setup`). Add `export PATH="$HOME/.claude-workbench/bin:$PATH"` only if you want to run `workbench-*` CLIs **manually from your terminal** for debugging.

### Two identifiers, one letter apart

The install flow uses two separate names that happen to look similar. Getting them mixed up is the most common new-user mistake:

| Step | What it references | Where it comes from |
|---|---|---|
| `/plugin marketplace add `**`kirinchen/claude-workbench`** | GitHub **repo** (auto-expands to `https://github.com/kirinchen/claude-workbench`) | Your GitHub `owner/repo` path |
| `/plugin install kanban@`**`claude-workbench`** | **Marketplace name** — the `"name"` field inside `.claude-plugin/marketplace.json` | Set in the marketplace metadata, not the repo name |

They're equal today by choice. If the repo were ever renamed to `cwb`, the add command would become `kirinchen/cwb` but install would still be `kanban@claude-workbench` (until the marketplace.json's `name` field is also changed). Other accepted `add` sources: full HTTPS URL, SSH URL (for private), local path — see [Claude Code plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces).

## Update

Updating has two layers — the **plugin code** on each machine, and any **project scaffold** mentor created inside your repo.

### Update the plugin (per machine)

```bash
> /plugin marketplace update claude-workbench
> /plugin update mentor@claude-workbench         # or kanban / notify
> /reload-plugins
```

The middle command is the one that matters — without `marketplace update`, `install` / `update` keep using the local cache at `~/.claude/plugins/cache/`. Repeat on every machine where you use the plugin; the cache is per-machine and is **not** synced through your repo.

Verify: `/doctor` should show no `Plugin errors` section, and `/reload-plugins` should report a non-zero `hooks` count.

### Re-align an existing project's scaffold (mentor only)

`/mentor:init` writes files into your repo. Those files do **not** auto-resync when mentor's framework templates change in a later version.

```bash
> /mentor:review              # list compliance gaps — missing docs, frontmatter drift, orphans
> /mentor:new <kind>          # create new Epic / Sprint / Issue / ADR using the latest templates
> /mentor:current-state       # opt in to the current_state/ layer if you didn't initially
```

If `/mentor:review` reports a missing scaffold doc that the current framework expects (for example `doc/task.md`, referenced from `plugins/mentor/frameworks/<mode>/framework.yaml`'s scaffold rules), open that yaml and add the missing pieces by hand. A dedicated `/mentor:upgrade` command that diffs scaffold rules against your repo and offers to fill the gaps is on the roadmap.

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
| `kanban × mentor` | New Issue can spawn kanban task; optional DONE gate on Issue Acceptance Criteria. | wired, awaits E2E test |
| `notify × memory` | Decision prompts carry "last time you chose X". | awaits memory |
| `mentor × memory` | Sprint retros + accepted ADRs persisted to memory. | wired, awaits memory |
| `mentor × notify` | Sprint-end / Epic-done push notifications. | wired, awaits E2E test |

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
│   ├── mentor/                         # v0.1.0 (ready — dev profile, replaces docsync)
│   ├── workbench/                      # v0.0.1 (meta stub)
│   └── workbench-dev/                  # v0.0.1 (meta stub)
└── schema/
    ├── kanban.schema.json              # canonical schema
    └── mentor.schema.json              # canonical schema
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
- Quickstarts: [`kanban`](./kanban_quickstart.md) · [`notify`](./notify_quickstart.md) · [`mentor`](./mentor_quickstart.md)
- [Claude Code plugins docs](https://code.claude.com/docs/en/plugins)
- [Claude Code hooks reference](https://code.claude.com/docs/en/hooks)
- [Model Context Protocol](https://modelcontextprotocol.io)
