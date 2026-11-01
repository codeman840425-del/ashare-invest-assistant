-- 演练校验指标：每行 "key=value"，源库与恢复库逐项比对。
SELECT 'rows.' || t, n FROM (
  SELECT 'market.minute_bars' t, count(*)::text n FROM market.minute_bars UNION ALL
  SELECT 'market.realtime_quotes', count(*)::text FROM market.realtime_quotes UNION ALL
  SELECT 'market.daily_bars', count(*)::text FROM market.daily_bars UNION ALL
  SELECT 'market.factor_values', count(*)::text FROM market.factor_values UNION ALL
  SELECT 'ops.ingest_request_log', count(*)::text FROM ops.ingest_request_log UNION ALL
  SELECT 'market.bars_5m', count(*)::text FROM market.bars_5m UNION ALL
  SELECT 'market.bars_daily_from_1m', count(*)::text FROM market.bars_daily_from_1m
) x
UNION ALL SELECT 'md5.market.minute_bars', md5(string_agg(m::text, '|' ORDER BY security_id, ts)) FROM market.minute_bars m
UNION ALL SELECT 'md5.market.realtime_quotes', md5(string_agg(m::text, '|' ORDER BY security_id, ts)) FROM market.realtime_quotes m
UNION ALL SELECT 'md5.market.daily_bars', md5(string_agg(m::text, '|' ORDER BY security_id, trade_date, adj_type)) FROM market.daily_bars m
UNION ALL SELECT 'md5.market.factor_values', md5(string_agg(m::text, '|' ORDER BY factor_id, security_id, trade_date)) FROM market.factor_values m
UNION ALL SELECT 'md5.ops.ingest_request_log', md5(string_agg(m::text, '|' ORDER BY id, requested_at)) FROM ops.ingest_request_log m
UNION ALL SELECT 'md5.market.bars_5m', md5(string_agg(m::text, '|' ORDER BY security_id, bucket)) FROM market.bars_5m m
UNION ALL SELECT 'md5.market.bars_daily_from_1m', md5(string_agg(m::text, '|' ORDER BY security_id, bucket)) FROM market.bars_daily_from_1m m
UNION ALL SELECT 'hypertables', string_agg(hypertable_schema || '.' || hypertable_name || '(compression=' || compression_enabled || ')', ',' ORDER BY 1)
  FROM timescaledb_information.hypertables WHERE hypertable_schema IN ('market', 'ops')
UNION ALL SELECT 'chunks.total', count(*)::text FROM timescaledb_information.chunks WHERE hypertable_schema IN ('market', 'ops')
UNION ALL SELECT 'chunks.compressed', count(*)::text FROM timescaledb_information.chunks WHERE is_compressed
UNION ALL SELECT 'chunks.compressed.minute_bars', count(*)::text FROM timescaledb_information.chunks WHERE is_compressed AND hypertable_name = 'minute_bars'
UNION ALL SELECT 'caggs', string_agg(view_schema || '.' || view_name || '(materialized_only=' || materialized_only || ',compression=' || compression_enabled || ')', ',' ORDER BY 1)
  FROM timescaledb_information.continuous_aggregates
UNION ALL SELECT 'jobs', string_agg(sig, ' ; ' ORDER BY sig) FROM (
  SELECT proc_name || '@' || hypertable_schema || '.' || hypertable_name || ' every ' || schedule_interval || ' '
         || (config - 'hypertable_id' - 'mat_hypertable_id')::text || ' scheduled=' || scheduled AS sig
  FROM timescaledb_information.jobs WHERE hypertable_name IS NOT NULL) j
UNION ALL SELECT 'jobs.count', count(*)::text FROM timescaledb_information.jobs WHERE hypertable_name IS NOT NULL;
