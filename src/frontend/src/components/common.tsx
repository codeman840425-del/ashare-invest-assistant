import { Tag, Tooltip } from 'antd';
import { Link } from 'react-router';
import { ApiError } from '../api/client';
import { errorText } from '../api/errorPolicy';
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

/** 按错误码显示中文文案（评审 M2）；附错误码与 request_id 便于排查 */
export function ErrorBox({ error, prefix = '加载失败' }: { error: unknown; prefix?: string }) {
  const e = error instanceof ApiError ? error : null;
  const fresh = e?.code === 'FRESH_DATA_REQUIRED';
  return (
    <div className={`error-box${fresh ? ' refreshing' : ''}`} role="alert" data-code={e?.code}>
      {fresh ? '' : `${prefix}：`}{errorText(error)}
      {e?.code === 'CONSENT_REQUIRED' ? <> <Link to="/onboarding">去完成 ›</Link></> : null}
      {e?.code === 'AUTH_REQUIRED' ? <> <Link to="/login">去登录 ›</Link></> : null}
      {e ? <span className="muted mono">（{e.code}{e.requestId ? ` · ${e.requestId}` : ''}）</span> : null}
    </div>
  );
}
