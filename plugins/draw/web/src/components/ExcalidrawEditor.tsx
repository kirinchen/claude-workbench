/**
 * ExcalidrawEditor — `.excalidraw` 檔(Google Drawing 式自由白板)的編輯器。
 *  - Excalidraw 是純前端 React 元件;載入該檔 JSON 當 initialData,存檔以 serializeAsJSON
 *    產生標準 `.excalidraw` JSON 寫回。
 *  - 「儲存」鈕 / Ctrl+S → onSave(json)(上層寫檔)。
 *  - 整包較重(~) → 由上層以 lazy + Suspense 載入;本檔直接 import Excalidraw 本體與 CSS,
 *    故整個 Excalidraw bundle 落在這個 lazy chunk 內。
 */
import { useCallback, useEffect, useMemo, useRef } from 'react';
import { Button, Space } from 'antd';
import { Excalidraw, serializeAsJSON } from '@excalidraw/excalidraw';
import '@excalidraw/excalidraw/index.css';
import type { ExcalidrawImperativeAPI } from '@excalidraw/excalidraw/types';

interface Props {
  /** .excalidraw JSON 文字(空字串 = 新檔,開空白白板)。 */
  code: string;
  /** 存檔:opts.stay=true 留在編輯器;否則(block 內)套用後回預覽。 */
  onSave: (code: string, opts?: { stay?: boolean }) => void;
  /** 有給(markdown block 用)→ 顯示「套用」「取消」;沒給(開檔)→ 只有「儲存」。 */
  onClose?: () => void;
  /** 滿版(撐滿父容器)。 */
  fill?: boolean;
}

export default function ExcalidrawEditor({ code, onSave, onClose, fill }: Props) {
  const apiRef = useRef<ExcalidrawImperativeAPI | null>(null);

  // 載入:解析檔內容當 initialData。appState 去掉 collaborators(Map,initialData 不吃)。
  const initialData = useMemo(() => {
    if (!code.trim()) return null;
    try {
      const d = JSON.parse(code) as { elements?: unknown[]; appState?: Record<string, unknown>; files?: unknown };
      const appState = { ...(d.appState ?? {}) };
      delete (appState as { collaborators?: unknown }).collaborators;
      return {
        elements: (d.elements ?? []) as never,
        appState: appState as never,
        files: (d.files ?? {}) as never,
      };
    } catch {
      return null; // 壞 JSON → 開空白
    }
  }, [code]);

  const save = useCallback(
    (stay = false) => {
      const api = apiRef.current;
      if (!api) return;
      const json = serializeAsJSON(api.getSceneElements(), api.getAppState(), api.getFiles(), 'local');
      onSave(json, { stay });
    },
    [onSave],
  );

  // Ctrl+S 存檔(window 層,不限焦點)。
  const saveRef = useRef(save);
  saveRef.current = save;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        e.stopPropagation(); // draw:Excalidraw 自己也綁 Ctrl+S(存成下載檔),捕獲階段先攔下
        saveRef.current(true);
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, []);

  return (
    <div
      style={{ display: 'flex', flexDirection: 'column', height: fill ? '100%' : '72vh' }}
      data-loc="excalidraw:editor"
    >
      <Space style={{ marginBottom: 8, justifyContent: 'flex-end' }}>
        {onClose && (
          <Button size="small" onClick={onClose} data-loc="excalidraw:cancel">
            取消
          </Button>
        )}
        <Button size="small" onClick={() => save(true)} title="儲存(Ctrl+S),留在編輯器" data-loc="excalidraw:save">
          儲存
        </Button>
        {onClose && (
          <Button size="small" type="primary" onClick={() => save(false)} data-loc="excalidraw:apply">
            套用
          </Button>
        )}
      </Space>
      <div style={{ flex: 1, minHeight: 0 }}>
        {/* theme="dark":porthole 整體深色(SPEC §3.1)。白板內容本身存在檔裡、不受主題影響。 */}
        <Excalidraw
          excalidrawAPI={(api) => {
            apiRef.current = api;
          }}
          initialData={initialData}
          theme="dark"
        />
      </div>
    </div>
  );
}
