import { render, screen } from '@testing-library/react';
import { RISK_DISCLOSURE_TEXT, RiskDisclosure } from './RiskDisclosure';

describe('RiskDisclosure 风险揭示', () => {
  it('文本与 plan / 同意书 signal_risk_disclosure 逐字一致', () => {
    expect(RISK_DISCLOSURE_TEXT).toBe(
      '本工具基于公开数据与您录入的信息、按透明规则生成规则信号，不构成投资建议，不保证收益；规则可能失效，交易决定与风险由您自行承担。',
    );
  });

  it('以 role=note 渲染完整揭示文字，并附 Lightweight Charts 署名', () => {
    render(<RiskDisclosure />);
    const el = screen.getByRole('note', { name: '风险揭示' });
    expect(el).toHaveTextContent(RISK_DISCLOSURE_TEXT);
    expect(el).toHaveTextContent('TradingView Lightweight Charts');
  });

  it('可关闭署名，但揭示文字仍在', () => {
    render(<RiskDisclosure showAttribution={false} />);
    const el = screen.getByTestId('risk-disclosure');
    expect(el).toHaveTextContent(RISK_DISCLOSURE_TEXT);
    expect(el).not.toHaveTextContent('TradingView');
  });
});
