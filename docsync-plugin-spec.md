# Plugin: `docsync` — SPEC

> 本文件為 `claude-workbench` 家族新增的 dev-profile plugin 設計。格式與 SPEC.md 中
> §3 (kanban) / §4 (notify) / §5 (memory) 章節對齊,可直接合併為 SPEC.md 新增章節。
> 合併時請更新: marketplace.json 加入新 entry、§2.2 整合表、§6 cross-plugin integration、
> §11 MVP Roadmap、Appendix B 互動矩陣。

---

## Plugin: `docsync`

### Role

確保**程式碼變動**與**文件內容**保持同步的開發者 plugin。適用於需要維護架構文件、API 文件、模組 README 等「活文件」的程式專案。屬於 **dev profile**,非核心 workbench 必備。

典型解決的痛點:Claude 幫忙改了 code 卻忘記更新對應的 ARCHITECTURE.md / CODE_MAP.md / README.md,導致文件逐漸失去真實性。

### Design Philosophy

docsync 貫徹「**Config-driven, not prompt-driven**」原則:

- Plugin 本身只提供**通用引擎**(rule engine + hooks + commands)
- 每個 project 的 code → doc mapping 存放在 project-local 的 `.claude/docsync.yaml`
- 使用者**永遠不必手寫 yaml** — 透過 `/docsync:init` 的互動式訪談由 Claude 產生

此設計將現有常見的「把 mapping rules 硬寫在 CLAUDE.md」做法結構化、可攜化、可驗證。

### Interactive Onboarding Philosophy

docsync 示範 workbench 家族的 `init` command 共通 UX 模式 — **掃描 → 推測 → 訪談 → 驗證**。

好的 AI onboarding 應像「老練的顧問進辦公室」:先看一圈,再只問真正需要 input 的問題。完整流程見下方 `/docsync:init` Interactive Init Flow 小節。

### Data Model

#### `.claude/docsync.yaml` Schema

```yaml
schema_version: 1

# Session 開始時,plugin 會提醒 Claude 閱讀這些文件
bootstrap_docs:
  - doc/ARCHITECTURE.md
  - doc/CODE_MAP.md
  - doc/DIRECTORY_TREE.md
  - doc/SPEC.md

# Code 變動 → Doc 更新對應規則
rules:
  - id: common-code-map                  # 規則 ID(人類可讀)
    pattern: "common/**"                 # glob pattern
    docs:
      - path: doc/CODE_MAP.md
        section: common                  # 可選:指定文件內的 section
        required: true                   # 必更(預設 true)
      - path: doc/ARCHITECTURE.md
        required_if: architecture_changed

  - id: exchange-client
    pattern: "exchange_client/**"
    docs:
      - path: doc/CODE_MAP.md
        section: exchange_client

  - id: position-manager
    pattern: "position-manager/**"
    docs:
      - path: doc/CODE_MAP.md
        section: position-manager
      - path: position-manager/dynamic_param.md
        required_if: params_changed

# 允許 Claude 跳過 doc 更新的情境
# (語義判斷由 skill 引導 Claude 做,非程式判斷)
skip_conditions:
  - bug_fix_only              # 純 bug 修正,無 API change
  - internal_refactor         # 僅改 private 函式
  - test_only                 # 只動 tests
  - comment_formatting_only   # 僅註解或格式

# 強制程度
enforcement: warn             # warn | block | silent

# 可選:和其他 plugin 的整合開關
integration:
  kanban:
    block_done_if_pending: false    # 若 true,task DONE 需 doc 已 sync
  memory:
    summarize_doc_changes: true     # 存入 memory
```

#### Schema 欄位說明

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `schema_version` | int | ✓ | 目前為 1 |
| `bootstrap_docs` | string[] | | Session 開始強烈建議 Claude 讀的文件清單 |
| `rules[].id` | string | ✓ | 規則識別碼,用於 log/error message |
| `rules[].pattern` | glob | ✓ | 檔案路徑 glob,如 `common/**`、`src/api/*.rs` |
| `rules[].docs[].path` | string | ✓ | 要更新的文件路徑 |
| `rules[].docs[].section` | string | | 文件內特定 section(用於 large doc) |
| `rules[].docs[].required` | bool | | 預設 true |
| `rules[].docs[].required_if` | enum | | 條件式必更,見下表 |
| `skip_conditions` | enum[] | | 允許跳過的情境 |
| `enforcement` | enum | | `warn` / `block` / `silent`,預設 `warn` |
| `integration` | object | | 與其他 plugin 的互動設定 |

