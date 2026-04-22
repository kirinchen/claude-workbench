# {{project_name}} — SPEC

*Single source of truth for this project. Describes what the system IS, not what was recently changed.*

---

## 1. Purpose

_One paragraph: what problem does this project solve, for whom?_

## 2. Boundaries

### In scope
- _Bullet list of things this project owns._

### Out of scope
- _Bullet list of things explicitly not handled here._

## 3. Architecture (sketch)

_ASCII diagram or short prose describing the main pieces and how they interact._

```
[client] -> [api] -> [db]
```

## 4. Invariants

_Things that must always be true. Each with a short rationale._

- **I1** — ...
- **I2** — ...

## 5. Public interface

### CLI / API / Commands

_List and short description. Each entry should be stable — if you need to change one, update this section in the same commit as the code change._

## 6. Configuration

_Environment variables, config files, defaults._

## 7. Deployment / distribution

_How this runs in production (or "N/A — local tool"). Any ops notes worth being in SPEC rather than a README._

## 8. Non-goals

_Things we deliberately won't do, with 1-line reason each._

---

*End of SPEC.md — keep it current; kill every claim that's no longer true.*
