/**
 * Mock 字段校验：示例数据的字段名必须与契约 v0.2.x（前端当前对齐 v0.2.7，docs/api-contract.md，只读）逐字一致（对齐版本见 api/enums.ts CONTRACT_VERSION）。
 * 字段清单直接从契约文本解析（§5.1 内联结构、§5.2 字段表、StrategyConclusion / DimensionCell / DailyReport 定义），
 * 契约改动后这里会第一时间失败。
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { CONTRACT_VERSION, ENUMS, REASON_CODES } from '../api/enums';
import type { Evidence, Suggestion } from '../api/types';
import {
  CANDIDATE_SIGNALS, DAILY_REPORTS, HORIZON_ASSESSMENTS, COUNTED_ROLES, NOTIFICATIONS, REASONS, SIGNAL_EVENTS, SUGGESTIONS, SUGGESTION_LIST, TERMINAL_ROWS, WATCHLIST,
  dailyBars, intradayBars, isDivergent, SECURITY_CODES,
} from './fixtures';
import { minuteEnds } from '../lib/market';

const CONTRACT = readFileSync(resolve(__dirname, '../../../../docs/api-contract.md'), 'utf8');

/** 解析 `{a: T, b, c: {..} | null}` 的顶层键名 */
function topKeys(src: string): string[] {
  const start = src.indexOf('{');
  const keys: string[] = [];
  let depth = 0;
  let cur = '';
  for (let i = start; i < src.length; i++) {
    const c = src[i];
    if ('{[('.includes(c)) {
      depth++;
      if (depth === 1) continue;
    }
    if ('}])'.includes(c)) {
      depth--;
      if (depth === 0) {
        keys.push(cur);
        break;
      }
    }
    if (depth === 1 && c === ',') {
      keys.push(cur);
      cur = '';
      continue;
    }
    if (depth >= 1) cur += c;
  }
  return keys
    .map((k) => k.trim().replace(/\\$/, '').split(/[:\s（]/)[0].trim())
    .filter(Boolean)
    .flatMap((k) => (k === 'DataStatusBlock' ? ['data_status', 'data_as_of', 'gaps'] : [k]));
}
function inlineShape(name: string): string[] {
  const line = CONTRACT.split('\n').find((l) => l.startsWith(`| \`${name}\` |`) && l.includes('`{'));
  if (!line) throw new Error(`契约中未找到 ${name} 的内联结构`);
  return topKeys(line.slice(line.indexOf('`{') + 1));
}
function proseShape(prefix: string): string[] {
  const line = CONTRACT.split('\n').find((l) => l.startsWith(prefix));
  if (!line) throw new Error(`契约中未找到 ${prefix}`);
  return topKeys(line.slice(line.indexOf('`{') + 1));
}
function tableFields(heading: string): string[] {
  const lines = CONTRACT.split('\n');
  const i = lines.findIndex((l) => l.startsWith(heading));
  const out: string[] = [];
  for (let j = i + 3; j < lines.length && lines[j].startsWith('|'); j++) {
    const first = lines[j].split('|')[1];
    for (const m of first.matchAll(/`([a-z_]+)`/g)) out.push(m[1]);
  }
  return out;
}
const sorted = (a: Iterable<string>) => [...a].sort();
const keysOf = (o: object) => sorted(Object.keys(o));

describe(`契约 ${CONTRACT_VERSION} 字段解析自检`, () => {
  it('能从契约解析出关键结构', () => {
    expect(inlineShape('TerminalRow')).toContain('active_reason_count');
    expect(tableFields('### 5.2')).toContain('dimension_matrix');
  });
});

