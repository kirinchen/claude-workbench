/**
 * SequenceEditor — mermaid sequenceDiagram 子集 的 GUI 編輯器(清單 / 表單式,不用 React Flow)。
 *  - 參與者區:可增 / 刪 / 上下移的列(id Input、alias Input、actor Switch)。
 *  - 訊息區:有序列,每列 [from][arrow][to][text] + activate / deactivate 小開關,可增 / 刪 / 上下移。
 *  - undo / redo:對整個 SeqModel 做快照堆疊(比照 FlowEditor 手法,但對 model)。
 *  - 「套用」→ serializeSequence → onSave(正規化 mermaid 文字);「取消」→ onClose。
 *  本元件輕量(純表單)→ 可由上層以 lazy + Suspense 載入。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button, Input, Select, Space, Switch, Typography, List } from 'antd';
import {
  PlusOutlined,
  UndoOutlined,
  RedoOutlined,
  DeleteOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
} from '@ant-design/icons';
import {
  parseSequence,
  serializeSequence,
  type SeqArrow,
  type SeqMessage,
  type SeqModel,
  type SeqParticipant,
} from '../lib/mermaidSequence';

const ARROW_OPTS: { value: SeqArrow; label: string }[] = [
  { value: 'solid', label: '->> 實心(sync)' },
  { value: 'dashed', label: '-->> 虛線(reply)' },
  { value: 'solidOpen', label: '-> 實線無箭頭' },
  { value: 'dashedOpen', label: '--> 虛線無箭頭' },
  { value: 'async', label: '-) 實線開放' },
  { value: 'asyncDashed', label: '--) 虛線開放' },
  { value: 'cross', label: '-x 實線叉' },
  { value: 'crossDashed', label: '--x 虛線叉' },
];

interface Props {
  code: string;
  onSave: (code: string, opts?: { stay?: boolean }) => void;
  onClose: () => void;
  /** 滿版模式:撐滿父容器高度(由上層的全螢幕切換帶入)。 */
  fill?: boolean;
}

/**
 * 編輯器內部用的「帶穩定 key」包裝:`uid` 只供 React key,絕不進序列化 model。
 * (序列化前會在 save 內把 uid 剝掉,只取回 SeqParticipant / SeqMessage 欄位。)
 */
type Keyed<T> = T & { uid: string };

// 穩定唯一 id 產生器:優先 crypto.randomUUID,fallback 流水號。
let uidCounter = 0;
function makeUid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `uid-${Date.now()}-${uidCounter++}`;
}

/** 把陣列中 idx 與 idx+dir 兩項對調(回傳新陣列;越界則原樣回傳)。 */
function moveItem<T>(arr: T[], idx: number, dir: -1 | 1): T[] {
  const to = idx + dir;
  if (to < 0 || to >= arr.length) return arr;
  const next = arr.slice();
  [next[idx], next[to]] = [next[to], next[idx]];
  return next;
}

// 編輯器內部 model:與 SeqModel 同構,但每列多帶一個穩定 uid(僅供 React key)。
interface KeyedModel {
  participants: Keyed<SeqParticipant>[];
  messages: Keyed<SeqMessage>[];
}

