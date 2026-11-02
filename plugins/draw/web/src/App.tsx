/**
 * draw — 主畫面。網址就是狀態(重新整理 = 重讀最新版,agent 改完圖使用者按 F5 就看得到):
 *   ?cwd=<目錄>                       首頁:選圖型 / 一次性的圖 / 開既有檔
 *   ?cwd=…&path=<檔>[&index=N]        編輯檔案裡的圖(md 的第 N 個圖區塊,或原生單檔)
 *   ?cwd=…&mem=<id>                   編輯一次性的圖(只在 server 記憶體)
 */
import { useCallback, useEffect, useMemo, useRef, useState, lazy, Suspense } from 'react';
import { Alert, Button, Card, Input, Modal, Radio, Space, Spin, Tag, Tooltip, Typography, message } from 'antd';
import { api, ApiError, BOOT, type FileDoc, type Info, type MemDrawing } from './api';
import { CHARTS, KIND_LABEL, EMPTY_EXCALIDRAW, type ChartDef, type Kind } from './charts';

const MermaidBlock = lazy(() => import('./components/MermaidBlock'));
const D2Block = lazy(() => import('./components/D2Block'));
const ExcalidrawBlock = lazy(() => import('./components/ExcalidrawBlock'));

const { Text, Title } = Typography;

function useQuery() {
  const [q, setQ] = useState(() => new URLSearchParams(location.search));
  useEffect(() => {
    const on = () => setQ(new URLSearchParams(location.search));
    window.addEventListener('popstate', on);
    return () => window.removeEventListener('popstate', on);
  }, []);
  const go = useCallback((next: Record<string, string | undefined>) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(next)) if (v !== undefined && v !== '') p.set(k, v);
    history.pushState(null, '', `?${p}`);
    setQ(p);
  }, []);
  return [q, go] as const;
}

export default function App() {
  const [q, go] = useQuery();
  const [info, setInfo] = useState<Info | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  useEffect(() => {
    api.info().then(setInfo, (e: Error) => setFatal(e.message));
  }, []);

  const cwd = q.get('cwd') || info?.home || '';
  const path = q.get('path') || undefined;
  const mem = q.get('mem') || undefined;
  const index = q.get('index') ? Number(q.get('index')) : undefined;

  const home = () => go({ cwd });

  return (
    <div className="draw-app">
      <header className="draw-head">
        <a className="draw-logo" onClick={home} title="回首頁">
          ✏️ draw
        </a>
        <Text type="secondary" className="draw-cwd" title="「目前目錄」= 跑 /draw 的地方">
          {cwd}
        </Text>
        <span style={{ flex: 1 }} />
        <Text type="secondary" style={{ fontSize: 12 }}>
          v{BOOT.version}
        </Text>
      </header>
      <main className="draw-main">
        {fatal ? (
          <Alert type="error" showIcon message="連不上 draw server" description={`${fatal} —— 重跑 /draw 再開一次。`} />
        ) : !info ? (
          <Spin />
        ) : mem ? (
          <MemEditor key={mem} id={mem} onHome={home} />
        ) : path ? (
          <FileEditor key={`${path}#${index ?? ''}`} cwd={cwd} path={path} index={index} go={go} onHome={home} info={info} />
        ) : (
          <Home cwd={cwd} info={info} go={go} />
        )}
      </main>
    </div>
  );
}

// ---------------- 首頁 ----------------

