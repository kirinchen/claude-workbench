# claude-workbench — 目前狀態

*[English](./current_state.md)*

**快照時間**：2026-04-21（更新——同日後續 session）
**工作目錄**：`/home/kirin/Desktop/project/claude-workbench`
**Git 分支**：`main`
**對應 spec**：[`SPEC.md`](./SPEC.md) v0.1.0 草稿
**Roadmap 階段**：**0b + Phase 2 + Phase 7 code-complete**，Phase 1 真實環境驗證尚未開始，Phase 3/5 跨 plugin 整合線路已接但未測。

這份檔案是即時實作快照。**當階段推出時保持與程式碼同步**——別讓它飄向「夢想版」。

> **注意**：這份是 live snapshot，變動快；en 和 zh-TW 版可能會短暫 drift。以英文版為準。

---

## 1. 狀態一覽

| Plugin / 元件 | Spec § | 狀態 | 說明 |
|---|---|---|---|
| `kanban` plugin | §3 | ✅ **v0.1.0 完成** | Phase 0a 骨架；Phase 0b 加上指令 + 自動化 |
| `notify` plugin | §4 | ✅ **v0.1.0 code-complete** | 僅 Pushover；dispatcher + CLI + setup/test/config 指令；見下方 §9 |
| `memory` plugin | §5 | 🟡 stub（只有 `plugin.json` + README） | Phase 4 |
| `docsync` plugin | §6 | ✅ **v0.1.0 code-complete** | Config-driven YAML、完整 init 流程、5 個指令、3 個 hook；見下方 §10 |
| Viewer（`kanban-tui`） | §7.1 | ⬜ 尚未開始 | v0.2.0 |
| Automation runners | §7.2 | 🟢 cron 路徑已備（runner + installer）；git-hook 路徑僅文件提到；webhook 未動 | Phase 3 將加真的 `workbench-notify` fan-out |
| `workbench` meta | §9.1 | 🟡 stub | 實際釋出在 Phase 6 |
| `workbench-dev` meta | §9.2 | 🟡 stub meta（依賴 `workbench` + `docsync`） | Phase 7 |
| `marketplace.json` | §10.1 | ✅ 6 個條目符合 SPEC | |
| Schema 同步 script | §10.2 | 🟢 手動 copy（kanban + docsync）已放 | 未來 CI 自動化 |
| Release / CI | §12 | ⬜ 尚未開始 | 沒有 `.github/workflows/` |
| Docs（`docs/`） | §10 | ⬜ 尚未開始 | README 涵蓋 install；沒有 quickstart / composition doc |

圖例：✅ 已完成 · 🟢 部分可用 · 🟡 stub · ⬜ 缺

---

## 2. Repo layout（實際、今天）

```
claude-workbench/
├── README.md                                ✅ 以 workbench 全家族定位
├── SPEC.md                                  ✅ 合併 workbench + docsync + 舊 viewer / automation
├── current_state.md                         ← 這份
│
├── .claude-plugin/
│   └── marketplace.json                         ✅ 6 個條目
│
├── plugins/
│   ├── kanban/                                  ✅ 見下方 §3
│   ├── notify/                                  ✅ 見下方 §9
│   ├── memory/.claude-plugin/plugin.json        🟡 stub + README
│   ├── docsync/                                 ✅ 見下方 §10
│   ├── workbench/.claude-plugin/plugin.json     🟡 stub meta + README
│   └── workbench-dev/.claude-plugin/plugin.json 🟡 stub meta + README
│
└── schema/
    ├── kanban.schema.json                       ✅ canonical，鏡射到 plugin templates
    └── docsync.schema.json                      ✅ canonical，鏡射到 plugins/docsync/templates/
```

尚未存在（spec 預期）：`viewer/`、`automation/`（canonical source；目前 cron 腳本在 `plugins/kanban/scripts/` 裡）、`docs/`、`scripts/`（CI helper）、`.github/workflows/`、`CHANGELOG.md`、`LICENSE`。

---

## 3. `plugins/kanban/` — 已完成 v0.1.0

### 3.1 內容

