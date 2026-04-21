# Claude Workbench — SPEC

*[English](./SPEC.md)*

**Project**: `kirin/claude-workbench`
**Version**: 0.1.0（草稿）
**Last Updated**: 2026-04-20
**Author**: Kirin

> **文件源流**：本檔是三份早期草稿的合併——原本只談 kanban 的 SPEC、擴充成 workbench 全家族的版本（SPEC_InClude3），以及 docsync dev-profile plugin 的 SPEC。凡三者有衝突：結構以 workbench family SPEC 為準；§6 以 docsync SPEC 為準；老 SPEC 才有的內容（viewer、automation runners）保留為 §7。

---

## 1. 家族概觀

### 1.1 What

`claude-workbench` 是一組 Claude Code plugin，把 CLI 變成一個**持久化、事件驅動**的 AI 工作空間。四個原子 plugin、兩個 meta-bundle，都從單一個 marketplace 發佈：

```
┌──────────────────────────────────────────────────────────────────────┐
│  claude-workbench (marketplace)                                       │
│                                                                        │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐        ┌──────────┐            │
│  │ kanban  │  │ notify  │  │ memory  │        │ docsync  │            │
│  │ tasks   │  │ push    │  │ RAG     │        │ code ↔   │            │
│  │         │  │ notif.  │  │ store   │        │  docs    │            │
│  └────┬────┘  └────┬────┘  └────┬────┘        └────┬─────┘            │
│       │            │            │                   │                  │
│       └─────┬──────┴────────────┘                   │                  │
│             ▼                                       ▼                  │
│      ┌─────────────┐                         ┌──────────────┐         │
│      │  workbench  │                         │ workbench-dev│         │
│      │ (core meta) │  ◄────── depends ──┐    │ (dev meta)   │         │
│      └─────────────┘                    └────┤               │         │
│                                              └──────────────┘         │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.2 Why

Claude Code 預設以 session 為範圍：開 session → 下指令 → 等 → 關掉。這留下四個落差：

1. **任務狀態不持續**。Session 關掉、context 消散。
2. **沒有事件觸發**。使用者必須在場才能推進互動。
3. **決策沒人看見**。離開桌前，Claude 獨自卡住。
4. **知識不累積**。每個 session 都從零開始。

四個 plugin 各自對應一個落差：

| Plugin | 分類 | 解決什麼 |
|---|---|---|
| **kanban** | core | 任務狀態持久化 + 人 / AI 共用的工作佇列 |
| **notify** | core | Claude 需要注意時的外部通知 |
| **memory** | core | 跨 session 的 RAG 知識庫 |
| **docsync** | dev | code ↔ 文件漂移防治 |

四個都獨立可用。組合透過 capability detection（§8.7）opt-in。

### 1.3 設計原則

1. **Has-a, not is-a** — 把能力當 plugin 注入；絕不 fork template。
2. **模組化 + 可組合** — 每個 plugin 自成完整；相鄰者同在則相乘。
3. **漸進採用** — 先裝一個、用一陣、再加其他。
4. **決定性 engine + AI 判斷力** — script 執行硬規則；Claude 處理曖昧。
5. **成本敏感** — 預設路徑用 Claude Pro/Max 訂閱（headless），不是 API credit。
6. **本機優先** — 資料留在使用者機器上；除 AI provider 外無第三方服務。
7. **Config-driven, not prompt-driven**（docsync 風味） — 規則專案各異時，寫進版本控的本機 config，由互動式產生而非手寫。

### 1.4 目標使用者

- 重度個人 Claude Code 使用者
- 同時經營多個專案
- 熟悉 git、CLI、基本 shell script
- 偏好訂閱 + 自架，而非完全託管 SaaS

### 1.5 Plugin 分類

- **Core**（`kanban`、`notify`、`memory`）— 打包進預設 `workbench` meta。每個 workbench 使用者都會拿到。
- **Dev**（`docsync` 以及未來的 `review`、`lint` 等）— 打包進 `workbench-dev`。主要把 Claude Code 用在軟體工程的人專用。

分類只是組織性的裝飾，不是架構邊界——任一 plugin 都可以透過 capability detection 依賴任一 plugin，跟分類無關。

---

## 2. 系統架構

### 2.1 資料流

```
┌─────────────────────────────────────────────────────────────────────┐
│ User Project                                                         │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │
│ │ kanban.json  │ │    .env      │ │  memory.db   │ │.claude/      │ │
│ │ (task state) │ │ (API tokens) │ │ (RAG store)  │ │  docsync.yaml│ │
│ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ │
│        │                │                │                │          │
│        └──────┬─────────┴──────┬─────────┴────────────────┘          │
│               ▼                ▼                                      │
│ ┌────────────────────────────────────────┐   ┌──────────────┐       │
│ │   Claude Code + Plugins                │◄──┤  Human       │       │
│ │   (skills · commands · hooks · MCP)    │   │  (viewer /   │       │
│ └──────┬─────────┬───────────┬───────────┘   │   phone)     │       │
│        │         │           │               └──────▲───────┘       │
│        │         │  Pushover │                      │                │
│        │         │   /ntfy   │                      │                │
│        │         └───────────┼──────────────────────┘                │
│        │                     │  (push)                               │
│ ┌──────▼────────────────────────────────┐                           │
│ │  External Runners (optional)           │                           │
│ │  cron · git hook · webhook             │                           │
│ │  → `claude -p` headless                │                           │
│ └────────────────────────────────────────┘                           │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Plugin 互動矩陣

| Pair | 效果 |
|---|---|
| kanban × notify | 任務狀態轉換觸發推播；要決策時以高優先度推 |
| kanban × memory | `next` 查詢過去工作；`done` 存完工筆記 |
| kanban × docsync | DONE gate：enforcement=block 時，文件沒更新就擋 |
| notify × memory | 決策提示附帶「上次你選 X」 |
| docsync × memory | 文件變更摘要持久化，支援跨 session 一致性 |
| docsync × notify | 被動——docsync 從不直接推播（見 §8.6） |
| 四個都有 | `cron → kanban:next → memory recall → work → docsync gate → notify push → user decides → memory save → kanban:done` |

整合永遠透過 **capability detection**（§8.7）opt-in。相鄰者缺席絕不破壞任何 plugin——只會退化為單 plugin 行為。

### 2.3 Plugin 職責邊界

嚴格的邊界防止 scope creep 和重疊：

| Plugin | 做什麼 | 不做什麼 |
|---|---|---|
| kanban | 任務狀態、state machine、依賴解析 | 推播、累積記憶、改文件 |
| notify | 派送到外部通道、provider 抽象層 | 決定*何時*推播（事件源頭決定） |
| memory | 存取知識、embedding、retrieval | 主動 push context（hook 或相鄰 plugin 做） |
| docsync | code ↔ 文件 對應追蹤、規則 engine、互動式 config | 修改文件內容本身、擋住非 DONE 的 code 變更 |

