# 正式日 K 数据契约（T-A128，主线补缺第 1 项）

状态：draft，架构契约，不代表已实现。基线 main `965598b`。适用范围是 Phase 2 最小闭环，也就是盘后求值和日报所需的日 K，不含分钟线、快照、财报和公告。引用只写文件名和函数名/配置项名/用例名。

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
  - 自选：是否纳入见 Q4。澄清前只取持仓，不读 `watchlist_items`。（目前也没有自选写入 API。）
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
- 新的放行条件，替换 `analyze` 中 `settings.app_env != "test"` 那一支，**三条同时满足才求值**：
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
- 持仓数量级：脱敏文档里没有找到。下面按 N≈10–50 只做量级示意，**不是假设**，见 Q1。自选目前为 0，基准 +1。
- 首次回填：窗口长度见 Q3。两张卡有 `lookback_trading_days: 120`，预热 62–64 根，这只是参考值。一次 history 调用能否覆盖整个窗口要等 T003 确认。
  - 只要 none：N+1 次，约 11–51 次；
  - 若按 Q2 另取 hfq：约 22–102 次。
- 日常增量：每个交易日 latest 调用 N+1 次，约 11–51 次；若取 hfq 则约 22–102 次。持仓变化时只为新标的补回填。
- 限流（不放宽）：
  - `master/daily_delivery.DAILY_HTTP_LIMIT=1` 和 `live_budget_issue()` 原样保留，它们管的是 18:00 名单，与本单无关、不借用。
  - 新增独立常量 `DAILY_BARS_HTTP_LIMIT = 0`，以 0 作为默认关闭的保险。超出时记 `daily_bars_http_budget_unset` 或 `daily_bars_quota_deferred`，不发请求。改数值必须有用户原话加评审提交，不能通过回执、环境变量或客户端参数放宽。
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
  - `DAILY_BARS_HTTP_LIMIT > 0`。
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
- 目标：§1 的协议、`daily_universe`（澄清前只含持仓，Q4）、`upsert_daily_bars`、`FakeDailyBarsSource`、迁移、`daily_bars_source` 配置。另在 `workers/jobs` 注册 `daily_bars_fetch`：`slot_jobs` 设钟点（时刻见 Q5，澄清前不排程，只能手动入队），加入 `LOCKED_TASKS`。
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
  - `test_universe_holdings_only_until_clarified`：Given 持仓 2 只、自选 1 只、scope=security 实例 1 个 / When 计算 daily_universe / Then 只返回持仓 2 只（Q4 澄清前）。

### B｜owned 快照 + 解除 analyze 闸｜中｜依赖 A 的接口，可与 C 并发
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

**留给用户**：安装回执、给出 DAILY_BARS_HTTP_LIMIT 的数值、首次实调。这些都需要用户本人批准麦蕊实调或出网。

## 6. 待澄清（澄清前实现单一律按最保守做法）

| # | 问题 | 为何拿不准 | 可选答案 | 澄清前做法 |
|---|---|---|---|---|
| Q1 | 持仓数量级 N 与每日调用上限 | 脱敏文档里没有；原始文件含敏感信息，不读 | 用户给 N 和上限；或按实际持仓数自动计算并设上限 | `DAILY_BARS_HTTP_LIMIT=0`，不出网；估算只作示意 |
| Q2 | 复权因子来源/口径 | `prepare` 必须有显式 A(d)；hfq/none 比值有舍入误差；除权接口未实测 | 另取 hfq 推因子（调用翻倍）；用专门的除权接口；只用不复权、qfq 特征暂缺 | 只存 adjust=none，不推因子；求值保持 `adjust_factor_missing` |
| Q3 | 首次回填窗口长度 | 卡的 lookback 是 120，预热 62–64；一次调用能否覆盖整个窗口未实测 | 120 个交易日；按卡的最大预热取；更长 | 实现单 A 把窗口做成参数，不设默认值；没有值就不回填 |
| Q4 | 自选与 scope=security 实例是否纳入取数范围 | 契约 eod_scope 写的是“自选与持仓”，但自选没有写入口；实例标的会增加调用量 | 只持仓；持仓+自选；再加实例标的 | 只取持仓 |
| Q5 | 取数钟点与就绪截止 | plan 写 15:30–16:30；麦蕊日 K 发布时间未实测 | 16:30；17:00；失败后重试一次 | 不进 slot 排程，只能手动或测试入队 |
| Q6 | 基准 000300.SH 的接口与主数据 | plan 标注【待 T003】，指数可能不在主数据中 | 用指数接口；不取，F50 记缺口 | 不取，F50 和基准相关的跟踪保持缺口 |
| Q7 | `source_licence_id` 是否进主键 | plan 的 per_licence 规则要求进；当前读方都不过滤 | 现在就升主键并让读方过滤；单用户期只加列 | 只加可空列，记录来源，不用于共享 |
| Q8 | 同键不同值（上游修正）怎么处理 | 覆盖会破坏 PIT；不覆盖可能保留错误值 | 不覆盖并告警；新建版本；人工确认后覆盖 | 不覆盖，记 `daily_bar_conflict` |
