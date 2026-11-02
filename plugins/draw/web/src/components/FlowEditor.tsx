/**
 * FlowEditor — flowchart 子集 的 GUI 編輯器(React Flow + dagre 自動排版)。
 *  - 解析 mermaid → 節點 / 邊 → dagre 排版 → React Flow 畫布。
 *  - double-click 節點 / 邊 → 改標籤;拖把手連線 → 新增邊;Delete 鍵刪選取;按鈕新增節點。
 *  - 「套用」→ serializeFlow → onSave(正規化 mermaid 文字)。
 *  本元件較重(React Flow + dagre)→ 由 Explore 以 lazy + Suspense 載入。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
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
import { Button, Modal, Input, Select, Space, Typography } from 'antd';
import { PlusOutlined, UndoOutlined, RedoOutlined } from '@ant-design/icons';
import {
  parseFlow,
  serializeFlow,
  nodeStyles,
  type FlowGraph,
  type FlowShape,
  type FlowClassStyle,
} from '../lib/mermaidFlow';

const SHAPE_OPTS: { value: FlowShape; label: string }[] = [
  { value: 'rect', label: '矩形' },
  { value: 'round', label: '圓角' },
  { value: 'diamond', label: '菱形(判斷)' },
];

/** `#rgb` / `#rrggbb` 是不是淺色(相對亮度 > 0.6)。非 hex(具名色、rgb())一律當深色。 */
function isLight(color: string): boolean {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(color.trim());
  if (!m) return false;
  const h = m[1].length === 3 ? [...m[1]].map((c) => c + c).join('') : m[1];
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.6;
}

/** 自訂節點:依 data.shape 用 SVG 畫矩形 / 圓角 / 菱形,標籤置中,上下接點。 */
function ShapedNode({ data }: NodeProps) {
  const d = data as { label?: string; shape?: FlowShape; look?: FlowClassStyle };
  const shape = d.shape ?? 'rect';
  // classDef / style 的 fill / stroke / color;沒有就走主題色。淺色 fill 沒指定字色 → 深字,
  // 不然主題的淺字壓在淺底上看不見。
  const fill = d.look?.fill ?? 'var(--card)';
  const stroke = d.look?.stroke ?? 'var(--muted)';
  const textColor = d.look?.color ?? (d.look?.fill && isLight(d.look.fill) ? '#1a1a1a' : undefined);
  const w = NODE_W;
  const h = NODE_H;
  const shapeEl =
    shape === 'diamond' ? (
      <polygon points={`${w / 2},1 ${w - 1},${h / 2} ${w / 2},${h - 1} 1,${h / 2}`} fill={fill} stroke={stroke} />
    ) : shape === 'round' ? (
      <rect x="1" y="1" width={w - 2} height={h - 2} rx={h / 2} ry={h / 2} fill={fill} stroke={stroke} />
    ) : (
      <rect x="1" y="1" width={w - 2} height={h - 2} rx="4" fill={fill} stroke={stroke} />
    );
  return (
    <div style={{ position: 'relative', width: w, height: h }}>
      <svg width={w} height={h} style={{ position: 'absolute', inset: 0, display: 'block' }}>
        {shapeEl}
      </svg>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 12,
          textAlign: 'center',
          color: textColor,
          padding: shape === 'diamond' ? '0 22px' : '0 8px',
          boxSizing: 'border-box',
          overflow: 'hidden',
        }}
      >
        {d.label}
      </div>
      <Handle type="target" position={Position.Top} style={{ background: 'var(--muted)' }} />
      <Handle type="source" position={Position.Bottom} style={{ background: 'var(--muted)' }} />
    </div>
  );
}

interface Props {
  code: string;
  onSave: (code: string, opts?: { stay?: boolean }) => void;
  onClose: () => void;
  /** 滿版模式:撐滿父容器高度(由 MermaidBlock 的全螢幕切換帶入)。 */
  fill?: boolean;
}

const NODE_W = 150;
const NODE_H = 44;

type Snap = { nodes: Node[]; edges: Edge[]; dir: string };

