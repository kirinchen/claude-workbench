---
description: Leave chat mode — stop recording the current session's chat thread.
allowed-tools: Read, Bash(echo:*), Bash(rm:*)
---

# /chat:exit

Stop recording the chat thread for this session. The thread file itself is
kept — only the recording marker is removed.

## 1. Find the session state

```bash
echo "$CLAUDE_CODE_SESSION_ID"
```

Then `Read` the file `.claude/chat/sessions/{that session id}.json`.

- If the file does not exist → this session is not in a chat thread. Tell the
  user that and stop here.
- If it exists → note its `chat` and `file` fields.

## 2. Remove the recording marker

```bash
rm -f ".claude/chat/sessions/{session id}.json"
```

## 3. Confirm

Tell the user:

- Recording stopped — the thread is saved at `doc/chat/{chat}.md`.
- `/chat:note` summarises it into `doc/note/`.
- `/chat:resume {chat}` re-opens it later (in this or a future session).

The conversation can continue normally — it just won't be logged anymore.
