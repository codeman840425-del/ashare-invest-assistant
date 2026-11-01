import { useId } from 'react';
import { Switch } from 'antd';
import type { CardRiskLevel } from '../api/enums';
import { isHighRisk } from '../lib/strategyRisk';

/**
 * 高风险策略的固定风险说明（契约 v0.2.6 T006e；plan 2.5.0A ⑫；T-A07 §4 第 4 条默认文案）。
 * 文案逐字使用原文，由 t-f22.test.tsx 读取 plan.md 比对；改文案只能先改 plan / 编排者裁定。
 */
export const HIGH_RISK_STRATEGY_NOTE = '高风险策略：短线情绪类规则，波动和回撤可能很大，规则可能很快失效。仅供研究参考，盈亏自负。';


interface Props {
  checked: boolean;
  onChange: (next: boolean) => void;
  riskLevel: CardRiskLevel | null | undefined;
  loading?: boolean;
  disabled?: boolean;
  /** 开关的可访问名称（固定为模板名） */
  name: string;
  testId?: string;
}

/**
 * 策略启用开关（可复用：策略库、策略详情、我的策略实例）。
 * `risk_level: high` 时开关旁**固定**展示风险说明：开、关两种状态都显示；启用时不弹窗、不要求勾选确认（v0.2.6 T006e）。
 */
export function StrategyEnableSwitch({ checked, onChange, riskLevel, loading, disabled, name, testId }: Props) {
  const high = isHighRisk(riskLevel);
  const noteId = useId();
  return (
    <span className="strategy-enable" data-testid={testId}>
      <Switch
        size="small" checked={checked} loading={loading} disabled={disabled} onChange={onChange}
        // 评审 m5：名称固定为模板名，开/关由 aria-checked 表达；风险说明用 aria-describedby 关联
        aria-label={name} aria-describedby={high ? noteId : undefined} checkedChildren="启用" unCheckedChildren="停用"
      />
      {high ? (
        <span className="high-risk-note" id={noteId} role="note" aria-label="高风险策略说明" data-testid="high-risk-note">{HIGH_RISK_STRATEGY_NOTE}</span>
      ) : null}
    </span>
  );
}
