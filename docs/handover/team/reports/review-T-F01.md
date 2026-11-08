# 评审报告：T-F01 前端（提交 7049424，src/frontend）

- 评审人：架构师；日期：2026-11-01（MST）
- 依据：docs/plan.md、docs/api-contract.md **v0.2.2**（评审对象按 v0.2.2 实现）；同日 T-A03 已把契约升到 **v0.2.3**（提交 `b864d97`），受影响的条目标注「待同步契约 v0.2.3」
- 范围：提交 7049424（88 个文件，+14,780 行）。评审时工作区有其他代理未提交的改动（`src/api/enums.ts`、`client.ts`、`client.test.ts` 及新增 `accountTypes.ts` 等），**不在本次评审范围内**，也不是本次检查产生的

## 结论：**有条件通过**

| 级别 | 数量 |
|---|---|
| 阻断 | 0 |
| 主要 | 5 |
| 次要 | 12 |
| 建议 | 7 |

通过条件：修完 5 条「主要」（其中 M3 需按契约 v0.2.3 改），并同步契约 v0.2.3（见第 4 节）。「次要」可在下一迭代处理。

## 1. 检查结果

| 检查 | 结果 |
|---|---|
| `npm ci` | 0 退出；没有改动任何已跟踪文件 |
| `npm run lint` / `typecheck` | 均 0 退出 |
| `npm test` | 7 个文件、75 个用例全部通过（基于契约 v0.2.2）。**注意**：契约升到 v0.2.3 后，`src/mocks/contract.test.ts` 有 3 个用例失败（TerminalRow、契约版本、`/horizon-assessments` 字段）。这是预期结果，需前端同步 |
| `npm run build` | 0 退出；主包约 2.49 MB（Vite 默认 500 kB 告警被调高的阈值掩盖） |
| `npm run check:deps` | 0 退出；没有 `ag-grid-enterprise` / `<at>ag-grid-enterprise/*` |
| mock 是否进入生产包 | 没有。`dist/` 中找不到 msw、`mockServiceWorker`、“示例数据”。`main.tsx:16` 在 production 模式下直接返回，不启用 MSW |
| `npm audit` | 12 个 moderate，没有 high 或 critical |
| 密钥与许可证 | 没有发现密钥、licence、真实账户数据或第三方版权代码 |
| XSS | 没有 `dangerouslySetInnerHTML` / `innerHTML`。`prototype/dist` 里出现的同名字符串是 React 运行时自带的 |
| 令牌存储 | `localStorage` 只存布局（`layout.ts`、`TerminalPage.tsx:26–27`），不存令牌。CSRF 令牌从非 HttpOnly Cookie 读取（`client.ts:39–41`、`:51`），符合契约 §1.3 |
| AG Grid Enterprise | 三道防线：eslint `no-restricted-imports`、`check-deps.mjs`、`wording.test.ts` |
| 风险揭示 | `src/components/AppShell.tsx:87` 每页都渲染 `RiskDisclosure`，含 TradingView 署名 |
| 可解释性 | 候选卡显示理由、反证、失效、不可执行原因与解除条件。详情页有维度×策略矩阵，分歧时并列展示、不合并（`src/features/terminal/SuggestionPanel.tsx:31–35`）。“拟定计划草案”按钮已禁用并说明原因（`SuggestionPanel.tsx:80`） |
| 空、加载、错误状态 | 终端表、候选卡、日报、策略列表都有空状态与加载状态（`WatchTable.tsx:119`、`SuggestionPanel.tsx:23–25`、`DailyReportPage.tsx:24`、`SuggestionDetailPage.tsx:117`） |

## 2. 发现

### 主要

**M1 收到 304 时返回 undefined，会清空查询缓存** — `src/api/client.ts:61`
- 问题：`if (res.status === 204 || res.status === 304) return undefined`，收到 304 后返回 `undefined`，TanStack Query 会把它当成新数据写入，终端表瞬间变空。契约 §7.3、§9 要求 `/terminal`、`/today` 支持 304。
- 修复：304 时返回调用方传入的旧数据（`queryClient.getQueryData(key)`），或者抛出 `NotModified` 并在 queryFn 中捕获后返回旧数据；并加一个 304 单测。

**M2 没有按错误码分别处理** — `src/api/client.ts`（整体）、`ErrorBox`
- 问题：没有带类型的 `ErrorCode` 联合类型，所有错误都只显示 message。
  - `401 AUTH_REQUIRED` 应跳转 `/login`。
  - `CONSENT_REQUIRED` 应进入同意页。
  - `503 FRESH_DATA_REQUIRED` 应提示“数据刷新中”并稍后重试。
  - `405 METHOD_NOT_ALLOWED` 属于程序错误，应写入控制台或日志。
