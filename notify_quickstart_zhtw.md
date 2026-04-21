# notify — 快速上手

*[English](./notify_quickstart.md)*

> 透過 Pushover 把 Claude Code 的通知推到你手機。避免「AI 卡住等回應、但人不在電腦前」的死結。

*完整設計見 [`SPEC.md §4`](./SPEC.md)，程式碼見 [`plugins/notify/`](./plugins/notify)。*

---

## 0. 前置條件

- 已安裝 Claude Code。
- 有 Pushover 帳號（免費試用，解鎖要一次性 $5 / 平台）。
- Shell rc（`~/.bashrc` 或 `~/.zshrc`）包含：
  ```bash
  export PATH="$HOME/.claude-workbench/bin:$PATH"
  ```

---

## 1. 取得 Pushover 憑證

1. 到 **https://pushover.net** 註冊（免費）。
2. 儀表板首頁會看到 **Your User Key**——30 字元的字串，`u` 開頭。複製下來。
3. 拉到 **"Your Applications"** → **Create an Application/API Token** → 取個名字（例：`claude-code`）→ 會給你一組 30 字元的 **API Token/Key**，`a` 開頭。複製下來。
4. 手機裝 Pushover app（iOS / Android，一次性買斷解除 7 天試用），登入同一個帳號。第一次開 app 會註冊裝置——那就是收推播的對象。

---

## 2. 把 token 設成環境變數（**不要**放進 JSON）

加到 `~/.bashrc` / `~/.zshrc`：
```bash
export PUSHOVER_USER_KEY="u..."          # 儀表板的 Your User Key
export PUSHOVER_APP_TOKEN="a..."         # 你建立的 Application 給的 API Token
```
然後：
```bash
source ~/.bashrc    # 或開新 terminal
```

**macOS 注意**：如果你從 Dock / Launchpad 啟動 Claude Code（GUI），它**看不到** shell rc 的 env。解法是：(a) 永遠從 terminal 開 Claude（iTerm / Terminal 裡 `claude`），或 (b) 用 `launchctl setenv` 把變數設給整個 GUI 環境。

---

## 3. 安裝 plugin

在 Claude Code 裡（任一專案都行）：
```
> /plugin marketplace add kirinchen/claude-workbench
> /plugin install notify@claude-workbench
```

---

## 4. 跑 setup

```
> /notify:setup
```

它會做這些事：
1. 寫 `~/.claude-workbench/notify-config.json`，用 `${PUSHOVER_USER_KEY}` / `${PUSHOVER_APP_TOKEN}` 引用——**token 不會進 JSON 檔**。
2. 跑 `install-cli.sh`，把 `workbench-notify` symlink 到 `~/.claude-workbench/bin/`。
3. 印出後續步驟（export、PATH、驗證）。

之後想重跑 setup：加 `--reset`。

---

## 5. 驗證

在 Claude 裡：
```
> /notify:test
```
手機應該在 ~3 秒內震動，顯示「Claude Code · test」。

在 Claude 外：
```bash
workbench-notify --health
#  -> exit 0，印 "notify: ok"（config + provider 都正常）
workbench-notify --title "Hi" --message "from shell" --priority normal
```

---

## 6. 理解什麼情況會推播

Claude Code 會發四種 `Notification` hook 事件；plugin 依照 config 裡的 `rules[]` 路由：

| 事件 | 意思 | 預設優先度 | Throttle |
|---|---|---|---|
| `permission_prompt` | Claude 要工具權限 | high | 無 |
| `elicitation_dialog` | Claude 要透過 `AskUserQuestion` 問你 | high | 無 |
| `idle_prompt` | Claude 閒置等待輸入 | normal | 5 分鐘 |
| `auth_success` | 認證流程完成 | low | 無 |

相鄰 plugin（kanban、docsync、memory）要推播時就直接 call CLI：
```bash
workbench-notify --title "Kanban" --message "task-042 blocked" --priority high
```

---

## 7. 調整規則

編輯 `~/.claude-workbench/notify-config.json`。關鍵旋鈕：

