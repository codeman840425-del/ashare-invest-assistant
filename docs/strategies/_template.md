# 策略知识卡模板（T006 · v0.2 草案）

> 作者：量化策略研究员 · 2026-11-01（v0.2 按 plan §2.5.14 契约与 T003 报告修订）
> 依据：`/workspace/team/vision.md`《策略卡字段定稿》（用户 11:52 表 + 编排者补充 + 不可执行原因 + 11:56 硬性原则）；`docs/plan.md` §2.5.14（导入契约，**字段名、结构、枚举以它为准**）、§0B、§2.5、§2.8、§2.12、§2.13；`docs/strategy-references.md` §3；`/workspace/team/reports/T003-mairui-capability.md`（2026-11-01，大部分接口未实测）。
> **字段覆盖以 vision.md 定稿为准，字段名与格式以 plan §2.5.14 为准**。两者的关系：§2.5.14 B 节是导入的最低要求，本模板多出来的字段由导入器存进 `extra` 并在详情页展示（§2.5.14 G）。差异见文末附录 B。
> 数据：本模板里的 `f.xxx` 是**本项目的特征键**（要在 `feature_catalog` 登记，未登记的写进 `validation.feature_requests`），**不是麦蕊字段名**。T003 报告里列出的麦蕊接口与因子 ID 只来自官方文档，绝大多数未实测；引用时一律写"文档已列·待T003验证"。

---

## 0. 怎么用这份模板

### 0.1 正式卡与示例的标记规则（导入器据此识别，务必遵守）
- **正式策略卡**：每个文件只放一张卡，机器可读部分写在一个以 `yaml strategy-card` 为信息串的围栏代码块里（三个反引号 + `yaml strategy-card`）。可选再加 `yaml strategy-spec` 和 `yaml validation` 两种块（§2.5.14 A），或者像本模板这样把 `rules`/`params_schema`/`stops` 和 `validation` 作为顶层键放在同一个卡片块里（§2.5.14 G，两种写法都接受）。
- **模板和示例**（包括本文件附录 A、`catalog.md`）**一律不用这个标记**，只用普通 `yaml` 代码块，否则会被导入器当作真卡。
- 正文文字会作为 `narrative` 原样保存，可以自由写说明。
- 文档中不得出现真实账户、股东代码、真实持仓或金额；示例证券只用 `600000.SH` 这类虚构示例（§2.5.14 A）。

### 0.2 三层与本模板的关系
| 层 | 本模板里要完成的内容 | 状态 |
|---|---|---|
| L1 策略知识卡（解释用） | 标 **[B]**（§2.5.14 B 节必填）和 **[L1]** 的字段必须填；规则可以只写文字并标 `status: to_quantify` | 系统计算 `completeness` |
| L2 可运行模板 | 标 **[L2]** 的字段全部填完；所有规则 `quantified`、所有特征在 `feature_catalog` 白名单内；通过 G1–G7 | `draft` → `simulating` → `published` |
| L3 实例与计划 | 标 **[SYS]** 的字段由系统回填。**文档里不要填**，填了也会被忽略（§2.5.14 B/G） | — |

- **[B]** = §2.5.14 B 节必填；**[L1]** = vision 定稿要求、知识卡阶段应填；**[L2]** = 晋级前必填；**[OPT]** = 选填；**[SYS]** = 系统字段。
- 同一 `key` 的任何修改都要递增 `version_no`；发布后的版本不可改（幂等键 `key + version_no`）。

### 0.3 全卡通用写法规则（硬性）
1. **措辞**：只写"候选信号 / 计划条件 / 规则条件满足（候选）"。禁用"推荐、建议买入、立即买入/卖出、必涨、稳赚、保证、目标价、金股、牛股"等词（plan §7.2）。不承诺收益，不推荐具体股票。
2. **认识论标注**（`epistemic`，[B]）：至少标出 `hypothesis` 和每个阈值参数的类型：`fact`（数据事实）/ `estimate`（估算：费率、冲击成本、置信度）/ `hypothesis`（策略逻辑与经验阈值）。
3. **时间**：A 股时刻一律写**北京时间（UTC+8）**；天数一律是交易日。
4. **禁止未来函数**：规则在时点 t 只能用 `available_at ≤ t` 的数据（§7.2）。
5. **可追溯**：每条规则都能产出 `rule_refs`（规则 ID、版本、取值、阈值、是否通过）和 `evidence`（特征键、取值、`data_as_of`、`fetched_at`、来源）。每张卡至少 1 条 `counter`、1 条 `invalidation`、1 种止损（G1）。
6. **数值**：模板与示例中的数字都是"示例"，不是回测或实测结论。
7. **黑盒模型**（机器学习、合成打分）只能出现在 `model_refs`，角色固定为 `auxiliary`，不计入规则满足率，不能单独触发计划草案（P1b）。LLM 只把结构化证据改写成文字（P1a）。
8. **DSL**：只用 §2.5.14 C 节白名单：比较、`and/or/not`、`+ - * /`、`ma/ema/atr/highest/lowest/ref/cross_up/cross_down/between/rank_pct/pct_change`、`for N days`、`within N days`；`min(x,n)`/`max(x,n)` 是 `lowest`/`highest` 的别名（所以**不要**用 `max(a,b)` 表示"取两者较大"）。特征写 `f.` 前缀、参数写 `p.` 前缀（推荐）。`ctx.*`（`ctx.last_price`、`ctx.holding_days`、`ctx.sellable_qty`、`ctx.max_r_reached`）和 `plan.*`（`plan.stop_loss`、`plan.take_profit`、`plan.entry_price`）**只能在 hold/weakening/exit 规则中用**。表达式 ≤ 300 字符，嵌套 ≤ 6 层。

---

## 1. 身份 [B]
| 字段 | 填写规范 | 示例 |
|---|---|---|
| `key` [B] | `^[a-z][a-z0-9_]{2,40}$`，全站唯一；周期前缀 `t_` 日内做T、`st_` 短线、`sw_` 波段、`lt_` 中长线；通用组件用 `gate_`/`ctx_`/`hold_`/`veto_` | `sw_ma_trend_pullback` |
| `version_no` [B] | 整数 ≥ 1，只增。规则、参数默认值、数据口径任何变化都 +1 | 1 |
| `name` [B] | ≤ 30 字，"周期·方法" | 波段·均线趋势回踩 |
| `category` [B] | `trend / momentum / reversal / breakout / value / quality / dividend / low_vol / event / intraday_t`；要新增取值先提给架构师 | trend |
| `horizons[]` [B] | `intraday_t / short / swing / long` | [swing] |
| `card_id` [OPT] | `catalog.md` 中的编号 | W-01 |
| `owner` [OPT] | "系统内置" / 用户 ID / `llm_draft`（附 `llm_call_id`） | 系统内置 |
| 生命周期、`completeness` [SYS] | `draft/simulating/published/observing/retired` 与完整度由系统计算 | 不填 |

## 2. 来源 [L1]
| 字段 | 填写规范 | 示例 |
|---|---|---|
| `sources[]` [OPT/L1] | `{title, kind, url_or_ref, source_version, license, license_status}`；`kind` ∈ open_source / paper / book / article / internal；`license_status` ∈ `idea_only` / `code_reusable`；CC BY-NC、AGPL、无 LICENSE 的项目只能 `idea_only`（plan §7.6）；查不到版本写"待核实" | KHunter，MIT，idea_only |
| `principle_text` [L1] | 原理解释：给新手看的 3–5 句话，说清"它在赌什么、什么时候会错" | 见附录 A |
| `pitfalls[]` [OPT] | 常见误用与陷阱 | "把下跌趋势中的反弹当回踩" |

