# UPDATE: kanban plugin — Jira backend driver

> **Status**: final v0.1
> **Targets**: kanban plugin v0.2.0
> **Compatibility**: 100% backwards-compatible — existing local-mode users unaffected
> **Related**: `SPEC.md` §kanban, `plugins/kanban/`, `schema/kanban.schema.json`,
> `plugins/notify/` (referenced for credential storage convention)

---

## 1. Why

The `kanban` plugin currently uses a single backend: a project-local
`kanban.json` file. This is excellent for solo work and prototyping but has
three structural limits when multiple humans + multiple AI agents collaborate
across machines:

1. **No cross-machine sync.** Each repo's `kanban.json` is local. Sharing means
   committing it, which conflicts on every transition.
2. **No native human UI for non-developers.** Non-technical owners want a
   phone app to approve work. Building one means writing a server.
3. **No real audit trail across actors.** `kanban.json` records the current
   state, not who-did-what-when across distributed sessions.

Building a self-hosted backend (Postgres + Hono + SSE + SSH+tmux poke, as
explored in earlier drafts) solves all three but costs ~1 week of work and
introduces ops burden.

**Resolution:** Add Jira Cloud as a second `kanban` backend driver. Jira
already provides cross-machine sync, mobile UI, audit log, permissions,
notifications, and SaaS reliability — for free up to 10 users. The `kanban`
plugin keeps its existing slash command surface; only the storage layer
changes.

This update introduces:

- **Driver abstraction** so `kanban.json` (local) and Jira (cloud) implement
  the same contract.
- **`/kanban:initjira`** to switch a project to Jira mode.
- **Agent Property (AP)** — a single Jira custom field that distinguishes
  which AI agent owns a card (humans use the native `assignee`; agents share
  one Jira account and are disambiguated by AP value).
- **Auto-detection rule** — when an agent's prompt contains a Jira card key or
  URL, the plugin runs a pre-flight check before the agent acts on it.
- **Bundled skills** — agent-facing and owner-facing instruction sets that
  teach Claude how to use the plugin, including a strict prohibition on
  bypassing it via other Jira MCP servers.

---

## 2. Non-goals

- **Push-based wake-up (SSH+tmux poke).** Pull is sufficient when triggered by
  slash commands and Claude Code hooks. Realtime feedback to humans is
  delegated to `notify` plugin.
- **Multi-driver per project.** Each project picks one driver (`local` or
  `jira`). Migration path is documented but a project does not run both
  simultaneously.
- **Replacing `assignee`.** Humans still go in Jira's native `assignee` field.
  AP is **only** the disambiguator for the shared agent account.
- **Two-way sync between local and jira modes** within one project.
- **Bundling or recommending an external Jira MCP server** (Atlassian Rovo,
  `mcp-atlassian`, etc.) — see §18 for why this is structural, not
  circumstantial.

---

## 3. Data model

### 3.1 Driver abstraction

`plugins/kanban/drivers/<name>.py` implements:

````python
class Driver(Protocol):
    name: str  # 'local' | 'jira'

    def health(self) -> HealthResult: ...
    def list_tasks(self, filter: TaskFilter) -> list[Task]: ...
    def get_task(self, key: str) -> Task: ...
    def create_task(self, task: TaskInput) -> Task: ...
    def transition(self, key: str, to_status: str, **kwargs) -> Task: ...
    def post_comment(self, key: str, body: str, kind: CommentKind) -> Comment: ...
    def list_comments(self, key: str) -> list[Comment]: ...
    def assign(self, key: str, member: MemberRef) -> Task: ...
    def list_members(self) -> list[Member]: ...

    # Optional capabilities — drivers may raise NotSupported
    def list_aps(self) -> list[str]: ...           # jira-only in v1
    def register_ap(self, name: str) -> None: ...  # jira-only in v1
````

`MemberRef` is the union
`{ kind: 'human', accountId: str } | { kind: 'agent', ap: str }`. The local
driver implements `human`/`agent` as plain strings. The jira driver maps
`human` → `assignee` and `agent` → `assignee=<shared agent account>` plus the
AP custom field.

### 3.2 `kanban.json` schema additions

A new top-level section `backend` selects the driver. Existing fields are
unchanged.

````json
{
    "version": "0.2",
    "backend": {
        "driver": "jira",
        "jira": {
            "boardUrl": "https://yourteam.atlassian.net/jira/software/projects/AGENT/boards/1",
            "projectKey": "AGENT",
            "agentAccountId": "557058:abc...",
            "ap": {
                "fieldId": "customfield_10042",
                "fieldName": "Claude Agent",
                "registered": ["agent-fin-exchange", "agent-quant-bot"]
            }
        }
    },
    "tasks": [],
    "meta": {}
}
````

