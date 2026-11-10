# S-01 短线·强势股回踩 `st_pullback_ma` — 正式卡 v2（T-R55；v1 为 T-R25 首次正式化）
> **v2 变更（T-R55，按编排者裁定 S-01 升 v2）**：v1 原文冻结在 `cards/history/st_pullback_ma.v1.md`（v1 原文冻结＝提交 055105a 的卡，即 T-B100 导入库内的 v1 内容；库内 v1 审核作废，须按 v2 重新导入并重跑 G1–G6）。相对 055105a，v1 版本号下曾有两次未升号的改动，现随 v2 一并生效：① fe2afa5（T-R40）：S01-FX1–FX8 八个夹具的 desc 前缀改为「【虚构】」（原为【入场】【不满足】等场景标签），夹具数值与期望不变；② 4c00ae7（T-R43）：卡头「与草稿的差异」增 ③「v1 选股只扫持仓 ∪ 自选」说明（screen:null、全市场 DSL 暂缓，T-A83 ④）；validation 末尾新增 S01-FX9（反证 C1 正例）与 S01-FX10（反证 C2 正例）两个【虚构】夹具。规则、参数、阈值、data_needs、universe、screen、costs 均未改；本次只把 version_no 1→2（:29、:92），并改本标题与本行。
> 正式卡（由 T-R16/S-01_st_pullback_ma.md 草稿正式化；草稿保留过程记录）。导入格式：plan 2.5.14 A 节三个带标签块，导入器只读这三块，正文存为 `narrative`。
> 夹具全部数值**虚构**；`600000.SH` 为 plan 2.5.14 A 允许的虚构示例代码，不代表任何真实行情。期望值由规则确定性推得（与 T-R15 卡同法）；导入时若 T-B71 fixture 执行器 diff，以实跑为准回修。
> 结论只由规则决定；AI 只做中文解释。与其他卡结论相反时并列展示，不合并（P4）。
> **与草稿的差异（v1 正式化裁定，研究员权限内）**：① E1 由截面分位 `rank_pct(pct_change(...))` 改为绝对涨幅阈值 `pct_change(f.close_qfq, 20) >= p.rs_min`——`rank_pct` 在 DSL 白名单内但求值器未实现（src/backend/app/features/pipeline.py「never guess」分支返回 None），截面输入契约属 T-B72；截面分位版待其落地后升 v2。② X4 结构止损（`plan.stop_loss_qfq`，QFQ-1）不进 v1 规则集，止损用入场价比例止损（X2）；QFQ-1 实现后升版补入。其余规则、阈值、参数与草稿复核版一致。 ③ **v1 选股只扫「持仓 ∪ 自选」**（T-R43 注明）：`screen: null`（spec:140），v1 不做全市场扫描；`universe.pool` 所写「全市场」部分待全市场选股 DSL 落地后随升版生效（该 DSL 暂缓，T-A83 ④）。

## 规则摘要
- **入场（E1–E4 全部为真才 `entry_ok`）**：E1 20 日涨幅 ≥ `rs_min`（强势）；E2 MA5>MA10>MA20 多头排列；E3 当日最低回踩 MA10 上方 `touch_pct` 以内且收盘不破 MA10；E4 当日成交额 < 5 日均额×`shrink_ratio`（缩量）。
- **过滤**：F1 20 日均额 ≥ `min_amount`；F2 上市 ≥ `min_list_days`。**否决**：V1 大盘（沪深300 指数口径 `f.market_regime_idx`）`downtrend`。
- **反证（并列展示，不抵消）**：C1 回踩日单日跌幅 < −5%（疑似出货）；C2 放量回落。**失效**：I1 MA5 跌破 MA10（多头排列前提消失）。
- **退出（任一为真 → `exit_signal`/sell）**：X1 收盘连续 `exit_confirm_days` 日低于 MA10（趋势失效）；X2 收盘 ≤ 入场价×(1−`hard_stop_pct`)（止损，买入当日 T+1 不可卖由执行层 `T1_NOT_SELLABLE` 阻断）；X3 持有 ≥ `time_stop` 日且未达 1R（时间止损）。
- **优先级**：持有中 → exit > hold；未持有 → veto > insufficient_data > entry_ok > not_triggered。

