/** P2N-05i：DeepSeek先起草20条合成文字/六项用例标题；结构修正和全部断言由执行者复核。 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { qk } from '../api/queries';
import { apiGet } from '../api/client';
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
function renderAt(path: string) {
  const client = makeQueryClient(true); const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={client}><ConfigProvider theme={{ token: { motion: false } }}><RouterProvider router={router} /></ConfigProvider></AppProviders>);
  return { client, router };
}
const evidence = exampleExplanationEvidence();
it.each(EXAMPLE_EXPLANATIONS)('$name：来源、版本、验证与旧版text投影不伪造', ({ mode, explanation }) => {
  render(<ExplanationView explanation={explanation} evidence={evidence} testId="explanation" />);
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
  render(<><ExplanationView explanation={exampleExplanation('success')} evidence={evidence} testId="first" /><ExplanationView explanation={exampleExplanation('success')} evidence={evidence} testId="second" /></>);
  const first = screen.getByTestId('first'); const second = screen.getByTestId('second'); const link = within(first).getByRole('link');
  expect(link.getAttribute('href')).not.toBe(within(second).getByRole('link').getAttribute('href')); expect(first.querySelector('details')).not.toHaveAttribute('open');
  fireEvent.click(link); expect(first.querySelector('details')).toHaveAttribute('open');
  const target = document.getElementById(link.getAttribute('href')!.slice(1)); expect(target).toHaveFocus(); expect(target).toHaveTextContent('TEST.EXAMPLE_FACT'); expect(target).toHaveTextContent('来源：'); expect(target).toHaveTextContent('数据时间：');
});
it('无引用/悬空引用不向其他对象借证据，null不填0', () => {
  const explanation = exampleExplanation('success', 'EXAMPLE_GAP');
  explanation.paragraphs?.[0].evidence_ids.push('EXAMPLE_OTHER_OBJECT');
  render(<ExplanationView explanation={explanation} evidence={evidence} testId="explanation" />);
  const view = screen.getByTestId('explanation'); expect(view).toHaveTextContent('引用缺失：EXAMPLE_OTHER_OBJECT（本对象无此证据）');
  expect(within(view).queryByRole('link', { name: /EXAMPLE_OTHER_OBJECT/ })).not.toBeInTheDocument();
  fireEvent.click(within(view).getByRole('link')); expect(screen.getByTestId('explanation-evidence-EXAMPLE_GAP')).toHaveTextContent('—（缺数据）');
});
it('模型正文、版本与证据字符串按纯文本展示，不产生HTML节点', () => {
  const text = '<img src=x onerror="void(0)"><script>void(0)</script>示例数据';
  const explanation = exampleExplanation('success'); explanation.text = text; explanation.paragraphs = [{ text, expr: null, evidence_ids: [] }]; explanation.prompt_version = '<b>TEST-PROMPT</b>';
  render(<ExplanationView explanation={explanation} evidence={[]} testId="explanation" />);
  const view = screen.getByTestId('explanation'); expect(view).toHaveTextContent(text); expect(view).toHaveTextContent('<b>TEST-PROMPT</b>'); expect(view.querySelector('img, script, b')).toBeNull();
});
it('来源/验证状态不一致不伪装为已验证AI或模板', () => {
  const explanation = exampleExplanation('success'); explanation.validation_status = 'fallback';
  render(<ExplanationView explanation={explanation} evidence={evidence} testId="explanation" />);
  const view = screen.getByTestId('explanation'); expect(view).toHaveTextContent('来源与验证状态不一致，未确认有效'); expect(within(view).getByRole('heading')).not.toHaveTextContent('AI 中文解释');
});
it('建议与分歧解释从AI切模板，action/score/confidence逐字段及独立规则UI均不变，免责逐字', async () => {
  const body = structuredClone(suggestionOf('600000.SH')!); body.explanation = exampleExplanation('success'); body.evidence.push(...evidence);
  body.divergence = [{ dimensions: ['technical', 'capital'], summary: '示例数据：不同规则方向并列保留。', resolving_info: [] }];
  const ruleFields = (sg: Suggestion) => sg.strategies.map((s) => ({ action: s.action, score: s.score, confidence: s.confidence })); const original = structuredClone(ruleFields(body));
  server.use(http.get('*/api/v1/suggestions/:id', () => HttpResponse.json(body)));
  const { client } = renderAt(`/suggestions/${body.id}`); const view = await screen.findByTestId('sg-explanation');
  expect(view).toHaveTextContent('验证通过'); await screen.findAllByTestId('strategy-card');
  const snapshot = () => screen.getAllByTestId('strategy-card').map((card) => ({ action: card.querySelector('.action-badge')?.textContent, score: card.querySelector('.sc-metrics b')?.textContent, confidence: card.querySelector('.conf-tag .num')?.textContent }));
  const before = snapshot(); expect(before).toHaveLength(body.strategies.length);
  body.strategies.forEach((s, index) => { expect(before[index].score).toBe(String(s.score)); expect(before[index].confidence).toBe(s.confidence.value.toFixed(2)); });
  expect(view.querySelector('.action-badge, .sc-metrics')).toBeNull();
  const divergence = screen.getByTestId('divergence-explanation-0'); fireEvent.click(within(divergence).getByText('本卡整体解释（非该分歧专属）', { selector: 'summary' })); expect(divergence).toHaveTextContent(body.explanation.text);
  act(() => client.setQueryData(qk.suggestion(body.id), { ...body, explanation: exampleExplanation('failure') }));
  await waitFor(() => expect(screen.getByTestId('sg-explanation')).toHaveTextContent('模板兜底')); expect(snapshot()).toEqual(before); expect(ruleFields(client.getQueryData<Suggestion>(qk.suggestion(body.id))!)).toEqual(original); expect(ruleFields(body)).toEqual(original);
  expect(screen.getByTestId('card-disclaimer').textContent).toBe(DISCLAIMER_TEXT);
});
it('日报逐股整体解释明确非专属；引用不触发卡片导航，旧日报保留text与未知验证状态', async () => {
  const report = await apiGet<DailyReport>(`/daily-reports/${REPORT_DATE}`); expect(report.explanation.validation_status).toBe('fallback');
  expect(report.stocks.every((s) => !Object.hasOwn(s, 'explanation'))).toBe(true);
  const { router } = renderAt(`/daily-reports/${REPORT_DATE}`); await screen.findByTestId('report-explanation');
  const stock = screen.getByTestId(`stock-explanation-${report.stocks[0].security_code}`); fireEvent.click(within(stock).getByText('本期整体解释（非个股专属）', { selector: 'summary' }));
  expect(stock).toHaveTextContent(report.explanation.text); expect(stock).toHaveTextContent('TEST-PROMPT-V1'); expect(stock).toHaveTextContent('模板兜底');
  const rules = screen.getByTestId(`stc-${report.stocks[0].security_code}`).querySelector('.badges')?.textContent;
  fireEvent.click(within(stock).getByRole('link', { name: '查看解释证据 EXAMPLE_FACT' })); expect(router.state.location.pathname).toBe(`/daily-reports/${REPORT_DATE}`); expect(screen.getByTestId(`stc-${report.stocks[0].security_code}`).querySelector('.badges')?.textContent).toBe(rules);
  expect(screen.getByTestId('card-disclaimer').textContent).toBe(DISCLAIMER_TEXT);
  await act(async () => { await router.navigate(`/daily-reports/${PREV_REPORT_DATE}`); });
  await waitFor(() => expect(screen.getByTestId('report-explanation')).toHaveTextContent('验证状态未提供（旧版存档）')); expect(screen.getByTestId('report-explanation')).not.toHaveTextContent('验证通过');
});
it('MSW新记录段落合成text且引用只在本响应，未改变规则字段；旧档没有补造新增键', async () => {
  const original = suggestionOf('600000.SH')!; const sg = await apiGet<Suggestion>(`/suggestions/${original.id}`); const report = await apiGet<DailyReport>(`/daily-reports/${REPORT_DATE}`);
  for (const object of [sg, report]) { expect(object.explanation.text).toBe(object.explanation.paragraphs?.map((p) => p.text).join('\n')); for (const p of object.explanation.paragraphs ?? []) for (const id of p.evidence_ids) expect(object.evidence.some((e) => e.id === id)).toBe(true); }
  expect(sg.strategies.map((s) => [s.action, s.score, s.confidence])).toEqual(original.strategies.map((s) => [s.action, s.score, s.confidence]));
  const legacy = await apiGet<DailyReport>(`/daily-reports/${PREV_REPORT_DATE}`); expect(legacy.explanation).not.toHaveProperty('paragraphs'); expect(legacy.explanation).not.toHaveProperty('validation_status');
});

