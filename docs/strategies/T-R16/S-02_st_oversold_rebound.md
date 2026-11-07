# S-02 超跌反弹 `st_oversold_rebound` — 知识卡 v1（T-R16 第二批）

> **当前状态：不可导入**（83a66cd 裁定后，本轮只写知识内容，不补 golden，不实现引擎）。下面的 expr 是设计层规则，**不是**当前可以导入的 schema；标“拟议”的字段、函数、语义在契约中还不存在，不代表现有能力或新的裁定。
> 初稿：DeepSeek（`team/reports/deepseek/T-R16/S-02.md`，未核实草稿），本文为研究员逐条复核后的版本。来源：通用规则组合，无外部来源。阈值均为 hypothesis，不含收益、回测或覆盖率数字。

## 1 身份
key `st_oversold_rebound`；category `reversal`；horizons `[short]`；risk_level `normal`。

## 3 假设、反证与维度
- why_it_works（hypothesis）：短期跌幅过大、RSI 超卖后出现收盘企稳，抛压暂时出清，常见 1–5 日技术性反弹。
- falsified_by：1) 样本外信号后 3 日扣费超额中位数 ≤ 0；2) 企稳确认组与未确认组没有差异（说明企稳条件无效）；3) downtrend 环境下的胜率与 range 相同（说明环境否决无效）。
- 维度：technical 为 core；sector_market 为 veto（downtrend）；news 由 N-01 系统挂载。

## 4 标的范围
主板、创业板、科创板；上市满 `p.min_list_days`；20 日均额 ≥ `p.min_amount`。

## 5 数据（时点 / 单位 / 复权 / 预热）
| 键 | 频率 | 单位 | 复权 | 可得时点 | 状态 |
|---|---|---|---|---|---|
| f.rsi14 | 日 | 0–100 | qfq | T 盘后 | 已注册 |
| f.close_qfq / f.low_qfq / f.high_qfq | 日 | 元 | qfq@as_of | T 盘后 | 已注册 |
| f.amount / f.amount_20d_avg | 日 | CNY | none | T 盘后 | 已注册 |
| f.market_regime | 日 | enum | — | T 盘后 | G-02 |
预热：RSI 预热 28 根；取 30 根有效日 K；不足时 `insufficient_data`，不产生候选。数据缺失：`f.market_regime` 缺失 → 买入方向 `KEY_DATA_MISSING`。

## 7 规则（设计层定稿；未定的部分标 拟议 / 待定）
| id | role | expr | 说明 |
|---|---|---|---|
| E1 | entry | `f.rsi14 < p.rsi_os within 3 days` | 近 3 日出现过超卖 |
| E2 | entry | `pct_change(f.close_qfq, 5) <= -p.drop_5d` | 短期跌幅 |
| E3 | entry | `f.close_qfq > ref(f.high_qfq, 1)` | 收盘收复前日高点，企稳确认 |
| F1 | filter | `f.amount_20d_avg >= p.min_amount and f.list_days >= p.min_list_days` |  |
| V1 | veto | `f.market_regime == 'downtrend'` |  |
| C1 | counter | `f.close_qfq < ref(f.close_qfq, 1) and f.amount > f.amount_20d_avg * 1.5` | 放量续跌 |
| I1 | invalidation | `f.close_qfq < ref(lowest(f.low_qfq, 5), 1)` | 收盘跌破前 5 日最低，反弹失败 |
| X1 | exit（止损） | `f.close_qfq <= plan.entry_price_qfq * (1 - p.stop_pct)` | 当前可用 |
| X1b | exit（止损，实现 MVP 后） | `f.close_qfq < plan.stop_loss_qfq` | 结构止损 = 入场前 5 日最低 qfq（QFQ-1） |
| X2 | exit（止盈） | `f.close_qfq >= plan.entry_price_qfq * (1 + p.tp_pct)` |  |
| X3 | exit | `f.rsi14 > p.rsi_exit and f.close_qfq < ref(f.close_qfq, 1)` | 反弹衰竭 |
| X4 | exit（时间） | `ctx.holding_days >= p.max_hold` |  |

