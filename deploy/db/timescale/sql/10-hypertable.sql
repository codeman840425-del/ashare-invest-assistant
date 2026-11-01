-- 单张表的 hypertable / chunk 间隔 / 压缩 / 保留（由 db-apply-timescale.sh 逐行调用，参数经 psql 变量传入）。
SET aia.tbl = :'tbl';
SET aia.time_col = :'time_col';
SET aia.chunk = :'chunk';
SET aia.segmentby = :'segmentby';
SET aia.orderby = :'orderby';
SET aia.compress_after = :'compress_after';
SET aia.drop_after = :'drop_after';
SET aia.migrate = :'migrate';
SET aia.dry_run = :'dry_run';

DO $aia$
DECLARE
  v_tbl     text := current_setting('aia.tbl');
  v_time    text := current_setting('aia.time_col');
  v_chunk   text := current_setting('aia.chunk');
  v_seg_s   text := current_setting('aia.segmentby');
  v_ord_s   text := current_setting('aia.orderby');
  v_after   text := current_setting('aia.compress_after');
  v_drop    text := current_setting('aia.drop_after');
  v_migrate boolean := current_setting('aia.migrate') = '1';
  v_dry     boolean := current_setting('aia.dry_run') = '1';
  v_rel     regclass := to_regclass(v_tbl);
  v_schema  text; v_name text;
  v_is_ht   boolean;
  v_has_rows boolean;
  v_cur_interval interval;
  v_seg text; v_ord text;
  v_cur_seg text; v_cur_ord text; v_compressed_chunks int;
  v_job int; v_cfg jsonb;
  p text := '[aia-ts] ' || current_setting('aia.tbl') || ': ';
