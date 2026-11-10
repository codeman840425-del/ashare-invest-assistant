# T-R58 做T提醒阈值：前期调研回顾与外部项目对照表

> 范围：只回答「VWAP 偏离 2%、量比 2 倍」这类日内阈值有没有出处，以及别的项目怎么设。复测方案见同目录 `retest_plan.md`（T-R58b）。
> 用语：本文中的阈值只作「候选信号 / 计划条件」的讨论，不构成选股或收益承诺。
> 标签：**实证** = 出处给出了样本检验结果；**惯例** = 出处只给默认值或公式，没有检验；**未查到** = 出处里没有这一项；**仅见摘要** = 只读到二手转述或摘要页。
> 核对列：**Codex 初筛→已核对** = 该行先由 Codex L2 从公开仓库源码抽取，再由研究员按提交逐行核对（§3.5）；**DeepSeek 初筛→已核对** = 该行先由 DeepSeek 从公开摘录中抽取（未核实草稿，存于 `team/reports/deepseek/T-R58/`），再由研究员回到原始出处 WebFetch 逐项核对；**人工直查** = 研究员直接读原始出处，未经 DeepSeek。

## 1 结论先行

1. 「|dev_pct| ≥ 2%」「量比 ≥ 2」两个数，在本次检索到的公开资料里**都没有实证出处**。见到的同类数值只有：Q-Code「较日内 VWAP 回落 1.5%」（页面自标「待验证」）、海通「集合竞价量比阈值 4」（另一个量，样本内 2015.1–2019.5）。两者都不能支撑 2% / 2 倍。
2. 我们自己的前期调研**早就提出过按波动归一化的阈值**：`catalog.md:105` 写的是 `|dev_t| ≥ k×σ_t` 且 `|dev_t| ≥ 1.2%`（示例），`T-R16/T-01_t_vwap_revert.md:62` 的 k 默认 2.0（1.0–4.0）。T-A143 契约（362ad41）定 2% / 2 倍时没有引用这些内容，也没有说明为什么不用。
3. 量比**窗口 N=5 有出处**（聚宽 jqdatasdk `LB` 的 N=5、天软 FAQ、同花顺 SuperMind 文章都是过去 5 个交易日、每日 240 分钟），属于**惯例**；但**阈值 2 没有出处**。
4. T-A143 的量比口径（`362ad41:docs/contracts/intraday-bars.md:90`：除以过去 5 日**同一时刻累计量**的均值）与上述惯例口径（今日每分钟均量 ÷ 过去 5 日每分钟均量）**不同**。同一时刻口径能避开日内 U 形量能分布，但不是行业常用的「量比」，两种口径下的同一个阈值不可互换。**编排者已裁定（T-R58b）：只用惯例口径，同一时刻口径废弃**（见 §5）。
5. 外部开源项目（vnpy、qlib、backtrader、TSP、bondTrader）**都没有给 VWAP 偏离或量比的默认交易阈值**；它们只提供指标定义或无阈值的穿越信号。
6. 按波动归一化有学术先例：Zarattini 等（SPY，14 日噪声边界 + VWAP 跟踪止损，**样本内**）；A 股有日内动量/反转的文献（Chu 等 2019；Gao 等 2018 为美股市场层面）。这些只说明「归一化」方向有依据，**不提供 A 股做T的具体阈值**。
7. 本仓「有回测」的参数为 0（见 `param_audit.md`）。在复测完成前，维持「只显示指标、不发信号」的保守默认（契约 Q5 的保守选项，`362ad41:docs/contracts/intraday-bars.md:222`）。

## 2 前期调研回顾（本仓内，path:line）

