/**
 * d2 — D2(https://d2lang.com)子集的解析 / 序列化,給 GUI 編輯器用。
 *
 * 支援子集:
 *  - shape(葉節點):     `id` 或 `id: Label`
 *  - container(容器,可巢狀):`id: Label { ...子節點... }`(label 可省)
 *  - 點路徑:             `a.b.c`(中間段視為 container)
 *  - 連線(邊):          `a -> b`、`a -> b: Label`、`a <-> b`、`a <- b`、`a -- b`
 *                        端點可為 shape 或 container;支援鏈 `a -> b -> c`。
 *  - 行內 `#` 註解(引號內不算)。
 * 不支援(退回純文字編輯,不丟例外):style/class、sql_table、code、icon、near、
 *   邊上的 `{...}` 樣式區塊(會被忽略)等。
 *
 * D2 原生支援「容器對容器」邊(mermaid architecture-beta 做不到)——這是引入 D2 的主因。
 * 渲染走後端 `d2` CLI(POST /api/d2/render);本檔只管模型 ↔ 文字。
 */

export type D2Arrow = '->' | '<-' | '<->' | '--';

export interface D2Node {
  /** 末段 local id(在其 parent 內唯一)。 */
  id: string;
  /** 完整點路徑(如 gA.a)。模型主鍵。 */
  fullId: string;
  /** 顯示文字(省略時 D2 以 id 當 label)。 */
  label?: string;
  /** parent container 的 fullId(頂層為 undefined)。 */
  parent?: string;
  /** 是否為 container(有子節點 / 被宣告成有 `{}`)。 */
  container: boolean;
}

export interface D2Edge {
  from: string; // fullId
  to: string; // fullId
  arrow: D2Arrow;
  label?: string;
}

export interface D2Model {
  nodes: D2Node[];
  edges: D2Edge[];
}

/* ───────────────────────── 掃描工具(引號 / 大括號感知) ───────────────────────── */

/** 去掉 `#` 行內註解(雙引號內的 # 不算)。 */
function stripComments(code: string): string {
  let out = '';
  let inQuote = false;
  for (let i = 0; i < code.length; i++) {
    const c = code[i];
    if (inQuote) {
      out += c;
      if (c === '\\' && i + 1 < code.length) {
        out += code[++i];
      } else if (c === '"') {
        inQuote = false;
      }
      continue;
    }
    if (c === '"') {
      inQuote = true;
      out += c;
    } else if (c === '#') {
      while (i < code.length && code[i] !== '\n') i++;
      if (i < code.length) out += '\n';
    } else {
      out += c;
    }
  }
  return out;
}

/** 把一段 scope body 依「深度 0 的換行 / 分號」切成多個 statement。 */
function splitStatements(body: string): string[] {
  const stmts: string[] = [];
  let depth = 0;
  let inQuote = false;
  let cur = '';
  for (let i = 0; i < body.length; i++) {
    const c = body[i];
    if (inQuote) {
      cur += c;
      if (c === '\\' && i + 1 < body.length) cur += body[++i];
      else if (c === '"') inQuote = false;
      continue;
    }
    if (c === '"') {
      inQuote = true;
      cur += c;
    } else if (c === '{') {
      depth++;
      cur += c;
    } else if (c === '}') {
      depth = Math.max(0, depth - 1);
      cur += c;
    } else if ((c === '\n' || c === ';') && depth === 0) {
      if (cur.trim()) stmts.push(cur.trim());
      cur = '';
    } else {
      cur += c;
    }
  }
  if (cur.trim()) stmts.push(cur.trim());
  return stmts;
}

/** 找深度 0、引號外第一個 char(回傳 index,無則 -1)。 */
function indexTopLevel(s: string, ch: string): number {
  let depth = 0;
  let inQuote = false;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (inQuote) {
      if (c === '\\') i++;
      else if (c === '"') inQuote = false;
      continue;
    }
    if (c === '"') inQuote = true;
    else if (depth === 0 && c === ch) return i; // 先比對目標(ch 可能就是括號)
    else if (c === '{' || c === '(' || c === '[') depth++;
    else if (c === '}' || c === ')' || c === ']') depth--;
  }
  return -1;
}

