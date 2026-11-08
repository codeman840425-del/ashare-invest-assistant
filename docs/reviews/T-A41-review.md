# T-A41｜T-B91 与 P2N-05j 攒批复审

- 时间：2026-11-08，北京时间（Asia/Shanghai）。
- 后端仅复审 `f28727d`、`38fc560` 的 diff；前端仅复审 `4333170` 的 diff。本机例外：提交只存在于共享盒子本地；不克隆、不推送、不调用 DeepSeek、不改实现代码。
- 对照：T-A32、P2N-07-review、T-A37、team/reports/T-A40.md、T-B91.md、T-B91-evidence.md。下列文件行号为目标提交版本；检查时相关工作树与目标版本一致。
- **T-B91：不通过。** 原 B2 仅部分关闭；新增重要问题 1 项、建议 2 项，无新增阻断。原 B2 仍按原阻断等级保留，不重复算成新增问题。
- **05j：通过（本次契约 mock/UI 增量范围）。** I1–I3 全部关闭；不代替真实后端解释权限过滤及 P2N-09 联调验收。
- 本文“关闭”指 diff 所示修复成立或所要求的回归已提交；本轮未成功复跑的后端集成场景不冒充本轮动态验收通过，也不签生产放行。

## 1. T-A32 逐项复审

| 项目 | 判定 | 证据与边界 | 归属 |
|---|---|---|---|
| R1 日报顶层时点 | 关闭 | `src/backend/app/reports/service.py:119-203,292-304,366-367` 汇集已使用账户估值/现金、六维事实和建议证据时点，取最早；全无为 null/unavailable。`src/backend/app/api/v1/daily_reports.py:94-124` 对旧档只读提取冻结组件时点，拒绝晚于 generated_at 的时点，不写回存档。对应自检 `test_tb91_fixes.py:548`、`test_tb91_closing.py:365`。当前市场部分本来无事实，不编市场时点。 | 后端 |
| R2 日报账户金额 | 关闭 | `src/backend/app/reports/service.py:120-205` 收盘价→参考价→已知成本；缺现金展示 0.00 加 cash gap；整体不可算才 account=null；pnl_day 保持 null 加 gap。`src/backend/app/reports/models.py:37-38` 金额非 Optional；`src/backend/app/api/v1/daily_reports.py:87-93` 旧档非法账户只读投影为 null。对应 `test_tb91_fixes.py:390,502`。 | 后端 |
| R3 除权事实和周期 RC1 | 关闭（代码/离线链路范围） | `src/backend/app/risk/rc1.py:76-160,181` 以可得 none/qfq OHLC 精确有理比例证明连续性；缺配对、时点不一致等仍 unknown，不默认无除权。`src/backend/app/risk/worker.py:26-45,47-146` 按本人账户、当前实例版本及最新建议盘中/盘后评估并 events.record；`src/backend/app/workers/jobs.py:389-391,438-439` 注册与周期排程。`test_tb91_fixes.py:341,579` 有连续/变化/缺证及实际队列回归；本轮未重新取得动态通过证据，不宣称真实行情/生产运行已验。 | 后端 |

## 2. P2N-07 逐项复审

