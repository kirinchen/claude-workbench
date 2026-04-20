---
description: Initialize kanban.json + kanban.schema.json in the current project.
argument-hint: [--with-examples]
allowed-tools: Read, Write, Bash(date:*), Bash(cp:*), Bash(test:*), Bash(ls:*)
---

# /kanban:init

Arguments: `$ARGUMENTS`

You are initialising kanban in the project root (`$CLAUDE_PROJECT_DIR` or cwd if unset). Follow these steps exactly:

## 1. Pre-flight checks

Run these checks. If any fail, stop and report:

- If `kanban.json` already exists in the project root, STOP. Ask the user whether to overwrite (`rm kanban.json && re-run`) rather than silently clobbering.
- Confirm we are at the project root (look for `.git` or common markers). If unsure, ask before proceeding.

## 2. Choose template

- If `$ARGUMENTS` contains `--with-examples`: use `${CLAUDE_PLUGIN_ROOT}/templates/kanban.example.json`.
- Otherwise: use `${CLAUDE_PLUGIN_ROOT}/templates/kanban.empty.json`.

## 3. Copy schema

Copy `${CLAUDE_PLUGIN_ROOT}/templates/kanban.schema.json` to `<project-root>/kanban.schema.json`.

## 4. Materialise kanban.json

1. Read the chosen template file.
2. Generate a current ISO 8601 timestamp with timezone via Bash: `date -Iseconds`. Capture the output exactly.
3. Replace **every** occurrence of `__CREATED_AT__` and `__UPDATED_AT__` with that timestamp.
4. Write the result to `<project-root>/kanban.json`.

## 5. Verify

- Read back `kanban.json` and confirm no `__CREATED_AT__` / `__UPDATED_AT__` placeholders remain.
- Report what was created, e.g.:

> ✓ Created kanban.json (empty / with 4 example tasks) and kanban.schema.json.
> Next: try `/kanban:status` or `/kanban:next`.

## Absolute rules

- Do NOT create extra files beyond `kanban.json` and `kanban.schema.json`.
- Do NOT commit. Let the `kanban-autocommit.sh` hook or the user decide.
- Do NOT populate tasks yourself — templates are the only source.
