/**
 * MermaidBlock — mermaid 區塊,右上角 tab 切換 預覽 / 編輯 / GUI。
 *  - onApply 有給(Explore)→ 顯示 tab、可寫回;沒給(Chat)→ 純預覽。
 *  - flowchart:預覽 / 編輯 / GUI;其他 mermaid:預覽 / 編輯。
 *  - mermaid 偏重 → 動態 import;FlowEditor(React Flow)→ lazy。
 *  - securityLevel='strict':渲染 repo 檔 / LLM 內容,擋 script / click 注入。
 */
import { useEffect, useMemo, useRef, useState, lazy, Suspense } from 'react';
import { createPortal } from 'react-dom';
import { Segmented, Input, Button, Space, Spin, Switch } from 'antd';
import { FullscreenOutlined } from '@ant-design/icons';
import type { SegmentedValue } from 'antd/es/segmented';
import { markKeepGui, takeKeepGui } from '../lib/guiSession';
import { isFlowchart } from '../lib/mermaidFlow';
import { isStateDiagram } from '../lib/mermaidState';
import { isErd } from '../lib/mermaidErd';
import { isClassDiagram } from '../lib/mermaidClass';
import { isSequence } from '../lib/mermaidSequence';
import { isArchitecture } from '../lib/mermaidArchitecture';
import { isMindmap } from '../lib/mermaidMindmap';

const FlowEditor = lazy(() => import('./FlowEditor'));
const StateEditor = lazy(() => import('./StateEditor'));
const ErdEditor = lazy(() => import('./ErdEditor'));
const ClassEditor = lazy(() => import('./ClassEditor'));
const SequenceEditor = lazy(() => import('./SequenceEditor'));
const ArchitectureEditor = lazy(() => import('./ArchitectureEditor'));
const MindmapEditor = lazy(() => import('./MindmapEditor'));

type Mode = 'preview' | 'edit' | 'gui';

type MermaidApi = {
  initialize: (cfg: Record<string, unknown>) => void;
  render: (id: string, text: string) => Promise<{ svg: string }>;
};

let mermaidPromise: Promise<MermaidApi> | null = null;
function getMermaid(): Promise<MermaidApi> {
  if (!mermaidPromise) {
    mermaidPromise = import('mermaid').then((m) => {
      const api = m.default as unknown as MermaidApi;
      // theme:'dark' —— porthole 本身深色底(SPEC §3.1),用 'default' 會在深色頁面裡爆出一塊白圖。
      api.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'dark' });
      return api;
    });
  }
  return mermaidPromise;
}

let seq = 0;

interface Props {
  code: string;
  /** 有給 → 可編輯(顯示 tab、套用寫回);沒給 → 純預覽。 */
  onApply?: (newCode: string) => void;
  /** 跨 remount 保留 GUI 狀態的鍵(由 CM6 widget 傳入 lang:index);Chat 預覽不給。 */
  sessionKey?: string;
  /** draw plugin:初始模式(預設 preview)。 */
  initialMode?: Mode;
}

