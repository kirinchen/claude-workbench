# Mentor — `doc/current_state/` Spec

> 擴充 `plugins/mentor/` 的 **development mode**,補上「目前實作狀態」這一層。
> 格式與 [`epic/mentor-plugin-spec.md`](./mentor-plugin-spec.md) 對齊。
>
> **狀態**:spec draft(simplified)。尚未實作。
>
> **設計轉折**:本 spec 經過一次大幅簡化——原版有 Tier A/B/C、auto-generator、staleness check 等多層機制;最終共識是**最小可行紀律**:mentor 只 scaffold 一份 `ARCHITECTURE.md`,其餘文件由 agent 視需要自治建立並維護。

---

## 1. Role

在 mentor 現有的文件階層裡補一層:

| 層級 | 文件 | 講什麼 |
|---|---|---|
| 意圖 / 大藍圖 | `doc/SPEC.md` | 這系統**應該是**什麼(不變的承諾) |
| **現況快照** | `doc/current_state/*` | 這系統**現在長**什麼樣(實作現實) |
| 活動 / 進行中 | `doc/Sprint/<active>.md` + `kanban.json` | 這週在做什麼 |
| 背景知識 | `doc/Wiki/` | 永恆的 how-to / 概念 / reference |
| 決策紀錄 | `doc/Wiki/architecture-decisions/ADR-*.md` | 為什麼做這個選擇 |

**為什麼分開**:SPEC 描述**意圖**,過時是 bug(承諾跟現實脫鉤)。current_state 描述**實作**,本來就會跟 code 一起變動。把這兩層混在 SPEC 裡會讓 SPEC 變得難維護——加實作細節之後,改 code 的人每次都要回頭改 SPEC,大多時候不會做,SPEC 就壞了。

**實證背景**:本 repo 根目錄 `current_state.md` 已存在,README 拿它當賣點(「live implementation snapshot」)。本 spec 是把 user 已經 organically 在用的 pattern formalize 進 mentor framework,讓其他專案也能直接套用。

## 2. Design Philosophy

1. **Opt-in by default** — `/mentor:init` 一定要問,user 不要就完全不發生:不 scaffold、不寫 config、所有 review / hook 都不 nag。
2. **最小種子,agent 自治** — mentor 只 scaffold 一份 `ARCHITECTURE.md`。其他文件(UML、CODEMAP、DATA_MODEL...)**由 agent 視需要自己建**,mentor 不預先列清單、不限制檔名。
3. **規則放在 skill,不在 hook** — 行為紀律寫進 `mentor-workflow/SKILL.md`,讓 agent 內化為工作習慣;而不是用 PreToolUse hook 機械式擋。
4. **No staleness check** — 不引入 `last_verified` frontmatter、不在 `/mentor:review` 做時間警告。紀律靠 SKILL 的「**改 code 時同步改文件**」維持;事後查不會比事前內化有效。
5. **Repo-local** — 放 `doc/current_state/`,跟 code 同 PR review。Wiki 對 agent 不可見,放錯地方就違背設計目的。
6. **Development mode only** — basic mode 不需要這層(個人專案 / 原型 SPEC 就夠)。
7. **Never overwrite** — scaffold 只新建缺的檔,既有檔絕不動。

## 3. Directory Structure

```
doc/
├── SPEC.md
├── current_state/                    ← NEW(opt-in)
│   └── ARCHITECTURE.md               ← mentor 唯一 scaffold 的檔
│       (其他檔由 agent 視需要自己建)
├── Wiki/
├── Epic/
├── Sprint/
└── Issue/
```

`doc/current_state/` 啟用後可能演化成的樣子(範例,**不是 mentor 預先 ship 的**):

```
doc/current_state/
├── ARCHITECTURE.md         ← 種子,mentor scaffold
├── CODEMAP.md              ← agent 第一次 trace 模組依賴時自建
├── UML.md                  ← agent 整理 class 關係時自建
├── DATA_MODEL.md           ← agent 第一次碰 DB schema 時自建
└── ...
```

每個由 agent 自建的檔,agent 也要負責後續維護(見 §6 Rule 2)。

## 4. Frontmatter

每個 current_state 檔案最少需要:

```yaml
---
title: Architecture
owner: null                       # optional,負責 review 的人 / team
---
```

- 沒有 `last_verified` 欄位(已從設計中移除)。
- 不做機器驗證(`mentor-guard.py` 不檢查 current_state 的 frontmatter)。

## 5. `/mentor:init` 整合(MUST ASK)

在 `/mentor:init` Phase 4(integration)之後、Phase 5(first sprint)之前,加一個 Phase 4.5:

```
> Scaffold doc/current_state/?
>   Purpose: snapshot of how the system actually looks now,
>            so agents and new contributors don't have to re-derive
>            it from raw code every session.
>   What ships: doc/current_state/ARCHITECTURE.md (single seed file)
>   What follows: agent will add more files here (UML, CODEMAP, ...)
>                 as needs arise — you don't need to plan them now.
>   [y/N]   ← default N
```

- **User 選 N**(含 timeout / Ctrl-C):skip,什麼都不發生。隨時可用 `/mentor:current-state init` 補。
- **User 選 Y**:
  1. 顯示將建立的檔(就 `ARCHITECTURE.md` 一份)
  2. 確認後 scaffold
  3. 在 `.claude/mentor.yaml` 寫入 `current_state.enabled: true`

`--current-state=yes|no` CLI flag 跳過問題(CI / 自動化用)。

## 6. Agent 行為規則(寫入 `mentor-workflow/SKILL.md`)

只在 `current_state.enabled: true` 時對 agent 生效。**兩條規則**:

### Rule 1 — 改 code 同步改 ARCHITECTURE
> 當你的 code 變更超出 `doc/current_state/ARCHITECTURE.md` 目前描述的範圍(新元件、移除元件、互動方式改變、技術選型替換)時,**必須在同個 change set 內更新 ARCHITECTURE.md**。
>
> 判斷「超出範圍」的標準:如果一個沒讀過你 PR 的人,讀 ARCHITECTURE.md 之後對系統的理解會是錯的——那就是超出範圍。typo / 重新命名變數 / 內部 refactor **不算**;新增 API 端點 / 換掉 db / 拆出新 service **算**。

### Rule 2 — 自建文件 = 自承諾維護
> 當你發現自己希望有(但不存在)某種上下文文件(例:UML、CODEMAP、DATA_MODEL),**直接在 `doc/current_state/` 下建立**,不必先問 user。檔名自由(camelCase / SNAKE_CASE / 中文都可),只要清楚表達內容。
>
> **但**:你建的檔 = 你 commit 自己未來要維護它。Rule 1 的同步義務同樣套用。**不要憑空 scaffold 你不打算填的 stub**——空殼文件比沒有文件更糟。

## 7. `.claude/mentor.yaml` 新增區塊

```yaml
current_state:
  enabled: false                    # user 同意 scaffold 時才變 true
  path: doc/current_state/          # 可覆寫
```

就這麼小。沒有 `staleness_days`、沒有 `tier_c_enabled`、沒有 `bootstrap_include`(預設行為固定見 §8)、沒有 `template_choice`。

`enabled: false` 是預設——確保「user 沒說要就什麼都不發生」。

## 8. SessionStart bootstrap 擴充

現有 `mentor-bootstrap.py` 注入:
- `doc/SPEC.md`
- active sprint

新增(只在 `current_state.enabled: true` 時):
- **`doc/current_state/ARCHITECTURE.md` 一份**(無論資料夾下還有多少其他檔)

**為什麼只讀一份**:agent 自建的 UML / CODEMAP 等,agent 自己會記得 Read on demand,不該每次 session 都全塞 context。SessionStart bootstrap 的目的是給 agent「最小可動」的心智模型——`ARCHITECTURE.md` 是入口,其他是延伸閱讀。

## 9. 新增 CLI / 指令

### v0.1 必備

- `/mentor:current-state init` — 讓 user 之後補 scaffold(當初 init 時說 N 的路徑)。互動同 §5。

### 不做(刻意的)

- `workbench-mentor current-state list / refresh / validate` — 沒有 staleness check 之後沒實際用途。
- `/mentor:refresh-current-state` — 同上。
- 任何 auto-generator(lockfile-to-tech-stack、tree-walker)— 簡化設計刪掉。

