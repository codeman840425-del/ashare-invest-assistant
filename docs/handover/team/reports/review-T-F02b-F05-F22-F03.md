# 评审报告：T-F02b / T-F05 / T-F22 / T-F03（前端）

- 评审人：架构师（代审）　日期：2026-11-02（北京时间）
- 仓库：`/workspace/ashare-invest-assistant`，前端 `src/frontend`
- 依据：`docs/api-contract.md` v0.2.6（含 v0.2.3–v0.2.6 变更表）、`docs/plan.md`、上一轮 `review-T-F02.md`，以及 2026-11-02 用户已定背景（自用、无风险测评/同意弹窗、fit_ack 作废、HorizonCap.kind 仅 gate|data_missing、S-03 等高风险模板默认关闭+开关旁固定说明、用户各自麦蕊证书且永不回显）
- 评审范围：7d1993f（T-F02b）→ 0e8a073（T-F05）→ 5f8b5e0（T-F22）→ b79ce80（T-F03，HEAD）
- 本次只读代码，未改代码、未提交、未推送。

## 0. 检查方式与偏差说明

- 仓库用的是 **pnpm**（`pnpm-lock.yaml`，`packageManager: pnpm<at>10.34.6`），没有 `package-lock.json`，`npm ci` 跑不了。改为：用 `git archive <commit>` 把每个提交导出到 `/tmp/rev-*`，在导出目录里执行 `pnpm install --frozen-lockfile`（lockfile 不变；各提交的 lockfile 与 HEAD 相同）。主工作树不动。
- 主工作树里有别的任务（看起来是 T-F08：`api/queries.ts`、`app/routes.tsx`、`i18n/labels.ts`、`styles.css` 有改动，`pages/today/` 未跟踪）的未提交改动，与本次评审无关，我没有碰。下文的行号都以**提交内容**（HEAD b79ce80 导出）为准。

| 提交 | typecheck | lint（--max-warnings=0） | vitest | build | check:dist |
|---|---|---|---|---|---|
| 7d1993f T-F02b | 通过 | 通过 | 227/227 | 通过 | — |
| 0e8a073 T-F05 | 通过 | 通过 | 236/236（14 个文件） | 通过 | — |
| 5f8b5e0 T-F22 | **失败**（同 B1） | — | — | — | — |
| b79ce80 T-F03（干净导出） | **失败**：`src/mocks/accountHandlers.ts(18)`、`src/mocks/session.ts(13)` TS2307 找不到 `./licence` | 通过 | **16 个文件全部失败**（同一原因） | **失败** | — |
| b79ce80 + 工作树里的 `mocks/licence.ts`（仅用于验证其余部分） | 通过 | 通过 | 265/265 | 通过 | 通过（示例标记 0 命中，业务块 ≤ 500 kB） |

> T-F22、T-F03 自报“typecheck/vitest/build 全部通过”，原因是他们在工作树里跑，被 git 忽略的文件还在本地；从仓库检出就构建不了。

## 1. 结论

| 提交 | 结论 | 说明 |
|---|---|---|
| 7d1993f T-F02b | **通过** | 上轮 P1–P4 都已修复并有测试（见 §3）；剩下的只有 m 级问题 |
| 0e8a073 T-F05 | **通过** | 同意/风险测评/fit_ack/`kind: requires` 已清干净，免责提示原文一致；只有 m 级问题 |
| 5f8b5e0 T-F22 | **不通过** | B1：`mocks/licence.ts` 被 `.gitignore` 规则 `licence.*` 忽略，没有进提交，干净检出的 typecheck/test/build 都失败；另有 M1（证书横幅状态不刷新）。证书安全本身做得好（见 §4） |
| b79ce80 T-F03 | **有条件通过** | 本提交自己的改动质量不错，契约内的接口都对齐了；条件：B1 修复后 HEAD 能从干净检出构建，并处理 M2（缺数原因只在悬浮提示里可见，没有 `data_licence_unavailable` 样例和测试）。契约外的接口都标成“待契约 T-A08”，不算前端缺陷（见附录） |

## 2. 问题清单

