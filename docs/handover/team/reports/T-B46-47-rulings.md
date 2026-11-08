# T-B46 / T-B47 待定项裁定

架构师 · 2026-11-01（America/Denver）
文档提交：`4532478`，另有 `db486aa` 只把新任务编号改为 T-B30a，因为 T-B48 已被 v0.2.9 同步任务占用。都只在本地，未推送。只改了 `docs/api-contract.md` 与 `docs/plan.md`。契约版本号仍为 v0.2.9，变更表新增 #27（T-B46/T-B47）和 #28（评审 be607b3/f72b8c7/8fd9502）。
涉及产品取舍的项都按最保守的默认执行，登记为 plan 第 9 节问题 75–79。

对应关系：T-B46 第 5 节架构师项 1–9 → R1–R7（第 1、6、9 项并入 R6）；T-B47 → R8–R11；追加裁定 A–E 在文末。

---

## R1 持仓快照行的形状（T-B46 第 2 项）
- **接受**：`import_rows.kind=snapshot_position` 与部分唯一索引都是内部实现，不进契约。
- 规范化后的快照行至少包含证券代码、数量、可卖数量、成本价和参考价。参考价可空。
- <account-field>只存 HMAC 与掩码。

## R2 上传与解析方式（T-B46 第 3 项）
- **接受**：上传只收单个文件，不用 Idempotency-Key。重复上传由 `IMPORT_DUPLICATE_FILE` warning 覆盖，契约原本就这样写。
- **接受**：V1 单实例，用 BackgroundTasks 解析；resolve 同步重新解析。
- 主数据为空时，按代码段推断市场，行照常导入。不在主数据中的持仓 `security_type=null`，按 R6 估算显示，不跑策略。

## R3 /accounts 与限速（T-B46 第 4 项）
- **接受**字段映射。`POST /accounts` 只收 `broker_name`（1–32，必填）和 `alias`（1–32，可空），已写进契约。
- **接受**限速初值：accounts 20/h，imports 上传 30/h、写 120/h，trades 写 120/h。后续调整走 plan 6.1 配置，不改契约。
- **接受**：revert 只作废（`voided`），不物理删除。

## R4 错误分界与对账符号（T-B46 第 5 项）
- 表头缺必需列 → 文件级 `IMPORT_COLUMN_MISMATCH`。列存在但单元格为空 → 行级 `IMPORT_REQUIRED_FIELD_EMPTY`。
- `format_score` 是内部值，不对外返回。
- **接受** `cash_gap = 我们的值 − 券商的值`。正数表示我们算多了。

## R5 行数、errors.csv、data_as_of（T-B46 第 7 项）
- 上传阶段的行数可以是近似值，以解析完成后的 `stats` 为准。
- **errors.csv 包含 warning 行**。契约列中有 `severity`，前端和用户可以按它筛选。
- **接受** `data_as_of` 取稳定值，ETag 基于它计算。

## R6 /portfolio 响应（T-B46 第 1、6、9 项）
契约 #27 ⑥ 已写入 §7.2 `/portfolio` 行。
- ① **驳回** `instrument_kind`，改为 `security_type: security_type | null`。null 表示不在主数据中。**驳回**顶层 `estimated`，只保留持仓行上的 `estimated`。
- ② 现价按以下顺序取：
  1. 该证券最近一个交易日的日线收盘价（只读库内已有数据，不触发拉取）；
  2. 没有日线时，用最近一次持仓快照中的参考价；
  3. 两者都没有时，按成本估算，`estimated=true`，`market_value`、`pnl`、`pnl_pct` 为 null（问题 79）。
- **接受**代码格式转换（`SH600001` → `600001.SH`）。**接受** price 存储用不限精度的 numeric，但输入按契约 pattern 最多 4 位小数。
- ③ `cash`、`total_assets`、`qty`、`sellable_qty`、`cost_price`、`weight_pct` 不为 null。没有现金记录时 `cash="0.00"`，并在 `gaps` 中列 `{key:"cash", reason:"user_input_missing"}`。
- ④ 行业数据未接入时，`exposure.sector=[]`，`gaps` 中列 `exposure.sector`，但这一项**不单独**把 `data_status` 降为 `partial`。其他缺口照 1.1 节取最差状态。
- 手工成交的费用记入 other_fee，`net_amount` 保持 null。**接受**不存 original_filename（数据最小化）。

