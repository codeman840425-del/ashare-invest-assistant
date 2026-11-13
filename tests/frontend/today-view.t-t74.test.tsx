/**
 * T-T74：today 页空态与缺口展示，按契约 16 条 G/W/T 先写红。
 *
 * 契约：git show 1c10a10:docs/contracts/today-view.md（§4 的 16 条）；补充裁定 git show 838b121:docs/contracts/today-view.md（docs/T-A139 新头，§7 的 12 条）。未合入 docs。
 * S3-7 编排者批准同步：17:30–17:45 不提前显示缺口；逾时阈值 = REPORT_EXPECTED_AT + 15 分钟（默认 17:45）；缺口区显示代码和名称；
 * 时间按 Asia/Shanghai（含浏览器时区非上海的用例）；未知 code 兜底。
 *
 * 禁用 skip / todo / xfail。断言失败信息带「缺实现：…」，避免被当成用例写错。
 * 只 mock fetch，禁止真实网络；麦蕊 0 次。不改前端目录。
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, waitFor } from '@testing-library/react';
import { existsSync, realpathSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { useEffect, type ReactNode } from 'react';
import { MemoryRouter } from 'react-router';

import { clearEtagCache } from '@/api/client';
import type { DailyReport, SuggestionSummary, TerminalRow, TodayResponse } from '@/api/types';
import { TodayPage } from '@/pages/today/TodayPage';

const EMPTY = { items: [] as never[], more: false };
const TRADE_DATE = '2026-11-10';
/** 北京 10:00 */
const TIME_1000 = '2026-11-10T02:00:00Z';
/** 北京 17:20 */
const TIME_1720 = '2026-11-10T09:20:00Z';
/** 北京 17:40 */
const TIME_1740 = '2026-11-10T09:40:00Z';
/** 北京 18:40（日报已生成窗口） */
const TIME_1840 = '2026-11-10T10:40:00Z';
/** 北京 18:44（保留原场景，已过默认逾时阈值，S5） */
const TIME_1844 = '2026-11-10T10:44:00Z';
/** 北京 18:45（保留原场景，已过默认逾时阈值，S5） */
const TIME_1845 = '2026-11-10T10:45:00Z';
/** 北京 18:50（S5 逾时，默认阈值之后） */
const TIME_1850 = '2026-11-10T10:50:00Z';
/** 北京 17:44（默认 REPORT_EXPECTED_AT=17:30，逾时 17:45 前 1 分钟） */
const TIME_1744 = '2026-11-10T09:44:00Z';
/** 北京 17:45（默认逾时阈值） */
const TIME_1745 = '2026-11-10T09:45:00Z';
/** 北京 14:59:59（交易日 15:00 前，不显示 R2） */
const TIME_145959 = '2026-11-10T06:59:59Z';
/** 北京 15:00:00（S4 起点，仍不显示 R2） */
const TIME_150000 = '2026-11-10T07:00:00Z';
/** 北京 19:10（逾时后仍 generating → S4） */
const TIME_1910 = '2026-11-10T11:10:00Z';

const S1 = '还没有导入持仓，导入后才能生成你的日报。';
const S2 = '当前没有持仓，日报只覆盖你的自选。';
const S3 = '今天休市，没有新的日报。';
const S4 = '盘后数据准备中，日报约 17:30 生成。';
const S4_HINT = '候选信号已更新。';
const S5 = '今日日报还没有生成，请稍后再看。';
const S6 = '今日行情数据未就绪，本日报未做策略分析。';
const S7 = '行情数据源尚未开通，本日报未做策略分析。';
const S8 = '今日盘后分析没有完成记录。';
const R2 = '今天没有新的候选信号。';
const A1 = '暂时算不出账户总览（缺持仓价格或现金）。';
const COPY_BARS_MISSING = '今日缺少日 K 数据，未参与分析。';
const COPY_SOURCE_MISSING = '未进入今日数据快照，未参与分析。';
const COPY_NOT_ELIGIBLE = '该证券不在分析范围内（仅支持上市股票）。';
const COPY_NO_INSTANCES = '还没有启用中的策略实例。';
const COPY_UNKNOWN = '部分数据暂不可用。';
const COPY_MORE = (n: number) => `等 ${n} 只`;
const COPY_USER_INPUT = '有信息待补录。';
const COPY_CASH = '未录入现金';
const COPY_REPORT_FAIL = '日报详情暂时读取失败，分析缺口稍后显示。';


function missing(detail: string): string {
  return `缺实现：${detail}`;
}

function emptyToday(over: Partial<TodayResponse> = {}): TodayResponse {
  return {
    server_time: TIME_1000,
    trade_date: TRADE_DATE,
    session: 'closed',
    market: { regime: null, regime_position_range: null, data_status: 'fresh' },
    focus: EMPTY,
    pending_plan_drafts: EMPTY,
    released_reasons: EMPTY,
    risk_flags: EMPTY,
    invalidations_today: EMPTY,
    daily_report: { date: TRADE_DATE, status: 'not_yet' },
    reconciliation: { status: 'matched', as_of: null, diff_count: 0, important_count: 0 },
    unread_notifications: 0,
    alerts: EMPTY,
    plan_triggers: EMPTY,
    data_gaps: EMPTY,
    evidence: [],
    ...over,
  };
}

function holdingRow(code: string, name: string, suggestion: SuggestionSummary | null = null): TerminalRow {
  return {
    security_code: code,
    name,
    in_watchlist: false,
    focus: true,
    quote: null,
    holding: {
      qty: '100',
      sellable_qty: '100',
      cost_price: '10.00',
      weight_pct: '12.5',
      pnl: null,
      pnl_pct: null,
      security_type: 'stock',
      estimated: false,
    },
    suggestion,
    active_reason_count: 0,
    max_risk_level: null,
    data_status: 'fresh',
    data_as_of: null,
  };
}

