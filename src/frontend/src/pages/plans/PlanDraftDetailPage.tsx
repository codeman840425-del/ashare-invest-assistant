import { useState } from 'react';
import { Alert, Button, Checkbox, Input, Modal, Radio, Space, Tag, type ButtonProps } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { Link, useNavigate, useParams } from 'react-router';
import { ApiError } from '../../api/client';
import { stateErrorText } from '../../lib/stateTransition';
import { useConfirmPlanDraft, useCreatePlanDraft, useDiscardPlanDraft, usePlanDraft } from '../../api/planQueries';
import type { ChecklistAnswerValue, PlanDraft } from '../../api/planTypes';
import { ActionBadge, ErrorBox, Loading } from '../../components/common';
import { CardDisclaimer } from '../../components/RiskDisclosure';
import { EPISTEMIC, PLAN_DRAFT_STATUS, RISK_CONTROL, RISK_LEVEL } from '../../i18n/labels';
import { fmtNum, fmtTime } from '../../lib/format';
import { canAct, canRegenerate, deviationFields, lotWarning, missingRequired, priceError, qtyError } from '../../lib/planDraft';

const ANSWERS: { value: ChecklistAnswerValue; label: string }[] = [
  { value: 'yes', label: '是' },
  { value: 'no', label: '否' },
  { value: 'unsure', label: '不确定' },
];
const FIELD_TEXT: Record<string, string> = { chosen_qty: '数量', chosen_price: '价格' };

/** 计划草案详情（契约 v0.2.8 §7.7）：确认（判断清单 + 风险确认 + 偏离二次确认）、放弃、失效后重新生成 */
export function PlanDraftDetailPage() {
  const { id = '' } = useParams();
  const q = usePlanDraft(id);
  return (
    <div className="page-scroll page" data-testid="plan-draft-page">
      <div style={{ marginBottom: 8 }}>
        <Link to="/plan-drafts" className="small"><ArrowLeftOutlined /> 计划草案</Link>
      </div>
      {q.isPending ? <Loading /> : q.isError ? <ErrorBox error={q.error} /> : <DraftView key={q.data.id} d={q.data} />}
      <CardDisclaimer />
    </div>
  );
}

function DraftView({ d }: { d: PlanDraft }) {
  const st = PLAN_DRAFT_STATUS[d.status];
  return (
    <>
      <div className="sig-head" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
        <h2 className="page-title" style={{ margin: 0 }}>{d.name} <span className="mono muted">{d.security_code}</span></h2>
        <ActionBadge action={d.action} />
        <Tag color={st.color} data-testid="draft-status">{st.text}</Tag>
        <span className="muted small">有效至 <span className="mono">{d.valid_until ? fmtTime(d.valid_until) : '—'}</span> · 生成于 <span className="mono">{fmtTime(d.created_at)}</span></span>
      </div>
      <StatusBanner d={d} />
      <div className="plan-grid">
        <div>
          <Figures d={d} />
          <section className="panel sig-panel">
            <h4>风险提示</h4>
            {d.risk_flags.length ? d.risk_flags.map((f, i) => (
              <div key={i} className="tw"><Tag color={RISK_LEVEL[f.level].color}>{RISK_LEVEL[f.level].text}</Tag>{RISK_CONTROL[f.control]}：{f.message}</div>
            )) : <span className="muted small">无</span>}
            <h4 style={{ marginTop: 8 }}>来源候选信号</h4>
            <Space wrap size={4}>
              {d.signal_ids.map((s) => <Link key={s} to={`/candidate-signals/${s}`} className="mono small" data-testid="draft-signal-link">{s.slice(-8)}</Link>)}
            </Space>
          </section>
        </div>
        <div>{canAct(d.status) ? <ConfirmForm d={d} /> : <ReadonlyChecklist d={d} />}</div>
      </div>
    </>
  );
}