- 修复：从 `/meta/enums.error_codes` 生成 `ErrorCode` 类型。在 `client.ts` 中把错误映射为 `ApiError{code, http_status, details}`。全局 `QueryCache.onError` 处理 401 和 CONSENT；`ErrorBox` 按 code 显示文案。

**M3 周期理由的证据来自另一份快照** — `src/pages/SuggestionDetailPage.tsx:75` — **待同步契约 v0.2.3**
- 问题：`/horizon-assessments` 的 `reasons[].evidence_ids` 用候选卡的 `sg.evidence` 解析，两者不是同一快照，可能显示错误的证据。
- 修复：契约 v0.2.3 已在响应中加入 `snapshot_id` 和 `evidence[]`，改为只在本响应内解析，并删除借用 `sg.evidence` 的逻辑。同时改 `types.ts:56` 的 `HorizonAssessment`。

**M4 管理后台入口对所有用户可见** — `src/app/routes.tsx:34`、`src/app/nav.ts:24`
- 问题：`routes.tsx:34` 的 `['admin/*', '管理后台']` 占位页“管理后台”对所有人可见。plan 2.4 规定只有 admin 可见；契约 §7.9 规定非管理员访问 `/admin/*` 一律 404，不暴露其存在。
- 修复：只在 `me.role === 'admin'` 时注册该路由和导航项，否则渲染 `NotFoundPage`；补一条路由测试。

**M5 K 线止损线只取第一个有止损的策略，分歧时等于合并了结论** — `src/features/terminal/ChartPanel.tsx:33`（`strategies.find(...)`）
- 问题：`suggestion.strategies.find(...)` 取第一个带止损/止盈的策略，图上不标明来源。存在分歧时，这违背“并列展示、不合并”（plan 2.5.5、P1）。
- 修复：二选一。
  - 只画当前选中策略的止损线，并在图例中写出策略名。
  - `consensus.status === 'divergent'` 时不画线，改在候选卡中分别显示。

### 次要

| # | 位置 | 问题 | 修复 |
|---|---|---|---|
| m1 | `src/app/queryClient.ts:5` | 所有错误都 `retry: 1`，4xx 也重试 | 4xx 不重试；5xx 与网络错误重试 1–2 次 |
| m2 | `src/mocks/handlers.ts:75`、`:146` | mock 返回 `501 NOT_IMPLEMENTED`，这个码不在契约 §4 中；兜底处理器把用错方法也返回 404（应为 405 + `Allow` 头；`/admin/*` 例外，仍为 404） | 未实现的接口用 404 `NOT_FOUND`；兜底处理器区分路径不存在和方法不对 |
| m3 | `src/lib/format.ts:28` | `PROVIDER[e.provider]` 遇到映射表外的值（如旧契约 §5.1 的 `local`）时显示 "undefined"。`types.ts:33–34` 已按 §3 用 `DataProvider`，做法正确。**待同步契约 v0.2.3**（已统一为 `data_provider`，删除 `local`，与前端现有类型一致） | 删除 `types.ts:33` 的遗留注释；`providerText` 对未知值兜底显示原值 |
| m4 | `src/pages/SuggestionDetailPage.tsx:35`、`types.ts:197–205` | 纯离场策略（H-01）的单元格显示“—”。**待同步契约 v0.2.3** | `DimensionCell` 增加 `exit_hits/exit_total`，`rules_total = 0` 时显示“离场 x/y” |
| m5 | `src/pages/SuggestionDetailPage.tsx:82` | `inputs_missing` 只能统一提示“相关周期按封顶处理”。**待同步契约 v0.2.3** | 用新增的 `caps[]` 逐周期说明封顶原因（缺数据或 `SH0C` 等前提规则） |
| m6 | `SuggestionDetailPage.tsx:92–94`、`SuggestionPanel.tsx:13`、`queries.ts:101`（`useActiveReasons`） | 拉取全部生效原因后在前端过滤，每张卡都重复请求。**待同步契约 v0.2.3** | 改用 `GET /non-executable-reasons?suggestion_id=` 或 `signal_ids=` 批量查询 |
| m7 | `ChartPanel.tsx:53`、`types.ts:157` | 数据时效用行情时间 `q?.t` 代替，而行级没有 `data_as_of`。**待同步契约 v0.2.3** | `TerminalRow.data_as_of` 已加入契约，改读这个字段 |
| m8 | `ChartPanel.tsx:21`、`:30`、`queries.ts:69–70`（`useSignals`） | 分时标记取的是全市场 `/signals`（有条数上限）再按证券过滤，标记可能缺失；日 K 标记包含已作废、已过期的候选信号。**待同步契约 v0.2.3**（第 6 项：两个接口都要求带 `security_code`） | 请求时带 `security_code`；日 K 标记按 `state` 过滤，或者用样式区分 |
| m9 | `vite.config.ts:13`（`chunkSizeWarningLimit: 4000`） | 主包 2.49 MB，调高阈值把告警掩盖了 | 恢复默认阈值；图表、AG Grid、详情页按路由懒加载，或拆分 `manualChunks` |
| m10 | `src/api/queries.ts:103`、`:109` | `qk.reasons('*')` 是取巧写法；suggestions 的 key 不在 `qk` 中统一定义 | 所有 key 都在 `qk` 定义；失效时用前缀 `['reasons']` |
| m11 | `prototype/dist/` | 构建产物被提交进仓库 | 删除并加入 `.gitignore`；原型需要发布时由 CI 构建 |
| m12 | `package-lock.json` | `npm audit` 报 12 个 moderate | 评估是否只影响开发依赖；能升级的升级，其余记录豁免理由 |

