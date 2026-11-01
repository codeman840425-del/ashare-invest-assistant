# 周期分类器规则 v1（T006a ①）

> 本文给出 plan §6.1 `config/horizon_classifier.yaml` 中留空的 `rules:`（plan 第 2277 行 `rules: {}`），以及 plan §2.5.3 所说的“正式规则与阈值”。
> 字段名对齐 `docs/api-contract.md` v0.2：`horizon` 枚举、`/horizon-assessments`、`TextWithEvidence`、`/me/profile`。
> **所有阈值与分值都是初值，待模拟跟踪校准**，不是统计结论，也没有回测依据。示例表中的数值全部为“示例”。
> 分类结果是**候选周期**，不是买卖建议。用户确认后才生效（plan §2.5.0、§9 C Q15）。

## 0. 粘贴位置（给架构师）

| 改动 | plan.md 位置 | 做法 |
|---|---|---|
| 规则正文 | §6.1 `config/horizon_classifier.yaml` 代码块，第 2277–2278 行（`rules: {}` 及其下一行注释） | 删除这两行，换成第 4 节的 `rules:` 整块（顶格缩进不变，块内 2 空格缩进） |
| 特征清单 | 同一代码块 `features:` 列表（第 2262–2276 行） | 按第 5 节补充新增键，并统一键名前缀（`f.` / `user.` / `profile.` / `sec.`） |
| 代码块后的说明 | 第 2280 行“`rules` 为空时……” | 保留；另加一句“规则见 docs/strategies/horizon_classifier.md v1” |
| §2.5.3 正文 | 第 535 行“正式规则与阈值由策略研究员在 docs/strategies/ 中给出” | 可在句末加“（见 horizon_classifier.md v1）”；示例阈值的措辞不用改 |

> `rules` 的结构（`gates` / `requires` / `components` / `bands`）是我方提议，导入器的解析方式需要架构师确认。若改成 DSL 字符串表达式，判定语义必须保持与第 3 节一致。

## 1. 输入

所有输入都取自同一份**评估快照**：T−1 交易日盘后落库的特征，加评估时点的持仓、画像版本和成交统计。同一快照、同一 `classifier_version` 必须得到完全相同的输出（确定性）。

| 键 | 类型 / 单位 | 来源 | 缺失时 |
|---|---|---|---|
| `sec.type` | `stock` / `etf` / `cb` / … | 证券主数据 | 视为非股票 → HG1 |
| `sec.board` | `main` / `chinext` / `star` / `bse` | 证券主数据 | 不得缺失（导入时即应有） |
| `f.is_st` | bool | 证券状态（同 G-01） | 视为 true（保守），理由写“风险警示状态未知” |
| `f.is_delisting_period` | bool | 证券状态 | 视为 false |
| `f.list_days` | int，交易日 | 同 G-01 | 视为 < 20 → HG5 |
| `f.amount_20d_avg` | 元 | 日 K 成交额 20 日均值 | 计入数据缺失 |
| `f.turnover_20d_avg` | 截面 `rank_pct` | feature_catalog | 计入数据缺失 |
| `f.volatility_20d` | 截面 `rank_pct` | feature_catalog | 计入数据缺失 |
| `f.intraday_amplitude_20d` | 截面 `rank_pct` | feature_catalog | 计入数据缺失 |
| `f.ma_trend` | 只用符号（> 0 = 多头） | feature_catalog | 计入数据缺失 |
| `f.momentum_60d` | 只用符号（> 0 = 上涨） | feature_catalog | 计入数据缺失 |
| `f.roe_ttm` | %（12 表示 12%） | feature_catalog | 计入数据缺失；long 封顶 59 |
| `f.profit_cagr_3y` | % | feature_catalog | 计入数据缺失（基期净利润 ≤ 0 时应为 null） |
| `f.dividend_continuous_years` | 年 | feature_catalog | 计入数据缺失 |
| `f.limit_up_count_20d` | 次 | feature_catalog | 计入数据缺失 |
| `f.fin_report_count` | 期 | 财报表 | 计入数据缺失；long 封顶 59 |
| `user.has_position` | bool，该账户当前持有数量 > 0 | 持仓 | 视为 false |
| `user.has_t_trades` | bool，导入成交中存在同日买卖 | 导入成交 | 视为“无记录”：0 分，**不算**数据缺失 |
| `user.avg_holding_days` | 交易日 | 导入成交（已平仓回合） | 同上 |
| `profile.horizon_pref` | `horizon[]` | `/me/profile` | 0 分，不算数据缺失 |
| `profile.effort` | `low` / `medium` / `high` | `/me/profile` | 0 分；相关 requires 视为不满足 |
| `profile.risk_tolerance` | int 1–5 | `/me/profile` | 同上 |
| `profile.experience` | `novice` / `intermediate` / `advanced` | `/me/profile` | 0 分 |

