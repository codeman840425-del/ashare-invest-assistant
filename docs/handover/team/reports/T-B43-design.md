# T-B43 设计：行业归属表与停牌数据（后端，T-B49 第 7 项）

- 依据：plan 2.1B（`per_licence`）、plan 数据来源表“申万一级行业归属 / 停牌”两行、T-O11 裁定第 4 节（RC4 行业、停牌）、feature_spec v1.0.1（`f.sw_l1`、G-01 停牌）。
- 结论先行：**本次不加迁移**。上游字段（一级行业代码格式、`sf` 取值、`/hitc/jrts` 的 `tp` 结构）都还是【待核实，T-B05】；`market.*` 的 `source_licence_id` 约定要到 T-B04a 才落地（目前 market 下没有任何表带这一列）。现在建表只会是空表，T-B05 实测后多半还要改。迁移随 T-B43 实现一起提交，编号排在当时的 head 之后。
- 在此之前：RC4 一律出 gap `fit_assessment.sector / no_source`（T-B49 已实现）；停牌照旧出 `counter_evidence.suspension / not_yet_published`（T-B10 已有）。

## 1. 行业归属（RC4、`f.sw_l1`、`rank_pct_in`）

数据来源（ingest 采集，周更）：主源 `/hszg/list`（行业树，周六 03:05）+ `/hszg/zg/{code}`（个股所属指数/行业/概念，周六 11:00）；备选 `/hslt/primarylist`、`/hslt/sectors`。

### 1.1 `market.industry_nodes`：行业树（按证书）

| 列 | 类型 | 说明 |
|---|---|---|
| source_licence_id | uuid NOT NULL | FK `app.user_data_licences.id`（2.1B；删除证书/账号时随删除 CLI 清理） |
| taxonomy | text NOT NULL | CHECK ∈ {`sw`, `concept`}；以后加别的分类体系只加枚举值 |
| code | text NOT NULL | 上游行业/概念代码，原样保存（格式【待核实】，不做转换） |
| level | smallint | 申万 1–3；概念为 NULL；CHECK `taxonomy <> 'sw' OR level BETWEEN 1 AND 3` |
| name | text NOT NULL | |
| parent_code | text | 申万二/三级指向上一级；一级与概念为 NULL |
| valid_from | date NOT NULL | 首次在行业树中看到的交易日 |
| valid_to | date | 最后一次看到后的下一个采集日；仍有效时为 NULL |
| raw_payload_id | uuid | FK `market.raw_payloads.id`（可追溯） |
| fetched_at | timestamptz NOT NULL | |

主键 `(source_licence_id, taxonomy, code, valid_from)`；部分唯一索引 `(source_licence_id, taxonomy, code) WHERE valid_to IS NULL`（同一节点同一时刻只有一个有效版本）。

### 1.2 `market.security_industries`：证券 → 行业/概念（按证书，区间表）

| 列 | 类型 | 说明 |
|---|---|---|
| source_licence_id | uuid NOT NULL | 同上 |
| security_code | text NOT NULL | `600000.SH` 形式，FK `market.securities.code` |
| taxonomy | text NOT NULL | `sw` / `concept` |
| level | smallint | 申万 1–3；概念 NULL |
| node_code | text NOT NULL | 对应 `industry_nodes.code` |
| node_name | text NOT NULL | 采集时的名称（改名不回写历史） |
| valid_from | date NOT NULL | 本次归属首次被观察到的采集日 |
| valid_to | date | 归属变化或消失时填，开区间 |
| first_seen_at | timestamptz NOT NULL | 计算“可得时点”用 |
| raw_payload_id | uuid | |

