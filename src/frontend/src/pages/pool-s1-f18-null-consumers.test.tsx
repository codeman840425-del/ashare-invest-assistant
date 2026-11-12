import { render, screen, waitFor, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import type { BarsResponse, DataStatusBlock, Evidence, QuoteItem } from '../api/types';
import type { SecurityProfile } from '../api/marketTypes';
import type { StreamEventMap } from '../api/streamTypes';
import { fmtTime } from '../lib/format';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { preloadRoutes } from '../test/preloadRoutes';

// Only canvas renderers are replaced. Keep page, query and null consumers real.
vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div /> }));
vi.mock('../components/charts/IntradayChart', () => ({
  IntradayChart: ({ empty }: { empty: ReactNode }) => <div data-testid="s1-f18-minute-consumed">{empty}</div>,
}));
vi.mock('../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div /> }));
beforeAll(() => preloadRoutes(routes), 30_000);
beforeEach(() => mockLoginAs('demo_user'));
const code = '600000.SH';
const oldTime = '2026-10-23T14:28:00+08:00';
const oldText = '2026-10-23 14:28';
const gap = { key: 'f18', reason: 'no_source' as const, message: 'S1F18合成来源缺口' };

function renderAt(path: string) {
  const client = makeQueryClient(true);
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(<AppProviders client={client}><RouterProvider router={router} /></AppProviders>);
  return () => { view.unmount(); client.clear(); };
}

function profile(at: string | null): SecurityProfile {
  return {
    security_code: code, name: 'S1F18合成证券', type: 'stock', exchange: 'SH', board: 'main',
    list_date: null, list_date_basis: null, delist_date: null, listing_status: 'listed', risk_flag: null,
    former_names: [], code_history: [], master_as_of: '2026-11-02', attribution: 'S1F18独立公开来源',
    industry: null, concepts: [], total_shares: null, float_shares: null, suspended: null,
    sources: at ? [{ provider: 'exchange', endpoint: 'synthetic-public', fetched_at: at }] : [],
    data_status: 'partial', data_as_of: at, gaps: [gap],
  };
}

it('S1F18 preserves the required nullable public key and non-null Evidence/quote fields', () => {
  const block: DataStatusBlock = { data_status: 'unavailable', data_as_of: null, gaps: [] };
  // @ts-expect-error The key is required even when its value can be null.
  const missing: DataStatusBlock = { data_status: 'unavailable', gaps: [] };
  const evidence: Evidence = {
    id: 'f18', key: 'close', value: null, unit: null, provider: 'system', endpoint: null,
    data_as_of: oldTime, fetched_at: oldTime, epistemic_type: 'fact',
  };
  // @ts-expect-error Evidence.data_as_of is independently non-null.
  const badEvidence: Evidence = { ...evidence, data_as_of: null };
  // @ts-expect-error Evidence.fetched_at is independently non-null.
  const badFetched: Evidence = { ...evidence, fetched_at: null };
  // @ts-expect-error SSE quote's own timestamp remains non-null.
  const badQuote: StreamEventMap['quote'] = { items: [], data_as_of: null };
  expect([block.data_as_of, badEvidence.data_as_of, badFetched.fetched_at, badQuote.data_as_of]).toEqual([null, null, null, null]);
  expect(missing).not.toHaveProperty('data_as_of');
});

it('S1F18 formats null as empty and preserves an old trusted server timestamp exactly', () => {
  expect(fmtTime(null)).toBe('');
  expect(fmtTime(undefined)).toBe('');
  expect(fmtTime('')).toBe('');
  expect(fmtTime(oldTime)).toBe(oldText);
});

for (const at of [null, oldTime]) {
  it(`S1F18 market consumes ${at === null ? 'null without inventing a time' : 'the old server time'}`, async () => {
    server.use(http.get('/api/v1/market/overview', () => HttpResponse.json({
      trade_date: '2026-11-02', session: 'closed', indices: [], breadth: null, regime: null,
      regime_position_range: null, turnover_total: null, data_status: 'unavailable', data_as_of: at, gaps: [gap],
    })));
    const dispose = renderAt('/market');
    try {
      const page = await screen.findByTestId('market-page');
      expect(await within(page).findByText(at === null ? '数据不可用（无数据时点）' : `更新于 ${oldText}`)).toBeInTheDocument();
      expect(within(page).getByTestId('market-gap-note')).toHaveTextContent(gap.message);
      const head = page.querySelector('.mk-head')!;
      expect(head).toHaveTextContent('2026-11-02');
      if (at === null) expect(head).not.toHaveTextContent('更新于');
      expect(head.textContent).not.toMatch(/Invalid Date|NaN|undefined/);
    } finally { dispose(); }
  });

  it(`S1F18 profile consumes ${at === null ? 'explicit null' : 'the old public timestamp'}`, async () => {
    server.use(http.get(`/api/v1/securities/${code}`, () => HttpResponse.json(profile(at))));
    const dispose = renderAt(`/stocks/${code}`);
    try {
      const panel = await screen.findByTestId('profile-panel');
      expect(await within(panel).findByTestId('profile-attribution')).toHaveTextContent('S1F18独立公开来源（主数据截至 2026-11-02）');
      const tag = within(panel).getByTestId('data-status-tag');
      const description = document.getElementById(tag.getAttribute('aria-describedby')!)!;
      expect(description).toHaveTextContent(gap.message);
      if (at === null) expect(description).not.toHaveTextContent('数据时间');
      else expect(description).toHaveTextContent(`数据时间 ${oldText}`);
      expect(panel.textContent).not.toMatch(/Invalid Date|NaN|undefined/);
    } finally { dispose(); }
  });
}

const quote: QuoteItem = {
  security_code: code, name: 'S1F18合成证券', price: '10.24', change_pct: '2.20', volume: '1000', amount: '10240',
  t: '2026-11-02T10:31:00+08:00', data_status: 'fresh', data_as_of: '2026-11-02T10:31:00+08:00', gaps: [],
};
const minuteBase: BarsResponse = {
  security_code: code, name: 'S1F18合成证券', freq: '1m', adjust: 'none', pre_close: '10.02',
  items: [], next_before: null, adjust_as_of: null, data_status: 'unavailable', data_as_of: null, gaps: [gap],
};

for (const mode of ['null', 'fallback', 'item'] as const) {
  it(`S1F18 reaches both slice consumers with minute timestamp ${mode}`, async () => {
    const minute: BarsResponse = {
      ...minuteBase,
      data_as_of: mode === 'fallback' ? '2026-11-02T09:30:00+08:00' : null,
      items: mode === 'item' ? [{
        t: '2026-11-02T09:30:00+08:00', open: '10.05', high: '10.06', low: '10.04', close: '10.05',
        pre_close: null, volume: '1000', amount: '10050', avg_price: '10.05', is_final: true,
      }] : [],
    };
    server.use(
      http.get(`/api/v1/securities/${code}`, () => HttpResponse.json(profile(null))),
      http.get('/api/v1/quotes', () => HttpResponse.json({ items: [quote] })),
      http.get(`/api/v1/securities/${code}/bars`, ({ request }) => {
        if (new URL(request.url).searchParams.get('freq') === '1m') return HttpResponse.json(minute);
        // Daily data deliberately has no current-day bar/pre_close to short circuit the minute consumer.
        return HttpResponse.json({ ...minuteBase, freq: 'd', adjust: 'qfq', pre_close: null, data_as_of: oldTime, items: [] });
      }),
    );
    const dispose = renderAt(`/stocks/${code}`);
    try {
      // PriceChartPanel has consumed the exact minute response before rendering the canvas stub.
      expect(await screen.findByTestId('s1-f18-minute-consumed')).toHaveTextContent('无分时数据');
      const head = await screen.findByTestId('stock-head');
      // Quote presence and non-null minute.pre_close are necessary to reach StockPage's slice branch.
      await waitFor(() => expect(head).toHaveTextContent('10.24'));
      const previousClose = within(head).getByText('昨收').parentElement!;
      await waitFor(() => expect(previousClose).toHaveTextContent(mode === 'null' ? '昨收—' : '昨收10.02'));
      expect(head.textContent).not.toMatch(/Cannot read properties|TypeError|undefined|NaN/);
    } finally { dispose(); }
  });
}
