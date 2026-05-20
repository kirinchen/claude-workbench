---
description: Start a new logged chat thread — the conversation is recorded to doc/chat/{name}.md until /chat:exit.
argument-hint: [chat-name]
allowed-tools: Read, Write, Bash(echo:*), Bash(mkdir:*), Bash(date:*), Bash(ls:*), Bash(test:*)
---

# /chat:new

Start a new **chat thread**. From now until `/chat:exit` (or the session
ends), every conversational turn in *this* session is appended to a markdown
log by the plugin's `Stop` hook.

This command **only turns on logging** — your behaviour, tools, and tone do
not change. "Chat mode" is purely a recording marker scoped to this session.

## 1. Gather facts

Run one bash block:

```bash
echo "session=$CLAUDE_CODE_SESSION_ID"
date '+%Y-%m-%d %H:%M'
date '+%Y-%m-%dT%H:%M:%S%z'
mkdir -p doc/chat .claude/chat/sessions
ls doc/chat 2>/dev/null
```

## 2. Resolve the chat name

- If `$ARGUMENTS` is non-empty, slugify it: lowercase, trim, spaces and
  punctuation → `-`, collapse repeats, keep only `[a-z0-9-]`.
- If `$ARGUMENTS` is empty, use `chat-YYYY-MM-DD`. If that file already exists
  in `doc/chat/`, append `-2`, `-3`, … until the name is free.

The thread file is `doc/chat/{name}.md`.

## 3. Refuse to clobber

If `doc/chat/{name}.md` already exists and the user gave an explicit name,
STOP. Do not overwrite it. Tell the user it exists and suggest
`/chat:resume {name}` to continue it, or `/chat:new {other-name}`.

## 4. Write the thread file

Create `doc/chat/{name}.md`:

```
# Chat: {name}

> Started {YYYY-MM-DD HH:MM} · session `{first 8 chars of the session id}`
```

## 5. Write the session state

Create `.claude/chat/sessions/{session id from step 1}.json`:

```json
{
  "chat": "{name}",
  "file": "doc/chat/{name}.md",
  "transcript_cursor": null,
  "started_at": "{ISO-8601 timestamp from step 1}"
}
```

`transcript_cursor: null` is intentional — it tells the `Stop` hook to set its
watermark on the next turn, so *this* `/chat:new` turn is not logged. Recording
begins with the user's next message.

## 6. Confirm

Tell the user briefly:

- Thread started: `doc/chat/{name}.md` — it records automatically every turn,
  nothing else to do.
- `/chat:exit` stops recording · `/chat:note` summarises the thread into
  `doc/note/` · `/chat:resume {name}` re-opens it later.

Then just continue the conversation normally.