```
plugins/kanban/
├── .claude-plugin/plugin.json              ✅ name、version、description
├── skills/
│   └── kanban-workflow/
│       ├── SKILL.md                         ✅ 完整的 workflow 規則
│       └── references/
│           ├── schema-spec.md               ✅
│           ├── priority-rules.md            ✅
│           └── dependency-rules.md          ✅
├── commands/
│   ├── init.md                              ✅ /kanban:init
│   ├── next.md                              ✅ /kanban:next
│   ├── done.md                              ✅ /kanban:done
│   ├── block.md                             ✅ /kanban:block         (Phase 0b)
│   ├── status.md                            ✅ /kanban:status
│   └── enable-automation.md                 ✅ /kanban:enable-automation (Phase 0b)
├── hooks/hooks.json                         ✅ SessionStart、UserPromptSubmit、PreToolUse、PostToolUse
├── scripts/
│   ├── kanban-guard.sh                      ✅ 擋住對 kanban.json 的直接編輯
│   ├── kanban-autocommit.sh                 ✅ 獨立 commit + sibling fan-out stubs
│   ├── kanban-session-check.sh              ✅ DOING/BLOCKED 注入器（python 優先、jq 退而求其次）
│   ├── cron-runner.sh                       ✅ headless `claude -p` runner（Phase 0b）
│   └── install-cron.sh                      ✅ 可重複執行的 crontab installer（Phase 0b）
└── templates/
    ├── kanban.schema.json                   ✅ schema/kanban.schema.json 的 copy
    ├── kanban.empty.json                    ✅
    └── kanban.example.json                  ✅ 4 個範例任務分佈在 4 個 column
```

### 3.2 現在能做什麼

- `/kanban:init [--with-examples]` 把 template + schema copy 到新專案。
- `/kanban:status` 唯讀，穩定。
- `/kanban:next` 挑排名最高的 ready TODO 並移到 DOING。
- `/kanban:done [task-id] [--note=…]` 關掉 DOING 任務，並回報哪些下游任務被解除依賴。
- `/kanban:block <task-id> --reason=…` 要求 reason；DONE 上不給用。
- `/kanban:enable-automation` 走過 cron 或 git-hook 安裝。
- `kanban-guard.sh` 擋掉 `kanban.json` 的直接編輯。**已端到端測試**：Edit/Write → exit 2 帶轉向訊息；Bash → exit 0。
- `kanban-session-check.sh` 發出 `hookSpecificOutput.additionalContext`，包 DOING（full 模式也包 BLOCKED）。**已在 scratch fixture 上測過**。
- `kanban-autocommit.sh` 在只有 `kanban.json` dirty 時產生 `kanban: task-001 TODO→DOING` 類 commit。**已在 scratch repo 端到端測試**。
- `install-cron.sh` idempotent（對同一專案目錄拒絕重複安裝），把 runner 裝到 `~/.claude-workbench/bin/`，crontab 條目有 tag 方便移除。

### 3.3 已知限制 / 擱置事項

- 沒有 `/kanban:unblock` — BLOCKED 任務目前要手動改 YAML 才能回 TODO。Spec 有提；v0.2.0。
- `kanban-session-check.sh` 還**沒**做 `git fetch` + remote-drift 偵測（SPEC §3.6 列為未來工作）。現在只讀 local file。
- `cron-runner.sh` 用一個很陽春的 `"/kanban:next and execute …"` prompt。真要長期自主運作可能需要專用 `runner-prompt.md`。
- Autocommit 和 session-check 都依賴 `python3`；有 `jq` fallback 但**沒有**純 POSIX 退路。若沒 python 也沒 jq，整合 fan-out 會變 silent no-op（不是硬錯誤）。
- Schema 驗證只做結構性的——沒有在 runtime 檢查 `required_if` 這類語意欄位（那是 docsync 的事）。

### 3.4 埋在程式碼裡的解讀選擇

| 決定 | 位置 | 為什麼 |
|---|---|---|
| Autocommit matcher 除了 `Bash` 也包含 `Write|Edit|MultiEdit` | `hooks/hooks.json` | 這樣 `/kanban:init` 的 Write 也會自動 commit；SPEC §3.6 只寫 `Bash` 會讓 init-time commit 沒接好 |
| Autocommit 不 pass `--no-verify` | `kanban-autocommit.sh` | 尊重 user 的 pre-commit hook；失敗時靜默（跳過 commit），不強過 linter |
| 只做 standalone commit | `kanban-autocommit.sh` | 若其他檔案 dirty 就拒絕；避免把 kanban 狀態混在 code 變更裡 |
| Python3 優先、jq fallback | `kanban-session-check.sh`、`kanban-autocommit.sh` | Python 在現代 Linux/macOS 比 jq 常見；兩個 hook 都要夠穩 |

