# hc

Drive your *other* agent terminals from inside Claude Code, when they live in
[herdr-core](https://herdr.dev/core/) (`hc`) rather than tmux. List them, read
what they are doing, start a new one, send one a message.

This is the herdr-core counterpart of the [`tmux`](../tmux) plugin. Requires
the `hc` CLI on PATH and Python 3 (stdlib only).

## Commands

| Command | What it does |
|---|---|
| `/hc:ls` | Every terminal with its status (idle / working / blocked / done) and folder, across added machines. |
| `/hc:create <name> [dir] [first task]` | Start a terminal in a directory, launch Claude Code in it, and add it to the Herdr App sidebar. Refuses a name that is already live. |
| `/hc:review <terminal> [what you want to know]` | Read the screen (default 200 lines of history) and answer, always leading with the status. |
| `/hc:send <terminal> <what to say>` | Paste a message and press Enter, then confirm it was delivered or queued. Refuses a `blocked` terminal. |

## What is different from the tmux plugin

- **Status is reported, not scraped.** herdr-core takes each program's status
  from OSC 7501. There is no `tmux-state.py` equivalent here and there should
  not be one — do not infer busy/idle from screen text.
- **No `/hc:draft`.** `hc send` always presses Enter; there is no CLI way to
  type into a box without submitting. `hc send` instead waits for a person's
  unfinished draft before typing, and `--if idle` sends only when the agent is
  free.
- **Creating a terminal is not enough for the Herdr App to show it.** The App
  sidebar draws a Space / Tab layout stored in the core document `herdr-app`.
  `scripts/hc-app-place.py` adds the new terminal to the Space whose folder is
  its working directory (creating the Space if needed). It only ever adds.
- **Other machines need no ssh.** After `hc machine add <host>`, the same
  commands take `machine/<name>` addresses.

## Safety

- These commands never stop or restart the core (`hc server stop` ends every
  terminal on it) and never kill a terminal.
- `/hc:send` does not use `--force`: answering someone's permission dialog is
  their call.
- Flags for `hc run` go **before** `--`; everything after it is the program's
  argv. `hc run … -- claude --json` passes `--json` to `claude`.

## Scripts

| Script | Role |
|---|---|
| `scripts/hc-ls.py [--json]` | Table of live terminals. |
| `scripts/hc-create.sh <name> --cwd <dir> [--run <cmd>\|--no-run] [--task <text>]` | Create, place in the App layout, print the new terminal's state. Exit 3 exists · 4 bad name · 5 no directory · 6 no hc. |
| `scripts/hc-app-place.py <terminal> [--dry-run]` | Idempotently add one terminal to the Herdr App layout. |