---

## 3. Plugin 1：`kanban`

### 3.1 角色

Claude 與 user 之間的工作橋樑。User 在 `kanban.json` 加任務；Claude 挑、執行、更新狀態。兩邊讀寫同一份檔案。

### 3.2 Data Model

```jsonc
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
      "title": "Rewrite grid pricing dynamic classifier",
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
      "description": "See fin-exchange-manage repo's pricing.py.",
      "comments": [
        { "author": "kirin", "ts": "2026-04-19T09:00:00+08:00", "text": "Rule-based first; ML later." }
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

**欄位規則**：

| 欄位 | 型別 | 必填 | 備註 |
|---|---|---|---|
| `schema_version` | int | ✓ | 目前 `1`。不可遞減。 |
| `meta.priorities` | string[] | ✓ | 由高到低排序。 |
| `meta.categories` | string[] | | User 自定。 |
| `meta.columns` | string[] | ✓ | 必須恰好是 `["TODO","DOING","DONE","BLOCKED"]`。 |
| `meta.{created,updated}_at` | ISO 8601 | ✓ | 含時區。 |
| `tasks[].id` | string | ✓ | `^task-[0-9]{3,}$`。 |
| `tasks[].title` | string | ✓ | 單行。 |
| `tasks[].column` | enum | ✓ | `meta.columns` 之一。 |
| `tasks[].priority` | enum | ✓ | `meta.priorities` 之一。 |
| `tasks[].category` | string | | 若有值，必須在 `meta.categories` 內。 |
| `tasks[].tags` | string[] | | 自由格式。 |
| `tasks[].depends` | string[] | | 其他 task id。強制 DAG。 |
| `tasks[].{created,updated}` | ISO 8601 | ✓ | 含時區。 |
| `tasks[].started` | ISO 8601 | 條件性 | column ∈ {DOING, DONE} 時必填。 |
| `tasks[].completed` | ISO 8601 | 條件性 | column == DONE 時必填。 |
| `tasks[].assignee` | string | | `claude-code`、人、或 null。 |
| `tasks[].description` | string | | 多行 markdown。不可放 secret。 |
| `tasks[].comments` | `{author, ts, text}[]` | | 實務上 append-only。 |
| `tasks[].custom` | object | | 無 schema；`blocked_reason`、`needs_user_input`、`estimated_hours` 已識別。 |

### 3.3 狀態轉換

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
            │ DONE  │────────────────┘   (DONE is terminal)
            └───────┘
```

不變式：

- **TODO → DOING**：設 `started = now`；每個 `depends` id 必須都在 `DONE`。
- **DOING → DONE**：設 `completed = now`。
- **DOING → BLOCKED**（或 TODO → BLOCKED）：`custom.blocked_reason` 必須非空；`started` 若已設則保留。
- **BLOCKED → TODO**：清 `custom.blocked_reason`。
- **DONE → 任何**：禁止。要恢復工作就建新任務。

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
│   ├── init.md               # /kanban:init
│   ├── next.md               # /kanban:next
│   ├── done.md               # /kanban:done
│   ├── block.md              # /kanban:block
│   ├── status.md             # /kanban:status
│   └── enable-automation.md  # /kanban:enable-automation
├── hooks/hooks.json
├── scripts/
│   ├── kanban-guard.sh           # PreToolUse：擋直接編輯
│   ├── kanban-autocommit.sh      # PostToolUse：獨立 commit + sibling fan-out
│   ├── kanban-session-check.sh   # SessionStart + UserPromptSubmit：顯示 DOING/BLOCKED
│   ├── cron-runner.sh            # headless runner（由 install-cron.sh 安裝）
│   └── install-cron.sh           # crontab installer
└── templates/
    ├── kanban.schema.json
    ├── kanban.empty.json
    └── kanban.example.json
