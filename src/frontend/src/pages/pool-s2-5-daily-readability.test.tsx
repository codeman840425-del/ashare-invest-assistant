import { render, screen, within } from '@testing-library/react';
import { createMemoryRouter } from 'react-router';
import { RouterProvider } from 'react-router/dom';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { DAILY_REPORTS, REPORT_DATE } from '../mocks/fixtures';
import { server } from '../mocks/server';
import { DailyReportPage } from './DailyReportPage';
import { fmtTime } from '../lib/format';

// Existing synthetic report only; no live account or external data.
function openReport() {
  const router = createMemoryRouter([
    { path: '/daily-reports/:date', element: <DailyReportPage /> },
  ], { initialEntries: [`/daily-reports/${REPORT_DATE}?filter=changed`] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

it('章节入口定位已渲染区域，快照日期、生成时间和来源时点分别保留', async () => {
  const router = openReport();
  const page = await screen.findByTestId('daily-report');
  expect(within(page).getByRole('heading', { level: 1, name: '盘后日报' })).toBeInTheDocument();
  const nav = within(page).getByRole('navigation', { name: '日报章节' });
  for (const link of within(nav).getAllByRole('link')) {
    const id = link.getAttribute('href')!.slice(1);
    expect(page.querySelector(`[id="${id}"]`)).toBeInTheDocument();
  }
  const info = within(page).getByLabelText('日报快照信息');
  expect(info).toHaveTextContent(REPORT_DATE);
  expect(within(info).getByText('生成于')).toBeInTheDocument();
  expect(within(info).getByText('数据截至')).toBeInTheDocument();
  expect(info).toHaveTextContent(fmtTime(DAILY_REPORTS[0].generated_at));
  expect(info).toHaveTextContent(DAILY_REPORTS[0].data_as_of === null ? '—（无来源）' : fmtTime(DAILY_REPORTS[0].data_as_of));
  expect(router.state.location.search).toBe('?filter=changed');
});

it('缺失来源、价格和涨跌幅分别显示缺数据，账户金额缺值不伪装为0', async () => {
  const report = structuredClone(DAILY_REPORTS[0]);
  report.data_as_of = null;
  report.stocks[0].close = null;
  report.stocks[0].change_pct = null;
  report.stocks[0].change_from_previous = 'changed';
  if (!report.account) throw new Error('Synthetic report must contain an account');
  report.account.position_pct = null;
  report.account.pnl_day = null;
  server.use(http.get('/api/v1/daily-reports/:date', () => HttpResponse.json(report)));
  openReport();
  const page = await screen.findByTestId('daily-report');
  expect(within(page).getByLabelText('日报快照信息')).toHaveTextContent('—（无来源）');
  const stock = within(page).getByTestId(`stc-${report.stocks[0].security_code}`);
  expect(within(stock).getByTestId('stc-close')).toHaveTextContent('收盘价 —（缺数据） · 涨跌幅 —（缺数据）');
  const account = within(page).getByTestId('report-account');
  expect(account).toHaveTextContent('—（缺少资产分母）');
  expect(account).toHaveTextContent('—（缺少计算基准）');
});

it('变化字段显示中文名称且保留要点、失效条件、次日关注和原证据入口', async () => {
  const report = structuredClone(DAILY_REPORTS[0]);
  const stock = report.stocks[0];
  stock.change_from_previous = 'changed';
  stock.change_fields = ['actions', 'confidence_level', 'executability', 'max_risk_level'];
  server.use(http.get('/api/v1/daily-reports/:date', () => HttpResponse.json(report)));
  openReport();
  const card = await screen.findByTestId(`stc-${stock.security_code}`);
  expect(card).toHaveTextContent('变化：策略动作、置信等级、可执行性、最高风险级别');
  for (const name of ['要点', '失效条件', '次日关注']) {
    expect(within(card).getByRole('heading', { name, level: 3 })).toBeInTheDocument();
  }
  for (const item of [...stock.highlights, ...stock.invalidation, ...stock.next_watch]) {
    expect(card).toHaveTextContent(item.text);
  }
  expect(within(card).getByTestId(`dimensions-${stock.security_code}`)).toHaveTextContent('六维事实与缺口');
});
