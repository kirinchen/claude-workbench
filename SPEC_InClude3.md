# Claude Workbench — SPEC

**Project**: `kirin/claude-workbench`
**Version**: 0.1.0 (Draft)
**Last Updated**: 2026-04-20
**Author**: Kirin

---

## 1. 家族概觀

### 1.1 What

`claude-workbench` 是一組讓 Claude Code CLI 成為個人 AI 工作環境的 plugin 家族。透過三個核心 plugin 加上一個 meta-bundle,使用者可以**單獨安裝任一功能**,也可以**一鍵安裝全套**。

```
┌──────────────────────────────────────────────────────────┐
│  claude-workbench (marketplace)                           │
│                                                            │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐              │
│  │  kanban  │   │  notify  │   │  memory  │              │
│  │          │   │          │   │          │              │
│  │ 工作流狀態│   │ 人機介面 │   │ 長期記憶 │              │
│  └─────┬────┘   └─────┬────┘   └─────┬────┘              │
│        │              │              │                     │
│        └──────┬───────┴──────────────┘                     │
│               ▼                                            │
│        ┌──────────────┐                                   │
│        │  workbench   │   ← meta-plugin                   │
│        │   (bundle)   │     declares dependencies         │
│        └──────────────┘                                   │
└──────────────────────────────────────────────────────────┘
```

### 1.2 Why

使用 Claude Code 的典型痛點:

1. **任務狀態無法持久化** — session 關閉後 context 消失
2. **無法事件驅動** — 使用者必須主動 attend 才能跟 AI 互動
3. **離開電腦就斷線** — AI 需要決策時沒人看到
4. **知識不累積** — 每次 session 都從零開始

Workbench 的三個 plugin 正好各自解決其中一類問題:

| Plugin | 解決什麼 |
|---|---|
| **kanban** | 任務狀態持久化 + 人 / AI 共用工作列 |
| **notify** | AI 需要注意力時透過 Pushover 等管道通知使用者 |
| **memory** | 跨 session 的 RAG 知識庫,自動累積與注入相關 context |

三者獨立可用,組合時互相加乘。

### 1.3 Design Principles

1. **Has-a, not is-a** — 以 plugin 形式注入能力,不強迫 fork template
2. **Modular + composable** — 每個 plugin 單獨完整,偵測到 sibling plugin 時自動強化
3. **漸進式採用** — 先裝一個、用順後再加其他
4. **Deterministic engine + AI judgement** — 程式碼處理硬性規則,AI 處理判斷
5. **Cost-aware** — 預設走 Claude Pro/Max 訂閱(headless 模式),不燒 API credit
6. **Local-first** — 資料留在使用者機器,不送第三方服務

### 1.4 Target User

- 重度使用 Claude Code 的個人開發者
- 有多專案並行需求
- 熟悉 git / CLI / 基本 shell scripting
- 願意用訂閱方案換自主掌控

---

## 2. System Architecture

### 2.1 整體資料流

```
┌────────────────────────────────────────────────────────────────┐
│  使用者 Project                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ kanban.json  │  │   .env       │  │  memory.db   │          │
│  │ (任務狀態)    │  │ (API tokens) │  │  (RAG 知識庫) │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                 │                  │                   │
│         │          ┌──────┴──────┬───────────┘                   │
│         │          │             │                               │
│  ┌──────▼──────────▼─────────────▼──────┐   ┌─────────────┐    │
│  │        Claude Code + Plugins          │◄──┤    人類     │    │
│  │  (skills, commands, hooks, MCP)       │   │ (viewer /   │    │
│  └──────┬────────────┬─────────────┬─────┘   │  手機)      │    │
│         │            │             │         └──────▲──────┘    │
│         │            │    Pushover │                │            │
│         │            │   /ntfy.sh  │                │            │
│         │            └─────────────┼────────────────┘            │
│         │                          │  (推播通知)                  │
│         │                                                         │
│  ┌──────▼─────────────────────────────────┐                     │
│  │  External Runners (optional)            │                     │
│  │  cron / git hook / webhook server       │                     │
│  │  → `claude -p` headless mode            │                     │
│  └─────────────────────────────────────────┘                     │
└────────────────────────────────────────────────────────────────┘
```

### 2.2 Plugin 互相作用

| Pair | 整合效果 |
|---|---|
| kanban + notify | Task 需要使用者決策時自動推播;長任務完成時通知 |
| kanban + memory | Task 完成時自動提取重點存入 memory;新 task 開始時查詢歷史相關經驗 |
| notify + memory | 通知內容夾帶「上次類似情境你選了什麼」 |
| All three | Claude 選 task → 執行 → 需決策時推播 → 你回覆 → 結論存 memory → 下次自動 recall |

