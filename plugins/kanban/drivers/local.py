"""LocalDriver — kanban.json-backed implementation of the Driver Protocol.

Behaviour mirrors v0.1.x exactly. AP capabilities are not supported.
The slash commands continue to use Read/Write tools directly for state
mutation; this driver exists so future code (hooks, /kanban:status, jira
parity) can read kanban.json through one canonical path.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib import kanban_io
from lib import transitions as _tr
from drivers.base import (
    AgentRef,
    Comment,
    CommentKind,
    Driver,
    HealthResult,
    HealthStatus,
    HumanRef,
    Member,
    MemberRef,
    NotSupported,
    Task,
    TaskFilter,
    TaskInput,
)


LOCAL_COLUMNS = ("TODO", "DOING", "APPROVED", "BLOCKED")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _next_task_id(tasks: list[dict[str, Any]]) -> str:
    nums = []
    for t in tasks:
        tid = t.get("id", "")
        if tid.startswith("task-"):
            try:
                nums.append(int(tid[5:]))
            except ValueError:
                pass
    n = (max(nums) + 1) if nums else 1
    return f"task-{n:03d}"


def _to_task(raw: dict[str, Any]) -> Task:
    assignee = raw.get("assignee")
    member: MemberRef | None
    if assignee:
        # Local mode does not distinguish human vs agent; treat as human by default.
        member = HumanRef(accountId=assignee)
    else:
        member = None
    return Task(
        id=raw["id"],
        title=raw["title"],
        column=raw["column"],
        priority=raw.get("priority", ""),
        created=raw["created"],
        updated=raw["updated"],
        description=raw.get("description", ""),
        category=raw.get("category"),
        tags=list(raw.get("tags") or []),
        depends=list(raw.get("depends") or []),
        started=raw.get("started"),
        completed=raw.get("completed"),
        assignee=member,
        comments=[
            Comment(author=c["author"], ts=c["ts"], text=c["text"])
            for c in (raw.get("comments") or [])
        ],
        custom=dict(raw.get("custom") or {}),
    )


class LocalDriver:
    name = "local"

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.path = self.project_root / "kanban.json"

    # --- helpers -------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        return kanban_io.load(self.path)

    def _save(self, data: dict[str, Any]) -> None:
        data.setdefault("meta", {})["updated_at"] = _now()
        kanban_io.save(self.path, data)

    def _find(self, data: dict[str, Any], key: str) -> dict[str, Any]:
        for t in data.get("tasks", []):
            if t.get("id") == key:
                return t
        raise KeyError(f"task {key!r} not found")

    # --- Driver Protocol ----------------------------------------------

    def health(self) -> HealthResult:
        if not self.path.exists():
            return HealthResult(HealthStatus.UNREACHABLE, "kanban.json missing")
        try:
            self._load()
        except Exception as e:
            return HealthResult(HealthStatus.DEGRADED, f"parse error: {e}")
        return HealthResult(HealthStatus.OK)

    def list_tasks(self, filter: TaskFilter | None = None) -> list[Task]:
        data = self._load()
        out = [_to_task(t) for t in data.get("tasks", [])]
        if filter is None:
            return out
        if filter.column:
            out = [t for t in out if t.column == filter.column]
        if filter.assignee:
            out = [
                t
                for t in out
                if t.assignee
                and getattr(t.assignee, "accountId", None) == filter.assignee
            ]
        if filter.priority:
            out = [t for t in out if t.priority == filter.priority]
        if filter.category:
            out = [t for t in out if t.category == filter.category]
        if filter.limit:
            out = out[: filter.limit]
        return out

    def get_task(self, key: str) -> Task:
        data = self._load()
        return _to_task(self._find(data, key))

    def create_task(self, task: TaskInput) -> Task:
        data = self._load()
        tasks = data.setdefault("tasks", [])
        ts = _now()
        new_id = _next_task_id(tasks)
        raw: dict[str, Any] = {
            "id": new_id,
            "title": task.title,
            "column": "TODO",
            "priority": task.priority or "P2",
            "created": ts,
            "updated": ts,
            "description": task.description,
            "category": task.category,
            "tags": list(task.tags),
            "depends": list(task.depends),
            "started": None,
            "completed": None,
            "assignee": (
                getattr(task.assignee, "accountId", None)
                if task.assignee and task.assignee.kind == "human"
                else None
            ),
            "comments": [],
            "custom": dict(task.custom),
        }
        tasks.append(raw)
        self._save(data)
        return _to_task(raw)

    def transition(self, key: str, to_column: str, **kwargs: Any) -> Task:
        # Alias legacy DONE → APPROVED (#48). Internal storage and checks
        # only see the canonical name; CLI / slash command surfaces emit
        # a deprecation warning before reaching here.
        to_column = _tr.normalize_canonical(to_column)
        if to_column not in LOCAL_COLUMNS:
            raise ValueError(
                f"local driver only supports {LOCAL_COLUMNS}; got {to_column!r}"
            )
        data = self._load()
        raw = self._find(data, key)
        # Compare against the normalised stored value; older kanban.json
        # files load with column="DONE" rewritten to "APPROVED" by
        # kanban_io._normalize_legacy_columns.
        if raw["column"] == "APPROVED":
            raise ValueError("APPROVED is terminal — cannot transition")
        ts = _now()
        raw["column"] = to_column
        raw["updated"] = ts
        if to_column == "DOING" and not raw.get("started"):
            raw["started"] = ts
        if to_column == "APPROVED":
            raw["completed"] = ts
            if not raw.get("started"):
                raw["started"] = ts
        if to_column == "BLOCKED":
            reason = kwargs.get("reason")
            if not reason:
                raise ValueError("transition to BLOCKED requires reason=...")
            raw.setdefault("custom", {})["blocked_reason"] = reason
        self._save(data)
        return _to_task(raw)

    def post_comment(
        self, key: str, body: str, kind: CommentKind = CommentKind.COMMENT
    ) -> Comment:
        data = self._load()
        raw = self._find(data, key)
        ts = _now()
        author = "claude-code"
        comment = {"author": author, "ts": ts, "text": body}
        raw.setdefault("comments", []).append(comment)
        raw["updated"] = ts
        self._save(data)
        return Comment(author=author, ts=ts, text=body, kind=kind)

    def list_comments(self, key: str) -> list[Comment]:
        return self.get_task(key).comments

    def assign(self, key: str, member: MemberRef) -> Task:
        data = self._load()
        raw = self._find(data, key)
        if member.kind == "human":
            raw["assignee"] = member.accountId  # type: ignore[union-attr]
        else:
            raw["assignee"] = member.ap  # type: ignore[union-attr]
        raw["updated"] = _now()
        self._save(data)
        return _to_task(raw)

    def list_members(self) -> list[Member]:
        # Local mode has no member directory; return empty.
        return []

    def list_aps(self) -> list[str]:
        raise NotSupported("local driver does not support agent properties")

    def register_ap(self, name: str) -> None:
        raise NotSupported("local driver does not support agent properties")

    # Mutation primitives (#55) — local mode edits kanban.json directly,
    # so a slash-command wrapper for these would just duplicate Edit on
    # the file. Stubs raise NotSupported until/unless a use case appears.
    def update_description(self, key: str, description: str) -> Task:
        raise NotSupported(
            "update_description is jira-only; edit kanban.json directly in local mode"
        )

    def update_summary(self, key: str, summary: str) -> Task:
        raise NotSupported(
            "update_summary is jira-only; edit kanban.json directly in local mode"
        )

    def update_labels(
        self, key: str, *, add: list[str] | None = None, remove: list[str] | None = None
    ) -> Task:
        raise NotSupported(
            "update_labels is jira-only; edit kanban.json directly in local mode"
        )

    def delete_issue(self, key: str, *, cascade: bool = False) -> None:
        raise NotSupported(
            "delete_issue is jira-only; edit kanban.json directly in local mode"
        )