**单位约定。**
- 波动、振幅、换手这类特征的单位尚未实测（可能是小数也可能是百分数），一律用 T−1 截面的 `rank_pct`（平均秩 / N，取值 [0, 1]，并列取平均秩）。截面范围：沪深 A 股股票，剔除北交所、停牌股、上市不足 20 日的股票。
- 成交额用绝对值（元）。
- ROE 和增速按“百分数”假设；`unit` 字段写在规则里。导入器须比对 feature_catalog 的 unit，不一致就拒绝导入，不能静默换算。
- `f.ma_trend` 和 `f.momentum_60d` 只用符号，不依赖量纲。

`f.amihud_20d` 保留在 features 中，但 v1 规则不使用：它与日均成交额高度相关，重复计分会放大流动性的权重。

## 2. 输出（与契约一致）

`GET /horizon-assessments` 返回 `{suitable: horizon[], scores: {horizon: int}, reasons: [TextWithEvidence], classifier_version}`。

- `scores`：四个周期都要给。值为 0–100 的**整数**。
- `suitable`：`scores ≥ suitable_threshold`（60）的周期。按分数降序；同分时按 `tie_order` 排：long → swing → short → intraday_t（偏保守的在前）。
- `reasons`：每个周期 2–4 条（`reasons_per_horizon: [2, 4]`），每条是 `{text, expr, evidence_ids}`。
  - `text` 以“【周期】适合/不适合理由：”开头，引用特征值。
  - `expr` 写命中的条件，例如 `rank_pct(f.intraday_amplitude_20d) >= 0.7`。
  - `evidence_ids` 指向快照中的证据：特征证据，或者画像版本、成交统计对应的证据。
- 入库的 `symbol_horizon_assessments.reasons` 还带 `{horizon, polarity: for/against}`，但契约的 TextWithEvidence 没有这两个字段（见第 8 节缺口 1）。在契约补字段之前，前端只能靠 text 的前缀区分。

## 3. 判定顺序（确定性）

对每个周期 h ∈ [intraday_t, short, swing, long] 都执行以下步骤：

1. **闸门 `gates`**：按顺序全部求值，适用周期包含 h 且条件为真的都记录下来。
   - 带 `score: 0` 的：h 的最终分数记为 0。
   - 带 `cap` 的：记入封顶集合。
2. **周期前提 `requires`**：条件为假时，或者输入为 null 时（`not_null` 除外），执行 `else_score: 0` 或 `else_cap`。
3. **组件打分 `components`**：每个组件的 `bands` 自上而下取**第一条**为真的分档，得到 pts；都不满足则 0 分。输入为 null 时得 0 分；如果输入是 `f.*`，就把该组件的满分计入 `missing_points`。
4. **数据缺失封顶**：`missing_points ≥ 40` 时 cap 59。
5. **合成**：`raw = Σ pts`（四个周期的满分都是 100）。
   - 任一处给出 score 0 → `score = 0`。
   - 否则 `score = min(raw, 所有 cap)`。
   - 结果取整数（各分档本来就是整数）。
6. **suitable**：`score ≥ 60`。
7. **理由**：排序规则是 pts 降序，同分按组件顺序。
   - 适合理由：pts > 0 的组件。
   - 不适合理由的先后：闸门 → requires → 0 分且非缺失的组件（按满分降序）→ 数据缺失。
   - score ≥ 60：最多 3 条适合理由 + 1 条不适合理由（有才给）。
   - score < 60：至少 1 条、最多 2 条不适合理由 + 最多 2 条适合理由。
   - 不足 2 条时，补一条“【h】得分 X/100（阈值 60）”，`evidence_ids` 取空数组，`expr` 填 `score >= 60` 或 `score < 60`。
