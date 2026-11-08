# 评审报告：T-F02 / T-F02a / T-F04 前端（提交 c68afb8、bd8200d，src/frontend）

- 评审人：架构师
- 依据：plan.md、api-contract.md v0.2.3（git HEAD，含同日补充：§4 `413 PAYLOAD_TOO_LARGE`、问题 37 新手 `intraday_t` 封顶 IT0C）、前端自述 `T-F01.md`（新增 4 条）与 `T-F02.md`（12 条）
- 方式：在独立 worktree `/tmp/rev-fe`（bd8200d）中检查和运行，未改动主仓库索引或工作区；没有提交，也没有改 docs。以下行号均以 bd8200d 为准，路径相对 `src/frontend/src/`。

## 结论：**有条件通过**（阻断 0 / 主要 4 / 次要 12 / 建议 6）

整体质量好：
- 认证流程、全局错误分派、管理端 404 隐身、导入两步提交（Idempotency-Key 按请求体换新）、对账的“可能原因（假设）”与摊薄成本口径说明都做到位。
- 只用 AG Grid Community，产物中没有 MSW，也没有密钥。

合并到可上线状态之前，必须先处理下面 4 条“主要”：
- **P1**：示例风险测评题库会进入生产包；
- **P2**：通知深链与契约路由不一致；
- **P3**：注册 `agreements` 取值与后端不一致；
- **P4**：`/portfolio` 持仓合并口径与其他页签不一致（需要契约补参数）。

## 1. 检查结果（worktree /tmp/rev-fe，bd8200d，pnpm 10.34.6）

| 项 | 结果 |
|---|---|
| lint（eslint --max-warnings=0） | 0 退出 |
| typecheck | 0 退出 |
| test（vitest） | 11 个文件，216 个用例全部通过（T-F01 复修后为 103 个） |
| build | 0 退出；主包 `index-*.js` 2,986.30 kB（gzip 900.69 kB），比 T-F01 时的 2.49 MB **继续增大**（见 m9） |
| check:deps | 0 退出 |
| pnpm audit --audit-level high | 0 退出（1 个 moderate，仅开发依赖） |
| AG Grid | 只有 `ag-grid-community` / `ag-grid-react`；`test/wording.test.ts` 有禁用 enterprise 的断言 |
| 产物检查 | dist 中没有 msw；但含“题库为示例数据”字样，说明示例题库进了生产包（P1） |
| 密钥 | 源码和 mock 中只有占位值（`mock-csrf` 等），没有真实密钥 |

## 2. 发现

### 阻断
无。

### 主要

**P1 示例风险测评题库进入生产构建，提交的 q_id 后端不认** — `i18n/accountLabels.ts:35`（`RISK_QUESTIONS`）、`pages/auth/OnboardingPage.tsx:46`、`:79`、`:80–88`
- 前端自拟了 6 道题，生产包中也带着，页面上还写着“题库为示例数据”。
- 后端 T-B03 没有题库，未配置时返回 `400 questionnaire not configured`。题库以后由 T-B15 提供，其 q_id 也不会和前端自拟的一致。
- 后果：真实用户在生产环境要么无法完成测评，导致 ⚖ 功能全部不可用；要么拿到的是没有合规依据的示例题库。
- 要求：
<redacted:sensitive-value-or-command>
  - 示例题库只在 `IS_MOCK` 下由 MSW 提供，不得写在 `i18n` 常量中打进生产包。
  - 接口返回 400 或 404（未配置）时，显示“风险测评题库尚未发布，暂不能开通候选信号与日报”，不得回退到示例题。

**P2 通知深链与契约 §5.1 路由不一致** — `pages/portfolio/PortfolioPage.tsx:25`、`pages/portfolio/ImportWizardPage.tsx:25–26`、`app/routes.tsx:63`；跳转处在 `components/AppShell.tsx:28`、`features/terminal/BottomPanel.tsx:48`（直接 `navigate(n.target.route)`）
- 契约 §5.1 `Notification.target.route` 规定：
  - `import_batch` → `/portfolio/import?batch={id}`；
  - `reconciliation` → `/portfolio?tab=reconciliation&account_id={id}`。