function StatusBanner({ d }: { d: PlanDraft }) {
  const nav = useNavigate();
  const regen = useCreatePlanDraft();
  if (canRegenerate(d.status)) {
    return (
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 12 }}
        data-testid="draft-stale"
        message={d.status === 'stale' ? '生成草案后行情、持仓或规则条件已变化，该草案已失效，不能再确认或修改' : '该草案已过有效期，不能再确认或修改'}
        description={
          <div>
            <div className="small">可以按原候选信号重新生成一份新草案；新草案与本草案互不关联，本草案保持不变。</div>
            {regen.isError ? <div className="error-text small" data-testid="regen-error">{stateErrorText(regen.error, 'signal', { regen: true })}</div> : null}
          </div>
        }
        action={
          <Button
            size="small"
            loading={regen.isPending}
            onClick={() => regen.mutate(d.signal_ids, { onSuccess: (n) => nav(`/plan-drafts/${n.id}`) })}
            data-testid="regen-btn"
          >
            重新生成草案
          </Button>
        }
      />
    );
  }
  if (d.status === 'confirmed') return <Alert type="success" showIcon style={{ marginBottom: 12 }} message="该草案已确认并生成交易计划" description={<Link to="/plans">查看计划</Link>} data-testid="draft-confirmed" />;
  if (d.status === 'discarded') return <Alert type="info" showIcon style={{ marginBottom: 12 }} message="你已放弃该草案" data-testid="draft-discarded" />;
  return null;
}

function Figures({ d }: { d: PlanDraft }) {
  const u = d.user_context_snapshot;
  return (
    <section className="panel sig-panel" data-testid="draft-figures">
      <h4>草案区间</h4>
      <div className="sc-metrics">
        <div><label>数量区间（股）</label><b className="mono" data-testid="qty-range">{d.qty_range.min}–{d.qty_range.max}</b><span className="muted small">每手 {d.qty_range.lot}</span></div>
        <div><label>价格区间</label><b className="mono" data-testid="price-range">{d.price_range.low}–{d.price_range.high}</b></div>
        <div><label>止损</label><b className="mono down">{d.stops.stop_loss ?? '—'}</b></div>
        <div><label>止盈</label><b className="mono up">{d.stops.take_profit ?? '—'}</b></div>
        <div><label>时间止损</label><b className="mono">{d.stops.time_stop_days != null ? `${d.stops.time_stop_days} 日` : '—'}</b></div>
        <div><label>最大亏损 <Tag>估算</Tag></label><b className="mono">{fmtNum(d.max_loss_amount)}</b><span className="muted small">占总资产 {d.max_loss_pct}%</span></div>
        <div><label>费用 <Tag color={EPISTEMIC[d.fee_estimate.epistemic_type].color}>{EPISTEMIC[d.fee_estimate.epistemic_type].text}</Tag></label><b className="mono">{fmtNum(d.fee_estimate.amount)}</b></div>
      </div>
      <h4 style={{ marginTop: 8 }}>生成时的持仓与资金</h4>
      <div className="sc-metrics">
        <div><label>持仓</label><b className="mono">{u.holding_qty}</b></div>
        <div><label>可卖</label><b className="mono">{u.sellable_qty}</b></div>
        <div><label>可用资金</label><b className="mono">{fmtNum(u.cash)}</b></div>
        <div><label>所属行业占比</label><b className="mono">{u.sector_pct}%</b></div>
      </div>
      <div className="muted small">以上为生成草案那一刻的快照；下单前请在券商端核对实时价格、可用资金与可卖数量。</div>
    </section>
  );
}

function ReadonlyChecklist({ d }: { d: PlanDraft }) {
  return (
    <section className="panel sig-panel">
      <h4>判断清单</h4>
      {d.judgment_checklist.map((c) => <div key={c.id} className="small">· {c.question}{c.required ? <span className="muted">（必答）</span> : null}</div>)}
    </section>
  );
}