## 3. 假设与维度 [B]
| 字段 | 填写规范 | 示例 |
|---|---|---|
| `hypothesis.why_it_works` [B] | 一句可被检验的机制陈述 | 中期趋势有惯性，回踩不破给出止损距离较近的跟随点 |
| `hypothesis.falsified_by[]` [B] | **什么证据否定这个假设**，必须可观测、可量化（研究侧用 validation.md 的方法检验），至少 1 条，建议 ≥ 2 | 样本外 20 日扣费超额中位数 ≤ 0 |
| `dimensions[]` [B] | `{dimension, role}`：`dimension` ∈ technical / capital / fundamental / sentiment / sector_market / news；`role` ∈ core / auxiliary / veto。不用的维度不写 | technical: core |
| `epistemic` [B] | `{field_path: fact\|estimate\|hypothesis}` | `hypothesis: hypothesis`、`params_schema.pullback_pct: hypothesis` |

## 4. 标的范围 [OPT/L1；L2 量化]
| 字段 | 填写规范 | 示例 |
|---|---|---|
| `universe.pool` | 持仓 / 自选 / 全市场 / 指数成分（指数成分必须用"当时成分"，防幸存者偏差） | 持仓 ∪ 自选 |
| `universe.boards` | 主板 / 创业板 / 科创板 / 北交所逐项写是否包含及原因 | 北交所暂不含（plan 第 9 节问题 10） |
| `universe.exclude[]` | 可交易性闸门之外的额外排除 | 上市 < 120 个交易日 |
| `universe.liquidity` | DSL 表达式，如 `ma(f.amount, 20) >= p.min_amount`（停牌日不计入） | 5,000 万元（示例） |

## 5. 数据 [B]
`data_needs[]` 每项：

| 键 | 必填 | 规范 |
|---|---|---|
| `feature_key` | [B] | `feature_catalog` 中的键；未登记的写进 `validation.feature_requests[]` |
| `frequency` | [B] | `1m / daily / quarterly / event` |
| `adjust` | [B] | `none / qfq / hfq`。价格类指标用 `qfq`；收益计算用 `hfq`；**分钟线只有不复权**（T003 实测：分钟级传前复权返回 503），所以 1m 特征写 `none`，并在除权日截断窗口 |
| `available_at` | [B] | 可得时点（北京时间），如"T 日约 17:20 后（文档：日线 15:30 开始、约 17:1x 完成）"、"`plrq`（披露日）次一交易日 09:30" |
| `source_hint` | [OPT] | 来源说明：麦蕊接口写"文档已列·待T003验证"或"T003 已实测"；本地派生写公式 |
| `warmup_bars` | [OPT] | 预热所需有效 K 线数 |
| `missing_policy` | [OPT] | `insufficient_data`（不出信号）/ `dimension_unknown`（该维度 unknown，不阻断）/ `veto_unknown`（否决规则无法判定 → 买入方向按"不通过"并记 `KEY_DATA_MISSING`） |
| 核实状态 | [SYS] | `verified_doc / verified_live / gap`，系统按 `feature_catalog` 标注；只有 `verified_doc` 的字段最多晋级到 `simulating`（G2） |

**T003 已知的数据事实（写卡时直接适用）**
- 没有新闻、快讯、研报、舆情接口；公告只有标题 + 链接 + 级别 + 类型（`lx` 只区分"其他/财报类"），**交易日盘后更新**。依赖新闻的规则一律 `to_quantify` 并写不可执行原因及解除条件；依赖公告的规则只能盘后求值，最早次一交易日执行。
- 集合竞价数据**只有盘后**（开盘/收盘竞价量、竞昨比），没有 09:15–09:25 的实时撮合数据。依赖竞价的规则不能盘中运行，只能盘后求值、次日使用；开盘缺口只能用 09:30 后的快照开盘价。
- 因子按文档共 85 个（不是 77），**全部日频**，日终批算；"日内类"因子（如日内波动、VWAP 偏离的 20 日统计）也是日频历史统计，**不能用于盘中**。北向相关因子按文档返回空；`attention_score` 可能为空。
- 财报文档带披露日期 `plrq`，原则上可按时点取数；是否历史全量填充、是否保留修订前版本未实测。
- 涨跌停/强势股池文档称约 30 天历史；龙虎榜每日约 20:00 发布；行业/概念成分周更且未见历史成分。
- 日线实测发现疑似"伪停牌"占位行（`sf=1, v=0`、OHLC 相等，但当日实际有成交），需复核——见 §7.3。

## 6. 选股 [L2，筛选型才填；择时型写 `screen: null`]
`screen: {universe, filters[], rank_by, top_n}`（§2.5.14 C）。另建议填写：平局规则（按证券代码升序，保证确定性）、单行业入选上限、再平衡日、是否行业/市值中性化（validation.md §2.4）。

## 7. 规则 [B 卡片列表 + L2 规则规格]

### 7.1 两层写法
1. **卡片列表**（[B]，给人看，L1 必填）：`entry[]`、`counter_evidence[]`、`invalidation[]`、`exit[]`，每项 `{text, expr, status}`；每类至少 1 条，`exit` 至少 1 条止损类。`expr` 可以为 `null`（仅文字、`to_quantify`）。
2. **规则规格**（[L2]，给引擎）：`rules[]`，每项 `{id, dimension, role, expr, weight, required_features, eval_time, status, text, edge_cases}`。`role` ∈ entry / hold / weakening / exit / filter / veto / counter / invalidation；`eval_time` ∈ `daily_close / intraday_1m / event`（**必填**，§2.5.14 G）。`id` 前缀：E 入场、A 辅助入场、H 持有、W 转弱、X 退出、V 否决、C 反证、I 失效、F 筛选。
3. 两层的 `expr` **必须一致**；卡片列表项用 `ref: <id>` 指向规则（`ref` 是本模板建议的扩展键，待架构师确认导入器接受，见附录 B）。
4. 其他规格键：`kind: rule_template`、`action_map`、`stops`、`dimension_view_thresholds`、`applicability.market_regime`、`valid_until: {trading_days}`（§2.5.14 C）。

### 7.2 时点规则（禁止未来函数，所有卡共用，不可放宽）
| 情形 | 规则 |
|---|---|
| 日线信号 | T 日收盘后、日线数据到齐后求值（文档：约 17:1x 完成，待交易日实测）；**最早执行 T+1 09:30**；模拟入场价 = T+1 开盘价（plan §2.8.1）。不得把 T 日收盘价当作可成交价 |
| 盘中信号 | 只用已收完的 1 分钟 bar；模拟入场价 = 下一根 1 分钟 bar 的开盘价。盘中可用的只有实时快照和 1 分钟 K（1 分钟 Pro 待T003验证）；**因子全部日频，盘中只能用 T−1 日的因子值** |
| 集合竞价 | 没有实时竞价数据：竞价类特征只能在盘后取得，最早用于次一交易日；当日开盘缺口只能用 09:30 后快照的开盘价 |
| 财务数据 | 以披露日 `plrq` 为准，不以报告期为准；披露时刻未知 → 一律按盘后处理，次一交易日 09:30 起可用 |
| 公告 | 麦蕊公告盘后更新 → 一律按盘后处理：次一交易日 09:30 起可用（即使公告本身在盘中发布） |
| 龙虎榜 | 约 20:00 发布 → 次一交易日 09:30 起可用 |
| 因子截面 | 只用本项目按时点落库的截面（带 `first_seen_at`）；麦蕊回溯的历史因子是否按当时可知信息计算未核实，核实前不能用于研究侧验证 |
| 指数/行业成分 | 用当时成分；麦蕊成分周更、未见历史成分 → 从本项目落库起按周快照积累 |
| 交易约束 | 涨跌停价用当日有效的规则版本（`market_rule_versions`，如沪深主板 ST 自 2026-07-06 起 10%，plan §2.13） |

