# 评审报告：45589c2（T-B16-core：delete-user-data CLI + 迁移 0011）

- 评审对象：`45589c2`（父提交 `4caedc0`，2026-11-02 07:24 UTC+8，仅本地）
- 依据：docs/plan.md §7.3「删除用户数据 CLI 规则」（2832–2846 行）、plan.md:2831（移除 /me/export）、用户裁定 ①–⑤
- 方式：`git archive 45589c2` 导出到 /tmp/rev4，`uv sync --frozen`；临时容器 timescale/timescaledb:2.31.0-pg16 + redis:7.4.12-alpine 实测，测完已删除（rev4-pg、rev4-redis）；未改代码、未提交、未推送，未打印任何密钥

## 结论：不通过

有 2 个 B 级问题：一是 api/ingest 角色可以借 purging 状态绕过不可变约束，而且不留痕迹（已实测复现）；二是 data_snapshots 中由持仓和成交派生的内容完全没有处理（裁定 ③）。另有 4 个 M 级问题。迁移的 upgrade/downgrade/upgrade 来回结构一致，`alembic check` 干净；CLI 正常路径的物理删除、文件清理和 purging 不能提交这几项都按预期工作。

## 问题表

| 级别 | 位置 | 问题原因 | 修复建议 | 归属 |
|---|---|---|---|---|
| **B1** | migrations/versions/0011_t_b16_purge_user.py:208–223（reject_purging_commit / trg_users_purging_not_committed）；deploy/db/roles/grants.sql（aia_api/aia_ingest 对 app.users 有整表 UPDATE） | 延迟约束触发器只在提交时检查“是否还存在 status='purging' 的行”。aia_api 可以在同一事务里：把任意用户置为 purging，删除或匿名化该用户的不可变行，再把状态改回 approved，然后提交。提交成功，触发器被绕过。实测两次：① 删掉别人的 app.user_profiles（直接 DELETE 会被拒绝，绕过后 COMMIT 成功）；② 把管理员置为 purging 后，把他的 audit_logs 改成 actor_id=NULL、detail={}、ip_hash=NULL，再改回 approved 并提交，等于管理员可以抹掉自己的审计痕迹。用 INSERT 直接插入 purging 用户再改状态，同样能提交。aia_ingest 权限相同。0011 原本应该“只收紧不放宽”，有这个口子就不成立 | ① 在 app.users 上加 BEFORE UPDATE 触发器：OLD.status='purging' 时禁止任何 UPDATE（purging 只能以 DELETE 结束），并禁止 INSERT 时直接写 purging；② 延迟触发器改为按 NEW.id 检查该行在提交时已不存在（`NOT EXISTS (SELECT 1 FROM app.users WHERE id = NEW.id)`），不再依赖全表 EXISTS；③ 限制谁能写入 'purging'（例如触发器要求 current_user 为表 owner 或迁移角色，或在 grants.sql 里对 status 做列级收权）——plan 禁止设专用角色，这一项由架构师定方案，再同步 grants.sql 和 verify-roles.sh；④ 补自测：api 角色执行“置 purging → 删除 → 改回 → 提交”必须失败 | 后端（①②④）；架构师（③ 权限方案，改 plan） |
| **B2** | app/cli/delete_user_data.py STEPS（109–238 行，没有 data_snapshots 步骤）；0011 purge_row_owner（87–125 行，没有 data_snapshots 分支） | 按设计，data_snapshots 会含持仓和成交派生内容：plan.md:84 写明 evidence 全部来自 data_snapshot；plan.md:1016 写明 EvidencePack 给出持仓比例和成本价；plan.md:1257 写明每个版本都生成快照；§2.5.6 中 RC2–RC6 用到持仓和成交。CLI 删掉了 suggestions、plan_versions 等引用方，却留下了它们引用的快照，表上也没有 user 归属，触发器同样不能放行这类删除。按裁定 ③ 定为 B。目前还没有写入方，所以现网暂时没有真实数据，但必须在写入方落地之前改好 | 删除前收集该用户待删行中的 snapshot_id，删完后清掉不再被其他行引用的快照；给 data_snapshots 加 owner_user_id 或映射规则，并在 purge_row_owner 中放行；如果快照在多个用户之间共享，plan 需明确“共享快照不得含个人派生数据” | 后端；架构师（快照归属/共享规则写入 plan） |
| **M1** | 0011:156–170（account_reviews 分支只允许改 user_id/admin_id）；delete_user_data.py:98 | account_reviews.reason 原样保留（该列可为空）。实测删除后，reason 中的个人信息仍在 | reason 置 NULL；purge_anonymize_ok 的期望值加上 `reason IS NULL` | 后端 |
| **M2** | 0011:59–61（purge_pii_key 正则）、147–155（audit_logs 分支）；写入方 app/api/v1/data_licence.py:324–330、359–364 | 实测：data_licence.paused 和 admin.user_approved 这类审计行，在匿名化后 detail 里仍有 `"user_id": "<被删用户 uuid>"` 和自由文本 `"reason"`。target_id 虽已置 NULL，但关联没有断开，也违背 §7.3「指向该用户的值置空」。此外 `security_codes`、`names` 等复数键也匹配不到 | scrub 规则中：值等于被删用户 uid 或证书 id 的字段一律删除或置 NULL（不论键名）；`reason`、`text` 等自由文本键加入清除列表；正则覆盖复数形式；补自测 | 后端 |
| **M3** | delete_user_data.py:572–594（purge_redis 只按 `*uid*` 扫描键名） | 会话键为 `auth:session:<sid_digest>`，uid 只在值里。CLI 删掉了 `auth:user_sessions:<uid>` 索引，会话本体却留在 Redis，直到 TTL 到期，而 §7.3 要求物理删除“会话”。实测执行后 `auth:session:…` 仍在（用户行已删，所以这个会话不能再登录，但数据有残留）。删除索引之后也没法再按索引回收 | 在扫描删除之前调用 `SessionStore.revoke_user(uid)`（app/auth/sessions.py:127），或先 SMEMBERS 索引再逐个删除；补自测 | 后端 |
| **M4** | delete_user_data.py:176–184 | llm_calls 只删“仅被该用户 suggestions/daily_reports 通过 llm_call_id 引用”的行。按 target_type/target_id 关联的重试、降级、失败调用，以及 app.llm_strategy_drafts.llm_call_ids（uuid[]）引用的行都漏掉了。共享行的 request_body/response_body 按设计包含 EvidencePack（持仓比例、成本价），不满足裁定 ④。llm_calls 没有不可变触发器，可以直接改 | 同时按 target 和 llm_strategy_drafts 收集；共享行把 request_body、response_body 置 NULL（再加 request_hash）；目前还没有写入方，先把规则和自测补上 | 后端；架构师确认 ④ 的落地口径 |
| m1 | delete_user_data.py（login_attempts 只按 user_id 删） | 账号创建前，或用户名不匹配时留下的 `username_tried='<用户名>'`、user_id 为 NULL 的行会保留（实测剩 1 行） | 同时删除 `username_tried = 用户名` 的行（180 天保留期本身也会清掉，可接受，但应写明） | 后端 |
| m2 | `_unhandled_fk_refs` | 只检查到 app.users 的外键列。text 形式的引用（non_executable_reasons.released_by、strategy_instances.paused_by、notifications.target_id、ops.ingest_request_log.requester/dedup_key、ops.data_licence_events.actor）没有扫描，也没有处理。后两项目前没有写入方 | 补非外键引用清单，阻断或匿名化 | 后端 |
| m3 | 0011 + grants.sql 默认权限 | aia_api/aia_ingest 对 ops.pending_file_purges 有增删改查权限，path 中含 uid | grants.sql 对该表撤销 api/ingest 的权限，verify-roles.sh 增加对应断言 | 运维（架构师确认） |
| m4 | 0011 文件头 | Create Date 写的是 08:30，晚于提交时间 07:24 | 改为实际时间 | 后端 |
| m5 | 自测报告 T-B16-core.md | 自测在共享隔离库 be-b03a-pg 上对 201 个 pending 用户执行了 `--execute` | 在报告中注明；测试员确认该库仍可用于其他用例 | 后端/测试员 |

