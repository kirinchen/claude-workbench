/**
 * MindmapEditor — mermaid `mindmap` 圖型的樹狀 GUI 編輯器(React Flow + dagre 排版)。
 *  以 D2Editor / ArchitectureEditor 為藍本,但 mindmap 是「單 root 嚴格樹」:
 *   - 每個 MindmapNode → 一個 RF node(node.id = MindmapNode.key);階層「用邊表達」
 *     (mindmap 非巢狀容器,故不用 parentId,改以 parent.key → child.key 的無箭頭邊)。
 *   - 自訂節點:方框顯示 text(角落小字顯示 shape / icon);四邊各 source+target Handle。
 *   - double-click 節點 → 改 text / shape / icon / class;按鈕新增子節點 / 兄弟節點。
 *   - 拖把手連線 = 「改 parent」:把 target 的既有 incoming 邊換成 source→target 的新邊。
 *     **樹的不變式:一個節點只能有一個 parent**,所以拉新線一定會換掉 target 原本那條
 *     邊 —— 這不是掉邊。舊版換完既不提示也不重排版,新線還從畫布右側繞回來,看起來就是
 *     「拉了新線,某條既有的邊憑空消失」(Tide #141)。故現在改 parent 後會 message 明講
 *     「X 由 A 改掛到 B」並自動重排版,讓結果一眼看得懂。
 *   - Delete 刪選取節點 + 整個子樹;root 不可刪。
 *
 *  單 root 不變式:mindmap 只能有一個 root(無 incoming 邊的節點)。所有操作後都要
 *  恰好一個 root。改 parent 時防環(source 不可是 target 的後代)、且不可把 root 變成
 *  自己子樹的子節點(會變兩 root 或環)。存檔時若殘留多個無 parent,把多餘的掛回 root。
 *
 *  圖 ⇄ 模型 的純邏輯(建邊 / 改 parent / 存檔序列化)住在 `lib/mindmapGraph`,
 *  才能用 node:test 做 round-trip 迴歸(不必起瀏覽器)。
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
  Position,
  applyNodeChanges,
  applyEdgeChanges,
  type Node,
  type Edge,
  type Connection,
  type NodeChange,
  type EdgeChange,
  type NodeProps,
  type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from '@dagrejs/dagre';
import { Button, Modal, Input, Select, Space, Typography, message } from 'antd';
import {
  PlusOutlined,
  UndoOutlined,
  RedoOutlined,
  ApartmentOutlined,
  BranchesOutlined,
} from '@ant-design/icons';
import { parseMindmap, serializeMindmap, MINDMAP_SHAPE_LABELS, type MindmapShape } from '../lib/mermaidMindmap';
import {
  buildHierarchyEdges,
  buildParentMap,
  checkReparent,
  collectSubtree,
  findRootId,
  graphToModel,
  makeHierarchyEdge,
  modelToGraphNodes,
  reparentEdges,
  type MindmapNodeFields,
} from '../lib/mindmapGraph';

/** 側邊 ∈ L/R/T/B(沿用 D2Editor 的 handle 命名 s-<SIDE> / t-<SIDE>)。 */
type Side = 'L' | 'R' | 'T' | 'B';
const SIDES: Side[] = ['L', 'R', 'T', 'B'];

const SHAPE_OPTS: { value: MindmapShape; label: string }[] = (
  Object.keys(MINDMAP_SHAPE_LABELS) as MindmapShape[]
).map((s) => ({ value: s, label: MINDMAP_SHAPE_LABELS[s] }));

const NODE_W = 140;
const NODE_H = 56;

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

/** node.data 形狀 = lib 的 MindmapNodeFields(parent 由邊表達,不存這裡)。 */
type MindmapNodeData = MindmapNodeFields;

/** 四邊各放 source+target Handle(任意側邊都能拖出 / 落下 = 改 parent)。 */
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

