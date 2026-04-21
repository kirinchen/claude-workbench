# docsync

*[繁體中文](./README_zhtw.md)*

Part of the [claude-workbench](../../README.md) family — **dev profile**. See [`SPEC.md §6`](../../SPEC.md) for the full design.

Keep **code changes** and **documentation** in sync. Config-driven, not prompt-driven: per-project mapping lives in `.claude/docsync.yaml`, generated interactively by `/docsync:init` (scan → interview → dry-run → write).

## Why

Living docs (ARCHITECTURE.md, CODE_MAP.md, per-module README) lose truthfulness as Claude edits code without touching them. The common workaround — hardcoding "when you change X, update Y" rules into `CLAUDE.md` — is unstructured, unportable, unverifiable. docsync replaces that with a versioned YAML the whole team (and Claude) can read.

## Install

```bash
> /plugin install docsync@claude-workbench
> /docsync:init                  # interactive setup
```

`/docsync:init` will:

1. **Scan** the repo — project type, modules, existing docs.
2. **Interview** you in small batches (`AskUserQuestion`) — bootstrap docs, module→doc mapping, enforcement level, skip conditions.
3. **Dry-run** against the last ~20 git commits — "if docsync v1 had been active, here's what it would have flagged".
4. **Write** `.claude/docsync.yaml` and offer to commit it.

## Slash commands

| Command | Purpose |
|---|---|
| `/docsync:init` | Interactive setup (scan → interview → dry-run → write) |
| `/docsync:check` | Manually scan for pending syncs since a git ref |
| `/docsync:rules` | Show which rule matches a given path |
| `/docsync:bootstrap` | List the `bootstrap_docs` the plugin asks Claude to read at SessionStart |
| `/docsync:validate` | Validate `.claude/docsync.yaml` against the schema |

## Enforcement levels

Set in `.claude/docsync.yaml` → `enforcement`:

- `silent` — only `/docsync:check` surfaces pendings.
- `warn` (default) — PostToolUse hook reminds Claude in context after each code edit.
- `block` — when `integration.kanban.block_done_if_pending: true`, `/kanban:done` is gated on a clean docsync.

## CLI

`workbench-docsync` is the stable integration surface for sibling plugins:

```bash
workbench-docsync match <file-path> --format json       # which rules apply?
workbench-docsync check --since <git-ref> --format json # any pending syncs?
workbench-docsync summarize --session <id> --format json
workbench-docsync --health
```

All read-only. Never mutates the YAML.

## Templates

Three starter templates are bundled — `/docsync:init` uses the closest match to your detected project type:

- `docsync.example.yaml` — Rust monorepo (Cargo workspaces)
- `docsync.python.yaml` — Python project (`pyproject.toml`)
- `docsync.js.yaml` — JS monorepo (pnpm / lerna)

## Integration

- `docsync × kanban` — DONE gate when `integration.kanban.block_done_if_pending: true`.
- `docsync × memory` — doc-change summaries persisted when `integration.memory.summarize_doc_changes: true`.
- `docsync × notify` — passive only. docsync never pushes directly; blocked transitions fire through kanban's notify path (SPEC §8.6).

## Profile

docsync is `dev` profile — part of the `workbench-dev` meta-bundle, not the core `workbench` bundle.
