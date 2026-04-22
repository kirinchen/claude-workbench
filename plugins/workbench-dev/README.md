# workbench-dev (meta, stub)

*[繁體中文](./README_zhtw.md)*

Part of the [claude-workbench](../../README.md) family.

**Meta-plugin** — no commands, skills, or hooks of its own. Installing it pulls in the full developer stack:

- [`workbench`](../workbench) — core bundle (`kanban` + `notify` + `memory`)
- [`mentor`](../mentor) — onboarding mentor + doc hierarchy (Epic/Sprint/Issue/ADR) + workflow discipline
- Future additions: `review` (AI code review), `lint` (config-driven lint reminders)

## Install

```bash
> /plugin marketplace add kirinchen/claude-workbench
> /plugin install workbench-dev@claude-workbench
```

## Current status

- `workbench` — v0.0.1 stub (waits on `memory` v0.1.0)
- `mentor` — v0.1.0 ✓ (replaces earlier `docsync` draft)

Until the `workbench` meta-bundle can pin `^0.1.0` of all three core plugins (i.e. once `memory` ships), prefer installing the individual plugins.

See [`SPEC.md §9.2`](../../SPEC.md) for the design.
