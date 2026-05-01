---
description: Post a reply comment on a Jira card, optionally @-mentioning the recipient.
argument-hint: <KEY> --to <accountId> --body "<text>"
allowed-tools: Read, Bash(python3:*)
---

# /kanban:reply

Post a comment on a Jira card. When `--to <accountId>` is given, the
comment includes a Jira-native @-mention so the recipient gets a real
notification (rather than just a comment buried in the card history).

Used most often in the @-mention reply flow:

> Human: `@AgentBot 評估一下這個可行性 就開始動工`
> Bot:    (does work) → `/kanban:reply DMI-1099 --to 5e393f5c... --body "..."` → @Kirin sees the reply in their Jira inbox

The `accountId` of the original commenter comes from
`/kanban:mentions` output (`authorAccountId` field). LLM should NEVER
invent an accountId — pull it from the surfaced mention metadata.

## 0. Pre-flight

- `kanban.json#backend.driver == "jira"`.
- Parse `$ARGUMENTS`:
  - `<KEY>` — Jira issue key (`^[A-Z][A-Z0-9_]+-\d+$`)
  - `--to <accountId>` — optional; when present, must be a real Jira
    accountId (24+ chars, hex-ish format). If the user gave a display
    name instead, look it up with the existing user-search infra (or
    decline and ask for the accountId).
  - `--body "<text>"` — required. Quoted strings supported.
  - `--display-name <name>` — optional override for the @-rendered
    text; defaults to "user" or whatever the helper has on file.

## 1. Run the helper

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py post-reply \
  --kanban-path '<kanban.json path>' \
  --key '<KEY>' \
  [--to-account-id '<accountId>'] \
  [--display-name '<name>'] \
  --body '<text>'
```

| Response | Action |
|---|---|
| `{ok: true, key, ts, mentioned}` | print `✓ replied to <KEY>; @<name> notified` |
| `{ok: false, error}` | surface verbatim |

## 2. Format guidance for the LLM

When replying to an @-mention from a human, the body should typically
include:

1. **Verdict** (1 sentence) — "feasible, small task" / "feasible but
   needs schema decision first" / etc.
2. **What you did** — claimed the card / spawned sub-cards / asked a
   clarifying question.
3. **Next blocker or ETA** — "expecting to finish in 2h" / "blocked on
   X / waiting for input on Y".

Keep it tight (<200 chars per paragraph). Long-form goes in the issue
description, not the comment.

## Absolute rules

- Never invent an `accountId`. If unknown, omit `--to-account-id` (the
  comment becomes a normal note without a notification).
- Never @-mention the bot account from itself (would self-trigger the
  detection on the next sync).
- Never bypass the agent-prefix grammar (SPEC §9) — `post-reply` writes
  through the same driver path as other comments, so the prefix is added
  automatically.
