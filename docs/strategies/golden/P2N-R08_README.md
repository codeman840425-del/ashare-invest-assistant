# P2N-R08 RC5/RC6、健康度与降权：离线金标准 v1

## 范围与使用

- 本包92个独立案例：**83 ready + 9 blocked/spec_ambiguity**。全部虚构，不使用真实账户/成交/行情；不实调麦蕊，不改变阈值或来源等级。只交付R08，未开始R09。
- 文件沿golden目录既有`<任务>_golden.json`、`check_<任务>.py`命名。JSON顶层task/schema_version/fictitious/source_registry/cases；每例有id、输入、步骤、单位、精度、期望、来源条款。**不是完整HTTP响应**，而是后端/测试可直接引用的单元级逻辑投影。
- 消费时只选择`case_status == "ready"`；按kind适配后端输出再断言expected。`blocked`必须显式skip/xfail并报告原因，expected=null不是通过标签、不是业务null结论。不得用本包自核替代实际实现测试。
- 执行：`python3 docs/strategies/golden/check_P2N-R08.py`。零网络、零业务代码导入，不读模型草稿或生成器，不跑旧golden/全量/coverage。独立自核目前83 PASS；9未运行；4个损坏期望的负向oracle均拒绝。

## 权威依据与非依据

规则以plan-phase2-next P2N-08、plan §2.5.6/2.5.7/2.8.2/6.1及api-contract §7.11.2–3/§6.0A为准。source_registry为每项具体文件/节/原文短引，自核验证短引仍可定位；不是以消息摘要裁定。P2N-09/plan §2.7/契约§7.11.4只确认“解释不改规则结论”，本轮不交付R09解释案例。

validation.md §6.2复述既定公式/阈值，§6.3明确是待确认建议，**不把它的主跟踪期、次日生效、覆盖率观察等建议偷偷定为本包规则**。cards/H-01、W-01 v2只作不改动作/优先级/止损的边界依据，未修改旧卡/夹具。compliance/versioning及risk_questionnaire已停用，不恢复问卷/同意门禁；固定disclaimer保持原文。

## 算术与状态语义

1. RC5闭仓：输入是按结束时刻排序、归集完成的已平仓损益CNY，负数严格<0，连续尾部>=3触发；原始成交如何归集不在这些ready案例中猜测。正值明确中断；平本、费用、零股/分批平仓归集留blocked。
2. 账户回撤：本包采用峰值与当前净值的正幅度`(peak-current)/peak*100`，9.99/10/10.01分别验证<、=、>10；peak为1000且路径齐全。当前净值null -> unknown，不前值/0补齐。这里不是TrackingResult负号的max_drawdown_pct，两者不可混用。
3. 模拟失败：ready仅计数**已由上游明确分类**的失败bool序列；4/5/6边界。失败如何从direction_correct/收益/失效、跟踪期等导出尚未明确，端到端映射是blocked，不能自作定义。
4. RC6五种checks各有一正一反：opposite_side、qty_over_plan、held_after_invalidation、buy_without_stop、buy_during_wait。单例仅启用指定check，不据一项无命中宣称全RC6干净；失效例时刻严格早于评价。数量是单笔股数100/101，不把其当可执行整手委托校验；不新增交易下单。
5. as-of选择只用成交时已明确有效版本；旧版本不能被11点修订回填10点成交。重放仅验证一个逻辑事件，logical_event_key是测试标签，不规定生产数据库键。冲正例给定已重建有效闭仓集合，只重算风险，不承诺自动撤销暂停/历史事件。
6. 降权：`w_tilde=(wins+5)/(n+10)`；`e=tanh(avg_excess_pct/5)`，超额为pct（5=5%）；`raw=1+1.2*(w_tilde-0.5)+0.4*e`；clamp到[0.3,1.2]。n=19与n=0直接weight=1，n=20正常计算。关闭auto_downweight使本人的applied_weight=1，不关闭computed_weight或全站健康。
7. 12位参考值只为测试oracle，容差<=1e-12，**不是新增业务落库舍入规则**。其余比较全部Decimal精确，无二进制浮点。首次定稿用60位Decimal.exp参考；自核独立用Fraction胜率、80/90位Decimal及sinh/cosh Taylor级数重算，不运行生成器或比对AI答案自证。零超额有精确有理数锚点，回撤用交叉相乘另核10%边界。
8. clamp六例是纯算子raw上下/恰等边界，不伪造可达统计样本；另有n=100的真实公式组合覆盖上下clamp。
9. 健康输入为按交易日顺序、齐全、已计算的**全站**weight，prior_streaks均0；published的<0.8连续5日进入、observing的>=0.9连续10日恢复，恰等/断续序列均有例。内部评估关闭时不要求不存在的恢复数据；启用时只验证<70%进入及n<20优先，恢复定义留blocked。
10. observing的<0.6连续20日仅通知管理员复审，恰0.6不触发；绝不自动retired。draft/simulating/retired不因好weight晋级/恢复。排序案例逐字段保留action/score/confidence/stops，不伪造G7批准。
11. 评价状态按disabled > 已知triggered（可同时缺数据）> 无触发且完整ok > unknown+gap。此处优先级来自契约，不拿缺数清除既知风险。
12. 暂停：pause_on_trigger开/关分开，用户resume系统暂停清空paused_by/pause_reason_code/paused_until并记录released_reason_code；用户暂停不系统恢复；不可运行版本用户resume为409。到期例使用**已存**paused_until的严格前/后，不擅算5交易日起点/日内时刻，也不把RC1时间止损规则移用于RC5。未裁定的恰到期/再触发等留待澄清。

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

