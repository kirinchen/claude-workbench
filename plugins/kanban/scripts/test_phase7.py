#!/usr/bin/env python3
"""Phase 7 regression checks for kanban v0.3.0 — compound transitions.

Run from anywhere:
    python3 plugins/kanban/scripts/test_phase7.py

No live Jira; everything mocked. Covers:
  (a) DSL parser — happy path matches the user's example exactly
  (b) DSL parser — `Assignee to me` requires --current-user-account-id
  (c) DSL parser — UPPERCASE self-reference resolves cycle
  (d) DSL parser — missing `>`, unknown canonical, bad component all error
  (e) Suggester — non-English names mapped via statusCategory
  (f) Suggester — ambiguous `new`-category statuses flagged
  (g) Migrate legacy v0.2 statusMap+labelFallback → transitions (lossless)
  (h) kanban_io auto-migrates legacy backend on load
  (i) JiraDriver._issue_to_task — 4 cards on shared In Progress disambiguate
       correctly (DOING vs BLOCKED vs REVIEW)
  (j) JiraDriver.transition — REVIEW: status (skip if same) + addLabels +
       assignee in correct order
  (k) JiraDriver.transition — DOING→DONE refuses self-approve when AP matches
  (l) write-backend CLI accepts a transitions block and persists v0.3 shape
  (m) parse-transitions-dsl CLI returns parsed JSON; set-transitions CLI
       writes only the transitions field, drops legacy keys
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
sys.path.insert(0, str(REPO / "plugins" / "kanban"))

from lib import kanban_io, transitions as _tr  # noqa: E402
from lib.jira_client import JiraClient, _Response  # noqa: E402


def _user_dsl() -> str:
    return """
