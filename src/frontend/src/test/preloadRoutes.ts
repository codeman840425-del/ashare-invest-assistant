import type { RouteObject } from 'react-router';

/**
 * 测试用：提前加载路由表里的懒加载页面模块。
 * 页面模块第一次 import（冷启动转译）可能要 1 秒以上，如果发生在 findBy* / waitFor 的等待窗口里，
 * 机器繁忙时会偶发超时。评审 b23401a N8 要求不放宽全局超时，所以把这部分耗时挪到 beforeAll。
 */
export async function preloadRoutes(routes: RouteObject[]): Promise<void> {
  const loads: Promise<unknown>[] = [];
  const walk = (rs: RouteObject[]) => {
    for (const r of rs) {
      if (typeof r.lazy === 'function') loads.push(r.lazy());
      if (r.children) walk(r.children);
    }
  };
  walk(routes);
  await Promise.all(loads);
}
