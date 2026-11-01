import { Tag, Tooltip } from 'antd';
import type { Action, ConsensusStatus, DataStatus, TLeg } from '../api/enums';
import type { Confidence, Gap } from '../api/types';
import { ACTION_COLOR, ACTION_FULL, ACTION_SHORT, CONF_LEVEL, DATA_STATUS, GAP_REASON } from '../i18n/labels';
import { fmtTime } from '../lib/format';

/** 策略 + 动作徽标。措辞为“规则信号/候选”，不是投资建议 */
export function ActionBadge({ action, strategyName, tLeg, size = 'sm' }: { action: Action; strategyName?: string; tLeg?: TLeg | null; size?: 'sm' | 'lg' }) {
  const label = ACTION_SHORT[action] + (tLeg ? (tLeg === 'sell_first' ? '·先卖' : '·先买') : '');
  return (
    <Tooltip title={`${strategyName ? strategyName + '：' : ''}${ACTION_FULL[action]}`}>
      <span className={`action-badge ${size}`} style={{ borderColor: ACTION_COLOR[action], color: ACTION_COLOR[action] }}>
        {strategyName && size === 'sm' ? <i className="sk">{strategyName.slice(0, 2)}</i> : null}
        {label}
      </span>
    </Tooltip>
  );
}

export function ConsensusBadge({ status, actions }: { status: ConsensusStatus; actions?: Partial<Record<Action, number>> }) {
  const parts = Object.entries(actions ?? {}).map(([a, n]) => `${ACTION_SHORT[a as Action]} ${n}`).join(' / ');
  if (status === 'divergent')
    return (
      <Tooltip title={`存在分歧${parts ? '：' + parts : ''}（各策略并列，不合并为单一结论）`}>
        <span className="cons-badge divergent">分歧</span>
      </Tooltip>
    );
  if (status === 'unanimous') return <span className="cons-badge unanimous">一致</span>;
  if (status === 'single') return <span className="cons-badge single">单策略</span>;
  return <span className="cons-badge none">无</span>;
}

export function DataStatusTag({ status, asOf, gaps }: { status: DataStatus; asOf?: string | null; gaps?: Gap[] }) {
  const d = DATA_STATUS[status];
  const tip = [asOf ? `数据时间 ${fmtTime(asOf)}` : null, ...(gaps ?? []).map((g) => `${g.key}：${GAP_REASON[g.reason]} — ${g.message}`)]
    .filter(Boolean)
    .join('\n');
  return (
    <Tooltip title={tip ? <span style={{ whiteSpace: 'pre-line' }}>{tip}</span> : undefined}>
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

export function Loading({ text = '加载中…' }: { text?: string }) {
  return <div className="loading-box">{text}</div>;
}

export function ErrorBox({ error }: { error: unknown }) {
  const e = error as { message?: string; code?: string; requestId?: string | null };
  return (
    <div className="error-box" role="alert">
      加载失败：{e?.message ?? String(error)}
      {e?.code ? <span className="muted mono">（{e.code}{e.requestId ? ` · ${e.requestId}` : ''}）</span> : null}
    </div>
  );
}
