// vitest 配置（T-T01）。从仓库根目录：pnpm -C tests test
// 别名 @ → src/frontend/src，前端源码（T-F 系列）落地后测试可直接 import '@/...'。
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

const r = (p: string) => fileURLToPath(new URL(p, import.meta.url));

export default defineConfig({
  resolve: {
    alias: { '@': r('../src/frontend/src') },
  },
  test: {
    root: r('.'),
    include: ['frontend/**/*.{test,spec}.{ts,tsx}'],
    exclude: ['node_modules/**', 'e2e/**'],
    environment: 'jsdom',
    setupFiles: ['frontend/setup.ts'],
    globals: false,
    restoreMocks: true,
    // 前端单测永不联网（麦蕊只由后端 ingest 调用；前端测试连后端也用 mock）
    environmentOptions: { jsdom: { url: 'http://localhost/' } },
  },
});
