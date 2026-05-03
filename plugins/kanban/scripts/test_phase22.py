#!/usr/bin/env python3
"""Phase 22 regression checks for kanban v0.3.15 — `set-conventions`
incremental flags.

Closes #36. The original `set-conventions` required `--conventions-json`
carrying the entire block, so adding a single note required a
read → parse → append → re-serialize round-trip. For LLM-driven slash
command flows the round-trip is risky: an agent that paraphrases an
existing note on the way through silently overwrites it. The new
`--append-note`, `--remove-note`, `--set-toggle` flags let callers
mutate the block atomically without reproducing existing material.

Cases:
  (a) `--append-note "X"` adds X to existing notes; subsequent
      identical append is a no-op (idempotent for slash-command re-run
      safety).
  (b) `--remove-note "X"` drops X if present; absent is a no-op.
  (c) `--set-toggle blockedRequiresLink=false` flips the bool;
      string values pass through unchanged.
  (d) `--conventions-json` and the incremental flags are mutually
      exclusive — caller cannot accidentally combine modes.
  (e) Calling `set-conventions` with neither mode fails clearly.
  (f) Full-replace `--conventions-json` path still works (back-compat).
  (g) Several incremental flags in one call apply correctly together.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"


def _seed_jira(td, *, conventions=None) -> pathlib.Path:
    p = pathlib.Path(td) / "kanban.json"
    cfg = {
        "boardUrl": "https://x.atlassian.net/jira/software/projects/AGENT/boards/1",
        "boardId": 1, "projectKey": "AGENT",
        "transitions": {
            "TODO": {"status": "Selected for Development"},
            "DOING": {"status": "In Progress"},
            "DONE": {"status": "Done"},
        },
        "ap": {"fieldId": "customfield_10042", "fieldName": "Claude Agent",
               "registered": ["agent-fin"]},
    }
    if conventions is not None:
        cfg["conventions"] = conventions
    p.write_text(json.dumps({
        "version": "0.2",
        "backend": {"driver": "jira", "jira": cfg},
        "meta": {"priorities": ["P0"], "categories": [],
                 "columns": ["TODO", "DOING", "BLOCKED", "REVIEW",
                             "DONE", "CANCELLED"],
                 "created_at": "x", "updated_at": "x"},
        "tasks": [],
    }))
    return p


def _isolated_home(td: pathlib.Path) -> dict[str, str]:
    home = td / "fakehome"
    home.mkdir(parents=True, exist_ok=True)
    return {"HOME": str(home)}


def _run(*args, env_extra=None) -> subprocess.CompletedProcess:
    cmd = ["python3", str(PLUGIN / "scripts" / "jira_setup.py"), *args]
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, capture_output=True, env=env, text=True)


def _read_conventions(kp: pathlib.Path) -> dict:
    return json.loads(kp.read_text())["backend"]["jira"]["conventions"]


def test_append_note_adds_then_idempotent():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td, conventions={"notes": ["existing"],
                                         "blockedRequiresLink": True})
        env = _isolated_home(td)

        # First append — added
        out = _run("set-conventions", "--kanban-path", str(kp),
                   "--append-note", "new rule", env_extra=env)
        assert out.returncode == 0, out.stderr
        cv = _read_conventions(kp)
        assert cv["notes"] == ["existing", "new rule"]

        # Second append (same text) — no-op (idempotent)
        out = _run("set-conventions", "--kanban-path", str(kp),
                   "--append-note", "new rule", env_extra=env)
        assert out.returncode == 0, out.stderr
        cv = _read_conventions(kp)
        assert cv["notes"] == ["existing", "new rule"], cv["notes"]


def test_remove_note_drops_present_no_op_when_absent():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td, conventions={"notes": ["a", "b", "c"],
                                         "blockedRequiresLink": True})
        env = _isolated_home(td)

        out = _run("set-conventions", "--kanban-path", str(kp),
                   "--remove-note", "b", env_extra=env)
        assert out.returncode == 0, out.stderr
        cv = _read_conventions(kp)
        assert cv["notes"] == ["a", "c"]

        # Removing something not there — no-op
        out = _run("set-conventions", "--kanban-path", str(kp),
                   "--remove-note", "ghost", env_extra=env)
        assert out.returncode == 0, out.stderr
        cv = _read_conventions(kp)
        assert cv["notes"] == ["a", "c"]


def test_set_toggle_flips_bool_and_preserves_notes():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td, conventions={"notes": ["x"],
                                         "blockedRequiresLink": True})
        env = _isolated_home(td)

        out = _run("set-conventions", "--kanban-path", str(kp),
                   "--set-toggle", "blockedRequiresLink=false",
                   env_extra=env)
        assert out.returncode == 0, out.stderr
        cv = _read_conventions(kp)
        assert cv["blockedRequiresLink"] is False
        # Notes preserved
        assert cv["notes"] == ["x"]

        # Case-insensitive bool: TRUE works too
        out = _run("set-conventions", "--kanban-path", str(kp),
                   "--set-toggle", "blockedRequiresLink=TRUE",
                   env_extra=env)
        assert out.returncode == 0, out.stderr
        cv = _read_conventions(kp)
        assert cv["blockedRequiresLink"] is True


def test_conventions_json_and_incremental_are_mutually_exclusive():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td)
        env = _isolated_home(td)

        out = _run(
            "set-conventions", "--kanban-path", str(kp),
            "--conventions-json", json.dumps({"notes": ["x"]}),
            "--append-note", "y",
            env_extra=env,
        )
        assert out.returncode != 0, out.stdout
        # The error surfaces in stdout (via _emit/_fail JSON) or stderr
        combined = (out.stdout + out.stderr).lower()
        assert "mutually exclusive" in combined \
            or "cannot be combined" in combined \
            or "different modes" in combined, combined


def test_set_conventions_requires_at_least_one_mode():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td)
        env = _isolated_home(td)

        out = _run("set-conventions", "--kanban-path", str(kp),
                   env_extra=env)
        assert out.returncode != 0, out.stdout
        combined = (out.stdout + out.stderr).lower()
        assert "requires either" in combined or "incremental" in combined, combined


def test_full_replace_path_still_works():
    """Back-compat: existing slash-command invocations using
    --conventions-json must keep working."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td, conventions={"notes": ["old"],
                                         "blockedRequiresLink": True})
        env = _isolated_home(td)

        out = _run(
            "set-conventions", "--kanban-path", str(kp),
            "--conventions-json", json.dumps({
                "notes": ["new1", "new2"],
                "blockedRequiresLink": False,
            }),
            env_extra=env,
        )
        assert out.returncode == 0, out.stderr
        cv = _read_conventions(kp)
        assert cv["notes"] == ["new1", "new2"]
        assert cv["blockedRequiresLink"] is False


