# /watchlist 最小契约裁定（T-A129，主线补缺第 2 项）

状态：draft，架构裁定，不代表已实现。基线 main `965598b`。输入是后端 T-B126 第一阶段报告（`/workspace/team/reports/T-B126.md`）列出的 9 条歧义，编号 ①–⑨ 与该报告一致。本文只补 `docs/api-contract.md` §7.3 中 `/watchlist` 两行没写清的部分；本文与 §7.3 不一致处以本文为准，§7.3 原文不改。引用只写文件名、函数名、配置项名和用例名。

原则：取最小可用，够前端"自选入口"（加入、移出、列表）用即可。

## 0. 核对结论（依据）

- 表已存在：`app.watchlist_items`（`0001_baseline`，`db/tables/research.py` 的 `watchlist_items`），列 id、user_id、security_code、group_name、note、added_at、removed_at；无唯一约束，无 focus 列。
- 生产读路径全部按 `removed_at IS NULL` 过滤：`aggregates/service.terminal`、`workers/daily`、`intraday/engine`、`signals/service`、`reports/service`。`cli/delete_user_data` 已覆盖本表。
- **focus 已有存放处**：`db/tables/realtime.py` 的 `user_realtime_prefs.focus_codes`（text[]，plan 表设计"≤ 权益上限"）。`aggregates/service.terminal` 与 `intraday/engine` 已按它判定重点关注。所以 focus **不需要**给 `watchlist_items` 加列。
- 代码规范化已有公共函数：`api/v1/trades.normalize_code`（接受 600000 / 600000.SH / SH600000，大小写均可，6 位裸码先查主数据且排除指数，再按 `importing/preview.infer_market` 推断）；`SECURITY_CODE_PATTERN` 是其 schema。`api/v1/candidates`、`api/v1/horizon`、`api/v1/suggestions` 已复用。名称用 `api/v1/trades.security_names`（主数据优先，查不到为代码本身）。
- 重复 → `409 CONFLICT{field}` 的先例：`api/v1/candidates`（部分唯一索引，迁移 `0016_t_b10_research_candidates`）与 `plans/service`。
- 上限来源：`config/realtime.yaml` 的 `watchlist.per_user_cap`（100）与 `watchlist.focus_cap`（20），模型 `config_files.RealtimeWatchlist`；权益表 `entitlement_overrides` / `plan_entitlements` / `user_subscriptions` 的读取写法见 `api/v1/suggestions.refresh_interval`。`/me` 的 entitlements 目前恒为空对象（归 T-B28）。
- 前端：`src/frontend/src/api/types.ts` 有 `WatchlistItem` / `WatchlistResponse` 类型，mock `handlers.ts` 只有 GET；尚无任何写请求调用和入口组件（T-A127 第 2 项前端部分）。
- 幂等头：`common/idempotency.run`（不带头时不经 Redis），`api/v1/candidates` 已用。
- horizon 触发器 `watchlist_add` 只存在于 `config/horizon_classifier.yaml`、`config_files.RecomputeTrigger` 与 `schemas/enums`，生产代码没有任何触发调用方（`import_confirm` 同样没有）。
- `refresh_tier` 无任何后端实现（分层分配器未落地，plan 0A.3 / T003 待验证）。

## 1. 本单（T-B126）范围

做：`GET /watchlist`、`POST /watchlist`、`DELETE /watchlist/{security_code}`，一个迁移（部分唯一索引），新模块 `app/api/v1/watchlist.py`。

划出（见 §3）：`PATCH /watchlist/{security_code}`、`PUT /watchlist/{security_code}/focus`（⑦）、添加后的 horizon 重算 / universe / refresh_tier 分配（⑨）。

## 2. 逐条裁定

通用前置（所有路径）：未登录 → `401 AUTH_REQUIRED`；账号未批准 → `403 ACCOUNT_NOT_APPROVED`；写请求缺 CSRF → `403 CSRF_FAILED`。只读写本人行。

### ① 方法与路径绑定

裁定：方案 A。

| 方法 | 路径 | 本单 |
|---|---|---|
| GET | `/watchlist` | 实现 |
| POST | `/watchlist` | 实现 |
| DELETE | `/watchlist/{security_code}` | 实现 |
| PATCH | `/watchlist/{security_code}` | 划出，后续单实现 |
| PUT | `/watchlist/{security_code}/focus` | 划出（⑦） |

不提供 `GET /watchlist/{security_code}`；集合路径上的 PATCH/DELETE、条目路径上的 GET/POST 都由全局处理返回 `405 METHOD_NOT_ALLOWED`（带 `Allow`）。PATCH 在后续单落地之前，条目路径 PATCH 同样是 405。

