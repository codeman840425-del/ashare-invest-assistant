# 日 K 生成本人快照 + 解除 analyze 闸（实现单 B 实施契约，T-A133）

状态：draft，架构契约，不代表已实现。基点 docs/T-A128 `04178d0`（契约 `daily-bars-source.md` §5.B、§7），源码按 be/T-B127 `832faa2` 核对（其后 `fc798cc` 只改 selfchecks，不影响本文）。**本文件与 `daily-bars-source.md` §2、§5.B 不一致处以本文件为准。** 引用只写文件路径、函数名、用例名。原则：最小可用；不编造、不推断数据；Q2/Q3/Q4/Q5 保守默认不变。**无行情标的的去留与两条测试前置条件见 §12（T-A137）。**用户本人已裁定 Q1、Q3、Q4、Q5 与 QB1，落地见 §11（T-A135）；本文其余各节与 §11 冲突处以 §11 为准。Q2 仍保守。**

## 0. 核对结论（决定本单形状的事实）

- 闸在 `workers/daily.analyze` 的实例循环里，位于 `runnable` 之后；放行后 `require_isolated` 只认 `tb70_` 库，并只取 schema_version 为 `replay/baseline.VERSION` 的快照。
- `features/evaluation.evaluate_snapshot` 经 `replay/baseline.read` 读快照；`read` 只接受 `VERSION`，其他 schema 一律 NOT_FOUND。所以只改闸不够，`read` 也必须接受新 schema。
- `evaluate_snapshot` 还要读 instrument 的 `board`（`strategy/cards/fixtures.calculate` → `market_rules/lots.lot_spec`）。`securities.board` 可空；为空时 `lot_spec` 会按主板处理，这是推断，本单不允许。
- `features/pipeline.prepare` 只收 `is_final` 为真且 `first_seen_at <= as_of` 的 bar。`analyze` 的 as_of 写死为交易日 17:30（北京）。`reports/dimensions.load_inputs` 另要求 `first_seen_at >= 当日 17:10`。单 A 的 `first_seen_at` 就是 `daily_bars.fetched_at`，等于取数时的墙钟时间。**结论：当日 bar 只有在 17:10–17:30（北京）之间取到才对 analyze 可见**，见 §9 QB1（**已由 T-A135 裁定**：交易日 17:15 取数，时点不改，见 §11.3）。
- `prepare` 遇到同一天既有 bar 又有 suspended gap 会抛 `suspension_or_listing_conflict`，所以停牌占位行只能进 gaps，不能进 bars。
- `reports/service.build` 把 analyze 的每个 issue 都转成 `pipeline.<issue>` 缺口，文案通用。新 issue 不必改 `reports/service`。
- `phase` 先调 `covered`：休市日直接返回 0，日历未覆盖时整次运行 failed 后抛出。analyze 和 report 在这两种日子都不会执行，本单不改。
- daily_bars 的其他读方都不会把停牌占位行当成价格：`tracking/service.instrument` 在 Python 里跳过 OHLC 为空或非正的行；`risk/rc1` 遇到非正 OHLC 返回缺口；`/portfolio` 按 close 非空过滤；`reports/service.build` 按 close > 0 过滤。T-A130/T-A132 提到的「tracking 不滤 close 空行」只是查询里没加过滤，结果不受影响（见 §7）。

## 1. 入口与调用关系

- 新模块 `app/marketdata/daily_snapshot.py`，只放纯函数，**不注册任务**：不进 `workers/jobs.TASKS`、`LOCKED_TASKS`、`RETRY_TASKS`，不进 `slot_jobs`、`schedule()`（Q5 保守；T-A135 裁定 Q5 后仍成立，进 `slot_jobs` 的只是单 A 的取数任务）。
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
  - 范围：`marketdata/daily_bars.daily_universe(conn, owner, trade_date)`（~~只取持仓，Q4~~ **已由 T-A135 取代**：持仓 + 本人有效自选，见 §11.1）。范围为空时返回 (None, ())、零写入。
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
- id：uuid5(NAMESPACE_URL, 由 OWNED_VERSION、owner、trade_date、hash 拼成的串，拼法见 T-A134 J12)。插入用主键 ON CONFLICT DO NOTHING。已有同 id 的行，但 owner 或 hash 不同时，抛 ValueError（owned_snapshot_hash_conflict），不 UPDATE。
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

> 本节 G/W/T 的精确观测面与修正见 §10「T-T71 裁定（T-A134）」，冲突时以 §10 为准。

- 文件：`tests/backend/unit/test_daily_snapshot_impl_b.py`，由测试组维护；后端不新增 selfchecks。
- 临时库：同 `daily-bars-source.md` §7「测试落点、临时库与种子」：`pg_o61.guard_temp_pg` 先核端口归属，`CREATE DATABASE tt…_ TEMPLATE o61_tmp_0030`，只对临时库 alembic upgrade head（0032），finally 删库，建库失败则 skip。不起实例，不做端口转发。
- 种子（全部虚构，只进临时库）：
  - 沿用 §7 的日历 5 行、u1/u2 和持仓链；A、B、C 为 stock、listed，board 取 `Board` 中的值；另加 H（stock、listed、board 为空）挂在 u1 下；
  - u1 一个 active 的 account 范围实例，策略/卡/feature_catalog/engine policy 链路形状同 `selfchecks/test_tb76_daily` 的种子；
  - 日 K 用 `fetch_and_record(..., fetched_at=当日北京 17:15)` 配合 `FakeDailyBarsSource(missing=…, suspended=…)` 写入；
  - 代码只用仓库合成夹具里已有的代码，不取自任何含股东代码的材料。
- 凡是连库用例都挂上 §6 的两个探针，并在结束时断言 socket 记录为空、mairui_get 计数为 0。

用例（Given / When / Then）：

