/**
 * mermaidFlow — mermaid flowchart 子集 的解析 / 序列化 + 區塊取代。
 *
 * 子集:節點(矩形)+ 有向邊(`-->`)+ 邊標籤(`-->|label|`)+ 方向(TD/TB/BT/LR/RL)。
 * 不支援:subgraph、其他形狀 —— 超出子集,GUI 不處理(退回純文字編輯)。
 *
 * **樣式語句**(`classDef` / `class` / `style` / `linkStyle` / `click`)不是節點:原樣收進
 * `extras`,存檔時接在邊後面寫回(引用到已刪節點的 id 會濾掉);節點上的 `:::cls` 收進
 * `classes`。GUI 用 `classDefs` 把 fill / stroke / color 套到節點上。
 * GUI 存檔走 serializeFlow → 正規化重寫該 mermaid 區塊(註解 / 手動排版會丟,已與使用者確認)。
 */

export type FlowShape = 'rect' | 'round' | 'diamond';
export interface FlowNode {
  id: string;
  label: string;
  shape: FlowShape; // [] 矩形 / () 圓角 / {} 菱形(判斷)
  /** `:::cls` 掛上的 class(`class a,b cls` 那種在 extras,不在這)。 */
  classes?: string[];
}
export interface FlowEdge {
  source: string;
  target: string;
  label?: string;
}
export interface FlowGraph {
  dir: string;
  nodes: FlowNode[];
  edges: FlowEdge[];
  /** 樣式語句原文(classDef / class / style / linkStyle / click),存檔時原樣寫回。 */
  extras?: string[];
}

/** 一個 class 的視覺樣式(只取 GUI 畫得出來的三項)。 */
export interface FlowClassStyle {
  fill?: string;
  stroke?: string;
  color?: string;
}

const STYLE_STMT = /^(classDef|class|style|linkStyle|click)\s/;

/** `fill:#d6f5d6,stroke:#2e7d32,color:#000` → { fill, stroke, color }。 */
function parseStyleProps(spec: string): FlowClassStyle {
  const out: FlowClassStyle = {};
  for (const kv of spec.split(',')) {
    const i = kv.indexOf(':');
    if (i === -1) continue;
    const k = kv.slice(0, i).trim();
    const v = kv.slice(i + 1).trim().replace(/;$/, '');
    if (k === 'fill' || k === 'stroke' || k === 'color') out[k] = v;
  }
  return out;
}

/**
 * 每個節點最後該套的樣式:classDef 經 `class` 語句 / `:::cls` 套上,`style <id>` 再蓋過去。
 * 回 id → 樣式;沒樣式的節點不在表裡。
 */
export function nodeStyles(g: FlowGraph): Map<string, FlowClassStyle> {
  const defs = new Map<string, FlowClassStyle>();
  const assigned = new Map<string, string[]>();
  const direct = new Map<string, FlowClassStyle>();
  for (const n of g.nodes) if (n.classes?.length) assigned.set(n.id, [...n.classes]);
  for (const line of g.extras ?? []) {
    let m = /^classDef\s+(\S+)\s+(.+)$/.exec(line);
    if (m) {
      for (const name of m[1].split(',')) defs.set(name, parseStyleProps(m[2]));
      continue;
    }
    m = /^class\s+(\S+)\s+(\S+)/.exec(line);
    if (m) {
      for (const id of m[1].split(',')) assigned.set(id, [...(assigned.get(id) ?? []), m[2]]);
      continue;
    }
    m = /^style\s+(\S+)\s+(.+)$/.exec(line);
    if (m) direct.set(m[1], parseStyleProps(m[2]));
  }
  const out = new Map<string, FlowClassStyle>();
  for (const n of g.nodes) {
    const st: FlowClassStyle = { ...defs.get('default') };
    for (const c of assigned.get(n.id) ?? []) Object.assign(st, defs.get(c));
    Object.assign(st, direct.get(n.id));
    if (st.fill || st.stroke || st.color) out.set(n.id, st);
  }
  return out;
}

