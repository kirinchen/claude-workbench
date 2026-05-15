---
description: Delete a Jira card. Destructive — refuses without --confirm; writes an audit snapshot first.
argument-hint: <KEY> --confirm [--cascade-subtasks] [--force]
allowed-tools: Read, Bash(python3:*)
---

# /kanban:delete

**Destructive.** Permanently delete a Jira card. The card and its Jira
changelog are gone after this; the only record left is the on-disk
audit snapshot written to `.claude/.kanban-cache/audit/<KEY>-<ts>.json`
**before** the DELETE call.

> Read this before invoking: this command is the one mutation that
> truly cannot be undone. Confirm intent with the user before running
> it, even though `--confirm` is required at the CLI layer.

Use cases:
- Garbage-collecting agent-spawned sub-cards that turned out to be
  wrong scope (the most common driver — see issue #55).
- Removing a duplicate card a teammate filed.
- Cleaning up a test card.

## 0. Pre-flight (do this before generating the command)

1. **Confirm with the user.** Even if they just asked to delete, echo
   back: card key + summary + status. Wait for an explicit yes.
2. **Don't delete recently-APPROVED cards.** The helper refuses by
   default if the card was approved within the last 7 days; if you
   need to override, pass `--force` and surface why in your message
   to the user.
3. **Prefer `/kanban:transition <KEY> --to CANCELLED`** when the goal
   is "this card shouldn't be worked on anymore but should remain in
   the history." Delete is for genuine erase-from-existence intent.

Parse `$ARGUMENTS`:
- `<KEY>` — Jira issue key.
- `--confirm` — REQUIRED. Without it the helper refuses.
- `--cascade-subtasks` — also delete sub-tasks linked to this card.
  Default leaves them orphaned (Jira's own default behavior).
- `--force` — override the recent-APPROVED guard.

## 1. Run the helper

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py delete-issue \
  --kanban-path '<kanban.json path>' \
  --key '<KEY>' \
  --confirm \
  [--cascade-subtasks] \
  [--force]
```

Response:

```json
{
  "ok": true,
  "key": "BZK-648",
  "audit_path": "/path/to/.claude/.kanban-cache/audit/BZK-648-20260515T143000Z.json",
  "cascade": false
}
```

Refusal modes:

| `kind` | meaning |
|---|---|
| `needs-confirm` | `--confirm` not passed |
| `recent-approved` | card APPROVED within 7d; pass `--force` to proceed |

## 2. Render

```
✓ Deleted BZK-648
  Audit: .claude/.kanban-cache/audit/BZK-648-<ts>.json
```

Surface the audit path so the user can grep it later — it's the only
trace of the card that remains.

## Absolute rules

- **Never delete without explicit user intent.** Don't proactively
  prune cards just because they look stale.
- **Never delete an APPROVED card without checking.** The recent-7d
  guard catches the bad case; for older approvals, still confirm with
  the user — APPROVED means the work shipped and someone may need
  the record.
- **Never `--cascade-subtasks` without explicit ask.** Cascading
  deletes can erase a whole tree of work.
- **Don't loop deletes across many keys.** One key per invocation,
  one explicit user confirmation each.
