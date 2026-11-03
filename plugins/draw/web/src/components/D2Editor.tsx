/**
 * D2Editor — D2(https://d2lang.com)子集 的 GUI 編輯器(React Flow + dagre 近似排版)。
 *  以 ArchitectureEditor 為藍本,但支援 D2 的「容器對容器」邊(architecture-beta 做不到)。
 *  - 解析 D2 → container(parent 容器,可當邊端點)/ shape(葉節點)/ 邊。
 *  - container 與 shape 都有四邊 source+target Handle;任意兩節點(含 container)可連。
 *  - double-click 節點 → 改 local id / label / 所屬 container;double-click 邊 → 改 arrow / label / 刪。
 *  - 拖把手連線 → 新增邊(預設 '->');Delete 刪選取;按鈕新增 shape / container。
 *  - 「套用」→ serializeD2 → onSave;「取消」→ onClose。
 *
 *  fullId 是 D2Model 主鍵且隨 parent 變動。本元件不在編輯期維護 fullId,而以 React Flow
 *  的 parentId 鏈為拓樸 SSoT,在「改 id / 改 container」與「存檔」時統一由 parentId 鏈重建
 *  所有節點 fullId,並同步 node.id 與 edges 的 source/target,確保 round-trip 不壞。
 *
 *  D2 layout(dagre)約束:container 不能連到自己的後代 / 祖先,也不能自連 → onConnect 與
 *  存檔皆過濾此類非法邊。
 *
 *  本元件較重(React Flow + dagre)→ 由上層以 lazy + Suspense 載入。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  NodeResizer,
  Position,
  MarkerType,
  addEdge,
  applyNodeChanges,
  applyEdgeChanges,
  type Node,
  type Edge,
  type Connection,
  type NodeChange,
  type EdgeChange,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from '@dagrejs/dagre';
import { Button, Modal, Input, Select, Space, Typography, message } from 'antd';
import {
  PlusOutlined,
  UndoOutlined,
  RedoOutlined,
  ApartmentOutlined,
} from '@ant-design/icons';
import {
  parseD2,
  serializeD2,
  type D2Arrow,
  type D2Model,
  type D2Node,
  type D2Edge,
} from '../lib/d2';

/** 側邊 ∈ L/R/T/B(沿用 ArchitectureEditor 的 handle 命名)。 */
type Side = 'L' | 'R' | 'T' | 'B';

const ARROW_OPTS: { value: D2Arrow; label: string }[] = [
  { value: '->', label: '指向終點 (->)' },
  { value: '<-', label: '指向起點 (<-)' },
  { value: '<->', label: '雙向 (<->)' },
  { value: '--', label: '無箭頭 (--)' },
];

const SHAPE_W = 120;
const SHAPE_H = 56;
const GROUP_PAD = 40;

/** Side → React Flow Position。 */
function sidePos(s: Side): Position {
  switch (s) {
    case 'L':
      return Position.Left;
    case 'R':
      return Position.Right;
    case 'T':
      return Position.Top;
    case 'B':
      return Position.Bottom;
  }
}

/** 由 sourceHandle / targetHandle id(如 "s-R" / "t-L")取側邊。 */
function handleSide(h: string | null | undefined, fallback: Side): Side {
  if (!h) return fallback;
  const c = h.slice(-1).toUpperCase();
  return c === 'L' || c === 'R' || c === 'T' || c === 'B' ? (c as Side) : fallback;
}

/** node.data 形狀:localId = 末段 id;label;fullId(僅快照,SSoT 是 parentId 鏈)。 */
type D2NodeData = {
  localId: string;
  label?: string;
  fullId: string;
};

/** edge.data 形狀:arrow / label。 */
type D2EdgeData = {
  arrow: D2Arrow;
  label?: string;
};

const SIDES: Side[] = ['L', 'R', 'T', 'B'];

