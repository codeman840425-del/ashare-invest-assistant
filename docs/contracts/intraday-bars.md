# 分钟线与日内做 T 契约（T-A143，draft）

状态：draft，架构契约，不代表已实现。基线 docs/T-A142 `0dfaae9`。依据：用户原话「日内做T 不需要分钟线？」。据此，分钟线从 T-A142 `daily-bars-tdx.md` §3.6 的「可选」改为**必需**。本契约只定分钟线数据与做 T 最小闭环；日 K 链路仍按 `daily-bars-source.md` 与 `daily-snapshot-from-bars.md`。

**红线（不变）：** 真实麦蕊调用不放开。分钟线的真实调用须单 D 获批（建议在单 D 里另列分钟线一项，下称「单 D 分钟线部分」），用户本人批准前，下面所有新常量默认 0，默认部署 0 次出网。通达信目录的挂载与导入须用户本人同意，默认不导入（`daily-bars-tdx.md` §3.1、§7 U-T0）。

## 1. 数据源

### 1.1 当天与实时：麦蕊 1 分钟 K（主源）

出处只有两处，且都**未实测**：`docs/plan.md` §0A 接口表与 §0A.7 推导；`reports/T003-mairui-capability.md`（1 分钟 Pro 一项写明「未验证（被 IP 超限中断）」）。

| 用途 | 接口（据上述文档） | 要点 | 限频（据文档） |
| --- | --- | --- | --- |
| 盘中增量 | `/hsstock/pro/latest/{code}.{mkt}/1/n?lt=1..5` | 单股；lt 最多 5 根；Redis 集群盘中增量 | 「限流同证书档位」，钻石版按 6,000 次/分钟理解 |
| 盘后补齐 | `/hsstock/pro/history/{code}.{mkt}/1/n?st&et&lt` | 单股；文档称深度约 5 年 | 同上；`history/full` 全量接口 60 次/分钟 |

- 字段：按契约 `Bar`（t、open、high、low、close、volume、amount），t 为 bar 结束时间（`market.minute_bars` 列注释：09:31 表示 09:30–09:31）。
- 复权：分钟线只有不复权（T003：分钟级传复权 f 报 503；`api-contract` 的 `bar_adjust` 规定 1m 只支持 none）。
- 成交量单位：麦蕊日线是手；分钟线单位**未实测**。契约统一为股，单 D 分钟线部分的首次实调必须核对一次「额 ÷ 量 ≈ 价」。
- 通用限制（plan §0A）：同一证书 60 秒内最多 2 个来源 IP，超出报 103 或 429。串行时延两处记录不一致：T003 约 0.26 秒/次，T-A136 实测日线约 1.85 秒/次。下面的估算两个都列，**以 1.85 秒为保守口径**。

### 1.2 历史：通达信 minline / fzline（只取 A 股）

- 据编排者 2026-11-10 只读扫描（架构未核实）：
  - minline 的 .lc1：sh 4,831、sz 4,369、bj 360 个文件，样本每只 31,920 根，约 133 个交易日；
  - fzline 的 .lc5：同样的文件数，样本每只 13,776 根，约 287 个交易日。
- 只读挂载：与日线同一张运维单 O1（`daily-bars-tdx.md` §3.2），把 sh、sz、bj 下的 minline、fzline 以 `:ro` 挂进容器；宿主路径是部署参数，不进代码与 compose 默认值。
- 导入前算 sha256，清单落盘到可写的审计目录，复跑时比对，机制与 `daily-bars-tdx.md` §3.3 第 1–4 步相同（共用一个清单辅助函数）。
- 只取 A 股：文件名规则与主数据过滤同日线（`trades.normalize_code`，加 `securities` 的 type 为 stock 且 listing_status 为 listed）。
- 格式要点（公开资料，**未实测**）：每条 32 字节，小端。
  - 前 2 字节：打包日期（年 = 值整除 2048 再加 2004；余数整除 100 为月，余数模 100 为日）；
  - 接着 2 字节：当日零点起的分钟数，按 bar 结束时间理解，须实测确认；
  - 然后 open、high、low、close、成交额为 float32，成交量为整数，最后 4 字节保留。
  - .lc1 为 1 分钟，.lc5 为 5 分钟。价格是否需要换算、成交量是股还是手，都要用「额 ÷ 量落在 [low, high]」逐文件自检，规则同日线（`tdx_unit_suspect:<code>`）。

### 1.3 来源标注与不混写

