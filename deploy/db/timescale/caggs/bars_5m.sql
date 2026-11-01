-- market.bars_5m：1 分钟 K → 5 分钟 K（plan §3A.3）。
-- 占位符由 db-apply-timescale.sh 在库内替换：{{source}} 源表、{{key}} 证券列（security_id/code）、{{time}} 时间列。
-- 注意：time_bucket 按"桶起点"对齐；若后端约定分钟 K 的 ts 是 bar 结束时间（09:31 表示 09:30–09:31），
--       需在后端协调后改为 bar 起始时间入库，或在这里调整（见报告"后端协调"）。
-- 修改定义不会自动重建视图（会提示 drift）；需 DROP MATERIALIZED VIEW 后重跑 apply。
SELECT {{key}} AS {{key}},
       time_bucket(INTERVAL '5 minutes', {{time}}) AS bucket,
       first(open, {{time}})  AS open,
       max(high)              AS high,
       min(low)               AS low,
       last(close, {{time}})  AS close,
       sum(volume)            AS volume,
       sum(amount)            AS amount,
       count(*)               AS bar_count
FROM {{source}}
GROUP BY {{key}}, time_bucket(INTERVAL '5 minutes', {{time}})