8. **之后的策略匹配**（plan §2.5.3 的后续步骤，不属于分类器打分）：
   - 范围：每个 suitable 周期下的策略模板，按 `applicability` / `fit_dimensions` 匹配。
   - 排除：`risk_level: high` 的卡（Q11，例如 S-03）；不可执行的卡（N-03）。
   - 系统组件 H-01 / G-01 / N-01 不经分类器，由系统挂载（C(3)）。
   - 结果生成 `status=proposed` 的实例，用户确认后才生效（Q15）。
9. **用户覆盖**：用户选了不在 suitable 中的周期时，需要 `fit_ack`（否则返回 `422 STRATEGY_FIT_ACK_REQUIRED`）。确认后 `horizon_assessment.user_overridden = true`，之后重算不改用户的选择；suitable 集合变化时只提示“系统建议已变化”。

**重算触发**沿用 plan：`import_confirm`、`watchlist_add`、每周六。建议架构师考虑增加“持仓清零 / 新建仓”这个触发：intraday_t 依赖 `user.has_position`，周内变化时最多滞后一周。T 卡运行时另有 `NO_POSITION` / `T1_NOT_SELLABLE` 拦截，所以滞后不会导致错误执行。

## 4. 规则正文（粘贴到 plan §6.1，替换 `rules: {}`）

