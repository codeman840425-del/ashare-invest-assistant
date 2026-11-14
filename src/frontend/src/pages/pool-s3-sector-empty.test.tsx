import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { MemoryRouter } from 'react-router';
import type { SectorFlowsResponse } from '../api/marketTypes';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { MARKET_OVERVIEW } from '../mocks/marketFixtures';
import { server } from '../mocks/server';
import { MarketPage } from './market/MarketPage';

it.each([null, '2026-11-12'])('板块空态保留真实日期%s，不把null显示成日期或默认交易日', async (tradeDate) => {
  // Chief 6851075568空态裁定的合成响应；不请求真实板块数据。
  const sector: SectorFlowsResponse = {
    kind: 'industry', taxonomy: null, trade_date: tradeDate, items: [], sources: [],
    data_status: 'unavailable', data_as_of: null,
    gaps: [{ key: 'sector_flows', reason: 'no_source', message: '合成板块数据源未接入' }],
  };
  server.use(
    http.get('/api/v1/market/overview', () => HttpResponse.json({ ...MARKET_OVERVIEW, indices: [] })),
    http.get('/api/v1/market/sector-flows', () => HttpResponse.json(sector)),
  );
  render(<AppProviders client={makeQueryClient(true)}><MemoryRouter><MarketPage /></MemoryRouter></AppProviders>);
  const meta = await screen.findByTestId('sector-meta');
  const note = await screen.findByTestId('sector-gap-note');
  expect(note).toHaveTextContent('合成板块数据源未接入');
  expect(meta).toHaveTextContent(tradeDate ?? '交易日期暂不可用');
  expect(meta).not.toHaveTextContent('null');
  expect(await screen.findByText('暂无板块资金：无数据源')).toBeInTheDocument();
});
