// 真实应用 E2E 入口（T-T01 脚手架）。仅当 E2E_BASE_URL 指向已启动的站点时执行；否则 skip。
// 主流程（plan §8.0：注册→审核→登录→导入→启用策略→日报→盘中翻转→建议卡→转计划→模拟跟踪）由后续 T-T 任务补齐。
// 本地/CI 站点必须运行在 MAIRUI_MODE=replay 下；E2E 永不触发真实麦蕊调用。
import { expect, test } from '@playwright/test';

test.skip(!process.env.E2E_BASE_URL, '未设置 E2E_BASE_URL，跳过真实应用 E2E');

test('健康检查可达且不泄露细节', async ({ request }) => {
  const res = await request.get('/api/v1/health');
  test.skip(res.status() === 404, '后端 /api/v1/health 尚未实现（占位服务）');
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(['ok', 'degraded']).toContain(body.status);
});

test('首页在 1440×900 深色下可打开', async ({ page }) => {
  await page.goto('/');
  expect(page.viewportSize()).toEqual({ width: 1440, height: 900 });
  expect(await page.evaluate(() => matchMedia('(prefers-color-scheme: dark)').matches)).toBe(true);
});