## 10. 和其他元件的關係

| 元件 | 互動 |
|---|---|
| `doc/SPEC.md` | SPEC 是意圖、`ARCHITECTURE.md` 是實作。SPEC §3 的 Architecture sketch 仍可保留(高層、不變的 invariant);詳細實作放 `current_state/ARCHITECTURE.md`。SPEC 獨立可讀,不**強制**引用 current_state。 |
| ADR | ADR `accepted` 後,Rule 1 自然會推 agent 更新 `ARCHITECTURE.md`(決策 → 實作改 → 同步文件)。不需要額外 hook 強迫。 |
| kanban | 無直接耦合。Issue 的 acceptance criteria **可以**引用 current_state 檔(例:「更新 `current_state/CODEMAP.md` 的 `auth/` 區塊」),但 mentor 不強制。 |
| Wiki | 清楚分工:Wiki = **永恆**(概念、how-to);current_state = **快照**(實作現況)。如果一個概念穩到不會變,從 current_state 搬去 Wiki。 |
| `mentor-guard.py` | **完全不擋** current_state 檔——guard 只檢查 Epic/Sprint/Issue/ADR 的 frontmatter。current_state 的紀律靠 SKILL 規則,不靠 hook。 |
| `mentor-finalcheck.py` | **不主動掃** current_state——同上,行為層交給 SKILL。 |

## 11. 明確不做

- **不做 staleness 檢查**(`last_verified` / `/mentor:review` 時間警告)— 簡化共識刪掉。
- **不預先列檔案 tier / preset**(原 Tier A/B/C 全砍)— agent 自己決定要哪些。
- **不做 auto-generator**(DIRECTORY_TREE / TECH_STACK / EXTERNAL_DEPENDENCIES 自動產)— 手寫紀律 + agent 自治足夠 v0.1。
- **不自動 sync 到 Confluence / Notion** — 公司要的話自己接 CI(例:markdown-to-confluence)。
- **不做 SPEC drift detector**(偵測 SPEC §3 vs ARCHITECTURE.md 發散)— 太深,不在範圍。
- **不進 basic mode** — basic 選擇「最精簡」是刻意的。
- **不限制 agent 自建檔名 / 檔數** — 過早規範會殺 Rule 2 的彈性。

## 12. 實作 Phase 拆分

**Phase A(MVP,估約 80~120 行實作)**
- `/mentor:init` 的 Phase 4.5 問題 + 分支邏輯
- `frameworks/development/templates/current_state/ARCHITECTURE.md` template 一份
- `.claude/mentor.yaml` 的 `current_state:` 區塊讀寫
- `mentor-bootstrap.py` 擴充:`current_state.enabled: true` 時讀 `ARCHITECTURE.md`
- `/mentor:current-state init` slash command
- `mentor-workflow/SKILL.md` 加 Rule 1 + Rule 2 段落

**Phase B(未來,只有需求出現才做)**
- ADR-accepted 時的 hook 提示(現在靠 Rule 1 自然驅動,不需要)
- GitHub Action template:PR diff 動 code 時提示「ARCHITECTURE.md 是否需要同步」
- 如果有人實際反映「agent 沒在守 Rule 1」,再考慮 PostToolUse 軟提醒

## 13. 對應的 SOLID 風險

參考 [`epic/mentor-solid-refactor.md`](./mentor-solid-refactor.md):

- 加 `ARCHITECTURE.md` template **不**增加 OCP 違規——就一個檔,沒有「新文件類型」要 plumb 到 5 個地方的問題。
- SKILL 規則寫死在 `SKILL.md` markdown 裡——這算紀律宣告,不算 code 分支,不踩任何 SOLID 違規。
- `current_state.enabled` config 進 `MentorConfig`——加一個 boolean 不破壞 ISP 太多;但下次 `current_state.*` 再加欄位時,要記得 backlog #4(MentorConfig 全曝光的 ISP 違規)還沒清。

---

*End of mentor-current-state spec(simplified)— 待 review 後合併為 `mentor-plugin-spec.md` 的新章節,或獨立維護。*
