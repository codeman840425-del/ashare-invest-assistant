-- 恢复演练样例数据（确定性伪随机，按 psql 变量 :securities / :days 控制规模）。
-- 1 分钟 K：最近 :days 个工作日、每日 240 根（上海时间 09:30–11:29、13:00–14:59 的 bar 起点）。
WITH days AS (
  SELECT d::date AS day
  FROM generate_series((now() AT TIME ZONE 'Asia/Shanghai')::date - (:days * 7 / 5 + 3), (now() AT TIME ZONE 'Asia/Shanghai')::date - 1, interval '1 day') d
  WHERE extract(isodow FROM d) < 6
  ORDER BY d DESC LIMIT :days
), mins AS (
  SELECT m FROM generate_series(0, 119) m
), bars AS (
  SELECT s AS security_id,
         ((day + time '09:30' + make_interval(mins => m)) AT TIME ZONE 'Asia/Shanghai') AS ts
  FROM days, mins, generate_series(1, :securities) s
  UNION ALL
  SELECT s, ((day + time '13:00' + make_interval(mins => m)) AT TIME ZONE 'Asia/Shanghai')
  FROM days, mins, generate_series(1, :securities) s
)
INSERT INTO market.minute_bars (security_id, ts, open, high, low, close, volume, amount, fetched_at)
SELECT security_id, ts,
       round(p, 3), round(p * 1.002, 3), round(p * 0.998, 3), round(p * (1 + ((h % 7) - 3) / 2000.0), 3),
       100 * (h % 5000 + 1), round(p * 100 * (h % 5000 + 1), 2), ts + interval '5 seconds'
FROM (
  SELECT security_id, ts,
         abs(hashtext(security_id::text || ts::text)) AS h,
         ((10 + security_id % 90) * (1 + sin(extract(epoch FROM ts)::float8 / 86400.0 + security_id) / 20))::numeric AS p
  FROM bars
) x
ON CONFLICT DO NOTHING;

INSERT INTO market.daily_bars (security_id, trade_date, open, high, low, close, volume, amount)
SELECT security_id, (bucket AT TIME ZONE 'Asia/Shanghai')::date, first(open, ts), max(high), min(low), last(close, ts), sum(volume), sum(amount)
FROM (SELECT *, time_bucket('1 day', ts, 'Asia/Shanghai') AS bucket FROM market.minute_bars) m
GROUP BY security_id, bucket
ON CONFLICT DO NOTHING;

INSERT INTO market.realtime_quotes (security_id, ts, price, volume, amount, source)
SELECT security_id, ts, close, volume, amount, 'ssjy_all'
FROM market.minute_bars WHERE ts > now() - interval '10 days' AND extract(minute FROM ts)::int % 5 = 0
ON CONFLICT DO NOTHING;

INSERT INTO market.factor_values (security_id, trade_date, factor_id, value, calc_version, available_from, first_seen_at)
SELECT d.security_id, d.trade_date, f, (hashtext(d.security_id::text || d.trade_date::text || f::text) % 10000) / 1000.0,
       'v1', d.trade_date + interval '16 hours', d.trade_date + interval '16 hours'
FROM market.daily_bars d, generate_series(1, 10) f
ON CONFLICT DO NOTHING;

INSERT INTO ops.ingest_request_log (requested_at, requester, priority, dataset, endpoint_key, symbols_count, dedup_key, status, http_status, latency_ms, finished_at)
SELECT now() - make_interval(mins => g * 37), 'ingest', 'P1', 'minute_bars', 'pro_history', 1, 'drill-' || g, 'done', 200, 50 + g % 200,
       now() - make_interval(mins => g * 37) + interval '80 ms'
FROM generate_series(1, 1000) g;
