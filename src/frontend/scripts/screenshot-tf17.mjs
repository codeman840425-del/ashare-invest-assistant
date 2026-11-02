// T-F17 候选信号截图：build:mock 后 vite preview（只连 127.0.0.1），Playwright 1440×900 深色；/api/v1 由页内 MSW 返回示例数据。
// 用法：pnpm run build:mock && node scripts/screenshot-tf17.mjs [输出目录]
/* global history, window, document, PopStateEvent -- 仅在 page.evaluate 的浏览器上下文中使用 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const OUT = resolve(process.argv[2] ?? '/workspace/team/reports/T-F17');
const PORT = 4182;
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

  // 与 mocks/fixtures.ts 的 uid(n) 相同规则
  const uid = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
  const BUY = uid(1000);
  const REDUCE = uid(1003);
  // 1. 列表
  await login('demo_user', '/candidate-signals');
  await page.waitForSelector(`[data-testid="conflict-${BUY}"]`);
  result.checks.listRows = await page.locator('[data-testid=signals-table] tbody tr.ant-table-row').count();
  await shot('01-signal-list.png', '候选信号列表：方向冲突标记、观察中徽标、状态与筛选（示例）');

  // 2. 详情：冲突并列、原因与自动重评状态、跟踪统计 n
  await go(`/candidate-signals/${BUY}`);
  await page.waitForSelector('[data-testid=signal-conflicts]');
  await page.waitForSelector('[data-testid=track-5]');
  await page.waitForSelector('[data-testid=signal-events] .ant-timeline-item');
  result.checks.reevalTexts = await page.getByTestId('reeval').allInnerTexts();
  await shot('02-signal-detail.png', '候选信号详情：冲突并列、不可执行原因 + 解除条件 + 自动重评状态、跟踪统计带 n 与样本少（示例）');

  // 3. 手动解除后
  await go(`/candidate-signals/${REDUCE}`);
  await page.getByTestId(`release-${uid(1004)}`).click();
  await page.getByTestId('release-note').fill('已核对（示例）');
  await page.getByTestId('release-ok').click();
  await page.waitForFunction(() => document.querySelector('[data-testid=signal-state]')?.textContent?.includes('原因已解除'));
  await shot('03-signal-released.png', '手动解除唯一生效原因后：信号变为“原因已解除”，原因显示“你手动解除”与备注（示例）');

  // 4. 今日已解除
  await go('/candidate-signals?tab=released');
  await page.waitForSelector('[data-testid=released-table] tbody tr.ant-table-row');
  result.checks.releasedRows = await page.locator('[data-testid=released-table] tbody tr.ant-table-row').count();
  await shot('04-released-today.png', '今日已解除页签：released_since={trade_date}T00:00:00+08:00（示例）');
} finally {
  await browser.close();
  server.kill();
}
writeFileSync(resolve(OUT, 'result.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
