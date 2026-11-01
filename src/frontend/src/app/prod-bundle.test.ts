/**
 * 评审 T-F02 P1：示例题库与 MSW 不得进入生产包。
 * 源码层：除测试与 main.tsx 里受 MODE 守卫的动态导入外，任何业务代码都不得引用 src/mocks/ 或 msw。
 * 产物层：pnpm build 后由 scripts/check-dist.mjs（pnpm check:dist）扫描 dist/，见 reports/T-F02b.md。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';

const SRC = resolve(__dirname, '..');
const files: string[] = [];
const walk = (d: string) => {
  for (const n of readdirSync(d)) {
    const p = join(d, n);
    if (statSync(p).isDirectory()) walk(p);
    else if (/\.(ts|tsx)$/.test(n)) files.push(p);
  }
};
walk(SRC);
const app = files.filter((f) => {
  const r = relative(SRC, f).replaceAll('\\', '/');
  return !r.startsWith('mocks/') && !r.startsWith('test/') && !/\.test\.tsx?$/.test(r);
});
const IMPORT = /(?:from\s+|import\s*\(\s*)['"]([^'"]+)['"]/g;

describe('生产包不含示例数据与 MSW（源码层）', () => {
  it('业务代码不引用 mocks/ 与 msw（main.tsx 的受守卫动态导入除外）', () => {
    const bad: string[] = [];
    for (const f of app) {
      const r = relative(SRC, f).replaceAll('\\', '/');
      for (const m of readFileSync(f, 'utf8').matchAll(IMPORT)) {
        const spec = m[1];
        if (!/(^|\/)mocks(\/|$)/.test(spec) && !/^msw(\/|$)/.test(spec) && spec !== 'virtual:msw') continue;
        if (r === 'main.tsx' && m[0].startsWith('import')) continue;
        bad.push(`${r} → ${spec}`);
      }
    }
    expect(bad).toEqual([]);
  });

  it('main.tsx 的 MSW 启动在 MODE === production 时直接返回', () => {
    const main = readFileSync(join(SRC, 'main.tsx'), 'utf8');
    const guard = main.indexOf("import.meta.env.MODE === 'production'");
    expect(guard).toBeGreaterThan(-1);
    for (const m of main.matchAll(/import\s*\(\s*['"]([^'"]+)['"]/g)) expect(m.index).toBeGreaterThan(guard);
  });

  it('v0.2.5：同意流程与风险测评的残留（路由、题库、门槛）在业务代码和 mocks 里都不存在', () => {
    const hits = files
      .filter((f) => !/\.test\.tsx?$/.test(f))
      .filter((f) => /onboarding|CONSENT_REQUIRED|risk-assessment|consent-docs|demo_[a-z]\d?_\w+|demo-sha256/.test(readFileSync(f, 'utf8')))
      .map((f) => relative(SRC, f));
    expect(hits).toEqual([]);
  });
});
