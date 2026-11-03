/**
 * 可畫的圖型清單 —— 與 porthole 編輯器「空白行右鍵 → 插入圖表」同一份(MarkdownEditor 的 GUI_SAMPLES),
 * 去掉表格(不是圖)。code 是起手範例(不含 fence)。
 */
export type Kind = 'mermaid' | 'excalidraw' | 'd2';

export interface ChartDef {
  id: string;
  label: string;
  hint: string;
  kind: Kind;
  code: string;
}

const lines = (xs: string[]) => xs.join('\n');

export const EMPTY_EXCALIDRAW = '{"type":"excalidraw","version":2,"source":"draw","elements":[],"appState":{},"files":{}}';

export const CHARTS: ChartDef[] = [
  {
    id: 'flow',
    label: 'Flowchart',
    hint: '流程圖',
    kind: 'mermaid',
    code: lines(['graph TD;', '    A[開始] --> B[處理];', '    A --> C[檢查];', '    B --> D[完成];', '    C --> D;']),
  },
  {
    id: 'state',
    label: 'State diagram',
    hint: '狀態圖',
    kind: 'mermaid',
    code: lines(['stateDiagram-v2', '    direction LR', '    [*] --> Idle', '    Idle --> Running : start', '    Running --> [*]']),
  },
  {
    id: 'erd',
    label: 'ERD',
    hint: '資料表關聯',
    kind: 'mermaid',
    code: lines([
      'erDiagram',
      '    CUSTOMER {',
      '        string name',
      '        string email PK',
      '    }',
      '    ORDER {',
      '        int id PK',
      '    }',
      '    CUSTOMER ||--o{ ORDER : places',
    ]),
  },
  {
    id: 'class',
    label: 'Class diagram',
    hint: '類別圖',
    kind: 'mermaid',
    code: lines(['classDiagram', '    class Animal {', '        +int age', '        +eat() void', '    }', '    class Dog {', '        +bark() void', '    }', '    Animal <|-- Dog']),
  },
  {
    id: 'sequence',
    label: 'Sequence diagram',
    hint: '時序圖',
    kind: 'mermaid',
    code: lines(['sequenceDiagram', '    participant A as Alice', '    participant B as Bob', '    A->>B: Hello', '    B-->>A: Hi']),
  },
  {
    id: 'arch',
    label: 'Architecture',
    hint: '架構圖(mermaid)',
    kind: 'mermaid',
    code: lines([
      'architecture-beta',
      '    group api(cloud)[API]',
      '    service db(database)[Database] in api',
      '    service server(server)[Server] in api',
      '    db:L -- R:server',
    ]),
  },
  {
    id: 'mindmap',
    label: 'Mind map',
    hint: '心智圖',
    kind: 'mermaid',
    code: lines(['mindmap', '  root((主題))', '    分支A', '      子項1', '    分支B', '    分支C']),
  },
  {
    id: 'd2',
    label: 'D2 架構圖',
    hint: '容器對容器的連線;需要本機有 d2 指令',
    kind: 'd2',
    code: lines(['api: API 層 {', '  server: 伺服器', '}', 'data: 資料層 {', '  db: 資料庫', '}', 'api -> data: 容器對容器', 'api.server -> data.db']),
  },
  {
    id: 'excalidraw',
    label: 'Excalidraw 白板',
    hint: '自由手繪白板',
    kind: 'excalidraw',
    code: EMPTY_EXCALIDRAW,
  },
];

export const KIND_LABEL: Record<Kind, string> = { mermaid: 'Mermaid', excalidraw: 'Excalidraw', d2: 'D2' };
