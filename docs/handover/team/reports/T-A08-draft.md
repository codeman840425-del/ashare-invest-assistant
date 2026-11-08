# T-A08 草案：契约 v0.2.7 补缺（策略 risk_level、策略实例列表与状态机、个股数据接口、周 K 口径、/today 补块）

- 起草：执行代理（替架构师），2026-11-02（北京时间）。**只是草案**：仓库只读，`docs/api-contract.md`、`docs/plan.md`、README、backlog 一律未改，也未提交。
- 基线：仓库 HEAD `8405877`（契约 v0.2.6，785 行）；前端对比对象为 `b79ce80`（T-F03 个股/市场 mock）、`5f8b5e0`（策略 mock）、`8405877`（T-F08 /today）。
- 依据：契约 v0.2.6 §1、§1.1、§1.2、§3、§4、§5.1、§6.0、§7.3–§7.10；plan 2.1B（per_licence）、2.4、3.3、4.4；`T007.md`（证券主数据）；`T003-mairui-capability.md`（麦蕊能力）；`T-F03.md`、`T-F08.md`、`frontend-backlog.md`、`T-O09.md`。
- 约定：标【待补测】【待 T003 补测】的数值或映射，必须等实测结果出来才能定稿；本草案不新增任何与荐股、评级、目标价相关的字段或文案。
- 使用方式：第 1–3 节可以直接粘进契约（第 1 节放 §0 顶部，第 2 节按小标题放进对应章节，第 3 节放 §9）；第 4–7 节是给架构师和编排者看的说明。

---

## 1. 变更记录（粘到契约 §0 顶部，放在 v0.2.6 之前）

### v0.2.7（2026-11-02，T-A08：补齐策略列表 `risk_level`、策略实例列表与状态机、个股数据接口、周 K 口径、`/today` 的提醒、计划触发与数据缺口；**无不兼容变更**：只新增端点、字段和枚举值；`/securities?q=` 保留为别名）

| # | 项 | 决定 | 后端改动 | 前端改动 |
|---|---|---|---|---|
| 1 | `/strategies` 风险等级 | 列表元素和版本详情加 `risk_level: card_risk_level`（取当前版本关联 L1 卡片的值；未关联卡片时为 `normal`；派生版本继承母版本）；列表加筛选 `?risk_level=` | 查询时 join 卡片版本 | 列表徽标；启用开关旁的固定风险说明改为读列表字段（不再单独请求卡片） |
| 2 | 策略实例对象 | 定义 `StrategyInstance` 完整结构（§5.1）；`origin` 新增 `system`（H-01 一类系统挂载）；新增字段 `horizon`、`paused_by`、`pause_reason_code`、`paused_until`、`updated_at`、`archived_at` | `strategy_instances` 加列；`origin` 约束加 `system` | 用完整类型替换“最小字段” |
| 3 | 策略实例列表 | `GET /strategy-instances`：筛选（`status` 可多值，默认 `proposed,active,paused`）、§1.2 游标分页、`order: instance_sort` | 新增查询与索引 | 列表页筛选和排序 |
| 4 | 实例状态机 | 明确 confirm/pause/resume/archive 的合法转换、请求体、幂等（目标态即当前态时返回 200 且不写事件）、`409 INVALID_STATE_TRANSITION{from,to,allowed}`；`origin=system` 的实例不能由用户归档；`/events` 元素结构 | 行锁 + 事件表 | 按 `allowed` 显示可用按钮；mock 改为幂等 |
| 5 | 证券搜索 | 新增 `GET /securities/search`：代码、简称、拼音首字母、曾用名、旧代码、模糊（pg_trgm）；分层排序；`/securities?q=` 保留为别名，结构不变 | `pg_trgm`、`name_initials`、历史表 | 搜索框改用新端点，展示 `match_kind` |
| 6 | 证券资料 | 新增 `GET /securities/{code}`（`SecurityProfile`）：交易所主数据（全站一份）+ 本人证书取到的行业、概念、股本 | 新增 | 字段改名（见第 5 节） |
| 7 | 财务 | 新增 `GET /securities/{code}/financials` | 新增 | 增加 `report_period`、`announce_date` 展示 |
| 8 | 资金流 | 新增 `GET /securities/{code}/fund-flows` | 新增 | 分档净额允许为 null |
| 9 | 因子 | 新增 `GET /securities/{code}/factors`（只有全市场排名，**没有**行业内分位） | 新增 | 删除行业分位列 |
| 10 | 公告 | 新增 `GET /securities/{code}/announcements`：只给元数据和外链，不给正文和摘要 | 新增 + URL 白名单 | 外链只用 `url`，为 null 时不显示链接 |
| 11 | 板块资金 | 新增 `GET /market/sector-flows`：盘后数据，每日更新一次 | 新增 | `sector_id`→`sector_code`；停止 60 秒轮询 |
| 12 | 周 K 口径 | `freq=w`：自然周聚合日线、`t` 为该周最后一个有成交的交易日、未收盘周 `is_final=false`、复权同日线；`Bar` 加 `is_final`，bars 响应加 `adjust_as_of` | 聚合实现 | `adjust_as_of` 变化时整段重载 |
| 13 | 共享对象 | 新增 `ProviderRef`、`SecurityHit`、`SecurityProfile`、`FinancialPeriod`、`FundFlowDay`、`FactorValue`、`Announcement`、`SectorFlow`、`TodayAlert`、`TodayPlanTrigger`、`TodayDataGap`、`RiskEvent` | 同步 | 同步类型 |
| 14 | 枚举 | 新增 `security_type` `board` `listing_status` `security_risk_flag` `security_match_kind` `report_period` `factor_category` `announcement_category` `sector_kind` `industry_taxonomy` `instance_origin` `instance_event_kind` `instance_sort` `sector_sort` `alert_origin` `alert_status` `plan_condition_kind` `data_gap_scope`；`data_provider` 加 `exchange` | `/meta/enums` 同步 | 文案 |
| 15 | 读接口与证书 | 本节所有个股/板块**读**接口不返回 `409 DATA_LICENCE_UNAVAILABLE`，按 §1.1 只降级 `data_status` 并给 `data_licence_unavailable` gap；缓存未命中返回 `pending` 并按本人证书入队 | 按证书判定 | 横幅沿用 T-F22 |
| 16 | `/today` | 新增 `alerts`、`plan_triggers`、`data_gaps` 三块和顶层 `evidence[]`；`risk_flags` 元素加 `risk_event_id`；写明 6 个列表的“查看全部”去向 | T-B13 聚合 | T-F08 新增三块 |
| 17 | 列表补参（T-F17/T-F18） | `GET /candidate-signals` 元素即完整 `CandidateSignal`；`/non-executable-reasons` 加 `released_since`；`GET /plan-drafts` 加 `?status=&security_code=&signal_id=`，`PlanDraft` 加 `created_at`；`stale` 草案的重新生成就是用原 `signal_ids` 再 `POST /plan-drafts` | 同步 | 同步 |
<redacted:sensitive-value-or-command>
| — | `/meta/enums.version` | `"v0.2.6"` → `"v0.2.7"` | 同步 | `CONTRACT_VERSION` |

---

## 2. 正文增改（按章节粘贴）

### 2.1 §1.1 补充（数据状态：混合来源响应）

在 §1.1 `data_status` 段落末尾追加：

