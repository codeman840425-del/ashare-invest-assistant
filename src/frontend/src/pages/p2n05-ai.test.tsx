import type { ReactNode } from 'react';
import * as explanationLinks from '../lib/explanations';
import { ENUMS } from '../api/enums';
import { mockLoginAs } from '../mocks/session';
import { exampleFallbackExplanation, withExampleSuggestionExplanation } from '../mocks/explanationFixtures';
/** P2N-05i：DeepSeek先起草20条合成文字/六项用例标题；结构修正和全部断言由执行者复核。 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { qk } from '../api/queries';
import { apiGet, apiPost } from '../api/client';
import type { RefreshSuggestionResponse } from '../api/suggestionQueries';
import type { DailyReport, Suggestion } from '../api/types';
import { ExplanationView } from '../components/ExplanationView';
import { DISCLAIMER_TEXT } from '../components/RiskDisclosure';
import { EXAMPLE_EXPLANATIONS, exampleExplanation, exampleExplanationEvidence } from '../mocks/explanationFixtures';
import { REPORT_DATE, PREV_REPORT_DATE, suggestionOf } from '../mocks/fixtures';
import { server } from '../mocks/server';
import { preloadRoutes } from '../test/preloadRoutes';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div /> }));
beforeAll(() => preloadRoutes(routes), 30_000);
afterEach(() => vi.restoreAllMocks());
function renderExplanation(ui: ReactNode) {
  const client = makeQueryClient(true); return { ...render(<AppProviders client={client}>{ui}</AppProviders>), client };
}
function renderAt(path: string) {
  const client = makeQueryClient(true); const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={client}><ConfigProvider theme={{ token: { motion: false } }}><RouterProvider router={router} /></ConfigProvider></AppProviders>);
  return { client, router };
}
const evidence = exampleExplanationEvidence();
it.each(EXAMPLE_EXPLANATIONS)('$name：来源、版本、验证与旧版text投影不伪造', ({ mode, explanation }) => {
  renderExplanation(<ExplanationView explanation={explanation} evidence={evidence} testId="explanation" />);
  const view = screen.getByTestId('explanation'); expect(view).toHaveTextContent(explanation.text);
  if (mode.startsWith('legacy')) {
    expect(view).toHaveTextContent('验证状态未提供（旧版存档）'); expect(view).not.toHaveTextContent('验证通过'); expect(within(view).queryByRole('link')).not.toBeInTheDocument();
    expect(explanation).not.toHaveProperty('paragraphs'); expect(explanation).not.toHaveProperty('prompt_version'); expect(explanation).not.toHaveProperty('validation_status');
  } else {
    expect(explanation.text).toBe(explanation.paragraphs?.map((p) => p.text).join('\n'));
    expect(view).toHaveTextContent(mode === 'success' ? '验证通过' : '模板兜底');
    expect(view).toHaveTextContent(`提示词版本：${mode === 'disabled' ? '未提供' : 'TEST-PROMPT-V1'}`);
    expect(within(view).getByRole('link')).toHaveAttribute('href', expect.stringContaining('#'));
  }
  if (explanation.source === 'template') { expect(within(view).getByRole('heading')).toHaveTextContent('模板解释（非 AI 生成）'); expect(within(view).getByRole('heading')).not.toHaveTextContent('AI 中文解释'); }
});
it('引用点击打开并定位本对象证据；多处同id不产生重复锚点', () => {
  renderExplanation(<><ExplanationView explanation={exampleExplanation('success')} evidence={evidence} testId="first" /><ExplanationView explanation={exampleExplanation('success')} evidence={evidence} testId="second" /></>);
  const first = screen.getByTestId('first'); const second = screen.getByTestId('second'); const link = within(first).getByRole('link');
  expect(link.getAttribute('href')).not.toBe(within(second).getByRole('link').getAttribute('href')); expect(first.querySelector('details')).not.toHaveAttribute('open');
  fireEvent.click(link); expect(first.querySelector('details')).toHaveAttribute('open');
  const target = document.getElementById(link.getAttribute('href')!.slice(1)); expect(target).toHaveFocus(); expect(target).toHaveTextContent('TEST.EXAMPLE_FACT'); expect(target).toHaveTextContent('来源：'); expect(target).toHaveTextContent('数据时间：');
});
it('无引用/悬空引用不向其他对象借证据，null不填0', () => {
  const explanation = exampleExplanation('success', 'EXAMPLE_GAP');
  explanation.paragraphs?.[0].evidence_ids.push('EXAMPLE_OTHER_OBJECT');
  renderExplanation(<ExplanationView explanation={explanation} evidence={evidence} testId="explanation" />);
  const view = screen.getByTestId('explanation'); expect(view).toHaveTextContent('引用缺失：EXAMPLE_OTHER_OBJECT（本对象无此证据）');
  expect(within(view).queryByRole('link', { name: /EXAMPLE_OTHER_OBJECT/ })).not.toBeInTheDocument();
  fireEvent.click(within(view).getByRole('link')); expect(screen.getByTestId('explanation-evidence-EXAMPLE_GAP')).toHaveTextContent('—（缺数据）');
});
it('模型正文、版本与证据字符串按纯文本展示，不产生HTML节点', () => {
  const text = '<img src=x onerror="void(0)"><script>void(0)</script>示例数据';
  const explanation = exampleExplanation('success'); explanation.text = text; explanation.paragraphs = [{ text, expr: null, evidence_ids: [] }]; explanation.prompt_version = '<b>TEST-PROMPT</b>';
  renderExplanation(<ExplanationView explanation={explanation} evidence={[]} testId="explanation" />);
  const view = screen.getByTestId('explanation'); expect(view).toHaveTextContent(text); expect(view).toHaveTextContent('<b>TEST-PROMPT</b>'); expect(view.querySelector('img, script, b')).toBeNull();
});
it('来源/验证状态不一致不伪装为已验证AI或模板', () => {
  const explanation = exampleExplanation('success'); explanation.validation_status = 'fallback';
  renderExplanation(<ExplanationView explanation={explanation} evidence={evidence} testId="explanation" />);
  const view = screen.getByTestId('explanation'); expect(view).toHaveTextContent('来源与验证状态不一致，未确认有效'); expect(within(view).getByRole('heading')).not.toHaveTextContent('AI 中文解释');
});
it('建议与分歧解释从AI切模板，action/score/confidence逐字段及独立规则UI均不变，免责逐字', async () => {
  const body = structuredClone(suggestionOf('600000.SH')!); body.explanation = exampleExplanation('success'); body.evidence.push(...evidence);
  body.divergence = [{ dimensions: ['technical', 'capital'], summary: '示例数据：不同规则方向并列保留。', resolving_info: [], explanation: exampleExplanation('success', 'EXAMPLE_DIVERGENCE') }];
  const ruleFields = (sg: Suggestion) => sg.strategies.map((s) => ({ action: s.action, score: s.score, confidence: s.confidence })); const original = structuredClone(ruleFields(body));
  server.use(http.get('*/api/v1/suggestions/:id', () => HttpResponse.json(body)));
  const { client } = renderAt(`/suggestions/${body.id}`); const view = await screen.findByTestId('sg-explanation');
  expect(view).toHaveTextContent('验证通过'); await screen.findAllByTestId('strategy-card');
  const snapshot = () => screen.getAllByTestId('strategy-card').map((card) => ({ action: card.querySelector('.action-badge')?.textContent, score: card.querySelector('.sc-metrics b')?.textContent, confidence: card.querySelector('.conf-tag .num')?.textContent }));
  const before = snapshot(); expect(before).toHaveLength(body.strategies.length);
  body.strategies.forEach((s, index) => { expect(before[index].score).toBe(String(s.score)); expect(before[index].confidence).toBe(s.confidence.value.toFixed(2)); });
  expect(view.querySelector('.action-badge, .sc-metrics')).toBeNull();
  const divergence = screen.getByTestId('divergence-explanation-0'); fireEvent.click(within(divergence).getByText('本项分歧解释', { selector: 'summary' })); expect(divergence).toHaveTextContent(body.divergence[0].explanation!.text);
  act(() => client.setQueryData(qk.suggestion(body.id), { ...body, explanation: exampleExplanation('failure') }));
  await waitFor(() => expect(screen.getByTestId('sg-explanation')).toHaveTextContent('模板兜底')); expect(snapshot()).toEqual(before); expect(ruleFields(client.getQueryData<Suggestion>(qk.suggestion(body.id))!)).toEqual(original); expect(ruleFields(body)).toEqual(original);
  expect(screen.getByTestId('card-disclaimer').textContent).toBe(DISCLAIMER_TEXT);
});
it('日报逐股使用本项解释；引用不触发卡片导航，旧日报不借顶层text回填', async () => {
  const report = await apiGet<DailyReport>(`/daily-reports/${REPORT_DATE}`); expect(report.explanation.validation_status).toBe('fallback');
  expect(report.stocks[0].explanation).not.toBeNull(); expect(report.stocks[2].explanation).toBeNull(); expect(report.stocks[3]).not.toHaveProperty('explanation');
  const { router } = renderAt(`/daily-reports/${REPORT_DATE}`); await screen.findByTestId('report-explanation');
  const stock = screen.getByTestId(`stock-explanation-${report.stocks[0].security_code}`); fireEvent.click(within(stock).getByText('本股解释', { selector: 'summary' }));
  expect(stock).toHaveTextContent(report.stocks[0].explanation!.text); expect(stock).not.toHaveTextContent(report.explanation.text); expect(stock).toHaveTextContent('TEST-PROMPT-V1'); expect(stock).toHaveTextContent('验证通过');
  const rules = screen.getByTestId(`stc-${report.stocks[0].security_code}`).querySelector('.badges')?.textContent;
  fireEvent.click(within(stock).getByRole('link', { name: `查看解释证据 ${report.stocks[0].security_code}:EXPLANATION` })); expect(router.state.location.pathname).toBe(`/daily-reports/${REPORT_DATE}`); expect(screen.getByTestId(`stc-${report.stocks[0].security_code}`).querySelector('.badges')?.textContent).toBe(rules);
  expect(screen.getByTestId('card-disclaimer').textContent).toBe(DISCLAIMER_TEXT);
  await act(async () => { await router.navigate(`/daily-reports/${PREV_REPORT_DATE}`); });
  await waitFor(() => expect(screen.getByTestId('report-explanation')).toHaveTextContent('验证状态未提供（旧版存档）')); expect(screen.getByTestId('report-explanation')).not.toHaveTextContent('验证通过');
});
it('MSW新记录段落合成text且引用只在本响应，未改变规则字段；旧档没有补造新增键', async () => {
  const original = suggestionOf('600000.SH')!; const sg = await apiGet<Suggestion>(`/suggestions/${original.id}`); const report = await apiGet<DailyReport>(`/daily-reports/${REPORT_DATE}`);
  for (const object of [sg, report]) { expect(object.explanation.text).toBe(object.explanation.paragraphs?.map((p) => p.text).join('\n')); for (const p of object.explanation.paragraphs ?? []) for (const id of p.evidence_ids) expect(object.evidence.some((e) => e.id === id)).toBe(true); }
  expect(sg.strategies.map((s) => [s.action, s.score, s.confidence])).toEqual(original.strategies.map((s) => [s.action, s.score, s.confidence]));
  const legacy = await apiGet<DailyReport>(`/daily-reports/${PREV_REPORT_DATE}`); expect(legacy.explanation).not.toHaveProperty('paragraphs'); expect(legacy.explanation).not.toHaveProperty('validation_status'); expect(legacy.explanation).not.toHaveProperty('fallback_reason');
});

