/**
 * StateEditor — stateDiagram-v2 子集 的 GUI 編輯器(React Flow + dagre 自動排版)。
 *  - 解析 mermaid → 節點(狀態 / 起點 / 終點)/ 轉移 → dagre 排版 → React Flow 畫布。
 *  - double-click 狀態 → 改 label;double-click 邊 → 改 / 刪轉移 label;拖把手連線 → 新增轉移;
 *    Delete 鍵刪選取;按鈕新增狀態 / 起點 / 終點。
 *  - 「套用」→ serializeState → onSave(正規化 mermaid 文字)。
 *  本元件較重(React Flow + dagre)→ 由 MermaidBlock 以 lazy + Suspense 載入。
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
  parseState,
  serializeState,
  type StateGraph,
  type StateKind,
} from '../lib/mermaidState';

/** 自訂節點:state = 圓角矩形含 label;start = 實心黑圓;end = 雙圈圓。上下接點 Handle。 */
function StateShapedNode({ data }: NodeProps) {
  const d = data as { label?: string; kind?: StateKind };
  const kind = d.kind ?? 'state';

  if (kind === 'start' || kind === 'end') {
    const r = PSEUDO / 2;
    return (
      <div style={{ position: 'relative', width: PSEUDO, height: PSEUDO }}>
        <svg width={PSEUDO} height={PSEUDO} style={{ position: 'absolute', inset: 0, display: 'block' }}>
          {kind === 'start' ? (
            // 實心黑圓(●)
            <circle cx={r} cy={r} r={r - 1} fill="var(--text)" stroke="var(--text)" />
          ) : (
            // 雙圈圓(◉):外圈 + 實心內圈
            <>
              <circle cx={r} cy={r} r={r - 1} fill="var(--card)" stroke="var(--text)" strokeWidth={1.5} />
              <circle cx={r} cy={r} r={r - 5} fill="var(--text)" stroke="var(--text)" />
            </>
          )}
        </svg>
        <Handle type="target" position={Position.Top} style={{ background: 'var(--muted)' }} />
        <Handle type="source" position={Position.Bottom} style={{ background: 'var(--muted)' }} />
      </div>
    );
  }

  // state:圓角矩形含 label。
  const w = NODE_W;
  const h = NODE_H;
  return (
    <div style={{ position: 'relative', width: w, height: h }}>
      <svg width={w} height={h} style={{ position: 'absolute', inset: 0, display: 'block' }}>
        <rect x="1" y="1" width={w - 2} height={h - 2} rx="8" ry="8" fill="var(--card)" stroke="var(--muted)" />
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
          padding: '0 8px',
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
const PSEUDO = 22;

type Snap = { nodes: Node[]; edges: Edge[]; dir: string };

/** 依 kind 取 dagre 尺寸:偽狀態用小尺寸。 */
function sizeOf(n: Node): { width: number; height: number } {
  const kind = (n.data as { kind?: StateKind }).kind ?? 'state';
  if (kind === 'start' || kind === 'end') return { width: PSEUDO, height: PSEUDO };
  return { width: NODE_W, height: NODE_H };
}

function layout(nodes: Node[], edges: Edge[], dir: string): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: dir, nodesep: 40, ranksep: 64 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(n.id, sizeOf(n)));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  return nodes.map((n) => {
    const p = g.node(n.id);
    const s = sizeOf(n);
    return { ...n, position: { x: p.x - s.width / 2, y: p.y - s.height / 2 } };
  });
}

