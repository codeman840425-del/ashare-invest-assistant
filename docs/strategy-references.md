# 开源 A 股量化项目调研与策略库借鉴（T002）

> 作者：架构师 · 2026-11-01（丹佛时间 MST）
> 范围：9 个开源项目。实际查看了 README、LICENSE 文件和策略相关源码（克隆到 `/tmp/t002/`，没有放进本仓库）。Star 数和最近推送时间来自 GitHub API（2026-11-01 查询；推送时间已换算成丹佛时间）。
> 原则：只写已核实的内容，不清楚的标【待核实】。**本文件不改 plan.md**，需要合并进 plan.md 的改动列在第 4 节。
> 关联：`/workspace/team/vision.md`（含 11:51 用户定的"三层策略库"方向）、`docs/plan.md` §2.5（策略库与建议引擎现稿）。

---

## 0. 结论速览

| 项目 | 许可证（以 LICENSE 文件为准） | 闭源商业 SaaS 能否复用代码 | ★ / 最近推送 | 最值得借鉴的一点 |
|---|---|---|---|---|
| tick-stock-panel (TSP) | MIT | 可以，需保留版权声明 | 6774 / 2026-11-01 | 统一指标口径：派生列只算一次，策略、监控、模拟盘按同一组列名取值；自定义信号是"字段白名单 + 固定运算符"JSON |
| KHunter | MIT（附派生声明：源自 a-share-quant-selector，再分发须保留） | 可以，需保留两份声明 | 670 / 2026-10-07 | BaseStrategy + StrategyRegistry + 带类型/范围的参数 YAML；五维评分里每个维度带"一票否决 + 原因" |
| a-share-quant-selector | MIT | 可以，需保留声明 | 502 / 2026-09-07 | 最小可用的"基类 + 注册表 + 参数 YAML"骨架；结果按形态分类（回落碗中/靠近多空线…） |
| OSkhQuant | **CC BY-NC 4.0**（明确禁止商业目的） | **不可以** | 1621 / 2026-10-19 | 只借思想：每个信号带 `reason`；触发周期抽象（tick/1m/5m/1d）；A 股成本与整手规则 |
| QuantMind | **AGPL-3.0** | **不可以**（网络提供服务也要开源） | 1847 / 2026-10-31 | 只借思想：模板 = `.py` + `.json` 参数清单（含 min/max/说明）；基本面过滤命名 `f_{字段}_{min/max/not/in}`；AI 代码要过 AST 白名单 + 子进程隔离 |
| CTBZStock | MIT | 可以，需保留声明 | 232 / 2026-07-21 | 可交易性过滤清单（ST、上市不满 30 天、退市整理期、开盘涨跌停不可买、低价股）；成交相对开盘价的滑点统计 |
| QMT-QuantLimit | Apache-2.0 | 可以（保留 LICENSE/NOTICE，改动要标注）；但关键选股代码只有 `.pyc`，没有源码 | 222 / 2025-01-15 | 打板触发 = "到涨停价 + 时间窗（≤10:00）+ 短窗口涨幅 ≥3%"，逐笔数据环形缓存 |
| bondTrader | **无 LICENSE 文件**（README："仅供学习交流使用"） | **不可以**（默认保留所有权利） | 319 / 2024-05-21 | 行情中心 / 策略触发器 / 交易维护器三进程解耦；策略 = JSON 参数数组，可按编号单独启停 |
| AlphaGPT_Tushare | **无 LICENSE 文件**；README 写了"MIT License"，但 GitHub 识别为无许可证 | **视为不可以**【待核实，需作者补 LICENSE】 | 184 / 2026-01-25 | LLM 只能在"给定特征 + 给定算子"内生成表达式；用相关系数 > 0.9 去重 |

**总体判断**
- 9 个项目都以**回测/实盘下单**为中心，没有一个是"多用户、证据化建议、不回测"的形态。所以我们**借思想和接口形状，自己实现**。
- 可以合法复用代码的只有 MIT/Apache 的 4 个项目：TSP、KHunter、a-share-quant-selector、CTBZStock；QMT-QuantLimit 是 Apache，但核心代码只有 `.pyc`。
- **建议不直接拷贝任何代码**，原因有三：①数据源都不同（TickFlow/akshare/tushare/掘金/QMT/jvQuant，我们用麦蕊）；②存储形态不同（本地 Parquet/YAML，我们用 PostgreSQL 多用户）；③这样可以避免许可证混用。如果将来拷了 MIT 片段，要在仓库 `THIRD_PARTY_NOTICES.md` 里登记。

---

## 1. 逐项目调研

### 1.1 tick-stock-panel（TSP）
- **仓库**：https://github.com/shy3130/tick-stock-panel
- **许可证**：MIT（LICENSE："Copyright (c) 2026 tick-stock-panel contributors"）。可以闭源商用，保留版权与许可声明即可。
- **热度**：6774★ / 1623 fork；最近推送 2026-11-01 09:31（丹佛时间）。非 fork。
- **定位**：自托管、零运维的 A 股"自建策略 + 监控 + 回测"工作台。README 声明"不作为投资软件"，不做 AI 荐股。
  - 技术栈：Polars + FastAPI 风格后端 + React 18，单个 Docker 容器，数据存本地 Parquet。
  - 数据源：TickFlow SDK / fuyao / TdxQuant，并支持插件数据源。插件按"能力路由矩阵"决定哪个能力走哪个源，找不到可用源就直接报错（fail-closed）。
