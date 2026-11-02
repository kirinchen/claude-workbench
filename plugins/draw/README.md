# draw

*[繁體中文](./README_zhtw.md)*

Draw diagrams **with** your agent. `/draw` opens a small editor in your
browser; the diagram is saved as plain text in your repo — ideally right inside
the markdown doc it belongs to — so the agent can read it, comment on it, and
edit it, and you see its edits on refresh.

The editors are extracted from porthole's
markdown editor; no porthole needed.

## Install

```
/plugin marketplace add kirinchen/claude-workbench
/plugin install draw@claude-workbench
```

Needs Node 18+ on `PATH`.

## Commands

| Command | What it does |
|---|---|
| `/draw` | Open the chart picker → choose how to keep the diagram → draw. |
| `/draw <file>` | Open the diagram(s) already in `<file>` (`.md` with diagram blocks, or `.mmd` / `.excalidraw` / `.d2`). |

Then just ask the agent: *"look at my diagram"*, *"connect Login to API"*.
The bundled `draw` skill tells it how to read and edit each format.

## Charts

Same list as porthole's "insert chart" menu — each with a GUI editor:

| Chart | Stored as |
|---|---|
| Flowchart, State, ERD, Class, Sequence, Architecture, Mind map | Mermaid |
| D2 architecture (container-to-container edges) | D2 — needs the [`d2`](https://d2lang.com) CLI; greyed out without it |
| Excalidraw whiteboard | Excalidraw JSON |

## Where the diagram goes

After you pick a chart the page asks:

| Option | Result |
|---|---|
| **One-off** | Kept only in the draw server's memory — gone when it restarts. The agent can still read it (`mem:<id>`). |
| **Save in the current directory** | You give a name → `<name>.md` (or `<name>.mmd` / `.excalidraw` / `.d2`). |
| **Save at a path** | Relative, absolute, or `~/…`. An existing `.md` gets the diagram appended at the end. |

For the two file options you choose **Markdown block** (default — the diagram
lives in the doc as a ```` ```mermaid ```` / ```` ```excalidraw ```` / ```` ```d2 ```` fence, renders on GitHub for Mermaid) or **native single file**.

## Working with the agent

- Saving from the browser writes only that block; the rest of the `.md` is untouched.
- When the agent changes the file, the page shows a *changed elsewhere* banner
  within ~2 s — press **重新載入 (reload)**.
- If you save over a change you have not reloaded, the server refuses (409) and
  asks before overwriting.

## How it works

```
/draw ──> scripts/draw.mjs open ──> server/server.mjs (127.0.0.1:7391, zero deps)
                                     ├── serves dist/ (pre-built React editor)
                                     ├── /api/file    read / create / write back blocks
                                     ├── /api/memory  one-off drawings
                                     └── /api/d2/render  (shells out to d2)
agent ──> scripts/draw.mjs summary|get|list|put
```

- One server per machine, bound to `127.0.0.1` only. A per-start token
  (injected into the page) is required on every API call, and the `Host`
  header must be `127.0.0.1` / `localhost`, so other websites cannot write your
  files.
- State: `~/.claude-workbench/draw/server.json`; log: `server.log` beside it.
- Excalidraw's hand-drawn fonts load from its default CDN; offline it falls back
  to system fonts.

Requires **Node 18+**. The front-end is pre-built into `dist/`; to rebuild:
`cd plugins/draw/web && npm install && npm run build`.