## 时点 / 单位 / 复权 / 预热
- 日线盘后（`daily_close`）求值，只用 as_of 当日及以前的有效日 K；信号最早 T+1 09:30 执行，模拟入场价 = T+1 开盘价。无未来数据。
- 价格统一 qfq@as_of（T-R15 ⓪）：`x_qfq(d)=x(d)×A(d)/A(T)`；止损引用的 `plan.entry_price_qfq` 由求值器派生。成交额 `f.amount` 单位元。
- 预热：MA20 + 20 日涨幅 = 21 根；5/10/20 日均线与涨幅取最大窗口 21 根 → **warmup 25 根有效日 K**（含缓冲）；停牌日不计入有效 K；不足 → `insufficient_data`。
- 板块约束：主板/创业板/科创板（北交所不含）；涨跌停价按 `config/market_rules.yaml` 生效段（创业板/科创板 20%；注册制新股前 5 日无涨跌幅，`f.limit_*_price = null`）；止损价截断到涨跌停价之内。T+1：买入当日可卖 0，卖出信号照常、执行层 `T1_NOT_SELLABLE`。整手：科创板 ≥200 股、1 股递增，其余 100 股整数倍；零股一次性卖出。

## 成本与滑点（estimate）
佣金按用户费率（单笔最低 5 元）；印花税卖出 0.05%；过户费双向 0.001%；基础滑点 `slippage_bp` 10bp；冲击成本按参与率 5 档（plan 2.13，待校准）。

## 反证 / 失效（研究侧）
反证：缩量回踩若发生在放量下跌后（C1/C2 命中），抛压未必出清。失效：多头排列消失（I1）后本卡前提不再成立。证伪见 `hypothesis.falsified_by`。

```yaml strategy-card
key: st_pullback_ma
version_no: 2
name: 短线·强势股回踩
category: momentum
horizons: [short]
card_id: S-01
risk_level: normal
hypothesis:
  why_it_works: 短期强势、均线多头排列的股票，在缩量回踩 MA10 不破时抛压较轻，趋势容易延续
  falsified_by:
    - 样本外信号后 5 个交易日扣费超额（对所属行业指数）中位数 <= 0
    - 模拟跟踪 n >= 30 后 5 日胜率 < 45%
    - 参数邻域（rs_min ±0.05、shrink_ratio ±0.1）内结论符号翻转
dimensions:
  - {dimension: technical, role: core}
  - {dimension: sector_market, role: veto}
entry:
  - {ref: E1, text: 20 日涨幅达到绝对强势阈值, status: quantified}
  - {ref: E2, text: MA5>MA10>MA20 多头排列, status: quantified}
  - {ref: E3, text: 当日最低回踩 MA10 上方 touch_pct 以内且收盘不破 MA10, status: quantified}
  - {ref: E4, text: 当日成交额低于 5 日均额的 shrink_ratio 倍（缩量）, status: quantified}
counter_evidence:
  - {ref: C1, text: 回踩日单日跌幅大于 5%，可能是出货, status: quantified}
  - {ref: C2, text: 放量回落, status: quantified}
invalidation:
  - {ref: I1, text: MA5 跌破 MA10，多头排列前提消失, status: quantified}
exit:
  - {ref: X1, text: 收盘连续 exit_confirm_days 日低于 MA10（趋势失效）, status: quantified}
  - {ref: X2, text: 收盘跌破入场价 8%（止损类）, status: quantified}
  - {ref: X3, text: 持有满 time_stop 日未达 1R（时间止损）, status: quantified}
data_needs:
  - {feature_key: f.close_qfq, frequency: daily, adjust: qfq, available_at: T 日日线入库后}
  - {feature_key: f.low_qfq, frequency: daily, adjust: qfq, available_at: T 日日线入库后}
  - {feature_key: f.amount, frequency: daily, adjust: none, available_at: T 日日线入库后}
  - {feature_key: f.list_days, frequency: daily, adjust: none, available_at: T 日 18:00 主数据后}
  - {feature_key: f.market_regime_idx, frequency: daily, adjust: none, available_at: T 日盘后（沪深300 日线落库后，F50）}
  - {feature_key: f.limit_up_price, frequency: daily, adjust: none, available_at: T 日开盘前（无涨跌幅日为 null）}
  - {feature_key: f.limit_locked_up, frequency: daily, adjust: none, available_at: T 日日线入库后}
  - {feature_key: f.is_suspended, frequency: daily, adjust: none, available_at: T 日日线入库后（sf）}
epistemic:
  hypothesis: hypothesis
  params_schema.rs_min: hypothesis
  params_schema.touch_pct: hypothesis
  params_schema.shrink_ratio: hypothesis
  params_schema.exit_confirm_days: hypothesis
  params_schema.hard_stop_pct: hypothesis
  params_schema.time_stop: hypothesis
  params_schema.min_amount: hypothesis
  params_schema.min_list_days: hypothesis
  params_schema.slippage_bp: estimate
universe:
  pool: 全市场（持仓 ∪ 自选优先）
  boards: {main: true, chinext: true, star: true, bse: false}
  exclude: [ST、停牌、上市不足 min_list_days 由 G-01/F2 处理]
pitfalls:
  - 把下跌趋势中的反弹当作回踩（由 E2 多头排列与 V1 大盘否决防护）
  - 忽略 T+1：入场当天无法止损
  - 用在成交稀少的股票上，成交价远离参考价（由 F1 与冲击成本防护）
a_share_constraints: T+1；涨跌停按 config/market_rules.yaml 生效段；止损价截断到涨跌停价内；科创板整手 ≥200 股后 1 股递增，零股一次性卖出；北交所不含
validation_summary: {type: rule, window: 未执行, benchmark: 所属申万一级行业指数；对照中证全指, cost_model: plan 2.13 默认（含冲击成本分档）, oos_result: 未验证, trade_log_ref: null}
```

