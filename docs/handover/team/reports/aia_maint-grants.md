# aia_maint 最小授权（删除用户数据 CLI：dry-run + --execute）

日期：2026-11-01（后端）。对象：运维（替换 deploy/db/roles/grants.sql 里 `$maint` 块）、架构师（知会）。

## 1. 结论
- aia_maint 只需要：CONNECT、`USAGE ON SCHEMA app, ops`、10 个 `app.purge_*` 函数 EXECUTE，
  以及 81 张表上的**列级** SELECT/UPDATE/INSERT 与 66 张表的表级 DELETE（全部列在 §3 SQL 中）。
- **不需要**：market 任何权限（当前无 `source_licence_id` 表）、任何序列（两张 INSERT 表的 id 都是 `gen_random_uuid()`）、
  TRUNCATE/REFERENCES/TRIGGER、默认权限、角色成员。
- 不可 SELECT：`app.users.password_hash`、`app.user_data_licences.ciphertext / licence_hmac`、`app.llm_providers.api_key_ciphertext`、
  `app.notification_channel_bindings.target_ciphertext`、`app.import_rows.raw_line`、`app.llm_calls.request_body / response_body`、
  `app.user_data_licence_cooldowns.fingerprint`。任何表都**无表级** SELECT/UPDATE/INSERT（否则覆盖将来新增的列）。
- `app.users` 上只有 SELECT(id, reviewed_by, role, status, username)、UPDATE(reviewed_by, status)、DELETE；**无 UPDATE(role)**、无 INSERT。
- 注意：llm_calls 的 request_body/response_body 是 **UPDATE-only**（清除时置 NULL/脱敏，不读取），PG 允许只写不读的列授权。

## 2. 怎么得出的（来自实际代码路径，不是猜）
1. 在隔离库 be-b03a-pg 上，给 SQLAlchemy 挂 `before_cursor_execute` 钩子，只记录调用栈最近的非库帧位于
   `app/cli/delete_user_data.py` 的语句；跑完整的 purge + dry-run 自测（tb16core 93 项、tb03f_review 24 项、tb10 57 项），
   共 675 条不同语句。
2. 每条语句在另一条超级用户连接上以 `debug_print_rewritten` 执行后回滚，解析改写树里的 `RTEPERMISSIONINFO`
   （requiredPerms / selectedCols / updatedCols / insertedCols）——这正是 PG16 executor 做权限检查用的结构，
   比 EXPLAIN 精确（不会把 Seq Scan 的整行输出算进去）。只取语句本身的改写树；执行期间的 RI 级联以表属主身份运行，不计入。
3. 触发器/函数都是 SECURITY INVOKER，体内查询以 aia_maint 身份执行：purge_user_ids、reject_purging_commit、purge_ref_ids、
   purge_target_ref、purge_row_owner 的 13 个分支逐条同法采集（读 users(id,status)、accounts/user_profiles/user_data_licences(id,user_id)、
   各父表 (id, user_id|account_id|plan_id) 等）。purge_scrub_json / purge_pii_key / purge_json_mentions 不读表。
4. 汇总后断言：无一列落在禁止列表；`FOR UPDATE` 用到的 users、ops.pending_file_purges 均已有列级 UPDATE（PG 要求至少一列 UPDATE）。

## 3. 可直接执行的 SQL（以库属主/migrate 角色执行；幂等；先 REVOKE 清干净）
密码不在此 SQL 里；若需建角色：`CREATE ROLE aia_maint LOGIN NOINHERIT PASSWORD '<从密钥管理取，勿写入文件>';`（占位符，切勿落盘）。

