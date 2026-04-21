# notify

*[English](./README.md)*

[claude-workbench](../../README_zhtw.md) 全家族的一員。完整設計見 [`SPEC.md §4`](../../SPEC.md)。

當 Claude Code 需要你注意時，透過外部通道（目前：**Pushover**）找到你——避免「AI 卡住等回應、人卻在 AFK」的死結。

## 會觸發推播的事件

Claude Code 會對四種事件發出 `Notification` hook，每一種都可路由：

| 事件 | 意思 | 預設優先度 |
|---|---|---|
| `permission_prompt` | Claude 要工具權限 | high |
| `elicitation_dialog` | Claude 要問使用者 | high |
| `idle_prompt` | Claude 閒置等輸入 | normal（節流 1 / 5 分鐘） |
| `auth_success` | 認證流程完成 | low |

## 安裝

```bash
> /plugin install notify@claude-workbench
> /notify:setup         # 互動式 Pushover 設定（問 token）
> /notify:test          # 送一則測試推播
```

`/notify:setup` 也會把 `workbench-notify` CLI link 到 `~/.claude-workbench/bin/`，讓相鄰 plugin（`kanban`、`docsync`、`memory`）透過 capability detection 發現它。

確認 `~/.claude-workbench/bin/` 在 PATH 上：

```bash
export PATH="$HOME/.claude-workbench/bin:$PATH"
```

## Config

放在 `~/.claude-workbench/notify-config.json`（專案之外，token 不會漏進 git）。Secret 用 env var 展開：

```json
{
  "schema_version": 1,
  "default_provider": "pushover",
  "providers": {
    "pushover": {
      "enabled": true,
      "user_key": "${PUSHOVER_USER_KEY}",
      "app_token": "${PUSHOVER_APP_TOKEN}"
    }
  },
  "rules": [
    { "match": { "notification_type": "permission_prompt" },  "providers": ["pushover"], "priority":  1 },
    { "match": { "notification_type": "elicitation_dialog" }, "providers": ["pushover"], "priority":  1 },
    { "match": { "notification_type": "idle_prompt" },        "providers": ["pushover"], "priority": -1, "throttle_seconds": 300 },
    { "match": { "notification_type": "auth_success" },       "providers": ["pushover"], "priority": -2 }
  ]
}
```

在 shell rc 或 `.env` + direnv 裡設 env var——**絕不要**直接寫死在 JSON 裡。

## CLI

`workbench-notify` 是給相鄰 plugin 用的穩定整合介面：

```bash
workbench-notify \
  --title "Kanban" \
  --message "task-042 needs your decision" \
  --priority high
```

健康檢查（相鄰 plugin 做 capability detection 用）：

```bash
workbench-notify --health   # 當 config 可讀且至少一個 provider 啟用時 exit 0
```

## Slash 指令

| 指令 | 目的 |
|---|---|
| `/notify:setup` | 互動式 Pushover 設定 + CLI 安裝 |
| `/notify:test` | 送測試推播 |
| `/notify:config` | 顯示或告知怎麼編輯 config |

## 推播內容

訊息在送出前會過 scrubber 清掉 token 形態子字串（`sk-…`、`ghp_…`、`xoxb-…`、JWT、AWS key、純 hex ≥32）。失敗寫入 `~/.claude-workbench/logs/notify-failures.log`——hook 絕不擋住 Claude。

## v0.1.0 不包含

- ntfy / Slack / Telegram provider（Phase 8+）
- 專案級別 override
- 比簡易時窗節流更複雜的 rate-limit 計算
