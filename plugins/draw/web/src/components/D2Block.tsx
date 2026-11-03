/**
 * D2Block — D2 區塊,右上角 tab 切換 預覽 / 編輯 / GUI。
 *  - 渲染走後端:POST /api/d2/render {src} → {svg}(d2 CLI)。
 *  - onApply 有給(Explore)→ 顯示 tab、可寫回;沒給(Chat)→ 純預覽。
 *  - SVG 來自外部子程序輸出,注入前先淨化(去 script / on* / javascript:)。
 *  - GUI 編輯器(D2Editor)→ lazy import,重 / 非預覽必需才載。
 */
import { useEffect, useMemo, useState, lazy, Suspense } from 'react';
import { createPortal } from 'react-dom';
import { Segmented, Input, Button, Space, Spin, Switch } from 'antd';
import { FullscreenOutlined } from '@ant-design/icons';
import type { SegmentedValue } from 'antd/es/segmented';
import { markKeepGui, takeKeepGui } from '../lib/guiSession';

const D2Editor = lazy(() => import('./D2Editor'));

type Mode = 'preview' | 'edit' | 'gui';

interface Props {
  code: string;
  /** 有給 → 可編輯(顯示 tab、套用寫回);沒給 → 純預覽。 */
  onApply?: (newCode: string) => void;
  /** 跨 remount 保留 GUI 狀態的鍵(由 CM6 widget 傳入 lang:index);Chat 預覽不給。 */
  sessionKey?: string;
  /** draw plugin:初始模式(預設 preview)。 */
  initialMode?: Mode;
}

/**
 * 淨化後端回傳的 SVG —— 注入 DOM 前移除可執行面:
 *  - <script>…</script> 整段
 *  - 所有 on* 事件屬性(onclick / onload …)
 *  - href / xlink:href 中的 javascript: 連結
 * 不引第三方;用 DOMParser 走 SVG 命名空間,逐節點清。解析失敗則退回空字串(寧缺勿錯)。
 */
function sanitizeSvg(raw: string): string {
  try {
    const doc = new DOMParser().parseFromString(raw, 'image/svg+xml');
    // parsererror:DOMParser 解析失敗時會塞一個 <parsererror> 進文件
    if (doc.querySelector('parsererror')) return '';
    const root = doc.documentElement;
    if (!root || root.nodeName.toLowerCase() !== 'svg') return '';

    // 去 <script>
    root.querySelectorAll('script').forEach((el) => el.remove());

    // 逐元素清屬性
    const walk = (el: Element): void => {
      for (const attr of Array.from(el.attributes)) {
        const name = attr.name.toLowerCase();
        const value = attr.value;
        // on* 事件屬性
        if (name.startsWith('on')) {
          el.removeAttribute(attr.name);
          continue;
        }
        // 危險協定連結(href / xlink:href / src):擋 javascript:/vbscript:/data:,
        // 但保留 data:image/(SVG 內嵌圖示常用,安全)。
        if (name === 'href' || name === 'xlink:href' || name === 'src') {
          const v = value.trim();
          if (/^(javascript|vbscript):/i.test(v) || (/^data:/i.test(v) && !/^data:image\//i.test(v))) {
            el.removeAttribute(attr.name);
          }
        }
      }
      for (const child of Array.from(el.children)) walk(child);
    };
    walk(root);

    return new XMLSerializer().serializeToString(root);
  } catch {
    return '';
  }
}

export default function D2Block({ code, onApply, sessionKey, initialMode }: Props) {
  // remount 後若有 keep 標記 → 直接回 GUI(及全螢幕),支援「Ctrl+S 存檔但留在編輯器」。
  const restored = useMemo(() => takeKeepGui(sessionKey), [sessionKey]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [svg, setSvg] = useState(''); // 已淨化的 SVG;用 state 而非 ref,避免 loading 卸載 div 時 SVG 落空
  const [mode, setMode] = useState<Mode>(restored ? 'gui' : initialMode ?? 'preview');
  const [draft, setDraft] = useState(code);
  const [guiFull, setGuiFull] = useState(restored?.full ?? false); // GUI 全螢幕(滿版覆蓋視窗)

  const editable = !!onApply;

  // 預覽:呼叫後端渲染 → 淨化 → 注入。AbortController 避免 code 連改時的競態。
  useEffect(() => {
    if (mode !== 'preview') return;
    const ctrl = new AbortController();
    let alive = true;
    setLoading(true);
    setErr(null);
    void (async () => {
      try {
        const res = await fetch('/api/d2/render', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ src: code }),
          signal: ctrl.signal,
        });
        const data: { svg?: string; error?: string } = await res.json().catch(() => ({}));
        if (!alive) return;
        if (!res.ok) {
          setErr(data.error ?? `渲染失敗(${res.status})`);
          setSvg('');
          return;
        }
        const clean = sanitizeSvg(data.svg ?? '');
        setSvg(clean);
        setErr(clean ? null : 'SVG 淨化失敗(空白輸出)');
      } catch (e) {
        if (!alive) return;
        // abort 是正常取消,不當錯誤
        if ((e as Error).name === 'AbortError') return;
        setErr((e as Error).message ?? String(e));
        setSvg('');
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
      ctrl.abort();
    };
  }, [code, mode]);

  const opts = [{ label: '預覽', value: 'preview' }];
  if (editable) {
    opts.push({ label: '編輯', value: 'edit' });
    opts.push({ label: 'GUI', value: 'gui' });
  }

  const onTab = (v: SegmentedValue) => {
    const m = v as Mode;
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
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }} data-loc="d2:gui:full">
              <FullscreenOutlined style={{ color: '#888' }} />
              <Switch
                size="small"
                checked={guiFull}
                onChange={setGuiFull}
                title="全螢幕"
                data-loc="d2:gui:full:switch"
              />
            </span>
          )}
          <Segmented size="small" value={mode} onChange={onTab} options={opts} data-loc="d2:tabs" />
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
            d2 渲染失敗:{err}
            {'\n\n'}
            {code}
          </pre>
        ) : loading ? (
          <div style={{ textAlign: 'center', padding: 24 }}>
            <Spin />
          </div>
        ) : (
          // 已淨化,故用 dangerouslySetInnerHTML;由 state 餵入(非 ref),避免 loading 卸載時落空
          <div style={{ textAlign: 'center' }} dangerouslySetInnerHTML={{ __html: svg }} />
        ))}

      {mode === 'edit' && (
        <div>
          <Input.TextArea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            autoSize={{ minRows: 4, maxRows: 24 }}
            style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 13 }}
            data-loc="d2:edit"
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
              data-loc="d2:edit:apply"
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
              <D2Editor
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
          // portal 到 body:脫離祖先 containing block,fixed 才能真正覆蓋整個視窗。
          // z-index 低於 antd modal(1000),讓編輯器內節點/邊的彈窗仍在最上層。
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
              data-loc="d2:gui:overlay"
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
