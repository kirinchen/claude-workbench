# kanban — 快速上手

*[English](./kanban_quickstart.md)*

> Claude Code 的任務狀態持續化。專案根目錄的一份 `kanban.json` 就是你和 Claude 共用的工作佇列。

*完整設計見 [`SPEC.md §3`](./SPEC.md)，程式碼見 [`plugins/kanban/`](./plugins/kanban)。*

---

## 0. 前置條件

- 已安裝 Claude Code 並完成 `claude login`。
- 可用的 `git`（kanban 會用它自動 commit，但**不需要**設 remote）。
- Shell rc（`~/.bashrc` 或 `~/.zshrc`）包含以下這行——相鄰 plugin 需要：
  ```bash
  export PATH="$HOME/.claude-workbench/bin:$PATH"
  ```
- 專案目錄是一個 git repo（不是就先 `git init`）。

---

## 1. 安裝

```bash
cd my-project
claude
```

在 Claude Code 裡：
```
> /plugin marketplace add kirinchen/claude-workbench
> /plugin install kanban@claude-workbench
```

不用外部服務、不用 token。這是最容易試的一個 plugin。

---

## 2. 初始化 `kanban.json`

```
> /kanban:init --with-examples
```

產生：
- `kanban.json` — 工作佇列（附 4 個範例任務讓你看懂結構）。
- `kanban.schema.json` — JSON Schema（讓編輯器做驗證 + 未來的 viewer 會用）。

想要空白的看板就拿掉 `--with-examples`。

**背後裝了什麼**：
- `kanban-guard.sh`（PreToolUse）——阻止 Claude 直接手動編輯 `kanban.json`。
- `kanban-session-check.sh`（SessionStart）——每個 session 開始時自動把 DOING / BLOCKED 列出來。
- `kanban-autocommit.sh`（PostToolUse）——把 kanban 變更自動 commit 成獨立 commit。

---

## 3. 新增任務

**你（人類）直接編輯 `kanban.json` 來新增任務**。Claude **不能**——guard hook 擋住了。這是刻意設計：狀態轉換走 slash command，但任務的**創建**走你。

新增一個 TODO 任務的最小欄位（塞進 `tasks[]`）：
```jsonc
{
  "id": "task-005",
  "title": "簡短祈使句的標題",
  "column": "TODO",
  "priority": "P1",
  "category": "infra",
  "tags": ["backend"],
  "depends": [],
  "created": "2026-04-21T14:00:00+08:00",
  "updated": "2026-04-21T14:00:00+08:00",
  "started": null,
  "completed": null,
  "assignee": null,
  "description": "比較長的 markdown 描述。",
  "comments": [],
  "custom": {}
}
```

同一次編輯也要更新 `meta.updated_at`。**還不想 commit** 可以先不急——`kanban-autocommit.sh` 只有在 `kanban.json` 是唯一 dirty file 時才會觸發。

之後：Textual TUI viewer 規劃在 v0.2，你不會永遠都在手改 JSON。

---

## 4. 日常流程

在 Claude Code 裡：
```
> /kanban:status          # 唯讀總覽
> /kanban:next            # 挑最高優先度、可執行的 TODO，移到 DOING 並開始做
> /kanban:done            # 關掉目前 DOING 任務（可選 --note=...）
> /kanban:block <task-id> --reason="需要 ops 給 API key"
```

Skill 會強制執行的規則（見 `plugins/kanban/skills/kanban-workflow/SKILL.md`）：
- 有未完成 `depends` 的任務**不能**進 DOING。
- `APPROVED` 是終點——不會被修改、不會被搬回來。
- `BLOCKED` 必須有非空的 `custom.blocked_reason`。

`/kanban:next` 之後，Claude 會直接依照任務的 `description` 開始做。你隨時可以打斷。

---

## 5. 自動 commit

當 `kanban.json` 是唯一 dirty file 時，PostToolUse hook 會跑：
```
git add kanban.json && git commit -m "kanban: task-042 TODO→DOING"
```

