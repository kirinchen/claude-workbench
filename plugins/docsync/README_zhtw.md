# docsync

*[English](./README.md)*

[claude-workbench](../../README_zhtw.md) 全家族的一員——**dev 分類**。完整設計見 [`SPEC.md §6`](../../SPEC.md)。

讓 **code 變更** 和 **文件** 保持同步。**Config-driven, not prompt-driven**：per-project 的映射放在 `.claude/docsync.yaml`，由 `/docsync:init` 互動式產生（scan → interview → dry-run → write）。

## 為什麼

會變的文件（ARCHITECTURE.md、CODE_MAP.md、各 module 的 README）在 Claude 不斷改 code、卻沒動文件的過程中會逐漸失真。常見解法是把「改 X 時要更新 Y」硬塞進 `CLAUDE.md`——那是無結構、無可攜、無法驗證的。docsync 把這件事改成 team（以及 Claude）都能讀的版本控 YAML。

## 安裝

```bash
> /plugin install docsync@claude-workbench
> /docsync:init                  # 互動式設定
```

`/docsync:init` 會：

1. **Scan** repo——專案類型、modules、現有文件。
2. **Interview** 用 `AskUserQuestion` 一批最多 3 題——bootstrap docs、module→doc 映射、enforcement 等級、skip conditions。
3. **Dry-run** 對最近 ~20 個 git commit 跑——「如果 docsync v1 當時啟用，會 flag 什麼」。
4. **Write** `.claude/docsync.yaml` 並詢問是否 commit。

## Slash 指令

| 指令 | 目的 |
|---|---|
| `/docsync:init` | 互動式設定（scan → interview → dry-run → write） |
| `/docsync:check` | 自當前 git ref 以來手動掃描 pending 同步 |
| `/docsync:rules` | 顯示哪條規則命中特定路徑 |
| `/docsync:bootstrap` | 列出 plugin 會在 SessionStart 請 Claude 讀的 `bootstrap_docs` |
| `/docsync:validate` | 用 schema 驗證 `.claude/docsync.yaml` |

## Enforcement 等級

在 `.claude/docsync.yaml` → `enforcement` 設：

- `silent` — 只有 `/docsync:check` 會顯示 pending。
- `warn`（預設） — PostToolUse hook 在 context 裡提醒 Claude 每次 code 編輯。
- `block` — 當 `integration.kanban.block_done_if_pending: true` 時，`/kanban:done` 會被 docsync 擋下直到同步。

## CLI

`workbench-docsync` 是給相鄰 plugin 用的穩定整合介面：

```bash
workbench-docsync match <file-path> --format json       # 哪些規則適用？
workbench-docsync check --since <git-ref> --format json # 有 pending 嗎？
workbench-docsync summarize --session <id> --format json
workbench-docsync --health
```

全部唯讀。**永不**修改 YAML。

## Template

三份起手 template 隨附 in box—— `/docsync:init` 會選最接近你偵測到的專案類型那份：

- `docsync.example.yaml` — Rust 單一倉庫（Cargo workspaces）
- `docsync.python.yaml` — Python 專案（`pyproject.toml`）
- `docsync.js.yaml` — JS 單一倉庫（pnpm / lerna）

## 整合

- `docsync × kanban` — DONE gate：當 `integration.kanban.block_done_if_pending: true` 時觸發。
- `docsync × memory` — 當 `integration.memory.summarize_doc_changes: true` 時，session 結束持久化文件變更摘要。
- `docsync × notify` — 純被動。docsync 絕不直接推播；被擋的轉換透過 kanban 的 notify 路徑推（SPEC §8.6）。

## 分類

docsync 是 `dev` 分類——屬於 `workbench-dev` meta-bundle，不在核心 `workbench` bundle 裡。
