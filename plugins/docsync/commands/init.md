---
description: Interactive scan→interview→dry-run→write to create .claude/docsync.yaml.
argument-hint: [--from-existing-claude-md] [--reset]
allowed-tools: Read, Write, Glob, Grep, Bash(git:*), Bash(ls:*), Bash(test:*), Bash(cat:*), Bash(mkdir:*), Bash(bash:*), Bash(workbench-docsync:*), AskUserQuestion
---

# /docsync:init

Arguments: `$ARGUMENTS`

Generate `.claude/docsync.yaml` through the **scan → infer → interview → dry-run → validate** flow described in SPEC §6.7. Behave like an experienced consultant walking into an office: look around first, only ask what you genuinely need the human for.

## 1. Pre-flight

- If `.claude/docsync.yaml` already exists and `--reset` is NOT set: stop and ask the user whether to overwrite (`/docsync:init --reset`) or edit by hand.
- If `--reset` is set: read the existing YAML first so you can pre-fill answers during the interview, then propose the new shape alongside the old.

## 2. Phase 1 — Scan (silent)

Detect **project type**:

- `Cargo.toml` with `[workspace]` → Rust monorepo
- `pnpm-workspace.yaml` / `lerna.json` → JS monorepo
- `pyproject.toml` / `setup.py` / `setup.cfg` → Python
- `go.mod` → Go
- Multiple of the above → mixed; report all

Enumerate **code modules** (top-level dirs, minus): `.git`, `node_modules`, `target`, `dist`, `.venv`, `venv`, `.cache`, `build`, `out`, `.idea`, `.vscode`, `doc*`, `docs*`.

Enumerate **docs**: `doc/`, `docs/`, `documentation/`, plus root-level `README*`, `ARCHITECTURE*`, `CODE_MAP*`, `SPEC*`, `DIRECTORY_TREE*`, `CONTRIBUTING*`. For each code module, also look for its own `README.md`.

If `--from-existing-claude-md`:
- Read `CLAUDE.md` at the project root.
- Parse tables or bulleted rules that look like "when X → update Y". Pre-fill the interview answers.

Report the scan summary to the user before any questions:

> **Scan:**
> - Project type: Rust monorepo (Cargo workspace with 4 members)
> - Code modules: `common`, `execution`, `position-manager`, `risk`
> - Docs found: `doc/ARCHITECTURE.md`, `doc/CODE_MAP.md`, `doc/SPEC.md`, plus module READMEs in `position-manager/`, `risk/`
> - Pre-filled rules: 3 (from CLAUDE.md mapping table)

## 3. Phase 2 — Interview (AskUserQuestion, batches ≤ 3)

Use `AskUserQuestion` with multi-select / single-select where possible. Never more than 3 questions per call.

**Batch 1 — Bootstrap docs** (multi-select):
> Which docs should I ask Claude to read at the start of every session?
> Candidates: `doc/ARCHITECTURE.md`, `doc/CODE_MAP.md`, `doc/SPEC.md`, `doc/DIRECTORY_TREE.md`, ...

**Batch 2 — Module → doc mapping** (single-select per module, in batches of ≤3 modules at a time):
> For `position-manager/**`, pick the update target:
>   (a) Global CODE_MAP section
>   (b) Module's own README
>   (c) Both
>   (d) Neither — no doc update required
>   (e) Custom paths (will prompt)

**Batch 3 — Enforcement** (single-select):
> Enforcement level?
>   - `warn` (recommended) — PostToolUse hook reminds Claude in context
>   - `block` — gates `/kanban:done` when docsync has pendings (requires kanban integration)
>   - `silent` — only `/docsync:check` surfaces pendings

**Batch 4 — Skip conditions** (multi-select):
> Which changes should Claude be allowed to consider "no doc update needed"?
> Candidates: `bug_fix_only`, `internal_refactor`, `test_only`, `comment_formatting_only`

**Batch 5 — Integration** (only if `workbench-kanban` or `workbench-memory` is available):
> Enable kanban DONE gate when docsync has pendings? (yes / no)
> Persist doc-change summaries into memory at session end? (yes / no)

## 4. Phase 3 — Propose

Render the complete draft YAML in a single code block. Ask:

> Does this look right?
>  - `yes` — proceed to dry-run
>  - `edit <section>` — tell me which section (rules / bootstrap_docs / skip_conditions / integration / enforcement)
>  - `cancel` — abort, do not write

Loop on `edit` until the user says `yes` or `cancel`.

## 5. Phase 4 — Dry-run validate (the killer feature)

Before writing the file:

1. `git log -n 20 --pretty=format:"%h %s"` → get the last 20 commits.
2. Pick **3 representative** commits:
   - One that crosses multiple modules
   - One that is doc-heavy
   - One that is code-only
3. For each, run `git show --name-only --pretty=format: <sha>` and feed the file list through the draft rules (use `workbench-docsync match <path>` ONLY if the YAML is already written; otherwise simulate in-message by applying the globs).
4. Render the "if docsync v1 had been active" report:

```
commit abc123 "refactor grid pricing"
├ changed: position-manager/src/grid.rs
└ would prompt: doc/CODE_MAP.md (§position-manager)
                position-manager/README.md (required_if: params_changed)

commit def456 "fix typo in comment"
├ changed: common/src/types.rs
└ would skip (matches skip_condition: comment_formatting_only)
```

Ask once more:

> Dry-run result look reasonable? (yes / edit / cancel)

## 6. Phase 5 — Write

Only after `yes`:

1. `mkdir -p .claude` at the project root.
2. Write `.claude/docsync.yaml` with the final shape.
3. Run `bash ${CLAUDE_PLUGIN_ROOT}/scripts/install-cli.sh` and surface stdout.
4. Run `workbench-docsync validate` and surface the result. If it fails, print the errors but don't delete the file — the user can fix it by hand.

## 7. Post-write checks

- Verify `.claude/` isn't ignored by `.gitignore` in a way that would hide this file. If it is (e.g. `.claude/*` broadly), tell the user how to un-ignore just `docsync.yaml` (`!docsync.yaml`).
- Ask whether to commit now:
  > `git add .claude/docsync.yaml && git commit -m "chore: add docsync config"`
  > (yes / no — if no, just print the command)

## 8. Emit next-steps

> ✓ docsync initialised.
>
> Try:
>   `/docsync:check --since HEAD~5`
>   `/docsync:rules position-manager/src/grid.rs`
>
> The `/docsync:bootstrap` command lists the docs I'll remind you to read at session start.

## Absolute rules

- Never write `.claude/docsync.yaml` without the user confirming the dry-run (phase 5 explicit `yes`).
- Never hand-edit `CLAUDE.md` during this flow (that's out of scope — docsync owns its own file).
- Never ask more than 3 questions per `AskUserQuestion` call.
- Never skip Phase 4 (dry-run). It's what sells the rules to the user.
- Never use `--allowedTools` or suggest bypassing hooks as a shortcut.
