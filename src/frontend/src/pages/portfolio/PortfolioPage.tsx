import { useEffect, useState } from 'react';
import { Alert, Button, DatePicker, Empty, Form, Input, InputNumber, Modal, Popconfirm, Radio, Select, Space, Table, Tabs, Tag, Tooltip } from 'antd';
import type { Dayjs } from 'dayjs';
import { Link, useNavigate, useSearchParams } from 'react-router';
import {
  downloadErrorsCsv, useAccounts, useCreateAccount, useCreateTrade, useImports, useReconciliation, useRevertImport, useTrades,
} from '../../api/accountQueries';
import type { BrokerAccount, ImportBatch, ReconciliationItem, Trade } from '../../api/accountTypes';
import { usePortfolio } from '../../api/queries';
import type { PortfolioPosition } from '../../api/types';
import { DataStatusTag, ErrorBox, Loading } from '../../components/common';
import { DILUTED_COST_NOTE, IMPORT_STATUS, RECON_KIND, RECON_STATUS, TRADE_SIDE } from '../../i18n/importLabels';
import { fmtAmount, fmtNum, fmtTime, pctClass, signed } from '../../lib/format';
import { applyFieldErrors } from '../../lib/formErrors';
import { TERM } from '../../i18n/statementTerms';

type TabKey = 'positions' | 'trades' | 'imports' | 'reconciliation';
const TABS: TabKey[] = ['positions', 'trades', 'imports', 'reconciliation'];

/** 持仓与账户（T-F02a）：账户选择 / 新建，持仓、成交（手工录入）、导入记录（撤销）、对账（摊薄成本口径）。 */
export function PortfolioPage() {
  const [sp, setSp] = useSearchParams();
  const accounts = useAccounts();
  const list = accounts.data?.items ?? [];
  const accountId = sp.get('account') ?? list[0]?.id;
  const tab = (TABS as string[]).includes(sp.get('tab') ?? '') ? (sp.get('tab') as TabKey) : 'positions';
  const navigate = useNavigate();
  const [creating, setCreating] = useState(false);

  const setParam = (k: string, v: string) => {
    const n = new URLSearchParams(sp);
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
              onChange={(v) => setParam('account', v)}
              options={list.map((a) => ({ value: a.id, label: accountLabel(a) }))}
              data-testid="account-select"
            />
          ) : null}
          <Button onClick={() => setCreating(true)}>新建账户</Button>
          <Button type="primary" disabled={!accountId} onClick={() => navigate(`/portfolio/import?account=${accountId}`)} data-testid="go-import">导入交割单 / 持仓</Button>
        </Space>
      </div>
      {!list.length ? (
        <Empty description="还没有券商账户。先新建一个账户，再导入通达信交割单或持仓快照。" />
      ) : (
        <Tabs
          activeKey={tab}
          onChange={(k) => setParam('tab', k)}
          items={[
            { key: 'positions', label: '持仓', children: <PositionsTab /> },
            { key: 'trades', label: '成交', children: <TradesTab accountId={accountId!} /> },
            { key: 'imports', label: '导入记录', children: <ImportsTab accountId={accountId!} /> },
            { key: 'reconciliation', label: '对账', children: <ReconTab accountId={accountId!} onGo={(t) => setParam('tab', t)} /> },
          ]}
        />
      )}
      <CreateAccountModal open={creating} onClose={(id) => { setCreating(false); if (id) setParam('account', id); }} />
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

