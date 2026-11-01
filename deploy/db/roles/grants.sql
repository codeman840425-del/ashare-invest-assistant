-- 分库角色与列级授权（T-O10）。幂等：每次 compose up 在 migrate、timescale-apply 之后由 db-roles 服务执行。
-- 以库属主（POSTGRES_USER，下称 owner = current_user）连接执行；owner 继续持有全部对象，migrate 仍用 owner。
--   aia_api    ：业务 schema 的表/视图 SELECT/INSERT/UPDATE/DELETE、序列、函数；
--                但下表 deny 列表里的“密文列”一律不可 SELECT（列级授权：同表其余列可 SELECT，表级 INSERT/UPDATE 保留，
--                api 只用公钥封装后写入、注销时置空，从不读回；T-B45“api 不读证书密文”）。
--   aia_ingest ：同上且全列可读（ingest 持私钥，需要读密文解封）。
-- 口令不在本文件：apply-roles.sh 以 psql 变量 :'api_pw' / :'ingest_pw' 传入（来自 secret 文件，不经环境变量、不入库）。
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
END
$roles$;

ALTER ROLE aia_api    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT;
ALTER ROLE aia_ingest LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT;

-- 口令：本会话关闭语句日志，避免 ALTER ROLE ... PASSWORD 进服务器日志。
SET log_statement = 'none';
SET log_min_duration_statement = -1;
ALTER ROLE aia_api    PASSWORD :'api_pw';
ALTER ROLE aia_ingest PASSWORD :'ingest_pw';
RESET log_min_duration_statement;
RESET log_statement;

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
