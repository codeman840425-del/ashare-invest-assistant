-- 恢复演练专用的样例表（只在演练容器的演练库里创建，绝不在 aia 主库执行）。
-- 字段取自 plan §3.3 / §3A.6；真实表结构以后端迁移为准，这里只用于验证部署侧策略与备份恢复流程。
CREATE SCHEMA IF NOT EXISTS market;
CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS market.minute_bars (
  security_id integer     NOT NULL,
  ts          timestamptz NOT NULL,
  open numeric(12,3), high numeric(12,3), low numeric(12,3), close numeric(12,3),
  volume bigint, amount numeric(20,2),
  source text NOT NULL DEFAULT 'pro_history',
  fetched_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (security_id, ts)
);
CREATE INDEX IF NOT EXISTS minute_bars_sec_ts_desc ON market.minute_bars (security_id, ts DESC);

CREATE TABLE IF NOT EXISTS market.realtime_quotes (
  security_id integer NOT NULL, ts timestamptz NOT NULL,
  price numeric(12,3), open numeric(12,3), high numeric(12,3), low numeric(12,3), pre_close numeric(12,3),
  volume bigint, amount numeric(20,2), pct_change numeric(8,4), source text, fetched_at timestamptz DEFAULT now(),
  PRIMARY KEY (security_id, ts)
);

CREATE TABLE IF NOT EXISTS market.daily_bars (
  security_id integer NOT NULL, trade_date date NOT NULL,
  open numeric(12,3), high numeric(12,3), low numeric(12,3), close numeric(12,3),
  volume bigint, amount numeric(20,2), adj_type text NOT NULL DEFAULT 'none', fetched_at timestamptz DEFAULT now(),
  PRIMARY KEY (security_id, trade_date, adj_type)
);

CREATE TABLE IF NOT EXISTS market.factor_values (
  security_id integer NOT NULL, trade_date date NOT NULL, factor_id integer NOT NULL,
  value double precision, calc_version text, fetched_at timestamptz DEFAULT now(),
  available_from timestamptz, first_seen_at timestamptz,
  PRIMARY KEY (factor_id, security_id, trade_date)
);

CREATE TABLE IF NOT EXISTS ops.ingest_request_log (
  id bigint GENERATED ALWAYS AS IDENTITY, requested_at timestamptz NOT NULL,
  requester text, priority text, dataset text, endpoint_key text, symbols_count int, dedup_key text,
  status text, http_status int, mairui_code text, latency_ms int, finished_at timestamptz,
  PRIMARY KEY (id, requested_at)
);
