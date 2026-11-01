import { useState } from 'react';
import { Alert, Button, Descriptions, Modal, Select, Table, Tag, Tooltip, message } from 'antd';
import { ArrowLeftOutlined, BellOutlined } from '@ant-design/icons';
import {
  CANDIDATE_SIGNALS, QUOTES, SECURITIES, STRATEGIES, nameOf, positionOf, reasonsOf, signalById, suggestionById, suggestionOf,
} from '../mock/data';
import type { Evidence, SuggestionStrategy } from '../types/contract';
import {
  ACTION_FULL, CHECK_ON, DIMENSION, EPISTEMIC, GAP_REASON, HORIZON, LIFECYCLE, ORIGIN, REASON_CODE, RELEASE_KIND,
  RISK_CONTROL, RISK_LEVEL, SIGNAL_STATE, VIEW,
} from '../labels';
import { ActionBadge, ConfidenceTag, ConsensusBadge, DataStatusTag, fmtNum, fmtTime, pctClass, signed } from '../components/common';
import { EvidenceChips, providerText } from '../components/EvidenceChip';
import { go } from '../router';

export function SuggestionDetail({ param }: { param?: string }) {
  const sg = (param && (suggestionById(param) ?? (SECURITIES.some((s) => s.code === param) ? suggestionOf(param) : undefined))) || suggestionOf('600000.SH');
  const code = sg.security_code;
  const q = QUOTES[code];
  const pos = positionOf(code);
  const [draftFor, setDraftFor] = useState<SuggestionStrategy | null>(null);

  const matrixCols = [
    { title: '维度', dataIndex: 'dimension', width: 92, render: (d: keyof typeof DIMENSION) => <b>{DIMENSION[d]}</b> },
    ...sg.strategies.map((s) => ({
      title: (
        <div className="mx-head">
          <span>{STRATEGIES[s.strategy_key].name}</span>
          <ActionBadge action={s.action} tLeg={s.t_leg} />
        </div>
      ),
      key: s.strategy_key,
      render: (_: unknown, row: (typeof sg.dimension_matrix)[number]) => {
        const c = row.cells.find((x) => x.strategy_key === s.strategy_key)!;
        const dv = s.dimension_views.find((v) => v.dimension === row.dimension)!;
        const rule = dv.rules[0];
        return (
          <div className={`mx-cell v-${c.view}`}>
            <span className="mx-view" style={{ color: VIEW[c.view].color }}>{VIEW[c.view].text}</span>
            <span className="mono mx-score">{c.score ?? '—'}</span>
            <span className="mx-ev muted">{c.key_evidence}</span>
            {rule ? <Tooltip title={`规则 ${rule.rule_id}：value=${rule.value} / threshold=${rule.threshold}（evidence ${rule.evidence_id}）`}><span className={`mx-rule ${rule.pass ? 'ok' : 'ng'}`}>{rule.rule_id}{rule.pass ? '✓' : '✗'}</span></Tooltip> : null}
          </div>
        );
      },
    })),
  ];
  const isDiverged = (d: string) => sg.divergence.some((x) => x.dimensions.includes(d as never));

  const evCols = [
    { title: 'ID', dataIndex: 'id', width: 46 },
    { title: '指标 key', dataIndex: 'key', width: 190, render: (v: string) => <span className="mono">{v}</span> },
    { title: '值', width: 110, render: (_: unknown, e: Evidence) => <span className="mono">{String(e.value)}{e.unit ? ` ${e.unit}` : ''}</span> },
    { title: '类型', width: 64, render: (_: unknown, e: Evidence) => <Tag color={EPISTEMIC[e.epistemic_type].color}>{EPISTEMIC[e.epistemic_type].text}</Tag> },
    { title: '来源', width: 210, render: (_: unknown, e: Evidence) => <span className="mono small">{providerText(e)}</span> },
    { title: '数据时间', width: 120, render: (_: unknown, e: Evidence) => <span className="mono small">{fmtTime(e.data_as_of)}</span> },
    { title: '抓取时间', width: 130, render: (_: unknown, e: Evidence) => <span className="mono small">{fmtTime(e.fetched_at)}</span> },
  ];

  return (
    <div className="detail">
      <div className="detail-head">
        <Button size="small" icon={<ArrowLeftOutlined />} onClick={() => go('/terminal')}>终端</Button>
        <Select
          size="small" value={code} style={{ width: 170 }}
          options={SECURITIES.map((s) => ({ value: s.code, label: `${s.name} ${s.code}` }))}
          onChange={(v) => go(`/suggestions/${suggestionOf(v).id}`)}
        />
        <span className="q-name">{nameOf(code)}</span>
        <span className={`q-price mono ${pctClass(q.change_pct)}`}>{q.price}</span>
        <span className={`mono ${pctClass(q.change_pct)}`}>{signed(q.change_pct)}%</span>
        <DataStatusTag status={sg.data_status} asOf={sg.data_as_of} />
        <span className="muted small">候选信号卡 · {ORIGIN[sg.origin]} · 生成 {fmtTime(sg.created_at)} · 快照 {sg.snapshot_id.slice(0, 8)} · {sg.feature_set_version}</span>
        <span className="spacer" />
        {pos ? <span className="small">持仓 <b className="mono">{fmtNum(pos.qty, 0)}</b> 股 · 可卖 <b className="mono">{fmtNum(pos.sellable_qty, 0)}</b> · 成本 <b className="mono">{pos.cost}</b> · 占比 <b className={`mono ${Number(pos.weight_pct) > 20 ? 'warn' : ''}`}>{pos.weight_pct}%</b></span> : <span className="muted small">未持仓</span>}
        <span className="small">适合周期：{sg.horizon_assessment.suitable.map((h) => <Tag key={h}>{HORIZON[h]}</Tag>)}</span>
        <ConsensusBadge consensus={sg.consensus} />
        <Tag color={sg.executability.status === 'blocked' ? 'orange' : sg.executability.status === 'executable' ? 'green' : 'default'}>
          {sg.executability.status === 'blocked' ? `部分不可执行（${sg.executability.reason_ids.length} 项原因）` : sg.executability.status === 'executable' ? '可拟定计划草案' : '无方向性候选信号'}
        </Tag>
      </div>

      {sg.divergence.length ? (
        <Alert
          className="div-alert" type="warning" showIcon
          message={<span><b>存在分歧，不合并为单一结论</b>：{Object.entries(sg.consensus.actions).map(([a, n]) => `${ACTION_FULL[a as keyof typeof ACTION_FULL].replace(/^规则信号：|（候选）$/g, '')} ×${n}`).join('　')}　—— 以下各策略并列展示，请结合计划条件自行判断。</span>}
          description={
            <div className="div-list">
              {sg.divergence.map((d, i) => (
                <div key={i}>
                  <Tag color="orange">{d.dimensions.map((x) => DIMENSION[x]).join(' / ')}</Tag>{d.summary}
                  <span className="muted">　能化解分歧的信息：</span>
                  {d.resolving_info.map((r, j) => (
                    <span key={j} className="resolve">{r.description}{r.subscribable ? <Button size="small" type="link" icon={<BellOutlined />} onClick={() => message.success('示例：已订阅（原型不保存）')}>订阅</Button> : null}</span>
                  ))}
                </div>
              ))}
            </div>
          }
        />
      ) : null}

      <div className="detail-grid">
        <section className="panel matrix-panel">
          <div className="panel-head"><span className="panel-title">六维度 × 策略矩阵</span><span className="muted small">单元格 = 维度观点 · 维度分 · 关键证据 · 规则命中；橙色行 = 分歧维度</span></div>
          {sg.strategies.length ? (
            <Table
              className="dense-table matrix" size="small" pagination={false} rowKey="dimension"
              columns={matrixCols} dataSource={sg.dimension_matrix}
              rowClassName={(r) => (isDiverged(r.dimension) ? 'row-diverged' : '')}
            />
          ) : <Alert type="info" message="暂无启用的策略实例，仅展示行情与数据状态（示例）" />}
        </section>
        <section className="panel side-panel">
          <div className="panel-head"><span className="panel-title">风控标记</span></div>
          {sg.risk_flags.length ? sg.risk_flags.map((f, i) => (
            <div key={i} className={`risk-row lv-${f.level}`}>
              <Tag color={RISK_LEVEL[f.level].color}>{RISK_LEVEL[f.level].text}</Tag>
              <b>{RISK_CONTROL[f.control]}</b>　{f.message}
              {f.gated_actions.length ? <div className="muted small">受限动作：{f.gated_actions.map((a) => ACTION_FULL[a].replace(/^规则信号：|（候选）$/g, '')).join('、')}{f.quantity_cap != null ? ` · 数量上限 ${f.quantity_cap}` : ''}</div> : null}
            </div>
          )) : <div className="muted small">无</div>}
          <div className="panel-head"><span className="panel-title">数据缺口</span></div>
          {sg.gaps.map((g) => (
            <div key={g.key} className="gap-row small"><Tag>{GAP_REASON[g.reason]}</Tag>{g.message}</div>
          ))}
          <div className="panel-head"><span className="panel-title">说明（模板生成）</span></div>
          <div className="small explain">{sg.explanation.text}</div>
          {sg.supersedes_id ? <div className="small muted">取代：上一版候选信号卡 {sg.supersedes_id.slice(0, 8)}（10:12 生成，已被盘中事件重评取代）</div> : null}
        </section>
      </div>

      <div className="panel-head section-gap"><span className="panel-title">各策略结论（并列，不合并）</span><span className="muted small">动作均为规则信号，需结合您的计划条件判断；“生成计划草案”仅拟定草案，不下单</span></div>
      <div className="strat-grid" style={{ gridTemplateColumns: `repeat(${Math.max(1, sg.strategies.length)}, minmax(0, 1fr))` }}>
        {sg.strategies.map((s) => {
          const cs = signalById(s.candidate_signal_id);
          const rs = cs ? reasonsOf(cs.id) : [];
          const meta = STRATEGIES[s.strategy_key];
          return (
            <section key={s.strategy_key} className="panel strat-card">
              <div className="sc-head">
                <ActionBadge action={s.action} tLeg={s.t_leg} size="lg" />
                <div>
                  <div className="sc-name">{meta.name}</div>
                  <div className="muted small">{HORIZON[s.horizon]} · v{s.version_no} · {LIFECYCLE[s.lifecycle]}{s.priority_downweighted ? ` · 优先级权重 ${s.priority_weight}` : ''}</div>
                </div>
                <span className="spacer" />
                {cs ? <Tag color={SIGNAL_STATE[cs.state].color}>{SIGNAL_STATE[cs.state].text}</Tag> : <Tag>持有/等待：不生成草案</Tag>}
              </div>
              <div className="sc-action">{ACTION_FULL[s.action]}{s.t_leg ? `（${s.t_leg === 'sell_first' ? '先卖后买' : '先买后卖'}）` : ''}</div>
              <div className="sc-metrics">
                <div><label>规则满足度</label><b className="mono">{s.score}</b></div>
                <div><label>置信度</label><ConfidenceTag c={s.confidence} /></div>
                <div><label>止损</label><b className="mono down">{s.stop_loss ?? '—'}</b></div>
                <div><label>止盈</label><b className="mono up">{s.take_profit ?? '—'}</b></div>
                <div><label>时间止损</label><b className="mono">{cs?.stops.time_stop_days != null ? `${cs.stops.time_stop_days} 日` : '—'}</b></div>
                <div><label>有效至</label><b className="mono small">{cs ? fmtTime(cs.valid_until).slice(5) : '—'}</b></div>
              </div>
              <div className="sc-sec"><h4>理由</h4>{s.reasons.map((r, i) => <div key={i} className="tw"><span>· {r.text}</span><EvidenceChips ids={r.evidence_ids} evidence={sg.evidence} /></div>)}</div>
              <div className="sc-sec counter"><h4>反证</h4>{s.counter_evidence.map((r, i) => <div key={i} className="tw"><span>· {r.text}</span><EvidenceChips ids={r.evidence_ids} evidence={sg.evidence} /></div>)}</div>
              <div className="sc-sec"><h4>失效条件</h4>{s.invalidation.map((r, i) => <div key={i} className="tw"><span>· {r.text}</span>{r.expr ? <code>{r.expr}</code> : null}<EvidenceChips ids={r.evidence_ids} evidence={sg.evidence} /></div>)}</div>
              {cs?.risk_flags.length ? <div className="sc-sec"><h4>风控标记</h4>{cs.risk_flags.map((f, i) => <div key={i} className="small"><Tag color={RISK_LEVEL[f.level].color}>{RISK_CONTROL[f.control]}</Tag>{f.message}</div>)}</div> : null}
              {rs.length ? (
                <div className="sc-sec blocked">
                  <h4>不可执行原因 · 解除条件</h4>
                  {rs.map((r) => (
                    <div key={r.id} className="reason">
                      <div><Tag color="orange">{r.code}</Tag><b>{REASON_CODE[r.code]}</b>：{r.description}</div>
                      <div className="rc">
                        解除条件（{RELEASE_KIND[r.release_condition.kind]}）：{r.release_condition.human_text}
                        {r.release_condition.expr ? <code>{r.release_condition.expr}</code> : null}
                        {r.release_condition.at ? <span className="mono"> @ {fmtTime(r.release_condition.at)}</span> : null}
                      </div>
                      <div className="muted small">检查时机：{r.release_condition.check_on.map((c) => CHECK_ON[c]).join('、')} · {r.release_condition.machine_checkable ? '系统自动检查' : '需您操作'} · 检出 {fmtTime(r.detected_at).slice(11)}</div>
                    </div>
                  ))}
                </div>
              ) : null}
              <div className="sc-foot">
                <span className="muted small">{cs ? `候选信号 ${cs.id.slice(0, 8)} · 规则引用 ${cs.rule_refs.length} 条` : '无候选信号'}</span>
                <Button size="small" type="primary" ghost onClick={() => setDraftFor(s)}>生成计划草案</Button>
              </div>
            </section>
          );
        })}
      </div>

      <div className="panel-head section-gap"><span className="panel-title">证据（时间 + 来源）</span><span className="muted small">事实 / 估计 / 假设 / 执行 四类分开标注</span></div>
      <section className="panel">
        <Table className="dense-table" size="small" pagination={false} rowKey="id" columns={evCols} dataSource={sg.evidence} />
      </section>

      <PlanDraftModal s={draftFor} code={code} onClose={() => setDraftFor(null)} />
    </div>
  );
}

