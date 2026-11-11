# T-A160 裁定：DataStatusBlock.data_as_of 可空口径的全站外延（A-12，F-11 带出 4 待裁字段）

日期：2026-11-11（北京时间）｜裁定人：架构师｜输入：PR #70「待架构师裁定」节（F-11，e62d6af）
依据：契约 §7.3 T-A53 第 4 条（四端点「全空 null」先例）、§1.1 混合来源响应、TerminalRow（L616「完全无数据时 null」）、日报 T-A29（L1179「非 null 最早值、全空 null」）、T-A33 R4（L1246 同口径）、/market/overview 自身字段级 null 先例（§7.3 L891）、Evidence 结构（L602）。

## 总裁定：data_as_of 语义统一为「实际使用数据时点中最早的非空值；完全无数据时 null」——全站外延

T-A53 第 4 条为四端点写的口径不是特例，是 `data_as_of` 的**本义**（「数据截至何时」——没有数据就没有「截至」；用生成时刻/当前时刻冒充数据时点正是该字段要防的伪造）。TerminalRow、日报、RiskEvaluation 三处既有裁定同向。因此：**凡 DataStatusBlock 的 `data_as_of` 一律 `string(datetime) | null`**，无数据时 null，不取 `generated_at`/`evaluated_at`/当前时刻替代。这不是放宽必填，是把「必填」的正确值域补全——null 本身就是如实答案。

## 逐字段裁定（PR #70 四项）

### ① SecurityProfile.data_as_of → 可空（null）

- 混合来源对象（公开主数据 + 本人证书数据）。公开主数据侧**恒有** `master_as_of`（三所快照日，T-B94 裁定：任一所从未成功即部署前置违规，不进运行时）——因此 `data_as_of` 下界：公开侧可用时 ≥ `master_as_of`；**证书侧（行业/概念/股本/停牌）从未取得**（ETF 全 null、指数无证书数据、新用户未设证书）且公开侧也判不出有效时点时为 null。
- 实操：`data_as_of` = 公开侧 `master_as_of` 与证书侧各 `fetched_at` 中实际参与本响应字段的最早非空值；ETF/指数的证书字段全 null 时 = `master_as_of`（公开侧仍在响应中，不算「全空」）。**仅当整个响应没有任何带数据时点的字段时才 null**（理论上仅主数据不可用，属部署异常态）。
- 前端：`SecurityProfile` 的 `data_as_of` 改 `string | null`，null 显示「—」。

### ② SectorFlowsResponse（/market/sector-flows）.data_as_of → 可空（null）

- 盘后证书数据端点。从未取得任何板块流量 → `items: []`、`data_status:"unavailable"`、gap `no_source`、`data_as_of: null`（与 T-A53 四端点完全同构，无需新理由）。有数据时 = 所返回各行 `trade_date` 对应入库时点的最早值。
- 该端点另有顶层 `trade_date` 字段（§7.3 L888）：无数据时**同样 null**（T-A158 先例：无批次不造日期）；有数据时 = 数据所属交易日，维持。

### ③ MarketOverview.data_as_of → 可空（null）

- T-A53 第 3 条已明确本端点 null 语义（breadth/regime 等 null + no_source）；其 DataStatusBlock.data_as_of 随总裁定：指数行情**从未取得**（全部 indices 行 price=null 且无任何历史行参与）→ null；有任一可用行情时点 → 最早非空值。
- 注意：本端点顶层 `trade_date` 维持契约现状（`string(date)`，最近交易日——交易日历恒可算，与「有无行情数据」无关，不改为 null）。字段级差异已由契约自身的 null 标注表达。

### ④ Evidence.data_as_of → **不改，维持必填**

- Evidence 是**论断锚点**（建议/信号/日报的事实依据），不是 DataStatusBlock 成员；其 `data_as_of` 表示「该条事实的数据时点」，由生成方在写入时填定。`value=null`（未知指标）时 `data_as_of` 仍必填——**「这个未知结论基于何时的一无所知」本身是可陈述的事实**（写入时点已定），与「整个响应无数据」不同层。
- 快照类（CandidateSignal/SignalEvent/CandidateVersion 等顶层 DataStatusBlock）：按总裁定统一可空——它们生成时快照完整，实际必有值；可空只是允许「快照无任何数据时点」的诚实表达（如全 gap 信号）。前端类型同步放宽不破坏现有数据。

### SSE `quote` 事件的 data_as_of（PR #70 第 3 问）

→ 可空（null）：推送块与 /quotes 同源；全空推送（理论上不推）与批量部分缺失时按「最早非空值，全空 null」。

## 契约同步（本提交执行）

| 位置 | 改动 |
|---|---|
| §5.1 DataStatusBlock 行 | `data_as_of: string(datetime) \| null` + 总语义一句（最早非空值，全空 null；不取生成/评估时刻） |
| §5.1 SecurityProfile 尾行 | 补「data_as_of 参与即最早非空；全空 null」 |
| §7.3 sector-flows 行 | 补 data_as_of/trade_date 空态 null |
| §7.3 market/overview 行 | 补 data_as_of 可空（trade_date 维持必填的区分说明） |
| §7.3 T-A53 第 4 条 | 注明口径已由 T-A160 全站外延 |

## 落地

- 前端（F 线）：全局 `DataStatusBlock.data_as_of` 改 `string | null`（F-11 的切片方案可回退为全局统一，SliceDataStatusBlock 保留或合并均可）；Evidence/SSE 同步。随 F-13 空态巡检一单走。
- 后端：§7.3 各端点空态响应补 `data_as_of: null`（多数已按 T-A53/T-A158 实现，核对即可）；Evidence 不动。
- 测试：null 断言随 F-11/F-13 的用例走。

- DeepSeek：未用，原因：裁定不外包。
