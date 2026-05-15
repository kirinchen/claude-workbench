---
description: Add or remove labels on a Jira card without changing its status.
argument-hint: <KEY> [--add L1 [--add L2 …]] [--remove L1 [--remove L2 …]] [--override-ap]
allowed-tools: Read, Bash(python3:*)
---

# /kanban:label

Add or remove labels on a Jira card as a stand-alone operation
(separate from a status transition). Each `--add` and `--remove` is
repeatable; you can mix both in one invocation.

Use cases:
- Marking a card `kanban:cancelled` or `wontfix` without forcing a
  status change.
- Tagging a card `agent-touched` for a custom JQL filter the team
  maintains.
- Removing a stale label after the condition no longer applies.

If `backend.jira.labels.allowed` is configured in `kanban.json`, every
`--add` is checked against the allowlist and rejected when not on it.
Removal is never gated by the allowlist — removing a stale label is
always safe.

## 0. Pre-flight

- `kanban.json#backend.driver == "jira"`.
- Parse `$ARGUMENTS`:
  - `<KEY>` — Jira issue key.
  - `--add <label>` — repeatable; at least one of `--add` or `--remove`
    is required (one invocation can do both).
  - `--remove <label>` — repeatable.
  - `--override-ap` — acknowledge AP-mismatch warning. Surfaced but
    non-blocking.

## 1. Run the helper

The CLI surface is two subcommands (one each for add / remove). When
the user passes both, run them sequentially:

```bash
# --add L1 [--add L2 ...]
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py add-label \
  --kanban-path '<kanban.json path>' \
  --key '<KEY>' \
  --label '<L1>' [--label '<L2>' ...]

# --remove L1 [--remove L2 ...]
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py remove-label \
  --kanban-path '<kanban.json path>' \
  --key '<KEY>' \
  --label '<L1>' [--label '<L2>' ...]
```

Response (each call):

```json
{
  "ok": true,
  "key": "BZK-646",
  "labels": ["kanban:cancelled", "agent-touched"],
  "warnings": []
}
```

Allowlist rejection:

```json
{"ok": false, "error": "labels [\"foo\"] are not in backend.jira.labels.allowed (...)", "kind": "label-not-allowed"}
```

When the allowlist rejects, surface the error verbatim. Don't retry
with a guessed label — ask the user to either pick from the allowlist
or extend it.

## 2. Render

```
✓ BZK-646 labels: kanban:cancelled, agent-touched
```

When both add and remove happen, render the final label list from the
second call's response (already merged).

## Absolute rules

- Don't add labels that conflict with the kanban plugin's own
  controlled set (`kanban_awaiting_approval`, `kanban_needs_decision`,
  etc.) by hand — those are managed by `/kanban:transition` and a
  manual add desyncs the card. Use `/kanban:transition` instead.
- Don't use label edits as a status-change shortcut. If the intent is
  to move the card, use `/kanban:transition`; if it's metadata, use
  this command.
- Never bulk-label across many cards in a loop without the user
  asking. One key per invocation, one user-driven intent per session.
