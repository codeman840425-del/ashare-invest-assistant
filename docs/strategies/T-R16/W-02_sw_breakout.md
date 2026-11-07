# W-02 收敛放量突破 `sw_breakout` — 知识卡 v1（T-R16 首批）

> **当前状态：不可导入**（83a66cd 裁定：本批不补卡/golden，实现 MVP 后再议；文中做T配对、null 与组合约束、新特征等“待定”项一律暂停）。下文“可进入模板”仅表示未来潜力。

> **标签：未来可进入模板，当前不可导入**（所用特征均在 feature_spec 中已注册；DSL 已按白名单复核）。突破位用 `plan.breakout_level_qfq`，实现 MVP 后可用。初稿来自 DeepSeek（`team/reports/deepseek/T-R16/W-02.md`，未核实草稿），本文为复核后版本。阈值均为 hypothesis；来源：通用规则组合，无外部来源；不含收益数字。

## 1 身份
key `sw_breakout`；category `momentum`；horizons `[swing]`（观察窗 3–10 日，最长持有 `p.max_hold` 日）。

## 3 假设与维度
- why_it_works（hypothesis）：布林带宽处于长期低分位，说明波动收敛；此时放量创 20 日收盘新高，往往是新一段波动的起点。量价同时确认可以减少无量假突破。
- falsified_by：① 收敛 + 放量突破的样本中，3 日内跌回突破位 3% 以下的比例与随机突破基准没有差异；② 样本外 10 日扣费超额中位数 ≤ 0；③ 参数邻域（分位阈值 0.1–0.3、放量倍数 1.3–2.0）内结论符号翻转。
- 维度：technical 为 core；sector_market 为 veto（`downtrend`）；news 为 veto（N-01，系统挂载）。原稿把 `f.main_net_20d` 列为辅助：资金类特征未验证，已删除。

## 5 数据（均为日线，T 日盘后可得）
f.close_qfq（qfq@as_of）；f.boll_bw20_pct120；f.amount、f.amount_20d_avg（none，单位元）；f.list_days；f.market_regime。
预热：布林 20 根 + 120 日分位 → **140 根有效日 K**（停牌日不计）；不足时 `insufficient_data`。

## 7 规则
| id | role | expr |
|---|---|---|
| E1 | entry | `f.boll_bw20_pct120 <= p.bw_pct120_th` |
| E2 | entry | `f.close_qfq > ref(highest(f.close_qfq, 20), 1)`（高于前 20 日最高收盘，不含当日） |
| E3 | entry | `f.amount >= f.amount_20d_avg * p.vol_mult` |
| F1 | filter | `f.amount_20d_avg >= p.min_amount` |
| F2 | filter | `f.list_days >= p.min_list_days` |
| V1 | veto | `f.market_regime == 'downtrend'` |
| C1 | counter | `pct_change(f.close_qfq, 1) > 0.095`（突破当日接近涨停，次日成交与追高风险大；主板阈值，创业板和科创板按 market_rules 换算，**待定**） |
| I1 | invalidation | `f.close_qfq < plan.entry_price_qfq * (1 - p.fail_pct) within 3 days`（突破失败） |
| X1 | exit（止损） | `f.close_qfq <= plan.entry_price_qfq * (1 - p.stop_pct)` |
| X2 | exit | `f.close_qfq < ma(f.close_qfq, 10) for 2 days` |
| X3 | exit（时间） | `ctx.holding_days >= p.max_hold` |
| X4 | exit（时间止损） | `ctx.holding_days >= 3 and ctx.max_r_reached < 0.5` |
- 原稿各处的改动：
  - V1（停牌、ST、上市天数）→ G-01 和 F2 处理。
  - V3（公告）→ N-01 系统挂载，本卡不重复写。
  - V4（`f.limit_locked_up` 作为 veto）→ 改为执行层原因 `LIMIT_LOCKED`。
  - 原稿 `highest(...)[1]` 的下标写法不在 DSL 内 → 改为 `ref(..., 1)`。
  - 原稿 C2/X3 写成 `... not (...) for 3 days`，DSL 语义不清 → 改为 X4。
  - 原稿 X5（公告）→ N-01 处理。
- X5 跌回突破位（实现 MVP 后）：`f.close_qfq < plan.breakout_level_qfq * (1 - p.fail_pct)`（83a66cd 裁定）；本卡在 MVP 前不可导入，不以入场价替代突破位。

## 8–10 执行与仓位
T 日盘后确认，T+1 开盘价模拟入场；信号有效 1 个交易日。止损价截断到涨跌停价之内。仓位按 RC2/RC3 建议。

## 11 验证
`fixture`、`trigger_stats`、`tracking_sim`；horizon_days `[3,10]`；`min_n=30`；基准：中证全指或所属行业指数；对照组为“无收敛条件的 20 日新高”样本。正式卡导入前需补 ≥ 6 个虚构 golden，包括 140 根预热不足和停牌跨越的用例。

## 14 不可执行原因
`LIMIT_LOCKED`（buy 方向：突破次日一字涨停；sell 方向：一字跌停）、`SUSPENDED`、`T1_NOT_SELLABLE`、`KEY_DATA_MISSING`、`NEW_LISTING`、`ST_OR_DELISTING`。

## 15–17 环境 / 节奏 / A股约束
适用于 uptrend、range；每日盘后扫描。T+1 规则同 S-01。注册制新股上市前 5 日没有涨跌幅限制，但 F2 已经把这段时间排除在外。整手：科创板 ≥ 200 股、按 1 股递增，其余板块 100 股整数倍。

## 18 成本（estimate）
佣金按用户费率，单笔最低 5 元；印花税仅卖出 0.05%；过户费 0.001%；`slippage_bp` 15（突破日流动性偏紧，取 S-01 的 1.5 倍）；冲击成本按 plan 2.13 分档。

## 20 冲突
与 W-01（回踩买入）同标的同日都触发时并列展示；与 H-01 并列展示，不合并。

## 22 参数（hypothesis）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| bw_pct120_th | float | 0.2 | 0.05 | 0.4 | 0.05 |
| vol_mult | float | 1.5 | 1.2 | 3.0 | 0.1 |
| fail_pct | float | 0.03 | 0.01 | 0.05 | 0.01 |
| stop_pct | float | 0.05 | 0.03 | 0.10 | 0.01 |
| max_hold | int | 20 | 10 | 40 | 5 |
| min_amount | float | 50000000.0 | 10000000.0 | 500000000.0 | 10000000.0 |
| min_list_days | int | 120 | 60 | 250 | 10 |
| slippage_bp（estimate） | float | 15.0 | 0.0 | 50.0 | 1.0 |

## 复核记录
key 与 name 已改正；category 已归入枚举；下标写法已改为 `ref`；veto 与执行层原因已分开；公告与可交易性交还 G-01、N-01；“未站稳”时间修饰已改写；突破位改用 `plan.breakout_level_qfq`（MVP 后）。

## 缺口交叉引用
见 [engine_gaps.md](engine_gaps.md)：QFQ-2, RUL-3。