function PositionsTab() {
  // [待契约确认] GET /portfolio 未带 account_id，这里展示的是全部账户合并持仓
  const q = usePortfolio();
  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorBox error={q.error} />;
  const p = q.data;
  return (
    <div data-testid="positions-tab">
      <Space size={24} className="kv-line">
        <span>总资产 <b className="mono">{fmtAmount(p.total_assets)}</b></span>
        <span>现金余额 <b className="mono">{fmtAmount(p.cash)}</b></span>
        <DataStatusTag status={p.data_status} asOf={p.data_as_of} gaps={p.gaps} />
        <span className="muted">合并全部账户；成本为摊薄成本（分红计入成本）</span>
      </Space>
      <Table<PortfolioPosition>
        size="small" rowKey="security_code" pagination={false} dataSource={p.positions}
        locale={{ emptyText: '暂无持仓' }}
        columns={[
          { title: '代码', dataIndex: 'security_code', render: (v: string) => <Link className="mono" to={`/stocks/${v}`}>{v}</Link> },
          { title: '名称', dataIndex: 'name' },
          { title: '数量', dataIndex: 'qty', align: 'right', render: (v: string) => <span className="mono">{fmtNum(v, 0)}</span> },
          { title: '可卖', dataIndex: 'sellable_qty', align: 'right', render: (v: string) => <span className="mono">{fmtNum(v, 0)}</span> },
          { title: '摊薄成本', dataIndex: 'cost_price', align: 'right', render: (v: string) => <span className="mono">{fmtNum(v, 3)}</span> },
          { title: '市值', dataIndex: 'market_value', align: 'right', render: (v: string) => <span className="mono">{fmtAmount(v)}</span> },
          { title: '浮动盈亏', dataIndex: 'pnl', align: 'right', render: (v: string) => <span className={`mono ${pctClass(v)}`}>{signed(v)}</span> },
          { title: '盈亏%', dataIndex: 'pnl_pct', align: 'right', render: (v: string) => <span className={`mono ${pctClass(v)}`}>{signed(v)}%</span> },
          { title: '仓位%', dataIndex: 'weight_pct', align: 'right', render: (v: string) => <span className="mono">{fmtNum(v)}%</span> },
        ]}
      />
    </div>
  );
}

interface TradeForm { trade_date: Dayjs; trade_time?: string; security_code: string; side: 'buy' | 'sell'; qty: number; price: number; fee_total?: number | null }
const TRADE_FIELDS = ['trade_date', 'trade_time', 'security_code', 'side', 'qty', 'price', 'fee_total'] as const;

function TradesTab({ accountId }: { accountId: string }) {
  const q = useTrades(accountId);
  const create = useCreateTrade();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm<TradeForm>();
  const [other, setOther] = useState<string[]>([]);
  const submit = (v: TradeForm) => {
    setOther([]);
    create.mutate(
      {
        account_id: accountId, trade_date: v.trade_date.format('YYYY-MM-DD'), trade_time: v.trade_time?.trim() || null, security_code: v.security_code.trim().toUpperCase(),
        side: v.side, qty: String(v.qty), price: String(v.price), fee_total: v.fee_total == null ? null : String(v.fee_total),
      },
      { onSuccess: () => setOpen(false), onError: (e) => setOther(applyFieldErrors(form, e, TRADE_FIELDS)) },
    );
  };
  return (
    <div data-testid="trades-tab">
      <Space className="kv-line">
        <Button type="primary" size="small" onClick={() => { form.resetFields(); create.reset(); setOther([]); setOpen(true); }}>手工录入成交</Button>
        <span className="muted">原记录不可修改；录错时请录入一条更正记录，或撤销整批导入。</span>
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
                {r.voided ? <Tooltip title="所属导入批次已撤销，此记录不再参与持仓与对账"><Tag color="purple">已作废</Tag></Tooltip> : null}
              </Space>
            ),
          },
        ]}
      />
      <Modal open={open} title="手工录入成交" okText="保存" onOk={() => form.submit()} okButtonProps={{ loading: create.isPending }} onCancel={() => setOpen(false)} destroyOnHidden>
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
      <Table<ImportBatch>
        size="small" rowKey="batch_id" loading={q.isPending} dataSource={q.data?.items ?? []} pagination={false}
        locale={{ emptyText: '暂无导入记录' }}
        columns={[
          { title: '上传时间', dataIndex: 'created_at', render: (v: string) => <span className="mono">{fmtTime(v)}</span> },
          { title: '类型', dataIndex: 'kind', render: (k: ImportBatch['kind']) => (k === 'trades' ? '交割单 / 成交' : '持仓快照') },
          { title: '状态', dataIndex: 'status', render: (s: ImportBatch['status']) => <Tag color={IMPORT_STATUS[s].color}>{IMPORT_STATUS[s].text}</Tag> },
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
          <Button type="primary" onClick={() => navigate(`/portfolio/import?account=${accountId}&kind=positions`)}>导入持仓快照</Button>
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
                return <Button size="small" type="link" onClick={() => (k.actionTo === 'import' ? navigate(`/portfolio/import?account=${accountId}`) : onGo('trades'))}>{k.action}</Button>;
              },
            },
          ]}
        />
      )}
    </div>
  );
}
