---
description: Summarise the active chat thread into a durable note under doc/note/.
argument-hint: [note-name]
allowed-tools: Read, Write, Bash(echo:*), Bash(ls:*), Bash(mkdir:*), Bash(date:*), AskUserQuestion
---

# /chat:note

Distil a chat thread into a durable note: `doc/chat/{chat}.md` →
`doc/note/{note}.md`. This does **not** leave chat mode — recording continues,
so this command's own turn will also land in the thread.

## 1. Find the source thread

```bash
echo "$CLAUDE_CODE_SESSION_ID"
date '+%Y-%m-%d %H:%M'
ls doc/chat/*.md 2>/dev/null
```

`Read` `.claude/chat/sessions/{that session id}.json`:

- If it exists → the source thread is its `chat` / `file`.
- If it does not exist (this session is not in a chat): if `$ARGUMENTS` names
  an existing `doc/chat/*.md` thread, use that; otherwise list the threads and
  ask the user which one to summarise (`AskUserQuestion`).

## 2. Resolve the note name

- `note` = `$ARGUMENTS` if given, slugified the same way as `/chat:new`;
  otherwise the source chat's name.
- The note file is `doc/note/{note}.md`.
- If it already exists, ask the user whether to overwrite it or pick another
  name.

## 3. Read and summarise

`Read` the full `doc/chat/{chat}.md`, then:

```bash
mkdir -p doc/note
```

Write `doc/note/{note}.md`:

```
# Note: {note}

> Summarised from doc/chat/{chat}.md on {YYYY-MM-DD HH:MM}

## TL;DR

<2–4 sentences capturing what the conversation was about and where it landed>

## Key points

- <decisions, facts, answers and conclusions that matter>

## Open questions / next steps

- <anything left unresolved — omit this whole section if there is none>
```

Summarise the *substance* — decisions, answers, conclusions. Drop greetings,
tangents, and tool chatter. Keep it skimmable.

## 4. Confirm

Tell the user where the note landed, and that the chat thread is still
recording (run `/chat:exit` first next time if a clean cut is wanted).