describe(`Mock 字段与契约 ${CONTRACT_VERSION} 逐字一致`, () => {
  const sg = SUGGESTIONS[0];
  const st = sg.strategies[0];
  const cases: [string, () => object[]][] = [
    ['TerminalRow', () => TERMINAL_ROWS],
    ['SuggestionSummary', () => TERMINAL_ROWS.flatMap((r) => (r.suggestion ? [r.suggestion] : []))],
    ['Notification', () => NOTIFICATIONS],
    ['SignalEvent', () => SIGNAL_EVENTS],
    ['WatchlistItem', () => WATCHLIST.items],
    ['Stops', () => SUGGESTIONS.flatMap((s) => s.strategies.map((x) => x.stops))],
    ['RiskFlag', () => SUGGESTIONS.flatMap((s) => s.risk_flags)],
    ['TextWithEvidence', () => SUGGESTIONS.flatMap((s) => s.strategies.flatMap((x) => [...x.reasons, ...x.counter_evidence, ...x.invalidation]))],
    ['RuleRef', () => SUGGESTIONS.flatMap((s) => s.strategies.flatMap((x) => x.rule_refs))],
    ['Bar', () => [...(dailyBars(SECURITY_CODES[0])?.items ?? []), ...(intradayBars(SECURITY_CODES[0])?.items ?? [])]],
    ['ReleaseCondition', () => REASONS.map((r) => r.release_condition)],
  ];
  // v0.2.7 在说明文字里给对象加的字段（不在花括号结构内），逐条核对说明原文后并入期望集合
  const PROSE_ADDED: Record<string, string[]> = {
    Bar: ['is_final'],
    // §7.11.4 aggregation/version amendments extend the older §5.1 inline shape.
    Notification: ['merged_count', 'refs', 'updated_at', 'version'],
  };
  it('Notification includes the four explicit §7.11.4 contract amendments', () => {
    expect(CONTRACT).toContain('`Notification` 追加 `merged_count: int`');
    expect(CONTRACT).toContain('`updated_at: datetime`');
    expect(CONTRACT).toContain('`refs: [{type, id, at}]`');
    expect(CONTRACT).toContain('`Notification` 追加 `version: int`');
    expect(sorted([...inlineShape('Notification'), ...PROSE_ADDED.Notification])).toEqual([
      'body', 'created_at', 'id', 'kind', 'merged_count', 'name', 'read_at',
      'refs', 'security_code', 'severity', 'target', 'title', 'updated_at', 'version',
    ]);
  });
  it('v0.2.7：Bar 的 is_final 来自说明原文', () => {
    expect(CONTRACT).toContain('v0.2.7 加 `is_final: boolean`');
  });
  it.each(cases)('%s', (name, get) => {
    const expected = sorted([...inlineShape(name), ...(PROSE_ADDED[name] ?? [])]);
    const items = get();
    expect(items.length).toBeGreaterThan(0);
    for (const it of items) expect(keysOf(it)).toEqual(expected);
  });

  it('Evidence（provider 按 §3 data_provider，见遗留问题 #1）', () => {
    const line = CONTRACT.split('\n').find((l) => l.startsWith('| `Evidence` |'))!;
    const expected = sorted(topKeys(line.slice(line.indexOf('结构 `{') + 3)));
    const all: Evidence[] = [...SUGGESTIONS.flatMap((s) => s.evidence), ...DAILY_REPORTS.flatMap((d) => d.evidence)];
    for (const e of all) {
      expect(keysOf(e)).toEqual(expected);
      expect(ENUMS.data_provider).toContain(e.provider);
      expect(ENUMS.epistemic_type).toContain(e.epistemic_type);
    }
  });

  it('Suggestion（§5.2 字段表）', () => {
    const expected = sorted(tableFields('### 5.2'));
    for (const s of SUGGESTIONS) expect(keysOf(s)).toEqual(expected);
  });

  it('StrategyConclusion / DimensionCell', () => {
    const sc = sorted(proseShape('`StrategyConclusion`'));
    // v0.2.4 #10 已修正 DimensionCell 的 `}` 笔误：exit_hits / exit_total 与 rules_* 同属一个对象
    const dc = sorted(proseShape('`DimensionCell`'));
    expect(dc).toEqual(expect.arrayContaining(['exit_hits', 'exit_total']));
    for (const s of SUGGESTIONS) {
      for (const x of s.strategies) expect(keysOf(x)).toEqual(sc);
      for (const row of s.dimension_matrix) for (const c of row.cells) expect(keysOf(c)).toEqual(dc);
    }
    expect(st).toBeDefined();
  });

  it('DailyReport（§5.3）', () => {
    const lines = CONTRACT.split('\n');
    const i = lines.findIndex((l) => l.startsWith('### 5.3'));
    const def = lines.slice(i).find((l) => l.startsWith('`{date'))!;
    const expected = sorted(topKeys(def));
    for (const d of DAILY_REPORTS) expect(keysOf(d)).toEqual(expected);
  });
});