When `backend.driver = "local"` (default for backwards-compat), `tasks` keeps
its existing shape and the plugin behaves exactly as v0.1.x. When
`backend.driver = "jira"`, `tasks` is **not used** — it is ignored on read and
not written to. (Rationale: avoid dual-write inconsistency. The single source
of truth becomes Jira.)

### 3.3 Secrets

API tokens and the agent account email **never** go into `kanban.json` and are
**never** edited by the user manually. They live in `~/.claude-workbench/.env`,
treated as plugin-internal storage — same model as `notify`.

Storage path:

````
~/.claude-workbench/.env
````

Variables owned by the kanban jira driver:

````
JIRA_BASE_URL          # e.g. https://yourteam.atlassian.net
JIRA_AGENT_EMAIL       # shared agent Atlassian account
JIRA_API_TOKEN         # API token for the shared agent account
````

Lifecycle rules:

- **Write**: only `/kanban:initjira` and `/kanban:reset-credentials` may write
  these keys. Both prompt inside the Claude session. The user pastes once.
- **Read**: only the plugin reads them at runtime; never echoed back to the
  session, never logged, never included in error messages (only `present` /
  `missing` / `invalid` is reported).
- **Update**: re-running `/kanban:initjira` re-prompts and overwrites *only*
  the `JIRA_*` lines. Other plugins' lines (Pushover, etc.) are preserved
  byte-for-byte.
- **Rotate**: `/kanban:reset-credentials` re-prompts and overwrites without
  touching anything else in `kanban.json`.
- **Inspection**: `/kanban:whoami` reports `Token: ✓ valid` or
  `Token: ✗ invalid (re-run /kanban:reset-credentials)` — never the value.

The user is **not expected** to know `~/.claude-workbench/.env` exists. It is
documented in spec only because someone debugging or migrating machines may
need to find it. Slash commands cover every normal flow.

If the file does not exist when a kanban command needs credentials, the
plugin prints exactly one line:

````
This project uses Jira mode but credentials are not configured on this machine.
Run /kanban:initjira to set up.
````

It does not prompt outside an init flow — credentials must be deliberately
entered, not lazily collected from random commands.

### 3.4 Agent identity (per repo)

Each repo writes `./.claude/kanban-agent.json`:

````json
{ "ap": "agent-fin-exchange" }
````

This is the only thing committed to git that identifies the agent. AP must
already exist in `kanban.json#backend.jira.ap.registered`; otherwise the
plugin refuses to operate and prints the registration command.

Whether to commit `kanban-agent.json` to git is a team convention (see open
question §16.2). The plugin reads from `./.claude/` regardless.

---

## 4. Slash commands

### 4.1 New: `/kanban:initjira`

Switches the current project from local mode to Jira mode. Idempotent —
re-runs overwrite the `backend` block; append-only on `.env`. Resumable: if
credentials are already valid from a previous interrupted run, Step 1 is
skipped automatically and the user is told why.

Interactive flow:

````
> /kanban:initjira

Step 1/5 — Jira credentials

  Paste these into this session — they are stored encrypted-at-rest by your
  OS keychain when available, otherwise in a plugin-internal config file.
  You will never need to edit them by hand.

  Base URL:                    https://yourteam.atlassian.net
  Shared agent account email:  agents@yourteam.com
  API token:                   ********  (hidden input)

  [validating]   GET /myself  → ✓ authenticated as Agent Bot
  [storing]      ✓ saved to plugin config

  Need to change these later? Run /kanban:reset-credentials.

Step 2/5 — Board URL
  Paste the board URL from Jira:
  > https://yourteam.atlassian.net/jira/software/projects/AGENT/boards/1
  [resolved]   project=AGENT, board=1

Step 3/5 — Workflow check
  Required statuses: TODO, DOING, BLOCKED, REVIEW, DONE, CANCELLED
  Found: To Do, In Progress, Done

  ⚠ 3 statuses missing. Add them in Jira project settings, then re-run.
  (or accept the partial mapping with --partial; degraded features
  documented in §7.)

Step 4/5 — Agent Property (AP) field
  This field distinguishes which AI agent owns a card.

  [a] Use existing field    (browse custom fields)
  [b] Create new field      (recommended, named "Claude Agent")
  Choice: b

  [creating]   ✓ customfield_10042 "Claude Agent" (single-select)
  [creating]   ✓ Field added to default screen for AGENT project

