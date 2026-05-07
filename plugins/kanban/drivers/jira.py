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
from lib.jira_client import (
    JiraClient,
    JiraError,
    _text_to_inline_nodes,
    adf_to_text,
    text_to_adf,
    text_to_adf_with_mention,
)
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


CANONICAL_COLUMNS = ("TODO", "DOING", "BLOCKED", "REVIEW", "APPROVED", "CANCELLED")


class SelfApproveRefused(RuntimeError):
    """Raised when an agent tries to transition its own card to APPROVED.

    SPEC §8 invariant — the plugin enforces this client-side as well as
    delegating to Jira workflow conditions when admin can configure them.
    APPROVED was renamed from DONE in #48 to disambiguate from the Jira
    workflow status `Done`.
    """

# SPEC §9 prefix grammar. Historically the prefix was authored as markdown
# `**[ap] [kind]**`; v0.3.12 switched to ADF strong marks (so Jira UI no
# longer renders literal `**` and broken `<span class="error">` around the
# brackets — see #27). When parsing, accept both forms so old comments stay
# readable.
_PREFIX_RE = re.compile(
    r"^(?:\*\*)?\[(?P<ap>[a-z][a-z0-9-]+)\]\s+\[(?P<kind>Q|A|C|S)\](?:\*\*)?\s*\n*(?P<rest>.*)$",
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
        # Lazy cache of `{status_name: category_key}` for the project.
        # Populated on first call to `_get_status_category` and reused
        # within the driver instance. Used by anti-self-approve to
        # distinguish a true terminal-Done transition from an
        # intermediate APPROVED step (#50). `None` until populated;
        # `{}` if the lookup ever failed (avoid retry storms).
        self._status_categories: dict[str, str] | None = None

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

    def _get_status_category(self, status_name: str) -> str | None:
        """Return the Jira statusCategory key (`new`, `indeterminate`,
        `done`) for the given status display name, or None if the
        lookup couldn't resolve it.

        Lazy-populates a per-instance cache on first call. On API
        failure we cache an empty map so subsequent calls don't hammer
        Jira; the caller treats None as "unknown — fail closed" (#50).

        Used by anti-self-approve to tell apart a true terminal-Done
        transition (block) from an intermediate APPROVED step where
        the DSL maps APPROVED to a non-terminal Jira status — e.g.
        `transitions.APPROVED.status == "REVIEW"` for teams that use
        a soft "agent done, awaiting human approval" intermediate
        before the human pushes REVIEW → Done.
        """
        if not status_name:
            return None
        if self._status_categories is None:
            self._status_categories = {}
            if not self.project_key:
                return None
            try:
                client = self._client_or_raise()
                types = client.get_project_statuses(self.project_key) or []
            except (JiraError, RuntimeError):
                # Lookup failed — keep the empty cache so we don't retry
                # on every transition; caller treats None as unknown.
                return None
            for issue_type in types:
                for status in (issue_type or {}).get("statuses") or []:
                    nm = status.get("name") or ""
                    cat = (status.get("statusCategory") or {}).get("key")
                    if nm and cat and nm not in self._status_categories:
                        self._status_categories[nm] = cat
        return self._status_categories.get(status_name)

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
    def _agent_prefix_text(ap: str | None, kind: CommentKind) -> str:
        """Plain text of the SPEC §9 prefix (no markdown). The ADF builder
        wraps this in a strong-marked text node, so Jira UI renders it as
        bold without the markdown literals leaking through (see #27)."""
        ap_str = ap or "agent"
        return f"[{ap_str}] [{kind.value}]"

    def _agent_comment_body(
        self, body: str, kind: CommentKind, ap: str | None
    ) -> dict[str, Any]:
        # Two paragraphs: bold prefix on its own line, then the body. ADF
        # doesn't parse markdown — emitting the prefix as a strong-marked
        # text node is the only way to get bold rendering without the raw
        # `**` showing up in the Jira UI (#27). URLs in the body are
        # split out into ADF link-marked nodes so they render clickable.
        body_nodes = _text_to_inline_nodes(body) or [{"type": "text", "text": ""}]
        return {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": self._agent_prefix_text(ap, kind),
                            "marks": [{"type": "strong"}],
                        }
                    ],
                },
                {
                    "type": "paragraph",
                    "content": body_nodes,
                },
            ],
        }

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
                elif getattr(self, "partial", False) and filter.column in getattr(self, "label_fallback", {}):
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
        new_key = resp["key"]

        # Fixup pass — re-assert fields the project's Create Screen scheme
        # may have silently dropped (#35). Jira filters the POST body
        # against the Create Screen for the target issuetype: fields not
        # on that screen are silently elided, the API returns 201, and
        # `labels: []` ends up on the issue. The Edit Screen is generally
        # more permissive, so a follow-up PUT recovers most cases. Best-
        # effort: a fixup failure leaves an audit comment but doesn't
        # roll back the create (the card exists; users prefer "labels
        # missing" over "no card at all").
        fixup: dict[str, Any] = {}
        if task.tags:
            fixup["labels"] = list(task.tags)
        if fixup:
            try:
                client._request(
                    "PUT", f"/rest/api/3/issue/{new_key}",
                    body={"fields": fixup},
                )
            except JiraError as e:
                self._post_system_comment(
                    new_key,
                    f"create_task fixup failed (fields {sorted(fixup)} may "
                    f"have been silently dropped by Create Screen scheme): "
                    f"{e.detail or e}",
                )

        # Sub-card linking — best-effort. If link creation fails, log via
        # an audit comment on the new card but don't undo the create. The
        # card exists; the user can manually link if needed.
        if task.parent_key:
            try:
                client.create_issue_link(
                    type_name=task.link_type,
                    inward_key=task.parent_key,
                    outward_key=new_key,
                )
            except JiraError as e:
                self._post_system_comment(
                    new_key,
                    f"link to parent {task.parent_key} ({task.link_type}) failed: "
                    f"{e.detail or e}",
                )

        return self.get_task(new_key)

    def transition(self, key: str, to_column: str, **kwargs: Any) -> Task:
        # Alias legacy DONE → APPROVED (#48). Caller-side surfaces (CLI
        # --to, slash command bodies) emit a deprecation warning before
        # delegating; here we just normalise so internal logic sees only
        # the canonical name.
        to_column = _tr.normalize_canonical(to_column)
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

        # Flavor resolution (#45). When the spec carries a `flavors` block,
        # the caller must pick one (via --flavor / kwargs["flavor"]) or
        # the spec must declare a `defaultFlavor`. The chosen flavor's
        # addLabels / removeLabels / assignee are merged onto the parent
        # spec, then the rest of the compound write runs unchanged. When
        # the spec has no flavors, a stray `flavor` kwarg is silently
        # ignored (forward compat — callers can pass it unconditionally).
        flavor_name = kwargs.get("flavor")
        flavors = spec.get("flavors") or {}
        if flavors:
            if not flavor_name:
                flavor_name = spec.get("defaultFlavor")
            if not flavor_name:
                raise RuntimeError(
                    f"transition to {to_column!r} requires --flavor "
                    f"(available: {sorted(flavors)}); set "
                    f"transitions.{to_column}.defaultFlavor in kanban.json "
                    f"to skip this when one flavor is the common case"
                )
            if flavor_name not in flavors:
                raise RuntimeError(
                    f"unknown flavor {flavor_name!r} for {to_column!r} "
                    f"(available: {sorted(flavors)})"
                )
            flavor_spec = flavors[flavor_name] or {}
            # Build a merged spec WITHOUT mutating self.transitions_map —
            # subsequent reads / disambiguate calls still see the pristine
            # config.
            merged_add = list(spec.get("addLabels") or []) + list(
                flavor_spec.get("addLabels") or []
            )
            merged_remove = list(spec.get("removeLabels") or []) + list(
                flavor_spec.get("removeLabels") or []
            )
            spec = dict(spec)
            spec["addLabels"] = merged_add
            spec["removeLabels"] = merged_remove
            if flavor_spec.get("assignee"):
                spec["assignee"] = flavor_spec["assignee"]

        # Early category check — fail fast on lookup failure before
        # spending a get_task hit. Per #50, anti-self-approve must only
        # fire when the target Jira status is the workflow's true
        # terminal Done — not for teams whose DSL maps APPROVED to an
        # intermediate status (e.g. canonical APPROVED → Jira "REVIEW"
        # with the `kanban_awaiting_approval` label, where the agent is
        # just signalling completion; the human still has to push
        # REVIEW → Done). The status's `statusCategory` key is the
        # Jira-native semantic flag:
        #   `done`          → guard applies (true approval)
        #   `indeterminate` → intermediate, allow
        #   `new`           → also intermediate, allow
        #   None (lookup failed) → fail closed (refuse with a distinct
        #     message so the user can tell "Jira API hiccup" apart from
        #     "you're trying to self-approve")
        target_category: str | None = None
        if to_column == "APPROVED":
            target_category = self._get_status_category(target_status)
            if target_category is None:
                raise RuntimeError(
                    f"cannot verify whether status {target_status!r} is the "
                    f"workflow's terminal Done state (Jira status-category "
                    f"lookup failed). For safety, refusing the transition — "
                    f"anti-self-approve cannot be skipped without "
                    f"verification. Retry in a moment, or run /kanban:whoami "
                    f"to check Jira credentials. See #50."
                )

        # One pre-flight read serves anti-self-approve, the already-in-
        # target-status fast path, and the blocked_by idempotency check.
        existing_for_status = self.get_task(key)
        if to_column == "APPROVED" and target_category == "done":
            current_ap = self._current_repo_ap()
            if current_ap and existing_for_status.ap and existing_for_status.ap == current_ap:
                # Only refuse when the agent itself owns the work.
                # Per issue #19: if the assignee is a different account
                # (e.g. a human teammate who actually completed the
                # work), the agent is recording, not approving — allow.
                # An unassigned card defaults to "agent's own work" for
                # safety: without an explicit human owner the strict
                # original guard still applies.
                assignee_acct: str | None = None
                if existing_for_status.assignee is not None:
                    assignee_acct = getattr(
                        existing_for_status.assignee, "accountId", None
                    )
                recording_for_other = (
                    assignee_acct is not None
                    and self.agent_account_id is not None
                    and assignee_acct != self.agent_account_id
                )
                if not recording_for_other:
                    raise SelfApproveRefused(
                        f"anti-self-approve: agent {current_ap!r} cannot "
                        f"transition its own card {key} to APPROVED — ask "
                        "another agent or a human reviewer to approve "
                        "(or assign the card to that human first if you "
                        "are recording on their behalf)"
                    )
        # else (target_category in {"indeterminate", "new"}): intermediate
        # state, no self-approve concern (#50).
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
            # Match by transition action name first, then destination status
            # name. Jira's `to.name` is locale-translated (e.g. zh-TW shows
            # "審查" for canonical "REVIEW") even with Accept-Language: en-US,
            # but `name` (the workflow action label) stays English. Falling
            # back to `to.name` keeps English-locale users working when their
            # action name differs from their status name (e.g. action="Resolve
            # Issue", status="Resolved", DSL="Resolved"). See #17.
            tid = next(
                (
                    t["id"]
                    for t in transitions
                    if t.get("name") == target_status
                    or (t.get("to") or {}).get("name") == target_status
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
        self,
        key: str,
        body: str,
        kind: CommentKind = CommentKind.COMMENT,
        *,
        mention_account_id: str | None = None,
        mention_display: str | None = None,
    ) -> Comment:
        """Post a comment with the SPEC §9 prefix grammar.

        When `mention_account_id` is supplied, the body is wrapped in an
        ADF doc that begins with a Jira-native @-mention node — used by
        /kanban:reply to notify the human who originally @-mentioned the
        bot. Without it, the comment is plain text (existing behaviour).
        """
        client = self._client_or_raise()
        ap = self._current_repo_ap()
        if mention_account_id:
            adf = text_to_adf_with_mention(
                self._agent_prefix_text(ap, kind),
                mention_account_id,
                mention_display or "user",
                body,
            )
        else:
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
