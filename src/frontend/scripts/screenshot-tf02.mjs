// T-F02 / T-F02a / T-F04 验收截图：build:mock 后用 vite preview 起本地服务，Playwright 1440×900 深色。
// 只访问 127.0.0.1；/api/v1 由页面内 MSW Service Worker 返回示例数据（整页刷新会重置示例会话，所以登录后只做页内跳转）。
// 用法：pnpm run build:mock && node scripts/screenshot-tf02.mjs [输出目录]
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const OUT = resolve(process.argv[2] ?? '/workspace/team/reports/T-F02');
const PORT = 4174;
const BASE = `http://127.0.0.1:${PORT}`;
mkdirSync(OUT, { recursive: true });
// 示例口令由代码生成（mock 只校验长度），仓库里不出现字面口令
const PW = 'x'.repeat(12);

const server = spawn('pnpm', ['exec', 'vite', 'preview', '--mode', 'mock', '--host', '127.0.0.1', '--port', String(PORT), '--strictPort'], { stdio: ['ignore', 'pipe', 'pipe'] });
await new Promise((ok, fail) => {
  const t = setTimeout(() => fail(new Error('vite preview 启动超时')), 20000);
  const on = (b) => { if (String(b).includes(String(PORT))) { clearTimeout(t); ok(); } };
  server.stdout.on('data', on);
  server.stderr.on('data', on);
});

