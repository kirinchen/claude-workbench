---
description: Start a new herdr-core terminal in a working directory, launch Claude Code in it, and add it to the Herdr App sidebar.
argument-hint: <name> [dir or repo] [first task]
allowed-tools: Bash(bash:*), Bash(python3:*), Bash(hc:*)
---

# /hc:create

Arguments: `$ARGUMENTS`

- `$1` — the terminal name. Required. 1–32 of `a-z 0-9 - _`.
- The rest — a directory (or a repo name), and optionally the first task.

Creates the terminal in the background and leaves it running. It never touches
a terminal that already exists.

## 1. Work out the name and the directory

Use the name the user gave. If they described it instead ("one for otter card
158"), run `/hc:ls` and follow the convention already on this machine — a
common shape is `<repo>` for a long-lived agent and `<card id>-<repo>` for one
scoped to a task.

The directory defaults to the sibling repo matching the name (`../<repo>`). If
nothing plausible matches, ask — a terminal in the wrong directory is worse
than none.

## 2. Create

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/hc-create.sh "<name>" --cwd "<dir>"
```

- `claude` is launched by default; `--run "<cmd>"` overrides it, `--no-run`
  gives a plain shell.
- If the user gave a first task **in this same request**, pass it with
  `--task "<text>"`. It becomes the program's first argument, which is more
  reliable than sending to an agent that is still booting. Otherwise leave it
  out — creating a terminal and briefing it are two decisions.

| Exit | Meaning | What to do |
|---|---|---|
| 3 | A live terminal with that name exists | Stop. Do not restart it; offer `/hc:send`. |
| 4 | The name is not valid for hc | Propose a corrected one (lower case, no dots). |
| 5 | The directory does not exist | Stop and ask. |
| 6 | `hc` missing or the core is unreachable | Report it. Do not start the core yourself. |

The script also writes the terminal into the Herdr App layout (the core
document `herdr-app`). Without that step a terminal exists in the core but
never appears in the App sidebar. If it prints a warning that this failed, say
so — the terminal still works through `hc attach <name>`.

## 3. Report

```
<name> — created (<address>)

  cwd: <directory>
  ran: <command>
  status: <idle / working / blocked — from the JSON the script printed>
```

`blocked` right after creation usually means a first-run dialog (trust this
folder, browser tools). Read it with `/hc:review <name>` and tell the user;
do not answer a permission dialog on their behalf.

Then give the follow-up with the real name: `/hc:send <name> <instruction>`.
