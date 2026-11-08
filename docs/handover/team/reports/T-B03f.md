# T-B03f：评审 be607b3 / 8fd9502 / f72b8c7 修复

- 提交：`a8e055b`（仅本地，未推送；不 amend 原提交）。
- 依据：review-be607b3*.md、review-8fd9502*.md、review-f72b8c7*.md；编排者 18:20 指令；docs 4532478（契约变更表 #28、plan 7.3 保留期 / ID 类键清洗粒度 / aia_maint 细则 ⑤）。
- 改动：app/api/v1/data_licence.py、app/licences/service.py、app/db/tables/licences.py、app/cli/delete_user_data.py、app/main.py、app/api/v1/auth.py、新迁移 migrations/versions/0015_t_b03f_review_fixes.py（down_revision 0014）。

## be607b3

- (a) 管理员对**未暂停**用户 `resume` → `204`，不写审计、不写事件、不发通知（提前返回）。
- (b) 只有真实状态变化（未暂停→暂停、暂停→恢复）时，在同一事务内给用户写一条 `data_licence` 类通知：标题“数据证书已被管理员暂停 / 恢复”，**正文不含 reason**。重复暂停（幂等）不再发通知。
- (c) 冷却记录保留期（契约 #28 ①、plan 7.3）：`paused_until` 非空的到 `paused_until` 过期；`paused_until` 为空的最多保留到删除后 24 小时（`COOLDOWN_NULL_UNTIL_TTL`）。读取时过期记录一律视为不存在；物理删除 `purge_expired_cooldowns(conn, now)`，返回行数。
  - 仓库里还没有周期任务框架（beat.py 是占位，ingest tick 只写心跳），所以目前在每次写入/读取冷却记录时（`DELETE` 与 `PUT /me/data-licence`）顺带清理全表的过期行。plan 7.3 要求的“每小时周期任务”在 beat 落地时直接调用 `purge_expired_cooldowns`。
  - 解读：plan 7.3 写“两者以先到者为准”。本实现按契约 #28：有 `paused_until` 的到 `paused_until`，**不**再加 24 小时上限。如果架构师的意思是所有记录都取 min(paused_until, 删除+24h)，只需在 `_cooldown_expired` 里改一行，请明示。
  - 删除用户时，冷却记录已在 T-B16-core 中一并物理删除（不变）。
- (d) 只读检查共享库：aia-t01-postgres-1 与 rvpg 都已到 0014，0012 已应用，所以**不改 0012**，新增迁移 0015：`COMMENT ON` 把指纹列注释改成 `HMAC(K_cooldown, user_id||0x00||licence_hmac)`（与实现一致），表定义同步；downgrade 恢复旧注释。

## 8fd9502

- (a) ID 类键清洗粒度（plan 7.3 v0.2.9 内裁定）：迁移 0015 重定义 `app.purge_pii_key`，从“整键删除”名单中去掉 id 类键（user_id、target_user_id、actor_user_id、licence_id、license_id、account_id、profile_id 及其复数形式）。这些键交给已有的“值是否指向被删用户/其证书”规则：数组只移除被删用户的 id，空数组保留 `[]`；单值键指向被删用户则删键，指向其他用户（如执行操作的管理员）则保留。`reason`/`note`/`comment` 等自由文本仍整体删除。触发器 `purge_anonymize_ok` 用同一函数，口径一致。
  - `username` 仍在整键删除名单里（与 8a760d1 一致）。plan 写的是“值为被删用户才删”，目前审计 detail 里不写 username，所以影响为零。如需严格按 plan 处理，请架构师确认。
- (b) dry-run：
  - 第一条语句就是 `SET TRANSACTION READ ONLY`，写入会报 ReadOnlySqlTransaction。
  - 当前角色是 `aia_api` / `aia_ingest` 时**拒绝**（plan 7.3 aia_maint 细则 ⑤），rc=1，提示改用 `AIA_MAINT_DATABASE_URL_FILE` 或只读角色。
  - 连接无权读 `ops.pending_file_purges` 时（运维 REVOKE 之后），dry-run 降级为跳过该项并提示；`--execute` 遇到这种情况拒绝执行。

## f72b8c7

- 第 58 行：注册闸门不再直接调用 `get_settings()`（被带参数的 dependency override 时会出错）。`create_app` 把配置写入 `app.state.settings`，闸门先读它，取不到时才回退到 `get_settings()`。closed 模式下畸形 JSON 仍返回 503，open 模式仍返回 400。
- 413：已有中间件在路由前返回 `413 PAYLOAD_TOO_LARGE`（closed 模式下发 60 MB 请求体已实测为 413），与契约 #28 ② 一致，无改动。

## 自检

- /tmp/tb02/selftest_tb03f_review.py：24 passed / 0 failed。覆盖：
  - (c) 6 种冷却情形，以及直接调用清理函数；
  - (d) 注释、表定义、alembic check 和 head=0015；
  - 8fd9502(a) 三类键；
  - (b) 只读事务、低权降级、服务账号拒绝、输出不含口令（临时角色用运行时生成的口令，用后删除）；
  - f72b8c7 的 override。
- selftest_tb03f 23/0。selftest_tb16core 93/0：审计用例改为多用户 id，期望只删被删用户的 id。其余 20 个自检都通过。
  - selftest_api 有 1 条预期失败：契约 §3 已有 81 个枚举，比实现多出 T-A11 的 3 个，留给 T-B10。
- 隔离库 0015 upgrade → downgrade → upgrade 往返通过，alembic check 无差异。
- tester 全套：855 passed / 2 failed / 54 xfailed / 1 xpassed。两条失败都不是本任务代码引起的：
  1. `test_alembic_head_is_known`：新 head 0015 不在已知列表中；
  2. `test_snapshot_equals_plan_block[realtime]`：docs 4532478 给 plan 的 realtime.yaml 加了 `admin_alerts`，测试快照还没同步。
- t_t24 / t_t25c（删除 CLI）47 passed、1 xfailed（原有）。ruff、mypy（102 文件）通过，secret_scan 7 个文件阻断 0。未调用麦蕊，STOP 未动。

## 谁需要做什么

- 运维：按 plan 7.3 aia_maint 细则 ①–④ 改 `deploy/db/roles/grants.sql`，在 schema 级 GRANT 和 ALTER DEFAULT PRIVILEGES 之后 `REVOKE ALL ON ops.pending_file_purges FROM aia_api, aia_ingest`；`verify-roles.sh` 加断言；生产 dry-run 用 aia_maint DSN 文件。
- 架构师：确认冷却期“先到者”的解读（有 paused_until 时是否也设 24h 上限）；确认 `username` 整键删除可以保留。
- 测试员：
  - 已知 head 加入 `0015`（T-B10 之后还会有 0016）；
  - 同步 realtime 快照（admin_alerts）；
  - 补测试：冷却保留期、resume 未暂停时 204、暂停/恢复通知不含 reason、ID 类键清洗、dry-run 拒绝服务账号。
- 后端（beat 落地者）：每小时调用 `app.licences.service.purge_expired_cooldowns`。
- 写快照的后端任务：含用户数据的 `data_snapshots` 必须填 `user_id`（沿用 T-B16-core-r2）。
