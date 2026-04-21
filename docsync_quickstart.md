# docsync — quickstart

> Keep code changes and documentation in sync. Config-driven (`.claude/docsync.yaml`), not prompt-driven. Replaces the common "hardcoded rules in CLAUDE.md" pattern with something structured, versioned, and team-reviewable.

*See [`SPEC.md §6`](./SPEC.md) for full design, [`plugins/docsync/`](./plugins/docsync) for the code.*

---

## 0. Prerequisites

- Claude Code installed.
- Your project is a **git repo** with some commit history — the init flow dry-runs rules against the last ~20 commits, which is what makes the config concrete.
- Shell rc contains:
  ```bash
  export PATH="$HOME/.claude-workbench/bin:$PATH"
  ```
- Recommended: `pip install pyyaml`. The plugin's fallback YAML parser handles the shipped templates, but if you hand-edit the YAML with anchors, flow syntax, or multi-line block scalars, PyYAML is needed.

---

## 1. Install

Inside Claude Code, **in the project you want docsync to govern** (it's per-project):

```
> /plugin marketplace add kirinchen/claude-workbench   # skip if already added
> /plugin install docsync@claude-workbench
```

---

## 2. The init flow (scan → interview → dry-run → write)

```
> /docsync:init
```

This is the important bit. The command runs five phases — don't just smash yes on everything, Phase 4 is what makes the rules actually fit your repo.

### Phase 1 — Scan (silent)
Detects:
- Project type: Rust monorepo (`Cargo.toml` + `[workspace]`) · JS monorepo (`pnpm-workspace.yaml` / `lerna.json`) · Python (`pyproject.toml`) · Go (`go.mod`) · mixed.
- Code modules: top-level dirs, skipping `.git`, `node_modules`, `target`, `.venv`, `dist`, etc.
- Existing docs: `doc/`, `docs/`, `README*`, `ARCHITECTURE*`, `CODE_MAP*`, `SPEC*`, per-module READMEs.

Pass `--from-existing-claude-md` to also parse mapping tables out of your current `CLAUDE.md` and pre-fill the interview answers.

### Phase 2 — Interview (≤ 3 questions per batch, via `AskUserQuestion`)
You'll be asked, in batches:
1. **Bootstrap docs** (multi-select) — which docs should Claude be reminded to read at the start of each session?
2. **Module → doc mapping** (per-module, single-select) — global CODE_MAP section / module README / both / neither / custom.
3. **Enforcement**: `warn` (recommended, default) / `block` (hard gate via kanban integration) / `silent` (only `/docsync:check` surfaces pending).
4. **Skip conditions**: `bug_fix_only` / `internal_refactor` / `test_only` / `comment_formatting_only`.
5. **Integration** (only asked if kanban / memory are installed): DONE gate? memory summary?

### Phase 3 — Propose
Claude renders the full draft YAML in a code block. Reply:
- `yes` → proceed.
- `edit rules` (or `edit bootstrap_docs`, `edit enforcement`, …) → loops back.
- `cancel` → abort, nothing written.

### Phase 4 — Dry-run (the killer feature — **don't skip**)
Runs against your last 20 commits, picks 3 representative ones (cross-module / doc-heavy / code-only), and shows what the rules **would have** flagged:

```
commit abc123 "refactor grid pricing"
├ changed: position-manager/src/grid.rs
└ would prompt: doc/CODE_MAP.md (§position-manager)
                position-manager/README.md (required_if: params_changed)

commit def456 "fix typo in comment"
├ changed: common/src/types.rs
└ would skip (skip_condition: comment_formatting_only)
```

If Phase 4 reads wrong — too noisy, wrong skips, missed a module — go back to Phase 2/3 and fix. The YAML is only written after you confirm this.

### Phase 5 — Write
1. `.claude/docsync.yaml` is written.
2. `install-cli.sh` links `workbench-docsync` into `~/.claude-workbench/bin/`.
3. You're asked whether to `git commit` the YAML (yes by default — it's team-shareable config).

---

## 3. Verify

Inside Claude:
```
> /docsync:validate                      # checks the YAML shape
> /docsync:rules src/api/handler.py      # "which rules match this file?"
> /docsync:check --since HEAD~5          # "any pending syncs in last 5 commits?"
> /docsync:bootstrap                     # lists bootstrap_docs
```

Outside Claude:
```bash
workbench-docsync --health
workbench-docsync rules --format text
workbench-docsync check --since HEAD~5 --format json
#  -> exit 0 if clean, exit 2 if pending (this is the contract used by the
#     kanban DONE gate when enforcement=block)
```

---

## 4. How it runs during a session

| Hook | When | What it does |
|---|---|---|
| SessionStart | session begins | Emits `additionalContext` reminding Claude to read `bootstrap_docs` before any code edit |
| PostToolUse · Edit/Write/MultiEdit | after each code edit | Matches the edited file against rules; if `enforcement=warn`, injects `additionalContext` listing the doc(s) Claude should update; `silent` skips |
| Stop | session ends | Aggregates all code changes, reports pending syncs, optionally fans out a summary into `workbench-memory` if memory integration is enabled |

