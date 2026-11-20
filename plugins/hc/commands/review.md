---
description: Read a herdr-core terminal's screen and report what it is doing — working, idle, blocked, or done.
argument-hint: [terminal] [what you want to know] [--depth N]
allowed-tools: Bash(hc:*), Bash(python3:*), AskUserQuestion
---

# /hc:review

Arguments: `$ARGUMENTS`

- `$1` — the terminal: a name, an address (`t7`), or `machine/t7`. Optional: without it (or when it is no terminal) you pick from a menu, step 0.
- Everything after it — what the user wants to know. Optional.
- `--depth N` — lines of history above the screen. Default **200**.

## 0. Pick the terminal (when `$1` is missing or not a terminal)

`$1` may be empty, or a partial name the user remembers. Don't make them type an exact
address: let them choose from a menu.

```bash
hc get "$1" --json        # skip when $1 is empty; exit 0 → $1 is the terminal, go to step 1
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/hc-pick.py --for review --query "$1"
```

The script prints one of:

- `{"pick": {...}}` — one terminal left: use its `address` from here on and say which
  one you took (`name (address)`) in the report. Later steps' `$1` means that address.
- `{"ask": {header, question, options}}` — show it with **AskUserQuestion**: copy
  `header`, `question`, and each option's `label` / `description` exactly; never add,
  drop or reorder options (the menu holds 4). Then run the script again with the
  chosen option's `args` (quote each one). The user typing text into "Other" instead →
  run it again with `--for review --query "<their text>"`. Repeat until `pick`.
- `{"none": "..."}` after a `--query` from `$1` → `$1` was probably the start of the
  message, not a name: run it again without `--query`. `none` otherwise → say so, show
  `/hc:ls`, stop.
- Exit 2 — `hc` missing or the core unreachable; say so and stop.

The menu goes machine → space → terminal, skipping a level when everything fits on one
screen. This session's own terminal is never offered.

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
