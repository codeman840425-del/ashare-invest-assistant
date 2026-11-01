import { useState } from 'react';
import { Alert, Button, Form, Input, Result } from 'antd';
import { Link, useNavigate } from 'react-router';
import { ApiError } from '../../api/client';
import { useRegister, useRegistrationMode } from '../../api/accountQueries';
import { errorText } from '../../api/errorPolicy';
import { Loading, ErrorBox } from '../../components/common';
import { DISCLAIMER_TEXT } from '../../components/RiskDisclosure';
import { AuthLayout } from './AuthLayout';

interface FormValues {
  username: string; display_name: string; password: string; password2: string; invite_code?: string; apply_note?: string;
}

/** 契约 #24：^[a-z0-9_]{4,32}$，输入即转小写；保留字由后端 400 返回 */
const USERNAME_RE = /^[a-z0-9_]{4,32}$/;
const APPLY_NOTE_MAX = 200; // v0.2.4 #2
/** v0.2.5：注册不再提交 agreements；提交即视为已知悉固定免责提示（T-A06 裁定 6） */

/** 400 fields[].issue → 中文（未知 issue 显示原值） */
function issueText(field: string, issue: string): string {
  if (field === 'invite_code' && issue === 'invalid') return '邀请码无效或已失效';
  if (field === 'username' && issue === 'reserved') return '该用户名为系统保留，请换一个';
  if (issue === 'required') return '必填';
  if (issue === 'too_long') return '超出长度上限';
  if (issue === 'too_short') return '长度不足';
  if (issue === 'invalid') return '格式不正确';
  return issue;
}

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
      {
        username: v.username.toLowerCase(), password: v.password, display_name: v.display_name.trim(),
        invite_code: mode === 'invite' ? v.invite_code?.trim() || null : null,
        apply_note: v.apply_note?.trim() || null,
      },
      {
        onSuccess: (r) => setDone(r.username),
        onError: (e) => {
          if (!(e instanceof ApiError)) return setErr(errorText(e));
          if (e.code === 'REGISTRATION_CLOSED') return setErr('closed');
          if (e.code === 'CONFLICT') return form.setFields([{ name: 'username', errors: ['用户名已被使用'] }]);
          if (e.code === 'VALIDATION_ERROR') {
            const fields = ((e.details as { fields?: { field: string; issue: string }[] } | null)?.fields ?? []);
            const known = new Set(['username', 'password', 'display_name', 'invite_code', 'apply_note']);
            form.setFields(fields.filter((f) => known.has(f.field)).map((f) => ({ name: f.field as keyof FormValues, errors: [issueText(f.field, f.issue)] })));
            const other = fields.filter((f) => !known.has(f.field));
            if (other.length) setErr(other.map((f) => `${f.field}：${issueText(f.field, f.issue)}`).join('；'));
            else if (!fields.length) setErr(errorText(e));
            return;
          }
          setErr(e.code === 'RATE_LIMITED' ? '注册请求过于频繁，请稍后再试。' : errorText(e));
        },
      },
    );
  };

  return (
    <AuthLayout title={mode === 'invite' ? '注册（邀请制）' : '注册'} testId="register-page">
      <Alert type="info" showIcon style={{ marginBottom: 12 }} title="注册后需管理员审核，审核通过前无法登录。" />
      {err && err !== 'closed' ? <Alert type="error" showIcon style={{ marginBottom: 12 }} title={err} /> : null}
      <Form<FormValues> form={form} layout="vertical" onFinish={onFinish} requiredMark={false} disabled={register.isPending}>
        <Form.Item name="username" label="用户名" extra="4–32 位小写字母、数字或下划线，用于登录"
          normalize={(v: string | undefined) => v?.toLowerCase()}
          rules={[{ required: true, message: '请输入用户名' }, { pattern: USERNAME_RE, message: '4–32 位小写字母、数字或下划线' }]}>
          <Input autoComplete="username" data-testid="reg-username" />
        </Form.Item>
        <Form.Item name="display_name" label="显示名" rules={[{ required: true, whitespace: true, message: '请输入显示名' }, { max: 32, message: '不超过 32 个字' }]}>
          <Input />
        </Form.Item>
        <Form.Item name="password" label="密码" extra="10–128 位，包含字母和数字"
          rules={[{ required: true, message: '请输入密码' }, { min: 10, message: '至少 10 位' }, { max: 128, message: '不超过 128 位' }, { pattern: /(?=.*[A-Za-z])(?=.*\d)/, message: '需同时包含字母和数字' }]}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item name="password2" label="确认密码" dependencies={['password']}
          rules={[{ required: true, message: '请再次输入密码' }, ({ getFieldValue }) => ({ validator: (_r, val) => (val === getFieldValue('password') ? Promise.resolve() : Promise.reject(new Error('两次输入的密码不一致'))) })]}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        {mode === 'invite' ? (
          <Form.Item name="invite_code" label="邀请码" rules={[{ required: true, whitespace: true, message: '邀请制下必须填写邀请码' }]}>
            <Input data-testid="reg-invite" />
          </Form.Item>
        ) : null}
        {/* v0.2.4 #2：apply_note ≤200 字，邀请制必填 */}
        <Form.Item name="apply_note" label={mode === 'invite' ? '申请说明' : '申请说明（可选）'} extra="简单说明用途，供管理员审核参考"
          rules={[{ required: mode === 'invite', whitespace: true, message: '邀请制下请填写申请说明' }, { max: APPLY_NOTE_MAX, message: `不超过 ${APPLY_NOTE_MAX} 字` }]}>
          <Input.TextArea rows={2} maxLength={APPLY_NOTE_MAX} showCount data-testid="reg-apply-note" />
        </Form.Item>
        <div className="reg-disclaimer" data-testid="reg-disclaimer">
          <div className="muted small">提交注册即视为已知悉：</div>
          <p data-testid="reg-disclaimer-text">{DISCLAIMER_TEXT}</p>
        </div>
        <Button type="primary" htmlType="submit" block loading={register.isPending}>提交注册申请</Button>
      </Form>
      <div className="auth-links"><span>已有账号？<Link to="/login">登录</Link></span></div>
    </AuthLayout>
  );
}