#### `required_if` 條件列舉

| 值 | 語義 |
|---|---|
| `architecture_changed` | 跨模組依賴、公開介面、資料流有變 |
| `api_changed` | 公開函式簽章、route、protocol 變更 |
| `params_changed` | 可調參數、config schema 變更 |
| `schema_changed` | DB schema、data model 變更 |

這些條件**不靠程式判斷**,由 skill 引導 Claude 做語義判斷後填 hook metadata。

#### Enforcement 語義

| 值 | 效果 |
|---|---|
| `silent` | 僅 `/docsync:check` 手動查詢時顯示 |
| `warn`(預設) | Code 改動後,PostToolUse hook 在 context 提醒 Claude |
| `block` | Kanban 整合啟用時,DONE 前必須完成 doc sync |

### Directory Structure

```
plugins/docsync/
├── .claude-plugin/plugin.json
├── skills/
│   └── docsync-workflow/
│       ├── SKILL.md                    # 教 Claude 如何判斷 skip conditions
│       └── references/
│           ├── update-patterns.md      # 各類 doc 的更新範本
│           └── skip-decision-tree.md   # skip_conditions 的判斷指南
├── commands/
│   ├── init.md                         # /docsync:init(互動式設定)
│   ├── check.md                        # /docsync:check(手動掃描)
│   ├── rules.md                        # /docsync:rules(顯示/測試)
│   ├── bootstrap.md                    # /docsync:bootstrap(列 session 起始讀過什麼)
│   └── validate.md                     # /docsync:validate(驗證 yaml)
├── hooks/
│   └── hooks.json
├── scripts/
│   ├── docsync-bootstrap.py            # SessionStart: 注入 bootstrap_docs
│   ├── docsync-guard.py                # PostToolUse: 偵測 code change
│   ├── docsync-finalcheck.py           # Stop: session 結束檢查
│   ├── rule-engine.py                  # 共用 rule matching 邏輯
│   └── workbench-docsync               # Public CLI
└── templates/
    ├── docsync.example.yaml            # Rust monorepo 範本
    ├── docsync.python.yaml             # Python 專案範本
    └── docsync.js.yaml                 # JS/TS monorepo 範本
```

### Slash Commands

| Command | 參數 | 用途 |
|---|---|---|
| `/docsync:init` | `[--from-existing-claude-md]` | 互動式產生 `.claude/docsync.yaml` |
| `/docsync:check` | `[<path>]` | 手動掃描 pending sync;可指定檔案 |
| `/docsync:rules` | `[<path>]` | 顯示當前規則;可測試某路徑會 match 哪些規則 |
| `/docsync:bootstrap` | | 列出本 session 起始時讀過的 bootstrap_docs |
| `/docsync:validate` | | 驗證 yaml schema 正確性 |

### Interactive Init Flow

`/docsync:init` 的完整互動腳本。本節是 docsync 作為「訪談式 onboarding」範本的核心。

#### Phase 1 — Scan(靜默)

Claude 自主執行,不問使用者:

1. **偵測 project 類型**:
   - `Cargo.toml` + `[workspace]` → Rust monorepo
   - `pnpm-workspace.yaml` / `lerna.json` → JS monorepo
   - `pyproject.toml` / `setup.py` → Python
   - `go.mod` → Go
   - 多個符合 → multi-lang monorepo

2. **識別 code 模組**:
   - 讀 root directory
   - 過濾:`.git`, `node_modules`, `target`, `dist`, `.venv`, `doc*`, `.cache`
   - 其餘目錄視為 candidate modules

3. **識別 documentation**:
   - 找 `doc/`, `docs/`, `documentation/` 下的 `*.md`
   - 找 root 的 `README`, `ARCHITECTURE`, `CODE_MAP`, `SPEC`, `DIRECTORY_TREE`, `CONTRIBUTING`
   - 找各 module 底下的 `README.md`

4. **若帶 `--from-existing-claude-md` flag**:
   - 讀 `CLAUDE.md`
   - 嘗試解析既有的 code → doc mapping table
   - 作為訪談的 "推測值" 帶入

#### Phase 2 — Inquiry(互動)

用 Claude Code 內建的 **`AskUserQuestion` tool** 做結構化多選,避免使用者打字(尤其手機場景)。問題分批,一次不問超過三題。

**Batch 1 — Bootstrap docs**

- 先 summary:「我找到 N 個 code 模組、M 個 doc 檔案」
- Multi-select:「以下哪些文件應該在每次 session 開始時被 Claude 讀取?」
- 選項:所有掃到的 top-level docs,每個附一行內容預覽

