import { Tag, Tooltip } from 'antd';
import type { Action, Confidence, DataStatus, Suggestion } from '../types/contract';
import { ACTION_COLOR, ACTION_FULL, ACTION_SHORT, CONF_LEVEL, DATA_STATUS } from '../labels';
import { STRATEGIES } from '../mock/data';

export function ActionBadge({ action, strategyKey, tLeg, size = 'sm' }: { action: Action; strategyKey?: string; tLeg?: string | null; size?: 'sm' | 'lg' }) {
  const name = strategyKey ? STRATEGIES[strategyKey]?.name : undefined;
  const label = ACTION_SHORT[action] + (tLeg ? (tLeg === 'sell_first' ? '·先卖' : '·先买') : '');
  return (
    <Tooltip title={`${name ? name + '：' : ''}${ACTION_FULL[action]}`}>
      <span className={`action-badge ${size}`} style={{ borderColor: ACTION_COLOR[action], color: ACTION_COLOR[action] }}>
        {name && size === 'sm' ? <i className="sk">{name.slice(0, 2)}</i> : null}
        {label}
      </span>
    </Tooltip>
  );
}

export function ConsensusBadge({ consensus }: { consensus: Suggestion['consensus'] }) {
  const parts = Object.entries(consensus.actions).map(([a, n]) => `${ACTION_SHORT[a as Action]} ${n}`).join(' / ');
  if (consensus.status === 'divergent')
    return (
      <Tooltip title={`存在分歧：${parts}（各策略并列，不合并为单一结论）`}>
        <span className="cons-badge divergent">分歧</span>
      </Tooltip>
    );
  if (consensus.status === 'unanimous') return <span className="cons-badge unanimous">一致</span>;
  if (consensus.status === 'single') return <span className="cons-badge single">单策略</span>;
  return <span className="cons-badge none">无</span>;
}

export function DataStatusTag({ status, asOf }: { status: DataStatus; asOf?: string }) {
  const d = DATA_STATUS[status];
  return (
    <Tooltip title={asOf ? `数据时间 ${fmtTime(asOf)}` : undefined}>
      <span className="ds-tag" style={{ color: d.color }}>
        <span className="dot" style={{ background: d.color }} />
        {d.text}
      </span>
    </Tooltip>
  );
}

export function ConfidenceTag({ c }: { c: Confidence }) {
  const l = CONF_LEVEL[c.level];
  return (
    <span className="conf-tag">
      <Tag color={l.color} variant="outlined" style={{ marginInlineEnd: 4 }}>置信度 {l.text}</Tag>
      <span className="num">{c.value.toFixed(2)}</span>
    </span>
  );
}

export const fmtTime = (t: string) => t.replace('T', ' ').replace(/\+08:00$/, '').replace(/:00$/, '');
export const fmtNum = (v: string | number, digits = 2) =>
  Number(v).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
export const pctClass = (v: string | number) => (Number(v) > 0 ? 'up' : Number(v) < 0 ? 'down' : 'flat');
export const signed = (v: string | number, digits = 2) => (Number(v) > 0 ? '+' : '') + fmtNum(v, digits);

export function SampleWatermark() {
  return <div className="watermark" aria-hidden>示例数据</div>;
}
