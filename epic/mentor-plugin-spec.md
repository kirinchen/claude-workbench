# Plugin: `mentor` — SPEC

> 本文件為 `claude-workbench` 家族的 `mentor` plugin 設計,取代原先的 `docsync`。
> 格式與主 SPEC.md 中 §3 (kanban) / §4 (notify) / §5 (memory) 章節對齊,
> 可直接合併為主 SPEC.md 新增章節。
>
> 合併指引於文件最末。

---

## Plugin: `mentor`

### Role

**Mentor plugin 扮演「新進員工 onboarding Mentor」的角色**——它規範 agent 在某個 project 應該:

1. **讀哪些文件**(bootstrap docs)
2. **怎麼填資料**(doc templates 與 frontmatter 規範)
3. **工作順序**(task pickup workflow、更新時機、產出標準)
4. **在哪裡記錄**(Epic / Sprint / Issue / Wiki 的分層邏輯)

這不只是 doc sync 工具,而是一個 **project 工作紀律的規範者**。裝了 mentor 的 project,等於告訴 agent:「這是我們公司的做事方法,跟著做。」

### Why Replace `docsync`

實作 docsync 後發現的痛點:

1. **規則每個 project 都要重寫**——同類型 project 應該共用 framework
2. **只管 code ↔ doc mapping 太窄**——沒涵蓋「怎麼開始一個 task」「怎麼結束一個 task」的工作流
3. **沒有「文件層級」概念**——把 SPEC 跟 Wiki 跟 Issue 當成同一層,實際上它們角色不同

`mentor` 把這些痛點解決:提供 framework 選擇、管理多層文件、定義工作順序。

### Design Philosophy

1. **Framework-first**:使用者選 framework(basic / development),framework 決定 project 該有什麼、agent 該做什麼
2. **Template-driven**:每種文件有標準 template,agent 不用自由發揮
3. **Graceful with kanban**:裝了 kanban 用 `kanban.json`,沒裝回退 `doc/task.md`
4. **Progressive complexity**:basic 模式輕量即用,development 模式有完整階層

### Framework Modes

Mentor 提供兩種 framework,使用者 `/mentor:init` 時選擇:

#### Mode 1: `basic` — 基本模式

**適合**:個人專案、原型、工具型 repo、維護期專案、單人 session

**檔案結構**:

```
<project>/
├── doc/
│   └── SPEC.md                      ← 單一真相來源
├── kanban.json                      ← (若裝 kanban plugin)
└── doc/task.md                      ← (若未裝 kanban plugin,fallback)
```

**Agent 行為規範**:

- Session 開始必讀:`doc/SPEC.md`
- 挑 task:從 kanban.json 的 TODO 列 / 或 task.md 最上方未完成項
- 執行 task:若影響 SPEC 須同步更新
- 結束 task:更新 kanban/task.md state

#### Mode 2: `development` — 開發模式

**適合**:多 feature 並行、有規劃 cycle、多 agent 協作、中大型專案

**檔案結構**:

```
<project>/
├── doc/
│   ├── SPEC.md                      ← 系統規格(穩定、緩慢變動)
│   ├── Wiki/                        ← 背景知識、決策紀錄、教學
│   │   ├── README.md                ← 索引
│   │   ├── architecture-decisions/
│   │   │   └── ADR-001-xxx.md
│   │   └── guides/
│   │       └── setup.md
│   ├── Epic/                        ← 大方向目標群
│   │   ├── README.md                ← 索引
│   │   ├── EPIC-001-user-auth.md
│   │   └── EPIC-002-payment.md
│   ├── Sprint/                      ← 時間窗口
│   │   ├── README.md                ← 索引 + 當前 sprint 指標
│   │   ├── SPRINT-2026-W17.md
│   │   └── SPRINT-2026-W18.md
│   └── Issue/                       ← 具體問題/bug/需求
│       ├── README.md                ← 索引
│       ├── ISSUE-042-rate-limit.md
│       └── ISSUE-043-memory-leak.md
├── kanban.json
└── doc/task.md                      ← (若未裝 kanban plugin,fallback)
```

**關係模型**:

```
Epic ──┬─ 包含多個 Issue
       └─ 跨多個 Sprint

Sprint ─── 時間窗口,包含本 Sprint 該完成的 Issue

Issue ──┬─ 屬於一個 Epic
        ├─ 屬於一個 Sprint(或 backlog)
        └─ 被拆成多個 Task

Task ──── 執行單位,可交給 agent(kanban.json 中的一筆)
```

