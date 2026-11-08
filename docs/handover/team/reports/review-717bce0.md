# 评审报告：前端 717bce0（T-F21 性能与窗口加载）

- 评审人：架构师（代审）　日期：2026-11-02（北京时间）
- 被评审提交：`717bce0`（2026-11-02 07:25 北京时间）。自述见：`T-F21.md`（此前漏审）
- 评审依据：
  - HEAD 上的 `docs/api-contract.md`（v0.2.8，含补充裁定 #17）；
  - 本提交自述对齐的契约版本：v0.2.7 §1.2。v0.2.8 新增的要求按设计不在本提交范围内，记为“待对齐”，**不算缺陷**。
  - 自述中的“契约待定项”不在本次裁定范围内，只做记录。
- 本次只读：没有改代码，没有提交，没有推送；主工作树没有动过。

## 0. 干净检出结果

方法：`git archive 717bce0 src/frontend docs | tar -x -C /tmp/rv8/717bce0`，然后在 `src/frontend` 下执行 `pnpm install --frozen-lockfile`。之后依次执行下表各步，与其他提交**串行**进行，不并行跑。环境：Node v24.22.1（CI 用 22）、pnpm 10.34.6。

| 步骤 | 命令 | 结果 |
|---|---|---|
| install | `pnpm install --frozen-lockfile` | rc=0，lockfile 未变 |
| typecheck | `pnpm run typecheck`（app/node/test 三个 tsconfig） | rc=0 |
| lint | `eslint . --max-warnings=0` | rc=0，0 警告 |
| test | `pnpm run test`（vitest run） | rc=0：Test Files 22 passed / 1 skipped（23）；Tests 358 passed / 1 skipped（359） |
| build | `pnpm run build` | rc=0 |
| check:dist | `pnpm run check:dist` | rc=0：dist 共 35 个文件，20 个示例标记 0 命中；业务代码块均 ≤ 500 kB |
| 被忽略的已跟踪文件 | `git ls-tree -r 717bce0 src/frontend \| git check-ignore --no-index --stdin` | 0 命中 |

说明：被跳过的 1 个测试文件是 `tracked-sources.test.ts`，因为 archive 导出里没有 `.git`，它会按设计跳过。上表最后一行就是替代它做的同类检查。测试数与自述一致。

## 1. 结论：**通过**

没有 B 级或 M 级问题。

## 2. 窗口加载（契约 §1.2，before/next_before）

- `useBarsWindow` 改用 `useInfiniteQuery`：
  - 第一页不带 `before`；
  - 之后用上一页的 `next_before` 取更早的数据；
  - `next_before` 为 null 时停止。
  - 这与契约的游标语义一致。
- `mergeBarPages` 按 `t` 升序排列并去重。即使多页的边界有重叠，也不会出现重复的 K 线。
- 多页的 `adjust_as_of` 不一致时（`consistentPages`），会调用 `resetQueries` 整窗重载，不会把不同复权基准的数据拼在一起。这符合契约中 `adjust_as_of` 变化时须整窗重取的要求。
- `syncAdjustAsOf` 增加了 `self` QueryKey（经 `hashKey` 比较），不会让自己失效；遇到 InfiniteData 时读取 `pages[0]`。
- 取更早数据失败时，已加载的窗口会保留，并且可以重试。个股表头和图表共用 250 根的窗口缓存，终端页用 120 根。日线原本就不轮询，所以没有回归。

## 3. 通用游标分页

- `useCursorPages` 和 `CursorPager` 已接入公告列表和管理员用户列表。`clampLimit` 把 limit 限制在 1–200，默认 50，与契约的分页上限一致。
- AG Grid 设置了 `rowBuffer`，并用 `applyTransactionAsync` 批量更新，属于纯性能改动，不涉及契约。

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
| m | m1 | K 线窗口没有使用契约中的 `from`/`to` 参数，只靠 `before` 向前翻页。这在功能上够用，自述也已列出 | 前端 |
| m | m2 | mock 指数日线的长度是固定的，不能覆盖“翻到最早一页”的边界情况。自述已列出 | 前端 |
| 记录 | — | 本提交没有同步 v0.2.8，按设计由 9547181 负责（见 `review-9547181.md`） | — |
