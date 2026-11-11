# F-05 策略详情页（/strategies/:id?version=:vid）

基线 `origin/main=465e020`，分支 `ds/F-05`。F-01 列出的最后一个前端差口，本单完成后 F-01 三个差口全部闭合。

## 关键前置发现（影响实现口径）
**后端没有 `GET /strategies/{id}` 单端点。** 唯一的详情读接口是契约 §7.4 `GET /strategies/{id}/versions/{vid}`（不可变版本配置）。契约里 `strategy_version` 通知的跳转格式也是 `/strategies/{strategy_id}?version={vid}`。因此本页按**版本**展示，缺 `version` 参数时给出「从策略库选择版本」的指引，而不是去拼一个不存在的端点。

## 改动（只动 src/frontend/）
- `api/strategyTypes.ts`：新增 `StrategyVersionDetail`（config 各块 + `lifecycle`/`card_version_id`/`risk_level`/`param_hash`/`parent_version_id`/`internal_check`）、`StrategyRule`、`InternalCheck`、`StrategyParamsSchemaField`——字段照后端 `version_detail` 与 plan §2.5.14 C 节。
- `api/strategyQueries.ts`：新增 `useStrategyVersionDetail`、`useSiteStrategyTracking`（`scope=site`）。既有的 `useStrategyTracking` 固定 `scope=mine` 供信号详情用，未改动。
- `mocks/strategyVersionHandlers.ts`（新）：合成配置（参数/规则/止损/内部检验），未列模板有兜底结构。**注册顺序放在 strategyHandlers 之后**，避免吃掉更具体的 `/versions/:vid/tracking`。
- `pages/strategies/StrategyDetailPage.tsx`（新）：版本元信息、参数定义表、规则表、止损与时间止损、全站跟踪统计。
- `app/routes.tsx`：`strategies/:id` 从占位改为真实路由。
- `pages/strategies/t-f05.test.tsx`（新）：7 例。

## 守则执行
- **内部检验按契约「方案 A」**：只显示是否做过、方法类型、日期，**不含任何数值或通过与否**；测试里专门断言不出现「通过/失败/达标」字样。
- 跟踪统计明确标注「全站汇总，不含任何他人持仓或个股信息」，且 `value=null` 时显示「样本不足」而非 0。
- 前端不重算规则，只展示后端返回的版本配置。

## 验证
- `vitest run src/pages/strategies/t-f05.test.tsx` = **7/7**
- 回归 `t-f22.test.tsx` = **14/14**
- `secret_scan`（7 文件）= 0 阻断 0 告警；`git diff --check` = 0
- 未跑全量/coverage、未构建、未 typecheck（未授权）

## 移交项
- 策略库列表目前没有指向详情页的链接（`StrategiesPage` 未改）；若要入口可另开小单加一行链接到 `/strategies/{id}?version={current_version.id}`。
- 派生版本（`POST /derive`）与生命周期事件未接入。
- DeepSeek：未用，原因：字段逐条对齐后端 `version_detail` 与 plan C 节，不外包。