So in the middle of a session:
1. You edit `src/api/handler.py`.
2. Next Claude turn sees: `docsync: \`src/api/handler.py\` matched 1 rule(s). Consider updating: doc/api.md (rule: api)`.
3. Claude reads the doc, updates it, and (per the skill) explains its reasoning — or declares the change matches a `skip_condition` and justifies.

---

## 5. When Claude decides to skip

The skill teaches Claude judgement for:
- **`skip_conditions`** — when a change is `bug_fix_only`, `internal_refactor`, `test_only`, or `comment_formatting_only`, the doc update is genuinely not needed. Definitions are strict (see [`plugins/docsync/skills/docsync-workflow/references/skip-decision-tree.md`](./plugins/docsync/skills/docsync-workflow/references/skip-decision-tree.md)).
- **`required_if`** — a rule can declare `required_if: api_changed` etc. If the semantic condition doesn't apply, the doc isn't required. Claude must state the condition and why out loud.

Over-skipping is the failure mode this plugin exists to prevent. If a skip looks too aggressive in practice, re-run `/docsync:init --reset` and trim `skip_conditions`.

---

## 6. Integration with sibling plugins

Set in `.claude/docsync.yaml`:

```yaml
integration:
  kanban:
    block_done_if_pending: false      # flip to true to gate /kanban:done
  memory:
    summarize_doc_changes: true       # Stop hook writes doc summaries to memory
```

- **kanban gate**: when true and `enforcement=block`, `/kanban:done` calls `workbench-docsync check --since $(git merge-base HEAD main) --format json` — exit 2 blocks the transition until docs are in sync. (Note: kanban-autocommit doesn't wire this call yet as of v0.1.0 — this is the last piece of the three-way integration.)
- **memory summary**: if `workbench-memory` is on PATH, each session's doc-update summary is saved as a memory entry for future recall. Memory is still Phase 4 → this is inert until memory ships.

---

## 7. Tuning / iterating

Docsync **never self-edits** `.claude/docsync.yaml` — the user owns it. To change rules:

```
> /docsync:init --reset
```

Or edit by hand and run `/docsync:validate`. The structural checks that fire:
- `schema_version` must be `1`.
- `enforcement` must be `silent | warn | block`.
- Rule ids must be unique.
- `required_if` must be one of `architecture_changed`, `api_changed`, `params_changed`, `schema_changed`.
- Every `bootstrap_docs` path must exist on disk.

---

## 8. Templates shipped in the box

If init doesn't match your layout well, three starter templates live in [`plugins/docsync/templates/`](./plugins/docsync/templates/):
- `docsync.example.yaml` — Rust monorepo (Cargo workspaces)
- `docsync.python.yaml` — Python project (`pyproject.toml`)
- `docsync.js.yaml` — JS monorepo (pnpm / lerna)

You can copy one to `.claude/docsync.yaml`, tweak, and `/docsync:validate`.

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `workbench-docsync: cannot locate workbench-docsync.py` | Shim installed via `ln -s` but symlink-resolution failed on your shell | Fixed in v0.1.0 shim; re-run `bash ${CLAUDE_PLUGIN_ROOT}/scripts/install-cli.sh` or set `DOCSYNC_CLI_PY=/full/path/workbench-docsync.py` |
| `docsync: no .claude/docsync.yaml found` | Run from outside the project dir, or init never completed | `cd` into the project root; re-run `/docsync:init` |
| `/docsync:validate` fails with "unknown required_if=..." | hand-edit introduced a typo or an invalid value | Use one of: `architecture_changed`, `api_changed`, `params_changed`, `schema_changed` |
| PostToolUse warn fires on every edit, feels like nagging | Rules too broad, or `skip_conditions` too narrow | `/docsync:init --reset`; in Phase 2 add more `skip_conditions` or tighten the rule globs |
| YAML parse error after hand-edit | Using YAML features the fallback parser doesn't support (anchors, flow syntax) | `pip install pyyaml` |
| Pending stays on `README.md (required_if: api_changed)` even though you DIDN'T change the API | The semantic condition is Claude's judgement; if the doc genuinely wasn't needed, say so in chat — the engine doesn't auto-resolve this | Accept as-is or rewrite the rule to drop `required_if` |
| `.claude/docsync.yaml` not showing up in git | `.gitignore` has `.claude/` or `.claude/*` | Add `!.claude/docsync.yaml` as a negated rule |

---

## 10. Uninstall

```
> /plugin uninstall docsync@claude-workbench
```

Leaves behind:
- `.claude/docsync.yaml` (your project's config — version-controlled).
- `~/.claude-workbench/bin/workbench-docsync` (symlink, now dangling).

To fully clean:
```bash
rm -f ~/.claude-workbench/bin/workbench-docsync
rm -f .claude/docsync.yaml    # only if you want to forget the mapping
```

---

## 11. Next steps

- Add `kanban`: [`kanban_quickstart.md`](./kanban_quickstart.md). Enables the DONE gate integration.
- Add `notify`: [`notify_quickstart.md`](./notify_quickstart.md). When `enforcement=block` fires, the blocked transition pushes via notify.
- Read [`plugins/docsync/skills/docsync-workflow/references/`](./plugins/docsync/skills/docsync-workflow/references/) to see how Claude decides when `skip_conditions` and `required_if` apply.
