---
schema_version: 1
repo: your-repo-slug
display_name: Your Project
jira_base_url: https://your-org.atlassian.net/browse
repo_url: https://github.com/your-org/your-repo
owner: your-username
---

# Your Project — Feature Map

*Per-repo feature ledger consumed by the cross-repo tree-map viewer. Run `workbench-mentor review` (or `/mentor:review`) to validate; run `/mentor:renewtree` to regenerate this file as a reviewable diff.*

*Hard rules the validator enforces: bullet marker is `- ` only (no `*`, no `+`, no tabs); exactly 2 spaces per nesting level; status tokens (`` `@done` `` / `` `@wip` `` / `` `@todo` `` / `` `@blocked` ``) live on leaf bullets only — parents are derived; `(jira:KEY)` allowed on leaves only and must match `^[A-Z][A-Z0-9]+-[0-9]+$`; a child bullet whose text begins with `note:` is metadata for its parent, not a node; nothing follows the tree.*

- Module A
  - Feature A1 `@todo`
  - Feature A2 `@wip` (jira:PROJ-1)
    - note: replace this example with a real reminder about Feature A2
- Module B
  - Feature B1 `@todo`
