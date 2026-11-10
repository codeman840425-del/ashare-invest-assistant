/**
 * T-F33 自选入口：股票行与个股详情的「加自选」/「移出自选」按钮（契约 docs/contracts/watchlist.md）。
 * 是否已在自选以 GET /watchlist 为准；409 显示「已在自选」，403 显示上限（带 limit/current），404 显示已不在自选；
 * 失败或冲突后都会重拉列表，按钮按服务端状态纠正。指数按契约 U1 保守默认不可加入，直接禁用。
 */
import { useState } from 'react';
import { Button, Space, Tooltip, Typography } from 'antd';
import { inWatchlist, useAddWatchlist, useRemoveWatchlist, useWatchlist, watchlistErrorText } from '../../api/watchlistQueries';
import type { SecurityType } from '../../api/enums';

type Feedback = { kind: 'ok' | 'warn' | 'error'; text: string } | null;

export function WatchlistToggle({ code, securityType = null, size = 'small', testId = 'watchlist-toggle' }: {
  code: string;
  /** 已知证券类型时，指数直接禁用（契约 U1） */
  securityType?: SecurityType | null;
  size?: 'small' | 'middle';
  testId?: string;
}) {
  const list = useWatchlist();
  const add = useAddWatchlist();
  const remove = useRemoveWatchlist();
  const [fb, setFb] = useState<Feedback>(null);
  const isIndex = securityType === 'index';
  const inList = inWatchlist(list.data, code);
  const busy = add.isPending || remove.isPending;

  const onAdd = () => {
    setFb(null);
    add.mutate({ security_code: code }, {
      onSuccess: () => setFb({ kind: 'ok', text: '已加入自选' }),
      onError: (e) => setFb({ kind: (e as { status?: number }).status === 409 ? 'warn' : 'error', text: watchlistErrorText(e, 'add') }),
    });
  };
  const onRemove = () => {
    setFb(null);
    remove.mutate(code, {
      onSuccess: () => setFb({ kind: 'ok', text: '已移出自选' }),
      onError: (e) => setFb({ kind: (e as { status?: number }).status === 404 ? 'warn' : 'error', text: watchlistErrorText(e, 'remove') }),
    });
  };

  return (
    <Space size={4} data-testid={testId} data-code={code}>
      {isIndex ? (
        <Tooltip title="指数不能加入自选">
          <Button size={size} disabled data-testid="watchlist-add">加自选</Button>
        </Tooltip>
      ) : inList ? (
        <Button size={size} loading={remove.isPending} disabled={busy || list.isPending} onClick={onRemove} data-testid="watchlist-remove">移出自选</Button>
      ) : (
        <Button size={size} loading={add.isPending} disabled={busy || list.isPending} onClick={onAdd} data-testid="watchlist-add">加自选</Button>
      )}
      {fb ? (
        <Typography.Text role="status" className="small" type={fb.kind === 'ok' ? 'secondary' : fb.kind === 'warn' ? 'warning' : 'danger'} data-testid="watchlist-feedback" data-kind={fb.kind}>
          {fb.text}
        </Typography.Text>
      ) : null}
    </Space>
  );
}
