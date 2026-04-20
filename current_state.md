# claude-workbench — current state

**Snapshot taken**: 2026-04-21
**Working directory**: `/home/kirin/Desktop/project/claude-kanban` (local dir still carries the old name — see §6.9 for why a local rename was attempted and reverted this session)
**Git branch**: `main`
**Against spec**: [`SPEC.md`](./SPEC.md) v0.1.0 draft
**Roadmap phase**: **0b complete**, Phase 1 (real-project validation) not started.

This file is the live implementation snapshot. Keep it in sync with the code when phases ship — don't let it drift into "aspirational".

---

## 1. Status at a glance

| Plugin / Component | Spec § | Status | Notes |
|---|---|---|---|
| `kanban` plugin | §3 | ✅ **v0.1.0 complete** | Skeleton shipped Phase 0a; commands + automation added Phase 0b |
| `notify` plugin | §4 | 🟡 stub (`plugin.json` + README only) | Phase 2 |
| `memory` plugin | §5 | 🟡 stub (`plugin.json` + README only) | Phase 4 |
| `docsync` plugin | §6 | 🟡 stub (`plugin.json` + README only) | Phase 7 |
| Viewer (`kanban-tui`) | §7.1 | ⬜ not started | v0.2.0 |
| Automation runners | §7.2 | 🟢 cron path ready (runner + installer); git-hook path documented in command only; webhook untouched | Phase 3 will add real `workbench-notify` for fan-out |
| `workbench` meta | §9.1 | 🟡 stub | Real release in Phase 6 |
| `workbench-dev` meta | §9.2 | 🟡 stub meta (deps on `workbench` + `docsync`) | Phase 7 |
| `marketplace.json` | §10.1 | ✅ 6 entries matching SPEC | |
| Schema sync script | §10.2 | ⬜ not automated | Manual copy in place; CI later |
| Release / CI | §12 | ⬜ not started | No `.github/workflows/` yet |
| Docs (`docs/`) | §10 | ⬜ not started | README covers install; no quickstart/composition docs |

Legend: ✅ shipped · 🟢 partial, usable · 🟡 stub · ⬜ absent.

---

## 2. Repo layout (actual, today)

```
claude-workbench/
├── README.md                                ✅ workbench-positioned
├── SPEC.md                                  ✅ merged workbench + docsync + old viewer/automation
├── current_state.md                         ← this file
│
├── .claude-plugin/
│   └── marketplace.json                         ✅ 6 entries
│
├── plugins/
│   ├── kanban/                                  ✅ see §3 below
│   ├── notify/.claude-plugin/plugin.json        🟡 stub + README
│   ├── memory/.claude-plugin/plugin.json        🟡 stub + README
│   ├── docsync/.claude-plugin/plugin.json       🟡 stub + README
│   ├── workbench/.claude-plugin/plugin.json     🟡 stub meta + README
│   └── workbench-dev/.claude-plugin/plugin.json 🟡 stub meta + README
│
└── schema/
    └── kanban.schema.json                       ✅ canonical, mirrored into plugin templates
```

Not yet present (per spec): `viewer/`, `automation/` (canonical source; cron scripts currently live inside `plugins/kanban/scripts/`), `docs/`, `scripts/` (CI helpers), `.github/workflows/`, `CHANGELOG.md`, `LICENSE`.

---

## 3. `plugins/kanban/` — shipped v0.1.0

### 3.1 Contents

```
plugins/kanban/
├── .claude-plugin/plugin.json              ✅ name, version, description
├── skills/
│   └── kanban-workflow/
│       ├── SKILL.md                         ✅ full workflow rules
│       └── references/
│           ├── schema-spec.md               ✅
│           ├── priority-rules.md            ✅
│           └── dependency-rules.md          ✅
├── commands/
│   ├── init.md                              ✅ /kanban:init
│   ├── next.md                              ✅ /kanban:next
│   ├── done.md                              ✅ /kanban:done
│   ├── block.md                             ✅ /kanban:block         (Phase 0b)
│   ├── status.md                            ✅ /kanban:status
│   └── enable-automation.md                 ✅ /kanban:enable-automation (Phase 0b)
├── hooks/hooks.json                         ✅ SessionStart, UserPromptSubmit, PreToolUse, PostToolUse
├── scripts/
│   ├── kanban-guard.sh                      ✅ blocks direct edits to kanban.json
│   ├── kanban-autocommit.sh                 ✅ standalone commits + sibling fan-out stubs
│   ├── kanban-session-check.sh              ✅ DOING/BLOCKED context injector (Python primary, jq fallback)
│   ├── cron-runner.sh                       ✅ headless `claude -p` runner  (Phase 0b)
│   └── install-cron.sh                      ✅ idempotent crontab installer (Phase 0b)
└── templates/
    ├── kanban.schema.json                   ✅ copy of schema/kanban.schema.json
    ├── kanban.empty.json                    ✅
    └── kanban.example.json                  ✅ 4 sample tasks across all 4 columns
```