> **混合来源响应（v0.2.7）**：一个响应同时含“交易所主数据”（全站一份，`provider=exchange`）和“本人证书取到的麦蕊数据”时，`data_status` 只按证书部分判定。证书部分从未取到时为 `partial`（主数据仍返回），`gaps` 给出 `data_licence_unavailable` 或 `not_yet_published`，被影响的字段为 `null`；证书部分全部可用时按 0A.3 规则判定。**个股与板块类读接口**（§7.3 中 v0.2.7 新增的端点、`/securities/{code}/bars`、`/quotes`）**不返回** `409 DATA_LICENCE_UNAVAILABLE`；该错误码仍只用于需要触发拉取的写操作。
>
> **缓存未命中**：本人证书下没有缓存时返回 `200`，`data_status:"pending"`，按本人证书入队（P1）；当日该证书配额不足时 `gaps` 加 `{reason:"quota_deferred"}`，不报 429。
>
> **证书范围**：除 `provider=exchange` 的主数据外，所有字段都只来自本人证书取到的数据；**不会用他人证书的数据补齐**（与 v0.2.6 #1 一致）。

### 2.2 §3 枚举（新增与修改）

| 名称 | 取值 |
|---|---|
| `data_provider`（修改） | 原有取值 + `exchange`（沪深北交易所公开证券列表，见 T007；只用于证券主数据） |
| `security_type` | `stock` `cdr` `index`（ETF、可转债暂不收录，见未决 Q3） |
| `board` | `main` `chinext` `star` `bse` |
| `listing_status` | `listed` `delisting_period` `delisted` `missing_from_list`（`missing_from_list`=麦蕊或历史数据中有、但交易所当前列表中找不到，T007 §5）。**停牌不是上市状态**，用 `SecurityProfile.suspended` 表示 |
| `security_risk_flag` | `st` `star_st` `delisting`（同时命中时取最高一项：`delisting` > `star_st` > `st`） |
| `security_match_kind` | `code_exact` `name_exact` `initials_exact` `code_prefix` `name_prefix` `initials_prefix` `name_contains` `former_name` `former_code` `fuzzy`（按此顺序即排序层级） |
| `report_period` | `q1` `h1` `q3` `fy` |
| `factor_category` | 麦蕊因子的 11 个分类，键名按 T003 的分类表定稿【待 T003 补测：分类中文名与键名对照】 |
| `announcement_category` | `periodic_report` `other`（麦蕊只区分定期报告，原始分类放在 `category_raw`） |
| `sector_kind` | `industry` `concept` |
| `industry_taxonomy` | `sw_l1` `sw_l2` `csrc`（板块资金的 `industry` 对应哪套分类【待 T003 补测】） |
| `instance_origin` | `classifier` `user` `system` |
| `instance_event_kind` | `created` `confirmed` `paused` `resumed` `params_changed` `archived` |
| `instance_sort` | `created_at_desc`（默认） `updated_at_desc` `strategy_name_asc` |
| `sector_sort` | `main_net_desc`（默认） `main_net_asc` `change_pct_desc` `change_pct_asc` |
| `alert_origin` | `plan_condition` `holding_event` `user_custom`（plan 3.3 `alert_rules.origin`） |
| `alert_status` | `new` `read` `checked` `acted` `dismissed`（plan 3.3 `alerts.status`） |
| `plan_condition_kind` | `trigger` `invalidation`（plan 3.3 `plan_conditions.kind`） |
| `data_gap_scope` | `user` `account` `security` `market` |

`/meta/enums.enums` 的键集合与本表同步扩充。

### 2.3 §4 错误码（说明补充，不新增错误码）

- `NOT_FOUND`：v0.2.7 起，用北交所旧代码访问 `/securities/{code}*` 时返回 `404 NOT_FOUND`，`details: {superseded_by: string}`（新代码）。其余情况仍无 `details`。
- `INVALID_STATE_TRANSITION{from, to, allowed}`：`allowed` 是**用户从 `from` 出发、通过接口可以到达的目标状态**（不含系统专用转换），按 `instance_status` 枚举顺序排列；没有可达状态时为 `[]`。
- `INVALID_CURSOR`：游标与本次请求的筛选或排序参数不一致时也返回此码（v0.2.7 写明）。

### 2.4 §5.1 共享对象（新增与修改）

**`Bar`（修改）**：在原结构末尾加 `is_final: boolean`。日 K：当日收盘并入库后为 `true`，盘中返回的当日 bar 为 `false`；周 K 见 §6.4；1m：正在形成的那一分钟若返回则为 `false`【待 T003 补测：麦蕊分钟线是否返回未完成的那一分钟】。bars 响应顶层加 `adjust_as_of: string(date) | null`（前复权的基准日；`adjust=none` 时为 `null`）。客户端发现 `adjust_as_of` 变化时，必须丢弃已缓存的同证券、同复权方式的 bar 并重新加载。

**`ProviderRef`**：`{provider: data_provider, endpoint: string | null, fetched_at: string(datetime) | null}`。只用于展示类接口的 `sources[]`，用来注明来源；建议、信号类论断仍用 `Evidence`。

**`SecurityHit`**：`{security_code, name, type: security_type, exchange: "SH"|"SZ"|"BJ", board: board | null（指数为 null）, listing_status: listing_status | null, risk_flag: security_risk_flag | null, match_kind: security_match_kind, matched_text: string | null（命中的是曾用名、旧代码或拼音首字母时，给出命中的原文；其余为 null）, quote_missing: boolean | null（该代码在交易所列表中有、在本人证书的麦蕊代码集中没有时为 true；尚未比对时为 null【待补测：交易所与麦蕊代码集比对】）}`。

**`SecurityProfile`**：
```
{security_code, name, full_name: string | null, type: security_type, exchange, board: board | null,
 list_date: string(date) | null, list_date_basis: "listing" | "neeq_select" | null,
 delist_date: string(date) | null, listing_status: listing_status, risk_flag: security_risk_flag | null,
 former_names: [{name, until: string(date) | null}], code_history: [{security_code, until: string(date) | null}],
 master_as_of: string(date), attribution: string,
 industry: {taxonomy: industry_taxonomy, code: string, name: string} | null,
 concepts: [{code: string, name: string}],
 total_shares: string(decimal) | null, float_shares: string(decimal) | null,   // 单位：股
 suspended: boolean | null,
 sources: ProviderRef[], data_status, data_as_of, gaps}
```
- 第一行到 `attribution` 来自交易所主数据（`provider=exchange`，全站一份，T007）；`list_date_basis="neeq_select"` 表示北交所平移股取的是精选层挂牌日；`full_name` 在交易所列表中缺失时为 `null` 并带 `gaps[{key:"full_name", reason:"no_source"}]`；`attribution` 是固定的来源说明文字（如“证券列表来自上交所、深交所、北交所公开信息”），前端原样展示。
- `industry` 之后的字段来自本人证书（`provider=mairui`）；从未取到时为 `null` 或 `[]`，规则见 §1.1 混合来源响应。
- 指数：`board`、`list_date_basis`、股本、`industry` 为 `null`，`concepts` 为 `[]`。

**`FinancialPeriod`**：
```
{period_end: string(date), report_period: report_period, announce_date: string(date) | null,
 available_from: string(date) | null, is_restated: boolean,
 revenue, revenue_yoy_pct, net_profit, net_profit_yoy_pct, deducted_net_profit,
 eps, bvps, roe_pct, gross_margin_pct, debt_ratio_pct, operating_cash_flow}
```
从 `revenue` 起全部为 `string(decimal) | null`。金额单位元，`eps`/`bvps` 单位元/股，`*_pct` 为百分数（`12.3` 表示 12.3%）。利润表和现金流量表科目按报告期**累计**口径（Q3 = 1–9 月），不做单季拆分。`available_from` 为公告日的下一个交易日（时点视图用），未知时为 `null`。

