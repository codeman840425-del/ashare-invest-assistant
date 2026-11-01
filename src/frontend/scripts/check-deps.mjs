// 依赖合规检查：禁止 ag-grid-enterprise（及任何 @ag-grid-enterprise/* 包）出现在 package.json / package-lock.json / node_modules。
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const bad = [];
for (const f of ['package.json', 'package-lock.json']) {
  const p = resolve(root, f);
  if (existsSync(p) && /ag-grid-enterprise/.test(readFileSync(p, 'utf8'))) bad.push(f);
}
for (const d of ['node_modules/ag-grid-enterprise', 'node_modules/@ag-grid-enterprise']) if (existsSync(resolve(root, d))) bad.push(d);
if (bad.length) {
  console.error(`✗ 发现 ag-grid-enterprise：${bad.join(', ')}`);
  process.exit(1);
}
const lock = JSON.parse(readFileSync(resolve(root, 'package-lock.json'), 'utf8'));
const v = (n) => lock.packages?.[`node_modules/${n}`]?.version ?? '-';
console.log('✓ 无 ag-grid-enterprise');
for (const n of ['react', 'antd', 'ag-grid-community', 'ag-grid-react', 'lightweight-charts', 'react-resizable-panels', 'react-router', '@tanstack/react-query', 'msw', 'vite', 'vitest', 'typescript', 'eslint', 'playwright']) {
  console.log(`  ${n.padEnd(24)} ${v(n)}`);
}
