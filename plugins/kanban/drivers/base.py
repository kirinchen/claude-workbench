"""Driver Protocol — defines the contract every storage backend must satisfy.

Phase 1 lands the Protocol and dataclasses; only `local` is implemented.
Phase 2 adds `jira`. Optional capabilities (list_aps, register_ap) raise
NotSupported on drivers that don't implement them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Protocol, Union


class CommentKind(str, Enum):
    """Maps to the SPEC §9 comment-prefix grammar (Q/A/C/S)."""
    QUESTION = "Q"
    ANSWER = "A"
    COMMENT = "C"
    SYSTEM = "S"


class HealthStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    UNAUTHENTICATED = "unauthenticated"


@dataclass
class HealthResult:
    status: HealthStatus
    detail: str = ""


@dataclass
class HumanRef:
    accountId: str
    kind: Literal["human"] = "human"


@dataclass
class AgentRef:
    ap: str
    kind: Literal["agent"] = "agent"


MemberRef = Union[HumanRef, AgentRef]


@dataclass
class Member:
    """Returned from list_members. Drivers may leave fields empty if unknown."""
    ref: MemberRef
    displayName: str = ""
    email: str = ""


@dataclass
class TaskFilter:
    """Common query knobs. Drivers translate to JQL / dict filtering."""
    column: str | None = None          # e.g. "TODO" or Jira-mapped status
    ap: str | None = None              # restrict to one agent property
    assignee: str | None = None        # human accountId or local string
    priority: str | None = None        # at-or-above (driver-specific ordering)
    category: str | None = None
    limit: int | None = None


@dataclass
class TaskInput:
    """For create_task. Required fields per driver may differ."""
    title: str
    description: str = ""
    priority: str | None = None
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    depends: list[str] = field(default_factory=list)
    assignee: MemberRef | None = None
    custom: dict[str, Any] = field(default_factory=dict)
    # Jira-only: when set, the new issue is linked back to the parent via
    # an issue link of `link_type` (default "Relates"). Used by
    # /kanban:create-sub to spawn breakdown cards from a parent.
    parent_key: str | None = None
    link_type: str = "Relates"


@dataclass
class Comment:
    author: str          # for jira: human displayName or AP if agent
    ts: str              # ISO 8601
    text: str
    kind: CommentKind = CommentKind.COMMENT


@dataclass
class Task:
    """Driver-neutral task record. id is `task-NNN` (local) or `KEY-N` (jira)."""
    id: str
    title: str
    column: str
    priority: str
    created: str
    updated: str
    description: str = ""
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    depends: list[str] = field(default_factory=list)
    started: str | None = None
    completed: str | None = None
    assignee: MemberRef | None = None
    ap: str | None = None              # jira: AP custom-field value
    comments: list[Comment] = field(default_factory=list)
    custom: dict[str, Any] = field(default_factory=dict)


class NotSupported(Exception):
    """Raised when a driver does not implement an optional capability."""


class Driver(Protocol):
    name: str

    def health(self) -> HealthResult: ...
    def list_tasks(self, filter: TaskFilter | None = None) -> list[Task]: ...
    def get_task(self, key: str) -> Task: ...
    def create_task(self, task: TaskInput) -> Task: ...
    def transition(self, key: str, to_column: str, **kwargs: Any) -> Task: ...
    def post_comment(self, key: str, body: str, kind: CommentKind = CommentKind.COMMENT) -> Comment: ...
    def list_comments(self, key: str) -> list[Comment]: ...
    def assign(self, key: str, member: MemberRef) -> Task: ...
    def list_members(self) -> list[Member]: ...

    # Optional — jira-only in v0.2.
    def list_aps(self) -> list[str]: ...
    def register_ap(self, name: str) -> None: ...

    # Mutation primitives — jira-only in v0.3.28 (#55).
    def update_description(self, key: str, description: str) -> Task: ...
    def update_summary(self, key: str, summary: str) -> Task: ...
    def update_labels(
        self, key: str, *, add: list[str] | None = None, remove: list[str] | None = None
    ) -> Task: ...
    def delete_issue(self, key: str, *, cascade: bool = False) -> None: ...
