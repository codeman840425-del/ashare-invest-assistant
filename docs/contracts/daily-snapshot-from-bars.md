# 日 K 生成本人快照 + 解除 analyze 闸（实现单 B 实施契约，T-A133）

状态：draft，架构契约，不代表已实现。基点 docs/T-A128 `04178d0`（契约 `daily-bars-source.md` §5.B、§7），源码按 be/T-B127 `832faa2` 核对（其后 `fc798cc` 只改 selfchecks，不影响本文）。**本文件与 `daily-bars-source.md` §2、§5.B 不一致处以本文件为准。** 引用只写文件路径、函数名、用例名。原则：最小可用；不编造、不推断数据；Q2/Q3/Q4/Q5 保守默认不变。

## 0. 核对结论（决定本单形状的事实）

- 闸在 `workers/daily.analyze` 的实例循环里，位于 `runnable` 之后；放行后 `require_isolated` 只认 `tb70_` 库，并只取 schema_version 为 `replay/baseline.VERSION` 的快照。
- `features/evaluation.evaluate_snapshot` 经 `replay/baseline.read` 读快照；`read` 只接受 `VERSION`，其他 schema 一律 NOT_FOUND。所以只改闸不够，`read` 也必须接受新 schema。
- `evaluate_snapshot` 还要读 instrument 的 `board`（`strategy/cards/fixtures.calculate` → `market_rules/lots.lot_spec`）。`securities.board` 可空；为空时 `lot_spec` 会按主板处理，这是推断，本单不允许。
- `features/pipeline.prepare` 只收 `is_final` 为真且 `first_seen_at <= as_of` 的 bar。`analyze` 的 as_of 写死为交易日 17:30（北京）。`reports/dimensions.load_inputs` 另要求 `first_seen_at >= 当日 17:10`。单 A 的 `first_seen_at` 就是 `daily_bars.fetched_at`，等于取数时的墙钟时间。**结论：当日 bar 只有在 17:10–17:30（北京）之间取到才对 analyze 可见**，见 §9 QB1。
- `prepare` 遇到同一天既有 bar 又有 suspended gap 会抛 `suspension_or_listing_conflict`，所以停牌占位行只能进 gaps，不能进 bars。
- `reports/service.build` 把 analyze 的每个 issue 都转成 `pipeline.<issue>` 缺口，文案通用。新 issue 不必改 `reports/service`。
- `phase` 先调 `covered`：休市日直接返回 0，日历未覆盖时整次运行 failed 后抛出。analyze 和 report 在这两种日子都不会执行，本单不改。
- daily_bars 的其他读方都不会把停牌占位行当成价格：`tracking/service.instrument` 在 Python 里跳过 OHLC 为空或非正的行；`risk/rc1` 遇到非正 OHLC 返回缺口；`/portfolio` 按 close 非空过滤；`reports/service.build` 按 close > 0 过滤。T-A130/T-A132 提到的「tracking 不滤 close 空行」只是查询里没加过滤，结果不受影响（见 §7）。

## 1. 入口与调用关系

- 新模块 `app/marketdata/daily_snapshot.py`，只放纯函数，**不注册任务**：不进 `workers/jobs.TASKS`、`LOCKED_TASKS`、`RETRY_TASKS`，不进 `slot_jobs`、`schedule()`（Q5 保守）。
- `OWNED_VERSION`：常量，值为 owned-daily-v1。
- `ANALYZE_AS_OF`：常量，值为北京时间 17:30。`workers/daily.analyze` 改为引用它，不再写死时刻（数值不变）。
- `FINAL_AFTER`：常量，值为北京时间 17:10，与 `reports/dimensions.load_inputs` 的阈值相同。
- `daily_bars_ready(conn, owner: uuid.UUID, trade_date: dt.date) -> tuple[bool, tuple[str, ...]]`
  - 取 pipeline_runs 中 kind 为 daily_batch、step 为 daily_bars.fetch、run_date 为 trade_date，且 stats.user_id 为空（全体运行）或等于 owner 的行，按 started_at、finished_at 降序取第一行。
  - 状态为 ok 或 partial 时返回 True，同时返回该行 stats.issues 中**只属于 owner 当日 `daily_universe` 的** `daily_bars_missing:<code>` 与 `daily_bar_conflict:<code>:<date>`（排序去重，不带出他人标的）。
  - 没有行，或状态为 skipped、failed、running：返回 (False, ())。
