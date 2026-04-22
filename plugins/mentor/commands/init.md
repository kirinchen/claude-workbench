---
description: Interactive setup for the mentor plugin — scan, pick framework mode, generate structure.
argument-hint: [--mode=basic|development] [--reset]
allowed-tools: Read, Write, Glob, Grep, Bash(git:*), Bash(ls:*), Bash(test:*), Bash(mkdir:*), Bash(cp:*), Bash(cat:*), Bash(bash:*), Bash(date:*), Bash(workbench-mentor:*), AskUserQuestion
---

# /mentor:init

Arguments: `$ARGUMENTS`

Generate `.claude/mentor.yaml` and the framework's document structure through **scan → infer → interview → propose → write**. Behave like an experienced consultant walking into an office: look around first, only ask what you need the human for.

## 1. Pre-flight

- If `.claude/mentor.yaml` already exists and `--reset` is NOT set: stop and ask whether to overwrite (`/mentor:init --reset`) or edit by hand.
- If `.claude/docsync.yaml` exists: surface this up front. Offer `/mentor:migrate-from-docsync` as an alternative flow — don't silently upgrade.

## 2. Phase 1 — Scan (silent)

Detect:
- **Project type** via well-known files:
  - `Cargo.toml` + `[workspace]` → Rust monorepo
  - `pnpm-workspace.yaml` / `lerna.json` → JS monorepo
  - `pyproject.toml` / `setup.py` → Python
  - `go.mod` → Go
  - Multiple → mixed
- **Existing docs**: `doc/`, `docs/`, plus root-level `README*`, `SPEC*`, `ARCHITECTURE*`, `CODE_MAP*`. For development mode candidates: `Wiki/`, `Epic/`, `Sprint/`, `Issue/`.
- **Sibling plugins**: `command -v workbench-kanban`, `workbench-memory`, `workbench-notify`. Also check for project-level `kanban.json`.
- **Existing docsync config**: `.claude/docsync.yaml` (surfaces in Phase 2 as migration option).

Render the scan summary before any questions.

## 3. Phase 2 — Mode selection

Use `AskUserQuestion` (single-select):

> Found: {project_type}, docs: {present?}, kanban: {yes/no}, docsync: {yes/no}.
>
> Which framework mode fits?
>  1. **basic** — SPEC.md + tasks. Good for personal projects, prototypes, maintenance.
>  2. **development** — SPEC + Wiki + Epic + Sprint + Issue + tasks. Good for planning cycles and multi-agent collaboration.
>  3. **Migrate from existing docsync config** — only shown if `.claude/docsync.yaml` found.

If `$ARGUMENTS` contains `--mode=basic` or `--mode=development`, skip this step and use that.

## 4. Phase 3 — Structure preview

Render the plan concretely. Example (development mode):

```
Will create:
  + doc/SPEC.md                       (from template)
  + doc/Wiki/README.md
  + doc/Wiki/architecture-decisions/ADR-template.md
  + doc/Epic/README.md
  + doc/Sprint/README.md
  + doc/Sprint/SPRINT-{ISO-week}.md   (your first active sprint)
  + doc/Issue/README.md
  + .claude/mentor.yaml

Will keep (already exists):
  = doc/SPEC.md
  = doc/Wiki/                         (will add README if missing)

Skipped:
  - kanban.json (managed by kanban plugin)
```

Let the user edit paths via `paths:` keys if the defaults clash with their layout.

Accept `yes` / `edit <section>` / `cancel`. Loop on `edit` until confirmed.

## 5. Phase 4 — Integration

For each sibling plugin detected, ask one yes/no:

> Detected sibling plugins:
>   ✓ kanban   — Sync issues to kanban tasks? [Y/n]
>   ✓ memory   — Save sprint retros + ADRs to memory? [Y/n]
>   ✓ notify   — Push on sprint-end and epic-done? [Y/n]

Translate answers into `.claude/mentor.yaml` `integration.*.enabled` fields (`auto` when yes, `disable` when no). `auto` means "do it when the sibling's CLI is on PATH AND `--health` returns 0".

## 6. Phase 5 — First sprint (development mode only)

Ask once:

> Create your first sprint now?
>   ID: SPRINT-{year}-W{ISO-week}  (auto)
>   Goal: <free-text>
>   Length: 7 days (ends {today + 7})
>
> [Y/n]

If yes: materialise `doc/Sprint/SPRINT-<id>.md` from the development template with `status: active`. This is the file `mentor-bootstrap.py` surfaces at SessionStart.

## 7. Phase 6 — Write

1. `mkdir -p .claude`
2. Create all directories and files from the chosen framework template:
   - basic → copy `${CLAUDE_PLUGIN_ROOT}/frameworks/basic/templates/SPEC.md` → `<paths.spec>` (if missing)
   - development → copy the full tree under `${CLAUDE_PLUGIN_ROOT}/frameworks/development/templates/` into the project, respecting `paths.*`
3. **Never overwrite** existing files. Report each file as `created` or `kept` and proceed.
4. Write `.claude/mentor.yaml` (schema_version 1 + user's answers).
5. Run `bash ${CLAUDE_PLUGIN_ROOT}/scripts/install-cli.sh` and surface stdout.
6. Run `workbench-mentor --health` and `workbench-mentor review --format text` to confirm structural health.
7. Ask whether to commit:
   > `git add .claude/mentor.yaml doc/ && git commit -m "chore: adopt mentor framework"`  — [Y/n]

## 8. Next-steps block

Print:

```
✓ mentor initialised (mode: basic|development).

Try:
  /mentor:status                  — current sprint + open issues
  /mentor:new issue --title "..." — create your first Issue
  /mentor:review                  — compliance check

Agent will be reminded at session start to read:
  - doc/SPEC.md
  - doc/Sprint/<active>.md (development mode)
```

## Absolute rules

- **Never** write `.claude/mentor.yaml` without a `yes` from Phase 3 and (when shown) Phase 4 / 5.
- **Never** overwrite an existing doc file. If the user wants a fresh template, they delete the old file first.
- **Never** combine kanban.json with `doc/task.md`. Pick one based on whether kanban is installed — the other path stays empty.
- **Never** modify `CLAUDE.md`. This is out of scope for mentor.
- **Never** more than 3 questions per `AskUserQuestion` batch.
- **Never** bypass the scan phase. Even with `--mode=...` flag, still run Phase 1 silently to populate the structure preview with real paths.