Step 5/5 — First AP registration
  Register the agent for *this* repo. You can register more later via
  /kanban:register-ap, or skip this step now and assign later via
  /kanban:assign-ap.
  AP name (alphanumeric + hyphens, lowercase): agent-fin-exchange

  [checking uniqueness]   ✓ new
  [adding option]         ✓ "agent-fin-exchange" added to Claude Agent
  [writing]               ✓ kanban.json#backend updated
  [writing]               ✓ .claude/kanban-agent.json (this repo's AP)

Final check — Jira MCP conflict scan
  [scanning]   user + project MCP scopes
  [result]     ✓ no conflicting Jira MCP servers detected

Done. This project now uses Jira. Existing kanban.json#tasks is preserved
but ignored. To use it again, set backend.driver = "local".

Try:
  > /kanban:status      (now reads from Jira)
  > /kanban:next        (picks next TODO from Jira)
````

Validations performed (each fail rolls back partial state):

1. `GET /myself` — token valid
2. `GET /project/{key}` — project exists, token has access
3. `GET /board/{id}/configuration` — board reachable
4. `GET /field` — custom field exists or can be created (requires admin)
5. AP name regex `^[a-z][a-z0-9-]{2,40}$` — strict
6. AP uniqueness — case-insensitive search through existing options
7. Jira MCP conflict scan — see §18.2

Resume behaviour: if the user previously ran `/kanban:initjira` and it
crashed/cancelled after Step 1 (credentials saved) but before Step 2
(`backend.driver` not yet `jira`), re-running prints:

````
Detected valid Jira credentials from previous run. Skipping Step 1.
(Run /kanban:reset-credentials if you want to re-enter them.)
Continuing from Step 2/5 — Board URL.
````

### 4.2 New: `/kanban:reset-credentials`

Re-prompts for Jira credentials and overwrites them. Use when the API token
is rotated, expired, or compromised. Never asks the user to find or edit any
file.

````
> /kanban:reset-credentials

  Current Base URL: https://yourteam.atlassian.net
  Current Email:    agents@yourteam.com
  Current Token:    ✗ invalid (last check 3m ago)

  Replace? (Y/n) y

  Base URL:        [enter to keep current]   _
  Email:           [enter to keep current]   _
  API token:       ********  (hidden input)

  [validating]   ✓ authenticated as Agent Bot
  [storing]      ✓ saved
````

This command does *not* touch `kanban.json`, AP registry, or any other
plugin's settings.

### 4.3 New: `/kanban:register-ap`

Add another AP without re-running full init.

````
> /kanban:register-ap agent-quant-bot

  [checking uniqueness]   ✓ new
  [fuzzy check]           ⚠ similar to existing: agent-quant
                          continue? (y/N)  y
  [adding option]         ✓ added to Claude Agent
  [writing]               ✓ kanban.json updated
````

Fuzzy check uses Levenshtein distance ≤2 against all existing AP names. The
warning is non-blocking — owner decides.

### 4.4 New: `/kanban:assign-ap`

Set the current repo's AP. Useful when one machine works on multiple repos
or when switching agents.

````
> /kanban:assign-ap agent-fin-exchange

  [validating]   ✓ exists in registered APs
  [writing]      ✓ .claude/kanban-agent.json
````

### 4.5 New: `/kanban:whoami`

Displays current state — AP, project, base URL, last sync. **Token value is
never displayed**, only validity status. Also reports any Jira MCP conflict
(see §18.2).

````
> /kanban:whoami

  Repo:        /home/kirin/code/fin-exchange
  Driver:      jira
  Base URL:    https://yourteam.atlassian.net
  Email:       agents@yourteam.com
  Project:     AGENT
  Board:       1
  AP (this repo):   agent-fin-exchange
  AP (registered):  agent-fin-exchange, agent-quant-bot
  Token:       ✓ valid (last checked 14s ago)
  Jira MCP:    ✓ no conflicts detected
````

The `Token` line shows exactly one of: `✓ valid`, `✗ invalid`, `? unknown`.
No prefix, suffix, or character-count is leaked.

### 4.6 New: `/kanban:question`

Post a question to the current task and transition it to BLOCKED. Maps to
the spec's `?block=true` semantics.

````
> /kanban:question AGENT-42 "should v1 API stay backward-compatible?"

  [posting]     ✓ comment added (kind=question)
  [transition]  ✓ AGENT-42: In Progress → Blocked
  [audit]       wrote system comment with AP attribution
````

### 4.7 New: `/kanban:sync`

Pulls open cards for the current AP and posts a summary into the session.
Also runs automatically on `SessionStart` (see §6).

````
> /kanban:sync

  [fetching]   AGENT project, AP=agent-fin-exchange
  [found]      3 open cards

  AGENT-42  Blocked     "auth refactor"        (open question from kirin)
  AGENT-51  In Progress "v1 deprecation plan"
  AGENT-58  To Do       "wire dynamic-rate"    P1, just assigned by alice

  Suggested next: AGENT-58 (highest priority, unblocked)
````

### 4.8 Existing commands — driver-aware behaviour

`/kanban:init`, `/kanban:status`, `/kanban:next`, `/kanban:done`, etc. all
gain driver dispatch. The user-facing surface is unchanged. Behaviour
differences in jira mode are documented in §7 (graceful degradation table).

`/kanban:next` in jira mode runs:

````jql
project = AGENT
  AND "Claude Agent" = "agent-fin-exchange"
  AND status = "To Do"
  AND issuetype = Task
ORDER BY priority DESC, created ASC
````

then transitions the picked issue to DOING and writes a system comment
`[agent-fin-exchange] [S] claimed`.

---

## 5. Auto-detect: Card key / URL in agent prompts

When the agent or user mentions a Jira card in any context, the plugin
intercepts before the agent acts.

### 5.1 Detection patterns

````
KEY:    \b[A-Z][A-Z0-9_]+-[0-9]+\b           e.g. AGENT-42, FIN-103
URL:    https?://[^/]+/browse/[A-Z][A-Z0-9_]+-[0-9]+
URL:    https?://[^/]+/.*[?&]selectedIssue=[A-Z][A-Z0-9_]+-[0-9]+
````

Project key prefix must match `backend.jira.projectKey` to avoid false
positives from unrelated repos / past chats.

### 5.2 Hook wiring

Two Claude Code hooks:

**`UserPromptSubmit`** — when the user types something containing a card
reference, plugin runs precheck and prepends a context block to the prompt
that the agent will read:

````
[kanban context for AGENT-42]
  Status:        Blocked
  AP:            agent-quant-bot   ⚠ NOT YOU (you are agent-fin-exchange)
  Last update:   2h ago by alice (human)
  Open question: "should v1 API stay backward-compatible?"

  Suggested action: do NOT modify this card; if you need to take it over,
  run /kanban:assign-ap-of-task AGENT-42 first.
````

**`PreToolUse`** for tools that touch files / git — when the model is about
to write code referencing a card key in commit messages or branch names,
run the same check; abort with code 2 (feedback to model) if AP mismatch.

### 5.3 Precheck rules

For each detected card, fetch once (cached 30s per session) and evaluate:

| Check | If true |
|---|---|
| Card not found in project | warn, continue |
| AP empty | inject "unassigned" context, no block |
| AP = current repo's AP | inject normal context, proceed |
| AP = different registered agent | **inject ⚠ warning**, suggest reassignment command |
| Status = DONE or CANCELLED | inject "card is closed" warning |
| Status = REVIEW and current actor is the AP | inject "this card is awaiting human review, do not edit" warning |
| Open question without answer | inject the question text + "consider answering before continuing" |

The plugin never silently auto-claims a card on the user's behalf. It surfaces
context; the agent decides.

### 5.4 Cache semantics

- Cache scope: per Claude Code session.
- TTL: 30 seconds per card key.
- Invalidation: any plugin-issued write (`transition`, `post_comment`,
  `assign`) clears the entry for that card immediately.
- Trade-off: if owner changes a card in Jira UI within the 30s window after
  agent fetched it, agent's context is briefly stale. Acceptable —
  `SessionStart` always re-syncs from authoritative Jira state, and the
  upper bound on staleness is short.

---

## 6. Polling / sync

Pull only. Three trigger sources:

1. **`SessionStart` hook** — runs `/kanban:sync` automatically. Pulls open
   cards for current AP, posts summary to session.
2. **`UserPromptSubmit` hook with stale-detection** — if last sync >5 min
   ago, silently re-sync before processing the prompt.
3. **Explicit `/kanban:sync`** — user-initiated.

No background daemon. No tmux poke. Push-style notification (when owner
approves a card) is delegated to `notify` plugin via `kanban × notify`
integration (§13): owner sees the change immediately on their phone via
Pushover; the agent sees it the next time its session is active. If the
agent is idle, the owner's decision waits until the agent next interacts —
acceptable trade-off documented in §2 non-goals.

---

## 7. Graceful degradation table

When `backend.driver = "jira"` is selected, the workflow may not have all six
canonical statuses. Mapping rules:

| kanban concept | Jira full | Jira partial (3 statuses) | Local mode |
|---|---|---|---|
| TODO | "To Do" | "To Do" | TODO |
| DOING | "In Progress" | "In Progress" | DOING |
| BLOCKED | "Blocked" | (collapses to In Progress + label `kanban:blocked`) | BLOCKED |
| REVIEW | "In Review" | (collapses to In Progress + label `kanban:review`) | REVIEW |
| DONE | "Done" | "Done" | DONE |
| CANCELLED | "Cancelled" | (collapses to Done + label `kanban:cancelled`) | CANCELLED |

When labels substitute for statuses, transitions write the label and post a
system comment so the audit trail stays readable. `/kanban:initjira` warns
loudly when running in partial mode.

Capabilities `local` driver does not implement (raise `NotSupported`):
`list_aps`, `register_ap`, board URL resolution, attachments, sub-tasks.

Capabilities `jira` driver gains: native multi-user `assignee`, mobile app,
SSO, audit log, custom fields, sprint, epic linking (read-only in v1).

---

## 8. Anti-self-approve enforcement

Spec invariant: a worker cannot approve their own card. Enforcement layers:

| Layer | Mechanism | Strength |
|---|---|---|
| Jira workflow condition | `currentUser() != "{agent_account_id}"` on REVIEW → DONE transition | server-enforced, plugin cannot bypass |
| Jira workflow condition | `currentUser() != assignee` (covers human self-approve) | server-enforced |
| Plugin pre-flight | Before calling transition API, refuse if `task.ap == current_repo_ap` | client-side, fast feedback |

Both Jira-side conditions are configured by `/kanban:initjira` step 3 if admin
permissions are present; otherwise the command warns and falls back to
plugin-only enforcement (clearly marked).

---

## 9. Comment authoring

All API calls from the plugin use the shared agent account, so Jira's
`author` field will always be that account when an agent writes. Real human
authorship is preserved (humans use their own Jira accounts via the UI, not
the plugin).

For agent-written comments, the plugin prepends a structured prefix to the
ADF body:

````
**[agent-fin-exchange] [Q]**

Should v1 API stay backward-compatible? Line 47 of auth/legacy.ts has an
ambiguous deprecation warning.
````

Prefix grammar:

````
\*\*\[(?P<ap>[a-z][a-z0-9-]+)\] \[(?P<kind>Q|A|C|S)\]\*\*\n\n
````

where `C` = comment, `Q` = question, `A` = answer, `S` = system.

`list_comments` parses this prefix on read to reconstruct AP attribution. If
prefix is absent (humans replying via Jira UI), author is the human's Jira
display name, kind is inferred (`A` if last agent comment was `Q`, else `C`).

---

## 10. Plugin layout

````
plugins/kanban/
├── .claude-plugin/
│   └── plugin.json                          # bump to 0.2.0
├── commands/
│   ├── kanban-init.md                       # existing, driver-aware
│   ├── kanban-initjira.md                   # NEW
│   ├── kanban-reset-credentials.md          # NEW
│   ├── kanban-register-ap.md                # NEW
│   ├── kanban-assign-ap.md                  # NEW
│   ├── kanban-whoami.md                     # NEW
│   ├── kanban-question.md                   # NEW
│   ├── kanban-sync.md                       # NEW
│   ├── kanban-status.md                     # existing, driver-aware
│   ├── kanban-next.md                       # existing, driver-aware
│   └── kanban-done.md                       # existing, driver-aware
├── drivers/
│   ├── __init__.py                          # NEW — driver registry
│   ├── base.py                              # NEW — Protocol definitions
│   ├── local.py                             # NEW — extracted from existing
│   └── jira.py                              # NEW
├── hooks/
│   ├── kanban-guard.sh                      # existing
│   ├── card-detect.sh                       # NEW — UserPromptSubmit
│   └── session-start-sync.sh                # NEW — SessionStart
├── lib/
│   ├── jira_client.py                       # NEW — REST + retry/backoff
│   ├── ap_registry.py                       # NEW — uniqueness + fuzzy match
│   ├── card_parser.py                       # NEW — key/URL extraction
│   ├── credentials.py                       # NEW — atomic .env read/write
│   └── mcp_conflict_scan.py                 # NEW — detect conflicting Jira MCPs
├── skills/
│   ├── kanban-jira-agent/                   # NEW — agent-facing skill
│   │   └── SKILL.md
│   └── kanban-jira-setup/                   # NEW — owner-facing skill
│       └── SKILL.md
└── README.md                                # add jira section
````

---

## 11. Migration path

For users currently on `kanban` v0.1.x:

````
> /kanban:initjira              # opts in
[plugin offers to import kanban.json#tasks into Jira]
[user confirms]
[plugin creates Jira issues for each TODO/DOING task, preserving title,
 description, priority, tags-as-labels]
[plugin sets backend.driver = "jira", leaves tasks[] intact for rollback]
````

Rollback: edit `kanban.json` and set `backend.driver = "local"`. The original
`tasks` array is still there. (Jira issues stay in Jira; they are not deleted.)

Reverse migration (jira → local) is **not supported** in v0.2. If you need
to demo offline, scaffold a fresh repo with `/kanban:init`.

---

## 12. Credential storage (internal reference)

> User-facing rule: **never edit this file by hand**. Use `/kanban:initjira`
> or `/kanban:reset-credentials`. This section exists for plugin developers
> and for debugging across machines.

The kanban jira driver stores its credentials alongside notify's, in the
shared workbench config:

````
~/.claude-workbench/.env

# Owned by notify plugin — not touched by kanban
PUSHOVER_TOKEN=...
PUSHOVER_USER=...

# Owned by kanban jira driver — written only by
# /kanban:initjira and /kanban:reset-credentials
JIRA_BASE_URL=https://yourteam.atlassian.net
JIRA_AGENT_EMAIL=agents@yourteam.com
JIRA_API_TOKEN=ATATT3xFfGF0...
````

Write rules:

- Each plugin owns its prefix (`PUSHOVER_*`, `JIRA_*`, etc.).
- A plugin must never modify another plugin's lines.
- Editing must use atomic write (write to `.env.tmp`, fsync, rename) to
  survive partial writes.
- File mode `0600`. Plugin verifies on read; if the mode is broader,
  re-tightens it and warns once per session.

Migration to a new machine: copying this file across machines is supported
but discouraged in favour of running `/kanban:initjira` again — the API
token is per-Atlassian-account anyway, and re-running validates the new
machine's network reach to Jira at the same time.

---

## 13. Composition — how this plays with other plugins

| Pair | Effect | Status after this update |
|---|---|---|
| `kanban × notify` | Card transitions push to Pushover | ready, replaces SSH+tmux poke |
| `kanban × mentor` | mentor Issue → kanban Jira card; Acceptance Criteria → DoD | wire as in existing SPEC |
| `kanban × memory` | `/kanban:next` queries past cards in same project | awaits memory v0.1 |

`kanban × notify` is the critical replacement for the SSH+tmux poke that the
self-hosted route would have provided. When owner approves a card in Jira UI
(or any actor moves a card to REVIEW/DONE), the next session start of the
relevant agent triggers `/kanban:sync` which pulls the new state and the
agent picks up the next card. Real-time feedback to humans goes through
`notify` (Pushover/Telegram) so the owner sees the change immediately on
their phone.

---

## 14. Out of scope for v0.2

- Multi-board support (current repo binds to one board)
- Sprint planning (read-only Sprint info acceptable; no scheduling)
- Webhooks (push from Jira to local). Pull-only is sufficient given the
  trigger model in §6.
- Other drivers (Linear, GitHub Issues). The Driver protocol leaves room.
- Two-way sync between local mode and jira mode within one project.
- `/kanban:reassign-ap-of-task` — owners can edit AP in Jira UI directly;
  not duplicating that path in v0.2 (revisit if user feedback demands).
- **Active enforcement** of the no-other-Jira-MCP rule. v0.2 detects and
  warns; agent-side compliance is via skill instruction. Hard
  PreToolUse-level blocking is deferred (see §16.4).

---

## 15. Test plan

1. Fresh project, `/kanban:init` → `local` mode works as v0.1.x
2. Fresh project, `/kanban:initjira` → end-to-end Jira mode bootstrap
3. Existing v0.1.x project + `/kanban:initjira` → migration imports tasks
4. `/kanban:initjira` interrupted at Step 3 → re-run resumes from Step 2
   without re-prompting credentials
5. `/kanban:reset-credentials` after token rotation → all subsequent
   commands work without restart
6. `/kanban:register-ap` with collision → fuzzy warning fires
7. `kanban-agent.json` with stale AP → plugin refuses, prints command
8. Agent prompt contains card key from different project → no precheck
   (ignored)
9. Agent prompt contains card key with mismatched AP → ⚠ warning injected
10. Workflow has only 3 statuses → partial mode warning + label fallback
11. Anti-self-approve: agent calls transition to DONE on its own card →
    refused server-side (Jira workflow condition), client also refuses
12. Token expired → `/kanban:whoami` reports `✗ invalid`, all other
    commands fail-fast with re-init suggestion
13. `~/.claude-workbench/.env` mode `0644` → plugin re-tightens to `0600`
    and warns once
14. Concurrent `/kanban:initjira` across two terminals on same machine →
    last writer wins atomically; no truncated `.env`
15. With Atlassian Rovo MCP enabled at user scope, `/kanban:initjira`
    detects and warns; user proceeds; agent in this repo correctly
    refuses to use Rovo MCP (skill enforced).
16. Skill `kanban-jira-agent` is auto-discovered when an agent enters a
    repo with `backend.driver=jira` and the AP context block injection
    references the skill's contract.

---

## 16. Open questions for follow-up

These are deferred to v0.2.x or v0.3:

1. **AP fuzzy match metric.** Currently Levenshtein ≤2. `agent-fin` vs
   `agent-fix` triggers the warning (distance 1) which may be noisy.
   Alternative: prefix match ≥8 chars + Levenshtein ≤1. Measure
   false-positive rate after first few weeks of use.
2. **`kanban-agent.json` git policy.** Default is to commit (team sees
   per-repo agent identity). Some teams may want it gitignored if multiple
   humans run different agents in the same repo. Document both patterns;
   default does not change.
3. **`/notify:reset-credentials`.** Not in scope for this update, but the
   pattern from §4.2 should be ported to `notify` plugin so both core
   plugins share the rotation flow. File a follow-up issue.
4. **Hard MCP exclusion via PreToolUse hook.** v0.2 is detect-and-warn
   (§18.2) plus skill-level prohibition. Stronger option: a PreToolUse
   hook that aborts (exit code 2) any tool call whose name matches
   `(?i)atlassian|jira|rovo` when `backend.driver=jira` and the tool isn't
   from the kanban plugin itself. Tracked for v0.3 pending real-world
   feedback on whether soft enforcement is sufficient.
5. **Auto-detect cache TTL.** 30s session-local cache (§5.4). If real-world
   feedback shows owner edits during agent's window are frequent, consider
   shrinking to 10s or invalidating on `UserPromptSubmit`.

---

## 17. Versioning & release

- Plugin version: `0.1.x` → `0.2.0`.
- Marketplace `.claude-plugin/marketplace.json`: bump matching entry per
  repo's pre-commit hook contract.
- Changelog entry: in `CHANGELOG.md`, under `kanban` section, describe the
  driver abstraction, `initjira`, AP, credential commands, and the bundled
  skills as the v0.2.0 feature set.
- Backwards compatibility: existing `kanban.json` files without a `backend`
  block are read as `{ "driver": "local" }` implicitly. No migration of
  existing local-mode users is required.

---

## 18. Skills & MCP servers — what to add, what NOT to add

### 18.1 Why kanban does not require any external Jira MCP

The plugin's jira driver is a complete, opinionated Jira API client. It is
deliberately the **only** sanctioned path for AI agents to touch Jira in a
kanban-jira project. Reasons:

- **Anti-self-approve, AP routing, comment-prefix attribution, audit
  trail** are all enforced inside the plugin. A second Jira-writing path
  (Atlassian Rovo MCP, `mcp-atlassian`, etc.) bypasses these guarantees
  silently.
- **Custom field handling** in Atlassian's official MCP is documented as
  unreliable ("Custom Jira fields may not be recognized or returned
  without explicit setup"). Since AP is a custom field, a parallel MCP
  could overwrite or omit it.
- **Token economy**: a Jira MCP exposes 10–20 low-level tools to the
  agent's context; the plugin's `/kanban:*` surface is ~10 high-level
  commands. Doubling them is wasteful.
- **Auth model mismatch**: this plugin uses a shared agent Atlassian
  account with API token (single credential, simple rotation). Most Jira
  MCPs assume per-user OAuth, which would require each agent machine to
  go through a browser flow.

If a user has Atlassian Rovo MCP enabled at the Claude Code level for
their **personal** workflow (search Confluence, browse own tickets), that
is fine and orthogonal — but **agents working in a kanban-jira project
must not call it**. The agent skill in §18.3 forbids this explicitly.

### 18.2 Detecting and warning about a conflicting MCP

`/kanban:initjira` (final step) and `/kanban:whoami` both check whether
a Jira MCP server is registered for the current Claude Code scope:

````python
def detect_jira_mcp_conflict() -> list[str]:
    # Inspect ~/.claude/settings.json + ./.claude/settings.json + ./.mcp.json
    # Look for servers whose URL or command suggests Jira:
    #   url: contains "atlassian" or "jira"
    #   command/args: contains "mcp-atlassian", "jira-mcp", etc.
    return matching_server_names
````

If matches found:

````
⚠ Detected conflicting Jira MCP server(s): atlassian-rovo

  This plugin enforces AP routing, anti-self-approve, and comment
  attribution. A separate Jira MCP can bypass these silently.

  Recommended: scope the conflicting MCP to user-level (not project-level)
  so agents in this repo do not see it. The skill kanban-jira-agent
  already instructs agents not to call other Jira MCPs, but defense in
  depth is preferred.

  Continue anyway? (y/N)
````

This is a warning, not a block — the user may have a legitimate reason
(e.g. owner uses Rovo MCP for personal Confluence work, agents in this
repo are scoped to project-only). Decision is theirs. Hard enforcement
via PreToolUse hook is tracked in §16.4 for v0.3.

### 18.3 Skills shipped with the plugin

Two skills, both auto-discovered via the `plugins/kanban/skills/`
directory.

#### `kanban-jira-agent` (agent-facing)

Path: `plugins/kanban/skills/kanban-jira-agent/SKILL.md`

YAML frontmatter:

````yaml
---
name: kanban-jira-agent
description: How to use the Jira-backed kanban for AI agents. Triggers when
  the agent is in a project with backend.driver=jira and needs to claim,
  comment on, transition, or hand off a card.
---
````

Body content:

````markdown
# Working with kanban (Jira mode)

You are working in a project where kanban tasks live in Jira. Your AP
(Agent Property) is in `./.claude/kanban-agent.json`. Always operate
through the `/kanban:*` slash commands — never call Jira REST API
directly, never use any other Jira MCP server even if one is available
in your environment.

## Session start
1. `/kanban:sync` — already runs automatically on SessionStart, but
   run it explicitly if you suspect stale state.
2. Read the printed summary. Cards listed are yours.

## Picking work
- `/kanban:next` — auto-claims highest priority TODO and transitions
  to In Progress. Do this before starting work.
- Don't claim a card already DOING by another AP — the precheck hook
  will warn you.

## During work
- Found a blocker that needs human input? Use
  `/kanban:question <KEY> "<question>"`. This auto-transitions to
  Blocked. Do not edit the card any further until you see an answer.
- Your status changes get auto-committed by the kanban-guard hook.
  Don't bypass with `git commit --no-verify`.

## Finishing work
- `/kanban:done` — transitions to In Review with a system comment.
- DO NOT approve your own card. The Jira workflow will refuse the
  transition; the plugin will refuse it earlier. This is intentional.

## Card key auto-detection
If you mention a card key (e.g. AGENT-42) or paste a Jira URL, the
plugin injects context above your prompt automatically. Read it
before acting. Pay especially close attention to ⚠ warnings about AP
mismatch.

## Forbidden
- Direct Jira API calls (curl, fetch, any HTTP client)
- Atlassian Rovo MCP, mcp-atlassian, or any other Jira MCP — your
  plugin is the only sanctioned path
- Editing kanban.json directly
- Approving your own cards (Jira will reject; don't try)
````

#### `kanban-jira-setup` (owner-facing)

Path: `plugins/kanban/skills/kanban-jira-setup/SKILL.md`

YAML frontmatter:

````yaml
---
name: kanban-jira-setup
description: Setup and recovery guidance for the kanban Jira backend.
  Triggers when the user runs /kanban:initjira, /kanban:reset-credentials,
  or describes a Jira mode setup problem.
---
````

Body covers (high-level):

- Walking the user through `/kanban:initjira` step-by-step in plain
  language, especially for non-technical owners.
- Handling Step 3 workflow gaps: how to add the missing canonical statuses
  in Jira project settings, or how to opt into `--partial` mode.
- Handling Step 4 permission gaps: when the shared agent account does not
  have admin rights to create custom fields, instructing how to ask a
  Jira admin to create the AP field once and then re-run init with `[a]
  Use existing field`.
- Migration from local mode: explaining what gets imported, what stays
  behind, and how to roll back.
- Token rotation flow via `/kanban:reset-credentials`.
- Recognizing and resolving a Jira MCP conflict warning (§18.2).

These skills are versioned with the plugin and updated via the existing
`/plugin update kanban@claude-workbench` flow.

### 18.4 Outside the plugin — what user may still want

These are user-level decisions, **not** part of kanban plugin:

| Tool | Use case | Recommendation |
|---|---|---|
| Atlassian Rovo MCP | Owner browses Confluence, searches own tickets | Fine to enable at user scope; do not enable at project scope where agents run |
| Jira mobile app | Owner approves cards from phone | Recommended (this is the primary push channel) |
| Pushover (via `notify` plugin) | Real-time alerts when agent transitions to In Review | Recommended; configured separately via `/notify:setup` |
| `/jira` CLI tool (e.g. jira-pilot) | Owner power-user CLI | Orthogonal to this plugin; harmless |
