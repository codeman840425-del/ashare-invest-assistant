/**
 * T-F27：契约 v0.2.9 #37–#40（docs 0edb298）。
 * #37 拟定草案七步判定；#38 heartbeat 字段显示；#39 告警 message 原样显示与 master.* 排序；#40 到期剩余天数文案。
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { ApiError } from '../api/client';
import type { AdminIngestStatus } from '../api/adminTypes';
import type { DataLicenceStatus } from '../api/licenceTypes';
import { expiryCellText, expiryLeftText } from '../i18n/licenceLabels';
import { canDraft } from '../lib/signals';
import { stateErrorText } from '../lib/stateTransition';
import { uid } from '../mocks/fixtures';
import { INGEST_ALERT_TEXT, MASTER_KEYS, ingestAlerts, setMockIngestHeartbeat, setMockMasterAlerts } from '../mocks/ingestAlerts';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { patchSignal, signalsNow } from '../mocks/signalHandlers';
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
type Err = { error: { code: string; details: Record<string, unknown> } };
async function draft(ids: unknown) {
  const r = await apiFetch(`${API}/plan-drafts`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ signal_ids: ids }) });
  return { status: r.status, body: (await r.json()) as Err & { id?: string } };
}

describe('#37 拟定草案的判定顺序（§7.7 七步）', () => {
  it('① 格式不对 → 400 VALIDATION_ERROR（signal_ids）', async () => {
    for (const ids of [[], 'x', ['not-a-uuid'], null]) {
      const r = await draft(ids);
      expect(r.status).toBe(400);
      expect(r.body.error.code).toBe('VALIDATION_ERROR');
    }
  });
  it('② 不存在 → 400 fields=[{signal_ids, not_found}]，不再是 404；与存在的 blocked 信号混在一起也先报 not_found', async () => {
    for (const ids of [[uid(9999)], [uid(1000), uid(9999)]]) {
      const r = await draft(ids);
      expect(r.status).toBe(400);
      expect(r.body.error.code).toBe('VALIDATION_ERROR');
      expect(r.body.error.details.fields).toEqual([{ field: 'signal_ids', issue: 'not_found' }]);
    }
    const e = new ApiError(400, 'VALIDATION_ERROR', 'x', { fields: [{ field: 'signal_ids', issue: 'not_found' }] }, null);
    expect(stateErrorText(e, 'signal')).toBe('候选信号不存在或已不可见');
  });
  it('③ 证券 / 动作不一致 → 400（先于终态与 blocked）', async () => {
    const r = await draft([uid(1000), uid(1003)]);
    expect(r.status).toBe(400);
    expect(r.body.error.code).toBe('VALIDATION_ERROR');
  });
  it('④ simulating 与 blocked 同时成立 → STRATEGY_VERSION_NOT_RUNNABLE', async () => {
    patchSignal(uid(1000), { lifecycle: 'simulating' });
    const r = await draft([uid(1000)]);
    expect(r.status).toBe(409);
    expect(r.body.error.code).toBe('STRATEGY_VERSION_NOT_RUNNABLE');
  });
  it('⑤ 终态（与 blocked 混合时也先报终态）→ INVALID_STATE_TRANSITION，allowed=[]', async () => {
    const r = await draft([uid(1000), uid(1005)]);
    expect(r.status).toBe(409);
    expect(r.body.error.code).toBe('INVALID_STATE_TRANSITION');
    expect(r.body.error.details).toEqual({ from: 'expired', to: 'drafted', allowed: [] });
  });
  it('⑥ blocked → SIGNAL_NOT_EXECUTABLE，不论原因码；reason_ids 去重后按 id 升序', async () => {
    const a = await draft([uid(1000)]);
    expect(a.status).toBe(409);
    expect(a.body.error.code).toBe('SIGNAL_NOT_EXECUTABLE');
    expect(a.body.error.details.reason_ids).toEqual([uid(1001), uid(1002)]);
    const b = await draft([uid(1026)]);
    expect(b.body.error.code).toBe('SIGNAL_NOT_EXECUTABLE');
    expect(b.body.error.details.reason_ids).toEqual([uid(1027), uid(1028)]);
    const c = await draft([uid(1016), uid(1016)]);
    expect(c.body.error.details.reason_ids).toEqual([uid(1017)]);
  });
  it('⑥ 状态为 open 但仍有 active 原因 → 同样 SIGNAL_NOT_EXECUTABLE', async () => {
    patchSignal(uid(1035), { state: 'open' });
    const r = await draft([uid(1035)]);
    expect(r.status).toBe(409);
    expect(r.body.error.code).toBe('SIGNAL_NOT_EXECUTABLE');
    expect(r.body.error.details.reason_ids).toEqual([uid(1036)]);
  });
  it('open 且无原因 → 201，信号变为 drafted；open/drafted/released 可拟定，其余不可', async () => {
    patchSignal(uid(1005), { state: 'open' });
    const r = await draft([uid(1005)]);
    expect(r.status).toBe(201);
    expect(signalsNow().find((c) => c.id === uid(1005))?.state).toBe('drafted');
    expect(['open', 'drafted', 'released', 'blocked', 'expired'].map((s) => canDraft(s as never))).toEqual([true, true, true, false, false]);
  });
});

const baseStatus = async () => {
  mockLoginAs('admin');
  return getJson<AdminIngestStatus>('/admin/ingest/status');
};

describe('#38 采集心跳', () => {
  it('mock：setMockIngestHeartbeat 写 heartbeat 字段；stale/unknown 出告警，paused/ok 不出', async () => {
    for (const [hb, alert] of [['ok', false], ['stale', true], ['paused', false], ['unknown', true]] as const) {
      setMockIngestHeartbeat(hb);
      const d = await baseStatus();
      expect(d.heartbeat).toBe(hb);
      expect(d.alerts.some((a) => a.key === 'heartbeat')).toBe(alert);
      expect(d).not.toHaveProperty('heartbeat_at');
    }
  });
  it.each([['ok', '正常'], ['stale', '心跳超时'], ['paused', '已暂停'], ['unknown', '无法判断'], ['weird', '无法判断'], [undefined, '无法判断']])(
    'heartbeat=%s → “%s”，前端不自行生成告警', async (hb, text) => {
      const d = await baseStatus();
      const body: Record<string, unknown> = { ...d, alerts: [] };
      if (hb === undefined) delete body.heartbeat; else body.heartbeat = hb;
      server.use(http.get(`${API}/admin/ingest/status`, () => HttpResponse.json(body)));
      renderAt('/admin/ingest');
      expect(await screen.findByTestId('ingest-heartbeat', undefined, { timeout: 5000 })).toHaveTextContent(text);
      expect(screen.getByTestId('ingest-alerts-empty')).toBeInTheDocument();
    });
});

describe('#39 告警 message 原样显示；master.* 文案与排序', () => {
  it('message 原样显示（不按 key 映射），不认识的 key / level 照样显示', async () => {
    const d = await baseStatus();
    server.use(http.get(`${API}/admin/ingest/status`, () => HttpResponse.json({ ...d, alerts: [
      { level: 'critical', key: 'heartbeat', message: '服务端给的示例文案 A' },
      { level: 'warning', key: 'future.key', message: '服务端新增的示例告警' },
      { level: 'notice', key: 'x.y', message: '未知级别示例' },
    ] })));
    renderAt('/admin/ingest');
    const box = await screen.findByTestId('ingest-alerts', undefined, { timeout: 5000 });
    expect(within(box).getByTestId('ingest-alert-heartbeat')).toHaveTextContent('服务端给的示例文案 A');
    expect(within(box).getByTestId('ingest-alert-heartbeat')).not.toHaveTextContent(INGEST_ALERT_TEXT.heartbeat);
    expect(within(box).getByTestId('ingest-alert-future.key')).toHaveTextContent('服务端新增的示例告警');
    expect(within(box).getByTestId('ingest-alert-x.y')).toHaveTextContent('未知级别示例');
  });
  it('mock 5 条文案按 §7.9 ⑥；同级 #31 ② 的键在前、master.* 在后；critical 在前（licence.expired 先于 master.vendor_unknown）', async () => {
    expect(MASTER_KEYS.map((k) => INGEST_ALERT_TEXT[k])).toEqual([
      '证券名单更新失败，暂时沿用上一版', '行情源仍列着已退市的证券', '行情源出现交易所名单里没有的证券，暂不收录',
      '部分证券在行情源中暂时没有数据', '部分证券的名称或上市信息与其他来源不一致，待核对',
    ]);
    const d = await baseStatus();
    const quiet = { ...d, leader: d.leader, budget: { per_minute_limit: 100, used_last_minute: 1 }, queues: [], errors_24h: [], ip_limit_alerts_24h: 0,
      freshness: d.freshness.map((f) => ({ ...f, data_status: 'fresh' as const })), heartbeat: 'ok' as const };
    const lic = { ...d.licences[0], status: 'expired' as const, days_left: -1 };
    const all = { 'master.field_mismatch': 'warning', 'master.quote_missing': 'warning', 'master.vendor_unknown': 'warning', 'master.vendor_stale_listed': 'warning', 'master.snapshot_rejected': 'warning' } as const;
    expect(ingestAlerts({ ...quiet, licences: [lic] }, all).map((a) => a.key)).toEqual(['licence.expired', ...MASTER_KEYS]);
    const crit = ingestAlerts({ ...quiet, licences: [lic] }, { 'master.vendor_unknown': 'warning', 'master.snapshot_rejected': 'critical' });
    expect(crit.map((a) => [a.level, a.key])).toEqual([['critical', 'master.snapshot_rejected'], ['warning', 'licence.expired'], ['warning', 'master.vendor_unknown']]);
    expect(crit[0].message).toBe('证券名单更新失败，暂时沿用上一版');
    setMockMasterAlerts({ 'master.vendor_unknown': 'warning' });
    const live = await getJson<AdminIngestStatus>('/admin/ingest/status');
    expect(live.alerts.at(-1)).toEqual({ level: 'warning', key: 'master.vendor_unknown', message: '行情源出现交易所名单里没有的证券，暂不收录' });
  });
});

describe('#40 到期剩余天数文案', () => {
  it('null / 负数 / 0 / 正数', () => {
    expect([null, -3, 0, 7].map(expiryLeftText)).toEqual(['未填写到期日', '已过填写的到期日', '今天到期', '还剩 7 天']);
    expect(expiryCellText(null, null)).toBe('未填写到期日');
    expect(expiryCellText('2026-11-09', 7)).toBe('2026-11-09（还剩 7 天）');
  });
  it('days_left 为 null 不出 licence.expiring', async () => {
    const d = await baseStatus();
    const row = { ...d.licences[0], status: 'active' as const, expires_on: null, days_left: null };
    expect(ingestAlerts({ ...d, licences: [row] }).some((a) => a.key.startsWith('licence.expir'))).toBe(false);
  });
  it('采集状态页：管理员自己的证书未填到期日 → “未填写到期日”', async () => {
    const d = await baseStatus();
    const row = d.licences.find((l) => l.user_id === uid(3))!;
    expect(row.days_left).toBeNull();
    renderAt('/admin/ingest');
    expect(await screen.findByTestId(`ingest-exp-${row.licence_id}`, undefined, { timeout: 5000 })).toHaveTextContent(/^未填写到期日$/);
  });
  it('数据证书（管理）页：未填 / 已过 / 今天 / 还剩 N 天；未设置证书显示 —', async () => {
    mockLoginAs('admin');
    renderAt('/admin/data-licences');
    const table = await screen.findByTestId('lic-table', undefined, { timeout: 5000 });
    await waitFor(() => expect(within(table).getByTestId(`dl-exp-${uid(3)}`)).toHaveTextContent(/^未填写到期日$/));
    expect(within(table).getByTestId(`dl-exp-${uid(2)}`)).toHaveTextContent(/（还剩 \d+ 天）$/);
  });
  it.each([[null, null, '未填写到期日'], ['2026-10-30', -3, '2026-10-30（已过填写的到期日）'], ['2026-11-02', 0, '2026-11-02（今天到期）'], ['2026-11-12', 10, '2026-11-12（还剩 10 天）']])(
    '设置页：expires_on=%s days=%s → %s', async (exp, days, text) => {
      mockLoginAs('demo_user');
      const cur = await getJson<DataLicenceStatus>('/me/data-licence');
      server.use(http.get(`${API}/me/data-licence`, () => HttpResponse.json({ ...cur, status: 'active', expires_on: exp, days_to_expiry: days })));
      renderAt('/settings/data-licence');
      expect(await screen.findByTestId('licence-expiry', undefined, { timeout: 5000 })).toHaveTextContent(text as string);
    });
});
