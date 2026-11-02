/** T-F21 性能：AG Grid 虚拟化 + 批量事务、K 线窗口加载（bars before+limit）、通用游标分页（契约 §1.2） */
import { onTestFinished } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import type { Bar, BarsResponse } from '../api/types';
import type { Announcement } from '../api/marketTypes';
import { consistentPages, mergeBarPages } from '../api/marketQueries';
import { DataGrid, type DataColumn } from '../components/DataGrid';
import { planRowUpdate } from '../components/gridBatch';
import { shiftView } from '../components/charts/chartBase';
import { flattenPages, clampLimit } from '../lib/cursorPaging';
import { HISTORY_DAYS, dailyBars } from '../mocks/fixtures';
import { page } from '../mocks/handlerUtils';
import { server } from '../mocks/server';

// 页面模块的冷加载放在等待窗口之外（评审 b23401a N8）
beforeAll(() => preloadRoutes(routes), 30_000);

// 图表在 jsdom 里不绘制：记录根数，并提供一个“拖到左边缘”的按钮触发 onReachStart
vi.mock('../components/charts/KlineChart', () => ({
  KlineChart: ({ bars, onReachStart, viewKey }: { bars: Bar[]; onReachStart?: () => void; viewKey?: string }) => (
    <div data-testid="kline" data-n={bars.length} data-first={bars[0]?.t} data-key={viewKey}>
      <button type="button" onClick={() => onReachStart?.()}>模拟拖到左边缘</button>
    </div>
  ),
}));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));
vi.mock('../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div data-testid="fund-flow-chart" /> }));

const API = '/api/v1';
const CODE = '600000.SH';

function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders client={makeQueryClient(true)}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}

/** 记录 bars 请求的 freq/limit/before */
function recordBars() {
  const calls: { freq: string | null; limit: string | null; before: string | null }[] = [];
  const onReq = ({ request }: { request: Request }) => {
    const u = new URL(request.url);
    if (u.pathname.endsWith('/bars')) calls.push({ freq: u.searchParams.get('freq'), limit: u.searchParams.get('limit'), before: u.searchParams.get('before') });
  };
  server.events.on('request:start', onReq);
  return { calls, stop: () => server.events.removeListener('request:start', onReq) };
}

const bar = (t: string): Bar => ({ t, open: '1', high: '1', low: '1', close: '1', pre_close: null, volume: '1', amount: '1', avg_price: null, is_final: true });
const resp = (ts: string[], asOf = '2026-10-30', next: string | null = null): BarsResponse => ({
  security_code: CODE, name: '示例', freq: 'd', adjust: 'qfq', pre_close: null, items: ts.map(bar), next_before: next, adjust_as_of: asOf,
  data_status: 'fresh', data_as_of: '2026-10-30T15:00:00+08:00', gaps: [],
});