```yaml
rules:
  rule_schema: 1                     # 本规则块的结构版本（建议，待架构师确认导入器）
  calibration: initial_values        # 全部阈值与分值为初值，待模拟跟踪/内部评估校准；不是统计结论
  rank_pct_universe: "T−1 日盘后落库截面：沪深 A 股股票，剔除北交所、停牌、上市 < 20 个交易日；平均秩 / N，取值 [0, 1]"
  data_missing_cap: {missing_points_ge: 40, cap: 59}   # 某周期中因 f.* 缺失而拿不到的满分合计 ≥ 40 → 该周期最高 59 分
  tie_order: [long, swing, short, intraday_t]          # suitable[] 同分时的排序
  gates:                             # 按顺序全部求值；score 取 0 优先，其次取最小 cap
    - {id: HG1, input: sec.type, op: ne, value: stock, horizons: all, score: 0,
       reason: "分类器只覆盖 A 股股票（ETF、可转债等不分类）"}
    - {id: HG2, input: sec.board, op: eq, value: bse, horizons: all, score: 0,
       reason: "首版不含北交所（plan 第 9 节 C(8)）"}
    - {id: HG3, input: f.is_delisting_period, op: eq, value: true, horizons: all, score: 0,
       reason: "退市整理期：不分类"}
    - {id: HG4, input: f.is_st, op: eq, value: true, horizons: all, cap: 59,
       reason: "风险警示股票（ST/*ST）：可交易性闸门阻断买入方向，不列为适合"}
    - {id: HG5, input: f.list_days, op: lt, value: 20, horizons: all, cap: 59,
       reason: "上市不足 20 个交易日：历史太短"}
    - {id: HG6, input: f.list_days, op: lt, value: 60, horizons: [swing, long], cap: 59,
       reason: "上市不足 60 个交易日：60 日趋势与动量无法计算"}
  horizons:
    intraday_t:
      requires:
        - {id: IT0, input: user.has_position, op: eq, value: true, else_score: 0,
           reason: "做T 需要已有底仓（T+1：当日买入不能当日卖出）"}
        - {id: IT0B, input: profile.effort, op: in, value: [medium, high], else_cap: 59,
           reason: "做T 需要盘中盯盘，画像精力为低或未填写"}
        - {id: IT0C, input: profile.experience, op: in, value: [intermediate, advanced], else_cap: 59,
           reason: "做T 需要盘中决断与纪律，画像经验为新手或未填写"}   # 编排者默认，用户可否决（2026-11-01）
      components:
        - {id: IT1, input: f.intraday_amplitude_20d, transform: rank_pct,
           bands: [{op: ge, value: 0.7, pts: 30}, {op: ge, value: 0.5, pts: 20}, {op: ge, value: 0.3, pts: 10}],
           text: "近 20 日日内振幅位于全市场 {v:pct} 分位"}
        - {id: IT2, input: f.amount_20d_avg, unit: CNY,
           bands: [{op: ge, value: 500000000, pts: 25}, {op: ge, value: 200000000, pts: 15}, {op: ge, value: 100000000, pts: 5}],
           text: "近 20 日日均成交额 {v:yi} 亿元"}
        - {id: IT3, input: profile.effort,
           bands: [{op: eq, value: high, pts: 20}, {op: eq, value: medium, pts: 10}],
           text: "画像精力：{v}"}
        - {id: IT4, input: user.has_t_trades,
           bands: [{op: eq, value: true, pts: 15}],
           text: "该股导入成交中{v:has}同日买卖（做T）记录"}
        - {id: IT5, input: profile.experience,
           bands: [{op: eq, value: advanced, pts: 10}, {op: eq, value: intermediate, pts: 5}],
           text: "画像经验：{v}"}
    short:
      requires:
        - {id: SH0, input: profile.risk_tolerance, op: ge, value: 3, else_cap: 59,
           reason: "短线波动大，画像风险承受 < 3 或未填写"}
        - {id: SH0B, input: profile.effort, op: in, value: [medium, high], else_cap: 59,
           reason: "短线需要每日跟踪，画像精力为低或未填写"}
        - {id: SH0C, input: profile.experience, op: in, value: [intermediate, advanced], else_cap: 59,
           reason: "短线需要盯盘与止损纪律，画像经验为新手或未填写"}   # 问题 37 方案 A，已定（2026-11-01）
      components:
        - {id: SH1, input: f.amount_20d_avg, unit: CNY,
           bands: [{op: ge, value: 300000000, pts: 20}, {op: ge, value: 100000000, pts: 10}],
           text: "近 20 日日均成交额 {v:yi} 亿元"}
        - {id: SH2, input: f.turnover_20d_avg, transform: rank_pct,
           bands: [{op: ge, value: 0.6, pts: 15}, {op: ge, value: 0.4, pts: 8}],
           text: "近 20 日平均换手率位于全市场 {v:pct} 分位"}
        - {id: SH3, input: f.limit_up_count_20d, unit: count,
           bands: [{op: ge, value: 2, pts: 15}, {op: ge, value: 1, pts: 10}],
           text: "近 20 日涨停 {v} 次"}
        - {id: SH4, input: f.volatility_20d, transform: rank_pct,
           bands: [{op: between, value: [0.4, 0.9], pts: 10}],
           text: "近 20 日波动率位于全市场 {v:pct} 分位（0.4–0.9 加分，过低或过高不加）"}
        - {id: SH5, input: f.ma_trend, unit: sign,
           bands: [{op: gt, value: 0, pts: 10}],
           text: "均线趋势值 {v}（> 0 为多头排列）"}
        - {id: SH6, input: profile.horizon_pref,
           bands: [{op: contains, value: short, pts: 15}],
           text: "画像周期偏好：{v}"}
        - {id: SH7, input: profile.effort,
           bands: [{op: eq, value: high, pts: 10}, {op: eq, value: medium, pts: 5}],
           text: "画像精力：{v}"}
        - {id: SH8, input: user.avg_holding_days, unit: trading_days,
           bands: [{op: le, value: 5, pts: 5}],
           text: "该股历史平均持有 {v} 个交易日"}
    swing:
      requires: []
      components:
        - {id: SW1, input: f.amount_20d_avg, unit: CNY,
           bands: [{op: ge, value: 100000000, pts: 15}, {op: ge, value: 50000000, pts: 8}],
           text: "近 20 日日均成交额 {v:yi} 亿元"}
        - {id: SW2, input: f.ma_trend, unit: sign,
           bands: [{op: gt, value: 0, pts: 20}],
           text: "均线趋势值 {v}（> 0 为多头排列）"}
        - {id: SW3, input: f.momentum_60d, unit: sign,
           bands: [{op: gt, value: 0, pts: 15}],
           text: "近 60 日动量 {v}（> 0 为上涨）"}
        - {id: SW4, input: f.volatility_20d, transform: rank_pct,
           bands: [{op: le, value: 0.8, pts: 10}],
           text: "近 20 日波动率位于全市场 {v:pct} 分位（≤ 0.8 加分）"}
        - {id: SW5, input: f.roe_ttm, unit: pct,
           bands: [{op: gt, value: 0, pts: 10}],
           text: "ROE(TTM) {v}%"}
        - {id: SW6, input: profile.horizon_pref,
           bands: [{op: contains, value: swing, pts: 20}],
           text: "画像周期偏好：{v}"}
        - {id: SW7, input: user.avg_holding_days, unit: trading_days,
           bands: [{op: between, value: [5, 60], pts: 10}],
           text: "该股历史平均持有 {v} 个交易日"}
    long:
      requires:
        - {id: LG0, input: f.fin_report_count, op: ge, value: 12, else_cap: 59,
           reason: "已披露财报不足 12 期（或缺失）：基本面历史不完整"}
        - {id: LG0B, input: f.roe_ttm, op: not_null, else_cap: 59,
           reason: "ROE(TTM) 缺失：无法判断质量"}
      components:
        - {id: LG1, input: f.fin_report_count, unit: count,
           bands: [{op: ge, value: 12, pts: 15}],
           text: "已披露财报 {v} 期"}
        - {id: LG2, input: f.roe_ttm, unit: pct,
           bands: [{op: ge, value: 10, pts: 20}, {op: ge, value: 5, pts: 10}],
           text: "ROE(TTM) {v}%"}
        - {id: LG3, input: f.profit_cagr_3y, unit: pct,
           bands: [{op: gt, value: 0, pts: 15}],
           text: "近 3 年净利润复合增速 {v}%"}
        - {id: LG4, input: f.dividend_continuous_years, unit: years,
           bands: [{op: ge, value: 3, pts: 15}, {op: ge, value: 1, pts: 8}],
           text: "连续分红 {v} 年"}
        - {id: LG5, input: f.volatility_20d, transform: rank_pct,
           bands: [{op: le, value: 0.6, pts: 10}, {op: le, value: 0.8, pts: 5}],
           text: "近 20 日波动率位于全市场 {v:pct} 分位"}
        - {id: LG6, input: profile.horizon_pref,
           bands: [{op: contains, value: long, pts: 20}],
           text: "画像周期偏好：{v}"}
        - {id: LG7, input: user.avg_holding_days, unit: trading_days,
           bands: [{op: ge, value: 60, pts: 5}],
           text: "该股历史平均持有 {v} 个交易日"}
```

