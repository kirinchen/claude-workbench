# claude-workbench

*[English](./README.md)*

一組 Claude Code plugin，把 CLI 變成一個**持久化、事件驅動**的 AI 工作空間。可以只裝一個、兩個、或全裝——每個 plugin 單獨都有用，裝在一起會互相加成。

> **狀態**：v0.1.0（草稿）。`kanban`、`notify`、`docsync` 已完工；`memory` 是剩下的核心 stub。完整設計見 [`SPEC.md`](./SPEC.md)，即時實作快照見 [`current_state.md`](./current_state.md)。
>
> **快速上手**：[`kanban`](./kanban_quickstart_zhtw.md) · [`notify`](./notify_quickstart_zhtw.md) · [`mentor`](./plugins/mentor/README.md) *(docsync 已由 mentor 取代——詳見 [`epic/mentor-plugin-spec.md`](./epic/mentor-plugin-spec.md))*

## Plugins

| Plugin | 分類 | 解決什麼 | 狀態 |
|---|---|---|---|
| [`kanban`](./plugins/kanban) | core | 任務狀態持續化 + 人 / AI 共用的工作佇列，透過 `kanban.json` | **v0.1.0 可用** |
| [`notify`](./plugins/notify) | core | 當 Claude 需要你回應時推播通知（Pushover） | **v0.1.0 可用** |
| [`memory`](./plugins/memory) | core | 跨 session 的 RAG 記憶（SQLite + embeddings，純本機） | v0.0.1 stub |
| [`mentor`](./plugins/mentor) | dev | Onboarding 顧問 — 規範 bootstrap 文件、Epic/Sprint/Issue/ADR 階層、agent 工作流程（取代 `docsync`） | **v0.1.0 可用** |
| [`workbench`](./plugins/workbench) | — | ★ 核心組合包（kanban + notify + memory） | meta，stub |
| [`workbench-dev`](./plugins/workbench-dev) | — | ★ 開發者組合包（workbench + docsync） | meta，stub |

可以一個一個裝漸進採用，也可以等 `memory` v0.1.0 出來後直接裝 meta-bundle。

## 為什麼要有這個專案

Claude Code 的預設用法是**以 session 為範圍**：開啟 session → 下指令 → 等結果 → 關掉。這會造成幾個落差：context 消散、沒有持續性的任務佇列、沒有事件驅動的觸發機制、不同機器之間沒有共享狀態、知識也不會累積。

Workbench 把這四個痛點拆成三個可以互相組合的獨立 plugin：

1. **狀態持久化** — `kanban.json` 放在專案根目錄，是唯一事實來源（single source of truth）。
2. **事件觸發 Claude** — 透過 cron / git hook / webhook 驅動 headless `claude -p`。
3. **Claude 能找到你** — Pushover（以及未來其他 provider）在需要決策時推播。
4. **知識累積** — 每個專案自己的 RAG 記憶，在 session 開始時自動注入。

## 安裝

```bash
# 1. 在任一專案裡啟動 Claude Code
cd my-project
claude

# 2. 加入 marketplace（repo 已 public；若是 private 用 SSH URL）
> /plugin marketplace add kirinchen/claude-workbench

# 3. 安裝你需要的 plugin
> /plugin install kanban@claude-workbench       # 可用
> /plugin install notify@claude-workbench       # 可用（Pushover）
> /plugin install mentor@claude-workbench       # 可用（dev 分類，取代 docsync）
> /plugin install memory@claude-workbench       # 尚未釋出
> /plugin install workbench@claude-workbench    # bundle（等 memory 完工）
```

裝完之後看該 plugin 的 quickstart——連結在檔案頂端。

> **不用改 shell rc**。Hook script 和 slash command 執行時會自動把 `~/.claude-workbench/bin` 加進 `PATH`，notify 的 token 由 `/notify:setup` 寫進 `~/.claude-workbench/.env` 自動讀取。如果你想**在 terminal 手動**執行 `workbench-*` CLI（純 debug 用），才需要手動 `export PATH="$HOME/.claude-workbench/bin:$PATH"`。

### 兩個差一個字的 identifier

安裝流程用到**兩個長得很像但不同意義的名字**。新手最常踩的坑就是搞混：

| 步驟 | 它指的是什麼 | 來源 |
|---|---|---|
| `/plugin marketplace add `**`kirinchen/claude-workbench`** | GitHub **repo**（會自動展開成 `https://github.com/kirinchen/claude-workbench`） | 你的 GitHub `owner/repo` 路徑 |
| `/plugin install kanban@`**`claude-workbench`** | **Marketplace 名稱**——來自 `.claude-plugin/marketplace.json` 裡的 `"name"` 欄位 | 在 marketplace metadata 裡定義，不是 repo 名 |