describe('T-F21 纯函数', () => {
  it('planRowUpdate：引用未变 → none；仅值变 → update（只含变化的行）；增删/换序 → reset', () => {
    const id = (r: { id: string }) => r.id;
    const a = { id: 'a', v: 1 }, b = { id: 'b', v: 1 }, c = { id: 'c', v: 1 };
    const rows = [a, b, c];
    expect(planRowUpdate(rows, rows, id)).toEqual({ kind: 'none' });
    expect(planRowUpdate(rows, [a, b, c], id)).toEqual({ kind: 'none' });
    const b2 = { id: 'b', v: 2 };
    expect(planRowUpdate(rows, [a, b2, c], id)).toEqual({ kind: 'update', update: [b2] });
    expect(planRowUpdate(rows, [a, b], id)).toEqual({ kind: 'reset' });
    expect(planRowUpdate(rows, [b, a, c], id)).toEqual({ kind: 'reset' });
  });

  it('mergeBarPages：最新页在前、更早页在后 → 合并为升序并按 t 去重；consistentPages 截掉基准日不同的更早页', () => {
    const p1 = resp(['2026-10-28', '2026-10-29', '2026-10-30'], 'A', '2026-10-28');
    const p2 = resp(['2026-10-26', '2026-10-27', '2026-10-28'], 'A', null);
    expect(mergeBarPages([p1, p2]).map((b) => b.t)).toEqual(['2026-10-26', '2026-10-27', '2026-10-28', '2026-10-29', '2026-10-30']);
    const p3 = resp(['2026-10-23'], 'B');
    expect(consistentPages([p1, p2, p3])).toEqual([p1, p2]);
    expect(consistentPages([])).toEqual([]);
  });

  it('shiftView：左侧拼进 k 根后视口右移 k；换图或找不到原最左一根 → null', () => {
    const prev = { key: 'X:d', first: '2026-10-26', from: 30, to: 120 };
    expect(shiftView(prev, 'X:d', ['2026-10-22', '2026-10-23', '2026-10-26', '2026-10-27'])).toEqual({ from: 32, to: 122 });
    expect(shiftView(prev, 'X:d', ['2026-10-26', '2026-10-27'])).toEqual({ from: 30, to: 120 });
    expect(shiftView(prev, 'Y:d', ['2026-10-26'])).toBeNull();
    expect(shiftView(prev, 'X:d', ['2026-10-27'])).toBeNull();
    expect(shiftView(null, 'X:d', ['2026-10-26'])).toBeNull();
  });

  it('flattenPages 跨页去重；clampLimit 按 §1.2 夹在 1–200', () => {
    const pages = [{ items: [{ id: '1' }, { id: '2' }] }, { items: [{ id: '2' }, { id: '3' }] }];
    expect(flattenPages(pages, (r) => r.id).map((r) => r.id)).toEqual(['1', '2', '3']);
    expect(flattenPages(pages).length).toBe(4);
    expect([clampLimit(0), clampLimit(500), clampLimit(30)]).toEqual([50, 200, 30]);
  });

  it('示例日 K：最近 120 根之前补了历史，日期升序、pre_close 前后衔接、OHLC 自洽', () => {
    const d = dailyBars(CODE)!;
    expect(d.items.length).toBe(HISTORY_DAYS + 120);
    for (let i = 1; i < d.items.length; i++) {
      expect(d.items[i].t > d.items[i - 1].t).toBe(true);
      expect(d.items[i].pre_close).toBe(d.items[i - 1].close);
    }
    for (const b of d.items) {
      const [o, h, l, c] = [b.open, b.high, b.low, b.close].map(Number);
      expect(h).toBeGreaterThanOrEqual(Math.max(o, c));
      expect(l).toBeLessThanOrEqual(Math.min(o, c));
      expect(c).toBeGreaterThan(0);
    }
  });
});

type Row = { id: string; v: number };
const COLS: DataColumn<Row>[] = [{ key: 'id', header: '代码', value: (r) => r.id }, { key: 'v', header: '值', value: (r) => r.v }];
const rowsOf = (n: number) => Array.from({ length: n }, (_, i) => ({ id: `r${String(i).padStart(4, '0')}`, v: i }));

describe('T-F21 表格', () => {
  it('2,000 行只渲染可视区附近的行（行虚拟化）', async () => {
    // jsdom 没有布局：给元素一个 800×300 的尺寸，让 AG Grid 算出可视区
    const rect = vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, top: 0, left: 0, right: 800, bottom: 300, width: 800, height: 300, toJSON: () => ({}) } as DOMRect);
    const ch = vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(300);
    const cw = vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(800);
    const oh = vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(300);
    const ow = vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(800);
    onTestFinished(() => [rect, ch, cw, oh, ow].forEach((m) => m.mockRestore()));
    render(<div style={{ height: 300 }}><DataGrid<Row> testId="g" rows={rowsOf(2000)} columns={COLS} getRowId={(r) => r.id} /></div>);
    const bodyRows = () => document.querySelectorAll('.ag-row[row-index]').length;
    await waitFor(() => expect(bodyRows()).toBeGreaterThan(0));
    expect(bodyRows()).toBeLessThan(2 * 20 + 20);
    expect(screen.getByTestId('g').textContent).toContain('r0000');
    expect(screen.getByTestId('g').textContent).not.toContain('r1999');
  });

  it('batchUpdates：只改值的刷新走批量事务，单元格更新；增删行整体替换', async () => {
    const id = (r: Row) => r.id;
    const base = rowsOf(3);
    const { rerender } = render(<DataGrid<Row> testId="g" rows={base} columns={COLS} getRowId={id} batchUpdates />);
    await waitFor(() => expect(screen.getByTestId('g').textContent).toContain('r0001'));
    const next = [base[0], { id: 'r0001', v: 777 }, base[2]];
    rerender(<DataGrid<Row> testId="g" rows={next} columns={COLS} getRowId={id} batchUpdates />);
    await waitFor(() => expect(screen.getByTestId('g').textContent).toContain('777'));
    rerender(<DataGrid<Row> testId="g" rows={[...next, { id: 'r0009', v: 9 }]} columns={COLS} getRowId={id} batchUpdates />);
    await waitFor(() => expect(screen.getByTestId('g').textContent).toContain('r0009'));
    rerender(<DataGrid<Row> testId="g" rows={[next[2]]} columns={COLS} getRowId={id} batchUpdates />);
    await waitFor(() => expect(screen.getByTestId('g').textContent).not.toContain('r0009'));
    expect(screen.getByTestId('g').textContent).toContain('r0002');
    expect(screen.getByTestId('g').textContent).not.toContain('777');
  });
});

