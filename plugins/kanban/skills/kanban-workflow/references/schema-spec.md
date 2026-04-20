# kanban.json Schema — Field Reference

Canonical schema is `kanban.schema.json` (JSON Schema draft-07). This file explains it in prose for AI consumption.

## Top-level

| Field | Type | Required | Notes |
|---|---|---|---|
| `$schema` | string | optional | Path to `kanban.schema.json`. Keep pointed at `./kanban.schema.json`. |
| `schema_version` | integer | ✓ | Currently `1`. Never decrement. Bump only on breaking changes. |
| `meta` | object | ✓ | See below. |
| `tasks` | array of task | ✓ | May be empty. |

## `meta`

| Field | Type | Required | Notes |
|---|---|---|---|
| `priorities` | string[] | ✓ | Ordered highest → lowest. Default `["P0","P1","P2","P3"]`. |
| `categories` | string[] | optional | User-defined. May be empty. |
| `columns` | string[] | ✓ | Always exactly `["TODO","DOING","DONE","BLOCKED"]`. Do not rename or reorder. |
| `created_at` | ISO 8601 | ✓ | Set once at `/kanban:init`. Do not modify. |
| `updated_at` | ISO 8601 | ✓ | Update on every write. |

## `task`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | ✓ | Format `task-NNN`, min 3 digits. Monotonically increasing. |
| `title` | string | ✓ | Single line, imperative ideally. |
| `column` | enum | ✓ | One of `meta.columns`. |
| `priority` | string | ✓ | One of `meta.priorities`. |
| `category` | string\|null | optional | If set, must match one of `meta.categories`. |
| `tags` | string[] | optional | Free-form. |
| `depends` | string[] | optional | Other task ids. Cycles forbidden. |
| `created` | ISO 8601 | ✓ | Immutable. |
| `updated` | ISO 8601 | ✓ | Set on every mutation. |
| `started` | ISO 8601\|null | conditional | Required when `column == DOING` or `DONE`. |
| `completed` | ISO 8601\|null | conditional | Required when `column == DONE`. |
| `assignee` | string\|null | optional | `claude-code`, a human name, or null. |
| `description` | string | optional | Multi-line markdown allowed. Do NOT store secrets. |
| `comments` | comment[] | optional | Append-only in practice. |
| `custom` | object | optional | Schema-free. Use for `blocked_reason`, `estimated_hours`, etc. |

## `comment`

```json
{ "author": "kirin | claude-code | <other>", "ts": "ISO 8601 tz", "text": "..." }
```

Comments are the preferred channel for AI → human communication. Append, never rewrite.

## Column invariants

- `TODO`: `started = null`, `completed = null`.
- `DOING`: `started != null`, `completed = null`, exactly one assignee that is working now.
- `DONE`: `started != null`, `completed != null`. Immutable.
- `BLOCKED`: `custom.blocked_reason` is a non-empty string.

## Timestamp discipline

- Always ISO 8601 with timezone (e.g. `2026-04-20T14:30:00+08:00`).
- Never emit `Z` unless the project truly runs in UTC.
- Use the system timezone (`date -Iseconds` on Linux / macOS).