### 3.2 What works right now

- `/kanban:init [--with-examples]` copies template + schema into a fresh project.
- `/kanban:status` is read-only and reliable.
- `/kanban:next` picks the top-ranked ready TODO and transitions to DOING.
- `/kanban:done [task-id] [--note=…]` closes the DOING task and reports which downstream tasks were unblocked.
- `/kanban:block <task-id> --reason=…` requires a reason; refuses on DONE tasks.
- `/kanban:enable-automation` walks the user through cron or git-hook install.
- `kanban-guard.sh` blocks direct edits of `kanban.json`. **Tested end-to-end**: Edit/Write → exit 2 with redirect message; Bash → exit 0.
- `kanban-session-check.sh` emits `hookSpecificOutput.additionalContext` with DOING (and BLOCKED in full mode). **Tested** against a scratch fixture.
- `kanban-autocommit.sh` produces commits like `kanban: task-001 TODO→DOING` when only `kanban.json` is dirty. **Tested end-to-end** on a scratch repo.
- `install-cron.sh` is idempotent (refuses duplicate install for the same project dir), installs runner to `~/.claude-workbench/bin/`, and tags the crontab entry for easy removal.

### 3.3 Known limitations / parked work

- No `/kanban:unblock` — a BLOCKED task currently requires manual YAML editing to return to TODO. Spec notes this; v0.2.0.
- `kanban-session-check.sh` does NOT yet do `git fetch` + remote-drift detection (SPEC §3.6 lists this as future). Current impl only reads the local file.
- `cron-runner.sh` uses a naive `"/kanban:next and execute …"` prompt. For serious long-running autonomous use we probably need a purpose-built `runner-prompt.md`.
- Autocommit and session-check both rely on `python3`; fallback paths exist for `jq` but NOT for pure POSIX. If a user's system has neither Python nor jq, integration fan-out becomes silent no-op (not a hard failure).
- Schema validation is structural only — no runtime check of `required_if` semantic fields (those live in docsync).

### 3.4 Open interpretation choices embedded in code

| Decision | Where | Why |
|---|---|---|
| Autocommit matcher includes `Write|Edit|MultiEdit` in addition to `Bash` | `hooks/hooks.json` | So `/kanban:init`'s Write also auto-commits; SPEC §3.6 shows only `Bash` but that leaves init-time commit unplumbed |
| Autocommit does NOT pass `--no-verify` | `kanban-autocommit.sh` | Respects user's pre-commit hooks; failure is silent (skips commit) rather than forcing past linters |
| Standalone-only commits | `kanban-autocommit.sh` | Refuses if any other file is dirty; avoids tangling kanban transitions with code changes |
| Python3 primary, jq fallback | `kanban-session-check.sh`, `kanban-autocommit.sh` | Python is more portable than jq on modern Linux/macOS; both hook sites need to stay robust |

---

## 4. Capability-detection wiring (Phase 0a)

Both `kanban-session-check.sh` and `kanban-autocommit.sh` open with:

```bash
has_plugin() { command -v "workbench-$1" >/dev/null 2>&1; }
HAS_NOTIFY=0;  has_plugin notify  && HAS_NOTIFY=1
HAS_MEMORY=0;  has_plugin memory  && HAS_MEMORY=1
```

Dispatch blocks for `workbench-notify` and `workbench-memory` exist inside `kanban-autocommit.sh` but are guarded and currently no-op (neither CLI is on PATH). When Phase 2 / Phase 4 ship the CLIs into `~/.claude-workbench/bin/`, these blocks activate automatically without a code change.

**Caveat surfaced in SPEC §8.7**: `command -v` only detects installation, not configuration. The planned fix is a `workbench-<name> --health` contract returning exit 0 when ready — deferred to Phase 2 when notify is the first real consumer of the pattern.

`HAS_DOCSYNC` is mentioned in SPEC §3.7 but not yet wired in any shipped script (Phase 7).

---

## 5. What's verified

| Verification | Tool used | Result |
|---|---|---|
| All JSON files parse | `python3 -m json` per file | ✅ 10/10 (`marketplace.json`, all `plugin.json`, hooks, templates, schema) |
| Shell script syntax | `bash -n` | ✅ all five |
| Guard hook blocks `kanban.json` | manual `echo JSON \| bash guard.sh` | ✅ exit 2 on Edit/Write targeting kanban.json; exit 0 otherwise |
| Session-check emits SessionStart JSON | scratch fixture `/tmp/kanban-test/` | ✅ DOING+BLOCKED in full mode; DOING-only in `--lightweight` |
| Autocommit produces readable commit message | scratch repo `/tmp/kanban-ac-test/` | ✅ `kanban: task-001 TODO→DOING` |

