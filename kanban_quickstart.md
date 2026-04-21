# kanban — quickstart

> Task state persistence for Claude Code. A single `kanban.json` at the project root is the shared work queue between you and Claude.

*See [`SPEC.md §3`](./SPEC.md) for full design, [`plugins/kanban/`](./plugins/kanban) for the code.*

---

## 0. Prerequisites

- Claude Code installed and `claude login` done.
- `git` available (kanban uses it for auto-commits; no remote required).
- Shell rc (`~/.bashrc` or `~/.zshrc`) contains — needed for sibling plugins:
  ```bash
  export PATH="$HOME/.claude-workbench/bin:$PATH"
  ```
- Project directory is a git repo (`git init` if needed).

---

## 1. Install

```bash
cd my-project
claude
```

Inside Claude Code:
```
> /plugin marketplace add kirinchen/claude-workbench
> /plugin install kanban@claude-workbench
```

No external services, no tokens. This is the cheapest plugin to try.

---

## 2. Initialise `kanban.json`

```
> /kanban:init --with-examples
```

Creates:
- `kanban.json` — the work queue (with 4 sample tasks so you can see the shape).
- `kanban.schema.json` — JSON Schema (for editor validation + the viewer).

Drop `--with-examples` if you want an empty board.

**What got installed under the hood**:
- `kanban-guard.sh` (PreToolUse) — blocks Claude from hand-editing `kanban.json`.
- `kanban-session-check.sh` (SessionStart) — surfaces DOING/BLOCKED at start of each session.
- `kanban-autocommit.sh` (PostToolUse) — commits kanban changes as standalone commits.

---

## 3. Add a task

You (the human) edit `kanban.json` directly to add new tasks. Claude **cannot** — the guard hook blocks direct edits. This is deliberate: state transitions go through slash commands, task creation goes through you.

Minimum fields for a new TODO task (append into `tasks[]`):
```jsonc
{
  "id": "task-005",
  "title": "Short imperative title",
  "column": "TODO",
  "priority": "P1",
  "category": "infra",
  "tags": ["backend"],
  "depends": [],
  "created": "2026-04-21T14:00:00+08:00",
  "updated": "2026-04-21T14:00:00+08:00",
  "started": null,
  "completed": null,
  "assignee": null,
  "description": "Longer markdown description.",
  "comments": [],
  "custom": {}
}
```

Bump `meta.updated_at` in the same edit. **Do NOT** commit yet if you'd rather batch with other changes — `kanban-autocommit.sh` only fires when `kanban.json` is the *only* dirty file.

Later: viewer (Textual TUI) is planned for v0.2 — you won't be editing JSON forever.

---

## 4. Day-to-day flow

Inside Claude Code:
```
> /kanban:status          # read-only overview of all columns
> /kanban:next            # pick top-priority ready TODO, move to DOING, begin
> /kanban:done            # close the current DOING task (optionally --note=...)
> /kanban:block <task-id> --reason="need API key from ops"
```

Rules the skill enforces (see `plugins/kanban/skills/kanban-workflow/SKILL.md`):
- A task with unresolved `depends` cannot move to DOING.
- `DONE` is terminal — never edited, never moved back.
- `BLOCKED` requires a non-empty `custom.blocked_reason`.

After `/kanban:next`, Claude just starts working on the task's `description`. You can interrupt at any time.

---

## 5. Auto-commits

When `kanban.json` is the only dirty file, the PostToolUse hook runs:
```
git add kanban.json && git commit -m "kanban: task-042 TODO→DOING"
```

This is **opt-out by mixing** — if you also have other dirty files, autocommit refuses, so you can stage them together manually. (Kanban transitions read better as standalone commits for history diffing.)

---

## 6. Headless automation (optional)

To let Claude work through the queue while you're away:
```
> /kanban:enable-automation
```
Choose **cron polling** (recommended, every 10 min by default). The command walks you through:
1. Installing `cron-runner.sh` into `~/.claude-workbench/bin/`.
2. Writing a tagged crontab line.
3. Logging to `~/.claude-workbench/logs/cron-runner.log`.

Uses your `claude login` — **no API credits consumed**. `flock` prevents overlap.

Remove later: `crontab -e` and delete the `# claude-workbench:` tagged line.

---

## 7. Verify everything works

```bash
# Inside Claude:
> /kanban:status          # should render the board
> /kanban:next            # should pick up a TODO

# Outside Claude:
git log --oneline | head -3      # should see "kanban: task-XXX TODO→DOING"
```

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "Direct edits to kanban.json are blocked" when you want Claude to write it | Guard hook fired — working as intended | Use `/kanban:next` / `/kanban:done` / `/kanban:block` instead |
| Autocommit didn't fire | Other files were also dirty | Either stage kanban.json alone, or commit manually |
| `/kanban:next` says "all blocked" | Every TODO has unresolved deps | Fix deps first, or unblock a BLOCKED task |
| SessionStart shows no DOING/BLOCKED summary | `kanban.json` missing or not at project root | Check you `cd`'d into the right dir before `claude` |
| Autocommit ran but commit message says "kanban: update" | transition detection fallback (python3 + jq both unavailable) | Install one of them |

---

## 9. Uninstall

Inside Claude:
```
> /plugin uninstall kanban@claude-workbench
```

`kanban.json` and `kanban.schema.json` remain in your project — the plugin leaves your data alone. Delete them manually if you want a clean slate.

If you enabled cron: `crontab -e` and remove the tagged line.

---

## 10. Next steps

- Add `notify`: [`notify_quickstart.md`](./notify_quickstart.md) — so Claude can push you a notification when `DOING → BLOCKED` fires.
- Add `docsync`: [`docsync_quickstart.md`](./docsync_quickstart.md) — so code changes stay linked to doc updates.
- Read [`SPEC.md §8`](./SPEC.md) to see how the three plugins interact when all installed.