- **策略库怎么搭的（已读源码）**

  | 方面 | 实现 |
  |---|---|
  | 基类 / 形态 | 一个策略就是一个 `.py` 文件，放在 `data/strategies/{custom,ai,composite}/`。文件里写：<br>• `META` 字典：id、name、description、tags、asset_types、timeframes；params 每项含 id/label/type/default/min/max/step；scoring 权重合计为 1；order_by；limit<br>• `basic_filter`（pl.Expr）或带 `LOOKBACK_DAYS` 的 `filter_history`<br>• `ENTRY_SIGNALS` / `EXIT_SIGNALS` / `STOP_LOSS` / `MAX_HOLD_DAYS`<br>高级策略设 `EXECUTION_BACKEND="matrix_native"`，实现 `required_fields()`、`required_warmup_bars(params)`、`compute_signals(market, params) -> SignalMatrix` |
  | 注册 / 发现 | `StrategyEngine._load_all/_load_file` 扫描目录自动加载（`StrategyDef`、`CompositeSpec`）。内置 25 个示例，如 ma_golden_cross、macd_golden、boll_breakout、limit_up_momentum、broken_board_recovery、consecutive_limit_ups、pullback_ma20_bounce、oversold_bounce、low_volatility_leader、platform_consolidation_breakout |
  | 指标预计算 | `indicators/pipeline.py`（2515 行），按 `ENRICHED_COLUMNS_BY_CATEGORY` 分类：MA/EMA/MACD/BOLL/KDJ/ATR14/量比/60 日高低/5–60 日动量/年化波动/RSI6/14/24/`signal_*` 等。<br>**口径细节**：README 写"68 列…一次扫表落盘 enriched Parquet"；pipeline 的 docstring 却写"存储只保留 14 列窄表（前复权 OHLCV + raw_* + 换手 + 连板数），指标按 symbol `.over()` 即时计算"。两处表述不完全一致，以源码为准【实际落盘列数待核实】 |
  | 依赖推断 | `feature_deps.py` 用 AST 推断策略需要哪些列，推不出就报错；`factors/registry.py` 是依赖与预热窗口的唯一权威来源 |
  | 自定义信号 | `custom_signals.py`：JSON 定义 `{field, op, threshold}`，条件之间只能 AND。<br>• `ALLOWED_FIELDS` 是字段白名单<br>• 运算符固定：`> >= < <= == !=`，字符串另有 contains/==/!=<br>• 编译成 Polars 表达式，以 `csg_` 前缀列注入。**回测、策略、监控都按列名找信号，注入后三处同时生效，不需要任何特殊处理**（这就是"一个口径"的实现方式）<br>• 盘中信号用 `csgi_` 前缀，走 `intraday_features` 特征帧，与分钟策略和回放用的是同一口径 |
  | 监控规则 | `monitor_rules.py` 统一定义 MonitorRule：<br>• 类型：strategy/signal/price/market/ladder/sector/abnormal/volume_delta/date<br>• 范围：symbols/all/sector/watchlist_group<br>• 条件组合：and/or<br>• 字段复用同一份白名单 |
  | AI 生成策略 | `ai_generator.py`：LLM 按提示词生成**完整的 Python 策略文件**，然后：<br>• 过 AST 安全检查：import 只允许 polars/datetime/numpy，禁用危险内置函数、dunder 属性和文件 IO<br>• 存为 `ai_` 前缀草稿，必须人工发布<br>`ai_iterator.py` 负责有界循环：生成 → 回测 → 诊断 → 修改，不会自动上线 |
  | 合并 | `composite.py` 是策略和回测共用的纯函数（防止两边口径不一致）。<br>• 回测时退出信号做"来源投影"：子策略 B 的退出只能平掉 B 自己开的仓，避免误平 A 的仓（"幽灵平仓"） |
  | 模拟盘 | `paper.py` 已实现：<br>• T+1：可卖不足时订单失效<br>• 费用与印花税<br>• 涨跌停买不进、卖不出：按开关决定排队还是失效留痕<br>• 净值、round_trips、最大回撤<br>`paper_auto.py`：监控事件触发自动下单，**同一规则 + 同一标的有 N 个交易日冷却期**；冷却状态从订单列表重放推导，没有单独的状态文件 |
  | 市场环境 | `docs/market-phase.md` 把情绪周期分 6 阶段：冰点/启动/主升/高潮/退潮/修复。<br>• 输入是涨停梯队：首板数、≥2/3/5 板数、晋级率、梯队完整度<br>• 用 EMA 平滑，并要 2 日确认，防止阶段来回跳<br>另有服务：emotion_score、sector_rotation、market_mainline、abnormal_moves |
- **可借鉴**
  1. **一个口径**：派生指标/信号由一个函数统一产出，按列名供监控、模拟跟踪、复盘使用。
  2. **字段白名单 + 固定运算符**的自定义条件 DSL，编译成表达式，不执行任意代码。
  3. `required_fields` / `required_warmup_bars` / 推不出依赖就报错，对应我们的数据装配与缺口检测。
  4. 情绪周期 6 阶段，配合平滑和 2 日确认（供情绪维度和 RC3 使用）。
  5. 模拟盘规则：T+1、涨跌停不可成交、费用、冷却期。
  6. AI 产物只能是草稿，必须人工发布。
  7. 子策略的退出只作用于自己的仓位（对应我们"每个策略独立跟踪"）。
- **不适合**
  - 以回测/挖掘为中心（我们不做回测）。
  - 在进程内执行 LLM 生成的 Python，就算有 AST 检查也不适合多用户 SaaS。
  - 单用户本地 Parquet/JSON 文件存储（是否支持多租户【待核实】，没看到相关设计）。
  - 数据源是 TickFlow 等，不是麦蕊。

### 1.2 KHunter
- **仓库**：https://github.com/ling-0729/KHunter
- **许可证**：MIT 正文 + 派生声明（源自 Dzy-HW-XD/a-share-quant-selector，MIT；所有分发须保留）。GitHub 因为有附加段落识别为 NOASSERTION，正文是标准 MIT。可以商用，需保留两份声明。
- **热度**：670★ / 180 fork；最近推送 2026-10-07（丹佛时间）；v1.7.1。
- **技术形态**：Python 3.10+，Web（`web_server.py`，端口 5001）。数据走 akshare + tushare（见 requirements.txt）。另有 `start.bat` 面向 Windows、vectorbt 回测、`ptrade/` 目录、飞书日报。
- **策略库怎么搭的**

  | 方面 | 实现 |
  |---|---|
  | 基类 | `BaseStrategy(ABC)`：<br>• 构造：`__init__(name, params)`<br>• 抽象方法：`calculate_indicators(df)`、`select_stocks(df, stock_name) -> list[dict]`<br>• 公共能力：`quick_filter`、数据校验、停牌判断、ST/退市过滤（`_validate_stock_name`）、`get_selection_criteria()`<br>• `execute_selection` 是标准化流水线 |
  | 注册表 | `StrategyRegistry.auto_register_from_directory` 导入目录下不以下划线开头的 `.py`，按类名注册 BaseStrategy 子类。`run_strategy` **每次运行都重读最新参数**。废弃策略放 `strategy/disabled/` 归档 |
  | 参数 | `config/strategy_params.yaml`：`strategies.<类名>` 下有 display_name、description、icon、color、param_groups、`param_details{default,min,max,type,group,description}`、params。另有 `strategy_order.yaml`。<br>`_convert_param_types` 修过一个 bug：YAML 里的 `'false'` 字符串被当成真值。这说明**参数必须有类型化 schema** |
  | 参数审计 | `param_tracker.py`：参数哈希 + `logs/param_changes.log`；`param_lock.py`：`.param_lock` 锁定 |
  | 择时 | `TimingStrategy(ABC)`：calculate_indicators / is_buy_point / is_sell_point / calculate_support / get_timing_result。<br>`TimingResult` 字段：is_buy、is_sell、数量、`signal_strength` 0–1、支撑/阻力、指标快照、message、`trade_type` buy/add/sell/reduce、add_count。由工厂类 `TimingStrategyFactory` 创建 |
  | 多维评分 | `stock_score_calculator`：技术 35%、资金 35%、基本面 10%、板块 10%、事件 10%。每个维度的明细带 `veto` + `veto_reason`（一票否决） |
  | 环境与风控 | `regime_router.yaml`：环境分明确/萌芽/震荡，分别映射选股器、择时器和仓位，支持 manual_override 和 confirm_days。<br>大盘 ADX 仓位上限：ADX>25 且上升 → 100%；ADX<18 且上升且收盘>MA20 → 50%；其他 → 0%。<br>`risk_config.yaml`：按 VaR/EWMA 分正常/注意/危险/崩溃四级，各级对应仓位上限、止损倍数、是否清仓。<br>另有 Kelly 配置、`pool_removal_config`、`continuous_temp_risk` |
  | 口径一致 | 实盘和回测共用同一个信号时点解析器：信号日当天收盘确定信号，T+1 执行，无未来函数。另有 `trading_plan` 表 |
  | 选股策略（文件名） | golden_triangle、immortal_guidance、leader、limit_up_pullback、main_uptrend_dip_buy、morning_star、multi_golden_cross、multi_party_cannon、new_stock_drawdown、oversold_rebound、resistance_breakout、strategy_2560_selection，另有形态匹配（pattern_*）和圆弧底参数（strategy_params.yaml 首项） |