export default function SequenceEditor({ code, onSave, onClose, fill }: Props) {
  const init = useMemo(() => parseSequence(code), [code]);

  const [participants, setParticipants] = useState<Keyed<SeqParticipant>[]>(() =>
    init.participants.map((p) => ({ ...p, uid: makeUid() })),
  );
  const [messages, setMessages] = useState<Keyed<SeqMessage>[]>(() =>
    init.messages.map((m) => ({ ...m, uid: makeUid() })),
  );
  // 自動產生新參與者 id 的流水號。
  const [seq, setSeq] = useState(1);

  // 復原 / 重做:對整個 model 做快照堆疊(上限 50)。
  const [past, setPast] = useState<KeyedModel[]>([]);
  const [future, setFuture] = useState<KeyedModel[]>([]);

  // 在「變動之前」呼叫:把當前 model 推進 past、清空 future。
  const takeSnapshot = useCallback(() => {
    setPast((p) => [...p.slice(-49), { participants, messages }]);
    setFuture([]);
  }, [participants, messages]);

  const undo = useCallback(() => {
    if (!past.length) return;
    const prev = past[past.length - 1];
    setFuture((f) => [{ participants, messages }, ...f]);
    setPast((p) => p.slice(0, -1));
    setParticipants(prev.participants);
    setMessages(prev.messages);
  }, [past, participants, messages]);

  const redo = useCallback(() => {
    if (!future.length) return;
    const next = future[0];
    setPast((p) => [...p, { participants, messages }]);
    setFuture((f) => f.slice(1));
    setParticipants(next.participants);
    setMessages(next.messages);
  }, [future, participants, messages]);

  // saveRef:讓 window Ctrl+S 取到最新 save(save 定義在後且依賴 participants/messages,避免 stale 閉包)。
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

  // Ctrl+S = 存檔但留在編輯器。綁 window(不限焦點,點過工具列也有效)。
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

  // ── 參與者操作 ─────────────────────────────────────────────
  const addParticipant = () => {
    takeSnapshot();
    let s = seq;
    const used = new Set(participants.map((p) => p.id));
    let id = `P${s++}`;
    while (used.has(id)) id = `P${s++}`;
    setSeq(s);
    setParticipants((ps) => [...ps, { id, actor: false, uid: makeUid() }]);
  };

  const updateParticipant = (idx: number, patch: Partial<SeqParticipant>) => {
    takeSnapshot();
    // 改 id 時同步把所有 from/to 指到舊 id 的訊息改成新 id,避免端點懸空。
    const oldId = participants[idx]?.id;
    const newId = patch.id;
    if (newId !== undefined && oldId !== undefined && newId !== oldId) {
      setMessages((ms) =>
        ms.map((m) => {
          if (m.from !== oldId && m.to !== oldId) return m;
          return {
            ...m,
            from: m.from === oldId ? newId : m.from,
            to: m.to === oldId ? newId : m.to,
          };
        }),
      );
    }
    setParticipants((ps) => ps.map((p, i) => (i === idx ? { ...p, ...patch } : p)));
  };

  const removeParticipant = (idx: number) => {
    takeSnapshot();
    setParticipants((ps) => ps.filter((_, i) => i !== idx));
  };

  const moveParticipant = (idx: number, dir: -1 | 1) => {
    takeSnapshot();
    setParticipants((ps) => moveItem(ps, idx, dir));
  };

  // ── 訊息操作 ───────────────────────────────────────────────
  const addMessage = () => {
    takeSnapshot();
    // 預設端點:有參與者就用前兩個,否則留空(套用前需自行選擇)。
    const from = participants[0]?.id ?? '';
    const to = participants[1]?.id ?? participants[0]?.id ?? '';
    setMessages((ms) => [...ms, { from, to, arrow: 'solid', text: '', uid: makeUid() }]);
  };

  const updateMessage = (idx: number, patch: Partial<SeqMessage>) => {
    takeSnapshot();
    setMessages((ms) => ms.map((m, i) => (i === idx ? { ...m, ...patch } : m)));
  };

  const removeMessage = (idx: number) => {
    takeSnapshot();
    setMessages((ms) => ms.filter((_, i) => i !== idx));
  };

  const moveMessage = (idx: number, dir: -1 | 1) => {
    takeSnapshot();
    setMessages((ms) => moveItem(ms, idx, dir));
  };

  // 參與者下拉選項:用 id(顯示 id 與 alias)。
  const pOptions = useMemo(
    () =>
      participants.map((p) => ({
        value: p.id,
        label: p.alias ? `${p.id} (${p.alias})` : p.id,
      })),
    [participants],
  );

  const save = (stay = false) => {
    // 清掉沒填 id 的空白參與者列;訊息端點 trim。
    const cleanParticipants = participants
      .map<SeqParticipant>((p) => ({
        id: p.id.trim(),
        alias: p.alias?.trim() || undefined,
        actor: p.actor,
      }))
      .filter((p) => p.id);
    const validIds = new Set(cleanParticipants.map((p) => p.id));
    const cleanMessages = messages
      .map<SeqMessage>((m) => ({
        from: m.from.trim(),
        to: m.to.trim(),
        arrow: m.arrow,
        text: m.text,
        activate: m.activate || undefined,
        deactivate: m.deactivate || undefined,
      }))
      // 兩端皆須為已存在的參與者(避免序列化出空端點)。
      .filter((m) => m.from && m.to && validIds.has(m.from) && validIds.has(m.to));
    const model: SeqModel = { participants: cleanParticipants, messages: cleanMessages };
    onSave(serializeSequence(model), { stay });
  };
  saveRef.current = save; // 每次 render 更新,供 Ctrl+S 取最新

  return (
    <div
      style={{ display: 'flex', flexDirection: 'column', height: fill ? '100%' : '70vh' }}
      tabIndex={0}
      onKeyDown={onKeyDown}
      data-loc="seq:root"
    >
      <Space wrap style={{ marginBottom: 8 }}>
        <Space.Compact>
          <Button
            size="small"
            icon={<UndoOutlined />}
            disabled={!past.length}
            onClick={undo}
            title="復原(Ctrl+Z)"
            data-loc="seq:undo"
          />
          <Button
            size="small"
            icon={<RedoOutlined />}
            disabled={!future.length}
            onClick={redo}
            title="重做(Ctrl+Y)"
            data-loc="seq:redo"
          />
        </Space.Compact>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          參與者順序即圖中由左至右 · 訊息順序即時間先後 · Ctrl+Z/Y 復原重做
        </Typography.Text>
      </Space>

      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', paddingRight: 4 }}>
        {/* ── 參與者區 ───────────────────────────────────── */}
        <Typography.Title level={5} style={{ margin: '4px 0 8px' }}>
          參與者
        </Typography.Title>
        <List
          size="small"
          bordered
          dataSource={participants}
          locale={{ emptyText: '尚無參與者' }}
          renderItem={(p, i) => (
            <List.Item key={p.uid} style={{ padding: '6px 8px' }}>
              <Space wrap>
                <Input
                  placeholder="id"
                  style={{ width: 120 }}
                  value={p.id}
                  onChange={(e) => updateParticipant(i, { id: e.target.value })}
                  data-loc="seq:participant-id"
                />
                <Input
                  placeholder="alias(可空白)"
                  style={{ width: 160 }}
                  value={p.alias ?? ''}
                  onChange={(e) => updateParticipant(i, { alias: e.target.value })}
                  data-loc="seq:participant-alias"
                />
                <span>
                  actor{' '}
                  <Switch
                    size="small"
                    checked={p.actor}
                    onChange={(v) => updateParticipant(i, { actor: v })}
                    data-loc="seq:participant-actor"
                  />
                </span>
                <Button
                  size="small"
                  icon={<ArrowUpOutlined />}
                  disabled={i === 0}
                  onClick={() => moveParticipant(i, -1)}
                  title="上移"
                  data-loc="seq:participant-up"
                />
                <Button
                  size="small"
                  icon={<ArrowDownOutlined />}
                  disabled={i === participants.length - 1}
                  onClick={() => moveParticipant(i, 1)}
                  title="下移"
                  data-loc="seq:participant-down"
                />
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => removeParticipant(i)}
                  title="刪除"
                  data-loc="seq:participant-del"
                />
              </Space>
            </List.Item>
          )}
        />
        <Button
          size="small"
          icon={<PlusOutlined />}
          onClick={addParticipant}
          style={{ marginTop: 8 }}
          data-loc="seq:add-participant"
        >
          新增參與者
        </Button>

        {/* ── 訊息區 ─────────────────────────────────────── */}
        <Typography.Title level={5} style={{ margin: '16px 0 8px' }}>
          訊息
        </Typography.Title>
        <List
          size="small"
          bordered
          dataSource={messages}
          locale={{ emptyText: '尚無訊息' }}
          renderItem={(m, i) => (
            <List.Item key={m.uid} style={{ padding: '6px 8px' }}>
              <Space wrap>
                <Select
                  placeholder="from"
                  style={{ width: 130 }}
                  value={m.from || undefined}
                  onChange={(v: string) => updateMessage(i, { from: v })}
                  options={pOptions}
                  data-loc="seq:message-from"
                />
                <Select
                  style={{ width: 170 }}
                  value={m.arrow}
                  onChange={(v: SeqArrow) => updateMessage(i, { arrow: v })}
                  options={ARROW_OPTS}
                  data-loc="seq:message-arrow"
                />
                <Select
                  placeholder="to"
                  style={{ width: 130 }}
                  value={m.to || undefined}
                  onChange={(v: string) => updateMessage(i, { to: v })}
                  options={pOptions}
                  data-loc="seq:message-to"
                />
                <Input
                  placeholder="text"
                  style={{ width: 180 }}
                  value={m.text}
                  onChange={(e) => updateMessage(i, { text: e.target.value })}
                  data-loc="seq:message-text"
                />
                <span>
                  +act{' '}
                  <Switch
                    size="small"
                    checked={!!m.activate}
                    onChange={(v) => updateMessage(i, { activate: v })}
                    title="目標前 + (activate)"
                    data-loc="seq:message-activate"
                  />
                </span>
                <span>
                  -deact{' '}
                  <Switch
                    size="small"
                    checked={!!m.deactivate}
                    onChange={(v) => updateMessage(i, { deactivate: v })}
                    title="目標前 -(deactivate)"
                    data-loc="seq:message-deactivate"
                  />
                </span>
                <Button
                  size="small"
                  icon={<ArrowUpOutlined />}
                  disabled={i === 0}
                  onClick={() => moveMessage(i, -1)}
                  title="上移"
                  data-loc="seq:message-up"
                />
                <Button
                  size="small"
                  icon={<ArrowDownOutlined />}
                  disabled={i === messages.length - 1}
                  onClick={() => moveMessage(i, 1)}
                  title="下移"
                  data-loc="seq:message-down"
                />
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => removeMessage(i)}
                  title="刪除"
                  data-loc="seq:message-del"
                />
              </Space>
            </List.Item>
          )}
        />
        <Button
          size="small"
          icon={<PlusOutlined />}
          onClick={addMessage}
          style={{ marginTop: 8 }}
          data-loc="seq:add-message"
        >
          新增訊息
        </Button>
      </div>

      <Space style={{ marginTop: 8, justifyContent: 'flex-end' }}>
        <Button onClick={onClose} data-loc="seq:cancel">
          取消
        </Button>
        <Button onClick={() => save(true)} title="存檔但留在編輯器(Ctrl+S)" data-loc="seq:save">
          儲存
        </Button>
        <Button type="primary" onClick={() => save(false)} data-loc="seq:apply">
          套用
        </Button>
      </Space>
    </div>
  );
}