function Home({ cwd, info, go }: { cwd: string; info: Info; go: ReturnType<typeof useQuery>[1] }) {
  const [picked, setPicked] = useState<ChartDef | null>(null);
  const [mems, setMems] = useState<Omit<MemDrawing, 'code'>[]>([]);
  const [openPath, setOpenPath] = useState('');
  useEffect(() => {
    api.memList().then((r) => setMems(r.drawings), () => {});
  }, []);

  return (
    <div className="draw-home">
      <Title level={4} style={{ marginTop: 0 }}>
        要畫哪一種圖?
      </Title>
      <div className="chart-grid">
        {CHARTS.map((c) => {
          const disabled = c.kind === 'd2' && !info.d2;
          const card = (
            <Card
              key={c.id}
              hoverable={!disabled}
              size="small"
              className={`chart-card${disabled ? ' is-disabled' : ''}`}
              onClick={() => !disabled && setPicked(c)}
              data-loc={`draw:chart:${c.id}`}
            >
              <div className="chart-label">{c.label}</div>
              <div className="chart-hint">{c.hint}</div>
              <Tag style={{ marginTop: 6 }}>{KIND_LABEL[c.kind]}</Tag>
            </Card>
          );
          return disabled ? (
            <Tooltip key={c.id} title="這台機器沒有 d2 指令(https://d2lang.com 裝好後重開 server)">
              {card}
            </Tooltip>
          ) : (
            card
          );
        })}
      </div>

      <Title level={5}>開啟既有檔案</Title>
      <Space.Compact style={{ width: '100%', maxWidth: 640 }}>
        <Input
          placeholder="doc/plan.md、arch.excalidraw、flow.mmd …(相對於目前目錄)"
          value={openPath}
          onChange={(e) => setOpenPath(e.target.value)}
          onPressEnter={() => openPath.trim() && go({ cwd, path: openPath.trim() })}
        />
        <Button type="primary" disabled={!openPath.trim()} onClick={() => go({ cwd, path: openPath.trim() })}>
          開啟
        </Button>
      </Space.Compact>

      {mems.length > 0 && (
        <>
          <Title level={5}>一次性的圖(server 重開就沒了)</Title>
          <Space direction="vertical">
            {mems.map((m) => (
              <a key={m.id} onClick={() => go({ cwd, mem: m.id })}>
                <Tag>{KIND_LABEL[m.kind]}</Tag>
                {m.name} <Text type="secondary">mem:{m.id}</Text>
              </a>
            ))}
          </Space>
        </>
      )}

      {picked && (
        <SaveDialog
          chart={picked}
          cwd={cwd}
          onCancel={() => setPicked(null)}
          onDone={(r) => {
            setPicked(null);
            if (r.mem) go({ cwd, mem: r.mem });
            else go({ cwd, path: r.path, index: String(r.index ?? 0) });
          }}
        />
      )}
    </div>
  );
}

// ---------------- 保存方式 ----------------

type SaveMode = 'memory' | 'here' | 'path';
type Format = 'md' | 'native';
const NATIVE_EXT: Record<Kind, string> = { mermaid: '.mmd', excalidraw: '.excalidraw', d2: '.d2' };

