# S-01 强势股短线回踩 `st_pullback_ma` — 知识卡 v1（T-R16 首批）

> **标签：可进入模板（全市场分支）**，但有 1 项待定（结构止损的口径），定稿前不写正式 `strategy-card` 块。初稿来自 DeepSeek（`team/reports/deepseek/T-R16/S-01.md`，未核实草稿），本文是研究员复核后的版本。阈值均为 hypothesis；来源：通用规则组合，无外部来源；不含收益数字。
> 数据：日线价量已实测（catalog）；截面分位 `rank_pct` 在 DSL 白名单内。行业内排名分支依赖 `f.sw_l1`（来源待 T003），首版不用。

## 1 身份
key `st_pullback_ma`；category `momentum`；horizons `[short]`（持有 1–5 个交易日，信号有效 1 个交易日）。

## 3 假设与维度
- why_it_works（hypothesis）：短期强势、均线多头排列的股票，在缩量回踩 MA10 不破时，抛压较轻，趋势容易延续。
- falsified_by：① 样本外信号后 5 日扣费超额的中位数 ≤ 0；② 模拟跟踪 n ≥ 30 后胜率 < 45%；③ 参数邻域（分位 0.7–0.9、缩量系数 0.6–0.8）内结论符号翻转。
- 维度：technical 为 core；sector_market 为 veto（`downtrend`）；news 为 veto（N-01，系统挂载）。原稿把基本面 PIT 键和资金维度当作辅助，已删除，因为它们未验证，且与本逻辑无关。

## 4–5 范围与数据
- 范围：沪深主板、创业板、科创板（北交所不含）；`f.list_days ≥ p.min_list_days`；20 日均成交额 ≥ `p.min_amount`。ST、停牌、新股由 G-01 处理。
- 特征：f.close_qfq / f.low_qfq / f.high_qfq（qfq@as_of，T 日盘后）；f.amount（none，单位元）；f.market_regime（G-02）。
- 预热：MA20 + 20 日涨幅需 21 根，ATR 15 根 → 取 **25 根有效日 K**；停牌日不计入有效 K；不足时 `insufficient_data`。

## 7 规则（DSL 已按白名单与 qfq 口径复核）
| id | role | expr |
|---|---|---|
| E1 | entry | `rank_pct(pct_change(f.close_qfq, 20)) >= p.rs_pct` |
| E2 | entry | `ma(f.close_qfq, 5) > ma(f.close_qfq, 10) and ma(f.close_qfq, 10) > ma(f.close_qfq, 20)` |
| E3 | entry | `f.low_qfq <= ma(f.close_qfq, 10) * (1 + p.touch_pct) and f.close_qfq >= ma(f.close_qfq, 10)` |
| E4 | entry | `f.amount < ma(f.amount, 5) * p.shrink_ratio` |
| F1 | filter | `ma(f.amount, 20) >= p.min_amount` |
| F2 | filter | `f.list_days >= p.min_list_days` |
| V1 | veto | `f.market_regime == 'downtrend'` |
| C1 | counter | `pct_change(f.close_qfq, 1) < -0.05`（回踩日单日跌幅大，可能是出货） |
| C2 | counter | `f.amount > ma(f.amount, 20) * 1.5`（放量回落） |
| I1 | invalidation | `ma(f.close_qfq, 5) < ma(f.close_qfq, 10)` |
| X1 | exit | `f.close_qfq < ma(f.close_qfq, 10) for p.exit_confirm_days days` |
| X2 | exit（止损） | `f.close_qfq <= plan.entry_price_qfq * (1 - p.hard_stop_pct)` |
| X3 | exit（时间止损） | `ctx.holding_days >= p.time_stop and ctx.max_r_reached < 1` |
- 回踩日低点止损（原稿 X2 写成 `f.close_qfq < plan.stop_loss`）**待定**：`plan.stop_loss` 存的是不复权价，与 qfq 序列比较属于口径混用（T-R15 ⓪ 的 adjust_mismatch），契约中又没有 `plan.stop_loss_qfq`。定稿前只用 X2 的硬止损。
- 原稿 E5（`close ≤ MA5` 近似回踩）用 E3 的“触及 MA10”代替；原稿 X4（未创新高即时间止损）几乎每天都会成立，已改为 X3。原稿的 X5（大盘转弱减仓）属于 H-01 和风控 RC3 的职责，已删除。

## 8–10 入场 / 退出 / 仓位
T 日盘后确认，最早 T+1 09:30 执行，模拟入场价 = T+1 开盘价；信号有效 1 个交易日，过期作废。止损价截断到涨跌停价之内。仓位按 RC2/RC3 建议，不在本卡内硬编码。

## 11 验证
`fixture`、`trigger_stats`、`tracking_sim`；horizon_days `[1,5]`；`min_n=30`；基准：所属行业指数或中证全指。正式卡需 ≥ 6 个虚构 golden（导入前补）。

## 14 不可执行原因
`LIMIT_LOCKED`（买入方向一字涨停；卖出方向一字跌停，`direction=sell`）、`SUSPENDED`、`T1_NOT_SELLABLE`、`KEY_DATA_MISSING`（`f.market_regime` 缺失时阻断买入草案）、`NEW_LISTING`、`ST_OR_DELISTING`。

## 15–17 环境 / 节奏 / A股约束
适用于 uptrend、range；每日盘后扫描。T+1：买入当日不能卖出，买入当日触发的止损记 `T1_NOT_SELLABLE`。涨跌停按 market_rules 计算。整手：科创板 ≥ 200 股、按 1 股递增，其余板块 100 股整数倍；零股须一次性卖出。

## 18 成本（estimate）
佣金按用户费率，单笔最低 5 元；印花税仅卖出 0.05%；过户费 0.001%；`slippage_bp` 10；冲击成本按 plan 2.13 分档（0/5/15/30/60bp），参与率 > 2% 标“容量受限”。

## 20 冲突
与 S-02（超跌反弹）方向相反时并列展示；与 W-01、H-01 并列展示，不合并。

## 22 参数（hypothesis，slippage 为 estimate）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| rs_pct | float | 0.8 | 0.6 | 0.95 | 0.05 |
| touch_pct | float | 0.01 | 0.0 | 0.03 | 0.005 |
| shrink_ratio | float | 0.7 | 0.5 | 0.9 | 0.05 |
| exit_confirm_days | int | 2 | 1 | 3 | 1 |
| hard_stop_pct | float | 0.08 | 0.05 | 0.12 | 0.01 |
| time_stop | int | 5 | 3 | 10 | 1 |
| min_amount | float | 50000000.0 | 10000000.0 | 500000000.0 | 10000000.0 |
| min_list_days | int | 60 | 30 | 250 | 10 |
| slippage_bp | float | 10.0 | 0.0 | 50.0 | 1.0 |

## 复核记录
1. 原稿 key 与 name 互换、category 不在枚举内：已改正。
2. 原稿用了不在白名单内的 `bars_since_signal`：已删除。
3. 原稿把一字涨停写成 `not_triggered`，应为执行层原因 `LIMIT_LOCKED`：已改正。
4. 原稿把否决规则写成“C1/C2 → vetoed”混在 counter 角色里：已拆分为 veto 与 counter 两类。
5. 原稿结构止损存在口径混用：标为待定。
6. 原稿时间止损每天都会触发：已改写。
7. 原稿“持仓 2–10 日”与短线 1–5 日的定位不一致：已统一为 1–5 日。
**待定**：回踩低点止损的 qfq 口径键（需架构师裁定是否增加 `plan.stop_loss_qfq`）；行业内排名分支（`f.sw_l1`）。
