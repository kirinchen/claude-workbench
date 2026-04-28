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