function SaveDialog({
  chart,
  cwd,
  fixedPath,
  onCancel,
  onDone,
}: {
  chart: ChartDef;
  cwd: string;
  /** 從既有 md 進來新增圖 → 路徑固定(接在文件尾端) */
  fixedPath?: string;
  onCancel: () => void;
  onDone: (r: { mem?: string; path?: string; index?: number }) => void;
}) {
  const [mode, setMode] = useState<SaveMode>(fixedPath ? 'path' : 'here');
  const [name, setName] = useState(chart.id === 'excalidraw' ? 'whiteboard' : `${chart.id}-diagram`);
  const [target, setTarget] = useState(fixedPath ?? '');
  const [format, setFormat] = useState<Format>('md');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // 指定路徑若已帶副檔名 → 格式跟著副檔名走
  const pathFormat: Format | null = /\.(md|markdown)$/i.test(target) ? 'md' : /\.(mmd|mermaid|excalidraw|d2)$/i.test(target) ? 'native' : null;
  const effFormat = mode === 'path' && pathFormat ? pathFormat : format;
  const ext = effFormat === 'md' ? '.md' : NATIVE_EXT[chart.kind];
  const preview =
    mode === 'memory'
      ? '只存在 draw server 的記憶體;關掉 server 或重開機就沒了'
      : mode === 'here'
        ? `${cwd.replace(/\/$/, '')}/${name.trim() || '…'}${ext}`
        : target.trim()
          ? `${target.trim()}${pathFormat ? '' : ext}${effFormat === 'md' ? '(已存在就把圖接在文件尾端)' : ''}`
          : '…';

  const ok = async () => {
    setBusy(true);
    setErr(null);
    try {
      const code = chart.kind === 'excalidraw' ? EMPTY_EXCALIDRAW : chart.code;
      if (mode === 'memory') {
        const d = await api.memCreate(chart.kind, code, name.trim() || undefined);
        onDone({ mem: d.id });
        return;
      }
      const p = mode === 'here' ? name.trim() : target.trim();
      if (!p) throw new Error(mode === 'here' ? '要給名稱' : '要給路徑');
      if (mode === 'here' && /[\\/]/.test(p)) throw new Error('名稱不能有 / —— 要存到別的目錄請選「存在指定的地方」');
      const r = await api.fileCreate(cwd, p, chart.kind, code, effFormat);
      if (r.appended) message.info(`已把圖接在 ${r.path} 尾端`);
      onDone({ path: r.path, index: r.index });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      title={`${chart.label} —— 這張圖要怎麼保存?`}
      okText="開始畫"
      cancelText="取消"
      onOk={ok}
      onCancel={onCancel}
      confirmLoading={busy}
      width={560}
      data-loc="draw:save"
    >
      <Radio.Group value={mode} onChange={(e) => setMode(e.target.value)} style={{ width: '100%' }} disabled={!!fixedPath}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Radio value="memory">
            <b>一次性</b> <Text type="secondary">—— 不存檔,重開 server 就沒了</Text>
          </Radio>
          <Radio value="here">
            <b>存在目前目錄</b> <Text type="secondary">—— 要給名稱</Text>
          </Radio>
          {mode === 'here' && (
            <Input autoFocus value={name} onChange={(e) => setName(e.target.value)} onPressEnter={ok} addonAfter={ext} style={{ marginLeft: 24, width: 'calc(100% - 24px)' }} />
          )}
          <Radio value="path">
            <b>存在指定的地方</b> <Text type="secondary">—— 相對於目前目錄,或絕對路徑 / ~/…</Text>
          </Radio>
          {mode === 'path' && (
            <Input
              autoFocus
              value={target}
              disabled={!!fixedPath}
              onChange={(e) => setTarget(e.target.value)}
              onPressEnter={ok}
              placeholder="doc/plan.md 或 ~/notes/arch.excalidraw"
              style={{ marginLeft: 24, width: 'calc(100% - 24px)' }}
            />
          )}
          {mode === 'memory' && (
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="名稱(選填,方便 agent 認)" style={{ marginLeft: 24, width: 'calc(100% - 24px)' }} />
          )}
        </Space>
      </Radio.Group>

      {mode !== 'memory' && (
        <div style={{ marginTop: 16 }}>
          <Text type="secondary">存成:</Text>{' '}
          <Radio.Group
            size="small"
            optionType="button"
            value={effFormat}
            disabled={(mode === 'path' && !!pathFormat) || !!fixedPath}
            onChange={(e) => setFormat(e.target.value)}
            options={[
              { label: 'Markdown 內嵌(.md)', value: 'md' },
              { label: `原生單檔(${NATIVE_EXT[chart.kind]})`, value: 'native' },
            ]}
          />
          <div style={{ marginTop: 6 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {effFormat === 'md'
                ? `圖以 \`\`\`${chart.kind} 區塊寫在 md 裡 —— 企劃 / SPEC 跟圖放同一份,agent 讀得懂`
                : '一個檔一張圖'}
            </Text>
          </div>
        </div>
      )}

      <div className="save-preview">→ {preview}</div>
      {err && <Alert type="error" showIcon message={err} style={{ marginTop: 12 }} />}
    </Modal>
  );
}

// ---------------- 編輯器 ----------------

function DiagramEditor({ kind, code, onApply }: { kind: Kind; code: string; onApply: (c: string) => void }) {
  const Comp = kind === 'mermaid' ? MermaidBlock : kind === 'd2' ? D2Block : ExcalidrawBlock;
  return (
    <Suspense fallback={<Spin />}>
      <Comp code={code} onApply={onApply} initialMode="gui" />
    </Suspense>
  );
}

/** 每 2 秒看一次來源有沒有被別人(agent)改過;改過就提示重新載入(不自動蓋掉畫到一半的東西)。 */
function useChangedElsewhere(check: () => Promise<string>, current: string | null) {
  const [changed, setChanged] = useState(false);
  const cur = useRef(current);
  cur.current = current;
  useEffect(() => {
    setChanged(false);
  }, [current]);
  useEffect(() => {
    const t = setInterval(() => {
      if (document.hidden || cur.current === null) return;
      check().then(
        (s) => setChanged(s !== cur.current),
        () => {},
      );
    }, 2000);
    return () => clearInterval(t);
  }, [check]);
  return changed;
}

function EditorShell({
  title,
  tags,
  changed,
  onReload,
  onHome,
  children,
}: {
  title: string;
  tags: React.ReactNode;
  changed: boolean;
  onReload: () => void;
  onHome: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="draw-editor">
      <div className="editor-bar">
        <Button size="small" onClick={onHome}>
          ← 回首頁
        </Button>
        <Text strong className="editor-title" title={title}>
          {title}
        </Text>
        {tags}
        <span style={{ flex: 1 }} />
        <Text type="secondary" style={{ fontSize: 12 }}>
          GUI 裡按「儲存」或 Ctrl+S 寫回
        </Text>
        <Button size="small" onClick={onReload} title="重讀最新版(agent 改過圖之後)">
          重新載入
        </Button>
      </div>
      {changed && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 8 }}
          message="這張圖被別人改過了(可能是 agent)"
          action={
            <Button size="small" type="primary" onClick={onReload}>
              重新載入
            </Button>
          }
        />
      )}
      {children}
    </div>
  );
}