### B（阻断）

**B1　`src/frontend/src/mocks/licence.ts` 未进提交（5f8b5e0 起，HEAD 仍是）**
- 位置：`.gitignore:38`（`licence.*`，由 6908fc5 T-O09 在 06:09 加入；`mocks/licence.ts` 06:05 就已创建）；引用处 `src/frontend/src/mocks/accountHandlers.ts:18`、`src/frontend/src/mocks/session.ts:13`。`git status --ignored` 显示 `!! src/frontend/src/mocks/licence.ts`，`git ls-files` 里没有它。
- 后果：任何干净检出（CI、其他成员、部署构建）都会在 typecheck、vitest（16/16 个文件）和 `vite build` 失败。自报的检查结果在仓库状态下无法复现。
- 修复：**不要放宽 `.gitignore`**，这条规则是证书落盘的防线。把文件改成不命中规则的名字，例如 `mocks/licenceStore.ts`，同步改 2 处 import 和相关测试；用 `git check-ignore -v` 确认不再被忽略后提交。另外，自检流程（以及 CI，如果还没有）应改为在 `git archive HEAD`/干净 clone 上跑 typecheck/test/build，避免再有“只在本地存在”的文件。

### M（主要）

**M1　全局证书横幅依赖 `Me.data_licence_status`，验证结果出来后不会刷新（T-F22）**
- 位置：`src/frontend/src/api/licenceQueries.ts:22–24`（只在 mutation 成功时 invalidate 一次 `qk.me`），轮询（pending 时每 3 秒）只更新 `['me','data-licence']`；`src/frontend/src/components/AppShell.tsx:104` 的 `LicenceBanner` 读的是 `useMe()`（`api/queries.ts:33`，没有轮询）。
- 后果：PUT/测试之后状态是 `pending_verification`（横幅不显示）。之后验证变成 `invalid`/`expired`/`quota_exceeded` 时，横幅要等到窗口重新聚焦或刷新页面才出现。服务端在会话中途把证书改为 `quota_exceeded`/`paused_by_admin`，也同样不会反映出来（SSE `data_licence` 事件还没接入）。而横幅正是契约 v0.2.6 #8 规定的“你的数据证书不可用”提示入口。
- 修复：在 `useDataLicence` 的数据变化时同步写回 `qk.me`（`setQueryData(qk.me, m => m && {...m, data_licence_status: s.status})`），或者在 `pending_verification` 时让 `/me` 也随之轮询；SSE 接入前，`/me` 给一个低频轮询（例如 60 秒）。补测试：PUT `X-INVALID-…` 后不刷新页面，横幅应出现“证书无效”。

**M2　缺数/过期的原因只在悬浮提示里，空图不说明原因，也没有 `data_licence_unavailable` 样例（T-F03，对应评审重点 4）**
- 位置：
  - `src/frontend/src/components/common.tsx:36–48`：`DataStatusTag` 把 `gaps[].reason/message` 只放进 `Tooltip`，挂在一个不可聚焦的 `<span>` 上。键盘、触屏和读屏都拿不到。
  - `src/frontend/src/pages/stock/PriceChartPanel.tsx:48` 只特殊处理了 `pending`。`unavailable`、`stale` 且 `items` 为空时，`components/charts/KlineChart.tsx:33` 只显示“无日 K 数据”（周线也是这句），不给原因，也不引导去证书设置页。
  - 只有资金流页签（`pages/stock/StockTabs.tsx:102`）把 gaps 显示在了正文里。
  - `mocks/marketFixtures.ts`、`mocks/handlers.ts:106–163` 的个股/市场接口全部返回 `fresh`，没有 `stale`/`unavailable`/`gaps[].reason = "data_licence_unavailable"` 的样例，`t-f03.test.tsx` 也没有覆盖（T-F03 自报里也承认了）。