```

### 3.5 Slash 指令

| 指令 | 參數 | 目的 |
|---|---|---|
| `/kanban:init` | `[--with-examples]` | 建立 `kanban.json` + `kanban.schema.json` |
| `/kanban:next` | `[--category=X] [--priority=Y]` | 挑下一個可執行 TODO，移到 DOING，開始 |
| `/kanban:done` | `[<task-id>] [--note=<text>]` | 關任務（預設：當前 DOING） |
| `/kanban:block` | `<task-id> --reason=<text>` | 移到 BLOCKED 並要 reason |
| `/kanban:status` | | 唯讀總覽 |
| `/kanban:enable-automation` | | 互動式：安裝 cron 或 git hook |

每個指令檔有 `argument-hint` frontmatter、明確的 step list、絕對規則（不容 AI 自由詮釋狀態轉換）。

### 3.6 Hooks

```json
{
  "SessionStart": [{ "hooks": [{ "type": "command",
    "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/kanban-session-check.sh" }] }],
  "UserPromptSubmit": [{ "hooks": [{ "type": "command",
    "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/kanban-session-check.sh --lightweight" }] }],
  "PreToolUse": [{ "matcher": "Edit|Write|MultiEdit",
    "hooks": [{ "type": "command",
      "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/kanban-guard.sh" }] }],
  "PostToolUse": [{ "matcher": "Bash|Write|Edit|MultiEdit",
    "hooks": [{ "type": "command",
      "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/kanban-autocommit.sh" }] }]
}
```

Hook 行為：

- `kanban-session-check.sh`（SessionStart）— 把 DOING 和 BLOCKED 當 `additionalContext` 注入。未來：`git fetch` + 遠端漂移偵測。
- `--lightweight`（UserPromptSubmit）— 只 DOING；降低雜訊。
- `kanban-guard.sh` — 若 Edit/Write/MultiEdit 目標為 `kanban.json`，exit 2；指向 `/kanban:*` 指令。
- `kanban-autocommit.sh` — 若 `kanban.json` 是唯一 dirty file，獨立 commit 並附帶 transition-aware message（`kanban: task-042 TODO→DOING`）。然後在 sibling 有裝時 fan-out 到 notify/memory。

### 3.7 Capability Detection

`kanban-session-check.sh` 和 `kanban-autocommit.sh` 都以此開頭：

```bash
has_plugin() { command -v "workbench-$1" >/dev/null 2>&1; }
HAS_NOTIFY=0; has_plugin notify && HAS_NOTIFY=1
HAS_MEMORY=0; has_plugin memory && HAS_MEMORY=1
HAS_DOCSYNC=0; has_plugin docsync && HAS_DOCSYNC=1
```

整合 block 只在對應 flag 為 `1` 時執行。相鄰者缺席 → 靜默 no-op。

---

## 4. Plugin 2：`notify`

### 4.1 角色

Claude Code 需要注意時透過外部通道找到 user——避免「AI 卡住、user 不在」的死結。

### 4.2 觸發事件

用 Claude Code 內建的 `Notification` hook。四種事件型態：

| 事件 | 意思 | 預設優先度 |
|---|---|---|
| `permission_prompt` | Claude 要工具權限 | high |
| `elicitation_dialog` | Claude 要問 user | high |
| `idle_prompt` | Claude 閒置等輸入 | normal |
| `auth_success` | 認證流程完成 | low |

### 4.3 Provider 抽象層

```
┌────────────┐    ┌──────────────────┐    ┌────────────────────┐
│ Claude     │───►│ notify-dispatch  │───►│ Pushover / ntfy /  │
│ hook event │    │ (Python)         │    │ Slack / Telegram   │
└────────────┘    └──────────────────┘    └────────────────────┘
```

v0.1.0 只出 Pushover。其他 provider 不動 hook 就能掛上。

### 4.4 Config — `~/.claude-workbench/notify-config.json`

```jsonc
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
    "ntfy": { "enabled": false, "topic": "kirin-claude-code", "server": "https://ntfy.sh" }
  },
  "rules": [
    { "match": { "notification_type": "permission_prompt" }, "providers": ["pushover"], "priority": 1 },
    { "match": { "notification_type": "idle_prompt" },       "providers": ["pushover"], "priority": -1, "throttle_seconds": 300 }
  ]
}
```

- `${…}` env-var 展開。不要直接寫 secret 進 config。
- `rules` 是每事件路由 + 優先度 + throttle。
- `throttle_seconds` 擋住 idle-prompt 灌爆。

### 4.5 目錄結構

```
plugins/notify/
├── .claude-plugin/plugin.json
├── skills/notify-usage/SKILL.md
├── commands/{setup,test,config}.md
├── hooks/hooks.json
├── scripts/
│   ├── notify-dispatch.py
│   ├── providers/{pushover,ntfy,slack,telegram}.py
│   └── workbench-notify          # 公開 CLI entry
└── templates/notify-config.example.json
```

### 4.6 Slash 指令

| 指令 | 目的 |
|---|---|
| `/notify:setup` | 互動式 provider config（問 token） |
| `/notify:test` | 送測試訊息 |
| `/notify:config` | 顯示或編輯 config |

### 4.7 Hooks

```json
{
  "Notification": [
    { "matcher": "permission_prompt|elicitation_dialog",
      "hooks": [{ "type": "command",
        "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/notify-dispatch.py" }] },
    { "matcher": "idle_prompt",
      "hooks": [{ "type": "command",
        "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/notify-dispatch.py --throttle 300" }] }
  ]
}
```

### 4.8 公開 CLI

`workbench-notify` 是給相鄰 plugin 的整合 entry：

```bash
workbench-notify \
  --title "Kanban" \
  --message "Task task-042 needs your decision" \
  --priority high \
  --provider pushover \
  --url "claude://resume-session/<session-id>"
```

安裝到 `~/.claude-workbench/bin/`（必須在 PATH 上）。

### 4.9 Pushover 實作注意事項

- HTTPS POST 到 `https://api.pushover.net/1/messages.json`。
- 5 秒 timeout（hook 不能拖死 Claude）。
- 失敗 append 到 `~/.claude-workbench/logs/notify-failures.log`；絕不擋。
- 訊息送前 scrub token 形態子字串（`sk-…`、`ghp_…` 等）。

---

## 5. Plugin 3：`memory`

### 5.1 角色

跨 Claude Code session 的持續知識庫。自動擷取 session 摘要、存 SQLite 含 embedding、SessionStart 時注入相關舊記憶。

### 5.2 Data Model — `memory.db`

```sql
CREATE TABLE memories (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    topic        TEXT NOT NULL,
    content      TEXT NOT NULL,
    tags         TEXT,                    -- JSON array
    source       TEXT,                    -- session_id, task_id, or 'manual'
    project      TEXT,                    -- hash(cwd)
    created_at   TEXT NOT NULL,           -- ISO 8601
    updated_at   TEXT NOT NULL,
    access_count INTEGER DEFAULT 0,
    last_access  TEXT
);
CREATE INDEX idx_project ON memories(project);
CREATE INDEX idx_created ON memories(created_at);
CREATE INDEX idx_tags    ON memories(tags);

-- Vector search via sqlite-vss
CREATE VIRTUAL TABLE memory_embeddings USING vss0(
    embedding(384)   -- sentence-transformers/all-MiniLM-L6-v2
);
```

檔案權限：`600`。透過 `hash(cwd)` 做專案隔離。

### 5.3 Save 策略

三條寫入路徑：

1. **顯式** — Claude 呼叫 MCP tool `memory.save(topic, content, tags)`。
2. **隱式** — `Stop` hook 跑 summariser，session 結束擷取 N 個重點。
3. **手動** — user 跑 `workbench-memory save "…"`。

Embedding 本機透過 `sentence-transformers/all-MiniLM-L6-v2` 產生（CPU、384 維、多語言）。無外部 API。

### 5.4 Retrieval 策略

三條讀取路徑：

1. **SessionStart 注入** — 對當前 `cwd` 查 top-K 相關記憶，當 `additionalContext` 注入。
2. **顯式** — Claude 呼叫 `memory.search(query, limit)`。
3. **手動** — `workbench-memory search "…"`。

注入格式：

```markdown
<!-- Injected by memory plugin -->
## Relevant memories from past sessions

### Bitfinex lending bot rate limit handling (2026-04-10)
…

### Claude Code auth on WSL2 (2026-04-15)
…
<!-- End memory injection -->
```

### 5.5 目錄結構

