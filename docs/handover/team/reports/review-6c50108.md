# 评审报告：前端 6c50108（T-A08 前端同步 v0.2.7 + T-F08 评审修复）

- 评审人：架构师（代审）　日期：2026-11-02（北京时间）
- 被评审提交：`6c50108`。自述见 `T-A08-frontend.md`，以及 `T-F08.md` 的“评审修复”一节。
  - 提交信息自称“T-A08 契约 v0.2.7 同步（22 处分歧）+ T-F08 评审修复”。
  - 只改 `src/frontend/`，共 35 个文件，+1411/−298 行。
- 评审依据：
  - 契约 v0.2.7（fa6d55d）：这次提交自称对齐的版本，按它评。
  - 契约 v0.2.8（HEAD，6ef79c4）：比 v0.2.7 多出的要求标为“待对齐”，**不算缺陷**。
  - 上几轮评审：`review-T-F02b-F05-F22-F03.md`、`review-T-F08.md`。
- 本次只读：没有改代码，没有提交。主工作树没有动过。

## ⚠ 先说明：6c50108 已经不在 main 上

`git reflog` 显示提交经过两次 amend：d949b7d → **6c50108** → **d1fccf6**。现在的 main 是：

d1fccf6 → 457a211（T-B02y）→ 116cb7e（T-B03d）→ 8249d6e（T-F24，HEAD）

`git branch --contains 6c50108` 没有输出，也就是说 6c50108 已经是悬空提交，推送 main 时不会推它，推的是 d1fccf6。

两者只差一个文件 `src/pages/t-a08.test.tsx`（+8/−3）：
- 在 6c50108 里，“system 实例不能归档”这个用例在示例数据没有系统实例时直接 `return`，等于空转。
- d1fccf6 改为先用 `mockAddInstance` 造一个系统实例，再断言 409 和 `INVALID_STATE_TRANSITION`。

所以 d1fccf6 是 6c50108 的改进版。我对两个提交都做了干净检出，结论同时适用于两者。

## 0. 干净检出结果

方法：`git archive <commit> src/frontend docs | tar -x -C /tmp/rv-…`，然后执行 `pnpm install --frozen-lockfile`（成功，lockfile 没有变化）。之所以把 docs 一起导出，是因为 t-f08 和 contract 两组测试要读契约原文。

| 导出 | typecheck | lint（`eslint . --max-warnings=0`） | vitest | build | check:dist |
|---|---|---|---|---|---|
| 6c50108 | 通过 | 通过（0 警告） | 20 个文件：19 个通过，1 个跳过；322 个用例：321 个通过，1 个跳过 | 通过 | 通过：33 个文件，20 个示例标记 0 命中，业务代码块都 ≤ 500 kB |
| d1fccf6 | 通过 | 通过 | 同上，321 个通过，1 个跳过 | — | — |

- 跳过的用例是 `src/test/tracked-sources.test.ts`（B1 守卫）。导出目录里没有 `.git`，所以它自动跳过。我用另一种方法补查了：把 `git ls-tree -r 6c50108 src/frontend` 的结果交给 `git check-ignore --no-index`，**0 个被忽略的文件**，结论等价。
- 只导出 `src/frontend`、不带 docs 时，t-f08 里逐字比对契约原文的 3 个用例会 `skipIf(!HAS_DOCS)` 并给出提示，不会失败（上轮 m8 已处理）。

**结论：干净检出全绿。**

## 1. 结论

**通过。** 没有 B 级问题，也没有 M 级问题，只有 4 条 m 级问题和一份 v0.2.8 待对齐清单。

可以推送，但有一个前提：推 main 时实际推的是 d1fccf6，同时会带上 457a211、116cb7e、8249d6e 三个提交（T-B02y、T-B03d、T-F24），**这三个不在本次评审范围内**。

## 2. 重点 1：上轮阻断项是否已修

