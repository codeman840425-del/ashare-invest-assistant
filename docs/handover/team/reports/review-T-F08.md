# 评审报告：T-F08 今日关注 `/today`（前端，8405877）

- 评审人：架构师（代审）　日期：2026-11-02（北京时间）
- 仓库：`/workspace/ashare-invest-assistant`，前端 `src/frontend`；被评审提交 `8405877`（父提交 b79ce80），自述 `T-F08.md`
- 依据：
  - `docs/api-contract.md` v0.2.7（fa6d55d）：§7.3 `/today` 行、“`/today` 补充”、“查看全部”去向表；
  - `docs/plan.md` 2.3 能力 1（“今日关注”首页、数据完整性面板）、2.2 `situation`、2.4 页面清单与免责提示要求；
  - `docs/strategies/compliance/disclaimer.md`（1.0）；契约 v0.2.5、v0.2.6 的作废项：同意流程、风险测评、`fit_ack`、`HorizonCap.kind: requires`。
- 8405877 早于 v0.2.7。v0.2.7 才新加的要求单独列为“待对齐 v0.2.7”（第 4 节），**不算缺陷**。
- 本次只读代码，没有改代码、没有提交。

## 0. 检查方式与结果

- 干净导出：`git archive 8405877 src/frontend | tar -x -C /tmp/rv-f08`，在导出目录执行 `pnpm install --frozen-lockfile`（成功，lockfile 未变）。主工作树没有动。
- 补充验证：为了检查其余部分，另建了 `/tmp/rv-f08b`。其中 `src/frontend` 和 `docs` 都按 8405877 导出，再把 527b65e 的 `mocks/licenceStore.ts` 放成 `mocks/licence.ts`，然后再跑一遍。之所以要导出 docs，是因为 `t-f08.test.tsx:18` 和 `contract.test.ts` 读的是 `../../../../docs/api-contract.md`。

| 环境 | typecheck | lint（`eslint . --max-warnings=0`） | vitest | build | check:dist |
|---|---|---|---|---|---|
| 8405877 干净导出 | **失败**：`src/mocks/accountHandlers.ts(18)`、`src/mocks/session.ts(13)` TS2307 找不到 `./licence`（B1） | **失败**：`scripts/screenshot-tf08.mjs:3` `'document' is defined but never used`（B2） | **17 个文件全部失败**（同 B1） | **失败**（同 B1） | — |
| 8405877 + 补上 `mocks/licence.ts` + docs | 通过 | 仍失败（B2）；只查 `src` 时通过 | 17 个文件 271/271 通过 | 通过 | 通过（示例标记 0 命中，业务代码块 ≤ 500 kB） |
| 同上，契约换成 v0.2.7（fa6d55d） | — | — | `t-f08.test.tsx` 6/6 通过（v0.2.7 只新增了字段，三个列表的元素字段没有变） | — | — |

> 自述说“typecheck、eslint、vitest、build 全部通过”。这是在工作树里跑的：被 git 忽略的 `mocks/licence.ts` 在本地存在，而 eslint 也许只跑了 `src`。从仓库检出后，这些结果无法复现。

**上轮 B1 是否还在**：**还在。** 8405877 的 `.gitignore:38`（`licence.*`）仍然忽略 `mocks/licence.ts`，`git ls-tree 8405877` 里没有这个文件，而 `accountHandlers.ts:18` 和 `session.ts:13` 仍然 import `./licence`。这个提交没有修，也没有在干净导出上自检。另外顺带确认：后来的 527b65e（T-F22a）已把它改名为 `mocks/licenceStore.ts`。新名字已进入提交树，`git check-ignore` 不再命中，两处 import 也已改过。

## 1. 结论

**有条件通过。**
- 页面本身质量不错：
  - 只用 v0.2.6 §7.3 列出的字段；
  - 列表按服务端顺序展示（plan 2.3：按相关度，不按“股票好坏”）；
  - `security_code=null` 显示“账户级”且不给链接，与 v0.2.7 §1 的 `name` 例外一致；
  - 免责提示与 `disclaimer.md` 逐字一致，只展示、不需要勾选；
  - 带弱 ETag 的 15 秒轮询符合 §8；
  - 没有同意流程、风险测评、`fit_ack`、`kind: requires` 的残留（`src` 里只剩说明“已删除”的注释）。