---

## 4. Capability-detection 接線（Phase 0a）

`kanban-session-check.sh` 和 `kanban-autocommit.sh` 開頭都是：

```bash
has_plugin() { command -v "workbench-$1" >/dev/null 2>&1; }
HAS_NOTIFY=0;  has_plugin notify  && HAS_NOTIFY=1
HAS_MEMORY=0;  has_plugin memory  && HAS_MEMORY=1
```

`kanban-autocommit.sh` 裡針對 `workbench-notify` 和 `workbench-memory` 的 dispatch block 都有，只是被 flag 保護，目前是 no-op（兩個 CLI 都還沒進 PATH）。Phase 2 / Phase 4 把 CLI 放進 `~/.claude-workbench/bin/` 之後，這些 block 會自動啟用，**不用改程式**。

**SPEC §8.7 強調的注意事項**：`command -v` 只偵測安裝、不偵測設定。計劃中的修法是 `workbench-<name> --health` 契約（ready 就 exit 0）——延到 Phase 2 notify 這個首批真實消費者登場時再落。

SPEC §3.7 提到 `HAS_DOCSYNC`，但還沒在任何已釋出 script 裡接線（Phase 7）。

---

## 5. 已驗證項目

| 驗證項 | 工具 | 結果 |
|---|---|---|
| 所有 JSON 檔 parse | `python3 -m json` per file | ✅ 10/10（`marketplace.json`、所有 `plugin.json`、hook、template、schema） |
| Shell script 語法 | `bash -n` | ✅ 五個都過 |
| Guard hook 擋 `kanban.json` | 手動 `echo JSON \| bash guard.sh` | ✅ Edit/Write targeting kanban.json 時 exit 2；其他 exit 0 |
| Session-check 發出 SessionStart JSON | scratch fixture `/tmp/kanban-test/` | ✅ full 模式 DOING+BLOCKED；`--lightweight` 只 DOING |
| Autocommit 產生可讀的 commit message | scratch repo `/tmp/kanban-ac-test/` | ✅ `kanban: task-001 TODO→DOING` |

**未驗證**：

- 用 `jsonschema` 做 schema conformance（這台機器沒 `pip`；延到 CI）。
- Claude Code 實際載入 plugin（需要 `claude` CLI）。
- `install-cron.sh` 端到端（會動 user 的 crontab——透過 slash command opt-in）。
- 任何整合 plugin fan-out 路徑（notify/memory 沒 binary 可讓 `HAS_*` 翻成 1）。

---

## 6. 相對於目前 SPEC.md 的 gap

這些是要關掉的追蹤項，讓 repo 符合合併後 SPEC 所描述的：

1. **缺少的頂層目錄**（依 §10）：`automation/`（canonical runner source——今天只存在於 kanban plugin 內）、`viewer/`、`docs/`、`scripts/`（CI）、`.github/workflows/`、`CHANGELOG.md`、`LICENSE`。
2. **沒有真的 `workbench-notify` / `workbench-memory` CLI** — 所以 capability detection 永遠短路。（**已在此次 session 解決 notify；docsync 同時落定**。）
3. **沒有 `--health` subcommand 契約** 給 sibling detection。（**已落**。）
4. **`kanban-session-check.sh` 缺 `git fetch`** 那步 spec 有承諾。
5. **Viewer 不存在** — spec 承諾的 Textual TUI 放在 `viewer/`。
6. **`docsync` 只有 stub** — 完整 plugin 在 Phase 7。（**此次 session 已完成**。）
7. **Memory 的 embedding model 安裝 UX** 未解（Open Question 11）。
8. **Schema / automation 同步 script（§10.2、§10.3）** 未寫 — 目前 schema copy 是手動的。
9. **Git remote 尚未設定** — local repo 無 remote；一旦 push，應落在 `github.com/kirin/claude-workbench`（**實際落在 `kirinchen/claude-workbench`**）。
10. **Local 目錄名稱仍是 `claude-kanban`** — 所有 upstream 引用（marketplace、schema `$id`、plugin homepage、`~/.claude-workbench/` CLI 目錄）都是 `claude-workbench`，只是磁碟上那個目錄沒改名。見下方 §6.9。