**`FundFlowDay`**：`{trade_date, amount: string(decimal) | null（当日成交额）, main_net, super_large_net, large_net, medium_net, small_net, main_net_pct, is_final: boolean}`。除 `trade_date`、`is_final` 外均为 `string(decimal) | null`，单位元（`main_net_pct` 为百分数）。口径：主力 = 特大单 + 大单；净额 = 主动买入额 − 主动卖出额；分档阈值以麦蕊为准【待 T003 补测：分档阈值与 `main_net_pct` 的分母】。

**`FactorValue`**：`{factor_id: string（麦蕊原始因子 id）, feature_key: string | null（已登记进 feature_catalog 的为其键，否则为 null）, name: string, category: factor_category, value: string(decimal) | null, unit: string | null【待 T003 补测】, market_rank: int | null, market_rank_pct: string(decimal) | null【待 T003 补测：排名方向与样本数 N】}`。

**`Announcement`**：`{id, published_at: string(datetime), title: string, category: announcement_category, category_raw: string | null, level_raw: string | null, url: string | null, url_主机：<host> | null, file_format: "pdf" | "html" | "other" | null, first_seen_at: string(datetime)}`。`url` 只有在 `https` 且主机在白名单（交易所、巨潮等，配置 `announcements.url_host_allowlist`）内时才给出，否则为 `null`；`url_host` 始终是原始链接的主机名（无链接时为 `null`）。**不提供正文、摘要或任何由系统改写的内容。**

**`SectorFlow`**：`{sector_code: string, name: string, change_pct, main_net, amount: string(decimal) | null, up_count: int | null, down_count: int | null, leader: {security_code, name, change_pct} | null}`。金额单位元。`leader` 是当日该板块涨幅最大的成分股（客观行情事实，不构成任何建议）。

**`StrategyInstance`**：
```
{id, strategy_id, strategy_key, strategy_name, strategy_version_id, version_no: int, lifecycle: lifecycle,
 derived_strategy_version_id: uuid | null, risk_level: card_risk_level,
 status: instance_status, origin: instance_origin,
 scope: "account" | "security" | "watch_group", account_id: uuid | null,
 security_code: string | null, name: string | null,
 horizon: horizon, param_overrides: object | null, budget_amount: string(decimal) | null, auto_downweight: boolean,
 paused_by: "user" | "system" | null, pause_reason_code: reason_code | null, paused_until: string(datetime) | null,
 created_at, confirmed_at: string(datetime) | null, updated_at, archived_at: string(datetime) | null}
```
- `name` 是证券简称；`security_code` 为 `null` 时 `name` 也为 `null`（§1 “带 name”规则的例外，只适用于这里）。
- `strategy_version_id`、`version_no`、`lifecycle`、`risk_level` 指实例实际运行的版本：有派生版本时就是派生版本。
- `status != "paused"` 时，`paused_by`、`pause_reason_code`、`paused_until` 都为 `null`。用户暂停时 `pause_reason_code=null`、`paused_until=null`；系统因连续亏损暂停时 `pause_reason_code="LOSS_STREAK_PAUSE"`，`paused_until` 为自动恢复的时间。

<redacted:sensitive-value-or-command>

### 2.5 §6.0 实例状态机（替换原表中 `instance_status` 一行，并新增 §6.0A）

| 实例 `instance_status` | `proposed` `active` `paused` `archived` | proposed→active（用户确认）；active→paused（用户；或系统因 `LOSS_STREAK_PAUSE`）；paused→active（用户；或系统暂停到期后由系统恢复）；proposed/active/paused→archived（用户；`origin=system` 的实例只能由系统归档；分类结果变化后过时的 `proposed` 由系统归档）；archived 为终态 |

**§6.0A 实例操作（v0.2.7）**

| 操作 | 请求体 | 合法转换 | 幂等（当前已是目标态） | 非法时 |
|---|---|---|---|---|
| `POST /strategy-instances/{id}/confirm` | 无 | proposed→active | active → `200`，不变 | paused/archived → `409 INVALID_STATE_TRANSITION` |
| `POST .../pause` | `{note: string(≤200) \| null}`（可省略请求体） | active→paused（`paused_by="user"`） | paused → `200`，不变（**系统暂停不会被改写成用户暂停**） | proposed/archived → 409 |
| `POST .../resume` | `{note: string(≤200) \| null}` | paused→active | active → `200`，不变 | proposed/archived → 409 |
| `POST .../archive` | `{note: string(≤200) \| null}` | proposed/active/paused→archived | archived → `200`，不变 | `origin=system` → 409（`allowed` 不含 `archived`） |

规则：
1. 成功时一律返回 `200 StrategyInstance`（完整对象）。幂等的空操作也返回 `200` 和当前对象，**不写事件**、不改 `updated_at`。
2. 发生状态转换时写一条 `/events`，`actor` 为 `user` 或 `system`。服务端对实例加行锁，并发请求串行执行；先完成的一方转换状态，后到的一方按幂等或非法规则处理。
3. `allowed` 示例：从 `proposed` 出发为 `["active","archived"]`；从 `active` 出发为 `["paused","archived"]`；从 `paused` 出发为 `["active","archived"]`；从 `archived` 出发为 `[]`；`origin=system` 的实例去掉 `archived`。
4. confirm 或 resume 时，如果实际运行的版本 `lifecycle` 不可运行（如 `retired`、`simulating`），返回 `409 STRATEGY_VERSION_NOT_RUNNABLE{lifecycle}`，状态不变。
5. resume 一个系统暂停（`pause_reason_code="LOSS_STREAK_PAUSE"`）的实例，视为“用户确认恢复”：清空暂停字段，并在事件 `detail` 中记 `{released_reason_code: "LOSS_STREAK_PAUSE"}`。用户暂停的实例不会被系统自动恢复。
6. 暂停期间该实例不生成新的候选信号；已存在的候选信号状态不变。归档时如何处理仍开放的候选信号，见未决 Q5。
7. 对 archived 实例 `PATCH` → `409 IMMUTABLE_RESOURCE`。
8. `POST /strategy-instances` 创建的实例 `origin="user"`、直接为 `active`（与 v0.2.6 一致）；`proposed` 只由周期分类器产生（`origin="classifier"`）；`origin="system"` 只由系统挂载（如 H-01）。

### 2.6 §6.4 周 K 口径（新增小节）

1. **聚合方式**：由日 K 按自然周（周一到周日，北京时间）聚合，复权方式与同一请求的日 K 完全相同（`qfq` 与 `hfq` 都先对日线复权再聚合；`adjust` 默认 `qfq`）。不直接使用麦蕊的周线。
2. **`t`**：该周最后一个**有成交**的交易日（与 §5.1 `Bar.t` “周线取该周最后交易日”一致，并明确停牌日不算）。当周还没有结束时，`t` 为截至目前最新的有成交交易日。
3. **字段**：`open` 为该周第一个有成交日的开盘价；`close` 为 `t` 当日的收盘价；`high`/`low` 为周内最高和最低；`volume`、`amount` 为求和；`avg_price` = `amount / volume`（`volume=0` 时为 `null`）。
4. **`pre_close`**：上一根周 K 的 `close`；第一根取该周首个有成交日的日线 `pre_close`，没有则为 `null`。
5. **不完整周**（节假日、部分停牌）照常聚合，不补齐；整周停牌或休市的那一周**不出 bar**；麦蕊停牌占位行（`sf=1`）不参与聚合。
6. **`is_final`**：该周最后一个交易日已收盘、且当日日线已入库时为 `true`；否则为 `false`（包括盘中和收盘后日线尚未入库的时段）。
7. **复权映射**：`qfq` 对应麦蕊 `f`，`hfq` 对应 `b`，`none` 对应 `n`【待 T003 补测：`f` 与 `fr` 的差别、前复权基准日如何取得（填 `adjust_as_of`）】。
8. `limit`、`before`、`next_before` 按周 K 根数计算，规则与日 K 相同。

