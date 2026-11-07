# 系统组件边界：G-01 / G-02 / N-01（T-R15，v1）

> 系统组件由 `engine_policy.system_components` 挂载（plan 2.5.11A），**不是策略卡、不经导入器**，本文无 `strategy-card` 块。只规定研究侧的边界、最小证据、优先级与解除条件；原因码只用契约 §6.1 现有 22 个，不新增字段。结论由规则决定，AI 只做中文解释；六个维度冲突时并列展示、不合并（P4）。

## 共同优先级（同一候选同时命中多个时）
1. 模板 state 由模板规则决定；系统组件只在下列两种情况下改变 state：G-01 低价股（无原因码项）→ `vetoed`；N-01 风险公告命中（买入方向）→ `vetoed`。
2. 其余命中只产出不可执行原因（`reason_codes` 全部列出、不去重合并、不互相抵消），每个原因各自按解除条件独立解除；全部解除后才可执行。展示顺序：SUSPENDED → ST_OR_DELISTING → NEW_LISTING → LIMIT_LOCKED → KEY_DATA_MISSING → 其他（只排序，不影响判定）。
3. 卖出/减仓方向：G-01 的 veto 不阻断卖出，但停牌 `SUSPENDED` 与一字跌停 `LIMIT_LOCKED`（`detail.direction=sell`，T-R15 ⑤⑩）照常记为不可执行原因；N-01 不阻断卖出；N-01 对持仓只加反证（counter），不触发卖出；H-01 结论不受影响。

## G-01 可交易性闸门 `gate_tradability`（dimension=technical；只阻断买入方向）
| 检查项 | 最小证据（特征/数据） | 结果 | 解除条件 |
|---|---|---|---|
| 停牌（含伪停牌 `suspect`） | `f.is_suspended = true`（来源 `sf`，plan 2.5.14 T-R15 ④）；与快照冲突按数据缺失 | `SUSPENDED`（买卖两个方向都适用，`direction` 取 buy/sell；卖出方向 state 仍按规则为 exit_signal/weakening，只是不可执行，T-R15 ⑩） | 复牌后首根有效日 K 入库（event） |
| ST/*ST/退市整理 | `f.is_st`、`f.is_delisting_period`（缺失时 is_st 按 true，保守） | `ST_OR_DELISTING` | 交易所列表撤销风险警示（event） |
| 上市不满 30 个交易日 | `f.list_days < 30`（缺失按不满足） | `NEW_LISTING` | `f.list_days ≥ 30`（expr） |
| 一字涨停 | `f.limit_locked_up = true`；涨停价按 `market_rules.yaml` 生效段，**无涨跌幅日 limit 价为 null，此项不命中**（不按 20% 推算） | `LIMIT_LOCKED` | 盘中价 < `f.limit_up_price`（expr，tick） |
| 低价股 | `f.close_qfq < 2` 元（qfq@as_of，T 日即不复权价） | veto → state=`vetoed` | 次日重评 |
- 证据缺失时：对应检查项按“数据缺失”处理 → `KEY_DATA_MISSING`（附缺失键），不判为通过。
- 板块：科创板/创业板涨跌幅、风险警示、新股无涨跌幅、科创板 200 股起买/零股规则全部读 `market_rules.yaml`，G-01 不硬编码数值；北交所不扫描。

## G-02 大盘环境 `ctx_market_regime`（dimension=sector_market；只产出上下文）
- **最小环境输入**：沪深300 不复权收盘 ≥ 60 根有效日 K（MA20、MA60）＋ `f.market_breadth`（上涨家数占比）近 20 日 ≥ 15 个有效值。
- **判定（日线盘后，as_of 及以前数据）**：`uptrend` = 收盘 > MA60 且 MA20 > MA60 且宽度 20 日均值 > 0.50；`downtrend` = 收盘 < MA60 且 MA20 < MA60 且宽度 20 日均值 < 0.40；其余 `range`。**2 日防抖**：新状态需连续 2 个交易日成立才切换，否则沿用前值。阈值 `epistemic=hypothesis`。
- **缺失**：任一最小输入缺失 → `f.market_regime = null`（不沿用前值、不填 range）；引用它的 veto 按 `veto_unknown`：买入方向草案 `KEY_DATA_MISSING`（missing=["f.market_regime"]），解除 = 新快照非空；RC3 区间为 null 并记 gap。
- 只产出 `f.market_regime`，不挂规则、不产生信号；情绪周期 6 阶段在涨停池积累前不输出。

## N-01 风险公告否决 `veto_risk_announcement`（dimension=news）
- **规则**：`f.ann_risk_count_10d > 0`（近 10 个交易日风险类标题关键词命中条数；关键词表版本化存 `event_definitions`）。买入方向 → veto（state=`vetoed`）；持有中 → counter（反证并列，不触发卖出）。
- **时点**：公告只有日期 → 一律按盘后，次一交易日 09:30 起计入（2.12.2）；`max(公告时间, first_seen_at)`。无未来数据。
- **缺公告否决（优先级高于模板 entry_ok）**：`f.ann_risk_count_10d` 为 null，或公告数据源 `feature_catalog.status ≠ verified_live`，或数据过期 → 模板 state 照常（可为 entry_ok），候选照常展示，但**买入方向计划草案被 `KEY_DATA_MISSING` 阻断**（missing=["f.ann_risk_count_10d"]）。
- **解除条件**（`kind=expr`，machine_checkable）：该字段在新快照中非空 **且** 公告源 `status = verified_live`；两者缺一不解除；不可手动解除。卖出方向不受影响。
- **与其他组件**：与 G-01 原因并列；N-01 命中（veto）优先于 N-01 缺失（KEY_DATA_MISSING）——命中时直接 `vetoed`，不再报缺失。
