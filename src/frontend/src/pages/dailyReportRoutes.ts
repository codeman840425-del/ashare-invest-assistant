/** T-F13 盘后日报：筛选与去向常量（单独成文件，供页面与测试共用） */

/** 逐股卡片筛选（URL `?filter=`，非法值按 all 处理） */
export const STOCK_FILTERS = ['all', 'changed', 'unchanged', 'removed'] as const;
export type StockFilter = (typeof STOCK_FILTERS)[number];

/** 待处理计数的去向（契约未规定日报里的去向，按 §7.6/§7.7 列表参数取最接近的筛选；见 T-F13 遗留问题） */
export const PENDING_ROUTE = { plan_drafts: '/plan-drafts?status=pending', active_reasons: '/candidate-signals?state=blocked' } as const;