### 2.7 §7.3 行情与个股（新增与修改的行）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/securities/search` 🔒 | v0.2.7。`?q=`（必填，归一化后长度 1–20）`&types=`（逗号分隔 `security_type`，默认 `stock,cdr`）`&include_delisted=false&limit=`（默认 20，最大 50），**不分页** → `{items: SecurityHit[], master_as_of: string(date)}`。**归一化**：NFKC、去空白、字母转大写；`600000.SH`、`SH600000`、`sh600000`、`600000` 都按代码处理。**匹配范围**：6 位代码、简称、拼音首字母（例如 `PFYH`）、曾用名、北交所旧代码（经 `security_code_history` 解析到新代码，`match_kind=former_code`）、模糊匹配（`pg_trgm` 相似度 ≥ `search.similarity_threshold`，默认 0.3；查询中至少有 2 个汉字才启用）。**排序**：先按 `security_match_kind` 层级（`code_exact` > `name_exact` > `initials_exact` > `code_prefix` > `name_prefix` > `initials_prefix` > `name_contains` > `former_name` = `former_code` > `fuzzy`）；同层依次比较：`listing_status`（`listed` 优先，其次 `delisting_period`，其余靠后）→ `type`（`stock` > `cdr` > `index`）→ 命中位置（越靠前越优先）→ 简称长度（短的优先）→ trgm 相似度（降序）→ `security_code`（升序）。同一证券只出现一次，取最高层的命中。**拼音首字母**：用 pypinyin 生成，多音字的组合最多 16 个；另外生成去掉 `ST`/`*ST` 前缀的版本；巨潮提供的拼音只用于交叉校验。`include_delisted=false` 时排除 `delisted`，`missing_from_list` 仍返回。默认不含指数，未决 Q6。缓存：`Cache-Control: private, max-age=60`。q 为空或归一化后超长 → `400 VALIDATION_ERROR`。只查交易所主数据，不触发麦蕊拉取，也不受证书影响（`quote_missing` 除外） |
| GET | `/securities` 🔒 | `?q=`：**v0.2.7 起为 `/securities/search` 的别名**，`types` 和 `limit` 取默认值，返回结构保持 `[{security_code, name}]`（最多 20 条）。新代码请改用 `/securities/search` |
| GET | `/securities/{code}` 🔒 | v0.2.7。`SecurityProfile`（§5.1），弱 ETag。不存在 → `404 NOT_FOUND`；北交所旧代码 → `404 NOT_FOUND{superseded_by}`。主数据每日 18:00 更新、07:30 补拉（T007 §6）；行业、概念、股本按本人证书每日盘后更新；`suspended` 每个交易日 09:15 前按本人证书刷新【待 T003 补测：停牌标记的来源端点】 |
| GET | `/securities/{code}/financials` 🔒 | v0.2.7。`?report_period=`（可多值，默认全部）`&limit=`（默认 8，最大 40）`&as_of=`（日期，可选：只返回 `available_from ≤ as_of` 的报告期，时点视图）→ `{security_code, name, items: FinancialPeriod[]（period_end 降序）, sources: ProviderRef[], data_status, data_as_of, gaps}`，**不分页**。同一报告期有更正时只返回最新一版，`is_restated=true`。指数或无财务数据的证券：`200`，`items: []`，`data_status:"unavailable"`，`gaps:[{key:"financials", reason:"no_source"}]`。更新：每日盘后按本人证书增量拉取【待 T003 补测：财报端点与 `announce_date` 字段是否可得】 |
| GET | `/securities/{code}/fund-flows` 🔒 | v0.2.7。`?days=`（默认 60，最大 250）或 `?from=&to=`（日期，区间不超过 250 个交易日；两种方式同时给出 → `400 VALIDATION_ERROR`）→ `{security_code, name, items: FundFlowDay[]（trade_date 升序）, sources, data_status, data_as_of, gaps}`，不分页。停牌日不出行。当日数据在盘后更新（15:40 后）【待 T003 补测：更新时刻】，入库前不出当日行；更新后会再次校准的日期 `is_final=false`。指数 → `200` 空 `items` + `no_source` gap |
| GET | `/securities/{code}/factors` 🔒 | v0.2.7。`?trade_date=`（可选，默认最新）`&category=`（可多值）→ `{security_code, name, trade_date, factor_set_version: string, counts: {total: int, by_category: object<factor_category, int>}, items: FactorValue[], sources, data_status, data_as_of, gaps}`，不分页。因子数量为 85 个（77 个日频 + 8 个日内）【待 T003 补测：最终数量与单位】。北向资金类因子取不到时 `value` 为 `null`，并带 `gaps[{key:"factor.<id>", reason:"no_source"}]`。**不提供行业内分位**（未决 Q4）。每日盘后按本人证书更新 |
| GET | `/securities/{code}/announcements` 🔒 | v0.2.7。§1.2 游标分页（默认 `published_at desc, id desc`）；`?from=&to=&category=` → `Paged<Announcement> & {disclaimer: string, sources, data_status, data_as_of, gaps}`。`disclaimer` 为固定文案：“公告内容以交易所及上市公司披露原文为准，本系统仅提供标题与原文链接。” 每日盘后按本人证书更新，盘中不刷新【待 T003 补测】 |
| GET | `/market/sector-flows` 🔒 | v0.2.7。`?kind=industry\|concept`（必填）`&sort=`（`sector_sort`，默认 `main_net_desc`）`&limit=`（默认 20，最大 100），不分页 → `{kind, taxonomy: industry_taxonomy \| null（concept 时为 null）, trade_date, items: SectorFlow[], sources, data_status, data_as_of, gaps}`。**盘后数据**：每个交易日 15:40 后按本人证书更新一次，盘中返回上一交易日的数据；不提供盘中实时数据，前端不必轮询（响应带弱 ETag） |
| GET | `/securities/{code}/bars`（修改） | 增加 `freq=w` 的口径（§6.4）；`Bar` 加 `is_final`；响应顶层加 `adjust_as_of`。其他不变 |
| GET | `/today`（修改） | 见下方 §7.3 `/today` 补充 |

所有新增的个股读接口：`{code}` 不存在 → `404 NOT_FOUND`；用北交所旧代码 → `404{superseded_by}`；参数越界 → `400 VALIDATION_ERROR`；限流 → `429 RATE_LIMITED{retry_after_s}`。**不返回** `409 DATA_LICENCE_UNAVAILABLE`。弱 ETag 与 §1 相同。

#### §7.3 `/today` 补充（v0.2.7，在原响应结构上新增字段）

新增顶层字段（都必须出现）：
```
alerts: {items: TodayAlert[], more: boolean},
plan_triggers: {items: TodayPlanTrigger[], more: boolean},
data_gaps: {items: TodayDataGap[], more: boolean},
evidence: Evidence[]
```
`risk_flags.items[]` 加 `risk_event_id: uuid | null`。