function PlanDraftModal({ s, code, onClose }: { s: SuggestionStrategy | null; code: string; onClose: () => void }) {
  if (!s) return null;
  const cs = CANDIDATE_SIGNALS.find((c) => c.id === s.candidate_signal_id);
  const rs = cs ? reasonsOf(cs.id) : [];
  let body;
  if (!cs) body = <Alert type="info" showIcon message="持有 / 等待类规则信号不生成计划草案（示例）" />;
  else if (rs.length)
    body = (
      <Alert
        type="warning" showIcon
        message="该候选信号当前不可执行，不能拟定草案（接口将返回 422 SIGNAL_NOT_EXECUTABLE）"
        description={<ul className="plain">{rs.map((r) => <li key={r.id}>{REASON_CODE[r.code]} —— 解除条件：{r.release_condition.human_text}</li>)}</ul>}
      />
    );
  else
    body = (
      <Descriptions size="small" column={1} bordered>
        <Descriptions.Item label="证券">{nameOf(code)} {code}</Descriptions.Item>
        <Descriptions.Item label="规则信号">{ACTION_FULL[s.action]}</Descriptions.Item>
        <Descriptions.Item label="计划条件">价格回踩不破 {s.stop_loss} 且 {cs.valid_until.slice(5, 16).replace('T', ' ')} 前满足入场规则</Descriptions.Item>
        <Descriptions.Item label="拟定数量">按单只上限与可用资金折算，示例 <b>500 股</b>（100 股整数倍）</Descriptions.Item>
        <Descriptions.Item label="止损 / 止盈">{s.stop_loss ?? '—'} / {s.take_profit ?? '—'}</Descriptions.Item>
        <Descriptions.Item label="失效条件">{s.invalidation.map((x) => x.text).join('；')}</Descriptions.Item>
      </Descriptions>
    );
  return (
    <Modal open title={`生成计划草案（示例）· ${STRATEGIES[s.strategy_key].name}`} onCancel={onClose} onOk={onClose} okText="知道了" cancelButtonProps={{ style: { display: 'none' } }} width={560}>
      <Alert type="info" banner message="原型仅演示交互：不调用接口、不保存、不下单。草案需您确认后才成为计划，交易由您在券商端自行完成。" style={{ marginBottom: 12 }} />
      {body}
    </Modal>
  );
}
