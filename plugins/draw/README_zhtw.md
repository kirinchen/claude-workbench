# draw

*[English](./README.md)*

**跟 agent 一起畫圖。** `/draw` 在瀏覽器開一個小編輯器;圖以純文字存進 repo ——
最好直接寫在它所屬的 markdown 文件裡 —— agent 讀得懂、能給回饋、能直接改,
你重新整理就看到它的改動。

編輯器抽自 porthole 的 markdown 編輯器,不需要裝 porthole。

## 安裝

```
/plugin marketplace add kirinchen/claude-workbench
/plugin install draw@claude-workbench
```

需要 `PATH` 上有 Node 18+。

## 指令

| 指令 | 做什麼 |
|---|---|
| `/draw` | 首頁:這個 repo 已有的圖(點了直接開)+ 新增圖型清單 |
| `/draw <檔案>` | 直接開檔案裡的圖(含圖區塊的 `.md`,或 `.mmd` / `.excalidraw` / `.d2`) |

畫完直接問 agent:「看一下我的圖」、「把 Login 接到 API」。plugin 附的 `draw` skill
會教它怎麼讀、怎麼改各種格式。

## 總覽

首頁最上面是**這個 repo 已有的圖**(目前目錄的 git 根;用 `git ls-files`,被 ignore 的不列):
每個含圖區塊的 `.md`、每個 `.mmd` / `.excalidraw` / `.d2`,新的在前,標出幾張、各是什麼圖型。
點檔名或單張圖直接開。

## 從別台機器開

預設只綁 `127.0.0.1`。要從別台(例如筆電走 Tailscale)開,讓 server 也綁這台的位址:

```bash
/draw --host 100.x.y.z          # 這次
# 或固定寫進 ~/.claude/settings.json:  "env": { "DRAW_HOST": "100.x.y.z" }
```

`/draw` 會多印一個「別台機器用」的網址,帶 `&t=<token>`:不是本機的瀏覽器要有它才載得到頁面,
API 每次一樣檢查 token。`Host` 頭只收 `127.0.0.1`、`localhost`、綁的那個位址;
MagicDNS 名稱之類用 `DRAW_ALLOWED_HOSTS=名1,名2` 加。

## 圖型

跟 porthole「插入圖表」選單同一份,每種都有 GUI 編輯器:

| 圖型 | 存成 |
|---|---|
| Flowchart、State、ERD、Class、Sequence、Architecture、Mind map | Mermaid |
| D2 架構圖(容器對容器的連線) | D2 —— 要有 [`d2`](https://d2lang.com) 指令,沒有就反灰 |
| Excalidraw 白板 | Excalidraw JSON |

## 圖存在哪

選完圖型會問:

| 選項 | 結果 |
|---|---|
| **一次性** | 只存在 draw server 記憶體,重開就沒了。agent 一樣讀得到(`mem:<id>`) |
| **存在目前目錄** | 給名稱 → `<名稱>.md`(或 `.mmd` / `.excalidraw` / `.d2`) |
| **存在指定的地方** | 相對路徑、絕對路徑或 `~/…`。既有 `.md` → 圖接在文件尾端 |

存檔的兩種選項可再選 **Markdown 內嵌**(預設;圖以 ```` ```mermaid ```` 等區塊寫在文件裡,
Mermaid 在 GitHub 上也會顯示)或 **原生單檔**。

## 跟 agent 協作

- 從瀏覽器存檔只改那一個區塊,`.md` 其他內容不動
- agent 改了檔 → 頁面約 2 秒內跳出「被別人改過了」提示 → 按 **重新載入**
- 沒重新載入就存檔 → server 拒絕(409),問過你才覆蓋

## 運作方式

```
/draw ──> scripts/draw.mjs open ──> server/server.mjs(127.0.0.1:7391,零依賴)
                                     ├── 提供 dist/(build 好的 React 編輯器)
                                     ├── /api/file    讀 / 新建 / 寫回圖區塊
                                     ├── /api/memory  一次性的圖
                                     └── /api/d2/render(呼叫 d2)
agent ──> scripts/draw.mjs summary|get|list|put
```

- 一台機器一個 server,綁 `127.0.0.1`(有設 `DRAW_HOST` 再加那個位址)。每次啟動產生 token,
  每個 API 都要帶,`Host` 頭也會檢查 —— 其他網站寫不了你的檔。token 只發給本機連線,
  或網址帶了 `?t=<token>` 的頁面。
- 狀態檔 `~/.claude-workbench/draw/server.json`,log 在同目錄 `server.log`。
- Excalidraw 手寫字型走它預設的 CDN;離線時退回系統字型。

需要 **Node 18+**。前端已 build 在 `dist/`;要重 build:
`cd plugins/draw/web && npm install && npm run build`。
