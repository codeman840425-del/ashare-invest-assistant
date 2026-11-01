import { useState } from 'react';
import { Alert, Button, Checkbox, Radio, Result, Steps } from 'antd';
import { useNavigate, useSearchParams } from 'react-router';
import { useMe } from '../../api/queries';
import { consentBody, useConsent, useConsentDocs, useRiskAssessment, useRiskQuestionnaire } from '../../api/accountQueries';
import type { ConsentKey } from '../../api/accountTypes';
import { ErrorBox, Loading } from '../../components/common';
import { CONSENT_ORDER, CONSENT_TEXT, QUESTIONNAIRE_UNPUBLISHED, RISK_LEVEL_TEXT } from '../../i18n/accountLabels';
import { safeNext } from '../../lib/auth';
import { AuthLayout } from './AuthLayout';

/**
 * 开通引导（plan I2）：同意条款 + 风险测评。403 CONSENT_REQUIRED 与首次登录都落到这里，完成后回到 ?next=。
 * 已同意的条款不再重复提交；测评可重做（覆盖旧结果）。
 * 条款版本与哈希取 /meta/consent-docs（v0.2.4 #3、#4）；问卷只从接口取，未发布时不回退到任何本地题目（评审 P1）。
 * 注意：用户已取消风险测评与同意弹窗（T-F05 取消），本页为 T-F02 已提交代码，只做 v0.2.4 类型对齐，去留等编排者决定（见 reports/T-F02b.md）。
 */
export function OnboardingPage() {
  const [sp] = useSearchParams();
  const next = safeNext(sp.get('next'));
  const navigate = useNavigate();
  const me = useMe();
  const docs = useConsentDocs();
  const [startedAt] = useState(() => new Date().toISOString());
  const consent = useConsent();
  const risk = useRiskAssessment();
  const [checked, setChecked] = useState<ConsentKey[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [redo, setRedo] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const u = me.data;
  const missingConsents = u ? CONSENT_ORDER.filter((k) => u.consents[k]?.needs_reconsent ?? true) : [];
  const step = !u ? 0 : missingConsents.length ? 0 : !u.risk_assessment || redo ? 1 : 2;
  const qn = useRiskQuestionnaire(!!u && step === 1);

  if (me.isPending) return <AuthLayout title="开通引导"><Loading /></AuthLayout>;
  if (me.isError) return <AuthLayout title="开通引导"><ErrorBox error={me.error} /></AuthLayout>;
  const user = me.data;

  const submitConsents = async () => {
    setErr(null);
    try {
      for (const key of missingConsents) await consent.mutateAsync(consentBody(docs.data?.items, key, 'onboarding', 'checkbox_unticked'));
    } catch (e) {
      setErr(e);
    }
  };
  const questions = qn.data?.questions ?? [];
  const submitRisk = () => {
    if (!qn.data) return;
    setErr(null);
    risk.mutate(
      {
        questionnaire_version: qn.data.version,
        answers: questions.filter((q) => answers[q.q_id]).map((q) => ({ q_id: q.q_id, choice: answers[q.q_id] })),
        started_at: startedAt,
        client_duration_s: Math.round((Date.now() - Date.parse(startedAt)) / 1000),
      },
      { onSuccess: () => setRedo(false), onError: setErr },
    );
  };

  return (
    <AuthLayout title="开通引导" wide testId="onboarding-page">
      <Steps size="small" current={step} style={{ marginBottom: 16 }} items={[{ title: '阅读并同意' }, { title: '风险测评' }, { title: '完成' }]} />
      {err ? <ErrorBox error={err} /> : null}
      {step === 0 ? (
        <div data-testid="onboarding-consents">
          <p className="muted">使用候选信号、规则信号和计划条件相关功能前，需要先阅读并同意以下条款。</p>
          {CONSENT_ORDER.map((k) => {
            const done = user.consents[k] ? !user.consents[k].needs_reconsent : false;
            return (
              <div key={k} className="consent-item">
                <Checkbox
                  checked={done || checked.includes(k)}
                  disabled={done}
                  onChange={(e) => setChecked((c) => (e.target.checked ? [...c, k] : c.filter((x) => x !== k)))}
                  data-testid={`consent-${k}`}
                >
                  <b>{CONSENT_TEXT[k].title}</b>
                  {done ? <span className="muted">（已同意 {user.consents[k]?.version}）</span> : null}
                </Checkbox>
                <div className="muted consent-summary">{CONSENT_TEXT[k].summary}</div>
              </div>
            );
          })}
          <Button type="primary" block disabled={docs.isPending || !missingConsents.every((k) => checked.includes(k))} loading={consent.isPending} onClick={() => void submitConsents()}>
            同意并继续
          </Button>
        </div>
      ) : step === 1 ? (
        <div data-testid="onboarding-risk">
          {qn.isPending ? (
            <Loading />
          ) : qn.isError ? (
            <ErrorBox error={qn.error} />
          ) : !qn.data || !questions.length ? (
            <Result status="info" title={QUESTIONNAIRE_UNPUBLISHED} subTitle="题库由合规负责人发布后即可完成测评。在此之前，持仓、导入和行情等功能可以正常使用。"
              extra={<Button onClick={() => navigate('/portfolio', { replace: true })}>先去持仓与账户</Button>} data-testid="questionnaire-unpublished" />
          ) : (
            <>
              <p className="muted">测评结果用于决定候选信号的展示范围（如新手封顶），不用于评价任何证券。问卷版本 <span className="mono">{qn.data.version}</span>。</p>
              {questions.map((q, i) => (
                <div key={q.q_id} className="risk-q">
                  <div className="risk-q-title">{i + 1}. {q.title}</div>
                  <Radio.Group value={answers[q.q_id]} onChange={(e) => setAnswers((a) => ({ ...a, [q.q_id]: e.target.value as string }))}>
                    {q.choices.map((c) => <Radio key={c.id} value={c.id}>{c.text}</Radio>)}
                  </Radio.Group>
                </div>
              ))}
              <Button type="primary" block disabled={questions.some((q) => q.required && !answers[q.q_id])} loading={risk.isPending} onClick={submitRisk}>提交测评</Button>
            </>
          )}
        </div>
      ) : (
        <Result
          status="success"
          title="开通完成"
          subTitle={<span data-testid="risk-level">风险承受能力：{RISK_LEVEL_TEXT[user.risk_assessment!.risk_tolerance] ?? user.risk_assessment!.risk_tolerance}</span>}
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
