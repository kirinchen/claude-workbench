---
description: Rotate Jira API credentials for the current machine.
allowed-tools: Bash(python3:*), AskUserQuestion
---

# /kanban:reset-credentials

Re-prompt and overwrite the Jira credentials in `~/.claude-workbench/.env`.
Use when the API token has been rotated, expired, or exposed.

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
