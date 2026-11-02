/**
 * ClassEditor — mermaid classDiagram 子集 的 GUI 編輯器(React Flow + dagre 自動排版)。
 *  - 解析 mermaid → 類別(表格節點)/ 關係(邊)→ dagre 排版 → React Flow 畫布。
 *  - double-click 類別 → 改類名 / stereotype / 成員清單;double-click 邊 → 改 type / multiplicity / label。
 *  - 拖把手連線 → 新增關係(預設 association);Delete 刪選取;按鈕新增類別。
 *  - 「套用」→ serializeClass → onSave(正規化 mermaid 文字)。
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
import { Button, Modal, Input, Select, Space, Typography, message } from 'antd';
import { PlusOutlined, UndoOutlined, RedoOutlined, DeleteOutlined } from '@ant-design/icons';
import {
  parseClass,
  serializeClass,
  type Visibility,
  type MemberKind,
  type ClassMember,
  type ClassNode,
  type ClassRel,
  type ClassRelType,
  type ClassModel,
} from '../lib/mermaidClass';

const REL_OPTS: { value: ClassRelType; label: string }[] = [
  { value: 'inheritance', label: 'inheritance (<|--)' },
  { value: 'composition', label: 'composition (*--)' },
  { value: 'aggregation', label: 'aggregation (o--)' },
  { value: 'association', label: 'association (-->)' },
  { value: 'dependency', label: 'dependency (..>)' },
  { value: 'realization', label: 'realization (..|>)' },
  { value: 'solid', label: 'solid (--)' },
  { value: 'dashed', label: 'dashed (..)' },
];

const VIS_OPTS: { value: Visibility; label: string }[] = [
  { value: '+', label: '+ public' },
  { value: '-', label: '- private' },
  { value: '#', label: '# protected' },
  { value: '~', label: '~ package' },
  { value: '', label: '(無)' },
];

const KIND_OPTS: { value: MemberKind; label: string }[] = [
  { value: 'attr', label: 'attribute' },
  { value: 'method', label: 'method' },
];

const NODE_W = 200;
const ROW_H = 22;
const HEADER_H = 34;
const SECTION_H = 18; // attributes/methods 分段標題列

/** 依成員數估算節點高度(供 dagre 排版用)。表頭 + (有 stereotype 多一列) + 成員列。 */
function classHeight(n: { stereotype?: string; members: ClassMember[] }): number {
  const header = HEADER_H + (n.stereotype ? SECTION_H : 0);
  const body = Math.max(n.members.length, 1) * ROW_H;
  return header + body;
}

/** 成員顯示文字:visibility 符號 + text。 */
function memberLine(m: ClassMember): string {
  return `${m.vis}${m.text}`;
}