理由：前端入口只需要列表、加入、移出；单条详情可由列表得到。

- Given 已登录已批准用户，When `GET /watchlist/600000.SH`，Then 405，`Allow` 含 DELETE。
- Given 同上，When `DELETE /watchlist`，Then 405，`Allow` 含 GET、POST。

### ② 重复添加

裁定：方案 A。本人已有同一规范化代码的**有效行**（removed_at 为空）→ `409 CONFLICT`，`details` 为 `{field: "security_code", existing_id: uuid}`（与 candidates 同形），不新增行。并发两次插入时以数据库部分唯一索引（⑧）兜底，捕获 IntegrityError 后同样返回 409。

`Idempotency-Key`（§1 通例）照常支持，作用域名 `watchlist:add`，用 `common/idempotency.run`；同键同体重放返回首次的 201 结果（先于业务判重），同键异体 → `409 IDEMPOTENCY_CONFLICT`。

理由：与仓库已有的唯一冲突先例一致；前端可把 409 显示为"已在自选中"。

- Given 本人自选已有 600000.SH，When POST `{security_code: "sh600000"}`，Then 409，`details.field` 为 security_code，`details.existing_id` 为该行 id，有效行数仍为 1。
- Given 他人自选有 600000.SH、本人没有，When 本人 POST 600000.SH，Then 201（他人数据不影响本人）。
- Given 首次 POST 带 Idempotency-Key K 得到 201，When 同 K 同体再 POST，Then 返回相同的 201 体，有效行数仍为 1。

### ③ 删除语义

裁定：软删（把 removed_at 写为当前时间），成功 `204` 无体。路径参数先过 `normalize_code`，格式不合法 → `400 VALIDATION_ERROR{fields:[{field:"security_code", issue:"invalid"}]}`。本人没有该代码的有效行（从未加过、已删除、或只存在于他人自选）一律 `404 NOT_FOUND`，不区分三种情况，避免探测他人数据。

理由：plan 表设计带 removed_at，所有既有读路径都按它过滤；物理删除会让 `signals/service` 等历史判断失去依据。不选"不存在也 204"，因为 §1 错误表把"不存在或不属于当前用户"统一为 404。

本单 DELETE 不改 `user_realtime_prefs.focus_codes`（focus 写入划出，见 ⑦；当前没有任何写入 focus_codes 的 API）。

- Given 本人有效行 600000.SH，When `DELETE /watchlist/600000`，Then 204；随后 GET 不含该代码；库中该行 removed_at 非空、行仍在。
- Given 同一行已删除，When 再 DELETE，Then 404。
- Given 只有他人有 000001.SZ，When 本人 DELETE 000001.SZ，Then 404，他人行不变。
- Given 任意，When `DELETE /watchlist/60000X`，Then 400，issue 为 invalid。

### ④ GET 排序

裁定：方案 A，`added_at` 升序，同时刻按 `id` 升序。只返回本人有效行，不分页。

理由：与 `aggregates/service.terminal` 读自选的顺序一致（终端"其余自选按加入时间"）。按 focus 优先由前端或终端聚合自己做，本接口不掺入。

- Given 本人先后加入 A、B、C，且 B 已删除，When GET，Then `items` 依次为 A、C。
- Given 他人有自选，When 本人 GET，Then 不出现他人行。
- Given 本人无自选，When GET，Then `items` 为空数组，`caps` 仍完整（前端空态）。

### ⑤ 代码校验与归一化

裁定：
1. 格式：复用 `api/v1/trades.normalize_code`，接受与 trades/search 相同的多种写法，规范化为 `{6位}.{SH|SZ|BJ}` 后存库和返回。不合法或推断不出市场 → `400 VALIDATION_ERROR{fields:[{field:"security_code", issue:"invalid"}]}`。请求体 schema 用 `SECURITY_CODE_PATTERN`。
2. 主数据：规范化后的代码必须在 `market.securities` 中存在，否则 `400 VALIDATION_ERROR`，issue 为 `unknown_security`（与 candidates 的 unknown_security 同口径）。
3. 类型与状态：type 为 index → 400，issue 为 `security_type_not_supported`；listing_status 为 delisted → 400，issue 为 `delisted`。其余类型（股票、ETF 等）与其余状态（含 delisting_period、missing_from_list、风险警示）允许。
4. 北交所旧代码（在 `security_code_history.old_code` 中）→ 400，issue 为 `superseded`，`fields` 元素额外带 `superseded_by`（新代码）。

