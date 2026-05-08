---
description: Set or rotate Jira credentials on this machine — entry point for both first-time-on-this-machine setup and token rotation.
allowed-tools: Bash(python3:*), AskUserQuestion
---

# /kanban:reset-credentials

Capture (or re-capture) the Jira credentials in `~/.claude-workbench/.env`.
Two main use cases:

- **First-time setup on a new machine for an existing repo.** When you
  `git clone` (or `git pull`) a repo that already has Jira mode
  configured, `kanban.json` carries the full `backend.jira` block
  (transitions, projectKey, ap.fieldId, conventions) already — config
  travels via git. The only thing this machine is missing is your
  Jira API token, which is per-machine by design. Run this command to
  capture it, no need to re-pull the board config — that lands
  automatically on next `/kanban:sync` (or run `/kanban:pull-board-config`
  to force it now).
- **Token rotation.** Existing token expired, was rotated by an admin,
  or was exposed; replace it.

This command does NOT touch `kanban.json`, AP registry, or any other
plugin's configuration. Only the `JIRA_*` lines in `.env` are replaced.

## 0. Show current state

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py read-credentials
```

Print:
```
Current Base URL: <baseUrl> (or "(not set)")
Current Email:    <email>   (or "(not set)")
Current Token:    <"present" if tokenPresent else "missing">
```

## 1. Capture base URL + email

Two `AskUserQuestion` calls. Defaults to current value on empty input —
tell the user "press Enter to keep current".

1. **Base URL** — same validation as `/kanban:initjira`.
2. **Email** — Atlassian account email.

Do **NOT** ask for the API token here. The token is captured in step 2
by the user themselves, in their own terminal, NOT through this chat.

## 2. Token capture (USER-DRIVEN — do not run via Bash tool)

> ⚠ **The token must NOT enter Claude Code's conversation log.** Claude
> Code's Bash tool prints every command it runs (including any
> `echo "<token>" | ...` you might be tempted to construct) so the
> agent must NEVER call Bash with a command that contains the token
> literal. Doing so leaks the token to the conversation transcript and
> the user has to rotate. The fix shipped in kanban@0.3.18 (#42-ish)
> is `--prompt-token`, which captures the token interactively via
> `getpass` — no argv, no stdin pipe, no echo.

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
Paste the token at the prompt and press Enter (it won't echo).
On success: {"ok": true}

Then come back here and tell me "done" so I can verify.
─────────────────────────────────────────────────────────────────
```

**Substitute** `<URL>` and `<EMAIL>` with the values captured in step 1
before printing — those aren't secret. Do NOT substitute or invent any
token-related field.

After the user reports "done", proceed to step 3 to verify.

## 3. Verify

The store command itself doesn't validate — it just writes. After the
user says they ran it, run a separate, no-secret-needed read:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py read-credentials
```

If `tokenPresent: true`, run `/kanban:whoami` to confirm the token
actually authenticates against Jira. If `whoami` reports
`UNAUTHENTICATED`, tell the user "the token didn't authenticate — try
again, or check the URL / email" and loop back to step 2.

## 4. Confirm

```
✓ credentials updated; authenticated as <displayName>.
```

Do NOT print the token. The email/URL is fine.

## Absolute rules

- **NEVER** call the Bash tool with a command that contains the token
  as a literal (e.g. `echo "<actual token>" | ...`). Claude Code prints
  every Bash command to the conversation transcript; doing so leaks the
  token immediately. Use `--prompt-token` and tell the user to run it
  themselves. See #42 (the original "I followed your instructions and
  the plugin then warned me my token was leaked" report).
- **NEVER** ask for the token via `AskUserQuestion` either — the
  user's response is part of the conversation log.
- Never echo the API token in any output.
- Never modify `kanban.json` here — that is the job of `/kanban:initjira`.
- If verification fails twice, abort. Do not silently leave a bad token
  in `.env`.
