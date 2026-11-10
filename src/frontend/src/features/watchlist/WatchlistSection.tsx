/** T-F33：今日关注页的「我的自选」卡片（GET /watchlist）。列表顺序按服务端（加入时间升序），空列表显示空态。 */
import { Link } from 'react-router';
import { Tag } from 'antd';
import { useWatchlist } from '../../api/watchlistQueries';
import { ErrorBox } from '../../components/common';
import { WatchlistToggle } from './WatchlistToggle';

export function WatchlistSection() {
  const q = useWatchlist();
  const items = q.data?.items ?? [];
  return (
    <section className="today-card" data-testid="today-watchlist" aria-label="我的自选">
      <div className="today-card-head">
        <span className="today-card-title">我的自选</span>
        {q.data ? <span className="muted small" data-testid="today-watchlist-count">{items.length} / {q.data.caps.watchlist} 只</span> : null}
      </div>
      {q.isPending ? <div className="muted small">加载中…</div> : q.isError && !q.data ? (
        <ErrorBox error={q.error} prefix="自选加载失败" />
      ) : items.length ? (
        <ul className="today-list">
          {items.map((x) => (
            <li key={x.security_code} data-testid={`watchlist-item-${x.security_code}`}>
              <Link to={`/stocks/${encodeURIComponent(x.security_code)}`}><span className="mono">{x.security_code}</span> {x.name}</Link>
              {x.group ? <Tag>{x.group}</Tag> : null}
              {x.note ? <span className="muted small">{x.note}</span> : null}
              <WatchlistToggle code={x.security_code} testId={`watchlist-row-${x.security_code}`} />
            </li>
          ))}
        </ul>
      ) : (
        <div className="muted small today-empty" data-testid="today-watchlist-empty">还没有自选股。可在重点关注、持仓或个股页点「加自选」加入。</div>
      )}
    </section>
  );
}