整合是**可選的,透過 capability detection 實現**:每個 plugin 開工前偵測 sibling 是否安裝,有就加碼,沒有就 graceful degrade。

### 2.3 Plugin 職責邊界

嚴格的邊界避免功能重疊:

| Plugin | 只做 | 絕不做 |
|---|---|---|
| kanban | 任務狀態管理、狀態機、依賴解析 | 通知、記憶累積 |
| notify | 訊息轉發到外部通道、provider 抽象 | 決定「什麼時候該通知」(由事件源決定) |
| memory | 知識存取、embedding、retrieval | 主動 push context (由 hook 或其他 plugin 呼叫) |

---

## 3. Plugin 1: `kanban`

### 3.1 角色

作為 Claude 跟使用者之間的**工作橋樑**。使用者在 `kanban.json` 新增 task,Claude 自主選取、執行、更新狀態。

### 3.2 Data Model

完整 `kanban.json` 結構:

```json
{
  "$schema": "./kanban.schema.json",
  "schema_version": 1,
  "meta": {
    "priorities": ["P0", "P1", "P2", "P3"],
    "categories": ["trading", "aiops", "youtube", "infra"],
    "columns": ["TODO", "DOING", "DONE", "BLOCKED"],
    "created_at": "2026-04-18T10:00:00+08:00",
    "updated_at": "2026-04-20T14:30:00+08:00"
  },
  "tasks": [
    {
      "id": "task-042",
      "title": "重寫 grid pricing dynamic classifier",
      "column": "TODO",
      "priority": "P1",
      "category": "trading",
      "tags": ["bitfinex", "refactor"],
      "depends": ["task-038", "task-040"],
      "created": "2026-04-18T10:00:00+08:00",
      "updated": "2026-04-19T14:30:00+08:00",
      "started": null,
      "completed": null,
      "assignee": "claude-code",
      "description": "參考 fin-exchange-manage repo 的 pricing.py",
      "comments": [
        {
          "author": "kirin",
          "ts": "2026-04-19T09:00:00+08:00",
          "text": "先用 rule-based,之後再換 ML"
        }
      ],
      "custom": {
        "estimated_hours": 4,
        "blocked_reason": null,
        "needs_user_input": false
      }
    }
  ]
}
```

### 3.3 狀態轉移規則

```
         (create)
            │
            ▼
        ┌───────┐
        │ TODO  │ ◄──────────────┐
        └───┬───┘                │
            │ /kanban:next       │ (unblock)
            ▼                    │
        ┌───────┐                │
        │ DOING │ ───────────────┼─► ┌─────────┐
        └───┬───┘                │   │ BLOCKED │
            │ /kanban:done       │   └─────────┘
            ▼                    │
        ┌───────┐                │
        │ DONE  │                │
        └───────┘                │
```

限制:

- **TODO → DOING**:`started` 設當下時間;所有 `depends` 必須已在 DONE
- **DOING → DONE**:`completed` 設當下時間
- **DOING → BLOCKED**:`custom.blocked_reason` 必須有值
- **BLOCKED → TODO**:清除 `custom.blocked_reason`
- **DONE → 任何狀態**:禁止(已完成不可回滾)

### 3.4 目錄結構

```
plugins/kanban/
├── .claude-plugin/plugin.json
├── skills/
│   └── kanban-workflow/
│       ├── SKILL.md
│       └── references/
│           ├── schema-spec.md
│           ├── priority-rules.md
│           └── dependency-rules.md
├── commands/
│   ├── init.md                       # /kanban:init
│   ├── next.md                       # /kanban:next
│   ├── done.md                       # /kanban:done
│   ├── block.md                      # /kanban:block
│   ├── status.md                     # /kanban:status
│   └── enable-automation.md          # /kanban:enable-automation
├── hooks/
│   └── hooks.json
├── scripts/
│   ├── kanban-guard.sh               # PreToolUse 守門員
│   ├── kanban-autocommit.sh          # PostToolUse 自動 commit
│   ├── kanban-session-check.sh       # SessionStart 檢查遠端變動
│   └── install-cron.sh               # 啟用 polling
└── templates/
    ├── kanban.schema.json
    ├── kanban.empty.json
    └── kanban.example.json
```

### 3.5 Slash Commands

| Command | 參數 | 用途 |
|---|---|---|
| `/kanban:init` | `[--with-examples]` | 初始化 kanban.json + schema |
| `/kanban:next` | `[--category=X] [--priority=Y]` | 選下一個 task 並開始 |
| `/kanban:done` | `[<task-id>] [--note=<text>]` | 標記完成 |
| `/kanban:block` | `<task-id> --reason=<text>` | 移到 BLOCKED |
| `/kanban:status` | | 列出當前狀態摘要 |
| `/kanban:enable-automation` | | 設定 cron / git hook / webhook |

