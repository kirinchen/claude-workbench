# mentor

*[English](./README.md)*

[claude-workbench](../../README_zhtw.md) 全家族的一員——**dev profile**。完整設計見 [`epic/mentor-plugin-spec.md`](../../epic/mentor-plugin-spec.md)。

**Mentor 是你專案從來沒有過的 onboarding 顧問。** 它告訴 Claude（和任何人類貢獻者）**先讀什麼**、**填哪些 template**、**用什麼順序工作**、**決定要記錄在哪裡**。裝完之後，你的 repo 不只是多一個 doc 資料夾——是長出了一套工作紀律。

取代舊的 `docsync` plugin——範圍更廣，由 framework 驅動。

## 兩種模式，挑一種

跑 `/mentor:init` 然後選：

| 模式 | 適合 | 文件階層 |
|---|---|---|
| **basic** | 個人專案、原型、工具、維護期 | `doc/SPEC.md` + tasks |
| **development** | 多 feature、規劃週期、多 agent 協作 | `SPEC + Wiki + Epic + Sprint + Issue` + tasks |

basic 是刻意設計成最精簡——等之後出現規劃壓力時再升級到 `development`。

## 安裝

```
> /plugin install mentor@claude-workbench
> /mentor:init            # 互動式——scan、選模式、產生結構
```

## Slash 指令（v0.1.0 MVP）

| 指令 | 目的 |
|---|---|
| `/mentor:init` | 互動式選模式 + 產生結構 |
| `/mentor:status` | 目前模式、active sprint、open issues |
| `/mentor:new` `<epic\|sprint\|issue\|adr>` | 從該模式的 template 產生新文件 |
| `/mentor:review` | 合規檢查——missing docs、orphan issues、template drift |
| `/mentor:migrate-from-docsync` | 讀 `.claude/docsync.yaml` → 寫 `.claude/mentor.yaml` |

延後到 v0.2：`/mentor:sprint-start`、`/mentor:sprint-end`（sprint 生命週期 + 自動 retro）。

## Hooks

- **SessionStart**——把 bootstrap docs + active sprint pointer 透過 `additionalContext` 注入。
- **PreToolUse**（Edit / Write / MultiEdit）——警告缺 frontmatter 或違反 template 結構的文件。
- **Stop**——session 結束時的合規摘要。

## CLI

`workbench-mentor`——給相鄰 plugin 用的穩定整合介面：

```bash
workbench-mentor --health
workbench-mentor config --format json
workbench-mentor active-sprint --format json
workbench-mentor trace task-042 --format json       # task → issue → epic
workbench-mentor review --format json               # 乾淨 exit 0；有違規 exit 2
```

## Kanban fallback

- 有裝 kanban → `kanban.json` 是 task state 的擁有者；mentor 讀 Issue frontmatter 裡的 `tasks: [...]` 來 trace
- 沒裝 kanban → mentor 寫 `doc/task.md` 當作最簡單的任務清單

兩者**絕不共存**。

## 相鄰 plugin 整合

全部 opt-in，透過 `.claude/mentor.yaml`：

- **mentor × kanban** — 新 Issue 自動建立 kanban task entry；可選的 Acceptance Criteria DONE gate
- **mentor × memory** — Sprint retro + ADR 存成 memory entry
- **mentor × notify** — Sprint 結束 / Epic 完成推播

## 檔案結構

```
plugins/mentor/
├── .claude-plugin/plugin.json
├── skills/mentor-workflow/
│   ├── SKILL.md
│   └── references/
│       ├── basic-mode-guide.md
│       ├── development-mode-guide.md
│       └── task-pickup-workflow.md
├── commands/{init,status,new,review,migrate-from-docsync}.md
├── hooks/hooks.json
├── scripts/
│   ├── framework_engine.py        # config loader + mode resolution
│   ├── mentor-bootstrap.py        # SessionStart
│   ├── mentor-guard.py            # PreToolUse
│   ├── mentor-finalcheck.py       # Stop
│   ├── workbench-mentor.py        # CLI
│   ├── workbench-mentor           # bash shim
│   └── install-cli.sh
├── frameworks/
│   ├── basic/     — framework.yaml + SPEC template
│   └── development/ — framework.yaml + SPEC/Wiki/Epic/Sprint/Issue/ADR templates
└── templates/mentor.example.yaml
```

## v0.1.0 不包含

- `/mentor:sprint-start`、`/mentor:sprint-end`（sprint 生命週期）
- `mentor-checkpoint.py` PostToolUse hook（智能觸發）
- 完整的 retro 自動化（Stop hook 目前只持久化已完成的 retro，不會 draft）
- 自訂 framework template（`templates.source: custom` 已在 schema 內，但 `/mentor:init` v0.1.0 還沒實作這條路徑）
