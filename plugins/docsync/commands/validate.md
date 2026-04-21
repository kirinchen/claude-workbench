---
description: Validate .claude/docsync.yaml against the schema.
allowed-tools: Bash(workbench-docsync:*)
---

# /docsync:validate

## 1. Run

```bash
workbench-docsync validate
```

## 2. Interpret

- Exit 0 → report "✓ YAML validates (N rules, M bootstrap docs)".
- Exit 2 → surface each error verbatim. Common causes:
  - `schema_version` not 1 (only supported version)
  - duplicate rule ids
  - unknown `required_if` value
  - bootstrap doc path that doesn't exist
- Other non-zero → tell the user to run `/docsync:init --reset` if the config is truly broken.

## 3. Follow-up

If validation failed, do NOT offer to auto-fix. Ask the user to edit the YAML or re-run `/docsync:init --reset`. docsync deliberately never mutates its own config file.

## Absolute rules

- Read-only. No writes.
- Never suggest editing `CLAUDE.md` in response to a validation failure — the two files are independent.
