# T-A157 裁定：策略卡审核的刷新语义（重跑/失效/审计）

日期：2026-11-11（北京时间）｜裁定人：架构师｜输入：R-04 补证清单发现（PR #53；「重复 POST 复用旧 pending、已完成检查不重算，刷新能力缺口」）
取证：`app/strategy/reviews.py`（request_review L150-210 / execute_review L213-229 / content_sha256 L35-52 / stale_reason L107-114）、`app/strategy/promotions.py`（prepare 的 G2 registry 实时读 feature_catalog L94-105）、`source_reviews.source_issues`、`api/v1/promotions.py` submit L90-105；契约 §7.4（T-A18/T-A20 已并入的审核绑定语义）。

## 0. 现状（取证确认，与 R-04 一致）

1. 幂等键 = `(version_id, decision=pending, binding{card_id, version_id, content_sha256})`；同版本同内容且有非 stale pending → **返回旧 review_id，created=false，不排执行**（reviews.py L171-174 + promotions.py L103）。
2. `content_sha256` **只哈希卡内容**（fields/epistemic/refs/config/params_schema/rule_snippet_refs/feature_set_version/kind/code_entry），**不含 feature_catalog 状态**；目录状态变化不触发 stale（L35-52）。
3. 已完成（decision≠pending 或 compliance_lint.status≠execution_pending）的审核：execute_review 直接 return（L221-226）；重复 POST 也只匹配 decision=pending 的候选（L168）→ **已完成审核永不因目录变化重算**。
4. G2 在 prepare 时实时读 feature_catalog registry（promotions.py L94-105）——重跑一次 prepare 即可吃到新目录状态。

## 1. 裁定①：同版本同内容重复 POST——**新增显式重跑参数，不强制强制新轮**

- **保留现有幂等默认**：`POST /strategy-cards/{id}/promotion-requests`（body `{version_id}`）行为不变——同绑定非 stale pending → 202 旧 review_id、created=false。理由：幂等是 T-A18 防重复排队的既有承诺（「幂等，不重跑」写进契约），后台任务重试/网络重放不应制造重复执行轮。
- **新增 `rerun: boolean`（默认 false）**：请求体可选字段。`rerun=true` 时：
  - 存在同绑定**非 stale pending**：将该旧审核置 `decision=changes_requested` 不行——篡改语义；正确做法：**旧 pending 保持不动，新建一轮审核**（新 review_id，gate_results 全 skipped/execution_pending，正常排队执行）。旧 pending 与新轮并存于历史，`GET /admin/promotions` 分页可见。
  - 存在同绑定**已完成（approved/rejected/changes_requested）**审核：同样新建一轮（这是本缺口的核心——已完成的 G2 fail 不能因 F21 补齐而自动复活，但**用户应有权要求重查**）。
  - `rerun=true` 且无任何既有审核：等同首次，新建（不报错）。
- **错误语义**：版本非 draft / 非 current → 409 既有错误不变；rerun 不豁免 stale 检查（binding 对照新轮自身）。
- **为什么不选「强制每 POST 新轮」**：破坏幂等承诺 → 网络重放即重复执行轮，浪费执行且污染审核历史；「显式 opt-in 重跑」把重跑决定交给有权限的提交者，与项目「显式优于隐式」一致。

## 2. 裁定②：数据变化后已完成检查的失效/重算触发条件——**不自动失效，不自动重算；显式重跑 + stale 摘要留痕**

1. **已完成审核不自动失效**。G7 批准后的 lifecycle 跃迁（draft→simulating）不受目录后续变化影响——批准是「当时证据下的人审结论」，历史不回写（版本不可变原则同向）。目录变化只影响**下一轮**审核。
2. **不设目录变更自动触发器**（不监听 feature_catalog 变化自动重跑 pending 审核）。理由：① pending 在队列/执行中遇目录变化会产生竞态（G2 读到哪个版本的状态不可复现）；② 自动重跑违反「重跑是显式决定」；③ 审核结果的可复现性依赖「执行时刻的目录快照」，自动触发会破坏该锚点。
3. **stale 判定维持内容绑定不动**（content_sha256 不加目录状态）。但补一条**执行时刻目录快照留痕**：gate_results 的 G2 detail 记录 `feature_status_snapshot: {feature_key: status}`（执行时实读），使「这轮 G2 是按哪个目录状态判的」可追溯——这是复现与事后审计的依据，不是失效条件。
4. **前端/管理端提示义务**（产品行为，非阻断）：`GET /promotion-requests/{id}` 当 `decision` 为终态且 G2 曾 fail 时，若当前 feature_catalog 中相关键状态已变化，响应可附 `rerun_available: true` 信息键（非契约强制，实现可选；MVP 可先不做，靠人工发现）。

## 3. 裁定③：审计事件——新增 `promotion.rerun`

- 新事件 `promotion.rerun`：`actor_id=提交者`、`target_type=promotion`、`target_id=新 review_id`、`detail={previous_review_id, version_id, card_id, trigger="manual_rerun", feature_status_changed: bool（新轮 G2 快照与上一轮 G2 快照的逐键差异是否存在，无法比较时 false）}`。
- 首次提交（无既有审核）不记 rerun（沿用现状，无审计事件——请求本身有 review 行可查）；只有真发生「放弃/并存旧轮、新建一轮」时记。
- 既有 `promotion.decision` 审计不变；G7 决定审计不变。

## 4. 契约与实现同步清单

| # | 事项 | 位置 | 角色 |
|---|---|---|---|
| 1 | POST 请求体加 `rerun: boolean=false`；rerun 语义、202 新旧轮并存、幂等默认不变 | 契约 §7.4 promotion-requests 行 | 架构师（本提交） |
| 2 | G2 detail 补 `feature_status_snapshot` | 契约 §7.4 GET /promotion-requests 的 gate_results 说明 | 架构师（本提交） |
| 3 | 审计事件 `promotion.rerun` 登记 | 契约 §4 审计事件（若有列表）+ plan 相应节 | 架构师（本提交） |
| 4 | request_review 加 rerun 分支；G2 快照写入；审计接入 | src/backend（reviews.py/promotions.py） | 后端（另领单） |
| 5 | 定点负例：rerun=false 幂等不变；rerun=true 三态（pending/终态/无既有）；快照留痕；审计逐条 | selfchecks | 后端随单 |
| 6 | plan §2.5.14 审核流程补 rerun 语义一句 | plan | 架构师（本提交） |

## 5. 不采纳项

| 不采纳 | 理由 |
|---|---|
| 同内容重复 POST 强制新轮 | 破坏 T-A18 幂等承诺，重放即重复执行 |
| feature_catalog 变更自动失效已完成审核 | 批准是当时证据的人审结论，历史不回写；自动失效让 G7 批准随时悬空 |
| 目录变更自动重跑 pending | 执行时刻目录状态不可复现，竞态与审计锚点皆失 |
| content_sha256 摄入目录状态 | stale 语义只绑内容版本；目录是外部事实，用快照留痕而非绑定哈希 |
