// T-F08 截图：build:mock 后 vite preview（只连 127.0.0.1），Playwright 1440×900 深色；/api/v1 由页内 MSW 返回示例数据。
// 用法：pnpm run build:mock && node scripts/screenshot-tf08.mjs [输出目录]
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const OUT = resolve(process.argv[2] ?? '/workspace/team/reports/T-F08');
const PORT = 4178;
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

  await login('/today');
  await page.waitForSelector('[data-testid=today-page]');
  await page.waitForSelector('[data-testid=today-focus] .ant-table-row');
  result.checks.notPlaceholder = (await page.locator('[data-testid=placeholder]').count()) === 0;
  result.checks.cardDisclaimer = await page.locator('[data-testid=today-page] [data-testid=card-disclaimer]').isVisible();
  result.checks.focusRows = await page.locator('[data-testid=today-focus] .ant-table-row').count();
  result.checks.draftLinks = await page.locator('[data-testid=today-drafts] a[href^="/plan-drafts/"]').count();
  result.checks.riskItems = await page.locator('[data-testid=today-risks] li').count();
  await shot('01-today-top.png', '今日关注首屏：交易日/时段/大盘环境、日报与对账状态、重点关注（示例）');

  // 首屏已能放下全部区块；第二张用 2 倍像素裁出下半部分列表，便于核对文字
  const ctx2 = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: 'dark', locale: 'zh-CN', timezoneId: 'Asia/Shanghai' });
  const page2 = await ctx2.newPage();
  page2.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) result.consoleErrors.push(`${page2.url()} :: ${m.text()}`); });
  page2.on('pageerror', (e) => result.pageErrors.push(`${page2.url()} :: ${e.message}`));
  page2.on('response', (r) => { if (r.status() >= 400) result.failedRequests.push(`${r.url()} :: HTTP ${r.status()}`); });
  page2.on('request', (r) => { if (!r.url().startsWith(BASE) && !r.url().startsWith('data:')) result.external.push(r.url()); });
  await page2.goto(`${BASE}/login?next=${encodeURIComponent('/today')}`);
  await page2.getByLabel('用户名').fill('demo_user');
  await page2.getByLabel('密码').fill(PW);
  await page2.locator('button[type=submit]').click();
  await page2.waitForSelector('[data-testid=today-focus] .ant-table-row');
  await page2.mouse.move(1430, 890);
  await page2.waitForTimeout(500);
  const file2 = resolve(OUT, '02-today-lists.png');
  await page2.locator('.today-grid').screenshot({ path: file2 });
  result.shots.push({ file: file2, note: '下半部分（2 倍像素裁图）：待确认计划草案、风险提示、今日解除的不可执行原因、今日失效（示例；空列表显示“无”）' });
} finally {
  await browser.close();
  server.kill();
}
writeFileSync(resolve(OUT, 'result.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