def test_combo_append_remove_toggle_in_one_call():
    """All three incremental flags in one call apply consistently."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td, conventions={"notes": ["keep", "drop"],
                                         "blockedRequiresLink": True})
        env = _isolated_home(td)

        out = _run(
            "set-conventions", "--kanban-path", str(kp),
            "--append-note", "added",
            "--append-note", "added2",
            "--remove-note", "drop",
            "--set-toggle", "blockedRequiresLink=false",
            env_extra=env,
        )
        assert out.returncode == 0, out.stderr
        cv = _read_conventions(kp)
        assert cv["notes"] == ["keep", "added", "added2"]
        assert cv["blockedRequiresLink"] is False


def main() -> int:
    cases = [
        ("append_note_adds_then_idempotent", test_append_note_adds_then_idempotent),
        ("remove_note_drops_present_no_op_when_absent",
         test_remove_note_drops_present_no_op_when_absent),
        ("set_toggle_flips_bool_and_preserves_notes",
         test_set_toggle_flips_bool_and_preserves_notes),
        ("conventions_json_and_incremental_are_mutually_exclusive",
         test_conventions_json_and_incremental_are_mutually_exclusive),
        ("set_conventions_requires_at_least_one_mode",
         test_set_conventions_requires_at_least_one_mode),
        ("full_replace_path_still_works",
         test_full_replace_path_still_works),
        ("combo_append_remove_toggle_in_one_call",
         test_combo_append_remove_toggle_in_one_call),
    ]
    failed = 0
    for name, fn in cases:
        try:
            fn()
        except Exception as e:
            print(f"FAIL  {name}: {e}", file=sys.stderr)
            failed += 1
        else:
            print(f"ok    {name}")
    if failed:
        print(f"phase22: {failed} failure(s)", file=sys.stderr)
        return 1
    print("phase22: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