**Batch 2 — Module-to-doc mapping**

對每個 code 模組分別問(或用 matrix 一次問)。Single-select:
- 「當 `{module}/` 的 code 改動時,哪份 doc 應該更新?」
- 選項:
  - `doc/CODE_MAP.md` (全域 code map)
  - `{module}/README.md` (模組內 readme)
  - 兩者都要
  - 都不需要(純 infra 模組)
  - 其他(後續自行輸入)

**Batch 3 — Enforcement**

Single-select:
- 「docsync 該多嚴格?」
- 選項:
  - `warn`:提醒但不阻擋(推薦新手)
  - `block`:未同步 doc 不能 mark task DONE
  - `silent`:僅手動 `/docsync:check` 時顯示

**Batch 4 — Skip conditions**

Multi-select:
- 「哪些 code 改動可以不更新 doc?」
- 選項:
  - Bug fix only (無 API 變更)
  - Internal refactor (改 private 函式)
  - Test-only changes
  - Comment / formatting only

**Batch 5 — Integration**(僅當 sibling plugin 存在)

若偵測到 kanban 已安裝:
- Yes/No:「task mark DONE 前是否強制 doc 已 sync?」

若偵測到 memory 已安裝:
- Yes/No:「要把 doc 變更的摘要自動存進 memory 嗎?」

#### Phase 3 — Propose

Claude 彙整答案成完整 yaml,以 code block 顯示:

```yaml
# .claude/docsync.yaml(proposed)
schema_version: 1
bootstrap_docs: [...]
rules: [...]
enforcement: warn
skip_conditions: [...]
```

詢問:「這份設定看起來對嗎?」

- `yes` → 進 Phase 4
- `edit <section>` → 回到該 section 的 Batch 重問
- `cancel` → 不寫入任何檔案

#### Phase 4 — Dry-run Validate

在正式寫入之前,**用真實 commit 歷史做模擬**,證明規則合理:

1. `git log --oneline -n 20` 取最近 commit
2. 挑出 3 個代表性 commit(跨模組、文件型、純 code 型)
3. 對每個 commit 列出 changed files
4. 用剛才產生的規則做 dry-run:「若 docsync 當時已啟用,會提示更新哪些 doc?」
5. 展示結果:

```
若 docsync v1 當時已啟用:

commit abc123 - "refactor grid pricing"
├ 變更: position-manager/src/grid.rs
└ 會提示更新: doc/CODE_MAP.md (position-manager 區塊)
              position-manager/dynamic_param.md (因為改了 grid param)

commit def456 - "fix typo in comment"
├ 變更: common/src/types.rs
└ 會跳過(符合 skip_condition: comment_formatting_only)
```

**使用者看到這個 preview 會立刻知道規則對不對**,遠比讀 yaml 直觀。

#### Phase 5 — Write & Next Steps

使用者確認後:

1. 寫入 `.claude/docsync.yaml`
2. 詢問:「要 commit `.claude/docsync.yaml` 進 git 嗎?」(預設 yes,利於團隊共享)
3. 若 `.claude/` 未在 `.gitignore` 保護其他檔案,提醒使用者檢查
4. 顯示 next steps:
   - `/docsync:check` 手動掃描 pending syncs
   - `/docsync:rules <path>` 測試某路徑 match 哪些規則
   - 規則可直接編輯 `.claude/docsync.yaml`,或 `/docsync:init` 重跑

### Hooks

```json
{
  "SessionStart": [
    {
      "hooks": [{
        "type": "command",
        "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/docsync-bootstrap.py"
      }]
    }
  ],
  "PostToolUse": [
    {
      "matcher": "Edit|Write|MultiEdit",
      "hooks": [{
        "type": "command",
        "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/docsync-guard.py"
      }]
    }
  ],
  "Stop": [
    {
      "hooks": [{
        "type": "command",
        "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/docsync-finalcheck.py"
      }]
    }
  ]
}
```

#### Hook 行為

**`docsync-bootstrap.py`** (SessionStart):
- 讀 `.claude/docsync.yaml`
- 對每個 `bootstrap_docs` 檔案檢查存在性
- 產出 `systemMessage` 注入 Claude context:
  ```
  [docsync] Please read these before code work:
  - doc/ARCHITECTURE.md (exists)
  - doc/CODE_MAP.md (exists)
  - doc/DIRECTORY_TREE.md (missing — will be generated as needed)
  ```
- 不阻擋 session 啟動

