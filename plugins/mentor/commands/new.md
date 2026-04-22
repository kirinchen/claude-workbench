---
description: Create a new Epic, Sprint, Issue, or ADR from the mode's template.
argument-hint: <epic|sprint|issue|adr> [--title=<text>] [--epic=EPIC-001]
allowed-tools: Read, Write, Glob, Bash(ls:*), Bash(test:*), Bash(date:*), Bash(mkdir:*), Bash(workbench-mentor:*), Bash(export:*), AskUserQuestion
---

# /mentor:new

Arguments: `$ARGUMENTS`

Create a new structured document. Behaviour depends on the current framework mode (`workbench-mentor config --format json` tells you).

## 1. Parse args

- First positional: **required** — `epic` | `sprint` | `issue` | `adr`.
- `--title=<text>` — if missing and needed, ask via `AskUserQuestion` once.
- `--epic=<id>` — only meaningful for `issue` subtype; optional.

Reject `epic` / `sprint` / `issue` / `adr` in `basic` mode — that hierarchy only exists in `development`. Tell the user to `/mentor:init --reset` to switch mode.

## 2. Resolve paths and next ID

```bash
export PATH="$HOME/.claude-workbench/bin:$PATH"
workbench-mentor config --format json
```

Pull `paths.<type>` and `id_patterns.<type>`. For `epic`/`issue`: find the highest existing sequence number in that directory, increment. For `sprint`: use ISO week (`date +%G-W%V` or equivalent).

## 3. Gather fields interactively

Use `AskUserQuestion` in batches of ≤3. Only ask what's required per type:

| Type | Required ask |
|---|---|
| epic | title, why (1–2 sentence), target sprint (optional) |
| sprint | goal, start date (default today), end date (default +7d) |
| issue | title, parent epic (select from existing), priority (P0–P3) |
| adr | title, context (1–2 sentence), decision (1 sentence) |

## 4. Materialise

1. Read the appropriate template from `${CLAUDE_PLUGIN_ROOT}/frameworks/development/templates/`:
   - epic → `Epic/epic-template.md`
   - sprint → `Sprint/sprint-template.md`
   - issue → `Issue/issue-template.md`
   - adr → `Wiki/architecture-decisions/ADR-template.md`
2. Fill frontmatter (`id`, `title`, `created`, `status: planning` or appropriate default, linked ids).
3. Write to `<paths.<type>>/<generated-id>.md`.
4. If `integration.kanban.sync_issue_to_task: true` AND the type is `issue` AND the kanban plugin is installed: **do NOT** directly edit `kanban.json` (that's guarded). Instead, print an instruction: "Add a kanban task via `/kanban:*` referencing this issue."

## 5. Report

Show the path created and the next-step suggestions:

```
✓ Created doc/Issue/ISSUE-043.md
  epic: EPIC-001
  status: open
  priority: P1

Next:
  - Fill in the Acceptance Criteria section
  - /kanban:next to pick an implementation task (if tasks added)
```

## Absolute rules

- Never use this command in `basic` mode. Stop and explain.
- Never overwrite an existing file. If the auto-generated ID collides, bump.
- Never modify `kanban.json` from this command — that belongs to the kanban plugin's guarded path.
- Never invent fields beyond the template. Extensions go in `custom:` frontmatter (future).
