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
- `DONE` 是終點——不會被修改、不會被搬回來。
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