/** container 與 shape 共用:四邊各放 source+target Handle(D2 容器也能當邊端點)。 */
function FourSideHandles({ color }: { color: string }) {
  return (
    <>
      {SIDES.map((s) => (
        <span key={s}>
          <Handle
            id={`t-${s}`}
            type="target"
            position={sidePos(s)}
            style={{ background: color, width: 9, height: 9, zIndex: 10 }}
          />
          <Handle
            id={`s-${s}`}
            type="source"
            position={sidePos(s)}
            style={{ background: color, width: 9, height: 9, zIndex: 10 }}
          />
        </span>
      ))}
    </>
  );
}

/** 自訂節點:shape = 方框 + label;四邊 source+target Handle。 */
function ShapeNode({ data }: NodeProps) {
  const d = data as D2NodeData;
  return (
    <div
      style={{
        position: 'relative',
        width: SHAPE_W,
        height: SHAPE_H,
        border: '1px solid #555',
        borderRadius: 6,
        background: 'var(--card)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 12,
        fontWeight: 600,
        boxSizing: 'border-box',
        padding: '0 8px',
        textAlign: 'center',
        overflow: 'hidden',
      }}
    >
      <span
        style={{
          maxWidth: '100%',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
        {d.label || d.localId}
      </span>
      <FourSideHandles color="#555" />
    </div>
  );
}

/** 自訂節點:container(group)= 虛線框 + 標題 + NodeResizer;四邊 source+target Handle。 */
function GroupNode({ data, selected }: NodeProps) {
  const d = data as D2NodeData;
  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        border: '1px dashed #888',
        borderRadius: 8,
        background: 'rgba(0,0,0,0.02)',
        boxSizing: 'border-box',
      }}
    >
      {/* 選取時出現把手,可縮放 container(applyNodeChanges 寫回 style 尺寸)。 */}
      <NodeResizer isVisible={selected} minWidth={SHAPE_W + GROUP_PAD} minHeight={SHAPE_H + GROUP_PAD} />
      <div
        style={{
          position: 'absolute',
          top: 4,
          left: 8,
          fontSize: 12,
          fontWeight: 600,
          color: '#555',
          pointerEvents: 'none',
        }}
      >
        {d.label || d.localId}
      </div>
      {/* container 也能當邊端點 → 藍色把手,zIndex 高於子節點以便在邊框上仍可抓到。 */}
      <FourSideHandles color="var(--accent)" />
    </div>
  );
}

interface Props {
  code: string;
  /** opts.stay=true:寫回但留在 GUI(Ctrl+S / 儲存);否則寫回並回 preview(套用)。 */
  onSave: (code: string, opts?: { stay?: boolean }) => void;
  onClose: () => void;
  /** 滿版模式:撐滿父容器高度(由上層全螢幕切換帶入)。 */
  fill?: boolean;
}

type Snap = { nodes: Node[]; edges: Edge[] };

/** dagre 近似排版(僅排無 parent 的頂層節點;container 子節點維持相對座標)。 */
function layout(nodes: Node[], edges: Edge[]): Node[] {
  const top = nodes.filter((n) => !n.parentId);
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 48, ranksep: 80 });
  g.setDefaultEdgeLabel(() => ({}));
  top.forEach((n) => {
    const w = typeof n.style?.width === 'number' ? n.style.width : SHAPE_W;
    const h = typeof n.style?.height === 'number' ? n.style.height : SHAPE_H;
    g.setNode(n.id, { width: w, height: h });
  });
  edges.forEach((e) => {
    if (top.some((n) => n.id === e.source) && top.some((n) => n.id === e.target)) {
      g.setEdge(e.source, e.target);
    }
  });
  dagre.layout(g);
  return nodes.map((n) => {
    if (n.parentId) return n; // 子節點維持相對座標
    const p = g.node(n.id);
    if (!p) return n;
    const w = typeof n.style?.width === 'number' ? n.style.width : SHAPE_W;
    const h = typeof n.style?.height === 'number' ? n.style.height : SHAPE_H;
    return { ...n, position: { x: p.x - w / 2, y: p.y - h / 2 } };
  });
}

/**
 * 拓樸排序:parent 節點必排在子節點之前(React Flow 要求,否則子節點脫離容器、位置錯亂)。
 * 用於 init 與「改所屬 container」之後。
 */
