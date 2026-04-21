# memory (stub)

*[繁體中文](./README_zhtw.md)*

Part of the [claude-workbench](../../README.md) family.

**Status**: Not yet implemented. See [`SPEC.md §5`](../../SPEC.md) for the design.

Planned in v0.1.0:
- SQLite + `sqlite-vss` vector store (`memory.db`)
- `sentence-transformers/all-MiniLM-L6-v2` embeddings (local, CPU-friendly)
- MCP server exposing `memory.save`, `memory.search`, `memory.list_recent`, `memory.get`, `memory.update`, `memory.forget`
- `SessionStart` hook auto-injects project-relevant memories
- `Stop` hook summarises session into memory
- `workbench-memory` CLI (used by sibling plugins for cross-plugin integration)

Installing this stub currently does nothing. Please wait for v0.1.0.