## R7 对账种类与夹具不一致（T-B46 第 8 项）
- **实现正确**：契约要求汇总中的 `cash_chain_break` 与逐行的 `IMPORT_CASH_CHAIN_BREAK` 同时出现。replay 把超卖截到 0，这也符合规则。
- 改夹具，不改后端：测试员把 `scenario_with_trades` 的期望改为 `{cash_chain_break, cash_gap}`。
- gb18030 夹具中同一代码对应两个名称的问题，也由测试员修夹具。

## R8 周期评估的存储（T-B47：horizon 落库）
契约 #27 ⑧ 与 `/horizon-assessments` 接口行；plan 2.5.3、3.3。
- GET 时先读本人、该证券、当前 `classifier_version` 的最新一条 `symbol_horizon_assessments`。以下两种情况同步计算一次并落库（新增 `trigger=on_demand`），再返回：
  - 没有这样的记录；
  - 记录输入快照的 `data_as_of` 早于库中该证券最新日线的日期。
- `snapshot_id` 必须是真实的 `data_snapshots.id`：
  - `purpose` 新增 `horizon`；
  - `user_id` 必填，因为输入含画像和 `user.*`；
  - 用到证书数据时带 `licence_id`。
  - 同一输入返回同一条记录。
- `security_code` 加 pattern。格式合法但推断不出市场或不在主数据中 → `404 NOT_FOUND`。
- 表结构：
  - `user_id` NOT NULL；
  - `snapshot_id` NOT NULL，FK 到 `data_snapshots`；
  - 索引 `(user_id, security_code, classifier_version_id, created_at desc)`。
- 保留期（问题 75，默认）：每个（用户、证券、分类器版本）的最新一条长期保留，其余超过 180 天的物理删除，只被它们引用的快照一起删除。删除用户时全部删除。

## R9 分类器输入：平均持有天数、退市风险、f.* 特征库（T-B47）
- **`user.avg_holding_days`**（问题 76，默认）的口径：
  - 范围：本人全部账户最近 365 个自然日内已平仓的买入批次。
  - 配对：FIFO 配对卖出。
  - 计算：持有交易日数按成交数量加权平均，取整。同日买卖算 0 天，作废成交不计。
  - 已平仓批次少于 3 个时为 null，按未填写处理，不封顶、不提示。
- **退市风险**（问题 77，默认）：`f.is_st` = `risk_flag ∈ {st, star_st, delisting}`，宁可少推荐。`f.is_delisting_period` 只看 `listing_status = delisting_period`。c9e 的实现已经符合。
- **f.* 特征库**：
  - 新增 **T-B30a**（后端，依赖 T-B35、T-B07、T-R11）：产出 `horizon_classifier.yaml` 列出的 15 个 `f.*`，写入 `feature_catalog` 与 `feature_bars_daily`；与 T-B43 重叠的键只实现一次。
  - 新增 **T-R11**（研究员，依赖 T-B35）：在 `docs/strategies/horizon_classifier.md` 附录写明这 15 个键的口径和 3 组手算样例。
  - **T-B30 以 T-B30a 完成为验收前提**。在 T-B30a 之前，所有证券都因 `data_missing` 封顶，这是预期行为。前端应显示“数据不足”，而不是“都不适合”。

## R10 /admin/ingest/status 口径与告警（T-B47）
契约 #27 ⑨ 与 §7.9；plan 6.1 `config/realtime.yaml` 新增 `admin_alerts`。
- `leader`：只认未过期的租约，没有时整个字段为 `null`。
- `budget`：
  - `per_minute_limit` 是全部 `active` 证书每分钟上限之和，不受 `licences[]` 500 行截断影响；
  - `used_last_minute` 是最近 60 秒全部证书的请求数。
- `queues`：深度对全部证书聚合。`oldest_age_s` 按队列中最早一条计算，不限回看时间，空队列为 0。
- `freshness` 固定 6 行：`quotes`、`minute_bars`、`daily_bars`、`financials`、`announcements`、`security_master`。stale 阈值：
  - `quotes` 盘中超过 `stale_threshold_s`（30 秒）；
  - `minute_bars` 超过 180 秒；
  - `daily_bars` 交易日 17:00 后仍不是当日；
  - `announcements` 交易日 20:00 后仍不是当日；
  - `security_master` 超过 1 个交易日；
  - `financials` 超过 120 天。
