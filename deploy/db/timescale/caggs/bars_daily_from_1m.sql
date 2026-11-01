-- market.bars_daily_from_1m：1 分钟 K → 日 K（按 Asia/Shanghai 自然日分桶），用于与 market.daily_bars 对账（plan §3A.3）。
-- bar_count 可用来发现缺分钟（A 股正常 240 根）。
SELECT {{key}} AS {{key}},
       time_bucket(INTERVAL '1 day', {{time}}, 'Asia/Shanghai') AS bucket,
       first(open, {{time}})  AS open,
       max(high)              AS high,
       min(low)               AS low,
       last(close, {{time}})  AS close,
       sum(volume)            AS volume,
       sum(amount)            AS amount,
       count(*)               AS bar_count
FROM {{source}}
GROUP BY {{key}}, time_bucket(INTERVAL '1 day', {{time}}, 'Asia/Shanghai')
