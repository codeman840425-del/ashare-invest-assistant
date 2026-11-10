# T-R58 我方参数清查（T-A142、T-A143 契约与 H-01、W-01、S-01 卡）

> 状态只有四类：**有出处**（外部公开资料、制度原文、内部实测或用户决定，下表「依据」列写明是哪种）；**有回测**（本仓有可复核的历史回测结果；虚构夹具不算）；**未验证**；**制度参数，有出处**（交易所/监管/税务规则）。
> 范围：契约按提交读取——T-A143 = `362ad41`，T-A142 = `0dfaae9`；卡片按 origin/main `ef32153`（H-01 v3、W-01 v2、S-01 v2），另列 S-01 v3 草稿（`d10ebd8`，T-R57）的新增参数。T-01/T-02 前期做T卡作为补充一并清查。
> 每一行的「位置」均已用脚本核对该行确实含所列取值（不一致则不入表）。同一取值在一张卡里重复出现（如 C(7) 与 costs 区）只列一次。表中阈值仅作候选信号/计划条件讨论。

## 1 统计

| 范围 | 有出处 | 有回测 | 未验证 | 制度参数，有出处 | 合计 |
|---|---|---|---|---|---|
| T-A143 | 6 | 0 | 17 | 0 | 23 |
| T-A142 | 6 | 0 | 4 | 0 | 10 |
| H-01 v3 | 0 | 0 | 20 | 5 | 25 |
| W-01 v2 | 0 | 0 | 37 | 4 | 41 |
| S-01 v2 | 0 | 0 | 24 | 2 | 26 |
| S-01 v3（d10ebd8） | 0 | 0 | 2 | 0 | 2 |
| 做T 前期卡（补充） | 2 | 0 | 21 | 0 | 23 |
| **合计** | **14** | **0** | **125** | **11** | **150** |

- 「有回测」为 0：本仓没有任何一份针对上述参数的历史回测结果；`T-R43/s01_fixture_eval.py` 等只跑【虚构】夹具，不计入。
- 「未验证」125 项中，策略/展示/风控阈值 69 项（卡内多已自标 hypothesis 或 estimate），其余为估计、统计惯例、工程或待用户决定的项。
- 「有出处」14 项里，只有量比回看 5 日、240 分钟/日、VWAP 偏离的定义式等来自外部公开资料（且均为「惯例」，不是阈值实证）；其余是内部实测、推导或用户答卡。**没有任何一个做T触发阈值（偏离、量比、k、spike 等）属于「有出处」中的实证。**
- T-02 的「短窗涨速 3%」列为有出处，是指数值取自 QMT-QuantLimit 项目，并非该数值被检验过。

## 2 明细

### T-A143

