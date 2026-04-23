# mentor — 快速上手

*[English](./mentor_quickstart.md)*

> 你的專案從來沒有過的 onboarding 顧問。Mentor 告訴 Claude（和任何人類貢獻者）**先讀什麼**、**填哪些 template**、**用什麼順序工作**、**決定要記錄在哪裡**。

*完整設計見 [`epic/mentor-plugin-spec.md`](./epic/mentor-plugin-spec.md)，程式碼見 [`plugins/mentor/`](./plugins/mentor)。*

取代舊的 `docsync` plugin——範圍更廣，由 framework 驅動。

---

## 0. 前置條件

- 已安裝 Claude Code 並完成 `claude login`。
- 有 `python3`（hook 會用到；macOS / Linux 預裝；Windows 的 Git Bash 會附）。
- 一個你想要建立工作紀律的專案目錄。

**不需要改 shell rc**。Hook script 和 slash command 執行時會自動把 `~/.claude-workbench/bin` prepend 到 PATH。**只有**當你想**從 terminal 手動**敲 `workbench-mentor`（除錯用）時，才要自己在 shell rc 裡加那條 `export PATH`。

---

## 1. 選擇適合你專案的模式

Mentor 有兩種模式——在 `/mentor:init` 時挑一個：

| 模式 | 適合 | 文件階層 |
|---|---|---|
| **basic** | 個人專案、原型、工具、維護期專案 | `doc/SPEC.md` + tasks |
| **development** | 多 feature、有規劃週期、多 agent 協作 | `SPEC + Wiki + Epic + Sprint + Issue` + tasks |

不用想太多——basic 是刻意設計成最精簡的。等之後出現規劃壓力時再升級到 `development`（`/mentor:init --reset`）。

---

## 2. 安裝 plugin

在 Claude Code 裡（任一專案都行）：
```
> /plugin marketplace add kirinchen/claude-workbench
> /plugin install mentor@claude-workbench
```

---

## 3. 跑 init

```
> /mentor:init
```

它會做這些事——互動式，**絕不覆寫**既有檔案：
1. **Scan** 你的專案：類型（Rust monorepo / JS / Python / Go）、現有文件、相鄰 plugin（kanban / memory / notify）、有沒有殘留的 `.claude/docsync.yaml`。
2. **問**你哪一種模式（basic vs development）。如果線索很明確就只問一題。
3. **預覽**將要建立的結構——具體的檔案清單，標 `+`（新建）、`=`（保留）、`-`（跳過）。
4. **問**相鄰 plugin 的整合（一次一題 yes/no），只問實際偵測到的 plugin。
5. **（只在 development 模式）** 問要不要建立第一個 sprint，ID 是 `SPRINT-{year}-W{ISO-week}`。
6. **寫入**：`.claude/mentor.yaml` + 從選定 framework template 複製的目錄結構，然後跑 `install-cli.sh`，最後 `workbench-mentor --health` 確認。
7. 問要不要 commit（`chore: adopt mentor framework`）。

要重來：`/mentor:init --reset`。要跳過模式問題：`/mentor:init --mode=basic`（或 `--mode=development`）。

如果你以前裝過 docsync：`/mentor:migrate-from-docsync` 會把 `.claude/docsync.yaml` 翻成 `.claude/mentor.yaml`（舊檔備份成 `.bak`，**絕不刪除**）。

---

## 4. 驗證

在 Claude 裡：
```
> /mentor:status          # 目前模式 + active sprint + open issues
> /mentor:review          # 合規檢查——missing docs、frontmatter drift、orphan issues
```

在 Claude 外（**只在**你把 `~/.claude-workbench/bin` 加進 shell rc 的 PATH 時才能這樣用）：
```bash
workbench-mentor --health
#  -> exit 0，印 "mentor: ok"（.claude/mentor.yaml 載得進去就算 ok）
workbench-mentor active-sprint --format json
workbench-mentor trace task-042 --format json       # task → issue → epic
workbench-mentor review --format json               # 乾淨 exit 0；有違規 exit 2
```

---

## 5. 日常流程

### Basic 模式