1. `test_ready_requires_ok_or_partial_run`：Given 当日分别没有运行、只有 skipped、只有 failed、只有 ok 的 daily_bars.fetch 行 / When `daily_bars_ready(u1)` / Then 只有 ok 那组为 True。（见 T-A134 J13：ok 与 partial 为 True）
2. `test_ready_uses_latest_run_in_owner_scope`：Given 先有 ok 的全体运行，后有 skipped 的全体运行；另一组只有 stats.user_id 为 u2 的 ok 运行 / Then 前者 False（取最新一行），后者对 u1 为 False。
3. `test_ready_carries_only_owner_issues`：Given partial 运行的 issues 含 `daily_bars_missing:A`（u1 持有）和 `daily_bars_missing:C`（只有 u2 持有）/ Then u1 拿到的 issue 只有 A 那条。
4. `test_snapshot_shape_fields_from_daily_bars`：Given 11-06、11-09、11-10 三天 fake 行 / When `build_owned_snapshot(u1, 11-10)` / Then 顶层键恰为 §2 的 6 个；A、B 各 3 根 bar，字段恰为 §2 所列，first_seen_at 等于 fetched_at，is_final 为 true，sessions 为这三天；没有 factors、scalars、lots、entry 键。
5. `test_snapshot_hash_matches_dimensions_digest`：Then 行的 hash 等于 `reports/dimensions.digest(items)`，也等于 `replay/baseline.manifest_hash(items)`。
6. `test_suspended_placeholder_becomes_gap_not_bar`（自 A 移来）：Given suspended 含 B / Then B 当日在 gaps（suspended），不在 bars；`prepare` 不抛错，f.is_suspended 为 true。（见 T-A134 J3）
7. `test_snapshot_omits_code_without_today_bar`：Given missing 含 B / Then 没有 B 的 instrument，omitted 含 `daily_bars_missing:B`。
8. `test_snapshot_excludes_unsourced_legacy_rows`：Given A 当日只有一行 source 为空的直接插入行 / Then A 进 omitted（`daily_bars_missing:A`）。
9. `test_snapshot_board_missing_omitted`：Then H 进 omitted（`security_board_missing:H`），A、B 不受影响。
10. `test_snapshot_today_bar_outside_final_window_omitted`：Given A 当日行 fetched_at 为 16:00，B 为 20:00（北京）/ Then 分别记 `daily_bars_not_final:A`、`daily_bars_after_asof:B`。
11. `test_snapshot_mairui_rows_unbound_in_b`：Given A 当日行 source 为 mairui / Then A 进 omitted（`owned_snapshot_licence_unbound:A`），快照 licence_id 为空。
12. `test_snapshot_closed_day_returns_none`：Given 11-08 / Then 返回 (None, ())，data_snapshots 零新增。
13. `test_snapshot_calendar_hole_not_built`：Given 删掉日历里 11-09 这一行 / Then 返回 (None, (calendar_not_covered,))，零写入；analyze 的 issues 含 `calendar_not_covered`。
14. `test_snapshot_only_owner_universe`（**Then 已由 T-A135 取代**，见 §11.1）：~~Then u1 的快照不含 C（u2 的持仓），也不含 u1 的自选代码（Q4）。~~
15. `test_owned_snapshot_idempotent_rerun`：Given 日 K 不变 / When build 两次、analyze 两次 / Then id 相同，data_snapshots 中该 schema 只有一行，suggestions 不重复归档。
16. `test_snapshot_conflict_keeps_first_row`：Given 同键不同 close 的第二次 upsert / Then 快照 hash 不变，analyze issues 含 `daily_bar_conflict:<code>:<date>`。（见 T-A134 J5：第二次须经 `fetch_and_record`）
17. `test_analyze_off_keeps_legacy_issue_and_report`：Given app_env 为 local、源为 off / When 依次跑 daily_analysis、daily_report / Then evaluations 为空，issues 含 `owned_market_cache_adapter_missing`，日报照出且 gaps 含该项，data_snapshots 零新增。（见 T-A134 J6：零新增指 analyze 阶段）
18. `test_analyze_test_env_off_keeps_tb70_path`：Given app_env 为 test、源为 off / When 打桩 `require_isolated` 和 `build_owned_snapshot` 为计数桩后跑 analyze / Then 前者每个可运行实例调用 1 次，后者 0 次，issues 与改动前相同。（见 T-A134 绿例复核）
19. `test_analyze_not_ready_no_bars_today`：Given 源为 fake、当日没有 fetch 运行 / Then 不求值，issues 含 `daily_bars_not_ready`，suggestions 零写入，data_snapshots 零新增，日报照出。
20. `test_analyze_fake_bars_produces_evaluations`：Given 源为 fake、A、B 完整、库名不以 tb70_ 开头 / Then A、B 都有 evaluation，simulation 为 true，source_hash 等于 owned 快照的 hash，没有调用 `require_isolated`。（见 T-A134 J7）
21. `test_missing_factor_stays_gap_not_one`：Then 上例的 evaluation gaps 含 `adjust_factor_missing:<date>`，f.close_qfq 为 null，不用 1 补（见 T-A134 J7）。（§5.B 的「有显式合成因子」作废，B 不写因子。）
22. `test_analyze_partial_bars_gaps_no_fabricated_suggestion`：Given missing 含 B / Then A 正常求值；B 记 `daily_bars_missing:B` 和 `owned_source_security_missing:B`，没有 B 的 evaluation、建议、置信度或止损。
23. `test_load_inputs_accepts_owned_schema_same_day`：Given 有 11-10 的 owned 快照 / When `load_inputs(u1, A, 11-10)` / Then sources 的 kind 为 owned-daily-v1；以 11-09 调用时不选它。（见 T-A134 J8）
24. `test_baseline_read_accepts_owned_keeps_filters`：Then `baseline.read` 能读 owned 快照；以他人 owner 读时 NOT_FOUND；licence_id 非空的同 schema 行也是 NOT_FOUND。（见 T-A134 J9）
25. `test_fetch_and_record_fetched_at_injection`：Given 传入带时区的 fetched_at / Then 写入行的 fetched_at 等于它；传入不带时区的值时 ValueError、零写入；`daily_bars_fetch_task` 的签名不变。
26. `test_daily_snapshot_not_a_task`（不连库）：Then `TASKS`、`LOCKED_TASKS` 的值和 `slot_jobs`、`schedule()` 里都没有 daily_snapshot 的函数。（见 T-A134 J10）
27. `test_impl_b_has_no_network_imports`（不连库，静态）：Then §6 列出的 4 个文件里没有对 app.ingest、socket、httpx、requests、urllib.request 的直接导入，函数内的也算。
28. `test_placeholder_rows_ignored_by_price_readers`：Given B 当日为停牌占位行 / Then `tracking/service.instrument` 的 bars 不含该日，`/portfolio` 的现价不取该日，`reports/service.build` 的估值不取该日。（见 T-A134 J11）

