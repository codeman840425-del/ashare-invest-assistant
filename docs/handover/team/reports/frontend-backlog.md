# 前端剩余任务 × 契约齐全度评估（契约 v0.2.6，2026-11-02）

判定标准（编排者 2026-11-02 06:16）：任务用到的每个接口，在 docs/api-contract.md（含 changelog）里都要有明确的路径、请求/响应结构和枚举，才算“齐全”。只写了路径、结构是“见 plan”或“状态跃迁”这种描述的，都算不齐全。

已完成或已取消、本表跳过：
- T-F00、T-F01（含终端 T-F11 主体、建议详情、日报页骨架）、T-F02/F02a/F04、T-F02b、T-F05（v0.2.5 删减任务）、T-F22、T-F03。
- 同意流程与风险测评（T-A06 作废）。

> 编号说明：plan 第 2999 行 “T-F05–T-F10” 合起来写了 6 项，按顺序推定为 F05 候选、F06 计划编辑器与版本对比、F07 提醒规则、F08 今日关注、F09 复盘、F10 隐私中心。其中 “T-F05” 这个编号已被 v0.2.5 的删减任务占用，“候选”这一项本表记为 T-F05（候选）。建议架构师 / 编排者重新编号。

| 顺序 | 任务 | 用到的接口 | 契约齐全？ | 缺什么 |
|---|---|---|---|---|
| 1 | T-F05（候选）研究候选 + 用户决定 | 研究候选 CRUD、用户决定（plan T-B10） | ❌ | 契约里**没有**研究候选端点（`/candidates` 只在前端占位里出现），路径、结构、状态枚举全缺 |
| 2 | T-F06 计划编辑器与版本对比 | `/plans`、`/plans/{id}`、`/plans/{id}/versions`、`/plans/{id}/close` | ❌ | 只有路径。缺：ActionPlan / PlanVersion 结构（条件、仓位、`origin`、`base_version_no`、状态枚举），列表参数，版本对比接口（或说明由前端对两版 diff），计划条件的表达结构 |
| 3 | T-F07 提醒规则 | `/alert-rules`、`/alerts` | ❌ | 只有一句“提醒规则与触发记录”。缺：规则结构（价格 / 事件类型、阈值、渠道）、触发记录结构、枚举、PATCH/DELETE 语义 |
| 4 | **T-F08 今日关注** | `GET /today`（§7.3，弱 ETag）；共享对象 TerminalRow、SuggestionSummary、RiskFlag；枚举 market_session / market_regime / plan_draft_status / reason_code / risk_control / risk_level / reconciliation_status；跳转目标路由（§5.1 Notification.target 已定） | ✅ | 无。plan 2.3 / 2.4 里提到的“提醒、数据缺口、计划触发”**不在 /today 契约里**，本任务不做、不自定结构（见 T-F08.md） → **本轮实现** |
| 5 | T-F09 复盘 | `/reviews`、`/reviews/{id}` | ❌ | 只有路径。缺：复盘结构（时间线、三分归因、标签、策略边界统计）、创建请求体 |
| 6 | T-F10 隐私中心 | 导出、数据删除说明 | ❌ | T-A06 已取消自助注销和撤回同意；导出（T-B16）在契约里**没有端点**。需要先确认隐私中心是否还保留，以及保留后用哪些接口 |
| 7 | T-F12 建议卡（补全） | `/suggestions/{id}`（齐全，T-F01 已实现）、`/suggestions/{id}/chain`、`/suggestions/{id}/tracking`、`/suggestions/{id}/actions` | ⚠️ 部分 | `chain` 只写“返回取代链”，没有结构；`tracking` 的“各期价格依据”没有结构；`explanation` 里“LLM 解释引用跳转”的引用格式没定义 |
| 8 | T-F13 盘后日报（补全） | `/daily-reports*`（§5.3） | ✅（已在 T-F01 实现） | 无。剩余工作只是 UI 打磨，不卡契约 |
| 9 | T-F14 通知中心 | `/notifications*`（齐全）、`/notification-preferences`、`/channels`、SSE `/stream`（§8 齐全） | ⚠️ 部分 | 偏好、免打扰、渠道绑定只有路径，没有结构和枚举 |
| 10 | T-F15 管理后台（LLM / 实时参数 / 套餐） | `/admin/llm/*`、`/admin/realtime-settings`、`/admin/plans`、`/admin/subscriptions` | ❌ | LLM 只定了 key 的读写规则，providers / models / routes / prompts / usage 都没有结构；realtime-settings、plans、subscriptions 都只有路径 |
<redacted:sensitive-value-or-command>
| 12 | T-F17 候选信号卡与不可执行原因 | `/candidate-signals*`、`/non-executable-reasons*`、`/meta/enums.reason_codes` | ⚠️ 基本齐全 | 列表 `GET /candidate-signals` 的元素没有明说是 `CandidateSignal` 还是摘要；“自动重评状态”的字段没有明确（推测是 reason `status` + `released_by`）。补一句就能做。已由 T-A08（契约 v0.2.7 §7.6）补齐：列表元素即完整 `CandidateSignal`；“自动重评状态” = 原因的 `status` + `released_at` + `released_by`。 |
| 13 | T-F18 计划草案确认页 | `/plan-drafts*`（PlanDraft、confirm、discard 的错误码齐全） | ⚠️ 基本齐全 | `GET /plan-drafts` 的列表参数（如 `?status=`）没写；“stale 后重新生成”是否就是用原 `signal_ids` 再 `POST /plan-drafts`，需要一句确认。已由 T-A08（契约 v0.2.7 §7.7）补齐：`GET /plan-drafts?status=&security_code=&signal_id=`；`stale` 后重新生成 = 用原 `signal_ids` 再 `POST /plan-drafts`。 |
| 14 | T-F19 策略实例管理 + 限制管理 | `/strategy-instances*`、`/restrictions*` | ❌ | 实例 GET 的列表 / 详情结构、`events` 结构都没定义（已派 T-A08）；restrictions 齐全 |
| 15 | T-F20 管理端：模板生命周期 / 审核 / ingest 状态 | `/admin/promotions*`、`/promotion-requests/{id}`、`/admin/strategies/.../lifecycle`、`/admin/ingest/status`、pause/resume | ⚠️ 部分 | ingest 状态页齐全；`/admin/promotions` 列表元素没有结构；内部评估是第三阶段 |
| 16 | T-F21 性能（虚拟化 / K 线窗口 / 游标翻页） | `/securities/{code}/bars` 的 `before`+`limit`、§1.2 游标 | ✅ | 无（属于工程优化，不新增接口） |
| 17 | T-F22 遗留：管理端证书列表 | `/admin/data-licences`、pause/resume | ✅ | 无（T-F22 遗留项，可以随时补做） |

## 结论
- 按顺序，第一个齐全的是 **T-F08 今日关注**，本轮实现，报告见 T-F08.md。
- 其后齐全或接近齐全的有：T-F13（已实现）、T-F17 / T-F18（各差一句说明）、T-F21、T-F22 遗留的管理端证书列表。
- 卡在契约上的（需要架构师补）：T-F05（候选）、T-F06、T-F07、T-F09、T-F10、T-F12 补全、T-F14 偏好 / 渠道、T-F15、T-F16、T-F19 实例、T-F20 审核列表。
