import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * file:// 下浏览器会拦截 <script type="module" crossorigin>（CORS 限制）。
 * 产物打成单个 IIFE 包，并把入口脚本改为普通 defer 脚本，保证 dist/index.html 双击即可打开。
 */
function classicScriptForFileProtocol(): Plugin {
  return {
    name: 'classic-script-for-file-protocol',
    apply: 'build',
    enforce: 'post',
    transformIndexHtml(html) {
      return html
        .replace(/<script type="module" crossorigin/g, '<script defer')
        .replace(/<link rel="stylesheet" crossorigin/g, '<link rel="stylesheet"')
        .replace(/<link rel="modulepreload"[^>]*>/g, '');
    },
  };
}

// base 设为 './'，配合 hash 路由，dist/index.html 可直接以 file:// 双击打开
export default defineConfig({
  base: './',
  plugins: [react(), classicScriptForFileProtocol()],
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 2500,
    modulePreload: false,
    rollupOptions: {
      output: { format: 'iife' },
    },
  },
});
