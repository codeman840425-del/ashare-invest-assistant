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

-- T-O11：aia_maint（删除用户数据 CLI 专用）。整段在一个 DO 里：先撤后授，事务内完成，不留中间态。
DO $maint$
DECLARE
  owner_role text := current_user;
  t          text;
  r          record;
  p          text;
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO aia_maint', current_database());
  -- 成员关系已在授权之前由 $maint_members$ 撤清（见文件前部），这里只在末尾自检。

  FOR t IN SELECT unnest(ARRAY['app', 'ops', 'market']) LOOP
    IF to_regnamespace(t) IS NULL THEN CONTINUE; END IF;
    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM aia_maint', t);
    EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM aia_maint', t);
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO aia_maint', t);
  END LOOP;

  -- app：删除 / 匿名化 / 解除关联；新表由默认权限覆盖（plan §7.3 物理删除清单会随迁移增加）
  GRANT SELECT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO aia_maint;
  GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app TO aia_maint;
  EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA app GRANT SELECT, UPDATE, DELETE ON TABLES TO aia_maint', owner_role);
  IF to_regclass('app.audit_logs') IS NOT NULL THEN
    GRANT INSERT ON TABLE app.audit_logs TO aia_maint;
  END IF;

  -- ops：只到匿名化的两张审计/日志表 + 待清文件队列
  FOREACH t IN ARRAY ARRAY['ops.data_licence_events', 'ops.ingest_request_log'] LOOP
    IF to_regclass(t) IS NULL THEN RAISE WARNING 'db-roles: % 不存在，aia_maint 跳过', t; CONTINUE; END IF;
    EXECUTE format('GRANT SELECT, UPDATE, DELETE ON TABLE %s TO aia_maint', t::regclass);
  END LOOP;
  IF to_regclass('ops.pending_file_purges') IS NOT NULL THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE ops.pending_file_purges TO aia_maint;
  END IF;

  -- market：按 source_licence_id 删除用该用户证书取到的行
  IF to_regnamespace('market') IS NOT NULL THEN
    GRANT SELECT, DELETE ON ALL TABLES IN SCHEMA market TO aia_maint;
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA market GRANT SELECT, DELETE ON TABLES TO aia_maint', owner_role);
  END IF;

  -- 需要 INSERT 的两张表若用序列取号，只给它们自己的序列
  FOR r IN
    SELECT DISTINCT format('%I.%I', sn.nspname, s.relname) AS q
      FROM pg_depend d
      JOIN pg_class s ON s.oid = d.objid AND s.relkind = 'S'
      JOIN pg_namespace sn ON sn.oid = s.relnamespace
     WHERE d.deptype IN ('a', 'i')
       AND d.refobjid IN (SELECT x::regclass FROM unnest(ARRAY['app.audit_logs', 'ops.pending_file_purges']) x
                           WHERE to_regclass(x) IS NOT NULL)
  LOOP
    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO aia_maint', r.q);
  END LOOP;

  -- 自检：aia_maint 不得有 TRUNCATE / REFERENCES / TRIGGER，INSERT 只在两张表上；api/ingest 对待清队列无权限
  FOR r IN
    SELECT c.oid::regclass::text AS q FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f') AND n.nspname IN ('app', 'ops', 'market')
  LOOP
    FOREACH p IN ARRAY ARRAY['TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
      IF has_table_privilege('aia_maint', r.q, p) THEN
        RAISE EXCEPTION 'db-roles: aia_maint 不应有 % ON %', p, r.q;
      END IF;
    END LOOP;
    IF has_table_privilege('aia_maint', r.q, 'INSERT')
       AND r.q NOT IN ('app.audit_logs', 'ops.pending_file_purges') THEN
      RAISE EXCEPTION 'db-roles: aia_maint 不应有 INSERT ON %', r.q;
    END IF;
  END LOOP;
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
  RAISE NOTICE 'db-roles: aia_maint 已按 CLI 最小权限授权';
END
$maint$;
