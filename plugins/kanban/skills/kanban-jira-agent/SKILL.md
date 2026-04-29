---
name: kanban-jira-agent
description: Use this skill whenever kanban.json at the project root has backend.driver = "jira", or when the agent is about to claim, comment on, transition, or hand off a Jira card managed by this kanban plugin. Triggers also when the user mentions a Jira KEY-N reference (e.g. AGENT-42), a Jira board URL, or asks to pick the next task in a Jira-mode project.
---

# Working with kanban (Jira mode)

You are working in a project where kanban tasks live in Jira, not in
`kanban.json`. Your AP (Agent Property) is recorded in
`./.claude/kanban-agent.json`. Always operate through `/kanban:*` slash
commands — never call the Jira REST API directly, and never use any other
Jira MCP server even if one is available in your environment.

## Session start

`/kanban:sync` runs automatically on `SessionStart`. Read the printed
summary; cards listed are yours. If you suspect stale state, run
`/kanban:sync` again explicitly.

## Picking work

- `/kanban:next` — claims the highest-priority TODO card scoped to your AP,
  transitions it to In Progress, and posts a `[<ap>] [S] claimed` system
  comment. Do this **before** starting any work.
- Do not claim a card already DOING by another AP — the precheck hook
  warns you when you mention such a card.

## During work

- Found a blocker that needs human input? `/kanban:question <KEY> "<text>"`.
  This posts a Q-prefixed comment **and** moves the card to Blocked. Do not
  edit the card further until a human (or another AP) replies.
- Card-key auto-detection: if you mention a key (e.g. `AGENT-42`) or paste a
  Jira URL, the plugin injects context above your prompt. Read it before
  acting; pay close attention to ⚠ warnings about AP mismatch.

## Finishing work

- `/kanban:done` transitions DOING → In Review with a system comment. The
  human reviewer (or another AP) approves the card by transitioning it to
  Done in the Jira UI.
- DO NOT push your own card to Done. The plugin refuses (anti-self-approve);
  the Jira workflow may also reject it. This is intentional.

## Forbidden

- Direct Jira API calls (curl, fetch, any HTTP client)
- Atlassian Rovo MCP, mcp-atlassian, jira-mcp, or any other Jira MCP — your
  plugin is the only sanctioned path
- Editing `kanban.json` directly (the `kanban-guard.sh` PreToolUse hook
  blocks this anyway)
- Approving your own cards (the plugin will refuse; do not retry with
  workarounds)
- Bypassing PreToolUse hooks via `--no-verify`-style flags

## When to fall back

- If the Jira API is unreachable: `/kanban:status` should report a network
  error in its Token row. Do not proceed with state-changing commands until
  the user confirms connectivity.
- If your AP becomes invalid (registered list changed, Jira admin removed
  the option): `/kanban:whoami` shows the mismatch. Stop and ask the user.

## Reference: SPEC sections

- §3.4 — agent identity (`.claude/kanban-agent.json`)
- §5 — auto-detect rules (precheck on UserPromptSubmit)
- §8 — anti-self-approve invariant
- §9 — comment prefix grammar
- §18 — why no other Jira MCP is allowed
