import { useEffect, useRef, useState } from 'react';
import { Alert, Button, DatePicker, Empty, Form, Input, InputNumber, Modal, Popconfirm, Radio, Select, Space, Table, Tabs, Tag, Tooltip } from 'antd';
import type { Dayjs } from 'dayjs';
import { Link, useNavigate, useSearchParams } from 'react-router';
import {
  downloadErrorsCsv, useAccounts, useCreateAccount, useCreateTrade, useImports, useReconciliation, useRevertImport, useTrades, useVoidTrade,
} from '../../api/accountQueries';
import type { BrokerAccount, ImportBatchSummary, ReconciliationItem, Trade } from '../../api/accountTypes';
import { newIdempotencyKey } from '../../api/client';
import { usePortfolio } from '../../api/queries';
import type { PortfolioPosition } from '../../api/types';
import { DataStatusTag, ErrorBox, Loading } from '../../components/common';
import { DILUTED_COST_NOTE, IMPORT_STATUS, RECON_KIND, RECON_STATUS, TRADE_SIDE, voidReasonText } from '../../i18n/importLabels';
import { fmtAmount, fmtNum, fmtTime, pctClass, signed } from '../../lib/format';
import { applyFieldErrors } from '../../lib/formErrors';
import { TERM } from '../../i18n/statementTerms';
import { SECURITY_TYPE } from '../../i18n/labels';
import { WatchlistToggle } from '../../features/watchlist/WatchlistToggle';

type TabKey = 'positions' | 'trades' | 'imports' | 'reconciliation';
const TABS: TabKey[] = ['positions', 'trades', 'imports', 'reconciliation'];

/** 持仓与账户（T-F02a）：账户选择 / 新建，持仓、成交（手工录入）、导入记录（撤销）、对账（摊薄成本口径）。 */
export function PortfolioPage() {
  const [sp, setSp] = useSearchParams();
  const accounts = useAccounts();
  const list = accounts.data?.items ?? [];
  // 通知深链用 account_id（契约 Notification.target.route）；旧链接的 account 作为别名（评审 P2）
  const asked = sp.get('account_id') ?? sp.get('account');
  // 评审 m14：链接里的账户不在本人账户列表中时，回落到第一个账户并提示，不显示原始 uuid
  const unknownAsked = !!asked && accounts.isSuccess && !list.some((a) => a.id === asked);
  const accountId = asked && !unknownAsked ? asked : list[0]?.id;
  const tab = (TABS as string[]).includes(sp.get('tab') ?? '') ? (sp.get('tab') as TabKey) : 'positions';
  const navigate = useNavigate();
  const [creating, setCreating] = useState(false);

  const setParam = (k: string, v: string) => {
    const n = new URLSearchParams(sp);
    if (k === 'account_id') n.delete('account');
    n.set(k, v);
    setSp(n, { replace: true });
  };

  if (accounts.isPending) return <Loading />;
  if (accounts.isError) return <div className="page-scroll page"><ErrorBox error={accounts.error} /></div>;

  return (
    <div className="page-scroll page" data-testid="portfolio-page">
      <div className="page-head">
        <h2 className="page-title">持仓与账户</h2>
        <Space>
          {list.length ? (
            <Select<string>
              value={accountId}
              style={{ width: 240 }}
              onChange={(v) => setParam('account_id', v)}
              options={list.map((a) => ({ value: a.id, label: accountLabel(a) }))}
              data-testid="account-select"
            />
          ) : null}
          <Button onClick={() => setCreating(true)}>新建账户</Button>
          <Button type="primary" disabled={!accountId} onClick={() => navigate(`/portfolio/import?account_id=${encodeURIComponent(accountId ?? '')}`)} data-testid="go-import">导入交割单 / 持仓</Button>
        </Space>
      </div>
      {unknownAsked ? (
        <Alert type="warning" showIcon data-testid="unknown-account" style={{ marginBottom: 12 }}
          title={list.length ? '链接中的账户不存在或不属于你，已切换到第一个账户。' : '链接中的账户不存在或不属于你。'} />
      ) : null}
      {!list.length ? (
        <Empty description="还没有券商账户。先新建一个账户，再导入通达信交割单或持仓快照。" />
      ) : (
        <Tabs
          activeKey={tab}
          onChange={(k) => setParam('tab', k)}
          items={[
            { key: 'positions', label: '持仓', children: <PositionsTab accountId={accountId!} /> },
            { key: 'trades', label: '成交', children: <TradesTab accountId={accountId!} /> },
            { key: 'imports', label: '导入记录', children: <ImportsTab accountId={accountId!} /> },
            { key: 'reconciliation', label: '对账', children: <ReconTab accountId={accountId!} onGo={(t) => setParam('tab', t)} /> },
          ]}
        />
      )}
      <CreateAccountModal open={creating} onClose={(id) => { setCreating(false); if (id) setParam('account_id', id); }} />
    </div>
  );
}

