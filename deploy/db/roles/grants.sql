-- 分库角色与列级授权（T-O10）。幂等：每次 compose up 在 migrate、timescale-apply 之后由 db-roles 服务执行。
-- 以库属主（POSTGRES_USER，下称 owner = current_user）连接执行；owner 继续持有全部对象，migrate 仍用 owner。
--   aia_api    ：业务 schema 的表/视图 SELECT/INSERT/UPDATE/DELETE、序列、函数；
--                但下表 deny 列表里的“密文列”一律不可 SELECT（列级授权：同表其余列可 SELECT，表级 INSERT/UPDATE 保留，
--                api 只用公钥封装后写入、注销时置空，从不读回；T-B45“api 不读证书密文”）。
--   aia_ingest ：同上且全列可读（ingest 持私钥，需要读密文解封）。
--   两者对 ops.pending_file_purges（待清文件队列，path 含 uid）没有任何权限（T-O11，评审 45589c2 m3、plan §7.3）。
--   aia_maint  ：只给删除用户数据 CLI（app.cli.delete_user_data）用，api/ingest 进程不持有其凭据（T-O11，plan §7.3
--                “purging 的写入权”）。只有 0013 的触发器认它能把 app.users.status 写成 purging；对其他不可变表
--                它和普通角色一样受触发器约束。权限只到 CLI 必需：app 全表 SELECT/UPDATE/DELETE（删除/匿名化/解除关联）、
--                app.audit_logs INSERT（admin.user_data_deleted）、ops.data_licence_events / ops.ingest_request_log
--                SELECT/UPDATE/DELETE（匿名化）、ops.pending_file_purges 增删改查、market 全表 SELECT/DELETE
--                （按 source_licence_id 删）。不给 CREATE/TRUNCATE/REFERENCES/TRIGGER、INSERT（audit/pending 以外）、
--                SUPERUSER/BYPASSRLS、任何角色成员身份；NOINHERIT。
-- 口令不在本文件：apply-roles.sh 以 psql 变量 :'api_pw' / :'ingest_pw' / :'maint_pw' 传入（来自 secret 文件，不经环境变量、不入库）。
-- 新迁移若新增“密文列”，把 schema.table.column 加进 deny 列表（下方两处 aia_deny 数组保持一致）。
\set ON_ERROR_STOP on
SET client_min_messages = notice;

DO $roles$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aia_api') THEN
    CREATE ROLE aia_api LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aia_ingest') THEN
    CREATE ROLE aia_ingest LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aia_maint') THEN
    CREATE ROLE aia_maint LOGIN;
  END IF;
END
$roles$;

ALTER ROLE aia_api    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT;
ALTER ROLE aia_ingest LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT;
ALTER ROLE aia_maint  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;

-- 口令：本会话关闭语句日志，避免 ALTER ROLE ... PASSWORD 进服务器日志。
SET log_statement = 'none';
SET log_min_duration_statement = -1;
ALTER ROLE aia_api    PASSWORD :'api_pw';
ALTER ROLE aia_ingest PASSWORD :'ingest_pw';
ALTER ROLE aia_maint  PASSWORD :'maint_pw';
RESET log_min_duration_statement;
RESET log_statement;

-- T-O11（架构师细化裁定）：aia_maint 的成员关系必须在任何授权和自检之前撤清——若 aia_api / aia_ingest
-- 是 aia_maint 的成员，它们就能经 aia_maint 读到密文列、动待清队列，后面 $grants$ 的自检也会先报错。
DO $maint_members$
DECLARE
  r record;
