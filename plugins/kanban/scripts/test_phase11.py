#!/usr/bin/env python3
"""Phase 11 regression checks for kanban v0.3.4 — team conventions (issue #10).

Soft agreements (`backend.jira.conventions`) travel with the share code
(`kanban-jira-code/2`). Receiver UX requires literal-phrase ack before
init completes. One opt-in machine-actionable toggle:
`blockedRequiresLink`.

Cases:
  (a) lib.conventions.normalize fills defaults and drops unknown keys
  (b) lib.conventions.validate flags >200-char notes and >10-note count
  (c) lib.conventions.is_empty distinguishes default vs populated
  (d) lib.conventions.hash_conventions is stable across normalised input
  (e) lib.conventions.record_ack / has_recent_ack roundtrip + preserves
       sibling fields in kanban-agent.json (notably `ap`)
  (f) emit-jira-code emits schema /2 with conventions block (empty by
       default)
  (g) emit-jira-code preserves user-set notes + blockedRequiresLink
  (h) import-jira-code accepts /1 (back-compat — conventions empty)
  (i) import-jira-code accepts /2 with conventions; ackRequired=True when
       notes non-empty AND no ack on file
  (j) import-jira-code rejects unknown schema versions (e.g. /3)
  (k) set-conventions writes block, returns warnings on guardrail breach
  (l) read-conventions returns block + ackHash + alreadyAcked
  (m) record-conventions-ack writes the right hash; subsequent
       read-conventions reflects alreadyAcked=True
  (n) cmd_transition refuses BLOCKED without --blocked-by when
       blockedRequiresLink is true; allows it when false
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "kanban"
sys.path.insert(0, str(REPO / "plugins" / "kanban"))

from lib import conventions as cv  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "jira_setup_mod", str(PLUGIN / "scripts" / "jira_setup.py")
)
_jira_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_jira_setup)  # type: ignore[union-attr]


# --- lib.conventions ----------------------------------------------------


def test_normalize_fills_defaults_drops_unknown():
    assert cv.normalize(None) == {"notes": []}
    assert cv.normalize({}) == {"notes": []}
    assert cv.normalize({"notes": ["a", 1, "b"]}) == {"notes": ["a", "b"]}
    out = cv.normalize({"notes": ["x"], "blockedRequiresLink": True, "futureField": 99})
    assert out == {"notes": ["x"], "blockedRequiresLink": True}


def test_validate_flags_guardrails():
    # Guardrail bumped 200 → 300 in 0.3.10 (issue #20). 350 chars is
    # over the new threshold; verify the warning text reflects it.
    warns = cv.validate({"notes": ["a" * 350, "ok"]})
    assert any("350 chars" in w for w in warns)
    # 250 chars is under the new threshold — should NOT warn.
    warns = cv.validate({"notes": ["a" * 250]})
    assert all("250 chars" not in w for w in warns)
    warns = cv.validate({"notes": ["x"] * 15})
    assert any("15 entries" in w for w in warns)
    warns = cv.validate({"notes": ["", "   ", "real"]})
    assert any("empty" in w for w in warns)
    assert cv.validate({"notes": ["use CANCELLED not DELETE"]}) == []
    assert cv.validate(None) == []


def test_is_empty():
    assert cv.is_empty(None) is True
    assert cv.is_empty({}) is True
    assert cv.is_empty({"notes": []}) is True
    assert cv.is_empty({"notes": ["x"]}) is False
    assert cv.is_empty({"blockedRequiresLink": True}) is False


def test_hash_stability():
    h1 = cv.hash_conventions({"notes": ["a", "b"]})
    h2 = cv.hash_conventions({"notes": ["a", "b"]})
    h3 = cv.hash_conventions({"notes": ["a", "c"]})
    assert h1 == h2
    assert h1 != h3
    h4 = cv.hash_conventions({"notes": ["a", "b"], "futureField": 1})
    assert h1 == h4


def test_record_ack_preserves_existing_fields():
    with tempfile.TemporaryDirectory() as td:
        repo = pathlib.Path(td)
        agent_dir = repo / ".claude"
        agent_dir.mkdir()
        (agent_dir / "kanban-agent.json").write_text(
            json.dumps({"ap": "agent-fin"}) + "\n"
        )
        conv = {"notes": ["use CANCELLED not DELETE"]}
        assert not cv.has_recent_ack(repo, conv)
        cv.record_ack(repo, conv)
        assert cv.has_recent_ack(repo, conv)
        on_disk = json.loads((agent_dir / "kanban-agent.json").read_text())
        assert on_disk["ap"] == "agent-fin"
        assert "acknowledgedConventions" in on_disk
        assert on_disk["acknowledgedConventions"]["hash"] == cv.hash_conventions(conv)
        other = {"notes": ["different"]}
        assert not cv.has_recent_ack(repo, other)


# --- CLI: emit/import ---------------------------------------------------


def _seed_jira(td, *, conventions=None) -> pathlib.Path:
    p = pathlib.Path(td) / "kanban.json"
    cfg = {
        "boardUrl": "https://acme.atlassian.net/jira/software/projects/AGENT/boards/1",
        "boardId": 1, "projectKey": "AGENT",
        "transitions": {
            "TODO": {"status": "Selected for Development"},
            "DOING": {"status": "In Progress"},
            "BLOCKED": {"status": "In Progress", "addLabels": ["kanban:blocked"]},
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
                 "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"],
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


def test_emit_default_v2_with_empty_conventions():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td)
        out = _run("emit-jira-code", "--kanban-path", str(kp),
                   env_extra=_isolated_home(td))
        assert out.returncode == 0, out.stderr
        code = json.loads(out.stdout)["code"]
        assert code["schema"] == "kanban-jira-code/2"
        assert code["conventions"] == {"notes": []}


def test_emit_preserves_notes_and_toggle():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td, conventions={
            "notes": ["use CANCELLED not DELETE",
                      "Review 一律 assign kirin"],
            "blockedRequiresLink": True,
        })
        out = _run("emit-jira-code", "--kanban-path", str(kp),
                   env_extra=_isolated_home(td))
        assert out.returncode == 0
        code = json.loads(out.stdout)["code"]
        assert code["conventions"]["notes"] == [
            "use CANCELLED not DELETE", "Review 一律 assign kirin"
        ]
        assert code["conventions"]["blockedRequiresLink"] is True


def test_import_v1_back_compat():
    """Old code with schema=/1 still importable; conventions silently empty."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = pathlib.Path(td) / "kanban.json"
        kp.write_text(json.dumps({
            "version": "0.2",
            "backend": {"driver": "jira", "jira": {"projectKey": "AGENT"}},
            "meta": {"priorities": ["P0"], "categories": [],
                     "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"],
                     "created_at": "x", "updated_at": "x"},
            "tasks": [],
        }))
        v1_code = {
            "schema": "kanban-jira-code/1",
            "boardUrl": "https://acme.atlassian.net/jira/software/projects/AGENT/boards/1",
            "boardId": 1, "projectKey": "AGENT",
            "transitions": {"DOING": {"status": "In Progress"}},
        }
        out = _run("import-jira-code",
                   "--kanban-path", str(kp),
                   "--code-json", json.dumps(v1_code),
                   env_extra=_isolated_home(td))
        assert out.returncode == 0, out.stderr
        j = json.loads(out.stdout)
        assert j["ok"] is True
        assert j["schema"] == "kanban-jira-code/1"
        assert j["conventions"] == {"notes": []}
        assert j["ackRequired"] is False


