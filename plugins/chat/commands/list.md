---
description: List saved chat threads under doc/chat/, newest first, marking the one recording in this session.
allowed-tools: Read, Bash(echo:*), Bash(ls:*), Bash(grep:*)
---

# /chat:list

Show the saved chat threads so the user can pick one to `/chat:resume` or
`/chat:note`.

## 1. Gather

```bash
echo "session=$CLAUDE_CODE_SESSION_ID"
ls -t doc/chat/*.md 2>/dev/null || echo "NO_THREADS"
```

- `NO_THREADS` (or no `doc/chat/` directory) → tell the user there are no chat
  threads yet, and that `/chat:new` starts one. Stop here.
- Otherwise the `ls -t` order is newest-first — that index is exactly what
  `/chat:resume <N>` uses.

`Read` `.claude/chat/sessions/{session id}.json` if it exists — its `file`
field is the thread currently recording in *this* session.

## 2. Describe each thread

For every `doc/chat/*.md`, read its `> Started …` header line for the start
time, and count `## ` turn headers for a rough size (`grep -c '^## ' <file>`).

## 3. Print the list

Newest first, as a compact table — index, name, started, turns, and a marker
on the thread recording in this session:

```
Chat threads (doc/chat/):

  #  thread             started            turns
  1  refactor-plan   ●  2026-05-20 14:30      12   ← recording now
  2  api-questions      2026-05-19 09:05      31
  3  chat-2026-05-18     2026-05-18 16:40       4

Resume:  /chat:resume <name | number | keyword>
Summary: /chat:note
```

Mark `← recording now` only on the thread matching this session's state file.
If no thread is active in this session, omit the marker and add a one-line note
that nothing is recording right now.