- 每行带 source。新写入只用两个取值：mairui、tdx_local。基线 CHECK 里已有的 pro_latest、pro_history 保留，只为兼容，新代码不再写。
- 主键 (code, ts) 一键一行：
  - 跨源一律 DO NOTHING，先写者留下；
  - 通达信导入的截止日 D 取「库里该代码最早一根 mairui 分钟线所在日的前一开市日」；没有 mairui 行时取前一开市日。所以两源不重叠。
- 同源的麦蕊盘后补齐，可以更新同源、同键的盘中行：只在已有行的 source 也是 mairui 时更新，其他源一律不动。

## 2. 存储

### 2.1 估算（按 1 分钟 240 根/日、5 分钟 48 根/日、242 交易日/年；每行约 110 B，口径同 plan §3A.2；Timescale 压缩按 10 倍估）

| 范围 | 1 分钟：每日行数 | 1 分钟：每年（未压缩 / 压缩后） | .lc1 历史 133 日 | .lc5 历史 287 日 |
| --- | --- | --- | --- | --- |
| 持仓加自选 50 只 | 1.2 万 | 290 万行，0.32 GB / 约 0.03 GB | 160 万行，0.18 GB | 69 万行，0.08 GB |
| 持仓加自选 200 只 | 4.8 万 | 1,162 万行，1.28 GB / 约 0.13 GB | 638 万行，0.70 GB | 276 万行，0.30 GB |
| 全市场 5,600 只 | 134.4 万 | 3.25 亿行，35.8 GB / 约 3.6 GB | 1.79 亿行，19.7 GB | 7,715 万行，8.5 GB |

- 通达信原始文件（A 股）：.lc1 每只约 1.02 MB，5,600 只约 5.7 GB；.lc5 每只约 0.44 MB，约 2.5 GB。只读挂载，不复制。
- 持仓和自选的只数，脱敏资料里没有。50 和 200 是量级示意（自选上限 `watchlist.per_user_cap` 为 100）。

### 2.2 表结构（推荐：沿用 Timescale hypertable，不另做按月分区）

- 1 分钟：沿用基线已有的 `market.minute_bars`。它是 hypertable，按 ts 每 1 天一个 chunk，主键 (code, ts)。新迁移 0034（排在 `daily-bars-tdx.md` 的 0033 之后）：
  - source 的 CHECK 加入 mairui 与 tdx_local；
  - 加可空列 source_licence_id，口径同日线 0032；tdx_local 行为空；
  - 不改主键，不改已有行。
- 5 分钟：新表 `market.minute5_bars`，列与 minute_bars 相同，hypertable 每 7 天一个 chunk，主键 (code, ts)。只存 .lc5 历史。以后的 5 分钟线在读取时由 1 分钟聚合，不另存。不能塞进 minute_bars：同一 ts 下 1 分钟 bar 和 5 分钟 bar 会撞主键。
- 不按月原生分区的理由：基线已是 hypertable（chunk 自动建、自动压缩，可按 chunk 删）。改成按月分区要重建表，没有收益。
- 压缩：chunk 满 7 天后压缩（plan §3A 原定）。
- 保留期：
  - 推荐：1 分钟（持仓加自选）保留 3 年，5 分钟历史全部保留；
  - 保守默认：不自动删除。按上表，200 只 3 年压缩后不到 0.5 GB。
  - 全市场分钟线：本期不存（§3.4）。
- downgrade：有 mairui 或 tdx_local 的分钟行时拒绝；minute5_bars 非空时拒绝。

## 3. 做 T 最小闭环

### 3.1 对象

- 只针对持仓股：上一交易日收盘时持有数量 base_qty 大于 0 的 A 股（不含 ETF、可转债）。
- ETF 的 T+0（`market_rules/lots.fund_t_plus`）压后。

### 3.2 T+1 约束

- 今日可卖数量 sellable_qty = base_qty − 今日已卖数量；今日买入的不可卖。
- 做 T 只能用底仓：任何与做 T 相关的数量提示，卖出一侧都不得超过 sellable_qty，并须通过 `market_rules/lots.check_qty`（传入 sellable_qty）。
- 不给出买入、卖出之类的诱导措辞；动作名只用既有的 ACTION_FULL、ACTION_SHORT，并显示免责提示（today-view 既有约定）。

### 3.3 指标与信号（只用当日 mairui 分钟行）

