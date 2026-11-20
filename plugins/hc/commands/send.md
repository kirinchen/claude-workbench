---
description: Send a message to another herdr-core terminal and confirm it was delivered, queued, or refused.
argument-hint: [terminal] <what to say>
allowed-tools: Bash(hc:*), Bash(python3:*), AskUserQuestion
---

# /hc:send

Arguments: `$ARGUMENTS`

- `$1` — the terminal: a name, an address (`t7`), or `machine/t7`. Optional: without it (or when it is no terminal) you pick from a menu, step 0.
- Everything after it — what to say. Asked for after picking when missing.

This writes into someone else's working session — compose deliberately.

## 0. Pick the terminal (when `$1` is missing or not a terminal)

`$1` may be empty, or a partial name the user remembers. Don't make them type an exact
address: let them choose from a menu.

```bash
hc get "$1" --json        # skip when $1 is empty; exit 0 → $1 is the terminal, go to step 1
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/hc-pick.py --for send --query "$1"
```

The script prints one of:

- `{"pick": {...}}` — one terminal left: use its `address` from here on and say which
  one you took (`name (address)`) in the report. Later steps' `$1` means that address.
- `{"ask": {header, question, options}}` — show it with **AskUserQuestion**: copy
  `header`, `question`, and each option's `label` / `description` exactly; never add,
  drop or reorder options (the menu holds 4). Then run the script again with the
  chosen option's `args` (quote each one). The user typing text into "Other" instead →
  run it again with `--for send --query "<their text>"`. Repeat until `pick`.
- `{"none": "..."}` after a `--query` from `$1` → `$1` was probably the start of the
  message, not a name: run it again without `--query`. `none` otherwise → say so, show
  `/hc:ls`, stop.
- Exit 2 — `hc` missing or the core unreachable; say so and stop.

The menu goes machine → space → terminal, skipping a level when everything fits on one
screen. This session's own terminal is never offered.

The message — everything after `$1`. When `$1` was not a terminal and there is
more text, the whole of `$ARGUMENTS` may be the message: decide by reading it. No message
at all → after picking, ask the user what to say (a plain question, not a menu) and wait
for the answer before step 1.

## 1. Check the state

```bash
hc get "$1" --json
```

- Exit 3 → no such terminal; run `/hc:ls`, relay the list, stop.
- `status: blocked` → **stop**. A person has to answer a prompt there. Do not
  use `--force`: that would answer their permission dialog for them.
- `status: working` → the message will be queued behind the current turn. Say
  so up front. If the user wants it to arrive only when the agent is free, use
  `--if idle` in step 3 and report "not sent — it is busy" when it is refused.

## 2. Compose

One message, in the user's language. No literal newlines.

## 3. Send

```bash
hc send "$1" "<composed text>" --json
```

`hc send` pastes the text and presses Enter. It waits (up to 60 s) for a person
who is mid-typing in that terminal to finish or clear their draft, so an unsent
draft is not clobbered. There is no "type without sending" mode.

Exit codes: 3 not found · 9 blocked · 10 status mismatch (`--if` did not hold).

## 4. Confirm — do not skip

```bash
hc get "$1" --json
hc read "$1" --lines 20
```

| Evidence | Report |
|---|---|
| Message visible in the transcript, `status: working` | Delivered; it is working on it. |
| `status` was `working` before and the message sits in its queue | Queued behind the current turn. |
| Message nowhere on screen | Ambiguous — say so. Do not resend blindly; it may still have arrived. |

## 5. Report

```
<terminal> — <delivered | queued | not sent>

  sent: <the exact text>

<one line of evidence>
```
