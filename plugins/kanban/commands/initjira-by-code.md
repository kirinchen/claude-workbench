---
description: Bootstrap Jira mode in this repo from a code emitted elsewhere — skips DSL setup.
allowed-tools: Read, Bash(python3:*), Bash(test:*), Bash(ls:*), Bash(git:*), AskUserQuestion
---

# /kanban:initjira-by-code

Short version of `/kanban:initjira` for repos / machines that already have
a sibling repo configured for the same Jira board. Skips:

- Step 2: board URL parse (the code carries `projectKey` / `boardId`)
- Step 3: compound transition DSL (the code carries `transitions`)
- Step 4: AP custom-field discovery (the code carries `ap.fieldId`)

You still need:

- Step 1: Jira credentials on this machine (the code does NOT contain a
  token — it is per-machine).
- Step 5: this repo's AP assignment.

## 0. Pre-flight

- Confirm `kanban.json` exists at the project root. If missing, run
  `/kanban:init` first.
- `$CLAUDE_PROJECT_DIR` (or `git rev-parse --show-toplevel`) → kanban path.
- If `kanban.json#backend.driver` is already `"jira"`, ask the user
  whether to overwrite the current mapping (the import will replace
  `backend.jira` wholesale).

## Step 1/3 — Credentials

If `~/.claude-workbench/.env` already has valid Jira credentials, skip.
To check, call `read-credentials` and verify `tokenPresent` is true:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py read-credentials
# expect: {"baseUrl": "...", "email": "...", "tokenPresent": true}
```

Do **not** use the `health` helper as the oracle here — at this point
`kanban.json#backend.driver` is still `"local"` (nothing has switched it
to `"jira"` yet), so `health` runs against the local driver and returns
`ok=true` regardless of whether Jira credentials exist. See #31.

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
the team agreed to share), the user must read them before init can
complete. The friction is intentional — pasting code is not the same as
having read it.

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
mismatches, abort init with:

> Init aborted — conventions not acknowledged. Re-run when ready, or run
> `/kanban:show-conventions` to read them outside the init flow.

Once the literal phrase is entered, persist the ack:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py record-conventions-ack \
  --kanban-path '<kanban.json path>'
```

This writes a hash + timestamp to `.claude/kanban-agent.json` so future
re-runs of `/kanban:initjira-by-code` (with the same conventions) skip
this step.

## Step 3/3 — Assign this repo's AP

Same as `/kanban:initjira` step 5. Show the live AP roster from Jira:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py live-list-aps \
  --kanban-path '<kanban.json path>'
```

| Response | Action |
|---|---|
| `{ok: true, registered: [...]}` | list options; ask the user to pick or `/kanban:register-ap <new>` first |

If the user picks an existing AP:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py assign-ap \
  --kanban-path '<kanban.json path>' --name '<picked-ap>'
```

If the user wants a new AP, instruct them to run
`/kanban:register-ap <name>` then `/kanban:assign-ap <name>`.

## Done

```
✓ /kanban:initjira-by-code complete.

Project:    <projectKey>
Board:      #<boardId>
Driver:     jira (imported from code)
Transitions: <count>  (e.g. TODO→Selected for Development, DOING→In Progress, ...)
AP field:   <fieldName> (<fieldId>)
This repo:  <ap-name>

Try: /kanban:status
```

## Absolute rules

- Never accept a code with `schema != "kanban-jira-code/1"`.
- Never invent fields the code is missing (e.g. don't synthesise an AP
  field from any local hint — the code is authoritative).
- Never surface the API token in any output.
- Never write to `kanban.json` via Edit/Write — go through the helper.
