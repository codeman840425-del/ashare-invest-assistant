import { numericRiskRule, validateRiskParams } from '../lib/riskControlParams';
import { useState, useEffect } from 'react';
import { Alert, Button, Checkbox, Input, InputNumber, Select, Tabs, Tag } from 'antd';
import { Link, useSearchParams } from 'react-router';
import type { RiskControlSetting } from '../api/phase2Types';
import { ENUMS } from '../api/enums';
import { useRiskSettings, useSaveRiskSettings, useRiskEvaluation, useRiskEvents } from '../api/phase2Queries';
import { ErrorBox, Loading, DataStatusTag } from '../components/common';
import { RiskFlagView } from '../components/RiskFlagView';
import { EvidenceChips } from '../components/EvidenceChips';
import { CardDisclaimer } from '../components/RiskDisclosure';
import { RISK_CONTROL, GAP_REASON, REGIME } from '../i18n/labels';
import { fmtTime } from '../lib/format';
import { IS_MOCK } from '../lib/env';

const CHECKS = { opposite_side: '方向与计划相反', qty_over_plan: '数量超出计划', held_after_invalidation: '失效后仍持有', buy_without_stop: '未设止损条件', buy_during_wait: '等待期间新增' };
function SettingFields({ value, change }: { value: RiskControlSetting; change: (next: RiskControlSetting) => void }) {
  const decimal = (path: string, label: string, v: string, update: (v: string) => void) => {
    const rule = numericRiskRule(value.control, path);
    return <label style={{ display: 'block', margin: '8px 0' }}>{label}<Input type="number" inputMode="decimal" min={rule.min} max={rule.max} step={1} aria-label={label} value={v} onChange={(e) => update(e.target.value)} style={{ maxWidth: 200, marginLeft: 8 }} /><span className="small muted"> 范围 {rule.min}–{rule.max}；契约默认 {JSON.stringify(rule.defaultValue)}；最多2位小数</span></label>;
  };
  const integer = (path: string, label: string, v: number, update: (v: number) => void) => {
    const rule = numericRiskRule(value.control, path);
    const inactive = value.control === 'loss_streak_drawdown' && path === 'pause_days' && !value.params.pause_on_trigger;
    return <label style={{ display: 'block', margin: '8px 0' }}>{label}<InputNumber aria-label={label} value={v} min={rule.min} max={rule.max} step={1} precision={0} disabled={inactive} onChange={(n) => { if (typeof n === 'number') update(n); }} style={{ marginLeft: 8 }} /><span className="small muted"> 范围 {rule.min}–{rule.max}；契约默认 {rule.defaultValue.toString()}{inactive ? '（当前不生效）' : ''}</span></label>;
  };
  const bool = (label: string, checked: boolean, update: (v: boolean) => void) => <div><Checkbox checked={checked} onChange={(e) => update(e.target.checked)}>{label}</Checkbox></div>;
  switch (value.control) {
    case 'stop_take': return <>{decimal('long_horizon_default_stop_pct', '中长线默认止损比例（%）', value.params.long_horizon_default_stop_pct, (v) => change({ ...value, params: { ...value.params, long_horizon_default_stop_pct: v } }))}{bool('止损止盈限制在涨跌停价格内', value.params.clamp_to_price_limit, (v) => change({ ...value, params: { ...value.params, clamp_to_price_limit: v } }))}</>;
    case 'position_cap': return decimal('single_position_max_pct', '单只仓位上限（%）', value.params.single_position_max_pct, (v) => change({ ...value, params: { single_position_max_pct: v } }));
    case 'total_exposure': return <>{(['uptrend', 'range', 'downtrend'] as const).map((regime) => <div key={regime}>{([0, 1] as const).map((i) => decimal(`regime_ranges.${regime}`, `${REGIME[regime]}参考仓位${i === 0 ? '下限' : '上限'}（%）`, value.params.regime_ranges[regime][i], (v) => {
      const pair: [string, string] = [...value.params.regime_ranges[regime]]; pair[i] = v;
      change({ ...value, params: { ...value.params, regime_ranges: { ...value.params.regime_ranges, [regime]: pair } } });
    }))}</div>)}{integer('regime_confirm_days', '大盘环境确认天数', value.params.regime_confirm_days, (v) => change({ ...value, params: { ...value.params, regime_confirm_days: v } }))}</>;
    case 'sector_concentration': return <>{decimal('sw_l1_max_pct', '申万一级行业上限（%）', value.params.sw_l1_max_pct, (v) => change({ ...value, params: { ...value.params, sw_l1_max_pct: v } }))}{decimal('concept_max_pct', '概念集中度上限（%）', value.params.concept_max_pct, (v) => change({ ...value, params: { ...value.params, concept_max_pct: v } }))}</>;
    case 'loss_streak_drawdown': return <>{integer('closed_loss_streak', '已平仓连续亏损笔数', value.params.closed_loss_streak, (v) => change({ ...value, params: { ...value.params, closed_loss_streak: v } }))}{decimal('drawdown_from_peak_pct', '账户高点回撤（%）', value.params.drawdown_from_peak_pct, (v) => change({ ...value, params: { ...value.params, drawdown_from_peak_pct: v } }))}{integer('strategy_sim_fail_streak', '策略模拟连续失败次数', value.params.strategy_sim_fail_streak, (v) => change({ ...value, params: { ...value.params, strategy_sim_fail_streak: v } }))}{bool('触发时暂停', value.params.pause_on_trigger, (v) => change({ ...value, params: { ...value.params, pause_on_trigger: v } }))}{integer('pause_days', '暂停交易日数', value.params.pause_days, (v) => change({ ...value, params: { ...value.params, pause_days: v } }))}</>;
    case 'plan_violation': return <>{Object.entries(CHECKS).map(([key, label]) => <div key={key}><Checkbox checked={value.params.checks.includes(key)} onChange={(e) => change({ ...value, params: { checks: e.target.checked ? [...value.params.checks, key] : value.params.checks.filter((x) => x !== key) } })}>{label}</Checkbox></div>)}</>;
  }
}
function SettingCard({ item }: { item: RiskControlSetting }) {
  const [draft, setDraft] = useState(item);
  const save = useSaveRiskSettings();
  const issues = validateRiskParams(draft);
  const [systemDefault, setSystemDefault] = useState<RiskControlSetting | null>(() => item.source === 'system' ? structuredClone(item) : null);
  useEffect(() => { setDraft(item); if (item.source === 'system') setSystemDefault(structuredClone(item)); }, [item]);
  const edit = (next: RiskControlSetting) => { save.reset(); setDraft(next); };
  return <section className="panel" style={{ padding: 16 }} data-testid={`risk-setting-${item.control}`}>
    <h3>{RISK_CONTROL[item.control]} <Tag>{item.source === 'system' ? '系统有效值' : '本人覆盖值'}</Tag></h3>
    <fieldset disabled={save.isPending} style={{ border: 0, padding: 0 }}>
      <Checkbox checked={draft.enabled} onChange={(e) => edit({ ...draft, enabled: e.target.checked })}>启用 {RISK_CONTROL[item.control]}</Checkbox>
      {item.control === 'stop_take' && !draft.enabled ? <Alert type="warning" title="已关闭止损止盈风控；不再施加该项门控，请自行核实计划条件。" /> : null}
      <SettingFields value={draft} change={edit} />
      <Button loading={save.isPending} disabled={issues.length > 0} onClick={() => { if (!issues.length) save.mutate(draft); }}>保存 {RISK_CONTROL[item.control]}</Button>
      <Button disabled={systemDefault === null} onClick={() => { if (systemDefault) edit(structuredClone(systemDefault)); }}>恢复默认 {RISK_CONTROL[item.control]}</Button>
      {systemDefault === null ? <p className="muted small">本次读取未返回该项系统默认值，无法恢复；不以契约参考值冒充当前系统值。</p> : null}
      {issues.length ? <div role="alert" data-testid={`risk-param-errors-${item.control}`}>{issues.map((issue) => <p key={issue.field + issue.kind}><code>{issue.field}</code>：{issue.message}</p>)}</div> : null}
    </fieldset>
    {save.isError ? <ErrorBox error={save.error} prefix="设置未保存" /> : null}
    {save.isSuccess ? <Alert type="success" title="设置已保存（以服务端响应为准）" /> : null}
  </section>;
}
function SettingsPanel() {
  const settings = useRiskSettings();
  if (settings.isPending) return <Loading />;
  if (settings.isError) return <ErrorBox error={settings.error} />;
  return <div className="stock-grid">{settings.data.map((s) => <SettingCard key={s.control} item={s} />)}</div>;
}
const STATE = { ok: '输入齐全，未触发', triggered: '已触发', unknown: '未知（输入不足）', disabled: '已关闭（不施加门控）' };
function EvaluationPanel({ initialCode }: { initialCode: string }) {
  const [draft, setDraft] = useState(initialCode);
  const [code, setCode] = useState(initialCode);
  const q = useRiskEvaluation(code);
  return <section className="panel" style={{ padding: 16 }} data-testid="risk-evaluation">
    <h3>当前缓存评价（不回写历史日报或候选信号）</h3>
    <Input aria-label="风控评价证券代码" placeholder="证券代码，如 600000.SH" value={draft} onChange={(e) => setDraft(e.target.value)} style={{ maxWidth: 260 }} />
    <Button onClick={() => { const next = draft.trim().toUpperCase(); if (next === code) void q.refetch(); else setCode(next); }} disabled={!draft.trim()}>读取当前评价</Button>
    {q.isFetching ? <Loading /> : null}{q.isError ? <ErrorBox error={q.error} /> : null}
    {q.data && !q.isError ? <><p>{q.data.name} · {q.data.security_code} · 评价时间 {fmtTime(q.data.evaluated_at)} · 快照 {q.data.snapshot_id ?? '—（完全无数据）'}</p><DataStatusTag status={q.data.data_status} />
      {q.data.controls.map((c) => <div className="stc-sec" key={c.control} data-testid={`risk-state-${c.control}`}><b>{RISK_CONTROL[c.control]}</b> · {STATE[c.state]}
        {c.control === 'total_exposure' && c.state === 'unknown' ? <p>大盘环境未知；不以卡片指数环境替代，不施加 RC3 门控。</p> : null}
        {c.flags.map((flag, i) => <RiskFlagView key={i} flag={flag} evidence={q.data?.evidence ?? []} />)}
        {(['position_cap', 'sector_concentration'] as const).some((key) => key === c.control) && (c.state === 'unknown' || c.flags.some((f) => f.quantity_cap === null)) ? <p>可新增数量：—（额度未知，不代表0或无限额度）</p> : null}
        {c.gaps.map((g, i) => <p className="small" key={`${g.key}-${i}`}>缺口 · {GAP_REASON[g.reason]}：{g.message}</p>)}
      </div>)}
    </> : null}
  </section>;
}
function EventsPanel() {
  const [params] = useSearchParams();
  const [status, setStatus] = useState('active'); const [control, setControl] = useState('');
  const [code, setCode] = useState(params.get('security_code') ?? ''); const [since, setSince] = useState('');
  const events = useRiskEvents(status, control, code, since);
  const items = events.data?.pages.flatMap((p) => p.items) ?? [];
  const target = params.get('event');
  return <section className="panel" style={{ padding: 16 }} data-testid="risk-events">
    <h3>风控事件（只读）</h3>
    <Select aria-label="风控事件状态" value={status} onChange={setStatus} options={[{ value: 'active', label: '未解除' }, { value: 'cleared', label: '已解除' }, { value: '', label: '全部' }]} style={{ width: 140 }} />
    <Select aria-label="风控事件类型" value={control} onChange={setControl} options={[{ value: '', label: '全部风控' }, ...ENUMS.risk_control.map((value) => ({ value, label: RISK_CONTROL[value] }))]} style={{ width: 200 }} />
    <Input aria-label="风控事件证券代码" value={code} onChange={(e) => setCode(e.target.value.trim().toUpperCase())} placeholder="全部证券" style={{ maxWidth: 180 }} />
    <Input aria-label="风控事件起始时间" value={since} onChange={(e) => setSince(e.target.value)} placeholder="ISO 日期时间（可选）" style={{ maxWidth: 240 }} />
    {events.isPending ? <Loading /> : null}{events.isError ? <ErrorBox error={events.error} /> : null}
    {events.isSuccess && !items.length ? <p>暂无符合条件的风控事件；不是“风险为零”。</p> : null}
    {target && events.isSuccess && !items.some((e) => e.id === target) ? <p>定位事件不在已加载列表，请调整筛选或加载更多。</p> : null}
    {items.map((e) => <article key={e.id} id={`risk-event-${e.id}`} className="stc-sec" data-testid={`risk-event-${e.id}`}>
      <h4>{e.name ?? '账户 / 策略项'} · {e.status === 'active' ? '未解除' : '已解除'}{target === e.id ? <Tag>当前定位事件</Tag> : null}</h4>
      <p>触发 {fmtTime(e.triggered_at)} · 解除 {e.cleared_at === null ? '—' : fmtTime(e.cleared_at)}</p>
      <RiskFlagView flag={e} evidence={e.evidence} /><EvidenceChips ids={e.evidence_ids} evidence={e.evidence} />
      {e.suggestion_id ? <Link to={`/suggestions/${e.suggestion_id}`}>查看生成时的候选信号</Link> : null}
    </article>)}
    <Button disabled={!events.hasNextPage || events.isFetchingNextPage || events.isError} loading={events.isFetchingNextPage} onClick={() => void events.fetchNextPage()}>加载更多事件</Button>
  </section>;
}
export function RiskControlsPage() {
  const [params, setParams] = useSearchParams(); const tab = params.get('tab') === 'events' ? 'events' : 'settings';
  return <div className="page-scroll"><div className="page" data-testid="risk-controls-page">
    <h2 className="page-title">风控设置与事件</h2>
    {IS_MOCK ? <Alert type="info" title="示例数据 · mock 阶段，未联调后端；合成评价不进行真实风控求值" /> : null}
    <CardDisclaimer />
    <Tabs activeKey={tab} onChange={(next) => { const updated = new URLSearchParams(params); updated.set('tab', next); setParams(updated); }} items={[
      { key: 'settings', label: '有效设置与当前评价', children: <><SettingsPanel /><EvaluationPanel initialCode={params.get('security_code') ?? ''} /></> },
      { key: 'events', label: '事件', children: <EventsPanel /> },
    ]} />
  </div></div>;
}
