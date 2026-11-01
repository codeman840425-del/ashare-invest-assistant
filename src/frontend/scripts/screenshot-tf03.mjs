// T-F03 截图：build:mock 后 vite preview（只连 127.0.0.1），Playwright 1440×900 深色；/api/v1 由页内 MSW 返回示例数据。
// 用法：pnpm run build:mock && node scripts/screenshot-tf03.mjs [输出目录]
/* global document, window, PopStateEvent -- 仅在 page.waitForFunction 的浏览器上下文中使用 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const OUT = resolve(process.argv[2] ?? '/workspace/team/reports/T-F03');
const PORT = 4177;
const BASE = `http://127.0.0.1:${PORT}`;
mkdirSync(OUT, { recursive: true });
const PW = 'x'.repeat(12);
const CODE = '600000.SH';

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
  const shot = async (name, note) => { await page.mouse.move(1430, 890); await page.waitForTimeout(500); const file = resolve(OUT, name); await page.screenshot({ path: file }); result.shots.push({ file, note }); };
  const login = async (next) => {
    await page.goto(`${BASE}/login?next=${encodeURIComponent(next)}`);
    await page.getByLabel('用户名').fill('demo_user');
    await page.getByLabel('密码').fill(PW);
    await page.locator('button[type=submit]').click();
  };

  await login('/market');
  await page.waitForSelector('[data-testid=sector-panel]');
  await page.waitForFunction(() => document.querySelectorAll('canvas').length > 0, null, { timeout: 15000 }).catch(() => {});
  await shot('01-market.png', '市场概览：指数、涨跌家数/涨跌停、regime、板块资金（示例）');

  // 页内跳转到个股（整页刷新会重置示例会话）
  await page.evaluate((code) => { window.history.pushState({}, '', `/stocks/${code}`); window.dispatchEvent(new PopStateEvent('popstate')); }, CODE);
  await page.waitForSelector('[data-testid=stock-head]');
  await page.waitForSelector('[data-testid=price-chart] canvas', { timeout: 15000 });
  await shot('02-stock-intraday.png', `个股档案 ${CODE}：分时（深色，默认视图）、档案、周期判定、财务`);

  await page.locator('[data-testid=price-chart] .ant-segmented-item', { hasText: '日K' }).click();
  await page.waitForTimeout(800);
  await shot('03-stock-daily.png', '日 K（深色，前复权）');

  await page.getByRole('tab', { name: '财务' }).click();
  await page.waitForSelector('[data-testid=tab-financials]');
  await page.locator('[data-testid=tab-financials]').scrollIntoViewIfNeeded();
  await shot('04-stock-financials.png', '财务 Tab');

  await page.getByRole('tab', { name: '资金流' }).click();
  await page.waitForSelector('[data-testid=tab-fund-flow]');
  await page.locator('[data-testid=tab-fund-flow]').scrollIntoViewIfNeeded();
  await shot('05-stock-fund-flow.png', '资金流 Tab');

  await page.getByRole('tab', { name: '公告' }).click();
  await page.waitForSelector('[data-testid=tab-announcements]');
  await page.waitForSelector('[data-testid=tab-announcements] a.ext-link');
  await page.locator('[data-testid=tab-announcements]').scrollIntoViewIfNeeded();
  result.checks.announcementLinksNoopener = await page.locator('[data-testid=tab-announcements] a[target=_blank]').evaluateAll((as) => as.length > 0 && as.every((a) => (a.getAttribute('rel') ?? '').includes('noopener')));
  await shot('06-stock-announcements.png', '公告 Tab：只给外链，不在页内取外部数据');
} finally {
  await browser.close();
  server.kill();
}
writeFileSync(resolve(OUT, 'result.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