- **可借鉴**
  1. 基类 + 目录自动注册 + 参数 schema（default/min/max/type/group/description）。这套直接对应我们 L2 模板。
  2. 每次运行都读最新参数，并配合参数哈希做审计。我们用不可变版本 + `param_hash` 实现。
  3. 维度级 **veto + 原因**。我们保留否决，但**不加权合成**。
  4. `TimingResult` 的 `trade_type`（buy/add/sell/reduce）、支撑/阻力、指标快照。
  5. 环境路由要有 confirm_days 防抖；ADX 仓位上限可作为 RC3 的输入之一。
  6. 实盘与回测共用"信号日收盘 → T+1"的时点规则，对应我们模拟跟踪的入场价口径。
- **不适合**
  - 加权综合分（违反"不合并"）。
  - vectorbt 回测、ptrade 耦合。
  - Tushare/akshare 依赖（akshare 是爬虫性质，商用授权不明）。
  - YAML 文件配置是单用户的。
  - Windows 启动脚本。

### 1.3 a-share-quant-selector
- **仓库**：https://github.com/Dzy-HW-XD/a-share-quant-selector（GitHub 搜索找到，并由 KHunter LICENSE 的派生声明交叉确认）
- **许可证**：MIT（"Copyright (c) 2026 Ziyu Du"）。可以商用，保留声明。
- **热度**：502★ / 106 fork；最近推送 2026-09-07 23:54（丹佛时间）。
- **结构**
  - 简化版 BaseStrategy：calculate_indicators / select_stocks / `analyze_stock -> {code, name, signals}`
  - strategy_registry + strategy_params.yaml（如 BowlReboundStrategy：N、M、CAP…）
  - 数据走 akshare，有钉钉通知和 Web UI
- **策略：碗口反弹**
  - 条件：知行短期趋势线 > 多空线；近期出现放量阳线；最大量那天如果是阴线就剔除；KDJ J ≤ 阈值
  - 结果按"回落碗中 / 靠近多空线 / 靠近短期线"分类
  - B1 形态匹配：拿 10 个历史成功案例算相似度排序（双线结构占 30% …）
- **可借鉴**
  - 结果分类标签可以直接作为证据展示。
  - 参数 YAML 的最小骨架。
- **不适合**
  - 只有一个策略。
  - akshare 数据。
  - "成功案例库相似度"有挑样本的幸存者偏差，不适合当可解释规则。

### 1.4 OSkhQuant（看海量化）
- **仓库**：https://github.com/khscience/OSkhQuant
- **许可证**：**CC BY-NC 4.0**，LICENSE 明确"严禁商业目的"。**闭源商业 SaaS 不能复用任何代码或文档**。另外依赖 PyQt5，按其 THIRD_PARTY_NOTICES 是 GPL v3。
- **热度**：1621★ / 427 fork；最近推送 2026-10-19（丹佛时间）；v2.2.0。
- **形态**：Windows 10/11 上的 PyQt5 桌面回测软件，数据来自 BaoStock/Tushare，存储用 DuckDB，基于 miniQMT。
- **策略结构**
  - 一个策略是一个 `.py`：`from khQuantImport import *`，定义 `params` 字典、`init()`、`khHandlebar(data) -> List[Dict]`，可选 `khPreMarket` / `khPostMarket`。
  - 配套 `.kh` JSON 配置：运行模式、回测区间、初始资金；交易成本含最低佣金、佣金率、印花税、过户费、滑点；触发类型 tick/1m/5m/1d。
  - 信号格式：`{code, action: buy|sell, price, volume(100 股整数倍), reason, timestamp}`。
  - 内置 MyTT 指标库和缠论工具 `khChanLunTools`。
  - `khRisk.KhRiskManager`（position_limit / order_limit / loss_limit）只是空壳。
- **可借鉴（仅思想）**
  - 每个信号必须带 `reason`。
  - 触发周期抽象。
  - 模拟跟踪里的 A 股成本与整手规则。
- **不适合**：非商用许可、Windows 桌面、回测中心、QMT 耦合、Tushare。

### 1.5 QuantMind
- **仓库**：https://github.com/qusong0627/QuantMind
- **许可证**：**AGPL-3.0**。通过网络向用户提供服务也必须公开源码，**闭源 SaaS 不能复用代码**（包括 121 个 strategy_templates 文件和文档）。
- **热度**：1847★ / 420 fork；最近推送 2026-10-31（丹佛时间）。
- **形态**：Qlib + RD-Agent，13 个 ML/DL 模型、300+ 特征（Alpha158/Alpha101/GTJA191 等）、Parquet + DuckDB、RSS 舆情 + FinBERT 情感（`backend/services/api/news/sentiment.py` 等）、IM 渠道机器人、本地 T+1 模拟、Docker 部署。
- **策略结构**
  - `strategy_templates/*.py` 与 `*.json` 成对出现（共 121 个文件）。
    - JSON 含 id、name、description、category、difficulty，以及 `params[]{name, description, default, min, max}`。例：as06 深度价值，PE<15、PB<1.5，双周调仓。
    - `.py` 里是 `STRATEGY_CONFIG {"class": "RedisTopkStrategy", "kwargs": {signal: "<PRED>", topk, n_drop}}`。
  - 50 个 A 股模板由生成器脚本作为唯一真源生成，配有校验脚本 `validate_ashare_templates.py`（检查结构与契约）。模板思想来自 1001 份 TradingView Pine 策略去重后的 531 条。
  - 主结构是"模型信号选股 + A 股硬约束"。
  - 基本面硬过滤：kwargs 里写 `f_{field}_{op}`，op 后缀为 `_max`(<=)、`_min`(>=)、`_not`(!=)、`_in`。例：`f_roe_min: 0.1`、`f_is_st_not: 1`。
  - Strategy Lab 规范（v1.0 规划态）：
    - AI 写 Python 后先过 **AST 白名单**（禁止 import os/sys/subprocess/socket，禁用 exec/eval/open/`__import__`），再用 **subprocess + seccomp** 兜底。
    - 回测后有"4 关卡过拟合报告"，通过后才能"转模板"。
  - `ai_strategy` 服务目录有 generators、llm、models，另有 `DEPRECATED.md`；没有逐文件细读【待核实】。
- **可借鉴（仅思想，自写实现）**
  1. 模板参数清单的 JSON 形态，配合**生成器 + 契约校验脚本**做 CI 守门。
  2. 基本面过滤的后缀命名法，可以作为我们 DSL 的语法糖。
  3. "转模板前必须过关卡"的升级门槛思想。我们的关卡不包含回测收益，见 §3.3。
  4. 舆情只作为独立维度展示，不参与动作。