- `build_owned_snapshot(conn, owner: uuid.UUID, trade_date: dt.date) -> tuple[uuid.UUID | None, tuple[str, ...]]`
  - 返回（快照 id 或 None，issue 元组）。issue 是 omitted 中的 issue（排序去重）；sessions 区间有日历空洞时返回 (None, (calendar_not_covered,))。
  - 不 begin、不 commit，事务由调用方负责（同单 A 的 `fetch_and_record`）。
  - 先调 `reports/service.covered`：休市返回 (None, ())、零写入；CALENDAR_NOT_COVERED 原样抛出（正常路径上 `phase` 已先拦住）。
  - 范围：`marketdata/daily_bars.daily_universe(conn, owner, trade_date)`（只取持仓，Q4）。范围为空时返回 (None, ())、零写入。
  - 构造 §2 的 items，按 §5 写入或复用，返回快照 id。
- 调用关系（`workers/daily.analyze` 内，替换「app_env 不是 test 就跳过」那一支，其余逻辑不动）：
  1. `daily_bars_source` 为 off：app_env 不是 test 时记 `owned_market_cache_adapter_missing` 并跳过，与现状一致；app_env 为 test 时走原 tb70 路径（`require_isolated` + `VERSION`），一字不改。
  2. 不是 off：每个 owner 在第一次走到这一支时调用一次 `daily_bars_ready`，未就绪记 `daily_bars_not_ready` 并跳过该实例。
  3. 就绪：同一次 analyze 内只调用一次 `build_owned_snapshot`，结果缓存给后续实例。id 为 None 时沿用现有 issue `owned_source_or_card_missing`。
  4. 有快照 id 时，按 id 读出这一行作为 source（不按 created_at 搜索），**不调用 `require_isolated`**，之后的 card、registry、source_gate、codes、`evaluate_snapshot`、`conclusion` 流程不变。
  5. 把 `daily_bars_ready` 带出的 issue 和 `build_owned_snapshot` 返回的 issue 并入本 owner 的 issues。
- `replay/baseline.read`：schema_version 接受 `VERSION` 与 `OWNED_VERSION` 两种，owner、licence_id 为空、purpose 为 report 这三条过滤**不放宽**。
- `reports/dimensions.load_inputs`：候选快照同时接受两种 schema。owned-daily-v1 另要求 items.trade_date 等于 day。按 created_at、id 降序取第一个含该标的的快照；hash 校验不变。
- `marketdata/daily_bars.fetch_and_record` 增加仅限关键字的参数 `fetched_at: dt.datetime | None = None`：None 时取当前 UTC 时间（现行为）；不带时区时在写库前抛 ValueError。`daily_bars_fetch_task` 的签名不变，不暴露这个参数。用途是让测试把 fetched_at 定在 17:10–17:30 之间。

## 2. 快照字段口径（只按下游实际读取的字段倒推）

data_snapshots 行：user_id 为 owner；licence_id 为空（mairui 行的证书绑定由单 C 定，见 §3）；purpose 为 report；created_at 取当前时间；hash 见 §5。

items 顶层（只放 JSON 原生值，数值一律字符串）：

