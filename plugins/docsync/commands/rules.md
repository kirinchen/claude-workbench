---
description: Show docsync rules; test what matches a given path.
argument-hint: [<file-path>]
allowed-tools: Bash(workbench-docsync:*)
---

# /docsync:rules

Arguments: `$ARGUMENTS` — optional file path.

## 1. With a path

```bash
workbench-docsync match "$PATH" --format json
```

Render the result readably:

> Matches for `position-manager/src/grid.rs`:
>   - rule `position-manager` (pattern: `position-manager/**`)
>     → `doc/CODE_MAP.md` §position-manager  required=true
>     → `position-manager/README.md`  required_if=params_changed

If zero matches, say: "No rule matches `<path>`. Either it's genuinely unmapped, or your rule globs don't cover it."

## 2. Without a path

```bash
workbench-docsync rules --format text
```

Render as a table (rule id · pattern · target docs) plus enforcement level and bootstrap docs. Point at `/docsync:init --reset` for edits.

## Absolute rules

- Read-only. Never modify YAML.
- If the config is missing, tell the user to run `/docsync:init`.