- **不适合**：AGPL；ML/DL 很重（Qlib、FinBERT，单机 10–100 用户维护成本高）；回测中心；RSS 抓取的版权与合规风险。

### 1.6 CTBZStock（草台班子量化）
- **仓库**：https://github.com/thisiszhou/CTBZStock
- **许可证**：MIT（"Copyright (c) 2024 Algernon"）。可以商用。
- **热度**：232★ / 33 fork；最近推送 2026-07-21（丹佛时间）。
- **形态**：A 股中低频框架，覆盖历史数据下载 → 本地 RocksDB 离线回测 → 掘金（gm.api）模拟/实盘定时交易，有飞书通知。README 写明系统需要 Windows / Windows Server（受券商客户端限制）。
- **策略结构**
  - 同一个"小市值 Demo"写了两份：`strategy/backtrade/small_cap_demo.py`（继承 `system.simulation.Simulation`）和 `strategy/online/small_cap_demo.py`（直接调 `gm.api`），**逻辑是复制的**。
  - 过滤函数 `buy_stock_filter` / `holding_stock_filter`：只要沪深主板 00/60；开盘价 < 1.8 不买；ST/停牌不买；上市不满 30 天不买；进入退市整理期不买；开盘就涨跌停不买；持有中变 ST 或进入退市期就卖。
  - `transaction/order_trigger.py` 统计成交相对开盘价的买卖滑点和近 N 日完成度。
- **可借鉴**
  1. 一份完整、可直接列成规则的"**可交易性闸门**"清单。
  2. 执行偏差统计（成交价 vs 参考价），用于复盘的"执行"维度。
  3. 反面教材：回测版和实盘版各写一份必然漂移，印证了我们必须"一份规则、一个求值器"。
- **不适合**：掘金耦合、Windows、回测中心、单策略。

### 1.7 QMT-QuantLimit
- **仓库**：https://github.com/123quant/QMT-QuantLimit
- **许可证**：Apache-2.0。可以商用，需保留 LICENSE/NOTICE 并标注修改。**但** `选股/舆情选股/*.pyc`、`选股/量价选股/问财选股.pyc` 只提供了编译产物，没有源码，没法审阅。
- **热度**：222★ / 78 fork；最近推送 2025-01-15（丹佛时间），已有较长时间没更新。
- **策略**：`打板策略.py`，264 行，`xtquant` miniQMT 回调式。
  - `on_tick` 维护每只股票最近 40 笔 tick 的 deque。
  - 条件：最新价 ≥ 涨停价，且时间 ≤ 10:00，且 `(最新价 − 25 笔前价格) / 昨收 ≥ 3%`。满足就按金额取整到 100 股，以涨停价下单。
  - `策略数据初始化.py` 每日生成涨停价 JSON。
  - 股票池来自手工 txt、问财导出，或"大模型读韭研公社帖子"（.pyc）。
- **可借鉴**
  - 情绪类触发要有**时间窗参数**和"**短窗口涨速**"条件。
  - 盘中按标的维护环形缓存。
- **不适合**：QMT 自动下单（我们不下单）；爬取问财和韭研公社（授权与合规风险）；闭源 `.pyc`。

### 1.8 bondTrader
- **仓库**：https://github.com/freevolunteer/bondTrader
- **许可证**：**无 LICENSE 文件**（API 返回 None），README 写"仅供学习交流使用"。默认保留所有权利，**不能复用代码**。
- **热度**：319★ / 87 fork；最近推送 2024-05-21（丹佛时间），已长期不更新。
- **形态**：Go 语言（src/hqCenter、bondTrigger、orderHolder）+ Python 辅助脚本，依赖 jvQuant 行情和交易 API。做可转债日内 T+0，"债随股动"：正股异动时买转债。
- **策略结构**
  - `data/trigger.json` 是策略配置数组。每项含：
    - holdCnt 最大同时开仓数；amt/vol 仓位
    - bUpper 买单溢价、bWait 买单超时
    - atSale 立即挂卖价差（填 0 切换到模式二）、holdSec 最长持仓
    - high/low 止盈止损点
    - 正股观察窗 sec 内的涨幅 raRate、换手 tnRate、秒均成交额 stockAmt；转债秒均成交额 bondAmt
  - 可以通过 HTTP `ctl?cid=&op=on|off` 按编号启停单个策略。
  - 三进程：行情中心（透传、落地、回放）/ 策略触发器（只管何时买卖）/ 交易维护器（委托与状态）。
- **可借鉴（仅思想）**
  - "**窗口内涨幅 + 换手 + 成交额**"三阈值异动触发，配合**最长持有时间**，可用于日内做T（我们只有 1 分钟粒度）。
  - 策略 = 参数数组 + 单项启停。
  - 行情、策略、执行解耦：对应我们 data-gateway / 策略引擎 / 建议与通知。
- **不适合**：无许可证、可转债与秒级、自动交易、jvQuant 耦合。

### 1.9 AlphaGPT_Tushare
- **仓库**：https://github.com/LilianaMajamay/AlphaGPT_Tushare（非 fork。描述说受聚宽社区帖子启发，是否源自某个上游 AlphaGPT【待核实】）
- **许可证**：**仓库里没有 LICENSE 文件**，pyproject 没有 license 字段，GitHub 识别为 None；只有 README 的"许可证"一节写了"MIT License"。**结论：许可状态不清，在作者补上 LICENSE 文件之前按"不可复用"处理**【待核实】。
- **热度**：184★ / 59 fork；最近推送 2026-01-25（丹佛时间）。
- **流程（已读 src）**
  1. Tushare 拉日线，算归一化特征（ret_norm、vol_chg_norm、trend_norm、mom5_norm…）。
  2. `FactorOperators` 注册表：一元 NEG/ABS/DELTA/SIGN/LOG/SQRT，二元 ADD/SUB/MUL/DIV（加 1e-6 防零）/MAX/MIN。
  3. 提示词把**可用特征和可用算子列给 LLM**（DeepSeek），要求只输出 JSON 列表，并限定最少算子数和最大长度。
  4. 校验：长度 5–200、必须包含已知特征、括号配对、不含 `/0`。
  5. 前缀表达式转换后用 `numexpr` 求值（没用 eval，但 numexpr 也是字符串求值）。
  6. 和已有因子的相关系数 > 0.9 就视为重复剔除。
  7. 回测、IC、滚动夏普。
- **可借鉴**
  - LLM **只能在给定字段 + 给定算子内组合**，输出结构化 JSON。
  - 结构校验后**去重**：我们用"与现有模板命中集合的重合度"代替相关系数。
- **不适合**：许可不清；Tushare；以 IC/夏普回测为门槛（我们不回测）；字符串级校验偏弱，应改为解析成 AST 再按白名单逐节点校验。

---

## 2. 共性观察（为推荐结构提供依据）

