import { useState } from 'react';
import { Alert, Button, Checkbox, Radio, Result, Steps } from 'antd';
import { useNavigate, useSearchParams } from 'react-router';
import { useMe } from '../../api/queries';
import { useConsent, useRiskAssessment } from '../../api/accountQueries';
import type { ConsentKey } from '../../api/accountTypes';
import { ErrorBox, Loading } from '../../components/common';
import { CONSENT_ORDER, CONSENT_TEXT, CONSENT_VERSION, RISK_LEVEL_TEXT, RISK_QUESTIONS } from '../../i18n/accountLabels';
import { safeNext } from '../../lib/auth';
import { AuthLayout } from './AuthLayout';

const CHOICES = ['a', 'b', 'c', 'd'] as const;

/**
 * 开通引导（plan I2）：同意条款 + 风险测评。403 CONSENT_REQUIRED 与首次登录都落到这里，完成后回到 ?next=。
 * 已同意的条款不再重复提交；测评可重做（覆盖旧结果）。
 */
export function OnboardingPage() {
  const [sp] = useSearchParams();
  const next = safeNext(sp.get('next'));
  const navigate = useNavigate();
  const me = useMe();
  const consent = useConsent();
  const risk = useRiskAssessment();
  const [checked, setChecked] = useState<ConsentKey[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [redo, setRedo] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  if (me.isPending) return <AuthLayout title="开通引导"><Loading /></AuthLayout>;
  if (me.isError) return <AuthLayout title="开通引导"><ErrorBox error={me.error} /></AuthLayout>;
  const u = me.data;
  const missingConsents = CONSENT_ORDER.filter((k) => !u.consents[k]);
  const step = missingConsents.length ? 0 : !u.risk_assessment || redo ? 1 : 2;

  const submitConsents = async () => {
    setErr(null);
    try {
      for (const key of missingConsents) await consent.mutateAsync({ key, version: CONSENT_VERSION });
    } catch (e) {
      setErr(e);
    }
  };
  const submitRisk = () => {
    setErr(null);
    risk.mutate({ answers: RISK_QUESTIONS.map((q) => ({ q_id: q.q_id, choice: answers[q.q_id] })) }, { onSuccess: () => setRedo(false), onError: setErr });
  };

  return (
    <AuthLayout title="开通引导" wide testId="onboarding-page">
      <Steps size="small" current={step} style={{ marginBottom: 16 }} items={[{ title: '阅读并同意' }, { title: '风险测评' }, { title: '完成' }]} />
      {err ? <ErrorBox error={err} /> : null}
      {step === 0 ? (
        <div data-testid="onboarding-consents">
          <p className="muted">使用候选信号、规则信号和计划条件相关功能前，需要先阅读并同意以下条款。</p>
          {CONSENT_ORDER.map((k) => {
            const done = !!u.consents[k];
            return (
              <div key={k} className="consent-item">
                <Checkbox
                  checked={done || checked.includes(k)}
                  disabled={done}
                  onChange={(e) => setChecked((c) => (e.target.checked ? [...c, k] : c.filter((x) => x !== k)))}
                  data-testid={`consent-${k}`}
                >
                  <b>{CONSENT_TEXT[k].title}</b>
                  {done ? <span className="muted">（已同意 {u.consents[k]?.version}）</span> : null}
                </Checkbox>
                <div className="muted consent-summary">{CONSENT_TEXT[k].summary}</div>
              </div>
            );
          })}
          <Button type="primary" block disabled={!missingConsents.every((k) => checked.includes(k))} loading={consent.isPending} onClick={() => void submitConsents()}>
            同意并继续
          </Button>
        </div>
      ) : step === 1 ? (
        <div data-testid="onboarding-risk">
          <p className="muted">测评结果用于决定候选信号的展示范围（如新手封顶），不用于评价任何证券。题库为示例数据。</p>
          {RISK_QUESTIONS.map((q, i) => (
            <div key={q.q_id} className="risk-q">
              <div className="risk-q-title">{i + 1}. {q.title}</div>
              <Radio.Group value={answers[q.q_id]} onChange={(e) => setAnswers((a) => ({ ...a, [q.q_id]: e.target.value as string }))}>
                {q.options.map((o, j) => <Radio key={o} value={CHOICES[j]}>{o}</Radio>)}
              </Radio.Group>
            </div>
          ))}
          <Button type="primary" block disabled={RISK_QUESTIONS.some((q) => !answers[q.q_id])} loading={risk.isPending} onClick={submitRisk}>提交测评</Button>
        </div>
      ) : (
        <Result
          status="success"
          title="开通完成"
          subTitle={<span data-testid="risk-level">风险承受能力：{RISK_LEVEL_TEXT[u.risk_assessment!.level] ?? u.risk_assessment!.level}</span>}
          extra={[
            <Button key="go" type="primary" onClick={() => navigate(next, { replace: true })}>进入系统</Button>,
            <Button key="redo" onClick={() => { setAnswers({}); setRedo(true); }}>重新测评</Button>,
          ]}
        />
      )}
      <Alert type="info" showIcon style={{ marginTop: 12 }} title="本工具只做研究记录与复盘，不提供证券投资咨询，不代客下单。" />
    </AuthLayout>
  );
}
