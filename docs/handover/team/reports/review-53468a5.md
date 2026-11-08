# 评审报告：前端 53468a5（T-F18 计划草案列表/详情、确认与放弃、失效重新生成）

- 评审人：架构师（代审）　日期：2026-11-02（北京时间）
- 被评审提交：`53468a5`（2026-11-02 08:11 北京时间）。自述见：`T-F18.md`
- 评审依据：
  - HEAD 上的 `docs/api-contract.md`（v0.2.8，含补充裁定 #17）；
  - 本提交自述对齐的契约版本：v0.2.8 §7.7。
  - 自述中的“契约待定项”不在本次裁定范围内，只做记录。
- 本次只读：没有改代码，没有提交，没有推送；主工作树没有动过。

## 0. 干净检出结果

方法：`git archive 53468a5 src/frontend docs | tar -x -C /tmp/rv8/53468a5`，然后在 `src/frontend` 下执行 `pnpm install --frozen-lockfile`。之后依次执行下表各步，与其他提交**串行**进行，不并行跑。环境：Node v24.22.1（CI 用 22）、pnpm 10.34.6。

| 步骤 | 命令 | 结果 |
|---|---|---|
| install | `pnpm install --frozen-lockfile` | rc=0，lockfile 未变 |
| typecheck | `pnpm run typecheck`（app/node/test 三个 tsconfig） | rc=0 |
| lint | `eslint . --max-warnings=0` | rc=0，0 警告 |
| test | `pnpm run test`（vitest run） | rc=0：Test Files 26 passed / 1 skipped（27）；Tests 408 passed / 1 skipped（409） |
| build | `pnpm run build` | rc=0 |
| check:dist | `pnpm run check:dist` | rc=0：dist 共 45 个文件，21 个示例标记 0 命中；业务代码块均 ≤ 500 kB |
| 被忽略的已跟踪文件 | `git ls-tree -r 53468a5 src/frontend \| git check-ignore --no-index --stdin` | 0 命中 |

说明：被跳过的 1 个测试文件是 `tracked-sources.test.ts`，因为 archive 导出里没有 `.git`，它会按设计跳过。上表最后一行就是替代它做的同类检查。测试数与自述一致。

## 1. 结论：**通过**

没有 B 级或 M 级问题。

## 2. 接口与请求体（§7.7）

- 列表：
  - `status` 支持多值，用逗号分隔；
  - 还支持 `security_code`、`signal_id` 筛选，用游标分页。
- 确认：请求体为 `{checklist_answers, risk_ack:true, chosen_qty, chosen_price, deviation_ack}`，其中 `chosen_qty` 以字符串传递。服务端返回的错误按字段显示在表单中。
- 确认成功后跳转到 `/plans/{plan_id}`。这个页面在 85e9b70 中已经补了占位页，跳转可以落地。
- 重新生成：只允许对 `stale`、`expired` 状态的草案操作，新旧草案之间不建立关联。契约 §7.7 原文写明“原草案保持不变，两者之间不建关联”，实现与之一致。
  - 自述第 3 条说“契约对此未作规定”，这个说法不准确，属于文档小误差，不影响实现。
- 详情页有 `CardDisclaimer`。最大亏损标注“估算”，费用带有认知标签。

## 证书安全与已作废内容

- **证书安全**：在本提交 `src/frontend` 的新增行中搜索 fingerprint、mask、suffix 字样，以及 ≥32 位的十六进制串，0 命中，没有出现任何证书值或其片段。证书相关的展示只用 `licence_id`、状态和日期。`check:dist` 的示例标记在产物中 0 命中。
- **已作废内容**：在新增行中搜索 consent、risk_assessment、`fit_ack`、`STRATEGY_FIT_ACK`、`/onboarding`、`me/export`、`PROFILE_OR_CONSENT`，0 命中。在 53468a5 的整棵树中有 3 处命中，都是已知且无害的：
  - `prototype/` 下的旧原型，不参与构建，本轮提交没有改动；
  - `strategyTypes.ts` 里一条“v0.2.5 起没有 fit_ack”的说明注释；
  - `strategyHandlers.ts` 里一条“忽略 fit_ack”的说明注释。

  这与 `review-6c50108.md` 的结论一致。
- 新增的 `console.log` 只出现在截图脚本中，业务代码里没有。

## 3. 问题清单

| 级别 | 编号 | 问题 | 归属 |
|---|---|---|---|
| B | — | 无 | — |
| M | — | 无 | — |
| m | m1 | `useCreatePlanDraft` 在遇到非网络错误后不会更换 Idempotency-Key，这一点和“确认”的处理不同。例如收到 `409 SIGNAL_NOT_EXECUTABLE` 后，在同一个组件里重试，会用同一个键发送同样的请求体。契约 §2 规定“24 小时内同键同体返回首次结果”，所以重试只会拿回第一次的错误。后端目前还没有实现幂等，所以现在不会暴露 | 前端 |
| m | m2 | 自述第 3 条称“契约未规定重新生成后新旧草案是否关联”，与契约 §7.7 原文不符，建议更正自述 | 前端 |