- 修复：抽一个 `GapNote` 组件，在 `stale`/`partial`/`unavailable` 时在正文显示 `GAP_REASON + message`；`data_licence_unavailable` 附“去设置数据证书 ›”链接（`/settings/data-licence`）。`DataStatusTag` 加 `tabIndex={0}` 和 `aria-describedby`，或者直接显示可见文字。空图时显示原因。MSW 加一个证书不可用的开关或示例代码，返回 `unavailable` 加 `data_licence_unavailable`，再补对应测试（K 线、财务、资金流、因子、公告、市场概览各至少一个）。

### m（次要）

| 编号 | 提交 | 位置 | 问题 | 修复 |
|---|---|---|---|---|
| m1 | T-F22 | `pages/settings/DataLicencePage.tsx:43, 64, 75` | `mutErr = put.error ?? patch.error ?? del.error ?? test.error`，`reset()` 只清本地 msg/other，不清各 mutation 的 error。前一次失败的提示会和后一次成功的提示同时留在页面上 | 提交前对四个 mutation 调 `.reset()`，或者只显示最近一次操作的错误 |
| m2 | T-F22 | `pages/settings/DataLicencePage.tsx:95` | 证书输入框是 `Input.Password` 加 `autoComplete="new-password"`，浏览器或密码管理器可能提示“保存密码”，把证书存进浏览器 | 改成 `autoComplete="off"`，再加 `data-1p-ignore`、`data-lpignore="true"` 等忽略标记；页面上说明“不要让浏览器保存” |
| m3 | T-F22 | `api/errorPolicy.ts:8–39` | `ERROR_TEXT` 没有 `DATA_LICENCE_IN_USE`、`DATA_LICENCE_NOT_SET`、`DATA_LICENCE_UNAVAILABLE` 的中文文案，会退回显示服务端 message | 补文案；`UNAVAILABLE` 按 `details.status` 显示对应状态，并附设置页链接 |
| m4 | T-F22 | `mocks/accountHandlers.ts:126–161` | 没有模拟 PUT 的 `429 RATE_LIMITED`（10 次/小时）、`/test` 的 429（5 次/小时）和 `503 INGEST_PAUSED`，前端对这三种情况的展示没有测试 | mock 加开关和计数，并补测试 |
| m5 | T-F22 | `components/StrategyEnableSwitch.tsx:33, 36` | `role=switch` 的 `aria-label` 随状态变成“启用X/停用X”，与 `aria-checked` 重复，切换后名称也会变。风险说明没有用 `aria-describedby` 关联到开关 | 名称固定为模板名，风险说明加 `id`，开关用 `aria-describedby` 指向它 |
| m6 | T-F22 | `pages/strategies/StrategiesPage.tsx:36–48` | 已有 `proposed` 实例时，打开开关会再 POST 一个新实例（重复），契约应走 `POST /strategy-instances/{id}/confirm`（契约:615）。`horizon: t.horizons[0]` 在 `horizons` 为空时是 `undefined`（类型漏洞，`noUncheckedIndexedAccess` 未开） | `proposed` 时调 confirm；`horizons` 为空时禁用开关 |
| m7 | T-F22 | `pages/strategies/StrategiesPage.tsx:28` | `accountId` 取第一个账户，账户加载失败或没有账户时没有任何提示 | 显示“请先创建账户”或 ErrorBox |
| m8 | T-F22 | `mocks/strategyHandlers.ts:60–61` | `STRATEGY_VERSION_NOT_RUNNABLE` mock 返回 422，契约是 **409**，details 应为 `{lifecycle}`，而且 simulating 也应拒绝（契约:335）。`STRATEGY_HORIZON_MISMATCH` 的 details 缺 `strategy_key`（契约:329） | 按契约改 mock 并补测试 |
| m9 | T-F22 | `api/strategyQueries.ts` | `/strategies`、`/strategy-instances` 用 `limit=200`，不跟 `next_cursor`，超过 200 条会被静默截断 | 跟游标翻页，或者在 `next_cursor` 非空时提示 |
| m10 | T-F03 | `pages/stock/StockPage.tsx:190–197` | 周期面板的封顶原因（caps）和画像提示（hints）只放在不可聚焦 `<span>` 的 Tooltip 里（a11y） | 改成可见文字或可聚焦元素 |
| m11 | T-F03 | `pages/stock/PriceChartPanel.tsx:40`；`components/charts/KlineChart.tsx:33` | 周线说明写“口径待契约确认”，但契约 v0.2.6 `Bar`（契约:445）已经写明“周线取该周最后交易日”，只有 1m 还待 T003。周线为空时也显示“无日 K 数据” | 去掉“待契约确认”；空态文案按 freq 区分 |
| m12 | T-F03 | `pages/stock/StockPage.tsx:80–98, 119` | 昨收取自“当日日 K”（`todayBar`）。盘中日 K 还没生成时，今开、最高、最低、昨收都显示“—”，涨跌额也不显示。契约 bars 响应顶层有 `pre_close`（1m 时为前收，契约:585），可以直接用 | 1m 响应已经在缓存里，用 `bars(1m).pre_close` 兜底 |
| m13 | T-F03 | `api/marketQueries.ts:107–111`；`pages/stock/StockPage.tsx:27–33` | 搜索 `q` 在请求参数和 queryKey 里没有 trim（组件里已经 trim，属于防御性问题）。`/stocks/600000.sh` 这类小写代码会被判为无效代码 | queryKey 和参数里 trim；路由参数先 `toUpperCase()` 再校验 |
| m14 | T-F02b | `pages/portfolio/PortfolioPage.tsx:27, 57, 316, 334` | URL 里的 `account_id` 不校验是否在账户列表里：未知 id 会显示原始 uuid，接口返回 404。拼 URL 时没有 `encodeURIComponent` | 不在列表里就回落到第一个账户并提示；拼 URL 时编码 |
| m15 | T-F05 | `components/RiskDisclosure.tsx:10` | `<footer role="note">` 覆盖了 footer 原有的 contentinfo 地标 | 去掉 role，或者把 footer 改成 `<div role="note">` |
| m16 | T-F03 | `mocks/handlers.ts:106–119` | bars mock 缺 `freq` 时默认按 `d` 处理（契约规定必填，应返回 400）；按 limit 截取后 `next_before` 没有更新 | 与契约对齐 |
| m17 | T-F03 | `pages/stock/PriceChartPanel.tsx:18` | 切换 freq 时没有 `keepPreviousData`，图表会闪一下“加载中” | 按 freq 加占位数据 |
| m18 | T-F03 | `components/charts/IntradayChart.tsx:98–105` | 分时图只在 `minuteEnds()` 的 240 个时刻上取 bar，`t` 不在序列里的 bar（09:30 集合竞价，或者上游实测是“分钟开始时刻”）会被静默丢掉 | T003 确认口径前，开发模式下统计丢弃数量并告警，加一条测试 |
| m19 | T-F03 | `pages/stock/StockPage.tsx:102–103` | 市值用 `Number()` 浮点乘法，只用于显示，影响很小 | 可以保持现状，或用 decimal 库 |

