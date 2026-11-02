/** T-B46/T-B47 裁定的前端同步（reports/T-B46-47-rulings.md；契约 v0.2.9 #27、§7.2 /portfolio、§7.3 /horizon-assessments、§7.9 /admin/ingest/status） */
import { render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { INGEST_DATASETS, type AdminIngestStatus } from '../api/adminTypes';
import { ENUMS } from '../api/enums';
import type { Portfolio, PortfolioPosition } from '../api/types';
import { horizonDataMissing, noSuitableForLackOfData } from '../i18n/horizonCaps';
import { HORIZON_ASSESSMENTS, PORTFOLIO, SUGGESTIONS, allDataMissingAssessment } from '../mocks/fixtures';
import { ingestAlerts } from '../mocks/ingestAlerts';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { apiFetch } from '../test/apiFetch';

beforeAll(() => preloadRoutes(routes), 30_000);

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

const API = '/api/v1';
const getJson = async <T,>(path: string) => (await (await apiFetch(`${API}${path}`)).json()) as T;
function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

describe('R6 持仓：证券类型只看 security_type，估算只看行上的 estimated', () => {
  const stock = PORTFOLIO.positions.find((p) => !p.estimated)!;
  const offMaster = PORTFOLIO.positions.find((p) => p.security_type === null)!;
  const withRows = (map: (p: PortfolioPosition) => PortfolioPosition): Portfolio => ({ ...PORTFOLIO, positions: PORTFOLIO.positions.map(map) });

  it('mock：字段名是 security_type，没有 instrument_kind 与顶层 estimated；必填数值不为 null', () => {
    expect(PORTFOLIO).not.toHaveProperty('estimated');
    for (const p of PORTFOLIO.positions) {
      expect(p).not.toHaveProperty('instrument_kind');
      expect(p).toHaveProperty('security_type');
      for (const k of ['qty', 'sellable_qty', 'cost_price', 'weight_pct'] as const) expect(p[k]).not.toBeNull();
      if (p.security_type === null) expect(p.estimated).toBe(true);
      if (p.estimated) expect([p.market_value, p.pnl, p.pnl_pct]).toEqual([null, null, null]);
    }
    expect(PORTFOLIO.cash).not.toBeNull();
    expect(PORTFOLIO.total_assets).not.toBeNull();
  });

  it('security_type=null 显示“不在主数据·估算”，与代码无关（转债代码的行若在主数据中，不再显示可转债字样）', async () => {
    // 把示例股票改成不在主数据、把转债代码的行改成在主数据且有现价：显示只跟 security_type / estimated 走
    server.use(http.get(`${API}/portfolio`, () => HttpResponse.json(withRows((p) =>
      p.security_code === stock.security_code ? { ...p, security_type: null, estimated: true, market_value: null, pnl: null, pnl_pct: null }
        : p.security_code === offMaster.security_code ? { ...p, security_type: 'stock', estimated: false, market_value: '1.00', pnl: '0.00', pnl_pct: '0.00' } : p))));
    renderAt('/portfolio');
    const tag = await screen.findByTestId(`est-label-${stock.security_code}`, undefined, { timeout: 5000 });
    expect(tag).toHaveTextContent('不在主数据·估算');
    expect(within(tag.closest('tr')!).queryByRole('link')).toBeNull();
    expect(screen.queryByTestId(`est-label-${offMaster.security_code}`)).toBeNull();
    expect(screen.queryByText(/可转债/)).toBeNull();
    const cbRow = screen.getByText(offMaster.security_code).closest('tr')!;
    expect(within(cbRow).getByRole('link', { name: offMaster.security_code })).toBeInTheDocument();
  });

  it('问题 79：在主数据中但无现价的行（estimated=true）只标“估算”，可进个股页；说明区分两种原因', async () => {
    server.use(http.get(`${API}/portfolio`, () => HttpResponse.json(withRows((p) =>
      p.security_code === stock.security_code ? { ...p, estimated: true, market_value: null, pnl: null, pnl_pct: null } : p))));
    renderAt('/portfolio');
    const tag = await screen.findByTestId(`est-label-${stock.security_code}`, undefined, { timeout: 5000 });
    expect(tag.textContent).toBe('估算');
    const row = tag.closest('tr')!;
    expect(within(row).getAllByText('—').length).toBe(4);
    expect(within(row).getByRole('link', { name: stock.security_code })).toBeInTheDocument();
    expect(screen.getByTestId(`est-weight-${stock.security_code}`)).toHaveTextContent('估算');
    const note = screen.getByTestId('est-note');
    expect(note).toHaveTextContent('部分持仓不在证券主数据中');
    expect(note).toHaveTextContent('部分持仓没有日线收盘价，也没有持仓快照参考价');
  });

  it('非股票类型按 security_type 显示类型标签（ETF）', async () => {
    server.use(http.get(`${API}/portfolio`, () => HttpResponse.json(withRows((p) => (p.security_code === stock.security_code ? { ...p, security_type: 'etf' } : p)))));
    renderAt('/portfolio');
    expect(await screen.findByTestId(`type-tag-${stock.security_code}`, undefined, { timeout: 5000 })).toHaveTextContent('ETF');
    expect(screen.queryByTestId(`est-label-${stock.security_code}`)).toBeNull();
  });

  it('R6 ③④：没有现金记录 → cash="0.00" + gaps cash/user_input_missing；行业未接入 → sector=[] + gaps，不单独降为 partial', async () => {
    const other = await getJson<Portfolio>('/portfolio?account_id=other-account');
    expect(other.cash).toBe('0.00');
    expect(other.gaps).toContainEqual(expect.objectContaining({ key: 'cash', reason: 'user_input_missing' }));
    expect(other.data_status).not.toBe('partial');
    const body: Portfolio = {
      ...PORTFOLIO, positions: PORTFOLIO.positions.filter((p) => !p.estimated), exposure: { sector: [] }, data_status: 'fresh',
      gaps: [{ key: 'exposure.sector', reason: 'no_source', message: '行业数据未接入（示例）' }],
    };
    server.use(http.get(`${API}/portfolio`, () => HttpResponse.json(body)));
    renderAt('/portfolio');
    await screen.findByTestId('positions-tab', undefined, { timeout: 5000 });
    expect(screen.queryByTestId('total-est')).toBeNull();
    expect(screen.queryByTestId('est-note')).toBeNull();
  });
});

describe('R10 采集状态：leader 可为 null、freshness 固定 6 行、alerts[]', () => {
  it('mock：freshness 6 行且顺序固定、状态无 partial；alerts 永不为 null，level 只取 warning/critical', async () => {
    mockLoginAs('admin');
    const d = await getJson<AdminIngestStatus>('/admin/ingest/status');
    expect(d.freshness.map((f) => f.dataset)).toEqual([...INGEST_DATASETS]);
    for (const f of d.freshness) expect(['fresh', 'stale', 'pending', 'unavailable']).toContain(f.data_status);
    expect(Array.isArray(d.alerts)).toBe(true);
    for (const a of d.alerts) {
      expect(Object.keys(a).sort()).toEqual(['key', 'level', 'message']);
      expect(['warning', 'critical']).toContain(a.level);
      expect(a.key).toMatch(/^(leader|heartbeat|budget|ip_limit|queue\.(p0_intraday|p1_daily|p2_backfill)|errors\..+|freshness\.[a-z_]+|licence\.[a-z_]+)$/);
      expect(a.message).not.toMatch(/203\.0\.113|seed-/);
    }
    expect(d.alerts).toContainEqual(expect.objectContaining({ key: 'ip_limit', level: 'critical' }));
    expect(d.alerts).toContainEqual(expect.objectContaining({ key: 'freshness.financials', level: 'warning' }));
    expect(d.alerts).toContainEqual(expect.objectContaining({ key: 'licence.quota_exceeded', level: 'warning' }));
  });

  it('示例告警口径：无 leader / 盘中 P0 超 300 秒 / quotes 不可用 → critical；P0 超 60 秒、预算 ≥ 90% → warning', () => {
    const base = { leader: null, budget: { per_minute_limit: 100, used_last_minute: 90 }, queues: [{ priority: 'p0_intraday' as const, depth: 1, oldest_age_s: 301 }],
      errors_24h: [{ upstream_code: 'http_5xx', count: 20 }], ip_limit_alerts_24h: 0,
      freshness: INGEST_DATASETS.map((dataset) => ({ dataset, data_as_of: null, data_status: 'unavailable' as const })), licences: [], licences_truncated: false };
    const by = Object.fromEntries(ingestAlerts(base).map((a) => [a.key, a.level]));
    expect(by).toEqual({ leader: 'critical', 'queue.p0_intraday': 'critical', budget: 'warning', 'errors.http_5xx': 'warning', 'freshness.quotes': 'critical' });
    expect(ingestAlerts({ ...base, queues: [{ priority: 'p0_intraday', depth: 1, oldest_age_s: 61 }] }).find((a) => a.key === 'queue.p0_intraday')?.level).toBe('warning');
  });

  it('页面显示告警（级别 + 服务端文案 + key），leader 为 null 显示“无”', async () => {
    mockLoginAs('admin');
    renderAt('/admin/ingest');
    const box = await screen.findByTestId('ingest-alerts', undefined, { timeout: 5000 });
    const ip = within(box).getByTestId('ingest-alert-ip_limit');
    expect(ip).toHaveAttribute('data-level', 'critical');
    expect(ip).toHaveTextContent('严重');
    expect(ip).toHaveTextContent('24 小时内出现 IP 受限（示例）');
    expect(within(box).getByTestId('ingest-alert-freshness.financials')).toHaveTextContent('警告');
  });

  it('alerts 为 [] 时显示“当前无告警”；leader=null 不报错', async () => {
    mockLoginAs('admin');
    const d = await getJson<AdminIngestStatus>('/admin/ingest/status');
    server.use(http.get(`${API}/admin/ingest/status`, () => HttpResponse.json({ ...d, leader: null, alerts: [] })));
    renderAt('/admin/ingest');
    expect(await screen.findByTestId('ingest-alerts-empty', undefined, { timeout: 5000 })).toHaveTextContent('当前无告警');
    expect(screen.getByText('无（没有未过期的租约）')).toBeInTheDocument();
  });
});

describe('R8/R9 周期评估：缺数据时显示“数据不足”，不说“都不适合”', () => {
  const sg = SUGGESTIONS[0];
  const dm = allDataMissingAssessment(HORIZON_ASSESSMENTS[sg.security_code]);

  it('判定：没有适合周期且有 data_missing 封顶 → 数据不足；gate 封顶不算', () => {
    expect(noSuitableForLackOfData(dm)).toBe(true);
    for (const h of ENUMS.horizon) expect(horizonDataMissing(dm, h)).toBe(true);
    const gateOnly = { suitable: [], caps: [{ horizon: 'long' as const, cap: 0, kind: 'gate' as const, rule_id: 'HG1', inputs_missing: [] }] };
    expect(noSuitableForLackOfData(gateOnly)).toBe(false);
    expect(horizonDataMissing(gateOnly, 'long')).toBe(false);
    for (const c of dm.caps) expect(dm.scores[c.horizon]).toBeLessThanOrEqual(c.cap);
  });

  it('个股页：四个周期都标“数据不足”，标题旁显示“数据不足”', async () => {
    server.use(http.get(`${API}/horizon-assessments`, () => HttpResponse.json(dm)));
    renderAt(`/stocks/${sg.security_code}`);
    const hz = await screen.findByTestId('horizon-panel', undefined, { timeout: 5000 });
    expect(await within(hz).findByTestId('hz-data-missing')).toHaveTextContent('数据不足');
    for (const h of ENUMS.horizon) expect(within(hz).getByTestId(`hz-dm-${h}`)).toHaveTextContent('数据不足');
    expect(hz).not.toHaveTextContent('都不适合');
  });

  it('候选信号卡：头部适合周期为空时显示“数据不足”，各周期行也标出', async () => {
    server.use(
      http.get(`${API}/horizon-assessments`, () => HttpResponse.json(dm)),
      http.get(`${API}/suggestions/:id`, () => HttpResponse.json({ ...sg, horizon_assessment: { ...sg.horizon_assessment, suitable: [] } })),
    );
    renderAt(`/suggestions/${sg.id}`);
    const head = await screen.findByTestId('sg-suitable', undefined, { timeout: 5000 });
    await waitFor(() => expect(within(head).getByTestId('sg-hz-data-missing')).toHaveTextContent('数据不足'));
    const hz = screen.getByTestId('horizon-panel');
    for (const h of ENUMS.horizon) expect(await within(hz).findByTestId(`hz-dm-${h}`)).toHaveTextContent('数据不足');
  });

  it('适合周期为空、但没有 data_missing 封顶时显示“—”（不显示“数据不足”）', async () => {
    const plain = { ...HORIZON_ASSESSMENTS[sg.security_code], suitable: [], caps: [], inputs_missing: [] };
    server.use(
      http.get(`${API}/horizon-assessments`, () => HttpResponse.json(plain)),
      http.get(`${API}/suggestions/:id`, () => HttpResponse.json({ ...sg, horizon_assessment: { ...sg.horizon_assessment, suitable: [] } })),
    );
    renderAt(`/suggestions/${sg.id}`);
    const hz = await screen.findByTestId('horizon-panel', undefined, { timeout: 5000 });
    await within(hz).findAllByText('支持');
    const head = screen.getByTestId('sg-suitable');
    expect(head).toHaveTextContent('—');
    expect(within(head).queryByTestId('sg-hz-data-missing')).toBeNull();
  });
});
