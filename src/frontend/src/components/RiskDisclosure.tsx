/**
 * 固定免责提示（契约 v0.2.5 #1；docs/strategies/compliance/disclaimer.md 1.0）。
 * 文案必须与 disclaimer.md 逐字一致（标点、空格都不改），由 RiskDisclosure.test.tsx 读取原文比对。
 * 展示位置：页面底部、候选信号卡、行动计划卡、注册页。只展示，不需要勾选。
 */
export const DISCLAIMER_TEXT = '本工具仅供个人研究参考，不构成投资建议。候选信号由规则自动生成，数据可能延迟或出错，盈亏自负。';

export function RiskDisclosure({ showAttribution = true }: { showAttribution?: boolean }) {
  return (
    <footer className="risk-footer" role="note" aria-label="免责提示" data-testid="risk-disclosure">
      <span>{DISCLAIMER_TEXT}</span>
      {showAttribution ? <span className="muted"> · 图表由 TradingView Lightweight Charts 提供</span> : null}
    </footer>
  );
}

/** 卡片内的免责提示（候选信号卡、行动计划卡） */
export function CardDisclaimer() {
  return <div className="card-disclaimer muted small" role="note" aria-label="免责提示" data-testid="card-disclaimer">{DISCLAIMER_TEXT}</div>;
}