/** 切出深度 0 的箭頭運算子(回傳片段 + 運算子序列)。支援鏈。 */
function splitArrows(s: string): { parts: string[]; ops: D2Arrow[] } {
  const parts: string[] = [];
  const ops: D2Arrow[] = [];
  let depth = 0;
  let inQuote = false;
  let cur = '';
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (inQuote) {
      cur += c;
      if (c === '\\' && i + 1 < s.length) cur += s[++i];
      else if (c === '"') inQuote = false;
      continue;
    }
    if (c === '"') {
      inQuote = true;
      cur += c;
      continue;
    }
    if (c === '{' || c === '(' || c === '[') depth++;
    else if (c === '}' || c === ')' || c === ']') depth--;
    if (depth === 0) {
      // 比對箭頭(長的優先)
      const three = s.slice(i, i + 3);
      const two = s.slice(i, i + 2);
      if (three === '<->') {
        parts.push(cur);
        cur = '';
        ops.push('<->');
        i += 2;
        continue;
      }
      if (two === '->' || two === '<-' || two === '--') {
        parts.push(cur);
        cur = '';
        ops.push(two as D2Arrow);
        i += 1;
        continue;
      }
    }
    cur += c;
  }
  parts.push(cur);
  return { parts, ops };
}

/** 深度 0、引號外切點路徑(`a.b.c` → ['a','b','c'])。 */
function splitDots(s: string): string[] {
  const segs: string[] = [];
  let inQuote = false;
  let cur = '';
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (inQuote) {
      cur += c;
      if (c === '\\' && i + 1 < s.length) cur += s[++i];
      else if (c === '"') inQuote = false;
      continue;
    }
    if (c === '"') {
      inQuote = true;
      cur += c;
    } else if (c === '.') {
      segs.push(cur);
      cur = '';
    } else {
      cur += c;
    }
  }
  segs.push(cur);
  return segs.map((x) => x.trim()).filter(Boolean);
}

/** 去掉外層雙引號 + 還原跳脫(\" → "、\\ → \、\n → 換行)。 */
function unquote(s: string): string {
  const t = s.trim();
  if (t.length >= 2 && t.startsWith('"') && t.endsWith('"')) {
    return t.slice(1, -1).replace(/\\(.)/g, (_, c) => (c === 'n' ? '\n' : c));
  }
  return t;
}

/* ───────────────────────── 解析 ───────────────────────── */

/** 解析 D2 子集 → 模型。無法解析的語句盡量略過,不丟例外。 */
export function parseD2(code: string): D2Model {
  const nodes: D2Node[] = [];
  const edges: D2Edge[] = [];
  const index = new Map<string, D2Node>();

  const ensureNode = (fullId: string, localId: string, parent: string | undefined, container: boolean): D2Node => {
    let n = index.get(fullId);
    if (!n) {
      n = { id: localId, fullId, parent, container };
      index.set(fullId, n);
      nodes.push(n);
    } else if (container) {
      n.container = true;
    }
    return n;
  };

  // 解析 key 路徑(相對 parent),建立中間 container,回傳最末節點。
  const resolveKey = (keyRaw: string, parent: string | undefined): D2Node | null => {
    const segs = splitDots(keyRaw).map(unquote).filter(Boolean);
    if (!segs.length) return null;
    let cur = parent;
    let node: D2Node | null = null;
    for (let i = 0; i < segs.length; i++) {
      const seg = segs[i];
      const full = cur ? `${cur}.${seg}` : seg;
      const isLast = i === segs.length - 1;
      node = ensureNode(full, seg, cur, !isLast); // 中間段一定是 container
      cur = full;
    }
    return node;
  };

  const parseBody = (body: string, parent: string | undefined): void => {
    for (const stmt of splitStatements(body)) {
      const arrowInfo = splitArrows(stmt);
      if (arrowInfo.ops.length > 0) {
        // 連線(可能是鏈)。最後一段可能含 `: label`(及被忽略的 `{...}` 樣式)。
        const parts = arrowInfo.parts.map((p) => p.trim());
        const last = parts[parts.length - 1];
        let label: string | undefined;
        let lastKey = last;
        const braceAt = indexTopLevel(last, '{');
        const keyAndLabel = braceAt >= 0 ? last.slice(0, braceAt).trim() : last;
        const colonAt = indexTopLevel(keyAndLabel, ':');
        if (colonAt >= 0) {
          lastKey = keyAndLabel.slice(0, colonAt).trim();
          const lab = keyAndLabel.slice(colonAt + 1).trim();
          label = lab ? unquote(lab) : undefined;
        } else {
          lastKey = keyAndLabel;
        }
        parts[parts.length - 1] = lastKey;

        const endpoints = parts.map((k) => resolveKey(k, parent));
        for (let i = 0; i < arrowInfo.ops.length; i++) {
          const a = endpoints[i];
          const b = endpoints[i + 1];
          if (a && b) edges.push({ from: a.fullId, to: b.fullId, arrow: arrowInfo.ops[i], label });
        }
        continue;
      }

      // 宣告:`KEY [: label] [{ block }]`
      const braceAt = indexTopLevel(stmt, '{');
      const head = (braceAt >= 0 ? stmt.slice(0, braceAt) : stmt).trim();
      const block =
        braceAt >= 0 ? stmt.slice(braceAt + 1, stmt.lastIndexOf('}')) : null;

      const colonAt = indexTopLevel(head, ':');
      const keyRaw = (colonAt >= 0 ? head.slice(0, colonAt) : head).trim();
      const labelRaw = colonAt >= 0 ? head.slice(colonAt + 1).trim() : '';
      if (!keyRaw) continue;

      const node = resolveKey(keyRaw, parent);
      if (!node) continue;
      if (labelRaw) node.label = unquote(labelRaw);
      if (block !== null) {
        node.container = true;
        parseBody(block, node.fullId);
      }
    }
  };

  parseBody(stripComments(code), undefined);
  return { nodes, edges };
}

