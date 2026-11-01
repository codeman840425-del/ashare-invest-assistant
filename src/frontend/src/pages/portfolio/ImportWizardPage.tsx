import { useMemo, useState } from 'react';
import {
  Alert, Button, Checkbox, Collapse, DatePicker, Descriptions, Form, Popconfirm, Radio, Result, Select, Space, Steps, Table, Tag, Upload,
} from 'antd';
import type { Dayjs } from 'dayjs';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';
import {
  downloadErrorsCsv, useAccounts, useConfirmImport, useDiscardImport, useImportBatch, useImportOptions, useImportRows, useResolveFinding, useRevertImport,
  useUploadImport, type RowFilter,
} from '../../api/accountQueries';
import type { ImportBatch, ImportConfirmResponse, ImportFinding, ImportKind, ImportRow } from '../../api/accountTypes';
import { ApiError, newIdempotencyKey } from '../../api/client';
import { ENUMS } from '../../api/enums';
import { IMPORT_422_TEXT, IMPORT_CODES, IMPORT_TONE, rowTone } from '../../api/importCodes';
import { ErrorBox, Loading } from '../../components/common';
import { DEDUP_STATUS, ENCODINGS, IMPORT_FIELDS, IMPORT_ROW_STATUS, IMPORT_STATUS, PARSERS, RECON_STATUS, TRADE_SIDE } from '../../i18n/importLabels';
import { fmtAmount, fmtNum, fmtTime } from '../../lib/format';
import { FindingItem, FindingTag, ToneLegend } from './importParts';

const KIND_TEXT: Record<ImportKind, string> = { trades: '交割单 / 成交明细', positions: '持仓快照' };
const toIso = (d: Dayjs) => d.format('YYYY-MM-DDTHH:mm:ss+08:00');

/** 交割单导入向导（T-F04）：上传 → 解析 → 预览着色与逐项处理 → 确认写入 → 结果（可撤销 / 下载问题清单）。 */
export function ImportWizardPage() {
  const { batchId } = useParams();
  return batchId ? <BatchView id={batchId} /> : <UploadStep />;
}

function StepsBar({ current, failed }: { current: number; failed?: boolean }) {
  return (
    <Steps size="small" current={current} status={failed ? 'error' : undefined} style={{ margin: '4px 0 16px' }}
      items={[{ title: '上传文件' }, { title: '解析' }, { title: '预览与处理' }, { title: '确认写入' }, { title: '完成' }]} />
  );
}

// ---------------- 1. 上传 ----------------
interface UploadForm { account_id: string; kind: ImportKind; snapshot_as_of?: Dayjs | null }