/** 自訂節點:方框 + text;角落小字顯示 shape / icon;root 加粗換色。 */
function MindmapNodeView({ data }: NodeProps) {
  const d = data as MindmapNodeData;
  const root = !!d.isRoot;
  return (
    <div
      style={{
        position: 'relative',
        width: NODE_W,
        height: NODE_H,
        border: root ? '2px solid var(--accent)' : '1px solid var(--muted)',
        borderRadius: 8,
        background: root ? 'var(--accent-soft)' : 'var(--card)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 12,
        fontWeight: root ? 700 : 600,
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
        {d.text || <span style={{ color: 'var(--muted)' }}>(空白)</span>}
      </span>
      {/* 角落小字:shape 名稱 + icon(若有)。 */}
      <span
        style={{
          position: 'absolute',
          bottom: 2,
          right: 6,
          fontSize: 9,
          fontWeight: 400,
          color: 'var(--muted)',
          pointerEvents: 'none',
          maxWidth: '90%',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
        {d.shape !== 'default' ? d.shape : ''}
        {d.icon ? ` · ${d.icon}` : ''}
      </span>
      <FourSideHandles color={root ? 'var(--accent)' : 'var(--muted)'} />
    </div>
  );
}

interface Props {
  code: string;
  onSave: (code: string, opts?: { stay?: boolean }) => void;
  onClose: () => void;
  /** 滿版模式:撐滿父容器高度(由上層全螢幕切換帶入)。 */
  fill?: boolean;
}

type Snap = { nodes: Node[]; edges: Edge[] };

/** dagre 樹狀排版(LR,像心智圖);節點 + 邊都進 dagre 算座標。 */
function layout(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 32, ranksep: 80 });
  g.setDefaultEdgeLabel(() => ({}));
  const ids = new Set(nodes.map((n) => n.id));
  nodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  edges.forEach((e) => {
    if (ids.has(e.source) && ids.has(e.target)) g.setEdge(e.source, e.target);
  });
  dagre.layout(g);
  return nodes.map((n) => {
    const p = g.node(n.id);
    if (!p) return n;
    return { ...n, position: { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 } };
  });
}

export default function MindmapEditor({ code, onSave, onClose, fill }: Props) {
  const nodeTypes = useMemo(() => ({ mindmap: MindmapNodeView }), []);

  const init = useMemo(() => {
    const model = parseMindmap(code);
    const rfNodes: Node[] = modelToGraphNodes(model).map((n) => ({
      id: n.id,
      type: 'mindmap',
      data: n.data,
      position: { x: 0, y: 0 },
      style: { width: NODE_W, height: NODE_H },
    }));
    // 階層用邊表達:對每個有 parent 的節點建一條 parent.key → child.key 邊。
    const rfEdges: Edge[] = buildHierarchyEdges(model);
    return { nodes: layout(rfNodes, rfEdges), edges: rfEdges };
  }, [code]);

  const [nodes, setNodes] = useState<Node[]>(init.nodes);
  const [edges, setEdges] = useState<Edge[]>(init.edges);
  const [seq, setSeq] = useState(1); // 新節點 id 計數(邊 id 由 target 導出,不用序號)

  // 雙擊編輯節點。
  const [editNode, setEditNode] = useState<{
    id: string;
    text: string;
    shape: MindmapShape;
    icon: string;
    cls: string;
  } | null>(null);

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

  // saveRef:讓 window Ctrl+S 取到最新 save(save 定義在後且依賴 nodes/edges,避免 stale 閉包)。
  const saveRef = useRef<(stay?: boolean) => void>(() => {});

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

  // React Flow 實例:重排版後要把視野重新框回全圖(節點會換 rank / 移位,
  // 不 fitView 的話新位置可能落在可視範圍外 → 又是一種「東西不見了」的錯覺)。
  const rfRef = useRef<ReactFlowInstance<Node, Edge> | null>(null);
  const fitLater = useCallback(() => {
    // 等 React 把新座標畫上去再框視野。
    requestAnimationFrame(() => rfRef.current?.fitView({ duration: 200 }));
  }, []);

  // 選取節點 id(用於「新增子 / 兄弟 / 刪除」)。
  const selectedId = useMemo(() => nodes.find((n) => n.selected)?.id, [nodes]);
  const rootId = useMemo(() => findRootId(nodes.map((n) => n.id), edges), [nodes, edges]);

  /**
   * 節點刪除:Delete/Backspace 觸發。攔截 remove change,改為刪「選取節點 + 整個子樹」,
   * 並擋掉 root(root 不可刪)。邊的 remove 照常套用(applyEdgeChanges)。
   */
  const onNodesChange = useCallback(
    (c: NodeChange[]) => {
      const removeIds = c.flatMap((x) => (x.type === 'remove' ? [x.id] : []));
      if (removeIds.length) {
        // root 不可刪:從刪除集合濾掉 root(而非整批拒絕),其餘照刪。
        const delIds = rootId !== undefined ? removeIds.filter((id) => id !== rootId) : removeIds;
        if (delIds.length < removeIds.length) message.warning('root 不可刪除,已略過');
        const rest = c.filter((x) => x.type !== 'remove');
        if (!delIds.length) {
          if (rest.length) setNodes((n) => applyNodeChanges(rest, n));
          return;
        }
        takeSnapshot();
        // 展開為「子樹」一併刪除。
        const toDelete = new Set<string>();
        for (const id of delIds) for (const s of collectSubtree(id, edges)) toDelete.add(s);
        setNodes((n) => n.filter((x) => !toDelete.has(x.id)));
        setEdges((es) => es.filter((e) => !toDelete.has(e.source) && !toDelete.has(e.target)));
        // 套用其餘非 remove 變更。
        if (rest.length) setNodes((n) => applyNodeChanges(rest, n));
        return;
      }
      setNodes((n) => applyNodeChanges(c, n));
    },
    [edges, rootId, takeSnapshot],
  );

  const onEdgesChange = useCallback(
    (c: EdgeChange[]) => {
      if (c.some((x) => x.type === 'remove')) takeSnapshot();
      setEdges((e) => applyEdgeChanges(c, e));
    },
    [takeSnapshot],
  );

  /** dagre 重排版(預設用目前的邊)+ 重框視野。 */
  const reLayout = useCallback(
    (es: Edge[] = edges) => {
      setNodes((n) => layout(n, es));
      fitLater();
    },
    [edges, fitLater],
  );

  /**
   * 拖把手連線 = 改 parent:把 target 的 parent 改成 source(合法性檢查見 checkReparent)。
   *  - 先移除 target 既有的 incoming 邊,再加 source → target 的新邊(reparentEdges)。
   *  - **換掉的舊邊 = 使用者眼中「消失的既有邊」**(Tide #141)→ 一定要 message 明講
   *    「X 由 A 改掛到 B」,並重排版讓 target 落到新 parent 底下;不然畫面上只剩一條
   *    從畫布邊緣繞回來的新線 + 一條莫名不見的舊線,看起來就像掉邊。
   */
  const onConnect = useCallback(
    (c: Connection) => {
      if (!c.source || !c.target) return;
      const source = c.source;
      const target = c.target;
      const check = checkReparent(edges, source, target, rootId);
      if (!check.ok) {
        message.warning(check.reason);
        return;
      }
      takeSnapshot();
      // 先移除 target 既有 incoming 邊,再加新邊 → 維持「每節點至多一條 incoming」。
      const { edges: next, prevParent } = reparentEdges(edges, source, target, c.sourceHandle, c.targetHandle);
      setEdges(next);
      // 換掉的舊邊要明講,否則使用者只看到「既有的邊消失」(Tide #141);
      // 同時重排版 + 重框視野,新 parent 底下的位置才對得上,不會留一條繞回畫布外的線。
      reLayout(next);
      const label = (id: string): string => {
        const d = nodes.find((n) => n.id === id)?.data as MindmapNodeData | undefined;
        return d?.text?.trim() || '(空白)';
      };
      message.info(
        prevParent !== undefined
          ? `已改 parent:「${label(target)}」由「${label(prevParent)}」改掛到「${label(source)}」底下(mindmap 是樹,一個節點只能有一個 parent)`
          : `已改 parent:「${label(target)}」掛到「${label(source)}」底下`,
      );
    },
    [edges, nodes, rootId, takeSnapshot, reLayout],
  );

  /** 產生不重複的新節點 id。 */
  const newNodeId = useCallback(
    (start: number): { id: string; next: number } => {
      const used = new Set(nodes.map((n) => n.id));
      let s = start;
      let id = `m_${s++}`;
      while (used.has(id)) id = `m_${s++}`;
      return { id, next: s };
    },
    [nodes],
  );

  /** 新增子節點(對選取節點;沒選取則對 root)。 */
  const addChild = useCallback(() => {
    const parent = selectedId ?? rootId;
    if (parent === undefined) {
      message.warning('沒有可作為 parent 的節點');
      return;
    }
    takeSnapshot();
    const { id, next } = newNodeId(seq);
    setSeq(next + 1);
    const data: MindmapNodeData = { text: '', shape: 'default', isRoot: false };
    setNodes((n) => [
      ...n,
      { id, type: 'mindmap', data, position: { x: 0, y: 0 }, style: { width: NODE_W, height: NODE_H } },
    ]);
    setEdges((es) => [...es, makeHierarchyEdge(parent, id)]);
  }, [selectedId, rootId, seq, newNodeId, takeSnapshot]);

  /** 新增兄弟(加到選取節點的 parent 之下;root 無 parent → 退化成加 child)。 */
  const addSibling = useCallback(() => {
    if (selectedId === undefined) {
      message.warning('請先選取一個節點');
      return;
    }
    const byParent = buildParentMap(edges);
    const parent = byParent.get(selectedId);
    if (parent === undefined) {
      // 選取的是 root(無 parent)→ root 不能有兄弟(會變兩 root)→ 退化成加 child。
      message.info('root 無 parent,改為新增子節點');
      addChild();
      return;
    }
    takeSnapshot();
    const { id, next } = newNodeId(seq);
    setSeq(next + 1);
    const data: MindmapNodeData = { text: '', shape: 'default', isRoot: false };
    setNodes((n) => [
      ...n,
      { id, type: 'mindmap', data, position: { x: 0, y: 0 }, style: { width: NODE_W, height: NODE_H } },
    ]);
    setEdges((es) => [...es, makeHierarchyEdge(parent, id)]);
  }, [selectedId, edges, seq, newNodeId, addChild, takeSnapshot]);

  /** 套用節點編輯:text / shape / icon / class。 */
  const applyNode = useCallback(() => {
    if (!editNode) return;
    takeSnapshot();
    setNodes((ns) =>
      ns.map((n) => {
        if (n.id !== editNode.id) return n;
        const data: MindmapNodeData = {
          ...(n.data as MindmapNodeData),
          text: editNode.text,
          shape: editNode.shape,
          icon: editNode.icon.trim() || undefined,
          cls: editNode.cls.trim() || undefined,
        };
        return { ...n, data };
      }),
    );
    setEditNode(null);
  }, [editNode, takeSnapshot]);

  /** 存檔:React Flow → MindmapModel(graphToModel)→ serializeMindmap → onSave。 */
  const save = useCallback(
    (stay = false) => {
      // 畫布 → 模型 → mindmap 文字(單 root 收斂 / BFS 排序在 lib,見 graphToModel)。
      const model = graphToModel(
        nodes.map((n) => ({ id: n.id, data: n.data as MindmapNodeData })),
        edges,
      );
      onSave(serializeMindmap(model), { stay });
    },
    [nodes, edges, onSave],
  );
  saveRef.current = save; // 每次 render 更新,供 Ctrl+S 取最新

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: fill ? '100%' : '70vh' }}>
      <Space wrap style={{ marginBottom: 8 }}>
        <Button icon={<PlusOutlined />} onClick={addChild} data-loc="mindmap:add-child">
          新增子節點
        </Button>
        <Button icon={<BranchesOutlined />} onClick={addSibling} data-loc="mindmap:add-sibling">
          新增兄弟
        </Button>
        <Space.Compact>
          <Button
            size="small"
            icon={<UndoOutlined />}
            disabled={!past.length}
            onClick={undo}
            title="復原(Ctrl+Z)"
            data-loc="mindmap:undo"
          />
          <Button
            size="small"
            icon={<RedoOutlined />}
            disabled={!future.length}
            onClick={redo}
            title="重做(Ctrl+Y)"
            data-loc="mindmap:redo"
          />
        </Space.Compact>
        <Button
          size="small"
          icon={<ApartmentOutlined />}
          onClick={() => {
            takeSnapshot();
            reLayout();
          }}
          data-loc="mindmap:layout"
        >
          自動排版
        </Button>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          雙擊節點改 text/shape/icon/class · 拖把手連線=改 parent · Delete 刪子樹 · Ctrl+Z/Y
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
        data-loc="mindmap:canvas"
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
            const d = n.data as MindmapNodeData;
            setEditNode({
              id: n.id,
              text: d.text,
              shape: d.shape,
              icon: d.icon ?? '',
              cls: d.cls ?? '',
            });
          }}
          nodeTypes={nodeTypes}
          onInit={(inst) => (rfRef.current = inst)}
          deleteKeyCode={['Delete', 'Backspace']}
          fitView
        >
          <Background />
          <Controls />
          <MiniMap pannable zoomable />
        </ReactFlow>
      </div>

      <Space style={{ marginTop: 8, justifyContent: 'flex-end' }}>
        <Button onClick={onClose} data-loc="mindmap:cancel">
          取消
        </Button>
        <Button onClick={() => save(true)} title="存檔但留在編輯器(Ctrl+S)" data-loc="mindmap:save">
          儲存
        </Button>
        <Button type="primary" onClick={() => save(false)} data-loc="mindmap:apply">
          套用
        </Button>
      </Space>

      {/* 節點編輯:text / shape / icon / class */}
      <Modal
        title="編輯節點"
        open={!!editNode}
        onOk={applyNode}
        onCancel={() => setEditNode(null)}
        okText="確定"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <span>
            text{' '}
            <Input
              style={{ width: 280 }}
              value={editNode?.text ?? ''}
              onChange={(e) => setEditNode((s) => (s ? { ...s, text: e.target.value } : s))}
              onPressEnter={applyNode}
              placeholder="節點文字"
              data-loc="mindmap:node-text"
            />
          </span>
          <span>
            shape{' '}
            <Select
              style={{ width: 200 }}
              value={editNode?.shape ?? 'default'}
              onChange={(v: MindmapShape) => setEditNode((s) => (s ? { ...s, shape: v } : s))}
              options={SHAPE_OPTS}
              data-loc="mindmap:node-shape"
            />
          </span>
          <span>
            icon{' '}
            <Input
              style={{ width: 280 }}
              value={editNode?.icon ?? ''}
              onChange={(e) => setEditNode((s) => (s ? { ...s, icon: e.target.value } : s))}
              placeholder="(可空白,如 fa fa-book)"
              data-loc="mindmap:node-icon"
            />
          </span>
          <span>
            class{' '}
            <Input
              style={{ width: 280 }}
              value={editNode?.cls ?? ''}
              onChange={(e) => setEditNode((s) => (s ? { ...s, cls: e.target.value } : s))}
              placeholder="(可空白,空白分隔多個)"
              data-loc="mindmap:node-class"
            />
          </span>
        </Space>
      </Modal>
    </div>
  );
}