function layout(nodes: Node[], edges: Edge[], dir: string): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: dir === 'TD' ? 'TB' : dir, nodesep: 40, ranksep: 64 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  return nodes.map((n) => {
    const p = g.node(n.id);
    return { ...n, position: { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 } };
  });
}

export default function FlowEditor({ code, onSave, onClose, fill }: Props) {
  const nodeTypes = useMemo(() => ({ shaped: ShapedNode }), []);

  const init = useMemo(() => {
    const gph = parseFlow(code);
    const looks = nodeStyles(gph);
    const ns: Node[] = gph.nodes.map((n) => ({
      id: n.id,
      type: 'shaped',
      data: { label: n.label, shape: n.shape, classes: n.classes, look: looks.get(n.id) },
      position: { x: 0, y: 0 },
    }));
    const es: Edge[] = gph.edges.map((e, i) => ({
      id: `e${i}-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      label: e.label,
    }));
    return { dir: gph.dir, nodes: layout(ns, es, gph.dir), edges: es, extras: gph.extras };
  }, [code]);

  const [nodes, setNodes] = useState<Node[]>(init.nodes);
  const [edges, setEdges] = useState<Edge[]>(init.edges);
  const [dir, setDir] = useState(init.dir);
  const [seq, setSeq] = useState(1);
  const [editNode, setEditNode] = useState<{ id: string; label: string; shape: FlowShape } | null>(
    null,
  );
  const [editEdge, setEditEdge] = useState<{ id: string; label: string } | null>(null);
  const [adding, setAdding] = useState<string | null>(null);
  const [addShape, setAddShape] = useState<FlowShape>('rect');

  // 復原 / 重做:快照堆疊;copy/paste:剪貼簿 ref。
  const [past, setPast] = useState<Snap[]>([]);
  const [future, setFuture] = useState<Snap[]>([]);
  const clipboard = useRef<{ nodes: Node[]; edges: Edge[] } | null>(null);

  // saveRef:讓 window Ctrl+S 取到最新 save(save 定義在後且依賴 nodes/edges,避免 stale 閉包)。
  const saveRef = useRef<(stay?: boolean) => void>(() => {});

  // 在「變動之前」呼叫:把當前狀態推進 past、清空 future(上限 50)。
  const takeSnapshot = useCallback(() => {
    setPast((p) => [...p.slice(-49), { nodes, edges, dir }]);
    setFuture([]);
  }, [nodes, edges, dir]);

  const undo = useCallback(() => {
    if (!past.length) return;
    const prev = past[past.length - 1];
    setFuture((f) => [{ nodes, edges, dir }, ...f]);
    setPast((p) => p.slice(0, -1));
    setNodes(prev.nodes);
    setEdges(prev.edges);
    setDir(prev.dir);
  }, [past, nodes, edges, dir]);

  const redo = useCallback(() => {
    if (!future.length) return;
    const next = future[0];
    setPast((p) => [...p, { nodes, edges, dir }]);
    setFuture((f) => f.slice(1));
    setNodes(next.nodes);
    setEdges(next.edges);
    setDir(next.dir);
  }, [future, nodes, edges, dir]);

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

  const copy = useCallback(() => {
    const sel = nodes.filter((n) => n.selected);
    if (!sel.length) return;
    const ids = new Set(sel.map((n) => n.id));
    clipboard.current = {
      nodes: sel,
      edges: edges.filter((e) => ids.has(e.source) && ids.has(e.target)),
    };
  }, [nodes, edges]);

  const paste = useCallback(() => {
    const clip = clipboard.current;
    if (!clip?.nodes.length) return;
    takeSnapshot();
    let s = seq;
    const used = new Set(nodes.map((n) => n.id));
    const idMap = new Map<string, string>();
    const newNodes = clip.nodes.map((n) => {
      let nid = `n${s++}`;
      while (used.has(nid)) nid = `n${s++}`;
      used.add(nid);
      idMap.set(n.id, nid);
      return {
        ...n,
        id: nid,
        position: { x: n.position.x + 24, y: n.position.y + 24 },
        selected: true,
        data: { ...n.data },
      };
    });
    const newEdges = clip.edges.flatMap((e, i) => {
      const source = idMap.get(e.source);
      const target = idMap.get(e.target);
      if (!source || !target) return [];
      return [{ ...e, id: `e-paste-${s}-${i}`, source, target, selected: false }];
    });
    setSeq(s);
    setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), ...newNodes]);
    setEdges((es) => [...es, ...newEdges]);
  }, [nodes, seq, takeSnapshot]);

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
      } else if (k === 'c') {
        e.preventDefault();
        copy();
      } else if (k === 'v') {
        e.preventDefault();
        paste();
      }
    },
    [undo, redo, copy, paste],
  );

  // 刪除(Delete 鍵 / 變動含 remove)前先快照,讓刪除可復原。
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
      takeSnapshot();
      setEdges((e) => addEdge({ ...c, id: `e-${c.source}-${c.target}-${e.length}` }, e));
    },
    [takeSnapshot],
  );

  const reLayout = (d = dir) => setNodes((n) => layout(n, edges, d));

  const addNode = () => {
    const label = (adding ?? '').trim();
    if (!label) return;
    takeSnapshot();
    let id = `n${seq}`;
    let s = seq;
    while (nodes.some((n) => n.id === id)) id = `n${++s}`;
    setSeq(s + 1);
    setNodes((n) => [
      ...n,
      { id, type: 'shaped', data: { label, shape: addShape }, position: { x: 40, y: 40 } },
    ]);
    setAdding(null);
    setAddShape('rect');
  };

  const applyNodeLabel = () => {
    if (!editNode) return;
    takeSnapshot();
    setNodes((ns) =>
      ns.map((n) =>
        n.id === editNode.id
          ? { ...n, data: { ...n.data, label: editNode.label, shape: editNode.shape } }
          : n,
      ),
    );
    setEditNode(null);
  };

  const applyEdgeLabel = () => {
    if (!editEdge) return;
    takeSnapshot();
    setEdges((es) =>
      es.map((e) => (e.id === editEdge.id ? { ...e, label: editEdge.label } : e)),
    );
    setEditEdge(null);
  };

  const deleteEdge = () => {
    if (!editEdge) return;
    takeSnapshot();
    setEdges((es) => es.filter((e) => e.id !== editEdge.id));
    setEditEdge(null);
  };

  const save = (stay = false) => {
    const g: FlowGraph = {
      dir,
      nodes: nodes.map((n) => ({
        id: n.id,
        label: String(n.data.label ?? n.id),
        shape: (n.data.shape as FlowShape) ?? 'rect',
        classes: n.data.classes as string[] | undefined,
      })),
      edges: edges.map((e) => ({
        source: e.source,
        target: e.target,
        label: e.label ? String(e.label) : undefined,
      })),
      extras: init.extras, // classDef / class / style… 原樣寫回(刪掉的節點由 serializeFlow 濾)
    };
    onSave(serializeFlow(g), { stay });
  };
  saveRef.current = save; // 每次 render 更新,供 Ctrl+S 取最新

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: fill ? '100%' : '70vh' }}>
      <Space wrap style={{ marginBottom: 8 }}>
        <Button icon={<PlusOutlined />} onClick={() => setAdding('')} data-loc="flow:add-node">
          新增節點
        </Button>
        <Space.Compact>
          <Button size="small" icon={<UndoOutlined />} disabled={!past.length} onClick={undo} title="復原(Ctrl+Z)" data-loc="flow:undo" />
          <Button size="small" icon={<RedoOutlined />} disabled={!future.length} onClick={redo} title="重做(Ctrl+Y)" data-loc="flow:redo" />
        </Space.Compact>
        <span>
          方向{' '}
          <Select
            size="small"
            value={dir}
            onChange={(d) => {
              takeSnapshot();
              setDir(d);
              reLayout(d);
            }}
            style={{ width: 88 }}
            options={['TD', 'LR', 'BT', 'RL'].map((d) => ({ value: d, label: d }))}
          />
        </span>
        <Button
          size="small"
          onClick={() => {
            takeSnapshot();
            reLayout();
          }}
        >
          自動排版
        </Button>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          雙擊改字 · 拖把手連線 · Delete 刪 · Ctrl+C/V 複製貼上 · Ctrl+Z/Y 復原重做
        </Typography.Text>
      </Space>

      <div
        style={{ flex: 1, border: '1px solid var(--line)', borderRadius: 8, minHeight: 0, outline: 'none' }}
        tabIndex={0}
        onKeyDown={onKeyDown}
        data-loc="flow:canvas"
      >
        <ReactFlow
          colorMode="dark"
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeDragStart={() => takeSnapshot()}
          onNodeDoubleClick={(_e, n) =>
            setEditNode({
              id: n.id,
              label: String(n.data.label ?? ''),
              shape: (n.data.shape as FlowShape) ?? 'rect',
            })
          }
          nodeTypes={nodeTypes}
          onEdgeDoubleClick={(_e, ed) => setEditEdge({ id: ed.id, label: String(ed.label ?? '') })}
          deleteKeyCode={['Delete', 'Backspace']}
          fitView
        >
          <Background />
          <Controls />
          <MiniMap pannable zoomable />
        </ReactFlow>
      </div>

      <Space style={{ marginTop: 8, justifyContent: 'flex-end' }}>
        <Button onClick={onClose}>取消</Button>
        <Button onClick={() => save(true)} title="存檔但留在編輯器(Ctrl+S)" data-loc="flow:save">
          儲存
        </Button>
        <Button type="primary" onClick={() => save(false)} data-loc="flow:apply">
          套用
        </Button>
      </Space>

      <Modal
        title="節點標籤"
        open={!!editNode}
        onOk={applyNodeLabel}
        onCancel={() => setEditNode(null)}
        okText="確定"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input
            autoFocus
            value={editNode?.label ?? ''}
            onChange={(e) => setEditNode((s) => (s ? { ...s, label: e.target.value } : s))}
            onPressEnter={applyNodeLabel}
          />
          <span>
            形狀{' '}
            <Select
              size="small"
              value={editNode?.shape ?? 'rect'}
              onChange={(v) => setEditNode((s) => (s ? { ...s, shape: v } : s))}
              style={{ width: 140 }}
              options={SHAPE_OPTS}
            />
          </span>
        </Space>
      </Modal>

      <Modal
        title="邊標籤"
        open={!!editEdge}
        onOk={applyEdgeLabel}
        onCancel={() => setEditEdge(null)}
        okText="確定"
        cancelText="取消"
        footer={[
          <Button key="del" danger onClick={deleteEdge}>
            刪除此邊
          </Button>,
          <Button key="cancel" onClick={() => setEditEdge(null)}>
            取消
          </Button>,
          <Button key="ok" type="primary" onClick={applyEdgeLabel}>
            確定
          </Button>,
        ]}
      >
        <Input
          autoFocus
          value={editEdge?.label ?? ''}
          onChange={(e) => setEditEdge((s) => (s ? { ...s, label: e.target.value } : s))}
          onPressEnter={applyEdgeLabel}
          placeholder="(可空白)"
        />
      </Modal>

      <Modal
        title="新增節點"
        open={adding !== null}
        onOk={addNode}
        onCancel={() => setAdding(null)}
        okText="新增"
        cancelText="取消"
        okButtonProps={{ disabled: !adding?.trim() }}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input
            autoFocus
            value={adding ?? ''}
            onChange={(e) => setAdding(e.target.value)}
            onPressEnter={addNode}
            placeholder="節點文字"
          />
          <span>
            形狀{' '}
            <Select
              size="small"
              value={addShape}
              onChange={setAddShape}
              style={{ width: 140 }}
              options={SHAPE_OPTS}
            />
          </span>
        </Space>
      </Modal>
    </div>
  );
}
