#!/usr/bin/env python3
"""Phase 14 regression checks for kanban v0.3.7 — resolve-doc-link.

The cross-plugin (kanban × mentor) helper that turns a repo-relative
doc path into a clickable GitHub URL for Jira comments.

Cases:
  (a) _parse_github_origin: HTTPS form (with / without .git suffix)
  (b) _parse_github_origin: SSH form (git@github.com:owner/repo.git)
  (c) _parse_github_origin: non-GitHub returns None
  (d) _parse_github_origin: malformed returns None
  (e) cmd_resolve_doc_link: real git repo with GitHub origin → returns
       /blob/<branch>/<path> URL
  (f) cmd_resolve_doc_link: doc-path leading slashes / ./ stripped
  (g) cmd_resolve_doc_link: doc-path with `..` rejected
  (h) cmd_resolve_doc_link: file existence reflected in `exists` flag
  (i) cmd_resolve_doc_link: --branch override beats current branch
  (j) cmd_resolve_doc_link: missing origin → ok=false with clear error
  (k) cmd_resolve_doc_link: non-GitHub origin → ok=false, host=other
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

_spec = importlib.util.spec_from_file_location(
    "jira_setup_mod", str(PLUGIN / "scripts" / "jira_setup.py")
)
_jira_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_jira_setup)  # type: ignore[union-attr]


# --- _parse_github_origin ----------------------------------------------


def test_parse_origin_https_variants():
    fn = _jira_setup._parse_github_origin
    assert fn("https://github.com/owner/repo") == ("owner", "repo")
    assert fn("https://github.com/owner/repo.git") == ("owner", "repo")
    assert fn("https://github.com/owner/repo/") == ("owner", "repo")
    assert fn("http://github.com/owner/repo.git") == ("owner", "repo")


def test_parse_origin_ssh_variants():
    fn = _jira_setup._parse_github_origin
    assert fn("git@github.com:owner/repo.git") == ("owner", "repo")
    assert fn("git@github.com:owner/repo") == ("owner", "repo")


def test_parse_origin_non_github():
    fn = _jira_setup._parse_github_origin
    assert fn("https://gitlab.com/owner/repo.git") is None
    assert fn("git@bitbucket.org:owner/repo.git") is None
    assert fn("https://internal.dev/owner/repo") is None


def test_parse_origin_malformed():
    fn = _jira_setup._parse_github_origin
    assert fn("") is None
    assert fn("not-a-url") is None
    assert fn("https://github.com") is None
    assert fn(None) is None  # type: ignore[arg-type]


# --- cmd_resolve_doc_link integration ----------------------------------


def _init_repo_with_origin(td: pathlib.Path, origin: str) -> pathlib.Path:
    """Create an empty git repo at `td` and set its origin URL."""
    subprocess.run(["git", "init", "-q", "-b", "main", str(td)], check=True)
    subprocess.run(
        ["git", "-C", str(td), "remote", "add", "origin", origin], check=True
    )
    # Configure user so commits work (we only test pre-commit branches but
    # branch detection needs at least one commit on some git versions)
    subprocess.run(
        ["git", "-C", str(td), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(td), "config", "user.name", "test"], check=True
    )
    # Empty initial commit so `branch --show-current` returns 'main'
    subprocess.run(
        ["git", "-C", str(td), "commit", "--allow-empty", "-m", "init", "-q"],
        check=True,
    )
    return td


def _seed_kanban(repo: pathlib.Path) -> pathlib.Path:
    p = repo / "kanban.json"
    p.write_text(json.dumps({
        "version": "0.2",
        "backend": {"driver": "jira", "jira": {"projectKey": "AGENT"}},
        "meta": {"priorities": ["P0"], "categories": [],
                 "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED"],
                 "created_at": "x", "updated_at": "x"},
        "tasks": [],
    }))
    return p


def _capture(fn, args):
    from io import StringIO
    old = sys.stdout
    sys.stdout = StringIO()
    try:
        try:
            rc = fn(args)
        except SystemExit as e:
            rc = e.code
        out = sys.stdout.getvalue()
    finally:
        sys.stdout = old
    return rc, out


def test_resolve_happy_path():
    with tempfile.TemporaryDirectory() as td:
        repo = pathlib.Path(td)
        _init_repo_with_origin(repo, "https://github.com/kirinchen/claude-workbench.git")
        kp = _seed_kanban(repo)

        class A:
            kanban_path = str(kp)
            doc_path = "epic/AGENT-001-foo.md"
            branch = None

        rc, out = _capture(_jira_setup.cmd_resolve_doc_link, A())
        assert rc == 0
        j = json.loads(out)
        assert j["ok"] is True
        assert j["host"] == "github"
        assert j["owner"] == "kirinchen"
        assert j["repo"] == "claude-workbench"
        assert j["branch"] == "main"
        assert j["url"] == (
            "https://github.com/kirinchen/claude-workbench/blob/main/"
            "epic/AGENT-001-foo.md"
        )
        assert j["exists"] is False  # we didn't create the file


def test_resolve_strips_leading_slashes():
    with tempfile.TemporaryDirectory() as td:
        repo = pathlib.Path(td)
        _init_repo_with_origin(repo, "git@github.com:owner/repo.git")
        kp = _seed_kanban(repo)

        class A:
            kanban_path = str(kp)
            doc_path = "/epic/X.md"  # leading slash stripped
            branch = None
        rc, out = _capture(_jira_setup.cmd_resolve_doc_link, A())
        assert rc == 0
        j = json.loads(out)
        assert j["url"].endswith("/blob/main/epic/X.md")

        class B(A):
            doc_path = "./epic/X.md"  # ./ also stripped
        rc, out = _capture(_jira_setup.cmd_resolve_doc_link, B())
        j = json.loads(out)
        assert j["url"].endswith("/blob/main/epic/X.md")


def test_resolve_rejects_traversal():
    with tempfile.TemporaryDirectory() as td:
        repo = pathlib.Path(td)
        _init_repo_with_origin(repo, "https://github.com/owner/repo")
        kp = _seed_kanban(repo)

        class A:
            kanban_path = str(kp)
            doc_path = "epic/../../../etc/passwd"
            branch = None
        rc, out = _capture(_jira_setup.cmd_resolve_doc_link, A())
        assert rc != 0
        j = json.loads(out)
        assert j["ok"] is False


def test_resolve_exists_flag_reflects_filesystem():
    with tempfile.TemporaryDirectory() as td:
        repo = pathlib.Path(td)
        _init_repo_with_origin(repo, "https://github.com/owner/repo.git")
        kp = _seed_kanban(repo)
        # Create the doc file
        (repo / "epic").mkdir()
        (repo / "epic" / "real.md").write_text("# real")

        class A:
            kanban_path = str(kp)
            doc_path = "epic/real.md"
            branch = None
        rc, out = _capture(_jira_setup.cmd_resolve_doc_link, A())
        j = json.loads(out)
        assert j["exists"] is True

        class B(A):
            doc_path = "epic/missing.md"
        rc, out = _capture(_jira_setup.cmd_resolve_doc_link, B())
        j = json.loads(out)
        assert j["exists"] is False


def test_resolve_branch_override():
    with tempfile.TemporaryDirectory() as td:
        repo = pathlib.Path(td)
        _init_repo_with_origin(repo, "https://github.com/owner/repo")
        kp = _seed_kanban(repo)

        class A:
            kanban_path = str(kp)
            doc_path = "epic/X.md"
            branch = "release/v2"
        rc, out = _capture(_jira_setup.cmd_resolve_doc_link, A())
        j = json.loads(out)
        assert j["branch"] == "release/v2"
        assert "/blob/release/v2/epic/X.md" in j["url"]


def test_resolve_no_origin():
    with tempfile.TemporaryDirectory() as td:
        repo = pathlib.Path(td)
        # Initialise but don't add an origin
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        kp = _seed_kanban(repo)

        class A:
            kanban_path = str(kp)
            doc_path = "epic/X.md"
            branch = None
        rc, out = _capture(_jira_setup.cmd_resolve_doc_link, A())
        assert rc != 0
        j = json.loads(out)
        assert j["ok"] is False
        assert "git origin" in j["error"].lower()


def test_resolve_non_github():
    with tempfile.TemporaryDirectory() as td:
        repo = pathlib.Path(td)
        _init_repo_with_origin(repo, "https://gitlab.com/owner/repo.git")
        kp = _seed_kanban(repo)

        class A:
            kanban_path = str(kp)
            doc_path = "epic/X.md"
            branch = None
        rc, out = _capture(_jira_setup.cmd_resolve_doc_link, A())
        assert rc != 0
        j = json.loads(out)
        assert j["ok"] is False
        assert j["host"] == "other"
        assert "github.com" in j["error"]


def test_resolve_empty_doc_path():
    with tempfile.TemporaryDirectory() as td:
        repo = pathlib.Path(td)
        _init_repo_with_origin(repo, "https://github.com/owner/repo")
        kp = _seed_kanban(repo)

        class A:
            kanban_path = str(kp)
            doc_path = ""
            branch = None
        rc, out = _capture(_jira_setup.cmd_resolve_doc_link, A())
        assert rc != 0


def main() -> int:
    cases = [
        ("parse_origin_https_variants", test_parse_origin_https_variants),
        ("parse_origin_ssh_variants", test_parse_origin_ssh_variants),
        ("parse_origin_non_github", test_parse_origin_non_github),
        ("parse_origin_malformed", test_parse_origin_malformed),
        ("resolve_happy_path", test_resolve_happy_path),
        ("resolve_strips_leading_slashes", test_resolve_strips_leading_slashes),
        ("resolve_rejects_traversal", test_resolve_rejects_traversal),
        ("resolve_exists_flag_reflects_filesystem",
         test_resolve_exists_flag_reflects_filesystem),
        ("resolve_branch_override", test_resolve_branch_override),
        ("resolve_no_origin", test_resolve_no_origin),
        ("resolve_non_github", test_resolve_non_github),
        ("resolve_empty_doc_path", test_resolve_empty_doc_path),
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
    print("phase14: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
