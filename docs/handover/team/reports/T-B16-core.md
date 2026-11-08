# T-B16 本体：导出与管理员删除用户数据 CLI

**结果：按指令停止并上报。没有写代码，也没有提交。** 原因是不可变触发器挡住了删除，而文档没有写怎么处理。导出接口在契约里也没有定义。

## 1. 删除被不可变触发器挡住（在隔离库 0008 上实测）
- 共有 66 个外键引用 `app.users`，全部是 `ON DELETE NO ACTION`。其中 19 张表带 `user_id`，并且有 DELETE 触发器（`reject_mutation` 或 guard 系列）：
  - `app.account_reviews`：每个经过审批的用户都有一行
  - `app.user_profiles`：填过画像的用户都有一行
  - `app.trades`、`suggestions`、`suggestion_user_actions`、`candidate_signals`（含各分区）、`plan_drafts`、`plan_draft_confirmations`、`signal_events`、`risk_events`、`claims`、`symbol_horizon_assessments`、`daily_reports`、`risk_control_settings_history`、`ops.data_licence_events` 等
- `app.audit_logs` 没有外键，但不可变。plan §7.3 要求“审计日志保留脱敏记录”，这就要 UPDATE 其中的 actor/target，同样会被触发器拒绝。
- 结论：只要用户被审批过（有 `account_reviews` 行），事务里删 `app.users` 必然失败：要么外键阻止，要么去删子表时触发器报错。
- plan §7.3 和 §3、契约都没有说明删除用户时怎样处理不可变表，比如临时放行的会话变量、专用数据库角色、`session_replication_role`、匿名化代替删除等。所以按指令停在这里，没有自行设计绕过触发器的办法。

## 2. 导出 `GET /me/export` 不在契约里
plan §7.3 写的是“`GET /me/export`，JSON+CSV”，但契约 v0.2.6 和 v0.2.7 都没有这个端点，导出的范围、格式、文件结构也都没定义。契约是唯一事实来源，所以没有实现。

## 需要架构师决定（之后后端约半天可完成）
1. **删除方式**。下面三种选一种，或者组合：
   - (a) 改为匿名化：保留不可变行，把 `users` 行改成墓碑（清掉用户名、显示名、申请说明，状态改为 deleted），可变的个人数据表物理删除；
   - (b) 新增迁移：在触发器里加只对专用维护角色或会话变量（如 `app.purge_user`）放行的分支，CLI 在同一个事务里 `SET LOCAL` 后整体删除；
   - (c) 按表逐一规定是删除、匿名化还是保留。
2. **审计日志的“脱敏保留”具体做什么**：是把 actor_id 替换成某种墓碑，还是只删掉 detail 里的个人字段；并说明这些 UPDATE 怎样获得触发器放行。
3. **原始导入文件**（`/srv/aia/imports/`）的删除要不要放进同一个 CLI，失败时怎么补偿。文件系统的删除没法和数据库事务一起回滚。
4. **把 `GET /me/export` 写进契约**：范围（哪些表，是否含审计和通知）、JSON 与 CSV 的结构（zip 还是多文件）、限流、审计动作名。

## 已准备好的设计（拿到决定后直接按此实现）
- `python -m app.cli delete-user-data --user-id <uuid>`：
  - 默认只做 dry-run，按表列出行数，并标出哪些表是不可变的；
  - 真正执行需要加 `--execute`，并在交互提示里手动输入完整的 user-id 确认；
  - 单个事务完成；
  - 写一条 `admin.user_data_deleted` 审计，`detail` 里只记各表行数，不含个人信息。

## 2026-11-02 07:2x 实现（按 plan §7.3）—— 提交 45589c2（仅本地，未 push）

