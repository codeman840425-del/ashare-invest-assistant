// T-F22 遗留：管理端数据证书列表截图：build:mock 后 vite preview（只连 127.0.0.1），Playwright 1440×900 深色；/api/v1 由页内 MSW 返回示例数据。
// 用法：pnpm run build:mock && node scripts/screenshot-admin-licences.mjs [输出目录]
/* global history, window, PopStateEvent -- 仅在 page.evaluate 的浏览器上下文中使用 */
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const OUT = resolve(process.argv[2] ?? '/workspace/team/reports/T-F22-admin-licences');
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

  // 1. 列表
  await login('admin', '/admin/data-licences');
  await page.waitForSelector('[data-testid=lic-status-novice_user]');
  result.checks.rows = await page.locator('[data-testid=lic-table] tbody tr.ant-table-row').count();
  result.checks.noLicenceText = !/seed-|digest/.test(await page.locator('body').innerText());
  await shot('01-admin-licences.png', '管理端数据证书列表：每位用户一行（含未设置），状态、用量、队列；暂停期间删除证书的行有标记（示例）');

  // 2. 暂停二次确认
  await page.getByTestId('lic-pause-novice_user').click();
  await page.waitForSelector('[data-testid=lic-effect]');
  result.checks.okDisabledInitially = await page.getByTestId('lic-ok').isDisabled();
  await page.getByTestId('lic-reason').fill('示例：调用量异常，排查期间暂停');
  await page.getByTestId('lic-ack').check();
  result.checks.okEnabledAfter = await page.getByTestId('lic-ok').isEnabled();
  await shot('02-pause-confirm.png', '暂停二次确认：说明影响、必填理由（写入审计）、勾选核对用户后才能确认（示例）');

  // 3. 暂停后
  await page.getByTestId('lic-ok').click();
  await page.waitForSelector('[data-testid=lic-done]');
  await page.waitForSelector('[data-testid=lic-resume-novice_user]');
  result.checks.afterPause = await page.getByTestId('lic-status-novice_user').innerText();
  await shot('03-after-pause.png', '暂停成功后列表刷新为服务端状态，行操作变为“恢复”（示例）');

  // 4. 恢复（证书已在暂停期间删除）
  await page.getByTestId('lic-resume-rejected_user').click();
  await page.waitForSelector('[data-testid=lic-effect]');
  await shot('04-resume-deleted.png', '恢复二次确认：该用户暂停期间删除了证书，恢复后为“未设置”（示例）');
  await page.keyboard.press('Escape');

  // 5. 采集状态页跳转并高亮
  await go('/admin/ingest');
  await page.waitForSelector('[data-testid=admin-ingest]');
  await page.locator('[data-testid=admin-ingest] a', { hasText: 'novice_user' }).first().click();
  await page.waitForSelector('tr.row-focus');
  result.checks.focusRow = await page.locator('tr.row-focus').innerText();

} finally {
  await browser.close();
  server.kill();
}
writeFileSync(resolve(OUT, 'result.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