### 7.3 边界情况（默认处理，卡内可加严、不可放宽）
| 情况 | 默认处理 |
|---|---|
| 停牌 | 停牌日没有有效 K 线，不补值；`ma(x,n)` 等按"最近 n 根有效 K 线"计算；复牌首日若停牌 ≥ 5 个交易日，入场规则 `insufficient_data` 1 个交易日，退出/失效规则照常求值 |
| 伪停牌占位行 | 日线 `sf=1` 且当日实时快照或分钟线显示有成交 → 视为**数据缺失**（不是停牌），该日记 `DATA_STALE`/`KEY_DATA_MISSING`，不进入指标计算，并上报数据质量告警（T003 §2 疑点，待复核） |
| 缺失值 | 不插值、不前值填充；按 `missing_policy` 处理 |
| 新股/次新股 | 有效 K 线 < `warmup_bars` → `insufficient_data`；上市 < 30 个交易日由闸门阻断买入；注册制新股前 5 日无涨跌幅限制，这几天的 K 线不进入波动类指标窗口 |
| 复权 | 指标用前复权，**每次除权后整段重算**（前复权历史会变），落库记录复权因子版本；收益用后复权；止损价等绝对价格在除权日按复权因子调整并记录事件；1 分钟线不复权，窗口跨除权日时截断 |
| 涨跌停 | 一字涨停买入不可成交、一字跌停卖出不可成交（`LIMIT_LOCKED`）；止损止盈价截断到当日涨跌停价之内（G5） |
| ST/退市整理 | 闸门阻断买入方向；持仓股变 ST 仍评估卖出方向 |
| 数据陈旧 | 数据 `stale` 时不生成新信号、不翻转（`DATA_STALE`） |

## 8. 入场 [L1 文字；L2 量化]
| 字段 | 规范 | 示例 |
|---|---|---|
| `action_map` | §2.5.14 C：`{entry_all_core_pass: buy, held_hold: hold, exit: sell, else: wait}` | 同左 |
| `entry_policy.core` / `auxiliary` | 哪些 entry 规则是核心（全部通过才成立）、哪些是辅助（不通过只降分；数据缺失时维度 unknown） | core [E1,E2,E3]；auxiliary [A1] |
| `entry_policy.confirm` | 确认时点与防抖：日线收盘确认；盘中连续 2 根 bar 成立才确认 | 日线收盘确认 |
| `valid_until` | `{trading_days: n}`；plan 默认：做T 当日 14:50、短线 1、波段 5、中长线 20 | `{trading_days: 5}` |
| `entry_policy.price_band` | 参考价 ±（滑点 + 冲击成本），截断到涨跌停价内 | 见 §18 |
| `entry_policy.cooldown_days` | 同模板同证券冷却（plan 默认 3） | 3 |

## 9. 退出 [B 至少一条止损；L2 全部量化]
| 字段 | 规范 |
|---|---|
| `stops.stop_loss` | 止损价公式（可引用 `plan.entry_price`、`atr(n)`）；写明 T+1：买入当天不能卖，最早 T+2 |
| `stops.take_profit` | 止盈价公式或 `null` |
| `stops.time_stop_days` | 时间止损（交易日）；做T 模板必须有当日回补规则或 14:50 时间止损（G1） |
| `exit[]` / `rules` 中 role=exit | 趋势失效类退出（如跌破均线）、结构止损（如跌破前 20 日最低） |
| `exit_policy.trailing` | 跟踪止盈；目前 DSL 没有"入场以来最高价"，写 `status: to_quantify` 并提 `ctx` 扩展需求 |
| `exit_policy.rebalance` | 筛选型策略：再平衡后掉出名单的处理 |

## 10. 仓位 [L1 建议；L2 量化]
| 字段 | 规范 | 示例 |
|---|---|---|
| `risk_suggestions` [OPT] | 引用 RC1–RC6 并写本卡建议值：单标的上限（RC2）、总仓位按大盘（RC3）、行业集中度（RC4）。取与用户风控设置中更严者 | RC2: 10%（示例） |
| `position.strategy_budget` | 本策略实例占总资产上限 | 30%（示例） |
| `position.risk_per_trade` | 单笔最大亏损占总资产比例；数量 =（该金额）/（参考价 − 止损价），向下取整到交易单位 | 1%（示例） |
| `position.regime_scale` | 按大盘环境缩放 | uptrend 1.0 / range 0.5 / downtrend 0 |

## 11. 验证 [L1 摘要 + L2 机器块]
> 用户原话（vision.md 11:37）："不要回测，只要模拟跟踪建议的后续表现。" 所以本字段分两块：①`validation_summary`（L1 展示用，研究侧离线验证摘要，没做就写"未验证"）；②`validation`（§2.5.14 E 节的机器块，G6 的输入）。详细方法见 validation.md（不被导入）。

| 字段 | 规范 |
|---|---|
| `validation_summary.type` | factor / event / rule |
| `validation_summary.window` / `benchmark` / `cost_model` | 研究区间与切分、基准、成本口径（引用 §18） |
| `validation_summary.oos_result` | `{metric, value, n, window}`；**没执行就写"未验证"，不得填未执行的数字** |
| `validation_summary.trade_log_ref` | 研究侧交易明细位置（仅内部） |
| `validation.methods[]` | 必选 `fixture`、`trigger_stats`；可选 `tracking_sim`；问题 26 获批后可加 `factor_ic`、`event_study`、`param_robustness` |
| `validation.fixtures[]` | ≥ 6 个，覆盖：满足、不满足、缺数据、维度分歧、涨跌停或停牌、做T 无底仓（非做T 卡用"持仓可卖为 0 时触发卖出"代替，见附录 B）。数值全部虚构 |
| `validation.window` / `horizon_days` / `metrics` / `min_n` / `pass_criteria` | 默认 120 日全 A / `[1,5,20]` / 每个指标按 `{value, n, window, small_sample}` 输出 / 20 |
| `validation.feature_requests[]` | `{name, desc, source_hint, frequency}`：引擎还没有的特征 |

> **键名说明**：§2.5.14 G 规定单块写法中顶层 `validation` 视为验证机器块，同时又把卡内 `validation.type/...` 当作展示摘要。为避免歧义，本模板把摘要改名为 `validation_summary`，`validation` 只放 E 节机器块（附录 B 第 9 项，请架构师确认）。

## 12. 运行 [SYS，不填]
系统在卡片详情页展示：最近扫描时间与 `snapshot_id`、数据状态（fresh/stale/partial 与缺失特征）、最近信号与阻断原因。

## 13. 复盘 [SYS + 用户备注，不填]
系统回填"表现记录"：模拟跟踪 T+1/5/20 `{value, n, window, small_sample}`（n < 5 不显示数值）、执行偏差（实际成交 vs 草案参考价）、失效记录、结果归因（市场 / 判断 / 执行，validation.md §7.5）。

## 14. 不可执行原因及解除条件 [L2]
- **信号级**（L3）：候选信号成立但不生成计划草案时，写原因码 + `release_condition`（kind = expr / time / event / user_action，是否机器可判断），共 23 个原因码（plan §2.5.9）。卡片里填 `non_executable.applicable[]`（适用的原因码）和 `non_executable.card_specific[]`（本卡特有的触发情形，必须带解除条件，原因码仍从 23 个里选）。
- **卡片级**："卡片为什么还不能运行"由系统字段 **`gates_missing[]` [SYS]** 表示：系统根据 G1–G7 的检查结果计算（如 G2 某特征是缺口、G1 缺失效条件），在 API（plan §7.4）和详情页返回，**研究员不填**；它不属于 23 个原因码。研究员可以在正文里写"预计的缺口及解除条件"，供审核参考。

