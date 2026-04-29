---
description: Post a question to a Jira card and transition it to BLOCKED.
argument-hint: <KEY> "<question text>"
allowed-tools: Read, Bash(python3:*)
---

# /kanban:question

Arguments: `$ARGUMENTS`

Post a Q-kind comment (per SPEC §9 prefix grammar) to a Jira card and move
the card to `BLOCKED`. The agent stops working on the card until a human
answers; once answered, the card returns to TODO via human action in Jira UI.

Local mode does not have an equivalent — for local mode use `/kanban:block`
with a `--reason=<question>` instead.

## 0. Pre-flight

- Confirm `kanban.json#backend.driver == "jira"`. If not, tell the user this
  command is jira-only and suggest `/kanban:block` for local mode.
- Parse `$ARGUMENTS`:
  - First token must be a Jira KEY matching `^[A-Z][A-Z0-9_]+-\\d+$`. Reject
    if missing.
  - The remainder (quoted or not) is the question text. Strip surrounding
    quotes. Reject if empty.

## 1. Post the question

The driver writes a Q-kind comment with the SPEC §9 AP prefix
(`**[<ap>] [Q]**\\n\\n<text>`):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py transition \
  --kanban-path '<kanban.json path>' \
  --key '<KEY>' --to BLOCKED --reason '<question text>'
```

The driver's `transition(BLOCKED, reason=...)` posts a system comment with
the reason. We piggy-back on that for the question — it gets the same
audit trail with the AP attribution. (Future v0.3 may upgrade to a
distinct `--kind=Q` flag if the system-vs-question distinction matters in
practice.)

Parse the JSON response:

| Shape | Action |
|---|---|
| `{ok: true, key, column, raw_status}` | print `✓ <KEY> → Blocked. Question posted.` |
| `{ok: false, error}` | surface verbatim and stop |

## 2. Inform the user

```
✓ <KEY> "<title if known>" → Blocked.
  Question: "<question text>"

The card is paused until a human (or another agent) replies. You can keep
working on other tasks via /kanban:next.
```

## Absolute rules

- Do not bypass the helper to call Jira directly — the AP prefix and BLOCKED
  transition must be coupled.
- Do not silently invent the question text — it must come from the user.
- Do not mark the question as resolved yourself — the answer is human-side.
