# F-01 策略页面前端入口核对（差口清单）

基线：origin/main=465e020，分支 ds/T-F34b worktree（只读核对，不改代码）。
性质：**差口核对单**，不做任何实现改动；接线待编排者派单后开工。

## 一、现状矩阵

| 页面 | 后端路由（main） | 前端路由 | 前端 API 封装 | MSW mock | 导航入口 | 结论 |
|---|---|---|---|---|---|---|
| `/strategies` 策略库 | ✅ `strategy_cards.py:189 GET /strategies` | ✅ `routes.tsx:53` 真实页 `StrategiesPage` | ✅ `useStrategyTemplates` | ✅ `strategyHandlers.ts:116` | ✅ `nav.ts:8` | **已接，完整** |
| `/strategy-instances` 我的策略实例 | ✅ `instances.py:112,305,326,92,98` 全套 | ❌ `PLACEHOLDERS` 占位页（routes.tsx:18,66） | ✅ `useStrategyInstances` / `useCreateStrategyInstance` / `useInstanceTransition` | ✅ `strategyHandlers.ts:123,150,178` | ✅ `nav.ts:17` | **差口 A** |
| `/strategies/:id` 策略详情 | ✅ `strategy_cards.py:161` + `/tracking` | ❌ `PLACEHOLDERS` 占位页（routes.tsx:16） | 部分：`/tracking` 有封装（signalQueries.ts:121） | ✅ `strategyHandlers.ts:107` | 无独立导航（从列表点入） | **差口 B**（需新页面） |
| `/strategy-cards` 策略知识卡 | ✅ `strategy_cards.py:40,91,120,92 GET /strategy-cards[/{id}][/versions]` | ❌ `PLACEHOLDERS` 占位页（routes.tsx:17,66） | ❌ **完全没有** | ❌ **完全没有** | ✅ `nav.ts:18` | **差口 C**（最大） |

补充：`/feature-catalog`（strategy_cards.py:138）前端也**无任何调用**。

## 二、三个差口

### 差口 A：`/strategy-instances` 占位页 → 可立刻接（成本最低）
- 后端 5 个端点全实现；前端 **API 封装、类型（`StrategyInstance`/`StrategyInstanceCreate`/`StrategyInstanceCreated`）、mock 三层都已就绪**。
- 缺的只是页面组件本身：`routes.tsx` 把 `strategy-instances` 从 `PLACEHOLDERS` 移出、换成真实路由。
- 数据已经在 `StrategiesPage` 里被消费（`useStrategyInstances` 与模板同页展示）——需要先**裁定产品形态**：策略实例是继续挂在 `/strategies` 页内展示，还是独立成页？若是后者，两者会重复展示同一数据。
- 接线路由：`{ path: 'strategy-instances', lazy: ... }`，组件读 `useStrategyInstances()` + 复用 `StrategyEnableSwitch`（已有，`components/StrategyEnableSwitch.tsx`）。

### 差口 B：`/strategies/:id` 策略详情（需新页面）
- 后端 `GET /strategies/{strategy_id}/versions/{version_id}` 与 `/tracking` 均在。
- 前端只有 tracking 的 query（signalQueries.ts:121），没有 `/strategies/{id}` 详情查询、没有详情类型。
- **需补**：`useStrategyDetail(id, versionId)` + 类型 + mock handler + 页面组件。属于完整新页面，不是接线。

### 差口 C：`/strategy-cards` 策略知识卡（从零到一）
- 后端 4 个 GET 端点（列表/详情/版本列表/指定版本）+ `/feature-catalog` 都在。
- 前端 **零**：无 query、无类型、无 mock、无页面。导航里有入口（`nav.ts:18`），点进去是占位页。
- 需先确认契约：`docs/api-contract.md` 里 `/strategy-cards` 的响应字段结构，再补四层（类型→query→mock→页面）。

## 三、建议接线顺序（供派单参考）

1. **差口 A**（最高性价比，只缺页面组件，依赖全就绪）——但需先裁定「策略实例独立成页 vs 留在策略库页」。
2. **差口 C** 列表页（后端齐全，需补四层，工作量中等）。
3. **差口 B** 详情页（依赖 C 的列表入口，最后做）。
4. `/feature-catalog` 建议跟随 C 一起（作为策略卡的字段说明数据源）。

## 四、风险与提醒

- 差口 C/B 均需**先读契约确认响应结构**，当前 `strategyTypes.ts` 只有 `StrategyTemplate`/`StrategyInstance`，没有 card 类型——不要照后端模型臆造前端类型。
- `/strategies` 页已同时展示模板与实例，做差口 A 时务必避免同一数据在 `nav` 的两个入口重复呈现。
- 本单**未改任何代码、未跑测试**（纯核对）；扫描不适用（无新增文件入库）。

DeepSeek：未用，原因：核对依赖逐条读后端路由与前端代码，不外包。