| 项目 | 判定 | 证据与边界 | 归属 |
|---|---|---|---|
| B1 草案始终 503 | 关闭（生成实现已接入） | `src/backend/app/plans/drafts.py:102-130` 用真实组装替换固定异常；`src/backend/app/plans/generation.py:41-395` 读取本人账户/可信报价/费用/交易单位/来源实例，冻结快照并写草案、状态和审计。buy/add 不再因“未配置单笔上限”无条件拒绝。`test_tb91_fixes.py:834`、`test_tb91_closing.py:68` 补生成→确认、重放及他人权限用例。生产报价可达性仍归 B2，不能因此宣称生产闭环。 | 后端 |
| B2 生产数据链和自动调度 | **部分关闭，原阻断保留** | `src/backend/app/plans/worker.py:118-187` 接受非 test 的 owned-unadjusted-quote-v1，校验本人有效许可、哈希、未复权、鲜度、停牌；`src/backend/app/workers/jobs.py:365-387,390,439` 补 owner sweep 排程。可是 `src/backend/app/ingest/owned_quotes.py:27-107` 只是 record_quote 适配函数：本次 diff 没有给现有采集完成流程增加调用；全仓调用检索只见 `src/backend/selfchecks/test_tb91_fixes.py:89`。这证明离线手动注入可走通，不能证明采集→快照→定时条件任务的生产数据链已接通。须补实际可信采集完成调用及定点闭环证据，或由编排者明确另立生产接线任务后再收口；当前不能完整关闭旧 B2。 | 后端（采集接线需与运维协调） |
| I1 价格等号 | 关闭 | `src/backend/app/plans/worker.py:212-214` 为 >= / <=；`test_tb91_fixes.py:128` 有生产 schema 适配及包含边界回归。 | 后端 |
| I2 pct_change / pct=0 | 关闭 | `src/backend/app/plans/models.py:59` 拒绝 0；`src/backend/app/plans/worker.py:191-210,236-247` 按 (price/prev_close−1)×100、HALF_UP 四位、正负阈值比较，缺 prev_close 拒绝，不补零，并保留操作数。`test_tb91_fixes.py:128,196,968` 有针对性回归。 | 后端 |
| I3 日期下界/09:00/顺延/补发 | 关闭 | `src/backend/app/plans/service.py:75-81` 北京当天写入下界；`src/backend/app/plans/worker.py:92-111` 顺延到已知开市日、09:00 含等号、错过可补判；日历缺口明确 gap；同文件 `:83-86` 幂等去重。`test_tb91_fixes.py:196,223,278` 覆盖相关边界。 | 后端 |
| S1 中途回滚与并发确认回归 | 关闭（回归已补） | `src/backend/selfchecks/test_tb91_fixes.py:871-967` 使用真实确认路径，覆盖多信号中途异常的整体回滚及相同/冲突并发；不是只检查单表。确认仍在同一事务，保留 owner 锁与来源快照校验。此项测试本轮未重跑；历史通过仅来源于 T-B91-evidence，不能记作本轮通过。 | 后端 |

## 3. T-A40 口径和四个必测场景

| 项目 | 判定 | 证据 | 归属 |
|---|---|---|---|
| 未配置本笔亏损上限跳过、不自造配置 | 关闭 | `src/backend/app/plans/generation.py:219-284` 数量由实际现金/费用、单只上限、预算、ST 与既有数量 cap 约束；已删除无条件缺少 per_trade_max_loss_input 的拒绝。没有新增配置键。 | 后端 |
| 仍输出 max_loss；资产未知 pct=null；无止损且 RC1 关闭两者 null+警示 | **部分关闭** | `src/backend/app/plans/generation.py:206-216,273-304,348-368` 实现 high、止损距离及买卖费用、资产未知 gap，模型允许 null（`models.py:297-298`）。但关闭 RC1 的新增警示写入非法 risk_level=attention，见 N-I1，不能作为契约闭环签收；另见 N-S2 文案矛盾。 | 后端 |
| 多实例来源全额计入每个来源实例，剩余取最小 | 关闭 | `src/backend/app/plans/budgets.py:43-108,111-120` 本人 active/triggered 计划，v1 来源归属、当前版本 buy/add 金额，qty×price 优先、size_amount 回退；每实例独立累加全额，取剩余最小。`src/backend/app/plans/service.py:133-134` 冻结 v1 candidate_signal_ids；`generation.py:285-289` 保存 estimate/参与 plan_ids。 | 后端 |
| 金额 unknown 时 buy/add 拒绝，null 预算不约束 | 关闭（代码） | `src/backend/app/plans/budgets.py:41-43,70-106` null 预算直接跳过；缺来源或金额抛 BudgetUnknownError；`generation.py:219-224` 转具名 gap、事务回滚。预算耗尽由 `drafts.py:120-130` 提交原因事实后返回 409，非半成品草案；确认 `drafts.py:341-361` 重验预算及 chosen_qty×chosen_price。unknown 的 API 级回归仍需补，见 N-S1。 | 后端 |
| 必测① 两项 null 正常出草案 | 已补；本轮环境错误 | `test_tb91_closing.py:68-115` buy/add 两个参数，预算 null 且无单笔配置仍能确认；本轮两个节点均在 PG 建连前置失败。 | 后端；运维恢复隔离测试服务 |
| 必测② 预算耗尽 | 已补；本轮环境错误 | `test_tb91_closing.py:143-187` 检查 409、原因持久化与重新评估释放；本轮 setup PG Connection refused。 | 后端；运维恢复隔离测试服务 |
| 必测③ 多实例全额 | 已补；本轮环境错误 | `test_tb91_closing.py:190-268` 检查归属与全额计算；本轮 setup PG Connection refused。 | 后端；运维恢复隔离测试服务 |
| 必测④ 金额 unknown 拒绝买入/加仓 | **部分关闭（缺 API 断言）** | `test_tb91_closing.py:269-311` 有 allocations 抛异常、size_amount 回退和旧草案确认 stale，但没有“unknown 状态 POST /plan-drafts 拒绝 buy/add 并不写草案”的直接断言；不能把 helper 异常等价为完整端点拒绝测试。本轮该合并节点也未进入执行体。 | 后端 |

