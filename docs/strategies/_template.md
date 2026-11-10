# 策略知识卡模板（T006a · v0.3 草案）

> 作者：量化策略研究员 · 2026-11-01（v0.2 按 plan §2.5.14 契约与 T003 报告修订；**v0.3（T006a）按 `docs/api-contract.md` v0.2 与 plan §2.5.14 H 节①–⑫、§9 C(1)–C(8) 编排者默认决策对齐**，ST 涨跌幅已核实，见 `market_rules_check.md`）
> 依据：团队文件 vision.md《策略卡字段定稿》（不入库；用户 11:52 表 + 编排者补充 + 不可执行原因 + 11:56 硬性原则）；`docs/plan.md` §2.5.14（导入契约，**字段名、结构、枚举以它为准**，H 节为对本模板 v0.2 的裁决）、`docs/api-contract.md` v0.2（API 字段名、枚举）、§0B、§2.5、§2.8、§2.12、§2.13；`docs/strategy-references.md` §3；团队报告 T003-mairui-capability（不入库；2026-11-01，大部分接口未实测）。
> **字段覆盖以 vision.md 定稿为准，字段名与格式以 plan §2.5.14 为准**。两者的关系：§2.5.14 B 节是导入的最低要求，本模板多出来的字段由导入器存进 `extra` 并在详情页展示（§2.5.14 G）。差异与裁决状态见文末附录 B。
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
5. **可追溯**：每条规则都能产出 `rule_refs`（契约 `RuleRef`：`rule_id`、`role`、`dimension`、`passed`、`value`、`threshold`、`evidence_ids[]`；结果字段是 `passed`，不是 `pass`）和 `evidence`（特征键、取值、`data_as_of`、`fetched_at`、来源）。每张卡至少 1 条 `counter`、1 条 `invalidation`、1 种止损（G1）。
6. **数值**：模板与示例中的数字都是"示例"，不是回测或实测结论。
7. **黑盒模型**（机器学习、合成打分）只能出现在 `model_refs`，角色固定为 `auxiliary`，不计入规则满足率，不能单独触发计划草案（P1b）。LLM 只把结构化证据改写成文字（P1a）。
8. **DSL**：只用 §2.5.14 C 节白名单及 H 节⑤新增：比较、`and/or/not`、`+ - * /`、`ma/ema/atr/highest/lowest/ref/cross_up/cross_down/between/rank_pct/pct_change`；H⑤新增 `max2(a,b)`/`min2(a,b)`（两数取大/小，别名 `greatest`/`least`）、`std(x,n)`、`ts_pct_rank(x,n)`、`rank_pct_in(x, group_key)`；`for N days`、`within N days` 的 N 可以是整数字面量或 `int` 参数 `p.xxx`（须在 `params_schema` 范围内，上限 250）；日内规则用 `for N bars`/`within N bars`。`min(x,n)`/`max(x,n)` 是滚动的 `lowest`/`highest` 别名，**两数取大/小只能用 `max2`/`min2`**。特征写 `f.` 前缀、参数写 `p.` 前缀。`ctx.*`（`ctx.last_price`、`ctx.holding_days`、`ctx.sellable_qty`、`ctx.max_r_reached`；T-B42 新增 `ctx.cost_price`、`ctx.position_weight`、`ctx.sector_weight`、`ctx.highest_close_since_entry`、`ctx.now_hhmm`）和 `plan.*`（`plan.stop_loss`、`plan.take_profit`、`plan.entry_price`）**只能在 hold/weakening/exit 规则中用**，且只在绑定实例与计划时求值。表达式 ≤ 300 字符，嵌套 ≤ 6 层。
9. **契约命名（api-contract v0.2）**：所有 `score` 为 0–100 **整数**或 `null`；证据引用一律 `evidence_ids`（复数数组），不写 `evidence_id`；止损止盈一律嵌套在 `stops{stop_loss, take_profit, time_stop_days}` 中，不平铺。
10. **样本量**（plan H⑧ / §2.12.3）：n < 5 不显示数值；5 ≤ n < 30 标"样本少"（`small_sample=true`）；n ≥ 30 正常。

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
| `risk_level` [OPT] | `normal \| high`（契约枚举 `card_risk_level`，默认 `normal`；plan H⑫）。`high` 的卡默认不启用、不被周期分类器推荐，晋级与展示时附加风险提示 | normal |
| 生命周期、`completeness` [SYS] | `draft/simulating/published/observing/retired` 与完整度由系统计算 | 不填 |