## 8–10 执行与仓位
T 日盘后确认，T+1 开盘价模拟入场，信号有效 1 个交易日；止损价截断到涨跌停价之内；仓位按 RC2/RC3 建议。

## 11 验证（本轮不写 golden）
`fixture`、`trigger_stats`、`tracking_sim`；horizon_days [1,3,5]；`min_n=30`；基准用所属行业指数或中证全指。

## 14 不可执行原因
`LIMIT_LOCKED`（buy：一字涨停；sell：一字跌停，`direction=sell`）、`SUSPENDED`、`T1_NOT_SELLABLE`、`KEY_DATA_MISSING`、`NEW_LISTING`、`ST_OR_DELISTING`。

## 15–16 环境与节奏
适用于 range；uptrend 可用；downtrend 否决。每日盘后扫描。

## 17 A股约束
T+1：当日买入的股份当日不可卖，触发退出时记 `T1_NOT_SELLABLE`，顺延到可卖日。涨跌停价按 market_rules 计算（主板 10%、创业板和科创板 20%、ST 5%；注册制新股上市前 5 日无涨跌幅限制），一字封板按执行层原因 `LIMIT_LOCKED` 处理（写明 direction），不写成 veto。停牌记 `SUSPENDED`，可交易性、ST、退市整理由 G-01 处理，风险公告由 N-01 处理（均由系统挂载，本卡不重复写）。整手：科创板 ≥ 200 股、超出部分按 1 股递增；其余板块 100 股整数倍；零股须一次性卖出。

## 18 成本与滑点（estimate）
佣金按用户费率，单笔最低 5 元，双边计；印花税仅卖出 0.05%；过户费 0.001%（双边）；滑点 `p.slippage_bp`（estimate）；冲击成本按 plan 2.13 分档（0/5/15/30/60bp），参与率 > 2% 标“容量受限”。

## 20 冲突
与 S-01（强势回踩）、W-02（突破）方向相反时并列；与 H-01 并列。 一律并列展示，不合并结论。

## 22 参数（hypothesis；slippage_bp 为 estimate）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| rsi_os | float | 30.0 | 20.0 | 35.0 | 1.0 |
| drop_5d | float | 0.08 | 0.05 | 0.15 | 0.01 |
| stop_pct | float | 0.03 | 0.02 | 0.05 | 0.005 |
| tp_pct | float | 0.06 | 0.04 | 0.1 | 0.01 |
| rsi_exit | float | 55.0 | 50.0 | 65.0 | 1.0 |
| max_hold | int | 5 | 3 | 10 | 1 |
| min_amount | float | 50000000.0 | 10000000.0 | 500000000.0 | 10000000.0 |
| min_list_days | int | 60 | 30 | 120 | 10 |
| slippage_bp | float | 10.0 | 0.0 | 50.0 | 1.0 |

## 23 当前不可导入原因与引擎需补能力
- QFQ-1 `plan.stop_loss_qfq`（已裁定，未实现，实现 MVP 后）

## 复核记录（相对 DeepSeek 原稿）
1. 原稿 X1 `f.close_qfq < plan.stop_loss` 口径混用，已改为 entry_price_qfq，另加 MVP 后的 stop_loss_qfq
2. 原稿企稳条件“收阳且高于当日最低”几乎每天都成立，已改为收复前日高点
3. 原稿缺少短期跌幅条件，已补 E2
4. 原稿 C1 把风险公告写成 counter，已交给 N-01
5. 原稿仓位参数属于 RC 层，已删除
6. 原稿 I1（跌破入场价 3%）与 X1 重复，已改为跌破前 5 日最低（用 ref 避开包含当日导致恒不成立）