## 3. 上轮 review-T-F02 P1–P4 复核（T-F02b）

| 项 | 结论 | 证据 |
|---|---|---|
| P1 生产包不含 mock/示例数据 | 已修复 | `prod-bundle.test.ts`、`scripts/check-dist`；HEAD 构建后 check:dist 示例标记 0 命中 |
| P2 深链/路由与契约 `target.route` 一致 | 已修复 | `PortfolioPage.tsx:26–27` 读 `account_id`，并兼容旧参数 `account`；`ImportWizardPage.tsx:28–29` 把 `?batch=` 重定向到 `/portfolio/import/:id`；`fixtures.ts:639–640` 的路由已改为契约路由 |
| P3 注册不再发 agreements | 已修复 | 注册页请求体没有 `agreements`；mock 遇到旧字段时容忍并忽略（`accountHandlers.ts:93`） |
| P4 持仓按账户查询 | 已修复 | `queries.ts:105` `usePortfolio(accountId)` 带 `account_id` |

## 4. 重点核查结论

1. **契约一致性**：`api/enums.ts` 的 `CONTRACT_VERSION = 'v0.2.6'`。`data_licence_status`、`data_licence_tier`、`gap_reason.data_licence_unavailable`、三个 `DATA_LICENCE_*`（409）、`STRATEGY_VERSION_NOT_RUNNABLE`（409）都已同步。`Me` 七个字段、`DataLicenceStatus`、`QuoteItem`、`BarsResponse`、`MarketOverview` 与契约一致。`/securities?q=` 按数组解析，正确。`HorizonCap.kind` 是 `'gate' | 'data_missing'`（`types.ts:56`）。偏差见 m6、m8、m9、m16；契约里没有的部分见附录。
2. **废弃内容残留**：同意流程、风险测评、`fit_ack`、`STRATEGY_FIT_ACK_REQUIRED`、`kind: 'requires'`、`/onboarding`，在运行代码中都已清除。grep 结果只出现在注释、“断言已删除”的测试和 mock 的容忍分支里。`prototype/` 目录还留着旧代码，但不进生产构建（建议后续单独清理或归档）。horizonCaps 已去掉 IT0。高风险说明 `HIGH_RISK_STRATEGY_NOTE` 与 plan 原文一致，模板默认不启用、不自动匹配。
3. **证书安全**：做得好。
   - 输入框不回显，可见性切换已关闭（`visibilityToggle={false}`），提交后立即清空。
   - 证书只放在 ref 里，mutation 的 variables 只含元数据，query/mutation 缓存里没有证书值。
   - 证书不进 console（`errorPolicy` 只对 405 打日志）、不进 localStorage（localStorage 只存终端布局）、不进 URL。
   - MSW 只存 FNV 摘要，种子数据是 `seed-2` 这类假值。`t-f22.test.tsx` 和截图脚本用随机假证书，在 DOM、query/mutation 缓存和请求日志里逐个检查 4 字符子串，确认没有泄漏。
   - 只剩 m2（浏览器可能提示保存密码）。注意：mutation 默认 retry=0；以后如果给 PUT 加 retry，会发出空证书，需要留意。
