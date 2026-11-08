// Playwright 示例（T-T01）：验证 E2E 环境本身——视口 1440×900、深色主题、窄屏提示约定（plan §2.4）。
import { expect, test } from '@playwright/test';

test.skip(!!process.env.E2E_BASE_URL, '已指定 E2E_BASE_URL，示例静态页不参与');

test('视口为 1440×900，深色主题生效', async ({ page }) => {
  await page.goto('/index.html');
  await expect(page).toHaveTitle(/E2E 冒烟页/);
  expect(page.viewportSize()).toEqual({ width: 1440, height: 900 });
  expect(await page.evaluate(() => matchMedia('(prefers-color-scheme: dark)').matches)).toBe(true);
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(bg).toBe('rgb(20, 20, 20)');
  await expect(page.getByRole('status')).toHaveAttribute('data-status', 'fresh');
  await expect(page.getByText('请使用电脑端')).toBeHidden();
});

test('宽度 < 1280 时提示“请使用电脑端”', async ({ page }) => {
  await page.setViewportSize({ width: 1200, height: 900 });
  await page.goto('/index.html');
  await expect(page.getByText('请使用电脑端')).toBeVisible();
});