function UploadStep() {
  const [sp] = useSearchParams();
  const navigate = useNavigate();
  const accounts = useAccounts();
  const upload = useUploadImport();
  const [file, setFile] = useState<File | null>(null);
  const [form] = Form.useForm<UploadForm>();
  const kind = Form.useWatch('kind', form);

  if (accounts.isPending) return <Loading />;
  if (accounts.isError) return <div className="page-scroll page"><ErrorBox error={accounts.error} /></div>;
  const list = accounts.data.items;
  const fileErrors = upload.error instanceof ApiError && upload.error.code === 'IMPORT_FILE_ERRORS'
    ? ((upload.error.details as { findings?: ImportFinding[] } | null)?.findings ?? []) : [];

  const submit = (v: UploadForm) => {
    if (!file) return;
    upload.mutate(
      { file, account_id: v.account_id, kind: v.kind, snapshot_as_of: v.snapshot_as_of ? toIso(v.snapshot_as_of) : null },
      { onSuccess: (r) => navigate(`/portfolio/import/${r.batch_id}`, { replace: true }) },
    );
  };

  return (
    <div className="page-scroll page narrow" data-testid="import-upload">
      <h2 className="page-title">交割单导入</h2>
      <StepsBar current={0} failed={fileErrors.length > 0} />
      {!list.length ? (
        <Alert type="warning" showIcon title={<span>还没有券商账户，请先到 <Link to="/portfolio">持仓与账户</Link> 新建。</span>} />
      ) : (
        <Form<UploadForm> form={form} layout="vertical" requiredMark={false} onFinish={submit}
          initialValues={{ account_id: sp.get('account') ?? list[0].id, kind: sp.get('kind') === 'positions' ? 'positions' : 'trades' }}>
          <Form.Item name="account_id" label="导入到账户" rules={[{ required: true }]}>
            <Select options={list.map((a) => ({ value: a.id, label: `${a.alias} · ${a.broker_name}` }))} style={{ maxWidth: 320 }} />
          </Form.Item>
          <Form.Item name="kind" label="文件类型">
            <Radio.Group optionType="button" options={(['trades', 'positions'] as const).map((k) => ({ value: k, label: KIND_TEXT[k] }))} />
          </Form.Item>
          {kind === 'positions' ? (
            <Form.Item name="snapshot_as_of" label="持仓快照时间（可后补）" extra="不填时按文件推断，并给出“快照时间按推断处理”的提示">
              <DatePicker showTime={{ format: 'HH:mm' }} format="YYYY-MM-DD HH:mm" />
            </Form.Item>
          ) : null}
          <Form.Item label="文件" required>
            <Upload.Dragger
              accept=".txt,.csv"
              maxCount={1}
              beforeUpload={(f) => { setFile(f); upload.reset(); return false; }}
              onRemove={() => setFile(null)}
              fileList={file ? [{ uid: 'f', name: file.name, status: 'done' }] : []}
            >
              <p>把通达信导出的 .txt / .csv 拖到这里，或点击选择</p>
              <p className="muted">文件只用于解析本账户的成交与持仓；预览中只显示掩码后的原始行。</p>
            </Upload.Dragger>
          </Form.Item>
          {fileErrors.length ? (
            <div className="imp-findings" data-testid="upload-file-errors">
              <Alert type="error" showIcon title={IMPORT_422_TEXT.IMPORT_FILE_ERRORS} style={{ marginBottom: 8 }} />
              {fileErrors.map((f) => <FindingItem key={f.id} f={f} readOnly />)}
            </div>
          ) : upload.isError ? <ErrorBox error={upload.error} prefix="上传失败" /> : null}
          <Space>
            <Button type="primary" htmlType="submit" disabled={!file} loading={upload.isPending} data-testid="upload-submit">上传并解析</Button>
            <Link to="/portfolio?tab=imports">查看导入记录</Link>
          </Space>
        </Form>
      )}
    </div>
  );
}

// ---------------- 2+. 批次 ----------------
function BatchView({ id }: { id: string }) {
  const q = useImportBatch(id);
  const [result, setResult] = useState<ImportConfirmResponse | null>(null);
  if (q.isPending) return <Loading />;
  if (q.isError) return <div className="page-scroll page"><ErrorBox error={q.error} /></div>;
  const b = q.data;
  const st = IMPORT_STATUS[b.status];
  const step = b.status === 'uploaded' || b.status === 'parsing' ? 1 : b.status === 'previewed' || b.status === 'failed' ? 2 : 4;
  return (
    <div className="page-scroll page" data-testid="import-batch">
      <div className="page-head">
        <h2 className="page-title">交割单导入 <Tag color={st.color} data-testid="batch-status">{st.text}</Tag></h2>
        <Space>
          <span className="muted">{KIND_TEXT[b.kind]} · 上传于 <span className="mono">{fmtTime(b.created_at)}</span></span>
          <Link to={`/portfolio?account=${b.account_id}&tab=imports`}>返回导入记录</Link>
        </Space>
      </div>
      <StepsBar current={step} failed={b.status === 'failed'} />
      {step === 1 ? <Loading text="正在解析文件…" /> : null}
      {b.status === 'previewed' || b.status === 'failed' ? <PreviewStep b={b} onCommitted={setResult} /> : null}
      {b.status === 'committed' || b.status === 'reverted' || b.status === 'discarded' ? <DoneStep b={b} result={result} /> : null}
    </div>
  );
}

