/**
 * mermaidArchitecture — mermaid architecture-beta(Architecture Diagram)子集 的解析 / 序列化。
 *
 * 子集(官方 https://mermaid.js.org/syntax/architecture.html):
 *  - 開頭行 "architecture-beta"。
 *  - group:    `group {id}({icon})[{title}]` 可選結尾 ` in {parentGroupId}`(巢狀 group)。
 *  - service:  `service {id}({icon})[{title}]` 可選結尾 ` in {groupId}`。
 *  - junction: `junction {id}` 可選 ` in {groupId}`(無 icon/title)。
 *  - 邊:      `{id}{:side} {edge} {:side}{id}`,例 `db:L -- R:server`。
 *      side ∈ L R T B(left/right/top/bottom)。
 *      edge:'--' 基底,可帶箭頭 '-->' / '<--' / '<-->' / '--'。
 *      {group} 修飾子:接在「端點 id 正後方」(例 `server{group}:R --> L:db`),
 *        意為該端點(service/junction)的線改接到其「所屬 group 的邊界」——視覺上即連到 group。
 *        端點 id 永遠是 service/junction,**不可**是 group id(mermaid 會 DB 階段 TypeError);
 *        且 {group} 僅當該 service 屬於某 group、兩端在不同 group 時合法。
 *  - icon:內建 cloud/database/disk/internet/server,或 iconify 名稱(如 logos:aws)——當字串保留。
 * 略過不支援 / 未知行,不丟例外。
 * GUI 存檔走 serializeArchitecture → 正規化重寫該 mermaid 區塊(註解 / 手動排版會丟)。
 */

export type Side = 'L' | 'R' | 'T' | 'B';

export interface ArchGroup {
  id: string;
  icon?: string;
  title?: string;
  parent?: string; // 'in' parent group id(巢狀)
}
export interface ArchService {
  id: string;
  icon?: string;
  title?: string;
  group?: string; // 'in' group id
}
export interface ArchJunction {
  id: string;
  group?: string; // 'in' group id
}
export interface ArchEdge {
  from: string;
  fromSide: Side;
  to: string;
  toSide: Side;
  arrowFrom: boolean; // 左箭頭(指向 from)
  arrowTo: boolean; // 右箭頭(指向 to)
  fromGroup?: boolean; // from 端點的 {group} 修飾子(線接到該 service 所屬 group 邊界)
  toGroup?: boolean; // to 端點的 {group} 修飾子
}
export interface ArchModel {
  groups: ArchGroup[];
  services: ArchService[];
  junctions: ArchJunction[];
  edges: ArchEdge[];
}

const SIDES = new Set<Side>(['L', 'R', 'T', 'B']);

/** 是否為 architecture-beta。 */
export function isArchitecture(code: string): boolean {
  return /^\s*architecture-beta\b/i.test(code);
}

function asSide(s: string): Side | null {
  const u = s.toUpperCase();
  return SIDES.has(u as Side) ? (u as Side) : null;
}

// node 宣告:`{id}({icon})[{title}]` 後可選 ` in {parent}`。
// icon / title 皆可選;junction 走另一條規則(無 icon/title)。
const NODE_RE =
  /^(group|service)\s+([^\s:(){}[\]]+)\s*(?:\(([^)]*)\))?\s*(?:\[([^\]]*)\])?\s*(?:in\s+([^\s(){}[\]]+))?\s*$/i;
const JUNCTION_RE = /^junction\s+([^\s(){}[\]]+)\s*(?:in\s+([^\s(){}[\]]+))?\s*$/i;

// 邊:`{from}{group?}:{fromSide} {edge} {toSide}:{to}{group?}`,例 `db:L -- R:server`。
// 左端:id[{group}]:side;右端:side:id[{group}]。
// edge 段以 [<>-]{2,} 寬鬆抓取,再判讀箭頭(核心須為 '--')。
const EDGE_RE =
  /^([^\s:(){}[\]]+)(\{group\})?:([LRTBlrtb])\s*([<>-]{2,})\s*([LRTBlrtb]):([^\s:(){}[\]]+)(\{group\})?$/;

/** 解析 architecture-beta 子集 → 模型。無法解析的語法盡量略過,不丟例外。 */
export function parseArchitecture(code: string): ArchModel {
  const groups: ArchGroup[] = [];
  const services: ArchService[] = [];
  const junctions: ArchJunction[] = [];
  const edges: ArchEdge[] = [];

  for (let raw of code.split(/\r?\n/)) {
    // 去掉行內 / 整行 mermaid 註解(%%)。
    const cm = raw.indexOf('%%');
    if (cm >= 0) raw = raw.slice(0, cm);
    const line = raw.trim();
    if (!line) continue;
    if (/^architecture-beta\b/i.test(line)) continue;

    // junction(先試,因 group/service regex 也可能誤吃)。
    const jm = JUNCTION_RE.exec(line);
    if (jm) {
      junctions.push({ id: jm[1], group: jm[2] || undefined });
      continue;
    }

    // group / service。
    const nm = NODE_RE.exec(line);
    if (nm) {
      const kind = nm[1].toLowerCase();
      const id = nm[2];
      const icon = nm[3]?.trim() || undefined;
      const title = nm[4]?.trim() || undefined;
      const inId = nm[5] || undefined;
      if (kind === 'group') groups.push({ id, icon, title, parent: inId });
      else services.push({ id, icon, title, group: inId });
      continue;
    }

    // 邊。
    const em = EDGE_RE.exec(line);
    if (em) {
      const from = em[1];
      const fromGroup = !!em[2];
      const fromSide = em[3] ? asSide(em[3]) : null;
      const edgeTok = em[4];
      const toSide = em[5] ? asSide(em[5]) : null;
      const to = em[6];
      const toGroup = !!em[7];
      // edge token 必須是合法的連線:核心是 '--',前後可有 '<' / '>'。
      const core = edgeTok.replace(/[<>]/g, '');
      if (core === '--') {
        edges.push({
          from,
          fromSide: fromSide ?? 'R',
          to,
          toSide: toSide ?? 'L',
          arrowFrom: edgeTok.startsWith('<'),
          arrowTo: edgeTok.endsWith('>'),
          fromGroup: fromGroup || undefined,
          toGroup: toGroup || undefined,
        });
      }
      continue;
    }

    // 其餘無法解析的行略過。
  }

  return { groups, services, junctions, edges };
}

