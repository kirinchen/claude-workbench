# kanban — quickstart

*[繁體中文](./kanban_quickstart_zhtw.md)*

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
- `APPROVED` is terminal — never edited, never moved back.
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

## 8a. Jira mode (kanban v0.2+)

The default driver writes to `kanban.json`. For multi-machine teams or
non-developer owners, switch to **Jira mode** instead. Same slash command
surface, different storage layer.

```
> /kanban:initjira
```

Five interactive steps: credentials → board URL → workflow check → AP
custom field → first AP registration. Tokens are stored in
`~/.claude-workbench/.env` (the same file `notify` uses). The flow is
idempotent and resumable — re-running picks up where the last one stopped.

After init:

```
> /kanban:status     # live state from Jira
> /kanban:doing      # work the cards already in DOING (owner curates TODO → DOING; agent executes)
> /kanban:done       # transition DOING → In Review (a human approves to Done)
> /kanban:question AGENT-42 "should v1 stay backward-compatible?"
> /kanban:whoami     # show driver, AP, token validity, MCP scan
```

Per-repo agent identity lives in `.claude/kanban-agent.json` (commit it —
the team should see which agent owns the repo). Anti-self-approve refuses
APPROVED transitions on a card whose AP equals this repo's AP.

If the workflow lacks canonical statuses (`BLOCKED`, `REVIEW`, `CANCELLED`),
re-run with `--partial` to accept label substitutes (`kanban:blocked`, etc.).

See [`epic/kanban_plugin_ Jira_backend_driver_UPDATE.md`](./epic/) for the
full v0.2 design.

---

## 8b. Multi-machine / multi-repo setup (kanban v0.3.27+)

The biggest source of friction is "I set this up on machine A — does
machine B / repo B / teammate C have to redo all five steps?"

Setup splits into three layers, each with a different lifecycle:

| Layer | Where it lives | When you redo it |
|---|---|---|
| **Per-board** (shareable) | Jira project property `kanban-config` (transitions, AP custom-field id, board metadata, `conventions` notes) | **Once**, by an admin via `/kanban:push-board-config`. Receivers pull automatically on `/kanban:sync` (8h TTL) or via `/kanban:pull-board-config`. |
| **Per-machine** | Jira credentials in `~/.claude-workbench/.env` (base URL, agent email, API token) | Once per machine. All repos on that machine share. |
| **Per-repo** | This repo's AP in `.claude/kanban-agent.json` | Once per repo. Each repo picks its own AP from the live Jira options list. |

### Cheatsheet

| Scenario | What you run on the new side |
|---|---|
| **All-new machine + all-new repo (board already configured)** | `/kanban:init` → `/kanban:initjira` (auto-detects existing `kanban-config`, pulls it, skips DSL/AP-discovery, only asks for credentials + AP assignment) |
| **All-new machine + first repo on a fresh board** | `/kanban:init` → `/kanban:initjira` (5-step interactive: credentials → board URL → DSL → AP field → AP assignment) → `/kanban:push-board-config` to publish for future joiners (admin role required) |
| **Same machine, new repo** | `/kanban:init` → `/kanban:initjira` (credentials auto-skipped; auto-detects board config + skips DSL/AP-discovery; only AP assignment is interactive) |
| **Same repo, different machine** | `git pull` → `/kanban:reset-credentials`. The committed `kanban.json` carries the cached `backend.jira` block, and `/kanban:sync` will refresh from Jira on next session anyway. |
| **Existing repo already in Jira mode on this machine** | Nothing — already set up. `/kanban:whoami` to verify (cache-age row tells you when it last synced). |

### How it works

The team's canonical config lives on the Jira project itself, under
property key `kanban-config`. Admins push it once; everyone else's
local `kanban.json` is a per-machine cache that auto-refreshes every
8 hours via the passive sync inside `/kanban:sync`.

**Admin (publisher):**
```
> /kanban:push-board-config
✓ Pushed 6 fields to Jira project AGENT properties.kanban-config
```

**Anyone else (receiver):**
```
> /kanban:init                # scaffold kanban.json (local mode)
> /kanban:initjira            # auto-detects board config, pulls,
                              #   asks for credentials + AP assignment
> /kanban:doing               # ready to work
```

Or, on an already-Jira-mode repo whose cache is stale:
```
> /kanban:sync                # passive sync if cache > 8h
```

Or to force a refresh now:
```
> /kanban:pull-board-config
```

> **Why publishing once works for everyone**: when conventions, transitions,
> or any team-wide setting changes, the admin re-runs
> `/kanban:push-board-config` on their repo. Within 8 hours every
> teammate's next `/kanban:sync` automatically pulls the new version,
> the conventions ack-hash forces a re-acknowledgement if notes
> changed, and per-machine fields (`agentAccountId`, `ap.registered`)
> stay untouched. No paste flow, no drift.

> **Permissions**: pushing requires Jira project-admin role on the
> agent's account. Pulls only need normal project access. If a non-
> admin runs `/kanban:push-board-config`, the helper returns a clear
> permission-error pointing at the role grant.

Migration from earlier (≤ 0.3.26) plugin versions that used the
`/kanban:showjira-code` paste flow: have a project-admin run
`/kanban:push-board-config` once on the source repo. Done — every
other repo / machine pulls automatically next session.

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