| # | 位置 | 内容摘要 | 与本题关系 |
|---|---|---|---|
| P1 | `docs/strategy-references.md:46` | TSP（tick-stock-panel，MIT）指标流水线含量比 | 量比口径来源之一 |
| P2 | `docs/strategy-references.md:48` | TSP 自定义信号 `{field, op, threshold}`，条件只能 AND | 阈值由用户配置，无默认 |
| P3 | `docs/strategy-references.md:180-181` | QMT-QuantLimit：最新价 ≥ 涨停价、时间 ≤ 10:00、25 笔涨幅/昨收 ≥ 3% | 打板阈值，不是做T阈值 |
| P4 | `docs/strategy-references.md:193-204` | bondTrader `trigger.json`：窗口涨幅 + 换手 + 秒均成交额三阈值 + 最长持仓 | 只给配置值，无理由（见 §3 B 行） |
| P5 | `docs/strategy-references.md:310` | G1：日内做T策略须有回补/时间止损 | 规则完整性要求 |
| P6 | `docs/strategy-references.md:394` | 盘中建议按下一根 1 分钟 bar 开盘价入场 | 复测成交假设 |
| P7 | `docs/strategy-references.md:407-408` | T-01/T-02 思路来源：TSP 分时穿越均价、bondTrader、QMT 短窗涨速 | 做T候选的出处链 |
| P8 | `docs/plan.md:26` | Tier-1 1,500 只每分钟取 1 分钟 K，Tier-2 每 5 分钟 | 数据频率前提 |
| P9 | `docs/plan.md:95` | 09:15–09:25 集合竞价：麦蕊无盘中竞价数据 | 海通竞价量比无法复用 |
| P10 | `docs/plan.md:121` | 量比等由日 K（盘后）+ 当日 1 分钟 K 增量计算 | 量比口径的原始设计 |
| P11 | `docs/plan.md:1619` | 冲击成本分档，标「编排者默认，初值待校准」 | 成本参数未验证 |
| P12 | `docs/strategies/catalog.md:105` | T-01：VWAP 公式与单位实测（`vwap = cje/(v×100)`）；`σ_t` = 当日已完成 1 分钟收益标准差 × sqrt(已完成 bar 数)；触发 `|dev_t| ≥ k×σ_t` 且 `≥ 1.2%`（示例），09:45–14:30，连续 2 次确认 | **前期已提出波动归一化** |
| P13 | `docs/strategies/catalog.md:112` | T-02：N 分钟涨速 ≥ x%（借 QMT「短窗涨速 ≥ 3%」） | 阈值为占位 |
| P14 | `docs/strategies/catalog.md:118` | T-03：跳空超过 k×ATR% | 同为波动归一化 |
| P15 | `docs/strategies/T-R16/T-01_t_vwap_revert.md:5` | 初稿来自 DeepSeek，研究员复核；标「仅知识卡」 | 阈值全部 hypothesis |
| P16 | `docs/strategies/T-R16/T-01_t_vwap_revert.md:26` | σ 预热：至少 30 根 1 分钟 bar（hypothesis） | 复测须同口径 |
| P17 | `docs/strategies/T-R16/T-01_t_vwap_revert.md:62-69` | k 2.0、revert_band 0.5、stop_mult 1.5、trend_abs_pct 0.05、t_ratio 0.3、max_t_per_day 1、min_edge_cost_mult 2.0、14:50/14:30 | 前期参数表 |
| P18 | `docs/strategies/T-R16/T-02_t_spike_fade.md:4` | 「来源：通用规则组合，无外部来源。阈值均为 hypothesis」 | 前期已自认无出处 |
| P19 | `docs/strategies/T-R16/T-02_t_spike_fade.md:62-71` | spike_k 2.0、spike_min 0.025、revert_band 0.5、stop_add 1.0、invalid_dev 0.05、near_limit 0.02、t_ratio 0.3、max_t_per_day 1、slippage_bp 10、14:50 | 前期参数表 |
| P20 | `docs/handover/team/reports/T003-mairui-capability.md:34` | 网络源单股快照含字段 `lb(量比)` | 数据源自带量比，口径未核对 |

小结：前期调研对 VWAP 偏离用的是「k×σ + 绝对下限（示例 1.2%）」的写法，并已承认无外部来源、全部为 hypothesis；对量比没有给阈值。2% / 2 倍不来自前期调研。

## 3 外部对照表

列：项目｜参数名｜默认值｜设置理由（照原文）｜来源 URL｜标签｜核对方式。代码仓库的 URL 均为原始文件，行号按下列提交核对（2026-11-11 北京时间读取）：jqdatasdk `ba61143`、qlib `5435523`、vnpy `c6e231c`、vnpy_algotrading `bee959d`、backtrader `b853d7c`、bondTrader `ab3be3d`、tick-stock-panel `487eab5`。

### 3.1 量比