- VWAP：当日 09:30 起累计成交额 ÷ 累计成交量。
- 偏离 dev_pct：(最新收盘 − VWAP) ÷ VWAP。
- 量比：当日截至当前分钟的累计量，除以过去 5 个交易日同一时刻累计量的均值。历史不足 5 日时为空，并记 gap。
- 信号：复用既有 signal_kind 里的 vwap_deviation 与 volume_spike（`SignalEvent`，经 `/signals`，不含动作建议）。阈值是配置项，初值为 |dev_pct| ≥ 2% 与量比 ≥ 2，**待复测**（§7 Q5）。
- 数据不足时：本股不出信号，`data_status` 为 partial 或 unavailable，gap 标出原因（no_source、quota_deferred 等既有 reason）。

### 3.4 复测输入

- 复测读取 minute_bars 与 minute5_bars，按 (code, 交易日) 给出有序的分钟序列，每根带 source。
- tdx_local 与 mairui 都可以用作复测输入，但结果里必须保留 source。
- 本期只交付数据就绪和一个只读导出 CLI（`intraday-bars-export`，输出 CSV 或 JSONL 到审计目录）；复测引擎压后。

### 3.5 与日报、today 的关系

- today（盘中）：持仓行在既有的 `/today` 响应里新增可空字段 t_view，内容为 vwap、dev_pct、volume_ratio、base_qty、sellable_qty、data_status、as_of。不新增接口。前端沿用 `/today` 的轮询（`notify.poll_fallback_s`），不新增 SSE 事件类型。
- 日报（17:30）：每只持仓加一条「当日分时摘要」，维度键为 stocks.<代码>.intraday，内容为收盘相对 VWAP 的偏离和当日信号次数。缺分钟数据时记 gap，reason 为 no_source。today-view §8 c 已裁定 stocks 维度键非 user_input_missing 时不在 today 显示，这里一致。
- 日报和 today 只用 mairui 分钟行；tdx_local 分钟行只进复测，不进这两处（与日 K 的 `_load_bars` 排除规则同理）。

### 3.6 压后

自选股的盘中信号与做 T 视图；ETF T+0；五档盘口；集合竞价；分钟级因子与技术指标接口；全市场分钟线的存储与采集；5 分钟实时采集；通知推送节奏调优；复测引擎；任何形式的自动下单（永不做）。

## 4. 麦蕊分钟 K 的调用量

### 4.1 估算（盘中 240 分钟；单股接口，每次一只）

| 档位 | 每分钟调用 | N=20 每日 | N=50 每日 | N=200 每日 |
| --- | --- | --- | --- | --- |
| A：全部每 1 分钟（lt=2） | N | 4,800 | 12,000 | 48,000 |
| B：重点 20 只每 1 分钟，其余每 5 分钟（lt=5） | 20 + (N−20)/5 | 4,800 | 6,240 | 13,440 |
| C：全部每 5 分钟（lt=5） | N/5 | 960 | 2,400 | 9,600 |
| D：只做盘后补齐（history，1 次/只/日） | — | 20 | 50 | 200 |

- 额度不是瓶颈：钻石版文档为 6,000 次/分钟；`config/ingest.yaml` 自设每证书 3,000 次/分钟，其中 minute_bars 份额 2,000。
- **瓶颈是串行时延**：单连接、固定出口 IP，按 1.85 秒/次，每分钟最多约 32 次；按 0.26 秒/次，约 230 次。
  - 按保守口径，A 档只能覆盖约 30 只；
  - B 档在 N=50 时为 26 次/分钟，可行；N=200 时为 56 次/分钟，不可行；
  - C 档在 N=200 时为 40 次/分钟，也不可行。
- 推荐：持仓（最多 20 只）每 1 分钟，自选不采集盘中分钟线（压后），收盘后用 D 档补齐当日全部持仓与自选。每分钟上限取 30，比保守口径的 32 次低一点。

### 4.2 与 `DAILY_BARS_BATCH_LIMIT`（500 次/批）的关系：推荐独立配额，共享红线

- 独立配额：
  - 盘中采集是连续流，不是批，用新常量 `INTRADAY_BARS_PER_MINUTE_LIMIT`（`app/ingest` 模块常量，默认整数 0，硬上界 30；不进 Settings，不读环境变量或回执）；
  - 判定同 `daily_bars_batch_budget`：正整数且不超过硬上界为 capped，其余为 unset，不出网；
  - 单 D 分钟线部分把它改为 30。
- 盘后补齐（D 档）是批，复用源契约 §9.3 的批机制与 `DAILY_BARS_BATCH_LIMIT`（500 次/批，续接直到做完）。在 15:30 起跑，17:00 前须结束，未完成的按 §9.3 顺延到 17:45 以后，避开 17:15 日 K 批。
- 共享的红线：
  - 同一条串行单连接、同一固定出口 IP；
  - STOP、HALT、103、429 时，盘中采集与所有批一起停，不重试；HALT 由运维人工清除。
  - 开市日 09:15–15:05 盘中采集开启时，日 K 回填批与新股补历史批不运行，顺延到 15:05 以后，避免与盘中争用唯一连接。
