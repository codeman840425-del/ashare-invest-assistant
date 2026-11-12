/**
 * F-15：STOCK_SUB_PATHS_PENDING 删除守卫（口径由 PR #19 / ds/T-F34b 准备，main=465e020 尚未含该实现）。
 *
 * 目标：五端点（bars/financials/fund-flows/factors/announcements）全部上线后，前端需删掉
 * `STOCK_SUB_PATHS_PENDING` 里对应的模板行。本文件以「哨兵 + 删除守卫」方式守住这个交接项：
 *   - 空锁（守卫未接线，main 现状）：mock 不拦截五端点；静态校验器只允许空清单；
 *   - 每上线一个端点，把 slug 加进 liveSlugs，守卫立即报出仍登记为「开发中」的模板行与应删清单；
 *   - 接口级证据用显式路径 handler（不用 `{code}` 通配：本仓 MSW 3.0.3 下 `*` 通配 + `http.all`
 *     在该路径上会静默不命中，守卫若写成通配会「看起来接了其实没接」）。
 * 只动前端 mock/测试，不碰后端、不改契约。
 */
import { http, HttpResponse } from 'msw';
import { API_BASE } from '../api/client';
import { server } from '../mocks/server';

const API = API_BASE;

/** 五端点：slug → 后端统一前缀（上线即注册）。此表是本守卫的事实来源，上线端点从守卫清单里删行。 */
export const FIVE_SUB_ENDPOINTS = [
  'bars',
  'financials',
  'fund-flows',
  'factors',
  'announcements',
] as const;
export type SubEndpoint = (typeof FIVE_SUB_ENDPOINTS)[number];
const TEMPLATE = '/securities/{code}/';
export const templatesOf = (slugs: readonly string[]): string[] => slugs.map((s) => `${TEMPLATE}${s}`);

export interface GuardCheck {
  /** 模板 ↔ 端点对不上的脏行（拼写错误/旧路径） */
  unknown: string[];
  /** 已上线却仍登记为「开发中」的行：必须删除，否则真实资源 404 会被吞成“功能开发中” */
  liveStillPending: string[];
  /** 仍待上线的行（可保留） */
  stillPending: string[];
}

/**
 * 删除守卫：`liveSlugs` = 已确认在后端注册上线的端点。
 * 交付后每上线一个端点，把它的 slug 加进调用处的 liveSlugs，守卫立即要求前端删掉对应模板行。
 */
export function auditStockSubPending(
  pendingTemplates: readonly string[],
  liveSlugs: readonly SubEndpoint[],
): GuardCheck {
  const known = new Set(templatesOf(FIVE_SUB_ENDPOINTS));
  const unknown = pendingTemplates.filter((t) => !known.has(t));
  const liveSet = new Set(templatesOf(liveSlugs));
  const liveStillPending = pendingTemplates.filter((t) => liveSet.has(t));
  const stillPending = pendingTemplates.filter((t) => known.has(t) && !liveSet.has(t));
  return { unknown, liveStillPending, stillPending };
}

/** 请求是否命中某模板（带前缀路径；查询串不影响） */
export function hitsTemplate(template: string, url: URL): boolean {
  const path = url.pathname.replace(/^\/api\/v1/, '');
  const re = new RegExp(`^${template.replace('{code}', '[^/]+')}$`);
  return re.test(path);
}

/** 把模板实例化成一条示例路径（同 hitsTemplate 的反向，用于接口层断言） */
export function samplePathOf(template: string, code = '600000.SH'): string {
  return `${API}${template.replace('{code}', code)}`;
}

