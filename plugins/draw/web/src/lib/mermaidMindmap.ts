/**
 * mermaidMindmap — mermaid `mindmap` 圖型的解析 / 序列化(給 GUI 樹狀編輯器用)。
 *
 * mindmap 是縮排式階層樹(非 `-->` 邊):
 *  - 開頭行 `mindmap`。
 *  - 每行一個節點,**階層由行首空白數決定**:第一個節點 = 唯一 root;之後每個節點的
 *    parent = 其上方「縮排嚴格更小」的最近節點。縮排只看相對大小(差幾格不重要)。
 *  - 節點形狀(可加可選 id 前綴 `id[text]`):
 *      預設(無分隔符,純文字) / `[]` square / `()` rounded / `(())` circle /
 *      `{{}}` hexagon / `)text(` cloud / `))text((` bang。
 *  - 文字含 `()[]{}` 等特殊字元時,以 `"..."` 包在形狀分隔符內(實測 mermaid 接受)。
 *  - `::icon(...)` 與 `:::class` 各佔一行,裝飾「上一個節點」。
 * 不支援的進階語法盡量保留(icon/class round-trip),無法解析的行略過,不丟例外。
 */

export type MindmapShape = 'default' | 'square' | 'rounded' | 'circle' | 'hexagon' | 'cloud' | 'bang';

export interface MindmapNode {
  /** 內部穩定 id(React Flow node.id)。 */
  key: string;
  /** mermaid id 前綴(解析到才有);序列化需要 id 的形狀時優先用它,否則用 key。 */
  mid?: string;
  text: string;
  shape: MindmapShape;
  /** ::icon(...) 內容(如 fa fa-book)。 */
  icon?: string;
  /** :::class 類別(可含多個,空白分隔)。 */
  cls?: string;
  /** parent 節點 key(root 為 undefined)。 */
  parent?: string;
}

export interface MindmapModel {
  /** nodes[0] = root(序列化時第一個輸出);其餘依插入序。 */
  nodes: MindmapNode[];
}

/** 是否為 mindmap。 */
export function isMindmap(code: string): boolean {
  return /^\s*mindmap\b/i.test(code);
}

/* ───────────────────────── 解析 ───────────────────────── */

// 形狀分隔符,長的優先(避免 (( 被 ( 先吃、)) 被 ) 先吃)。
const SHAPE_DELIMS: { open: string; close: string; shape: MindmapShape }[] = [
  { open: '))', close: '((', shape: 'bang' },
  { open: '((', close: '))', shape: 'circle' },
  { open: '{{', close: '}}', shape: 'hexagon' },
  { open: '[', close: ']', shape: 'square' },
  { open: '(', close: ')', shape: 'rounded' },
  { open: ')', close: '(', shape: 'cloud' },
];

/**
 * 去掉外層 "..."(若有);還原被換成 ' 的引號無法復原,故只剝引號。
 * 全空白的引號內容(`" "`)= 序列化「空文字節點」的載體(見 quoteBody),還原成空字串。
 */
function unquoteText(s: string): string {
  const t = s.trim();
  if (t.length >= 2 && t.startsWith('"') && t.endsWith('"')) {
    const inner = t.slice(1, -1);
    return inner.trim() === '' ? '' : inner;
  }
  return t;
}

/** 解析單一節點 token(可選 id 前綴 + 形狀 + 文字)。 */
function parseNodeToken(raw: string): { mid?: string; text: string; shape: MindmapShape } {
  const s = raw.trim();
  for (const { open, close, shape } of SHAPE_DELIMS) {
    const oi = s.indexOf(open);
    if (oi >= 0 && s.length >= oi + open.length + close.length && s.endsWith(close)) {
      const mid = s.slice(0, oi).trim() || undefined;
      const inner = s.slice(oi + open.length, s.length - close.length);
      return { mid, text: unquoteText(inner), shape };
    }
  }
  return { text: unquoteText(s), shape: 'default' };
}

/** 解析 mindmap 子集 → 模型(縮排 stack 建樹)。 */
export function parseMindmap(code: string): MindmapModel {
  const nodes: MindmapNode[] = [];
  // stack:由淺到深的祖先鏈,用於找 parent。
  const stack: { indent: number; key: string }[] = [];
  let counter = 0;
  let lastKey: string | undefined;

  for (const rawLine of code.split(/\r?\n/)) {
    if (/^\s*mindmap\b/i.test(rawLine)) continue; // header
    if (/^\s*%%/.test(rawLine)) continue; // 註解
    if (!rawLine.trim()) continue; // 空行

    const indent = rawLine.length - rawLine.replace(/^\s+/, '').length;
    const content = rawLine.trim();

    // ::icon(...) → 裝飾上一個節點。greedy 收到最後一個 ) 以容許內容含 );
    // 不論是否匹配,只要以 ::icon( 起頭就不當節點(避免解析失敗變幻影節點)。
    if (content.startsWith('::icon(')) {
      const iconM = /^::icon\((.*)\)\s*$/.exec(content);
      if (iconM) {
        const last = nodes.find((n) => n.key === lastKey);
        if (last) last.icon = iconM[1].trim();
      }
      continue;
    }
    // :::class → 裝飾上一個節點
    const clsM = /^:::(.+)$/.exec(content);
    if (clsM) {
      const last = nodes.find((n) => n.key === lastKey);
      if (last) last.cls = clsM[1].trim();
      continue;
    }

    // 找 parent:彈出 stack 上 indent >= 自己的;剩下的 top 即 parent。
    while (stack.length && stack[stack.length - 1].indent >= indent) stack.pop();
    const stackParent = stack.length ? stack[stack.length - 1].key : undefined;

    const { mid, text, shape } = parseNodeToken(content);
    const key = `m${counter++}`;
    const isFirst = nodes.length === 0;
    // 單 root 不變式:非第一個節點若算不出 parent(縮排比 root 還淺、或並列頂層)→
    // 一律掛到 root,避免「多 root」在序列化時被靜默丟失(mermaid 也只允許一個 root)。
    const parent = isFirst ? undefined : stackParent ?? nodes[0].key;
    nodes.push({ key, mid, text, shape, parent });
    stack.push({ indent, key });
    lastKey = key;
  }

  return { nodes };
}

