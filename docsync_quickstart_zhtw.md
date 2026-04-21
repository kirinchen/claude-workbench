# docsync — 快速上手

*[English](./docsync_quickstart.md)*

> 讓 code 變更和文件保持同步。**Config-driven**（`.claude/docsync.yaml`），不是 prompt-driven。取代常見的「把規則硬寫在 CLAUDE.md」模式，改成結構化、可版本控、團隊可 review 的形式。

*完整設計見 [`SPEC.md §6`](./SPEC.md)，程式碼見 [`plugins/docsync/`](./plugins/docsync)。*

---

## 0. 前置條件

- 已安裝 Claude Code。
- 你的專案是個**有 commit 歷史的 git repo**——init 流程會拿最近 ~20 個 commit 做 dry-run，這是讓 config 變得具體可用的關鍵。
- Shell rc 包含：
  ```bash
  export PATH="$HOME/.claude-workbench/bin:$PATH"
  ```
- 建議：`pip install pyyaml`。Plugin 內建一個簡易 fallback parser 能處理隨附的 template，但如果你手改 YAML 用到 anchor / flow syntax / 多行 block scalar，就需要 PyYAML。

---

## 1. 安裝

在 Claude Code 裡，**進入你要 docsync 管理的那個專案**（docsync 是 per-project 的）：

```
> /plugin marketplace add kirinchen/claude-workbench   # 已加過可省略
> /plugin install docsync@claude-workbench
```

---

## 2. Init 流程（scan → interview → dry-run → write）

```
> /docsync:init
```

**重點在這**。指令會跑五階段——別一路按 yes，Phase 4 才是確認規則合不合理的地方。

### Phase 1 — Scan（靜默）
偵測：
- 專案類型：Rust 單一倉庫（`Cargo.toml` + `[workspace]`）· JS 單一倉庫（`pnpm-workspace.yaml` / `lerna.json`）· Python（`pyproject.toml`）· Go（`go.mod`）· 混合。
- Code modules：頂層目錄，排除 `.git`、`node_modules`、`target`、`.venv`、`dist` 等。
- 現有文件：`doc/`、`docs/`、`README*`、`ARCHITECTURE*`、`CODE_MAP*`、`SPEC*`、每個 module 的 README。

加 `--from-existing-claude-md` 還會解析你現有的 `CLAUDE.md`，從裡面的 mapping 表格預填 interview 答案。

### Phase 2 — Interview（一次最多 3 題，用 `AskUserQuestion`）
會依序問你：
1. **Bootstrap docs**（多選）——哪些文件希望 Claude 在每個 session 開始時自動讀？
2. **Module → doc 映射**（每個 module 單選）——global CODE_MAP section / module README / 兩者 / 都不要 / 自訂。
3. **Enforcement**：`warn`（推薦、預設）/ `block`（搭配 kanban 整合做硬閘）/ `silent`（只有 `/docsync:check` 會顯示 pending）。
4. **Skip conditions**：`bug_fix_only` / `internal_refactor` / `test_only` / `comment_formatting_only`。
5. **整合**（只有 kanban / memory 已裝才問）：DONE gate？memory summary？

### Phase 3 — Propose
Claude 會把完整 draft YAML 丟進一個 code block 給你看。回覆：
- `yes` → 繼續。
- `edit rules`（或 `edit bootstrap_docs`、`edit enforcement`、…）→ 回到前面修改。
- `cancel` → 中止，什麼都不寫。

### Phase 4 — Dry-run（**殺手級功能，不要跳過**）
針對你最近 20 個 commit 跑規則，挑 3 個有代表性的（跨 module、文件改動多的、純 code 的），告訴你新規則**如果當時已生效**會怎麼判：

```
commit abc123 "refactor grid pricing"
├ changed: position-manager/src/grid.rs
└ would prompt: doc/CODE_MAP.md (§position-manager)
                position-manager/README.md (required_if: params_changed)

commit def456 "fix typo in comment"
├ changed: common/src/types.rs
└ would skip (skip_condition: comment_formatting_only)
```

