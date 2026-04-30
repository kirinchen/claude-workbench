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

If `~/.claude-workbench/.env` already has valid Jira credentials (run
`/kanban:whoami` or the `health` helper to check), skip. Otherwise run
the same Step 1 flow as `/kanban:initjira` (capture base URL, agent
email, API token; validate via `validate-credentials`; persist via
`store-credentials`).

## Step 2/3 — Paste and import the code

Ask the user via `AskUserQuestion` to paste the JSON code emitted by
`/kanban:showjira-code` on the source machine. Strip leading/trailing
whitespace and any surrounding code-fence backticks (the user is likely
copy-pasting from a chat).

Validate the structure: must be a JSON object with
`schema == "kanban-jira-code/1"`. Surface any parse error verbatim.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py import-jira-code \
  --kanban-path '<kanban.json path>' \
  --code-json '<the pasted JSON>'
```

| Response | Action |
|---|---|
| `{ok: true, imported: {...}}` | print one-line summary: imported `<projectKey>/<boardId>`, `<N>` transitions, AP field `<fieldName>` |
| `{ok: false, error: ..., errors?: [...]}` | surface the error(s); ask the user to re-paste |

After two validation failures, abort.

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