1. **"基类 + 目录自动注册 + 参数 schema"是共识**（TSP、KHunter、a-share-quant-selector、QuantMind 模板），可以放心采用。
2. **口径漂移是这类项目最常见的问题**。TSP 专门抽出 `composite.py`，并让自定义信号以列的形式注入；KHunter 让实盘和回测共用信号时点解析器；CTBZ 两份代码复制正是反例。这说明"一份指标计算 + 一个规则求值器"必须作为硬约束。
3. **LLM 直接写 Python 的项目都要靠 AST 白名单和子进程沙箱补漏**（TSP、QuantMind），而且都只给单用户本地用。对多用户 SaaS 来说，让 LLM 只输出受限 DSL（AlphaGPT 的思路，加上 TSP 的字段白名单）风险小一个数量级。
4. **YAML 文件参数在多用户下不可行**。KHunter 的类型 bug 和锁文件说明了这一点：参数应进 DB，用类型化 schema 并做版本化。
5. **加权综合分是普遍做法（KHunter、TSP scoring），但违反我们"不合并"的要求**。只借"维度明细 + 否决原因"。
6. **环境判定都要做防抖**（KHunter confirm_days、TSP EMA + 2 日确认），否则 RC3 会频繁翻转。

---

## 3. 我们策略库的推荐结构（按用户 11:51 定的三层：L1 知识卡 / L2 可运行模板 / L3 实例与计划）

> 适用规模：10–100 用户、单机 Docker Compose（FastAPI + Celery + Redis + PostgreSQL 16）。
> 设计取向：**少一层抽象就少一份口径**。开源证据显示：
> - 精简可行：TSP 只靠"一个 `.py` 文件 + META"、KHunter 只靠"一个基类 + 一个 YAML"就撑起了几十个策略；
> - 层多了会出问题：CTBZ 的复制代码就是因为分层/分份才漂移。
>
> 所以下面对编排者的五层草案和 vision.md 的卡片字段都做了**简化建议**，原因在各处注明。

### 3.0 总览

```
           ┌──────────── 共享底座（不算"层"，所有层共用）────────────┐
           │ data-gateway(麦蕊) → 指标宽表 feature_bars（日/1分钟，一个口径，│
           │ 带 feature_set_version，按时点可回看）                      │
           └──────────────────────────────────────────────────────────────┘
 L1 策略知识卡 strategy_cards（解释用；可以只有文字，规则可标"待量化"）
      │  升级门槛 G1–G7（§3.3，机器检查 + 人工审核）
      ▼
 L2 可运行模板 strategy_templates + 不可变 template_versions
      （YAML 规则 DSL，由一个求值器执行；少量内置 Python 评估器插件）
      │  扫描/盘中评估 → 候选信号（每维度观点 + 证据，不合并）
      ▼
 L3 实例与计划：用户实例 strategy_instances（启用哪些模板、改了哪些参数）
      → 候选信号 + 真实持仓/现金/约束 + 风控 hooks → 计划草案 → 用户确认 → plan_versions
      └→ 模拟跟踪（tracking）→ 表现回填到 L1 卡片和 L2 版本 → 可开关的降权
```

**简化建议 1：五层草案里的"信号层"不单独成层。** 原子信号就是 L2 模板里的一条规则（`dimension + role + expr`）。如果单独建信号层，"信号定义"和"策略里引用的信号"会有两份口径（TSP 用列名统一引用才没出问题）。可复用的原子条件做成**命名规则片段**（`rule_snippets`），由模板引用即可。

**简化建议 2：数据与指标不算一层，而是共享底座。** 它不面向用户，但必须唯一。

**简化建议 3：L1 和 L2 用同一份卡片 schema，靠"完整度状态"区分**，不要做两张互不相关的表。L1 卡片升级后生成 L2 版本，卡片继续作为该模板的说明页。这样避免一个策略有两份文案。参考 QuantMind：模板 JSON 同时承载说明和参数；KHunter：同一份 YAML 里同时有 description 和 param_details。

### 3.1 共享底座：指标宽表（一个口径）
- **来源**：
  - 麦蕊日 K、1 分钟 K（Pro）、实时快照、因子截面（`/factor/batch`、`/factor/screen`）
  - 本地派生：VWAP、ATR14、前高/前低、N 日新高、连续净流入天数、市场宽度、情绪周期阶段、板块相对强弱
- **存储**：
  - `feature_bars_daily(symbol, trade_date, feature_set_version, cols…)`：PostgreSQL 宽表，或"窄表 + JSONB 派生列"【二选一待 T-B05 实测后定】
  - 盘中 1 分钟特征放 Redis 环形缓存，每只股票保留当日分钟数据（借 QMT-QuantLimit 的 deque 思路），收盘落库
- **约束**（借 TSP）：
  1. 派生列**只能由 `features/pipeline.py` 一个模块产出**。盘中建议、盘后日报、模拟跟踪入场价判定、复盘回看都按列名读取，不允许各自重算。
  2. 有 `feature_catalog` 表/注册表，记录每列的 id、维度、来源接口/因子、单位、预热窗口（`warmup_bars`）、更新时点、epistemic_type。规则 DSL 的**字段白名单就是这张表**。
  3. `data_snapshot` 记录 `feature_set_version`，保证按原貌回看。
- **规模估算**：5000 只股票 × 每日一行 × ~120 列，一年约 125 万行，PostgreSQL 单机轻松承载。只有用户关注的标的（上限见 plan 配额章节）才需要盘中 1 分钟特征。

### 3.2 L1 策略知识卡（解释层）
- **用途**：给新手看的"这个方法是什么、什么时候有效、什么时候会坑你"。可以只有文字，没有可运行规则。
- **字段**：在 vision.md 建议字段的基础上**精简为必填 8 项 + 选填若干**。理由：用户是新手，卡片越长越不会读；开源项目的 description 一般只有 1–3 句加参数说明（KHunter/QuantMind）。
  - **必填（8 项）**
    1. 名称/key/版本
    2. 适用周期
    3. 一句话原理
    4. 涉及维度及每个维度的角色（核心/辅助/否决）
    5. 成立条件（每条注明"已量化 / 待量化"）
    6. 反证与失效条件
    7. 退出规则（止损/止盈/时间止损/跟踪止盈，至少一种）
    8. 数据需求（麦蕊接口/因子 + 缺口）
  - **选填**：适用市场环境与标的类型、仓位与风控建议、常见误用与陷阱、个人适配性（盯盘时间/波动承受/经验）、参考资料
  - **系统字段**：完整度状态 `draft / documented / runnable_candidate / promoted / retired`；表现记录（从 L2 跟踪回填，只读）
- **来源**：
  - 内置卡由我们编写，可参考开源策略的**思想**（见 §3.7 表）
  - 用户自建卡
  - **LLM 生成卡**：LLM 只产出 L1 卡片草稿或 L2 规则草稿，见 §3.5

### 3.3 L1 → L2 升级门槛（机器检查 + 人工审核）
升级后生成 L2 `template_versions`，版本号只增不改。门槛如下：