只有兩層：`doc/SPEC.md`（事實）+ tasks（kanban.json 或 `doc/task.md`）。

```
> /kanban:next            # 有裝 kanban 的話——挑一個 TODO 開始做
> /mentor:status          # 看合規狀況 + 任務概覽
```

basic 模式**不要**引入 Epic / Sprint / Issue 概念——你選 basic 就是因為不想要這些 overhead。等規劃壓力長出來再升級到 development。

### Development 模式

完整階層 + 任務挑取紀律。Session 內的流程：

1. **SessionStart hook** 把 `bootstrap_docs` + active Sprint pointer 透過 `additionalContext` 浮上來。第一次改 code 之前先讀過。
2. **挑任務**→ trace 它：`workbench-mentor trace <task-id>` 顯示 `task → issue → epic`。讀 Issue 的 Acceptance Criteria，確認任務符合 Epic 的 Success Criteria，再開始。
3. **改 code**。
4. **PreToolUse hook** 在你編輯 Epic / Sprint / Issue / ADR 文件且缺 frontmatter 時**警告**（不會擋）。
5. **Stop hook** 在 session 結束時：印合規摘要；如果有裝 memory 且你把 ADR 推到 `accepted` 或結束了一個 Sprint，會把這些寫進 memory。

建立新的結構化文件：
```
> /mentor:new epic   --title="使用者認證系統"
> /mentor:new issue  --title="登入 rate limit" --epic=EPIC-001
> /mentor:new adr    --title="用 Postgres 當 session store"
> /mentor:new sprint                                  # ID 自動設成當前 ISO 週
```

`/mentor:new` 是建立 framework 文件的**唯一**方式——手刻沒 frontmatter 的文件會被 `/mentor:review` flag 出來。

---

## 6. 什麼東西寫在哪

| 情境 | 文件類型 |
|---|---|
| 新的大方向或功能集 | **Epic**——**為什麼** |
| 具體的問題 / bug / 需求 | **Issue**——**做什麼** + Acceptance Criteria |
| 值得記錄的技術決策 | **ADR**（在 `doc/Wiki/architecture-decisions/`）——context + decision |
| 背景知識 / how-to | **Wiki** 頁面——手寫在 `doc/Wiki/` |
| 要執行的工作單元 | **kanban task**（`/kanban:*`）——不是 mentor 文件 |

要避免的錯誤選擇：
- 不要為 bug fix 開 Epic（用 Issue）。
- Epic 裡不要寫**實作細節**——那是 Issue 的領域。
- Issue 裡不要寫**策略**——那是 Epic 的領域。
- 不要同時寫 `kanban.json` 和 `doc/task.md`——根據有沒有裝 kanban 二選一。

---

## 7. 相鄰 plugin 整合

全部 opt-in，透過 `.claude/mentor.yaml` `integration.*.enabled`（預設 `auto`——當相鄰 plugin 的 CLI 在 PATH 上**且** `--health` exit 0 時才啟用）：

| 組合 | 效果 |
|---|---|
| `mentor × kanban` | 新 Issue 可自動建立 kanban task；可選的 Issue Acceptance Criteria DONE gate |
| `mentor × memory` | Sprint retro + accepted ADR 持久化到 memory |
| `mentor × notify` | Sprint 結束 / Epic 完成推播 |

你不用直接呼叫——hook 和 `/mentor:*` 指令自己會發散。

---

## 8. 調整 config

編輯 `.claude/mentor.yaml`。關鍵旋鈕：

- `mode`：`basic` 或 `development`。要切換，建議走 `/mentor:init --reset`（會幫你 scaffold 新目錄），不要手改這欄。
- `paths.*`：如果你的文件不放 `doc/`，改這裡覆寫。
- `agent_behavior.bootstrap_docs`：SessionStart hook 浮上來的文件清單。Claude 必須在 session 開始就讀的東西通通加進來（例：`CONVENTIONS.md`、`ARCHITECTURE.md`）。
- `agent_behavior.require_issue_context`：development 模式預設 `true`——pickup 流程要求開始前要 trace 到 Issue。
- `integration.kanban.block_done_if_issue_incomplete`：opt-in 的 DONE gate。預設關（避免打斷現有的 kanban 流程）。
- `integration.memory.save_sprint_retro` / `save_adr`：Stop hook 跑時把這些寫進 memory。