### 建议

| # | 位置 | 建议 |
|---|---|---|
| s1 | `vite.config.ts:19` | 注释引用的 README 不存在：补上，或者改为引用 plan 2.10 |
| s2 | `SuggestionPanel.tsx:34` | `unanimous` 分支直接读 `strategies[0]`；为防御后端异常数据，加空数组保护 |
| s3 | `src/mocks/handlers.ts` | 补 `/today` 的 mock（T-F01 遗留第 12 项），以及 ETag/304 的 mock，用于覆盖 M1 |
| s4 | `queries.ts:35`、`:70` 等 | 15 秒轮询应只在 SSE 断开时启用（契约 §8）。SSE 接入后改为按连接状态切换 |
| s5 | `useBars(code, '1m')` | 盘中 SSE 未接入前，分时图不会刷新；建议在交易时段按 ≥ 15 秒轮询，或在 SSE 接入任务中处理 |
| s6 | `types.ts:240`（`DailyReportStock`）、`:157`（`TerminalRow`）、`DailyReportPage.tsx` | **待同步契约 v0.2.3**：`DailyReport.stocks[]` 加 `close/change_pct/data_status/max_risk_level` 并显示；`/terminal` 加 `trade_date`；`cash_available` 只在终端出现，标签写“可用资金” |
| s7 | `src/api/enums.ts:6`、`src/mocks/contract.test.ts` | `CONTRACT_VERSION` 改为 `v0.2.3`，契约测试按 v0.2.3 第 9 节新增断言更新（当前 3 个用例失败） |

## 3. 做得好的地方
- 契约测试直接解析 `docs/api-contract.md`，字段漂移能马上发现。
- 生产包与 mock 完全隔离；Enterprise 禁用有三道防线。
- 分歧并列、风险揭示全站可见；禁用词测试（`wording.test.ts`）覆盖了用户可见文案。

## 4. 需同步契约 v0.2.3 的前端改动清单
M3、m3、m4、m5、m6、m7、m8、s6、s7。另外：通知已读接口的响应维持 `204`（与现有 mock 一致），通知跳转直接使用服务端给的 `target.route`。

## T-F01 复审（提交 c68afb8 + bd8200d）

- 复审方式：在独立 worktree `/tmp/rev-fe`（bd8200d）中复核。
- 运行结果：lint、typecheck、test（11 个文件，216 个用例）、build、check:deps 均为 0 退出；audit 无 high 级问题。
- 行号以 bd8200d 为准，路径相对 `src/frontend/src/`。
- **复审结论：通过。** M1–M5 全部修复，次要问题中 11 条已修复、1 条恶化（m9），建议中 3 条完成、4 条留到下一迭代。
- 新增 4 条的裁定见 `review-T-F02.md` 第 3 节。

### 主要