```sql
-- aia_maint 最小权限（删除用户数据 CLI app.cli.delete_user_data：dry-run + --execute）
-- 由 CLI 实际发出的每条语句的 RTEPermissionInfo（PG16 executor 校验的 selectedCols/updatedCols/insertedCols/requiredPerms）
-- 以及 SECURITY INVOKER 触发器/函数体内的查询逐条采集得出；以库属主（migrate 用的 owner）执行；幂等；单事务。
BEGIN;
-- 0. 撤清：表/列/序列/函数上的现有授权 + 默认权限（REVOKE ... ON TABLE 同时撤掉该表全部列级授权）
DO $rv$
DECLARE s text;
BEGIN
  FOREACH s IN ARRAY ARRAY['app', 'ops', 'market'] LOOP
    CONTINUE WHEN to_regnamespace(s) IS NULL;
    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM aia_maint', s);
    EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM aia_maint', s);
    EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA %I FROM aia_maint', s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL ON TABLES FROM aia_maint', current_user, s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL ON SEQUENCES FROM aia_maint', current_user, s);
    EXECUTE format('REVOKE ALL ON SCHEMA %I FROM aia_maint', s);
  END LOOP;
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO aia_maint', current_database());
END
$rv$;
GRANT USAGE ON SCHEMA app, ops TO aia_maint;
-- market：当前没有带 source_licence_id 的表，CLI 只查 pg_catalog，不需要 USAGE/表权限（见报告 §4 新表规则）

-- 1. 函数（触发器函数以调用者身份运行，体内调用的 purge_* 需 EXECUTE；默认 PUBLIC 有 EXECUTE，这里显式授予，
--    以防将来 REVOKE FROM PUBLIC）。函数本身都不是 SECURITY DEFINER。
GRANT EXECUTE ON FUNCTION
  app.purge_ref_ids(uuid[]), app.purge_target_ref(text, uuid[]), app.purge_json_mentions(jsonb, text[]),
  app.purge_scrub_json(jsonb, text[]), app.purge_scrub_json(jsonb), app.purge_pii_key(text),
  app.purge_permits(text, text, jsonb, jsonb), app.purge_user_ids(), app.purge_row_owner(text, jsonb),
  app.purge_anonymize_ok(text, jsonb, jsonb, uuid[])
  TO aia_maint;

-- 2. 表/列（SELECT 只给 WHERE/JOIN/SET 表达式/返回实际引用的列；UPDATE 只给 SET 的列；DELETE 表级；INSERT 只给写入的列）
GRANT SELECT (account_id) ON app.account_events TO aia_maint;
GRANT DELETE ON app.account_events TO aia_maint;
GRANT SELECT (admin_id, id, user_id) ON app.account_reviews TO aia_maint;
GRANT UPDATE (admin_id, reason, user_id) ON app.account_reviews TO aia_maint;
GRANT SELECT (id, user_id) ON app.accounts TO aia_maint;
GRANT DELETE ON app.accounts TO aia_maint;
GRANT SELECT (current_version_id, id, user_id) ON app.action_plans TO aia_maint;
GRANT UPDATE (current_version_id) ON app.action_plans TO aia_maint;
GRANT DELETE ON app.action_plans TO aia_maint;
GRANT SELECT (id, user_id) ON app.alert_rules TO aia_maint;
GRANT DELETE ON app.alert_rules TO aia_maint;
GRANT SELECT (id, user_id) ON app.alerts TO aia_maint;
GRANT DELETE ON app.alerts TO aia_maint;
GRANT SELECT (actor_id, detail, ip_hash, target_id) ON app.audit_logs TO aia_maint;
GRANT UPDATE (actor_id, detail, ip_hash, target_id) ON app.audit_logs TO aia_maint;
GRANT INSERT (action, actor_id, actor_role, detail, target_id, target_type) ON app.audit_logs TO aia_maint;
GRANT SELECT (snapshot_id) ON app.broker_position_snapshot_items TO aia_maint;
GRANT DELETE ON app.broker_position_snapshot_items TO aia_maint;
GRANT SELECT (account_id, id) ON app.broker_position_snapshots TO aia_maint;
GRANT DELETE ON app.broker_position_snapshots TO aia_maint;
GRANT SELECT (signal_id) ON app.candidate_signal_events TO aia_maint;
GRANT DELETE ON app.candidate_signal_events TO aia_maint;
GRANT SELECT (id, user_id) ON app.candidate_signals TO aia_maint;
GRANT DELETE ON app.candidate_signals TO aia_maint;
GRANT SELECT (candidate_id, created_by, id) ON app.candidate_versions TO aia_maint;
GRANT DELETE ON app.candidate_versions TO aia_maint;
GRANT SELECT (account_id) ON app.cash_movements TO aia_maint;
GRANT DELETE ON app.cash_movements TO aia_maint;
GRANT SELECT (claim_id) ON app.claim_links TO aia_maint;
GRANT DELETE ON app.claim_links TO aia_maint;
GRANT SELECT (id, user_id) ON app.claims TO aia_maint;
GRANT DELETE ON app.claims TO aia_maint;
GRANT SELECT (report_id) ON app.daily_report_items TO aia_maint;
GRANT DELETE ON app.daily_report_items TO aia_maint;
GRANT SELECT (id, llm_call_id, user_id) ON app.daily_reports TO aia_maint;
GRANT DELETE ON app.daily_reports TO aia_maint;
GRANT SELECT (id, items, known_events, licence_id, user_id) ON app.data_snapshots TO aia_maint;
GRANT DELETE ON app.data_snapshots TO aia_maint;
GRANT SELECT (created_by, user_id) ON app.entitlement_overrides TO aia_maint;
GRANT UPDATE (created_by) ON app.entitlement_overrides TO aia_maint;
GRANT DELETE ON app.entitlement_overrides TO aia_maint;
GRANT SELECT (account_id) ON app.holdings TO aia_maint;
GRANT DELETE ON app.holdings TO aia_maint;
GRANT SELECT (id, user_id) ON app.import_batches TO aia_maint;
GRANT DELETE ON app.import_batches TO aia_maint;
GRANT SELECT (batch_id, storage_path) ON app.import_files TO aia_maint;
GRANT DELETE ON app.import_files TO aia_maint;
GRANT SELECT (id, user_id) ON app.import_mappings TO aia_maint;
GRANT DELETE ON app.import_mappings TO aia_maint;
GRANT SELECT (batch_id) ON app.import_rows TO aia_maint;
GRANT DELETE ON app.import_rows TO aia_maint;
GRANT SELECT (bound_username, created_by, id, revoked_by, used_by) ON app.invite_codes TO aia_maint;
GRANT UPDATE (bound_username, used_by) ON app.invite_codes TO aia_maint;
GRANT SELECT (id, target_id, target_type) ON app.llm_calls TO aia_maint;
GRANT UPDATE (request_body, request_hash, response_body, target_id, target_type, validation_errors) ON app.llm_calls TO aia_maint;
GRANT DELETE ON app.llm_calls TO aia_maint;
GRANT SELECT (created_by, id) ON app.llm_providers TO aia_maint;
GRANT UPDATE (created_by) ON app.llm_providers TO aia_maint;
GRANT SELECT (id, llm_call_ids, requested_by, reviewer_id) ON app.llm_strategy_drafts TO aia_maint;
GRANT UPDATE (reviewer_id) ON app.llm_strategy_drafts TO aia_maint;
GRANT SELECT (id, user_id, username_tried) ON app.login_attempts TO aia_maint;
GRANT DELETE ON app.login_attempts TO aia_maint;
GRANT SELECT (id, released_by, user_id) ON app.non_executable_reasons TO aia_maint;
GRANT UPDATE (released_by) ON app.non_executable_reasons TO aia_maint;
GRANT DELETE ON app.non_executable_reasons TO aia_maint;
GRANT SELECT (id, user_id) ON app.notification_channel_bindings TO aia_maint;
GRANT DELETE ON app.notification_channel_bindings TO aia_maint;
GRANT SELECT (binding_id, notification_id) ON app.notification_deliveries TO aia_maint;
GRANT DELETE ON app.notification_deliveries TO aia_maint;
GRANT SELECT (user_id) ON app.notification_preferences TO aia_maint;
GRANT DELETE ON app.notification_preferences TO aia_maint;
GRANT SELECT (id, target_id, user_id) ON app.notifications TO aia_maint;
GRANT UPDATE (target_id, target_route, target_type) ON app.notifications TO aia_maint;
GRANT DELETE ON app.notifications TO aia_maint;
GRANT SELECT (account_id) ON app.opening_positions TO aia_maint;
GRANT DELETE ON app.opening_positions TO aia_maint;
GRANT SELECT (plan_version_id) ON app.plan_conditions TO aia_maint;
GRANT DELETE ON app.plan_conditions TO aia_maint;
GRANT SELECT (id, user_id) ON app.plan_draft_confirmations TO aia_maint;
GRANT DELETE ON app.plan_draft_confirmations TO aia_maint;
GRANT SELECT (id, user_id) ON app.plan_drafts TO aia_maint;
GRANT DELETE ON app.plan_drafts TO aia_maint;
GRANT SELECT (id, plan_id) ON app.plan_versions TO aia_maint;
GRANT DELETE ON app.plan_versions TO aia_maint;
GRANT SELECT (created_by, id) ON app.prompt_templates TO aia_maint;
GRANT SELECT (changed_by, id) ON app.realtime_settings TO aia_maint;
GRANT SELECT (reason_id) ON app.reason_status_events TO aia_maint;
GRANT DELETE ON app.reason_status_events TO aia_maint;
GRANT SELECT (run_id) ON app.reconciliation_items TO aia_maint;
GRANT DELETE ON app.reconciliation_items TO aia_maint;
GRANT SELECT (account_id, id) ON app.reconciliation_runs TO aia_maint;
GRANT DELETE ON app.reconciliation_runs TO aia_maint;
GRANT SELECT (current_version_id, id, user_id) ON app.research_candidates TO aia_maint;
GRANT UPDATE (current_version_id) ON app.research_candidates TO aia_maint;
GRANT DELETE ON app.research_candidates TO aia_maint;
GRANT SELECT (review_id) ON app.review_versions TO aia_maint;
GRANT DELETE ON app.review_versions TO aia_maint;
GRANT SELECT (current_version_id, id, user_id) ON app.reviews TO aia_maint;
GRANT UPDATE (current_version_id) ON app.reviews TO aia_maint;
GRANT DELETE ON app.reviews TO aia_maint;
GRANT SELECT (id, user_id) ON app.risk_control_settings TO aia_maint;
GRANT DELETE ON app.risk_control_settings TO aia_maint;
GRANT SELECT (changed_by, id, setting_id, user_id) ON app.risk_control_settings_history TO aia_maint;
GRANT DELETE ON app.risk_control_settings_history TO aia_maint;
GRANT SELECT (id, user_id) ON app.risk_events TO aia_maint;
GRANT DELETE ON app.risk_events TO aia_maint;
GRANT SELECT (id, user_id) ON app.signal_events TO aia_maint;
GRANT DELETE ON app.signal_events TO aia_maint;
GRANT SELECT (id, owner_user_id) ON app.strategies TO aia_maint;
GRANT SELECT (created_by, id) ON app.strategy_card_versions TO aia_maint;
GRANT SELECT (id, owner_user_id) ON app.strategy_cards TO aia_maint;
GRANT SELECT (actor_id, id, instance_id) ON app.strategy_instance_events TO aia_maint;
GRANT DELETE ON app.strategy_instance_events TO aia_maint;
GRANT SELECT (id, user_id) ON app.strategy_instances TO aia_maint;
GRANT DELETE ON app.strategy_instances TO aia_maint;
GRANT SELECT (actor_id, id) ON app.strategy_lifecycle_events TO aia_maint;
GRANT SELECT (id, reviewer_id) ON app.strategy_promotion_reviews TO aia_maint;
GRANT UPDATE (reviewer_id) ON app.strategy_promotion_reviews TO aia_maint;
GRANT SELECT (id, user_id) ON app.strategy_runs TO aia_maint;
GRANT DELETE ON app.strategy_runs TO aia_maint;
GRANT SELECT (id, user_id) ON app.strategy_tracking_stats TO aia_maint;
GRANT DELETE ON app.strategy_tracking_stats TO aia_maint;
GRANT SELECT (id, lifecycle_changed_by, published_by) ON app.strategy_versions TO aia_maint;
GRANT SELECT (current_suggestion_id, id, user_id) ON app.suggestion_threads TO aia_maint;
GRANT UPDATE (current_suggestion_id) ON app.suggestion_threads TO aia_maint;
GRANT DELETE ON app.suggestion_threads TO aia_maint;
GRANT SELECT (suggestion_id) ON app.suggestion_tracking TO aia_maint;
GRANT DELETE ON app.suggestion_tracking TO aia_maint;
GRANT SELECT (id, user_id) ON app.suggestion_user_actions TO aia_maint;
GRANT DELETE ON app.suggestion_user_actions TO aia_maint;
GRANT SELECT (id, llm_call_id, user_id) ON app.suggestions TO aia_maint;
GRANT DELETE ON app.suggestions TO aia_maint;
GRANT SELECT (id, user_id) ON app.symbol_horizon_assessments TO aia_maint;
GRANT DELETE ON app.symbol_horizon_assessments TO aia_maint;
GRANT SELECT (id, user_id) ON app.trades TO aia_maint;
GRANT DELETE ON app.trades TO aia_maint;
GRANT SELECT (user_id) ON app.user_data_licence_cooldowns TO aia_maint;
GRANT DELETE ON app.user_data_licence_cooldowns TO aia_maint;
GRANT SELECT (user_id) ON app.user_data_licence_holds TO aia_maint;
GRANT DELETE ON app.user_data_licence_holds TO aia_maint;
GRANT SELECT (id, user_id) ON app.user_data_licences TO aia_maint;
GRANT DELETE ON app.user_data_licences TO aia_maint;
GRANT SELECT (id, user_id) ON app.user_profiles TO aia_maint;
GRANT DELETE ON app.user_profiles TO aia_maint;
GRANT SELECT (user_id) ON app.user_realtime_prefs TO aia_maint;
GRANT DELETE ON app.user_realtime_prefs TO aia_maint;
GRANT SELECT (id, user_id) ON app.user_restrictions TO aia_maint;
GRANT DELETE ON app.user_restrictions TO aia_maint;
GRANT SELECT (id, user_id) ON app.user_signal_states TO aia_maint;
GRANT DELETE ON app.user_signal_states TO aia_maint;
GRANT SELECT (user_id) ON app.user_strategy_weights TO aia_maint;
GRANT DELETE ON app.user_strategy_weights TO aia_maint;
GRANT SELECT (created_by, id, user_id) ON app.user_subscriptions TO aia_maint;
GRANT UPDATE (created_by) ON app.user_subscriptions TO aia_maint;
GRANT DELETE ON app.user_subscriptions TO aia_maint;
GRANT SELECT (id, reviewed_by, role, status, username) ON app.users TO aia_maint;
GRANT UPDATE (reviewed_by, status) ON app.users TO aia_maint;
GRANT DELETE ON app.users TO aia_maint;
GRANT SELECT (id, user_id) ON app.watchlist_items TO aia_maint;
GRANT DELETE ON app.watchlist_items TO aia_maint;
GRANT SELECT (id, user_id) ON ops.data_licence_events TO aia_maint;
GRANT UPDATE (licence_id, user_id) ON ops.data_licence_events TO aia_maint;
GRANT SELECT (dedup_key, licence_id, requester) ON ops.ingest_request_log TO aia_maint;
GRANT UPDATE (dedup_key, licence_id, requester) ON ops.ingest_request_log TO aia_maint;
GRANT SELECT (attempts, created_at, id, last_error, path) ON ops.pending_file_purges TO aia_maint;
GRANT UPDATE (attempts, last_attempt_at, last_error) ON ops.pending_file_purges TO aia_maint;
GRANT INSERT (attempts, last_attempt_at, last_error, path) ON ops.pending_file_purges TO aia_maint;
GRANT DELETE ON ops.pending_file_purges TO aia_maint;
COMMIT;
```

