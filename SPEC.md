# Claude Kanban — SPEC

**Project**: `kirin/claude-kanban`
**Version**: 0.1.0 (Draft)
**Last Updated**: 2026-04-20
**Author**: Kirin

---

## 1. 專案概觀

### 1.1 What

`claude-kanban` 是一組讓 Claude Code CLI 以 **kanban.json** 作為工作橋樑的工具集。使用者透過編輯 kanban.json（手動或透過 viewer）傳遞任務給 Claude，Claude 自主選取、執行、更新狀態，形成「AI 同事」般的協作模式。

### 1.2 Why

傳統使用 Claude Code 的模式是**每次開 session → 口頭下指令 → 等 AI 執行**。此模式的痛點：

- 無法持久化任務佇列，session 關閉後 context 消失
- 無法事件驅動觸發（例如 git push 後自動接手）
- 任務狀態無法從外部工具觀察
- 多台機器 / 多 session 之間無法共享工作清單

本專案以 **kanban.json 作為 single source of truth**，讓 AI 跟人都能讀寫同一份狀態，解決上述所有問題。

### 1.3 Design Principles

1. **Has-a, not is-a**：以 plugin 形式注入能力，不強迫 fork template
2. **漸進式採用**：每個元件獨立可用，使用者可選擇只裝 plugin、或加 viewer、或加 automation
3. **Deterministic engine + AI judgement**：程式碼處理硬性規則（hooks、schema），AI 處理需要判斷的部分
4. **職責分離**：plugin 給 AI 用、viewer 給人用、automation 串接兩者
5. **Cost-aware**：預設走 Claude Pro/Max 訂閱（headless 模式），不燒 API credit

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  使用者 Project (existing repo)                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  kanban.json          ← single source of truth        │   │
│  │  kanban.schema.json   ← local schema (from plugin)    │   │
│  │  .claude/             ← Claude Code project config    │   │
│  └──────────────────────────────────────────────────────┘   │
│         ▲                    ▲                    ▲          │
│         │ read/write         │ read/write         │ read     │
│         │                    │                    │          │
│  ┌──────┴──────┐     ┌──────┴──────┐     ┌───────┴──────┐   │
│  │ Claude Code │     │   Viewer    │     │  Automation  │   │
│  │  + plugin   │     │  (TUI/GUI)  │     │   runner     │   │
│  └──────┬──────┘     └─────────────┘     └───────┬──────┘   │
│         │                                         │          │
│         └───────── headless `claude -p` ──────────┘          │
└─────────────────────────────────────────────────────────────┘
```

三個元件職責：

| 元件 | 主要使用者 | 形態 | 必要性 |
|---|---|---|---|
| **Plugin** | Claude Code (AI) | Claude Code marketplace plugin | 必須 |
| **Viewer** | 人類使用者 | TUI / Web / Desktop binary | 選配 |
| **Automation** | 觸發器 | cron / git hook / webhook | 選配 |

---

## 3. Data Model

### 3.1 kanban.json 結構

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
        "blocked_reason": null
      }
    }
  ]
}
```

### 3.2 欄位規範

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `schema_version` | integer | ✓ | 目前為 1,未來結構變更時遞增 |
| `meta.priorities` | string[] | ✓ | 優先順序列舉值,P0 最高 |
| `meta.categories` | string[] | | 使用者自定分類 |
| `meta.columns` | string[] | ✓ | 固定為 TODO/DOING/DONE/BLOCKED |
| `tasks[].id` | string | ✓ | 格式 `task-NNN`,至少三位數字 |
| `tasks[].title` | string | ✓ | 單行描述 |
| `tasks[].column` | enum | ✓ | 必須是 `meta.columns` 之一 |
| `tasks[].priority` | enum | ✓ | 必須是 `meta.priorities` 之一 |
| `tasks[].category` | string | | 必須是 `meta.categories` 之一 |
| `tasks[].tags` | string[] | | 任意標籤 |
| `tasks[].depends` | string[] | | 其他 task.id 的列表 |
| `tasks[].created` | ISO 8601 | ✓ | 必帶時區 |
| `tasks[].updated` | ISO 8601 | ✓ | 每次修改更新 |
| `tasks[].started` | ISO 8601 | | 移入 DOING 時設定 |
| `tasks[].completed` | ISO 8601 | | 移入 DONE 時設定 |
| `tasks[].assignee` | string | | `claude-code` 或人名 |
| `tasks[].description` | string | | Multi-line 描述 |
| `tasks[].comments` | object[] | | 見下方 |
| `tasks[].custom` | object | | Schema-free 擴充欄位 |

