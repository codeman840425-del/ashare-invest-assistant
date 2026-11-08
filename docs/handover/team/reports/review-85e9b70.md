# 评审报告：前端 85e9b70（评审 8249d6e/7afbc06 修复：form_started_at 与 /plans/{id}）

- 评审人：架构师（代审）　日期：2026-11-02（北京时间）
- 被评审提交：`85e9b70`（2026-11-02 07:38 北京时间）。自述见：`review-fixes-frontend.md`
- 评审依据：
  - HEAD 上的 `docs/api-contract.md`（v0.2.8，含补充裁定 #17）；
  - 本提交自述对齐的契约版本：v0.2.8 #11（注册蜜罐 form_started_at）。
  - 自述中的“契约待定项”不在本次裁定范围内，只做记录。
- 本次只读：没有改代码，没有提交，没有推送；主工作树没有动过。

## 0. 干净检出结果

方法：`git archive 85e9b70 src/frontend docs | tar -x -C /tmp/rv8/85e9b70`，然后在 `src/frontend` 下执行 `pnpm install --frozen-lockfile`。之后依次执行下表各步，与其他提交**串行**进行，不并行跑。环境：Node v24.22.1（CI 用 22）、pnpm 10.34.6。

| 步骤 | 命令 | 结果 |
|---|---|---|
| install | `pnpm install --frozen-lockfile` | rc=0，lockfile 未变 |
| typecheck | `pnpm run typecheck`（app/node/test 三个 tsconfig） | rc=0 |
| lint | `eslint . --max-warnings=0` | rc=0，0 警告 |
| test | `pnpm run test`（vitest run） | rc=0：Test Files 23 passed / 1 skipped（24）；Tests 362 passed / 1 skipped（363） |
| build | `pnpm run build` | rc=0 |
| check:dist | `pnpm run check:dist` | rc=0：dist 共 35 个文件，20 个示例标记 0 命中；业务代码块均 ≤ 500 kB |
| 被忽略的已跟踪文件 | `git ls-tree -r 85e9b70 src/frontend \| git check-ignore --no-index --stdin` | 0 命中 |

说明：被跳过的 1 个测试文件是 `tracked-sources.test.ts`，因为 archive 导出里没有 `.git`，它会按设计跳过。上表最后一行就是替代它做的同类检查。测试数与自述一致。

## 1. 结论：**通过**

没有 B 级或 M 级问题。review-8249d6e 的 m1 已修复，/plans/{id} 的 404 已修复。

## 2. form_started_at（契约 v0.2.8 #11；review-8249d6e m1）

- `serverClock.ts` 增加了 `calibrated` 标志，只有 `noteServerDate` 从响应头 `Date` 解析成功时才会置为 true。另外新增：
  - `calibratedServerNowMs()`：未校正时返回 null；
  - `isServerClockCalibrated()`；
  - `resetServerClock()`，供测试使用。
- `RegisterPage` 只有在 `/meta/registration` 加载成功后才渲染 `RegisterForm`，所以 `useState(() => calibratedServerNowMs())` 取值时，时钟已经有机会完成校正。
  - 如果没有有效的 `Date` 头，取到的值是 null，提交时用条件展开省略这个字段。这符合 #11“不传则服务端不做最短填写时间检查”的规定。
  - 重试时沿用同一个值。
- `RegisterRequest.form_started_at?` 改为可选，与契约一致。
- 原理说明：校正值是“Date − 本地收到时刻”，它是真实时差的下界。因此 form_started_at 只会偏早，不会偏晚，正常用户不会被误判为“填写太快”或“未来时间”。

## 3. /plans/{id}

增加了“计划详情”占位页，不再返回 404。后续 53468a5 确认草案后会跳转到这里，跳转可以落地。

## 证书安全与已作废内容

- **证书安全**：在本提交 `src/frontend` 的新增行中搜索 fingerprint、mask、suffix 字样，以及 ≥32 位的十六进制串，0 命中，没有出现任何证书值或其片段。证书相关的展示只用 `licence_id`、状态和日期。`check:dist` 的示例标记在产物中 0 命中。
- **已作废内容**：在新增行中搜索 consent、risk_assessment、`fit_ack`、`STRATEGY_FIT_ACK`、`/onboarding`、`me/export`、`PROFILE_OR_CONSENT`，0 命中。在 53468a5 的整棵树中有 3 处命中，都是已知且无害的：
  - `prototype/` 下的旧原型，不参与构建，本轮提交没有改动；
  - `strategyTypes.ts` 里一条“v0.2.5 起没有 fit_ack”的说明注释；
  - `strategyHandlers.ts` 里一条“忽略 fit_ack”的说明注释。

  这与 `review-6c50108.md` 的结论一致。
- 新增的 `console.log` 只出现在截图脚本中，业务代码里没有。

## 4. 问题清单

| 级别 | 编号 | 问题 | 归属 |
|---|---|---|---|
| B | — | 无 | — |
| M | — | 无 | — |
| m | m1 | 本提交只处理了 review-8249d6e 的 m1 和 /plans 404；review-8249d6e 的 m2、m3，以及 review-7afbc06 的 m1、m2、m3、m5 仍未处理，也没有在自述中说明处理计划。建议列入待办 | 前端 |
