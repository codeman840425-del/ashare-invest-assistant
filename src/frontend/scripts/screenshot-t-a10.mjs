// T-A10 前端同步（契约 v0.2.9）截图：build:mock 后 vite preview（只连 127.0.0.1），Playwright 1440×900 深色；/api/v1 由页内 MSW 返回示例数据。
// 用法：pnpm run build:mock && node scripts/screenshot-t-a10.mjs [输出目录]
/* global history, window, PopStateEvent -- 仅在 page.evaluate 的浏览器上下文中使用 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const OUT = resolve(process.argv[2] ?? '/workspace/team/reports/T-A10-frontend');
const PORT = 4185;
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

  const api = (p) => page.evaluate((u) => fetch(`/api/v1${u}`).then((r) => r.json()), p);

  // 1. 持仓：无行情行看 estimated 字段
  await login('demo_user', '/portfolio');
  await page.waitForSelector('[data-testid="cb-tag-113050.SH"]');
  result.checks.cbRow = await page.getByTestId('cb-tag-113050.SH').locator('xpath=ancestor::tr').innerText();
  await shot('01-portfolio-estimated.png', '持仓：estimated=true 的行现价/市值/盈亏“—”，仓位标“估算”；顶部数据状态 partial（示例）');

  // 2. 候选信号详情：原因带证券、含已解除（status=all），状态历史分页
  const rel = (await api('/non-executable-reasons?status=released&limit=50')).items[0];
  result.checks.releasedReason = { code: rel.code, security_code: rel.security_code, name: rel.name };
  await go(`/candidate-signals/${rel.signal_id}`);
  await page.waitForSelector('[data-testid=signal-events] li, [data-testid=signal-events] tr, [data-testid=signal-events-pager-end]');
  await page.getByTestId('signal-reasons').scrollIntoViewIfNeeded();
  result.checks.events = await page.getByTestId('signal-events').innerText();
  await shot('02-signal-detail.png', '候选信号详情：自动重评状态含已解除原因（status=all），状态历史按页加载、cause 文案（示例）');

  // 3. 建议详情：策略卡片里的已解除原因
  const sig = await api(`/candidate-signals/${rel.signal_id}`);
  if (sig.suggestion_id) {
    await go(`/suggestions/${sig.suggestion_id}`);
    await page.waitForSelector('[data-testid=strategy-card]');
    await page.getByTestId('strategy-card').scrollIntoViewIfNeeded();
    result.checks.strategyCard = await page.getByTestId('strategy-card').innerText();
    await shot('03-suggestion-released.png', '建议详情策略卡片：生效原因在前，已解除原因标“已解除”（示例）');
  }

  // 4. 放弃草案：不再有备注框，请求体 {}
  const draft = (await api('/plan-drafts?status=pending')).items[0];
  await go(`/plan-drafts/${draft.id}`);
  await page.getByTestId('discard-btn').click();
  await page.waitForSelector('[data-testid=discard-hint]');
  result.checks.discardNote = await page.locator('[data-testid=discard-note]').count();
  await shot('04-discard-no-note.png', '放弃计划草案：只有说明与确认按钮，没有备注框（示例）');
} finally {
  await browser.close();
  server.kill();
}
writeFileSync(resolve(OUT, 'result.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
