# 首轮空跑判读样张（R-05）

> R-02 §7 的首轮实例；供编排者统一发布时参考。对象是已经完成的 **T-B136-official 首轮空跑**，本页全部观察值来自该轮冻结产物及执行记录。r2 的正式结论须另页填写和复核。

**结论：当前不可评价策略。** 首轮原结论为 `data_insufficient`，`promote=false`，原因为 `P1 samples insufficient`。时点 ST、上市状态历史和终止上市名单三项输入缺失；各年 ST/上市状态未知计数分别等于全部股票日，有效可评估股票日为 0。未产生有效腿，无法据此判断收益、成本实现或择时效果。

范围：run_id 使用执行目录标签 `T-B136-official`（summary 未提供原生 run_id）；全量输入检查及首轮空跑，不含 r2。执行记录 E 报告北京时间 **2026-11-11 08:40:31—09:10:15**、代码 `d4405a8d64420acba2ffb880bc977cfe5059dd45`；方案由 S 自述为 `6814edc61ac85db3464d793a28df73191cc7df7e`，seed=136。结果截止时间取 E；本次取证时间见[观察值快照](first_run_observations.json)的 `captured_beijing`，两者分列。

证据：首轮三件套齐全，本次读前/读后 SHA256 均与已有记录一致；执行代码/配置/依赖的完整历史复现证据仍不齐。独立复核状态：**本样张待独立复核**，既有 T-R67 首轮结构核验不是本页或 r2 的终验。

关键结果：**170 条 trial，全为训练阶段；0 条腿；评估候选、R 对照、敏感性和保留集均未执行。** 五窗口的 n=0、days=0 为候选缺失后的空态统计；均值和区间不可估。红旗与缺证：首页维持黄色［数据阻断/待核］；没有有效腿可供成本、分布及 R 组核验，不能因没有红色已确认项而标全绿。

## 1. 证据索引

[观察值快照](first_run_observations.json)只保留原生状态、空值和聚合计数，不是原三件套或运行环境备份。以下别名加字段路径构成本页定位；定位 S/T/L 时，分别使用该文件的完整 SHA，不能使用快照 SHA 代替。

| 别名 | 首轮证据 | SHA256 | 本次核对范围 |
|---|---|---|---|
| S | `summary.json`，15,566,003 字节 | `ca0b88e8c3a3b41dc12fed198b393bcec4e4a04d2601f9c8bc2767347bd963bb` | 下表引用的原生字段和拼接聚合 |
| T | `trials.csv`，97,426 字节 | `7c4a6c22df742d41538e355fab62ffaa3a539937a70058a33649cfd8eab4ee26` | 16 列、170 数据行、phase/group/status/n 与空统计量 |
| L | `legs.csv`，413 字节 | `10591b3db7bc1758339ee6eff286a141fdebc5dfa24a7d40ea6701fbad0adb0a` | 41 列、0 数据行，只有表头 |
| E | 首轮 `reports/T-B136-official-run.md` | `f3b11e0f8209abf6f1857b9ef05beb03c8787081f73267723f938ecf4cfec8c3` | 执行版本/时间、正常退出及各阶段执行范围；不是 summary 自证 |

