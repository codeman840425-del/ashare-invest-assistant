# 正式日 K 数据契约（T-A128，主线补缺第 1 项）

状态：draft，架构契约，不代表已实现。基线 main `965598b`。适用范围是 Phase 2 最小闭环，也就是盘后求值和日报所需的日 K，不含分钟线、快照、财报和公告。引用只写文件名和函数名/配置项名/用例名。**用户本人已裁定 Q1、Q3、Q4、Q5（含 QB1），落地见 §8（T-A135）；本文其余各节与 §8 冲突处以 §8 为准。**

## 0. 现状（核对结论）

- 生产代码没有任何地方写 `market.daily_bars`。`ingest/owned_quotes.record_quote` 没有调用方，`workers/ingest.py` 只写心跳。
- `workers/daily.py:analyze` 在 `app_env` 不是 test 时记 issue `owned_market_cache_adapter_missing` 并跳过。它读的是 `data_snapshots`（purpose=report、`replay/baseline.VERSION`），不直接读 daily_bars。
- `features/pipeline.prepare` 只接受不复权（adjust=none）日 K 加显式复权因子 A(d)。缺因子时 qfq 价格全为 null，并记 `adjust_factor_missing:<date>`，不会默认按 1 处理。所以**只有日 K、没有复权因子时，策略求值仍然全是缺口**（见 §6 Q2）。
- `daily_bars` 的主键是 (code, trade_date, adj_type)。它没有 pre_close、停牌标记、来源和证书列。读它的地方有 `/portfolio`、`reports/service.build`、`risk/rc1`、`tracking/service`、`intraday/engine`，都不按来源过滤。

## 1. 日 K 来源适配器

- 协议：`DailyBarsSource`（Python `typing.Protocol`），放在新模块 `app/marketdata/daily_bars.py`。
  - 属性 `name: str`，取值 fake 或 mairui。
  - 方法 `fetch(codes: Sequence[str], start: date, end: date, adjust: BarAdjust) -> DailyBarsResult`。这是同步调用，不允许重试，也不允许跟随重定向。
  - `DailyBarsResult` 是冻结的 dataclass，包含：
    - `bars: list[DailyBar]`，字段 code、trade_date、open、high、low、close、pre_close、volume、amount、adj_type、is_suspended；
    - `gaps: list[BarGap]`，字段 code、trade_date|None、reason（只用 `schemas/enums.GapReason` 的值）、issue；
    - `halted: str | None`，记录停机原因。
  - 单位固定为 CNY/股、股、CNY，与 `replay/baseline.payload` 和 `features/pipeline.prepare` 的检查一致；指数行按 `tracking/service` 的现有口径。
- 范围：由 `daily_universe(conn, owner, trade_date) -> list[str]` 计算，取下面几类的并集：
  - 持仓：沿用 `api/v1/portfolio._account(...).positions`，与 `analyze` 一致；
  - 自选：~~是否纳入见 Q4。澄清前只取持仓，不读 `watchlist_items`。~~ **已由 T-A135 取代**：纳入本人有效自选，见 §8.2。
  - active 的 `strategy_instances` 中 scope=security 的 `security_code`。scope=account 已被持仓∪自选覆盖；watch_group 本单不展开。是否纳入见 Q4，澄清前不纳入；
  - 基准 `000300.SH`：`tracking/models.benchmark_code` 和 H-01/W-01 的 F50 需要它。它的可得性见 Q6，澄清前只在 fake 源里给出。
  - 只取证券主数据中 type 为 stock 且 listed 的标的，与 `analyze` 的 `security_not_eligible` 判定相同；基准是例外。
- 写入唯一入口：新增 `upsert_daily_bars(conn, result, *, source, licence_id, fetched_at) -> UpsertStats`，放在 `app/marketdata/daily_bars.py`。仓库里现在没有可复用的 daily_bars 写入函数，`record_quote` 写的是 data_snapshots，不能复用。其他模块不得直接 insert daily_bars，由测试做静态断言。
- 幂等键：(code, trade_date, adj_type)，也就是现有主键。
  - 同键、同值：不做任何事。
  - 同键、不同值：**不覆盖**。保留已有行和它的 fetched_at，以免破坏 PIT 的 first_seen_at；记 issue `daily_bar_conflict:<code>:<date>`，留给人工处理（Q8）。
- 表结构（迁移，见实现单 A）：新增可空列 `pre_close`、`is_suspended`，以及 `source`（fake/mairui，非空）和 `source_licence_id`（可空）。`source_licence_id` 暂不进入主键，见 §6 Q7。
- 缺口机制：沿用 analyze 的 `issues` 字符串和 `reports/service._gap`，reason 用 `GapReason`。新增的 issue 名：
  - `daily_bars_source_off`
  - `daily_bars_not_ready`
  - `daily_bars_missing:<code>`
  - `daily_bars_upstream_halted`（reason 为 upstream_error）
  - `daily_bars_quota_deferred`（101，reason 为 quota_deferred）
  - `daily_bars_http_budget_unset`
  - `calendar_not_covered`
- 交易日历：先调用 `reports/service.covered(conn, date)`。
  - 抛出 CALENDAR_NOT_COVERED 时，记 `calendar_not_covered` 并停止，不发起取数。
  - 非交易日直接 no-op。
  - 只为 is_open 的日子写行。
- 停牌：
  - 来源明确报告停牌时，写 `is_suspended=true` 的占位行，OHLC 为空。快照构建时这一天转成 gaps，reason 为 suspended，对应 `prepare` 的停牌语义，停牌日不计入有效 K。
  - 交易日没有任何行，且来源没有说明停牌时，记 `daily_bars_missing`，reason 为 no_source，**不推断为停牌**。
- 记录运行：沿用 `pipeline_runs`，kind=daily_batch，step=`daily_bars.fetch`。stats 只写计数和 issue，不写代码明细之外的私有数据。

## 2. 解除 analyze 的 test-only 闸

- 配置项：`Settings.daily_bars_source: Literal["off","fake","mairui"] = "off"`，环境变量 `DAILY_BARS_SOURCE`，命名沿用 `data_licence_settings_enabled`、`master_snapshot_path` 的扁平 snake_case 风格。
  - fake 只在 `app_env` 为 test 时允许；其他环境由启动校验拒绝，以免假数据流进用户的 `/portfolio`。
  - mairui 另需 §4 的用户授权回执。
- 新的放行条件，替换 `analyze` 中「app_env 不是 test 就跳过」那一支，**三条同时满足才求值**：
  1. `daily_bars_source` 不是 off；
  2. 当日 `daily_bars.fetch` 运行状态为 ok 或 partial；
  3. 本人当日 owned 快照已构建。新增 `build_owned_snapshot(conn, owner, date) -> uuid`，写 data_snapshots，purpose=report，schema_version=`owned-daily-v1`。instrument 结构与 `replay/baseline.payload` 相同：bars、gaps、sessions 取自 trading_calendar，first_seen_at 取 fetched_at；factors 见 Q2。
- 不满足时的处理：
  - off：issue 仍用 `owned_market_cache_adapter_missing`，保持现有日报的 gap 文案和测试不变。
  - 没就绪：记 `daily_bars_not_ready`。
  - 都继续出日报（`report_task` 不变）。
- 部分数据：缺 bar 的标的走现有 `owned_source_security_missing:<code>`，或由 `prepare` 产出 `daily_bar_missing`/`adjust_factor_missing`，进 `evaluated_input_gaps`。**不假造建议、置信度或止损**，也不以前值补齐。
- tb70 合成快照（VERSION）仍只在 `require_isolated` 下可用。owned 快照必须带本人 licence_id，fake 源除外，fake 的 licence_id 为空且只限 test。`analyze` 里 `licence_id.is_(None)` 的过滤要随之区分两种 schema。`reports/dimensions.load_inputs` 同样要接受 `owned-daily-v1`。
- **不在本单**：`workers/signal_rt.tick`、`intraday/engine`（compute/handoff/recover）、`intraday/consumer`、`plans/worker` 的 synthetic 闸都不动。

## 3. 麦蕊调用量估算（不出网，只按代码/文档粒度）

- 接口粒度：仓库里**没有**麦蕊日 K 客户端。plan.md 列的是单标的接口：
  - 历史：`/hsstock/history/{code}.{mkt}/d/{fq}`，带 st/et；
  - 最新：`/hsstock/latest/{code}.{mkt}/d/{fq}?lt=`。
  - 文档里没有批量日 K 接口，ingest.yaml 的 `eod_scope` 写有“批量日 K”，但没有对应接口实测，状态是【待 T003】。
  - 因此按**每标的每复权口径 1 次**估算。
- 持仓数量级：脱敏文档里没有找到。下面按 N≈10–50 只做量级示意，**不是假设**，见 Q1。自选目前为 0，基准 +1。（**已由 T-A135 取代**：范围含自选，调用量与回填量的公式见 §8.3。）
- 首次回填（**已由 T-A135 取代**：近 3 年，见 §8.3）：窗口长度见 Q3。两张卡有 `lookback_trading_days: 120`，预热 62–64 根，这只是参考值。一次 history 调用能否覆盖整个窗口要等 T003 确认。
  - 只要 none：N+1 次，约 11–51 次；
  - 若按 Q2 另取 hfq：约 22–102 次。
- 日常增量：每个交易日 latest 调用 N+1 次，约 11–51 次；若取 hfq 则约 22–102 次。持仓变化时只为新标的补回填。
- 限流（不放宽）：
  - `master/daily_delivery.DAILY_HTTP_LIMIT=1` 和 `live_budget_issue()` 原样保留，它们管的是 18:00 名单，与本单无关、不借用。
  - 新增独立常量 `DAILY_BARS_HTTP_LIMIT`，默认值 0，以 0 作为默认关闭的保险（Q1 裁定后的取值空间与判定见 §8.1，默认值仍为 0）。超出时记 `daily_bars_http_budget_unset` 或 `daily_bars_quota_deferred`，不发请求。改数值必须有用户原话加评审提交，不能通过回执、环境变量或客户端参数放宽。
  - `ingest.yaml` 的 budget/shares/licences 现值不动，日 K 归 other 份额、p1_daily 优先级，并发为 1。
