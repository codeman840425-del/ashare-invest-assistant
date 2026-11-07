# W-01 波段·均线趋势回踩 `sw_ma_trend_pullback` — 正式卡 v1（T-R15）

> 正式卡（非 catalog 草案、非 `_template.md` 示例）。导入格式：plan 2.5.14 A 节三个带标签块（`strategy-card` / `strategy-spec` / `validation`），导入器只读这三块，正文存为 `narrative`。
> 夹具中全部价格、成交额、持仓与场景均为**虚构**；`688018.SH`、`688073.SH`、`300364.SZ`、`301218.SZ` 只作“科创板/创业板”场景标签写在 `desc` 中，不代表、不暗示任何真实行情。夹具期望值由 `golden/gen_T-R15.py` 本地确定性求值生成并自检。
> 结论只由规则决定；AI 只对规则结论做中文解释，不改变 state/action。六个维度冲突时并列展示，不合并为单一结论（P4）。

## 规则摘要
- **入场（全部为真才 `entry_ok`）**：E1 MA20>MA60 连续 `trend_days` 根有效日 K；E2 近 3 日最低价 ≤ MA20×(1+`pullback_pct`) 且收盘 > MA20；E3 收盘 ≥ 60 日最高收盘×(1−`max_dd_from_high`)；过滤 F1 20 日均成交额 ≥ `min_amount`；F2 上市交易日数 ≥ `min_list_days`；F3 **成本过滤**：ATR14/收盘（bp）≥ `min_edge_cost_mult`×(2×`slippage_bp`+`fixed_cost_bp`)，一倍 ATR 的波动覆盖不了往返成本的若干倍则不出买入。
- **否决**：V1 大盘 `downtrend`；V2 最近一期净利同比 < `np_yoy_floor`；V4 RSI14 > `rsi_overheat`。否决数据缺失（`veto_unknown`）→ 状态照常求值，买入方向计划草案由 `KEY_DATA_MISSING` 阻断，解除 = 字段在新快照中非空。
- **退出（任一为真 → `exit_signal`/sell）**：X1 收盘连续 `exit_confirm_days` 日低于 MA20；X2 盘中价 ≤ 计划止损；X3 持有 ≥ `time_stop` 日且未达 1R；X4 收盘跌破前 20 日最低价；X5 达 `trail_trigger_r`R 后收盘（qfq）跌破 `ctx.highest_close_since_entry_qfq`−`trail_atr_mult`×ATR14；X6 收盘（qfq@T）≤ 止损价 max2(`plan.entry_price_qfq`−`atr_mult`×ATR14, 前 20 日最低价)。
- **优先级**：持有中 → 只看 exit（exit > hold）；未持有 → veto > insufficient_data > entry_ok > not_triggered。G-01/N-01 由系统挂载，见 `system_components_T-R15.md`。

## 时点 / 单位 / 复权 / 预热
- 日线盘后（`daily_close`）求值，只用 as_of 当日及以前的有效日 K；信号最早 T+1 09:30 执行，模拟入场价 = T+1 开盘价；季报类特征按 plrq 次一交易日 09:30 可见；公告按 2.12.2 次日开盘生效。无未来数据。
- **价格口径（plan 2.5.14 T-R15 裁定⓪）**：全部价格规则统一 qfq，基准日 = as_of（T）：`x_qfq(d)=x(d)×A(d)/A(T)`，A(d) 只用 T 日已可得的除权信息；T 日 qfq 值即不复权值。计划价持久化为不复权，规则只用求值器派生的 `plan.entry_price_qfq`；`ctx.last_price` 只与同为不复权的 `plan.stop_loss` 比较。用 qfq@T 算出的止损价就是 T 日不复权价。成交额 `f.amount` 单位元。ATR 为 Wilder（首值取前 14 个 TR 简单平均，warmup 15）。
- 预热：MA60 + `trend_days`−1 = 64 根（默认），60 日最高 60 根，ATR14 15 根，RSI14 28 根 → **warmup 65 根有效日 K**（按参数上限 120+20−1=139）；停牌日不计入有效 K；不足 → `insufficient_data`。`for N days` 按有效日 K 计数。
- 板块约束：涨跌停价按 `config/market_rules.yaml` 生效段计算（创业板/科创板现行 20%，**注册制新股上市前 5 个交易日无涨跌幅，`f.limit_*_price = null`**，不硬编码 20%）；止损/止盈价截断到次日涨跌停价之内。科创板买入 ≥200 股、200 股以上 1 股递增，其他板块 100 股整数倍；不足一个申报单位的零股卖出须一次性申报（`lot_rule` 在计划确认时按草案 `market_rule_version_id` 校验，不在卡内重算）。T+1：买入当日可卖 0，卖出信号照常、执行层 `T1_NOT_SELLABLE`。

## 成本与滑点（`epistemic: estimate`）
佣金按用户费率（单笔最低 5 元）；印花税卖出 0.05%；过户费双向 0.001%；基础滑点 `slippage_bp` 默认 10bp；冲击成本按参与率 5 档 0/5/15/30/60bp（plan 2.13，待校准），参与率 > 2% 标“容量受限”。`fixed_cost_bp`=8 是 F3 使用的往返固定费率近似值（印花税 5bp + 双边佣金约 2.5bp + 过户费），不进计划价格计算。

## 反证 / 失效
反证（并列展示，不抵消）：行业 20 日弱于大盘、主力 20 日净流出、当日成交额 < 20 日均额一半。失效：MA20 跌破 MA60；大盘转 `downtrend`。研究侧证伪见 `hypothesis.falsified_by`。

```yaml strategy-card
key: sw_ma_trend_pullback
version_no: 1
name: 波段·均线趋势回踩
category: trend
horizons: [swing]
card_id: W-01
risk_level: normal
hypothesis:
  why_it_works: 中期趋势存在惯性；趋势中的回踩不破提供止损距离较近的跟随点
  falsified_by:
    - 研究侧：样本外信号后 20 个交易日扣费超额收益（对所属申万一级行业指数）中位数 ≤ 0
    - 研究侧：参数邻域（ma_fast ±5、pullback_pct ±0.01）内扣费超额符号翻转
    - 模拟跟踪：n ≥ 30 时 5 日胜率 < 45% 且平均超额 < 0
dimensions:
  - {dimension: technical, role: core}
  - {dimension: capital, role: auxiliary}
  - {dimension: fundamental, role: veto}
  - {dimension: sentiment, role: veto}
  - {dimension: sector_market, role: veto}
entry:
  - {ref: E1, text: 20 日均线连续 N 根有效日 K 高于 60 日均线, status: quantified}
  - {ref: E2, text: 近 3 日最低价回到 20 日均线上方 pullback_pct 以内且收盘仍在均线上方, status: quantified}
  - {ref: E3, text: 收盘距 60 日最高收盘回撤不超过 max_dd_from_high, status: quantified}
counter_evidence:
  - {ref: C1, text: 所属行业近 20 日弱于大盘, status: quantified}
  - {ref: C2, text: 近 20 日主力资金净流出, status: quantified}
  - {ref: C3, text: 当日成交额不足 20 日均额一半, status: quantified}
invalidation:
  - {ref: I1, text: 20 日均线跌破 60 日均线, status: quantified}
  - {ref: I2, text: 大盘环境转为下行, status: quantified}
exit:
  - {ref: X2, text: 盘中触及计划止损价（止损类；买入当日由 T1_NOT_SELLABLE 阻断执行）, status: quantified}
  - {ref: X1, text: 收盘连续 exit_confirm_days 日低于 20 日均线, status: quantified}
  - {ref: X4, text: 收盘跌破前 20 日最低价（结构止损）, status: quantified}
  - {ref: X3, text: 持有满 time_stop 日仍未达 1R（时间止损）, status: quantified}
  - {ref: X6, text: 收盘（qfq@T）跌破止损价 max2(建仓价 qfq − atr_mult×ATR14, 前 20 日最低价)（止损类）, status: quantified}
  - {ref: X5, text: 达到 trail_trigger_r R 后收盘跌破入场以来最高收盘 − trail_atr_mult×ATR14（跟踪止盈，入场以来最高收盘按 qfq@T 折算）, status: quantified}
data_needs:
  - {feature_key: f.close_qfq, frequency: daily, adjust: qfq, available_at: T 日日线入库后}
  - {feature_key: f.high_qfq, frequency: daily, adjust: qfq, available_at: T 日日线入库后}
  - {feature_key: f.low_qfq, frequency: daily, adjust: qfq, available_at: T 日日线入库后}
  - {feature_key: f.amount, frequency: daily, adjust: none, available_at: T 日日线入库后}
  - {feature_key: f.list_days, frequency: daily, adjust: none, available_at: T 日开盘前}
  - {feature_key: f.limit_up_price, frequency: daily, adjust: none, available_at: T 日开盘前（无涨跌幅日为 null）}
  - {feature_key: f.limit_down_price, frequency: daily, adjust: none, available_at: T 日开盘前（无涨跌幅日为 null）}
  - {feature_key: f.is_suspended, frequency: daily, adjust: none, available_at: T 日日线入库后（sf）}
  - {feature_key: f.limit_locked_up, frequency: daily, adjust: none, available_at: T 日日线入库后}
  - {feature_key: f.rsi14, frequency: daily, adjust: qfq, available_at: T 日日线入库后}
  - {feature_key: f.main_net_20d, frequency: daily, adjust: none, available_at: T 日盘后（待T003验证）}
  - {feature_key: f.np_yoy_latest, frequency: quarterly, adjust: none, available_at: plrq 次一交易日 09:30}
  - {feature_key: f.market_regime, frequency: daily, adjust: none, available_at: T 日盘后（G-02）}
  - {feature_key: f.ind_rs20, frequency: daily, adjust: none, available_at: T 日盘后}
epistemic:
  hypothesis: hypothesis
  params_schema.trend_days: hypothesis
  params_schema.pullback_pct: hypothesis
  params_schema.max_dd_from_high: hypothesis
  params_schema.exit_confirm_days: hypothesis
  params_schema.atr_mult: hypothesis
  params_schema.time_stop: hypothesis
  params_schema.trail_trigger_r: hypothesis
  params_schema.trail_atr_mult: hypothesis
  params_schema.rsi_overheat: hypothesis
  params_schema.np_yoy_floor: hypothesis
  params_schema.min_amount: hypothesis
  params_schema.min_list_days: hypothesis
  params_schema.min_edge_cost_mult: hypothesis
  params_schema.slippage_bp: estimate
  params_schema.fixed_cost_bp: estimate
  costs.impact_tiers: estimate
universe:
  pool: 持仓 ∪ 自选
  boards: {main: true, chinext: true, star: true, bse: false}
  security_types: [stock]
applicability: {market_regime: [uptrend, range]}
pitfalls:
  - 把下跌趋势中的反弹当回踩（E1、V1 防护）
  - 忽略 T+1：入场当日无法止损
  - 低波动个股的一倍 ATR 覆盖不了往返成本（F3 防护）
  - 一字涨停时规则满足但不可成交（G-01 LIMIT_LOCKED）
costs:
  commission: 用户费率；未导入时默认估算，单笔最低 5 元
  stamp_duty_sell: 0.0005
  transfer_fee: 0.00001
  slippage_bp: 10
  impact_adv_days: 20
  max_participation_pct: 0.02
  impact_tiers: [{max_r: 0.001, bp: 0}, {max_r: 0.005, bp: 5}, {max_r: 0.01, bp: 15}, {max_r: 0.02, bp: 30}, {max_r: null, bp: 60, flag: 容量受限}]
a_share_constraints: 涨跌停按 config/market_rules.yaml 生效段（创业板/科创板现行 20%，注册制新股前 5 日无涨跌幅为 null）；科创板买入 ≥200 股、1 股递增，其余 100 股整数倍；零股卖出一次性申报；T+1；ST/退市整理/停牌/新股由 G-01 处理
validation_summary: {type: rule, window: 未执行, benchmark: 所属申万一级行业指数；对照中证全指, cost_model: plan 2.13 默认（含冲击成本分档）, oos_result: 未验证, trade_log_ref: null}
fit: {effort: low, risk_tolerance_min: 3, experience_min: novice}
```