describe('Mock 业务一致性', () => {
  const inEnum = (k: keyof typeof ENUMS, v: string) => expect(ENUMS[k] as readonly string[]).toContain(v);

  it('枚举取值全部在契约 §3 内', () => {
    for (const s of SUGGESTIONS) {
      inEnum('suggestion_status', s.status);
      inEnum('consensus_status', s.consensus.status);
      inEnum('executability_status', s.executability.status);
      for (const x of s.strategies) {
        inEnum('action', x.action);
        inEnum('strategy_eval_state', x.state);
        inEnum('horizon', x.horizon);
        for (const v of x.dimension_views) { inEnum('dimension', v.dimension); inEnum('dimension_view', v.view); }
        for (const m of x.model_refs) expect(m.role).toBe('auxiliary');
      }
    }
    for (const n of NOTIFICATIONS) { inEnum('notification_kind', n.kind); inEnum('severity', n.severity); inEnum('notification_target_type', n.target.type); }
    for (const e of SIGNAL_EVENTS) inEnum('signal_kind', e.kind);
    for (const c of CANDIDATE_SIGNALS) inEnum('candidate_signal_state', c.state);
    for (const r of REASONS) { expect(REASON_CODES as readonly string[]).toContain(r.code); inEnum('reason_status', r.status); inEnum('release_kind', r.release_condition.kind); }
  });

  it('P1 可解释性：rule_refs / evidence / counter_evidence / invalidation 非空，evidence_ids 全部可解析', () => {
    const check = (s: Suggestion) => {
      const ids = new Set(s.evidence.map((e) => e.id));
      expect(s.evidence.length).toBeGreaterThan(0);
      for (const x of s.strategies) {
        expect(x.rule_refs.length).toBeGreaterThan(0);
        expect(x.counter_evidence.length).toBeGreaterThan(0);
        expect(x.invalidation.length).toBeGreaterThan(0);
        for (const t of [...x.reasons, ...x.counter_evidence, ...x.invalidation]) for (const id of t.evidence_ids) expect(ids).toContain(id);
        for (const r of x.rule_refs) for (const id of r.evidence_ids) expect(ids).toContain(id);
      }
      for (const row of s.dimension_matrix) for (const c of row.cells) for (const id of c.key_evidence_ids) expect(ids).toContain(id);
    };
    SUGGESTIONS.forEach(check);
  });

  it('v0.2.2：RuleRef.passed 三值；DimensionCell 只统计 entry/filter/hold 且 passed = true', () => {
    expect(CONTRACT).toMatch(/passed: boolean \\?\| null/);
    const counted = new Set(['entry', 'filter', 'hold']);
    for (const s of SUGGESTIONS) {
      for (const row of s.dimension_matrix) {
        for (const c of row.cells) {
          const x = s.strategies.find((st) => st.strategy_version_id === c.strategy_version_id)!;
          const rules = x.dimension_views.find((v) => v.dimension === row.dimension)!.rules;
          for (const r of rules) expect([true, false, null]).toContain(r.passed);
          const ok = rules.filter((r) => counted.has(r.role) && r.passed === true);
          expect(c.rules_total).toBe(rules.filter((r) => counted.has(r.role)).length);
          expect(c.rules_passed).toBe(ok.length);
          expect(c.key_evidence_ids).toEqual(ok.flatMap((r) => r.evidence_ids).slice(0, 3));
          expect(c.key_evidence_ids.length).toBeLessThanOrEqual(3);
        }
      }
    }
  });

  it('前端对齐的契约版本是契约里真实存在的版本，且不高于契约当前版本', () => {
    // 契约升版（如 v0.2.7 只新增端点/字段）时前端可能尚未对齐：此处只要求 CONTRACT_VERSION 有对应变更记录、不超前；
    // 是否已对齐到最新版由前端任务跟踪（见 /workspace/team/reports），不在这里让 CI 因 docs 升版而失败。
    const ver = (v: string) => v.replace(/^v/, '').split('.').map(Number);
    const cmp = (a: string, b: string) => {
      const [x, y] = [ver(a), ver(b)];
      for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] - y[i];
      return 0;
    };
    expect(CONTRACT_VERSION).toMatch(/^v\d+\.\d+\.\d+$/);
    expect(CONTRACT).toContain(`### ${CONTRACT_VERSION}（`);
    const current = /版本：\*\*(v\d+\.\d+\.\d+)\*\*/.exec(CONTRACT)?.[1];
    expect(current).toBeTruthy();
    expect(cmp(CONTRACT_VERSION, current!)).toBeLessThanOrEqual(0);
  });

  it('v0.2.3：/horizon-assessments 字段、四周期分数非空、每周期 2–4 条理由、证据可解析、缺数据封顶', () => {
    const line = CONTRACT.split('\n').find((l) => l.includes('`/horizon-assessments?security_code=`'))!;
    const shape = line.slice(line.indexOf('周期分类结果'));
    const HZ_KEYS = ['suitable', 'scores', 'reasons', 'inputs_missing', 'caps', 'hints', 'classifier_version', 'snapshot_id', 'evidence'];
    expect(sorted(topKeys(shape))).toEqual(sorted(HZ_KEYS));
    expect(sorted(topKeys(shape.slice(shape.indexOf('scores:') + 7)))).toEqual(sorted(ENUMS.horizon));
    expect(Object.keys(HORIZON_ASSESSMENTS)).toHaveLength(SUGGESTIONS.length);
    let capped = 0;
    for (const s of SUGGESTIONS) {
      const a = HORIZON_ASSESSMENTS[s.security_code];
      expect(keysOf(a)).toEqual(sorted(HZ_KEYS));
      expect(a.classifier_version).toMatch(/^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/);
      expect(a.inputs_missing).toEqual([...new Set(a.inputs_missing)].sort());
      for (const c of a.caps) expect(a.scores[c.horizon]).toBeLessThanOrEqual(c.cap);
      expect(keysOf(a.scores)).toEqual(sorted(ENUMS.horizon));
      expect(a.suitable).toEqual(s.horizon_assessment.suitable);
      // v0.2.3：只在本响应的 evidence[] 内解析
      const ids = new Set(a.evidence.map((e) => e.id));
      for (const h of ENUMS.horizon) {
        expect(Number.isInteger(a.scores[h])).toBe(true);
        expect(a.scores[h]).toBeGreaterThanOrEqual(0);
        expect(a.scores[h]).toBeLessThanOrEqual(100);
        const rs = a.reasons.filter((r) => r.horizon === h);
        expect(rs.length).toBeGreaterThanOrEqual(2);
        expect(rs.length).toBeLessThanOrEqual(4);
      }
      for (const r of a.reasons) {
        expect(keysOf(r)).toEqual(sorted(['text', 'expr', 'evidence_ids', 'horizon', 'polarity']));
        expect(['for', 'against']).toContain(r.polarity);
        for (const id of r.evidence_ids) expect(ids).toContain(id);
      }
      if (a.inputs_missing.length) {
        capped++;
        expect(a.inputs_missing.every((k) => k.startsWith('f.'))).toBe(true);
        expect(a.scores.long).toBeLessThanOrEqual(59);
      }
    }
    expect(capped).toBeGreaterThan(0);
  });

  it('v0.2.6 T006e：caps[].kind 只有 gate / data_missing；LG0 记 data_missing；IT0 与画像类规则不进 caps', () => {
    const line = CONTRACT.split('\n').find((l) => l.startsWith('| `HorizonCap` |'))!;
    expect(line).toContain('kind: "gate" \\| "data_missing"');
    const all = Object.values(HORIZON_ASSESSMENTS).flatMap((a) => a.caps);
    for (const c of all) {
      expect(['gate', 'data_missing']).toContain(c.kind);
      expect(['IT0', 'SH0', 'SH0B', 'SH0C', 'IT0B', 'IT0C']).not.toContain(c.rule_id);
      if (c.kind === 'gate') expect(c.rule_id).toMatch(/^HG[1-6]$/);
    }
    expect(all.some((c) => c.kind === 'data_missing' && c.rule_id === 'LG0' && c.inputs_missing.length === 0)).toBe(true);
  });

  it('v0.2.2 G-01：停牌/一字涨停等可执行性原因只进 gate_results 与不可执行原因，策略状态不改为 vetoed', () => {
    const gateCodes = new Set(['SUSPENDED', 'LIMIT_LOCKED']);
    for (const cs of CANDIDATE_SIGNALS) {
      const codes = REASONS.filter((r) => cs.reason_ids.includes(r.id)).map((r) => r.code as string);
      if (!codes.some((c) => gateCodes.has(c))) continue;
      expect(cs.gate_results.find((g) => g.gate === 'gate_tradability')?.passed).toBe(false);
      const sg = SUGGESTIONS.find((s) => s.candidate_signal_ids.includes(cs.id))!;
      const st = sg.strategies.find((x) => x.candidate_signal_id === cs.id)!;
      expect(st.state).not.toBe('vetoed');
    }
  });

  it('v0.2.2 P1b：有计划草稿的候选信号必有 role ∈ {entry, exit, weakening} 且 passed = true 的规则', () => {
    for (const cs of CANDIDATE_SIGNALS) {
      if (!cs.plan_draft_ids.length) continue;
      expect(cs.rule_refs.some((r) => ['entry', 'exit', 'weakening'].includes(r.role) && r.passed === true)).toBe(true);
    }
    expect([...COUNTED_ROLES].sort()).toEqual(['entry', 'filter', 'hold']);
  });

  it('v0.2.3 #11：行级 divergent 当且仅当同时存在 bullish 与 bearish（neutral/unknown 不参与）', () => {
    expect(isDivergent(['bullish', 'neutral'])).toBe(false);
    expect(isDivergent(['bullish', 'unknown', 'neutral'])).toBe(false);
    expect(isDivergent(['bullish', 'bearish'])).toBe(true);
    expect(isDivergent(['bearish', 'neutral', 'bullish'])).toBe(true);
  });

  it('v0.2.3 #20：exit_hits/exit_total 只统计 weakening/exit 且已求值的规则', () => {
    for (const s of SUGGESTIONS) {
      for (const row of s.dimension_matrix) {
        for (const c of row.cells) {
          const x = s.strategies.find((st) => st.strategy_version_id === c.strategy_version_id)!;
          const rules = x.dimension_views.find((v) => v.dimension === row.dimension)!.rules.filter((r) => ['weakening', 'exit'].includes(r.role) && r.passed !== null);
          expect(c.exit_total).toBe(rules.length);
          expect(c.exit_hits).toBe(rules.filter((r) => r.passed === true).length);
        }
      }
    }
  });

  it('v0.2.3 #15：RuleRef.dimension 必填', () => {
    for (const cs of CANDIDATE_SIGNALS) for (const r of cs.rule_refs) expect(ENUMS.dimension).toContain(r.dimension);
    for (const s of SUGGESTIONS) for (const x of s.strategies) for (const r of x.rule_refs) expect(ENUMS.dimension).toContain(r.dimension);
  });

  it('v0.2.3 #3：日报逐股含 close/change_pct/data_status/max_risk_level', () => {
    for (const st of DAILY_REPORTS[0].stocks) {
      expect(ENUMS.data_status).toContain(st.data_status);
      expect(st.max_risk_level === null || ENUMS.risk_level.includes(st.max_risk_level)).toBe(true);
      expect(st.close === null || /^-?\d+\.\d{2}$/.test(st.close)).toBe(true);
    }
  });

  it('矩阵 divergent 与各策略维度观点一致；共识计数与动作一致', () => {
    for (const s of SUGGESTIONS) {
      expect(s.dimension_matrix.map((r) => r.dimension)).toEqual([...ENUMS.dimension]);
      for (const row of s.dimension_matrix) {
        expect(row.cells).toHaveLength(s.strategies.length);
        expect(row.divergent).toBe(isDivergent(row.cells.map((c) => c.view)));
      }
      const counts: Record<string, number> = {};
      for (const x of s.strategies) counts[x.action] = (counts[x.action] ?? 0) + 1;
      expect(s.consensus.actions).toEqual(counts);
      // v0.2.3 #11：按 (action, t_leg) 判断是否全部相同
      const distinct = new Set(s.strategies.map((x) => `${x.action}|${x.t_leg ?? ''}`)).size;
      expect(s.consensus.status).toBe(s.strategies.length === 0 ? 'none' : s.strategies.length === 1 ? 'single' : distinct === 1 ? 'unanimous' : 'divergent');
    }
  });

  it('可执行性：blocked 必有活跃不可执行原因，reason_ids 均能在 /non-executable-reasons 中找到', () => {
    const ids = new Set(REASONS.map((r) => r.id));
    for (const s of SUGGESTIONS) {
      for (const id of s.executability.reason_ids) expect(ids).toContain(id);
      if (s.executability.status === 'blocked') expect(s.executability.reason_ids.length).toBeGreaterThan(0);
      expect(new Set([...s.executability.executable_signal_ids, ...s.executability.blocked_signal_ids])).toEqual(new Set(s.candidate_signal_ids));
    }
  });

  it('终端行的 suggestion 摘要与 /suggestions 列表一致', () => {
    for (const r of TERMINAL_ROWS) {
      if (!r.suggestion) continue;
      const li = SUGGESTION_LIST.find((x) => x.id === r.suggestion!.id)!;
      expect(li.security_code).toBe(r.security_code);
      expect({ ...li, security_code: undefined, name: undefined }).toMatchObject(r.suggestion);
    }
  });

  it('K 线：日 K 日期升序、OHLC 自洽；分时最多 240 根且时间落在交易分钟内', () => {
    const d = dailyBars(SECURITY_CODES[0])!;
    const bars = d.items;
    for (let i = 1; i < bars.length; i++) expect(bars[i].t > bars[i - 1].t).toBe(true);
    for (const b of bars) {
      const [o, h, l, c] = [b.open, b.high, b.low, b.close].map(Number);
      expect(h).toBeGreaterThanOrEqual(Math.max(o, c));
      expect(l).toBeLessThanOrEqual(Math.min(o, c));
    }
    const m = intradayBars(SECURITY_CODES[0])!;
    expect(m.items.length).toBeLessThanOrEqual(240);
    const allowed = new Set(minuteEnds());
    for (const b of m.items) expect(allowed).toContain(b.t.slice(11, 16));
  });

  it('通知 target.route 只指向已实现或占位的站内路由', () => {
    for (const n of NOTIFICATIONS) {
      if (n.target.route) expect(n.target.route.startsWith('/')).toBe(true);
      if (n.target.type === 'none') expect(n.target.route).toBeNull();
    }
  });

  it('示例数据标注“示例”', () => {
    const text = JSON.stringify({ SUGGESTIONS, NOTIFICATIONS, DAILY_REPORTS });
    expect(text).toContain('示例');
  });
});