- 停止规则：
  - 只经 `ingest/egress.mairui_get` 出网，它会先检查 STOP/HALT，再按 `ingest/daily_lists.limited` 和 `ingest/upstream.classify` 判 103/429，并 `_write_halt`。
  - 遇到 STOP、HALT、103、429，或 `DailyHaltError`/`EgressDenied`，**整批立即停**，不重试，剩余标的记 `daily_bars_upstream_halted`。
  - HALT 不由代码清除。

## 4. 离线假源与真实开关

- `FakeDailyBarsSource`：确定性合成。种子取 (code, trade_date)，价格落在 20% 涨跌幅内，参照 `replay/baseline.payload` 的写法；因子行只在测试场景显式给出，并标注合成（值 1，带 available_at）；正式口径见 Q2，可选夹具 `selfchecks/fixtures/daily_bars_fake.json`。只在 app_env=test 时可用。
- `MairuiDailyBarsSource`：放在 `app/ingest/daily_bars.py`，只有 ingest 进程可以调用。它在 ingest 的 tick 里消费 outbox，kind=`mairui_daily_bars`，模式同 `master/daily_delivery.request` 和 `ingest/daily_lists.process`。worker 不出网。
- 用户授权开关（默认关）：需要同时满足下面三条才会出网，否则不建 outbox、不取证书、不开 socket。
  - `daily_bars_source=mairui`；
  - 运维安装的只读回执 `/run/aia/receipts/mairui-daily-bars.json`，校验沿用 `daily_delivery.read_grant` 的 root-owned 0444 规则；
  - `DAILY_BARS_HTTP_LIMIT` 不是 0（**已由 T-A135 细化**：合法的开放取值只有「不限」哨兵，见 §8.1）。
- 必测用例（建议名）：
  - `test_daily_bars_default_off_no_writes`
  - `test_fake_source_refused_outside_test_env`
  - `test_fake_source_deterministic_and_idempotent`
  - `test_upsert_conflict_never_overwrites`
  - `test_only_writer_inserts_daily_bars`（静态扫描）
  - `test_non_trading_day_noop_and_calendar_not_covered`
  - `test_suspended_placeholder_becomes_gap_not_bar`
  - `test_universe_holdings_watch_instances_benchmark`
  - `test_mairui_off_opens_no_socket`（transport 和 netguard 探针）
  - `test_mairui_requires_receipt_and_budget`
  - `test_stop_103_429_halts_whole_batch_records_gap`
  - `test_daily_http_limit_unchanged`（断言 DAILY_HTTP_LIMIT=1、DAILY_BARS_HTTP_LIMIT=0）
  - `test_analyze_off_keeps_legacy_issue_and_report`
  - `test_analyze_fake_bars_produces_evaluations`
  - `test_analyze_partial_bars_gaps_no_fabricated_suggestion`
  - `test_missing_factor_stays_gap_not_one`

## 5. 实现单（后端，全部可在没有麦蕊授权时离线完成）

用例写法：`用例名`：Given 输入 / When 动作 / Then 返回、写库、缺口名、是否出网。“出网=否”统一用 transport 探针和 `ingest/netguard` 计数断言为 0。

### A｜写入口 + 假源 + 调度｜中
- 澄清：签名、排程、迁移列、假源注入、停牌用例、测试落点以 §7（T-A130）为准，本小节与 §7 冲突处作废。
- 目标：§1 的协议、`daily_universe`（澄清前只含持仓，Q4）、`upsert_daily_bars`、`FakeDailyBarsSource`、迁移、`daily_bars_source` 配置。另在 `workers/jobs` 注册 `daily_bars_fetch`：~~`slot_jobs` 设钟点（时刻见 Q5，澄清前不排程，只能手动入队）~~（**已由 T-A135 取代**：北京时间 17:15 进 `slot_jobs`，见 §8.4），加入 `LOCKED_TASKS`。
- 文件：
  - 新增 `app/marketdata/daily_bars.py`；
  - `app/db/tables/market.py`；
  - `migrations/versions/` 新增一个迁移；
  - `app/config.py`；
  - `app/workers/jobs.py`；
  - `selfchecks/test_tb_dailybars_*.py`。
- 不做：不出网，不改 ingest，不动 analyze，不改 `/portfolio` 等读方。
- 验收：
  - `test_daily_bars_default_off_no_writes`：Given 默认配置（off）和一个交易日 / When 执行 daily_bars_fetch / Then 返回 0，daily_bars 零写入，pipeline_runs 记 issue `daily_bars_source_off`，出网=否。
  - `test_fake_source_refused_outside_test_env`：Given app_env=local 且 `DAILY_BARS_SOURCE=fake` / When 启动校验 Settings / Then 校验失败，零写入，出网=否。
  - `test_fake_no_bars_for_day`：Given fake 源当日对全部标的都不出 bar / When fetch / Then daily_bars 零新增，每个标的记 `daily_bars_missing:<code>`（no_source），运行状态 partial，出网=否。
  - `test_fake_partial_codes_missing`：Given 3 个标的中 1 个无 bar / When fetch / Then 写 2 个标的的行，记 1 条 `daily_bars_missing:<code>`，状态 partial，出网=否。
  - `test_fake_source_deterministic_and_idempotent`：Given 同一日同一范围 / When 连续 fetch 两次 / Then 第二次 inserted=0、unchanged=全部，fetched_at 不变，无新 issue。
  - `test_upsert_conflict_never_overwrites`：Given 已有行，再次写入同键但 close 不同 / When upsert / Then 原值与 fetched_at 不变，记 `daily_bar_conflict:<code>:<date>`。
  - `test_only_writer_inserts_daily_bars`：Given 扫描 src/backend/app / When 静态检查 / Then 只有 `upsert_daily_bars` 含对 daily_bars 的写语句。
  - `test_non_trading_day_noop_and_calendar_not_covered`：Given 休市日；另一组为日历未覆盖的日期 / When fetch / Then 休市日零写入、无 issue；未覆盖日期零写入并记 `calendar_not_covered`；出网=否。
  - `test_suspended_placeholder_becomes_gap_not_bar`：Given fake 源报告某标的当日停牌 / When fetch 后构建快照 / Then 写一行 is_suspended=true、OHLC 为空，快照里该日进 gaps（suspended），不进 bars。
  - ~~`test_universe_holdings_only_until_clarified`~~（**已由 T-A135 取代**，改为 `test_universe_holdings_and_active_watchlist`，见 §8.2）：Given 持仓 2 只、自选 1 只、scope=security 实例 1 个 / When 计算 daily_universe / Then 只返回持仓 2 只（Q4 澄清前）。

### B｜owned 快照 + 解除 analyze 闸｜中｜依赖 A 的接口，可与 C 并发
- 实施契约见 `docs/contracts/daily-snapshot-from-bars.md`（T-A133）。本小节和 §2 与它冲突时，以新文件为准。
- 目标：§2 的 `build_owned_snapshot`、analyze 的三条放行条件、`reports/dimensions.load_inputs` 接受新 schema，以及日报 gap 文案。
- 文件：
  - 新增 `app/marketdata/daily_snapshot.py`；
  - `app/workers/daily.py`；
  - `app/reports/dimensions.py`；
  - `app/reports/service.py`（仅 gap 文案）；
  - 对应 selfchecks。
- 不做：不动 signal_rt、intraday、plans/worker 的闸；不实现真实因子来源（Q2）。
- 验收：
  - `test_analyze_off_keeps_legacy_issue_and_report`：Given off / When 依次跑 daily_analysis 和 daily_report / Then evaluations 为空，issues 含 `owned_market_cache_adapter_missing`，日报照常生成且 gaps 含该项，出网=否。
  - `test_analyze_not_ready_no_bars_today`：Given fake 已开但当日 fetch 未运行 / When 跑 daily_analysis / Then 不求值，issue 为 `daily_bars_not_ready`，suggestions 零写入，日报照常生成。
  - `test_analyze_partial_bars_gaps_no_fabricated_suggestion`：Given 2 只持仓中 1 只当日无 bar / When 跑 analyze / Then 有 bar 的那只正常求值；缺 bar 的那只记 `owned_source_security_missing:<code>` 或 `daily_bar_missing:<date>`，不给它生成建议、置信度或止损。
  - `test_analyze_fake_bars_produces_evaluations`：Given test 环境、fake 源完整、有显式合成因子 / When 跑 analyze / Then 每个标的都有 evaluation，simulation=true，source_hash 等于该 owned 快照的 hash。
  - `test_missing_factor_stays_gap_not_one`：Given 有 bars 但没有因子行 / When 跑 analyze / Then qfq 特征为 null，gaps 含 `adjust_factor_missing:<date>`，不用 1 补。
  - `test_owned_snapshot_idempotent_rerun`：Given 同一 owner、同一日、bars 不变 / When build_owned_snapshot 跑两次，analyze 也跑两次 / Then 快照 id 相同，data_snapshots 只有一行，suggestions 不重复归档。
  - 回归：test_tb76_assembly、test_tb76_daily、test_p2n04 中受影响的用例，以及 p2n10 第一切片，全部保持绿。

### C｜麦蕊适配器（开关默认关）｜中｜依赖 A 的写入口，与 B 文件不重叠
- 目标：§4 的 `MairuiDailyBarsSource`、outbox kind、回执读取、`DAILY_BARS_HTTP_LIMIT=0`、§3 的停止规则；全部用假 transport 测试。
- 文件：
  - 新增 `app/ingest/daily_bars.py`；
  - `app/workers/ingest.py`（tick 挂钩）；
  - `app/master/daily_delivery.py` 只读复用，不修改；
  - selfchecks。