| 关卡 | 检查内容 | 自动/人工 | 依据项目 |
|---|---|---|---|
| G1 规则完整 | 成立（entry）、失效（invalidation/exit）、止损三类规则**都已量化**，没有任何"待量化"条目；每个周期至少一条 exit；日内做T策略必须有"当日回补/时间止损"规则 | 自动 | vision 定义；bondTrader 的 holdSec |
| G2 数据可得 | 每个字段都在 `feature_catalog` 白名单内，且数据源状态不是"缺口"；预热窗口可以满足（比如上市不满 N 日就输出 insufficient_data，不算失败） | 自动 | TSP feature_deps 推不出依赖就报错、required_warmup_bars |
| G3 语法安全 | 规则 DSL 解析成 AST，只允许白名单字段、运算符、函数（比较、布尔、`cross_up/down`、`ma()`、`for N days`、`rank_pct`、`between`…）；**不执行任意代码**；表达式长度和嵌套深度有上限 | 自动 | TSP custom_signals、AlphaGPT 算子注册表（我们做得更严：AST 节点白名单） |
| G4 参数 schema | 每个参数都有 type/default/min/max/step/说明，默认值落在范围内；类型严格（不允许 `'false'` 这种字符串布尔） | 自动 | KHunter param_details 及其类型 bug |
| G5 可交易性与 A 股约束 | 自动挂上通用闸门：ST、停牌、上市不足 N 天、退市整理期、一字涨跌停不可成交、T+1 可卖数量；止损止盈价限制在涨跌停范围内 | 自动 | CTBZ 过滤清单、TSP paper.py |
| G6 历史体检（**不是回测**） | 在最近 N 个交易日（默认 120）的指标宽表上**只统计触发频率与数据覆盖率**：触发率过高（如 >30% 股票-日）或为 0 都要警告；和已有模板的命中集合重合度 >0.9（Jaccard）视为重复。**不计算收益、胜率、夏普**，以遵守"不做回测"的要求；表现只从上线后的模拟跟踪得到 | 自动 | AlphaGPT 相关性去重、QuantMind 关卡思想（去掉回测部分） |
| G7 人工审核 | 全站内置/共享模板由管理员审核；用户私有模板由本人确认。审核页并排展示卡片文字和规则的逐条对应、G1–G6 报告 | 人工 | TSP 草稿须人工发布 |

- 不通过时卡片留在 L1，并显示缺哪一关，比如"止损规则待量化"。这本身就是给新手的教育信息。
- **退役**：模板版本可以标记 `retired`；正在使用它的实例会收到提示，旧建议仍可回看。借 KHunter 的 `strategy/disabled/` 归档。

### 3.4 L2 可运行模板（基类 / 注册表 / 参数 / 指标预计算放在这一层）

**3.4.1 两种执行形态（简化建议 4：默认只用 DSL）**
- **A. 规则型（默认，覆盖 9 个内置策略中的绝大多数）**
  - 模板就是 YAML/JSON 配置，即 plan §2.5.1 的 `strategy_versions.config`。
  - 由**唯一的** `RuleEvaluator` 执行。
  - 优点：新增模板不需要写代码，LLM 产出也走同一条路径。
- **B. 评估器插件（只限内置、需要代码审查）**
  - 用于 DSL 不好表达的逻辑，比如分时 VWAP 偏离带、形态识别（碗口、平台整理）、情绪周期阶段。
  - 插件**只产出新的特征列或信号列**（借 TSP：自定义信号以 `csg_` 列注入），写进指标宽表，再由规则型模板引用。
  - 插件本身**不直接给出动作**。这样动作映射、风控、跟踪仍然只有一条路径。

**3.4.2 插件接口（Python，内置代码，借 TSP matrix_native + KHunter BaseStrategy）**
```python
class FeaturePlugin(ABC):
    id: str; version: str
    dimension: Dimension            # technical/capital/fundamental/sentiment/sector_market/news
    timeframe: Literal["daily", "1m"]
    output_columns: list[ColumnSpec]  # 进入 feature_catalog
    def required_fields(self) -> set[str]: ...
    def required_warmup_bars(self, params) -> int: ...
    def compute(self, frame: pl.DataFrame, params) -> pl.DataFrame: ...   # 纯函数，无 IO
```

**3.4.3 规则型模板求值接口（RuleEvaluator 对每个模板版本的输出）**
```python
class TemplateResult(BaseModel):
    template_version_id: str; horizon: Horizon
    state: Literal["entry_ok", "hold_ok", "weakening", "exit_signal", "insufficient_data", "vetoed"]
    dimension_views: list[DimensionView]  # 每维度: view(bullish/bearish/neutral/unknown), score, rules[{rule_id, pass, value, threshold, evidence_id}], veto_reason?
    proposed_action: Action               # buy/add/hold/reduce/sell/wait (+ t_leg)；只是"候选"，交给 L3
    stops: {stop_loss, take_profit, time_stop?, trailing?}
    support_resistance: {support?, resistance?}   # 借 KHunter TimingResult
    reasons / counter_evidence / invalidation: list[EvidenceRef]
    data_gaps: list[str]
```
- **规则角色**在 plan 现有的 `entry / hold / weakening / exit` 之外，**新增 `veto`**（借 KHunter 一票否决）。命中时该模板 `state=vetoed`，并在对应维度格子里显示否决原因。**veto 只作用于本模板自身**，不改写其他模板，也不跨模板合并。

**3.4.4 注册与发现**
- 规则型模板：DB 表 `strategy_templates`（头）+ `template_versions`（不可变）。内置模板随代码放在 `strategies/builtin/*.yaml`，启动时以 key + version 为幂等键 upsert。这和 TSP/KHunter 的"扫描目录"等价，但**以 DB 为准**。
- 评估器插件：用模块级装饰器 `@register_plugin` 在进程启动时注册（借 KHunter `auto_register_from_directory`）。不支持运行时热加载第三方代码。

**3.4.5 参数与版本**
- 参数 schema 存在模板版本里（借 KHunter param_details / QuantMind JSON params）。用户改参就生成**用户私有派生版本**（`parent_version_id`），并记录 `param_hash` 和 diff（借 KHunter param_tracker）。不使用锁文件，版本本身不可变。
- 不在运行时读 YAML 文件。KHunter 的"每次运行读最新参数"在我们这里对应"实例引用某个具体版本"，升级要显式操作。

**3.4.6 调度**：盘后由 Celery 批量对 universe 计算宽表并求值；盘中由 realtime 进程按 1 分钟 bar 增量求值。两条路径调用同一个 `RuleEvaluator`。

