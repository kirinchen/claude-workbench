#!/usr/bin/env node
/**
 * draw server — /draw 的本機小 server(零依賴,只用 Node 內建模組)。
 *
 *  - 預設只綁 127.0.0.1;`--host <IP>` / env `DRAW_HOST`(例如 tailnet IP)→ 另外再綁那個位址,
 *    讓別台機器打得開。每次啟動產生一次性 token,寫進 state 檔(~/.claude-workbench/draw/server.json)。
 *    所有 /api 都要帶 `X-Draw-Token`,並檢查 Host 頭(擋其他網頁 / DNS rebinding 偷寫檔);
 *    從非本機連進來的,首頁也要帶 `?t=<token>`(token 才不會發給同網段的任何人)。
 *    額外放行的 Host 名稱(如 MagicDNS 名)用 env `DRAW_ALLOWED_HOSTS`(逗號分隔)。
 *  - 靜態檔:plugin 的 dist/(build 好隨 plugin 發佈)。
 *  - 圖的三種存法:
 *      memory —— 只在本 process 記憶體,server 重開就沒了
 *      md     —— 寫成 markdown 的 ```mermaid / ```excalidraw / ```d2 區塊(新檔或接在既有 .md 尾端)
 *      native —— 單檔 .mmd / .excalidraw / .d2
 *  - 寫回檔案時帶 base(上次讀到的內容):檔案被別人(agent)改過 → 409,不蓋掉對方的改動。
 *
 * 用法:node server.mjs [--port 7391] [--host <IP>]
 */
import http from 'node:http';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { parseBlocks, replaceBlock, fenceFor, KINDS } from './blocks.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DIST = path.resolve(HERE, '..', 'dist');
const STATE_DIR = process.env.DRAW_STATE_DIR || path.join(os.homedir(), '.claude-workbench', 'draw');
const STATE_FILE = path.join(STATE_DIR, 'server.json');
const VERSION = JSON.parse(fs.readFileSync(path.resolve(HERE, '..', '.claude-plugin', 'plugin.json'), 'utf8')).version;

const argPort = (() => {
  const i = process.argv.indexOf('--port');
  return i > 0 ? Number(process.argv[i + 1]) : Number(process.env.DRAW_PORT || 7391);
})();

const argHost = (() => {
  const i = process.argv.indexOf('--host');
  return (i > 0 ? process.argv[i + 1] : process.env.DRAW_HOST || '').trim();
})();
if (argHost === '0.0.0.0' || argHost === '::') {
  console.error('DRAW_HOST 請給具體位址(例如 tailnet IP),不要綁全部介面');
  process.exit(2);
}
/** 要 listen 的位址:永遠有 127.0.0.1;有給 host 再加一個。 */
const BIND = [...new Set(['127.0.0.1', ...(argHost && argHost !== 'localhost' ? [argHost] : [])])];
const EXTRA_HOST_NAMES = (process.env.DRAW_ALLOWED_HOSTS || '')
  .split(',')
  .map((x) => x.trim().toLowerCase())
  .filter(Boolean);

const TOKEN = crypto.randomBytes(18).toString('base64url');
const NATIVE_EXT = { '.mmd': 'mermaid', '.mermaid': 'mermaid', '.excalidraw': 'excalidraw', '.d2': 'd2' };
const EXT_OF = { mermaid: '.mmd', excalidraw: '.excalidraw', d2: '.d2' };
const MAX_BODY = 20 * 1024 * 1024;
const D2_BIN = process.env.D2_BIN || 'd2';
const HAS_D2 = spawnSync(D2_BIN, ['--version'], { stdio: 'ignore' }).status === 0;

/** 一次性的圖(memory 模式)。id → {id, kind, name, code, updatedAt} */
const mem = new Map();

// ---------- helpers ----------

function httpError(status, message) {
  const e = new Error(message);
  e.status = status;
  return e;
}

