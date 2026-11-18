---
description: Read a herdr-core terminal's screen and report what it is doing — working, idle, blocked, or done.
argument-hint: <terminal> [what you want to know] [--depth N]
allowed-tools: Bash(hc:*)
---

# /hc:review

Arguments: `$ARGUMENTS`

- `$1` — the terminal: a name, an address (`t7`), or `machine/t7`. Get it from `/hc:ls`.
- Everything after it — what the user wants to know. Optional.
- `--depth N` — lines of history above the screen. Default **200**.

## 1. Read it

```bash
hc get "$1" --json
hc read "$1" --lines 200
```

Exit 3 from either means no such terminal — run `/hc:ls`, relay the list and
stop; do not guess a near-miss name.

## 2. State first, content second

Report the status in one line, always. It comes from `hc get` (the program's
own OSC 7501 report), never from screen text:

| `status` | Tell the user |
|---|---|
| `idle` | Not working. Ready for input. |
| `working` | Working right now. |
| `blocked` | Waiting on a person — a permission prompt or a question. `/hc:send` will refuse. |
| `done` | Finished a turn nobody has looked at yet. |
| `error` | Hit an error; read why on screen. |
| none | A plain program (shell, server) — no status to report. |

While a terminal is `working`, `blocked` or `error`, `hc read` returns only the
visible screen and marks the read incomplete. Say so if the answer might be
further up.

## 3. Answer what was asked

Ground every claim in a line you can point at. If the answer is not on screen,
say the history does not reach that far and suggest a larger `--depth`.

## 4. Report

```
<terminal> — <status in plain words>

<2–5 lines answering the question, or a general read if none was given>
```

Keep it short.
