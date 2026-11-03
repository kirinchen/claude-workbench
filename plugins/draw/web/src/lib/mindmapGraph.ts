/**
 * mindmapGraph — mindmap GUI 編輯器的「圖 ⇄ 模型」純邏輯(不碰 React / React Flow)。
 *
 * mindmap 是**單 root 嚴格樹**:每個節點恰有一條 incoming 邊(parent),root 沒有。
 * 畫布用「邊」表達階層,所以「拖把手連線」= **改 parent**:必然會把 target 原本的
 * incoming 邊換掉。這不是掉邊,是樹的不變式;UI 端要把它講清楚(見 reparentEdges
 * 回傳的 prevParent)並重新排版,否則使用者只會看到「某條既有的邊憑空消失」。
 *
 * 抽成純函式的理由:連線 → 序列化 → 讀回 的 round-trip 才能用 node:test 迴歸,
 * 不必起瀏覽器(見 mindmapGraph.test.ts)。
 */
import type { MindmapModel, MindmapNode, MindmapShape } from './mermaidMindmap.ts';

/**
 * 節點可編欄位(對應 MindmapNode,但 parent 由邊表達,不存這裡)。
 * 用 `type` 而非 `interface`:React Flow 的 `Node.data` 要求 `Record<string, unknown>`,
 * 只有 type alias 的物件型別有隱含 index signature,interface 沒有 → 會不可指派。
 */
export type MindmapNodeFields = {
  text: string;
  shape: MindmapShape;
  icon?: string;
  cls?: string;
  /** mermaid id 前綴(round-trip 用)。 */
  mid?: string;
  /** 是否為 root(視覺用;SSoT 是「無 incoming 邊」)。 */
  isRoot?: boolean;
};

/** 畫布節點的最小結構(React Flow Node 滿足之)。 */
export type MindmapGraphNode = {
  id: string;
  data: MindmapNodeFields;
};

