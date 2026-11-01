import type { ReactNode } from 'react';
import { Tag } from 'antd';
import { IS_MOCK } from '../../lib/env';
import { RiskDisclosure } from '../../components/RiskDisclosure';

/** 登录 / 注册 / 审核状态 / 开通引导共用的居中布局（不含主导航，不发起需登录的请求） */
export function AuthLayout({ title, children, wide, testId }: { title: string; children: ReactNode; wide?: boolean; testId?: string }) {
  return (
    <div className="auth-page" data-testid={testId}>
      <div className="auth-brand">
        <span className="logo">A</span>
        <span>投资研究与决策助手</span>
        {IS_MOCK ? <Tag color="gold" style={{ marginLeft: 8 }}>示例数据</Tag> : null}
      </div>
      <div className={`auth-card${wide ? ' wide' : ''}`}>
        <h2 className="auth-title">{title}</h2>
        {children}
      </div>
      <div className="auth-foot"><RiskDisclosure /></div>
    </div>
  );
}
