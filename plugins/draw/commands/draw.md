---
description: Open a local browser editor to draw a diagram (Mermaid / D2 / Excalidraw) — new, or one already in a file.
argument-hint: "[file — .md with diagram blocks, or .mmd / .excalidraw / .d2]"
allowed-tools: Bash(node:*)
---

# /draw

Arguments: `$ARGUMENTS`

- No argument → the page opens on the chart picker (Flowchart, State, ERD,
  Class, Sequence, Architecture, Mind map, D2, Excalidraw). After a chart is
  picked, the page asks how to keep it:
  - **one-off** — lives only in the draw server's memory; gone when it restarts
  - **save in the current directory** — needs a name
  - **save at a path** — relative to the current directory, absolute, or `~/…`

  and, for the two file options, whether to write a markdown fenced block
  (`.md`, the default) or a native single file (`.mmd` / `.excalidraw` / `.d2`).
- A file argument → open the diagram(s) in that file directly. A `.md` with
  several diagram blocks shows a picker; a `.md` with none offers to append one.

## Run

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/draw.mjs" open $ARGUMENTS --cwd "$PWD"
```

It starts the server if it is not already running (one per machine, bound to
`127.0.0.1`), opens the browser, and prints one JSON line:
`{"url", "opened", "port", "version", "d2"}`.

Requires Node 18+. Nothing else — the editor is pre-built inside the plugin.

## Report

Two or three lines, no more:

```
draw → <url>
<"opened in your browser" — or, if opened is false, "open this URL yourself">
<only if d2 is false:> D2 is greyed out — install https://d2lang.com to enable it.
```

If `opened` is false (SSH session, no desktop), the URL only works from this
machine; say so, and suggest `ssh -L <port>:127.0.0.1:<port>` for a remote
browser.

Then stop. Do not read the diagram yet — the user has not drawn it. When they
come back with "look at my diagram", follow the `draw` skill.
