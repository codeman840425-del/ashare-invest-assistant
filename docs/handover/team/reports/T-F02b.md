# T-F02b 报告：评审修复并同步契约 #23–#27（对齐 v0.2.5）

- 提交：`7d1993f` `fix(frontend): T-F02b 评审修复并同步契约 #23–#27（对齐 v0.2.5）`（本地提交，未 push；38 个文件，全部在 src/frontend/）
- **对齐的契约版本：v0.2.5**。提交前 docs/api-contract.md 已是 v0.2.5（架构师 T-A06，bd33f83），所以 `CONTRACT_VERSION = 'v0.2.5'`，`contract.test.ts` 断言为 `toBe('v0.2.5')`。
- 依据：review-T-F02.md、review-T-F01.md（复审部分）、T-A05-decisions.md（#23–#27）、v0.2.4 / v0.2.5 变更表、T-A06.md。
- 检查：typecheck、`eslint --max-warnings=0`、vitest（13 个文件、227 个用例）、build、build:mock 全部通过；check:dist 结果为 dist 0 命中，dist-mock 反向自检命中 20 个；secret_scan（工作区 118 个文件，暂存 38 个文件）阻断 0、警告 0；gitleaks dir（仓库配置 + `--ignore-gitleaks-allow`，以及默认规则）和 gitleaks `--staged` 均为 no leaks found；没有豁免。

## 提交拆分（T-F02b 与 T-F05）
v0.2.5 删除了同意流程、风险测评和 fit_ack，用户已把这些删除另列为 T-F05（单独提交，排在本提交之后）。为让两个提交各自都能编译并通过测试，做法如下：
- 本提交：完成评审修复，`CONTRACT_VERSION` 改为 v0.2.5。同意、测评相关代码暂时保留 v0.2.4 的形态。
- 契约派生的两个测试用显式常量标出暂时的差异，T-F05 提交时去掉：
  - `review-fixes.test.ts` 中的 `T_F05_PENDING = ['CONSENT_REQUIRED', 'STRATEGY_FIT_ACK_REQUIRED']`；
  - `contract.test.ts` 中暂不比对 `hints`。
- 属于 v0.2.5 的其余改动都在 T-F05 中做，包括 `HorizonHint`/`hints`、Me 精简、画像改为选填、免责提示逐字、删除 /onboarding。

## 主要问题（review-T-F02）
| # | 处理 | 位置 / 证据 |
|---|---|---|
| P1 示例题库进入生产包 | 已修复。题库移到 `mocks/compliance.ts`，只由 MSW handler 引用。新增 `scripts/check-dist.mjs`（`pnpm check:dist`）扫描 dist：示例题目、题干、q_id、`demo-sha256`、`DEMO-INVITE-OK`、`mockServiceWorker`、`virtual:msw`、`setupWorker` 都不能出现；业务 chunk 超过 500 kB 也判失败。`--expect-present` 对 dist-mock 做反向自检，证明这个检查有效。测试 `app/prod-bundle.test.ts`：业务代码不得 import mocks/ 或 msw；main.tsx 的动态 import 必须在 production 守卫之后。结果：dist 中 21 个标记 0 命中，dist-mock 中命中 20 个。（T-F05 会把题库整个删除，届时同步更新标记表） | scripts/check-dist.mjs、src/app/prod-bundle.test.ts |
| P2 通知深链 | 已修复。`/portfolio` 读取 `account_id`，兼容旧的 `account`；`/portfolio/import?batch=<id>` 用 `<Navigate replace>` 跳到 `/portfolio/import/:id`；页面内链接统一用 `account_id`。测试：t-f02b「P2 通知深链参数」 | PortfolioPage.tsx、ImportWizardPage.tsx |
| P3 agreements 取值 | 已按 v0.2.4 改为 ConsentKey（terms / privacy / signal_risk_disclosure）。v0.2.5 已删除 agreements 字段（服务端忽略），勾选框由 T-F05 删除 | RegisterPage.tsx、accountLabels.ts |
| P4 持仓合并口径 | 已修复（契约 v0.2.4 #14）。`GET /portfolio?account_id=` 默认按当前账户请求，提供「当前账户 / 合并全部账户」切换（`portfolio-scope`）；mock 支持按 account_id 过滤。测试已覆盖 | queries.ts `usePortfolio(accountId)`、handlers.ts |

