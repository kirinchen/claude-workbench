---
description: Send a message to another herdr-core terminal and confirm it was delivered, queued, or refused.
argument-hint: <terminal> <what to say>
allowed-tools: Bash(hc:*)
---

# /hc:send

Arguments: `$ARGUMENTS`

- `$1` — the terminal: a name, an address (`t7`), or `machine/t7`. Get it from `/hc:ls`.
- Everything after it — what to say. Required.

This writes into someone else's working session — compose deliberately.

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
