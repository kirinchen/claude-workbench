---
description: Show or edit the notify plugin config.
argument-hint: [show|edit]
allowed-tools: Read, Bash(cat:*), Bash(ls:*), Bash(test:*)
---

# /notify:config

Arguments: `$ARGUMENTS`  (`show` = default, `edit` = open in `$EDITOR`)

## 1. Locate

Config path: `~/.claude-workbench/notify-config.json`.

If it doesn't exist, tell the user to run `/notify:setup` and stop.

## 2. Show mode (default)

Read and display the file. Redact obvious secret values in the display:

- Any field ending in `_key`, `_token`, `_secret`, `password` → print as `"<redacted>"` regardless of content.
- `${ENV_VAR}` references — leave as-is (they're already indirection).

Also print:
- Path of config file.
- Path of the failure log (`~/.claude-workbench/logs/notify-failures.log`) and whether it's non-empty.
- Result of `workbench-notify --health` (just pass/fail, not the command output).

## 3. Edit mode

Do NOT launch an editor yourself. Instead, print:

```
To edit the config, open it in your editor:

  $EDITOR ~/.claude-workbench/notify-config.json

After saving, validate with:
  /notify:test
```

Reason: the Claude Code harness has no good way to interactively edit a file in the user's real terminal; pretending otherwise leads to split-brain state.

## Absolute rules

- Never write to the config file from this command.
- Never dump unredacted secrets to stdout.
- Never fetch tokens from env and print them.
