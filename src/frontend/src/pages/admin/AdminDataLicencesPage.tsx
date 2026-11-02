import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { Alert, Button, Checkbox, Input, Modal, Segmented, Space, Table, Tag, Tooltip, type ButtonProps } from 'antd';
import { useAdminDataLicences, useAdminLicenceAction, type AdminLicenceOp } from '../../api/adminQueries';
import { ADMIN_REASON_MAX, type AdminDataLicence } from '../../api/adminTypes';
import { ApiError } from '../../api/client';
import { errorText } from '../../api/errorPolicy';
import type { DataLicenceState } from '../../api/enums';
import { CursorPager } from '../../components/CursorPager';
import { ErrorBox } from '../../components/common';
import { LICENCE_ERROR, LICENCE_STATUS, LICENCE_TIER, expiryLeftText } from '../../i18n/licenceLabels';
import { fmtTime } from '../../lib/format';

const PAGE_SIZE = 50;
type Filter = 'all' | 'paused' | 'abnormal' | 'not_set';
const ABNORMAL: readonly DataLicenceState[] = ['invalid', 'expired', 'quota_exceeded', 'ip_limited'];
const MATCH: Record<Filter, (r: AdminDataLicence) => boolean> = {
  all: () => true,
  paused: (r) => r.status === 'paused_by_admin',
  abnormal: (r) => ABNORMAL.includes(r.status),
  not_set: (r) => r.status === 'not_set',
};
const OP_TEXT: Record<AdminLicenceOp, string> = { pause: '暂停', resume: '恢复' };

/** 行上可做的操作：已暂停 → 恢复；已设置（非暂停）→ 暂停；未设置 → 无（pause 会 409 DATA_LICENCE_NOT_SET） */
function opOf(r: AdminDataLicence): AdminLicenceOp | null {
  if (r.status === 'paused_by_admin') return 'resume';
  if (r.status === 'not_set') return null;
  return 'pause';
}
/** 暂停期间用户删除了证书：GET 仍为 paused_by_admin，licence_id 为 null；恢复后为 not_set（v0.2.8 §7.9） */
const deletedWhilePaused = (r: AdminDataLicence) => r.status === 'paused_by_admin' && r.licence_id === null;

function effectText(r: AdminDataLicence, op: AdminLicenceOp): string {
  if (op === 'pause') {
    return '暂停后采集服务不再使用该证书，用户的行情数据会停在旧数据；用户在暂停期间替换或删除证书都不会解除暂停，只有管理员恢复才能解除。操作会写入审计。';
  }
  if (deletedWhilePaused(r)) return '该用户已在暂停期间删除了证书。恢复只解除暂停记录，之后状态为“未设置”，需要用户重新设置证书。操作会写入审计。';
  return '恢复后状态变为“验证中”，系统会重新验证该证书；验证通过前不会用于采集。操作会写入审计。';
}

function adminErrorText(e: unknown): string {
  // 管理端语境：ErrorBox 的“你还没有设置数据证书 / 去设置”是给用户本人的，这里单独说明
  if (e instanceof ApiError && e.code === 'DATA_LICENCE_NOT_SET') return '该用户没有设置数据证书，也不在暂停中，无法操作；列表已刷新';
  return errorText(e);
}

/**
 * 管理端数据证书列表（契约 v0.2.8 §5.1 AdminDataLicence、§7.9 GET /admin/data-licences、pause / resume）。
 * 每位用户一行（含未设置的用户），§1.2 游标“加载更多”；暂停 / 恢复须填写理由并二次确认。
 * 页面不显示、也拿不到证书值或其任何片段。
 */
