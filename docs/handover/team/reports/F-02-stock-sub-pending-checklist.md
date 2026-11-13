# F-02 STOCK_SUB_PATHS_PENDING 上线预备：前端回改 checklist

基线：origin/main=465e020（`src/frontend/` 只读核对，未改代码）。

## 一、结论（一句话）

**前端五层早已就绪，卡的只有后端。** 后端实现任一子资源路由的那天，前端要做的不是"接线"，而是**删一行清单 + 跑一轮定点回归**——这是本 checklist 的全部实质内容。

## 二、五项子资源现状矩阵

| 子资源 | 契约（docs/api-contract.md） | 后端路由 | 前端类型 | 前端 query | 前端页面 | MSW mock | 清单内 |
|---|---|---|---|---|---|---|---|
| `bars` | §7.3 line 890，完整 | ❌ 无 | ✅ `BarsResponse`/`Bar` | ✅ `useBarsOf`/`useBarsWindow` | ✅ `PriceChartPanel` | ✅ handlers.ts:213 | ✅ |
| `financials` | §7.3 line 884，完整 | ❌ 无 | ✅ `FinancialsResponse` | ✅ `useFinancials` | ✅ `FinancialsTab` | ✅ handlers.ts:268 | ✅ |
| `fund-flows` | §7.3 line 885，完整 | ❌ 无 | ✅ `FundFlowsResponse` | ✅ `useFundFlows` | ✅ `FundFlowTab` | ✅ handlers.ts:278 | ✅ |
| `factors` | §7.3 line 886，完整 | ❌ 无 | ✅ `FactorsResponse` | ✅ `useFactors` | ✅ `FactorsTab` | ✅ handlers.ts:288 | ✅ |
| `announcements` | §7.3 line 887，完整 | ❌ 无 | ✅ `AnnouncementsResponse` | ✅ `useAnnouncements` | ✅ `AnnouncementsTab` | ✅ handlers.ts:298 | ✅ |

后端 `src/backend/app/api/v1/securities.py` 当前只有 3 个路由：`GET /search`、`GET ""`（列表）、`GET "/{code}"`（详情）。

**后端排期：查无任何子资源任务记录**（`docs/handover/team/tasks/T-B*.md` 无相关条目）。后端子资源何时实现尚不可知，F-01/B 线也未排。

## 三、后端实现某子资源后的前端回改 checklist

对**每一个**已实现的子资源（以 `financials` 为例）：

1. **删清单行**：`src/frontend/src/api/errorPolicy.ts` 中 `STOCK_SUB_PATHS_PENDING` 删除 `'/securities/{code}/financials'` 这一行。
   ⚠️ **不删的后果**：该子资源真实返回 404（如证券不存在、越权）时会被 `isStockSubPending()` 判成"功能开发中"，把真实错误伪装成未上线 —— 这是本清单最重要的红线。
2. **更新注释**：同文件 `STOCK_SUB_PATHS_PENDING` 上方注释里的"当前未注册：……"列表同步删掉该子资源。
3. **mock 对齐**：`src/frontend/src/mocks/handlers.ts` 对应 handler 从"恒返回 404"改为按契约返回正常数据（后端已实现，mock 不该再扮演未实现）。
4. **补 404 回归用例**：在 `t-f34b.test.tsx` 的"③ 个股子资源显式清单"组里：
   - 从 `isStockSubPending(...)` 的"命中"循环里移除该项；
   - 新增一条"该子资源 404 → 走正常错误框，不显示 route-pending"的断言。
5. **跑定点**：`vitest run src/pages/t-f34b.test.tsx src/pages/t-f33.test.tsx`（+ 对应页签测试），全绿才算回改完成。
6. **密钥扫描 + diff --check + pathspec 提交**（常规流程）。

**五项全部实现后**：`STOCK_SUB_PATHS_PENDING` 变成空数组，`isStockSubPending()` 恒 false，ErrorBox 的"开发中"判定自动退回只剩 `ROUTE_PENDING_PATHS`。此时可直接删除该清单与函数（保留 `isSuperseded`/`isBootstrapRequired`）。

## 四、与 B 线的协调建议

- 后端每实现一项，**在该 PR 描述里点名"请前端同步删 STOCK_SUB_PATHS_PENDING 对应行"**，避免前端漏删导致错误被吞。
- 建议后端一次性实现全部五项（它们同属 §7.3 个股读接口，共用 `data_status`/证书判定框架），前端只跑一轮回改，比分五次做省事。

## 五、本单边界

- **未改任何前端代码**（这是预备 checklist，不是实现）；未跑测试；未新增 Mock。
- 清单文件本身无敏感信息；扫描 0 命中。

DeepSeek：未用，原因：核对依赖逐条读契约与前后端代码，不外包。
