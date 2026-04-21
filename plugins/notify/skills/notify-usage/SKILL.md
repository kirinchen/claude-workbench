---
name: notify-usage
description: Use when the user asks about push notifications from Claude Code, mentions Pushover/ntfy, reports "I didn't get notified", wants to enable alerts, or when a sibling plugin (kanban, docsync, memory) needs to call `workbench-notify` for cross-plugin integration.
---

# Notify plugin — how it works and how to use it

The `notify` plugin reaches the user through an external channel (v0.1.0: **Pushover**) when Claude Code needs attention. It exists so "AI stalls, user is AFK" stops happening.

## 0. Absolute rules

1. **Never inline secrets** (user keys, app tokens) in `notify-config.json`. Use `${ENV_VAR}` references.
2. **Never push from a tight loop.** Every dispatch writes to the external provider's network; use the `throttle_seconds` rule field or don't fire at all.
3. **Never push message bodies that can contain secrets** without relying on the built-in scrubber. If you're constructing a message yourself, still redact obvious tokens.
4. **Never assume the push was delivered.** Notify is best-effort. If the user needs an acknowledgement, block on their reply in-session; don't use notify as a sync primitive.
5. **Never call the dispatcher directly** from sibling plugin code. Use `workbench-notify`. That's the stable surface.

## 1. Architecture

```
Claude Code event → Notification hook → notify-dispatch.py
                                              │
                                        load config
                                              │
                                        match rule
                                              │
                                        providers/pushover.py
                                              │
                                         HTTPS POST
```

For sibling plugins:

```
kanban-autocommit.sh → workbench-notify --title … --message … --priority …
                               │
                          --cli mode
                               │
                          notify-dispatch.py (same path)
```

## 2. Events

Claude Code fires four `Notification` event types:

| Event | When |
|---|---|
| `permission_prompt` | Claude wants tool permission (`--allowedTools` didn't whitelist it). |
| `elicitation_dialog` | Claude is asking the user a question via `AskUserQuestion`. |
| `idle_prompt` | Claude is idle waiting for the next user prompt. |
| `auth_success` | Authentication flow finished. |

The plugin routes each via the `rules[]` array in `notify-config.json`. Unmatched events fall back to `default_provider` at priority 0.

## 3. Config + secrets location

Two files in `~/.claude-workbench/` (outside any project so nothing leaks into git):

- `notify-config.json` — routing rules, provider flags. Uses `${VAR}` references for secrets.
- `.env` — actual token values. Managed by `/notify:setup`. chmod 600. Auto-loaded by the dispatcher at every invocation.

```
# ~/.claude-workbench/.env — created by /notify:setup, never by hand
PUSHOVER_USER_KEY=u...
PUSHOVER_APP_TOKEN=a...
```

**Do NOT instruct users to `export PUSHOVER_*` in their shell rc.** The `.env` file handles it. If a user already has shell exports, those still win (process env takes precedence over the file), so nothing breaks for existing setups — but new setups go through `.env`.

## 4. When to use each slash command

| Command | Use when |
|---|---|
| `/notify:setup` | First-time install, changing provider tokens, re-linking the CLI. |
| `/notify:test` | Verifying config after setup, or debugging "I didn't get a push". |
| `/notify:config` | Showing path + current effective config; editing rules. |

## 5. Integration from sibling plugins

Before invoking, do capability detection:

```bash
if command -v workbench-notify >/dev/null 2>&1 && workbench-notify --health >/dev/null 2>&1; then
    workbench-notify --title "Kanban" --message "Started: $title" --priority low
fi
```

`--health` proves both the CLI is installed AND the config is valid AND a provider is enabled. Using `command -v` alone is a common mistake — see SPEC §8.7.

Priority guidance for siblings:

| Situation | Priority |
|---|---|
| Informational (task started, doc updated) | `low` |
| State change user cares about (task completed) | `normal` |
| Action needed (BLOCKED, decision required, docsync gate fired) | `high` |
| Never use `emergency` — it requires a Pushover retry/expire pair this plugin doesn't configure | — |

## 6. Debugging

- **No push arrived** — run `workbench-notify --health`. If that's green, check `~/.claude-workbench/logs/notify-failures.log`.
- **Duplicate pushes** — look at `~/.claude-workbench/state/notify-throttle.json`. A rule's `throttle_seconds` only throttles within `(event, provider)`; rebooting or `rm`-ing the state file resets the window.
- **Env var not expanded** — the dispatcher only expands `${UPPERCASE_VAR}`. Lowercase or `$VAR` forms are left literal, which is usually the bug.