- 不做：不安装回执，不改限额，不做实调。
- 验收：
  - `test_mairui_off_opens_no_socket`：Given `daily_bars_source` 为 off 或 fake / When 跑 ingest tick 加 daily_bars_fetch / Then 不建 outbox、不读证书，transport 调用 0 次，没有任何连到麦蕊主机的连接。
  - `test_mairui_requires_receipt_and_budget`：Given 选了 mairui，但分别缺回执、或 `DAILY_BARS_HTTP_LIMIT=0` / When fetch / Then transport 0 次，分别记 `data_licence_unavailable` 类缺口或 `daily_bars_http_budget_unset`，零写入。
  - `test_budget_cap_reached_defers_rest`：Given 假设上限为 2（只在测试里 monkeypatch）、范围 5 只 / When fetch / Then transport 恰好 2 次，其余 3 只记 `daily_bars_quota_deferred`，不在当日重试。
  - `test_stop_103_429_halts_whole_batch_records_gap`：Given 假 transport 第 2 次返回 103（另两组分别是 429，以及运行前已有 STOP 文件）/ When fetch / Then 103/429 组 transport 只调用 2 次，STOP 组 0 次；写入 HALT（沿用 `_write_halt`），剩余标的记 `daily_bars_upstream_halted`，不重试，下一次 tick 在 HALT 存在时 0 次。
  - `test_daily_http_limit_unchanged`：Given 导入模块 / Then `daily_delivery.DAILY_HTTP_LIMIT` 为 1，`live_budget_issue()` 结果不变，`DAILY_BARS_HTTP_LIMIT` 为 0；test_tb90_* 和 test_tb116b 的现有断言原样通过。
  - `test_mairui_rerun_idempotent_no_extra_calls`：Given 当日已成功取过 / When 再跑一次 / Then transport 0 次（已就绪的标的跳过），daily_bars 不变。

**留给用户**：安装回执、~~给出 DAILY_BARS_HTTP_LIMIT 的数值~~（**已由 T-A135 取代**：用户定为不设上限，见 §8.1）、首次实调。这些都需要用户本人批准麦蕊实调或出网。

## 6. 待澄清（澄清前实现单一律按最保守做法）

| # | 问题 | 为何拿不准 | 可选答案 | 澄清前做法 |
|---|---|---|---|---|
| Q1 | 持仓数量级 N 与每日调用上限 | 脱敏文档里没有；原始文件含敏感信息，不读 | 用户给 N 和上限；或按实际持仓数自动计算并设上限 | `DAILY_BARS_HTTP_LIMIT=0`，不出网；估算只作示意。**已裁定（T-A135）**：不设每日上限，以「不限」哨兵表达，默认仍为 0，见 §8.1 |
| Q2 | 复权因子来源/口径 | `prepare` 必须有显式 A(d)；hfq/none 比值有舍入误差；除权接口未实测 | 另取 hfq 推因子（调用翻倍）；用专门的除权接口；只用不复权、qfq 特征暂缺 | 只存 adjust=none，不推因子；求值保持 `adjust_factor_missing` |
| Q3 | 首次回填窗口长度 | 卡的 lookback 是 120，预热 62–64；一次调用能否覆盖整个窗口未实测 | 120 个交易日；按卡的最大预热取；更长 | 实现单 A 把窗口做成参数，不设默认值；没有值就不回填。**已裁定（T-A135）**：首次回填近 3 年；仍是参数、无默认，由 CLI 手动触发，前置为 upsert 分批，见 §8.3 |
| Q4 | 自选与 scope=security 实例是否纳入取数范围 | 契约 eod_scope 写的是“自选与持仓”，但自选没有写入口；实例标的会增加调用量 | 只持仓；持仓+自选；再加实例标的 | 只取持仓。**已裁定（T-A135）**：持仓 + 本人有效自选，不含实例标的，见 §8.2 |
| Q5 | 取数钟点与就绪截止 | plan 写 15:30–16:30；麦蕊日 K 发布时间未实测 | 16:30；17:00；失败后重试一次 | 不进 slot 排程，只能手动或测试入队。**已裁定（T-A135）**：交易日北京时间 17:15 进 `slot_jobs`，不重试，见 §8.4 |
| Q6 | 基准 000300.SH 的接口与主数据 | plan 标注【待 T003】，指数可能不在主数据中 | 用指数接口；不取，F50 记缺口 | 不取，F50 和基准相关的跟踪保持缺口 |
| Q7 | `source_licence_id` 是否进主键 | plan 的 per_licence 规则要求进；当前读方都不过滤 | 现在就升主键并让读方过滤；单用户期只加列 | 只加可空列，记录来源，不用于共享 |
| Q8 | 同键不同值（上游修正）怎么处理 | 覆盖会破坏 PIT；不覆盖可能保留错误值 | 不覆盖并告警；新建版本；人工确认后覆盖 | 不覆盖，记 `daily_bar_conflict` |

## 7. 单 A 澄清（T-A130）

输入是后端 T-B127 预读（`/workspace/team/reports/T-B127-preread.md`）列出的 9 条歧义，编号 ①–⑨ 与该报告一致。本节只补实现单 A；**本节与 §1、§4、§5.A 不一致处以本节为准**。原则：最小可用，与 §6 Q3/Q5/Q7 的保守默认一致。引用只写文件名、函数名和用例名。

### ① 任务签名、入口与用户范围

- 结论：沿用现网任务约定，**不另立签名**。965598b 里还没有 `daily_bars_fetch`；所谓「现网签名」指 `workers/daily.analysis_task` / `report_task` 的 `(settings, trade_date: str, user_id: str | None = None) -> int`，worker 按 `fn(settings, **args)` 调用（`workers/jobs.worker_tick`）。
  - 任务名常量 `DAILY_BARS_FETCH`，值为 daily_bars_fetch。实现函数 `daily_bars_fetch_task(settings, trade_date: str, user_id: str | None = None, window_trading_days: int | None = None) -> int`，放在 `app/marketdata/daily_bars.py`，由 `workers/jobs.TASKS` 注册，并加入 `LOCKED_TASKS`。**不加入** `RETRY_TASKS`（§1 不允许重试）。
  - 任务只做三件事：按配置选源、开连接、调用纯函数 `fetch_and_record(conn, source, *, trade_date: date, user_id: uuid.UUID | None, window_trading_days: int | None) -> int`（同模块）。测试用它注入自定义假源，不必经 Settings。
  - 返回值是本次 `inserted` 行数（与 `jobs.Task` 注释「处理条数」一致）。off、mairui（C 之前）、休市、日历未覆盖时都返回 0。
  - 用户范围：`user_id` 给定时只取该用户；缺省时取全部 approved 用户（与 `workers/daily.phase` 的 owners 查询同口径），按用户逐个算 `daily_universe` 后去重排序，一次 fetch。
  - `daily_bars_source=mairui` 而 C 未落地：零写入、不出网、不建 outbox；pipeline_runs 记 skipped 和 issue `daily_bars_http_budget_unset`（`DAILY_BARS_HTTP_LIMIT` 默认 0，C 落地后同名 issue 语义不变）。
- 理由：调用方（worker、`recover_task` 风格的手动入队）不必改；返回 int 符合 `Task` 类型。无参入口没有现网先例。
- 迁移路径：无，因为没有旧调用方。
- G/W/T：
  - `test_task_registered_locked_not_retried`：Given 导入 `workers/jobs` / Then `TASKS` 中 daily_bars_fetch 指向 `daily_bars_fetch_task`，它在 `LOCKED_TASKS` 中、不在 `RETRY_TASKS` 中；`inspect.signature` 的参数依次为 settings、trade_date、user_id（默认 None）、window_trading_days（默认 None）。
  - `test_task_user_scope_union_and_single`：Given 用户 u1 持仓 A、B，u2 持仓 C，fake 源 / When 分别以不给 user_id、user_id=u1 执行 / Then 前者写 A、B、C 各 1 行，返回 3；后者在空表上只写 A、B，返回 2。
  - `test_mairui_before_c_is_inert`：Given app_env=test、`daily_bars_source=mairui` / When 执行任务 / Then 返回 0，daily_bars 零写入，pipeline_runs 一行 skipped，issues 含 `daily_bars_http_budget_unset`，出网=否。

### ② 回填窗口参数与单日取数

- 结论：窗口只作为任务参数 `window_trading_days`，**不进 Settings，无默认值**。
  - 为 None 时只取 `trade_date` 当日（start=end=trade_date）。这是单日取数，不算回填，与 Q3「没有值就不回填」不冲突。
  - 为正整数 N 时，取 trading_calendar 中 `date <= trade_date` 且 is_open 的最近 N 天，闭区间 [最早一天, trade_date]，一次 fetch。日历里不足 N 个开市日时，记 `calendar_not_covered`，零写入。
  - 非正整数在任何写库之前抛 ValueError。
  - 只有手动入队或测试会传这个参数（见 ③）。
  - 窗口模式下，同一标的多日缺失只记一条 `daily_bars_missing:<code>`；stats.missing 记（标的，日）对数。
- 理由：Q3 要求参数化、无默认；单日是 A 验收的基本形态。
- G/W/T：
  - `test_single_day_when_no_window`：Given 日历 11-06、11-09、11-10 开市，持仓 1 只 / When 以 trade_date=11-10 执行且不给窗口 / Then 只写 11-10 一行。
  - `test_window_backfills_open_days_only`：Given 同上 / When window_trading_days=3 / Then 写 11-06、11-09、11-10 三行，周末 11-07、11-08 无行。
  - `test_window_exceeds_calendar_records_not_covered`：Given 日历只含上述 5 天 / When window_trading_days=10 / Then 零写入，issues 含 `calendar_not_covered`。
  - `test_window_non_positive_rejected`：Given window_trading_days 为 0 或 -1 / Then ValueError，daily_bars 与 pipeline_runs 都零写入。
  - `test_no_settings_field_for_window`：Given `Settings.model_fields` / Then 不含任何回填窗口字段。

### ③ slot_jobs 与排程