export function AdminDataLicencesPage() {
  const [sp] = useSearchParams();
  const focusUser = sp.get('user');
  const list = useAdminDataLicences(PAGE_SIZE);
  const action = useAdminLicenceAction();
  const [filter, setFilter] = useState<Filter>('all');
  const [pending, setPending] = useState<{ row: AdminDataLicence; op: AdminLicenceOp } | null>(null);
  const [reason, setReason] = useState('');
  const [ack, setAck] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const rows = list.items.filter(MATCH[filter]);

  const open = (row: AdminDataLicence, op: AdminLicenceOp) => {
    action.reset();
    setReason('');
    setAck(false);
    setPending({ row, op });
  };
  const trimmed = reason.trim();
  const ready = trimmed.length >= 1 && trimmed.length <= ADMIN_REASON_MAX && ack;
  const submit = () => {
    if (!pending || !ready) return;
    const { row, op } = pending;
    action.mutate(
      { userId: row.user_id, op, reason: trimmed },
      {
        onSuccess: () => {
          setDone(`已${OP_TEXT[op]} ${row.display_name}（${row.username}）的数据证书${op === 'resume' && deletedWhilePaused(row) ? '；该用户证书已删除，当前为“未设置”' : ''}`);
          setPending(null);
        },
      },
    );
  };

  const columns = [
    {
      title: '用户', key: 'user',
      render: (_: unknown, r: AdminDataLicence) => <span>{r.display_name}<span className="muted small">（<span className="mono">{r.username}</span>）</span></span>,
    },
    {
      title: '状态', key: 'status', width: 170,
      render: (_: unknown, r: AdminDataLicence) => (
        <span>
          <Tag color={LICENCE_STATUS[r.status].color} data-testid={`lic-status-${r.username}`}>{LICENCE_STATUS[r.status].text}</Tag>
          {deletedWhilePaused(r) ? <Tooltip title="用户在暂停期间删除了证书；恢复后为“未设置”"><Tag data-testid={`lic-deleted-${r.username}`}>证书已删除</Tag></Tooltip> : null}
        </span>
      ),
    },
    { title: '档位', key: 'tier', render: (_: unknown, r: AdminDataLicence) => <span>{r.tier ? LICENCE_TIER[r.tier] : '—'}{r.has_quant_pro ? <Tag style={{ marginLeft: 4 }}>量化Pro</Tag> : null}</span> },
    { title: '到期', key: 'exp', render: (_: unknown, r: AdminDataLicence) => (r.expires_on ? (r.days_to_expiry != null ? `${r.expires_on}（${expiryLeftText(r.days_to_expiry)}）` : r.expires_on) : r.licence_id ? '未填' : '—') },
    { title: '最近验证', key: 'ver', render: (_: unknown, r: AdminDataLicence) => (r.last_verified_at ? <span className="mono">{fmtTime(r.last_verified_at)}</span> : '—') },
    { title: '今日调用', dataIndex: 'calls_today', key: 'today', align: 'right' as const },
    { title: '近 1 分钟 / 上限', key: 'min', align: 'right' as const, render: (_: unknown, r: AdminDataLicence) => `${r.calls_last_minute} / ${r.per_minute_limit}` },
    { title: '队列 P0/P1/P2', key: 'queue', align: 'right' as const, render: (_: unknown, r: AdminDataLicence) => `${r.queue_depth.p0} / ${r.queue_depth.p1} / ${r.queue_depth.p2}` },
    { title: '熔断至', dataIndex: 'paused_until', key: 'pu', render: (v: string | null) => (v ? fmtTime(v) : '—') },
    {
      title: '最近错误', key: 'err',
      render: (_: unknown, r: AdminDataLicence) => (r.last_error_code ? <span>{LICENCE_ERROR[r.last_error_code]}{r.last_error_at ? <span className="muted small">（{fmtTime(r.last_error_at)}）</span> : null}</span> : '—'),
    },
    {
      title: '操作', key: 'op', width: 90,
      render: (_: unknown, r: AdminDataLicence) => {
        const op = opOf(r);
        if (!op) return <Tooltip title="该用户未设置证书，无需暂停"><span className="muted">—</span></Tooltip>;
        return (
          <Button size="small" danger={op === 'pause'} type={op === 'resume' ? 'primary' : 'default'} onClick={() => open(r, op)} data-testid={`lic-${op}-${r.username}`}>
            {OP_TEXT[op]}
          </Button>
        );
      },
    },
  ];

  return (
    <div className="page-scroll page" data-testid="admin-data-licences">
      <h2 className="page-title">数据证书（管理）</h2>
      <p className="muted small">每位用户一行（含未设置证书的用户）。只显示状态与用量，不显示证书值。按证书汇总的采集状态见 <Link to="/admin/ingest">采集状态（管理）</Link>。</p>
      <Space wrap style={{ marginBottom: 12 }}>
        <Segmented
          value={filter}
          onChange={(v) => setFilter(v as Filter)}
          options={[{ value: 'all', label: '全部' }, { value: 'paused', label: '管理员已暂停' }, { value: 'abnormal', label: '异常' }, { value: 'not_set', label: '未设置' }]}
          data-testid="lic-filter"
        />
        {filter !== 'all' ? <span className="muted small" data-testid="lic-filter-note">只筛选已加载的 {list.items.length} 行（接口未提供筛选参数）</span> : null}
      </Space>
      {done ? <Alert type="success" showIcon closable onClose={() => setDone(null)} style={{ marginBottom: 8 }} title={done} data-testid="lic-done" /> : null}
      {list.isError ? <ErrorBox error={list.error} /> : null}
      <Table<AdminDataLicence>
        size="small"
        rowKey="user_id"
        loading={list.isPending}
        dataSource={rows}
        pagination={false}
        columns={columns}
        rowClassName={(r) => (r.user_id === focusUser ? 'row-focus' : '')}
        locale={{ emptyText: filter === 'all' ? '没有用户' : '已加载的行中没有符合条件的用户' }}
        data-testid="lic-table"
      />
      <CursorPager query={list} loaded={list.items.length} unit="位用户" testId="lic-pager" />
      <Modal
        open={!!pending}
        title={pending ? `${OP_TEXT[pending.op]}数据证书：${pending.row.display_name}（${pending.row.username}）` : ''}
        okText={pending ? `确认${OP_TEXT[pending.op]}` : '确认'}
        okButtonProps={{ disabled: !ready, loading: action.isPending, danger: pending?.op === 'pause', 'data-testid': 'lic-ok' } as ButtonProps}
        onOk={submit}
        onCancel={() => setPending(null)}
        destroyOnHidden
      >
        {pending ? (
          <>
            <Alert type={pending.op === 'pause' ? 'warning' : 'info'} showIcon style={{ marginBottom: 8 }} title={effectText(pending.row, pending.op)} data-testid="lic-effect" />
            <div className="small muted" style={{ marginBottom: 4 }}>当前状态：{LICENCE_STATUS[pending.row.status].text}</div>
            <Input.TextArea
              rows={3}
              maxLength={ADMIN_REASON_MAX}
              showCount
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="必填：理由（写入审计）"
              data-testid="lic-reason"
            />
            <Checkbox checked={ack} onChange={(e) => setAck(e.target.checked)} style={{ marginTop: 8 }} data-testid="lic-ack">
              我已核对：要{OP_TEXT[pending.op]}的是用户 {pending.row.username} 的数据证书
            </Checkbox>
            {action.isError ? <Alert type="error" showIcon style={{ marginTop: 8 }} title={`操作失败：${adminErrorText(action.error)}`} data-testid="lic-error" /> : null}
          </>
        ) : null}
      </Modal>
    </div>
  );
}