function DetectPanel({ b }: { b: ImportBatch }) {
  const opts = useImportOptions();
  const [encoding, setEncoding] = useState<string | null>(b.encoding_override);
  const [parser, setParser] = useState<string | null>(b.parser_id);
  const [mapping, setMapping] = useState<Record<string, string>>(b.mapping ?? {});
  const [asOf, setAsOf] = useState<string | null>(b.snapshot_as_of);
  const conf = b.encoding_confidence;
  const fieldOptions = [{ value: '', label: '（忽略此列）' }, ...Object.entries(IMPORT_FIELDS).map(([v, l]) => ({ value: v, label: `${l}（${v}）` }))];
  const reparse = () =>
    opts.mutate({ id: b.batch_id, v: { encoding_override: encoding, parser_id: parser, mapping: Object.fromEntries(Object.entries(mapping).filter(([, v]) => v)), snapshot_as_of: asOf } });
  return (
    <div data-testid="detect-panel">
      <Descriptions size="small" column={4} bordered
        items={[
          { label: '解析器', children: <span className="mono">{b.parser_id ? `${b.parser_id} ${b.parser_version ?? ''}` : '未识别'}</span> },
          { label: '编码', children: <span className="mono">{b.encoding_override ? `${b.encoding_override}（手选）` : (b.detected_encoding ?? '未识别')}{conf != null && !b.encoding_override ? `，置信度 ${conf.toFixed(2)}` : ''}</span> },
          { label: '格式匹配度', children: <span className="mono">{b.format_score != null ? b.format_score.toFixed(2) : '—'}</span> },
          { label: '快照时间', children: <span className="mono">{b.kind === 'positions' ? (b.snapshot_as_of ? fmtTime(b.snapshot_as_of) : '未填') : '—'}</span> },
        ]}
      />
      <Collapse size="small" style={{ marginTop: 8 }} defaultActiveKey={b.status === 'failed' ? ['opt'] : []}
        items={[{
          key: 'opt', label: '调整编码 / 解析器 / 列映射后重新解析',
          children: (
            <div data-testid="options-form">
              <Space wrap style={{ marginBottom: 8 }}>
                <span>编码</span>
                <Select allowClear placeholder="自动识别" value={encoding ?? undefined} onChange={(v) => setEncoding(v ?? null)} style={{ width: 140 }} options={ENCODINGS.map((e) => ({ value: e, label: e }))} />
                <span>解析器</span>
                <Select allowClear placeholder="自动识别" value={parser ?? undefined} onChange={(v) => setParser(v ?? null)} style={{ width: 300 }} options={PARSERS.map((p) => ({ value: p.id, label: p.text }))} />
                {b.kind === 'positions' ? (
                  <>
                    <span>快照时间</span>
                    {/* 受控值用字符串保存，避免 dayjs 时区换算 */}
                    <DatePicker showTime={{ format: 'HH:mm' }} format="YYYY-MM-DD HH:mm" onChange={(d) => setAsOf(d ? toIso(d) : null)} />
                  </>
                ) : null}
              </Space>
              {b.detected_columns.length ? (
                <Table<{ col: string }>
                  size="small" pagination={false} rowKey="col" dataSource={b.detected_columns.map((col) => ({ col }))} style={{ maxWidth: 560 }}
                  columns={[
                    { title: '文件列', dataIndex: 'col', render: (v: string) => <span className="mono">{v}</span> },
                    {
                      title: '映射到字段', key: 'f',
                      render: (_v, r) => (
                        <Select size="small" style={{ width: 240 }} value={mapping[r.col] ?? ''} options={fieldOptions}
                          onChange={(v) => setMapping((m) => ({ ...m, [r.col]: v }))} data-testid={`map-${r.col}`} />
                      ),
                    },
                  ]}
                />
              ) : <div className="muted">未识别到表头。</div>}
              <Button type="primary" size="small" style={{ marginTop: 8 }} loading={opts.isPending} onClick={reparse} data-testid="reparse">重新解析</Button>
              {opts.isError ? <ErrorBox error={opts.error} prefix="重新解析失败" /> : null}
            </div>
          ),
        }]}
      />
    </div>
  );
}

