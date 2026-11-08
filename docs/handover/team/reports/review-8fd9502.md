# 评审报告：8fd9502（T-B16-core-r2：返修 45589c2 的 B1/B2/M1–M4，迁移 0013）

- 评审对象：`8fd9502`（父提交 `be607b3`，2026-11-02 07:50 UTC+8，仅本地）
- 依据：原评审 /workspace/team/reports/review-45589c2.md；docs/plan.md §7.3「删除用户数据 CLI 规则」与 §3.3（架构师裁定，提交 8a760d1：专用 aia_maint 角色写 purging、data_snapshots 加 user_id/licence_id、user_id 为空的快照只允许市场级内容）
- 方式：`git archive 8fd9502` 导出到 /tmp/rv3-8fd9502，`uv sync --frozen`；临时容器 timescale pg16（rv3-pg，库 aia 升到 0013）+ redis（rv3-redis）。执行 deploy/db/roles/grants.sql，aia_maint 因 grants.sql 中没有，按 plan §7.3 手工创建（LOGIN、无成员、只有业务表 DML）；分别以真实的 aia_api、aia_ingest、aia_maint 非超级用户连接实测。另在当前 HEAD `7a3e9cb`（含 0014）上复核外键覆盖。测完容器、临时目录、临时口令文件已删除。未改代码、未提交、未推送，未打印任何密钥

## 结论：有条件通过

B1、B2 已修好并实测确认；原 M1–M4 全部修好；原 m1、m2 也已处理。迁移 0013 往返一致、`alembic check` 干净。剩下的是 3 个 m 级问题和**运维前置项**：grants.sql 里还没有 aia_maint、api/ingest 仍能读写 ops.pending_file_purges、verify-roles.sh 没有对应断言。不完成运维前置项，生产上 CLI 的 `--execute` 无法运行（会因非 aia_maint 连接被拒），所以这是上线条件，不是代码缺陷。

## 原问题复核

| 原编号 | 复核结果 | 依据 |
|---|---|---|
| **B1** purging 绕过 | ✔ 已修 | 0013:206–250：BEFORE INSERT/UPDATE 触发器 `guard_users_purging`（禁止以 purging 插入；只有 `current_user='aia_maint'` 能 UPDATE 成 purging；purging 行任何 UPDATE 都拒绝）+ 延迟约束触发器按 `NEW.id` 检查该行提交时已不存在。aia_api/aia_ingest 的全部攻击路径被拒（见测试方法 2） |
| **B2** data_snapshots | ✔ 已修 | 0013:361–400 新增 user_id/licence_id（FK、部分索引），purge_row_owner 放行（0013:92）；CLI 删除 user_id=该用户或 licence_id=其证书的快照（delete_user_data.py:302）；user_id 为空但内容提到该用户的快照 → 阻断（77–85、643–648） |
| **M1** account_reviews.reason | ✔ 已修 | delete_user_data.py:135–136 reason 一律置 NULL；实测 bob 那行 reason/user_id 均为 NULL，carol 的 reason 保留 |
| **M2** 审计 detail 残留 | ✔ 已修（有过度清洗，见 m1） | 0013:106–165 `purge_pii_key`（覆盖复数）、`purge_ref_ids`（用户/证书/画像/账户 id）、`purge_scrub_json`；delete_user_data.py:119–127 |
| **M3** Redis 会话本体 | ✔ 已修 | delete_user_data.py:793 `revoke_sessions` 在事务前执行（失败则中止），798 `purge_redis` 收尾；实测 bob 的会话与限速键删除，carol 的会话保留 |
| **M4** llm_calls 覆盖 | ✔ 已修 | delete_user_data.py:563–602 运行时从 pg_catalog 发现外键、uuid[] 列与 target 引用；独占行删除，共享行清空 body/hash/validation_errors |
| 原 m1 username_tried | ✔ | delete_user_data.py:264 |
| 原 m2 text 引用 | ✔ | delete_user_data.py:154–157（ingest_request_log.requester/dedup_key）、286–289（released_by）等 |
| 原 m3 pending_file_purges 权限 | ✘ 未处理（运维项，见下） | grants.sql 未改 |

## 问题表

