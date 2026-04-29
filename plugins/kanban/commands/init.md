---
description: Initialize kanban.json + kanban.schema.json in the current project.
argument-hint: [--with-examples]
allowed-tools: Read, Bash(python3:*), Bash(test:*), Bash(ls:*)
---

# /kanban:init

Arguments: `$ARGUMENTS`

Scaffold `kanban.json` (v0.2 shape, `backend.driver=local`) and the matching
`kanban.schema.json` at the project root.

The actual work — copying templates, substituting timestamps, atomic write —
runs in `${CLAUDE_PLUGIN_ROOT}/scripts/kanban_local.py`. The helper writes
through `kanban_io.save()` (atomic `os.replace`), so the `kanban-guard.sh`
PreToolUse hook does NOT fire and there is no Write-tool error to recover
from. **Do not** call the Write or Edit tool directly on `kanban.json`.

## 1. Locate project root

`$CLAUDE_PROJECT_DIR` if set, else `git rev-parse --show-toplevel`, else
the current working directory. The kanban file lives at
`<project-root>/kanban.json`.

## 2. Pre-flight

If `kanban.json` already exists, stop and ask the user whether to overwrite.
The helper supports `--force` for the destructive case; pass it through
only after explicit user confirmation.

## 3. Run the helper

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/kanban_local.py init \
  --kanban-path '<project-root>/kanban.json' \
  [--with-examples]   # only if $ARGUMENTS contains --with-examples
  [--force]           # only after the user said yes to overwriting
```

The helper prints a JSON object:

```json
{ "ok": true, "kanban_path": "...", "schema_path": "...", "tasks": 0, "with_examples": false }
```

On `ok: false`, surface the `error` field and stop.

## 4. Report

```
✓ Created kanban.json v0.2 (local driver, 0 tasks) and kanban.schema.json.
  Next: try /kanban:status or /kanban:next.
```

If `--with-examples` was used, mention the 4 example tasks. If `--force`
overwrote an existing file, mention that previous tasks were discarded.

The template ships with `backend: { driver: "local" }`. To switch to the
Jira backend later, run `/kanban:initjira`.

## Absolute rules

- Do NOT use the Write or Edit tool on `kanban.json` — the helper is the
  only sanctioned mutation path.
- Do NOT create extra files beyond `kanban.json` and `kanban.schema.json`.
- Do NOT commit. Let the `kanban-autocommit.sh` hook or the user decide.
- Do NOT populate tasks yourself — templates are the only source.
