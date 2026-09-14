# tmux

在 Claude Code 裡面操作你**其他**的 tmux session：列出來、看它們在幹嘛、把訊息
組好放進某個 session 的輸入框，確定要送再送。

除了 `tmux` CLI 跟 Python 3 標準庫之外零依賴。不會在目標 session 裡裝任何東西
—— 這個 plugin 只做兩件事：讀 pane、送按鍵，跟你自己手動做的一模一樣。

## 指令

| 指令 | 作用 |
|---|---|
| `/tmux:ls` | 列出所有 session，附上狀態（閒 / 忙 / 有佇列 / 卡在對話框）與最後一行輸出。 |
| `/tmux:review <session> [你想知道什麼]` | capture 畫面（預設往回 200 行）並依敘述分析，開頭一定先講它現在忙、閒、還是有排隊訊息。 |
| `/tmux:draft <session> <要說什麼>` | 把組好的話放進目標的輸入框然後**停手** —— 不按 Enter。框裡已有草稿就改寫它。 |
| `/tmux:send <session> <要說什麼>` | 同上，但會按 Enter，送完重新 capture 確認是送出了還是排進佇列。 |

session 名稱**沒有自動補全**。先 `/tmux:ls`，從清單裡抄一個名字再打。

## 運作方式

```
/tmux:ls      ──> tmux-sessions.sh ──┐
/tmux:review  ──> tmux-capture.sh  ──┼──> tmux-state.py ──> {status, draft, summary}
/tmux:draft   ──┐                    │
/tmux:send    ──┴> tmux-input.sh   ──┘
```

所有 deterministic 的事都在 `scripts/`；指令的 markdown 只負責呼叫它們、組稿、
分析。這個切法是刻意的 —— 畫面解析跟按鍵時序不應該每次呼叫都重推一遍。

| Script | 用途 |
|---|---|
| `scripts/tmux-state.py` | 把 pane 解析成 `{ui, status, busy, queued, draft, ghost, summary}`。用 `-e` capture 並讀 SGR，因為真草稿跟淡色 placeholder 只差在樣式。唯一的事實來源。 |
| `scripts/tmux-capture.sh` | `<session> [-S N]` —— 輸出 scrollback + 畫面，空行已過濾。 |
| `scripts/tmux-input.sh` | `<session> --get\|--set\|--send\|--append\|--clear` —— 唯一會打字的東西。 |
| `scripts/tmux-sessions.sh` | `[--json]` —— `/tmux:ls` 那張表。 |

目標通常是 Claude Code TUI，但沒有任何地方假設它一定是。純 shell session 會回報
`ui: "plain"`，`ls`、`review`、`send` 照樣能用。

## 已知的坑

以下每一條都是實際踩到的，也就是這些 script 長成這樣的原因。

**1 —— 淡色 placeholder 長得跟草稿一模一樣。**
輸入框空的時候，Claude Code 會把你先前放棄的輸入用淡色（`ESC[2m`）重新顯示出來。
在普通的 `capture-pane` 裡，它跟真的未送出草稿是 byte 級一致 —— 同樣的位置、同樣
的字。把它當草稿處理兩邊都會出事：要嘛「改寫」一份根本不存在的草稿，要嘛對一個
早就空了的框無限迴圈清空。

所以 `tmux-state.py` 改用 `-e` capture 並追蹤 SGR 的 faint 旗標。淡色內容一律回報
為 `ghost`，絕不會是 `draft`，`has_draft` 維持 false；`/tmux:ls` 標成 `~` 而不是
`yes`。往這種框打字會直接覆蓋掉 placeholder，不需要先清。

**2 —— 現有草稿在**最後一個** `❯` 之後，但光這樣還不夠。**
Claude Code 在對話區也會用 `❯` 印過去的使用者發言，所以要取最後一個。可是對話框
（`/model`、權限確認）的選單列也長得像 `❯ 1. Default`，而且那時候根本沒有輸入框。
所以 `tmux-state.py` 改成錨定**邊框成對**：最後兩條夾住某個 `❯` 行的 `────`。
沒有成對邊框，就沒有輸入框。

**3 —— `C-u` 可以用，但它清的是一個「視覺行」，不是整個緩衝區。**
它確實能清 Claude Code 的輸入框（而且會顯示 `Ctrl+Y to paste deleted text`，
代表救得回來）。但有兩個陷阱：

- 草稿如果折行成兩列，一次 `C-u` 只會清掉後面那列，第一列留著。
- `C-u` 是「從行首刪到游標」。游標停在行中間的話，右邊的字會活下來。

所以清空的做法是 `End` 再 `C-u`，**迴圈到 `has_draft` 變 false 為止**（上限 40
輪，超過就 fail loud，而不是硬打在殘字上面）。不需要退而求其次用 Backspace×N，
也不必只能 append。

**4 —— 文字跟 Enter 要分開送。**
`send-keys -l "<文字>"` 打中文沒問題，不會吃字。但把 Enter 併進同一次呼叫，偶爾
會吃掉文字尾巴。所以 script 一律是：`-l` 文字 → `sleep 0.3` → `send-keys Enter`。
機器比較慢的話用 `TMUX_PLUGIN_TYPE_SETTLE` 調。

**5 —— 目標在忙的時候，訊息是排隊，不是被處理。**
對正在跑的 session 送訊息，它會進佇列；輸入框顯示
`Press up to edit queued messages`，footer 持續是 `esc to interrupt`。
`/tmux:review` 跟 `/tmux:send` 都會把這個當成獨立狀態（`queued` / `busy+queued`）
回報，而不是宣稱已送達。那句 placeholder 也刻意**不會**被當成草稿內容讀回來。

**6 —— 全程沒有 `ps | grep`。**
process list 的 pattern 會匹配到 script 自己的命令列，產生幽靈結果。這個 plugin
回報的每一件事都來自 `tmux` 本身。

**7 —— session 不存在就 fail loud。**
`tmux-state.py`、`tmux-capture.sh`、`tmux-input.sh` 都是 exit 2 並列出現有的
session，不會默默對空氣操作。

**8 —— 多行草稿讀回來是近似值。**
pane capture 無法分辨「折行」跟「真的換行」，所以折行草稿的 `draft` 是近似讀取，
不是 byte 精確的來回。它的用途是**改寫前先讀懂現有草稿**。寫入端則是精確的：
`--set` 直接拒絕內含換行的文字，因為字面換行會提早送出。

**9 —— 拒絕對自己打字。**
如果 `$TMUX` 顯示目標就是你正在跑的那個 session，`tmux-input.sh` 會停下來。
真的要的話加 `--allow-self`。

## 安裝

```
/plugin marketplace add kirin/claude-workbench
/plugin install tmux@claude-workbench
```

需要 `PATH` 上有 `tmux` 且 tmux server 正在跑。沒有設定檔。