BEGIN
  -- 不允许任何角色成员身份（NOINHERIT 之外再收一道）。PG16 起成员关系按授予者分别记录，
  -- 所以逐条带 GRANTED BY 撤销（apply-roles 以库超级用户身份执行，可代任何授予者撤销）。
  -- (1) aia_maint 自己不属于任何角色
  FOR r IN SELECT g.rolname AS grp, gr.rolname AS grantor
             FROM pg_auth_members m
             JOIN pg_roles g  ON g.oid  = m.roleid
             JOIN pg_roles gr ON gr.oid = m.grantor
            WHERE m.member = (SELECT oid FROM pg_roles WHERE rolname = 'aia_maint') LOOP
    EXECUTE format('REVOKE %I FROM aia_maint GRANTED BY %I CASCADE', r.grp, r.grantor);
  END LOOP;
  -- (2) 任何角色（至少 aia_api、aia_ingest）都不得是 aia_maint 的成员：否则 api/ingest 进程
  --     可 SET ROLE aia_maint 拿到删除权限。撤掉 aia_maint 的全部直接成员，间接链也随之断开。
  FOR r IN SELECT mb.rolname AS member, gr.rolname AS grantor
             FROM pg_auth_members m
             JOIN pg_roles mb ON mb.oid = m.member
             JOIN pg_roles gr ON gr.oid = m.grantor
            WHERE m.roleid = (SELECT oid FROM pg_roles WHERE rolname = 'aia_maint') LOOP
    -- 前面某条 CASCADE 可能已连带撤掉这一条
    CONTINUE WHEN NOT EXISTS (SELECT 1 FROM pg_auth_members m2
                               WHERE m2.roleid = (SELECT oid FROM pg_roles WHERE rolname = 'aia_maint')
                                 AND m2.member = (SELECT oid FROM pg_roles WHERE rolname = r.member)
                                 AND m2.grantor = (SELECT oid FROM pg_roles WHERE rolname = r.grantor));
    -- CASCADE：连同经其 ADMIN OPTION 转授出去的成员关系一起撤
    EXECUTE format('REVOKE aia_maint FROM %I GRANTED BY %I CASCADE', r.member, r.grantor);
    RAISE NOTICE 'db-roles: 已撤销 % 的 aia_maint 成员身份', r.member;
  END LOOP;
END
$maint_members$;

DO $grants$
DECLARE
  owner_role text := current_user;
  -- 密文列（aia_api 不可 SELECT）：schema.table.column
  aia_deny   text[] := ARRAY['app.user_data_licences.ciphertext'];
  s          text;
  r          record;
  allowed    text;
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO aia_api, aia_ingest', current_database());

  -- 业务 schema = owner 拥有的非系统 schema（app、ops、market、evaluation …；新 schema 下次 up 自动覆盖）。
  FOR s IN
    SELECT n.nspname FROM pg_namespace n
     WHERE n.nspowner = (SELECT oid FROM pg_roles WHERE rolname = owner_role)
       AND n.nspname NOT LIKE 'pg\_%' AND n.nspname <> 'information_schema'
       AND n.nspname NOT LIKE '\_timescaledb%' AND n.nspname NOT LIKE 'timescaledb\_%'
       AND n.nspname <> 'public'
     ORDER BY 1
  LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO aia_api, aia_ingest', s);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO aia_api, aia_ingest', s);
    EXECUTE format('GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA %I TO aia_api, aia_ingest', s);
    EXECUTE format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA %I TO aia_api, aia_ingest', s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO aia_api, aia_ingest', owner_role, s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO aia_api, aia_ingest', owner_role, s);
  END LOOP;

  -- 列级：对每张含 deny 列的表，撤掉 aia_api 的表级 SELECT 与密文列 SELECT，只授其余列的 SELECT。
  FOR r IN
    SELECT c.oid AS relid, n.nspname, c.relname,
           array_agg(a.attname ORDER BY a.attnum) FILTER (WHERE format('%s.%s.%s', n.nspname, c.relname, a.attname) = ANY (aia_deny)) AS denied
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
      JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
     WHERE c.relkind IN ('r', 'p')
     GROUP BY c.oid, n.nspname, c.relname
    HAVING bool_or(format('%s.%s.%s', n.nspname, c.relname, a.attname) = ANY (aia_deny))
  LOOP
    EXECUTE format('REVOKE SELECT ON TABLE %I.%I FROM aia_api', r.nspname, r.relname);
    EXECUTE format('REVOKE SELECT (%s) ON TABLE %I.%I FROM aia_api',
                   (SELECT string_agg(quote_ident(d), ', ') FROM unnest(r.denied) d), r.nspname, r.relname);
    SELECT string_agg(quote_ident(a.attname), ', ' ORDER BY a.attnum) INTO allowed
      FROM pg_attribute a
     WHERE a.attrelid = r.relid AND a.attnum > 0 AND NOT a.attisdropped AND NOT (a.attname = ANY (r.denied));
    EXECUTE format('GRANT SELECT (%s) ON TABLE %I.%I TO aia_api', allowed, r.nspname, r.relname);
    RAISE NOTICE 'db-roles: aia_api 不可读 %.%(%)', r.nspname, r.relname, array_to_string(r.denied, ',');
  END LOOP;

  -- 自检：deny 列表里的列必须存在（迁移未到时只告警，便于在旧库上先跑）；aia_api 对它们必须无 SELECT。
  FOR s IN SELECT unnest(aia_deny) LOOP
    IF to_regclass(split_part(s, '.', 1) || '.' || split_part(s, '.', 2)) IS NULL THEN
      RAISE WARNING 'db-roles: deny 列 % 所在表不存在（迁移未到？）', s;
    ELSIF has_column_privilege('aia_api', split_part(s, '.', 1) || '.' || split_part(s, '.', 2), split_part(s, '.', 3), 'SELECT') THEN
      RAISE EXCEPTION 'db-roles: aia_api 仍可 SELECT %', s;
    END IF;
  END LOOP;