| 级别 | 位置 | 问题原因 | 修复建议 | 归属 |
|---|---|---|---|---|
| **运维前置** | deploy/db/roles/grants.sql（全文 91 行，无 aia_maint）；verify-roles.sh | plan §7.3（8a760d1）要求的 aia_maint 角色在 grants.sql / apply-roles.sh 中不存在；CLI `--execute` 要求以 aia_maint 连接（delete_user_data.py:895–930），否则拒绝 | grants.sql 增加 aia_maint：LOGIN、NOINHERIT、非超级用户、不拥有任何对象、无 CREATE；只授 app/ops/market 业务表 DML（与 api 相同即可，触发器只认 current_user）；**aia_api、aia_ingest 不得是其成员**；口令走密钥文件，CLI 通过 `AIA_MAINT_DATABASE_URL_FILE` 读取，api/ingest 容器不挂载这份密钥 | 运维（架构师确认） |
| **运维前置**（原 m3） | grants.sql:55、58（对业务 schema 的 ALL TABLES 与 DEFAULT PRIVILEGES 授权） | 实测执行 grants.sql 后，aia_api、aia_ingest 仍能 SELECT/DELETE ops.pending_file_purges（path 含 uid）。因为第 55 行是整 schema 授权，单独 REVOKE 必须放在这个循环**之后**，否则每次 apply 都被重新授权 | 在 55–59 行循环之后 `REVOKE ALL ON ops.pending_file_purges FROM aia_api, aia_ingest; GRANT SELECT, INSERT, UPDATE, DELETE ON ops.pending_file_purges TO aia_maint;` | 运维 |
| **运维前置** | deploy/db/roles/verify-roles.sh（22 行，无相关断言） | 上述两项没有回归保护 | 增加断言：aia_maint 存在且 rolsuper=f、无成员（`pg_auth_members` 中 roleid=aia_maint 为空）、无 CREATE；`has_table_privilege('aia_api'/'aia_ingest','ops.pending_file_purges','SELECT')` 为 f；aia_api/aia_ingest 不能 `SET ROLE aia_maint` | 运维 |
| m1 | migrations/versions/0013_t_b16_core_r2.py:106–113、144–162 | 过度清洗：被删用户出现在某条审计里时，整条 detail 按 PII 键规则清洗，连带删掉与其他用户有关的内容。实测 `admin.user_disabled` 审计 detail 含 `user_ids: [bob, carol]` 与针对 carol 的 reason，删除 bob 后整个 detail 变成 `{}`，carol 的 user_ids 记录也没了。reason 按 8a760d1 裁定本来就清，但 `user_ids` 数组整体被 `purge_pii_key` 删掉属于误伤 | 对数组型 id 键改为“只删匹配 ids 的元素”，不整键删除；或架构师明确接受“删号时相关审计 detail 允许整体清空” | 后端；架构师（口径） |
| m2 | delete_user_data.py:655（build_plan 读 ops.pending_file_purges） | dry-run 也读 pending_file_purges。运维前置项收回 aia_api 权限后，用 api DSN 跑 dry-run 会报 permission denied。目前 dry-run 用 api DSN 是可以的（实测正常），收权后就不行 | dry-run 同样要求 aia_maint DSN（文档写明），或读 pending 失败时降级为“无权限，跳过” | 后端 |
| m3 | app/db/tables/reviews.py:44–51（data_snapshots.user_id/licence_id）；目前应用代码无写入方 | B2 的正确性依赖未来写入方把含个人派生内容的快照填上 user_id（或 licence_id）。现在只有 CLI 执行前的“user_id 为空但提到该用户”阻断兜底，只能识别 uid/证书 id 等字面量，识别不了持仓比例这类派生值 | 在 plan / 代码注释中把“写快照必须填 user_id（个人内容）”列为写入方验收项；T-B10 等写入方评审时检查 | 架构师（写入 plan）；后端（写入方） |

已按裁定接受、不计为问题：在 SAVEPOINT 里置 purging 再回滚后提交可以成功（无害，没有绕过）；aia_maint 被设计为唯一能写 purging 的角色；最终审计 `admin.user_data_deleted` 的 target_id 为 NULL、只记各表行数。

## 测试方法（实测 PG）

