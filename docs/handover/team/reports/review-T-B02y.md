# 评审报告：T-B02y（492898b，契约 v0.2.7 同步 + 迁移 0009），附带 a6c1437

- 评审人：架构师（代审）　日期：2026-11-02（北京时间）
- 依据：契约 v0.2.7（fa6d55d + Q3 裁定 35517f8），自述 `reports/T-B02y.md`、`reports/T-A08.md` §4（端点归属）。HEAD 上的 v0.2.8（6ef79c4）新增内容只记作“待对齐 v0.2.8”，不算缺陷。
- 只读代码，没有改代码、没有提交、没有推送。行号以 **a6c1437 的 `git archive` 导出**为准（a6c1437 是 492898b 的直接子提交，只改 `scripts/ci/nginx_limits_smoke.sh`）。

## 结论

| 提交 | 结论 | 说明 |
|---|---|---|
| 492898b（T-B02y） | **有条件通过** | 条件：修 M1（0009 补回填），或者先由运维确认所有要升级的库里没有 `paused`/`archived` 的实例、`market.securities` 为空。不涉及安全回退。 |
| a6c1437（T-O10） | **通过** | 只改 smoke 脚本：日志先写文件再 grep，全局桶加 5 次重试。不影响后端。 |

**contract 检查不能变绿。** 按 CI 的 contract job 在 a6c1437 上实跑，第 4 步“/meta/enums 与契约一致”报 2 项错误（见 §3）：一项是检查脚本的解析问题（M2，不是后端的问题），一项是 v0.2.7 文档和 Q3 裁定不一致（ETF）。其余各步都通过。
**可以推送**：492898b 没有让任何既有检查变差；这一步在 492898b 之前缺 18 个新枚举，必然更红（这一点是推断，没有回到 ec6c58d 重跑）。推送前请运维先跑 §1 里的预检 SQL，contract 检查要等 M2 和 ETF 文档对齐后才会变绿。

## 0. 检查方式

- 导出：先 `git archive a6c1437` 到 `/tmp/rev-b02y`，再把测试分支 test/T-T01 **已提交**的 37edb2c 的 `tests/` 覆盖进去。后端用 uv：`uv sync --frozen`，没有改 lockfile（npm ci 不适用）。主工作树没有动。
- **迁移用真实 PostgreSQL 测**：临时起了一个容器 `timescale/timescaledb:2.31.0-pg16`（和 CI 同一镜像），只在这个临时库上操作，测完已删除。

| 检查 | 结果 |
|---|---|
| uv sync --frozen | 通过 |
| ruff check . | 通过 |
| mypy（strict，73 个文件） | 通过 |
| pytest（tests/backend + tests/replay，37edb2c） | 4 failed / 733 passed / 92 skipped / 12 xfailed / 20 xpassed。4 个失败都在测试侧，见 m6 |
| check_contract.py（只查文档） | 通过 |
| check_code_namespaces.py（文档 / 后端） | 通过 / 通过（59/22/46/7） |
| dump_meta_enums.py | 通过 |
| **check_contract.py --meta-json** | **失败，2 项**（§3） |
| schemathesis 4.33.0（CI 同参数） | 763/763 通过 |
| alembic：空库 upgrade head → check → downgrade 0008 → upgrade → downgrade base → upgrade | 全部通过；`alembic check` 显示模型和迁移一致 |
| 0008 带数据升级 | **有 paused/archived 实例时失败**（M1）；securities 非空时按设计中止 |

## 1. 迁移 0009（实测）

- **触发器没有放松**：比较了 0008 和 0009 的 `pg_trigger` 全量（98 条）和 app/ops/market 下函数源码的 md5。0009 只**新增**了 `trg_strategy_instances_eligible_security` 和 `trg_candidate_signals_eligible_security`（后者自动下发到 candidate_signals 的全部分区，包括 default），以及函数 `reject_non_strategy_security`。其余触发器和函数一个字节都没变。downgrade 之后和 0008 完全一致。
- 触发器行为实测：ETF（510300）被拒，未知代码被拒，stock（600519）放行，`security_code IS NULL` 放行。函数不是 SECURITY DEFINER，按调用者权限读 `market.securities`。`deploy/db/roles/grants.sql:55,58` 给 aia_api/aia_ingest 授了 SELECT 和默认权限，所以运行时不会因为权限失败。
- `ck_securities_board` 在 0008 里不存在，没有重名。`strategy_instances` 没有不可变触发器，downgrade 里的 `UPDATE … origin='user'`（0009:322）实测能执行。
- 预检 SQL（推送或部署前请运维在目标库上跑，结果应为 0 / 0）：
  `SELECT count(*) FROM app.strategy_instances WHERE status IN ('paused','archived');`
  `SELECT count(*) FROM market.securities;`