兩個現在同名是**刻意設計**。如果未來把 repo 改名成 `cwb`，add 指令會變成 `kirinchen/cwb`，但 install 仍然是 `kanban@claude-workbench`（除非你同時也改了 marketplace.json 的 `name` 欄位）。`add` 還支援：完整 HTTPS URL、SSH URL（給 private repo）、本機路徑——詳見 [Claude Code plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces)。

## 快速體驗 — `kanban`

```bash
> /kanban:init --with-examples      # 建立 kanban.json + schema
> /kanban:status                    # 唯讀的狀態總覽
> /kanban:next                      # 挑一個 TODO 移到 DOING
> /kanban:done --note="deployed"    # 關掉當前 DOING 任務
```

Claude 對 `kanban.json` **會做的**：

- 遵守 `depends`——絕不會開始一個依賴未完成的任務。
- 依照優先順序（`meta.priorities`，預設 P0 最優先）。
- 遇到含糊處會在任務上 append comment 問你，而不是瞎猜。
- 自動把 kanban 狀態變更提交為獨立 commit。

**不會做的**：

- 不會直接 `Edit`/`Write` `kanban.json`（被 `kanban-guard.sh` 擋住）。
- 不會修改 `DONE` 欄位裡的任務。

## 組合使用

**Capability detection**（SPEC §8.7）：每個 plugin 都會檢查 sibling 的 CLI（`workbench-notify`、`workbench-memory`、`workbench-docsync`）是否存在，透過 `--health` 驗證可用，沒裝就優雅降級。

| 組合 | 效果 | 狀態 |
|---|---|---|
| `kanban × notify` | 狀態轉換觸發推播（BLOCKED → 高優先度）。 | 線路已接，E2E 未測 |
| `kanban × memory` | `/kanban:next` 查詢過去 session；`/kanban:done` 存完工筆記。 | 等 memory |
| `kanban × mentor` | 新 Issue 可自動產生 kanban task；可選的 Issue Acceptance Criteria DONE gate。 | 線路已接，等 E2E |
| `notify × memory` | 決策提示會附帶「上次你選了 X」。 | 等 memory |
| `mentor × memory` | Sprint retro + accepted ADR 持久化到 memory。 | 線路已接，等 memory |
| `mentor × notify` | Sprint 結束 / Epic 完成推播。 | 線路已接，等 E2E |

## Roadmap

依 [`SPEC.md §13`](./SPEC.md)：

- **Phase 0** ✓ — 骨架、marketplace、schema
- **Phase 1** ✓ — `kanban` v0.1.0（此版釋出）
- **Phase 2** — `notify` v0.1.0（Pushover）
- **Phase 3** — `kanban × notify` 整合
- **Phase 4** — `memory` v0.1.0（SQLite + embeddings + MCP）
- **Phase 5** — 三方整合
- **Phase 6** — `workbench` 組合包正式釋出

## 檔案結構

```
claude-workbench/
├── SPEC.md                             # 設計文件（workbench 全家族）
├── current_state.md                    # 實作快照
├── .claude-plugin/marketplace.json     # 6 個 plugin 條目
├── plugins/
│   ├── kanban/                         # v0.1.0（可用）
│   ├── notify/                         # v0.1.0（可用 — Pushover）
│   ├── memory/                         # v0.0.1（stub）
│   ├── mentor/                         # v0.1.0（可用 — dev 分類，取代 docsync）
│   ├── workbench/                      # v0.0.1（meta stub）
│   └── workbench-dev/                  # v0.0.1（meta stub）
└── schema/
    ├── kanban.schema.json              # canonical schema
    └── mentor.schema.json              # canonical schema
```

## 移除

```bash
> /plugin uninstall kanban@claude-workbench
> /plugin marketplace remove claude-workbench
```

你的 `kanban.json` 和 `kanban.schema.json` 不會被動。

## 授權

MIT——見 [`LICENSE`](./LICENSE)（待補）。

## 延伸閱讀

- [`SPEC.md`](./SPEC.md) — 完整 spec
- [`current_state.md`](./current_state.md) — 實作快照
- 快速上手：[`kanban`](./kanban_quickstart_zhtw.md) · [`notify`](./notify_quickstart_zhtw.md) · [`mentor`](./plugins/mentor/README.md)
- [Claude Code plugins docs](https://code.claude.com/docs/en/plugins)
- [Claude Code hooks reference](https://code.claude.com/docs/en/hooks)
- [Model Context Protocol](https://modelcontextprotocol.io)
