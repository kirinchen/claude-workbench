# chat

Claude Code 的輕量對話串（thread）。開一個 chat，之後每一輪對話都會被記錄到一個
markdown 檔，可以重讀、總結、隨時續聊。

`chat` **只負責記錄** —— 它不會改變 Claude 的行為。「chat 模式」純粹是一個綁定
單一 session 的記錄標記。

## 指令

| 指令 | 作用 |
|---|---|
| `/chat:new [name]` | 開一個對話串，把這個 session 記錄到 `doc/chat/{name}.md`。 |
| `/chat:exit` | 停止記錄（對話串檔案會保留）。 |
| `/chat:list` | 列出已存的對話串（最新在前），標出正在記錄的那一個。 |
| `/chat:note [name]` | 把目前的對話串總結成 `doc/note/{name}.md`。 |
| `/chat:resume <name\|N\|關鍵字>` | 重新開啟一個已存的對話串並繼續記錄。 |

## 運作方式

```
/chat:new ──> doc/chat/{name}.md                 (對話串，會進 git)
          └─> .claude/chat/sessions/{id}.json     (session 狀態，git ignore)

每一輪 ──> Stop hook ──> chat-logger.py ──> 接到 doc/chat/{name}.md 後面
```

- `Stop` hook 在每一輪結束後，把使用者訊息與 Claude 的文字回覆接進對話串。
  thinking、工具呼叫、系統雜訊都會被過濾掉。
- chat 模式**綁定單一 session**：Claude Code session 結束時（`SessionEnd`
  hook）狀態就會被清掉。要在新的 session 接續，請用 `/chat:resume`。
- `/chat:new` 這一輪本身不會被記錄 —— 記錄從你的下一則訊息開始。

## 檔案

| 路徑 | 進 git | 用途 |
|---|---|---|
| `doc/chat/{name}.md` | 是 | 對話記錄。 |
| `doc/note/{name}.md` | 是 | `/chat:note` 產生的總結。 |
| `.claude/chat/sessions/*.json` | 否 | 每個 session 的執行期狀態。 |

## resume 的查找規則

`/chat:resume` 依序解析參數：完全相符的對話串名稱 → 數字（第 N 新的對話串）→
對檔名做不分大小寫的關鍵字比對。

## 安裝

屬於 [claude-workbench](https://github.com/kirin/claude-workbench) marketplace。
啟用 `chat` plugin 即可 —— 不需設定、不需 token、沒有相依套件。
