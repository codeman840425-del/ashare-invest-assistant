/** T-F28：真实同源接口、门禁权限负例、null 缺口和模拟标记。 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { DAILY_REPORTS, uid, SUGGESTIONS } from '../mocks/fixtures';
import { EXAMPLE_PROMOTION_REPORT } from '../mocks/promotionFixtures';
import { DEMO_REVIEW_ID } from '../mocks/promotionHandlers';
import { promotionRows } from './admin/AdminStrategyGatesPage';
import { RiskFlagView } from '../components/RiskFlagView';
import { ActionBadge } from '../components/common';
import { NAV_ADMIN_GATES, navMoreFor } from '../app/nav';
import { confirmMockPromotion } from '../test/confirmMockPromotion';
import { apiFetch } from '../test/apiFetch';

beforeAll(() => preloadRoutes(routes), 30_000);
const API = '/api/v1';
const pagePath = `/admin/strategy-gates?review_id=${DEMO_REVIEW_ID}`;
function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

describe('T-F28 门禁', () => {
  beforeEach(() => mockLoginAs('admin'));
  it('逐条 G1–G6；null+原因变 warn，但不覆盖夹具 fail，缺项不是 pass', () => {
    const report = structuredClone(EXAMPLE_PROMOTION_REPORT);
    report.gate_results.find((g) => g.gate === 'G6')!.result = 'pass';
    const rows = promotionRows(report);
    expect(rows.map((g) => g.gate)).toEqual(['G1', 'G2', 'G3', 'G4', 'G5', 'G6']);
    expect(rows[5]).toMatchObject({ result: 'warn' });
    expect(rows[5].detail).toContain('no_history');
    report.gate_results[5].result = 'fail';
    expect(promotionRows(report)[5].result).toBe('fail');
    report.gate_results = [];
    expect(promotionRows(report).every((g) => g.result === 'skipped')).toBe(true);
  });
  it('只有管理员导航；普通用户直达不见审批按钮，也不请求报告', async () => {
    mockLoginAs('demo_user');
    let reads = 0;
    server.use(http.get(`${API}/promotion-requests/:id`, () => { reads++; return HttpResponse.json(EXAMPLE_PROMOTION_REPORT); }));
    expect(navMoreFor('user')).not.toContainEqual(NAV_ADMIN_GATES);
    expect(navMoreFor('admin')).toContainEqual(NAV_ADMIN_GATES);
    renderAt(pagePath);
    await screen.findByTestId('not-found');
    expect(screen.queryByTestId('approve-g7')).not.toBeInTheDocument();
    expect(reads).toBe(0);
  });
  it('批准必须填写意见并本人点击；不自动调用生命周期接口', async () => {
    let decisions = 0;
    let lifecycle = 0;
    let body: unknown;
    server.use(
      http.post(`${API}/admin/promotions/:id/decision`, async ({ request }) => { decisions++; body = await request.json(); return HttpResponse.json({}); }),
      http.post(`${API}/admin/strategies/:id/versions/:vid/lifecycle`, () => { lifecycle++; return HttpResponse.json({}); }),
    );
    renderAt(pagePath);
    const button = await screen.findByTestId('approve-g7');
    expect(screen.getByTestId('max-jaccard')).toHaveTextContent('近 120 日历史不足');
    expect(button).toBeDisabled();
    expect(decisions).toBe(0);
    fireEvent.change(screen.getByLabelText('G7 审核意见'), { target: { value: '本人已核对示例数据警告' } });
    fireEvent.click(screen.getByRole('checkbox', { name: '本人已核实并确认 G6 警告' }));
    fireEvent.click(button);
    await confirmMockPromotion('decision');
    await waitFor(() => expect(decisions).toBe(1));
    expect(body).toEqual({ decision: 'approved', comment: '本人已核对示例数据警告', ack_warn_gates: ['G6'], password: 'x'.repeat(10) });
    expect(lifecycle).toBe(0);
  });
  it('403 明确说明未完成，不重试、不自动晋级', async () => {
    let writes = 0;
    server.use(http.post(`${API}/admin/promotions/:id/decision`, () => { writes++; return HttpResponse.json({ error: { code: 'FORBIDDEN', message: '无权限', details: null } }, { status: 403 }); }));
    renderAt(pagePath);
    await screen.findByTestId('approve-g7');
    fireEvent.change(screen.getByLabelText('G7 审核意见'), { target: { value: '本人核对' } });
    fireEvent.click(screen.getByRole('checkbox', { name: '本人已核实并确认 G6 警告' }));
    fireEvent.click(screen.getByTestId('approve-g7'));
    await confirmMockPromotion('decision');
    await screen.findByText(/没有审批权限（403）/);
    expect(writes).toBe(1);
    expect(screen.queryByText('所选版本已转入模拟中')).not.toBeInTheDocument();
  });
  it('失败/缺失门禁禁用 G7', async () => {
    const report = structuredClone(EXAMPLE_PROMOTION_REPORT);
    report.gate_results[1].result = 'fail';
    server.use(http.get(`${API}/promotion-requests/:id`, () => HttpResponse.json(report)));
    renderAt(pagePath);
    await screen.findByTestId('approve-g7');
    fireEvent.change(screen.getByLabelText('G7 审核意见'), { target: { value: '不能绕过失败' } });
    expect(screen.getByTestId('approve-g7')).toBeDisabled();
  });
  it('生命周期必须另行选择版本及原因，只在点击后发送契约请求', async () => {
    const writes: unknown[] = [];
    server.use(http.post(`${API}/admin/strategies/:id/versions/:vid/lifecycle`, async ({ request, params }) => {
      writes.push({ id: params.id, vid: params.vid, body: await request.json() });
      return HttpResponse.json({ from: 'draft', to: 'simulating' });
    }));
    server.use(http.get(`${API}/promotion-requests/:id`, () => HttpResponse.json({ ...EXAMPLE_PROMOTION_REPORT, decision: 'approved' })));
    renderAt(pagePath);
    await screen.findByTestId('approve-g7');
    expect(screen.getByTestId('to-simulating')).toBeDisabled();
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '目标策略版本' }));
    fireEvent.click(await screen.findByText('门禁草稿（示例数据） · v1', { selector: '.ant-select-item-option-content' }));
    fireEvent.change(screen.getByLabelText('生命周期变更原因'), { target: { value: '本人检查完毕' } });
    expect(writes).toHaveLength(0);
    fireEvent.click(screen.getByTestId('to-simulating'));
    await confirmMockPromotion('lifecycle');
    await waitFor(() => expect(writes).toEqual([{ id: uid(512), vid: uid(322), body: { to: 'simulating', reason: '本人检查完毕', review_id: DEMO_REVIEW_ID, password: 'x'.repeat(10) } }]));
  });
  it('示例管理写端点拒绝普通用户', async () => {
    mockLoginAs('demo_user');
    for (const path of [`/admin/promotions/${DEMO_REVIEW_ID}/decision`, `/admin/strategies/${uid(512)}/versions/${uid(322)}/lifecycle`]) {
      const res = await apiFetch(`${API}${path}`, { method: 'POST', body: JSON.stringify({ decision: 'approved', comment: 'test', to: 'simulating', reason: 'test' }) });
      expect([403, 404]).toContain(res.status);
    }
  });
});

describe('T-F28 产品字段', () => {
  it('建议列表接住 status 筛选，真实取数并保留链接，不再跳首张', async () => {
    const router = renderAt('/suggestions?status=invalidated');
    await screen.findByTestId('suggestions-page');
    await screen.findByText('当前筛选没有候选信号卡');
    expect(screen.queryByTestId('placeholder')).not.toBeInTheDocument();
    expect(router.state.location.pathname + router.state.location.search).toBe('/suggestions?status=invalidated');
  });
  it('限量和门控分别显示、证据可追溯，不在前端推算 RC3/RC4', () => {
    render(<RiskFlagView flag={{ control: 'total_exposure', level: 'warning', message: '示例数据：拟超限', gated_actions: [], quantity_cap: '200', evidence_ids: [] }} evidence={[]} />);
    expect(screen.getByTestId('risk-flag')).toHaveTextContent('未门控（仅提示或限量）');
    expect(screen.getByTestId('risk-flag')).toHaveTextContent('数量上限 200');
  });
  it('摘要的模拟版本明确标注模拟中', () => {
    render(<ActionBadge action="buy" lifecycle="simulating" />);
    expect(screen.getByText('· 模拟中')).toBeInTheDocument();
  });
  it('日报无比较基准和账户 null 不崩溃、不显示伪 0', async () => {
    const report = structuredClone(DAILY_REPORTS[0]);
    report.stocks[0].change_from_previous = null;
    report.stocks[0].change_fields = [];
    if (report.account) { report.account.position_pct = null; report.account.pnl_day = null; }
    report.gaps.push({ key: 'stocks.change_from_previous', reason: 'no_source', message: '示例数据：没有前一开市日完成版日报' });
    server.use(http.get(`${API}/daily-reports/:date`, () => HttpResponse.json(report)));
    renderAt(`/daily-reports/${report.date}`);
    await screen.findByText('无比较基准 · 见数据缺口');
    expect(screen.getByText('—（缺少计算基准）')).toBeInTheDocument();
    expect(screen.getByText('—（缺少资产分母）')).toBeInTheDocument();
    expect(screen.getByText('示例数据：没有前一开市日完成版日报')).toBeInTheDocument();
  });
  it('建议详情展示引擎策略版本、置信度分项及风控数量上限', async () => {
    const sg = structuredClone(SUGGESTIONS[0]);
    sg.engine_policy = { version_no: 3, content_sha256: 'demo-policy-hash' };
    sg.risk_flags = [{ control: 'sector_concentration', level: 'warning', message: '示例数据：所属行业超限', gated_actions: ['buy', 'add'], quantity_cap: '0', evidence_ids: [] }];
    server.use(http.get(`${API}/suggestions/:id`, () => HttpResponse.json(sg)));
    renderAt(`/suggestions/${sg.id}`);
    await screen.findByTestId('suggestion-detail');
    expect(screen.getByTestId('engine-policy')).toHaveTextContent('v3 · demo-policy-hash');
    expect(within(screen.getByTestId('risk-flag')).getByText(/已门控（gated）/)).toBeInTheDocument();
    expect(screen.getAllByText(/数据完整度/).length).toBeGreaterThan(0);
  });
});
