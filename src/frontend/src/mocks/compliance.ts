/**
 * 示例合规数据（全部虚构，只给 MSW 用）：文书版本（/meta/consent-docs、/legal/*）、风险测评问卷与计分、Me.consents 的推导。
 * 契约 v0.2.4 #3–#6。真实文书与问卷由研究员 T-B15 起草、后端发布脚本写入；本文件不得被 src/mocks/ 以外的代码引用，
 * 也不会进入生产包（scripts/check-dist.mjs 与 src/app/prod-bundle.test.ts 检查，评审 P1）。
 * 计分规则只是演示用的极简版本，不对应 docs/strategies/compliance/risk_questionnaire.yaml 的分值。
 */
import type { ConsentDoc, Effort, Experience, LegalDocument, RiskAnswer, RiskAssessment, RiskQuestionnaire } from '../api/accountTypes';
import type { AssessmentStatus, ConsentKey, LegalDocKey } from '../api/enums';
import type { ConsentState, RiskAssessmentSummary } from '../api/types';

export const CONSENT_KEYS: ConsentKey[] = ['terms', 'privacy', 'signal_risk_disclosure', 'sensitive_financial_info'];
const TITLE: Record<LegalDocKey, string> = {
  terms: '用户协议（示例）',
  privacy: '隐私政策（示例）',
  signal_risk_disclosure: '规则信号风险揭示书（示例）',
  sensitive_financial_info: '个人敏感信息处理单独同意书（示例）',
  site_risk_notice: '全站风险提示（示例）',
};
const REQUIRED_FOR: Record<LegalDocKey, ConsentDoc['required_for']> = {
  terms: ['register'], privacy: ['register'], signal_risk_disclosure: ['register', 'advice'], sensitive_financial_info: ['import'], site_risk_notice: ['display'],
};
/** 示例哈希：明显的占位串，不是任何真实文本的摘要 */
export const demoSha = (key: string, version: string) => `demo-sha256-${key}-${version}`;

export type DocVersions = Record<LegalDocKey, string>;
export const INITIAL_DOC_VERSIONS: DocVersions = {
  terms: '1.0.0', privacy: '1.0.0', signal_risk_disclosure: '1.0.0', sensitive_financial_info: '1.0.0', site_risk_notice: '1.0.0',
};

export function consentDocs(v: DocVersions): ConsentDoc[] {
  return (Object.keys(TITLE) as LegalDocKey[]).map((key) => {
    const unversioned = v[key] === 'unversioned';
    return {
      key, version: v[key], version_no: unversioned ? null : Number(v[key].split('.')[0]), title: TITLE[key],
      summary: `${TITLE[key].replace('（示例）', '')}要点摘要（示例数据）`, effective_at: unversioned ? null : '2026-10-01T00:00:00+08:00',
      content_sha256: unversioned ? null : demoSha(key, v[key]), url: unversioned ? null : `/api/v1/legal/${key}`, required_for: REQUIRED_FOR[key],
    };
  });
}

export function legalDocument(key: LegalDocKey, version: string): LegalDocument {
  return {
    key, version, version_no: Number(version.split('.')[0]), title: TITLE[key], summary: `${TITLE[key]}要点（示例数据）`,
    content_md: `## ${TITLE[key]}\n\n本文为界面演示用的示例文本，不是正式文书。\n\n- 本工具只提供按规则计算的候选信号与计划条件，不构成投资建议。\n- 您可以随时在设置中查看已同意的版本。\n`,
    content_sha256: demoSha(key, version), locale: 'zh-CN', change_level: 'major', changelog: '首次发布（示例）',
    effective_at: '2026-10-01T00:00:00+08:00', published_at: '2026-09-25T00:00:00+08:00',
  };
}

const major = (v: string | null) => (v == null ? -1 : v === 'unversioned' ? 0 : Number(v.split('.')[0]));
export type Grants = Partial<Record<ConsentKey, { version: string; accepted_at: string }>>;
/** Me.consents：四个键都有；未同意/已撤回或 MAJOR 变化 → needs_reconsent（versioning.md §2） */
export function consentStates(g: Grants, v: DocVersions): Record<ConsentKey, ConsentState> {
  return Object.fromEntries(CONSENT_KEYS.map((k) => {
    const x = g[k];
    return [k, { version: x?.version ?? null, accepted_at: x?.accepted_at ?? null, current_version: v[k], needs_reconsent: !x || major(x.version) !== major(v[k]) }];
  })) as Record<ConsentKey, ConsentState>;
}

