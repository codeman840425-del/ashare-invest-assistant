// T-A09 前端同步（契约 v0.2.8）截图：build:mock 后 vite preview（只连 127.0.0.1），Playwright 1440×900 深色；/api/v1 由页内 MSW 返回示例数据。
// 用法：pnpm run build:mock && node scripts/screenshot-t-a09.mjs [输出目录]
/* global history, window, PopStateEvent -- 仅在 page.evaluate 的浏览器上下文中使用 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const OUT = resolve(process.argv[2] ?? '/workspace/team/reports/T-A09');
const PORT = 4184;
const BASE = `http://127.0.0.1:${PORT}`;
const PW = 'x'.repeat(12);
mkdirSync(OUT, { recursive: true });

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
  const shot = async (name, note) => {
    await page.mouse.move(1430, 890);
    await page.waitForTimeout(500);
    const file = resolve(OUT, name);
    await page.screenshot({ path: file });
    result.shots.push({ file, note });
  };
  const login = async (user, next) => {
    await page.goto(`${BASE}/login?next=${encodeURIComponent(next)}`);
    await page.getByLabel('用户名').fill(user);
    await page.getByLabel('密码').fill(PW);
    await page.locator('button[type=submit]').click();
  };

  // 1. ETF 个股页
  await login('demo_user', '/stocks/510300.SH');
  await page.waitForSelector('[data-testid=security-type-tag]');
  await page.waitForSelector('[data-testid=fin-empty]');
  result.checks.etfHead = await page.getByTestId('stock-head').innerText();
  await shot('01-etf-stock-page.png', 'ETF 个股页：类型标签、价格 3 位小数、行业/概念/份额“不适用”、财务页签“不适用”（示例）');

  // 2. 持仓含可转债
  await go('/portfolio');
  await page.waitForSelector('[data-testid="cb-tag-113050.SH"]');
  result.checks.cbRow = await page.getByTestId('cb-tag-113050.SH').locator('xpath=ancestor::tr').innerText();
  await shot('02-portfolio-convertible.png', '持仓：可转债显示“可转债·无行情”，现价/市值/盈亏“—”，仓位与总资产标“估算”（示例）');

  // 3. 证书被管理员暂停：测试按钮禁用
  await login('paused_user', '/settings/data-licence');
  await page.waitForSelector('[data-testid=licence-paused]');
  result.checks.testDisabled = await page.getByTestId('licence-test').isDisabled();
  await shot('03-licence-paused.png', '数据证书：管理员暂停期间“测试证书”禁用并说明（示例）');

  // 4. 管理端采集状态
  await login('admin', '/admin/ingest');
  await page.waitForSelector('[data-testid=ingest-licences] tbody tr');
  result.checks.ingestRows = await page.locator('[data-testid=ingest-licences] tbody tr').count();
  await shot('04-admin-ingest.png', '管理端采集状态：顶部合计 + 按证书一行，异常状态在前（示例）');
} finally {
  await browser.close();
  server.kill();
}
writeFileSync(resolve(OUT, 'result.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