describe('F-15 子资源「开发中」模板删除守卫', { timeout: 20_000 }, () => {
  const pendingTemplates: string[] = []; // 空锁 = main 现状：守卫尚未接线（PR #19 未合入）

  afterEach(() => server.resetHandlers());

  it('五端点 slug 与后端统一前缀一一对应（不允许拼写漂移）', () => {
    expect(templatesOf(FIVE_SUB_ENDPOINTS)).toEqual([
      '/securities/{code}/bars',
      '/securities/{code}/financials',
      '/securities/{code}/fund-flows',
      '/securities/{code}/factors',
      '/securities/{code}/announcements',
    ]);
  });

  it('空锁：尚未接线时清单必须为空（不得凭空登记待上线端点）', () => {
    const r = auditStockSubPending(pendingTemplates, []);
    expect(r).toEqual({ unknown: [], liveStillPending: [], stillPending: [] });
  });

  it('删行守卫：已上线端点仍登记 → 逐条报出，并给出应删清单', () => {
    const stale = templatesOf(FIVE_SUB_ENDPOINTS);
    const all = auditStockSubPending(stale, [...FIVE_SUB_ENDPOINTS]);
    expect(all.liveStillPending).toEqual(stale);
    expect(all.stillPending).toEqual([]);

    const partial = auditStockSubPending(stale, ['bars', 'financials']);
    expect(partial.liveStillPending).toEqual(['/securities/{code}/bars', '/securities/{code}/financials']);
    expect(partial.stillPending).toEqual([
      '/securities/{code}/fund-flows',
      '/securities/{code}/factors',
      '/securities/{code}/announcements',
    ]);
  });

  it('删行守卫：拼写/旧路径脏行单独归类，不混进待上线集合', () => {
    const r = auditStockSubPending(
      ['/securities/{code}/fund_flows', '/securities/{code}/factor', '/securities/{code}/bars'],
      [],
    );
    expect(r.unknown).toEqual(['/securities/{code}/fund_flows', '/securities/{code}/factor']);
    expect(r.stillPending).toEqual(['/securities/{code}/bars']);
    expect(r.liveStillPending).toEqual([]);
  });

  it('模板匹配不跨端点漂移：/fund-flows 不吞 /fund-flows-x，不吞详情路径', () => {
    const t = '/securities/{code}/fund-flows';
    expect(hitsTemplate(t, new URL(`${API}/securities/600000.SH/fund-flows?date=x`, 'http://x'))).toBe(true);
    expect(hitsTemplate(t, new URL(`${API}/securities/600000.SH/fund-flows-x`, 'http://x'))).toBe(false);
    expect(hitsTemplate(t, new URL(`${API}/securities/600000.SH`, 'http://x'))).toBe(false);
    expect(hitsTemplate(t, new URL(`${API}/securities/600000.SH/bars`, 'http://x'))).toBe(false);
    // 证券代码段不进正则特殊字符：同一模板对任意合法代码命中
    expect(hitsTemplate(t, new URL(`${API}/securities/920094.BJ/fund-flows`, 'http://x'))).toBe(true);
  });

  it('接口级证据：显式路径守卫只命中该端点，同类子路径与详情路径原样透出', async () => {
    const template = '/securities/{code}/bars';
    for (const code of ['600000.SH', '000001.SZ']) {
      server.resetHandlers();
      const covered = samplePathOf(template, code);
      const neighbour = samplePathOf('/securities/{code}/financials', code);
      // 守卫只按精确路径拦截：同代码的邻居端点不得被吞（前缀误伤会遮蔽真实资源 404）
      expect(hitsTemplate(template, new URL(covered, 'http://x'))).toBe(true);
      expect(hitsTemplate(template, new URL(neighbour, 'http://x'))).toBe(false);
      // 先证明基线 mock 对该端点确有业务响应，否则「邻居 200」证明不了守卫的精确性
      const base = await fetch(neighbour);
      expect(base.status).toBe(200);
      // 基线 handler 先注册，显式守卫后注册覆盖它
      server.use(
        http.get(covered, () =>
          HttpResponse.json(
            { error: { code: 'NOT_FOUND', message: '资源不存在', details: null, request_id: 'r' } },
            { status: 404 },
          ),
        ),
      );
      const onGuard = await fetch(`${covered}?freq=1m`);
      expect(onGuard.status).toBe(404);
      const body = await onGuard.json();
      expect(body.error.code).toBe('NOT_FOUND');
      // 邻居端点仍走基线 mock（业务体，非错误信封）
      const after = await fetch(neighbour);
      expect(after.status).toBe(200);
      const nb = await after.json();
      expect(nb.error).toBeUndefined();
      expect(Array.isArray(nb.items)).toBe(true);
    }
  });

  it('空清单不产生任何拦截：已上线端点的真实资源 404 原样透出（不被吞成开发中）', async () => {
    server.resetHandlers();
    const r = auditStockSubPending(pendingTemplates, ['factors']);
    expect(r.liveStillPending).toEqual([]);
    const res = await fetch(samplePathOf('/securities/{code}/factors', '999999.SH'));
    expect(res.status).toBe(404);
    const body = await res.json();
    // 资源语义 404 由页面/errorPolicy 判定，不被守卫改写
    expect(body.error.code).toBe('NOT_FOUND');
    expect(body.error.details).toBeNull();
  });
});