## 未决歧义（不混入通过数，需父级/架构师明确条款）

| 案例 | topic | 需要裁定 |
|---|---|---|
| P2N-R08-084 | sim_failure_mapping | 模拟失败究竟按direction_correct、绝对亏损、失效触发还是其他标志？跟踪期/排序/去重范围需明确；本包只验证上游预分类失败数列。 |
| P2N-R08-085 | closed_trade_grouping | 已平仓一笔按往返持仓段、成交、匹配批次还是其他？费用/平本是否中断/跳过及并列结束时刻排序需裁定。 |
| P2N-R08-086 | pause_expiry_origin | 5交易日起点是否第0天、到期盘前/收盘/原时刻未定；不能把RC1时间止损起点裁定移用于RC5。 |
| P2N-R08-087 | internal_recovery | 内部复验恢复没有明确数值条件；不得擅设>=70%或>=100%。 |
| P2N-R08-088 | rc6_cumulative_qty | 数量超计划按单笔还是累计、冲正后累积范围未定；本包只验单笔明显边界。 |
| P2N-R08-089 | rc6_plan_boundary | 同一时刻版本生效/关闭与成交先后及多计划选择无明确顺序，不猜半开区间。 |
| P2N-R08-090 | health_day_gap | 交易日缺统计时连续计数重置还是暂停未明；本包健康案例均明确连续且齐全。 |
| P2N-R08-091 | pause_retrigger | 重复触发是否延长/覆盖暂停期、期满但风险仍在是否立即重挂未明确。 |
| P2N-R08-092 | schedule_not_runnable | 用户resume的不可运行版本拒绝明确，系统期满恢复是否同样检查需明确；不能借此恢复退役策略。 |

以上歧义不阻断83个窄范围oracle使用，但不证明完整RC5/RC6/健康状态端到端通过。尤其不得从“预分类失败计数PASS”推出“模拟失败定义已闭合”。内部复验恢复、RC5到期计算/再触发、闭仓归集、RC6累计数量/同刻版本须先裁定再增量定稿。

## DeepSeek与审计

DeepSeek：用于36条纯虚构损益/净值/失败序列、计划字段对与统计输入的机械草稿（产出目录reports/deepseek/P2N-R08/，实际team目录）。一次官方调用deepseek-flash，2026-11-08 16:54:44北京时间开始，6.201秒，2086 tokens；未重试、未发真实资料/契约原文/内部对话。输入与草稿均不含最终触发/健康/风控裁决。36条各关联draft_seed_id并逐项复核；n=0的平均超额占位0改为null，不采用AI算术作为真值。扩展状态/边界及9项歧义由研究员依据权威条款定稿。草稿仍原样留档为未核实原件，复核记录另存review.json。