**Not verified**:

- Schema conformance via `jsonschema` (no `pip` on this host; deferred to CI).
- Claude Code actually loading the plugin (requires `claude` CLI).
- `install-cron.sh` end-to-end (would modify user crontab — opt-in via the slash command).
- Any integration-plugin fan-out paths (no notify/memory binaries to flip `HAS_*` flags).

---

## 6. Gaps relative to current SPEC.md

These are follow-ups to close to make the repo match what the merged SPEC describes:

1. **Missing top-level dirs** per §10: `automation/` (canonical runner source — today it only exists inside the kanban plugin), `viewer/`, `docs/`, `scripts/` (CI), `.github/workflows/`, `CHANGELOG.md`, `LICENSE`.
2. **No real `workbench-notify` / `workbench-memory` CLIs** — hence capability detection always short-circuits.
3. **No `--health` subcommand contract** for sibling detection.
4. **`kanban-session-check.sh` lacks `git fetch`** step the spec promises.
5. **Viewer doesn't exist** — spec promises Textual TUI in `viewer/`.
6. **`docsync` is stub-only** — full plugin is Phase 7.
7. **Embedding-model install UX for memory** unresolved (Open Question 11).
8. **Schema / automation sync scripts (§10.2, §10.3)** not written — current schema copy was manual.
9. **Git remote not yet configured** — local repo has no remote; once pushed, it should land at `github.com/kirin/claude-workbench`.
10. **Local directory name is still `claude-kanban`** — the upstream name everywhere (marketplace, schema `$id`, plugin homepages, `~/.claude-workbench/` CLI dir) is `claude-workbench`, but the on-disk directory wasn't renamed this session. See §6.9 below.

**Closed in this session**:
- ✓ `marketplace.json` now has 6 entries matching SPEC §10.1.
- ✓ `plugins/docsync/` and `plugins/workbench-dev/` stubs created (plugin.json + README each).
- ✓ All internal references (schema `$id`, plugin homepages, marketplace name) use `claude-workbench`; only the local filesystem dir retains the old name.

### 6.9 Note on the attempted local rename

The plan was to `mv claude-kanban claude-workbench` this session. The Claude Code harness binds `CLAUDE_PROJECT_DIR` to the session's original project path at startup and **re-materialises `.claude/` under that exact path whenever it goes missing** — so an `mv` mid-session produces a split-brain state: the content moves, but the harness writes fresh settings to the old name and subsequent `Bash` calls fail with "path does not exist" until the harness recreates the directory.

The merge was reverted (`rsync` + `rm -rf` of the new name) so the session keeps working. The directory rename is a **between-sessions** operation: close Claude Code, `mv` on disk, optionally configure the git remote as `git@github.com:kirin/claude-workbench.git`, restart Claude Code in the new dir. Nothing in the plugin code depends on the local directory's name — all stable references use the upstream `claude-workbench` identifier.

---

## 7. Open Questions carried forward

From SPEC §14, the ones most load-bearing on next phases:

- **#3 Concurrent headless Claude** — if the user enables cron on multiple machines against the same repo, current `flock` is per-machine only. Phase 1 validation will expose whether this matters.
- **#8 Notify rate limiting** — needs a concrete UX before Phase 2 lands (otherwise cron + notify ships alert fatigue).
- **#11 Memory embedding install UX** — blocks Phase 4 start; SessionStart can't synchronously download 80 MB.
- **#12 / #13 docsync granularity + semantic conditions** — design questions for Phase 7.

None block Phase 1 (manual real-use validation of kanban v0.1.0).

---

## 8. Suggested next steps

Ordered by leverage, not by strict SPEC sequence:

1. **Phase 1 validation** — use kanban v0.1.0 on a real project for a week. Log pain points in a scratch file (not in SPEC) before touching notify. The longer we defer validation, the more Phase 2 designs on shaky assumptions.
2. **Close the trivial gaps** from §6 above: add `docsync` / `workbench-dev` stubs to `marketplace.json`; drop a `LICENSE` file; seed `CHANGELOG.md`.
3. **Decide repo-rename timing** — do it before the first push to GitHub, not after. Rename is cheap locally; expensive after remote clones exist.
4. **Prototype `workbench-notify --health`** before writing notify proper. Settles the capability-detection contract question cheaply.
5. **Stop extending SPEC**, start adding to `docs/quickstart.md`. SPEC has front-loaded a lot; real users want a 1-page getting-started, not §§1–15.

---

*End of current_state.md*