| vision 定稿原因 | 原因码（plan §2.5.9） | 默认解除条件 |
|---|---|---|
| 数据过期 | `DATA_STALE` | 数据状态为 fresh |
| 行业暴露超限 | `SECTOR_EXPOSURE_EXCEEDED` | 行业占比 < 上限 |
| 已有同向计划 | `SAME_DIRECTION_PLAN_EXISTS` | 该计划进入终止状态 |
| 交易状态不满足 | `SUSPENDED` / `LIMIT_LOCKED` / `NON_TRADING_TIME` | 复牌 / 打开涨跌停 / 下一交易日 09:30 |
| 涨跌停、停牌、ST | `LIMIT_LOCKED` / `SUSPENDED` / `ST_OR_DELISTING` | 同上；摘帽；退市整理不可解除 |
| 资金不足或 T+1 可卖不足 | `INSUFFICIENT_CASH` / `T1_NOT_SELLABLE` | 可用资金 ≥ 所需；下一交易日 09:30 或可卖 ≥ 1 手 |
| 单标的上限或策略预算用尽 | `POSITION_CAP_REACHED` / `STRATEGY_BUDGET_EXHAUSTED` | 占比 < 上限；已用 < 预算 |
| 大盘环境不符 | `REGIME_MISMATCH` | 大盘环境变为适用值（2 日防抖） |
| 与已确认计划或禁投名单冲突 | `CONFLICTS_CONFIRMED_PLAN` / `BLOCKLISTED` | 用户修改计划 / 移出名单 |
| 冷静期 | `COOLING_OFF` | 冷静期结束 |
| 连续亏损/回撤暂停 | `LOSS_STREAK_PAUSE` | 用户确认恢复或暂停期满 |
| 置信度低或关键数据缺失 | `LOW_CONFIDENCE` / `KEY_DATA_MISSING` | 置信度 ≥ 阈值；字段在新快照中非空 |
| 非交易时段 | `NON_TRADING_TIME` | 下一交易日 09:30 |
| 用户手动屏蔽 | `USER_MUTED` | 取消屏蔽或到期 |
| plan 另增 | `NO_POSITION`、`NEW_LISTING`、`STRATEGY_CONFLICT`、`PROFILE_OR_CONSENT_MISSING` | 见 plan §2.5.9 |

## 15. 适用市场环境与风格 [OPT/L1]
| 字段 | 规范 | 示例 |
|---|---|---|
| `applicability.market_regime[]` | 取 `ctx_market_regime` 产出：`uptrend / range / downtrend`（2 日防抖；枚举与 §2.5.14 C 示例一致，`downtrend` 待架构师确认） | [uptrend, range] |
| `applicability.style` | 适合与不适合的风格（大小盘、成长价值、高低波、流动性） | 不适合日均成交额 < 5,000 万元的股票 |
| `applicability.when_not` | 不适用时：`pause`（不产生入场候选，退出照常）/ `warn_only`（照常产生但标"环境不符"） | downtrend → pause |

## 16. 周期与扫描节奏 [L1]
| 字段 | 规范 | 示例 |
|---|---|---|
| `horizons[]` | 见 §1 | [swing] |
| `holding_period` | 预期持有区间（交易日） | 5–60 |
| `scan.schedule` | `daily_close`（盘后批）/ `intraday_1m` / `weekly` / `monthly` / `event` | daily_close |
| `scan.intraday_role` | 盘中只监控哪些规则（一般只监控止损/失效，避免盘中噪声改变日线判断） | 只监控 X2 |

## 17. A股交易约束 [L2；系统自动挂载，卡内说明影响]
| 约束 | 说明本策略如何受影响 |
|---|---|
| T+1 | 买入当日不可卖：入场当天的止损无法执行，最早 T+2 |
| 做T 需底仓 | 先买后卖（`buy_first`）需有昨日及以前的可卖底仓；先卖后买（`sell_first`）需有可卖底仓并当日买回；无底仓 → `NO_POSITION`，可卖不足 → `T1_NOT_SELLABLE` |
| 涨跌停 | 主板 10%、创业板/科创板 20%、北交所 30%、沪深主板 ST 10%（2026-07-06 起）；注册制新股前 5 日不设限（plan §2.13，以交易所规则为准）；一字板不可成交 |
| 20% 涨跌幅板块 | 创业板/科创板的阈值（ATR 倍数、做T 偏离阈值）是否单独设参 |
| 北交所 | 是否覆盖；交易单位与涨跌幅不同 |
| 停牌 | 信号冻结；复牌首日见 §7.3 |
| ST/退市整理 | 闸门阻断买入 |
| 集合竞价 | 开盘竞价 09:15–09:25（09:20 后不可撤单）、收盘竞价 14:57–15:00（以交易所规则为准）；竞价期间不触发盘中信号；**没有实时竞价数据**，竞价类规则只能盘后 |
| 交易单位 | 买入 100 股整数倍（科创板 ≥ 200 股后可 1 股递增，plan §2.13） |

## 18. 成本与滑点 [L2，进入产品]
**默认费用**（plan §2.13；能用用户导入成交反推真实费率时以真实值为准，`epistemic: estimate`）

| 项 | 默认 |
|---|---|
| 佣金 | 双向，按用户费率，单笔最低 5 元 |
| 印花税 | 仅卖出 0.05% |
| 过户费 | 双向 0.001% |
| 基础滑点 | 模板参数 `slippage_bp`，默认 10 bp（0.1%） |
| **冲击成本** | 见下，分档确定性估算 |

**冲击成本（确定性分档估算）**
- 参与率：`r = 拟成交额 / ADV_N`，其中 `ADV_N = ma(f.amount, N)`（最近 N 根**有效**日 K 的成交额均值，停牌日不计，`N = p.impact_adv_days`，默认 20）。拟成交额 = 计划数量 × 参考价。
- 分档（**示例，待校准**；由 `engine_policy` 版本管理，不按个股调整）：

| 档 | 参与率 r | 单边冲击成本 |
|---|---|---|
| I1 | r ≤ 0.1% | 0 bp |
| I2 | 0.1% < r ≤ 0.5% | 5 bp |
| I3 | 0.5% < r ≤ 1% | 15 bp |
| I4 | 1% < r ≤ 2% | 30 bp |
| I5 | r > 2% | 60 bp，并标记"容量受限"（提示用户分批；不新增原因码） |

- 单边总价格成本 = 基础滑点 + 冲击成本；往返 = 两边相加 + 佣金 + 印花税 + 过户费。计划草案的费用估算、价格区间、模拟跟踪的"扣费口径"都用这一公式。
- **边界**：
  - 停牌：不计算（信号已被 `SUSPENDED` 阻断）；复牌后有效 K 线 < 5 根 → 按 I5 计并标"冲击成本无法可靠估算"。
  - `ADV_N = 0` 或有效 K 线 < 5 根（新股、长期停牌后）→ 不做除法，直接按 I5 计并标"无法可靠估算"。
  - 涨跌停无法成交（一字板或盘中封板）：不计算冲击成本，按不可成交处理（`LIMIT_LOCKED`；模拟跟踪记为"不可成交"，不计胜率）。
  - 做T：拟成交额按单腿计；两腿各算一次。
- `epistemic: estimate`；档位、阈值和 bp 值在研究侧用真实成交（导入数据）校准后再改版本。

**往返成本门槛**：研究侧摘要中预期单笔收益 ≤ 2 × 往返成本的规则型策略不建议晋级（小额做T 尤其要算最低 5 元佣金）。

## 19. 信号强度与置信度 [L2]
| 项 | 规则（确定性，随 `engine_policy` 版本记录） |
|---|---|
| `score`（0–100） | 本策略规则满足度 = Σ(通过的 entry 规则 weight) / Σ(entry 规则 weight) × 100；**不是股票好坏评分，不跨策略合成** |
| `confidence`（0–1；high ≥ 0.7，medium ≥ 0.4，其余 low） | `0.5×数据完整度 + 0.3×维度一致度 + 0.2×条件余量`（plan §2.5.4）。本模板的确定性定义：数据完整度 = 必需特征中非缺失且 fresh 的比例；维度一致度 = 非 unknown 维度中观点与本策略候选方向一致的比例（维度观点按 `dimension_view_thresholds` 划分）；条件余量 = 已通过的数值规则 `clip(|取值 − 阈值| / scale, 0, 1)` 的平均，`scale` 在 `margin_scale` 中逐条定义 |
| `epistemic` | 规则通过与否为 `fact`；score、confidence 为 `estimate`；策略逻辑为 `hypothesis` |
| 低置信 | 低于用户阈值（默认 0.4）→ `LOW_CONFIDENCE` |

