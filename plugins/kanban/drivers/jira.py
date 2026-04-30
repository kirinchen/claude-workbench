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

from lib import card_cache, credentials, transitions as _tr
from lib.jira_client import JiraClient, JiraError, adf_to_text, text_to_adf
from drivers.base import (
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


class SelfApproveRefused(RuntimeError):
    """Raised when an agent tries to transition its own card to DONE.

    SPEC §8 invariant — the plugin enforces this client-side as well as
    delegating to Jira workflow conditions when admin can configure them.
    """

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
        # kanban_io auto-migrates legacy backend.jira on load, so by the
        # time we get here the cfg is in v0.3 transitions form. Be defensive
        # in case a caller built the config in-memory: run the migration here
        # too — it is idempotent on already-migrated input.
        self.cfg: dict[str, Any] = _tr.migrate_legacy(backend.get("jira") or {})
        self.project_key: str = self.cfg.get("projectKey") or ""
        self.board_id: int | None = self.cfg.get("boardId")
        self.transitions_map: dict[str, dict[str, Any]] = self.cfg.get("transitions") or {}
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

    def _canonical_spec(self, column: str) -> dict[str, Any] | None:
        return self.transitions_map.get(column)

    def _canonical_to_status(self, column: str) -> str | None:
        spec = self._canonical_spec(column)
        return spec.get("status") if spec else None

    def _issue_to_task(self, issue: dict[str, Any]) -> Task:
        f = issue.get("fields") or {}
        status_name = ((f.get("status") or {}).get("name")) or ""
        labels = list(f.get("labels") or [])
        column = _tr.disambiguate(self.transitions_map, status_name, labels)
        if column is None:
            # Unknown status — surface raw to caller.
            column = status_name

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

        # Surface "is blocked by" links as the canonical `depends` list, so
        # downstream code (read-only display, /kanban:next dep checks) gets
        # parity with local-mode `depends`. We pull the inwardIssue.key of
        # every `Blocks` link — that's the issue that blocks us.
        depends: list[str] = []
        for link in f.get("issuelinks") or []:
            ltype = (link.get("type") or {}).get("name")
            if ltype != "Blocks":
                continue
            inward = link.get("inwardIssue") or {}
            inward_key = inward.get("key")
            if inward_key:
                depends.append(inward_key)

        return Task(
            id=issue.get("key", ""),
            title=f.get("summary", ""),
            column=column,
            priority=priority,
            created=f.get("created", ""),
            updated=f.get("updated", ""),
            description=adf_to_text(f.get("description")) if f.get("description") else "",
            tags=labels,
            depends=depends,
            assignee=member,
            ap=ap_value,
            comments=[],
            custom={
                "raw_status": status_name,
                "raw_labels": labels,
                "raw_issuelinks": f.get("issuelinks") or [],
            },
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
                  "created", "updated", "description", "issuelinks"]
        if self.ap_field_id:
            fields.append(self.ap_field_id)
        max_results = filter.limit if filter and filter.limit else 50

        resp = client.search_jql(jql, fields=fields, max_results=max_results)
        return [self._issue_to_task(i) for i in resp.get("issues", [])]

    def get_task(self, key: str) -> Task:
        client = self._client_or_raise()
        fields = ["summary", "status", "priority", "assignee", "labels",
                  "created", "updated", "description", "issuelinks"]
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
        spec = self._canonical_spec(to_column)
        if not spec:
            raise RuntimeError(
                f"no transition spec configured for {to_column!r} — "
                "re-run /kanban:initjira step 3 to define it"
            )
        target_status = spec.get("status")
        if not target_status:
            raise RuntimeError(f"transition spec for {to_column!r} missing `status`")

        # One pre-flight read serves anti-self-approve, the already-in-
        # target-status fast path, and the blocked_by idempotency check.
        existing_for_status = self.get_task(key)
        if to_column == "DONE":
            current_ap = self._current_repo_ap()
            if current_ap and existing_for_status.ap and existing_for_status.ap == current_ap:
                raise SelfApproveRefused(
                    f"anti-self-approve: agent {current_ap!r} cannot "
                    f"transition its own card {key} to DONE — ask another "
                    "agent or a human reviewer to approve"
                )
        client = self._client_or_raise()

        # Step 0 — blocked_by issue links (only meaningful when transitioning
        # TO a BLOCKED column). Done BEFORE the status transition so a bad
        # blocker key (404) leaves the card in its current state instead of
        # half-blocked. See SPEC §10 / issue #8.
        blocked_by = kwargs.get("blocked_by") or []
        if to_column == "BLOCKED" and blocked_by:
            self._link_blockers(client, key, blocked_by, existing_for_status)

        # Step A — status transition (find the right transition id).
        # Skip if the issue is already in the target status (avoids the API
        # rejecting a no-op transition).
        existing_status = existing_for_status.custom.get("raw_status")
        if existing_status != target_status:
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
                    f"no Jira workflow transition leads to status {target_status!r} "
                    f"on issue {key} — check Jira workflow conditions"
                )
            client.transition_issue(key, tid)

        # Step B — labels add/remove. Read existing, mutate, PUT whole list.
        add_labels = list(spec.get("addLabels") or [])
        remove_labels = list(spec.get("removeLabels") or [])
        partial_failure: str | None = None
        if add_labels or remove_labels:
            current_labels = list(existing_for_status.custom.get("raw_labels") or [])
            updated = [l for l in current_labels if l not in remove_labels]
            for l in add_labels:
                if l not in updated:
                    updated.append(l)
            if updated != current_labels:
                try:
                    client.update_issue(key, {"labels": updated})
                except JiraError as e:
                    partial_failure = f"label sync failed: {e.detail or e}"

        # Step C — assignee. If the spec pins a specific accountId, set it.
        spec_assignee = spec.get("assignee") or {}
        if spec_assignee.get("accountId"):
            try:
                client._request(
                    "PUT",
                    f"/rest/api/3/issue/{key}/assignee",
                    body={"accountId": spec_assignee["accountId"]},
                )
            except JiraError as e:
                partial_failure = (
                    (partial_failure + "; " if partial_failure else "")
                    + f"assignee set failed: {e.detail or e}"
                )

        # Audit trail for blocked transitions and partial failures.
        if to_column == "BLOCKED":
            reason = kwargs.get("reason")
            if reason:
                self.post_comment(key, f"Blocked: {reason}", CommentKind.SYSTEM)
        if partial_failure:
            self._post_system_comment(
                key,
                f"compound transition partial — status to {target_status!r} OK, but "
                f"{partial_failure}",
            )

        # Any successful transition invalidates the cache for that key.
        card_cache.invalidate(self.project_root, key)
        return self.get_task(key)

    def post_comment(
        self, key: str, body: str, kind: CommentKind = CommentKind.COMMENT
    ) -> Comment:
        client = self._client_or_raise()
        ap = self._current_repo_ap()
        adf = self._agent_comment_body(body, kind, ap)
        raw = client.add_comment(key, adf)
        # Comment write changes the card's "last update" — drop the cache.
        card_cache.invalidate(self.project_root, key)
        return Comment(
            author=ap or self.email,
            ts=raw.get("created") or _now_iso(),
            text=body,
            kind=kind,
        )

    _BLOCKER_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")

    def _existing_blocker_keys(self, task: Task) -> set[str]:
        """Return the set of inwardIssue keys whose link type is `Blocks`."""
        out: set[str] = set()
        for link in task.custom.get("raw_issuelinks") or []:
            ltype = (link.get("type") or {}).get("name")
            if ltype != "Blocks":
                continue
            inward = link.get("inwardIssue") or {}
            inward_key = inward.get("key")
            if isinstance(inward_key, str):
                out.add(inward_key)
        return out

    def _link_blockers(
        self,
        client: JiraClient,
        key: str,
        blocked_by: list[str],
        existing: Task,
    ) -> None:
        """Validate + create `Blocks` links from each blocker to `key`.

        Done before the status transition. Raises RuntimeError on any
        validation failure so the slash command surfaces the error and
        the card stays in its previous state.

        Idempotent: skips blockers that already have an inward `Blocks`
        link to this card.
        """
        # Validate format and self-link rule first — purely local checks
        # so we fail fast without any network round-trips.
        for raw in blocked_by:
            if not isinstance(raw, str) or not self._BLOCKER_KEY_RE.match(raw):
                raise RuntimeError(
                    f"invalid blocker key {raw!r} — expected format like "
                    "'AGENT-42' (uppercase project + dash + digits)"
                )
            if raw == key:
                raise RuntimeError(
                    f"refusing self-block: {key} cannot be blocked by itself"
                )

        # Dedup the input list (case the caller passed duplicates) and
        # filter out blockers already linked.
        seen_existing = self._existing_blocker_keys(existing)
        seen_local: set[str] = set()
        to_link: list[str] = []
        for raw in blocked_by:
            if raw in seen_existing or raw in seen_local:
                continue
            seen_local.add(raw)
            to_link.append(raw)

        for blocker in to_link:
            try:
                client.create_issue_link(
                    type_name="Blocks",
                    inward_key=blocker,
                    outward_key=key,
                )
            except JiraError as e:
                # 404 most likely — blocker key doesn't exist or no view
                # permission. Surface verbatim so the user can fix.
                raise RuntimeError(
                    f"blocker {blocker} could not be linked: "
                    f"{e.detail or e} (status {e.status_code})"
                ) from e

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
        client = self._client_or_raise()
        if member.kind == "human":
            client._request(
                "PUT",
                f"/rest/api/3/issue/{key}/assignee",
                body={"accountId": member.accountId},  # type: ignore[union-attr]
            )
        else:  # AgentRef — write the AP custom field, leave assignee alone.
            if not self.ap_field_id:
                raise NotSupported(
                    "AP field is not configured — run /kanban:initjira step 4"
                )
            ap_value = member.ap  # type: ignore[union-attr]
            client.update_issue(
                key,
                {self.ap_field_id: {"value": ap_value}},
            )
            # Also set assignee to the shared agent account so notifications
            # land somewhere visible. No-op if agentAccountId is unset.
            if self.agent_account_id:
                client._request(
                    "PUT",
                    f"/rest/api/3/issue/{key}/assignee",
                    body={"accountId": self.agent_account_id},
                )
        card_cache.invalidate(self.project_root, key)
        return self.get_task(key)

    def list_members(self) -> list[Member]:
        # Returns the registered AP roster as agent members. Human members
        # come from Jira directly via UI; we don't shadow that here.
        out: list[Member] = []
        for ap in self.list_aps():
            out.append(Member(ref=AgentRef(ap=ap), displayName=ap))
        return out

    def list_aps(self) -> list[str]:
        return list((self.cfg.get("ap") or {}).get("registered") or [])

    def register_ap(self, name: str) -> None:
        """Append `name` to backend.jira.ap.registered. Caller is expected to
        have already added the option in Jira and validated uniqueness — this
        only persists the cached registry. The full flow lives in
        scripts/jira_setup.py to keep network ops out of the driver fast path.
        """
        ap_block = self.cfg.setdefault("ap", {})
        registered = list(ap_block.get("registered") or [])
        if name not in registered:
            registered.append(name)
        ap_block["registered"] = registered

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
