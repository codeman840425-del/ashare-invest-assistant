# F-10 factors 前端对接 T-A158 空态裁定

基线 `origin/main=465e020`，分支 `ds/F-10`，不叠加 #54/#19。**字段形态以后端 `ds/B-05-factors` 分支 PR 为准。**

## 裁定要点（架构师 T-A158）
`trade_date` 请求合法值原样透传、无批次为 null；`factor_set_version` 无真实版本时 null、**合成版本禁入生产响应**；ETF 用 `not_applicable`，指数/无数据用 `no_source`。

## 改动（src/frontend/）
- `api/marketTypes.ts`：`FactorsResponse` 的 `trade_date: DateStr | null`、`factor_set_version: string | null`，并注明「不得用任何常量兜底」。
- `pages/stock/StockTabs.tsx`：`?? <span className="muted">未知</span>`，null 时如实显示「未知」，**不拼成 "null"、不填常量**。
- `mocks/marketFixtures.ts` / `mocks/handlers.ts`：指数与 ETF 的空态改为两字段 null、不再下发 `mr-factors-85（示例）` 这类合成版本名。
- `pages/stock/t-f10.test.tsx`（新）：4 例。

## 一处已知边界（须如实说明）
main 上 `DataStatusBlock.data_as_of` 仍是非空 `DateTime`——**其可空化属于 F-07（#54），本分支未叠加**。因此 fixtures 里 `data_as_of` 保持合法值，测试不断言其为 null。#54 合入后如有需要可再收口。

## 验证
- `t-f10` **4/4**；回归 `t-f03`+`t-f21` **27/27**
- `tsc --noEmit -p tsconfig.app.json` = **0**（派单授权）
- `secret_scan` 5 文件 0 命中；`git diff --check` 干净
- 未跑全量/coverage、未构建

## 移交项
- **后端 factors PR 合入后**，前端需按实际字段形态再对一次（本单已按后端交接的口径实现）。
- `data_as_of` 可空依赖 F-07（#54）。
- DeepSeek：未用，原因：字段逐条对照裁定与后端交接口径，不外包。
