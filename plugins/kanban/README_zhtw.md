# kanban

*[English](./README.md)*

[claude-workbench](../../README_zhtw.md) 全家族的一員。Claude Code 的任務狀態持續化 + workflow 文法。

**兩種儲存模式，同一套 slash command：**

| 模式 | 儲存位置 | 適合 |
|---|---|---|
| **local** | 專案根目錄的 `kanban.json` | 個人專案、單機、不用團隊共享 |
| **jira**  | Jira Cloud（per-board 設定 + per-machine token） | 多機器團隊、async 協作、手機審核 |

可以先用 `/kanban:init`（local）之後再 `/kanban:initjira` 升級到 Jira — slash command 介面不變。

完整 walk-through 見 [`kanban_quickstart_zhtw.md`](../../kanban_quickstart_zhtw.md)，完整設計見 [`SPEC_zhtw.md §3`](../../SPEC_zhtw.md)。

## 安裝

```
> /plugin marketplace add kirinchen/claude-workbench
> /plugin install kanban@claude-workbench
> /kanban:init                     # local mode — scaffold kanban.json
# (選用) 切換到 Jira-backed:
> /kanban:initjira                 # 互動式 setup
> /kanban:assign-ap <name>         # 這個 repo 的 AP（Jira routing 用）
```

## Slash 指令清單

完整可用清單以 Claude Code 的 `/` autocomplete 為準（會反映你目前安裝的 plugin）。kanban 0.3.20 為例：

### 日常工作流

| 指令 | 做什麼 |
|---|---|
| `/kanban:status` | 唯讀的看板總覽（driver-aware） |
| `/kanban:sync` | 拉這個 AP 的 open-card 摘要 |
| `/kanban:doing` | 工作 DOING 池 — 讀完所有屬於你的卡片，依合理順序執行 *(Jira；local mode 用 `/kanban:next`)* |
| `/kanban:done` | 把任務（預設目前 DOING）標 APPROVED |
| `/kanban:block <key>` | 把任務移到 BLOCKED（要寫 reason） |
| `/kanban:question <key> "<text>"` | 在卡片 post 問題並轉到 BLOCKED |
| `/kanban:reply <key>` | 對卡片 post 回覆，可選 `@`-mention 對方 |

### Inbox / 非同步訊號

| 指令 | 做什麼 |
|---|---|
| `/kanban:mentions` | 列出 `@`-mention 你 agent 帳號的 comments / descriptions（你的收件匣） |
| `/kanban:reconcile` | 找出 canonical 看板看不到的卡片（unmapped status、missing AP） |

### 卡片生命週期

| 指令 | 做什麼 |
|---|---|
| `/kanban:create-sub <parent>` | 從 parent issue 衍生 N 張子卡，用 Jira issue link 連回去 |
| `/kanban:next` | Jira mode 已 DEPRECATED（用 `/kanban:doing`）；local mode 還能用 |

### Setup / 設定（Jira）

| 指令 | 做什麼 |
|---|---|
| `/kanban:init` | 在當前專案建立 `kanban.json` + schema |
| `/kanban:initjira` | 把專案從 local 切到 Jira-backed（5-step 互動式；偵測到 board 已有 config 時跳過 DSL/AP-discovery，直接 pull） |
| `/kanban:reset-credentials` | 設定或更新這台機器的 Jira credentials *(secret-safe — 你自己在自己 terminal 跑)* |
| `/kanban:push-board-config` | 把這個 repo 的 `backend.jira` 推到 Jira project property `kanban-config`（admin-only；team 共用權威設定） |
| `/kanban:pull-board-config` | 從 Jira-side 權威 config 重新整理 local cache（`/kanban:sync` 每 8h 自動觸發；這個指令強制立即跑） |
| `/kanban:show-board-config` | 唯讀檢視 Jira-side `kanban-config` 內容 |
| `/kanban:assign-ap <name>` | 設定這個 repo 的 Agent Property（寫進 `.claude/kanban-agent.json`） |
| `/kanban:register-ap <name>` | 註冊新的 AP value 到 Jira AP custom field |
| `/kanban:fix-ap-screen` | 把 AP custom field attach 到專案 screen（修 issue #6） |
| `/kanban:edit-conventions` | 撰寫或編輯團隊 `conventions` block — narrative notes + per-team toggles |
| `/kanban:show-conventions` | 顯示團隊 `conventions` block（read-only） |
| `/kanban:enable-automation` | 裝一個 trigger 讓 Claude Code 在 `kanban.json` 變動時自動跑（cron / git hook） |
| `/kanban:whoami` | 顯示目前的 driver / board / AP / token 有效性 / board-config cache age |

