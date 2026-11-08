# P2N-R08 RC5/RC6、健康度与降权：离线金标准 v1 / R08b裁定增量

## 范围与使用

- 本包92个独立案例：**92 ready + 0 blocked**（原001–083不变；084–092按T-A33/T-A36/T-A37解除未决）。全部虚构，不使用真实账户/成交/行情；不实调麦蕊，不改变阈值或来源等级。仅本包R08/R08b范围；不涉及R09或其他任务。
- 文件沿golden目录既有`<任务>_golden.json`、`check_<任务>.py`命名。JSON顶层task/schema_version/fictitious/source_registry/cases；每例有id、输入、步骤、单位、精度、期望、来源条款。**不是完整HTTP响应**，而是后端/测试可直接引用的单元级逻辑投影。
- 消费时只选择`case_status == "ready"`；按kind适配后端输出再断言expected。`blocked`必须显式skip/xfail并报告原因，expected=null不是通过标签、不是业务null结论。不得用本包自核替代实际实现测试。
- 本次定点执行：`python3 docs/strategies/golden/check_P2N-R08.py --r08b`。仅084–092九例41个内嵌情景；独立重算输入，9个期望篡改+9个输入篡改均拒绝。001–083只比对原提交规范化JSON/hash，不重复其oracle；原83通过记录沿用R08。默认无参数为整包入口，本轮未运行。零网络/业务导入/全量/coverage。

## 权威依据与非依据

规则以plan-phase2-next P2N-08、plan §2.5.6/2.5.7/2.8.2/6.1及api-contract §7.11.2–3/§6.0A为准。source_registry为每项具体文件/节/原文短引，自核验证短引仍可定位；不是以消息摘要裁定。P2N-09/plan §2.7/契约§7.11.4只确认“解释不改规则结论”，本轮不交付R09解释案例。

validation.md §6.2复述既定公式/阈值，§6.3明确是待确认建议，**不把它的主跟踪期、次日生效、覆盖率观察等建议偷偷定为本包规则**。cards/H-01、W-01 v2只作不改动作/优先级/止损的边界依据，未修改旧卡/夹具。compliance/versioning及risk_questionnaire已停用，不恢复问卷/同意门禁；固定disclaimer保持原文。

## 算术与状态语义

1. RC5闭仓：输入是按结束时刻排序、归集完成的已平仓损益CNY，负数严格<0，连续尾部>=3触发；原始成交如何归集不在这些ready案例中猜测。正值明确中断；平本、费用、分批平仓归集现由085依据T-A33补充。
2. 账户回撤：本包采用峰值与当前净值的正幅度`(peak-current)/peak*100`，9.99/10/10.01分别验证<、=、>10；peak为1000且路径齐全。当前净值null -> unknown，不前值/0补齐。这里不是TrackingResult负号的max_drawdown_pct，两者不可混用。
3. 模拟失败：ready仅计数**已由上游明确分类**的失败bool序列；4/5/6边界。084按正式T-A36选项B和T-A37最新映射补充本人、策略版本、去重、排序、complete分类；不是端到端验收。
4. RC6五种checks各有一正一反：opposite_side、qty_over_plan、held_after_invalidation、buy_without_stop、buy_during_wait。单例仅启用指定check，不据一项无命中宣称全RC6干净；失效例时刻严格早于评价。数量是单笔股数100/101，不把其当可执行整手委托校验；不新增交易下单。
5. as-of选择只用成交时已明确有效版本；旧版本不能被11点修订回填10点成交。重放仅验证一个逻辑事件，logical_event_key是测试标签，不规定生产数据库键。冲正例给定已重建有效闭仓集合，只重算风险，不承诺自动撤销暂停/历史事件。
6. 降权：`w_tilde=(wins+5)/(n+10)`；`e=tanh(avg_excess_pct/5)`，超额为pct（5=5%）；`raw=1+1.2*(w_tilde-0.5)+0.4*e`；clamp到[0.3,1.2]。n=19与n=0直接weight=1，n=20正常计算。关闭auto_downweight使本人的applied_weight=1，不关闭computed_weight或全站健康。
7. 12位参考值只为测试oracle，容差<=1e-12，**不是新增业务落库舍入规则**。其余比较全部Decimal精确，无二进制浮点。首次定稿用60位Decimal.exp参考；自核独立用Fraction胜率、80/90位Decimal及sinh/cosh Taylor级数重算，不运行生成器或比对AI答案自证。零超额有精确有理数锚点，回撤用交叉相乘另核10%边界。
8. clamp六例是纯算子raw上下/恰等边界，不伪造可达统计样本；另有n=100的真实公式组合覆盖上下clamp。
9. 健康输入为按交易日顺序、齐全、已计算的**全站**weight，prior_streaks均0；published的<0.8连续5日进入、observing的>=0.9连续10日恢复，恰等/断续序列均有例。内部评估关闭时不要求不存在的恢复数据；启用时只验证<70%进入及n<20优先，087现按T-A33第9点补恢复>=基线×0.8且与权重同时连续10日；关闭内部条件时忽略。
10. observing的<0.6连续20日仅通知管理员复审，恰0.6不触发；绝不自动retired。draft/simulating/retired不因好weight晋级/恢复。排序案例逐字段保留action/score/confidence/stops，不伪造G7批准。
11. 评价状态按disabled > 已知triggered（可同时缺数据）> 无触发且完整ok > unknown+gap。此处优先级来自契约，不拿缺数清除既知风险。
12. 暂停：pause_on_trigger开/关分开，用户resume系统暂停清空paused_by/pause_reason_code/paused_until并记录released_reason_code；用户暂停不系统恢复；不可运行版本用户resume为409。到期例使用**已存**paused_until的严格前/后，不擅算5交易日起点/日内时刻，也不把RC1时间止损规则移用于RC5。086/091/092补充T-A33裁定的第0天、15:00、max不叠加、期满不重挂及不可运行检查。

