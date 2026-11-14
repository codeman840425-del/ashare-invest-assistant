import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { http, HttpResponse } from 'msw';
import type { Bar, BarsResponse } from '../api/types';
import { mk, consistentPages } from '../api/marketQueries';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { server } from '../mocks/server';
import { PriceChartPanel } from './stock/PriceChartPanel';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: ({ bars }: { bars: Bar[] }) => <div data-testid="rendered-bars">{bars.map((bar) => `${bar.t}:${bar.close}`).join('|')}</div> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div /> }));
const code = '000001.SZ'; // 合成证券；此文件不请求真实数据。
const bar = (t: string, close: string): Bar => ({ t, open: close, high: close, low: close, close, pre_close: null, volume: '100', amount: '1000', avg_price: null, is_final: true });
function response(adjust: 'qfq' | 'none', items: Bar[], extra: Partial<BarsResponse> = {}): BarsResponse {
  return { security_code: code, name: '合成证券', freq: 'd', adjust, pre_close: null, items, next_before: null,
    adjust_as_of: adjust === 'qfq' ? '2026-11-12' : null, data_status: 'fresh', data_as_of: '2026-11-12T18:00:00+08:00', gaps: [], ...extra };
}
const unavailable = () => response('qfq', [], { data_status: 'unavailable', data_as_of: null, adjust_as_of: null, gaps: [{ key: 'bars', reason: 'no_source', message: '合成无来源' }] });
function openPage() {
  const client = makeQueryClient(true);
  render(<AppProviders client={client}><MemoryRouter><PriceChartPanel code={code} /></MemoryRouter></AppProviders>);
  return client;
}

it('无qfq时读取none并明确标注；更早页沿none游标，两个缓存各保原响应', async () => {
  const calls: string[] = [];
  server.use(http.get('/api/v1/securities/:code/bars', ({ request }) => {
    const params = new URL(request.url).searchParams;
    const adjust = params.get('adjust');
    const before = params.get('before');
    calls.push(`${adjust}:${before ?? 'latest'}`);
    return HttpResponse.json(adjust === 'qfq' ? unavailable() : before
      ? response('none', [bar('2026-11-11', '9')])
      : response('none', [bar('2026-11-12', '10')], { next_before: '2026-11-12' }));
  }));
  const client = openPage();
  expect(await screen.findByText('不复权（前复权数据不可用，已回落）')).toBeInTheDocument();
  expect(screen.getByTestId('rendered-bars')).toHaveTextContent('2026-11-12:10');
  await userEvent.click(screen.getByRole('button', { name: '加载更早的 K 线' }));
  await waitFor(() => expect(screen.getByTestId('rendered-bars')).toHaveTextContent('2026-11-11:9|2026-11-12:10'));
  expect(calls).toEqual(['qfq:latest', 'none:latest', 'none:2026-11-12']);
  const qfq = client.getQueryData<{ pages: BarsResponse[] }>(mk.barsWindow(code, 'd', 'qfq', 250));
  const none = client.getQueryData<{ pages: BarsResponse[] }>(mk.barsWindow(code, 'd', 'none', 250));
  expect(qfq?.pages[0]).toEqual(unavailable());
  expect(none?.pages.every((page) => page.adjust === 'none')).toBe(true);
});

it('none也因数据许可不可用时，保留真实空态与原因，不制造K线', async () => {
  const none = response('none', [], { data_status: 'unavailable', data_as_of: null,
    gaps: [{ key: 'bars', reason: 'data_licence_unavailable', message: '合成许可不可用' }] });
  server.use(http.get('/api/v1/securities/:code/bars', ({ request }) => HttpResponse.json(
    new URL(request.url).searchParams.get('adjust') === 'qfq' ? unavailable() : none,
  )));
  const client = openPage();
  expect(await screen.findByText('不复权（前复权数据不可用，已回落）')).toBeInTheDocument();
  expect(screen.getByTestId('chart-gap-note')).toHaveTextContent('合成许可不可用');
  expect(screen.getByTestId('rendered-bars')).toBeEmptyDOMElement();
  expect(client.getQueryData<{ pages: BarsResponse[] }>(mk.barsWindow(code, 'd', 'none', 250))?.pages[0]).toEqual(none);
});

it('qfq有数据时继续使用qfq，不请求none', async () => {
  const calls: string[] = [];
  server.use(http.get('/api/v1/securities/:code/bars', ({ request }) => {
    calls.push(new URL(request.url).searchParams.get('adjust')!);
    return HttpResponse.json(response('qfq', [bar('2026-11-12', '8')]));
  }));
  openPage();
  expect(await screen.findByTestId('rendered-bars')).toHaveTextContent('2026-11-12:8');
  expect(screen.getByTestId('chart-adjust-label')).toHaveTextContent('前复权');
  expect(calls).toEqual(['qfq']);
});

it.each(['fresh', 'pending'] as const)('qfq为%s空响应时不把正常空窗/准备中误判成无来源', async (status) => {
  const calls: string[] = [];
  server.use(http.get('/api/v1/securities/:code/bars', ({ request }) => {
    calls.push(new URL(request.url).searchParams.get('adjust')!);
    return HttpResponse.json(response('qfq', [], { data_status: status }));
  }));
  openPage();
  if (status === 'pending') await screen.findByText('数据准备中，请稍后刷新');
  else await screen.findByTestId('rendered-bars');
  expect(calls).toEqual(['qfq']);
});

it.each(['qfq', 'none'])('%s真实404类错误不吞为回落成功或空数据', async (failedAdjust) => {
  const calls: string[] = [];
  server.use(http.get('/api/v1/securities/:code/bars', ({ request }) => {
    const adjust = new URL(request.url).searchParams.get('adjust')!;
    calls.push(adjust);
    return adjust === failedAdjust ? HttpResponse.json({ error: { code: 'NOT_FOUND', message: '合成404', details: null, request_id: 'synthetic' } }, { status: 404 }) : HttpResponse.json(unavailable());
  }));
  openPage();
  expect(await screen.findByRole('alert')).toHaveAttribute('data-code', 'NOT_FOUND');
  expect(calls).toEqual(failedAdjust === 'qfq' ? ['qfq'] : ['qfq', 'none']);
});

it('即使基准日同为null，整窗也不拼接qfq与none', () => {
  const none = response('none', [bar('2026-11-12', '10')]);
  const qfq = response('qfq', [bar('2026-11-11', '8')], { adjust_as_of: null });
  expect(consistentPages([none, qfq])).toEqual([none]);
});
