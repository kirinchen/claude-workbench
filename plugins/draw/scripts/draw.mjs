#!/usr/bin/env node
/**
 * draw — /draw 的指令列入口(零依賴)。
 *
 *   draw.mjs open [path] [--cwd DIR] [--host IP] [--no-browser]
 *                                                     起 server(沒在跑才起)+ 開瀏覽器,印網址;
 *                                                     --host / env DRAW_HOST:另綁該位址(如 tailnet IP)給別台開
 *   draw.mjs status                                   server 在不在、port、版本
 *   draw.mjs stop                                     關 server(一次性的圖會一起消失)
 *   draw.mjs list                                     列一次性(memory)的圖
 *   draw.mjs get <path | mem:ID> [--index N]          印圖的原始碼(md 檔印每個圖區塊)
 *   draw.mjs summary <path | mem:ID> [--index N]      給 agent 讀的摘要:節點 / 連線 / 文字
 *   draw.mjs put mem:ID <file | ->                    改寫一次性的圖(檔案或 stdin)
 *
 * 檔案裡的圖 agent 直接讀寫檔即可;這支主要給 open 與一次性的圖用。
 */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawn } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const SERVER = path.join(ROOT, 'server', 'server.mjs');
const STATE_DIR = process.env.DRAW_STATE_DIR || path.join(os.homedir(), '.claude-workbench', 'draw');
const STATE_FILE = path.join(STATE_DIR, 'server.json');
const LOG_FILE = path.join(STATE_DIR, 'server.log');
const VERSION = JSON.parse(fs.readFileSync(path.join(ROOT, '.claude-plugin', 'plugin.json'), 'utf8')).version;

const argv = process.argv.slice(2);
const cmd = argv.shift();
const flag = (name) => {
  const i = argv.indexOf(name);
  if (i < 0) return undefined;
  const v = argv[i + 1];
  argv.splice(i, 2);
  return v;
};
const bool = (name) => {
  const i = argv.indexOf(name);
  if (i < 0) return false;
  argv.splice(i, 1);
  return true;
};

function die(msg, code = 1) {
  console.error(msg);
  process.exit(code);
}

function readState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
  } catch {
    return null;
  }
}