回归：`selfchecks/test_tb76_assembly`、`test_tb76_daily`、`test_p2n04_daily_dimensions`、tb70 系列，以及 T-T70 的 A 套件全部保持绿。必须真跑，跑法见 §10「回归跑法」。

## 9. 只有用户能定的问题

| # | 问题 | 澄清前保守默认 |
|---|---|---|
| QB1（**已裁定，T-A135**：交易日北京时间 17:15 取数，analyze 时点不改，见 §11.3） | analyze 用固定的 17:30（北京）作为时点，而日 K 要 17:10 之后取到才算完成版；当日 bar 只有在 17:10–17:30 之间取到才会被用到。是要定在这个窗口里取数（并入 Q5），还是把 analyze 的时点后移、改成随取数时间走？ | 不改时点。窗口外取到的当日行，对应标的进 omitted，不求值 |
| Q2 | 复权因子（原问题） | 不写因子，qfq 全为缺口 |
| Q4（**已裁定，T-A135**：自选进快照，实例标的不进，见 §11.1） | 自选或实例标的是否进快照（原问题） | 只取持仓；自选代码记 `owned_source_security_missing` |
| Q5（**已裁定，T-A135**：17:15 进 `slot_jobs`，见 `daily-bars-source.md` §8.4） | 取数钟点（原问题，与 QB1 相关） | 不排程 |

单 B 合入以后，在 ~~QB1 和~~ Q2 澄清之前，正式环境就算开了源，也拿不到有效的 qfq 特征。这是如实的缺口，不是故障。（QB1 已由 T-A135 裁定。）

## 10. T-T71 裁定（T-A134）

依据：测试 T-T71 `04b51c5`（基 50835e3，28 例：24 红 4 绿，歧义 J1、J3、J5–J13）；后端 T-B128 `cb96fba`（T-T71 23 过 5 败）。源码按 50835e3 / cb96fba 核对。原则：不放松断言变绿；不能观测的「弱断言」一律改成可观测的精确断言。

### 10.1 逐条裁定

- **J1 缺实现的红形态：接受测试现做法。** 收集阶段不导入新符号，在用例内用 `importlib.util.find_spec` / `hasattr` / `inspect.signature` 探测，缺失时以「缺实现：」前缀的断言报红。理由：模块级 ImportError 会使整文件收集失败，连带把 4 条现状守护例（17、18、26、28）一起淹没；`xfail_strict` 或 importorskip 会把缺实现变成 xfail/skip，属静默。附加要求：
  - 不得用 skip、xfail、importorskip 承载缺实现；实现落地后探测保留为硬断言。
  - `b_db` 建库失败则 skip 的口径只适用于没有 PG 的环境。评审与门禁运行必须是 28 collected、0 skipped（同 10.3 的强制真跑开关）。
- **J3 `f.is_suspended` 路径：** `features/pipeline.prepare` 返回值的 features 字典中键 f.is_suspended。Then 改为：该值为 True（是布尔 True，不是「字符串里出现」）；同时当日 `raw_close` 为 None。测试须删除按 `repr` 查子串的写法，它对任何输出都成立（`prepare` 总会写这个键，值可能是 None）。
- **J5 冲突 issue 的承载：** 第二次取数必须经 `marketdata/daily_bars.fetch_and_record`，由它自己写 partial 运行记录。不得直接调 `upsert_daily_bars` 后手写 pipeline_runs。
  - Given：三天 fake 取数（17:15）后 build 得 hash1。
  - When：用测试内虚构源（包装 `FakeDailyBarsSource`，只把 A 在 11-10 的 close 改成与原值不同、但仍在该行 [low, high] 内的值）以 `fetched_at` 为 11-10 17:20 再取 11-10。
  - Then：
    - 最新一条 daily_bars.fetch 运行的 status 为 partial，stats.issues 含 `daily_bar_conflict:A:2026-11-10`；
    - 库内 A 行的 close 不变；
    - 再次 build 得到同一 id、同一 hash；
    - analyze 的 issues 含该冲突项。
  - 注意：同一事务内 started_at 取事务开始时刻，会相同。最新一行由 finished_at 降序决定，实现须保留 §1 的「started_at、finished_at 降序」。
  - 后端 cb96fba 的 `daily_bars_ready` 带出逻辑已符合，不改。
- **J6 「data_snapshots 零新增」：** 指 analyze 阶段。`reports/dimensions.build` 在日报阶段会写 p2n04 维度快照，这是既有行为，允许。用例 17 的 Then 改为：
  - phase ANALYZE 之后 data_snapshots 总数等于之前（严格相等）；
  - phase REPORT 之后 owned-daily-v1 行数为 0。
  - 测试须删除恒真的「大于等于 before」断言。
- **J7 evaluation 键路径：** 以 `workers/daily.analyze` 的 evaluations 元素为准，字段为 instance_id、security_code、simulation、source_hash、state、action、rule_refs、evidence、gaps。
  - 用例 20：每个元素的 source_hash 键等于 owned 快照行的 hash，按键取值，不用 `get` 兜底。
  - 用例 21：对 items.sessions 中每个日期 d，该元素的 gaps 列表含 `adjust_factor_missing:<d>`。f.close_qfq 为 null 的观测分两层：
    - 对快照中 A 的 instrument 调 `prepare`（factors 取 instrument 的 factors，缺省为空列表），断言 features 中 f.close_qfq 为 None，series 中 f.close_qfq 全为 None；
    - evaluation 的 evidence 中 key 为 f.close_qfq 的条目，value 不含非 null 数值。
  - 测试须删除「repr 里不含 '1'」这类恒真断言。
- **J8 load_inputs 的 sources 形状：** 列表元素为 kind、id、hash 三键，kind 等于所选快照的 schema_version（cb96fba 已如此）。Then：
  - 以 11-10 调用时，恰有一个元素，kind 为 `OWNED_VERSION`，id 等于快照 id 的字符串形式，hash 等于行 hash；
  - 以 11-09 调用时，sources 为空列表（临时库里没有 tb70 快照）。
  - 不再用 repr 子串。
