# mentor — quickstart

*[繁體中文](./mentor_quickstart_zhtw.md)*

> The onboarding consultant your project never had. Mentor tells Claude (and any human contributor) *what to read first*, *what templates to fill*, *what order to work in*, and *where to record decisions*.

*See [`epic/mentor-plugin-spec.md`](./epic/mentor-plugin-spec.md) for full design, [`plugins/mentor/`](./plugins/mentor) for the code.*

Replaces the earlier `docsync` plugin — broader scope, framework-driven.

---

## 0. Prerequisites

- Claude Code installed and `claude login` done.
- `python3` available (used by hooks; pre-installed on macOS / Linux; ships with Git Bash on Windows).
- A project directory you want to bring under a working discipline.

**No shell rc changes are required.** Hook scripts and slash commands auto-prepend `~/.claude-workbench/bin` to PATH when they run. You only need to add it to your shell rc if you want to invoke `workbench-mentor` **manually from your terminal** (e.g. for debugging).

---

## 1. Pick the mode that fits your project

Mentor has two modes — pick one at `/mentor:init`:

| Mode | Good for | Doc hierarchy |
|---|---|---|
| **basic** | Personal projects, prototypes, tools, maintenance mode | `doc/SPEC.md` + tasks |
| **development** | Multi-feature, planning cycles, multi-agent collaboration | `SPEC + Wiki + Epic + Sprint + Issue` + tasks |

Don't overthink it — basic is deliberately minimal. Upgrade to `development` later (`/mentor:init --reset`) when planning pressure shows up.

---

## 2. Install the plugin

Inside Claude Code (any project):
```
> /plugin marketplace add kirinchen/claude-workbench
> /plugin install mentor@claude-workbench
```

---

## 3. Run init

```
> /mentor:init
```

What it does — interactive, **never overwrites** existing files:
1. **Scans** your project: type (Rust monorepo / JS / Python / Go), existing docs, sibling plugins (kanban / memory / notify), and any leftover `.claude/docsync.yaml`.
2. **Asks** which mode (basic vs development). Single question if unambiguous.
3. **Previews** the structure to be created — concrete file list with `+` (new), `=` (kept), `-` (skipped).
4. **Asks** about sibling integrations one yes/no at a time (only for plugins it actually detected).
5. **(development only)** Asks whether to create your first sprint with ID `SPRINT-{year}-W{ISO-week}`.
6. **Writes**: `.claude/mentor.yaml` + framework directories from the chosen template, runs `install-cli.sh`, then `workbench-mentor --health` to confirm.
7. Asks whether to commit (`chore: adopt mentor framework`).

To start over: `/mentor:init --reset`. Or skip the mode question with `/mentor:init --mode=basic` (or `--mode=development`).

If you have a docsync config from before: `/mentor:migrate-from-docsync` translates `.claude/docsync.yaml` → `.claude/mentor.yaml` (backs up the old file, never deletes).

---

## 4. Verify

Inside Claude:
```
> /mentor:status          # current mode + active sprint + open issues
> /mentor:review          # compliance check — missing docs, frontmatter drift, orphan issues
```