it('多段正文逐段展示、保留换行及各自引用，不用旧text替换新段落', () => {
  const explanation = exampleExplanation('success');
  explanation.paragraphs = [
    { text: '示例数据：第一段\n保留换行。', expr: null, evidence_ids: ['EXAMPLE_FACT', 'EXAMPLE_FACT'] },
    { text: '示例数据：第二段保留缺口。', expr: null, evidence_ids: ['EXAMPLE_GAP'] },
  ];
  explanation.text = '示例数据：旧text不应替换新增段落。';
  renderExplanation(<ExplanationView explanation={explanation} evidence={evidence} testId="explanation" />);
  const view = screen.getByTestId('explanation'); expect(view).toHaveTextContent('第一段'); expect(view).toHaveTextContent('第二段'); expect(view).not.toHaveTextContent('旧text不应替换');
  expect(within(view).getAllByRole('link')).toHaveLength(2); expect(within(view).getByText(/第一段/)).toHaveStyle({ whiteSpace: 'pre-wrap' });
});
it('空paragraphs仍保留存档text和模板标签，不伪造证据或提示词版本', () => {
  const explanation = exampleExplanation('disabled'); explanation.paragraphs = [];
  renderExplanation(<ExplanationView explanation={explanation} evidence={evidence} testId="explanation" />);
  const view = screen.getByTestId('explanation'); expect(view).toHaveTextContent(explanation.text); expect(view).toHaveTextContent('模板兜底'); expect(view).toHaveTextContent('提示词版本：未提供'); expect(within(view).queryByRole('link')).toBeNull();
});

