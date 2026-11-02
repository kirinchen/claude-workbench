/**
 * ExcalidrawBlock — markdown 內 ```excalidraw 區塊(內嵌自由白板)。
 *  - 預覽:把場景 exportToSvg 成靜態 SVG 顯示(純讀,不載編輯器)。
 *  - 編輯:原始 .excalidraw JSON 文字(textarea)。
 *  - GUI:Excalidraw 白板編輯器(ExcalidrawEditor),套用寫回 fence。
 *  與 MermaidBlock / D2Block 同模式(tab 切換 + 全螢幕 portal + 跨 remount 保留 GUI)。
 */
import { useEffect, useMemo, useState, lazy, Suspense } from 'react';
import { createPortal } from 'react-dom';
import { Segmented, Input, Button, Space, Spin, Switch } from 'antd';
import { FullscreenOutlined } from '@ant-design/icons';
import type { SegmentedValue } from 'antd/es/segmented';
import { markKeepGui, takeKeepGui } from '../lib/guiSession';

const ExcalidrawEditor = lazy(() => import('./ExcalidrawEditor'));

type Mode = 'preview' | 'edit' | 'gui';

interface Props {
  code: string;
  onApply?: (newCode: string) => void;
  sessionKey?: string;
  /** draw plugin:初始模式(預設 preview)。 */
  initialMode?: Mode;
}

/** 解析 .excalidraw JSON → 場景;壞 JSON 回 null。 */
function parseScene(
  code: string,
): { elements: readonly unknown[]; appState: Record<string, unknown>; files: unknown } | null {
  if (!code.trim()) return { elements: [], appState: {}, files: {} };
  try {
    const d = JSON.parse(code) as { elements?: unknown[]; appState?: Record<string, unknown>; files?: unknown };
    return { elements: d.elements ?? [], appState: d.appState ?? {}, files: d.files ?? {} };
  } catch {
    return null;
  }
}

export default function ExcalidrawBlock({ code, onApply, sessionKey, initialMode }: Props) {
  const restored = useMemo(() => takeKeepGui(sessionKey), [sessionKey]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [svg, setSvg] = useState('');
  const [mode, setMode] = useState<Mode>(restored ? 'gui' : initialMode ?? 'preview');
  const [draft, setDraft] = useState(code);
  const [guiFull, setGuiFull] = useState(restored?.full ?? false);

  const editable = !!onApply;

  // 預覽:把場景 exportToSvg 成 SVG。
  useEffect(() => {
    if (mode !== 'preview') return;
    let alive = true;
    const scene = parseScene(code);
    if (!scene) {
      setErr('無效的 excalidraw JSON');
      setSvg('');
      return;
    }
    if (!scene.elements.length) {
      setErr(null);
      setSvg('');
      return; // 空白白板 → 不畫 SVG
    }
    setLoading(true);
    setErr(null);
    void import('@excalidraw/excalidraw')
      .then(({ exportToSvg }) =>
        exportToSvg({
          elements: scene.elements as never,
          appState: { ...scene.appState, exportBackground: true, exportWithDarkMode: false } as never,
          files: (scene.files ?? {}) as never,
        }),
      )
      .then((el) => {
        if (!alive) return;
        // 讓預覽 SVG 隨容器縮放:保留 viewBox 比例,寬度不超過容器(避免場景原始寬度
        // 太大 → 長橫向 scroll),也不放大超過原尺寸。
        el.setAttribute('style', `${el.getAttribute('style') ?? ''};max-width:100%;height:auto;`);
        setSvg(el.outerHTML);
      })
      .catch((e) => {
        if (alive) setErr(String((e as Error).message ?? e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [code, mode]);

  const opts = [{ label: '預覽', value: 'preview' }];
  if (editable) {
    opts.push({ label: '編輯', value: 'edit' });
    opts.push({ label: 'GUI', value: 'gui' });
  }

  const onTab = (v: SegmentedValue) => {
    const m = v as Mode;
    if (m === 'edit') setDraft(code);
    if (m !== 'gui') setGuiFull(false);
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
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }} data-loc="exc:gui:full">
              <FullscreenOutlined style={{ color: '#888' }} />
              <Switch size="small" checked={guiFull} onChange={setGuiFull} title="全螢幕" />
            </span>
          )}
          <Segmented size="small" value={mode} onChange={onTab} options={opts} data-loc="exc:tabs" />
        </div>
      )}

      {mode === 'preview' &&
        (err ? (
          <pre style={{ color: 'var(--danger)', background: 'rgba(226,114,91,0.12)', padding: 8, borderRadius: 6, whiteSpace: 'pre-wrap' }}>
            excalidraw 預覽失敗:{err}
          </pre>
        ) : loading ? (
          <div style={{ textAlign: 'center', padding: 24 }}>
            <Spin />
          </div>
        ) : svg ? (
          <div style={{ textAlign: 'center', overflow: 'auto' }} dangerouslySetInnerHTML={{ __html: svg }} />
        ) : (
          <div style={{ textAlign: 'center', color: 'var(--muted)', padding: 24 }}>(空白白板)</div>
        ))}

      {mode === 'edit' && (
        <div>
          <Input.TextArea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            autoSize={{ minRows: 4, maxRows: 24 }}
            style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12 }}
            data-loc="exc:edit"
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
              data-loc="exc:edit:apply"
            >
              套用
            </Button>
          </Space>
        </div>
      )}

      {mode === 'gui' &&
        (() => {
          const editor = (
            <Suspense fallback={<Spin />}>
              <ExcalidrawEditor
                code={code}
                fill={guiFull}
                onSave={(c, optsArg) => {
                  if (optsArg?.stay) {
                    if (sessionKey) markKeepGui(sessionKey, guiFull);
                    onApply?.(c);
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
              data-loc="exc:gui:overlay"
            >
              <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 4, marginBottom: 8 }}>
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