| 位置 | 参数 | 取值 | 状态 | 性质 | 依据 / 备注 |
|---|---|---|---|---|---|
| `362ad41:docs/contracts/intraday-bars.md:89` | VWAP 偏离 dev_pct 定义 | (收盘−VWAP)/VWAP | 有出处 | 指标定义 | 与 qlib VWAP0、TSP 分时均价同类；单位实测见 catalog.md:105 |
| `362ad41:docs/contracts/intraday-bars.md:90` | 量比回看天数 | 5 个交易日 | 有出处 | 指标定义 | 聚宽 LB N=5、天软、SuperMind（reference_survey §3.1） |
| `362ad41:docs/contracts/intraday-bars.md:90` | 量比口径 | 同一时刻累计量之比 | 未验证 | 指标定义 | 与惯例口径（每分钟均量之比）不同，无外部出处，需裁定 |
| `362ad41:docs/contracts/intraday-bars.md:91` | VWAP 偏离阈值 | \|dev_pct\| ≥ 2% | 未验证 | 策略阈值 | 无外部出处；已称撤回但本提交仍在 |
| `362ad41:docs/contracts/intraday-bars.md:91` | 量比阈值 | ≥ 2 | 未验证 | 策略阈值 | 无外部出处 |
| `362ad41:docs/contracts/intraday-bars.md:222` | Q5 推荐初值 | 2% 与 2 倍 | 未验证 | 策略阈值 | 同上（重复出现） |
| `362ad41:docs/contracts/intraday-bars.md:47` | 每日 1 分钟 bar 数 | 240 | 有出处 | 制度/惯例 | 沪深连续交易 4 小时；天软、SuperMind 同按 240 分钟/日 |
| `362ad41:docs/contracts/intraday-bars.md:47` | 年交易日数 | 242 | 未验证 | 工程估算 | 容量估算用，未核对交易日历 |
| `362ad41:docs/contracts/intraday-bars.md:47` | 每行字节数 | 约 110 B | 未验证 | 工程估算 | 口径同 plan §3A.2，未实测 |
| `362ad41:docs/contracts/intraday-bars.md:47` | 压缩比 | 10 倍 | 未验证 | 工程估算 | 未实测 |
| `362ad41:docs/contracts/intraday-bars.md:31` | .lc 每条字节数 | 32 字节 | 未验证 | 数据格式 | 契约自标「公开资料，未实测」 |
| `362ad41:docs/contracts/intraday-bars.md:21` | 串行时延 | 0.26 s / 1.85 s | 有出处 | 工程实测 | 内部实测（T003、T-A136），两处不一致 |
| `362ad41:docs/contracts/intraday-bars.md:60` | 1 分钟 chunk | 1 天 | 未验证 | 工程 | 沿用基线，无性能实测 |
| `362ad41:docs/contracts/intraday-bars.md:64` | 5 分钟 chunk | 7 天 | 未验证 | 工程 |  |
| `362ad41:docs/contracts/intraday-bars.md:66` | 压缩时点 | chunk 满 7 天 | 未验证 | 工程 | plan §3A 原定 |
| `362ad41:docs/contracts/intraday-bars.md:68` | 1 分钟保留期（推荐） | 3 年 | 未验证 | 用户待定 | Q6 待答 |
| `362ad41:docs/contracts/intraday-bars.md:69` | 保留期（保守默认） | 不自动删除 | 未验证 | 用户待定 | Q6 待答 |
| `362ad41:docs/contracts/intraday-bars.md:126` | 盘中采集范围/频率 | 持仓 ≤20 只、每 1 分钟 | 未验证 | 用户待定 | Q2 待答 |
| `362ad41:docs/contracts/intraday-bars.md:131` | INTRADAY_BARS_PER_MINUTE_LIMIT | 默认 0，硬上界 30 | 有出处 | 工程 | 由 1.85 s/次 → 每分钟约 32 次推算（:122） |
| `362ad41:docs/contracts/intraday-bars.md:134` | 盘后补齐时间窗 | 15:30 起，17:00 前结束 | 未验证 | 工程排程 |  |
| `362ad41:docs/contracts/intraday-bars.md:134` | 批大小 | 500 次/批 | 有出处 | 用户决定 | 沿用 T-A142 用户答卡值 |
| `362ad41:docs/contracts/intraday-bars.md:138` | 盘中回避窗口 | 09:15–15:05 | 未验证 | 工程排程 | 09:15 为竞价开始（制度），15:05 为留余量 |
| `362ad41:docs/contracts/intraday-bars.md:221` | 首次实调次数 | 约 10 次 | 未验证 | 用户待定 | Q4 待答 |

### T-A142

| 位置 | 参数 | 取值 | 状态 | 性质 | 依据 / 备注 |
|---|---|---|---|---|---|
| `0dfaae9:docs/contracts/daily-bars-source.md:592` | 日报时刻 | 17:30 | 有出处 | 用户决定 | 用户 11-10 答卡（同文件 :586 节） |
| `0dfaae9:docs/contracts/daily-bars-source.md:605` | 容量估算 | 1.85 s/次 → 15 分钟约 480 次 | 有出处 | 工程实测 | 内部实测推算 |
| `0dfaae9:docs/contracts/daily-bars-source.md:619` | 回填窗口 | 3 年 | 未验证 | 工程 |  |
| `0dfaae9:docs/contracts/daily-bars-source.md:621` | 延迟入队窗口 | [17:00, 17:45) | 未验证 | 工程排程 |  |
| `0dfaae9:docs/contracts/daily-bars-source.md:642` | DAILY_BARS_BATCH_LIMIT | 0 → 500 | 有出处 | 用户决定 | 用户答卡 |
| `0dfaae9:docs/contracts/daily-bars-source.md:643` | DAILY_BARS_BATCH_CEILING | 500 | 有出处 | 用户决定 | 用户答卡 |
| `0dfaae9:docs/contracts/daily-bars-tdx.md:32` | 股票价格换算 | 整数 ÷100 | 有出处 | 数据格式 | 通达信日线格式公开资料 |
| `0dfaae9:docs/contracts/daily-bars-tdx.md:81` | 单位自检容差 / 拒收比例 | 1% / 5% | 未验证 | 工程 |  |
| `0dfaae9:docs/contracts/daily-bars-tdx.md:109` | amount 比对容差 | max(1 元, 2.4e-7×) | 有出处 | 工程推导 | float32 相对精度 ×2，原文写明推导 |
| `0dfaae9:docs/contracts/today-view.md:45` | S5 逾时时刻 | 17:45 | 未验证 | 工程排程 | 由日报 17:30 + 余量 |