```
plugins/memory/
├── .claude-plugin/plugin.json
├── skills/memory-workflow/
│   ├── SKILL.md
│   └── references/tagging-guide.md
├── commands/{init,save,search,list,forget,export}.md
├── hooks/hooks.json
├── .mcp.json                      # 註冊 memory MCP server
├── mcp-server/
│   ├── server.py
│   ├── embedder.py
│   └── schema.sql
├── scripts/
│   ├── memory-inject.py          # SessionStart
│   ├── memory-summarize.py       # Stop
│   └── workbench-memory          # 公開 CLI entry
└── templates/memory-config.example.json
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

### 5.7 Slash 指令

| 指令 | 目的 |
|---|---|
| `/memory:init` | 建立 SQLite + 下載 embedding model |
| `/memory:save` | 手動存 |
| `/memory:search <query>` | 手動查 |
| `/memory:list` | 最近 N 筆 |
| `/memory:forget <id>` | 刪除 |
| `/memory:export` | Markdown 備份 |

### 5.8 Hooks

```json
{
  "SessionStart": [{ "hooks": [{ "type": "command",
    "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/memory-inject.py" }] }],
  "Stop": [{ "hooks": [{ "type": "command",
    "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/memory-summarize.py" }] }]
}
```

### 5.9 保留策略

- 預設：絕不自動刪。User 擁有保留權。
- `/memory:forget <id>` 手動刪。
- `workbench-memory prune --older-than 365d --min-access 0` opt-in CLI。
- 未來：冷儲存（出 embedding index，仍可查）。

### 5.10 公開 CLI

```bash
workbench-memory save --topic "…" --content "…" --tags "a,b"
workbench-memory search --query "…" --project current --limit 3 --format json
```

安裝到 `~/.claude-workbench/bin/`。

---

## 6. Plugin 4：`docsync`（dev 分類）

### 6.1 角色

讓 **code 變更** 和 **文件** 保持同步。針對維護活文件（ARCHITECTURE.md、CODE_MAP.md、每 module README、…）的專案，它們會在 Claude 改 code 卻沒動對應文件時逐漸失去真實性。

### 6.2 設計哲學

**Config-driven, not prompt-driven**：

- Plugin 只出 *engine*（規則 + hook + 指令）。
- 每專案的映射住在 `.claude/docsync.yaml`，跟 repo 一起版控。
- User 永遠不自己手寫 YAML——`/docsync:init` 互動式產生。

這把常見的「把映射規則硬塞進 CLAUDE.md」模式，轉成結構化、可攜、可驗證的東西。

### 6.3 互動式 Onboarding 哲學

`/docsync:init` 展示 Workbench 全家族推薦的 `init` UX：
**scan → infer → interview → validate**。好的 AI onboarding 要像有經驗的顧問走進辦公室——先環顧四周，只問真的非人類不可的事。完整流程見 §6.7。

### 6.4 Data Model — `.claude/docsync.yaml`

```yaml
schema_version: 1

# Plugin 要求 Claude 在 SessionStart 閱讀的文件。
bootstrap_docs:
  - doc/ARCHITECTURE.md
  - doc/CODE_MAP.md
  - doc/DIRECTORY_TREE.md
  - doc/SPEC.md

# Code → doc 更新規則。
rules:
  - id: common-code-map
    pattern: "common/**"
    docs:
      - path: doc/CODE_MAP.md
        section: common
        required: true
      - path: doc/ARCHITECTURE.md
        required_if: architecture_changed

  - id: position-manager
    pattern: "position-manager/**"
    docs:
      - path: doc/CODE_MAP.md
        section: position-manager
      - path: position-manager/dynamic_param.md
        required_if: params_changed

# 允許 Claude 在這些情境跳過 doc 更新（語意判斷，由 skill 指引）。
skip_conditions:
  - bug_fix_only
  - internal_refactor
  - test_only
  - comment_formatting_only

# 嚴格度。
enforcement: warn       # warn | block | silent

# 相鄰 plugin 整合（選用）。
integration:
  kanban:
    block_done_if_pending: false
  memory:
    summarize_doc_changes: true
