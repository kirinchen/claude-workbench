---
description: Show or edit the notify plugin config.
argument-hint: [show|edit]
allowed-tools: Read, Bash(cat:*), Bash(ls:*), Bash(test:*), Bash(export:*), Bash(workbench-notify:*)
---

# /notify:config

Arguments: `$ARGUMENTS`  (`show` = default, `edit` = open in `$EDITOR`)

## 1. Locate

- Config: `~/.claude-workbench/notify-config.json`
- Tokens: `~/.claude-workbench/.env` (auto-loaded by the dispatcher at runtime)

If the config doesn't exist, tell the user to run `/notify:setup` and stop.

## 2. Show mode (default)

Read and display `notify-config.json`. Redact obvious secret values in the display:

- Any field ending in `_key`, `_token`, `_secret`, `password` → print as `"<redacted>"` regardless of content.
- `${ENV_VAR}` references — leave as-is (they're already indirection).

Also print (all optional — only show if relevant):
- Path of config file.
- Whether `~/.claude-workbench/.env` exists (but **do NOT print its contents**).
- Path of the failure log (`~/.claude-workbench/logs/notify-failures.log`) and whether it's non-empty.
- Result of `workbench-notify --health` (prefixed with a PATH prepend):

```bash
export PATH="$HOME/.claude-workbench/bin:$PATH"
workbench-notify --health
```
Report just pass/fail, not the command output.

## 3. Edit mode

Do NOT launch an editor yourself. Instead, print:

```
Config:  $EDITOR ~/.claude-workbench/notify-config.json
Tokens:  $EDITOR ~/.claude-workbench/.env        # chmod 600 after saving

After editing, validate with:
  /notify:test
```

Reason: the Claude Code harness can't cleanly hand the user's TTY over to an interactive editor; pretending otherwise leads to split-brain state.

## Absolute rules

- Never write to the config file or `.env` from this command.
- Never dump unredacted secrets to stdout.
- Never cat `~/.claude-workbench/.env` — merely state whether it exists.
- Never fetch tokens from env and print them.