async function call(state, method, p, body) {
  const res = await fetch(`http://127.0.0.1:${state.port}${p}`, {
    method,
    headers: { 'X-Draw-Token': state.token, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(5000),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function alive() {
  const s = readState();
  if (!s) return null;
  try {
    const info = await call(s, 'GET', '/api/info');
    return { ...s, ...info };
  } catch {
    return null;
  }
}

async function ensureServer(host) {
  let s = await alive();
  const needHost = host && host !== '127.0.0.1' && host !== 'localhost' && !(s?.hosts || []).includes(host);
  if (s && (s.version !== VERSION || needHost)) {
    // plugin 更新過 / 要多綁一個位址 → 重開 server(一次性的圖會消失,先講)
    const why = s.version !== VERSION ? `是舊版 ${s.version},換成 ${VERSION}` : `沒綁 ${host},重開來加上`;
    console.error(`draw server ${why}(一次性的圖會清掉)`);
    await call(s, 'POST', '/api/shutdown').catch(() => {});
    await new Promise((r) => setTimeout(r, 300));
    s = null;
  }
  if (s) return s;
  fs.mkdirSync(STATE_DIR, { recursive: true });
  const log = fs.openSync(LOG_FILE, 'a');
  const args = host ? [SERVER, '--host', host] : [SERVER];
  const child = spawn(process.execPath, args, { detached: true, stdio: ['ignore', log, log] });
  child.unref();
  for (let i = 0; i < 50; i++) {
    await new Promise((r) => setTimeout(r, 100));
    s = await alive();
    if (s && s.pid === child.pid) return s;
  }
  die(`draw server 起不來,看 log:${LOG_FILE}`);
}

function openBrowser(url) {
  const plat = process.platform;
  const [bin, args] =
    plat === 'darwin' ? ['open', [url]] : plat === 'win32' ? ['cmd', ['/c', 'start', '', url]] : ['xdg-open', [url]];
  try {
    const c = spawn(bin, args, { detached: true, stdio: 'ignore' });
    c.on('error', () => {});
    c.unref();
    return true;
  } catch {
    return false;
  }
}

// ---------- 摘要 ----------

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

// ---------- 讀圖 ----------

async function loadTarget(target) {
  if (!target) die('要給 <path> 或 mem:<id>');
  if (target.startsWith('mem:')) {
    const s = await alive();
    if (!s) die('draw server 沒在跑 —— 一次性的圖已經不在了');
    const d = await call(s, 'GET', `/api/memory/${target.slice(4)}`);
    return [{ label: `mem:${d.id}(${d.name})`, kind: d.kind, code: d.code }];
  }
  const abs = path.resolve(target);
  if (!fs.existsSync(abs)) die(`找不到 ${abs}`);
  const text = fs.readFileSync(abs, 'utf8');
  const ext = path.extname(abs).toLowerCase();
  const NATIVE = { '.mmd': 'mermaid', '.mermaid': 'mermaid', '.excalidraw': 'excalidraw', '.d2': 'd2' };
  if (NATIVE[ext]) return [{ label: abs, kind: NATIVE[ext], code: text }];
  const { parseBlocks } = await import(pathToFileURL(path.join(ROOT, 'server', 'blocks.mjs')).href);
  return parseBlocks(text).map((b) => ({ label: `${abs} 第 ${b.index} 個圖(第 ${b.start + 1} 行)`, kind: b.kind, code: b.code }));
}

// ---------- main ----------

async function main() {
  switch (cmd) {
    case 'open': {
      const cwd = path.resolve(flag('--cwd') || process.cwd());
      const host = (flag('--host') || process.env.DRAW_HOST || '').trim();
      const noBrowser = bool('--no-browser');
      const target = argv[0];
      const s = await ensureServer(host);
      const q = new URLSearchParams({ cwd });
      if (target) q.set('path', path.resolve(cwd, target));
      const url = `http://127.0.0.1:${s.port}/?${q}`;
      // 別台機器用的網址:帶 token(非本機連線拿首頁要 token)
      const remote = (s.hosts || []).filter((h) => h !== '127.0.0.1');
      const remoteUrls = remote.map((h) => `http://${h.includes(':') ? `[${h}]` : h}:${s.port}/?${q}&t=${s.token}`);
      const opened = !noBrowser && openBrowser(url);
      console.log(JSON.stringify({ url, remoteUrls, opened, port: s.port, version: s.version, d2: s.d2 }));
      return;
    }
    case 'status': {
      const s = await alive();
      console.log(JSON.stringify(s ? { running: true, port: s.port, pid: s.pid, version: s.version, hosts: s.hosts, d2: s.d2 } : { running: false }));
      return;
    }
    case 'stop': {
      const s = await alive();
      if (!s) return console.log('draw server 沒在跑');
      await call(s, 'POST', '/api/shutdown').catch(() => {});
      return console.log(`draw server(pid ${s.pid})已關閉`);
    }
    case 'list': {
      const s = await alive();
      if (!s) return console.log('draw server 沒在跑(沒有一次性的圖)');
      const { drawings } = await call(s, 'GET', '/api/memory');
      if (!drawings.length) return console.log('沒有一次性的圖');
      for (const d of drawings) console.log(`mem:${d.id}  ${d.kind}  ${d.name}  ${d.updatedAt}`);
      return;
    }
    case 'get':
    case 'summary': {
      const idx = flag('--index');
      let items = await loadTarget(argv[0]);
      if (idx !== undefined) items = items.filter((_, i) => i === Number(idx));
      if (!items.length) die('這個檔裡沒有 mermaid / excalidraw / d2 圖');
      for (const it of items) {
        console.log(`## ${it.label} —— ${it.kind}`);
        console.log(cmd === 'get' ? it.code : summarize(it.kind, it.code));
        console.log();
      }
      return;
    }
    case 'put': {
      const target = argv[0];
      if (!target?.startsWith('mem:')) die('put 只用在一次性的圖(mem:<id>);檔案裡的圖請直接改檔');
      const src = argv[1];
      if (!src) die('要給來源檔,或 - 讀 stdin');
      const code = (src === '-' ? fs.readFileSync(0, 'utf8') : fs.readFileSync(src, 'utf8')).replace(/\n$/, '');
      const s = await alive();
      if (!s) die('draw server 沒在跑');
      const d = await call(s, 'PUT', `/api/memory/${target.slice(4)}`, { code });
      return console.log(`已更新 mem:${d.id}(${d.name});請使用者在瀏覽器按「重新載入」`);
    }
    default:
      die('用法:draw.mjs open|status|stop|list|get|summary|put …(見檔頭說明)', 2);
  }
}

main().catch((e) => die(e.message));
