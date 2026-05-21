---
description: Re-open a saved chat thread and resume recording into it.
argument-hint: <chat-name | number | keyword>
allowed-tools: Read, Write, Bash(echo:*), Bash(ls:*), Bash(mkdir:*), Bash(date:*), AskUserQuestion
---

# /chat:resume

Re-open a previously saved thread from `doc/chat/` and start recording new
turns into it again — for example, to continue it in a fresh session.

## 1. Gather facts

```bash
echo "session=$CLAUDE_CODE_SESSION_ID"
date '+%Y-%m-%d %H:%M'
date '+%Y-%m-%dT%H:%M:%S%z'
ls -t doc/chat/*.md 2>/dev/null
```

`ls -t` lists threads newest-first — that is the order used for numeric lookup.

## 2. Resolve `$ARGUMENTS` to exactly one thread

Match in this order:

1. **Exact** — `doc/chat/{$ARGUMENTS}.md` exists → use it.
2. **Number** — `$ARGUMENTS` is an integer N → the N-th file in the `ls -t`
   list (1 = most recent).
3. **Keyword** — case-insensitive substring of a thread's base name:
   - exactly one match → use it,
   - several matches → list them and ask the user to pick (`AskUserQuestion`),
   - no match → tell the user, show the available threads, and stop.

If `$ARGUMENTS` is empty, list the threads and ask which one to resume.

## 3. Load the thread into context

`Read` the resolved `doc/chat/{name}.md` in full. This is the conversation
history — use it so you can pick the thread up naturally.

## 4. Re-arm recording

Write `.claude/chat/sessions/{session id from step 1}.json`:

```json
{
  "chat": "{name}",
  "file": "doc/chat/{name}.md",
  "transcript_cursor": null,
  "started_at": "{ISO-8601 timestamp from step 1}"
}
```

`transcript_cursor: null` keeps the `/chat:resume` turn itself out of the log —
recording resumes with the user's next message.

If a state file already exists for this session (a different thread was
active), overwrite it — one session records into one thread at a time — and
mention the switch to the user.

Append a resume marker to the end of `doc/chat/{name}.md`:

```
> _— resumed {YYYY-MM-DD HH:MM} —_
```

## 5. Confirm

Briefly tell the user the thread is re-opened and recording, give a one-line
recap of where the conversation left off, and continue.