## 覆盖矩阵（ready）

| kind | 例数 | 范围 |
|---|---:|---|
| rc5_closed | 6 | 已平仓尾部0/1/2/3/4，正值中断 |
| rc5_nav | 4 | 回撤9.99/10/10.01/null |
| rc5_sim | 4 | 预分类模拟失败0/4/5/6 |
| rc6_plan | 10 | 五checks各一正一反 |
| weight | 13 | n=0/19/20/30/100，零/正/负超额，关闭本人降权 |
| clamp | 6 | 0.3与1.2上下及恰等 |
| health | 17 | 迟滞、连续性、n<20、不自动退役/晋级、关闭开关不关健康 |
| health_internal_entry | 3 | 内部复验<70%/恰70%及n19优先 |
| evaluation_state | 4 | disabled/triggered/unknown/ok优先 |
| rc5_correction | 1 | 冲正有效集重算，不自行恢复暂停 |
| rc6_asof | 1 | 成交时版本，不读未来修订 |
| rc6_replay | 1 | 同逻辑导入幂等 |
| rc6_missing_plan | 1 | 有效计划不足unknown |
| pause_release | 6 | 用户恢复、期限前后、用户暂停、不可运行版本 |
| pause_trigger | 2 | pause_on_trigger开关 |
| ranking_only | 4 | 四生命周期下动作/分数/置信度/止损不变 |

## R08b已解除的九项与覆盖矩阵

每个新kind对应一个顶层独立案例，`input.scenarios`与`expected.results`按位置配对；共41个情景。结果是单元投影，不新增API字段。所有场景纯虚构，金额/费用为CNY、单价CNY/股、股数shares、权重ratio、日数交易日，时间均UTC+8；内部稳健度为合成指数点。精确Decimal比较，不新订落库舍入。

| 案例 / kind | 情景数 | 权威条款及审阅结论 |
|---|---:|---|
| 084 / t33_sim | 8 | §7.11.3第2点T-A36 B、T-A37最新修正：intraday_t=1/short=5/swing=20/long=20；建议周期优先、版本后备、仍未知gap；本人/版本过滤、去重、非complete跳过、成功清零。RC5早期预警，不代替终评。 |
| 085 / t33_closed | 2 | 第3点；部分卖出不结段，费用计入，平本跳过；无开仓记gap；-1/0/-2/-3连亏3，后续+1清零。 |
| 086 / t33_expiry | 5 | 第4点及总则；第0天不含入N，恰15:00当日、之后次日、非交易日顺延；缺日历不推算。 |
| 087 / t33_recovery | 5 | 第9点；80恰等、79.99不足、9/10日、禁用内部条件、n19优先。 |
| 088 / t33_qty | 4 | 第6点；60+60>100，撤销后60，60+40恰等不触发，102也只一次；范围过滤。 |
| 089 / t33_version | 5 | 第7点；半开边界/同刻新版本、仅日期变更unknown+gap、无有效版本、同向优先/最新/id最小、无同向才opposite。 |
| 090 / t33_gap | 4 | 第8点；缺日两个计数清零，不拼接，缺后重新满5/10才跃迁。此例内部评估未启用。 |
| 091 / t33_edge | 4 | 第4点；新边沿max延长不叠加、同计数非新边沿、期满风险仍在但不重挂；恢复版本明确可运行。 |
| 092 / t33_resume | 4 | 第5点及总则；retired/simulating保持暂停、until=null、reason保留，system事件精确detail并通知；可运行恢复、无日历不解除。 |

原001–083规范化JSON逐例与原提交6d096cd0762ccafd55c7ae07c5d94abaeda299b1相同；仅验证内容不变，不重跑旧任务。新九例的review含输入hash和条款；source_registry短引定位当前权威原文。092的`system_event_detail=null`/`expiry_blocked_actor=null`只表示未产生本条“到期被阻止”事件的投影，不断言不存在其他事件或通知。088的logical_events只验重算后一逻辑事件，不模拟生产持久化/通知。oracle对这些合成输入确定性核算，不承诺覆盖任意成交匹配、交易日历或端到端实现；未决0不等于全量验收。

## DeepSeek与审计

DeepSeek：用于36条纯虚构损益/净值/失败序列、计划字段对与统计输入的机械草稿（产出目录reports/deepseek/P2N-R08/，实际team目录）。一次官方调用deepseek-flash，2026-11-08 16:54:44北京时间开始，6.201秒，2086 tokens；未重试、未发真实资料/契约原文/内部对话。输入与草稿均不含最终触发/健康/风控裁决。36条各关联draft_seed_id并逐项复核；n=0的平均超额占位0改为null，不采用AI算术作为真值。扩展状态/边界及9项歧义由研究员依据权威条款定稿。草稿仍原样留档为未核实原件，复核记录另存review.json。

R08b DeepSeek：复用上述R08虚构机械草稿（历史1次2086tokens），本轮0次/0tokens；未新请求模型，不以模型裁定阈值。独立核算及review见本包与team/reports/deepseek/P2N-R08b/。本角色只对本包三个精确路径扫描并本地提交，不推送、不触碰其他人的暂存。
