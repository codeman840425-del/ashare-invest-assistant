# T-F34b 错误口径补全（在 origin/main=465e020 基线上重建）

## 范围与基线
- 分支 `ds/T-F34b`，从 `origin/main=465e020` 切出，worktree 在 `.worktrees/ds-T-F34b`（遵守 worktree 铁规）。
- 承接 11-10 交接清单 §4 的 T-F34b 重建项；原 WIP 已随旧 worktree 清理丢失，本单按清单文字重写，并**适配 main 现状**（main 与旧 tb-T-F34=47ede97 是两条独立线：main 的 `StockPage` 已是纯资源 404，无 route-pending 分支；main 的 `t-f34.test.tsx` 是日报/时区单，与本单无关）。

## 改动（只动 src/frontend/）
- `api/errorPolicy.ts`：新增 `STOCK_SUB_PATHS_PENDING`（5 条个股子资源**显式清单**，不用通配正则，后端实现后必须删行）、`isStockSubPending()`；新增契约 §7.3 `isSuperseded()`；新增 `isBootstrapRequired()` + `BOOTSTRAP_REQUIRED_ISSUE`（T-B94 裁定：首导未完成 = 500 + `details.issue=security_master_bootstrap_required`）。
- `components/common.tsx`：`ErrorBox` 判定顺序改为 **superseded（真实资源 404，优先，不被吞）→ 开发中（ROUTE_PENDING 或子资源清单）→ 首导未完成专属文案 → 通用错误**。
- `pages/stock/StockPage.tsx`：详情 404 带 `superseded_by` 时提示「已停用，请改用新代码」。
- `pages/t-f34b.test.tsx`（新）：11 例，覆盖四项判定 + 页面级展示 + 回归保护。

## 用例前提修正（交接清单点名的 2 条）
原两条财务页签用例断言「页签内出现 route-pending」，但接口 404 时页签本身不可渲染，前提错误。本单改为**页面级断言**（页面出现 `route-pending` 空态、且不出现「加载失败」），与实现一致。

## 验证
- `vitest run src/pages/t-f34b.test.tsx` = 11/11 通过。
- 回归：`t-f33.test.tsx` + `t-f03.test.tsx` = 32/32 通过。
- `git diff --check` = 0；`secret_scan`（4 文件）= 0 阻断 0 告警；未跑全量/coverage、未构建、未 typecheck（未授权）。
- 未推送、未开 PR（PR 由 Grok 团队审阅合入，合入权不在本团队）。

## 移交项
- 后端实现 bars/financials/fund-flows/factors/announcements 任一子资源后，**必须**从 `STOCK_SUB_PATHS_PENDING` 删掉对应行，否则真实 404 会被显示成「功能开发中」。
- 首导（master_bootstrap）完成后 500 分支自然不再出现；前端文案保留作为部署态兜底。
- DeepSeek：未用，原因：本单判定依赖逐条核对契约与后端路由，不外包。
