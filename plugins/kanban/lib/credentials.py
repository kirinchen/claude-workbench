"""Atomic ~/.claude-workbench/.env reader/writer.

Shared with notify plugin's storage convention. Each plugin owns its prefix
(e.g. JIRA_*, PUSHOVER_*) and must never modify another plugin's lines.

Public surface:
    env_path() -> Path
    read(prefix=None) -> dict[str, str]
    write(updates: dict[str, str], prefix: str) -> None
    delete(keys: list[str]) -> None
    ensure_mode() -> bool   # True if file exists with 0600

Write strategy: read all lines, replace lines whose key starts with `prefix`,
preserve everything else byte-for-byte, write to tempfile, fsync, rename.
"""
from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Iterable


ENV_DIR = Path.home() / ".claude-workbench"
ENV_FILE = ENV_DIR / ".env"

# Match KEY=VALUE lines (no inline comments — keeps the format simple).
_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def env_path() -> Path:
    return ENV_FILE


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return f.read().splitlines()


def _parse(lines: Iterable[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in lines:
        m = _LINE_RE.match(line.strip())
        if not m:
            continue
        out[m.group(1)] = m.group(2)
    return out


def read(prefix: str | None = None) -> dict[str, str]:
    """Return all KEY=VALUE pairs in .env, optionally filtered by prefix."""
    if not ENV_FILE.exists():
        return {}
    pairs = _parse(_read_lines(ENV_FILE))
    if prefix is None:
        return pairs
    return {k: v for k, v in pairs.items() if k.startswith(prefix)}


def ensure_mode() -> bool:
    """If .env exists with mode broader than 0600, tighten and return False.
    Returns True if file is already 0600 (or absent).
    """
    if not ENV_FILE.exists():
        return True
    mode = ENV_FILE.stat().st_mode & 0o777
    if mode != 0o600:
        os.chmod(ENV_FILE, 0o600)
        return False
    return True


def write(updates: dict[str, str], prefix: str) -> None:
    """Replace all lines whose key starts with `prefix` with the given updates.

    Other plugins' lines are preserved byte-for-byte (including blanks/comments).
    File mode is forced to 0600. Write is atomic via tempfile + rename.

    Raises ValueError if any update key does not start with `prefix` (guards
    against accidentally clobbering another plugin's namespace).
    """
    for k in updates:
        if not k.startswith(prefix):
            raise ValueError(
                f"key {k!r} does not start with prefix {prefix!r} — refusing to write"
            )

    ENV_DIR.mkdir(parents=True, exist_ok=True)
    old_umask = os.umask(0o077)
    try:
        existing = _read_lines(ENV_FILE)

        kept: list[str] = []
        seen: set[str] = set()
        for line in existing:
            stripped = line.strip()
            m = _LINE_RE.match(stripped)
            if m and m.group(1).startswith(prefix):
                key = m.group(1)
                if key in updates:
                    kept.append(f"{key}={updates[key]}")
                    seen.add(key)
                # else: drop (key removed in this update set)
                continue
            kept.append(line)

        # Append any new keys not present before.
        for key, val in updates.items():
            if key not in seen:
                kept.append(f"{key}={val}")

        body = "\n".join(kept)
        if body and not body.endswith("\n"):
            body += "\n"

        fd, tmp_path = tempfile.mkstemp(prefix=".env.", suffix=".tmp", dir=ENV_DIR)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(body)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, ENV_FILE)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    finally:
        os.umask(old_umask)


def delete(keys: list[str]) -> None:
    """Remove the named keys. No-op if .env or keys absent."""
    if not ENV_FILE.exists() or not keys:
        return
    existing = _read_lines(ENV_FILE)
    targets = set(keys)
    kept = [
        line
        for line in existing
        if not (
            (m := _LINE_RE.match(line.strip())) is not None
            and m.group(1) in targets
        )
    ]
    body = "\n".join(kept)
    if body and not body.endswith("\n"):
        body += "\n"
    fd, tmp_path = tempfile.mkstemp(prefix=".env.", suffix=".tmp", dir=ENV_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, ENV_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