- 通过的条件：
  1. 修复 B1、B2，使提交能从干净检出通过 typecheck、lint、test 和 build。后续的 527b65e 已修复两者，由它的评审负责确认；
  2. 处理 M1（轮询失败时整页被错误框替换）；
  3. 按第 4 节对齐 v0.2.7。

## 2. 问题清单

### B（阻断）

**B1　`mocks/licence.ts` 未进提交（上轮 B1，8405877 仍存在）**
- 位置：`.gitignore:38`（`licence.*`）；引用处 `src/frontend/src/mocks/accountHandlers.ts:18`、`src/frontend/src/mocks/session.ts:13`。
- 原因：干净检出时 typecheck、全部 17 个测试文件和 build 都失败。T-F08 的自检是在工作树上做的，所以没有发现。
- 怎么改：不放宽 `.gitignore`，把文件改名为不命中规则的名字，例如 `mocks/licenceStore.ts`（527b65e 已经这样做），并同步两处 import。自检改为在 `git archive HEAD` 的导出上跑。

**B2　lint 门禁失败：`scripts/screenshot-tf08.mjs:3`**
- 位置：`src/frontend/scripts/screenshot-tf08.mjs:3` 的 `/* global document -- … */`。eslint 配置对 `scripts/**/*.mjs` 用的是 node globals，`no-unused-vars` 把这条 global 声明报为未使用。
- 原因：`pnpm lint` 和 `eslint . --max-warnings=0` 都返回 1，CI 门禁会红。自述的“eslint 通过”无法复现（多半只查了 `src`）。
- 怎么改：删掉这行（527b65e 已删）。如果确实需要浏览器 globals，就像 `eslint.config.js` 对 `screenshot.mjs`、`screenshot-tf02.mjs` 那样，把 `screenshot-tf08.mjs` 加进同时启用 node 和 browser globals 的 `files` 列表。自检命令统一用 `pnpm lint`，不要只查 `src`。

### M（主要）

**M1　轮询一次失败，整页就被错误框替换，已有数据全部消失**
- 位置：`src/frontend/src/pages/today/TodayPage.tsx:70`：`if (q.isError || !q.data) return <ErrorBox …/>`；`src/frontend/src/api/queries.ts:45` 每 15 秒轮询。
- 原因：TanStack Query v5 在**后台重新拉取失败**时，`isError` 会变成 true，但 `data` 仍然保留。按 `api/errorPolicy.ts:81–86`：
  - 5xx 和网络错误只重试 1 次；
  - `429 RATE_LIMITED`、`503 FRESH_DATA_REQUIRED` 不重试。

  所以，后端短暂抖动（约 2 秒以上）或者被限流一次，首页就会整页变成“加载失败”。持仓、风险提示、草案等上一次的有效内容都看不到了，要等下一次轮询成功才恢复。终端页的做法是把 `ErrorBox` 显示在数据上方、保留表格（`features/terminal/TerminalPage.tsx:78`），两页的行为不一致。现有测试只覆盖“首次加载就失败”（`t-f08.test.tsx:129–133`）。
- 怎么改：只有 `!q.data` 时才整页显示错误。有数据时在页头显示一条 `ErrorBox`，或者“刷新失败，显示的是 {server_time} 的数据”，正文保留不动。补一个测试：先成功渲染，再让 `/today` 返回 500 或 429，推进一个轮询周期后，原有内容仍在，同时出现错误提示。

### m（次要）

