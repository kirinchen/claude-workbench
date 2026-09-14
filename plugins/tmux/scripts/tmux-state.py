#!/usr/bin/env python3
"""Parse a tmux pane's visible screen into a structured state description.

Deterministic half of the `tmux` plugin: everything here is pure parsing, so
the slash commands never have to guess at ANSI layout. Python stdlib only.

Usage:
    tmux-state.py <session> [--field <name>]

Emits a JSON object on stdout (or a single field's raw value with --field).
Exits 2 with the list of live sessions on stderr if <session> does not exist.

What it detects
---------------
ui       claude-code | dialog | plain
status   idle | busy | queued | busy+queued | dialog | unknown
draft    real, unsent text in the Claude Code input box ("" if empty)
ghost    dim placeholder text shown in an *empty* box — NOT a draft
queued   True when the target is busy and the box shows the queue placeholder
summary  last non-empty content line above the input box (for `/tmux:ls`)

The pane is captured with `-e` so SGR attributes survive: Claude Code renders
a real draft in normal weight and a placeholder in faint (`ESC[2m`), and the
two are indistinguishable in a plain capture. Telling them apart is the whole
reason this script reads escape sequences at all.

Deliberately never shells out to `ps`/`pgrep`/`grep` over a process list —
those patterns match this script's own command line and produce phantom hits.
Every fact below comes from `tmux` itself.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

# U+2500 BOX DRAWINGS LIGHT HORIZONTAL — the Claude Code input-box border.
BORDER_CHAR = "─"
MIN_BORDER_RUN = 10
# U+276F HEAVY RIGHT-POINTING ANGLE QUOTATION MARK — the input-box prompt.
# Also printed in the transcript for past user turns, hence "last one wins".
PROMPT_CHAR = "❯"
NBSP = " "
RULE_CHARS = "─━┄┈═▁▔¯—_-"

QUEUE_PLACEHOLDER = "Press up to edit queued messages"
BUSY_MARKER = "esc to interrupt"
DIALOG_MARKERS = ("Esc to cancel", "Enter to confirm", "Enter to set as default")

# Transient Claude Code chrome that would otherwise win the "last content
# line" race and make every `/tmux:ls` summary read "Update installed".
CHROME = (
    "Update installed",
    "Restart to update",
    "focus-events",
    "bypass permissions on",
    "plan mode on",
    "Ctrl+Y to paste deleted text",
)

# How far up from the bottom to look for the footer markers.
FOOTER_SCAN = 6

ESC = "\x1b"


def styled(line: str) -> list[tuple[str, bool]]:
    """Split a captured line into (character, is_faint) pairs.

    Handles the two escape families tmux hands back with `-e`: SGR (`ESC[…m`,
    the only one whose state we track) and OSC 8 hyperlinks, which Claude Code
    wraps around the session link in the footer and which must be discarded
    payload-and-all rather than leaking their URL into the text.
    """
    out: list[tuple[str, bool]] = []
    faint = False
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch != ESC:
            out.append((ch, faint))
            i += 1
            continue
        if line.startswith(ESC + "[", i):
            j = i + 2
            while j < n and line[j] not in "@ABCDEFGHJKSTfmnsulh":
                j += 1
            if j < n and line[j] == "m":
                params = [p for p in line[i + 2:j].split(";")]
                for p in params:
                    if p in ("", "0", "22"):
                        faint = False
                    elif p == "2":
                        faint = True
            i = j + 1
        elif line.startswith(ESC + "]", i):
            j = i + 2
            while j < n:
                if line[j] == "\x07":
                    j += 1
                    break
                if line.startswith(ESC + "\\", j):
                    j += 2
                    break
                j += 1
            i = j
        else:
            i += 2
    return out


def plain(line: str) -> str:
    return "".join(ch for ch, _ in styled(line))


def tmux(*args: str) -> str:
    return subprocess.run(
        ["tmux", *args], capture_output=True, text=True, check=False
    ).stdout


def live_sessions() -> list[str]:
    out = tmux("list-sessions", "-F", "#{session_name}")
    return [s for s in out.splitlines() if s]


def require_session(name: str) -> None:
    sessions = live_sessions()
    if name in sessions:
        return
    listing = "\n".join(f"  - {s}" for s in sessions) or "  (none)"
    sys.stderr.write(
        f"tmux-state: no such session: {name!r}\nLive sessions:\n{listing}\n"
    )
    sys.exit(2)


def is_border(line: str) -> bool:
    s = line.strip()
    return len(s) >= MIN_BORDER_RUN and set(s) == {BORDER_CHAR}


def is_rule(line: str) -> bool:
    """A horizontal rule of any box-drawing character (borders, underlines)."""
    s = line.strip()
    return len(s) >= MIN_BORDER_RUN and len(set(s)) == 1 and s[0] in RULE_CHARS


def content_lines(lines: list[str]) -> list[str]:
    """Lines a human would call content: no blanks, rules, or transient chrome."""
    return [
        ln.strip()
        for ln in lines
        if ln.strip() and not is_rule(ln) and not any(c in ln for c in CHROME)
    ]


def find_input_box(lines: list[str]) -> tuple[int, int] | None:
    """Locate the Claude Code input box as (top_border, bottom_border).

    The box is the *last* pair of adjacent border lines that encloses a line
    starting with `❯`. Anchoring on the border pair — rather than on the last
    `❯` alone — is what keeps transcript echoes and dialog menu items
    (`❯ 1. Default`) from being mistaken for the input box.
    """
    borders = [i for i, ln in enumerate(lines) if is_border(ln)]
    for bottom, top in zip(reversed(borders), reversed(borders[:-1])):
        if bottom - top < 2:
            continue
        if any(ln.lstrip().startswith(PROMPT_CHAR) for ln in lines[top + 1:bottom]):
            return top, bottom
    return None


def box_line(raw: str, is_first: bool) -> tuple[str, bool]:
    """Return (text, all_faint) for one line of the input box."""
    pairs = styled(raw)
    k = 0
    while k < len(pairs) and pairs[k][0] in " \t":
        k += 1
    if is_first and k < len(pairs) and pairs[k][0] == PROMPT_CHAR:
        k += 1
    while k < len(pairs) and pairs[k][0] in (NBSP + " \t"):
        k += 1
    body = pairs[k:]
    while body and body[-1][0] in " \t":
        body.pop()
    visible = [(c, f) for c, f in body if c.strip()]
    return "".join(c for c, _ in body), bool(visible) and all(f for _, f in visible)


def looks_like_dialog(lines: list[str]) -> bool:
    tail = [ln for ln in lines if ln.strip()][-FOOTER_SCAN:]
    return any(m in ln for ln in tail for m in DIALOG_MARKERS)


def read_state(session: str) -> dict:
    require_session(session)

    raw_lines = tmux("capture-pane", "-p", "-e", "-t", session).split("\n")
    lines = [plain(ln).rstrip() for ln in raw_lines]
    pane_cmd = tmux(
        "display-message", "-p", "-t", session, "#{pane_current_command}"
    ).strip()

    tail = [ln for ln in lines if ln.strip()][-FOOTER_SCAN:]
    busy = any(BUSY_MARKER in ln for ln in tail)

    state = {
        "session": session,
        "pane_command": pane_cmd,
        "busy": busy,
        "queued": False,
        "draft": "",
        "draft_lines": [],
        "has_draft": False,
        "ghost": "",
        "summary": "",
    }

    box = find_input_box(lines)
    if box is None:
        state["ui"] = "dialog" if looks_like_dialog(lines) else "plain"
        content = content_lines(lines)
        state["summary"] = content[-1] if content else ""
        state["status"] = (
            "dialog" if state["ui"] == "dialog"
            else "busy" if busy
            else "idle" if content
            else "unknown"
        )
        return state

    top, bottom = box
    state["ui"] = "claude-code"

    parsed = [
        box_line(raw_lines[i], is_first=(i == top + 1))
        for i in range(top + 1, bottom)
    ]
    parsed = [(t, f) for t, f in parsed if t.strip()]
    texts = [t.strip() for t, _ in parsed]
    all_faint = bool(parsed) and all(f for _, f in parsed)

    if texts and texts[0] == QUEUE_PLACEHOLDER:
        # Busy target holding messages — the box itself is empty.
        state["queued"] = True
    elif all_faint:
        # Faint text in an empty box is Claude Code's placeholder for input you
        # abandoned earlier. It looks exactly like a draft in a plain capture,
        # but there is nothing there to clear, rewrite, or send.
        state["ghost"] = "\n".join(texts)
    else:
        # Wrapped lines and real newlines are indistinguishable in a pane
        # capture, so a multi-line read-back is an approximation — see README
        # "Known traps".
        state["draft_lines"] = texts
        state["draft"] = "\n".join(texts)
        state["has_draft"] = bool(texts)

    content = content_lines(lines[:top])
    state["summary"] = content[-1] if content else ""

    if busy and state["queued"]:
        state["status"] = "busy+queued"
    elif busy:
        state["status"] = "busy"
    elif state["queued"]:
        state["status"] = "queued"
    else:
        state["status"] = "idle"
    return state


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("session")
    ap.add_argument("--field", help="print one field's raw value instead of JSON")
    args = ap.parse_args()

    state = read_state(args.session)
    if args.field:
        if args.field not in state:
            sys.stderr.write(f"tmux-state: unknown field: {args.field}\n")
            return 2
        value = state[args.field]
        print(value if isinstance(value, str) else json.dumps(value))
        return 0
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