### H-01 v3

| 位置 | 参数 | 取值 | 状态 | 性质 | 依据 / 备注 |
|---|---|---|---|---|---|
| `docs/strategies/cards/hold_risk_monitor.md:17` | 创业板/科创板涨跌幅；新股前 5 日无涨跌幅 | 20% / 5 日 | 制度参数，有出处 | 制度 | market_rules_check.md:26-33 官方出处 O1–O8 |
| `docs/strategies/cards/hold_risk_monitor.md:83` | 卖出印花税 | 0.0005 | 制度参数，有出处 | 制度 | 财政部 税务总局公告 2023 年第 39 号 |
| `docs/strategies/cards/hold_risk_monitor.md:84` | 过户费 | 0.00001 | 制度参数，有出处 | 制度 | 中国结算 2022-04-29 起 0.01‰（新华社报道） |
| `docs/strategies/cards/hold_risk_monitor.md:85` | 滑点 | 10 bp | 未验证 | 估计 | plan 默认 |
| `docs/strategies/cards/hold_risk_monitor.md:86` | 冲击 ADV 天数 | 20 | 未验证 | 估计 | plan:1619 「编排者默认，初值待校准」 |
| `docs/strategies/cards/hold_risk_monitor.md:87` | 最大参与率 | 0.02 | 未验证 | 估计 | 同上 |
| `docs/strategies/cards/hold_risk_monitor.md:88` | 冲击分档 | 0/5/15/30/60 bp | 未验证 | 估计 | 同上 |
| `docs/strategies/cards/hold_risk_monitor.md:89` | 科创板零股 | <200 股 | 制度参数，有出处 | 制度 | 科创板交易规则（market_rules_check 出处） |
| `docs/strategies/cards/hold_risk_monitor.md:99` | ma_long | 60（40–120） | 未验证 | 策略阈值 | 卡内 epistemic: hypothesis |
| `docs/strategies/cards/hold_risk_monitor.md:100` | ma_break_days | 3 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/hold_risk_monitor.md:101` | reclaim_days | 2 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/hold_risk_monitor.md:102` | cost_atr_k | 2.0 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/hold_risk_monitor.md:103` | single_cap | 0.20 | 未验证 | 风控 | 卡内 estimate |
| `docs/strategies/cards/hold_risk_monitor.md:104` | sector_cap | 0.40 | 未验证 | 风控 | 卡内 estimate |
| `docs/strategies/cards/hold_risk_monitor.md:112` | C2 均线 | MA20 | 未验证 | 策略阈值 |  |
| `docs/strategies/cards/hold_risk_monitor.md:116` | 维度看多/看空阈值 | 0.67 / 0.33 | 未验证 | 展示阈值 |  |
| `docs/strategies/cards/hold_risk_monitor.md:117` | 有效期 | 1 交易日 | 未验证 | 展示 |  |
| `docs/strategies/cards/hold_risk_monitor.md:137` | 样本量门槛 | n≥30；5≤n<30 小样本；n<5 不显示 | 未验证 | 统计惯例 | 经验法则，无出处 |
| `docs/strategies/cards/hold_risk_monitor.md:142` | BH 校正 q | 0.10 | 未验证 | 统计惯例 | 方法有出处（BH 1995），q 取值为惯例 |
| `docs/strategies/cards/hold_risk_monitor.md:143` | 示例名义金额 M | 50,000 元 | 未验证 | 示例 |  |
| `docs/strategies/cards/hold_risk_monitor.md:143` | 最低佣金 | 5 元 | 制度参数，有出处 | 制度 | 证监发〔2002〕21 号（T-R58b 已复核：证监会法规库标「现行有效」；实收以券商为准，用户可配置，见 §5） |
| `docs/strategies/cards/hold_risk_monitor.md:151` | 只报告的 α 与邻域 | 0.10；ma_long ±5、ma_break_days ±1 | 未验证 | 统计惯例 |  |
| `docs/strategies/cards/hold_risk_monitor.md:163` | 历史回看 | 120 交易日 | 未验证 | 统计 |  |
| `docs/strategies/cards/hold_risk_monitor.md:167` | min_n | 30 | 未验证 | 统计惯例 |  |
| `docs/strategies/cards/hold_risk_monitor.md:171` | 触发率上限 | 0.3 | 未验证 | 统计 |  |

### W-01 v2

| 位置 | 参数 | 取值 | 状态 | 性质 | 依据 / 备注 |
|---|---|---|---|---|---|
| `docs/strategies/cards/sw_ma_trend_pullback.md:17` | 涨跌幅 / 新股前 5 日 | 20% / 5 日 | 制度参数，有出处 | 制度 | market_rules_check.md |
| `docs/strategies/cards/sw_ma_trend_pullback.md:42` | 证伪：超额观察期 | 20 交易日 | 未验证 | 统计 |  |
| `docs/strategies/cards/sw_ma_trend_pullback.md:43` | 证伪：参数邻域 | ma_fast ±5、pullback_pct ±0.01 | 未验证 | 统计 |  |
| `docs/strategies/cards/sw_ma_trend_pullback.md:44` | 证伪：胜率门槛 | n≥30 时 5 日胜率 <45% | 未验证 | 统计 |  |
| `docs/strategies/cards/sw_ma_trend_pullback.md:113` | 最低佣金 | 5 元 | 制度参数，有出处 | 制度 | 证监发〔2002〕21 号（T-R58b 已复核，用户可配置，见 §5） |
| `docs/strategies/cards/sw_ma_trend_pullback.md:114` | 卖出印花税 | 0.0005 | 制度参数，有出处 | 制度 | 财政部 税务总局公告 2023 年第 39 号 |
| `docs/strategies/cards/sw_ma_trend_pullback.md:115` | 过户费 | 0.00001 | 制度参数，有出处 | 制度 | 中国结算 |
| `docs/strategies/cards/sw_ma_trend_pullback.md:116` | 滑点 | 10 bp | 未验证 | 估计 |  |
| `docs/strategies/cards/sw_ma_trend_pullback.md:117` | 冲击 ADV 天数 | 20 | 未验证 | 估计 | plan:1619 |
| `docs/strategies/cards/sw_ma_trend_pullback.md:118` | 最大参与率 | 0.02 | 未验证 | 估计 | plan:1619 |
| `docs/strategies/cards/sw_ma_trend_pullback.md:119` | 冲击分档 | 0/5/15/30/60 bp | 未验证 | 估计 | 卡内 estimate |
| `docs/strategies/cards/sw_ma_trend_pullback.md:122` | 风险偏好下限 | 3 | 未验证 | 适配 |  |
| `docs/strategies/cards/sw_ma_trend_pullback.md:131` | ma_fast | 20 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/sw_ma_trend_pullback.md:132` | ma_slow | 60 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/sw_ma_trend_pullback.md:133` | trend_days | 5 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/sw_ma_trend_pullback.md:134` | pullback_pct | 0.02 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/sw_ma_trend_pullback.md:135` | max_dd_from_high | 0.15 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/sw_ma_trend_pullback.md:136` | exit_confirm_days | 2 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/sw_ma_trend_pullback.md:137` | atr_mult | 2.0 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/sw_ma_trend_pullback.md:138` | time_stop | 40 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/sw_ma_trend_pullback.md:139` | trail_trigger_r | 2.0 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/sw_ma_trend_pullback.md:140` | trail_atr_mult | 2.0 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/sw_ma_trend_pullback.md:141` | rsi_overheat | 75 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/sw_ma_trend_pullback.md:142` | np_yoy_floor | −30% | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/sw_ma_trend_pullback.md:143` | min_amount | 5,000 万元 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/sw_ma_trend_pullback.md:144` | min_list_days | 120 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/sw_ma_trend_pullback.md:145` | slippage_bp | 10 | 未验证 | 估计 | estimate |
| `docs/strategies/cards/sw_ma_trend_pullback.md:146` | fixed_cost_bp | 8 | 未验证 | 估计 | estimate |
| `docs/strategies/cards/sw_ma_trend_pullback.md:147` | min_edge_cost_mult | 3.0 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/sw_ma_trend_pullback.md:150` | E2 回看 | 3 日最低 | 未验证 | 策略阈值 |  |
| `docs/strategies/cards/sw_ma_trend_pullback.md:151` | E3 回看 | 60 日最高 | 未验证 | 策略阈值 |  |
| `docs/strategies/cards/sw_ma_trend_pullback.md:160` | C3 缩量 | <20 日均额×0.5 | 未验证 | 策略阈值 |  |
| `docs/strategies/cards/sw_ma_trend_pullback.md:165` | X3 R 倍数 | 1R | 未验证 | 策略阈值 |  |
| `docs/strategies/cards/sw_ma_trend_pullback.md:166` | X4 回看 | 20 日最低 | 未验证 | 策略阈值 |  |
| `docs/strategies/cards/sw_ma_trend_pullback.md:170` | time_stop_days | 40 | 未验证 | 策略阈值 |  |
| `docs/strategies/cards/sw_ma_trend_pullback.md:171` | 维度看多/看空阈值 | 0.67 / 0.33 | 未验证 | 展示阈值 |  |
| `docs/strategies/cards/sw_ma_trend_pullback.md:173` | 有效期 | 5 交易日 | 未验证 | 展示 |  |
| `docs/strategies/cards/sw_ma_trend_pullback.md:182` | 历史回看 | 120 | 未验证 | 统计 |  |
| `docs/strategies/cards/sw_ma_trend_pullback.md:186` | min_n | 30 | 未验证 | 统计惯例 |  |
| `docs/strategies/cards/sw_ma_trend_pullback.md:190` | 触发率上限 | 0.3 | 未验证 | 统计 |  |
| `docs/strategies/cards/sw_ma_trend_pullback.md:193` | 触发率下限 | >0 | 未验证 | 统计 |  |