**边界与比较语义。**
- `ge`、`le` 含等号，`gt`、`lt` 不含。`between: [a, b]` 两端都含。
- `contains` 用于数组（`horizon_pref` 含该值）。`in` 用于标量（标量在列表中）。
- 分档从高到低排列，取第一个命中的分档，所以 `ge 0.7` 与 `ge 0.5` 不会重复计分。
- 全部数值都写成整数或普通小数，不用 `5.0e8` 这类科学计数法：PyYAML（YAML 1.1）会把 `5.0e8` 解析成字符串，我们已实测踩坑。
- `rank_pct` 在 T−1 截面上计算。该股不在截面内（停牌、上市不足 20 日）时，它的 `rank_pct` 为 null，计入数据缺失。

## 5. 需要新增或统一的特征键（给架构师）

plan §6.1 的 `features:` 列表用的是不带前缀的键（如 `turnover_20d_avg`、`user.avg_holding_days`），而契约 DSL 要求特征带 `f.` 前缀。建议把列表统一成下面的样子。“启动时必须都在 feature_catalog 中”的约束不变：

```yaml
features:
  - f.amount_20d_avg            # 新增：成交额 20 日均值（元）
  - f.turnover_20d_avg
  - f.amihud_20d                # v1 规则未用，保留
  - f.volatility_20d
  - f.intraday_amplitude_20d
  - f.ma_trend
  - f.momentum_60d
  - f.roe_ttm
  - f.profit_cagr_3y
  - f.dividend_continuous_years
  - f.limit_up_count_20d
  - f.fin_report_count          # 新增：已披露财报期数
  - f.list_days                 # 已用于 G-01
  - f.is_st                     # 新增或与 G-01 共用：风险警示状态
  - f.is_delisting_period       # 新增：退市整理期
  - sec.type                    # 新增：证券类型（主数据，不是时间序列特征）
  - sec.board                   # 新增：板块
  - user.has_position           # 新增：当前是否有持仓
  - user.avg_holding_days
  - user.has_t_trades
  - profile.horizon_pref
  - profile.effort
  - profile.risk_tolerance      # 新增（契约 /me/profile 已有）
  - profile.experience          # 新增（契约 /me/profile 已有）
```