/** 組裝 `(icon)[title]` 段(皆可選)。 */
function nodeDecor(icon?: string, title?: string): string {
  let s = '';
  if (icon) s += `(${icon})`;
  if (title) s += `[${title}]`;
  return s;
}

/** 箭頭符號:都假→'--',僅 to→'-->',僅 from→'<--',兩者→'<-->'。 */
function edgeToken(arrowFrom: boolean, arrowTo: boolean): string {
  return `${arrowFrom ? '<' : ''}--${arrowTo ? '>' : ''}`;
}

/**
 * architecture-beta 的 id 僅允許 `[A-Za-z0-9_]`(含空白 / 中文 / 點的字串要放在 title `[...]`,
 * 不能當 id,否則 mermaid lexer 直接爆)。把任意字串正規化為合法 id。
 */
export function sanitizeArchId(raw: string): string {
  let s = raw.replace(/[^A-Za-z0-9_]+/g, '_').replace(/^_+|_+$/g, '');
  if (!s) s = 'id';
  if (/^[0-9]/.test(s)) s = `n${s}`;
  return s;
}

/** 建 oldId→safeId 對照表(sanitize + 去重),供序列化時節點 / parent / group / 邊端點一致改寫。 */
function buildIdMap(m: ArchModel): Map<string, string> {
  const map = new Map<string, string>();
  const used = new Set<string>();
  for (const n of [...m.groups, ...m.services, ...m.junctions]) {
    if (map.has(n.id)) continue;
    const base = sanitizeArchId(n.id);
    let cand = base;
    let i = 2;
    while (used.has(cand)) cand = `${base}_${i++}`;
    used.add(cand);
    map.set(n.id, cand);
  }
  return map;
}

/** 模型 → 正規化 mermaid architecture-beta 文字(id 一律 sanitize 以保證可解析)。 */
export function serializeArchitecture(m: ArchModel): string {
  const idMap = buildIdMap(m);
  const idOf = (id: string) => idMap.get(id) ?? sanitizeArchId(id);
  const lines = ['architecture-beta'];

  // id 被 sanitize 改寫且本來沒 title 時,用原始 id 當 title,避免人類標籤(如中文)整個丟失。
  // title 不能含 ']'(會破壞 `[...]`),先剔除。
  const keepLabel = (rawId: string, title?: string): string | undefined => {
    if (title) return title;
    if (idOf(rawId) === rawId) return undefined;
    const t = rawId.replace(/]/g, '').trim();
    return t || undefined;
  };

  for (const g of m.groups) {
    let line = `    group ${idOf(g.id)}${nodeDecor(g.icon, keepLabel(g.id, g.title))}`;
    if (g.parent) line += ` in ${idOf(g.parent)}`;
    lines.push(line);
  }
  for (const s of m.services) {
    let line = `    service ${idOf(s.id)}${nodeDecor(s.icon, keepLabel(s.id, s.title))}`;
    if (s.group) line += ` in ${idOf(s.group)}`;
    lines.push(line);
  }
  for (const j of m.junctions) {
    let line = `    junction ${idOf(j.id)}`;
    if (j.group) line += ` in ${idOf(j.group)}`;
    lines.push(line);
  }
  for (const e of m.edges) {
    const left = `${idOf(e.from)}${e.fromGroup ? '{group}' : ''}:${e.fromSide}`;
    const right = `${e.toSide}:${idOf(e.to)}${e.toGroup ? '{group}' : ''}`;
    lines.push(`    ${left} ${edgeToken(e.arrowFrom, e.arrowTo)} ${right}`);
  }

  return lines.join('\n');
}

/** Side → 人類可讀標記(供 UI 顯示)。 */
export function sideLabel(s: Side): string {
  switch (s) {
    case 'L':
      return 'L (left)';
    case 'R':
      return 'R (right)';
    case 'T':
      return 'T (top)';
    case 'B':
      return 'B (bottom)';
  }
}

/** 內建 icon → emoji(其餘 icon 顯示名稱)。 */
export function iconEmoji(icon?: string): string | null {
  switch (icon) {
    case 'cloud':
      return '☁';
    case 'database':
      return '🗄';
    case 'disk':
      return '💾';
    case 'internet':
      return '🌐';
    case 'server':
      return '🖥';
    default:
      return null;
  }
}
