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
    // 评审 m9：路由懒加载 + 第三方库分块。只有 vendor-antd / vendor-ag-grid 两个第三方块超过 500 kB（库本身体积），
    // 阈值按它们设到 1300 kB；业务代码块 ≤ 500 kB 由 scripts/check-dist.mjs（pnpm check:dist）单独卡住，不靠调高阈值掩盖
    chunkSizeWarningLimit: 1300,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined;
          if (id.includes('ag-grid')) return 'vendor-ag-grid';
          if (id.includes('lightweight-charts')) return 'vendor-charts';
          if (/[\\/](antd|@ant-design|rc-[^\\/]+|@rc-component)[\\/]/.test(id)) return 'vendor-antd';
          if (/[\\/](react|react-dom|react-router|scheduler)[\\/]/.test(id)) return 'vendor-react';
          return undefined;
        },
      },
    },
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
    // 评审 7afbc06 m5：高负载下（CI、全量并发）页面级用例偶发超时；单个用例给足时间，异步查询超时见 src/test/setup.ts
    testTimeout: 20_000,
  },
}));