| 项目 | 参数名 | 默认值 | 设置理由 | 来源 URL | 标签 | 核对 |
|---|---|---|---|---|---|---|
| 聚宽 jqdatasdk `LB` | N（过去交易日数） | 5 | 未查到（docstring 只给公式：开市后平均每分钟成交量 ÷ 过去 N 日平均每分钟成交量） | https://raw.githubusercontent.com/JoinQuant/jqdatasdk/master/jqdatasdk/technical_analysis.py （:2677） | 惯例 | DeepSeek 初筛→已核对 |
| 聚宽 jqdatasdk `DBLB` 对比量比 | N / M | 5 / 5 | 未查到 | 同上（:1343） | 惯例 | DeepSeek 初筛→已核对 |
| 聚宽 jqdatasdk `VR` 成交量变异率 | N / M | 26 / 6 | 未查到 | 同上（:1111） | 惯例 | DeepSeek 初筛→已核对 |
| 聚宽 jqdatasdk `SG_LB` | — | 无参数 | 该函数的「量比」= 个股成交量 ÷ 大盘成交量 × 1000，与 `LB` 同名不同义 | 同上（:2353） | 惯例 | 人工直查（DeepSeek 未涉及） |
| 同花顺 SuperMind 文章「计算实时量比」 | 过去交易日数 / 每日分钟数 | 5 / 240 | 未查到（只给公式与示例代码 `60*4*days`） | https://quant.10jqka.com.cn/view/article/13YTJ9KAEX99066TU0NQZQ598 （2023-10-30 用户文章） | 惯例 | DeepSeek 初筛→已核对 |
| 天软 FAQ id=17249 | 过去交易日数 / 每日分钟数 | 5 / 240（集合竞价算在第一分钟） | 未查到 | http://tinysoft.com/TSDN/HelpDoc/display.tsl?id=17249 | 惯例 | DeepSeek 初筛→已核对 |
| tick-stock-panel `vol_ratio_5d` | 回看天数 / 盘中折算 | 5（不含当天）/ ×240/已交易分钟 | 注释写「标准量比(同花顺/东财)」 | https://raw.githubusercontent.com/shy3130/tick-stock-panel/main/backend/app/indicators/pipeline.py （:445-446、:519、:2216） | 惯例 | DeepSeek 初筛→已核对（DeepSeek 输出的 URL 被截断，已补全） |
| tick-stock-panel 分时 `vol_ratio_Nm_today` | N（bar） | 1 / 3 / 5 | 未查到（定义为当前 N 根量和 ÷ 此前 N 根量和，不跨午休） | https://raw.githubusercontent.com/shy3130/tick-stock-panel/main/backend/app/strategy/intraday_features.py （:38） | 惯例 | DeepSeek 初筛→已核对 |
| qlib `HighFreqHandler` 成交量归一 | 均值窗口 | 7200 根 1 分钟 bar（`HighFreqGeneralHandler` 写作 day_length×30，即 30 日） | 未查到 | https://raw.githubusercontent.com/microsoft/qlib/main/qlib/contrib/data/highfreq_handler.py （:83、:179） | 惯例 | DeepSeek 初筛→已核对 |
| 海通量化「海量」专题 131（新浪转载） | 集合竞价量比 = 240 × 竞价成交额 ÷ 过去 5 日日均成交额；T+0 阈值 | 4 | 原文为「不低于一定阈值（4）」；参数敏感性：T+0 量比阈值 3–5、开盘涨幅阈值 −1%–1% 时「整体表现较好」；T+1 量比 2–5 | https://finance.sina.cn/2019-07-17/detail-ihytcitm2536959.d.html | 实证（样本内 2015.1–2019.5；因子 rank IC 均值 0.01）。**另一个量**（开盘前竞价，非盘中），且我方无盘中竞价数据（`docs/plan.md:95`） | DeepSeek 初筛→已核对（DeepSeek 把三个区间的理由填成「未查到」，已按原文敏感性结论更正） |
| vnpy `ArrayManager` | 量比 | 未查到 | — | https://raw.githubusercontent.com/vnpy/vnpy/master/vnpy/trader/utility.py | 未查到 | DeepSeek 初筛→已核对 |
| backtrader indicators | 量比 | 未查到 | — | https://api.github.com/repos/mementum/backtrader/contents/backtrader/indicators | 未查到 | DeepSeek 初筛→已核对 |
| backtrader 示例 `RelativeVolume`（samples，非库内指标） | period / volisnan | 20 / True | 未查到；计算式为 `volume(-period) / volume`，即 20 根前的量 ÷ 当前量（方向与量比相反） | https://github.com/mementum/backtrader/blob/b853d7c90b6721476eb5a5ea3135224e33db1f14/samples/data-filler/relativevolume.py#L34-L35 | 惯例（示例代码） | Codex 初筛→已核对 |
| backtrader 示例 `RelativeVolumeByBar` | prestart / start / end | 08:00 / 09:10 / 17:15 | 未查到；当前 bar 量 ÷ **上一交易日同一时刻 bar 量**（单 bar、只回看 1 日，不是累计量） | https://github.com/mementum/backtrader/blob/b853d7c90b6721476eb5a5ea3135224e33db1f14/samples/relative-volume/relvolbybar.py#L37-L39 | 惯例（示例代码） | Codex 初筛→已核对 |
| qlib `RandomOrderStrategy` | volume_ratio | 0.01 | 随机订单量占成交量的比例，**不是量比** | https://github.com/microsoft/qlib/blob/54355232463878d2eebb91fe0ee5fa7fa1f5976c/qlib/contrib/strategy/rule_strategy.py#L544 | 惯例（与本题无关，列出以免误读） | Codex 初筛→已核对（Codex 归为「成交量比率」，已更正） |
| 米筐 RQData | 量比 | 未查到 | — | https://www.ricequant.com/doc/rqdata/python/generic-api | 未查到 | DeepSeek 初筛→已核对 |
| **我方 T-A143** | 量比阈值 | 2 | 未写理由，标「待复测」 | `362ad41:docs/contracts/intraday-bars.md:91`、`:222` | 未查到出处 | 人工直查 |

