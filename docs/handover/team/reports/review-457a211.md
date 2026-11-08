# 评审：457a211（T-B02y：契约 v0.2.8 ETF 与枚举）

- 评审时间：2026-11-02（UTC+8）；基准：契约 v0.2.8（`git show 7afbc06:docs/api-contract.md`）
- 方式：只读；git archive 导出 /tmp/rev3-457a211；`uv sync --frozen`、ruff、mypy、pytest；7afbc06 上跑 CI contract 作业
- 自报：/workspace/team/reports/T-B02y.md

## 结论：**通过**（只有 m 级问题）

## 问题表

| 编号 | 位置 | 问题 | 原因 | 修复建议 | 负责 |
|---|---|---|---|---|---|
| m1 | src/backend/app/strategy/eligibility.py:10、:32 | 查不到的代码返回 `422 INSTANCE_SCOPE_INVALID{issue:"unknown_security"}`；契约 §4 第 433 行只定义了 `{scope}` 和 ETF 的 `security_type_not_supported` | 后端自行扩展了 issue 取值 | 由架构师把 `unknown_security` 写进契约 §4，或者后端去掉该 issue，只返回 `{scope}` | 架构师 / 后端 |
| m2 | eligibility.py（整体） | 只提供常量和函数，实例创建、更新端点尚未调用 | 端点属于 T-B06 / T-B07 | 接入时补端到端测试；DB 守卫触发器 `trg_strategy_instances_eligible_security`（BEFORE INSERT OR UPDATE OF security_code）返回 check_violation 而不是 422，端点必须先调用 `ensure_strategy_eligible` | 后端（T-B06/B07） |
| m3 | tests（测试分支 caa1f09） | 6 个用例失败：test_alembic_head_is_known 期望 0008；test_meta_enums 的 5 个用例不认识 v0.2.8 | 测试预期滞后 | 测试员按 v0.2.8 更新 | 测试员 |

## 核对
| 检查项 | 结果 |
|---|---|
| /meta/enums：security_type、gap reason 含 `not_applicable` | ✓ |
| ETF 实例 → 422 INSTANCE_SCOPE_INVALID{scope, security_code, security_type:"etf", issue:"security_type_not_supported"}（errors.py:148 为 422） | ✓（函数层面） |
| ETF 搜索：默认类型、排序 | ✓ |
| SecurityProfile ETF 空字段与 §5.1 一致 | ✓ |
| gaps not_applicable | ✓ |
| 价格精度 dp3 | ✓ |
| ruff / mypy / uv sync --frozen | ✓ |
| pytest：6 failed / 784 passed / 93 skipped / 14 xfailed，失败全是测试预期滞后 | 见 m3 |

## 测试方法
干净导出 + 测试分支用例；schema / openapi 由 7afbc06 上的 schemathesis 覆盖（见 review-116cb7e.md 的 CI 小节）。
