#!/usr/bin/env python3
"""chat-logger.py — Stop / SessionEnd hook for the `chat` plugin.

On every `Stop`, if the current session has an active chat thread, the
conversational turns added since the last run are appended to the thread's
markdown log. On `SessionEnd`, the session's chat-mode state is cleared — chat
mode is session-scoped and never leaks into the next session.

The hook is silent and always exits 0: a logging plugin must never block the
agent or inject anything into the model's context.

State lives at  .claude/chat/sessions/{session_id}.json  (relative to cwd):

    {
      "chat": "my-thread",
      "file": "doc/chat/my-thread.md",
      "transcript_cursor": null,   # null => set the watermark, log nothing yet
      "started_at": "2026-05-20T14:30:00+08:00"
    }
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime

_SYS_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)


def read_payload() -> dict:
    try:
        data = json.load(sys.stdin)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def state_path(cwd: str, session_id: str) -> str:
    return os.path.join(cwd, ".claude", "chat", "sessions", f"{session_id}.json")


def load_json(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def save_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def hhmm(ts: str) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except Exception:
        return ""


def turn_text(record: dict):
    """Return (speaker, text, timestamp) for a loggable turn, else None.

    speaker is 'you' or 'claude'. Thinking, tool calls, tool results,
    slash-command echoes, sidechain (subagent) turns and system reminders are
    all filtered out — only human-readable conversation survives.
    """
    rtype = record.get("type")
    message = record.get("message") or {}
    content = message.get("content")
    ts = record.get("timestamp", "")

    if rtype == "user":
        if record.get("isMeta") or record.get("isSidechain"):
            return None
        if not isinstance(content, str):
            return None  # list content == tool_result, not a real turn
        text = _SYS_REMINDER.sub("", content).strip()
        if not text or "<command-name>" in text or text.startswith("<local-command-"):
            return None
        return ("you", text, ts)

    if rtype == "assistant":
        if record.get("isSidechain"):
            return None
        if not isinstance(content, list):
            return None
        parts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        text = "".join(parts).strip()
        return ("claude", text, ts) if text else None

    return None


def render(records: list) -> str:
    turns = [t for t in (turn_text(r) for r in records if isinstance(r, dict)) if t]
    if not turns:
        return ""
    # Merge consecutive turns from the same speaker into one block.
    merged: list[list] = []
    for speaker, text, ts in turns:
        if merged and merged[-1][0] == speaker:
            merged[-1][1] += "\n\n" + text
        else:
            merged.append([speaker, text, ts])

    out = []
    for speaker, text, ts in merged:
        label = "\U0001f9d1 You" if speaker == "you" else "\U0001f916 Claude"
        stamp = hhmm(ts)
        head = f"## {label} · {stamp}" if stamp else f"## {label}"
        out.append(f"\n{head}\n\n{text}\n")
    return "".join(out)


def read_transcript(path: str) -> list:
    records = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                records.append({})
    return records


def handle_stop(payload: dict) -> None:
    cwd = payload.get("cwd") or os.getcwd()
    session_id = payload.get("session_id") or ""
    if not session_id:
        return

    sp = state_path(cwd, session_id)
    state = load_json(sp)
    if not isinstance(state, dict):
        return  # this session is not in chat mode

    transcript = payload.get("transcript_path")
    if not transcript or not os.path.exists(transcript):
        return

    records = read_transcript(transcript)
    total = len(records)
    cursor = state.get("transcript_cursor")

    if not isinstance(cursor, int) or cursor > total:
        # First Stop after /chat:new or /chat:resume (or the transcript was
        # compacted): drop the watermark here, log nothing this turn.
        state["transcript_cursor"] = total
        save_json(sp, state)
        return

    block = render(records[cursor:total])
    if block:
        chat_file = os.path.join(cwd, state.get("file", ""))
        try:
            with open(chat_file, "a", encoding="utf-8") as fh:
                fh.write(block)
        except OSError:
            pass

    state["transcript_cursor"] = total
    save_json(sp, state)


def handle_session_end(payload: dict) -> None:
    cwd = payload.get("cwd") or os.getcwd()
    session_id = payload.get("session_id") or ""
    if not session_id:
        return

    sp = state_path(cwd, session_id)
    state = load_json(sp)
    if isinstance(state, dict) and state.get("file"):
        chat_file = os.path.join(cwd, state["file"])
        try:
            with open(chat_file, "a", encoding="utf-8") as fh:
                fh.write(f"\n> _— session ended {datetime.now():%Y-%m-%d %H:%M} —_\n")
        except OSError:
            pass
    try:
        os.remove(sp)
    except OSError:
        pass


def main() -> int:
    payload = read_payload()
    try:
        if payload.get("hook_event_name") == "SessionEnd":
            handle_session_end(payload)
        else:  # Stop
            handle_stop(payload)
    except Exception:
        pass  # a logging hook must never break the agent
    return 0


if __name__ == "__main__":
    sys.exit(main())
