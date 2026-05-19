---
description: Propose a refreshed doc/feat_map.md as a reviewable diff against the committed version — never overwrites silently.
argument-hint: [--apply]
allowed-tools: Read, Grep, Glob, Bash(git:*), Bash(workbench-mentor:*), Bash(diff:*), AskUserQuestion, Write
---

# /mentor:renewtree

Arguments: `$ARGUMENTS`

## Goal

Walk the codebase, build a fresh feature tree, and **propose** an updated `doc/feat_map.md` as a unified diff against the committed file. The user reviews and accepts (manually, or via `--apply`); this command never silently overwrites the canonical artifact.

`feat_map.md` is a **reviewable artifact, not a regenerated cache** (spec §8). Topology renames break node identity and external references — every regeneration should be a human-in-the-loop change.

Spec: [kirinchen/claude-workbench#60](https://github.com/kirinchen/claude-workbench/issues/60).

## What this command does NOT do

- Does **not** invent status. Existing leaf statuses (`@done` / `@wip` / `@todo` / `@blocked`) are carried forward by node path; only **new** leaves get a default `@todo`.
- Does **not** overwrite without explicit confirmation. Default behavior is diff-only; `--apply` writes only after the user has seen the diff.
- Does **not** touch frontmatter values that are already set (`repo`, `display_name`, `jira_base_url`, `repo_url`, `owner`). New files inherit placeholders from the template.
- Does **not** validate cross-repo `repo` slug uniqueness — that's the kelp viewer's job when it scans `project/`.

## Pre-flight

1. Run `workbench-mentor --health`. If it fails: tell the user to run `/mentor:init` first and stop.
2. Read `.claude/mentor.yaml`. If `mode != development`: tell the user `feat_map.md` is only enforced in development mode and stop (offer `/mentor:upgrade` if they want to switch).
3. Read the current `doc/feat_map.md` if it exists. Parse its frontmatter and tree using the same shape the validator expects (bullets, indentation, status tokens, Jira refs, `note:` children).

## Phase 1 — Survey the codebase

Use `Glob` + `Read` to build a mental model of feature topology. Sources, in priority order:

1. **`doc/SPEC.md`** § Architecture / § Public interface — the declared feature boundary.
2. **`doc/Epic/*.md`** frontmatter (`id`, `title`, `status`) — active feature directions.
3. **Top-level packages / plugins / modules** (e.g. `plugins/*/`, `packages/*/`, `crates/*/`) — the durable shape.
4. **`doc/Wiki/architecture-decisions/*.md`** — ADRs that named specific subsystems.
5. **The current `doc/feat_map.md`** itself — preserve titles for stability.

Do **not** grep over `node_modules/`, `target/`, `dist/`, `.git/`, vendored deps. Cap the scan at ~30 directories and ~50 read operations; this is a coarse-grained ledger, not a full code map.

## Phase 2 — Propose the tree

Build a forest where:

- Top-level bullets = **modules / plugins / major subsystems** (1–10 typical).
- Children = **features** within that module (each a deliverable thing, not a file).
- Grandchildren = **subfeatures** where needed; otherwise keep depth at 2.
- **Leaves** carry the status. Default new leaves to `` `@todo` ``. Carry over existing statuses by matching node path (root title → ... → leaf title). On rename, treat it as a new leaf — surface the rename to the user.

Status carry-over rules:

| Existing leaf status | Action |
|---|---|
| `@done` | Carry forward unless the leaf has obviously been removed. |
| `@wip` / `@blocked` | Carry forward; surface as "still in progress / still blocked — confirm?" |
| `@todo` | Carry forward. |
| Leaf no longer exists | Drop. Mention dropped leaves in the proposal summary. |

Preserve `(jira:KEY)` refs and `note:` children verbatim when the leaf carries over.

## Phase 3 — Render the proposed file

Render the full proposed `doc/feat_map.md` content to a scratch buffer:

- Frontmatter: reuse existing values verbatim. If creating from scratch, fill `repo` from the directory basename and leave the rest as placeholders for the user to set.
- Body: heading `# {display_name} — Feature Map`, optional one-line intro, then the tree.
- Hard rules (the validator will check):
  - Bullet marker is `- ` only. No `*`, no `+`, no tabs.
  - Exactly 2 spaces per nesting level.
  - Status tokens on leaves only.
  - `(jira:KEY)` on leaves only, matching `^[A-Z][A-Z0-9]+-[0-9]+$`.
  - `- note:` bullets are metadata, attached as children of their parent node.
  - No content after the tree.

## Phase 4 — Diff & confirm

If `doc/feat_map.md` already exists:

1. Write the proposed content to a temp file (e.g. `/tmp/feat_map.proposed.md`).
2. Run `diff -u doc/feat_map.md /tmp/feat_map.proposed.md` and surface the unified diff verbatim.
3. Summarise the changes in plain language:
   - New nodes added (with default `@todo`).
   - Renamed nodes (old title → new title) — flag explicitly, since rename breaks identity.
   - Dropped nodes (and any statuses they carried).
   - Status carry-over confirmations.

If `doc/feat_map.md` does **not** exist: render the full proposed file as a "would create" block instead.

Then ask via `AskUserQuestion`:

> Apply this proposed `feat_map.md`?
>   1. Yes — write it now
>   2. Edit a section first (which?)
>   3. No — discard the proposal

If `$ARGUMENTS` contains `--apply`, skip the question and write directly **only after** showing the diff/preview.

## Phase 5 — Write & validate

On confirmation:

1. Write the proposed content to `doc/feat_map.md`.
2. Run `workbench-mentor review --format text` to confirm zero `feat_map` violations.
3. If violations remain: surface them, undo the write (restore the prior committed version with `git checkout -- doc/feat_map.md` ONLY IF the prior state was clean), and ask the user how to proceed.
4. Suggest: `git diff doc/feat_map.md` (for inspection) and `git add doc/feat_map.md && git commit -m "chore: refresh feat_map.md"` (do not run autonomously).

## Absolute rules

- **Never** overwrite `doc/feat_map.md` without showing the diff first (even with `--apply`, the diff is rendered before the write).
- **Never** invent leaf statuses. New leaves get `@todo`; existing leaves keep their status verbatim.
- **Never** drop a node silently. Every dropped node must appear in the proposal summary.
- **Never** rename a node casually. Renames break identity per spec §8 — surface every rename for explicit human approval.
- **Never** run `git checkout --` unless the user has explicitly asked, AND the prior state was already clean.
- **Never** modify frontmatter values that are already set in the committed file.