- **J9 licence_id 非空行的构造：** 测试在临时库里直接插入一条虚构的已删除证书行：
  - 字段：owner 为 u1，provider 为 mairui，seal_key_version 为 1，tier 为 free，status 取 `ROW_STATUSES` 中任一值，deleted_at 有值，ciphertext 与 licence_hmac 为空；
  - 这条行满足 `user_data_licences` 的 live_has_secret 与 deleted_wiped 约束，不含任何密文或真实证书；
  - 再复制 owned 快照，填该 licence_id，插入一行，断言 `baseline.read` 抛 NOT_FOUND。
  - 删除「查不到证书就跳过这半句」的分支（cb96fba 报告该半句当前被跳过，属静默）。B 实现不读证书表，不受影响。
- **J10 `slot_jobs` / `schedule`：**
  - `schedule(settings)` 是纯函数，须实际调用，断言其键与 `TASKS` 中对应函数都不来自 daily_snapshot 模块。
  - `slot_jobs` 在 17:30、18:00、18:30 窗口内会连库，保留源码静态检查。
  - 补一条：对 `workers/jobs.py` 全文静态扫描，不出现 build_owned_snapshot、daily_bars_ready、daily_snapshot。理由：只比 `__module__` 会漏掉在 jobs 里包一层的任务。
- **J11 日报「估值不取该日」的观测面：** 观测 `reports/service.build` 写出的 daily_reports 行。
  - Given：仅本例内去掉 u1 的 H 持仓行，使账户估值可计算。（**已由 T-A137 细化**：持仓明细只追加，改为本例内追加一份 version_no=2 的持仓快照，只含 A、B，同时去掉 H 和无行情的 ETF D；`build` 的 now 须满足 §12.3。）
  - Then：
    - body.account 非空；
    - body.account.total_assets 等于「A 取 11-10 收盘 × 数量 + B 取 11-09 收盘 × 数量 + 现金」，两位小数，ROUND_HALF_UP，现金取 `api/v1/portfolio._account` 的 cash，为空按 0.00；
    - gaps 不含 `account.<B>.price`。
  - `/portfolio` 继续用 `latest_daily_close` 断言 B 取 11-09。
  - 仅断言 build 返回非空，不足以证明估值没取该日。
- **J12 uuid5 拼接串：** 由 OWNED_VERSION、str(owner)（小写带连字符的标准形式）、trade_date 的 ISO 日期、hash 四段用英文冒号依次连接，作为 uuid5(NAMESPACE_URL, …) 的 name。与 cb96fba 的实现一致。测试应断言快照 id 等于按此公式算出的值，把幂等固定下来。
- **J13：** 用例 1 的 Then 改为：ok 与 partial 为 True；没有运行、skipped、failed、running 为 False。测试在循环里补 running 和「无行」两组。
- **J14（后端 T-B128 提出的 §2 / §5 措辞）：** §2 bars 行中「trade_date 当天的 `ANALYZE_AS_OF`」的 trade_date，指 §2 表头所述的入参 trade_date，即快照日。入选截止是快照日 17:30；is_final 仍按每根 bar 自己的 trade_date 当天 `FINAL_AFTER` 判定。cb96fba 的读法正确，不改。理由：按每根 bar 自己的日期截止，会把盘后补取的历史行全部排除。

### 10.2 T-B128 剩余 5 红：归测试补全种子卡，契约口径不改

- 5 例：`test_owned_snapshot_idempotent_rerun`、`test_snapshot_conflict_keeps_first_row`、`test_analyze_fake_bars_produces_evaluations`、`test_missing_factor_stays_gap_not_one`、`test_analyze_partial_bars_gaps_no_fabricated_suggestion`。
- 产生处：`workers/assembly.conclusion` 内部要求以下条件同时成立，否则抛 `p1_rule_evidence_counter_invalidation_missing`：
  - rule_refs 非空；
  - evaluation evidence 非空；
  - 至少一条 role 为 counter 的规则；
  - 至少一条 role 为 invalidation 的规则。
- 这是既有的「宁缺勿造」校验：P1 结论必须带反证和失效条件。§1 规定 conclusion 流程不变，B 没有理由改它。
- 契约错在 §8 种子写了「形状同 `selfchecks/test_tb76_daily`」，那张卡只有 entry 一条规则，在当前 `conclusion` 下必然抛错。**本节更正为：卡形状同 `selfchecks/test_tb76_assembly` 的虚构接线卡。**
- 最小卡（全部虚构，config 写入 strategy_versions，card_version 的 fields 维持 mount_policy 为 user）：
  - rules 共 4 条，dimension 均为 technical，eval_time 均为 daily_close，weight 均为 1：
    - E：role entry，表达式「f.close_qfq 大于 0」；
    - X：role exit，「f.close_qfq 大于 0」；
    - C：role counter，「f.close_qfq 小于 0」；
    - I：role invalidation，「f.close_qfq 小于 0」。
  - action_map：entry_all_core_pass 为 buy，held_hold 为 hold，exit 为 sell，else 为 wait。
  - dimension_view_thresholds：bullish 0.67，bearish 0.33。`conclusion` 按维度出 view 时必读这一项，缺了会 KeyError。
  - stops：stop_loss、take_profit 为空，time_stop_days 为 5；valid_until 的 trading_days 为 40。种子日历只有 5 行，所以 valid_until 会如实成为缺口，不会抛错。
  - feature_catalog 已有 f.close_qfq（declared）。这是前置条件，不由迁移提供，见 §12.2。`strategy/cards/dsl` 的 Interpreter 在值为 None 时也会记录输入，所以 qfq 全为 null 时 evidence 仍非空，`conclusion` 能走完。
- 不允许的做法：
  - 让这 5 例只断言快照或评估、不跑 conclusion，因为用例 15 的「建议不重复归档」和用例 22 的「没有 B 的建议」都依赖 conclusion 与归档；
  - 让 analyze 把该 ValueError 吞成 issue，这是行为变更，不在本单范围。