## 4. 新问题（只针对本次增量）

### N-I1｜重要｜新增关闭 RC1 警示的 level 违反统一枚举（后端）

- 位置：`src/backend/app/plans/generation.py:355-368`，尤其 `:360`。
- 新增 risk_flags 使用 `level="attention"`；统一 `src/backend/app/schemas/enums.py:171-174` / 契约 risk_level 只允许 info、warning、critical。PlanDraft 的 dict[Any] 未拦住，因此响应可带出非法枚举；严格客户端解析/显示不能保证正常。
- 定点核验：原样取新增警示对象调用共享 `RiskFlag.model_validate`，明确得到 enum 验证错误。未改代码、未访问数据库。现有无止损测试 `test_tb91_closing.py:348-350` 只看 control 和 gated_actions，漏了 level。
- 修复验收：使用既定合法级别，不新增枚举；补关闭 RC1 草案完整 RiskFlag 合约验证，包括 level。不得仅放宽客户端或模型来掩盖非法值。

### N-S1｜建议｜unknown 缺生成端点拒绝的精确回归（后端）

- 位置：`src/backend/selfchecks/test_tb91_closing.py:269-311`。
- T-A40 四项里，unknown 当前只测 helper 异常与旧草案确认 stale。建议在金额 unknown 的真实本人状态下分别 POST buy/add，断言具名 gap、拒绝、无新草案/计划/状态半提交；sell/reduce 不受其影响。代码已有拒绝路径，因此不把“测试不完整”误报为“实际放行”。

### N-S2｜建议｜RC1 关闭但存有止损时，数值和警示相互矛盾（后端）

- 位置：`src/backend/app/plans/generation.py:150-156,298-301,359-361`。
- loss 是否为 null 由是否有 stop_loss 决定，但警示无条件按 RC1 关闭输出“最大亏损无法计算”及 max_loss_amount gap。关闭 RC1、已有正止损且参考价高于止损时，会同时有计算值和“无法计算”。
- 建议区分“RC1 不主动监测”与“缺止损无法计算”；补关闭 RC1+已有止损场景。不应为了统一文案擅自把已有结果清空。

## 5. 05j：T-A37 I1–I3

| 项目 | 判定 | diff 证据 | 归属 |
|---|---|---|---|
| I1 本项解释绑定 | 关闭 | `src/frontend/src/api/types.ts` 的 Divergence/DailyReportStock 新增 optional nullable explanation；`src/frontend/src/pages/DailyReportPage.tsx:133` 只渲染 s.explanation 并按证券前缀过滤证据；`src/frontend/src/pages/SuggestionDetailPage.tsx:274` 只读 d.explanation。null/缺键不拿顶层补；`src/frontend/src/mocks/explanationFixtures.ts:164-189` 仅 MSW 构造独立、null、缺键场景，分歧引用按关联维度选择。 | 前端 |
| I2 fallback_reason | 关闭 | `src/frontend/src/lib/explanations.ts:1-11` 五个既定值文案及未知值原样展示；`src/frontend/src/components/ExplanationView.tsx:27` 区分新原因和旧模板缺键；fixture 的新记录补 fallback_reason 与调用 ID/null，未升级旧档。`p2n05-ai.test.tsx:137,196` 等覆盖。 | 前端 |
| I3 调用 ID 管理员可见 | 关闭 | `src/frontend/src/components/ExplanationView.tsx:12-14,39` 使用 useMe 已成功且 role=admin 才显示；加载/失败/未知/user 隐藏，不按 source 或 ID 非空推权限。`src/frontend/src/lib/explanations.ts:12-16` 页面未接入时只读不造可点击路由，未来页面存在才生成编码深链。`p2n05-ai.test.tsx:183-194` 等覆盖。 | 前端 |

