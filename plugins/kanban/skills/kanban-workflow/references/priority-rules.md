# Priority Rules

## Ordering

`meta.priorities` is the source of truth for priority order. Position `0` is highest. Default is `["P0","P1","P2","P3"]`:

- `P0` — drop everything, do this now
- `P1` — important, schedule next
- `P2` — normal
- `P3` — nice-to-have

Never hardcode these letters. Always read `meta.priorities` from the project's kanban.json in case the user customised them.

## Selecting the next TODO task

1. Build the candidate set: `tasks` where `column == "TODO"` and every id in `depends` is in `DONE`.
2. Apply filters the user passed (`--category`, `--priority`, tag filters).
3. Sort by:
   1. `priorityIndex` ascending (using `meta.priorities.indexOf(task.priority)`).
   2. `created` ascending.
   3. `id` ascending as final deterministic tiebreak.
4. If the top priority bucket has ≥ 2 candidates, show the top 3 and ask the user to pick.

## P0 semantics

If any `column == TODO` task has priority `P0`:

- Refuse to pick anything else until P0s are handled or explicitly deprioritised by the user.
- If you're already doing a non-P0 and a P0 appears, finish the current atomic step, report the P0, and ask whether to switch.

## Priority changes mid-flight

The user may reprioritise a DOING task. This is allowed. Do NOT move it back to TODO — update `priority`, update `updated`, leave the column alone.

## Escalation

If you detect that priorities in kanban.json contradict what the user just said verbally, trust the verbal input, update kanban.json via a slash command, and add a comment noting the change.
