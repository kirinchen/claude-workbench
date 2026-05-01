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

## 2026-05-01 (clickable doc links)

### Added
- **kanban 0.3.7** — `resolve-doc-link` helper turns a repo-relative
  doc path into a clickable GitHub URL for Jira comments. First piece
  of the `kanban × mentor` integration line from SPEC §13.

  Motivation: when the agent posts `please see epic/AGENT-001-foo.md`
  to Jira, the human reading the comment can't click — they have to
  navigate GitHub manually. With this helper, the agent posts
  `https://github.com/<owner>/<repo>/blob/main/epic/AGENT-001-foo.md`
  instead. The skill (`kanban-jira-agent`) carries the rule.

  Highlights:
  - New CLI subcommand:
    ```
    resolve-doc-link --kanban-path P --doc-path 'epic/X.md' [--branch B]
    ```
    Returns `{ok, url, exists, branch, host, owner, repo, docPath}`.
  - Reads `git remote get-url origin`, parses both HTTPS and SSH GitHub
    forms (`https://github.com/owner/repo` and
    `git@github.com:owner/repo.git`).
  - Branch resolution: explicit `--branch` > current git branch > `main`.
  - Doc-path strips leading `/` and `./`; refuses `..` traversal even
    though GitHub itself would 404.
  - `exists` flag reflects whether the file is present locally — the
    URL is still returned for uncommitted files (skill explains how
    to handle).
  - **Non-GitHub origins** (GitLab, Bitbucket, internal): returns
    `ok=false` with `host: "other"` so the LLM can fall back to a
    relative path with a one-line explanation. Other hosts can land
    later when the URL formats stabilise.
  - `kanban-jira-agent` SKILL.md gains a "Linking to repo docs"
    section with the four response branches (exists / not-exists /
    other-host / no-origin).
  - **No automatic comment rewriting** — the LLM decides when to use
    a URL vs a relative path. Plugin provides primitive, LLM decides;
    same philosophy as the mention-reply work in 0.3.5.
  - `test_phase14.py`: 12 cases covering origin parsers (HTTPS / SSH /
    non-GitHub / malformed), happy-path resolution, leading-slash
    handling, traversal rejection, exists flag, branch override, no
    origin, non-GitHub host, empty doc-path. All 14 phase suites
    (148 tests) green.

## 2026-05-01 (sync stale + Q checks)

### Added
- **kanban 0.3.6** — `/kanban:sync` (and the SessionStart hook that
  fires it automatically) now surfaces two checks beyond the existing
  open-cards + mentions blocks:

  - **`[stale DOING — N card(s) idle ≥ 2 day(s)]`** — DOING cards
    belonging to this AP whose `updated` timestamp is older than 2
    days. The agent might have forgotten the card sat in DOING; the
    block prompts them to resume, ask a `/kanban:question`, or close
    via `/kanban:done`.
  - **`[unanswered questions — N BLOCKED card(s) waiting on human, ≥24h]`**
    — BLOCKED cards where this AP posted a Q-prefix comment via
    `/kanban:question` and no other party has commented since,
    AND ≥24h have passed (so the human has had time to reply). Helps
    the agent spot stuck-on-the-human items rather than waiting forever.

  Together with the existing open-cards summary and mentions block,
  `/kanban:sync` is now the equivalent of "open Jira and look around" —
  the answer to issue/question #13 ("how does the agent know what to
  check?"). No new slash command (intentionally — Option A from the
  thread); both checks are augmentations of the existing primitive.

  Highlights:
  - `_detect_stale_doing(driver, repo_ap)` reads `Task.updated` from
    `list_tasks(column=DOING, ap=...)`. No extra network calls beyond
    the existing list_tasks.
  - `_detect_unanswered_questions(driver, repo_ap)` does
    `list_tasks(BLOCKED) + list_comments` per BLOCKED card. The
    existing prefix-grammar parser (`_parse_comment`) already
    distinguishes own Q-comments (author == this AP) from anything
    else; the detector uses that.
  - Best-effort: detector failures don't block the rest of the sync
    output.
  - Thresholds hardcoded for now (2 days / 24 hours) — moved to
    conventions only when a real use case demands per-team tuning.
  - `test_phase13.py`: 11 mocked cases covering both detectors,
    timestamp edge cases, and the cmd_sync_summary integration. All
    13 phase suites (136 tests) green.

## 2026-05-01