### 已 Deprecated

| 指令 | 替代 |
|---|---|
| `/kanban:next`（Jira mode） | `/kanban:doing`（#33） |
| `/kanban:showjira-code`、`/kanban:import-jira-code`、`/kanban:initjira-by-code` | `/kanban:push-board-config` + `/kanban:pull-board-config`（0.3.27 移除 — migration 步驟看 CHANGELOG） |

## 核心概念

- **Canonical columns**：`TODO → DOING → BLOCKED → REVIEW → APPROVED → CANCELLED`。Slash command 永遠講 canonical 名稱；Jira driver 透過 `transitions` DSL 翻譯。
- **Compound transitions**（`v0.3+`）：`BLOCKED > In Progress + Label` 讓多個 canonical state 共享同一個 Jira status，靠 label disambiguate — 詳見 `epic/kanban_plugin_ Jira_backend_driver_UPDATE.md`。
- **Agent Property (AP)**：一個 Jira single-select custom field，把卡片 routing 到特定 agent / repo。每個 repo 在 `.claude/kanban-agent.json#ap` 宣告自己的 AP；像 `/kanban:doing` 這類命令會用它 filter（`cf[<id>] = "<repo's ap>"`）。
- **Conventions**：per-team narrative notes + opt-in toggles（例如 `blockedRequiresLink: true`），存在 Jira project 的 `kanban-config` property；接收端在 `/kanban:pull-board-config`（或 `/kanban:sync` 的 passive sync）拉到新內容後必須明確 acknowledge 才能繼續工作。
- **Board config single-source-of-truth**（since 0.3.27）：team 共用設定存在 Jira project property `kanban-config`。Admin 用 `/kanban:push-board-config` 推；其他人用 `/kanban:pull-board-config` 拉（手動或 8h passive-sync TTL 自動）。Local `kanban.json#backend.jira` 是 per-machine cache。

## Hooks

- **PreToolUse** (`kanban-guard.sh`) — 擋住對 `kanban.json` 的 Edit / Write。狀態變更要走 slash command。
- **PostToolUse** (`kanban-autocommit.sh`) — 當 `kanban.json` 是唯一 dirty file 時自動 commit 成獨立 commit。
- **SessionStart** (`kanban-session-check.sh`) — session 開始時印出 DOING / BLOCKED + mention 數量。
- **UserPromptSubmit** (`kanban-card-detect.sh`) — 當 prompt 裡貼到 Jira URL 或 `KEY-N`，把卡片標題、status、AP、最近的 comments 透過 `additionalContext` 注入（Jira mode only）。

## 檔案結構

```
plugins/kanban/
├── .claude-plugin/plugin.json
├── commands/                        # 24 個 slash command（一個命令一個 .md）
├── drivers/
│   ├── base.py                      # Driver protocol + Task/Comment dataclasses
│   ├── local.py                     # kanban.json driver
│   └── jira.py                      # Jira Cloud driver
├── lib/
│   ├── jira_client.py               # HTTP + ADF helpers
│   ├── kanban_io.py                 # atomic kanban.json read/write
│   ├── transitions.py               # compound transitions DSL
│   ├── ap_registry.py               # AP fuzzy-collision 檢查
│   ├── conventions.py               # team conventions block
│   ├── credentials.py               # ~/.claude-workbench/.env reader / writer
│   ├── card_cache.py                # 30s precheck cache
│   └── card_parser.py               # 從 prompt 文字抽 Jira KEY-N
├── hooks/hooks.json
├── scripts/
│   ├── kanban-guard.sh              # PreToolUse
│   ├── kanban-autocommit.sh         # PostToolUse
│   ├── kanban-session-check.sh      # SessionStart
│   ├── kanban-card-detect.sh        # UserPromptSubmit
│   ├── kanban_local.py              # local-driver helper
│   ├── jira_setup.py                # Jira-driver helper (subcommands)
│   ├── cron-runner.sh               # /kanban:enable-automation cron mode
│   └── test_phase{1..25}.py         # regression suite（108+ 個 check）
├── skills/
│   ├── kanban-workflow/SKILL.md     # generic + local-mode workflow
│   └── kanban-jira-agent/SKILL.md   # Jira-mode agent behaviour
└── templates/
    ├── kanban.example.json
    └── kanban.schema.json
```