- 前端现状：
  - 只认路径参数 `portfolio/import/:batchId`，带 `?batch=` 会打开一个新的上传向导；
  - 持仓页读的是 `?account=`，忽略 `account_id`，会落到第一个账户。
- 要求：
  - 前端同时接受 `?batch=`（可以 `<Navigate>` 到 `/portfolio/import/:id`）和 `account_id`（可以把 `account` 作为别名保留）；
  - 补一条测试，从 mock 通知点击跳转到这两个页面。
- 契约不改。

**P3 注册 `agreements` 取值与后端不一致** — `pages/auth/RegisterPage.tsx:47`、`:94–98`；`i18n/accountLabels.ts:19`
- 前端按 consent key 提交 `["terms","privacy","signal_risk_disclosure"]`；后端 T-B03 要求的集合恰为 `{terms, privacy, risk_disclosure}`。联调时注册会一律返回 400。
- 裁定（T-F02 #11）：以契约的 consent key 为准，前端保持不变，**后端改**。前端去掉 `:94` 的 `[待契约确认]`。

**P4 持仓页签按全部账户合并，其他页签按单个账户** — `pages/portfolio/PortfolioPage.tsx:110`（“合并全部账户”）
- 契约 §7.2 `GET /portfolio` 没有 `account_id` 参数，前端只能合并显示；但成交、导入、对账页签都按所选账户，同一页面上口径不一致。用户切换账户后，持仓数据不变，容易误读。
- 裁定（T-F02 #7）：契约给 `/portfolio` 加可选 `?account_id=`。前端在后端支持之前保留“合并全部账户”说明；后端支持后传入所选账户，并保留“全部账户”选项。

### 次要

| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| m1 | `pages/admin/AdminUsersPage.tsx:14`、`:12` | 从 `disabled` 恢复到 `approved` 时不要求理由；plan 1736 写明“禁用/恢复（须填理由）” | `NEEDS_REASON` 改为 `t !== 'approved' \|\| from === 'disabled'` |
| m2 | `pages/admin/AdminUsersPage.tsx:16`、`:65` | 同 IP 高亮阈值写死为 3，plan 只说显示数量 | 按裁定 #8 改用服务端返回的 `same_ip_flag`；接口加上之前保留 3，并注明是临时值 |
| m3 | `api/accountTypes.ts:16`（`RegisterRequest`）、`pages/auth/RegisterPage.tsx:47` | 没有“申请说明”字段，但 plan 1733 有“可选申请说明”，管理端也在显示 `apply_note`（`accountTypes.ts:56`） | 按裁定 #1 契约加 `apply_note` 后，补一个 ≤200 字的 TextArea |
| m4 | `pages/auth/LoginPage.tsx:28–31` | 审核驳回 / 停用的 `reason` 放在 URL 查询串里，会进入浏览器历史和 nginx 访问日志 | 改用 `navigate(..., { state })` 传递；URL 只留 `status` |
| m5 | `pages/auth/LoginPage.tsx:40` | 兜底分支显示 `e.message`（可能是英文或服务端原文），没有走 `errorText()` | 改为 `errorText(e)` |
| m6 | `api/errorPolicy.ts:29`、`:68` | `FRESH_DATA_REQUIRED` 文案写“稍后自动重试”，但这个码只出现在写操作（如 `manual_refresh`），mutation 不会自动重试；对 query 的 3 次重试实际不会触发 | 按裁定 T-F01 新增 #2：去掉 query 的特判，文案改为“行情数据暂未更新，请 {retry_after_s} 秒后再试” |
| m7 | `pages/portfolio/ImportWizardPage.tsx:84` 附近 | 413 `PAYLOAD_TOO_LARGE` 只显示“文件过大”（`errorPolicy.ts:21`），选文件时没有本地预检 | 选文件时按 `import.max_file_bytes` 预检（取 `/meta/enums` 或常量，服务端仍为准）；413 时如果有 `details.max_bytes` 就显示上限 |
| m8 | `pages/portfolio/PortfolioPage.tsx:175` | “已作废”的提示只写“所属导入批次已撤销”，手工作废和更正替代的情况没有覆盖 | 按裁定 #5 显示 `void_reason` |
| m9 | 构建产物 | 主包 2.99 MB，继续增大（承接 T-F01 m9） | 路由级 `lazy()`：admin、portfolio、导入向导、图表 |
| m10 | `api/accountQueries.ts:92` | 管理端用户列表固定 `limit: 100`，没有按游标翻页 | 按 §1.2 游标加“加载更多” |
| m11 | `pages/settings/ProfilePage.tsx:76`、`:35` | InputNumber 没有 `precision`，可以输入 12.345，后端（最多 2 位小数）会返回 400 | 加 `precision={2}` |
| m12 | `i18n/accountLabels.ts:27` | 新手提示只写“短线周期分数封顶 59”；问题 37 / IT0C 规定 `intraday_t` 同样封顶，且画像未填也视同新手 | 改为“短线与日内做T 周期分数封顶 59（画像未填写同样处理；可在卡片上确认后覆盖）” |