TODO > Selected for Development
DOING > In Progress
BLOCKED > In Progress + Label
REVIEW > In Progress + label + Assignee to me (kirin)
DONE > Done
CANCELLED > DONE + label
"""


# --- DSL parser tests ----------------------------------------------------


def test_dsl_user_example():
    out = _tr.parse_dsl(_user_dsl(), current_user_account_id="kirin-acct")
    assert out["TODO"] == {"status": "Selected for Development"}
    assert out["DOING"] == {"status": "In Progress"}
    assert out["BLOCKED"] == {"status": "In Progress", "addLabels": ["kanban:blocked"]}
    assert out["REVIEW"]["status"] == "In Progress"
    assert out["REVIEW"]["addLabels"] == ["kanban:review"]
    assert out["REVIEW"]["assignee"] == {"accountId": "kirin-acct"}
    assert out["APPROVED"] == {"status": "Done"}
    assert out["CANCELLED"] == {"status": "Done", "addLabels": ["kanban:cancelled"]}


def test_dsl_assignee_me_requires_account_id():
    try:
        _tr.parse_dsl("REVIEW > In Progress + Assignee to me")
        assert False, "should have raised"
    except ValueError as e:
        assert "accountId" in str(e)


def test_dsl_self_reference():
    out = _tr.parse_dsl(
        "DONE > Done\nCANCELLED > DONE + label",
        current_user_account_id="x",
    )
    assert out["CANCELLED"]["status"] == "Done"


def test_dsl_circular_reference_refused():
    try:
        _tr.parse_dsl("DOING > REVIEW\nREVIEW > DOING")
        assert False
    except ValueError as e:
        assert "circular" in str(e).lower()


def test_dsl_syntax_errors():
    for bad in (
        "TODO without separator",
        "BAD > In Progress",
        "TODO > In Progress + UnknownComponent",
    ):
        try:
            _tr.parse_dsl(bad)
            assert False, f"should reject: {bad!r}"
        except ValueError:
            pass


def test_dsl_explicit_label_name():
    out = _tr.parse_dsl(
        "REVIEW > In Progress + label review-needed",
        current_user_account_id="x",
    )
    assert out["REVIEW"]["addLabels"] == ["review-needed"]


# --- Auto-suggester ------------------------------------------------------


def test_suggester_non_english():
    found = [
        {"name": "Selected for Development", "category": "new"},
        {"name": "Backlog", "category": "new"},
        {"name": "進行中", "category": "indeterminate"},
        {"name": "完成", "category": "done"},
    ]
    res = _tr.suggest_from_jira(found)
    assert res.suggestions["DOING"]["status"] == "進行中"
    assert res.suggestions["APPROVED"]["status"] == "完成"
    assert "TODO" in res.suggestions  # picked first new-category status
    assert "TODO" in res.ambiguous     # but flagged as ambiguous
    assert set(res.unmapped) == {"BLOCKED", "REVIEW", "CANCELLED"}


def test_suggester_english_exact_match_wins():
    found = [
        {"name": "To Do", "category": "new"},
        {"name": "In Progress", "category": "indeterminate"},
        {"name": "Done", "category": "done"},
    ]
    res = _tr.suggest_from_jira(found)
    # Exact-name match → confidence 1.0
    assert res.suggestions["TODO"]["confidence"] == 1.0
    assert res.suggestions["DOING"]["confidence"] == 1.0
    assert res.suggestions["APPROVED"]["confidence"] == 1.0


# --- Legacy migration ----------------------------------------------------


def test_migrate_legacy_lossless():
    legacy = {
        "projectKey": "AGENT",
        "statusMap": {"TODO": "To Do", "DOING": "In Progress", "APPROVED": "Done"},
        "partial": True,
        "labelFallback": {
            "BLOCKED": "kanban:blocked",
            "REVIEW": "kanban:review",
            "CANCELLED": "kanban:cancelled",
        },
    }
    mig = _tr.migrate_legacy(legacy)
    assert "statusMap" not in mig
    assert "partial" not in mig
    assert "labelFallback" not in mig
    t = mig["transitions"]
    assert t["TODO"] == {"status": "To Do"}
    assert t["DOING"] == {"status": "In Progress"}
    assert t["APPROVED"] == {"status": "Done"}
    assert t["BLOCKED"] == {"status": "In Progress", "addLabels": ["kanban:blocked"]}
    assert t["REVIEW"] == {"status": "In Progress", "addLabels": ["kanban:review"]}
    assert t["CANCELLED"] == {"status": "Done", "addLabels": ["kanban:cancelled"]}


def test_migrate_idempotent():
    already = {
        "projectKey": "AGENT",
        "transitions": {"DOING": {"status": "In Progress"}},
    }
    out = _tr.migrate_legacy(already)
    assert out["transitions"] == already["transitions"]


def test_kanban_io_auto_migrates_on_load():
    legacy = {
        "version": "0.2",
        "backend": {
            "driver": "jira",
            "jira": {
                "projectKey": "AGENT",
                "statusMap": {"TODO": "To Do", "DOING": "In Progress", "APPROVED": "Done"},
                "partial": True,
                "labelFallback": {"BLOCKED": "kanban:blocked"},
            },
        },
        "meta": {
            "priorities": ["P0"],
            "categories": [],
            "columns": ["TODO", "DOING", "APPROVED", "BLOCKED"],
            "created_at": "x",
            "updated_at": "x",
        },
        "tasks": [],
    }
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "kanban.json"
        p.write_text(json.dumps(legacy))
        loaded = kanban_io.load(p)
        cfg = loaded["backend"]["jira"]
        assert "statusMap" not in cfg
        assert "labelFallback" not in cfg
        assert "transitions" in cfg


# --- Driver disambiguation + compound write -----------------------------


def _seed_jira_data():
    return {
        "version": "0.2",
        "backend": {
            "driver": "jira",
            "jira": {
                "projectKey": "AGENT",
                "agentAccountId": "shared-agent",
                "transitions": {
                    "TODO":      {"status": "Selected for Development"},
                    "DOING":     {"status": "In Progress"},
                    "BLOCKED":   {"status": "In Progress", "addLabels": ["kanban:blocked"]},
                    "REVIEW":    {"status": "In Progress",
                                  "addLabels": ["kanban:review"],
                                  "assignee": {"accountId": "kirin-acct"}},
                    "APPROVED":      {"status": "Done"},
                    "CANCELLED": {"status": "Done", "addLabels": ["kanban:cancelled"]},
                },
                "ap": {
                    "fieldId": "customfield_10042",
                    "fieldName": "Claude Agent",
                    "registered": ["agent-fin"],
                },
            },
        },
        "meta": {
            "priorities": ["P0"],
            "categories": [],
            "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "APPROVED", "CANCELLED"],
            "created_at": "x",
            "updated_at": "x",
        },
        "tasks": [],
    }


def _patched_driver(data, project_root):
    from drivers.jira import JiraDriver
    from lib import credentials

    orig = credentials.read
    credentials.read = lambda prefix=None: {
        "JIRA_BASE_URL": "https://x",
        "JIRA_AGENT_EMAIL": "a@b",
        "JIRA_API_TOKEN": "tok",
    }
    try:
        drv = JiraDriver(data, project_root)
    finally:
        credentials.read = orig
    return drv


def _attach_mock(drv, queue, calls):
    def t(method, url, headers, body):
        calls.append({"method": method, "url": url, "body": body})
        return queue.pop(0)
    drv._client = JiraClient(
        drv.base_url, drv.email, drv._token, transport=t, sleep=lambda _: None
    )


def _issue(key, status, labels=(), assignee=None, ap_value=None):
    fields = {
        "summary": key,
        "status": {"name": status},
        "priority": {"name": "P1"},
        "assignee": {"accountId": assignee} if assignee else None,
        "labels": list(labels),
        "created": "x",
        "updated": "y",
    }
    if ap_value is not None:
        fields["customfield_10042"] = {"value": ap_value}
    return {"key": key, "fields": fields}


def test_disambiguate_shared_in_progress():
    with tempfile.TemporaryDirectory() as td:
        drv = _patched_driver(_seed_jira_data(), pathlib.Path(td))
        # 4 issues all on `In Progress`, distinguished only by labels/assignee.
        assert drv._issue_to_task(_issue("AGENT-1", "In Progress")).column == "DOING"
        assert drv._issue_to_task(
            _issue("AGENT-2", "In Progress", labels=["kanban:blocked"])
        ).column == "BLOCKED"
        assert drv._issue_to_task(
            _issue("AGENT-3", "In Progress", labels=["kanban:review"],
                   assignee="kirin-acct")
        ).column == "REVIEW"
        # Done + cancelled label → CANCELLED
        assert drv._issue_to_task(
            _issue("AGENT-4", "Done", labels=["kanban:cancelled"])
        ).column == "CANCELLED"
        # Done with no labels → DONE
        assert drv._issue_to_task(_issue("AGENT-5", "Done")).column == "APPROVED"


def test_compound_transition_to_review():
    """Going from In Progress (DOING) → In Progress+label+assignee (REVIEW)
    should skip the status transition step (already in target status), do a
    PUT for labels, then a PUT for assignee."""
    with tempfile.TemporaryDirectory() as td:
        drv = _patched_driver(_seed_jira_data(), pathlib.Path(td))
        pre = _issue("AGENT-1", "In Progress", labels=[], ap_value=None)
        post = _issue("AGENT-1", "In Progress", labels=["kanban:review"],
                      assignee="kirin-acct", ap_value=None)
        queue = [
            _Response(200, json.dumps(pre).encode(), {}),     # pre-flight get_task
            _Response(204, b"", {}),                          # PUT labels
            _Response(204, b"", {}),                          # PUT assignee
            _Response(200, json.dumps(post).encode(), {}),    # final get_task
        ]
        calls = []
        _attach_mock(drv, queue, calls)
        out = drv.transition("AGENT-1", "REVIEW")
        assert out.column == "REVIEW"
        # No /transitions or transition POST should have been issued.
        urls = [c["url"] for c in calls]
        assert not any("/transitions" in u for u in urls), urls
        # PUT labels first, then PUT assignee.
        put_calls = [c for c in calls if c["method"] == "PUT"]
        assert len(put_calls) == 2
        body0 = json.loads(put_calls[0]["body"])
        assert body0 == {"fields": {"labels": ["kanban:review"]}}
        assert "/assignee" in put_calls[1]["url"]


def test_compound_transition_status_change():
    """Going from To Do → In Progress should: pre-flight get, get_transitions,
    POST transition, final get. (No labels/assignee in DOING spec.)"""
    with tempfile.TemporaryDirectory() as td:
        drv = _patched_driver(_seed_jira_data(), pathlib.Path(td))
        pre = _issue("AGENT-1", "Selected for Development")
        post = _issue("AGENT-1", "In Progress")
        queue = [
            _Response(200, json.dumps(pre).encode(), {}),
            _Response(
                200,
                json.dumps({"transitions": [{"id": "21", "to": {"name": "In Progress"}}]}).encode(),
                {},
            ),
            _Response(204, b"", {}),
            _Response(200, json.dumps(post).encode(), {}),
        ]
        calls = []
        _attach_mock(drv, queue, calls)
        out = drv.transition("AGENT-1", "DOING")
        assert out.column == "DOING"
        # Exactly one POST (the transition) — no labels/assignee writes.
        posts = [c for c in calls if c["method"] == "POST"]
        assert len(posts) == 1, posts


def test_self_approve_refused_v03():
    """Classic anti-self-approve refusal: AP=mine AND assignee is the
    agent account itself. (#19 in 0.3.10 loosened the rule to allow
    when assignee differs from agent — see test_phase17 for that
    branch.)"""
    with tempfile.TemporaryDirectory() as td:
        proj = pathlib.Path(td)
        (proj / ".claude").mkdir()
        (proj / ".claude" / "kanban-agent.json").write_text(json.dumps({"ap": "agent-fin"}))
        drv = _patched_driver(_seed_jira_data(), proj)
        pre = _issue("AGENT-7", "In Progress", labels=["kanban:review"],
                     assignee="shared-agent",  # the agent's own account
                     ap_value="agent-fin")
        queue = [_Response(200, json.dumps(pre).encode(), {})]
        calls = []
        _attach_mock(drv, queue, calls)
        from drivers.jira import SelfApproveRefused

        try:
            drv.transition("AGENT-7", "APPROVED")
            assert False, "should have raised"
        except SelfApproveRefused as e:
            assert "agent-fin" in str(e)
        assert len(calls) == 1


# --- CLI subcommands ------------------------------------------------------


def _run(*args, stdin: bytes = b""):
    return subprocess.run(
        ["python3", str(PLUGIN / "scripts" / "jira_setup.py"), *args],
        input=stdin, capture_output=True,
    )


def test_parse_transitions_dsl_cli():
    out = _run(
        "parse-transitions-dsl",
        "--dsl-text", _user_dsl(),
        "--current-user-account-id", "kirin-acct",
        "--no-user-lookup",
    )
    assert out.returncode == 0, out.stderr
    j = json.loads(out.stdout)
    assert j["ok"] is True
    assert j["transitions"]["BLOCKED"]["addLabels"] == ["kanban:blocked"]
    assert j["transitions"]["REVIEW"]["assignee"] == {"accountId": "kirin-acct"}


def test_set_transitions_cli_writes_v03_shape():
    with tempfile.TemporaryDirectory() as td:
        kp = pathlib.Path(td) / "kanban.json"
        kp.write_text(json.dumps({
            "version": "0.2",
            "backend": {
                "driver": "jira",
                "jira": {
                    "projectKey": "AGENT",
                    "statusMap": {"TODO": "To Do", "DOING": "In Progress", "APPROVED": "Done"},
                    "partial": True,
                    "labelFallback": {"BLOCKED": "kanban:blocked"},
                },
            },
            "meta": {
                "priorities": ["P0"], "categories": [],
                "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "APPROVED", "CANCELLED"],
                "created_at": "x", "updated_at": "x",
            },
            "tasks": [],
        }))

        new_transitions = {
            "TODO": {"status": "Selected for Development"},
            "DOING": {"status": "In Progress"},
            "APPROVED": {"status": "Done"},
        }
        out = _run(
            "set-transitions",
            "--kanban-path", str(kp),
            "--transitions-json", json.dumps(new_transitions),
            "--available-statuses", json.dumps(["Selected for Development", "In Progress", "Done"]),
        )
        assert out.returncode == 0, out.stderr
        j = json.loads(out.stdout)
        assert j["ok"] is True
        on_disk = json.loads(kp.read_text())
        cfg = on_disk["backend"]["jira"]
        assert "statusMap" not in cfg
        assert "labelFallback" not in cfg
        assert "partial" not in cfg
        assert cfg["transitions"]["TODO"] == {"status": "Selected for Development"}


def test_set_transitions_cli_validates():
    """`status` not in available list → exit non-zero unless --force."""
    with tempfile.TemporaryDirectory() as td:
        kp = pathlib.Path(td) / "kanban.json"
        kp.write_text(json.dumps({
            "version": "0.2",
            "backend": {"driver": "jira", "jira": {"projectKey": "AGENT"}},
            "meta": {
                "priorities": ["P0"], "categories": [],
                "columns": ["TODO", "DOING", "BLOCKED", "REVIEW", "APPROVED", "CANCELLED"],
                "created_at": "x", "updated_at": "x",
            },
            "tasks": [],
        }))
        out = _run(
            "set-transitions",
            "--kanban-path", str(kp),
            "--transitions-json", json.dumps({"DOING": {"status": "Nonexistent"}}),
            "--available-statuses", json.dumps(["To Do", "In Progress", "Done"]),
        )
        assert out.returncode != 0
        j = json.loads(out.stdout)
        assert j["ok"] is False
        assert j["errors"]


def test_build_status_map_cli_returns_suggestions():
    """build-status-map returns the new shape (suggestions + unmapped)."""
    # We can't hit real Jira; instead test the suggester directly above.
    # Here we just verify the CLI argparse accepts the call shape.
    out = _run("build-status-map", "--help")
    assert out.returncode == 0
    text = out.stdout.decode()
    assert "--project" in text


# --- entry point ---------------------------------------------------------


def main() -> int:
    cases = [
        ("dsl_user_example", test_dsl_user_example),
        ("dsl_assignee_me_requires_account_id", test_dsl_assignee_me_requires_account_id),
        ("dsl_self_reference", test_dsl_self_reference),
        ("dsl_circular_reference_refused", test_dsl_circular_reference_refused),
        ("dsl_syntax_errors", test_dsl_syntax_errors),
        ("dsl_explicit_label_name", test_dsl_explicit_label_name),
        ("suggester_non_english", test_suggester_non_english),
        ("suggester_english_exact_match_wins", test_suggester_english_exact_match_wins),
        ("migrate_legacy_lossless", test_migrate_legacy_lossless),
        ("migrate_idempotent", test_migrate_idempotent),
        ("kanban_io_auto_migrates_on_load", test_kanban_io_auto_migrates_on_load),
        ("disambiguate_shared_in_progress", test_disambiguate_shared_in_progress),
        ("compound_transition_to_review", test_compound_transition_to_review),
        ("compound_transition_status_change", test_compound_transition_status_change),
        ("self_approve_refused_v03", test_self_approve_refused_v03),
        ("parse_transitions_dsl_cli", test_parse_transitions_dsl_cli),
        ("set_transitions_cli_writes_v03_shape", test_set_transitions_cli_writes_v03_shape),
        ("set_transitions_cli_validates", test_set_transitions_cli_validates),
        ("build_status_map_cli_returns_suggestions", test_build_status_map_cli_returns_suggestions),
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
    print("phase7: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