- **本条已由 T-A135 取代**（Q5 已裁定，见 §8.4；「不加入 `schedule()`」仍成立）。原结论：采用预读方案 A。只登记 `TASKS` 和 `LOCKED_TASKS`，不加入 `slot_jobs`，也不加入 `schedule()`，不写恒假开关或注释掉的钟点。§5.A 中「slot_jobs 设钟点」一句作废，Q5 澄清后另开单。
- 理由：`slot_jobs` 一旦列入就会在开市日的钟点窗口入队，`beat_tick` 按间隔入队，两者都违背 Q5「只能手动或测试入队」。
- G/W/T：
  - ~~`test_daily_bars_fetch_never_scheduled`~~（**已由 T-A135 取代**，改为 `test_daily_bars_fetch_slot_1715_open_day_only`，见 §8.4）：Given 一个已覆盖的开市日，北京时间 00:00–23:59 每 5 分钟取一个 now（`covered` 打桩为 True）/ When 调 `slot_jobs(settings, now)` / Then 结果里从不出现 daily_bars_fetch；同时 `schedule(settings)` 的键不含它。

### ④ 迁移与列缺省

- 结论（采用预读方案 A）：
  - `pre_close`：MONEY，可空。
  - `is_suspended`：boolean，可空，无 server_default。旧行保持 NULL；`upsert_daily_bars` 写正常行时写 false，停牌占位行写 true。
  - `source`：text，**可空**。CHECK：为空，或取 fake、mairui 之一。旧行和既有自检里的直接插入保持 NULL；`upsert_daily_bars` 要求 source 非空，否则在写库前抛 ValueError。§1「source 非空」改为「经写入口写入的行非空」。
  - `source_licence_id`：uuid，可空，**不加 FK**（先例是 `market.security_reconciliation_diffs.source_licence_id`），不进主键（Q7）。
  - 复用已有的非空 `fetched_at`，不另加列。
  - 停牌占位行：OHLC、pre_close、volume、amount 全部为空，只有 `is_suspended=true`。
  - downgrade：只要有一行 source 非空就拒绝，抛错且不删数据；否则删除上述 4 列和 CHECK。
- 迁移号：新文件，`down_revision` 为合入时的唯一头。T-A129 的 watchlist 迁移也定为 0031（`docs/contracts/watchlist.md`，分支 docs/T-A129）。**顺延规则**：先合入者用 0031；后合入者把文件名、revision 和 down_revision 顺延到下一个号，并指向先合入者。两边测试都用 alembic `ScriptDirectory.get_current_head()` 动态取头，不写死号码，并断言 `alembic heads` 只有一个。
- 理由：NOT NULL 会让 `test_ta26_rc1`、`test_tb91_fixes`、`test_p2n03_tracking`、`tb49c` 等直接插入 daily_bars 的自检在迁移后失败，而 A 的文件清单不含这些文件。新增一个 legacy 取值又会污染来源语义。
- G/W/T：
  - `test_migration_adds_nullable_columns_single_head`：Given 临时库在 0030 / When upgrade head / Then 4 列存在且都可空，`alembic heads` 只有一个头；插入一行不带 source 的旧式数据成功，插入 source 为非法值的行被 CHECK 拒绝。
  - `test_upsert_requires_source`：Given source=None / When `upsert_daily_bars` / Then ValueError，零写入。
  - `test_downgrade_refuses_when_sourced_rows_exist`：Given 已写一行 fake / When downgrade 到上一版 / Then 失败，行和列都还在；表里没有带 source 的行时 downgrade 成功、列被删除。
  - `test_normal_row_is_suspended_false`：Given fake 正常 bar / When upsert / Then 该行 is_suspended 为 false（不是 NULL）。

### ⑤ UpsertStats、同值比较、issue 和运行状态的落点

- 结论：
  - `UpsertStats` 是冻结 dataclass，字段为 `inserted: int`、`unchanged: int`、`conflicts: int`、`issues: tuple[str, ...]`（只放 `daily_bar_conflict:<code>:<date>`，按字典序）。
  - 同值比较列：open、high、low、close、pre_close、volume、amount、is_suspended。先把入参量化到列精度（MONEY 为 4 位小数）再精确比较，NULL 只与 NULL 相等。**不比较** fetched_at、source、source_licence_id：同值但来源不同算 unchanged，保留原行的来源。
  - 写法：先 `INSERT … ON CONFLICT DO NOTHING RETURNING`；没有插入的键读回比较，分为 unchanged 或 conflict。任何情况都不 UPDATE。
  - 运行记录：`fetch_and_record` 每次执行（休市日除外，见 ⑧）插入一行 pipeline_runs，kind=daily_batch，step=`daily_bars.fetch`，run_date=trade_date。
    - stats 只含：user_id、window_trading_days、codes（标的数）、inserted、unchanged、conflicts、missing、suspended、issues（排序后的字符串列表）。
    - 证券代码可以出现在 issue 字符串里；不得写入数量、成本、账户 id、用户名。
  - 状态：
    - off、mairui（C 之前）、日历未覆盖：skipped；
    - 有 missing 或 conflict：partial；
    - 其余：ok（范围为空时也是 ok，codes=0）；
    - 异常：failed，error 只写异常类型名（同 `workers/daily.phase`）。
  - B 判断「当日就绪」时，取该 run_date 下 started_at 最新的一行（B 的范围，这里只约定 A 不覆盖旧行）。
- 理由：与验收里的 inserted、unchanged 字样对齐；不 UPDATE 满足 Q8；状态取值都在 `pipeline_runs` 现有 CHECK 内，新 step 名与 tb76.* 共存。
- G/W/T：
  - `test_upsert_stats_fields_and_equal_after_quantize`：Given 已有行 close=10.1234，再写 close=10.12340 / Then inserted=0、unchanged=1、conflicts=0。
  - `test_same_values_different_source_is_unchanged`：Given 已有 fake 行，同值以 source=mairui、licence_id 为一个 uuid 写入 / Then unchanged=1，行的 source 仍为 fake。
  - `test_run_row_stats_shape`：Given fake 源、3 只中 1 只缺 / When `fetch_and_record` / Then pipeline_runs 新增一行，step 为 daily_bars.fetch，status partial，stats 键集合恰为上列 9 个，issues 含 `daily_bars_missing:<code>`。

### ⑥ 假源的注入方式与合成算法

- 结论：
  - 构造函数 `FakeDailyBarsSource(*, missing: frozenset[str] = frozenset(), suspended: frozenset[str] = frozenset())`，参数只能按关键字传。
  - **默认对每个请求的标的、[start, end] 内每个日历日各合成一根**；只为 is_open 日写行由 `fetch_and_record` 过滤，非开市日的 bar 被丢弃且不计数。
  - missing 中的标的不出 bar，出 `BarGap(reason=no_source, issue=daily_bars_missing:<code>)`。suspended 中的标的出停牌占位 bar，不出 gap。同一标的两边都有时按 missing 处理。
  - 「全部不出 bar」就是 missing 等于全部标的。不用 json 夹具；§4 提到的 `selfchecks/fixtures/daily_bars_fake.json` 不做。
  - 合成：种子取 sha256(code + "|" + ISO 日期) 的前 8 字节（不用 Python 内置 hash）。
    - pre_close 在 5–50 元之间；
    - close 与 pre_close 的比值在 [0.8, 1.2] 内；
    - open 落在同一带内；
    - high = max(open, close) × (1 + 小量)，low = min(open, close) × (1 − 小量)；
    - 价格量化到 0.01，volume 固定 10000（与 `replay/baseline.payload` 一致），amount = close × volume；
    - adj_type 固定 none（Q2）。
    - 各日独立，不做跨日递推：前一日 close 不必等于后一日 pre_close。
  - 契约不钉死黄金价格。测试只断言：两个实例输出相同；约束成立；同一 (code, date) 结果与调用顺序无关。
  - 不出指数（Q6，A 的范围不含基准），不写 factor_values（因子留给 B）。
- 理由：默认出 bar 符合「确定性合成」的原文，也让 A-5 这类幂等用例成立；无参默认加关键字注入，能让 T-T70 的各个场景同时变绿。
- G/W/T：
  - `test_fake_default_one_bar_per_code_day`：Given `FakeDailyBarsSource()`，两只标的，start=end=11-10 / Then 2 个 bar，is_suspended 为 false，gaps 为空。
  - `test_fake_missing_and_suspended_injection`：Given missing 含 A、suspended 含 B、C 正常 / Then A 只有 gap（no_source），B 是 OHLC 为空、is_suspended 为 true 的占位 bar，C 正常。
  - `test_fake_deterministic_and_bounded`：Given 两个独立实例，同一组 (code, date) / Then 输出完全相同，且 low ≤ min(open, close) ≤ max(open, close) ≤ high，close/pre_close−1 的绝对值不超过 0.2，volume 为 10000。

### ⑦ 停牌验收不依赖 B；suspended 与 GapReason

- 结论：
  - `test_suspended_placeholder_becomes_gap_not_bar` **移到实现单 B**，A 不导入 `app/marketdata/daily_snapshot.py`。
  - A 改用 `test_suspended_placeholder_row_written`（见下）。
  - A 不改 `GapReason`，停牌也不产出 BarGap。快照里「suspended」用哪套字符串空间（`features/pipeline.prepare` 的 gaps 字符串，还是给 `GapReason` 增值）由 B 裁定。
  - 提醒 B：`tracking/service` 读 daily_bars 时不过滤 close 为空的行，B 需要确认这类读方不受占位行影响。`reports/service` 用 close > 0、`/portfolio` 用 close 非空过滤，不受影响。
- 理由：派单要求 A 的验收不依赖 B 的模块（快照、解 analyze 闸）。§1 也写明停牌在「快照构建时」才转成 gap。
- G/W/T：
  - `test_suspended_placeholder_row_written`：Given fake 源 suspended 含 B，当日开市 / When `fetch_and_record` / Then B 一行：is_suspended 为 true，OHLC、pre_close、volume、amount 全为空，source 为 fake；stats.suspended=1；无 `daily_bars_missing:B`；状态 ok。
  - `test_impl_a_imports_no_b_module`：Given 静态扫描 `app/marketdata/daily_bars.py` 与 A 的测试文件 / Then 不引用 daily_snapshot 和 `workers/daily`。

