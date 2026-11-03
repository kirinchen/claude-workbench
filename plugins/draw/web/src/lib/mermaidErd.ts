/**
 * mermaidErd — mermaid erDiagram(ERD)子集 的解析 / 序列化。
 *
 * 子集:
 *  - 開頭行 "erDiagram"。
 *  - 實體區塊(多行):`NAME { TYPE attr [PK|FK|UK ...] ["comment"] ... }`。
 *    實體也可只出現在關係中(無區塊)→ 視為無屬性實體。
 *  - 關係(單行):`LEFT <leftCard><line><rightCard> RIGHT : label`。
 * 不支援:其他 mermaid ER 進階語法 —— 超出子集,GUI 不處理(退回純文字編輯)。
 * GUI 存檔走 serializeErd → 正規化重寫該 mermaid 區塊(註解 / 手動排版會丟)。
 */

export type Card = 'zero-one' | 'one' | 'zero-many' | 'one-many';

export interface ErdAttr {
  type: string;
  name: string;
  keys: string[]; // keys ⊂ ['PK','FK','UK']
  comment?: string;
}
export interface ErdEntity {
  name: string;
  attrs: ErdAttr[];
}
export interface ErdRel {
  left: string;
  right: string;
  leftCard: Card;
  rightCard: Card;
  identifying: boolean;
  label: string;
}
export interface ErdModel {
  entities: ErdEntity[];
  rels: ErdRel[];
}

const KEY_TOKENS = new Set(['PK', 'FK', 'UK']);

/** 是否為 erDiagram。 */
export function isErd(code: string): boolean {
  return /^\s*erDiagram\b/i.test(code);
}

// 左側基數 token → Card。長形式(}o / }|)排前,避免被短形式先吃掉。
const LEFT_CARD: { token: string; card: Card }[] = [
  { token: '}o', card: 'zero-many' },
  { token: '}|', card: 'one-many' },
  { token: '|o', card: 'zero-one' },
  { token: '||', card: 'one' },
];
// 右側基數 token → Card。
const RIGHT_CARD: { token: string; card: Card }[] = [
  { token: 'o{', card: 'zero-many' },
  { token: '|{', card: 'one-many' },
  { token: 'o|', card: 'zero-one' },
  { token: '||', card: 'one' },
];

function leftCardFromToken(t: string): Card | null {
  return LEFT_CARD.find((c) => c.token === t)?.card ?? null;
}
function rightCardFromToken(t: string): Card | null {
  return RIGHT_CARD.find((c) => c.token === t)?.card ?? null;
}

function leftCardToken(c: Card): string {
  switch (c) {
    case 'zero-one':
      return '|o';
    case 'one':
      return '||';
    case 'zero-many':
      return '}o';
    case 'one-many':
      return '}|';
  }
}
function rightCardToken(c: Card): string {
  switch (c) {
    case 'zero-one':
      return 'o|';
    case 'one':
      return '||';
    case 'zero-many':
      return 'o{';
    case 'one-many':
      return '|{';
  }
}

// 實體名字元類:Unicode 字母 / 數字 / _ / -(吃中文等非 ASCII 名,否則整個實體被丟掉)。
const NAME = '[\\p{L}\\p{N}_-]+';
// 關係行:LEFT <leftCard><line><rightCard> RIGHT : label
// leftCard ∈ {|o,||,}o,}|}  line ∈ {--,..}  rightCard ∈ {o|,||,o{,|{}
const REL_RE = new RegExp(
  `^(${NAME})\\s+(\\|o|\\|\\||\\}o|\\}\\|)(--|\\.\\.)(o\\||\\|\\||o\\{|\\|\\{)\\s+(${NAME})(?:\\s*:\\s*(.*))?$`,
  'u',
);

/** 解析單個屬性行:`TYPE NAME [PK|FK|UK ...] ["comment"]`。回傳 null 表示無法解析。 */
function parseAttrLine(line: string): ErdAttr | null {
  const s = line.trim();
  if (!s) return null;
  // 先抽出尾端的 "comment"(可含空白);去頭尾引號後把 &quot; 還原成 "(對應 serialize 的 escape)。
  let comment: string | undefined;
  let rest = s;
  const cm = /"([^"]*)"\s*$/.exec(rest);
  if (cm) {
    comment = cm[1].replace(/&quot;/g, '"');
    rest = rest.slice(0, cm.index).trim();
  }
  // key 段同時用空白與逗號切分,容許 "PK,FK" / "PK, FK" / "PK FK"。
  const tokens = rest.split(/[\s,]+/).filter(Boolean);
  if (tokens.length < 2) return null;
  const type = tokens[0];
  const name = tokens[1];
  const keys = tokens
    .slice(2)
    .map((t) => t.toUpperCase())
    .filter((t) => KEY_TOKENS.has(t));
  return { type, name, keys, comment };
}