### 建议

| # | 位置 | 建议 |
|---|---|---|
| s1 | `api/accountQueries.ts:119` | `createTrade` 每次调用都生成新的 Idempotency-Key。用户重复点击或网络重试时不幂等。和导入确认一样，由调用方持有 key，表单提交成功后再换新 |
| s2 | `api/errorPolicy.ts:57–58` | `CONSENT_REQUIRED` 一律跳到 `/onboarding`。裁定 #11 新增 `sensitive_financial_info` 后，`details.required` 可能不含 `signal_risk_disclosure`，应按 `required` 决定去向（导入前的单独同意弹窗），避免在引导页循环 |
| s3 | `pages/auth/OnboardingPage.tsx:39`、`i18n/accountLabels.ts:8` | `CONSENT_VERSION='v1'` 是写死的。按裁定 #3 改用 `/meta/consent-docs` 返回的版本 |
| s4 | `api/accountTypes.ts:108`、`accountQueries.ts:131` | `/imports` 列表复用了详情类型 `ImportBatch`。按裁定 #10 拆出 `ImportBatchSummary` |
| s5 | `pages/t-f02.test.tsx` | 共 12 个用例，缺少：注册（字段错误映射、registration closed）、画像（404 → 默认值、保存）、413、CSRF 头、登出清缓存、通知深链（P2）、管理员恢复须填理由（m1）。建议补上 |
| s6 | `pages/SuggestionDetailPage.tsx:81–85` | 封顶说明显示的是“规则 SH0C 不满足”，用户看不懂。建议显示规则的 `reason`（分类器 YAML 中已有，可以随 `caps[]` 返回），或者在前端为 SH0C/IT0C 准备文案 |

## 3. 前端问题的裁定

### T-F01.md 新增 4 条

| # | 问题 | 裁定 | 内容 |
|---|---|---|---|
| 1 | `DimensionCell` 括号位置 | **确认（契约笔误）** | 契约 §5.2 第 387 行中 `rules_total: int}` 后面多了一个 `}`，`exit_hits/exit_total` 属于同一对象。改文本，见第 4 节 D1。契约测试按“同一对象”解析即可 |
| 2 | `FRESH_DATA_REQUIRED` 重试范围 | **修改（前端）** | 契约 §4 规定这个码只用于**明确要求最新数据的写操作**（如 `manual_refresh`），读接口不会返回。所以：query 不需要特判，mutation 不自动重试；直接显示文案，有 `retry_after_s` 时写出秒数（见 m6）。契约不改 |
| 3 | 同意页路由 `/onboarding` | **确认** | 前端路由定为 `/onboarding?next=`（同时承担风险测评）；`/account-status` 也一并确认。plan 第 405 行的页面清单需要补上，见 D9 |
| 4 | CI Node 22 | **确认 + 运维动作** | CI 固定 Node 22，`engines.node >=22` 保留。运维（T-O）在首次 CI 运行后报告结果；建议仓库加 `.nvmrc`（内容为 22），本地开发也用 22 |

### T-F02.md 12 条