function topoSortNodes(nodes: Node[]): Node[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const sorted: Node[] = [];
  const seen = new Set<string>();
  const visit = (n: Node) => {
    if (seen.has(n.id)) return;
    seen.add(n.id);
    const parent = n.parentId ? byId.get(String(n.parentId)) : undefined;
    if (parent) visit(parent);
    sorted.push(n);
  };
  for (const n of nodes) visit(n);
  return sorted;
}

/** 由 markerStart/markerEnd 帶出 arrow 對應的箭頭(<- 或 <-> 有 start;-> 或 <-> 有 end)。 */
function markersFor(arrow: D2Arrow) {
  return {
    markerStart: arrow === '<-' || arrow === '<->' ? { type: MarkerType.ArrowClosed } : undefined,
    markerEnd: arrow === '->' || arrow === '<->' ? { type: MarkerType.ArrowClosed } : undefined,
  };
}

/**
 * 由 React Flow 節點集合,依 parentId 鏈重建每個 node 的 fullId。
 * 回傳 oldId → newFullId 對照,供同步 node.id 與 edges 端點。
 * localId 取自 node.data.localId(fallback 現有 id 末段)。
 */
function rebuildFullIds(nodes: Node[]): Map<string, string> {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const localOf = (n: Node): string => {
    const d = n.data as Partial<D2NodeData>;
    const lid = d.localId ?? n.id.split('.').pop() ?? n.id;
    return String(lid);
  };
  const cache = new Map<string, string>();
  const resolve = (n: Node, seen: Set<string>): string => {
    if (cache.has(n.id)) return cache.get(n.id)!;
    if (seen.has(n.id)) return localOf(n); // 防環(理論上不會發生)
    seen.add(n.id);
    const parent = n.parentId ? byId.get(String(n.parentId)) : undefined;
    const full = parent ? `${resolve(parent, seen)}.${localOf(n)}` : localOf(n);
    cache.set(n.id, full);
    return full;
  };
  const map = new Map<string, string>();
  for (const n of nodes) map.set(n.id, resolve(n, new Set()));
  return map;
}

/**
 * 套用 rebuildFullIds 的結果:把 node.id / parentId / data.fullId 與 edges 的 source/target
 * 一次性改寫成新 fullId。回傳新的 nodes / edges。
 */
function applyFullIds(nodes: Node[], edges: Edge[], map: Map<string, string>): { nodes: Node[]; edges: Edge[] } {
  const newNodes = nodes.map((n) => {
    const nid = map.get(n.id) ?? n.id;
    const pid = n.parentId ? map.get(String(n.parentId)) ?? String(n.parentId) : undefined;
    const data = { ...(n.data as D2NodeData), fullId: nid };
    const next: Node = { ...n, id: nid, data };
    if (pid !== undefined) next.parentId = pid;
    else delete next.parentId;
    return next;
  });
  const newEdges = edges.map((e) => ({
    ...e,
    source: map.get(e.source) ?? e.source,
    target: map.get(e.target) ?? e.target,
  }));
  return { nodes: newNodes, edges: newEdges };
}

/**
 * 沿 parentId 鏈判斷 a 是否為 b 的祖先(含 a===b)。
 * byParent: nodeId → parentId(string | undefined)。
 */
function isAncestor(a: string, b: string, byParent: Map<string, string | undefined>): boolean {
  let cur: string | undefined = b;
  const seen = new Set<string>();
  while (cur !== undefined && !seen.has(cur)) {
    if (cur === a) return true;
    seen.add(cur);
    cur = byParent.get(cur);
  }
  return false;
}

/**
 * 判斷一條邊是否為 D2 非法邊:
 *  - 自連(from === to)
 *  - container 連到自己的後代或祖先(任一端是另一端的祖先 → 用雙向祖先判斷涵蓋兩種)
 * from/to 為 React Flow node.id(= fullId)。
 */
function isIllegalEdge(from: string, to: string, byParent: Map<string, string | undefined>): boolean {
  if (from === to) return true;
  // from 是 to 的祖先 → container→後代;to 是 from 的祖先 → container→祖先。皆非法。
  if (isAncestor(from, to, byParent)) return true;
  if (isAncestor(to, from, byParent)) return true;
  return false;
}

