/**
 * guiSession — 跨「CM6 widget remount」保留 GUI 編輯狀態。
 *
 * 為什麼需要:GUI 編輯器存檔會 onApply 改寫文件 → MarkdownEditor 的 fence widget
 * 因內容變更而重建 → 承載編輯器的 MermaidBlock / D2Block 整個 remount,mode 與全螢幕
 * state 被重置回 preview。為支援「Ctrl+S 存檔但留在編輯器」,存檔前用 sessionKey
 * (lang:index)記下「remount 後要直接回到 GUI(及是否全螢幕)」,新元件掛載時取回並消耗。
 */
const keep = new Map<string, { full: boolean }>();

/** 標記:該 sessionKey 的元件 remount 後應直接進 GUI 模式。 */
export function markKeepGui(key: string, full: boolean): void {
  keep.set(key, { full });
}

/** 取回並消耗(只作用於緊接著的那次 remount;之後正常開檔回 preview)。 */
export function takeKeepGui(key: string | undefined): { full: boolean } | undefined {
  if (!key) return undefined;
  const v = keep.get(key);
  if (v) keep.delete(key);
  return v;
}