**`TodayAlert`**（plan 能力 4“提醒”；来源：`alerts` 表）
`{id: uuid, rule_id: uuid, origin: alert_origin, severity: severity, status: alert_status, security_code: string | null, name: string | null, title: string, triggered_at: string(datetime), data_as_of: string(datetime) | null, affected_plans: [{plan_id: uuid, plan_version_no: int, condition_id: uuid | null}], evidence_ids: string[]}`
- 范围：`status ∈ {new, read}` 的提醒（未处理的一直显示，不限日期）；**不含** `origin=plan_condition` 的提醒，这类放进 `plan_triggers`，避免重复。
- `title`：“发生了什么”的事实陈述（例如“示例银行发布业绩预告”），经过禁用词校验，不包含动作建议。`security_code` 为 `null` 时 `name` 也为 `null`（账户级提醒）。
- `evidence_ids` 非空，每个 id 都能在同一响应的 `evidence[]` 中找到（提醒的“事实 + 来源”）。
- 排序：`severity`（important > attention > info）→ `triggered_at` 降序 → `id`。最多 50 条，`more=true` 时到 `/alerts?status=new,read` 查看。

**`TodayPlanTrigger`**（plan “计划触发”；来源：`plan_conditions` 的满足记录，即 SSE `plan_triggered` 与 `origin=plan_condition` 的提醒）
`{plan_id: uuid, plan_version_no: int, security_code: string, name: string, condition_id: uuid, condition_kind: plan_condition_kind, condition_text: string, triggered_at: string(datetime), alert_id: uuid | null, evidence_ids: string[]}`
- 范围：当前 `trade_date` 内首次满足的条件，加上计划状态仍为 `triggered`、用户还没有处理的条件。
- `condition_text` 取自 `plan_conditions.description`（用户自己写的计划条件），服务端只拼接“计划条件已满足”这类事实提示，**不下单，也不生成新的动作建议**。
- `evidence_ids` 非空，指向判定满足时所用的价格或事件数据。
- 排序：`condition_kind`（`invalidation` 优先）→ `triggered_at` 降序 → `plan_id`。最多 50 条，`more=true` 时到 `/plans?status=triggered` 查看。

**`TodayDataGap`**（plan 2.3“数据完整性面板”；来源：本人证书状态、导入与对账状态、本人证书下持仓或关注证券的数据集新鲜度）
`{key: string, reason: gap_reason, scope: data_gap_scope, dataset: string | null, message: string, security_count: int, securities: [{security_code, name}], since: string(datetime) | null, route: string | null}`
- 粒度：同一 `(reason, dataset)` 合并为一条；`securities` 最多 10 个（按持仓权重降序），全部数量见 `security_count`；`scope` 为 `user`/`account`/`market` 时 `securities` 为 `[]`、`security_count` 为 0。
- 收录哪些：`data_licence_unavailable`、`user_input_missing`（如未录入现金、未导入交割单）、`upstream_error`、`quota_deferred`；只收录**会影响用户当日结论**、并且可以处理或等待恢复的缺口。产品层面的固定缺口（`no_source`，例如北向资金不可得）和按时会发布的数据（`not_yet_published`）不收录。
- `message` 说明影响了什么（例如“未录入现金余额，无法计算总仓位比例”）；`route` 是处理入口（如 `/settings/data-licence`、`/portfolio/import`），没有时为 `null`。
- 排序：`reason`（`data_licence_unavailable` > `user_input_missing` > `upstream_error` > `quota_deferred`）→ 受影响持仓的权重合计降序 → `key`。最多 50 条（合并后实际很少超过）；`more` 恒为 `false`，没有单独的列表页。

**“查看全部”去向（`more=true` 时，v0.2.7 写明）**

| 列表 | 前端路由 | 接口 |
|---|---|---|
| `focus` | `/terminal` | `GET /terminal` |
| `pending_plan_drafts` | `/plan-drafts?status=pending,stale` | `GET /plan-drafts?status=pending,stale` |
| `released_reasons` | `/candidate-signals?tab=released` | `GET /non-executable-reasons?status=released&released_since={trade_date}T00:00:00+08:00` |
<redacted:sensitive-value-or-command>
| `invalidations_today` | `/suggestions?status=invalidated` | `GET /suggestions?status=invalidated` |
| `alerts` | `/alerts` | `GET /alerts?status=new,read` |
| `plan_triggers` | `/plans?status=triggered` | `GET /plans?status=triggered` |
| `data_gaps` | 无（`more` 恒为 false） | — |

### 2.8 §7.4 策略库（替换 `/strategies` 列表行，补充版本详情）

| GET | `/strategies` 🔒 | `?horizon=&lifecycle=&security_code=&risk_level=`（v0.2.7 加 `risk_level`），§1.2 分页 → 元素 `{id, key, name, horizons, risk_level: card_risk_level, current_version: {id, version_no, lifecycle}, health: {state, weight, n}}`。`risk_level` 取当前版本关联的 L1 卡片版本的值；未关联卡片时为 `normal`；派生版本继承母版本的值（v0.2.7） |

`/strategies/{id}/versions/{vid}` 同样加 `risk_level: card_risk_level`（取该版本自身关联的卡片版本）。

### 2.9 §7.5 策略实例（替换 `/strategy-instances*` 各行）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/strategy-instances` 🔒 | v0.2.7。`?status=`（可多值，默认 `proposed,active,paused`；要包含已归档需显式传 `archived`）`&strategy_id=&strategy_version_id=&horizon=&scope=&account_id=&security_code=&origin=&risk_level=&order=`（`instance_sort`，默认 `created_at_desc`；同值时按 `id` 同向排序），§1.2 游标分页 → `Paged<StrategyInstance>`。游标与本次的筛选或排序不一致 → `400 INVALID_CURSOR` |
| POST | `/strategy-instances` 🔒 | 不变：→ `201 {id, status:"active", derived_strategy_version_id, warnings}`（`origin="user"`），支持 `Idempotency-Key` |
| GET | `/strategy-instances/{id}` 🔒 | `StrategyInstance`；他人或不存在的 → `404 NOT_FOUND` |
| PATCH | `/strategy-instances/{id}` 🔒 | 不变；archived → `409 IMMUTABLE_RESOURCE` |
| POST | `/strategy-instances/{id}/confirm` · `/pause` · `/resume` · `/archive` 🔒 | 见 §6.0A：→ `200 StrategyInstance`；目标态即当前态时返回 200（幂等）；非法 → `409 INVALID_STATE_TRANSITION{from, to, allowed}`；版本不可运行 → `409 STRATEGY_VERSION_NOT_RUNNABLE{lifecycle}` |
| GET | `/strategy-instances/{id}/events` 🔒 | §1.2 分页，`at desc, id desc` → 元素 `{id, kind: instance_event_kind, from_status: instance_status \| null, to_status: instance_status \| null, actor: "user" \| "system", reason_code: reason_code \| null, note: string \| null, detail: object \| null, at: string(datetime)}`。`created` 的 `from_status` 为 `null`；`params_changed` 两个状态都为 `null`，`detail` 中给出 `{derived_strategy_version_id}` |
<redacted:sensitive-value-or-command>

### 2.10 §7.6 / §7.7 两句补充（对应 T-F17、T-F18，原句见第 7 节 ③）