| 字段 | 来源 | 谁读 | 缺失时 |
|---|---|---|---|
| schema_version | 常量 `OWNED_VERSION` | analyze、`baseline.read`、`load_inputs` | 不会缺 |
| trade_date | 入参 ISO 日期 | `load_inputs` 选快照 | 不会缺 |
| calendar_basis | 常量 trading_calendar | 说明用 | 不会缺 |
| sessions | trading_calendar 中 is_open 的日期，范围是 [所有入选行的最早 trade_date, trade_date]，升序 | `prepare`、`load_inputs` | 该区间内有日期不在日历中时不建快照，见 §3 |
| instruments | 见下表，按 security_code 升序 | analyze、`evaluate_snapshot`、`load_inputs` | 可以为空列表 |
| omitted | 被排除的标的：security_code 加 issue，按代码升序 | analyze 并入 issues | 空列表 |

不放持仓数量、成本、账户 id、用户名（持仓仍由 analyze 经 `_account` 传入 holding）。

instrument（每个 `daily_universe` 标的一个，除非被 omitted）：

| 字段 | 来源 | 缺失时 |
|---|---|---|
| security_code | universe 代码 | — |
| board | `securities.board` | 为空：不建该 instrument，omitted 记 `security_board_missing:<code>` |
| adjust / currency / price_unit / volume_unit / amount_unit | 常量 none / CNY / CNY/share / share / CNY（`daily-bars-source.md` §1 的单位约定，`prepare` 会校验） | — |
| bars | daily_bars 中 adj_type 为 none、source 非空、trade_date 在 sessions 内、is_suspended 为 false、OHLC 都非空、fetched_at 不晚于 trade_date 当天的 `ANALYZE_AS_OF` 的行，按 trade_date 升序 | 不补、不前值填充；缺的日子由 `prepare` 产出 `daily_bar_missing:<date>` |
| bars[].trade_date | trade_date | — |
| bars[].open/high/low/close/pre_close/volume/amount | 同名列，Decimal 转字符串；pre_close、volume、amount 为空时写 null | 原样 null |
| bars[].first_seen_at | fetched_at，带时区的 ISO 字符串 | — |
| bars[].is_final | fetched_at 不早于该 trade_date 当天的 `FINAL_AFTER` 时为 true，否则 false | — |
| gaps | 同样过滤后 is_suspended 为 true 的占位行，写 trade_date 和 reason suspended | 无停牌则为空列表；其他缺日**不写 gap**，不推断原因 |
| factors / scalars / lots / entry | **不写**（Q2 未定；也没有其他来源） | analyze 用 `get` 取默认值；`prepare` 产出 `adjust_factor_missing:<date>`，qfq 全为 null |

当日行规则：标的必须有一行 trade_date 当天的入选行（正常 bar 或停牌占位行），否则整只标的进 omitted。

- 当日无行，或只有 source 为空的旧式行：`daily_bars_missing:<code>`。
- 当日行 fetched_at 早于 `FINAL_AFTER`：`daily_bars_not_final:<code>`。
- 当日行 fetched_at 晚于 `ANALYZE_AS_OF`：`daily_bars_after_asof:<code>`。
- 当日为停牌占位行：保留该 instrument，当日进 gaps（`prepare` 会给出 f.is_suspended 为 true）。
- 被 omitted 的标的在 analyze 里照旧得到 `owned_source_security_missing:<code>`：不求值、不生成建议。

## 3. 异常行为（一行一种）

