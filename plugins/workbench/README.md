# workbench (meta)

Part of the [claude-workbench](../../README.md) family.

This is a **meta-plugin** — it has no commands, skills, or hooks of its own. Installing it pulls in the three sibling plugins so you get the whole kit in one shot:

- [`kanban`](../kanban) — task lifecycle via `kanban.json`
- [`notify`](../notify) — push notifications when Claude needs attention
- [`memory`](../memory) — persistent RAG memory across sessions

## Install

```bash
> /plugin marketplace add kirin/claude-workbench
> /plugin install workbench@claude-workbench
```

## Current status

- `kanban` — v0.1.0 (ready)
- `notify` — v0.0.1 stub (real in v0.1.0)
- `memory` — v0.0.1 stub (real in v0.1.0)

Prefer installing plugins individually until v0.1.0 of all three lands. Today the bundle is useful mainly as a roadmap marker.

See [`SPEC.md §9`](../../SPEC.md) for the design.
