"""JiraDriver — Jira Cloud-backed implementation of the Driver Protocol.

Phase 2 scope:
- health, list_tasks, get_task, transition (canonical → Jira via statusMap),
  post_comment, list_comments, assign (human only).
- AP-related ops (list_aps, register_ap) raise NotSupported. Phase 3 lands them.
- Anti-self-approve client-side enforcement requires AP wiring (Phase 3).
- Comment prefix grammar (SPEC §9) is wired so Phase 3 can light up AP-aware
  attribution — for now agent comments use kind=COMMENT with no AP prefix.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..lib import credentials
from ..lib.jira_client import JiraClient, JiraError, adf_to_text, text_to_adf
from .base import (
    AgentRef,
    Comment,
    CommentKind,
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


CANONICAL_COLUMNS = ("TODO", "DOING", "BLOCKED", "REVIEW", "DONE", "CANCELLED")

# SPEC §9 prefix grammar.
_PREFIX_RE = re.compile(
    r"^\*\*\[(?P<ap>[a-z][a-z0-9-]+)\]\s+\[(?P<kind>Q|A|C|S)\]\*\*\s*\n*(?P<rest>.*)$",
    re.DOTALL,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class JiraDriver:
    name = "jira"

    def __init__(self, kanban_data: dict[str, Any], project_root: Path):
        self.project_root = Path(project_root)
        backend = kanban_data.get("backend") or {}
        if backend.get("driver") != "jira":
            raise ValueError("JiraDriver requires backend.driver == 'jira'")
        self.cfg: dict[str, Any] = backend.get("jira") or {}
        self.project_key: str = self.cfg.get("projectKey") or ""
        self.board_id: int | None = self.cfg.get("boardId")
        self.status_map: dict[str, str] = self.cfg.get("statusMap") or {}
        self.partial: bool = bool(self.cfg.get("partial"))
        self.label_fallback: dict[str, str] = self.cfg.get("labelFallback") or {}
        self.agent_account_id: str | None = self.cfg.get("agentAccountId")
        self.ap_field_id: str | None = (self.cfg.get("ap") or {}).get("fieldId")

        env = credentials.read("JIRA_")
        self.base_url = env.get("JIRA_BASE_URL", "")
        self.email = env.get("JIRA_AGENT_EMAIL", "")
        self._token = env.get("JIRA_API_TOKEN", "")
        self._client: JiraClient | None = None

    # --- helpers -------------------------------------------------------

    def _client_or_raise(self) -> JiraClient:
        if not (self.base_url and self.email and self._token):
            raise RuntimeError(
                "Jira credentials missing — run /kanban:initjira or "
                "/kanban:reset-credentials"
            )
        if self._client is None:
            self._client = JiraClient(self.base_url, self.email, self._token)
        return self._client

    def _canonical_to_status(self, column: str) -> str | None:
        return self.status_map.get(column)

    def _status_to_canonical(self, status_name: str) -> str:
        for canonical, display in self.status_map.items():
            if display == status_name:
                return canonical
        # Unknown — return the raw status as-is so callers see it untranslated.
        return status_name

    def _issue_to_task(self, issue: dict[str, Any]) -> Task:
        f = issue.get("fields") or {}
        status_name = ((f.get("status") or {}).get("name")) or ""
        column = self._status_to_canonical(status_name)
        # Apply label fallback in partial mode.
        if self.partial and self.label_fallback:
            for canonical, label in self.label_fallback.items():
                if label in (f.get("labels") or []):
                    column = canonical
                    break

        ap_value: str | None = None
        if self.ap_field_id:
            raw = f.get(self.ap_field_id)
            if isinstance(raw, dict):
                ap_value = raw.get("value")
            elif isinstance(raw, str):
                ap_value = raw

        priority = ((f.get("priority") or {}).get("name")) or ""
        assignee_obj = f.get("assignee") or {}
        member: MemberRef | None = None
        if assignee_obj.get("accountId"):
            member = HumanRef(accountId=assignee_obj["accountId"])

        return Task(
            id=issue.get("key", ""),
            title=f.get("summary", ""),
            column=column,
            priority=priority,
            created=f.get("created", ""),
            updated=f.get("updated", ""),
            description=adf_to_text(f.get("description")) if f.get("description") else "",
            tags=list(f.get("labels") or []),
            depends=[],  # epic/issuelink resolution deferred (out of scope v0.2)
            assignee=member,
            ap=ap_value,
            comments=[],
            custom={"raw_status": status_name},
        )

    @staticmethod
    def _agent_prefix(ap: str | None, kind: CommentKind) -> str:
        ap_str = ap or "agent"
        return f"**[{ap_str}] [{kind.value}]**\n\n"

    def _agent_comment_body(
        self, body: str, kind: CommentKind, ap: str | None
    ) -> dict[str, Any]:
        return text_to_adf(self._agent_prefix(ap, kind) + body)

    def _parse_comment(self, raw: dict[str, Any]) -> Comment:
        author = ((raw.get("author") or {}).get("displayName")) or ""
        ts = raw.get("created") or ""
        text = adf_to_text(raw.get("body"))
        kind = CommentKind.COMMENT
        m = _PREFIX_RE.match(text or "")
        if m:
            try:
                kind = CommentKind(m.group("kind"))
            except ValueError:
                pass
            author = m.group("ap")
            text = m.group("rest").strip()
        return Comment(author=author, ts=ts, text=text, kind=kind)

    # --- Driver Protocol ----------------------------------------------

    def health(self) -> HealthResult:
        if not (self.base_url and self.email and self._token):
            return HealthResult(HealthStatus.UNAUTHENTICATED, "credentials missing")
        try:
            client = self._client_or_raise()
            client.get_myself()
        except JiraError as e:
            if e.status_code == 401:
                return HealthResult(HealthStatus.UNAUTHENTICATED, e.detail)
            return HealthResult(HealthStatus.UNREACHABLE, e.detail)
        if not self.project_key:
            return HealthResult(HealthStatus.DEGRADED, "projectKey unconfigured")
        return HealthResult(HealthStatus.OK)

    def list_tasks(self, filter: TaskFilter | None = None) -> list[Task]:
        if not self.project_key:
            raise RuntimeError("backend.jira.projectKey unconfigured")
        client = self._client_or_raise()

        clauses = [f'project = "{self.project_key}"']
        if filter:
            if filter.column:
                status = self._canonical_to_status(filter.column)
                if status:
                    clauses.append(f'status = "{status}"')
                elif self.partial and filter.column in self.label_fallback:
                    clauses.append(f'labels = "{self.label_fallback[filter.column]}"')
            if filter.assignee:
                clauses.append(f'assignee = "{filter.assignee}"')
            if filter.priority:
                clauses.append(f'priority = "{filter.priority}"')
            if filter.ap and self.ap_field_id:
                # Phase 3 feature: jql-by-AP. Field id is safe to inject; AP
                # values are validated [a-z0-9-] so quote-escaping is moot.
                clauses.append(f'cf[{self.ap_field_id[12:]}] = "{filter.ap}"')

        jql = " AND ".join(clauses) + " ORDER BY priority DESC, created ASC"
        fields = ["summary", "status", "priority", "assignee", "labels",
                  "created", "updated", "description"]
        if self.ap_field_id:
            fields.append(self.ap_field_id)
        max_results = filter.limit if filter and filter.limit else 50

        resp = client.search_jql(jql, fields=fields, max_results=max_results)
        return [self._issue_to_task(i) for i in resp.get("issues", [])]

    def get_task(self, key: str) -> Task:
        client = self._client_or_raise()
        fields = ["summary", "status", "priority", "assignee", "labels",
                  "created", "updated", "description"]
        if self.ap_field_id:
            fields.append(self.ap_field_id)
        issue = client.get_issue(key, fields=fields)
        return self._issue_to_task(issue)

    def create_task(self, task: TaskInput) -> Task:
        # Used by §11 migration. Phase 2 ships a minimal create that maps to
        # /rest/api/3/issue. Idempotency (don't double-create on retry) is
        # the importer's responsibility, not the driver's.
        if not self.project_key:
            raise RuntimeError("backend.jira.projectKey unconfigured")
        client = self._client_or_raise()
        body: dict[str, Any] = {
            "fields": {
                "project": {"key": self.project_key},
                "summary": task.title,
                "issuetype": {"name": "Task"},
            }
        }
        if task.description:
            body["fields"]["description"] = text_to_adf(task.description)
        if task.priority:
            body["fields"]["priority"] = {"name": task.priority}
        if task.tags:
            body["fields"]["labels"] = list(task.tags)
        resp = client._request("POST", "/rest/api/3/issue", body=body)
        return self.get_task(resp["key"])

    def transition(self, key: str, to_column: str, **kwargs: Any) -> Task:
        if to_column not in CANONICAL_COLUMNS:
            raise ValueError(
                f"unknown canonical column {to_column!r}; expected one of "
                f"{CANONICAL_COLUMNS}"
            )
        client = self._client_or_raise()
        target_status = self._canonical_to_status(to_column)

        if target_status:
            transitions = (client.get_transitions(key) or {}).get("transitions", [])
            tid = next(
                (
                    t["id"]
                    for t in transitions
                    if (t.get("to") or {}).get("name") == target_status
                ),
                None,
            )
            if not tid:
                raise RuntimeError(
                    f"no transition to status {target_status!r} on issue {key} — "
                    f"check Jira workflow conditions"
                )
            client.transition_issue(key, tid)
        elif self.partial and to_column in self.label_fallback:
            # Apply label substitute via PUT issue.
            label = self.label_fallback[to_column]
            client._request(
                "PUT",
                f"/rest/api/3/issue/{key}",
                body={"update": {"labels": [{"add": label}]}},
            )
            self._post_system_comment(
                key, f"label substitute applied: {label} (canonical={to_column})"
            )
        else:
            raise RuntimeError(
                f"no Jira status or label fallback configured for {to_column!r}"
            )

        if to_column == "BLOCKED":
            reason = kwargs.get("reason")
            if reason:
                self.post_comment(key, f"Blocked: {reason}", CommentKind.SYSTEM)
        return self.get_task(key)

    def post_comment(
        self, key: str, body: str, kind: CommentKind = CommentKind.COMMENT
    ) -> Comment:
        client = self._client_or_raise()
        ap = self._current_repo_ap()
        adf = self._agent_comment_body(body, kind, ap)
        raw = client.add_comment(key, adf)
        return Comment(
            author=ap or self.email,
            ts=raw.get("created") or _now_iso(),
            text=body,
            kind=kind,
        )

    def _post_system_comment(self, key: str, body: str) -> None:
        try:
            self.post_comment(key, body, CommentKind.SYSTEM)
        except JiraError:
            pass  # do not block the transition if commenting fails

    def list_comments(self, key: str) -> list[Comment]:
        client = self._client_or_raise()
        raw = client.list_comments(key)
        return [self._parse_comment(c) for c in (raw.get("comments") or [])]

    def assign(self, key: str, member: MemberRef) -> Task:
        if member.kind != "human":
            raise NotSupported(
                "Jira agent assignment by AP is a Phase 3 feature — "
                "use a human accountId here"
            )
        client = self._client_or_raise()
        client._request(
            "PUT",
            f"/rest/api/3/issue/{key}/assignee",
            body={"accountId": member.accountId},  # type: ignore[union-attr]
        )
        return self.get_task(key)

    def list_members(self) -> list[Member]:
        # Phase 3 surfaces /user/assignable + AP registry. Phase 2 returns [].
        return []

    def list_aps(self) -> list[str]:
        raise NotSupported("AP operations land in Phase 3")

    def register_ap(self, name: str) -> None:
        raise NotSupported("AP operations land in Phase 3")

    # --- repo identity ------------------------------------------------

    def _current_repo_ap(self) -> str | None:
        """Read .claude/kanban-agent.json. Phase 3 wires this fully — Phase 2
        treats it as best-effort for outgoing comment attribution.
        """
        path = self.project_root / ".claude" / "kanban-agent.json"
        if not path.exists():
            return None
        try:
            import json
            return json.loads(path.read_text()).get("ap")
        except Exception:
            return None
