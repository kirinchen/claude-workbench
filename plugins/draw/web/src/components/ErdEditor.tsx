/**
 * ErdEditor — mermaid erDiagram(ERD)子集 的 GUI 編輯器(React Flow + dagre 自動排版)。
 *  - 解析 mermaid → 實體(表格節點)/ 關係(邊)→ dagre 排版 → React Flow 畫布。
 *  - double-click 實體 → 改實體名 + 屬性清單;double-click 邊 → 改基數 / identifying / label。
 *  - 拖把手連線 → 新增關係(預設 ||--o{ , label "rel");Delete 刪選取;按鈕新增實體。
 *  - 「套用」→ serializeErd → onSave(正規化 mermaid 文字)。
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
import { Button, Modal, Input, Select, Space, Switch, Typography, message } from 'antd';
import { PlusOutlined, UndoOutlined, RedoOutlined, DeleteOutlined } from '@ant-design/icons';
import {
  parseErd,
  serializeErd,
  cardSymbol,
  type Card,
  type ErdAttr,
  type ErdEntity,
  type ErdModel,
} from '../lib/mermaidErd';

const CARD_OPTS: { value: Card; label: string }[] = [
  { value: 'zero-one', label: 'zero-one (0..1)' },
  { value: 'one', label: 'one (1)' },
  { value: 'zero-many', label: 'zero-many (0..*)' },
  { value: 'one-many', label: 'one-many (1..*)' },
];

const KEY_OPTS = ['PK', 'FK', 'UK'].map((k) => ({ value: k, label: k }));

const NODE_W = 200;
const ROW_H = 24;
const HEADER_H = 30;

/** 依屬性數估算節點高度(供 dagre 排版與 SVG 用)。 */
function entityHeight(attrCount: number): number {
  return HEADER_H + Math.max(attrCount, 1) * ROW_H;
}

/** 自訂節點:實體 = 表格(表頭=實體名;每列一屬性)。左右接點 Handle。 */
function EntityNode({ data }: NodeProps) {
  const d = data as { name?: string; attrs?: ErdAttr[] };
  const name = d.name ?? '';
  const attrs = d.attrs ?? [];
  return (
    <div
      style={{
        position: 'relative',
        width: NODE_W,
        border: '1px solid #555',
        borderRadius: 4,
        background: 'var(--card)',
        fontSize: 12,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          height: HEADER_H,
          lineHeight: `${HEADER_H}px`,
          textAlign: 'center',
          fontWeight: 600,
          background: 'var(--surface)',
          borderBottom: '1px solid #555',
          padding: '0 6px',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
        {name}
      </div>
      {attrs.length === 0 ? (
        <div style={{ height: ROW_H, lineHeight: `${ROW_H}px`, textAlign: 'center', color: 'var(--muted)' }}>
          (無屬性)
        </div>
      ) : (
        attrs.map((a, i) => (
          <div
            key={i}
            style={{
              height: ROW_H,
              lineHeight: `${ROW_H}px`,
              display: 'flex',
              gap: 6,
              padding: '0 6px',
              borderTop: i === 0 ? 'none' : '1px solid var(--line)',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
            }}
          >
            <span style={{ color: '#888' }}>{a.type}</span>
            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}>{a.name}</span>
            {a.keys.length > 0 && (
              <span style={{ color: '#c41d7f', fontWeight: 600 }}>{a.keys.join(',')}</span>
            )}
          </div>
        ))
      )}
      <Handle type="target" position={Position.Left} style={{ background: '#555' }} />
      <Handle type="source" position={Position.Right} style={{ background: '#555' }} />
    </div>
  );
}

interface Props {
  code: string;
  onSave: (code: string, opts?: { stay?: boolean }) => void;
  onClose: () => void;
  /** 滿版模式:撐滿父容器高度(由上層的全螢幕切換帶入)。 */
  fill?: boolean;
}

type Snap = { nodes: Node[]; edges: Edge[] };

/** 邊標籤文字:cardinality + label,如 "1..*  places"。 */
function edgeLabel(leftCard: Card, rightCard: Card, label: string): string {
  return `${cardSymbol(leftCard)}..${cardSymbol(rightCard)}  ${label}`.trim();
}

function layout(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 48, ranksep: 80 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => {
    const d = n.data as { attrs?: ErdAttr[] };
    g.setNode(n.id, { width: NODE_W, height: entityHeight(d.attrs?.length ?? 0) });
  });
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  return nodes.map((n) => {
    const p = g.node(n.id);
    const d = n.data as { attrs?: ErdAttr[] };
    const h = entityHeight(d.attrs?.length ?? 0);
    return { ...n, position: { x: p.x - NODE_W / 2, y: p.y - h / 2 } };
  });
}

