// T-F22 截图：build:mock 后 vite preview（只连 127.0.0.1），Playwright 1440×900 深色；/api/v1 由页内 MSW 返回示例数据。
// 用法：pnpm run build:mock && node scripts/screenshot-tf22.mjs [输出目录]
/* global document -- 仅在 page.waitForFunction 的浏览器上下文中使用 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const OUT = resolve(process.argv[2] ?? '/workspace/team/reports/T-F22');
const PORT = 4176;
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
  const shot = async (name, note) => { await page.mouse.move(1430, 890); await page.waitForTimeout(300); const file = resolve(OUT, name); await page.screenshot({ path: file }); result.shots.push({ file, note }); };

  // 新用户（未设置证书）：横幅 + 设置页
  await page.goto(`${BASE}/login?next=${encodeURIComponent('/settings/data-licence')}`);
  await page.getByLabel('用户名').fill('new_user');
  await page.getByLabel('密码').fill(PW);
  await page.locator('button[type=submit]').click();
  await page.waitForSelector('[data-testid=licence-page]');
  result.checks.bannerNotSet = await page.locator('[data-testid=licence-banner]').getAttribute('data-status');
  await shot('01-licence-not-set.png', '设置 → 数据证书：未设置（全站横幅）');

  // 提交运行时生成的虚构证书 → 输入清空、验证中 → 可用
  const fake = Array.from({ length: 28 }, () => 'QXZJKVWY'[Math.floor(Math.random() * 8)]).join('');
  await page.getByTestId('licence-input').fill(fake);
  await page.getByTestId('licence-save').click();
  await page.waitForSelector('[data-testid=licence-msg]');
  result.checks.inputClearedAfterSubmit = (await page.getByTestId('licence-input').inputValue()) === '';
  await page.waitForFunction(() => document.querySelector('[data-testid=licence-status]')?.textContent?.includes('可用'), null, { timeout: 15000 });
  const html = await page.content();
  result.checks.licenceAbsentFromDom = ![...Array(fake.length - 3).keys()].some((i) => html.includes(fake.slice(i, i + 4)));
  await shot('02-licence-active.png', '提交后：输入已清空，状态为可用');

  // 策略库：S-03 高风险模板开关旁固定说明；启用后不弹窗
  await page.getByRole('link', { name: '策略库' }).click();
  await page.waitForSelector('[data-testid=enable-st_strong_momo]');
  await page.getByTestId('enable-st_strong_momo').getByRole('switch').click();
  await page.waitForFunction(() => document.querySelector('[data-testid=enable-st_strong_momo] [role=switch]')?.getAttribute('aria-checked') === 'true');
  result.checks.noDialog = (await page.locator('[role=dialog]').count()) === 0;
  await shot('03-strategies-high-risk.png', '策略库：S-03 启用，开关旁固定风险说明');
} finally {
  await browser.close();
  server.kill();
}
writeFileSync(resolve(OUT, 'result.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
