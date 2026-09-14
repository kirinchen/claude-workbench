# tmux

Drive your *other* tmux sessions from inside Claude Code. List them, read what
they are doing, compose a message into one's input box, and — when you mean
it — press Enter.

Zero dependencies beyond the `tmux` CLI and Python 3 stdlib. Nothing is
installed into the target sessions; this plugin only reads panes and sends
keystrokes, exactly as you would by hand.

## Commands

| Command | What it does |
|---|---|
| `/tmux:ls` | Every session with its status (idle / busy / queued / dialog) and last line of output. |
| `/tmux:review <session> [what you want to know]` | Capture the pane (default 200 lines of scrollback) and answer the question, always leading with whether it is busy, idle, or holding queued messages. |
| `/tmux:draft <session> <what to say>` | Compose into the target's input box and **stop** — no Enter. Rewrites an existing draft if there is one. |
| `/tmux:send <session> <what to say>` | Same, then Enter, then re-capture to confirm the message was delivered or queued. |

Session names are **not tab-completable**. Run `/tmux:ls`, copy a name, type it.

## How it works

```
/tmux:ls      ──> tmux-sessions.sh ──┐
/tmux:review  ──> tmux-capture.sh  ──┼──> tmux-state.py ──> {status, draft, summary}
/tmux:draft   ──┐                    │
/tmux:send    ──┴> tmux-input.sh   ──┘
```

Everything deterministic lives in `scripts/`; the command markdown only calls
them and does the composing and analysis. That split is deliberate — screen
parsing and keystroke timing are not things to re-derive per invocation.

| Script | Purpose |
|---|---|
| `scripts/tmux-state.py` | Parse a pane into `{ui, status, busy, queued, draft, ghost, summary}`. Captures with `-e` and reads SGR, because a real draft and a dim placeholder differ only in styling. The single source of truth. |
| `scripts/tmux-capture.sh` | `<session> [-S N]` — dump scrollback + screen, blank lines filtered. |
| `scripts/tmux-input.sh` | `<session> --get\|--set\|--send\|--append\|--clear` — the only thing that types. |
| `scripts/tmux-sessions.sh` | `[--json]` — the `/tmux:ls` table. |

The target is usually a Claude Code TUI, but nothing assumes it. A plain shell
session reports `ui: "plain"` and still works for `ls`, `review`, and `send`.

## Known traps

Every one of these was hit in practice. They are why the scripts look the way
they do.

**1 — A dim placeholder looks exactly like a draft.**
When the input box is empty, Claude Code redisplays input you abandoned
earlier as faint text (`ESC[2m`). In a plain `capture-pane` it is byte-identical
to a real unsent draft — same position, same characters. Acting on it goes
badly in both directions: you "rewrite" a draft that was never there, or you
loop forever trying to clear a box that is already empty.

`tmux-state.py` therefore captures with `-e` and tracks the SGR faint flag.
Faint content is reported as `ghost`, never as `draft`, and `has_draft` stays
false. `/tmux:ls` marks it `~` rather than `yes`. Typing into such a box
replaces the placeholder outright — no clearing needed.

**2 — The draft is after the *last* `❯`, and even that is not enough.**
Claude Code prints `❯` in the transcript for past user turns too, so the last
one wins. But a dialog (`/model`, a permission prompt) also renders menu rows
as `❯ 1. Default`, and there is no input box at all. `tmux-state.py` anchors on
the **border pair**: the last two `────` rules that enclose a `❯` line. No
border pair, no input box.

**3 — `C-u` works, but clears one *visual* line, not the buffer.**
It does clear the Claude Code input box (and offers `Ctrl+Y to paste deleted
text`, so it is recoverable). Two catches:

- On a draft that wraps to two rows, one `C-u` leaves the first row behind.
- `C-u` kills from the start of the line **to the cursor**. With the cursor
  parked mid-line, text to its right survives.

So clearing is `End` then `C-u`, **looped until `has_draft` is false** (capped
at 40 rounds, then it fails loud rather than typing on top of leftovers).
Backspace×N was not needed, and "append only" was not needed.

**4 — Send the text and the Enter separately.**
`send-keys -l "<text>"` handles CJK fine — no dropped characters. But bundling
Enter into the same call intermittently eats the tail of the text. The scripts
always do: `-l` text → `sleep 0.3` → `send-keys Enter`. Tune with
`TMUX_PLUGIN_TYPE_SETTLE` if your machine is slower.

**5 — A busy target queues, it does not act.**
Send to a session that is mid-turn and the message goes into a queue; the box
shows `Press up to edit queued messages` and the footer keeps saying
`esc to interrupt`. `/tmux:review` and `/tmux:send` both report this as a
distinct state (`queued` / `busy+queued`) rather than claiming delivery. The
placeholder is also explicitly *not* read back as draft text.

**6 — No `ps | grep` anywhere.**
Process-list patterns match the script's own command line and produce phantom
hits. Every fact this plugin reports comes from `tmux` itself.

**7 — A missing session fails loud.**
`tmux-state.py`, `tmux-capture.sh`, and `tmux-input.sh` all exit 2 and print
the live session list rather than silently targeting nothing.

**8 — Multi-line read-back is approximate.**
A pane capture cannot distinguish a wrapped line from a real newline, so
`draft` for a wrapping draft is a close read, not a byte-exact round-trip.
It is meant for *reading* the current draft before rewriting it. Writing is
exact: `--set` rejects embedded newlines outright, since a literal newline
would submit early.

**9 — Refuses to type into itself.**
If `$TMUX` says the target is the session you are running in, `tmux-input.sh`
stops. Override with `--allow-self`.

## Install

```
/plugin marketplace add kirin/claude-workbench
/plugin install tmux@claude-workbench
```

Requires `tmux` on `PATH` and a running tmux server. No config file.
