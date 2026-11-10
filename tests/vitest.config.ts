// vitest 配置（T-T01）。从仓库根目录：pnpm -C tests test
// 别名 @ → src/frontend/src，前端源码（T-F 系列）落地后测试可直接 import '@/...'。
// T-T74：在不改前端目录、不改前端 package.json 的前提下，解析
// src/frontend/node_modules（react / antd / react-query 等），以渲染 TodayPage。
// 叠加对照时以 process.cwd() 的上级仓库根为准（例如 /tmp/tt74-run-b91ddaa/tests），
// 这样 @ 指向对照头的 src，而不是本测试分支工作树里的旧前端。
import { existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, type Plugin } from 'vitest/config';

const r = (p: string) => fileURLToPath(new URL(p, import.meta.url));
const configRepo = r('..');
// 叠加对照时 tests/ 常是符号链接，cwd 会回到测试分支。对照头仓库根用 TT74_REPO_ROOT 显式传入。
const repoRoot = process.env.TT74_REPO_ROOT ? path.resolve(process.env.TT74_REPO_ROOT) : configRepo;
const frontendSrc = path.join(repoRoot, 'src/frontend/src');
const frontendNm = path.join(repoRoot, 'src/frontend/node_modules');
const requireFromTests = createRequire(r('./package.json'));
const requireFromFrontend = createRequire(path.join(repoRoot, 'src/frontend/package.json'));

function resolveFrontendDeps(): Plugin {
  return {
    name: 't-t74-resolve-frontend-deps',
    enforce: 'pre',
    resolveId(id) {
      if (!id || id.startsWith('\0') || id.startsWith('.') || id.startsWith('/') || id.startsWith('@/')) {
        return null;
      }
      if (id.startsWith('virtual:') || id.startsWith('vitest')) {
        return null;
      }
      // 测试自己的依赖交给 Vite 默认解析，避免把 ESM 包解析成 CJS。
      try {
        requireFromTests.resolve(id);
        return null;
      } catch {
        /* fall through to frontend node_modules */
      }
      try {
        return requireFromFrontend.resolve(id);
      } catch {
        return null;
      }
    },
  };
}

export default defineConfig({
  plugins: [resolveFrontendDeps()],
  esbuild: { jsx: 'automatic', jsxImportSource: 'react' },
  resolve: {
    alias: { '@': frontendSrc },
  },
  server: {
    fs: { allow: [repoRoot, configRepo, r('.'), frontendNm] },
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
    server: {
      deps: { moduleDirectories: [frontendNm, 'node_modules'] },
    },
  },
});