function resolvePath(cwd, p) {
  if (typeof p !== 'string' || !p.trim()) throw httpError(400, '缺少路徑');
  let s = p.trim();
  if (s === '~' || s.startsWith('~/')) s = path.join(os.homedir(), s.slice(1));
  const base = typeof cwd === 'string' && path.isAbsolute(cwd) ? cwd : os.homedir();
  return path.resolve(base, s);
}

function stamp(text) {
  return crypto.createHash('sha1').update(text).digest('hex').slice(0, 12);
}

async function readText(abs) {
  try {
    return await fsp.readFile(abs, 'utf8');
  } catch (e) {
    if (e.code === 'ENOENT') return null;
    throw e;
  }
}

async function writeText(abs, text) {
  await fsp.mkdir(path.dirname(abs), { recursive: true });
  const tmp = `${abs}.draw-${process.pid}.tmp`;
  await fsp.writeFile(tmp, text, 'utf8');
  await fsp.rename(tmp, abs);
}

/** 讀一個檔 → 圖清單。md → 所有 diagram block;原生檔 → 單一圖。 */
async function loadFile(abs) {
  const text = await readText(abs);
  if (text === null) throw httpError(404, `找不到檔案:${abs}`);
  const ext = path.extname(abs).toLowerCase();
  if (NATIVE_EXT[ext]) {
    return { path: abs, format: 'native', stamp: stamp(text), blocks: [{ index: 0, kind: NATIVE_EXT[ext], code: text.replace(/\n$/, '') }] };
  }
  const blocks = parseBlocks(text).map(({ index, kind, code }) => ({ index, kind, code }));
  return { path: abs, format: 'md', stamp: stamp(text), blocks };
}

// ---------- API ----------

async function api(req, url, body) {
  const route = `${req.method} ${url.pathname}`;

  if (route === 'GET /api/info') {
    return { version: VERSION, d2: HAS_D2, home: os.homedir(), pid: process.pid, hosts: BIND };
  }

  if (route === 'GET /api/memory') {
    return { drawings: [...mem.values()].map(({ code, ...rest }) => ({ ...rest, bytes: code.length })) };
  }

  if (route === 'POST /api/memory') {
    const { kind, code, name } = body;
    if (!KINDS.includes(kind)) throw httpError(400, `不支援的圖型:${kind}`);
    const id = crypto.randomBytes(4).toString('hex');
    const d = { id, kind, name: name || `${kind}-${id}`, code: String(code ?? ''), updatedAt: new Date().toISOString() };
    mem.set(id, d);
    return d;
  }

  const memMatch = /^\/api\/memory\/([a-f0-9]+)$/.exec(url.pathname);
  if (memMatch) {
    const d = mem.get(memMatch[1]);
    if (!d) throw httpError(404, `一次性的圖 ${memMatch[1]} 不存在(server 重開過就沒了)`);
    if (req.method === 'GET') return d;
    if (req.method === 'PUT') {
      d.code = String(body.code ?? '');
      d.updatedAt = new Date().toISOString();
      return d;
    }
    if (req.method === 'DELETE') {
      mem.delete(d.id);
      return { ok: true };
    }
  }

  if (route === 'GET /api/file') {
    return loadFile(resolvePath(url.searchParams.get('cwd'), url.searchParams.get('path')));
  }

  // 新建:md(新檔 / 接在既有 md 尾端)或原生單檔(已存在就拒絕,不覆蓋)。
  if (route === 'POST /api/file') {
    const { cwd, kind, code = '', format } = body;
    if (!KINDS.includes(kind)) throw httpError(400, `不支援的圖型:${kind}`);
    let abs = resolvePath(cwd, body.path);
    const ext = path.extname(abs).toLowerCase();
    if (format === 'native') {
      if (!NATIVE_EXT[ext]) abs += EXT_OF[kind];
      else if (NATIVE_EXT[ext] !== kind) throw httpError(400, `${ext} 是 ${NATIVE_EXT[ext]} 的副檔名,跟圖型 ${kind} 不合`);
      if ((await readText(abs)) !== null) throw httpError(409, `檔案已存在:${abs}(不覆蓋;要改它請用「開啟既有檔案」)`);
      await writeText(abs, `${code}\n`);
      return { ...(await loadFile(abs)), index: 0 };
    }
    if (format !== 'md') throw httpError(400, 'format 要是 md 或 native');
    if (ext !== '.md' && ext !== '.markdown') abs += '.md';
    const old = await readText(abs);
    const block = fenceFor(kind, code);
    const next = old === null ? `${block}\n` : `${old.replace(/\s*$/, '')}\n\n${block}\n`;
    await writeText(abs, next);
    const loaded = await loadFile(abs);
    return { ...loaded, index: loaded.blocks.length - 1, appended: old !== null };
  }

  // 寫回:base = 上次讀到的檔案 stamp;不符 → 409(有人改過檔)。force 可略過。
  if (route === 'PUT /api/file') {
    const { cwd, index = 0, code = '', base, force } = body;
    const abs = resolvePath(cwd, body.path);
    const old = await readText(abs);
    if (old === null) throw httpError(404, `檔案不見了:${abs}`);
    if (!force && base && base !== stamp(old)) {
      throw httpError(409, '檔案在你編輯期間被改過(可能是 agent 改了圖)。重新載入看最新版,或強制覆蓋。');
    }
    const ext = path.extname(abs).toLowerCase();
    const next = NATIVE_EXT[ext] ? `${code}\n` : replaceBlock(old, Number(index), code);
    await writeText(abs, next);
    return { ...(await loadFile(abs)), index: Number(index) };
  }

  if (route === 'GET /api/scan') {
    return scanRepo(url.searchParams.get('cwd'));
  }

  if (route === 'POST /api/d2/render') {
    return { svg: await renderD2(body.src) };
  }

  if (route === 'POST /api/shutdown') {
    setTimeout(() => process.exit(0), 50);
    return { ok: true };
  }

  throw httpError(404, `沒有這個 API:${route}`);
}