## 20. 冲突与互斥 [L2]
| 字段 | 规范 |
|---|---|
| `conflict.exclusive_group` | 互斥组名：同组模板对同一证券、同一周期给出相反方向 → `STRATEGY_CONFLICT`，不自动拟草案，由用户选择 |
| `conflict.known_conflicts[]` | 与哪些卡天然可能相反，以及"什么新信息有助判断" |
| `conflict.display_priority` | **只影响展示顺序**（默认 fit × 健康度权重），不合并结论、不取保守动作、不设主策略（P4） |
| veto 作用范围 | 只作用于本模板 |

## 21. 个人适配 [OPT/L1]
`fit: {effort: low|medium|high, risk_tolerance_min: 1–5, experience_min: novice|intermediate|experienced}`（§2.5.14 B）；另可写 `capital_min_cny`（至少能买 1 手且满足单标的上限）、`drawdown_expect`、`mismatch_handling`（不匹配时提示并降置信度，实例化需逐项确认）。

## 22. 参数与敏感性 [L2]
`params_schema`（D 节）：映射形式 `{name: {type, default, min, max, step, desc, unit?, choices?}}` 或列表形式（`说明` 是 `desc` 的别名）。类型严格；`default ∈ [min, max]`。另填 `user_editable`（false 的参数不允许在 L3 改）和 `sensitivity`（研究侧结论摘要，未做写"未评估"，方法见 validation.md §5.1）。

## 23. 审计与版本 [部分 SYS]
- 研究员填写：`changelog[]: {version_no, date, author, change, reason}`。
- 系统记录：`version_id`、`parent_version_id`、`param_hash`、`feature_set_version`、`market_rule_version`、`engine_policy_version`、G1–G7 报告与审核人；旧版本信号按当时版本原样回看。

## 24. 合规文案 [L2，G7 校验]
`compliance_variants`（§2.5.14 B 选填）：
- 标题："按《{name} v{version_no}》规则：{动作}条件满足（候选，{k}/{n} 条）"。
- 同屏必须同时展示反证与失效条件。
- 声明："本工具基于您选择的规则对公开数据进行计算，输出为规则信号，不构成投资建议或收益承诺；交易决策与风险由您自行承担。"（plan §7.2）
- 通过禁用词校验。

---

## 附录 A：完整示例卡（示例，不是正式卡；所有数字均为示例，不是回测或实测结论）

> 注意：下面用普通 `yaml` 代码块，**故意不带** `strategy-card` 标记。研究员把它变成正式卡时，把文件另存为独立文件，并把信息串改成 `yaml strategy-card`。

正文说明（正式卡里作为 `narrative`）：当股票处在中期上升趋势（20 日均线持续高于 60 日均线）时，价格回落到 20 日均线附近而没有有效跌破，常被看作趋势中的回撤。本方法假设趋势有惯性，在回踩不破时给出跟随的候选信号，代价是趋势结束时会被止损。它不预测顶和底，只在"趋势仍在"时给出候选信号，并事先写好什么情况下认错。

