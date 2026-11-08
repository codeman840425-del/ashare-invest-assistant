import { mkdir } from 'node:fs/promises';
import { test, expect } from './fixtures';
import type { Page } from '@playwright/test';

// 开关不是授权本身：只有编排者核实且用户另行通知后才能执行，不得自行设置开关。
test.beforeEach(() => {
  test.skip(process.env.T_T27_EXECUTION_APPROVED !== 'yes', '仅准备：尚未收到执行授权');
});

async function capture(page: Page, route: string, file: string, testId?: string) {
  const response = await page.goto(route);
  expect(response?.ok(), '页面文档应成功返回').toBeTruthy();
  await expect(page).toHaveURL(new RegExp(`${route.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?:\\?|$)`));
  if (testId) await expect(page.getByTestId(testId)).toBeVisible();
  else await expect(page.locator('body')).not.toBeEmpty();
  // 截图严格在运行时生成；只给未填写凭据的登录表单截图。
  await mkdir('/workspace/screens', { recursive: true });
  await page.screenshot({ path: `/workspace/screens/${file}`, fullPage: true });
}

test('01 登录入口（不提交）', async ({ page }) => {
  await capture(page, '/login', '01-login.png', 'login-page');
});
test('02 注册入口（不提交，允许如实展示 closed 状态）', async ({ page }) => {
  await capture(page, '/register', '02-register.png');
  await expect(page.getByRole('button', { name: '登录', exact: true })).toHaveCount(0);
});

const views = [
  ['/portfolio', '03-portfolio.png', 'portfolio-page'],
  ['/today', '04-focus.png', undefined], // nav.ts：“今日关注”，不是虚构 /watchlist 路由。
  ['/terminal', '05-watchlist.png', 'watch-table'], // 自选/持仓分段实际位于 terminal。
  ['/strategies', '06-strategies.png', 'strategies-page'],
  ['/daily-reports', '07-post-market.png', undefined],
  ['/terminal', '08-intraday.png', 'terminal'], // 盘中建议在终端右栏；不伪造 /intraday 路由。
  ['/portfolio/import', '09-import.png', undefined], // 只打开向导，不上传、不确认。
  ['/notifications', '10-notifications.png', 'notifications-page'],
] as const;
for (const [route, file, id] of views) {
  test(`${file} ${route}`, async ({ signedIn }) => {
    await capture(signedIn, route, file, id);
  });
}

test('11 管理端（可选 fixture 默认禁用）', async ({ signedIn, adminSetup }) => {
  test.skip(!adminSetup, '待批准管理员身份/审核步骤；不自动赋权');
  await adminSetup!(signedIn);
  await capture(signedIn, '/admin/users', '11-admin-users.png');
  await capture(signedIn, '/admin/ingest', '12-admin-ingest.png');
  await capture(signedIn, '/admin/data-licences', '13-admin-data-licences.png');
});

test('可选注册/审核步骤接口（默认禁用，无业务实现）', async ({ page, registrationSetup }) => {
  test.skip(!registrationSetup, '注册提交/审核须独立授权后另接 fixture');
  await registrationSetup!(page);
});