/** edge.data 載入關係的結構化欄位(節點 id 即實體名)。 */
type EdgeData = {
  leftCard: Card;
  rightCard: Card;
  identifying: boolean;
  relLabel: string;
};

export default function ErdEditor({ code, onSave, onClose, fill }: Props) {
  const nodeTypes = useMemo(() => ({ entity: EntityNode }), []);

  const init = useMemo(() => {
    const model = parseErd(code);
    const ns: Node[] = model.entities.map((e) => ({
      id: e.name,
      type: 'entity',
      data: { name: e.name, attrs: e.attrs },
      position: { x: 0, y: 0 },
    }));
    const es: Edge[] = model.rels.map((r, i) => ({
      id: `r${i}-${r.left}-${r.right}`,
      source: r.left,
      target: r.right,
      label: edgeLabel(r.leftCard, r.rightCard, r.label),
      data: {
        leftCard: r.leftCard,
        rightCard: r.rightCard,
        identifying: r.identifying,
        relLabel: r.label,
      } satisfies EdgeData,
    }));
    return { nodes: layout(ns, es), edges: es };
  }, [code]);

  const [nodes, setNodes] = useState<Node[]>(init.nodes);
  const [edges, setEdges] = useState<Edge[]>(init.edges);
  const [seq, setSeq] = useState(1);

  // 雙擊編輯狀態:實體(含屬性草稿)/ 關係。
  const [editEntity, setEditEntity] = useState<{
    id: string;
    name: string;
    attrs: ErdAttr[];
  } | null>(null);
  const [editEdge, setEditEdge] = useState<{
    id: string;
    leftCard: Card;
    rightCard: Card;
    identifying: boolean;
    relLabel: string;
  } | null>(null);
  const [adding, setAdding] = useState<string | null>(null);

  // 復原 / 重做:快照堆疊;copy/paste:剪貼簿 ref。
  const [past, setPast] = useState<Snap[]>([]);
  const [future, setFuture] = useState<Snap[]>([]);
  const clipboard = useRef<{ nodes: Node[]; edges: Edge[] } | null>(null);
  // saveRef:讓 window Ctrl+S 取到最新 save(save 定義在後且依賴 nodes/edges,避免 stale 閉包)。
  const saveRef = useRef<(stay?: boolean) => void>(() => {});

  // 在「變動之前」呼叫:把當前狀態推進 past、清空 future(上限 50)。
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
      const base = String((n.data as { name?: string }).name ?? n.id);
      let nid = `${base}_${s++}`;
      while (used.has(nid)) nid = `${base}_${s++}`;
      used.add(nid);
      idMap.set(n.id, nid);
      return {
        ...n,
        id: nid,
        position: { x: n.position.x + 32, y: n.position.y + 32 },
        selected: true,
        data: { ...n.data, name: nid },
      };
    });
    const newEdges = clip.edges.flatMap((e, i) => {
      const source = idMap.get(e.source);
      const target = idMap.get(e.target);
      if (source === undefined || target === undefined) return [];
      return [{ ...e, id: `r-paste-${s}-${i}`, source, target, selected: false }];
    });
    setSeq(s);
    setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), ...newNodes]);
    setEdges((es) => [...es, ...newEdges]);
  }, [nodes, edges, seq, takeSnapshot]);

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
      // 新關係預設 ||--o{(one → zero-many),label "rel"。
      const data: EdgeData = {
        leftCard: 'one',
        rightCard: 'zero-many',
        identifying: true,
        relLabel: 'rel',
      };
      setEdges((e) =>
        addEdge(
          {
            ...c,
            id: `r-${c.source}-${c.target}-${e.length}`,
            label: edgeLabel(data.leftCard, data.rightCard, data.relLabel),
            data,
          },
          e,
        ),
      );
    },
    [takeSnapshot],
  );

  const reLayout = () => setNodes((n) => layout(n, edges));

  const addEntity = () => {
    const name = (adding ?? '').trim();
    if (!name) return;
    takeSnapshot();
    let id = name;
    let s = seq;
    while (nodes.some((n) => n.id === id)) id = `${name}_${s++}`;
    setSeq(s + 1);
    setNodes((n) => [
      ...n,
      { id, type: 'entity', data: { name: id, attrs: [] as ErdAttr[] }, position: { x: 40, y: 40 } },
    ]);
    setAdding(null);
  };

  const applyEntity = () => {
    if (!editEntity) return;
    const newName = editEntity.name.trim() || editEntity.id;
    // 改名後若與「其他」實體重名 → 提示並中止,避免產生重名實體。
    const dup = nodes.some(
      (n) =>
        n.id !== editEntity.id && String((n.data as { name?: string }).name ?? n.id) === newName,
    );
    if (dup) {
      message.error(`實體名「${newName}」已存在`);
      return;
    }
    takeSnapshot();
    // 清掉沒填 type/name 的空白屬性列。
    const attrs = editEntity.attrs
      .map((a) => ({
        type: a.type.trim(),
        name: a.name.trim(),
        keys: a.keys,
        comment: a.comment?.trim() || undefined,
      }))
      .filter((a) => a.type || a.name);
    setNodes((ns) =>
      ns.map((n) =>
        n.id === editEntity.id ? { ...n, data: { ...n.data, name: newName, attrs } } : n,
      ),
    );
    setEditEntity(null);
  };

  const applyEdge = () => {
    if (!editEdge) return;
    takeSnapshot();
    setEdges((es) =>
      es.map((e) => {
        if (e.id !== editEdge.id) return e;
        const data: EdgeData = {
          leftCard: editEdge.leftCard,
          rightCard: editEdge.rightCard,
          identifying: editEdge.identifying,
          relLabel: editEdge.relLabel.trim() || 'rel',
        };
        return {
          ...e,
          data,
          label: edgeLabel(data.leftCard, data.rightCard, data.relLabel),
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

  // 屬性列編輯小工具(只在 editEntity Modal 內用)。
  const updateAttr = (idx: number, patch: Partial<ErdAttr>) =>
    setEditEntity((s) =>
      s ? { ...s, attrs: s.attrs.map((a, i) => (i === idx ? { ...a, ...patch } : a)) } : s,
    );
  const addAttrRow = () =>
    setEditEntity((s) =>
      s ? { ...s, attrs: [...s.attrs, { type: 'string', name: '', keys: [] }] } : s,
    );
  const removeAttrRow = (idx: number) =>
    setEditEntity((s) => (s ? { ...s, attrs: s.attrs.filter((_, i) => i !== idx) } : s));

  const save = (stay = false) => {
    const model: ErdModel = {
      entities: nodes.map<ErdEntity>((n) => {
        const d = n.data as { name?: string; attrs?: ErdAttr[] };
        return {
          name: String(d.name ?? n.id),
          attrs: (d.attrs ?? []).map((a) => ({
            type: a.type,
            name: a.name,
            keys: a.keys,
            comment: a.comment,
          })),
        };
      }),
      // 過濾掉端點已不存在的關係邊(避免 left/right 為 undefined 的關係)。
      rels: edges.flatMap((e) => {
        const src = nodes.find((n) => n.id === e.source);
        const tgt = nodes.find((n) => n.id === e.target);
        if (!src || !tgt) return [];
        const d = (e.data ?? {}) as Partial<EdgeData>;
        const srcName = String((src.data as { name?: string }).name ?? e.source);
        const tgtName = String((tgt.data as { name?: string }).name ?? e.target);
        return [
          {
            left: srcName,
            right: tgtName,
            leftCard: d.leftCard ?? 'one',
            rightCard: d.rightCard ?? 'zero-many',
            identifying: d.identifying ?? true,
            label: d.relLabel ?? 'rel',
          },
        ];
      }),
    };
    onSave(serializeErd(model), { stay });
  };
  saveRef.current = save; // 每次 render 更新,供 Ctrl+S 取最新

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: fill ? '100%' : '70vh' }}>
      <Space wrap style={{ marginBottom: 8 }}>
        <Button icon={<PlusOutlined />} onClick={() => setAdding('')} data-loc="erd:add">
          新增實體
        </Button>
        <Space.Compact>
          <Button
            size="small"
            icon={<UndoOutlined />}
            disabled={!past.length}
            onClick={undo}
            title="復原(Ctrl+Z)"
            data-loc="erd:undo"
          />
          <Button
            size="small"
            icon={<RedoOutlined />}
            disabled={!future.length}
            onClick={redo}
            title="重做(Ctrl+Y)"
            data-loc="erd:redo"
          />
        </Space.Compact>
        <Button
          size="small"
          onClick={() => {
            takeSnapshot();
            reLayout();
          }}
          data-loc="erd:layout"
        >
          自動排版
        </Button>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          雙擊實體改欄位 · 雙擊邊改關係 · 拖把手連線 · Delete 刪 · Ctrl+C/V 複製貼上 · Ctrl+Z/Y 復原重做
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
        data-loc="erd:canvas"
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
            const d = n.data as { name?: string; attrs?: ErdAttr[] };
            setEditEntity({
              id: n.id,
              name: String(d.name ?? n.id),
              attrs: (d.attrs ?? []).map((a) => ({
                type: a.type,
                name: a.name,
                keys: [...a.keys],
                comment: a.comment,
              })),
            });
          }}
          nodeTypes={nodeTypes}
          onEdgeDoubleClick={(_e, ed) => {
            const d = (ed.data ?? {}) as Partial<EdgeData>;
            setEditEdge({
              id: ed.id,
              leftCard: d.leftCard ?? 'one',
              rightCard: d.rightCard ?? 'zero-many',
              identifying: d.identifying ?? true,
              relLabel: d.relLabel ?? 'rel',
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
        <Button onClick={onClose} data-loc="erd:cancel">
          取消
        </Button>
        <Button onClick={() => save(true)} title="存檔但留在編輯器(Ctrl+S)" data-loc="erd:save">
          儲存
        </Button>
        <Button type="primary" onClick={() => save(false)} data-loc="erd:apply">
          套用
        </Button>
      </Space>

      {/* 實體編輯:改名 + 屬性清單 */}
      <Modal
        title="編輯實體"
        open={!!editEntity}
        onOk={applyEntity}
        onCancel={() => setEditEntity(null)}
        okText="確定"
        cancelText="取消"
        width={640}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <span>
            實體名{' '}
            <Input
              style={{ width: 240 }}
              value={editEntity?.name ?? ''}
              onChange={(e) => setEditEntity((s) => (s ? { ...s, name: e.target.value } : s))}
              data-loc="erd:entity-name"
            />
          </span>
          <Space direction="vertical" style={{ width: '100%' }} size={6}>
            {editEntity?.attrs.map((a, i) => (
              <Space key={i} wrap>
                <Input
                  placeholder="type"
                  style={{ width: 96 }}
                  value={a.type}
                  onChange={(e) => updateAttr(i, { type: e.target.value })}
                  data-loc="erd:attr-type"
                />
                <Input
                  placeholder="name"
                  style={{ width: 120 }}
                  value={a.name}
                  onChange={(e) => updateAttr(i, { name: e.target.value })}
                  data-loc="erd:attr-name"
                />
                <Select
                  mode="multiple"
                  allowClear
                  placeholder="keys"
                  style={{ width: 150 }}
                  value={a.keys}
                  onChange={(v: string[]) => updateAttr(i, { keys: v })}
                  options={KEY_OPTS}
                  data-loc="erd:attr-keys"
                />
                <Input
                  placeholder="comment"
                  style={{ width: 130 }}
                  value={a.comment ?? ''}
                  onChange={(e) => updateAttr(i, { comment: e.target.value })}
                  data-loc="erd:attr-comment"
                />
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => removeAttrRow(i)}
                  data-loc="erd:attr-del"
                />
              </Space>
            ))}
            <Button
              size="small"
              icon={<PlusOutlined />}
              onClick={addAttrRow}
              data-loc="erd:attr-add"
            >
              新增屬性
            </Button>
          </Space>
        </Space>
      </Modal>

      {/* 關係編輯:基數 / identifying / label */}
      <Modal
        title="編輯關係"
        open={!!editEdge}
        onOk={applyEdge}
        onCancel={() => setEditEdge(null)}
        okText="確定"
        cancelText="取消"
        footer={[
          <Button key="del" danger onClick={deleteEdge} data-loc="erd:rel-del">
            刪除此關係
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
            左側基數{' '}
            <Select
              style={{ width: 200 }}
              value={editEdge?.leftCard ?? 'one'}
              onChange={(v: Card) => setEditEdge((s) => (s ? { ...s, leftCard: v } : s))}
              options={CARD_OPTS}
              data-loc="erd:rel-left-card"
            />
          </span>
          <span>
            右側基數{' '}
            <Select
              style={{ width: 200 }}
              value={editEdge?.rightCard ?? 'zero-many'}
              onChange={(v: Card) => setEditEdge((s) => (s ? { ...s, rightCard: v } : s))}
              options={CARD_OPTS}
              data-loc="erd:rel-right-card"
            />
          </span>
          <span>
            identifying{' '}
            <Switch
              checked={editEdge?.identifying ?? true}
              onChange={(v) => setEditEdge((s) => (s ? { ...s, identifying: v } : s))}
              data-loc="erd:rel-identifying"
            />{' '}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              ({editEdge?.identifying ? '-- 實線' : '.. 虛線'})
            </Typography.Text>
          </span>
          <span>
            label{' '}
            <Input
              style={{ width: 240 }}
              value={editEdge?.relLabel ?? ''}
              onChange={(e) => setEditEdge((s) => (s ? { ...s, relLabel: e.target.value } : s))}
              onPressEnter={applyEdge}
              placeholder="rel"
              data-loc="erd:rel-label"
            />
          </span>
        </Space>
      </Modal>

      {/* 新增實體 */}
      <Modal
        title="新增實體"
        open={adding !== null}
        onOk={addEntity}
        onCancel={() => setAdding(null)}
        okText="新增"
        cancelText="取消"
        okButtonProps={{ disabled: !adding?.trim() }}
      >
        <Input
          autoFocus
          value={adding ?? ''}
          onChange={(e) => setAdding(e.target.value)}
          onPressEnter={addEntity}
          placeholder="實體名稱(如 CUSTOMER)"
          data-loc="erd:add-name"
        />
      </Modal>
    </div>
  );
}
