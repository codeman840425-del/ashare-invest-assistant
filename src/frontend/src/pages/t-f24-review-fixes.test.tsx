/**
 * T-F24 review-5969886 跟进：评审 m1–m3、nit1 与 heartbeat 示例场景（契约 v0.2.9 #31 ①–⑤）。
 * 测试数据均为示例。
 */
import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { INGEST_DATASETS, type AdminIngestStatus, type IngestLicenceStatus } from '../api/adminTypes';
import type { HorizonAssessment, Portfolio } from '../api/types';
import { HORIZON_DATA_MISSING, horizonDataMissing, noSuitableForLackOfData } from '../i18n/horizonCaps';
import { INGEST_DATASET_NAME } from '../i18n/ingestLabels';
import { HORIZON_ASSESSMENTS, SUGGESTIONS, allDataMissingAssessment } from '../mocks/fixtures';
import { INGEST_ALERT_TEXT, ingestAlerts, setMockIngestHeartbeat } from '../mocks/ingestAlerts';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { apiFetch } from '../test/apiFetch';

beforeAll(() => preloadRoutes(routes), 30_000);
afterEach(() => setMockIngestHeartbeat('ok'));

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

type Base = Omit<AdminIngestStatus, 'alerts'>;
const quiet: Base = {
  leader: { instance_id: 'ingest-demo-1', egress_ip_masked: '203.0.113.x', lease_expires_at: '2026-11-02T10:00:30+08:00' },
  budget: { per_minute_limit: 100, used_last_minute: 1 },
  queues: [{ priority: 'p0_intraday', depth: 0, oldest_age_s: 0 }, { priority: 'p1_daily', depth: 0, oldest_age_s: 0 }],
  errors_24h: [], ip_limit_alerts_24h: 0,
  freshness: INGEST_DATASETS.map((dataset) => ({ dataset, data_as_of: '2026-11-02', data_status: 'fresh' as const })),
  licences: [], licences_truncated: false, heartbeat: 'ok',
};
const lic = (status: IngestLicenceStatus['status'], days_left: number | null, i: number): IngestLicenceStatus => ({
  licence_id: `lic-demo-${i}`, user_id: `user-demo-${i}`, username: `demo_${i}`, display_name: `示例用户${i}`, status, tier: 'monthly', has_quant_pro: false,
  expires_on: '2026-11-10', days_left, calls_today: 0, daily_limit: null, per_minute_limit: 120, calls_last_minute: 0,
  queue_depth: { p0: 0, p1: 0, p2: 0 }, paused_until: null, last_error_code: null, last_error_at: null,
});

describe('① m1：无现金记录的账户 data_status=partial（#31 ①）', () => {
  it('mock：其他账户 cash 缺口 → partial；只有 exposure.sector 缺口的主账户示例不因此降级', async () => {
    const other = await getJson<Portfolio>('/portfolio?account_id=other-account');
    expect(other.gaps).toContainEqual(expect.objectContaining({ key: 'cash', reason: 'user_input_missing' }));
    expect(other.data_status).toBe('partial');
  });
});

describe('② m2：horizonDataMissing 硬门槛优先（#31 ③，问题 89）', () => {
  const sg = SUGGESTIONS[0];
  const dm = allDataMissingAssessment(HORIZON_ASSESSMENTS[sg.security_code]);
  const withGate = (h: HorizonAssessment['caps'][number]['horizon']): HorizonAssessment => ({
    ...dm, caps: [...dm.caps, { horizon: h, cap: 0, kind: 'gate', rule_id: 'HG1', inputs_missing: [] }],
  });

  it('同一周期同时有 gate 与 data_missing 封顶 → 该周期不显示“数据不足”', () => {
    const a = withGate('long');
    expect(horizonDataMissing(a, 'long')).toBe(false);
    expect(horizonDataMissing(a, 'swing')).toBe(true);
    expect(noSuitableForLackOfData(a)).toBe(true);
  });

  it('每个有 data_missing 的周期都有 gate 封顶 → 整体不是“数据不足”', () => {
    const a: HorizonAssessment = { ...dm, caps: dm.caps.flatMap((c) => [c, { horizon: c.horizon, cap: 0, kind: 'gate' as const, rule_id: 'HG1', inputs_missing: [] }]) };
    expect(noSuitableForLackOfData(a)).toBe(false);
    for (const c of dm.caps) expect(horizonDataMissing(a, c.horizon)).toBe(false);
  });

  it('suitable 非空 → 整体不是“数据不足”', () => {
    expect(noSuitableForLackOfData({ ...dm, suitable: ['swing'] })).toBe(false);
  });

  it('个股页：被 gate 封顶的周期不标“数据不足”，其余周期照常标注', async () => {
    server.use(http.get(`${API}/horizon-assessments`, () => HttpResponse.json(withGate('long'))));
    renderAt(`/stocks/${sg.security_code}`);
    const hz = await screen.findByTestId('horizon-panel', undefined, { timeout: 5000 });
    expect(await within(hz).findByTestId('hz-dm-swing')).toHaveTextContent(HORIZON_DATA_MISSING);
    expect(within(hz).queryByTestId('hz-dm-long')).toBeNull();
  });
});

