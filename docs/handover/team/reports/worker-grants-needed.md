# worker 任务需要的数据库权限（aia_api）

依据：契约 v0.2.9 #41 / plan 7.3 第 8 条（docs 96ea475，review-028c077 M1）。worker 改用 `aia_api` 连接后，下表列出**每个 worker 任务实际执行的表与操作**。只需 DML，不要任何 DDL。
维护人：后端。每有一个 worker 任务落地就更新本文件；运维据此修改 `deploy/db/roles/grants.sql` 和 `verify-roles.sh`。

- 列出的是代码里真实的语句。`FOR UPDATE` 需要该表的 UPDATE 权限（PostgreSQL 规定）。
- `aia_api` 仍然不能读证书密文列，下面没有任何一项涉及 `app.user_data_licences` 的密文列。

## 已上线任务

| 任务（beat 调度名） | 代码 | 表 | 操作 | 备注 |
|---|---|---|---|---|
| `licences.purge_expired_cooldowns` | `app.licences.service.purge_expired_cooldowns` | `app.user_data_licence_cooldowns` | SELECT, DELETE | `DELETE … WHERE <到期条件>`（WHERE 里读列，所以需要 SELECT） |
| `imports.purge_preview_rows` | `app.importing.pipeline.purge_uncommitted_import_rows` | `app.import_rows` | SELECT, DELETE | `DELETE … WHERE batch_id IN (子查询)` |
| | | `app.import_batches` | SELECT | 子查询 `status IN ('discarded','failed')` |
| `imports.purge_expired_raw_files` | `app.importing.pipeline.purge_expired_raw_files` | `app.import_files` | SELECT, UPDATE（`deleted_at`, `storage_path`；`FOR UPDATE SKIP LOCKED` 也要求 UPDATE） | 另外需要挂载与 api 相同的 `IMPORT_STORAGE_PATH` 卷。根目录不存在时报错、行保留（#41 ②），不会误标为已删除 |

## T-B52 主数据同步与首次导入（已落地，按代码实际语句定稿）

`master.sync_exchange_lists`、`master.sync_bse_code_map`、`master.purge_snapshots` 由 worker 执行，`python -m app.cli.master_bootstrap` 由运维在部署时执行。两者都用 `aia_api`，都**不会**调用 `master.reconcile_vendor`（首次导入有自检：AST + 运行后队列为空）。代码：`app/master/sync.py`。

| 表 | 操作 | 用途（实际语句） |
|---|---|---|
| `market.securities` | SELECT, INSERT, UPDATE | 建档；改名 / 状态 / 风险警示 / `last_seen_on` / `missing_since` / `field_sources` 的 UPDATE |
| `market.security_name_history` | SELECT, INSERT, UPDATE, DELETE | 关闭旧区间、同日就地改、新开区间；深市按 SSGSGMXX 重建某个代码时 `DELETE … WHERE code=` 后整体重插 |
| `market.security_risk_flag_history` | SELECT, INSERT, UPDATE, DELETE | 同上（重建时与简称历史一起删后插） |
| `market.security_listing_status_history` | SELECT, INSERT, UPDATE | 关闭旧区间、同日就地改、新开区间 |
| `market.security_code_history` | SELECT, INSERT, DELETE | 北交所新旧代码对照；对照关系变化时 `DELETE … WHERE old_code=` 后重插（没有 UPDATE） |
| `market.master_snapshots` | SELECT, INSERT, UPDATE（`fetched_at`, `trade_date`, `row_count`, `parse_status`, `reject_reason`, `raw_path`） | 记录快照；相同 sha 复用旧行时更新这几列；`purge_snapshots` 把超过 90 天的 `raw_path` 置空 |
| `market.master_runs` | SELECT, INSERT, UPDATE | 运行记录（开始时 INSERT，结束时 UPDATE `finished_at` / `status` / `snapshot_ids` / `stats`）；07:30 补拉读当日各运行的 `stats` |

- 卷：worker 与执行首次导入的容器都要挂载同一个 `MASTER_SNAPSHOT_PATH`（原始快照，文件 0640）。生产环境未设置时任务在连库之前就报错（不写库）。
- 序列：`master_snapshots.id`、`master_runs.id` 是 identity 列，有 INSERT 权限就能取号，**不需要**单独授予序列 USAGE。下面的 `security_search_terms` 和 `security_reconciliation_diffs` 也一样。
- **T-B54 将追加：** `market.security_search_terms`：SELECT, INSERT, DELETE（同一事务内整体重建词条）。
- **T-B53 将追加：** `master.reconcile_vendor` / `master.crosscheck` 对 `market.security_reconciliation_diffs` 的 SELECT、INSERT、UPDATE。

## 不在本表内

- `beat` 只连 Redis，不连数据库。`signal-rt` 由运维另行核实（plan 7.3 第 8 条 ⑥）。
- 用户数据删除 CLI 用 `aia_maint`（迁移 0013），不经过 worker。

## T-B61：批次交接、比对及兜底（本地交付，运维部署前补授权并验证）
- 更正上文T-B52时期“都不会调用”的历史判断：注册后worker的SYNC_LISTS成功（含管理员手动触发）链式触发reconcile_vendor；CLI bootstrap仍不触发。
- `master.reconcile_vendor`（含10分钟批次重试）：aia_api 对 market.master_runs SELECT/UPDATE(stats，FOR UPDATE)，market.master_vendor_batches SELECT/INSERT/UPDATE(status,error_code，已请求批次过期或作用域不可用时)；app.user_data_licence_status、app.user_data_licence_holds SELECT；不选密文/HMAC。
- `master.reconcile_vendor_apply`：aia_api 对 market.master_vendor_batches SELECT/UPDATE(status,reconciled_at，FOR UPDATE)，market.master_vendor_list_rows SELECT，market.securities SELECT，market.security_reconciliation_diffs SELECT/INSERT/UPDATE；pg_advisory_xact_lock，不需DDL或属主。
- `master.vendor_batches_sweep`（beat每900秒投递，worker执行）：aia_api 对 market.master_vendor_batches SELECT/UPDATE(status,error_code)；过期requested置expired，fetched超过30分钟重新排apply。
- `master.purge_snapshots` 新增：aia_api 对 market.master_vendor_list_rows SELECT/DELETE，market.master_vendor_batches SELECT(requested_at,id)；只删14天前规范化行，批次元数据不删。已有主数据任务权限保留。
- ingest规范化结果交接：aia_ingest 对 market.master_vendor_batches SELECT、仅UPDATE(status,fetched_at,datasets,error_code)；对 market.master_vendor_list_rows 仅INSERT；状态视图及holds仅SELECT。不得UPDATE归属/期限/attempt，不得DELETE规范行或更改reconciled。
- 管理端读取：aia_api SELECT market.security_reconciliation_diffs、market.master_snapshots、market.master_runs、market.securities、状态视图与app.users；仍不得SELECT证书密文/HMAC，无新告警表。
- 新表主键UUID，无新增identity序列。迁移0020由既有迁移角色执行；不向worker/ingest授予DDL、属主、SET ROLE到属主或密文列权限。
- 运维据此更新grants.sql/verify-roles.sh；隔离真角色已验证worker/API为aia_api、交接为aia_ingest，拒绝密文SELECT、worker DDL、ingest改归属/删行；不代替部署角色验收。
