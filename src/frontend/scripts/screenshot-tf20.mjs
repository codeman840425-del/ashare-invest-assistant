// T-F20 截图：build:mock 后 vite preview（只连 127.0.0.1），1440×900 深色；localStorage mock:route-pending=1 模拟路由未实现。
// 用法：pnpm run build:mock && node scripts/screenshot-tf20.mjs [输出目录]
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const OUT = resolve(process.argv[2] ?? '/workspace/team/reports/T-F20');
const PORT = 4186;
const BASE = `http://127.0.0.1:${PORT}`;
mkdirSync(OUT, { recursive: true });
const server = spawn('pnpm', ['exec', 'vite', 'preview', '--mode', 'mock', '--host', '127.0.0.1', '--port', String(PORT), '--strictPort'], { stdio: ['ignore', 'pipe', 'pipe'] });
await new Promise((ok, fail) => {
  const t = setTimeout(() => fail(new Error('vite preview 启动超时')), 20000);
  const on = (b) => { if (String(b).includes(String(PORT))) { clearTimeout(t); ok(); } };
  server.stdout.on('data', on);
  server.stderr.on('data', on);
});
const browser = await chromium.launch();
try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark', locale: 'zh-CN', timezoneId: 'Asia/Shanghai' });
  await ctx.addInitScript(() => localStorage.setItem('mock:route-pending', '1'));
  const page = await ctx.newPage();
  await page.goto(`${BASE}/today`);
  await page.waitForSelector('[data-testid=route-pending]', { timeout: 15000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: resolve(OUT, '01-today-route-pending.png') });
  console.log('ok', resolve(OUT, '01-today-route-pending.png'));
} finally {
  await browser.close();
  server.kill();
}