已按裁定接受、不计为问题：ip_hash 在 actor 为本人或 NULL 时置 NULL（①）；pending_file_purges.path 含 uid、admin 作为阻断项、存在匿名化 NULL 时 downgrade 失败、bound_username 置 NULL（⑤）。

## 测试方法（实测 PG）

1. 在 rev4-pg 上 `alembic upgrade head`（0011），`alembic check` 无差异。用 psql 变量执行 deploy/db/roles/grants.sql，临时口令只在本地用过、未打印；之后以真实的 aia_api 非超级用户角色连接测试。
2. 绕过测试（aia_api）：直接 DELETE user_profiles 被拒绝 ✔；在一个事务里置 purging → DELETE → 改回 approved → COMMIT，成功 ✘（B1）；对管理员做同样操作后抹掉审计，成功 ✘；INSERT purging 后改状态再 COMMIT，成功 ✘；单独提交 purging，被拒绝 ✔；在 purging 状态下改 action、改无关行、对非本人 actor 改 ip_hash，都被拒绝 ✔；SET CONSTRAINTS 在事务外无效，api 不是 owner，不能 DISABLE TRIGGER ✔。
3. CLI 端到端测试：先造用户 carol（画像、账户、成交、证书、证书事件、审核记录、3 条审计、登录记录、导入批次和文件、磁盘文件、Redis 会话和限速键），同时造 dave 作为对照。dry-run 输出正确；`--execute` 输入确认后 rc=0。目标数据删除完整，dave 的数据不受影响，导入目录已清空，pending 为 0，purging 行为 0。残留：reason（M1）、审计 detail 中的 user_id 和 reason（M2）、auth:session 键（M3）、username_tried 行（m1）。
4. 迁移测试：在新库 aia2 上依次执行 0010 → head → 0010 → head。降级后的触发器（104 个）和 8 个守卫函数的 md5 与 0010 一致；两次 head 的结果相同；0011 只新增 trg_users_purging_not_committed、pending_file_purges.trg_no_truncate，并修改 reject_mutation/guard_daily_reports。在有匿名化数据的库上 downgrade，报 NotNullViolation 并整体回滚（符合裁定 ⑤）。
5. 静态检查：mypy 干净；ruff 只在 migrations/env.py 报一条 E501（不是本次提交引入的）。
6. 清理：已执行 `docker rm -f rev4-pg rev4-redis`，临时目录已删除；没有动 be-b03a-*、aia-t01-* 等其他容器。

## 检查项

| 检查项 | 结果 |
|---|---|
| api 能否把用户置为 purging | 能（有整表 UPDATE 权限，CHECK 也允许）✘ |
| purging 不提交时能否删除不可变行 | 能，改回状态即可提交 ✘（B1） |
| 匿名化 UPDATE 能否改动无关行或无关列 | 不能 ✔ |
| 能否绕过延迟触发器 | 能，见 B1 ✘ |
| 物理删除（画像、账户、成交、证书、导入、登录） | ✔ |
| 匿名化（audit/account_reviews/data_licence_events） | 部分：reason 和 detail 中的 user_id 有残留 ✘（M1/M2） |
| IP 处理 | ip_hash 置 NULL（按裁定 ① 接受）✔ |
| 导入文件 / pending 重试 | ✔ |
| Redis | 会话本体残留 ✘（M3） |
| /me/export 已移除 | ✔（路由不存在） |
| data_snapshots | 未处理 ✘（B2） |
| llm_calls | 覆盖不全 ✘（M4） |
| 0011 upgrade/downgrade/upgrade | ✔ |
| 0011 只收紧不放宽 | 在 B1 修复前不成立 ✘ |
| grants.sql 是否需要更新 | 需要（B1 的权限方案、m3）|
