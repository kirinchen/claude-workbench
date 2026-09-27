---
description: Start a new detached tmux session in a working directory and launch Claude Code in it.
argument-hint: <session> [dir or repo] [what it is for]
allowed-tools: Bash(bash:*), Bash(python3:*), Bash(tmux:*)
---

# /tmux:create

Arguments: `$ARGUMENTS`

- `$1` — the session name. Required.
- The rest — a directory (or a repo name), and optionally what the session is
  for. Both optional; infer the directory from the name when it is not given.

Creates the session **detached** and leaves it running. It does not attach,
does not send a first message, and never touches a session that already
exists.

## 1. Work out the name and the directory

If the user gave a name, use it verbatim. If they described the session
instead ("one for otter card 158"), propose a name that matches what is
already on this machine — run `/tmux:ls` and follow the local convention
rather than inventing one. A common shape is `<repo-short-name>` for a
long-lived session and `<repo-short-name>-<card id>` for one scoped to a
single task, but read the list before assuming.

The directory defaults to the sibling repo that matches the name
(`../<repo>` from the current project). If nothing plausible matches, ask
rather than guessing — a session in the wrong directory is worse than no
session.

`.` and `:` are tmux target separators and are rejected, as is whitespace.

## 2. Create

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/tmux-create.sh "<name>" --cwd "<dir>"
```

`claude` is what gets launched by default. Override with `--run "<cmd>"`, or
pass `--no-run` for a plain shell.

Exit codes are all fail-loud, and each means something different:

| Exit | Meaning | What to do |
|---|---|---|
| 3 | A session with that name already exists | Stop. Do not restart it — report it and offer `/tmux:send` instead. |
| 4 | The name is not addressable in tmux | Propose a corrected name. |
| 5 | The directory does not exist | Stop and ask; do not fall back to the current directory. |

The script prints the new session's state after the command has had time to
boot. `ui: "claude-code"` with `status: idle` means Claude Code is up and
waiting; `ui: "plain"` means you are looking at a shell, so either `--no-run`
was used or the launch did not take.

## 3. Report

```
<name> — created

  cwd: <directory>
  ran: <command>
  <one line of state: idle / busy, and whether the Claude box is up>
```

Then give the follow-up, with the real name filled in:

```
/tmux:send <name> <first instruction>
```

Do not send that first message yourself unless the user asked for it in this
same request. Creating a session and briefing it are two decisions, and the
brief is usually the one they want to write.