**`docsync-guard.py`** (PostToolUse):
- 從 hook input 取得剛改的檔案路徑
- 用 `rule-engine.py` match 所有適用規則
- 查該次 session 內 doc 是否也已被改過
- 若有 pending,根據 `enforcement`:
  - `silent`:記錄但不輸出
  - `warn`:`systemMessage` 提醒 Claude
  - `block`:若 sibling kanban 正在 DOING task 且準備 DONE,exit 2 擋下

**`docsync-finalcheck.py`** (Stop):
- 彙整本 session 所有 code changes
- 對照 rules 算出應更新但未更新的 docs
- 若有 pending,在 session end 時顯示總結

### Skill

`skills/docsync-workflow/SKILL.md` 教 Claude:

1. **何時套用 skip_conditions** — 需語義判斷的情境,如「修一個 null check」算 bug_fix_only,但「改 error handling 流程」不算
2. **如何寫好 doc 更新** — `references/update-patterns.md` 提供 CODE_MAP / ARCHITECTURE / README 各自的寫作範本
3. **遇到規則衝突時的處理** — 例如一個 code change 同時 trigger 兩個規則,該怎麼 prioritize
4. **絕對規則** — 不可為了省事跳過 required doc;不可自行修改 `.claude/docsync.yaml`(使用者手動控制)

### Public CLI

`workbench-docsync` 作為其他 plugin 整合用的入口:

```bash
# 檢查某個 code 變動會觸發哪些 rules(給 kanban 整合用)
workbench-docsync match <file-path> --format json

# 檢查當前是否有 pending sync(給 kanban DONE 檢查用)
workbench-docsync check --since <git-ref> --format json
# Exit code: 0 = no pending, 2 = pending exists

# 匯出變更摘要(給 memory 整合用)
workbench-docsync summarize --session <session-id> --format json
```

### Cross-Plugin Integration

#### docsync × kanban

**Task DONE 閘門**(當 `integration.kanban.block_done_if_pending: true`):

`kanban-autocommit.sh` 在 `DOING->DONE` 之前:

```bash
if [[ $HAS_DOCSYNC -eq 1 ]]; then
    if ! workbench-docsync check --since "$(git merge-base HEAD main)" --format json | jq -e '.pending | length == 0' > /dev/null; then
        echo "Task cannot be marked DONE: docsync has pending syncs" >&2
        workbench-docsync check --since "$(git merge-base HEAD main)"
        exit 2
    fi
fi
```

**Task description 自動加到 bootstrap**:

若 task description 提到特定 doc 路徑,該 session 的 bootstrap_docs 臨時加入該 doc。

#### docsync × memory

**Doc 變更自動摘要**(當 `integration.memory.summarize_doc_changes: true`):

`docsync-finalcheck.py` 在 session 結束時:

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

**歷史查詢**:

下次 Claude 改類似 code 時,memory 可以 recall 「上次這類變動怎麼更新 doc 的」,提升 doc 品質一致性。

#### docsync × notify

docsync **不主動**呼叫 notify — doc sync 本身不是值得打擾使用者的事件。但當 `enforcement: block` 擋下 kanban DONE 時,由 kanban 的 notify 整合負責發通知。

### Capability Detection

其他 plugin 偵測 docsync:

```bash
has_plugin() { command -v "workbench-$1" &>/dev/null; }
HAS_DOCSYNC=$(has_plugin docsync && echo 1 || echo 0)
```

docsync 不需偵測 sibling plugin(整合行為由 `.claude/docsync.yaml` 的 `integration` 區塊開關)。

### Security Considerations

- **`.claude/docsync.yaml` 不存 secrets** — 僅 path / pattern / 枚舉值
- **Rule engine 不執行任意程式** — 只做 glob match 與靜態判斷
- **`workbench-docsync` CLI 所有 subcommand 為 read-only,不修改 yaml**
- **Skip conditions 是 advisory,不是 bypass** — 即使使用者選了所有 skip,rules 中明確 `required: true` 的 doc 仍會提醒

### Profile Classification

此 plugin 屬於 **dev profile**,不列入預設 `workbench` meta-plugin。未來擴充:

```json
// plugins/workbench-dev/.claude-plugin/plugin.json
{
  "name": "workbench-dev",
  "version": "0.1.0",
  "description": "Claude Workbench for developers — core + docsync + (future: review, lint)",
  "dependencies": [
    { "name": "workbench", "version": "^0.1.0" },
    { "name": "docsync", "version": "^0.1.0" }
  ]
}
```

