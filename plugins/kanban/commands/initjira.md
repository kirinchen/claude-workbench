---
description: Switch the current project from local kanban.json to Jira-backed kanban.
allowed-tools: Read, Bash(python3:*), Bash(test:*), Bash(ls:*), Write, AskUserQuestion
---

# /kanban:initjira

Arguments: `$ARGUMENTS`

This command switches a project to **Jira mode** end-to-end: credentials,
board, workflow check, Agent Property (AP) custom field, and the first AP
registration. After it completes, `/kanban:doing`, `/kanban:done`, and
`/kanban:block` operate against Jira with anti-self-approve enforcement.

The helper `${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py` does the network +
file work; this command orchestrates the prompts and surfaces results.

**Token handling rule**: when calling helper subcommands that need the token,
ALWAYS pipe the token via stdin (`echo "$TOKEN" | python3 .../jira_setup.py …`)
— never pass it in `--token=` argv. Never echo the token back to the user.

## 0. Pre-flight

1. Confirm `kanban.json` exists at the project root (`$CLAUDE_PROJECT_DIR` or
   `git rev-parse --show-toplevel`). If missing, stop and tell the user to run
   `/kanban:init` first.
2. Read `kanban.json#backend.driver`. If already `"jira"`, ask whether to
   re-run init (overwriting the backend block) or abort.
3. Parse `--partial` flag from `$ARGUMENTS`. Default off.

## Step 1/3 — Credentials

Check if credentials already exist:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py read-credentials
```

If `tokenPresent: true`, run `/kanban:whoami` to confirm they
authenticate; if it succeeds, print "Detected valid Jira credentials
from a previous run. Skipping Step 1." and continue to Step 2.

Otherwise, capture **base URL + email** via two `AskUserQuestion` calls:

1. **Base URL** — example: `https://yourteam.atlassian.net`. Validate the
   pattern `https?://[^/ ]+` before continuing.
2. **Shared agent account email** — the Atlassian account agents will operate
   under. Pattern: standard email.

Do **NOT** ask for the API token here. The token is captured in the
next sub-step by the user themselves, in their own terminal.

### Token capture (USER-DRIVEN — do NOT run via Bash tool)

> ⚠ **The token must NOT enter Claude Code's conversation log.** Claude
> Code's Bash tool prints every command it runs to the conversation
> transcript, so any `echo "<token>" | ...` you might construct leaks
> the token. Use `--prompt-token` (added in kanban@0.3.18) and have the
> user run it themselves.

Print this block to the user verbatim, then **stop and wait**:

```
─────────────────────────────────────────────────────────────────
For security, paste your Jira API token in YOUR OWN terminal, not
through this chat. Open a terminal on this machine and run:

  python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py \
    store-credentials --base-url "<URL>" --email "<EMAIL>" \
    --prompt-token

You'll see:
  Jira API token:
Paste the token (generated at
https://id.atlassian.com/manage-profile/security/api-tokens) at the
prompt and press Enter (it won't echo). On success: {"ok": true}

Then come back here and tell me "done" so I can verify.
─────────────────────────────────────────────────────────────────
```

**Substitute** `<URL>` and `<EMAIL>` with the values captured above
before printing — those aren't secret. Do NOT substitute or invent
any token-related field.

After the user reports "done", verify with `read-credentials` (look for
`tokenPresent: true`) and then run `/kanban:whoami` to confirm the
token actually authenticates against Jira. If `whoami` reports
`UNAUTHENTICATED`, tell the user "the token didn't authenticate — try
again, or check the URL / email" and loop back to the prompt block.
On success, confirm: `✓ authenticated as <displayName>; credentials saved.`

## Step 2/3 — Board URL

Ask for the board URL (e.g. `https://yourteam.atlassian.net/jira/software/projects/AGENT/boards/1`).

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py \
  parse-board-url --url '<URL>'