BEGIN
  IF v_rel IS NULL THEN
    RAISE NOTICE '%SKIP 表不存在（建表归后端迁移；建表后重跑本脚本即可）', p; RETURN;
  END IF;
  SELECT n.nspname, c.relname INTO v_schema, v_name
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.oid = v_rel;
  IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = v_rel AND attname = v_time AND attnum > 0 AND NOT attisdropped) THEN
    RAISE NOTICE '%SKIP 时间列 % 不存在', p, v_time; RETURN;
  END IF;

  -- 1) hypertable 转换 / chunk 间隔
  v_is_ht := EXISTS (SELECT 1 FROM timescaledb_information.hypertables
                     WHERE hypertable_schema = v_schema AND hypertable_name = v_name);
  IF NOT v_is_ht THEN
    EXECUTE format('SELECT EXISTS (SELECT 1 FROM %s LIMIT 1)', v_rel) INTO v_has_rows;
    IF v_has_rows AND NOT v_migrate THEN
      RAISE WARNING '%SKIP 普通表已有数据，未转换为 hypertable（确认停写后用 AIA_TS_MIGRATE_DATA=1 重跑）', p; RETURN;
    END IF;
    IF v_dry THEN RAISE NOTICE '%[dry-run] 将转换为 hypertable（%，chunk %）', p, v_time, v_chunk; RETURN; END IF;
    PERFORM create_hypertable(v_rel, by_range(v_time, v_chunk::interval), migrate_data => v_has_rows);
    RAISE NOTICE '%转换为 hypertable（时间列 %，chunk %）', p, v_time, v_chunk;
  ELSE
    SELECT time_interval INTO v_cur_interval FROM timescaledb_information.dimensions
     WHERE hypertable_schema = v_schema AND hypertable_name = v_name AND column_name = v_time AND dimension_type = 'Time';
    IF v_cur_interval IS NULL THEN
      RAISE WARNING '%已是 hypertable 但时间维度不是 %，跳过 chunk 间隔设置', p, v_time;
    ELSIF v_cur_interval <> v_chunk::interval THEN
      IF v_dry THEN RAISE NOTICE '%[dry-run] chunk 间隔 % → %', p, v_cur_interval, v_chunk;
      ELSE
        PERFORM set_chunk_time_interval(v_rel, v_chunk::interval);
        RAISE NOTICE '%chunk 间隔 % → %（只影响新建 chunk）', p, v_cur_interval, v_chunk;
      END IF;
    ELSE
      RAISE NOTICE '%hypertable OK（chunk %）', p, v_cur_interval;
    END IF;
  END IF;

  -- 2) 压缩设置 + 压缩策略
  IF v_after = 'none' THEN
    SELECT job_id INTO v_job FROM timescaledb_information.jobs
     WHERE proc_name = 'policy_compression' AND hypertable_schema = v_schema AND hypertable_name = v_name;
    IF v_job IS NOT NULL THEN
      IF NOT v_dry THEN PERFORM remove_compression_policy(v_rel, if_exists => true); END IF;
      RAISE NOTICE '%删除压缩策略 job %（已压缩数据保持不变）', p, v_job;
    END IF;
  ELSIF v_after <> '-' THEN
    v_seg := pg_temp.aia_resolve_list(v_rel, v_seg_s);
    v_ord := pg_temp.aia_resolve_list(v_rel, v_ord_s);
    IF v_seg IS NULL OR v_ord IS NULL THEN
      RAISE WARNING '%压缩列不存在（segmentby=% orderby=%），跳过压缩配置', p, v_seg_s, v_ord_s;
    ELSE
      SELECT segmentby, orderby INTO v_cur_seg, v_cur_ord
        FROM timescaledb_information.hypertable_compression_settings WHERE hypertable = v_rel;
      SELECT count(*) INTO v_compressed_chunks FROM timescaledb_information.chunks
       WHERE hypertable_schema = v_schema AND hypertable_name = v_name AND is_compressed;
      IF pg_temp.aia_norm(v_cur_seg) <> pg_temp.aia_norm(v_seg)
         OR pg_temp.aia_norm(v_cur_ord) <> pg_temp.aia_norm(v_ord)
         OR NOT EXISTS (SELECT 1 FROM timescaledb_information.hypertables
                        WHERE hypertable_schema = v_schema AND hypertable_name = v_name AND compression_enabled) THEN
        IF v_compressed_chunks > 0 THEN
          RAISE WARNING '%已有 % 个压缩 chunk，压缩设置与配置不同（当前 segmentby=% orderby=%，配置 %/%）；为安全起见不自动修改',
            p, v_compressed_chunks, v_cur_seg, v_cur_ord, v_seg, v_ord;
        ELSIF v_dry THEN
          RAISE NOTICE '%[dry-run] 压缩设置 segmentby=% orderby=%', p, v_seg, v_ord;
        ELSE
          EXECUTE format('ALTER TABLE %s SET (timescaledb.compress, timescaledb.compress_segmentby = %L, timescaledb.compress_orderby = %L)',
                         v_rel, v_seg, v_ord);
          RAISE NOTICE '%压缩设置 segmentby=[%] orderby=[%]', p, v_seg, v_ord;
        END IF;
      ELSE
        RAISE NOTICE '%压缩设置 OK（segmentby=[%] orderby=[%]）', p, v_cur_seg, v_cur_ord;
      END IF;

      SELECT job_id, config INTO v_job, v_cfg FROM timescaledb_information.jobs
       WHERE proc_name = 'policy_compression' AND hypertable_schema = v_schema AND hypertable_name = v_name;
      IF v_job IS NOT NULL AND (v_cfg->>'compress_after')::interval = v_after::interval THEN
        RAISE NOTICE '%压缩策略 OK（job %，% 后压缩）', p, v_job, v_after;
      ELSIF v_dry THEN
        RAISE NOTICE '%[dry-run] 压缩策略 → % 后压缩（当前 %）', p, v_after, coalesce(v_cfg->>'compress_after', '无');
      ELSE
        IF v_job IS NOT NULL THEN PERFORM remove_compression_policy(v_rel, if_exists => true); END IF;
        SELECT add_compression_policy(v_rel, compress_after => v_after::interval) INTO v_job;
        RAISE NOTICE '%压缩策略 job %：% 后压缩', p, v_job, v_after;
      END IF;
    END IF;
  END IF;

  -- 3) 保留策略
  v_job := NULL; v_cfg := NULL;
  SELECT job_id, config INTO v_job, v_cfg FROM timescaledb_information.jobs
   WHERE proc_name = 'policy_retention' AND hypertable_schema = v_schema AND hypertable_name = v_name;
  IF v_drop = 'none' THEN
    IF v_job IS NOT NULL THEN
      IF NOT v_dry THEN PERFORM remove_retention_policy(v_rel, if_exists => true); END IF;
      RAISE NOTICE '%删除保留策略 job %', p, v_job;
    END IF;
  ELSIF v_drop <> '-' THEN
    IF v_job IS NOT NULL AND (v_cfg->>'drop_after')::interval = v_drop::interval THEN
      RAISE NOTICE '%保留策略 OK（job %，保留 %）', p, v_job, v_drop;
    ELSIF v_dry THEN
      RAISE NOTICE '%[dry-run] 保留策略 → %（当前 %）', p, v_drop, coalesce(v_cfg->>'drop_after', '无');
    ELSE
      IF v_job IS NOT NULL THEN PERFORM remove_retention_policy(v_rel, if_exists => true); END IF;
      SELECT add_retention_policy(v_rel, drop_after => v_drop::interval) INTO v_job;
      RAISE NOTICE '%保留策略 job %：保留 %', p, v_job, v_drop;
    END IF;
  END IF;
END
$aia$;