### 3.2 VWAP 与 VWAP 偏离

| 项目 | 参数名 | 默认值 | 设置理由 | 来源 URL | 标签 | 核对 |
|---|---|---|---|---|---|---|
| vnpy `ArrayManager` | size（序列长度） | 100 | 未查到；文件内无 VWAP 方法 | https://raw.githubusercontent.com/vnpy/vnpy/master/vnpy/trader/utility.py （:511） | 惯例 | DeepSeek 初筛→已核对 |
| vnpy_algotrading | VWAP 算法 | 未查到（algos 目录只有 best_limit、iceberg、sniper、stop、twap） | — | https://github.com/vnpy/vnpy_algotrading/tree/main/vnpy_algotrading/algos | 未查到 | DeepSeek 初筛→已核对 |
| vnpy_algotrading `TwapAlgo` | time / interval | 600 / 60（秒） | 未查到 | https://raw.githubusercontent.com/vnpy/vnpy_algotrading/main/vnpy_algotrading/algos/twap_algo.py （:16-17） | 惯例（执行算法，非信号） | DeepSeek 初筛→已核对 |
| qlib Alpha158 | VWAP0 = $vwap/$close；rolling 窗口 | 5/10/20/30/60 | 未查到；文件内无交易阈值 | https://raw.githubusercontent.com/microsoft/qlib/main/qlib/contrib/data/loader.py （:78、:139） | 惯例（因子定义） | DeepSeek 初筛→已核对 |
| qlib Alpha158 | volume 原始窗口 | 0–4 | **默认配置不含 volume 项**；0–4 只是 docstring 示例与 `range(5)` 回退值 | 同上（:134-135） | 惯例 | DeepSeek 初筛→已核对（DeepSeek 写成默认 0–4，已更正） |
| backtrader indicators | VWAP | 未查到（目录无 vwap 文件） | — | https://api.github.com/repos/mementum/backtrader/contents/backtrader/indicators | 未查到 | DeepSeek 初筛→已核对 |
| 聚宽 jqdatasdk | VWAP 函数 | 未查到 | — | jqdatasdk technical_analysis.py（同上） | 未查到 | DeepSeek 初筛→已核对 |
| 米筐 RQData | `get_vwap` | 有函数；偏离交易阈值未查到 | — | https://www.ricequant.com/doc/rqdata/python/generic-api | 惯例 | 人工直查 |
| tick-stock-panel 分时信号 | 价格上穿/下穿均价；min_bars | 2 | 「旧实现要求至少两根已完成 bar 才判穿越」；无偏离百分比阈值 | https://raw.githubusercontent.com/shy3130/tick-stock-panel/main/backend/app/strategy/intraday_signals.py （:31） | 惯例 | DeepSeek 初筛→已核对 |
| tick-stock-panel VWAP 单位 | vwap = 累计成交额 ÷ (累计成交量×100) | — | 成交量单位为手 | intraday_features.py（:106） | 惯例（与我方 `catalog.md:105` 实测一致） | 人工直查 |
| Q-Code「底仓 T0 配对」 | 现价较日内 VWAP 回落 q | 1.5% | 未查到；页面自标「验证状态：待验证」「不提供任何未实测的收益或回撤数字」 | https://q-code.com.cn/market/strategy/intraday-t0-paired-trade/ （更新 2026-09-25） | 惯例 | DeepSeek 初筛→已核对 |
| 同上 | 当日买入次数上限 | 2 次 | 未查到 | 同上 | 惯例 | DeepSeek 初筛→已核对 |
| 同上 | 回升 r（或回归 VWAP） | 1.5% | 未查到 | 同上 | 惯例 | DeepSeek 初筛→已核对（DeepSeek 漏了「或回归 VWAP」，已补） |
| 同上 | 收盘前未配对处理时点 | 收盘前 5 分钟，未配对部分默认保留为净加仓 | 未查到 | 同上 | 惯例 | DeepSeek 初筛→已核对（DeepSeek 写成「保留时间 5 分钟」，语义不对，已更正） |
| 同上 | 单日配对股数上限 p | 底仓 20% | 未查到 | 同上 | 惯例 | DeepSeek 初筛→已核对 |
| Zarattini, Aziz, Barbon 2024（CXO Advisory 摘要） | 噪声边界回看 | 14 个交易日 | 边界内视为供需平衡（无趋势） | https://www.cxoadvisory.com/momentum-investing/complex-intraday-time-series-momentum-strategy-applied-to-spy/ ；原文 SSRN 4824172 | 实证（SPY 2007-05–2024-04，**样本内**）；仅见摘要 | DeepSeek 初筛→已核对 |
| 同上 | 检查时点 | 每个整点与半点（HH:00 / HH:30） | 未查到 | 同上 | 仅见摘要 | 人工直查（DeepSeek 漏抽） |
| 同上 | 波动目标 / 最大杠杆 | 日波动 2% / 4 倍 | 未查到 | 同上 | 仅见摘要 | DeepSeek 初筛→已核对 |
| 同上 | 跟踪止损 | 噪声边界与日内 VWAP 取较紧者 | 未查到 | 同上 | 仅见摘要 | 人工直查 |
| 同上 | 佣金 / 滑点 | 每股 0.0035 / 0.001 美元 | 原文「假设」 | 同上 | 仅见摘要 | DeepSeek 初筛→已核对 |
| bondTrader `trigger.json` | holdCnt 3、amt 2000、vol 0、bUpper 0.02、bWait 3、atSale 0.3、holdSec 6、high 1、low 0.4、sec 10、raRate 0.125、tnRate 0.005、stockAmt 20、bondAmt 2 | 同左 | 未查到；只有注释「低自盈,短持仓,低触发」；**原文无单位**；仓库未见 LICENSE | https://raw.githubusercontent.com/freevolunteer/bondTrader/main/data/trigger.json | 惯例（可转债，非股票） | DeepSeek 初筛→已核对（14 项逐项一致） |
| **我方 T-A143** | \|dev_pct\| 阈值 | 2% | 未写理由，标「待复测」 | `362ad41:docs/contracts/intraday-bars.md:91`、`:222` | 未查到出处 | 人工直查 |
| **我方 catalog / T-01** | k×σ 与绝对下限 | k=2.0；1.2%（示例） | hypothesis；「无外部来源」 | `docs/strategies/catalog.md:105`、`docs/strategies/T-R16/T-01_t_vwap_revert.md:62` | 未查到出处 | 人工直查 |