```yaml strategy-spec
key: st_pullback_ma
version_no: 2
kind: rule_template
horizons: [short]
params_schema:
  rs_min: {type: float, default: 0.15, min: 0.10, max: 0.30, step: 0.05, desc: 20 日涨幅绝对强势阈值, unit: ratio}
  touch_pct: {type: float, default: 0.01, min: 0.0, max: 0.03, step: 0.005, desc: 回踩触及 MA10 上方容忍带, unit: ratio}
  shrink_ratio: {type: float, default: 0.7, min: 0.5, max: 0.9, step: 0.05, desc: 缩量系数（当日额/5 日均额上限）, unit: ratio}
  exit_confirm_days: {type: int, default: 2, min: 1, max: 3, step: 1, desc: 跌破 MA10 确认天数, unit: 有效日K}
  hard_stop_pct: {type: float, default: 0.08, min: 0.05, max: 0.12, step: 0.01, desc: 硬止损比例, unit: ratio}
  time_stop: {type: int, default: 5, min: 3, max: 10, step: 1, desc: 时间止损天数, unit: 交易日}
  min_amount: {type: float, default: 50000000.0, min: 10000000.0, max: 500000000.0, step: 10000000.0, desc: 20 日均成交额下限, unit: CNY}
  min_list_days: {type: int, default: 60, min: 30, max: 250, step: 10, desc: 上市交易日下限, unit: 交易日}
  slippage_bp: {type: float, default: 10.0, min: 0.0, max: 50.0, step: 1.0, desc: 基础滑点, unit: bp}
rules:
  - {id: E1, dimension: technical, role: entry, weight: 2, eval_time: daily_close, status: quantified,
     expr: "pct_change(f.close_qfq, 20) >= p.rs_min", required_features: [f.close_qfq],
     edge_cases: 有效 K < 21 → insufficient_data}
  - {id: E2, dimension: technical, role: entry, weight: 2, eval_time: daily_close, status: quantified,
     expr: "ma(f.close_qfq, 5) > ma(f.close_qfq, 10) and ma(f.close_qfq, 10) > ma(f.close_qfq, 20)",
     required_features: [f.close_qfq]}
  - {id: E3, dimension: technical, role: entry, weight: 2, eval_time: daily_close, status: quantified,
     expr: "f.low_qfq <= ma(f.close_qfq, 10) * (1 + p.touch_pct) and f.close_qfq >= ma(f.close_qfq, 10)",
     required_features: [f.low_qfq, f.close_qfq]}
  - {id: E4, dimension: technical, role: entry, weight: 1, eval_time: daily_close, status: quantified,
     expr: "f.amount < ma(f.amount, 5) * p.shrink_ratio", required_features: [f.amount]}
  - {id: F1, dimension: technical, role: filter, weight: 0, eval_time: daily_close, status: quantified,
     expr: "ma(f.amount, 20) >= p.min_amount", required_features: [f.amount]}
  - {id: F2, dimension: technical, role: filter, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.list_days >= p.min_list_days", required_features: [f.list_days]}
  - {id: V1, dimension: sector_market, role: veto, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.market_regime_idx == 'downtrend'", required_features: [f.market_regime_idx]}
  - {id: C1, dimension: technical, role: counter, weight: 0, eval_time: daily_close, status: quantified,
     expr: "pct_change(f.close_qfq, 1) < -0.05", required_features: [f.close_qfq]}
  - {id: C2, dimension: technical, role: counter, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.amount > ma(f.amount, 20) * 1.5", required_features: [f.amount]}
  - {id: I1, dimension: technical, role: invalidation, weight: 0, eval_time: daily_close, status: quantified,
     expr: "ma(f.close_qfq, 5) < ma(f.close_qfq, 10)", required_features: [f.close_qfq]}
  - {id: X1, dimension: technical, role: exit, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.close_qfq < ma(f.close_qfq, 10) for p.exit_confirm_days days", required_features: [f.close_qfq]}
  - {id: X2, dimension: technical, role: exit, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.close_qfq <= plan.entry_price_qfq * (1 - p.hard_stop_pct)", required_features: [],
     edge_cases: 买入当日可卖 0，信号照常，执行层记 T1_NOT_SELLABLE}
  - {id: X3, dimension: technical, role: exit, weight: 0, eval_time: daily_close, status: quantified,
     expr: "ctx.holding_days >= p.time_stop and ctx.max_r_reached < 1", required_features: []}
action_map: {entry_all_core_pass: buy, held_hold: hold, exit: sell, else: wait}
stops: {stop_loss: "plan.entry_price_qfq * (1 - p.hard_stop_pct)", take_profit: null, time_stop_days: 5}
dimension_view_thresholds: {bullish: 0.67, bearish: 0.33}
valid_until: {trading_days: 1}
screen: null
```