def test_import_v2_with_notes_sets_ack_required():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = pathlib.Path(td) / "kanban.json"
        kp.write_text(json.dumps({
            "version": "0.2",
            "backend": {"driver": "jira", "jira": {"projectKey": "AGENT"}},
            "meta": {"priorities": ["P0"], "categories": [],
                     "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"],
                     "created_at": "x", "updated_at": "x"},
            "tasks": [],
        }))
        v2_code = {
            "schema": "kanban-jira-code/2",
            "boardUrl": "https://acme.atlassian.net/jira/software/projects/AGENT/boards/1",
            "boardId": 1, "projectKey": "AGENT",
            "transitions": {"DOING": {"status": "In Progress"}},
            "conventions": {
                "notes": ["use CANCELLED not DELETE"],
                "blockedRequiresLink": False,
            },
        }
        out = _run("import-jira-code",
                   "--kanban-path", str(kp),
                   "--code-json", json.dumps(v2_code),
                   env_extra=_isolated_home(td))
        assert out.returncode == 0, out.stderr
        j = json.loads(out.stdout)
        assert j["ok"] is True
        assert j["schema"] == "kanban-jira-code/2"
        assert j["conventions"]["notes"] == ["use CANCELLED not DELETE"]
        assert j["ackRequired"] is True


def test_import_rejects_unknown_schema():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = pathlib.Path(td) / "kanban.json"
        kp.write_text(json.dumps({
            "version": "0.2",
            "backend": {"driver": "jira", "jira": {"projectKey": "X"}},
            "meta": {"priorities": ["P0"], "categories": [],
                     "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"],
                     "created_at": "x", "updated_at": "x"},
            "tasks": [],
        }))
        out = _run("import-jira-code",
                   "--kanban-path", str(kp),
                   "--code-json", json.dumps({"schema": "kanban-jira-code/3"}),
                   env_extra=_isolated_home(td))
        assert out.returncode != 0
        j = json.loads(out.stdout)
        assert j["ok"] is False


