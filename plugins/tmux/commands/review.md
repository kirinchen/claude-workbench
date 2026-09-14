---
description: Capture a tmux session's screen and report what it is doing — busy, idle, or holding queued messages.
argument-hint: <session> [what you want to know] [--depth N]
allowed-tools: Bash(bash:*), Bash(python3:*)
---

# /tmux:review

Arguments: `$ARGUMENTS`

- `$1` — the session name (exact; get it from `/tmux:ls`).
- Everything after it — what the user wants to know. Optional; with no
  description, give a general "what is going on in there" read.
- `--depth N` anywhere in the arguments — how many lines of scrollback to
  capture. Default **200**.

## 1. Read the session

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/tmux-capture.sh "$1" -S 200
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/tmux-state.py "$1"
```

If either exits 2 the session does not exist — the script already printed the
live session list. Relay that list and stop; do not guess at a near-miss name.

## 2. Establish the state before analysing content

`tmux-state.py` gives this directly — report it in one line, always, even when
the user only asked about content:

| `status` | What to tell the user |
|---|---|
| `idle` | Not working. Ready for input. |
| `busy` | Working right now (`esc to interrupt` is showing). |
| `queued` / `busy+queued` | **Busy and already holding queued messages** — the box shows `Press up to edit queued messages`. Anything sent now lands behind them. |
| `dialog` | Blocked on a dialog/selector a human must answer. Cannot be typed into. |
| `plain` (ui) | Not a Claude Code TUI — a shell or another program. Say so; the busy/queue read does not apply. |

Also mention `has_draft: true` — there is real unsent text sitting in its input
box, which a later `/tmux:draft` would overwrite.

A non-empty `ghost` is **not** a draft: it is the dim placeholder Claude Code
shows in an *empty* box for input abandoned earlier. Mention it only as
"nothing in the box (it still shows … as a placeholder)" — never as a pending
message.

## 3. Analyse against the description

Read the captured screen and answer what was actually asked. Typical asks:

- "is it stuck?" → look for an unanswered question, a dialog, or a long-idle
  spinner versus a genuinely finished turn.
- "what did it conclude?" → summarise the last assistant turn.
- "did my last message land?" → find it echoed in the transcript.

Ground every claim in a line you can point at. The capture is the only
evidence; if the answer is not on screen, say the scrollback does not go back
far enough and suggest a larger `--depth`.

## 4. Report

```
<session> — <status in plain words>

<2–5 lines answering the description, or a general read if none was given>

Draft in box: <the text, or "none" — say "placeholder only" if `ghost` is set>
```

Keep it short. The user is checking on a session, not reading a report.