**此次 session 關掉的**：
- ✓ `marketplace.json` 現在有 6 個條目符合 SPEC §10.1。
- ✓ `plugins/docsync/` 和 `plugins/workbench-dev/` stub 建立（各自有 plugin.json + README）。
- ✓ 所有內部引用（schema `$id`、plugin homepage、marketplace name）都用 `claude-workbench`；只有 local filesystem 目錄還是舊名。

### 6.9 關於本次嘗試重新命名本機目錄

原計畫是在這 session `mv claude-kanban claude-workbench`。Claude Code harness 在 startup 時把 `CLAUDE_PROJECT_DIR` 綁到 session 原始的專案路徑，而且**只要 `.claude/` 消失就會在那個確切路徑重新 materialise**——所以 session 中途 `mv` 會產生 split-brain：內容搬走了，harness 卻還寫新的 settings 到舊名下，後續 `Bash` call 會「path does not exist」直到 harness 把目錄重建回來。

Merge 已還原（`rsync` + `rm -rf` 新名稱），這樣 session 能繼續跑。目錄改名是**跨 session** 操作：關掉 Claude Code、在磁碟上 `mv`、（可選）把 git remote 設成 `git@github.com:kirin/claude-workbench.git`、在新目錄重啟 Claude Code。Plugin 程式碼**不**依賴 local 目錄名——所有穩定引用都用 upstream `claude-workbench` 識別。

---

## 7. 繼續帶著的 Open Questions

取自 SPEC §14，對下一階段影響最大的：

- **#3 併發的 headless Claude** — 若 user 在多台機器都跑 cron 對同一 repo，目前的 `flock` 只保 per-machine。Phase 1 驗證會暴露這是不是問題。
- **#8 Notify rate limiting** — Phase 2 落地前要有具體 UX（不然 cron + notify 一起來就是告警疲勞）。
- **#11 Memory embedding 安裝 UX** — 卡住 Phase 4 的開始；SessionStart 不能同步下 80 MB。
- **#12 / #13 docsync granularity + 語意條件** — Phase 7 的設計問題。

沒有一項卡住 Phase 1（kanban v0.1.0 真實環境手動驗證）。

---

## 8. 建議的下一步

按槓桿大小排序，不是嚴格 SPEC 順序：

1. **Phase 1 驗證** — 真實專案上用 plugin 一週。把痛點記在 scratch 檔（不是 SPEC）再去改程式。拖越久，Phase 3/5 整合就越容易建在錯誤假設上。
2. **三方流程 E2E smoke**（SPEC §8.8）：實際 repo 裝 kanban + notify + docsync，觸發一次 DOING→DONE + docsync-mapped 檔案編輯，驗 Pushover 有推、docsync 在 `enforcement=block` 時擋得住。
3. **開工 `memory` v0.1.0** — 這是最後一個核心 stub，也擋住 `workbench` 核心 bundle release。
4. **停止擴充 SPEC**，開始寫 `docs/quickstart.md`。SPEC 前載太多；真實 user 要的是一頁式 getting-started。
5. **在 plugin 環境或 CI 裝 PyYAML** — docsync 的 fallback YAML parser 夠處理隨附 template，但不是完整 YAML 實作。透過 `workbench-docsync` 消費 `.claude/docsync.yaml` 的 sibling 沒事，手寫詭異 YAML 的 user 會踩到 fallback。

---

## 9. `plugins/notify/` — 已完成 v0.1.0

### 9.1 內容

