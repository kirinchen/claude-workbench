/** md fenced block 的解析 / 改寫(server 與 CLI 共用,無副作用)。 */
export const KINDS = ['mermaid', 'excalidraw', 'd2'];

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

/** 把第 index 個 diagram block 的內容換成 code(fence 本身保留)。 */
export function replaceBlock(md, index, code) {
  const blocks = parseBlocks(md);
  const b = blocks[index];
  if (!b) throw Object.assign(new Error(`第 ${index} 個圖不存在(文件裡只有 ${blocks.length} 個)`), { status: 404 });
  const lines = md.split('\n');
  lines.splice(b.start + 1, b.end - b.start - 1, ...code.split('\n'));
  return lines.join('\n');
}

export function fenceFor(kind, code) {
  const ticks = code.includes('```') ? '````' : '```';
  return `${ticks}${kind}\n${code}\n${ticks}`;
}

