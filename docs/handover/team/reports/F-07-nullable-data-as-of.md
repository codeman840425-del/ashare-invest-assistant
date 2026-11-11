# F-07 DataStatusBlock.data_as_of 可空类型收口

基线 `origin/main=465e020`，分支 `ds/F-07`（未叠加 #49）。

## 问题
契约 T-A53：空数据场景 `data_as_of` 为 `null`（没取到数据就没有"截至"时间）。前端 `DataStatusBlock.data_as_of` 写死 `DateTime`（string），把合法的 null 拒掉，B-03 的空数据 dry 链因此 13 项 TS2322。

## 改动（只动 src/frontend/）
- `api/types.ts`：`data_as_of: DateTime | null`，并加注释说明消费点不能直接拼字符串。
- `pages/market/MarketPage.tsx`：唯一一处真实的类型断裂——`fmtTime(m.data_as_of)`。改为 `data_as_of ? '更新于 …' : '数据不可用（无数据时点）'`，**不编造时间**。
- `pages/t-f07.test.tsx`（新）：5 例。

## 为什么只有一处消费点要改
`DataStatusTag` / `GapNote` / `dataStatusLines` 的签名本来就是 `string | null`，其余页面早已按可空处理（`DailyReportPage`、`AlertDetailPage` 等都有 `=== null ? '—' : fmtTime(...)`）。真正会编译失败的只有 MarketPage 这一处直接 `fmtTime`。

## 验证（三项，逐条实证）
1. **typecheck**：`tsc --noEmit -p tsconfig.app.json` → **exit 0**（清零前唯一错误就是 MarketPage:29 TS2345）。
2. **B-03 dry 链**（19 场景）：用本分支前端跑 `b03_frontend_dry.cjs`，结果 `known_nullable_timestamp_errors: 0`、`populated_types_passed: 6`、`mock_resources_matched: 5`——**13 项 TS2322 清零，19 场景全过**。报告存 `F:\workspace\team\status\F-07-b03-dry.json`（未入库）。
3. **定点**：`t-f07` 5/5（类型层 null/非 null + JSON 往返 + 页面空态/有值/报错三态）；回归 `t-f03` 14/14（含市场概览）。

密钥扫描 3 文件 0 命中；`git diff --check` 干净。

## 移交项
- 其余 `DateTime` 字段（`Evidence.data_as_of`、`suggestionQueries` 的 `data_as_of: string` 等）**不在本单范围**，契约未要求可空，未改；若后续出现同类诊断再收口。
- DeepSeek：未用，原因：类型收口需逐条核对消费点，不外包。