## 4. 核验查询（每行一个断言，ok 必须全部为 true）
```sql
-- aia_maint 权限核验：每行一个断言，ok 必须全部为 true（任何 false 即授权不合规）
WITH deny_sel(tbl, col) AS (VALUES
  ('app.users', 'password_hash'),
  ('app.user_data_licences', 'ciphertext'),
  ('app.user_data_licences', 'licence_hmac'),
  ('app.llm_providers', 'api_key_ciphertext'),
  ('app.notification_channel_bindings', 'target_ciphertext'),
  ('app.import_rows', 'raw_line'),
  ('app.llm_calls', 'request_body'),
  ('app.llm_calls', 'response_body'),
  ('app.user_data_licence_cooldowns', 'fingerprint')
), checks AS (
  SELECT 'no SELECT on ' || tbl || '.' || col AS check_name,
         NOT has_column_privilege('aia_maint', tbl, col, 'SELECT') AS ok
    FROM deny_sel WHERE to_regclass(tbl) IS NOT NULL
  UNION ALL SELECT 'no UPDATE on app.users.role', NOT has_column_privilege('aia_maint', 'app.users', 'role', 'UPDATE')
  UNION ALL SELECT 'no UPDATE on app.users.password_hash', NOT has_column_privilege('aia_maint', 'app.users', 'password_hash', 'UPDATE')
  UNION ALL SELECT 'no INSERT on app.users', NOT has_any_column_privilege('aia_maint', 'app.users', 'INSERT')
  -- 表级 SELECT/UPDATE/INSERT 会覆盖所有列（含将来新增的列）：一律不允许
  UNION ALL SELECT 'no table-level ' || p || ' on ' || c.oid::regclass,
         NOT has_table_privilege('aia_maint', c.oid, p)
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         CROSS JOIN unnest(ARRAY['SELECT', 'UPDATE', 'INSERT', 'TRUNCATE', 'REFERENCES', 'TRIGGER']) p
   WHERE n.nspname IN ('app', 'ops', 'market') AND c.relkind IN ('r', 'p')
  UNION ALL SELECT 'no default privileges for aia_maint',
         NOT EXISTS (SELECT 1 FROM pg_default_acl d, aclexplode(d.defaclacl) a
                      WHERE a.grantee = 'aia_maint'::regrole)
  UNION ALL SELECT 'aia_maint: no role memberships',
         NOT EXISTS (SELECT 1 FROM pg_auth_members WHERE member = 'aia_maint'::regrole)
  UNION ALL SELECT 'aia_maint: not superuser / no BYPASSRLS / no CREATEROLE',
         NOT (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb) FROM pg_roles r WHERE r.rolname = 'aia_maint'
  UNION ALL SELECT 'can UPDATE app.users.status (purge marker)', has_column_privilege('aia_maint', 'app.users', 'status', 'UPDATE')
  UNION ALL SELECT 'can DELETE app.users', has_table_privilege('aia_maint', 'app.users', 'DELETE')
  UNION ALL SELECT 'can INSERT app.audit_logs(action)', has_column_privilege('aia_maint', 'app.audit_logs', 'action', 'INSERT')
)
SELECT check_name, ok FROM checks ORDER BY ok, check_name;
```
- 用法：`psql ... -f verify.sql`，任何 `ok = f` 即不合规。也可加 `WHERE NOT ok` 只看失败项（应为 0 行）。
- 隔离库实测：756 条断言全 true。