### 3.3 Comment 結構

```json
{
  "author": "kirin | claude-code | <其他>",
  "ts": "ISO 8601 with timezone",
  "text": "comment body"
}
```

### 3.4 狀態轉移規則

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

轉移限制：

- **TODO → DOING**：`started` 必須設為當下時間；所有 `depends` 必須已在 DONE
- **DOING → DONE**：`completed` 必須設為當下時間
- **DOING → BLOCKED**：`custom.blocked_reason` 必須有值
- **BLOCKED → TODO**：清除 `custom.blocked_reason`
- **DONE → 任何狀態**：禁止（已完成不可回滾；如需重開請新建 task）

---

## 4. Component 1 — Claude Code Plugin

### 4.1 Plugin 目錄結構

```
plugins/kanban/
├── .claude-plugin/
│   └── plugin.json                     # plugin 元資料
├── skills/
│   └── kanban-workflow/
│       ├── SKILL.md                    # 主規則
│       └── references/
│           ├── schema-spec.md          # 給 AI 看的 schema 說明
│           ├── priority-rules.md       # 優先順序判斷邏輯
│           └── dependency-rules.md     # 依賴處理邏輯
├── commands/
│   ├── init.md                         # /kanban:init
│   ├── next.md                         # /kanban:next
│   ├── done.md                         # /kanban:done
│   ├── block.md                        # /kanban:block
│   ├── status.md                       # /kanban:status
│   └── enable-automation.md            # /kanban:enable-automation
├── hooks/
│   └── hooks.json                      # hook 設定
├── scripts/
│   ├── kanban-guard.sh                 # 檔案守衛(PreToolUse)
│   ├── kanban-autocommit.sh            # 自動 commit(PostToolUse)
│   ├── kanban-session-check.sh         # session 起始檢查
│   └── install-cron.sh                 # 啟用 polling 用
└── templates/
    ├── kanban.schema.json              # JSON Schema
    ├── kanban.empty.json               # 空白種子
    └── kanban.example.json             # 範例種子
```

### 4.2 `plugin.json`

```json
{
  "name": "kanban",
  "version": "0.1.0",
  "description": "Kanban-driven workflow for Claude Code. Manages task lifecycle through kanban.json.",
  "author": "kirin",
  "homepage": "https://github.com/kirin/claude-kanban",
  "license": "MIT"
}
```

### 4.3 Skill Design

**`skills/kanban-workflow/SKILL.md`** 觸發條件（寫在 frontmatter description）：

> Use this skill whenever kanban.json exists in the project root, or when the user mentions tasks, TODO, kanban, priorities, or asks "what should I work on next", "pick a task", "繼續工作" etc.

Skill 正文涵蓋：

1. 讀 kanban.json 的時機與方式
2. 狀態轉移的強制規則（引用 §3.4）
3. 依賴處理：遇到有 unresolved deps 的 task 時怎麼判斷
4. 優先順序邏輯：同 priority 多個 task 時的 tie-breaker
5. 遇到衝突或歧異時的 escalation 方式（新增 BLOCKED task、寫 comment 問使用者）
6. 絕對禁止事項（直接 edit kanban.json、改 DONE task、繞過 hooks）

### 4.4 Slash Commands