## 次要问题（review-T-F02 m1–m12）
| # | 处理 |
|---|---|
| m1 从停用恢复须填理由 | 已修复：`NEEDS_REASON = to !== 'approved' \|\| from === 'disabled'`（AdminUsersPage.tsx:15） |
| m2 同 IP 阈值 | 已修复：直接使用服务端返回的 `same_ip_flag`，去掉 3 的兜底（契约已有该字段） |
| m3 申请说明 | 已修复：加了 `apply_note` TextArea，≤200 字（`APPLY_NOTE_MAX`） |
| m4 reason 进 URL | 已修复：reason 通过 `navigate(..., {state})` 传递，URL 只保留 status |
| m5 兜底显示 e.message | 已修复：改为 `errorText(e)` |
| m6 FRESH_DATA_REQUIRED | 已修复：去掉 query 的特判，文案改为“行情数据暂未更新，请 {retry_after_s} 秒后再试”（有测试） |
| m7 413 与本地预检 | 已修复：选文件时按 5 MB 预检（`upload-too-big`）；413 时有 `details.max_bytes` 就显示上限。测试：t-f02b「超过 5 MB…」 |
| m8 作废原因 | 已修复：`voidReasonText` 显示 `void_reason`，`batch_reverted:*` 显示为“所属导入批次已撤销”。还新增了手工作废（必须填原因）和更正（必须填原因，原记录作废）的界面与 mock（`POST /trades/:id/void`）。测试已覆盖 |
| m9 主包体积 | 已修复：除登录页和 AppShell 外，其余路由都改为懒加载；`manualChunks` 拆出 vendor-react / antd / ag-grid / charts。主入口约 32 kB；超过 500 kB 的只有 vendor-antd（约 1265 kB）和 vendor-ag-grid（约 1208 kB），所以 `chunkSizeWarningLimit` 设为 1300，业务 chunk 的体积由 check-dist 把关 |
| m10 管理端翻页 | 已修复：`useInfiniteQuery` 按游标分页，加“加载更多”（`admin-users-more`） |
| m11 画像小数位 | 已修复：`precision={2}`，提交时 `toFixed(2)` |
| m12 新手封顶文案 | 已按当时口径改为“短线与日内做T封顶…”。**v0.2.5 已改为只提示、不封顶**，T-F05 会改成 hints 文案 |

## 建议（review-T-F02 s1–s6）
- s1 成交幂等：已做。Idempotency-Key 由表单用 useRef 持有，提交成功后才换新；mock 支持重放，测试已覆盖。
- s2 按 `details.required` 决定跳转去向：已做（v0.2.4 形态）。v0.2.5 删除了 CONSENT_REQUIRED，T-F05 会整段删掉。
- s3 同意文书版本取自 `/meta/consent-docs`：已做（v0.2.4 形态），T-F05 会删除。
- s4 拆出 `ImportBatchSummary`：已做。
- s5 补测试：新增 `pages/t-f02b.test.tsx`，8 个用例，覆盖：
  - 深链 ×2；
  - 作废须填原因；
  - 批次撤销文案；
  - 幂等重放与 409；
  - 更正须填原因；
  - 5 MB 预检；
  - 处理选项表。
  注册错误和画像的已有用例保留在 t-f02.test.tsx。
- s6 封顶说明文案：已做。`i18n/horizonCaps.ts` 按 rule_id 显示中文规则说明；快照不一致时标注“周期分类基于较新快照”。

## T-F01 复审余项（review-T-F01 复审）
- m9：同上，已拆包。
- s1：vite.config.ts 里引用的 README 仍不存在。**未处理**，留给以后补 src/frontend/README。
- s2：`strategies[0]` 空数组保护已加。
- s4 / s5：依赖 SSE 任务，未做。

## 契约同步
- #23–#27（T-A05，7c62f59）与 v0.2.4 的 #10–#14 已同步：DimensionCell 改为 prose、resolution_choices 表、成交 void/correct、CSRF（cookie 优先）、portfolio account_id。
- v0.2.5：本提交只改了版本号和上述两处显式例外，其余见 T-F05。

## 需要谁做什么
- **编排 / 用户**：审阅后 push `7d1993f`。
- **T-F05（我，紧接着做）**：删除同意 / 测评 / fit_ack，接入 hints，免责提示改为逐字一致，去掉 `T_F05_PENDING` 例外。
