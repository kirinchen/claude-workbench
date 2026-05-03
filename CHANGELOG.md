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
