# workbench-dev（meta，stub）

*[English](./README.md)*

[claude-workbench](../../README_zhtw.md) 全家族的一員。

**Meta-plugin** — 自己沒有任何 command、skill、hook。裝它會把完整的開發者 stack 一次拉進來：

- [`workbench`](../workbench) — 核心組合包（`kanban` + `notify` + `memory`）
- [`mentor`](../mentor) — 專案 onboarding 顧問 + 文件階層（Epic/Sprint/Issue/ADR） + 工作紀律
- 未來成員：`review`（AI code review）、`lint`（config-driven lint 提醒）

## 安裝

```bash
> /plugin marketplace add kirinchen/claude-workbench
> /plugin install workbench-dev@claude-workbench
```

## 目前狀態

- `workbench` — v0.0.1 stub（等 `memory` v0.1.0）
- `mentor` — v0.1.0 ✓（取代早期的 `docsync` 草稿）

在 `workbench` meta-bundle 能 pin 三個核心 plugin 的 `^0.1.0`（也就是 memory 完工後）之前，建議還是一個一個裝。

設計見 [`SPEC.md §9.2`](../../SPEC.md)。
