---
description: List every herdr-core terminal with its status (idle / working / blocked / done) and folder.
allowed-tools: Bash(python3:*), Bash(hc:*)
---

# /hc:ls

Show what every terminal in herdr-core is doing, so the user can pick a name
for `/hc:review` or `/hc:send`. This includes terminals on machines added with
`hc machine add` (their address reads `machine/t7`).

## 1. Gather

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/hc-ls.py
```

Exit 2 means `hc` is not installed or the core cannot be reached — say so and
stop. Do **not** try to start, stop or restart the core yourself.

## 2. Report

Print the table as-is (`*` marks the terminal this session runs in), then one
short line of orientation:

- which are **working** right now,
- which are **blocked** — a person has to answer a permission prompt or a
  question there; `/hc:send` will refuse to type into it,
- which are **done** — finished a turn that nobody has looked at yet,
- `-` in the status column is a plain program (a shell, a dev server): it
  reports no status, which is not the same as idle.

The status is what the program itself reports (OSC 7501). Never guess a status
from screen text.

Close with the follow-ups and a real name from the list:

```
/hc:review <name> [what you want to know]
/hc:send   <name> <what to say>
```
