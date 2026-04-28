---
description: Re-align an existing project's scaffold with the active framework — list missing docs, optionally fill them in.
argument-hint: [--apply]
allowed-tools: Bash(workbench-mentor:*), Bash(diff:*), Bash(git:*), Read
---

# /mentor:upgrade

Arguments: `$ARGUMENTS`

## Goal

Diff the active framework's scaffold rules (`plugins/mentor/frameworks/<mode>/framework.yaml`) against the user's repo and report:

- **Missing required** scaffold files
- **Missing optional** scaffold files (e.g. `doc/task.md` when no kanban)
- **Skipped** rules whose `when` clause doesn't apply (e.g. `current_state` not enabled)

Optionally fill in the missing files from templates with `--apply`.

## What this command does NOT do

- It does **not** touch `.claude/mentor.yaml`. If you need new schema fields, run `/mentor:init --reset` (which preserves doc files but rewrites the yaml).
- It does **not** overwrite existing files. Existing scaffold content is preserved verbatim, even if the template was updated in a newer mentor version.
- It does **not** diff the *content* of existing files against newer templates. See "Manual content compare" below.

## Steps

### 1. Pre-flight

Run `workbench-mentor --health`. If it fails (no `.claude/mentor.yaml`), tell the user to run `/mentor:init` first and stop.

### 2. Dry-run report (always)

Run:

```bash
workbench-mentor upgrade --format text
```

Surface the report verbatim. Possible outcomes:

- **Nothing to do** → end. Optionally run `/mentor:review` to confirm compliance is clean.
- **Only `Skipped` rules** → end. The `when` clauses didn't activate, by design.
- **Missing files** → continue to step 3.

### 3. Confirm + apply (only if missing files exist and `--apply` not in `$ARGUMENTS`)

Ask the user:

> Create N missing file(s) from templates? Existing files will not be touched. [y/N]

On `y`, run:

```bash
workbench-mentor upgrade --apply --format text
```

If `$ARGUMENTS` already contains `--apply`, skip the confirmation and run apply directly.

### 4. Post-apply

After `--apply` reports created files:

1. Suggest `git diff` (or `git status`) so the user can inspect new files before committing.
2. Suggest `/mentor:review` to confirm compliance is now clean.
3. If the user wants to commit, propose:
   ```
   git add doc/ && git commit -m "chore: scaffold gaps filled by /mentor:upgrade"
   ```
   (Only suggest — never commit autonomously.)

## Per-file diff against the current template (`--diff`)

When the user passes `--diff <FILE>` (e.g. `/mentor:upgrade --diff doc/Epic/epic-template.md`), call:

```bash
workbench-mentor upgrade --diff <FILE> --format text
```

This produces a unified diff between the user's repo file and the bundled template. Use it when a template has changed in a later mentor version and the user wants to cherry-pick edits into an existing file (which `--apply` will *not* touch).

Surface the diff verbatim. After the diff:

- If the CLI says the file is **identical to the template**: confirm "no merge needed" and stop.
- If a **diff is shown**: do **not** auto-apply it. Suggest the user copy/paste the relevant hunks themselves, or open the file and the template side-by-side.

`--diff` is mutually exclusive with `--apply`; the CLI rejects the combination.

## Edge cases

- **`framework.yaml` borrows a template from another mode** (e.g. development's `doc/task.md` borrows `../../basic/templates/task.md`). The CLI resolves these correctly; just report what it says.
- **Custom `paths.*` in mentor.yaml**: the CLI remaps default paths (`doc/SPEC.md`, `doc/Epic/`, ...) to the user's configured paths via prefix substitution. Targets in the report reflect the user's actual paths, not the framework defaults.
- **Template file missing on disk** (corrupted plugin install): CLI silently skips that rule during `--apply`. Surface a hint to re-install the plugin if the user expected a file but `--apply` didn't create it.

## Absolute rules

- **Never** overwrite an existing scaffold file. The CLI guarantees this; do not invoke any other tool that bypasses it.
- **Never** modify `.claude/mentor.yaml` from this command.
- **Never** run `--apply` without first showing the dry-run report (unless the user passed `--apply` explicitly in `$ARGUMENTS`).
- **Never** commit on the user's behalf. Suggest the commit; let them run it.