/* ───────────────────────── 序列化 ───────────────────────── */

/**
 * D2 保留字:當成裸 key / 邊端點會被 d2 當特殊欄位處理而編譯失敗(reserved field / keyword)。
 * 命中時一律加引號(加引號永遠合法)。比對大小寫不敏感。
 * (含 '-' 的保留字本來就不符 \w 會被引號,列出僅備忘。)
 */
const D2_RESERVED = new Set([
  'style', 'near', 'shape', 'label', 'class', 'direction', 'width', 'height',
  'icon', 'constraint', 'top', 'left', 'tooltip', 'link', 'grid-rows',
  'grid-columns', 'grid-gap', 'vertical-gap', 'horizontal-gap',
]);

/** 跳脫雙引號字串內容:\ → \\、" → \"、換行 → \n。 */
function escQuoted(s: string): string {
  return s.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n');
}

/** key(單段 id)序列化:非 \w 或為保留字 → 加引號。 */
function quoteKey(id: string): string {
  const safe = /^[A-Za-z0-9_]+$/.test(id) && !D2_RESERVED.has(id.toLowerCase());
  return safe ? id : `"${escQuoted(id)}"`;
}

/** label 序列化:含 D2 特殊字元 / 方括號 / 箭頭 / 前後空白 / 換行 → 加引號(並跳脫)。 */
function quoteLabel(s: string): string {
  const needs = /[:;{}[\]#|"\n]/.test(s) || /->|<-|--|<>/.test(s) || /^\s|\s$/.test(s);
  return needs ? `"${escQuoted(s)}"` : s;
}

/** 由 fullId 走 parent 鏈組出可序列化的點路徑(每段視需要加引號)。 */
function edgePath(fullId: string, index: Map<string, D2Node>): string {
  const n = index.get(fullId);
  if (!n) {
    return fullId
      .split('.')
      .map((s) => quoteKey(s))
      .join('.');
  }
  const segs: string[] = [];
  let cur: D2Node | undefined = n;
  const seen = new Set<string>();
  while (cur && !seen.has(cur.fullId)) {
    seen.add(cur.fullId);
    segs.unshift(quoteKey(cur.id));
    cur = cur.parent ? index.get(cur.parent) : undefined;
  }
  return segs.join('.');
}

/** 模型 → 正規化 D2 文字(node 樹巢狀,edge 一律以完整點路徑寫在頂層)。 */
export function serializeD2(model: D2Model): string {
  const index = new Map<string, D2Node>();
  for (const n of model.nodes) index.set(n.fullId, n);

  const childrenOf = new Map<string | undefined, D2Node[]>();
  for (const n of model.nodes) {
    const key = n.parent;
    if (!childrenOf.has(key)) childrenOf.set(key, []);
    childrenOf.get(key)!.push(n);
  }

  const lines: string[] = [];
  const emit = (parent: string | undefined, indent: number): void => {
    const pad = '  '.repeat(indent);
    for (const n of childrenOf.get(parent) ?? []) {
      const kids = childrenOf.get(n.fullId) ?? [];
      const isContainer = n.container || kids.length > 0;
      const labelPart = n.label !== undefined && n.label !== n.id ? `: ${quoteLabel(n.label)}` : '';
      if (isContainer) {
        // container:`id: Label {` … `}`(label 與 id 相同則省略 label 但保留 `:`)
        const head = n.label !== undefined && n.label !== n.id ? `${quoteKey(n.id)}${labelPart}` : quoteKey(n.id);
        lines.push(`${pad}${head} {`);
        emit(n.fullId, indent + 1);
        lines.push(`${pad}}`);
      } else {
        lines.push(`${pad}${quoteKey(n.id)}${labelPart}`);
      }
    }
  };
  emit(undefined, 0);

  for (const e of model.edges) {
    const from = edgePath(e.from, index);
    const to = edgePath(e.to, index);
    const labelPart = e.label ? `: ${quoteLabel(e.label)}` : '';
    lines.push(`${from} ${e.arrow} ${to}${labelPart}`);
  }

  return lines.join('\n');
}
