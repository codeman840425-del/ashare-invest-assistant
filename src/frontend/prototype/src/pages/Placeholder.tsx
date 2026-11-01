import { Button, Result } from 'antd';
import { NAV_MAIN, NAV_MORE } from '../components/AppShell';
import { go } from '../router';

export function Placeholder({ path }: { path: string }) {
  const item = [...NAV_MAIN, ...NAV_MORE].find((n) => n.path === path);
  return (
    <div className="placeholder">
      <Result
        status="info"
        title={`${item?.label ?? path}（占位）`}
        subTitle={`本原型只实现“交易终端 / 候选信号卡 / 盘后日报”三页；${item?.label ?? '该页面'}按 plan.md §2.4 页面清单保留导航入口，后续迭代实现。`}
        extra={[
          <Button key="t" type="primary" onClick={() => go('/terminal')}>交易终端</Button>,
          <Button key="s" onClick={() => go('/suggestions')}>候选信号卡</Button>,
          <Button key="r" onClick={() => go('/reports')}>盘后日报</Button>,
        ]}
      />
    </div>
  );
}
