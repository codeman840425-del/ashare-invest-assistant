/**
 * 评审 T-F22a B1 守卫：src/、scripts/ 下的源文件都不能被 .gitignore 忽略。
 * 否则本地能跑、干净检出（CI）缺文件——T-O09 main 失败即此原因（mocks/licence.ts 命中根目录 `licence.*`）。
 */
import { execFileSync } from 'node:child_process';
import { readdirSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';

const ROOT = resolve(__dirname, '../..');

function gitAvailable(): boolean {
  try {
    execFileSync('git', ['rev-parse', '--is-inside-work-tree'], { cwd: ROOT, stdio: 'pipe' });
    return true;
  } catch {
    return false;
  }
}

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(tsx?|mjs|cjs|js|css|json)$/.test(name)) out.push(relative(ROOT, p));
  }
  return out;
}

describe('源文件未被 .gitignore 忽略（B1 守卫）', () => {
  it.runIf(gitAvailable())('src/ 与 scripts/ 下没有被忽略的源文件', () => {
    const files = [...walk(join(ROOT, 'src')), ...walk(join(ROOT, 'scripts'))];
    expect(files.length).toBeGreaterThan(50);
    let ignored: string;
    try {
      ignored = execFileSync('git', ['check-ignore', '--no-index', '--stdin'], { cwd: ROOT, input: files.join('\n'), stdio: 'pipe' }).toString();
    } catch (e) {
      // exit 1 = 没有任何文件被忽略
      if ((e as { status?: number }).status === 1) ignored = '';
      else throw e;
    }
    expect(ignored.trim().split('\n').filter(Boolean)).toEqual([]);
  });
});