```

Result is `{"projectKey": "...", "boardId": ...}`. If parse fails, ask once
more, then abort.

Validate that the project + board are reachable with our credentials.
The token is already in `~/.claude-workbench/.env` from step 1; use
`--from-env` so the helper reads it directly — **never** echo the token
to a Bash command (Claude Code prints every Bash command to the
conversation log, which would leak the token; #42).

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py \
  validate-project --base-url '<URL>' --email '<EMAIL>' \
  --project '<KEY>' --board <ID> --from-env
```

Print `✓ project=<projectName> (<projectKey>); board=<boardName> (<boardType>)`.

> **Tip — already configured the same board in another repo or machine?**
> Skip this entire flow: run `/kanban:showjira-code` in the source repo,
> copy the printed JSON, then run `/kanban:import-jira-code` in this repo
> and paste it. Jumps straight from credentials to step 5 (assign AP).

## Step 3/5 — Compound transitions (canonical → Jira)

This is the heart of Jira mode. For each canonical column
(`TODO / DOING / BLOCKED / REVIEW / DONE / CANCELLED`) you must define a
**compound transition spec**: which Jira status to move to, plus optional
labels to add/remove and an optional pinned assignee. Multiple canonicals
can share the same Jira status — the reader disambiguates by labels.

### 3a. Auto-suggest from the project's workflow

```bash
echo "<TOKEN>" | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py \
  build-status-map --base-url '<URL>' --email '<EMAIL>' --project '<KEY>'
```

Returns:

```json
{
  "found": [{"name":"進行中","category":"indeterminate"}, ...],
  "suggestions": {
     "DOING": {"status":"進行中", "confidence":0.95, "reason":"statusCategory=indeterminate"},
     "DONE":  {"status":"完成",   "confidence":0.95, "reason":"statusCategory=done"}
  },
  "unmapped": ["TODO","BLOCKED","REVIEW","CANCELLED"],
  "ambiguous": ["TODO"]
}
```

Print this to the user as a starting point. Format:

```
Found Jira statuses:
  • Selected for Development  (category: new)
  • Backlog                   (category: new)
  • 進行中                     (category: indeterminate)
  • 完成                       (category: done)

Auto-suggested mapping (confidence in parens):
  DOING → 進行中    (0.95, statusCategory=indeterminate)
  DONE  → 完成      (0.95, statusCategory=done)

Unmapped: TODO, BLOCKED, REVIEW, CANCELLED
Ambiguous: TODO (multiple "new"-category statuses — pick one explicitly)
```

### 3b. Capture the user's compound mapping

Show the user a **DSL prompt** they can paste into. This is more
expressive than a flat status map — it supports `+ Label[ name]` and
`+ Assignee to me|<displayName>`.

> Please define each canonical column. The auto-suggestions above are a
> starting point, but you almost certainly need to override at least the
> unmapped ones. Format (one line per canonical):
>
>     CANONICAL > <Jira status> [+ Label [name]] [+ Assignee to me|<name>]
>
> Examples:
>
>     TODO > Selected for Development
>     DOING > In Progress
>     BLOCKED > In Progress + Label                       # adds kanban:blocked
>     REVIEW > In Progress + label + Assignee to me       # adds kanban:review + assigns to current user
>     DONE > Done
>     CANCELLED > DONE + label                            # same Jira status as canonical DONE, plus kanban:cancelled
>
> - `Label` / `label` (no name) defaults to `kanban:<canonical-lower>`.
> - `Label some-name` lets you choose the label text.
> - `Assignee to me` resolves to your current Jira accountId; `Assignee to <name>` queries `/user/search`.
> - An UPPERCASE word on the right (e.g. `DONE`) refers to another canonical's resolved Jira status — useful when several canonicals share a status.
> - Lines starting with `#` are comments.

Use `AskUserQuestion` to capture the multi-line DSL block.

### 3c. Parse the DSL

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py parse-transitions-dsl \
  --dsl-text '<USER_DSL_BLOCK>' \
  --current-user-account-id '<accountId from Step 1>'
