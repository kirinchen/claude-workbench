# notify — quickstart

*[繁體中文](./notify_quickstart_zhtw.md)*

> Push notifications from Claude Code to your phone via Pushover. So "AI stalls while user is AFK" stops happening.

*See [`SPEC.md §4`](./SPEC.md) for full design, [`plugins/notify/`](./plugins/notify) for the code.*

---

## 0. Prerequisites

- Claude Code installed.
- A Pushover account (free trial, one-time $5 per platform to unlock).
- Shell rc (`~/.bashrc` or `~/.zshrc`) contains:
  ```bash
  export PATH="$HOME/.claude-workbench/bin:$PATH"
  ```

---

## 1. Get Pushover credentials

1. Sign up at **https://pushover.net** (free).
2. The dashboard home page shows **Your User Key** — a 30-char string starting with `u`. Copy it.
3. Scroll to **"Your Applications"** → **Create an Application/API Token** → name it (e.g. `claude-code`) → you get a 30-char **API Token/Key** starting with `a`. Copy it.
4. Install the Pushover app on your phone (iOS / Android, one-time purchase unlocks beyond the 7-day trial) and log into the same account. On first launch the app registers a device — that's what receives pushes.

---

## 2. Export tokens as env vars (**not** into JSON)

Add to `~/.bashrc` / `~/.zshrc`:
```bash
export PUSHOVER_USER_KEY="u..."          # Your User Key from dashboard
export PUSHOVER_APP_TOKEN="a..."         # API Token from the app you created
```
Then:
```bash
source ~/.bashrc    # or open a fresh terminal
```

**macOS caveat**: if you launch Claude Code from the Dock / Launchpad (GUI), it won't see shell rc env vars. Either (a) always start Claude from a terminal (`claude` in iTerm/Terminal), or (b) set the vars via `launchctl setenv` so the GUI app sees them too.

---

## 3. Install the plugin

Inside Claude Code (any project):
```
> /plugin marketplace add kirinchen/claude-workbench
> /plugin install notify@claude-workbench
```

---

## 4. Run setup

```
> /notify:setup
```

What it does:
1. Writes `~/.claude-workbench/notify-config.json` using `${PUSHOVER_USER_KEY}` / `${PUSHOVER_APP_TOKEN}` references — **tokens never land in the JSON file**.
2. Runs `install-cli.sh` which symlinks `workbench-notify` into `~/.claude-workbench/bin/`.
3. Prints the follow-up steps (export, PATH, verify).

If you re-run setup later: pass `--reset` to reconfigure.

---

## 5. Verify

Inside Claude:
```
> /notify:test
```
Your phone should buzz within ~3 seconds with "Claude Code · test".

Outside Claude:
```bash
workbench-notify --health
#  -> exit 0, prints "notify: ok" when config + provider are both good
workbench-notify --title "Hi" --message "from shell" --priority normal
```

---

## 6. Understand what fires pushes

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

## 7. Tune rules

Edit `~/.claude-workbench/notify-config.json`. Key knobs:

- `providers.pushover.enabled`: set to `false` to mute entirely without uninstalling.
- `providers.pushover.device`: set to a device name to send only to one device instead of all registered ones.
- `providers.pushover.sound_map`: override sound per event (see [Pushover sound list](https://pushover.net/api#sounds)).
- `rules[].throttle_seconds`: seconds of silence required between pushes for the same `(event, provider)` pair.
- `rules[].priority`: `-2` (lowest, silent) to `1` (high; `2` would be "emergency" but is clamped to `1` because the plugin doesn't wire Pushover's retry/expire pair).

After editing, re-check with `workbench-notify --health`. No restart needed — the dispatcher re-reads the config each call.

---

## 8. Security posture

- HTTPS-only to Pushover.
- Messages run through a scrubber that redacts common token shapes (`sk-…`, `sk-ant-…`, `ghp_…`, `xox[abpr]-…`, `AKIA…`, `AIza…`, JWTs, bare hex ≥40 chars) before send.
- Failures append to `~/.claude-workbench/logs/notify-failures.log` — **no message body** is written, only reason, to avoid secret leak via log.
- No telemetry. The plugin never contacts anything except your configured provider.

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/notify:test` says "sent" but no push arrives | Pushover app not logged in, or no device registered | Open the Pushover app, sign in, let it complete device registration; then resend |
| `workbench-notify: command not found` | `~/.claude-workbench/bin` not on PATH | Add to shell rc (Step 0), re-source |
| `workbench-notify --health` exit 1: "unconfigured" | `~/.claude-workbench/notify-config.json` missing | Run `/notify:setup` |
| `workbench-notify --health` exit 1: "no enabled provider" | `providers.pushover.enabled: false` | Flip it back to `true` |
| Push arrives but body is empty / "[REDACTED]" | scrubber overmatched on a legit string (bare hex etc.) | Report as bug; workaround: shorten the hex in the message before passing |
| GUI-launched Claude on macOS gets no pushes | env vars not inherited | Launch Claude from terminal, or use `launchctl setenv` |
| Duplicate / spammy pushes | rules have no throttle | Add `"throttle_seconds": 300` to noisy rules |

Inspect the failure log:
```bash
tail -n 20 ~/.claude-workbench/logs/notify-failures.log
```
Reset throttle state (e.g. after testing):
```bash
rm ~/.claude-workbench/state/notify-throttle.json
```

---

## 10. Uninstall

```
> /plugin uninstall notify@claude-workbench
```

This removes the plugin but leaves:
- `~/.claude-workbench/notify-config.json` (your config).
- `~/.claude-workbench/bin/workbench-notify` (symlink — now dangling).
- `~/.claude-workbench/logs/notify-failures.log`.

To fully clean:
```bash
rm -f ~/.claude-workbench/notify-config.json
rm -f ~/.claude-workbench/bin/workbench-notify
```
The env vars (`PUSHOVER_USER_KEY`, `PUSHOVER_APP_TOKEN`) are yours to keep or remove from shell rc.

---

## 11. Next steps

- Add `kanban` (if you haven't): [`kanban_quickstart.md`](./kanban_quickstart.md). Task transitions automatically push when both are installed.
- Add `docsync`: [`docsync_quickstart.md`](./docsync_quickstart.md). When `enforcement=block`, docsync gates `/kanban:done` and the blocked transition pushes via this plugin.
- See [`SPEC.md §8.8`](./SPEC.md) for the end-to-end flow when kanban + notify + (future) memory + docsync are all installed.
