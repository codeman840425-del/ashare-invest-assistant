import { useState } from 'react';
import { Alert, Button, Form, Input } from 'antd';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { ApiError } from '../../api/client';
import { errorText } from '../../api/errorPolicy';
import { useLogin, useRegistrationMode } from '../../api/accountQueries';
import { fmtDuration, safeNext } from '../../lib/auth';
import { AuthLayout } from './AuthLayout';

interface FormValues { username: string; password: string }

export function LoginPage() {
  const [sp] = useSearchParams();
  const next = sp.get('next');
  const navigate = useNavigate();
  const login = useLogin();
  const reg = useRegistrationMode();
  const [err, setErr] = useState<string | null>(null);

  const onFinish = (v: FormValues) => {
    setErr(null);
    login.mutate({ ...v, username: v.username.trim().toLowerCase() }, {
      onSuccess: () => {
        navigate(safeNext(next), { replace: true });
      },
      onError: (e) => {
        if (e instanceof ApiError && e.code === 'ACCOUNT_NOT_APPROVED') {
          const d = (e.details ?? {}) as { status?: string; reason?: string | null };
          // 原因只放在 history state，不进 URL（避免进入浏览器历史与访问日志；评审 m4）
          const q = new URLSearchParams({ status: d.status ?? 'pending', username: v.username });
          navigate(`/account-status?${q.toString()}`, { state: { reason: d.reason ?? null } });
        } else if (e instanceof ApiError && e.code === 'ACCOUNT_LOCKED') {
          const s = Number((e.details as { retry_after_s?: number } | null)?.retry_after_s ?? 0);
          setErr(`登录失败次数过多，账号已临时锁定，请 ${fmtDuration(s)}后再试。`);
        } else if (e instanceof ApiError && e.code === 'INVALID_CREDENTIALS') {
          setErr('用户名或密码不正确。');
        } else if (e instanceof ApiError && e.code === 'RATE_LIMITED') {
          setErr('请求过于频繁，请稍后再试。');
        } else {
          setErr(errorText(e));
        }
      },
    });
  };

  const mode = reg.data?.mode;
  return (
    <AuthLayout title="登录" testId="login-page">
      {sp.get('expired') ? <Alert type="warning" showIcon title="登录已失效，请重新登录。" style={{ marginBottom: 12 }} /> : null}
      {err ? <Alert type="error" showIcon title={err} style={{ marginBottom: 12 }} data-testid="login-error" /> : null}
      <Form<FormValues> layout="vertical" onFinish={onFinish} requiredMark={false} disabled={login.isPending}>
        <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
          <Input autoComplete="username" autoFocus />
        </Form.Item>
        <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Button type="primary" htmlType="submit" block loading={login.isPending}>登录</Button>
      </Form>
      <div className="auth-links">
        {mode && mode !== 'closed' ? (
          <span>还没有账号？<Link to="/register">{mode === 'invite' ? '凭邀请码注册' : '注册'}</Link></span>
        ) : (
          <span className="muted" data-testid="register-closed-hint">当前不开放注册，账号由管理员创建。</span>
        )}
      </div>
    </AuthLayout>
  );
}