| # | 问题 | 裁定 | 内容 |
|---|---|---|---|
| 1 | username 长度 3–32 还是 4–32 | **确认 plan，修改契约** | 用户名 4–32 位，`^[a-z0-9_]+$`，服务端会先转小写，保留词返回 400 字段错误；密码规则按 plan 1733。契约 §7.1 同步修改，并加 `apply_note`（D2） |
| 2 | `resolution_choices` 取值 | **修改契约** | 按前端 mock 的取值定为枚举（D3）。另加 `IMPORT_ACCOUNT_MISMATCH: [confirm_new_holder_code]`。覆盖类选项为 `force_import`、`keep_import_void_manual`、`confirm_new_holder_code`，必须填理由。resolve 端点接受任何 `resolution_choices` 非空的提示，39 和 40 虽然 `needs_action=false`，也可以覆盖。后端（T-B02x）实现 |
<redacted:sensitive-value-or-command>
| 4 | 没有画像时的返回 | **确认** | `GET /me/profile` 没有画像时返回 `404 NOT_FOUND`，前端按默认值展示。契约写明（D2） |
| 5 | AdminUser / Trade / TradeCreate 结构 | **修改契约** | AdminUser 采用前端定义的结构，另加 `same_ip_flag`；Trade 加 `void_reason`、`voided_at`、`corrects_trade_id`；TradeCreate 加 `corrects_trade_id` 和 `reason`；新增 `POST /trades/{id}/void`（plan 1203、1488），见 D5 |
| 6 | CSRF 以哪里的值为准 | **确认（以 Cookie 为准）** | 响应体和 Cookie 中的值相同；前端优先读 Cookie，响应体中的值只作兜底（与后端 T-B03 的双提交实现一致）。前端去掉 `client.ts:60` 的 `[待契约确认]`。契约 §1.3 补一句（D6） |
| 7 | `/portfolio` 是否按账户 | **修改契约** | 加可选参数 `?account_id=`，不传时合并全部账户（D7）。见 P4 |
| 8 | 同 IP 阈值 | **修改 plan 与契约** | 阈值作为配置项 `admin.same_ip_highlight_threshold`（默认 3），服务端返回 `same_ip_flag`，前端不写死（D5、D8）|
| 9 | 单只仓位上限 | **确认** | 5–50，最多 2 位小数，用 decimal 字符串传输。契约写明（D2）；前端补 `precision`（m11） |
| 10 | `/imports` 列表项结构 | **修改契约** | 列表项定为 `ImportBatchSummary`（D5）。前端拆分类型（s4） |
| 11 | 邀请码与 agreements | **修改契约 / plan，后端修改** | ① V1 只用 `closed` 模式，`invite` 模式（plan 问题 18）留到以后，邀请码表和校验暂不做；后端在 `invite` 模式下返回 503 REGISTRATION_CLOSED 的做法确认；以后邀请码无效时返回 `400 VALIDATION_ERROR{fields:[{field:"invite_code"}]}`，不新增错误码。② `agreements` 的取值与 consent key 一致：`terms`、`privacy`、`signal_risk_disclosure`，**后端把 `risk_disclosure` 改过来**（P3）。③ plan 表 `consents.kind` 的取值（第 1240 行）与契约 key 对齐；《个保法》要求的单独同意（plan 2660）定为新 key `sensitive_financial_info`，首次 `POST /imports` 或 `POST /trades` 前必须同意，否则返回 `403 CONSENT_REQUIRED{required:["sensitive_financial_info"]}`（D2、D6、D10）|
| 12 | DimensionCell | **确认** | 同 T-F01 新增 #1（D1） |

## 4. 需架构师改文档（我本次未改；由当前编辑 docs 的同事或下一次 T-A 任务落实）

> 下面的行号以 HEAD 0111b51 为准；docs 正在被编辑，落实时请按小节定位。