| Command | Argument | 用途 |
|---|---|---|
| `/kanban:init` | `[--with-examples]` | 初始化 kanban.json + schema |
| `/kanban:next` | `[--category=X] [--priority=Y]` | 選下一個 task 並開始 |
| `/kanban:done` | `[<task-id>] [--note=<text>]` | 標記完成(預設當前 DOING 的 task) |
| `/kanban:block` | `<task-id> --reason=<text>` | 移到 BLOCKED 欄 |
| `/kanban:status` | | 列出當前 kanban 狀態摘要 |
| `/kanban:enable-automation` | | 設定 cron/git hook/webhook |

每個 command 的 prompt 包含：

- `argument-hint` frontmatter 供 Claude Code autocomplete
- 引用 `${CLAUDE_PLUGIN_ROOT}/templates/` 或 `scripts/` 的路徑
- 明確步驟清單（不留 AI 自由發揮空間，確保 deterministic 行為）

### 4.5 Hooks

**`hooks/hooks.json`**：

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

**Hook 行為規範**：

- `kanban-session-check.sh`：`git fetch`,若 kanban.json 有遠端變動則 inject `systemMessage` 提醒
- `kanban-session-check.sh --lightweight`：僅檢查本地 kanban.json 是否有 DOING task,提醒當前任務
- `kanban-guard.sh`：若 Claude 嘗試直接 edit kanban.json → exit 2,inject 錯誤訊息要求改用 `/kanban:*` command
- `kanban-autocommit.sh`：偵測 kanban.json 是否因 bash 命令變動,若是則自動 `git commit -m "kanban: <task-id> <column-transition>"`

### 4.6 Templates（會被複製到使用者 project）

| 檔案 | 何時被複製 | 目標路徑 |
|---|---|---|
| `kanban.schema.json` | `/kanban:init` | `<project>/kanban.schema.json` |
| `kanban.empty.json` | `/kanban:init`(預設) | `<project>/kanban.json` |
| `kanban.example.json` | `/kanban:init --with-examples` | `<project>/kanban.json` |

Templates 是 plugin 中**唯一會離開 plugin 安裝目錄進入使用者專案**的檔案。

---

## 5. Component 2 — Viewer

### 5.1 設計目標

- 視覺化 kanban.json 給人類使用者看
- 支援手動 drag-and-drop 移動 task（寫回 kanban.json）
- **不依賴 Claude Code**：可獨立安裝使用
- **不綁定任何 viewer 實作**：plugin 只認 kanban.json，任何符合 schema 的 viewer 都能用

### 5.2 推薦實作：`kanban-tui`（Python + Textual）

**為什麼選 Textual**：

- 單一 Python codebase 跨平台
- 可以同時輸出 TUI 跟 Web（Textual 支援 `textual serve`）
- 安裝透過 `pipx install kanban-tui`，使用者熟悉
- Kirin 熟 Python，維護成本低

### 5.3 核心功能（MVP）

- [ ] 四欄 kanban 視圖（TODO / DOING / DONE / BLOCKED）
- [ ] Task 卡片顯示：id, title, priority, category, tags
- [ ] 點擊卡片展開詳情（description, comments, history）
- [ ] Keyboard shortcut 移動 task（`j/k` 選，`h/l` 移欄）
- [ ] 新增 task（`n` 鍵開表單）
- [ ] 編輯 comment / description
- [ ] Schema 驗證：寫回前驗證，不通過則拒絕
- [ ] File watcher：偵測 kanban.json 被外部修改時自動 reload

### 5.4 後續擴充

- [ ] 依賴關係視覺化（DAG 圖）
- [ ] 時間軸視圖（Gantt）
- [ ] 多 project 聚合視圖
- [ ] Web 版（`textual serve kanban_tui.app:KanbanApp`）
- [ ] VSCode extension（獨立 side project）

### 5.5 分發

- **PyPI**: `pipx install kanban-tui`
- **GitHub Releases**: 用 PyInstaller 打包單檔 binary（Windows .exe / macOS .app / Linux AppImage）供不熟 Python 的使用者
- **Homebrew tap**（未來）

---

## 6. Component 3 — Automation

### 6.1 目標

讓 Claude Code 在使用者**未主動開 session** 的情況下，由外部事件觸發執行 kanban task。