```

關鍵欄位：

| 欄位 | 型別 | 備註 |
|---|---|---|
| `rules[].id` | string | log / error 用的識別字。 |
| `rules[].pattern` | glob | `common/**`、`src/api/*.rs`、… |
| `rules[].docs[].path` | string | 要更新的檔案。 |
| `rules[].docs[].section` | string | 選用——大文件內的命名 section。 |
| `rules[].docs[].required` | bool | 預設 `true`。 |
| `rules[].docs[].required_if` | enum | `architecture_changed` \| `api_changed` \| `params_changed` \| `schema_changed` |
| `skip_conditions` | enum[] | 見上清單。語意性——由 Claude 判斷。 |
| `enforcement` | enum | `silent` / `warn` / `block`。 |

`required_if` 的值是 **語意性**，不是程式性的。Skill 教 Claude 何時套用；規則 engine 只列出候選。

`enforcement` 語意：

| 值 | 效果 |
|---|---|
| `silent` | 只有 `/docsync:check` 會顯示 pending。 |
| `warn`（預設） | PostToolUse hook 在 context 裡提醒 Claude。 |
| `block` | 啟用 kanban 整合時，DONE 會被卡住直到同步完成。 |

### 6.5 目錄結構

```
plugins/docsync/
├── .claude-plugin/plugin.json
├── skills/docsync-workflow/
│   ├── SKILL.md
│   └── references/
│       ├── update-patterns.md       # 如何寫 CODE_MAP / ARCHITECTURE / README section
│       └── skip-decision-tree.md    # 每個 skip_condition 何時套用
├── commands/
│   ├── init.md                      # /docsync:init
│   ├── check.md                     # /docsync:check
│   ├── rules.md                     # /docsync:rules
│   ├── bootstrap.md                 # /docsync:bootstrap
│   └── validate.md                  # /docsync:validate
├── hooks/hooks.json
├── scripts/
│   ├── docsync-bootstrap.py         # SessionStart：注入 bootstrap_docs 提醒
│   ├── docsync-guard.py             # PostToolUse：偵測 pending 同步
│   ├── docsync-finalcheck.py        # Stop：session 結束摘要
│   ├── rule-engine.py
│   └── workbench-docsync            # 公開 CLI
└── templates/
    ├── docsync.example.yaml         # Rust 單一倉庫
    ├── docsync.python.yaml
    └── docsync.js.yaml
```

### 6.6 Slash 指令

| 指令 | 參數 | 目的 |
|---|---|---|
| `/docsync:init` | `[--from-existing-claude-md]` | 互動式產生 `.claude/docsync.yaml` |
| `/docsync:check` | `[<path>]` | 手動掃描 pending 同步 |
| `/docsync:rules` | `[<path>]` | 顯示規則；測試哪條 match 特定路徑 |
| `/docsync:bootstrap` | | 列出此 session 讀過的 bootstrap_docs |
| `/docsync:validate` | | 驗證 YAML schema |

### 6.7 互動式 Init Flow

核心 UX pattern。五階段。

**Phase 1 — Scan**（靜默）：

1. 透過以下偵測專案類型：`Cargo.toml` + `[workspace]`（Rust 單一倉庫）、`pnpm-workspace.yaml`/`lerna.json`（JS 單一倉庫）、`pyproject.toml`/`setup.py`（Python）、`go.mod`（Go）、或多種 → 混合。
2. 列出 code modules：頂層目錄扣掉 `.git`、`node_modules`、`target`、`dist`、`.venv`、`doc*`、`.cache`。
3. 列出 docs：`doc/`、`docs/`、`documentation/`，加上 root 的 `README`、`ARCHITECTURE`、`CODE_MAP`、`SPEC`、`DIRECTORY_TREE`、`CONTRIBUTING`；以及每個 module 自己的 `README.md`。
4. 若 `--from-existing-claude-md`：解析 `CLAUDE.md` 裡現有的映射表格，預填推論。

**Phase 2 — Inquiry**（互動式，用 `AskUserQuestion`）：

先摘要 scan：「找到 N modules、M docs。」接著一批最多 3 題：

- **批次 1 — Bootstrap docs**：多選 SessionStart 時要載入哪些 docs。
- **批次 2 — Module → doc 映射**：每 module 單選（global CODE_MAP / module README / 兩者 / 都不要 / 自訂）。
- **批次 3 — Enforcement**：`warn`（推薦）/ `block` / `silent`。
- **批次 4 — Skip conditions**：多選。
- **批次 5 — 整合**（僅當相鄰者已裝）：kanban DONE gate？memory summary？

**Phase 3 — Propose**：

把 draft YAML 當單個 code block 呈現。問：「這樣對嗎？」接受 `yes` / `edit <section>` / `cancel`。

**Phase 4 — Dry-run validate**（殺手級功能）：

寫檔前先對真實歷史證明規則合理：

1. `git log --oneline -n 20`。
2. 挑 3 個代表性 commit（跨 module、文件多的、純 code）。
3. 對每個列變更檔、跑規則、回報會 flag 什麼。

範例：

```
If docsync v1 had been active:

commit abc123 "refactor grid pricing"
├ changed: position-manager/src/grid.rs
└ would prompt: doc/CODE_MAP.md (position-manager section)
                position-manager/dynamic_param.md (grid params changed)

commit def456 "fix typo in comment"
├ changed: common/src/types.rs
└ would skip (matches skip_condition: comment_formatting_only)
```

User 透過預覽理解規則的速度遠快於看 YAML。

**Phase 5 — Write & 後續**：

1. 寫 `.claude/docsync.yaml`。
2. 問要不要 commit（預設 yes——團隊共享）。
3. 確認 `.claude/` 沒被藏其他專案資料的 gitignore 規則一併 ignore 掉。
4. 印出 next-steps 摘要。

### 6.8 Hooks

```json
{
  "SessionStart": [{ "hooks": [{ "type": "command",
    "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/docsync-bootstrap.py" }] }],
  "PostToolUse": [{ "matcher": "Edit|Write|MultiEdit",
    "hooks": [{ "type": "command",
      "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/docsync-guard.py" }] }],
  "Stop": [{ "hooks": [{ "type": "command",
    "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/docsync-finalcheck.py" }] }]
}
```

行為：

- `docsync-bootstrap.py` — 讀 yaml、檢查 `bootstrap_docs` 存在性、發 `systemMessage` 提醒。絕不擋 session start。
- `docsync-guard.py` — 每次 code 編輯時，match 規則、檢查 session 內該 doc 有沒有被動到。依 `enforcement`：silent / 透過 `systemMessage` warn / block（只有 kanban gate 啟用時）。
- `docsync-finalcheck.py` — session 結束：聚合變更、回報未同步的 docs。

### 6.9 Skill

`skills/docsync-workflow/SKILL.md` 教 Claude：

1. **`skip_conditions` 何時適用** — 語意判斷（例：null-check fix = `bug_fix_only`；改錯誤處理流程**不是**）。
2. **怎麼寫好 doc 更新** — `references/update-patterns.md` 給每 doc type 的 template。
3. **規則衝突解決** — 一次 code 變更觸發兩條規則時如何取捨。
4. **絕對規則** — 絕不為省時間跳過 `required: true` 的 doc；絕不自改 `.claude/docsync.yaml`（user 擁有）。

### 6.10 公開 CLI

```bash
# 哪些規則 match 這個路徑？
workbench-docsync match <file-path> --format json

# 自某個 git ref 以來有 pending 同步嗎？（exit 0 = 乾淨，2 = pending）
workbench-docsync check --since <git-ref> --format json

# 摘要此 session 的文件變更（給 memory 整合用）
workbench-docsync summarize --session <session-id> --format json
```

全部唯讀。絕不修改 YAML。

### 6.11 分類

docsync 是 `dev` 分類——不在預設 `workbench` meta。打包進 `workbench-dev`（§9.2）。

---

## 7. 同伴工具

### 7.1 Viewer — `kanban-tui`

給人看 / 編輯 `kanban.json` 的獨立 app。**不**依賴 Claude Code——任何符合 schema 的 viewer 都能用。

**實作**（推薦）：Python + [Textual](https://textual.textualize.io/)。

- 單一 Python codebase、跨平台。
- TUI + web（`textual serve`）。
- 散佈：`pipx install kanban-tui`；GitHub Releases 有 PyInstaller binary；未來 Homebrew tap。

**MVP 功能**：

- 四欄檢視（TODO / DOING / DONE / BLOCKED）。
- 任務卡：id、title、priority、category、tags。
- 展開卡 → description、comments、歷史。
- 鍵盤：`j/k` 選、`h/l` 跨欄移、`n` 新任務、`e` 編輯。
- 寫入前 schema 驗證。
- 檔案 watcher：外部編輯自動 reload。

**後續**：

- 依賴 DAG 檢視。
- Gantt / timeline。
- 多專案聚合檢視。
- Web 版（`textual serve`）。
- VSCode extension（獨立專案）。

### 7.2 Automation Runner

讓 Claude Code 不用開啟 live session 就能對 kanban 運作。三種模式：

#### 7.2.1 Cron polling（推薦預設）

由 `/kanban:enable-automation` 安裝。Crontab 行：

```cron
*/10 * * * * /home/kirin/.claude-workbench/bin/cron-runner.sh /home/kirin/myproject
```

`cron-runner.sh`：

1. `flock` 擋重入。
2. `git pull --ff-only`（絕不 merge）。
3. 本機預檢：有 ready TODO 嗎（deps 全 DONE）？無則早退——不 invoke Claude。
4. `claude -p "…"` 搭 `--allowedTools`、`--permission-mode acceptEdits`。
5. Log 到 `~/.claude-workbench/logs/cron-runner.log`。

用 user 的 `claude login`（Pro/Max 訂閱）。**不吃 API credit。**

#### 7.2.2 Git post-merge hook

由 `/kanban:enable-automation` mode 2 安裝。僅當 pull 的 diff 包含 `kanban.json` 才觸發。延遲低於 cron 但要 user 在主機 `git pull`。

#### 7.2.3 Webhook 伺服器（進階）

FastAPI 監聽 GitHub webhook。HMAC 驗證。當 `kanban.json` 變更合入 `main` 時觸發 headless Claude。v0.1.0 不包；部屬由 user 負責。

#### 7.2.4 成本

| 模式 | 認證 | 成本 |
|---|---|---|
| 本機 cron | `claude login`（Pro/Max） | 訂閱 |
| 本機 git-hook | `claude login`（Pro/Max） | 訂閱 |
| 自架 webhook | `claude login`（Pro/Max） | 訂閱 |
| GitHub Actions | `ANTHROPIC_API_KEY` | **API 計費** |

預設 docs 推薦前三者。GitHub Actions 標「只在可接受 API 計費時用」。

---

## 8. 跨 Plugin 整合

### 8.1 kanban × notify

在 `kanban-autocommit.sh` 狀態轉換後觸發：

| 事件 | 訊息 | 優先度 |
|---|---|---|
| TODO → DOING（長任務） | "Started: $title" | low |
| DOING → DONE | "Completed: $title" | normal |
| DOING → BLOCKED | "$id blocked: $reason" | high |
| `custom.needs_user_input == true` | "$id needs your decision" | high |

```bash
if [[ $HAS_NOTIFY -eq 1 ]]; then
    case "$prev->$new" in
        "TODO->DOING")    workbench-notify --priority low  --title "Kanban" --message "Started: $title" ;;
        "DOING->BLOCKED") workbench-notify --priority high --title "Kanban: action needed" --message "$tid blocked: $reason" ;;
        "DOING->DONE")    workbench-notify --priority normal --title "Kanban" --message "Completed: $title" ;;
    esac