### 3.6 Hooks

```json
{
  "SessionStart": [
    {
      "hooks": [{
        "type": "command",
        "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/kanban-session-check.sh"
      }]
    }
  ],
  "UserPromptSubmit": [
    {
      "hooks": [{
        "type": "command",
        "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/kanban-session-check.sh --lightweight"
      }]
    }
  ],
  "PreToolUse": [
    {
      "matcher": "Edit|Write",
      "hooks": [{
        "type": "command",
        "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/kanban-guard.sh"
      }]
    }
  ],
  "PostToolUse": [
    {
      "matcher": "Bash",
      "hooks": [{
        "type": "command",
        "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/kanban-autocommit.sh"
      }]
    }
  ]
}
```

### 3.7 Capability Detection(整合其他 plugin)

`kanban-session-check.sh` 與 `kanban-autocommit.sh` 開頭偵測:

```bash
has_plugin() { command -v "workbench-$1" &>/dev/null; }
HAS_NOTIFY=$(has_plugin notify && echo 1 || echo 0)
HAS_MEMORY=$(has_plugin memory && echo 1 || echo 0)
```

偵測到就啟用對應整合(詳見 §6)。沒偵測到則 graceful degrade。

---

## 4. Plugin 2: `notify`

### 4.1 角色

當 Claude Code 需要使用者注意力時,透過**外部通道**通知使用者,避免「AI 等在那邊、人不在電腦前」的盲點。

### 4.2 觸發時機

主要靠 Claude Code 內建的 `Notification` hook,支援四種 event type:

| event type | 說明 | 預設 priority |
|---|---|---|
| `permission_prompt` | Claude 需要許可執行 tool | high |
| `elicitation_dialog` | Claude 要問使用者問題 | high |
| `idle_prompt` | Claude idle 等待輸入 | normal |
| `auth_success` | 認證完成 | low |

### 4.3 Provider 抽象設計

**核心抽象**:notify 不綁死 Pushover,而是定義 provider interface,使用者選用。

```
┌─────────────────┐
│  Claude Code    │
│  hook event     │
└────────┬────────┘
         │
┌────────▼────────┐
│  notify-dispatch│  ← 讀 config,分派到 provider
│     (Python)    │
└────────┬────────┘
         │
    ┌────┴─────┬──────────┬──────────┐
    ▼          ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│Pushover│ │ntfy.sh │ │ Slack  │ │Telegram│
└────────┘ └────────┘ └────────┘ └────────┘
```

v0.1.0 只實作 Pushover;後續加其他 provider 不需要改 hook 邏輯。

### 4.4 Data Model(config)

**`~/.claude-workbench/notify-config.json`**:

```json
{
  "schema_version": 1,
  "default_provider": "pushover",
  "providers": {
    "pushover": {
      "enabled": true,
      "user_key": "${PUSHOVER_USER_KEY}",
      "app_token": "${PUSHOVER_APP_TOKEN}",
      "device": null,
      "sound_map": {
        "permission_prompt": "siren",
        "elicitation_dialog": "cosmic",
        "idle_prompt": "pushover",
        "auth_success": "none"
      }
    },
    "ntfy": {
      "enabled": false,
      "topic": "kirin-claude-code",
      "server": "https://ntfy.sh"
    }
  },
  "rules": [
    {
      "match": { "notification_type": "permission_prompt" },
      "providers": ["pushover"],
      "priority": 1
    },
    {
      "match": { "notification_type": "idle_prompt" },
      "providers": ["pushover"],
      "priority": -1,
      "throttle_seconds": 300
    }
  ]
}
```

- 環境變數展開(`${...}`)不在 config 直接存 secret
- `rules` 允許根據 event 不同選不同 provider、不同優先度
- `throttle_seconds` 避免 idle_prompt 連環轟炸

### 4.5 目錄結構

```
plugins/notify/
├── .claude-plugin/plugin.json
├── skills/
│   └── notify-usage/
│       └── SKILL.md                  # 教 Claude 何時主動呼叫 notify
├── commands/
│   ├── setup.md                      # /notify:setup 互動設定 provider
│   ├── test.md                       # /notify:test 發測試訊息
│   └── config.md                     # /notify:config 看/改設定
├── hooks/
│   └── hooks.json                    # Notification hook
├── scripts/
│   ├── notify-dispatch.py            # 主分派邏輯
│   ├── providers/
│   │   ├── pushover.py
│   │   ├── ntfy.py                   # (v0.2)
│   │   ├── slack.py                  # (v0.3)
│   │   └── telegram.py               # (v0.3)
│   └── workbench-notify              # CLI entry (供其他 plugin 呼叫)
└── templates/
    └── notify-config.example.json
```