| 情形 | 写快照吗 | issue（analyze issues）/ 缺口 | 日报 |
|---|---|---|---|
| daily_bars_source 为 off，非 test | 不写，不调用 B | `owned_market_cache_adapter_missing`（原名） | 照出，gap 文案不变 |
| off，test | 不写；走原 tb70 路径 | 原有 issue 不变 | 照出 |
| 当日 daily_bars.fetch 没有运行，或最新一行是 skipped（off、mairui 在 C 之前、日历未覆盖）、failed、running | 不写 | `daily_bars_not_ready` | 照出，无建议 |
| 运行为 partial，部分标的缺当日行 | 写；缺的进 omitted | `daily_bars_missing:<code>`、`owned_source_security_missing:<code>` | 照出；缺的标的无建议 |
| 停牌（当日占位行，OHLC 全空） | 写；当日进 gaps（suspended），不进 bars | 不另记 issue；由求值结果给出 SUSPENDED | 照出 |
| 历史某日停牌 | 写；该日进 gaps，`prepare` 不把它计入有效 K | — | 照出 |
| 历史某日没有行 | 写；不写 gap | 求值 gaps 含 `daily_bar_missing:<date>`，analyze 记 `evaluated_input_gaps:<code>` | 照出；建议的 data_status 为 partial |
| 休市日 | 不写（`phase` 先返回 0；直接调用 `build_owned_snapshot` 返回 (None, ())） | 无 | 与现状一致（不生成） |
| trade_date 不在日历中 | 不写（`phase` 先记 failed） | 与现状一致 | 与现状一致 |
| sessions 区间内有日期不在日历中 | 不写，返回 (None, (calendar_not_covered,)) | `calendar_not_covered` 与 `owned_source_or_card_missing` | 照出，无建议 |
| 没有复权因子（Q2） | 写；不写 factors | 求值 gaps 含 `adjust_factor_missing:<date>`，qfq 特征为 null，**不用 1 补** | 照出；止损为 null 时记 `stops.*` 缺口 |
| board 为空 | 写；该标的进 omitted | `security_board_missing:<code>` | 照出；该标的无建议 |
| 当日行 fetched_at 不在 17:10–17:30 | 写；该标的进 omitted | `daily_bars_not_final:<code>` 或 `daily_bars_after_asof:<code>` | 照出；该标的无建议（QB1） |
| 入选行里有 source 为 mairui 的行 | 写；该标的进 omitted | `owned_snapshot_licence_unbound:<code>`；证书绑定留给单 C | 照出 |
| source 为空的旧式行 | 不入选，视同不存在 | 可能触发 `daily_bars_missing:<code>` | — |
| 日 K 同键冲突 | 写；用库里原有的行（单 A 不覆盖） | 从运行记录带出 `daily_bar_conflict:<code>:<date>` | 照出 |

`suspended` 只用 `prepare` 的 gaps 字符串空间，`schemas/enums.GapReason` 不增值（回答 §7 ⑦ 留给 B 的问题）。日报中的 `pipeline.*` 缺口 reason 仍为 no_source。

## 4. 解闸条件与「不误报」

- 三条同时满足才求值：源不是 off；`daily_bars_ready` 为 True；`build_owned_snapshot` 返回 id。
- 不满足时依次记 `owned_market_cache_adapter_missing`（off，非 test）、`daily_bars_not_ready`、`owned_source_or_card_missing`，都不求值、不写 suggestions。
- 不误报的保证：
  - 没有就绪运行就不建快照；
  - 当日无可见行的标的不求值；
  - 缺口只经 gaps 和 issues 传递；
  - 不补前值、不补因子、不按主板推断 board、不按停牌推断缺行。
- test 环境：源为 off（默认）时 analyze 行为与现状逐字一致，`test_tb76_*`、`test_p2n04_*`、tb70 自检不受影响；源为 fake 时只走 owned 路径。
- 非 test 环境不可能出现 fake（单 A 的 Settings 校验）。mairui 在单 C 之前运行状态总是 skipped，所以只会得到 `daily_bars_not_ready`。

## 5. 幂等与事务边界

