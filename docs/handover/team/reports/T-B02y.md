# T-B02y 后端同步契约 v0.2.7（架构师 fa6d55d；Q3 编排者裁定 35517f8）

提交：**492898b**（本地，未 push；pathspec 提交，11 个文件，只在 src/backend/ 与 config/）。不调用麦蕊，探针与 STOP 未动（sha256 02339d1e…fbe17 已核对）。隔离库 be-b03a-pg（55499）/ be-b03a-redis（56499）。

## 做了什么
| 项 | 内容 |
|---|---|
| 枚举 / 版本（T-A08 #14、#36） | `CONTRACT_VERSION="v0.2.7"`；18 个新枚举全部注册到 `/meta/enums`（共 77 个）；`data_provider` 加 `exchange`；`security_type` = `stock cdr index etf`（**etf 按 Q3 裁定加入**）；`STRATEGY_ELIGIBLE_SECURITY_TYPES = {stock, cdr}` |
| 配置 | 新增 `config/securities.yaml`（plan §6.1 原样：similarity_threshold 0.3、initials_max_variants 16、limit 20/50、公告外链白名单 7 个主机）+ 校验模型；业务配置文件 8 → 9 个（`config/` 顶层文件集合是强校验，**部署必须带上该文件**） |
| 迁移 0009 | `strategy_instances`：+horizon、paused_by、pause_reason_code、paused_until、updated_at、archived_at；origin 加 `system`；CHECK：非 paused 时暂停字段全 null、paused 必须有 paused_by、用户暂停不带 reason/until、`archived ⇔ archived_at`；索引 `(user_id, status, created_at desc, id desc)`。`market.securities`：+type（CHECK 含 etf）、list_date_basis、delist_date、risk_flag、name_norm、name_initials、master_source、master_as_of；`status`→`listing_status`（CHECK）；删 `industry_codes`；`pg_trgm` + gin 索引；新表 `security_name_history`、`security_code_history`、`security_risk_flag_history`。表里已有行时迁移主动报错（无法推断 type，不把 ETF 猜成股票）。downgrade 可用（已往返验证），`alembic check` 无差异 |
| **ETF 不运行策略** | 应用层 `app/strategy/eligibility.py`：`is_strategy_eligible`（etf/index/未知/None → False，失败即关闭）、`ensure_strategy_eligible`（→ 400 VALIDATION_ERROR，fields `[{field: security_code, issue: not_strategy_eligible}]`）、`split_strategy_universe`（选股池剔除 ETF/指数/未知）。DB 兜底：触发器 `app.reject_non_strategy_security()` 挂在 `strategy_instances`（INSERT / UPDATE OF security_code，security_code 非空时）和 `candidate_signals`（INSERT），只放行 stock/cdr。持仓/交割单不受限（ETF 可进持仓） |
| §6.0A 状态机（纯函数） | `app/strategy/instances/state.py`：confirm/pause/resume/archive、幂等空操作（不写事件、不改 updated_at）、`409 INVALID_STATE_TRANSITION{from,to,allowed}`、origin=system 不能用户归档、`STRATEGY_VERSION_NOT_RUNNABLE{lifecycle}`（可运行 = published/observing）、resume 系统暂停记 `released_reason_code`、系统暂停/到期恢复（不自动恢复用户暂停）、archived PATCH → IMMUTABLE_RESOURCE |
| §6.2 周 K（纯函数） | `app/marketdata/weekly.py`：自然周（周一–周日，北京时间）、t=最后有成交日、open/close/high/low/sum、pre_close 规则、sf=1 占位行不参与、整周停牌不出 bar、is_final=本周最后交易日（按日历）15:00 北京时间后已收盘且该日日线已入库 |

## 没做 / 归属（按 T-A08 §4）
<redacted:sensitive-value-or-command>
- `/imports`、`/trades`、`/portfolio` **不在 T-A08 范围内**，未实现（T-B02x 的纯函数已在 `app/domain/trades.py`，留给对应任务）。
- `market.securities` 保留文本 `code` 为主键，**没有**引入 uuid `security_id`：全部 app 表用文本 `security_code`，没有外键指向它；如架构师坚持加 uuid，需单独迁移。
- 行业（按证书）的新表由 T-B06 建；本迁移只把 `industry_codes` 从公开主数据表移出。
- `strategy_instances.horizon` 可空（旧行无值），由 T-B32 写入时必填。