### 4.6 Slash Commands

| Command | 用途 |
|---|---|
| `/notify:setup` | 互動式引導設定 provider(問 Pushover token 等) |
| `/notify:test` | 發測試訊息,確認設定正確 |
| `/notify:config` | 顯示或編輯目前設定 |

### 4.7 Hooks

```json
{
  "Notification": [
    {
      "matcher": "permission_prompt|elicitation_dialog",
      "hooks": [{
        "type": "command",
        "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/notify-dispatch.py"
      }]
    },
    {
      "matcher": "idle_prompt",
      "hooks": [{
        "type": "command",
        "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/notify-dispatch.py --throttle 300"
      }]
    }
  ]
}
```

### 4.8 Public CLI(給其他 plugin 呼叫)

**`workbench-notify`** 作為 notify plugin 對外的 API:

```bash
workbench-notify \
  --title "Kanban" \
  --message "Task task-042 needs your decision" \
  --priority high \
  --provider pushover \
  --url "claude://resume-session/<session-id>"
```

安裝 notify plugin 時在 `~/.claude-workbench/bin/` 建立此 symlink,加進 PATH。這是 kanban 跟 memory 偵測到 notify 存在時使用的入口。

### 4.9 Pushover 實作細節

- 使用 HTTPS POST 到 `https://api.pushover.net/1/messages.json`
- Timeout 5 秒(hook 不能卡太久)
- 失敗時寫入 `~/.claude-workbench/logs/notify-failures.log`,不阻擋 Claude 執行
- 敏感資訊過濾:message 中出現類似 `sk-...`、`ghp_...` 等 token pattern 時自動 mask

---

## 5. Plugin 3: `memory`

### 5.1 角色

跨 session 的長期知識庫。自動從對話中擷取重點、儲存到 SQLite,並在新 session 開始時根據當前 context 自動檢索相關記憶注入。

### 5.2 Data Model

**SQLite schema**(`memory.db`):

```sql
CREATE TABLE memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic       TEXT NOT NULL,
    content     TEXT NOT NULL,
    tags        TEXT,                    -- JSON array
    source      TEXT,                    -- session_id, task_id, or 'manual'
    project     TEXT,                    -- project path hash
    created_at  TEXT NOT NULL,           -- ISO 8601
    updated_at  TEXT NOT NULL,
    access_count INTEGER DEFAULT 0,
    last_access TEXT
);

CREATE INDEX idx_project ON memories(project);
CREATE INDEX idx_created ON memories(created_at);
CREATE INDEX idx_tags ON memories(tags);

-- Vector search via sqlite-vss
CREATE VIRTUAL TABLE memory_embeddings USING vss0(
    embedding(384)              -- sentence-transformers all-MiniLM-L6-v2
);
```

### 5.3 儲存策略

**三種寫入時機**:

1. **Explicit**:Claude 呼叫 MCP tool `memory.save(topic, content, tags)`
2. **Implicit via Stop hook**:Session 結束時,`Stop` hook 觸發 summarizer,自動提取本次 session 的 N 條重點
3. **Manual**:使用者在 CLI `workbench-memory save "..."`

**實作細節**:

- Embedding 用 `sentence-transformers/all-MiniLM-L6-v2`(CPU-friendly,384 dim,多語言)
- 本地 Python 推論,不送外部 API
- 每條 memory 生成 embedding 後存入 `memory_embeddings`
- Project 隔離:用 `hash(cwd)` 當 project ID,避免跨專案污染

### 5.4 檢索策略

**三種讀取時機**:

1. **SessionStart hook 自動注入**:session 開始時根據 cwd 查出 top-K relevant memories 作為 context
2. **Explicit query**:Claude 呼叫 MCP tool `memory.search(query, limit)`
3. **Manual**:使用者 `workbench-memory search "..."`

**注入 context 格式**:

```markdown
<!-- Injected by memory plugin -->
## Relevant memories from past sessions

### Bitfinex lending bot 的 rate limit 處理 (2026-04-10)
…

### Claude Code CLI 在 WSL2 的認證問題 (2026-04-15)
…
<!-- End memory injection -->
```

Claude 讀到這段會自動作為背景知識;不需要 skill 明確教。

### 5.5 目錄結構