```yaml
# ===== 1 身份 [B] =====
key: sw_ma_trend_pullback
version_no: 1
name: 波段·均线趋势回踩
category: trend
horizons: [swing]
card_id: W-01
owner: 系统内置
# 生命周期、completeness、表现记录：[SYS]，不填

# ===== 2 来源 =====
sources:
  - {title: "KHunter multi_golden_cross / main_uptrend_dip_buy", kind: open_source,
     url_or_ref: "https://github.com/ling-0729/KHunter（strategy/ 目录）", source_version: 待核实,
     license: MIT, license_status: idea_only}
  - {title: "tick-stock-panel pullback_ma20_bounce", kind: open_source,
     url_or_ref: "https://github.com/shy3130/tick-stock-panel", source_version: 待核实,
     license: MIT, license_status: idea_only}
principle_text: "见正文说明"
pitfalls:
  - 把下跌趋势中的反弹当作回踩（由 E1、V1 防护）
  - 忽略 T+1：入场当天无法止损
  - 用在成交稀少的股票上，成交价远离参考价（由流动性下限与冲击成本防护）

# ===== 3 假设与维度 [B] =====
hypothesis:
  why_it_works: "中期趋势存在惯性；趋势中的回踩不破提供了止损距离较近的跟随点"
  falsified_by:
    - "研究侧：样本外信号后 20 个交易日扣费超额收益（对所属行业指数）中位数 ≤ 0（validation.md §4）"
    - "研究侧：参数邻域（ma_fast ±5、pullback_pct ±0.01）内超额收益符号翻转（不稳健）"
    - "模拟跟踪：n ≥ 30 时 5 日平滑胜率 < 45% 且平均超额 < 0（validation.md §6）"
dimensions:
  - {dimension: technical, role: core}
  - {dimension: capital, role: auxiliary}
  - {dimension: fundamental, role: veto}
  - {dimension: sentiment, role: veto}
  - {dimension: sector_market, role: veto}
  - {dimension: news, role: veto}
epistemic:
  hypothesis: hypothesis
  params_schema.trend_days: hypothesis
  params_schema.pullback_pct: hypothesis
  params_schema.max_dd_from_high: hypothesis
  params_schema.atr_mult: hypothesis
  params_schema.rsi_overheat: hypothesis
  params_schema.np_yoy_floor: hypothesis
  params_schema.min_amount: hypothesis
  params_schema.slippage_bp: estimate
  costs.impact_tiers: estimate

# ===== 4 标的范围 =====
universe:
  pool: 持仓 ∪ 自选
  boards: {main: true, chinext: true, star: true, bse: false}   # 北交所：待问题 10 拍板
  exclude: ["上市 < 120 个交易日"]
  liquidity: "ma(f.amount, 20) >= p.min_amount"

# ===== 5 数据 [B]（f.* 为本项目特征键；未登记的见 validation.feature_requests）=====
data_needs:
  - {feature_key: f.close_qfq, frequency: daily, adjust: qfq,
     available_at: "T 日日线到齐后（文档：约 17:1x 完成，待交易日实测）",
     source_hint: "日线 history/latest，复权 f（T003 已实测：日线五种复权均有数据）", missing_policy: insufficient_data}
  - {feature_key: f.low_qfq, frequency: daily, adjust: qfq, available_at: 同上, source_hint: 同上}
  - {feature_key: f.amount, frequency: daily, adjust: none, available_at: 同上,
     source_hint: "日线字段 a（成交额，T003 已实测）"}
  - {feature_key: f.rsi14, frequency: daily, adjust: qfq, available_at: 同上,
     source_hint: "本地按 close_qfq 计算 Wilder RSI(14)；也可对照因子 rsi_14（文档已列·待T003验证）", warmup_bars: 28}
  - {feature_key: f.main_net_20d, frequency: daily, adjust: none, available_at: "T 日 15:40 后（文档·待T003验证）",
     source_hint: "资金流或因子 main_20d_net（文档已列·待T003验证；口径=特大+大单主买−主卖）", missing_policy: dimension_unknown}
  - {feature_key: f.np_yoy_latest, frequency: quarterly, adjust: none,
     available_at: "披露日 plrq 的次一交易日 09:30",
     source_hint: "利润表（含 plrq，文档已列·待T003验证）本地派生：只取 plrq ≤ 当日的最近一期", missing_policy: veto_unknown}
  - {feature_key: f.ann_risk_count_10d, frequency: event, adjust: none,
     available_at: "公告盘后更新 → 次一交易日 09:30",
     source_hint: "公告标题（文档已列·待T003验证）+ 本地关键词表（立案调查/退市风险警示/重大违法）", missing_policy: veto_unknown}
  - {feature_key: f.market_regime, frequency: daily, adjust: none, available_at: "T 日盘后",
     source_hint: "本地组件 ctx_market_regime（catalog G-02）"}
  - {feature_key: f.ind_rs20, frequency: daily, adjust: none, available_at: "T 日盘后",
     source_hint: "申万一级归属（周更，文档已列·待T003验证）+ 指数日线，本地派生", missing_policy: dimension_unknown}

# ===== 6 选股 =====
screen: null          # 择时型：对持仓与自选逐只求值

# ===== 7 规则：卡片列表 [B] =====
entry:
  - {ref: E1, text: "20 日均线连续 N 日高于 60 日均线（趋势成立）", status: quantified,
     expr: "ma(f.close_qfq, p.ma_fast) > ma(f.close_qfq, p.ma_slow) for 5 days"}
  - {ref: E2, text: "近 3 日最低价回到 20 日均线上方 2% 以内，收盘仍在均线上方（回踩不破）", status: quantified,
     expr: "lowest(f.low_qfq, 3) <= ma(f.close_qfq, p.ma_fast) * (1 + p.pullback_pct) and f.close_qfq > ma(f.close_qfq, p.ma_fast)"}
  - {ref: E3, text: "距 60 日最高收盘不超过 15%", status: quantified,
     expr: "f.close_qfq >= highest(f.close_qfq, 60) * (1 - p.max_dd_from_high)"}
counter_evidence:
  - {ref: C1, text: "所属行业近 20 日弱于大盘", status: quantified, expr: "f.ind_rs20 < 0"}
  - {ref: C2, text: "近 20 日主力资金净流出", status: quantified, expr: "f.main_net_20d < 0"}
  - {ref: C3, text: "当日成交额不足 20 日均额一半（流动性差，成交价可能偏离）", status: quantified,
     expr: "f.amount < ma(f.amount, 20) * 0.5"}
invalidation:
  - {ref: I1, text: "20 日均线跌破 60 日均线：本卡的前提消失", status: quantified,
     expr: "ma(f.close_qfq, p.ma_fast) < ma(f.close_qfq, p.ma_slow)"}
  - {ref: I2, text: "大盘环境转为下行（已防抖）", status: quantified, expr: "f.market_regime == 'downtrend'"}
exit:
  - {ref: X2, text: "盘中触及止损价（买入当日不可卖）", status: quantified,
     expr: "ctx.last_price <= plan.stop_loss and ctx.sellable_qty > 0"}
  - {ref: X1, text: "收盘跌破 20 日均线连续 2 日：趋势失效", status: quantified,
     expr: "f.close_qfq < ma(f.close_qfq, p.ma_fast) for 2 days"}
  - {ref: X4, text: "收盘跌破前 20 日最低价：结构止损", status: quantified,
     expr: "f.close_qfq < lowest(ref(f.low_qfq, 1), 20)"}
  - {ref: X3, text: "持有满 40 日仍未达到 1R：时间止损", status: quantified,
     expr: "ctx.holding_days >= p.time_stop and ctx.max_r_reached < 1"}

# ===== 7 规则：规格 [L2] =====
kind: rule_template
rules:
  - {id: E1, dimension: technical, role: entry, weight: 2, eval_time: daily_close, status: quantified,
     expr: "ma(f.close_qfq, p.ma_fast) > ma(f.close_qfq, p.ma_slow) for 5 days", required_features: [f.close_qfq],
     edge_cases: "有效 K 线 < ma_slow + 5 → insufficient_data"}
  - {id: E2, dimension: technical, role: entry, weight: 2, eval_time: daily_close, status: quantified,
     expr: "lowest(f.low_qfq, 3) <= ma(f.close_qfq, p.ma_fast) * (1 + p.pullback_pct) and f.close_qfq > ma(f.close_qfq, p.ma_fast)",
     required_features: [f.low_qfq, f.close_qfq]}
  - {id: E3, dimension: technical, role: entry, weight: 1, eval_time: daily_close, status: quantified,
     expr: "f.close_qfq >= highest(f.close_qfq, 60) * (1 - p.max_dd_from_high)", required_features: [f.close_qfq]}
  - {id: A1, dimension: capital, role: entry, weight: 1, core: false, eval_time: daily_close, status: quantified,
     expr: "f.main_net_20d > 0", required_features: [f.main_net_20d], edge_cases: "缺失 → 资金维度 unknown，不阻断"}
  - {id: V1, dimension: sector_market, role: veto, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.market_regime == 'downtrend'", required_features: [f.market_regime]}
  - {id: V2, dimension: fundamental, role: veto, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.np_yoy_latest < p.np_yoy_floor", required_features: [f.np_yoy_latest],
     edge_cases: "缺失 → 买入方向按否决处理，记 KEY_DATA_MISSING"}
  - {id: V3, dimension: news, role: veto, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.ann_risk_count_10d > 0", required_features: [f.ann_risk_count_10d],
     edge_cases: "公告盘后更新：当日盘中发布的公告次一交易日才计入"}
  - {id: V4, dimension: sentiment, role: veto, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.rsi14 > p.rsi_overheat", required_features: [f.rsi14]}
  - {id: C1, dimension: sector_market, role: counter, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.ind_rs20 < 0", required_features: [f.ind_rs20]}
  - {id: C2, dimension: capital, role: counter, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.main_net_20d < 0", required_features: [f.main_net_20d]}
  - {id: C3, dimension: technical, role: counter, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.amount < ma(f.amount, 20) * 0.5", required_features: [f.amount]}
  - {id: I1, dimension: technical, role: invalidation, weight: 0, eval_time: daily_close, status: quantified,
     expr: "ma(f.close_qfq, p.ma_fast) < ma(f.close_qfq, p.ma_slow)", required_features: [f.close_qfq]}
  - {id: I2, dimension: sector_market, role: invalidation, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.market_regime == 'downtrend'", required_features: [f.market_regime]}
  - {id: X1, dimension: technical, role: exit, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.close_qfq < ma(f.close_qfq, p.ma_fast) for 2 days", required_features: [f.close_qfq]}
  - {id: X2, dimension: technical, role: exit, weight: 0, eval_time: intraday_1m, status: quantified,
     expr: "ctx.last_price <= plan.stop_loss and ctx.sellable_qty > 0", required_features: []}
  - {id: X3, dimension: technical, role: exit, weight: 0, eval_time: daily_close, status: quantified,
     expr: "ctx.holding_days >= p.time_stop and ctx.max_r_reached < 1", required_features: []}
  - {id: X4, dimension: technical, role: exit, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.close_qfq < lowest(ref(f.low_qfq, 1), 20)", required_features: [f.close_qfq, f.low_qfq]}
action_map: {entry_all_core_pass: buy, held_hold: hold, exit: sell, else: wait}
dimension_view_thresholds: {bullish: 0.67, bearish: 0.33}

# ===== 8 入场 =====
entry_policy:
  core: [E1, E2, E3]
  auxiliary: [A1]
  confirm: "日线收盘确认；最早执行 T+1 09:30；模拟入场价 = T+1 开盘价"
  price_band: "参考价 ×（1 ± (slippage_bp + 冲击成本 bp) / 10000），截断到 T+1 涨跌停价之内"
  cooldown_days: 3
valid_until: {trading_days: 5}

# ===== 9 退出 =====
stops:
  stop_loss: "plan.entry_price - p.atr_mult * atr(14)"     # 截断到跌停价之上（G5）；T+1：最早 T+2 执行
  take_profit: null
  time_stop_days: 40
exit_policy:
  trailing: {status: to_quantify, text: "达到 2R 后，跟踪止盈 = 入场以来最高收盘 − 2×ATR14",
             need: "ctx.highest_close_since_entry（需架构师新增 ctx 字段）"}
  rebalance: 不适用

# ===== 10 仓位 =====
risk_suggestions: {RC2_single_cap: 0.10, RC3: 按用户设置, RC4_sector_cap: 0.40}   # 示例
position: {strategy_budget: 0.30, risk_per_trade: 0.01,
           regime_scale: {uptrend: 1.0, range: 0.5, downtrend: 0}}             # 示例

# ===== 11 验证 =====
validation_summary:
  type: rule
  window: 未执行
  benchmark: "所属申万一级行业指数；对照中证全指"
  cost_model: "§18 默认（含冲击成本分档）"
  oos_result: 未验证
  trade_log_ref: null
validation:
  methods: [fixture, trigger_stats, tracking_sim]
  window: {lookback_trading_days: 120, universe: 全A（不含北交所）}
  horizon_days: [1, 5, 20]
  metrics: [trigger_rate, coverage, win_rate, avg_excess]
  min_n: 20
  pass_criteria:
    - {metric: trigger_rate, op: "<=", value: 0.30}
    - {metric: trigger_rate, op: ">", value: 0}
  fixtures:   # 证券与数值全部虚构
    - {id: FX1, desc: 满足, as_of: "2026-03-02",
       features: {f.close_qfq: 10.70, "ma(f.close_qfq,20)": 10.42, "ma(f.close_qfq,60)": 9.87, "lowest(f.low_qfq,3)": 10.51,
                  "highest(f.close_qfq,60)": 11.80, f.amount: 1.2e8, "ma(f.amount,20)": 1.0e8, f.main_net_20d: 3.0e7,
                  f.np_yoy_latest: 12.0, f.ann_risk_count_10d: 0, f.rsi14: 56, f.market_regime: range, f.ind_rs20: 1.5},
       expect: {state: entry_ok, action: buy, rule_ids_passed: [E1, E2, E3, A1]}}
    - {id: FX2, desc: 不满足（收盘跌破 MA20）, as_of: "2026-03-02",
       features: {f.close_qfq: 10.20, "ma(f.close_qfq,20)": 10.42, "ma(f.close_qfq,60)": 9.87},
       expect: {state: insufficient_data, action: wait, rule_ids_passed: [E1]}}   # 见附录 B 第 10 项：此处期望 state 待架构师确认
    - {id: FX3, desc: 缺数据（净利润同比缺失，否决无法判定）, as_of: "2026-03-02",
       features: {f.np_yoy_latest: null},
       expect: {state: vetoed, action: wait, rule_ids_passed: [E1, E2, E3], reason_codes: [KEY_DATA_MISSING]}}
    - {id: FX4, desc: 维度分歧（技术满足、行业弱、资金流出）, as_of: "2026-03-02",
       features: {f.main_net_20d: -2.0e7, f.ind_rs20: -1.8},
       expect: {state: entry_ok, action: buy, rule_ids_passed: [E1, E2, E3]}}
    - {id: FX5, desc: 一字涨停（买入不可成交）, as_of: "2026-03-02",
       features: {f.limit_locked_up: true},
       expect: {state: entry_ok, action: buy, rule_ids_passed: [E1, E2, E3], reason_codes: [LIMIT_LOCKED]}}
    - {id: FX6, desc: 持有但当日买入可卖为 0 时触及止损（代替"做T无底仓"）, as_of: "2026-03-03",
       holding: {qty: 1000, sellable: 0},
       expect: {state: exit_signal, action: sell, rule_ids_passed: [], reason_codes: [T1_NOT_SELLABLE]}}
  feature_requests:
    - {name: f.ann_risk_count_10d, desc: "近 10 个交易日风险类公告条数（标题关键词表，版本化）", source_hint: "公告接口（文档已列·待T003验证）", frequency: event}
    - {name: f.np_yoy_latest, desc: "按 plrq 对齐的最近一期归母净利润同比", source_hint: "利润表 plrq（文档已列·待T003验证）", frequency: quarterly}
    - {name: f.ind_rs20, desc: "申万一级行业指数 20 日收益 − 中证全指 20 日收益", source_hint: "板块成分（周更）+ 指数日线", frequency: daily}
    - {name: f.market_regime, desc: "大盘环境 uptrend/range/downtrend（catalog G-02）", source_hint: 本地组件, frequency: daily}

# ===== 14 不可执行原因 =====
non_executable:
  applicable: [DATA_STALE, KEY_DATA_MISSING, LOW_CONFIDENCE, NON_TRADING_TIME, SUSPENDED, LIMIT_LOCKED,
               ST_OR_DELISTING, NEW_LISTING, INSUFFICIENT_CASH, T1_NOT_SELLABLE, POSITION_CAP_REACHED,
               STRATEGY_BUDGET_EXHAUSTED, SECTOR_EXPOSURE_EXCEEDED, REGIME_MISMATCH, SAME_DIRECTION_PLAN_EXISTS,
               CONFLICTS_CONFIRMED_PLAN, BLOCKLISTED, COOLING_OFF, LOSS_STREAK_PAUSE, STRATEGY_CONFLICT, USER_MUTED]
  card_specific:
    - {code: KEY_DATA_MISSING, when: "f.np_yoy_latest 或 f.ann_risk_count_10d 缺失",
       release_condition: {kind: expr, expr: "两个字段在新快照中都非空", machine_checkable: true}}
# gates_missing[]：[SYS]，系统根据 G1–G7 计算，不填。
# 预计缺口（仅供审核参考，正文说明）：f.main_net_20d / f.np_yoy_latest / f.ann_risk_count_10d 的来源只有文档依据，G2 最多到 simulating。

# ===== 15/16 环境与节奏 =====
applicability: {market_regime: [uptrend, range], style: "不适合日均成交额 < 5,000 万元的股票", when_not: {downtrend: pause}}
holding_period: "5–60 个交易日"
scan: {schedule: daily_close, intraday_role: "只对已持有并有计划的证券监控 X2"}

# ===== 17/18 约束与成本 =====
a_share_constraints: "全部按 §17 默认；创业板/科创板与主板使用相同 ATR 倍数（ATR 已反映波动，示例）"
costs:
  commission: "用户费率；未导入时用默认估算，单笔最低 5 元"
  stamp_duty_sell: 0.0005
  transfer_fee: 0.00001
  slippage_bp: 10
  impact_adv_days: 20
  impact_tiers: [{max_r: 0.001, bp: 0}, {max_r: 0.005, bp: 5}, {max_r: 0.01, bp: 15},
                 {max_r: 0.02, bp: 30}, {max_r: null, bp: 60, flag: 容量受限}]      # 示例，待校准

# ===== 19 强度与置信度 =====
margin_scale: {E2: "atr(14) / ma(f.close_qfq, 20)", E3: "p.max_dd_from_high"}

# ===== 20 冲突与互斥 =====
conflict:
  exclusive_group: swing_direction
  known_conflicts:
    - "st_oversold_rebound：本卡在趋势破坏时退出，超跌卡可能同时给出买入候选——两者并列，由用户选择；有助判断的信息：MA60 是否收复、行业相对强弱是否转正"
  display_priority: "fit × 健康度权重，只排序"

# ===== 21 个人适配 =====
fit: {effort: low, risk_tolerance_min: 3, experience_min: novice}
fit_extra: {capital_min_cny: 20000, drawdown_expect: "单笔约 2×ATR14"}          # 示例

# ===== 22 参数 =====
params_schema:
  ma_fast:          {type: int,   default: 20,    min: 10,    max: 30,    step: 5,     desc: 快均线周期, user_editable: true}
  ma_slow:          {type: int,   default: 60,    min: 40,    max: 120,   step: 10,    desc: 慢均线周期, user_editable: true}
  pullback_pct:     {type: float, default: 0.02,  min: 0.0,   max: 0.05,  step: 0.005, desc: 距快均线的回踩容差}
  max_dd_from_high: {type: float, default: 0.15,  min: 0.05,  max: 0.25,  step: 0.05,  desc: 距 60 日高点最大回撤}
  atr_mult:         {type: float, default: 2.0,   min: 1.0,   max: 3.5,   step: 0.5,   desc: 止损 ATR 倍数}
  time_stop:        {type: int,   default: 40,    min: 20,    max: 60,    step: 5,     desc: 时间止损, unit: 交易日}
  rsi_overheat:     {type: float, default: 80,    min: 70,    max: 90,    step: 5,     desc: 过热否决阈值}
  np_yoy_floor:     {type: float, default: -50,   min: -80,   max: -20,   step: 10,    desc: 净利润同比否决下限, unit: "%"}
  min_amount:       {type: float, default: 5.0e7, min: 1.0e7, max: 5.0e8, step: 1.0e7, desc: 日均成交额下限, unit: 元}
  slippage_bp:      {type: float, default: 10,    min: 0,     max: 100,   step: 5,     desc: 基础滑点, unit: bp, user_editable: false}
# sensitivity：全部"未评估"
# 说明：E1/X1 的 "for 5 days"/"for 2 days" 写成字面量，因为 DSL 是否允许 "for p.xxx days" 待架构师确认（附录 B 第 11 项）

# ===== 23 审计 =====
changelog: [{version_no: 1, date: 2026-11-01, author: 策略研究员, change: 初稿, reason: T006}]

# ===== 24 合规文案 =====
compliance_variants:
  signal_title: "按《波段·均线趋势回踩 v1》规则：买入条件满足（候选，{k}/{n} 条）"
  disclaimer: "本工具基于您选择的规则对公开数据进行计算，输出为规则信号，不构成投资建议或收益承诺；交易决策与风险由您自行承担。"
```

