# T-04 布林外轨回归T `t_boll_revert` — 知识卡 v1（T-R16 第二批）

> **当前状态：不可导入**（83a66cd 裁定后，本轮只写知识内容，不补 golden，不实现引擎）。下面的 expr 是设计层规则，**不是**当前可以导入的 schema；标“拟议”的字段、函数、语义在契约中还不存在，不代表现有能力或新的裁定。
> 初稿：DeepSeek（`team/reports/deepseek/T-R16/T-04.md`，未核实草稿），本文为研究员逐条复核后的版本。来源：通用规则组合，无外部来源。阈值均为 hypothesis，不含收益、回测或覆盖率数字。

## 1 身份
key `t_boll_revert`；category `intraday_t`；horizons `[intraday_t]`；risk_level `normal`。

## 3 假设、反证与维度
- why_it_works（hypothesis）：日线布林带处于收敛状态时，盘中价格触及外轨，更可能是短期噪声，有向中轨回归的倾向；用底仓做反向T。
- falsified_by：1) 盘后统计中，触及外轨后当日回到中轨方向（回补带）的比例不高于基线；2) 扣费后单腿结果中位数 ≤ 0；3) 带宽不在收敛区间时结论与收敛区间相同（说明收敛条件无效）。
- 维度：technical 为 core；sector_market 为 veto（downtrend 时不做 buy_first）；news 由 N-01 系统挂载。

## 4 标的范围
持有合规可卖底仓的主板、创业板、科创板证券，上市满 120 个交易日。

## 5 数据（时点 / 单位 / 复权 / 预热）
| 键 | 频率 | 单位 | 复权 | 可得时点 | 状态 |
|---|---|---|---|---|---|
| f.boll_bw20_pct120 | 日 | ratio | qfq | T−1 盘后 | 已注册 |
| f.close_qfq | 日 | 元 | qfq@as_of | T−1 盘后 | 已注册 |
| 布林 %b（拟议，FEA-2） | 日或盘中 | 比值 | qfq | — | 未注册 |
| f.vwap_intraday / f.vwap_dev / f.intraday_sigma | 盘中 1m | 元 / ratio / ratio | none（当日） | 本 bar 结束后 | 已注册；1 分钟历史覆盖未核实（DAT-1） |
预热：日线 140 根有效 K（布林 20 + 120 日分位）+ 当日 30 根 1 分钟 bar；不足时 `insufficient_data`，不产生候选。数据缺失：日线特征缺失 → `insufficient_data`；盘中缺失 → `DATA_STALE`。

## 7 规则（设计层定稿；未定的部分标 拟议 / 待定）
| id | role | expr | 说明 |
|---|---|---|---|
| E1 | entry | `f.boll_bw20_pct120 <= p.bw_th` | 日线收敛（T−1 盘后值） |
| E2 | entry（buy_first） | `f.vwap_intraday <= (ma(f.close_qfq, 20) - p.band_k * std(f.close_qfq, 20)) * (1 + p.touch)` | 盘中均价触及下轨；带由 T−1 及以前的 qfq 收盘计算，口径见 RUL-5 |
| E3 | entry（sell_first） | `f.vwap_intraday >= (ma(f.close_qfq, 20) + p.band_k * std(f.close_qfq, 20)) * (1 - p.touch)` | 触及上轨 |
| C1 | counter | `f.boll_bw20_pct120 > p.bw_th` | 带宽扩张，可能是趋势启动（与 W-02 冲突） |
| X1 | exit（回补） | `between(f.vwap_dev, -p.revert_band, p.revert_band)` | 回到当日均价附近 |
| X2 | exit（止损） | `f.vwap_intraday <= (ma(f.close_qfq, 20) - (p.band_k + p.stop_add) * std(f.close_qfq, 20))` | buy_first 方向继续破位止损（sell_first 对称） |
| X-T | exit（时间） | `ctx.now_hhmm >= p.time_stop_hhmm` | 日终了结 |
- 原稿 `ctx.last_price <= ctx.cost_price_qfq - 1.5 * atr(14)` 把做T单腿止损和持仓成本止损混在一起，已改为基于带宽的 X2。
- 原稿 `ctx.holding_days >= 3` 不适用于日内T，已删除。