```yaml validation
methods: [fixture, trigger_stats, tracking_sim]
window: {lookback_trading_days: 120, universe: 全A（不含北交所）}
horizon_days: [1, 5]
metrics: [trigger_rate, coverage, win_rate, avg_excess]
min_n: 30
pass_criteria:
  - {metric: trigger_rate, op: "<=", value: 0.30}
  - {metric: trigger_rate, op: ">", value: 0}
fixtures:
  - id: S01-FX1
    desc: 【虚构】入场：强势+多头排列+缩量回踩 MA10 不破 → entry_ok/buy
    as_of: '2026-10-30'
    security: {code: 600000.SH, board: main, list_date: '2020-01-02'}
    series:
      f.close_qfq: [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.25, 10.5, 10.75, 11.0, 11.25, 11.5, 11.75, 12.0, 12.25, 12.5]
      f.low_qfq: [9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 10.15, 10.4, 10.65, 10.9, 11.15, 11.4, 11.65, 11.9, 12.15, 11.0]
      f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 100000000.0]
    features:
      f.list_days: 600
      f.is_suspended: false
      f.limit_up_price: 13.75
      f.limit_down_price: 11.25
      f.limit_locked_up: false
      f.limit_locked_down: false
      f.market_regime_idx: uptrend
    expect:
      state: entry_ok
      action: buy
      rule_ids_passed: [E1, E2, E3, E4, F1, F2]
      reason_codes: []
  - id: S01-FX2
    desc: 【虚构】不满足：未回踩（最低价远离 MA10）且未缩量 → not_triggered/wait
    as_of: '2026-10-30'
    security: {code: 600000.SH, board: main, list_date: '2020-01-02'}
    series:
      f.close_qfq: [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.25, 10.5, 10.75, 11.0, 11.25, 11.5, 11.75, 12.0, 12.25, 12.5]
      f.low_qfq: [9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 10.15, 10.4, 10.65, 10.9, 11.15, 11.4, 11.65, 11.9, 12.15, 12.3]
      f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0]
    features:
      f.list_days: 600
      f.is_suspended: false
      f.limit_up_price: 13.75
      f.limit_down_price: 11.25
      f.limit_locked_up: false
      f.limit_locked_down: false
      f.market_regime_idx: uptrend
    expect:
      state: not_triggered
      action: wait
      rule_ids_passed: [E1, E2, F1, F2]
      reason_codes: []
  - id: S01-FX3
    desc: 【虚构】缺数据：有效 K 仅 10 根（warmup 25 不足）→ insufficient_data/wait
    as_of: '2026-10-30'
    security: {code: 600000.SH, board: main, list_date: '2026-09-15'}
    series:
      f.close_qfq: [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
      f.low_qfq: [9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9]
      f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0]
    features:
      f.list_days: 600
      f.is_suspended: false
      f.limit_up_price: 11.0
      f.limit_down_price: 9.0
      f.limit_locked_up: false
      f.limit_locked_down: false
      f.market_regime_idx: uptrend
    expect:
      state: insufficient_data
      action: wait
      rule_ids_passed: [E3, F2]
      reason_codes: []
  - id: S01-FX4
    desc: 【虚构】维度分歧：入场条件全满足但大盘 downtrend 否决 → vetoed/wait
    as_of: '2026-10-30'
    security: {code: 600000.SH, board: main, list_date: '2020-01-02'}
    series:
      f.close_qfq: [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.25, 10.5, 10.75, 11.0, 11.25, 11.5, 11.75, 12.0, 12.25, 12.5]
      f.low_qfq: [9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 10.15, 10.4, 10.65, 10.9, 11.15, 11.4, 11.65, 11.9, 12.15, 11.0]
      f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 100000000.0]
    features:
      f.list_days: 600
      f.is_suspended: false
      f.limit_up_price: 13.75
      f.limit_down_price: 11.25
      f.limit_locked_up: false
      f.limit_locked_down: false
      f.market_regime_idx: downtrend
    expect:
      state: vetoed
      action: wait
      rule_ids_passed: [E1, E2, E3, E4, F1, F2, V1]
      reason_codes: []
  - id: S01-FX5
    desc: 【虚构】一字涨停：入场成立但买入方向 LIMIT_LOCKED，不可执行
    as_of: '2026-10-30'
    security: {code: 600000.SH, board: main, list_date: '2020-01-02'}
    series:
      f.close_qfq: [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.25, 10.5, 10.75, 11.0, 11.25, 11.5, 11.75, 12.0, 12.25, 12.5]
      f.low_qfq: [9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 10.15, 10.4, 10.65, 10.9, 11.15, 11.4, 11.65, 11.9, 12.15, 11.0]
      f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 100000000.0]
    features:
      f.list_days: 600
      f.is_suspended: false
      f.limit_up_price: 13.75
      f.limit_down_price: 11.25
      f.limit_locked_up: true
      f.limit_locked_down: false
      f.market_regime_idx: uptrend
    expect:
      state: entry_ok
      action: buy
      rule_ids_passed: [E1, E2, E3, E4, F1, F2]
      reason_codes: [LIMIT_LOCKED]
      reason_details: {LIMIT_LOCKED: {direction: buy}}
  - id: S01-FX6
    desc: 【虚构】停牌：入场成立但标的停牌，不可执行
    as_of: '2026-10-30'
    security: {code: 600000.SH, board: main, list_date: '2020-01-02'}
    series:
      f.close_qfq: [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.25, 10.5, 10.75, 11.0, 11.25, 11.5, 11.75, 12.0, 12.25, 12.5]
      f.low_qfq: [9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 10.15, 10.4, 10.65, 10.9, 11.15, 11.4, 11.65, 11.9, 12.15, 11.0]
      f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 100000000.0]
    features:
      f.list_days: 600
      f.is_suspended: true
      f.limit_up_price: 13.75
      f.limit_down_price: 11.25
      f.limit_locked_up: false
      f.limit_locked_down: false
      f.market_regime_idx: uptrend
    expect:
      state: entry_ok
      action: buy
      rule_ids_passed: [E1, E2, E3, E4, F1, F2]
      reason_codes: [SUSPENDED]
      reason_details: {SUSPENDED: {direction: buy}}
  - id: S01-FX7
    desc: 【虚构】可卖 0 时卖出信号：持有中跌破止损（X2）与 MA10（X1），当日买入部分 T+1 不可卖
    as_of: '2026-10-30'
    security: {code: 600000.SH, board: main, list_date: '2020-01-02'}
    series:
      f.close_qfq: [13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 12.85, 12.7, 12.55, 12.4, 12.25, 12.1, 11.95, 11.8, 11.65, 11.5]
      f.low_qfq: [12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.75, 12.6, 12.45, 12.3, 12.15, 12.0, 11.85, 11.7, 11.55, 11.4]
      f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0]
    features:
      f.list_days: 600
      f.is_suspended: false
      f.limit_up_price: 14.3
      f.limit_down_price: 11.7
      f.limit_locked_up: false
      f.limit_locked_down: false
      f.market_regime_idx: uptrend
    holding: {qty: 2000, sellable: 0}
    ctx:
      ctx.holding_days: 3
      ctx.max_r_reached: 0.5
    plan:
      plan.entry_price_qfq: 12.9
    expect:
      state: exit_signal
      action: sell
      rule_ids_passed: [F1, F2, I1, X1, X2]
      reason_codes: [T1_NOT_SELLABLE]
  - id: S01-FX8
    desc: 【虚构】时间止损：持有满 time_stop 日未达 1R → exit_signal/sell（可卖充足）
    as_of: '2026-10-30'
    security: {code: 600000.SH, board: main, list_date: '2020-01-02'}
    series:
      f.close_qfq: [13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 12.85, 12.8, 12.75, 12.7, 12.65, 12.6, 12.55, 12.5, 12.45, 12.4]
      f.low_qfq: [12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.75, 12.7, 12.65, 12.6, 12.55, 12.5, 12.45, 12.4, 12.35, 12.3]
      f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0]
    features:
      f.list_days: 600
      f.is_suspended: false
      f.limit_up_price: 13.65
      f.limit_down_price: 11.15
      f.limit_locked_up: false
      f.limit_locked_down: false
      f.market_regime_idx: uptrend
    holding: {qty: 2000, sellable: 2000}
    ctx:
      ctx.holding_days: 5
      ctx.max_r_reached: 0.5
    plan:
      plan.entry_price_qfq: 12.9
    expect:
      state: exit_signal
      action: sell
      rule_ids_passed: [F1, F2, I1, X1, X3]
      reason_codes: []
  - id: S01-FX9
    desc: 【虚构】反证 C1 正例（T-R43）：强势多头后回踩日单日跌幅 −6.48%（< −5%）且缩量，但收盘跌破 MA10（E3 不成立）→ not_triggered/wait；C1 并列展示、不改结论
    as_of: '2026-10-30'
    security: {code: 600000.SH, board: main, list_date: '2020-01-02'}
    series:
      f.close_qfq: [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.5, 11.0, 11.5, 12.0, 12.5, 13.0, 13.5, 14.0, 14.5, 13.56]
      f.low_qfq: [9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 10.4, 10.9, 11.4, 11.9, 12.4, 12.9, 13.4, 13.9, 14.4, 13.51]
      f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 100000000.0]
    features:
      f.list_days: 600
      f.is_suspended: false
      f.limit_up_price: 14.92
      f.limit_down_price: 12.2
      f.limit_locked_up: false
      f.limit_locked_down: false
      f.market_regime_idx: uptrend
    expect:
      state: not_triggered
      action: wait
      rule_ids_passed: [E1, E2, E4, F1, F2, C1]
      reason_codes: []
  - id: S01-FX10
    desc: 【虚构】反证 C2 正例（T-R43）：同 FX2 走势，as_of 成交额 4 亿 > 20 日均额×1.5（放量）→ E4 不成立 → not_triggered/wait；C2 并列展示、不改结论
    as_of: '2026-10-30'
    security: {code: 600000.SH, board: main, list_date: '2020-01-02'}
    series:
      f.close_qfq: [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.25, 10.5, 10.75, 11.0, 11.25, 11.5, 11.75, 12.0, 12.25, 12.5]
      f.low_qfq: [9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 9.9, 10.15, 10.4, 10.65, 10.9, 11.15, 11.4, 11.65, 11.9, 12.15, 12.4]
      f.amount: [200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 200000000.0, 400000000.0]
    features:
      f.list_days: 600
      f.is_suspended: false
      f.limit_up_price: 13.75
      f.limit_down_price: 11.25
      f.limit_locked_up: false
      f.limit_locked_down: false
      f.market_regime_idx: uptrend
    expect:
      state: not_triggered
      action: wait
      rule_ids_passed: [E1, E2, F1, F2, C2]
      reason_codes: []
```