## 5. 隔离库验证（全部仅在 be-b03a-pg，未连共享库、未调麦蕊）
| 自测（以 aia_maint + 恰好上述授权运行） | 结果 |
|---|---|
| tb16core_min（aia_maint 用 *_FILE DSN 登录：dry-run、--execute、retry pending、blocked admin、门控测试；授权后先跑 verify.sql） | 94 passed / 0 failed |
| tb10_min（SET LOCAL ROLE aia_maint 执行完整清除） | 57 passed / 0 failed |
| 反例：aia_maint `SELECT password_hash` / `SELECT ciphertext` / `SELECT *` from users / `UPDATE users SET role` / `SELECT api_key_ciphertext` | 全部 permission denied |
- tb16core 两项门控测试的期望改为 `permission denied`（最小授权下更早被拒：aia_maint 无 INSERT users、无 UPDATE users.display_name），
  原本靠触发器报错拦截，现在是权限层拦截，更严。

## 6. 代码改动（需要了，已提交 78c5281）
- `app/cli/delete_user_data.py::_market_licence_tables` 改查 `pg_catalog` 而非 `information_schema.columns`：
  后者只列出当前角色有权限的列，最小授权下将来新增的 market 表会被**静默跳过**；现在照样发现，随后的 count/DELETE
  因缺权限报错、整笔回滚（失败即响）。