### 6.2 三種觸發模式

#### 6.2.1 Cron Polling（推薦預設）

**`automation/cron-runner.sh`**：

```bash
#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:?project dir required}"
LOCK_FILE="/tmp/kanban-$(echo $PROJECT_DIR | md5sum | cut -d' ' -f1).lock"

# 防重入
exec 200>"$LOCK_FILE"
flock -n 200 || { echo "Previous run still executing"; exit 0; }

cd "$PROJECT_DIR"
git pull --quiet --ff-only || exit 1

# headless 模式呼叫 Claude,吃訂閱額度
claude -p "$(cat ${CLAUDE_PLUGIN_ROOT}/scripts/runner-prompt.md)" \
  --allowedTools "Read,Write,Edit,Bash(git:*),Bash(kanban:*)" \
  --permission-mode acceptEdits \
  --output-format json \
  >> /var/log/kanban-agent.log 2>&1
```

**Crontab 範例**（由 `/kanban:enable-automation` 自動安裝）：

```cron
*/10 * * * * /home/kirin/.claude-kanban/cron-runner.sh /home/kirin/myproject
```

#### 6.2.2 Git Hook（post-merge）

**`automation/git-hooks/post-merge`**：

使用者本機 `git pull` 後自動觸發。適合個人開發機，延遲極低。

```bash
#!/usr/bin/env bash
changed=$(git diff-tree -r --name-only --no-commit-id ORIG_HEAD HEAD)
if echo "$changed" | grep -q '^kanban\.json$'; then
    claude -p "kanban.json changed via git pull, process any new TODO tasks" \
      --allowedTools "Read,Write,Edit,Bash(git:*)" \
      --permission-mode acceptEdits &
fi
```

#### 6.2.3 Webhook（進階）

**`automation/webhook-server.py`**：FastAPI server 接 GitHub webhook，push 到 main 且 kanban.json 變動時觸發 headless Claude。

適合有 remote server 且希望團隊協作的場景。安裝指引獨立於 plugin 之外（需要使用者自己部署 server 並設定 HMAC secret 驗證）。

### 6.3 成本考量

| 觸發模式 | 認證方式 | 成本計算 |
|---|---|---|
| 本機 cron | 使用者 Claude Pro/Max 登入 | 訂閱額度 |
| 本機 git hook | 使用者 Claude Pro/Max 登入 | 訂閱額度 |
| Webhook on personal server | 使用者 Claude Pro/Max 登入 | 訂閱額度 |
| GitHub Actions | `ANTHROPIC_API_KEY` | **API 付費** |

預設推薦前三種；GitHub Actions 方案在文件中標註「僅適合 API 付費可接受的情境」。

---

## 7. Repository Structure（Monorepo）

```
kirin/claude-kanban/
├── README.md                           # 總入口
├── LICENSE                             # MIT
├── CHANGELOG.md
├── SPEC.md                             # 本文件
│
├── .claude-plugin/
│   └── marketplace.json                # Claude Code marketplace 清單
│
├── plugins/
│   └── kanban/                         # 見 §4
│
├── viewer/
│   ├── pyproject.toml
│   ├── src/kanban_tui/
│   │   ├── __init__.py
│   │   ├── app.py                      # Textual app entry
│   │   ├── models.py                   # kanban.json parser + validator
│   │   ├── widgets/                    # 卡片、欄位、表單
│   │   └── schema.py                   # 引用 plugin 的 schema
│   ├── tests/
│   └── README.md
│
├── automation/
│   ├── cron-runner.sh
│   ├── git-hooks/
│   │   └── post-merge
│   ├── webhook-server.py
│   ├── systemd/
│   │   └── kanban-agent.service
│   └── README.md
│
├── docs/
│   ├── quickstart.md
│   ├── architecture.md
│   ├── plugin-development.md
│   └── troubleshooting.md
│
├── schema/
│   └── kanban.schema.json              # 主 schema,由 CI 同步到 plugin/templates/
│
├── scripts/
│   ├── sync-schema.sh                  # 把 schema/ 同步到 plugins/kanban/templates/
│   ├── sync-automation.sh              # 把 automation/script 同步到 plugin/scripts/
│   └── validate-plugin.sh              # 驗證 plugin 結構
│
└── .github/
    └── workflows/
        ├── ci.yml                      # lint, test, validate-plugin
        ├── release-viewer.yml          # build viewer binary, publish PyPI
        └── release.yml                 # tag → sync → release notes
```

