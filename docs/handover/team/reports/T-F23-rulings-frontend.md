# T-F23 裁定跟进（前端）——reports/frontend-pending-rulings.md 已裁定项

依据：契约 v0.2.9 #30（docs 66f0c79、1d02980 及 HEAD 上的 §1.3、§7.6、§7.7、§7.7B 原文）。契约未定之处不猜，列入“缺失的契约项”。

## 提交
- `787e453` feat(frontend): T-F23 裁定跟进（主体，31 个文件，只含 src/frontend/）
- `d9c045f` fix(frontend): 同步契约 §4 登记 414 URI_TOO_LONG（#34，docs 4b40e5c）。别人提交的 4b40e5c 在 §4 加了 414，导致前端 `review-fixes.test.ts`（ERROR_CODES 与 §4 逐行比对）在干净检出上失败；契约原文已定名称与状态码，前端只登记码、按通用错误显示 message。
- 均为本地提交，未 push，未 amend。

## 完成项
| 裁定 | 实现 |
|---|---|
| §7.7B 计划页 | `/plans` 列表（状态/来源筛选、分页）、`/plans/:id` 详情（当前版本、计划条件、已满足的条件、版本历史、修改=新建版本、关闭）；已结束计划的修改/关闭按钮禁用并说明 |
| §7.7B 提醒页 | `/alerts` 列表（状态/来源/级别/证券/计划筛选）、`/alerts/:id` 详情（状态迁移按 ALERT_NEXT；打开详情不改状态） |
| 枚举 | `plan_status`、`plan_condition_type`、`plan_origin` 进 api/enums.ts（/meta/enums 由后端提供，mock 不拦截） |
| 冲突证据 | 候选信号详情改读 evidence 中 `signal.conflict_signal_id`，按 id 列出对方信号；对方信号不存在时显示 conflict-missing |
| lot_rule | `lotRuleOf` 只从 `details.fields[]` 读 `min_buy`、`step`，顶层不再读 |
| plan-drafts mock 顺序 | 400 signal_ids（跨证券/动作/t_leg 不同）先于全部 409；同向但因 STRATEGY_CONFLICT 处于 blocked → 409 SIGNAL_NOT_EXECUTABLE；其他原因 blocked/非 drafted·released → 409 INVALID_STATE_TRANSITION |
| 科创板卖出 | 按公式提示：qty = 可卖量，或 qty ≤ 可卖量、qty ≥ min_buy 且 (qty−min_buy)%step=0；科创板 200/1，其他 100/100；confirm mock 同公式 |
| 未分类 | 持仓页行业分布显示“未分类”（Tooltip 说明不参与行业集中度判断）；示例夹具补该桶 |
| 研究候选改版 | 带 Idempotency-Key，重试复用同一键 |
| CSRF mock | 白名单只留 POST /auth/login、/auth/register（另做 Origin 校验，外站 → 403）；其余未登录写请求 → 401（含非法 JSON）；顺序 413 → 404/405 → 401/403 → 503 → 400 |
| /auth/password | 补 mock（缺 CSRF → 403，校验 → 400，成功 → 204） |
| 403 CSRF_FAILED | 全局横幅提示刷新页面（csrf-refresh-btn） |
| #26 ⑤ | 管理员暂停/恢复的通知标题用固定文案“数据证书已被管理员暂停/恢复” |

## 测试
- 新增 `src/pages/t-f23-rulings.test.tsx`（37 例）；更新 routes-review、routes、t-a08、t-a10、t-f18、review-b23401a（blocked 信号用例改用 T1_NOT_SELLABLE 致 blocked 的 uid(1016)，因 #30 后 STRATEGY_CONFLICT 致 blocked 返回 SIGNAL_NOT_EXECUTABLE）。
- 工作区：typecheck 0、eslint 0 warning、vitest 40 文件 622 例全过。
- 干净检出（HEAD d9c045f 的 worktree，不依赖工作区）：CI rc=0，vitest 622/622；check-dist 正向 0 命中、反向自检 20 个示例标记。pnpm audit 提示 1 个 moderate（既有依赖，与本次无关）。
- 扫描：secret_scan（files/staged）阻断 0、gitleaks（dir ×2、staged）0、禁用词与 11 位数字 0 命中。

## 截图（1440×900 暗色，0 控制台错误，0 外部请求）
- T-F23-rulings-frontend/plans.png、plan-detail.png、alerts.png

## handlers.ts / fixtures.ts
提交前 `git diff` 逐块核对：handlers.ts 3 处（import、resetPlansAlerts、展开 planAlertHandlers）、fixtures.ts 2 处（“未分类”桶、冲突证据后处理）均为本人改动；工作区中未发现他人未提交的块。逐文件暂存，未 `git add src/frontend/`。

## 缺失的契约项（请编排者派给架构师）
1. `Alert` 无 `plan_id` 字段：`/alerts?plan_id=` 的过滤依据未定，mock 暂按 `affected_plans` 过滤。
2. 提醒详情“检查清单”的语义（是否需作答、是否持久化）未定，前端只读展示。
3. `not_allowed` 与 `404` 的先后（计划/提醒归属与状态同时不符时）未写明。
4. `SAME_DIRECTION_PLAN_EXISTS` 在释放信号时的检查条件未细化，mock 未实现。
5. 全局请求体上限 `max_bytes` 具体值未定（示例用 25 MiB）。
6. `data_licence` 通知正文未定（mock 用示例文案，标题按 #26 ⑤ 固定）。
7. 计划 `account_id` 归属校验的错误码未写明。
8. #30 ④ 与 §7.6 研究候选 `planned`：示例数据中仍保留一条 planned 用于显示验证（契约写明“本版实际不会出现，前端仍要能显示”）。
9. STRATEGY_CONFLICT 致 blocked 与“信号状态不是 drafted/released → INVALID_STATE_TRANSITION”两句的优先级：前端 mock 按 #30 验收 5 取“同向且 STRATEGY_CONFLICT 生效 → SIGNAL_NOT_EXECUTABLE”，其余 blocked → INVALID_STATE_TRANSITION；请架构师在 §7.7 明确。

## 其他说明
- HEAD 上 46538a6 新增 #32（T-T25，7 条裁定）、4b40e5c 新增 #34（414）：不在本次 #29–#31 范围；仅为保持 CI 绿同步了 #34 的错误码登记。
- 已满足无需改动：事件 cause、PlanDraft 无 instance_id。