### 3.5 Codex L2 源码默认值核对（T-R58b）

- 模型与档位：L2 `gpt-6.1-sol`，`model_reasoning_effort=medium`，`codex exec -s read-only`，不联网；输入为公开仓库浅克隆（vnpy `c6e231c`、vnpy_ctastrategy `7a8768d`、vnpy_algotrading `bee959d`、qlib `5435523`、backtrader `b853d7c`），不含本仓契约、样本或私有数据。约 77k tokens。原始输出：`team/reports/codex/T-R58/l2_output.md`（未经核对的草稿）。
- 核对方法：脚本逐行打开 Codex 给出的「仓库/路径/行号」，检查该行是否含所列默认值；再人工读上下文核语义。
- 结果：Codex 共给 **106 行**。行号与默认值对不上、属编造：**0 行**。需更正语义：**1 行**（qlib `RandomOrderStrategy.volume_ratio=0.01` 是随机订单量比例，不是量比）。需加注：**2 行**（backtrader `RelativeVolume` 是「过去量 ÷ 当前量」，方向与量比相反；`StandardDeviation.safepow` 文档字符串写 default False、代码 :51 实为 True，源码自身不一致，Codex 两处都照实列出）。漏抽：**1 处**（vnpy_algotrading `TwapAlgo` time 600 / interval 60，Codex 写「未找到」，第一部分已人工列入 §3.2）。
- Codex 未发现任何 VWAP 偏离或量比的**交易阈值**默认值，与 §1 第 5 条一致。
- 与本题相关、已核对的波动倍数默认值（只说明各项目倍数各不相同、均无检验，**不用于定 k**）：