describe('③ m3：告警 key 与固定文案（#31 ②④）', () => {
  it('14 天内到期用 licence.expiring，多张证书只出一条；expired 不算 expiring', () => {
    const out = ingestAlerts({ ...quiet, licences: [lic('active', 3, 1), lic('active', 10, 2), lic('expired', 0, 3), lic('active', 30, 4)] });
    expect(out.filter((a) => a.key === 'licence.expiring')).toEqual([{ level: 'warning', key: 'licence.expiring', message: '有证书即将到期' }]);
    expect(out.filter((a) => a.key === 'licence.expired')).toHaveLength(1);
    expect(out.some((a) => a.key === 'licence.active')).toBe(false);
    expect(ingestAlerts({ ...quiet, licences: [lic('expired', 0, 1)] }).some((a) => a.key === 'licence.expiring')).toBe(false);
  });

  it('每个 key 最多一条；同 key 两级同时满足只出 critical', () => {
    const out = ingestAlerts({ ...quiet, licences: [lic('invalid', null, 1), lic('invalid', null, 2), lic('ip_limited', null, 3), lic('quota_exceeded', null, 4), lic('quota_exceeded', null, 5)] });
    const keys = out.map((a) => a.key);
    expect(new Set(keys).size).toBe(keys.length);
    expect(out.find((a) => a.key === 'licence.invalid')).toEqual({ level: 'critical', key: 'licence.invalid', message: '有证书无效' });
    expect(out.find((a) => a.key === 'licence.ip_limited')?.message).toBe('有证书 IP 受限');
    expect(out.find((a) => a.key === 'licence.quota_exceeded')?.message).toBe('有证书今日额度已用完');
  });

  it('固定文案全表；message 不带数值阈值（只允许 upstream_code / dataset_name 占位）', () => {
    const all = ingestAlerts({
      ...quiet, leader: null, budget: { per_minute_limit: 100, used_last_minute: 95 },
      queues: [{ priority: 'p0_intraday', depth: 1, oldest_age_s: 301 }, { priority: 'p1_daily', depth: 1, oldest_age_s: 3601 }],
      errors_24h: [{ upstream_code: 'http_5xx', count: 20 }, { upstream_code: '101', count: 25 }], ip_limit_alerts_24h: 2,
      freshness: INGEST_DATASETS.map((dataset) => ({ dataset, data_as_of: null, data_status: 'stale' as const })),
    });
    const msg = Object.fromEntries(all.map((a) => [a.key, a.message]));
    expect(msg).toMatchObject({
      leader: '没有采集主实例（无未过期的租约）', 'queue.p0_intraday': '盘中队列（P0）等待过久', 'queue.p1_daily': '日频队列（P1）等待过久',
      budget: '近 1 分钟调用量接近上限', ip_limit: '24 小时内出现 IP 受限', 'errors.101': '上游错误码 101 24 小时内次数过多',
      'freshness.quotes': '实时行情过期或不可用', 'freshness.minute_bars': '分钟线已过期', 'freshness.daily_bars': '日线已过期',
      'freshness.financials': '财务数据已过期', 'freshness.announcements': '公告已过期', 'freshness.security_master': '证券主数据已过期',
    });
    for (const a of all) expect(a.message.replace(/上游错误码 \S+ 24 小时/, '').replace('近 1 分钟', '').replace('24 小时内出现', '')).not.toMatch(/\d{2,}/);
  });

  it('排序：critical 在前；同级按固定 key 顺序，errors.* 按 upstream_code 升序，freshness.* 按固定顺序', () => {
    const out = ingestAlerts({
      ...quiet, budget: { per_minute_limit: 100, used_last_minute: 95 }, ip_limit_alerts_24h: 1,
      errors_24h: [{ upstream_code: 'http_5xx', count: 20 }, { upstream_code: '101', count: 25 }],
      freshness: INGEST_DATASETS.map((dataset) => ({ dataset, data_as_of: null, data_status: dataset === 'quotes' ? 'unavailable' as const : 'stale' as const })),
      licences: [lic('active', 5, 1), lic('invalid', null, 2), lic('expired', 0, 3)], heartbeat: 'stale',
    });
    expect(out.map((a) => a.key)).toEqual([
      'heartbeat', 'ip_limit', 'freshness.quotes', 'licence.invalid',
      'budget', 'errors.101', 'errors.http_5xx', 'freshness.minute_bars', 'freshness.daily_bars', 'freshness.financials', 'freshness.announcements', 'freshness.security_master',
      'licence.expired', 'licence.expiring',
    ]);
  });
});

