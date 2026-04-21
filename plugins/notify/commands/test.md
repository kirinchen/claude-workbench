---
description: Send a test push through the notify plugin.
argument-hint: [--message=<text>] [--priority=<low|normal|high>]
allowed-tools: Bash(workbench-notify:*), Bash(test:*), Bash(cat:*), Bash(export:*)
---

# /notify:test

Arguments: `$ARGUMENTS`

Every Bash block below prepends `~/.claude-workbench/bin` to PATH first so this command works **even when the user hasn't added that to their shell rc**.

## 1. Parse args

- `--message=<text>` — override default test message.
- `--priority=<low|normal|high>` — default `normal`.

## 2. Health-check first

Run:

```bash
export PATH="$HOME/.claude-workbench/bin:$PATH"
workbench-notify --health
```

- Exit 0 → proceed.
- Non-zero → STOP. Tell the user to run `/notify:setup` and surface the stderr from the health check.

If `workbench-notify` still isn't found even with the PATH prepend, the shim was never installed — tell the user to re-run `/notify:setup`.

## 3. Send

```bash
export PATH="$HOME/.claude-workbench/bin:$PATH"
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
- Always prepend PATH in each Bash block (redundant across blocks is fine — each block is its own subshell).