| 项目 | 参数 | 默认值 | 位置 | 标签 | 核对 |
|---|---|---|---|---|---|
| vnpy `ArrayManager.std` | nbdev | 1 | https://github.com/vnpy/vnpy/blob/c6e231caf32b7fc97e6459817fff66458cf7e7c4/vnpy/trader/utility.py#L809 | 惯例 | Codex 初筛→已核对 |
| vnpy `ArrayManager.boll` / `keltner` | dev | 无默认（必填） | https://github.com/vnpy/vnpy/blob/c6e231caf32b7fc97e6459817fff66458cf7e7c4/vnpy/trader/utility.py#L1050-L1053 | 惯例 | Codex 初筛→已核对 |
| backtrader `BollingerBands` | period / devfactor | 20 / 2.0 | https://github.com/mementum/backtrader/blob/b853d7c90b6721476eb5a5ea3135224e33db1f14/backtrader/indicators/bollinger.py#L43 | 惯例 | Codex 初筛→已核对 |
| backtrader `AverageTrueRange` | period | 14 | https://github.com/mementum/backtrader/blob/b853d7c90b6721476eb5a5ea3135224e33db1f14/backtrader/indicators/atr.py#L113 | 惯例 | Codex 初筛→已核对 |
| backtrader `StandardDeviation` | period / safepow | 20 / True | https://github.com/mementum/backtrader/blob/b853d7c90b6721476eb5a5ea3135224e33db1f14/backtrader/indicators/deviation.py#L51 | 惯例 | Codex 初筛→已核对 |
| vnpy_ctastrategy 示例 `BollChannelStrategy` | boll_window / boll_dev / atr_window / sl_multiplier | 18 / 3.4 / 30 / 5.2 | https://github.com/vnpy/vnpy_ctastrategy/blob/7a8768de9784dda35a7b261a7ade1dbfbff50919/vnpy_ctastrategy/strategies/boll_channel_strategy.py#L20-L24 | 惯例（期货示例策略） | Codex 初筛→已核对 |
| vnpy_ctastrategy 示例 `KingKeltnerStrategy` | kk_length / kk_dev | 11 / 1.6 | https://github.com/vnpy/vnpy_ctastrategy/blob/7a8768de9784dda35a7b261a7ade1dbfbff50919/vnpy_ctastrategy/strategies/king_keltner_strategy.py#L20-L21 | 惯例（期货示例策略） | Codex 初筛→已核对 |
| vnpy `BarGenerator` | window / interval | 0 / `Interval.MINUTE` | https://github.com/vnpy/vnpy/blob/c6e231caf32b7fc97e6459817fff66458cf7e7c4/vnpy/trader/utility.py#L186-L188 | 惯例（分钟合成） | Codex 初筛→已核对 |
| qlib `HighFreqGeneralHandler` | day_length | 240 | https://github.com/microsoft/qlib/blob/54355232463878d2eebb91fe0ee5fa7fa1f5976c/qlib/contrib/data/highfreq_handler.py#L114 | 惯例（与量比 240 分钟/日一致） | Codex 初筛→已核对 |
| qlib 高频示例 `simpson_vwap` | 近似式 | (open+2high+2low+close)/6 | https://github.com/microsoft/qlib/blob/54355232463878d2eebb91fe0ee5fa7fa1f5976c/examples/highfreq/highfreq_handler.py#L46 | 惯例（无成交额时的近似；我方有成交额，不用） | Codex 初筛→已核对 |

### 3.3 学术与券商研报（只用于「方向」，不提供 A 股做T阈值）