fi
```

### 8.2 kanban × memory

**情境 A — 開始**：`/kanban:next` 的 prompt 包含：

> 執行任務前，若 `workbench-memory` 可用：從 title+tags 擷取關鍵字，跑 `workbench-memory search --query "<terms>" --limit 3 --format json`，在開始前呈現相關 match。

**情境 B — 完成**：`kanban-autocommit.sh` 在 `DOING → DONE` 時：

```bash
if [[ $HAS_MEMORY -eq 1 ]]; then
    workbench-memory save \
        --topic "Task $tid: $title" \
        --content "$completion_note" \
        --tags "$tags" \
        --source "kanban:$tid"
fi
```

### 8.3 notify × memory

當 `notify-dispatch.py` 處理 `elicitation_dialog` 時，可以帶上過去的決策：

```python
if has_memory_plugin():
    past = subprocess.run(
        ["workbench-memory", "search",
         "--query", context, "--tags", "decision",
         "--limit", "1", "--format", "json"],
        capture_output=True, text=True, timeout=3
    )
    if past.stdout:
        msg += f"\n\n💭 Past decision: {json.loads(past.stdout)['content'][:200]}"
```

### 8.4 docsync × kanban

**DONE gate**（`integration.kanban.block_done_if_pending: true`）：

`kanban-autocommit.sh` 確認 `DOING → DONE` 前：

```bash
if [[ $HAS_DOCSYNC -eq 1 ]]; then
    if ! workbench-docsync check --since "$(git merge-base HEAD main)" --format json \
        | jq -e '.pending | length == 0' >/dev/null; then
        echo "Task cannot be marked DONE: docsync has pending syncs" >&2
        workbench-docsync check --since "$(git merge-base HEAD main)"
        exit 2
    fi
fi
```

**任務驅動的 bootstrap 擴充**：若任務 description 提到特定 doc 路徑，docsync 此 session 暫時把它們加到 `bootstrap_docs`。

### 8.5 docsync × memory

當 `integration.memory.summarize_doc_changes: true`，`docsync-finalcheck.py` 在 session 結束：

```bash
if [[ $HAS_MEMORY -eq 1 ]]; then
    for doc in "${UPDATED_DOCS[@]}"; do
        summary=$(workbench-docsync summarize --file "$doc" --format json)
        workbench-memory save \
            --topic "Doc update: $doc" \
            --content "$summary" \
            --tags "docsync,$(basename $doc .md)" \
            --source "docsync:$SESSION_ID"
    done
fi
```

下次改類似 code 時 memory 就會 recall「上次改這種 code 時，我們是這樣改 doc」。

### 8.6 docsync × notify（被動）

docsync 從不直接 call notify——doc 漂移不值得推播。**但**當 `enforcement: block` 擋下 kanban DONE（§8.4），那個被擋的轉換會透過 kanban 的 notify 整合（§8.1）以 `needs_user_input = true` 觸發推播。

### 8.7 Capability Detection 標準

每個整合感知的 script 開頭都是：

```bash
has_plugin() { command -v "workbench-$1" >/dev/null 2>&1; }
HAS_KANBAN=0;  has_plugin kanban  && HAS_KANBAN=1
HAS_NOTIFY=0;  has_plugin notify  && HAS_NOTIFY=1
HAS_MEMORY=0;  has_plugin memory  && HAS_MEMORY=1
HAS_DOCSYNC=0; has_plugin docsync && HAS_DOCSYNC=1
```

注意事項：`command -v` 只證明 CLI 存在，不證明相鄰者有設定。未來精修：每個 CLI 加 `--health` subcommand，ready 就 exit 0——改用它做偵測。

### 8.8 全裝時的端到端 UX

```
[09:00] User 出門前在 viewer 加 task-050 "Refactor lending bot pricing"

[09:15] Cron 觸發 → headless Claude 開始
        [SessionStart hooks]
        ├─ kanban:    看到 task-050 在 TODO → 自動 /kanban:next
        ├─ memory:    注入「2024-03：類似的 refactor 用了 EMA smoothing」
        └─ docsync:   提醒閱讀 doc/ARCHITECTURE.md + position-manager/README.md

[09:20] Claude refactor 中；遇到 rate-limit 設計決策
        [elicitation_dialog event]
        ├─ notify:    Pushover 推到手機：
        │     "Decide: token bucket or leaky bucket?
        │      💭 Past decision: 2025-12 you chose token bucket"
        └─ Claude 等待

[09:22] User 通勤中，用 iOS app 回 "token bucket"

[09:30] Claude 寫完；嘗試 /kanban:done
        ├─ docsync gate：position-manager/dynamic_param.md 有 pending 同步
        ├─ Claude 更新 doc
        └─ 重試 DONE → 通過 gate

[09:31] 狀態 fan-out
        ├─ kanban:    DOING → DONE，autocommit
        ├─ notify:    Pushover "task-050 complete"
        ├─ memory:    存「task-050：選 token bucket，理由 …」
        └─ docsync:   把 "position-manager/dynamic_param.md updated: …" 寫進 memory