## 2. 问题清单

### B 级（阻断）
无。

### M 级

**M1　0009 没有回填，0008 上已有 `paused`/`archived` 实例时升级失败**
- 位置：`migrations/versions/0009_t_b02y_contract_v027.py:122-135`（`ck_strategy_instances_pause_fields`、`ck_strategy_instances_archived_at`）
- 原因：新加的 `paused_by` 和 `archived_at` 都是 NULL，CHECK 却要求 `status='paused'` 时 `paused_by` 非空、`status='archived'` 时 `archived_at` 非空。实测：0008 上插入 paused 行，升级报 `CheckViolation ck_strategy_instances_pause_fields`；插入 archived 行，升级报 `ck_strategy_instances_archived_at`。“降级后带数据再升级”也一样失败。DDL 有事务，失败会整体回滚，不会损坏数据，但部署会卡住。目前代码里没有写实例的路由，实际受影响的概率低，但这条正是本次要求的“能从 0008 的数据上升级”。
- 修复：在加这两个 CHECK 之前回填，例如 `UPDATE app.strategy_instances SET paused_by='user' WHERE status='paused';` 和 `UPDATE app.strategy_instances SET archived_at=coalesce(confirmed_at, created_at) WHERE status='archived';`，并补一条“0008 带 paused/archived 数据升级”的迁移测试。

**M2　contract 检查的 §3 解析器把说明文字里的记号当成枚举值，`listing_status` 永远对不上（不是后端问题）**
- 位置：`scripts/ci/contract_md.py:129-144`（只去掉全角括号里的内容，再取反引号记号）；契约 v0.2.7 §3 第 343 行 `listing_status` 行末的“**停牌不是上市状态**，用 `SecurityProfile.suspended` 表示”。
- 原因：这句说明不在括号里，`SecurityProfile.suspended` 被当成了第 5 个取值。后端 `ListingStatus`（`app/schemas/enums.py:600-604`）是对的。v0.2.8 的文档里这句还在，HEAD 上一样报错。
- 修复（二选一，负责人是架构师或运维）：把这句说明放进全角括号；或者让解析器只取到第一个“。”为止，或排除带“.”的记号。

### m 级

- **m1 周 K `is_final` 的边界**（`app/marketdata/weekly.py:111-125`）：如果本股在该周最后一个交易日停牌、ingest 又没有存 `sf=1` 占位行，`ltd in stored` 永远为假，这一周就永远不会 final。另外，第一根 bar 的 `pre_close` 取当周首日的日线值；分页（`before`）时如果调用方没有多带一周数据，窗口第一根和全量结果会不同。建议 T-B06 调用时多取一周，并且要求 ingest 一定落占位行。`adjust_as_of` 不在本提交范围（T-B06）。
- **m2 锁**：`ix_strategy_instances_user_status_created`（0009:137-142）没有用 CONCURRENTLY，CHECK 也没有用 NOT VALID，执行时会短暂持有 ACCESS EXCLUSIVE 锁。`updated_at DEFAULT now()` 是 STABLE 默认值，不会重写表。现在表很小，可以接受；以后有大表时再改成 CONCURRENTLY 或 NOT VALID + VALIDATE。
- **m3 触发器只在写入时检查**：升级时不校验已有行（实测：引用了 securities 里不存在的代码的旧实例照样升级成功）；以后把某个代码的 type 改成 etf，也不会重新检查已有的实例和信号。建议 T-B06 导入主数据后做一次一致性扫描。
- **m4 降级会丢信息**：`origin=system` 被改成 `user`（0009:322），暂停原因和到期时间、证券 type 以及三张历史表都会丢。作为降级可以接受，但应在迁移的 docstring 里写明。
- **m5 pg_trgm**：迁移自己执行了 `CREATE EXTENSION IF NOT EXISTS pg_trgm`（0009:194）。PG13 起它是受信任扩展，迁移角色对库有 CREATE 权限就够了，所以自述里“运维必须先建扩展”只有在迁移角色没有这个权限时才需要。扩展建在 public 下，降级时不删，这样做合理。
- **m6 测试分支落后**（37edb2c 的 4 个失败都在测试侧）：`test_alembic_head_is_known` 仍期望 0007；`test_register_when_not_open_is_503…[invite]` 和 `test_register_invalid_invite_codes_share_one_response_body` 是 T-B03c（3834925）上线邀请码之后行为变了，之前就已存在；`test_v027_meta_enums_has_new_enums` 期望没有 etf，和 Q3 裁定冲突。自述说“只有 1 个失败”，用已提交的 37edb2c 复现不出来（自述多半用了工作区里未提交的测试）。
- **m7 权限偏宽**（运维 f29d97a，不属于本提交）：按 `grants.sql:55,58`，aia_api 对 market.* 的新表（securities 和三张历史表）有 INSERT/UPDATE/DELETE，而这几张表只该由 ingest 写。建议 market schema 对 aia_api 只授 SELECT。

