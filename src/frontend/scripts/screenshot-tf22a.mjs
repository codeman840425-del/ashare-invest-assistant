// T-F22a 截图：build:mock 后 vite preview（只连 127.0.0.1），Playwright 1440×900 深色；/api/v1 由页内 MSW 返回示例数据。
// 用法：pnpm run build:mock && node scripts/screenshot-tf22a.mjs [输出目录]
/* global history, window, PopStateEvent -- 仅在 page.evaluate 的浏览器上下文中使用 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const OUT = resolve(process.argv[2] ?? '/workspace/team/reports/T-F22a');
const PORT = 4177;
const BASE = `http://127.0.0.1:${PORT}`;
mkdirSync(OUT, { recursive: true });
const PW = 'x'.repeat(12);

const server = spawn('pnpm', ['exec', 'vite', 'preview', '--mode', 'mock', '--host', '127.0.0.1', '--port', String(PORT), '--strictPort'], { stdio: ['ignore', 'pipe', 'pipe'] });
await new Promise((ok, fail) => {
  const t = setTimeout(() => fail(new Error('vite preview 启动超时')), 20000);
  const on = (b) => { if (String(b).includes(String(PORT))) { clearTimeout(t); ok(); } };
  server.stdout.on('data', on);
  server.stderr.on('data', on);
});

const result = { viewport: '1440x900', shots: [], consoleErrors: [], pageErrors: [], external: [], checks: {} };
const browser = await chromium.launch();
try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark', locale: 'zh-CN', timezoneId: 'Asia/Shanghai' });
  const page = await ctx.newPage();
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) result.consoleErrors.push(`${page.url()} :: ${m.text()}`); });
  page.on('pageerror', (e) => result.pageErrors.push(`${page.url()} :: ${e.message}`));
  page.on('request', (r) => { if (!r.url().startsWith(BASE) && !r.url().startsWith('data:')) result.external.push(r.url()); });
  // 示例数据存于页内内存：用客户端路由跳转，不整页刷新
  const go = (path) => page.evaluate((p) => { history.pushState({}, '', p); window.dispatchEvent(new PopStateEvent('popstate')); }, path);
  const shot = async (name, note) => { await page.waitForTimeout(400); const file = resolve(OUT, name); await page.screenshot({ path: file }); result.shots.push({ file, note }); };

  await page.goto(`${BASE}/login?next=${encodeURIComponent('/settings/data-licence')}`);
  await page.getByLabel('用户名').fill('demo_user');
  await page.getByLabel('密码').fill(PW);
  await page.locator('button[type=submit]').click();
  await page.waitForSelector('[data-testid=licence-page]');
  result.checks.bannerBefore = await page.locator('[data-testid=licence-banner]').count();

  // M1：提交“验证为无效”的虚构证书 → 不刷新页面，横幅自动出现 invalid
  const fake = 'X-INVALID-' + Array.from({ length: 24 }, () => 'QXZJKVWY'[Math.floor(Math.random() * 8)]).join('');
  await page.getByTestId('licence-input').fill(fake);
  await page.getByTestId('licence-save').click();
  await page.waitForSelector('[data-testid=licence-banner][data-status=invalid]', { timeout: 15000 });
  result.checks.bannerAfter = await page.locator('[data-testid=licence-banner]').getAttribute('data-status');
  await shot('01-licence-banner-auto.png', 'M1：提交后验证失败，横幅自动变为“无效”（未刷新页面）');

  // M2：个股档案缺数原因可见，可用键盘打开数据状态说明
  await go('/stocks/600000.SH');
  await page.waitForSelector('[data-testid=quote-gap-note]');
  await page.waitForSelector('[data-testid=chart-gap-note]');
  const tag = page.getByTestId('data-status-tag').first();
  await tag.focus();
  await page.keyboard.press('Enter');
  await page.waitForSelector('[role=tooltip]');
  result.checks.tooltipText = await page.locator('[role=tooltip]').first().innerText();
  await shot('02-stock-gap-notes.png', 'M2：证书不可用时的行情 / 分时缺数说明；键盘 Enter 打开数据状态说明');

  await go('/market');
  await page.waitForSelector('[data-testid=sector-gap-note]');
  await shot('03-market-gap-notes.png', 'M2：市场页概览与板块资金缺数说明');
} finally {
  await browser.close();
  server.kill();
}
writeFileSync(resolve(OUT, 'result.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