改完之後用 `workbench-mentor --health` 和 `workbench-mentor review --format text` 再確認。**不用重啟**——config 每次 call 都重讀。

---

## 9. 疑難排解

| 症狀 | 原因 | 解法 |
|---|---|---|
| `/mentor:status` 說「not configured」 | 沒有 `.claude/mentor.yaml` | 跑 `/mentor:init` |
| `/mentor:new epic` 被擋說「basic mode」 | Epic / Sprint / Issue / ADR 只在 development 模式存在 | `/mentor:init --reset` 選 `development` |
| `workbench-mentor: command not found` **只在 terminal 裡** | `~/.claude-workbench/bin` 不在你 shell 的 PATH 上 | 這是正常的——slash command 和 hook 不需要這個。如果要從 terminal 手動用，加 `export PATH="$HOME/.claude-workbench/bin:$PATH"` 到 `~/.bashrc` |
| `workbench-mentor --health` exit 1：「no config」 | 這個專案裡沒 `.claude/mentor.yaml` | 跑 `/mentor:init`，或 `cd` 到對的專案根 |
| `/mentor:review` 報手刻文件 `no_frontmatter` | 你跳過 `/mentor:new`，文件沒 YAML 區塊 | 補上必要的 frontmatter——格式見 `frameworks/development/templates/<type>/<type>-template.md` |
| `/mentor:review` 報 `orphan_issue` | Issue 的 `epic:` 指向不存在的 Epic | 要嘛建立缺的 Epic（`/mentor:new epic`），要嘛改 Issue 的 `epic:` 欄位 |
| `/mentor:review` 報 `drift` | 文件有 frontmatter 但缺必要欄位（例：`id`、`status`、`date`） | 補上缺的欄位；每種類型的必要欄位寫在 `mentor-guard.py` |
| SessionStart 沒浮上來 bootstrap docs | Hook 默默失敗（Python 錯誤、config 缺失） | 用 `claude --debug` 看 output；確認 `python3` 在 PATH 上 |
| Mentor 好像「忘了」active sprint | Sprint 的 `status:` 不是 `active`，或 `end:` 已經過期 | 開 Sprint 文件，修 `status:` 或 `end:`；mentor 只浮 `status: active` 且 `end >= today` 的 Sprint |

`workbench-mentor review --format json` 是給你寫 script 處理違規時的結構化輸出。

---

## 10. 解除安裝

```
> /plugin uninstall mentor@claude-workbench
```

會留下：
- `.claude/mentor.yaml`（你的 config——通常會想留）。
- `doc/SPEC.md`、`doc/Epic/`、`doc/Sprint/`、`doc/Issue/`、`doc/Wiki/`（你的實際內容——絕對要留）。
- `~/.claude-workbench/bin/workbench-mentor`（symlink，現在是 dangling）。

要完全清乾淨（只在你決定放棄這個 framework 紀律時才這樣做）：
```bash
rm -f ~/.claude-workbench/bin/workbench-mentor
rm .claude/mentor.yaml
# 你的 doc/ 是你的——自己決定要留還是刪。
```

---

## 11. 下一步

- 加裝 `kanban`（如果還沒）：[`kanban_quickstart_zhtw.md`](./kanban_quickstart_zhtw.md)。兩個都裝後，mentor 的 Issue 生命週期可以和 kanban 的 task 狀態同步。
- 加裝 `notify`：[`notify_quickstart_zhtw.md`](./notify_quickstart_zhtw.md)。Sprint 結束和 Epic 完成可以推到你手機。
- 讀 [`epic/mentor-plugin-spec.md`](./epic/mentor-plugin-spec.md) 了解完整設計——包括兩種模式分割的原因和整合矩陣。
- 讀 [`plugins/mentor/skills/mentor-workflow/SKILL.md`](./plugins/mentor/skills/mentor-workflow/SKILL.md) 看 mentor 注入給 Claude 的具體行為。
