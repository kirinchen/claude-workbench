---
name: kanban-workflow
description: Use this skill whenever kanban.json exists in the project root, or when the user mentions tasks, TODO, kanban, priorities, or asks "what should I work on next", "pick a task", "繼續工作", etc. This skill governs task lifecycle (TODO → DOING → DONE/BLOCKED) through the kanban.json file.
---

# Kanban Workflow

You operate on a `kanban.json` file at the project root. It is the **single source of truth** for tasks. Humans and AI agents both read/write it, so correctness and determinism matter.

## 0. Absolute Rules (do not violate)

1. **Never directly Edit or Write `kanban.json`**. Always go through a `/kanban:*` slash command. The `kanban-guard.sh` hook will block direct edits anyway, but don't try.
2. **Never modify a task in the `DONE` column.** DONE is append-only. If work needs to resume, create a new task that references the old id.
3. **Never skip `depends`.** A task cannot move to `DOING` if any of its `depends` are not `DONE`.
4. **Never bypass hooks** (`--no-verify`, disabling `kanban-guard.sh`, etc.).
5. **All timestamps are ISO 8601 with timezone.** Use the local timezone of the project; never emit naive times.

## 1. When to read kanban.json

- At session start (the `SessionStart` hook surfaces DOING tasks automatically — re-read if you need the full picture).
- Before picking a new task (`/kanban:next`).
- Before marking something done or blocked.
- When the user asks about status.

Use the `Read` tool. Never assume in-memory state is current — another session, the viewer, or a git pull may have changed it.

## 2. State Transition Rules

```
TODO ──► DOING ──► DONE
          │
          └──► BLOCKED ──► TODO
```

| From | To | Required side effects |
|---|---|---|
| TODO | DOING | set `started` = now; verify all `depends` are DONE |
| DOING | DONE | set `completed` = now |
| DOING | BLOCKED | `custom.blocked_reason` MUST be non-empty |
| BLOCKED | TODO | clear `custom.blocked_reason` |
| DONE | * | **forbidden** |

Every transition also updates `meta.updated_at` and the task's `updated`.

## 3. Picking a task (priority + dependency)

When asked for "next task", follow this order:

1. Filter to `column == "TODO"` **with all `depends` DONE**.
2. Apply user-supplied filters (e.g. `--category=trading`, `--priority=P1`).
3. Sort by `priority` ascending using `meta.priorities` order (so `P0` before `P1`).
4. Tie-break by `created` ascending (oldest first).
5. If multiple remain, **surface the top 3 to the user and let them pick** instead of guessing.

See `references/priority-rules.md` and `references/dependency-rules.md` for detailed logic.

## 4. Handling dependencies

- If the top candidate has unresolved `depends`, skip it — do NOT move a task to DOING that has non-DONE deps.
- If ALL TODO tasks have unresolved deps, say so explicitly and suggest either (a) unblocking a BLOCKED task, or (b) creating a new task.

## 5. Escalation / ambiguity

When you encounter ambiguity you cannot resolve from kanban.json alone:

- **Prefer a comment over a guess.** Append a comment to the task (`author: claude-code`, `ts: now`, `text: "<question>"`) and ask the user.
- **Prefer BLOCKED over stalling.** If you genuinely cannot proceed without input, move the task to BLOCKED with a clear `custom.blocked_reason`.
- **Never silently reinterpret the task.** If the title says X but the description implies Y, surface the conflict.

## 6. Concurrent safety

Multiple sessions may touch kanban.json. Minimise window of risk:

- Read → decide → write, back-to-back. Don't hold stale state across long tool calls.
- Before writing, re-read kanban.json to confirm the task is still in the column you expect. If not, stop and report.
- Use the `assignee` field to claim a task you're about to work on.

## 7. Commit hygiene

The `kanban-autocommit.sh` PostToolUse hook commits kanban.json automatically after Bash-driven changes. You do not need to commit kanban.json manually. Do NOT include kanban.json in commits that also contain code changes — keep kanban transitions as standalone commits.

## 8. References

- `references/schema-spec.md` — field meanings and validation rules.
- `references/priority-rules.md` — priority tie-breaking and filtering.
- `references/dependency-rules.md` — dependency resolution and DAG traversal.
