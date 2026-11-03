/**
 * mermaidSequence — mermaid sequenceDiagram 子集 的解析 / 序列化。
 *
 * 子集:
 *  - 開頭行 "sequenceDiagram"。
 *  - 參與者(順序重要):`participant A` / `participant A as Alice` / `actor A` / `actor A as Bob`。
 *    訊息引用到未宣告的參與者 → 依出現順序自動補上(participant,非 actor)。
 *  - 訊息:`FROM<arrow>TO: text`,arrow token 對應 8 種箭頭類型(見 ARROWS)。
 *    可選 inline 啟用:目標前 "+"(activate)、回覆前 "-"(deactivate),
 *    例 `A->>+B: x` / `B-->>-A: y`。
 *  - 略過不丟例外:note、loop/alt/opt/par/end、autonumber、rect、box、link/links。
 * 不支援以上略過語法的結構化編輯 —— 超出子集,GUI 不處理(序列化時會丟,已與使用者確認)。
 */

export type SeqArrow =
  | 'solid' // ->>  實心箭頭(sync)
  | 'dashed' // -->> 虛線箭頭(reply)
  | 'solidOpen' // ->  實線無箭頭
  | 'dashedOpen' // --> 虛線無箭頭
  | 'async' // -)   實線開放箭頭
  | 'asyncDashed' // --)  虛線開放箭頭
  | 'cross' // -x   實線叉
  | 'crossDashed'; // --x  虛線叉

export interface SeqParticipant {
  id: string;
  alias?: string;
  actor: boolean;
}
export interface SeqMessage {
  from: string;
  to: string;
  arrow: SeqArrow;
  text: string;
  activate?: boolean;
  deactivate?: boolean;
}
export interface SeqModel {
  participants: SeqParticipant[];
  messages: SeqMessage[];
}

// arrow token ↔ 類型。長形式(含 -- 的虛線)排前面,避免被短形式先吃掉。
const ARROWS: { token: string; arrow: SeqArrow }[] = [
  { token: '-->>', arrow: 'dashed' },
  { token: '-->', arrow: 'dashedOpen' },
  { token: '--)', arrow: 'asyncDashed' },
  { token: '--x', arrow: 'crossDashed' },
  { token: '->>', arrow: 'solid' },
  { token: '->', arrow: 'solidOpen' },
  { token: '-)', arrow: 'async' },
  { token: '-x', arrow: 'cross' },
];

/** SeqArrow → mermaid arrow token。 */
export function arrowToken(a: SeqArrow): string {
  return ARROWS.find((x) => x.arrow === a)?.token ?? '->>';
}

// 略過的區塊 / 行關鍵字(出現在行首即整行忽略,不丟例外)。
const SKIP_RE =
  /^(note\b|loop\b|alt\b|else\b|opt\b|par\b|and\b|end\b|autonumber\b|rect\b|box\b|activate\b|deactivate\b|link\b|links\b|participant\b|actor\b)/i;

/** 是否為 sequenceDiagram。 */
export function isSequence(code: string): boolean {
  return /^\s*sequenceDiagram\b/i.test(code);
}

/**
 * 解析一行訊息:`FROM<arrow>[+]TO : text`(text 在第一個 ":" 之後)。
 * 回傳 null 表示這行不是訊息(交由上層略過)。
 */
function parseMessageLine(line: string): SeqMessage | null {
  // text 在第一個 ":" 之後;箭頭與端點在 ":" 之前。
  const ci = line.indexOf(':');
  const head = (ci >= 0 ? line.slice(0, ci) : line).trim();
  const text = ci >= 0 ? line.slice(ci + 1).trim() : '';

  // 找出 head 中的 arrow token(取最先出現、且最長的匹配)。
  // id 內可能含 arrow-like 字元('-' '>' 'x' ')'),故先用正則切出 from 段
  //(不吃進箭頭起始字元 '-'),再從 from 邊界處起找 token,避免把 id 內的 '-' 當箭頭。
  const fm = /^[^\->]*/.exec(head);
  const searchStart = fm ? fm[0].length : 0;
  let best: { idx: number; token: string; arrow: SeqArrow } | null = null;
  for (const { token, arrow } of ARROWS) {
    const idx = head.indexOf(token, searchStart);
    if (idx < 0) continue;
    if (!best || idx < best.idx || (idx === best.idx && token.length > best.token.length)) {
      best = { idx, token, arrow };
    }
  }
  if (!best) return null;

  const fromRaw = head.slice(0, best.idx).trim();
  let toRaw = head.slice(best.idx + best.token.length).trim();
  if (!fromRaw || !toRaw) return null;

  // 回覆前 '-' 在來源端 → deactivate;目標前 '+' → activate。
  let activate = false;
  let deactivate = false;
  let from = fromRaw;
  if (from.startsWith('-')) {
    deactivate = true;
    from = from.slice(1).trim();
  } else if (from.startsWith('+')) {
    // 來源端 '+' 罕見,容錯吃掉
    from = from.slice(1).trim();
  }
  // 目標前可同時帶 '-'(deactivate)與 '+'(activate),例 '-+';兩者皆吃掉。
  for (;;) {
    if (toRaw.startsWith('+')) {
      activate = true;
      toRaw = toRaw.slice(1).trim();
    } else if (toRaw.startsWith('-')) {
      deactivate = true;
      toRaw = toRaw.slice(1).trim();
    } else {
      break;
    }
  }
  if (!from || !toRaw) return null;

  return {
    from,
    to: toRaw,
    arrow: best.arrow,
    text,
    activate: activate || undefined,
    deactivate: deactivate || undefined,
  };
}

