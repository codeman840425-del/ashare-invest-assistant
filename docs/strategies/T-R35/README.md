# T-R35｜H-01 / S-01 模拟复盘方案（只读核对，2026-11-09）



> 事实陈述（编排者提供，本文照录）：H-01 与 S-01 于 2026-11-09 过了 G7 审批，**编排者代批**，`ack_warn_gates=[G6]`；生命周期仍为 `draft`。

> 本文用语一律「候选信号 / 计划条件」，不承诺收益。不写库、不启服务、不调麦蕊、不读凭证。



## 0. 审批记录核对（代码 / docs，只读）



| 核对项 | 结果 | 出处 |

|---|---|---|

| G7 是否允许代理/脚本代批 | **不允许** | plan.md §2.5.13：「G7：由用户本人以管理员身份…批准。代理只准备报告，不代为批准。」；契约 §7.4 / api-contract.md:953 T-A18③ / T-A20；`promotions.py:55-71` `human_admin`：Bearer → `403 HUMAN_SESSION_REQUIRED`；会话须 `origin=="password_login"` |

| 批准是否须本人密码 | **是** | api-contract.md:953；`promotions.py` DecisionRequest.password + `reauth.transaction` |

| `ack_warn_gates` 语义 | 批准时每个 G1–G6 的 `warn` 必须列入，否则 `422 PROMOTION_WARN_UNACKNOWLEDGED` | api-contract.md:501,953；`reviews.py:307-313`；晋级时再校验 `reviews.py:467-475` |

| 仓库 docs 内是否见「用户本人确认」H-01/S-01 G7 记录 | **未见** | 只读检索 strategies/reviews/handover：多见「代理不代批 / G7 未执行 / 仍 draft」；**无** 2026-11-09 用户本人批准确认文。编排者代批作为外部事实照录，**与现行审批规则不符**（规则要求本人交互会话） |

| 生命周期仍 `draft` 是否与「已批 G7」相容 | **相容（两步分离）** | 契约：decision 与 lifecycle **两步**（api-contract.md:960）；`decide()` 只改 review（`reviews.py:329-398`），`change_lifecycle(draft→simulating)` 另调（`reviews.py:401-519`）且须带已批准 `review_id` |



**结论（核对）**：若仅有「代批」而无符合 T-A18/T-A20 的本人会话审计，则按规则 **G7 不应视为有效**；即便存在有效 `approved` review，未调 lifecycle 前版本保持 `draft` 符合设计。本文以下方案在「若/当合法进入 simulating」前提下写复盘口径，不假定库内状态已变。



---



## 1. draft → simulating：前提与操作路径



### 1.1 前提条件（须全部满足）



1. 目标 `strategy_versions.lifecycle == draft`（表约束见 migrations `0001_baseline` lifecycle 枚举）。

2. 存在绑定本版本的 `strategy_promotion_reviews`，且 `decision=approved`、非 stale（绑定 `version_id` + `content_sha256` 与当前一致）。

3. G1–G6 无 `fail`（`pass`/`warn` 可）；每个 `warn` 已在决策时写入 `compliance_lint.ack_warn_gates`（本背景为 `[G6]`）。

4. G7 结果为 `pass`，且 `compliance_lint.human_review == {"origin":"password_login"}`（`reviews.py:460-465`）。

5. 调用方为管理员 **浏览器交互会话** + 本次请求密码复核（`HUMAN_SESSION_REQUIRED` / `REAUTH_FAILED`）。



### 1.2 系统操作路径（已实现）



| 步骤 | 接口 / 行为 | 出处 |

|---|---|---|

| A. 申请审核 | `POST /strategy-cards/{card_id}/promotion-requests` body `{version_id}` → 202 + review | `promotions.py:90+`；跑 G1–G6 写 `gate_results` |

| B. G7 决定 | `POST /admin/promotions/{review_id}/decision` `{decision, comment, ack_warn_gates, password}` | `promotions.py:183+` → `reviews.decide` |

| C. 生命周期 | `POST /admin/strategies/{id}/versions/{vid}/lifecycle` `{to:"simulating", reason, review_id, password}` | `promotions.py:211-234` → `reviews.change_lifecycle` |

| D. 前端入口 | `/admin/strategy-gates` 批准弹窗勾选 warn、密码框 | `AdminStrategyGatesPage.tsx`；契约路由说明见 first_batch_import.md §5 |

| 状态字段 | `strategy_versions.lifecycle`；事件 `strategy_lifecycle_events`；审计 `promotion.decision` / `strategy.lifecycle` | `reviews.py:488-518`；tables/strategy.py |



### 1.3 未实现 / 待定



| 项 | 说明 |

|---|---|

| `simulating→published` 证据链 | 代码**硬拒**：`reviews.py:476-484` 注释写明 MVP 无 plan §2.5.13 verified_live+模拟证据链，一律 `PROMOTION_GATES_NOT_MET` |

