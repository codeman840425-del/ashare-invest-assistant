-- 单个连续聚合：创建（WITH NO DATA）+ 刷新策略 + 可选压缩/保留（由 db-apply-timescale.sh 逐行调用）。
SET aia.cagg = :'cagg';
SET aia.source = :'source';
SET aia.def = :'def';
SET aia.key_alts = :'key_alts';
SET aia.start_offset = :'start_offset';
SET aia.end_offset = :'end_offset';
SET aia.schedule = :'schedule';
SET aia.compress_after = :'compress_after';
SET aia.drop_after = :'drop_after';
SET aia.dry_run = :'dry_run';

DO $aia$
DECLARE
  v_cagg   text := current_setting('aia.cagg');
  v_src    text := current_setting('aia.source');
  v_def    text := current_setting('aia.def');
  v_start  text := current_setting('aia.start_offset');
  v_end    text := current_setting('aia.end_offset');
  v_sched  text := current_setting('aia.schedule');
  v_after  text := current_setting('aia.compress_after');
  v_drop   text := current_setting('aia.drop_after');
  v_dry    boolean := current_setting('aia.dry_run') = '1';
  v_src_rel regclass := to_regclass(v_src);
  v_src_schema text; v_src_name text; v_time text; v_key text;
  v_schema text := split_part(v_cagg, '.', 1);
  v_name   text := split_part(v_cagg, '.', 2);
  v_sql text; v_md5 text; v_old_comment text;
  v_job int; v_cfg jsonb; v_sched_cur interval;
  v_comp_enabled boolean;
  p text := '[aia-ts] ' || current_setting('aia.cagg') || ': ';
