import { useState } from 'react';
import { Alert, Button, Checkbox, Form, Input, Result } from 'antd';
import { Link, useNavigate } from 'react-router';
import { ApiError } from '../../api/client';
import { useRegister, useRegistrationMode } from '../../api/accountQueries';
import type { ConsentKey } from '../../api/accountTypes';
import { Loading, ErrorBox } from '../../components/common';
import { CONSENT_ORDER, CONSENT_TEXT } from '../../i18n/accountLabels';
import { AuthLayout } from './AuthLayout';

interface FormValues { username: string; display_name: string; password: string; password2: string; invite_code?: string; agreements: ConsentKey[] }

// [待契约确认] 契约 username 为 3–32；plan 3.6 为 4–32 且限定小写字母/数字/下划线。前端按更严的 plan 校验，后端以 400 fields 为准。
const USERNAME_RE = /^[a-z0-9_]{4,32}$/;

export function RegisterPage() {
  const reg = useRegistrationMode();
  const register = useRegister();
  const navigate = useNavigate();
  const [form] = Form.useForm<FormValues>();
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  if (reg.isLoading) return <AuthLayout title="注册"><Loading /></AuthLayout>;
  if (reg.isError) return <AuthLayout title="注册"><ErrorBox error={reg.error} /></AuthLayout>;
  const mode = reg.data?.mode ?? 'closed';

  if (mode === 'closed' || err === 'closed') {
    return (
      <AuthLayout title="注册" testId="register-closed">
        <Result status="info" title="当前不开放注册" subTitle="本系统为自用部署，账号由管理员通过命令行创建。如需使用请联系管理员。" extra={<Link to="/login">返回登录</Link>} />
      </AuthLayout>
    );
  }
  if (done) {
    return (
      <AuthLayout title="注册" testId="register-done">
        <Result status="success" title="注册申请已提交" subTitle="账号需要管理员审核通过后才能登录，审核结果可在登录页查看。"
          extra={<Button type="primary" onClick={() => navigate(`/account-status?status=pending&username=${encodeURIComponent(done)}`)}>查看审核状态</Button>} />
      </AuthLayout>
    );
  }

  const onFinish = (v: FormValues) => {
    setErr(null);
    register.mutate(
      { username: v.username, password: v.password, display_name: v.display_name.trim(), invite_code: v.invite_code?.trim() || null, agreements: v.agreements },
      {
        onSuccess: (r) => setDone(r.username),
        onError: (e) => {
          if (!(e instanceof ApiError)) return setErr(e.message);
          if (e.code === 'REGISTRATION_CLOSED') return setErr('closed');
          if (e.code === 'CONFLICT') return form.setFields([{ name: 'username', errors: ['用户名已被使用'] }]);
          if (e.code === 'VALIDATION_ERROR') {
            const fields = ((e.details as { fields?: { field: string; issue: string }[] } | null)?.fields ?? []);
            const known = new Set(['username', 'password', 'display_name', 'invite_code', 'agreements']);
            form.setFields(fields.filter((f) => known.has(f.field)).map((f) => ({ name: f.field as keyof FormValues, errors: [f.issue] })));
            const other = fields.filter((f) => !known.has(f.field));
            if (other.length) setErr(other.map((f) => `${f.field}：${f.issue}`).join('；'));
            return;
          }
          // [待契约确认] 邀请码无效的错误码未定义，暂按通用错误展示后端文案
          setErr(e.code === 'RATE_LIMITED' ? '注册请求过于频繁，请稍后再试。' : e.message);
        },
      },
    );
  };

  return (
    <AuthLayout title={mode === 'invite' ? '注册（邀请制）' : '注册'} testId="register-page">
      <Alert type="info" showIcon style={{ marginBottom: 12 }} title="注册后需管理员审核，审核通过前无法登录。" />
      {err && err !== 'closed' ? <Alert type="error" showIcon style={{ marginBottom: 12 }} title={err} /> : null}
      <Form<FormValues> form={form} layout="vertical" onFinish={onFinish} requiredMark={false} disabled={register.isPending} initialValues={{ agreements: [] }}>
        <Form.Item name="username" label="用户名" extra="4–32 位小写字母、数字或下划线，用于登录"
          rules={[{ required: true, message: '请输入用户名' }, { pattern: USERNAME_RE, message: '4–32 位小写字母、数字或下划线' }]}>
          <Input autoComplete="username" />
        </Form.Item>
        <Form.Item name="display_name" label="显示名" rules={[{ required: true, whitespace: true, message: '请输入显示名' }, { max: 32, message: '不超过 32 个字' }]}>
          <Input />
        </Form.Item>
        <Form.Item name="password" label="密码" extra="至少 10 位，包含字母和数字"
          rules={[{ required: true, message: '请输入密码' }, { min: 10, message: '至少 10 位' }, { pattern: /(?=.*[A-Za-z])(?=.*\d)/, message: '需同时包含字母和数字' }]}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item name="password2" label="确认密码" dependencies={['password']}
          rules={[{ required: true, message: '请再次输入密码' }, ({ getFieldValue }) => ({ validator: (_r, val) => (val === getFieldValue('password') ? Promise.resolve() : Promise.reject(new Error('两次输入的密码不一致'))) })]}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        {mode === 'invite' ? (
          <Form.Item name="invite_code" label="邀请码" rules={[{ required: true, whitespace: true, message: '邀请制下必须填写邀请码' }]}>
            <Input />
          </Form.Item>
        ) : null}
        {/* [待契约确认] agreements 的取值按 consent key（terms/privacy/signal_risk_disclosure）提交 */}
        <Form.Item name="agreements" label="协议与揭示"
          rules={[{ validator: (_r, v: ConsentKey[]) => (CONSENT_ORDER.every((k) => v?.includes(k)) ? Promise.resolve() : Promise.reject(new Error('需同意全部三项才能注册'))) }]}>
          <Checkbox.Group className="agree-group">
            {CONSENT_ORDER.map((k) => (
              <Checkbox key={k} value={k} data-testid={`agree-${k}`}>
                <b>{CONSENT_TEXT[k].title}</b>
                <div className="muted small">{CONSENT_TEXT[k].summary}</div>
              </Checkbox>
            ))}
          </Checkbox.Group>
        </Form.Item>
        <Button type="primary" htmlType="submit" block loading={register.isPending}>提交注册申请</Button>
      </Form>
      <div className="auth-links"><span>已有账号？<Link to="/login">登录</Link></span></div>
    </AuthLayout>
  );
}