## 自检
- `/tmp/tb02/selftest_tb02y.py` **78/78 PASS**：枚举/版本/配置；资格判定与选股池过滤；状态机全部转换、幂等、409 细节、系统暂停；周 K 口径（停牌、部分停牌、周日、北京时间收盘、日历缺失）；DB：迁移字段/索引/历史表/pg_trgm、ETF/指数/未知代码写实例被拒、改成 ETF 被拒、ETF 候选信号被拒、股票通过、6 种非法暂停/归档组合被 CHECK 拒绝；`alembic check` 一致。DB 测试在单事务内整体回滚。
- 其他自检：tb03c 57、tb45 67、api 205、tb16 123、xff 21、tb03a 38、t006e、env、tb04ax 114、tb02x 61 全过（api/tb16 自检已把版本改为 v0.2.7、业务文件 9 个）。
- ruff / mypy（73 文件）通过。
- 测试员套件（wt-tests-T-T01，已含 v0.2.7 用例）：**1 failed, 537 passed, 240 skipped, 1 xfailed**。唯一失败 `test_v027_meta_enums_has_new_enums`：测试按契约 §3 现行行写死 `security_type == [stock, cdr, index]`，后端按 Q3 裁定多了 `etf`。

## 需要谁做什么
- **架构师（T-A09）**：契约 §3 `security_type` 行加 `etf`（Q3 已定），并同步各接口说明；确认 `security_id` 不引入（或另开任务）。
- **测试员**：T-A09 落地后把 `V027_ENUMS["security_type"]` 改为含 `etf`；朴素 §3 解析器会把说明里的反引号词当取值（`data_provider` 多出 `provider`、`listing_status` 多出 `SecurityProfile.suspended`），属测试侧伪影。
- **运维**：部署时带上 `config/securities.yaml`（缺了进程起不来），执行迁移 0009（需要 `CREATE EXTENSION pg_trgm` 权限；`market.securities` 必须为空）。
- **T-B06/T-B07/T-B13/T-B20/T-B32**：端点实现时调用 `ensure_strategy_eligible` / `split_strategy_universe`、`apply_user_op`、`aggregate_weekly`。

---

## 追加：改为对齐契约 v0.2.8（T-A09，docs 6ef79c4）— commit **457a211**（另有 licence_id / 按证书 ingest 状态并入 T-B03d 的 **116cb7e**）
按 6:56 指令把同步目标从 v0.2.7 改为 v0.2.8；顺序不变（同步 → T-B03d → T-B16-core）。

| v0.2.8 条目 | 落地 |
|---|---|
| `/meta/enums` version | `CONTRACT_VERSION = "v0.2.8"`（`app/schemas/enums.py`、`app/api/v1/meta.py`） |
| #3 `security_type` | 顺序改为 `stock cdr etf index`（契约 §3 第 374 行） |
| #7 `gap_reason` | 加 `not_applicable` |
| #10 ETF 建实例 | `ensure_strategy_eligible(code, type, scope=)` → **422 `INSTANCE_SCOPE_INVALID`** `{scope, security_code, security_type:"etf", issue:"security_type_not_supported"}`（替换 v0.2.7 版的 400）；未知代码 `{scope, security_code, issue:"unknown_security"}`；指数同样 422 |
| #4–#9 ETF 搜索/资料/个股数据/行情 | 新文件 `app/marketdata/security_types.py`：默认搜索类型 `stock,cdr,etf`、类型排序 stock>cdr>etf>index、ETF 资料置 null 的字段、四个个股数据集对 ETF 返回缺口 `not_applicable`（fund-flows 的 key 为 `fund_flows`）、指数仍 `no_source`、价格小数位（ETF 3 / 股票 2）、ETF 整手 100 份。仓库里还没有搜索/资料/数据端点和 H-01 挂载代码，端点由 T-B06/T-B07/T-B13/T-B32 实现时直接调用 |
| #1 按证书 ingest 状态 | `app/licences/service.py::ingest_licences(conn, rds, settings) -> (licences, truncated)`：IngestLicenceStatus 全部键；不列 not_set；最多 500 行 + `licences_truncated`；按 invalid, ip_limited, quota_exceeded, expired, paused_by_admin, pending_verification, active → days_left 升序（null 最后）→ username 排序；`daily_limit` 只有钻石版过期后为 `diamond_after_expiry_per_day`。**`/admin/ingest/status` 端点本身未实现**：leader/budget/queues/errors/freshness 依赖 ingest 基础设施，归 ingest 任务（T-B04x），它直接调用 `ingest_licences()` |
| #2 AdminDataLicence.licence_id | 管理端列表加 `licence_id`（未设置为 null），与 ingest 行一致（自检对比） |
| Q63 可转债展示 | **未决，未实现**（只在 `security_types.py` 文档里记为待定） |

