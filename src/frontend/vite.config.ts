/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { msw } from 'msw/vite';

// 正式前端包。prototype/ 是独立的 T-F00 原型包：这里显式把它排除在
// 依赖预扫描、文件监听和测试之外（构建只从 index.html → src/main.tsx 出发，不会打包到它）。
export default defineConfig(({ mode }) => ({
  // MSW 只用于开发 / 测试 / 示例构建（--mode mock）；生产构建不注入 Service Worker
  plugins: [react(), ...(mode === 'production' ? [] : [msw()])],
  build: {
    outDir: mode === 'mock' ? 'dist-mock' : 'dist',
    chunkSizeWarningLimit: 4000,
  },
  optimizeDeps: { entries: ['index.html'] },
  server: {
    port: 5173,
    watch: { ignored: ['**/prototype/**', '**/dist/**', '**/dist-mock/**'] },
    // 开发期由 MSW 拦截 /api/v1；若要联调真实后端，设置 VITE_API_PROXY=http://127.0.0.1:8000 并关闭 MSW（见 README）
    proxy: process.env.VITE_API_PROXY ? { '/api': { target: process.env.VITE_API_PROXY, changeOrigin: false } } : undefined,
  },
  preview: { port: 4173 },
  test: {
    globals: true,
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    exclude: ['prototype/**', 'node_modules/**', 'dist/**', 'dist-mock/**'],
    setupFiles: ['src/test/setup.ts'],
    css: false,
  },
}));