```
plugins/memory/
├── .claude-plugin/plugin.json
├── skills/
│   └── memory-workflow/
│       ├── SKILL.md                  # 教 Claude 何時該 save / search
│       └── references/
│           └── tagging-guide.md      # 如何寫好 tags 的參考
├── commands/
│   ├── init.md                       # /memory:init 建 SQLite + 下載 embedding model
│   ├── save.md                       # /memory:save 手動存一條
│   ├── search.md                     # /memory:search 手動查
│   ├── list.md                       # /memory:list 最近 N 條
│   ├── forget.md                     # /memory:forget 刪除某條
│   └── export.md                     # /memory:export 匯出 markdown 備份
├── hooks/
│   └── hooks.json
├── .mcp.json                         # 註冊 memory MCP server
├── mcp-server/
│   ├── server.py                     # MCP server 實作
│   ├── embedder.py                   # embedding 邏輯
│   └── schema.sql
├── scripts/
│   ├── memory-inject.py              # SessionStart hook 用
│   ├── memory-summarize.py           # Stop hook 用 (呼叫 Claude summarize)
│   └── workbench-memory              # CLI entry
└── templates/
    └── memory-config.example.json
```

### 5.6 MCP Server Tools

| Tool | 參數 | 回傳 |
|---|---|---|
| `memory.save` | topic, content, tags[] | memory_id |
| `memory.search` | query, limit=5, min_similarity=0.5 | matches[] |
| `memory.list_recent` | days=7, project=current | matches[] |
| `memory.get` | id | memory |
| `memory.update` | id, content, tags | memory |
| `memory.forget` | id | success |

### 5.7 Slash Commands

| Command | 用途 |
|---|---|
| `/memory:init` | 建立 SQLite、下載 embedding model(首次安裝用) |
| `/memory:save` | 手動儲存一條 memory |
| `/memory:search <query>` | 手動檢索 |
| `/memory:list` | 列出最近 N 條 |
| `/memory:forget <id>` | 刪除 |
| `/memory:export` | 匯出 markdown 檔備份 |

### 5.8 Hooks

```json
{
  "SessionStart": [
    {
      "hooks": [{
        "type": "command",
        "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/memory-inject.py"
      }]
    }
  ],
  "Stop": [
    {
      "hooks": [{
        "type": "command",
        "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/memory-summarize.py"
      }]
    }
  ]
}
```

### 5.9 Retention Policy

- 預設**不自動刪除** — 使用者資料自主
- 提供 `/memory:forget` 手動刪除
- 提供 `workbench-memory prune --older-than 365d --min-access 0` CLI 工具(明確選擇才執行)
- 未來可加 "cold storage":超過 N 天未存取的 memory 移到 archive table,不進 embedding index 但仍可 query

### 5.10 Public CLI(給其他 plugin 呼叫)

```bash
workbench-memory save \
  --topic "Task task-042 outcome" \
  --content "..." \
  --tags "bitfinex,grid-pricing"

workbench-memory search \
  --query "grid pricing strategy" \
  --project current \
  --limit 3 \
  --format json
```

---

## 6. Cross-Plugin Integration

### 6.1 kanban + notify

**觸發點**:kanban 狀態轉移時

| 事件 | 通知內容 | Priority |
|---|---|---|
| Task 移到 DOING(長任務) | 「開始處理 task-042:...」 | low |
| Task 完成 | 「task-042 已完成」 | normal |
| Task 移到 BLOCKED | 「task-042 被 block,原因:...」 | high |
| 使用者需要決策(BLOCKED 帶 `needs_user_input: true`) | 「task-042 需要你決定」 | high |

**實作**:`kanban-autocommit.sh` 裡:

```bash
if [[ $HAS_NOTIFY -eq 1 ]]; then
    case "$STATE_TRANSITION" in
        "TODO->DOING")
            workbench-notify --priority low \
                --title "Kanban" --message "Started: $TASK_TITLE" ;;
        "DOING->BLOCKED")
            workbench-notify --priority high \
                --title "Kanban: action needed" \
                --message "$TASK_ID blocked: $REASON" ;;
        "DOING->DONE")
            workbench-notify --priority normal \
                --title "Kanban" --message "Completed: $TASK_TITLE" ;;
    esac
fi
```

### 6.2 kanban + memory

**場景 A:新 task 開始時查詢相關經驗**

`/kanban:next` command prompt 增加:

```markdown
Before executing the task, if `workbench-memory` is available:
1. Extract key terms from task title and tags
2. Run: `workbench-memory search --query "<terms>" --limit 3 --format json`
3. If relevant matches found, mention them before starting:
   "Found 3 related memories from past work: ..."
```

**場景 B:Task 完成時自動存重點**