function ConfirmForm({ d }: { d: PlanDraft }) {
  const nav = useNavigate();
  const confirm = useConfirmPlanDraft(d.id);
  const discard = useDiscardPlanDraft(d.id);
  const [qty, setQty] = useState(d.qty_range.min);
  const [price, setPrice] = useState(d.price_range.low);
  const [answers, setAnswers] = useState<Record<string, ChecklistAnswerValue | undefined>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [riskAck, setRiskAck] = useState(false);
  const [devAck, setDevAck] = useState(false);
  const [review, setReview] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [discardNote, setDiscardNote] = useState('');

  const qErr = qtyError(qty);
  const pErr = priceError(price);
  const dev = deviationFields(d, qty, price);
  const missing = missingRequired(d, answers);
  const doubtful = d.judgment_checklist.filter((c) => c.required && (answers[c.id] === 'no' || answers[c.id] === 'unsure'));
  const serverMissing = confirm.error instanceof ApiError && confirm.error.code === 'CHECKLIST_INCOMPLETE' ? ((confirm.error.details?.missing as string[] | undefined) ?? []) : [];
  const ready = !qErr && !pErr && !missing.length && riskAck && (!dev.length || devAck);
  const blockers = [
    qErr, pErr,
    missing.length ? `判断清单还有 ${missing.length} 项必答未作答` : null,
    !riskAck ? '请勾选风险确认' : null,
    dev.length && !devAck ? '请确认偏离草案区间' : null,
  ].filter(Boolean) as string[];

  const submit = () =>
    confirm.mutate(
      {
        checklist_answers: d.judgment_checklist.flatMap((c) => {
          const a = answers[c.id];
          if (!a) return [];
          const note = (notes[c.id] ?? '').trim();
          return [note ? { id: c.id, answer: a, note } : { id: c.id, answer: a }];
        }),
        risk_ack: true,
        chosen_qty: qty.trim(),
        chosen_price: price.trim(),
        deviation_ack: dev.length > 0 && devAck,
      },
      { onSuccess: (r) => nav(`/plans/${r.plan_id}`) },
    );

  return (
    <section className="panel sig-panel" data-testid="confirm-form">
      <h4>确认计划</h4>
      <div className="plan-inputs">
        <label className="small">数量（股）
          <Input value={qty} onChange={(e) => { setQty(e.target.value); setDevAck(false); }} status={qErr ? 'error' : undefined} inputMode="numeric" data-testid="chosen-qty" />
        </label>
        <label className="small">价格
          <Input value={price} onChange={(e) => { setPrice(e.target.value); setDevAck(false); }} status={pErr ? 'error' : undefined} inputMode="decimal" data-testid="chosen-price" />
        </label>
      </div>
      {qErr || pErr ? <div className="error-text small">{qErr ?? pErr}</div> : null}
      {lotWarning(d, qty) ? <div className="muted small" data-testid="lot-warning">{lotWarning(d, qty)}</div> : null}
      {dev.length ? (
        <Alert
          type="warning"
          showIcon
          style={{ margin: '8px 0' }}
          data-testid="deviation-alert"
          message={`${dev.map((f) => FIELD_TEXT[f]).join('、')}超出草案区间`}
          description={<Checkbox checked={devAck} onChange={(e) => setDevAck(e.target.checked)} data-testid="deviation-ack">我确认按偏离草案区间的{dev.map((f) => FIELD_TEXT[f]).join('、')}生成计划</Checkbox>}
        />
      ) : null}

      <h4 style={{ marginTop: 8 }}>判断清单</h4>
      <div className="muted small" style={{ marginBottom: 4 }}>请按你自己的判断作答，标“必答”的每一项都要回答。</div>
      {d.judgment_checklist.map((c) => (
        <div key={c.id} className={`check-item${serverMissing.includes(c.id) ? ' missing' : ''}`} data-testid={`check-${c.id}`}>
          <div className="small">{c.question}{c.required ? <Tag color="red" style={{ marginLeft: 6 }}>必答</Tag> : <span className="muted">（选答）</span>}</div>
          <Space wrap>
            <Radio.Group
              size="small"
              optionType="button"
              value={answers[c.id]}
              onChange={(e) => setAnswers({ ...answers, [c.id]: e.target.value as ChecklistAnswerValue })}
              options={ANSWERS}
              data-testid={`answer-${c.id}`}
            />
            <Input size="small" style={{ width: 220 }} maxLength={200} placeholder="可选：备注" value={notes[c.id] ?? ''} onChange={(e) => setNotes({ ...notes, [c.id]: e.target.value })} data-testid={`note-${c.id}`} />
          </Space>
        </div>
      ))}
      {doubtful.length ? (
        <Alert type="info" showIcon style={{ margin: '8px 0' }} data-testid="doubt-alert" message={`你对 ${doubtful.length} 项必答选择了“否”或“不确定”。可以继续确认，但建议先想清楚再操作。`} />
      ) : null}

      <Checkbox checked={riskAck} onChange={(e) => setRiskAck(e.target.checked)} style={{ marginTop: 8 }} data-testid="risk-ack">
        我已了解：草案由规则自动生成，仅供参考；最大亏损和费用为估算；交易由我在券商端自行完成，盈亏自负。
      </Checkbox>

      {confirm.isError ? <div className="error-text small" style={{ marginTop: 8 }} data-testid="confirm-error">{stateErrorText(confirm.error, 'draft')}{fieldsOf(confirm.error)}</div> : null}
      <Space style={{ marginTop: 12 }} wrap>
        <Button type="primary" disabled={!ready} onClick={() => setReview(true)} data-testid="confirm-btn">确认并生成计划</Button>
        <Button danger onClick={() => { discard.reset(); setDiscardNote(''); setDiscardOpen(true); }} data-testid="discard-btn">放弃草案</Button>
      </Space>
      {!ready && blockers.length ? <div className="muted small" style={{ marginTop: 6 }} data-testid="confirm-blockers">还差：{blockers.join('；')}</div> : null}

      <Modal
        open={review}
        title="再次确认"
        okText="确认生成计划"
        okButtonProps={{ loading: confirm.isPending, 'data-testid': 'review-ok' } as ButtonProps}
        onOk={() => { setReview(false); submit(); }}
        onCancel={() => setReview(false)}
        destroyOnHidden
      >
        <div data-testid="review-summary">
          <div>{d.name} <span className="mono">{d.security_code}</span></div>
          <div>数量 <b className="mono">{qty}</b> 股 · 价格 <b className="mono">{price}</b></div>
          {dev.length ? <div className="warn-text small">{dev.map((f) => FIELD_TEXT[f]).join('、')}超出草案区间（已确认偏离）</div> : null}
          <div className="muted small" style={{ marginTop: 8 }}>确认后生成交易计划，本草案不能再修改。计划只是你的记录，不会自动下单。</div>
        </div>
      </Modal>
      <Modal
        open={discardOpen}
        title="放弃计划草案"
        okText="确认放弃"
        okButtonProps={{ danger: true, loading: discard.isPending, 'data-testid': 'discard-ok' } as ButtonProps}
        onOk={() => discard.mutate(discardNote.trim() || null, { onSuccess: () => setDiscardOpen(false) })}
        onCancel={() => setDiscardOpen(false)}
        destroyOnHidden
      >
        <div className="muted small" style={{ marginBottom: 8 }}>放弃后该草案不能再确认；候选信号仍可再次拟定草案。</div>
        <Input.TextArea rows={3} maxLength={200} showCount value={discardNote} onChange={(e) => setDiscardNote(e.target.value)} placeholder="可选：放弃原因" data-testid="discard-note" />
        {discard.isError ? <div className="error-text" style={{ marginTop: 8 }} data-testid="discard-error">{stateErrorText(discard.error, 'draft')}</div> : null}
      </Modal>
    </section>
  );
}

/** DEVIATION_ACK_REQUIRED / CHECKLIST_INCOMPLETE 的 details 补充说明 */
function fieldsOf(e: unknown): string {
  if (!(e instanceof ApiError)) return '';
  if (e.code === 'DEVIATION_ACK_REQUIRED') {
    const f = (e.details?.fields as string[] | undefined) ?? [];
    return f.length ? `（${f.map((x) => FIELD_TEXT[x] ?? x).join('、')}）` : '';
  }
  if (e.code === 'CHECKLIST_INCOMPLETE') {
    const m = (e.details?.missing as string[] | undefined) ?? [];
    return m.length ? `（${m.length} 项）` : '';
  }
  return '';
}