/* ───────────────────────── 序列化 ───────────────────────── */

/** 文字是否需引號(含括號 / 引號 / 前後空白 / 空字串)。 */
function needsQuote(text: string): boolean {
  return /[()[\]{}"]/.test(text) || /^\s|\s$/.test(text) || text === '';
}

/**
 * 包引號的節點內容。`"` → `'`(mermaid 不吃巢狀引號)。
 * **空文字必須補一個空白**:mermaid 的 mindmap 文法不接受空的引號內容(`a[""]` 會噴
 * `Expecting 'NODE_DESCR', got 'NODE_DEND'`)→ 整張圖 parse 失敗、什麼都不渲染。
 * 「新增子節點」後未命名的節點正是空文字,故一定要擋。`a[" "]` 實測可解析;
 * 讀回時 unquoteText 把全空白內容還原成空字串,round-trip 一致。
 */
function quoteBody(text: string): string {
  const body = text.replace(/"/g, "'");
  return `"${body.trim() === '' ? ' ' : body}"`;
}

/** id 前綴正規化成合法 token(僅 \w);空則回 undefined。 */
function safeMid(s: string | undefined): string | undefined {
  if (!s) return undefined;
  const t = s.replace(/[^A-Za-z0-9_]+/g, '_').replace(/^_+|_+$/g, '');
  return t || undefined;
}

/**
 * 序列化單一節點為一行內容(不含縮排)。需要 id 的形狀以 mid 或 key 當 id;
 * id 必須全域唯一(mermaid 同 id 會 merge 成同節點 → 資料遺失),故傳入 usedIds 去重。
 */
function serializeNodeBody(n: MindmapNode, usedIds: Set<string>): string {
  const quoted = needsQuote(n.text);
  // 預設形狀但文字需引號 → 退回 square(預設無分隔符無法包引號)。
  const shape: MindmapShape = n.shape === 'default' && quoted ? 'square' : n.shape;
  if (shape === 'default') return n.text;

  // id 唯一化:優先 mid,碰撞則退回唯一的 key,仍碰撞再加序號。
  let id = safeMid(n.mid) ?? n.key;
  if (usedIds.has(id)) id = n.key; // key(m0 / m_0)保證唯一
  let cand = id;
  let i = 2;
  while (usedIds.has(cand)) cand = `${id}_${i++}`;
  usedIds.add(cand);
  id = cand;
  const body = quoted ? quoteBody(n.text) : n.text;
  switch (shape) {
    case 'square':
      return `${id}[${body}]`;
    case 'rounded':
      return `${id}(${body})`;
    case 'circle':
      return `${id}((${body}))`;
    case 'hexagon':
      return `${id}{{${body}}}`;
    case 'cloud':
      return `${id})${body}(`;
    case 'bang':
      return `${id}))${body}((`;
    default:
      return n.text;
  }
}

/** 模型 → 正規化 mindmap 文字(每層 2 空白;icon/class 緊跟節點之後)。 */
export function serializeMindmap(model: MindmapModel): string {
  const lines = ['mindmap'];
  const childrenOf = new Map<string | undefined, MindmapNode[]>();
  for (const n of model.nodes) {
    const k = n.parent;
    if (!childrenOf.has(k)) childrenOf.set(k, []);
    childrenOf.get(k)!.push(n);
  }

  // root:第一個無 parent 的節點(mindmap 僅一個 root)。
  const root = model.nodes.find((n) => !n.parent);
  if (!root) return lines.join('\n');

  const seen = new Set<string>();
  const usedIds = new Set<string>();
  const emit = (n: MindmapNode, depth: number): void => {
    if (seen.has(n.key)) return; // 防環
    seen.add(n.key);
    const pad = '  '.repeat(depth);
    lines.push(`${pad}${serializeNodeBody(n, usedIds)}`);
    if (n.icon) lines.push(`${'  '.repeat(depth + 1)}::icon(${n.icon})`);
    if (n.cls) lines.push(`${'  '.repeat(depth + 1)}:::${n.cls}`);
    for (const c of childrenOf.get(n.key) ?? []) emit(c, depth + 1);
  };
  emit(root, 0);
  // 防禦:任何未走訪到的節點(多 root / 斷鏈)→ 掛到 root 之下(depth 1),避免靜默丟失。
  for (const n of model.nodes) if (!seen.has(n.key)) emit(n, 1);

  return lines.join('\n');
}

/** 形狀 → 人類可讀標籤(供 UI Select)。 */
export const MINDMAP_SHAPE_LABELS: Record<MindmapShape, string> = {
  default: '預設(無框)',
  square: '方框 []',
  rounded: '圓角 ()',
  circle: '圓 (())',
  hexagon: '六角 {{}}',
  cloud: '雲 )(',
  bang: '爆炸 ))((',
};
