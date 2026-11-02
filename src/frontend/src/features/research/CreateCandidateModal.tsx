/** T-F23 新建研究候选（契约 v0.2.9 §7.7A POST /candidates）：手工、个股页、候选信号卡三种来源 */
import { useState } from 'react';
import { Form, Input, Modal, type ButtonProps } from 'antd';
import { useNavigate } from 'react-router';
import { useCreateCandidate } from '../../api/candidateQueries';
import type { CandidateCreateOrigin } from '../../api/candidateTypes';
import { RESEARCH_ORIGIN } from '../../i18n/candidateLabels';
import { ConditionsEditor, CandidateWriteError } from './candidateForm';
import { applyCandidateErrors, toConditionInputs, type ConditionValues } from './candidateFormUtils';

interface Values { security_code?: string; thesis?: string; conditions_to_hold?: ConditionValues[] }

export function CreateCandidateModal({ open, onClose, origin, securityCode = null, suggestionId = null, title }: {
  open: boolean;
  onClose: () => void;
  origin: CandidateCreateOrigin;
  /** from_stock / suggestion 由入口带入，不可改；manual 由用户填写 */
  securityCode?: string | null;
  suggestionId?: string | null;
  title?: string;
}) {
  const [form] = Form.useForm<Values>();
  const create = useCreateCandidate();
  const nav = useNavigate();
  const [topErrors, setTopErrors] = useState<string[]>([]);
  const submit = (v: Values) => {
    setTopErrors([]);
    create.mutate(
      {
        origin,
        // suggestion 来源不带代码（契约允许 null，取建议的证券），避免与建议不一致的 mismatch
        security_code: origin === 'manual' ? (v.security_code ?? '').trim().toUpperCase() || null : origin === 'suggestion' ? null : securityCode,
        suggestion_id: origin === 'suggestion' ? suggestionId : null,
        thesis: v.thesis?.trim() || null,
        conditions_to_hold: toConditionInputs(v.conditions_to_hold),
      },
      {
        onSuccess: (c) => { onClose(); form.resetFields(); nav(`/candidates/${c.id}`); },
        onError: (e) => setTopErrors(applyCandidateErrors(form, e, ['security_code', 'thesis'])),
      },
    );
  };
  return (
    <Modal
      open={open}
      title={title ?? '新建研究候选'}
      okText="创建"
      cancelText="取消"
      width={720}
      onCancel={() => { create.reset(); setTopErrors([]); onClose(); }}
      onOk={() => form.submit()}
      okButtonProps={{ loading: create.isPending, 'data-testid': 'cand-create-ok' } as ButtonProps}
      destroyOnHidden
    >
      <div data-testid="cand-create-modal">
        <div className="muted small" style={{ marginBottom: 8 }}>
          来源：{RESEARCH_ORIGIN[origin]}{securityCode && origin !== 'manual' ? ` · ${securityCode}` : ''}。
          创建后系统按当时数据生成理由、反证与适配提示并写入快照；研究候选是你的研究记录，不能直接生成计划草案。
        </div>
        <Form<Values> form={form} layout="vertical" onFinish={submit} initialValues={{ conditions_to_hold: [] }}>
          {origin === 'manual' ? (
            <Form.Item name="security_code" label="证券代码" rules={[{ required: true, whitespace: true, message: '请填写证券代码' }]}>
              <Input placeholder="如 600000.SH（ETF、指数不支持）" style={{ width: 240 }} data-testid="cand-code" />
            </Form.Item>
          ) : null}
          <Form.Item name="thesis" label="研究要点（可不填）" rules={[{ max: 2000, message: '至多 2000 字' }]}>
            <Input.TextArea rows={3} maxLength={2000} showCount placeholder="你为什么关注它、想验证什么" data-testid="cand-thesis" />
          </Form.Item>
          <ConditionsEditor form={form} />
        </Form>
        {topErrors.map((t) => <div key={t} className="error-text small" role="alert" data-testid="cand-top-error">{t}</div>)}
        {create.isError ? <CandidateWriteError error={create.error} /> : null}
      </div>
    </Modal>
  );
}