- 若补卡后仍有其他异常，测试按原样报回，不改断言。
- 后端无需改动。

### 10.3 回归跑法

**事实（只读核对，2026-11-10 21:50 前后，北京时间）**

- **tb70 夹具**：`selfchecks/test_tb70_replay.integration` 写死连接 postgres 用户、库 tb70_replay、UNIX socket 目录 /tmp/tb70-pg-socket（默认 5432 套接字名），不读环境变量。
  - socket 不存在时 skip。
  - 通过 `replay/baseline.require_isolated` 要求：app_env 为 test、库名以 tb70_ 开头、socket 目录以 /tmp/tb70- 开头。
  - 要求 alembic 版本**恰为 0020**，已过时：当前头是 0032，cb96fba 未加迁移。
  - Redis 使用 /tmp/tb70-redis-socket/redis.sock；`no_network` 只放行 AF_UNIX。
  - `test_tb76_daily` 与 `test_tb76_assembly` 复用这个夹具，合计 10 例 skip。
- **p2n04 夹具**：`selfchecks/test_p2n04_daily_dimensions.database` 调 `selfchecks/test_p2n03_tracking.database`。
  - socket 改为 /tmp/tb70-p2n04-pg-socket，Redis 为 /tmp/p2n04-redis/redis.sock。
  - 对 socket 是否存在用的是 **assert**，所以缺 socket 时 21 个 setup error。
  - 要求 listen_addresses 为空，即不监听 TCP。
  - 自建库 tb70_p2n03_随机后缀，迁到 head，执行 deploy_grants，以 aia_api 连接，结束时 DROP WITH FORCE。
  - `selfchecks/test_p2n02_risk_controls.database` 是同样写法。
- **仓库里没有起 tb70 socket 的脚本**：selfchecks/、deploy/、tests/、scripts/ 均无。
  - 唯一先例是 T-T21 日志：PG、Redis 和 runner 都用 `--network none`，同一个具名卷在 runner 内挂到 /tmp/tb70-pg-socket 与 /tmp/tb70-redis-socket。
  - `tests/backend/milestone/tt21_plugin.py` 有现成的夹具替换钩子：缺 socket 时直接 fail，迁移期望不用 0020。但它依赖的 `tt21_head.expected_main_head` 把迁移文件钉在 dcf734d，到 0031、0032 必然失败，不能原样用。
  - `scripts/ci/assert_a1s_a32_ran.py` 是现成的「junit 中必须执行、不得 skip」校验写法，可以参照。
- **现有实例与归属**（docker ps、ss 与 status、reports 核对）：

| 实例 | 连接 | 归属 / 用途 |
|---|---|---|
| o61-pg | host 网络，127.0.0.1:55461，socket 在 /tmp/o61-pg，端口名 55461 | 运维 T-O61 保留；测试和后端用 `pg_o61.guard_temp_pg` 在上面建 tt*、o61_tmp_* 临时库 |
| o60-pg | 55460 | 运维 T-O60 |
| o57-pg | 55457 | 运维 T-O57、T-O58 |
| o55-p2-pg | 55494 | 运维 T-O55 |
| o53-p3-pg | bridge 网络，socket /tmp/o53-p3-pg | 运维 T-O53；测试 T-T36 用过 |
| o33-review-pg | 无网络，socket /tmp/tb70-tb91-owned-socket | 运维 T-O33 评审环境（t_o33_review） |
| o33-review-redis | 无网络 | 运维 T-O33 评审环境 |
| tb58-isolated-pg3 | 无网络，socket /tmp/tb58-pg3-socket | 后端 T-B58 遗留 |
| tb61-isolated-redis2 | 无网络 | 后端遗留（见 reports/T-B63.md） |

  - /tmp 下多处 .s.PGSQL 文件是已停实例的残留，文件存在不等于实例在跑。
  - /tmp/tb70-pg-socket 与 /tmp/tb70-redis-socket 是空目录，/tmp/tb70-p2n04-pg-socket 不存在。

**后端问「能否在 o61-pg 自建临时库并挂 socket 重跑」：不可以。**

1. o61-pg 监听 127.0.0.1，p2n03/p2n04 夹具断言 listen_addresses 为空，必然失败。这条是隔离保证，不得删。
2. o61-pg 的 socket 在 /tmp/o61-pg，端口名 55461。要让夹具连上，只能在 /tmp/tb70-* 下放符号链接或 socat 之类代理指向 o61。这等于给他人实例做端口/套接字转发，违反「不建转发、不碰他人实例」，还会让 `require_isolated` 的路径检查名存实亡。
3. tb70 夹具不读环境变量，用环境变量替代需要先改夹具。即使改了，也要放宽 AF_UNIX、listen_addresses、socket 前缀三条隔离断言，这属于放宽断言。
4. tb70 夹具的库名固定为 tb70_replay，不符合 `pg_o61` 只允许 tt* 与 o61_tmp_* 库名的护栏。

- o33-review-pg 的 socket 前缀虽然合规，但它是运维在用的评审实例，不借用。

**跑法：新起一套专用、无网络的临时实例。归测试，单号建议 T-T71b。**

- **时点**：后端交回单 B（现为 cb96fba）之后、架构师评审 T-B128 之前。测试补完种子卡（10.2）与 J 系列改动后，一次跑完。
- **起之前先查归属**，并把核对结果写进 status/测试.md：
  - `docker ps -a` 与 `docker volume ls` 确认拟用名字未被占用；
  - 拟用名：容器 tt71b-regress-pg、tt71b-regress-redis，卷 tt71b-regress-sock、tt71b-regress-redissock；
  - 实例全部 `--network none`，不发布端口，不写宿主 /tmp 的 tb70-* 目录（socket 只在卷里），所以不占任何端口。
- **PG**：本机已有镜像 timescale/timescaledb:2.31.0-pg16，参数 listen_addresses 为空，socket 目录为卷挂载点。
  - 只建 tb70_replay 一个库，以 alembic 迁到当时的单一 head；其余库由 p2n 夹具自建自删。迁到 head 后 feature_catalog 为空，须先按 §12.2 播种，再跑回归（T-A137 补）。
  - 不复制任何真实数据，不放股东代码。
