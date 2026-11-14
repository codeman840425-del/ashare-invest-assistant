# F-03 策略实例独立页（/strategy-instances）

## 背景
F-01 核对发现 `/strategy-instances` 是占位页，但 API 封装、类型、mock 三层早已就绪。编排者 2026-11-11 裁定：**独立成页，不并入策略库页**（避免同一数据双展示）。

## 改动（只动 src/frontend/）
- `pages/strategies/StrategyInstancesPage.tsx`（新）：**实例视角**列表——策略名+版本号、生命周期、周期、作用范围、状态标签、启用开关；展开行给来源/预算/自动降权/暂停方等明细。
- `app/routes.tsx`：从 `PLACEHOLDERS` 移除 `strategy-instances`，改为真实路由（懒加载）。
- `pages/strategies/t-f03.test.tsx`（新）：11 例。

## 关键设计（不重算规则）
- 状态、范围、周期、风险等级**全部照后端返回展示**，前端不做任何推断。
- 开关转发严格按契约 §6.0A：`active`→`pause`；`paused`→`resume`；`proposed`→**`confirm`（不重复创建实例）**；`archived` 禁用开关。
- 与策略库页互补：策略库按「模板」视角看全部模板+启用，本页按「实例」视角管理运行中的实例。两页数据同源但视角不同。

## 验证
- `vitest run src/pages/strategies/t-f03.test.tsx` = **11/11**
- 回归 `t-f22.test.tsx` + `t-f22a.test.tsx` = **41/41**
- `secret_scan`（3 文件）= 0 阻断 0 告警；`git diff --check` = 0
- 未跑全量/coverage、未构建、未 typecheck（未授权）

## 移交项
- 实例详情（`GET /strategy-instances/{id}`）与事件流（`/events`）本页未接入，展开行只用列表字段；需要时另开单。
- 归档操作（`POST /archive`）本页未提供按钮（契约允许，但需产品确认交互位置）。
- DeepSeek：未用，原因：页面与用例需逐条对齐契约 §6.0A，不外包。