`kanban-autocommit.sh` 在 `DOING->DONE` 時:

```bash
if [[ $HAS_MEMORY -eq 1 ]]; then
    workbench-memory save \
        --topic "Task $TASK_ID: $TASK_TITLE" \
        --content "$COMPLETION_NOTE" \
        --tags "$TASK_TAGS" \
        --source "kanban:$TASK_ID"
fi
```

### 6.3 notify + memory

**場景**:Claude 需要使用者決策時,通知內容夾帶「過去類似情境你怎麼選的」

`notify-dispatch.py` 處理 `elicitation_dialog` event 時:

```python
if has_memory_plugin():
    context = extract_context_from_message(message)
    past_decisions = subprocess.run(
        ["workbench-memory", "search",
         "--query", context, "--tags", "decision", "--limit", "1",
         "--format", "json"],
        capture_output=True, text=True, timeout=3
    )
    if past_decisions.stdout:
        decision = json.loads(past_decisions.stdout)
        message += f"\n\n💭 Past decision: {decision['content'][:200]}"
```

### 6.4 三者全部啟用時的使用者體驗

```
[09:00] 使用者出門前在 viewer 新增 task-050 "重構 lending bot pricing"

[09:15] Cron 觸發 → headless Claude 啟動
        [SessionStart hook]
        ├─ kanban 偵測到 task-050 in TODO → 自動 /kanban:next
        └─ memory 注入:"2024-03 處理過類似需求,當時用 EMA 平滑"

[09:20] Claude 進行 refactor,遇到 rate limit decision
        [elicitation_dialog event]
        ├─ notify 發 Pushover:
        │   "需要決定:要用 token bucket 還是 leaky bucket?
        │    💭 Past decision: 2025-12 你選了 token bucket"
        └─ Claude 等候

[09:22] 使用者通勤中在手機上看到推播,回覆「token bucket」
        (透過 Claude iOS app 或 web claude.ai resume session)

[09:30] Claude 完成 task
        ├─ kanban 移到 DONE
        ├─ notify 發 Pushover:"task-050 完成"
        └─ memory 自動存:"task-050: 改用 token bucket,原因..."

[19:00] 使用者回家看 viewer,看到 task-050 已完成,timeline 清楚
```

### 6.5 Capability Detection 標準

每個 plugin 的 script 開頭統一用這段:

```bash
has_plugin() { command -v "workbench-$1" &>/dev/null; }
HAS_NOTIFY=$(has_plugin notify && echo 1 || echo 0)
HAS_MEMORY=$(has_plugin memory && echo 1 || echo 0)
HAS_KANBAN=$(has_plugin kanban && echo 1 || echo 0)
```

整合功能在 `HAS_*` 為 1 時才啟用。沒裝 sibling plugin 時,功能 graceful degrade(例如 kanban 仍然能完成 task,只是沒通知)。

---

## 7. Meta-plugin: `workbench`

### 7.1 角色

Bundle 四者為一(或三)。使用者想一鍵安裝全套時使用。

### 7.2 plugin.json

```json
{
  "name": "workbench",
  "version": "0.1.0",
  "description": "Complete Claude Workbench — kanban + notify + memory",
  "author": { "name": "Kirin" },
  "dependencies": [
    { "name": "kanban", "version": "^0.1.0" },
    { "name": "notify", "version": "^0.1.0" },
    { "name": "memory", "version": "^0.1.0" }
  ]
}
```

**本體沒有 commands / skills / hooks**。只是 dependency 宣告。

### 7.3 安裝流程

```
/plugin install workbench@claude-workbench
→ Resolving dependencies...
  ✓ Installing kanban@0.1.0
  ✓ Installing notify@0.1.0
  ✓ Installing memory@0.1.0
  ✓ Installing workbench@0.1.0
```

---

## 8. Repository Structure

```
kirin/claude-workbench/
├── README.md                          # 家族入口
├── LICENSE                            # MIT
├── CHANGELOG.md
├── SPEC.md                            # 本文件
│
├── .claude-plugin/
│   └── marketplace.json
│
├── plugins/
│   ├── kanban/                        # §3
│   ├── notify/                        # §4
│   ├── memory/                        # §5
│   └── workbench/                     # §7 (meta)
│
├── viewer/                            # 選配,kanban 的 TUI
│   ├── pyproject.toml
│   └── src/kanban_tui/
│
├── automation/                        # kanban 的外部 runner
│   ├── cron-runner.sh
│   ├── git-hooks/post-merge
│   └── webhook-server.py
│
├── schema/                            # 共用 schema
│   └── kanban.schema.json
│
├── docs/
│   ├── quickstart.md
│   ├── composition.md                 # 三 plugin 怎麼互相加乘
│   ├── provider-setup/
│   │   ├── pushover.md
│   │   └── ntfy.md
│   └── troubleshooting.md
│
├── scripts/                           # CI 輔助
│   ├── sync-schema.sh
│   ├── sync-automation.sh
│   └── validate-plugins.sh
│
└── .github/
    └── workflows/
        ├── ci.yml
        ├── release-viewer.yml
        └── release.yml
```

