/** 风险揭示：每个页面固定展示（plan §2.1 / 契约同意书 signal_risk_disclosure）。文字不可删改。 */
export const RISK_DISCLOSURE_TEXT =
  '本工具基于公开数据与您录入的信息、按透明规则生成规则信号，不构成投资建议，不保证收益；规则可能失效，交易决定与风险由您自行承担。';

export function RiskDisclosure({ showAttribution = true }: { showAttribution?: boolean }) {
  return (
    <footer className="risk-footer" role="note" aria-label="风险揭示" data-testid="risk-disclosure">
      <span>{RISK_DISCLOSURE_TEXT}</span>
      {showAttribution ? <span className="muted"> · 图表由 TradingView Lightweight Charts 提供</span> : null}
    </footer>
  );
}