- 新增 `alerts[]`，永不为 null。告警口径（问题 78，初值，T003 实测后复核）：
  - 没有 leader 或心跳 stale → critical；
  - P0 队列等待超过 60 秒 → warning，超过 300 秒 → critical；
  - P1 队列超过 3600 秒 → warning；
  - 预算用到 90% 及以上 → warning；
  - 24 小时内有 1 次 IP 超限 → critical；
  - 单个上游错误码 24 小时达到 20 次 → warning；
  - quotes stale 或 unavailable → critical，其他数据集 stale → warning；
  - 有 invalid 或 ip_limited 证书 → critical，有 expired 或 quota_exceeded 证书、或剩余天数 ≤14 → warning。
- `message` 为固定中文文案，不含证书值、IP 全文或理由。

## R11 带登录态 schemathesis 的 12 个 ST202（T-B47），以及 OpenAPI 收紧
处理原则：schema 能表达的约束一律收紧 schema（后端改）。schema 无法表达的业务校验，由测试员在 schemathesis 配置中加有限例外，例外必须写明错误码，不得按端点整体放行。

| # | 端点 | 现象 | 裁定 | 谁做 |
|---|---|---|---|---|
| 1 | GET /accounts | `cursor` 任意串 → 400 INVALID_CURSOR | 游标不透明，schema 无法表达有效性（契约 §1.2 新增条目） | 测试员：`cursor` 参数的 `400 INVALID_CURSOR` 加例外 |
| 2 | GET /horizon-assessments | 15 位数字代码 → 400 | 加契约 pattern；格式合法但不在主数据中 → 404 | 后端 |
| 3 | GET /imports | 同 1 | 同 1 | 测试员 |
| 4 | GET /imports/{id}/rows | 同 1 | 同 1 | 测试员 |
| 5 | GET /trades | 同 1 | 同 1 | 测试员 |
| 6 | PATCH /me/data-licence | `tier`、`has_quant_pro` 传 null 被拒 | 收紧 schema：两者可省略但不可为 null，OpenAPI 不标 nullable；`expires_on` 可为 null | 后端 |
| 7 | POST /imports | multipart 中 `snapshot_as_of` 为空串 → 400 | 后端放宽：空串按 null 处理 | 后端 |
| 8 | POST /imports | 内容不是支持的表格 → 422 IMPORT_UNSUPPORTED_FILE_TYPE | 保留 422，文件类型 schema 无法表达 | 测试员：加例外（仅限该错误码） |
| 9 | POST /trades | `qty`、`price` 空串或非数字 → 400 | decimal 字段加 pattern，只接受字符串；`security_code` 加 pattern；格式合法但推断不出市场仍为 400，这一条由测试员加例外 | 后端（pattern）＋测试员（未知市场例外） |
| 10 | PUT /imports/{id}/options | `encoding_override` 任意串 → 400 | 改为内联取值；解析器与批次 kind 不符（kind_mismatch）schema 无法表达，加例外 | 后端（enum）＋测试员（kind_mismatch 例外） |
| 11 | PUT /me/data-licence | `licence` 长度 → 400 | OpenAPI 写明 `minLength 16`、`maxLength 64`、pattern `^[A-Za-z0-9-]{16,64}$` | 后端 |
| 12 | PUT /me/profile | `max_single_position_pct` 越界 → 400 | 加 pattern（5–50，最多 2 位小数，只接受字符串） | 后端 |

同时写入契约：`POST /accounts` 字段 1–32；`/trades`、`/imports` 的 `?account_id=` 不是本人账户时 → 404（与 `/portfolio` 一致）。

---

## 产品问题（默认执行，用户可改）
- 75：周期评估保留期，最新一条长期保留，其余 180 天后删除。
- 76：平均持有天数的口径，365 天、FIFO、按数量加权，少于 3 笔视为未知。
- 77：退市风险警示按 ST 处理。
- 78：采集告警阈值，补测后复核。
- 79：非可转债持仓缺现价时按成本估算并标“估算”。

## 各角色待办
- **后端**：
  - T-B46-x：R6、R3、R11 中的后端项；
  - T-B47-x：R8、R10；
  - T-B30a；
  - 追加裁定 A–E 中的后端项。
- **测试员**：
  - 按 R11 配置 schemathesis 例外；
  - 去掉 CSRF 与 register-closed 的 xfail；
  - 按 R6 改 /portfolio 断言；
  - 按 R7 修夹具；
  - 补 R8、R10 的用例；
  - T-T16 中补 data_snapshots 写入方用例（D）；
  - 补注册接口先返回 413 的用例（E）。