### 设计
- **迁移 0011**：在 `ck_users_status` 中加入 `purging`。`account_reviews.user_id/admin_id`、`data_licence_events.user_id/licence_id` 改为可空，用于匿名化保留。新建 `ops.pending_file_purges(path UNIQUE, attempts, last_error, …)`，不含 user_id，并禁止 TRUNCATE。新增函数 `purge_permits / purge_row_owner / purge_anonymize_ok / purge_target_ref / purge_scrub_json / purge_pii_key`。
- **数据状态闸门**：`reject_mutation` 与 `guard_daily_reports` 只在两种情况下放行：
  1. 行的属主当前处于 `purging`，且操作为 DELETE；
  2. 对审计/保留表做 UPDATE，且变更后的值恰好等于匿名化值，其它列不变。

  不读会话变量，不依赖 session_replication_role，也没有专用角色。`trg_users_purging_not_committed` 是 DEFERRABLE INITIALLY DEFERRED 的约束触发器：提交时只要还有 purging 行就失败，所以 purging 只能在单个事务内出现。API 代码不引用 purging（自检用 grep 证明）。
- **CLI**：`python -m app.cli delete-user-data --user-id <uuid> [--execute]`。
  - 默认 dry-run，按表列出计数并标注 delete/anonymize/unlink，同时列出阻断项、待删文件和 pending 重试队列。
  - `--execute` 需要手动输入完整 user-id 确认。
  - 执行顺序：先 `SELECT … FOR UPDATE`，置 purging，然后依次匿名化 audit_logs、account_reviews、data_licence_events、ingest_request_log；再删 market.*（动态查找含 source_licence_id 列的表）；再按 FK 顺序物理删除全部用户数据；最后删 licences 和 users 行。之后写一条审计 `admin.user_data_deleted`，actor 为 NULL，role 为 system，detail 只有 `{"rows":{表:数}}`。以上在单个事务内提交，任何 DB 错误都会整体回滚，rc=1。
  - 提交后先重试 pending 队列，再删原始导入文件（只处理 AIA_IMPORTS_DIR 根内的路径），失败的写入 pending_file_purges。随后清 Redis：SCAN 删除 uid/licence 相关 key、`auth:lockout:<sha256(username)>*`，并对 `ingest:requests` 中的匹配条目执行 XDEL。
  - 退出码：0 成功；1 拒绝/确认不符/DB 错误；2 用法错误；3 已提交但文件或 Redis 有残留。
  - 动态检查所有指向 app.users 的 FK 列，出现未处理的列就拒绝执行。

### 测试（隔离库 be-b03a-pg / 临时库 aia_tb16core，非超级用户角色 tb16_nosu）
- selftest_tb16core：**60/60 PASS**。覆盖：
  - dry-run 不改数据；确认不符或只输入部分 id 时拒绝。
  - 非 purging 的 DELETE/UPDATE 仍被挡住；会话变量无效；非超级用户无法 SET session_replication_role。
  - 带 purging 提交失败，包括 SET CONSTRAINTS ALL IMMEDIATE、忘删 users 行、直接 INSERT purging 用户三种情况。
  - purging 的 A 删不了 B 的行；匿名化值错误、改动 action、匿名化 B 的审计行都被拒绝。
  - 有阻断项时拒绝执行；目录 chmod 555 时返回 rc=3，路径进入队列，下一次运行先重试并清空队列。
  - 审计 detail 只有计数；A 的种子行全部删除，B 不受影响；扫描 114 张表无 PII 残留；Redis 中 A 的 key 和 stream 条目已删，B 的保留。
  - 执行后触发器照常阻断。
- 回归：tb03c 57、tb45 67、api 205、tb16 123、xff 21、tb03a 39、t006e、env、tb04ax 114、tb02x 61、tb02y 86、tb03d 67、m1_0009 17，全部通过。
- tester 套件：566 passed，5 failed。失败的都是 test_meta_enums 的版本常量还停在 v0.2.7（测试侧问题，后端已是 v0.2.8）。
- ruff、ruff format --check、mypy、alembic check 均干净。
- 中途有 5 个旧自检报 503 REGISTRATION_CLOSED。原因是隔离库里历次自检累积了 201 个 pending 用户，触发了 ≥200 的注册上限（契约 4caedc0 已写明该行为），属于环境问题，不是回归。处理方式：用本 CLI 对这 201 个 pending 用户逐个执行 `--execute`，201/201 rc=0，无 purging 残留，顺便做了一次实测。

