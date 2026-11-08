/** 示例数据；DeepSeek 草稿经契约复核，不代表真实门禁通过。 */
import { uid } from './fixtures';
import type { PromotionReport } from '../api/promotionTypes';
export const EXAMPLE_PROMOTION_REPORT: PromotionReport = {
  review_id: uid(940), card_id: uid(512), version_id: uid(322), version_no: 1,
  content_sha256: 'abcdef'.repeat(10) + 'abcd', stale: false,
  submitted_by: uid(3), submitted_at: '2026-11-01T08:00:00+08:00', reviewer_id: null, decided_at: null,
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