// 预期内的 4xx（演示 422 拦截等）记录为 expected4xx，不算失败
const EXPECTED_4XX = [/\/imports\/[^/]+\/confirm :: HTTP 422/];
const result = { viewport: '1440x900', shots: [], consoleErrors: [], pageErrors: [], failedRequests: [], expected4xx: [], external: [], checks: {} };
const browser = await chromium.launch();
try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark', locale: 'zh-CN', timezoneId: 'Asia/Shanghai' });
  const page = await ctx.newPage();
  page.on('console', (m) => {
    // 浏览器会把 4xx 响应自动打印成 console error，这类由 response 监听单独统计
    if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) result.consoleErrors.push(`${page.url()} :: ${m.text()}`);
  });
  page.on('pageerror', (e) => result.pageErrors.push(`${page.url()} :: ${e.message}`));
  page.on('requestfailed', (r) => { const e = r.failure()?.errorText ?? ''; if (!e.includes('ERR_ABORTED')) result.failedRequests.push(`${r.url()} :: ${e}`); });
  page.on('response', (r) => {
    if (r.status() < 400) return;
    const s = `${r.url()} :: HTTP ${r.status()}`;
    (EXPECTED_4XX.some((re) => re.test(s)) ? result.expected4xx : result.failedRequests).push(s);
  });
  page.on('request', (r) => { if (!r.url().startsWith(BASE) && !r.url().startsWith('data:')) result.external.push(r.url()); });
  const shot = async (name, note) => { await page.mouse.move(1430, 890); await page.waitForTimeout(250); const file = resolve(OUT, name); await page.screenshot({ path: file }); result.shots.push({ file, note }); };
  const login = async (username, next) => {
    await page.goto(`${BASE}/login?next=${encodeURIComponent(next)}`);
    await page.getByLabel('用户名').fill(username);
    await page.getByLabel('密码').fill(PW);
    await page.locator('button[type=submit]').click();
  };

  // 1) 登录页
  await page.goto(`${BASE}/login`);
  await page.waitForSelector('[data-testid=login-page], form');
  await page.waitForTimeout(400);
  await shot('01-login.png', '登录页（深色）');

  // 2) 开通引导：未签署用户登录 → /onboarding
  await login('new_user', '/portfolio');
  await page.waitForSelector('[data-testid=onboarding-consents]');
  for (const cb of await page.locator('[data-testid=onboarding-consents] input[type=checkbox]').all()) await cb.check();
  await page.waitForTimeout(300);
  await shot('02-onboarding-consents.png', '开通引导：阅读并同意');
  await page.getByRole('button', { name: /同意并继续/ }).click();
  await page.waitForSelector('[data-testid=onboarding-risk]');
  for (const g of await page.locator('[data-testid=onboarding-risk] .ant-radio-group').all()) await g.locator('input[type=radio]').nth(1).check();
  await page.getByRole('button', { name: /提交测评/ }).click();
  await page.waitForSelector('[data-testid=risk-level]');
  result.checks.riskLevel = await page.locator('[data-testid=risk-level]').innerText();
  await shot('03-onboarding-done.png', '开通引导：测评完成');

  // 3) 用户审核（管理员）
  await login('admin', '/admin/users');
  await page.waitForSelector('[data-testid=admin-users] .ant-table-row');
  await page.waitForTimeout(400);
  await shot('04-admin-users.png', '用户审核（待审核列表，同 IP 注册数 ≥3 标橙）');
  await page.click('[data-testid=act-rejected-pending_user]');
  await page.waitForSelector('[data-testid=admin-reason]');
  await page.waitForTimeout(300);
  result.checks.rejectOkDisabledWithoutReason = await page.locator('.ant-modal-footer .ant-btn-primary').isDisabled();
  await shot('05-admin-reject-reason.png', '驳回必须填写理由');

  // 4) 持仓 / 对账（示例会话默认 demo_user）
  await page.goto(`${BASE}/portfolio?tab=reconciliation`);
  await page.waitForSelector('[data-testid=diluted-cost-note]');
  await page.waitForTimeout(500);
  await shot('06-portfolio-reconciliation.png', '对账：分红计入摊薄成本口径 + 差异项');
  await page.goto(`${BASE}/portfolio?tab=trades`);
  await page.waitForSelector('[data-testid=trades-tab] .ant-table-row');
  await page.waitForTimeout(300);
  await shot('07-portfolio-trades.png', '成交记录（作废记录带标记）');

  // 5) 导入向导：上传 → 预览着色 → 确认 422 → 写入
  await page.goto(`${BASE}/portfolio/import`);
  await page.waitForSelector('[data-testid=import-upload]');
  await page.setInputFiles('[data-testid=import-upload] input[type=file]', { name: 'trades_sample.txt', mimeType: 'text/plain', buffer: Buffer.from('示例列A\t示例列B\n20261026\t09:35:12\n') });
  await page.click('[data-testid=upload-submit]');
  await page.waitForSelector('[data-testid=rows-table] .imp-error', { timeout: 15000 });
  await page.waitForTimeout(500);
  result.checks.toneRows = await page.evaluate(() => Object.fromEntries(['imp-error', 'imp-action', 'imp-skip', 'imp-info'].map((c) => [c, document.querySelectorAll(`[data-testid=rows-table] tr.${c}`).length])));
  await shot('08-import-preview.png', '导入预览：按提示码着色（红=错误 / 橙=需处理 / 灰=跳过 / 金=仅提示）');
  await page.locator('[data-testid=rows-table]').scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await shot('09-import-preview-rows.png', '导入预览：行级着色与提示');
  await page.getByRole('radio', { name: /只写入有效行/ }).check();
  await page.click('[data-testid=confirm-import]');
  await page.waitForSelector('[data-testid=confirm-error]');
  await page.locator('[data-testid=confirm-panel]').scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await shot('10-import-confirm-422.png', '确认写入被拦：需处理的警告未确认（IMPORT_WARNINGS_UNACKNOWLEDGED）');
  await page.click('[data-testid=ack-warnings]');
  await page.click('[data-testid=confirm-import]');
  await page.waitForSelector('[data-testid=import-done]');
  await page.waitForTimeout(400);
  await shot('11-import-done.png', '导入完成：写入统计、对账结果、撤销入口');

  // 6) 投资画像
  await page.goto(`${BASE}/settings/profile`);
  await page.waitForSelector('[data-testid=profile-page] form');
  await page.waitForTimeout(300);
  await shot('12-profile.png', '投资画像');
} finally {
  await browser.close();
  server.kill();
}
writeFileSync(resolve(OUT, 'screenshot-result.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
const bad = result.consoleErrors.length + result.pageErrors.length + result.external.length + result.failedRequests.length;
process.exit(bad ? 1 : 0);
