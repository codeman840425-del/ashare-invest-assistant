import { Button } from 'antd';

/** useInfiniteQuery 结果里分页条需要的部分 */
export interface CursorPagerQuery {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  isFetchNextPageError: boolean;
  fetchNextPage: () => Promise<unknown>;
}

/**
 * 游标分页条（契约 §1.2，T-F21）：还有下一页 →“加载更多”（显示已加载条数）；
 * 下一页失败 → 已加载的数据保留，就地提示并可重试；到底 →“已显示全部 N 条”。
 */
export function CursorPager({ query, loaded, testId = 'cursor-pager', unit = '条', allText }: {
  query: CursorPagerQuery;
  loaded: number;
  testId?: string;
  unit?: string;
  /** 到底时的文案；不传用“已显示全部 N 条” */
  allText?: string;
}) {
  if (!query.hasNextPage) {
    if (!loaded) return null;
    return <div className="cursor-pager muted small" data-testid={`${testId}-end`}>{allText ?? `已显示全部 ${loaded} ${unit}`}</div>;
  }
  return (
    <div className="cursor-pager" data-testid={testId}>
      <span className="muted small">已加载 {loaded} {unit}</span>
      {query.isFetchNextPageError ? <span className="warn small" role="alert">下一页加载失败，已加载的内容保留</span> : null}
      <Button size="small" onClick={() => void query.fetchNextPage()} loading={query.isFetchingNextPage} data-testid={`${testId}-more`}>
        {query.isFetchNextPageError ? '重试' : '加载更多'}
      </Button>
    </div>
  );
}
