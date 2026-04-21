# Doc update patterns

Templates for the three most common doc types docsync governs. These are starting points — match the style of the existing doc above all.

## CODE_MAP.md — per-module section

**Shape**: one section per module, each section describes **what the module contains and why**, not the file-by-file listing.

```markdown
## position-manager

Manages open positions for each exchange account: fill tracking, PnL rollup,
and liquidation proximity. Owns `Position` and `PositionBook` types.

Entry points:
- `PositionBook::apply_fill` — ingest a fill event from the exchange.
- `PositionBook::mark_price` — mark all positions at the current mid.

Not in this module:
- Order placement (see `execution`).
- Risk limits (see `risk`).
```

**Good updates look like**: a changed bullet, an added entry point, a re-explained boundary. **Bad updates look like**: "refactored this module" or a diff summary.

## ARCHITECTURE.md

**Shape**: cross-module narrative. Sections are about *relationships*, not individual modules.

**When to update** (maps to `required_if: architecture_changed`):

- New module was introduced (or deleted).
- Cross-module dependency direction changed.
- A synchronous call became async (or vice versa).
- A bounded context was split or merged.

**Not an architecture change**: internal refactor, adding a new function inside an existing module, renaming a type.

Template for a new module being added:

```markdown
### position-manager ↔ execution

`execution` subscribes to `PositionBook::position_updated` events and uses the
current exposure to size new orders. `position-manager` never calls
`execution` directly — the direction is strictly event-driven.
```

## Per-module README.md

**Shape**: pitched at a developer who is about to edit *this module*. Covers: what it does, how to run its tests, any non-obvious invariants, and the "please don't" list.

**When to update** (maps to `required_if: params_changed` for param-focused READMEs):

- A tunable config parameter was added, removed, renamed, or had its default changed.
- A tunable's *meaning* changed even if the name stayed the same.

Good structure:

```markdown
# position-manager

Rolls up fills into position state.

## Config (dynamic_param.md)
| Param | Default | Meaning |
|---|---|---|
| `grid.step_bps` | 50 | Price step between grid levels, in basis points. |

## Invariants
- A `Position` can never have negative quantity in the `Long` book.

## Testing
`cargo test -p position-manager`
```

## Schema files (JSON Schema, OpenAPI)

**When to update** (maps to `required_if: schema_changed` or `api_changed`):

- A field was added, removed, or renamed.
- A type constraint changed (string → enum, nullable flipped, required list changed).
- An API endpoint's request/response shape changed.

Never edit the schema **and** leave a referring doc stale — both are in the rule, both get updated in the same session.

## What to never do

- Write "Updated on 2026-04-21" headers. Git already knows.
- Delete doc content without a replacement. Stubs like "(TBD)" rot silently — better to remove than to leave a broken promise.
- Invent invariants you haven't verified in code. Doc claims must be grounded.
