/**
 * T-F23 裁定跟进：操作计划表单（契约 v0.2.9 §7.7B）。新建（POST /plans）与新建版本（POST /plans/{id}/versions）共用。
 * 条件类型只给可写的 5 种（indicator、event 本版 → 400 not_supported，不提供入口）。条件都是“计划条件”（hypothesis），不是预测。
 */
import { Alert, Button, Form, Input, Select, Space } from 'antd';
import { Link } from 'react-router';
import { ApiError } from '../../api/client';
import { ENUMS, type Action, type PlanConditionKind, type PlanConditionType } from '../../api/enums';
import { WRITABLE_CONDITION_TYPES } from '../../api/planAlertTypes';
import { ACTION_SHORT, PLAN_CONDITION_KIND } from '../../i18n/labels';
import { PLAN_CONDITION_TYPE } from '../../i18n/planAlertLabels';

const PARAM_LABEL: Partial<Record<PlanConditionType, string>> = { price_above: '价格', price_below: '价格', pct_change: '涨跌幅 %（带符号）', date: '日期 YYYY-MM-DD' };


export function PlanWriteError({ error, onReload }: { error: unknown; onReload?: () => void }) {
  if (!(error instanceof ApiError)) return null;
  const d = error.details ?? {};
  if (error.code === 'CONFLICT' && typeof d.existing_id === 'string') {
    return <Alert type="warning" showIcon data-testid="plan-dup" title={<>同一证券已有相同动作的进行中计划，<Link to={`/plans/${d.existing_id}`}>打开已有计划</Link></>} />;
  }
  if (error.code === 'VERSION_CONFLICT') {
    return (
      <Alert type="warning" showIcon data-testid="plan-version-conflict"
        title={`计划已被修改（当前为第 ${String(d.current_version_no ?? '?')} 版），本次修改没有保存。`}
        action={onReload ? <Button size="small" onClick={onReload} data-testid="plan-version-reload">载入最新版本</Button> : undefined} />
    );
  }
  if (error.code === 'INVALID_STATE_TRANSITION') return <Alert type="error" showIcon data-testid="plan-terminal" title="计划已结束（已完成或已取消），不能再修改或关闭。" />;
  if (error.status === 400) return <Alert type="error" showIcon data-testid="plan-invalid" title="有字段未通过校验，请按提示修改。" />;
  return <Alert type="error" showIcon title={error.message} />;
}

export function PlanFormFields({ create, versioning }: { create?: boolean; versioning?: boolean }) {
  return (
    <>
      {create ? (
        <Form.Item name="security_code" label="证券代码" rules={[{ required: true, message: '请填写证券代码' }]}>
          <Input placeholder="如 600000.SH" data-testid="plan-f-code" />
        </Form.Item>
      ) : null}
      {versioning ? (
        <Form.Item name="change_reason" label="修改原因" rules={[{ required: true, message: '请填写修改原因' }, { max: 200 }]}>
          <Input maxLength={200} data-testid="plan-f-reason" />
        </Form.Item>
      ) : null}
      <Space wrap>
        <Form.Item name="action" label="计划动作" rules={[{ required: true }]}>
          <Select<Action> style={{ width: 120 }} options={(ENUMS.action as readonly Action[]).map((a) => ({ value: a, label: ACTION_SHORT[a] }))} data-testid="plan-f-action" />
        </Form.Item>
        <Form.Item name="qty" label="数量（股，可空）"><Input style={{ width: 120 }} data-testid="plan-f-qty" /></Form.Item>
        <Form.Item name="price" label="价格（可空）"><Input style={{ width: 120 }} data-testid="plan-f-price" /></Form.Item>
        <Form.Item name="review_date" label="复核日期（可空）"><Input style={{ width: 140 }} placeholder="YYYY-MM-DD" data-testid="plan-f-review" /></Form.Item>
      </Space>
      <Form.Item name="rationale" label="计划依据" rules={[{ required: true, message: '请填写计划依据' }, { max: 2000 }]}>
        <Input.TextArea rows={2} maxLength={2000} data-testid="plan-f-rationale" />
      </Form.Item>
      <Form.Item name="risks" label="风险（可空）" rules={[{ max: 2000 }]}><Input.TextArea rows={2} maxLength={2000} /></Form.Item>
      <div className="muted small" style={{ marginBottom: 6 }}>计划条件（最多 20 条）：条件只是你的假设，满足时系统只提示“发生了什么”，不会下单，也不会自动关闭计划。</div>
      <Form.List name="conditions">
        {(rows, { add, remove }) => (
          <>
            {rows.map((r) => (
              <Space key={r.key} align="start" wrap data-testid="plan-f-cond">
                <Form.Item name={[r.name, 'kind']} rules={[{ required: true }]}>
                  <Select<PlanConditionKind> style={{ width: 110 }} options={(ENUMS.plan_condition_kind as readonly PlanConditionKind[]).map((k) => ({ value: k, label: PLAN_CONDITION_KIND[k] }))} />
                </Form.Item>
                <Form.Item name={[r.name, 'type']} rules={[{ required: true }]}>
                  <Select<PlanConditionType> style={{ width: 170 }} options={WRITABLE_CONDITION_TYPES.map((t) => ({ value: t, label: PLAN_CONDITION_TYPE[t] }))} />
                </Form.Item>
                <Form.Item noStyle shouldUpdate>
                  {(f) => {
                    const t = f.getFieldValue(['conditions', r.name, 'type']) as PlanConditionType | undefined;
                    const lab = t ? PARAM_LABEL[t] : undefined;
                    return lab ? (
                      <Form.Item name={[r.name, 'value']} rules={[{ required: true, message: `请填写${lab}` }]}>
                        <Input style={{ width: 150 }} placeholder={lab} />
                      </Form.Item>
                    ) : null;
                  }}
                </Form.Item>
                <Form.Item name={[r.name, 'description']} rules={[{ required: true, message: '请填写条件说明' }, { max: 200 }]}>
                  <Input style={{ width: 300 }} maxLength={200} placeholder="条件说明（1–200 字）" />
                </Form.Item>
                <Button size="small" onClick={() => remove(r.name)}>删除</Button>
              </Space>
            ))}
            <Button size="small" disabled={rows.length >= 20} onClick={() => add({ kind: 'trigger', type: 'price_below', description: '' })} data-testid="plan-f-add-cond">添加计划条件</Button>
          </>
        )}
      </Form.List>
    </>
  );
}
