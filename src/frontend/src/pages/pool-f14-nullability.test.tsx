/**
 * F-14：A-12 终裁（#78 756b7b7）前端落地核验 + 两处 slice 崩溃回归。
 * 文件名 pool-f14-nullability 固定，不占用 main 既有测试号（t-f12/t-f13/t-f14 已从 main 逐字节恢复）。
 *
 * 类型负例：由 `tsc --noEmit -p tsconfig.test.json` 验证（app 配置排除测试文件，跑它不能消耗 @ts-expect-error）。
 * 负例必须直接对真实类型赋值字面 null；不得使用 `asNull(): T` / `never` 之类强转 helper（RV-11 P2-1）。
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import type { BarsResponse, DataStatusBlock, Evidence, QuoteItem } from '../api/types';
import type { FactorsResponse } from '../api/marketTypes';
import type { StreamEventMap } from '../api/streamTypes';
import { fmtTime } from '../lib/format';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { preloadRoutes } from '../test/preloadRoutes';

// 分时图桩：把 empty 文本透传出来（真实组件在 bars 为空时渲染同样的文本）
vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({
  IntradayChart: ({ empty }: { empty: React.ReactNode }) => <div data-testid="chart-empty">{empty}</div>,
}));
vi.mock('../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div data-testid="fund-flow-chart" /> }));

beforeAll(() => preloadRoutes(routes), 30_000);
const API = '/api/v1';
const expectNoBadTime = (root: HTMLElement) => {
  expect(root.textContent).not.toMatch(/Invalid Date|NaN|undefined/);
};

function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

describe('① 类型负例：Evidence / SSE quote 拒绝 null，DataStatusBlock 允许 null 但不得缺键', () => {
  it('Evidence 两个时点、SSE quote.data_as_of 直接赋 null 均被拒绝', () => {
    // @ts-expect-error Evidence.data_as_of 必填非空（A-12 不放宽）
    const badAsof: Evidence = { id: 'E1', key: 'close', value: '10', unit: null, provider: 'system', endpoint: null, data_as_of: null, fetched_at: '2026-11-02T15:01:00+08:00', epistemic_type: 'fact' };
    // @ts-expect-error Evidence.fetched_at 必填非空
    const badFetch: Evidence = { id: 'E2', key: 'close', value: '10', unit: null, provider: 'system', endpoint: null, data_as_of: '2026-11-02T15:00:00+08:00', fetched_at: null, epistemic_type: 'fact' };
    // @ts-expect-error 契约 §8：quote 直接是 payload，其 data_as_of 必填非空
    const badQuote: StreamEventMap['quote'] = { items: [], data_as_of: null };
    // @ts-expect-error DataStatusBlock 的键必须出现（只允许值为 null，不允许缺键）
    const missingKey: DataStatusBlock = { data_status: 'unavailable', gaps: [] };

    // 正例：DataStatusBlock 允许 null；SSE quote 至少一条有可信时点的行情项
    const okBlock: DataStatusBlock = { data_status: 'unavailable', data_as_of: null, gaps: [] };
    const okQuote: StreamEventMap['quote'] = {
      data_as_of: '2026-11-02T10:31:00+08:00',
      items: [{ security_code: '600000.SH', name: '示例银行', price: '10.24', change_pct: '2.20', amount: '420000000.00', t: '2026-11-02T10:31:00+08:00' }],
    };
    expect([badAsof.data_as_of, badFetch.fetched_at, badQuote.data_as_of, okBlock.data_as_of, missingKey]).toEqual([null, null, null, null, { data_status: 'unavailable', gaps: [] }]);
    expect(okQuote.items.length).toBeGreaterThan(0);
  });
});

describe('② fmtTime 底层空时点防护（自 t-f13 迁入的独立回归）', () => {
  it('fmtTime(null/undefined/空串) 返回空串，不抛错、不产出编造时间', () => {
    expect(fmtTime(null)).toBe('');
    expect(fmtTime(undefined)).toBe('');
    expect(fmtTime('')).toBe('');
    expect(fmtTime('2026-11-02T10:31:00+08:00')).not.toBe('');
  });
});

describe('② mock 空态时点口径（A-12：全空即 null，有真实批次保留旧时点）', { timeout: 20_000 }, () => {
  beforeEach(() => mockLoginAs('demo_user'));
  const getFactors = async (path: string) => (await (await fetch(`${API}${path}`)).json()) as FactorsResponse;

  it('指数全空：items=[] 且 data_as_of=null（不再写固定旧时点）', async () => {
    const f = await getFactors('/securities/000300.SH/factors');
    expect(f.items).toEqual([]);
    expect(f.data_as_of).toBeNull();
    expect(f.trade_date).toBeNull();
    expect(f.factor_set_version).toBeNull();
  });

  it('ETF 全空：data_as_of=null（不沿用 etfNotApplicable 的 NOW 占位）', async () => {
    const f = await getFactors('/securities/510300.SH/factors');
    expect(f.items).toEqual([]);
    expect(f.data_as_of).toBeNull();
    expect(f.gaps.map((g) => g.reason)).toEqual(['not_applicable']);
  });

  it('对照：有真实批次的股票仍保留旧时点与版本号（空态口径不污染有数据场景）', async () => {
    const f = await getFactors('/securities/600000.SH/factors');
    expect(f.data_as_of).toBe('2026-10-30T18:30:00+08:00');
    expect(f.factor_set_version).not.toBeNull();
    expect(f.items.length).toBeGreaterThan(0);
  });
});

describe('② 页面：null 响应必须等到其特有完成内容再断言', { timeout: 25_000 }, () => {
  beforeEach(() => mockLoginAs('demo_user'));

  it('MarketOverview：null → 等「数据不可用（无数据时点）」（加载态无此文案）', async () => {
    server.use(http.get(`${API}/market/overview`, () => HttpResponse.json({
      trade_date: '2026-11-02', session: 'closed', indices: [], breadth: null, regime: null, regime_position_range: null,
      turnover_total: null, data_status: 'unavailable', data_as_of: null,
      gaps: [{ key: 'all', reason: 'no_source', message: '从未取得（示例）' }],
    })));
    renderAt('/market');
    const page = await screen.findByTestId('market-page', {}, { timeout: 10_000 });
    const line = await screen.findByText('数据不可用（无数据时点）', {}, { timeout: 10_000 });
    expect(line).toBeInTheDocument();
    expectNoBadTime(page);
  });

  it('SectorFlows：null → 等该响应的 gap 提示（sector-gap-note）并在容器内断言', async () => {
    server.use(http.get(`${API}/market/sector-flows`, () => HttpResponse.json({
      kind: 'industry', taxonomy: 'sw_l1', trade_date: '2026-11-02', items: [], sources: [],
      data_status: 'unavailable', data_as_of: null, gaps: [{ key: 'sector', reason: 'no_source', message: '板块资金从未取得（示例）' }],
    })));
    renderAt('/market');
    const panel = await screen.findByTestId('sector-panel', {}, { timeout: 10_000 });
    // 加载态只渲染容器；这条 gap 文本只在 null 响应被消费后出现
    const gap = await within(panel).findByTestId('sector-gap-note', {}, { timeout: 10_000 });
    expect(gap.textContent).toContain('板块资金从未取得（示例）');
    expectNoBadTime(panel);
  });

  it('SecurityProfile：null → 等 attribution（profile 成功态才渲染）', async () => {
    server.use(http.get(`${API}/securities/:code`, () => HttpResponse.json({
      security_code: '600000.SH', name: '示例银行', type: 'stock', exchange: 'SH', board: 'main',
      list_date: null, list_date_basis: null, delist_date: null, listing_status: 'listed', risk_flag: null,
      former_names: [], code_history: [], master_as_of: '2026-11-02', attribution: '示例来源',
      industry: null, concepts: [], total_shares: null, float_shares: null, suspended: null, sources: [],
      data_status: 'partial', data_as_of: null, gaps: [{ key: 'cert', reason: 'data_licence_unavailable', message: '证书不可用（示例）' }],
    })));
    renderAt('/stocks/600000.SH');
    const panel = await screen.findByTestId('profile-panel', {}, { timeout: 10_000 });
    await waitFor(() => expect(panel.textContent).toContain('示例来源'), { timeout: 10_000 });
    expectNoBadTime(panel);
    expect(document.querySelector('.error-box')).toBeNull();
  });
});

describe('③ 两处 slice 崩溃回归（真实组件路径，全部显式合成，不用 passthrough）', { timeout: 30_000 }, () => {
  beforeEach(() => mockLoginAs('demo_user'));

  // quote 必须存在：没有 quote 时 preClose 分支提前 return，触达不到旧崩溃行
  const quote: QuoteItem = {
    security_code: '600000.SH', name: '示例银行', price: '10.24', change_pct: '2.20', volume: '41230000', amount: '420000000.00',
    t: '2026-11-02T10:31:00+08:00', data_status: 'fresh', data_as_of: '2026-11-02T10:31:00+08:00', gaps: [],
  };
  /** quoteDelayMs>0 时延迟返回：用于证明「quote 晚于 minute 到达」时断言同样成立（顺序不影响） */
  const armQuote = (quoteDelayMs = 0) =>
    server.use(
      http.get(`${API}/quotes`, async () => {
        if (quoteDelayMs > 0) await new Promise((r) => setTimeout(r, quoteDelayMs));
        return HttpResponse.json({ items: [quote] });
      }),
    );
  /**
   * 头部「昨收」取值：昨收行在场时返回该值，行不在场返回 null（未渲染 / 显示占位都不算采纳）。
   * 只读头部统计区，不扫全页文本——否则价格或其它字段里的同数字会造成假命中。
   */
  const shouCloseOf = (head: HTMLElement): string | null => {
    const row = Array.from(head.querySelectorAll('*')).find((el) => /^昨收$/.test(el.textContent?.trim() ?? ''));
    const box = row?.parentElement ?? null;
    const m = box?.textContent?.match(/昨收\s*([0-9.]+)/);
    return m ? m[1] : null;
  };

  /** 日 K 固定给「不含今日」的 bar：todayBar() 找不到当日 bar → 不会提前给出 pre_close（不短路旧行） */
  const dailyBars = (): BarsResponse => ({
    security_code: '600000.SH', name: '示例银行', freq: 'd', adjust: 'qfq', pre_close: null,
    items: [{ t: '2026-10-30', open: '10.00', high: '10.10', low: '9.95', close: '10.02', pre_close: null, volume: '1000', amount: '10020', avg_price: null, is_final: true }],
    next_before: null, adjust_as_of: '2026-10-30', data_status: 'fresh', data_as_of: '2026-10-30T15:00:00+08:00', gaps: [],
  });

  const barsRoute = (minute: Record<string, unknown>) =>
    http.get(`${API}/securities/:code/bars`, ({ request }) => {
      const freq = new URL(request.url).searchParams.get('freq') ?? '';
      if (freq === '1m') return HttpResponse.json(minute);
      return HttpResponse.json(dailyBars());
    });

  const minuteBase = {
    security_code: '600000.SH', name: '示例银行', freq: '1m', adjust: 'none',
    next_before: null, adjust_as_of: null, gaps: [],
  };

  /** 无时点空态用例：同一份合成 minute（items=[] + data_as_of=null + pre_close 非空） */
  const armEmptyMinute = () =>
    server.use(barsRoute({ ...minuteBase, pre_close: '10.02', items: [], data_status: 'unavailable', data_as_of: null,
      gaps: [{ key: 'bars', reason: 'no_source', message: '分时从未取得（示例）' }] }));

  /** 两条真实 slice 行都被走到、且结果符合契约：minute 空态 + quote 已被头部消费 + 昨收未采纳 10.02 */
  async function expectBothSlicePathsReached() {
    // ① minute 响应被消费并走过 PriceChartPanel.tradeDate（null 时点不取交易日）
    const empty = await screen.findByTestId('chart-empty', {}, { timeout: 15_000 });
    expect(empty.textContent).toMatch(/无分时数据/);
    // ② quote 已被 StockHeader 消费：头部显示该 quote 价格；否则 StockPage.intradayPreClose 会因 !q 提前 return，旧 slice 行根本走不到
    const head = await screen.findByTestId('stock-head', {}, { timeout: 15_000 });
    await waitFor(() => expect(head.textContent).toContain('10.24'), { timeout: 12_000 });
    // ③ 无时点就不认交易日：昨收不采纳 10.02（缺省为未渲染/占位），头部无失败痕迹
    expect(shouCloseOf(head)).not.toBe('10.02');
    expect(head.textContent).not.toMatch(/Cannot read properties|TypeError|undefined|NaN/);
    return { head, empty };
  }

  it('无时点空态（minute 先到）：1m items=[] 且 data_as_of=null → 两处 slice 路径都走到且不崩', async () => {
    armQuote();
    armEmptyMinute();
    renderAt('/stocks/600000.SH');
    await expectBothSlicePathsReached();
  });

  it('无时点空态（quote 延后 400ms）：到达顺序不影响断言，仍两处路径都走到且不崩', async () => {
    armQuote(400);
    armEmptyMinute();
    renderAt('/stocks/600000.SH');
    await expectBothSlicePathsReached();
  });

  it('item.t 优先：items[0].t 与 quote 同日 → 采纳 pre_close，不崩', async () => {
    armQuote();
    server.use(barsRoute({ ...minuteBase, pre_close: '10.02', data_status: 'fresh', data_as_of: null,
      items: [{ t: '2026-11-02T09:30:00+08:00', open: '10.05', high: '10.06', low: '10.04', close: '10.05', pre_close: null, volume: '1000', amount: '10050', avg_price: '10.05', is_final: true }] }));
    renderAt('/stocks/600000.SH');
    const head = await screen.findByTestId('stock-head', {}, { timeout: 15_000 });
    // 行情已消费（价格出现）且 quote-gap-note/DataStatusTag 到位后才断言前收列
    await waitFor(() => expect(head.textContent).toContain('10.24'), { timeout: 12_000 });
    await waitFor(() => expect(head.textContent).toMatch(/昨收\s*10\.02/), { timeout: 12_000 });
    expect(document.body.textContent).not.toMatch(/Cannot read properties|TypeError/);
  });

  it('仅非空 data_as_of 回退：items=[] 但 data_as_of 与 quote 同日 → 采纳 pre_close', async () => {
    armQuote();
    server.use(barsRoute({ ...minuteBase, pre_close: '10.02', items: [], data_status: 'fresh', data_as_of: '2026-11-02T09:30:00+08:00' }));
    renderAt('/stocks/600000.SH');
    const head = await screen.findByTestId('stock-head', {}, { timeout: 15_000 });
    await waitFor(() => expect(head.textContent).toContain('10.24'), { timeout: 12_000 });
    await waitFor(() => expect(head.textContent).toMatch(/昨收\s*10\.02/), { timeout: 12_000 });
  });

  it('跨交易日：data_as_of 与 quote 不同日 → 不采纳该 pre_close', async () => {
    armQuote();
    server.use(barsRoute({ ...minuteBase, pre_close: '9.80', items: [], data_status: 'fresh', data_as_of: '2026-11-01T09:30:00+08:00' }));
    renderAt('/stocks/600000.SH');
    const head = await screen.findByTestId('stock-head', {}, { timeout: 15_000 });
    await waitFor(() => expect(head.textContent).toContain('10.24'), { timeout: 12_000 });
    // 等 minute 消费完成（chart-empty 来自 minute 响应），再断言前收未被采纳
    await screen.findByTestId('chart-empty', {}, { timeout: 12_000 });
    expect(head.textContent).not.toContain('9.80');
  });
});
