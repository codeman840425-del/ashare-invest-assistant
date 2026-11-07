# W-03 主力净流入 `sw_main_inflow` — 知识卡 v1（T-R16 第二批）

> **当前状态：不可导入**（83a66cd 裁定后，本轮只写知识内容，不补 golden，不实现引擎）。下面的 expr 是设计层规则，**不是**当前可以导入的 schema；标“拟议”的字段、函数、语义在契约中还不存在，不代表现有能力或新的裁定。
> 初稿：DeepSeek（`team/reports/deepseek/T-R16/W-03.md`，未核实草稿），本文为研究员逐条复核后的版本。来源：通用规则组合，无外部来源。阈值均为 hypothesis，不含收益、回测或覆盖率数字。

## 1 身份
key `sw_main_inflow`；category `trend`；horizons `[swing]`；risk_level `normal`。（资金流类在 category 枚举中没有对应取值，暂用 trend，是否新增取值**待定**，需提给架构师）

## 3 假设、反证与维度
- why_it_works（hypothesis）：20 日主力资金持续净流入、而价格还没有明显透支的股票，可能处在机构建仓阶段，波段延续概率较高。
- falsified_by：1) `f.main_net_20d` 来源核实后，样本外 10 日扣费超额中位数 ≤ 0；2) 净流入为正与为负两组的后续收益没有差异；3) 资金指标与成交额高度相关（相关系数 > 0.8，hypothesis），说明它只是量能代理。
- 维度：capital 为 core；technical 为 auxiliary（趋势与透支过滤）；sector_market 为 veto；news 由 N-01 系统挂载。

## 4 标的范围
主板、创业板、科创板；上市满 120 日；20 日均额 ≥ `p.min_amount`。

## 5 数据（时点 / 单位 / 复权 / 预热）
| 键 | 频率 | 单位 | 复权 | 可得时点 | 状态 |
|---|---|---|---|---|---|
| f.main_net_20d | 日 | CNY | none | T 15:40 后 | 已注册；**来源与口径未实测**（DAT-4） |
| f.amount_20d_avg | 日 | CNY | none | T 盘后 | 已注册 |
| f.momentum_60d | 日 | pct（35 = 35%） | qfq | T 盘后 | 已注册 |
| f.close_qfq | 日 | 元 | qfq@as_of | T 盘后 | 已注册 |
预热：60 根有效日 K（动量 60，≥45 有效）；不足时 `insufficient_data`，不产生候选。数据缺失：`f.main_net_20d` 缺失 → `insufficient_data`，不用 0 填补。

## 7 规则（设计层定稿；未定的部分标 拟议 / 待定）
| id | role | expr | 说明 |
|---|---|---|---|
| E1 | entry | `f.main_net_20d > 0 for p.inflow_days days` | 20 日累计净流入连续为正；原稿用的 `f.main_net_20d_pos_days` 未注册，已改写 |
| E2 | entry | `f.main_net_20d >= f.amount_20d_avg * 20 * p.inflow_ratio` | 净流入占 20 日成交额的比例（两者都是 CNY） |
| E3 | entry | `f.close_qfq > ma(f.close_qfq, 20)` |  |
| F1 | filter | `f.amount_20d_avg >= p.min_amount and f.list_days >= p.min_list_days` |  |
| V1 | veto | `f.market_regime == 'downtrend'` |  |
| C1 | counter | `f.momentum_60d > p.overext` | 价格透支（单位 pct，原稿写 0.35 有误） |
| I1 | invalidation | `f.main_net_20d < 0 for 3 days` | 资金转弱 |
| X1 | exit（止损） | `f.close_qfq <= plan.entry_price_qfq * (1 - p.stop_pct)` | 原稿用 `ctx.last_price`，与 qfq 口径混用，已改 |
| X2 | exit | `f.main_net_20d < 0 for p.outflow_days days` |  |
| X3 | exit（时间） | `ctx.holding_days >= p.max_hold and ctx.max_r_reached < 1` |  |
- E1、X2 中的 `for p.x days` 依赖参数化时间修饰（RUL-6）；在此之前只能用常数天数。

## 8–10 执行与仓位
T 日盘后（15:40 后资金数据可得）确认，T+1 开盘模拟入场；仓位按 RC2/RC3。

## 11 验证（本轮不写 golden）
`fixture`、`trigger_stats`、`tracking_sim`；horizon_days [5,10,20]；`min_n=30`；对照组为同成交额分位、无资金条件的样本。

## 14 不可执行原因
`LIMIT_LOCKED`（两个方向）、`SUSPENDED`、`T1_NOT_SELLABLE`、`KEY_DATA_MISSING`、`NEW_LISTING`、`ST_OR_DELISTING`。

## 15–16 环境与节奏
适用于 uptrend、range；每日盘后扫描。

## 17 A股约束
T+1：当日买入的股份当日不可卖，触发退出时记 `T1_NOT_SELLABLE`，顺延到可卖日。涨跌停价按 market_rules 计算（主板 10%、创业板和科创板 20%、ST 5%；注册制新股上市前 5 日无涨跌幅限制），一字封板按执行层原因 `LIMIT_LOCKED` 处理（写明 direction），不写成 veto。停牌记 `SUSPENDED`，可交易性、ST、退市整理由 G-01 处理，风险公告由 N-01 处理（均由系统挂载，本卡不重复写）。整手：科创板 ≥ 200 股、超出部分按 1 股递增；其余板块 100 股整数倍；零股须一次性卖出。

## 18 成本与滑点（estimate）
佣金按用户费率，单笔最低 5 元，双边计；印花税仅卖出 0.05%；过户费 0.001%（双边）；滑点 `p.slippage_bp`（estimate）；冲击成本按 plan 2.13 分档（0/5/15/30/60bp），参与率 > 2% 标“容量受限”。

## 20 冲突
与 W-04 同向时并列（维度不同）；与 H-01 并列。 一律并列展示，不合并结论。

## 22 参数（hypothesis；slippage_bp 为 estimate）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| inflow_days | int | 5 | 3 | 10 | 1 |
| inflow_ratio | float | 0.03 | 0.01 | 0.08 | 0.01 |
| overext | float | 35.0 | 20.0 | 60.0 | 5.0 |
| stop_pct | float | 0.08 | 0.05 | 0.12 | 0.01 |
| outflow_days | int | 3 | 2 | 5 | 1 |
| max_hold | int | 20 | 10 | 40 | 5 |
| min_amount | float | 100000000.0 | 20000000.0 | 500000000.0 | 10000000.0 |
| min_list_days | int | 120 | 60 | 250 | 10 |
| slippage_bp | float | 10.0 | 0.0 | 50.0 | 1.0 |

## 23 当前不可导入原因与引擎需补能力
- DAT-4 `f.main_net_20d` 来源与口径
- RUL-6 `for p.x days` 参数化

## 复核记录（相对 DeepSeek 原稿）
1. 原稿用了未注册的 `f.main_net_20d_pos_days`、`f.main_net_20d_ratio`，已改写为已注册键加时间修饰
2. `f.momentum_60d` 单位是 pct，原稿 0.35 和 0.40 有误
3. `ctx.last_price` 与 qfq 混用，已改正
4. 原稿 C3（行业走弱 for 5 days）依赖 DAT-3，已删除
5. 原稿加仓规则属于 RC 层，已删除