| 出处 | 要点 | 标签 | 核对 |
|---|---|---|---|
| Zarattini, Aziz & Barbon (2024) SSRN 4824172 / SFI 24-97 | 日内动量用按近 14 日波动缩放的噪声边界；VWAP 用作跟踪止损 | 实证（样本内） | 人工直查（Concretum、CXO 页面） |
| Gao, Han, Li & Zhou (2018) JFE 129(2):394-414, DOI 10.1016/j.jfineco.2018.05.009 | 美股市场层面：首半小时收益预测末半小时收益 | 实证 | 人工直查（crossref） |
| Chu, Gu & Zhou (2019) FRL 30:83-88, DOI 10.1016/j.frl.2019.04.002 | 中国股市日内动量 | 实证（仅见摘要） | 人工直查（crossref） |
| 华宝证券（2023-07-02）T0 环境研究 | 日内振幅、换手、波动越高，T0 环境越好；**未给阈值** | 实证（仅见摘要/正文要点） | 人工直查 |
| 东北证券（2023-11-29）日内成交量分布因子 | 日内成交量呈 U 形；**未给做T阈值** | 实证 | 人工直查 |
| Bailey & López de Prado (2014) JPM 40(5):94-107, DOI 10.3905/jpm.2014.40.5.094；White (2000) Econometrica 68:1097-1126, DOI 10.1111/1468-0262.00152；Hansen (2005) JBES 23(4):365-380, DOI 10.1198/073500105000000063 | 多参数网格搜索后需做多重检验校正（DSR / Reality Check / SPA），留给复测方案使用 | 方法 | 人工直查（crossref） |

### 3.4 原文明确没有的项目（DeepSeek 第 2 批列出，研究员逐条核对一致）

- vnpy `ArrayManager`：无 VWAP、无量比方法。
- vnpy_algotrading：algos 目录无 VWAP 算法文件。
- qlib Alpha158 loader：无交易阈值，无量比定义。
- backtrader indicators：无 VWAP、无量比文件（`samples/` 下有两个相对成交量示例，见 §3.1 Codex 行）。
- jqdatasdk：无 VWAP 函数；`LB`、`DBLB` 未给信号阈值。
- 米筐 RQData：未查到量比函数，未查到 VWAP 偏离阈值。

## 4 DeepSeek 初筛记录与核对统计

- 调用 2 次（另有 2 次 `--check-only` 本地检查，不发送），共 6,621 tokens（第 1 批 4,779，第 2 批 1,842）。输入只含带来源 URL 的公开资料文字摘录，不含源码行、内部契约或私有数据。产出：`team/reports/deepseek/T-R58/draft_batch1.md`、`draft_batch2.md`（含 meta）。
- 第 1 批输出触到 2,000 completion tokens 上限，最后一行 URL 被截断、「原文明确没有的项目」一节缺失；第 2 批只补 bondTrader 参数与该节。
- DeepSeek 共给出 59 条（第 1 批参数 39 行；第 2 批参数 14 行 + 「明确没有」6 条）。逐条回原始出处核对：
  - 与原文不符、属编造：**0 条**；
  - 需要更正：**6 条**——qlib volume 窗口「默认 0–4」（默认配置并无此项）；Q-Code「保留时间 5 分钟」（应为收盘前 5 分钟时点）；海通三个敏感性区间的理由（原文有敏感性结论，被填成「未查到」）；tick-stock-panel URL 截断；
  - 漏抽：**3 处**——Zarattini 的 HH:00/HH:30 检查时点、海通 T+1 开盘涨幅区间 −1%–1%、Q-Code「或回归 VWAP」；另有聚宽 `SG_LB`（不在输入摘录中）由人工补入。
- 结论：DeepSeek 抽取的数值全部能在原文找到，错误集中在「理由」与「语义」两列；表中所有 DeepSeek 行均以研究员核对后的内容为准。

## 5 裁定结果（编排者，T-R58b）

1. 契约 362ad41 残留的 2% / 2 倍：由架构师在 T-A146 删除，本文件不改契约。
2. 量比口径：只用行业惯例口径（回看 5 日、每天 240 分钟）。T-A143 的「同一时刻累计量」口径**已裁定废弃**，复测不再作对照。量比阈值仍为「待复测」。
3. 偏离阈值形式：候选为 `k×σ_t` 加绝对下限（`catalog.md:105`、T-01 卡）；固定百分比只作对照组。k 与下限由复测定，复测前不生效。
4. 制度参数：只复核做T与 P2N 主线用到的几条，结果见 `param_audit.md` §5。

复测方案见 `retest_plan.md`。
