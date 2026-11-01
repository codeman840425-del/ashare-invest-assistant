import { Button, Result } from 'antd';
import { useLocation, useNavigate, useSearchParams } from 'react-router';

/** 契约 §4 已规划、但 T-F01 只放骨架的路由 */
export function PlaceholderPage({ title }: { title: string }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [params] = useSearchParams();
  // v0.2.7：/today“查看全部”等入口带 tab / status / event 等参数进来，页面未实现前先接住并显示，实现时按这些参数初始化筛选
  const received = [...params.entries()];
  return (
    <div className="page-scroll" data-testid="placeholder" data-params={params.toString()}>
      <Result
        status="info"
        title={title}
        subTitle={<span>页面骨架已就位（<span className="mono">{pathname}</span>），功能在后续任务按契约接入。</span>}
        extra={<Button size="small" onClick={() => navigate('/terminal')}>回到交易终端</Button>}
      >
        {received.length ? (
          <div className="small muted" data-testid="placeholder-params">
            已接收筛选参数：{received.map(([k, v]) => <span key={k} className="mono" data-param={k}>{k}={v} </span>)}
          </div>
        ) : null}
      </Result>
    </div>
  );
}

export function NotFoundPage() {
  const navigate = useNavigate();
  return (
    <div className="page-scroll" data-testid="not-found">
      <Result status="404" title="页面不存在" extra={<Button size="small" onClick={() => navigate('/terminal')}>回到交易终端</Button>} />
    </div>
  );
}