## 2. 来源 [L1]
| 字段 | 填写规范 | 示例 |
|---|---|---|
| `sources[]` [OPT/L1] | `{title, kind, url_or_ref, source_version, license, license_status}`；`kind` ∈ open_source / paper / book / article / internal；`license_status` ∈ `idea_only` / `code_reusable`；CC BY-NC、AGPL、无 LICENSE 的项目只能 `idea_only`（plan §7.6）；查不到版本写"待核实" | KHunter，MIT，idea_only |
| `principle_text` [L1] | 原理解释：给新手看的 3–5 句话，说清"它在赌什么、什么时候会错" | 见附录 A |
| `pitfalls[]` [OPT] | 常见误用与陷阱 | "把下跌趋势中的反弹当回踩" |
| `refs[]` [OPT] | 出处编号列表 `{ref, title, url}`（`url` 可为 `null`），对应 API `GET /strategy-cards/{id}` 的 `refs`；`ref` 用研究员文档里的出处编号（如 `strategy-references §3 #5`）。**注意与 §7 卡片列表项的 `ref: <rule_id>` 是两回事**（同名不同义，见附录 B 第 15 项） | `{ref: "SR-3.5", title: "KHunter", url: "https://github.com/ling-0729/KHunter"}` |

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
| `universe.boards` | 主板 / 创业板 / 科创板 / 北交所逐项写是否包含及原因 | 北交所首版不含（plan §9 C(8)，编排者默认）；ETF、可转债只展示不出信号 |
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
| `missing_policy` | [OPT] | `insufficient_data`（不出信号）/ `dimension_unknown`（该维度 unknown，不阻断）/ `veto_unknown`（否决规则无法判定 → 模板状态照常求值（核心满足时仍为 `entry_ok`、候选信号照常生成并展示），但**买入方向的计划草案被阻断**，记 `KEY_DATA_MISSING`，解除条件 = 字段在新快照中非空；卖出方向不受影响。口径同 plan §9 C(4)、catalog N-01） |
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
3. 卡片列表项用 `ref: <rule_id>` 指向 `rules[]`（plan H①**已采纳**）：必须指向**角色相容**的规则（entry→entry、counter_evidence→counter、invalidation→invalidation、exit→exit/hold/weakening）；卡片项可省略 `expr`（导入器从规则复制），两边都写时去除空白后必须完全一致，否则 `CARD_IMPORT_INVALID`（`issue=ref_expr_mismatch`）。
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
| 交易约束 | 涨跌停价用**当日有效**的规则版本（`market_rule_versions`）。沪深主板风险警示股票（ST/*ST）自 2026-07-06 起 10%（此前 5%；依据上证发〔2026〕41号、深证上〔2026〕551号，2026-04-24 发布，已核实，见 `market_rules_check.md`）；回看 2026-07-06 之前的数据按 5% 段计算 |

### 7.3 边界情况（默认处理，卡内可加严、不可放宽）
| 情况 | 默认处理 |
|---|---|
| 停牌 | 停牌日没有有效 K 线，不补值；`ma(x,n)` 等按"最近 n 根有效 K 线"计算；复牌首日若停牌 ≥ 5 个交易日，入场规则 `insufficient_data` 1 个交易日，退出/失效规则照常求值 |
| 伪停牌占位行 | 日线 `sf=1` 且当日实时快照或分钟线显示有成交 → 视为**数据缺失**（不是停牌），该日记 `DATA_STALE`/`KEY_DATA_MISSING`，不进入指标计算，并上报数据质量告警（T003 §2 疑点，待复核） |
| 缺失值 | 不插值、不前值填充；按 `missing_policy` 处理 |
| 新股/次新股 | 有效 K 线 < `warmup_bars` → `insufficient_data`；上市 < 30 个交易日由闸门阻断买入；注册制新股前 5 日无涨跌幅限制，这几天的 K 线不进入波动类指标窗口 |
| 复权 | 指标用前复权，**每次除权后整段重算**（前复权历史会变），落库记录复权因子版本；收益用后复权；止损价等绝对价格在除权日按复权因子调整并记录事件；1 分钟线不复权，窗口跨除权日时截断 |
| 涨跌停 | 一字涨停买入不可成交、一字跌停卖出不可成交（`LIMIT_LOCKED`）；止损止盈价截断到当日涨跌停价之内（G5）。标准键名（plan H⑥）：`f.limit_up_price`/`f.limit_down_price`（当日涨跌停价）、`f.is_limit_up_close`/`f.is_limit_down_close`（收盘封板）、`f.limit_locked_up`/`f.limit_locked_down`（全天一字板） |
| ST/退市整理 | 闸门阻断买入方向；持仓股变 ST 仍评估卖出方向 |
| 数据陈旧 | 数据 `stale` 时不生成新信号、不翻转（`DATA_STALE`） |

## 8. 入场 [L1 文字；L2 量化]
| 字段 | 规范 | 示例 |
|---|---|---|
| `action_map` | §2.5.14 C：`{entry_all_core_pass: buy, held_hold: hold, exit: sell, else: wait}`。模板状态枚举（契约 `strategy_eval_state`）：`entry_ok / not_triggered / hold_ok / weakening / exit_signal / vetoed / insufficient_data`；`not_triggered`（数据完整、无否决、核心入场未全满足）→ 未持有时 `wait`、已持有时按持有规则（`hold`），不生成候选信号（plan H④） | 同左 |
| `entry_policy.core` / `auxiliary` | 哪些 entry 规则是核心（全部通过才成立）、哪些是辅助（不通过只降分；数据缺失时维度 unknown） | core [E1,E2,E3]；auxiliary [A1] |
| `entry_policy.confirm` | 确认时点与防抖：日线收盘确认；盘中连续 2 根 bar 成立才确认 | 日线收盘确认 |
| `valid_until` | `{trading_days: n}`；plan 默认：做T 当日 14:50、短线 1、波段 5、中长线 20 | `{trading_days: 5}` |
| `entry_policy.price_band` | 参考价 ±（滑点 + 冲击成本），截断到涨跌停价内；参考价口径 plan §2.8 与 §2.8.1 存在不一致，见 validation.md §7.1 | 见 §18 |
| `entry_policy.cooldown_days` | 同模板同证券冷却（plan 默认 3） | 3 |

## 9. 退出 [B 至少一条止损；L2 全部量化]
| 字段 | 规范 |
|---|---|
| `stops.stop_loss` | 止损价公式（可引用 `plan.entry_price`、`atr(n)`；多种止损取较高者用 `max2(a,b)`）；写明 T+1：买入当天不能卖，最早下一交易日 |
| `stops.take_profit` | 止盈价公式或 `null` |
| `stops.time_stop_days` | 时间止损（交易日）；做T 模板必须有当日回补规则或 14:50 时间止损（G1） |
| `exit[]` / `rules` 中 role=exit | 趋势失效类退出（如跌破均线）、结构止损（如跌破前 20 日最低） |
| `exit_policy.trailing` | 跟踪止盈：用 `ctx.highest_close_since_entry`（T-B42 新增）写成 role=exit 规则；T-B42 上线前该规则 G2 不通过 |
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
| `validation_summary.oos_result` | 按 api-contract v0.2 为 `string \| null`：没执行就写 `"未验证"`；执行过写一句含指标、数值、n、区间的文字摘要。**不得填未执行的数字**。（plan 第 881 行写成对象 `{metric, value, n, window}`，与契约冲突，见附录 B 第 16 项） |
| `validation_summary.trade_log_ref` | 研究侧交易明细位置（仅内部） |
| `validation.methods[]` | 必选 `fixture`、`trigger_stats`；可选 `tracking_sim`；问题 26 已定（内部评估仅管理员可见，见 validation.md §0）后可加 `factor_ic`、`event_study`、`param_robustness` |
| `validation.fixtures[]` | ≥ 6 个，格式 `{id, desc, as_of, features: {f.key: value}, series?: {f.key: [最早…最新]}, holding?: {qty, sellable}, ctx?: {ctx.*: v}, plan?: {plan.*: v}, expect: {state, action?, rule_ids_passed[], reason_codes[]?}}`。`features` 键**只能是 `feature_catalog` 的 `f.*` 键**，不能写表达式字符串（否则 `fixture_key_not_in_catalog`）；需要函数值时给 `series`（长度 ≥ 规则 warmup），由求值器计算（plan H③）。覆盖：满足、不满足（`not_triggered`）、缺数据、维度分歧、涨跌停或停牌、做T 无底仓（非做T 卡用"可卖为 0 时出现卖出信号"代替，plan H⑩）。数值全部虚构 |
| `validation.window` / `horizon_days` / `metrics` / `min_n` / `pass_criteria` | 默认 120 日全 A（不含北交所）/ `[1,5,20]` / 每个指标按 `{value, n, window, small_sample}` 输出 / **30**（plan H⑧） |
| `validation.feature_requests[]` | `{name, desc, source_hint, frequency}`：引擎还没有的特征 |

> **键名说明（plan H② 已定）**：摘要用 `validation_summary`（选填展示字段），`validation` **只**放 E 节机器块；在 `validation` 里写摘要键会被导入器拒绝（`issue=summary_key_in_validation`）。用户可见范围按方案 A（§2.12.4）。
>
> **`rule_ids_passed` 的口径（本模板约定，待架构师确认，附录 B 第 17 项）**：列出 `rules[]` 中求值结果为真的全部规则 ID，按 `rules[]` 顺序；对 veto/counter/invalidation 规则，"为真"即"命中"。未持有时不求值引用 `ctx.*`/`plan.*` 的规则；求值结果为 unknown（数据缺失）的规则不列入。

## 12. 运行 [SYS，不填]
系统在卡片详情页展示：最近扫描时间与 `snapshot_id`、数据状态（fresh/stale/partial 与缺失特征）、最近信号与阻断原因。

## 13. 复盘 [SYS + 用户备注，不填]
系统回填"表现记录"：模拟跟踪 T+1/5/20 `{value, n, window, small_sample}`（n < 5 不显示数值；5 ≤ n < 30 标"样本少"）、执行偏差（实际成交 vs 草案参考价）、失效记录、结果归因（市场 / 判断 / 执行，validation.md §7.5）。

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
| `applicability.market_regime[]` | 取 `ctx_market_regime` 产出：`uptrend / range / downtrend`（2 日防抖；`f.market_regime ∈ {uptrend, range, downtrend}`，与 API 枚举 `market_regime` 一致，plan H⑥ 已定；由系统组件 G-02 产出） | [uptrend, range] |
| `applicability.style` | 适合与不适合的风格（大小盘、成长价值、高低波、流动性） | 不适合日均成交额 < 5,000 万元的股票 |
| `applicability.when_not` | 不适用时：`pause`（不产生入场候选，退出照常）/ `warn_only`（照常产生但标"环境不符"） | downtrend → pause |

## 16. 周期与扫描节奏 [L1]
| 字段 | 规范 | 示例 |
|---|---|---|
| `horizons[]` | 见 §1 | [swing] |
| `holding_period` | 预期持有区间（交易日） | 5–60 |
| `scan.schedule` | `daily_close`（盘后批）/ `intraday_1m` / `weekly` / `monthly_first_trading_day`（月度再平衡，如 catalog L-01）/ `event` | daily_close |
| `scan.mode` [OPT] | `post_close_stats`：只做盘后统计、不出盘中信号（plan §9 C(5)，如 T-01 在延迟实测前）；省略 = 正常 | 省略 |
| `scan.intraday_role` | 盘中只监控哪些规则（一般只监控止损/失效，避免盘中噪声改变日线判断） | 只监控 X2 |

## 17. A股交易约束 [L2；系统自动挂载，卡内说明影响]
| 约束 | 说明本策略如何受影响 |
|---|---|
| T+1 | 买入当日不可卖：入场当天的止损无法执行，最早下一交易日（X2 当日照常出信号，执行层记 `T1_NOT_SELLABLE`） |
| 做T 需底仓 | 先买后卖（`buy_first`）需有昨日及以前的可卖底仓；先卖后买（`sell_first`）需有可卖底仓并当日买回；无底仓 → `NO_POSITION`，可卖不足 → `T1_NOT_SELLABLE` |
| 涨跌停 | 主板 10%、创业板/科创板 20%、北交所 30%；沪深主板风险警示股票（ST/*ST）自 2026-07-06 起 10%（此前 5%；上证发〔2026〕41号、深证上〔2026〕551号，见 `market_rules_check.md`），回看按当时有效段；创业板/科创板 ST 本就 20%，不变；注册制新股前 5 日不设限（plan §2.13）；一字板不可成交 |
| 20% 涨跌幅板块 | 创业板/科创板的阈值（ATR 倍数、做T 偏离阈值）是否单独设参 |
| 北交所 | 首版不含（plan §9 C(8)），涉及北交所的卡（如 catalog N-03）暂不可执行；交易单位与涨跌幅不同 |
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
- 卡片键：`costs.impact_adv_days`、`costs.impact_tiers`（plan H⑨，进入产品，`epistemic_type=estimate`，档位为 plan §9 C(6) 初值待校准）。可选 `costs.max_participation_pct`：参与率上限，超过则提示"容量受限"（不新增原因码）。
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
| `score`（0–100 **整数**，四舍五入；契约 `int \| null`） | 本策略规则满足度 = Σ(通过的 entry 规则 weight) / Σ(entry 规则 weight) × 100；**不是股票好坏评分，不跨策略合成** |
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
`fit: {effort: low|medium|high, risk_tolerance_min: 1–5, experience_min: novice|intermediate|advanced}`（§2.5.14 B；枚举与契约 profile.experience 一致，为 `advanced` 不是 `experienced`）；另可写 `capital_min_cny`（至少能买 1 手且满足单标的上限）、`drawdown_expect`、`mismatch_handling`（不匹配时只提示并降置信度；实例化**不需确认**：画像低于 `fit` 下限时 `POST /strategy-instances` 照常 201，只在 `warnings[]` 说明，契约 v0.2.5 `fit_ack` 作废）。`fit` 各项只作提示，不阻止、不封顶。

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
risk_level: normal
# 生命周期、completeness、表现记录：[SYS]，不填

# ===== 2 来源 =====
sources:
  - {title: "KHunter multi_golden_cross / main_uptrend_dip_buy", kind: open_source,
     url_or_ref: "https://github.com/ling-0729/KHunter（strategy/ 目录）", source_version: 待核实,
     license: MIT, license_status: idea_only}
  - {title: "tick-stock-panel pullback_ma20_bounce", kind: open_source,
     url_or_ref: "https://github.com/shy3130/tick-stock-panel", source_version: 待核实,
     license: MIT, license_status: idea_only}
refs:
  - {ref: SR-KHunter, title: "KHunter（strategy-references §3）", url: "https://github.com/ling-0729/KHunter"}
  - {ref: SR-tick-stock-panel, title: "tick-stock-panel（strategy-references §3）", url: "https://github.com/shy3130/tick-stock-panel"}
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
  params_schema.exit_confirm_days: hypothesis
  params_schema.trail_trigger_r: hypothesis
  params_schema.trail_atr_mult: hypothesis
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
  boards: {main: true, chinext: true, star: true, bse: false}   # 北交所首版不含（plan §9 C(8)）
  exclude: ["上市 < 120 个交易日"]
  liquidity: "ma(f.amount, 20) >= p.min_amount"

# ===== 5 数据 [B]（f.* 为本项目特征键；未登记的见 validation.feature_requests）=====
data_needs:
  - {feature_key: f.close_qfq, frequency: daily, adjust: qfq,
     available_at: "T 日日线到齐后（文档：约 17:1x 完成，待交易日实测）",
     source_hint: "日线 history/latest，复权 f（T003 已实测：日线五种复权均有数据）", missing_policy: insufficient_data}
  - {feature_key: f.low_qfq, frequency: daily, adjust: qfq, available_at: 同上, source_hint: 同上}
  - {feature_key: f.high_qfq, frequency: daily, adjust: qfq, available_at: 同上, source_hint: "同上；atr(14) 需要高低收三列"}
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
     expr: "ma(f.close_qfq, p.ma_fast) > ma(f.close_qfq, p.ma_slow) for p.trend_days days"}
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
  - {ref: X2, text: "盘中触及止损价（买入当日可卖为 0 时仍出卖出信号，由 T1_NOT_SELLABLE 阻断执行）", status: quantified,
     expr: "ctx.last_price <= plan.stop_loss"}
  - {ref: X1, text: "收盘跌破 20 日均线连续 2 日：趋势失效", status: quantified,
     expr: "f.close_qfq < ma(f.close_qfq, p.ma_fast) for p.exit_confirm_days days"}
  - {ref: X4, text: "收盘跌破前 20 日最低价：结构止损", status: quantified,
     expr: "f.close_qfq < lowest(ref(f.low_qfq, 1), 20)"}
  - {ref: X3, text: "持有满 40 日仍未达到 1R：时间止损", status: quantified,
     expr: "ctx.holding_days >= p.time_stop and ctx.max_r_reached < 1"}
  - {ref: X5, text: "达到 2R 后，收盘跌破入场以来最高收盘 − 2×ATR14：跟踪止盈", status: quantified,
     expr: "ctx.max_r_reached >= p.trail_trigger_r and f.close_qfq < ctx.highest_close_since_entry - p.trail_atr_mult * atr(14)"}

# ===== 7 规则：规格 [L2] =====
kind: rule_template
rules:
  - {id: E1, dimension: technical, role: entry, weight: 2, eval_time: daily_close, status: quantified,
     expr: "ma(f.close_qfq, p.ma_fast) > ma(f.close_qfq, p.ma_slow) for p.trend_days days", required_features: [f.close_qfq],
     edge_cases: "有效 K 线 < ma_slow + trend_days − 1 → insufficient_data"}
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
     expr: "f.close_qfq < ma(f.close_qfq, p.ma_fast) for p.exit_confirm_days days", required_features: [f.close_qfq]}
  - {id: X2, dimension: technical, role: exit, weight: 0, eval_time: intraday_1m, status: quantified,
     expr: "ctx.last_price <= plan.stop_loss", required_features: [],
     edge_cases: "可卖为 0（买入当日）时信号照常出现，执行层记 T1_NOT_SELLABLE，解除 = 下一交易日 09:30"}
  - {id: X3, dimension: technical, role: exit, weight: 0, eval_time: daily_close, status: quantified,
     expr: "ctx.holding_days >= p.time_stop and ctx.max_r_reached < 1", required_features: []}
  - {id: X4, dimension: technical, role: exit, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.close_qfq < lowest(ref(f.low_qfq, 1), 20)", required_features: [f.close_qfq, f.low_qfq]}
  - {id: X5, dimension: technical, role: exit, weight: 0, eval_time: daily_close, status: quantified,
     expr: "ctx.max_r_reached >= p.trail_trigger_r and f.close_qfq < ctx.highest_close_since_entry - p.trail_atr_mult * atr(14)",
     required_features: [f.close_qfq, f.high_qfq, f.low_qfq], edge_cases: "依赖 T-B42 的 ctx.highest_close_since_entry；上线前 G2 不通过"}
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
  stop_loss: "max2(plan.entry_price - p.atr_mult * atr(14), lowest(ref(f.low_qfq, 1), 20))"   # ATR 止损与结构止损取高者（H⑤）；截断到跌停价之上（G5）；买入当日不可卖
  take_profit: null
  time_stop_days: 40
exit_policy:
  trailing: "见规则 X5（ctx.highest_close_since_entry，T-B42）"
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
  min_n: 30
  pass_criteria:
    - {metric: trigger_rate, op: "<=", value: 0.30}
    - {metric: trigger_rate, op: ">", value: 0}
  fixtures:   # 证券与数值全部虚构（示例）；series 为最早→最新的 70 根有效日 K，最后一根 = as_of 当日
    - id: FX1
      desc: 满足（趋势成立、回踩不破、无否决）
      as_of: "2026-03-02"
      series: &s1
        f.close_qfq: [9.04, 9.08, 9.12, 9.16, 9.2, 9.25, 9.29, 9.33, 9.37, 9.41, 9.46, 9.5, 9.54, 9.58, 9.63, 9.67, 9.71, 9.76, 9.8, 9.85, 9.89, 9.93, 9.98, 10.02, 10.07, 10.11, 10.16, 10.21, 10.25, 10.3, 10.34, 10.39, 10.44, 10.48, 10.53, 10.58, 10.63, 10.67, 10.72, 10.77, 10.82, 10.87, 10.92, 10.97, 11.02, 11.06, 11.11, 11.16, 11.21, 11.27, 11.32, 11.37, 11.42, 11.47, 11.52, 11.57, 11.62, 11.68, 11.73, 11.78, 11.84, 11.89, 11.94, 12.0, 11.91, 11.83, 11.75, 11.77, 11.79, 11.82]
        f.low_qfq: [8.93, 8.97, 9.01, 9.05, 9.09, 9.14, 9.18, 9.22, 9.26, 9.3, 9.35, 9.39, 9.43, 9.47, 9.51, 9.55, 9.59, 9.64, 9.68, 9.73, 9.77, 9.81, 9.86, 9.9, 9.95, 9.99, 10.04, 10.09, 10.13, 10.18, 10.22, 10.27, 10.31, 10.35, 10.4, 10.45, 10.5, 10.54, 10.59, 10.64, 10.69, 10.74, 10.79, 10.84, 10.89, 10.93, 10.98, 11.03, 11.08, 11.13, 11.18, 11.23, 11.28, 11.33, 11.38, 11.43, 11.48, 11.54, 11.59, 11.64, 11.7, 11.75, 11.8, 11.86, 11.77, 11.69, 11.61, 11.63, 11.65, 11.68]
        f.high_qfq: [9.15, 9.19, 9.23, 9.27, 9.31, 9.36, 9.4, 9.44, 9.48, 9.52, 9.57, 9.61, 9.65, 9.69, 9.75, 9.79, 9.83, 9.88, 9.92, 9.97, 10.01, 10.05, 10.1, 10.14, 10.19, 10.23, 10.28, 10.33, 10.37, 10.42, 10.46, 10.51, 10.57, 10.61, 10.66, 10.71, 10.76, 10.8, 10.85, 10.9, 10.95, 11.0, 11.05, 11.1, 11.15, 11.19, 11.24, 11.29, 11.34, 11.41, 11.46, 11.51, 11.56, 11.61, 11.66, 11.71, 11.76, 11.82, 11.87, 11.92, 11.98, 12.03, 12.08, 12.14, 12.05, 11.97, 11.89, 11.91, 11.93, 11.96]
        f.amount: [100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000]
      features: &fbase {f.main_net_20d: 30000000, f.np_yoy_latest: 12.0, f.ann_risk_count_10d: 0, f.rsi14: 56, f.market_regime: range, f.ind_rs20: 1.5}
      expect: {state: entry_ok, action: buy, rule_ids_passed: [E1, E2, E3, A1]}
    - id: FX2
      desc: 不满足（当日收盘跌破 MA20，E2 不成立）
      as_of: "2026-03-02"
      series:
        f.close_qfq: [9.04, 9.08, 9.12, 9.16, 9.2, 9.25, 9.29, 9.33, 9.37, 9.41, 9.46, 9.5, 9.54, 9.58, 9.63, 9.67, 9.71, 9.76, 9.8, 9.85, 9.89, 9.93, 9.98, 10.02, 10.07, 10.11, 10.16, 10.21, 10.25, 10.3, 10.34, 10.39, 10.44, 10.48, 10.53, 10.58, 10.63, 10.67, 10.72, 10.77, 10.82, 10.87, 10.92, 10.97, 11.02, 11.06, 11.11, 11.16, 11.21, 11.27, 11.32, 11.37, 11.42, 11.47, 11.52, 11.57, 11.62, 11.68, 11.73, 11.78, 11.84, 11.89, 11.94, 12.0, 11.91, 11.83, 11.75, 11.77, 11.79, 11.26]
        f.low_qfq: [8.93, 8.97, 9.01, 9.05, 9.09, 9.14, 9.18, 9.22, 9.26, 9.3, 9.35, 9.39, 9.43, 9.47, 9.51, 9.55, 9.59, 9.64, 9.68, 9.73, 9.77, 9.81, 9.86, 9.9, 9.95, 9.99, 10.04, 10.09, 10.13, 10.18, 10.22, 10.27, 10.31, 10.35, 10.4, 10.45, 10.5, 10.54, 10.59, 10.64, 10.69, 10.74, 10.79, 10.84, 10.89, 10.93, 10.98, 11.03, 11.08, 11.13, 11.18, 11.23, 11.28, 11.33, 11.38, 11.43, 11.48, 11.54, 11.59, 11.64, 11.7, 11.75, 11.8, 11.86, 11.77, 11.69, 11.61, 11.63, 11.65, 11.15]
        f.high_qfq: [9.15, 9.19, 9.23, 9.27, 9.31, 9.36, 9.4, 9.44, 9.48, 9.52, 9.57, 9.61, 9.65, 9.69, 9.75, 9.79, 9.83, 9.88, 9.92, 9.97, 10.01, 10.05, 10.1, 10.14, 10.19, 10.23, 10.28, 10.33, 10.37, 10.42, 10.46, 10.51, 10.57, 10.61, 10.66, 10.71, 10.76, 10.8, 10.85, 10.9, 10.95, 11.0, 11.05, 11.1, 11.15, 11.19, 11.24, 11.29, 11.34, 11.41, 11.46, 11.51, 11.56, 11.61, 11.66, 11.71, 11.76, 11.82, 11.87, 11.92, 11.98, 12.03, 12.08, 12.14, 12.05, 11.97, 11.89, 11.91, 11.93, 11.79]
        f.amount: [100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000]
      features: *fbase
      expect: {state: not_triggered, action: wait, rule_ids_passed: [E1, E3, A1]}
    - id: FX3
      desc: 缺数据（净利润同比缺失，V2 否决无法判定 → 按 C(4) 阻断买入草案）
      as_of: "2026-03-02"
      series: *s1
      features: {f.main_net_20d: 30000000, f.np_yoy_latest: null, f.ann_risk_count_10d: 0, f.rsi14: 56, f.market_regime: range, f.ind_rs20: 1.5}
      expect: {state: entry_ok, action: buy, rule_ids_passed: [E1, E2, E3, A1], reason_codes: [KEY_DATA_MISSING]}
    - id: FX4
      desc: 维度分歧（技术满足；行业弱于大盘、主力资金净流出）
      as_of: "2026-03-02"
      series: *s1
      features: {f.main_net_20d: -20000000, f.np_yoy_latest: 12.0, f.ann_risk_count_10d: 0, f.rsi14: 56, f.market_regime: range, f.ind_rs20: -1.8}
      expect: {state: entry_ok, action: buy, rule_ids_passed: [E1, E2, E3, C1, C2]}
    - id: FX5
      desc: 一字涨停（规则满足，但买入不可成交）
      as_of: "2026-03-02"
      series: *s1
      features: {f.main_net_20d: 30000000, f.np_yoy_latest: 12.0, f.ann_risk_count_10d: 0, f.rsi14: 56, f.market_regime: range, f.ind_rs20: 1.5, f.limit_locked_up: true}
      expect: {state: entry_ok, action: buy, rule_ids_passed: [E1, E2, E3, A1], reason_codes: [LIMIT_LOCKED]}
    - id: FX6
      desc: 当日买入（可卖为 0）后盘中触及止损（代替"做T无底仓"，plan H⑩）
      as_of: "2026-03-03"
      series:
        f.close_qfq: [9.04, 9.08, 9.12, 9.16, 9.2, 9.25, 9.29, 9.33, 9.37, 9.41, 9.46, 9.5, 9.54, 9.58, 9.63, 9.67, 9.71, 9.76, 9.8, 9.85, 9.89, 9.93, 9.98, 10.02, 10.07, 10.11, 10.16, 10.21, 10.25, 10.3, 10.34, 10.39, 10.44, 10.48, 10.53, 10.58, 10.63, 10.67, 10.72, 10.77, 10.82, 10.87, 10.92, 10.97, 11.02, 11.06, 11.11, 11.16, 11.21, 11.27, 11.32, 11.37, 11.42, 11.47, 11.52, 11.57, 11.62, 11.68, 11.73, 11.78, 11.84, 11.89, 11.94, 12.0, 11.91, 11.83, 11.75, 11.77, 11.3, 11.18]
        f.low_qfq: [8.93, 8.97, 9.01, 9.05, 9.09, 9.14, 9.18, 9.22, 9.26, 9.3, 9.35, 9.39, 9.43, 9.47, 9.51, 9.55, 9.59, 9.64, 9.68, 9.73, 9.77, 9.81, 9.86, 9.9, 9.95, 9.99, 10.04, 10.09, 10.13, 10.18, 10.22, 10.27, 10.31, 10.35, 10.4, 10.45, 10.5, 10.54, 10.59, 10.64, 10.69, 10.74, 10.79, 10.84, 10.89, 10.93, 10.98, 11.03, 11.08, 11.13, 11.18, 11.23, 11.28, 11.33, 11.38, 11.43, 11.48, 11.54, 11.59, 11.64, 11.7, 11.75, 11.8, 11.86, 11.77, 11.69, 11.61, 11.63, 11.19, 11.07]
        f.high_qfq: [9.15, 9.19, 9.23, 9.27, 9.31, 9.36, 9.4, 9.44, 9.48, 9.52, 9.57, 9.61, 9.65, 9.69, 9.75, 9.79, 9.83, 9.88, 9.92, 9.97, 10.01, 10.05, 10.1, 10.14, 10.19, 10.23, 10.28, 10.33, 10.37, 10.42, 10.46, 10.51, 10.57, 10.61, 10.66, 10.71, 10.76, 10.8, 10.85, 10.9, 10.95, 11.0, 11.05, 11.1, 11.15, 11.19, 11.24, 11.29, 11.34, 11.41, 11.46, 11.51, 11.56, 11.61, 11.66, 11.71, 11.76, 11.82, 11.87, 11.92, 11.98, 12.03, 12.08, 12.14, 12.05, 11.97, 11.89, 11.91, 11.77, 11.3]
        f.amount: [100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000, 104000000, 102000000, 100000000, 116000000, 114000000, 112000000, 110000000, 108000000, 106000000]
      features: *fbase
      holding: {qty: 1000, sellable: 0}
      ctx: {ctx.last_price: 11.10, ctx.holding_days: 0, ctx.sellable_qty: 0, ctx.max_r_reached: 0, ctx.highest_close_since_entry: 11.18}
      plan: {plan.entry_price: 11.28, plan.stop_loss: 11.13}
      expect: {state: exit_signal, action: sell, rule_ids_passed: [E1, E3, A1, X1, X2], reason_codes: [T1_NOT_SELLABLE]}
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
  max_participation_pct: 0.02     # 示例：参与率 > 2% 标"容量受限"
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
  min_amount:       {type: float, default: 50000000, min: 10000000, max: 500000000, step: 10000000, desc: 日均成交额下限, unit: 元}
  trend_days:       {type: int,   default: 5,     min: 3,     max: 10,    step: 1,     desc: 趋势确认天数（E1 的 for N days）, unit: 交易日}
  exit_confirm_days: {type: int,  default: 2,     min: 1,     max: 5,     step: 1,     desc: 跌破均线确认天数（X1）, unit: 交易日}
  trail_trigger_r:  {type: float, default: 2.0,   min: 1.0,   max: 4.0,   step: 0.5,   desc: 启动跟踪止盈的 R 倍数（X5）}
  trail_atr_mult:   {type: float, default: 2.0,   min: 1.0,   max: 4.0,   step: 0.5,   desc: 跟踪止盈 ATR 倍数（X5）}
  slippage_bp:      {type: float, default: 10,    min: 0,     max: 100,   step: 5,     desc: 基础滑点, unit: bp, user_editable: false}
# sensitivity：全部"未评估"
# 说明：数值一律写成普通数字（不用 5.0e7 这类科学计数法：YAML 1.1 解析器会把它读成字符串）

# ===== 23 审计 =====
changelog: [{version_no: 1, date: 2026-11-01, author: 策略研究员, change: "初稿；T006a 按 api-contract v0.2 / plan H 对齐（示例卡未发布，故未递增版本）", reason: T006}]

# ===== 24 合规文案 =====
compliance_variants:
  signal_title: "按《波段·均线趋势回踩 v1》规则：买入条件满足（候选，{k}/{n} 条）"
  disclaimer: "本工具基于您选择的规则对公开数据进行计算，输出为规则信号，不构成投资建议或收益承诺；交易决策与风险由您自行承担。"
```

### A.1 一条候选信号的追溯链（证券与数值均为虚构示例；行情序列取自 FX1 的 `series`，A1/C1 的取值与 FX1 不同，用来演示 unknown 维度与反证同屏）
| 项 | 内容 |
|---|---|
| 证券 | `600000.SH`（虚构示例，不代表该证券的任何真实情况） |
| 生成时点 | 示例交易日 T 18:05（北京时间），`snapshot_id = sn_示例`，`feature_set_version = fs_示例` |
| state / 候选动作 | `entry_ok` / 未持有 → `buy`，展示为"规则信号：买入条件满足（候选，3/3 条核心）" |
| rule_refs（`RuleRef`） | E1：MA20 = 11.70 > MA60 = 10.79，连续 ≥ `p.trend_days`（5）日，`passed: true`；E2：近 3 日最低 11.63 ≤ 11.70 × 1.02 = 11.93，且收盘 11.82 > 11.70，`passed: true`；E3：11.82 ≥ 12.00 × 0.85 = 10.20，`passed: true`；A1：主力 20 日净额缺失 → 资金维度 unknown（不列入 `rule_refs` 的 passed 结果）；V1–V4 均 `passed: false`（未命中：环境 range、净利同比 +12%、风险公告 0 条、RSI14 = 56）。每条带 `evidence_ids` |
| evidence | 每个数值一条 `{id, feature_key, value, data_as_of = T, fetched_at, provider, epistemic_type = fact}`，由 `rule_refs[].evidence_ids` 引用 |
| counter_evidence | C1：行业 20 日相对强弱 −1.8%（弱于大盘）命中 → 同屏展示 |
| invalidation / stops | I1：MA20 < MA60；I2：大盘转下行；退出 X1、X4、X5。`stops.stop_loss` = max2(11.82 − 2 × 0.28, 11.13) = 11.26（假设参考价 11.82；`plan.entry_price` 以 T+1 实际参考价为准），`stops.take_profit = null`，`stops.time_stop_days = 40` |
| score / confidence | score = round((2+2+1)/(2+2+1+1) × 100) = 83（整数）；数据完整度 9/10 = 0.90（10 个必需特征缺 1 个），维度一致度：非 unknown 维度 5 个中 4 个与买入方向一致 = 0.80，条件余量 0.45（示例）→ 0.5×0.90 + 0.3×0.80 + 0.2×0.45 = 0.78 → high（示例计算） |
| 成本估算 | 拟成交 1,000 股 × 11.82 = 11,820 元；ADV20 ≈ 1.079 亿元 → r ≈ 0.011% → I1 档 0 bp；单边价格成本 = 10 bp |
| 可执行性 | 盘后产生 → `NON_TRADING_TIME`（解除：T+1 09:30）；用户该行业已占 43% → `SECTOR_EXPOSURE_EXCEEDED`（解除：行业占比 < 40%）→ 信号状态 `blocked`，不生成草案 |

---

## 附录 B：与 vision.md 定稿 / plan.md 的差异与待确认项（v0.3：已按 plan §2.5.14 H 与 api-contract v0.2 标注状态）

| # | 项 | vision 定稿 | plan / 契约现稿 | 本模板处理 | 状态 |
|---|---|---|---|---|---|
| 1 | 字段总量 | 12 组 + 不可执行原因 + 10 项编排者补充 | §2.5.0A 精简为 8 必填 + 选填 + 系统；§2.5.14 G 同意多出的字段存入 `extra` | 按定稿列全部字段；用 [B]/[L1]/[L2]/[SYS] 分层 | 已一致 |
| 2 | 运行、复盘、表现记录 | 定稿字段 | 系统字段，不得在文档填写 | 保留字段说明，标 [SYS]，示例中不填 | 已一致 |
| 3 | 验证 | 区间/基准/成本/样本外/交易明细 | 问题 26 已定：内部评估仅管理员可见（方案 A） | `validation_summary` + E 节 `validation` | **已解决**（H②、§9 问题 26） |
| 4 | 冲突与互斥"及优先级" | 编排者补充 | P4 不合并 | 优先级只解释为展示顺序 | 已一致 |
| 5 | 冲击成本 | "成本与滑点" | H⑨：进入产品，`costs.impact_*`；§9 C(6) 分档为初值 | §18 分档确定性估算，示例待校准 | **已解决**（H⑨） |
| 6 | 卡片级不可运行原因 | 不可执行原因（信号级） | `gates_missing[]` 系统字段 | 研究员不填 | 已一致 |
| 7 | `dimensions[].role` | 维度及角色 | core/auxiliary/veto | 不用的维度不写 | 已一致 |
| 8 | 卡片列表 `ref` | — | H①：采纳，角色相容，`ref_expr_mismatch` | §7.1 第 3 条 | **已解决**（H①） |
| 9 | `validation` 键名 | — | H②：分开，`summary_key_in_validation` | §11 键名说明 | **已解决**（H②） |
| 10 | fixture 键与"不满足"的 state | — | H③：键只能是 `f.*`，函数值用 `series`；H④：新增 `not_triggered` | 附录 A 夹具改用 `series`，FX2 改为 `not_triggered` | **已解决**（H③④） |
| 11 | DSL 细节 | — | H⑤：`for p.x days`、`max2/min2`、`std`、`ts_pct_rank`、`rank_pct_in`、`for N bars`；T-B42 新增 ctx；H⑥ 涨跌停键名 | E1/X1 用参数天数；止损改 `max2`；跟踪止盈写成 X5；§7.3 列标准键名 | **已解决**（H⑤⑥；实现依赖 T-B42） |
| 12 | 大盘环境枚举 | — | H⑥：`uptrend/range/downtrend` | 同左 | **已解决**（H⑥） |
| 13 | 因子数量 | 77 | H⑪：以 `feature_catalog` 为准 | 全部日频，盘中只用 T−1 | **已解决**（H⑪） |
| 14 | 非做T卡的无底仓夹具 | — | H⑩：可用"可卖为 0 时出现卖出信号"替代 | FX6 | **已解决**（H⑩） |
| 15 | `refs` 与列表项 `ref` 同名 | — | 契约 `GET /strategy-cards/{id}` 返回卡片级 `refs: [{ref, title, url}]`；H① 的列表项 `ref` 指规则 ID | 两者都用，文档中分别说明 | **待架构师确认**：导入器按位置区分即可，建议在 §2.5.14 B 写明 `refs` 为卡片级选填字段 |
| 16 | `oos_result` 类型 | — | 契约 v0.2：`string \| null`；plan 第 881 行：对象 `{metric, value, n, window}` | 按契约写字符串 | **待架构师统一** |
| 17 | `rule_ids_passed` 与 `passed` 的语义 | — | 契约 `RuleRef.passed: boolean`；未定义 veto/counter 规则"passed"是指"命中"还是"未命中" | 本模板约定：求值为真即列入（veto/counter 为真 = 命中），unknown 不列入，未持有时不求值 ctx/plan 规则 | **已解决**（契约 v0.2.2，T-A02 提交 044b50b：`RuleRef.passed` 为 boolean \| null，`rule_ids_passed` 只列求值为真的规则） |
| 18 | 涨跌停夹具的期望 state | — | 一字涨停时，系统组件 G-01 闸门（买入方向 veto）与执行层 `LIMIT_LOCKED` 都可能生效 | FX5 写为模板自身 `entry_ok` + `reason_codes: [LIMIT_LOCKED]`（夹具只评估本模板，不挂系统组件） | **待架构师确认** |
| 19 | `ctx.*` 只能用于 hold/weakening/exit | — | catalog T-01 的入场规则需要 `ctx.now_hhmm`（时间条件） | T-01 目前为 `post_close_stats`，暂不受影响 | **待架构师确认**：`ctx.now_hhmm` 是否例外允许在 entry 规则中使用 |
| 20 | ST 涨跌幅 | — | plan §2.13 / market_rules：主板 ST 自 2026-07-06 起 10% | 已核实官方出处（`market_rules_check.md`），§7.2、§17 已同步 | **已核实**；plan 问题 36 与 §2.13"待核实"标记可关闭（需架构师改 plan） |