### 3.5 LLM 生成策略：只产出 L1 卡片或 L2 草稿
- **输入**：用户的自然语言想法，或一张"待量化"的 L1 卡。提示词附上 `feature_catalog` 字段白名单（含单位与含义）、DSL 语法和算子表、参数 schema 规则。这是借 AlphaGPT 的"只准用给定特征和算子"。
- **输出**：严格 JSON（卡片字段 + 规则 DSL + 参数 schema），**禁止输出代码**。
- **校验**：自动跑 G1–G6。失败原因回传给 LLM，最多修正 3 轮（借 TSP ai_iterator 的有界迭代，但去掉回测）。仍失败就**降级保存为 L1 卡片**，不完整的条目标"待量化"。
- **审批**：G7 人工审核。LLM 产物永远是 `draft`，不会自动启用（借 TSP、QuantMind）。全站共享需要管理员审核。
- **沙箱**：因为只解析 DSL，不执行代码，所以**不需要 seccomp 或子进程沙箱**（QuantMind 要靠它兜底，我们从根上去掉了这个风险）。G6 体检在 Celery worker 里用只读数据库账号执行，设超时。
- **存档**：记录 `llm_call_id`、模型、提示词版本、原始输出，便于审计。这与 plan §2.7 的 LLM 网关一致。
- **与 plan 现有表述的关系**：plan 现在写的是"LLM 只写解释、不做决定"。这里的生成能力**仍然不做决定**：产物必须经过机器门槛和人工审核才能成为模板，动作仍然由确定性求值器给出。建议排在主线之后的阶段。

### 3.6 L3 策略实例与操作计划
- **实例 `strategy_instances`**：用户 × 标的（或账户默认）× 启用的模板版本 × 周期。由 plan §2.5.3 的周期分类器初始化，用户可以改。
- **候选信号**：L2 输出的 `TemplateResult` 只叫"候选信号"。界面不出现"立即买入"，展示为"规则信号：买入条件满足"（符合 plan 7.2 的措辞）。
- **生成计划草案**：候选信号 + 真实持仓（可卖数量）+ 现金 + 用户约束（单只上限、行业上限、不碰 ST 等）+ 风控 hooks → 计划草案，包含动作、数量区间、价格区间、止损止盈、失效条件、需要人工核对的项。**用户确认后**才成为 `plan_versions`。
- **六项风控 hooks**（统一接口 `RiskHook.evaluate(ctx) -> RiskFlag[]`，逐项开关，**只打标记、只门控数量，不改写模板的候选动作**）：

  | 风控 | 关键参数 | 借鉴来源 |
  |---|---|---|
  | RC1 止损/止盈 | 来自模板 `stops`，限制在涨跌停范围内 | TSP STOP_LOSS / MAX_HOLD_DAYS、bondTrader high/low/holdSec |
  | RC2 单只仓位上限 | — | KHunter position_limit、OSkhQuant 风控接口 |
  | RC3 总仓位按环境 | regime = 指数趋势 + 宽度 + 情绪周期 6 阶段，配合 **confirm_days 防抖**；ADX 仓位上限可作为辅助指标展示 | TSP market-phase、KHunter regime_router 与 ADX 规则 |
  | RC4 板块集中度 | — | — |
  | RC5 连亏/回撤 | 账户层与"策略模拟跟踪连续失败"两类；VaR/EWMA 分级可后置 | KHunter risk_config |
  | RC6 违反计划 | 成交导入后对照 `plan_versions` | KHunter trading_plan 表思想 |

- **模拟跟踪**（plan §2.8 的 T+1/5/20），按开源项目的成熟规则补充：
  - 入场价：信号日收盘生成的建议按 T+1 开盘价入场；盘中建议按下一根 1 分钟 bar 开盘价入场（借 KHunter 信号时点解析器、TSP 盘中口径）
  - 一字涨停买不进、一字跌停卖不出时记为"不可成交"，不计入胜率（借 TSP paper.py）
  - 可选扣除费用和印花税（借 OSkhQuant/TSP 成本模型）
  - **同模板 + 同标的冷却 N 个交易日**，防止反复出同一建议、虚增样本（借 TSP paper_auto）
  - 每个模板版本独立跟踪，退出只作用于自己（借 TSP 来源投影）
- **降权**：沿用 plan §2.5.7 的公式（平滑胜率 + 超额，限制在 0.3–1.2，n<20 不调整），只影响排序。新增两点：结果**回填 L1 卡片的"表现记录"**；连续表现差时（如 weight<0.6 持续 20 个交易日）在 L1/L2 上提示"建议复审"，**不自动退役**。
- **执行偏差**：用户真实成交价对比建议价，记录滑点和完成度（借 CTBZ 滑点统计），作为复盘"执行"维度的素材。

### 3.7 内置策略候选 × 4 周期 × 6 维度
图例：● 核心规则；○ 辅助/参考；✕ 否决条件；— 不用。来源列只表示**思想参考**，代码自写。①–⑨ 是 plan §2.5.2 已有的 9 个，★ 是本次建议新增的候选（建议先作为 L1 卡片，满足 G1–G7 后再进入 L2）。

| # | 模板 key | 周期 | 技术 | 资金 | 基本面 | 情绪 | 板块与大盘 | 消息 | 思想来源 |
|---|---|---|---|---|---|---|---|---|---|
| ① | t_vwap_revert 均价回归做T | 日内做T | ● | ○ | — | ✕（涨跌停/炸板时不做） | ✕（大盘单边下跌时只高抛） | ✕（重大公告） | TSP 分时信号"价格上穿/下穿均价"、bondTrader holdSec 时间止损 |
| ★ | t_intraday_surge 分时异动高抛/低吸 | 日内做T | ●（N 分钟涨速） | ○（成交额放大） | — | ✕ | ○ | ✕ | bondTrader 窗口涨幅/换手/成交额三阈值、QMT-QuantLimit 25 笔涨速 + 时间窗 |
| ② | st_strong_momo 强势情绪 | 短线 | ● | ● | ✕（ST/预亏） | ● | ● | ✕ | TSP limit_up_momentum / consecutive_limit_ups、KHunter limit_up_pullback、QMT-QuantLimit 打板（只取观察条件，不做打板下单） |
| ★ | st_broken_board_recovery 断板反包 | 短线 | ● | ○ | ✕ | ● | ○ | ✕ | TSP broken_board_recovery |
| ③ | st_oversold_rebound 超跌反弹 | 短线 | ● | ● | ✕ | ○ | ○ | ✕ | KHunter oversold_rebound、TSP oversold_bounce |
| ★ | st_pullback_ma 强势回踩均线 | 短线/波段 | ● | ○ | ✕ | — | ○ | ✕ | TSP pullback_ma20_bounce、KHunter main_uptrend_dip_buy |
| ④ | sw_trend_follow 趋势跟随 | 波段 | ● | ● | ✕ | ✕（过热） | ● | ✕ | KHunter multi_golden_cross / regime_router、TSP 均线多头 |
| ⑤ | sw_breakout 突破 | 波段 | ● | ● | ✕ | ✕（一字/炸板） | ○ | ✕ | TSP boll_breakout / platform_consolidation_breakout、KHunter resistance_breakout |
| ★ | sw_bowl_rebound 碗口/圆弧底 | 波段 | ●（插件产出形态列） | ○ | ✕ | — | ○ | ✕ | a-share-quant-selector 碗口反弹、KHunter 圆弧底参数（不使用"成功案例相似度"） |
| ⑥ | lt_value 低估值 | 中长线 | ○ | ○ | ● | — | ○ | ✕ | QuantMind as06 深度价值的思想（f_pe/pb 过滤） |
| ⑦ | lt_quality_growth 高 ROE 增长 | 中长线 | ○ | ○ | ● | — | — | ○ | QuantMind 质量过滤思想 |
| ⑧ | lt_dividend 红利 | 中长线 | ○ | — | ● | — | — | ○ | —（自有设计） |
| ⑨ | lt_low_vol 低波动 | 中长线 | ○ | — | ✕ | — | ○ | ✕ | TSP low_volatility_leader |
| 通用 | gate_tradability 可交易性闸门（所有模板自动挂载） | 全部 | — | — | ✕（ST/退市） | ✕（一字板） | — | ✕（停牌/退市整理） | CTBZ、KHunter `_validate_stock_name` |
| 通用 | regime 大盘环境 / 情绪周期（插件，产出特征列，供 RC3 和各模板引用） | 全部 | ○ | ○ | — | ● | ● | — | TSP market-phase 6 阶段、KHunter ADX/regime_router |

