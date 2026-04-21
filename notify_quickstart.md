# notify — quickstart

*[繁體中文](./notify_quickstart_zhtw.md)*

> Push notifications from Claude Code to your phone via Pushover. So "AI stalls while user is AFK" stops happening.

*See [`SPEC.md §4`](./SPEC.md) for full design, [`plugins/notify/`](./plugins/notify) for the code.*

---

## 0. Prerequisites

- Claude Code installed.
- A Pushover account (free trial, one-time $5 per platform to unlock).

**No shell rc changes are required.** The dispatcher auto-loads tokens from `~/.claude-workbench/.env`, and hook scripts auto-prepend `~/.claude-workbench/bin` to PATH. You only need to add `~/.claude-workbench/bin` to PATH in your shell rc if you want to run `workbench-notify` **manually from your terminal** (e.g. for debugging).

---

## 1. Get Pushover credentials

1. Sign up at **https://pushover.net** (free).
2. The dashboard home page shows **Your User Key** — a 30-char string starting with `u`. Copy it.
3. Scroll to **"Your Applications"** → **Create an Application/API Token** → name it (e.g. `claude-code`) → you get a 30-char **API Token/Key** starting with `a`. Copy it.
4. Install the Pushover app on your phone (iOS / Android, one-time purchase unlocks beyond the 7-day trial) and log into the same account. On first launch the app registers a device — that's what receives pushes.

Have both keys ready — `/notify:setup` will ask for them.

---

## 2. Install the plugin

Inside Claude Code (any project):
```
> /plugin marketplace add kirinchen/claude-workbench
> /plugin install notify@claude-workbench
```

---

## 3. Run setup (handles tokens for you)

```
> /notify:setup
```

What it does — **no shell rc edits, no env var exports by hand**:
1. Asks for your Pushover user key and app token.
2. Writes them to `~/.claude-workbench/.env` with `chmod 600`. That file is auto-loaded by the dispatcher at every hook / CLI call — no shell export needed.
3. Writes `~/.claude-workbench/notify-config.json` with `${PUSHOVER_USER_KEY}` / `${PUSHOVER_APP_TOKEN}` references — **tokens never appear inside the JSON**.
4. Runs `install-cli.sh` which symlinks `workbench-notify` into `~/.claude-workbench/bin/`.

To reconfigure later: `/notify:setup --reset`.

---

## 4. Verify

Inside Claude:
```
> /notify:test
```
Your phone should buzz within ~3 seconds with "Claude Code · test".

Outside Claude (**only** if you added `~/.claude-workbench/bin` to your shell rc's PATH):
```bash
workbench-notify --health
#  -> exit 0, prints "notify: ok" when config + provider are both good
workbench-notify --title "Hi" --message "from shell" --priority normal
```

If `workbench-notify` isn't found from the terminal, that's expected with the default setup — `/notify:test` inside Claude still works, because it prepends PATH in its own command body.

---

## 5. Understand what fires pushes

Claude Code emits four `Notification` hook events; the plugin routes each via `rules[]` in the config:

| Event | Meaning | Default priority | Throttle |
|---|---|---|---|
| `permission_prompt` | Claude wants tool permission | high | none |
| `elicitation_dialog` | Claude is asking a question via `AskUserQuestion` | high | none |
| `idle_prompt` | Claude is idle awaiting input | normal | 5 min |
| `auth_success` | Auth flow finished | low | none |

When sibling plugins (kanban, docsync, memory) want to push, they call the CLI:
```bash
workbench-notify --title "Kanban" --message "task-042 blocked" --priority high
```

---

## 6. Tune rules

Edit `~/.claude-workbench/notify-config.json`. Key knobs:

- `providers.pushover.enabled`: set to `false` to mute entirely without uninstalling.
- `providers.pushover.device`: set to a device name to send only to one device instead of all registered ones.
- `providers.pushover.sound_map`: override sound per event (see [Pushover sound list](https://pushover.net/api#sounds)).
- `rules[].throttle_seconds`: seconds of silence required between pushes for the same `(event, provider)` pair.
- `rules[].priority`: `-2` (lowest, silent) to `1` (high; `2` would be "emergency" but is clamped to `1` because the plugin doesn't wire Pushover's retry/expire pair).

After editing, re-check with `workbench-notify --health`. No restart needed — the dispatcher re-reads the config each call.

---

## 7. Security posture

- HTTPS-only to Pushover.
- Messages run through a scrubber that redacts common token shapes (`sk-…`, `sk-ant-…`, `ghp_…`, `xox[abpr]-…`, `AKIA…`, `AIza…`, JWTs, bare hex ≥40 chars) before send.
- Failures append to `~/.claude-workbench/logs/notify-failures.log` — **no message body** is written, only reason, to avoid secret leak via log.
- No telemetry. The plugin never contacts anything except your configured provider.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/notify:test` says "sent" but no push arrives | Pushover app not logged in, or no device registered | Open the Pushover app, sign in, let it complete device registration; then resend |
| `/notify:test` fails with `workbench-notify: command not found` | `install-cli.sh` never ran (setup interrupted) | Re-run `/notify:setup` — it runs the installer as its final step |
| `workbench-notify: command not found` **only when running from your terminal** | `~/.claude-workbench/bin` not on your shell PATH | Expected — not required for slash commands. Add `export PATH="$HOME/.claude-workbench/bin:$PATH"` to `~/.bashrc` if you want manual terminal use |
| `workbench-notify --health` exit 1: "unconfigured" | `~/.claude-workbench/notify-config.json` missing | Run `/notify:setup` |
| `workbench-notify --health` exit 1: "no enabled provider" | `providers.pushover.enabled: false` | Flip it back to `true` |
| Push arrives but body is empty / "[REDACTED]" | Scrubber over-matched on a legit string (bare hex etc.) | Report as bug; workaround: shorten the hex in the message before passing |
| `notify-failures.log` says "pushover: send returned falsy" and health is ok | Tokens in `~/.claude-workbench/.env` are wrong | `/notify:setup --reset` and re-enter tokens |
| Duplicate / spammy pushes | Rules have no throttle | Add `"throttle_seconds": 300` to noisy rules |

Inspect the failure log:
```bash
tail -n 20 ~/.claude-workbench/logs/notify-failures.log
```
Reset throttle state (e.g. after testing):
```bash
rm ~/.claude-workbench/state/notify-throttle.json
```

---

## 9. Uninstall

```
> /plugin uninstall notify@claude-workbench
```

This removes the plugin but leaves:
- `~/.claude-workbench/.env` (your Pushover tokens — you probably want these gone).
- `~/.claude-workbench/notify-config.json` (your config).
- `~/.claude-workbench/bin/workbench-notify` (symlink — now dangling).
- `~/.claude-workbench/logs/notify-failures.log`.

To fully clean:
```bash
rm -f ~/.claude-workbench/.env
rm -f ~/.claude-workbench/notify-config.json
rm -f ~/.claude-workbench/bin/workbench-notify
```

If you had also added `export PATH="$HOME/.claude-workbench/bin:$PATH"` to your shell rc, that's yours to keep or remove.

---

## 10. Next steps

- Add `kanban` (if you haven't): [`kanban_quickstart.md`](./kanban_quickstart.md). Task transitions automatically push when both are installed.
- Add `docsync`: [`docsync_quickstart.md`](./docsync_quickstart.md). When `enforcement=block`, docsync gates `/kanban:done` and the blocked transition pushes via this plugin.
- See [`SPEC.md §8.8`](./SPEC.md) for the end-to-end flow when kanban + notify + (future) memory + docsync are all installed.
