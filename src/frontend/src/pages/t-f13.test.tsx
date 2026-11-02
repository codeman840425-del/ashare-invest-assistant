/** T-F13（契约 v0.2.7 §5.3 DailyReport、§7 `/daily-reports*`）：盘后日报页补全 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { preloadRoutes } from '../test/preloadRoutes';
import { DISCLAIMER_TEXT } from '../components/RiskDisclosure';
import { DAILY_REPORT_LIST, DAILY_REPORTS, PREV_REPORT_DATE, REPORT_DATE } from '../mocks/fixtures';
import { server } from '../mocks/server';
import { PENDING_ROUTE } from './dailyReportRoutes';

// 页面模块的冷加载放在等待窗口之外（评审 b23401a N8）
beforeAll(() => preloadRoutes(routes), 30_000);

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

const API = '/api/v1';

function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders client={makeQueryClient(true)}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}

const cur = DAILY_REPORTS.find((d) => d.date === REPORT_DATE)!;

describe('T-F13 盘后日报', () => {
  it('/daily-reports 跳到最新一期（列表按日期倒序）', async () => {
    expect(DAILY_REPORT_LIST.map((x) => x.date)).toEqual([REPORT_DATE, PREV_REPORT_DATE]);
    const router = renderAt('/daily-reports');
    await waitFor(() => expect(router.state.location.pathname).toBe(`/daily-reports/${REPORT_DATE}`));
  });

  it('账户概览：对账状态、差异数与重要差异数、对账时间、查看对账链接；参考区间注明不是指令', async () => {
    renderAt(`/daily-reports/${REPORT_DATE}`);
    const acct = await screen.findByTestId('report-account');
    expect(within(acct).getByTestId('report-rec').textContent).toBe(`存在差异 · ${cur.reconciliation.diff_count} 处差异（重要 ${cur.reconciliation.important_count}）`);
    expect(acct.textContent).toContain('对账于');
    expect(within(acct).getByRole('link', { name: '查看对账 ›' }).getAttribute('href')).toBe(`/portfolio?tab=reconciliation&account_id=${cur.account_id}`);
    expect(acct.textContent).toContain('（模板参数，不是指令）');
    expect(within(acct).getByRole('img').getAttribute('aria-label')).toMatch(/^当前仓位 [\d.]+%，参考区间 40–60%$/);
  });

  it('免责提示固定展示（⚖ 接口）；数据缺口逐条列出', async () => {
    renderAt(`/daily-reports/${REPORT_DATE}`);
    const page = await screen.findByTestId('daily-report');
    expect(within(page).getByTestId('card-disclaimer').textContent).toBe(DISCLAIMER_TEXT);
    const gaps = within(page).getByTestId('report-gaps');
    for (const g of cur.gaps) expect(gaps.textContent).toContain(g.message);
  });

  it('待处理：计数大于 0 时给出去向链接', async () => {
    renderAt(`/daily-reports/${REPORT_DATE}`);
    const p = await screen.findByTestId('report-pending');
    const hrefs = within(p).getAllByRole('link').map((a) => a.getAttribute('href'));
    expect(hrefs).toEqual([cur.pending.plan_drafts ? PENDING_ROUTE.plan_drafts : null, cur.pending.active_reasons ? PENDING_ROUTE.active_reasons : null].filter(Boolean));
  });

  it('逐股卡片：键盘经标题链接进入候选信号卡；鼠标点卡片空白处也可进入（评审 b23401a N4）', async () => {
    const router = renderAt(`/daily-reports/${REPORT_DATE}`);
    const s = cur.stocks.find((x) => x.suggestion_id)!;
    const card = await screen.findByTestId(`stc-${s.security_code}`);
    expect(card.getAttribute('role')).toBeNull();
    expect(card.hasAttribute('tabindex')).toBe(false);
    const link = within(card).getByTestId(`stc-link-${s.security_code}`);
    expect(link.tagName).toBe('A');
    expect(link.getAttribute('href')).toBe(`/suggestions/${s.suggestion_id}`);
    fireEvent.click(card);
    await waitFor(() => expect(router.state.location.pathname).toBe(`/suggestions/${s.suggestion_id}`));
  });

  it('按变化筛选：URL ?filter= 驱动，非法值按“全部”', async () => {
    const router = renderAt(`/daily-reports/${REPORT_DATE}?filter=changed`);
    await screen.findByTestId('daily-report');
    const changed = cur.stocks.filter((s) => s.change_from_previous === 'new' || s.change_from_previous === 'changed');
    expect(document.querySelectorAll('.stock-card')).toHaveLength(changed.length);
    fireEvent.click(screen.getByText(`全部 ${cur.stocks.length}`));
    await waitFor(() => expect(router.state.location.search).toBe(''));
    expect(document.querySelectorAll('.stock-card')).toHaveLength(cur.stocks.length);
    fireEvent.click(screen.getByText('已移出 0'));
    expect(await screen.findByTestId('report-empty')).toHaveTextContent('没有符合筛选条件的证券');
  });

  it('非法 filter 值按全部处理', async () => {
    renderAt(`/daily-reports/${REPORT_DATE}?filter=bogus`);
    await screen.findByTestId('daily-report');
    expect(document.querySelectorAll('.stock-card')).toHaveLength(cur.stocks.length);
  });

  it('上一期：未导入交割单 → 账户概览为空并给出导入入口；宽度缺失；已移出证券不可点击', async () => {
    const router = renderAt(`/daily-reports/${REPORT_DATE}`);
    await screen.findByTestId('daily-report');
    await waitFor(() => expect(screen.getByRole('button', { name: '上一期' })).toBeEnabled());
    expect(screen.getByRole('button', { name: '下一期' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '上一期' }));
    await waitFor(() => expect(router.state.location.pathname).toBe(`/daily-reports/${PREV_REPORT_DATE}`));
    const none = await screen.findByTestId('report-no-account');
    expect(none.textContent).toContain('尚未导入交割单');
    expect(within(none).getByRole('link').getAttribute('href')).toBe('/portfolio/import');
    expect(screen.getByTestId('report-rec').textContent).toBe('未导入');
    expect(screen.getByTestId('report-no-breadth')).toBeInTheDocument();
    const removed = screen.getByTestId('stc-000003.SZ');
    expect(removed.getAttribute('role')).toBeNull();
    expect(removed.getAttribute('tabindex')).toBeNull();
    expect(removed.textContent).toContain('已移出持仓与自选');
    expect(within(screen.getByTestId('report-pending')).queryAllByRole('link')).toHaveLength(0);
    await waitFor(() => expect(screen.getByRole('button', { name: '下一期' })).toBeEnabled());
    expect(screen.getByRole('button', { name: '上一期' })).toBeDisabled();
  });

  it('日期列表按 §1.2 游标分页：最早一期在第二页时，点一次“上一期”就加载更早并跳转（评审 7afbc06 m1）', async () => {
    const seen: (string | null)[] = [];
    server.use(http.get(`${API}/daily-reports`, ({ request }) => {
      const cursor = new URL(request.url).searchParams.get('cursor');
      seen.push(cursor);
      return HttpResponse.json(cursor === 'p2' ? { items: [DAILY_REPORT_LIST[1]], next_cursor: null } : { items: [DAILY_REPORT_LIST[0]], next_cursor: 'p2' });
    }));
    const router = renderAt(`/daily-reports/${REPORT_DATE}`);
    await screen.findByTestId('daily-report');
    const prev = await screen.findByRole('button', { name: '上一期' });
    await waitFor(() => expect(prev).toBeEnabled());
    fireEvent.click(prev);
    await waitFor(() => expect(router.state.location.pathname).toBe(`/daily-reports/${PREV_REPORT_DATE}`));
    expect(seen).toContain('p2');
  });

  it('“上一期”加载更早时用户已换日期：加载完成后不再跳转（评审 b23401a N6）', async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => { release = r; });
    server.use(http.get(`${API}/daily-reports`, async ({ request }) => {
      const cursor = new URL(request.url).searchParams.get('cursor');
      if (cursor === 'p2') { await gate; return HttpResponse.json({ items: [DAILY_REPORT_LIST[1]], next_cursor: null }); }
      return HttpResponse.json({ items: [DAILY_REPORT_LIST[0]], next_cursor: 'p2' });
    }), http.get(`${API}/daily-reports/2026-10-20`, () => HttpResponse.json({ ...cur, date: '2026-10-20' })));
    // 先看过 10-20（进缓存），再回到最新一期；之后切回 10-20 时页面不经过加载态，切换器保持挂载
    const router = renderAt('/daily-reports/2026-10-20');
    await screen.findByTestId('daily-report');
    await router.navigate(`/daily-reports/${REPORT_DATE}`);
    await waitFor(() => expect(document.querySelector('.report-dates')?.textContent).toContain(REPORT_DATE));
    const prev = await screen.findByRole('button', { name: '上一期' });
    await waitFor(() => expect(prev).toBeEnabled());
    fireEvent.click(prev);
    await router.navigate('/daily-reports/2026-10-20');
    await waitFor(() => expect(document.querySelector('.report-dates')?.textContent).toContain('2026-10-20'));
    // “更早”那一页此时才返回：等待期间地址已变，不应再跳到 10-29
    release();
    await new Promise((r) => setTimeout(r, 200));
    expect(router.state.location.pathname).toBe('/daily-reports/2026-10-20');
  });

  it('切换日期保留 ?filter=（评审 7afbc06 m2）', async () => {
    const router = renderAt(`/daily-reports/${REPORT_DATE}?filter=changed`);
    await screen.findByTestId('daily-report');
    await waitFor(() => expect(screen.getByRole('button', { name: '上一期' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: '上一期' }));
    await waitFor(() => expect(router.state.location.pathname).toBe(`/daily-reports/${PREV_REPORT_DATE}`));
    expect(router.state.location.search).toBe('?filter=changed');
    await waitFor(() => expect(screen.getByRole('button', { name: '下一期' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: '下一期' }));
    await waitFor(() => expect(router.state.location.pathname).toBe(`/daily-reports/${REPORT_DATE}`));
    expect(router.state.location.search).toBe('?filter=changed');
  });

  it('卡片名称取自标题（aria-labelledby）；链接名带去向说明；证据标签不在链接内、可聚焦并显示详情（评审 7afbc06 m3、b23401a N2–N5）', async () => {
    const router = renderAt(`/daily-reports/${REPORT_DATE}`);
    const s = cur.stocks.find((x) => x.suggestion_id)!;
    const card = await screen.findByTestId(`stc-${s.security_code}`);
    expect(card.hasAttribute('aria-label')).toBe(false);
    const title = document.getElementById(card.getAttribute('aria-labelledby')!)!;
    expect(card.contains(title)).toBe(true);
    const link = screen.getByRole('link', { name: `${s.name} ${s.security_code}：查看候选信号卡` });
    expect(link).toBe(title);
    const chip = card.querySelector<HTMLElement>('.ev-chip:not(.missing):not(.none)');
    expect(chip).not.toBeNull();
    if (chip) {
      expect(link.contains(chip)).toBe(false);
      expect(chip.closest('a,[role="link"]')).toBeNull();
      expect(chip.getAttribute('role')).toBe('button');
      expect(chip.getAttribute('tabindex')).toBe('0');
      expect(chip.getAttribute('aria-label')).toMatch(/^证据 /);
      // N3：空格被 preventDefault（不滚动页面），Enter / 空格 / 点击都不冒泡到卡片
      expect(fireEvent.keyDown(chip, { key: ' ' })).toBe(false);
      expect(fireEvent.keyDown(chip, { key: 'Enter' })).toBe(false);
      fireEvent.click(chip);
      expect(router.state.location.pathname).toBe(`/daily-reports/${REPORT_DATE}`);
      fireEvent.focus(chip);
      expect(await screen.findByRole('tooltip')).toHaveTextContent('来源：');
    }
  });

  it('不存在的日期：显示错误并给出回到最新一期的链接', async () => {
    renderAt('/daily-reports/2020-01-01');
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '查看最新一期日报 ›' }).getAttribute('href')).toBe('/daily-reports');
  });
});