**Agent 行為規範**:

- Session 開始必讀:`doc/SPEC.md` + 當前 Sprint 文件(`Sprint/` 中 status=active)
- 挑 task 前必須先:
  1. 看 task 屬於哪個 Issue(task metadata)
  2. 看 Issue 屬於哪個 Epic
  3. 確認方向符合 Epic Success Criteria
- 執行 task 中若遇到不確定,先查 `doc/Wiki/`
- 完成 task 後:
  - 更新 task state(kanban.json / task.md)
  - 若本 issue 所有 task 完成,更新 Issue status
  - 若 Sprint 結束,觸發 retrospective draft 寫入 Sprint 文件
  - 若引入新決策,寫 ADR 到 `Wiki/architecture-decisions/`

### Data Model

#### `.claude/mentor.yaml`

```yaml
schema_version: 1

# 選擇 framework mode
mode: development                   # basic | development

# 文件路徑(可覆寫)
paths:
  spec: doc/SPEC.md
  wiki: doc/Wiki/
  epic: doc/Epic/
  sprint: doc/Sprint/
  issue: doc/Issue/
  task_fallback: doc/task.md        # 沒裝 kanban plugin 時用

# ID 生成規則
id_patterns:
  epic: "EPIC-{seq:03d}"             # EPIC-001, EPIC-002
  sprint: "SPRINT-{year}-W{week:02d}" # SPRINT-2026-W17
  issue: "ISSUE-{seq:03d}"
  task: "task-{seq:03d}"

# Agent 行為規範
agent_behavior:
  bootstrap_docs:                   # Session 開始必讀
    - doc/SPEC.md
    - doc/Sprint/active.md          # 自動連結到當前 active sprint
  require_issue_context: true       # 挑 task 前必須先讀對應 issue
  auto_retrospective: true          # sprint 結束自動草擬 retro
  require_adr_on_decision: true     # 重大決策需寫 ADR

# Template 來源(可自訂或用預設)
templates:
  source: builtin                   # builtin | custom
  custom_path: .claude/mentor-templates/  # 若 source=custom

# 與其他 plugin 的整合
integration:
  kanban:
    enabled: auto                   # auto | force | disable
    sync_issue_to_task: true        # issue 有新 task 時自動建 kanban entry
    block_done_if_issue_incomplete: false
  memory:
    enabled: auto
    save_sprint_retro: true         # retro 存入 memory
    save_adr: true
  notify:
    enabled: auto
    notify_sprint_end: true
    notify_epic_done: true
```

#### Epic Template

```markdown
---
id: EPIC-001
title: User authentication system
status: active                      # planning | active | done | cancelled
owner: kirin
created: 2026-04-20
target_sprint: 2026-W18
issues: [ISSUE-042, ISSUE-043]
---

## Why (為什麼要做)

## Success Criteria (何謂完成)
- [ ] Criterion 1
- [ ] Criterion 2

## Out of Scope (明確不做的)

## Related Wiki
- [Architecture Decision](../Wiki/architecture-decisions/ADR-001.md)
```

#### Sprint Template

```markdown
---
id: SPRINT-2026-W17
start: 2026-04-21
end: 2026-04-27
goal: "完成 login 主流程"
issues: [ISSUE-042, ISSUE-044]
status: active                      # planning | active | review | done
---

## Sprint Goal

## Committed Issues
- [ISSUE-042] Rate limit handling
- [ISSUE-044] Session token refresh

## Daily Notes
(agent 每天進來更新)

### 2026-04-21
...

## Retrospective
(sprint 結束時由 agent 草擬)

### What went well
### What could be improved
### Action items
```

#### Issue Template

```markdown
---
id: ISSUE-042
title: Rate limit handling in auth service
epic: EPIC-001
sprint: 2026-W17
status: open                        # open | in_progress | resolved | closed
priority: P1
tasks: [task-042, task-045]
---

## Problem

## Acceptance Criteria
- [ ] Condition 1
- [ ] Condition 2

## Investigation / Notes

## Resolution
(完成時填)
```

#### Wiki ADR Template

```markdown
---
id: ADR-001
title: Use token bucket for rate limiting
status: accepted                    # proposed | accepted | deprecated | superseded
date: 2026-04-22
deciders: [kirin]
related_issues: [ISSUE-042]
---

## Context

## Decision

## Consequences

## Alternatives Considered
```

### Directory Structure