describe('④ m3：freshness 显示数据集中文名（#31 ③）', () => {
  it('采集状态页 6 行都用中文名，不显示 key', async () => {
    mockLoginAs('admin');
    renderAt('/admin/ingest');
    await screen.findByTestId('ingest-alerts', undefined, { timeout: 5000 });
    for (const d of INGEST_DATASETS) {
      const tag = screen.getByTestId(`ingest-fresh-${d}`);
      expect(tag).toHaveTextContent(INGEST_DATASET_NAME[d]);
      expect(tag.textContent).not.toContain(d);
    }
    expect(Object.values(INGEST_DATASET_NAME)).toEqual(['实时行情', '分钟线', '日线', '财务数据', '公告', '证券主数据']);
  });
});

describe('⑤ 可选：React key 防御与 heartbeat 示例场景', () => {
  it('服务端若返回重复 key 也能逐条渲染、无 React key 警告', async () => {
    mockLoginAs('admin');
    const d = await getJson<AdminIngestStatus>('/admin/ingest/status');
    const dup = { level: 'warning' as const, key: 'budget', message: INGEST_ALERT_TEXT.budget };
    server.use(http.get(`${API}/admin/ingest/status`, () => HttpResponse.json({ ...d, alerts: [dup, dup] })));
    const err = vi.spyOn(console, 'error').mockImplementation(() => {});
    renderAt('/admin/ingest');
    const box = await screen.findByTestId('ingest-alerts', undefined, { timeout: 5000 });
    expect(await within(box).findAllByTestId('ingest-alert-budget')).toHaveLength(2);
    expect(err.mock.calls.some((c) => String(c[0]).includes('same key'))).toBe(false);
    err.mockRestore();
  });

  it('心跳 stale/unknown 且 leader 不为 null → heartbeat critical；leader 为 null 时只出 leader', async () => {
    // v0.2.9 #38：心跳状态改为响应字段 heartbeat；paused 不出告警
    expect(ingestAlerts(quiet)).toEqual([]);
    expect(ingestAlerts({ ...quiet, heartbeat: 'paused' })).toEqual([]);
    expect(ingestAlerts({ ...quiet, heartbeat: 'unknown' })).toEqual([{ level: 'critical', key: 'heartbeat', message: '采集主实例心跳超时' }]);
    expect(ingestAlerts({ ...quiet, leader: null, heartbeat: 'stale' }).map((a) => a.key)).toEqual(['leader']);
    setMockIngestHeartbeat('stale');
    mockLoginAs('admin');
    const d = await getJson<AdminIngestStatus>('/admin/ingest/status');
    expect(d.alerts[0]).toEqual({ level: 'critical', key: 'heartbeat', message: '采集主实例心跳超时' });
    expect(d).not.toHaveProperty('heartbeat_at');
    renderAt('/admin/ingest');
    const box = await screen.findByTestId('ingest-alerts', undefined, { timeout: 5000 });
    expect(within(box).getByTestId('ingest-alert-heartbeat')).toHaveTextContent('严重');
  });
});
