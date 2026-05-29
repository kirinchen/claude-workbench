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

### Fixed
- **kanban 0.3.31** — `JiraDriver.list_tasks(column=…)` now honours
  `transitions[col].addLabels` when building JQL, so BLOCKED and DOING
  no longer return the same result set when both map to the same Jira
  status (the canonical "BLOCKED = In Progress + label `kanban:blocked`"
  setup). `/kanban:sync` no longer duplicates In-Progress cards under
  BLOCKED. The new `_column_jql_clauses` helper mirrors `disambiguate`'s
  semantics: it AND-includes each `addLabels` label, AND-excludes each
  `removeLabels` label, and AND-excludes any same-status sibling whose
  `addLabels` is a strict superset of the queried column's. Closes #63.

### Added
- **chat 0.1.0** — new lightweight plugin for logged conversation threads.
  `/chat:new` starts recording the session to `doc/chat/{name}.md` via a
  `Stop` hook; `/chat:exit` stops; `/chat:note` summarises a thread into
  `doc/note/`; `/chat:resume` re-opens a saved thread (by name, index, or
  keyword). Chat mode is session-scoped — the `SessionEnd` hook clears it, so
  it never leaks into the next session. Logging only; agent behaviour is
  unchanged.

## 2026-05-16 (kanban markdown → ADF — bug after #57)

