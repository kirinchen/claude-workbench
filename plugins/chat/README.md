# chat

Lightweight conversation threads for Claude Code. Start a chat, and every turn
is logged to a markdown file you can re-read, summarise, and resume later.

`chat` is **logging only** — it does not change how Claude behaves. "Chat mode"
is just a per-session recording marker.

## Commands

| Command | What it does |
|---|---|
| `/chat:new [name]` | Start a thread. Records this session to `doc/chat/{name}.md`. |
| `/chat:exit` | Stop recording. The thread file is kept. |
| `/chat:list` | List saved threads, newest first, marking the one recording now. |
| `/chat:note [name]` | Summarise the active thread into `doc/note/{name}.md`. |
| `/chat:resume <name\|N\|keyword>` | Re-open a saved thread and record into it again. |

## How it works

```
/chat:new ──> doc/chat/{name}.md                 (thread, committed to git)
          └─> .claude/chat/sessions/{id}.json     (session state, git-ignored)

every turn ──> Stop hook ──> chat-logger.py ──> append to doc/chat/{name}.md
```

- The `Stop` hook appends user messages and Claude's text replies after every
  turn. Thinking, tool calls, and system noise are filtered out.
- Chat mode is **session-scoped**: it ends when the Claude Code session ends
  (the `SessionEnd` hook clears the state). Use `/chat:resume` to continue in a
  new session.
- The `/chat:new` turn itself is not logged — recording starts with your next
  message.

## Files

| Path | Tracked | Purpose |
|---|---|---|
| `doc/chat/{name}.md` | git | The conversation log. |
| `doc/note/{name}.md` | git | Summaries produced by `/chat:note`. |
| `.claude/chat/sessions/*.json` | ignored | Per-session runtime state. |

## Resume lookup

`/chat:resume` resolves its argument as: exact thread name → a number (the
N-th most recent thread) → case-insensitive keyword match on the file name.

## Install

Part of the [claude-workbench](https://github.com/kirin/claude-workbench)
marketplace. Enable the `chat` plugin — no setup, tokens, or dependencies
required.
