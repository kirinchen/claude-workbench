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
  capture it, no need to re-paste the code via `/kanban:import-jira-code`.
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

## 1. Capture new values

Three `AskUserQuestion` calls. For Base URL / Email, default to current value
on empty input — tell the user "press Enter to keep current".

1. **Base URL** — same validation as `/kanban:initjira`.
2. **Email** — Atlassian account email.
3. **API token** — secret. Do not echo.

## 2. Validate

```bash
echo "<TOKEN>" | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py \
  validate-credentials --base-url '<URL>' --email '<EMAIL>'
```

If `ok=false`, surface the error and ask once more for the token. On second
failure, abort without writing.

## 3. Store

```bash
echo "<TOKEN>" | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py \
  store-credentials --base-url '<URL>' --email '<EMAIL>'
```

This atomically rewrites only the `JIRA_*` lines, leaving any `PUSHOVER_*`
or other plugin lines untouched.

## 4. Confirm

```
✓ credentials updated; authenticated as <displayName>.
```

Do NOT print the token, the email/URL is fine.

## Absolute rules

- Never echo the API token.
- Never pass the token via argv — always stdin pipe.
- Never modify `kanban.json` here — that is the job of `/kanban:initjira`.
- If validation fails twice, abort. Do not store an unvalidated token.