function FileEditor({
  cwd,
  path,
  index,
  go,
  onHome,
  info,
}: {
  cwd: string;
  path: string;
  index?: number;
  go: ReturnType<typeof useQuery>[1];
  onHome: () => void;
  info: Info;
}) {
  const [doc, setDoc] = useState<FileDoc | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [gen, setGen] = useState(0);
  const [adding, setAdding] = useState<ChartDef | null>(null);

  const load = useCallback(() => {
    setErr(null);
    api.fileGet(cwd, path).then(
      (d) => {
        setDoc(d);
        setGen((g) => g + 1);
      },
      (e: Error) => setErr(e.message),
    );
  }, [cwd, path]);
  useEffect(load, [load]);

  const check = useCallback(() => api.fileGet(cwd, path).then((d) => d.stamp), [cwd, path]);
  const changed = useChangedElsewhere(check, doc?.stamp ?? null);

  const effIndex = doc ? (index ?? (doc.blocks.length === 1 ? 0 : undefined)) : undefined;
  const block = doc && effIndex !== undefined ? doc.blocks[effIndex] : undefined;

  const save = useCallback(
    async (code: string, force = false) => {
      if (!doc || effIndex === undefined) return;
      try {
        const d = await api.filePut(cwd, doc.path, effIndex, code, doc.stamp, force);
        setDoc(d);
        message.success('已存檔');
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          Modal.confirm({
            title: '檔案在你畫的時候被改過了',
            content: '可能是 agent 改了圖。重新載入會丟掉你這次還沒存的改動;強制覆蓋會蓋掉對方的改動。',
            okText: '強制覆蓋',
            okButtonProps: { danger: true },
            cancelText: '先不要',
            onOk: () => save(code, true),
          });
        } else message.error((e as Error).message);
      }
    },
    [cwd, doc, effIndex],
  );

  if (err) return <Alert type="error" showIcon message={err} action={<Button onClick={onHome}>回首頁</Button>} />;
  if (!doc) return <Spin />;

  // md 裡沒有圖 / 有多張要先選
  if (!block) {
    return (
      <div className="draw-home">
        <Title level={5} style={{ marginTop: 0 }}>
          {doc.path}
        </Title>
        {doc.blocks.length > 0 ? (
          <>
            <Text type="secondary">這份文件有 {doc.blocks.length} 張圖,要編輯哪一張?</Text>
            <Space direction="vertical" style={{ marginTop: 12, display: 'flex' }}>
              {doc.blocks.map((b) => (
                <Card key={b.index} size="small" hoverable onClick={() => go({ cwd, path, index: String(b.index) })}>
                  <Tag>{KIND_LABEL[b.kind]}</Tag> 第 {b.index + 1} 張 <Text type="secondary">{firstLine(b)}</Text>
                </Card>
              ))}
            </Space>
          </>
        ) : (
          <Text type="secondary">這份文件裡還沒有圖。</Text>
        )}
        {doc.format === 'md' && (
          <>
            <Title level={5}>在文件尾端新增一張圖</Title>
            <div className="chart-grid">
              {CHARTS.filter((c) => c.kind !== 'd2' || info.d2).map((c) => (
                <Card key={c.id} size="small" hoverable className="chart-card" onClick={() => setAdding(c)}>
                  <div className="chart-label">{c.label}</div>
                  <div className="chart-hint">{c.hint}</div>
                </Card>
              ))}
            </div>
          </>
        )}
        {adding && (
          <SaveDialog
            chart={adding}
            cwd={cwd}
            fixedPath={doc.path}
            onCancel={() => setAdding(null)}
            onDone={(r) => {
              setAdding(null);
              go({ cwd, path, index: String(r.index ?? 0) });
            }}
          />
        )}
      </div>
    );
  }

  return (
    <EditorShell
      title={doc.path}
      tags={
        <>
          <Tag color="cyan">{KIND_LABEL[block.kind]}</Tag>
          {doc.format === 'md' && doc.blocks.length > 1 && (
            <a onClick={() => go({ cwd, path })}>
              第 {block.index + 1} / {doc.blocks.length} 張
            </a>
          )}
        </>
      }
      changed={changed}
      onReload={load}
      onHome={onHome}
    >
      <DiagramEditor key={gen} kind={block.kind} code={block.code} onApply={(c) => void save(c)} />
    </EditorShell>
  );
}

