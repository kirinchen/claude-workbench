# Related projects

*[繁體中文](./RELATED_zhtw.md)*

> **Looking for...**
> - A GUI to manage Claude Code installs and MCP servers? → [Norman-else/claude-workbench](https://github.com/Norman-else/claude-workbench) (different project, name collision is incidental)
> - Session-level productivity metrics + CLAUDE.md auto-improvement? → [blackwell-systems/claudewatch](https://github.com/blackwell-systems/claudewatch)
> - 70+ domain-specific Claude Code skills? → [wshobson/agents](https://github.com/wshobson/agents)
> - tmux + cron framework for long-running agents? → [mikeypotter/claude-agent-os](https://github.com/mikeypotter/claude-agent-os)
> - Role-based subagent definitions (analyst, architect, ...)? → [valllabh/claude-agents](https://github.com/valllabh/claude-agents) · [iannuttall/claude-agents](https://github.com/iannuttall/claude-agents)
>
> **None of the above? Stay here.** This repo is the **plugin family for session-spanning workflow infrastructure**: kanban state, push notifications, mentor onboarding, RAG memory.

## TL;DR

The Claude Code ecosystem already has plenty of tools, but most occupy categories *different* from claude-workbench. This page exists for two reasons:

1. **Save your time** — if you wanted one of the projects above, click through and don't read the rest of our docs.
2. **Be honest about positioning** — when people search "Claude Code workflow", "Claude Code AgentOps", or "Claude Code plugin", multiple projects show up. Here is how they differ.

## The five categories

| Category | Verbs | Example projects |
|---|---|---|
| **Skills / subagents** | "what Claude knows how to do" | wshobson/agents, valllabh/claude-agents, iannuttall/claude-agents |
| **Multi-agent runtimes** | "how Claude runs long" | mikeypotter/claude-agent-os |
| **Session analytics** | "how good was the past" | blackwell-systems/claudewatch |
| **GUI / launchers** | "how to configure Claude Code" | Norman-else/claude-workbench |
| **Workflow infrastructure** | "what state persists between sessions, how humans + Claude coordinate on it" | **claude-workbench (this repo)** |

The first four are fairly populated. The last one — **the plumbing that makes Claude Code feel like a real working environment instead of a sequence of one-shot sessions** — is where this repo lives.

## Comparison

### vs. [Norman-else/claude-workbench](https://github.com/Norman-else/claude-workbench)

**Their tool**: a desktop GUI for managing Claude Code installs, plugins, and MCP servers.
**This repo**: a plugin family that runs *inside* Claude Code.

The name overlap is incidental — different problem space, no functional collision. You could use Norman-else's GUI to install and toggle the plugins from this repo. We considered renaming to avoid confusion but kept the name because:
- functional overlap is zero,
- "workbench" describes our family-of-plugins shape better than alternatives,
- GitHub auto-redirects, but ecosystem references (existing Markdown, blog posts, search snippets) don't.

### vs. [blackwell-systems/claudewatch](https://github.com/blackwell-systems/claudewatch)

**Their tool**: scans past Claude Code sessions, computes productivity metrics, auto-generates CLAUDE.md improvements.
**This repo**: prescribes how Claude works during a session (mentor) and persists state between them (kanban, memory).

claudewatch operates **after** sessions; claude-workbench operates **before and during** sessions. Concrete complement:

- Use mentor + kanban to structure work.
- A month later, run claudewatch's `metrics` to see if the structure helped.
- claudewatch flags a SKILL.md that didn't move the friction needle.
- Edit the skill and measure again.

If you care about measuring the impact of your AI workflow, run both.

### vs. [wshobson/agents](https://github.com/wshobson/agents)

**Their pack**: 70+ domain-specific Claude Code plugins (testing, security, data, frontend, ...).
**This repo**: four general-purpose plugins (kanban, notify, mentor, memory) that don't know or care about your domain.

Different axis:
- wshobson's plugins are **vertical** — pick the ones for your stack.
- claude-workbench is **horizontal** — install once, applies to any work.

You can install both. Run a wshobson security skill *inside* a kanban-tracked task that mentor governs.

### vs. [mikeypotter/claude-agent-os](https://github.com/mikeypotter/claude-agent-os)

**Their framework**: tmux + cron orchestration for headless, multi-hour Claude runs.
**This repo**: doesn't try to keep agents alive — focuses on the *moments between* sessions (state, notifications, memory).

If you're running 8-hour agent sessions, claude-agent-os solves a problem we don't try to solve. Our `notify` plugin handles the "agent needs human input" boundary; their framework handles "agent runs uninterrupted for hours". Compatible.

### vs. [valllabh/claude-agents](https://github.com/valllabh/claude-agents) · [iannuttall/claude-agents](https://github.com/iannuttall/claude-agents)

**Their packs**: curated subagent definitions — role-based (analyst, architect, developer, ...) or personal collections.
**This repo**: doesn't define agents; defines **the workspace agents operate in**.

Subagent definitions are useful primitives; they don't address the "what happens between sessions" gap. Use either alongside this repo's `mentor` plugin to govern *how* those agents work.

## Where we are unique

claude-workbench is the only project I'm aware of that:

- Persists task state across sessions in a single source of truth (`kanban.json`) that both human and AI can edit.
- Pushes to your phone (Pushover today, ntfy/Slack soon) when the agent needs you, so you can leave headless sessions running.
- Codifies the framework hierarchy (Epic → Sprint → Issue → ADR) inside the plugin, not in your CLAUDE.md, with hooks that enforce structural compliance.
- Composes — kanban × notify × mentor × memory all check for each other and degrade gracefully when partial.

If you find another project doing this *as a unified surface*, open an issue and I'll add it here.

## A note for project maintainers listed above

If your project is on this list and you'd like the description rephrased, the comparison adjusted, or your project moved to a different category, please open an issue. The goal is to help users navigate, not to misrepresent.