### 8.1 `marketplace.json`

```json
{
  "name": "claude-workbench",
  "owner": {
    "name": "Kirin",
    "email": "kirin@example.com"
  },
  "plugins": [
    {
      "name": "kanban",
      "source": "./plugins/kanban",
      "description": "Kanban workflow for Claude Code",
      "category": "productivity",
      "keywords": ["kanban", "tasks", "workflow"]
    },
    {
      "name": "notify",
      "source": "./plugins/notify",
      "description": "Push notifications when Claude needs your attention",
      "category": "productivity",
      "keywords": ["notifications", "pushover", "alerts"]
    },
    {
      "name": "memory",
      "source": "./plugins/memory",
      "description": "Persistent RAG memory across sessions",
      "category": "productivity",
      "keywords": ["memory", "rag", "sqlite", "embeddings"]
    },
    {
      "name": "workbench",
      "source": "./plugins/workbench",
      "description": "★ Complete bundle — kanban + notify + memory",
      "category": "productivity",
      "keywords": ["bundle", "meta"]
    }
  ]
}
```

---

## 9. Versioning & Release

### 9.1 版本策略

**Monorepo 統一版號**,使用 Semantic Versioning:

- **MAJOR**:任何 plugin 有 breaking schema / API change
- **MINOR**:新功能、新 plugin
- **PATCH**:bug fix

Meta-plugin `workbench` 的 dependency 版本使用 caret range(`^0.1.0`),minor bump 會自動 match。

### 9.2 Release 流程

```bash
# 1. 更新 CHANGELOG.md
# 2. 更新四個 plugin.json 的 version(可用 script 批次改)
# 3. 更新 marketplace.json 裡各 plugin 的 version
# 4. git tag v0.2.0 && git push origin v0.2.0

# GitHub Actions 自動:
# - 驗證所有 plugin.json
# - 檢查 workbench 的 dependencies 版本對得上
# - 同步 schema/ → plugins/*/templates/
# - Build viewer binary 三平台
# - 發 GitHub Release 附 checksums
# - 發 PyPI (viewer)
```

### 9.3 使用者升級

```bash
/plugin update kanban@claude-workbench           # 單獨升級
/plugin update workbench@claude-workbench        # 升級 bundle(帶動三個)
```

---

## 10. Security Considerations

### 10.1 Secret 處理

- **從不**存 plain secret 在 config JSON
- 環境變數展開(`${PUSHOVER_APP_TOKEN}`)
- 建議使用者用 `direnv` 或 `.env` + gitignore
- notify plugin message 中有 token pattern 時自動 mask

### 10.2 Hook 安全

- 所有 hook script 用 `set -euo pipefail`
- `kanban-guard.sh` 拒絕繞過 schema 的 edit
- 不執行 kanban.json / memory.db 內容中的任意字串
- `--allowedTools` 不使用 wildcard,僅列必要

### 10.3 Memory plugin 隱私

- 資料**全本地**,不送第三方
- Embedding model 本地跑(`sentence-transformers`)
- Project isolation:`hash(cwd)` 避免跨專案污染
- `memory.db` 預設權限 `600`

### 10.4 Notify plugin 安全

- HTTPS-only(拒絕 HTTP provider endpoint)
- Webhook / Pushover response 不寫入 kanban.json 或 memory
- Failure log 不含 full message(避免 log 外流 secret)

### 10.5 供應鏈

- 所有 release binary 附 SHA256
- Signed git commits
- 未來考慮 Sigstore / cosign

---

## 11. MVP Roadmap

### 11.1 Phase 0:骨架(1 週)

- [ ] Monorepo 結構建立
- [ ] `marketplace.json`(四個 plugin entry)
- [ ] 四個 `plugin.json`(含 workbench meta)
- [ ] README + SPEC + LICENSE
- [ ] CI 基本驗證(lint, plugin schema check)

### 11.2 Phase 1:kanban v0.1.0(1-2 週)

- [ ] `kanban.schema.json` 完整版
- [ ] Skill + 5 個 commands
- [ ] PreToolUse / PostToolUse / SessionStart hooks
- [ ] Templates(empty + example)
- [ ] docs/quickstart.md 中涵蓋 kanban 使用方式

