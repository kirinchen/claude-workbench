---
title: Architecture (current state)
owner: null
---

# Architecture — Current State

> *How the system **actually** looks right now. Pair with [`../SPEC.md`](../SPEC.md) which describes intent.*
>
> **Maintenance rule**: when your code change goes beyond what this file describes
> (new component, removed component, interaction change, tech stack swap),
> update this file in the same change set. Trivial refactors and renames don't count.

## 1. Components

_Real components currently deployed/running. Names match what you see in the codebase._

- **`<component-name>`** — purpose · tech (lang/framework/version)
- ...

## 2. Interactions

_How components actually talk. ASCII or mermaid is fine._

```
[client] --HTTP--> [api] --SQL--> [db]
                       \--queue--> [worker]
```

## 3. Data flow

_Walk through the 1–2 most important request flows end-to-end._

1. Client posts X →
2. API validates Y →
3. Worker picks up Z →
4. ...

## 4. Tech stack snapshot

_Languages, frameworks, runtime versions currently in use. Source of truth is the lockfile; this section is for the human-readable summary._

- Language: `<lang>` `<version>`
- Framework: `<name>` `<version>`
- Datastore: `<name>` `<version>`
- Runtime: `<container/host>` `<version>`

## 5. External dependencies

_Third-party services / SaaS / APIs the system actually calls in production._

- `<service>` — purpose · auth method
- ...

## 6. Pointers to deeper docs

_Other `current_state/` files that go deeper. Agent adds these as needed (UML, CODEMAP, DATA_MODEL, etc.)._

- ...

---

*Anything in this file should be **verifiable from the running code right now**. If a claim here contradicts the code, the claim is wrong — fix it.*
