---
name: chat-usage
description: Use when the user asks how the `chat` plugin works, mentions /chat:new /chat:exit /chat:note /chat:resume, asks where a chat log went, or reports that a chat thread is not being recorded.
---

# Chat plugin — logged conversation threads

The `chat` plugin records a Claude Code conversation to a markdown file so it
can be re-read, summarised, and resumed later. It is **logging only** — it does
not change how Claude behaves or what tools it uses.

## Model

- A **thread** is `doc/chat/{name}.md` — plain markdown, committed to git.
- "Chat mode" is a per-session marker:
  `.claude/chat/sessions/{session_id}.json` (runtime state, git-ignored).
  While that file exists, the `Stop` hook appends each new turn to the thread.
- Chat mode is **session-scoped**. It does not carry into a new Claude Code
  session — the `SessionEnd` hook clears the state file.

## Commands

| Command | Effect |
|---|---|
| `/chat:new [name]` | Create `doc/chat/{name}.md`, start recording this session. |
| `/chat:exit` | Stop recording (the thread file is kept). |
| `/chat:list` | List saved threads, newest first, marking the active one. |
| `/chat:note [name]` | Summarise the active thread → `doc/note/{name}.md`. |
| `/chat:resume <name\|N\|keyword>` | Re-open a saved thread and record into it again. |

## How recording works

`scripts/chat-logger.py` runs on every `Stop`. If this session has a state
file, it reads the session transcript and appends turns added since the last
run — user messages and Claude's text replies only. Thinking, tool calls, tool
results, slash-command echoes, subagent turns and system reminders are filtered
out.

`transcript_cursor` in the state file is the watermark. `/chat:new` and
`/chat:resume` set it to `null`, which makes the next `Stop` set the watermark
without logging — so the command's own turn never appears in the thread.

## Resume lookup

`/chat:resume` resolves its argument as: exact thread name → an integer (N-th
most recent thread) → case-insensitive keyword match on the file name. No index
file is kept; the filesystem under `doc/chat/` is the source of truth.

## Common issues

- **"My chat isn't being recorded."** Check `.claude/chat/sessions/` for a file
  named with the current session id (`echo $CLAUDE_CODE_SESSION_ID`). No file →
  not in chat mode; run `/chat:new` or `/chat:resume`.
- **"Recording stopped after I restarted Claude Code."** Expected — chat mode
  is session-scoped. Run `/chat:resume {name}` in the new session.
- **The first turn isn't logged.** Also expected — the watermark is set on the
  turn after `/chat:new`, so logging starts with the next message.
- **`/chat:note` output appears in the thread too.** `/chat:note` does not exit
  chat mode, so its confirmation is part of the still-recording session. Run
  `/chat:exit` first for a clean cut.