Outside Claude (**only** if you added `~/.claude-workbench/bin` to your shell rc's PATH):
```bash
workbench-mentor --health
#  -> exit 0, prints "mentor: ok" when .claude/mentor.yaml is loadable
workbench-mentor active-sprint --format json
workbench-mentor trace task-042 --format json       # task → issue → epic
workbench-mentor review --format json               # exit 0 clean, 2 on violations
```

---

## 5. Day-to-day flow

### Basic mode

Just two layers: `doc/SPEC.md` (the truth) + tasks (kanban.json or `doc/task.md`).

```
> /kanban:next            # if kanban installed — pick a TODO and start
> /mentor:status          # see compliance + task overview
```

Don't introduce Epic / Sprint / Issue concepts in basic mode — that's why you picked basic. If planning pressure grows, switch to development.

### Development mode

Full hierarchy plus task-pickup discipline. The flow inside a session:

1. **SessionStart hook** surfaces `bootstrap_docs` + the active Sprint pointer as `additionalContext`. Read those before your first code change.
2. **Pick a task** → trace it: `workbench-mentor trace <task-id>` shows `task → issue → epic`. Read the Issue's Acceptance Criteria, verify the task fits the Epic's Success Criteria, then start.
3. **Make the change.**
4. **PreToolUse hook** warns (does not block) if you're editing an Epic/Sprint/Issue/ADR doc with missing frontmatter.
5. **Stop hook** at session end: prints a compliance summary; if memory is installed and you've moved an ADR to `accepted` or finished a Sprint, persists those into memory.

Create new structured docs:
```
> /mentor:new epic   --title="User authentication system"
> /mentor:new issue  --title="Rate limit on login" --epic=EPIC-001
> /mentor:new adr    --title="Postgres for session store"
> /mentor:new sprint                                  # ID auto-set to current ISO week
```

`/mentor:new` is **the** way to create framework docs — hand-rolled docs without frontmatter will be flagged by `/mentor:review`.

---

## 6. What goes where

| Situation | Document type |
|---|---|
| New major direction or feature-set | **Epic** — the *why* |
| Concrete problem / bug / request | **Issue** — the *what* + Acceptance Criteria |
| Technical decision worth recording | **ADR** in `doc/Wiki/architecture-decisions/` — context + decision |
| Background knowledge / how-to | **Wiki** page — hand-written in `doc/Wiki/` |
| Unit of work to execute | **kanban task** (`/kanban:*`) — not a mentor doc |

Wrong choices to avoid:
- Don't create an Epic for a bug fix (use Issue).
- Don't write *implementation* in an Epic — that's Issue territory.
- Don't write *strategy* in an Issue — that's Epic territory.
- Don't write `kanban.json` AND `doc/task.md` — pick one based on whether kanban is installed.

---

## 7. Sibling integration

All opt-in via `.claude/mentor.yaml` `integration.*.enabled` (default: `auto` — engages when the sibling's CLI is on PATH AND `--health` returns 0):

| Pair | Effect |
|---|---|
| `mentor × kanban` | New Issue can auto-create a kanban task; optional DONE gate on Issue Acceptance Criteria |
| `mentor × memory` | Sprint retros + accepted ADRs persisted to memory |
| `mentor × notify` | Sprint-end / Epic-done push notifications |

You don't invoke these directly — the hooks and `/mentor:*` commands handle the fan-out.

---

## 8. Tune the config

Edit `.claude/mentor.yaml`. Key knobs:

- `mode`: `basic` or `development`. To switch, prefer `/mentor:init --reset` (it scaffolds the new directories) over editing this by hand.
- `paths.*`: override if your project's docs live somewhere other than `doc/`.
- `agent_behavior.bootstrap_docs`: list of docs the SessionStart hook surfaces. Add anything Claude must read at session start (e.g. `CONVENTIONS.md`, `ARCHITECTURE.md`).
- `agent_behavior.require_issue_context`: development mode default `true` — pickup workflow demands tracing to an Issue before starting.
- `integration.kanban.block_done_if_issue_incomplete`: opt-in DONE gate. Off by default (so existing kanban flows aren't disrupted).
- `integration.memory.save_sprint_retro` / `save_adr`: persist these into memory when the Stop hook runs.

After editing, re-check with `workbench-mentor --health` and `workbench-mentor review --format text`. **No restart needed** — config is re-read every call.

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/mentor:status` says "not configured" | `.claude/mentor.yaml` missing | Run `/mentor:init` |
| `/mentor:new epic` rejected with "basic mode" | Epic/Sprint/Issue/ADR only exist in development mode | `/mentor:init --reset` and pick `development` |
| `workbench-mentor: command not found` **only when running from your terminal** | `~/.claude-workbench/bin` not on your shell PATH | Expected — slash commands and hooks don't need this. Add `export PATH="$HOME/.claude-workbench/bin:$PATH"` to `~/.bashrc` only for terminal use |
| `workbench-mentor --health` exit 1: "no config" | `.claude/mentor.yaml` not in this project | Run `/mentor:init`, or `cd` to the right project root |
| `/mentor:review` reports `no_frontmatter` on a doc you wrote by hand | You skipped `/mentor:new`, the doc has no YAML block | Add the required frontmatter — see `frameworks/development/templates/<type>/<type>-template.md` for the shape |
| `/mentor:review` reports `orphan_issue` | Issue's `epic:` field points to an Epic that doesn't exist | Either create the missing Epic (`/mentor:new epic`) or fix the Issue's `epic:` field |
| `/mentor:review` reports `drift` | Doc has frontmatter but missing required fields (e.g. `id`, `status`, `date`) | Add the missing field; required fields per type are enforced in `mentor-guard.py` |
| Bootstrap docs not surfaced at SessionStart | Hook silently failed (Python error, missing config) | Check `claude --debug` output; verify `python3` is on PATH |
| Mentor seems to "forget" the active sprint | Sprint's `status:` is not `active`, or Sprint's `end:` is in the past | Open the Sprint doc, fix `status:` or `end:`; mentor only surfaces Sprints that match `status: active` AND `end >= today` |

`workbench-mentor review --format json` is the structured output if you want to script around violations.

---

## 10. Uninstall

```
> /plugin uninstall mentor@claude-workbench
```

This removes the plugin but leaves:
- `.claude/mentor.yaml` (your config — usually want to keep).
- `doc/SPEC.md`, `doc/Epic/`, `doc/Sprint/`, `doc/Issue/`, `doc/Wiki/` (your actual content — definitely want to keep).
- `~/.claude-workbench/bin/workbench-mentor` (symlink — now dangling).

To fully clean (only do this if you want to abandon the framework discipline):
```bash
rm -f ~/.claude-workbench/bin/workbench-mentor
rm .claude/mentor.yaml
# Your doc/ tree is yours — keep or delete deliberately.
```

---

## 11. Next steps

- Add `kanban` (if you haven't): [`kanban_quickstart.md`](./kanban_quickstart.md). When both are installed, mentor's Issue lifecycle and kanban's task state can sync.
- Add `notify`: [`notify_quickstart.md`](./notify_quickstart.md). Sprint-end and Epic-done can push to your phone.
- Read [`epic/mentor-plugin-spec.md`](./epic/mentor-plugin-spec.md) for the full design — including the rationale behind the two-mode split and the integration matrix.
- Read [`plugins/mentor/skills/mentor-workflow/SKILL.md`](./plugins/mentor/skills/mentor-workflow/SKILL.md) to see exactly what behaviour mentor injects into Claude.