**驗收**:在一個真實 project 上跑一週,記錄 pain points。

### 11.3 Phase 2:notify v0.1.0(1 週)

- [ ] Pushover provider
- [ ] `notify-dispatch.py` 分派邏輯
- [ ] `/notify:setup` 互動式設定
- [ ] Notification hook 綁定
- [ ] `workbench-notify` CLI 發布

**驗收**:idle + permission prompt 時手機能收到推播。

### 11.4 Phase 3:kanban × notify 整合(2-3 天)

- [ ] kanban hooks 加上 `has_plugin notify` 偵測
- [ ] Task 狀態轉移時發通知
- [ ] 文件化 integration(docs/composition.md)

### 11.5 Phase 4:memory v0.1.0(2 週)

- [ ] SQLite + sqlite-vss 環境
- [ ] MCP server 實作(save / search / list)
- [ ] `memory-inject.py` SessionStart hook
- [ ] `memory-summarize.py` Stop hook
- [ ] `workbench-memory` CLI

**驗收**:連續用兩週後,新 session 能 recall 兩週前討論的細節。

### 11.6 Phase 5:三者整合(1 週)

- [ ] kanban × memory:task done 自動存、next 自動查
- [ ] notify × memory:通知夾帶 past decision
- [ ] E2E 測試場景:§6.4 的使用者體驗流程

### 11.7 Phase 6:Workbench v0.1.0 bundle release

- [ ] Meta-plugin 正式發佈
- [ ] README 宣傳「一鍵安裝全套」
- [ ] Blog post 宣傳(台灣 AI engineering 圈)

### 11.8 Future(v0.2+)

- [ ] notify:ntfy / Slack / Telegram provider
- [ ] memory:cold storage、cross-project search
- [ ] viewer:依賴關係 DAG、web 版
- [ ] kanban:`/kanban:enable-automation` + webhook server
- [ ] New plugin ideas:`schedule`(時間觸發)、`review`(AI code review)

---

## 12. Open Questions

1. **Task ID 生成**:連續遞增 vs hash-based?
2. **DONE 歸檔**:kanban.json 長期膨脹,何時搬 archive?
3. **Concurrent headless Claude**:多台機器同時 cron 觸發怎麼 lock?
4. **Memory scope**:是否要支援使用者跨 project 檢索?privacy 怎麼處理?
5. **Notify rate limit**:使用者被通知炸的 UX 怎麼避免?
6. **Plugin version compatibility**:當 kanban v0.2 改 schema、notify 還是 v0.1 時怎麼處理?
7. **Viewer 是否進 marketplace**:viewer 獨立或做成 plugin 的一部分?
8. **Memory embedding model 的安裝體驗**:首次下載 ~80MB model 的 UX?

---

## 13. References

- [Claude Code Plugins documentation](https://code.claude.com/docs/en/plugins)
- [Claude Code Plugins reference](https://code.claude.com/docs/en/plugins-reference)
- [Claude Code Hooks reference](https://code.claude.com/docs/en/hooks)
- [Claude Code Headless mode](https://code.claude.com/docs/en/headless)
- [Model Context Protocol](https://modelcontextprotocol.io)
- [sqlite-vss](https://github.com/asg017/sqlite-vss)
- [sentence-transformers](https://www.sbert.net/)
- [Pushover API](https://pushover.net/api)

---

## Appendix A — 安裝體驗腳本

### A.1 漸進式安裝

```bash
# Day 1: 先試 kanban
$ claude
> /plugin marketplace add kirin/claude-workbench
> /plugin install kanban@claude-workbench
> /kanban:init --with-examples
> /kanban:next

# Day 7: 加通知
> /plugin install notify@claude-workbench
> /notify:setup
# [引導輸入 Pushover token]
> /notify:test

# Day 14: 加記憶
> /plugin install memory@claude-workbench
> /memory:init
# [下載 embedding model, 建 SQLite]
```

### A.2 一鍵全套

```bash
$ claude
> /plugin marketplace add kirin/claude-workbench
> /plugin install workbench@claude-workbench
→ Installing kanban + notify + memory + workbench...

> /kanban:init
> /notify:setup
> /memory:init
```

---

## Appendix B — Plugin 互動矩陣

| | kanban 提供 | notify 提供 | memory 提供 |
|---|---|---|---|
| **kanban 消費** | — | Task 狀態變動通知 | Task 歷史查詢 |
| **notify 消費** | 通知內容來源 | — | 通知內容加碼 |
| **memory 消費** | Task 事件 → 存 memory | — | — |

---

*End of SPEC.md*
