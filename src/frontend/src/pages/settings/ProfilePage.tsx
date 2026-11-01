import { useState } from 'react';
import { Alert, Button, Checkbox, Form, InputNumber, Radio, Rate, Tag } from 'antd';
import { Link } from 'react-router';
import { useMe } from '../../api/queries';
import { useProfile, useSaveProfile } from '../../api/accountQueries';
import type { ProfileInput } from '../../api/accountTypes';
import { ENUMS, type Horizon } from '../../api/enums';
import { ErrorBox, Loading } from '../../components/common';
import { EFFORT, EXPERIENCE, RISK_LEVEL_TEXT } from '../../i18n/accountLabels';
import { HORIZON } from '../../i18n/labels';
import { applyFieldErrors } from '../../lib/formErrors';

interface FormValues { horizon_pref: Horizon[]; effort: ProfileInput['effort']; risk_tolerance: number | null; experience: ProfileInput['experience']; max_single_position_pct: number }
const FIELDS = ['horizon_pref', 'effort', 'risk_tolerance', 'experience', 'max_single_position_pct'] as const;
const DEFAULTS: FormValues = { horizon_pref: ['swing'], effort: 'medium', risk_tolerance: 3, experience: 'novice', max_single_position_pct: 20 };

/** 投资画像（契约 §7.1 GET/PUT /me/profile，版本化；T-A02 的五个表单项）。画像只影响候选信号的排序与展示范围。 */
export function ProfilePage() {
  const me = useMe();
  const profile = useProfile();
  const save = useSaveProfile();
  const [form] = Form.useForm<FormValues>();
  const [msg, setMsg] = useState<string | null>(null);
  const [other, setOther] = useState<string[]>([]);

  if (profile.isPending) return <Loading />;
  if (profile.isError) return <ErrorBox error={profile.error} />;
  const p = profile.data;
  const initial: FormValues = p
    ? { horizon_pref: p.horizon_pref, effort: p.effort, risk_tolerance: p.risk_tolerance, experience: p.experience, max_single_position_pct: Number(p.max_single_position_pct) }
    : DEFAULTS;

  const onFinish = (v: FormValues) => {
    setMsg(null);
    setOther([]);
    save.mutate(
      { ...v, max_single_position_pct: String(Number(v.max_single_position_pct.toFixed(2))) },
      { onSuccess: (r) => setMsg(`已保存为第 ${r.version_no} 版（旧版本保留）`), onError: (e) => setOther(applyFieldErrors(form, e, FIELDS)) },
    );
  };

  return (
    <div className="page narrow" data-testid="profile-page">
      <h2 className="page-title">
        投资画像 {p ? <Tag className="mono">第 {p.version_no} 版</Tag> : <Tag color="gold">尚未填写</Tag>}
      </h2>
      <p className="muted">画像用于候选信号的周期偏好、新手封顶和仓位上限提示；不会据此给出买卖结论。每次保存生成新版本。</p>
      <div className="kv-line">
        风险测评：{me.data?.risk_assessment ? <b>{RISK_LEVEL_TEXT[me.data.risk_assessment.risk_tolerance]}</b> : <span className="muted">未完成</span>}
        <Link to="/onboarding?next=/settings/profile" style={{ marginLeft: 12 }}>{me.data?.risk_assessment ? '重新测评' : '去完成'}</Link>
      </div>
      {msg ? <Alert type="success" showIcon title={msg} style={{ margin: '12px 0' }} data-testid="profile-saved" /> : null}
      {other.length ? <Alert type="error" showIcon title={other.join('；')} style={{ margin: '12px 0' }} /> : null}
      {save.isError && !other.length ? <ErrorBox error={save.error} prefix="保存失败" /> : null}
      <Form<FormValues> form={form} layout="vertical" initialValues={initial} onFinish={onFinish} requiredMark={false} style={{ marginTop: 12 }}>
        <Form.Item name="horizon_pref" label="关注的周期（可多选）" rules={[{ required: true, type: 'array', min: 1, message: '至少选择一个周期' }]}>
          <Checkbox.Group options={ENUMS.horizon.map((h) => ({ value: h, label: HORIZON[h] }))} />
        </Form.Item>
        <Form.Item name="effort" label="可投入的盯盘精力">
          <Radio.Group>
            {(Object.keys(EFFORT) as (keyof typeof EFFORT)[]).map((k) => <Radio key={k} value={k}>{EFFORT[k].text}<span className="muted">（{EFFORT[k].hint}）</span></Radio>)}
          </Radio.Group>
        </Form.Item>
        <Form.Item name="risk_tolerance" label="风险承受（1 低 – 5 高）" rules={[{ required: true }]}>
          <Rate count={5} />
        </Form.Item>
        <Form.Item name="experience" label="投资经验">
          <Radio.Group>
            {(Object.keys(EXPERIENCE) as (keyof typeof EXPERIENCE)[]).map((k) => <Radio key={k} value={k}>{EXPERIENCE[k].text}</Radio>)}
          </Radio.Group>
        </Form.Item>
        <Form.Item noStyle shouldUpdate={(a, b) => a.experience !== b.experience}>
          {({ getFieldValue }) => <div className="muted form-hint">{EXPERIENCE[(getFieldValue('experience') as FormValues['experience']) ?? 'novice']?.hint}</div>}
        </Form.Item>
        {/* v0.2.4 #7：5–50，最多 2 位小数（评审 m11） */}
        <Form.Item name="max_single_position_pct" label="单只股票最大仓位（%）" extra="用于计划条件里的仓位上限提示，范围 5–50"
          rules={[{ required: true, type: 'number', min: 5, max: 50, message: '请输入 5–50' }]}>
          <InputNumber min={5} max={50} step={1} precision={2} addonAfter="%" style={{ width: 160 }} />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={save.isPending}>保存为新版本</Button>
      </Form>
    </div>
  );
}