窗口身份另核[冻结 experiments](https://github.com/codeman840425-del/ashare-invest-assistant/blob/d4405a8d64420acba2ffb880bc977cfe5059dd45/src/backend/retest/t_r58/experiments.py#L406)与[冻结 judgement](https://github.com/codeman840425-del/ashare-invest-assistant/blob/d4405a8d64420acba2ffb880bc977cfe5059dd45/src/backend/retest/t_r58/judgement.py#L184)：本次只读源码与该提交的 Git blob 一致。先由代码的 phase/segment 绑定确认 P1 五窗顺序，再使用索引；不是从五个相同的零值猜身份。

## 2. 五窗口主表

收益和成本单位均为 bp of N（每腿名义金额，1bp=0.01%），不是账户收益率或年化。表内 n/days 均为 **S 的空态输出**；执行状态来自 T 的 phase 缺行、E 以及冻结控制流。不存在对应 trial_id 时直写“无”，不能造 `selected_A` 行。

| 窗口 / phase / segment | 日期范围 | 候选/方向；trial_id | 有效腿 n | 有腿交易日 days | 扣费均值（bp） | 95% 区间（bp） | 平均往返成本（bp） | 执行状态及证据 |
|---|---|---|---|---|---|---|---|---|
| 评估折1 / `evaluation_1` / `fold2` | 2023-10-18—2024-04-23 | 未选出/无；无 | 0 | 0 | 不可估 | 不可估 | 未提供 | 未执行候选评估；S:`criteria.P1.windows[0]`，T 无该 phase |
| 评估折2 / `evaluation_2` / `fold3` | 2024-04-24—2024-10-30 | 未选出/无；无 | 0 | 0 | 不可估 | 不可估 | 未提供 | 未执行候选评估；S:`criteria.P1.windows[1]`，T 无该 phase |
| 评估折3 / `evaluation_3` / `fold4` | 2024-10-31—2025-05-08 | 未选出/无；无 | 0 | 0 | 不可估 | 不可估 | 未提供 | 未执行候选评估；S:`criteria.P1.windows[2]`，T 无该 phase |
| 评估折4 / `evaluation_4` / `fold5` | 2025-05-09—2025-11-10 | 未选出/无；无 | 0 | 0 | 不可估 | 不可估 | 未提供 | 未执行候选评估；S:`criteria.P1.windows[3]`，T 无该 phase |
| 保留集 / `holdout` / `holdout` | 2025-11-11—2026-11-10 | 未选出/无；无 | 0 | 0 | 不可估 | 不可估 | 未提供 | 未执行；S:`criteria.P1.windows[4]`、`checks.L7.holdout_runs=0`，E |

日期是预设窗口边界，不表示已经评估了该日区间。days=0 是有腿日数，不是市场开市日数。零腿时 S 的 mean/low/high 均为 null，T 的 mean_bp/ci_low_bp/ci_high_bp 均为空单元格；不得呈现为 `0.00bp`、有效 CI 或显著性结论。

## 3. P1—P10 原生状态与判读

要求仅引用[冻结方案 §8.3](https://github.com/codeman840425-del/ashare-invest-assistant/blob/6814edc61ac85db3464d793a28df73191cc7df7e/docs/strategies/T-R58/retest_plan.md)；本表不新增门槛。所有 S 路径均受上表 S 的 SHA 约束。

| 判据 | 本次观察值 | 方案要求/用途 | 原状态 → 呈现 | 证据与补证责任 |
|---|---|---|---|---|
| P1 | 五窗各 n=0、days=0 | 每窗 n≥30、覆盖≥20 个有腿交易日 | `fail` → 样本门槛未满足 | S:`criteria.P1`；后端交付补齐输入后的冻结结果，不能据此否定策略 |
| P2 | 五窗均值/区间不可估，robustness=null | 保留集正均值/正区间下限，四折至少三正及稳健性同号 | `unknown` → 不可判 | S:`criteria.P2`+P1；研究员待有腿后读，不用 null 推符号 |
| P3 | 平均往返成本=null；保留集均值不可估 | 净均值大于两倍平均往返成本 | `unknown` → 不可判 | S:`criteria.P3`；复核需同 trial 的实腿五项费用，不能用约30bp推导代填 |
| P4 | share=null；L 无腿，分母为0 | 问题了结并集占比≤30% | `unknown` → 不可判 | S:`criteria.P4`；后端/复核补同范围 reason 与分母，不把0/0写0% |
| P5 | paired.n=0、days=0、mean/low/high=null | A*−R 配对差及区间下限为正；核对配对范围 | `unknown` → 不可判 | S:`criteria.P5.paired`、L；R 未执行，后端另补逐腿或等价控制证据 |
| P6 | neighbors=[]，没有 A* | 训练选定值及邻域稳定性 | `unknown` → 不可判 | S:`criteria.P6`；不能把空列表视为邻域全通过 |
| P7 | 标签2023=down、2024/2025=up；两环境均n=0、days=0、均值/区间null | 两环境有可评估证据且各自不显著为负 | `unknown` → 不可判 | S:`criteria.P7`；已有标签不等于有两组样本，研究员待实腿统计 |
| P8 | 1万元及0.03%两档 train/holdout 均null；training_brackets/boundary=null | 敏感性与训练边界的原定观察用途 | `unknown` → 不可判 | S:`criteria.P8`、E；后端交付实际执行的敏感性，不套佣金推导 |
| P9 | state=unknown；缺终止名单；hf_pool_delisted=177 | 退市覆盖及尾段核验 | `unknown` → 不可判 | S:`criteria.P9`、`delisting`；数据负责人补名单/尾段证据，另按当轮生效裁定审查 |
| P10 | directions=[] | 按训练窗口决定启用方向 | `fail` → 未得到可启用方向 | S:`criteria.P10`；不是已证实某方向收益≤0，不从保留集反挑方向 |

## 4. 红旗与缺证（逐项留存）

红旗编号沿 R-02 §4。黄色表示没有足够执行证据或尚未完成该项核验；本次不将首轮的空态说明升级为实现正确，也不把历史文案里的“未命中”扩大成已完成全部检查。

| 编号 | 状态 | 本次观察/证据范围 | 影响与负责人 |
|---|---|---|---|
| R0 | 黄色［缺证］ | S:`checks.L2/L3/L5/L6/L8/L13.state=no_eligible_legs`；若干检查仅留evidence文案 | 空态不证明有腿路径已通过；后端/测试补执行断言和定点证据 |
| R1 | 黄色［不可判］ | S:P1/P2；四折与保留集均无收益分布 | 无法比较时间趋势或回落；研究员待有腿 |
| R2 | 黄色［未执行/缺证］ | S:P3/P5/P8；E:R与敏感性执行0次 | 无法核R净成本/最低佣金/冲击方向；复核待费用证据 |
| R3 | 黄色［未执行］ | S:`holdout_by_source`两段n=0、均值null；L7=0 | 拼接前后收益不可比；研究员待保留集正式产物 |
| R4 | 黄色［缺证］ | 无有效成交/容量轨迹，L仅表头 | 无法比较2026-04-13前后成交行为；后端/复核补轨迹 |
| R5 | 黄色［未执行］ | S:`checks.L5.state=no_eligible_legs` | 分段印花税未获真实模拟腿验证；复核待有腿 |
| R6 | 黄色［不可判］ | 有效可评估股票日=0，L腿数=0 | 触发率分母为0，不能报告0%或策略弱；研究员待补数后重新归因 |
| R7 | 黄色［未执行］ | S:`checks.L6.state=no_eligible_legs` | T+1/底仓路径无执行样本；后端/测试补证 |
| R8 | 黄色［不可判］ | S:`checks.L13.state=no_eligible_legs` | 无法给不可成交率；后端补有意义分母与计数 |
| R9 | 黄色［不可判］ | L无reason数据行；S:P4.share=null | 无时间止损分布；研究员/复核待有腿 |
| R10 | 黄色［部分有据/其余待核］ | T仅五训练phase；S:L7 holdout_runs=0；E同述 | 已见保留集未开；时序/embargo/了结路径仍缺腿证据，测试续核 |
| R11 | 黄色［数据阻断］ | S:P9 unknown、termination_list_sha256=null | 尚非P9已确认fail；数据负责人补名单与尾段，禁止用后轮计数回填 |
| R12 | 黄色［缺证］ | L无估值/除权腿；S:data.gbbq_revision_bias=unable_to_verify | 无法核无法估值率与除权价格；后端/复核补证 |
| R13 | 黄色［未执行/缺证］ | S:P5.paired.n=0；L无control_mean_bp/control_n_ok列 | R未执行，汇总0=0不证明逐腿1:1；后端补控制轨迹或等价证据 |
| R14 | 黄色［数据阻断］ | S:`exclusions[年].st_unknown / checks.L9.stock_days[年]`各为100% | 与“未知剔除为0”疑点方向相反；实际是整日剔除，数据负责人补时点状态 |

## 5. 附表：训练登记、覆盖和分母

T 的170行来自 `training_1`、`training_2`、`training_3`、`training_4`、`training_final` 各34行；按group为 A=105、B=25、CA=20、CB=20；按status为 no_legs=130、base_unselected=40。**170行的n均为CSV字符串`0`，不是空值**；selected均为False，均值和CI单元格为空。不能把训练记录当评估腿，也不把 `base_unselected` 计为已执行量比策略。

| 年 | 全部股票日（分母） | ST未知（分子/分母） | 上市状态未知（分子/分母） | 有效可评估股票日 |
|---|---|---|---|---|
| 2022 | 1,310,914 | 1,310,914/1,310,914=100% | 1,310,914/1,310,914=100% | 0 |
| 2023 | 1,310,914 | 1,310,914/1,310,914=100% | 1,310,914/1,310,914=100% | 0 |
| 2024 | 1,310,914 | 1,310,914/1,310,914=100% | 1,310,914/1,310,914=100% | 0 |
| 2025 | 1,316,331 | 1,316,331/1,316,331=100% | 1,316,331/1,316,331=100% | 0 |
| 2026 | 1,110,485 | 1,110,485/1,110,485=100% | 1,110,485/1,110,485=100% | 0 |

来源 S:`checks.L9.stock_days`、`exclusions`。两个未知原因重叠，不能加成200%；股票日分母含warmup等状态，不能当触发率分母。原根级coverage缺失，原data三项coverage/摘要为null，不补成空对象或0%。首轮池为HF 5,387、vipdoc-only 30、HF退市177、BJ=0，不能外推为全A股覆盖。

## 6. 附表：拼接、费用、敏感性与R组

| 项 | 本轮观察 | 证据与限制 |
|---|---|---|
| 拼接/来源 | S:`splice`的5,417/5,417项ok=true；L14.stocks_checked=5417，one_source_per_stock_day=true | 拼接摘要不是收益路径核验；vipdoc单只读快照、shared_date_use，independent_package_equality=not_applicable |
| 两段保留集 | through_2026-08-06与from_2026-08-07均n=0、days=0、mean/low/high=null | S:`holdout_by_source`；未开保留集，不解释为两段实测一致 |
| 数据质量报告项 | missing_bars=110,127,600；bar_ok_failed=4,074,747；snapshot_revisions与gbbq_revision_bias均unable_to_verify | S:`checks.bar_quality`、`checks.L11`、`data`；保留风险，不自动变成策略判据 |
| 佣金/印花税/过户费/滑点/冲击 | 金额（元）均未提供；每腿均值（bp of N）均不可估 | L无数据行、S:P3平均成本null；空集合费用和不能当每腿成本0元/0bp |
| 基准0.025%、0.015%与0.03%佣金敏感性 | 基准费率见T的params与E；各档可比腿、实际双边佣金差和净收益差均无观察值 | E:R与敏感性0次；不得把+1/−2bp成本推导填为本轮观察 |
| 名义1万/20万元敏感性 | 本轮未执行，无可比成交腿与区间 | T无敏感性phase，E；P8仅保留原有两档null结构，不补新原生键 |
| R组 | P5.paired.n=0；净均值/成本/配对区间/20次抽样完成数均无证据 | E未执行R；trials无R行、legs无control列；R均值也不可反推 |
| 多重性 | family=34；34项raw_p=1.0、holm_p=1.0、conservative_p1=true；dsr=null | S:`multiplicity`；无样本保守占位，不是有效统计检验或“无显著收益”的证据 |
| P9正文交叉核 | 本首轮仅有hf_pool_delisted=177、state=unknown | S:`delisting`；T-R66b后续12只正文核对及后轮188只分类均不得回填本轮 |

佣金补充说明仅为 **RV-01 发现后的勘误推导**：固定每边成交额N=50,000元、两边均不触最低佣金、其他费用与腿不变时，0.025%→0.03%双边佣金25→30元，成本+1bp、净收益−1bp；0.025%→0.015%双边佣金25→15元，成本−2bp、净收益+2bp。N=10,000元且每边成交额相同时三档均各收5元，差值为0。这些数值不属于本轮实跑敏感性。

## 7. 剩余补证与换数

后端交付补数后冻结三件套及代码/完整配置/依赖/状态输入SHA的执行sidecar；复核补费用、R控制及全量冻结核验，测试完成R1—R5，研究员按T-R68预筛后由T-R66完成正式判读。具体触发与换数对应见[换数说明](README.md)。首轮归因不得自动沿用到r2，若r2仍零腿须重新核对数据和控制流。

供编排者采用的摘要：“首轮输入的时点状态和终止名单不齐，170条训练登记未产生交易腿，保留集尚未执行。本次尚不能评价策略，补齐输入并完成冻结核验后再判。”本样张不改变策略生命周期，不构成G7或部署批准。

DeepSeek：未用；环境无可用凭据，本单为既有观察值的确定性提取与研究核对，规则和结论不外包。

申请新任务：r2正式三件套冻结后，按原优先级进行预筛、复核和T-R66判读。
