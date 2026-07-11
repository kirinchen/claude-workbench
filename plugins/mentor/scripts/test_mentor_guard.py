#!/usr/bin/env python3
"""Tests for mentor-guard.py frontmatter detection.

Regression coverage for the false positive where editing the *body* of an
Epic/Sprint/Issue/ADR made the guard warn "no YAML frontmatter block found at
top of file" — because it inspected the edit fragment (``new_string``) instead
of the resulting file. The original bug report reproduced it with a Chinese
title on a git-untracked file; the tests below pin that exact scenario down and
prove neither the non-ASCII title nor the untracked state is the cause.

Pure standard library (PyYAML is not assumed to be installed). Run with:

    python3 test_mentor_guard.py
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _load(name: str, filename: str):
    """Import a script by path (mentor-guard.py's hyphen blocks `import`)."""
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


guard = _load("mentor_guard", "mentor-guard.py")

MENTOR_YAML = """\
schema_version: 1
mode: development
paths:
  spec: doc/SPEC.md
  wiki: doc/Wiki/
  epic: doc/Epic/
  sprint: doc/Sprint/
  issue: doc/Issue/
"""

# Epic with a Chinese title + em dash + full-width punctuation — exactly the
# shape that was (wrongly) suspected of breaking the UTF-8 / regex path.
EPIC_WITH_FM = """\
---
id: EPIC-001
title: Journey Layer — 從單題引擎到「Starter 問題 → IBM」完整旅程系統
status: planning
owner: Kelly Tsai（主）／Corey（次）
created: 2026-07-10
---

## Why

JQF v2 引擎一次精煉一題。
"""

EPIC_NO_FM = """\
## Why

JQF v2 引擎一次精煉一題，沒有 frontmatter。
"""


def _make_project(epic_body: str) -> tuple[Path, Path]:
    """Create a throwaway project (NOT a git repo → maximally 'untracked')."""
    root = Path(tempfile.mkdtemp(prefix="mentor-guard-test-"))
    (root / ".claude").mkdir()
    (root / ".claude" / "mentor.yaml").write_text(MENTOR_YAML, encoding="utf-8")
    epic_dir = root / "doc" / "Epic"
    epic_dir.mkdir(parents=True)
    epic_path = epic_dir / "EPIC-001-journey-layer.md"
    epic_path.write_text(epic_body, encoding="utf-8")
    return root, epic_path


def _run_guard(project_dir: Path, event: dict) -> str:
    """Invoke the real hook end-to-end; return the additionalContext (or '')."""
    saved_stdin = sys.stdin
    saved_env = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(project_dir)
    sys.stdin = io.StringIO(json.dumps(event))
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            guard.main()
    finally:
        sys.stdin = saved_stdin
        if saved_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved_env
    out = buf.getvalue().strip()
    if not out:
        return ""
    return json.loads(out).get("hookSpecificOutput", {}).get("additionalContext", "")


# --- test cases ---------------------------------------------------------------

def test_edit_body_fragment_chinese_untracked_no_false_positive() -> None:
    """THE regression: edit the body of an untracked, Chinese-titled Epic.

    The frontmatter lives at the top of the file, outside the edited fragment.
    The guard must NOT warn — it used to, because it saw only ``new_string``.
    """
    proj, epic = _make_project(EPIC_WITH_FM)
    event = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(epic),
            "old_string": "JQF v2 引擎一次精煉一題。",
            "new_string": "JQF v2 引擎一次精煉一題（stateless runTurn）。",
        },
    }
    ctx = _run_guard(proj, event)
    assert ctx == "", f"expected no warning, got: {ctx!r}"


def test_edit_removing_required_field_is_flagged() -> None:
    """Reconstruction (not just fragment) lets us catch a real regression:
    an edit that deletes a required frontmatter field."""
    proj, epic = _make_project(EPIC_WITH_FM)
    event = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(epic),
            "old_string": "status: planning\n",
            "new_string": "",
        },
    }
    ctx = _run_guard(proj, event)
    assert "missing fields: status" in ctx, f"expected missing-field warning, got: {ctx!r}"


def test_multiedit_body_fragments_no_false_positive() -> None:
    """MultiEdit (previously skipped entirely) is now reconstructed too."""
    proj, epic = _make_project(EPIC_WITH_FM)
    event = {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": str(epic),
            "edits": [
                {"old_string": "## Why", "new_string": "## Why（為什麼）"},
                {"old_string": "一次精煉一題", "new_string": "一次精煉一題（單題）"},
            ],
        },
    }
    ctx = _run_guard(proj, event)
    assert ctx == "", f"expected no warning, got: {ctx!r}"


def test_write_full_valid_content_is_clean() -> None:
    proj, epic = _make_project(EPIC_WITH_FM)
    event = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(epic), "content": EPIC_WITH_FM},
    }
    assert _run_guard(proj, event) == ""


def test_write_content_with_bom_is_clean() -> None:
    """A leading UTF-8 BOM must not hide otherwise-valid frontmatter."""
    proj, epic = _make_project(EPIC_WITH_FM)
    event = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(epic), "content": "﻿" + EPIC_WITH_FM},
    }
    ctx = _run_guard(proj, event)
    assert ctx == "", f"expected no warning for BOM-prefixed content, got: {ctx!r}"


def test_write_content_without_frontmatter_is_flagged() -> None:
    """True negative preserved: genuinely missing frontmatter still warns."""
    proj, epic = _make_project(EPIC_WITH_FM)
    event = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(epic), "content": EPIC_NO_FM},
    }
    ctx = _run_guard(proj, event)
    assert "no YAML frontmatter" in ctx, f"expected missing-frontmatter warning, got: {ctx!r}"


def test_edit_body_when_file_truly_lacks_frontmatter_is_flagged() -> None:
    """If the file on disk really has no frontmatter, editing its body should
    still warn — reconstruction must not mask real problems."""
    proj, epic = _make_project(EPIC_NO_FM)
    event = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(epic),
            "old_string": "沒有 frontmatter",
            "new_string": "仍然沒有 frontmatter",
        },
    }
    ctx = _run_guard(proj, event)
    assert "no YAML frontmatter" in ctx, f"expected missing-frontmatter warning, got: {ctx!r}"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    total = len(tests)
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
