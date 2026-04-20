# workbench-dev (meta, stub)

Part of the [claude-workbench](../../README.md) family.

**Meta-plugin** — no commands, skills, or hooks of its own. Installing it pulls in the full developer stack:

- [`workbench`](../workbench) — core bundle (`kanban` + `notify` + `memory`)
- [`docsync`](../docsync) — code ↔ documentation sync tracking
- Future additions: `review` (AI code review), `lint` (config-driven lint reminders)

## Install

```bash
> /plugin marketplace add kirin/claude-workbench
> /plugin install workbench-dev@claude-workbench
```

## Current status

- `workbench` — v0.0.1 stub (core bundle)
- `docsync` — v0.0.1 stub (Phase 7)

This bundle is useful today only as a roadmap marker. Prefer installing plugins individually until v0.1.0 of `docsync` lands.

See [`SPEC.md §9.2`](../../SPEC.md) for the design.