const DIRS = new Set(['TB', 'TD', 'BT', 'LR', 'RL']);

/** 是否為 flowchart(graph / flowchart 開頭)。 */
export function isFlowchart(code: string): boolean {
  return /^\s*(graph|flowchart)\b/i.test(code);
}

/** 抓節點規格:`id` / `id[label]`(矩形) / `id(label)`(圓角) / `id{label}`(菱形)。回傳 id。 */
function parseNodeSpec(
  p: string,
  ensure: (id: string, label?: string, shape?: FlowShape, classes?: string[]) => void,
): string {
  let s = p.trim();
  if (!s) return '';
  // `A[x]:::cls` / `A:::c1:::c2` → 剝掉 class 尾巴另外記
  const classes: string[] = [];
  s = s.replace(/(?::::([A-Za-z0-9_-]+))+$/, (tail) => {
    classes.push(...tail.split(':::').filter(Boolean));
    return '';
  });
  const m = /^([^\s[\](){}]+)\s*(?:\[([^\]]*)\]|\(([^)]*)\)|\{([^}]*)\})?$/.exec(s);
  if (!m) {
    ensure(s, undefined, undefined, classes);
    return s;
  }
  const id = m[1];
  let label: string | undefined;
  let shape: FlowShape | undefined;
  if (m[2] !== undefined) {
    label = m[2];
    shape = 'rect';
  } else if (m[3] !== undefined) {
    label = m[3];
    shape = 'round';
  } else if (m[4] !== undefined) {
    label = m[4];
    shape = 'diamond';
  }
  if (label !== undefined) {
    label = label.trim().replace(/^"(.*)"$/s, '$1').replace(/^'(.*)'$/s, '$1');
  }
  ensure(id, label, shape, classes);
  return id;
}

// 箭頭(含可選 |label|);長/帶 > 的形式排前面,避免被短形式先吃掉。
const ARROW = /(?:-->|==>|-\.->|--x|--o|---|===|--|==)(?:\|([^|]*)\|)?/g;

function parseStatement(
  stmt: string,
  ensure: (id: string, label?: string, shape?: FlowShape, classes?: string[]) => void,
  edges: FlowEdge[],
): void {
  const parts: string[] = [];
  const labels: (string | undefined)[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  ARROW.lastIndex = 0;
  let hasArrow = false;
  while ((m = ARROW.exec(stmt)) !== null) {
    hasArrow = true;
    parts.push(stmt.slice(last, m.index));
    labels.push(m[1]);
    last = m.index + m[0].length;
  }
  parts.push(stmt.slice(last));
  const ids = parts.map((p) => parseNodeSpec(p, ensure)).filter(Boolean);
  if (!hasArrow) return; // 純節點宣告,parseNodeSpec 已登記
  for (let i = 0; i + 1 < ids.length; i++) {
    const label = labels[i]?.trim();
    edges.push({ source: ids[i], target: ids[i + 1], label: label || undefined });
  }
}

/** 解析 flowchart 子集 → 圖模型。無法解析的語法盡量略過,不丟例外。 */
export function parseFlow(code: string): FlowGraph {
  const lines = code
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith('%%'));

  let dir = 'TD';
  let start = 0;
  if (lines.length && /^(graph|flowchart)\b/i.test(lines[0])) {
    const h = /^(?:graph|flowchart)\s+([A-Za-z]{2})\b/i.exec(lines[0]);
    if (h && DIRS.has(h[1].toUpperCase())) dir = h[1].toUpperCase();
    start = 1;
  }

  const nodes = new Map<string, FlowNode>();
  const ensure = (id: string, label?: string, shape?: FlowShape, classes?: string[]) => {
    const ex = nodes.get(id);
    if (ex) {
      if (label !== undefined) ex.label = label;
      if (shape) ex.shape = shape;
      if (classes?.length) ex.classes = [...new Set([...(ex.classes ?? []), ...classes])];
      return;
    }
    const n: FlowNode = { id, label: label ?? id, shape: shape ?? 'rect' };
    if (classes?.length) n.classes = [...new Set(classes)];
    nodes.set(id, n);
  };
  const edges: FlowEdge[] = [];
  const extras: string[] = [];

  for (let i = start; i < lines.length; i++) {
    // 樣式語句整行收走,不拿 `;` 切(classDef 的值裡本來就可能有 `;`)。
    if (STYLE_STMT.test(lines[i])) {
      extras.push(lines[i].replace(/;\s*$/, ''));
      continue;
    }
    for (const stmt of lines[i].split(';')) {
      if (!stmt.trim()) continue;
      if (STYLE_STMT.test(stmt.trim())) extras.push(stmt.trim());
      else parseStatement(stmt, ensure, edges);
    }
  }
  return { dir, nodes: [...nodes.values()], edges, extras };
}