[19:00] User 回家，打開 viewer：task-050 DONE，時間線和決策紀錄完整
```

---

## 9. Meta-plugin

### 9.1 `workbench`（核心組合包）

```json
{
  "name": "workbench",
  "version": "0.1.0",
  "description": "Complete Claude Workbench — kanban + notify + memory",
  "author": "kirin",
  "dependencies": [
    { "name": "kanban", "version": "^0.1.0" },
    { "name": "notify", "version": "^0.1.0" },
    { "name": "memory", "version": "^0.1.0" }
  ]
}
```

自己沒有 command / skill / hook——純相依宣告。

### 9.2 `workbench-dev`（開發者組合包）

```json
{
  "name": "workbench-dev",
  "version": "0.1.0",
  "description": "Claude Workbench for developers — core + docsync + (future: review, lint)",
  "author": "kirin",
  "dependencies": [
    { "name": "workbench", "version": "^0.1.0" },
    { "name": "docsync",   "version": "^0.1.0" }
  ]
}
```

疊在 `workbench` 之上，避免核心三者之間的版本 drift。

---

## 10. Repository 結構

```
kirin/claude-workbench/
├── README.md
├── LICENSE                                  # MIT
├── CHANGELOG.md
├── SPEC.md                                  # 本檔
├── current_state.md                         # 實作快照
│
├── .claude-plugin/
│   └── marketplace.json                     # 6 條目（4 plugin + 2 meta）
│
├── plugins/
│   ├── kanban/                              # §3
│   ├── notify/                              # §4
│   ├── memory/                              # §5
│   ├── docsync/                             # §6
│   ├── workbench/                           # §9.1 meta
│   └── workbench-dev/                       # §9.2 meta
│
├── viewer/                                  # §7.1（選用）
│   ├── pyproject.toml
│   └── src/kanban_tui/
│
├── automation/                              # §7.2 canonical runner 原始碼
│   ├── cron-runner.sh
│   ├── git-hooks/post-merge
│   ├── webhook-server.py
│   └── systemd/kanban-agent.service
│
├── schema/                                  # canonical schema
│   ├── kanban.schema.json
│   └── docsync.schema.json
│
├── docs/
│   ├── quickstart.md
│   ├── architecture.md
│   ├── composition.md                       # plugin 如何相乘
│   ├── provider-setup/{pushover,ntfy}.md
│   ├── plugin-development.md
│   └── troubleshooting.md
│
├── scripts/                                 # CI helper
│   ├── sync-schema.sh                       # schema/ → plugins/*/templates/
│   ├── sync-automation.sh                   # automation/ → plugins/kanban/scripts/
│   └── validate-plugins.sh
│
└── .github/workflows/
    ├── ci.yml                               # lint、test、validate-plugin
    ├── release-viewer.yml
    └── release.yml