function nameOnlyRow(code: string, name: string): TerminalRow {
  return {
    ...holdingRow(code, name),
    holding: null,
    focus: false,
  };
}

function suggestion(): SuggestionSummary {
  return {
    id: '00000000-0000-4000-8000-000000000099',
    created_at: '2026-11-10T17:31:00+08:00',
    status: 'active',
    consensus: 'single',
    actions: [
      {
        strategy_key: 'demo',
        strategy_name: '示例策略',
        action: 'hold',
        t_leg: null,
        lifecycle: 'published',
      },
    ],
    executability_status: 'not_applicable',
    divergent_dimensions: [],
    top_score: 50,
  };
}

function emptyReport(over: Partial<DailyReport> = {}): DailyReport {
  return {
    data_status: 'fresh',
    data_as_of: '2026-11-10T17:30:00+08:00',
    date: TRADE_DATE,
    generated_at: '2026-11-10T18:30:00+08:00',
    account_id: '00000000-0000-4000-8000-000000000001',
    market: { regime: null, regime_position_range: null, breadth: null, summary: [] },
    account: {
      total_assets: '100000.00',
      cash: '20000.00',
      position_pct: '12.5',
      pnl_day: '10.00',
      position_vs_regime: 'within',
    },
    reconciliation: { status: 'matched', as_of: null, diff_count: 0, important_count: 0 },
    stocks: [],
    pending: { plan_drafts: 0, active_reasons: 0 },
    explanation: { source: 'template', text: '示例', llm_call_id: null },
    evidence: [],
    gaps: [],
    ...over,
  };
}

function pipelineGap(key: string): DailyReport['gaps'][number] {
  return { key, reason: 'no_source', message: key };
}

function cashTodayGap(message = '未录入现金。'): TodayResponse['data_gaps']['items'][number] {
  return {
    key: 'cash',
    reason: 'user_input_missing',
    scope: 'account',
    dataset: null,
    message,
    security_count: 0,
    securities: [],
    since: null,
    route: '/portfolio/import',
  };
}

function countIn(text: string, snippet: string): number {
  if (!snippet) return 0;
  return text.split(snippet).length - 1;
}

type FetchPlan = {
  today: TodayResponse;
  report?: DailyReport | 'absent';
};

const reportUrls: string[] = [];
const allUrls: string[] = [];

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.toString();
  if (typeof Request !== 'undefined' && input instanceof Request) return input.url;
  return String(input);
}

function installFetch(plan: FetchPlan): void {
  reportUrls.length = 0;
  allUrls.length = 0;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = requestUrl(input);
    allUrls.push(`${init?.method ?? 'GET'} ${url}`);
    const path = url.replace(/^https?:\/\/[^/]+/, '');
    if (path.includes('/watchlist') && !path.includes('/watchlist/')) {
      return json({ items: [], caps: { watchlist: 100, focus: 20 } });
    }
    if (path.includes('/daily-reports/')) {
      reportUrls.push(path);
      if (!plan.report || plan.report === 'absent') {
        return json(
          { error: { code: 'NOT_FOUND', message: 'not found', details: null, request_id: 'tt74' } },
          404,
        );
      }
      return json(plan.report);
    }
    if (path.includes('/today') && !path.includes('/daily-reports/')) {
      return json(plan.today);
    }
    throw new Error(`前端单测禁止真实网络请求：${url}`);
  });
}

function Providers({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 0, gcTime: 0 } },
  });
  // 卸载时取消未完成查询，避免测试间泄漏。
  useEffect(() => () => client.clear(), [client]);
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

async function renderToday(plan: FetchPlan) {
  installFetch(plan);
  render(
    <Providers>
      <TodayPage />
    </Providers>,
  );
  await waitFor(
    () => {
      const page = document.querySelector('[data-testid="today-page"]');
      if (!page) {
        const err = document.querySelector('.error-box, [data-testid="error-box"], .page-scroll')?.textContent ?? bodyText().slice(0, 400);
        throw new Error(missing(`TodayPage 未能完成渲染（未出现 data-testid=today-page）。当前页：${err}；已请求：${allUrls.join(' | ') || '无'}`));
      }
    },
    { timeout: 5000 },
  );
  const st = plan.today.daily_report.status;
  const hasHold = plan.today.focus.items.some((r) => r.holding != null);
  const isS1 = plan.today.reconciliation.status === 'not_imported' && !hasHold;
  const isS3 = plan.today.session === 'non_trading_day';
  // 契约 §1：partial 也算 ready 才请求日报；838b121 §7②：S1/S3 即使 ready 也不请求。
  if ((st === 'ready' || st === 'partial') && !isS1 && !isS3) {
    await waitFor(
      () => {
        if (!reportUrls.length) {
          throw new Error(
            missing(`daily_report.status=${st} 时应请求 /daily-reports/${plan.today.daily_report.date}（契约 §1）`),
          );
        }
      },
      { timeout: 3000 },
    );
  }
}

function bodyText(): string {
  return document.body.textContent ?? '';
}

/**
 * 「数据缺口」区：契约 1c10a10 未规定 testid。
 * 优先 T-F34 分析缺口列表 today-report-gaps，其次既有区块 today-data-gaps / aria-label=数据缺口。
 * 只在此范围内计数证券代码，避免把重点关注表里的代码算进去。
 */
function gapArea(): HTMLElement {
  const el = (document.querySelector('[data-testid="today-report-gaps"]')
    ?? document.querySelector('[data-testid="today-data-gaps"]')
    ?? document.querySelector('[aria-label="数据缺口"]')) as HTMLElement | null;
  if (!el) {
    throw new Error(missing('未找到「数据缺口」区（优先 today-report-gaps，其次既有 today-data-gaps / aria-label=数据缺口；契约未规定 testid）'));
  }
  return el;
}

