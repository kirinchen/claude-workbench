/**
 * mermaidState — mermaid stateDiagram-v2 子集 的解析 / 序列化。
 *
 * 子集:狀態節點(`id` / `id : Label`)+ 起點 / 終點偽狀態(`[*]`)+ 轉移(`A --> B` / `A --> B : label`)。
 * 不支援:composite state(`state X { ... }`)、`<<choice>>`、fork/join、note、classDef ——
 *   這些超出子集,GUI 不處理(解析時略過該行、不丟例外;退回純文字編輯)。
 * GUI 存檔走 serializeState → 正規化重寫該 mermaid 區塊(註解 / 手動排版 / 樣式會丟)。
 */

export type StateKind = 'state' | 'start' | 'end';
export interface StateNode {
  id: string;
  label: string;
  kind: StateKind;
}
export interface StateEdge {
  source: string;
  target: string;
  label?: string;
}
export interface StateGraph {
  dir: string;
  nodes: StateNode[];
  edges: StateEdge[];
}

const DIRS = new Set(['TB', 'LR', 'RL', 'BT']);

/** 是否為 stateDiagram(stateDiagram / stateDiagram-v2 開頭)。 */
export function isStateDiagram(code: string): boolean {
  return /^\s*stateDiagram(-v2)?\b/i.test(code);
}

/** 去除標籤外層引號。 */
function stripQuotes(s: string): string {
  return s
    .trim()
    .replace(/^"(.*)"$/s, '$1')
    .replace(/^'(.*)'$/s, '$1');
}

/** 解析 stateDiagram-v2 子集 → 圖模型。無法解析的語法盡量略過,不丟例外。 */
export function parseState(code: string): StateGraph {
  const lines = code
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith('%%'));

  let dir = 'TB';
  let start = 0;
  if (lines.length && /^stateDiagram(-v2)?\b/i.test(lines[0])) {
    start = 1;
    // 次行可選 direction
    if (lines[start]) {
      const h = /^direction\s+([A-Za-z]{2})\b/i.exec(lines[start]);
      if (h && DIRS.has(h[1].toUpperCase())) {
        dir = h[1].toUpperCase();
        start += 1;
      }
    }
  }

  // 命名狀態:第一次出現即登記(label 預設=id),之後 `id : Label` 行更新 label。
  const named = new Map<string, StateNode>();
  const ensureState = (id: string, label?: string): void => {
    const ex = named.get(id);
    if (ex) {
      if (label !== undefined) ex.label = label;
      return;
    }
    named.set(id, { id, label: label ?? id, kind: 'state' });
  };

  // 偽狀態:每個 `[*]` 出現各建獨立節點;作來源=start、作目標=end。
  const pseudo: StateNode[] = [];
  let startSeq = 0;
  let endSeq = 0;
  const edges: StateEdge[] = [];

  /** 把轉移端點規格 → 節點 id;`[*]` 依角色建獨立偽節點。 */
  const endpointId = (spec: string, role: 'source' | 'target'): string => {
    const s = spec.trim();
    if (s === '[*]') {
      const id = role === 'source' ? `start${++startSeq}` : `end${++endSeq}`;
      pseudo.push({ id, label: '', kind: role === 'source' ? 'start' : 'end' });
      return id;
    }
    ensureState(s);
    return s;
  };

  // composite state(`state X { ... }`)區塊:用大括號深度追蹤,深度>0 期間整段
  // 略過 —— 區塊內文不是頂層語法,不該被當成狀態/轉移解析(否則巢狀內容會污染圖)。
  let braceDepth = 0;

  for (let i = start; i < lines.length; i++) {
    const line = lines[i];

    // 已在 composite 區塊內:逐字結算大括號(支援巢狀),整行略過、不建任何節點/邊。
    if (braceDepth > 0) {
      for (const ch of line) {
        if (ch === '{') braceDepth++;
        else if (ch === '}' && braceDepth > 0) braceDepth--;
      }
      continue;
    }

    // composite/state 區塊開始:行內出現 '{' 即進入跳過模式並計數(同行可能含多個括號)。
    if (line.includes('{')) {
      for (const ch of line) {
        if (ch === '{') braceDepth++;
        else if (ch === '}' && braceDepth > 0) braceDepth--;
      }
      continue;
    }

    // 略過不支援語法:composite state 宣告(無內文)、note、fork/join、choice、classDef 等。
    if (
      /^state\s/i.test(line) ||
      /^note\b/i.test(line) ||
      /^classDef\b/i.test(line) ||
      /^class\s/i.test(line) ||
      /<<\s*(choice|fork|join)\s*>>/i.test(line) ||
      line === '}'
    ) {
      continue;
    }

    // 轉移:`A --> B` / `A --> B : label`。
    const arrow = /^(.*?)\s*-->\s*(.*)$/.exec(line);
    if (arrow) {
      const src = arrow[1].trim();
      let rest = arrow[2].trim();
      let label: string | undefined;
      const ci = rest.indexOf(':');
      if (ci >= 0) {
        label = stripQuotes(rest.slice(ci + 1));
        rest = rest.slice(0, ci).trim();
      }
      if (!src || !rest) continue;
      const sourceId = endpointId(src, 'source');
      const targetId = endpointId(rest, 'target');
      edges.push({ source: sourceId, target: targetId, label: label || undefined });
      continue;
    }

    // 狀態宣告:`id : Label`(偽狀態 `[*]` 不在此登記)。
    const decl = /^([^\s:]+)\s*:\s*(.*)$/.exec(line);
    if (decl && decl[1] !== '[*]') {
      ensureState(decl[1], stripQuotes(decl[2]));
      continue;
    }

    // 單獨 `id`(非偽狀態)。
    if (/^[^\s:]+$/.test(line) && line !== '[*]') {
      ensureState(line);
      continue;
    }
  }

  return { dir, nodes: [...named.values(), ...pseudo], edges };
}

function escapeLabel(s: string): string {
  return s.replace(/"/g, '&quot;');
}

/** 圖模型 → 正規化 mermaid stateDiagram-v2 文字。 */
export function serializeState(g: StateGraph): string {
  const dir = DIRS.has(g.dir) ? g.dir : 'TB';
  const lines = ['stateDiagram-v2'];
  if (dir !== 'TB') lines.push(`    direction ${dir}`);

  // 端點 kind 查表:start/end 印 `[*]`,否則印節點 id。
  const byId = new Map<string, StateNode>();
  for (const n of g.nodes) byId.set(n.id, n);

  // label != id 的命名狀態輸出 `id : label`。
  for (const n of g.nodes) {
    if (n.kind !== 'state') continue;
    if (n.label && n.label !== n.id) {
      lines.push(`    ${n.id} : ${escapeLabel(n.label)}`);
    }
  }

  const render = (id: string): string => {
    const n = byId.get(id);
    if (n && (n.kind === 'start' || n.kind === 'end')) return '[*]';
    return id;
  };

  for (const e of g.edges) {
    const head = `    ${render(e.source)} --> ${render(e.target)}`;
    lines.push(e.label ? `${head} : ${escapeLabel(e.label)}` : head);
  }

  return lines.join('\n');
}
