import { useState } from 'react';
import { Alert, Button, Input, Modal, Segmented, Space, Table, Tag, Tooltip } from 'antd';
import { usePatchAdminUser, useAdminUsers } from '../../api/accountQueries';
import type { AdminUser, AdminUserPatch } from '../../api/accountTypes';
import type { AccountStatus } from '../../api/enums';
import { ErrorBox } from '../../components/common';
import { ROLE_TEXT } from '../../i18n/accountLabels';
import { ACCOUNT_STATUS } from '../../i18n/importLabels';
import { fmtTime } from '../../lib/format';

type Target = AdminUserPatch['status'];
const ACTIONS: Record<AccountStatus, Target[]> = { pending: ['approved', 'rejected'], approved: ['disabled'], rejected: ['approved'], disabled: ['approved'] };
const ACTION_TEXT: Record<Target, string> = { approved: '通过', rejected: '驳回', disabled: '停用' };
const NEEDS_REASON = (t: Target) => t !== 'approved';
/** 同一 IP 注册数达到这个值时高亮提示（plan 3.6 风控线索） // [待契约确认] 阈值 */
const SAME_IP_ALERT = 3;

/** 管理端用户审核（契约 §7.9 GET/PATCH /admin/users）。驳回、停用必须填写理由。 */
export function AdminUsersPage() {
  const [status, setStatus] = useState<AccountStatus | ''>('pending');
  const [q, setQ] = useState('');
  const list = useAdminUsers(status, q.trim());
  const patch = usePatchAdminUser();
  const [pending, setPending] = useState<{ user: AdminUser; to: Target } | null>(null);
  const [reason, setReason] = useState('');

  const open = (user: AdminUser, to: Target) => {
    patch.reset();
    setReason('');
    setPending({ user, to });
  };
  const submit = () => {
    if (!pending) return;
    patch.mutate({ id: pending.user.id, status: pending.to, reason: reason.trim() || null }, { onSuccess: () => setPending(null) });
  };

  return (
    <div className="page-scroll page" data-testid="admin-users">
      <h2 className="page-title">用户审核</h2>
      <Space wrap style={{ marginBottom: 12 }}>
        <Segmented<AccountStatus | ''>
          value={status}
          onChange={setStatus}
          options={[{ value: 'pending', label: '待审核' }, { value: 'approved', label: '已通过' }, { value: 'rejected', label: '已驳回' }, { value: 'disabled', label: '已停用' }, { value: '', label: '全部' }]}
        />
        <Input.Search allowClear placeholder="用户名 / 显示名" style={{ width: 220 }} onSearch={setQ} data-testid="admin-users-search" />
      </Space>
      {list.isError ? <ErrorBox error={list.error} /> : null}
      <Table<AdminUser>
        size="small"
        rowKey="id"
        loading={list.isPending}
        dataSource={list.data?.items ?? []}
        pagination={false}
        locale={{ emptyText: '没有符合条件的用户' }}
        columns={[
          { title: '用户名', dataIndex: 'username', render: (v: string, r) => <span><span className="mono">{v}</span>{r.role === 'admin' ? <Tag style={{ marginLeft: 6 }}>{ROLE_TEXT.admin}</Tag> : null}</span> },
          { title: '显示名', dataIndex: 'display_name' },
          { title: '状态', dataIndex: 'status', width: 90, render: (s: AccountStatus) => <Tag color={ACCOUNT_STATUS[s].color}>{ACCOUNT_STATUS[s].text}</Tag> },
          { title: '申请说明', dataIndex: 'apply_note', ellipsis: true, render: (v: string | null) => v ?? <span className="muted">—</span> },
          { title: '注册时间', dataIndex: 'created_at', width: 150, render: (v: string) => <span className="mono">{fmtTime(v)}</span> },
          { title: '注册 IP 属地', dataIndex: 'register_ip_region', width: 120, render: (v: string | null) => v ?? '—' },
          {
            title: '同 IP 注册', dataIndex: 'same_ip_registrations', width: 96, align: 'right',
            render: (n: number) => (n >= SAME_IP_ALERT ? <Tooltip title="同一 IP 注册较多，建议核实"><Tag color="orange" className="mono">{n}</Tag></Tooltip> : <span className="mono">{n}</span>),
          },
          { title: '审核理由', dataIndex: 'review_reason', ellipsis: true, render: (v: string | null) => v ?? <span className="muted">—</span> },
          {
            title: '操作', key: 'op', width: 140,
            render: (_v, r) => (
              <Space size={4}>
                {ACTIONS[r.status].map((t) => (
                  <Button key={t} size="small" danger={t !== 'approved'} type={t === 'approved' ? 'primary' : 'default'} onClick={() => open(r, t)} data-testid={`act-${t}-${r.username}`}>
                    {ACTION_TEXT[t]}
                  </Button>
                ))}
              </Space>
            ),
          },
        ]}
      />
      <Modal
        open={!!pending}
        title={pending ? `${ACTION_TEXT[pending.to]}：${pending.user.display_name}（${pending.user.username}）` : ''}
        okText={pending ? `确认${ACTION_TEXT[pending.to]}` : '确认'}
        okButtonProps={{ disabled: !!pending && NEEDS_REASON(pending.to) && !reason.trim(), loading: patch.isPending, danger: pending?.to !== 'approved' }}
        onOk={submit}
        onCancel={() => setPending(null)}
        destroyOnHidden
      >
        {pending && NEEDS_REASON(pending.to) ? <Alert type="warning" showIcon style={{ marginBottom: 8 }} title="驳回或停用必须填写理由，理由会展示给该用户并写入审计。" /> : null}
        <Input.TextArea
          rows={3}
          maxLength={200}
          showCount
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder={pending && NEEDS_REASON(pending.to) ? '必填：理由' : '可选：备注'}
          data-testid="admin-reason"
        />
        {patch.isError ? <div style={{ marginTop: 8 }}><ErrorBox error={patch.error} prefix="操作失败" /></div> : null}
      </Modal>
    </div>
  );
}