**覆盖检查（4 × 6）**：资金维度在中长线只作参考，是合理的；**消息维度全周期只用公告类型做否决或参考**，这是麦蕊的新闻缺口导致的（plan §4.5）；情绪维度在中长线不作条件。新增的 4 个 ★ 补强了日内和短线的密度。建议 MVP 只上 ①–⑨ 加通用闸门，★ 作为 L1 卡片先展示。

### 3.8 单机 10–100 用户的务实取舍
- **不引入**：Qlib/ML 模型、FinBERT、DuckDB/Parquet 第二存储、子进程沙箱、热加载第三方代码。原因是维护成本和攻击面，以及我们不执行代码。
- 求值性能：日终 5000 股 × ~15 个模板，用 Polars 向量化，预计分钟级完成【实测待核实】。盘中只算关注标的。
- 全站模板共享一份宽表；用户差异只体现在实例参数和风控上，所以不需要按用户复制数据。
- 许可证：保持"思想借鉴、自写实现"。如果拷 MIT 片段，登记到 `THIRD_PARTY_NOTICES.md`。**禁止拷贝 OSkhQuant、QuantMind、bondTrader、AlphaGPT_Tushare 的任何代码或文档文本。**

---

## 4. 建议合并进 plan.md 的具体改动（由编排者合并，本文件不改 plan.md）

1. **§2.5 开头**：加入三层结构 L1 知识卡 / L2 可运行模板 / L3 实例与计划，以及共享指标底座（§3.0 图）；注明"信号层"并入 L2 规则和 `rule_snippets`。
2. **§2.5.1 概念表**：
   - 新增 `strategy_cards`（L1，带完整度状态和表现回填）、`rule_snippets`、`feature_catalog`、`strategy_instances`。
   - 把 `strategies/strategy_versions` 改名或说明为 L2 `strategy_templates/template_versions`。
   - 规则角色新增 `veto`。
   - 参数 schema 必须有 type/default/min/max/step/说明，用户改参生成派生版本，记录 `parent_version_id` 和 `param_hash`。
3. **新增 §2.5.x「L1→L2 升级门槛」**：G1–G7 原文照录 §3.3，并明确 G6"历史体检"只统计触发率、覆盖率和重合度，**不算收益**，与"不做回测"一致。
4. **新增 §2.5.x「指标宽表（一个口径）」**：
   - `features/pipeline.py` 是派生列的唯一产出者，`feature_catalog` 同时就是 DSL 字段白名单。
   - `data_snapshot` 记录 `feature_set_version`。
   - 盘中 1 分钟特征放 Redis 环形缓存，收盘落库。
   - 盘中、盘后、跟踪、复盘统一按列名读取。
5. **§2.5.2**：
   - 加"通用可交易性闸门"规则组（ST、停牌、上市不足 N 天、退市整理期、一字板、T+1 可卖），所有模板自动挂载。
   - 把 regime / 情绪周期 6 阶段做成插件产出的特征列，并加 confirm_days 防抖。
   - 列出 4 个 ★ 候选作为 L1 卡片（不进 MVP L2）。
6. **§2.5.4 流水线**：
   - ③的输出改名为"候选信号"（L2）。
   - 在④和⑦之间插入"L3 计划草案：结合可卖数量、现金、约束生成数量和价格区间，用户确认后成为 plan_versions"。
   - 明确插件只产出特征列，不产出动作。
7. **§2.5.6 风控**：RC3 加入情绪周期阶段和防抖，ADX 仓位上限作为参考展示；RC5 的 VaR/EWMA 分级标记为后置。统一 `RiskHook` 接口。
8. **§2.5.7 / §2.8 模拟跟踪**补充：
   - 入场价口径：盘后建议按 T+1 开盘价，盘中建议按下一根 1 分钟 bar 开盘价
   - 一字板不可成交的样本剔除
   - 可选费用和印花税
   - 同模板 + 同标的冷却 N 日
   - 表现回填 L1 卡片
   - weight<0.6 持续 20 日提示复审，不自动退役
9. **§2.7 LLM 网关**新增用途"策略草稿生成"：只输出 JSON（卡片 + DSL），走 G1–G6 自动校验，最多修正 3 轮，失败就降级为 L1 卡片；G7 人工审核；永远不执行代码；存 llm_call_id。放在主线之后的阶段。
10. **§2.3 能力 2"不做什么"**：把"用户自写代码策略（MVP 只允许受限表达式改参）"改成"任何人和 LLM 都不能提交可执行代码；自定义只能通过受限 DSL 和参数"。
11. **§3.3 数据表**新增：
    - `strategy_cards`、`card_versions`（如果卡片也要版本化）
    - `rule_snippets`
    - `feature_catalog`、`feature_bars_daily`
    - `strategy_instances`
    - `template_promotion_reviews`（G1–G7 报告 + 审核人）
    - `llm_strategy_drafts`
12. **§6 目录结构**：`backend/app/strategy/{cards,templates,evaluator,plugins,promotion,instances}`、`backend/app/features/{pipeline,catalog}`、`strategies/builtin/*.yaml`；新增 `THIRD_PARTY_NOTICES.md`。
13. **§8 阶段**：
    - MVP：底座 + L2 的 ①–⑨ + 闸门 + L3 计划草案 + 跟踪 + 降权
    - 第二阶段：L1 卡片库（含 ★）+ 升级流程 + 用户派生版本
    - 第三阶段：LLM 草稿生成
14. **新增一条风险/合规**：开源代码许可证清单（§0 表），明确不得拷贝 CC BY-NC / AGPL / 无许可证项目的代码。

---

## 5. 待核实清单
- TSP 实际落盘的列数：README 说 68 列，pipeline docstring 说 14 列窄表 + 即时计算；TSP 是否支持多租户。
- QuantMind `ai_strategy` 服务的具体实现（只看了目录和 Strategy_Lab 规范）。
- AlphaGPT_Tushare 的真实许可证（需作者补 LICENSE 文件）及其是否源自某个上游 AlphaGPT。
- QMT-QuantLimit 中 `.pyc` 选股逻辑（没有源码）。
- 指标宽表的存储形态（宽表还是窄表 + JSONB）和日终求值耗时，需 T-B05 用麦蕊实测数据定。
- 麦蕊因子总数 77 还是 85、各字段空值率（沿用 plan 的待核实项）。