```

### 10.1 `marketplace.json`（6 條目）

```json
{
  "name": "claude-workbench",
  "owner": { "name": "Kirin" },
  "plugins": [
    { "name": "kanban",  "source": "./plugins/kanban",  "description": "Kanban workflow", "category": "productivity", "keywords": ["kanban","tasks"] },
    { "name": "notify",  "source": "./plugins/notify",  "description": "Push notifications", "category": "productivity", "keywords": ["notifications","pushover"] },
    { "name": "memory",  "source": "./plugins/memory",  "description": "Persistent RAG memory", "category": "productivity", "keywords": ["memory","rag"] },
    { "name": "docsync", "source": "./plugins/docsync", "description": "Code ↔ doc sync tracking", "category": "developer-tools", "keywords": ["docs","drift"] },
    { "name": "workbench",     "source": "./plugins/workbench",     "description": "★ Core bundle (kanban + notify + memory)", "category": "productivity", "keywords": ["bundle","meta"] },
    { "name": "workbench-dev", "source": "./plugins/workbench-dev", "description": "★ Dev bundle (workbench + docsync)", "category": "developer-tools", "keywords": ["bundle","meta"] }
  ]
}
```

### 10.2 Schema Sync 策略

`schema/*.json` 是 canonical。CI（`scripts/sync-schema.sh`）複製到：

- `plugins/kanban/templates/kanban.schema.json`
- `plugins/docsync/templates/docsync.schema.json`
- `viewer/src/kanban_tui/schema.json`

一個來源、三個鏡像、零手改。

### 10.3 Automation Sync 策略

`automation/*` 是 canonical。CI（`scripts/sync-automation.sh`）把需要跟 plugin 一起 ship 的 script（給 `/kanban:enable-automation` 用）複製到 `plugins/kanban/scripts/`。

---

## 11. 安全

### 11.1 Plugin 安全

- 所有 hook script 用 `set -euo pipefail`。
- `kanban-guard.sh` 拒絕任何繞過 schema 的嘗試（對 `kanban.json` 做 Edit/Write）。
- 絕不執行來自 `kanban.json`、`memory.db`、`.claude/docsync.yaml` 內容的任意字串。
- `--allowedTools` 永遠是明確白名單。無萬用字元。

### 11.2 Automation 安全

- Webhook 伺服器必須驗 HMAC 簽章。
- Cron runner 用 `flock` 擋重入。
- Runner log 不應含完整訊息 body（避免透過 log 洩漏 secret）。
- User 負責 `kanban.json` / `memory.db` / `docsync.yaml` 不含 secret；hook 層級 secret 掃描是未來工作。

### 11.3 Memory 隱私

- 所有資料本機。Embedding model 本機跑。
- `memory.db` 預設 `0600`。
- 透過 `hash(cwd)` 做專案隔離；除非 user 顯式跨專案查詢，否則絕不跨洩漏。

### 11.4 Notify 安全

- 所有 provider 都 HTTPS-only。
- Response body 絕不寫回 `kanban.json` 或 `memory.db`。
- 訊息 scrubber 在送前 mask token 形態子字串。

### 11.5 Secret 處理

- Config 裡用 `${ENV_VAR}` 展開；絕不把 secret inline 進 JSON。
- 文件推薦 `.env` + `direnv` 模式。
- 每個分類給 `.gitignore` template。

### 11.6 供應鏈

- Release binary 附 SHA256。
- 簽名 git commit。
- 考慮中：Sigstore / cosign。

### 11.7 隱私

- 無 telemetry。
- 除了用 headless 時的 Anthropic API 本身以外，無第三方資料出站。
- Headless 對話遵守 Anthropic 隱私政策。

---

## 12. 版號與 Release

Monorepo 用單一 Semantic Version：

- **MAJOR** — 任何 plugin 破壞 schema 或公開 API。
- **MINOR** — 新功能、新 plugin。
- **PATCH** — bug fix。

Meta-plugin 依賴用 caret（`^0.1.0`），minor 升級自動傳播。

Release 流程：

1. 更新 `CHANGELOG.md`。
2. 更新所有 `plugin.json` + `marketplace.json` 的版號（script 輔助）。
3. `git tag v0.2.0 && git push origin v0.2.0`。
4. CI 驗 plugin、同步 schema、3 平台 build viewer、發 GitHub Release + PyPI。

使用者升級：

```bash
/plugin update kanban@claude-workbench         # 單一 plugin
/plugin update workbench@claude-workbench      # 核心 bundle
/plugin update workbench-dev@claude-workbench  # 開發者 bundle
```

Breaking schema 升版附 migration CLI：

```bash
kanban-tui migrate --from 1 --to 2 kanban.json
```

---

## 13. MVP Roadmap

| 階段 | 目標 | 狀態 |
|---|---|---|
| **0a** — Workbench 骨架（marketplace、stub plugin、schema） | v0.1.0 bootstrap | ✓ 完成 |
| **0b** — kanban 完工（`/kanban:block`、`/kanban:enable-automation`、cron script） | v0.1.0 kanban | ✓ 完成 |
| **1** — kanban v0.1.0 驗證 | 1 週真實專案使用 | 進行中 |
| **2** — notify v0.1.0（Pushover + `workbench-notify` CLI） | 1 週 | 待辦 |
| **3** — kanban × notify 整合 | 2–3 天 | 待辦 |
| **4** — memory v0.1.0（SQLite + MCP + embeddings） | 2 週 | 待辦 |
| **5** — 三方整合（§8.8 端到端流程） | 1 週 | 待辦 |
| **6** — `workbench` bundle 釋出 | 0.5 週 | 待辦 |
| **7** — docsync v0.1.0 + `workbench-dev` bundle | 2 週 | 待辦 |
| **8+**（v0.2+） — 追加 notify provider；memory 冷儲存 / 跨專案；viewer DAG + web；kanban webhook runner；`review`/`lint`/`schedule` 新 plugin | 持續 | backlog |

docsync 刻意排最後——它依賴較早階段建立的成熟跨 plugin 整合模式。

---

## 14. Open Questions

編號以利跨討論引用：

1. **Task ID 產生**：單調遞增（`task-043`）vs hash（`task-a4f2`）？單調遞增在多人時會撞。
2. **DONE 歸檔**：何時把舊 DONE 移到 `kanban-archive/YYYY-MM.json`？按數量？年齡？大小？
3. **併發的 headless Claude**：多台機器 cron 撞同一個 repo——`DOING + timestamp` 是足夠的鎖嗎？
4. **Viewer 寫入衝突**：last-write-wins + 檔案 watcher reload（v0.1）或 CRDT（未來）？
5. **Schema 擴充機制**：使用者要 `custom` 以外的頭等欄位——支援專案區域 schema 擴充？
6. **多 repo 聚合**：跨專案全域 kanban 檢視——有用還是肥大？
7. **Memory 範圍 / 跨專案搜尋**：啟用的隱私影響。
8. **Notify rate limiting**：避免告警疲勞的 UX 模式？
9. **Plugin 版號 skew**：kanban v0.2（新 schema）+ notify v0.1 仍安裝——優雅處理？
10. **Viewer 納入 marketplace**：只 PyPI / 獨立，還是也進 marketplace？
11. **Memory embedding model 安裝 UX**：~80 MB 首次下載——進度條？第一次 save 時惰性下載？
12. **docsync section 級別粒度**：如何偵測「user 更新了 section X」——標題標記，或保守的「任何 edit = 同步」？
13. **docsync 語意條件**：`required_if: api_changed`——v0.2 前 skill 能把 Claude 的判斷推多遠？
14. **docsync 多語言單一倉庫**：Rust + Python + shell 混雜時的 template 組合策略。
15. **docsync 改名 / 搬家**：`git mv` 當 code 變更——會觸發規則嗎？若舊檔名仍在文件中怎辦？
16. **docsync ↔ CLAUDE.md 共存**：提示 user 移除 docsync 現在接管的 CLAUDE.md section，還是讓兩者共存？
17. **docsync 大規模效能**：大型單一倉庫跑 `/docsync:check --since main`——cache 策略？

---

## 15. 參考

- [Claude Code Plugins — docs](https://code.claude.com/docs/en/plugins)
- [Claude Code Plugins — reference](https://code.claude.com/docs/en/plugins-reference)
- [Claude Code Hooks — reference](https://code.claude.com/docs/en/hooks)
- [Claude Code Headless mode](https://code.claude.com/docs/en/headless)
- [Claude Code `AskUserQuestion` tool](https://code.claude.com/docs/en/plugins-reference#ask-user-question)
- [Model Context Protocol](https://modelcontextprotocol.io)
- [JSON Schema draft-07](https://json-schema.org/draft-07)
- [sqlite-vss](https://github.com/asg017/sqlite-vss)
- [sentence-transformers](https://www.sbert.net/)
- [Pushover API](https://pushover.net/api)
- [Textual](https://textual.textualize.io/)
- 先前相關作品：Obsidian Kanban plugin、GitHub Projects、Linear API。

---

## 附錄 A — 安裝 UX 腳本

### A.1 漸進安裝

```bash
# Day 1 — 先裝 kanban
$ claude
> /plugin marketplace add kirin/claude-workbench
> /plugin install kanban@claude-workbench
> /kanban:init --with-examples
> /kanban:next

# Day 7 — 加推播
> /plugin install notify@claude-workbench
> /notify:setup       # 引導式 Pushover 設定
> /notify:test

# Day 14 — 加 memory
> /plugin install memory@claude-workbench
> /memory:init        # 下載 embedding model、建 SQLite

# Day 21 — 加 docsync（dev 分類，opt-in）
> /plugin install docsync@claude-workbench
> /docsync:init       # 互動式 scan → interview → dry-run → write
```

### A.2 一次到位 bundle

```bash
# 只要核心
> /plugin install workbench@claude-workbench
> /kanban:init && /notify:setup && /memory:init

# 開發者完整 stack
> /plugin install workbench-dev@claude-workbench
> /kanban:init && /notify:setup && /memory:init && /docsync:init
```

### A.3 啟用自動化

```bash
> /kanban:enable-automation

Claude: Which trigger?
  1. Cron polling (every 10 min, recommended)
  2. Git post-merge hook

User: 1
Claude: Interval? (default 10)
User: 10

Claude: Installing…
Installed:
  */10 * * * * /home/kirin/.claude-workbench/bin/cron-runner.sh /home/kirin/my-project
Logs: ~/.claude-workbench/logs/cron-runner.log
Remove: crontab -e and delete the tagged lines.
```

---

## 附錄 B — Plugin 互動矩陣

列 = 消費方；行 = 提供方。儲存格 = 消費方於提供方安裝時得到的能力。

| | kanban | notify | memory | docsync |
|---|---|---|---|---|
| **kanban** | — | 任務狀態轉換推播 | next 時查過去、done 時存 | DONE gate（當 enforcement=block） |
| **notify** | 狀態轉換觸發 | — | prompt 內帶「過去決策：…」 | —（docsync 不直接推播） |
| **memory** | 任務事件 → 存 | — | — | 文件變更摘要 |
| **docsync** | 任務描述 → bootstrap 擴充 | — | 寫入摘要 | — |

空格 ≠ 「不可能」——只是 v0.1.0 還沒接。新整合可在 minor release 加，不動 schema。

---

*End of SPEC_zhtw.md*