`marketplace.json` 應新增兩個 entries:`docsync` 跟 `workbench-dev`。

### MVP Scope (v0.1.0)

必要:

- [ ] YAML schema definition + validator
- [ ] `/docsync:init` 互動式訪談完整流程(Phase 1-5)
- [ ] SessionStart hook — bootstrap docs injection
- [ ] PostToolUse hook — warn enforcement
- [ ] `/docsync:check` 手動掃描
- [ ] `/docsync:rules` 規則測試
- [ ] Rule engine(glob match, required_if, skip_conditions)
- [ ] 三份 yaml template(Rust / Python / JS)
- [ ] `workbench-docsync` CLI(match, check, summarize)
- [ ] Skill with skip-decision-tree reference

次要(v0.2+):

- [ ] `block` enforcement mode 實作
- [ ] kanban DONE 閘門整合
- [ ] memory 摘要整合
- [ ] `--from-existing-claude-md` 解析
- [ ] Doc section-level granularity(section-aware diff)
- [ ] Stop hook 的 session 總結

### Open Questions

1. **Section-level granularity** — 目前 `section` 欄位只記錄語義位置,rule engine 無法真的判斷「使用者是否更新了該 section」。需要實作時決定:用 H2/H3 heading marker 掃,還是採保守策略(doc 整體有改動即視為 synced)?

2. **語義判斷能力** — `required_if: api_changed` 需要 Claude 判斷某 code change 是否改了 public API。Skill 能做到什麼程度?要不要先只支援路徑 pattern,語義條件 v0.2 再做?

3. **Multi-language mixed repo** — 若 Rust + Python + shell script 混合,`docsync:init` 的 template 怎麼合成?目前設計是選主語言 template 後人工加 rule。

4. **Rename / move 處理** — 檔案 rename(`git mv`)應算 code change 嗎?若檔名本身出現在 doc 裡呢?

5. **與既有 CLAUDE.md 共存** — 若使用者既有 CLAUDE.md 裡已經寫了類似規則,docsync 啟用後是否提示使用者刪除 CLAUDE.md 的對應段落?還是並存?

6. **Performance** — 大型 monorepo 上 `docsync:check --since main` 可能掃幾百個檔案,要不要加 cache?

### References

- Claude Code AskUserQuestion tool documentation
- Claude Code hook events: SessionStart / PostToolUse / Stop
- Existing workbench SPEC: §6 Cross-Plugin Integration pattern
- PEP 621 / Cargo.toml workspace spec(for project type detection)

---

## 合併指引(給 Claude Code)

把本文件合併進 `SPEC.md` 時請執行以下異動:

1. **新增主章節**:作為 `§6 Plugin 4: docsync`(或插入於現有 plugin 章節之後),
   並把現有 §7 Meta-plugin 之後的章節號順延。

2. **更新 `§1.1 What` 的架構圖**:在三個 atomic plugin 之外加入 `docsync`,
   並註記為 dev profile。

3. **更新 `§2.2 Plugin 互相作用表`**:新增 docsync 的列與欄,參考本文件
   「Cross-Plugin Integration」章節。

4. **更新 `§2.3 Plugin 職責邊界表`**:新增 docsync 的職責描述
   - 只做:code ↔ doc 對應追蹤、規則引擎、互動式 config 產生
   - 絕不做:實際修改 doc 內容(由 Claude 執行)、阻擋非 DOING->DONE 的 code 修改

5. **更新 `§6 Cross-Plugin Integration`**:新增 §6.6 docsync × kanban、
   §6.7 docsync × memory。

6. **更新 `§7 Meta-plugin`**:新增 `workbench-dev` meta-plugin 描述。

7. **更新 `§8 Repository Structure`**:
   - `plugins/` 下加 `docsync/` 與 `workbench-dev/`
   - `marketplace.json` 新增兩個 entries(docsync、workbench-dev)
   - `schema/` 加 `docsync.schema.json`

8. **更新 `§11 MVP Roadmap`**:
   - 將 docsync 列為 **Phase 7**(v0.3.0 target),在 Phase 6 bundle 發布之後
   - 將 `workbench-dev` meta-plugin 列為 Phase 7 末尾

9. **更新 `Appendix B 互動矩陣`**:表格新增 docsync 列與欄。

10. **不需要動**:§9 Versioning、§10 Security(已涵蓋一般原則)、Appendix A
    安裝體驗(可選擇性加一段 `/plugin install docsync@claude-workbench`)。

---

*End of docsync plugin SPEC*
