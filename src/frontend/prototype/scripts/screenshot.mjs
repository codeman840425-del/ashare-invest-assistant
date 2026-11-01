// 用 Playwright（headless chromium）以 file:// 打开 dist/index.html，1440×900 截三页。
// 用法：pnpm run build && pnpm run screenshot [输出目录]
import { chromium } from 'playwright';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const here = path.dirname(fileURLToPath(import.meta.url));
const dist = path.resolve(here, '../dist/index.html');
const outDir = process.argv[2] ?? '/workspace/team/reports/T-F00';
fs.mkdirSync(outDir, { recursive: true });
const base = pathToFileURL(dist).href;

const pages = [
  { file: '01-terminal.png', hash: '#/terminal', canvases: 2 },
  { file: '02-signal-detail.png', hash: '#/suggestions/600000.SH', canvases: 0, full: true },
  { file: '03-daily-report.png', hash: '#/reports/2026-10-30', canvases: 0, full: true },
];

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const page = await ctx.newPage();
const errors = [];
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errors.push(`[${m.type()}] ${m.text()}`); });
page.on('pageerror', (e) => errors.push(`[pageerror] ${e.message}`));
page.on('request', (r) => { if (!r.url().startsWith('file://') && !r.url().startsWith('data:')) errors.push(`[network] ${r.url()}`); });

let failed = false;
for (const p of pages) {
  await page.goto(base + p.hash);
  await page.waitForSelector('.shell');
  if (p.canvases) {
    await page.waitForFunction((n) => {
      const ok = (sel) => { const c = document.querySelector(`${sel} canvas`); return c && c.width > 100 && c.height > 100; };
      return n === 2 ? ok('[data-testid=kline]') && ok('[data-testid=intraday]') : true;
    }, p.canvases, { timeout: 10000 });
  }
  await page.waitForTimeout(600);
  const banner = await page.locator('.sample-banner').isVisible();
  const wm = await page.locator('.watermark').count();
  await page.screenshot({ path: path.join(outDir, p.file) });
  if (p.full) {
    // 附加：整页长图（临时取消内部滚动容器，仅用于截图）
    const tag = await page.addStyleTag({ content: 'body{overflow:visible!important}.shell{height:auto!important}.content{overflow:visible!important}' });
    await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(outDir, p.file.replace('.png', '-full.png')), fullPage: true });
    await tag.evaluate((n) => n.remove());
  }
  console.log(`${p.file}: banner=${banner} watermark=${wm}`);
}

// 交互抽查：终端行 → 详情；生成计划草案 → 弹窗
await page.goto(base + '#/terminal');
await page.locator('.dense-table tbody tr', { hasText: '演示电子' }).first().dblclick();
await page.waitForSelector('.detail');
console.log('dblclick → detail:', await page.evaluate(() => location.hash));
await page.getByRole('button', { name: '生成计划草案' }).first().click();
await page.waitForSelector('.ant-modal');
console.log('plan draft modal:', (await page.locator('.ant-modal-title').innerText()).trim());

await browser.close();
const real = errors.filter((e) => !/Download the React DevTools/.test(e));
if (real.length) { console.log('CONSOLE/NETWORK ISSUES:\n' + real.join('\n')); failed = true; } else console.log('console: no errors/warnings; network: file:// only');
process.exit(failed ? 1 : 0);