### 决定 / 残留（请架构师确认）
- audit_logs.ip_hash：actor 是本人或为 NULL 时置 NULL（不截断）；管理员的 ip_hash 保留。
- account_reviews.reason 原样保留（可能包含用户自述，**需确认**是否也要清空）。
- data_snapshots 未按用户区分，作为残留。
- llm_calls：只被该用户 suggestions/daily_reports 引用的会删除，共享的保留。
- invite_codes.bound_username 置 NULL；used_by 等指向用户的列解除关联（unlink）。
- 目前没有带 source_licence_id 的 market 表，CLI 运行时动态发现。
- pending_file_purges.path 可能含 uid 目录名，这是一个残留关联，重试成功后删除。
- 管理员被不可变或 NOT NULL 列引用时作为阻断项，拒绝执行（需人工处理）。
- 0011 的 downgrade 在已有匿名化 NULL 数据时会失败（有意为之）。
- /me/export 不在本任务范围。

### 谁要做什么
- 运维：共享库执行迁移 0009（含回填）、0010、0011；按需设置 AIA_IMPORTS_DIR（默认 /srv/aia/imports）。
- 测试：test_meta_enums 更新到 v0.2.8；可把 tb16core 的场景转成正式测试。

---

## T-B16-core-r2（评审 45589c2 修复；8fd9502，2026-11-02 07:50 前后，仅本地提交）

依据：评审 review-45589c2.md、07:36 派单摘要、**plan §7.3/§3.3 8a760d1（权威）**。全部改动都是新迁移和新提交，没有 amend。

### 改动
- **迁移 0013_t_b16_core_r2**（0012 → 0013，可降级）：
  - **B1 角色门**：新触发器 `trg_users_purging_guard`（BEFORE INSERT OR UPDATE ON app.users，函数 `app.guard_users_purging`）：
    - 以 status=purging INSERT 一律拒绝；
    - 原值已是 purging 的行任何 UPDATE 都拒绝（只能 DELETE），aia_maint 也不例外；
    - 把 status 改成 purging 时，若 `current_user <> 'aia_maint'` 则拒绝（42501）。

    这个角色只决定谁能写 purging。其余不可变表的放行仍然只看“该行属于 purging 用户”，没有任何会话变量、角色或维护模式旁路。
  - **按行延迟检查**：`trg_users_purging_not_committed` 改为 `AFTER UPDATE OF status … DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.status='purging')`，提交时检查 `id = NEW.id` 的行必须已不存在。也就是说，本事务里每个被置为 purging 的 id 都必须已删除。
  - **B2 / §3.3**：`app.data_snapshots` 加列和外键：
    - `user_id`（可空，FK users，部分索引）；
    - `licence_id`（可空，FK user_data_licences，部分索引）。

    `purge_row_owner` 对 data_snapshots 先按 user_id 判断归属，user_id 为空时按 licence 的所有者判断。
  - **M1/M2 审计**：
    - `purge_pii_key` 扩充：支持复数形式；新增 reason、note、comment、remark、memo、text、description、display_name、user_id、target_user_id、actor_user_id、licence_id、license_id、account_id、profile_id、shareholder_code、broker_account、phone、address 等。
    - 新函数 `purge_ref_ids(uuid[])`：返回 uid 以及该用户的证书行、画像、账户 id。
    - 新函数 `purge_json_mentions` 和 `purge_scrub_json(jsonb, text[])`：除了按键名清理，还会删掉键名或字符串值中含上述任一 id 的项，以及数组里含这些 id 的元素。
    - `purge_anonymize_ok`：如果 audit 行只是 detail 提到该用户（actor 和 target 都不是该用户），也允许按上述规则清理 detail；`account_reviews` 必须把 reason 置 NULL。
