import { useState } from 'react';
import { Alert, Button, Checkbox, Descriptions, Form, Input, Popconfirm, Select, Space, Tag, Tooltip } from 'antd';
import { ApiError } from '../../api/client';
import { ENUMS, type DataLicenceTier } from '../../api/enums';
import {
  useDataLicence, useDeleteDataLicence, usePatchDataLicence, usePutDataLicence, useTestDataLicence,
} from '../../api/licenceQueries';
import { LICENCE_RE, type DataLicenceStatus } from '../../api/licenceTypes';
import { ErrorBox, Loading } from '../../components/common';
import { LICENCE_ERROR, LICENCE_STATUS, LICENCE_TIER, expiryLeftText } from '../../i18n/licenceLabels';
import { applyFieldErrors } from '../../lib/formErrors';
import { fmtTime } from '../../lib/format';

interface FormValues { licence: string; tier: DataLicenceTier; has_quant_pro: boolean; expires_on: string }
const FIELDS = ['licence', 'tier', 'has_quant_pro', 'expires_on'] as const;
/**
 * 202 后是否处于冷却（契约 #13：quota_exceeded / ip_limited，或带 paused_until）；只有这时才提示“冷却到期前不会重新验证”。
 * paused_until 是否到期由服务端判断（到期则已转为 pending_verification），前端不拿本地时钟比较。
 */