function PreviewStep({ b, onCommitted }: { b: ImportBatch; onCommitted: (r: ImportConfirmResponse) => void }) {
  const previewed = b.status === 'previewed';
  const [filter, setFilter] = useState<RowFilter>({});
  const rows = useImportRows(b.batch_id, previewed, filter);
  const allRows = useImportRows(b.batch_id, previewed, {});
  const resolve = useResolveFinding();
  const discard = useDiscardImport();
  const navigate = useNavigate();
  const [dlErr, setDlErr] = useState<unknown>(null);

  const actionable = useMemo(
    () => [...b.file_findings, ...(allRows.data?.items ?? []).flatMap((r) => r.findings)].filter((f) => f.needs_action),
    [b.file_findings, allRows.data],
  );
  const fileErrors = b.file_findings.filter((f) => f.severity === 'error');
  const s = b.stats;

  return (
    <>
      <DetectPanel key={`${b.parser_id}-${b.encoding_override}-${JSON.stringify(b.mapping)}`} b={b} />
      {b.file_findings.length ? (
        <section className="imp-section" data-testid="file-findings">
          <h3>文件级提示（{b.file_findings.length}）</h3>
          {fileErrors.length ? <Alert type="error" showIcon title={IMPORT_422_TEXT.IMPORT_FILE_ERRORS} style={{ marginBottom: 8 }} /> : null}
          {b.file_findings.map((f) => (
            <FindingItem key={`${f.id}-${f.resolution?.choice ?? ''}`} f={f} busy={resolve.isPending && resolve.variables?.v.finding_id === f.id}
              onResolve={(choice, reason) => resolve.mutate({ id: b.batch_id, v: { finding_id: f.id, choice, reason } })} />
          ))}
        </section>
      ) : null}
      {resolve.isError ? <ErrorBox error={resolve.error} prefix="处理失败" /> : null}

      {previewed ? (
        <>
          <section className="imp-section" data-testid="import-stats">
            <Space wrap size={6}>
              <span>共 <b className="mono">{s.rows}</b> 行</span>
              <Tag color="green">正常 {s.ok}</Tag><Tag color="gold">警告 {s.warning}</Tag><Tag color="red">错误 {s.error}</Tag><Tag>跳过 {s.skipped}</Tag>
              <span className="muted">｜</span>
              <Tag color="green">新成交 {s.new}</Tag><Tag>库内已有 {s.duplicate_in_db}</Tag><Tag>文件内重复 {s.duplicate_in_file}</Tag>
              <Tag color="orange">疑似手动录入重复 {s.possible_duplicate_of_manual}</Tag>
              {s.needs_action_open ? <Tag color="orange">待处理 {s.needs_action_open}</Tag> : <Tag color="green">无待处理项</Tag>}
            </Space>
            <ToneLegend />
          </section>

          <section className="imp-section">
            <Space wrap style={{ marginBottom: 8 }}>
              <Select allowClear placeholder="行状态" style={{ width: 120 }} value={filter.status} onChange={(v) => setFilter((f) => ({ ...f, status: v }))}
                options={ENUMS.import_row_status.map((x) => ({ value: x, label: IMPORT_ROW_STATUS[x].text }))} data-testid="filter-status" />
              <Select allowClear placeholder="去重结果" style={{ width: 160 }} value={filter.dedup_status} onChange={(v) => setFilter((f) => ({ ...f, dedup_status: v }))}
                options={ENUMS.dedup_status.map((x) => ({ value: x, label: DEDUP_STATUS[x].text }))} />
              <Select allowClear showSearch placeholder="提示码" style={{ width: 260 }} value={filter.code} onChange={(v) => setFilter((f) => ({ ...f, code: v }))}
                optionFilterProp="label" options={IMPORT_CODES.filter((c) => c.scope === 'row').map((c) => ({ value: c.code, label: `${c.title} ${c.code}` }))} />
            </Space>
            {rows.isError ? <ErrorBox error={rows.error} /> : null}
            <RowsTable rows={rows.data?.items ?? []} loading={rows.isPending} />
          </section>

          {actionable.length ? (
            <section className="imp-section" data-testid="needs-action">
              <h3>需处理的警告（{actionable.filter((f) => !f.resolution).length} 项未处理 / 共 {actionable.length} 项）</h3>
              <p className="muted">可以逐项选择处理方式；也可以在确认时勾选“接受默认处理”。选择“仍然导入”等覆盖默认处理的选项时必须填写理由。</p>
              {actionable.filter((f) => f.row_no != null).map((f) => (
                <FindingItem key={`${f.id}-${f.resolution?.choice ?? ''}`} f={f} busy={resolve.isPending && resolve.variables?.v.finding_id === f.id}
                  onResolve={(choice, reason) => resolve.mutate({ id: b.batch_id, v: { finding_id: f.id, choice, reason } }, { onSuccess: () => void allRows.refetch() })} />
              ))}
            </section>
          ) : null}

          <ConfirmPanel b={b} onCommitted={onCommitted} />
        </>
      ) : (
        <Alert type="error" showIcon style={{ marginTop: 12 }} title="解析失败" description="请根据上面的提示调整编码、解析器或列映射后重新解析；也可以放弃本批次重新上传。" />
      )}
      <Space style={{ marginTop: 12 }}>
        <Popconfirm title="放弃这个批次？" description="不会写入任何数据。" okText="放弃" okButtonProps={{ danger: true }}
          onConfirm={() => discard.mutate({ id: b.batch_id, v: null }, { onSuccess: () => navigate(`/portfolio?account=${b.account_id}&tab=imports`) })}>
          <Button danger loading={discard.isPending}>放弃本批次</Button>
        </Popconfirm>
        {s.error + s.warning > 0 ? <Button onClick={() => { setDlErr(null); downloadErrorsCsv(b.batch_id).catch(setDlErr); }}>下载问题清单 CSV</Button> : null}
      </Space>
      {discard.isError ? <ErrorBox error={discard.error} prefix="放弃失败" /> : null}
      {dlErr ? <ErrorBox error={dlErr} prefix="下载失败" /> : null}
    </>
  );
}