END
$grants$;

-- T-O11：待清文件队列只给 aia_maint（上面的 ALL TABLES 授权与默认权限会把它也授给 api/ingest，这里每次都撤回）。
DO $purges$
DECLARE
  seq record;
BEGIN
  IF to_regclass('ops.pending_file_purges') IS NULL THEN
    RAISE WARNING 'db-roles: ops.pending_file_purges 不存在（迁移 0011 未到？），跳过撤权';
    RETURN;
  END IF;
  REVOKE ALL ON TABLE ops.pending_file_purges FROM aia_api, aia_ingest;
  FOR seq IN
    SELECT DISTINCT format('%I.%I', sn.nspname, s.relname) AS q
      FROM pg_depend d
      JOIN pg_class s ON s.oid = d.objid AND s.relkind = 'S'
      JOIN pg_namespace sn ON sn.oid = s.relnamespace
     WHERE d.refobjid = 'ops.pending_file_purges'::regclass AND d.deptype IN ('a', 'i')
  LOOP
    EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM aia_api, aia_ingest', seq.q);
  END LOOP;
  RAISE NOTICE 'db-roles: aia_api、aia_ingest 对 ops.pending_file_purges 无任何权限';
END
$purges$;

-- T-A04 ④（架构师裁定，review-028c077 M1）：worker 改用 aia_api 连接，不再用库属主。
-- worker 任务实际读写的表（app/workers/jobs.py TASKS），只补 DML、不给 DDL：
--   licences.purge_expired_cooldowns      → app.user_data_licence_cooldowns：SELECT、DELETE
--   imports.purge_preview_rows（9e693b2） → app.import_rows：SELECT、DELETE；app.import_batches：SELECT
--   imports.purge_expired_raw_files        → app.import_files：SELECT（含 FOR UPDATE SKIP LOCKED），UPDATE (deleted_at, storage_path)
-- 上面 $grants$ 的 ALL TABLES 授权目前已覆盖这些权限；这里显式再授一遍并自检，作为 worker 的依赖声明：
-- 将来收窄 aia_api 时这里会报错而不是让 worker 静默失效。aia_api 仍读不到密文列（$grants$ 的 aia_deny）。
DO $worker$
DECLARE
  spec text[] := ARRAY[
    'app.user_data_licence_cooldowns|SELECT|', 'app.user_data_licence_cooldowns|DELETE|',
    'app.import_rows|SELECT|', 'app.import_rows|DELETE|',
    'app.import_batches|SELECT|',
    'app.import_files|SELECT|', 'app.import_files|UPDATE|deleted_at,storage_path'];
  e text; t text; p text; cols text; c text; s text;