- 事务：`phase` 为每个 owner 开一个 `conn.begin()`，并持有 owner 级 advisory 锁；`daily_bars_ready`、`build_owned_snapshot`、求值、归档都在这个事务里。出错时整体回滚，快照也不留下；`phase` 记 failed。
- hash：`replay/baseline.manifest_hash(items)`。items 只含 JSON 原生值，所以它等于 `reports/dimensions.digest(items)`，`load_inputs` 的 hash 校验能通过。
- id：uuid5(NAMESPACE_URL, 由 OWNED_VERSION、owner、trade_date、hash 拼成的串)。插入用主键 ON CONFLICT DO NOTHING。已有同 id 的行，但 owner 或 hash 不同时，抛 ValueError（owned_snapshot_hash_conflict），不 UPDATE。
- 同一用户同一日重跑：日 K 不变时 hash 相同、id 相同，data_snapshots 只有一行，analyze 结果相同；建议是否重复归档沿用 `archive_conclusions` 的现有幂等性。
- 日 K 有冲突行：单 A 不覆盖，快照读到的是原有行，hash 不变。
- 补取了原来缺的标的：只有 fetched_at 不晚于当日 17:30 的行才会入选，所以盘后补取不改变当日快照；在此之前补上的会得到新的 hash 和新 id，旧快照保留，analyze 用本次返回的 id，`load_inputs` 取最新一个。
- 部分标的缺失：只影响 omitted 和对应 issue，不影响其他标的的 instrument。

## 6. 麦蕊 0 调用

- `app/marketdata/daily_snapshot.py` 和改动后的 `workers/daily.py`、`replay/baseline.py`、`reports/dimensions.py` 不得直接导入（模块顶层和函数内都算）`app.ingest`，以及 socket、httpx、requests、urllib.request。
- B 不读证书，不建 outbox，不碰 `ingest/egress`。
- 探针沿用 `daily-bars-source.md` §7「T-T70 补充裁定」第 4 条：socket 探针加 `ingest/egress.mairui_get` 计数桩，不调用 `netguard.install()`。

## 7. 与单 A 遗留的接口

- 停牌占位行（OHLC 全空、is_suspended 为 true）对其他读方的影响：`tracking/service.instrument` 跳过（当作当天无 bar，而不是停牌）；`risk/rc1` 返回缺口；`/portfolio` 和 `reports/service.build` 被过滤。都不会产生错误价格，本单不改这些读方。tracking 把停牌当缺 bar 是语义欠缺，另开单。
- 单 A 的 `fetch_and_record` 把 source 写死为 fake（T-A132 非阻塞第 1 项），B 不依赖它，也不修，单 C 前修。批量写入的参数上限（第 2 项）与 B 无关。
- B 的唯一 A 侧改动是 §1 的 `fetched_at` 关键字参数。
- **本单不需要迁移**：data_snapshots 的 purpose 已含 report，schema_version 在 jsonb 里，daily_bars 列已由 0032 提供。如果实现时确实发现需要迁移，编号用 0033，down_revision 为 0032，并先报架构师。

## 8. 验收清单（测试左移，用例名级别）

- 文件：`tests/backend/unit/test_daily_snapshot_impl_b.py`，由测试组维护；后端不新增 selfchecks。
- 临时库：同 `daily-bars-source.md` §7「测试落点、临时库与种子」：`pg_o61.guard_temp_pg` 先核端口归属，`CREATE DATABASE tt…_ TEMPLATE o61_tmp_0030`，只对临时库 alembic upgrade head（0032），finally 删库，建库失败则 skip。不起实例，不做端口转发。
- 种子（全部虚构，只进临时库）：
  - 沿用 §7 的日历 5 行、u1/u2 和持仓链；A、B、C 为 stock、listed，board 取 `Board` 中的值；另加 H（stock、listed、board 为空）挂在 u1 下；
  - u1 一个 active 的 account 范围实例，策略/卡/feature_catalog/engine policy 链路形状同 `selfchecks/test_tb76_daily` 的种子；
  - 日 K 用 `fetch_and_record(..., fetched_at=当日北京 17:15)` 配合 `FakeDailyBarsSource(missing=…, suspended=…)` 写入；
  - 代码只用仓库合成夹具里已有的代码，不取自任何含股东代码的材料。
- 凡是连库用例都挂上 §6 的两个探针，并在结束时断言 socket 记录为空、mairui_get 计数为 0。