這個設計**用混合檔案自動退出**——只要你還有其他 dirty file，autocommit 就拒絕觸發，你可以自己手動 stage 一起 commit。（把 kanban 狀態變更留成獨立 commit，看 history 會清爽很多。）

---

## 6. Headless 自動化（選用）

想讓 Claude 在你不在時自動消化佇列：
```
> /kanban:enable-automation
```
選 **cron polling**（推薦，預設每 10 分鐘）。指令會帶你走過：
1. 把 `cron-runner.sh` 安裝到 `~/.claude-workbench/bin/`。
2. 寫一行有 tag 的 crontab。
3. log 輸出到 `~/.claude-workbench/logs/cron-runner.log`。

**用的是你的 `claude login`（Pro / Max 訂閱），不會燒 API credit**。`flock` 防止重入。

移除：`crontab -e` 刪掉帶 `# claude-workbench:` tag 的那行。

---

## 7. 驗證整個流程

```bash
# 在 Claude 裡：
> /kanban:status          # 應該看得到看板
> /kanban:next            # 應該挑到一個 TODO

# 在 Claude 外：
git log --oneline | head -3      # 應該看到 "kanban: task-XXX TODO→DOING"
```

---

## 8. 疑難排解

| 症狀 | 原因 | 解法 |
|---|---|---|
| "Direct edits to kanban.json are blocked" 當你想叫 Claude 改時 | Guard hook 正常觸發 | 改用 `/kanban:next` / `/kanban:done` / `/kanban:block` |
| Autocommit 沒觸發 | 有其他 dirty file | 要嘛只 stage kanban.json，要嘛自己手動 commit |
| `/kanban:next` 說「全部被擋」 | 每個 TODO 都有未完成 deps | 先解 deps，或把某個 BLOCKED 任務解鎖 |
| SessionStart 沒顯示 DOING / BLOCKED 摘要 | `kanban.json` 不存在或不在專案根 | 確認你 `cd` 到對的目錄才開 `claude` |
| Autocommit 跑了但 message 是 "kanban: update" | Transition detection 的 fallback 觸發（python3 + jq 都沒裝） | 裝其中一個 |

---

## 8a. Jira 模式（kanban v0.2+）

預設 driver 寫進 `kanban.json`。如果是多機器團隊、或非工程的 owner 要用手機審核，切到 **Jira 模式**：slash command 介面不變，只換儲存層。

```
> /kanban:initjira
```

五步互動式：憑證 → board URL → workflow 檢查 → AP custom field → 第一個 AP 註冊。Token 存到 `~/.claude-workbench/.env`（和 notify 共用同一個檔）。整個 flow 冪等可續跑——上次中斷點接著走。

init 完之後：

```
> /kanban:status     # 從 Jira 拉即時狀態
> /kanban:doing      # 執行已在 DOING 的卡片（owner 把 TODO 推進 DOING；agent 執行）
> /kanban:done       # DOING → In Review（由人類批准成 Done）
> /kanban:question AGENT-42 "v1 是否保留向下相容？"
> /kanban:whoami     # 顯示 driver、AP、token 有效性、MCP 衝突
```

每個 repo 的 agent 身份存在 `.claude/kanban-agent.json`（建議 commit——讓團隊看到哪個 agent 管哪個 repo）。Anti-self-approve 會拒絕「自己 AP 的卡片」轉 APPROVED。

如果 workflow 沒有完整 6 個 canonical status（缺 `BLOCKED` / `REVIEW` / `CANCELLED`），加 `--partial` 重跑——缺的欄位會用 label 替代（`kanban:blocked` 等）。

完整 v0.2 設計見 [`epic/kanban_plugin_ Jira_backend_driver_UPDATE.md`](./epic/)。

---

## 8b. 多機器 / 多 repo setup（kanban v0.3+）

最常見的卡關：「我在 A 機器設好了——B 機器 / B repo / 同事 C 是不是要把五步 init 全跑一次？」

Setup 拆成**三層**，每層有自己的生命週期：

