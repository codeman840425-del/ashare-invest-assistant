/** 24条纯合成状态：DeepSeek 初稿与输入逐项保真复核；全部为示例数据。 */
export const PHASE2_STATES = [
  {
    "kind": "dimension",
    "dimension": "technical",
    "feature": "f.rsi14",
    "status": "verified_doc",
    "value": "52.5",
    "unit": "index_0_100",
    "data_status": "partial",
    "text": "示例数据：已保存的RSI事实"
  },
  {
    "kind": "dimension",
    "dimension": "capital",
    "feature": "f.main_net_20d",
    "status": "declared",
    "value": null,
    "unit": null,
    "data_status": "unavailable",
    "text": "示例数据：来源或输入缺失"
  },
  {
    "kind": "dimension",
    "dimension": "fundamental",
    "feature": "f.pe_ttm_pit",
    "status": "declared",
    "value": null,
    "unit": "times",
    "data_status": "unavailable",
    "text": "示例数据：来源或输入缺失"
  },
  {
    "kind": "dimension",
    "dimension": "sentiment",
    "feature": "f.is_limit_up_close",
    "status": null,
    "value": null,
    "unit": "bool",
    "data_status": "unavailable",
    "text": "示例数据：来源或输入缺失"
  },
  {
    "kind": "dimension",
    "dimension": "sector_market",
    "feature": "f.market_regime",
    "status": "declared",
    "value": null,
    "unit": "enum",
    "data_status": "unavailable",
    "text": "示例数据：来源或输入缺失"
  },
  {
    "kind": "dimension",
    "dimension": "news",
    "feature": "f.ann_risk_count_10d",
    "status": "declared",
    "value": null,
    "unit": "count",
    "data_status": "unavailable",
    "text": "示例数据：来源或输入缺失"
  },
  {
    "kind": "evaluation",
    "control": "stop_take",
    "state": "ok",
    "enabled": true,
    "text": "示例数据：合成风险状态"
  },
  {
    "kind": "evaluation",
    "control": "position_cap",
    "state": "triggered",
    "enabled": true,
    "text": "示例数据：合成风险状态"
  },
  {
    "kind": "evaluation",
    "control": "total_exposure",
    "state": "unknown",
    "enabled": true,
    "text": "示例数据：大盘环境未知"
  },
  {
    "kind": "evaluation",
    "control": "sector_concentration",
    "state": "unknown",
    "enabled": true,
    "text": "示例数据：合成风险状态"
  },
  {
    "kind": "evaluation",
    "control": "loss_streak_drawdown",
    "state": "unknown",
    "enabled": true,
    "text": "示例数据：合成风险状态"
  },
  {
    "kind": "evaluation",
    "control": "plan_violation",
    "state": "disabled",
    "enabled": false,
    "text": "示例数据：合成风险状态"
  },
  {
    "kind": "tracking",
    "state": "complete",
    "horizon_days": 1,
    "return_pct": "1.25",
    "benchmark_return_pct": null,
    "excess_pct": null,
    "exclusion_reason": null
  },
  {
    "kind": "tracking",
    "state": "pending",
    "horizon_days": 5,
    "return_pct": null,
    "benchmark_return_pct": null,
    "excess_pct": null,
    "exclusion_reason": null
  },
  {
    "kind": "tracking",
    "state": "untradable",
    "horizon_days": 20,
    "return_pct": null,
    "benchmark_return_pct": null,
    "excess_pct": null,
    "exclusion_reason": "示例数据：停牌"
  },
  {
    "kind": "tracking",
    "state": "excluded",
    "horizon_days": 1,
    "return_pct": null,
    "benchmark_return_pct": null,
    "excess_pct": null,
    "exclusion_reason": "示例数据：wait不计有效样本"
  },
  {
    "kind": "tracking",
    "state": "unavailable",
    "horizon_days": 20,
    "return_pct": null,
    "benchmark_return_pct": null,
    "excess_pct": null,
    "exclusion_reason": null
  },
  {
    "kind": "empty_or_failure",
    "name": "legacy_daily",
    "value": null,
    "text": "示例数据：legacy_daily"
  },
  {
    "kind": "empty_or_failure",
    "name": "removed_stock",
    "value": null,
    "text": "示例数据：removed_stock"
  },
  {
    "kind": "empty_or_failure",
    "name": "empty_tracking",
    "value": null,
    "text": "示例数据：empty_tracking"
  },
  {
    "kind": "empty_or_failure",
    "name": "settings_validation_error",
    "value": null,
    "text": "示例数据：settings_validation_error"
  },
  {
    "kind": "empty_or_failure",
    "name": "settings_invalid_range",
    "value": null,
    "text": "示例数据：settings_invalid_range"
  },
  {
    "kind": "empty_or_failure",
    "name": "settings_server_error",
    "value": null,
    "text": "示例数据：settings_server_error"
  },
  {
    "kind": "empty_or_failure",
    "name": "empty_risk_events",
    "value": null,
    "text": "示例数据：empty_risk_events"
  }
] as const;