```
plugins/notify/
├── .claude-plugin/plugin.json              ✅ v0.1.0
├── skills/notify-usage/SKILL.md            ✅ 規範 capability-detection + priority 慣例
├── commands/
│   ├── setup.md                            ✅ /notify:setup（互動式 Pushover config + CLI 安裝）
│   ├── test.md                             ✅ /notify:test
│   └── config.md                           ✅ /notify:config（show/edit，redact 過的顯示）
├── hooks/hooks.json                        ✅ Notification：permission_prompt|elicitation_dialog|idle_prompt|auth_success
├── scripts/
│   ├── notify-dispatch.py                  ✅ hook + CLI + --health 模式；scrubber；throttle 狀態
│   ├── providers/__init__.py               ✅
│   ├── providers/pushover.py               ✅ stdlib HTTPS；5s timeout；priority / sound 對應
│   ├── workbench-notify                    ✅ bash shim（exec python3 notify-dispatch.py --cli "$@"）
│   └── install-cli.sh                      ✅ idempotent symlink 到 ~/.claude-workbench/bin/
└── templates/
    └── notify-config.example.json          ✅ 用 env var 的形狀，4 條 rule 對應 4 種事件
```

### 9.2 現在能做什麼

- `workbench-notify --health` 在 `~/.claude-workbench/notify-config.json` 存在、parse 成功、至少一個 provider 啟用時 exit 0。這是 SPEC §8.7 承諾的 capability detection 契約。
- `/notify:setup` link CLI、寫一份引用 `${PUSHOVER_USER_KEY}` / `${PUSHOVER_APP_TOKEN}` 的 config——**token 絕不進 JSON**。
- Dispatcher 在送出前 scrub 掉 token 形態的子字串（`sk-…`、`ghp_…`、`xoxb-…`、JWT、AWS key、純 hex ≥ 40）。
- 失敗寫入 `~/.claude-workbench/logs/notify-failures.log` 但**不寫 message body** — 避免 secret 從 log 外洩。
- 每條 rule 的 `throttle_seconds`（`idle_prompt` 預設 300）透過 `~/.claude-workbench/state/notify-throttle.json` 節流。

### 9.3 已知限制 / 擱置事項

- **只有 Pushover** — example config 有 `ntfy`/`slack`/`telegram` 區塊但還沒對應的 provider module。Dispatcher 容錯（log 一條 "unknown provider"）而不是 crash。
- **非同步投遞 (無)** — 每次 hook call 透過 HTTPS stack 同步呼叫。Pushover 5 秒 timeout 卡住 latency，但網路完全死的時候 hook 會拖 5 秒。
- **`emergency` 優先度被夾到 `high`** — Pushover 真正的 `priority=2` 需要 `retry`/`expire` 配對，這個 plugin 沒接。
- **Throttle 狀態是 per-user 非 per-project** — 同一台機器的多個專案共用 `(event, provider)` throttle key。
- **`/notify:config edit` 不會真的啟動 `$EDITOR`** — 刻意印指令，因為 harness 無法乾淨地搶走 user 的 TTY。

### 9.4 現在開始運作的 sibling 接線

`kanban-autocommit.sh` 從 Phase 0a 就有 `HAS_NOTIFY=1` 的 dispatch block（本 doc §4）。notify v0.1.0 裝好、`~/.claude-workbench/bin/` 在 PATH 上以後，那些 block 自動觸發。尚未端到端驗證。

---

## 10. `plugins/docsync/` — 已完成 v0.1.0

### 10.1 內容

```
plugins/docsync/
├── .claude-plugin/plugin.json              ✅ v0.1.0
├── skills/docsync-workflow/
│   ├── SKILL.md                            ✅
│   └── references/
│       ├── update-patterns.md              ✅ CODE_MAP / ARCHITECTURE / 每 module README template
│       └── skip-decision-tree.md           ✅ skip_conditions + required_if 判斷規則
├── commands/
│   ├── init.md                             ✅ /docsync:init（scan → interview → dry-run → write）
│   ├── check.md                            ✅ /docsync:check
│   ├── rules.md                            ✅ /docsync:rules
│   ├── bootstrap.md                        ✅ /docsync:bootstrap
│   └── validate.md                         ✅ /docsync:validate
├── hooks/hooks.json                        ✅ SessionStart · PostToolUse(Edit|Write|MultiEdit) · Stop
├── scripts/
│   ├── rule_engine.py                      ✅ 純邏輯；PyYAML 優先、小 fallback parser
│   ├── docsync-bootstrap.py                ✅ SessionStart — bootstrap docs 提醒
│   ├── docsync-guard.py                    ✅ PostToolUse — 每次 edit 規則比對，warn 等級
│   ├── docsync-finalcheck.py               ✅ Stop — session 結束摘要 + memory fan-out
│   ├── workbench-docsync.py                ✅ CLI：match / check / summarize / rules / validate / --health
│   ├── workbench-docsync                   ✅ bash shim
│   └── install-cli.sh                      ✅ symlink installer
└── templates/
    ├── docsync.example.yaml                ✅ Rust 單一倉庫
    ├── docsync.python.yaml                 ✅
    ├── docsync.js.yaml                     ✅
    └── docsync.schema.json                 ✅ schema/docsync.schema.json 的鏡射
```

