// Playwright 配置（T-T01）。plan §8.0：桌面 1440×900、深色主题。
// 运行：pnpm -C tests e2e
//  - 未设置 E2E_BASE_URL：自动用 python3 起本地静态页（tests/e2e/static，端口 E2E_STATIC_PORT，默认 4399）跑示例。
//    不用 4173：那是 vite preview 默认端口，reuseExistingServer 会误连前端预览（T-T01a 发现）。
//  - 设置 E2E_BASE_URL（如 http://127.0.0.1:8080，nginx）：不起静态服务，直接测目标站点；app.spec.ts 才会执行。
import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';

const here = fileURLToPath(new URL('.', import.meta.url));

const staticPort = Number(process.env.E2E_STATIC_PORT ?? 4399);
const externalBaseURL = process.env.E2E_BASE_URL;
const baseURL = externalBaseURL ?? `http://127.0.0.1:${staticPort}`;

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.ts',
  outputDir: '../test-results',
  reporter: [['list'], ['html', { outputFolder: '../playwright-report', open: 'never' }]],
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 30_000,
  use: {
    baseURL,
    viewport: { width: 1440, height: 900 },
    colorScheme: 'dark',
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'desktop-chromium-dark',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        colorScheme: 'dark',
      },
    },
  ],
  webServer: externalBaseURL
    ? undefined
    : {
        command: `python3 -m http.server ${staticPort} --bind 127.0.0.1 --directory static`,
        url: `http://127.0.0.1:${staticPort}/index.html`,
        cwd: here,
        reuseExistingServer: !process.env.CI,
        timeout: 15_000,
      },
});
