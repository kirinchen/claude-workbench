# Dependency Rules

## `depends` semantics

`task.depends` is a list of `task-id` strings. Semantics: **"do not move this task to DOING until every dependency has `column == DONE`"**.

- `depends` may be empty (`[]`) or omitted.
- Dependencies on `BLOCKED` or `DOING` tasks do NOT count as satisfied.
- Dependencies on non-existent ids are an error — fix before proceeding.

## Validation

When writing kanban.json:

1. Every id in `depends` must exist in `tasks[]`.
2. The dependency graph must be a DAG (no cycles). If you detect a cycle, refuse to write and report the cycle path.
3. Self-dependency (`task-042 depends on task-042`) is forbidden.

Cycle detection: do a DFS from each task; if you revisit a node in the current path stack, it's a cycle.

## Resolution strategy

When `/kanban:next` is invoked:

1. Compute the "ready set" = TODO tasks whose deps are all DONE.
2. If ready set is empty but TODO is not:
   - Report which TODO tasks are blocked by which deps.
   - Suggest: unblock a BLOCKED task, complete a DOING task, or create a missing prerequisite.
3. Never auto-start a dependency that is itself TODO — ask the user first.

## Showing dependency context

When starting a task that has deps, briefly surface what satisfied them so the user can verify:

> task-042 starting. Deps satisfied: task-038 (DONE 2026-04-19), task-040 (DONE 2026-04-20).

This catches the edge case where a DONE task was completed by an unexpected branch/person.

## Adding new deps to an in-flight task

Allowed only if the new dep is itself already DONE. If the user wants to add an unmet dep to a DOING task, move the DOING task to BLOCKED with `blocked_reason: "waiting on task-XYZ"` instead.