### ⑧ covered() 的错误码与休市日运行记录

- 结论：**按现网 `reports/service.covered` 实现，不改 covered**。
  - covered 返回 False：休市，no-op。不插 pipeline_runs，无 issue，返回 0（与 `workers/daily.phase` 遇到休市时直接返回的做法一致）。
  - covered 抛 AppError，且错误码为 MAINTENANCE、details 的 issue 为 CALENDAR_NOT_COVERED：视为日历未覆盖。插一行 skipped，issues 为 calendar_not_covered，返回 0。其它 AppError 原样抛出。
  - §1「抛出 CALENDAR_NOT_COVERED」改读为上述判定；`aggregates/calendar` 的 `ErrorCode.CALENDAR_NOT_COVERED` 不在本路径上。
  - 判定顺序：off → mairui（C 之前）→ covered → 窗口 → 范围 → fetch → upsert。也就是说，off 在休市日也会记 skipped 和 daily_bars_source_off。
- 理由：改 covered 会牵动日报和钟点任务，超出 A 的范围。
- G/W/T：
  - `test_non_trading_day_noop_and_calendar_not_covered`（覆盖 §5.A 的同名用例）：Given 日历含 11-08 且 is_open 为 false，不含 11-11，fake 源 / When 分别以 11-08、11-11 执行 / Then 11-08：零写入，pipeline_runs 无新增行，返回 0；11-11：零写入，一行 skipped，issues 恰为 calendar_not_covered；两组都不出网。
  - `test_off_recorded_even_on_closed_day`：Given off，trade_date=11-08 / Then 一行 skipped，issue 为 daily_bars_source_off。

### ⑨ licence_id 的类型

- 结论：采用预读方案 A。签名为 `upsert_daily_bars(conn, result, *, source: str, licence_id: uuid.UUID | None, fetched_at: datetime) -> UpsertStats`。fake 和测试一律传 **None**，原样写入 `source_licence_id`。传入空串或其它非 UUID、非 None 的值时，在写库前抛 TypeError，**不做空串到 None 的规范化**。
- 理由：列是 uuid；Q7 只加可空列。
- G/W/T：
  - `test_licence_id_none_written_as_null`：Given licence_id=None / Then 行的 source_licence_id 为 NULL。
  - `test_licence_id_empty_string_rejected`：Given 空串 / Then TypeError，零写入。

### 测试落点、临时库与种子（定死）

- **放哪里**：A 的验收只有一套，放在 `tests/backend/unit/test_daily_bars_source_impl_a_t_t70.py`，由测试组 T-T70 维护（测试左移）。
  - 后端 T-B127 **不新增** `selfchecks/test_tb_dailybars_*.py`；§5.A 文件清单中这一项作废。
  - 依据：selfchecks 的集成库是 `selfchecks/test_tb70_replay.integration`，它断言 alembic 停在 0020，放不下新列；tests/backend/unit 已有 o61 临时库约定（`tests/backend/pg_o61.py`）。
  - T-T70 需要按本节调整：
    - 任务经 `jobs.TASKS` 查到后按 `(settings, trade_date=…, user_id=…)` 调用；
    - 场景用 `fetch_and_record` 加 `FakeDailyBarsSource(missing=…, suspended=…)`；
    - licence_id 传 None；
    - 「返回 0」只断言 int 0；
    - 停牌加快照的用例移给 B。
- **临时库先跑迁移**：
  - 沿用 `pg_o61.guard_temp_pg`（先核端口归属）、`template_db_name()`（默认 o61_tmp_0030）和 `validate_temp_db_name`，以 `CREATE DATABASE <tt70_…> TEMPLATE <模板>` 建库，断言 alembic_version 为 0030。
  - **然后只对临时库**执行 alembic upgrade head：URL 由 `libpq_sqlalchemy_url(临时库)` 经 `-x url=` 传入，不打印。断言版本等于 `ScriptDirectory.get_current_head()`。
  - 不升级、不改模板库；finally 里删除临时库；建库失败时 skip（同 `test_ta95_r6_g1_g3_t_t61`）。
  - 不起新实例，不做端口转发。
  - 纯单元用例不连库：Settings 校验、静态扫描、假源确定性、slot_jobs/schedule、签名。
- **种子**：需要，全部虚构，只写进临时库。
  - trading_calendar：先清空临时库里的这张表，再插 5 行：11-06 开、11-07 休、11-08 休、11-09 开、11-10 开（2026 年）；11-11 不插，用作未覆盖日。
  - securities：3 只 type=stock、listing_status=listed 的标的 A、B、C（列只填非空列 code、type、name、exchange）；外加 1 只 type=etf 的 D，用于资格过滤。代码沿用仓库已有合成夹具里用过的代码，**不得取自用户持仓文件或任何含股东代码的材料**。
  - users：u1、u2，都是 approved。
  - 持仓链（形状同 `test_tb74_candidates.setup`）：每个用户 accounts 1 行 → import_batches 1 行（committed、positions）→ broker_position_snapshots 1 行（version_no=1）→ broker_position_snapshot_items。u1 持 A、B，u2 持 C，D 挂在 u1 下验证资格过滤。
  - 仅 `test_universe_holdings_only_until_clarified` 额外需要：watchlist_items 1 行（u1、代码 E）和 1 个 scope=security 的 active strategy_instance（代码 F，链路同 `test_tb74_candidates.setup`）；断言只返回 A、B。

### 留给用户（不自行假设）

本节没有新增需要用户定的产品问题。~~Q3（窗口长度 N）、Q5（钟点）、Q1、Q2、Q4、Q6、Q7、Q8 仍按 §6 的保守做法执行，等用户答复。~~ **已由 T-A135 取代**：Q1、Q3、Q4、Q5 已裁定（§8）；Q2、Q6、Q7、Q8 仍按 §6 保守做法。

### T-T70 补充裁定（T-A131）

输入是测试 T-T70 报告（`/workspace/team/reports/T-T70.md`，分支 test/T-T70 的 `efc8cb8`）「剩余歧义」一节。该节共 7 条：第 1–6 条是技术歧义，在这里逐条裁定；第 7 条是 Q3/Q5，仍归用户，见文末。本小节只是补充，与 §7 ①–⑨ 和 Q3/Q5 的保守默认（窗口没有默认值、不自动回填；不排程、只能手动入队）一致。本小节与 §5 文首、§7 种子段不一致的地方，以本小节为准。

#### 补1　「回填窗口字段」的名单

- 结论：`Settings.model_fields` 中**任何字段名**（不区分大小写）都不得含有 window、backfill、lookback 这三个子串。另外，以 daily_bars_ 开头的字段只允许 `daily_bars_source` 一个。环境变量由字段名派生，所以不再单列。
- 理由：§7 ② 规定窗口只是任务参数（`daily_bars_fetch_task` / `fetch_and_record` 的 `window_trading_days`）。965598b 的 `app/config.py` 里现在没有字段含这三个子串，按子串断言不会误伤；只列举名字则会漏掉 `daily_bars_backfill_days` 这类变体。
- G/W/T：`test_no_settings_field_for_window`：Given `Settings.model_fields` / When 遍历字段名 / Then 没有字段名含 window、backfill、lookback；以 daily_bars_ 开头的字段名集合恰为 {daily_bars_source}。

#### 补2　`daily_universe` 的返回顺序

- 结论：`daily_universe(conn, owner, trade_date) -> list[str]` 返回**去重后按代码字符串升序**排列的列表（Python `sorted` 的顺序）。`fetch_and_record` 在多用户时，取各用户结果的并集，同样去重升序后再 fetch 一次（与 §7 ① 的「去重排序」相同）。
- 理由：返回值用 list 而不是 set，测试和 stats.codes 才能复现；`api/v1/portfolio` 读 daily_bars 时也用 `sorted(codes)`。
- G/W/T：`test_universe_holdings_only_until_clarified`：Given §7 种子以及 universe 专用的附加种子 / When `daily_universe(conn, u1, 11-10)` / Then 返回值**列表相等**于 sorted([A, B])，不再只比较集合。

#### 补3　种子里的 listing_status 必须写

- 结论：**必须写**。A、B、C、D 都写 `listing_status=listed`（T-A135 起，§8.2 新增的自选种子 E、E2 同样必须写）。§7 种子段「列只填非空列 code、type、name、exchange」改读为「填这 4 个非空列，再加 listing_status」。`daily_universe` 的资格过滤与 `workers/daily.analyze` 的 `security_not_eligible` 判定相同：type 为 stock 且 listing_status 为 listed 才纳入。**listing_status 为空也视为不合格**，不按 listed 推断。
- 理由：`market.securities.listing_status` 是可空列；`workers/daily.analyze` 对空值判为不合格。不写这一列，A、B 会被过滤掉，用例会误红。
- G/W/T：同一个用例 `test_universe_holdings_only_until_clarified`：Given 附加种子里再加一只证券 G（type=stock，listing_status 为空），并把 G 挂进 u1 的持仓快照 / Then 返回值里没有 G，也没有 D（etf）、E（自选）、F（实例）。

#### 补4　出网探针：测试怎样证明没有出网

- 结论：在单 A 里，「出网=否」只用下面两个探针证明，**不再使用** `ingest/netguard.netguard_blocks()` 的计数（它是恒返回 0 的占位）。测试**不调用** `netguard.install()`，因为钩子装上后无法卸载，会污染同一进程里的其它用例。
  1. socket 探针（写法同 `selfchecks/test_tb90_daily_pipeline` 的 guarded connect）：monkeypatch `socket.socket.connect` 和 `connect_ex`。放行 AF_UNIX，以及 AF_INET/AF_INET6 下的回环地址（127.0.0.0/8、::1，临时库就在回环上）；其它地址一律记录并抛 OSError。用例结束时断言记录为空。
  2. 入口探针：monkeypatch `ingest/egress.mairui_get`，改成计数后抛错的桩，断言计数为 0。
  3. 静态约束：`app/marketdata/daily_bars.py` 不得在模块顶层导入 `app.ingest.egress`、`app.ingest.netguard`、socket、httpx、requests、urllib.request。实现单 C 落地后，选源时需要的 `app/ingest/daily_bars.py` 只能在函数内延迟导入，不在这条禁令的名单里。