- **config/securities.yaml**：已在 492898b 纳入版本控制（`git ls-files` 可见，工作区无改动）。它是按 plan §6.1 手写的后端配置，由 `app/config_files.py` 读取，**不是**导入器生成（与 `config/strategies/` 不同），无需额外处理。
- 自检：`selftest_tb02y.py` **86/86**（新增 422 细节、unknown/index、搜索默认与排序、not_applicable 缺口与 key、指数 no_source、价格小数位/整手、ETF null 字段；alembic head ≥ 0009）；按证书 ingest 状态与 licence_id 的检查在 `selftest_tb03d.py`（见 T-B03d.md）。其他自检全过。ruff / mypy（74 文件）/ `alembic check` 通过。
- 测试员套件：**5 failed, 531 passed, 240 skipped, 3 xfailed**，失败全在 `test_meta_enums.py`，都是测试侧版本白名单/期望没跟到 v0.2.8：`'v0.2.8' in {'v0.2.5','v0.2.6','v0.2.7'}`、`== 'v0.2.7'`，以及 `security_type` 期望 `[stock, cdr, index]`（后端与契约 §3 一致：`stock cdr etf index`）。

### 需要谁做什么（v0.2.8 部分）
- **测试员**：`test_meta_enums.py` 的版本白名单加 `v0.2.8`、期望版本改为 v0.2.8、`security_type` 改为 `[stock, cdr, etf, index]`；补 v0.2.8 用例（422 ETF 实例、not_applicable、licence_id、蜜罐、暂停按用户）。
- **ingest 任务（T-B04x）**：实现 `/admin/ingest/status`，`licences[]` / `licences_truncated` 直接用 `ingest_licences()`。
- **T-B06/T-B07/T-B13/T-B32**：用 `security_types.py` 的辅助函数实现 ETF 的搜索/资料/缺口/精度；实例创建调用 `ensure_strategy_eligible(..., scope=...)`。
- **编排者/架构师**：Q63 可转债展示规则待定。

## 评审修复（review-T-B02y.md，2026-11-02 约 07:20 北京时间）— 提交 c55a42e（新提交，未 amend）

**前置核对（只读）**：0009 未推送（`git branch -r --contains 492898b` 为空），也未在任何共享库执行过：
`aia-t01-postgres-1` 的 `aia` 库 alembic_version = **0008**；测试临时容器 `busy_swirles` 的 `tt01d_auth_*` 库也是 0008。
所以按要求**原地修改 0009**，没有另写纠正迁移。（隔离库 be-b03a-pg 曾执行过旧 0009，只是本地自测库。）

- **M1 已修**：`0009` 在加 `ck_strategy_instances_pause_fields` / `ck_strategy_instances_archived_at` 之前回填：
  - `status='paused'` → `paused_by='user'`（0008 没有系统暂停）；`pause_reason_code`/`paused_until` 保持 NULL。
  - `status='archived'` → `archived_at` = 该实例最近一次 `kind='archived'` 的 `strategy_instance_events.at`（只追加表，最可信）；没有事件时退回 `confirmed_at`，再退回 `created_at`。不用 `updated_at`：它是 0009 新加的列，旧行值是迁移时刻 now()。
- **security_type 顺序**：schemas / `/meta/enums` 在 457a211 已是 `stock cdr etf index`；本提交把 0009 里 `ck_securities_type` 的取值顺序也改成同一顺序（CHECK 语义不受顺序影响，只为一致）。
- **m4**：0009 docstring 写明降级丢失项（origin=system→user、暂停原因/到期、archived_at、horizon、证券 type、三张历史表），再升级按回填规则重建。
- **测试** `/tmp/tb02/selftest_m1_0009.py`（隔离容器内新建临时库 `aia_m1_0009`，测完删除）：upgrade 0008 → 插入 1 个 paused、3 个 archived（有事件 / 只有 confirmed_at / 只有 created_at）、1 个 active → upgrade head → 校验回填 → alembic check → downgrade 0008（5 行仍在）→ upgrade head → 再次校验 → `ck_securities_type` 顺序。**17/17 通过**。
- 其余评审项：M2 是 CI 解析器问题（已由 307132b 文档改括号处理，非后端）；m1/m3（周 K 边界、存量一致性扫描）归 T-B06；m2 锁目前表小可接受；m5 pg_trgm 说明已更正：迁移角色有 CREATE 权限即可；m6 测试侧；m7 运维 grants。
- 上轮安全回退 M1/M2/M5：已在 T-B03d **116cb7e** 修复（见 reports/T-B03d.md），不在本提交。

**谁需要做什么**：运维——部署前 0009 不再需要“无 paused/archived”的预检，`market.securities` 为空的预检仍需要；测试——可加“0008 带 paused/archived 数据升级”的迁移用例（参照上面的 selftest）。