- `GET /candidate-signals` 行末追加：“列表元素即完整的 `CandidateSignal`（与详情相同，P1 校验同样适用），§1.2 分页；‘自动重评状态’由该信号 `reason_ids` 对应的 `/non-executable-reasons` 的 `status`、`released_at`、`released_by` 表示，信号本身的 `state` 随之在 `blocked`/`released` 之间变化（v0.2.7）。”
- `GET /non-executable-reasons` 行加参数：“`released_since=`（datetime，只返回 `released_at ≥ released_since` 的原因，排序 `released_at desc, id desc`；v0.2.7）”。
- `GET /plan-drafts` 行末追加：“列表 `?status=`（可多值，默认全部）`&security_code=&signal_id=`，§1.2 分页（`created_at desc, id desc`）；`PlanDraft` 加 `created_at: string(datetime)`。`stale` 或 `expired` 的草案不能修改；‘重新生成’就是用原草案的 `signal_ids` 再调 `POST /plan-drafts`，生成一份新草案，原草案保持不变，两者之间不建关联（v0.2.7）。”

### 2.11 §7.10 `/meta/enums`

`"version": "v0.2.7"`；`enums` 按 §2.2 扩充；`error_codes` 不变。

---

## 3. 验收项（粘到 §9，标题“v0.2.7 验收”）

1. `/meta/enums.version == "v0.2.7"`；`enums` 的键集合等于 §3 表名集合（包括新增的 18 个枚举与 `data_provider.exchange`）。
2. `/strategies` 每个元素都有 `risk_level ∈ card_risk_level`；`?risk_level=high` 只返回 high；未关联卡片的模板为 `normal`；派生版本与母版本一致。
3. `GET /strategy-instances`：默认不含 `archived`；`?status=archived` 只返回 archived；各 `order` 下翻页不重复、不遗漏（插入并发数据后再翻页）；改变筛选后沿用旧游标 → `400 INVALID_CURSOR`。
4. 状态机：对 4 种状态 × 4 种操作的 16 种组合，结果全部符合 §6.0A（200 转换 / 200 幂等 / 409 + `allowed` 正确）；幂等的空操作不写事件、不改 `updated_at`；`origin=system` 的实例 archive → 409 且 `allowed` 不含 `archived`；对同一实例并发 10 次 pause，只产生 1 条 `paused` 事件。
5. 系统暂停 → 用户 resume：`paused_by`、`pause_reason_code`、`paused_until` 全部清空，事件 `actor="user"`，`detail.released_reason_code="LOSS_STREAK_PAUSE"`；用户暂停的实例到期后不会被系统恢复。
6. 搜索：夹具中 `600000`、`600000.SH`、`SH600000`、`示例银行`、`SLYH`（拼音首字母）、曾用名、北交所旧代码各自命中，`match_kind` 正确；排序符合层级与平手规则（固定夹具做快照测试）；`limit=51` → 400；默认不含 `delisted` 和 `index`。
7. **pg_trgm 中文可用**：迁移中执行 `CREATE EXTENSION IF NOT EXISTS pg_trgm`；部署检查 `SELECT show_trgm('贵州茅台')` 返回非空数组。数据库为 C locale 而返回空数组时，模糊匹配回退为 `ILIKE '%q%'`，并在启动日志告警。
8. `/securities?q=` 别名返回 `[{security_code, name}]`、最多 20 条，前 20 条与 `/securities/search` 的结果一致。
9. 个股读接口：本人证书不可用时返回 `200`，`data_status ∈ {stale, unavailable, partial}`，带 `data_licence_unavailable` gap，**从不返回** 409；用户 A 的证书取到的数据不会出现在用户 B 的响应里（两个用户、两张证书的夹具）。
10. `SecurityProfile`：证书不可用时主数据字段仍然齐全，`data_status="partial"`；北交所旧代码 → `404` 且 `details.superseded_by` 为新代码。
11. 财务：`limit=41` → 400；`as_of` 早于某期的 `available_from` 时不返回该期；指数返回空 `items` + `no_source`。
12. 公告：任何 `url` 都是 https 且主机在白名单内；响应中没有正文或摘要字段；`disclaimer` 与固定文案逐字一致。
13. 周 K：用固定日线夹具（含节假日周、整周停牌周、`sf=1` 占位行、盘中当日 bar）验证 `t`、OHLC、`pre_close`、`is_final`、整周停牌不出 bar；`qfq` 周 K 的 `close` 等于同一请求下 `qfq` 日 K 在 `t` 日的 `close`。
<redacted:sensitive-value-or-command>
15. 禁用词：`alerts[].title`、`plan_triggers[].condition_text` 的服务端拼接部分、`data_gaps[].message`、`SectorFlow`、`Announcement.disclaimer` 都通过合规禁用词校验。

---

## 4. 未决问题

| # | 问题 | 草案的暂定做法 | 需要谁定 |
|---|---|---|---|
| Q1 | plan 2.1B 写“证券列表、交易日历等参考数据也按证书各取一份”，本草案把**交易所主数据**作为全站一份（它不是麦蕊数据，不受麦蕊证书约束） | 交易所主数据全站一份（`provider=exchange`）；麦蕊来源的行业、概念、股本、代码集按证书各取一份 | 用户 / 架构师（同步改 plan 2.1B、4.4） |
| Q2 | 交易所公开证券列表能否展示、能否再分发（T007 §4） | 只展示代码、简称、上市日期、状态，加 `attribution` 注明来源 | 用户（合规） |
| Q3 | ETF、可转债是否纳入 `security_type` 和搜索 | 暂不纳入 | 架构师 + 研究员 |
| Q4 | 因子的行业内分位：麦蕊没有直接提供，自行计算需要定义行业口径和最小样本数 | 不提供，只给全市场排名 | 研究员 |
| Q5 | 实例归档时，其已开放的候选信号如何处理（继续有效直到过期，还是置为 `invalidated`） | 暂不变更状态，信号自然过期 | 架构师 + 研究员 |
| Q6 | 搜索默认是否包含指数 | 不包含，需要时传 `types=` | 前端 + 产品 |
| Q7 | 实例数量是否受权益上限约束（`ENTITLEMENT_LIMIT_REACHED`） | 本版不加；如需加，confirm/resume 时检查 | 架构师（2.9 权益） |
| Q8 | 复权 `f` 与 `fr` 的区别、前复权基准日如何取得 | 先按 `f` 实现，`adjust_as_of` 来源待补测 | T003 补测 |
| Q9 | `/alerts`、`/plans` 的完整结构仍未定义（T-F06/T-F07 卡在这里）；`/today` 的“查看全部”指向这两个页面，但页面还不能做 | `TodayAlert`、`TodayPlanTrigger` 先作为这两个接口元素的子集，结构定义时必须兼容 | 架构师（下一轮 T-A09） |
| Q10 | 板块资金的 `industry` 用哪套行业分类；分档阈值、因子单位等 | 标【待 T003 补测】 | T003 补测 |

---

## 5. 与前端 mock 的分歧（b79ce80 / 5f8b5e0 / 8405877）

