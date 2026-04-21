---
description: Send a test push through the notify plugin.
argument-hint: [--message=<text>] [--priority=<low|normal|high>]
allowed-tools: Bash(workbench-notify:*), Bash(test:*), Bash(cat:*)
---

# /notify:test

Arguments: `$ARGUMENTS`

## 1. Parse args

- `--message=<text>` — override default test message.
- `--priority=<low|normal|high>` — default `normal`.

## 2. Health-check first

Run:

```bash
workbench-notify --health
```

- Exit 0 → proceed.
- Non-zero → STOP. Tell the user to run `/notify:setup` and surface the stderr from the health check.

If `workbench-notify` isn't on PATH at all, tell the user to either re-run `/notify:setup` or add `~/.claude-workbench/bin` to PATH.

## 3. Send

```bash
workbench-notify \
  --title "Claude Code · test" \
  --message "${MESSAGE:-Test push from /notify:test at $(date -Iseconds)}" \
  --priority "${PRIORITY:-normal}"
```

Check exit code:
- 0 → report "✓ sent. If nothing arrived, check ~/.claude-workbench/logs/notify-failures.log".
- non-zero → surface the last line of the failure log.

## 4. Tail the failure log (only if exit non-zero)

```bash
test -f ~/.claude-workbench/logs/notify-failures.log && \
  cat ~/.claude-workbench/logs/notify-failures.log | tail -n 5
```

## Absolute rules

- Never send more than one push per invocation.
- Never include the user's tokens in the message body.
- Do NOT retry on failure inside this command — report and let the user fix config.