- **CLI**（app/cli/delete_user_data.py）：
  - **连接角色**：从 `AIA_MAINT_DATABASE_URL_FILE`（文件内容是 DSN，按 *_file 约定）或 `AIA_MAINT_DATABASE_URL` 读取连接串。`--execute` 在没有该 DSN、或 `SELECT current_user` 不是 aia_maint 时拒绝执行（rc 1）。dry-run 可以退回用 DATABASE_URL。
  - **M3 会话**：执行前先调用 `SessionStore.revoke_user(uid)`，失败就取消，不改数据库；提交后在 purge_redis 里先再吊销一次，再按键名删除。
  - **M1**：account_reviews.reason 一律置 NULL。
  - **M2**：audit 匿名化的 WHERE 条件增加“detail 提到该用户”，SET 改用 `purge_scrub_json(detail, ref_ids)`。
  - **M4 llm_calls**：引用列在运行时从 pg_catalog 动态发现，包括：
    - 指向 llm_calls 的外键：`daily_reports.llm_call_id`、`suggestions.llm_call_id`；
    - `^llm_call_ids?$` 形式的 uuid[] 列：`llm_strategy_drafts.llm_call_ids[]`；
    - `llm_calls.target_id` 指向该用户的对象（对象 id 也是动态发现的：凡是有指向 users 外键列、且有 id 列的表，都取该用户的行）。

    处理方式：
    - 只被该用户引用 → 在所有引用方删除之后物理删除；
    - 也被他人引用 → 保留元数据，把 request_body、response_body、request_hash、validation_errors 置 NULL，若 target 指向该用户也一并解除；
    - 无人引用 → 不动。

    dry-run 会列出分类数量和发现的引用列。
  - **B2**：`data_snapshots WHERE user_id = uid OR licence_id = ANY(该用户证书)` 物理删除，顺序在引用方之后、证书行之前。执行前的阻断检查只针对 user_id 和 licence_id 都为空的快照（这类快照只能是市场级内容）。
  - **m1**：login_attempts 增加按 `lower(username_tried) = lower(username)` 删除（包括 user_id 为空的行）。
  - **m2**：
    - 他人的 `non_executable_reasons.released_by = uid` → 置 NULL；
    - 他人的 `notifications.target_id` 指向该用户对象 → target_type 改为 'none'，target_id 和 target_route 置 NULL；
    - `ops.ingest_request_log`：涉及该用户证书或文本引用的行，licence_id 置 NULL、dedup_key 置 NULL；requester 含 uid 或证书 id 的改为 'purged'。
    - `strategy_instances.paused_by` 和 `ops.data_licence_events.actor` 是枚举（system/admin 等），不会存用户标识，**不适用**。
- **m4**：0011 头部 Create Date 改为 `2026-11-02 07:24:29+08:00`，只改注释，和 0013 在同一个新提交里。
- **m5**：T-B16-core 的测试一节已记录：为解除注册上限，在隔离库 be-b03a-pg 中用本 CLI 对 201 个 pending 用户执行了 `--execute`（隔离库专用，与共享库无关）。r2 之后执行必须用 aia_maint。之后清理隔离库的脚本 /tmp/tb02/purge_pending.py 只在隔离库使用。

### 8a760d1 与 07:36 派单摘要的差异（按 8a760d1 执行）
1. account_reviews.reason：摘要写的是“清空”；8a760d1 明确为**一律置 NULL**，包括管理员被删除时他写给别人的 reason。按后者实现。
2. data_snapshots：摘要写“user_id（相关时 licence_id）”；8a760d1 的 §3.3 规定**两列都加**，licence_id 有外键，两列都可空。已实现，按任一列删除。
3. llm_calls 共享行：8a760d1 要求 request_body 和 response_body 置 NULL，request_hash“可清”。本实现**也清 request_hash**，另外清了 validation_errors（可能回显输入）。
4. aia_maint 的授权由运维通过 grants.sql 和 verify-roles.sh 落地；本仓库不写 deploy/，SQL 草稿见下文。

