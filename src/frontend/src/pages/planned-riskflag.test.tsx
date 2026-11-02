/** planned 状态显示 + 风险标记文案（契约 v0.2.9 #29：star_st = 退市风险警示，delisting = 退市整理） */
import { render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { SECURITY_RISK_FLAG, SECURITY_RISK_FLAG_TIP, LISTING_STATUS } from '../i18n/labels';
import { RESEARCH_STATUS } from '../i18n/candidateLabels';
import { ENUMS } from '../api/enums';
import type { ResearchCandidate, ResearchCandidateSummary } from '../api/candidateTypes';
import { candidatesNow } from '../mocks/candidateHandlers';
import { DEMO_RISK_FLAG, searchSecurities, securityProfile } from '../mocks/marketFixtures';
import { mockLoginAs } from '../mocks/session';
import { apiFetch } from '../test/apiFetch';

beforeAll(() => preloadRoutes(routes), 30_000);

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

const API = '/api/v1';
const WAIT = { timeout: 5000 };
function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}
const PLANNED = () => candidatesNow().find((s) => s.head.status === 'planned')!;

describe('#29 风险标记文案', () => {
  it('三个取值的文案与契约原文一致，且覆盖全部枚举', () => {
    expect(SECURITY_RISK_FLAG.star_st).toBe('退市风险警示');
    expect(SECURITY_RISK_FLAG.delisting).toBe('退市整理');
    expect(SECURITY_RISK_FLAG.st).toBe('其他风险警示');
    expect(Object.keys(SECURITY_RISK_FLAG).sort()).toEqual([...ENUMS.security_risk_flag].sort());
    expect(SECURITY_RISK_FLAG_TIP.star_st).toContain('*ST');
    expect(SECURITY_RISK_FLAG_TIP.st).toContain('ST');
    // 旧文案“退市风险”已不再使用；delisting 标记与上市状态“退市整理期”分开
    expect(Object.values(SECURITY_RISK_FLAG)).not.toContain('退市风险');
    expect(LISTING_STATUS.delisting_period).toBe('退市整理期');
  });
  it('mock：示例证券的风险标记同时出现在搜索与证券主数据中', () => {
    const [code, flag] = Object.entries(DEMO_RISK_FLAG)[0];
    expect(flag).toBe('star_st');
    expect(securityProfile(code)!.risk_flag).toBe('star_st');
    expect(searchSecurities(code.slice(0, 6)).items.find((h) => h.security_code === code)!.risk_flag).toBe('star_st');
    expect(securityProfile('600000.SH')!.risk_flag).toBeNull();
  });
  it('个股页风险标记 Tag 显示“退市风险警示”，悬停说明带 *ST', async () => {
    renderAt('/stocks/002001.SZ');
    const tag = await screen.findByTestId('risk-flag-tag', undefined, WAIT);
    expect(tag).toHaveTextContent('退市风险警示');
    expect(tag).toHaveAttribute('data-flag', 'star_st');
    expect(tag).toHaveAttribute('title', '退市风险警示（*ST）');
  });
  it('没有风险标记的证券不显示 Tag', async () => {
    renderAt('/stocks/600000.SH');
    await screen.findByTestId('stock-head', undefined, WAIT);
    expect(screen.queryByTestId('risk-flag-tag')).toBeNull();
  });
});

describe('planned（已计划）显示', () => {
  beforeEach(() => mockLoginAs('admin'));

  it('mock：默认列表含 planned，status=planned 只返回已计划；planned 为终态，新建版本 409 allowed=[]', async () => {
    const id = PLANNED().head.id;
    const all = (await (await apiFetch(`${API}/candidates`)).json()) as { items: ResearchCandidateSummary[] };
    expect(all.items.find((x) => x.id === id)?.status).toBe('planned');
    const only = (await (await apiFetch(`${API}/candidates?status=planned`)).json()) as { items: ResearchCandidateSummary[] };
    expect(only.items.map((x) => x.id)).toEqual([id]);
    const r = await apiFetch(`${API}/candidates/${id}/versions`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ base_version_no: 1, thesis: null, conditions_to_hold: [], decision: null, decision_reason: null }),
    });
    expect(r.status).toBe(409);
    const body = (await r.json()) as { error: { code: string; details: { allowed: unknown[] } } };
    expect(body.error.code).toBe('INVALID_STATE_TRANSITION');
    expect(body.error.details.allowed).toEqual([]);
  });
  it('列表页状态 Tag 显示“已计划”', async () => {
    renderAt('/candidates');
    await waitFor(() => expect(screen.getAllByTestId('cand-status').map((x) => x.textContent)).toContain(RESEARCH_STATUS.planned.text), WAIT);
    expect(RESEARCH_STATUS.planned.text).toBe('已计划');
  });
  it('详情页：状态 Tag、已计划提示；终态不出新建版本表单；plan_ids 为空时不出计划链接', async () => {
    const c = PLANNED();
    renderAt(`/candidates/${c.head.id}`);
    expect(await screen.findByTestId('cand-detail-status', undefined, WAIT)).toHaveTextContent('已计划');
    const alert = screen.getByTestId('cand-planned');
    expect(alert).toHaveTextContent('研究候选已结束');
    expect(alert.querySelector('a[href^="/plans/"]')).toBeNull();
    expect(screen.queryByTestId('cand-dropped')).toBeNull();
    expect(screen.queryByTestId('cand-actions')).toBeNull();
    expect(screen.queryByTestId('cand-new-version-btn')).toBeNull();
    expect(screen.getByTestId('cand-history')).toBeInTheDocument();
    const detail = (await (await apiFetch(`${API}/candidates/${c.head.id}`)).json()) as ResearchCandidate;
    expect(detail.plan_ids).toEqual([]);
  });
  it('他人（demo_user）看不到管理员示例账户的 planned 候选', async () => {
    mockLoginAs('demo_user');
    const r = await apiFetch(`${API}/candidates/${PLANNED().head.id}`);
    expect(r.status).toBe(404);
  });
});