- 全量回归（runall，含 pytest）：自测各组 0 失败；pytest 887 passed / 2 failed，两项均与本改动无关：
  `test_snapshot_equals_plan_block[horizon_classifier]`（plan/分类器 yaml 的 C5 单位变更，T-R11a 处理）与
  `test_d_grants_who_may_insert`（读 deploy/db/roles/grants.sql，运维未提交改动）；api 自测 1 项 `enum keys == contract §3`（契约 #29/#30 新枚举，T-B50 范围）。

## 7. 给运维 / 后续规则
- 运维：用 §3 替换 grants.sql 的 `$maint` 块（当前块是 ALL TABLES 表级 + 默认权限，过宽），aia_maint 的列拒绝清单（grants.sql `maint_deny`）补上 §1 的全部列；部署后跑 §4。注意：aia_api 的 `aia_deny` 只放 licence 密文，不扩展（T-O11 裁定，见 reports/T-O11-aia_deny-ruling.md）。
- **新表规则**：迁移若新增带 user FK / source_licence_id 的表，须同时在此清单加列级授权；未加时 CLI dry-run/execute 会报
  permission denied（不会静默漏删）。market 表出现 `source_licence_id` 时需加 `USAGE ON SCHEMA market` + `SELECT(source_licence_id), DELETE`。
- 默认 PUBLIC 对函数有 EXECUTE；若运维对函数 `REVOKE ... FROM PUBLIC`，§3 已显式授予这 10 个函数。