const inCooldown = (r: DataLicenceStatus) => r.status === 'quota_exceeded' || r.status === 'ip_limited' || !!r.paused_until;
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
  // v0.2.8 补充裁定③：设置开关关闭时 PUT/PATCH/test → 503 MAINTENANCE；之后禁用保存与测试（GET、DELETE 照常）
  const [closed, setClosed] = useState(false);

  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const s = q.data;
  const isSet = s.status !== 'not_set';
  const initial: FormValues = { ...DEFAULTS, tier: s.tier ?? DEFAULTS.tier, has_quant_pro: s.has_quant_pro ?? false, expires_on: s.expires_on ?? '' };
  // v0.2.8 #12/#14：管理员暂停期间可以更换证书（202，状态仍为暂停、不验证），但不能测试
  const paused = s.status === 'paused_by_admin';
  const isMaintenance = (e: unknown) => e instanceof ApiError && e.code === 'MAINTENANCE';
  const onMutError = (e: unknown) => {
    if (isMaintenance(e)) { setClosed(true); return; }
    setOther(applyFieldErrors(form, e, FIELDS));
  };
  const meta = (v: FormValues) => ({ tier: v.tier, has_quant_pro: !!v.has_quant_pro, expires_on: v.expires_on || null });

  // 评审 m1：每次操作前清掉四个 mutation 上一次的错误，页面只显示最近一次操作的结果
  const reset = () => {
    setMsg(null);
    setOther([]);
    put.reset();
    patch.reset();
    del.reset();
    test.reset();
  };
  const onFinish = (v: FormValues) => {
    reset();
    const licence = (v.licence ?? '').trim();
    // 提交即清空：证书值不在表单、状态或缓存里停留
    form.setFieldValue('licence', '');
    if (!licence) {
      if (!isSet) { form.setFields([{ name: 'licence', errors: ['请输入证书'] }]); return; }
      patch.mutate(meta(v), { onSuccess: () => setMsg('已更新档位与到期日'), onError: onMutError });
      return;
    }
    if (!LICENCE_RE.test(licence)) {
      form.setFields([{ name: 'licence', errors: ['格式不符：应为 16–64 位字母、数字或连字符'] }]);
      return;
    }
    put.submit(licence, meta(v), {
      // v0.2.8 #12/#13：202 时状态可能仍为暂停或冷却中（重复提交同一证书不清除冷却），按返回的状态给提示
      onSuccess: (r) => setMsg(r.status === 'paused_by_admin'
        ? '证书已加密保存，之后不会再显示。管理员暂停期间不会验证，管理员恢复后才会验证。'
        : r.status === 'pending_verification'
          ? '已提交，正在验证。证书已加密保存，之后不会再显示。'
          : inCooldown(r)
            ? `证书已加密保存，之后不会再显示。当前状态“${LICENCE_STATUS[r.status].text}”，冷却到期前不会重新验证。`
            : `证书已加密保存，之后不会再显示。当前状态“${LICENCE_STATUS[r.status].text}”。`),
      onError: onMutError,
    });
  };
  const saving = put.isPending || patch.isPending;
  const mutErrRaw = put.error ?? patch.error ?? del.error ?? test.error;
  const mutErr = isMaintenance(mutErrRaw) ? null : mutErrRaw;

  return (
    <div className="page narrow" data-testid="licence-page">
      <h2 className="page-title">数据证书 <LicenceBadge s={s.status} /></h2>
      <p className="muted">
        行情只用你本人的麦蕊证书获取，不会使用他人或管理员的证书。证书加密保存，提交后不会再显示，任何页面和接口都看不到它的内容或末几位。
      </p>
      {s.status === 'pending_verification' ? <Alert type="info" showIcon title="正在验证证书，稍后自动刷新状态" style={{ margin: '12px 0' }} /> : null}
      {closed ? (
        <Alert type="warning" showIcon data-testid="licence-closed" style={{ margin: '12px 0' }} title="设置暂未开放"
          description="证书设置暂时关闭，暂不能保存或测试证书；仍可查看状态和删除证书。" />
      ) : null}
      {paused ? (
        <Alert type="warning" showIcon data-testid="licence-paused" style={{ margin: '12px 0' }} title="管理员已暂停你的证书取数"
          description="暂停期间不能测试证书；可以更换证书，保存后状态仍为“管理员已暂停”、不会验证。删除后重新提交也不会解除暂停，需要管理员恢复。" />
      ) : null}
      {msg ? <Alert type="success" showIcon title={msg} style={{ margin: '12px 0' }} data-testid="licence-msg" /> : null}
      {other.length ? <Alert type="error" showIcon title={other.join('；')} style={{ margin: '12px 0' }} /> : null}
      {mutErr && !other.length ? <ErrorBox error={mutErr} prefix="操作失败" /> : null}

      <Descriptions size="small" column={2} bordered style={{ margin: '12px 0' }} data-testid="licence-status">
        <Descriptions.Item label="状态"><LicenceBadge s={s.status} /></Descriptions.Item>
        <Descriptions.Item label="档位（自报）">{s.tier ? LICENCE_TIER[s.tier] : '—'}{s.has_quant_pro ? <Tag style={{ marginLeft: 6 }}>Quant Pro</Tag> : null}</Descriptions.Item>
        <Descriptions.Item label="到期日（自填）">
          {s.expires_on ?? '—'}
          {s.days_to_expiry != null ? <span className={s.days_to_expiry <= 7 ? 'down' : 'muted'}>（{expiryLeftText(s.days_to_expiry)}）</span> : null}
        </Descriptions.Item>
        <Descriptions.Item label="设置时间">{s.set_at ? fmtTime(s.set_at) : '—'}</Descriptions.Item>
        <Descriptions.Item label="最近验证">{s.last_verified_at ? fmtTime(s.last_verified_at) : '—'}</Descriptions.Item>
        <Descriptions.Item label="最近错误">
          {s.last_error_code ? <span data-testid="licence-error">{LICENCE_ERROR[s.last_error_code]}（{s.last_error_code}）{s.last_error_at ? ` · ${fmtTime(s.last_error_at)}` : ''}</span> : '—'}
        </Descriptions.Item>
        {s.paused_until ? <Descriptions.Item label="暂停至" span={2}>{fmtTime(s.paused_until)}</Descriptions.Item> : null}
      </Descriptions>

      <Form<FormValues> form={form} layout="vertical" initialValues={initial} onFinish={onFinish} requiredMark={false} autoComplete="off">
        <Form.Item
          name="licence" label={isSet ? '更换证书（留空则只更新下面的档位与到期日）' : '证书'}
          extra={<span data-testid="licence-no-save">浏览器或密码管理器如果询问是否保存，请选择“不保存”。证书只应保存在本站服务端。</span>}
        >
          <Input.Password
            data-testid="licence-input" autoComplete="off" visibilityToggle={false} spellCheck={false}
            // 评审 m2：提示浏览器与常见密码管理器不要保存或自动填充证书
            data-1p-ignore="true" data-lpignore="true" data-bwignore="true" data-form-type="other"
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
          <Button type="primary" htmlType="submit" loading={saving} disabled={closed} data-testid="licence-save">{isSet ? '保存' : '保存并验证'}</Button>
          <Tooltip title={paused ? '管理员暂停期间不能测试' : closed ? '设置暂未开放' : undefined}>
            <Button disabled={!isSet || paused || closed} loading={test.isPending} data-testid="licence-test"
              onClick={() => { reset(); test.mutate(undefined, { onSuccess: () => setMsg('已提交测试，结果稍后显示在状态里'), onError: (e) => { if (isMaintenance(e)) setClosed(true); } }); }}>
              测试证书
            </Button>
          </Tooltip>
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