### 7.1 `marketplace.json`

```json
{
  "name": "claude-kanban",
  "owner": {
    "name": "Kirin",
    "email": "kirin@example.com"
  },
  "plugins": [
    {
      "name": "kanban",
      "source": "./plugins/kanban",
      "version": "0.1.0",
      "description": "Kanban-driven workflow for Claude Code",
      "category": "productivity",
      "keywords": ["kanban", "tasks", "workflow", "automation"]
    }
  ]
}
```

### 7.2 Schema 同步策略

`schema/kanban.schema.json` 是主檔，CI 自動同步到：

- `plugins/kanban/templates/kanban.schema.json`（plugin 使用）
- `viewer/src/kanban_tui/schema.json`（viewer 使用）

避免三處手動維護不同步。

### 7.3 Automation script 同步策略

同上模式：`automation/` 是主檔，CI 把需要在 plugin 內部引用的 script 複製到 `plugins/kanban/scripts/`。

---

## 8. Versioning & Release

### 8.1 版本策略

單一版本號涵蓋整個 repo，使用 **Semantic Versioning**：

- **MAJOR**: kanban.json schema 破壞性變更
- **MINOR**: 新增 command / hook / viewer 功能
- **PATCH**: bug fix、文件修正

### 8.2 Release 流程

```bash
# 1. 更新 CHANGELOG.md
# 2. 更新 plugin.json, pyproject.toml, marketplace.json 的 version
# 3. 打 tag
git tag v0.2.0
git push origin v0.2.0

# GitHub Actions 會自動:
# - 驗證 plugin 結構
# - 同步 schema / scripts
# - Build viewer binary (三平台)
# - 發 GitHub Release 附 binary + SHA256
# - 發 PyPI package
```

### 8.3 使用者升級路徑

```bash
# Plugin 升級
claude
> /plugin update kanban@claude-kanban

# Viewer 升級
pipx upgrade kanban-tui

# Schema 破壞性升級時提供 migration CLI
kanban-tui migrate --from 1 --to 2 kanban.json
```

---

## 9. Security Considerations

### 9.1 Plugin 安全

- 所有 hook script 用 `set -euo pipefail`
- `kanban-guard.sh` 拒絕任何試圖繞過 schema 驗證的行為
- 不執行使用者 kanban.json 裡的任意內容（避免 description 中的 shell injection）
- Plugin 不請求敏感 tool 權限（無 Bash 全權限，只限 `git:*` 跟 `kanban:*`）

### 9.2 Automation 安全

- Webhook server 必須驗證 HMAC signature
- Cron runner 用 `flock` 防重入
- 禁止在 kanban.json 或 description 中貼入 secrets（hook 可選配 secret scanning）
- Headless 模式 `--allowedTools` 明確列舉，不使用 wildcard

### 9.3 供應鏈安全

- GitHub Releases 所有 binary 附 SHA256
- Plugin 變更需要 signed commit
- 未來可加 Sigstore / cosign 簽章

### 9.4 隱私

- 不送 kanban 內容到任何第三方服務（Anthropic API 以外）
- 不做 telemetry
- 使用者若用 headless 模式，對話紀錄遵循 Anthropic 的隱私政策

---

## 10. MVP Scope

### 10.1 Must-have（v0.1.0）

- [x] SPEC.md（本文件）
- [ ] `marketplace.json` + `plugin.json` 可被 Claude Code 認識
- [ ] `kanban.schema.json`（完整版）
- [ ] `/kanban:init` command
- [ ] `/kanban:next` command
- [ ] `/kanban:done` command
- [ ] `/kanban:status` command
- [ ] `skills/kanban-workflow/SKILL.md`
- [ ] `kanban-guard.sh` PreToolUse hook
- [ ] `kanban-autocommit.sh` PostToolUse hook
- [ ] Templates: empty + example
- [ ] README with 3-step install