function firstLine(b: { kind: Kind; code: string }) {
  if (b.kind === 'excalidraw') {
    try {
      const n = (JSON.parse(b.code).elements ?? []).filter((e: { isDeleted?: boolean }) => !e.isDeleted).length;
      return `${n} 個元素`;
    } catch {
      return '';
    }
  }
  return b.code.split('\n')[0]?.slice(0, 60) ?? '';
}

function MemEditor({ id, onHome }: { id: string; onHome: () => void }) {
  const [d, setD] = useState<MemDrawing | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [gen, setGen] = useState(0);
  const load = useCallback(() => {
    api.memGet(id).then(
      (x) => {
        setD(x);
        setGen((g) => g + 1);
      },
      (e: Error) => setErr(e.message),
    );
  }, [id]);
  useEffect(load, [load]);
  const check = useCallback(() => api.memGet(id).then((x) => x.updatedAt), [id]);
  const changed = useChangedElsewhere(check, d?.updatedAt ?? null);
  const hint = useMemo(() => `agent 讀這張圖:draw.mjs summary mem:${id}`, [id]);

  if (err) return <Alert type="error" showIcon message={err} action={<Button onClick={onHome}>回首頁</Button>} />;
  if (!d) return <Spin />;
  return (
    <EditorShell
      title={d.name}
      tags={
        <>
          <Tag color="cyan">{KIND_LABEL[d.kind]}</Tag>
          <Tooltip title={hint}>
            <Tag color="orange">一次性 · mem:{id}</Tag>
          </Tooltip>
        </>
      }
      changed={changed}
      onReload={load}
      onHome={onHome}
    >
      <DiagramEditor
        key={gen}
        kind={d.kind}
        code={d.code}
        onApply={(c) =>
          void api.memPut(id, c).then(
            (x) => {
              setD(x);
              message.success('已存(一次性,server 重開就沒了)');
            },
            (e: Error) => message.error(e.message),
          )
        }
      />
    </EditorShell>
  );
}
