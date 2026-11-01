// 依赖合规检查：禁止 ag-grid-enterprise（及任何 @ag-grid-enterprise/* 包）出现在 package.json / pnpm-lock.yaml / node_modules（含 .pnpm 虚拟仓库）。
// 前端统一用 pnpm（CI 要求提交 pnpm-lock.yaml，不接受 package-lock.json）。
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const bad = [];
for (const f of ['package.json', 'pnpm-lock.yaml']) {
  const p = resolve(root, f);
  if (existsSync(p) && /ag-grid-enterprise/.test(readFileSync(p, 'utf8'))) bad.push(f);
}
if (existsSync(resolve(root, 'package-lock.json'))) bad.push('package-lock.json（应改用 pnpm-lock.yaml）');
for (const d of ['node_modules/ag-grid-enterprise', 'node_modules/@ag-grid-enterprise']) if (existsSync(resolve(root, d))) bad.push(d);
const store = resolve(root, 'node_modules/.pnpm');
if (existsSync(store)) for (const e of readdirSync(store)) if (/ag-grid-enterprise/.test(e)) bad.push(`node_modules/.pnpm/${e}`);
if (bad.length) {
  console.error(`✗ 依赖检查失败：${bad.join(', ')}`);
  process.exit(1);
}
const lockPath = resolve(root, 'pnpm-lock.yaml');
if (!existsSync(lockPath)) {
  console.error('✗ 缺少 pnpm-lock.yaml');
  process.exit(1);
}
// pnpm-lock v9：importers['.'] 下 dependencies / devDependencies 的 `name:\n  specifier: ..\n  version: ..`
const lock = readFileSync(lockPath, 'utf8');
const importer = lock.slice(lock.indexOf('\nimporters:'), lock.indexOf('\npackages:'));
const v = (n) => {
  const esc = n.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&');
  const m = importer.match(new RegExp(`\\n {6}'?${esc}'?:\\n {8}specifier: [^\\n]+\\n {8}version: ([^\\s(]+)`));
  return m ? m[1] : '-';
};
console.log('✓ 无 ag-grid-enterprise（pnpm-lock.yaml）');
for (const n of ['react', 'antd', 'ag-grid-community', 'ag-grid-react', 'lightweight-charts', 'react-resizable-panels', 'react-router', '@tanstack/react-query', 'msw', 'vite', 'vitest', 'typescript', 'eslint', 'playwright']) {
  console.log(`  ${n.padEnd(24)} ${v(n)}`);
}
