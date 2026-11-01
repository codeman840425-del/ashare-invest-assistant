/**
 * 合规自查：源码与示例数据中不得出现荐股措辞；风险揭示里的“不保证收益”是否定语境，单独放行。
 * 也检查依赖中没有 ag-grid-enterprise（禁止任何企业版包或功能）。
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

const ROOT = resolve(__dirname, '../..');
const SRC = join(ROOT, 'src');
const SELF = resolve(__filename);

const BANNED = ['推荐买入', '推荐卖出', '强烈推荐', '必涨', '稳赚', '荐股', '牛股', '金股', '抄底良机', '保本', '翻倍', '内幕', '目标价'];
const ALLOWED_PHRASES = ['不保证收益'];

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
    const hits = files.filter((f) => {
      let t = readFileSync(f, 'utf8');
      for (const ok of ALLOWED_PHRASES) t = t.split(ok).join('');
      return t.includes(word);
    });
    expect(hits).toEqual([]);
  });
  it('用“候选信号 / 规则信号”而非“建议买入”类措辞', () => {
    const hits = files.filter((f) => /建议(买入|卖出|加仓|减仓)/.test(readFileSync(f, 'utf8')));
    expect(hits).toEqual([]);
  });
});

describe('依赖', () => {
  it('package.json 与 lock 中没有 ag-grid-enterprise', () => {
    const pkg = readFileSync(join(ROOT, 'package.json'), 'utf8');
    const lock = readFileSync(join(ROOT, 'package-lock.json'), 'utf8');
    expect(pkg).not.toContain('ag-grid-enterprise');
    expect(lock).not.toContain('ag-grid-enterprise');
    const deps = JSON.parse(pkg).dependencies as Record<string, string>;
    expect(Object.keys(deps)).toEqual(expect.arrayContaining(['ag-grid-community', 'ag-grid-react', 'antd', 'lightweight-charts', 'react-resizable-panels']));
  });
});
