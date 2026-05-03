---
description: Bootstrap or re-sync Jira mode in this repo from a code emitted elsewhere — skips DSL setup. Replaces /kanban:initjira-by-code (#34).
allowed-tools: Read, Bash(python3:*), Bash(test:*), Bash(ls:*), Bash(git:*), AskUserQuestion
---

# /kanban:import-jira-code

Import a `kanban-jira-code/2` JSON payload (emitted by
`/kanban:showjira-code` on a sibling repo / machine) into the current
repo. Two use cases, same command:

- **First-run bootstrap** — fresh repo, no `backend.jira` yet. Equivalent
  to running `/kanban:initjira` but skipping the parts the code already
  carries (board URL, transitions DSL, AP field discovery).
- **Re-sync** — repo is already on Jira mode but the team's
  configuration drifted (e.g. `/kanban:edit-conventions` added a rule on
  machine A; machine B re-imports to pick it up). The conventions ack
  hash forces re-acknowledgment when notes change; the AP step is
  idempotent (skipped when the local AP is still on the board).

Skips compared to `/kanban:initjira`:

- Step 2: board URL parse (the code carries `projectKey` / `boardId`)
- Step 3: compound transition DSL (the code carries `transitions`)
- Step 4: AP custom-field discovery (the code carries `ap.fieldId`)

You still need:

- Step 1: Jira credentials on this machine (the code does NOT contain a
  token — it is per-machine).
- Step 3: this repo's AP assignment (idempotent — see below).

## 0. Pre-flight

- Confirm `kanban.json` exists at the project root. If missing, run
  `/kanban:init` first.
- `$CLAUDE_PROJECT_DIR` (or `git rev-parse --show-toplevel`) → kanban path.
- If `kanban.json#backend.driver` is already `"jira"`, ask the user
  whether to overwrite the current mapping (the import will replace
  `backend.jira` wholesale). For routine re-sync this is the expected
  flow — say yes; for a fresh code from an unfamiliar source, double-check
  it's the right team's payload first.

## Step 1/3 — Credentials

If `~/.claude-workbench/.env` already has valid Jira credentials, skip.
To check, call `read-credentials` and verify `tokenPresent` is true:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py read-credentials
# expect: {"baseUrl": "...", "email": "...", "tokenPresent": true}
```

Do **not** use the `health` helper as the oracle here — at this point
`kanban.json#backend.driver` is still `"local"` (or being switched), so
`health` may run against the local driver and return `ok=true` regardless
of whether Jira credentials exist. See #31.

If credentials are missing, run the same Step 1 flow as `/kanban:initjira`
(capture base URL, agent email, API token; validate via
`validate-credentials`; persist via `store-credentials`).

## Step 2/3 — Paste and import the code

Ask the user via `AskUserQuestion` to paste the JSON code emitted by
`/kanban:showjira-code` on the source machine. Strip leading/trailing
whitespace and any surrounding code-fence backticks (the user is likely
copy-pasting from a chat).

Validate the structure: must be a JSON object with `schema` equal to
`kanban-jira-code/1` or `kanban-jira-code/2`. Surface any parse error
verbatim.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py import-jira-code \
  --kanban-path '<kanban.json path>' \
  --code-json '<the pasted JSON>'
```

| Response | Action |
|---|---|
| `{ok: true, imported: {...}, schema, conventions, ackRequired}` | print one-line summary: imported `<projectKey>/<boardId>`, `<N>` transitions, AP field `<fieldName>`. If `ackRequired` is true, proceed to step 2.5. |
| `{ok: false, error: ..., errors?: [...]}` | surface the error(s); ask the user to re-paste |

After two validation failures, abort.

## Step 2.5/3 — Acknowledge team conventions (only if `ackRequired`)

When the imported code carries a non-empty `conventions` block (notes
the team agreed to share), the user must read them before import can
complete. The friction is intentional — pasting code is not the same as
having read it. The conventions hash is checked against the prior ack
in `.claude/kanban-agent.json`, so re-sync where conventions didn't
change auto-skips this step.

Render the notes as a numbered list, then ask via `AskUserQuestion`:

```
⚠ Team conventions you should know before starting work:

  1. <note 1>
  2. <note 2>
  3. <note 3>

If `blockedRequiresLink` is true:
  ⚙ This team requires `--blocked-by KEY` on every /kanban:block call.

Type the literal phrase 'I have read these' to acknowledge and continue:
```

The ack must be the **exact** string `I have read these` (case-sensitive,
trim leading/trailing whitespace). Other answers (`yes`, `Y`, `ok`,
`sure`, `已讀`, etc.) are **not** accepted — re-prompt once. After two
mismatches, abort import with:

> Import aborted — conventions not acknowledged. Re-run when ready, or run
> `/kanban:show-conventions` to read them outside the import flow.

Once the literal phrase is entered, persist the ack:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py record-conventions-ack \
  --kanban-path '<kanban.json path>'
```

This writes a hash + timestamp to `.claude/kanban-agent.json` so future
re-runs of `/kanban:import-jira-code` (with the same conventions) skip
this step.

## Step 3/3 — Assign this repo's AP (idempotent)

For re-sync this is usually a no-op: the repo already has its AP set in
`.claude/kanban-agent.json#ap`, and that name still exists on the board.
First check whether the existing assignment is still valid:

```bash
# 1. Read the repo's existing AP (None on first-run)
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py read-agent-ap \
  --kanban-path '<kanban.json path>'

# 2. Read the board's currently-registered AP roster
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py live-list-aps \
  --kanban-path '<kanban.json path>'
```

Decision matrix:

| Local `ap` | In `live-list-aps#registered`? | Action |
|---|---|---|
| set (e.g. `narrative-fin-agent`) | yes | print `AP: <name> (kept from existing config)` and skip the prompt |
| set | no — name was de-registered upstream | warn `AP <name> is no longer on the board roster — please re-pick` and re-prompt as for first-run |
| not set | n/a | first-run flow: list options + prompt |

For first-run / re-prompt flow, show the live AP roster and let the user
pick:

```
| Response | Action |
|---|---|
| `{ok: true, registered: [...]}` | list options; ask the user to pick or `/kanban:register-ap <new>` first |
```

If the user picks an existing AP:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py assign-ap \
  --kanban-path '<kanban.json path>' --name '<picked-ap>'
```

If the user wants a new AP, instruct them to run
`/kanban:register-ap <name>` then `/kanban:assign-ap <name>`.

## Done

```
✓ /kanban:import-jira-code complete.

Project:    <projectKey>
Board:      #<boardId>
Driver:     jira (imported from code)
Transitions: <count>  (e.g. TODO→Selected for Development, DOING→In Progress, ...)
AP field:   <fieldName> (<fieldId>)
This repo:  <ap-name>  (kept | newly assigned)

Try: /kanban:status
```

## Absolute rules

- Never accept a code with `schema != "kanban-jira-code/1"` and
  `schema != "kanban-jira-code/2"`.
- Never invent fields the code is missing (e.g. don't synthesise an AP
  field from any local hint — the code is authoritative).
- Never surface the API token in any output.
- Never write to `kanban.json` via Edit/Write — go through the helper.
- The conventions ack hash mechanism is the team-drift safety net —
  preserve it. Re-importing after a conventions change *must* force
  a fresh ack; do not bypass step 2.5 for "convenience".
