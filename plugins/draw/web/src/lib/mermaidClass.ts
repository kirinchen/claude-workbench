/**
 * mermaidClass — mermaid classDiagram 子集 的解析 / 序列化。
 *
 * 子集:
 *  - 開頭行 "classDiagram"。可選次行 "direction TB|LR|RL|BT"(預設 TB)。
 *  - 類別宣告三種:
 *      (a) 區塊:   class Animal { ... 成員 ... }
 *      (b) 行內成員: Animal : +int age   /   Animal : +eat() void
 *      (c) 裸宣告:  class Animal
 *  - 成員:[visibility][內容];visibility ∈ + - # ~(可省)。內容含 "()" 視為 method,否則 attribute。
 *  - stereotype(可選):區塊內一行 "<<interface>>" / "<<abstract>>" 等 → node.stereotype。
 *  - 關係(單行):LEFT [leftCard] <token> [rightCard] RIGHT [: label]。card 為可選引號字串。
 * 不支援(略過不丟例外):泛型 ~T~、namespace、note、click、style、cssClass。
 * GUI 存檔走 serializeClass → 正規化重寫該 mermaid 區塊(註解 / 手動排版 / 樣式會丟)。
 */

export type Visibility = '+' | '-' | '#' | '~' | '';
export type MemberKind = 'attr' | 'method';

export interface ClassMember {
  vis: Visibility;
  text: string; // 不含 visibility,如 "int age" / "eat() void"
  kind: MemberKind;
}
export interface ClassNode {
  name: string;
  stereotype?: string;
  members: ClassMember[];
}
export type ClassRelType =
  | 'inheritance'
  | 'composition'
  | 'aggregation'
  | 'association'
  | 'dependency'
  | 'realization'
  | 'solid'
  | 'dashed';
export interface ClassRel {
  left: string;
  right: string;
  type: ClassRelType;
  label?: string;
  leftCard?: string;
  rightCard?: string;
}
export interface ClassModel {
  dir: string;
  classes: ClassNode[];
  rels: ClassRel[];
}

const DIRS = new Set(['TB', 'LR', 'RL', 'BT']);
const VIS = new Set(['+', '-', '#', '~']);

/** 是否為 classDiagram。 */
export function isClassDiagram(code: string): boolean {
  return /^\s*classDiagram\b/i.test(code);
}

// 關係 token → type。長 token(含 |、..|>)排前面,避免被短形式先吃掉。
// realization(..|>)需排在 dependency(..>)前;dashed(..)排最後。
const REL_TOKENS: { token: string; type: ClassRelType }[] = [
  { token: '..|>', type: 'realization' },
  { token: '<|--', type: 'inheritance' },
  { token: '..>', type: 'dependency' },
  { token: '-->', type: 'association' },
  { token: '*--', type: 'composition' },
  { token: 'o--', type: 'aggregation' },
  { token: '..', type: 'dashed' },
  { token: '--', type: 'solid' },
];

/** type → canonical token(序列化用)。 */
function relToken(t: ClassRelType): string {
  switch (t) {
    case 'inheritance':
      return '<|--';
    case 'composition':
      return '*--';
    case 'aggregation':
      return 'o--';
    case 'association':
      return '-->';
    case 'dependency':
      return '..>';
    case 'realization':
      return '..|>';
    case 'solid':
      return '--';
    case 'dashed':
      return '..';
  }
}

// 序列化時 " escape 成 &quot;,解析時還原。
function unescape(s: string): string {
  return s.replace(/&quot;/g, '"');
}

/** 去除外層引號並還原 escape(card / label 用)。 */
function stripQuotes(s: string): string {
  const t = s.trim();
  const m = /^"(.*)"$/s.exec(t);
  return unescape(m ? m[1] : t);
}

/** 拆出成員的 visibility / text / kind。text 不含 visibility,含 "()" 視為 method。 */
function parseMember(raw: string): ClassMember | null {
  let s = raw.trim();
  if (!s) return null;
  let vis: Visibility = '';
  if (VIS.has(s[0])) {
    vis = s[0] as Visibility;
    s = s.slice(1).trim();
  }
  if (!s) return null;
  const lp = s.indexOf('(');
  const rp = s.indexOf(')');
  const kind: MemberKind = lp >= 0 && rp >= 0 && lp < rp ? 'method' : 'attr';
  return { vis, text: s, kind };
}

// 關係行:LEFT [leftCard] <token> [rightCard] RIGHT [: label]
// card 為可選引號字串(如 "1" / "0..*")。token 來自 REL_TOKENS。
const CARD = '"[^"]*"';
const ID = '[A-Za-z0-9_]+';
const REL_RE = new RegExp(
  `^(${ID})\\s+(?:(${CARD})\\s+)?` +
    `(\\.\\.\\|>|<\\|--|\\.\\.>|-->|\\*--|o--|\\.\\.|--)` +
    `\\s+(?:(${CARD})\\s+)?(${ID})(?:\\s*:\\s*(.*))?$`,
);