4. **缺数与过期的展示**：见 M2。终端、建议卡等老页面已有 `stale`/`unavailable` 样例（`fixtures.ts:80–116`），个股和市场页没有。
5. **测试与 a11y**：HEAD 有 265 个用例（补上 licence.ts 后），覆盖面不错；缺口见 M1、M2、m4。a11y 问题见 m5、m10、m15。

## 附录 A：T-F03（以及 T-F22 策略库）前端调用或 mock 的接口清单

> 标“待契约 T-A08”的项是前端先行定义的结构，**不算前端缺陷**，请 T-A08 定稿时逐条确认或改名。类型定义在 `src/frontend/src/api/marketTypes.ts`；调用在 `src/frontend/src/api/marketQueries.ts`（行号如下）；mock 在 `src/frontend/src/mocks/handlers.ts:106–163` 和 `mocks/marketFixtures.ts`。

### A.1 契约里已有的接口（已对齐）

| 接口 | 前端参数 | 用到的响应字段 | 位置 |
|---|---|---|---|
| `GET /securities?q=` | `q`（防抖 250 ms，已 trim） | `[{security_code, name}]`（≤ 20 条，不分页） | marketQueries:110；SecuritySearch |
| `GET /quotes?codes=` | 单个代码 | `items[].{security_code, name, price, change_pct, volume, amount, t, data_status, data_as_of, gaps}`；15 秒轮询 | marketQueries:40 |
| `GET /securities/{code}/bars` | `freq`=1m/d/w，`adjust`（1m 用 none，其他用 qfq），`limit`（1m 240 / d 250 / w 120）；不用 `from/to/before` | `pre_close`、`items[].{t, open, high, low, close, pre_close, volume, amount, avg_price}`、`data_status/data_as_of/gaps`；`next_before` 不用 | marketQueries:50；PriceChartPanel:12 |
| `GET /market/overview` | 无 | `trade_date, session, indices[].{security_code, name, price, change_pct, amount}, breadth{up, down, flat, limit_up, limit_down}, regime, regime_position_range{min_pct, max_pct}, turnover_total` + DataStatusBlock；15 秒轮询 | marketQueries:92 |
| `GET/PUT/PATCH/DELETE /me/data-licence`、`POST /me/data-licence/test` | PUT `{licence, tier, has_quant_pro, expires_on}`；PATCH 只改元数据 | `DataLicenceStatus` 全部字段；pending 时每 3 秒轮询 | licenceQueries |
| `GET /strategies`、`GET/POST /strategy-instances`、`POST /strategy-instances/{id}/pause\|resume` | `limit=200`；POST 按契约 613 | 实例的 `id, status, warnings[]` | strategyQueries |