- **Redis**：本机已有镜像 redis:7.4.12-alpine，unixsocket 放在 Redis 卷里。
- **runner**：沿用 T-T21 写法：本机镜像 aia-backend:aia-t01，`--network none`，代码只读挂载。
  - PG 卷同时挂到 /tmp/tb70-pg-socket 与 /tmp/tb70-p2n04-pg-socket；
  - Redis 卷同时挂到 /tmp/tb70-redis-socket 与 /tmp/p2n04-redis；
  - 不改夹具里的路径。
- **强制真跑开关**（由测试在 tests/ 下新增，例如 `tests/backend/milestone/tt71_regress_plugin.py`，以 `-p` 显式启用，仿 tt21_plugin）：
  - 只替换 tb70 integration 夹具中过时的「恰为 0020」期望，改为迁移图动态算出的唯一 head；仍要求单头、根为 0001。其他断言一字不改。
  - 在会话结束时检查：tb70、tb76_assembly、tb76_daily、p2n04 四个文件中只要有 skip，整次运行非零退出。
  - 不启用插件时，行为与现在相同。
- **跑两遍、同一命令**：先在 50835e3（B 之前）跑，再在 B 分支头跑。
  - 逐节点对比，B 不得新增 fail 或 error。
  - B 之前就失败的列为基线，单列报告，不算 B 的阻塞。例如 `test_tb76_daily` 中期望 `p1_conclusion_assembler_missing` 的旧例，可能在当前 conclusion 下已失效，以实测为准。
  - T-T70 A 套件、A1s–A32 照旧用 o61 的 guard_temp_pg 跑，不进这套实例。
- **清理**：跑完立即停止并删除测试自建的 2 个容器和 4 个具名卷（只删自己建的）。
  - 不动 tt20-*、tt21-* 卷与任何匿名卷，包括 17:02 的那个匿名卷；
  - 不动他人容器；
  - 在 status/测试.md 记录起止时间与名字，报告里附逐节点结果和两遍对比。
- **p2n04 缺 socket 时用 assert 的问题：归后端修**（src/backend/selfchecks 属后端）。做法：
  - 在 T-B128 上另起一个提交，不与 B 逻辑混在一起；
  - 把 `selfchecks/test_p2n03_tracking.database` 与 `selfchecks/test_p2n02_risk_controls.database` 中「socket 文件存在」的 assert 改为 pytest.skip，原因文案与 tb70 一致：专用无网络 PG 未供给；
  - listen_addresses 为空等隔离断言保持 assert，不改；
  - 默认 skip，评审前由上面的插件强制真跑。这样不会把应真跑的回归变成静默 skip：评审报告必须附插件模式下 0 skip 的结果，否则该轮回归视为未跑。
- tb70 夹具中「恰为 0020」的旧断言只在插件模式下被替换，selfchecks 原文暂不改。是否在 selfchecks 中改成动态 head，另开单，不阻塞 B。

### 10.4 两份改动清单

- **测试（T-T71b，只改 tests/）**：
  - 种子卡按 10.2 补全；
  - J3、J5、J6、J7、J8、J9、J10、J11、J12、J13 按 10.1 改断言或补构造，删除 repr 子串、恒真比较、条件跳过等写法；
  - 用例 18 另加 `daily_bars_ready` 计数桩，断言为 0 次；
  - 新增强制真跑插件，按 10.3 起停专用实例，跑两遍并对比。
- **后端（T-B128 追加，只改 src/backend/）**：
  - 只做 p2n02、p2n03 夹具中「socket 文件存在」的 assert 改 skip，单独一个提交；
  - B 逻辑不改：J5、J8、J12、J14 已与本节一致；10.2 不需要后端改动。

### 10.5 只有用户能定的

本节无新增。~~QB1、Q2、Q4、Q5 维持 §9 的保守默认。~~ **已由 T-A135 取代**：QB1、Q4、Q5 已裁定（§11）；Q2 维持保守。

## 11. 用户裁定落地（T-A135）

依据：`/workspace/team/rules/daily-bars-user-decisions-2026-11-10.md`；取数侧的全部细节在 `daily-bars-source.md` §8，本节只写对单 B 的影响。源码按 be/T-B128 `af77bb5` 核对。Q2 不变：不写 factors，缺因子走 `adjust_factor_missing`，不补 1。

### 11.1 Q4：快照范围随 `daily_universe` 扩大到本人有效自选

- `build_owned_snapshot` 的签名和流程不变，范围仍取 `daily_universe(conn, owner, trade_date)`；该函数改为「合格持仓 ∪ 本人 `removed_at IS NULL` 的合格自选」（`daily-bars-source.md` §8.2）。所以自选代码按 §2 的同一套规则建 instrument：board 为空照样 omitted，当日无行照样 `daily_bars_missing:<code>`。
- `analyze` 对 account 范围实例本来就遍历「持仓 ∪ 有效自选」（`workers/daily.analyze` 的 codes）。范围扩大后，自选代码有了 instrument，正常求值，不再记 `owned_source_security_missing:<code>`。scope=security 的实例只在代码属于持仓或自选时求值，不变。
- `daily_bars_ready` 带出 issue 的「owner 当日 universe」同样包含自选代码。
- 幂等：持仓、自选和日 K 都不变时 hash 与 id 不变；同日内自选变化会得到新的 hash 和新 id，旧快照保留，analyze 用本次返回的 id（§5 规则不变）。
- 种子：自选行只加在下面列出的用例里，§8 的公共种子不加，免得改动用例 4、20、22 等的期望。
- G/W/T：
  - 用例 14 `test_snapshot_only_owner_universe`（改 Then）：Given u1 有效自选 E（stock、listed、board 有值）、已移除自选 E2；u2 持有 C / Then u1 快照的 instruments 恰为 A、B、E（另加 omitted 中的 H），不含 C、E2。
  - `test_analyze_watchlist_code_evaluated`（新）：Given 源为 fake、u1 有效自选 E 当日有行、u1 的 account 范围实例 / When 跑 analyze / Then E 有 evaluation，source_hash 等于快照 hash；issues 不含 `owned_source_security_missing:E`。
  - `test_ready_carries_only_owner_issues`（加一组）：Given u1 有效自选 C、partial 运行 issues 含 `daily_bars_missing:C` / Then u1 拿到该条。
  - `test_snapshot_watchlist_change_new_id`（新）：Given 同日先 build 一次，再给 u1 加有效自选 E 后 build / Then 两个 id 不同，第一行仍在，`load_inputs(u1, A, 当日)` 取后者。