BEGIN
  FOREACH e IN ARRAY spec LOOP
    t := split_part(e, '|', 1); p := split_part(e, '|', 2); cols := split_part(e, '|', 3);
    IF to_regclass(t) IS NULL THEN
      RAISE WARNING 'db-roles: worker 用表 % 不存在（迁移未到？），跳过', t;
      CONTINUE;
    END IF;
    IF cols = '' THEN
      EXECUTE format('GRANT %s ON TABLE %s TO aia_api', p, t);
      IF NOT has_table_privilege('aia_api', t, p) THEN
        RAISE EXCEPTION 'db-roles: aia_api 缺少 worker 所需的 % ON %', p, t;
      END IF;
    ELSE
      EXECUTE format('GRANT %s (%s) ON TABLE %s TO aia_api', p,
                     (SELECT string_agg(quote_ident(x), ', ') FROM unnest(string_to_array(cols, ',')) x), t);
      FOREACH c IN ARRAY string_to_array(cols, ',') LOOP
        IF NOT has_column_privilege('aia_api', t, c, p) THEN
          RAISE EXCEPTION 'db-roles: aia_api 缺少 worker 所需的 %(%) ON %', p, c, t;
        END IF;
      END LOOP;
    END IF;
  END LOOP;
  -- 不给 DDL：aia_api 不拥有任何对象、在业务 schema 与库上无 CREATE、对任何表无 TRUNCATE/REFERENCES/TRIGGER
  IF EXISTS (SELECT 1 FROM pg_class WHERE relowner = 'aia_api'::regrole)
     OR EXISTS (SELECT 1 FROM pg_namespace WHERE nspowner = 'aia_api'::regrole) THEN
    RAISE EXCEPTION 'db-roles: aia_api 拥有表或 schema（不得有 DDL 能力）';
  END IF;
  IF has_database_privilege('aia_api', current_database(), 'CREATE') THEN
    RAISE EXCEPTION 'db-roles: aia_api 对库有 CREATE';
  END IF;
  FOR s IN SELECT n.nspname FROM pg_namespace n
            WHERE n.nspname NOT LIKE 'pg\_%' AND n.nspname <> 'information_schema' LOOP
    IF has_schema_privilege('aia_api', s, 'CREATE') THEN
      RAISE EXCEPTION 'db-roles: aia_api 在 schema % 上有 CREATE', s;
    END IF;
  END LOOP;
  IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               CROSS JOIN unnest(ARRAY['TRUNCATE','REFERENCES','TRIGGER']) pr
              WHERE n.nspname IN ('app','ops','market') AND c.relkind IN ('r','p')
                AND has_table_privilege('aia_api', c.oid, pr)) THEN
    RAISE EXCEPTION 'db-roles: aia_api 有表级 TRUNCATE/REFERENCES/TRIGGER';
  END IF;
  RAISE NOTICE 'db-roles: worker（aia_api）所需 DML 已就位，无 DDL';
END
$worker$;