理由：前端入口从 `/securities/search`（主数据）选证券，要求主数据存在不影响正常路径，又能挡住手输错码；ETF 在终端照常显示（契约 v0.2.8），故允许。指数与已退市是否允许属产品问题，澄清前取保守拒绝（见 §4 U1、U2）。

- Given 主数据有 600000.SH（stock, listed），When POST `{security_code: "600000"}`，Then 201，响应 `security_code` 为 600000.SH、`name` 为主数据简称。
- Given 主数据没有 600999.SH，When POST 600999.SH，Then 400，issue 为 unknown_security，无新行。
- Given 主数据 000300.SH 的 type 为 index，When POST 000300.SH，Then 400，issue 为 security_type_not_supported。
- Given 主数据某代码 listing_status 为 delisted，When POST 该代码，Then 400，issue 为 delisted。
- Given 任意，When POST `{security_code: "ABC"}`，Then 400，issue 为 invalid。

### ⑥ group / note 规则

裁定：方案 B。
- POST 可省略 `group`、`note` 键，省略等同 null；未知键 → 400（`extra="forbid"`，与 trades 的 `_Body` 一致）。
- 类型必须为字符串或 null，否则 400。
- 空串（长度 0）按 null 存；不做 trim，非空字符串按原样存（`watch_group` 选择器按原样精确匹配 group_name，见 §7.3 实例选择器说明）。
- 长度上限：`group` ≤ 32 个字符，`note` ≤ 500 个字符（按 Unicode 码点计），超出 → `400 VALIDATION_ERROR{fields:[{field:"group"|"note", issue:"too_long"}]}`。

理由：前端加入入口通常只传代码；上限是防滥用的技术值，不涉及产品取舍。

- Given 合法代码，When POST 只带 `security_code`，Then 201，响应 `group`、`note` 为 null。
- Given 合法代码，When POST `group` 为空串，Then 201，响应 `group` 为 null。
- Given 合法代码，When POST `note` 为 501 个汉字，Then 400，field 为 note、issue 为 too_long，无新行。
- Given 合法代码，When POST 带未知键 `focus`，Then 400。

### ⑦ focus

裁定：**`PUT /watchlist/{security_code}/focus` 划出本单**。本单不加迁移列，`WatchlistItem.focus` 在 GET 与 POST 响应中按"该代码是否在本人 `user_realtime_prefs.focus_codes` 中"计算，本人无该行时为 false。`caps.focus` 按 ⑩ 上限来源给出。

理由：focus 已有存放处且已被 terminal / intraday 读取，GET 不违反 `WatchlistItem` 必选字段；前端自选入口不需要设置重点关注。PUT 还要定 focus_cap 超限 key、"不在自选时"的错误码、删除自选时是否同步清 focus_codes，以及对 `intraday/engine` 盘中刷新集合的影响，牵涉盘中配额，不属最小可用。

后续归属：后端新单"watchlist focus + PATCH"（建议 T-B127 之后排），开工前由架构师补 focus 契约；须同时裁定 DELETE 自选是否同步移出 focus_codes。

- Given 本人 focus_codes 含 600000.SH 且自选有 600000.SH，When GET，Then 该项 `focus` 为 true。
- Given 本人没有 user_realtime_prefs 行，When GET，Then 每项 `focus` 为 false，`caps.focus` 为整数。
- Given 任意，When `PUT /watchlist/600000.SH/focus`，Then 本单下为 404 或 405（路由未注册），测试只断言"不是 2xx"。

### ⑧ 唯一性与"加回"

裁定：方案 B + 部分唯一索引。
- 加回 = 插入新行（新 id、新 added_at、group/note 取本次请求），旧行保持 removed_at，不恢复。
- 迁移 `0031`（新文件，`down_revision` 为当前单头 `0030`；若 T-A128 实现单 A 的迁移先合入，则顺延并改 down_revision，保持单头）：
  - 在 `app.watchlist_items` 上建唯一索引 `uq_watchlist_items_user_code_active`，列 (user_id, security_code)，条件 `removed_at IS NULL`。
  - 不加列、不改默认值、不动已有行。
  - upgrade 前先查有效重复行；有重复则抛错中止并打印重复组数（不打印代码与用户），不自动去重。
  - downgrade：删除该索引。
  - `db/tables/research.py` 的 `watchlist_items` 同步声明该索引（`Index(..., unique=True, postgresql_where=...)`），使元数据与迁移一致（`selfchecks/test_ta14_migrations` 单头检查保持绿）。