/** 缺口行：只在缺口区内找，优先 li/tr（含代码、名称与文案）。 */
function gapRowEl(contains: (text: string) => boolean): HTMLElement | undefined {
  const area = document.querySelector('[data-testid="today-report-gaps"]')
    ?? document.querySelector('[data-testid="today-data-gaps"]')
    ?? document.querySelector('[aria-label="数据缺口"]');
  if (!area) return undefined;
  const nodes = [...area.querySelectorAll('li, tr, p, span, div, section')].filter((el) => contains(el.textContent ?? ''));
  const leaf = nodes.sort((a, b) => (a.textContent?.length ?? 9_999) - (b.textContent?.length ?? 9_999))[0] as HTMLElement | undefined;
  if (!leaf) return undefined;
  return (leaf.closest('li, tr') as HTMLElement | null) ?? leaf;
}

interface TodayViewApi {
  REPORT_EXPECTED_AT: string;
  REPORT_OVERDUE_GRACE_MIN?: number;
  overdueAt?: (expectedAt?: string) => string;
  preReportState: (t: TodayResponse, expectedAt?: string) => string | null;
  s4Text?: (expectedAt?: string) => string;
}

async function loadTodayView(): Promise<TodayViewApi> {
  // 运行时按文件探测，避免 Vite 在 bcf9bcb（尚无该模块）变换阶段就把整份用例打掉。
  // 叠加对照时优先 process.cwd() 上级（对照头 src），再回退到本文件相对路径。
  const candidates: string[] = [];
  if (process.env.TT74_REPO_ROOT) {
    candidates.push(path.resolve(process.env.TT74_REPO_ROOT, 'src/frontend/src/pages/today/todayView.ts'));
  }
  candidates.push(path.resolve(process.cwd(), '../src/frontend/src/pages/today/todayView.ts'));
  try {
    candidates.push(fileURLToPath(new URL('../../src/frontend/src/pages/today/todayView.ts', import.meta.url)));
  } catch {
    /* vitest worker 里 import.meta.url 可能不是 file:，忽略 */
  }
  const file = candidates.find((c) => existsSync(c));
  if (!file) {
    throw new Error(missing('未提供 pages/today/todayView.ts（REPORT_EXPECTED_AT / overdueAt；编排者裁定逾时 = REPORT_EXPECTED_AT+15 分钟）'));
  }
  try {
    const href = pathToFileURL(realpathSync(file)).href;
    return await import(/* @vite-ignore */ href) as unknown as TodayViewApi;
  } catch (e) {
    throw new Error(missing(`无法加载 todayView（REPORT_EXPECTED_AT / overdueAt）：${String(e)}`));
  }
}

function expectText(snippet: string, why: string): void {
  expect(bodyText().includes(snippet), why).toBe(true);
}

function expectNoText(snippet: string, why: string): void {
  expect(bodyText().includes(snippet), why).toBe(false);
}

function expectNoDailyReportFetch(why: string): void {
  expect(reportUrls, why).toEqual([]);
}

function expectImportLink(why: string): void {
  const link = document.querySelector('a[href="/portfolio/import"]');
  expect(link, why).toBeTruthy();
  expect(link?.textContent ?? '', why).toMatch(/导入交割单/);
}

