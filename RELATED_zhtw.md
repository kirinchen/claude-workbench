# 相關專案

*[English](./RELATED.md)*

> **你想找的是…**
> - 管理 Claude Code 安裝跟 MCP server 的 GUI？→ [Norman-else/claude-workbench](https://github.com/Norman-else/claude-workbench)（不同專案，名字撞純屬巧合）
> - Session 級別的生產力 metrics + CLAUDE.md 自動改進？→ [blackwell-systems/claudewatch](https://github.com/blackwell-systems/claudewatch)
> - 70+ 個領域專屬的 Claude Code skill？→ [wshobson/agents](https://github.com/wshobson/agents)
> - tmux + cron 跑長時間 agent 的框架？→ [mikeypotter/claude-agent-os](https://github.com/mikeypotter/claude-agent-os)
> - 角色制 subagent 定義（analyst、architect、developer…）？→ [valllabh/claude-agents](https://github.com/valllabh/claude-agents) · [iannuttall/claude-agents](https://github.com/iannuttall/claude-agents)
>
> **以上都不是？留下來看。** 這個 repo 是 **跨 session 工作流基礎設施的 plugin 家族**：kanban 狀態、推播通知、mentor onboarding、RAG 記憶。

## 一句話定位

Claude Code 生態已經有不少工具，但大多落在跟 claude-workbench **不同的範疇**。這份文件存在的兩個理由：

1. **省你時間** — 如果你要的是上面其中一個，點過去就好，不用看我們其他文件。
2. **誠實定位** — 當有人搜「Claude Code workflow」、「Claude Code AgentOps」、「Claude Code plugin」，會跑出多個專案。這裡講清楚誰做什麼。

## 五個範疇

| 範疇 | 動詞 | 代表專案 |
|---|---|---|
| **Skill / Subagent** | 「Claude 會做什麼」 | wshobson/agents、valllabh/claude-agents、iannuttall/claude-agents |
| **多 agent runtime** | 「Claude 怎麼跑得久」 | mikeypotter/claude-agent-os |
| **Session 分析** | 「過去做得多好」 | blackwell-systems/claudewatch |
| **GUI / Launcher** | 「怎麼設定 Claude Code」 | Norman-else/claude-workbench |
| **工作流基礎設施** | 「session 之間什麼狀態被保留、人跟 Claude 怎麼在上面協作」 | **claude-workbench（這個 repo）** |

前四個範疇都已經有不少作品。最後一個 — **讓 Claude Code 從「一連串獨立 session」變成「真正可用的工作環境」的管路** — 就是這個 repo 在做的事。

## 跟各專案的差異

### vs. [Norman-else/claude-workbench](https://github.com/Norman-else/claude-workbench)

**他的工具**：管理 Claude Code 安裝、plugin、MCP server 的桌面 GUI。
**這個 repo**：跑在 Claude Code **裡面**的 plugin 家族。

名字撞是巧合 — 不同問題範疇，零功能衝突。你可以用 Norman-else 的 GUI 來裝跟切換這個 repo 的 plugin。我們考慮過改名，但決定保留：
- 功能零重疊，
- 「workbench」描述「plugin 家族」這個型態比其他名字準，
- GitHub 雖然會自動 redirect，但生態系既有的引用（既有 Markdown、blog 文、搜尋結果片段）不會跟著改。

### vs. [blackwell-systems/claudewatch](https://github.com/blackwell-systems/claudewatch)

**他的工具**：掃描既往的 Claude Code session、算生產力 metrics、自動產出 CLAUDE.md 的改進 patch。
**這個 repo**：規範 Claude session 中**該怎麼做事**（mentor），以及讓狀態跨 session 持續（kanban、memory）。

claudewatch 在 session **之後**運作；claude-workbench 在 session **之前跟之中**運作。具體互補：

- 用 mentor + kanban 結構化你的工作流。
- 一個月後，跑 claudewatch 的 `metrics` 看結構化有沒有真的有幫助。
- claudewatch 標出某個 SKILL.md 並沒讓 friction 下降。
- 改該 skill，再量測一次。

如果你在意「AI 工作流量化」這件事，**兩個都裝**。

### vs. [wshobson/agents](https://github.com/wshobson/agents)

**他的 pack**：70+ 個領域專屬的 Claude Code plugin（testing、security、data、frontend…）。
**這個 repo**：四個泛用 plugin（kanban、notify、mentor、memory），不認識也不在乎你的領域。

不同軸：
- wshobson 的 plugin 是 **垂直**的 — 挑符合你 stack 的就好。
- claude-workbench 是 **水平**的 — 裝一次，適用所有工作。

兩個都裝沒衝突。在 mentor 治理、kanban 追蹤的 task 裡跑 wshobson 的 security skill，正常運作。

### vs. [mikeypotter/claude-agent-os](https://github.com/mikeypotter/claude-agent-os)

**他的框架**：tmux + cron 編排，讓 Claude 能 headless 跑好幾個小時。
**這個 repo**：不嘗試讓 agent 一直活著 — 處理的是 session **之間的縫隙**（狀態、通知、記憶）。

如果你在跑 8 小時的 agent session，claude-agent-os 解的是我們不解的問題。我們的 `notify` plugin 處理「agent 需要人類介入」這個邊界；他的框架處理「agent 連續跑數小時」。可同時存在。

### vs. [valllabh/claude-agents](https://github.com/valllabh/claude-agents) · [iannuttall/claude-agents](https://github.com/iannuttall/claude-agents)

**他們的 pack**：精選的 subagent 定義 — 角色制（analyst、architect、developer…）或個人收藏。
**這個 repo**：不定義 agent；定義 **agent 工作的工作環境**。

Subagent 定義是有用的 primitive，但沒解決「session 之間發生什麼」這個 gap。搭配這個 repo 的 `mentor` plugin 來治理那些 agent 的**工作方式**，組合起來剛好。

## 我們獨佔的位置

claude-workbench 是我目前知道的、唯一同時做這幾件事的專案：

- 用單一事實來源（`kanban.json`）跨 session 持久化 task 狀態，且人跟 AI 都能編輯。
- agent 需要你回應時推到你的手機（目前 Pushover，未來 ntfy / Slack）— 你可以放心讓 headless session 跑。
- 把 framework 階層（Epic → Sprint → Issue → ADR）寫進 plugin 而不是你的 CLAUDE.md，並用 hook 強制結構合規。
- 互相組合 — kanban × notify × mentor × memory 互相偵測對方存在、缺一可優雅降級。

如果你發現有別的專案**作為同一介面**做這些事，開 issue，我會加進這份名單。

## 給上述專案維護者的話

如果你的專案在這份名單上、想調整描述、調整比較方式、或換到不同範疇，**請開 issue**。目的是幫使用者導航，不是誤述你的作品。
