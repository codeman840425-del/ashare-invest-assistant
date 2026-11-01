// T-F13 截图：build:mock 后 vite preview（只连 127.0.0.1），Playwright 1440×900 深色；/api/v1 由页内 MSW 返回示例数据。
// 用法：pnpm run build:mock && node scripts/screenshot-tf13.mjs [输出目录]
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const OUT = resolve(process.argv[2] ?? '/workspace/team/reports/T-F13');
const PORT = 4180;
const BASE = `http://127.0.0.1:${PORT}`;
mkdirSync(OUT, { recursive: true });

const server = spawn('pnpm', ['exec', 'vite', 'preview', '--mode', 'mock', '--host', '127.0.0.1', '--port', String(PORT), '--strictPort'], { stdio: ['ignore', 'pipe', 'pipe'] });
await new Promise((ok, fail) => {
  const t = setTimeout(() => fail(new Error('vite preview 启动超时')), 20000);
  const on = (b) => { if (String(b).includes(String(PORT))) { clearTimeout(t); ok(); } };
  server.stdout.on('data', on);
  server.stderr.on('data', on);
});

const result = { viewport: '1440x900', shots: [], consoleErrors: [], pageErrors: [], failedRequests: [], external: [], checks: {} };
const browser = await chromium.launch();
try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark', locale: 'zh-CN', timezoneId: 'Asia/Shanghai' });
  const page = await ctx.newPage();
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) result.consoleErrors.push(`${page.url()} :: ${m.text()}`); });
  page.on('pageerror', (e) => result.pageErrors.push(`${page.url()} :: ${e.message}`));
  page.on('response', (r) => { if (r.status() >= 400) result.failedRequests.push(`${r.url()} :: HTTP ${r.status()}`); });
  page.on('request', (r) => { if (!r.url().startsWith(BASE) && !r.url().startsWith('data:')) result.external.push(r.url()); });

  const shot = async (name, note) => {
    await page.mouse.move(1430, 890);
    await page.waitForTimeout(400);
    const f = resolve(OUT, name);
    await page.screenshot({ path: f });
    result.shots.push({ file: f, note });
  };
  await page.goto(`${BASE}/daily-reports`);
  await page.waitForSelector('[data-testid=daily-report]');
  await page.waitForSelector('[data-testid=report-account]');
  result.checks.date = new URL(page.url()).pathname;
  result.checks.cards = await page.locator('.stock-card').count();
  result.checks.disclaimer = await page.locator('[data-testid=card-disclaimer]').count();
  result.checks.pendingLinks = await page.locator('[data-testid=report-pending] a').evaluateAll((as) => as.map((a) => a.getAttribute('href')));
  await shot('01-report-latest.png', '最新一期：账户概览（对账差异与重要差异、查看对账）、市场、待处理去向、数据缺口、免责提示（示例）');
  await page.goto(`${BASE}/daily-reports/2026-10-30?filter=changed`);
  await page.waitForSelector('.stock-card');
  result.checks.changedCards = await page.locator('.stock-card').count();
  await page.locator('.stock-card').first().focus();
  await shot('02-report-filter-changed.png', '?filter=changed：只显示新增 / 有变化；卡片键盘聚焦描边（示例）');
  await page.getByRole('button', { name: '上一期' }).click();
  await page.waitForSelector('[data-testid=report-no-account]');
  result.checks.prevDate = new URL(page.url()).pathname;
  await shot('03-report-prev-not-imported.png', '上一期：未导入交割单、市场宽度缺失、已移出证券不可点击（示例）');
} finally {
  await browser.close();
  server.kill();
}
writeFileSync(resolve(OUT, 'result.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