// ---------- 總覽:repo 裡已有的圖 ----------

const SKIP_DIRS = new Set(['node_modules', '.git', 'dist', 'build', '.venv', 'venv', '__pycache__', '.next', 'target', '.cache']);
const MAX_SCAN_FILES = 20000;
const MAX_MD_BYTES = 2 * 1024 * 1024;

/** mermaid 第一行 → 圖型名稱(跟首頁清單同名)。 */
export function mermaidType(code) {
  const first = (code.split('\n').find((l) => l.trim() && !l.trim().startsWith('%%')) || '').trim();
  const w = first.split(/[\s;]/)[0];
  const map = {
    graph: 'Flowchart',
    flowchart: 'Flowchart',
    stateDiagram: 'State',
    'stateDiagram-v2': 'State',
    erDiagram: 'ERD',
    classDiagram: 'Class',
    sequenceDiagram: 'Sequence',
    'architecture-beta': 'Architecture',
    mindmap: 'Mind map',
  };
  return map[w] || w || 'Mermaid';
}

function blockType(kind, code) {
  if (kind === 'mermaid') return mermaidType(code);
  if (kind === 'd2') return 'D2';
  try {
    const n = (JSON.parse(code || '{}').elements || []).filter((e) => !e.isDeleted).length;
    return `Excalidraw(${n} 個元素)`;
  } catch {
    return 'Excalidraw';
  }
}