plan §2.5.3 还提到 ATR% 和“交易频率”。v1 规则未使用：ATR% 与 `volatility_20d` 信息重叠；交易频率与 `avg_holding_days` 重叠。所以不必新增。

## 6. 边界情况

| 情况 | 处理 |
|---|---|
| 北交所 | HG2：四个周期都 0 分，理由“首版不含北交所” |
| ETF、可转债 | HG1：都 0 分；不在分类器范围内 |
| 退市整理期 | HG3：都 0 分 |
| ST/*ST（含 2026-07-06 起主板 10% 涨跌幅的新规，见 market_rules_check.md） | HG4：都封顶 59，不列为适合；分数照常给出，供参考 |
| 摘帽 | 下一次重算时 `f.is_st=false`，正常打分 |
| 上市 < 20 日 | HG5：都封顶 59 |
| 上市 20–59 日 | HG6：swing / long 封顶 59；short / intraday_t 正常打分 |
| 长期停牌 | 不单设闸门。20 日窗口的特征在有效 K 线不足时为 null，`rank_pct` 也为 null，触发数据缺失封顶 |
| 银行等没有毛利率之类口径的行业 | v1 只用 ROE、增速、分红，不受影响 |
| 亏损股 | ROE ≤ 0：swing 的 SW5、long 的 LG2 得 0 分；增速基期 ≤ 0 时为 null，计入缺失 |
| 无导入成交 | `user.*` 为“无记录”，0 分，不算缺失 |
| 画像未填 | profile 组件 0 分；intraday_t / short 的 requires 不满足，封顶 59；swing / long 不受影响 |
| 持仓已清 | intraday_t 的 IT0 不满足，得 0 分（下次重算生效） |
| 除权除息 | 涉及价格的特征按前复权计算（与 feature_catalog 一致）；分类器本身不碰价格 |

## 7. 示例用例（全部为示例数值，标的代码只是占位，不对应真实公司情况）

以下各行都假设为 600000.SH 在不同的虚构情形下。`rank_pct` 直接给出分位值。结果用第 4 节规则逐条计算（我们用一个小脚本核对过）。

| 用例 | 关键输入（示例） | intraday_t | short | swing | long | suitable |
|---|---|---|---|---|---|---|
| A 大盘稳健 + 长线画像 | 振幅分位 0.2、成交额 8 亿、换手分位 0.2、波动分位 0.25、ma_trend>0、mom>0、ROE 11%、增速 6%、连续分红 8 年、财报 40 期；有底仓、无做T、均持 90 日；偏好 [long, swing]、精力 low、风险 2、经验 intermediate | 30（raw 30；IT0B 封顶 59） | 30 | 90 | 100 | [long, swing] |
| B 高振幅活跃 + 底仓 + 做T记录 | 振幅分位 0.85、成交额 12 亿、换手分位 0.8、涨停 2 次、波动分位 0.75、ma_trend>0、mom>0、ROE 3%、增速 −5%、分红 0 年、财报 30 期；有底仓、有做T、均持 4 日；偏好 [short, intraday_t]、精力 high、风险 4、经验 advanced | 100 | 100 | 70 | 20 | [short, intraday_t, swing] |
| C 同 B，但为 ST | 同 B，`f.is_st=true` | 59 | 59 | 59 | 20 | [] |
| D 北交所 | `sec.board=bse` | 0 | 0 | 0 | 0 | [] |
| E 次新（上市 40 日） | 振幅分位 0.7、成交额 4 亿、换手分位 0.9、涨停 1 次、波动分位 0.85、ma_trend>0、mom 缺失、ROE 8%、增速缺失、财报 6 期；无持仓、无成交记录；偏好 [swing, short]、精力 medium、风险 3、经验 novice | 0（无底仓） | 59（novice 封顶，raw 85） | 59（HG6，raw 65） | 10 | [] |
| F 无持仓 + 画像未填 + 财务缺失 | 振幅分位 0.5、成交额 1.5 亿、换手分位 0.5、波动分位 0.5、ma_trend<0、mom<0；ROE、增速、分红、财报期数都缺失；无持仓 | 0 | 28 | 25 | 10（缺失 65 分，封顶） | [] |

> 用例 E 说明：按已定规则（用户 2026-11-01 拍板方案 A，见第 9 节），novice 用户的 short 封顶 59（raw 85→59），因此不列为“适合”；用户可经 `fit_ack` 自行选择。intraday_t 对 novice 同样封顶 59（编排者默认，用户可否决），本例因无底仓本就为 0。

用例 B 的理由示例（示例文本；evidence_ids 为示例）：

```yaml
- {text: "【intraday_t】适合理由：近 20 日日内振幅位于全市场 0.85 分位", expr: "rank_pct(f.intraday_amplitude_20d) >= 0.7", evidence_ids: ["ev-示例-01"]}
- {text: "【intraday_t】适合理由：近 20 日日均成交额 12.0 亿元", expr: "f.amount_20d_avg >= 500000000", evidence_ids: ["ev-示例-02"]}
- {text: "【intraday_t】适合理由：画像精力：high", expr: "profile.effort == 'high'", evidence_ids: ["ev-示例-profile"]}
- {text: "【long】不适合理由：ROE(TTM) 3.0%（< 5% 不加分）", expr: "f.roe_ttm < 5", evidence_ids: ["ev-示例-03"]}
```

## 8. 契约与 plan 缺口（需架构师 / 编排者处理）

1. **`/horizon-assessments` 的 reasons 缺 `horizon` 和 `polarity`。** 契约是 `[TextWithEvidence]`，DB 是 `{horizon, text, evidence_ids, polarity}`。建议契约把元素改为 `TextWithEvidence & {horizon, polarity: "for"|"against"}`。
2. **`scores: {horizon: int}` 没有“无法评估”的表示。** 本规则用 0 分加理由来表达。若要区分“0 分”与“未评估”，契约需要允许 null。
3. **画像字段冲突。** plan 第 1170 行 `user_profiles` 是 `horizon(short/medium/long)`、`weekly_hours`；契约 `/me/profile` 是 `horizon_pref: horizon[]`、`effort`、`risk_tolerance`、`experience`。本规则按契约来，plan 需同步。
4. **plan §6.1 的 `features:` 键名没有前缀，并且缺第 5 节的新增键。**
5. **`rules` 的结构需要确认。** 本文用结构化的 gates/requires/components/bands；导入器也可以改用 DSL 表达式，但语义须与第 3 节一致。
6. **是否按 `profile.experience` 限制 short / intraday_t**（见用例 E；plan 问题 37；详见第 9 节）。**short：【已定 A】（用户拍板，2026-11-01，见 T-A03 §2）**：novice 或未填经验 → short 封顶 59，可 `fit_ack` 覆盖，落地为 `horizon_classifier.yaml` 规则 SH0C（`version_no: 2`，`classifier_version: "1.1.0"`）。**intraday_t：编排者默认，用户可否决**：同样封顶，口径与 short 一致（novice 或未填 → 封顶 59，可 `fit_ack` 覆盖）。另外，intraday_t 在 §9 C(6) 下目前只做盘后统计：分类器列为“适合”只表示周期匹配，T-01 实例运行时仍只出盘后统计。前端文案需说明这一点。

## 9. 问题 37：novice 是否限制 short（T006b 问题 4；short **【已定 A】**，intraday_t **编排者默认，用户可否决**）

> 本节原为专业建议和备选方案。2026-11-01 用户已就 short 选定方案 A（T-A03 §2）；intraday_t 由编排者默认同样封顶，用户可否决。9.1–9.3 保留为决策依据。改动只涉及 `horizon_classifier.yaml` 新版本（plan 问题 37 原文），不影响契约。

### 9.1 现状

- short 现有两条前提：SH0（风险承受 ≥ 3）和 SH0B（精力 medium/high），不满足就封顶 59。经验（`profile.experience`）在 short 里**不参与**。
- intraday_t 里经验只作为加分项（IT5），也不封顶。
- 结果：一个 novice 用户，只要风险填 3、精力填 medium，次新股、高换手股的 short 就可能 ≥ 60，被列为"适合"（用例 E，short 85，示例）。
- 用户选不在 suitable 里的周期时，已有 `fit_ack` 覆盖机制（第 3 节第 9 步）。所以"封顶"不等于"禁止"，用户确认后仍可使用。

### 9.2 方案

| 方案 | 做法（yaml 改动示意） | 优点 | 缺点 |
|---|---|---|---|
| **A. 硬封顶** | short.requires 增加 `{id: SH0C, input: profile.experience, op: in, value: [intermediate, advanced], else_cap: 59, reason: "短线需要盯盘与止损纪律，画像经验为新手或未填写"}` | 规则最简单，与 SH0/SH0B 同一机制；默认不推荐，用户仍可 `fit_ack` 覆盖 | 经验是自填的，填 intermediate 就能绕过；画像未填的用户也会被封顶（与 SH0 现行做法一致） |
| **B. 只提示** | 分数不变；novice 且 short ∈ suitable 时，在 short 的理由里加一条不适合理由（如"画像经验为新手，短线波动大"），前端显示新手提示 | 不改变分数与 suitable，最少打扰 | 提示容易被忽略；"适合"标签本身就是推荐信号，与提示互相矛盾 |
| **C. 封顶 + 显式确认后解除** | 同 A，但用户在画像中勾选"我了解短线风险"（新增画像字段）后不再封顶 | 比 `fit_ack` 粒度更粗：一次确认，所有标的生效 | 要新增画像字段，属于契约改动；与现有 `fit_ack` 有重叠 |
| **D. 组合条件封顶** | 只有 novice **且**（风险 < 4 或精力 ≠ high）时才封顶 | 对自报高风险、高精力的新手放行 | 规则更难解释；仍依赖自填 |

### 9.3 研究员建议

**倾向方案 A。** 理由：

1. **与交易所的适当性管理思路一致。**
   - 交易所对风险更高的品种，要求普通投资者先签风险揭示书、会员不得接受未签者的买入委托。例如深交所 2026 交易规则第 4.5.2 条（风险警示股票），见 market_rules_check.md O6。
   - 这是"默认设门槛、确认后放行"的思路，A 加上现有 `fit_ack` 与之同构。
   - **这里只是类比，交易所并没有对"短线"本身设适当性要求。**
2. **short 对执行能力的要求高。**
   - plan 对 short 的定义是"短线 1–5 天"（plan §2 周期枚举）。这类持有需要每日跟踪、按计划止损。
   - 新手最常见的问题是不止损、追涨。默认不把 short 列为"适合"，可以减少新手被"适合"标签误导。
   - 这一点是定性判断，**没有本产品的数据支撑**（不编造回测或统计）。
3. **成本低、可逆。**
   - 只加一条 requires，复用现有 `else_cap` 和 `fit_ack` 机制，不改契约。
   - 以后如果放宽，只需发 classifier 新版本。
4. **与 plan 已定的问题 11 一致**：高风险短线情绪类策略默认不启用，用户逐项确认后才能手动启用。A 把同样的"默认保守、确认放行"用到周期层面。
5. **B 的问题是标签矛盾**：同时显示"适合"和"新手慎用"，用户难以理解。

如果用户更看重"少打扰"，B 是合理的次选。C、D 的复杂度目前没有必要。

**intraday_t 是否同样处理**：研究员原建议先不加（intraday_t 已要求有底仓，§9 C(6) 下目前只出盘后统计）。**编排者已定默认：intraday_t 对 novice 也封顶，口径与 short 一致**（示意：intraday_t.requires 增加 `{id: IT0C, input: profile.experience, op: in, value: [intermediate, advanced], else_cap: 59, reason: "做T 需要盘中决断与纪律，画像经验为新手或未填写"}`，与架构师 fce21bb 一致）。用户可否决。

### 9.4 选 A 时的影响（示例）

- 用例 E（novice）：short 由 85 → 59（示例），suitable 由 [short] → []。用户可通过 `fit_ack` 自行选择 short。
- 用例 B（advanced）不受影响。
- 需要同步：`classifier_version` 升版；用例表增加一行 novice 对照；理由文案见上表。

**状态：short【已定 A】（用户拍板，2026-11-01，T-A03 §2）；intraday_t【编排者默认，用户可否决】（同样封顶，口径与 short 一致）。** 架构师已在 plan 问题 37 与 §6.1 落地 SH0C（`version_no: 2`，`classifier_version: "1.1.0"`）；架构师已在 fce21bb 落地 IT0C。第 4 节 rules 块已同步补入 SH0C、IT0C（T006d，结构不变，均为对应周期 requires 的 else_cap 59）。