/** 畫布邊的最小結構(React Flow Edge 滿足之)。 */
export type MindmapGraphEdge = {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

/** 預設把手(React Flow handle id;沿用 D2Editor 的 s-<SIDE> / t-<SIDE> 命名)。 */
const DEFAULT_SOURCE_HANDLE = 's-R';
const DEFAULT_TARGET_HANDLE = 't-L';

/**
 * 階層邊的 id **只由 target 決定**。
 * 「每個節點至多一條 incoming 邊」是本圖的不變式 → 以 target 當 id 天生唯一,
 * 不需要遞增序號。舊版用 `me-<source>-<target>-<seq>`,序號來源有兩套(初始邊用
 * 陣列 index、新邊用 state 計數器)→ 同一 id 空間有撞號風險,且撞號時 React 會
 * 拿同 key 蓋掉另一條邊(=真的掉邊)。改成由 target 導出即從結構上消滅這類 bug。
 */
export function hierarchyEdgeId(target: string): string {
  return `me-${target}`;
}

/** 建一條階層邊(無箭頭、無 label);handle 可帶入拖出 / 落下的實際側邊。 */
export function makeHierarchyEdge(
  source: string,
  target: string,
  sourceHandle?: string | null,
  targetHandle?: string | null,
): MindmapGraphEdge {
  return {
    id: hierarchyEdgeId(target),
    source,
    target,
    sourceHandle: sourceHandle ?? DEFAULT_SOURCE_HANDLE,
    targetHandle: targetHandle ?? DEFAULT_TARGET_HANDLE,
  };
}

/** 模型 → 階層邊:每個有 parent 的節點一條 parent → child 邊。 */
export function buildHierarchyEdges(model: MindmapModel): MindmapGraphEdge[] {
  return model.nodes
    .filter((n) => n.parent !== undefined)
    .map((n) => makeHierarchyEdge(n.parent as string, n.key));
}

/** 由 edges 建「child.id → parent.id」對照(每個節點至多一條 incoming 邊)。 */
export function buildParentMap(edges: MindmapGraphEdge[]): Map<string, string> {
  const m = new Map<string, string>();
  for (const e of edges) m.set(e.target, e.source);
  return m;
}

/** 沿 parent 鏈判斷 a 是否為 b 的祖先(含 a===b)。byParent: childId → parentId。 */
export function isAncestor(a: string, b: string, byParent: Map<string, string>): boolean {
  let cur: string | undefined = b;
  const seen = new Set<string>();
  while (cur !== undefined && !seen.has(cur)) {
    if (cur === a) return true;
    seen.add(cur);
    cur = byParent.get(cur);
  }
  return false;
}

/** 找 root:無 incoming 邊的節點 id(理論上恰一個)。 */
export function findRootId(nodeIds: string[], edges: MindmapGraphEdge[]): string | undefined {
  const hasIncoming = new Set(edges.map((e) => e.target));
  return nodeIds.find((id) => !hasIncoming.has(id));
}

/** 從 rootId 起 BFS 收集子樹所有節點 id(含自身)。 */
export function collectSubtree(rootId: string, edges: MindmapGraphEdge[]): Set<string> {
  const children = new Map<string, string[]>();
  for (const e of edges) {
    if (!children.has(e.source)) children.set(e.source, []);
    children.get(e.source)!.push(e.target);
  }
  const out = new Set<string>([rootId]);
  const queue = [rootId];
  while (queue.length) {
    const cur = queue.shift()!;
    for (const c of children.get(cur) ?? []) {
      if (!out.has(c)) {
        out.add(c);
        queue.push(c);
      }
    }
  }
  return out;
}

/**
 * 改 parent 的合法性檢查(source 要成為 target 的新 parent)。
 *  - 自連禁止。
 *  - target 不可是 root:root 原本無 incoming,給它 parent 會多出第二個 root 或成環。
 *  - 防環:source 不可是 target 的後代(含 target 自己)。
 */
export function checkReparent(
  edges: MindmapGraphEdge[],
  source: string,
  target: string,
  rootId: string | undefined,
): { ok: true } | { ok: false; reason: string } {
  if (source === target) return { ok: false, reason: '不可把節點連到自己' };
  if (target === rootId) return { ok: false, reason: '不可改 root 的 parent(mindmap 只能有一個 root)' };
  if (isAncestor(target, source, buildParentMap(edges))) {
    return { ok: false, reason: '不可把節點掛到自己的子孫底下(會形成環)' };
  }
  return { ok: true };
}

/**
 * 套用改 parent:移除 target 既有的 incoming 邊,加上 source → target 的新邊。
 * 回傳 prevParent(被換掉的舊 parent id)供 UI 明講「哪條邊被換掉了」。
 */
export function reparentEdges(
  edges: MindmapGraphEdge[],
  source: string,
  target: string,
  sourceHandle?: string | null,
  targetHandle?: string | null,
): { edges: MindmapGraphEdge[]; prevParent?: string } {
  const prevParent = edges.find((e) => e.target === target)?.source;
  const kept = edges.filter((e) => e.target !== target);
  return { edges: [...kept, makeHierarchyEdge(source, target, sourceHandle, targetHandle)], prevParent };
}

/**
 * 畫布(節點 + 邊)→ MindmapModel。
 *  - 每個節點的 parent = 其 incoming 邊的 source(無 incoming = root)。
 *  - 維持單 root:取「第一個無 parent 者」當 root;其餘無 parent 者(理論上不該出現)
 *    一律掛回 root 之下,保證恰好一個 root、不靜默丟節點。
 *  - 以 BFS 從 root 走出順序(parent 先於 child),serializeMindmap 的縮排才正確。
 */
export function graphToModel(nodes: MindmapGraphNode[], edges: MindmapGraphEdge[]): MindmapModel {
  const idSet = new Set(nodes.map((n) => n.id));
  // 端點不存在的邊不計入(理論上不會,刪節點已清邊)。
  const cleanParent = new Map<string, string>();
  for (const [child, parent] of buildParentMap(edges)) {
    if (idSet.has(child) && idSet.has(parent)) cleanParent.set(child, parent);
  }

  const noParent = nodes.filter((n) => !cleanParent.has(n.id));
  const rootNode = noParent[0] ?? nodes[0];
  if (!rootNode) return { nodes: [] };
  const extraRoots = new Set(noParent.slice(1).map((n) => n.id));

  const effParent = (id: string): string | undefined => {
    if (id === rootNode.id) return undefined;
    if (extraRoots.has(id)) return rootNode.id; // 多餘 root 掛回 root
    return cleanParent.get(id);
  };

  const children = new Map<string, string[]>();
  for (const n of nodes) {
    const p = effParent(n.id);
    if (p !== undefined) {
      if (!children.has(p)) children.set(p, []);
      children.get(p)!.push(n.id);
    }
  }
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const ordered: MindmapGraphNode[] = [];
  const seen = new Set<string>();
  const queue = [rootNode.id];
  while (queue.length) {
    const cur = queue.shift()!;
    if (seen.has(cur)) continue;
    seen.add(cur);
    const node = byId.get(cur);
    if (node) ordered.push(node);
    for (const c of children.get(cur) ?? []) if (!seen.has(c)) queue.push(c);
  }
  // 任何 BFS 沒走到的(理論上不該有)→ 補在後面,parent 補成 root。
  for (const n of nodes) if (!seen.has(n.id)) ordered.push(n);

  const mmNodes: MindmapNode[] = ordered.map((n) => ({
    key: n.id,
    mid: n.data.mid,
    text: n.data.text,
    shape: n.data.shape,
    icon: n.data.icon?.trim() || undefined,
    cls: n.data.cls?.trim() || undefined,
    parent: n.id === rootNode.id ? undefined : effParent(n.id) ?? rootNode.id,
  }));
  return { nodes: mmNodes };
}

/** 模型 → 畫布節點(data 欄位;座標由呼叫端排版)。 */
export function modelToGraphNodes(model: MindmapModel): MindmapGraphNode[] {
  const rootKey = model.nodes[0]?.key;
  return model.nodes.map((n) => ({
    id: n.key,
    data: {
      text: n.text,
      shape: n.shape,
      icon: n.icon,
      cls: n.cls,
      mid: n.mid,
      isRoot: n.key === rootKey,
    },
  }));
}
