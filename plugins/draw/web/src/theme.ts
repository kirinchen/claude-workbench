/**
 * theme — 視覺主題的**單一來源**(SPEC §3.1)。
 *
 * 色票跟 Tide 看板(`tide/src/ui/style.css`)對齊,一份 `PALETTE` 餵兩個消費者:
 *   1. `antdTheme` → Antd 6 `ConfigProvider`(按鈕 / 輸入框 / Modal / Tree… 全跟著變)
 *   2. `applyPalette()` → 寫成 `:root` 的 CSS 變數,供 `styles.css` 與自寫 markup 吃
 *
 * 要調色改這一處就好;**不要**在元件裡再硬寫色值(畫面會在下次改色時裂成兩半)。
 * `main.tsx` 在 render 前呼叫 `applyPalette()`(早於任何元件讀 var)。
 */
import { theme, type ThemeConfig } from 'antd';

export const PALETTE = {
  bg: '#0e1a24',
  surface: '#16242f',
  card: '#1d3340',
  line: '#2a4452',
  text: '#d7e3ea',
  muted: '#7d97a5',
  accent: '#3fb6c4',
  /** 狀態色(與 Tide 的留言面板同一組)。 */
  danger: '#e2725b',
  warn: '#e0a458',
  ok: '#3fb950',
  /** 高亮底(選取列 / 命中)。accent 的低透明度,疊在任何 surface 上都不糊。 */
  accentSoft: 'rgba(63, 182, 196, 0.18)',
  accentFaint: 'rgba(63, 182, 196, 0.08)',
  /** 搜尋命中的黃底(深色版:暗黃底 + 亮字)。 */
  hitBg: 'rgba(224, 164, 88, 0.3)',
} as const;

export const FONT_FAMILY = 'system-ui, -apple-system, "Noto Sans TC", "PingFang TC", sans-serif';
export const FONT_MONO = 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';

/**
 * fenced code 的語法高亮色(深色版,one-dark 風、與 accent 同調)。
 * 兩邊共用:CM6 編輯器的 `HighlightStyle`(`lib/cmTheme`)與預覽的 `.tok-*` CSS
 * —— SPEC §4.1 要求編輯器與預覽的高亮一致,所以色值只能有一份。
 */
export const CODE_TOKENS = {
  keyword: '#c678dd',
  atom: '#56b6c2',
  number: '#d19a66',
  string: '#98c379',
  regexp: '#e5c07b',
  variable: '#e06c75',
  type: '#56b6c2',
  class: '#e5c07b',
  property: '#61afef',
  comment: '#7d97a5',
  meta: '#9aaab4',
  invalid: '#e2725b',
} as const;

const kebab = (s: string) => s.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);

/** 把 PALETTE / CODE_TOKENS 寫成 `:root` 的 CSS 變數(`--bg`、`--tok-keyword`…)。 */
export function applyPalette(): void {
  const root = document.documentElement.style;
  for (const [k, v] of Object.entries(PALETTE)) {
    root.setProperty(`--${kebab(k)}`, v);
  }
  for (const [k, v] of Object.entries(CODE_TOKENS)) {
    root.setProperty(`--tok-${k}`, v);
  }
  root.setProperty('--font', FONT_FAMILY);
  root.setProperty('--font-mono', FONT_MONO);
}

export const antdTheme: ThemeConfig = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: PALETTE.accent,
    colorInfo: PALETTE.accent,
    colorLink: PALETTE.accent,
    colorError: PALETTE.danger,
    colorWarning: PALETTE.warn,
    colorSuccess: PALETTE.ok,
    colorBgBase: PALETTE.bg,
    colorTextBase: PALETTE.text,
    colorBgContainer: PALETTE.surface,
    colorBgElevated: PALETTE.card,
    colorBgLayout: PALETTE.bg,
    colorBorder: PALETTE.line,
    colorBorderSecondary: PALETTE.line,
    borderRadius: 10,
    fontSize: 14,
    fontFamily: FONT_FAMILY,
    fontFamilyCode: FONT_MONO,
  },
  components: {
    Layout: {
      headerBg: PALETTE.surface,
      headerHeight: 48,
      headerPadding: '0 16px',
      bodyBg: PALETTE.bg,
      siderBg: PALETTE.surface,
    },
    Tree: {
      nodeSelectedBg: PALETTE.accentSoft,
      nodeHoverBg: PALETTE.accentFaint,
      directoryNodeSelectedBg: PALETTE.accentSoft,
    },
    Button: { defaultBg: PALETTE.surface, defaultBorderColor: PALETTE.line },
    Input: { activeBorderColor: PALETTE.accent, hoverBorderColor: PALETTE.accent },
    Select: { optionSelectedBg: PALETTE.accentSoft },
    Table: { headerBg: PALETTE.surface, rowHoverBg: PALETTE.accentFaint },
    Alert: { withDescriptionPadding: '12px 16px' },
  },
};
