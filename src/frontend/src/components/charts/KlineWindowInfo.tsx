import { Button } from 'antd';

/** T-F21：窗口已加载根数、是否到最早；“更早”按钮给键盘/读屏用户（拖动图表到左边缘效果相同） */
export function KlineWindowInfo({ q, unit }: {
  q: { bars: unknown[]; hasNextPage: boolean; isFetchingNextPage: boolean; isFetchNextPageError: boolean; reachedStart: boolean; loadOlder: (force?: boolean) => void };
  unit: string;
}) {
  return (
    <span className="kline-window muted small" data-testid="kline-window">
      已载入 {q.bars.length} 根{unit} K
      {q.isFetchingNextPage ? ' · 正在加载更早…' : q.isFetchNextPageError ? <span className="warn"> · 更早的加载失败</span> : q.reachedStart ? ' · 已到最早' : ''}
      {q.hasNextPage ? (
        <Button size="small" type="link" onClick={() => q.loadOlder(true)} loading={q.isFetchingNextPage} aria-label="加载更早的 K 线" data-testid="kline-older">
          {q.isFetchNextPageError ? '重试' : '‹ 更早'}
        </Button>
      ) : null}
    </span>
  );
}