## 8–10 执行与仓位
T 腿数量 ≤ `p.t_ratio` × `ctx.sellable_qty`，按整手规则取整；同一证券每天最多 `p.max_t_per_day` 次；一笔 T 结束后持仓数量回到原值，不新增净敞口。日终未回补的腿按 X-T 了结（规则设计；执行配对见 ENG-1）。

## 11 验证（本轮不写 golden）
方法 `fixture`、`trigger_stats` + 盘后重放：触发后回补率、单腿扣费后结果、日终未回补率，均以 `Stat` 输出并标“模拟”；时间切分样本外，`min_n=30`。对照组为不加收敛条件的触轨样本。

## 14 不可执行原因
`NO_POSITION`、`T1_NOT_SELLABLE`、`LIMIT_LOCKED`（buy 或 sell 方向）、`SUSPENDED`、`DATA_STALE`、`NON_TRADING_TIME`；盘后统计模式下只做统计，不产生不可执行原因。

## 15–16 环境与节奏
适用于 range；节奏：盘后重放统计。

## 17 A股约束
**做T约束**：只用 T−1 日及以前形成的合规可卖底仓（`ctx.sellable_qty > 0`）；严禁当日新买入的股份当日卖出，也不为了做T当日开新仓；两腿配对语义（ENG-1）未实现，**两腿未配对时不可执行**，只能 `post_close_stats`。涨跌停价按 market_rules 计算（主板 10%、创业板和科创板 20%、ST 5%；注册制新股上市前 5 日无涨跌幅限制），一字封板按执行层原因 `LIMIT_LOCKED` 处理（写明 direction），不写成 veto。停牌记 `SUSPENDED`，可交易性、ST、退市整理由 G-01 处理，风险公告由 N-01 处理（均由系统挂载，本卡不重复写）。整手：科创板 ≥ 200 股、超出部分按 1 股递增；其余板块 100 股整数倍；零股须一次性卖出。

## 18 成本与滑点（estimate）
佣金按用户费率，单笔最低 5 元，双边计；印花税仅卖出 0.05%；过户费 0.001%（双边）；滑点 `p.slippage_bp`（estimate）；冲击成本按 plan 2.13 分档（0/5/15/30/60bp），参与率 > 2% 标“容量受限”。

## 20 冲突
与 W-02（收敛后突破）在带宽扩张时方向相反；与 T-01 同日同证券只记一次T。 一律并列展示，不合并结论。

## 22 参数（hypothesis；slippage_bp 为 estimate）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| bw_th | float | 0.3 | 0.1 | 0.4 | 0.05 |
| band_k | float | 2.0 | 1.5 | 2.5 | 0.25 |
| touch | float | 0.002 | 0.0 | 0.005 | 0.001 |
| revert_band | float | 0.005 | 0.002 | 0.01 | 0.001 |
| stop_add | float | 0.5 | 0.25 | 1.0 | 0.25 |
| t_ratio | float | 0.3 | 0.1 | 0.5 | 0.05 |
| max_t_per_day | int | 1 | 1 | 2 | 1 |
| slippage_bp | float | 10.0 | 0.0 | 50.0 | 1.0 |
| time_stop_hhmm | 待定（RUL-2） | 14:50 | — | — | — |

## 23 当前不可导入原因与引擎需补能力
- ENG-1 两腿配对（未配对时不可执行）
- ENG-2 入场条件中引用 ctx 字段
- ENG-4 盘中实时求值（C(5) 条件满足前只做盘后统计）
- RUL-2 时刻类参数类型
- RUL-4 盘中 `ref`、`for N bars` 的粒度（bar 还是 day）
- FEA-2 布林 %b（可选；不登记时用 ma 和 std 组合，DSL 长度 ≤ 300 字符）
- DAT-1 1 分钟覆盖
- RUL-5 日线 qfq 带与盘中价的口径

## 复核记录（相对 DeepSeek 原稿）
1. 原稿称“只依赖已有特征”，但需要盘中价，DAT-1 未验证，已改正
2. 原稿止损混入持仓成本与 ATR，已改为基于带宽
3. 原稿时间止损按日计，已删除
4. 口径：qfq@as_of 下当日价格不复权，与 T−1 及以前的 qfq 序列可比，但需要裁定（RUL-5）
