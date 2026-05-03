---
description: DEPRECATED alias — use /kanban:import-jira-code (#34).
allowed-tools: Read, Bash(python3:*), Bash(test:*), Bash(ls:*), Bash(git:*), AskUserQuestion
---

# /kanban:initjira-by-code  *(deprecated alias)*

Renamed in kanban@0.3.16 (#34): the helper subcommand has always been
`import-jira-code`, the slash command should match. Also, the command
already supported re-import on a configured repo — the new name makes
that obvious instead of hiding it behind "init".

**Use `/kanban:import-jira-code` instead.** This alias forwards to the
same flow for one release cycle, then will be removed.

## Action

1. Print the deprecation notice:

   ```
   /kanban:initjira-by-code is deprecated as of kanban@0.3.16 (#34).
   Use /kanban:import-jira-code — same flow, clearer name, supports
   both first-run bootstrap and re-sync. This alias will be removed
   in a future release.
   ```

2. Then follow the flow at `/kanban:import-jira-code` exactly. Do not
   re-implement the steps here — read the body of `import-jira-code.md`
   in this same `commands/` directory and execute it.