| # | 状态 | 证据 |
|---|---|---|
| M1 304 清空缓存 | **已修复** | `api/client.ts:107–109`：304 时返回缓存的 200 响应体，没有缓存时抛 `ApiError(304,'NOT_MODIFIED')`；`:38` 有 `clearEtagCache()`，登录和登出时调用（`api/accountQueries.ts:38`、`:51`） |
| M2 没有按错误码分别处理 | **已修复** | `api/errorPolicy.ts:11–29`：错误码文案表（含 `PAYLOAD_TOO_LARGE`）；`:57–58`：全局处理 401 和 `CONSENT_REQUIRED`；`app/useApiErrorRedirect.ts:20–27`：401 时清缓存并跳转 `/login?next=`，`CONSENT_REQUIRED` 跳转 `/onboarding?next=`；`app/queryClient.ts:6–7`：query 和 mutation 都接入。余项：`FRESH_DATA_REQUIRED` 的文案和重试，见 review-T-F02 m6 |
| M3 周期理由的证据来自另一份快照 | **已修复** | `pages/SuggestionDetailPage.tsx:75`：改为在 `a.evidence`（周期分类响应自带的证据）中解析；`:81–85`：显示 `caps[]`。建议：当 `a.snapshot_id ≠ sg.snapshot_id` 时，标注“周期分类基于较新快照” |
| M4 管理后台入口对所有用户可见 | **已修复** | `app/nav.ts:25–27` `navMoreFor(role)`；`app/AdminGate.tsx:10` 对非管理员渲染 404；`app/routes.tsx:67–69` 三条 admin 路由都包在 AdminGate 中；测试见 `pages/t-f02.test.tsx:97` |
| M5 分歧时 K 线仍画止损线 | **已修复** | `features/terminal/chartStops.ts:18`：divergent 或 none 时不画线；`:20–22`：各策略价位不一致时不画线；`:24`：图例写明策略名；`features/terminal/ChartPanel.tsx:59–60`：图例文案 |

### 次要

| # | 状态 | 证据 |
|---|---|---|
| m1 4xx 也重试 | **已修复** | `api/errorPolicy.ts:65–70`：4xx 不重试，5xx 和网络错误重试 1 次；`app/queryClient.ts:9` |
| m2 mock 返回 501 | **已修复** | `mocks/handlers.ts:216–221`：方法不对时返回 405，带 `Allow` 头和 `details.allowed`；其余返回 404 |
| m3 provider 显示 undefined | **已修复** | `lib/format.ts:28–29`：未知值显示原值 |
| m4 纯离场策略单元格显示“—” | **已修复** | `lib/format.ts:31–33`：显示“离场 x/y” |
| m5 封顶原因不明确 | **已修复** | `pages/SuggestionDetailPage.tsx:81–85` 显示 `caps[]`。规则类封顶的文案还可以改进，见 review-T-F02 s6 |
| m6 拉全部原因后在前端过滤 | **已修复** | `api/queries.ts:119–120`：改为 `/non-executable-reasons?suggestion_id=` |
| m7 数据时效用行情时间代替 | **已修复** | `features/terminal/ChartPanel.tsx:55`：改用 `row.data_as_of` |
| m8 分时标记取全市场信号 | **已修复** | `api/queries.ts:79`：`/signals?security_code=&since=`；`features/terminal/chartStops.ts:28`：日 K 标记只显示 5 种状态 |
| m9 主包体积 | **未修复，且恶化** | 主包从 2.49 MB 增至 2.99 MB；`vite.config.ts:13` 仍是 `chunkSizeWarningLimit: 4000`。前端自述说留到下一迭代。要求在 T-F03 之前完成路由级拆包 |
| m10 query key 不统一 | **已修复** | `api/queries.ts:17–19`：全部 key 在 `qk` 中定义，`reasons('*')` 已去掉 |
| m11 构建产物进了仓库 | **已修复** | `git ls-files prototype/dist` 为 0 |
| m12 npm audit 告警 | **已修复** | 改用 pnpm 后，audit 只剩 1 个 moderate（仅开发依赖） |

### 建议

| # | 状态 | 证据 |
|---|---|---|
| s1 README 引用 | 未做 | `vite.config.ts:19` 仍引用 README，`src/frontend/README*` 不存在 |
| s2 `strategies[0]` 空数组保护 | 未做 | `features/terminal/SuggestionPanel.tsx:34` |
| s3 `/today` 和 ETag 的 mock | **已做** | `mocks/handlers.ts:79–87` 用 `jsonWithEtag` 实现 |
| s4 SSE 断开时才轮询 | 未做（依赖 SSE 任务） | `api/queries.ts:40`、`:81`、`:86` 仍按固定间隔轮询 |
| s5 分时图刷新 | 未做（依赖 SSE 任务） | — |
| s6 日报和终端字段 | **已做** | 前端自述中的 s6；`api/types.ts:407` 等处有 `trade_date` |
| s7 契约版本 | **已做** | `api/enums.ts:6` 为 `CONTRACT_VERSION = 'v0.2.3'` |
