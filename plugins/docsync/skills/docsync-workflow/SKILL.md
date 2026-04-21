---
name: docsync-workflow
description: Use whenever `.claude/docsync.yaml` exists in the project, when the user edits code files that likely map to living docs (CODE_MAP, ARCHITECTURE, per-module README), or when any `/docsync:*` command is invoked. This skill governs the config-driven code↔doc sync loop.
---

# Docsync Workflow

You operate alongside `.claude/docsync.yaml`, a versioned, project-local config that declares which docs are kept in sync with which code. The plugin enforces the rules through hooks; you enforce the **judgement** — when `required_if` conditions apply, when `skip_conditions` apply, how to write a good doc update.

## 0. Absolute rules

1. **Never self-edit `.claude/docsync.yaml`.** The user owns it. Edits go through `/docsync:init` (re-init) or manual editing outside Claude Code.
2. **Never skip a `required: true` doc to save time.** If the rule fires, update the doc, or move the code change to BLOCKED via `/kanban:block` and explain.
3. **Never fabricate `required_if` conditions** to exempt yourself. Each value (`architecture_changed`, `api_changed`, `params_changed`, `schema_changed`) is defined in `references/skip-decision-tree.md`.
4. **Never write doc updates that describe *what* the code change was** — describe what the **module now does**. Docs document intended state, not diffs.
5. **Never rely on hook output for the full picture.** If the PostToolUse guard fires on one file, re-check with `workbench-docsync check --since HEAD~1` before finishing, because later edits in the same session may have added more pendings.

## 1. The lifecycle

```
SessionStart  → docsync-bootstrap.py  → systemMessage: "read these docs first"
                                          ▲
                                          │ bootstrap_docs from YAML
code edit     → PostToolUse Edit/Write    │
                     │                    │
              docsync-guard.py ──► match rules ──► warn / block
                                                      │
                                                  you update doc
                                                      │
Stop          → docsync-finalcheck.py ──► pending list + memory fan-out
```

## 2. When to read docs

- **Always** at session start, from the `bootstrap_docs` list. The SessionStart hook surfaces them — open them before first code edit.
- **Before** editing a module, read the module's own `README.md` if it exists and is in a rule.
- **After** a `docsync-guard` warning, read the doc it pointed at before updating it — don't paste blind changes.

## 3. When to update docs (and when not to)

Default: if a rule fires and the mapped doc has `required: true`, update it.

Reasons NOT to update (evaluate in order — first match wins):

1. The change matches a `skip_conditions` value declared in YAML (`bug_fix_only`, `internal_refactor`, `test_only`, `comment_formatting_only`). See `references/skip-decision-tree.md` for when each applies — bugs that *change behaviour* are NOT `bug_fix_only`.
2. The `doc` has `required: false` and no `required_if` — it's an opt-in.
3. The `doc` has `required_if: <condition>` and the condition does **not** apply to this change. Do this analysis transparently: quote the rule, state the condition, justify.

If none of these apply, update the doc.

## 4. How to write a good doc update

See `references/update-patterns.md` for per-doc templates. Common rules:

- Write in present tense, describing the module's current responsibility.
- Do not say "recently changed to" or "as of 2026-04-21" — the git history carries that.
- If the doc has a section, update only that section. Don't rewrite unrelated sections.
- Keep diffs minimal. A doc update is not a refactoring opportunity.

## 5. Rule conflict resolution

When multiple rules match the same changed file:

1. **Union the required docs.** If two rules map to different docs, update both.
2. **If two rules map to the SAME doc but different sections**, update the section whose rule id sorts first. Document the choice inline if ambiguous.
3. **Never** silently pick one rule over another without noting it.

## 6. Escalation

If you genuinely cannot write a good doc update — the code change is too ambiguous, the doc structure doesn't match the new reality, etc.:

- **Prefer asking the user** via a comment (if kanban is installed: append to the task; else surface in the final response).
- **Prefer BLOCKED** over shipping a hallucinated doc update.
- Never "update" a doc with a vague "refactored X" sentence to satisfy the hook.

## 7. Integration with siblings

Only touch these paths when the YAML explicitly enables them:

- `integration.kanban.block_done_if_pending: true` → `/kanban:done` is gated on `workbench-docsync check` returning 0. Don't invoke this yourself; kanban-autocommit.sh calls it.
- `integration.memory.summarize_doc_changes: true` → the Stop hook summarises doc changes into memory. Don't call `workbench-memory` directly from your normal workflow.

## 8. CLI you can call

These are safe for you to run inside a session:

```bash
workbench-docsync match path/to/file.py         # "which rules apply to this?"
workbench-docsync check --since HEAD             # "what's pending right now?"
workbench-docsync rules                          # "show me the rule table"
workbench-docsync validate                       # "is the YAML well-formed?"
```

`workbench-docsync summarize` is for hooks; don't invoke it manually.

## 9. References

- `references/update-patterns.md` — templates per doc type (CODE_MAP, ARCHITECTURE, module README).
- `references/skip-decision-tree.md` — when each `skip_conditions` / `required_if` value applies.
