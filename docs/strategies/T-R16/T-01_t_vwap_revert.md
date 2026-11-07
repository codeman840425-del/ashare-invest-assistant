# T-01 均价偏离回归做T `t_vwap_revert` — 知识卡 v1（T-R16 首批）

> **当前状态：不可导入**（83a66cd 裁定：本批不补卡/golden，实现 MVP 后再议；文中做T配对、null 与组合约束、新特征等“待定”项一律暂停）。下文“可进入模板”仅表示未来潜力。

> **标签：仅知识卡**（不可进入可运行模板）。初稿来自 DeepSeek（`team/reports/deepseek/T-R16/T-01.md`，未核实草稿），本文是研究员复核后的版本，改动见末节。所有阈值均为 hypothesis，不含收益或回测数字。来源：通用规则组合，无外部来源。
> 不能进模板的原因：① 盘中快照延迟只有小样本实测，不满足 C(5) 的开放条件；② 1 分钟历史覆盖**未核实**，`f.vwap_intraday`、`f.vwap_dev`、`f.intraday_sigma` 的单位与口径【待 T003】；③ 引擎已有 `t_leg`（plan 2.5.11A），但同一笔 T 的卖腿与买腿如何配对、回补怎么写成规则，plan 没有给示例（待架构师）。目前只能按 `scan.mode: post_close_stats` 做盘后统计，不产生候选、草案或通知。

## 1 身份
key `t_vwap_revert`；category `intraday_t`；horizons `[intraday_t]`；risk_level `normal`。

## 3 假设与维度
- why_it_works（hypothesis）：持有底仓的股票在日内相对当日 VWAP 出现显著偏离（以当日已实现波动归一化）后，有向 VWAP 回归的倾向；顺着偏离的反方向做一次T，可以在不改变持仓数量的前提下降低持仓成本。
- falsified_by：① 盘后统计中，触发后到 14:50 前回到 VWAP 回补带的比例，不高于同股同日随机时点的基线；② 扣除往返成本后，单腿结果的中位数 ≤ 0；③ 14:50 时仍未回补的比例 > 30%（hypothesis）。
- 维度：technical 为 core；sector_market 为 veto（G-02 判定 `downtrend` 时不做 `buy_first`）；news 为 veto（N-01 由系统挂载，本卡不重复写）。capital、fundamental、sentiment 不参与（原稿把 `f.main_net_20d` 和 vwap 偏离归入资金、情绪维度，已删除）。

## 4 标的范围
**只针对已有合规可卖底仓的证券**：`ctx.sellable_qty > 0`，且可卖部分只来自 T−1 日及以前买入的持仓。A 股当日新买入的股份当日不能卖出：严禁“当日新仓卖出”，也不允许为了做T当日先开新仓。ST、停牌、退市整理由 G-01 处理；北交所不在范围内。

## 5 数据（PIT）
| 键 | 频率 | 复权 | 可得时点 | 状态 |
|---|---|---|---|---|
| f.vwap_intraday / f.vwap_dev / f.intraday_sigma | 盘中 1m | none（当日不复权） | 本 bar 结束后 | 单位与口径【待 T003】，1 分钟历史覆盖未核实 |
| f.close_qfq（前收） | 日线 | qfq@as_of | T−1 收盘后 | 已实测 |
| f.limit_up_price / f.limit_down_price | 日 | none | T 日开盘前 | 由 market_rules 计算 |
| f.market_regime | 日 | — | T−1 盘后 | G-02 |
预热：σ 至少需要当日已完成的 30 根 1 分钟 bar（hypothesis），30 根之前（约 10:00 前）不触发。

## 7 规则（只在盘后重放时求值；DSL 写法待 `t_leg` 机制确定后才能定稿）
- E-S（sell_first 上偏）：`f.vwap_dev >= p.k * f.intraday_sigma and ctx.now_hhmm < p.last_entry_hhmm`，前提是 `ctx.sellable_qty > 0`（ctx 字段只能用在 hold/exit 角色，入场条件怎么表达**待定**）。
- E-B（buy_first 下偏）：`f.vwap_dev <= -p.k * f.intraday_sigma`，同时要求有足够的可卖底仓，用于当日卖出等量旧股完成回补；新买入的股份当日不可卖。
- X-R（回补）：`between(f.vwap_dev, -p.revert_band * f.intraday_sigma, p.revert_band * f.intraday_sigma)`。
- X-T（时间止损，止损类）：`ctx.now_hhmm >= p.time_stop_hhmm`，此时仍未回补就按规则了结当日的 T 腿。
- X-S（偏离扩大止损）：偏离达到 `p.stop_mult × k × σ`（abs 不在白名单内，上下两侧分开写）。
- C1（反证，趋势日）：日内涨跌幅超过 `p.trend_abs_pct`，用 `ctx.last_price` 相对前收计算；**不得使用当日收盘价**，原稿 `pct_change(f.close_qfq,1)` 在盘中会用到未来数据，已删除。
- I1（失效）：`f.market_regime == 'downtrend'`，不做 `buy_first`。
冲突处理：H-01 给出 weakening 或 exit 时，压制 `buy_first`，两张卡的结论并列展示。