### A.2 待契约 T-A08（前端先行定义）

| 接口 | 前端参数 | 前端假定的响应结构 |
|---|---|---|
| `GET /securities/{code}` | 无 | `{security_code, name, exchange: SH\|SZ\|BJ, board: main\|chinext\|star\|bse, industry\|null, concepts[], list_date\|null, status: listed\|suspended\|delisted, risk_warning: bool, total_shares\|null, float_shares\|null}` + DataStatusBlock；404 → “未找到证券” |
| `GET /securities/{code}/financials` | `limit=8` | `{security_code, name, items[]: {period_end, announce_date\|null, revenue, revenue_yoy_pct, net_profit, net_profit_yoy_pct, eps, roe_pct, gross_margin_pct, debt_ratio_pct, operating_cash_flow}（全部可为 null，按累计口径）}` + DataStatusBlock；排序（新→旧还是旧→新）待定 |
| `GET /securities/{code}/fund-flows` | `days=60` | `{items[]: {trade_date, main_net, super_large_net, large_net, medium_net, small_net, main_net_pct\|null}（前端假定按日期升序）}` + DataStatusBlock；“主力 = 超大单 + 大单” |
| `GET /securities/{code}/factors` | 无 | `{trade_date, calc_version, items[]: {factor_id, name, group: value\|quality\|growth\|momentum\|volatility\|liquidity, value\|null, unit\|null, pct_rank_market\|null, pct_rank_industry\|null（0–100）}}` + DataStatusBlock |
| `GET /securities/{code}/announcements` | `limit=30`（不跟 `next_cursor`，只提示去巨潮查询） | `Paged<{id, published_at, title, category\|null, url\|null}>` + DataStatusBlock；前端只渲染 http(s) 外链（`noopener noreferrer`），不抓取 |
| `GET /market/sector-flows` | `kind=industry\|concept`，`limit=20`；60 秒轮询 | `{kind, trade_date, items[]: {sector_id, name, change_pct\|null, main_net\|null, up_count\|null, down_count\|null, leader: {security_code, name, change_pct}\|null}}` + DataStatusBlock |
| `GET /strategies` 的 `risk_level` | — | `StrategyTemplate.risk_level?: card_risk_level`（`strategyTypes.ts:17`）；契约列表还没有这个字段 |
| `GET /strategy-instances` 列表元素 | — | `{id, strategy_id, strategy_version_id, scope, account_id, security_code, horizon, status, …}`（`strategyTypes.ts:33–42`，自定义结构） |
| 其他待定 | — | `/securities?q=` 是否包含指数（mock 只返回个股）；`DataStatusBlock.data_as_of` 是否可为 null（前端类型为非空） |

### A.3 周 K 日期的处理

- 请求：`freq=w&adjust=qfq&limit=120`。
- 渲染：`KlineChart` 用 `t.slice(0, 10)` 作为 lightweight-charts 的 business day，**原样使用后端给的 `t`，不做任何换算**；MA5/20/60 按周计算。
- 页面文案：显示“周线日期取该周最后交易日（口径待契约确认）”。契约 v0.2.6 `Bar` 已经定为“周线取该周最后交易日”，文案应去掉“待契约确认”（m11）。
- mock：`marketFixtures.ts` `toWeekly()` 把日线按自然周（周一起算）聚合，`t` 取该周最后一个交易日，`pre_close` 取上一周收盘，`avg_price=null`，与契约一致。
- 1m：`t` 视为分钟结束时刻（09:31–11:30、13:01–15:00，共 240 根）；交易日取 `items[0].t` 或 `data_as_of` 的日期部分。口径待 T003/T-B05，见 m18。
