# 评审报告：前端 b34260f（T-F17 候选信号卡与不可执行原因）

- 评审人：架构师（代审）　日期：2026-11-02（北京时间）
- 被评审提交：`b34260f`（2026-11-02 08:00 北京时间）。自述见：`T-F17.md`
- 评审依据：
  - HEAD 上的 `docs/api-contract.md`（v0.2.8，含补充裁定 #17）；
  - 本提交自述对齐的契约版本：v0.2.8 §7.6。
  - 自述中的“契约待定项”不在本次裁定范围内，只做记录。
- 本次只读：没有改代码，没有提交，没有推送；主工作树没有动过。

## 0. 干净检出结果

方法：`git archive b34260f src/frontend docs | tar -x -C /tmp/rv8/b34260f`，然后在 `src/frontend` 下执行 `pnpm install --frozen-lockfile`。之后依次执行下表各步，与其他提交**串行**进行，不并行跑。环境：Node v24.22.1（CI 用 22）、pnpm 10.34.6。

| 步骤 | 命令 | 结果 |
|---|---|---|
| install | `pnpm install --frozen-lockfile` | rc=0，lockfile 未变 |
| typecheck | `pnpm run typecheck`（app/node/test 三个 tsconfig） | rc=0 |
| lint | `eslint . --max-warnings=0` | rc=0，0 警告 |
| test | `pnpm run test`（vitest run） | rc=0：Test Files 25 passed / 1 skipped（26）；Tests 391 passed / 1 skipped（392） |
| build | `pnpm run build` | rc=0 |
| check:dist | `pnpm run check:dist` | rc=0：dist 共 41 个文件，21 个示例标记 0 命中；业务代码块均 ≤ 500 kB |
| 被忽略的已跟踪文件 | `git ls-tree -r b34260f src/frontend \| git check-ignore --no-index --stdin` | 0 命中 |

说明：被跳过的 1 个测试文件是 `tracked-sources.test.ts`，因为 archive 导出里没有 `.git`，它会按设计跳过。上表最后一行就是替代它做的同类检查。测试数与自述一致。

## 1. 结论：**通过**

没有 B 级或 M 级问题。

## 2. 接口与请求体（§7.6）

- 列表：
  - 支持 `state`、`security_code`、`instance_id`、`horizon` 筛选，用游标分页；
  - 筛选条件写入 URL；
  - 同一证券方向相反的信号会标记“方向冲突”；
  - 带“模拟中”“观察中”徽标。
- 今日已解除：`released_since={trade_date}T00:00:00+08:00`，其中 `trade_date` 取自 `/today`。
- 不可执行原因：按 `signal_ids` 查询，不分页。
- 状态历史：兼容数组和 `{items}` 两种响应形式，统一归一化。
- 忽略：请求体为 `{note}`。
- 手动解除：请求体为 `{confirm:true, note}`。只在同时满足以下条件时才显示入口：
  - `<host>=false`；
  - 原因处于 active；
  - 不是 BLOCKLISTED。
- 策略跟踪统计用 `StatValue` 展示，带 n，样本少时标注“样本少”。
- `apiGet` 会去掉值为空的查询参数，不会发送 `?state=` 这样的空参数。

## 3. 披露要求

- 详情页有 `CardDisclaimer`。
- 列表页依靠 AppShell 全局的 `RiskDisclosure`，满足契约的提示要求。

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
| m | m1 | `useSignalReasonsAll` 不传 `status` 参数，而契约没有写明这个参数的默认值。如果后端默认只返回 active，已解除和已作废的原因在详情页就看不到。**这是契约的模糊点，只做记录，由架构师确认，本次不裁定** | 架构师（记录）/ 前端 |
| m | m2 | 策略跟踪统计是按 key 在 `useStrategyTemplates` 列表中查找策略的。这个列表可能分页，也没有传 `scope`，模板一多就可能找不到 | 前端 |
| m | m3 | 详情页的方向冲突只看 `useCandidateSignals(code)` 返回的第一页，超过一页的冲突会漏掉 | 前端 |
| m | m4 | “今日已解除”标签页对每个信号单独请求一次，共 N 个请求。自述已列出，建议以后改为批量接口或按 id 列表查询 | 前端 |