## 3. v0.2.7 各项状态

| 契约项 | 状态 |
|---|---|
| #1 /strategies risk_level | 枚举已有；**端点未实现**，归 T-B20 |
| #2 StrategyInstance 字段 + #4 §6.0A 状态机 | 库表和 `app/strategy/instances/state.py` 已实现，逐条对照 §6.0A：幂等返回 200 且不写事件；非法返回 409 `{from,to,allowed}`，allowed 按枚举顺序；origin=system 时去掉 archived；系统暂停不会被改写成用户暂停；lifecycle 不可运行时返回 STRATEGY_VERSION_NOT_RUNNABLE；resume 时记 released_reason_code；archived 上 PATCH 返回 IMMUTABLE_RESOURCE。全部符合。**路由未实现**，归 T-B32 |
| #3 GET /strategy-instances | 只有索引；**端点未实现**，归 T-B32 |
| #5–#11 证券类端点、sector-flows | 表、索引、`config/securities.yaml` 已就位（取值和 §7 一致：0.3 / 16 / 20 / 50 / 公告白名单）；**端点未实现**，归 T-B06、T-B07 |
| #12 周 K | 纯函数按 §6.2 实现（自然周、`t`、open/close/high/low/sum、pre_close、整周停牌不出 bar、`is_final`），见 m1；**端点和 `adjust_as_of` 未实现**，归 T-B06 |
| #14 18 个新枚举、data_provider 加 exchange | 已实现，check_contract 逐项比对一致。例外：listing_status 是 M2 的解析问题；security_type 见下 |
| #16 /today 三个新块 | **未实现**，归 T-B13 |
| /meta/enums | version 是 `v0.2.7`，键集合齐全 |
| Q3 ETF | 后端按裁定加了 `etf`，并用 eligibility 和 DB 触发器保证策略不跑 ETF。这样做是对的。但 v0.2.7 的 §3 正文（第 341 行）仍是 `stock cdr index`，所以在 a6c1437 上 check_contract 会报这一项，文档在 v0.2.8 才改 |

**按契约 v0.2.7，这些端点在本提交里都没有实现。** 自述已经写明，T-A08 §4 也把它们分给了各自的任务，不算本提交的缺陷，状态待各任务完成。

## 4. 待对齐 v0.2.8（不算缺陷）
用 HEAD（6c50108）的文档对照本次导出的 /meta/enums，共 5 项，其中和后端有关的 3 项：
- `security_type` 的顺序：v0.2.8 是 `stock cdr etf index`，后端是 `stock cdr index etf`，需要调整。
- `/meta/enums` 的 version 要改成 `v0.2.8`。
- `gap_reason` 要加 `not_applicable`。
另外 2 项和后端无关：listing_status（同 M2），以及文档自身 §4.1 和 plan 3.5A-1 的 `IMPORT_LOT_SIZE_IRREGULAR` 不一致。

## 5. 安全回退（上轮 M1/M2/M5）
492898b 没有改 `app/licences/`、`api/v1/auth.py`、`api/v1/admin.py`。
- 上轮 M1（先 DELETE 再 PUT 可以绕过管理员暂停，service.py:189-200）：**未修复，没有变差**。
- 上轮 M2（重复 PUT 会重置 quota_exceeded/ip_limited）：**未修复，没有变差**。
- 上轮 M5（改密码的限速放在 verify 之后，现在在 auth.py:363-367）：**未修复，没有变差**。
- 上轮 M3（没有列级授权）：运维 f29d97a 已经处理（`grants.sql:38,72-73` 对 aia_api 撤销 `user_data_licences.ciphertext` 的读权限）。这一条只做了静态核对，没有实跑 verify-roles.sh。