```
plugins/mentor/
├── .claude-plugin/plugin.json
├── skills/
│   └── mentor-workflow/
│       ├── SKILL.md                # 教 agent 如何遵守 framework 規範
│       └── references/
│           ├── basic-mode-guide.md
│           ├── development-mode-guide.md
│           ├── writing-epic.md
│           ├── writing-sprint.md
│           ├── writing-issue.md
│           ├── writing-adr.md
│           └── task-pickup-workflow.md
├── commands/
│   ├── init.md                     # /mentor:init (互動式 framework 選擇)
│   ├── status.md                   # /mentor:status (顯示目前 framework + sprint)
│   ├── new.md                      # /mentor:new <epic|sprint|issue|adr>
│   ├── sprint-start.md             # /mentor:sprint-start
│   ├── sprint-end.md               # /mentor:sprint-end (觸發 retro)
│   ├── review.md                   # /mentor:review (檢查 framework 合規性)
│   └── migrate-from-docsync.md     # 舊 docsync 使用者遷移
├── hooks/
│   └── hooks.json
├── scripts/
│   ├── mentor-bootstrap.py         # SessionStart: 注入 bootstrap docs
│   ├── mentor-guard.py             # PreToolUse: 檢查文件編輯是否符合 template
│   ├── mentor-checkpoint.py        # PostToolUse: task 完成後更新層級文件
│   ├── mentor-finalcheck.py        # Stop: session 結束總結
│   ├── framework-engine.py         # 共用 framework 判斷邏輯
│   └── workbench-mentor            # Public CLI
├── frameworks/                     # 內建 framework 定義
│   ├── basic/
│   │   ├── framework.yaml
│   │   └── templates/
│   │       └── SPEC.md
│   └── development/
│       ├── framework.yaml
│       └── templates/
│           ├── SPEC.md
│           ├── Wiki/README.md
│           ├── Wiki/architecture-decisions/ADR-template.md
│           ├── Epic/README.md
│           ├── Epic/epic-template.md
│           ├── Sprint/README.md
│           ├── Sprint/sprint-template.md
│           ├── Issue/README.md
│           └── Issue/issue-template.md
└── templates/
    └── mentor.example.yaml
```

### Slash Commands

| Command | 參數 | 用途 |
|---|---|---|
| `/mentor:init` | `[--mode=basic\|development]` | 互動式 framework 選擇 + 初始化 |
| `/mentor:status` | | 顯示當前 framework、active sprint、open issues |
| `/mentor:new` | `<type> [--title=...]` | 產生新 Epic/Sprint/Issue/ADR |
| `/mentor:sprint-start` | `[--goal=...]` | 開啟新 sprint |
| `/mentor:sprint-end` | | 結束 sprint + 生成 retrospective 草稿 |
| `/mentor:review` | | 檢查專案是否符合 framework(找出缺失的 doc、不符合 template 的檔案) |
| `/mentor:migrate-from-docsync` | | 從 `.claude/docsync.yaml` 遷移到 `.claude/mentor.yaml` |

### Interactive Init Flow

`/mentor:init` 的完整互動腳本。

#### Phase 1 — Scan(靜默)

1. 偵測 project 類型(Rust/JS/Python/Go/multi)
2. 掃描既有結構:
   - 是否已有 `doc/` 目錄
   - 是否已有 `SPEC.md`
   - 是否有 `Wiki/`、`Epic/`、`Sprint/`、`Issue/`
   - 是否裝了 kanban plugin(偵測 `workbench-kanban` 或 `kanban.json`)
   - 是否有舊 `.claude/docsync.yaml`
3. 推測合適 mode:
   - 單人專案、只有 SPEC.md → 推薦 basic
   - 已有多層 doc 結構、或裝了 kanban → 推薦 development

#### Phase 2 — Mode Selection

用 AskUserQuestion single-select:

```
"Welcome. I'll help set up mentor for this project.
 
 Based on scan: {project_type}, {has_existing_docs}, {has_kanban}.
 
 Which framework fits your workflow?"

Options:
  1. basic        — SPEC.md + tasks. 適合個人/原型/維護期。
                    Detected match: {yes/no}
  2. development  — SPEC + Wiki + Epic + Sprint + Issue + tasks.
                    適合多 feature 並行、planning cycle、團隊協作。
                    Detected match: {yes/no}
  3. Migrate from existing docsync config
                    (只有偵測到舊 config 時出現)
```

#### Phase 3 — Structure Review

顯示將建立/保留的檔案結構:

