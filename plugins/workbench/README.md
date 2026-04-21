# workbench (meta)

*[繁體中文](./README_zhtw.md)*

Part of the [claude-workbench](../../README.md) family.

This is a **meta-plugin** — it has no commands, skills, or hooks of its own. Installing it pulls in the three sibling plugins so you get the core bundle in one shot:

- [`kanban`](../kanban) — task lifecycle via `kanban.json`
- [`notify`](../notify) — push notifications when Claude needs attention
- [`memory`](../memory) — persistent RAG memory across sessions

## Install

```bash
> /plugin marketplace add kirinchen/claude-workbench
> /plugin install workbench@claude-workbench
```

## Current status

- `kanban` — v0.1.0 ✓
- `notify` — v0.1.0 ✓
- `memory` — v0.0.1 stub (real in v0.1.0)

Until `memory` v0.1.0 lands, prefer installing the individual plugins. This bundle is useful today only as a roadmap marker — its dependency set isn't pinned yet and will switch to real `^0.1.0` bounds when memory ships.

See [`SPEC.md §9`](../../SPEC.md) for the design.
