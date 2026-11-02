/** T-F23 研究候选表单的公共部分：成立条件编辑、请求体整理、服务端错误映射（契约 v0.2.9 §7.7A） */
import { Button, Form, Input, Select, Space, type FormInstance } from 'antd';
import { Link } from 'react-router';
import { ApiError } from '../../api/client';
import { ENUMS, type ConfidenceLevel } from '../../api/enums';
import { errorText } from '../../api/errorPolicy';
import { CANDIDATE_ISSUE, RESEARCH_STATUS } from '../../i18n/candidateLabels';
import { CONF_LEVEL } from '../../i18n/labels';
import type { ResearchCandidateStatus } from '../../api/enums';
import { MAX_CONDITIONS } from './candidateFormUtils';

/** 成立条件（固定为“假设”）：文字 1–200 字；验证日期与验证方式至少填一项 */
export function ConditionsEditor({ form }: { form: FormInstance }) {
  return (
    <Form.List name="conditions_to_hold">
      {(items, { add, remove }) => (
        <div data-testid="conditions-editor">
          {items.map(({ key, name }) => (
            <div key={key} className="cand-cond-edit" data-testid={`cond-edit-${name}`}>
              <Form.Item name={[name, 'text']} label={`成立条件 ${name + 1}（假设）`} rules={[
                { required: true, whitespace: true, message: '请填写条件' },
                { max: 200, message: '至多 200 字' },
              ]}>
                <Input maxLength={200} showCount placeholder="例如：下季度毛利率不再下降" data-testid={`cond-text-${name}`} />
              </Form.Item>
              <Space wrap align="start">
                <Form.Item name={[name, 'verify_by']} label="验证日期" dependencies={[['conditions_to_hold', name, 'verify_method']]}>
                  <Input type="date" style={{ width: 160 }} data-testid={`cond-by-${name}`} />
                </Form.Item>
                <Form.Item
                  name={[name, 'verify_method']} label="验证方式"
                  dependencies={[['conditions_to_hold', name, 'verify_by']]}
                  rules={[
                    { max: 200, message: '至多 200 字' },
                    {
                      validator: async (_r, v: string | undefined) => {
                        const by = form.getFieldValue(['conditions_to_hold', name, 'verify_by']) as string | undefined;
                        if (!by?.trim() && !v?.trim()) throw new Error(CANDIDATE_ISSUE.verification_required);
                      },
                    },
                  ]}
                >
                  <Input maxLength={200} style={{ width: 280 }} placeholder="例如：查看三季报" data-testid={`cond-method-${name}`} />
                </Form.Item>
                <Form.Item name={[name, 'confidence']} label="把握">
                  <Select<ConfidenceLevel> allowClear style={{ width: 90 }} placeholder="未填"
                    options={(ENUMS.confidence_level as readonly ConfidenceLevel[]).map((c) => ({ value: c, label: CONF_LEVEL[c].text }))} />
                </Form.Item>
                <Button size="small" type="link" danger onClick={() => remove(name)} data-testid={`cond-remove-${name}`}>删除</Button>
              </Space>
            </div>
          ))}
          <Button size="small" disabled={items.length >= MAX_CONDITIONS} onClick={() => add({ text: '', verify_by: '', verify_method: '', confidence: null })} data-testid="cond-add">
            添加成立条件（{items.length}/{MAX_CONDITIONS}）
          </Button>
        </div>
      )}
    </Form.List>
  );
}


/** 409 与其他错误的提示；CONFLICT 带 existing_id 时给出已有候选的链接 */
export function CandidateWriteError({ error, onReload }: { error: unknown; onReload?: () => void }) {
  if (error instanceof ApiError) {
    const d = error.details ?? {};
    if (error.code === 'CONFLICT' && typeof d.existing_id === 'string') {
      return (
        <div className="error-text small" role="alert" data-testid="cand-conflict">
          该证券已有进行中的研究候选（每只证券同时只保留一个），<Link to={`/candidates/${d.existing_id}`} data-testid="cand-existing-link">查看已有候选</Link>
        </div>
      );
    }
    if (error.code === 'VERSION_CONFLICT') {
      return (
        <div className="error-text small" role="alert" data-testid="cand-version-conflict">
          已有更新的第 {String(d.current_version_no ?? '?')} 版（可能在其他窗口修改过），本次未保存。
          {onReload ? <Button size="small" type="link" onClick={onReload} data-testid="cand-reload">载入最新版本</Button> : null}
        </div>
      );
    }
    if (error.code === 'INVALID_STATE_TRANSITION') {
      const from = d.from as ResearchCandidateStatus | undefined;
      return (
        <div className="error-text small" role="alert" data-testid="cand-terminal-error">
          研究候选已{from && from in RESEARCH_STATUS ? `是“${RESEARCH_STATUS[from].text}”` : '结束'}，不能再新建版本；需要重新研究请新建候选。
        </div>
      );
    }
    if (error.code === 'VALIDATION_ERROR') return null;
  }
  return <div className="error-text small" role="alert" data-testid="cand-error">{errorText(error)}</div>;
}