### S-01 v2

| 位置 | 参数 | 取值 | 状态 | 性质 | 依据 / 备注 |
|---|---|---|---|---|---|
| `docs/strategies/cards/st_pullback_ma.md:19` | 涨跌幅 / 新股前 5 日 | 20% / 5 日 | 制度参数，有出处 | 制度 | market_rules_check.md |
| `docs/strategies/cards/st_pullback_ma.md:38` | 证伪：超额观察期 | 5 交易日 | 未验证 | 统计 |  |
| `docs/strategies/cards/st_pullback_ma.md:39` | 证伪：胜率门槛 | n≥30 后 5 日胜率 <45% | 未验证 | 统计 |  |
| `docs/strategies/cards/st_pullback_ma.md:40` | 证伪：参数邻域 | rs_min ±0.05、shrink_ratio ±0.1 | 未验证 | 统计 |  |
| `docs/strategies/cards/st_pullback_ma.md:86` | 科创板整手 | ≥200 股 | 制度参数，有出处 | 制度 | 科创板交易规则 |
| `docs/strategies/cards/st_pullback_ma.md:96` | rs_min | 0.15 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/st_pullback_ma.md:97` | touch_pct | 0.01 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/st_pullback_ma.md:98` | shrink_ratio | 0.7 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/st_pullback_ma.md:99` | exit_confirm_days | 2 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/st_pullback_ma.md:100` | hard_stop_pct | 0.08 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/st_pullback_ma.md:101` | time_stop | 5 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/st_pullback_ma.md:102` | min_amount | 5,000 万元 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/st_pullback_ma.md:103` | min_list_days | 60 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/cards/st_pullback_ma.md:104` | slippage_bp | 10 | 未验证 | 估计 | estimate |
| `docs/strategies/cards/st_pullback_ma.md:110` | E2 多头排列均线 | MA5/10/20 | 未验证 | 策略阈值 |  |
| `docs/strategies/cards/st_pullback_ma.md:116` | E4 缩量基准 | 5 日均额 | 未验证 | 策略阈值 |  |
| `docs/strategies/cards/st_pullback_ma.md:124` | C1 单日跌幅 | < −5% | 未验证 | 策略阈值 |  |
| `docs/strategies/cards/st_pullback_ma.md:126` | C2 放量 | >20 日均额×1.5 | 未验证 | 策略阈值 |  |
| `docs/strategies/cards/st_pullback_ma.md:135` | X3 R 倍数 | 1R | 未验证 | 策略阈值 |  |
| `docs/strategies/cards/st_pullback_ma.md:137` | time_stop_days | 5 | 未验证 | 策略阈值 |  |
| `docs/strategies/cards/st_pullback_ma.md:138` | 维度看多/看空阈值 | 0.67 / 0.33 | 未验证 | 展示阈值 |  |
| `docs/strategies/cards/st_pullback_ma.md:139` | 有效期 | 1 交易日 | 未验证 | 展示 |  |
| `docs/strategies/cards/st_pullback_ma.md:145` | 历史回看 | 120 | 未验证 | 统计 |  |
| `docs/strategies/cards/st_pullback_ma.md:148` | min_n | 30 | 未验证 | 统计惯例 |  |
| `docs/strategies/cards/st_pullback_ma.md:150` | 触发率上限 | 0.30 | 未验证 | 统计 |  |
| `docs/strategies/cards/st_pullback_ma.md:151` | 触发率下限 | >0 | 未验证 | 统计 |  |