如果 Phase 4 看起來不對——太吵、skip 太寬、漏掉某個 module——回 Phase 2/3 修。**YAML 要你確認 Phase 4 後才會寫出**。

### Phase 5 — Write
1. 寫 `.claude/docsync.yaml`。
2. `install-cli.sh` 把 `workbench-docsync` symlink 到 `~/.claude-workbench/bin/`。
3. 問你要不要 `git commit` 這個 YAML（預設 yes——config 是團隊共享的）。

---

## 3. 驗證

在 Claude 裡：
```
> /docsync:validate                      # 檢查 YAML 結構
> /docsync:rules src/api/handler.py      # 「這個檔案觸發哪些規則？」
> /docsync:check --since HEAD~5          # 「最近 5 個 commit 有沒有 pending 同步？」
> /docsync:bootstrap                     # 列出 bootstrap_docs
```

在 Claude 外：
```bash
workbench-docsync --health
workbench-docsync rules --format text
workbench-docsync check --since HEAD~5 --format json
#  -> exit 0 表乾淨，exit 2 表有 pending（這是 kanban DONE gate 在
#     enforcement=block 時使用的契約）
```

---

## 4. Session 中怎麼運作

| Hook | 何時 | 做什麼 |
|---|---|---|
| SessionStart | Session 開始 | 發 `additionalContext` 提醒 Claude 在寫 code 前先讀 `bootstrap_docs` |
| PostToolUse · Edit/Write/MultiEdit | 每次 code 編輯後 | 用規則比對剛改的檔案；`enforcement=warn` 時注入 `additionalContext` 列出 Claude 應該更新的文件；`silent` 跳過 |
| Stop | Session 結束 | 聚合整個 session 的變更、回報 pending、若啟用 memory 整合則把摘要寫進 `workbench-memory` |

所以在 session 中會變成這樣：
1. 你叫 Claude 改 `src/api/handler.py`。
2. 下一個 Claude turn 會看到：`docsync: \`src/api/handler.py\` matched 1 rule(s). Consider updating: doc/api.md (rule: api)`。
3. Claude 讀那份文件、更新、根據 skill 的要求說明它的判斷——或者宣稱這次變更符合某個 `skip_condition` 並給理由。

---

## 5. Claude 決定 skip 的邏輯

Skill 會教 Claude 以下判斷：

- **`skip_conditions`**——當變更屬於 `bug_fix_only`、`internal_refactor`、`test_only`、`comment_formatting_only` 時，該次 doc 更新確實不必要。定義很嚴格（見 [`plugins/docsync/skills/docsync-workflow/references/skip-decision-tree.md`](./plugins/docsync/skills/docsync-workflow/references/skip-decision-tree.md)）。
- **`required_if`**——規則可以標 `required_if: api_changed` 等條件。若語意條件不成立，該 doc 就不是必要更新。Claude 必須**公開說明**條件與理由。

**過度 skip** 是這個 plugin 要避免的主要失敗模式。如果實際用起來覺得 skip 太寬，重跑 `/docsync:init --reset`，把 `skip_conditions` 剪短。

---

## 6. 跟相鄰 plugin 的整合

在 `.claude/docsync.yaml` 裡設：

```yaml
integration:
  kanban:
    block_done_if_pending: false      # 改成 true 啟用 kanban DONE gate
  memory:
    summarize_doc_changes: true       # Stop hook 會把文件變更摘要寫進 memory
```

- **kanban gate**：當為 true 且 `enforcement=block` 時，`/kanban:done` 會呼叫 `workbench-docsync check --since $(git merge-base HEAD main) --format json`——exit 2 就擋住 DONE 轉換，直到文件同步。（注意：v0.1.0 的 kanban-autocommit 還沒接這個呼叫——這是三方整合最後一塊。）
- **memory summary**：若 `workbench-memory` 在 PATH 上，每個 session 的文件更新摘要會存成 memory entry 供未來 recall。Memory 仍在 Phase 4 → 目前這條是 inert（沒作用），等 memory 出來才會動。