// T-A36 + T-A37 I1–I3：读取独立字段，原因不猜测，当前用户角色统一门控。
it.each(ENUMS.explanation_fallback_reason)('回退原因%s按五值映射，不从调用id/版本猜测', (reason) => {
  const explanation = exampleFallbackExplanation(reason);
  renderExplanation(<ExplanationView explanation={explanation} evidence={evidence} testId="reason" />);
  expect(screen.getByTestId('reason-fallback')).toHaveTextContent(explanationLinks.EXPLANATION_FALLBACK_TEXT[reason]);
  expect(explanation.llm_call_id === null).toBe(reason === 'not_enabled' || reason === 'budget_exceeded');
});
it('未知回退枚举原样显示；passed/null不显示原因；旧模板缺键只显示模板兜底', async () => {
  const unknown = { ...exampleFallbackExplanation('timeout'), fallback_reason: 'future_reason' };
  const client = makeQueryClient(true); client.setQueryData(qk.me, { role: 'user' });
  render(<AppProviders client={client}><ExplanationView explanation={exampleExplanation('success')} evidence={evidence} testId="passed" /><ExplanationView explanation={exampleExplanation('legacy_template')} evidence={[]} testId="legacy" /></AppProviders>);
  expect(screen.queryByTestId('passed-fallback')).toBeNull(); expect(screen.getByTestId('legacy-fallback').textContent).toBe('模板兜底');
  expect(explanationLinks.explanationFallbackText(unknown.fallback_reason)).toBe('future_reason');
  const body = { ...suggestionOf('600000.SH')!, explanation: unknown };
  server.use(http.get('*/api/v1/suggestions/:id', () => HttpResponse.json(body)));
  const router = createMemoryRouter(routes, { initialEntries: [`/suggestions/${body.id}`] }); render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  expect(await screen.findByTestId('sg-explanation-fallback')).toHaveTextContent('future_reason');
});
it.each(['demo_user', 'admin'])('角色%s：建议整体/两项分歧/日报整体/两股调用id统一门控，正文引用互不串用', async (username) => {
  mockLoginAs(username);
  const base = structuredClone(suggestionOf('600000.SH')!);
  base.divergence = [
    { dimensions: ['technical'], summary: '示例数据：技术分歧', resolving_info: [] },
    { dimensions: ['capital'], summary: '示例数据：资金分歧', resolving_info: [] },
    { dimensions: ['news'], summary: '示例数据：本项无解释', resolving_info: [] },
    { dimensions: ['fundamental'], summary: '示例数据：旧项缺键', resolving_info: [] },
  ];
  const sg = withExampleSuggestionExplanation(base, 0); delete sg.divergence[3].explanation;
  expect(sg.divergence[0].explanation).not.toBeNull(); expect(sg.divergence[1].explanation).not.toBeNull();
  const ids = [0, 1, 2, 3, 4, 5].map((n) => `TEST-CALL-${username}-${n}`);
  sg.explanation.llm_call_id = ids[0]; sg.divergence[0].explanation!.llm_call_id = ids[1]; sg.divergence[1].explanation!.llm_call_id = ids[2];
  const report = await apiGet<DailyReport>(`/daily-reports/${REPORT_DATE}`); report.explanation.llm_call_id = ids[3]; report.stocks[0].explanation!.llm_call_id = ids[4]; report.stocks[1].explanation!.llm_call_id = ids[5];
  server.use(http.get('*/api/v1/suggestions/:id', () => HttpResponse.json(sg)), http.get('*/api/v1/daily-reports/:date', () => HttpResponse.json(report)));
  const { router } = renderAt(`/suggestions/${sg.id}`); await screen.findByTestId('sg-explanation');
  for (const i of [0, 1]) {
    const item = screen.getByTestId(`divergence-explanation-${i}`); fireEvent.click(within(item).getByText('本项分歧解释', { selector: 'summary' }));
    expect(item).toHaveTextContent(sg.divergence[i].explanation!.text); expect(item).not.toHaveTextContent(sg.explanation.text); expect(item).not.toHaveTextContent(sg.divergence[1 - i].explanation!.text);
    expect(within(item).getAllByRole('link').every((a) => a.getAttribute('href')?.startsWith('#'))).toBe(true);
    expect(within(item).getByRole('link', { name: `查看解释证据 ${sg.divergence[i].explanation!.paragraphs![0].evidence_ids[0]}` })).toBeInTheDocument();
  }
  expect(screen.queryByTestId('divergence-explanation-2')).toBeNull(); expect(screen.queryByTestId('divergence-explanation-3')).toBeNull();
  if (username === 'admin') { await waitFor(() => expect(screen.getByTestId('sg-llm-call')).toHaveTextContent(ids[0])); for (const id of ids.slice(0, 3)) expect(document.body.textContent).toContain(id); expect(screen.queryByRole('link', { name: ids[0] })).toBeNull(); }
  else for (const id of ids) expect(document.body.textContent).not.toContain(id);
  await act(async () => { await router.navigate(`/daily-reports/${REPORT_DATE}`); }); await screen.findByTestId('report-explanation');
  for (const i of [0, 1]) {
    const stock = report.stocks[i]; const item = screen.getByTestId(`stock-explanation-${stock.security_code}`); fireEvent.click(within(item).getByText('本股解释', { selector: 'summary' }));
    expect(item).toHaveTextContent(stock.explanation!.text); expect(item).not.toHaveTextContent(report.explanation.text); expect(item).not.toHaveTextContent(report.stocks[1 - i].explanation!.text);
    const refs = within(item).getAllByRole('link'); expect(refs).toHaveLength(1); expect(refs[0]).toHaveAccessibleName(`查看解释证据 ${stock.security_code}:EXPLANATION`);
  }
  for (const i of [2, 3]) expect(screen.queryByTestId(`stock-explanation-${report.stocks[i].security_code}`)).toBeNull();
  if (username === 'admin') for (const id of ids.slice(3)) { expect(document.body.textContent).toContain(id); expect(screen.queryByRole('link', { name: id })).toBeNull(); }
  else for (const id of ids) expect(document.body.textContent).not.toContain(id);
});
it('角色加载中/读取失败均隐藏调用id；不以source或非空id猜管理员', async () => {
  server.use(http.get('*/api/v1/me', () => HttpResponse.json({ error: { code: 'EXAMPLE_UNAVAILABLE' } }, { status: 503 })));
  const explanation = exampleFallbackExplanation('validation_failed'); const { client } = renderExplanation(<ExplanationView explanation={explanation} evidence={evidence} testId="unknown-role" />);
  expect(document.body.textContent).not.toContain(explanation.llm_call_id!); await waitFor(() => expect(client.getQueryState(qk.me)?.status).toBe('error')); expect(document.body.textContent).not.toContain(explanation.llm_call_id!);
});
it('角色未知也不显示id；页面存在时管理员才有编码深链', async () => {
  expect(explanationLinks.hasAdminLlmUsagePage()).toBe(false);
  for (const role of [undefined, 'user'] as const) expect(explanationLinks.adminLlmUsageHref(role, 'TEST & ?', true)).toBeNull();
  expect(explanationLinks.adminLlmUsageHref('admin', 'TEST & ?', false)).toBeNull(); expect(explanationLinks.adminLlmUsageHref('admin', null, true)).toBeNull();
  mockLoginAs('admin'); vi.spyOn(explanationLinks, 'hasAdminLlmUsagePage').mockReturnValue(true);
  const explanation = exampleExplanation('success'); explanation.llm_call_id = 'TEST & ?'; renderExplanation(<ExplanationView explanation={explanation} evidence={evidence} testId="future-page" />);
  expect(await screen.findByRole('link', { name: 'TEST & ?' })).toHaveAttribute('href', '/admin/llm/usage?call_id=TEST%20%26%20%3F');
});
it('MSW本项解释只引证券前缀/关联维度，含null/缺键；新记录原因和调用记录符合T-A36', async () => {
  const sg = await apiGet<Suggestion>(`/suggestions/${suggestionOf('600000.SH')!.id}`); const report = await apiGet<DailyReport>(`/daily-reports/${REPORT_DATE}`);
  for (const stock of report.stocks) for (const paragraph of stock.explanation?.paragraphs ?? []) for (const id of paragraph.evidence_ids) expect(id.startsWith(stock.security_code + ':') && report.evidence.some((e) => e.id === id)).toBe(true);
  for (const d of sg.divergence) {
    const related = new Set(sg.strategies.flatMap((s) => s.dimension_views.filter((v) => d.dimensions.includes(v.dimension)).flatMap((v) => v.rules.flatMap((r) => r.evidence_ids))));
    for (const p of d.explanation?.paragraphs ?? []) for (const id of p.evidence_ids) expect(related.has(id) && sg.evidence.some((e) => e.id === id)).toBe(true);
  }
  for (const e of [sg.explanation, report.explanation, ...report.stocks.flatMap((s) => s.explanation ? [s.explanation] : [])]) {
    expect(e.text).toBe(e.paragraphs?.map((p) => p.text).join('\n')); if (e.validation_status === 'passed') expect(e.fallback_reason).toBeNull(); else expect(e.fallback_reason).toBeTruthy();
  }
  const legacy = await apiGet<DailyReport>(`/daily-reports/${PREV_REPORT_DATE}`); expect(legacy.stocks.every((s) => !Object.hasOwn(s, 'explanation'))).toBe(true);
});