| 層級 | 內容 | 何時要重跑 |
|---|---|---|
| **Per-board（可分享）** | `transitions`、AP custom field id、board metadata、`conventions` 規則 | **一次**。然後 `/kanban:showjira-code`，任何同事 / repo 用 `/kanban:import-jira-code` 貼 JSON 就繼承 |
| **Per-machine（每台必做）** | Jira 憑證（`~/.claude-workbench/.env`：base URL、agent email、API token） | 每台機器一次。之後該台所有 repo 共用 |
| **Per-repo（每個 repo 必做）** | 這個 repo 用哪個 AP（`.claude/kanban-agent.json`） | 每個 repo 一次。各自從 Jira live options 挑 |

### Cheatsheet

| 情境 | 新 receiver 端要跑的 |
|---|---|
| **全新機器 + 全新 repo** | `/kanban:init` → `/kanban:import-jira-code`（一個指令做完憑證 + 貼 code + 選 AP） |
| **同機器 + 新 repo** | `/kanban:init` → `/kanban:import-jira-code`（憑證自動跳過——本機已有；只剩貼 code + 選 AP 互動） |
| **同 repo + 換機器**（clone 一個已經是 jira mode 的 repo） | `git pull` → `/kanban:reset-credentials`。`kanban.json` 已經帶完整 `backend.jira` block 透過 git 過來了，這台只缺自己這台機器的 Jira token。**不用重貼 code。** |
| **既有 repo 已是 jira mode 在這台** | 啥都不用——已 setup。`/kanban:whoami` 可驗證 |

> **為什麼同 repo 換機器這麼簡單**：`kanban.json` 會被 `kanban-autocommit.sh`
> PostToolUse hook 自動 commit，跟著 `git push` / `git pull` 走。`backend.jira`
> block（transitions、projectKey、ap.fieldId、conventions）就是
> `/kanban:showjira-code` 印出來那份 JSON——只是 git 幫你做傳輸。唯一 per-machine
> 的東西是你 `~/.claude-workbench/.env` 裡的 Jira API token，那個不在 git 裡
> （也不該在——每台機器各拿一張 token 比較安全）。

### 運作原理

來源端：

```
> /kanban:showjira-code
```

印出 `kanban-jira-code/2` 格式 JSON，含 per-board 設定——`transitions`、`ap.fieldId`、`boardId`、`projectKey`、`conventions`。**Token 不在 code 內**——憑證永遠 per-machine 留在 `~/.claude-workbench/.env`。

接收端（任何另一台機器 / 另一個 repo）：

```
> /kanban:init                  # scaffold kanban.json (local mode)
> /kanban:import-jira-code      # 貼 JSON；視情況跑憑證 + 選 AP
```

第一次在某台機器跑時會問憑證；同台第二個 repo 時自動跳過。如果 code 帶 `conventions.notes` 非空，接收端必須輸入 `I have read these` 才能完成 init（這個 friction 是刻意的——詳見 issue #10）。

版本相容性：
- `kanban-jira-code/1`（v0.3.0+）—— transitions + AP field
- `kanban-jira-code/2`（v0.3.4+）—— 加上 `conventions`（notes + `blockedRequiresLink`）
- v0.3.4+ 接收端兩種都收；v0.3.4 來源端預設輸出 /2

---

## 9. 解除安裝

在 Claude 裡：
```
> /plugin uninstall kanban@claude-workbench
```

`kanban.json` 和 `kanban.schema.json` 會留在你的專案——plugin 不動你的資料。想要乾淨重置就自己刪。

如果啟用了 cron：`crontab -e` 刪掉帶 tag 的那行。

---

## 10. 下一步

- 加裝 `notify`：[`notify_quickstart_zhtw.md`](./notify_quickstart_zhtw.md)——裝了之後 `DOING → BLOCKED` 會推播到你手機。
- 加裝 `docsync`：[`docsync_quickstart_zhtw.md`](./docsync_quickstart_zhtw.md)——讓 code 變更自動連動到文件更新。
- 讀 [`SPEC.md §8`](./SPEC.md) 看三個 plugin 都裝時的互動方式。