### S-01 v3（d10ebd8）

| 位置 | 参数 | 取值 | 状态 | 性质 | 依据 / 备注 |
|---|---|---|---|---|---|
| `d10ebd8:docs/strategies/cards/st_pullback_ma.md:125` | rs_pct | 0.8（0.6–0.95） | 未验证 | 策略阈值 | 草稿原值，用户决定恢复截面分位；非回测得出 |
| `d10ebd8:docs/strategies/cards/st_pullback_ma.md:31` | 截面样本数下限 N_min | 待定 | 未验证 | 统计 | 卡内写「参数待定（需裁定）」 |

### 做T 前期卡（补充）

| 位置 | 参数 | 取值 | 状态 | 性质 | 依据 / 备注 |
|---|---|---|---|---|---|
| `docs/strategies/catalog.md:105` | T-01 绝对偏离下限 | 1.2%（示例） | 未验证 | 策略阈值 | 示例值 |
| `docs/strategies/catalog.md:105` | T-01 触发时段 / 确认次数 | 09:45–14:30 / 2 次 | 未验证 | 策略阈值 |  |
| `docs/strategies/catalog.md:105` | VWAP 单位换算 | cje/(v×100) | 有出处 | 数据口径 | 内部实测 run-20261101-190106 GAP2 |
| `docs/strategies/catalog.md:112` | T-02 短窗涨速 | 3%（借 QMT） | 有出处 | 策略阈值 | 出处为他项目默认值（strategy-references.md:181），非实证 |
| `docs/strategies/T-R16/T-01_t_vwap_revert.md:26` | σ 预热 bar 数 | 30 | 未验证 | 策略阈值 | hypothesis |
| `docs/strategies/T-R16/T-01_t_vwap_revert.md:62` | k | 2.0（1.0–4.0） | 未验证 | 策略阈值 | 卡注「无外部来源」 |
| `docs/strategies/T-R16/T-01_t_vwap_revert.md:63` | revert_band | 0.5 | 未验证 | 策略阈值 |  |
| `docs/strategies/T-R16/T-01_t_vwap_revert.md:64` | stop_mult | 1.5 | 未验证 | 策略阈值 |  |
| `docs/strategies/T-R16/T-01_t_vwap_revert.md:65` | trend_abs_pct | 0.05 | 未验证 | 策略阈值 |  |
| `docs/strategies/T-R16/T-01_t_vwap_revert.md:66` | t_ratio | 0.3 | 未验证 | 策略阈值 |  |
| `docs/strategies/T-R16/T-01_t_vwap_revert.md:67` | max_t_per_day | 1 | 未验证 | 策略阈值 |  |
| `docs/strategies/T-R16/T-01_t_vwap_revert.md:68` | min_edge_cost_mult | 2.0 | 未验证 | 策略阈值 |  |
| `docs/strategies/T-R16/T-01_t_vwap_revert.md:69` | time_stop / last_entry | 14:50 / 14:30 | 未验证 | 策略阈值 |  |
| `docs/strategies/T-R16/T-02_t_spike_fade.md:62` | spike_k | 2.0 | 未验证 | 策略阈值 | 卡注「无外部来源」 |
| `docs/strategies/T-R16/T-02_t_spike_fade.md:63` | spike_min | 0.025 | 未验证 | 策略阈值 |  |
| `docs/strategies/T-R16/T-02_t_spike_fade.md:64` | revert_band | 0.5 | 未验证 | 策略阈值 |  |
| `docs/strategies/T-R16/T-02_t_spike_fade.md:65` | stop_add | 1.0 | 未验证 | 策略阈值 |  |
| `docs/strategies/T-R16/T-02_t_spike_fade.md:66` | invalid_dev | 0.05 | 未验证 | 策略阈值 |  |
| `docs/strategies/T-R16/T-02_t_spike_fade.md:67` | near_limit | 0.02 | 未验证 | 策略阈值 |  |
| `docs/strategies/T-R16/T-02_t_spike_fade.md:68` | t_ratio | 0.3 | 未验证 | 策略阈值 |  |
| `docs/strategies/T-R16/T-02_t_spike_fade.md:69` | max_t_per_day | 1 | 未验证 | 策略阈值 |  |
| `docs/strategies/T-R16/T-02_t_spike_fade.md:70` | slippage_bp | 10 | 未验证 | 估计 |  |
| `docs/strategies/T-R16/T-02_t_spike_fade.md:71` | time_stop | 14:50（待定） | 未验证 | 策略阈值 |  |