it.each([{ name: '缺角色', body: { status: 'approved', username: 'example-unknown-role' } }, { name: '空用户', body: null }])('角色响应成功但$name时仍不渲染调用id', async ({ body }) => {
  server.use(http.get('*/api/v1/me', () => HttpResponse.json(body)));
  const explanation = exampleFallbackExplanation('timeout'); const { client } = renderExplanation(<ExplanationView explanation={explanation} evidence={evidence} testId="missing-role" />);
  await waitFor(() => expect(client.getQueryState(qk.me)?.status).toBe('success')); expect(document.body.textContent).not.toContain(explanation.llm_call_id!);
});
it('手动刷新新快照带not_enabled及空调用id，旧卡解释不被异步改写', async () => {
  const sg = await apiGet<Suggestion>(`/suggestions/${suggestionOf('600000.SH')!.id}`); const original = structuredClone(sg.explanation);
  const next = await apiPost<RefreshSuggestionResponse>('/suggestions/refresh', { security_code: sg.security_code });
  expect(next.suggestion?.explanation).toMatchObject({ source: 'template', validation_status: 'fallback', fallback_reason: 'not_enabled', llm_call_id: null });
  expect(next.suggestion?.explanation.text).toBe(next.suggestion?.explanation.paragraphs?.map((p) => p.text).join('\n'));
  const old = await apiGet<Suggestion>(`/suggestions/${sg.id}`); expect(old.explanation).toEqual(original);
});