### Fixed
- **kanban 0.3.30** — agent-emitted markdown now renders correctly in
  Jira. Previously, `text_to_adf` wrapped any body in a single flat
  paragraph, so a comment or description containing `## Heading`,
  `- bullets`, or ``` ```code``` ``` showed up in the Jira UI with
  the literal markdown source instead of styled blocks.

  New `lib/markdown_adf.py` parses a markdown subset into proper ADF
  nodes:
  - Headings `#`..`######` (h1–h6); requires a space after the hashes
    so `#123` stays a plain issue ref rather than an h1.
  - Bold (`**...**` / `__...__`), italic (`*...*` / `_..._`), inline
    code (`` `...` ``), explicit links `[text](url)`.
  - Bare URLs still auto-linkify (pre-fix behavior preserved).
  - Fenced code blocks (triple-backtick), with optional language tag
    → `codeBlock` with `attrs.language`.
  - Bullet lists (`-`/`*`/`+`) and ordered lists (`N.`) →
    `bulletList`/`orderedList` of `listItem`s.
  - Blockquotes (`>`) wrap inner paragraph(s).

  Call-site impact:
  - `text_to_adf()` now routes through `markdown_to_adf()`. All
    existing callers (`drivers/jira.py` create / update description,
    add comment) benefit automatically. Plain-text inputs round-trip
    to the same single-paragraph + URL-auto-link shape as before, so
    non-markdown payloads see zero regression.
  - `text_to_adf_with_mention()` body now markdown-parses too.
    Single-paragraph bodies still inline next to the @mention chip
    (preserves the chat-bubble look); multi-block bodies put the
    mention on its own paragraph and emit body blocks as siblings so
    headings/lists/code-fences render correctly.
  - The SPEC §9 prefix (#27) intentionally stays literal — it's a
    fixed-shape label rendered bold via an ADF `strong` mark, not
    user-supplied markdown.

  Out of scope (would need a real CommonMark parser): tables,
  setext-style headings, reference links, nested lists, escape
  sequences, HTML passthrough.

  Tests: `scripts/test_phase35.py` adds 22 cases covering every
  supported markdown construct, plain-text round-trip equivalence,
  mention single-line vs multi-block routing, and prefix-stays-literal.

## 2026-05-16 (kanban versioned board config — #57)

### Added
- **kanban 0.3.29** — `/kanban:push-board-config` and
  `/kanban:pull-board-config` now carry a `_meta` block (version,
  content hash, pushedAt, pushedByAccountId) on every push of the
  `kanban-config` Jira project property. Closes the silent-clobber
  gap exposed by `0.3.27`: two admins pushing without an intervening
  pull no longer overwrite each other without warning.

  **Behavior:**
  - Push reads the current remote `_meta` first. The new payload
    bumps `version` by 1 and stores the canonical sha256 of the
    just-pushed content (canonicalization sorts keys, tight
    separators, `_meta` itself excluded so the hash describes content).
  - Push refuses by default when the remote `_meta.hash` doesn't
    match what this machine last pulled or pushed (auto-`--if-match`).
    Resolve by `/kanban:pull-board-config`, reconcile, push again.
    `--force` bypasses the fence for intentional clobbers.
  - Pull stores `_meta` into local `backend.jira._meta`, so the next
    push on this machine can fence correctly without an explicit
    flag. A successful push also writes the freshly-minted `_meta`
    back into local for the same reason.
  - `/kanban:show-board-config` with `--kanban-path` now emits a
    `diff` block identifying one of four sync states: `in-sync`,
    `remote-ahead`, `local-edits`, `diverged` (or `unknown` when
    local has no cached `_meta` yet).

  **Schema**: `backend.jira._meta` declared as optional (writers
  maintain it; users shouldn't hand-edit). Old payloads without
  `_meta` migrate automatically — pull treats them as
  `{version: 0, hash: null}` and the next push initializes `v1`.

  **Out of scope**: real ETag concurrency at the Atlassian API level
  (they don't offer it on entity properties); per-field version
  history / rollback.

  Tests: `scripts/test_phase34.py` adds 15 cases covering canonical
  hash stability, first-push init, version bump, `--if-match` fence
  (refuse + force), `cmd_push` auto-fill, `_meta` round-trip through
  pull/push, and all four diff states.

## 2026-05-08 (kanban paste-flow removal + initjira auto-detect — PR 3 of 3)

### Removed (BREAKING for ≤ 0.3.26 users mid-paste)
- **kanban 0.3.27** — completes the showjira-code → board-config
  replacement. Three slash commands and two helper subcommands are
  gone. The `/kanban:initjira` interactive flow gains a Step 2.5
  auto-detect that pulls existing board config and skips DSL +
  AP-discovery when found. Multi-machine bootstrap now happens via
  Jira project property `kanban-config`, single source of truth.

  **Removed slash commands**:
  - `/kanban:showjira-code`
  - `/kanban:import-jira-code`
  - `/kanban:initjira-by-code` (was already a deprecation shim from #34)

  **Removed helper subcommands** (`scripts/jira_setup.py`):
  - `cmd_emit_jira_code` + its argparse subparser
  - `cmd_import_jira_code` + its argparse subparser

  **Removed test phase**: `test_phase8.py` (entire file — emit/import
  round-trip coverage). Phase 11 conventions tests for emit/import
  also dropped (the conventions block itself + its set/read/ack flow
  stays fully covered). Phase 28 emit/import migration tests dropped
  (the underlying `_alias_done_to_approved` semantics still tested
  directly).

  **Migration steps for 0.3.26 → 0.3.27**:

  Existing teams that were using the paste flow have a one-time
  migration. Pick the source repo (whichever one had the
  authoritative `backend.jira` block) and run, as a Jira
  **project-admin** account:

  ```
  /kanban:push-board-config
  ```

  Done — every other repo / machine on the same Jira project picks
  up the config automatically on its next `/kanban:sync` (8h passive
  TTL) or via `/kanban:pull-board-config`. No paste, no drift.

  If your `kanban.json` is fresh (no `transitions` block populated),
  re-run `/kanban:initjira` — Step 2.5 will probe for existing board
  config and pull it without needing the interactive DSL setup.

  **`/kanban:initjira` Step 2.5** (new): after credential capture
  and board URL parsing (now yielding `projectKey`), the spec runs
  `pull-board-config --project-key <KEY>` to probe for an existing
  `kanban-config` property. Three outcomes:
  - **200 OK** — pull succeeds; skip Steps 3 + 4 (DSL + AP-discovery);
    jump to Step 5 (assign AP).
  - **404** — board has no published config yet (first agent on this
    board); fall through to interactive Steps 3 + 4 as before. The
    `Done` summary at the end recommends `/kanban:push-board-config`
    to publish for future joiners.
  - **Other error** — surface verbatim; fall through to interactive
    flow.

  **Cross-references swept** (paste-flow → push/pull-board-config):
  - `commands/{reset-credentials,edit-conventions,show-conventions,push-board-config,initjira}.md`
  - `lib/conventions.py` (ack-hash docstring)
  - `templates/kanban.schema.json` (conventions description)
  - `plugins/kanban/README.md` + `README_zhtw.md` (slash-command
    table, deprecated section, core concepts including a new
    "Board config single-source-of-truth (since 0.3.27)" item)
  - `kanban_quickstart.md` + `kanban_quickstart_zhtw.md` (entire 8b
    Multi-machine setup section rewritten — three-layer storage
    table now points at Jira project property; cheatsheet covers
    the new bootstrap paths; "How it works" walks through admin
    push + receiver pull)

  Phase 32 covers seven cases: cmd_emit_jira_code attribute removed;
  cmd_import_jira_code attribute removed; old command markdown files
  absent; emit/import argparse subcommands no longer accepted (rc !=
  0 with "invalid choice"); initjira step 2.5 probe finds board
  config; step 2.5 probe gets 404 → notFound signal for fallback;
  step 2.5 bootstrap-with-explicit-project-key path (fresh repo
  flipping from local to jira after pulling).

  All 31 phases green (the loop in test_all.sh skips phase 8 since
  its file was removed alongside emit/import).

## 2026-05-07 (kanban board-config slash commands + passive sync — PR 2 of 3)

### Added
- **kanban 0.3.26** — three new slash commands and SessionStart-
  triggered passive sync wire up the helpers from PR 1 (#52, 0.3.25).
  Multi-machine teams now stay in sync without manual paste flow.
  This is **PR 2 of 3**; PR 3 removes `showjira-code` /
  `import-jira-code` / `initjira-by-code` and ships the migration
  command.

  **New slash commands**:
  - `/kanban:push-board-config` — admin uploads this repo's
    `backend.jira` block to the Jira project property `kanban-config`
    (the canonical shared source). Strips per-machine fields
    (`agentAccountId`, `ap.registered`) before pushing. Requires
    Jira project-admin role; non-admin pushes get a clear permission
    message pointing at the role grant.
  - `/kanban:pull-board-config [--project-key K]` — anyone can pull
    the latest config from Jira. Overwrites local `backend.jira`,
    preserves per-machine fields, records `cachedAt`. Resets the 8h
    TTL clock for passive sync. Useful when you know the team just
    pushed and don't want to wait for the next session, or when
    bootstrapping a fresh repo.
  - `/kanban:show-board-config` — read-only inspection of the
    Jira-side payload. Doesn't touch local state, doesn't reset the
    cache TTL. Useful for spotting drift between local cache and the
    canonical Jira-side config.

  **Passive sync at SessionStart** (`cmd_sync_summary`):
  When the local board-config cache is older than `CACHE_TTL_HOURS`
  (8h, defined in `lib/board_config`), `/kanban:sync` opportunistically
  pulls from Jira before rendering its open-cards summary. The pull
  result feeds the same session — fresh transitions / conventions
  are honored immediately. Best-effort:
  - 404 (no config on Jira yet) — silent skip; common during
    early adoption.
  - 403 (permission denied) — stderr warning; continue with stale
    cache.
  - missing credentials — silent skip; the token row in
    `/kanban:whoami` already surfaces this.
  - any other failure — stderr warning; continue.

  **`/kanban:whoami`** gains a `Board config:` row showing where the
  config lives on Jira plus the local cache age:
  ```
  Board config:  Jira project AGENT properties.kanban-config
                 (synced 3h ago, fresh)
  ```
  Or for never-synced state:
  ```
  Board config:  Jira project AGENT properties.kanban-config
                 (never synced — run /kanban:pull-board-config)
  ```
  Backed by a tiny new helper subcommand `read-board-config-cache`
  that returns metadata (cachedAt, cacheAgeHours, stale, ttlHours)
  without making any Jira call.

  **Internal**: shared merge helper `_apply_pulled_board_config` used
  by both the explicit `pull-board-config` subcommand and the new
  `_maybe_passive_sync_board_config` entry point. Identical merge
  semantics — Jira-side wins on shared fields, per-machine fields
  preserved.

  **Drive-by fix**: latent bug in `JiraDriver.list_tasks` that
  referenced uninitialised `self.partial` / `self.label_fallback`
  attributes (legacy v0.2 fields removed in v0.3 migrate_legacy).
  Triggered when iterating columns whose canonical → Jira status
  mapping was undefined. Defensive `getattr(..., False)` /
  `getattr(..., {})` so the lookup falls through cleanly.

  **Coexistence**: `/kanban:showjira-code`, `/kanban:import-jira-code`,
  `/kanban:initjira-by-code` continue to work unchanged. PR 3
  removes them along with their helper subcommands.

  Phase 31 covers ten cases: passive sync local-mode no-op; fresh-
  cache no-op (no Jira call); stale + successful pull (overwrites
  local + preserves per-machine + records cachedAt); stale + 404
  silent skip; stale + 403 warns + continues; stale + missing
  credentials silent skip; `read-board-config-cache` never-synced /
  fresh / stale; `cmd_sync_summary` end-to-end with stale cache
  (pull then summary). Plus 3 phase-18 sync_summary tests updated to
  pre-mark the cache fresh (so passive sync doesn't consume their
  reconcile mock queue).

  All 31 phases green.

## 2026-05-07 (kanban board-config helper layer — PR 1 of 3)

### Added
- **kanban 0.3.25** — `lib/board_config.py` + three new helper
  subcommands lay the foundation for moving the canonical shared
  board config off per-receiver paste flows
  (`/kanban:showjira-code` → `/kanban:import-jira-code` round-trip)
  onto the **Jira project itself**, stored under property key
  `kanban-config`. Multi-machine teams stop drifting silently when
  one repo updates the rules.

  This is **PR 1 of 3**. Helpers + tests only — no slash commands,
  no driver-level passive sync, no removal of the old paste flow yet.
  PR 2 wires `/kanban:push-board-config` / `/kanban:pull-board-config`
  / `/kanban:show-board-config` and adds 8h-TTL passive sync at
  driver init. PR 3 removes `showjira-code` / `import-jira-code` /
  `initjira-by-code` and ships the migration command.

  **Storage model**:
  - **Jira project property `kanban-config`** — authoritative; written
    by push (requires Jira project-admin role), read by pull. 32KB
    Atlassian-imposed cap, plenty for transitions DSL + conventions.
  - **`kanban.json#backend.jira`** — git-tracked per-machine cache.
    Mirrors the property's value. Survives clones; auto-commits on
    pull just like any other state change.
  - **`.claude/kanban-agent.json#boardConfigCachedAt`** — ISO 8601
    timestamp of the last successful pull on this machine. Drives the
    8-hour passive-sync TTL (constant `CACHE_TTL_HOURS=8` in
    `lib/board_config`).

  **Authority precedence**: Jira-side wins on read; local push only
  fires when an admin runs `/kanban:push-board-config` explicitly.
  Two agents pushing simultaneously is last-writer-wins (Atlassian
  doesn't expose ETag versioning on properties).

  **Offline behaviour**: when Jira is unreachable, pull fails — the
  local cache continues to serve. PR 2 will surface a "using stale
  cache" warning in `/kanban:whoami`.

  **New `lib/board_config.py` surface**:
  - `push(client, project_key, config)` — writes property; raises
    `BoardConfigError` with permission-clear message on 403
  - `pull(client, project_key)` — returns the unwrapped config dict;
    distinguishes 404 ("no config yet") via `not_found` attribute
  - `cache_age_hours(repo_root)` — float | None
  - `is_cache_stale(repo_root, ttl_hours=None)` — bool, default 8h TTL
  - `mark_synced(repo_root, ts=None)` — writes
    `.claude/kanban-agent.json#boardConfigCachedAt`, preserves other
    fields (`ap`, `lastMentionSeenAt`, etc.)

  **New `JiraClient` methods** (`lib/jira_client.py`):
  - `get_project_property(key, prop_key)` — full envelope
    `{"key", "value"}`
  - `set_project_property(key, prop_key, value)` — body is the JSON
    value to store

  **New helper subcommands** (`scripts/jira_setup.py`):
  - `push-board-config --kanban-path P` — strips per-machine fields
    (`agentAccountId`, `ap.registered`) before writing; marks local
    cache as freshly synced too
  - `pull-board-config --kanban-path P [--project-key K]` — overwrites
    `backend.jira` from Jira; **preserves** per-machine fields
    (`agentAccountId`, `ap.registered`); records `cachedAt`
  - `read-board-config [--kanban-path P] [--project-key K]` — print
    Jira-side config without touching local state

  **Coexistence**: `showjira-code` / `import-jira-code` /
  `initjira-by-code` keep working unchanged in 0.3.25. PR 3 removes
  them.

  Phase 30 covers eleven cases: push happy path; push 403 →
  permission-denied with admin-role hint; pull happy path; pull 404
  → distinct `not_found` error; cache age None when unset; cache age
  float when set (3h tolerance); stale-cache logic across no-cache /
  fresh / past-TTL / custom TTL; mark_synced preserves other fields;
  push command strips per-machine fields; pull command preserves
  per-machine fields and records `cachedAt`; read command does not
  touch local kanban.json or `.claude/kanban-agent.json`.

  All 30 phases green.

## 2026-05-06 (kanban anti-self-approve keyed on statusCategory)

### Fixed
- **kanban 0.3.24** — anti-self-approve guard now keys on the target
  Jira status's `statusCategory` rather than just the canonical name
  `APPROVED`. Closes #50.

  **The bug**: pre-fix, `transition --to APPROVED` (or the legacy
  `--to DONE` alias) blocked **any** agent-driven transition to
  canonical APPROVED when the agent owned the card. But teams whose
  DSL maps canonical APPROVED to a non-terminal Jira status (e.g.
  `transitions.APPROVED.status == "REVIEW"` plus `addLabels:
  ["kanban_awaiting_approval"]` for a soft "agent done, awaiting
  human approval" intermediate) got blocked on a path that's
  semantically NOT a self-approval — the agent is just signalling
  completion; the human still has to push REVIEW → Done.

  Reporter (`narrative-fin-agent`) had to PATCH labels via Jira REST
  directly to recover, breaking the "DSL is the only thing touching
  transitions/labels" invariant.

  **The fix**: query Jira's `statusCategory` for the target status
  (lazy-cached via `get_project_statuses` per driver instance):

  - `category == "done"` → fire the strict guard (true approval —
    existing behavior preserved when DSL maps to a Jira terminal Done)
  - `category in {"indeterminate", "new"}` → allow (intermediate
    stage; the actual #50 fix)
  - `category is None` (lookup failed) → refuse with a **distinct**
    error message so the caller can tell "Jira API hiccup" apart from
    "you're trying to self-approve". Lookup is cached even on failure
    to avoid retry storms; user can retry the operation.

  Strict (fail-closed) policy on lookup failure preserves the safety
  invariant — anti-self-approve must not be skippable just because
  the network hiccuped. The distinct error wording lets a human
  retrying after a transient failure tell what's going on.

  **Performance**: one extra `get_project_statuses` call per driver
  lifetime; cached after that. For a `/kanban:doing` session with
  multiple transitions, the cost is amortised over the session.

  **kanban-jira-agent SKILL** updated with the precise contract and
  the failure-mode error message so agents can recognise it.

  Phase 29 covers seven cases: strict block when category=done +
  AP=mine + assignee=agent (existing behavior preserved); allow when
  category=indeterminate (the #50 fix); allow when category=new;
  lookup failure → distinct error (NOT SelfApproveRefused); recording
  for another human still works on done category; lazy cache reused
  on second transition; cache failure not retried.

## 2026-05-04 (kanban canonical DONE → APPROVED rename)

### Changed
- **kanban 0.3.23** — canonical state `DONE` renamed to `APPROVED` to
  disambiguate from the Jira workflow status `Done`. Closes #48.

  **The naming collision** caused real configuration mistakes: users
  put "I'm done, please review" labels on the DSL's `DONE` entry
  (dead code — `/kanban:done` transitions to canonical REVIEW, never
  to DONE), wrote conventions notes describing a flow that doesn't
  exist (DOING → DONE), and read DSL `"DONE": {"status": "Done"}` as
  "the agent's done state" rather than the post-approval terminal.
  After #45 (REVIEW flavors) shipped, this remained the next-biggest
  source of footguns.

  **The rename is breaking but back-compat-bridged.** Every input
  surface accepts the legacy `DONE` token through one minor cycle and
  normalises to `APPROVED` on the way in:

  - `lib/transitions.py` — `CANONICAL_COLUMNS` is now
    `(TODO, DOING, BLOCKED, REVIEW, APPROVED, CANCELLED)`.
    `parse_dsl` accepts `DONE > Done` on the LHS and the
    `CANCELLED > DONE + label` self-reference on the RHS, both
    aliased. `migrate_legacy` renames `transitions.DONE` to
    `transitions.APPROVED` in-memory; idempotent on already-renamed
    input. New `_alias_done_to_approved` helper exposes the rename
    for callers that round-trip JSON.
  - `lib/kanban_io.py:load` migrates `task.column == "DONE"` to
    `"APPROVED"` in-memory and rewrites `meta.columns`. First
    persistence write afterwards normalises on disk. Existing
    committed kanban.json files load cleanly with no user action.
  - `drivers/jira.py:transition()` and `drivers/local.py:transition()`
    normalise the `to_column` argument via `_tr.normalize_canonical`.
    Anti-self-approve checks now key on `"APPROVED"`; error wording
    matches.
  - `scripts/jira_setup.py:cmd_transition` adds `APPROVED` to the
    `--to` choices alongside `DONE` (deprecation alias) and emits a
    stderr warning when `DONE` is used.
  - `scripts/jira_setup.py:cmd_set_transitions` accepts a JSON block
    with the legacy `DONE` key, auto-renames to `APPROVED`, returns a
    deprecation warning. Refuses input that carries BOTH keys
    (ambiguous).
  - `scripts/jira_setup.py:cmd_emit_jira_code` now emits
    `kanban-jira-code/3` with `APPROVED`. `cmd_import_jira_code`
    accepts `/1`, `/2`, `/3` payloads and auto-upgrades the legacy
    `DONE` key to `APPROVED` on import.
  - `templates/kanban.schema.json` — schema bumped: `transitions`
    properties now include `APPROVED` (canonical) and keep `DONE` as
    a deprecated slot for back-compat parsing. `meta.columns` and
    `task.column` enums include both tokens. `if/then` validation
    block on `APPROVED` requires `started` + `completed`; the legacy
    `DONE` block is preserved for older data files.
  - `templates/kanban.empty.json` and `kanban.example.json` use
    `APPROVED` in the columns array and on the seeded sample task.

  **`/kanban:done` (slash command) is unchanged** — reporter flagged
  the command name as a separate confusion layer (Jira mode actually
  transitions to REVIEW, not APPROVED) and asked to file it as a
  follow-up. This PR honours that out-of-scope marker.

  **Migration timeline**: the legacy `DONE` alias paths log
  deprecation warnings in 0.3.x; planned removal target is **kanban
  0.5** (multiple minor releases of warnings before reject — gives
  ecosystem time to upgrade).

  Phase 28 covers thirteen back-compat paths: alias-helper basic +
  idempotent + conflict-skip; `kanban_io.load` task.column +
  meta.columns migration; `parse_dsl` accepts legacy DONE on LHS and
  on RHS self-reference; `migrate_legacy` v0.2 statusMap rename;
  `migrate_legacy` v0.3 transitions rename; `cmd_set_transitions`
  deprecation + ambiguity reject; `cmd_import_jira_code` v2-with-DONE
  upgrades to APPROVED on persist; `cmd_emit_jira_code` outputs
  `/3`; `cmd_transition --to DONE` aliases with stderr warning. The
  prior 27 phases were swept (test data updated DONE → APPROVED) and
  remain green.

  Docs sweep: `commands/`, `skills/` (kanban-workflow,
  kanban-jira-agent, kanban-jira-setup, references), plugin README +
  README_zhtw, top-level kanban_quickstart + _zhtw, top-level README
  + _zhtw all updated to use `APPROVED` for the canonical state name.
  CHANGELOG entries for prior releases are unchanged (historical).
  Jira workflow status names (`Done`) stay as Jira's own naming.

## 2026-05-04 (kanban REVIEW flavors)

### Added
- **kanban 0.3.22** — transitions DSL now supports `flavors` —
  same-status sub-classification via labels, atomically applied. The
  agent's compound transition write merges the chosen flavor's
  `addLabels` / `removeLabels` / `assignee` into the parent spec on
  the same write, so the card lands in REVIEW + the flavor label in
  one operation (no transient "REVIEW without label" window). Closes
  #45.

  **Why this matters**: REVIEW was a single canonical state but
  carried two semantically different signals — "agent finished, please
  approve" vs "agent stuck, posted options, please decide." An outside
  observer (board glance, JQL, mobile UI) couldn't tell them apart
  without opening the card. Per-team agents were inventing their own
  label conventions (`kanban_awaiting_approval` vs `pls-approve` vs
  `awaiting-review`) — the plugin should provide consistency, not push
  it onto every team.

  **Why `flavors` instead of new canonical states**: lifecycle stage
  (canonical state) and within-stage metadata (flavor) are different
  abstraction layers. Flavors don't trigger different plugin behavior
  (anti-self-approve, `/kanban:doing`, `/kanban:reconcile` all treat
  the flavors equivalently). A new canonical state would also force
  `local` driver migration, SPEC + quickstart updates, and
  `/kanban:status` column changes — none of which serve the actual
  use case (label-level triage on the same lifecycle stage).

  **DSL shape** (additive — no flavors block = same as before):

  ```json
  "REVIEW": {
    "status": "REVIEW",
    "flavors": {
      "awaiting_approval": { "addLabels": ["kanban_awaiting_approval"] },
      "needs_decision":    { "addLabels": ["kanban_needs_decision"] }
    },
    "defaultFlavor": "awaiting_approval"
  }
  ```

  - `transition --to REVIEW --flavor awaiting_approval` does status +
    label add atomically.
  - `--flavor` required when state has flavors; `defaultFlavor`
    (optional) is the fallback so `/kanban:done` can stay short.
  - Invalid / missing flavor → raise with the available flavor list.
  - State without `flavors` block → ignore stray `--flavor` (forward
    compat — callers can pass it unconditionally).

  **Slash command updates**:

  - `/kanban:done` — when DSL declares flavors on REVIEW, pass
    `--flavor awaiting_approval` (the conventional name; respects
    whatever key the team's DSL uses).
  - `kanban-jira-agent` SKILL — explains the two flavors and which
    command path to use for each: `/kanban:done` for
    `awaiting_approval`, `/kanban:transition --flavor needs_decision`
    after posting an options comment for `needs_decision`.

  **Naming guidance**: new plugin-suggested labels prefer underscore
  (`kanban_awaiting_approval`) over colon (`kanban:foo`). The colon
  form visually parses as a slash-command path and confuses operators.
  Existing built-in `kanban:blocked` / `kanban:cancelled` keep the
  colon for back-compat.

  **Forward / back compat**: kanban-jira-code/2 payloads carrying
  `flavors` blocks survive round-trip through receivers older than
  0.3.22 — Python's dict round-trip is forgiving and the older driver
  ignores the unknown keys (it just won't know how to consume
  `--flavor`). No new schema version needed.

  Phase 27 covers eight cases: validator accepts well-formed flavors;
  validator rejects six malformed shapes; driver merges flavor's
  addLabels onto compound write; defaultFlavor fallback; missing
  flavor + no default raises with available list; invalid flavor
  raises; state-without-flavors ignores stray `--flavor`;
  cmd_transition argparse threads `--flavor` into kwargs.

## 2026-05-04 (kanban clickable URLs in ADF bodies)

### Fixed
- **kanban 0.3.21** — URLs in agent-posted comments and issue
  descriptions now render as clickable links in Jira UI instead of
  plain un-clickable text. Session-reported.

  ADF doesn't auto-linkify text — a URL only renders clickable when
  the text node carries an explicit `link` mark. The plugin's three
  ADF builders (`text_to_adf` for descriptions and plain comments,
  `text_to_adf_with_mention` for `/kanban:reply`'s `@`-mention path,
  and the driver-level `_agent_comment_body` for prefixed agent
  comments) all wrapped the entire body in a single plain text node.
  URLs were faithfully preserved as text but uselessly so — the user
  had to copy-paste them into the address bar manually.

  New `_text_to_inline_nodes(text)` in `lib/jira_client.py` splits
  the body on a conservative URL regex (`https?://[^\s<>"\)\]]+`)
  and emits a list of ADF text nodes — URL spans get
  `marks: [{type: "link", attrs: {href: url}}]`, non-URL spans stay
  plain. Trailing sentence punctuation (`.`, `,`, `;`, `:`, `!`,
  `?`) is stripped off URLs and put back into a following plain
  span, so "see https://x.com." parses cleanly as URL + period.
  Closing brackets / quotes are excluded from the regex so URLs
  inside parens or square brackets don't pull the close-bracket
  into the link.

  All three ADF builders use the new helper for body content.
  Existing strong-marked SPEC §9 prefixes (the #27 fix) and
  `@`-mention chips are untouched. `adf_to_text` round-trips
  link-marked output back to a clean plain string (lossy on marks
  but text content preserved — non-destructive to existing
  text-extraction callers like `find-mentions`).

  Phase 26 covers ten cases: single URL; URL in middle splits
  3-ways; trailing-punctuation stripping; close-bracket exclusion;
  multiple URLs each get their own mark; no-URL plain-text path;
  empty input; `text_to_adf` produces clickable URL; mention path
  preserves chip + link; driver `_agent_comment_body` keeps strong
  prefix + clickable body URL together; `adf_to_text` round-trip.

## 2026-05-04 (plugin READMEs)

### Documentation
- **kanban 0.3.20** — new `plugins/kanban/README.md` + `README_zhtw.md`.
  Lists every slash command (24) grouped by purpose (day-to-day,
  inbox/async, lifecycle, setup), explains driver concepts (local vs
  Jira, AP routing, compound transitions, conventions), enumerates
  hooks, sketches the file layout. Drives off the convention "to find
  available commands, the authoritative source is Claude Code's `/`
  autocomplete; this README is the offline / discovery surface."
- **mentor 0.2.4** — `README.md` + `README_zhtw.md` slash-command
  table updated to include `/mentor:upgrade` and
  `/mentor:current-state` (both shipped after the v0.1.0 MVP table
  was written). File-layout `commands/{...}.md` line broadened to
  reflect the seven shipped commands.

## 2026-05-04 (kanban precheck recent comments)

### Fixed
- **kanban 0.3.19** — the card-detect hook now surfaces the most
  recent 3 comments verbatim in its context block, so an agent
  pasting a Jira URL into a prompt sees load-bearing instructions
  ("stop", "delete this", "scope changed") instead of just the
  static title/status/AP. Closes #42.

  **The original bug**: `scripts/kanban-card-detect.sh` always passed
  `--skip-comments` to `precheck-card`, and even without that flag
  `_detect_open_question` only considered SPEC §9 `Q:`-prefixed
  comments. So a free-form instruction comment from the user was
  silently invisible to the agent — the implicit "if you reference a
  card, you have its context" contract held for static fields but not
  dynamic ones, which is where async decisions actually live.

  **Fix has three parts**:

  - `precheck-card` gains `--comments-limit N` (default **3**, max
    recommended 5; `0` disables, equivalent to `--skip-comments`).
    The most recent N comments are surfaced verbatim with author +
    relative timestamp + SPEC §9 kind tag + a 500-char excerpt.
    Newlines collapse to spaces so the block stays grep-friendly.
  - `kanban-card-detect.sh` drops `--skip-comments`, replaced by
    `--comments-limit 3`. The 30s precheck cache absorbs the extra
    API call across repeated key references in a session.
  - New `read-card-comments` helper subcommand: `python3
    jira_setup.py read-card-comments --kanban-path P --key KEY
    [--limit N]` returns `{ok, key, comments: [{author, ts, kind,
    text}, ...]}`. Building block for any slash command that needs
    recent context (and the natural fix for "the plugin's CLI doesn't
    expose read-comments anywhere" gap reporter called out).

  **Output shape** in the precheck block:

  ```
  [kanban context for BZK-633]
    Title:        ...
    Status:       In Progress
    AP:           quant-oak  (you)
    Recent comments (3):
      Bot (5d ago) [S]: claimed
      Alice (yesterday) [C]: 我同意; 改方向到 NFA
      Kirin (2h ago) [C]: 已經不需要了, 由 NFA 主導, 幫我把這卡 delete
  ```

  The Q-prefix open-question detection is preserved — it remains a
  high-signal warning (`Open question: ...`) above the recent-comments
  block when an unanswered Q exists. Recent-comments and open-question
  are now complementary surfaces, not the only path.

  Phase 25 covers seven cases: rendering when recent_comments present;
  no section when empty; excerpt newline-collapse + 500-char truncate
  with `…`; relative-timestamp buckets (just now / Nm / Nh /
  yesterday / Nd / Nw / Nmo / Ny ago); cache-hit path emits the
  block; `--skip-comments` back-compat; `read-card-comments` shape +
  `--limit` truncation.

## 2026-05-03 (kanban secret-safe token capture)

### Security
- **kanban 0.3.18** — token capture flow no longer routes the API
  token through the agent's Bash tool, so the token literal can't end
  up in Claude Code's conversation transcript. Closes #42.

  **The original bug**: `/kanban:reset-credentials` and
  `/kanban:initjira` step 1 told the agent to capture the token via
  `AskUserQuestion`, then to run `echo "<TOKEN>" | python3 ... store-
  credentials ...` through the Bash tool. Claude Code prints every Bash
  command to the conversation transcript for transparency, so the
  token literal was logged. The plugin's own leak detector then warned
  the user to rotate — a self-inflicted loop where you set up the
  token following the docs and immediately got told you'd leaked it.

  **The fix** has three parts:

  - `_read_token` accepts `prompt=True`, which uses
    `getpass.getpass`. `getpass` reads from the controlling terminal
    directly: never argv, never stdin pipe, never the parent
    process's view of file descriptors. `EOFError` /
    `KeyboardInterrupt` exit cleanly with rc=2.
  - `store-credentials` and `validate-credentials` gain
    `--prompt-token` flags that drive the prompt path. Existing
    automation that pipes the token via stdin still works (back-compat
    preserved) but the new agent-facing flow is `--prompt-token`.
  - `validate-project` gains `--from-env`, which reads the token from
    `~/.claude-workbench/.env` (where step 1's `store-credentials`
    wrote it) instead of stdin. This lets `/kanban:initjira` step 2
    validate the project + board without piping the token through
    a Bash command at all.

  **Slash command flow change**: `/kanban:reset-credentials` step 3
  and `/kanban:initjira` step 1 are now USER-DRIVEN — the agent
  prints a block of instructions for the user to run in their own
  terminal:

  ```
  python3 .../jira_setup.py store-credentials \
    --base-url "<URL>" --email "<EMAIL>" --prompt-token
  ```

  The user runs this, sees `Jira API token:` (no echo), pastes,
  presses Enter. The token never traverses the agent's Bash tool, so
  it never appears in the conversation transcript. The agent then
  verifies via `read-credentials` (no token in argv) + `/kanban:whoami`
  (token read from `.env`).

  Both commands now carry an explicit absolute rule: "**NEVER** call
  the Bash tool with a command that contains the token literal" — and
  "**NEVER** ask for the token via `AskUserQuestion`" (the user's
  response is also part of the conversation log).

  Phase 24 covers six cases: `_read_token(prompt=True)` reads from
  getpass and strips whitespace; clean abort on EOF/Ctrl-C;
  `store-credentials --prompt-token` writes to `.env` without touching
  stdin; back-compat — stdin path still works without the flag;
  `validate-project --from-env` reads from `.env`, never stdin;
  missing-token-in-`.env` fails with a `reset-credentials` hint.

### Fixed
- Phase 3's `_setup_cmd` now defaults `HOME` to a throwaway directory
  so a real `~/.claude-workbench/.env` on the test machine doesn't
  trigger live Jira API calls and mask the offline-only assertions
  (e.g. fuzzy-collision check). Symptom on a developer machine with
  an existing `.env`: `register-ap` saw real credentials, hit the
  Jira instance, got 404 / 401, and `register_ap_fuzzy_no_force`
  failed with a network error instead of returning the expected
  fuzzy-match warning.

## 2026-05-03 (kanban same-repo-different-machine UX)

### Changed
- **kanban 0.3.17** — documentation + slash-command guidance for the
  "same repo cloned on a new machine" flow. No code or test changes;
  pure UX clarity.

  Background: `kanban.json` is committed by `kanban-autocommit.sh` and
  travels with the repo via git. In Jira mode it carries the full
  `backend.jira` block (transitions, projectKey, ap.fieldId,
  conventions) — i.e. the same payload `/kanban:showjira-code` would
  emit, except git is the transport. The only legitimately
  per-machine state is the API token in `~/.claude-workbench/.env`.
  So when you `git clone` (or `git pull`) a repo that's already in
  Jira mode on a new machine, you do NOT need to re-paste the code
  — you just need to capture this machine's token.

  But the existing docs hid that. The Multi-machine cheatsheet only
  listed "new repo" / "teammate joining" scenarios; readers reached
  for `/kanban:import-jira-code` and re-pasted redundantly.
  `/kanban:reset-credentials` was the right tool but its description
  framed it purely as "rotate Jira credentials," not "first-time
  setup on this machine for an existing repo."

  Fixed:

  - `commands/reset-credentials.md` description and body now spell
    out both use cases: first-time-on-this-machine setup AND token
    rotation.
  - `commands/import-jira-code.md` step 0 now detects when
    `backend.jira` already has a non-empty `transitions` map (the
    git-pull signal) and proactively suggests `/kanban:reset-credentials`
    before doing a wholesale re-import. Default no on the "continue
    anyway" prompt — the import will replace `backend.jira` wholesale,
    which is rarely what someone wants when their config came from
    git.
  - `kanban_quickstart.md` + `kanban_quickstart_zhtw.md` cheatsheet
    gains a new row: "Same repo, different machine → `git pull` +
    `/kanban:reset-credentials`." A blockquote underneath explains
    why this works (autocommit hook + git transport).

## 2026-05-03 (kanban command renames + scope narrowing)

### Changed
- **kanban 0.3.16** — two slash command renames; the helper subcommands
  and overall framing now match what the commands actually do. Closes
  #33 and #34.

  **`/kanban:next` → `/kanban:doing` (Jira mode only).** The old name
  implied a single-step "pick the next task" model, but the actual
  workflow on a multi-card AP is "agent works through every card the
  owner has placed in DOING, reasoning across them." The new command
  reads only `status=DOING AND assignee=this-AP` cards (helper:
  `list-doing`) and never pulls from TODO. The state machine the plugin
  enforces:

  ```
  TODO  ──(owner moves)──▶  DOING  ──(/kanban:doing executes)──▶  DONE
  ```

  - **TODO → DOING is the owner's call** (Jira UI, or the owner's own
    `/kanban:transition`). The agent must never pull from TODO unless
    an explicit @-mention from the owner names a card with start intent.
  - The token-cost win is real: 11 open TODOs were being scanned by
    the old auto-pick to choose one card; the new command only reads
    the (small) DOING set.
  - Local mode keeps its `/kanban:next` semantics — local has no AP
    routing, the pick-one model is still right there.
  - `/kanban:next` becomes a deprecation shim for one release cycle:
    in Jira mode it prints a notice and stops; in local mode it forwards
    to the existing helper.

  **`/kanban:initjira-by-code` → `/kanban:import-jira-code`.** The
  helper has always been called `import-jira-code` — the slash command
  now matches. The new name also makes obvious that the command is
  not just first-run init: it works for re-sync too. To smooth the
  re-sync path:

  - Step 3 (AP) is now idempotent: when `.claude/kanban-agent.json#ap`
    is set AND the AP still appears in `live-list-aps`, the prompt is
    skipped and a one-line confirmation is printed. Re-import after a
    `/kanban:edit-conventions` change becomes friction-free.
  - The conventions ack-hash mechanism (forces re-ack when notes
    drift) is preserved — that's the team-drift safety net.
  - `/kanban:initjira-by-code` becomes a deprecation shim that prints
    a notice and forwards.

  Cross-references throughout the repo were updated:
  README/quickstart, `kanban-jira-agent` SKILL, and Jira-flavored
  commands (`initjira`, `create-sub`, `mentions`, `reconcile`,
  `fix-ap-screen`) now point at `/kanban:doing` and
  `/kanban:import-jira-code`. Generic / local-mode docs keep
  `/kanban:next` (still correct in local mode).

  New phase 23 covers the helper: list-doing returns DOING-only cards
  filtered by AP; empty-DOING is `ok=true` with empty list (slash
  command then says "owner needs to move a TODO into DOING"); missing
  repo AP fails with the assign-ap nudge; local backend is refused.
  All 23 phases green.

## 2026-05-03 (kanban set-conventions incremental flags)

### Added
- **kanban 0.3.15** — `set-conventions` accepts three new flags for
  incremental mutation, mutually exclusive with the existing
  `--conventions-json` full-replace mode. Closes #36.

  - `--append-note "..."` — append a note to `conventions.notes`.
    Idempotent: exact-text duplicates of existing notes are silently
    skipped, so slash-command flows that re-run on the same input
    won't double up. Repeat the flag to append several notes in one
    call.
  - `--remove-note "..."` — drop a note by exact-text match. Notes
    that don't exist are a no-op.
  - `--set-toggle KEY=VALUE` — set a single toggle (e.g.
    `blockedRequiresLink=false`). Booleans are recognised
    case-insensitively (`true` / `TRUE` / `false` / `FALSE`);
    everything else is stored as a string.

  Why this matters: the original `--conventions-json` mode required
  callers to faithfully reproduce the entire block to add a single
  rule. For LLM-driven slash-command flows that round-trip is risky —
  an agent that paraphrases an existing note on the way through
  silently overwrites it ("why did this rule disappear" mysteries).
  The incremental flags let callers atomically mutate the block
  without reproducing existing material.

  Phase 22 covers seven cases: append idempotency, remove no-op when
  absent, toggle bool conversion (case-insensitive), mutual
  exclusion with `--conventions-json`, "require at least one mode"
  guard, full-replace back-compat, and a combo call exercising all
  three incremental flags together.

## 2026-05-03 (kanban create_task fixup PUT)

### Fixed
- **kanban 0.3.14** — `create_task` now re-asserts `labels` via a
  follow-up `PUT /rest/api/3/issue/{key}` after the initial POST.
  Closes #35.

  Jira filters the `POST /rest/api/3/issue` body against the project's
  Create Screen for the target issuetype: fields not on that screen
  (commonly `labels` and AP custom fields on Story / Sub-task / Task)
  are silently elided. The API returns 201 with a key, the plugin
  treated that as success, and the requested fields didn't stick. In
  one reporter's session 26 of 28 created issues lost their labels
  this way — invisible to `/kanban:next` (AP filter) and to JQL like
  `labels = "<value>"`.

  The Edit Screen is generally more permissive than the Create Screen,
  so a follow-up PUT against the same key recovers most cases. The
  fixup is best-effort: a failure leaves an audit comment but does not
  roll back the create — users prefer "labels missing on this card"
  over "no card at all". Cost is at most one extra HTTP request per
  create; for `import-tasks` bulk runs this is acceptable.

  Phase 21 covers four cases: PUT carries the requested labels; no
  PUT fires when there are no tags; PUT failure posts a system comment
  and create still returns successfully; fixup PUT fires before the
  parent-link POST so a later link failure can't mask a prior fixup
  failure.

## 2026-05-02 (kanban health oracle + notes guardrail)

### Fixed
- **kanban 0.3.13** — `/kanban:initjira-by-code` step 1 was using
  `health` as the oracle for "are Jira credentials present?", but at
  that point `kanban.json#backend.driver` is still `"local"` (nothing has
  switched it to `"jira"` yet) so health runs against `LocalDriver` —
  which has nothing Jira-related to check and unconditionally returns
  `ok=true`. Callers silently bypassed credential capture; the failure
  was masked further by `import-jira-code` succeeding offline (it only
  writes config), surfacing only at `live-list-aps` several steps later
  with an empty roster. Closes #31.

  - `commands/initjira-by-code.md` step 1 now uses `read-credentials`
    + checks `tokenPresent` (the same pattern `initjira.md` was already
    using). Documents the trap explicitly so future readers don't repeat
    it: "Do **not** use the `health` helper as the oracle here".
  - `cmd_health` (`scripts/jira_setup.py`) appends a self-documenting
    hint to `detail` when the active driver is local: `"local driver —
    Jira credentials not checked; use read-credentials"`. `ok` stays
    `true` because the local driver IS healthy in its own right —
    flipping it would break `/kanban:init`'s legitimate post-init
    health check. The hint surfaces the misuse to anyone who prints
    `detail`.
  - Phase 20 covers the new behavior: `cmd_health` on a local-backend
    `kanban.json` returns `ok=true` with `local driver` + `read-creden\
tials` in `detail`; on a `jira` backend the local-driver hint is NOT
    appended (so it can't pollute real auth-failure messages).

### Changed
- **kanban 0.3.13** — `conventions.notes[*]` guardrail bumped 300 → 1024
  chars per note. Notes are increasingly carrying richer narrative
  (multi-sentence team-pattern descriptions, links to ADRs / SOPs);
  300 was too tight in practice. The guardrail is still a warning, not
  an error — reasonable long-form material stays in ADRs, but a single
  paragraph of context now fits without tripping the linter. Phase 11
  test thresholds adjusted (1100 chars → over, 900 → under).

## 2026-05-02 (mentor session-end summary opt-out)

### Added
- **mentor 0.2.3** — `agent_behavior.session_end_summary` flag in
  `mentor.yaml`. Default `true` preserves prior behavior; set to `false`
  to silence the Stop-hook user-visible summary. Closes #29.

  Stop hooks fire on every turn boundary in Claude Code, not just at
  true session end, so `mentor-finalcheck.py` was reprinting the same
  20-line "Documents touched this session" + violations block after
  every assistant reply — drowning out the actual end-of-turn message
  for doc-heavy projects (active Sprint planning, ADR drafting).
  Previously the only way to silence it was to disable the entire
  `mentor` plugin, losing SessionStart bootstrap, PreToolUse mentor-
  guard, and all `/mentor:*` skills along with it.

  The flag gates only the user-visible `systemMessage` print. The
  side effects in the same hook — `_fanout_memory` (Sprint retro / ADR
  capture into workbench-memory) and `review()` — keep running, since
  they're governed by separate knobs (`integration.memory_save_*`) and
  are no-ops when nothing's transitioned. One knob, one job.

  `mentor.example.yaml` carries a commented-out `session_end_summary:
  true` line so users discover the knob; the schema declares it under
  `agent_behavior.properties` (the schema is `additionalProperties:
  false`, so without the declaration the field would be rejected).

## 2026-05-02 (locale + JQL + ADF fixes)

### Fixed
- **kanban 0.3.12** — three orthogonal regressions surfaced after the
  morning's #16–#21 batch shipped. Closes #17 (re-opened), #26, #27.

  - **#17 transition lookup is now locale-immune.** The `Accept-Language:
    en-US` header added in 0.3.9 fixed JQL paths but does NOT untranslate
    the `to.name` field on `/transitions` responses — Atlassian still
    returns localized status names (e.g. `審查` for `REVIEW` on a zh-TW
    account) even with the header. `transition()` now matches by the
    transition action name (`t["name"]`, English-canonical regardless of
    UI locale) first, falling back to `t["to"]["name"]` for English-locale
    accounts whose action and status names differ. Same root cause hit
    `/kanban:reconcile`: it compared raw `status.name` against DSL names
    client-side. The fix moves the filter server-side via JQL `status
    not in (mapped_statuses)`, which JQL evaluates against canonical
    English regardless of UI locale. One JQL query instead of two; the
    localized status name in the response is used only for grouping in
    the diagnostic output (cosmetic).

  - **#26 `find-mentions` always returned 0.** `_jql_quote_ts()` was a
    passthrough that handed Jira full ISO-8601 strings with timezone
    offsets (`2026-05-02T11:44:37+08:00`) — JQL silently rejects this
    format and returns 0 results with no error. Now normalizes to JQL's
    canonical `yyyy-MM-dd HH:mm` via `datetime.fromisoformat`. Same
    `_jql_quote_ts` site is reused by `cmd_sync_summary`'s mentions
    block, which had the same bug.

  - **#27 agent comment prefix rendered broken in Jira UI.** The SPEC §9
    prefix was authored as a markdown literal (`**[ap] [kind]**`) and
    embedded into a single ADF text node; ADF doesn't parse markdown,
    so Jira's renderer emitted raw `**` plus broken `<span class="error">`
    around the brackets. The prefix is now an ADF text node with a
    `strong` mark in its own paragraph, with the body in a second
    paragraph. `_PREFIX_RE` now accepts both forms (old comments still
    parse). The same fix applies to `text_to_adf_with_mention` so
    `/kanban:reply` renders correctly.

  Tests: phase 19 covers transition action-name fallback (with both
  zh-TW and English locale workflows), reconcile's locale-immune JQL
  shape, `_jql_quote_ts` normalization (incl. quote-injection refusal),
  and ADF strong-mark prefix on both no-mention and mention paths.
  Phase 18 mocks updated to mirror the new server-side filter (mapped
  cards never reach the client); phase 2's `post_comment_prefixes`
  asserts the new ADF shape directly. All 19 phases green.

## 2026-05-02 (drift visibility)

### Added
- **kanban 0.3.11** — `/kanban:reconcile` slash command and a one-line
  drift reminder in `/kanban:sync`. Closes #21 (and the visibility
  story for the whole #16-#21 batch).

  Problem: cards can land in Jira statuses NOT mapped by the DSL — via
  manual UI moves, automation rules, or mistakes. Such cards were
  completely invisible to `/kanban:status`, `/kanban:next`, and
  `cmd_sync_summary`. Same for cards that have no AP set at all
  (manual creation in Jira UI, broken init flow, etc.) — they were
  silently excluded from the AP-filtered queries.

  In the reporter's session, 7 cards drifted to a `TO PROGRESS` status
  the DSL didn't map; the migration looked successful but those cards
  were silently orphaned until manual JQL detective work surfaced them.

  Fix:

  - **`cmd_reconcile`** runs two read-only JQL queries:
    1. `project = X AND cf[ap] = repo_ap AND statusCategory != Done`
       — my-AP cards; group by status name; flag any not in the
       transitions[*].status set as `unmapped`.
    2. `project = X AND cf[ap] is EMPTY AND statusCategory != Done`
       — open cards with no AP set (`missingAp`).
    Returns `{unmapped: {<status>: [keys]}, missingAp: [keys],
    totalUnmapped, totalMissingAp, errors, hint}`.
  - **`/kanban:reconcile`** slash command renders the result with
    suggested next steps (re-run `/kanban:initjira` step 3 to map
    missing statuses; or move cards back to mapped statuses).
  - **`cmd_sync_summary`** appends a single-line reminder when there's
    drift: `[drift — run /kanban:reconcile for details] N in unmapped
    statuses, M with no AP`. Best-effort: detection failures are
    silent so the rest of sync still prints.
  - Read-only — never modifies anything. Pair-mode reminder: this is
    diagnostic, not remediation. The user decides what to do based on
    the report.
  - `test_phase18.py`: 10 mocked cases covering the JQL-id helper,
    detector grouping, graceful skips when repo_ap or ap_field_id
    missing, error collection, hint generation, sync-summary
    integration both ways.
  - bumps 0.3.10 → 0.3.11. All 18 phase suites (183 tests) green.

## 2026-05-02 (assignee-aware self-approve + guardrail bump)

### Changed
- **kanban 0.3.10** — two behaviour-tuning fixes from real BZK board use:

  - **(#19)** Anti-self-approve now considers `assignee` alongside the
    AP custom field. Previously, refusing DONE only required
    `card.ap == repo_ap` — too strict when the agent is recording work
    completed by a human teammate (assignee = the human). The agent
    isn't approving its own work in that case; it's recording the
    human's completion.

    The new rule:

    | `card.ap` | `assignee` | DONE allowed? |
    |---|---|---|
    | mine | agent's own account | NO (refuse) |
    | mine | None (unassigned) | NO (refuse, strict default) |
    | mine | a different account (human teammate) | YES (allow) |
    | other / nil | anything | YES (allow) |

    Refusal message now hints at the workaround: "assign the card to
    that human first if you are recording on their behalf."

  - **(#20)** `conventions.notes[]` length guardrail bumped 200 → 300
    chars. Compound rules like `"REVIEW = ball in user court. (A) ...
    (B) ... Don't confuse with BLOCKED for ..."` consistently exceeded
    200 in real use; splitting them across multiple notes lost the
    connecting logic. 300 covers typical compound clauses; over that,
    move to an ADR.

  Both are advisory-level tweaks (no API change, no schema change).

  - `test_phase17.py` (5 cases): all four canonical
    AP/assignee combinations + workaround hint in error message.
  - phase 7's `test_self_approve_refused_v03` updated: mock issue's
    assignee changed from `kirin-acct` → `shared-agent` to match the
    new "refuse only when assignee is the agent itself" rule.
  - phase 11 guardrail tests updated for 300-char threshold.

  All 17 phase suites (173 tests) green. Bumps 0.3.9 → 0.3.10.

## 2026-05-02 (locale-stable Jira responses)

### Fixed
- **kanban 0.3.9** — JiraClient now sends `Accept-Language: en-US` on
  every request. Closes #17. The plugin's DSL stores status / priority /
  issue-type names in English; without this header, an agent account
  with non-English UI locale (e.g. zh-TW) caused Jira to return
  localized names like `進行中` for `In Progress`, and:

  - `transition --to REVIEW` failed with `no Jira workflow transition
    leads to status 'Resolved'` (because the response had `已解決`)
  - `import-tasks` priority validation drifted (returned localized
    priority names that didn't match user input)
  - any other lookup that string-matched against status/priority/type
    names was at risk

  The fix is one line in `lib/jira_client.py:_request` — adding the
  header. Workflows whose underlying status names are non-English
  (e.g. an actual zh-TW project where the admin defined statuses in
  Chinese) are unaffected, because Jira only translates English source
  names; non-English source has no English to translate to.

  This also affects #18's priority validation, which is now reliable
  across locales as a bonus.

  - `test_phase16.py`: 7 cases covering header presence on GET / POST /
    PUT, header coexistence with existing Authorization / Accept /
    Content-Type, header on 429 retry path, end-to-end transition
    lookup. All 16 phase suites (168 tests) green.
  - bumps 0.3.8 → 0.3.9

## 2026-05-02 (import-tasks completeness)

### Fixed
- **kanban 0.3.8** — `import-tasks` now produces fully-functional Jira
  cards instead of orphaned ghosts. Closes #16 + #18. Two related bugs
  surfaced together while migrating 22 local tasks to a real Jira board:

  - **(#16)** Imported issues had `customfield_<APFieldId> = null`,
    `assignee = null`, and stayed in the project's default initial
    status (e.g. `Backlog`) — so `/kanban:status` and `/kanban:next`
    couldn't see them. The migration looked successful but the cards
    were invisible to the plugin.
  - **(#18)** Local `P0..P3` priorities were passed verbatim, but
    Jira's default priority scheme uses `Highest/High/Medium/Low/Lowest`.
    Every issue failed individually with HTTP 400 before the user saw
    any signal that the whole batch would fail.

  Fix:

  - **Pre-flight priority validation** via `client.get_priorities()`
    (`GET /rest/api/3/priority`). Auto-map `P0..P4 → Highest..Lowest`
    when both ends are valid in the project's scheme. Fail-fast with
    one actionable error listing unmappable values + valid scheme,
    BEFORE any issue gets created.
  - **Post-create AP + assignee** via `driver.assign(AgentRef(ap=repo_ap))`
    — sets the AP custom field AND the agent assignee account in one
    API call (existing helper, already does both).
  - **Post-create transition to TODO** via
    `driver.transition(key, "TODO")` — moves the new card out of the
    project default status into the canonical TODO mapped by DSL.
  - **BLOCKED-origin audit comment** — when a local task was BLOCKED,
    the imported card lands in TODO (unified target) but a system
    comment preserves the original `blocked_reason` so context isn't
    lost.
  - **Per-task best-effort** — assign / transition failures don't
    abort the whole batch. Each result entry surfaces `apSet` /
    `apError` / `transitioned` / `transitionError` flags so the user
    knows exactly which post-create steps succeeded.
  - **Dry-run** still skips all writes; pre-flight still runs and
    surfaces resolved priorities so the user can preview the mapping.
  - **Pass-through** when credentials are missing — the priority
    pre-flight is skipped silently and the existing create-time-error
    path is preserved (so cli use without `~/.claude-workbench/.env`
    behaves as before).
  - `test_phase15.py`: 13 new mocked cases covering `_resolve_priority`
    in all 5 modes, pre-flight rejection (no creates), auto-map
    P1→High end-to-end, post-create assign + transition, BLOCKED
    audit comment, per-task best-effort on failures, dry-run, skip
    logic, no-credentials pass-through. All 15 phase suites
    (161 tests) green.

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