-- T-O11：aia_maint（删除用户数据 CLI 专用）——列级最小授权（升级部署门槛）。
-- 清单来源：后端 reports/aia_maint-grants.md §3（78c5281；由 CLI 实际语句的 RTEPermissionInfo 采集）。
--   SELECT / UPDATE / INSERT 只按列授予；DELETE 是表级权限，只在清单里的表上给；不给任何表级 SELECT/UPDATE/INSERT、
--   不给序列、不给默认权限（新表不会自动获得权限：迁移新增带 user FK 的表，须后端更新清单，否则 CLI 报 permission denied，不会静默漏删）。
--   market：按后端 §7 规则，凡带 source_licence_id 列的表，只给 USAGE ON SCHEMA market + SELECT(source_licence_id) + DELETE。
-- 整段在一个 DO 里：先撤后授，事务内完成，不留中间态。表或列在旧库上不存在时只告警（迁移未到）。
DO $maint$
DECLARE
  owner_role text := current_user;
  -- '表|权限|列,列'；DELETE 行的列为空（表级）
  spec text[] := ARRAY[
    'app.account_events|SELECT|account_id',
    'app.account_events|DELETE|',
    'app.account_reviews|SELECT|admin_id,id,user_id',
    'app.account_reviews|UPDATE|admin_id,reason,user_id',
    'app.accounts|SELECT|id,user_id',
    'app.accounts|DELETE|',
    'app.action_plans|SELECT|current_version_id,id,user_id',
    'app.action_plans|UPDATE|current_version_id',
    'app.action_plans|DELETE|',
    'app.alert_rules|SELECT|id,user_id',
    'app.alert_rules|DELETE|',
    'app.alerts|SELECT|id,user_id',
    'app.alerts|DELETE|',
    'app.audit_logs|SELECT|actor_id,detail,ip_hash,target_id',
    'app.audit_logs|UPDATE|actor_id,detail,ip_hash,target_id',
    'app.audit_logs|INSERT|action,actor_id,actor_role,detail,target_id,target_type',
    'app.broker_position_snapshot_items|SELECT|snapshot_id',
    'app.broker_position_snapshot_items|DELETE|',
    'app.broker_position_snapshots|SELECT|account_id,id',
    'app.broker_position_snapshots|DELETE|',
    'app.candidate_signal_events|SELECT|signal_id',
    'app.candidate_signal_events|DELETE|',
    'app.candidate_signals|SELECT|id,user_id',
    'app.candidate_signals|DELETE|',
    'app.candidate_versions|SELECT|candidate_id,created_by,id',
    'app.candidate_versions|DELETE|',
    'app.cash_movements|SELECT|account_id',
    'app.cash_movements|DELETE|',
    'app.claim_links|SELECT|claim_id',
    'app.claim_links|DELETE|',
    'app.claims|SELECT|id,user_id',
    'app.claims|DELETE|',
    'app.daily_report_items|SELECT|report_id',
    'app.daily_report_items|DELETE|',
    'app.daily_reports|SELECT|id,llm_call_id,user_id',
    'app.daily_reports|DELETE|',
    'app.data_snapshots|SELECT|id,items,known_events,licence_id,user_id',
    'app.data_snapshots|DELETE|',
    'app.entitlement_overrides|SELECT|created_by,user_id',
    'app.entitlement_overrides|UPDATE|created_by',
    'app.entitlement_overrides|DELETE|',
    'app.holdings|SELECT|account_id',
    'app.holdings|DELETE|',
    'app.import_batches|SELECT|id,user_id',
    'app.import_batches|DELETE|',
    'app.import_files|SELECT|batch_id,storage_path',
    'app.import_files|DELETE|',
    'app.import_mappings|SELECT|id,user_id',
    'app.import_mappings|DELETE|',
    'app.import_rows|SELECT|batch_id',
    'app.import_rows|DELETE|',
    'app.invite_codes|SELECT|bound_username,created_by,id,revoked_by,used_by',
    'app.invite_codes|UPDATE|bound_username,used_by',
    'app.llm_calls|SELECT|id,target_id,target_type',
    'app.llm_calls|UPDATE|request_body,request_hash,response_body,target_id,target_type,validation_errors',
    'app.llm_calls|DELETE|',
    'app.llm_providers|SELECT|created_by,id',
    'app.llm_providers|UPDATE|created_by',
    'app.llm_strategy_drafts|SELECT|id,llm_call_ids,requested_by,reviewer_id',
    'app.llm_strategy_drafts|UPDATE|reviewer_id',
    'app.login_attempts|SELECT|id,user_id,username_tried',
    'app.login_attempts|DELETE|',
    'app.non_executable_reasons|SELECT|id,released_by,user_id',
    'app.non_executable_reasons|UPDATE|released_by',
    'app.non_executable_reasons|DELETE|',
    'app.notification_channel_bindings|SELECT|id,user_id',
    'app.notification_channel_bindings|DELETE|',
    'app.notification_deliveries|SELECT|binding_id,notification_id',
    'app.notification_deliveries|DELETE|',
    'app.notification_preferences|SELECT|user_id',
    'app.notification_preferences|DELETE|',
    'app.notifications|SELECT|id,target_id,user_id',
    'app.notifications|UPDATE|target_id,target_route,target_type',
    'app.notifications|DELETE|',
    'app.opening_positions|SELECT|account_id',
    'app.opening_positions|DELETE|',
    'app.plan_conditions|SELECT|plan_version_id',
    'app.plan_conditions|DELETE|',
    'app.plan_draft_confirmations|SELECT|id,user_id',
    'app.plan_draft_confirmations|DELETE|',
    'app.plan_drafts|SELECT|id,user_id',
    'app.plan_drafts|DELETE|',
    'app.plan_versions|SELECT|id,plan_id',
    'app.plan_versions|DELETE|',
    'app.prompt_templates|SELECT|created_by,id',
    'app.realtime_settings|SELECT|changed_by,id',
    'app.reason_status_events|SELECT|reason_id',
    'app.reason_status_events|DELETE|',
    'app.reconciliation_items|SELECT|run_id',
    'app.reconciliation_items|DELETE|',
    'app.reconciliation_runs|SELECT|account_id,id',
    'app.reconciliation_runs|DELETE|',
    'app.research_candidates|SELECT|current_version_id,id,user_id',
    'app.research_candidates|UPDATE|current_version_id',
    'app.research_candidates|DELETE|',
    'app.review_versions|SELECT|review_id',
    'app.review_versions|DELETE|',
    'app.reviews|SELECT|current_version_id,id,user_id',
    'app.reviews|UPDATE|current_version_id',
    'app.reviews|DELETE|',
    'app.risk_control_settings|SELECT|id,user_id',
    'app.risk_control_settings|DELETE|',
    'app.risk_control_settings_history|SELECT|changed_by,id,setting_id,user_id',
    'app.risk_control_settings_history|DELETE|',
    'app.risk_events|SELECT|id,user_id',
    'app.risk_events|DELETE|',
    'app.signal_events|SELECT|id,user_id',
    'app.signal_events|DELETE|',
    'app.strategies|SELECT|id,owner_user_id',
    'app.strategy_card_versions|SELECT|created_by,id',
    'app.strategy_cards|SELECT|id,owner_user_id',
    'app.strategy_instance_events|SELECT|actor_id,id,instance_id',
    'app.strategy_instance_events|DELETE|',
    'app.strategy_instances|SELECT|id,user_id',
    'app.strategy_instances|DELETE|',
    'app.strategy_lifecycle_events|SELECT|actor_id,id',
    'app.strategy_promotion_reviews|SELECT|id,reviewer_id',
    'app.strategy_promotion_reviews|UPDATE|reviewer_id',
    'app.strategy_runs|SELECT|id,user_id',
    'app.strategy_runs|DELETE|',
    'app.strategy_tracking_stats|SELECT|id,user_id',
    'app.strategy_tracking_stats|DELETE|',
    'app.strategy_versions|SELECT|id,lifecycle_changed_by,published_by',
    'app.suggestion_threads|SELECT|current_suggestion_id,id,user_id',
    'app.suggestion_threads|UPDATE|current_suggestion_id',
    'app.suggestion_threads|DELETE|',
    'app.suggestion_tracking|SELECT|suggestion_id',
    'app.suggestion_tracking|DELETE|',
    'app.suggestion_user_actions|SELECT|id,user_id',
    'app.suggestion_user_actions|DELETE|',
    'app.suggestions|SELECT|id,llm_call_id,user_id',
    'app.suggestions|DELETE|',
    'app.symbol_horizon_assessments|SELECT|id,user_id',
    'app.symbol_horizon_assessments|DELETE|',
    'app.trades|SELECT|id,user_id',
    'app.trades|DELETE|',
    'app.user_data_licence_cooldowns|SELECT|user_id',
    'app.user_data_licence_cooldowns|DELETE|',
    'app.user_data_licence_holds|SELECT|user_id',
    'app.user_data_licence_holds|DELETE|',
    'app.user_data_licences|SELECT|id,user_id',
    'app.user_data_licences|DELETE|',
    'app.user_profiles|SELECT|id,user_id',
    'app.user_profiles|DELETE|',
    'app.user_realtime_prefs|SELECT|user_id',
    'app.user_realtime_prefs|DELETE|',
    'app.user_restrictions|SELECT|id,user_id',
    'app.user_restrictions|DELETE|',
    'app.user_signal_states|SELECT|id,user_id',
    'app.user_signal_states|DELETE|',
    'app.user_strategy_weights|SELECT|user_id',
    'app.user_strategy_weights|DELETE|',
    'app.user_subscriptions|SELECT|created_by,id,user_id',
    'app.user_subscriptions|UPDATE|created_by',
    'app.user_subscriptions|DELETE|',
    'app.users|SELECT|id,reviewed_by,role,status,username',
    'app.users|UPDATE|reviewed_by,status',
    'app.users|DELETE|',
    'app.watchlist_items|SELECT|id,user_id',
    'app.watchlist_items|DELETE|',
    'ops.data_licence_events|SELECT|id,user_id',
    'ops.data_licence_events|UPDATE|licence_id,user_id',
    'ops.ingest_request_log|SELECT|dedup_key,licence_id,requester',
    'ops.ingest_request_log|UPDATE|dedup_key,licence_id,requester',
    'ops.pending_file_purges|SELECT|attempts,created_at,id,last_error,path',
    'ops.pending_file_purges|UPDATE|attempts,last_attempt_at,last_error',
    'ops.pending_file_purges|INSERT|attempts,last_attempt_at,last_error,path',
    'ops.pending_file_purges|DELETE|'
  ];
  funcs text[] := ARRAY[
    'app.purge_ref_ids(uuid[])', 'app.purge_target_ref(text, uuid[])', 'app.purge_json_mentions(jsonb, text[])',
    'app.purge_scrub_json(jsonb, text[])', 'app.purge_scrub_json(jsonb)', 'app.purge_pii_key(text)',
    'app.purge_permits(text, text, jsonb, jsonb)', 'app.purge_user_ids()', 'app.purge_row_owner(text, jsonb)',
    'app.purge_anonymize_ok(text, jsonb, jsonb, uuid[])'];
  -- 不可读的列（后端 §1）；另有 users.role / users.password_hash 不可写
  maint_deny text[] := ARRAY[
    'app.users.password_hash', 'app.user_data_licences.ciphertext', 'app.user_data_licences.licence_hmac',
    'app.llm_providers.api_key_ciphertext', 'app.notification_channel_bindings.target_ciphertext',
    'app.import_rows.raw_line', 'app.llm_calls.request_body', 'app.llm_calls.response_body',
    'app.user_data_licence_cooldowns.fingerprint'];
  del_ok  text[] := ARRAY[]::text[];   -- 允许 DELETE 的表（清单 + market 证书表），自检用
  t text; s text; p text; cols text[]; have text[]; r record; e text;
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO aia_maint', current_database());
  -- 成员关系已在授权之前由 $maint_members$ 撤清（见文件前部），这里只在末尾自检。

  -- 0. 撤清（REVOKE ... ON TABLE 同时撤掉该表全部列级授权）+ 旧版遗留的默认权限
  FOREACH s IN ARRAY ARRAY['app', 'ops', 'market'] LOOP
    CONTINUE WHEN to_regnamespace(s) IS NULL;
    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM aia_maint', s);
    EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM aia_maint', s);
    EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA %I FROM aia_maint', s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL ON TABLES FROM aia_maint', owner_role, s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL ON SEQUENCES FROM aia_maint', owner_role, s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL ON FUNCTIONS FROM aia_maint', owner_role, s);
    EXECUTE format('REVOKE ALL ON SCHEMA %I FROM aia_maint', s);
  END LOOP;
  FOREACH s IN ARRAY ARRAY['app', 'ops'] LOOP
    IF to_regnamespace(s) IS NOT NULL THEN EXECUTE format('GRANT USAGE ON SCHEMA %I TO aia_maint', s); END IF;
  END LOOP;

  -- 1. 函数（都是 SECURITY INVOKER；PUBLIC 默认也有 EXECUTE，这里显式给，防将来收回 PUBLIC）
  FOREACH t IN ARRAY funcs LOOP
    IF to_regprocedure(t) IS NULL THEN RAISE WARNING 'db-roles: 函数 % 不存在，aia_maint 跳过', t; CONTINUE; END IF;
    EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO aia_maint', to_regprocedure(t));
  END LOOP;

  -- 2. 表 / 列
  FOREACH e IN ARRAY spec LOOP
    t := split_part(e, '|', 1); p := split_part(e, '|', 2);
    IF to_regclass(t) IS NULL THEN RAISE WARNING 'db-roles: % 不存在（迁移未到？），aia_maint 跳过 %', t, p; CONTINUE; END IF;
    IF p = 'DELETE' THEN
      EXECUTE format('GRANT DELETE ON TABLE %s TO aia_maint', to_regclass(t));
      del_ok := del_ok || to_regclass(t)::text;
      CONTINUE;
    END IF;
    cols := string_to_array(split_part(e, '|', 3), ',');
    SELECT array_agg(c ORDER BY c) INTO have FROM unnest(cols) c
     WHERE EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = to_regclass(t) AND a.attname = c AND a.attnum > 0 AND NOT a.attisdropped);
    IF coalesce(cardinality(have), 0) < cardinality(cols) THEN
      RAISE WARNING 'db-roles: % 缺列 %（迁移未到？），aia_maint 只授存在的列', t,
        (SELECT string_agg(c, ',') FROM unnest(cols) c WHERE NOT (c = ANY (coalesce(have, '{}'))));
    END IF;
    CONTINUE WHEN have IS NULL;
    EXECUTE format('GRANT %s (%s) ON TABLE %s TO aia_maint', p,
                   (SELECT string_agg(quote_ident(c), ', ') FROM unnest(have) c), to_regclass(t));
  END LOOP;

  -- 3. market：带 source_licence_id 的表（不含分区子表）
  FOR r IN
    SELECT c.oid::regclass::text AS q FROM pg_attribute a
      JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'market' AND c.relkind IN ('r', 'p') AND NOT c.relispartition
       AND a.attname = 'source_licence_id' AND a.attnum > 0 AND NOT a.attisdropped
     ORDER BY 1
  LOOP
    GRANT USAGE ON SCHEMA market TO aia_maint;
    EXECUTE format('GRANT SELECT (source_licence_id) ON TABLE %s TO aia_maint', r.q);
    EXECUTE format('GRANT DELETE ON TABLE %s TO aia_maint', r.q);
    del_ok := del_ok || r.q;
    RAISE NOTICE 'db-roles: aia_maint 可按 source_licence_id 删除 %', r.q;
  END LOOP;

  -- 4. 自检（失败即整段回滚）
  FOR r IN
    SELECT c.oid::regclass::text AS q, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S') AND n.nspname IN ('app', 'ops', 'market')
  LOOP
    IF r.relkind = 'S' THEN
      IF has_sequence_privilege('aia_maint', r.q, 'USAGE') OR has_sequence_privilege('aia_maint', r.q, 'SELECT')
         OR has_sequence_privilege('aia_maint', r.q, 'UPDATE') THEN
        RAISE EXCEPTION 'db-roles: aia_maint 不应有序列权限 %', r.q;
      END IF;
      CONTINUE;
    END IF;
    -- 表级 SELECT/INSERT/UPDATE 会覆盖全部列（含将来新增的列）：一律不允许
    FOREACH p IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
      IF has_table_privilege('aia_maint', r.q, p) THEN
        RAISE EXCEPTION 'db-roles: aia_maint 不应有表级 % ON %', p, r.q;
      END IF;
    END LOOP;
    IF has_table_privilege('aia_maint', r.q, 'DELETE') AND NOT (r.q = ANY (del_ok)) THEN
      RAISE EXCEPTION 'db-roles: aia_maint 不应有 DELETE ON %（不在清单）', r.q;
    END IF;
    IF has_any_column_privilege('aia_maint', r.q, 'INSERT') AND r.q NOT IN ('app.audit_logs', 'ops.pending_file_purges') THEN
      RAISE EXCEPTION 'db-roles: aia_maint 不应有 INSERT ON %', r.q;
    END IF;
  END LOOP;
  FOREACH e IN ARRAY maint_deny LOOP
    t := split_part(e, '.', 1) || '.' || split_part(e, '.', 2);
    CONTINUE WHEN to_regclass(t) IS NULL;
    IF has_column_privilege('aia_maint', t, split_part(e, '.', 3), 'SELECT') THEN
      RAISE EXCEPTION 'db-roles: aia_maint 不应可 SELECT %', e;
    END IF;
  END LOOP;
  IF to_regclass('app.users') IS NOT NULL AND (has_column_privilege('aia_maint', 'app.users', 'role', 'UPDATE')
       OR has_column_privilege('aia_maint', 'app.users', 'password_hash', 'UPDATE')) THEN
    RAISE EXCEPTION 'db-roles: aia_maint 不应可 UPDATE app.users.role / password_hash';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_default_acl d, aclexplode(d.defaclacl) a WHERE a.grantee = 'aia_maint'::regrole) THEN
    RAISE EXCEPTION 'db-roles: aia_maint 仍有默认权限';
  END IF;
  IF to_regclass('ops.pending_file_purges') IS NOT NULL THEN
    FOREACH t IN ARRAY ARRAY['aia_api', 'aia_ingest'] LOOP
      FOREACH p IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
        IF has_table_privilege(t, 'ops.pending_file_purges', p) THEN
          RAISE EXCEPTION 'db-roles: % 仍有 % ON ops.pending_file_purges', t, p;
        END IF;
      END LOOP;
    END LOOP;
  END IF;
  -- 成员关系自检：aia_maint 没有成员、也不属于任何角色；api/ingest 不能经任何链条取得 aia_maint
  IF EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r2 ON r2.rolname = 'aia_maint'
              WHERE m.roleid = r2.oid OR m.member = r2.oid) THEN
    RAISE EXCEPTION 'db-roles: aia_maint 仍有角色成员关系';
  END IF;
  FOREACH t IN ARRAY ARRAY['aia_api', 'aia_ingest'] LOOP
    IF pg_has_role(t, 'aia_maint', 'MEMBER') THEN
      RAISE EXCEPTION 'db-roles: % 仍是 aia_maint 的成员', t;
    END IF;
  END LOOP;
  IF NOT (SELECT rolcanlogin FROM pg_roles WHERE rolname = 'aia_maint') THEN
    RAISE EXCEPTION 'db-roles: aia_maint 必须有 LOGIN';
  END IF;
  IF (SELECT rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolinherit FROM pg_roles WHERE rolname = 'aia_maint') THEN
    RAISE EXCEPTION 'db-roles: aia_maint 角色属性不是最小（SUPERUSER/BYPASSRLS/CREATEROLE/CREATEDB/INHERIT）';
  END IF;
  RAISE NOTICE 'db-roles: aia_maint 已按列级清单授权（% 张表可 DELETE）', cardinality(del_ok);
END
$maint$;