describe('T-F21 K 线窗口加载', () => {
  it('个股日 K：先取 250 根；拖到左边缘按 next_before 取更早一页并拼在左侧；到最早后不再请求', async () => {
    const total = dailyBars(CODE)!.items.length;
    const rec = recordBars();
    renderAt(`/stocks/${CODE}`);
    const panel = await screen.findByTestId('price-chart');
    fireEvent.click(within(panel).getByText('日K'));
    await waitFor(() => expect(screen.getByTestId('kline').getAttribute('data-n')).toBe('250'));
    expect(screen.getByTestId('kline').getAttribute('data-key')).toBe(`${CODE}:d`);
    expect(screen.getByTestId('kline-window').textContent).toContain('已载入 250 根日 K');
    const first1 = screen.getByTestId('kline').getAttribute('data-first')!;
    fireEvent.click(screen.getByText('模拟拖到左边缘'));
    await waitFor(() => expect(screen.getByTestId('kline').getAttribute('data-n')).toBe('500'));
    expect(screen.getByTestId('kline').getAttribute('data-first')! < first1).toBe(true);
    // 键盘/读屏：按钮与拖动效果相同
    fireEvent.click(screen.getByTestId('kline-older'));
    await waitFor(() => expect(screen.getByTestId('kline').getAttribute('data-n')).toBe(String(total)));
    expect(screen.getByTestId('kline-window').textContent).toContain('已到最早');
    expect(screen.queryByTestId('kline-older')).toBeNull();
    const daily = rec.calls.filter((c) => c.freq === 'd');
    rec.stop();
    // 行情头与图表共用同一个窗口缓存：首页只请求一次
    expect(daily.filter((c) => c.before === null)).toHaveLength(1);
    expect(daily.filter((c) => c.before !== null).map((c) => c.limit)).toEqual(['250', '250']);
    const n = daily.length;
    fireEvent.click(screen.getByText('模拟拖到左边缘'));
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
    expect(rec.calls.filter((c) => c.freq === 'd').length).toBe(n);
  });

  it('更早一页失败：已加载的 K 线保留，提示失败；拖动不自动重试，点“重试”再取', async () => {
    let fail = true;
    let olderCalls = 0;
    server.use(http.get(`${API}/securities/:code/bars`, ({ request }) => {
      const u = new URL(request.url);
      if (u.searchParams.get('before') && u.searchParams.get('freq') === 'd') {
        olderCalls += 1;
        if (fail) return HttpResponse.json({ error: { code: 'INTERNAL', message: '示例失败', details: null, request_id: 'r' } }, { status: 500 });
      }
      return undefined;
    }));
    renderAt(`/stocks/${CODE}`);
    fireEvent.click(within(await screen.findByTestId('price-chart')).getByText('日K'));
    await waitFor(() => expect(screen.getByTestId('kline').getAttribute('data-n')).toBe('250'));
    fireEvent.click(screen.getByText('模拟拖到左边缘'));
    await waitFor(() => expect(screen.getByTestId('kline-window').textContent).toContain('更早的加载失败'));
    expect(screen.getByTestId('kline').getAttribute('data-n')).toBe('250');
    const after = olderCalls;
    fireEvent.click(screen.getByText('模拟拖到左边缘'));
    await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
    expect(olderCalls).toBe(after);
    fail = false;
    fireEvent.click(screen.getByTestId('kline-older'));
    await waitFor(() => expect(screen.getByTestId('kline').getAttribute('data-n')).toBe('500'));
  });

  it('v0.2.7 adjust_as_of：更早一页的复权基准日与已加载的不同 → 丢弃窗口，从最新一页重新加载', async () => {
    let asOf = '2026-10-30';
    const seen: (string | null)[] = [];
    server.use(http.get(`${API}/securities/:code/bars`, async ({ request }) => {
      const u = new URL(request.url);
      if (u.searchParams.get('freq') !== 'd') return undefined;
      const before = u.searchParams.get('before');
      seen.push(before);
      const all = dailyBars(CODE)!.items;
      const pool = before ? all.filter((b) => b.t < before) : all;
      const items = pool.slice(-250);
      if (before) asOf = '2026-11-02'; // 除权后基准日变了
      return HttpResponse.json({ ...dailyBars(CODE)!, items, next_before: pool.length > items.length ? items[0].t : null, adjust_as_of: asOf });
    }));
    renderAt(`/stocks/${CODE}`);
    fireEvent.click(within(await screen.findByTestId('price-chart')).getByText('日K'));
    await waitFor(() => expect(screen.getByTestId('kline').getAttribute('data-n')).toBe('250'));
    fireEvent.click(screen.getByText('模拟拖到左边缘'));
    await waitFor(() => expect(seen.filter((b) => b === null).length).toBe(2));
    await waitFor(() => expect(screen.getByTestId('kline').getAttribute('data-n')).toBe('250'));
    expect(seen).toEqual([null, expect.any(String), null]);
  });

  it('交易终端日 K：窗口 120 根，可继续向左加载', async () => {
    renderAt('/terminal');
    await waitFor(() => expect(screen.getByTestId('kline').getAttribute('data-n')).toBe('120'));
    expect(screen.getByTestId('kline-window').textContent).toContain('已载入 120 根日 K');
    fireEvent.click(screen.getByText('模拟拖到左边缘'));
    await waitFor(() => expect(screen.getByTestId('kline').getAttribute('data-n')).toBe('240'));
  });
});