export default function D2Editor({ code, onSave, onClose, fill }: Props) {
  const nodeTypes = useMemo(
    () => ({
      d2shape: ShapeNode,
      d2group: GroupNode,
    }),
    [],
  );

  const init = useMemo(() => {
    const model = parseD2(code);

    // 子節點數,用於估算 container 大小與相對鋪排。
    const childCount = new Map<string, number>();
    for (const n of model.nodes) {
      if (n.parent) childCount.set(n.parent, (childCount.get(n.parent) ?? 0) + 1);
    }

    // container 視為 d2group,shape 視為 d2shape。node.id 用 fullId。
    const placedInGroup = new Map<string, number>();
    const childPos = (parent: string) => {
      const idx = placedInGroup.get(parent) ?? 0;
      placedInGroup.set(parent, idx + 1);
      const cols = Math.max(1, Math.ceil(Math.sqrt(childCount.get(parent) ?? 1)));
      const col = idx % cols;
      const row = Math.floor(idx / cols);
      return { x: GROUP_PAD / 2 + col * (SHAPE_W + 24), y: GROUP_PAD + row * (SHAPE_H + 24) };
    };

    const rfNodes: Node[] = model.nodes.map((n) => {
      const data: D2NodeData = { localId: n.id, label: n.label, fullId: n.fullId };
      const base: Node = {
        id: n.fullId,
        type: n.container ? 'd2group' : 'd2shape',
        data,
        position: n.parent ? childPos(n.parent) : { x: 0, y: 0 },
        ...(n.parent ? { parentId: n.parent, extent: 'parent' as const } : {}),
      };
      if (n.container) {
        const cnt = childCount.get(n.fullId) ?? 0;
        const cols = Math.max(1, Math.ceil(Math.sqrt(cnt)));
        const rows = Math.max(1, Math.ceil(cnt / cols));
        base.style = {
          width: cols * (SHAPE_W + 24) + GROUP_PAD,
          height: rows * (SHAPE_H + 24) + GROUP_PAD + 16,
        };
      } else {
        base.style = { width: SHAPE_W, height: SHAPE_H };
      }
      return base;
    });

    const rfEdges: Edge[] = model.edges.map((e, i) => {
      const data: D2EdgeData = { arrow: e.arrow, label: e.label };
      return {
        id: `e${i}-${e.from}-${e.to}`,
        source: e.from,
        target: e.to,
        sourceHandle: 's-R',
        targetHandle: 't-L',
        label: e.label,
        data,
        ...markersFor(e.arrow),
      };
    });

    // parent 節點需排在子節點之前(React Flow 要求)。
    return { nodes: layout(topoSortNodes(rfNodes), rfEdges), edges: rfEdges };
  }, [code]);

  const [nodes, setNodes] = useState<Node[]>(init.nodes);
  const [edges, setEdges] = useState<Edge[]>(init.edges);

  // 雙擊編輯:節點 / 邊。
  const [editNode, setEditNode] = useState<{
    id: string;
    kind: 'd2shape' | 'd2group';
    localId: string;
    label: string;
    parent: string; // 所屬 container 的 node.id(fullId);''=頂層
  } | null>(null);
  const [editEdge, setEditEdge] = useState<{
    id: string;
    arrow: D2Arrow;
    label: string;
  } | null>(null);
  const [adding, setAdding] = useState<{ kind: 'd2shape' | 'd2group'; id: string } | null>(null);

  // 復原 / 重做快照堆疊。
  const [past, setPast] = useState<Snap[]>([]);
  const [future, setFuture] = useState<Snap[]>([]);

  const takeSnapshot = useCallback(() => {
    setPast((p) => [...p.slice(-49), { nodes, edges }]);
    setFuture([]);
  }, [nodes, edges]);

  const undo = useCallback(() => {
    if (!past.length) return;
    const prev = past[past.length - 1];
    setFuture((f) => [{ nodes, edges }, ...f]);
    setPast((p) => p.slice(0, -1));
    setNodes(prev.nodes);
    setEdges(prev.edges);
  }, [past, nodes, edges]);

  const redo = useCallback(() => {
    if (!future.length) return;
    const next = future[0];
    setPast((p) => [...p, { nodes, edges }]);
    setFuture((f) => f.slice(1));
    setNodes(next.nodes);
    setEdges(next.edges);
  }, [future, nodes, edges]);

  // saveRef:讓 onKeyDown 取到最新 save(save 定義在後且依賴 nodes/edges,避免 stale 閉包)。
  const saveRef = useRef<(stay?: boolean) => void>(() => {});

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      const k = e.key.toLowerCase();
      if (k === 'z' && !e.shiftKey) {
        e.preventDefault();
        undo();
      } else if (k === 'y' || (k === 'z' && e.shiftKey)) {
        e.preventDefault();
        redo();
      }
    },
    [undo, redo],
  );

  // Ctrl+S = 存檔但留在編輯器。綁 window(不限 canvas 焦點,點過工具列/Modal 也有效)。
  useEffect(() => {
    const onWinKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        saveRef.current(true);
      }
    };
    window.addEventListener('keydown', onWinKey);
    return () => window.removeEventListener('keydown', onWinKey);
  }, []);

  const onNodesChange = useCallback(
    (c: NodeChange[]) => {
      if (c.some((x) => x.type === 'remove')) takeSnapshot();
      setNodes((n) => applyNodeChanges(c, n));
    },
    [takeSnapshot],
  );
  const onEdgesChange = useCallback(
    (c: EdgeChange[]) => {
      if (c.some((x) => x.type === 'remove')) takeSnapshot();
      setEdges((e) => applyEdgeChanges(c, e));
    },
    [takeSnapshot],
  );

  const onConnect = useCallback(
    (c: Connection) => {
      if (!c.source || !c.target) return;
      const byParent = new Map(nodes.map((n) => [n.id, n.parentId ? String(n.parentId) : undefined]));
      // 擋 D2 非法邊:自連 / container↔後代 / container↔祖先。
      if (isIllegalEdge(c.source, c.target, byParent)) {
        if (c.source === c.target) message.warning('不可建立自連邊(D2 不允許節點連到自己)');
        else message.warning('不可建立 container 與其後代 / 祖先之間的邊(D2 layout 會編譯失敗)');
        return;
      }
      const fromSide = handleSide(c.sourceHandle, 'R');
      const toSide = handleSide(c.targetHandle, 'L');
      takeSnapshot();
      const data: D2EdgeData = { arrow: '->' };
      setEdges((e) =>
        addEdge(
          {
            source: c.source!,
            target: c.target!,
            id: `e-${c.source}-${c.target}-${e.length}`,
            sourceHandle: `s-${fromSide}`,
            targetHandle: `t-${toSide}`,
            data,
            ...markersFor('->'),
          },
          e,
        ),
      );
    },
    [nodes, takeSnapshot],
  );

  const reLayout = () => setNodes((n) => layout(n, edges));

  // 新增 shape / container。
  const doAdd = () => {
    if (!adding) return;
    const id = adding.id.trim();
    if (!id) return;
    if (nodes.some((n) => n.id === id)) {
      message.error(`id「${id}」已存在`);
      return;
    }
    takeSnapshot();
    const data: D2NodeData = { localId: id, label: undefined, fullId: id };
    if (adding.kind === 'd2group') {
      // container 須排在子節點之前 → 放陣列最前。
      setNodes((n) => [
        {
          id,
          type: 'd2group',
          data,
          position: { x: 40, y: 40 },
          style: { width: SHAPE_W + GROUP_PAD, height: SHAPE_H + GROUP_PAD + 16 },
        },
        ...n,
      ]);
    } else {
      setNodes((n) => [
        ...n,
        {
          id,
          type: 'd2shape',
          data,
          position: { x: 60, y: 60 },
          style: { width: SHAPE_W, height: SHAPE_H },
        },
      ]);
    }
    setAdding(null);
  };

  /**
   * 套用節點編輯:改 local id / label / 所屬 container。
   * 流程:先把 localId / parentId 在「目前 node.id 命名空間」更新,再以 rebuildFullIds
   * 沿 parentId 鏈重算所有 fullId,一次性改寫 node.id / parentId / data.fullId 與 edges 端點,
   * 讓 fullId 與 edges 永遠一致(避免改 id / 改 parent 後 round-trip 壞掉)。
   */
  const applyNode = () => {
    if (!editNode) return;
    const newLocal = editNode.localId.trim();
    if (!newLocal) {
      message.error('local id 不可為空');
      return;
    }
    const oldId = editNode.id;
    // 設 parentId 前確認該 container 仍存在;不存在則清為頂層。
    const parentExists = nodes.some((n) => n.id === editNode.parent && n.type === 'd2group');
    const parentSel = editNode.parent && parentExists ? editNode.parent : undefined;

    // 同層 local id 衝突檢查(同一 parent 下 local id 須唯一)。
    const siblingClash = nodes.some((n) => {
      if (n.id === oldId) return false;
      const np = n.parentId ? String(n.parentId) : undefined;
      if (np !== parentSel) return false;
      const lid = (n.data as Partial<D2NodeData>).localId ?? n.id.split('.').pop();
      return lid === newLocal;
    });
    if (siblingClash) {
      message.error(`同一層已有 local id「${newLocal}」`);
      return;
    }

    takeSnapshot();
    // 第一步:在現有命名空間更新目標節點的 localId / label / type / parentId。
    const staged = nodes.map((n) => {
      if (n.id !== oldId) return n;
      const data: D2NodeData = {
        ...(n.data as D2NodeData),
        localId: newLocal,
        label: editNode.label.trim() || undefined,
      };
      const next: Node = { ...n, data };
      if (parentSel) {
        next.parentId = parentSel;
        next.extent = 'parent';
      } else {
        delete next.parentId;
        delete next.extent;
      }
      return next;
    });
    // 第二步:沿 parentId 鏈重建所有 fullId,並改寫 node.id / parentId / edges。
    const map = rebuildFullIds(staged);
    const rebuilt = applyFullIds(staged, edges, map);
    // 改 parent 後重排,確保 parent 仍在子節點之前(否則 React Flow 子節點脫框)。
    setNodes(topoSortNodes(rebuilt.nodes));
    setEdges(rebuilt.edges);
    setEditNode(null);
  };

  const applyEdge = () => {
    if (!editEdge) return;
    takeSnapshot();
    setEdges((es) =>
      es.map((e) => {
        if (e.id !== editEdge.id) return e;
        const data: D2EdgeData = { arrow: editEdge.arrow, label: editEdge.label.trim() || undefined };
        return {
          ...e,
          data,
          label: data.label,
          ...markersFor(editEdge.arrow),
        };
      }),
    );
    setEditEdge(null);
  };

  const deleteEdge = () => {
    if (!editEdge) return;
    takeSnapshot();
    setEdges((es) => es.filter((e) => e.id !== editEdge.id));
    setEditEdge(null);
  };

  /**
   * 存檔:React Flow → D2Model → serializeD2 → onSave。
   *  - 存檔前再以 rebuildFullIds 統一重建 fullId(防編輯期殘留不一致)。
   *  - container 由 node.type 判定;parent 由 parentId 還原。
   *  - edges 由 node.id(= fullId)取 from/to + data.arrow/label。
   *  - 序列化前再次過濾 D2 非法邊(自連 / container↔後代 / 端點不存在)。
   */
  const save = (stay = false) => {
    // 統一重建 fullId(確保 node.id 與 edges 端點一致)。
    const map = rebuildFullIds(nodes);
    const { nodes: fnodes, edges: fedges } = applyFullIds(nodes, edges, map);

    const idSet = new Set(fnodes.map((n) => n.id));
    const byParent = new Map(fnodes.map((n) => [n.id, n.parentId ? String(n.parentId) : undefined]));

    const d2nodes: D2Node[] = fnodes.map((n) => {
      const d = n.data as D2NodeData;
      return {
        id: d.localId,
        fullId: n.id,
        label: d.label?.trim() || undefined,
        parent: n.parentId ? String(n.parentId) : undefined,
        container: n.type === 'd2group',
      };
    });

    const d2edges: D2Edge[] = fedges.flatMap((e) => {
      // 端點已不存在 → 丟棄。
      if (!idSet.has(e.source) || !idSet.has(e.target)) return [];
      // D2 非法邊(自連 / container↔後代 / 祖先)→ 序列化前過濾。
      if (isIllegalEdge(e.source, e.target, byParent)) return [];
      const d = (e.data ?? { arrow: '->' }) as D2EdgeData;
      return [{ from: e.source, to: e.target, arrow: d.arrow ?? '->', label: d.label?.trim() || undefined }];
    });

    const model: D2Model = { nodes: d2nodes, edges: d2edges };
    onSave(serializeD2(model), { stay });
  };
  saveRef.current = save; // 每次 render 更新,供 Ctrl+S 取最新

  // container Select 選項(自身不可當自己的 parent;亦排除自己的後代,避免造環)。
  const containerOptions = useMemo(() => {
    const byParent = new Map(nodes.map((n) => [n.id, n.parentId ? String(n.parentId) : undefined]));
    return nodes
      .filter((n) => n.type === 'd2group')
      .filter((n) => !editNode || (n.id !== editNode.id && !isAncestor(editNode.id, n.id, byParent)))
      .map((n) => {
        const d = n.data as D2NodeData;
        return { value: n.id, label: d.label ? `${d.localId} (${d.label})` : d.localId };
      });
  }, [nodes, editNode]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: fill ? '100%' : '70vh' }}>
      <Space wrap style={{ marginBottom: 8 }}>
        <Button
          icon={<PlusOutlined />}
          onClick={() => setAdding({ kind: 'd2shape', id: '' })}
          data-loc="d2:add-shape"
        >
          新增 shape
        </Button>
        <Button
          icon={<ApartmentOutlined />}
          onClick={() => setAdding({ kind: 'd2group', id: '' })}
          data-loc="d2:add-container"
        >
          新增 container
        </Button>
        <Space.Compact>
          <Button
            size="small"
            icon={<UndoOutlined />}
            disabled={!past.length}
            onClick={undo}
            title="復原(Ctrl+Z)"
            data-loc="d2:undo"
          />
          <Button
            size="small"
            icon={<RedoOutlined />}
            disabled={!future.length}
            onClick={redo}
            title="重做(Ctrl+Y)"
            data-loc="d2:redo"
          />
        </Space.Compact>
        <Button
          size="small"
          onClick={() => {
            takeSnapshot();
            reLayout();
          }}
          data-loc="d2:layout"
        >
          自動排版
        </Button>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          雙擊節點改 id/label/container · 雙擊邊改箭頭/label · 拖把手連線 · Delete 刪 · Ctrl+Z/Y
        </Typography.Text>
      </Space>

      <div
        style={{
          flex: 1,
          border: '1px solid var(--line)',
          borderRadius: 8,
          minHeight: 0,
          outline: 'none',
        }}
        tabIndex={0}
        onKeyDown={onKeyDown}
        data-loc="d2:canvas"
      >
        <ReactFlow
          colorMode="dark"
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeDragStart={() => takeSnapshot()}
          onNodeDoubleClick={(_e, n) => {
            const d = n.data as D2NodeData;
            setEditNode({
              id: n.id,
              kind: n.type === 'd2group' ? 'd2group' : 'd2shape',
              localId: d.localId,
              label: d.label ?? '',
              parent: n.parentId ? String(n.parentId) : '',
            });
          }}
          nodeTypes={nodeTypes}
          onEdgeDoubleClick={(_e, ed) => {
            const d = (ed.data ?? { arrow: '->' }) as D2EdgeData;
            setEditEdge({
              id: ed.id,
              arrow: d.arrow ?? '->',
              label: d.label ?? '',
            });
          }}
          deleteKeyCode={['Delete', 'Backspace']}
          fitView
        >
          <Background />
          <Controls />
          <MiniMap pannable zoomable />
        </ReactFlow>
      </div>

      <Space style={{ marginTop: 8, justifyContent: 'flex-end' }}>
        <Button onClick={onClose} data-loc="d2:cancel">
          取消
        </Button>
        <Button onClick={() => save(true)} title="存檔但留在編輯器(Ctrl+S)" data-loc="d2:save">
          儲存
        </Button>
        <Button type="primary" onClick={() => save(false)} data-loc="d2:apply">
          套用
        </Button>
      </Space>

      {/* 節點編輯:local id / label / 所屬 container */}
      <Modal
        title={editNode?.kind === 'd2group' ? '編輯 container' : '編輯 shape'}
        open={!!editNode}
        onOk={applyNode}
        onCancel={() => setEditNode(null)}
        okText="確定"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <span>
            local id{' '}
            <Input
              style={{ width: 240 }}
              value={editNode?.localId ?? ''}
              onChange={(e) => {
                const v = e.target.value.replace(/[^A-Za-z0-9_]+/g, '_'); // id 僅允許 \w(空白/中文→_)
                setEditNode((s) => (s ? { ...s, localId: v } : s));
              }}
              data-loc="d2:node-id"
            />
          </span>
          <span>
            label{' '}
            <Input
              style={{ width: 240 }}
              value={editNode?.label ?? ''}
              onChange={(e) => setEditNode((s) => (s ? { ...s, label: e.target.value } : s))}
              placeholder="(可空白,省略時以 id 當 label)"
              data-loc="d2:node-label"
            />
          </span>
          <span>
            所屬 container{' '}
            <Select
              style={{ width: 240 }}
              allowClear
              value={editNode?.parent || undefined}
              onChange={(v?: string) => setEditNode((s) => (s ? { ...s, parent: v ?? '' } : s))}
              placeholder="(頂層)"
              options={containerOptions}
              data-loc="d2:node-parent"
            />
          </span>
        </Space>
      </Modal>

      {/* 邊編輯:arrow / label / 刪除 */}
      <Modal
        title="編輯連線"
        open={!!editEdge}
        onOk={applyEdge}
        onCancel={() => setEditEdge(null)}
        okText="確定"
        cancelText="取消"
        footer={[
          <Button key="del" danger onClick={deleteEdge} data-loc="d2:edge-del">
            刪除此連線
          </Button>,
          <Button key="cancel" onClick={() => setEditEdge(null)}>
            取消
          </Button>,
          <Button key="ok" type="primary" onClick={applyEdge}>
            確定
          </Button>,
        ]}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <span>
            箭頭{' '}
            <Select
              style={{ width: 200 }}
              value={editEdge?.arrow ?? '->'}
              onChange={(v: D2Arrow) => setEditEdge((s) => (s ? { ...s, arrow: v } : s))}
              options={ARROW_OPTS}
              data-loc="d2:edge-arrow"
            />
          </span>
          <span>
            label{' '}
            <Input
              style={{ width: 240 }}
              value={editEdge?.label ?? ''}
              onChange={(e) => setEditEdge((s) => (s ? { ...s, label: e.target.value } : s))}
              placeholder="(可空白)"
              data-loc="d2:edge-label"
            />
          </span>
        </Space>
      </Modal>

      {/* 新增 shape / container */}
      <Modal
        title={adding?.kind === 'd2group' ? '新增 container' : '新增 shape'}
        open={adding !== null}
        onOk={doAdd}
        onCancel={() => setAdding(null)}
        okText="新增"
        cancelText="取消"
        okButtonProps={{ disabled: !adding?.id.trim() }}
      >
        <Input
          autoFocus
          value={adding?.id ?? ''}
          onChange={(e) => {
            const v = e.target.value.replace(/[^A-Za-z0-9_]+/g, '_'); // id 僅允許 \w(空白/中文→_)
            setAdding((s) => (s ? { ...s, id: v } : s));
          }}
          onPressEnter={doAdd}
          placeholder="local id(如 db、api;空白/中文請填到 label)"
          data-loc="d2:add-id"
        />
      </Modal>
    </div>
  );
}