### 给运维的角色 / 授权 SQL（草稿，落在 deploy 的 grants.sql；本仓库未改 deploy/）
```sql
-- 维护角色：只给删除用户数据 CLI 用；api/ingest 进程不持有其凭据（DSN 放密钥文件，经 AIA_MAINT_DATABASE_URL_FILE 指给 CLI）
<redacted:sensitive-value-or-command>
GRANT CONNECT ON DATABASE aia TO aia_maint;
GRANT USAGE ON SCHEMA app, ops, market TO aia_maint;
GRANT SELECT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO aia_maint;   -- 删除/匿名化/解除关联
GRANT INSERT ON app.audit_logs TO aia_maint;                             -- admin.user_data_deleted 审计
GRANT SELECT, UPDATE, DELETE ON ops.data_licence_events, ops.ingest_request_log TO aia_maint;
GRANT SELECT, INSERT, UPDATE, DELETE ON ops.pending_file_purges TO aia_maint;
GRANT SELECT, DELETE ON ALL TABLES IN SCHEMA market TO aia_maint;        -- 将来带 source_licence_id 的表
-- 不给 aia_maint：CREATE/TRUNCATE/REFERENCES/TRIGGER、BYPASSRLS、SUPERUSER、任何角色成员身份
-- api / ingest 对待清队列无任何权限
REVOKE ALL ON ops.pending_file_purges FROM aia_api, aia_ingest;
-- 注意：新表上线后需补授（或用 ALTER DEFAULT PRIVILEGES FOR ROLE <迁移角色> IN SCHEMA app GRANT SELECT, UPDATE, DELETE ON TABLES TO aia_maint）
```
verify-roles.sh 中要断言的内容（全部应当失败）：
```sql
-- 以 aia_api 连接：
BEGIN; UPDATE app.users SET status='purging' WHERE id=:'some_uid';   -- 期望 42501（只有 aia_maint 可以写 purging）
DELETE FROM app.trades WHERE user_id=:'some_uid';
UPDATE app.users SET status='approved' WHERE id=:'some_uid'; COMMIT;  -- 整个序列必须失败，数据不变
SELECT 1 FROM ops.pending_file_purges LIMIT 1;                        -- 期望 permission denied
-- 以 aia_maint 连接：
INSERT INTO app.users (username,password_hash,role,status) VALUES ('x','x','user','purging');  -- 期望拒绝
BEGIN; UPDATE app.users SET status='purging' WHERE id=:'uid'; COMMIT;  -- 期望提交失败（按行延迟检查）
```

### data_snapshots 无个人数据的证据
- 写入方：`grep -rln data_snapshots app/` 只命中表定义（reviews/strategy/signals/research/realtime 里的外键）和本 CLI，**目前没有任何快照写入代码**。按 §3.3，以后写入方在写持仓、成交或账户派生内容时必须填 user_id 或 licence_id。
- 共享库 aia-t01-postgres-1（只读事务，head 0008）的结果：`data_snapshots` 共 0 行；其中 items/known_events 含任一 users.id、带引号的 username、accounts.id、user_data_licences.id 的行数均为 0。隔离库（head 0013）也是 0 行。
- CLI 执行前仍会核查：user_id 和 licence_id 都为空的快照里如果出现该用户标识，就阻断执行。