const fakeAnns = (n: number): Announcement[] => Array.from({ length: n }, (_, i) => ({
  id: `ann_t_${String(i).padStart(3, '0')}`, published_at: `2026-10-${String(30 - (i % 28)).padStart(2, '0')}T17:30:00+08:00`, title: `示例公告 ${i + 1}`,
  category: 'other', category_raw: null, level_raw: null, url: null, url_host: null, file_format: null, first_seen_at: '2026-10-30T18:00:00+08:00',
}));

describe('T-F21 通用游标分页', () => {
  it('公告：首屏 30 条，“加载更多”按 next_cursor 取下一页；到底显示“已显示全部”', async () => {
    const list = fakeAnns(70);
    const cursors: (string | null)[] = [];
    server.use(http.get(`${API}/securities/:code/announcements`, ({ request }) => {
      const u = new URL(request.url);
      cursors.push(u.searchParams.get('cursor'));
      return HttpResponse.json({ ...page(list, u), disclaimer: '示例', sources: [], data_status: 'fresh', data_as_of: '2026-10-30T18:00:00+08:00', gaps: [] });
    }));
    renderAt(`/stocks/${CODE}?tab=announcements`);
    const tab = await screen.findByTestId('tab-announcements');
    await waitFor(() => expect(within(tab).getByTestId('ann-pager').textContent).toContain('已加载 30 条'));
    fireEvent.click(within(tab).getByTestId('ann-pager-more'));
    await waitFor(() => expect(within(tab).getByTestId('ann-pager').textContent).toContain('已加载 60 条'));
    fireEvent.click(within(tab).getByTestId('ann-pager-more'));
    await waitFor(() => expect(within(tab).getByTestId('ann-pager-end').textContent).toBe('已显示全部 70 条'));
    expect(within(tab).getByText('示例公告 70')).toBeInTheDocument();
    expect(cursors).toEqual([null, '30', '60']);
  });

  it('下一页失败：已加载的保留并就地提示，可重试', async () => {
    const list = fakeAnns(40);
    let fail = true;
    server.use(http.get(`${API}/securities/:code/announcements`, ({ request }) => {
      const u = new URL(request.url);
      if (u.searchParams.get('cursor') && fail) return HttpResponse.json({ error: { code: 'INTERNAL', message: '示例失败', details: null, request_id: 'r' } }, { status: 500 });
      return HttpResponse.json({ ...page(list, u), disclaimer: '示例', sources: [], data_status: 'fresh', data_as_of: '2026-10-30T18:00:00+08:00', gaps: [] });
    }));
    renderAt(`/stocks/${CODE}?tab=announcements`);
    const tab = await screen.findByTestId('tab-announcements');
    fireEvent.click(await within(tab).findByTestId('ann-pager-more'));
    expect(await within(tab).findByText('下一页加载失败，已加载的内容保留')).toHaveAttribute('role', 'alert');
    expect(within(tab).getByTestId('ann-pager-more')).toHaveTextContent(/重\s?试/);
    expect(within(tab).getByText('示例公告 30')).toBeInTheDocument();
    fail = false;
    fireEvent.click(within(tab).getByTestId('ann-pager-more'));
    await waitFor(() => expect(within(tab).getByTestId('ann-pager-end').textContent).toBe('已显示全部 40 条'));
  });
});