### Added
- **kanban 0.3.5** — @-mention detection + reply primitives. Lets a
  human in Jira write `@AgentBot 評估一下這個可行性 就開始動工` and
  the agent's next session sees it, classifies the workload, claims the
  card or spawns sub-cards, and replies with a notification.

  Plugin's job stops at "surface the mention" and "provide the
  primitives". Workload classification + decision making + content
  generation are LLM-side; the skill (`kanban-jira-agent`) carries the
  playbook for both LLM behaviours.

  Highlights:
  - **Detection** — `lib/jira_client.adf_extract_mentions(adf, target)`
    walks the ADF tree for `mention` nodes. New `find-mentions`
    helper subcommand: JQL bounds candidates by `updated >=`, then
    walks each issue's description + comments for mentions of
    `agentAccountId`. Self-mentions (author == agent) filtered out.
  - **Sync integration** — `cmd_sync_summary` (already wired to
    `SessionStart` via `kanban-jira-sync.sh`) now appends a
    `[mentions — N since X]` block when there are unread mentions.
    Best-effort: detection failures don't block the open-cards summary.
  - **Ack timestamp** — `.claude/kanban-agent.json#lastMentionSeenAt`
    tracks what's been shown. New `mark-mentions-read` subcommand
    advances it; refuses to move backwards. Preserves sibling fields
    (`ap`, `acknowledgedConventions`).
  - **Reply primitive** — `lib/jira_client.text_to_adf_with_mention()`
    builds a comment ADF that begins with a Jira-native `@-mention`
    node, so the recipient gets a real notification (not just a
    comment buried in card history). `post_comment` driver method
    gains optional `mention_account_id` / `mention_display` kwargs;
    new `post-reply` CLI subcommand routes through it. New
    `/kanban:reply <KEY> --to <accountId> --body "..."` slash command.
  - **Sub-card primitive** — `TaskInput` gains `parent_key` /
    `link_type` (default `Relates`); `create_task` creates the issue
    then attaches the link via the existing `create_issue_link`. New
    `create-sub` CLI subcommand spawns N sub-cards in a batch
    (auto-AP-assigned to the current repo). New
    `/kanban:create-sub <parent> --title "..." [--title "..."]` slash
    command. Failed titles tracked separately so the user can retry.
  - **Skill update** — `kanban-jira-agent` SKILL.md gains a "When
    you're @-mentioned" section with workload classification heuristic
    (small/large/ask-first), the "always reply with @-mention to
    original commenter" rule, and the prohibition on parallel claims.
  - **3 new slash commands**: `/kanban:mentions`, `/kanban:reply`,
    `/kanban:create-sub`.
  - **`test_phase12.py`**: 11 mocked cases — ADF extract/build,
    self-mention filter, ack roundtrip + preservation, reply routing
    with mention, sub-card batch + parent linking. All 12 phase
    suites (125 tests) green.

## 2026-04-30 (conventions)

