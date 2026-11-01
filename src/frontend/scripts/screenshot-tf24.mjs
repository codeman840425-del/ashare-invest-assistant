// T-F24 截图：build:mock 后 vite preview（只连 127.0.0.1），Playwright 1440×900 深色；/api/v1 由页内 MSW 返回示例数据（注册模式 invite）。
// 用法：pnpm run build:mock && node scripts/screenshot-tf24.mjs [输出目录]
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const OUT = resolve(process.argv[2] ?? '/workspace/team/reports/T-F24');
const PORT = 4179;
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

  await page.goto(`${BASE}/register`);
  await page.waitForSelector('[data-testid=register-page]');
  const hp = page.locator('[data-testid=reg-website]');
  result.checks.honeypotInViewport = await hp.isVisible() && (await hp.boundingBox())?.x >= 0;
  result.checks.honeypotTabindex = await hp.getAttribute('tabindex');
  result.checks.honeypotAutocomplete = await hp.getAttribute('autocomplete');
  // Tab 键遍历：蜜罐不应获得焦点
  const focused = [];
  await page.locator('[data-testid=reg-username]').focus();
  for (let i = 0; i < 12; i += 1) {
    await page.keyboard.press('Tab');
    focused.push(await page.evaluate(() => globalThis.document.activeElement?.getAttribute('name') ?? globalThis.document.activeElement?.tagName));
  }
  result.checks.honeypotFocusedByTab = focused.includes('website');
  // 无障碍树：表单里的 textbox 不应包含蜜罐
  const aria = await page.locator('form').ariaSnapshot();
  result.checks.a11yTextboxes = (aria.match(/- textbox/g) ?? []).length;
  result.checks.a11yMentionsWebsite = /website/i.test(aria);
  result.checks.ariaSnapshot = aria;
  await page.locator('button[type=submit]').click();
  await page.waitForSelector('text=邀请制下必须填写邀请码');
  await page.mouse.move(1430, 890);
  await page.waitForTimeout(400);
  const f1 = resolve(OUT, '01-register-invite.png');
  await page.screenshot({ path: f1 });
  result.shots.push({ file: f1, note: '邀请制注册页：空提交时邀请码与申请说明都提示必填；蜜罐输入框不可见（示例）' });
} finally {
  await browser.close();
  server.kill();
}
writeFileSync(resolve(OUT, 'result.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