/** 解析參與者宣告行:`participant A [as Alice]` / `actor A [as Bob]`。 */
function parseParticipantLine(line: string): SeqParticipant | null {
  const m = /^(participant|actor)\s+(.+)$/i.exec(line.trim());
  if (!m) return null;
  const actor = m[1].toLowerCase() === 'actor';
  const rest = m[2].trim();
  const am = /^(.+?)\s+as\s+(.+)$/i.exec(rest);
  if (am) {
    const id = am[1].trim();
    const alias = am[2].trim();
    return { id, alias: alias || undefined, actor };
  }
  return { id: rest, actor };
}

/** 解析 sequenceDiagram 子集 → 模型。無法解析的語法盡量略過,不丟例外。 */
export function parseSequence(code: string): SeqModel {
  const rawLines = code.split(/\r?\n/);

  // 以 Map 保序記錄參與者;訊息引用到未宣告者依出現順序補 participant。
  const order: string[] = [];
  const byId = new Map<string, SeqParticipant>();
  const ensure = (id: string): void => {
    if (byId.has(id)) return;
    byId.set(id, { id, actor: false });
    order.push(id);
  };
  const declare = (p: SeqParticipant): void => {
    const ex = byId.get(p.id);
    if (ex) {
      // 已被訊息預先補登 → 用顯式宣告覆寫 actor / alias。
      ex.actor = p.actor;
      if (p.alias !== undefined) ex.alias = p.alias;
      return;
    }
    byId.set(p.id, { ...p });
    order.push(p.id);
  };

  const messages: SeqMessage[] = [];

  for (let raw of rawLines) {
    // 去掉行內 / 整行 mermaid 註解(%%)。
    const cm = raw.indexOf('%%');
    if (cm >= 0) raw = raw.slice(0, cm);
    const line = raw.trim();
    if (!line) continue;
    if (/^sequenceDiagram\b/i.test(line)) continue;

    // 參與者宣告。
    if (/^(participant|actor)\b/i.test(line)) {
      const p = parseParticipantLine(line);
      if (p) declare(p);
      continue;
    }

    // 略過的區塊 / 控制行(participant/actor 已在上面處理)。
    if (SKIP_RE.test(line)) continue;

    // 訊息行。
    const msg = parseMessageLine(line);
    if (msg) {
      ensure(msg.from);
      ensure(msg.to);
      messages.push(msg);
    }
    // 其餘無法解析的行略過。
  }

  return { participants: order.map((id) => byId.get(id)!), messages };
}

/** 模型 → 正規化 mermaid sequenceDiagram 文字。 */
export function serializeSequence(m: SeqModel): string {
  const lines = ['sequenceDiagram'];

  for (const p of m.participants) {
    const kw = p.actor ? 'actor' : 'participant';
    if (p.alias && p.alias.trim()) lines.push(`    ${kw} ${p.id} as ${p.alias.trim()}`);
    else lines.push(`    ${kw} ${p.id}`);
  }

  for (const msg of m.messages) {
    const token = arrowToken(msg.arrow);
    // mermaid 的 activate / deactivate 前綴一律放在「目標」前:
    //   activate → 目標前 '+';deactivate → 目標前 '-'。
    // (放在來源前 mermaid 無法解析,故統一收斂到目標。)
    // 兩者皆有時並存,deactivate '-' 在前、activate '+' 在後(例 '-+')。
    const prefix = `${msg.deactivate ? '-' : ''}${msg.activate ? '+' : ''}`;
    lines.push(`    ${msg.from}${token}${prefix}${msg.to}: ${msg.text}`);
  }

  return lines.join('\n');
}