## 6. 权限、事务、确定性、字段及目录边界

- 权限：报价适配按有效许可推导 owner，不接受 HTTP 自报 owner；条件 worker 重查许可；生成/预算/确认查询限定本人，旧快照只读。未看到本次 diff 放宽数据库角色或新增 DDL 授权。由于 PG 未运行，本轮不能重新证明 aia_api/aia_ingest 动态最小权限；T-B91 的原角色测试是历史证据，不能冒充本轮复验。
- 事务：生成在 engine.begin 下；正常完成才提交；耗尽分支只提交不可执行原因，不写半份草案；unknown 抛出让事务回滚。确认保留 owner 锁、账户行锁、候选校验及来源哈希，新增实例行锁和实时预算比较。回滚/并发用例已补但本轮未重跑。
- 确定性：预算实例与 plan_ids 排序；报价哈希冻结、UUID5 去重；价格/pct 用 Decimal，百分比 HALF_UP 四位。日期不拿未知日历当休市；RC1 不把缺复权证据默认为未除权。
- 字段：候选置信度对外改为两位 JSON number；max_loss nullable、用户快照允许 budget/plan_ids 等 T-A40 信息。发现新增契约错误 N-I1；不能因 PlanDraft 的泛化 dict 校验通过就认定 RiskFlag 合法。
- 目录：f28727d/38fc560 均仅 src/backend（含 selfchecks/fixtures），没有 deploy/、根 tests/、docs/ 修改；4333170 仅 src/frontend（含本角色相关定点测试）。未发现越权改其他角色目录。架构师本轮仅新增本文，不写 team/reports/T-A41.md，不提交 docs/strategies，不暂存其他角色 WIP。

## 7. 本轮定点检查及证据分级

1. 前端：在 src/frontend 执行 `./node_modules/.bin/vitest run src/pages/p2n05-ai.test.tsx src/pages/t-f12.test.tsx`，**2 文件、55 测试通过**。没有全量或 coverage。
2. 后端：在 src/backend 执行 `PYTHONPATH=. uv run pytest -q selfchecks/test_tb91_closing.py::test_actual_buy_add_null_budget_to_confirmation_and_number selfchecks/test_tb91_closing.py::test_budget_exhausted_reason_commit_and_recheck selfchecks/test_tb91_closing.py::test_budget_multi_full_allocation_latest_unknown_and_stale selfchecks/test_tb91_fixes.py::test_reviewed_synthetic_operands_only`，结果 **1 passed、4 setup errors**。4 个集成参数节点都因专用 PG Unix socket Connection refused，未进入业务断言；不是业务断言失败，也不是通过。未改连其他库、未重启/重建他人服务。初次未加 PYTHONPATH 的尝试在收集阶段报 app 导入缺失，修正路径后得到上述最终结果。
3. 受影响后端 17 个 Python 文件 ruff check 通过；新增警示的共享模型定点验证如 N-I1，确定拒绝非法枚举。
4. T-B91.md/evidence 声称历史 38/13 节点及最终复验通过；本文仅将其列为后端提供的历史离线证据，未将日志声明合并进本轮通过数。
5. 提交前对本文执行 secret_scan files 模式及 git diff --check；只以 pathspec 本地提交本文，不 push。

申请新任务：请派发后端 N-I1 修复、B2 生产接线及恢复隔离服务后的四项定点复验任务。