```

Returns `{"ok": true, "transitions": {...}}` or `{"ok": false, "error": "..."}`.

If parsing fails, surface the error verbatim and re-prompt for the DSL
block once. After two failures, abort.

### 3d. Persist `backend.jira` (transitions + metadata)

Compose the full backend.jira JSON and write it via `write-backend`:

```json
{
  "boardUrl": "<URL from Step 2>",
  "boardId": <ID>,
  "projectKey": "<KEY>",
  "agentAccountId": "<accountId from Step 1's validate-credentials>",
  "transitions": { ... from 3c ... }
}
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py write-backend \
  --kanban-path '<kanban.json path>' \
  --jira-config-json '<full json above>'
```

`write-backend` writes atomically and drops any legacy `statusMap` /
`labelFallback` / `partial` keys (from v0.2.x users re-running init).

> Optional sanity check before writing: call `set-transitions` instead with
> `--available-statuses '<json array of names from `found`>'`. It validates
> that each `status` in the transitions exists in the project's workflow
> and returns errors without writing — useful when the user's DSL might
> have typos. `set-transitions` only writes the `transitions` field; use it
> for incremental edits after init, not for first-time setup.

## Step 4/5 — Agent Property (AP) custom field

Decide whether to use an existing custom field or create a new one. Ask the
user via `AskUserQuestion`:

> The AP field is what distinguishes which AI agent owns a card.
>   [a] Use an existing custom field   (browse candidates)
>   [b] Create a new field "Claude Agent" (recommended; requires Jira admin)
> Choice:

### Option [a] — use existing field

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py find-ap-field
```

Returns `{candidates: [{id, name}, ...]}`. If the list is empty, tell the
user "no fields look like an AP candidate — switch to [b] or have a Jira
admin create one and rerun". Otherwise, print the candidates and ask the
user to pick one by `id`.

Persist the choice:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py set-ap-field \
  --kanban-path '<kanban.json path>' \
  --field-id '<customfield_X>' --field-name '<name>'
```

### Option [b] — create new field

Pass the project key so the helper can attach the new field to project
screens automatically (closes #6 — without this, the field exists but no
issue can carry its value):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py create-ap-field \
  --name 'Claude Agent' --project '<KEY>'
```

The response now includes a `screens` summary:

```json
{
  "ok": true, "fieldId": "customfield_10042", "fieldName": "Claude Agent",
  "screens": {
    "attempted": [{"id": 1, "name": "Default Screen"},
                  {"id": 42, "name": "DMI: Kanban Default Issue Screen"}],
    "attached":  [{"id": 1, "name": "Default Screen"},
                  {"id": 42, "name": "DMI: Kanban Default Issue Screen"}],
    "denied": [], "errors": []
  }
}
```

If `screens.denied` is non-empty, the field exists but Jira refused to
attach it to one or more screens (admin permission needed). Surface the
list verbatim and suggest:

> ⚠ AP field created, but couldn't attach it to: `<screen names>`.
> Ask a Jira admin to add `<fieldName>` to those screens, or run
> `/kanban:fix-ap-screen` after they grant you permission. **Until at
> least one screen carries the field, `/kanban:doing` will return no
> work even if cards exist.**

On `ok=true`, persist the new field:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py set-ap-field \
  --kanban-path '<kanban.json path>' \
  --field-id '<returned fieldId>' --field-name 'Claude Agent'
```

Then verify the association is healthy before moving on:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py verify-ap-field-screens \
  --kanban-path '<kanban.json path>'
```

If `missing` is non-empty, print the same warning as above and continue —
don't abort init, but make sure the user knows the next step is to run
`/kanban:fix-ap-screen` (or have an admin do it).

On `403` from `create-ap-field` itself (the create step, not screen
association), surface the helper's error verbatim and tell the user to
either ask their Jira admin to create a single-select custom field once,
then re-run `/kanban:initjira` and choose `[a]`. Stop — do NOT silently
fall back to `[a]`; the choice is the user's.

