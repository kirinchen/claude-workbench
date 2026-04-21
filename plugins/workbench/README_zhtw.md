# workbench（meta）

*[English](./README.md)*

[claude-workbench](../../README_zhtw.md) 全家族的一員。

這是一個 **meta-plugin**——自己沒有任何 command、skill、hook。裝它會把三個相鄰的核心 plugin 一次拉進來：

- [`kanban`](../kanban) — 透過 `kanban.json` 管理任務生命週期
- [`notify`](../notify) — 當 Claude 需要你注意時推播
- [`memory`](../memory) — 跨 session 的持續性 RAG 記憶

## 安裝

```bash
> /plugin marketplace add kirinchen/claude-workbench
> /plugin install workbench@claude-workbench
```

## 目前狀態

- `kanban` — v0.1.0 ✓
- `notify` — v0.1.0 ✓
- `memory` — v0.0.1 stub（v0.1.0 再做真的）

在 `memory` v0.1.0 釋出前，建議還是一個一個裝。這個 bundle 目前主要是 roadmap 標記——dependency set 還沒 pin，等 memory 完工後會切成真正的 `^0.1.0` 約束。

設計見 [`SPEC.md §9`](../../SPEC.md)。
