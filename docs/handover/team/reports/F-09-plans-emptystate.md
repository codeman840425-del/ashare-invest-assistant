# F-09 /plans 与 /plan-drafts 两页空态与骨架核对

基线 `origin/main=465e020`，分支 `ds/F-09`。对照契约 §7.7 / §7.7B。**本单只核对，不改设计。**

## 一、结论（先说结果）

**两页的空态与骨架没有问题**，且质量高于预期——契约字段、默认筛选、空态文案、错误态分离都已到位。本单没有发现需要修的差异，**唯一建议是补两条长期守门测试**（已随本单交付）。

## 二、逐项核对

### 类型层：与契约逐字段一致
| 类型 | 契约来源 | 前端 | 结论 |
|---|---|---|---|
| `PlanSummary` | §7.7B line 1084（14 字段） | `api/planAlertTypes.ts:9` | ✅ 字段名、可空性逐条吻合（含 `triggered_at` 回 active 后为 null 的语义注释） |
| `Plan` = PlanSummary + | §7.7B line 1085 | `planAlertTypes.ts:74` | ✅ 含 `current_version`/`version_count`/`pending_triggers`/`evidence` |
| `PlanDraft` | §7.7 line 1031（22 字段） | `api/planTypes.ts:6` | ✅ 含 `qty_range{min,max,lot}`、`stops` 嵌套、`created_at`（v0.2.7 补） |

### 默认筛选口径
- 契约：`GET /plans` **默认 `active,triggered`**，`all` = 不过滤。
- 实现：`mocks/planAlertHandlers.ts:261` 的 `parseStatuses(..., ['active','triggered'])` 与页面「全部状态」勾选框 `plan-filter-all` 一致。✅
- `GET /plan-drafts`：契约默认全部；mock `planHandlers.ts:112` 无 status 时不过滤。✅

### 空态
| 页面 | 空态文案 | testid | 与错误态分离 |
|---|---|---|---|
| `/plans` | 「没有符合条件的计划」 | `plans-table` | ✅ `isError` → `ErrorBox`，空态不报错 |
| `/plan-drafts` | 「没有符合条件的计划草案」 | `drafts-table` | ✅ 同上 |

### 骨架（筛选与操作）
- `/plans`：全部状态开关、状态、来源、证券代码筛选、手工新建按钮，空数据时**仍全部可用**。✅
- `/plan-drafts`：状态、证券代码、候选信号标签。✅

## 三、唯一建议（非缺陷）

现有测试覆盖里 `pages/*.test.tsx` 中与 plans 相关的只有 `planned-riskflag.test.tsx`，**两页的空态/错误态没有守门测试**。本单新增 `pages/plans/t-f09.test.tsx`（7 例）补上：零数据不报错、筛选骨架仍在、500 走错误框、与空态可区分。

## 四、验证
- `t-f09` **7/7**；未跑全量/coverage、未构建
- 未改任何页面/mock/类型代码，**只新增测试文件**
- 扫描与 diff --check 随提交执行

## 五、移交项
- 详情页（`PlanDetailPage`/`PlanDraftDetailPage`）的空态与骨架不在本单范围。
- DeepSeek：未用，原因：核对依赖逐条读契约与实现，不外包。