| # | 位置 | 前端现状 | 契约草案 | 建议谁改 | 理由 |
|---|---|---|---|---|---|
| 1 | `marketTypes.ts` `SecurityHit` / 搜索 | 用 `GET /securities?q=`，只有 `{security_code, name}` | 新端点 `/securities/search` + `SecurityHit` 扩展字段；旧端点保留 | 前端（不急，别名保留） | 新字段是增量，旧调用仍然可用 |
| 2 | `SecurityProfile.status` | `listed \| suspended \| delisted` | `listing_status` 为 `listed/delisting_period/delisted/missing_from_list`；停牌单独用 `suspended: boolean \| null` | 前端 | 停牌不是上市状态；退市整理期需要单独展示 |
| 3 | `SecurityProfile.risk_warning: boolean` | 布尔值 | `risk_flag: security_risk_flag \| null`（区分 ST、*ST、退） | 前端 | 三种标记的风险含义不同 |
| 4 | `SecurityProfile.industry: string \| null`、`concepts: string[]` | 字符串 | `{taxonomy, code, name} \| null`、`[{code, name}]` | 前端 | 需要分类口径和代码，才能和板块资金关联 |
| 5 | `SecurityProfile.board` 不可为 null | `Board` | `board \| null`（指数为 null） | 前端 | 指数没有板块 |
| 6 | `SecurityProfile` 缺少字段 | 无 `full_name`、`type`、`list_date_basis`、`delist_date`、`former_names`、`code_history`、`master_as_of`、`attribution`、`sources` | 有 | 前端（新增展示，`attribution` 必须展示） | 来源说明是 T007 的展示要求 |
| 7 | `FinancialPeriod` | 无 `report_period`、`available_from`、`is_restated`、`deducted_net_profit`、`bvps` | 有 | 前端 | 增量字段 |
| 8 | `FundFlowDay` 分档净额 | `Decimal`（不可为 null） | `string(decimal) \| null`；另有 `amount`、`is_final` | 前端 | 麦蕊个别日期分档缺失 |
| 9 | `FactorValue.group` + 6 个分组 | `value/quality/growth/momentum/volatility/liquidity` | `category: factor_category`（麦蕊的 11 类） | 前端 | 6 个分组是前端自拟的，与数据源不符 |
| 10 | `FactorValue.pct_rank_market`（0–100 分位）、`pct_rank_industry` | 有 | `market_rank` + `market_rank_pct`；**没有行业分位** | 前端 | 数据源只有全市场排名（Q4） |
| 11 | `FactorsResponse.calc_version` | `calc_version` | `factor_set_version` + `counts` | 前端 | 与 `feature_set_version` 命名一致 |
| 12 | `Announcement.category: string \| null` | 自由文本 | `category: announcement_category` + `category_raw`、`level_raw`、`url_host`、`file_format`、`first_seen_at`；响应带 `disclaimer` | 前端 | 枚举要可校验；`disclaimer` 需要展示 |
| 13 | `SectorFlow.sector_id` | `sector_id` | `sector_code`；另有 `amount`；响应带 `taxonomy` | 前端 | 与 `industry.code` 命名一致 |
| 14 | 板块资金 60 秒轮询 | 轮询 | 盘后每日一次，弱 ETag | 前端 | 盘中没有新数据 |
| 15 | 周 K mock（`toWeekly`） | `t` 为该周最后一根日 K、第一根 `pre_close=null`、无 `is_final` | 第一根取首日日线的 `pre_close`；有 `is_final`；整周停牌不出 bar | 前端（mock） | `t` 的口径一致，其余是细节 |
| 16 | bars 响应 | 无 `adjust_as_of` | 有 | 前端 | 基准日变化时需要整段重载 |
| 17 | `/quotes` 的 `codes` 上限 | 200 | 契约 v0.2.6 已是 200 | **无分歧** | — |
| 18 | `strategyTypes.ts` `StrategyInstance` | 最小字段 | 完整结构（§5.1） | 前端 | 契约补齐后替换 |
| 19 | `strategyTypes.ts` 列表 `risk_level?` 可选 | 可选 | 必有 | 前端 | v0.2.7 起必有 |
| 20 | `strategyHandlers.ts` 状态转换 | 目标态即当前态返回 409；409 只带 `{from, to}`；archive 不检查 `origin` | 幂等返回 200；409 带 `allowed`；`origin=system` 不能归档 | 前端（mock） | 按 §6.0A |
| 21 | `strategyHandlers.ts` 列表 | 只排除 archived，无筛选和排序 | 筛选、排序、游标 | 前端（mock） | 增量 |
<redacted:sensitive-value-or-command>
| 23 | T-F08 `/today` 类型 | 没有 `alerts`、`plan_triggers`、`data_gaps`、`evidence`、`risk_event_id` | 新增 | 前端 | 新增字段，不破坏现有页面 |

后端目前没有任何个股接口实现，所以本次分歧不涉及后端代码。

---

## 6. plan.md 同步位置与建议文字

| 位置 | 现文（摘） | 建议改为 |
|---|---|---|
| §2.1B 第 343 行 `per_licence` 条 | “证券列表、交易日历等参考数据也按证书各取一份。” | “麦蕊来源的参考数据（麦蕊证券列表、行业与概念、交易日历）按证书各取一份；交易所公开证券列表（T007，`provider=exchange`）不是麦蕊数据，全站一份（契约 v0.2.7 §1.1，未决 Q1）。” |
<redacted:sensitive-value-or-command>
| §2.3 能力 1（第 414 行后） | — | 加一句：“‘今日关注’的提醒、计划触发、数据缺口三块的结构与排序见契约 v0.2.7 §7.3 `/today` 补充。” |
| §3.3 第 1377 行 `strategy_instances` | `origin(classifier/user)`，无 horizon | `origin(classifier/user/system)`；加 `horizon`、`paused_by(user/system, nullable)`、`pause_reason_code(nullable)`、`paused_until(nullable)`、`updated_at`、`archived_at(nullable)`；索引 `(user_id, status, created_at desc, id desc)` |
| §3.3 第 1378 行 `strategy_instance_events` | `kind, detail, actor_id, at` | 加 `from_status`、`to_status`、`actor(user/system)`、`reason_code`、`note` |
| §3.3 第 1458 行 `market.securities` | `code, name, exchange, board, list_date, status, industry_codes, updated_at` | `security_id, code, type, name, full_name, exchange, board, list_date, list_date_basis, delist_date, listing_status, name_norm, name_initials(text[]), master_as_of, updated_at`；行业与概念移到按证书的表；新增 `security_name_history`、`security_code_history`、`security_risk_flag_history`（T007 §5）；索引 `gin (name_norm gin_trgm_ops)`、`gin (name_initials)` |
| §4.4 第 2014 行 | “共享：所有行情/基本面/公告数据与用户无关，全站一份” | “按证书隔离：麦蕊来源的行情、基本面、公告按 `source_licence_id` 各存一份，每位用户只读本人证书的数据（2.1B）；只有交易所公开证券列表全站一份。用户数增长会增加外部调用（每张证书各自的被跟踪池）。” |
| §5 契约摘要第 2093 行 | “today、market、securities” | “today（含提醒、计划触发、数据缺口）、market（含 `/market/sector-flows`）、securities（`/securities/search`、资料、财务、资金流、因子、公告；周 K 口径 §6.4）” |
| §5 第 2101 行 | “L3 实例：`/strategy-instances`（CRUD、确认 `proposed`、暂停）。” | “L3 实例：`/strategy-instances`（列表筛选与分页、确认、暂停、恢复、归档，状态机见契约 §6.0A）。” |
| §6.1 配置 | — | 新增 `search.similarity_threshold: 0.3`、`search.initials_max_variants: 16`、`search.limit_default: 20`、`search.limit_max: 50`、`announcements.url_host_allowlist: [...]` |
| 任务表 T-B06（2940 行） | — | 末尾加“；`/securities/search`（pg_trgm + 拼音首字母）、`/securities/{code}`、周 K 聚合（契约 v0.2.7）” |
| 任务表 T-B07（2941 行） | — | 末尾加“；`/securities/{code}/financials` `/fund-flows` `/factors` `/announcements`、`/market/sector-flows`（契约 v0.2.7）” |
| 任务表 T-B13（2996 行） | “今日关注 `/today` 聚合” | “……聚合（含 v0.2.7 的 alerts、plan_triggers、data_gaps、evidence）” |
| 任务表 T-B20（2961 行） | — | 加“`/strategies` 的 `risk_level` 与筛选（v0.2.7）” |
| 任务表 T-B32（3032 行） | — | 加“列表筛选与分页、§6.0A 状态机与幂等、`/events` 结构（v0.2.7）” |
| 任务表 T-F03（2950 行） | — | 加“按契约 v0.2.7 调整 mock 类型（T-A08 分歧表 1–17）” |
| 任务表 T-F19（3047 行） | — | 加“按契约 v0.2.7 §6.0A 显示可用操作” |
| 任务表 T-F22（3056 行） | — | 加“`risk_level` 改为读 `/strategies` 列表字段” |

