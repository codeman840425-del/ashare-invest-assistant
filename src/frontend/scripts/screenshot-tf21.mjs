// T-F21 截图：build:mock 后 vite preview（只连 127.0.0.1），Playwright 1440×900 深色；/api/v1 由页内 MSW 返回示例数据。
// 用法：pnpm run build:mock && node scripts/screenshot-tf21.mjs [输出目录]
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const OUT = resolve(process.argv[2] ?? '/workspace/team/reports/T-F21');
const PORT = 4181;
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
  const waitWin = (re) => page.locator('[data-testid=kline-window]', { hasText: re }).first().waitFor({ timeout: 15000 });
  const winText = () => page.locator('[data-testid=kline-window]').first().innerText();
  await page.goto(`${BASE}/stocks/600000.SH`);
  await page.waitForSelector('[data-testid=price-chart]');
  await page.locator('[data-testid=price-chart] .ant-segmented-item', { hasText: '日K' }).click();
  await waitWin(/已载入 250 根/);
  result.checks.stockFirst = await winText();
  await shot('01-stock-kline-window.png', '个股日 K：首屏 250 根，显示载入数与“‹ 更早”（示例）');
  await page.locator('[data-testid=kline-older]').first().click();
  await waitWin(/已载入 500 根/);
  await page.locator('[data-testid=kline-older]').first().click();
  await waitWin(/已到最早/);
  result.checks.stockAll = await winText();
  await shot('02-stock-kline-reached-start.png', '连续向前加载到最早：600 根，提示“已到最早”（示例）');

  await page.goto(`${BASE}/stocks/600000.SH?tab=announcements`);
  await page.waitForSelector('[data-testid^=ann-pager]');
  result.checks.annPager = await page.locator('[data-testid^=ann-pager]').first().innerText();
  await shot('03-announcements-cursor-pager.png', '公告页签：§1.2 游标分页，已显示全部（示例）');

  await page.goto(`${BASE}/terminal`);
  await page.waitForSelector('[data-testid=kline-window]');
  await waitWin(/已载入 120 根/);
  result.checks.terminalFirst = await winText();
  result.checks.watchRows = await page.locator('.ag-row[row-index]').count();
  await shot('04-terminal-kline-window.png', '终端：日 K 首屏 120 根，标题区显示载入数；自选表批量事务更新（示例）');
} finally {
  await browser.close();
  server.kill();
}
writeFileSync(resolve(OUT, 'result.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