- **D1 契约 §5.2 `DimensionCell`（约第 387 行）**：把 `` rules_passed: int, rules_total: int}`（`rules_passed/rules_total` 只统计 role ∈ {entry, filter, hold}，v0.2.2）, exit_hits: int, exit_total: int}` `` 改为
  `` rules_passed: int, rules_total: int, exit_hits: int, exit_total: int}`（`rules_passed/rules_total` 只统计 role ∈ {entry, filter, hold}，v0.2.2；`exit_*` v0.2.3） ``；
  后面的括注不变。§0 v0.2.3 变更表第 69 行的 `DimensionCell{...}` 也补上 `exit_hits, exit_total`。
- **D2 契约 §7.1**：
<redacted:sensitive-value-or-command>
  - `GET/PUT /me/profile` 补充：“无画像 → `404 NOT_FOUND`；`max_single_position_pct` 取值 5–50，最多 2 位小数”。
  - `POST /me/consents` 的 key 改为引用枚举 `consent_key`（§3 新增：`terms | privacy | signal_risk_disclosure | sensitive_financial_info`）。
<redacted:sensitive-value-or-command>
- **D3 契约 §4.1（表后新增“处理选项”小节）及 §5.1 `ImportFinding`**：

  | 提示码 | resolution_choices（第一个为默认） | 覆盖类（须填理由） |
  |---|---|---|
  | 8 `IMPORT_ACCOUNT_MISMATCH` | `[confirm_new_holder_code]`（不选则须改选账户） | `confirm_new_holder_code` |
  | 26/27/28 `ENCODING_LOW_CONFIDENCE` / `FORMAT_LOW_CONFIDENCE` / `SNAPSHOT_AS_OF_ASSUMED` | `[confirm]`（要改编码、解析器或快照时间，用 PUT options） | — |
  | 33 `UNKNOWN_SECURITY` | `[import_as_is, skip_row]` | — |
  | 34 `MARKET_INFERRED_CONFLICT` | `[use_master_data]` | — |
  | 36 `UNKNOWN_BIZ_TYPE` | `[keep_skipped, manual_entry]` | — |
  | 39/40 `DUPLICATE_IN_DB` / `DUPLICATE_IN_FILE` | `[keep_skipped, force_import]`（`needs_action=false`，但可覆盖） | `force_import` |
  | 41 `POSSIBLE_DUPLICATE_OF_MANUAL` | `[skip_import_row, keep_import_void_manual]` | `keep_import_void_manual` |

  其余提示码的 `resolution_choices=[]`。§7.2 resolve 那一行的说明改为：“`choice` 须在该提示的 `resolution_choices` 中（`resolution_choices` 非空即可处理，不限 `needs_action`）；覆盖类选项 `reason` 必填（≤200），否则 `400 VALIDATION_ERROR`；写审计”。

- **D4 契约 §7.1 / §7.10 新增两个端点**：
  - `GET /meta/consent-docs`（不需登录）→ `{items: [{key: consent_key, version: string, title: string, summary: string, url: string | null, required_for: "register" | "advice" | "import"}]}`；
<redacted:sensitive-value-or-command>
  - 题库和文书内容的责任人：T-B15 / 合规。
- **D5 契约 §7.2 / §7.9 结构定义**：
  - `GET /admin/users` 的元素：`AdminUser {id, username, display_name, status: account_status, role, apply_note: string | null, created_at, register_ip_region: string | null（粗粒度）, same_ip_registrations: int, same_ip_flag: boolean, review_reason: string | null, reviewed_at: string | null, last_login_at: string | null}`；分页（§1.2），`?status=&q=`。PATCH 补充：“`rejected`、`disabled`，以及从 `disabled` 恢复为 `approved` 时，`reason` 必填（plan 3.6），否则 `400 VALIDATION_ERROR`”。
  - `Trade {id, account_id, trade_date, trade_time: string | null, security_code, name, side: trade_side, qty: string(decimal), price: string(decimal), amount: string(decimal), fee_total: string(decimal) | null, net_amount: string(decimal) | null, source: "import" | "manual", batch_id: uuid | null, voided: boolean, void_reason: string | null, voided_at: string(datetime) | null, corrects_trade_id: uuid | null, created_at}`；`GET /trades?account_id=&security_code=&from=&to=&include_voided=`，分页。
  - `TradeCreate {account_id, trade_date, trade_time: string | null, security_code, side, qty: string(decimal), price: string(decimal), fee_total: string(decimal) | null, corrects_trade_id: uuid | null, reason: string | null（corrects_trade_id 非空时必填）}`，支持 `Idempotency-Key`；带 `corrects_trade_id` 时，在同一事务中作废原记录并写入新记录。
  - 新增 `POST /trades/{id}/void` 🔒，请求体 `{reason: string(1–200)}` → `200 Trade`；已作废的记录再作废返回 `409 INVALID_STATE_TRANSITION`。导入回滚造成的作废，`void_reason` 为 `"batch_reverted:{batch_id}"`。
  - `GET /imports` 的元素：`ImportBatchSummary {batch_id, account_id, kind, status: import_status, parser_id: string | null, stats, created_at, committed_at: string | null, reverted_at: string | null}`。
- **D6 契约 §1.3**：
  - CSRF 一句后补充：“响应体 `csrf_token` 与 Cookie 值相同，以 Cookie 为准（双提交：服务端用常数时间比较请求头、Cookie 与会话内令牌）；响应体值只供读不到 Cookie 的客户端兜底”。
  - “合规门槛”后补充：“导入和手工录入成交（`POST /imports`、`POST /trades`）要求已同意 `sensitive_financial_info`（《个保法》第 28 条单独同意，plan 2660），否则 `403 CONSENT_REQUIRED{required:["sensitive_financial_info"]}`”。
- **D7 契约 §7.2 `GET /portfolio`**：路径改为 `/portfolio?account_id=`，说明中加“`account_id` 可选，不传时合并全部账户”。
- **D8 plan 3.6 管理员能力（约第 1736 行）及 6.1 配置**：“同 IP 注册数”后补充“超过 `admin.same_ip_highlight_threshold`（默认 3）时高亮，只作提示、不自动拦截”；在 6.1 配置样例中加入该键。
- **D9 plan 第 405 行页面清单**：补充 `/onboarding`（首次登录：同意风险揭示与条款、完成风险测评，`?next=` 返回原页）和 `/account-status`（待审核、驳回、停用说明）。
- **D10 plan 第 1240 行 `consents` 表**：`kind` 改为 `terms / privacy / signal_risk_disclosure / sensitive_financial_info / email_notification`（与契约 `consent_key` 一致；原 `privacy_policy` 改为 `privacy`，`risk_disclosure` 改为 `signal_risk_disclosure`）；同时说明 V1 只用 `closed` 注册模式，`invite` 模式（问题 18）留到以后。
- 以上改完后，契约版本升为 **v0.2.4**，并在 §0 变更记录中逐条登记。

## 5. 谁做什么

| 角色 | 事项 |
|---|---|
| 前端（T-F02 跟进） | P1、P2、P3（去掉待确认标记）；m1–m12；s1–s6。等契约 v0.2.4 发布后，对接 D2–D7（apply_note、consent-docs、题库接口、`same_ip_flag`、作废和更正 UI、`ImportBatchSummary`、`/portfolio?account_id`） |
| 后端 T-B03 | `agreements` 改为接受 `signal_risk_disclosure`（P3）；用户名规则改为 4–32 并加保留词；加 `apply_note`；`/meta/consent-docs`、题库接口（内容为空时返回 404）；consents 的 kind 迁移（D10）；`sensitive_financial_info` 门槛；`/admin/users` 的结构与 `same_ip_flag`，恢复时理由必填 |
| 后端 T-B02x（导入 / 成交） | D3 处理选项枚举与 resolve 校验；D5 Trade 作废与更正、`POST /trades/{id}/void`、`ImportBatchSummary`；D7 `/portfolio?account_id=` |
| T-B15 / 合规 | 提供风险测评题库与计分规则、各同意文书的正文与版本号 |
| 运维 T-O | 报告 CI 在 Node 22 上首次运行的结果；可选：加 `.nvmrc` |
| 架构师 / 文档负责人 | 在当前文档编辑完成后落实 D1–D10，发布契约 v0.2.4 |