/** 解析 erDiagram 子集 → 模型。無法解析的語法盡量略過,不丟例外。 */
export function parseErd(code: string): ErdModel {
  const rawLines = code.split(/\r?\n/);

  const entities = new Map<string, ErdEntity>();
  const ensureEntity = (name: string): ErdEntity => {
    let e = entities.get(name);
    if (!e) {
      e = { name, attrs: [] };
      entities.set(name, e);
    }
    return e;
  };
  const rels: ErdRel[] = [];

  let current: ErdEntity | null = null; // 正在解析的實體區塊

  for (let raw of rawLines) {
    // 去掉行內 / 整行 mermaid 註解(%%)。
    const cm = raw.indexOf('%%');
    if (cm >= 0) raw = raw.slice(0, cm);
    const line = raw.trim();
    if (!line) continue;
    if (/^erDiagram\b/i.test(line)) continue;

    // 在實體區塊內。
    if (current) {
      if (line === '}' || line.startsWith('}')) {
        current = null;
        continue;
      }
      const attr = parseAttrLine(line);
      if (attr) current.attrs.push(attr);
      continue;
    }

    // 實體區塊開頭:`NAME {`(NAME 支援中文等非 ASCII)。
    const open = new RegExp(`^(${NAME})\\s*\\{$`, 'u').exec(line);
    if (open) {
      current = ensureEntity(open[1]);
      continue;
    }

    // 關係行。
    const rm = REL_RE.exec(line);
    if (rm) {
      const left = rm[1];
      const leftCard = leftCardFromToken(rm[2]);
      const identifying = rm[3] === '--';
      const rightCard = rightCardFromToken(rm[4]);
      const right = rm[5];
      const label = (rm[6] ?? '').trim();
      if (leftCard && rightCard) {
        ensureEntity(left);
        ensureEntity(right);
        rels.push({ left, right, leftCard, rightCard, identifying, label: label || 'rel' });
      }
      continue;
    }

    // 其餘無法解析的行略過。
  }

  return { entities: [...entities.values()], rels };
}

// comment 內的 " escape 成 &quot;,避免提前閉合引號(parseAttrLine 會還原)。
function escapeComment(s: string): string {
  return s.replace(/"/g, '&quot;');
}

/** 模型 → 正規化 mermaid erDiagram 文字。 */
export function serializeErd(m: ErdModel): string {
  const lines = ['erDiagram'];

  for (const e of m.entities) {
    if (!e.attrs.length) {
      // 無屬性實體:若它有出現在某關係中,可省略區塊;但為了讓單獨實體也保留,輸出空區塊。
      const inRel = m.rels.some((r) => r.left === e.name || r.right === e.name);
      if (inRel) continue; // 關係行會帶出這個實體,毋須區塊
      lines.push(`    ${e.name} {`);
      lines.push(`    }`);
      continue;
    }
    lines.push(`    ${e.name} {`);
    for (const a of e.attrs) {
      let line = `        ${a.type} ${a.name}`;
      const keys = a.keys.filter((k) => KEY_TOKENS.has(k.toUpperCase()));
      if (keys.length) line += ` ${keys.join(', ')}`;
      if (a.comment) line += ` "${escapeComment(a.comment)}"`;
      lines.push(line);
    }
    lines.push(`    }`);
  }

  for (const r of m.rels) {
    const token = `${leftCardToken(r.leftCard)}${r.identifying ? '--' : '..'}${rightCardToken(
      r.rightCard,
    )}`;
    const label = r.label.trim() || 'rel';
    lines.push(`    ${r.left} ${token} ${r.right} : ${label}`);
  }

  return lines.join('\n');
}

/** Card → 簡短人類可讀標記(供邊標籤顯示)。 */
export function cardSymbol(c: Card): string {
  switch (c) {
    case 'zero-one':
      return '0..1';
    case 'one':
      return '1';
    case 'zero-many':
      return '0..*';
    case 'one-many':
      return '1..*';
  }
}
