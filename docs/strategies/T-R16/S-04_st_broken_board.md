# S-04 断板反包 `st_broken_board` — 知识卡 v1（T-R16 第二批）

> **当前状态：不可导入**（83a66cd 裁定后，本轮只写知识内容，不补 golden，不实现引擎）。下面的 expr 是设计层规则，**不是**当前可以导入的 schema；标“拟议”的字段、函数、语义在契约中还不存在，不代表现有能力或新的裁定。
> 初稿：DeepSeek（`team/reports/deepseek/T-R16/S-04.md`，未核实草稿），本文为研究员逐条复核后的版本。来源：通用规则组合，无外部来源。阈值均为 hypothesis，不含收益、回测或覆盖率数字。

## 1 身份
key `st_broken_board`；category `momentum`；horizons `[short]`；risk_level `high`。

## 3 假设、反证与维度
- why_it_works（hypothesis）：连板后首次断板（分歧）后，次日放量收复断板日高点，说明分歧转一致、情绪修复。
- falsified_by：1) 样本外反包次日起 3 日扣费超额中位数 ≤ 0；2) 放量条件与不放量组没有差异；3) downtrend 环境下结论与 uptrend 相同。
- 维度：sentiment 为 core；technical 为 core（收复高点）；capital（成交额）为 auxiliary；sector_market 为 veto；news 由 N-01 系统挂载。

## 4 标的范围
主板、创业板、科创板；上市满 60 日。

## 5 数据（时点 / 单位 / 复权 / 预热）
| 键 | 频率 | 单位 | 复权 | 可得时点 | 状态 |
|---|---|---|---|---|---|
| f.is_limit_up_close / f.limit_up_count_20d | 日 | bool / count | none | T 盘后 | 已注册 |
| f.close_qfq / f.high_qfq | 日 | 元 | qfq@as_of | T 盘后 | 已注册 |
| f.amount / f.amount_20d_avg | 日 | CNY | none | T 盘后 | 已注册 |
预热：20 根有效日 K；不足时 `insufficient_data`，不产生候选。数据缺失：关键特征缺失 → `insufficient_data`。

## 7 规则（设计层定稿；未定的部分标 拟议 / 待定）
| id | role | expr | 说明 |
|---|---|---|---|
| E1 | entry | `ref(f.is_limit_up_close, 2) == true and ref(f.is_limit_up_close, 1) == false and f.limit_up_count_20d >= p.min_boards` | T−2 封板、T−1 断板 |
| E2 | entry | `f.close_qfq > ref(f.high_qfq, 1)` | 收复断板日高点 |
| E3 | entry | `f.amount > f.amount_20d_avg * p.vol_ratio` | 放量 |
| V1 | veto | `f.market_regime == 'downtrend'` |  |
| C1 | counter | `f.close_qfq >= f.limit_up_price` | 当日已封板，次日可能一字买不进；仍记录统计（口径：limit_up_price 为 none，在 qfq@as_of 当日可比） |
| I1 | invalidation | `f.close_qfq < ref(f.high_qfq, 2) for 2 days` | 跌回断板前区间 |
| X1 | exit（止损） | `f.close_qfq <= plan.entry_price_qfq * (1 - p.stop_pct)` |  |
| X1b | exit（止损，实现 MVP 后） | `f.close_qfq < plan.breakout_level_qfq` | 断板日高点（QFQ-2） |
| X2 | exit | `f.close_qfq < ma(f.close_qfq, 5)` |  |
| X3 | exit（时间） | `ctx.holding_days >= p.max_hold` |  |
- 原稿用 `ref(f.high_qfq, ctx.holding_days + 1)`（动态偏移），DSL 不支持，已改为 X1b。
- 原稿 E1 只看 T−1 封板、T 断板，与“次日反包”的时序不符，已改为 T−2 封板、T−1 断板、T 反包。

## 8–10 执行与仓位
T 日盘后确认，T+1 开盘模拟入场；有效期 1 个交易日；仓位按 RC2。

## 11 验证（本轮不写 golden）
`fixture`、`trigger_stats`、`tracking_sim`；horizon_days [1,3,5]；`min_n=30`。

## 14 不可执行原因
`LIMIT_LOCKED`（两个方向）、`SUSPENDED`、`T1_NOT_SELLABLE`、`KEY_DATA_MISSING`、`NEW_LISTING`、`ST_OR_DELISTING`。

## 15–16 环境与节奏
适用于 uptrend、range；每日盘后扫描。

## 17 A股约束
T+1：当日买入的股份当日不可卖，触发退出时记 `T1_NOT_SELLABLE`，顺延到可卖日。涨跌停价按 market_rules 计算（主板 10%、创业板和科创板 20%、ST 5%；注册制新股上市前 5 日无涨跌幅限制），一字封板按执行层原因 `LIMIT_LOCKED` 处理（写明 direction），不写成 veto。停牌记 `SUSPENDED`，可交易性、ST、退市整理由 G-01 处理，风险公告由 N-01 处理（均由系统挂载，本卡不重复写）。整手：科创板 ≥ 200 股、超出部分按 1 股递增；其余板块 100 股整数倍；零股须一次性卖出。

## 18 成本与滑点（estimate）
佣金按用户费率，单笔最低 5 元，双边计；印花税仅卖出 0.05%；过户费 0.001%（双边）；滑点 `p.slippage_bp`（estimate）；冲击成本按 plan 2.13 分档（0/5/15/30/60bp），参与率 > 2% 标“容量受限”。

## 20 冲突
与 S-03 互斥（同标的同日）；与 H-01 并列。 一律并列展示，不合并结论。

## 22 参数（hypothesis；slippage_bp 为 estimate）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| min_boards | int | 2 | 1 | 5 | 1 |
| vol_ratio | float | 1.5 | 1.2 | 3.0 | 0.1 |
| stop_pct | float | 0.05 | 0.03 | 0.1 | 0.01 |
| max_hold | int | 5 | 3 | 10 | 1 |
| slippage_bp | float | 10.0 | 0.0 | 50.0 | 1.0 |

## 23 当前不可导入原因与引擎需补能力
- QFQ-2 `plan.breakout_level_qfq`（已裁定，未实现）
- RUL-3 按板块换算的近涨停阈值

## 复核记录（相对 DeepSeek 原稿）
1. E1 时序已修正
2. 动态 ref 已删除，改为 QFQ-2
3. 原稿“板块背离降权”在 DSL 中没有降权语义，已删除
4. 原稿 `p_sector_max` 属于组合层，已删除
5. 原稿收盘封板样本被排除，改为记录统计