- 不推荐共享一个配额：500 次/批的语义是一次性的、可续接的批；盘中需要每分钟稳定的节拍，放进批里会出现「批用完就等下一批」的空窗。

### 4.3 真实调用

- 等单 D 分钟线部分获用户本人批准。批准内容须写明：每分钟上限 30、覆盖哪些股票、首次实调的次数与时段，以及要核对的四件事：时延、成交量单位、lt 覆盖、盘后补齐深度。
- 批准前，盘中采集与盘后补齐都只在打桩 transport 下开发与测试。

## 5. 拆单与验收

时点标注：「现在」表示离线、fake 或打桩 transport 下可开发可测；「D 后」表示单 D 分钟线部分获批之后；「同意后」表示用户同意挂载与导入（U-T0）之后。

### 5.1 后端

**M1 迁移 0034（现在）**
- `test_migration_0034_minute_bars_source_and_licence`：Given 升到 0034 / Then minute_bars 可写 source 为 mairui 或 tdx_local，未知值失败；source_licence_id 存在且可空；主键仍为 (code, ts)。
- `test_migration_0034_minute5_bars_hypertable`：Then minute5_bars 存在，是按 ts 7 天一个 chunk 的 hypertable，主键 (code, ts)。
- `test_migration_0034_downgrade_refuses_with_rows`：Given 有 tdx_local 分钟行或 minute5_bars 非空 / Then downgrade 拒绝。

**M2 通达信分钟导入 `intraday-bars-import-tdx`（现在开发；真实导入在同意后）**
- `test_lc_parse_record_layout`：Given 构造的 32 字节 .lc1、.lc5 记录 / Then 日期、分钟、OHLC、额、量解析正确。
- `test_lc_import_a_share_only`：Given minline 内有 A 股、指数、ETF、880 板块文件 / Then 只导入 listed A 股；被过滤的文件不打开、不进清单。
- `test_lc_import_manifest_generated_and_compared`：Then 审计目录生成清单；复跑时输出新增、删除、变化计数。
- `test_lc_import_until_before_first_mairui_minute`：Given 某代码已有 mairui 分钟行起于 E 日 / Then 该代码只导入到 E 的前一开市日。
- `test_lc5_goes_to_minute5_bars_only`：Then .lc5 行只出现在 minute5_bars，minute_bars 不变。
- `test_lc_import_rerun_idempotent`：Then 第二次 inserted 为 0。
- `test_lc_import_readonly_root`：Given 只读根目录 / Then 成功，根目录不变。
- `test_lc_import_no_network`：Then `egress.mairui_get` 调用数为 0。

**M3 麦蕊分钟采集（现在用打桩 transport 开发；常量改 30 在 D 后）**
- `test_intraday_limit_default_zero_no_network`：Given 默认常量 / When 盘中 tick / Then transport 0 次，记 `daily_bars_http_budget_unset` 同类的 unset issue（建议名 `intraday_bars_budget_unset`）。
- `test_intraday_budget_resolution_table`：Given 0、1、30、31、-1、True、None、字符串 30 / Then 只有 1 和 30 为 capped。
- `test_intraday_calls_per_minute_never_exceed_cap`：Given 上限 monkeypatch 为 5、持仓 8 只 / Then 每分钟 transport 不超过 5 次，余下的记 quota_deferred，下一分钟优先。
- `test_intraday_writes_closed_minutes_only`：Given 返回含当前未走完的那一分钟 / Then 只写已结束的分钟。
- `test_intraday_halts_on_stop_halt_103_429`：Then 盘中采集与批一起停，不重试，写 HALT。
- `test_backfill_paused_during_session_when_intraday_on`：Given 开市日 10:00、盘中采集开启 / Then 日 K 回填与补历史批进 `jobs:delayed`，15:05 放出。
- `test_postclose_completion_uses_batch_limit`：Given 上限 monkeypatch 为 3、持仓加自选 5 只 / Then 首批 3 次并续接；17:00 未完成的顺延到 17:45。
- `test_postclose_same_source_update_cross_source_nothing`：Then 同为 mairui 的同键行被更新；已有 tdx_local 行不变。

