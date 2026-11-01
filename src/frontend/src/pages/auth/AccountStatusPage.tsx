import { Button, Result } from 'antd';
import { Link, useLocation, useSearchParams } from 'react-router';
import { ACCOUNT_STATUS } from '../../i18n/importLabels';
import type { AccountStatus } from '../../api/enums';
import { AuthLayout } from './AuthLayout';

const VIEW: Record<AccountStatus, { status: 'info' | 'warning' | 'error' | 'success'; title: string; desc: string }> = {
  pending: { status: 'info', title: '账号正在审核中', desc: '管理员审核通过后即可登录。审核期间不会创建登录会话，也不会保存你的任何持仓数据。' },
  rejected: { status: 'error', title: '注册申请未通过', desc: '如对结果有疑问，请联系管理员。' },
  disabled: { status: 'warning', title: '账号已停用', desc: '账号被管理员停用，暂时无法登录。已有数据会保留。' },
  approved: { status: 'success', title: '账号已通过审核', desc: '现在可以登录了。' },
};

/** 登录返回 403 ACCOUNT_NOT_APPROVED 或注册成功后进入此页（不需要登录） */
export function AccountStatusPage() {
  const [sp] = useSearchParams();
  const raw = sp.get('status') ?? 'pending';
  const status = (raw in VIEW ? raw : 'pending') as AccountStatus;
  const v = VIEW[status];
  // 原因从 history state 读取（评审 m4）；刷新或直接打开时没有原因，只显示状态
  const loc = useLocation();
  const reason = (loc.state as { reason?: string | null } | null)?.reason ?? null;
  const username = sp.get('username');
  return (
    <AuthLayout title="账号状态" testId="account-status">
      <Result
        status={v.status}
        title={v.title}
        subTitle={
          <div>
            {username ? <div>用户名：<span className="mono">{username}</span> · 状态：{ACCOUNT_STATUS[status].text}</div> : null}
            {reason ? <div data-testid="status-reason">原因：{reason}</div> : null}
            <div className="muted">{v.desc}</div>
          </div>
        }
        extra={<Link to="/login"><Button type={status === 'approved' ? 'primary' : 'default'}>返回登录</Button></Link>}
      />
    </AuthLayout>
  );
}