---

## 7. 追加四项

### ① T-F08 “查看全部”的去向核对

| 前端暂定 | plan 2.4（第 459 行） | 契约接口 | 结论 |
|---|---|---|---|
| `released_reasons` → `/candidate-signals` | **只有** `/candidate-signals/:id`（详情页），**没有**列表页；前端 `routes.tsx` 有占位 `candidate-signals`（候选信号列表） | `GET /candidate-signals` 存在（§7.6，列出的是信号），但“今日解除的原因”是**原因**，对应的是 `GET /non-executable-reasons?status=released`，而该接口没有按解除时间筛选的参数 | **建议改为 `/candidate-signals?tab=released`**：plan 2.4 补上 `/candidate-signals` 列表页（含“今日解除”页签）；契约给 `/non-executable-reasons` 加 `released_since`。理由：直接跳到信号列表看不出哪些原因是今天解除的 |
<redacted:sensitive-value-or-command>
| `pending_plan_drafts` → `/plan-drafts`（顺带核对） | plan 只有 `/plan-drafts/:id`；前端有占位 | `GET /plan-drafts` 存在，但列表参数未写 | 建议 `/plan-drafts?status=pending,stale`；plan 补列表页；契约补 `?status=`（同 ③ T-F18） |
| `invalidations_today` → `/suggestions`（顺带核对） | plan 只有 `/suggestions/:id`；前端已实现 `SuggestionIndex` | `GET /suggestions?status=` 存在 | 建议 `/suggestions?status=invalidated`；plan 补列表页 |
| `focus` → `/terminal` | 存在 | `GET /terminal` 存在 | 确认 |

### ② `/today` 补充“提醒、计划触发、数据缺口”三块

字段定义见 §2.7 “§7.3 `/today` 补充”，要点：
- `alerts: {items: TodayAlert[], more}`：来源为 `alerts` 表中未处理（`new`/`read`）的提醒，不含计划条件类（避免与计划触发重复）；`evidence_ids` 非空；按严重度、时间排序；最多 50 条；查看全部去 `/alerts`。
- `plan_triggers: {items: TodayPlanTrigger[], more}`：来源为当日满足、以及仍未处理的计划条件；失效条件优先；不下单、不产生新的动作建议；最多 50 条；查看全部去 `/plans?status=triggered`。
- `data_gaps: {items: TodayDataGap[], more}`：按 `(reason, dataset)` 合并；只收可处理或可恢复的缺口（证书、用户输入、上游错误、配额）；带处理入口 `route`；`more` 恒为 false。
- 新增顶层 `evidence: Evidence[]`，供前两块的 `evidence_ids` 引用。
- 前端参考：8405877 的 T-F08 **没有用到这三块的任何字段**（`T-F08.md` 遗留问题 2 已写明“本任务没有做，也没有自定结构”），所以字段完全按 plan 2.3、3.3（`alerts`、`plan_conditions`、`alert_rules` 表）和能力 4 的“三段式”定义，没有需要对齐的前端字段。
- 依赖：`/alerts`、`/plans` 的完整结构仍未定（未决 Q9），这两块的 `more` 落地页要等 T-F06/T-F07。

### ③ `frontend-backlog.md` 中 T-F17、T-F18 各补一句

backlog 里说的“各差一句说明”，指的是**契约里**缺的那一句，所以需要补两处：契约的原句（本草案 §2.10，随 v0.2.7 写入契约），以及 backlog 表格的状态更新。

**契约原句（位置：`docs/api-contract.md` §7.6 第 625 行 `GET /candidate-signals` 行的“说明”列末尾）**：
> 列表元素即完整的 `CandidateSignal`（与详情相同，P1 校验同样适用），§1.2 分页；“自动重评状态”由该信号 `reason_ids` 对应的 `/non-executable-reasons` 的 `status`、`released_at`、`released_by` 表示，信号本身的 `state` 随之在 `blocked`/`released` 之间变化（v0.2.7）。

**契约原句（位置：§7.7 第 657 行 `GET /plan-drafts` 行的“说明”列末尾）**：
> 列表 `?status=`（可多值，默认全部）`&security_code=&signal_id=`，§1.2 分页（`created_at desc, id desc`）；`PlanDraft` 加 `created_at: string(datetime)`。`stale` 或 `expired` 的草案不能修改；“重新生成”就是用原草案的 `signal_ids` 再调 `POST /plan-drafts`，生成一份新草案，原草案保持不变，两者之间不建关联（v0.2.7）。

**backlog 原句（位置：`/workspace/team/reports/frontend-backlog.md` 第 24 行 T-F17 行“缺什么”列末尾，追加）**：
> 已由 T-A08（契约 v0.2.7 §7.6）补齐：列表元素即完整 `CandidateSignal`；“自动重评状态” = 原因的 `status` + `released_at` + `released_by`。

**backlog 原句（位置：第 25 行 T-F18 行“缺什么”列末尾，追加）**：
> 已由 T-A08（契约 v0.2.7 §7.7）补齐：`GET /plan-drafts?status=&security_code=&signal_id=`；`stale` 后重新生成 = 用原 `signal_ids` 再 `POST /plan-drafts`。

（契约 v0.2.7 合入后，两行的“契约齐全？”列可以从“⚠️ 基本齐全”改成“✅”，第 33 行结论里的“（各差一句说明）”可以删掉。）

### ④ README 第 14 行

现文：
> - 本地默认叠加 `deploy/compose/docker-compose.dev.yml`：**麦蕊回放模式**（`MAIRUI_MODE=replay`，`ingest` 中 licence 强制为空）。

依据 T-O09（6908fc5）：compose 已完全不传全站证书变量，dev overlay 中强制置空的写法已删除；bc0b3d8 之后 ingest 发现该变量非空会拒绝启动；证书改为每位用户在“设置 → 数据证书”中录入，以 HPKE 密文入库，封装密钥以 docker secret 交付。

建议新行：
> - 本地默认叠加 `deploy/compose/docker-compose.dev.yml`：**麦蕊回放模式**（`MAIRUI_MODE=replay`，不调用麦蕊）。部署配置不再有全站麦蕊证书变量；`ingest` 发现 `MAIRUI_LICENCE` 非空会拒绝启动。证书由每位用户在“设置 → 数据证书”中录入，加密后入库（plan §2.1B，契约 v0.2.6）。

附带提示（不在第 14 行，供父代理判断）：第 15 行“`MAIRUI_LICENCE` 只注入 `ingest` 容器（plan §2.1A）”也已过时，与 T-O09 矛盾。建议改为：
> - 证书封装密钥以 docker secret 交付（私钥只挂 `ingest`，公钥挂 `api` 和 `ingest`），存放在仓库外的 `AIA_SECRETS_DIR`，见 `deploy/runbooks/data-licence-seal-keys.md`；任何 `.env`、证书、私钥、真实交割单都不入库（见 `.gitignore`）。