- 理由：单 A 没有 transport（transport 属于实现单 C），§5 文首说的「transport 探针」在 A 里没有对象。netguard 计数不能证明任何事。仓库里已有 guarded connect 的先例。
- G/W/T：
  - 所有标「出网=否」的 A 用例：Given 上述两个探针 / When 执行用例 / Then socket 探针的记录为空，并且 mairui_get 计数为 0。
  - `test_impl_a_has_no_network_imports`（新增，纯静态，不连库）：Given 解析 `app/marketdata/daily_bars.py` 的顶层 import / Then 不含上面列出的模块。

#### 补5　第二次 fetch 的 unchanged 落在哪里

- 结论：`fetch_and_record` 和 `daily_bars_fetch_task` 都**只返回 int（inserted）**，不返回 UpsertStats。`UpsertStats` 只是 `upsert_daily_bars` 的返回值。「第二次 unchanged=全部」写在**第二次运行新插入的那一行 pipeline_runs 的 stats.unchanged**。每次运行都插入新行，不更新旧行（§7 ⑤）。
- 理由：§7 ① 规定返回值为 int，这符合 `jobs.Task`；§7 ⑤ 已把 unchanged 列为 stats 的 9 个键之一。两处并不冲突，只是读取的位置不同。
- G/W/T：`test_fake_source_deterministic_and_idempotent`：Given u2（持 C）在 11-10 已用 fake 源跑过一次 / When 在新事务里再跑一次 `fetch_and_record` / Then 返回 0；daily_bars 的（code, trade_date, adj_type, fetched_at）集合不变；最新一行 pipeline_runs 的 stats 中 inserted 为 0、conflicts 为 0、unchanged 等于第一次运行后 daily_bars 的行数，issues 不多于第一次。

#### 补6　任务怎样拿数据库连接

- 结论：沿用 `workers/daily.phase` / `recover_task` 的做法，**不新增 Settings 字段**。
  - `daily_bars_fetch_task` 在函数体内延迟导入 `app.workers.jobs._engine`，避免与 `jobs.TASKS` 循环导入。它用 `_engine(settings)` 取引擎，连接串来自 `Settings.database_url`；值为 None 时 `_engine` 抛 RuntimeError，此时零写入。
  - 任务先校验参数，再开连接。参数错误包括 window_trading_days 不是正整数、user_id 不是合法 uuid 字符串，都抛 ValueError，并且两张表都不写。这一步排在 §7 ⑧ 的 off 判定之前。
  - 校验通过后，任务用一个 `engine.begin()` 事务完成选源、off/mairui 判定和 `fetch_and_record`。bars 和本次 pipeline_runs 行在同一事务里提交。
  - `fetch_and_record(conn, …)` **不自己 begin 或 commit**，事务由调用方负责，测试就是这样用 `engine.begin()` 包着调用的。
  - 事务里抛出异常时整体回滚。任务另开一个 `engine.begin()` 写一行 failed，error 只写异常类型名（同 §7 ⑤），然后原样抛出，由 `jobs.worker_tick` 记录。
  - 不做 advisory lock：并发由 `LOCKED_TASKS` 的 redis 锁负责（§7 ①）；即使重入，upsert 用 ON CONFLICT DO NOTHING，也是幂等的。
- 理由：仓库里每个任务都通过 `jobs._engine(settings)` 拿连接，引擎按 URL 缓存。测试只要把临时库 URL 传给 `Settings.database_url` 就能指向临时库，不必增加注入点。
- G/W/T：
  - `test_task_user_scope_union_and_single`（已有）：Given `Settings(app_env=test, daily_bars_source=fake, database_url=<临时库 URL 的明文字符串>)` / When 经 `jobs.TASKS` 调用 / Then 写入临时库，返回 3。
  - `test_task_without_database_url_raises_no_write`（新增，不连库）：Given 构造 Settings 时显式传 database_url=None（构造参数优先于环境变量和 .env），daily_bars_source 为 fake / When 调用任务 / Then 抛 RuntimeError。
  - 测试注意：`Settings.database_url` 是 SecretStr，必须传字符串。传给它的值应是 SQLAlchemy URL 对象 `render_as_string(hide_password=False)` 的结果，不能直接传 URL 对象，也不能用 `str(url)`（会把密码遮成星号）。这个值不打印、不写日志。

#### 留给用户（不变）

~~Q3（窗口长度 N）和 Q5（取数钟点）仍等用户答复。在答复之前，窗口没有默认值、不自动回填；不进 `slot_jobs`/`schedule()`，只能手动或由测试入队。~~ **已由 T-A135 取代**：见 §8.3（窗口仍无默认、不自动回填）与 §8.4（17:15 进 `slot_jobs`，仍不进 `schedule()`）。本小节不新增需要用户决定的问题。

## 8. 用户裁定落地（T-A135）

依据：`/workspace/team/rules/daily-bars-user-decisions-2026-11-10.md`（编排者记录的用户本人裁定，2026-11-10）。源码按 be/T-B128 `af77bb5` 核对。**本节与 §1–§7、§6 的保守默认冲突处以本节为准**；被推翻的原文已在原处标「已由 T-A135 取代」。Q2（复权因子）本单不改：缺因子仍走 `adjust_factor_missing`，不补 1。Q6、Q7、Q8 不变。

总原则（不因本节放宽）：

- 默认仍不出网。`daily_bars_source` 默认 off；没有运维安装的只读回执就不建 outbox、不开 socket。
- 遇 STOP、HALT、103、429，或 `DailyHaltError`/`EgressDenied`，仍整批立即停、不重试、剩余标的记 `daily_bars_upstream_halted`；HALT 不由代码清除（§3 原文不变）。
- 契约落地并经用户确认的实现合入之前，生产不自动调麦蕊。**真实首次调用仍须用户本人批准**；代理或其他角色转述的「用户同意」不算批准。

### 8.1 Q1：不设每日上限

- 用户原话：不设置上限。表达方式：**一个显式的「不限」取值，而不是把默认值改成不限**。
- 配置名与位置（沿用 `master/daily_delivery.DAILY_HTTP_LIMIT` 的模块常量写法，不进 Settings，不读环境变量或回执）：放在单 C 的 `app/ingest/daily_bars.py`。
  - `DAILY_BARS_HTTP_UNLIMITED`：哨兵常量，值为字符串 unlimited。
  - `DAILY_BARS_HTTP_LIMIT`：默认值仍为整数 0。
- 判定（单 C 新增纯函数 `daily_bars_http_budget(value) -> DailyBarsBudget`，三种结果）：
  - 值为整数 0：**unset**。不建 outbox，transport 0 次，记 `daily_bars_http_budget_unset`，运行状态 skipped。
  - 值等于 `DAILY_BARS_HTTP_UNLIMITED`：**unlimited**。不做每日计数截断；每个标的每复权口径仍只按计划请求，不重试（见下文结构上界）。
  - 值为正整数 n（只允许测试 monkeypatch，生产代码不得出现）：**capped(n)**。第 n 次之后的标的记 `daily_bars_quota_deferred`，当日不重试，沿用 `test_budget_cap_reached_defers_rest`。
  - 其他任何值（负数、布尔、None、其他字符串、浮点）：按 unset 处理，同上，不抛错、不出网。
- 什么时候改成「不限」：单 C 合入时 `DAILY_BARS_HTTP_LIMIT` 仍为 0。另开一张「开放单」（建议单 D），在用户本人批准首次实调之后，以一次经评审的代码提交把它改为 `DAILY_BARS_HTTP_UNLIMITED`，提交说明引用本节与用户 Q1 原话。环境变量、回执字段、客户端参数都不能改变它（§3 原则不变）。
- 「开放真实麦蕊」须同时满足，缺一不出网：
  1. 环境变量 `DAILY_BARS_SOURCE` 为 mairui（运维配置）；
  2. 运维安装的只读回执 `/run/aia/receipts/mairui-daily-bars.json`，按 `daily_delivery.read_grant` 的规则校验（root 属主、0444、目录不可写、在 start–end 有效期内）；
     - **（T-A138 细化，以 be/T-B130=41259c0 的 `ingest/daily_bars.read_daily_bars_grant` 为准，解析方式同 `daily_delivery.read_grant`）**
     - kind：回执的 kind 字段取值为 `mairui_daily_bars`，与日 K outbox 的 kind 共用同一个模块常量 `KIND`。它与名单链路（`daily_delivery`）的 `mairui_daily_snapshot` 是两个不同的值，名单回执 `mairui-daily.json` 不能冒充日 K 回执。
     - 字段集合：JSON 对象的键必须**恰好**是下面 6 个，多一个或少一个都拒绝（例如多带 limit 字段会被拒）：
       - kind；
       - user_id（UUID）；
       - licence_id（UUID）；
       - receipt_id（UUID）；
       - not_before（带时区的 ISO 时间）；
       - expires_at（带时区的 ISO 时间）。
     - 校验项（缺一即拒）：
       - 文件：root 属主、权限恰为 0444、常规文件、不跟随符号链接、不超过 8192 字节；
       - 所在目录：root 属主、组和其他人不可写，路径中不含符号链接；
       - 内容：可解析为 JSON，kind 符合上文；
       - 时间：not_before 与 expires_at 都带时区，且 not_before 早于 expires_at；按注入的 clock 取 now，须满足 not_before ≤ now < expires_at；
       - user_id：与本次拉取的 owner 相同；
       - 不读证书：licence_id 只作记录，不据此读取任何证书或密钥。
     - 违反任意一项时：transport 0 次，零写入，pipeline_runs 记 `data_licence_unavailable`，运行状态为 skipped。
     - 回执里的任何字段都不影响预算。预算只看常量，即 `daily_bars_http_budget(DAILY_BARS_HTTP_LIMIT)`，并且在读回执之前判定（unset 时根本不读回执）。
     - 用例（41259c0 自检）：`test_receipt_expired_is_rejected`、`test_receipt_wrong_kind_is_rejected`、`test_receipt_non_json_is_rejected`、`test_receipt_user_mismatch_is_rejected`，以及正向对照 `test_valid_receipt_still_allows_unlimited_fetch`（仅测试里 monkeypatch 为哨兵）。
  3. `daily_bars_http_budget(DAILY_BARS_HTTP_LIMIT)` 的结果不是 unset（即开放单已合入）；
  4. 单 C 与开放单都已合入。