### A.1 一条候选信号的追溯链（证券与数值均为虚构示例）
| 项 | 内容 |
|---|---|
| 证券 | `600000.SH`（虚构示例，不代表该证券的任何真实情况） |
| 生成时点 | 示例交易日 T 18:05（北京时间），`snapshot_id = sn_示例`，`feature_set_version = fs_示例` |
| state / 候选动作 | `entry_ok` / 未持有 → `buy`，展示为"规则信号：买入条件满足（候选，3/3 条核心）" |
| rule_refs | E1：MA20 = 10.42 > MA60 = 9.87，连续 ≥ 5 日 ✔；E2：近 3 日最低 10.51 ≤ 10.42 × 1.02 = 10.63，且收盘 10.70 > 10.42 ✔；E3：10.70 ≥ 11.80 × 0.85 = 10.03 ✔；A1：主力 20 日净额缺失 → 资金维度 unknown；V1–V4 均未命中（环境 range、净利同比 +12%、风险公告 0 条、RSI14 = 56） |
| evidence | 每个数值附 `{evidence_id, feature_key, value, data_as_of = T, fetched_at, provider, epistemic_type = fact}` |
| counter_evidence | C1：行业 20 日相对强弱 −1.8%（弱于大盘）成立 → 同屏展示 |
| invalidation | I1：MA20 < MA60；I2：大盘转下行；退出：X1、X4，止损价 = 10.70 − 2 × 0.31 = 10.08（`plan.entry_price` 以 T+1 实际参考价为准） |
| score / confidence | score = (2+2+1)/(2+2+1+1) × 100 = 83；数据完整度 8/9 = 0.89，维度一致度：非 unknown 维度 5 个中 4 个与买入方向一致 = 0.80，条件余量 0.45 → 0.5×0.89 + 0.3×0.80 + 0.2×0.45 = 0.78 → high（示例计算） |
| 成本估算 | 拟成交 1,000 股 × 10.70 = 10,700 元；ADV20 = 1.0 亿元 → r = 0.0107% → I1 档 0 bp；单边价格成本 = 10 bp |
| 可执行性 | 盘后产生 → `NON_TRADING_TIME`（解除：T+1 09:30）；用户该行业已占 43% → `SECTOR_EXPOSURE_EXCEEDED`（解除：行业占比 < 40%）→ 信号状态 `blocked`，不生成草案 |

