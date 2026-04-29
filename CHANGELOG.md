# Changelog

All notable changes to claude-workbench plugins are tracked here. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
each plugin follows [Semantic Versioning](https://semver.org/) independently.

The pre-commit hook (`.githooks/pre-commit`) enforces that any change under
`plugins/<name>/` is paired with a version bump in both that plugin's
`plugin.json` and the matching entry in `.claude-plugin/marketplace.json`.
Repository-level files (READMEs, RELATED.md, top-level scripts) are not
plugin-versioned but are noted under the date they shipped.

This log starts at the first patch series after the v0.1.0 plugin release.
For earlier history, see the git log.

## Unreleased

## 2026-04-30 (later)

### Added
- **kanban 0.3.0** — compound transitions for Jira mode. Closes #4.
  Replaces the v0.2 flat `statusMap` + `labelFallback` (which couldn't
  express realistic Jira workflows where multiple canonical states share
  one Jira status) with a richer per-canonical record:

  ```json
  "transitions": {
    "BLOCKED": { "status": "In Progress",
                 "addLabels": ["kanban:blocked"] },
    "REVIEW":  { "status": "In Progress",
                 "addLabels": ["kanban:review"],
                 "assignee": { "accountId": "..." } }
  }
  ```

  Highlights:
  - `lib/transitions.py` — DSL parser, auto-suggester, legacy migrator,
    and the read-back disambiguation algorithm (most-specific match wins).
  - **DSL** — users define transitions in plain text:
    `BLOCKED > In Progress + Label`,
    `REVIEW > In Progress + label + Assignee to me`,
    `CANCELLED > DONE + label` (UPPERCASE = canonical self-reference).
  - **Non-English status matching** (closes Bug #1 in #4) — the
    suggester uses Atlassian's `statusCategory.key` as a fallback signal
    so `進行中` / `完成` / `Backlog` are recognised even when the name
    isn't in the English keyword list.
  - **`/kanban:initjira` step 3 rewritten** — runs the suggester, prints
    the auto-detected mapping, then asks the user for a DSL block. The
    `--partial` flag is gone; partial workflows are now expressed
    naturally by sharing a status across canonicals.
  - **`drivers/jira.py`** — compound write order: status transition first
    (skip if already in target), then PUT labels (add/remove), then PUT
    assignee. Partial-failure tracking with audit comment. Anti-self-
    approve unchanged in semantics.
  - **Auto-migration on load** — existing v0.2.x kanban.json files
    (statusMap + labelFallback + partial) are converted in-memory to
    transitions form by `kanban_io.load`. Lossless on the writer's
    intent. First write upgrades the file in place; legacy keys dropped.
  - **New CLI subcommands**: `parse-transitions-dsl`, `set-transitions`.
    Existing `build-status-map` returns the richer suggestion shape.
  - **Per-machine board cache** — `~/.claude-workbench/kanban-boards/<host>__<KEY>__<id>.json`
    stores a board's `transitions` block, AP-field config, and AP roster.
    `/kanban:initjira` step 2.5 looks it up first; on hit the user can
    reuse without re-entering the DSL. `write-backend` writes the cache
    as a side-effect; `register-ap` syncs the AP roster so sibling repos
    pick up newly-registered APs without re-querying Jira. New
    subcommands `read-board-cache`, `list-board-cache`.
  - **Security**: removed `--dsl-file` from `parse-transitions-dsl`
    (would have allowed an LLM-driven misuse to reflect arbitrary file
    contents — including `~/.claude-workbench/.env` — back into the chat
    transcript via the parser's verbatim error messages). DSL parser
    errors now report `line N` plus a 32-char redacted snippet, never
    the full line.
  - **Tests**: 28 new cases across `test_phase7.py` (DSL parser,
    suggester, migration, disambiguation, compound write, CLI) and
    `test_phase8.py` (board cache: round-trip, AP roster sync,
    multi-repo sharing, missing/corrupt handling). All 8 phase suites
    (86 tests) green.
  - Workbench bundle: `0.0.2 → 0.0.3`, kanban dep `^0.2.0 → ^0.3.0`.

## 2026-04-30

### Fixed
- **kanban 0.2.2** — `/kanban:initjira` no longer fails with
  `ModuleNotFoundError: No module named 'kanban'` under the marketplace
  install layout (`<cache>/<repo>/kanban/<version>/...`). Both helpers
  now anchor `sys.path` at `parents[1]` (the directory holding `lib/`
  and `drivers/`) and use absolute imports `from lib import …` /
  `from drivers import …`. The driver modules' relative imports
  (`from ..lib import …`) — which fail when `drivers` is loaded as a
  top-level package — are converted to absolute. Tests updated to the
  same canonical sys.path. Verified end-to-end against a synthetic
  marketplace layout. Closes Bug B in #3.
- **kanban 0.2.1** — two bugs filed in #3:

  - **(Bug A)** local-mode mutation commands (`/kanban:init`,
    `/kanban:next`, `/kanban:done`, `/kanban:block`) no longer trip
    `kanban-guard.sh` and recover via Bash. They now route through a new
    `scripts/kanban_local.py` helper that writes via atomic `os.replace`
    through `kanban_io.save()` — same architecture pattern as the
    Jira-mode commands' `jira_setup.py`. Result: clean execution, no
    PreToolUse rejection messages mid-flow. The helper enforces
    dependency / priority / DONE-immutability rules in one place; slash
    commands shrink to thin orchestrators. New `scripts/test_phase6.py`
    (11 cases) covers init / next / done / block / status end-to-end.

  - **(Bug B)** `/kanban:initjira` no longer fails with
    `ModuleNotFoundError: No module named 'kanban'` under the marketplace
    install layout (`<cache>/<repo>/kanban/<version>/...`). Both helpers
    now anchor `sys.path` at `parents[1]` (the directory holding `lib/`
    and `drivers/`) and use absolute imports `from lib import …` /
    `from drivers import …`. The driver modules' relative imports
    (`from ..lib import …`) — which fail when `drivers` is loaded as a
    top-level package — are converted to absolute. Tests updated to the
    same canonical sys.path. Verified end-to-end against a synthetic
    marketplace layout.

## 2026-04-29

### Added
- **kanban 0.2.0** — Jira Cloud as a second backend driver. The plugin
  keeps the same `/kanban:*` command surface (status, next, done, block);
  the storage layer is the only thing that changes when a project opts in.
  Highlights:
  - **Driver abstraction** — `plugins/kanban/drivers/{base,local,jira}.py`
    behind a single `Driver` Protocol. `kanban.json` writers always emit
    the new `version: "0.2"` shape; readers still accept legacy
    `schema_version: 1` files transparently.
  - **`/kanban:initjira`** — five-step setup (credentials → board →
    workflow check → AP custom field → first AP registration), plus an
    optional migration step that imports existing local tasks into Jira
    and a final MCP-conflict scan.
  - **Agent Property (AP)** — single-select Jira custom field that
    distinguishes which AI agent owns a card. Slash commands
    `/kanban:register-ap`, `/kanban:assign-ap`, `/kanban:whoami`. Registry
    lives in Jira (source of truth) with a cached mirror in
    `kanban.json#backend.jira.ap.registered` and per-repo identity in
    `.claude/kanban-agent.json`.
  - **Anti-self-approve (SPEC §8)** — `JiraDriver.transition` refuses
    DONE when `task.ap == current_repo_ap`. Raises `SelfApproveRefused`;
    surfaced to slash commands as exit code 2 + `kind: self-approve`.
  - **Auto-detection** — `UserPromptSubmit` and `SessionStart` hooks scan
    for Jira card keys / URLs filtered by `projectKey`, run a precheck
    (cached 30s under `.claude/.kanban-cache/`), and inject context above
    the agent's prompt. Cache is invalidated on every plugin write.
  - **`/kanban:sync`** and **`/kanban:question`** — explicit refresh,
    Q-prefix comment + transition to BLOCKED.
  - **Comment prefix grammar (§9)** — agent comments include
    `**[<ap>] [Q|A|C|S]**` round-trip parsable; reader resolves AP
    attribution from the prefix when present.
  - **Bundled skills** — `kanban-jira-agent` (agent-facing rules) and
    `kanban-jira-setup` (owner-facing walkthrough). The existing
    `kanban-workflow` skill scopes itself to `backend.driver = "local"`.
  - **MCP conflict scan** — surfaces `atlassian|jira|rovo|mcp-atlassian`
    MCP servers configured at user / project / `.mcp.json` scope. Warning
    only — agent-side compliance is via the `kanban-jira-agent` skill.
  - **Graceful degradation** — `--partial` opts into label substitutes
    (`kanban:blocked` / `kanban:review` / `kanban:cancelled`) when the
    Jira workflow lacks canonical statuses. Round-trip safe.
  - **48 mocked regression tests** across five phase suites, runnable via
    `plugins/kanban/scripts/test_all.sh`.
  - Backwards-compatible: existing v0.1.x `kanban.json` files (no
    `backend` block, `schema_version: 1`) continue to work as local mode
    with no migration. The first write upgrades the file in place.

## 2026-04-28

### Added
- **mentor 0.2.2** — `workbench-mentor upgrade --diff <FILE>` produces a
  unified diff between a repo file and its bundled template. Closes the
  one remaining gap in the upgrade flow: `--apply` only fills missing
  files (never overwrites), so `--diff` is the path for cherry-picking
  template updates into already-existing files. Mutually exclusive with
  `--apply`. Available as a slash command via `/mentor:upgrade --diff <file>`.
- `RELATED.md` + `RELATED_zhtw.md` — ecosystem positioning. Compares
  claude-workbench against six neighbouring projects
  (Norman-else/claude-workbench GUI, blackwell-systems/claudewatch,
  wshobson/agents, mikeypotter/claude-agent-os, valllabh/claude-agents,
  iannuttall/claude-agents) and explicitly maps each to a different
  category (skills, runtime, analytics, GUI, infrastructure).
- `CHANGELOG.md` (this file).

## 2026-04-26

### Added
- **mentor 0.2.0** — `/mentor:upgrade` slash command and
  `workbench-mentor upgrade` CLI subcommand. Diffs the active framework's
  `scaffold` rules against the user's repo, lists missing required /
  optional files, and (with `--apply`) fills them from the bundled
  templates. Existing files are never overwritten and `.claude/mentor.yaml`
  is never touched. Cross-mode template borrowing
  (`development` → `basic/templates/task.md`) is supported. Default-paths
  are remapped to user-configured `paths.*` via prefix substitution.
- `.githooks/pre-commit` — Python hook that blocks commits touching
  `plugins/<name>/` without a paired version bump (plugin.json and
  marketplace.json must both change relative to HEAD and agree on the new
  value). New plugins (no HEAD version) and deletions are exempt. Activate
  with `git config core.hooksPath .githooks`. Bypass with `--no-verify`
  when intentional.

### Changed
- **mentor 0.2.1** — `workbench-mentor review` now appends a `Tip:` line
  (and a `hints[]` array in JSON mode) pointing at `/mentor:upgrade`
  whenever it finds `missing_doc` violations, closing the
  review → upgrade workflow loop.
- `commands/review.md` updated so `missing_doc` fix-up leads with
  `/mentor:upgrade`; `/mentor:new <type>` is now correctly scoped to
  individual doc instances (a new Epic, Sprint, Issue, or ADR), not
  framework-level scaffold.

### Documentation
- README EN + zh-TW: `## Update` / `## 更新` section documenting the
  two-layer update flow (per-machine plugin code refresh via
  `/plugin marketplace update` + project scaffold via `/mentor:upgrade`),
  plus a `## Development setup` / `## 開發者設定` block explaining how
  to enable the bundled pre-commit hook.

## 2026-04-25

### Fixed
- **kanban 0.1.1**, **notify 0.1.1**, **mentor 0.1.1** — wrap
  `hooks.json` content in a top-level `hooks` key to match Claude Code
  2.1.x's plugin schema. Flat layout was rejected with
  `path: ["hooks"], expected: record, received: undefined` at install
  time. Without this fix, plugin install reported "1 error during load"
  and the hooks count stayed at 0.
- **mentor 0.1.1** — `mentor-finalcheck.py` (Stop hook) now writes
  `systemMessage` instead of `hookSpecificOutput.additionalContext`. The
  Stop event is not in Claude Code's allow-list for `hookSpecificOutput`;
  the previous output failed schema validation at session end with
  "Invalid input" at the root.

### Documentation
- README EN + zh-TW: project status table updated to reflect the bumped
  versions (`v0.1.1 ready` / `v0.1.1 可用`).