- 不动：`daily_delivery.DAILY_HTTP_LIMIT` 仍为 1，`live_budget_issue()` 不变；`ingest.yaml` 的 budget/shares/licences 不动；并发仍为 1。
- 结构上界（不是额度，是正确性不变量，单 C 必须满足）：一次运行的 transport 调用次数恰为「计划调用数」，即标的数 × 每标的请求段数（§8.3 的 ceil(W/k)）；提前停止时更少，永不更多。是否在此之外再加一道数值型「每批防失控上限」，见 §8.6 U3；用户答复前不加。
- G/W/T（单 C 测试）：
  - `test_daily_http_limit_unchanged`（改）：Given 导入模块 / Then `DAILY_HTTP_LIMIT` 为 1，`live_budget_issue()` 不变，`DAILY_BARS_HTTP_LIMIT` 为 0，`DAILY_BARS_HTTP_UNLIMITED` 存在且值为 unlimited。开放单合入时，在同一提交里把本例对 `DAILY_BARS_HTTP_LIMIT` 的期望改为哨兵，其余断言不动。
  - `test_http_budget_resolution_table`（新，不连库）：Given 0、哨兵、3、-1、True、None、字符串 0、2.0 / When `daily_bars_http_budget` / Then 依次为 unset、unlimited、capped(3)，其余全部 unset。
  - `test_unlimited_no_cap_calls_equal_planned`（新）：Given monkeypatch 为哨兵、回执与源齐备、假 transport、5 个标的、单日 / When fetch / Then transport 恰 5 次，无 `daily_bars_quota_deferred`，写 5 行。
  - `test_unlimited_still_halts_on_stop_103_429`（新）：Given 哨兵；假 transport 第 2 次返回 103（另两组为 429、运行前已有 STOP）/ Then 103/429 组恰 2 次、STOP 组 0 次，写 HALT，剩余记 `daily_bars_upstream_halted`，不重试；下一次 tick 在 HALT 存在时 0 次。
  - `test_limit_not_widened_by_env_or_receipt`（新）：Given 限额常量为 0，同时设置名为 DAILY_BARS_HTTP_LIMIT 的环境变量为大数、回执 JSON 里多放一个 limit 字段 / Then 仍 transport 0 次，记 `daily_bars_http_budget_unset`。
  - `test_mairui_requires_receipt_and_budget`（不变）。

### 8.2 Q4：范围 = 持仓 + 本人有效自选

- `daily_universe(conn, owner, trade_date) -> list[str]`（签名不变）取并集：
  - 持仓：`api/v1/portfolio._account(...).positions`（不变）；
  - 自选：`watchlist_items` 中 user_id 为 owner、`removed_at IS NULL` 的 security_code（与 `reports/service.build`、`intraday/engine` 读自选的条件相同）。自选代码由 `/watchlist` 写入时已规范化，原样使用，不再变换大小写。
  - **不含**：scope=security 的实例标的（`workers/daily.analyze` 只在代码属于持仓或自选时才求值，实例标的已被覆盖）、watch_group、基准（Q6 不变）、他人的自选。
- 资格过滤对并集整体执行，不变：type 为 stock 且 listing_status 为 listed；listing_status 为空视为不合格。
- 去重升序（`sorted`）。多用户时 `fetch_and_record` 取各用户结果的并集再去重升序（§7 补2 不变）。不按 added_at 做 PIT 过滤：取运行时刻的有效自选。
- 快照范围随之扩大：`daily-snapshot-from-bars.md` 的 `build_owned_snapshot` 直接用 `daily_universe`，自选代码会进本人快照（见该文 §11）。这正好让 `analyze` 对 account 范围实例里的自选代码求值，而不是记 `owned_source_security_missing`。
- 调用量：N 为全体 approved 用户「合格持仓 ∪ 合格有效自选」去重后的个数，N ≤ Σ（持仓数 + 自选条数上限）。自选上限来自权益或 `config/realtime.yaml` 的 `watchlist.per_user_cap`（默认 100）。
- 不需要迁移（`watchlist_items` 已由 0031 提供）。
- G/W/T：
  - `test_universe_holdings_and_active_watchlist`（取代 `test_universe_holdings_only_until_clarified`；§7 种子段与补2、补3 中对旧名的引用都改读为新名）：Given §7 种子与补3 的 G；u1 另有自选 E（stock、listed，有效）、E2（stock、listed，removed_at 有值）、A（与持仓重复）、D（etf）；u2 自选 C2（stock、listed）；实例 F / When `daily_universe(conn, u1, 11-10)` / Then 列表相等于 sorted([A, B, E])：无 E2、D、F、G、C、C2，A 只出现一次。
  - `test_universe_watchlist_only_owner`（新）：Given u1 无持仓、只有有效自选 E / Then 返回 [E]；u2 的结果不含 E。
  - `test_task_user_scope_union_and_single`（Given 加 u2 有效自选 E）：Then 不给 user_id 时写 A、B、C、E；user_id=u1 时不写 E。

### 8.3 Q3：首次回填近 3 年；前置为 upsert 分批

**前置（必须先合入，否则不得触发任何多日窗口的真实回填）：`upsert_daily_bars` 分批。**

- 原因：每行 14 个绑定参数，一条多 VALUES 语句超过 4,681 行（65535 ÷ 14 取整）就会撞 PG 参数上限。3 年窗口下 N 只即约 N × 730 行。
- 做法：
  - 常量 `UPSERT_BATCH_ROWS`，值 1000（`app/marketdata/daily_bars.py`），并在模块导入时断言它乘以每行参数数不超过 65535。
  - 写入前按 (code, trade_date, adj_type) 升序排序，再按 1000 行切块；每块一条 `INSERT … ON CONFLICT DO NOTHING RETURNING`。
  - 每块的读回比较只查本块未插入的键，用 (code, trade_date, adj_type) 元组 IN（顺带完成 T-A132 非阻塞项⑶），不再用三个独立 IN 做笛卡尔范围查询。
  - `UpsertStats` 跨块累加；issues 全局排序去重。签名、返回类型、不 UPDATE 的规则都不变。
- 事务边界：全部块都在调用方的同一个事务里（`fetch_and_record` 仍不 begin/commit；`daily_bars_fetch_task` 用一个 `engine.begin()`），本次运行只写一行 pipeline_runs。任一块出错整体回滚，任务另开事务写 failed（§7 补6 不变）。不做逐块提交：那会让失败的运行留下半截数据，也与「一次运行一行运行记录」冲突。
- 不需要迁移。

**「3 年」的口径**

- 仍走 `window_trading_days` 参数，不进 Settings，没有默认值（§7 ②、补1 不变：Settings 字段名仍不得含 window、backfill、lookback）。
- 新增纯函数 `backfill_window_days(conn, trade_date: date, years: int) -> int | None`（`app/marketdata/daily_bars.py`）：
  - 起点 start 为 trade_date 往前 years 个公历年的同月同日（2 月 29 日回落到 2 月 28 日）。
  - 返回 trading_calendar 中 start < date ≤ trade_date 且 is_open 的天数，即按日历实际开市日计，不用每年 250 天之类的估算。
  - 日历覆盖检查：[start, trade_date] 内每个公历日都必须有日历行（行数等于天数），不满足时返回 None。
  - years 不是正整数时抛 ValueError。
- 日历覆盖不足：`backfill_window_days` 返回 None，触发方不入队，报 `calendar_not_covered`，**不缩短窗口**。§7 ② 原有的「窗口超出日历时零写入、记 `calendar_not_covered`」仍兜底。
- 量级：每年约 242 个开市日，3 年约 720–735 天，以日历为准。

**怎样触发（用户原文没有要求自动回填，所以不自动）**

- 新增命令 `python -m app.cli daily-bars-backfill --years 3 [--trade-date YYYY-MM-DD] [--apply]`（`app/cli/daily_bars_backfill.py`，注册进 `app/cli/__main__.COMMANDS`）：
  - trade-date 缺省为「数据已是完成版」的最近开市日：今天是开市日且北京时间已过 17:45 时取今天，否则取今天之前最近的开市日。显式给出今天而当前早于 17:45 时拒绝（退出码非零、不入队）。理由：upsert 不覆盖，17:10 之前取到的当日行会一直是非完成版，当日快照只能把它记为 `daily_bars_not_final`。
  - 默认只读演练：输出 window_trading_days、标的数 N、预计行数、预计 SQL 语句数、预计调用数，**不输出证券代码**，不入队、不写库。
  - 加 `--apply` 时只往 `jobs:worker` 推一条 daily_bars_fetch 任务，args 为 trade_date 和 window_trading_days，不带 user_id，然后返回。它不自己取数，所以锁、不重试、出网条件全部沿用任务本身的规则。
  - `--apply` 是运维动作：须在 §8.1 的开放条件都满足、并经用户本人批准后执行。交易日北京时间 17:00–17:45 之间不得运行，以免与 17:15 的钟点任务争 `LOCKED_TASKS` 锁，因为被锁跳过的那次钟点任务不会重排。
- 新进入范围的标的（新买入、新加自选）不自动补历史：从进入范围那天起每天取当日，历史缺日由 `prepare` 如实记 `daily_bar_missing:<date>`。要补就再手动跑一次本命令：已有行是 unchanged，幂等；代价是全体标的重新请求一遍。是否自动补，见 §8.6 U2。

