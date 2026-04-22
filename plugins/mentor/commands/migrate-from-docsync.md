---
description: Read .claude/docsync.yaml and generate .claude/mentor.yaml.
allowed-tools: Read, Write, Bash(ls:*), Bash(test:*), Bash(cp:*), Bash(mv:*), Bash(workbench-mentor:*), Bash(export:*), AskUserQuestion
---

# /mentor:migrate-from-docsync

Convert an existing docsync configuration to a mentor configuration. Safe: `.claude/docsync.yaml` is backed up, not deleted.

## 1. Pre-flight

- Verify `.claude/docsync.yaml` exists. If not: stop, tell user nothing to migrate.
- If `.claude/mentor.yaml` also exists: stop, ask whether to overwrite (`/mentor:migrate-from-docsync --force`) or cancel. **Do not silently merge.**

## 2. Parse docsync.yaml

Read the YAML. Relevant fields to translate:
- `bootstrap_docs` → `agent_behavior.bootstrap_docs`
- `enforcement: block` + `integration.kanban.block_done_if_pending` → `integration.kanban.block_done_if_issue_incomplete`
- `integration.memory.summarize_doc_changes` → `integration.memory.save_sprint_retro` + `save_adr` (both true)
- `rules[]` — **cannot map 1:1**. docsync's code↔doc rules don't exist in mentor. Surface them in the report so the user knows what's being dropped.

## 3. Pick target mode

Heuristic:
- docsync had `rules[]` with multiple doc paths → suggest `development` mode (these projects usually want the Epic/Sprint/Issue hierarchy)
- docsync had only a `doc/SPEC.md` / `doc/CODE_MAP.md` pair → suggest `basic`
- `--mode=basic|development` override takes precedence

Confirm with `AskUserQuestion`:

> docsync had {N} rules across {M} docs. Based on that shape, I suggest **{mode}** mode. OK?
>   - Use {mode}
>   - Use the other mode
>   - Cancel

## 4. Generate draft mentor.yaml

Render to the user before writing:

```
Proposed .claude/mentor.yaml:

schema_version: 1
mode: {chosen}
paths:
  spec: doc/SPEC.md
  ...
agent_behavior:
  bootstrap_docs: [<from docsync>]
  require_issue_context: {true if development else false}
integration:
  kanban:
    enabled: {same as docsync}
  memory:
    save_sprint_retro: {true if docsync had summarize_doc_changes else auto}
  notify:
    enabled: auto

Dropped (not representable in mentor):
  - {list docsync rules by id}
    (mentor doesn't enforce code↔doc mapping; it prescribes workflow.
     If you want per-file rules, keep docsync and mentor doesn't conflict.)
```

Ask `yes / edit / cancel`.

## 5. Write + backup

1. `cp .claude/docsync.yaml .claude/docsync.yaml.bak`
2. Write the new `.claude/mentor.yaml`.
3. Run `workbench-mentor review --format text` — report any immediate violations (likely: missing framework directories, since migration doesn't scaffold them).
4. Suggest `/mentor:init --mode=<chosen>` next to scaffold directories if development mode was picked.
5. Print whether the old file should be removed:
   > Old config backed up at `.claude/docsync.yaml.bak`. Keep or remove — mentor will not read it again.

## Absolute rules

- **Never delete** `.claude/docsync.yaml`. Always rename to `.bak`.
- **Never silently drop** docsync rules without listing them explicitly.
- **Never materialise** framework directories (Epic/Sprint/Issue) from this command — that's `/mentor:init`'s job. This command only translates the YAML.
