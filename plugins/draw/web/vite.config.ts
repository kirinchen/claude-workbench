import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// build 輸出到 plugin 根目錄的 dist/(隨 plugin 發佈,使用者不必 build)。
// dev:vite(5174)把 /api proxy 到 draw server(DRAW_PORT,預設 7391)。
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    host: '127.0.0.1',
    port: 5174,
    proxy: { '/api': { target: `http://127.0.0.1:${process.env.DRAW_PORT || 7391}`, changeOrigin: true } },
  },
  build: { outDir: '../dist', emptyOutDir: true, chunkSizeWarningLimit: 4000 },
});