beforeAll(() => {
  if (!('ResizeObserver' in window)) {
    class RO {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    Object.defineProperty(window, 'ResizeObserver', { writable: true, value: RO });
    Object.defineProperty(globalThis, 'ResizeObserver', { writable: true, value: RO });
  }
});

beforeEach(() => {
  reportUrls.length = 0;
  allUrls.length = 0;
  clearEtagCache();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  clearEtagCache();
});

describe('T-T74 today 页验收（1c10a10 §4，16 条 + 通用断言与逾时边界）', () => {
  it('1. S1 未导入持仓：状态条文案、导入入口，不请求日报', async () => {
    await renderToday({
      today: emptyToday({
        reconciliation: { status: 'not_imported', as_of: null, diff_count: 0, important_count: 0 },
        focus: EMPTY,
        daily_report: { date: TRADE_DATE, status: 'not_yet' },
      }),
    });
    expectText(S1, missing('S1 状态条未显示「还没有导入持仓…」（契约 §2.1 / 用例 1）'));
    expectImportLink(missing('S1 应有指向 /portfolio/import 的「导入交割单」（契约用例 1）'));
    expectNoDailyReportFetch(missing('S1 在 daily_report.status 非 ready 时不得请求 /daily-reports/（契约 §1、用例 1）'));
  });

  it('2. S2 已导入但无持仓', async () => {
    await renderToday({
      today: emptyToday({
        reconciliation: { status: 'matched', as_of: null, diff_count: 0, important_count: 0 },
        focus: { items: [nameOnlyRow('000001.SZ', '示例甲')], more: false },
      }),
    });
    expectText(S2, missing('S2 未显示「当前没有持仓，日报只覆盖你的自选。」（契约 §2.1 / 用例 2）'));
  });

  it('3. S3 非交易日，不请求日报', async () => {
    await renderToday({
      today: emptyToday({
        session: 'non_trading_day',
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
        server_time: TIME_1720,
        daily_report: { date: TRADE_DATE, status: 'not_yet' },
      }),
    });
    expectText(S3, missing('S3 未显示「今天休市，没有新的日报。」（契约 §2.1 / 用例 3）'));
    expectNoDailyReportFetch(missing('S3 不得请求 /daily-reports/（契约 §1、用例 3）'));
  });

  it('4. 北京 17:20、status=not_yet → S4，不请求日报，不提前显示缺口', async () => {
    await renderToday({
      today: emptyToday({
        session: 'closed',
        server_time: TIME_1720,
        daily_report: { date: TRADE_DATE, status: 'not_yet' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
    });
    expectText(S4, missing('S4 未显示「盘后数据准备中，日报约 17:30 生成。」（契约 §2.1 / §3 / 用例 4；17:30–17:45 不提前显示缺口）'));
    expectNoText(COPY_BARS_MISSING, missing('17:30–17:45 窗口不得提前显示分析缺口（契约 §3、用例 4）'));
    expectNoDailyReportFetch(missing('S4 在 status 非 ready 时不得请求 /daily-reports/（契约 §1、用例 4）'));
  });

  it('5. 北京 17:40、not_yet、有候选信号 → S4 并带「候选信号已更新。」', async () => {
    await renderToday({
      today: emptyToday({
        session: 'closed',
        server_time: TIME_1740,
        daily_report: { date: TRADE_DATE, status: 'not_yet' },
        focus: { items: [holdingRow('000001.SZ', '示例甲', suggestion())], more: false },
      }),
    });
    expectText(S4, missing('S4 文案未显示（契约用例 5）'));
    expectText(S4_HINT, missing('S4 在 focus 已有候选信号时应追加「候选信号已更新。」（契约 §2.1 / §3 / 用例 5）'));
    expectNoDailyReportFetch(missing('17:30–17:45 且 status 非 ready 时不得请求 /daily-reports/（契约 §3、用例 5）'));
  });

  it('6. 北京 18:50、status=not_yet → S5', async () => {
    await renderToday({
      today: emptyToday({
        session: 'closed',
        server_time: TIME_1850,
        daily_report: { date: TRADE_DATE, status: 'not_yet' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
    });
    expectText(S5, missing('S5 未显示「今日日报还没有生成，请稍后再看。」（契约 §2.1 / §3：逾时 = REPORT_EXPECTED_AT+15 分钟，默认 17:45；用例 6）'));
    expectNoDailyReportFetch(missing('S5 时 status 仍为 not_yet，不得请求 /daily-reports/（契约 §1、用例 6）'));
  });

  it('6b. 默认逾时边界：北京 17:44、not_yet 仍为 S4，不出 S5', async () => {
    await renderToday({
      today: emptyToday({
        session: 'closed',
        server_time: TIME_1744,
        daily_report: { date: TRADE_DATE, status: 'not_yet' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
    });
    expectText(S4, missing('默认 REPORT_EXPECTED_AT=17:30 时，逾时阈值为 17:45；17:44 仍应显示 S4'));
    expectNoText(S5, missing('17:44（阈值前 1 分钟）不得显示 S5'));
    expectNoDailyReportFetch(missing('17:44 且 status 非 ready 时不得请求 /daily-reports/'));
  });

  it('6b补充. 原北京 18:44、not_yet 场景 → S5', async () => {
    await renderToday({
      today: emptyToday({
        session: 'closed',
        server_time: TIME_1844,
        daily_report: { date: TRADE_DATE, status: 'not_yet' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
    });
    expectText(S5, missing('18:44 已过默认逾时阈值 17:45，应显示 S5'));
    expectNoText(S4, missing('18:44、not_yet 不得显示 S4'));
    expectNoDailyReportFetch(missing('18:44 且 status 非 ready 时不得请求 /daily-reports/'));
  });

  it('6c新增. 默认逾时边界：北京 17:45、not_yet → S5（含边界）', async () => {
    await renderToday({
      today: emptyToday({
        session: 'closed',
        server_time: TIME_1745,
        daily_report: { date: TRADE_DATE, status: 'not_yet' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
    });
    expectText(S5, missing('17:45 为默认逾时阈值（17:30 + 15 分钟），含边界，应显示 S5'));
    expectNoDailyReportFetch(missing('S5 时 status 仍为 not_yet，不得请求 /daily-reports/'));
  });

  it('6c. 原北京 18:45、not_yet 场景 → S5', async () => {
    await renderToday({
      today: emptyToday({
        session: 'closed',
        server_time: TIME_1845,
        daily_report: { date: TRADE_DATE, status: 'not_yet' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
    });
    expectText(S5, missing('18:45 已过默认逾时阈值（REPORT_EXPECTED_AT 17:30 + 15 分钟），应显示 S5'));
    expectNoDailyReportFetch(missing('S5 时 status 仍为 not_yet，不得请求 /daily-reports/'));
  });

  it('7. 浏览器时区为 America/Denver 时仍按 Asia/Shanghai 判定 S4', async () => {
    const RealDTF = Intl.DateTimeFormat;
    // 必须是可被 `new` 的函数；箭头函数不是 constructor，会把页面打挂。
    const spy = vi.spyOn(Intl, 'DateTimeFormat').mockImplementation(function DenverDTF(
      this: unknown,
      locales?: Intl.LocalesArgument,
      options?: Intl.DateTimeFormatOptions,
    ) {
      return new RealDTF(locales, { timeZone: 'America/Denver', ...options });
    } as unknown as typeof Intl.DateTimeFormat);
    try {
      await renderToday({
        today: emptyToday({
          session: 'closed',
          server_time: TIME_1720, // 09:20Z = 北京 17:20，丹佛 02:20
          daily_report: { date: TRADE_DATE, status: 'not_yet' },
          focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
        }),
      });
      expectText(
        S4,
        missing('判定时段必须用 Intl.DateTimeFormat 并显式指定 timeZone=Asia/Shanghai，不得用浏览器本地时区（契约 §2、用例 7）'),
      );
      expectNoDailyReportFetch(missing('用例 7 与 S4 相同，不得请求 /daily-reports/'));
      const usedShanghai = spy.mock.calls.some(([, opts]) => opts?.timeZone === 'Asia/Shanghai');
      expect(
        usedShanghai,
        missing('未调用 Intl.DateTimeFormat(..., { timeZone: "Asia/Shanghai" })（契约 §2）'),
      ).toBe(true);
    } finally {
      spy.mockRestore();
    }
  });

  it('8. ready + pipeline.daily_bars_not_ready → S6，页面不出现原始 code', async () => {
    await renderToday({
      today: emptyToday({
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
      report: emptyReport({
        gaps: [pipelineGap('pipeline.daily_bars_not_ready')],
      }),
    });
    expectText(S6, missing('S6 未显示「今日行情数据未就绪，本日报未做策略分析。」（契约 §2.1 / 用例 8）'));
    expectNoText('daily_bars_not_ready', missing('页面文本不得出现 daily_bars_not_ready 原始 code（契约 §1、用例 8）'));
  });

  it('9. pipeline.owned_market_cache_adapter_missing → S7', async () => {
    await renderToday({
      today: emptyToday({
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
      report: emptyReport({
        gaps: [pipelineGap('pipeline.owned_market_cache_adapter_missing')],
      }),
    });
    expectText(S7, missing('S7 未显示「行情数据源尚未开通，本日报未做策略分析。」（契约 §2.1 / 用例 9）'));
    expectNoText('owned_market_cache_adapter_missing', missing('页面不得出现 owned_market_cache_adapter_missing 原始 code（契约 §1）'));
  });

  it('10. 同一证券两条 pipeline 缺口合并为一行，显示代码+名称与两句文案，无 pipeline 字样', async () => {
    await renderToday({
      today: emptyToday({
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
        focus: { items: [holdingRow('000002.SZ', '示例乙')], more: false },
      }),
      report: emptyReport({
        gaps: [
          pipelineGap('pipeline.daily_bars_missing:000002.SZ'),
          pipelineGap('pipeline.owned_source_security_missing:000002.SZ'),
        ],
      }),
    });
    expectText(COPY_BARS_MISSING, missing('应显示 daily_bars_missing 文案「今日缺少日 K 数据，未参与分析。」（契约 §2.3 / 用例 10）'));
    expectText(COPY_SOURCE_MISSING, missing('应显示 owned_source_security_missing 文案「未进入今日数据快照，未参与分析。」（契约 §2.3 / 用例 10）'));
    expectNoText('pipeline.', missing('页面不得出现 pipeline 字样（契约用例 10）'));
    // 收窄到缺口区，不把重点关注表里的 000002.SZ 算进去。
    const area = gapArea();
    const gapEl = gapRowEl((s) => s.includes(COPY_BARS_MISSING) && s.includes(COPY_SOURCE_MISSING));
    expect(gapEl, missing('同一证券的两条缺口应出现在同一缺口行/区（契约 §2 / 用例 10）')).toBeTruthy();
    expect(area.contains(gapEl!), missing('缺口行必须位于「数据缺口」区内，而不是重点关注表（用例 10）')).toBe(true);
    const gapText = gapEl?.textContent ?? '';
    expect(gapText.includes('000002.SZ'), missing('缺口区应显示证券代码 000002.SZ（契约 U3 / 用例 10）')).toBe(true);
    expect(gapText.includes('示例乙'), missing('缺口区应显示证券名称（契约 U3：显示代码和名称；用例 10）')).toBe(true);
    const first = gapText.indexOf('000002.SZ');
    const last = gapText.lastIndexOf('000002.SZ');
    expect(
      first !== -1 && last === first,
      missing('同一证券的多条缺口应合并为「数据缺口」区一行（契约 §2 / 用例 10）'),
    ).toBe(true);
    const areaCodes = area.textContent?.split('000002.SZ').length ?? 1;
    expect(areaCodes - 1, missing('缺口区内 000002.SZ 只应出现一次（按证券合并为一行）')).toBe(1);
  });

  it('11. pipeline.security_not_eligible → 范围外文案，无操作按钮', async () => {
    await renderToday({
      today: emptyToday({
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
        focus: { items: [holdingRow('510000.SH', '示例基金')], more: false },
      }),
      report: emptyReport({
        gaps: [pipelineGap('pipeline.security_not_eligible:510000.SH')],
      }),
    });
    expectText(COPY_NOT_ELIGIBLE, missing('应显示「该证券不在分析范围内（仅支持上市股票）。」（契约 §2.3 / 用例 11）'));
    const row11 = gapRowEl((s) => s.includes(COPY_NOT_ELIGIBLE));
    expect(row11, missing('范围外文案应出现在缺口行（契约用例 11）')).toBeTruthy();
    expect((row11?.textContent ?? '').includes('510000.SH'), missing('缺口区应显示代码（契约 U3 / 用例 11）')).toBe(true);
    expect((row11?.textContent ?? '').includes('示例基金'), missing('缺口区应显示名称（契约 U3 / 用例 11）')).toBe(true);
    const ops = row11?.querySelectorAll('a[href="/strategy-instances"], a[href="/portfolio/import"], button') ?? [];
    expect(ops.length, missing('security_not_eligible 不可操作，不得出现操作按钮或策略/导入入口（契约 §2.3 / 用例 11）')).toBe(0);
  });

  it('12. pipeline.active_instances_missing → 文案且有 /strategy-instances 入口', async () => {
    await renderToday({
      today: emptyToday({
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
      report: emptyReport({
        gaps: [pipelineGap('pipeline.active_instances_missing')],
      }),
    });
    expectText(COPY_NO_INSTANCES, missing('应显示「还没有启用中的策略实例。」（契约 §2.3 / 用例 12）'));
    const link = document.querySelector('a[href="/strategy-instances"]');
    expect(link, missing('active_instances_missing 应有指向 /strategy-instances 的入口（契约 §2.3 / 用例 12）')).toBeTruthy();
  });

  it('13. 未知 pipeline code 显示兜底文案，不显示原始 code', async () => {
    await renderToday({
      today: emptyToday({
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
      report: emptyReport({
        gaps: [pipelineGap('pipeline.unknown_future_code:000001.SZ')],
      }),
    });
    expectText(COPY_UNKNOWN, missing('未知 code 应显示兜底文案「部分数据暂不可用。」（契约 §1、§2.3 / 用例 13）'));
    expectNoText('unknown_future_code', missing('未知 code 不得在页面显示原始 code（契约 §1 / 用例 13）'));
    const gap13 = gapRowEl((s) => s.includes(COPY_UNKNOWN));
    expect(gap13, missing('兜底文案应出现在缺口区（契约用例 13）')).toBeTruthy();
    expect((gap13?.textContent ?? '').includes('000001.SZ'), missing('缺口区仍应显示证券代码（契约 U3 / 用例 13）')).toBe(true);
    expect((gap13?.textContent ?? '').includes('示例甲'), missing('缺口区仍应显示证券名称（契约 U3 / 用例 13）')).toBe(true);
  });

  it('14. 日报 account 为 null + cash 缺口去向导入页 → A1 与「去补录 ›」', async () => {
    await renderToday({
      today: emptyToday({
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
        data_gaps: {
          items: [
            {
              key: 'user_input_missing:cash',
              reason: 'user_input_missing',
              scope: 'account',
              dataset: null,
              message: '未录入现金',
              security_count: 0,
              securities: [],
              since: null,
              route: '/portfolio/import',
            },
          ],
          more: false,
        },
      }),
      report: emptyReport({ account: null }),
    });
    expectText(A1, missing('应显示 A1「暂时算不出账户总览（缺持仓价格或现金）。」（契约 §2.2 / 用例 14）'));
    expectText('去补录 ›', missing('data_gaps 有去向导入页的项时应显示「去补录 ›」（契约 §2.2 / 用例 14）'));
    const link = [...document.querySelectorAll('a')].find((a) => (a.getAttribute('href') ?? '') === '/portfolio/import' && (a.textContent ?? '').includes('去补录'));
    expect(link, missing('「去补录 ›」应指向 /portfolio/import（契约用例 14）')).toBeTruthy();
  });

  it('15. account 非空且 pnl_day 为 null → 日盈亏显示「—」，不显示 0', async () => {
    await renderToday({
      today: emptyToday({
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
      report: emptyReport({
        account: {
          total_assets: '100000.00',
          cash: '20000.00',
          position_pct: '12.5',
          pnl_day: null,
          position_vs_regime: 'within',
        },
        gaps: [],
      }),
    });
    const text = bodyText();
    // 必须用契约用词「日盈亏」定位，避免误匹配免责声明里的「盈亏自负」或涨跌幅「—」。
    expect(text.includes('日盈亏'), missing('应展示账户总览「日盈亏」（契约 §2.2 A2 / 用例 15）')).toBe(true);
    const pnlChunk = text.match(/日盈亏[\s\S]{0,24}/)?.[0] ?? '';
    expect(pnlChunk.includes('—'), missing('pnl_day 为 null 时日盈亏应显示「—」（契约 §2.2 A2 / 用例 15）')).toBe(true);
    expect(
      !/日盈亏[\s\S]{0,24}(?:0\.00|\b0\b)/.test(text),
      missing('pnl_day 为 null 时不得把日盈亏显示为 0（契约 §2.2 A2 / 用例 15）'),
    ).toBe(true);
  });

  it('16. S9 且无候选信号 → R2 文案；无「买入」「卖出」；card-disclaimer 可见', async () => {
    await renderToday({
      today: emptyToday({
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
        focus: { items: [holdingRow('000001.SZ', '示例甲', null)], more: false },
      }),
      report: emptyReport({ gaps: [] }),
    });
    expectText(R2, missing('S9 且无候选信号时应显示「今天没有新的候选信号。」（契约 §2.2 R2 / 用例 16）'));
    expectNoText('买入', missing('页面文本不得含「买入」（契约 §2.2 用词约束 / 用例 16）'));
    expectNoText('卖出', missing('页面文本不得含「卖出」（契约 §2.2 用词约束 / 用例 16）'));
    const disc = document.querySelector('[data-testid="card-disclaimer"]');
    expect(disc, missing('CardDisclaimer（card-disclaimer）必须可见（契约 §2.2 R1/R2 / 用例 16）')).toBeTruthy();
    expect((disc as HTMLElement | null)?.offsetParent !== null || (disc?.textContent ?? '').length > 0, missing('card-disclaimer 必须可见（契约用例 16）')).toBe(true);
  });

  it('通用：缺口区超过 10 只证券时显示「等 N 只」', async () => {
    const rows: TerminalRow[] = [];
    const gaps: DailyReport['gaps'] = [];
    for (let i = 0; i < 12; i += 1) {
      const code = `6000${String(10 + i).padStart(2, '0')}.SH`;
      const name = `示例股${i + 1}`;
      rows.push(holdingRow(code, name));
      gaps.push(pipelineGap(`pipeline.daily_bars_missing:${code}`));
    }
    await renderToday({
      today: emptyToday({
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
        focus: { items: rows, more: false },
      }),
      report: emptyReport({ gaps }),
    });
    const moreArea = gapArea();
    expect(moreArea.textContent?.includes(COPY_MORE(2)), missing('缺口区最多 10 只，其余应显示「等 2 只」（契约 §2 展示位置 / 通用断言）')).toBe(true);
  });

  it('通用：逾时阈值由 REPORT_EXPECTED_AT + 15 分钟推导（默认 17:30 → 17:45，保留显式 18:30 参数）', async () => {
    const view = await loadTodayView();
    expect(view.REPORT_EXPECTED_AT, missing('应导出 REPORT_EXPECTED_AT，默认 17:30')).toBe('17:30');
    expect(view.REPORT_OVERDUE_GRACE_MIN, missing('应导出 REPORT_OVERDUE_GRACE_MIN=15（编排者裁定：逾时 = REPORT_EXPECTED_AT+15 分钟）')).toBe(15);
    expect(typeof view.overdueAt, missing('应导出 overdueAt()，由 expectedAt + 15 分钟推导逾时阈值，不得写死 18:45')).toBe('function');
    expect(view.overdueAt!('18:30'), missing('REPORT_EXPECTED_AT=18:30 时逾时应为 18:45')).toBe('18:45');
    expect(view.overdueAt!('17:30'), missing('REPORT_EXPECTED_AT 改为 17:30 时逾时应为 17:45，不得仍为 18:45')).toBe('17:45');
    if (view.s4Text) {
      expect(view.s4Text('17:30'), missing('S4 文案应随 REPORT_EXPECTED_AT 变为「日报约 17:30 生成。」')).toBe('盘后数据准备中，日报约 17:30 生成。');
    }
    const base = emptyToday({
      session: 'closed',
      daily_report: { date: TRADE_DATE, status: 'not_yet' },
      focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
    });
    expect(
      view.preReportState({ ...base, server_time: TIME_1744 }, '17:30'),
      missing('默认 17:30+15=17:45 时，17:44 应仍为 S4，不得出 S5'),
    ).toBe('S4');
    expect(
      view.preReportState({ ...base, server_time: TIME_1745 }, '17:30'),
      missing('默认 17:30+15=17:45 时，17:45 含边界应出 S5'),
    ).toBe('S5');
  });

  // ---------- 838b121 §7 补充裁定（12 条 + ③ 的 15:00 边界） ----------

  it('§7① 北京 18:40、not_yet → S5（已过默认逾时阈值 17:45）', async () => {
    await renderToday({
      today: emptyToday({
        session: 'closed',
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'not_yet' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
    });
    expectText(S5, missing('北京 18:40、not_yet 已过默认逾时阈值，应显示 S5（§9.1 17:30 链）'));
    expectNoText(S4, missing('18:40 已过逾时阈值，not_yet 不得显示 S4'));
    expectNoDailyReportFetch(missing('18:40 且 status 非 ready 时不得请求 /daily-reports/'));
  });

  it('§7① 北京 19:10、generating → S4，不显示 S5', async () => {
    await renderToday({
      today: emptyToday({
        session: 'closed',
        server_time: TIME_1910,
        daily_report: { date: TRADE_DATE, status: 'generating' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
    });
    expectText(S4, missing('逾时之后仍为 generating 时应显示 S4（契约 838b121 §7①）'));
    expectNoText(S5, missing('generating 即使已过逾时阈值也不得显示 S5（契约 838b121 §7①）'));
  });

  it('§7② S3 且 status=ready 时不请求日报，没有 today-account', async () => {
    await renderToday({
      today: emptyToday({
        session: 'non_trading_day',
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
      report: emptyReport(),
    });
    expectText(S3, missing('S3 应显示「今天休市，没有新的日报。」（契约 838b121 §7②）'));
    expectNoDailyReportFetch(missing('S3 即使 status 为 ready 也不得请求 /daily-reports/（契约 838b121 §7②）'));
    expect(document.querySelector('[data-testid="today-account"]'), missing('S3 不得显示 today-account / A1/A2（契约 838b121 §7②）')).toBeNull();
  });

  it('§7③ 北京 10:00、not_yet、无候选信号 → 不显示 R2', async () => {
    await renderToday({
      today: emptyToday({
        session: 'morning',
        server_time: TIME_1000,
        daily_report: { date: TRADE_DATE, status: 'not_yet' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
    });
    expectNoText(R2, missing('交易日 15:00 前、status 尚未 ready 时不得显示「今天没有新的候选信号。」（契约 838b121 §7③）'));
  });

  it('§7③ 边界：北京 14:59:59、not_yet、无候选信号 → 不显示 R2，也不显示 S4', async () => {
    await renderToday({
      today: emptyToday({
        session: 'afternoon',
        server_time: TIME_145959,
        daily_report: { date: TRADE_DATE, status: 'not_yet' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
    });
    expectNoText(R2, missing('14:59:59（15:00 前 1 秒）不得显示 R2（契约 838b121 §7③；编排者要求边界例）'));
    expectNoText(S4, missing('14:59:59 尚未到 15:00，不得显示 S4'));
  });

  it('§7③ 边界：北京 15:00:00、not_yet、无候选信号 → 显示 S4，不显示 R2', async () => {
    await renderToday({
      today: emptyToday({
        session: 'closed',
        server_time: TIME_150000,
        daily_report: { date: TRADE_DATE, status: 'not_yet' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
    });
    expectText(S4, missing('15:00:00 起应显示 S4（契约 838b121 §7①/③ 边界）'));
    expectNoText(R2, missing('15:00:00 为 S4，R2 只在 S9 时显示（契约 838b121 §7③）'));
  });

  it('§7③ S2、无候选信号 → 不显示 R2', async () => {
    await renderToday({
      today: emptyToday({
        reconciliation: { status: 'matched', as_of: null, diff_count: 0, important_count: 0 },
        focus: { items: [nameOnlyRow('000001.SZ', '示例甲')], more: false },
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
      }),
      report: emptyReport(),
    });
    expectText(S2, missing('应显示 S2（契约 838b121 §7③）'));
    expectNoText(R2, missing('S2 不得显示 R2（契约 838b121 §7③）'));
  });

  it('§7④ 未知 code 且参数为合法证券代码 → 归到该证券行，只显示兜底文案', async () => {
    await renderToday({
      today: emptyToday({
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
      report: emptyReport({
        gaps: [pipelineGap('pipeline.future_x:000001.SZ')],
      }),
    });
    expectText(COPY_UNKNOWN, missing('未知 code 应显示兜底文案「部分数据暂不可用。」（契约 838b121 §7④）'));
    const row = gapRowEl((s) => s.includes(COPY_UNKNOWN));
    expect(row, missing('兜底文案应出现在缺口行（契约 838b121 §7④）')).toBeTruthy();
    expect((row?.textContent ?? '').includes('000001.SZ'), missing('参数完全符合 6 位数字+.SH/.SZ/.BJ 时应归到该证券行（契约 838b121 §7④）')).toBe(true);
    expect((row?.textContent ?? '').includes('示例甲'), missing('证券行应显示名称（契约 U3 / 838b121 §7④）')).toBe(true);
    expectNoText('future_x', missing('不得显示原始 code future_x（契约 838b121 §7④）'));
  });

  it('§7④ 未知 code 参数为 f.pe 时是通用行，没有 /stocks/f.pe 链接', async () => {
    await renderToday({
      today: emptyToday({
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
      report: emptyReport({
        gaps: [pipelineGap('pipeline.future_gate:f.pe:missing')],
      }),
    });
    expectText(COPY_UNKNOWN, missing('未知 code 应显示兜底文案「部分数据暂不可用。」（契约 838b121 §7④）'));
    expectNoText('future_gate', missing('不得显示原始 code future_gate（契约 838b121 §7④）'));
    const bad = [...document.querySelectorAll('a')].filter((a) => (a.getAttribute('href') ?? '').includes('/stocks/f.pe'));
    expect(bad.length, missing('f.pe 不符合 6 位数字+.SH/.SZ/.BJ，不得生成 /stocks/f.pe 链接（契约 838b121 §7④；549ecdf 尚未实现）')).toBe(0);
    const row = gapRowEl((s) => s.includes(COPY_UNKNOWN));
    expect(row, missing('应作为通用行显示兜底文案（契约 838b121 §7④）')).toBeTruthy();
    expect((row?.textContent ?? '').includes('f.pe'), missing('通用行不应把 f.pe 当成证券代码展示（契约 838b121 §7④）') === false ? 'x' : ((row?.textContent ?? '').includes('f.pe') ? 'should-fail' : '')).not.toBe('should-fail');
    expect((row?.textContent ?? '').includes('f.pe'), missing('通用行不应把 f.pe 当成证券代码展示（契约 838b121 §7④）')).toBe(false);
  });

  it('§7⑤ S6 在状态条时，缺口区有 S8 文案、没有 S6 文案', async () => {
    await renderToday({
      today: emptyToday({
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
      report: emptyReport({
        gaps: [pipelineGap('pipeline.daily_bars_not_ready'), pipelineGap('pipeline.analysis')],
      }),
    });
    expectText(S6, missing('状态条应显示 S6（契约 838b121 §7⑤）'));
    const area = gapArea();
    expect(area.textContent?.includes(S8), missing('缺口区应有被压住的 S8 文案（契约 838b121 §7⑤）')).toBe(true);
    expect(area.textContent?.includes(S6), missing('已在状态条显示的 S6 不得在缺口区重复（契约 838b121 §7⑤）')).toBe(false);
  });

  it('§7⑥ status=ready 但日报 404 → 失败文案，没有 today-no-signals 和 today-account', async () => {
    await renderToday({
      today: emptyToday({
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
      report: 'absent',
    });
    expectText(COPY_REPORT_FAIL, missing('日报 404 时应显示「日报详情暂时读取失败，分析缺口稍后显示。」（契约 838b121 §7⑥）'));
    expect(document.querySelector('[data-testid="today-no-signals"]'), missing('日报读取失败时不得出现 today-no-signals（契约 838b121 §7⑥）')).toBeNull();
    expect(document.querySelector('[data-testid="today-account"]'), missing('日报读取失败时不得出现 today-account（契约 838b121 §7⑥）')).toBeNull();
    expectNoText(R2, missing('日报读取失败时不判定 S9，不得显示 R2（契约 838b121 §7⑥）'));
  });

  it('§7⑦ 日报 user_input_missing 缺口显示「有信息待补录。」并链到 /portfolio/import，同一 key 只一次', async () => {
    await renderToday({
      today: emptyToday({
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
      report: emptyReport({
        gaps: [
          { key: 'account.future_field', reason: 'user_input_missing', message: '待补字段' },
          { key: 'account.future_field', reason: 'user_input_missing', message: '待补字段' },
        ],
      }),
    });
    expectText(COPY_USER_INPUT, missing('reason 为 user_input_missing 的非 pipeline 缺口应显示「有信息待补录。」（契约 838b121 §7⑦；549ecdf 尚未实现）'));
    const area = gapArea();
    expect(countIn(area.textContent ?? '', COPY_USER_INPUT), missing('同一个 key 只显示一次「有信息待补录。」（契约 838b121 §7⑦）')).toBe(1);
    const link = [...(area.querySelectorAll('a') ?? [])].find((a) => (a.getAttribute('href') ?? '') === '/portfolio/import');
    expect(link, missing('user_input_missing 应有指向 /portfolio/import 的入口（契约 838b121 §7⑦）')).toBeTruthy();
  });

  it('§7⑦ 日报 gaps 含 market → today 页不展示', async () => {
    const hidden = '指数摘要缺口不得出现在 today 页';
    await renderToday({
      today: emptyToday({
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
      }),
      report: emptyReport({
        gaps: [{ key: 'market', reason: 'no_source', message: hidden }],
      }),
    });
    expectNoText(hidden, missing('market 缺口 today 页不展示（契约 838b121 §7⑦）'));
  });

  it('§7⑦ /today.data_gaps 与日报 gaps 都含 cash 时「未录入现金」只出现一次', async () => {
    await renderToday({
      today: emptyToday({
        server_time: TIME_1840,
        daily_report: { date: TRADE_DATE, status: 'ready' },
        focus: { items: [holdingRow('000001.SZ', '示例甲')], more: false },
        data_gaps: { items: [cashTodayGap('未录入现金。')], more: false },
      }),
      report: emptyReport({
        gaps: [{ key: 'cash', reason: 'user_input_missing', message: '未录入现金。' }],
      }),
    });
    // 必须看整个「数据缺口」区块（today-data-gaps），不能只用 today-report-gaps，
    // 否则会漏掉 /today.data_gaps 列表里的同一条 cash。
    const section = (document.querySelector('[data-testid="today-data-gaps"]')
      ?? document.querySelector('[aria-label="数据缺口"]')
      ?? gapArea()) as HTMLElement;
    const n = countIn(section.textContent ?? '', COPY_CASH);
    expect(n, missing('/today.data_gaps 与日报 gaps 都含 cash 时，「未录入现金」只能出现一次（契约 838b121 §7⑦；549ecdf 尚未实现）')).toBe(1);
  });
});