/** 自訂節點:類別 = 表格(表頭 = «stereotype» + 類名;分段顯示 attributes / methods)。左右接點。 */
function ClassNodeView({ data }: NodeProps) {
  const d = data as { name?: string; stereotype?: string; members?: ClassMember[] };
  const name = d.name ?? '';
  const members = d.members ?? [];
  const attrs = members.filter((m) => m.kind === 'attr');
  const methods = members.filter((m) => m.kind === 'method');
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
          minHeight: HEADER_H,
          textAlign: 'center',
          fontWeight: 600,
          background: 'var(--surface)',
          borderBottom: '1px solid #555',
          padding: '4px 6px',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
        {d.stereotype && (
          <div style={{ fontWeight: 400, fontStyle: 'italic', color: '#888', fontSize: 11 }}>
            «{d.stereotype}»
          </div>
        )}
        {name}
      </div>
      {members.length === 0 ? (
        <div style={{ height: ROW_H, lineHeight: `${ROW_H}px`, textAlign: 'center', color: 'var(--muted)' }}>
          (無成員)
        </div>
      ) : (
        <>
          {attrs.map((m, i) => (
            <div
              key={`a${i}`}
              style={{
                height: ROW_H,
                lineHeight: `${ROW_H}px`,
                padding: '0 6px',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {memberLine(m)}
            </div>
          ))}
          {methods.length > 0 && (
            <div style={{ borderTop: '1px solid #555' }}>
              {methods.map((m, i) => (
                <div
                  key={`m${i}`}
                  style={{
                    height: ROW_H,
                    lineHeight: `${ROW_H}px`,
                    padding: '0 6px',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {memberLine(m)}
                </div>
              ))}
            </div>
          )}
        </>
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

type Snap = { nodes: Node[]; edges: Edge[]; dir: string };

/** edge.data 載入關係的結構化欄位(節點 id 即類名)。 */
type EdgeData = {
  type: ClassRelType;
  label: string;
  leftCard: string;
  rightCard: string;
};

/** 邊標籤文字:[leftCard] type-token [rightCard] : label。 */
function relTokenOf(t: ClassRelType): string {
  return REL_OPTS.find((o) => o.value === t)?.label.replace(/^.*\(|\)$/g, '') ?? t;
}
function edgeLabel(d: EdgeData): string {
  const head = `${d.leftCard ? `${d.leftCard} ` : ''}${relTokenOf(d.type)}${
    d.rightCard ? ` ${d.rightCard}` : ''
  }`;
  return d.label ? `${head} : ${d.label}` : head;
}

function layout(nodes: Node[], edges: Edge[], dir: string): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: dir === 'TD' ? 'TB' : dir, nodesep: 48, ranksep: 80 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => {
    const d = n.data as { stereotype?: string; members?: ClassMember[] };
    g.setNode(n.id, {
      width: NODE_W,
      height: classHeight({ stereotype: d.stereotype, members: d.members ?? [] }),
    });
  });
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  return nodes.map((n) => {
    const p = g.node(n.id);
    const d = n.data as { stereotype?: string; members?: ClassMember[] };
    const h = classHeight({ stereotype: d.stereotype, members: d.members ?? [] });
    return { ...n, position: { x: p.x - NODE_W / 2, y: p.y - h / 2 } };
  });
}

export default function ClassEditor({ code, onSave, onClose, fill }: Props) {
  const nodeTypes = useMemo(() => ({ klass: ClassNodeView }), []);

  const init = useMemo(() => {
    const model = parseClass(code);
    const ns: Node[] = model.classes.map((c) => ({
      id: c.name,
      type: 'klass',
      data: { name: c.name, stereotype: c.stereotype, members: c.members },
      position: { x: 0, y: 0 },
    }));
    const es: Edge[] = model.rels.map((r, i) => {
      const data: EdgeData = {
        type: r.type,
        label: r.label ?? '',
        leftCard: r.leftCard ?? '',
        rightCard: r.rightCard ?? '',
      };
      return {
        id: `r${i}-${r.left}-${r.right}`,
        source: r.left,
        target: r.right,
        label: edgeLabel(data),
        data,
      };
    });
    return { dir: model.dir, nodes: layout(ns, es, model.dir), edges: es };
  }, [code]);

  const [nodes, setNodes] = useState<Node[]>(init.nodes);
  const [edges, setEdges] = useState<Edge[]>(init.edges);
  const [dir, setDir] = useState(init.dir);
  const [seq, setSeq] = useState(1);

  // 雙擊編輯狀態:類別(含成員草稿)/ 關係。
  const [editClass, setEditClass] = useState<{
    id: string;
    name: string;
    stereotype: string;
    members: ClassMember[];
  } | null>(null);
  const [editEdge, setEditEdge] = useState<{
    id: string;
    type: ClassRelType;
    label: string;
    leftCard: string;
    rightCard: string;
  } | null>(null);
  const [adding, setAdding] = useState<string | null>(null);

  // 復原 / 重做:快照堆疊;copy/paste:剪貼簿 ref。
  const [past, setPast] = useState<Snap[]>([]);
  const [future, setFuture] = useState<Snap[]>([]);
  const clipboard = useRef<{ nodes: Node[]; edges: Edge[] } | null>(null);

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
      // 新關係預設 association(-->),無 card / label。
      const data: EdgeData = { type: 'association', label: '', leftCard: '', rightCard: '' };
      setEdges((e) =>
        addEdge(
          {
            ...c,
            id: `r-${c.source}-${c.target}-${e.length}`,
            label: edgeLabel(data),
            data,
          },
          e,
        ),
      );
    },
    [takeSnapshot],
  );

  const reLayout = (d = dir) => setNodes((n) => layout(n, edges, d));

  const addClass = () => {
    const name = (adding ?? '').trim();
    if (!name) return;
    takeSnapshot();
    let id = name;
    let s = seq;
    while (nodes.some((n) => n.id === id)) id = `${name}_${s++}`;
    setSeq(s + 1);
    setNodes((n) => [
      ...n,
      {
        id,
        type: 'klass',
        data: { name: id, stereotype: undefined, members: [] as ClassMember[] },
        position: { x: 40, y: 40 },
      },
    ]);
    setAdding(null);
  };

  const applyClass = () => {
    if (!editClass) return;
    const newName = editClass.name.trim() || editClass.id;
    // 改名後若與「其他」類別重名 → 提示並中止,避免產生重名類別。
    const dup = nodes.some(
      (n) => n.id !== editClass.id && String((n.data as { name?: string }).name ?? n.id) === newName,
    );
    if (dup) {
      message.error(`類別名「${newName}」已存在`);
      return;
    }
    takeSnapshot();
    const stereotype = editClass.stereotype.trim() || undefined;
    // 清掉沒填 text 的空白成員列。
    const members = editClass.members
      .map<ClassMember>((m) => ({ vis: m.vis, text: m.text.trim(), kind: m.kind }))
      .filter((m) => m.text);
    // 改名:同步把節點 id 換成新類名,並重新指向引用舊 id 的關係端點,
    // 讓記憶體中的圖在改名後立即保持一致(不只在序列化時才修正)。
    const oldId = editClass.id;
    const renamed = newName !== oldId;
    setNodes((ns) =>
      ns.map((n) =>
        n.id === oldId
          ? { ...n, id: newName, data: { ...n.data, name: newName, stereotype, members } }
          : n,
      ),
    );
    if (renamed) {
      setEdges((es) =>
        es.map((e) => ({
          ...e,
          source: e.source === oldId ? newName : e.source,
          target: e.target === oldId ? newName : e.target,
        })),
      );
    }
    setEditClass(null);
  };

  const applyEdge = () => {
    if (!editEdge) return;
    takeSnapshot();
    setEdges((es) =>
      es.map((e) => {
        if (e.id !== editEdge.id) return e;
        const data: EdgeData = {
          type: editEdge.type,
          label: editEdge.label.trim(),
          leftCard: editEdge.leftCard.trim(),
          rightCard: editEdge.rightCard.trim(),
        };
        return { ...e, data, label: edgeLabel(data) };
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

  // 成員列編輯小工具(只在 editClass Modal 內用)。kind 預設由 text 是否含 () 推斷。
  const updateMember = (idx: number, patch: Partial<ClassMember>) =>
    setEditClass((s) =>
      s
        ? {
            ...s,
            members: s.members.map((m, i) => {
              if (i !== idx) return m;
              const next = { ...m, ...patch };
              // 若改了 text 而沒指定 kind:自動依 () 判定。
              if (patch.text !== undefined && patch.kind === undefined) {
                next.kind = patch.text.includes('(') && patch.text.includes(')') ? 'method' : 'attr';
              }
              return next;
            }),
          }
        : s,
    );
  const addMemberRow = () =>
    setEditClass((s) =>
      s ? { ...s, members: [...s.members, { vis: '+', text: '', kind: 'attr' }] } : s,
    );
  const removeMemberRow = (idx: number) =>
    setEditClass((s) => (s ? { ...s, members: s.members.filter((_, i) => i !== idx) } : s));

  const save = (stay = false) => {
    // node.id → 目前 data.name 對應:rename 後節點 id 不變(仍為舊類名),
    // 但 data.name 已更新;關係邊以 id 指向端點,故序列化時一律經此對應換回最新類名,
    // 確保關係 left/right 與類名一致(不會殘留舊名)。
    const nameById = new Map<string, string>(
      nodes.map((n) => [n.id, String((n.data as { name?: string }).name ?? n.id)]),
    );
    const model: ClassModel = {
      dir,
      classes: nodes.map<ClassNode>((n) => {
        const d = n.data as { name?: string; stereotype?: string; members?: ClassMember[] };
        return {
          name: nameById.get(n.id) ?? n.id,
          stereotype: d.stereotype,
          members: (d.members ?? []).map((m) => ({ vis: m.vis, text: m.text, kind: m.kind })),
        };
      }),
      // 以 nameById 重組每條關係的 left/right(最新類名);端點已不存在者過濾掉。
      rels: edges.flatMap<ClassRel>((e) => {
        const left = nameById.get(e.source);
        const right = nameById.get(e.target);
        if (left === undefined || right === undefined) return [];
        const d = (e.data ?? {}) as Partial<EdgeData>;
        return [
          {
            left,
            right,
            type: d.type ?? 'association',
            label: d.label || undefined,
            leftCard: d.leftCard || undefined,
            rightCard: d.rightCard || undefined,
          },
        ];
      }),
    };
    onSave(serializeClass(model), { stay });
  };
  saveRef.current = save; // 每次 render 更新,供 Ctrl+S 取最新

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: fill ? '100%' : '70vh' }}>
      <Space wrap style={{ marginBottom: 8 }}>
        <Button icon={<PlusOutlined />} onClick={() => setAdding('')} data-loc="class:add">
          新增類別
        </Button>
        <Space.Compact>
          <Button
            size="small"
            icon={<UndoOutlined />}
            disabled={!past.length}
            onClick={undo}
            title="復原(Ctrl+Z)"
            data-loc="class:undo"
          />
          <Button
            size="small"
            icon={<RedoOutlined />}
            disabled={!future.length}
            onClick={redo}
            title="重做(Ctrl+Y)"
            data-loc="class:redo"
          />
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
            data-loc="class:dir"
          />
        </span>
        <Button
          size="small"
          onClick={() => {
            takeSnapshot();
            reLayout();
          }}
          data-loc="class:layout"
        >
          自動排版
        </Button>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          雙擊類別改成員 · 雙擊邊改關係 · 拖把手連線 · Delete 刪 · Ctrl+C/V 複製貼上 · Ctrl+Z/Y 復原重做
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
        data-loc="class:canvas"
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
            const d = n.data as { name?: string; stereotype?: string; members?: ClassMember[] };
            setEditClass({
              id: n.id,
              name: String(d.name ?? n.id),
              stereotype: d.stereotype ?? '',
              members: (d.members ?? []).map((m) => ({ vis: m.vis, text: m.text, kind: m.kind })),
            });
          }}
          nodeTypes={nodeTypes}
          onEdgeDoubleClick={(_e, ed) => {
            const d = (ed.data ?? {}) as Partial<EdgeData>;
            setEditEdge({
              id: ed.id,
              type: d.type ?? 'association',
              label: d.label ?? '',
              leftCard: d.leftCard ?? '',
              rightCard: d.rightCard ?? '',
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
        <Button onClick={onClose} data-loc="class:cancel">
          取消
        </Button>
        <Button onClick={() => save(true)} title="存檔但留在編輯器(Ctrl+S)" data-loc="class:save">
          儲存
        </Button>
        <Button type="primary" onClick={() => save(false)} data-loc="class:apply">
          套用
        </Button>
      </Space>

      {/* 類別編輯:改名 + stereotype + 成員清單 */}
      <Modal
        title="編輯類別"
        open={!!editClass}
        onOk={applyClass}
        onCancel={() => setEditClass(null)}
        okText="確定"
        cancelText="取消"
        width={680}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Space wrap>
            <span>
              類名{' '}
              <Input
                style={{ width: 200 }}
                value={editClass?.name ?? ''}
                onChange={(e) => setEditClass((s) => (s ? { ...s, name: e.target.value } : s))}
                data-loc="class:class-name"
              />
            </span>
            <span>
              stereotype{' '}
              <Input
                style={{ width: 160 }}
                value={editClass?.stereotype ?? ''}
                onChange={(e) =>
                  setEditClass((s) => (s ? { ...s, stereotype: e.target.value } : s))
                }
                placeholder="interface / abstract"
                data-loc="class:class-stereotype"
              />
            </span>
          </Space>
          <Space direction="vertical" style={{ width: '100%' }} size={6}>
            {editClass?.members.map((m, i) => (
              <Space key={i} wrap>
                <Select
                  style={{ width: 120 }}
                  value={m.vis}
                  onChange={(v: Visibility) => updateMember(i, { vis: v })}
                  options={VIS_OPTS}
                  data-loc="class:member-vis"
                />
                <Input
                  placeholder="int age / eat() void"
                  style={{ width: 240 }}
                  value={m.text}
                  onChange={(e) => updateMember(i, { text: e.target.value })}
                  data-loc="class:member-text"
                />
                <Select
                  style={{ width: 120 }}
                  value={m.kind}
                  onChange={(v: MemberKind) => updateMember(i, { kind: v })}
                  options={KIND_OPTS}
                  data-loc="class:member-kind"
                />
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => removeMemberRow(i)}
                  data-loc="class:member-del"
                />
              </Space>
            ))}
            <Button
              size="small"
              icon={<PlusOutlined />}
              onClick={addMemberRow}
              data-loc="class:member-add"
            >
              新增成員
            </Button>
          </Space>
        </Space>
      </Modal>

      {/* 關係編輯:type / multiplicity / label */}
      <Modal
        title="編輯關係"
        open={!!editEdge}
        onOk={applyEdge}
        onCancel={() => setEditEdge(null)}
        okText="確定"
        cancelText="取消"
        footer={[
          <Button key="del" danger onClick={deleteEdge} data-loc="class:rel-del">
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
            type{' '}
            <Select
              style={{ width: 220 }}
              value={editEdge?.type ?? 'association'}
              onChange={(v: ClassRelType) => setEditEdge((s) => (s ? { ...s, type: v } : s))}
              options={REL_OPTS}
              data-loc="class:rel-type"
            />
          </span>
          <span>
            左 multiplicity{' '}
            <Input
              style={{ width: 160 }}
              value={editEdge?.leftCard ?? ''}
              onChange={(e) => setEditEdge((s) => (s ? { ...s, leftCard: e.target.value } : s))}
              placeholder='如 1 / 0..*'
              data-loc="class:rel-left-card"
            />
          </span>
          <span>
            右 multiplicity{' '}
            <Input
              style={{ width: 160 }}
              value={editEdge?.rightCard ?? ''}
              onChange={(e) => setEditEdge((s) => (s ? { ...s, rightCard: e.target.value } : s))}
              placeholder='如 1 / *'
              data-loc="class:rel-right-card"
            />
          </span>
          <span>
            label{' '}
            <Input
              style={{ width: 240 }}
              value={editEdge?.label ?? ''}
              onChange={(e) => setEditEdge((s) => (s ? { ...s, label: e.target.value } : s))}
              onPressEnter={applyEdge}
              placeholder="(可空白)"
              data-loc="class:rel-label"
            />
          </span>
        </Space>
      </Modal>

      {/* 新增類別 */}
      <Modal
        title="新增類別"
        open={adding !== null}
        onOk={addClass}
        onCancel={() => setAdding(null)}
        okText="新增"
        cancelText="取消"
        okButtonProps={{ disabled: !adding?.trim() }}
      >
        <Input
          autoFocus
          value={adding ?? ''}
          onChange={(e) => setAdding(e.target.value)}
          onPressEnter={addClass}
          placeholder="類別名稱(如 Animal)"
          data-loc="class:add-name"
        />
      </Modal>
    </div>
  );
}