| 编号 | 位置 | 问题 | 怎么改 |
|---|---|---|---|
| m1 | `src/app/routes.tsx:42` | plan 2.3 写的是“今日关注”**首页**，契约 §7.3 把 `/today` 称为“首页聚合”，但 `/` 仍然跳到 `/terminal`（自述遗留 3） | 需要产品或用户确认：如果首页确实是今日关注，就把 index 改为 `/today`；否则在 plan 2.3 写明首页是终端页。不改契约也行 |
| m2 | `TodayPage.tsx:37` | `more=true` 时计数显示“50 条”，看起来像总数只有 50 | 改成“前 50 条”，或者 `more` 时显示“50+ 条” |
| m3 | `TodayPage.tsx:99` | `not_yet` 一律显示“（收盘后生成）”。在非交易日（`session=non_trading_day`）或盘前，这句话会误导 | 按 `session` 区分：非交易日显示“非交易日，无日报”；盘前和盘中显示“收盘后生成” |
| m4 | `TodayPage.tsx:112` | 对账链接不带 `account_id`（自述遗留 4）。多账户时可能跳到别的账户 | 等契约给 `/today.reconciliation` 加 `account_id`（下一轮 T-A09 可一并加），再把它带上；在那之前保持现状，并在页面上注明“默认账户” |
| m5 | `TodayPage.tsx:143`、`170` | 列表 key 里用了数组下标 | 风险提示在 v0.2.7 有 `risk_event_id`，没有时退回 `control + security_code`；失效列表用 `suggestion_id + strategy_key + at` |
| m6 | `queries.ts:45` | 非交易日和收盘后也每 15 秒轮询 | 可以按 `session` 放慢（例如 `closed`、`non_trading_day` 时改为 60 秒）。不影响正确性，接入 SSE 后可以去掉 |
| m7 | `mocks/handlers.ts:39–61` | 默认 mock 的 `released_reasons`、`invalidations_today` 为空，`daily_report` 固定为 `not_yet`（自述遗留 6），手动浏览看不到这两块的非空样式 | 在 fixtures 里各加 1 条“今日解除”和“今日失效”的示例；对齐 v0.2.7 时一起补 alerts、plan_triggers、data_gaps 的示例 |
| m8 | `t-f08.test.tsx:18` | 测试直接读仓库根目录的 `docs/api-contract.md`，只导出 `src/frontend` 时会失败 | 可以保留（契约比对有价值），但要在 CI 和自检说明里写明需要完整仓库；也可以在 `docs` 不存在时 `skip` 并给出提示 |

## 3. 契约与 plan 逐项核对（v0.2.6 范围）

| 项 | 结果 |
|---|---|
| 顶层字段 `server_time`、`trade_date`、`session`、`market`、5 个列表、`daily_report`、`reconciliation`、`unread_notifications` | 全部展示，类型 `api/types.ts:445–458` 与 v0.2.6 一致 |
| 3 个列表的元素字段 | 测试直接解析契约原文比对（v0.2.6、v0.2.7 都通过） |
| 弱 ETag + 轮询 ≥ 15 秒 | `api/client.ts` 带 If-None-Match，304 时沿用缓存；`refetchInterval: 15_000`；页面隐藏时不轮询（默认行为） |
| 排序 | 前端不重新排序，符合 plan 2.3 |
| `security_code=null` | 显示“账户级”且不给链接，符合 v0.2.7 §1 的例外 |
| 措辞 | 参考仓位区间注明“模板参数，不是指令”；没有“推荐、买入建议”一类措辞 |
| 免责提示 | `CardDisclaimer` 与 `disclaimer.md` 1.0 逐字一致；只展示，不勾选，不记录 |
| 作废项 | 页面和本次改动里没有同意、风险测评、`fit_ack`、`kind: requires` |
| 越界字段 | 没有自定结构，也没有 `[待契约确认]` |

## 4. 待对齐 v0.2.7（不算缺陷，下一次提交要改的内容）

依据：契约 v0.2.7 §7.3 的 `/today` 行和“`/today` 补充”，§0 v0.2.7 #11–#13、#18。

1. **类型**（`api/types.ts:445–458`）：
   - `TodayResponse` 新增四个**必有**字段：`alerts: MoreList<TodayAlert>`、`plan_triggers: MoreList<TodayPlanTrigger>`、`data_gaps: MoreList<TodayDataGap>`、`evidence: Evidence[]`。
   - `risk_flags` 元素加 `risk_event_id: Uuid | null`。
   - 新增 `TodayAlert`、`TodayPlanTrigger`、`TodayDataGap` 三个接口，按契约逐字段写。
   - `api/enums.ts` 补 `alert_origin`、`alert_status`、`plan_condition_kind`、`data_gap_scope`（以 `/meta/enums` v0.2.7 为准）。