| CLI 代批 / 无密码晋级 | **未实现**（且规则禁止）；无绕过 `human_admin` 的正式入口 |

| 普通用户实例化 simulating | MVP 仅管理员（plan I1 / 契约 §6.0A 第 9；`instances/creation.py:182-183`）；自愿参与属 T-B79 **待定** |

| 本环境库内 H-01/S-01 review 行 | **未查库**（本任务禁止读凭证/写库）；是否已有 approved review **待运维/用户在隔离库核验** |



### 1.4 当前是否已满足「可模拟」



按编排者陈述：G7 代批 + 仍 draft → **lifecycle 前提未走完**，系统不会产生 simulating 候选信号。另：代批本身与规则冲突 → **合规前提未满足**，阻塞正式晋级，直至用户本人按 T-A18/T-A20 重做 decision（或架构师另裁例外——**本文不自定例外**）。



---



## 2. 「20 个交易日模拟复盘」指标与阈值



### 2.1 已有出处的正式口径（复盘 / 发布门槛）



| 指标 / 门槛 | 公式或定义 | 出处 |

|---|---|---|

| 发布样本门槛 | 模拟样本 **n ≥ 20** **或** 模拟满 **20 个交易日**；且必需字段全部 `verified_live`；管理员批准 → `published` | plan §2.5.13 |

| 跟踪窗 | 每条候选信号在 **T+1 / T+5 / T+20** 交易日收盘后算区间收益、基准、超额、最大回撤/上涨、失效是否触发 | plan §2.8 |

| 入场价 | 盘后信号 → T+1 开盘；盘中 → 下一根 1 分钟 bar 开盘 | plan §2.8.1 |

| 方向正确 | buy/add：超额>0；sell/reduce：超额<0；hold：\|超额\|≤阈值（T+1=1.0%、T+5=2%、T+20=5%，§9 C(7)）；wait 不计胜率；T+1 hold 只展示不进健康度 | plan §2.8 |

| 不可成交 | 一字涨停买不进等 → 不计胜率但计数展示 | plan §2.8.1 |

| 统计分组 | 策略版本 × 周期 × 范围(本人/全站) × 跟踪期(1/5/20) → n、胜率、平均收益、平均超额、盈亏比、最大连续亏损、最近 20 次 | plan §2.5.7 |

| 自动降权权重 | \(\tilde w=(wins+α·0.5)/(n+α)\)，α=10；\(e=\tanh(avg\_excess\_pct/s)\)，s=5；\(raw=1+β·(\tilde w-0.5)·2+γ·e\)，β=0.6、γ=0.4；`weight=clamp(raw,0.3,1.2)`；**n<20 时 weight=1** | plan §2.5.7 |

| 展示样本标注 | n<5 不显示数值；5≤n<30 标样本少；n≥30 正常（**展示阈值**，≠发布门槛） | plan §2.5.14 H⑧ / §2.12.3 |



数据字段（实现侧，只读点名）：`suggestion_tracking`、`strategy_tracking_stats`、`user_strategy_weights`（plan §2.5.7/§2.8）；具体列以 migrations/ORM 为准，本方案不臆造列名。



### 2.2 建议值（待架构师/用户裁定，非正式口径）



| 建议项 | 建议值 | 为何待裁 |

|---|---|---|

| 「统一 20 日复盘窗」与多跟踪期报表如何并存 | 建议：发布资格用 §2.5.13 的 n≥20 **或** 满 20 交易日；日常报表仍出 T+1/5/20 三列 | plan 同时存在两套窗，未写「只用 20 日一列」 |

| H-01 多周期样本如何计入 n | 建议：按结论 `horizon` 分桶；缺 horizon 的观测不进胜率（与 RC5 gap 对齐） | TB-A48 / R10：版本无唯一周期 |

| G6 warn 是否计入「模拟健康」否决 | 建议：仅审计标记，不自动挡 simulating 内信号 | 代码：warn+ack 可批准；无「G6 warn→降权」条文 |



边界：只用当时可得日 K / 已落库跟踪行；缺日按 T-A33（契约 §7.11.3）健康度连续计数缺日清零——**不编造**填充收益。



---



## 3. 健康度口径（健康 / 观察 / 退役）



| 状态 | 如何进入 | 运行效果 | 出处 |

|---|---|---|---|

| 健康 ≈ `published` | simulating 满足 n≥20 或满 20 日 + verified_live + 管理员批准（MVP 代码路径未接通，见 §1.3） | 正常候选信号 | plan §2.5.13 / §2.8.2 |

| 观察 `observing` | **仅**自 published：n≥20 且（weight<0.8 连续 5 日 **或** 内部复验<基线 70%） | 继续跑，带「观察中」；可降权排序 | plan §2.8.2 |