function relTypeFromToken(token: string): ClassRelType | null {
  return REL_TOKENS.find((r) => r.token === token)?.type ?? null;
}

/** 解析 classDiagram 子集 → 模型。無法解析的語法盡量略過,不丟例外。 */
export function parseClass(code: string): ClassModel {
  const rawLines = code.split(/\r?\n/);

  const classes = new Map<string, ClassNode>();
  const ensureClass = (name: string): ClassNode => {
    let c = classes.get(name);
    if (!c) {
      c = { name, members: [] };
      classes.set(name, c);
    }
    return c;
  };
  const rels: ClassRel[] = [];

  let dir = 'TB';
  let current: ClassNode | null = null; // 正在解析的 class 區塊

  for (let raw of rawLines) {
    // 去掉行內 / 整行 mermaid 註解(%%)。
    const cm = raw.indexOf('%%');
    if (cm >= 0) raw = raw.slice(0, cm);
    const line = raw.trim();
    if (!line) continue;
    if (/^classDiagram\b/i.test(line)) continue;

    // direction(只在頂層生效)。
    if (!current) {
      const d = /^direction\s+([A-Za-z]{2})\b/i.exec(line);
      if (d && DIRS.has(d[1].toUpperCase())) {
        dir = d[1].toUpperCase();
        continue;
      }
    }

    // 在 class 區塊內。
    if (current) {
      if (line === '}' || line.startsWith('}')) {
        current = null;
        continue;
      }
      // stereotype:<<interface>> / <<abstract>> 等。
      const st = /^<<\s*(.*?)\s*>>$/.exec(line);
      if (st) {
        current.stereotype = st[1];
        continue;
      }
      const mem = parseMember(line);
      if (mem) current.members.push(mem);
      continue;
    }

    // class 區塊開頭:`class Name {`。
    const open = /^class\s+([A-Za-z0-9_]+)\s*\{$/.exec(line);
    if (open) {
      current = ensureClass(open[1]);
      continue;
    }

    // 裸宣告:`class Name`(可能帶尾端 stereotype:class Name { 已被上面接走)。
    const decl = /^class\s+([A-Za-z0-9_]+)\s*$/.exec(line);
    if (decl) {
      ensureClass(decl[1]);
      continue;
    }

    // 行內成員:`Name : +int age` / `Name : +eat() void`。
    const inline = /^([A-Za-z0-9_]+)\s*:\s*(.*)$/.exec(line);
    if (inline && !REL_RE.test(line)) {
      const node = ensureClass(inline[1]);
      const content = inline[2].trim();
      // 行內 stereotype:`Name : <<interface>>`。
      const st = /^<<\s*(.*?)\s*>>$/.exec(content);
      if (st) {
        node.stereotype = st[1];
        continue;
      }
      const mem = parseMember(content);
      if (mem) node.members.push(mem);
      continue;
    }

    // 關係行。
    const rm = REL_RE.exec(line);
    if (rm) {
      const left = rm[1];
      const leftCard = rm[2] !== undefined ? stripQuotes(rm[2]) : undefined;
      const type = relTypeFromToken(rm[3]);
      const rightCard = rm[4] !== undefined ? stripQuotes(rm[4]) : undefined;
      const right = rm[5];
      const label = rm[6] !== undefined ? unescape(rm[6].trim()) : undefined;
      if (type) {
        ensureClass(left);
        ensureClass(right);
        rels.push({
          left,
          right,
          type,
          label: label || undefined,
          leftCard: leftCard || undefined,
          rightCard: rightCard || undefined,
        });
      }
      continue;
    }

    // 其餘無法解析的行略過(namespace、note、click、style、cssClass 等)。
  }

  return { dir, classes: [...classes.values()], rels };
}

// 文字內的 " escape 成 &quot;,避免提前閉合引號。
function escape(s: string): string {
  return s.replace(/"/g, '&quot;');
}

/** 模型 → 正規化 mermaid classDiagram 文字。 */
export function serializeClass(m: ClassModel): string {
  const lines = ['classDiagram'];
  const dir = DIRS.has(m.dir) ? m.dir : 'TB';
  if (dir !== 'TB') lines.push(`    direction ${dir}`);

  for (const c of m.classes) {
    lines.push(`    class ${c.name} {`);
    if (c.stereotype) lines.push(`        <<${c.stereotype}>>`);
    for (const mem of c.members) {
      lines.push(`        ${mem.vis}${mem.text}`);
    }
    lines.push(`    }`);
  }

  for (const r of m.rels) {
    let line = `    ${r.left} `;
    if (r.leftCard) line += `"${escape(r.leftCard)}" `;
    line += relToken(r.type);
    if (r.rightCard) line += ` "${escape(r.rightCard)}"`;
    line += ` ${r.right}`;
    if (r.label) line += ` : ${escape(r.label)}`;
    lines.push(line);
  }

  return lines.join('\n');
}