### 10.2 現在能做什麼

- `workbench-docsync match <path>` 解析哪些規則適用。
- `workbench-docsync check --since <ref>` 當任何規則的必要文件過時，exit 2 並回一個 JSON `{pending: [...]}` payload。這就是 SPEC §8.4 為 kanban DONE gate 指定的 shape。
- `workbench-docsync validate` 抓：`schema_version` 錯、規則 id 重複、未知的 `required_if` 值、bootstrap doc 不存在。
- SessionStart hook 把 bootstrap-docs 提醒注入為 `additionalContext`。
- PostToolUse guard 在每個 Edit/Write/MultiEdit 命中規則時發 `additionalContext` warn（`enforcement != silent` 時）。
- Stop hook 聚合 session 整體變更；若 `integration.memory.summarize_doc_changes: true` 且 `workbench-memory` 在 PATH 上，就對每個觸及的 doc fan-out 摘要。

### 10.3 已知限制 / 擱置事項

- **YAML parser fallback 窄** — 如果 user 沒裝 PyYAML 而且手寫詭異 YAML（anchor、flow syntax、多行 block scalar），fallback 會 raise。隨附 template 刻意選在 fallback 能處理的子集內。Docs 指使用者 `pip install pyyaml` 處理複雜 config。
- **`/docsync:init` Phase 4 dry-run** 目前在 command prompt 裡模擬規則比對，沒有 call `workbench-docsync match`（此時 YAML 還不在磁碟上）。未來改進：先寫 temp 路徑、比對、確認後 rename。
- **沒有 runtime 的 JSON-Schema 驗證** — `/docsync:validate` 做結構 + 語意檢查但沒載入 `docsync.schema.json`。CI 側用 `jsonschema` 驗證是後續。
- **`required_if` 是純語意的** — engine 列候選、skill 教判斷。沒有程式會自動區分「這次 edit 改了 API」vs「這次 edit 只是改 private helper 名字」。這是刻意設計（SPEC §6.4），未來 v0.2 可能加對明顯案例的 heuristic。
- **Glob matching**：只支援 `**` 和標準 fnmatch。`{a,b}` 分支未支援。
- **Rename/move**（Open Question 15）仍未定義 — `git mv` 會顯示為新路徑上的 edit，所以規則會觸發，但舊檔名還殘留在文件中，要 user 自己改。
- **Enforcement `block`** 接線存在（kanban-autocommit.sh 可 call `workbench-docsync check`），但 kanban 的 DONE command 還**沒**在允許轉換前呼叫這個檢查。三方 E2E 測試時要在 `kanban-autocommit.sh` 的 pre-commit 路徑加一行。

### 10.4 三塊現在如何互動

三個 plugin 都裝（`kanban` + `notify` + `docsync`）時：

- **SessionStart**：kanban 表示 DOING/BLOCKED；docsync 表示 bootstrap docs。都走 `additionalContext`。
- **Edit**：kanban-guard 擋 `kanban.json` 直編；docsync-guard 在命中規則的 code 編輯上 warn。
- **PostToolUse**：kanban-autocommit 對獨立的 kanban 變更 commit；docsync 的 Stop hook 還沒開（那是 session 結束）。
- **Kanban 轉換**：`workbench-notify` 透過 kanban-autocommit 的 `HAS_NOTIFY` block 觸發。
- **Session 結束**：docsync-finalcheck 跑；若 memory 裝了，摘要傳遞；沒有則只印摘要。

---

*End of current_state_zhtw.md*
