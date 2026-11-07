import { defineConfig } from '@playwright/test';

// 独立配置：发现用例不会启动 webServer、浏览器、登录或读取凭据。
export default defineConfig({
  testDir: '.',
  testMatch: 'viewer.spec.ts',
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 45_000,
  reporter: [['list']],
  outputDir: '../../test-results/t-t27',
  use: {
    baseURL: 'http://127.0.0.1:8080',
    browserName: 'chromium',
    viewport: { width: 1440, height: 900 },
    colorScheme: 'dark',
    locale: 'zh-CN',
    timezoneId: 'America/Denver',
    serviceWorkers: 'block',
    // 不保存含登录请求/表单/会话的 trace、录像或失败自动截图。
    trace: 'off', video: 'off', screenshot: 'off',
  },
});
