---
name: draw
description: Use when the user asks you to look at, review, give feedback on, or change a diagram they drew with /draw — or any ```mermaid / ```excalidraw / ```d2 block in a markdown file, a .mmd / .excalidraw / .d2 file, or a one-off drawing (mem:<id>). Also when they say "看一下我的圖", "幫我改圖", "my diagram", "the whiteboard".
---

# draw — reading and editing the user's diagrams

`/draw` opens a local browser editor. Whatever the user draws ends up in one
of three places, and you read / edit it **in place** — the same file the
browser edits:

| Where | What it looks like | How you read it | How you change it |
|---|---|---|---|
| Markdown block | a ```` ```mermaid ```` / ```` ```excalidraw ```` / ```` ```d2 ```` fence inside a `.md` | `summary <file.md>` | edit the fence content in the file |
| Native file | `foo.mmd`, `foo.excalidraw`, `foo.d2` | `summary <file>` | edit the file |
| One-off | `mem:<id>` (server memory only; gone on restart) | `summary mem:<id>` | `put mem:<id> <file>` |

```bash
D="node ${CLAUDE_PLUGIN_ROOT}/scripts/draw.mjs"
$D summary doc/plan.md          # every diagram in the file, summarised
$D summary doc/plan.md --index 1 # just the 2nd one
$D get doc/plan.md --index 1     # raw source
$D list                          # one-off drawings (mem:<id>)
```

If `${CLAUDE_PLUGIN_ROOT}` comes through empty, locate the script with
`ls -d ~/.claude/plugins/cache/*/draw/*/scripts/draw.mjs | tail -1`.

If you do not know which file the user means, ask, or look for recently
modified `.md` / `.excalidraw` / `.mmd` files in the working directory, and
run `list` for one-off drawings.

## Reading

- **Mermaid and D2** are text — the source *is* the diagram. Read it directly.
- **Excalidraw** is verbose JSON (coordinates, seeds, versions). Do not read the
  raw JSON when `summary` will do: it lists every shape with its label and
  position, every arrow as `from -> to : label` (by binding, or by which box the
  endpoint lands in), and free-floating text. Free text sitting inside a box is
  shown as that box's text — users often label a box that way instead of
  double-clicking it.

When giving feedback, name the nodes and connections you see ("`Login` → `API`
has no label; `DB` is not connected to anything") before suggesting changes, so
the user can tell you read the right diagram.

## Changing

- **Mermaid / D2 in markdown**: edit only the lines between the fences, keep the
  fence line itself. The browser's GUI editors understand a subset of each
  diagram type — keep to the same style the diagram already uses (one statement
  per line, the header line unchanged, e.g. `graph TD;`, `stateDiagram-v2`).
- **Excalidraw**: edit the JSON precisely — change a text element's `text` *and*
  `originalText`; to add an element, copy a sibling's full shape (every key) and
  give it a fresh `id`, a fresh `seed`, and `"version": 1`. Bound text needs
  `containerId` on the text and a matching `{"id", "type": "text"}` entry in the
  container's `boundElements`. Keep the JSON on one block; do not reformat the
  whole thing.
- **One-off**: write the new source to a temp file, then `put mem:<id> <file>`.

After you change a diagram, tell the user to press **重新載入** (or refresh) in
the browser. The page also notices on its own within ~2 seconds and shows a
"changed elsewhere" banner. If they had unsaved edits, saving from the browser
will refuse to overwrite your change (409) and ask them first — so tell them
you changed it *before* they save.

## Server

```bash
$D status   # running? port? d2 available?
$D stop     # stop it — one-off drawings are lost
```

One server per machine, bound to `127.0.0.1`, state in
`~/.claude-workbench/draw/server.json`, log in `server.log` next to it.