## 3 不计入的数值

- `362ad41:docs/contracts/intraday-bars.md:183`：测试用例「偏离 2.1%、量比 2.2」是夹具输入，不是参数，也不是回测。
- 卡片 `costs` 区与 C(7) 公式里重复出现的印花税、过户费、佣金，只在首次出现处计一次。
- 契约中的接口路径、表名、迁移编号等非数值约定不在清查范围。

## 4 制度参数出处

- 涨跌幅 20%、注册制新股上市前 5 日无涨跌幅、科创板 200 股：`docs/strategies/market_rules_check.md:26-33` 列出的官方规则原文（O1–O8）。
- 卖出印花税 0.05%：财政部 税务总局公告 2023 年第 39 号，自 2023-08-28 起减半征收，https://www.mof.gov.cn/jrttts/202308/t20230828_3904235.htm （减半前 1‰ 的原始文件本次未核对）。
- 过户费 0.001%（双向）：中国结算 2022-04-29 起下调，新华社报道 http://www.news.cn/2022-04/28/c_1128605983.htm 。
- 单笔最低佣金 5 元：证监发〔2002〕21 号，https://www.chinatax.gov.cn/chinatax/n810341/n810765/n812203/200202/c1209808/content.html （现行有效性已在 T-R58b 复核，见 §5）。

