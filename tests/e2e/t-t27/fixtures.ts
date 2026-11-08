import { test as base, expect, type Page } from '@playwright/test';

export const credentialInterface = '/workspace/team/runtime/T-O15/viewer-cred';
export type ViewerCredentials = Readonly<{ username: string; password: string }>;
export type ApprovedSetup = (page: Page) => Promise<void>;

type Fixtures = {
  signedIn: Page;
  // 可选步骤必须经另行批准后显式接入；此文件不实现审核、赋管理员或数据库操作。
  adminSetup: ApprovedSetup | undefined;
  registrationSetup: ApprovedSetup | undefined;
};

async function approvedViewerCredentials(): Promise<ViewerCredentials> {
  // 故意不猜测路径是文件/目录及 JSON/文本格式；未读取或生成任何凭据。
  // 获授权后先核对 T-O15 的实际路径格式，再单独实现此内存接口；禁止日志/附件/持久化会话。
  throw new Error('待授权并核对 viewer-cred 格式后接入凭据适配器；当前禁止登录');
}

export const test = base.extend<Fixtures>({
  adminSetup: [undefined, { option: true }],
  registrationSetup: [undefined, { option: true }],
  context: async ({ context }, use) => {
    test.skip(process.env.T_T27_EXECUTION_APPROVED !== 'yes', '仅准备：未获执行授权');
    const external: string[] = [];
    const mutations: string[] = [];
    await context.route('**/*', async (route) => {
      const r = route.request();
      const u = new URL(r.url());
      if (!['127.0.0.1', 'localhost'].includes(u.hostname) ||
          u.protocol !== 'http:' || u.port !== '8080' || u.username || u.password) {
        external.push('blocked');
        await route.abort('blockedbyclient');
        return;
      }
      const read = ['GET', 'HEAD', 'OPTIONS'].includes(r.method());
      const login = r.method() === 'POST' && u.pathname === '/api/v1/auth/login';
      if (!read && !login) {
        mutations.push('blocked');
        await route.abort('blockedbyclient');
        return;
      }
      await route.continue();
    });
    await context.routeWebSocket('**/*', (ws) => {
      const u = new URL(ws.url());
      if (['127.0.0.1', 'localhost'].includes(u.hostname) && u.protocol === 'ws:' && u.port === '8080') {
        ws.connectToServer();
      } else {
        external.push('blocked');
        ws.close();
      }
    });
    await use(context);
    // 仅报个数，不输出请求 URL、payload、cookie 或凭据。
    expect(external.length, '发现被阻止的外部请求').toBe(0);
    expect(mutations.length, '发生未获授权的写请求，已阻止').toBe(0);
  },
  signedIn: async ({ page }, use) => {
    test.skip(process.env.T_T27_EXECUTION_APPROVED !== 'yes', '登录步骤未授权');
    const c = await approvedViewerCredentials();
    await page.goto('/login');
    await page.getByLabel('用户名', { exact: true }).fill(c.username);
    await page.getByLabel('密码', { exact: true }).fill(c.password);
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await expect(page).not.toHaveURL(/\/login(?:\?|$)/);
    await use(page);
  },
});
export { expect };
