# notify

*[繁體中文](./README_zhtw.md)*

Part of the [claude-workbench](../../README.md) family. See [`SPEC.md §4`](../../SPEC.md) for the full design.

Reach you through an external channel (currently **Pushover**) when Claude Code needs attention — so "AI stalls while user is AFK" stops happening.

## Events that trigger a push

Claude Code fires a `Notification` hook on four event types. Each is routable:

| Event | Meaning | Default priority |
|---|---|---|
| `permission_prompt` | Claude wants tool permission | high |
| `elicitation_dialog` | Claude is asking the user | high |
| `idle_prompt` | Claude is idle awaiting input | normal (throttled to 1 / 5 min) |
| `auth_success` | Auth flow finished | low |

## Install

```bash
> /plugin install notify@claude-workbench
> /notify:setup         # guided Pushover config (prompts for tokens)
> /notify:test          # send a test push
```

`/notify:setup` handles three things in one go:
1. Writes your Pushover tokens to `~/.claude-workbench/.env` (chmod 600) — the dispatcher auto-loads this file, **no shell rc edits required**.
2. Writes `~/.claude-workbench/notify-config.json` with `${VAR}` references (tokens never appear in the JSON).
3. Links the `workbench-notify` CLI into `~/.claude-workbench/bin/` so sibling plugins can discover it.

**PATH setup is optional** — only needed if you want to run `workbench-notify` manually from your terminal. Slash commands and hook scripts auto-prepend PATH when they run. For terminal use:

```bash
export PATH="$HOME/.claude-workbench/bin:$PATH"
```

## Config

Two files live side by side in `~/.claude-workbench/`:

- **`.env`** — your tokens (chmod 600; managed by `/notify:setup`):
  ```
  PUSHOVER_USER_KEY=u...
  PUSHOVER_APP_TOKEN=a...
  ```
- **`notify-config.json`** — routing rules and provider flags (safe to commit to a dotfile repo, since it only references env vars):
  ```json
  {
    "schema_version": 1,
    "default_provider": "pushover",
    "providers": {
      "pushover": {
        "enabled": true,
        "user_key": "${PUSHOVER_USER_KEY}",
        "app_token": "${PUSHOVER_APP_TOKEN}"
      }
    },
    "rules": [
      { "match": { "notification_type": "permission_prompt" },  "providers": ["pushover"], "priority":  1 },
      { "match": { "notification_type": "elicitation_dialog" }, "providers": ["pushover"], "priority":  1 },
      { "match": { "notification_type": "idle_prompt" },        "providers": ["pushover"], "priority": -1, "throttle_seconds": 300 },
      { "match": { "notification_type": "auth_success" },       "providers": ["pushover"], "priority": -2 }
    ]
  }
  ```

Secrets ONLY live in `.env`. The JSON only holds `${VAR}` references, resolved at runtime.

## CLI

`workbench-notify` is the stable integration surface for sibling plugins:

```bash
workbench-notify \
  --title "Kanban" \
  --message "task-042 needs your decision" \
  --priority high
```

Health check (used by siblings for capability detection):

```bash
workbench-notify --health   # exit 0 when config is readable AND at least one provider enabled
```

## Slash commands

| Command | Purpose |
|---|---|
| `/notify:setup` | Interactive Pushover config + CLI install |
| `/notify:test` | Send a test push |
| `/notify:config` | Show or edit the config path |

## What gets pushed

Messages are scrubbed of token-shaped substrings (`sk-…`, `ghp_…`, `xoxb-…`, JWTs, AWS keys, bare hex ≥32) before send. Failures append to `~/.claude-workbench/logs/notify-failures.log` — the hook never blocks Claude.

## Not in v0.1.0

- ntfy / Slack / Telegram providers (Phase 8+)
- Per-project override files
- Rate-limit accounting beyond simple time-window throttle
