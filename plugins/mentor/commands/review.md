---
description: Compliance check — missing docs, frontmatter drift, orphan issues.
allowed-tools: Bash(workbench-mentor:*), Bash(export:*)
---

# /mentor:review

## 1. Run

```bash
export PATH="$HOME/.claude-workbench/bin:$PATH"
workbench-mentor review --format text
```

## 2. Interpret

- Exit 0 → report "✓ clean".
- Exit 2 → surface each violation verbatim, grouped by kind:
  - `missing_doc` — expected directory/file absent
  - `no_frontmatter` — doc has no YAML frontmatter block
  - `drift` — frontmatter present but missing required fields
  - `orphan_issue` — issue.epic points to non-existent epic
- Other non-zero → mentor not configured; tell the user to run `/mentor:init`.

## 3. Do NOT auto-fix

Review is diagnostic only. To fix:
- `missing_doc` for a framework file → materialise via `/mentor:new <type>`
- `no_frontmatter` / `drift` → the user edits the file, Claude can help but only with their go-ahead
- `orphan_issue` → fix the `epic:` frontmatter field, or create the missing Epic first

## Absolute rules

- Read-only. Never writes files.
- Never silently rewrite violations. Compliance is a human-in-the-loop decision.