| 项 | 结论 | 证据 |
|---|---|---|
| 上轮 B1：`mocks/licence.ts` 被 `.gitignore` 忽略 | **已修**（由更早的 527b65e 修复，6c50108 仍然正确） | 树里是 `mocks/licenceStore.ts`，源码里已经没有任何 `from './licence'`；check-ignore 0 命中；另有 `tracked-sources.test.ts` 守卫 |
| T-F08 B2：`scripts/screenshot-tf08.mjs` lint 报错 | **已修** | 全仓 `eslint . --max-warnings=0` 返回 0。本提交只给这个脚本加了 4 项计数，并把截图改成整页 |

## 3. 重点 2：契约一致性（按 v0.2.7 评）

**枚举**：我写脚本把 `api/enums.ts` 的 `ENUMS` 与 fa6d55d §3 枚举表逐个键比对，所有取值一致。其中有 5 项被脚本报成差异，是表格里中文括注导致的解析误报，人工核对后确认一致。`CONTRACT_VERSION = 'v0.2.7'`。

**22 处分歧**：我抽查了下面这些，和契约一致：
- 搜索：默认 `stock,cdr`，q 归一化后长度 1–20，limit 1–50，不分页；
- profile：`listing_status`、`suspended`、`risk_flag`；`board` 可以为 null；`industry` 是 `{taxonomy, code, name}`；补齐了曾用名、原代码和 attribution；
- 指数的财务、资金流、因子：200 + 空列表 + `no_source`；
- bars：带 `adjust_as_of` 和 `is_final`，基准日变化时丢弃缓存，有单元测试；
- 策略实例：状态机、游标、`INVALID_CURSOR`；`origin=system` 的实例不能归档；
- `/today`：四个新增字段，以及“查看全部”的 8 个去向。t-f08 测试直接解析契约表格来比对。
- `data_gaps[].route` 有站内路径白名单 `safeInternalRoute`：拒绝 `//`、`/\`、`http:`、`javascript:`，有测试。

## 4. 重点 3：前几轮的 M 级问题

| 来源 | 项 | 是否属于本提交 | 现状 |
|---|---|---|---|
| review-T-F02b-F05-F22-F03 M1 | 证书横幅不刷新 | 否（T-F22 的范围） | 6c50108 的树里已修：`licenceQueries.ts:14` 把状态写回 `qk.me`，`useMe` 有 `ME_POLL_MS` 轮询 |
| review-T-F02b-F05-F22-F03 M2 | 缺数原因只在悬浮提示里 | 部分属于（本提交改了 StockTabs、StockPage） | 已修：`DataStatusTag` 改为 `KeyTip`，可以 Tab 聚焦，读屏通过 aria-describedby 读到原因；`PriceChartPanel` 在空图时显示原因并带 `GapNote` |
| review-T-F08 M1 | 轮询失败后整页被错误框替换 | **是** | **已修**：`TodayPage` 只在没有数据时整页报错；有数据时在顶部显示“刷新失败，显示的是 {时间} 的数据”，正文保留。有测试（`t-f08.test.tsx:354`）：先成功，再返回 500，推进 15 秒后内容仍在 |
| review-T-F08 m1–m8 | — | 是 | m1：`/` 改为跳转 `/today`；m2：显示“前 N 条（共 50+ 条）”；m3：按 session 区分非交易日；m4：注明“默认账户”；m5：key 改为 `risk_event_id` 等；m6：收盘后和非交易日轮询放慢到 60 秒；m7：示例数据补了今日解除和今日失效；m8：没有 docs 时跳过。**全部已处理** |

## 5. 重点 4：证书安全与已作废内容

**证书安全**：没有问题。
- 我检查了新增行里所有带 `licen`、证书、token、secret 的内容，都只是状态名、`data_licence_unavailable`、`/settings/data-licence` 路由，以及 mock 的状态切换 `setMockLicence(uid, {status})`。
- 没有证书值，也没有掩码或后几位。
- 证书不可用时，数据缺口的第一条是 `data_licence_unavailable`，“去处理”链接指向证书设置页，有测试。

**已作废内容**：在 `src` 中搜索 consent、risk_assessment、`fit_ack`、`STRATEGY_FIT_ACK`、`kind: 'requires'`、`/onboarding`、`me/export`、数据导出、`PROFILE_OR_CONSENT`，非测试代码里只剩两处说明“已删除或忽略”的注释（`strategyTypes.ts:17`、`strategyHandlers.ts:130`）。没有残留。

## 6. 问题清单

### B（阻断）
无。

### M（主要）
无。

### m（次要）

| 编号 | 位置 | 问题 | 建议 |
|---|---|---|---|
| m1 | `app/routes.tsx` 的 `PLACEHOLDERS` | `/today` 的提醒和计划触发会链接到 `/plans/{plan_id}`，但路由里只有 `plans`，没有 `plans/:id`。点击后会进 404 页 | 加上 `['plans/:id', '计划详情']` 占位页，并给 t-a08 的“目标页接住参数”用例补这一条 |
| m2 | `mocks/marketFixtures.ts:161–173` | mock 搜索的 `kindOf` 只实现了 code_exact、name_exact、code_prefix、name_prefix、name_contains 五种匹配；同一层级内只按代码排序，没有按契约依次比较 listing_status、type、命中位置、简称长度；`matched_text` 恒为 null | 只影响示例数据，可以留到 v0.2.8 同步时一起补。至少同层先按 type 排序，并填上 `matched_text` |
| m3 | 6c50108 的 `t-a08.test.tsx` | “system 实例不能归档”在没有系统实例时 `return`，等于空转 | **d1fccf6 已修**；6c50108 已被 amend 替换，不需要再处理 |
| m4 | `T-A08-frontend.md` | 自述写“提交 d1fccf6”，评审任务给的是 6c50108，提交号前后不一致 | 以后 amend 后要同步更新自述和评审请求里的提交号；**最好不要 amend 已经送审的提交** |

## 7. 待对齐 v0.2.8（不算缺陷）

1. `CONTRACT_VERSION` 改为 `'v0.2.8'`，示例数据横幅、mock 注释同步。
2. `security_type` 加 `etf`（顺序是 stock cdr etf index），`gap_reason` 加 `not_applicable`，中文标签同步。
3. 搜索：mock 的 types 白名单加 `etf`，默认值改为 `stock,cdr,etf`，排序 stock > cdr > etf > index；搜索结果显示 ETF 徽标。
4. 个股页遇到 ETF：
   - 财务、资金流、因子、公告显示“不适用”（`not_applicable`），不要显示成“缺数”；
   - 价格显示 3 位小数；
   - 隐藏“建策略实例”入口，或者处理 `422 INSTANCE_SCOPE_INVALID{security_type:"etf", issue:"security_type_not_supported"}`；
   - board、风险警示、股本、行业为 null 时，显示“—”。
5. 证书设置页：处于 `paused_by_admin` 时禁用“测试”按钮（后端会返回 409），PUT 后仍然显示暂停状态。
6. 管理端：采集状态页改为按证书的 `licences[]` 表格，`AdminDataLicence` 加 `licence_id`；管理端类型按契约手写（`/admin/*` 不进 openapi）。
7. 注册页蜜罐（`website`、`form_started_at`）由 T-F24（8249d6e）负责，不在本次评审范围内。

## 8. 推送建议

本提交的部分可以推送：没有 B 级问题，干净检出全绿。但有两点要注意：
1. 推送 main 推的是 **d1fccf6**，不是 6c50108（后者已经悬空）。d1fccf6 的干净检出我也复跑了，全部通过。
2. 推 main 会一并推出 457a211（后端 T-B02y）、116cb7e（后端 T-B03d）、8249d6e（前端 T-F24）。这三个**没有经过本次评审**。如果要求“评审过才推送”，应该先评审它们，或者只推到 d1fccf6：`git push origin d1fccf6:main`。这条命令需要编排者确认后再执行。