```yaml strategy-spec
key: sw_ma_trend_pullback
version_no: 1
kind: rule_template
horizons: [swing]
params_schema:
  ma_fast: {type: int, default: 20, min: 10, max: 30, step: 1, desc: 快均线周期, unit: 有效日K}
  ma_slow: {type: int, default: 60, min: 40, max: 120, step: 5, desc: 慢均线周期, unit: 有效日K}
  trend_days: {type: int, default: 5, min: 3, max: 20, step: 1, desc: 趋势持续根数, unit: 有效日K}
  pullback_pct: {type: float, default: 0.02, min: 0.005, max: 0.05, step: 0.005, desc: 回踩距 MA20 容忍比例}
  max_dd_from_high: {type: float, default: 0.15, min: 0.05, max: 0.25, step: 0.01, desc: 距 60 日最高收盘最大回撤}
  exit_confirm_days: {type: int, default: 2, min: 1, max: 5, step: 1, desc: 跌破 MA20 确认根数, unit: 有效日K}
  atr_mult: {type: float, default: 2.0, min: 1.0, max: 4.0, step: 0.5, desc: ATR 止损倍数}
  time_stop: {type: int, default: 40, min: 10, max: 60, step: 5, desc: 时间止损持有日数, unit: 交易日}
  trail_trigger_r: {type: float, default: 2.0, min: 1.0, max: 4.0, step: 0.5, desc: 启动跟踪止盈的 R 倍数}
  trail_atr_mult: {type: float, default: 2.0, min: 1.0, max: 4.0, step: 0.5, desc: 跟踪止盈 ATR 倍数}
  rsi_overheat: {type: float, default: 75.0, min: 65.0, max: 85.0, step: 1.0, desc: RSI14 过热否决阈值}
  np_yoy_floor: {type: float, default: -30.0, min: -80.0, max: 0.0, step: 5.0, desc: 净利同比否决下限, unit: "%"}
  min_amount: {type: float, default: 50000000.0, min: 10000000.0, max: 500000000.0, step: 10000000.0, desc: 20 日均成交额下限, unit: 元}
  min_list_days: {type: int, default: 120, min: 60, max: 250, step: 10, desc: 最少上市交易日数, unit: 交易日}
  slippage_bp: {type: float, default: 10.0, min: 0.0, max: 50.0, step: 1.0, desc: 单边基础滑点, unit: bp}
  fixed_cost_bp: {type: float, default: 8.0, min: 5.0, max: 30.0, step: 1.0, desc: 往返固定费率近似, unit: bp, user_editable: false}
  min_edge_cost_mult: {type: float, default: 3.0, min: 1.0, max: 10.0, step: 0.5, desc: ATR 相对往返成本的最小倍数}
rules:
  - {id: E1, dimension: technical, role: entry, weight: 2, eval_time: daily_close, expr: "ma(f.close_qfq, p.ma_fast) > ma(f.close_qfq, p.ma_slow) for p.trend_days days", required_features: [f.close_qfq]}
  - {id: E2, dimension: technical, role: entry, weight: 2, eval_time: daily_close, expr: "lowest(f.low_qfq, 3) <= ma(f.close_qfq, p.ma_fast) * (1 + p.pullback_pct) and f.close_qfq > ma(f.close_qfq, p.ma_fast)", required_features: [f.low_qfq, f.close_qfq]}
  - {id: E3, dimension: technical, role: entry, weight: 1, eval_time: daily_close, expr: "f.close_qfq >= highest(f.close_qfq, 60) * (1 - p.max_dd_from_high)", required_features: [f.close_qfq]}
  - {id: A1, dimension: capital, role: entry, weight: 1, core: false, eval_time: daily_close, expr: "f.main_net_20d > 0", required_features: [f.main_net_20d], missing_policy: dimension_unknown}
  - {id: F1, dimension: technical, role: filter, weight: 0, eval_time: daily_close, expr: "ma(f.amount, 20) >= p.min_amount", required_features: [f.amount]}
  - {id: F2, dimension: technical, role: filter, weight: 0, eval_time: daily_close, expr: "f.list_days >= p.min_list_days", required_features: [f.list_days]}
  - {id: F3, dimension: technical, role: filter, weight: 0, eval_time: daily_close, expr: "atr(14) / f.close_qfq * 10000 >= p.min_edge_cost_mult * (2 * p.slippage_bp + p.fixed_cost_bp)", required_features: [f.high_qfq, f.low_qfq, f.close_qfq]}
  - {id: V1, dimension: sector_market, role: veto, weight: 0, eval_time: daily_close, expr: "f.market_regime == 'downtrend'", required_features: [f.market_regime], missing_policy: veto_unknown}
  - {id: V2, dimension: fundamental, role: veto, weight: 0, eval_time: daily_close, expr: "f.np_yoy_latest < p.np_yoy_floor", required_features: [f.np_yoy_latest], missing_policy: veto_unknown}
  - {id: V4, dimension: sentiment, role: veto, weight: 0, eval_time: daily_close, expr: "f.rsi14 > p.rsi_overheat", required_features: [f.rsi14], missing_policy: veto_unknown}
  - {id: C1, dimension: sector_market, role: counter, weight: 0, eval_time: daily_close, expr: "f.ind_rs20 < 0", required_features: [f.ind_rs20]}
  - {id: C2, dimension: capital, role: counter, weight: 0, eval_time: daily_close, expr: "f.main_net_20d < 0", required_features: [f.main_net_20d]}
  - {id: C3, dimension: technical, role: counter, weight: 0, eval_time: daily_close, expr: "f.amount < ma(f.amount, 20) * 0.5", required_features: [f.amount]}
  - {id: I1, dimension: technical, role: invalidation, weight: 0, eval_time: daily_close, expr: "ma(f.close_qfq, p.ma_fast) < ma(f.close_qfq, p.ma_slow)", required_features: [f.close_qfq]}
  - {id: I2, dimension: sector_market, role: invalidation, weight: 0, eval_time: daily_close, expr: "f.market_regime == 'downtrend'", required_features: [f.market_regime]}
  - {id: X1, dimension: technical, role: exit, weight: 0, eval_time: daily_close, expr: "f.close_qfq < ma(f.close_qfq, p.ma_fast) for p.exit_confirm_days days", required_features: [f.close_qfq]}
  - {id: X2, dimension: technical, role: exit, weight: 0, eval_time: intraday_1m, expr: "ctx.last_price <= plan.stop_loss", required_features: []}
  - {id: X3, dimension: technical, role: exit, weight: 0, eval_time: daily_close, expr: "ctx.holding_days >= p.time_stop and ctx.max_r_reached < 1", required_features: []}
  - {id: X4, dimension: technical, role: exit, weight: 0, eval_time: daily_close, expr: "f.close_qfq < lowest(ref(f.low_qfq, 1), 20)", required_features: [f.close_qfq, f.low_qfq]}
  - {id: X5, dimension: technical, role: exit, weight: 0, eval_time: daily_close, expr: "ctx.max_r_reached >= p.trail_trigger_r and f.close_qfq < ctx.highest_close_since_entry_qfq - p.trail_atr_mult * atr(14)", required_features: [f.close_qfq, f.high_qfq, f.low_qfq]}
  - {id: X6, dimension: technical, role: exit, weight: 0, eval_time: daily_close, expr: "f.close_qfq <= max2(plan.entry_price_qfq - p.atr_mult * atr(14), lowest(ref(f.low_qfq, 1), 20))", required_features: [f.close_qfq, f.high_qfq, f.low_qfq]}
action_map: {entry_all_core_pass: buy, held_hold: hold, exit: sell, else: wait}
stops: {stop_loss: "max2(plan.entry_price_qfq - p.atr_mult * atr(14), lowest(ref(f.low_qfq, 1), 20))", take_profit: null, time_stop_days: 40}
dimension_view_thresholds: {bullish: 0.67, bearish: 0.33}
applicability: {market_regime: [uptrend, range]}
valid_until: {trading_days: 5}
screen: null
```