### 10.2 Should-have（v0.2.0）

- [ ] `/kanban:block` + `/kanban:enable-automation`
- [ ] `SessionStart` hook with git fetch check
- [ ] Viewer MVP（Textual TUI,四欄檢視 + 移動）
- [ ] Cron-runner script + installer
- [ ] `docs/quickstart.md`

### 10.3 Nice-to-have（v0.3.0+）

- [ ] Viewer: 依賴關係 DAG 視圖
- [ ] Webhook server
- [ ] GitHub Actions 整合範例
- [ ] VSCode extension
- [ ] Multi-project aggregated view
- [ ] kanban CLI tool（`kanban list`, `kanban move`, 給 hook 內部使用）

---

## 11. Open Questions

需要在開發過程中決定：

1. **Task ID 生成策略**：連續遞增（`task-043`）還是 hash-based（`task-a4f2`）？連續遞增在 multi-user 情境有衝突風險。
2. **DONE task 歸檔**：kanban.json 長期會變肥,是否定期搬到 `kanban-archive/YYYY-MM.json`?搬的觸發條件(DONE 超過 N 天、檔案超過 N KB)?
3. **Concurrent AI agent**：多個 headless Claude 同時觸發時如何避免搶同一 task?用 DOING 狀態 + timestamp 當 lock 夠嗎?
4. **Viewer 寫回衝突**：使用者在 viewer 編輯時 AI 也在改,last-write-wins 還是 CRDT?初期先 last-write-wins + file watcher reload。
5. **Schema 擴充機制**：使用者想加自己的欄位（除了 `custom`）怎麼辦?要不要支援 project-local schema extension?
6. **Multi-repo 情境**：Kirin 可能想跨多個 project 聚合 kanban,是否需要 global kanban 概念?

---

## 12. References

- [Claude Code Plugins documentation](https://code.claude.com/docs/en/plugins)
- [Claude Code Headless mode](https://code.claude.com/docs/en/headless)
- [Claude Code Hooks reference](https://code.claude.com/docs/en/hooks)
- [JSON Schema draft-07](https://json-schema.org/draft-07)
- [Textual framework](https://textual.textualize.io/)
- Prior art: Obsidian Kanban plugin, GitHub Projects, Linear API

---

## Appendix A — 使用者體驗腳本

### A.1 第一次使用（全新 project）

```bash
$ cd my-new-project
$ claude
> /plugin marketplace add kirin/claude-kanban
> /plugin install kanban@claude-kanban
> /kanban:init --with-examples

# ...開始跟 Claude 協作...
> /kanban:next
Claude: 我挑了 task-001「設定專案骨架」,已移到 DOING,開始執行...
```

### A.2 啟用自動化

```bash
> /kanban:enable-automation

Claude: 請問要用哪種觸發方式?
  1. Cron polling(每 10 分鐘檢查,推薦)
  2. Git post-merge hook(git pull 後自動觸發)
  3. Webhook server(需要 remote server)

User: 1

Claude: 好的,我會安裝 cron job。這會用你的 Claude Pro 訂閱執行,不會燒 API。
[執行 install-cron.sh...]

已安裝。Crontab 內容:
  */10 * * * * /home/kirin/.claude-kanban/cron-runner.sh /home/kirin/my-new-project

想停用時執行:crontab -e 並刪除該行。
```

### A.3 日常使用

```bash
# 人類在 viewer 新增 task
$ kanban-tui
# [按 n 新增 "修復登入 bug", P1, 設 priority, save]

# 等待 cron 觸發(或立即手動觸發)
$ git push   # 其他地方開發時

# 回家後打開 viewer 看進度
$ kanban-tui
# 看到 task 已被 AI 移到 DONE,comment 裡有修復說明
```

---

*End of SPEC.md*
