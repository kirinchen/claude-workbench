---
description: Switch the current project from local kanban.json to Jira-backed kanban (steps 1–3 of setup).
argument-hint: [--partial]
allowed-tools: Read, Bash(python3:*), Bash(test:*), Bash(ls:*), AskUserQuestion
---

# /kanban:initjira

Arguments: `$ARGUMENTS`

This command switches a project to **Jira mode**. v0.2.0-dev / Phase 2 covers
steps 1–3 (credentials, board, workflow check). Steps 4–5 (Agent Property
custom field, AP registration) land in Phase 3 — until then, the project is
usable for read-only Jira list/get and human-only assignments, but agent-AP
routing is NOT yet active.

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

If credentials already exist (call `python3 jira_setup.py read-credentials` and
check `tokenPresent`), validate them silently:

```bash
echo "$TOKEN_FROM_ENV" | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py \
  validate-credentials --base-url <baseUrl> --email <email>
```

But you don't have access to the stored token from this session — instead,
*delegate the validation to a helper that reads from .env itself*. Use:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py health --kanban-path <kanban.json>
```

If health returns `ok=true`, print "Detected valid Jira credentials from a
previous run. Skipping Step 1." and continue to Step 2.

Otherwise, capture inputs via three separate `AskUserQuestion` calls:

1. **Base URL** — example: `https://yourteam.atlassian.net`. Validate the
   pattern `https?://[^/ ]+` before continuing.
2. **Shared agent account email** — the Atlassian account agents will operate
   under. Pattern: standard email.
3. **API token** — generated at https://id.atlassian.com/manage-profile/security/api-tokens.
   30+ alnum characters. Treat as secret — do not display or echo.

Then validate (token via stdin):

```bash
echo "<TOKEN>" | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py \
  validate-credentials --base-url '<URL>' --email '<EMAIL>'
```

Parse the JSON. On `ok=false`, print the error verbatim (it does NOT contain
the token) and ask the user to re-enter the token. Repeat at most twice. On
final failure, abort.

On `ok=true`, store the credentials:

```bash
echo "<TOKEN>" | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py \
  store-credentials --base-url '<URL>' --email '<EMAIL>'
```

Confirm to user: `✓ authenticated as <displayName>; credentials saved.`

## Step 2/3 — Board URL

Ask for the board URL (e.g. `https://yourteam.atlassian.net/jira/software/projects/AGENT/boards/1`).

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py \
  parse-board-url --url '<URL>'
```

Result is `{"projectKey": "...", "boardId": ...}`. If parse fails, ask once
more, then abort.

Validate that the project + board are reachable with our credentials. The
helper auto-loads token via `read-credentials`, but for explicit re-validation
re-prompt is overkill — instead use a single combined check:

```bash
python3 - <<'PY'
import json, subprocess, sys
from pathlib import Path
CHECKER = "${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py"
BASE = "<URL>"; EMAIL = "<EMAIL>"; PROJECT = "<KEY>"; BOARD = <ID>
# read token from .env via helper
out = subprocess.check_output(["python3", CHECKER, "read-credentials"])
token_present = json.loads(out)["tokenPresent"]
if not token_present: print("missing token"); sys.exit(1)
PY
```

In practice — for Phase 2 ergonomics — call validate-project by re-asking the
user for the token. Acceptable simplification: the user just typed it; the
session can hold it briefly in memory.

```bash
echo "<TOKEN>" | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py \
  validate-project --base-url '<URL>' --email '<EMAIL>' \
  --project '<KEY>' --board <ID>
```

Print `✓ project=<projectName> (<projectKey>); board=<boardName> (<boardType>)`.

## Step 3/3 — Workflow check

Pull the project's statuses and build the canonical → Jira-status map:

```bash
echo "<TOKEN>" | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py \
  build-status-map --base-url '<URL>' --email '<EMAIL>' --project '<KEY>'
```

Result includes `map`, `missing`, `partial`, `labelFallback`.

- If `missing` is empty: print `✓ workflow has all 6 canonical statuses`.
- If non-empty AND `--partial` is NOT set: print the missing list and stop.
  Tell the user to either (a) add the missing statuses in Jira project
  settings and re-run `/kanban:initjira`, or (b) re-run with `--partial` to
  accept label-fallback substitutions for the missing columns.
- If non-empty AND `--partial` IS set: warn loudly, list which columns will
  be substituted via labels (`kanban:blocked`, `kanban:review`,
  `kanban:cancelled`), proceed.

## Step 4 — Persist `backend.jira`

Compose the JSON payload and write it:

```json
{
  "boardUrl": "<URL>",
  "boardId": <ID>,
  "projectKey": "<KEY>",
  "agentAccountId": "<accountId from validate-credentials>",
  "statusMap": { ... from build-status-map },
  "partial": <true|false>,
  "labelFallback": { ... when partial }
}
```

Use Bash to call `write-backend` (single-quote the JSON; do NOT pass via Edit/Write
since `kanban-guard.sh` blocks those):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py \
  write-backend --kanban-path '<KANBAN_PATH>' \
  --jira-config-json '<json>'
```

## Done

Print:

```
✓ /kanban:initjira complete (Phase 2 partial: AP setup pending).

Project:    <projectName> (<projectKey>)
Board:      <boardName> (#<boardId>)
Driver:     jira
Workflow:   full | partial (label fallback: <list>)

Next:
  • /kanban:whoami         — check current state
  • /kanban:reset-credentials — rotate the API token
  • Steps 4–5 (AP custom field + first registration) land in v0.2 Phase 3.
    Until then, agent-AP routing is not active.
```

## Absolute rules

- Never echo the API token back to the user.
- Never pass the token via argv (`--token=…`) — always pipe via stdin.
- Never write `kanban.json` via Edit/Write tools — always go through
  `jira_setup.py write-backend`.
- If any helper call returns `ok=false`, surface its `error` field verbatim
  and stop; do not invent retry logic beyond what is specified above.
- Never proceed past a failed `validate-credentials` even with `--partial`.