1. 静态检查（/tmp/rv3-ci.sh）：ruff check、ruff format --check（77 个文件）、mypy strict 通过；ruff 单独检查 0012、0013 通过；scripts/ci 各检查通过；scripts/ci/tests 200 passed / 55 skipped；check_fixtures 失败为既有问题。
2. 迁移：`alembic upgrade head`（0013）成功，`alembic check` 无差异；0013 → 0011 → head 往返成功，app.users 上的触发器数 2 → 1 → 2。HEAD 7a3e9cb 上 0013 → 0014 成功、`alembic check` 干净；指向 app.users 的外键列 65 个，与 HANDLED_FK 完全一致（无遗漏、无多余），8fd9502 时点同样一致。
3. B1 攻击（分别以 aia_api、aia_ingest 执行，全部被拒）：UPDATE 成 purging（“只有 aia_maint 可写 purging”）；以 purging INSERT；管理员自置 purging 后抹审计；直接 DELETE 画像（reject_mutation）；`SET ROLE aia_maint`（permission denied）；`ALTER TABLE … DISABLE TRIGGER`（must be owner）；`SET session_replication_role`（permission denied）。三个角色在 app/ops/public 都没有 CREATE 权限；库中没有 SECURITY DEFINER 函数；aia_maint 没有成员。核对：画像仍在、审计未变、所有用户仍为 approved。
4. aia_maint 滥用：置 purging 后改回 → 拒（purging 行只能删除）；置 purging 不删就提交 → 提交时被延迟触发器拒；以 purging 插入 → 拒；置 purging 后改 username → 拒；乱改审计 → reject_mutation 拒；删除用户后同 id 重新插入为 approved → 提交时拒（按 id 检查）；SAVEPOINT 内置 purging 再回滚 → 提交成功（无害）。
5. CLI 端到端：以 api DSN 跑 `--execute` → 拒绝；dry-run 正常。以 aia_maint DSN（`AIA_MAINT_DATABASE_URL_FILE`，600 权限文件）执行 bob：先吊销 2 个会话；user_id=bob 与 licence_id=bob 证书的快照删除，市场级快照与 carol 的快照保留；account_reviews 中 bob 行 reason/user_id 为 NULL，carol 的 reason 保留；bob 相关审计 detail 清为 `{}`、target_id 置 NULL，证书暂停审计剩 `{"from":"active"}`（管理员理由已去掉）；`admin.user_disabled`（含 [bob, carol]）detail 整体清空（m1）；llm_calls 独占行删除、共享行 body/hash 清空；bob 的 daily_report 删除，carol 的保留；Redis 中 bob 的会话与限速键删除，carol 会话保留；最终审计只记行数。
6. 阻断：插入一条 user_id 为空、内容提到 carol 的快照后，对 carol 执行 → 被阻断，carol 仍在。
7. 权限现状：执行现有 grants.sql 后，aia_api、aia_ingest 仍能 SELECT/DELETE ops.pending_file_purges；grants.sql 中没有 aia_maint（运维前置）。
8. 清理：已 `docker rm -f rv3-pg rv3-redis`，/tmp/rv3-*（含 aia_maint DSN 文件）已删除；未动 sleepy_sutherland、youthful_banach、testcontainers-ryuk、aia-t01-*、be-b03a-* 等其他容器。

## 检查项

| 检查项 | 结果 |
|---|---|
| api/ingest 能否写 purging | 不能 ✔ |
| purging 行能否改回或改其他列 | 不能 ✔ |
| 置 purging 不删能否提交 | 不能 ✔ |
| 删后同 id 重插能否提交 | 不能 ✔ |
| 能否借 SET ROLE / DISABLE TRIGGER / replication_role 绕过 | 不能 ✔ |
| data_snapshots 归属与清理 | ✔（依赖写入方填 user_id，m3） |
| reason / 审计 detail / Redis 会话 / llm_calls | ✔（审计有过度清洗，m1） |
| 外键覆盖（含 HEAD 0014） | ✔ 65/65 |
| 0013 upgrade/downgrade/upgrade | ✔ |
| grants.sql 有 aia_maint | ✘ 运维前置 |
| api/ingest 无权访问 pending_file_purges | ✘ 运维前置 |
| verify-roles.sh 断言 | ✘ 运维前置 |

## 谁需要做什么

- 运维（上线前必须）：① grants.sql 新增 aia_maint（最小权限、LOGIN、api/ingest 不得是其成员，口令走密钥文件，CLI 用 `AIA_MAINT_DATABASE_URL_FILE`）；② 在第 55–59 行授权循环之后收回 aia_api、aia_ingest 对 ops.pending_file_purges 的全部权限，并授给 aia_maint；③ verify-roles.sh 加对应断言。不做这三项，CLI 无法执行 `--execute`。
- 后端：m1（数组型 id 只删匹配元素，或等架构师口径）；m2（dry-run 改用 aia_maint DSN 或权限不足时降级）。
- 架构师：确认 aia_maint 的权限方案细节；m1 口径；m3 把“写 data_snapshots 必须填 user_id”写进 plan 并列为写入方验收项。
