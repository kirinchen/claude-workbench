---
description: List every tmux session with its status (idle / busy / queued) and last line of output.
allowed-tools: Bash(bash:*), Bash(python3:*)
---

# /tmux:ls

Show what every tmux session on this machine is doing, so the user can pick a
name for `/tmux:review`, `/tmux:draft`, or `/tmux:send`.

**Session names are not tab-completable.** That is the whole reason this
command exists: run it first, read a name off the list, then type it.

## 1. Gather

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/tmux-sessions.sh
```

Exit 2 means no tmux server is running — say so and stop.

## 2. Report

Print the table as-is, then add one short line of orientation, for example:

- which sessions are **busy** right now (someone is waiting on them),
- which have a **real draft sitting in the input box** (`draft = yes`) —
  `/tmux:draft` on those will *rewrite* that draft, not add to it,
- `draft = ~` is only a dim placeholder of input someone abandoned earlier.
  The box is empty; there is nothing to preserve. Do not report it as an
  unsent message.
- which are showing a **dialog** and therefore cannot be typed into until a
  human answers it.

Close with the three follow-up commands and a real session name from the list:

```
/tmux:review <name> [what you want to know]
/tmux:draft  <name> <what to say>     # fills the box, does not send
/tmux:send   <name> <what to say>     # fills the box and presses Enter
```

Do not editorialise about sessions you cannot see into. If a summary line is
empty, say the session has no visible output rather than inventing one.