### 11.2 Q3：回填行进入快照的口径

- 不改 §2。回填行的 fetched_at 是回填运行时刻，晚于各自 trade_date 的 17:10，所以 `is_final` 为真；入选截止按快照日 17:30（§10 J14），所以回填之后的快照会带上这些历史 bar。
- 回填不得在开市日 17:45 之前把当日也取进来（`daily-bars-source.md` §8.3 的 CLI 规则），否则当日行非完成版且不可覆盖，当日只能记 `daily_bars_not_final:<code>`。
- 体积提醒：sessions 从最早入选行算起，3 年回填后每只约 730 根 bar，每个快照随 N 线性变大，每日一行。是否把 sessions 截到卡的最长 lookback，另开单，本单不改（见 reports/T-A135.md 的风险）。
- G/W/T：
  - `test_snapshot_includes_backfilled_history`（新）：Given 先以 trade_date=11-09、`window_trading_days=2`、`fetched_at`=11-09 北京 20:00 调 `fetch_and_record`，写入 11-06、11-09；再以 trade_date=11-10、`fetched_at`=11-10 北京 17:15 取当日 / When 以 11-10 build / Then 11-06、11-09、11-10 三根 bar 都入选且 is_final 为真；omitted 不含 A、B。
  - 用例 10 `test_snapshot_today_bar_outside_final_window_omitted`（不变）。

### 11.3 Q5 / QB1：17:15 取数，analyze 仍 17:30

- `ANALYZE_AS_OF`（17:30）、`FINAL_AFTER`（17:10）不变；analyze 仍在 `slot_jobs` 的 17:30 钟点。取数在 17:15 由 `slot_jobs` 排程（`daily-bars-source.md` §8.4）。
- 快照**仍由 analyze 首次过闸时惰性生成**，不注册任务、不进 `slot_jobs`/`schedule()`。
- 正常路径：17:15 取到的行在 [17:10, 17:30] 内，当日可见。取数拖过 17:30 时，晚到的标的记 `daily_bars_after_asof:<code>`，次日作为历史 bar 入选；取数事务在 analyze 时尚未提交，则记 `daily_bars_not_ready`。都不求值、不补跑。
- G/W/T：
  - 用例 26 `test_daily_snapshot_not_a_task`（不变）。§10 J10 对 `workers/jobs.py` 的静态扫描照旧：新加的 17:15 分支和常量里不得出现 build_owned_snapshot、daily_bars_ready、daily_snapshot 字样，注释也算。
  - `test_late_fetch_row_used_as_history_next_day`（新）：Given A 在 11-09 的行 fetched_at 为 11-09 17:35 / When 以 11-09 build，再以 11-10 build / Then 前者 omitted 含 `daily_bars_after_asof:A`；后者 A 的 bars 含 11-09 且 is_final 为真。

### 11.4 Q1：对单 B 无影响

- B 仍是麦蕊 0 调用（§6 不变）。上限常量和开放条件只在单 C 与开放单 D，B 不读。

### 11.5 只有用户能定的

- 新增的 U1（日报生成时刻）、U2（新标的自动补历史）、U3（每批防失控上限）列在 `daily-bars-source.md` §8.6。Q2 仍待定，维持保守。

## 12. 无行情标的与测试前置条件（T-A137）

依据：测试 T-T71b `e41967a`（`/workspace/team/reports/T-T71b.md` 歧义 1、2、4）。行为按 be/T-B128 `af77bb5` 的实际代码核对；本节只把现行代码行为写成契约，**不要求后端改代码**。

### 12.1 owned-daily-v1 里的无行情标的

T-T71b 歧义 1 里的「v2」是用例 28 追加的 **version_no=2 持仓快照**（`broker_position_snapshots`），不是 owned 快照的新 schema。owned-daily-v1 本来就不含 ETF D。无行情标的分两类，判定和去向不同：

| 类别 | 判定条件 | 在 owned 快照里 | `build_owned_snapshot` 的 issue | `workers/daily.analyze` 的行为 |
|---|---|---|---|---|
| 不合格标的（如 ETF D、listing_status 为空的 G） | 不满足「type 为 stock 且 listing_status 为 listed」，由 `marketdata/daily_bars.daily_universe` 的资格过滤剔除 | 不建 instrument，**也不进 omitted** | 无 | account 范围实例遍历「持仓 ∪ 有效自选」时，在读 instrument 之前就记 `security_not_eligible:<code>` 并跳过：不求值、不生成建议；不记 `owned_source_security_missing` |
| 合格但当日没有可用行 | 在 `daily_universe` 里，但当日无入选行、只有 source 为空的旧式行、board 为空，或 fetched_at 不在 17:10–17:30 | 不建 instrument，进 omitted | 按 §2：`daily_bars_missing:<code>`、`security_board_missing:<code>`、`daily_bars_not_final:<code>`、`daily_bars_after_asof:<code>` | 并入该 issue，另记 `owned_source_security_missing:<code>`，不求值 |