> 夹具：每例带 `security{code,board,list_date}`（虚构上市日）；停牌用 `f.is_suspended`；`expect.lot_rule` 按 `market_rules.yaml` 逐项比对。除权例 W01-FX12（送转，A(d)=前 74 根 1.0、后 6 根 1.5）、W01-FX13（现金分红，1.0→1.03）的 series 已按 qfq@as_of 折算；W01-FX14 锁定 Wilder（SMA 口径会得出相反结论）；W01-FX15 跟踪止盈跨除权（A(d)=前 74 根 1.0、后 6 根 1.5）。含 `LIMIT_LOCKED`/`SUSPENDED` 的夹具写 `expect.reason_details:{码:{direction}}`；`expect.lot_rule={min_buy, step, odd_lot_sell_all, sell_qty?}`（plan 2.5.14 T-R15 ⑧⑨）。

```yaml validation
methods: [fixture, trigger_stats, tracking_sim]
window:
  lookback_trading_days: 120
  universe: 全A（不含北交所）
horizon_days: [1, 5, 20]
metrics: [trigger_rate, coverage, win_rate, avg_excess]
min_n: 30
pass_criteria:
- metric: trigger_rate
  op: <=
  value: 0.3
- metric: trigger_rate
  op: '>'
  value: 0
feature_requests: []
fixtures:
- id: W01-FX1
  desc: 【虚构】满足：创业板场景；趋势成立、回踩不破、无否决；买入 lot_rule=100/100
  as_of: '2026-10-30'
  security:
    code: 300364.SZ
    board: chinext
    list_date: '2024-03-01'
  series:
    f.close_qfq: [20.0, 20.08, 20.16, 20.24, 20.32, 20.4, 20.48, 20.57, 20.65, 20.73, 20.81, 20.9, 20.98, 21.07, 21.15, 21.23, 21.32, 21.4, 21.49, 21.58, 21.66, 21.75, 21.84, 21.92, 22.01, 22.1, 22.19,
      22.28, 22.37, 22.45, 22.54, 22.63, 22.73, 22.82, 22.91, 23.0, 23.09, 23.18, 23.28, 23.37, 23.46, 23.56, 23.65, 23.75, 23.84, 23.94, 24.03, 24.13, 24.22, 24.32, 24.42, 24.52, 24.61, 24.71, 24.81, 24.91,
      25.01, 25.11, 25.21, 25.31, 25.41, 25.51, 25.62, 25.72, 25.82, 25.93, 26.03, 26.13, 26.24, 26.34, 26.45, 26.55, 26.66, 26.77, 26.61, 26.45, 26.29, 26.39, 26.5, 26.6]
    f.high_qfq: [20.3, 20.38, 20.46, 20.54, 20.62, 20.71, 20.79, 20.88, 20.96, 21.04, 21.12, 21.21, 21.29, 21.39, 21.47, 21.55, 21.64, 21.72, 21.81, 21.9, 21.98, 22.08, 22.17, 22.25, 22.34, 22.43, 22.52,
      22.61, 22.71, 22.79, 22.88, 22.97, 23.07, 23.16, 23.25, 23.34, 23.44, 23.53, 23.63, 23.72, 23.81, 23.91, 24.0, 24.11, 24.2, 24.3, 24.39, 24.49, 24.58, 24.68, 24.79, 24.89, 24.98, 25.08, 25.18, 25.28,
      25.39, 25.49, 25.59, 25.69, 25.79, 25.89, 26.0, 26.11, 26.21, 26.32, 26.42, 26.52, 26.63, 26.74, 26.85, 26.95, 27.06, 27.17, 27.01, 26.85, 26.68, 26.79, 26.9, 27.0]
    f.low_qfq: [19.7, 19.78, 19.86, 19.94, 20.02, 20.09, 20.17, 20.26, 20.34, 20.42, 20.5, 20.59, 20.67, 20.75, 20.83, 20.91, 21.0, 21.08, 21.17, 21.26, 21.34, 21.42, 21.51, 21.59, 21.68, 21.77, 21.86,
      21.95, 22.03, 22.11, 22.2, 22.29, 22.39, 22.48, 22.57, 22.66, 22.74, 22.83, 22.93, 23.02, 23.11, 23.21, 23.3, 23.39, 23.48, 23.58, 23.67, 23.77, 23.86, 23.96, 24.05, 24.15, 24.24, 24.34, 24.44, 24.54,
      24.63, 24.73, 24.83, 24.93, 25.03, 25.13, 25.24, 25.33, 25.43, 25.54, 25.64, 25.74, 25.85, 25.94, 26.05, 26.15, 26.26, 26.37, 26.21, 26.05, 25.9, 25.99, 26.1, 26.2]
    f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0]
  features:
    f.list_days: 600
    f.is_suspended: false
    f.limit_up_price: 31.8
    f.limit_down_price: 21.2
    f.limit_locked_up: false
    f.limit_locked_down: false
    f.main_net_20d: 30000000.0
    f.np_yoy_latest: 12.0
    f.rsi14: 56.0
    f.market_regime: range
    f.ind_rs20: 1.5
  expect:
    state: entry_ok
    action: buy
    rule_ids_passed: [E1, E2, E3, A1, F1, F2, F3]
    lot_rule:
      min_buy: 100
      step: 100
      odd_lot_sell_all: false
- id: W01-FX2
  desc: 【虚构】不满足：当日收盘跌破 MA20（E2 不成立）
  as_of: '2026-10-30'
  security:
    code: 301218.SZ
    board: chinext
    list_date: '2024-03-01'
  series:
    f.close_qfq: [20.0, 20.08, 20.16, 20.24, 20.32, 20.4, 20.48, 20.57, 20.65, 20.73, 20.81, 20.9, 20.98, 21.07, 21.15, 21.23, 21.32, 21.4, 21.49, 21.58, 21.66, 21.75, 21.84, 21.92, 22.01, 22.1, 22.19,
      22.28, 22.37, 22.45, 22.54, 22.63, 22.73, 22.82, 22.91, 23.0, 23.09, 23.18, 23.28, 23.37, 23.46, 23.56, 23.65, 23.75, 23.84, 23.94, 24.03, 24.13, 24.22, 24.32, 24.42, 24.52, 24.61, 24.71, 24.81, 24.91,
      25.01, 25.11, 25.21, 25.31, 25.41, 25.51, 25.62, 25.72, 25.82, 25.93, 26.03, 26.13, 26.24, 26.34, 26.45, 26.55, 26.66, 26.77, 26.61, 26.45, 26.29, 26.39, 26.5, 25.17]
    f.high_qfq: [20.3, 20.38, 20.46, 20.54, 20.62, 20.71, 20.79, 20.88, 20.96, 21.04, 21.12, 21.21, 21.29, 21.39, 21.47, 21.55, 21.64, 21.72, 21.81, 21.9, 21.98, 22.08, 22.17, 22.25, 22.34, 22.43, 22.52,
      22.61, 22.71, 22.79, 22.88, 22.97, 23.07, 23.16, 23.25, 23.34, 23.44, 23.53, 23.63, 23.72, 23.81, 23.91, 24.0, 24.11, 24.2, 24.3, 24.39, 24.49, 24.58, 24.68, 24.79, 24.89, 24.98, 25.08, 25.18, 25.28,
      25.39, 25.49, 25.59, 25.69, 25.79, 25.89, 26.0, 26.11, 26.21, 26.32, 26.42, 26.52, 26.63, 26.74, 26.85, 26.95, 27.06, 27.17, 27.01, 26.85, 26.68, 26.79, 26.9, 25.55]
    f.low_qfq: [19.7, 19.78, 19.86, 19.94, 20.02, 20.09, 20.17, 20.26, 20.34, 20.42, 20.5, 20.59, 20.67, 20.75, 20.83, 20.91, 21.0, 21.08, 21.17, 21.26, 21.34, 21.42, 21.51, 21.59, 21.68, 21.77, 21.86,
      21.95, 22.03, 22.11, 22.2, 22.29, 22.39, 22.48, 22.57, 22.66, 22.74, 22.83, 22.93, 23.02, 23.11, 23.21, 23.3, 23.39, 23.48, 23.58, 23.67, 23.77, 23.86, 23.96, 24.05, 24.15, 24.24, 24.34, 24.44, 24.54,
      24.63, 24.73, 24.83, 24.93, 25.03, 25.13, 25.24, 25.33, 25.43, 25.54, 25.64, 25.74, 25.85, 25.94, 26.05, 26.15, 26.26, 26.37, 26.21, 26.05, 25.9, 25.99, 26.1, 24.79]
    f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0]
  features:
    f.list_days: 600
    f.is_suspended: false
    f.limit_up_price: 31.8
    f.limit_down_price: 21.2
    f.limit_locked_up: false
    f.limit_locked_down: false
    f.main_net_20d: 30000000.0
    f.np_yoy_latest: 12.0
    f.rsi14: 56.0
    f.market_regime: range
    f.ind_rs20: 1.5
  expect:
    state: not_triggered
    action: wait
    rule_ids_passed: [E1, E3, A1, F1, F2, F3]
- id: W01-FX3
  desc: 【虚构】缺数据：f.np_yoy_latest 缺失 → V2 无法判定，买入草案 KEY_DATA_MISSING；科创板买入 lot_rule=200/1
  as_of: '2026-10-30'
  security:
    code: 688018.SH
    board: star
    list_date: '2023-01-03'
  series:
    f.close_qfq: [20.0, 20.08, 20.16, 20.24, 20.32, 20.4, 20.48, 20.57, 20.65, 20.73, 20.81, 20.9, 20.98, 21.07, 21.15, 21.23, 21.32, 21.4, 21.49, 21.58, 21.66, 21.75, 21.84, 21.92, 22.01, 22.1, 22.19,
      22.28, 22.37, 22.45, 22.54, 22.63, 22.73, 22.82, 22.91, 23.0, 23.09, 23.18, 23.28, 23.37, 23.46, 23.56, 23.65, 23.75, 23.84, 23.94, 24.03, 24.13, 24.22, 24.32, 24.42, 24.52, 24.61, 24.71, 24.81, 24.91,
      25.01, 25.11, 25.21, 25.31, 25.41, 25.51, 25.62, 25.72, 25.82, 25.93, 26.03, 26.13, 26.24, 26.34, 26.45, 26.55, 26.66, 26.77, 26.61, 26.45, 26.29, 26.39, 26.5, 26.6]
    f.high_qfq: [20.3, 20.38, 20.46, 20.54, 20.62, 20.71, 20.79, 20.88, 20.96, 21.04, 21.12, 21.21, 21.29, 21.39, 21.47, 21.55, 21.64, 21.72, 21.81, 21.9, 21.98, 22.08, 22.17, 22.25, 22.34, 22.43, 22.52,
      22.61, 22.71, 22.79, 22.88, 22.97, 23.07, 23.16, 23.25, 23.34, 23.44, 23.53, 23.63, 23.72, 23.81, 23.91, 24.0, 24.11, 24.2, 24.3, 24.39, 24.49, 24.58, 24.68, 24.79, 24.89, 24.98, 25.08, 25.18, 25.28,
      25.39, 25.49, 25.59, 25.69, 25.79, 25.89, 26.0, 26.11, 26.21, 26.32, 26.42, 26.52, 26.63, 26.74, 26.85, 26.95, 27.06, 27.17, 27.01, 26.85, 26.68, 26.79, 26.9, 27.0]
    f.low_qfq: [19.7, 19.78, 19.86, 19.94, 20.02, 20.09, 20.17, 20.26, 20.34, 20.42, 20.5, 20.59, 20.67, 20.75, 20.83, 20.91, 21.0, 21.08, 21.17, 21.26, 21.34, 21.42, 21.51, 21.59, 21.68, 21.77, 21.86,
      21.95, 22.03, 22.11, 22.2, 22.29, 22.39, 22.48, 22.57, 22.66, 22.74, 22.83, 22.93, 23.02, 23.11, 23.21, 23.3, 23.39, 23.48, 23.58, 23.67, 23.77, 23.86, 23.96, 24.05, 24.15, 24.24, 24.34, 24.44, 24.54,
      24.63, 24.73, 24.83, 24.93, 25.03, 25.13, 25.24, 25.33, 25.43, 25.54, 25.64, 25.74, 25.85, 25.94, 26.05, 26.15, 26.26, 26.37, 26.21, 26.05, 25.9, 25.99, 26.1, 26.2]
    f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0]
  features:
    f.list_days: 900
    f.is_suspended: false
    f.limit_up_price: 31.8
    f.limit_down_price: 21.2
    f.limit_locked_up: false
    f.limit_locked_down: false
    f.main_net_20d: 30000000.0
    f.np_yoy_latest: null
    f.rsi14: 56.0
    f.market_regime: range
    f.ind_rs20: 1.5
  expect:
    state: entry_ok
    action: buy
    rule_ids_passed: [E1, E2, E3, A1, F1, F2, F3]
    reason_codes: [KEY_DATA_MISSING]
    lot_rule:
      min_buy: 200
      step: 1
      odd_lot_sell_all: false
- id: W01-FX4
  desc: 【虚构】维度分歧：技术满足，行业弱于大盘、主力净流出（并列，不合并）
  as_of: '2026-10-30'
  security:
    code: 688073.SH
    board: star
    list_date: '2023-01-03'
  series:
    f.close_qfq: [20.0, 20.08, 20.16, 20.24, 20.32, 20.4, 20.48, 20.57, 20.65, 20.73, 20.81, 20.9, 20.98, 21.07, 21.15, 21.23, 21.32, 21.4, 21.49, 21.58, 21.66, 21.75, 21.84, 21.92, 22.01, 22.1, 22.19,
      22.28, 22.37, 22.45, 22.54, 22.63, 22.73, 22.82, 22.91, 23.0, 23.09, 23.18, 23.28, 23.37, 23.46, 23.56, 23.65, 23.75, 23.84, 23.94, 24.03, 24.13, 24.22, 24.32, 24.42, 24.52, 24.61, 24.71, 24.81, 24.91,
      25.01, 25.11, 25.21, 25.31, 25.41, 25.51, 25.62, 25.72, 25.82, 25.93, 26.03, 26.13, 26.24, 26.34, 26.45, 26.55, 26.66, 26.77, 26.61, 26.45, 26.29, 26.39, 26.5, 26.6]
    f.high_qfq: [20.3, 20.38, 20.46, 20.54, 20.62, 20.71, 20.79, 20.88, 20.96, 21.04, 21.12, 21.21, 21.29, 21.39, 21.47, 21.55, 21.64, 21.72, 21.81, 21.9, 21.98, 22.08, 22.17, 22.25, 22.34, 22.43, 22.52,
      22.61, 22.71, 22.79, 22.88, 22.97, 23.07, 23.16, 23.25, 23.34, 23.44, 23.53, 23.63, 23.72, 23.81, 23.91, 24.0, 24.11, 24.2, 24.3, 24.39, 24.49, 24.58, 24.68, 24.79, 24.89, 24.98, 25.08, 25.18, 25.28,
      25.39, 25.49, 25.59, 25.69, 25.79, 25.89, 26.0, 26.11, 26.21, 26.32, 26.42, 26.52, 26.63, 26.74, 26.85, 26.95, 27.06, 27.17, 27.01, 26.85, 26.68, 26.79, 26.9, 27.0]
    f.low_qfq: [19.7, 19.78, 19.86, 19.94, 20.02, 20.09, 20.17, 20.26, 20.34, 20.42, 20.5, 20.59, 20.67, 20.75, 20.83, 20.91, 21.0, 21.08, 21.17, 21.26, 21.34, 21.42, 21.51, 21.59, 21.68, 21.77, 21.86,
      21.95, 22.03, 22.11, 22.2, 22.29, 22.39, 22.48, 22.57, 22.66, 22.74, 22.83, 22.93, 23.02, 23.11, 23.21, 23.3, 23.39, 23.48, 23.58, 23.67, 23.77, 23.86, 23.96, 24.05, 24.15, 24.24, 24.34, 24.44, 24.54,
      24.63, 24.73, 24.83, 24.93, 25.03, 25.13, 25.24, 25.33, 25.43, 25.54, 25.64, 25.74, 25.85, 25.94, 26.05, 26.15, 26.26, 26.37, 26.21, 26.05, 25.9, 25.99, 26.1, 26.2]
    f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0]
  features:
    f.list_days: 900
    f.is_suspended: false
    f.limit_up_price: 31.8
    f.limit_down_price: 21.2
    f.limit_locked_up: false
    f.limit_locked_down: false
    f.main_net_20d: -20000000.0
    f.np_yoy_latest: 12.0
    f.rsi14: 56.0
    f.market_regime: range
    f.ind_rs20: -1.8
  expect:
    state: entry_ok
    action: buy
    rule_ids_passed: [E1, E2, E3, F1, F2, F3, C1, C2]
    lot_rule:
      min_buy: 200
      step: 1
      odd_lot_sell_all: false
- id: W01-FX5
  desc: 【虚构】一字涨停：科创板 20% 涨停价由 market_rules 计算；规则满足但不可成交
  as_of: '2026-10-30'
  security:
    code: 688073.SH
    board: star
    list_date: '2023-01-03'
  series:
    f.close_qfq: [20.0, 20.08, 20.16, 20.24, 20.32, 20.4, 20.48, 20.57, 20.65, 20.73, 20.81, 20.9, 20.98, 21.07, 21.15, 21.23, 21.32, 21.4, 21.49, 21.58, 21.66, 21.75, 21.84, 21.92, 22.01, 22.1, 22.19,
      22.28, 22.37, 22.45, 22.54, 22.63, 22.73, 22.82, 22.91, 23.0, 23.09, 23.18, 23.28, 23.37, 23.46, 23.56, 23.65, 23.75, 23.84, 23.94, 24.03, 24.13, 24.22, 24.32, 24.42, 24.52, 24.61, 24.71, 24.81, 24.91,
      25.01, 25.11, 25.21, 25.31, 25.41, 25.51, 25.62, 25.72, 25.82, 25.93, 26.03, 26.13, 26.24, 26.34, 26.45, 26.55, 26.66, 26.77, 26.61, 26.45, 26.29, 26.39, 26.5, 31.8]
    f.high_qfq: [20.3, 20.38, 20.46, 20.54, 20.62, 20.71, 20.79, 20.88, 20.96, 21.04, 21.12, 21.21, 21.29, 21.39, 21.47, 21.55, 21.64, 21.72, 21.81, 21.9, 21.98, 22.08, 22.17, 22.25, 22.34, 22.43, 22.52,
      22.61, 22.71, 22.79, 22.88, 22.97, 23.07, 23.16, 23.25, 23.34, 23.44, 23.53, 23.63, 23.72, 23.81, 23.91, 24.0, 24.11, 24.2, 24.3, 24.39, 24.49, 24.58, 24.68, 24.79, 24.89, 24.98, 25.08, 25.18, 25.28,
      25.39, 25.49, 25.59, 25.69, 25.79, 25.89, 26.0, 26.11, 26.21, 26.32, 26.42, 26.52, 26.63, 26.74, 26.85, 26.95, 27.06, 27.17, 27.01, 26.85, 26.68, 26.79, 26.9, 31.8]
    f.low_qfq: [19.7, 19.78, 19.86, 19.94, 20.02, 20.09, 20.17, 20.26, 20.34, 20.42, 20.5, 20.59, 20.67, 20.75, 20.83, 20.91, 21.0, 21.08, 21.17, 21.26, 21.34, 21.42, 21.51, 21.59, 21.68, 21.77, 21.86,
      21.95, 22.03, 22.11, 22.2, 22.29, 22.39, 22.48, 22.57, 22.66, 22.74, 22.83, 22.93, 23.02, 23.11, 23.21, 23.3, 23.39, 23.48, 23.58, 23.67, 23.77, 23.86, 23.96, 24.05, 24.15, 24.24, 24.34, 24.44, 24.54,
      24.63, 24.73, 24.83, 24.93, 25.03, 25.13, 25.24, 25.33, 25.43, 25.54, 25.64, 25.74, 25.85, 25.94, 26.05, 26.15, 26.26, 26.37, 26.21, 26.05, 25.9, 25.99, 26.1, 31.8]
    f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0]
  features:
    f.list_days: 900
    f.is_suspended: false
    f.limit_up_price: 31.8
    f.limit_down_price: 21.2
    f.limit_locked_up: true
    f.limit_locked_down: false
    f.main_net_20d: 30000000.0
    f.np_yoy_latest: 12.0
    f.rsi14: 70.0
    f.market_regime: range
    f.ind_rs20: 1.5
  expect:
    state: entry_ok
    action: buy
    rule_ids_passed: [E1, E2, E3, A1, F1, F2, F3]
    reason_codes: [LIMIT_LOCKED]
    lot_rule:
      min_buy: 200
      step: 1
      odd_lot_sell_all: false
    reason_details:
      LIMIT_LOCKED:
        direction: buy
- id: W01-FX6
  desc: 【虚构】T+1：当日买入（可卖 0）后触及止损，执行层 T1_NOT_SELLABLE（替代做T无底仓，H⑩）
  as_of: '2026-10-30'
  security:
    code: 301218.SZ
    board: chinext
    list_date: '2024-03-01'
  series:
    f.close_qfq: [20.0, 20.08, 20.16, 20.24, 20.32, 20.4, 20.48, 20.57, 20.65, 20.73, 20.81, 20.9, 20.98, 21.07, 21.15, 21.23, 21.32, 21.4, 21.49, 21.58, 21.66, 21.75, 21.84, 21.92, 22.01, 22.1, 22.19,
      22.28, 22.37, 22.45, 22.54, 22.63, 22.73, 22.82, 22.91, 23.0, 23.09, 23.18, 23.28, 23.37, 23.46, 23.56, 23.65, 23.75, 23.84, 23.94, 24.03, 24.13, 24.22, 24.32, 24.42, 24.52, 24.61, 24.71, 24.81, 24.91,
      25.01, 25.11, 25.21, 25.31, 25.41, 25.51, 25.62, 25.72, 25.82, 25.93, 26.03, 26.13, 26.24, 26.34, 26.45, 26.55, 26.66, 26.77, 26.61, 26.45, 26.29, 26.39, 26.5, 25.57, 24.91]
    f.high_qfq: [20.3, 20.38, 20.46, 20.54, 20.62, 20.71, 20.79, 20.88, 20.96, 21.04, 21.12, 21.21, 21.29, 21.39, 21.47, 21.55, 21.64, 21.72, 21.81, 21.9, 21.98, 22.08, 22.17, 22.25, 22.34, 22.43, 22.52,
      22.61, 22.71, 22.79, 22.88, 22.97, 23.07, 23.16, 23.25, 23.34, 23.44, 23.53, 23.63, 23.72, 23.81, 23.91, 24.0, 24.11, 24.2, 24.3, 24.39, 24.49, 24.58, 24.68, 24.79, 24.89, 24.98, 25.08, 25.18, 25.28,
      25.39, 25.49, 25.59, 25.69, 25.79, 25.89, 26.0, 26.11, 26.21, 26.32, 26.42, 26.52, 26.63, 26.74, 26.85, 26.95, 27.06, 27.17, 27.01, 26.85, 26.68, 26.79, 26.9, 25.95, 25.28]
    f.low_qfq: [19.7, 19.78, 19.86, 19.94, 20.02, 20.09, 20.17, 20.26, 20.34, 20.42, 20.5, 20.59, 20.67, 20.75, 20.83, 20.91, 21.0, 21.08, 21.17, 21.26, 21.34, 21.42, 21.51, 21.59, 21.68, 21.77, 21.86,
      21.95, 22.03, 22.11, 22.2, 22.29, 22.39, 22.48, 22.57, 22.66, 22.74, 22.83, 22.93, 23.02, 23.11, 23.21, 23.3, 23.39, 23.48, 23.58, 23.67, 23.77, 23.86, 23.96, 24.05, 24.15, 24.24, 24.34, 24.44, 24.54,
      24.63, 24.73, 24.83, 24.93, 25.03, 25.13, 25.24, 25.33, 25.43, 25.54, 25.64, 25.74, 25.85, 25.94, 26.05, 26.15, 26.26, 26.37, 26.21, 26.05, 25.9, 25.99, 26.1, 25.19, 24.54]
    f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0]
  features:
    f.list_days: 600
    f.is_suspended: false
    f.limit_up_price: 30.68
    f.limit_down_price: 20.46
    f.limit_locked_up: false
    f.limit_locked_down: false
    f.main_net_20d: 30000000.0
    f.np_yoy_latest: 12.0
    f.rsi14: 56.0
    f.market_regime: range
    f.ind_rs20: 1.5
  holding:
    qty: 1000
    sellable: 0
  ctx:
    ctx.last_price: 24.91
    ctx.holding_days: 0
    ctx.sellable_qty: 0
    ctx.max_r_reached: 0.0
    ctx.highest_close_since_entry_qfq: 25.57
  plan:
    plan.entry_price: 25.57
    plan.entry_price_qfq: 25.57
    plan.stop_loss: 25.04
  expect:
    state: exit_signal
    action: sell
    rule_ids_passed: [E1, E3, A1, F1, F2, F3, X1, X2, X4, X6]
    reason_codes: [T1_NOT_SELLABLE]
    lot_rule:
      min_buy: 100
      step: 100
      odd_lot_sell_all: false
- id: W01-FX7
  desc: 【虚构】上市初期：第 3 个交易日，注册制新股前 5 日无涨跌幅（limit 价 null，不按 20%）；K 线不足 → insufficient_data，不产候选
  as_of: '2026-10-30'
  security:
    code: 688018.SH
    board: star
    list_date: '2026-10-28'
  series:
    f.close_qfq: [30.0, 31.5, 33.2]
    f.high_qfq: [30.45, 31.97, 33.7]
    f.low_qfq: [29.55, 31.03, 32.7]
    f.amount: [200000000.0, 200000000.0, 200000000.0]
  features:
    f.list_days: 3
    f.is_suspended: false
    f.limit_up_price: null
    f.limit_down_price: null
    f.limit_locked_up: false
    f.limit_locked_down: false
    f.main_net_20d: 30000000.0
    f.np_yoy_latest: 12.0
    f.rsi14: 56.0
    f.market_regime: range
    f.ind_rs20: 1.5
  expect:
    state: insufficient_data
    action: wait
    rule_ids_passed: [A1]
    reason_codes: [NEW_LISTING]
- id: W01-FX8
  desc: 【虚构】成本拒绝：ATR14(Wilder)/收盘 < 3×(2×滑点+固定费率) → F3 不满足
  as_of: '2026-10-30'
  security:
    code: 300364.SZ
    board: chinext
    list_date: '2024-03-01'
  series:
    f.close_qfq: [20.0, 20.04, 20.08, 20.12, 20.16, 20.2, 20.24, 20.28, 20.32, 20.36, 20.4, 20.44, 20.49, 20.53, 20.57, 20.61, 20.65, 20.69, 20.73, 20.77, 20.82, 20.86, 20.9, 20.94, 20.98, 21.02, 21.07,
      21.11, 21.15, 21.19, 21.24, 21.28, 21.32, 21.36, 21.41, 21.45, 21.49, 21.53, 21.58, 21.62, 21.66, 21.71, 21.75, 21.79, 21.84, 21.88, 21.93, 21.97, 22.01, 22.06, 22.1, 22.15, 22.19, 22.23, 22.28, 22.32,
      22.37, 22.41, 22.46, 22.5, 22.55, 22.59, 22.64, 22.68, 22.73, 22.77, 22.82, 22.86, 22.91, 22.96, 23.0, 23.05, 23.09, 23.14, 23.09, 23.05, 23.0, 22.96, 22.97, 22.98]
    f.high_qfq: [20.02, 20.06, 20.1, 20.14, 20.18, 20.22, 20.26, 20.3, 20.34, 20.38, 20.42, 20.46, 20.51, 20.55, 20.59, 20.63, 20.67, 20.71, 20.75, 20.79, 20.84, 20.89, 20.93, 20.97, 21.01, 21.05, 21.1,
      21.14, 21.18, 21.22, 21.27, 21.31, 21.35, 21.39, 21.44, 21.48, 21.52, 21.56, 21.61, 21.65, 21.69, 21.74, 21.78, 21.82, 21.87, 21.91, 21.96, 22.0, 22.04, 22.09, 22.13, 22.18, 22.22, 22.26, 22.31, 22.35,
      22.4, 22.44, 22.49, 22.53, 22.58, 22.62, 22.67, 22.71, 22.76, 22.8, 22.85, 22.89, 22.94, 22.99, 23.03, 23.08, 23.12, 23.17, 23.12, 23.08, 23.03, 22.99, 23.0, 23.01]
    f.low_qfq: [19.98, 20.02, 20.06, 20.1, 20.14, 20.18, 20.22, 20.26, 20.3, 20.34, 20.38, 20.42, 20.47, 20.51, 20.55, 20.59, 20.63, 20.67, 20.71, 20.75, 20.8, 20.83, 20.87, 20.91, 20.95, 20.99, 21.04,
      21.08, 21.12, 21.16, 21.21, 21.25, 21.29, 21.33, 21.38, 21.42, 21.46, 21.5, 21.55, 21.59, 21.63, 21.68, 21.72, 21.76, 21.81, 21.85, 21.9, 21.94, 21.98, 22.03, 22.07, 22.12, 22.16, 22.2, 22.25, 22.29,
      22.34, 22.38, 22.43, 22.47, 22.52, 22.56, 22.61, 22.65, 22.7, 22.74, 22.79, 22.83, 22.88, 22.93, 22.97, 23.02, 23.06, 23.11, 23.06, 23.02, 22.97, 22.93, 22.94, 22.95]
    f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0]
  features:
    f.list_days: 600
    f.is_suspended: false
    f.limit_up_price: 27.56
    f.limit_down_price: 18.38
    f.limit_locked_up: false
    f.limit_locked_down: false
    f.main_net_20d: 30000000.0
    f.np_yoy_latest: 12.0
    f.rsi14: 56.0
    f.market_regime: range
    f.ind_rs20: 1.5
  expect:
    state: not_triggered
    action: wait
    rule_ids_passed: [E1, E2, E3, A1, F1, F2]
- id: W01-FX9
  desc: 【虚构】失效：大盘 downtrend → V1 否决、I2 命中
  as_of: '2026-10-30'
  security:
    code: 688018.SH
    board: star
    list_date: '2023-01-03'
  series:
    f.close_qfq: [20.0, 20.08, 20.16, 20.24, 20.32, 20.4, 20.48, 20.57, 20.65, 20.73, 20.81, 20.9, 20.98, 21.07, 21.15, 21.23, 21.32, 21.4, 21.49, 21.58, 21.66, 21.75, 21.84, 21.92, 22.01, 22.1, 22.19,
      22.28, 22.37, 22.45, 22.54, 22.63, 22.73, 22.82, 22.91, 23.0, 23.09, 23.18, 23.28, 23.37, 23.46, 23.56, 23.65, 23.75, 23.84, 23.94, 24.03, 24.13, 24.22, 24.32, 24.42, 24.52, 24.61, 24.71, 24.81, 24.91,
      25.01, 25.11, 25.21, 25.31, 25.41, 25.51, 25.62, 25.72, 25.82, 25.93, 26.03, 26.13, 26.24, 26.34, 26.45, 26.55, 26.66, 26.77, 26.61, 26.45, 26.29, 26.39, 26.5, 26.6]
    f.high_qfq: [20.3, 20.38, 20.46, 20.54, 20.62, 20.71, 20.79, 20.88, 20.96, 21.04, 21.12, 21.21, 21.29, 21.39, 21.47, 21.55, 21.64, 21.72, 21.81, 21.9, 21.98, 22.08, 22.17, 22.25, 22.34, 22.43, 22.52,
      22.61, 22.71, 22.79, 22.88, 22.97, 23.07, 23.16, 23.25, 23.34, 23.44, 23.53, 23.63, 23.72, 23.81, 23.91, 24.0, 24.11, 24.2, 24.3, 24.39, 24.49, 24.58, 24.68, 24.79, 24.89, 24.98, 25.08, 25.18, 25.28,
      25.39, 25.49, 25.59, 25.69, 25.79, 25.89, 26.0, 26.11, 26.21, 26.32, 26.42, 26.52, 26.63, 26.74, 26.85, 26.95, 27.06, 27.17, 27.01, 26.85, 26.68, 26.79, 26.9, 27.0]
    f.low_qfq: [19.7, 19.78, 19.86, 19.94, 20.02, 20.09, 20.17, 20.26, 20.34, 20.42, 20.5, 20.59, 20.67, 20.75, 20.83, 20.91, 21.0, 21.08, 21.17, 21.26, 21.34, 21.42, 21.51, 21.59, 21.68, 21.77, 21.86,
      21.95, 22.03, 22.11, 22.2, 22.29, 22.39, 22.48, 22.57, 22.66, 22.74, 22.83, 22.93, 23.02, 23.11, 23.21, 23.3, 23.39, 23.48, 23.58, 23.67, 23.77, 23.86, 23.96, 24.05, 24.15, 24.24, 24.34, 24.44, 24.54,
      24.63, 24.73, 24.83, 24.93, 25.03, 25.13, 25.24, 25.33, 25.43, 25.54, 25.64, 25.74, 25.85, 25.94, 26.05, 26.15, 26.26, 26.37, 26.21, 26.05, 25.9, 25.99, 26.1, 26.2]
    f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0]
  features:
    f.list_days: 900
    f.is_suspended: false
    f.limit_up_price: 31.8
    f.limit_down_price: 21.2
    f.limit_locked_up: false
    f.limit_locked_down: false
    f.main_net_20d: 30000000.0
    f.np_yoy_latest: 12.0
    f.rsi14: 56.0
    f.market_regime: downtrend
    f.ind_rs20: 1.5
  expect:
    state: vetoed
    action: wait
    rule_ids_passed: [E1, E2, E3, A1, F1, F2, F3, V1, I2]
- id: W01-FX10
  desc: 【虚构】科创板零股：持有 150 股（<200）；收盘连续 2 日破 MA20 → sell，lot_rule 要求一次性卖出全部 150 股
  as_of: '2026-10-30'
  security:
    code: 688073.SH
    board: star
    list_date: '2023-01-03'
  series:
    f.close_qfq: [20.0, 20.08, 20.16, 20.24, 20.32, 20.4, 20.48, 20.57, 20.65, 20.73, 20.81, 20.9, 20.98, 21.07, 21.15, 21.23, 21.32, 21.4, 21.49, 21.58, 21.66, 21.75, 21.84, 21.92, 22.01, 22.1, 22.19,
      22.28, 22.37, 22.45, 22.54, 22.63, 22.73, 22.82, 22.91, 23.0, 23.09, 23.18, 23.28, 23.37, 23.46, 23.56, 23.65, 23.75, 23.84, 23.94, 24.03, 24.13, 24.22, 24.32, 24.42, 24.52, 24.61, 24.71, 24.81, 24.91,
      25.01, 25.11, 25.21, 25.31, 25.41, 25.51, 25.62, 25.72, 25.82, 25.93, 26.03, 26.13, 26.24, 26.34, 26.45, 26.55, 26.66, 26.77, 26.61, 26.45, 26.29, 26.39, 25.07, 24.55]
    f.high_qfq: [20.3, 20.38, 20.46, 20.54, 20.62, 20.71, 20.79, 20.88, 20.96, 21.04, 21.12, 21.21, 21.29, 21.39, 21.47, 21.55, 21.64, 21.72, 21.81, 21.9, 21.98, 22.08, 22.17, 22.25, 22.34, 22.43, 22.52,
      22.61, 22.71, 22.79, 22.88, 22.97, 23.07, 23.16, 23.25, 23.34, 23.44, 23.53, 23.63, 23.72, 23.81, 23.91, 24.0, 24.11, 24.2, 24.3, 24.39, 24.49, 24.58, 24.68, 24.79, 24.89, 24.98, 25.08, 25.18, 25.28,
      25.39, 25.49, 25.59, 25.69, 25.79, 25.89, 26.0, 26.11, 26.21, 26.32, 26.42, 26.52, 26.63, 26.74, 26.85, 26.95, 27.06, 27.17, 27.01, 26.85, 26.68, 26.79, 25.45, 24.92]
    f.low_qfq: [19.7, 19.78, 19.86, 19.94, 20.02, 20.09, 20.17, 20.26, 20.34, 20.42, 20.5, 20.59, 20.67, 20.75, 20.83, 20.91, 21.0, 21.08, 21.17, 21.26, 21.34, 21.42, 21.51, 21.59, 21.68, 21.77, 21.86,
      21.95, 22.03, 22.11, 22.2, 22.29, 22.39, 22.48, 22.57, 22.66, 22.74, 22.83, 22.93, 23.02, 23.11, 23.21, 23.3, 23.39, 23.48, 23.58, 23.67, 23.77, 23.86, 23.96, 24.05, 24.15, 24.24, 24.34, 24.44, 24.54,
      24.63, 24.73, 24.83, 24.93, 25.03, 25.13, 25.24, 25.33, 25.43, 25.54, 25.64, 25.74, 25.85, 25.94, 26.05, 26.15, 26.26, 26.37, 26.21, 26.05, 25.9, 25.99, 24.69, 24.18]
    f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0]
  features:
    f.list_days: 900
    f.is_suspended: false
    f.limit_up_price: 30.08
    f.limit_down_price: 20.06
    f.limit_locked_up: false
    f.limit_locked_down: false
    f.main_net_20d: 30000000.0
    f.np_yoy_latest: 12.0
    f.rsi14: 56.0
    f.market_regime: range
    f.ind_rs20: 1.5
  holding:
    qty: 150
    sellable: 150
  ctx:
    ctx.last_price: 24.55
    ctx.holding_days: 12
    ctx.sellable_qty: 150
    ctx.max_r_reached: 0.4
    ctx.highest_close_since_entry_qfq: 26.39
  plan:
    plan.entry_price: 25.86
    plan.entry_price_qfq: 25.86
    plan.stop_loss: 22.43
  expect:
    state: exit_signal
    action: sell
    rule_ids_passed: [E1, E3, A1, F1, F2, F3, X1, X4, X6]
    lot_rule:
      min_buy: 200
      step: 1
      odd_lot_sell_all: true
      sell_qty: 150
- id: W01-FX11
  desc: 【虚构】停牌：as_of 当日 f.is_suspended=true（规则按此前有效日 K 求值），买入不可执行 SUSPENDED
  as_of: '2026-10-30'
  security:
    code: 301218.SZ
    board: chinext
    list_date: '2024-03-01'
  series:
    f.close_qfq: [20.0, 20.08, 20.16, 20.24, 20.32, 20.4, 20.48, 20.57, 20.65, 20.73, 20.81, 20.9, 20.98, 21.07, 21.15, 21.23, 21.32, 21.4, 21.49, 21.58, 21.66, 21.75, 21.84, 21.92, 22.01, 22.1, 22.19,
      22.28, 22.37, 22.45, 22.54, 22.63, 22.73, 22.82, 22.91, 23.0, 23.09, 23.18, 23.28, 23.37, 23.46, 23.56, 23.65, 23.75, 23.84, 23.94, 24.03, 24.13, 24.22, 24.32, 24.42, 24.52, 24.61, 24.71, 24.81, 24.91,
      25.01, 25.11, 25.21, 25.31, 25.41, 25.51, 25.62, 25.72, 25.82, 25.93, 26.03, 26.13, 26.24, 26.34, 26.45, 26.55, 26.66, 26.77, 26.61, 26.45, 26.29, 26.39, 26.5, 26.6]
    f.high_qfq: [20.3, 20.38, 20.46, 20.54, 20.62, 20.71, 20.79, 20.88, 20.96, 21.04, 21.12, 21.21, 21.29, 21.39, 21.47, 21.55, 21.64, 21.72, 21.81, 21.9, 21.98, 22.08, 22.17, 22.25, 22.34, 22.43, 22.52,
      22.61, 22.71, 22.79, 22.88, 22.97, 23.07, 23.16, 23.25, 23.34, 23.44, 23.53, 23.63, 23.72, 23.81, 23.91, 24.0, 24.11, 24.2, 24.3, 24.39, 24.49, 24.58, 24.68, 24.79, 24.89, 24.98, 25.08, 25.18, 25.28,
      25.39, 25.49, 25.59, 25.69, 25.79, 25.89, 26.0, 26.11, 26.21, 26.32, 26.42, 26.52, 26.63, 26.74, 26.85, 26.95, 27.06, 27.17, 27.01, 26.85, 26.68, 26.79, 26.9, 27.0]
    f.low_qfq: [19.7, 19.78, 19.86, 19.94, 20.02, 20.09, 20.17, 20.26, 20.34, 20.42, 20.5, 20.59, 20.67, 20.75, 20.83, 20.91, 21.0, 21.08, 21.17, 21.26, 21.34, 21.42, 21.51, 21.59, 21.68, 21.77, 21.86,
      21.95, 22.03, 22.11, 22.2, 22.29, 22.39, 22.48, 22.57, 22.66, 22.74, 22.83, 22.93, 23.02, 23.11, 23.21, 23.3, 23.39, 23.48, 23.58, 23.67, 23.77, 23.86, 23.96, 24.05, 24.15, 24.24, 24.34, 24.44, 24.54,
      24.63, 24.73, 24.83, 24.93, 25.03, 25.13, 25.24, 25.33, 25.43, 25.54, 25.64, 25.74, 25.85, 25.94, 26.05, 26.15, 26.26, 26.37, 26.21, 26.05, 25.9, 25.99, 26.1, 26.2]
    f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0]
  features:
    f.list_days: 600
    f.is_suspended: true
    f.limit_up_price: 31.8
    f.limit_down_price: 21.2
    f.limit_locked_up: false
    f.limit_locked_down: false
    f.main_net_20d: 30000000.0
    f.np_yoy_latest: 12.0
    f.rsi14: 56.0
    f.market_regime: range
    f.ind_rs20: 1.5
  expect:
    state: entry_ok
    action: buy
    rule_ids_passed: [E1, E2, E3, A1, F1, F2, F3]
    reason_codes: [SUSPENDED]
    lot_rule:
      min_buy: 100
      step: 100
      odd_lot_sell_all: false
    reason_details:
      SUSPENDED:
        direction: buy
- id: W01-FX12
  desc: 【虚构】除权·送转：10 送 5，A(d)=前 74 根 1.0、后 6 根 1.5；建仓不复权价 19.92，plan.entry_price_qfq=19.92×1.0/1.5；X6 用 qfq 口径不触发（若误用不复权建仓价会误触发）
  as_of: '2026-10-30'
  security:
    code: 688018.SH
    board: star
    list_date: '2023-01-03'
  series:
    f.close_qfq: [10.0, 10.04, 10.08, 10.12, 10.16, 10.2, 10.24, 10.2867, 10.3267, 10.3667, 10.4067, 10.4467, 10.4933, 10.5333, 10.5733, 10.62, 10.66, 10.7, 10.7467, 10.7867, 10.8333, 10.8733, 10.92, 10.96,
      11.0067, 11.0467, 11.0933, 11.14, 11.18, 11.2267, 11.2733, 11.32, 11.36, 11.4067, 11.4533, 11.5, 11.5467, 11.5933, 11.64, 11.6867, 11.7333, 11.78, 11.8267, 11.8733, 11.92, 11.9667, 12.0133, 12.0667,
      12.1133, 12.16, 12.2067, 12.26, 12.3067, 12.3533, 12.4067, 12.4533, 12.5067, 12.5533, 12.6067, 12.6533, 12.7067, 12.76, 12.8067, 12.86, 12.9133, 12.96, 13.0133, 13.0667, 13.12, 13.1733, 13.2267, 13.28,
      13.3267, 13.38, 13.38, 13.38, 13.38, 13.38, 13.38, 13.38]
    f.high_qfq: [10.1467, 10.1933, 10.2333, 10.2733, 10.3133, 10.3533, 10.3933, 10.44, 10.48, 10.52, 10.56, 10.6067, 10.6533, 10.6933, 10.7333, 10.78, 10.82, 10.86, 10.9067, 10.9467, 10.9933, 11.0333, 11.0867,
      11.1267, 11.1733, 11.2133, 11.26, 11.3067, 11.3467, 11.3933, 11.44, 11.4867, 11.5333, 11.58, 11.6267, 11.6733, 11.72, 11.7667, 11.8133, 11.86, 11.9067, 11.96, 12.0067, 12.0533, 12.1, 12.1467, 12.1933,
      12.2467, 12.2933, 12.34, 12.3867, 12.4467, 12.4933, 12.54, 12.5933, 12.64, 12.6933, 12.74, 12.7933, 12.84, 12.9, 12.9533, 13.0, 13.0533, 13.1067, 13.1533, 13.2067, 13.26, 13.32, 13.3733, 13.4267,
      13.48, 13.5267, 13.58, 13.58, 13.58, 13.58, 13.58, 13.58, 13.58]
    f.low_qfq: [9.8533, 9.8867, 9.9267, 9.9667, 10.0067, 10.0467, 10.0867, 10.1333, 10.1733, 10.2133, 10.2533, 10.2867, 10.3333, 10.3733, 10.4133, 10.46, 10.5, 10.54, 10.5867, 10.6267, 10.6733, 10.7133,
      10.7533, 10.7933, 10.84, 10.88, 10.9267, 10.9733, 11.0133, 11.06, 11.1067, 11.1533, 11.1867, 11.2333, 11.28, 11.3267, 11.3733, 11.42, 11.4667, 11.5133, 11.56, 11.6, 11.6467, 11.6933, 11.74, 11.7867,
      11.8333, 11.8867, 11.9333, 11.98, 12.0267, 12.0733, 12.12, 12.1667, 12.22, 12.2667, 12.32, 12.3667, 12.42, 12.4667, 12.5133, 12.5667, 12.6133, 12.6667, 12.72, 12.7667, 12.82, 12.8733, 12.92, 12.9733,
      13.0267, 13.08, 13.1267, 13.18, 13.18, 13.18, 13.18, 13.18, 13.18, 13.18]
    f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0]
  features:
    f.list_days: 900
    f.is_suspended: false
    f.limit_up_price: 16.06
    f.limit_down_price: 10.7
    f.limit_locked_up: false
    f.limit_locked_down: false
    f.main_net_20d: 30000000.0
    f.np_yoy_latest: 12.0
    f.rsi14: 56.0
    f.market_regime: range
    f.ind_rs20: 1.5
  holding:
    qty: 600
    sellable: 600
  ctx:
    ctx.last_price: 13.38
    ctx.holding_days: 8
    ctx.sellable_qty: 600
    ctx.max_r_reached: 0.2
    ctx.highest_close_since_entry_qfq: 13.38
  plan:
    plan.entry_price: 19.92
    plan.entry_price_qfq: 13.28
    plan.stop_loss: 11.95
  expect:
    state: hold_ok
    action: hold
    rule_ids_passed: [E1, E2, E3, A1, F1, F2, F3]
- id: W01-FX13
  desc: 【虚构】除权·现金分红：A(d)=前 74 根 1.0、后 6 根 1.03；建仓不复权价 26.55，plan.entry_price_qfq=26.55/1.03；X6 不触发（误用不复权价会误触发）
  as_of: '2026-10-30'
  security:
    code: 300364.SZ
    board: chinext
    list_date: '2024-03-01'
  series:
    f.close_qfq: [19.4175, 19.4951, 19.5728, 19.6505, 19.7282, 19.8058, 19.8835, 19.9709, 20.0485, 20.1262, 20.2039, 20.2913, 20.3689, 20.4563, 20.534, 20.6117, 20.699, 20.7767, 20.8641, 20.9515, 21.0291,
      21.1165, 21.2039, 21.2816, 21.3689, 21.4563, 21.5437, 21.6311, 21.7184, 21.7961, 21.8835, 21.9709, 22.068, 22.1553, 22.2427, 22.3301, 22.4175, 22.5049, 22.6019, 22.6893, 22.7767, 22.8738, 22.9612,
      23.0583, 23.1456, 23.2427, 23.3301, 23.4272, 23.5146, 23.6117, 23.7087, 23.8058, 23.8932, 23.9903, 24.0874, 24.1845, 24.2816, 24.3786, 24.4757, 24.5728, 24.6699, 24.767, 24.8738, 24.9709, 25.068,
      25.1748, 25.2718, 25.3689, 25.4757, 25.5728, 25.6796, 25.7767, 25.8835, 25.9903, 25.99, 25.99, 25.99, 25.99, 25.99, 25.99]
    f.high_qfq: [19.4951, 19.5728, 19.6505, 19.7282, 19.8058, 19.8835, 19.9612, 20.0485, 20.1262, 20.2039, 20.2816, 20.3689, 20.4466, 20.534, 20.6117, 20.6893, 20.7864, 20.8641, 20.9515, 21.0388, 21.1165,
      21.2039, 21.2913, 21.3689, 21.4563, 21.5437, 21.6311, 21.7184, 21.8058, 21.8835, 21.9709, 22.0583, 22.1553, 22.2427, 22.3301, 22.4175, 22.5049, 22.5922, 22.6893, 22.7767, 22.8641, 22.9612, 23.0485,
      23.1456, 23.2427, 23.3398, 23.4272, 23.5243, 23.6117, 23.7087, 23.8058, 23.9029, 23.9903, 24.0874, 24.1845, 24.2816, 24.3786, 24.4757, 24.5728, 24.6699, 24.767, 24.8641, 24.9709, 25.068, 25.165, 25.2718,
      25.3689, 25.466, 25.5728, 25.6796, 25.7864, 25.8835, 25.9903, 26.0971, 26.09, 26.09, 26.09, 26.09, 26.09, 26.09]
    f.low_qfq: [19.3398, 19.4175, 19.4951, 19.5728, 19.6505, 19.7282, 19.8058, 19.8932, 19.9709, 20.0485, 20.1262, 20.2136, 20.2913, 20.3786, 20.4563, 20.534, 20.6117, 20.6893, 20.7767, 20.8641, 20.9417,
      21.0291, 21.1165, 21.1942, 21.2816, 21.3689, 21.4563, 21.5437, 21.6311, 21.7087, 21.7961, 21.8835, 21.9806, 22.068, 22.1553, 22.2427, 22.3301, 22.4175, 22.5146, 22.6019, 22.6893, 22.7864, 22.8738,
      22.9709, 23.0485, 23.1456, 23.233, 23.3301, 23.4175, 23.5146, 23.6117, 23.7087, 23.7961, 23.8932, 23.9903, 24.0874, 24.1845, 24.2816, 24.3786, 24.4757, 24.5728, 24.6699, 24.7767, 24.8738, 24.9709,
      25.0777, 25.1748, 25.2718, 25.3786, 25.466, 25.5728, 25.6699, 25.7767, 25.8835, 25.89, 25.89, 25.89, 25.89, 25.89, 25.89]
    f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0]
  features:
    f.list_days: 600
    f.is_suspended: false
    f.limit_up_price: 31.19
    f.limit_down_price: 20.79
    f.limit_locked_up: false
    f.limit_locked_down: false
    f.main_net_20d: 30000000.0
    f.np_yoy_latest: 12.0
    f.rsi14: 56.0
    f.market_regime: range
    f.ind_rs20: 1.5
  holding:
    qty: 1000
    sellable: 1000
  ctx:
    ctx.last_price: 25.99
    ctx.holding_days: 8
    ctx.sellable_qty: 1000
    ctx.max_r_reached: 0.1
    ctx.highest_close_since_entry_qfq: 25.99
  plan:
    plan.entry_price: 26.55
    plan.entry_price_qfq: 25.7767
    plan.stop_loss: 23.2
  expect:
    state: hold_ok
    action: hold
    rule_ids_passed: [E1, E2, E3, A1, F1, F2]
- id: W01-FX15
  desc: 【虚构】跟踪止盈跨除权：10 送 5，A(d)=前 74 根 1.0、后 6 根 1.5；入场以来最高不复权收盘 20.07（除权前）→ ctx.highest_close_since_entry_qfq=20.07×1.0/1.5；已达 2.5R，X5 按 qfq 不触发（误用不复权最高价会误触发）
  as_of: '2026-10-30'
  security:
    code: 688073.SH
    board: star
    list_date: '2023-01-03'
  series:
    f.close_qfq: [10.0, 10.04, 10.08, 10.12, 10.16, 10.2, 10.24, 10.2867, 10.3267, 10.3667, 10.4067, 10.4467, 10.4933, 10.5333, 10.5733, 10.62, 10.66, 10.7, 10.7467, 10.7867, 10.8333, 10.8733, 10.92, 10.96,
      11.0067, 11.0467, 11.0933, 11.14, 11.18, 11.2267, 11.2733, 11.32, 11.36, 11.4067, 11.4533, 11.5, 11.5467, 11.5933, 11.64, 11.6867, 11.7333, 11.78, 11.8267, 11.8733, 11.92, 11.9667, 12.0133, 12.0667,
      12.1133, 12.16, 12.2067, 12.26, 12.3067, 12.3533, 12.4067, 12.4533, 12.5067, 12.5533, 12.6067, 12.6533, 12.7067, 12.76, 12.8067, 12.86, 12.9133, 12.96, 13.0133, 13.0667, 13.12, 13.1733, 13.2267, 13.28,
      13.3267, 13.38, 13.38, 13.38, 13.38, 13.38, 13.38, 13.38]
    f.high_qfq: [10.1467, 10.1933, 10.2333, 10.2733, 10.3133, 10.3533, 10.3933, 10.44, 10.48, 10.52, 10.56, 10.6067, 10.6533, 10.6933, 10.7333, 10.78, 10.82, 10.86, 10.9067, 10.9467, 10.9933, 11.0333, 11.0867,
      11.1267, 11.1733, 11.2133, 11.26, 11.3067, 11.3467, 11.3933, 11.44, 11.4867, 11.5333, 11.58, 11.6267, 11.6733, 11.72, 11.7667, 11.8133, 11.86, 11.9067, 11.96, 12.0067, 12.0533, 12.1, 12.1467, 12.1933,
      12.2467, 12.2933, 12.34, 12.3867, 12.4467, 12.4933, 12.54, 12.5933, 12.64, 12.6933, 12.74, 12.7933, 12.84, 12.9, 12.9533, 13.0, 13.0533, 13.1067, 13.1533, 13.2067, 13.26, 13.32, 13.3733, 13.4267,
      13.48, 13.5267, 13.58, 13.58, 13.58, 13.58, 13.58, 13.58, 13.58]
    f.low_qfq: [9.8533, 9.8867, 9.9267, 9.9667, 10.0067, 10.0467, 10.0867, 10.1333, 10.1733, 10.2133, 10.2533, 10.2867, 10.3333, 10.3733, 10.4133, 10.46, 10.5, 10.54, 10.5867, 10.6267, 10.6733, 10.7133,
      10.7533, 10.7933, 10.84, 10.88, 10.9267, 10.9733, 11.0133, 11.06, 11.1067, 11.1533, 11.1867, 11.2333, 11.28, 11.3267, 11.3733, 11.42, 11.4667, 11.5133, 11.56, 11.6, 11.6467, 11.6933, 11.74, 11.7867,
      11.8333, 11.8867, 11.9333, 11.98, 12.0267, 12.0733, 12.12, 12.1667, 12.22, 12.2667, 12.32, 12.3667, 12.42, 12.4667, 12.5133, 12.5667, 12.6133, 12.6667, 12.72, 12.7667, 12.82, 12.8733, 12.92, 12.9733,
      13.0267, 13.08, 13.1267, 13.18, 13.18, 13.18, 13.18, 13.18, 13.18, 13.18]
    f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0]
  features:
    f.list_days: 900
    f.is_suspended: false
    f.limit_up_price: 16.06
    f.limit_down_price: 10.7
    f.limit_locked_up: false
    f.limit_locked_down: false
    f.main_net_20d: 30000000.0
    f.np_yoy_latest: 12.0
    f.rsi14: 56.0
    f.market_regime: range
    f.ind_rs20: 1.5
  holding:
    qty: 800
    sellable: 800
  ctx:
    ctx.last_price: 13.38
    ctx.holding_days: 39
    ctx.sellable_qty: 800
    ctx.max_r_reached: 2.5
    ctx.highest_close_since_entry_qfq: 13.38
  plan:
    plan.entry_price: 17.6
    plan.entry_price_qfq: 11.7333
    plan.stop_loss: 10.56
  expect:
    state: hold_ok
    action: hold
    rule_ids_passed: [E1, E2, E3, A1, F1, F2, F3]
- id: W01-FX14
  desc: 【虚构】ATR 口径锁定：Wilder ATR14 ≥ 84bp 而 SMA ATR14 < 84bp → F3 按 Wilder 满足 → entry_ok（若误用 SMA 则 not_triggered）
  as_of: '2026-10-30'
  security:
    code: 688073.SH
    board: star
    list_date: '2023-01-03'
  series:
    f.close_qfq: [20.0, 20.08, 20.16, 20.24, 20.32, 20.4, 20.48, 20.57, 20.65, 20.73, 20.81, 20.9, 20.98, 21.07, 21.15, 21.23, 21.32, 21.4, 21.49, 21.58, 21.66, 21.75, 21.84, 21.92, 22.01, 22.1, 22.19,
      22.28, 22.37, 22.45, 22.54, 22.63, 22.73, 22.82, 22.91, 23.0, 23.09, 23.18, 23.28, 23.37, 23.46, 23.56, 23.65, 23.75, 23.84, 23.94, 24.03, 24.13, 24.22, 24.32, 24.42, 24.52, 24.61, 24.71, 24.81, 24.91,
      25.01, 25.11, 25.21, 25.31, 25.41, 25.51, 25.62, 25.72, 25.82, 25.93, 26.03, 26.13, 26.24, 26.34, 26.45, 26.55, 26.66, 26.77, 26.61, 26.45, 26.29, 26.39, 26.5, 26.6]
    f.high_qfq: [20.6, 20.68, 20.76, 20.85, 20.93, 21.01, 21.09, 21.19, 21.27, 21.35, 21.43, 21.53, 21.61, 21.7, 21.78, 21.87, 21.96, 22.04, 22.13, 22.23, 22.31, 22.4, 22.5, 22.58, 22.67, 22.76, 22.86,
      22.95, 23.04, 23.12, 23.22, 23.31, 23.41, 23.5, 23.6, 23.69, 23.78, 23.88, 23.98, 24.07, 24.16, 24.27, 24.36, 24.46, 24.56, 24.66, 24.75, 24.85, 24.95, 25.05, 25.15, 25.26, 25.35, 25.45, 25.55, 25.66,
      25.76, 25.86, 25.97, 26.07, 26.17, 26.28, 26.39, 26.49, 26.59, 26.71, 26.06, 26.16, 26.27, 26.37, 26.48, 26.58, 26.69, 26.8, 26.64, 26.48, 26.32, 26.42, 26.53, 26.63]
    f.low_qfq: [19.4, 19.48, 19.56, 19.63, 19.71, 19.79, 19.87, 19.95, 20.03, 20.11, 20.19, 20.27, 20.35, 20.44, 20.52, 20.59, 20.68, 20.76, 20.85, 20.93, 21.01, 21.1, 21.18, 21.26, 21.35, 21.44, 21.52,
      21.61, 21.7, 21.78, 21.86, 21.95, 22.05, 22.14, 22.22, 22.31, 22.4, 22.48, 22.58, 22.67, 22.76, 22.85, 22.94, 23.04, 23.12, 23.22, 23.31, 23.41, 23.49, 23.59, 23.69, 23.78, 23.87, 23.97, 24.07, 24.16,
      24.26, 24.36, 24.45, 24.55, 24.65, 24.74, 24.85, 24.95, 25.05, 25.15, 26.0, 26.1, 26.21, 26.31, 26.42, 26.52, 26.63, 26.74, 26.58, 26.42, 26.26, 26.36, 26.47, 26.57]
    f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0,
      200000000.0]
  features:
    f.list_days: 900
    f.is_suspended: false
    f.limit_up_price: 31.8
    f.limit_down_price: 21.2
    f.limit_locked_up: false
    f.limit_locked_down: false
    f.main_net_20d: 30000000.0
    f.np_yoy_latest: 12.0
    f.rsi14: 56.0
    f.market_regime: range
    f.ind_rs20: 1.5
  expect:
    state: entry_ok
    action: buy
    rule_ids_passed: [E1, E2, E3, A1, F1, F2, F3]
    lot_rule:
      min_buy: 200
      step: 1
      odd_lot_sell_all: false
```