export default function StateEditor({ code, onSave, onClose, fill }: Props) {
  const nodeTypes = useMemo(() => ({ stateShaped: StateShapedNode }), []);

  const init = useMemo(() => {
    const gph = parseState(code);
    const ns: Node[] = gph.nodes.map((n) => ({
      id: n.id,
      type: 'stateShaped',
      data: { label: n.label, kind: n.kind },
      position: { x: 0, y: 0 },
    }));
    const es: Edge[] = gph.edges.map((e, i) => ({
      id: `e${i}-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      label: e.label,
    }));
    return { dir: gph.dir, nodes: layout(ns, es, gph.dir), edges: es };
  }, [code]);

  const [nodes, setNodes] = useState<Node[]>(init.nodes);
  const [edges, setEdges] = useState<Edge[]>(init.edges);
  const [dir, setDir] = useState(init.dir);
  const [seq, setSeq] = useState(1);
  const [editNode, setEditNode] = useState<{ id: string; label: string } | null>(null);
  const [editEdge, setEditEdge] = useState<{ id: string; label: string } | null>(null);
  const [adding, setAdding] = useState<string | null>(null);

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
      let nid = `s${s++}`;
      while (used.has(nid)) nid = `s${s++}`;
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
      // 端點未被 remap(理論上不會發生)→ 跳過,避免產生懸空邊。
      if (source === undefined || target === undefined) return [];
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
    let id = `s${seq}`;
    let s = seq;
    while (nodes.some((n) => n.id === id)) id = `s${++s}`;
    setSeq(s + 1);
    setNodes((n) => [
      ...n,
      { id, type: 'stateShaped', data: { label, kind: 'state' }, position: { x: 40, y: 40 } },
    ]);
    setAdding(null);
  };

  // 新增起點 / 終點偽狀態:id 自取避免衝突。
  const addPseudo = (kind: 'start' | 'end') => {
    takeSnapshot();
    const prefix = kind === 'start' ? 'start' : 'end';
    let s = seq;
    let id = `${prefix}${s}`;
    while (nodes.some((n) => n.id === id)) id = `${prefix}${++s}`;
    setSeq(s + 1);
    setNodes((n) => [
      ...n,
      { id, type: 'stateShaped', data: { label: '', kind }, position: { x: 40, y: 40 } },
    ]);
  };

  const applyNodeLabel = () => {
    if (!editNode) return;
    takeSnapshot();
    setNodes((ns) =>
      ns.map((n) =>
        n.id === editNode.id ? { ...n, data: { ...n.data, label: editNode.label } } : n,
      ),
    );
    setEditNode(null);
  };

  const applyEdgeLabel = () => {
    if (!editEdge) return;
    takeSnapshot();
    setEdges((es) => es.map((e) => (e.id === editEdge.id ? { ...e, label: editEdge.label } : e)));
    setEditEdge(null);
  };

  const deleteEdge = () => {
    if (!editEdge) return;
    takeSnapshot();
    setEdges((es) => es.filter((e) => e.id !== editEdge.id));
    setEditEdge(null);
  };

  const save = (stay = false) => {
    const g: StateGraph = {
      dir,
      nodes: nodes.map((n) => {
        const data = n.data as { label?: string; kind?: StateKind };
        return {
          id: n.id,
          label: String(data.label ?? ''),
          kind: data.kind ?? 'state',
        };
      }),
      edges: edges.map((e) => ({
        source: e.source,
        target: e.target,
        label: e.label ? String(e.label) : undefined,
      })),
    };
    onSave(serializeState(g), { stay });
  };
  saveRef.current = save; // 每次 render 更新,供 Ctrl+S 取最新

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: fill ? '100%' : '70vh' }}>
      <Space wrap style={{ marginBottom: 8 }}>
        <Button icon={<PlusOutlined />} onClick={() => setAdding('')} data-loc="state:add">
          新增狀態
        </Button>
        <Button size="small" onClick={() => addPseudo('start')} data-loc="state:add-start">
          新增起點
        </Button>
        <Button size="small" onClick={() => addPseudo('end')} data-loc="state:add-end">
          新增終點
        </Button>
        <Space.Compact>
          <Button size="small" icon={<UndoOutlined />} disabled={!past.length} onClick={undo} title="復原(Ctrl+Z)" data-loc="state:undo" />
          <Button size="small" icon={<RedoOutlined />} disabled={!future.length} onClick={redo} title="重做(Ctrl+Y)" data-loc="state:redo" />
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
            options={['TB', 'LR', 'BT', 'RL'].map((d) => ({ value: d, label: d }))}
            data-loc="state:dir"
          />
        </span>
        <Button
          size="small"
          onClick={() => {
            takeSnapshot();
            reLayout();
          }}
          data-loc="state:layout"
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
        data-loc="state:canvas"
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
            // 偽狀態無 label,不開編輯。
            const kind = (n.data as { kind?: StateKind }).kind ?? 'state';
            if (kind !== 'state') return;
            setEditNode({ id: n.id, label: String((n.data as { label?: string }).label ?? '') });
          }}
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
        <Button onClick={onClose} data-loc="state:cancel">
          取消
        </Button>
        <Button onClick={() => save(true)} title="存檔但留在編輯器(Ctrl+S)" data-loc="state:save">
          儲存
        </Button>
        <Button type="primary" onClick={() => save(false)} data-loc="state:apply">
          套用
        </Button>
      </Space>

      <Modal
        title="狀態名稱"
        open={!!editNode}
        onOk={applyNodeLabel}
        onCancel={() => setEditNode(null)}
        okText="確定"
        cancelText="取消"
      >
        <Input
          autoFocus
          value={editNode?.label ?? ''}
          onChange={(e) => setEditNode((s) => (s ? { ...s, label: e.target.value } : s))}
          onPressEnter={applyNodeLabel}
        />
      </Modal>

      <Modal
        title="轉移標籤"
        open={!!editEdge}
        onOk={applyEdgeLabel}
        onCancel={() => setEditEdge(null)}
        okText="確定"
        cancelText="取消"
        footer={[
          <Button key="del" danger onClick={deleteEdge}>
            刪除此轉移
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
        title="新增狀態"
        open={adding !== null}
        onOk={addNode}
        onCancel={() => setAdding(null)}
        okText="新增"
        cancelText="取消"
        okButtonProps={{ disabled: !adding?.trim() }}
      >
        <Input
          autoFocus
          value={adding ?? ''}
          onChange={(e) => setAdding(e.target.value)}
          onPressEnter={addNode}
          placeholder="狀態名稱"
        />
      </Modal>
    </div>
  );
}
