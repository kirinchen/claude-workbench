/** draw server API(token 由 server 注入 index.html 的 window.__DRAW__)。 */
import type { Kind } from './charts';

declare global {
  interface Window {
    __DRAW__?: { token: string; version: string };
  }
}

export const BOOT = window.__DRAW__ ?? { token: '', version: 'dev' };

// porthole 搬來的元件(D2Block)直接 fetch('/api/d2/render') —— 在這裡統一補上 token。
const rawFetch = window.fetch.bind(window);
window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
  if (url.startsWith('/api/') || url.startsWith(`${location.origin}/api/`)) {
    const headers = new Headers(init?.headers);
    headers.set('X-Draw-Token', BOOT.token);
    return rawFetch(input, { ...init, headers });
  }
  return rawFetch(input, init);
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, (data as { error?: string }).error ?? `HTTP ${res.status}`);
  return data as T;
}

export interface Info {
  version: string;
  d2: boolean;
  home: string;
}
export interface MemDrawing {
  id: string;
  kind: Kind;
  name: string;
  code: string;
  updatedAt: string;
}
export interface Block {
  index: number;
  kind: Kind;
  code: string;
}
export interface FileDoc {
  path: string;
  format: 'md' | 'native';
  stamp: string;
  blocks: Block[];
  index?: number;
  appended?: boolean;
}

export const api = {
  info: () => call<Info>('GET', '/api/info'),
  memList: () => call<{ drawings: Omit<MemDrawing, 'code'>[] }>('GET', '/api/memory'),
  memCreate: (kind: Kind, code: string, name?: string) => call<MemDrawing>('POST', '/api/memory', { kind, code, name }),
  memGet: (id: string) => call<MemDrawing>('GET', `/api/memory/${id}`),
  memPut: (id: string, code: string) => call<MemDrawing>('PUT', `/api/memory/${id}`, { code }),
  fileGet: (cwd: string, path: string) =>
    call<FileDoc>('GET', `/api/file?${new URLSearchParams({ cwd, path })}`),
  fileCreate: (cwd: string, path: string, kind: Kind, code: string, format: 'md' | 'native') =>
    call<FileDoc>('POST', '/api/file', { cwd, path, kind, code, format }),
  filePut: (cwd: string, path: string, index: number, code: string, base: string, force = false) =>
    call<FileDoc>('PUT', '/api/file', { cwd, path, index, code, base, force }),
};
