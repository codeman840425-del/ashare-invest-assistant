# 前端评审待修（review-8249d6e m1、review-8249d6e/7afbc06 m4）

- 提交：85e9b70（只含 src/frontend/，未 push）
- 干净检出：eslint 0 警告、typecheck 通过、vitest 24 文件 363 用例全绿、build / check:dist / build:mock 反向自检通过；pnpm audit 仍为原有 1 个 moderate
- 扫描：secret_scan / gitleaks（工作区与暂存）0 命中；禁用词与 11 位数字 0 命中

## m1：/meta/registration 缺 Date 头时不传 form_started_at
- `lib/serverClock.ts` 增加“已校正”标志：只有拿到可解析的 `Date` 头才置位；新增 `calibratedServerNowMs()`（未校正返回 null）。
- `RegisterPage` 表单首次渲染时取 `calibratedServerNowMs()`；为 null 时请求体**不带** `form_started_at` 键（契约 v0.2.8 #11：不传则不做最短填写时间检查），`website` 照常提交。
- `RegisterRequest.form_started_at` 改为可选。
- 测试（t-f24.test.tsx）：无 Date 头 / 坏 Date 头不算校正；用 MSW 覆盖去掉 Date 头后提交，请求体无 `form_started_at`、用户照常创建、蜜罐无命中。

## m4：/plans/{id} 404
- 契约 §5 `Notification.target.route` 规定 `plan → /plans/{id}`，/today 计划条件也链接到这里，但计划详情页属于后续任务、契约没有给页面细节，所以按要求**接占位页**“计划详情”（PLACEHOLDERS 加 `plans/:id`），不再落 NotFound。mock 不需要改（占位页不发请求）。
- 测试 `pages/routes-review.test.tsx`：/plans/{id} 显示占位页，真正不存在的路径仍 404。
- 截图：`/workspace/team/reports/review-fixes/01-plan-detail-placeholder.png`（从 /today 的“计划 vN ›”点进来）。

## 未处理（不在本次范围）
- review-8249d6e m2/m3（mock 限速与待审核上限、website 非字符串）与 review-7afbc06 m1/m2/m3/m5 未在本次修改，待排期。
