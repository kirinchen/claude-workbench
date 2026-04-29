---
description: Register a new Agent Property (AP) value to the Jira AP custom field.
argument-hint: <ap-name>
allowed-tools: Read, Bash(python3:*), AskUserQuestion
---

# /kanban:register-ap

Arguments: `$ARGUMENTS`

Add a new AP option to `backend.jira.ap.fieldId`. The AP is the single-select
custom-field value that distinguishes which AI agent owns a card. The
operation:

1. Validates the AP name (`^[a-z][a-z0-9-]{2,40}$`).
2. Refuses exact duplicates (case-insensitive). Already-registered names exit ok.
3. Warns on fuzzy collisions (Levenshtein ≤ 2). The user decides whether to
   proceed via `--force`.
4. Adds the option to Jira's custom-field context.
5. Caches the name in `kanban.json#backend.jira.ap.registered`.

## 0. Pre-flight

- Confirm `kanban.json#backend.driver == "jira"` and `backend.jira.ap.fieldId`
  is set. If not, instruct the user to run `/kanban:initjira` first.
- Parse `$ARGUMENTS`: first token is the AP name. If absent, ask once via
  `AskUserQuestion`.

## 1. Try registration

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py \
  register-ap --kanban-path '<kanban.json path>' --name '<ap-name>'
```

Parse the JSON response:

| Response shape | Meaning | Action |
|---|---|---|
| `{ok: true, alreadyRegistered: true, ...}` | already in the registry | print `✓ already registered` and stop |
| `{ok: true, name, registered}` | added | print `✓ registered <name>; current AP roster: <list>` |
| `{ok: false, fuzzyMatch: true, similar: [...]}` | near-duplicate | proceed to step 2 |
| `{ok: false, error: ...}` | hard error | surface the error verbatim and stop |

## 2. Fuzzy-collision confirmation

If step 1 returned `fuzzyMatch`, list the similar names and their Levenshtein
distance, then ask once via `AskUserQuestion`:

> The following existing APs are similar to `<name>`:
>   • <existing> (distance N)
> Continue with registration? (y/N)

On `y`:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py \
  register-ap --kanban-path '<kanban.json path>' --name '<ap-name>' --force
```

On `n` or any other answer: stop. Do not retry.

## Absolute rules

- Never bypass the fuzzy-collision warning silently — the user must choose `--force`.
- Never edit `kanban.json` directly via Edit/Write — always go through the helper.
- Never invent an AP name — it must come from the user.