- 条数上限：只数本人有效行。同一用户的添加在事务内串行（先锁本人 `app.users` 行），保证 current 不超过 limit。

理由：新行保留完整加入/移出历史，读路径无需改；部分唯一索引是并发下的最终保证，与 candidates 迁移 0016 先例一致。

- Given 本人添加后删除 600000.SH，When 再 POST 600000.SH 带新 note，Then 201，新 id 不同于旧行，旧行 removed_at 不变，GET 只出现新行且 note 为新值。
- Given 空库迁到 0030，When upgrade 到 0031，Then 索引存在；downgrade 回 0030，Then 索引不存在。
- Given 迁移前库中存在同一 user_id 和 security_code 的两条有效行，When upgrade，Then 失败中止，表数据不变。
- Given 两个并发 POST 同一代码，Then 一个 201、一个 409，有效行数为 1。

### ⑨ 添加后的副作用（horizon 重算、universe、refresh_tier）

裁定：**划出本单**（方案 B）。本单 POST 只写 `watchlist_items`，不触发 `watchlist_add` 重算，不入队任何任务，不改实时 universe。`refresh_tier` 在本单固定返回 null，这是正式默认，表示"未分配"，前端不得当作错误。

理由：仓库里 horizon 重算触发器没有任何调用方（`import_confirm` 也没有），在本单接线等于顺带实现 horizon 调度；refresh_tier 分配器未落地；自选是否进入盘后分析范围已作为 T-A128 的 Q4 在待澄清中。

后续归属：horizon 触发接线归后端 horizon 调度单（与 `import_confirm`、`position_open_close` 一起做）；refresh_tier 归实时分层（plan 0A.3，T003 后）；自选进入日 K/分析范围随 T-A128 Q4 答复。

- Given 合法代码，When POST 201，Then `symbol_horizon_assessments` 行数不变，任务队列无新任务，响应 `refresh_tier` 为 null。
- Given 本人任意自选，When GET，Then 每项 `refresh_tier` 为 null。

### ⑩ 补充：上限与 caps（T-B126 已核对项 4 的落地方式）

- `caps.watchlist` / POST 上限 = 权益 `watchlist.per_user_cap`；`caps.focus` = 权益 `intraday.focus_cap`。取值顺序与 `api/v1/suggestions.refresh_interval` 相同（未过期覆盖 → 有效订阅的套餐值），但**取不到或值不是正整数时回落到 `config/realtime.yaml` 的 `watchlist.per_user_cap` / `watchlist.focus_cap`**，不返回 503。抽一个公共函数，不在 watchlist 模块里复制权益查询。
- 超限：POST 时本人有效行数 ≥ limit → `403 ENTITLEMENT_LIMIT_REACHED{key:"watchlist.per_user_cap", limit, current}`，无新行。
- 校验顺序：鉴权/CSRF → 请求体 400 → 代码 400 → 重复 409 → 上限 403 → 201。

- Given 未配置任何权益，When GET，Then `caps.watchlist` 为 100、`caps.focus` 为 20（等于 realtime.yaml 当前值；测试读配置，不写死数字）。
- Given 本人覆盖权益 `watchlist.per_user_cap` 为 2 且已有 2 条有效行，When POST 第 3 只，Then 403，details 为 key、limit 2、current 2。
- Given 同上已有 2 条且第 3 只与已有重复，When POST，Then 409（先判重）。
- Given 同上删除 1 条后，When POST，Then 201。

## 3. 划出项汇总

| 项 | 归属 | 前置 |
|---|---|---|
| PATCH 改 group/note | 后端后续单（与 focus 同单） | 本契约 ⑥ 的校验规则直接沿用 |
| PUT focus、删除时清 focus | 同上 | 架构师补 focus 契约（超限 key 建议 `intraday.focus_cap`） |
| watchlist_add 重算 | 后端 horizon 调度单 | 无 |
| refresh_tier 分配 | 实时分层 | T003 |
| 自选进入盘后分析/日 K 范围 | T-A128 实现单 | 用户答复 T-A128 Q4 |

## 4. 只有用户能定的产品问题（澄清前按保守默认实现）

- U1 指数（如沪深 300）能否加入自选？默认：不能（400 security_type_not_supported）。
- U2 已退市证券能否加入自选？默认：不能；退市整理期、风险警示可以。
- U3 每人自选上限取多少？默认：沿用 `config/realtime.yaml` 的 100（前端 mock 写的是 50，仅为演示数据）；数值待 T003。
- U4 删除后再加入，是否保留原分组和备注？默认：不保留，按本次请求的值（新行）。
