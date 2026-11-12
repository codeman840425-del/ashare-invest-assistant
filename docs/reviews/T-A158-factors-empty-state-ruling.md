# T-A158 裁定：/securities/{code}/factors 无数据空态的可空口径

日期：2026-11-11（北京时间）｜裁定人：架构师｜输入：B-05 factors 阻点单（F:\workspace\team\status\B-05-factors-contract-blocker.md，后端 2026-11-11）
依据：契约 §7.3 factors 行（v0.2.7/v0.2.8）、DataStatusBlock 空态先例（bars pending、ETF not_applicable）、FactorCategory 空枚举现状（app/schemas/enums.py:675，待 T003）。

## 裁定（采纳后端推荐，逐字段）

1. **`trade_date: string(date) | null`**：请求带 `?trade_date=` 时**原样返回请求值**（响应反映所请求的视图，不查库改写）；请求未指定（默认最新）而无任何可用因子批次时为 **null**——不造「最新交易日」（无数据时无「最新」可言，编一个日期违反不造数纪律）。有真实批次时照旧返回该批次交易日。
2. **`factor_set_version: string | null`**：无真实因子集批次时为 **null**。合成夹具版本（B-03 `synthetic-factors-85` 一类）只存在于测试 fixture，**不得**进入任何生产响应——包括显式启用的本地/测试源也不得冒充版本号（与 B-05 阻点单口径一致：placeholder 只接空态）。
3. **空态三形（沿用 v0.2.8 既有骨架 + 本裁定补可空）**：
   - ETF：`items: []`、`counts: {total: 0, by_category: {}}`、`trade_date=null`、`factor_set_version=null`、`data_status:"unavailable"`、`gaps:[{key:"factors", reason:"not_applicable"}]`（无请求日期时；带请求日期时 trade_date 原样返回，其余同）。
   - 指数/无数据证券：同上但 gap `reason:"no_source"`。
   - 股票正常但当日批次未产出：`data_status` 按既有语义（pending/unavailable），trade_date/factor_set_version 按 1/2 取值。
4. **`category` 枚举**：保持空枚举现状（`FactorCategory=[]`，待 T003 核实后注册）；**未知筛选值 → 400 VALIDATION_ERROR** 维持全站参数校验口径；B-03 的合成分类标签只供自检 fixture，不进 `/meta/enums`、不进生产数据。
5. **前端同步**：两字段消费改为可空（`string | null`），null 显示「—」类空态文案，不编造日期/版本。

## 理由

- 「空态返回请求值、无据可依返回 null」与 `bars.pending` 的 `adjust_as_of=null`、`/market/overview` 的 `breadth=null` 同一先例：**缺失即 null，不伪造锚点**。
- factor_set_version 是批次溯源键；用合成值会污染后续对账与快照对照（「这批数据是哪个版本算的」必须可答或明示不可答）。

## 同步与落地

| # | 事项 | 角色 |
|---|---|---|
| 1 | 契约 §7.3 factors 行改为 `trade_date: string(date) \| null`、`factor_set_version: string \| null` + 空态三形说明（本提交已改） | 架构师 |
| 2 | 后端 factors placeholder 空态按本裁定实现 + 定点（请求值透传/null/ETF/指数/未知 category 400） | 后端（B-05 续） |
| 3 | 前端 types/mocks 两字段改可空（与 F-07 的 data_as_of 收口同批风格） | 前端 |
| 4 | FactorCategory 空枚举保持，T003 核实后另走注册单 | 研究员/后端 |

- 调序确认：后端可先做 announcements（已授权部分），factors 按本裁定接续——阻点已解除。
- DeepSeek：未用，原因：裁定不外包。