## 8–10 入场 / 退出 / 仓位
同一证券每天最多做 `p.max_t_per_day` 次；T 腿数量 ≤ `p.t_ratio` × 可卖底仓，按 market_rules 的整手规则取整（科创板 ≥ 200 股、按 1 股递增；其余板块 100 股整数倍）。一笔 T 结束后持仓数量回到原值，不新增净敞口。

## 11 验证
方法：`fixture`、`trigger_stats`，加盘后重放统计（回补率、单腿扣费后结果、14:50 未回补率，均以 `Stat` 输出并标“模拟”）。按时间切分做样本外检验，`min_n=30`。

## 14 不可执行原因
`NO_POSITION`（无底仓）、`T1_NOT_SELLABLE`（可卖不足）、`LIMIT_LOCKED`（买卖两个方向）、`SUSPENDED`、`DATA_STALE`、`NON_TRADING_TIME`；盘后统计模式下只做统计，不产生不可执行原因。

## 15–16 环境与节奏
适用于 range、uptrend；趋势日不做。节奏：盘后重放统计；开放盘中运行需满足 C(5) 条件并经用户确认。

## 17 A股约束
T+1；做T必须有底仓（`sell_first` 卖的是旧股，`buy_first` 当日买入的股份当日不可卖，回补靠卖出等量旧股）；涨跌停价按 market_rules 计算，注册制新股上市前 5 日无涨跌幅；北交所不在范围内。

## 18 成本与滑点（estimate）
佣金按用户费率，单笔最低 5 元，双边计；印花税仅卖出 0.05%；过户费 0.001%；滑点 10bp；冲击成本按 plan 2.13 的 5 档（0/5/15/30/60bp）。原稿自编的 5/10/20bp 档位已删除。成本门槛：`k × σ` 对应的价差须 ≥ `p.min_edge_cost_mult` × 往返成本。

## 20 冲突
与 W-01、H-01 并列展示，不合并；G-01、N-01 由系统挂载。

## 22 参数（hypothesis）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| k | float | 2.0 | 1.0 | 4.0 | 0.5 |
| revert_band | float | 0.5 | 0.2 | 1.0 | 0.1 |
| stop_mult | float | 1.5 | 1.0 | 3.0 | 0.5 |
| trend_abs_pct | float | 0.05 | 0.02 | 0.08 | 0.01 |
| t_ratio | float | 0.3 | 0.1 | 0.5 | 0.1 |
| max_t_per_day | int | 1 | 1 | 2 | 1 |
| min_edge_cost_mult | float | 2.0 | 1.0 | 5.0 | 0.5 |
| time_stop_hhmm / last_entry_hhmm | — | 14:50 / 14:30 | — | — | — |
时刻类参数的类型不在 plan 2.5.14 D 节的 int/float/bool/enum 中，**待定**（建议用 enum）。

## 复核记录（相对 DeepSeek 原稿）
1. 原稿 key 与 name 互换，category 不在枚举内：已改正。
2. 原稿使用 `abs()`，不在 DSL 白名单内：已改为 between 或上下两侧分开写。
3. 原稿用 `pct_change(f.close_qfq,1)` 判趋势日，盘中会用到当日收盘价（未来数据）：已改为基于 `ctx.last_price`。
4. 原稿在入场条件里用 ctx 字段，当前 DSL 不允许：标为待定。
5. 原稿把 counter 角色写成“回补”：已改为 exit 类的回补规则，counter 只放反证。
6. 原稿冲击成本档位是自编的：已改为 plan 2.13 的分档。
7. 原稿把跌停写成 vetoed：已改为执行层原因 `LIMIT_LOCKED`。
8. 原稿把涨跌停价标为 qfq：已改为 none。
9. 原稿把资金、情绪辅助维度写进卡里：已删除。
**暂停（83a66cd，等 MVP）**：t_leg 配对机制、入场条件中 ctx 字段的用法、时刻类参数类型、vwap 类特征的单位与延迟实测。

## 缺口交叉引用
见 [engine_gaps.md](engine_gaps.md)：ENG-1, ENG-2, ENG-4, RUL-2, DAT-1。
