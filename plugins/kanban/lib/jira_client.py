"""Jira Cloud REST client used by drivers/jira.py.

Design constraints:
- stdlib only (urllib) — no `requests`/`httpx` dependency
- Basic Auth with shared agent email + API token
- Retry: 429 (Retry-After), 5xx (exponential backoff), network errors
- Injectable transport for tests (no live HTTP in CI)
- Never log/echo the token; redact on errors

Public surface (each maps to a Jira REST endpoint, mostly v3):
    JiraClient(base_url, email, api_token, *, transport=None)
        get_myself()
        get_project(project_key)
        get_board(board_id)
        get_board_configuration(board_id)
        get_project_statuses(project_key)
        search_jql(jql, fields=..., max_results=50)
        get_issue(key, fields=...)
        get_transitions(key)
        transition_issue(key, transition_id)
        add_comment(key, body_adf)         # body_adf is a dict per Jira ADF
        list_comments(key)

Errors raise JiraError with .status_code (or 0 for network) and .detail.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional


JsonAny = Any  # Jira responses are dicts/lists with mixed types


class JiraError(Exception):
    def __init__(self, status_code: int, detail: str = "", url: str = ""):
        super().__init__(f"[{status_code}] {detail or url}")
        self.status_code = status_code
        self.detail = detail
        self.url = url


@dataclass
class _Response:
    status: int
    body: bytes
    headers: dict[str, str]


# A transport is `(method, url, headers, body) -> _Response`. The default
# implementation uses urllib; tests inject a fake.
Transport = Callable[[str, str, dict[str, str], Optional[bytes]], _Response]


def _default_transport(
    method: str, url: str, headers: dict[str, str], body: Optional[bytes]
) -> _Response:
    req = urllib.request.Request(url=url, method=method, headers=headers, data=body)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return _Response(
                status=resp.status,
                body=resp.read(),
                headers={k.lower(): v for k, v in resp.headers.items()},
            )
    except urllib.error.HTTPError as e:
        return _Response(
            status=e.code,
            body=e.read() if hasattr(e, "read") else b"",
            headers={k.lower(): v for k, v in (e.headers.items() if e.headers else [])},
        )
    except urllib.error.URLError as e:
        # Treat as transport error; let retry loop decide.
        raise JiraError(0, f"network: {e.reason}", url) from e


# -------- retry policy --------------------------------------------------------

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BASE_BACKOFF_SEC = 0.5


def _retry_sleep(attempt: int, retry_after: Optional[str]) -> float:
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return _BASE_BACKOFF_SEC * (2**attempt)


# -------- client --------------------------------------------------------------


class JiraClient:
    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not base_url:
            raise ValueError("base_url required")
        self.base_url = base_url.rstrip("/")
        self.email = email
        self._token = api_token  # never logged
        self._transport = transport or _default_transport
        self._sleep = sleep

    # --- low-level ----------------------------------------------------

    def _auth_header(self) -> str:
        raw = f"{self.email}:{self._token}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> JsonAny:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query, doseq=True)}"
        headers = {
            "Authorization": self._auth_header(),
            "Accept": "application/json",
            # Force English responses regardless of the agent account's UI
            # locale. The plugin's DSL stores status / priority / issue-type
            # names in English; without this, a zh-TW (or any non-English)
            # account causes Jira to return localized names like `進行中` for
            # `In Progress`, and transition lookup / priority validation
            # silently fail. Closes #17. Workflows whose underlying source
            # names are non-English are unaffected — there's no English
            # source to translate from in that case.
            "Accept-Language": "en-US",
        }
        body_bytes: Optional[bytes] = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            body_bytes = json.dumps(body).encode("utf-8")

        last_exc: JiraError | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = self._transport(method, url, headers, body_bytes)
            except JiraError as e:
                last_exc = e
                if attempt < _MAX_RETRIES:
                    self._sleep(_retry_sleep(attempt, None))
                    continue
                raise

            if resp.status in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                self._sleep(_retry_sleep(attempt, resp.headers.get("retry-after")))
                continue

            if 200 <= resp.status < 300:
                if not resp.body:
                    return None
                try:
                    return json.loads(resp.body.decode("utf-8"))
                except json.JSONDecodeError:
                    return resp.body

            detail = ""
            try:
                payload = json.loads(resp.body.decode("utf-8"))
                msgs = payload.get("errorMessages") or []
                errs = payload.get("errors") or {}
                detail = "; ".join(
                    list(msgs) + [f"{k}: {v}" for k, v in errs.items()]
                ) or json.dumps(payload)
            except (ValueError, AttributeError):
                detail = resp.body.decode("utf-8", errors="replace")[:500]
            raise JiraError(resp.status, detail, url)

        # Exhausted retries on transport-level errors.
        if last_exc:
            raise last_exc
        raise JiraError(0, "retries exhausted", url)

    # --- high-level endpoints ----------------------------------------

    def get_myself(self) -> dict[str, Any]:
        return self._request("GET", "/rest/api/3/myself")

    def get_project(self, project_key: str) -> dict[str, Any]:
        return self._request("GET", f"/rest/api/3/project/{project_key}")

    def get_board(self, board_id: int) -> dict[str, Any]:
        return self._request("GET", f"/rest/agile/1.0/board/{board_id}")

    def get_board_configuration(self, board_id: int) -> dict[str, Any]:
        return self._request(
            "GET", f"/rest/agile/1.0/board/{board_id}/configuration"
        )

    def get_project_statuses(self, project_key: str) -> list[dict[str, Any]]:
        """Returns a list of issue-types each with their `statuses` array."""
        return self._request("GET", f"/rest/api/3/project/{project_key}/statuses")

    def get_project_property(
        self, project_key: str, property_key: str
    ) -> dict[str, Any]:
        """Read a project entity property — structured JSON keyed under
        the given property name. Used by the kanban plugin to store
        board-level config (transitions DSL, AP field, conventions) on
        the Jira project itself, replacing the per-machine `import-jira-
        code` paste flow (#issue-after-50).

        Returns the full envelope shape:
            {"key": "<property_key>", "value": <user-supplied JSON>}
        Raises `JiraError(404)` when the property hasn't been set yet —
        callers usually treat that as "no board config yet, fall back
        to local DSL setup."
        """
        return self._request(
            "GET",
            f"/rest/api/3/project/{project_key}/properties/{property_key}",
        )

    def set_project_property(
        self, project_key: str, property_key: str, value: Any
    ) -> None:
        """Write a project entity property. Requires the agent's Jira
        account to have project-admin role; non-admin writers get 403.
        Properties cap at 32KB per value (Atlassian limit) — well above
        what a typical transitions/conventions block needs.
        """
        self._request(
            "PUT",
            f"/rest/api/3/project/{project_key}/properties/{property_key}",
            body=value,
        )

    def search_jql(
        self,
        jql: str,
        *,
        fields: list[str] | None = None,
        max_results: int = 50,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"jql": jql, "maxResults": max_results}
        if fields:
            body["fields"] = fields
        return self._request("POST", "/rest/api/3/search/jql", body=body)

    def get_issue(self, key: str, *, fields: list[str] | None = None) -> dict[str, Any]:
        query = {"fields": ",".join(fields)} if fields else None
        return self._request("GET", f"/rest/api/3/issue/{key}", query=query)

    def get_transitions(self, key: str) -> dict[str, Any]:
        return self._request("GET", f"/rest/api/3/issue/{key}/transitions")

    def transition_issue(self, key: str, transition_id: str) -> None:
        self._request(
            "POST",
            f"/rest/api/3/issue/{key}/transitions",
            body={"transition": {"id": transition_id}},
        )

    def add_comment(self, key: str, body_adf: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/rest/api/3/issue/{key}/comment",
            body={"body": body_adf},
        )

    def list_comments(self, key: str) -> dict[str, Any]:
        return self._request("GET", f"/rest/api/3/issue/{key}/comment")

    # --- custom-field endpoints (Phase 3) -----------------------------

    def list_fields(self) -> list[dict[str, Any]]:
        """All fields visible to this account, including custom fields.

        Used by /kanban:initjira step 4 [a] (browse existing fields).
        """
        return self._request("GET", "/rest/api/3/field")

    def create_custom_field(
        self,
        name: str,
        description: str = "",
        type_key: str = "com.atlassian.jira.plugin.system.customfieldtypes:select",
        searcher_key: str = "com.atlassian.jira.plugin.system.customfieldtypes:multiselectsearcher",
    ) -> dict[str, Any]:
        """Create a single-select custom field. Requires Jira admin privileges.

        Returns the new field object including `id` (e.g. `customfield_10042`).
        """
        return self._request(
            "POST",
            "/rest/api/3/field",
            body={
                "name": name,
                "description": description,
                "type": type_key,
                "searcherKey": searcher_key,
            },
        )

    def list_field_contexts(self, field_id: str) -> dict[str, Any]:
        """List contexts for a custom field. The default context is the
        scope where adding an option makes that option available everywhere.
        """
        return self._request("GET", f"/rest/api/3/field/{field_id}/context")

    def list_field_options(self, field_id: str, context_id: int) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/rest/api/3/field/{field_id}/context/{context_id}/option",
        )

    def add_field_option(
        self, field_id: str, context_id: int, value: str
    ) -> dict[str, Any]:
        """Add a single-select option to a custom field's context."""
        return self._request(
            "POST",
            f"/rest/api/3/field/{field_id}/context/{context_id}/option",
            body={"options": [{"value": value}]},
        )

    def get_priorities(self) -> list[dict[str, Any]]:
        """GET /rest/api/3/priority — list of `{id, name, description}` rows.

        Used by import-tasks pre-flight: validate local priority strings
        against the actual project / scheme before creating any issues.
        Different Atlassian sites may have customised priority schemes,
        so we don't bake a fixed list into the plugin.
        """
        return self._request("GET", "/rest/api/3/priority")

    def update_issue(self, key: str, fields: dict[str, Any]) -> None:
        """PUT /issue/{key} with `fields` payload. Used by AgentRef assign
        to write the AP custom field directly.
        """
        self._request(
            "PUT",
            f"/rest/api/3/issue/{key}",
            body={"fields": fields},
        )

    def delete_issue(self, key: str, *, delete_subtasks: bool = False) -> None:
        """DELETE /rest/api/3/issue/{key}. Used by /kanban:delete (#55).

        `delete_subtasks=True` cascades to children; default leaves them
        orphaned (Jira's own default). A 403 here means the agent's
        account lacks "Delete Issues" permission in the project.
        """
        params = {"deleteSubtasks": "true" if delete_subtasks else "false"}
        self._request("DELETE", f"/rest/api/3/issue/{key}", query=params)

    # --- screens (0.3.2: AP-field association, #6) -------------------

    def list_screens(self, *, query: str | None = None) -> dict[str, Any]:
        """GET /rest/api/3/screens, optionally filtered by `queryString`.

        Used to find project-scoped screens that should carry the AP
        custom field. Most teams have screens whose names mention the
        project key or name; passing the project key as the query is
        a reasonable heuristic.
        """
        params = {"queryString": query} if query else None
        return self._request("GET", "/rest/api/3/screens", query=params)

    def list_screen_tabs(self, screen_id: int | str) -> list[dict[str, Any]]:
        """GET /rest/api/3/screens/{id}/tabs."""
        return self._request("GET", f"/rest/api/3/screens/{screen_id}/tabs")

    def list_screen_tab_fields(
        self, screen_id: int | str, tab_id: int | str
    ) -> list[dict[str, Any]]:
        """GET /rest/api/3/screens/{id}/tabs/{tab_id}/fields."""
        return self._request(
            "GET", f"/rest/api/3/screens/{screen_id}/tabs/{tab_id}/fields"
        )

    def add_field_to_screen_tab(
        self,
        screen_id: int | str,
        tab_id: int | str,
        field_id: str,
    ) -> dict[str, Any]:
        """POST /rest/api/3/screens/{id}/tabs/{tab_id}/fields.

        Adds a custom field to a screen tab so issues can have its value
        set at create / edit time. Idempotent on the server side: adding
        an already-present field returns 200 with the existing record.
        Requires Jira global admin (a 403 here is a real authorization
        signal, not a bug).
        """
        return self._request(
            "POST",
            f"/rest/api/3/screens/{screen_id}/tabs/{tab_id}/fields",
            body={"fieldId": field_id},
        )

    # --- issue links (0.3.3: /kanban:block --blocked-by, #8) ---------

    def create_issue_link(
        self, type_name: str, inward_key: str, outward_key: str
    ) -> None:
        """POST /rest/api/3/issueLink — link two issues.

        Jira link types are bidirectional. `type_name="Blocks"` reads as
        `inwardIssue` blocks `outwardIssue`; equivalently `outwardIssue`
        is blocked by `inwardIssue`. So when /kanban:block creates a
        link, the *blocker* is `inwardIssue` and the card we're
        transitioning is `outwardIssue`.

        Returns 201 No Content on success. 404 if either key is missing.
        """
        self._request(
            "POST",
            "/rest/api/3/issueLink",
            body={
                "type": {"name": type_name},
                "inwardIssue": {"key": inward_key},
                "outwardIssue": {"key": outward_key},
            },
        )


# -------- helpers ----------------------------------------------------------


# URL detector for clickable-link markup. Conservative on tail characters
# so a URL at end-of-sentence (e.g. "see https://x.com.") doesn't swallow
# the period, and a URL inside parens / quotes doesn't pull the closing
# bracket in. ADF doesn't auto-linkify plain text — without an explicit
# `link` mark the URL renders as un-clickable text.
import re as _re
_URL_RE = _re.compile(r"https?://[^\s<>\"\)\]]+")


def _text_to_inline_nodes(text: str) -> list[dict[str, Any]]:
    """Split `text` on URLs and return ADF text nodes — URL spans get
    a `link` mark so they render clickable in Jira UI.

    Returns a list ready to drop into a paragraph's `content`. Empty
    spans collapse so adjacent URLs don't yield empty text nodes.
    Trailing punctuation that's commonly attached to a sentence
    (`.`, `,`, `;`, `:`, `!`, `?`) is stripped off the URL and put back
    in a following plain-text node, so "see https://x.com." parses as
    URL "https://x.com" + plain ".".
    """
    if not text:
        return []
    out: list[dict[str, Any]] = []
    pos = 0
    for m in _URL_RE.finditer(text):
        # Plain text segment before the URL
        if m.start() > pos:
            out.append({"type": "text", "text": text[pos:m.start()]})
        url = m.group(0)
        # Strip trailing punctuation that's almost certainly NOT part
        # of the URL ("see https://x.com." → URL is x.com, "." is prose)
        trailer = ""
        while url and url[-1] in ".,;:!?":
            trailer = url[-1] + trailer
            url = url[:-1]
        if url:
            out.append({
                "type": "text",
                "text": url,
                "marks": [{"type": "link", "attrs": {"href": url}}],
            })
        if trailer:
            out.append({"type": "text", "text": trailer})
        pos = m.end()
    if pos < len(text):
        out.append({"type": "text", "text": text[pos:]})
    return out


def text_to_adf(text: str) -> dict[str, Any]:
    """Wrap a markdown-or-plain body in Atlassian Document Format.

    Used for comments and issue descriptions. The body is parsed as a
    markdown subset (headings, bold/italic, code spans + fences,
    bullet/ordered lists, blockquotes, ``[text](url)`` links) and
    emitted as proper ADF nodes; bare URLs in text are still
    auto-linkified so plain-text payloads round-trip unchanged. The
    SPEC §9 prefix is added at the driver layer.

    Markdown support was added after #57 to fix the "agent emits
    ``## Heading`` and Jira shows the literal hashes" bug. See
    ``lib/markdown_adf.py`` for the supported subset.
    """
    # Local import — markdown_adf is a sibling lib module. Imported at
    # call time so the import graph stays acyclic if either module
    # grows additional cross-references later.
    from lib.markdown_adf import markdown_to_adf
    return markdown_to_adf(text or "")


def adf_to_text(adf: dict[str, Any] | None) -> str:
    """Best-effort flatten of an ADF body back to plain text. Concatenates
    every text node in document order. Lossy by design.
    """
    if not adf:
        return ""
    out: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "text":
                t = node.get("text")
                if isinstance(t, str):
                    out.append(t)
            for child in node.get("content", []) or []:
                walk(child)
            if node.get("type") in {"paragraph", "heading"}:
                out.append("\n")
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(adf)
    return "".join(out).strip()


def adf_extract_mentions(
    adf: dict[str, Any] | None,
    target_account_id: str | None = None,
) -> list[dict[str, str]]:
    """Walk an ADF tree and return every `mention` node.

    Each result is `{"accountId": ..., "text": "@..."}`. When
    `target_account_id` is given, filter to only matching mentions.

    Used by find-mentions to detect when a human has @-mentioned the
    shared agent account. ADF `mention` node shape:
        {"type": "mention", "attrs": {"id": "<accountId>", "text": "@Name"}}
    """
    out: list[dict[str, str]] = []
    if not adf:
        return out

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "mention":
                attrs = node.get("attrs") or {}
                acct = attrs.get("id")
                txt = attrs.get("text", "")
                if isinstance(acct, str) and (
                    target_account_id is None or acct == target_account_id
                ):
                    out.append({"accountId": acct, "text": str(txt)})
            for child in node.get("content", []) or []:
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(adf)
    return out


def text_to_adf_with_mention(
    prefix_text: str,
    mention_account_id: str,
    mention_display: str,
    body_text: str,
) -> dict[str, Any]:
    """Build an ADF doc that prepends `prefix_text` (as its own paragraph,
    rendered bold) then a paragraph that begins with an @-mention node
    followed by the reply body.

    Used by /kanban:reply so the bot's reply notifies the human via Jira's
    native mention plumbing. Empty `prefix_text` collapses the prefix
    paragraph (used when caller already wrapped the prefix elsewhere). The
    prefix renders as bold via an ADF `strong` mark — markdown in
    `prefix_text` is intentionally NOT parsed because the SPEC §9 prefix
    text is fixed-shape and rendering ``**...**`` literally there would
    show stars instead of bold (#27).

    The reply body, by contrast, IS parsed as markdown (subset documented
    in `lib/markdown_adf.py`). When the body is a single paragraph it
    sits inline with the @mention chip — preserving the chat-bubble
    look. Multi-paragraph / list / code-fence bodies put the mention on
    its own paragraph and emit the body's blocks as siblings, so
    structured replies render correctly.
    """
    from lib.markdown_adf import markdown_to_adf
    content: list[dict[str, Any]] = []
    if prefix_text:
        content.append({
            "type": "paragraph",
            "content": [{
                "type": "text",
                "text": prefix_text,
                "marks": [{"type": "strong"}],
            }],
        })
    mention_node = {
        "type": "mention",
        "attrs": {
            "id": mention_account_id,
            "text": f"@{mention_display}" if mention_display else "@",
        },
    }
    if not body_text:
        content.append({"type": "paragraph", "content": [mention_node]})
        return {"type": "doc", "version": 1, "content": content}

    body_doc = markdown_to_adf(body_text)
    body_blocks = body_doc.get("content") or []
    first = body_blocks[0] if body_blocks else None

    if first and first.get("type") == "paragraph" and len(body_blocks) == 1:
        # Single-paragraph reply — inline next to the mention chip with
        # a leading space. Merge the space into the first inline text
        # node when possible (avoids fragmenting ADF into [" ", text]
        # for the common single-line case).
        inline_nodes = list(first.get("content") or [])
        merged: list[dict[str, Any]] = [mention_node]
        if inline_nodes and inline_nodes[0].get("type") == "text" and not inline_nodes[0].get("marks"):
            inline_nodes[0] = dict(inline_nodes[0])
            inline_nodes[0]["text"] = " " + inline_nodes[0]["text"]
            merged.extend(inline_nodes)
        else:
            merged.append({"type": "text", "text": " "})
            merged.extend(inline_nodes)
        content.append({"type": "paragraph", "content": merged})
    else:
        # Multi-block reply (lists, code fences, multiple paragraphs).
        # Put the mention alone, then emit body blocks as siblings so
        # each renders with its proper ADF shape.
        content.append({"type": "paragraph", "content": [mention_node]})
        content.extend(body_blocks)

    return {"type": "doc", "version": 1, "content": content}