- 不合格标的不进 omitted 的理由：omitted 只记「本该进快照而进不了」的标的；不合格标的本来就不在范围内，不取数（单 A 也不为它请求），记缺口会误导。
- 对日报的影响（`reports/service.build`，现行行为，不改）：持仓里的无行情标的既没有日 K 收盘、也没有券商参考价和已知成本时，账户估值整体不可算，`body.account` 为 null，gaps 含 `account`。有已知成本时按成本估值，并记 `account.<code>.price`。用例 28 的口径是 A 取 11-10 收盘、B 取 11-09 收盘，再加现金；要得到这个口径，本例的持仓快照必须同时去掉 H 和 D（§10.1 J11 已按此细化）。
- G/W/T：
  - `test_snapshot_excludes_ineligible_codes_silently`（新）：Given u1 持有 A、B、D（etf）、G（stock，listing_status 为空），都有当日 fake 行 / When `build_owned_snapshot(u1, 11-10)` / Then instruments 里没有 D、G；omitted 里也没有 D、G；返回的 issue 元组里没有含 D、G 的项。
  - `test_analyze_ineligible_holding_not_evaluated`（新）：Given 同上、account 范围实例 / When 跑 analyze / Then issues 含 `security_not_eligible:D` 和 `security_not_eligible:G`，不含 `owned_source_security_missing:D`；evaluations 里没有 D、G。
  - `test_report_account_null_when_holding_unpriced_uncosted`（新，守护现状）：Given u1 持有 D，D 无日 K、无券商参考价、成本未知，now 满足 §12.3 / When `reports/service.build` / Then daily_reports 行的 body.account 为 null，gaps 含 key 为 account 的项，不抛错。
  - 用例 28 `test_placeholder_rows_ignored_by_price_readers`：接受 T-T71b 的做法（追加只含 A、B 的 version_no=2 持仓快照，不 DELETE 持仓行），断言不变。

### 12.2 前置条件：feature_catalog 先播种

- 条件：跑 analyze 之前，`strategy.feature_catalog` 里必须已有卡规则引用的每个特征键。迁移**不**播种这张表（迁到 head 后为 0 行）。
  - 单元套件（`tests/backend/unit/test_daily_snapshot_impl_b.py`）：由 `_seed_b` 插入 f.close_qfq（declared），已满足。
  - 隔离回归（§10.3 的专用实例）：迁到 head 之后、跑 tb76/p2n04 之前，用官方的 feature_registry 加 load_metadata、import_metadata 写入目录；不导入正式卡，不 `--apply`。
- 违反时的行为（按 af77bb5 核对，分两种，都**不是**宁缺勿造的 issue 化）：
  - 卡版本 config **没有** source_hash（T-T71 的虚构卡就是这样）：`analyze` 用空 registry 调 `evaluate_snapshot`，`strategy/cards/dsl` 编译规则时抛 `ValueError("dsl_unknown_symbol")`。`analyze` 不捕获，**整次 ANALYZE 拒绝运行**：失败 owner 的事务回滚（含刚建的 owned 快照）；`workers/daily.phase` 把 tb76.analysis 运行记为 failed，error 只写 ValueError，然后原样抛出；worker 按 `RETRY_TASKS` 10 分钟后重试，共 3 次，用尽后调 `final_failure`。在它之前已经提交的 owner 结果保留。
  - 卡版本 config **有** source_hash：先过 `source_issues`，缺目录行的特征记 `runtime_source_gate:<特征键>:feature_not_verified_doc_or_live`，跳过该实例，**不抛错**，日报照出。declared 状态同样走这条，所以 T-T71 的种子卡**不得**带 source_hash，否则会在 source gate 处停下、不到 conclusion。
- G/W/T：
  - `test_analyze_empty_catalog_rejects_run`（新）：Given 临时库里 feature_catalog 为空、虚构卡没有 source_hash、fake 源已就绪 / When 经 `workers/daily.analysis_task` 跑 11-10 / Then 抛 ValueError；最新 tb76.analysis 运行 status 为 failed、error 为 ValueError；u1 的 owned-daily-v1 行数为 0；suggestions 零写入。
  - `test_analyze_missing_catalog_with_source_hash_is_gate_issue`（新）：Given feature_catalog 为空，卡 config 带 source_hash / When 跑 analyze / Then 不抛错；issues 含 `runtime_source_gate:f.close_qfq:feature_not_verified_doc_or_live`；没有该实例的 evaluation。

### 12.3 前置条件：`build` 的 now 不早于 ledger_at

- 条件：调用 `reports/service.build(conn, user_id, date, now)` 时，now 不得早于本人账户的 ledger_at（`api/v1/portfolio._ledger_as_of`：holdings.rebuilt_at、trades 的 created_at 或 voided_at、broker_position_snapshots.created_at 中的最大值），也不得早于账户的 price_at。生产路径自动满足：`workers/daily.phase` 的 REPORT 传入墙钟时间。测试里种子行的时间戳是建库时的真实墙钟，所以写死成 11-10 17:30 往往早于 ledger_at，必须传一个确定晚于种子时刻的 now（T-T71b 用 2030-01-01 UTC）。
- 违反时的行为（按 af77bb5 核对）：**不拒绝、不抛错**，按「未来账本不可回看」把账户整体置空：
  - body.account 为 null，gaps 含 key 为 account 的项；
  - 账户置空后持仓字典为空，日报的标的列表只剩有效自选，持仓标的不出现；
  - 报告照常写入 daily_reports。
- G/W/T：
  - `test_report_build_now_before_ledger_nulls_account`（新）：Given u1 的持仓快照已在墙钟时刻 t 写入 / When `build(conn, u1, 11-10, now=t 减 1 小时)` / Then 不抛错；body.account 为 null；gaps 含 account；body 的标的列表不含 A、B（u1 无自选时为空）。
  - `test_report_build_now_after_ledger_computes`：由用例 28 覆盖（now 为 2030-01-01 UTC，body.account 非空）。

### 12.4 与代码、测试的不一致（截至 af77bb5 / e41967a）

- 代码：12.1–12.3 都是 af77bb5 的现行行为，无不一致，后端无需改动。
- 测试（非阻断）：e41967a 的 `_seed_b` 在公共种子里给 u1 加了有效自选 E。af77bb5 的 `daily_universe` 只取持仓，所以当前 28/28 绿；但 §11.1 规定公共种子不加自选行，A 补丁单让 `daily_universe` 纳入自选后，用例 4、20、22 等会因多出 E 而变红。须在 A 补丁单落地之前，把 E 的自选行移到用例 14 和 §11.1 列出的新用例里。
- 测试（非阻断）：§10.3 原先没有写播种 feature_catalog 这一步，T-T71b 自行补做，现已写入 12.2。
- 不归本契约（非阻断，既有）：`selfchecks/test_tb76_assembly`、`test_tb76_daily` 里三例在 50835e3 与 af77bb5 上同样失败（worker 在 ANALYZE 成功后同一 tick 执行 TRACKING；只有 entry 规则的卡被 conclusion 的反证/失效校验打断）。须另开允许改 selfchecks 的后端单处理。