- `providers.pushover.enabled`：設 `false` 可以直接靜音但不用 uninstall。
- `providers.pushover.device`：填特定裝置名，就只推到那一台；不填就推所有已註冊的裝置。
- `providers.pushover.sound_map`：依事件類型覆寫音效（[Pushover sound 清單](https://pushover.net/api#sounds)）。
- `rules[].throttle_seconds`：同一個 `(event, provider)` 組合多少秒內不重複推。
- `rules[].priority`：`-2`（最低、靜音）到 `1`（high）。`2` 是 "emergency" 但被夾到 `1`——plugin 沒接 Pushover 的 retry/expire 配對。

改完之後用 `workbench-notify --health` 再確認一次。**不用重啟**——dispatcher 每次 call 都重讀 config。

---

## 8. 安全姿態

- 全程 HTTPS 連 Pushover。
- 訊息送出前會過一個 scrubber，redact 常見的 token 型態（`sk-…`、`sk-ant-…`、`ghp_…`、`xox[abpr]-…`、`AKIA…`、`AIza…`、JWT、純 hex ≥40 字元）。
- 失敗時 append 到 `~/.claude-workbench/logs/notify-failures.log`——**不會寫 message body**，只寫原因，避免 secret 透過 log 洩漏。
- 沒有 telemetry。Plugin 除了你設定的 provider，不跟任何服務通訊。

---

## 9. 疑難排解

| 症狀 | 原因 | 解法 |
|---|---|---|
| `/notify:test` 說「sent」但手機沒響 | Pushover app 沒登入，或裝置沒註冊 | 打開 app、登入、等它完成裝置註冊；重試 |
| `workbench-notify: command not found` | `~/.claude-workbench/bin` 不在 PATH | 加到 shell rc（Step 0），重新 source |
| `workbench-notify --health` exit 1：`unconfigured` | `~/.claude-workbench/notify-config.json` 不存在 | 跑 `/notify:setup` |
| `workbench-notify --health` exit 1：`no enabled provider` | `providers.pushover.enabled: false` | 改回 `true` |
| 推播送到了但 body 是空 / `[REDACTED]` | Scrubber 誤傷合法字串（純 hex 等） | 回報；暫時解法：傳 message 前把長 hex 縮短 |
| macOS GUI 啟動的 Claude 收不到推播 | env 沒繼承 | 從 terminal 開 Claude，或用 `launchctl setenv` |
| 推播太多 / 重複 | 規則沒設 throttle | 在吵的規則加 `"throttle_seconds": 300` |

檢查失敗 log：
```bash
tail -n 20 ~/.claude-workbench/logs/notify-failures.log
```
重置 throttle 狀態（測試後清乾淨用）：
```bash
rm ~/.claude-workbench/state/notify-throttle.json
```

---

## 10. 解除安裝

```
> /plugin uninstall notify@claude-workbench
```

會留下：
- `~/.claude-workbench/notify-config.json`（你的 config）。
- `~/.claude-workbench/bin/workbench-notify`（symlink，現在是 dangling）。
- `~/.claude-workbench/logs/notify-failures.log`。

要完全清乾淨：
```bash
rm -f ~/.claude-workbench/notify-config.json
rm -f ~/.claude-workbench/bin/workbench-notify
```
環境變數（`PUSHOVER_USER_KEY`、`PUSHOVER_APP_TOKEN`）自己決定要留在 shell rc 還是移掉。

---

## 11. 下一步

- 加裝 `kanban`（如果還沒）：[`kanban_quickstart_zhtw.md`](./kanban_quickstart_zhtw.md)。兩個都裝後，任務狀態轉換會自動推播。
- 加裝 `docsync`：[`docsync_quickstart_zhtw.md`](./docsync_quickstart_zhtw.md)。當 `enforcement=block` 時，docsync 會擋 `/kanban:done`，被擋的轉換會透過這個 plugin 推播。
- 看 [`SPEC.md §8.8`](./SPEC.md) 理解 kanban + notify +（未來的）memory + docsync 全裝時的端到端流程。
