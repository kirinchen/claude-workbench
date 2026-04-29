---
name: kanban-jira-setup
description: Use this skill when the user runs /kanban:initjira, /kanban:reset-credentials, /kanban:register-ap, /kanban:assign-ap, or describes a Jira-mode setup or recovery problem (token rotation, admin permission gaps, MCP conflicts, migration from local mode). It walks the user through the multi-step flow and resolves the most common failure modes.
---

# Setting up & recovering kanban Jira mode

This skill is for the **owner** running `/kanban:*` setup commands, not
for the agents working day-to-day inside a Jira-mode project.

## The five-step path through `/kanban:initjira`

| Step | What | Common gotcha |
|---|---|---|
| 1 | Capture credentials (base URL, shared agent email, API token) and validate via `GET /myself` | Token comes from https://id.atlassian.com/manage-profile/security/api-tokens; it is account-scoped, not project-scoped |
| 2 | Parse the board URL into `projectKey + boardId`; validate both | The URL usually contains `/jira/software/projects/<KEY>/boards/<ID>`; `?selectedIssue=...` URLs are not board URLs |
| 3 | Pull the project workflow statuses; map to canonical `TODO/DOING/BLOCKED/REVIEW/DONE/CANCELLED` | Many out-of-the-box Jira workflows have only 3 statuses; you can either add the missing ones in Jira project settings, or accept partial mode with `--partial` |
| 4 | Choose `[a] use existing custom field` or `[b] create new (Claude Agent)` | Option `[b]` requires Jira admin; if the helper returns a 403, switch to `[a]` and ask an admin to create the field once |
| 5 | Register the first AP and set this repo's AP | AP names match `^[a-z][a-z0-9-]{2,40}$`; the registry is a Jira custom-field options list, mirrored in `kanban.json` |

After Step 5, a migration prompt fires if local tasks are present.

## Workflow gap (Step 3): how to add missing statuses in Jira

If `/kanban:initjira` reports missing statuses, the user has two choices:

1. **Add the canonical statuses in Jira**:
   - Go to `Project settings → Workflows`
   - Edit the active workflow
   - Add `Blocked`, `In Review`, `Cancelled` (whichever are missing)
   - Re-run `/kanban:initjira`; Step 3 should now report `✓ all 6 found`

2. **Accept the partial mapping with `--partial`**:
   - Re-run `/kanban:initjira --partial`
   - Missing canonical columns are substituted via labels:
     `kanban:blocked`, `kanban:review`, `kanban:cancelled`
   - The driver reads back labels into the canonical column. Audit comments
     are still posted on every transition.
   - Trade-off: cards in `BLOCKED/REVIEW/CANCELLED` show the underlying
     status (e.g. In Progress) plus a label — Jira board UI reflects this
     differently from native statuses.

## Permission gap (Step 4): no admin to create the field

If `[b] create new field` returns `permission denied`:

1. Ask a Jira admin to create a single-select custom field once
   (suggested name: `Claude Agent`, description optional).
2. Have the admin add the field to the project's default screen so it is
   editable.
3. Re-run `/kanban:initjira` and choose `[a] Use existing field`. The
   helper's `find-ap-field` lists fields whose name contains `agent`,
   `claude`, or `ap`.

## Migration from local mode

When `/kanban:initjira` finds existing `kanban.json#tasks`, it offers to
import them as Jira issues:

- TODO / DOING are imported by default; DONE / CANCELLED are skipped
  (override with `--include-done` if the user wants a complete history).
- Each imported issue gets the label `migrated-from-local`.
- The mapping `local-task-id → jira-key` is recorded in
  `.claude/.migration-map.json` so re-running is idempotent.
- The original `kanban.json#tasks` array stays in place — kanban.json with
  `backend.driver = "jira"` ignores it on read, so nothing breaks. Rolling
  back is `set backend.driver = "local"` (manually) and the local tasks
  re-appear.

Reverse migration (jira → local) is **not supported** in v0.2 — the user
must scaffold a fresh repo with `/kanban:init` if they need offline.

## Token rotation

Run `/kanban:reset-credentials` when:
- The token expired or was revoked
- The agent account password changed (token still works, but rotate as a
  hygiene measure)
- The token was exposed (committed, logged, screen-shared)

This command rewrites only the `JIRA_*` lines in `~/.claude-workbench/.env`,
leaving Pushover and other plugins untouched.

## MCP conflict warning

`/kanban:initjira` (final step) and `/kanban:whoami` both surface any
`atlassian|jira|rovo|mcp-atlassian` MCP servers configured at user-,
project-, or `.mcp.json` scope. If the user wants to keep the conflicting
MCP for personal Confluence browsing:

- Move the entry to **user scope** (`~/.claude/settings.json`) so agents in
  this repo do not inherit it.
- The `kanban-jira-agent` skill instructs agents not to call other Jira
  MCPs, but defense in depth is preferred.

If the user wants to remove the MCP entirely, edit the relevant settings
file and delete the entry; the next `/kanban:whoami` confirms.

## Diagnostic commands

| Symptom | Run |
|---|---|
| Token validity unknown | `/kanban:whoami` (Token row) |
| AP mismatch on a card | `/kanban:status` to see live state; verify `.claude/kanban-agent.json` |
| Stuck card / cache stale | `/kanban:sync` to force a refresh |
| Onboarding a new agent in this repo | `/kanban:assign-ap <existing-name>` (no need to re-init) |
| Adding a new agent across the team | `/kanban:register-ap <new-name>` then `/kanban:assign-ap` in each repo |

## Reference: SPEC sections

- §3 — data model (driver abstraction, kanban.json layout, secrets)
- §4 — slash commands
- §7 — graceful degradation (full vs partial workflow)
- §8 — anti-self-approve enforcement layers
- §11 — migration from local mode
- §18 — MCP conflict policy