/**
 * 樣式語句寫回前先對齊現況:mermaid 碰到 `class` / `style` / `click` 引用不存在的 id 會
 * **憑空生出那個節點**,所以 GUI 刪掉的節點要從這些語句裡濾掉(全濾光就整行丟);
 * `linkStyle <n>` 的邊序號超出現有邊數的丟掉。classDef 原樣。
 */
function keepExtras(g: FlowGraph): string[] {
  const ids = new Set(g.nodes.map((n) => n.id));
  const out: string[] = [];
  for (const x of g.extras ?? []) {
    let m = /^class\s+(\S+)(\s+.*)$/.exec(x);
    if (m) {
      const kept = m[1].split(',').filter((id) => ids.has(id));
      if (kept.length) out.push(`class ${kept.join(',')}${m[2]}`);
      continue;
    }
    m = /^(style|click)\s+(\S+)/.exec(x);
    if (m) {
      if (ids.has(m[2])) out.push(x);
      continue;
    }
    m = /^linkStyle\s+(\S+)(\s+.*)$/.exec(x);
    if (m) {
      if (m[1] === 'default') out.push(x);
      else {
        const kept = m[1].split(',').filter((n) => Number(n) < g.edges.length);
        if (kept.length) out.push(`linkStyle ${kept.join(',')}${m[2]}`);
      }
      continue;
    }
    out.push(x);
  }
  return out;
}

function escapeLabel(s: string): string {
  return s.replace(/"/g, '&quot;');
}

/** 圖模型 → 正規化 mermaid flowchart 文字。 */
export function serializeFlow(g: FlowGraph): string {
  const dir = DIRS.has(g.dir) ? g.dir : 'TD';
  const lines = [`flowchart ${dir}`];
  for (const n of g.nodes) {
    const shape = n.shape ?? 'rect';
    const cls = (n.classes ?? []).map((c) => `:::${c}`).join('');
    if (shape === 'rect') {
      if (n.label && n.label !== n.id) lines.push(`    ${n.id}["${escapeLabel(n.label)}"]${cls}`);
      else lines.push(`    ${n.id}${cls}`);
    } else {
      const [open, close] = shape === 'diamond' ? ['{', '}'] : ['(', ')'];
      lines.push(`    ${n.id}${open}"${escapeLabel(n.label || n.id)}"${close}${cls}`);
    }
  }
  for (const e of g.edges) {
    if (e.label) lines.push(`    ${e.source} -->|${e.label}| ${e.target}`);
    else lines.push(`    ${e.source} --> ${e.target}`);
  }
  for (const x of keepExtras(g)) lines.push(`    ${x}`);
  return lines.join('\n');
}

/** 把 content 內某個 ```mermaid 區塊(body 與 oldCode 相符)換成 newCode。 */
export function replaceMermaidBlock(content: string, oldCode: string, newCode: string): string {
  const re = /```mermaid[ \t]*\r?\n([\s\S]*?)\r?\n?```/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(content)) !== null) {
    if (m[1].trim() === oldCode.trim()) {
      return (
        content.slice(0, m.index) +
        '```mermaid\n' +
        newCode +
        '\n```' +
        content.slice(m.index + m[0].length)
      );
    }
  }
  return content.replace(oldCode, newCode); // fallback
}
