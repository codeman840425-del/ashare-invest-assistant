import { Button, Result } from 'antd';
import { useLocation, useNavigate } from 'react-router';

/** 契约 §4 已规划、但 T-F01 只放骨架的路由 */
export function PlaceholderPage({ title }: { title: string }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return (
    <div className="page-scroll" data-testid="placeholder">
      <Result
        status="info"
        title={title}
        subTitle={<span>页面骨架已就位（<span className="mono">{pathname}</span>），功能在后续任务按契约接入。</span>}
        extra={<Button size="small" onClick={() => navigate('/terminal')}>回到交易终端</Button>}
      />
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