# --- CLI: set/read/record-ack ------------------------------------------


def test_set_conventions_writes_and_warns():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td)
        # 0.3.10 bumped guardrail to 300; use 350 to trigger the warning.
        notes = ["a" * 350, "ok note"]
        out = _run(
            "set-conventions",
            "--kanban-path", str(kp),
            "--conventions-json", json.dumps({"notes": notes}),
            env_extra=_isolated_home(td),
        )
        assert out.returncode == 0, out.stderr
        j = json.loads(out.stdout)
        assert j["ok"] is True
        assert any("350 chars" in w for w in j["warnings"])
        cfg = json.loads(kp.read_text())["backend"]["jira"]
        assert cfg["conventions"]["notes"] == notes


def test_read_conventions_returns_ack_state():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td, conventions={"notes": ["x"]})
        out = _run("read-conventions", "--kanban-path", str(kp),
                   env_extra=_isolated_home(td))
        j = json.loads(out.stdout)
        assert j["ok"] is True
        assert j["isEmpty"] is False
        assert j["alreadyAcked"] is False
        assert isinstance(j["ackHash"], str) and len(j["ackHash"]) > 0


def test_record_ack_then_read_shows_acked():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td, conventions={"notes": ["x"]})
        env = _isolated_home(td)
        out = _run("read-conventions", "--kanban-path", str(kp), env_extra=env)
        assert json.loads(out.stdout)["alreadyAcked"] is False
        out = _run("record-conventions-ack", "--kanban-path", str(kp), env_extra=env)
        assert out.returncode == 0
        out = _run("read-conventions", "--kanban-path", str(kp), env_extra=env)
        assert json.loads(out.stdout)["alreadyAcked"] is True


# --- blockedRequiresLink enforcement ------------------------------------


def test_block_requires_link_when_convention_on():
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td, conventions={"blockedRequiresLink": True})
        out = _run(
            "transition", "--kanban-path", str(kp),
            "--key", "AGENT-1", "--to", "BLOCKED", "--reason", "anything",
            env_extra=_isolated_home(td),
        )
        assert out.returncode != 0
        j = json.loads(out.stdout)
        assert j["ok"] is False
        assert j.get("kind") == "convention"
        assert "blockedRequiresLink" in j["error"]


def test_block_allows_when_convention_off():
    """Convention off → cmd_transition's pre-check passes through; failure
    downstream is for a different reason (no creds), not the convention."""
    with tempfile.TemporaryDirectory() as raw:
        td = pathlib.Path(raw)
        kp = _seed_jira(td)
        out = _run(
            "transition", "--kanban-path", str(kp),
            "--key", "AGENT-1", "--to", "BLOCKED", "--reason", "anything",
            env_extra=_isolated_home(td),
        )
        j = json.loads(out.stdout)
        assert j["ok"] is False
        assert j.get("kind") != "convention"


def main() -> int:
    cases = [
        ("normalize_fills_defaults_drops_unknown", test_normalize_fills_defaults_drops_unknown),
        ("validate_flags_guardrails", test_validate_flags_guardrails),
        ("is_empty", test_is_empty),
        ("hash_stability", test_hash_stability),
        ("record_ack_preserves_existing_fields", test_record_ack_preserves_existing_fields),
        ("emit_default_v2_with_empty_conventions", test_emit_default_v2_with_empty_conventions),
        ("emit_preserves_notes_and_toggle", test_emit_preserves_notes_and_toggle),
        ("import_v1_back_compat", test_import_v1_back_compat),
        ("import_v2_with_notes_sets_ack_required", test_import_v2_with_notes_sets_ack_required),
        ("import_rejects_unknown_schema", test_import_rejects_unknown_schema),
        ("set_conventions_writes_and_warns", test_set_conventions_writes_and_warns),
        ("read_conventions_returns_ack_state", test_read_conventions_returns_ack_state),
        ("record_ack_then_read_shows_acked", test_record_ack_then_read_shows_acked),
        ("block_requires_link_when_convention_on", test_block_requires_link_when_convention_on),
        ("block_allows_when_convention_off", test_block_allows_when_convention_off),
    ]
    for name, fn in cases:
        try:
            fn()
        except AssertionError as e:
            print(f"FAIL  {name}: {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"ERROR {name}: {type(e).__name__}: {e}", file=sys.stderr)
            return 2
        print(f"ok    {name}")
    print("phase11: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