const accountLabel = (a: BrokerAccount) => `${a.alias} · ${a.broker_name}${a.fund_account_masked ? `（${a.fund_account_masked}）` : ''}`;

function CreateAccountModal({ open, onClose }: { open: boolean; onClose: (id?: string) => void }) {
  const [form] = Form.useForm<{ alias: string; broker_name: string }>();
  const create = useCreateAccount();
  useEffect(() => {
    if (open) { form.resetFields(); create.reset(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  return (
    <Modal open={open} title="新建券商账户" okText="创建" onOk={() => form.submit()} okButtonProps={{ loading: create.isPending }} onCancel={() => onClose()} destroyOnHidden>
      <Form form={form} layout="vertical" requiredMark={false}
        onFinish={(v) => create.mutate(v, { onSuccess: (a) => onClose(a.id), onError: (e) => applyFieldErrors(form, e, ['alias', 'broker_name']) })}>
        <Form.Item name="alias" label="账户别名" rules={[{ required: true, whitespace: true, message: '请输入别名' }]}><Input maxLength={32} placeholder="如：主账户" /></Form.Item>
        <Form.Item name="broker_name" label="券商" rules={[{ required: true, whitespace: true, message: '请输入券商名称' }]}><Input maxLength={32} placeholder="如：某某证券" /></Form.Item>
        <div className="muted">{TERM.holderCode}、资金账号只在导入后以脱敏形式显示，不需要在这里填写。</div>
      </Form>
      {create.isError ? <ErrorBox error={create.error} prefix="创建失败" /> : null}
    </Modal>
  );
}

function PositionsTab({ accountId }: { accountId: string }) {
  const [scope, setScope] = useState<'account' | 'all'>('account');
  const q = usePortfolio(scope === 'account' ? accountId : undefined);
  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const p = q.data;
  // 契约 v0.2.9 #1/#2 与 T-B46 裁定 R6：证券类型只看 security_type（null = 不在证券主数据中），不看代码前缀；
  // 是否估算只看行上的 estimated（顶层没有 estimated）。估算行现价、市值、盈亏为 null 显示“—”，仓位按成本估算并标“估算”。
  const est = (r: PortfolioPosition) => r.estimated;
  const hasEst = p.positions.some(est);
  const hasOffMaster = p.positions.some((r) => r.security_type === null);
  // R6 ②：在主数据中、但既没有日线收盘价也没有持仓快照参考价的行（问题 79）
  const hasNoPrice = p.positions.some((r) => r.estimated && r.security_type !== null);
  const estLabel = (r: PortfolioPosition) => (r.security_type === null ? '不在主数据·估算' : '估算');
  const dashCell = <span className="mono muted">—</span>;
  const estTag = <Tag className="est-tag" style={{ marginInlineStart: 4, marginInlineEnd: 0 }}>估算</Tag>;
  const lastPrice = (r: PortfolioPosition) => {
    const qty = Number(r.qty);
    return qty > 0 && r.market_value !== null ? Number(r.market_value) / qty : null;
  };
  return (
    <div data-testid="positions-tab">
      <Space size={24} className="kv-line">
        <span>总资产 <b className="mono">{fmtAmount(p.total_assets)}</b>{hasEst ? <span data-testid="total-est">{estTag}</span> : null}</span>
        <span>现金余额 <b className="mono">{fmtAmount(p.cash)}</b></span>
        <DataStatusTag status={p.data_status} asOf={p.data_as_of} gaps={p.gaps} />
        <Radio.Group size="small" value={scope} onChange={(e) => setScope(e.target.value as 'account' | 'all')} optionType="button" data-testid="portfolio-scope"
          options={[{ value: 'account', label: '当前账户' }, { value: 'all', label: '合并全部账户' }]} />
        <span className="muted">成本为摊薄成本（分红计入成本）</span>
      </Space>
      {hasEst ? (
        <div className="muted small" data-testid="est-note" style={{ margin: '4px 0 8px' }}>
          {[hasOffMaster ? '部分持仓不在证券主数据中' : null, hasNoPrice ? '部分持仓没有日线收盘价，也没有持仓快照参考价' : null].filter(Boolean).join('；')}
          ，其现价、市值、盈亏显示“—”；仓位与总资产按成本估算。
        </div>
      ) : null}
      <Table<PortfolioPosition>
        size="small" rowKey="security_code" pagination={false} dataSource={p.positions}
        locale={{ emptyText: '暂无持仓' }}
        columns={[
          { title: '代码', dataIndex: 'security_code', render: (v: string, r) => (r.security_type === null ? <span className="mono">{v}</span> : <Link className="mono" to={`/stocks/${v}`}>{v}</Link>) },
          {
            title: '名称', dataIndex: 'name',
            render: (v: string, r) => (
              <span>
                {v}
                {r.security_type !== null && r.security_type !== 'stock' ? <Tag style={{ marginInlineStart: 6 }} data-testid={`type-tag-${r.security_code}`}>{SECURITY_TYPE[r.security_type]}</Tag> : null}
                {est(r) ? <Tag color="default" style={{ marginInlineStart: 6 }} data-testid={`est-label-${r.security_code}`}>{estLabel(r)}</Tag> : null}
              </span>
            ),
          },
          { title: '数量', dataIndex: 'qty', align: 'right', render: (v: string) => <span className="mono">{fmtNum(v, 0)}</span> },
          { title: '可卖', dataIndex: 'sellable_qty', align: 'right', render: (v: string) => <span className="mono">{fmtNum(v, 0)}</span> },
          { title: '摊薄成本', dataIndex: 'cost_price', align: 'right', render: (v: string) => <span className="mono">{fmtNum(v, 3)}</span> },
          {
            title: '现价', key: 'last', align: 'right',
            render: (_: unknown, r) => { const lp = lastPrice(r); return lp === null ? dashCell : <span className="mono">{fmtNum(lp, 3)}</span>; },
          },
          { title: '市值', dataIndex: 'market_value', align: 'right', render: (v: string | null) => (v === null ? dashCell : <span className="mono">{fmtAmount(v)}</span>) },
          { title: '浮动盈亏', dataIndex: 'pnl', align: 'right', render: (v: string | null) => (v === null ? dashCell : <span className={`mono ${pctClass(v)}`}>{signed(v)}</span>) },
          { title: '盈亏%', dataIndex: 'pnl_pct', align: 'right', render: (v: string | null) => (v === null ? dashCell : <span className={`mono ${pctClass(v)}`}>{signed(v)}%</span>) },
          {
            title: '仓位%', dataIndex: 'weight_pct', align: 'right',
            render: (v: string, r) => <span className="mono" data-testid={est(r) ? `est-weight-${r.security_code}` : undefined}>{fmtNum(v)}%{est(r) ? estTag : null}</span>,
          },
          {
            // T-F33：不在证券主数据中的持仓（如可转债）后端会返回 400 unknown_security，不给入口
            title: '自选', key: 'wl',
            render: (_: unknown, r) => (r.security_type === null ? null : <WatchlistToggle code={r.security_code} securityType={r.security_type} testId={`watchlist-pos-${r.security_code}`} />),
          },
        ]}
      />
      <SectorExposure sector={p.exposure.sector} />
    </div>
  );
}

/** 契约 v0.2.9 #30 ③：没有行业归属的持仓合并为“未分类”一项计入 exposure.sector；它不是行业，不参与 RC4 行业集中度 */
export const UNCLASSIFIED_SECTOR = '未分类';
function SectorExposure({ sector }: { sector: { name: string; pct: string }[] }) {
  if (!sector.length) return null;
  return (
    <div className="sector-exposure" data-testid="sector-exposure" style={{ marginTop: 12 }}>
      <div className="muted small" style={{ marginBottom: 4 }}>行业分布（占总资产）</div>
      <Space wrap size={[6, 6]}>
        {sector.map((x) => (
          x.name === UNCLASSIFIED_SECTOR ? (
            <Tooltip key={x.name} title="没有行业归属的持仓（如不在证券主数据中的可转债）按成本估算合并为此项；它不是行业，不参与行业集中度判断">
              <Tag data-testid="sector-unclassified">{x.name} <span className="mono">{fmtNum(x.pct)}%</span></Tag>
            </Tooltip>
          ) : (
            <Tag key={x.name} data-testid={`sector-${x.name}`}>{x.name} <span className="mono">{fmtNum(x.pct)}%</span></Tag>
          )
        ))}
      </Space>
    </div>
  );
}

interface TradeForm { trade_date: Dayjs; trade_time?: string; security_code: string; side: 'buy' | 'sell'; qty: number; price: number; fee_total?: number | null; reason?: string }
const TRADE_FIELDS = ['trade_date', 'trade_time', 'security_code', 'side', 'qty', 'price', 'fee_total', 'reason'] as const;


function TradesTab({ accountId }: { accountId: string }) {
  const q = useTrades(accountId);
  const create = useCreateTrade();
  const voidTrade = useVoidTrade();
  const [open, setOpen] = useState(false);
  const [corrects, setCorrects] = useState<Trade | null>(null);
  const [voiding, setVoiding] = useState<Trade | null>(null);
  const [voidReason, setVoidReason] = useState('');
  const [form] = Form.useForm<TradeForm>();
  const [other, setOther] = useState<string[]>([]);
  // 评审 s1：同一次录入（含网络失败后的重试）沿用同一个 Idempotency-Key，成功后才换新
  const idemKey = useRef(newIdempotencyKey());
  const openCreate = (orig: Trade | null) => {
    form.resetFields();
    create.reset();
    setOther([]);
    setCorrects(orig);
    idemKey.current = newIdempotencyKey();
    if (orig) form.setFieldsValue({ security_code: orig.security_code, side: orig.side, qty: Number(orig.qty), price: Number(orig.price), fee_total: orig.fee_total == null ? null : Number(orig.fee_total), trade_time: orig.trade_time ?? undefined });
    setOpen(true);
  };
  const submit = (v: TradeForm) => {
    setOther([]);
    create.mutate(
      {
        key: idemKey.current,
        body: {
          account_id: accountId, trade_date: v.trade_date.format('YYYY-MM-DD'), trade_time: v.trade_time?.trim() || null, security_code: v.security_code.trim().toUpperCase(),
          side: v.side, qty: String(v.qty), price: String(v.price), fee_total: v.fee_total == null ? null : String(v.fee_total),
          ...(corrects ? { corrects_trade_id: corrects.id, reason: v.reason?.trim() } : {}),
        },
      },
      {
        onSuccess: () => { idemKey.current = newIdempotencyKey(); setOpen(false); },
        onError: (e) => setOther(applyFieldErrors(form, e, TRADE_FIELDS)),
      },
    );
  };
  return (
    <div data-testid="trades-tab">
      <Space className="kv-line">
        <Button type="primary" size="small" onClick={() => openCreate(null)}>手工录入成交</Button>
        <span className="muted">原记录不可修改；录错时请录入一条更正记录或作废该条，导入的记录也可撤销整批。</span>
      </Space>
      {q.isError ? <ErrorBox error={q.error} /> : null}
      <Table<Trade>
        size="small" rowKey="id" loading={q.isPending} dataSource={q.data?.items ?? []} pagination={{ pageSize: 20, hideOnSinglePage: true }}
        rowClassName={(r) => (r.voided ? 'row-voided' : '')}
        locale={{ emptyText: '暂无成交' }}
        columns={[
          { title: TERM.tradeDate, dataIndex: 'trade_date', render: (v: string, r) => <span className="mono">{v} {r.trade_time ?? ''}</span> },
          { title: '代码', dataIndex: 'security_code', render: (v: string) => <span className="mono">{v}</span> },
          { title: '名称', dataIndex: 'name' },
          { title: '方向', dataIndex: 'side', render: (s: Trade['side']) => <Tag color={TRADE_SIDE[s].color}>{TRADE_SIDE[s].text}</Tag> },
          { title: '数量', dataIndex: 'qty', align: 'right', render: (v: string) => <span className="mono">{fmtNum(v, 0)}</span> },
          { title: '价格', dataIndex: 'price', align: 'right', render: (v: string) => <span className="mono">{fmtNum(v, 3)}</span> },
          { title: '金额', dataIndex: 'amount', align: 'right', render: (v: string) => <span className="mono">{fmtAmount(v)}</span> },
          { title: '费用', dataIndex: 'fee_total', align: 'right', render: (v: string | null) => <span className="mono">{v == null ? '—' : fmtNum(v)}</span> },
          {
            title: '来源', dataIndex: 'source',
            render: (s: Trade['source'], r) => (
              <Space size={4}>
                <Tag>{s === 'import' ? '导入' : '手工'}</Tag>
                {r.voided ? <Tooltip title={voidReasonText(r)}><Tag color="purple" data-testid={`voided-${r.id}`}>已作废</Tag></Tooltip> : null}
                {r.corrects_trade_id ? <Tag>更正记录</Tag> : null}
              </Space>
            ),
          },
          {
            title: '操作', key: 'op',
            render: (_v, r) => (r.voided ? <span className="muted">{voidReasonText(r)}</span> : (
              <Space size={4}>
                <Button size="small" type="link" onClick={() => openCreate(r)} data-testid={`correct-${r.id}`}>更正</Button>
                <Button size="small" type="link" danger onClick={() => { voidTrade.reset(); setVoidReason(''); setVoiding(r); }} data-testid={`void-${r.id}`}>作废</Button>
              </Space>
            )),
          },
        ]}
      />
      <Modal
        open={!!voiding} title="作废这条成交？" okText="作废" okButtonProps={{ danger: true, disabled: !voidReason.trim(), loading: voidTrade.isPending }}
        onCancel={() => setVoiding(null)} destroyOnHidden
        onOk={() => voiding && voidTrade.mutate({ id: voiding.id, reason: voidReason.trim() }, { onSuccess: () => setVoiding(null) })}
      >
        <p className="muted">作废不物理删除，记录保留并标记，持仓与对账随之重算。</p>
        <Input.TextArea value={voidReason} onChange={(e) => setVoidReason(e.target.value)} maxLength={200} showCount placeholder="作废原因（必填，1–200 字）" data-testid="void-reason" />
        {voidTrade.isError ? <ErrorBox error={voidTrade.error} prefix="作废失败" /> : null}
      </Modal>
      <Modal open={open} title={corrects ? '录入更正记录' : '手工录入成交'} okText="保存" onOk={() => form.submit()} okButtonProps={{ loading: create.isPending }} onCancel={() => setOpen(false)} destroyOnHidden>
        <Form<TradeForm> form={form} layout="vertical" requiredMark={false} initialValues={{ side: 'buy' }} onFinish={submit}>
          <Space align="start">
            <Form.Item name="trade_date" label={TERM.tradeDate} rules={[{ required: true, message: '必填' }]}><DatePicker /></Form.Item>
            <Form.Item name="trade_time" label="成交时间（可选）" rules={[{ pattern: /^\d{2}:\d{2}(:\d{2})?$/, message: 'HH:MM:SS' }]}><Input placeholder="10:30:00" style={{ width: 120 }} /></Form.Item>
          </Space>
          <Space align="start">
            <Form.Item name="security_code" label={TERM.securityCode} rules={[{ required: true, pattern: /^\d{6}\.(SH|SZ|BJ|sh|sz|bj)$/, message: '格式如 600000.SH' }]}><Input placeholder="600000.SH" style={{ width: 140 }} /></Form.Item>
            <Form.Item name="side" label="方向"><Radio.Group options={[{ value: 'buy', label: '买入' }, { value: 'sell', label: '卖出' }]} optionType="button" /></Form.Item>
          </Space>
          <Space align="start">
            <Form.Item name="qty" label="数量（股）" rules={[{ required: true, type: 'number', min: 1, message: '大于 0' }]}><InputNumber min={1} step={100} style={{ width: 130 }} /></Form.Item>
            <Form.Item name="price" label="价格" rules={[{ required: true, type: 'number', min: 0.001, message: '大于 0' }]}><InputNumber min={0} step={0.01} style={{ width: 120 }} /></Form.Item>
            <Form.Item name="fee_total" label="费用合计（可选）"><InputNumber min={0} step={0.01} style={{ width: 120 }} /></Form.Item>
          </Space>
          {corrects ? (
            <Form.Item name="reason" label="更正原因" extra="保存后原记录自动作废" rules={[{ required: true, whitespace: true, message: '更正时必须填写原因' }, { max: 200, message: '不超过 200 字' }]}>
              <Input maxLength={200} data-testid="correct-reason" />
            </Form.Item>
          ) : null}
        </Form>
        {other.length ? <Alert type="error" showIcon title={other.join('；')} /> : null}
        {create.isError && !other.length ? <ErrorBox error={create.error} prefix="保存失败" /> : null}
      </Modal>
    </div>
  );
}

function ImportsTab({ accountId }: { accountId: string }) {
  const q = useImports(accountId);
  const revert = useRevertImport();
  const navigate = useNavigate();
  const [dlErr, setDlErr] = useState<unknown>(null);
  return (
    <div data-testid="imports-tab">
      {q.isError ? <ErrorBox error={q.error} /> : null}
      {revert.isError ? <ErrorBox error={revert.error} prefix="撤销失败" /> : null}
      {dlErr ? <ErrorBox error={dlErr} prefix="下载失败" /> : null}
      <Table<ImportBatchSummary>
        size="small" rowKey="batch_id" loading={q.isPending} dataSource={q.data?.items ?? []} pagination={false}
        locale={{ emptyText: '暂无导入记录' }}
        columns={[
          { title: '上传时间', dataIndex: 'created_at', render: (v: string) => <span className="mono">{fmtTime(v)}</span> },
          { title: '类型', dataIndex: 'kind', render: (k: ImportBatchSummary['kind']) => (k === 'trades' ? '交割单 / 成交' : '持仓快照') },
          { title: '状态', dataIndex: 'status', render: (s: ImportBatchSummary['status']) => <Tag color={IMPORT_STATUS[s].color}>{IMPORT_STATUS[s].text}</Tag> },
          {
            title: '行数（正常 / 警告 / 错误 / 跳过）', key: 'stats',
            render: (_v, b) => <span className="mono">{b.stats.rows}（{b.stats.ok} / {b.stats.warning} / {b.stats.error} / {b.stats.skipped}）</span>,
          },
          { title: '写入 / 撤销时间', key: 't', render: (_v, b) => <span className="mono">{b.reverted_at ? `撤销 ${fmtTime(b.reverted_at)}` : b.committed_at ? fmtTime(b.committed_at) : '—'}</span> },
          {
            title: '操作', key: 'op',
            render: (_v, b) => (
              <Space size={4}>
                <Button size="small" type="link" onClick={() => navigate(`/portfolio/import/${b.batch_id}`)}>{b.status === 'previewed' || b.status === 'failed' ? '继续处理' : '查看'}</Button>
                {b.status === 'committed' ? (
                  <Popconfirm title="撤销这批导入？" description="该批写入的成交记录会标记为作废（不物理删除），持仓与对账随之重算。" okText="撤销" okButtonProps={{ danger: true }} onConfirm={() => revert.mutate(b.batch_id)}>
                    <Button size="small" danger type="link" data-testid={`revert-${b.batch_id}`}>撤销</Button>
                  </Popconfirm>
                ) : null}
                {b.stats.error + b.stats.warning > 0 ? (
                  <Button size="small" type="link" onClick={() => { setDlErr(null); downloadErrorsCsv(b.batch_id).catch(setDlErr); }}>问题清单 CSV</Button>
                ) : null}
              </Space>
            ),
          },
        ]}
      />
    </div>
  );
}

function ReconTab({ accountId, onGo }: { accountId: string; onGo: (tab: TabKey) => void }) {
  const q = useReconciliation(accountId);
  const navigate = useNavigate();
  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const r = q.data;
  const st = RECON_STATUS[r.status];
  return (
    <div data-testid="recon-tab">
      <Space className="kv-line">
        对账结果 <Tag color={st.color}>{st.text}</Tag>
        {r.as_of ? <span className="muted">券商数据截至 <span className="mono">{fmtTime(r.as_of)}</span></span> : null}
      </Space>
      <Alert type="info" showIcon title="成本口径" description={DILUTED_COST_NOTE} style={{ marginBottom: 12 }} data-testid="diluted-cost-note" />
      {r.status === 'not_imported' ? (
        <Empty description="还没有导入券商持仓快照，无法对账。">
          <Button type="primary" onClick={() => navigate(`/portfolio/import?account_id=${encodeURIComponent(accountId)}&kind=positions`)}>导入持仓快照</Button>
        </Empty>
      ) : (
        <Table<ReconciliationItem>
          size="small" rowKey={(x) => `${x.kind}-${x.security_code ?? 'cash'}`} pagination={false} dataSource={r.items}
          locale={{ emptyText: '没有差异' }}
          columns={[
            { title: '差异', dataIndex: 'kind', render: (k: ReconciliationItem['kind'], x) => <Space size={4}><Tag color={RECON_KIND[k].color}>{RECON_KIND[k].text}</Tag>{x.important ? <Tag color="red">重要</Tag> : null}</Space> },
            { title: '证券', key: 'sec', render: (_v, x) => (x.security_code ? <span><span className="mono">{x.security_code}</span> {x.name}</span> : <span className="muted">资金</span>) },
            { title: '我方', dataIndex: 'ours', align: 'right', render: (v: string | null) => <span className="mono">{v ?? '—'}</span> },
            { title: '券商', dataIndex: 'broker', align: 'right', render: (v: string | null) => <span className="mono">{v ?? '—'}</span> },
            { title: '差额', dataIndex: 'diff', align: 'right', render: (v: string | null) => <span className="mono">{v ?? '—'}</span> },
            { title: '说明', dataIndex: 'note', render: (v: string) => v || '—' },
            { title: '可能原因（假设）', key: 'cause', render: (_v, x) => <span className="muted">{RECON_KIND[x.kind].cause}</span> },
            {
              title: '数据整理', key: 'act',
              render: (_v, x) => {
                const k = RECON_KIND[x.kind];
                return <Button size="small" type="link" onClick={() => (k.actionTo === 'import' ? navigate(`/portfolio/import?account_id=${encodeURIComponent(accountId ?? '')}`) : onGo('trades'))}>{k.action}</Button>;
              },
            },
          ]}
        />
      )}
    </div>
  );
}
