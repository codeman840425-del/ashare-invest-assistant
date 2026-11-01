/** T-F02a：契约 v0.2.3 §4.1 的 46 个 IMPORT_* 提示码全部有中文文案、级别与着色（逐行对照 docs/api-contract.md，只读） */
import { readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { TERM } from '../i18n/statementTerms';
import {
  IMPORT_422_TEXT, IMPORT_CODES, IMPORT_CODE_MAP, IMPORT_TONE, findingText, findingTone, importCodeSpec, renderTemplate, rowTone,
} from './importCodes';

const CONTRACT = readFileSync(resolve(__dirname, '../../../../docs/api-contract.md'), 'utf8');
const CSS = readFileSync(resolve(__dirname, '../styles.css'), 'utf8');
const strip = (s: string) => s.replace(/`/g, '').replace(/\*\*/g, '').trim();

/** 解析 §4.1 表格：| # | code | 级别 | 范围 | 消息模板 | 处理与是否可覆盖 | 测试夹具 | */
function contractRows() {
  const start = CONTRACT.indexOf('### 4.1');
  expect(start).toBeGreaterThan(0);
  const section = CONTRACT.slice(start, CONTRACT.indexOf('\n---', start));
  return section
    .split('\n')
    .filter((l) => /^\|\s*\d+\s*\|\s*`IMPORT_/.test(l))
    .map((l) => {
      const c = l.split('|').slice(1, -1).map((x) => x.trim());
      return { no: Number(c[0]), code: strip(c[1]), severity: c[2], scope: c[3], template: strip(c[4]), handling: strip(c[5]) };
    });
}
const ROWS = contractRows();
const HAN = /[\u4e00-\u9fff]/;

describe('§4.1 IMPORT_* 提示码全覆盖', () => {
  it('契约表共 46 行：21 error + 25 warning；前端表同数且无重复', () => {
    expect(ROWS).toHaveLength(46);
    expect(ROWS.filter((r) => r.severity === 'error')).toHaveLength(21);
    expect(ROWS.filter((r) => r.severity === 'warning')).toHaveLength(25);
    expect(IMPORT_CODES).toHaveLength(46);
    expect(IMPORT_CODE_MAP.size).toBe(46);
  });

  it.each(ROWS.map((r) => [r.code, r] as const))('%s：编号/级别/范围/模板/处理与契约一致', (code, r) => {
    const spec = IMPORT_CODE_MAP.get(code);
    expect(spec, `前端缺少 ${code}`).toBeDefined();
    expect(spec!.no).toBe(r.no);
    expect(spec!.severity).toBe(r.severity);
    expect(spec!.scope).toBe(r.scope);
    expect(spec!.template).toBe(r.template);
    expect(spec!.handling).toBe(r.handling);
  });

  it.each(IMPORT_CODES.map((c) => [c.code, c] as const))('%s：中文短名、着色、needs_action 推导', (_code, c) => {
    expect(c.title).toMatch(HAN);
    expect(c.title.length).toBeLessThanOrEqual(12);
    expect(c.template).toMatch(HAN);
    expect(IMPORT_TONE[c.tone]).toBeDefined();
    if (c.severity === 'error') expect(c.tone).toBe('error');
    else expect(c.tone).not.toBe('error');
    expect(c.needs_action).toBe(/需确认|需选择/.test(c.handling));
    if (c.needs_action) expect(c.tone).toBe('action');
  });

  it('needs_action 共 7 个', () => {
    expect(IMPORT_CODES.filter((c) => c.needs_action)).toHaveLength(7);
  });

  it('每种着色都有图例文案、antd 颜色，且行背景类在 styles.css 中有定义', () => {
    for (const t of Object.values(IMPORT_TONE)) {
      expect(t.label).toMatch(HAN);
      expect(t.tag).toBeTruthy();
      expect(CSS).toContain(`.${t.rowClass} td`);
    }
    expect(IMPORT_TONE.error.tag).toBe('red');
    expect(IMPORT_TONE.action.tag).toBe('orange');
  });

  it('确认写入的 4 个 422 码都有中文说明（且不是 §4.1 提示码）', () => {
    for (const k of ['IMPORT_FILE_ERRORS', 'IMPORT_ROW_ERRORS', 'IMPORT_WARNINGS_UNACKNOWLEDGED', 'IMPORT_NOTHING_TO_COMMIT']) {
      expect(IMPORT_422_TEXT[k]).toMatch(HAN);
      expect(IMPORT_CODE_MAP.has(k)).toBe(false);
    }
  });
});

describe('运行时着色与文案', () => {
  const w = (code: string, needs_action = false, resolution: unknown = null) => ({ code, severity: 'warning' as const, needs_action, resolution, message: '', params: null });
  const actionCode = IMPORT_CODES.find((c) => c.needs_action)!.code;
  const infoCode = IMPORT_CODES.find((c) => c.severity === 'warning' && c.tone === 'info')!.code;

  it('findingTone：error 红；未处理 needs_action 橙；已处理退为金；仅提示为金', () => {
    expect(findingTone({ code: 'IMPORT_EMPTY_FILE', severity: 'error', needs_action: false })).toBe('error');
    expect(findingTone(w(actionCode, true))).toBe('action');
    expect(findingTone(w(actionCode, true, { choice: 'x' }))).toBe('info');
    expect(findingTone(w(infoCode))).toBe('info');
  });

  it('rowTone：错误 > 需处理 > 跳过 > 仅提示 > 无', () => {
    expect(rowTone({ status: 'error', findings: [] })).toBe('error');
    expect(rowTone({ status: 'warning', findings: [w(infoCode), w(actionCode, true)] })).toBe('action');
    expect(rowTone({ status: 'skipped', findings: [w(infoCode)] })).toBe('skip');
    expect(rowTone({ status: 'warning', findings: [w(infoCode)] })).toBe('info');
    expect(rowTone({ status: 'ok', findings: [] })).toBeNull();
  });

  it('未知码兜底：按级别着色、标题含原码', () => {
    const s = importCodeSpec('IMPORT_FUTURE_X', 'error');
    expect(s.tone).toBe('error');
    expect(s.title).toContain('IMPORT_FUTURE_X');
  });

  it('findingText：优先服务端 message，缺省按模板渲染 params，缺参保留占位', () => {
    expect(findingText({ code: 'IMPORT_FILE_TOO_LARGE', severity: 'error', message: '服务端文案', params: null })).toBe('服务端文案');
    expect(findingText({ code: 'IMPORT_FILE_TOO_LARGE', severity: 'error', message: '', params: { limit_mb: 5 } })).toBe('文件超过 5 MB');
    expect(renderTemplate('第 {a} 行 {b}', { a: 3 })).toBe('第 3 行 {b}');
  });
});

describe('仓库扫描 S7：前端源码不出现“像真实交割单表头”的文件', () => {
  it('src/ 下每个文件中字面的交割单表头词少于 3 个（统一引用 i18n/statementTerms 的 TERM）', () => {
    const root = resolve(__dirname, '..');
    const walk = (d: string): string[] => readdirSync(d, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(join(d, e.name)) : [join(d, e.name)]));
    const words = Object.values(TERM);
    const bad = walk(root).filter((f) => words.filter((w) => readFileSync(f, 'utf8').includes(w)).length >= 3);
    expect(bad).toEqual([]);
  });
});
