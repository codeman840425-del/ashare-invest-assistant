// T-F01 验收截图：构建示例数据包（build:mock）后用 vite preview 起本地服务，
// Playwright 1440×900 截主要页面，并验证分栏拖拽/持久化/恢复默认、收集控制台错误。
// 只访问 127.0.0.1；所有 /api/v1 请求由页面内 MSW Service Worker 返回示例数据。
// 用法：npm run build:mock && npm run screenshot [-- 输出目录]
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const OUT = resolve(process.argv[2] ?? '/workspace/team/reports/T-F01');
const PORT = 4173;
const BASE = `http://127.0.0.1:${PORT}`;
mkdirSync(OUT, { recursive: true });

const server = spawn('npx', ['vite', 'preview', '--mode', 'mock', '--host', '127.0.0.1', '--port', String(PORT), '--strictPort'], {
  stdio: ['ignore', 'pipe', 'pipe'],
});
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
  page.on('console', (m) => { if (m.type() === 'error') result.consoleErrors.push(`${page.url()} :: ${m.text()}`); });
  page.on('pageerror', (e) => result.pageErrors.push(`${page.url()} :: ${e.message}`));
  // 页面跳转时取消的在途请求（net::ERR_ABORTED）属正常，不计为失败
  page.on('requestfailed', (r) => { const e = r.failure()?.errorText ?? ''; if (!e.includes('ERR_ABORTED')) result.failedRequests.push(`${r.url()} :: ${e}`); });
  page.on('response', (r) => { if (r.status() >= 400) result.failedRequests.push(`${r.url()} :: HTTP ${r.status()}`); });
  page.on('request', (r) => { if (!r.url().startsWith(BASE) && !r.url().startsWith('data:')) result.external.push(r.url()); });

  const shot = async (name, note) => {
    const file = resolve(OUT, name);
    await page.screenshot({ path: file });
    result.shots.push({ file, note });
  };
  const leftWidth = () => page.locator('[data-panel][id="left"], [data-panel-id="left"], #left').first().boundingBox().then((b) => (b ? Math.round(b.width) : null));

  // 1) 终端
  await page.goto(`${BASE}/terminal`);
  await page.waitForSelector('[data-testid=watch-table] .ag-row', { timeout: 15000 });
  await page.waitForSelector('[data-testid=kline] canvas', { timeout: 15000 });
  await page.waitForSelector('[data-testid=consensus-bar]', { timeout: 15000 });
  await page.waitForTimeout(600);
  result.checks.bodyBackground = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  result.checks.gridBackground = await page.evaluate(() => {
    const el = document.querySelector('[data-testid=watch-table] .ag-root-wrapper');
    return el ? getComputedStyle(el).backgroundColor : null;
  });
  result.checks.riskDisclosure = await page.locator('[data-testid=risk-disclosure]').innerText();
  result.checks.terminalRows = await page.evaluate(() => new Set([...document.querySelectorAll('[data-testid=watch-table] .ag-row[row-id]')].map((e) => e.getAttribute('row-id'))).size);
  await shot('01-terminal.png', '交易终端（默认布局）');

  // 2) 拖拽左侧分隔条 +180px
  const before = await leftWidth();
  const sep = page.locator('[data-testid=sep-left]');
  const sb = await sep.boundingBox();
  await page.mouse.move(sb.x + sb.width / 2, sb.y + sb.height / 2);
  await page.mouse.down();
  await page.mouse.move(sb.x + sb.width / 2 + 90, sb.y + sb.height / 2, { steps: 6 });
  result.checks.separatorStateWhileDragging = await sep.getAttribute('data-separator');
  await page.mouse.move(sb.x + sb.width / 2 + 180, sb.y + sb.height / 2, { steps: 6 });
  await page.mouse.up();
  await page.waitForTimeout(700);
  const after = await leftWidth();
  // 底部分隔条向上拖 80px
  const vs = await page.locator('[data-testid=sep-bottom]').boundingBox();
  await page.mouse.move(vs.x + vs.width / 2, vs.y + vs.height / 2);
  await page.mouse.down();
  await page.mouse.move(vs.x + vs.width / 2, vs.y + vs.height / 2 - 80, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(700);
  await shot('02-terminal-dragged.png', '拖拽后：左栏变宽、底部面板变高');
  const saved = await page.evaluate(() => Object.keys(localStorage).filter((k) => k.includes('ashare.terminal')).map((k) => [k, localStorage.getItem(k)]));
  await page.reload();
  await page.waitForSelector('[data-testid=watch-table] .ag-row', { timeout: 15000 });
  await page.waitForTimeout(500);
  const afterReload = await leftWidth();
  await page.click('[data-testid=reset-layout]');
  await page.waitForTimeout(600);
  const afterReset = await leftWidth();
  result.checks.drag = { leftBefore: before, leftAfterDrag: after, leftAfterReload: afterReload, leftAfterReset: afterReset, savedLayouts: saved };
  await shot('03-terminal-reset.png', '刷新后保持拖拽布局，再点“恢复默认布局”');

  // 3) 选中另一只（停牌示例）+ 通知弹层
  await page.locator('[data-testid=watch-table] .ag-row', { hasText: '演示精工' }).first().click();
  await page.waitForTimeout(500);
  await page.click('button[aria-label="通知"]');
  await page.waitForSelector('[data-testid=notification-panel]');
  await page.waitForTimeout(300);
  await shot('04-terminal-notifications.png', '选中停牌示例 + 通知弹层');
  await page.keyboard.press('Escape');

  // 4) 候选信号卡详情（分歧样例：双击 示例银行）
  await page.goto(`${BASE}/terminal`);
  await page.waitForSelector('[data-testid=watch-table] .ag-row');
  await page.locator('[data-testid=watch-table] .ag-row', { hasText: '示例银行' }).first().dblclick();
  await page.waitForSelector('[data-testid=suggestion-detail]');
  await page.waitForSelector('[data-testid=matrix] .ag-row');
  result.checks.matrixVisibleHeight = await page.locator('[data-testid=matrix]').evaluate((el) => el.getBoundingClientRect().height);
  result.checks.evidenceVisibleHeight = await page.locator('[data-testid=evidence]').evaluate((el) => el.getBoundingClientRect().height);
  await page.waitForTimeout(500);
  result.checks.suggestionUrl = page.url();
  await shot('05-suggestion-detail.png', '候选信号卡详情（分歧样例，维度×策略矩阵）');
  await page.locator('.content').evaluate((el) => { el.scrollTop = 620; });
  await page.locator('[data-testid=suggestion-detail]').evaluate((el) => { el.scrollTop = 620; });
  await page.waitForTimeout(300);
  await shot('06-suggestion-detail-strategies.png', '候选信号卡详情（各策略并列卡片 + 解除条件）');

  // 5) 盘后日报（/reports 旧路径重定向）
  await page.goto(`${BASE}/reports`);
  await page.waitForSelector('[data-testid=daily-report]');
  await page.waitForTimeout(400);
  result.checks.reportUrl = page.url();
  await shot('07-daily-report.png', '盘后日报（/reports → /daily-reports/:date）');

  // 6) 占位页
  await page.goto(`${BASE}/strategies`);
  await page.waitForSelector('[data-testid=placeholder]');
  await shot('08-placeholder.png', '占位页（策略库）');

  // 7) 分辨率检测
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto(`${BASE}/terminal`);
  await page.waitForSelector('[data-testid=viewport-hint]');
  await page.waitForSelector('[data-testid=watch-table] .ag-row');
  await page.waitForTimeout(400);
  await shot('09-viewport-1366x768-hint.png', '1366×768：低于推荐分辨率提示');
  await page.setViewportSize({ width: 1200, height: 800 });
  await page.waitForSelector('[data-testid=desktop-guard]');
  await shot('10-viewport-1200-guard.png', '宽度 < 1280：请使用电脑端');
} finally {
  await browser.close();
  server.kill();
}
writeFileSync(resolve(OUT, 'screenshot-result.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
const bad = result.consoleErrors.length + result.pageErrors.length + result.external.length + result.failedRequests.length;
process.exit(bad ? 1 : 0);