BEGIN
  IF v_src_rel IS NULL THEN
    RAISE NOTICE '%SKIP 源表 % 不存在', p, v_src; RETURN;
  END IF;
  SELECT n.nspname, c.relname INTO v_src_schema, v_src_name
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.oid = v_src_rel;
  SELECT column_name INTO v_time FROM timescaledb_information.dimensions
   WHERE hypertable_schema = v_src_schema AND hypertable_name = v_src_name AND dimension_type = 'Time' LIMIT 1;
  IF v_time IS NULL THEN
    RAISE NOTICE '%SKIP 源表 % 还不是 hypertable', p, v_src; RETURN;
  END IF;
  v_key := pg_temp.aia_pick_col(v_src_rel, current_setting('aia.key_alts'));
  IF v_key IS NULL THEN
    RAISE NOTICE '%SKIP 源表缺少证券列（%）', p, current_setting('aia.key_alts'); RETURN;
  END IF;
  v_sql := replace(replace(replace(v_def, '{{source}}', v_src_rel::text), '{{key}}', quote_ident(v_key)), '{{time}}', quote_ident(v_time));
  v_md5 := md5(v_sql);

  -- 1) 视图
  IF to_regclass(v_cagg) IS NULL THEN
    IF v_dry THEN RAISE NOTICE '%[dry-run] 将创建连续聚合（WITH NO DATA）', p; RETURN; END IF;
    IF to_regnamespace(v_schema) IS NULL THEN EXECUTE format('CREATE SCHEMA %I', v_schema); END IF;
    EXECUTE format('CREATE MATERIALIZED VIEW %I.%I WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS %s WITH NO DATA',
                   v_schema, v_name, v_sql);
    EXECUTE format('COMMENT ON VIEW %I.%I IS %L', v_schema, v_name, 'managed by deploy/db/timescale; def_md5=' || v_md5);
    RAISE NOTICE '%已创建连续聚合（源 %，证券列 %，时间列 %）', p, v_src, v_key, v_time;
  ELSIF NOT EXISTS (SELECT 1 FROM timescaledb_information.continuous_aggregates WHERE view_schema = v_schema AND view_name = v_name) THEN
    RAISE WARNING '%SKIP 同名对象已存在但不是连续聚合', p; RETURN;
  ELSE
    v_old_comment := obj_description(to_regclass(v_cagg), 'pg_class');
    IF v_old_comment IS NULL OR position(v_md5 IN v_old_comment) = 0 THEN
      RAISE WARNING '%定义与 caggs/ 中的文件不一致（drift）；不会自动重建。需要时 DROP MATERIALIZED VIEW % 后重跑', p, v_cagg;
    ELSE
      RAISE NOTICE '%连续聚合 OK', p;
    END IF;
  END IF;

  -- 2) 刷新策略
  SELECT job_id, config, schedule_interval INTO v_job, v_cfg, v_sched_cur FROM timescaledb_information.jobs
   WHERE proc_name = 'policy_refresh_continuous_aggregate' AND hypertable_schema = v_schema AND hypertable_name = v_name;
  IF v_job IS NOT NULL AND (v_cfg->>'start_offset')::interval = v_start::interval
     AND (v_cfg->>'end_offset')::interval = v_end::interval AND v_sched_cur = v_sched::interval THEN
    RAISE NOTICE '%刷新策略 OK（job %：[now-%, now-%]，每 %）', p, v_job, v_start, v_end, v_sched;
  ELSIF v_dry THEN
    RAISE NOTICE '%[dry-run] 刷新策略 → [now-%, now-%]，每 %', p, v_start, v_end, v_sched;
  ELSE
    IF v_job IS NOT NULL THEN PERFORM remove_continuous_aggregate_policy(v_cagg::regclass, if_exists => true); END IF;
    SELECT add_continuous_aggregate_policy(v_cagg::regclass, start_offset => v_start::interval,
             end_offset => v_end::interval, schedule_interval => v_sched::interval) INTO v_job;
    RAISE NOTICE '%刷新策略 job %：[now-%, now-%]，每 %', p, v_job, v_start, v_end, v_sched;
  END IF;

  -- 3) 压缩（压缩期必须晚于刷新窗口 start_offset）
  IF v_after NOT IN ('-', 'none') THEN
    SELECT compression_enabled INTO v_comp_enabled FROM timescaledb_information.continuous_aggregates
     WHERE view_schema = v_schema AND view_name = v_name;
    IF NOT coalesce(v_comp_enabled, false) THEN
      IF v_dry THEN RAISE NOTICE '%[dry-run] 启用压缩', p;
      ELSE EXECUTE format('ALTER MATERIALIZED VIEW %I.%I SET (timescaledb.compress = true)', v_schema, v_name);
           RAISE NOTICE '%启用压缩', p; END IF;
    END IF;
    v_job := NULL; v_cfg := NULL;
    SELECT job_id, config INTO v_job, v_cfg FROM timescaledb_information.jobs
     WHERE proc_name = 'policy_compression' AND hypertable_schema = v_schema AND hypertable_name = v_name;
    IF v_job IS NOT NULL AND (v_cfg->>'compress_after')::interval = v_after::interval THEN
      RAISE NOTICE '%压缩策略 OK（job %，% 后压缩）', p, v_job, v_after;
    ELSIF NOT v_dry THEN
      IF v_job IS NOT NULL THEN PERFORM remove_compression_policy(v_cagg::regclass, if_exists => true); END IF;
      SELECT add_compression_policy(v_cagg::regclass, compress_after => v_after::interval) INTO v_job;
      RAISE NOTICE '%压缩策略 job %：% 后压缩', p, v_job, v_after;
    END IF;
  ELSIF v_after = 'none' THEN
    PERFORM remove_compression_policy(v_cagg::regclass, if_exists => true);
  END IF;

  -- 4) 保留
  IF v_drop NOT IN ('-', 'none') THEN
    v_job := NULL; v_cfg := NULL;
    SELECT job_id, config INTO v_job, v_cfg FROM timescaledb_information.jobs
     WHERE proc_name = 'policy_retention' AND hypertable_schema = v_schema AND hypertable_name = v_name;
    IF v_job IS NOT NULL AND (v_cfg->>'drop_after')::interval = v_drop::interval THEN
      RAISE NOTICE '%保留策略 OK（job %）', p, v_job;
    ELSIF NOT v_dry THEN
      IF v_job IS NOT NULL THEN PERFORM remove_retention_policy(v_cagg::regclass, if_exists => true); END IF;
      SELECT add_retention_policy(v_cagg::regclass, drop_after => v_drop::interval) INTO v_job;
      RAISE NOTICE '%保留策略 job %：保留 %', p, v_job, v_drop;
    END IF;
  ELSIF v_drop = 'none' AND NOT v_dry THEN
    PERFORM remove_retention_policy(v_cagg::regclass, if_exists => true);
  END IF;
END
$aia$;
