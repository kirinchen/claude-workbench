# docsync (stub)

Part of the [claude-workbench](../../README.md) family — **dev profile**.

**Status**: Not yet implemented. See [`SPEC.md §6`](../../SPEC.md) for the full design.

Planned in v0.1.0 (Phase 7):
- `/docsync:init` — interactive `scan → interview → dry-run → write` onboarding that produces `.claude/docsync.yaml`
- `/docsync:check`, `/docsync:rules`, `/docsync:bootstrap`, `/docsync:validate`
- SessionStart / PostToolUse / Stop hooks for bootstrap-docs reminder, post-edit sync guard, and session-end summary
- Rule engine: glob match, `required_if` semantic conditions, `skip_conditions`
- YAML templates for Rust / Python / JS monorepos
- `workbench-docsync` public CLI (for `kanban × docsync` DONE gate and `memory × docsync` summaries)

This stub plugin carries no commands or hooks yet. Please wait for Phase 7.