| 提示复审 | observing 且 weight<0.6 持续 20 日（或内部稳健度<50%×20 日）→ 通知管理员 | 不自动退役 | plan §2.8.2 |

| 退役 `retired` | **仅管理员确认** | 不再出新候选信号；历史可回看 | plan §2.5.13 / §2.8.2 |



**注意**：`observing` **不能**从 draft/simulating 手动设置（T-A14 / card_promotion_gates S-01）。simulating 阶段的「表现差」只影响标签/排序（若启用 auto_downweight），**不是** observing 状态机。



---



## 4. 失败退回与 RC5（口径 B）



### 4.1 RC5 模拟失败预警（早期预警，非终评）



- 范围：**用户本人** × **策略版本**（T-A36 B）。

- 失败 ⇔ tracking `state=complete` 且 `direction_correct=false`（契约 §7.11.3）。

- 跟踪期映射：`intraday_t→1`，`short→5`，`swing→20`，`long→20`（T-A37）；配置键 `rc5_loss_streak_drawdown.sim_fail_horizon_by_horizon`（plan.md:780；yaml 段 plan ~3023；实现 `feedback/core.py` / `pause.py`）。

- horizon 回退：结论 horizon → 版本唯一声明周期 → 否则跳过 + gap `sim_fail_horizon_unknown`，**不默认 5**（契约 §7.11.3；TB-A48）。

- 连续失败 ≥5 → 账户/策略级 risk_flag + 通知；暂停可恢复（RC5 预警属性）。

- **终评**仍归 §2.5.7 跟踪统计与 §2.8.2 健康度/管理员复审——RC5 不替代。



### 4.2 必须点明的口径风险：统一 20 日复盘 vs RC5 按周期



| 维度 | 复盘 / 发布窗 | RC5 失败预警窗 |

|---|---|---|

| 目的 | 样本积累与是否够格申请 published | 早期连续失败预警 |

| 长度 | plan 写「n≥20 或满 20 交易日」；跟踪报表固定 T+1/5/20 | 随策略周期 1/5/20 |

| **S-01** | 若用「满 20 交易日」作发布观察窗，长于其 RC5 窗 | `horizons=[short]` → RC5 用 **5** 日跟踪判定失败 |

| **H-01 v2** | 同上 20 日观察不自动等于某周期 | `horizons=[intraday_t,short,swing,long]`（cards/hold_risk_monitor.md；R10）：版本级**无唯一周期**；结论缺 horizon → RC5 **跳过**并记 `sim_fail_horizon_unknown`（不得回填 swing / 不得取数组首元素，TB-A48 R3） |



关系一句话：**20 日是「模拟是否够久/够样本」的复盘与发布资格窗；RC5 是「按周期看连续方向错误」的预警窗。二者并行，不可用 20 日替代 short=5，也不可因 H-01 挂载 swing 而给缺 horizon 的观测填 20。**



**待裁定（不自定）**：H-01 是否拆成每周期一个版本（或强制结论必带 horizon）以消减 `sim_fail_horizon_unknown`——见 §5。



### 4.3 `ack_warn_gates=[G6]` 含义与对模拟的影响



- **含义**：G6 自动结果为 `warn`（非 fail），批准人显式确认该警告（常见原因：历史不足 → `max_jaccard` null + `no_history`，G6 仍 warn——`g6.py:52-55`；T-A17）。fixtures 失败则为 fail，**不能**仅靠 ack 批准（`reviews.py:301-306`）。

- **对模拟**：ack 只满足「允许 decision=approved / 允许 draft→simulating」的门禁手续；**不**把 G6 统计改写为 pass，**不**免除 simulating 内跟踪与 RC5，**不**等同 verified_live，**不**自动 published。

- 若 G6 warn 来自「120 日体检不足」，进入 simulating 后仍应用真实跟踪积累 n；不编造 G6 历史收益。



---



## 5. 待裁定清单



1. **G7 代批效力**：是否承认 2026-11-09 编排者代批，或必须用户本人按 T-A18/T-A20 重批？（规则现状：必须本人）

2. **H-01 版本策略**：保持四周期 + 结论必填 horizon，还是拆版本？（影响 RC5 gap 率）

3. **「统一 20 日复盘」产品表述**：是否仅指 published 门槛，报表是否仍强制三窗并列？

4. **S-01 发布观察**：满 20 日 vs 以 short 的 T+5 为主报表是否双重展示？

5. **simulating→published MVP 证据链**：何时实现（代码现硬拒）？



---



## 6. 辅助索引



机器可读字段槽见同目录 `metrics_slots.json`（正式阈值以本文 §2.1 / plan 为准；DeepSeek 分组草稿见 team/reports/deepseek/T-R35/，未核实）。
