---
description: List Jira comments / descriptions that @-mention this agent's account.
allowed-tools: Read, Bash(python3:*)
---

# /kanban:mentions

Show all places the human @-mentioned the shared agent account since
the last sync. Mentions also surface automatically on `SessionStart`
via `/kanban:sync`; this command is the explicit "fetch now" path.

## 0. Pre-flight

- Confirm `kanban.json#backend.driver == "jira"`. Local mode has no
  mention concept — tell the user this is jira-only.
- Confirm `agentAccountId` exists in `backend.jira`. If not, the bot
  account is unconfigured — suggest `/kanban:initjira`.

## 1. Fetch

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py find-mentions \
  --kanban-path '<kanban.json path>' \
  [--since '<ISO timestamp>']
```

Returns:

```json
{
  "ok": true,
  "since": "<...>",
  "latestSeen": "<...>",
  "mentions": [
    {
      "key": "DMI-1099",
      "location": "comment",
      "commentId": "12345",
      "ts": "2026-04-30T10:00:00+08:00",
      "author": "Kirin",
      "authorAccountId": "5e393f5c...",
      "text": "@Agent Bot"
    },
    ...
  ]
}
```

## 2. Render

If `mentions` is empty:

```
✓ No new @-mentions since <since>.
```

Otherwise list one per line:

```
[mentions — N since <since>]
  DMI-1099  comment  by Kirin (3h ago):
    @Agent Bot 評估一下這個可行性 就開始動工
  DMI-1102  description  (just now):
    @Agent Bot
```

For each mention, fetch the surrounding comment / description so the
LLM can read intent — use `python3 .../jira_setup.py list-tasks ...` or
direct issue read via the existing helpers.

## 3. Decide what to do (LLM)

For each mention, the LLM should follow the `kanban-jira-agent` skill's
"When you're @-mentioned" section:

- Read the card (description + recent comments)
- Estimate workload
- Small (1–3h): `/kanban:next --task-id <KEY>` to claim, do the work,
  then `/kanban:reply <KEY> --to <authorAccountId> --body "..."`
- Large (>3h): `/kanban:create-sub <KEY> --title "..."` to spawn 2–5
  sub-cards, then claim them one at a time
- Uncertain: `/kanban:question <KEY> "<clarifying question>"`

## 4. Mark as read

After the LLM has surfaced + processed the mentions, advance the
acknowledgement timestamp so the next sync doesn't re-show them:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py mark-mentions-read \
  --kanban-path '<kanban.json path>' \
  --until '<latestSeen from step 1>'
```

If the user asked "show me mentions but don't mark them read" (rare —
they want to come back later), skip step 4.

## Absolute rules

- Read-only by default. Step 4 is a separate user-acknowledged write.
- Never auto-claim or auto-comment without LLM-side reasoning. The
  plugin only surfaces; the LLM decides. The skill's classification
  heuristic is the LLM's playbook, not the plugin's.
- Never reveal the bot's API token in any error surface.