**调用量粗估（不编造持仓数）**

- 记 N 为 §8.2 的标的数，W 为 `backfill_window_days` 的结果（约 730），k 为一次 history 调用最多能返回的交易日数（【待 T003】，未实测）。只取 adjust=none（Q2 不变）。
  - 首次回填调用数 = N × ceil(W / k)；若一次调用就能覆盖整个窗口，即为 N。
  - 回填行数约 N × W（停牌占位行也计在内）；SQL 语句数 = ceil(行数 / 1000)。
  - 每日增量调用数 = N，行数 = N。
  - 示意（不是假设）：N 为 10 时约 7,300 行、8 条语句；N 为 150 时约 110,000 行、110 条语句。
- 单 C 的 history 分段：k 小于 W 时按 k 切段，段与段之间不重试；任何一段触发停止规则就整批停（§3）。

**G/W/T**

- `test_upsert_batches_under_param_limit`：Given 5,000 根 fake bar（例如 10 只 × 500 天，直接构造 `DailyBarsResult`）/ When `upsert_daily_bars` / Then inserted 为 5000；用 SQLAlchemy 的 `before_cursor_execute` 计数，对 daily_bars 的 INSERT 恰为 5 条，每条绑定参数数不超过 65535。
- `test_upsert_batch_constant_bound`（不连库）：Then `UPSERT_BATCH_ROWS` 为 1000，乘以每行参数数后不超过 65535。
- `test_upsert_batched_stats_aggregate`：Given 已有 1,500 行（其中 1 行将以不同 close 再写），再写 2,500 行（含这 1,500 个键）/ Then inserted 为 1000、unchanged 为 1499、conflicts 为 1，issues 恰为那一条冲突。
- `test_upsert_batched_atomic_on_error`：Given 第 2 块执行时注入异常 / When 在 `engine.begin()` 内调用 / Then 回滚后 daily_bars 零新增（第 1 块也不留）。
- `test_backfill_window_days_three_years`：Given 合成日历覆盖 2023-11-10 至 2026-11-10 / When `backfill_window_days(conn, 2026-11-10, 3)` / Then 等于 2023-11-10（不含）到 2026-11-10（含）之间的 is_open 行数；另一组以 2024-02-29 为 trade_date 时，起点为 2021-02-28。
- `test_backfill_window_days_calendar_short`：Given 日历最早只到 2025-01-01 / Then 返回 None；日历中间缺一天时也返回 None。
- `test_backfill_cli_dry_run_default_no_enqueue`：Given 假 Redis / When 不带 `--apply` 运行 / Then 队列长度不变，输出不含任何证券代码，库零写入。
- `test_backfill_cli_apply_enqueues_once`：Given 假 Redis / When 带 `--apply` / Then 队列恰多一条，task 为 daily_bars_fetch，args 恰为 trade_date 与 window_trading_days；日历不足时不入队、退出码非零、输出含 calendar_not_covered。
- `test_backfill_cli_refuses_today_before_1745`：Given 今天为开市日、北京时间 16:00 / When 显式 `--trade-date` 为今天并带 `--apply` / Then 不入队、退出码非零；不给 trade-date 时取上一开市日。
- `test_no_settings_field_for_window`（不变）。

### 8.4 Q5 / QB1：交易日北京时间 17:15 自动取数；analyze 仍 17:30

- 推翻 §7 ③「不进 `slot_jobs`」。仍然**不进 `schedule()`**（间隔排程），仍然**不进 `RETRY_TASKS`**，仍在 `LOCKED_TASKS`。
- 接入（`app/workers/jobs.py`，照现有 18:00、17:30 分支的写法）：
  - 新常量 `DAILY_BARS_FETCH_TIME`，值为 17:15（与 `CODE_MAP_TIME` 同风格；不进 Settings，补1 不变）。
  - `slot_jobs` 新增一支：北京时间落在 [17:15, 17:15 + `SLOT_WINDOW_S`)，即 [17:15, 17:30) 时，用 `_engine(settings).connect()` 调 `reports/service.covered(conn, 北京日期)`；为 True 才排 (DAILY_BARS_FETCH, 17:15, {trade_date: 北京日期 ISO})。不带 user_id（全体 approved 用户），不带 window_trading_days（只取当日）。
  - 交易日判定就是 `covered`：休市不排；日历未覆盖时与现有 17:30 分支一样由 `covered` 抛错，本单不改这一既有行为。
  - `beat_slots` 对它不调用 `record_intent`、不调用 `read_grant`（beat 容器不挂回执卷；出网条件在 worker/ingest 里判，见 §8.1）。去重键沿用 `beat:slot:<task>:<YYYYMMDD>:1715`，同一窗口只推一次。
  - 源为 off 时照样排；任务自己记 skipped 和 `daily_bars_source_off`（§7 ⑧ 不变），「没开源」在运行记录里可见。
- 与 17:10–17:30 完成版窗口的关系：
  - 钟点窗口 [17:15, 17:30) 落在完成版窗口内。正常情况下取到的行 fetched_at 不早于 17:10，`is_final` 为真，且早于 17:30 截止。
  - fetched_at 口径（单 C 必须遵守）：真实源写入的 fetched_at **不得早于该行数据实际收到的时刻**；一次运行只用一个 fetched_at 时，取最后一个响应收到之后的时刻。fake 源可沿用 `fetch_and_record` 的开始时刻或注入值。
  - 取数拖过 17:30：这些行的 fetched_at 晚于 17:30，当日快照把对应标的放进 omitted 并记 `daily_bars_after_asof:<code>`，当日不求值；不改 as_of，不等待，不补跑。这些行仍是完成版，次日起作为历史 bar 进入快照（`daily-snapshot-from-bars.md` §10 J14）。
  - 若 17:30 时取数事务还没提交，analyze 看不到运行记录，记 `daily_bars_not_ready`。compose 里 worker 未设 replicas（默认 1），按 FIFO 执行；单副本时 analyze 会排在取数之后，此时走上一条。
- 重试与锁：失败不重试（不进 `RETRY_TASKS`，`_after_failure` 对它无动作）；运行中又到达同名任务时 worker 返回 locked 并丢弃，不重排。当日错过即为如实缺口，次日钟点照常。
- 快照仍由 analyze 惰性生成：`daily_bars_ready`、`build_owned_snapshot` 不注册任务、不进 `slot_jobs`/`schedule()`（`daily-snapshot-from-bars.md` §1 不变）。
- 「此前卡上的 18:30 作废」指此前卡里「每天 18:30 取数」那个选项。它**不改变** `slot_jobs` 里 `REPORT` 的 18:30 钟点，也不改变 `CODE_MAP_TIME`。日报实际几点生成，见 §8.6 U1。
- 17:15 时麦蕊当日数据是否已经完整，没有实测（【待 T003】）。首次实调时由运维记录，结果不符再报编排者。
- G/W/T：
  - `test_daily_bars_fetch_slot_1715_open_day_only`（取代 `test_daily_bars_fetch_never_scheduled`；后端 `selfchecks/test_tb127_daily_bars.py` 里的同名副本一并改）：Given `covered` 打桩为 True、`_engine` 打桩，北京时间 00:00–23:59 每 5 分钟一个 now / When `slot_jobs(settings, now)` / Then daily_bars_fetch 恰在 17:15、17:20、17:25 三个 now 出现，slot 为「当日 YYYYMMDD:1715」，args 恰为 {trade_date}；`covered` 为 False 时一次也不出现；`schedule(settings)` 的键不含它。
  - `test_task_registered_locked_not_retried`（不变）。
  - `test_beat_slots_fetch_once_no_intent_no_grant`（新）：Given 假 Redis，now 为开市日 17:16 / When 连续两次 `beat_slots` / Then 只推一次；`record_intent` 与 `read_grant` 的计数桩都为 0 次。
  - `test_fetch_locked_skip_not_retried`（新）：Given 锁已被占 / When `worker_tick` / Then 结果为 locked，`jobs:delayed` 为空。
  - `test_mairui_fetched_at_not_before_last_response`（单 C，新）：Given 假 transport 的最后一个响应在 t / Then 写入行的 fetched_at 不早于 t。
  - 快照侧用例见 `daily-snapshot-from-bars.md` §11。

### 8.5 改动清单与迁移

- 无新迁移（分批、范围、排程、常量都只改代码）。
- 建议拆单（都可离线完成，不出网）：
  - A 补丁单：`upsert_daily_bars` 分批；`daily_universe` 加自选；`slot_jobs` 17:15 接入；`backfill_window_days` 与 `daily-bars-backfill` 命令；`fetch_and_record` 改用源对象的 name 写 source，不再写死 fake（T-A132 非阻塞项⑴，单 C 前必须完成）。
  - 单 C：`DAILY_BARS_HTTP_LIMIT` 为 0 与 `DAILY_BARS_HTTP_UNLIMITED` 哨兵、`daily_bars_http_budget`、fetched_at 口径、结构上界。
  - 开放单 D（用户本人批准首次实调后才开）：常量改为哨兵；运维装回执、设 `DAILY_BARS_SOURCE`。

### 8.6 只有用户能定的（本单新增）

| # | 问题 | 答复前做法 |
|---|---|---|
| U1 | 用户原文是「analyze / 日报仍在 17:30 出」。但现网 `slot_jobs` 里 analyze 在 17:30，`REPORT`（daily_report 生成）在 18:30。日报保持 18:30 生成，还是要求提前？ | 不改 `REPORT` 的 18:30 |
| U2 | 新进入范围的标的（新买入、新加自选）要不要自动补近 3 年历史？ | 不自动；手动 `daily-bars-backfill` |
| U3 | 在「不设每日上限」之外，要不要再加一道数值型「每批防失控上限」（一次运行超过若干次调用就停）？架构建议加，作为兜底，数值由用户定 | 不加；只靠结构上界和 STOP/103/429 停止规则 |