```
Will create:
  + doc/SPEC.md                 (template)
  + doc/Sprint/README.md
  + doc/Sprint/SPRINT-2026-W17.md (current sprint)
  + doc/Epic/README.md
  + doc/Issue/README.md
  + doc/Wiki/README.md
  + .claude/mentor.yaml

Will keep (already exists):
  = doc/SPEC.md
  = doc/Wiki/ (will add README if missing)

Skipped:
  - kanban.json (managed by kanban plugin)
```

使用者確認前可修改路徑(`paths:` 區塊)。

#### Phase 4 — Integration Setup

偵測 sibling plugins,針對每個已裝的 plugin 問整合選項:

```
Detected plugins:
  ✓ kanban    — Sync issues to kanban tasks? [Y/n]
  ✓ memory    — Save sprint retros to memory? [Y/n]
  ✓ notify    — Notify on sprint end / epic done? [Y/n]
```

#### Phase 5 — First Sprint (僅 development mode)

```
Create your first sprint?
  Sprint ID: SPRINT-2026-W17 (auto from ISO week)
  Goal: [user input]
  Duration: 7 days (ends 2026-04-27)

[Y/n]
```

#### Phase 6 — Write & Next Steps

1. 寫入所有檔案
2. 寫 `.claude/mentor.yaml`
3. 詢問是否 commit 到 git
4. 顯示 next steps:
   - `/mentor:status` 隨時檢視專案狀態
   - `/mentor:new epic` 建立第一個 Epic
   - `/kanban:next` 開始挑 task(若裝了 kanban)

### Hooks

```json
{
  "SessionStart": [
    {
      "hooks": [{
        "type": "command",
        "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/mentor-bootstrap.py"
      }]
    }
  ],
  "PreToolUse": [
    {
      "matcher": "Edit|Write|MultiEdit",
      "hooks": [{
        "type": "command",
        "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/mentor-guard.py"
      }]
    }
  ],
  "PostToolUse": [
    {
      "matcher": "Edit|Write|MultiEdit",
      "hooks": [{
        "type": "command",
        "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/mentor-checkpoint.py"
      }]
    }
  ],
  "Stop": [
    {
      "hooks": [{
        "type": "command",
        "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/mentor-finalcheck.py"
      }]
    }
  ]
}
```

#### Hook 行為

**`mentor-bootstrap.py`** (SessionStart):
- 讀 `.claude/mentor.yaml`
- 注入 `systemMessage` 規範 agent 行為
  - basic mode: 「讀 SPEC.md 後再動手」
  - development mode: 「讀 SPEC.md + 當前 active sprint 後再挑 task;挑 task 前讀對應 issue」
- 列出當前 active sprint 指標、未完成 issue 數

**`mentor-guard.py`** (PreToolUse):
- 若編輯 `Epic/*.md`、`Sprint/*.md`、`Issue/*.md`、`Wiki/**/*.md`
- 檢查該檔案是否有 mentor frontmatter
- 若無或格式錯誤,`systemMessage` 提醒 agent 遵守 template
- 不阻擋,僅 warn

**`mentor-checkpoint.py`** (PostToolUse):
- 偵測檔案類型判斷是否為層級更新事件
- 當 Issue 的所有 task 都 DONE:提醒更新 Issue status
- 當 Sprint 到期日:提醒跑 `/mentor:sprint-end`
- 若 code 改動可能影響 SPEC:提醒更新 SPEC

**`mentor-finalcheck.py`** (Stop):
- 彙整本 session 的文件更動
- 檢查合規性:有沒有違反 template 的檔案、有沒有 orphan issue(無 epic)、有沒有 task 未關聯 issue
- 列出 pending actions

### Skill

`skills/mentor-workflow/SKILL.md` 觸發條件:

> Use this skill whenever `.claude/mentor.yaml` exists in the project, or when
> the user mentions epic, sprint, issue, retrospective, ADR, or asks about
> project workflow / conventions / onboarding.

Skill 正文涵蓋:

