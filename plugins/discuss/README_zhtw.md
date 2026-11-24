# discuss

*[English](./README.md)*

跟 agent **一起**討論一個檔,瀏覽器和終端機同時開著。`/discuss` 在
[porthole](https://github.com/kirinchen/porthole) 打開那個檔(markdown 編輯器 + Mermaid / D2 /
Excalidraw 圖形編輯),旁邊的對話就是**這個 Claude Code session**。取代 `draw`。

## 安裝

```
/plugin marketplace add kirinchen/claude-workbench
/plugin install discuss@claude-workbench
```

需要 `python3`,以及同一台機器上**跑著的 porthole**:

```bash
git clone https://github.com/kirinchen/porthole && cd porthole
cp .env.example .env      # PORTHOLE_BASE = 放各個 repo 的那一層目錄
npm install && npm run install:all && npm run prod
```

`/discuss` 從 porthole 啟動時寫的 `~/.local/state/porthole/server.json` 找位址,再試
`http://127.0.0.1:4321`;環境變數 `PORTHOLE_URL` 優先。執行 `/discuss` 的目錄要在 `PORTHOLE_BASE` 底下。
(`node` 只用來摘要 Excalidraw 圖。)

## 用法

| 指令 | 作用 |
|---|---|
| `/discuss` | 建一個 `doc/discuss/discuss-<時間>.md` 並在 porthole 打開。 |
| `/discuss <檔案>` | 打開那個檔(不存在的 `.md` 會建立)和它的對話。 |
| `/discuss <想討論的事>` | 建 `doc/discuss/<短檔名>.md`(明顯在講某個既有的檔就開那個檔),把你的話原文記成第一句,接著回答。 |
| `/discuss <檔案> <想討論的事>` | 打開那個檔,整行記成第一句,接著回答。 |

是哪一種由 agent 看內容判斷。

## 誰聽得到誰

| 在哪裡說 | 終端機 session | 結果 |
|---|---|---|
| 終端機 | 開著 | 那一輪寫進 `doc/chat/<thread>.md`,porthole 幾秒內出現。 |
| porthole | 開著,有 [`hc`](https://herdr.dev/core/) | 打進這個終端機:同一個 agent、同一份記憶,回覆兩邊都有。 |
| porthole | 開著,**沒有 `hc`** | 拒送:**單向**(終端機 → porthole),畫面會講明。 |
| porthole | 已關 | `claude -p --resume <session>`,記得先前的對話。porthole 的對話都帶 `--dangerously-skip-permissions`,這條也是。 |

- **只有一個 agent 回話**:終端機 session 開著時,porthole 不會另開一個。
- **權限對話框由你回答**:終端機停在對話框時 porthole 拒送並說明原因,不會替你按。
- **存檔不會蓋掉對方**:你編輯期間 agent 改了檔,porthole 會提示,直接存會被擋下(409)。

## 怎麼運作

```
/discuss ──> scripts/discuss.py open ──> ~/.local/state/porthole/bindings/<session>.json
                                          (thread ⇄ session ⇄ 終端機)
hooks:UserPromptSubmit / Stop ──> 把對話寫進 doc/chat/<thread>.md ──> porthole 輪詢
      SessionStart / SessionEnd ──> 把綁定標成開著 / 已結束
porthole 送出 ──> 讀綁定 ──> hc send "[porthole] …"  |  claude -p --resume
```

- 綁定刻意不放進 repo:thread 檔從 porthole 就改得到,放那裡等於目標可以被改掉。
- porthole 送來的訊息以 `[porthole] ` 開頭,hook 看到就不再記,不會重複。
- `python3 scripts/discuss.py unbind`(或叫 agent「停止記錄到 porthole」)解除綁定。
  `/clear` 之後是新的 session,不會自動綁。

測試:`python3 -m unittest discover -s plugins/discuss/tests`。