---

## 7. 調整 / 迭代

docsync **絕不自改** `.claude/docsync.yaml`——user 擁有它。要改規則：

```
> /docsync:init --reset
```

或手動改再跑 `/docsync:validate`。結構化檢查會抓：
- `schema_version` 必須是 `1`。
- `enforcement` 必須是 `silent | warn | block`。
- 規則 id 必須唯一。
- `required_if` 必須是 `architecture_changed`、`api_changed`、`params_changed`、`schema_changed` 其中之一。
- 每個 `bootstrap_docs` 路徑必須存在於磁碟上。

---

## 8. 隨附的 template

如果 init 跟你的 layout 配不太起來，三個起手式 template 在 [`plugins/docsync/templates/`](./plugins/docsync/templates/)：
- `docsync.example.yaml` — Rust 單一倉庫（Cargo workspaces）
- `docsync.python.yaml` — Python（`pyproject.toml`）
- `docsync.js.yaml` — JS 單一倉庫（pnpm / lerna）

可以挑一個複製到 `.claude/docsync.yaml`、修改、再 `/docsync:validate`。

---

## 9. 疑難排解

| 症狀 | 原因 | 解法 |
|---|---|---|
| `workbench-docsync: cannot locate workbench-docsync.py` | Shim 是 symlink，resolve 失敗 | v0.1.0 的 shim 已修；重跑 `bash ${CLAUDE_PLUGIN_ROOT}/scripts/install-cli.sh`，或設 `DOCSYNC_CLI_PY=/full/path/workbench-docsync.py` |
| `docsync: no .claude/docsync.yaml found` | 你不在專案根目錄，或 init 沒完成 | `cd` 回專案根；重跑 `/docsync:init` |
| `/docsync:validate` 回 "unknown required_if=..." | 手改時打錯 / 用到不支援的值 | 只能是：`architecture_changed`、`api_changed`、`params_changed`、`schema_changed` |
| PostToolUse warn 每次 edit 都觸發，像碎念 | 規則太廣，或 `skip_conditions` 太窄 | `/docsync:init --reset`；Phase 2 多勾一些 `skip_conditions` 或把 rule glob 收緊 |
| 手改後 YAML parse error | 用到 fallback parser 不支援的語法（anchor、flow syntax） | `pip install pyyaml` |
| `README.md (required_if: api_changed)` 持續 pending 但你**沒**改 API | 語意條件靠 Claude 判斷；文件真的沒必要改就在對話裡說清楚——engine 不會自動 resolve | 接受現況，或改寫規則移除 `required_if` |
| `.claude/docsync.yaml` 沒進 git | `.gitignore` 有 `.claude/` 或 `.claude/*` | 加一條反向規則：`!.claude/docsync.yaml` |

---

## 10. 解除安裝

```
> /plugin uninstall docsync@claude-workbench
```

會留下：
- `.claude/docsync.yaml`（你專案的 config——版本控的）。
- `~/.claude-workbench/bin/workbench-docsync`（symlink，現在 dangling）。

要完全清乾淨：
```bash
rm -f ~/.claude-workbench/bin/workbench-docsync
rm -f .claude/docsync.yaml    # 只在你確定要忘掉這份映射時才刪
```

---

## 11. 下一步

- 加裝 `kanban`：[`kanban_quickstart_zhtw.md`](./kanban_quickstart_zhtw.md)。啟用 DONE gate 整合。
- 加裝 `notify`：[`notify_quickstart_zhtw.md`](./notify_quickstart_zhtw.md)。當 `enforcement=block` 擋下 DONE 時，被擋的轉換會透過 notify 推播。
- 讀 [`plugins/docsync/skills/docsync-workflow/references/`](./plugins/docsync/skills/docsync-workflow/references/) 看 Claude 如何判斷 `skip_conditions` 和 `required_if` 何時成立。