1. Basic / development mode 的行為差異
2. 讀 bootstrap docs 的順序與時機
3. 挑 task 前的 context gathering 流程
4. 各層文件的寫作風格(呼應 references/*)
5. 何時該建新 Epic / Issue(判斷標準)
6. 絕對規則:
   - 不自行修改 `.claude/mentor.yaml`
   - 不繞過 template 結構
   - 不把不同層級的資訊混寫(Epic 寫 why、Issue 寫 what、Task 寫 how)

### Public CLI

`workbench-mentor` 作為整合用入口:

```bash
# 查詢當前 active sprint
workbench-mentor active-sprint --format json

# 查詢 task 屬於哪個 issue/epic
workbench-mentor trace task-042 --format json

# 驗證 project 合規性
workbench-mentor review --format json
# Exit code: 0=OK, 2=violations found

# 產生新檔案(給其他 plugin 呼叫用)
workbench-mentor new issue --title "..." --epic EPIC-001

# 取得 framework config
workbench-mentor config --format json
```

### Cross-Plugin Integration

#### mentor × kanban

**Issue → Task 同步**(development mode):

當 `integration.kanban.sync_issue_to_task: true`:

- 新建 Issue 時,`/mentor:new issue` 自動在 kanban.json 新增關聯 task
- Task 的 `description` 欄位自動帶入 Issue 連結
- Task 的 `tags` 自動帶入 issue id

**Fallback 邏輯**:

- 若裝了 kanban plugin → `kanban.json` 是 task 真相來源,`doc/task.md` 不產生
- 若未裝 kanban → 產生 `doc/task.md`,mentor 自己維護簡單 task 清單
- 兩者都不會並存

**Task Done 閘門**(可選):

當 `integration.kanban.block_done_if_issue_incomplete: true`:
- Task 要 DONE 時,kanban 呼叫 `workbench-mentor check --task <id>`
- 若對應 Issue 的 Acceptance Criteria 未全部打勾,阻擋並提示

#### mentor × memory

**Sprint Retrospective 存 memory**:

`/mentor:sprint-end` 產生 retro 後:
```bash
workbench-memory save \
  --topic "Sprint SPRINT-2026-W17 retrospective" \
  --content "<retro content>" \
  --tags "sprint,retro,mentor" \
  --source "mentor:sprint:2026-W17"
```

**ADR 存 memory**:

建立 ADR 時:
```bash
workbench-memory save \
  --topic "ADR-001: <title>" \
  --content "<decision + consequences>" \
  --tags "adr,decision,mentor" \
  --source "mentor:adr:001"
```

**新 Epic 啟動時查 memory**:

`/mentor:new epic` 時:
```bash
related=$(workbench-memory search --query "<epic title>" --limit 3)
# agent 把結果作為 Epic 的 "Related Context" 區段草稿
```

#### mentor × notify

**Sprint 結束通知**:

當 `integration.notify.notify_sprint_end: true`,sprint 到期:
```bash
workbench-notify --priority normal \
  --title "Sprint Ending" \
  --message "SPRINT-2026-W17 ends today. Run /mentor:sprint-end."
```

**Epic 完成通知**:

當 Epic 所有 Issue resolved,status 改為 done:
```bash
workbench-notify --priority normal \
  --title "Epic Complete" \
  --message "EPIC-001: User authentication — all issues resolved"
```

### Migration from docsync

提供 `/mentor:migrate-from-docsync` command:

1. 讀 `.claude/docsync.yaml`
2. 分析既有 rules:
   - 若只有 `doc/SPEC.md` + `doc/CODE_MAP.md` → 推薦 basic
   - 若有多層結構 → 推薦 development + 詢問映射
3. 產生 `.claude/mentor.yaml`
4. 保留 `.claude/docsync.yaml.bak`
5. 提示使用者檢查、可隨時 rollback

### Capability Detection

其他 plugin 偵測 mentor:

```bash
has_plugin() { command -v "workbench-$1" &>/dev/null; }
HAS_MENTOR=$(has_plugin mentor && echo 1 || echo 0)
```

Mentor 本身偵測 sibling(kanban/memory/notify)決定 integration 行為。

### Security Considerations

- **`.claude/mentor.yaml` 不存 secrets** — 僅 path / pattern / 枚舉值
- **Template engine 不執行任意程式** — 純字串替換
- **Frontmatter 解析只接受安全 YAML subset** — 禁用 `!!python/object` 等 tag
- **Framework templates 讀 plugin 目錄內資源** — 不從網路拉取

### Profile Classification

`mentor` 屬於 **dev profile**(跟原 docsync 相同),不列入預設 `workbench` meta-plugin:

```json
// plugins/workbench-dev/.claude-plugin/plugin.json
{
  "name": "workbench-dev",
  "version": "0.1.0",
  "description": "Claude Workbench for developers",
  "dependencies": [
    { "name": "workbench", "version": "^0.1.0" },
    { "name": "mentor", "version": "^0.1.0" }
  ]
}
```

### MVP Scope (v0.1.0)

必要:

- [ ] Mode schema 定義(basic + development)
- [ ] `/mentor:init` 互動式 flow
- [ ] Basic mode 完整實作
- [ ] Development mode 完整實作(含所有 4 種文件 template)
- [ ] SessionStart hook — bootstrap injection
- [ ] PreToolUse hook — template guard
- [ ] `/mentor:status`
- [ ] `/mentor:new <type>`
- [ ] `/mentor:sprint-start` + `/mentor:sprint-end`
- [ ] `/mentor:review` 合規性檢查
- [ ] `/mentor:migrate-from-docsync`
- [ ] kanban fallback 邏輯(有/無 kanban plugin 行為切換)
- [ ] Skill + references for all document types
- [ ] `workbench-mentor` CLI

次要(v0.2+):

- [ ] Custom framework 支援(使用者自訂 mode)
- [ ] Frontmatter schema 嚴格驗證
- [ ] Sprint 自動切換(到日期自動 end 舊 sprint、start 新 sprint)
- [ ] Epic/Issue/Sprint 視覺化輸出(mermaid)
- [ ] Team mode 支援(多使用者分工、ownership)

### Open Questions

1. **Sprint 命名衝突** — ISO week 編號在跨年時怎麼處理(2026-W52 vs 2027-W01)?
2. **Issue 跨 Sprint** — Issue 做到一半換 sprint 時的 state 遷移?
3. **Epic 無限期** — 沒設 target_sprint 的 Epic 算 active 還是 planning?
4. **多層 retrospective** — Sprint retro 跟 Epic retro 該不該都做?
5. **Wiki vs ADR 界線** — 什麼該寫 Wiki、什麼該寫 ADR?Skill 怎麼教 agent 判斷?
6. **Basic → Development 升級路徑** — 已用 basic 一段時間後想升 development,如何無痛?
7. **Template customization granularity** — 使用者想改 Epic template 但保留其他 default,怎麼設計?
8. **與 GitHub Issues / Linear 的關係** — 未來要不要雙向同步,還是刻意保持 local-first?

### References

- 原 `docsync` plugin SPEC(已由 mentor 取代)
- Claude Code hooks reference
- AskUserQuestion tool documentation
- ISO 8601 week date format(sprint naming)

---

## 合併指引(給 Claude Code)

把本文件合併進主 `SPEC.md` 時請執行:

### 刪除或廢棄

1. **標記原 `docsync` 章節為 deprecated**,不直接刪除,加 note:
   > ⚠️ Deprecated in v0.2. Replaced by `mentor` plugin. See Migration section.
2. 或直接用 `mentor` 章節取代原 docsync 章節位置

### 新增主章節

1. 作為 `§6 Plugin 4: mentor`(或原 docsync 位置),章節號順延
2. 內容從本文件「Plugin: `mentor`」小節開始複製

### 更新既有章節

3. **`§1.1 What` 的架構圖**:把原本的 `docsync` 節點改成 `mentor`
4. **`§2.2 Plugin 互相作用表`**:mentor 的互動欄取代 docsync 的欄位;更新所有 integration 描述
5. **`§2.3 Plugin 職責邊界表`**:
   - 只做:framework 規範、文件階層管理、template 驅動的 doc 產出、onboarding 指引
   - 絕不做:實際的 code-doc 雙向同步(mentor 只規範 agent 行為,不 enforce file diff)、task state 管理(屬 kanban)
6. **`§6 Cross-Plugin Integration`**:
   - 新增 mentor × kanban、mentor × memory、mentor × notify 小節
   - 移除原 docsync 相關小節
7. **`§7 Meta-plugin`**:`workbench-dev` 的 dependencies 把 `docsync` 改為 `mentor`
8. **`§8 Repository Structure`**:
   - `plugins/mentor/` 取代 `plugins/docsync/`
   - `schema/` 加 `mentor.schema.yaml`
   - marketplace.json entry 更名
9. **`§11 MVP Roadmap`**:原 docsync 的 Phase 調整為 mentor 的 Phase,新增 migration 工作項

### 新增遷移章節

10. 主 SPEC.md 末尾加 **"Appendix C — docsync → mentor Migration"**,內容為本文件 "Migration from docsync" 小節

### Appendix B 互動矩陣

11. 表格中 `docsync` 欄位全部改 `mentor`,更新 cell 內容對齊新設計

### 不需要動

- `§9 Versioning`
- `§10 Security`(general principles 已涵蓋)
- 其他 atomic plugin 章節

---

*End of mentor plugin SPEC*
