---
description: Interactive setup for the notify plugin — Pushover tokens + CLI install.
allowed-tools: Read, Write, Bash(mkdir:*), Bash(ls:*), Bash(test:*), Bash(bash:*), Bash(chmod:*), AskUserQuestion
---

# /notify:setup

Configure the `notify` plugin and install the `workbench-notify` CLI. Follow the steps exactly — do NOT ask free-form questions the script doesn't need.

## 1. Pre-flight

- Config path: `~/.claude-workbench/notify-config.json`.
- If it already exists, read it first. Treat this run as "update" rather than "initial", and skip Phase 2 unless the user asks to reconfigure (`/notify:setup --reset`).
- Check whether `${CLAUDE_PLUGIN_ROOT}/scripts/install-cli.sh` exists; you'll run it in Phase 4.

## 2. Ask about provider

Use `AskUserQuestion` once. v0.1.0 only supports Pushover, so this is effectively a confirmation:

> Configure Pushover now? (Other providers — ntfy / Slack / Telegram — land in v0.2+.)
>
> - Yes, I have Pushover keys.
> - Yes, but I don't have keys yet — show me where to get them.
> - Skip for now (just install the CLI shim).

If the user picks "show me where", tell them: create account at https://pushover.net, grab the 30-char **user key** from the dashboard, create an Application to get the **app token**. Then return to this command.

## 3. Capture tokens

If user chose to configure now, ask **once**, using `AskUserQuestion` (free-text via `allowFreeForm`):

> Pushover user key (starts with `u`)?

> Pushover app token (starts with `a`)?

Do NOT validate token format strictly — Pushover occasionally changes prefixes. Just check length ≥ 20 and reject whitespace/quotes.

**CRITICAL**: never write the tokens inline into `notify-config.json`. Write the config with `${PUSHOVER_USER_KEY}` / `${PUSHOVER_APP_TOKEN}` placeholders, then print an instruction block telling the user to export the env vars (see Phase 5).

## 4. Write config and install CLI

1. Create `~/.claude-workbench/` if missing (`mkdir -p`).
2. If config doesn't already exist, copy `${CLAUDE_PLUGIN_ROOT}/templates/notify-config.example.json` → `~/.claude-workbench/notify-config.json`.
3. If user skipped token capture: leave the example as-is.
4. Run `bash ${CLAUDE_PLUGIN_ROOT}/scripts/install-cli.sh` and surface its stdout verbatim. It handles:
   - `mkdir -p ~/.claude-workbench/bin`
   - `chmod +x` the scripts
   - `ln -sf` the shim

## 5. Emit next-steps block

Print (fill in the actual tokens the user supplied — do NOT paste the literal values into the message, paraphrase them as `<your-user-key>` for the user's own audit trail):

```
✓ notify configured.

Next:
  1. Export tokens in your shell rc (~/.bashrc, ~/.zshrc):
       export PUSHOVER_USER_KEY="u..."
       export PUSHOVER_APP_TOKEN="a..."
     Then `source` it or open a new shell.

  2. Ensure the CLI is on PATH:
       export PATH="$HOME/.claude-workbench/bin:$PATH"

  3. Verify:
       workbench-notify --health
       /notify:test

  4. Re-run this command with --reset to reconfigure.
```

## Absolute rules

- Never echo the actual token values back to the user in plain text after capture.
- Never write tokens inline into JSON; always use `${VAR}` references.
- Never skip step 4 (install-cli.sh) — siblings rely on the CLI being on PATH.
- Never mark the task complete if `workbench-notify --health` returns non-zero after setup; tell the user what to fix.