### 自检（隔离库 be-b03a-pg 中的临时库 aia_tb16core）
- 测试夹具只在隔离集群里创建 aia_maint（LOGIN，运行时随机密码，从不打印；DSN 写入 0600 的临时文件，结束时删除，并把密码置 NULL）和 aia_api（NOLOGIN，通过 SET ROLE 使用），并授予表权限；对 aia_api 撤销 pending_file_purges 的所有权限。
- selftest_tb16core **93/93 PASS**（原 60 项全部保留，必要时改为以 aia_maint 执行，新增 33 项）。新增内容：
  - **角色**：
    - aia_api 不能写 purging；
    - 超级用户（不是 aia_maint）也不能写 purging；
    - aia_api 的攻击序列“置 purging → 删除 → 改回 → 提交”失败；
    - aia_api 不能把 purging 改回；
    - aia_maint 也不能修改 purging 行（status 和其他列都不行）；
    - 以 purging 状态 INSERT 被拒绝（超级用户和 aia_maint 都一样）；
    - aia_maint 不是通用旁路：对非 purging 用户的 DELETE trades 和 UPDATE audit 都被拦下；
    - aia_api 读 pending_file_purges 返回 permission denied。
  - **按行检查**：C、D 都置 purging 但只删除 C，提交失败，D 不变；只置 C 并删除 C，提交成功。
  - **CLI**：
    - 没有 maint DSN 时 `--execute` 拒绝；
    - 用非 aia_maint 的 DSN 时被 current_user 检查拒绝；
    - 用 *_FILE 方式的 DSN 可以执行 dry-run；
    - dry-run 列出 llm 分类（独占 1、共享 1）和动态发现的引用列。
  - **清除结果**：
    - 管理员写的 reason、comment、note，复数键 user_ids 和 licence_ids，值里带 uid 的字符串以及数组元素都被清掉，只留下 `{"kind":"ok","list":["keep"],"nested":{"rows":1}}`；管理员的 actor_id、ip_hash 和 target 保留。
    - A 相关的 account_reviews.reason 为 NULL，B 的不受影响。
    - 共享 llm_call 的正文、响应和摘要被清空，元数据保留，B 的建议仍然链接它；无人引用的市场级调用原样保留。
    - A 的用户快照和证书快照被删除，市场快照保留。
    - username_tried 只有大小写不同的失败登录记录被删除。
    - B 的行里 released_by 和 notifications.target 已解除关联，行本身保留；A 的 ingest_request_log 行已匿名化，B 的不变。
    - A 的会话已用 SessionStore 吊销（B 的保留；B 被清除后 B 的会话也被吊销）。
  - **全库 PII 扫描**：表数为 **115**（0013 后比 114 多一张，含 0012 的 cooldowns），A 的 uid、用户名、证书 id 和标记字符串全部零命中。
  - **约束**：purging A 时把 account_reviews 的 reason 保留不清，会被触发器拒绝。
- 其余回归全部 PASS（见 T-B03e.md）。tester 套件结果为 579 passed、274 skipped、2 xfailed。ruff、format、mypy 和 alembic check 都干净，0013 的 downgrade/upgrade 往返也通过。

### 残留 / 需要确认
- 共享 llm_call 的判定比较保守：如果 target_id 指向非该用户的对象（例如证券代码），就算作“他人引用”，只清空正文，不删除。元数据里不含个人数据。
- `llm_strategy_drafts`：`requested_by = uid` 的草稿整行删除，它们的 llm_call_ids 算作该用户的引用。该用户只作为 reviewer_id 的草稿保留，只解除 reviewer_id。如果某个调用同时被 A 的草稿和他人对象引用，就算作共享，只清空正文。他人草稿的数组里不会出现悬空 id，因为被多方引用的调用不会被删除。
- aia_maint 的授权和 verify-roles.sh 由运维负责；没有这个角色的环境里，`--execute` 会拒绝执行。

### 谁要做什么（r2）
- 运维：建 aia_maint 并按上面的 SQL 授权；api/ingest 撤销 pending_file_purges 权限；verify-roles.sh 加入上述断言；maint DSN 进 secrets 并设置 `AIA_MAINT_DATABASE_URL_FILE`（只给 CLI）；在共享库执行迁移 0012、0013。
- 架构师：确认 llm_calls 共享判定的保守规则（target 指向非用户对象时算作共享）。
- 测试：alembic head 改为 0013；可把 selftest_tb16core 中的 r2 场景转成正式测试（需要能建角色的测试库）。
