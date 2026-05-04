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

## Working the DOING pool

- `/kanban:doing` — read every card already in DOING scoped to your AP,
  decide an execution order across them (deps, module affinity,
  priority as tiebreaker), then work them sequentially. Read-only —
  this command does NOT pull from TODO.
- **TODO → DOING is the owner's call.** If a card you want to work is
  still in TODO, ask the owner to move it (Jira UI or their own
  `/kanban:transition`); do not transition it yourself unless an
  explicit @-mention from the owner names that card with start intent
  (see "When you're @-mentioned" below).
- Do not work a DOING card owned by another AP — the precheck hook
  warns you when you mention such a card.

## Two flavors of REVIEW (#45)

When the team's `transitions.REVIEW` declares a `flavors` block, every
DOING → REVIEW transition must pick one. The two canonical flavors —
their exact names live in `backend.jira.transitions.REVIEW.flavors`,
but the conventional naming is:

- **`awaiting_approval`** — you finished the work. Card is ready for
  the human reviewer to glance, click APPROVED, and walk away. Use this
  via `/kanban:done` (which auto-passes the flavor) — most common path.
- **`needs_decision`** — you got stuck and posted N options in a
  comment. Card is waiting for the human to *make a choice*; they'll
  move it back to DOING (or somewhere else) once decided. Use
  `/kanban:transition <KEY> --to REVIEW --flavor needs_decision`
  directly after posting the options comment. NOT `/kanban:done`.

The two flavors carry different labels (e.g. `kanban_awaiting_approval`
vs `kanban_needs_decision`) so the human can JQL-filter or board-glance
to triage which kind of REVIEW each card needs. Picking wrong leaves
the wrong label on the card — fix with `/kanban:transition` again with
the correct flavor (label sets are PUT-overwriting, so the stale label
gets removed on the next transition).

Naming guidance for new label values your team adopts: prefer
underscore separators (`kanban_awaiting_approval`) over colon
(`kanban:awaiting`). The colon form visually parses as a slash-command
path and confuses operators. Existing built-in `kanban:blocked` /
`kanban:cancelled` keep the colon form for back-compat.

## During work

- Found a blocker that needs human input? `/kanban:question <KEY> "<text>"`.
  This posts a Q-prefixed comment **and** moves the card to Blocked. Do not
  edit the card further until a human (or another AP) replies.
- Card-key auto-detection: if you mention a key (e.g. `AGENT-42`) or paste a
  Jira URL, the plugin injects context above your prompt. Read it before
  acting; pay close attention to ⚠ warnings about AP mismatch.

## When you're @-mentioned by a human

`SessionStart` and `/kanban:sync` will surface mentions in this format:

```
[mentions — N since <timestamp>]
  DMI-1099  comment  by Kirin (3h ago):
    @Agent Bot 評估一下這個可行性 就開始動工
```

Treat each mention as a directive. Process:

1. **Read the card** — fetch `<KEY>` description + recent comments to
   understand context. Use `/kanban:status` or the precheck context that
   the auto-detect hook injects when you mention the key in your reply.

2. **Estimate workload** in your head:

   | Signal | Likely workload |
   |---|---|
   | Single concern, no architectural unknowns, ≤3 hr | **Small** |
   | Touches ≥2 components, design decisions needed, >3 hr | **Large** |
   | Scope unclear from the prose | **Ask first** |

3. **Act based on estimate**:

   - **Small** — the @-mention authorizes you to transition this card
     into DOING (the owner is the one asking):
     ```
     /kanban:transition <KEY> --to DOING    # owner-authorized TODO → DOING move
     /kanban:doing                          # read DOING and pick this card up
     # ... do the actual work ...
     /kanban:done <KEY>                     # transition to REVIEW
     /kanban:reply <KEY> --to <authorAccountId> --body "<verdict + status>"
     ```
   - **Large** — break down without transitioning the parent:
     ```
     /kanban:create-sub <KEY> --title "..." --title "..." --title "..."
     /kanban:reply <KEY> --to <authorAccountId> --body "Spawned <N> sub-cards: <list>"
     # owner reviews and moves the first sub-card to DOING; then:
     /kanban:doing
     ```
   - **Ask first** — don't claim anything yet:
     ```
     /kanban:question <KEY> "<clarifying question>"
     ```
     This posts a Q-prefix comment AND transitions the card to BLOCKED.
     Wait for the human's reply before proceeding.

4. **Always reply with @-mention** to the original commenter. The
   `authorAccountId` field in the surfaced mention metadata is what you
   pass to `/kanban:reply --to`. Never invent an accountId.

5. **Never** claim multiple cards in parallel within one session. Even
   when you spawn sub-cards, work them one at a time.

## Finishing work

- `/kanban:done` transitions DOING → In Review with a system comment. The
  human reviewer (or another AP) approves the card by transitioning it to
  Done in the Jira UI.
- DO NOT push your own card to Done. The plugin refuses (anti-self-approve);
  the Jira workflow may also reject it. This is intentional.

## Linking to repo docs

When a Jira comment references a file in this repo (mentor's Epic /
Sprint / Issue / ADR docs in particular, but also any source file the
human might want to read), **always resolve to a clickable GitHub URL
before posting**. Don't write `see epic/AGENT-001-foo.md` — Kirin
can't click that and has to navigate GitHub manually.

Resolve via:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/jira_setup.py resolve-doc-link \
  --kanban-path '<kanban.json>' \
  --doc-path 'epic/AGENT-001-foo.md'
```

Returns `{ok, url, exists, branch, host, ...}`. Use the `url` field
verbatim in the comment body.

Behaviour:

| Response | What to do |
|---|---|
| `{ok: true, url, exists: true}` | use the URL in your comment |
| `{ok: true, url, exists: false}` | use the URL anyway (file may be uncommitted); add a parenthetical "(uncommitted on `<branch>`)" so the reader knows |
| `{ok: false, host: "other", ...}` | non-GitHub origin (GitLab / Bitbucket). Fall back to the relative path and add a one-line explanation: "see `epic/AGENT-001-foo.md` (clickable link not supported on this repo's host)" |
| `{ok: false, error: "no git origin", ...}` | repo isn't cloned from a remote. Fall back to relative path; mention the constraint once. |

**Branch handling**: the helper defaults to the current git branch.
For comments destined to outlive a feature branch (e.g. on long-lived
parent cards), pass `--branch main` explicitly so the link still works
after the branch is deleted.

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

- §3.4 — agent identity (`.claude/kanban-agent.json`, also stores
  `lastMentionSeenAt` and `acknowledgedConventions`)
- §5 — auto-detect rules (precheck on UserPromptSubmit)
- §8 — anti-self-approve invariant
- §9 — comment prefix grammar
- §10 — team conventions (`/kanban:show-conventions`)
- §18 — why no other Jira MCP is allowed
