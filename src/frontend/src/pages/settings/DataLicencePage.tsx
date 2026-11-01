import { useState } from 'react';
import { Alert, Button, Checkbox, Descriptions, Form, Input, Popconfirm, Select, Space, Tag } from 'antd';
import { ENUMS, type DataLicenceTier } from '../../api/enums';
import {
  useDataLicence, useDeleteDataLicence, usePatchDataLicence, usePutDataLicence, useTestDataLicence,
} from '../../api/licenceQueries';
import { LICENCE_RE, type DataLicenceStatus } from '../../api/licenceTypes';
import { ErrorBox, Loading } from '../../components/common';
import { LICENCE_ERROR, LICENCE_STATUS, LICENCE_TIER } from '../../i18n/licenceLabels';
import { applyFieldErrors } from '../../lib/formErrors';
import { fmtTime } from '../../lib/format';

interface FormValues { licence: string; tier: DataLicenceTier; has_quant_pro: boolean; expires_on: string }
const FIELDS = ['licence', 'tier', 'has_quant_pro', 'expires_on'] as const;
const DEFAULTS: FormValues = { licence: '', tier: 'diamond', has_quant_pro: false, expires_on: '' };

export function LicenceBadge({ s }: { s: DataLicenceStatus['status'] }) {
  return <Tag color={LICENCE_STATUS[s].color} data-testid="licence-badge">{LICENCE_STATUS[s].text}</Tag>;
}

/**
 * 设置 → 数据证书（T-F22；契约 v0.2.6 §7.1 /me/data-licence*；plan 2.1B）。
 * - 证书输入为密码型、不自动填充；提交后立即清空（无论成功失败），页面任何地方都不回显证书值或其片段。
 * - 档位、Quant Pro、到期日为用户自报；只改这三项走 PATCH，不需要重新输入证书。
 */