export default function MermaidBlock({ code, onApply, sessionKey, initialMode }: Props) {
  // remount 後若有 keep 標記 → 直接回 GUI(及全螢幕),支援「Ctrl+S 存檔但留在編輯器」。
  const restored = useMemo(() => takeKeepGui(sessionKey), [sessionKey]);
  const ref = useRef<HTMLDivElement>(null);
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>(restored ? 'gui' : initialMode === 'gui' && !(isFlowchart(code) || isStateDiagram(code) || isErd(code) || isClassDiagram(code) || isSequence(code) || isArchitecture(code) || isMindmap(code)) ? 'preview' : (initialMode ?? 'preview'));
  const [draft, setDraft] = useState(code);
  const [guiFull, setGuiFull] = useState(restored?.full ?? false); // GUI 全螢幕(滿版覆蓋視窗)

  const editable = !!onApply;
  // GUI 可編輯的圖型(互斥,依標頭判定)
  const guiKind: 'flow' | 'state' | 'erd' | 'class' | 'sequence' | 'arch' | 'mindmap' | null = isFlowchart(code)
    ? 'flow'
    : isStateDiagram(code)
      ? 'state'
      : isErd(code)
        ? 'erd'
        : isClassDiagram(code)
          ? 'class'
          : isSequence(code)
            ? 'sequence'
            : isArchitecture(code)
              ? 'arch'
              : isMindmap(code)
                ? 'mindmap'
                : null;

  useEffect(() => {
    if (mode !== 'preview') return;
    let alive = true;
    void getMermaid().then(async (mermaid) => {
      try {
        const { svg } = await mermaid.render(`mmd-${seq++}`, code);
        if (alive && ref.current) {
          ref.current.innerHTML = svg;
          setErr(null);
        }
      } catch (e) {
        if (alive) setErr((e as Error).message ?? String(e));
      }
    });
    return () => {
      alive = false;
    };
  }, [code, mode]);

  const opts = [{ label: '預覽', value: 'preview' }];
  if (editable) opts.push({ label: '編輯', value: 'edit' });
  if (editable && guiKind) opts.push({ label: 'GUI', value: 'gui' });

  const onTab = (v: SegmentedValue) => {
    const m = v as Mode;
    if (m === 'gui' && !guiKind) return; // 無對應 GUI 編輯器時不進 gui(防呆)
    if (m === 'edit') setDraft(code); // 進編輯時以目前內容為準
    if (m !== 'gui') setGuiFull(false); // 離開 GUI → 取消全螢幕
    setMode(m);
  };

  return (
    <div
      style={{
        border: editable ? '1px solid var(--line)' : undefined,
        borderRadius: 8,
        padding: editable ? 8 : 0,
        margin: editable ? '8px 0' : 0,
      }}
    >
      {editable && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          {mode === 'gui' && (
            <span
              style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
              data-loc="mermaid:gui:full"
            >
              <FullscreenOutlined style={{ color: '#888' }} />
              <Switch
                size="small"
                checked={guiFull}
                onChange={setGuiFull}
                title="全螢幕"
                data-loc="mermaid:gui:full:switch"
              />
            </span>
          )}
          <Segmented size="small" value={mode} onChange={onTab} options={opts} data-loc="mermaid:tabs" />
        </div>
      )}

      {mode === 'preview' &&
        (err ? (
          <pre
            style={{
              color: '#cf1322',
              background: 'rgba(226,114,91,0.12)',
              padding: 8,
              borderRadius: 6,
              whiteSpace: 'pre-wrap',
            }}
          >
            mermaid 解析失敗:{err}
            {'\n\n'}
            {code}
          </pre>
        ) : (
          <div ref={ref} style={{ textAlign: 'center' }} />
        ))}

      {mode === 'edit' && (
        <div>
          <Input.TextArea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            autoSize={{ minRows: 4, maxRows: 24 }}
            style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 13 }}
            data-loc="mermaid:edit"
          />
          <Space style={{ marginTop: 8, width: '100%', justifyContent: 'flex-end' }}>
            <Button size="small" onClick={() => setMode('preview')}>
              取消
            </Button>
            <Button
              size="small"
              type="primary"
              onClick={() => {
                onApply?.(draft.trim());
                setMode('preview');
              }}
              data-loc="mermaid:edit:apply"
            >
              套用
            </Button>
          </Space>
        </div>
      )}

      {mode === 'gui' &&
        (() => {
          const EditorComp =
            guiKind === 'state'
              ? StateEditor
              : guiKind === 'erd'
                ? ErdEditor
                : guiKind === 'class'
                  ? ClassEditor
                  : guiKind === 'sequence'
                    ? SequenceEditor
                    : guiKind === 'arch'
                      ? ArchitectureEditor
                      : guiKind === 'mindmap'
                        ? MindmapEditor
                        : FlowEditor;
          const editor = (
            <Suspense fallback={<Spin />}>
              <EditorComp
                code={code}
                fill={guiFull}
                onSave={(c, opts) => {
                  // stay(Ctrl+S / 儲存):寫回但留在 GUI。改寫文件會使本元件 remount,
                  // 故先標記 sessionKey,讓 remount 後的新元件直接回到 GUI(及全螢幕)。
                  if (opts?.stay) {
                    if (sessionKey) markKeepGui(sessionKey, guiFull);
                    onApply?.(c);
                    // 觸發 Explore 存檔到磁碟(不退出編輯)。onApply 已同步更新 draft。
                    if (sessionKey) window.dispatchEvent(new Event('porthole:save-file'));
                  } else {
                    onApply?.(c);
                    setGuiFull(false);
                    setMode('preview');
                  }
                }}
                onClose={() => {
                  setGuiFull(false);
                  setMode('preview');
                }}
              />
            </Suspense>
          );
          if (!guiFull) return editor;
          // portal 到 body:脫離 CM6/編輯器祖先的 containing block,fixed 才能真正
          // 覆蓋整個視窗(否則只蓋中央、右側 Chat 仍露出)。z-index 低於 antd modal(1000)
          // 以便 FlowEditor 的節點/邊編輯視窗仍在最上層。
          return createPortal(
            <div
              style={{
                position: 'fixed',
                inset: 0,
                zIndex: 900,
                background: 'var(--surface)',
                padding: 12,
                display: 'flex',
                flexDirection: 'column',
              }}
              data-loc="mermaid:gui:overlay"
            >
              <div
                style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 4, marginBottom: 8 }}
              >
                <FullscreenOutlined style={{ color: '#888' }} />
                <Switch size="small" checked={guiFull} onChange={setGuiFull} title="退出全螢幕" />
              </div>
              <div style={{ flex: 1, minHeight: 0 }}>{editor}</div>
            </div>,
            document.body,
          );
        })()}
    </div>
  );
}
