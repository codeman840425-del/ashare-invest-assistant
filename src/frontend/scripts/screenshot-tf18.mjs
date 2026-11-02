// T-F18 计划草案截图：build:mock 后 vite preview（只连 127.0.0.1），Playwright 1440×900 深色；/api/v1 由页内 MSW 返回示例数据。
// 用法：pnpm run build:mock && node scripts/screenshot-tf18.mjs [输出目录]
/* global history, window, location, PopStateEvent -- 仅在 page.evaluate 的浏览器上下文中使用 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const OUT = resolve(process.argv[2] ?? '/workspace/team/reports/T-F18');
const PORT = 4183;
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
  const PENDING = uid(1012);
  const STALE = uid(7701);
  // 1. 列表（待确认 + 条件已变）
  await login('demo_user', '/plan-drafts?status=pending,stale');
  await page.waitForSelector(`[data-testid="draft-link-${STALE}"]`);
  result.checks.listRows = await page.locator('[data-testid=drafts-table] tbody tr.ant-table-row').count();
  await shot('01-plan-drafts.png', '计划草案列表：?status=pending,stale 多值筛选（示例）');

  // 2. 条件已变：重新生成
  await go(`/plan-drafts/${STALE}`);
  await page.waitForSelector('[data-testid=draft-stale]');
  await shot('02-draft-stale.png', '条件已变的草案：不能确认或修改，可按原候选信号重新生成（示例）');
  await page.getByTestId('regen-btn').click();
  await page.waitForFunction((old) => !location.pathname.endsWith(old), STALE);
  await page.waitForSelector('[data-testid=confirm-form]');
  result.checks.regenerated = new URL(page.url()).pathname;

  // 先确认会让同一候选信号变为已确认，重新生成就会被拒；所以先演示重新生成
  // 3. 详情：判断清单作答、数量超出区间 → 偏离确认
  await go(`/plan-drafts/${PENDING}`);
  await page.waitForSelector('[data-testid=confirm-form]');
  result.checks.blockedInitially = await page.getByTestId('confirm-btn').isDisabled();
  for (const id of ['q_counter', 'q_fit']) await page.getByTestId(`check-${id}`).getByText('是', { exact: true }).click();
  await page.getByTestId('check-q_broker').getByText('不确定', { exact: true }).click();
  await page.getByText('我已了解：草案由规则自动生成').click();
  const max = Number((await page.getByTestId('qty-range').innerText()).split('–')[1]);
  await page.getByTestId('chosen-qty').fill(String(max + 100));
  await page.getByText('我确认按偏离草案区间').click();
  result.checks.enabledAfter = await page.getByTestId('confirm-btn').isEnabled();
  await shot('03-draft-confirm-form.png', '草案详情：区间、估算最大亏损与费用、持仓快照；判断清单（含“不确定”提示）、风险确认、数量偏离确认（示例）');

  // 4. 二次确认 → 跳到计划页（占位）
  await page.getByTestId('confirm-btn').click();
  await page.waitForSelector('[data-testid=review-summary]');
  await shot('04-draft-review.png', '二次确认弹窗：数量、价格与偏离说明（示例）');
  await page.getByTestId('review-ok').click();
  await page.waitForURL(/\/plans\//);
  result.checks.afterConfirm = new URL(page.url()).pathname;

} finally {
  await browser.close();
  server.kill();
}
writeFileSync(resolve(OUT, 'result.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