## 5 制度参数复核（T-R58b）

> 范围按编排者裁定 ④：只复核做T与 P2N 主线用到的 T+1、涨跌幅（主板 / 创业板 / 科创板 / ST）、最低佣金 5 元、印花税、过户费。其余制度参数（整手、单笔上限、新股无涨跌幅等）本次不复核，沿用 `market_rules_check.md` 与 `config/market_rules.yaml` 的既有核对。核对日 2026-11-11（北京时间）。

| # | 参数 | 我方取值（出现处） | 现行文件与条款 | 核对结论 | 状态 |
|---|---|---|---|---|---|
| R1 | T+1：当日买入的股票当日不得卖出 | `t_plus: 1`（`config/market_rules.yaml`）；T-01 卡 §17 | 《上海证券交易所交易规则（2026年修订）》（上证发〔2026〕41号，2026-07-06 起施行）第 3.1.4 条「投资者买入的证券，在交收前不得卖出，但实行回转交易的除外」，第 3.1.5 条列出的当日回转品种不含 A 股；《深圳证券交易所交易规则（2026年修订）》第 3.1.4、3.1.5 条同文。https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml ；https://docs.static.szse.cn/www/lawrules/rule/stock/W020260424690713155663.pdf | 一致（研究员读了两份规则正文原文） | 制度参数，有出处 |
| R2 | 主板涨跌幅 10% | `main_board: 10` | 沪 2026 规则第 3.3.13 条「涨跌幅限制比例为10%」；深 2026 规则第 3.3.13 条「主板股票的价格涨跌幅限制比例为 10%」（链接同 R1） | 一致 | 制度参数，有出处 |
| R3 | 创业板涨跌幅 20% | `chinext: 20`；H-01/W-01/S-01 卡 | 深 2026 规则第 3.3.13 条「创业板股票的价格涨跌幅限制比例为 20%」 | 一致 | 制度参数，有出处 |
| R4 | 科创板涨跌幅 20% | `star: 20`；H-01/W-01/S-01 卡 | 沪 2026 规则第 6.6 条「本所对科创板股票交易实行价格涨跌幅限制，涨跌幅限制比例为20%」 | 一致 | 制度参数，有出处 |
| R5 | 主板 ST/*ST 涨跌幅 | 2026-07-06 起 10%、此前 5%（`config/market_rules.yaml` 两段）；**T-R16 下 12 张前期卡（含 T-02:51、T-03:51、T-04:52）仍写「ST 5%」** | 沪 2026 规则起草说明（三）「将主板风险警示股票价格涨跌幅限制比例由5%调整为10%」；深交所 2026 规则发布通知（2026-07-06 施行）与修订说明同；https://www.szse.cn/www/lawrules/rule/stock/t20260424_620190.html | config 一致。前期卡的「ST 5%」**已过时**（只对 2026-07-05 及以前的数据成立）。创业板、科创板 ST 本就 20%，未变 | 制度参数，有出处（前期卡措辞待改，见下） |
| R6 | 卖出印花税 0.05%（仅出让方） | `stamp_duty_sell_pct: 0.05` | 《中华人民共和国印花税法》税目税率表：证券交易 成交金额的千分之一，对出让方征收 http://www.npc.gov.cn/npc/c2/c30834/202106/t20210610_311898.html ；财政部 税务总局公告 2023 年第 39 号，自 2023-08-28 起减半 https://www.gov.cn/zhengce/zhengceku/202308/content_6900443.htm 。未查到之后的调整文件 | 一致：1‰ × 1/2 = 0.5‰ = 0.05% | 制度参数，有出处 |
| R7 | 过户费 0.001%（双向） | `transfer_fee_pct: 0.001` | 中国结算《关于降低股票交易过户费收费标准的通知》（2022-04-28）：自 2022-04-29 起沪深 A 股按成交金额 0.01‰ 双向收取。官网原页本次未打开成功，用新华社 http://www.news.cn/2022-04/28/c_1128605983.htm 与香港交易所通告 CT/037/22 https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2022/CT03722B.pdf 两个独立转载交叉核对。未查到之后的调整公告 | 一致：0.01‰ = 0.001% | 制度参数，有出处（原发布页待补链） |
| R8 | 单笔最低佣金 5 元 | `commission_min_yuan: 5`（注释写「券商常见做法」）；卡片「最低 5 元」 | 证监发〔2002〕21 号第一条「A股、证券投资基金每笔交易佣金不足5元的，按5元收取」，同条规定佣金上限 3‰；证监会法规库标注「现行有效」https://neris.csrc.gov.cn/falvfagui/rdqsHeader/mainbody?navbarId=3&secFutrsLawId=b25a17fb262742f2aea99515380cf3bb ；正文 https://www.chinatax.gov.cn/chinatax/n810341/n810765/n812203/200202/c1209808/content.html | 文件现行有效。但第六条规定**各券商自定佣金收取标准**，实际费率由券商定；市场上有宣传「免五」的券商（财联社 2025-09-30 报道，未见监管新文件）。所以「5 元」是有出处的默认值，用户实际收费可能不同 | 制度参数，有出处；**费率与最低额作为用户可配置参数**（默认费率无统一文件，`commission_rate_default_pct: null` 合理） |

要点：

1. 8 条全部找到现行原文或现行有效的文件，数值与 `config/market_rules.yaml` 一致，没有需要改的值。
2. 复测须按成交日期取 `market_rules` 的对应段：通达信导出样本很可能跨过 2026-07-06，跨过时主板 ST 的涨跌停价前后不同（5% → 10%）。
3. 佣金：复测与产品都按用户填写的费率与最低额计算；用户未填时，研究侧用最低额 5 元（证监发〔2002〕21 号）和两档费率做敏感性（见 `retest_plan.md` §6），不把某一档费率写成默认。
4. 需要别人改的地方（研究员不改）：① `config/market_rules.yaml` 中 `commission_min_yuan` 的注释「券商常见做法」可改为「证监发〔2002〕21 号，现行有效；实收以券商为准」——归架构师；② `docs/strategies/T-R16/` 下 12 张前期卡的「ST 5%」应改为「主板 ST 按 market_rules 分段（2026-07-06 起 10%）」——这批是仅知识卡，是否修订由编排者定。