**M4 做 T 指标、T+1 与 `/today` 的 t_view（现在）**
- `test_t_view_vwap_and_dev`：Given 构造的 3 根分钟线 / Then vwap 等于累计额除以累计量，dev_pct 按定义计算。
- `test_t_view_volume_ratio_needs_5_days`：Given 只有 3 日历史 / Then volume_ratio 为空，并记 gap。
- `test_t_view_sellable_is_base_minus_sold_today`：Given 昨日底仓 1,000 股、今日买入 500 股、卖出 300 股 / Then sellable_qty 为 700，今日买入的不计入。
- `test_t_view_only_holdings_with_base`：Given 今日新买、昨日无底仓的股 / Then 没有 t_view。
- `test_t_view_ignores_tdx_local`：Given 当日只有 tdx_local 分钟行 / Then data_status 为 unavailable。
- `test_signals_vwap_deviation_volume_spike_threshold`：Given 偏离 2.1%、量比 2.2 / Then `/signals` 各有一条，且不含动作建议。

**M5 日报分时摘要（现在）**
- `test_report_intraday_summary_key`：Given 持仓有当日 mairui 分钟行 / Then 日报 body 有 stocks.<代码>.intraday 摘要；没有分钟行时 gaps 有该键，reason 为 no_source。

### 5.2 前端（F36，现在，用 mock）

- Given `/today` 的持仓行带 t_view / Then 行内显示分时均价、偏离、可用底仓（「今日可用底仓 N 股」）、数据时间；不出现「买入」「卖出」这类诱导措辞，免责提示可见。
- Given t_view 为空，或 data_status 为 unavailable / Then 显示「分时数据暂不可用。」，不显示偏离。
- Given 机器时区为 America/Denver / Then as_of 按 Asia/Shanghai 显示。
- 用例名：`t-f36 t_view 正常显示`、`t-f36 t_view 不可用`、`t-f36 可用底仓不超过昨日底仓`、`t-f36 时区按北京时间`。

### 5.3 测试（T-T76）

- 隔离库复跑 M1–M5 的连库用例，以及：
  - `test_intraday_end_to_end_fake_source`：Given fake 分钟源、两只持仓 / When 盘中 tick 三次、盘后补齐、17:30 日报 / Then minute_bars 行数等于预期，t_view 与日报摘要一致，transport（真实）0 次。
  - `test_minute_sources_never_mixed`：Given 同一 (code, ts) 先写 tdx_local、再写 mairui / Then 只有一行，source 为 tdx_local，计数中有一次冲突。
- 篡改自证：把 `INTRADAY_BARS_PER_MINUTE_LIMIT` 改成 31，或把 sellable_qty 的计算改成含今日买入，相应用例必须变红。

### 5.4 运维

- O1（扩展，同意后）：在日线 lday 之外，再把 minline、fzline 只读挂进容器；宿主路径为部署参数；dry-run 确认 A 股文件数约为 5,600。
- O3（D 后）：盘中采集只在一个进程里出网，单连接、固定出口 IP；记录首次实调的时延与成交量单位。
- 单 D 分钟线部分的批准单（见 §4.3）。

## 6. 和日 K 契约的接口

- 共用：只读挂载（O1）、清单辅助函数、STOP/HALT 规则、串行单连接、`daily_bars_batch_budget` 的判定风格。
- 不改：17:15 日 K 批、17:30 日报、`DAILY_BARS_BATCH_LIMIT` 500。
- 新增约束：盘中采集开启时，日 K 回填与补历史批避开 09:15–15:05（§4.2）。这一条同时写进源契约 §9.2、§9.3 的实现单（A2、C2）。

## 7. 需要用户本人定的问题（推荐 / 保守默认）

| # | 问题 | 推荐 | 保守默认 |
| --- | --- | --- | --- |
| Q1 | 做 T 只看持仓，还是也看自选 | 只看持仓；自选压后 | 只看持仓 |
| Q2 | 盘中频率 | 持仓最多 20 只每 1 分钟，自选不采集，盘后补齐全部 | 获批前不采集；获批后先用 C 档（每 5 分钟） |
| Q3 | 是否同意把通达信分钟线目录只读挂进容器并导入 | 同意，只导 A 股 | 不挂载，不导入 |
| Q4 | 是否批准分钟线首次实调（单 D 分钟线部分） | 批准约 10 次小实调，核对时延、成交量单位、lt 覆盖 | 不调 |
| Q5 | 信号阈值（偏离、量比） | 2% 与 2 倍作为初值，复测后再调 | 只显示指标，不发信号 |
| Q6 | 分钟线保留期 | 1 分钟 3 年，5 分钟历史全部保留 | 不自动删除 |