- 主键 `(source_licence_id, security_code, taxonomy, node_code, valid_from)`。
- 申万每级只能有一个当前归属：部分唯一索引 `(source_licence_id, security_code, level) WHERE taxonomy = 'sw' AND valid_to IS NULL`；概念可多个。
- 读取索引 `(source_licence_id, taxonomy, level, node_code) WHERE valid_to IS NULL`（RC4 求同行业持仓、`rank_pct_in` 分组）。
- 写法：每周全量对比。没变化 → 不写；变化 → 旧行填 `valid_to`、插新行。**不覆盖历史**，回测按时点取值。
- 时点规则（与 feature_spec 一致）：`f.sw_l1` 在 D 日可用 ⇔ 存在 `valid_from ≤ D < coalesce(valid_to, ∞)` 且 `first_seen_at` 规整后（盘后 → 次一交易日开盘）≤ D 09:30。
- 不放进 `market.securities`：那张表只存全站一份的公开主数据（问题 51），行业属于按证书取的数据。

### 1.3 消费方

- **RC4**（研究候选 `fit_assessment`、风控）：用当前用户证书的数据。本人持仓 ∪ 候选证券按 `sw` 一级分组，算占比后与 `rc4_sector_concentration.sw_l1_max_pct` 比较；概念按 `concept_max_pct`。任何一只缺归属 → 该项照旧出 gap（`no_source` 或 `data_licence_unavailable`），不当作“不集中”。
- **`f.sw_l1`**：T-B43 在 `feature_catalog` 登记（`declared` 起步），值取 `node_code`。
- **删除用户数据 CLI**：`_market_licence_tables()` 自动发现带 `source_licence_id` 的 market 表，不用改代码。**运维**需要给 `aia_maint` 授这两张表的 SELECT/DELETE，给 ingest 角色授 INSERT/UPDATE。

## 2. 停牌

数据来源：主源日 K 的 `sf`（1 停牌 / 0 不停牌），随日 K 采集；补充源 `/hitc/jrts` 的 `tp`（今日停牌列表，每日 15:40）。

**选定方案：日 K 行上的停牌标记为准，`market_events` 只补“当天还没有日 K”的空档。**

- `market.daily_bars` 新增 `suspended boolean NULL`。NULL 表示上游没给或没核实，**不能**当成 false。只按 `sf` 写入，`sf` 以外的值写 NULL 并记采集告警。不新建表；按证书隔离随 T-B04a 给 `daily_bars` 加 `source_licence_id` 一起处理。
- `market.market_events` 用 `type = 'suspension'`（type 列目前没有 CHECK，不用改约束），`event_date` = 停牌日，`source = 'rule'`，`payload = {"origin": "jrts", "reason": <tp 原文>}`，同样带 `source_licence_id`。只用于盘中和当日日 K 入库前。
- 判定函数 `is_suspended(code, D)`：
  1. 当日日 K 存在且 `suspended` 非空 → 取它；
  2. 否则有 `jrts` 事件 → true；
  3. 否则 → **未知**：研究候选出 `counter_evidence.suspension` gap，分类器/G-01 进 `inputs_missing`。

  日 K 与 jrts 冲突时以日 K 为准，并记采集告警（`ingest_request_log`）。
- 伪停牌交叉校验（plan 2.5.11A ②，T-B05a）：`suspended = true` 但同日快照有成交 → 标 `suspect`。放在 T-B05a，不在本设计范围。
- 不选“只用 market_events”的原因：日 K 每天每只都有一行，放在行上不用额外 join，也能区分“没停牌”和“不知道”；事件表适合低频、有原文的事件。

## 3. 迁移计划（T-B43 实现时，不在 T-B49）

1. `CREATE TABLE market.industry_nodes`、`market.security_industries`（含上面的 CHECK 和索引）。
2. `ALTER TABLE market.daily_bars ADD COLUMN suspended boolean`（daily_bars 已分区就对父表加，可空，不回填）。
3. 迁移前预检查：无（都是新表或可空新列）。
4. 授权：运维在 grants.sql 加 ingest 写、api 读、aia_maint 读/删。

## 4. 待核实（T-B05，需要麦蕊，本次不做）

- `/hszg/zg/{code}` 返回里申万一级/二级/三级怎么区分、代码格式；
- `sf` 的取值范围（是否只有 0/1，停牌日是否还返回日 K 行）；
- `/hitc/jrts` 的 `tp` 结构与覆盖范围（是否含北交所）。