### Added
- **kanban 0.3.4** — share-code carries team conventions. Closes #10.
  The `/kanban:showjira-code` payload now travels with a small block
  of soft team agreements alongside the existing hard wiring
  (transitions / AP / board). Schema bumped to `kanban-jira-code/2`;
  receivers still accept v1 codes for back-compat.

  Scope is deliberately narrow — narrative-only plus one opt-in toggle.
  `summaryPrefix` / `defaultEpic` / `requiredLabels` / `commentTemplates`
  / `reviewerAccountId` were considered and **rejected** in this round
  to avoid slippery-slope / overlap with existing config (each can be
  re-proposed individually if a real use case lands).

  Highlights:
  - `lib/conventions.py` — normalize / validate / hash_conventions /
    record_ack / has_recent_ack. Length guardrails (200 chars × 10
    notes) are advisory; helpers warn but never reject.
  - `backend.jira.conventions = { notes: [string],
    blockedRequiresLink: bool }` (schema additive).
  - `/kanban:edit-conventions` — interactive author flow (per-note
    keep/edit/delete, length checks, toggle prompt).
  - `/kanban:show-conventions` — read-only render with ack status.
  - `/kanban:initjira-by-code` — when imported code carries non-empty
    notes, requires the literal phrase `I have read these` before
    init completes (no `yes`/`Y`/etc. — the friction is the feature,
    matching #10 §Receiver UX). Ack persists as a hash + timestamp in
    `.claude/kanban-agent.json`; same conventions on re-import skips
    the prompt.
  - `blockedRequiresLink: true` (per-team opt-in) — when set,
    `cmd_transition` refuses BLOCKED transitions without `--blocked-by`.
    Pairs with the `--blocked-by` shipped in 0.3.3 (#8); each team
    decides whether to enforce.
  - New helper subcommands: `set-conventions`, `read-conventions`,
    `record-conventions-ack`.
  - `test_phase11.py`: 15 mocked cases covering normalize / validate /
    hash / ack persistence / emit/import roundtrip with both v1 and v2
    schemas / set-and-warn / record-and-read / blockedRequiresLink
    enforcement on and off. All 11 phase suites (114 tests) green.

## 2026-04-30 (issue links)

### Added
- **kanban 0.3.3** — `/kanban:block` accepts `--blocked-by KEY[,KEY,...]`.
  Closes #8. Creates Jira native "is blocked by" issue links before
  applying the BLOCKED transition, so the dependency surfaces in Jira's
  "Linked work items" panel and JQL `issueLinkType` queries — instead of
  being buried in a free-text `blocked_reason` comment.

  Highlights:
  - `lib/jira_client.py` gains `create_issue_link(type_name, inward_key,
    outward_key)` mapping to `POST /rest/api/3/issueLink`.
  - `drivers/jira.py:_link_blockers` validates blocker key format
    (`^[A-Z][A-Z0-9_]+-\d+$`), refuses self-block, dedupes, skips
    already-linked blockers (idempotent), and runs **before** the status
    transition so a 404 leaves the card in its previous state instead of
    half-blocked.
  - `_issue_to_task` now reads `issuelinks` and surfaces inward `Blocks`
    keys as `Task.depends`, giving Jira mode parity with local mode's
    `depends[]` field.
  - `cmd_transition` accepts `--blocked-by` (comma-separated). Rejects
    use with `--to != BLOCKED`. Response gains `depends[]` reflecting
    the post-operation link state.
  - `commands/block.md` documents the Jira flow: pass `--blocked-by`
    explicitly, or confirm extraction from prose via `AskUserQuestion`
    (no silent inference). Multi-blocker, cross-project links supported.
  - `test_phase10.py`: 12 new mocked cases covering endpoint payload,
    `depends` extraction from `issuelinks`, format/self-block rejection,
    idempotency, atomicity (link-failure aborts before transition),
    full transition integration, CLI roundtrip. All 10 phase suites
    (111 tests) green.

## 2026-04-30 (later still)

### Fixed
- **kanban 0.3.2** — closes #6. `/kanban:initjira` option `[b] create new
  field` now attaches the new AP custom field to project screens
  automatically. Previously the field was created and option values added,
  but never associated with any screen, so Jira refused all writes
  (`customfield_X cannot be set. It is not on the appropriate screen, or
  unknown.`). Symptom was silent — `/kanban:next` returned no work even
  with cards present.

  - `lib/jira_client.py` gains `list_screens` (with query filter),
    `list_screen_tabs`, `list_screen_tab_fields`, `add_field_to_screen_tab`.
  - `scripts/jira_setup.py:create-ap-field` accepts `--project <KEY>` and
    runs `_associate_field_with_screens` after the create call. Strategy:
    list project-named screens via `queryString`, plus the global default
    screen id=1; for each, add the field to the first tab. Idempotent
    (already-attached returns silently; 403 routed to a dedicated
    `denied` bucket so the user can ask their admin).
  - New `associate-ap-field-screens` and `verify-ap-field-screens`
    subcommands for re-running or auditing the association after init.
  - New `/kanban:fix-ap-screen` slash command — recovery path for
    installs that ran on 0.3.1 (or earlier), or whose admin grants screen
    permission later.
  - `commands/initjira.md` step 4 option [b] now passes `--project`,
    surfaces the screens summary, and runs `verify-ap-field-screens`
    before continuing to step 5.
  - `test_phase9.py`: 12 new mocked cases covering endpoint payloads,
    candidate-screen selection (project + default fallback), happy path,
    idempotency, 403 handling, CLI integration. All 9 phase suites
    (99 tests) green.

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
  - **Code-based mapping sharing across machines / teams** —
    `/kanban:showjira-code` emits the current board's mapping
    (transitions + AP field config) as compact JSON. `/kanban:initjira-by-code`
    on another machine accepts the pasted JSON and skips the DSL setup
    entirely (jumps from credentials directly to "assign this repo's AP").
    Tokens / per-machine credentials are NEVER in the code; receiving
    machine still runs `/kanban:reset-credentials` once. Replaces the
    earlier per-machine `kanban-boards/` cache attempt — code-based
    sharing crosses machines, the cache didn't.
  - **Live AP roster** — `/kanban:assign-ap`, `/kanban:register-ap`,
    `/kanban:whoami` query Jira's custom-field options as the source of
    truth for who's registered (the local `kanban.json#registered` is
    just a hint that gets refreshed on each operation). On network /
    credential failure, the helpers fall back to the local list with a
    `fallbackUsed: true` flag so the user knows it may be stale.
  - **Security**: removed `--dsl-file` from `parse-transitions-dsl`
    (would have allowed an LLM-driven misuse to reflect arbitrary file
    contents — including `~/.claude-workbench/.env` — back into the chat
    transcript via the parser's verbatim error messages). DSL parser
    errors now report `line N` plus a 32-char redacted snippet, never
    the full line.
  - **Tests**: 29 new cases across `test_phase7.py` (DSL parser,
    suggester, migration, disambiguation, compound write, CLI) and
    `test_phase8.py` (emit/import code roundtrip, live AP query
    fallback, register-ap fuzzy via local hint). All 8 phase suites
    (87 tests) green.
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