用例（Given / When / Then）：

1. `test_ready_requires_ok_or_partial_run`：Given 当日分别没有运行、只有 skipped、只有 failed、只有 ok 的 daily_bars.fetch 行 / When `daily_bars_ready(u1)` / Then 只有 ok 那组为 True。
2. `test_ready_uses_latest_run_in_owner_scope`：Given 先有 ok 的全体运行，后有 skipped 的全体运行；另一组只有 stats.user_id 为 u2 的 ok 运行 / Then 前者 False（取最新一行），后者对 u1 为 False。
3. `test_ready_carries_only_owner_issues`：Given partial 运行的 issues 含 `daily_bars_missing:A`（u1 持有）和 `daily_bars_missing:C`（只有 u2 持有）/ Then u1 拿到的 issue 只有 A 那条。
4. `test_snapshot_shape_fields_from_daily_bars`：Given 11-06、11-09、11-10 三天 fake 行 / When `build_owned_snapshot(u1, 11-10)` / Then 顶层键恰为 §2 的 6 个；A、B 各 3 根 bar，字段恰为 §2 所列，first_seen_at 等于 fetched_at，is_final 为 true，sessions 为这三天；没有 factors、scalars、lots、entry 键。
5. `test_snapshot_hash_matches_dimensions_digest`：Then 行的 hash 等于 `reports/dimensions.digest(items)`，也等于 `replay/baseline.manifest_hash(items)`。
6. `test_suspended_placeholder_becomes_gap_not_bar`（自 A 移来）：Given suspended 含 B / Then B 当日在 gaps（suspended），不在 bars；`prepare` 不抛错，f.is_suspended 为 true。
7. `test_snapshot_omits_code_without_today_bar`：Given missing 含 B / Then 没有 B 的 instrument，omitted 含 `daily_bars_missing:B`。
8. `test_snapshot_excludes_unsourced_legacy_rows`：Given A 当日只有一行 source 为空的直接插入行 / Then A 进 omitted（`daily_bars_missing:A`）。
9. `test_snapshot_board_missing_omitted`：Then H 进 omitted（`security_board_missing:H`），A、B 不受影响。
10. `test_snapshot_today_bar_outside_final_window_omitted`：Given A 当日行 fetched_at 为 16:00，B 为 20:00（北京）/ Then 分别记 `daily_bars_not_final:A`、`daily_bars_after_asof:B`。
11. `test_snapshot_mairui_rows_unbound_in_b`：Given A 当日行 source 为 mairui / Then A 进 omitted（`owned_snapshot_licence_unbound:A`），快照 licence_id 为空。
12. `test_snapshot_closed_day_returns_none`：Given 11-08 / Then 返回 (None, ())，data_snapshots 零新增。
13. `test_snapshot_calendar_hole_not_built`：Given 删掉日历里 11-09 这一行 / Then 返回 (None, (calendar_not_covered,))，零写入；analyze 的 issues 含 `calendar_not_covered`。
14. `test_snapshot_only_owner_universe`：Then u1 的快照不含 C（u2 的持仓），也不含 u1 的自选代码（Q4）。
15. `test_owned_snapshot_idempotent_rerun`：Given 日 K 不变 / When build 两次、analyze 两次 / Then id 相同，data_snapshots 中该 schema 只有一行，suggestions 不重复归档。
16. `test_snapshot_conflict_keeps_first_row`：Given 同键不同 close 的第二次 upsert / Then 快照 hash 不变，analyze issues 含 `daily_bar_conflict:<code>:<date>`。
17. `test_analyze_off_keeps_legacy_issue_and_report`：Given app_env 为 local、源为 off / When 依次跑 daily_analysis、daily_report / Then evaluations 为空，issues 含 `owned_market_cache_adapter_missing`，日报照出且 gaps 含该项，data_snapshots 零新增。
18. `test_analyze_test_env_off_keeps_tb70_path`：Given app_env 为 test、源为 off / When 打桩 `require_isolated` 和 `build_owned_snapshot` 为计数桩后跑 analyze / Then 前者每个可运行实例调用 1 次，后者 0 次，issues 与改动前相同。
19. `test_analyze_not_ready_no_bars_today`：Given 源为 fake、当日没有 fetch 运行 / Then 不求值，issues 含 `daily_bars_not_ready`，suggestions 零写入，data_snapshots 零新增，日报照出。
20. `test_analyze_fake_bars_produces_evaluations`：Given 源为 fake、A、B 完整、库名不以 tb70_ 开头 / Then A、B 都有 evaluation，simulation 为 true，source_hash 等于 owned 快照的 hash，没有调用 `require_isolated`。
21. `test_missing_factor_stays_gap_not_one`：Then 上例的 evaluation gaps 含 `adjust_factor_missing:<date>`，f.close_qfq 为 null，不用 1 补。（§5.B 的「有显式合成因子」作废，B 不写因子。）
22. `test_analyze_partial_bars_gaps_no_fabricated_suggestion`：Given missing 含 B / Then A 正常求值；B 记 `daily_bars_missing:B` 和 `owned_source_security_missing:B`，没有 B 的 evaluation、建议、置信度或止损。
23. `test_load_inputs_accepts_owned_schema_same_day`：Given 有 11-10 的 owned 快照 / When `load_inputs(u1, A, 11-10)` / Then sources 的 kind 为 owned-daily-v1；以 11-09 调用时不选它。
24. `test_baseline_read_accepts_owned_keeps_filters`：Then `baseline.read` 能读 owned 快照；以他人 owner 读时 NOT_FOUND；licence_id 非空的同 schema 行也是 NOT_FOUND。
25. `test_fetch_and_record_fetched_at_injection`：Given 传入带时区的 fetched_at / Then 写入行的 fetched_at 等于它；传入不带时区的值时 ValueError、零写入；`daily_bars_fetch_task` 的签名不变。
26. `test_daily_snapshot_not_a_task`（不连库）：Then `TASKS`、`LOCKED_TASKS` 的值和 `slot_jobs`、`schedule()` 里都没有 daily_snapshot 的函数。
27. `test_impl_b_has_no_network_imports`（不连库，静态）：Then §6 列出的 4 个文件里没有对 app.ingest、socket、httpx、requests、urllib.request 的直接导入，函数内的也算。
28. `test_placeholder_rows_ignored_by_price_readers`：Given B 当日为停牌占位行 / Then `tracking/service.instrument` 的 bars 不含该日，`/portfolio` 的现价不取该日，`reports/service.build` 的估值不取该日。

回归：`selfchecks/test_tb76_assembly`、`test_tb76_daily`、`test_p2n04_daily_dimensions`、tb70 系列，以及 T-T70 的 A 套件全部保持绿。

## 9. 只有用户能定的问题

| # | 问题 | 澄清前保守默认 |
|---|---|---|
| QB1 | analyze 用固定的 17:30（北京）作为时点，而日 K 要 17:10 之后取到才算完成版；当日 bar 只有在 17:10–17:30 之间取到才会被用到。是要定在这个窗口里取数（并入 Q5），还是把 analyze 的时点后移、改成随取数时间走？ | 不改时点。窗口外取到的当日行，对应标的进 omitted，不求值 |
| Q2 | 复权因子（原问题） | 不写因子，qfq 全为缺口 |
| Q4 | 自选或实例标的是否进快照（原问题） | 只取持仓；自选代码记 `owned_source_security_missing` |
| Q5 | 取数钟点（原问题，与 QB1 相关） | 不排程 |

单 B 合入以后，在 QB1 和 Q2 澄清之前，正式环境就算开了源，也拿不到有效的 qfq 特征。这是如实的缺口，不是故障。
