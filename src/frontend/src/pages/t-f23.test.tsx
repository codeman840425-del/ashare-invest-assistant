/** T-F23 研究候选（契约 v0.2.9 §7.7A）：mock 接口行为 + 列表 / 详情 / 新建 / 新建版本 / 入口 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { NAV_MORE } from '../app/nav';
import { preloadRoutes } from '../test/preloadRoutes';
import { parseCandidateStatus } from '../api/candidateQueries';
import type { ResearchCandidate, ResearchCandidateSummary, CandidateVersion } from '../api/candidateTypes';
import { uid } from '../mocks/fixtures';
import { candidatesNow } from '../mocks/candidateHandlers';
import { mockLoginAs, state as session } from '../mocks/session';
import { apiFetch } from '../test/apiFetch';

beforeAll(() => preloadRoutes(routes), 30_000);

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

const API = '/api/v1';
type Paged<T> = { items: T[]; next_cursor: string | null };
type Err = { error: { code: string; details: Record<string, unknown> } };
const get = async <T,>(path: string) => { const r = await apiFetch(`${API}${path}`); return { status: r.status, body: (await r.json()) as T }; };
const post = async <T,>(path: string, body: unknown, key?: string) => {
  const r = await apiFetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...(key ? { 'Idempotency-Key': key } : {}) },
    body: JSON.stringify(body),
  });
  return { status: r.status, body: (await r.json()) as T };
};
const issues = (b: unknown) => ((b as Err).error.details.fields as { field: string; issue: string }[]);
function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}
const [C1, C2, C3, C4] = [0, 1, 2, 3].map((i) => candidatesNow()[i].head.id);
const SG_000001 = uid(101);
const manual = (code: string, extra: Record<string, unknown> = {}) => ({ origin: 'manual', security_code: code, suggestion_id: null, thesis: null, conditions_to_hold: [], ...extra });
const version = (base: number, extra: Record<string, unknown> = {}) => ({ base_version_no: base, thesis: null, conditions_to_hold: [], decision: null, decision_reason: null, ...extra });
const WAIT = { timeout: 5000 };

describe('mock：GET /candidates 列表与状态过滤', () => {
  it('默认 researching,watching,planned：不含已放弃，也不含他人的；按创建时间倒序', async () => {
    const r = await get<Paged<ResearchCandidateSummary>>('/candidates');
    expect(r.status).toBe(200);
    expect(r.body.items.map((x) => x.id)).toEqual([C2, C1]);
    expect(r.body.items.some((x) => x.id === C4)).toBe(false);
  });
  it('status=all 含已放弃；status=dropped 只要已放弃；非法状态 400', async () => {
    expect((await get<Paged<ResearchCandidateSummary>>('/candidates?status=all')).body.items.map((x) => x.id)).toEqual([C2, C1, C3]);
    expect((await get<Paged<ResearchCandidateSummary>>('/candidates?status=dropped')).body.items.map((x) => x.id)).toEqual([C3]);
    const bad = await get('/candidates?status=closed');
    expect(bad.status).toBe(400);
    expect(issues(bad.body)).toEqual([{ field: 'status', issue: 'invalid' }]);
  });
  it('反查：security_code、suggestion_id、origin', async () => {
    expect((await get<Paged<ResearchCandidateSummary>>('/candidates?security_code=600000.SH')).body.items.map((x) => x.id)).toEqual([C1]);
    expect((await get<Paged<ResearchCandidateSummary>>(`/candidates?suggestion_id=${uid(100)}`)).body.items.map((x) => x.id)).toEqual([C1]);
    expect((await get<Paged<ResearchCandidateSummary>>('/candidates?origin=from_stock')).body.items.map((x) => x.id)).toEqual([C2]);
  });
  it('他人的候选：详情、版本、版本列表都是 404', async () => {
    expect((await get(`/candidates/${C4}`)).status).toBe(404);
    expect((await get(`/candidates/${C4}/versions`)).status).toBe(404);
    expect((await get(`/candidates/${C4}/versions/1`)).status).toBe(404);
    expect((await post(`/candidates/${C4}/versions`, version(1))).status).toBe(404);
  });
  it('parseCandidateStatus：all / 多值 / 空与非法回到默认', () => {
    expect(parseCandidateStatus('all')).toBe('all');
    expect(parseCandidateStatus('dropped,watching')).toEqual(['dropped', 'watching']);
    expect(parseCandidateStatus('')).toEqual(['researching', 'watching', 'planned']);
    expect(parseCandidateStatus('x')).toEqual(['researching', 'watching', 'planned']);
  });
});

describe('mock：POST /candidates 新建', () => {
  it('手工新建：201，第 1 版，研究中；系统理由为空，条件固定为假设', async () => {
    const r = await post<ResearchCandidate>('/candidates', manual('000002.SZ', {
      thesis: '  示例研究要点  ',
      conditions_to_hold: [{ text: '示例条件', verify_by: '2026-12-01', verify_method: null, confidence: 'low' }],
    }));
    expect(r.status).toBe(201);
    expect(r.body).toMatchObject({ origin: 'manual', status: 'researching', version_count: 1, suggestion_id: null, security_code: '000002.SZ' });
    expect(r.body.current_version).toMatchObject({ version_no: 1, thesis: '示例研究要点', reasons: [], decision: null });
    expect(r.body.current_version.conditions_to_hold[0].epistemic_type).toBe('hypothesis');
    expect(r.body.current_version.fit_assessment).toMatchObject({ profile_filled: true, holdings_available: true });
  });
  it('候选信号卡来源：不带代码时取建议的证券，理由从建议复制', async () => {
    const r = await post<ResearchCandidate>('/candidates', { origin: 'suggestion', security_code: null, suggestion_id: SG_000001, thesis: null, conditions_to_hold: [] });
    expect(r.status).toBe(201);
    expect(r.body).toMatchObject({ security_code: '000001.SZ', suggestion_id: SG_000001, origin: 'suggestion' });
    expect(r.body.current_version.reasons.length).toBeGreaterThan(0);
  });
  it('请求体校验：strategy_screen 不支持；mismatch；条件缺验证方式；manual 带 suggestion_id', async () => {
    expect(issues((await post('/candidates', manual('000002.SZ', { origin: 'strategy_screen' }))).body)).toContainEqual({ field: 'origin', issue: 'not_supported' });
    expect(issues((await post('/candidates', { origin: 'suggestion', security_code: '600000.SH', suggestion_id: SG_000001, thesis: null, conditions_to_hold: [] })).body))
      .toEqual([{ field: 'security_code', issue: 'mismatch' }]);
    const r = await post('/candidates', manual('000002.SZ', { conditions_to_hold: [{ text: '示例', verify_by: null, verify_method: '  ', confidence: null }] }));
    expect(r.status).toBe(400);
    expect(issues(r.body)).toEqual([{ field: 'conditions_to_hold[0]', issue: 'verification_required' }]);
    expect(issues((await post('/candidates', manual('000002.SZ', { suggestion_id: SG_000001 }))).body)).toContainEqual({ field: 'suggestion_id', issue: 'not_allowed' });
  });
  it('证券：未知代码、ETF / 指数不支持；建议不存在 not_found', async () => {
    expect(issues((await post('/candidates', manual('999999.SH'))).body)).toEqual([{ field: 'security_code', issue: 'unknown_security' }]);
    expect(issues((await post('/candidates', manual('510300.SH'))).body)).toEqual([{ field: 'security_code', issue: 'security_type_not_supported' }]);
    expect(issues((await post('/candidates', { origin: 'suggestion', security_code: null, suggestion_id: uid(9999), thesis: null, conditions_to_hold: [] })).body))
      .toEqual([{ field: 'suggestion_id', issue: 'not_found' }]);
  });
  it('重复：已有研究中 / 观察中的同一证券 409 CONFLICT 带 existing_id；已放弃的可以重新新建', async () => {
    const dup = await post<Err>('/candidates', manual('600000.SH'));
    expect(dup.status).toBe(409);
    expect(dup.body.error).toMatchObject({ code: 'CONFLICT', details: { field: 'security_code', existing_id: C1 } });
    expect((await post('/candidates', manual('600002.SH'))).status).toBe(201);
  });
  it('Idempotency-Key：同键同体重放同一结果；同键异体 409 IDEMPOTENCY_CONFLICT', async () => {
    const a = await post<ResearchCandidate>('/candidates', manual('000002.SZ'), 'k-1');
    const b = await post<ResearchCandidate>('/candidates', manual('000002.SZ'), 'k-1');
    expect(b.status).toBe(201);
    expect(b.body.id).toBe(a.body.id);
    const c = await post<Err>('/candidates', manual('300001.SZ'), 'k-1');
    expect(c.status).toBe(409);
    expect(c.body.error.code).toBe('IDEMPOTENCY_CONFLICT');
  });
  it('未填画像、未导入持仓的用户：fit 两个标记为 false', async () => {
    mockLoginAs('novice_user');
    session.profiles.delete(uid(13));
    const r = await post<ResearchCandidate>('/candidates', manual('000002.SZ'));
    expect(r.status).toBe(201);
    expect(r.body.current_version.fit_assessment).toMatchObject({ profile_filled: false, holdings_available: false, hints: [] });
  });
});

describe('mock：POST /candidates/{id}/versions 新建版本', () => {
  it('乐观锁：base_version_no 不是当前版本 409 VERSION_CONFLICT 带 current_version_no', async () => {
    const r = await post<Err>(`/candidates/${C1}/versions`, version(1));
    expect(r.status).toBe(409);
    expect(r.body.error).toMatchObject({ code: 'VERSION_CONFLICT', details: { current_version_no: 2 } });
  });
  it('决定须带理由（先去掉首尾空格）；不做决定不能带理由', async () => {
    expect(issues((await post(`/candidates/${C1}/versions`, version(2, { decision: 'drop', decision_reason: '   ' }))).body)).toEqual([{ field: 'decision_reason', issue: 'required' }]);
    expect(issues((await post(`/candidates/${C1}/versions`, version(2, { decision_reason: '示例' }))).body)).toEqual([{ field: 'decision_reason', issue: 'not_allowed' }]);
  });
  it('放弃后为终态：再新建版本 409 INVALID_STATE_TRANSITION；旧版本不变', async () => {
    const r = await post<ResearchCandidate>(`/candidates/${C1}/versions`, version(2, { decision: 'drop', decision_reason: ' 示例理由 ' }));
    expect(r.status).toBe(201);
    expect(r.body).toMatchObject({ status: 'dropped', version_count: 3 });
    expect(r.body.current_version).toMatchObject({ version_no: 3, decision: 'drop', decision_reason: '示例理由' });
    const again = await post<Err>(`/candidates/${C1}/versions`, version(3));
    expect(again.status).toBe(409);
    expect(again.body.error).toMatchObject({ code: 'INVALID_STATE_TRANSITION', details: { from: 'dropped', allowed: [] } });
    const v1 = await get<CandidateVersion>(`/candidates/${C1}/versions/1`);
    expect(v1.body.decision).toBeNull();
    const list = await get<Paged<CandidateVersion>>(`/candidates/${C1}/versions`);
    expect(list.body.items.map((v) => v.version_no)).toEqual([3, 2, 1]);
  });
  it('转为观察 / 继续研究改变状态', async () => {
    const w = await post<ResearchCandidate>(`/candidates/${C2}/versions`, version(1, { decision: 'watch', decision_reason: '示例' }));
    expect(w.body.status).toBe('watching');
    const c = await post<ResearchCandidate>(`/candidates/${C2}/versions`, version(2, { decision: 'continue', decision_reason: '示例' }));
    expect(c.body.status).toBe('researching');
  });
});

describe('页面：研究候选列表', () => {
  it('入口在“更多”菜单；默认不显示已放弃，勾选“全部状态”后用 status=all', async () => {
    expect(NAV_MORE.some((n) => n.path === '/candidates' && n.label === '研究候选')).toBe(true);
    const router = renderAt('/candidates');
    const page = await screen.findByTestId('candidates-page');
    await within(page).findByTestId(`cand-link-${C1}`, undefined, WAIT);
    expect(within(page).getByTestId(`cand-link-${C2}`)).toBeInTheDocument();
    expect(within(page).queryByTestId(`cand-link-${C3}`)).toBeNull();
    fireEvent.click(within(page).getByTestId('filter-all'));
    await within(page).findByTestId(`cand-link-${C3}`, undefined, WAIT);
    expect(router.state.location.search).toBe('?status=all');
    expect(within(page).getByText(/研究候选不能直接生成计划草案/)).toBeInTheDocument();
  });
  it('手工新建：重复时提示并给出已有候选链接；换代码后创建并跳到详情', async () => {
    const router = renderAt('/candidates');
    fireEvent.click(await screen.findByTestId('cand-new-btn', undefined, WAIT));
    const modal = await screen.findByTestId('cand-create-modal');
    fireEvent.change(within(modal).getByTestId('cand-code'), { target: { value: '600000.sh' } });
    fireEvent.click(screen.getByTestId('cand-create-ok'));
    const conflict = await screen.findByTestId('cand-conflict', undefined, WAIT);
    expect(within(conflict).getByTestId('cand-existing-link')).toHaveAttribute('href', `/candidates/${C1}`);
    fireEvent.change(within(modal).getByTestId('cand-code'), { target: { value: '000002.SZ' } });
    fireEvent.click(within(modal).getByTestId('cond-add'));
    fireEvent.change(await within(modal).findByTestId('cond-text-0'), { target: { value: '示例条件' } });
    fireEvent.click(screen.getByTestId('cand-create-ok'));
    // 条件既无验证日期也无验证方式：前端先拦下
    expect(await screen.findByText(/验证日期与验证方式至少填一项|至少填一项/, undefined, WAIT)).toBeInTheDocument();
    fireEvent.change(within(modal).getByTestId('cond-method-0'), { target: { value: '示例方式' } });
    fireEvent.click(screen.getByTestId('cand-create-ok'));
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/candidates\/c0a1e000-/), WAIT);
    const detail = await screen.findByTestId('candidate-detail', undefined, WAIT);
    expect(await within(detail).findByTestId('cand-current-version-cond-0', undefined, WAIT)).toHaveTextContent('示例条件');
    expect(within(detail).getByTestId('cand-detail-status')).toHaveTextContent('研究中');
  });
});

describe('页面：研究候选详情', () => {
  it('当前版本、版本历史与回看；系统未列反证时显示提示', async () => {
    renderAt(`/candidates/${C1}`);
    const d = await screen.findByTestId('candidate-detail', undefined, WAIT);
    await within(d).findByTestId('cand-current-version', undefined, WAIT);
    expect(within(d).getByTestId('cand-current-version-decision')).toHaveTextContent('转为观察');
    expect(within(d).getByTestId('cand-current-version-cond-1')).toHaveTextContent('假设');
    expect(within(d).getByTestId('cand-source-suggestion')).toHaveAttribute('href', `/suggestions/${uid(100)}`);
    await within(d).findByTestId('cand-history-2', undefined, WAIT);
    fireEvent.click(within(d).getByTestId('cand-view-1'));
    const v1 = await screen.findByTestId('cand-view-version', undefined, WAIT);
    expect(within(v1).queryByTestId('cand-view-version-decision')).toBeNull();
    expect(within(v1).queryByTestId('cand-view-version-cond-1')).toBeNull();
  });
  it('做决定须填理由；放弃后只读', async () => {
    renderAt(`/candidates/${C2}`);
    fireEvent.click(await screen.findByTestId('cand-new-version-btn', undefined, WAIT));
    const form = await screen.findByTestId('cand-version-form');
    fireEvent.click(within(form).getByRole('radio', { name: '放弃' }));
    expect(await within(form).findByTestId('ver-drop-warn')).toBeInTheDocument();
    fireEvent.click(within(form).getByTestId('ver-submit'));
    expect(await within(form).findByText('做决定时须填写理由', undefined, WAIT)).toBeInTheDocument();
    fireEvent.change(within(form).getByTestId('ver-reason'), { target: { value: '示例理由' } });
    fireEvent.click(within(form).getByTestId('ver-submit'));
    expect(await screen.findByTestId('cand-dropped', undefined, WAIT)).toBeInTheDocument();
    expect(screen.getByTestId('cand-detail-status')).toHaveTextContent('已放弃');
    expect(screen.queryByTestId('cand-new-version-btn')).toBeNull();
    expect(candidatesNow()[1].versions).toHaveLength(2);
  });
  it('他人已先存了新版本：409 VERSION_CONFLICT 提示并可载入最新版本', async () => {
    renderAt(`/candidates/${C2}`);
    fireEvent.click(await screen.findByTestId('cand-new-version-btn', undefined, WAIT));
    const form = await screen.findByTestId('cand-version-form');
    expect((await post(`/candidates/${C2}/versions`, version(1, { thesis: '另一处保存（示例）' }))).status).toBe(201);
    fireEvent.change(within(form).getByTestId('ver-thesis'), { target: { value: '示例' } });
    fireEvent.click(within(form).getByTestId('ver-submit'));
    const c = await screen.findByTestId('cand-version-conflict', undefined, WAIT);
    fireEvent.click(within(c).getByTestId('cand-reload'));
    expect(await screen.findByTestId('cand-current-version-thesis', undefined, WAIT)).toHaveTextContent('另一处保存（示例）');
  });
  it('不存在或他人的候选：显示不存在', async () => {
    renderAt(`/candidates/${C4}`);
    expect(await screen.findByTestId('cand-not-found', undefined, WAIT)).toBeInTheDocument();
  });
});

describe('入口：个股页、候选信号卡详情', () => {
  it('个股页：已有观察中的候选只给链接', async () => {
    renderAt('/stocks/600000.SH');
    const box = await screen.findByTestId('add-to-research', undefined, WAIT);
    await within(box).findByTestId(`research-link-${C1}`, undefined, WAIT);
    expect(within(box).queryByTestId('add-to-research-btn')).toBeNull();
  });
  it('个股页：ETF 不能加入', async () => {
    renderAt('/stocks/510300.SH');
    const btn = await screen.findByTestId('add-to-research-btn', undefined, WAIT);
    expect(btn).toBeDisabled();
  });
  it('候选信号卡详情：用 suggestion 来源新建并跳到详情', async () => {
    const router = renderAt(`/suggestions/${SG_000001}`);
    const btn = await screen.findByTestId('add-to-research-btn', undefined, WAIT);
    await waitFor(() => expect(btn).not.toBeDisabled(), WAIT);
    fireEvent.click(btn);
    await screen.findByTestId('cand-create-modal');
    fireEvent.click(screen.getByTestId('cand-create-ok'));
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/candidates\//), WAIT);
    const created = candidatesNow().at(-1)!;
    expect(created.head).toMatchObject({ origin: 'suggestion', suggestion_id: SG_000001, security_code: '000001.SZ' });
  });
});