- **前端**：
  - 持仓显示改用 `security_type`，null 显示“不在主数据·估算”；
  - 采集状态页显示 `alerts[]`；
  - 写请求带 CSRF Cookie 与请求头；
  - 周期评估显示“数据不足”。
- **研究员**：T-R11。
- **运维**：
  - C：`grants.sql`、`verify-roles.sh`、`aia_maint` 连接串文件；
  - 交割单加密密钥轮换方案（评审 bbf58a0 m8）。

---

# 追加裁定 A–E（评审 be607b3 / f72b8c7 / 8fd9502）
在同一文档提交 `4532478` 中。契约变更表 #28 标注“v0.2.9 内，评审 be607b3/f72b8c7/8fd9502 裁定”；plan 7.3、3.3。

## A 证书冷却记录的保留期
- `DELETE /me/data-licence` 时保留的指纹与删除前的 `status`、`paused_until`：
  - 有 `paused_until` 的，保留到 `paused_until`；
  - `paused_until` 为 null 的（删除时没有处于冷却），**最多保留到删除后 24 小时**；
  - 两者以先到者为准；契约规定了更短期限的，以更短者为准。
- 每小时一次的周期任务物理删除过期记录。读取时过期记录一律视为不存在。删除用户时一并删除。
- 做什么：后端加清理任务和读取时的过期判断；测试员补 24 小时边界用例。

## B 删除用户时审计记录的清洗粒度（回应 8fd9502“过度清洗”）
- 数组值或复数键（`user_ids`、`licence_ids`、`target_ids`、`affected_users` 等）：只移除被删用户的 id 和该用户证书的 id，保留其他用户的 id。移除后为空的，保留空数组。
- 单值键（`user_id`、`target_user_id`、`licence_id`、`username` 等）：指向被删用户或其证书的，删除该键；指向其他用户的保留。
- 自由文本（`reason`、`note`、`comment` 等）：整体删除，不做部分替换。
- 嵌套 JSON 递归处理。
- 做什么：后端在删除用户数据 CLI 中实现，单元测试覆盖三类键。与 plan 7.3 原有条目冲突时，以这一条为准。

## C `aia_maint` 维护角色
- 它是 LOGIN 角色，按最小权限只授 CLI 用到的表与列。它与 `aia_api`、`aia_ingest` 互不为成员。
- CLI 只从 `AIA_MAINT_DATABASE_URL_FILE` 指向的文件读连接串。这个文件不在镜像和仓库中，`api`、`ingest` 容器不挂载。
- `grants.sql` 中，在 schema 级 GRANT 与 `ALTER DEFAULT PRIVILEGES` **之后**，显式执行 `REVOKE ALL ON ops.pending_file_purges FROM aia_api, aia_ingest`。
- `verify-roles.sh` 增加以下断言：
  - `aia_maint` 可以登录；
  - `aia_api`、`aia_ingest` 不是 `aia_maint` 的成员；
  - `aia_api`、`aia_ingest` 对 `ops.pending_file_purges` 的 SELECT/INSERT/UPDATE/DELETE 都为 false。
- dry-run 也用 `aia_maint` 连接，或用一个只读连接，不得用 `aia_api` 的连接。
- 做什么：运维改 `deploy/db/roles/`；后端改 CLI 的连接读取。

## D `data_snapshots` 写入方验收
- 每个写入方（候选、计划、提醒、复盘、筛选、周期评估，以及以后新增的）上线前都要有一条验收用例：
  - 快照含个人内容或由其派生的内容时，必须写 `user_id`；
  - 用到某用户证书取到的数据时，还必须写 `licence_id`；
  - 任一条不满足即拒写。
- 两层保障：应用层断言，加上表 CHECK（`purpose IN ('plan','horizon')` 时 `user_id IS NOT NULL`）。
- 做什么：后端在写入函数中加断言，迁移中加 CHECK；测试员在 T-T16 中按写入方逐个覆盖。

## E 注册接口先判断 413，再判断 503
- 请求体超过全局上限时，由中间件在路由之前返回 `413 PAYLOAD_TOO_LARGE`。即使 `registration_mode=closed`，也先于 `503 REGISTRATION_CLOSED`。契约 #16 的“一律先返回 503”只适用于没有超过上限的请求。
- 契约错误码表的 413 行与注册行已写明。
- 做什么：后端确认 `common/middleware.py` 的请求体上限中间件对 `/auth/register` 生效。现有实现很可能已经满足，只需补测试；测试员补用例：closed 模式下发送超大请求体，期望 413。
