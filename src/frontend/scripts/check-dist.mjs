#!/usr/bin/env node
/**
 * 生产包检查（评审 T-F02 P1、m9）：示例题库与 MSW 不得进入生产构建产物。
 *
 *   pnpm build && pnpm check:dist                    # 检查 dist/：命中任何示例标记即失败
 *   pnpm build:mock && node scripts/check-dist.mjs dist-mock --expect-present
 *                                                    # 反向自检：示例构建里必须能找到这些标记，证明检查本身有效
 *
 * 标记来源：src/mocks/session.ts 中带“（示例）”的示例账号文字（显示名、申请说明、驳回理由等，运行时解析，夹具改了这里自动跟上），
 * 以及示例邀请码、MSW 运行时与 Service Worker 文件名。（T-F05：示例题库随风险测评一起删除，标记来源改为 session.ts）
 * 另外检查业务代码块（非 vendor-*）不超过 500 kB。
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(import.meta.url), '../..');
const args = process.argv.slice(2);
const expectPresent = args.includes('--expect-present');
const dir = resolve(root, args.find((a) => !a.startsWith('--')) ?? 'dist');
if (!existsSync(dir)) {
  console.error(`check-dist: 找不到 ${relative(root, dir)}，请先构建`);
  process.exit(2);
}

const session = readFileSync(join(root, 'src/mocks/session.ts'), 'utf8');
const texts = [...new Set([...session.matchAll(/'([^'\n]{4,}（示例）)'/g)].map((m) => m[1]))];
const markers = [...new Set([...texts, 'DEMO-INVITE-OK', 'mockServiceWorker', 'virtual:msw', 'setupWorker'])];
if (texts.length < 5) {
  console.error('check-dist: 没能从 src/mocks/session.ts 解析出示例账号标记，脚本需要更新');
  process.exit(2);
}

const files = [];
const walk = (d) => {
  for (const n of readdirSync(d)) {
    const p = join(d, n);
    if (statSync(p).isDirectory()) walk(p);
    else files.push(p);
  }
};
walk(dir);

const hits = new Map();
for (const f of files) {
  if (/mockServiceWorker\.js$/.test(f)) hits.set('mockServiceWorker.js（文件）', relative(root, f));
  if (!/\.(js|mjs|html|css|json|map|txt)$/.test(f)) continue;
  const body = readFileSync(f, 'utf8');
  for (const m of markers) if (body.includes(m) && !hits.has(m)) hits.set(m, relative(root, f));
}

const BUDGET = 500 * 1024;
const big = files.filter((f) => /\.js$/.test(f) && !/[\\/]vendor-[^\\/]+\.js$/.test(f) && statSync(f).size > BUDGET);

if (expectPresent) {
  const missing = ['DEMO-INVITE-OK', 'mockServiceWorker', texts[0]].filter((m) => !hits.has(m));
  if (missing.length) {
    console.error(`check-dist（反向自检）: ${relative(root, dir)} 里缺少标记：${missing.join('、')}`);
    process.exit(1);
  }
  console.log(`check-dist（反向自检）: ${relative(root, dir)} 中找到示例标记 ${hits.size} 个，检查有效`);
  process.exit(0);
}

let failed = false;
if (hits.size) {
  failed = true;
  console.error(`check-dist: 生产包中发现示例 / MSW 内容（${hits.size} 项）：`);
  for (const [m, f] of hits) console.error(`  ${m}  ←  ${f}`);
}
if (big.length) {
  failed = true;
  for (const f of big) console.error(`check-dist: 业务代码块超过 500 kB：${relative(root, f)}（${Math.round(statSync(f).size / 1024)} kB）`);
}
if (failed) process.exit(1);
console.log(`check-dist: ${relative(root, dir)} 共 ${files.length} 个文件，${markers.length} 个示例标记 0 命中；业务代码块均 ≤ 500 kB`);
