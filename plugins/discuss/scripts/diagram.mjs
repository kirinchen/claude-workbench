#!/usr/bin/env node
/**
 * diagram — 讀檔案裡的圖(零依賴)。
 *
 *   diagram.mjs summary <file> [--index N]   給 agent 讀的摘要:節點 / 連線 / 文字
 *   diagram.mjs get     <file> [--index N]   圖的原始碼
 */
import fs from 'node:fs';
import path from 'node:path';

const KINDS = ['mermaid', 'excalidraw', 'd2'];
const FENCE_OPEN = /^( {0,3})(`{3,}|~{3,})\s*([A-Za-z0-9_-]+)?[^\n]*$/;

/** 找出 md 裡所有 fenced block;回 diagram 類(mermaid/excalidraw/d2)的清單,含行範圍。 */
export function parseBlocks(md) {
  const lines = md.split('\n');
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const m = FENCE_OPEN.exec(lines[i]);
    if (!m) continue;
    const fence = m[2];
    const lang = (m[3] || '').toLowerCase();
    let j = i + 1;
    while (j < lines.length) {
      const t = lines[j].trim();
      if (t.startsWith(fence[0].repeat(fence.length)) && /^[`~]+$/.test(t)) break;
      j++;
    }
    if (KINDS.includes(lang)) {
      out.push({ index: out.length, kind: lang, start: i, end: j, code: lines.slice(i + 1, j).join('\n') });
    }
    i = j;
  }
  return out;
}

function summarizeExcalidraw(code) {
  let scene;
  try {
    scene = JSON.parse(code || '{}');
  } catch {
    return '(excalidraw JSON 壞掉,解析不了)';
  }
  const els = (scene.elements || []).filter((e) => !e.isDeleted);
  const byId = new Map(els.map((e) => [e.id, e]));
  const textOf = new Map(); // containerId → text
  for (const e of els) if (e.type === 'text' && e.containerId) textOf.set(e.containerId, (e.text || '').replace(/\n/g, ' '));
  const label = (e) => (e ? textOf.get(e.id) || e.name || `${e.type}#${e.id.slice(0, 6)}` : '?');
  const pos = (e) => `(${Math.round(e.x)},${Math.round(e.y)} ${Math.round(e.width)}×${Math.round(e.height)})`;

  const shapes = els.filter((e) => ['rectangle', 'ellipse', 'diamond', 'frame', 'image', 'embeddable'].includes(e.type));
  const links = els.filter((e) => e.type === 'arrow' || e.type === 'line');
  const freeText = els.filter((e) => e.type === 'text' && !e.containerId);
  const draws = els.filter((e) => e.type === 'freedraw');

  // 找連線端點:有綁定用綁定,沒綁定找最近的形狀(端點落在框內)。
  const hit = (x, y) => shapes.find((s) => x >= s.x - 8 && x <= s.x + s.width + 8 && y >= s.y - 8 && y <= s.y + s.height + 8);
  const ends = (a) => {
    const pts = a.points || [[0, 0]];
    const [lx, ly] = pts[pts.length - 1];
    const from = a.startBinding?.elementId ? byId.get(a.startBinding.elementId) : hit(a.x, a.y);
    const to = a.endBinding?.elementId ? byId.get(a.endBinding.elementId) : hit(a.x + lx, a.y + ly);
    return [from, to];
  };
  const inside = (t, s) => t.x >= s.x && t.y >= s.y && t.x <= s.x + s.width && t.y <= s.y + s.height;

  const out = [`excalidraw:${shapes.length} 個形狀、${links.length} 條連線、${freeText.length} 段獨立文字${draws.length ? `、${draws.length} 筆手繪` : ''}`];
  if (shapes.length) {
    out.push('', '形狀(標籤 型別 位置):');
    for (const s of shapes) {
      const within = freeText.filter((t) => inside(t, s)).map((t) => t.text.replace(/\n/g, ' '));
      const extra = !textOf.get(s.id) && within.length ? `  ← 框內文字:${within.join(' / ')}` : '';
      out.push(`- ${label(s)}  [${s.type}] ${pos(s)}${extra}`);
    }
  }
  if (links.length) {
    out.push('', '連線:');
    for (const a of links) {
      const [f, t] = ends(a);
      const arrow = a.type === 'line' ? '—' : a.startArrowhead && a.endArrowhead ? '<->' : a.startArrowhead ? '<-' : '->';
      const lbl = textOf.get(a.id);
      out.push(`- ${f ? label(f) : '(空白處)'} ${arrow} ${t ? label(t) : '(空白處)'}${lbl ? ` : ${lbl}` : ''}`);
    }
  }
  if (freeText.length) {
    out.push('', '獨立文字:');
    for (const t of freeText) out.push(`- "${(t.text || '').replace(/\n/g, ' ')}" ${pos(t)}`);
  }
  return out.join('\n');
}

function summarize(kind, code) {
  if (kind === 'excalidraw') return summarizeExcalidraw(code);
  return `${kind}(文字即原始碼):\n${code}`;
}

function die(msg, code = 1) {
  console.error(msg);
  process.exit(code);
}

const argv = process.argv.slice(2);
const cmd = argv.shift();
const i = argv.indexOf('--index');
const index = i < 0 ? undefined : Number(argv.splice(i, 2)[1]);
if (!['summary', 'get'].includes(cmd) || !argv[0]) die('用法:diagram.mjs summary|get <file> [--index N]', 2);

const abs = path.resolve(argv[0]);
if (!fs.existsSync(abs)) die(`找不到 ${abs}`);
const text = fs.readFileSync(abs, 'utf8');
const NATIVE = { '.mmd': 'mermaid', '.mermaid': 'mermaid', '.excalidraw': 'excalidraw', '.d2': 'd2' };
const native = NATIVE[path.extname(abs).toLowerCase()];
let items = native
  ? [{ label: abs, kind: native, code: text }]
  : parseBlocks(text).map((b) => ({ label: `${abs} 第 ${b.index} 個圖(第 ${b.start + 1} 行)`, kind: b.kind, code: b.code }));
if (index !== undefined) items = items.filter((_, n) => n === index);
if (!items.length) die('這個檔裡沒有 mermaid / excalidraw / d2 圖');
for (const it of items) console.log(`## ${it.label} —— ${it.kind}\n${cmd === 'get' ? it.code : summarize(it.kind, it.code)}\n`);