it('多段正文逐段展示、保留换行及各自引用，不用旧text替换新段落', () => {
  const explanation = exampleExplanation('success');
  explanation.paragraphs = [
    { text: '示例数据：第一段\n保留换行。', expr: null, evidence_ids: ['EXAMPLE_FACT', 'EXAMPLE_FACT'] },
    { text: '示例数据：第二段保留缺口。', expr: null, evidence_ids: ['EXAMPLE_GAP'] },
  ];
  explanation.text = '示例数据：旧text不应替换新增段落。';
  render(<ExplanationView explanation={explanation} evidence={evidence} testId="explanation" />);
  const view = screen.getByTestId('explanation'); expect(view).toHaveTextContent('第一段'); expect(view).toHaveTextContent('第二段'); expect(view).not.toHaveTextContent('旧text不应替换');
  expect(within(view).getAllByRole('link')).toHaveLength(2); expect(within(view).getByText(/第一段/)).toHaveStyle({ whiteSpace: 'pre-wrap' });
});
it('空paragraphs仍保留存档text和模板标签，不伪造证据或提示词版本', () => {
  const explanation = exampleExplanation('disabled'); explanation.paragraphs = [];
  render(<ExplanationView explanation={explanation} evidence={evidence} testId="explanation" />);
  const view = screen.getByTestId('explanation'); expect(view).toHaveTextContent(explanation.text); expect(view).toHaveTextContent('模板兜底'); expect(view).toHaveTextContent('提示词版本：未提供'); expect(within(view).queryByRole('link')).toBeNull();
});