export function DataLicencePage() {
  const q = useDataLicence({ pollWhilePending: true });
  const put = usePutDataLicence();
  const patch = usePatchDataLicence();
  const del = useDeleteDataLicence();
  const test = useTestDataLicence();
  const [form] = Form.useForm<FormValues>();
  const [msg, setMsg] = useState<string | null>(null);
  const [other, setOther] = useState<string[]>([]);

  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const s = q.data;
  const isSet = s.status !== 'not_set';
  const initial: FormValues = { ...DEFAULTS, tier: s.tier ?? DEFAULTS.tier, has_quant_pro: s.has_quant_pro ?? false, expires_on: s.expires_on ?? '' };
  const meta = (v: FormValues) => ({ tier: v.tier, has_quant_pro: !!v.has_quant_pro, expires_on: v.expires_on || null });

  const reset = () => { setMsg(null); setOther([]); };
  const onFinish = (v: FormValues) => {
    reset();
    const licence = (v.licence ?? '').trim();
    // 提交即清空：证书值不在表单、状态或缓存里停留
    form.setFieldValue('licence', '');
    if (!licence) {
      if (!isSet) { form.setFields([{ name: 'licence', errors: ['请输入证书'] }]); return; }
      patch.mutate(meta(v), { onSuccess: () => setMsg('已更新档位与到期日'), onError: (e) => setOther(applyFieldErrors(form, e, FIELDS)) });
      return;
    }
    if (!LICENCE_RE.test(licence)) {
      form.setFields([{ name: 'licence', errors: ['格式不符：应为 16–64 位字母、数字或连字符'] }]);
      return;
    }
    put.submit(licence, meta(v), {
      onSuccess: () => setMsg('已提交，正在验证。证书已加密保存，之后不会再显示。'),
      onError: (e) => setOther(applyFieldErrors(form, e, FIELDS)),
    });
  };
  const saving = put.isPending || patch.isPending;
  const mutErr = put.error ?? patch.error ?? del.error ?? test.error;

  return (
    <div className="page narrow" data-testid="licence-page">
      <h2 className="page-title">数据证书 <LicenceBadge s={s.status} /></h2>
      <p className="muted">
        行情只用你本人的麦蕊证书获取，不会使用他人或管理员的证书。证书加密保存，提交后不会再显示，任何页面和接口都看不到它的内容或末几位。
      </p>
      {s.status === 'pending_verification' ? <Alert type="info" showIcon title="正在验证证书，稍后自动刷新状态" style={{ margin: '12px 0' }} /> : null}
      {msg ? <Alert type="success" showIcon title={msg} style={{ margin: '12px 0' }} data-testid="licence-msg" /> : null}
      {other.length ? <Alert type="error" showIcon title={other.join('；')} style={{ margin: '12px 0' }} /> : null}
      {mutErr && !other.length ? <ErrorBox error={mutErr} prefix="操作失败" /> : null}

      <Descriptions size="small" column={2} bordered style={{ margin: '12px 0' }} data-testid="licence-status">
        <Descriptions.Item label="状态"><LicenceBadge s={s.status} /></Descriptions.Item>
        <Descriptions.Item label="档位（自报）">{s.tier ? LICENCE_TIER[s.tier] : '—'}{s.has_quant_pro ? <Tag style={{ marginLeft: 6 }}>Quant Pro</Tag> : null}</Descriptions.Item>
        <Descriptions.Item label="到期日（自填）">
          {s.expires_on ?? '—'}
          {s.days_to_expiry != null ? <span className={s.days_to_expiry <= 7 ? 'down' : 'muted'}>（剩 {s.days_to_expiry} 天）</span> : null}
        </Descriptions.Item>
        <Descriptions.Item label="设置时间">{s.set_at ? fmtTime(s.set_at) : '—'}</Descriptions.Item>
        <Descriptions.Item label="最近验证">{s.last_verified_at ? fmtTime(s.last_verified_at) : '—'}</Descriptions.Item>
        <Descriptions.Item label="最近错误">
          {s.last_error_code ? <span data-testid="licence-error">{LICENCE_ERROR[s.last_error_code]}（{s.last_error_code}）{s.last_error_at ? ` · ${fmtTime(s.last_error_at)}` : ''}</span> : '—'}
        </Descriptions.Item>
        {s.paused_until ? <Descriptions.Item label="暂停至" span={2}>{fmtTime(s.paused_until)}</Descriptions.Item> : null}
      </Descriptions>

      <Form<FormValues> form={form} layout="vertical" initialValues={initial} onFinish={onFinish} requiredMark={false} autoComplete="off">
        <Form.Item name="licence" label={isSet ? '更换证书（留空则只更新下面的档位与到期日）' : '证书'}>
          <Input.Password
            data-testid="licence-input" autoComplete="new-password" visibilityToggle={false} spellCheck={false}
            placeholder={isSet ? '已设置（不显示）；输入新证书即替换' : '粘贴你的麦蕊证书'} style={{ maxWidth: 420 }}
          />
        </Form.Item>
        <Space size="large" align="start" wrap>
          <Form.Item name="tier" label="档位">
            <Select style={{ width: 140 }} options={ENUMS.data_licence_tier.map((t) => ({ value: t, label: LICENCE_TIER[t] }))} />
          </Form.Item>
          <Form.Item name="has_quant_pro" label="Quant Pro" valuePropName="checked">
            <Checkbox>已开通</Checkbox>
          </Form.Item>
          <Form.Item name="expires_on" label="到期日（可不填）" rules={[{ pattern: /^\d{4}-\d{2}-\d{2}$/, message: '格式 YYYY-MM-DD' }]}>
            <Input type="date" style={{ width: 170 }} data-testid="licence-expires" />
          </Form.Item>
        </Space>
        <Space>
          <Button type="primary" htmlType="submit" loading={saving} data-testid="licence-save">{isSet ? '保存' : '保存并验证'}</Button>
          <Button disabled={!isSet} loading={test.isPending} data-testid="licence-test"
            onClick={() => { reset(); test.mutate(undefined, { onSuccess: () => setMsg('已提交测试，结果稍后显示在状态里') }); }}>
            测试证书
          </Button>
          <Popconfirm title="删除后将停止用该证书取数，确定删除？" okText="删除" cancelText="取消"
            onConfirm={() => { reset(); del.mutate(undefined, { onSuccess: () => setMsg('证书已删除') }); }}>
            <Button danger disabled={!isSet} loading={del.isPending} data-testid="licence-delete">删除证书</Button>
          </Popconfirm>
        </Space>
      </Form>
      <p className="muted" style={{ marginTop: 16 }}>
        请用你本人的麦蕊账号申请证书；一张证书只能绑定一个账号。档位与到期日只用于限速和到期提醒，到期前 30 / 7 / 1 天会提醒。
      </p>
    </div>
  );
}