export function RowsTable({ rows, loading }: { rows: ImportRow[]; loading?: boolean }) {
  return (
    <Table<ImportRow>
      size="small" rowKey="row_no" loading={loading} dataSource={rows} pagination={{ pageSize: 50, hideOnSinglePage: true }}
      scroll={{ x: 1200 }}
      rowClassName={(r) => { const t = rowTone(r); return t ? IMPORT_TONE[t].rowClass : ''; }}
      locale={{ emptyText: '没有符合条件的行' }}
      data-testid="rows-table"
      columns={[
        { title: '行', dataIndex: 'row_no', width: 56, render: (v: number) => <span className="mono">{v}</span> },
        { title: '状态', dataIndex: 'status', width: 70, render: (v: ImportRow['status']) => <Tag color={IMPORT_ROW_STATUS[v].color}>{IMPORT_ROW_STATUS[v].text}</Tag> },
        { title: '去重', dataIndex: 'dedup_status', width: 130, render: (v: ImportRow['dedup_status']) => (v ? <Tag color={DEDUP_STATUS[v].color}>{DEDUP_STATUS[v].text}</Tag> : <span className="muted">—</span>) },
        { title: '日期', key: 'd', width: 150, render: (_v, r) => <span className="mono">{r.normalized ? `${r.normalized.trade_date} ${r.normalized.trade_time ?? ''}` : '—'}</span> },
        { title: '证券', key: 's', width: 160, render: (_v, r) => (r.normalized ? <span><span className="mono">{r.normalized.security_code}</span> {r.normalized.name}</span> : '—') },
        { title: '业务', key: 'b', width: 110, render: (_v, r) => (r.normalized ? (r.normalized.side ? <Tag color={TRADE_SIDE[r.normalized.side].color}>{TRADE_SIDE[r.normalized.side].text}</Tag> : r.normalized.biz_type_raw) : '—') },
        { title: '数量', key: 'q', width: 80, align: 'right', render: (_v, r) => <span className="mono">{r.normalized ? fmtNum(r.normalized.qty, 0) : '—'}</span> },
        { title: '价格', key: 'p', width: 80, align: 'right', render: (_v, r) => <span className="mono">{r.normalized ? fmtNum(r.normalized.price, 3) : '—'}</span> },
        { title: '金额', key: 'a', width: 110, align: 'right', render: (_v, r) => <span className="mono">{r.normalized ? fmtAmount(r.normalized.amount) : '—'}</span> },
        { title: '提示', key: 'f', render: (_v, r) => <Space size={2} wrap>{r.findings.map((f) => <FindingTag key={f.id} f={f} />)}</Space> },
        { title: '原始行（掩码）', dataIndex: 'raw_masked', width: 260, ellipsis: true, render: (v: string) => <span className="mono muted">{v}</span> },
      ]}
    />
  );
}