function listFiles(root) {
  const git = spawnSync('git', ['-C', root, 'ls-files', '-co', '--exclude-standard', '-z'], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
  if (git.status === 0) return git.stdout.split('\0').filter(Boolean);
  const out = [];
  const walk = (dir, depth) => {
    if (depth > 8 || out.length >= MAX_SCAN_FILES) return;
    let ents = [];
    try {
      ents = fs.readdirSync(path.join(root, dir), { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of ents) {
      if (out.length >= MAX_SCAN_FILES) return;
      const rel = dir ? `${dir}/${e.name}` : e.name;
      if (e.isDirectory()) {
        if (!SKIP_DIRS.has(e.name) && !e.name.startsWith('.')) walk(rel, depth + 1);
      } else out.push(rel);
    }
  };
  walk('', 0);
  return out;
}

async function scanRepo(cwd) {
  const base = typeof cwd === 'string' && path.isAbsolute(cwd) ? cwd : os.homedir();
  const top = spawnSync('git', ['-C', base, 'rev-parse', '--show-toplevel'], { encoding: 'utf8' });
  const root = top.status === 0 ? top.stdout.trim() : base;
  const all = listFiles(root);
  const truncated = all.length > MAX_SCAN_FILES;
  const files = [];
  for (const rel of all.slice(0, MAX_SCAN_FILES)) {
    const ext = path.extname(rel).toLowerCase();
    const isMd = ext === '.md' || ext === '.markdown';
    if (!isMd && !NATIVE_EXT[ext]) continue;
    if (rel.split('/').some((seg) => SKIP_DIRS.has(seg))) continue;
    const abs = path.join(root, rel);
    let st;
    try {
      st = await fsp.stat(abs);
    } catch {
      continue;
    }
    if (!st.isFile() || (isMd && st.size > MAX_MD_BYTES)) continue;
    const text = await readText(abs);
    if (text === null) continue;
    let blocks;
    if (isMd) {
      if (!/^\s{0,3}(`{3,}|~{3,})\s*(mermaid|excalidraw|d2)\b/im.test(text)) continue;
      blocks = parseBlocks(text).map((b) => ({ index: b.index, kind: b.kind, type: blockType(b.kind, b.code), line: b.start + 1 }));
    } else {
      blocks = [{ index: 0, kind: NATIVE_EXT[ext], type: blockType(NATIVE_EXT[ext], text), line: 1 }];
    }
    if (!blocks.length) continue;
    files.push({ path: abs, rel, format: isMd ? 'md' : 'native', mtime: st.mtime.toISOString(), blocks });
  }
  files.sort((a, b) => b.mtime.localeCompare(a.mtime));
  return { root, files, truncated };
}

function renderD2(src) {
  return new Promise((resolve, reject) => {
    if (!HAS_D2) return reject(httpError(501, '這台機器沒有 d2 指令(https://d2lang.com 安裝後重開 server)'));
    if (typeof src !== 'string' || !src.trim()) return reject(httpError(422, 'empty d2 source'));
    const child = spawn(D2_BIN, ['--no-xml-tag', '--theme=200', '-', '-'], { stdio: ['pipe', 'pipe', 'pipe'] });
    let out = '';
    let err = '';
    const timer = setTimeout(() => child.kill('SIGKILL'), 10_000);
    child.stdout.on('data', (c) => (out += c));
    child.stderr.on('data', (c) => (err += c));
    child.on('error', (e) => {
      clearTimeout(timer);
      reject(httpError(500, `d2 執行失敗:${e.message}`));
    });
    child.on('close', (codeNum) => {
      clearTimeout(timer);
      if (codeNum === 0) resolve(out);
      else reject(httpError(422, err.trim() || `d2 exit ${codeNum}`));
    });
    child.stdin.end(src);
  });
}

// ---------- static ----------

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.woff2': 'font/woff2',
  '.woff': 'font/woff',
  '.ttf': 'font/ttf',
};

function isLoopback(req) {
  const a = req.socket.remoteAddress || '';
  return a === '127.0.0.1' || a === '::1' || a === '::ffff:127.0.0.1';
}

async function serveStatic(req, url, res) {
  let rel = decodeURIComponent(url.pathname);
  if (rel === '/' || !path.extname(rel)) rel = '/index.html';
  const abs = path.resolve(DIST, `.${rel}`);
  if (!abs.startsWith(DIST + path.sep)) return send(res, 403, 'forbidden');
  let data;
  try {
    data = await fsp.readFile(abs);
  } catch {
    if (rel === '/index.html') return send(res, 500, 'dist/ 不存在:plugin 的前端還沒 build(cd web && npm i && npm run build)');
    return send(res, 404, 'not found');
  }
  if (rel === '/index.html') {
    // 別台機器連進來 → 首頁要帶 ?t=<token>,不然不發 token(只看得到說明)
    if (!isLoopback(req) && url.searchParams.get('t') !== TOKEN) {
      return send(res, 401, '這個網址少了 token。請用 /draw 印出的「別台機器用」完整網址(含 &t=…)。');
    }
    const boot = `<script>window.__DRAW__=${JSON.stringify({ token: TOKEN, version: VERSION })}</script>`;
    data = data.toString('utf8').replace('<!--DRAW_BOOT-->', boot);
    res.writeHead(200, { 'Content-Type': MIME['.html'], 'Cache-Control': 'no-store' });
    return res.end(data);
  }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(abs)] || 'application/octet-stream', 'Cache-Control': 'public, max-age=31536000, immutable' });
  res.end(data);
}

function send(res, status, body) {
  const isJson = typeof body !== 'string';
  res.writeHead(status, { 'Content-Type': isJson ? 'application/json; charset=utf-8' : 'text/plain; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(isJson ? JSON.stringify(body) : body);
}

let PORT = argPort;

const handler = async (req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
  // Host 頭只接受本機名 + 有綁的位址 + DRAW_ALLOWED_HOSTS(擋 DNS rebinding)。
  const host = (req.headers.host || '').toLowerCase();
  const okHosts = ['localhost', ...BIND, ...EXTRA_HOST_NAMES].map((h) => `${h.includes(':') ? `[${h}]` : h}:${PORT}`);
  if (!okHosts.includes(host)) return send(res, 403, 'bad host');

  if (!url.pathname.startsWith('/api/')) return serveStatic(req, url, res);
  if (req.headers['x-draw-token'] !== TOKEN) return send(res, 401, { error: 'token 不對(server 重開過?重新整理頁面或重跑 /draw)' });

  let body = {};
  if (req.method !== 'GET') {
    const chunks = [];
    let size = 0;
    for await (const c of req) {
      size += c.length;
      if (size > MAX_BODY) return send(res, 413, { error: 'too large' });
      chunks.push(c);
    }
    try {
      body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : {};
    } catch {
      return send(res, 400, { error: 'bad json' });
    }
  }
  try {
    send(res, 200, await api(req, url, body));
  } catch (e) {
    send(res, e.status || 500, { error: e.message });
  }
};

function listenOne(addr, port) {
  return new Promise((resolve, reject) => {
    const srv = http.createServer(handler);
    srv.once('error', reject);
    srv.listen(port, addr, () => resolve(srv));
  });
}

async function listen(port) {
  let first;
  try {
    first = await listenOne(BIND[0], port);
  } catch (e) {
    if (e.code !== 'EADDRINUSE') throw e;
    first = await listenOne(BIND[0], 0); // 預設 port 被佔 → 隨機
  }
  PORT = first.address().port;
  for (const addr of BIND.slice(1)) {
    try {
      await listenOne(addr, PORT);
    } catch (e) {
      console.error(`綁不到 ${addr}:${PORT}(${e.message})—— 這個位址是這台機器的嗎?`);
      process.exit(1);
    }
  }
  fs.mkdirSync(STATE_DIR, { recursive: true });
  fs.writeFileSync(
    STATE_FILE,
    JSON.stringify({ port: PORT, token: TOKEN, pid: process.pid, version: VERSION, hosts: BIND, startedAt: new Date().toISOString() }),
    { mode: 0o600 },
  );
  console.log(`draw server ${VERSION} on ${BIND.map((a) => `http://${a}:${PORT}`).join(' , ')}`);
}

const cleanup = () => {
  try {
    const s = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
    if (s.pid === process.pid) fs.unlinkSync(STATE_FILE);
  } catch {
    /* ignore */
  }
  process.exit(0);
};
process.on('SIGTERM', cleanup);
process.on('SIGINT', cleanup);
process.on('exit', () => {
  try {
    const s = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
    if (s.pid === process.pid) fs.unlinkSync(STATE_FILE);
  } catch {
    /* ignore */
  }
});

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) listen(PORT).catch((e) => {
    console.error(e.message);
    process.exit(1);
  });
