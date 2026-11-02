// T-F23 研究候选（契约 v0.2.9 §7.7A）截图：build:mock 后 vite preview（只连 127.0.0.1），Playwright 1440×900 深色；/api/v1 由页内 MSW 返回示例数据。
// 用法：pnpm run build:mock && node scripts/screenshot-t-f23.mjs [输出目录]
/* global history, window, PopStateEvent -- 仅在 page.evaluate 的浏览器上下文中使用 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const OUT = resolve(process.argv[2] ?? '/workspace/team/reports/T-F23');
const PORT = 4187;
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

  // 1. 列表：勾选“全部状态”（status=all，含已放弃）
  await login('demo_user', '/candidates');
  await page.waitForSelector('[data-testid=candidates-table] a');
  await page.getByTestId('filter-all').click();
  await page.waitForSelector('text=已放弃');
  result.checks.list = await page.getByTestId('candidates-table').innerText();
  await shot('01-candidates-list.png', '研究候选列表：全部状态（status=all，含已放弃），来源与版本（示例）');

  // 2. 详情：当前版本、版本历史
  const c1 = (await api('/candidates?security_code=600000.SH')).items[0];
  await go(`/candidates/${c1.id}`);
  await page.waitForSelector('[data-testid=cand-current-version]');
  await page.waitForSelector('[data-testid=cand-history-1]');
  result.checks.detail = await page.getByTestId('cand-current').innerText();
  await shot('02-candidate-detail.png', '研究候选详情：当前版本（研究要点、成立条件为假设、系统理由与反证、适配提示、本版决定）与版本历史（示例）');

  // 3. 个股页入口：新建研究候选
  await go('/stocks/000002.SZ');
  await page.getByTestId('add-to-research-btn').click();
  await page.waitForSelector('[data-testid=cand-create-modal]');
  await page.getByTestId('cand-thesis').fill('示例：观察去库存进度（示例）');
  await page.getByTestId('cond-add').click();
  await page.getByTestId('cond-text-0').fill('两个季度存货周转改善（示例）');
  await page.getByTestId('cond-by-0').fill('2027-01-31');
  await shot('03-create-from-stock.png', '个股页“加入研究候选”：来源=个股页，填写研究要点与成立条件（示例）');
  await page.getByTestId('cand-create-ok').click();
  await page.waitForSelector('[data-testid=candidate-detail] [data-testid=cand-current-version]');
  result.checks.createdUrl = page.url().replace(BASE, '');

  // 4. 新建版本：放弃须填理由
  await page.getByTestId('cand-new-version-btn').click();
  await page.getByRole('radio', { name: '放弃' }).check();
  await page.getByTestId('ver-reason').fill('示例：假设不成立（示例）');
  await page.waitForSelector('[data-testid=ver-drop-warn]');
  await shot('04-new-version-drop.png', '新建版本：选择“放弃”须填理由，并提示放弃后不能再修改（示例）');
} finally {
  await browser.close();
  server.kill();
}
writeFileSync(resolve(OUT, 'result.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