function ConfirmPanel({ b, onCommitted }: { b: ImportBatch; onCommitted: (r: ImportConfirmResponse) => void }) {
  const confirm = useConfirmImport();
  const [mode, setMode] = useState<'all' | 'valid_rows_only'>(b.stats.error ? 'valid_rows_only' : 'all');
  const [ack, setAck] = useState(false);
  // 同一次确认（同一请求体）的重试复用同一个 Idempotency-Key；改动请求体后换新 key
  const [key, setKey] = useState(newIdempotencyKey);
  const change = (fn: () => void) => { fn(); setKey(newIdempotencyKey()); confirm.reset(); };
  const e = confirm.error instanceof ApiError ? confirm.error : null;
  const codes = e?.code === 'IMPORT_WARNINGS_UNACKNOWLEDGED' ? ((e.details as { codes?: string[] } | null)?.codes ?? []) : [];
  return (
    <section className="imp-section imp-confirm" data-testid="confirm-panel">
      <h3>确认写入</h3>
      <Space orientation="vertical">
        <Radio.Group value={mode} onChange={(ev) => change(() => setMode(ev.target.value as typeof mode))}>
          <Radio value="all">全部写入（有错误行时会被拒绝）</Radio>
          <Radio value="valid_rows_only">只写入有效行（正常 / 警告且为新成交）</Radio>
        </Radio.Group>
        <Checkbox checked={ack} onChange={(ev) => change(() => setAck(ev.target.checked))} data-testid="ack-warnings">
          对未逐项处理的警告，接受默认处理（{b.stats.needs_action_open} 项）
        </Checkbox>
        <Button type="primary" loading={confirm.isPending} data-testid="confirm-import"
          onClick={() => confirm.mutate({ id: b.batch_id, body: { mode, acknowledge_warnings: ack }, key }, { onSuccess: onCommitted })}>
          确认写入
        </Button>
      </Space>
      {e && IMPORT_422_TEXT[e.code] ? (
        <Alert type="error" showIcon style={{ marginTop: 8 }} data-testid="confirm-error" title={IMPORT_422_TEXT[e.code]}
          description={codes.length ? <Space size={2} wrap>{codes.map((c) => <Tag key={c} color="orange">{IMPORT_CODES.find((x) => x.code === c)?.title ?? c}</Tag>)}</Space> : e.message} />
      ) : confirm.isError ? <ErrorBox error={confirm.error} prefix="写入失败" /> : null}
    </section>
  );
}

function DoneStep({ b, result }: { b: ImportBatch; result: ImportConfirmResponse | null }) {
  const revert = useRevertImport();
  const [dlErr, setDlErr] = useState<unknown>(null);
  const toRecon = `/portfolio?account=${b.account_id}&tab=reconciliation`;
  if (b.status === 'discarded') return <Result status="info" title="本批次已放弃" subTitle="没有写入任何数据。" extra={<Link to="/portfolio/import">重新上传</Link>} />;
  if (b.status === 'reverted') {
    return <Result status="info" title="本批次已撤销" subTitle={`撤销于 ${b.reverted_at ? fmtTime(b.reverted_at) : '—'}；写入的成交已标记为作废，持仓与对账已重算。`} extra={<Link to={toRecon}>查看对账</Link>} data-testid="import-reverted" />;
  }
  const rec = result?.reconciliation;
  return (
    <Result
      status="success"
      title="已写入"
      data-testid="import-done"
      subTitle={
        <div>
          {result ? <div>写入成交 {result.written.trades} 条、事件 {result.written.events} 条、快照持仓 {result.written.snapshot_positions} 条。</div> : <div>写入于 {b.committed_at ? fmtTime(b.committed_at) : '—'}。</div>}
          {rec ? <div>对账：<Tag color={RECON_STATUS[rec.status].color}>{RECON_STATUS[rec.status].text}</Tag>{rec.diff_count ? `${rec.diff_count} 项差异` : ''}</div> : null}
        </div>
      }
      extra={[
        <Link key="r" to={toRecon}><Button type="primary">查看对账</Button></Link>,
        <Popconfirm key="v" title="撤销这批导入？" description="写入的成交记录会标记为作废（不物理删除）。" okText="撤销" okButtonProps={{ danger: true }} onConfirm={() => revert.mutate(b.batch_id)}>
          <Button danger loading={revert.isPending} data-testid="revert-batch">撤销本批次</Button>
        </Popconfirm>,
        <Button key="c" onClick={() => { setDlErr(null); downloadErrorsCsv(b.batch_id).catch(setDlErr); }}>下载问题清单 CSV</Button>,
      ]}
    >
      {revert.isError ? <ErrorBox error={revert.error} prefix="撤销失败" /> : null}
      {dlErr ? <ErrorBox error={dlErr} prefix="下载失败" /> : null}
    </Result>
  );
}
