/**
 * 合规自查：源码与示例数据中不得出现荐股措辞（v0.2.5 起免责提示改为 disclaimer.md 原文，不再需要放行短语）。
 * 也检查依赖中没有 ag-grid-enterprise（禁止任何企业版包或功能）。
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

const ROOT = resolve(__dirname, '../..');
const SRC = join(ROOT, 'src');
const SELF = resolve(__filename);

const BANNED = ['推荐买入', '推荐卖出', '强烈推荐', '必涨', '稳赚', '荐股', '牛股', '金股', '抄底良机', '保本', '翻倍', '内幕', '目标价'];

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? walk(p) : /\.(tsx?|css|html)$/.test(f) ? [p] : [];
  });
}

describe('合规措辞', () => {
  const files = [...walk(SRC), join(ROOT, 'index.html')].filter((f) => resolve(f) !== SELF);
  it('扫描到源码文件', () => expect(files.length).toBeGreaterThan(20));
  it.each(BANNED)('不出现“%s”', (word) => {
    const hits = files.filter((f) => readFileSync(f, 'utf8').includes(word));
    expect(hits).toEqual([]);
  });
  it('用“候选信号 / 规则信号”而非“建议买入”类措辞', () => {
    const hits = files.filter((f) => /建议(买入|卖出|加仓|减仓)/.test(readFileSync(f, 'utf8')));
    expect(hits).toEqual([]);
  });
});

describe('依赖', () => {
  it('package.json 与 pnpm-lock.yaml 中没有 ag-grid-enterprise；只用 pnpm', () => {
    const pkg = readFileSync(join(ROOT, 'package.json'), 'utf8');
    const lock = readFileSync(join(ROOT, 'pnpm-lock.yaml'), 'utf8');
    expect(existsSync(join(ROOT, 'package-lock.json'))).toBe(false);
    expect(JSON.parse(pkg).packageManager).toMatch(/^pnpm@\d+\.\d+\.\d+$/);
    expect(pkg).not.toContain('ag-grid-enterprise');
    expect(lock).not.toContain('ag-grid-enterprise');
    const deps = JSON.parse(pkg).dependencies as Record<string, string>;
    expect(Object.keys(deps)).toEqual(expect.arrayContaining(['ag-grid-community', 'ag-grid-react', 'antd', 'lightweight-charts', 'react-resizable-panels']));
  });
});