## Step 5/5 — First AP registration

Ask for the AP name for *this* repo (regex `^[a-z][a-z0-9-]{2,40}$`).
Examples: `agent-fin-exchange`, `agent-quant-bot`. The user can register
more APs later via `/kanban:register-ap` and switch the active one via
`/kanban:assign-ap`.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py register-ap \
  --kanban-path '<kanban.json path>' --name '<ap-name>'
```

If `{ok: false, fuzzyMatch: true, similar: [...]}`, this is the first AP
and the registry should be empty — surface the response anyway and ask the
user to confirm proceeding with `--force`. (Realistically this only fires
on idempotent re-run of init.)

After successful registration, set this repo's AP:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py assign-ap \
  --kanban-path '<kanban.json path>' --name '<ap-name>'
```

## Step 6/6 — Migration of existing local tasks (optional)

Before printing the Done block, check whether `kanban.json#tasks` has any
entries from a prior local-mode life. If `len(tasks) > 0`, ask:

> Found N existing local tasks. Import them as Jira issues? (y/N)
>   • Imported tasks get the `migrated-from-local` label.
>   • DONE / CANCELLED tasks are skipped by default (use --include-done to override).
>   • The original `tasks[]` stays in kanban.json for rollback.

On `y`:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py import-tasks \
  --kanban-path '<kanban.json path>'
```

Surface the response: `imported`, `skipped`, mapping path. If any task
errored individually (`skippedDetail[i].reason` starts with `error:`),
print those lines so the user can investigate.

On `n` or absent: skip silently. The user can run `import-tasks` later via
the helper if they change their mind.

## Final check — Jira MCP conflict scan

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py mcp-conflict-scan \
  --kanban-path '<kanban.json path>'
```

If `conflicts` is non-empty, print a warning per SPEC §18.2:

```
⚠ Detected conflicting Jira MCP server(s):
  • <server> (in <source>) — matched on <matchedOn>

This plugin enforces AP routing, anti-self-approve, and comment attribution.
A separate Jira MCP can bypass these silently. Recommended:
  - scope the conflicting MCP to user-level only (not project-level), OR
  - disable it for repos that use kanban Jira mode.

The kanban-jira-agent skill instructs agents not to call other Jira MCPs,
but defense in depth is preferred.
```

This is informational. Do not block the init flow.

## Done

Print:

```
✓ /kanban:initjira complete.

Project:    <projectName> (<projectKey>)
Board:      <boardName> (#<boardId>)
Driver:     jira
Workflow:   full | partial (label fallback: <list>)
AP field:   <fieldName> (<fieldId>)
This repo:  <ap-name>
Roster:     <comma-list of registered APs>
Migration:  N imported, M skipped     (omit if not run)
MCP scan:   ✓ no conflicts | ⚠ <count> conflict(s)

Try:
  • /kanban:whoami       — confirm current state
  • /kanban:status       — read live Jira state for this AP
  • /kanban:doing         — claim the next TODO for this AP
```

## Absolute rules

- **NEVER** call the Bash tool with a command that contains the token
  literal (e.g. `echo "<actual token>" | ...`). Claude Code prints every
  Bash command to the conversation transcript, so any such command leaks
  the token. Token capture is user-driven via `--prompt-token` (the user
  runs the helper in their own terminal); subsequent steps use
  `--from-env` so the helper reads the token directly from
  `~/.claude-workbench/.env`. See #42 for the original "your plugin
  taught me to leak my own token" report.
- **NEVER** ask for the token via `AskUserQuestion` either — the user's
  response is part of the conversation log.
- Never echo the API token back to the user.
- Never write `kanban.json` via Edit/Write tools — always go through
  `jira_setup.py write-backend`.
- If any helper call returns `ok=false`, surface its `error` field verbatim
  and stop; do not invent retry logic beyond what is specified above.
- Never proceed past a failed token verification (`whoami` returning
  UNAUTHENTICATED) even with `--partial`.
