/** Local framework-owned headless context ONLY; never attaches the box desktop.
 * Seed consists solely of ephemeral fictional fixture sessions passed in memory.
 * No request.fulfill/MSW/response substitution, persistent profiles or public pages.
 */
import { test, expect, type Page } from 'playwright/test';
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';

test('first-slice 日报 → 风控 → 模拟跟踪 desktop', async ({ page, context, browser, baseURL }) => {
  const seed = JSON.parse(process.env.P2N10_CONTEXT ?? '{}');
  if (!seed.ownerCookies || !seed.strangerCookies || !baseURL) throw new Error('Prepared ephemeral TEST context required');
  const outside: string[] = [];
  const journal: { path: string; status: number; method: string }[] = [];
  const errors: string[] = [];
  const stages: string[] = [];
  const observed = (stage: string) => { stages.push(stage); writeFileSync(join(process.env.P2N10_ARTIFACTS!, 'desktop-progress.json'), JSON.stringify({ stages, journal }, null, 2)); };
  const origin = new URL(baseURL).origin;
  const protect = async (ctx: typeof context) => {
    await ctx.route('**/*', async (route) => {
      const u = new URL(route.request().url());
      if (u.origin === origin || ['data:', 'blob:'].includes(u.protocol)) await route.continue();
      else { outside.push(u.origin); await route.abort('blockedbyclient'); }
    });
  };
  await protect(context);
  await context.addCookies(seed.ownerCookies);
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('response', (r) => { const u = new URL(r.url()); if (u.origin === origin && u.pathname.startsWith('/api/')) journal.push({ path: u.pathname, status: r.status(), method: r.request().method() }); });
  const reportPath = `/daily-reports/${seed.date}`;
  await page.goto(reportPath);
  const card = page.getByTestId('stc-688018.SH');
  await expect(card).toBeVisible();
  const dimensions = page.getByTestId('dimensions-688018.SH');
  await dimensions.locator('summary').click();
  for (const d of ['technical', 'capital', 'fundamental', 'sentiment', 'sector_market', 'news']) await expect(page.getByTestId(`dimension-688018.SH-${d}`)).toBeVisible();
  await expect(dimensions).toContainText('字段等级与取数完整性独立');
  await expect(page.getByTestId('dimension-missing-688018.SH-sector_market')).toBeVisible();
  const citation = dimensions.getByRole('link', { name: /^查看六维证据 / }).first();
  const anchor = await citation.getAttribute('href');
  expect(anchor?.startsWith('#daily-688018.SH-')).toBeTruthy();
  await citation.click();
  await expect(page.locator(`[id="${anchor!.slice(1)}"]`)).toBeVisible();
  observed('owned non-empty daily six dimensions and resolvable local citation');
  await card.getByRole('link', { name: '查看当前风控设置与事件' }).click();
  await expect(page.getByTestId('risk-controls-page')).toBeVisible();
  await expect(page.getByText(/真实接口 · 可读取和保存本人风控设置/)).toBeVisible();
  await expect(page.getByTestId('risk-state-total_exposure')).toContainText('大盘环境未知');
  await expect(page.getByTestId('risk-evaluation-gaps')).toContainText('不能视为通过或正常');
  const position = page.getByTestId('risk-setting-position_cap');
  const input = position.getByLabel('单只仓位上限（%）');
  const save = position.getByRole('button', { name: /保存 / });
  await input.fill('25');
  const [saved] = await Promise.all([page.waitForResponse((r) => new URL(r.url()).pathname === '/api/v1/risk-controls' && r.request().method() === 'PUT'), save.click()]);
  expect(saved.status()).toBe(200);
  await expect(position).toContainText('设置已保存（以服务端响应为准）');
  await input.fill('51');
  await expect(save).toBeDisabled();
  await expect(position.getByTestId('risk-param-errors-position_cap')).toBeVisible();
  await position.getByRole('button', { name: /^恢复默认 / }).click();
  const [restored] = await Promise.all([page.waitForResponse((r) => new URL(r.url()).pathname === '/api/v1/risk-controls' && r.request().method() === 'PUT'), save.click()]);
  expect(restored.status()).toBe(200);

  observed('real risk save/default restore, bounds rejection, unknown not pass');
  await page.goto(reportPath);
  await page.getByTestId('stc-688018.SH').getByRole('link', { name: '查看候选信号模拟结果' }).click();
  await expect(page.getByTestId('tracking-results')).toBeVisible();
  await expect(page.getByTestId('tracking-results')).toContainText('模拟，不代表实际收益');
  const real = await context.request.get(`/api/v1/suggestions/${seed.suggestionId}/tracking`);
  expect(real.status()).toBe(200);
  const observations = (await real.json()).results;
  const completed = observations.filter((r: { state: string }) => r.state === 'complete');
  expect(completed.length).toBe(seed.expectedObservations);
  expect(completed.length).toBeGreaterThan(0);
  await expect(page.getByTestId('tracking-complete')).toHaveCount(completed.length);
  for (const period of [1, 5, 20]) await expect(page.getByTestId('tracking-results').getByRole('heading', { name: new RegExp(`^${period} 日`) }).first()).toBeVisible();

  observed('real non-empty worker tracking all generated suggestion lineages and T+1/5/20');
  const candidates = await context.request.get('/api/v1/candidate-signals');
  expect(candidates.status()).toBe(200);
  const rows = (await candidates.json()).items;
  expect(rows.length).toBeGreaterThan(0);
  expect(rows.some((r: { instance_id: string }) => r.instance_id === seed.missingInstanceId)).toBe(false);
  const stranger = await browser.newContext({ baseURL, serviceWorkers: 'block' });
  try {
    await protect(stranger);
    await stranger.addCookies(seed.strangerCookies);
    const foreign = await stranger.newPage();
    await foreign.goto(reportPath);
    await expect(foreign.getByTestId('stc-688018.SH')).toHaveCount(0);
    expect((await stranger.request.get(`/api/v1/daily-reports/${seed.date}`)).status()).toBe(404);
    expect((await stranger.request.get(`/api/v1/suggestions/${seed.suggestionId}/tracking`)).status()).toBe(404);
    expect((await stranger.request.get(`/api/v1/risk-controls/evaluation?security_code=688018.SH&account_id=${seed.accountId}`)).status()).toBe(404);
  } finally { await stranger.close(); }
  observed('foreign report/tracking/risk account 404 and no foreign stock rendered');
  for (const [id, code] of [[seed.simulatedId, 'STRATEGY_VERSION_NOT_RUNNABLE']]) {
    await page.goto(`/candidate-signals/${id}`);
    const draft = page.getByTestId('draft-btn');
    await expect.soft(draft).toBeDisabled({ timeout: 3000 });
    observed(await draft.count() && await draft.isDisabled() ? 'simulating candidate UI draft button disabled' : 'candidate UI failed to expose disabled draft button');
    const response = await context.request.post('/api/v1/plan-drafts', { data: { signal_ids: [id] }, headers: { 'X-CSRF-Token': seed.ownerCsrf, Origin: origin } });
    expect(response.status()).toBe(409);
    expect((await response.json()).error.code).toBe(code);
  }
  expect(outside).toEqual([]);
  expect(errors).toEqual([]);
  expect(context.serviceWorkers()).toHaveLength(0);
  writeFileSync(join(process.env.P2N10_ARTIFACTS!, 'desktop-assertions.json'), JSON.stringify({ desktop: '1440x900', realApi: true, ownerIsolation: true, citations: true, simulationDraftDenied: true, missingDataNotReleased: true, externalPageAttempts: outside, journal }, null, 2));
});

/** Unregistered second-slice skeleton, deliberately NOT reported as passed/skipped. */
export async function intradayPlanExplanationDesktop(_page: Page): Promise<never> {
  throw new Error('P2N-10b pending P2N-06..09 and matching real frontend acceptance');
}