// ---------------- 风险测评（示例问卷） ----------------
const choice = (ids: string, texts: string[]) => texts.map((text, i) => ({ id: ids[i], text }));
export const RISK_QUESTIONNAIRE: RiskQuestionnaire = {
  questionnaire_key: 'risk_profile',
  version: '1.0.0',
  intro: '本问卷用于了解您能承受的波动、投资经验和可投入的时间（示例问卷，不是正式版本）。结果不构成投资建议。',
  groups: [
    { id: 'risk', title: '风险承受（示例）' }, { id: 'experience', title: '投资经验（示例）' },
    { id: 'effort', title: '可投入精力（示例）' }, { id: 'knowledge', title: '产品认知（示例）' },
  ],
  questions: [
    { q_id: 'demo_r1_loss', group: 'risk', type: 'single', required: true, title: '投入的资金出现亏损时，您最多能接受亏损多少？（示例）',
      choices: choice('ABCDE', ['不能接受任何亏损', '5% 以内', '5%–15%', '15%–30%', '30% 以上']) },
    { q_id: 'demo_r2_drop', group: 'risk', type: 'single', required: true, title: '持有的股票一个月内下跌 20%，您最可能怎么做？（示例）',
      choices: choice('ABCD', ['立即全部卖出', '卖出一部分', '继续持有观察', '按事先写好的计划条件处理']) },
    { q_id: 'demo_e1_years', group: 'experience', type: 'single', required: true, title: '您投资 A 股的年限（示例）',
      choices: choice('ABCD', ['没有经验', '1 年以内', '1–5 年', '5 年以上']) },
    { q_id: 'demo_e0_self', group: 'experience', type: 'single', required: false, title: '您如何评价自己的投资经验？（自评，示例）',
      choices: choice('ABC', ['入门', '有一定经验', '经验丰富']) },
    { q_id: 'demo_t1_time', group: 'effort', type: 'single', required: true, title: '交易日您能花多少时间看盘或复盘？（示例）',
      choices: choice('ABC', ['每天 15 分钟以内', '每天 15–60 分钟', '盘中可以随时查看']) },
    { q_id: 'demo_k4_understand', group: 'knowledge', type: 'single', required: true, title: '本工具给出的规则信号能否确定股票未来的涨跌？（示例）',
      choices: choice('AB', ['能，按信号操作就能获利', '不能，只是按规则计算的参考信息，可能出错']) },
  ],
};
/** 理解确认题：答错 → 400 details.reason="understanding_required"（不入库） */
export const UNDERSTANDING_Q = { q_id: 'demo_k4_understand', correct: 'B' };

const idx = (answers: RiskAnswer[], q: string) => {
  const a = answers.find((x) => x.q_id === q);
  return a ? a.choice.charCodeAt(0) - 65 : 0;
};
const DAY = 86_400_000;
export function scoreAssessment(id: string, answers: RiskAnswer[], at: string): RiskAssessment {
  const r = idx(answers, 'demo_r1_loss') + idx(answers, 'demo_r2_drop'); // 0–7
  const risk = Math.min(5, Math.max(1, Math.round(r / 7 * 4) + 1));
  const exp: Experience = (['novice', 'novice', 'intermediate', 'advanced'] as const)[idx(answers, 'demo_e1_years')] ?? 'novice';
  const effort: Effort = (['low', 'medium', 'high'] as const)[idx(answers, 'demo_t1_time')] ?? 'low';
  const flags = [
    ...(idx(answers, 'demo_r1_loss') === 0 ? ['no_loss_tolerance'] : []),
    ...(idx(answers, 'demo_e0_self') === 2 && exp === 'novice' ? ['self_report_higher'] : []),
  ];
  return {
    assessment_id: id, questionnaire_version: RISK_QUESTIONNAIRE.version, submitted_at: at,
    expires_at: new Date(Date.parse(at) + 365 * DAY).toISOString(), status: 'valid',
    derived: {
      risk_tolerance: { value: flags.includes('no_loss_tolerance') ? 1 : risk, rule_ids: ['demo_RT_sum', ...(flags.includes('no_loss_tolerance') ? ['demo_RT_cap_noloss'] : [])] },
      experience: { value: exp, rule_ids: ['demo_EX_years'] },
      effort: { value: effort, rule_ids: ['demo_EF_time'] },
    },
    flags, needs_retest: false,
  };
}
/** 状态按时间计算（不存库）：有效期 365 天、提前 30 天提醒、宽限 30 天（问题 40 默认值） */
export function assessmentStatus(a: RiskAssessment, now: string, latest: boolean): AssessmentStatus {
  if (!latest) return 'superseded';
  const t = Date.parse(now);
  const exp = Date.parse(a.expires_at);
  if (t < exp - 30 * DAY) return 'valid';
  if (t < exp) return 'expiring';
  if (t < exp + 30 * DAY) return 'grace';
  return 'expired';
}
export const withStatus = (list: RiskAssessment[], a: RiskAssessment, now: string): RiskAssessment => {
  const status = assessmentStatus(a, now, list[list.length - 1] === a);
  return { ...a, status, needs_retest: a.needs_retest || status === 'expiring' || status === 'grace' || status === 'expired' };
};
export function assessmentSummary(list: RiskAssessment[], now: string): RiskAssessmentSummary | null {
  const last = list[list.length - 1];
  if (!last) return null;
  const a = withStatus(list, last, now);
  return {
    assessment_id: a.assessment_id, questionnaire_version: a.questionnaire_version, risk_tolerance: a.derived.risk_tolerance.value,
    submitted_at: a.submitted_at, expires_at: a.expires_at, status: a.status, needs_retest: a.needs_retest,
  };
}
export const ASSESSMENT_OK: ReadonlySet<AssessmentStatus> = new Set(['valid', 'expiring', 'grace']);
