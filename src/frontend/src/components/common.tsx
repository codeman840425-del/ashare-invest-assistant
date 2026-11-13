import { useId, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react';
import { Empty, Tag, Tooltip } from 'antd';
import { Link } from 'react-router';
import { ApiError } from '../api/client';
import { BOOTSTRAP_REQUIRED_ISSUE, LICENCE_ERROR_CODES, ROUTE_PENDING_TEXT, errorText, isBootstrapRequired, isRoutePending, isStockSubPending, isSuperseded } from '../api/errorPolicy';
import type { Action, ConsensusStatus, DataStatus, Lifecycle, TLeg } from '../api/enums';
import type { Confidence, Gap } from '../api/types';
import { ACTION_COLOR, ACTION_FULL, ACTION_SHORT, CONF_LEVEL, DATA_STATUS, GAP_REASON } from '../i18n/labels';
import { fmtTime } from '../lib/format';
import { isNotApplicable } from '../lib/dataGaps';

/** 策略 + 动作徽标。措辞为“规则信号/候选”，不是投资建议 */
export function ActionBadge({ action, strategyName, tLeg, lifecycle, size = 'sm' }: { action: Action; strategyName?: string; tLeg?: TLeg | null; lifecycle?: Lifecycle; size?: 'sm' | 'lg' }) {
  const label = ACTION_SHORT[action] + (tLeg ? (tLeg === 'sell_first' ? '·先卖' : '·先买') : '');
  return (
    <Tooltip title={`${strategyName ? strategyName + '：' : ''}${ACTION_FULL[action]}`}>
      <span className={`action-badge ${size}`} style={{ borderColor: ACTION_COLOR[action], color: ACTION_COLOR[action] }}>
        {strategyName && size === 'sm' ? <i className="sk">{strategyName.slice(0, 2)}</i> : null}
        {label}{lifecycle === 'simulating' ? <b className="small"> · 模拟中</b> : null}
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

/** 数据状态的原因文字：数据时间 + 每条缺口（GAP_REASON + message） */
function dataStatusLines(asOf?: string | null, gaps?: Gap[]): string[] {
  return [asOf ? `数据时间 ${fmtTime(asOf)}` : null, ...(gaps ?? []).map((g) => `${g.key}：${GAP_REASON[g.reason]} — ${g.message}`)]
    .filter((x): x is string => !!x);
}

/**
 * 数据状态徽标。原因同时放在悬浮提示与隐藏说明里（评审 T-F22a M2）：
 * 可 Tab 聚焦，Enter / Space 打开或收起，Esc 收起；读屏经 aria-describedby 读到原因。
 */
const NOT_APPLICABLE_TAG = { text: '不适用', color: 'var(--text-3, #8c8c8c)' };

export function DataStatusTag({ status, asOf, gaps }: { status: DataStatus; asOf?: string | null; gaps?: Gap[] }) {
  const d = isNotApplicable(gaps) ? NOT_APPLICABLE_TAG : DATA_STATUS[status];
  const lines = dataStatusLines(asOf, gaps);
  const body = (
    <>
      <span className="dot" style={{ background: d.color }} />
      {d.text}
    </>
  );
  if (!lines.length) return <span className="ds-tag" style={{ color: d.color }}>{body}</span>;
  return <KeyTip lines={lines} className="ds-tag" style={{ color: d.color }} testId="data-status-tag">{body}</KeyTip>;
}

/**
 * 可键盘查看的悬浮说明（评审 T-F22a M2 / m10）：可 Tab 聚焦，Enter / Space 打开或收起，Esc 或失焦收起；
 * 说明文字同时放在隐藏节点里，经 aria-describedby 给读屏。
 */
export function KeyTip({ lines, children, className = '', style, testId }: { lines: string[]; children: ReactNode; className?: string; style?: CSSProperties; testId?: string }) {
  const descId = useId();
  const [open, setOpen] = useState(false);
  const onKeyDown = (e: KeyboardEvent<HTMLSpanElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      setOpen((o) => !o);
    } else if (e.key === 'Escape') setOpen(false);
  };
  return (
    <>
      <Tooltip title={<span style={{ whiteSpace: 'pre-line' }}>{lines.join('\n')}</span>} open={open} onOpenChange={setOpen}>
        <span
          className={`${className} focusable`} style={style} tabIndex={0} role="button"
          aria-expanded={open} aria-describedby={descId} data-testid={testId}
          onKeyDown={onKeyDown} onBlur={() => setOpen(false)}
        >
          {children}
        </span>
      </Tooltip>
      <span id={descId} className="sr-only">{lines.join('；')}</span>
    </>
  );
}

const NOTE_STATUS: readonly DataStatus[] = ['stale', 'partial', 'unavailable'];
/**
 * 正文里可见的缺数 / 过期原因（评审 T-F22a M2）：stale / partial / unavailable 或有 gaps 时显示。
 * 原因含 data_licence_unavailable 时附“去设置数据证书”链接。
 */
export function GapNote({ status, gaps, asOf, testId = 'gap-note' }: { status: DataStatus; gaps: Gap[]; asOf?: string | null; testId?: string }) {
  if (!gaps.length && !NOTE_STATUS.includes(status)) return null;
  if (isNotApplicable(gaps)) {
    return (
      <div className="gap-note na small" role="note" aria-label="数据状态说明" data-testid={testId} data-status="not_applicable">
        <b>不适用</b>：该证券类型没有此类数据{gaps[0].message ? `（${gaps[0].message}）` : ''}
      </div>
    );
  }
  const licence = gaps.some((g) => g.reason === 'data_licence_unavailable');
  const head = status === 'unavailable' ? '数据暂不可用' : status === 'stale' ? `数据已过期${asOf ? `（截至 ${fmtTime(asOf)}）` : ''}` : status === 'partial' ? '部分数据缺失' : '数据提示';
  return (
    <div className="gap-note small" role="note" aria-label="数据状态说明" data-testid={testId} data-status={status}>
      <b>{head}</b>
      {gaps.length ? '：' : null}
      {gaps.map((g, i) => (
        <span key={`${g.key}-${i}`} data-reason={g.reason}>
          {i ? '；' : ''}{GAP_REASON[g.reason]}（{g.message}）
        </span>
      ))}
      {licence ? <> <Link to="/settings/data-licence" data-testid="gap-licence-link">去设置数据证书 ›</Link></> : null}
    </div>
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
  // 契约 §7.3：北交所旧代码的 404 带 details.superseded_by，是真实资源 404，优先于“开发中”判定
  if (isSuperseded(error)) {
    const next = (error as ApiError).details?.superseded_by as string;
    return (
      <div className="error-box" role="alert" data-code="SUPERSEDED">
        该证券代码已停用，请改用新代码 <span className="mono">{next}</span>
      </div>
    );
  }
  // T-F20/T-F34b：后端还没注册的路由（含个股子资源）显示“开发中”空状态，不当作错误
  if (isRoutePending(error) || isStockSubPending(error)) return <Empty className="route-pending" data-testid="route-pending" image={Empty.PRESENTED_IMAGE_SIMPLE} description={ROUTE_PENDING_TEXT} style={{ margin: '48px auto' }} />;
  const e = error instanceof ApiError ? error : null;
  // 首导未完成（T-B94 裁定）：部署态问题，给可理解的提示而不是通用“服务暂时不可用”
  const bootstrap = isBootstrapRequired(error);
  const fresh = e?.code === 'FRESH_DATA_REQUIRED';
  return (
    <div className={`error-box${fresh ? ' refreshing' : ''}`} role="alert" data-code={bootstrap ? BOOTSTRAP_REQUIRED_ISSUE : e?.code}>
      {bootstrap
        ? '证券主数据尚未完成首次导入，暂时查不到证券资料；请联系管理员完成主数据导入后再试'
        : <>{fresh ? '' : `${prefix}：`}{errorText(error)}</>}
      {e?.code === 'AUTH_REQUIRED' ? <> <Link to="/login">去登录 ›</Link></> : null}
      {e && LICENCE_ERROR_CODES.includes(e.code) ? <> <Link to="/settings/data-licence">去设置数据证书 ›</Link></> : null}
      {e ? <span className="muted mono">（{e.code}{e.requestId ? ` · ${e.requestId}` : ''}）</span> : null}
    </div>
  );
}
