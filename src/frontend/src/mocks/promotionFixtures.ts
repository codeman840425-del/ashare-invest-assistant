/** 示例数据；DeepSeek 草稿经契约复核，不代表真实门禁通过。 */
import type { PromotionReport } from '../api/promotionTypes';
export const EXAMPLE_PROMOTION_REPORT: PromotionReport = {
  decision: "pending",
  gate_results: [
    { gate: "G1", result: "pass", detail: "fictional-check-alpha ok" },
    { gate: "G2", result: "pass", detail: "fictional-check-beta ok" },
    { gate: "G3", result: "pass", detail: "fictional-check-gamma ok" },
    { gate: "G4", result: "pass", detail: "fictional-check-delta ok" },
    { gate: "G5", result: "pass", detail: "fictional-check-epsilon ok" },
    { gate: "G6", result: "warn", detail: "示例数据：no_history，近 120 日历史不足" },
    { gate: "G7", result: "skipped", detail: "示例数据：等待管理员本人批准" },
  ],
  fixture_runs: [
    { fixture_id: "fixture-0001", passed: true, diff: null },
    { fixture_id: "fixture-0002", passed: true, diff: null },
    { fixture_id: "fixture-0003", passed: true, diff: null },
  ],
  g6_report: {
    trigger_rate: {
      value: "0.42",
      n: 12,
      window: "7d",
      small_sample: true,
    },
    coverage: {
      value: "0.87",
      n: 12,
      window: "7d",
      small_sample: true,
    },
    max_jaccard: null,
    max_jaccard_null_reason: "no_history",
    quota_delta_per_min: 3,
  },
};