2. **“查看全部”去向**（`TodayPage.tsx:21–27` 的 `MORE_ROUTE`，以及测试 `t-f08.test.tsx:93–97`、`108`）：
   - `pending_plan_drafts`：`/plan-drafts` 改为 `/plan-drafts?status=pending,stale`
   - `released_reasons`：`/candidate-signals` 改为 `/candidate-signals?tab=released`
<redacted:sensitive-value-or-command>
   - `invalidations_today`：`/suggestions` 改为 `/suggestions?status=invalidated`
   - `focus`：仍是 `/terminal`
   - 新增 `alerts`：`/alerts`；`plan_triggers`：`/plans?status=triggered`；`data_gaps`：没有入口（`more` 恒为 false，不渲染“查看全部”）

<redacted:sensitive-value-or-command>
3. **新增三个区块**（`TodayPage.tsx`；`Section` 的 `ListKey` 要扩展到 8 个列表）：
   - **提醒**：显示 `severity` 标签、`title`（事实陈述，原样显示，不加动作措辞）、证券（null 时显示“账户级”）、`triggered_at`、`data_as_of`、受影响的计划（链接到 `/plans/{plan_id}`）、`status` 为 `new` 时的未读标记。`evidence_ids` 用 `EvidenceChips` 在同一响应的 `evidence[]` 中查找，并显示“事实 + 来源”。
   - **计划触发**：显示 `condition_kind`（`invalidation` 要醒目）、`condition_text`（用户自己写的条件，原样显示）、证券、`triggered_at`、计划链接 `/plans/{plan_id}`，以及证据。页面上明确“只提示条件已满足，不下单”。
   - **数据缺口**：显示 `reason` 的中文名（`GAP_REASON`）、`message`、`dataset`、受影响证券（最多 10 个，再加“共 {security_count} 只”）和 `since`。`route` 非空时给“去处理 ›”链接。**`route` 只接受以单个 `/` 开头的站内路径**：拒绝 `//`、`http:`、`javascript:`，不合格就不渲染链接。`data_licence_unavailable` 排在最前（服务端已经排好，前端不要重排）。这一块对应 plan 2.3 的“数据完整性面板”。
   - 顺序：服务端已排序，前端不重排。三块为空时显示“无”。数据缺口为空时，可以显示“数据完整”。
<redacted:sensitive-value-or-command>
5. **mock**（`mocks/handlers.ts:39–61`）：
   - `todayBody()` 补出四个新字段，每块至少 1 条示例，其中包括 1 条 `data_licence_unavailable`（`route: "/settings/data-licence"`）和 1 条 `user_input_missing`（`route: "/portfolio/import"`）。
   - `evidence_ids` 都要能在 `evidence[]` 中找到。
   - `risk_flags` 带 `risk_event_id`。
6. **测试**（`t-f08.test.tsx`）：
   - 字段比对从“`/today` 行”扩展到“`/today` 补充”中的三个对象：检查 `evidence_ids` 都能找到，检查 `alerts` 里没有 `origin=plan_condition`；
   - 8 个“查看全部”的去向按去向表断言，其中 `data_gaps` 没有入口；
   - `route` 白名单：恶意值不渲染成链接；
   - 契约 v0.2.7 验收 14、15 相关的断言。

## 5. 附：自述里遗留问题的去向

| 自述遗留 | 现状 |
|---|---|
| 1 “查看全部”对应关系 | v0.2.7 已写明去向表，见第 4 节第 2 条 |
| 2 提醒、计划触发、数据缺口没有契约 | v0.2.7 已补，见第 4 节第 3 条 |
| 3 首页仍是 `/terminal` | m1，需要产品确认 |
| 4 对账不带 `account_id` | m4，契约下一轮再补 |
| 5 链接指向占位页 | 正常，等对应页面任务实现 |
| 6 默认 mock 两个列表为空 | m7 |
