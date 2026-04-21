# memory（stub）

*[English](./README.md)*

[claude-workbench](../../README_zhtw.md) 全家族的一員。

**狀態**：尚未實作。設計見 [`SPEC.md §5`](../../SPEC.md)。

v0.1.0 規劃內容：
- SQLite + `sqlite-vss` vector store（`memory.db`）
- `sentence-transformers/all-MiniLM-L6-v2` embeddings（本機、對 CPU 友善）
- MCP server 提供 `memory.save`、`memory.search`、`memory.list_recent`、`memory.get`、`memory.update`、`memory.forget`
- `SessionStart` hook 自動注入專案相關記憶
- `Stop` hook 把 session 摘要寫進 memory
- `workbench-memory` CLI（給相鄰 plugin 做跨 plugin 整合用）

目前安裝這個 stub 不會做任何事。請等 v0.1.0。