---

## 附录 B：与 vision.md 定稿 / plan.md 的差异与待确认项

| # | 项 | vision 定稿 | plan 现稿 | 本模板处理 |
|---|---|---|---|---|
| 1 | 字段总量 | 12 组 + 不可执行原因 + 10 项编排者补充 | §2.5.0A 精简为 8 必填 + 选填 + 系统；§2.5.14 G 已同意多出的字段存入 `extra` | 按定稿列全部字段；用 [B]/[L1]/[L2]/[SYS] 分层 |
| 2 | 运行、复盘、表现记录 | 定稿字段 | 系统字段，不得在文档填写 | 保留字段说明，标 [SYS]，示例中不填 |
| 3 | 验证 | 区间/基准/成本/样本外/交易明细 | 产品不做回测；内部评估待问题 26 | `validation_summary` 摘要（未做写"未验证"）+ E 节 `validation` 机器块；见 validation.md §9 |
| 4 | 冲突与互斥"及优先级" | 编排者补充 | P4 不合并 | 优先级只解释为展示顺序 |
| 5 | 冲击成本 | "成本与滑点" | §2.5.14 G：是否进产品待确认 | **按编排者 12:21 指示进入产品，只放在"成本与滑点"字段**，分档确定性估算（§18），阈值为示例待校准。需架构师同步修改 §2.5.14 G 该行与 §2.13 |
| 6 | 卡片级不可运行原因 | 不可执行原因（信号级） | `gates_missing[]` 系统字段 | 已改：研究员不填，系统按 G1–G7 计算；不进入 23 个原因码 |
| 7 | `dimensions[].role` | 维度及角色 | 枚举 core/auxiliary/veto | v0.1 的 `none` 已删除，不用的维度不写 |
| 8 | 卡片列表与规则的对应 | — | B 节 `{text, expr, status}` | 增加扩展键 `ref` 指向 `rules[].id`，避免两处表达式不一致——**请架构师确认导入器接受 `ref`**，或由导入器校验两处 expr 相同 |
| 9 | `validation` 键名歧义 | — | G 节：单块里 `validation` 既是机器块又含展示摘要 | 摘要改名 `validation_summary`；请架构师在 G 节确认 |
| 10 | fixture 的 `features` 与"不满足"的 state | — | E 节 `features: {feature_key: value}` | 派生值（如 `ma(f.close_qfq,20)`）用表达式字符串作键，引擎是否接受待确认；"核心入场规则不满足"应输出的 state（`wait`/`insufficient_data`？现有 state 枚举里没有"条件不满足"）待架构师明确，FX2 暂写 `insufficient_data` 并标注 |
| 11 | DSL 细节 | — | C 节 | ① `for N days` 的 N 能否引用参数；② 缺少"两数取大"函数（如 `greatest(a,b)`），所以止损暂不写成"ATR 止损与结构止损取高者"，改为两条独立退出规则；③ 跟踪止盈需要 `ctx.highest_close_since_entry`；④ `f.limit_locked_up` 等交易状态特征的标准键名 |
| 12 | 大盘环境枚举 | — | C 节示例 `[uptrend, range]` | 采用 `uptrend/range/downtrend`，`downtrend` 需在 `feature_catalog` 确认 |
| 13 | 因子数量 | 77 | plan "77/85 不一致" | 按 T003：文档 85 个，全部日频，盘中不可用 |
| 14 | 做T fixture | — | E 节要求覆盖"做T 无底仓" | 非做T 卡用"可卖为 0 时触发卖出"代替；请确认 G6 是否对非做T 卡放宽 |
