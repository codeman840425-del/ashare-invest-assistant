# A股个人投资研究与决策助手 · REST 接口契约（MVP v1）

- 作者：架构师；日期：2026-11-02；版本：**v0.2.9**；状态：**已评审修订（T-A01，2026-11-01；v0.2.1 同日小修；v0.2.2 为 T-A02 合入研究员 T006a；v0.2.3 为 T-A03 处理前端 T-F01 遗留 21 条并同步研究员 T006b；v0.2.4 为 T-A05 合入研究员 T-B15 合规文书与问卷、前端 T-F02 评审 D1–D7；v0.2.5 为 T-A06 按用户 2026-11-02 决定删除同意流程与风险测评；v0.2.6 为 T-A07 每用户自用麦蕊证书并入 T006e 裁定；v0.2.7 为 T-A08 补齐个股数据接口、策略实例列表与状态机、周 K 口径与 `/today` 三块；v0.2.8 为 T-A09 按证书拆分 `/admin/ingest/status`、ETF 纳入、注册蜜罐字段、管理员暂停期间的证书 PUT 规则、`/admin/*` 不进 openapi；v0.2.9 为 T-A10 处理前端 T-A09/T-F17/T-F18 遗留待定项与测试 T-T23 的三项裁定，同版并入 T-A11 研究候选接口与 T-F22 管理端证书遗留裁定）；本契约是唯一事实来源**——plan.md、原型、后端 schema、测试夹具与本文不一致时，以本文为准并修改对方
- 配套：[`plan.md`](./plan.md)（架构方案）。本契约优先于代码：FastAPI 生成的 `openapi.json` 与本文不一致时**改代码**。例外：`/admin/*` 不进 `openapi.json`（v0.2.8，§1.3），其结构以本文为准、由契约测试验证。
- **示例值全部虚构**：代码用 `600000.SH / 000001.SZ`，ID 用 `00000000-0000-4000-8000-0000000000xx`，金额为随意整数；不含任何真实账户、股东代码、姓名、金额或委托/成交编号。证券简称一律用“示例银行”“演示电子”这类虚构名称。

---

## 0. 变更记录

> T-A24：Phase 2 后续接口缺口集中在 §7.11，全部标记 `status: draft`；不表示路由已实现，也不改变现有已生效接口或门禁。


### v0.2.9（2026-11-02，T-A10：处理前端 T-A09、T-F17、T-F18 与 review-fixes 遗留的待定项（报告 `T-A10-pending.md` P01–P21，按建议裁定采纳），并入测试 T-T23 的三项裁定；同版并入 T-A11（研究候选接口，#19–#25，版本号不升）与管理端证书遗留裁定（T-F22 遗留 1–5，#26）；**含不兼容变更**：#6（候选信号事件改为分页包装）、#11（放弃草案的请求体）、#12（`/non-executable-reasons` 默认只返回 `active`）；其余为新增字段、可空性放宽或规则写明）
> 本版不新增产品功能：只同步已定的裁定、补齐字段语义与校验顺序。不写入任何证书值。
> T-A11 只把 plan 已有的“研究候选卡”（plan 2.4 能力 2、3.1、3.3）写成接口，不加 plan 之外的功能；需要产品决定的按最保守的默认值执行，登记为 plan 第 9 节问题 66–71；T-F22 遗留的通知为默认执行（问题 74）。逐项裁定见 `reports/T-A11.md`。

| # | 项 | 决定 | 后端改动 | 前端改动 |
|---|---|---|---|---|
| 1 | 可转债持仓展示（U3 / plan 第 9 节问题 63 已定，P01） | U3 改为已定：保留原代码，标注“可转债·无行情”；无行情的持仓行 `market_value`、`pnl`、`pnl_pct` 为 `null`（**不是 0**），`weight_pct` 按成本（`qty × cost_price`）估算，`total_assets` 与 `exposure` 也计入成本估算值，顶层 `data_status` 为 `partial`；不跑策略、不出信号、不进入风控止损计算（§7.2 `/portfolio`、§5.1 `TerminalRow`） | 持仓汇总按此实现（`security_types.py` 的“未定，不实现”作废） | mock 的 `pnl=0` 改为 `null`，显示“—”与“估算” |
| 2 | 持仓行类型与估值标志（P02） | `/portfolio` 的 `positions[]` 与 `TerminalRow.holding` 加 `security_type: security_type \| null`（`null` = 不在证券主数据中，本版主要是可转债）与 `estimated: boolean`（`true` = 无行情、`weight_pct` 按成本估算）；**不新增**可转债枚举值 | 新增字段 | 计算与展示逻辑改读这两个字段；代码前缀只用于“可转债”文案 |
| 3 | `TerminalRow.holding` 可空性（P01） | `pnl`、`pnl_pct` 改为 `string(decimal) \| null`（无行情时为 `null`） | 同步 | 类型改为可空 |
| 4 | ETF 成交量单位（P03） | 不改字段：本版 ETF 与股票一样按“手”显示（1 手 = 100 份）；`volume` 原始单位仍【待 T003/T-B05】（v0.2.3 补充 #8），定后只改说明 | 无 | 无 |
| 5 | 管理端证书列表与暂停/恢复（P04–P06） | 契约不改：v0.2.6 #3 与 §7.9 已要求“管理端证书列表（只有状态）”与 pause/resume（`reason` 必填）；列表不显示证书值或任何片段；有该页后 `licences_truncated` 的提示改为链接，`licence_id` 两页互跳仍为可选 | 无（已实现） | 补页面（d26e1d3 已提交） |
| 6 | 候选信号事件（**不兼容**，P07） | `GET /candidate-signals/{id}/events` 改为 §1.2 分页 `{items, next_cursor}`，排序 `at desc, id desc`；元素 `{id, from: candidate_signal_state \| null, to: candidate_signal_state, cause: candidate_signal_event_cause, at}`（创建时 `from` 为 `null`）；**不返回** `detail`；新增枚举 `candidate_signal_event_cause`（§3），取值与后端 `candidate_signal_events.cause` 的 CHECK 一致；确认草案（drafted→confirmed）与用户忽略都用 `user` | 接口与 `/meta/enums` 输出新枚举 | 解析 `{items}`；mock 删除 `plan_confirmed`，只用 6 个取值 |
| 7 | 列表冲突（P08） | 不加 `conflict_signal_ids`：方向冲突以 `STRATEGY_CONFLICT` 原因表示（服务端对全部信号计算），列表页用 `GET /non-executable-reasons?signal_ids=` 判断；`STRATEGY_CONFLICT` 的 `evidence` 中写明对方信号 id（§6.1） | 生成该原因时写 evidence | 改按原因码判断冲突 |
| 8 | 不可执行原因带证券（P09） | `NonExecutableReason`（列表与详情）加只读 `security_code`、`name`（服务端联查信号，与 `/today.released_reasons` 一致） | 新增字段 | 去掉按 `signal_id` 逐个取信号 |
| 9 | 名单类原因的解除（P10） | `BLOCKLISTED`、`USER_MUTED` 的 `machine_checkable=true`，只能通过删除 `/restrictions` 解除；对其调用 `POST /non-executable-reasons/{id}/release` → `409 REASON_NOT_MANUALLY_RELEASABLE` | `/release` 校验 | 不显示“手动解除”，引导到名单页（已如此） |
| 10 | 跟踪统计范围（P11，plan 第 9 节问题 14 已定） | `GET /strategies/{id}/versions/{vid}/tracking` 加 `?scope=mine\|site`，默认 `mine`；`site` 只含策略级聚合（不含任何用户或个股持仓信息），只对登录用户在策略页展示；样本不足沿用 `Stat` 标注；本版不加人数阈值 | T-B27 实现参数 | 信号详情页只看 `mine`；全站在策略页 |
| 11 | 放弃草案（**不兼容**，P15） | `POST /plan-drafts/{id}/discard` 请求体改为 `{}`，删除 `note`（`plan_drafts` 无处存放，隐私从严）；旧客户端发来的 `note` 被**忽略**，不报 400 | 忽略 `note` 键 | 去掉备注输入框与 mock 中的 note |
| 12 | `/non-executable-reasons` 的 `status`（**行为写明**，架构师裁定） | `?status=` 默认值写明为 `active`，可选 `active` `released` `all`（`all` = 不按状态过滤，含 `obsolete`）；带 `signal_ids=` 或 `suggestion_id=` 时同样默认 `active` | 默认值与 `all` | **需要展示已解除原因的地方要传 `status=all`**（如信号详情的“自动重评状态”、建议卡原因列表）；只看已解除的“今日已解除”继续用 `status=released&released_since=` |
| 13 | 多信号生成草案（P12） | `POST /plan-drafts` 的 `signal_ids` 必须全部属于本人、同一 `security_code`、同一 `proposed_action`（有 `t_leg` 时 `t_leg` 也相同），否则 `400 VALIDATION_ERROR{field:"signal_ids"}`；方向相反的信号带 `STRATEGY_CONFLICT`，按已有规则 `409 SIGNAL_NOT_EXECUTABLE{reason_ids}`；来自多个实例时 `instance_id` 为 `null`；不做跨策略合成结论（plan P4） | 校验 | mock 加同向校验 |
| 14 | 整手规则（P13） | `qty_range.lot` = 买入递增单位（主板、创业板、ETF 100；科创板 1），`qty_range.min` 不低于起买量（科创板 200）；确认时按草案 `market_rule_version_id` 校验：买入/加仓 `chosen_qty ≥ 起买量` 且符合递增单位；卖出/减仓 `chosen_qty ≤ sellable_qty`，不足一手的零股只能连同全部余量一次卖出【以交易所规则为准，研究员核对】；不满足 → `400 VALIDATION_ERROR{field:"chosen_qty", issue:"lot_rule", min_buy, step}`，**不能**用 `deviation_ack` 绕过 | 确认校验（读 `config/market_rules.yaml` `lot.*`） | 按 `details` 提示；以服务端为准 |
| 15 | 已写明、不改（P14、P16–P21） | P14 重新生成见 §7.7（不建关联；原信号已失效时按 `409 INVALID_STATE_TRANSITION`）；P16 策略名经来源信号取得；P17 `/plans/{id}` 待 `/plans` 完整结构（plan 第 9 节问题 59）；P18 按 `details.from` 区分文案；P19 只有 `pending` 能放弃（§6.0）；P20 `form_started_at` 可不传（v0.2.8 #11）；P21 非契约问题 | 无 | P18 按 `details.from` 出文案 |
| 16 | 关闭注册时的判定（T-T23 裁定 1） | `registration_mode=closed` 时，**不论请求体格式是否正确**（非法 JSON、缺字段、类型错误、未知字段都算），一律先返回 `503 REGISTRATION_CLOSED`，与“注册模式最先”的判定顺序一致；实现上不能让框架的请求体校验先于模式判断 | 模式判断前置于请求体解析 | 无 |
| 17 | 导入码同步（T-T23 裁定 2） | 确认：plan 3.5A-1 第 46 行 `IMPORT_LOT_SIZE_IRREGULAR` 已由 67d123a 与 §4.1 同步，逐行一致，不改 | 无 | 无 |
| 18 | 证书设置开关的判定顺序（T-T23 裁定 3） | 维持 67d123a：`DATA_LICENCE_SETTINGS_ENABLED=false` 时 `PUT`/`PATCH /me/data-licence` 与 `POST /me/data-licence/test` → `503 MAINTENANCE`，`GET`、`DELETE` 照常。写明顺序：`PUT`/`PATCH` 的请求体格式校验（`400 VALIDATION_ERROR`）**先于** 503；`/test` 无请求体，503 先于其他判断。与注册接口顺序不同的原因：注册是公开端点，关闭时整体不可用；证书设置是登录后的局部开关，用户已登录、请求体格式错误照常提示 | 已如此实现，补测试 | 无 |
| 19 | 研究候选接口（v0.2.9 内，T-A11；T-F23 缺口 1、2、13、16） | 新增 §7.7A：`GET/POST /candidates`、`GET /candidates/{id}`、`GET /candidates/{id}/versions`（§1.2 分页，`version_no desc`）、`GET /candidates/{id}/versions/{version_no}`、`POST /candidates/{id}/versions`（`base_version_no` 乐观锁）；做决定 = 新建带 `decision` 的版本，不单设端点；没有删除，PUT/PATCH/DELETE → `405`；列表 `?status=`（多值，默认不含 `dropped`）`&security_code=&origin=&suggestion_id=`，排序 `created_at desc, id desc`；全部标 ⚖（§1.3 列表加 `/candidates*`） | T-B10 实现 | T-F23 列表、详情、版本、决定 |
| 20 | 研究候选对象（v0.2.9 内，T-A11；缺口 3、6、8、9） | `ResearchCandidate`、`ResearchCandidateSummary`、`CandidateVersion`、`CandidateCondition(Input)`、`CandidateFact`、`FitAssessment`（§7.7A）；用户填 `thesis` 与 `conditions_to_hold`（固定 `hypothesis`，须有验证日期或验证方式）；系统在每次新建版本时生成 `reasons`、`counter_evidence`（与 `CandidateSignal.counter_evidence` 同构）、`fit_assessment`，写入快照后不刷新 | 生成逻辑与快照 | 类型与展示 |
| 21 | 状态机与决定（v0.2.9 内，T-A11；缺口 4、5、11） | §6.0 加一行：continue→`researching`、watch→`watching`、drop→`dropped`；`planned` 只由系统写入（本人创建 `candidate_id` 指向该候选的计划时；本版无入口）；`dropped`、`planned` 为终态，再建版本 → `409 INVALID_STATE_TRANSITION{allowed:[]}`；`decision_reason` 自由文本 1–200 字，`decision` 非 null 时必填；候选不能直接生成计划草案 | 同上 | 决定表单 |
| 22 | 来源、重复与证券范围（v0.2.9 内，T-A11；缺口 2、12、15） | `POST` 只收 `manual`、`from_stock`、`suggestion`；`strategy_screen` → `400 VALIDATION_ERROR{issue:"not_supported"}`（`/factor/screen` 本版不定义）；引用他人或不存在的建议 → 同一个 `400{field:"suggestion_id", issue:"not_found"}`；同一证券已有 `researching`/`watching` 候选 → `409 CONFLICT{field:"security_code", existing_id}`；ETF、指数 → `400{issue:"security_type_not_supported"}`；候选信号入口按 `from_stock` | 部分唯一索引 `(user_id, security_code) WHERE status IN ('researching','watching')` | 三种入口 |
| 23 | 隐私与删除（v0.2.9 内，T-A11；缺口 7、17） | 只返回本人数据，他人 id 一律 404；系统内容只用本人证书数据与证券公开主数据，不用他人证书补齐；版本快照写本人 `user_id`、`licence_id`；为候选生成的 claims 写本人 `user_id`（不用 `user_id=null`）；本版不开放 `/claims`；plan 7.3 删除清单补 `research_candidates`、`candidate_versions`、`claim_links`（后端 T-B16 已删） | 快照与 claims 写 `user_id` | 无 |
| 24 | 通知与 SSE（v0.2.9 内，T-A11；缺口 14） | 研究候选没有通知与 SSE 事件，`notification_target_type` 不变；前端写后自行刷新 | 无 | 写后刷新 |
| 25 | 错误码与未决（v0.2.9 内，T-A11；缺口 10） | 不新增错误码；§4 `CONFLICT` 说明补研究候选的 `existing_id`；默认执行的产品问题登记为 plan 第 9 节问题 66–71 | 同上 | 文案 |
| 26 | 管理端证书遗留（v0.2.9 内，T-F22 遗留 1–5） | ① resume 幂等：已设置证书但未被管理员暂停 → `204`，状态不变，不写审计、不写事件、不发通知（与重复暂停一致）；② `GET /admin/data-licences` 排序为用户 `created_at desc, id desc`，V1 无服务端筛选参数（`?status=`、`?q=` 留待后续版本，问题 72）；③ 暂停理由与操作人不加字段，管理员在 `GET /admin/audit-logs` 查看（该接口结构未定义，问题 73）；④ 冷却不加字段：`AdminDataLicence`（经 `DataLicenceStatus`）与 `IngestLicenceStatus` 都已有 `status` 与 `paused_until`，冷却状态从这两个字段看出；⑤ 暂停、恢复成功且状态确实变化时给该用户发 `notification_kind=data_licence` 通知，正文不含理由，幂等重复调用不发（默认执行，问题 74）。见 §7.9 | resume 不再写审计（改 be607b3）；发通知 | 无（可选：通知文案） |
| 27 | 交割单、持仓、周期评估与采集状态（v0.2.9 内，T-B46/T-B47 裁定） | ① §1.2 写明：游标不透明，schema 无法表达其有效性，伪造、过期或与筛选不一致一律 `400 INVALID_CURSOR`；② `security_code`（`/horizon-assessments` 查询参数、`/trades` 查询参数与 `TradeCreate`）加格式 pattern；`/horizon-assessments` 格式合法但推断不出市场或不在证券主数据中 → `404 NOT_FOUND`；`POST /trades` 推断不出市场仍为 `400 VALIDATION_ERROR`；③ `PATCH /me/data-licence`：`tier`、`has_quant_pro` 可省略（不改）但不可为 null，`expires_on` 可为 null（清除）；`PUT` 的 `licence` 在 OpenAPI 写明 16–64 位与字符集；④ 请求体中的 decimal 字段一律是带 pattern 的字符串（`TradeCreate.qty`、`price`、`fee_total`，`/me/profile.max_single_position_pct`），不接受 JSON 数字与空串；⑤ `POST /imports` 的 multipart 字段 `snapshot_as_of` 为空串时按 null 处理；`PUT /imports/{id}/options` 的 `encoding_override`、`parser_id` 改为内联取值；⑥ `/portfolio`：持仓行字段为 `security_type`（不是 `instrument_kind`），顶层没有 `estimated`；现价取最近一个交易日的日线收盘价，没有日线才用持仓快照参考价，两者都没有的行按成本估算（`estimated=true`）；只缺行业暴露时持仓本身的 `data_status` 不降级，缺口照常列在 `gaps`；⑦ `/trades`、`/imports` 的 `?account_id=` 不是本人账户 → `404 NOT_FOUND`（与 `/portfolio` 一致）；`POST /accounts` 的 `alias`、`broker_name` 为 1–32 字，`broker_name` 必填；⑧ `/horizon-assessments` 结果落库（`symbol_horizon_assessments`，plan 3.3 新增触发 `on_demand`），`snapshot_id` 必须是 `data_snapshots` 中真实存在的 id；⑨ `/admin/ingest/status`：`leader` 可为 null（没有未过期的租约），`freshness` 为固定数据集列表，新增 `alerts[]`（告警口径见 §7.9）。默认执行的产品问题登记为 plan 第 9 节问题 75–79 | 持仓字段改名、现价来源；horizon 落库；ingest 状态；OpenAPI 收紧 | 持仓用 `security_type`；采集状态页显示 `alerts` |
| 28 | 证书冷却记录保留期、注册请求体上限（v0.2.9 内，评审 be607b3/f72b8c7/8fd9502 裁定） | ① `DELETE /me/data-licence` 时保留的冷却记录（证书指纹与删除前的 `status`、`paused_until`）：`paused_until` 为 null（删除时没有处于冷却）的记录最多保留到删除后 24 小时；契约已规定更短期限的以更短者为准；周期任务物理删除过期记录，读取时过期记录一律视为不存在（plan 7.3）；② `POST /auth/register`：请求体超过全局上限时，由中间件先返回 `413 PAYLOAD_TOO_LARGE`。这是全局规则，即使 `registration_mode=closed` 也先于 `503 REGISTRATION_CLOSED`；#16 的“一律先返回 503”只适用于未超过请求体上限的请求。用户删除时的审计清洗、`aia_maint` 维护角色、`data_snapshots` 写入方验收只涉及后端与运维，见 plan 7.3 与 3.3，不改接口 | 冷却记录清理任务；注册接口先过请求体上限 | 无 |
| 29 | 风险标记含义与 ETF 回转（v0.2.9 内，T-O11 评审裁定） | ① §3 `security_risk_flag` 写明三个值的含义：`star_st` 才是“退市风险警示”（*ST），`delisting` 是退市整理标记；取值与优先级不变；② v0.2.8 #9：ETF 类别数据源接入前，所有 ETF 的 `sellable_qty` 一律按 T+1，删除“待研究员核对 T+0 ETF”；③ 研究候选 RC4 的行业与停牌数据来源见 plan 4.2（待核实项照标）。不改字段、不改枚举 | `content.py` 中 `delisting` 文案改为“退市整理”；ETF T+0 判定以 `t0_round_trip.data_source` 非空为前提 | 风险标记文案按 ①（`star_st` = 退市风险警示，`delisting` = 退市整理） |
| 30 | 前端待定裁定（v0.2.9 内，前端待定裁定；T-A10-frontend 待定 1–9、T-F23 待定 1–7、csrf-frontend 遗留、plan 第 9 节问题 59/72） | ① `/plans`、`/alerts` 完整结构与状态机见 §7.7B，新增枚举 `plan_status`、`plan_condition_type`（问题 59 已定）；② `/admin/data-licences` V1 不加服务端筛选，`?status=&q=` 仍被忽略（问题 72 已定）；③ 候选信号创建事件 `cause=executability_check`、→`drafted` 为 `user`；`STRATEGY_CONFLICT` 的 evidence 用保留键 `signal.conflict_signal_id`；无行业归属的持仓计入 `exposure.sector` 的“未分类”且不参与 RC4；`PlanDraft` 无 `instance_id`（删去该句）；`lot_rule` 的 `min_buy`、`step` 放进 `fields[]` 元素（修正 #14 写法）；`POST /plan-drafts` 的 `400` 先于 `409`；卖出零股规则写成公式；§7.7A 补 T-F23 待定 1–7；④ CSRF 登录前白名单只有 login、register，另加 `Origin` 校验（§1.3）；⑤ 413/404/405/401/403/503/400 判定顺序写入 §1.3；默认执行的产品取舍登记为 plan 第 9 节问题 80–86 | 实现 §7.7B、两个新枚举进 `/meta/enums`、白名单与 `Origin` 校验、判定顺序（请求体解析不得先于认证与 CSRF）、事件 cause、evidence 键、“未分类”桶、lot_rule 结构 | 计划与提醒页按 §7.7B；mock 同步（白名单、顺序、400 先于 409、lot_rule 结构）；403 CSRF_FAILED 提示刷新 |
| 31 | 持仓估算、采集告警与周期评估显示（v0.2.9 内，T-B46-47 前端待定；评审 5969886） | ① `/portfolio`：§7.2 U3 一句“其他行 `estimated=false`”与 T-B46 裁定 ② 矛盾，以裁定 ②（R6）为准：顶层没有 `estimated`，在主数据中但缺现价的行同样 `estimated=true`；任一估算行或除 `exposure.sector` 外的任一缺口使 `data_status=partial`；估算行的 `gaps` 键为 `positions.convertible_bond`/`positions.unknown_security`/`positions.price`（均 `no_source`）；不加估算原因字段（问题 87）；② `/admin/ingest/status` `alerts[]`：每个 key 最多一条、按证书聚合；固定 key/level/文案表；14 天内到期用 `licence.expiring`；`critical` 在前、同级按固定 key 顺序；级别显示“严重”/“警告”；6 个数据集的中文显示名；不新增心跳时间字段（问题 88）；③ `/horizon-assessments` 前端“数据不足”判定：该周期有 `data_missing` 封顶且没有 `gate` 封顶；整体为 `suitable=[]` 且至少一个周期“数据不足”，否则“—”（问题 89）。不改字段、不改枚举 | `/portfolio`：现价第 1 步读库内日线收盘价；`exposure.sector` 缺口不单独降 `partial`；`cash` 等按 R6 ③ 非空；`positions.price` 的 reason 改为 `no_source`。`/admin/ingest/status`：按固定表实现 `alerts[]`（含 `heartbeat`、`licence.expiring`、排序）与 6 行 `freshness` | mock 中无现金记录账户 `data_status` 改为 `partial`；`horizonDataMissing` 排除有 gate 封顶的周期；mock 告警 key 与文案改用固定表；freshness 显示中文名 |
| 32 | 契约测试例外、冷却边界、不在主数据中的持仓估值（v0.2.9 内，T-T25） | ① 证书冷却：确认 #12/#13 与 §7.1 PUT 行的 `202` 写法不变（冷却中重复 PUT 或删除后重提同一证书 → `202` 与当前状态，不投递验证）；§7.1 DELETE 行补到期边界：到期时刻 = `paused_until`（非 null）或删除时刻 + 24 小时（null），当前时间等于到期时刻即已过期，“未到期”指早于 `paused_until`；② §7.2 `/portfolio`：T-B46 裁定 ② 的现价来源只适用于在证券主数据中的行，`security_type=null` 的行即使快照中有参考价也按成本估算（`estimated=true`，`market_value`/`pnl`/`pnl_pct` 为 null），与 U3、问题 79 一致；③ §7.7 卖出零股规则标注 T-R10 已核对（plan 2.13）。不改字段、不改枚举、不改状态码；schemathesis 例外与登记表、删除 CLI 触发器自检、`symbol_horizon_assessments.trigger` 的 CHECK 只涉及测试员与后端，见 plan 8.0、7.3、3.3 | 冷却记录按半开区间判定到期并用数据库 UTC 时间；`/portfolio` 对 `security_type=null` 的行不读快照参考价；新增迁移把 `on_demand` 加入 trigger CHECK；删除 CLI 触发器白名单自检；schemathesis.toml 与例外登记表一致；R11 #9/#10 的 schema 收紧 | 无改动（`security_type=null` 行本来就显示“不在主数据·估算”、市值“—”） |
| 33 | 证券主数据同步、对账与搜索（v0.2.9 内，T-A04） | ① 主数据来源定为**交易所公开列表**（`master_source`、`ProviderRef.provider=exchange`；plan 4.6.1）；巨潮、AKShare 只用于补缺与交叉核对，不建档、不覆盖交易所值；麦蕊代码集（`/hslt/list` ∪ `/bj/list/all` ∪ `/kc/list/all`）只用于按证书对账，不新建、不删除、不改状态；`delisted` 只认交易所终止上市名单，不从简称推断；② `/securities/search` 写明：检索走词条表（plan 4.6.3）；曾用名的拼音首字母也可搜，归入 `former_name`，`matched_text` 为曾用名原文；`vendor_unknown`（麦蕊有、交易所没有）的代码进隔离区，搜不到（plan 第 9 节问题 91）；与 `/meta/enums` 的关系与错误码写明；`SecurityHit.quote_missing` 判定写明；③ §3 新增 2 个枚举 `security_reconciliation_kind`、`security_reconciliation_source`（§3 表 84 → 86 个）；④ §7.9 新增只读 `GET /admin/securities/reconciliation`；`/admin/ingest/status.alerts` 新增 5 个 `master.*` 键；⑤ `SecurityProfile`、`/securities/{code}` 的来源说明去掉【待 T-A04】；ETF 名单端点待 T-B51 补测，补测前 ETF 不建档 | 主数据表、同步、对账、词条与搜索（plan T-B51–T-B54）；`/meta/enums` 加 2 个键；管理端接口与告警键 | 管理端对账页与告警文案（T-F25）；搜索结果显示曾用名命中、`quote_missing`（T-F26） |
| 34 | 网关 414（v0.2.9 内，T-T 复测补 414） | §4 登记 `414 URI_TOO_LONG`（nginx 在路由之前返回，信封与 413 同形，`details.max_bytes`）；§1.3 判定顺序 ① 加入 414，排在 413 之前。名称与状态码与后端 6670b10 的 OpenAPI 声明一致 | `/meta/enums.error_codes` 加 `URI_TOO_LONG`（HTTP 414；后端仍不产生此码，只是登记）；OpenAPI 已在 6670b10 声明 | 414 按通用错误处理，显示 `message` |
| 35 | 放弃或失败批次的预览行（v0.2.9 内，T-live-83a031c §8 裁定） | 批次转为 `discarded` 或 `failed` 时，同一事务删除该批次的全部预览行与解析出的未提交行级数据；批次头（含 `stats`、`file_findings`）保留，用于审计与计数；原始文件按现有留存策略处理（plan 3.5 ①，不变）。`GET /imports/{batch_id}/rows` 对这两种状态返回 `200`、`items: []`、`next_cursor: null`（不新增 410）；`errors.csv` 只有表头；对 `discarded` 批次 resolve 提示 → `409 INVALID_STATE_TRANSITION`。已有残留由每小时清理任务删除（plan 3.5、T-B56） | 状态变更事务内删行；beat 每小时清理任务；`/rows`、`errors.csv`、resolve 的行为 | 放弃或失败批次不再请求逐行预览，按批次头 `stats` 显示计数 |
| 36 | 手动刷新建议的响应（v0.2.9 内，架构师裁定；review-05d8a16 m2） | `POST /suggestions/refresh` 同步处理：请求内只用缓存重算，不做外部拉取；`200 {suggestion: Suggestion \| null, changed: boolean, superseded_id: string \| null, data_as_of}`；错误码沿用 `409 SUGGESTION_REFRESH_TOO_FREQUENT{retry_after_s}`、`409 DATA_LICENCE_UNAVAILABLE`、`503 FRESH_DATA_REQUIRED{data_as_of}` | 按此返回响应体（同步完成后再响应） | 以响应体为准；刷新后再 GET 也允许，结果一致 |
| 37 | 拟定草案时 `blocked` 信号的错误码（v0.2.9 内，T-F23 前端待定 9） | 矛盾在 §7.7：#30 写“同向但因 `STRATEGY_CONFLICT` 处于 `blocked` 时**才是** `409 SIGNAL_NOT_EXECUTABLE`”，而同一格旧句“信号状态不是 `drafted`/`released` → `409 INVALID_STATE_TRANSITION`”把全部 `blocked`（含 `STRATEGY_CONFLICT`）都划给 409 INVALID_STATE_TRANSITION；前端 mock 取了“只有 `STRATEGY_CONFLICT` 例外”的折中。**以 #30 与“仍有生效原因 → `SIGNAL_NOT_EXECUTABLE`”为准并推广**：`blocked` 是“有生效原因”的状态，不论原因码，一律 `409 SIGNAL_NOT_EXECUTABLE{reason_ids}`，`STRATEGY_CONFLICT` 不是特例；`INVALID_STATE_TRANSITION` 只用于终态信号（`confirmed` `dismissed` `expired` `invalidated` `superseded`）。旧句写于 #30 之前（当时由系统拟定草案），#30 起 →`drafted` 由用户触发，所以 `open` 也可拟定草案。完整判定顺序见 §7.7 `POST /plan-drafts`。不改字段、不改枚举 | 按 §7.7 七步顺序实现；`reason_ids` 取请求中全部信号的 `active` 原因 | mock：去掉“只有 `STRATEGY_CONFLICT` 才 409 SIGNAL_NOT_EXECUTABLE”的分支，任一 `blocked` 或有生效原因 → `SIGNAL_NOT_EXECUTABLE`；`open` 可拟定草案；不存在或他人的信号 → `400`（不是 `404`）；review-b23401a 用例改回 `SIGNAL_NOT_EXECUTABLE` |
| 38 | 采集状态的心跳字段（v0.2.9 内，T-F24 缺失项 1） | `/admin/ingest/status` 顶层新增 `heartbeat: ingest_health`（复用 §3 已有枚举，**不新增枚举**，不为 null）：与 `/health/ready.ingest` 同一判定（§7.10：Redis 不可用 → `unknown`；`ingest:paused` 存在 → `paused`；心跳键缺失、无法解析或超过 120 秒 → `stale`；否则 `ok`）。`alerts` 中的 `heartbeat` 告警只由服务端生成（leader 不为 null 且本字段为 `stale`/`unknown`），前端不自行推算告警。#31 ⑤ 不变：不返回心跳时间、`ts` 或已过秒数 | 响应加 `heartbeat`，与 `/health/ready` 共用判定函数 | 显示“采集心跳：正常/超时/已暂停/无法判断”；字段缺失或取值不认识按 `unknown` 显示；mock 的 setter 改为写这个字段 |
| 39 | `master.*` 告警文案与生成方（v0.2.9 内，T-F24 缺失项 2；T-A04 #33 ⑥） | `message` 由**服务端**按固定表生成，前端原样显示，**不按 `key` 映射文案**，遇到不认识的 `key` 也照样显示 `message`；级别显示沿用“严重”/“警告”。5 个键的文案改为面向普通用户的说法（不带代码、数量、证书或用户名）：`master.snapshot_rejected`“证券名单更新失败，暂时沿用上一版”；`master.vendor_stale_listed`“行情源仍列着已退市的证券”；`master.vendor_unknown`“行情源出现交易所名单里没有的证券，暂不收录”；`master.quote_missing`“部分证券在行情源中暂时没有数据”；`master.field_mismatch`“部分证券的名称或上市信息与其他来源不一致，待核对”。排序：仍 `critical` 在前；同级时排在 #31 ② 全部键之后，5 个键之间按上面的顺序 | 按新文案实现（T-B53） | T-F25：只显示服务端 `message`；mock 用这 5 条文案并按此排序 |
| 40 | 证书 `days_left` 为 null（v0.2.9 内，T-F24 缺失项 3） | `IngestLicenceStatus.days_left`（及 `DataLicenceStatus.days_to_expiry`）为 null **只表示用户没有填写到期日**（`expires_on` 为 null），不表示“不会过期”，也不表示“已过期”；null 不触发 `licence.expiring` 或任何到期类告警（问题 94）；排序仍为 null 在后。前端显示：null →“未填写到期日”；负数 →“已过填写的到期日”（是否失效以 `status` 为准）；0 →“今天到期”；正数 →“还剩 N 天” | 无（null 时不出 `licence.expiring`，补测试） | 按左列显示；mock 保持 null 不告警 |
| 41 | 证券接口的搜索限流与缓存头（v0.2.9 内，架构师裁定 2026-11-01；reports/T-A04-ops.md；plan 1.3、第 9 节问题 52） | ① 搜索单独限流：`GET /securities/search` 与 `GET /securities?q=` 在网关另设限额，**每客户端（按客户端 IP，与全站限速同键）5 r/s、burst 20**，与全站限速同时生效；超限返回统一错误信封 `429 RATE_LIMITED`（`details.retry_after_s`）+ `Retry-After` 头，与 §1 限速一致，不新增错误码。② `/securities/*`（含 `search`、`?q=`、`{code}` 及全部子资源）的**所有响应**（含 `304` 与错误）带 `Cache-Control: private, no-store`，覆盖 §1 条件请求行的 `private, no-cache` 与 search 原写的 `private, max-age=60`；弱 ETag / `If-None-Match` → `304` 照常。③ 不提供证券与行情数据的批量导出端点（问题 52）；现有 `errors.csv` 只含本人导入的掩码行，不受影响 | 路由层统一设 `Cache-Control`；网关新增 search 限流 zone（运维） | 不缓存 `/securities/*` 响应（不写本地存储）；429 按 `retry_after_s` 退避，搜索框输入做防抖（建议 ≥ 250 ms） |
| — | `/meta/enums.version` | `"v0.2.8"` → `"v0.2.9"`；`enums` 新增 4 个键：`candidate_signal_event_cause`（T-A10）与 `research_candidate_status`、`research_candidate_origin`、`candidate_decision`（T-A11）；#30 再加 `plan_status`、`plan_condition_type`，共新增 6 个 | 同步 | `CONTRACT_VERSION` |

### v0.2.8（2026-11-02，T-A09：`/admin/ingest/status` 按证书拆分、ETF 纳入（plan 第 9 节问题 53 已定）、注册蜜罐字段、管理员暂停期间的证书 PUT 规则、`/admin/*` 不进 openapi（架构师裁定）、首页为 `/today`；**含不兼容变更**：#1（管理端响应结构）、#12–#14（证书接口在暂停期与重复 PUT 时的行为）、#15（`openapi.json` 不再含 `/admin/*`）；#4 为默认搜索结果的行为变化，结构兼容）

| # | 项 | 决定 | 后端改动 | 前端改动 |
|---|---|---|---|---|
| 1 | `/admin/ingest/status` 证书状态（**不兼容**，仅管理端） | 删除全站 `licence: {expires_on, days_left}`，改为按证书的 `licences: IngestLicenceStatus[]` 与 `licences_truncated: boolean`（§5.1、§7.9）；字段与 v0.2.6 `/admin/data-licences`、每证书令牌桶与 p0/p1/p2 队列同名同义；**不含证书值或其任何片段** | 改响应；按证书汇总调用量、队列、熔断 | `/admin/ingest` 页改为按证书的表格 |
| 2 | `AdminDataLicence` | 加 `licence_id: uuid \| null`（未设置为 `null`），与 `IngestLicenceStatus.licence_id` 对应 | 新增字段 | 可选：两页互相跳转 |
| 3 | `security_type` 加 `etf` | ETF 纳入证券公开主数据、搜索、行情、持仓与导入；**策略不对 ETF 运行**；可转债本版不纳入（v0.2.7 未决 Q3） | 枚举；主数据导入交易所 ETF 名单【待 Q2 / T-A04 补测】 | 类型联合加 `etf`；类型徽标“ETF” |
| 4 | 证券搜索（行为变化） | `types=` 默认由 `stock,cdr` 改为 `stock,cdr,etf`；同层排序 `stock` > `cdr` > `etf` > `index`；默认仍不含指数 | 改默认值与排序 | 结果中显示 ETF 徽标；只要股票时传 `types=stock,cdr` |
| 5 | 证券资料 | ETF：`board`、`list_date_basis`、`risk_flag`、股本、`industry` 为 `null`，`concepts` 为 `[]`，不计入缺失、不出 gap（§5.1） | 同步 | 不显示这些栏位 |
| 6 | 个股数据 | ETF 的 financials、fund-flows、factors、announcements：`200`、空 `items`、`data_status:"unavailable"`、`gaps[].reason="not_applicable"`；指数保持 `no_source` 不变 | 同步 | 显示“ETF 不适用” |
| 7 | `gap_reason` 加 `not_applicable` | 该证券类型没有此类数据（本版只用于 ETF） | 枚举 | 文案 |
| 8 | 行情 | ETF 的 `/quotes`、`/bars`、`/terminal`、`/today` 行与股票同口径；价格保留 3 位小数【待 T003 补测：麦蕊 ETF 实时与日 K、复权口径】 | 采集范围含 ETF 持仓与自选 | 价格按 3 位小数显示 |
| 9 | 持仓与导入 | ETF 成交可导入、手工录入、重建持仓；整手 100 份；`sellable_qty` 按 T+1（v0.2.9 内，T-O11 评审裁定：ETF 类别数据源接入前所有 ETF 一律 T+1，plan 2.13）；可转债行仍按 `IMPORT_UNKNOWN_SECURITY` | 同步 | 无 |
| 10 | 策略实例 | ETF 不能建实例：`scope="security"` 且为 ETF → `422 INSTANCE_SCOPE_INVALID{scope, security_code, security_type:"etf", issue:"security_type_not_supported"}`（复用错误码，详情加三个键）；`account`/`watch_group` 范围运行时跳过 ETF；分类器 HG1 已对非股票判 0 分，规则不变，不产生 `proposed`；H-01 不挂到 ETF 持仓（§6.0A 第 8 条） | 校验与运行范围 | 个股页对 ETF 隐藏“建策略实例”，或按 422 提示 |
| 11 | 注册蜜罐（架构师裁定） | `POST /auth/register` 加可选字段 `website`（隐藏，须为空或不传）与 `form_started_at`（int，毫秒）；命中时返回与正常注册相同的状态码和响应体，不建用户，审计 `auth.register_honeypot`（不记表单内容），仍计入 IP 限速；两字段不触发 `extra=forbid` 的 400（§7.1） | 改注册体与判定 | 注册页加隐藏输入与表单渲染时间 |
| 12 | 暂停期 PUT（**行为定义**，架构师裁定） | 管理员暂停按用户记录；暂停期间 `PUT /me/data-licence` → `202`，`status` 仍为 `paused_by_admin`，不验证；DELETE 后再 PUT 也不解除；只有管理员 resume 解除（§7.1、§7.9） | 暂停记录与证书行分离 | 暂停状态下的提示文案 |
| 13 | 重复 PUT 同一证书（**行为定义**） | 不清除 `quota_exceeded`、`ip_limited` 和 `paused_until`；返回 `202` 与当前状态，到期前不验证。**补充（架构师裁定）**：删除后重新提交也不能跳过冷却——处于 `quota_exceeded`、`ip_limited`，或 `active` 但 `paused_until` 未到期时 DELETE，再于 `paused_until` 到期前 PUT **同一证书**，恢复删除前的 `status` 与 `paused_until`，返回 `202`，到期前不验证；是否同一证书由服务端按带密钥的证书指纹（HMAC）判定，不存明文；换成不同证书照常验证（§7.1） | 判定；删除后重新提交的冷却保持由 T-B04a-x 实现 | 无 |
| 14 | 暂停期测试与恢复 | 暂停期间 `POST /me/data-licence/test` → `409 DATA_LICENCE_UNAVAILABLE{status:"paused_by_admin"}`；resume 时证书已删除 → `not_set` | 同步 | 暂停时禁用“测试”按钮 |
| 15 | `/admin/*` 不进 openapi（**不兼容**，仅工具链） | `include_in_schema=False`；契约优先；管理端由契约测试验证（§1.3、§9） | 已如此实现，补契约测试 | 管理端类型按契约手写，不从 openapi 生成 |
| 16 | 首页 | 前端首页为 `/today`（今日关注），`/` 重定向到 `/today`；`/terminal` 为交易终端（plan 2.4） | 无 | 改根路由重定向 |
| 17 | v0.2.8 补充裁定（**架构师裁定**，版本号不变） | ① §4.1 `IMPORT_LOT_SIZE_IRREGULAR` 与 plan 3.5A-1 同步（ETF 按 100 份整数倍）；② `INSTANCE_SCOPE_INVALID` 加 `issue:"unknown_security"`：`scope="security"` 且代码不在证券主数据中 → `422 INSTANCE_SCOPE_INVALID{scope, security_code, issue:"unknown_security"}`（§4、§6.0A 第 8 条）；③ 证书设置开关 `DATA_LICENCE_SETTINGS_ENABLED=false`（生产默认）时 `PUT`/`PATCH /me/data-licence` 与 `POST /me/data-licence/test` → `503 MAINTENANCE`，`GET`、`DELETE` 照常（§7.1）；④ #13 补充：删除后重新提交同一证书不能跳过冷却；⑤ 管理员重复暂停幂等：已暂停时再次 pause（不论证书是否已删除）→ `204`，不返回 409（§7.9）；⑥ plan 7.3 补 T-B16 匿名化细则 | ② 校验；③ 已如此实现；④ T-B04a-x；⑤ 改 pause 判定；⑥ T-B16 | ③ 收到 503 `MAINTENANCE` 时显示“设置暂未开放”并禁用提交与测试；② 按 `issue` 提示“证券代码不存在” |
| — | `/meta/enums.version` | `"v0.2.7"` → `"v0.2.8"` | 同步 | `CONTRACT_VERSION` |

**v0.2.8 未决问题**（同步 plan 第 9 节问题 61–65；均有默认，未否决即按默认执行）

| # | plan 第 9 节 | 问题 | 默认（未否决即按此实现） | 需要谁定 |
|---|---|---|---|---|
| U1 | 61 | 跨境、债券、黄金、货币等 ETF 实行 T+0，`sellable_qty` 与 `T1_NOT_SELLABLE` 如何处理 | 一律按 T+1 计算（偏保守，只可能少算可卖数量） | 研究员核对品种清单 |
| U2 | 62 | ETF 名单来源；麦蕊 ETF 实时、日 K、复权是否可用 | 名单只用交易所公开基金列表；取不到行情时按 §1.1 降级 | T003 / T-A04 补测 |
| U3 | 63 | 交割单中的可转债按 `import_as_is` 导入后，持仓如何展示（无主数据、无行情） | ~~本版不变：按原代码显示，无行情~~ **【已定 2026-11-02，v0.2.9 #1–#3】**：标注“可转债·无行情”，`market_value`/`pnl`/`pnl_pct` 为 `null`，`weight_pct` 按成本估算并带 `estimated:true` | 编排者（已定） |
| U4 | 64 | 各档位麦蕊日额度（`IngestLicenceStatus.daily_limit`） | 只有钻石版过期后有值（`diamond_after_expiry_per_day`），其余为 `null` | T003 补测 |
| U5 | 65 | 指数的财务、资金流是否也改用 `not_applicable` | 不改，保持 `no_source`（避免对已上线行为做不兼容修改） | 架构师（下一轮） |

### v0.2.7（2026-11-02，T-A08：补齐策略列表 `risk_level`、策略实例列表与状态机、个股数据接口、周 K 口径、`/today` 的提醒、计划触发与数据缺口；证券公开主数据范围按用户 2026-11-02 决定（Q1）；**无不兼容变更**：只新增端点、字段和枚举值；`/securities?q=` 保留为别名）
> 本版不新增任何与荐股、评级、目标价相关的字段或文案；不写入任何证书值。标【待 T003 补测】【待补测】的数值或映射须等实测结果出来才能定稿。

| # | 项 | 决定 | 后端改动 | 前端改动 |
|---|---|---|---|---|
| 1 | `/strategies` 风险等级 | 列表元素和版本详情加 `risk_level: card_risk_level`（取当前版本关联 L1 卡片的值；未关联卡片时为 `normal`；派生版本继承母版本）；列表加筛选 `?risk_level=` | 查询时 join 卡片版本 | 列表徽标；启用开关旁的固定风险说明改为读列表字段（不再单独请求卡片） |
| 2 | 策略实例对象 | 定义 `StrategyInstance` 完整结构（§5.1）；`origin` 新增 `system`（H-01 一类系统挂载）；新增字段 `horizon`、`paused_by`、`pause_reason_code`、`paused_until`、`updated_at`、`archived_at` | `strategy_instances` 加列；`origin` 约束加 `system` | 用完整类型替换“最小字段” |
| 3 | 策略实例列表 | `GET /strategy-instances`：筛选（`status` 可多值，默认 `proposed,active,paused`）、§1.2 游标分页、`order: instance_sort` | 新增查询与索引 | 列表页筛选和排序 |
| 4 | 实例状态机 | §6.0A：明确 confirm/pause/resume/archive 的合法转换、请求体、幂等（目标态即当前态时返回 200 且不写事件）、`409 INVALID_STATE_TRANSITION{from,to,allowed}`；`origin=system` 的实例不能由用户归档；`/events` 元素结构 | 行锁 + 事件表 | 按 `allowed` 显示可用按钮；mock 改为幂等 |
| 5 | 证券搜索 | 新增 `GET /securities/search`：代码、简称、拼音首字母、曾用名、旧代码、模糊（pg_trgm）；分层排序；`/securities?q=` 保留为别名，结构不变 | `pg_trgm`、`name_initials`、历史表 | 搜索框改用新端点，展示 `match_kind` |
| 6 | 证券资料 | 新增 `GET /securities/{code}`（`SecurityProfile`）：证券公开主数据（全站一份，范围见 #19）+ 本人证书取到的行业、概念、股本 | 新增 | 字段改名（见 T-A08 报告分歧表） |
| 7 | 财务 | 新增 `GET /securities/{code}/financials` | 新增 | 增加 `report_period`、`announce_date` 展示 |
| 8 | 资金流 | 新增 `GET /securities/{code}/fund-flows` | 新增 | 分档净额允许为 null |
| 9 | 因子 | 新增 `GET /securities/{code}/factors`（只有全市场排名，**没有**行业内分位） | 新增 | 删除行业分位列 |
| 10 | 公告 | 新增 `GET /securities/{code}/announcements`：只给元数据和外链，不给正文和摘要 | 新增 + URL 白名单 | 外链只用 `url`，为 null 时不显示链接 |
| 11 | 板块资金 | 新增 `GET /market/sector-flows`：盘后数据，每日更新一次 | 新增 | `sector_id`→`sector_code`；停止 60 秒轮询 |
| 12 | 周 K 口径 | §6.2：`freq=w` 由日线按自然周聚合、`t` 为该周最后一个有成交的交易日、未收盘周 `is_final=false`、复权同日线；`Bar` 加 `is_final`，bars 响应加 `adjust_as_of` | 聚合实现 | `adjust_as_of` 变化时整段重载 |
| 13 | 共享对象 | 新增 `ProviderRef`、`SecurityHit`、`SecurityProfile`、`FinancialPeriod`、`FundFlowDay`、`FactorValue`、`Announcement`、`SectorFlow`、`StrategyInstance`、`TodayAlert`、`TodayPlanTrigger`、`TodayDataGap`、`RiskEvent` | 同步 | 同步类型 |
| 14 | 枚举 | 新增 `security_type` `board` `listing_status` `security_risk_flag` `security_match_kind` `report_period` `factor_category` `announcement_category` `sector_kind` `industry_taxonomy` `instance_origin` `instance_event_kind` `instance_sort` `sector_sort` `alert_origin` `alert_status` `plan_condition_kind` `data_gap_scope`（共 18 个）；`data_provider` 加 `exchange` | `/meta/enums` 同步 | 文案 |
| 15 | 读接口与证书 | 本版所有个股/板块**读**接口不返回 `409 DATA_LICENCE_UNAVAILABLE`，按 §1.1 只降级 `data_status` 并给 `data_licence_unavailable` gap；缓存未命中返回 `pending` 并按本人证书入队 | 按证书判定 | 横幅沿用 T-F22 |
| 16 | `/today` | 新增 `alerts`、`plan_triggers`、`data_gaps` 三块和顶层 `evidence[]`；`risk_flags` 元素加 `risk_event_id`；写明 8 个列表的“查看全部”去向 | T-B13 聚合 | T-F08 新增三块 |
| 17 | 列表补参（T-F17/T-F18） | `GET /candidate-signals` 元素即完整 `CandidateSignal`；`/non-executable-reasons` 加 `released_since`；`GET /plan-drafts` 加 `?status=&security_code=&signal_id=`，`PlanDraft` 加 `created_at`；`stale` 草案的重新生成就是用原 `signal_ids` 再 `POST /plan-drafts` | 同步 | 同步 |
| 18 | 风控事件 | `GET /risk-controls/events` 定义元素 `RiskEvent` 与参数 | 新增 | `/risk-controls` 页加“事件”页签 |
| 19 | 证券公开主数据范围（Q1，**用户已定 2026-11-02**；plan 2.1B 例外、第 9 节问题 51） | 只有交易所公开信息全站共享：**代码、简称、拼音、曾用名、交易所、板块、上市日、状态、风险警示**（`type`、`code_history`、`delist_date`、`list_date_basis` 分别是代码、上市日、状态的组成部分）。行业、概念、股本等仍按本人证书各取。公开信息的确切来源（交易所公开列表，或用管理员本人证书拉取）【待 Q2 / T-A04 补测】；**确认前不得用他人（含管理员）的证书为其他用户取数**，只用交易所公开列表。草案中的 `full_name` 不在上述范围内，**不收录** | 主数据表只存上述字段 | 不展示全称 |
| 20 | 通读修正（不改语义） | §1“证券简称”规则补 `security_code` 可为 null 时的例外；§3 `data_provider` 说明补 `ProviderRef.provider`；§4 `IMMUTABLE_RESOURCE` 补“已归档的策略实例”；§5.1 `Bar.t` 周线口径指向 §6.2；§6.0 实例行改为与 §6.0A 一致；§7.2 `/trades/{id}/void` 行多出一列（4 格放进 3 列表），合并为 3 列；§7.3 `/today` “到对应列表接口查看”改为指向去向表；§7.5 `/risk-controls/events`、实例 pause/resume/archive、`/events` 由“风控事件”“状态跃迁”“实例事件”改为完整定义；§9 v0.2.6 验收中的版本断言注明 v0.2.7 起的取值 | — | — |
| — | `/meta/enums.version` | `"v0.2.6"` → `"v0.2.7"` | 同步 | `CONTRACT_VERSION` |

**v0.2.7 未决问题**（同步 plan 第 9 节问题 51–60；Q2–Q10：编排者 2026-11-02 定为按默认执行，Q3 改定见该行；Q2、Q8、Q10 补测后复核）

| # | plan 第 9 节 | 问题 | 默认（未否决即按此实现） | 需要谁定 |
|---|---|---|---|---|
| Q1 | 51 | 证券公开主数据是否全站一份（plan 2.1B 原写“证券列表……也按证书各取一份”） | **已定（架构师 T-A08，2026-11-02）**：见上表 #19；来源【待 Q2 / T-A04 补测】，确认前不得用他人证书 | — |
| Q2 | 52 | 交易所公开证券列表能否展示、能否再分发（T007 §4）；连同 Q1 的来源（交易所公开列表或管理员本人证书） | 只展示 Q1 所列公开字段，加 `attribution` 注明来源；来源确认前只用交易所公开列表 | 用户（合规）；T-A04 补测 |
| Q3 | 53 | ETF、可转债是否纳入 `security_type` 和搜索 | **已定（编排者，2026-11-02）**：ETF 纳入 `security_type`、搜索与持仓（交割单可能含 ETF 成交），策略不对 ETF 运行；可转债本版不纳入。枚举与各接口的同步**已在 v0.2.8 完成**（T-A09，见 v0.2.8 #3–#10） | — |
| Q4 | 54 | 因子的行业内分位：麦蕊没有直接提供，自行计算需要定义行业口径和最小样本数 | 不提供，只给全市场排名 | 研究员 |
| Q5 | 55 | 实例归档时，其已开放的候选信号如何处理（继续有效直到过期，还是置为 `invalidated`） | 暂不变更状态，信号自然过期 | 架构师 + 研究员 |
| Q6 | 56 | 搜索默认是否包含指数 | 不包含，需要时传 `types=` | 前端 + 产品 |
| Q7 | 57 | 实例数量是否受权益上限约束（`ENTITLEMENT_LIMIT_REACHED`） | 本版不加；如需加，confirm/resume 时检查 | 架构师（2.9 权益） |
| Q8 | 58 | 复权 `f` 与 `fr` 的区别、前复权基准日如何取得 | 先按 `f` 实现，`adjust_as_of` 来源待补测 | T003 补测 |
| Q9 | 59 | `/alerts`、`/plans` 的完整结构仍未定义（T-F06/T-F07 卡在这里）；`/today` 的“查看全部”指向这两个页面 | `TodayAlert`、`TodayPlanTrigger` 先作为这两个接口元素的子集，结构定义时必须兼容 | 架构师（T-A09 未处理，顺延下一轮） |
| Q10 | 60 | 板块资金的 `industry` 用哪套行业分类；资金流分档阈值、因子单位等 | 标【待 T003 补测】 | T003 补测 |

### v0.2.6（2026-11-02，T-A07：每用户自用麦蕊证书（用户已定，plan 2.1B、第 9 节问题 49–50）；并入 T006e 架构裁定；**含不兼容变更**：`HorizonCap.kind` 删 `requires`、加 `gate`）
> 证书值**永不出现在任何响应、错误体、SSE、通知或日志中**（也没有末几位或指纹）。示例与测试夹具一律使用运行时生成的虚构值。

| # | 项 | 决定 | 后端改动 | 前端改动 |
|---|---|---|---|---|
| 1 | 每用户证书 | 每位用户只用自己的麦蕊证书取数；默认不跨用户共享（`data_sharing.mode=per_licence`；`shared_cache`【待麦蕊书面确认】，禁用）；**不回退**到他人或管理员证书 | `user_data_licences`（HPKE 密文，只有 `ingest` 能解密）、每证书令牌桶与队列、`source_licence_id` | — |
| 2 | 端点 | 新增 `GET/PUT/PATCH/DELETE /me/data-licence`、`POST /me/data-licence/test`（7.1） | 新增 | “设置 → 数据证书”页：密码型输入、提交后清空、永不回显 |
| 3 | 管理端 | 新增 `GET /admin/data-licences`、`POST /admin/data-licences/{user_id}/pause` · `/resume`（7.9）；`/admin/ingest/status` 的 `budget` 改为全进程合计 | 新增 | 管理端证书列表（只有状态） |
| 4 | 共享对象 | 新增 `DataLicenceStatus`、`AdminDataLicence`；`Me` 加 `data_licence_status` | 新增 | 状态徽标、横幅 |
| 5 | 枚举 | 新增 `data_licence_status`、`data_licence_tier`；`notification_kind` 加 `data_licence`；`gap_reason` 加 `data_licence_unavailable` | 同步 | 文案 |
| 6 | 错误码 | 新增 `409 DATA_LICENCE_IN_USE`、`409 DATA_LICENCE_NOT_SET`、`409 DATA_LICENCE_UNAVAILABLE` | 新增 | 提示 |
| 7 | SSE | 新增事件 `data_licence` | 新增 | 实时刷新状态 |
| 8 | 数据状态 | 本人证书不可用时，行情接口不报错，`data_status` 为 `stale`/`unavailable`、`gaps[].reason="data_licence_unavailable"`；需要触发拉取的写操作返回 `409 DATA_LICENCE_UNAVAILABLE` | 按证书判定 | 横幅“你的数据证书不可用” |
| 9 | T006e 裁定 1 | `hints[]` 与分数无关：周期已被 `IT0`（无底仓）判 0 分时，`experience=novice` 仍给出 `IT0C` 提示 | 分类器 | — |
| 10 | T006e 裁定 2 | `HorizonCap.kind` 改为 `"gate" \| "data_missing"`：HG1–HG6 → `gate`（`rule_id` 为 `HGn`，判 0 分的记 `cap: 0`）；`LG0`/`LG0B` 的 `else_cap` → `data_missing`（`rule_id` 为规则 ID，架构师归类）；`IT0` 的 `else_score: 0` 是分数，不进 `caps`；删 `requires` | 分类器输出 | 封顶说明按 `kind` 显示 |
| 11 | T006e 裁定 3 | 卡片 `fit`：画像不匹配**不降低** `confidence`（置信度只反映信号证据），只给 `warnings[]`/提示文字；相关画像字段未填写时不提示 | 建议生成 | — |
| 12 | T006e 裁定 4（编排者决定） | `risk_level: high` 的模板（如 S-03）手动启用**不需要逐项确认**，前端在启用开关旁固定展示风险说明（plan 2.5.0A ⑫）；`POST /strategy-instances` 本来没有确认字段，不变 | 无 | 启用开关旁固定文案，不弹窗 |
| — | `/meta/enums.version` | `"v0.2.5"` → `"v0.2.6"` | 同步 | `CONTRACT_VERSION` |

### v0.2.5（2026-11-02，T-A06；用户决定：仅朋友间私下使用、非商业；**不做风险测评、不做同意流程**；**含不兼容变更（删除端点、表与错误码）**）
> 本节列出的项一律**作废**，以本节为准；下文 v0.2.4 及更早的变更记录保留原文只作历史，凡与本节冲突的条目视为作废（条目首列已标 ~~作废~~ 的除外不再逐条修改）。plan 第 9 节问题 43–48。

**A. 作废清单**

| 类别 | 作废项（来源） | 替代 |
|---|---|---|
| 表 | `consents`（v0.2.3 #26、v0.2.4 #4）、`legal_documents` 与停用记录表 `legal_document_events`（v0.2.4 #3）、`questionnaires`、`risk_assessments`（v0.2.4 #6）；`user_profiles.assessment_id`、`user_profiles.questionnaire_version`（v0.2.4 #7）；`strategy_instances.fit_ack`（v0.2.3） | 无。已建的由新迁移删除（plan 3.3） |
| 端点 | `GET /meta/consent-docs`；`GET /legal/{doc_key}`、`/legal/{doc_key}/versions`、`/legal/{doc_key}/{version}`；`POST /me/consents`；`GET /me/risk-assessment/questionnaire`；`GET /me/risk-assessment`、`GET /me/risk-assessments`；`POST /me/risk-assessment`（v0.2.3 #26，v0.2.4 #3、#4、#6）；`DELETE /me`（plan 原 7.3，契约未定义，一并不做） | 无；账号删除由管理员手动处理 |
| 请求/响应字段 | `POST /auth/register` 的 `agreements`（v0.2.4 #2）；`Me.consents`、`Me.risk_assessment` 与 `RiskAssessmentSummary`（v0.2.4 #5、#6）；`/me/profile` 的 `assessment_id`（请求）、`questionnaire_version`（响应）与 `exceeds_assessment` 校验（v0.2.4 #7）；`POST /strategy-instances` 的 `fit_ack`（v0.2.3）；`POST /me/consents` 的 `content_sha256`/`action`/`ui_surface`/`presentation`；`doc_versions`、`needs_reconsent`、`current_version`、`"unversioned"` | 注册：提交即视为已知悉固定免责提示；旧客户端仍发 `agreements` 时**服务端忽略**（不报错、不记录）。画像字段全部选填 |
| 错误码 | `403 CONSENT_REQUIRED`（含 `details.required`，v0.2.4 #8）；`422 STRATEGY_FIT_ACK_REQUIRED`（含 `ack_allowed`、`blocking_rule_ids`，v0.2.4 #9）；`409 VERSION_CONFLICT` 中“问卷版本不是当前版本”的用法；`400 VALIDATION_ERROR` 的 `issue: "exceeds_assessment"`、`understanding_required` | 不适配只进 `warnings[]` / `hints[]` |
| 门槛 | §1.3 ⚖ 合规门槛（有效测评 + `signal_risk_disclosure` 同意）；`POST /imports`、`POST /trades` 的 `sensitive_financial_info` 门槛（v0.2.4 #13 后半） | ⚖ 只作为“建议类输出”标记：前端在其输出旁展示固定免责提示，服务端不拦截 |
| 枚举 | `consent_key`、`legal_doc_key`、`consent_presentation`、`assessment_status`（v0.2.4 新增）；`reason_code` 中的 `PROFILE_OR_CONSENT_MISSING`（23 → 22 个） | 无 |
| 配置键 | `config/auth.yaml` 的 `consents.doc_versions`（7c62f59，v0.2.4 已移出）；研究员 `risk_questionnaire.yaml`（全部键）；分类器中画像类规则的 `else_cap`（`SH0`、`SH0B`、`SH0C`、`IT0B`、`IT0C`） | 分类器 1.2.0 规则键 `mode: hint` |
| 工具 | 文书/问卷发布 CLI 与哈希/指纹/版本级别校验（v0.2.4 #15，versioning.md §3、§6） | 无 |
| 待确认问题 | plan 第 9 节问题 38–42；问题 37 方案 A（新手封顶） | 问题 43–48 |

**B. 新增或修改**

| # | 项 | 决定 | 后端改动 | 前端改动 |
|---|---|---|---|---|
| 1 | 固定免责提示 | 文案以 `docs/strategies/compliance/disclaimer.md`（1.0）为准：“本工具仅供个人研究参考，不构成投资建议。候选信号由规则自动生成，数据可能延迟或出错，盈亏自负。”；页面底部、候选信号卡、行动计划卡固定展示；不需要勾选、不记录 | 无 | `RiskDisclosure` 组件用该文案（逐字一致）；注册页展示同一文案 |
| 2 | 周期分类器 1.2.0（`version_no: 3`） | 画像类 `requires` 规则改为 `mode: hint`：画像未填写 → 不封顶、不提示；已填写且不满足 → 只进 `hints[]`，不改分数、不进 `caps[]`、不影响 `suitable`。`SH0C`/`IT0C` 只在自报 `experience=novice` 时提示 | 规则加载支持 `mode`；新版本行不可变；1.1.0 保留 | 显示 `hints[]` |
| 3 | `/horizon-assessments` | 响应加 `hints: HorizonHint[]`（永不为 null）；去掉“用户覆盖周期须带 `fit_ack`” | 同上 | 类型 |
| 4 | `POST /strategy-instances` | 删 `fit_ack`；I3 只校验模板 `horizons`（`STRATEGY_HORIZON_MISMATCH`）；周期不适合或画像低于卡片 `fit` 下限 → 正常 201，`warnings[]` 给出中文说明 | 删 fit_ack 校验 | 删确认对话框，改为显示 warnings |
| 5 | `Me` | `{id, username, display_name, role, status, entitlements}` | 删字段 | 类型；删 `/onboarding` 跳转（保留 `/account-status`） |
| 6 | `/me/profile` | 请求/响应不再有 `assessment_id`、`questionnaire_version`；`effort`、`risk_tolerance`、`experience` 用户自报、可为 null | 删校验与列 | 画像页改为普通选填表单 |
| 7 | 更换 LLM 供应商 | 只发站内通知（`notification_kind=system`），不要求重新同意 | 运维流程 | 无 |
| — | `/meta/enums.version` | `"v0.2.4"` → `"v0.2.5"`；删除 A 表所列枚举与原因码 | 同步 | `CONTRACT_VERSION` |

### v0.2.4（2026-11-01，T-A05；合入研究员 T-B15 的 `docs/strategies/compliance/`（问卷、文书版本规则）与前端评审 T-F02 §4 D1–D7；**含不兼容变更**：注册 `agreements` 的 `risk_disclosure` 改为 `signal_risk_disclosure`，`POST /me/consents` 必须带 `content_sha256`，`/meta/registration` 不再返回 `doc_versions`，`Me.risk_assessment` 结构改变，`POST /me/risk-assessment` 响应改为 `RiskAssessment` 且返回 201）
> 为什么单独升版本而不并入 v0.2.3：后端尚未同步 v0.2.3，但本次新增 3 张表、8 个端点并改了已发布字段的取值与必填项，不是“只加可选字段”，并入会让 v0.2.3 失去意义。
| # | 项 | 决定 | 后端改动 | 前端改动 |
|---|---|---|---|---|
| 1 | 同意项键名（RQ 待办 1、V 待办 1） | 新枚举 `consent_key` = `terms` `privacy` `signal_risk_disclosure` `sensitive_financial_info`；`legal_doc_key` = `consent_key` + `site_risk_notice`（只展示，不需同意）。免责声明并入 `terms`，不单列。`email_notification` 只在库里，不出现在契约 | 新迁移改 `consents.kind` CHECK 并改写旧值（plan 3.3） | 用 `consent_key` |
| 2 | 注册 `agreements`（D2） | 必须包含 `terms`、`privacy`、`signal_risk_disclosure`（原 `risk_disclosure` 作废，T-B03 现实现需改），可另含 `sensitive_financial_info`；其他值 → 400。`apply_note` ≤ 200（原 ≤ 500）；`display_name` 1–32；保留用户名 → 400 | 改校验 | 注册页勾选项 |
| 3 | 文书版本来源（V 待办 4） | 当前版本来自新表 `legal_documents`（只插入），取代 v0.2.3 #26 的 `config/auth.yaml consents.doc_versions`；无已发布版本时为 `"unversioned"`，只允许 `closed` 模式。新增 `GET /meta/consent-docs`、`GET /legal/{doc_key}`、`GET /legal/{doc_key}/versions`、`GET /legal/{doc_key}/{version}`（D4） | 建表 + 触发器 + 发布脚本 + 端点；删 auth.yaml 的 `consents` 段 | 同意弹窗从 `/meta/consent-docs` 取版本和链接 |
| 4 | `POST /me/consents`（V 待办 2） | 请求体加 `content_sha256`、`action`（`grant`/`withdraw`，默认 grant）、`ui_surface`、`presentation: consent_presentation`；`version`、`content_sha256` 与当前版本不符 → 400；服务端记录 channel、IP/UA 哈希、时间 | consents 扩列（plan 3.3） | 提交时带哈希 |
| 5 | `Me.consents`（V 待办 3） | 每个 `consent_key` 都有一项：`{version \| null, accepted_at \| null, current_version, needs_reconsent}`；`needs_reconsent` 按 versioning.md §2 判定（MAJOR 变化或已撤回；`"unversioned"` 视为 MAJOR 0） | 计算 | 据此弹出重新同意 |
| 6 | 风险测评端点（RQ 待办 2、3、6、7、8，D2、D4） | 新增 `GET /me/risk-assessment/questionnaire`（不含分值）、`GET /me/risk-assessment`（最近一次 + 状态）、`GET /me/risk-assessments`（历史）；`POST /me/risk-assessment` 请求体加 `questionnaire_version`（不符 → 409 `VERSION_CONFLICT`）、可选 `started_at`、`client_duration_s`；`choice` 暂为 string（以后有多选再改数组）；K4 答错 → 400 `details.reason="understanding_required"`；24 小时内超过 3 次 → 429；响应 `201 RiskAssessment`。`trade_count_12m` 由服务端从成交记录算，不由客户端提交 | 按 `risk_questionnaire.yaml` 实现计分；新表 `questionnaires`、`risk_assessments`（只插入） | `/onboarding` 测评页 |
| 7 | 画像与测评（RQ 待办 5） | 测评只给出建议值，用户确认后 `PUT /me/profile`（带 `assessment_id`）写入新画像版本；`risk_tolerance`、`experience`、`effort` 可为 null（未测评）；**【待用户确认】** 超过测评上限 → 400 `issue: exceeds_assessment`、`max_allowed`（plan 第 9 节问题 38）。无画像 → `GET` 404；`max_single_position_pct` 5–50、最多 2 位小数（D2） | 校验 | 画像页显示上限 |
| 8 | `CONSENT_REQUIRED.required`（RQ 待办 4） | 取值为 `consent_key` 或 `"risk_assessment"`（没有有效测评，含过期超过宽限期） | 门槛判定 | 按 `required` 跳转 `/onboarding` |
| 9 | `STRATEGY_FIT_ACK_REQUIRED.details` | 加 `ack_allowed: boolean`、`blocking_rule_ids: string[]`；**【待用户确认】**（问题 39）`no_loss_tolerance` 用户的 short/intraday_t、HG1–HG6 与 `data_missing` 封顶 `ack_allowed=false` | 判定 | 不可确认时不显示确认按钮 |
| 10 | `DimensionCell` 笔误（D1） | `exit_hits`、`exit_total` 与 `rules_*` 属于同一对象（v0.2.3 文字中多了一个 `}`），结构不变 | — | 按同一对象解析 |
| 11 | 导入提示的处理选项（D3） | §4.1 新增“处理选项”表，逐码给出 `resolution_choices`（第一个为默认）与覆盖类选项；resolve 只要求 `resolution_choices` 非空，不限 `needs_action`；覆盖类 `reason` 必填（≤ 200） | 按表生成 | 按表渲染 |
| 12 | 管理端用户与成交结构（D5） | 定义 `AdminUser`、`Trade`、`TradeCreate`、`ImportBatchSummary`；新增 `POST /trades/{id}/void`；PATCH `/admin/users/{id}` 在 `rejected`、`disabled`、`disabled→approved` 时 `reason` 必填 | 按结构返回 | 按结构渲染 |
| 13 | CSRF 与敏感信息门槛（D6） | CSRF 为双提交，以 Cookie 为准；`sensitive_financial_info` 门槛改为 `POST /imports`、`POST /trades`（`POST /accounts` 不再要求，修正 v0.2.3 #26） | 改门槛范围 | — |
| 14 | `/portfolio?account_id=`（D7） | `account_id` 可选，不传时合并全部账户 | 加参数 | 账户切换 |
| 15 | 文书与问卷发布（V 待办 4–6） | 发布脚本校验哈希、版本号递增、变更级别与清单一致、MAJOR 需 `review_ref`；接口不提供发布或修改文书的写接口 | CLI（T-B15） | — |
| — | `/meta/enums.version` | `"v0.2.3"` → `"v0.2.4"`；新增枚举 `consent_key`、`legal_doc_key`、`consent_presentation`、`assessment_status` | 改常量 | `CONTRACT_VERSION`、契约测试 |

### v0.2.3（2026-11-01，T-A03；处理前端 T-F01 §9 遗留 21 条，同步研究员 T006b 与用户拍板；**含一处不兼容类型变更**：`Evidence.provider` 改用 `data_provider`，删除 `local`）
| # | 项 | 决定 | 后端改动 | 前端改动 |
|---|---|---|---|---|
| 19 | `/horizon-assessments` 证据 | 响应加 `snapshot_id` 与 `evidence: Evidence[]`；`reasons[].evidence_ids` **只在本响应的 `evidence[]` 内解析**（同 `Suggestion` 的信封规则），不得借用建议卡的证据 | 加字段；契约测试检查可解析 | 改为从本响应解析，删除借用 `sg.evidence` 的逻辑 |
| 20 | 纯离场策略（exit-only）在矩阵中的口径 | 见 §5.2「纯离场策略」：只对**持有中**证券求值；`DimensionCell` 加 `exit_hits`/`exit_total`（只统计 role ∈ {weakening, exit}），`rules_passed/rules_total` 定义不变（仍为 0/0）；单元格 `view` 由离场规则派生；计入行级 `divergent`；从不给出 `entry_ok`/`buy`/`add` | 派生逻辑与校验 | 单元格显示“离场 x/y”，不再显示“—” |
| 21 | `classifier_version` 与 `inputs_missing` | `classifier_version` 为语义化版本字符串，匹配 `^(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)$`（如 `"1.1.0"`）；`inputs_missing` 为 **feature_catalog 键**（`f.*`）数组，去重、升序，**永不为 null**，无缺失时为 `[]`；新增 `caps[]` 给出“哪个周期因什么被封顶” | 加 `caps`；分类器 v1.1.0（问题 37 方案 A） | 按 `caps[]` 逐周期提示 |
| 1 | `Evidence.provider` | 统一为 `data_provider` 枚举（`mairui` `user_import` `user_input` `system`）；**删除 `local`** | 用枚举 | 已按 §3 实现；展示层对未知值兜底 |
| 2 | 日报路径 | API 只有 `/daily-reports`、`/daily-reports/{date}`；前端页面路由同名，`/reports`、`/reports/:date` 仅作重定向（plan 2.4 已改） | 无 | 无（已实现） |
| 3 | `DailyReport.stocks[]` | 加 `close`、`change_pct`、`data_status`、`max_risk_level`（均可为 null，`data_status` 除外） | 加字段 | 加列 |
| 4 | 现金字段 | **两个名字、两个含义，都保留**：`cash` = 由交割单与资金流水重建的**现金余额**（对应 plan 3.5A `cash_balance`），用于日报、草案上下文；`cash_available` = **可用资金**，取最近一次导入的券商资金快照的“可用”（`broker_position_snapshots.cash_available`），没有快照时等于 `cash`，只出现在 `/terminal.account` | 按定义计算 | 标签区分“现金余额”“可用资金” |
| 5 | `TerminalRow` 时效 | 加 `data_as_of: string(datetime) \| null`（该行行情与建议中较旧者的数据时点；完全无数据为 null） | 加字段 | `DataStatusTag` 改读此字段 |
| 6 | 图表标记 | V1 **不设专用端点**：日 K 标记取 `/candidate-signals?security_code=`（时点 = `data_as_of` 所在交易日），分时标记取 `/signals?security_code=&since=`；**必须带 `security_code`** | 两个接口支持该过滤 | 带 `security_code` 请求 |
| 7 | plan 前端版本 | 已按问题 34 定为 React 19 + antd 6；plan 中已无 React 18 / AntD 5 的残留（只剩问题 34 的历史说明） | 无 | 无 |
| 8 | `Bar.t` 与 `volume` 单位 | 维持【待 T003/T-B05】，不阻塞；口径定后只改说明不改字段 | T003 | 无 |
| 9 | `/market/overview` | 定义最小结构，见 §7.3 | 实现 | 可接入 |
| 10 | `CandidateSignal` | 给出正式结构与可空性，见 §7.6 | 按结构实现 | 对齐类型 |
| 11 | `divergent` 口径 | 行级：该维度单元格中**同时存在** `bullish` 与 `bearish`（`neutral`/`unknown` 不参与）；整体 `consensus.status`：0 个策略 `none`，1 个 `single`，≥ 2 个且 `(action, t_leg)` 全部相同 `unanimous`，否则 `divergent` | 实现 | 对齐 |
| 12 | `/today` mock | 契约无改动；前端补 mock | 无 | 补 mock |
| 13 | 通知路由 | `target.route` 由服务端生成，前端直接跳转；格式表见 §5.1 `Notification` | 实现 | 用 `route` |
| 14 | 标记已读 | `POST /notifications/{id}/read` 与 `POST /notifications/read-all` 均返回 **`204 No Content`**，幂等（已读再标不改 `read_at`）；客户端随后刷新 `unread-count` | 实现 | 无（mock 已是 204） |
| 15 | `RuleRef.dimension` | 所有 role（含 filter/veto/counter/invalidation）**必填、非空**；取规则规格中的 `dimension`（_template.md §2）；系统组件按 catalog 第 2 节归属（G-01 → `technical`，G-02 → `sector_market`，N-01 → `news`，H-01 → 规则自身声明） | 导入校验 | 无 |
| 16 | `/terminal.trade_date` | 加 `trade_date: string(date)`（行情所属交易日；非交易日为最近一个交易日） | 加字段 | 用它代替从行情时间截取 |
| 17 | 批量查不可执行原因 | `GET /non-executable-reasons` 加 `signal_ids=`（逗号分隔，≤ 100）与 `suggestion_id=` 过滤；带这两个参数时不分页 | 实现 | 按卡批量取，删除“取全部再过滤” |
| 18 | 建议卡“当前” | 不新增 `current`；`status=active` 即当前卡，同一用户同一证券**至多 1 张** `active` | 加唯一约束 | 无 |
| — | T006b 交易规则（plan 2.13、6.1） | 风险警示 50 万股/日买入上限只适用主板与创业板，不适用科创板；“只能限价申报”只适用沪市；沪 3.3.17、深 3.3.19 涨跌停价舍入已核实（含两条边界规则）；2023-04-10 之前不建模【已定】 | 改 `config/market_rules.yaml`（后端负责） | 草案/通知文案按交易所区分 |
| — | 问题 37【已定 A】 | novice（或画像未填）用户的 `short` 分数封顶 59，用户可用 `fit_ack` 覆盖；`intraday_t` 同样封顶 59（规则 IT0C，编排者默认，用户可否决） | `horizon_classifier.yaml` 发 1.1.0 | `caps[]` 展示 |
| 22 | 请求体过大（同日补充，回应 review-T-B02） | 应用层超限（导入文件超过 `imports.max_file_bytes` 等，键见 plan 6.1 `config/imports.yaml`；T-A05 统一键名）仍按 `422 IMPORT_FILE_ERRORS` + `IMPORT_*` 码返回、不创建批次；新增 `413 PAYLOAD_TOO_LARGE` 只用于**请求体超过网关/框架上限**（nginx `client_max_body_size`，须略大于应用上限），响应仍是 §4 错误信封（nginx 用 `error_page 413` 返回 JSON，`request_id` 照常） | 框架层兜底映射；运维配 nginx JSON 错误页 | 按通用错误处理，提示“文件过大” |
| 23 | `IT0C` 与原因码（同日补充，T-A05） | `SH0C`/`IT0C` 是周期分类器规则 ID，只出现在 `HorizonCap.rule_id`（`kind: "requires"`），**不是** `reason_code`，不进 `/meta/enums`；§6.1 原因码不变（仍 23 个） | 无（现实现即如此） | 按 `rule_id` 展示封顶说明，不查原因码文案 |
| 24 | 用户名长度（同日补充，T-A05） | `username` 由 3–32 改为 **4–32**，`^[a-z0-9_]{4,32}$`（输入转小写），保留名 → `400 VALIDATION_ERROR`；与 plan 3.3/3.6 一致 | 无（T-B03 已按 4–32） | 注册表单校验改 4 |
| 25 | 会话（同日补充，T-A05） | 空闲 7 天滑动 + 绝对 30 天；无“记住我”；登录与改密轮换 `sid` 和 CSRF 令牌（§1.3）；键见 plan 6.1 `config/auth.yaml` | 加绝对过期与改密轮换 | 改密 204 后从 `csrf_token` Cookie 重读令牌 |
| 26 | 同意书（同日补充，T-A05） | `POST /me/consents` 的 `key` 增加 `sensitive_financial_info`；`version` 必须等于服务端当前版本（`GET /meta/registration` 返回 `doc_versions`），否则 `400 VALIDATION_ERROR`；`POST /accounts`、`POST /imports` 及手工录入成交/持仓的写接口要求已同意 `sensitive_financial_info`（plan 7.3，个保法第 28 条单独同意），否则 `403 CONSENT_REQUIRED` | 校验版本、加 key 与门槛 | 导入前弹单独同意；提交 `doc_versions` 中的版本 （**v0.2.4 改**：版本来源改为 `legal_documents` 与 `/meta/consent-docs`，门槛范围改为 `POST /imports`、`POST /trades`）|
| 27 | 邀请码（同日补充，T-A05） | 注册体增加 `apply_note`（`invite` 模式必填）；邀请码错误/过期/已用/已吊销统一为 `400 VALIDATION_ERROR {fields:[{field:"invite_code", issue:"invalid"}]}`；新增 `/admin/invites`（§7.9）。邀请功能（T-B03c）完成前 `invite` 模式按 `closed` 处理，返回 `503 REGISTRATION_CLOSED` | T-B03c 实现 | 注册页加申请说明；管理端邀请码页 |
| — | `/meta/enums.version` | `"v0.2.2"` → `"v0.2.3"` | 改常量 | `CONTRACT_VERSION`、契约测试 |

### v0.2.2（2026-11-01，T-A02；合入研究员 T006a：周期分类器 v1、规则语义、交易规则核实；不改字段名，只放宽一处类型、补两处字段与说明）
| 项 | 决定 | 后端改动 |
|---|---|---|
| `RuleRef.passed` | 类型 `boolean` → **`boolean \| null`**。语义统一为“**该规则表达式求值为真**”：entry/filter/hold 为真 = 条件满足；veto/counter/invalidation/weakening/exit 为真 = **命中**。数据缺失无法求值 → `null`；未持有时 `ctx.*`/`plan.*` 规则不求值、**不出现在** `rule_refs`/`dimension_views[].rules` 中（plan 2.5.14 H⑮） | 求值器输出三值；Pydantic 类型改 `bool \| None`；前端渲染三态（满足/命中、不满足、无法判断） |
| `rule_ids_passed`（夹具 `expected.json`）与 P1b | `rule_ids_passed` = `passed == true` 的规则 ID（按 `rules[]` 顺序），`null` 不列入。`POST /plan-drafts` 的 `PLAN_REQUIRES_EXPLAINABLE_SIGNAL` 判定改为：信号中**没有任何 role ∈ {entry, exit, weakening} 且 passed = true 的 RuleRef** | 改判定条件；契约测试补“只有 veto 命中 / 只有 null”两例 |
| `DimensionCell.rules_passed/rules_total`、`key_evidence_ids` | 只统计 role ∈ {entry, filter, hold} 的规则（命中的 veto/counter 是反向信息，另见 `counter_evidence`、`gate_results`） | 改派生逻辑与一致性测试 |
| `/horizon-assessments` | `scores` **必含四个周期**，每个都是 int 0–100、**不为 null**（数据缺失按封顶处理，见 plan 6.1 `horizon_classifier.yaml` `data_missing_cap`）；`reasons[]` 元素为 `TextWithEvidence & {horizon: horizon, polarity: "for" \| "against"}`；新增 `inputs_missing: string[]`（缺失的 `f.*` 输入键，用来区分“真 0 分”与“缺数据被封顶”，回应 horizon_classifier.md §8 缺口 2；不再为此让 `scores` 允许 null）。重算触发新增 `position_open_close` | 改响应模型；分类器按规则 v1 输出 |
| 卡片 `refs[]` 与列表项 `ref` | 澄清：`/strategy-cards/{id}` 的 `refs[].ref` 是**出处编号**（如 `R12`），与卡片 `entry[]` 等列表项中引用规则的 `ref: <rule_id>` 不同义；两者都保留，不改名（plan 2.5.14 H⑬） | 导入器按位置区分；无接口字段变化 |
| `validation_summary.oos_result` | 确认 `string \| null`（plan 原写的结构化对象作废，以本契约为准） | 无 |
| G-01 与原因码 `LIMIT_LOCKED` 等 | 运行时 `gate_tradability` 中有对应原因码的检查项（停牌、一字涨停、ST/退市整理、新股）只写入 `gate_results` 并产出不可执行原因，**不把 `state` 改为 `vetoed`**；低价股仍为 veto（plan 2.5.11、2.5.14 H⑯） | 改闸门落点；T-T17 补“一字涨停 → `entry_ok` + `LIMIT_LOCKED`，打开后自动重评” |
| `/reconciliation` 成本口径 | 我方摊薄成本**计入分红**（现金红利冲减、股息红利税补缴计入，与通达信一致，plan 第 9 节问题 19 已定）；每次导入确认后与券商“成本价”对账 | 成本重建纳入 `account_events` 的红利与税费 |
| `/meta/enums.version` | `"v0.2.1"` → `"v0.2.2"` | 改常量 |

### v0.2.1（2026-11-01，T-A01 小修；不改任何字段名和枚举）
| 项 | 决定 | 后端改动 |
|---|---|---|
| `/admin/*` 访问控制自相矛盾（v0.2 的 §1.3、§9 写 403，§4、§7.9、变更记录写 404） | **统一为 404**（隐藏存在性）：凡不是“已登录且 `role=admin`”的请求（含未登录、普通用户、账号非 `approved`）访问任何 `/admin/*` 路径（含不存在的子路径、用错方法），一律 `404 NOT_FOUND`，响应体与普通不存在路径相同，不带 `Allow` 头。该判断先于 CSRF、同意、405、422 等其他校验。`403 FORBIDDEN` 保留在错误码表中，但 `/admin/*` 不再使用 | 管理端依赖从 403 改为 404；未登录访问 `/admin/*` 从 401 改为 404 |
| LLM 供应商 key 来源（配合 plan 2.7.1 DeepSeek 核实） | `/admin/llm/providers` 响应增加 `api_key_source: "env" \| "db"`；DeepSeek 的 key 只从环境变量 `DEEPSEEK_API_KEY` 读取（`api_key_source:"env"`），接口不可写入，PATCH 带 `api_key` → `422 VALIDATION_ERROR`；`api_key_set` 只表示进程内该值非空，任何接口都不返回 key 或其片段 | providers 序列化加字段 |
| `/meta/enums.version` | `"v0.2"` → `"v0.2.1"` | 改常量 |

### v0.2（2026-11-01，T-A01；处理前端原型评审 T-F00 §6 的 12 项与 T006 契约问题）
**改名 / 改口径**（客户端和后端须同步修改；原型 `src/types/contract.ts` 按此调整）
| 旧 | 新 | 说明 |
|---|---|---|
| 规则结果 `pass` | `passed` | 所有规则结果（`RuleRef`、`dimension_views[].rules[]`）统一 |
| `evidence_id`（单数） | `evidence_ids: string[]`；证据主键 `id` | 全文禁止出现 `evidence_id`；证据 `id` 在所属文档内唯一，全局用 `(snapshot_id, id)` 定位 |
| `invalidation: [{expr, evidence_id}]` | `TextWithEvidence{text, expr, evidence_ids}` | `reasons`、`counter_evidence`、`invalidation` 同构 |
| Suggestion 维度分 `score: 0.83` | `score: 0–100 整数`（未知为 `null`） | 对外所有 `score` 都是 0–100 整数；引擎内部 0–1 不外露；`confidence.value` 仍为 0–1 |
| `strategies[].stop_loss` / `take_profit`（平铺） | `strategies[].stops: Stops{stop_loss, take_profit, time_stop_days}` | 与 `CandidateSignal.stops`、`PlanDraft.stops` 统一 |
| `dimension_matrix[].cells[]{view}` | `DimensionCell{strategy_key, strategy_version_id, view, score, key_evidence_ids, rules_passed, rules_total}`，行上加 `divergent`（v0.2.3 起同一对象另有 `exit_hits, exit_total`，见 v0.2.3 #20） | §5.2 |
| `import_status`: `preview_ready` / `confirmed` | `previewed` / `committed`；新增 `discarded` | 6.0 状态机已更新 |
| 导入预览行 `status: ok\|error\|duplicate`、`error_code` | `status: import_row_status`、`findings: ImportFinding[]`、`dedup_status` | §4.1、§7.2 |
| `409 IMPORT_DUPLICATE_FILE` | 文件级 **warning** `IMPORT_DUPLICATE_FILE`（不再是 HTTP 错误） | 同一文件可重新预览，确认时按行去重 |
| `422 IMPORT_UNRECOGNIZED_FORMAT`、`422 IMPORT_ROW_COLUMN_MISMATCH` | `422 IMPORT_FILE_ERRORS{findings}`；`IMPORT_UNRECOGNIZED_FORMAT`、`IMPORT_ROW_COLUMN_MISMATCH` 改为提示码（名称不变） | 提示码全表见 §4.1 |
| `/imports/{id}` 的 `parser` | `parser_id`（`tdx_trades_v1` / `tdx_positions_v1`；旧名 `fmt_a_*` 作为别名接受） | plan 3.5A |
| `Stat`：n < 20 标 `small_sample` | n < 30 标 `small_sample`；n < 5 `value=null` | 展示阈值；降权门槛 n ≥ 20 不变 |
| SSE `signal{signal_event_id, security_code, kind, at}`（`kind` 未定义） | `SignalEvent`（§5.1），`kind: signal_kind`，加 `name`、`message` | 原型的 `quote_flip` → `rule_flip`，`text` → `message` |
| SSE `notification{id, kind, severity, title}` | 完整 `Notification`（§5.1） | 通知带 `created_at`、`read_at`、跳转目标 `target` |
| 原型中的 `/reports/daily/{date}` | 以 `/daily-reports/{date}` 为准 | 路径不变，补了结构 |
| `CandidateSignal.gate_results[].gate` | 说明：这是**运行时闸门名**（如 `gate_tradability`），不是 `gate` 枚举（G1–G7 晋级门禁） | 字段不改，只澄清 |

**新增**
- 枚举：`strategy_eval_state`、`executability_status`、`signal_kind`、`reconciliation_status`、`reconciliation_item_kind`、`card_risk_level`、`import_severity`、`import_scope`、`import_row_status`、`dedup_status`、`registration_mode`、`market_session`、`notification_target_type`、`bar_freq`、`bar_adjust`。
- 共享对象：`Stops`、`DimensionCell`、`StrategyConclusion`、`Suggestion`、`SuggestionSummary`、`Bar`、`WatchlistItem`、`Notification`、`SignalEvent`、`ImportFinding`、`DailyReport`、`TerminalRow`。
- 约定：凡含 `security_code` 的对象都同时带 `name`（证券简称）。
- 端点：`GET /terminal`（终端一屏聚合）、`GET /today` 的完整结构（两者都支持弱 ETag / 304）、`GET /meta/registration`、`PUT /imports/{id}/options`、`POST /imports/{id}/findings/{finding_id}/resolve`、`POST /imports/{id}/discard`、`GET /imports/{id}/errors.csv`、`PATCH /watchlist/{security_code}`；`/securities/{code}/bars` 补参数 `adjust`、`before`、`limit` 与响应结构；`/strategy-cards/{id}` 补 `ref`、`validation_summary`、`risk_level`；模板版本补 `internal_check`。
- 错误码：`422 IMPORT_FILE_ERRORS`、`422 IMPORT_NOTHING_TO_COMMIT`、`422 IMPORT_WARNINGS_UNACKNOWLEDGED`；§4.1 导入提示码全表（46 个）。
- 前端约束：终端实时表格只用 AG Grid **Community**（MIT），禁止依赖 `ag-grid-enterprise`（CI 检查，§9）。

**v0.2 补充（同日，处理后端骨架报告 T-B01 §4 的问题）**
| 项 | 决定 | 后端改动 |
|---|---|---|
| 大小写冲突 | §1 新增“大小写”规则：JSON 键与普通枚举值 `snake_case`；**码类取值**（`error.code`、`reason_code`、`IMPORT_*` 提示码、`gate` 的 `G1`–`G7`）用 `UPPER_SNAKE`/大写。`/meta/enums` 现状即符合 | 无 |
| `DATA_STALE` 同名 | 原因码保留 `DATA_STALE`；HTTP 错误码 `503 DATA_STALE` **改名为 `503 FRESH_DATA_REQUIRED`**。三类码（错误码、原因码、导入提示码）命名空间互不重名，CI 检查 | 改 `ErrorCode` |
| 405 | 新增 `405 METHOD_NOT_ALLOWED`（带 `Allow` 头，`details: {allowed: [...]}`）；例外：非管理员访问 `/admin/*` 时仍返回 `404 NOT_FOUND` | 改 405 映射（原为 404） |
| `/health` | 拆为 `GET /health/live`（存活，恒 200）与 `GET /health/ready`（就绪）；`GET /health` = `ready` 的别名。db 或 redis 失败 → **503** + `status: "down"`；只有 ingest 异常 → **200** + `status: "degraded"`。字段见 §7.10 | 加 live、503、`checked_at`、`version` |
| ingest 健康来源 | **确认** Redis 心跳 + 120 秒判 stale；键 `ingest:heartbeat`，值改为 JSON（含 `ts`），`ingest:paused` 存在即暂停。见 §7.10 | 心跳解析从“Unix 秒”改为 JSON 的 `ts` |
| `/meta/enums` 外层结构 | 采用后端实现并补 `version`、`import_codes`：见 §7.10 | 加两个键 |
| `PENDING_T_A01` 的 21 个枚举 | 逐项核对：`epistemic_type` `horizon` `dimension` `dimension_view` `rule_role` `action` `t_leg` `confidence_level` `consensus_status` `suggestion_origin` `suggestion_status` `risk_control` `risk_level` `lifecycle` `candidate_signal_state` `reason_code` `reason_status` `check_on` `release_kind` `plan_draft_status` `suggestion_user_action` 的**取值 v0.2 均不变**，可以解除 PENDING 标记。v0.2 真正改值的只有 `import_status` | 解除标记；按上表新增枚举 |
| §3 未收录的枚举 | 新增 `health_status`、`component_health`、`ingest_health`、`gap_reason`、`data_provider`、`source_kind`；`data_status` 与 `gate` 改为列出全部取值 | 加入 `CONTRACT_ENUMS` |

### v0.1（2026-11-01）
- 初稿。

---

## 1. 通用约定
| 项 | 约定 |
|---|---|
| 基础路径 | `/api/v1`；JSON，`Content-Type: application/json; charset=utf-8`（文件上传为 `multipart/form-data`；SSE 为 `text/event-stream`） |
| 命名与大小写 | **JSON 键**一律 `snake_case`。**枚举取值**分两类：① 普通枚举值小写 `snake_case`（如 `entry_ok`、`uptrend`），少数取值本身是固定记号的除外（`bar_freq` 的 `1m`/`d`/`w`）；② **码类取值**用大写 `UPPER_SNAKE`：`error.code`（§4）、`reason_code`（§6.1）、导入提示码 `IMPORT_*`（§4.1）、晋级门禁 `gate`（`G1`–`G7`），以及仅用于展示的风控编号 `RC1`–`RC6`。判断方法：取值是“码”（会出现在日志、文档、CI 检查里被检索）则大写，是“状态/类别”则小写。错误码、原因码、导入提示码三个命名空间**不得重名**（CI 检查，§9） |
| ID | UUID v4 字符串（`string(uuid)`） |
| 时间 | `string(datetime)`：ISO 8601 含时区，服务端统一输出 `+08:00`；日期 `string(date)` = `YYYY-MM-DD`（交易日按北京时间） |
| 金额/价格/数量/比例 | **十进制字符串** `string(decimal)`，如 `"10.25"`、`"0.1530"`；不用 JSON number，避免浮点误差。百分比字段名以 `_pct` 结尾，值为百分数（`"3.20"` = 3.20%） |
| 分数/置信度数值 | `number`。**所有名为 `score` 的字段都是 0–100 整数**（四舍五入；观点未知时为 `null`）；引擎内部的 0–1 小数不对外。`confidence.value` 为 0–1、两位小数。这些是规则计算结果，不是金额 |
| 证券代码 | `string`：`{6位代码}.{SH\|SZ\|BJ}`；指数、ETF 同格式（如 `000300.SH`、`510300.SH`；ETF 为 v0.2.8） |
| 证券简称 | **凡含 `security_code` 的对象都同时带 `name: string`**（证券简称）。不可变对象（建议、日报、信号）里的 `name` 是生成当时的简称，可能与当前简称不同；代码查不到简称时为代码本身，不为 `null`。**例外（v0.2.7 写明）**：`security_code` 本身允许为 `null` 的对象（`StrategyInstance`、`TodayAlert`、`RiskEvent`、`/today.risk_flags` 元素等），`security_code` 为 `null` 时 `name` 也为 `null` |
| 条件请求 | 标注“ETag”的 `GET` 返回弱 ETag（`W/"…"`）；客户端带 `If-None-Match` 且内容未变 → `304`（无响应体）。头 `Cache-Control: private, no-cache`（例外：`/securities/*` 一律 `private, no-store`，v0.2.9 #41） |
| 可空 | 标记为 `T \| null` 的字段总是出现，值可为 `null`；未标记的字段必有值 |
| 版本 | 破坏性变更走 `/api/v2`；新增字段不算破坏性，客户端须忽略未知字段 |
| 请求追踪 | 响应头 `X-Request-Id`；客户端可传入同名头 |
| 幂等 | 创建类 `POST` 支持 `Idempotency-Key` 头（24 小时内同键同体返回首次结果，同键异体 → `409 IDEMPOTENCY_CONFLICT`） |

### 1.1 数据状态（凡含行情/因子/建议的响应都带）
```json
{"data_status": "fresh", "data_as_of": "2026-11-02T10:31:00+08:00", "gaps": [{"key": "news", "reason": "no_source", "message": "本产品不提供新闻资讯"}]}
```
- `data_status: "fresh" | "stale" | "pending" | "partial" | "unavailable"`：`stale`=超过刷新间隔 ×2 未更新（0A.3）；`pending`=已投递按需拉取任务；`partial`=部分维度缺数据；`unavailable`=上游不可用，或本人数据证书不可用且从未取到数据（v0.2.6）。本人证书不可用时行情接口不报错，只把 `data_status` 置为 `stale`/`unavailable` 并在 `gaps` 中给出 `data_licence_unavailable`；**不会用他人证书的数据补齐**。
- `gaps[]: {key: string, reason: "no_source"|"not_yet_published"|"upstream_error"|"quota_deferred"|"user_input_missing"|"data_licence_unavailable"|"not_applicable", message: string}`（`not_applicable`：该证券类型没有此类数据，如 ETF 的财务、资金流、因子、公告；v0.2.8）。
- **混合来源响应（v0.2.7）**：一个响应同时含“证券公开主数据”（全站一份，范围见 v0.2.7 #19：代码、简称、拼音、曾用名、交易所、板块、上市日、状态、风险警示）和“本人证书取到的麦蕊数据”时，`data_status` 只按证书部分判定。证书部分从未取到时为 `partial`（主数据仍返回），`gaps` 给出 `data_licence_unavailable` 或 `not_yet_published`，被影响的字段为 `null`；证书部分全部可用时按 0A.3 规则判定。**个股与板块类读接口**（§7.3 中 v0.2.7 新增的端点、`/securities/{code}/bars`、`/quotes`）**不返回** `409 DATA_LICENCE_UNAVAILABLE`；该错误码仍只用于需要触发拉取的写操作。
- **A-12 终裁：T-A53 时点口径的全站外延（收敛 T-A160/#72）**：T-A53「最早非空值、全空 null」适用于所有响应级 DataStatusBlock；键必须出现，值为 `string(datetime) | null`，包括快照对象中的该块。只计算实际参与返回内容的数据时点；有旧缓存就保留旧时点，不以当前时刻刷新，不因部分缺失清空仍可用的时点。SecurityProfile 的公开/本人证书时点取并集见 §5.1；Evidence.data_as_of 与 §8 SSE quote 不属于本块，按各自非空规则。此处为语义外延，不将 HTTP /quotes 逐项结构机械套到 SSE 顶层。
- **缓存未命中（v0.2.7）**：本人证书下没有缓存时返回 `200`，`data_status:"pending"`，按本人证书入队（P1）；当日该证书配额不足时 `gaps` 加 `{reason:"quota_deferred"}`，不报 429。
- **证书范围（v0.2.7）**：除证券公开主数据外，所有字段都只来自本人证书取到的数据；**不会用他人证书的数据补齐**（与 v0.2.6 #1 一致）。公开主数据的确切来源（交易所公开列表，或用管理员本人证书拉取）【待 Q2 / T-A04 补测】；确认前只用交易所公开列表，不得用他人（含管理员）的证书为其他用户取数。

### 1.2 分页（游标）
- 请求：`?limit=`（默认 50，最大 200）`&cursor=`（不透明字符串）。
- 响应：`{"items": [...], "next_cursor": "string | null"}`；`next_cursor=null` 表示最后一页。排序固定且稳定（默认 `created_at desc, id desc`），各接口另注明。
- 少量小集合接口（枚举、设置）直接返回数组或对象，不分页（注明"不分页"）。
- 游标不透明（v0.2.9 内，T-B46/T-B47 裁定）：服务端签名，客户端不得解析或拼接；OpenAPI 只声明 `string`（≤2048 字符），有效性无法用 schema 表达。伪造、篡改、过期，或与本次筛选、排序参数不一致的游标一律 `400 INVALID_CURSOR`。契约测试（schemathesis）对 `cursor` 参数的 `400 INVALID_CURSOR` 按预期处理。

### 1.3 认证与安全
- **会话 Cookie** `sid`：`HttpOnly; Secure; SameSite=Lax; Path=/`；服务端会话存 Redis，空闲 7 天滑动过期、自登录起 30 天绝对过期（均可配置，plan 6.1 `config/auth.yaml` `session.*`）；V1 不提供“记住我”。登录与修改密码时轮换会话（新 `sid` 与新 `csrf_token`，旧会话作废）；改角色、禁用、驳回、管理员重置密码时吊销该用户全部会话。
- **CSRF**：登录成功后响应体与 Cookie `csrf_token`（非 HttpOnly）给出令牌；所有 `POST/PUT/PATCH/DELETE` 必须带头 `X-CSRF-Token`，缺失或不符 → `403 CSRF_FAILED`。响应体 `csrf_token` 与 Cookie 值相同，以 Cookie 为准（双提交：服务端用常数时间比较请求头、Cookie 与会话内令牌，三者须一致）；响应体值只供读不到 Cookie 的客户端兜底（v0.2.4 #13）。
- **CSRF 登录前白名单（v0.2.9 #30，csrf-frontend 遗留裁定）**：只有 `POST /auth/login`、`POST /auth/register` 不校验 `X-CSRF-Token`（调用时既没有会话，也没有 `csrf_token` Cookie）；白名单以本条为准，以后新增的端点一律不在白名单内。其余所有 `POST/PUT/PATCH/DELETE`（含 `/auth/logout`、`/auth/password`、`POST /imports` 等 multipart 上传、`/admin/*`）都按上条校验；`GET`/`HEAD`/`OPTIONS` 不校验。白名单内两个端点带了 `X-CSRF-Token` 头或 `csrf_token` Cookie 时忽略，不报错；请求带 `Origin` 头且不是本站源（部署配置的站点地址）→ `403 CSRF_FAILED`（防登录 CSRF），不带 `Origin` 的非浏览器客户端照常处理（plan 第 9 节问题 84）。白名单外的写请求没有有效会话 → `401 AUTH_REQUIRED`，不是 `403 CSRF_FAILED`。前端收到 `403 CSRF_FAILED` 时提示刷新页面，不自动重试。
- **判定顺序（v0.2.9 #30）**：从先到后——① 网关与全局上限（都在路由之前）：请求行（URI，含查询串）超过网关上限 → `414 URI_TOO_LONG`（nginx 返回，最先判定，后端收不到该请求；v0.2.9 内，T-T 复测补 414）；请求体超过全局上限 → `413 PAYLOAD_TOO_LARGE`（中间件，路由之前）；② 路由：路径不存在 → `404 NOT_FOUND`，方法不允许 → `405`；③ 认证：`/admin/*` 不是已登录的 `role=admin` → `404`（含缺 CSRF 的请求）；其他 🔒 端点没有有效会话 → `401 AUTH_REQUIRED`，账号非 `approved` → `403 ACCOUNT_NOT_APPROVED`；④ 写请求的 CSRF 不通过 → `403 CSRF_FAILED`（白名单端点改为上条的 `Origin` 校验）；⑤ 功能开关：`POST /auth/register` 在 `closed`（及邀请功能未上线的 `invite`）时 → `503 REGISTRATION_CLOSED`，先于该端点的 `Origin` 校验与请求体解析（#16）；无请求体的 `POST /me/data-licence/test` 的 `503 MAINTENANCE` 在此判断；⑥ 请求体与参数格式 → `400 VALIDATION_ERROR`（含非法 JSON）；有请求体的 `PUT`/`PATCH /me/data-licence` 的 `503 MAINTENANCE` 在此之后（#18 不变）；⑦ 之后是各端点自身的判断（资源归属 `404` → 状态 `409` → 业务 `409`/`422`/`503` 等），以各端点说明为准。框架的请求体解析不得先于 ③④：未登录发非法 JSON → `401`，已登录缺 CSRF 发非法 JSON → `403 CSRF_FAILED`。`429 RATE_LIMITED` 的位置保持各端点原有规定；部署层返回的全局维护页不在本顺序内。
- **权限**：未登录 → `401 AUTH_REQUIRED`；账号非 `approved` → `403 ACCOUNT_NOT_APPROVED`（以上两条均不适用于 `/admin/*`）；`/admin/*`：不是已登录的 `role=admin` 时（含未登录）一律 `404 NOT_FOUND`，与不存在的路径无法区分（不泄露管理端存在性；先于本节其他校验，v0.2.1）。用户只能访问自己的资源，访问他人资源一律 `404 NOT_FOUND`（不泄露存在性）。
- **合规门槛**：**无**（v0.2.5 作废原有的测评与同意门槛，`CONSENT_REQUIRED` 不再存在）。标 ⚖ 的建议类接口（`/today`、`/suggestions*`、`/daily-reports*`、`/signals*`、`/candidate-signals*`、`/plan-drafts*`、`/candidates*`（v0.2.9 T-A11）、`/stream` 中标 ⚖ 的事件）只表示“输出是规则信号”：前端须在其旁固定展示免责提示（`docs/strategies/compliance/disclaimer.md`：“本工具仅供个人研究参考，不构成投资建议。候选信号由规则自动生成，数据可能延迟或出错，盈亏自负。”），服务端不拦截。`POST /imports`、`POST /trades` 也不需要单独同意。
- **限速**：超限 `429 RATE_LIMITED`，头 `Retry-After`（秒）。
- **`/admin/*` 不进 openapi（v0.2.8，架构师裁定）**：所有 `/admin/*` 路由以 `include_in_schema=False` 注册，公开的 `openapi.json` 与 `/docs` 中没有它们（与上面的 404 规则一致，不向非管理员暴露管理端路径）。管理端的请求和响应结构**以本契约为准**（§5.1 `AdminDataLicence`、`IngestLicenceStatus` 等，§7.9），由契约测试逐接口校验（§9），不得依赖 `openapi.json` 生成管理端类型；前端管理页类型按本契约手写。“`openapi.json` 与本文不一致时改代码”只适用于非 `/admin/*` 路径。
- 敏感字段一律掩码输出（如 `shareholder_code_masked: "A00****000"` 为格式示意），任何接口都不返回原始股东代码、资金账号或原始上传文件内容。

---

## 2. 统一错误格式
```json
{"error": {"code": "VALIDATION_ERROR", "message": "参数校验失败", "details": {"fields": [{"field": "limit", "issue": "must be <= 200"}]}, "request_id": "req_9f8e7d"}}
```
| 字段 | 类型 | 说明 |
|---|---|---|
| `error.code` | string | 机器可读错误码（第 4 节），稳定 |
| `error.message` | string | 中文可读信息，可变，客户端不得据此判断逻辑 |
| `error.details` | object \| null | 结构化细节，按错误码约定 |
| `error.request_id` | string | 与响应头 `X-Request-Id` 一致 |

---

## 3. 枚举（`GET /meta/enums` 返回同一份，不分页）
| 枚举 | 取值 |
|---|---|
| `account_status` | `pending` `approved` `rejected` `disabled` |
| `role` | `user` `admin` |
| `epistemic_type` | `fact` `estimate` `hypothesis` `execution` |
| `horizon` | `intraday_t` `short` `swing` `long` |
| `dimension` | `technical` `capital` `fundamental` `sentiment` `sector_market` `news` |
| `dimension_view` | `bullish` `bearish` `neutral` `unknown` |
| `rule_role` | `entry` `hold` `weakening` `exit` `filter` `veto` `counter` `invalidation` |
| `action` | `buy` `add` `hold` `reduce` `sell` `wait` |
| `t_leg` | `sell_first` `buy_first` （仅 `intraday_t`） |
| `confidence_level` | `high` `medium` `low` |
| `consensus_status` | `unanimous` `divergent` `single` `none` |
| `strategy_eval_state` | `entry_ok` `not_triggered` `hold_ok` `weakening` `exit_signal` `vetoed` `insufficient_data`（单个模板对单只证券的评估结果；`not_triggered`=数据完整、无否决、核心入场条件未全部满足 → 映射为 `wait`，不生成候选信号） |
| `executability_status` | `executable` `blocked` `not_applicable`（至少一个候选信号无未解除原因 → `executable`；全部被阻断 → `blocked`；没有候选信号 → `not_applicable`） |
| `suggestion_origin` | `daily_batch` `intraday_event` `manual_refresh` |
| `suggestion_status` | `active` `superseded` `invalidated` `expired` |
| `risk_control` | `stop_take`(RC1) `position_cap`(RC2) `total_exposure`(RC3) `sector_concentration`(RC4) `loss_streak_drawdown`(RC5) `plan_violation`(RC6) |
| `risk_level` | `info` `warning` `critical`（只用于 `RiskFlag.level`） |
| `card_risk_level` | `normal` `high`（L1 卡片的策略风险等级，与 `risk_level` 无关；`high` 的卡片在晋级和展示时附加风险提示；手动启用**不需要确认**，前端在启用开关旁固定展示风险说明，v0.2.6 T006e） |
| `market_regime` | `uptrend` `range` `downtrend` |
| `signal_kind` | `rule_flip`（某条规则由不满足变满足或反之） `breakout`（突破区间上沿） `breakdown`（跌破区间下沿） `vwap_deviation`（偏离分时均价） `volume_spike`（放量） `limit_up_touch` `limit_down_touch` `limit_open`（涨跌停打开） `invalidation_near`（接近失效条件或止损位） `stop_hit`（触及止损/止盈价位，只提示） `suspended`（停牌/复牌） `data_stale`（行情变旧） |
| `market_session` | `non_trading_day` `pre_open` `call_auction` `morning` `lunch_break` `afternoon` `closing_auction` `closed`（北京时间；按交易日历与板块规则计算） |
| `bar_freq` | `1m` `d` `w` |
| `bar_adjust` | `none` `qfq` `hfq`（`1m` 只支持 `none`） |
| `registration_mode` | `closed`（V1 默认）`invite` `open`（保留，V1 不用） |
| `notification_target_type` | `suggestion` `candidate_signal` `plan_draft` `plan` `daily_report` `import_batch` `reconciliation` `strategy_version` `none` |
| `notification_ref_type` | `signal` `plan_condition`（§7.11.4 T-A31 既有枚举同步登记，`refs[].type`） |
| `notification_kind` | `suggestion_change` `invalidation` `daily_report` `alert` `import` `system` `reason_released` `plan_draft_ready` `plan_triggered` `strategy_health` `data_licence` |
| `severity` | `info` `attention` `important` |
| `channel` | `in_app` `email` `wecom_app`（预留） |
| `data_status` | `fresh` `stale` `pending` `partial` `unavailable`（含义见 1.1） |
| `gap_reason` | `no_source` `not_yet_published` `upstream_error` `quota_deferred` `user_input_missing` `data_licence_unavailable` `not_applicable`（`gaps[].reason`，1.1；v0.2.6 加 `data_licence_unavailable`；v0.2.8 加 `not_applicable`） |
| `data_provider` | `mairui` `user_import` `user_input` `system` `exchange`（`Evidence.provider` 与 `ProviderRef.provider`；`system` = 系统计算；v0.2.3 起 `Evidence.provider` 只用此枚举，没有 `local`；v0.2.7 加 `exchange` = 沪深北交易所公开证券列表（T007），只用于证券公开主数据，且只在 Q2 / T-A04 确认来源为交易所公开列表时使用；若确认改由管理员本人证书拉取，则这些字段的 `provider` 为 `mairui`） |
| `source_kind` | `market_data` `disclosure` `user_input` `system_calc`（证据来源类别，plan 3.1） |
| `trade_side` | `buy` `sell` |
| `import_status` | `uploaded` `parsing` `previewed` `committed` `failed` `discarded` `reverted`（v0.2：`preview_ready`→`previewed`，`confirmed`→`committed`） |
| `import_severity` | `error` `warning` |
| `import_scope` | `file` `row` `field` |
| `import_row_status` | `ok` `warning` `error` `skipped` |
| `dedup_status` | `new` `duplicate_in_db` `duplicate_in_file` `possible_duplicate_of_manual` |
| `reconciliation_status` | `matched` `diff` `not_imported` |
| `reconciliation_item_kind` | `quantity_mismatch` `missing_in_broker` `missing_in_ours` `cost_differs` `cash_gap` `cash_chain_break` |
| `card_completeness` | `draft` `documented` `runnable_candidate` `promoted` `retired` |
| `lifecycle` | `draft` `simulating` `published` `observing` `retired` |
| `instance_status` | `proposed` `active` `paused` `archived` |
| `candidate_signal_state` | `open` `drafted` `blocked` `released` `confirmed` `dismissed` `expired` `invalidated` `superseded` |
| `candidate_signal_event_cause` | `executability_check` `reason_released` `user` `expiry` `invalidation` `supersede`（v0.2.9；`/candidate-signals/{id}/events` 的 `cause`；确认草案与用户忽略都为 `user`；v0.2.9 #30：信号创建事件为 `executability_check`，→`drafted` 为 `user`） |
| `research_candidate_status` | `researching` `watching` `dropped` `planned`（v0.2.9 T-A11；研究候选状态，§6.0；`planned` 只由系统写入） |
| `research_candidate_origin` | `strategy_screen` `suggestion` `manual` `from_stock`（v0.2.9 T-A11；与库表 CHECK 一致；本版 `POST /candidates` 不接受 `strategy_screen`，§7.7A） |
| `candidate_decision` | `continue` `watch` `drop`（v0.2.9 T-A11；分别把研究候选状态置为 `researching`、`watching`、`dropped`） |
| `reason_code` | 见 6.1（22 个；v0.2.5 删 `PROFILE_OR_CONSENT_MISSING`） |
| `reason_status` | `active` `released` `obsolete` |
| `check_on` | `tick` `daily_close` `schedule` `holding_change` `cash_update` `import` `plan_change` `user_action` |
| `release_kind` | `expr` `time` `event` `user_action` |
| `plan_draft_status` | `pending` `confirmed` `discarded` `expired` `stale` |
| `plan_origin` | `manual` `plan_draft` |
| `restriction_kind` | `blocklist` `cooling_off` `mute` |
| `suggestion_user_action` | `viewed` `dismissed` `draft_requested` `draft_confirmed` `reason_manually_released` `acted_trade_linked`（没有 `converted_to_plan`） |
| `feature_status` | `declared` `verified_doc` `verified_live` `gap` `deprecated` |
| `gate` | `G1` `G2` `G3` `G4` `G5` `G6` `G7`（plan.md 2.5.13 的晋级门禁；**不同于** `CandidateSignal.gate_results[].gate` 中的运行时闸门名） |
| `llm_task` | `suggestion_rationale` `daily_report_stock` `daily_report_summary` `strategy_divergence` `announcement_title_digest` |
| `health_status` | `ok` `degraded` `down`（`/health/ready` 的 `status`） |
| `component_health` | `ok` `error`（`/health/ready` 的 `db`、`redis`） |
| `ingest_health` | `ok` `stale` `paused` `unknown`（`unknown` = Redis 不可用，无法判断） |
| `data_licence_status` | `not_set` `pending_verification` `active` `invalid` `expired` `quota_exceeded` `ip_limited` `paused_by_admin`（v0.2.6，plan 2.1B） |
| `data_licence_tier` | `free` `trial` `monthly` `annual` `diamond` `other`（v0.2.6；用户自报的麦蕊证书档位，决定默认每分钟上限） |
| `security_type` | `stock` `cdr` `etf` `index`（v0.2.7；v0.2.8 加 `etf`，见 v0.2.7 未决 Q3、plan 第 9 节问题 53；可转债本版不收录） |
| `board` | `main` `chinext` `star` `bse`（v0.2.7） |
| `listing_status` | `listed` `delisting_period` `delisted` `missing_from_list`（v0.2.7；`missing_from_list`=麦蕊或历史数据中有、但交易所当前列表中找不到，T007 §5；**停牌不是上市状态**，用 `SecurityProfile.suspended` 表示） |
| `security_risk_flag` | `st` `star_st` `delisting`（v0.2.7；同时命中时取最高一项：`delisting` > `star_st` > `st`。含义（v0.2.9 内，T-O11 评审裁定）：`st` = 其他风险警示（ST），`star_st` = 退市风险警示（*ST），`delisting` = 证券简称带“退”的退市整理标记；退市整理期这一上市状态另用 `listing_status=delisting_period` 表示） |
| `security_match_kind` | `code_exact` `name_exact` `initials_exact` `code_prefix` `name_prefix` `initials_prefix` `name_contains` `former_name` `former_code` `fuzzy`（v0.2.7；按此顺序即排序层级） |
| `security_reconciliation_kind` | `vendor_stale_listed` `vendor_unknown` `quote_missing` `quote_conflict` `field_mismatch`（v0.2.9 内，T-A04；证券主数据对账差异，含义见 plan 4.6.4；只出现在 `/admin/securities/reconciliation`） |
| `security_reconciliation_source` | `mairui_lists` `mairui_real_all` `cninfo` `akshare`（v0.2.9 内，T-A04；与交易所主数据比对的一方；`mairui_*` 按证书比对，plan 4.6.4） |
| `report_period` | `q1` `h1` `q3` `fy`（v0.2.7） |
| `factor_category` | 麦蕊因子的 11 个分类，键名按 T003 的分类表定稿（v0.2.7）【待 T003 补测：分类中文名与键名对照】 |
| `announcement_category` | `periodic_report` `other`（v0.2.7；麦蕊只区分定期报告，原始分类放在 `category_raw`） |
| `sector_kind` | `industry` `concept`（v0.2.7） |
| `industry_taxonomy` | `sw_l1` `sw_l2` `csrc`（v0.2.7；板块资金的 `industry` 对应哪套分类【待 T003 补测】） |
| `instance_origin` | `classifier` `user` `system`（v0.2.7） |
| `instance_event_kind` | `created` `confirmed` `paused` `resumed` `params_changed` `archived`（v0.2.7） |
| `instance_sort` | `created_at_desc`（默认） `updated_at_desc` `strategy_name_asc`（v0.2.7） |
| `sector_sort` | `main_net_desc`（默认） `main_net_asc` `change_pct_desc` `change_pct_asc`（v0.2.7） |
| `alert_origin` | `plan_condition` `holding_event` `user_custom`（v0.2.7；plan 3.3 `alert_rules.origin`） |
| `alert_status` | `new` `read` `checked` `acted` `dismissed`（v0.2.7；plan 3.3 `alerts.status`） |
| `plan_condition_kind` | `trigger` `invalidation`（v0.2.7；plan 3.3 `plan_conditions.kind`） |
| `plan_status` | `active` `triggered` `done` `cancelled`（v0.2.9 #30，plan 第 9 节问题 59、80；操作计划状态，§7.7B；`done`、`cancelled` 为终态，只由用户经 `/plans/{id}/close` 写入；系统只做 `active`→`triggered`，不自动关闭计划） |
| `plan_condition_type` | `price_above` `price_below` `pct_change` `indicator` `event` `date` `custom`（v0.2.9 #30；plan 3.3 `plan_conditions.type`；本版写入只接受 `price_above` `price_below` `pct_change` `date` `custom`，`indicator`、`event` → `400 VALIDATION_ERROR{issue:"not_supported"}`（plan 第 9 节问题 83）；`custom` 不自动判定） |
| `data_gap_scope` | `user` `account` `security` `market`（v0.2.7） |

---

## 4. 错误码表
| HTTP | code | 场景 | `details` |
|---|---|---|---|
| 400 | `VALIDATION_ERROR` | 参数/请求体校验失败 | `{fields:[{field, issue}]}` |
| 400 | `INVALID_CURSOR` | 游标无效或过期；v0.2.7 写明：游标与本次请求的筛选或排序参数不一致时也返回此码 | — |
| 401 | `AUTH_REQUIRED` | 未登录或会话过期 | — |
| 401 | `INVALID_CREDENTIALS` | 用户名或密码错误（不区分哪一项） | — |
| 403 | `ACCOUNT_NOT_APPROVED` | 账号待审核/已驳回/已禁用 | `{status}` |
| 403 | `ACCOUNT_LOCKED` | 连续失败临时锁定 | `{retry_after_s}` |
| 403 | `CSRF_FAILED` | CSRF 令牌缺失/不符 | — |
| 403 | `FORBIDDEN` | 角色不足（保留；`/admin/*` 不使用，一律 404，见 §1.3） | — |
| 403 | `ENTITLEMENT_LIMIT_REACHED` | 超出套餐权益上限（自选数、重点关注数、导入次数、LLM 解释次数等） | `{key, limit, current}` |
| 404 | `NOT_FOUND` | 资源不存在或不属于当前用户；v0.2.7 起，用北交所旧代码访问 `/securities/{code}*` 时也返回此码并带 `superseded_by`（新代码），其余情况无 `details` | `{superseded_by: string}`（只在北交所旧代码时） |
| 405 | `METHOD_NOT_ALLOWED` | 路径存在但方法不支持；响应头 `Allow`。非管理员（含未登录）访问 `/admin/*` 一律按 `404 NOT_FOUND` 返回，不带 `Allow` 头 | `{allowed: string[]}` |
| 413 | `PAYLOAD_TOO_LARGE` | 请求体超过网关/框架上限（v0.2.3 补充）；应用层文件超限仍用 `422 IMPORT_FILE_ERRORS`。v0.2.9 内写明（评审 f72b8c7 裁定）：这是全局规则，由中间件在路由之前判断，先于任何接口自身的判断（含注册关闭时的 `503 REGISTRATION_CLOSED`） | `{max_bytes}`（= plan 6.1 `imports.max_request_bytes`；nginx 返回时可省略） |
| 414 | `URI_TOO_LONG` | v0.2.9 内（T-T 复测补 414）：请求行（URI，含查询串）超过网关上限。**级别**：网关——由 nginx 在任何 location 与路由之前返回，后端收不到该请求，也从不产生此码；**范围**：全局，所有路径与方法（含 `/admin/*`、未登录请求；判定顺序见 §1.3 ①，先于 413）；`message` 固定为“请求地址过长”；信封与 413 同形（`error.code`、`message`、`details`、`request_id`），响应头带 `X-Request-Id`、`Cache-Control: no-store`；名称与状态码与后端 OpenAPI（6670b10）一致 | `{max_bytes}`（= nginx `large_client_header_buffers` 单个缓冲区大小，当前 8192） |
| 409 | `CONFLICT` | 唯一约束冲突（如用户名已存在；v0.2.9 T-A11：同一证券已有进行中的研究候选） | `{field}`；研究候选重复时另带 `existing_id: uuid`（本人已有的那条候选） |
| 409 | `IDEMPOTENCY_CONFLICT` | 同一幂等键、不同请求体 | — |
| 409 | `VERSION_CONFLICT` | 乐观锁版本号不符（`If-Match`/`base_version_no`） | `{current_version_no}`；测评时为 `{current_version: string}` |
| 409 | `IMMUTABLE_RESOURCE` | 试图修改不可变对象（建议、已发布策略版本、日报、成交原记录、已归档的策略实例（v0.2.7）） | — |
| 409 | `DATA_LICENCE_IN_USE` | 该证书已绑定到另一个账号（一张证书只能由一位用户使用；v0.2.6） | — |
| 409 | `DATA_LICENCE_NOT_SET` | 本人尚未设置数据证书（PATCH 或测试证书时） | — |
| 409 | `DATA_LICENCE_UNAVAILABLE` | 需要触发拉取的写操作（如手动刷新、按需拉取）而本人证书不可用；读接口不返回此错误，改用 `data_status` + `gaps` | `{status: data_licence_status}` |
| 422 | `IMPORT_FILE_ERRORS` | 文件级 error：上传阶段（空文件、过大、类型不符、行数超限，此时**不创建批次**），或确认时批次仍有文件级 error | `{findings: ImportFinding[]}`（code 见 §4.1） |
| 422 | `IMPORT_ROW_ERRORS` | `mode=all` 确认时仍有 error 行 | `{error_rows: int}` |
| 422 | `IMPORT_WARNINGS_UNACKNOWLEDGED` | 有未处理的 `needs_action` warning，且 `acknowledge_warnings≠true` | `{codes: string[], count: int}` |
| 422 | `IMPORT_NOTHING_TO_COMMIT` | 确认时没有可写入的行（只有表头、全部重复、全部错误等） | — |
| 422 | `STRATEGY_INVALID_CONFIG` | 策略配置校验失败（未知因子、表达式语法、参数越界） | `{errors:[{path, issue}]}` |
| 422 | `STRATEGY_EXPR_FORBIDDEN` | 规则表达式含非白名单字段或运算 | `{rule_id, token}` |
| 409 | `STRATEGY_VERSION_PUBLISHED` | 已发布版本不可修改 | `{version_no}` |
| 403 | `STRATEGY_NOT_OWNED` | 修改内置策略或他人策略（须先复制） | — |
| 422 | `STRATEGY_HORIZON_MISMATCH` | 给股票绑定的策略不支持所选周期 | `{strategy_key, horizons}` |
| 422 | `STRATEGY_SYSTEM_ONLY` | 该策略 `mount_policy=system_only`（如 H-01），只能由系统挂载，用户不能创建实例（plan 2.5.14 T-R15 裁定第 2 条） | `{strategy_key}` |
| 422 | `RISK_CONTROL_INVALID_PARAMS` | 风控阈值越界 | `{control, fields}` |
| 409 | `SUGGESTION_SUPERSEDED` | 对已被取代的建议执行动作 | `{current_id}` |
| 409 | `SUGGESTION_REFRESH_TOO_FREQUENT` | 手动刷新过于频繁（受权益 `realtime.min_notify_interval_s` 约束） | `{retry_after_s}` |
| 422 | `SUGGESTION_INSUFFICIENT_DATA` | 必备字段缺失，未生成建议（0A.2 缺一不可） | `{missing:[string]}` |
| 409 | `INVALID_STATE_TRANSITION` | 状态机不允许的跃迁（第 6.0 节）。`allowed` 是**用户从 `from` 出发、通过接口可以到达的目标状态**（不含系统专用转换），按该对象状态枚举的顺序排列；没有可达状态时为 `[]`（v0.2.7 写明） | `{from, to, allowed}` |
| 409 | `STRATEGY_VERSION_NOT_RUNNABLE` | 模板版本不是 `published`/`observing`（例如 simulating、retired） | `{lifecycle}` |
| 422 | `STRATEGY_PARAM_OUT_OF_RANGE` | 参数覆盖超出 param_schema 的 min/max/choices | `{param, min, max, choices}` |
| 422 | `INSTANCE_SCOPE_INVALID` | 实例作用范围不合法（例如 security 范围缺少代码，或代码不在账户/自选中；v0.2.8：证券为 ETF，策略不对 ETF 运行；v0.2.8 补充：代码不在证券主数据中） | `{scope}`；ETF 时为 `{scope, security_code, security_type: "etf", issue: "security_type_not_supported"}`（v0.2.8）；代码不在证券主数据中时为 `{scope, security_code, issue: "unknown_security"}`（v0.2.8 补充） |
| 422 | `PROMOTION_GATES_NOT_MET` | 晋级或上线时门禁未通过 | `{gates:[{gate, result}]}` |
| 422 | `PROMOTION_WARN_UNACKNOWLEDGED` | 批准时有 `warn` 门禁未列入 `ack_warn_gates`（T-A18） | `{gates: string[]}` |
| 409 | `PROMOTION_STALE` | 审核绑定的版本或内容哈希已变化（卡出新版本或内容改动），审核作废（T-A18） | `{current_version_id}` |
| 401 | `REAUTH_FAILED` | G7 决定或晋级时重新输入的密码不对（T-A20） | — |
| 403 | `HUMAN_SESSION_REQUIRED` | G7 决定或晋级未经浏览器交互登录会话（API token、服务账号、代理凭据，T-A18） | — |
| 422 | `CARD_IMPORT_INVALID` | 导入器校验研究员文档失败（plan.md 2.5.14，只在管理端/CI 出现） | `{file, block, errors:[{path, issue}]}` |
| 422 | `COMPLIANCE_LINT_FAILED` | 用户可见文案含禁用词 | `{terms}` |
| 500 | `SIGNAL_NOT_EXPLAINABLE` | 内部：信号缺少可解释字段，已拒绝写入（只出现在日志和管理端，不返回给普通用户） | `{missing}` |
| 422 | `PLAN_REQUIRES_EXPLAINABLE_SIGNAL` | 草案引用的信号没有通过的规则引用（只有模型输出） | `{signal_ids}` |
| 409 | `SIGNAL_NOT_EXECUTABLE` | 信号仍有生效的不可执行原因 | `{reason_ids}` |
| 409 | `PLAN_DRAFT_STALE` | 草案已过期，或依据的数据/持仓已变化 | `{status}` |
| 422 | `CHECKLIST_INCOMPLETE` | 判断清单必答项未答 | `{missing}` |
| 422 | `RISK_ACK_REQUIRED` | 未确认风险提示 | — |
| 422 | `DEVIATION_ACK_REQUIRED` | 数量或价格超出草案区间，且未确认偏离 | `{fields}` |
| 409 | `REASON_NOT_MANUALLY_RELEASABLE` | 该原因可由系统判断，不能手动解除 | `{code}` |
| 503 | `REGISTRATION_CLOSED` | 注册已关闭（`registration_mode=closed`，V1 默认） | — |
| 503 | `FRESH_DATA_REQUIRED` | （v0.1 名为 `DATA_STALE`）只用于**明确要求最新数据**的操作（例如手动刷新建议 `manual_refresh`），而行情已陈旧；读接口一律返回 200 加 `data_status`，不报此错。与原因码 `DATA_STALE` 的区别：原因码挂在候选信号上、表示“这个信号因数据陈旧暂不可执行”，随数据恢复自动解除；本错误码表示“这次请求没有执行” | `{data_as_of}` |
| 503 | `CALENDAR_NOT_COVERED` | 请求日期不在受审交易日历的覆盖范围内（T-A12），不按工作日猜测 | `{date, coverage_start, coverage_end}` |
| 503 | `INGEST_PAUSED` | 采集服务被管理员暂停或冷备切换中（只用于需要触发拉取的操作） | — |
| 503 | `LLM_UNAVAILABLE` | 所有 LLM 路由失败（只在显式请求 LLM 时返回；建议本身回落模板，不报错） | `{task}` |
| 429 | `LLM_BUDGET_EXCEEDED` | LLM 日预算用尽 | `{task, budget}` |
| 422 | `LLM_PROVIDER_TEST_FAILED` | 管理员测试连接失败 | `{provider_id, status, message}` |
| 502 | `UPSTREAM_ERROR` | 麦蕊返回错误（已映射，不含 licence） | `{provider:"mairui", upstream_code}` |
| 503 | `UPSTREAM_RATE_LIMITED` | `ingest` 令牌桶耗尽或上游限流，请求已排队（Web 进程不直连麦蕊） | `{retry_after_s}` |
| 503 | `UPSTREAM_UNAVAILABLE` | 上游不可用或证书过期，降级中 | — |
| 429 | `RATE_LIMITED` | 本站限速 | `{retry_after_s}` |
| 500 | `INTERNAL_ERROR` | 未预期错误 | — |
| 503 | `MAINTENANCE` | 维护模式；v0.2.8 补充：证书设置开关关闭（`DATA_LICENCE_SETTINGS_ENABLED=false`，生产默认）时 `PUT`/`PATCH /me/data-licence` 与 `POST /me/data-licence/test` 也返回此码（§7.1；`PUT`/`PATCH` 的请求体格式校验 `400` 先于此码，v0.2.9） | — |

### 4.1 导入提示码（`IMPORT_*`，出现在 `ImportFinding.code`，**不是** HTTP 错误码）
- 共 **46 个**：21 个 `error`（文件级 8、行/字段级 13）+ 25 个 `warning`（文件级 10、行/字段级 15）。`error` 阻止写入该文件或该行；`warning` 不阻止，`needs_action=true` 的需逐项处理或确认时统一接受默认处理。
- 对账差异**不是**提示码：6 种 `reconciliation_item_kind` 只出现在 `/reconciliation`。`IMPORT_CASH_CHAIN_BREAK`（单文件内逐行）与对账的 `cash_chain_break`（汇总结论）并存。
- 判定顺序、截断/“0 视为缺失”/撤单等规则见 plan.md 3.5A-1；本表与 plan.md 3.5A-1 的表由同一份数据生成，CI 比对两处逐行一致（§9）。消息模板中的 `{…}` 是 `params` 的键；股东代码、资金账号在 `params` 和 `message` 中一律先掩码。

| # | code | 级别 | 范围 | 消息模板 | 处理与是否可覆盖 | 测试夹具 / 提示 |
|---|---|---|---|---|---|---|
| 1 | `IMPORT_EMPTY_FILE` | error | file | 文件为空（0 字节或只有空白字符） | 不可覆盖；上传时即拒绝（`422 IMPORT_FILE_ERRORS`，不创建批次） | `empty.txt`；编码检测不得抛异常 |
| 2 | `IMPORT_FILE_TOO_LARGE` | error | file | 文件超过 {limit_mb} MB | 不可覆盖；上传时拒绝，不创建批次 | 生成器造 5 MB + 1 字节 |
| 3 | `IMPORT_UNSUPPORTED_FILE_TYPE` | error | file | 只支持 .txt / .csv 文本文件 | 不可覆盖；上传时拒绝（扩展名不符，或 NUL 字节占比 > 1% 视为二进制） | 生成器造含 NUL 的文件 |
| 4 | `IMPORT_TOO_MANY_ROWS` | error | file | 数据行超过 {limit} 行（默认 50,000） | 不可覆盖；请拆分文件 | 生成器 |
| 5 | `IMPORT_ENCODING_UNDETECTED` | error | file | 无法识别文件编码 | 可处理：用户在预览页手选编码后重新解析（`encoding_override`） | 生成器造随机字节文本 |
| 6 | `IMPORT_UNRECOGNIZED_FORMAT` | error | file | 无法识别文件格式，候选解析器：{candidates} | 可处理：用户手选解析器或手工列映射后重新解析 | 生成器造无表头文本 |
| 7 | `IMPORT_REQUIRED_COLUMN_MISSING` | error | file | 缺少必填列：{columns} | 可处理：只能把文件中**已存在**的列映射到缺失字段；**不得推算**（例如用金额 / 数量推价格） | `trades_missing_column.txt` |
| 8 | `IMPORT_ACCOUNT_MISMATCH` | error | file | 文件中的股东代码与所选账户已登记的不一致（按 HMAC 比较） | 可处理：改选账户，或确认“属于本账户的新股东代码”（写审计） | 生成器用两个不同的虚构股东代码 |
| 9 | `IMPORT_ROW_DECODE_ERROR` | error | row | 第 {row_no} 行无法按 {encoding} 解码 | 不可覆盖；**最先判定**。文件末尾不完整的多字节字符也归此码，不得因此整文件拒绝 | `trades_truncated_mid_char.txt` 行 5 |
| 10 | `IMPORT_ROW_TRUNCATED` | error | row | 第 {row_no} 行不完整（文件末行没有换行且列数不足） | 不可覆盖；**优先于** `ROW_COLUMN_MISMATCH`；残缺字段一律不入库 | `trades_truncated_last_line.txt` 行 7 |
| 11 | `IMPORT_ROW_COLUMN_MISMATCH` | error | row | 第 {row_no} 行的列数或列位置与表头不一致 | 不可覆盖（改文件或手动录入）；两种切分策略结果不一致也归此码 | `trades_column_mismatch.txt` 行 6、7 |
| 12 | `IMPORT_REQUIRED_FIELD_EMPTY` | error | field | 必填字段 {field} 为空 | 不可覆盖 | 生成器 |
| 13 | `IMPORT_INVALID_DATE` | error | field | 日期 {value} 无效 | 不可覆盖 | `trades_bad_formats.txt` 行 4 |
| 14 | `IMPORT_FUTURE_DATE` | error | field | 日期 {value} 晚于导入当天 | 不可覆盖 | 生成器 |
| 15 | `IMPORT_INVALID_TIME` | error | field | 时间 {value} 无效 | 不可覆盖；5 位左补零（`93005`→09:30:05）；**4 位及更短的非零值报错，不猜测**；`0` 或空视为缺失、不报错 | `trades_bad_formats.txt` 行 5、6 |
| 16 | `IMPORT_INVALID_NUMBER` | error | field | {field} 的值 {value} 不是有效数字 | 不可覆盖；先做全角转半角、去千分位 | 生成器 |
| 17 | `IMPORT_INVALID_SECURITY_CODE` | error | field | 证券代码 {value} 格式无效（应为 6 位数字） | 不可覆盖；格式有效但主数据中没有的见 `UNKNOWN_SECURITY` | 生成器 |
| 18 | `IMPORT_INVALID_QUANTITY` | error | field | 买卖类数量为 0（且不是撤单或废单） | 不可覆盖 | `trades_sign_and_value_errors.txt` 行 9 |
| 19 | `IMPORT_INVALID_PRICE` | error | field | 价格或成交金额 ≤ 0 | 不可覆盖 | `trades_sign_and_value_errors.txt` 行 7 |
| 20 | `IMPORT_SIDE_QTY_SIGN_MISMATCH` | error | row | 数量符号与买卖方向不一致 | 不可覆盖 | `trades_sign_and_value_errors.txt` 行 5、6 |
| 21 | `IMPORT_AMOUNT_MISMATCH` | error | row | 数量绝对值 × 价格 与成交金额相差 {diff} 元（容差 0.05 元） | 不可覆盖 | `trades_sign_and_value_errors.txt` 行 8 |
| 22 | `IMPORT_DUPLICATE_FILE` | warning | file | 同一文件已于 {imported_at} 导入（批次 {batch_id}） | 仅提示；仍可预览，重复行由去重挡住 | 同一账户重传 `trades_sample.txt` |
| 23 | `IMPORT_NO_DATA_ROWS` | warning | file | 只有表头，没有数据行 | 仅提示；批次照常创建，确认时返回 `422 IMPORT_NOTHING_TO_COMMIT` | `trades_header_only.txt` |
| 24 | `IMPORT_UNKNOWN_COLUMN` | warning | file | 已忽略未识别的列：{columns} | 仅提示；按表头名取列，不按固定列序 | `trades_extra_column.txt` |
| 25 | `IMPORT_FILE_POSSIBLY_TRUNCATED` | warning | file | 文件末尾不完整，可能没有导出完整 | 仅提示；与 `ROW_TRUNCATED` / 末行 `ROW_DECODE_ERROR` 同时出现 | `trades_truncated_last_line.txt`、`trades_truncated_mid_char.txt` |
| 26 | `IMPORT_ENCODING_LOW_CONFIDENCE` | warning | file | 编码判定为 {encoding}，置信度 {confidence} 较低 | 需确认：请核对预览中的中文；可改选编码 | 生成器 |
| 27 | `IMPORT_FORMAT_LOW_CONFIDENCE` | warning | file | 解析器 {parser} 的识别得分 {score} 低于 0.95 | 需确认：请核对列映射 | 生成器（缺少可选列） |
| 28 | `IMPORT_SNAPSHOT_AS_OF_ASSUMED` | warning | file | 快照没有日期，导出时间按 {as_of} 处理 | 需确认：确认或修改导出时间（问题 20） | `positions_sample.txt` |
| 29 | `IMPORT_SNAPSHOT_TOTALS_MISMATCH` | warning | file | 资金摘要与明细合计不一致（券商口径未知） | 仅展示，不判定、不阻止 | `positions_sample.txt` |
| 30 | `IMPORT_SNAPSHOT_SUPERSEDES` | warning | file | 该账户在 {as_of} 已有快照，确认后新版本覆盖旧版本（旧版本保留） | 仅提示 | 同一 as_of 重传 `positions_sample.txt` |
| 31 | `IMPORT_UNSUPPORTED_CURRENCY` | warning | file | 已忽略 {currency} 资金摘要行（只支持人民币） | 仅提示 | `positions_multi_currency.txt` |
| 32 | `IMPORT_NET_AMOUNT_MISMATCH` | warning | row | 发生金额与 ±成交金额 − 费用 相差 {diff} 元（容差 0.02 元） | 仅提示；照常导入，对账时参考 | `trades_sign_and_value_errors.txt` 行 10 |
| 33 | `IMPORT_UNKNOWN_SECURITY` | warning | row | 证券代码 {code} 不在证券主数据中（可能已退市或刚上市） | 需确认：确认后按原代码导入 | 生成器 |
| 34 | `IMPORT_MARKET_INFERRED_CONFLICT` | warning | row | 由代码段推断的市场与股东代码类型不一致 | 需确认；以证券主数据为准 | 生成器 |
| 35 | `IMPORT_NAME_MISMATCH` | warning | field | 证券名称 {name_raw} 与主数据 {name} 不同 | 仅提示；比较前去掉全部空白，名称内部有空格本身不报错 | `trades_column_mismatch.txt` 行 5 + 主数据夹具 |
| 36 | `IMPORT_UNKNOWN_BIZ_TYPE` | warning | row | 业务类型 {biz} 未识别，本行未导入 | 行状态 `skipped`；需确认（可改为手动录入），不猜测 | `trades_non_trade_events.txt` 行 7 |
| 37 | `IMPORT_ROW_CANCELLED` | warning | row | 撤单行，已忽略 | 行状态 `skipped`，无需处理；成交编号 `0` 不参与去重 | `trades_cancelled.txt` 行 5、6 |
| 38 | `IMPORT_ROW_REJECTED` | warning | row | 废单行，已忽略 | 行状态 `skipped`，无需处理 | `trades_cancelled.txt` 行 7 |
| 39 | `IMPORT_DUPLICATE_IN_DB` | warning | row | 与已导入的成交重复（批次 {batch_id}） | 默认 `skipped`；可覆盖：强制作为新成交，须填理由并写审计 | `trades_reimport_overlap.txt` 行 4–6 |
| 40 | `IMPORT_DUPLICATE_IN_FILE` | warning | row | 与本文件第 {other_row_no} 行重复 | 默认 `skipped`；可覆盖（同上）。去重规则 3（无编号）下完全相同的行**不报此码**，按 `#n` 保留为真实的多笔成交 | `trades_duplicates_in_file.txt` 行 7 |
| 41 | `IMPORT_POSSIBLE_DUPLICATE_OF_MANUAL` | warning | row | 可能与手动录入的成交 {trade_id} 是同一笔 | 需选择：跳过导入行（默认）/ 保留导入并作废手动记录 | 生成器 + 先手动录入同一笔 |
| 42 | `IMPORT_MISSING_OPENING_POSITION` | warning | row | 卖出数量超过重建后的持仓，可能缺期初持仓 | 仅提示；建议补录期初持仓 | 生成器 |
| 43 | `IMPORT_CASH_CHAIN_BREAK` | warning | row | 剩余金额链在本行断开，差额 {diff} 元 | 仅提示（日间可能有非成交资金流水） | `trades_duplicates_in_file.txt` 行 8；`trades_reimport_overlap.txt` |
| 44 | `IMPORT_NON_TRADING_DAY` | warning | row | 成交日期 {date} 不是交易日 | 仅提示 | 生成器 |
| 45 | `IMPORT_TIME_OUTSIDE_SESSION` | warning | row | 成交时间不在交易时段内 | 仅提示 | 生成器 |
| 46 | `IMPORT_LOT_SIZE_IRREGULAR` | warning | row | 买入数量不符合整手规则 | 仅提示（科创板 200 股起、按 1 股递增等规则按板块处理；ETF 按 100 份整数倍，v0.2.8） | 生成器 |

**处理选项（v0.2.4 #11，T-F02 D3）**：`ImportFinding.resolution_choices` 按下表生成，第一个为 `default_resolution`；表中没有的提示码 `resolution_choices = []`、`default_resolution = null`。覆盖类选项提交时 `reason` 必填（1–200 字），并写审计。

| 提示码 | `resolution_choices`（第一个为默认） | 覆盖类（须填理由） |
|---|---|---|
| 8 `IMPORT_ACCOUNT_MISMATCH` | `[confirm_new_holder_code]`（不选则须改选账户） | `confirm_new_holder_code` |
| 26/27/28 `IMPORT_ENCODING_LOW_CONFIDENCE` / `IMPORT_FORMAT_LOW_CONFIDENCE` / `IMPORT_SNAPSHOT_AS_OF_ASSUMED` | `[confirm]`（要改编码、解析器或快照时间，用 `PUT /imports/{batch_id}/options`） | — |
| 33 `IMPORT_UNKNOWN_SECURITY` | `[import_as_is, skip_row]` | — |
| 34 `IMPORT_MARKET_INFERRED_CONFLICT` | `[use_master_data]` | — |
| 36 `IMPORT_UNKNOWN_BIZ_TYPE` | `[keep_skipped, manual_entry]` | — |
| 39/40 `IMPORT_DUPLICATE_IN_DB` / `IMPORT_DUPLICATE_IN_FILE` | `[keep_skipped, force_import]`（`needs_action=false`，但可覆盖） | `force_import` |
| 41 `IMPORT_POSSIBLE_DUPLICATE_OF_MANUAL` | `[skip_import_row, keep_import_void_manual]` | `keep_import_void_manual` |


---
## 5. 共享对象（各接口复用）

### 5.1 通用对象
| 对象 | 结构 |
|---|---|
| `Evidence` | 主键 `id` 在所属文档（一条建议、一个候选信号、一份日报）内唯一，全局用 `(snapshot_id, id)` 定位；其他对象一律用 `evidence_ids: string[]` 引用，**不存在 `evidence_id` 字段**。结构 `{id: string, key: string(feature_key), value: string \| number \| boolean \| null, unit: string \| null, provider: data_provider, endpoint: string \| null, data_as_of: string(datetime), fetched_at: string(datetime), epistemic_type}` |
| `RuleRef` | `{rule_id: string, snippet_id: string(uuid) \| null, snippet_version: int \| null, role: rule_role, dimension: dimension, passed: boolean \| null, value: string \| null, threshold: string \| null, evidence_ids: string[]}`。`passed` = 规则表达式求值为真（veto/counter/invalidation/weakening/exit 为真即“命中”）；无法求值为 `null`；未持有时 `ctx.*`/`plan.*` 规则不出现（v0.2.2）。`dimension` 对所有 `role` 必填、非空，取规则规格中声明的维度（v0.2.3） |
| `ModelRef` | `{model_key: string, version: string, role: "auxiliary", output: object, evidence_ids: string[]}` — `role` 只允许为 `auxiliary` |
| `TextWithEvidence` | `{text: string, expr: string \| null, evidence_ids: string[]}`，用于 `counter_evidence[]`、`invalidation[]`、`reasons[]` |
| `Stat` | `{value: string(decimal) \| null, n: int, window: string, small_sample: boolean}`。n < 30 时 `small_sample=true`；n < 5 时 `value=null`（plan 2.12.3；这是展示阈值，与降权门槛 n ≥ 20 无关）。**所有胜率、收益、IC、CAR 都用这个结构** |
| `ReleaseCondition` | `{kind: "expr" \| "time" \| "event" \| "user_action", expr: string \| null, at: string(datetime) \| null, event: string \| null, action: string \| null, check_on: check_on[], human_text: string, machine_checkable: boolean}` |
| `RiskFlag` | `{control: risk_control, level: risk_level, message: string, gated_actions: action[], quantity_cap: string(decimal) \| null, evidence_ids: string[]}`；T-A15：`total_exposure`(RC3) 与 `sector_concentration`(RC4) 超出上限时 `gated_actions=["buy","add"]`，否则为 `[]`（只做提示），`sell`/`reduce`/`hold`/`wait` 永远不会被这两项门控（plan 2.5.6 T-A15） |
| `DataStatusBlock` | 1.1 节的 `{data_status, data_as_of: string(datetime) \| null, gaps[]}`。**A-12 终裁（收敛 T-A160/#72）**：取本响应实际使用数据时点中最早的非空值；全空为 `null`，不得取生成/评估/当前时刻替代。该语义全站适用于 DataStatusBlock，Evidence 及 §8 SSE `quote` 为独立结构，维持非空 |
| `Stops` | `{stop_loss: string(decimal) \| null, take_profit: string(decimal) \| null, time_stop_days: int \| null}`。所有止损、止盈、时间止损一律嵌套在 `stops` 中（`CandidateSignal`、`StrategyConclusion`、`PlanDraft`），不平铺 |
| `ImportFinding` | `{id: string, code: string(IMPORT_*，§4.1), severity: import_severity, scope: import_scope, row_no: int \| null, field: string \| null, message: string, params: object, needs_action: boolean, resolution_choices: string[]（按 §4.1“处理选项”表，v0.2.4）, default_resolution: string \| null（= `resolution_choices[0]`，为空时 null）, resolution: {choice: string, reason: string \| null, by: string(uuid), at: string(datetime)} \| null}`。`row_no` 为文件物理行号（从 1 起），文件级为 `null`；`params`/`message` 中的股东代码、资金账号先掩码 |
| `Bar` | `{t: string(date) \| string(datetime), open, high, low, close: string(decimal), pre_close: string(decimal) \| null, volume: string(decimal), amount: string(decimal), avg_price: string(decimal) \| null}`。`t`：日/周线为交易日（周线取该周最后一个**有成交**的交易日，口径见 §6.2，v0.2.7）；`1m` 为该分钟 bar 的**结束**时刻【口径待 T003/T-B05 实测上游后确认】。`volume` 单位为**股**、`amount` 单位为**元**（上游若以“手”返回，由 ingest 换算；上游单位【待 T003 核实】）。`avg_price` 只在 `1m` 给出（分时均价 = 当日累计成交额 / 累计成交量），日/周线为 `null`。v0.2.7 加 `is_final: boolean`：日 K 当日收盘并入库后为 `true`，盘中返回的当日 bar 为 `false`；周 K 见 §6.2；`1m` 正在形成的那一分钟若返回则为 `false`【待 T003 补测：麦蕊分钟线是否返回未完成的那一分钟】 |
| `WatchlistItem` | `{security_code, name, focus: boolean, group: string \| null, note: string \| null, added_at: string(datetime), refresh_tier: "tier1" \| "tier2" \| null}`。`refresh_tier` 由系统按重点关注与配额分配（只读；分层规则见 plan 0A.3，数值【待 T003】） |
| `SignalEvent` | `{signal_event_id: string, security_code, name, kind: signal_kind, at: string(datetime), message: string, strategy_key: string \| null, instance_id: string(uuid) \| null, instance_ids: string(uuid)[]（T-A34，§7.11.4）, rule_id: string \| null, price: string(decimal) \| null, candidate_signal_id: string(uuid) \| null}`。规则事件，**不含动作建议**；`message` 须通过禁用词校验 |
| `Notification` | `{id, kind: notification_kind, severity, title: string, body: string \| null, created_at: string(datetime), read_at: string(datetime) \| null, security_code: string \| null, name: string \| null, target: {type: notification_target_type, id: string \| null, route: string \| null}, merged_count: int, updated_at: string(datetime), refs: [{type: notification_ref_type, id: uuid, at: string(datetime), route: string \| null}], version: int}`。四个合并/版本字段同步 §7.11.4 的 T-A28/T-A31 既有定义：`merged_count`、`version` 均 ≥1，`refs` 按 `at desc` 最多20条；旧记录投影 `merged_count=1`、`refs=[]`、`updated_at=created_at`、`version=1`，不新增行为或放宽字段。`target.route` 是前端路由（如 `/suggestions/{id}`、`/daily-reports/2026-11-02`），`type=none` 时 `id` 与 `route` 为 `null`。`route` 由服务端生成，前端直接跳转（v0.2.3）：`suggestion` → `/suggestions/{id}`；`candidate_signal` → `/candidate-signals/{id}`；`plan_draft` → `/plan-drafts/{id}`；`plan` → `/plans/{id}`；`daily_report` → `/daily-reports/{date}`（`id` 为日期）；`import_batch` → `/portfolio/import?batch={id}`；`reconciliation` → `/portfolio?tab=reconciliation&account_id={id}`；`strategy_version` → `/strategies/{strategy_id}?version={id}`（`id` 为版本 id） |
| `TerminalRow` | `{security_code, name, in_watchlist: boolean, focus: boolean, quote: {price, change_pct, amount: string(decimal), t: string(datetime)} \| null, holding: {qty: string(decimal), sellable_qty: string(decimal), cost_price: string(decimal), weight_pct: string(decimal), pnl: string(decimal) \| null, pnl_pct: string(decimal) \| null, security_type: security_type \| null, estimated: boolean} \| null, suggestion: SuggestionSummary \| null, active_reason_count: int, max_risk_level: risk_level \| null, data_status: data_status, data_as_of: string(datetime) \| null}`。`cost_price` 为摊薄成本（plan 3.5A）；`holding` 的 `security_type`、`estimated` 与 `pnl`/`pnl_pct` 的可空性同 `/portfolio` 持仓行（v0.2.9 #1–#3）；`data_as_of` 为该行行情与建议中较旧者的数据时点，完全无数据时为 `null`（v0.2.3） |
| `SuggestionSummary` | `{id, created_at, status: suggestion_status, consensus: consensus_status, actions: [{strategy_key, strategy_name, action, t_leg: t_leg \| null}], executability_status: executability_status, divergent_dimensions: dimension[], top_score: int \| null}`。终端表格的动作徽标与分歧标记只读这里，不再逐只请求 `/suggestions/{id}`。T-A16：`actions[]` 元素加 `lifecycle: lifecycle`，为 `simulating` 时前端标“模拟中”；`top_score` = 各策略 `score` 的最大非 null 值，全为 null 时为 `null` |
| `HorizonHint` | `{horizon: horizon, rule_id: string, text: string}`（v0.2.5）。画像类 `requires` 规则（`mode: hint`）在画像**已填写且不满足**时给出的提示，如 `{horizon:"short", rule_id:"SH0C", text:"短线需要盯盘与止损纪律，您自报的经验为新手"}`；画像未填写不产生提示；不影响分数与 `suitable`。**提示与分数无关**：即使该周期已被 `IT0` 等判为 0 分，仍按画像给出提示（v0.2.6，T006e）。`rule_id` 不是 `reason_code` |
| `HorizonCap` | `{horizon: horizon, cap: int(0–100), kind: "gate" \| "data_missing", rule_id: string \| null, inputs_missing: string[]}`（v0.2.3；**v0.2.6 改 `kind` 取值，T006e**）。`gate`：hard gate 命中（`rule_id` 为 `HG1`–`HG6`，判 0 分的 HG1–HG3 记 `cap: 0`，`inputs_missing` 为 `[]`）；`data_missing`：数据缺失或不足导致封顶——必需特征缺失时 `rule_id=null`、`inputs_missing` 为该周期缺失的 `f.*` 键；`LG0`（财报不足 12 期）、`LG0B`（ROE 缺失）的 `else_cap` 也记为 `data_missing`，`rule_id` 为规则 ID。`requires` 取值 v0.2.6 删除：画像类规则只进 `hints[]`（v0.2.5）；`IT0`（无底仓）的 `else_score: 0` 是分数而非封顶，不进 `caps`，只在 `reasons[]` 中给出反向理由。`rule_id` 是 `horizon_classifier.yaml` 的规则 ID，**不是** `reason_code`，不进 `/meta/enums`（v0.2.3 #23）。同一周期多个封顶都列出，生效值取最小 |
| `DataLicenceStatus` | `{status: data_licence_status, tier: data_licence_tier \| null, has_quant_pro: boolean \| null, expires_on: string(date) \| null（用户填写）, days_to_expiry: int \| null, set_at: datetime \| null, last_verified_at: datetime \| null, last_error_code: "101" \| "102" \| "103" \| "429" \| "503" \| "network" \| "http_5xx" \| null, last_error_at: datetime \| null, paused_until: datetime \| null}`（v0.2.6）。**不含证书值或其任何片段**；未设置时 `status: "not_set"`、其余字段为 null |
| `AdminDataLicence` | `DataLicenceStatus` 全部字段 + `{licence_id: uuid \| null（v0.2.8；未设置为 null）, user_id: uuid, username, display_name, per_minute_limit: int, calls_last_minute: int, calls_today: int, queue_depth: {p0: int, p1: int, p2: int}}`（v0.2.6；同样不含证书值） |
| `IngestLicenceStatus` | v0.2.8，`/admin/ingest/status` 的 `licences[]` 元素，每张证书一行：`{licence_id: uuid, user_id: uuid, username, display_name, status: data_licence_status, tier: data_licence_tier \| null, has_quant_pro: boolean \| null, expires_on: string(date) \| null, days_left: int \| null, calls_today: int, daily_limit: int \| null, per_minute_limit: int, calls_last_minute: int, queue_depth: {p0: int, p1: int, p2: int}, paused_until: datetime \| null, last_error_code: 同 DataLicenceStatus, last_error_at: datetime \| null}`。与 `AdminDataLicence` 同名字段同义；`days_left` 即 `days_to_expiry`（北京时间 `expires_on` 减今天的天数，已过期为负，`expires_on` 为 null 时为 null；v0.2.9 #40：null 只表示用户没有填写到期日，不表示不会过期，不触发 `licence.expiring`，前端显示“未填写到期日”，`DataLicenceStatus.days_to_expiry` 同义）；`calls_today` 为北京时间当日 00:00 起该证书已发出的上游调用数；`daily_limit` 为该证书当日的上游日额度，目前只有钻石版过期后取 `ingest.yaml` 的 `diamond_after_expiry_per_day`，其余为 `null`（未知或不限，【待 T003 补测：各档位日额度】）；`per_minute_limit` 为该证书令牌桶的当前上限；`queue_depth` 为该证书 p0/p1/p2 队列积压；`paused_until` 是上游熔断或限流造成的暂停（管理员暂停看 `status`）。**不含证书值、密文、HMAC 或其任何片段，也不含证书长度** |

**v0.2.7 新增对象**（下列结构中未标 `| null` 的字段均不为 null；数组无元素时为 `[]`）

**`ProviderRef`**：`{provider: data_provider, endpoint: string | null, fetched_at: string(datetime) | null}`。只用于展示类接口的 `sources[]`，用来注明来源；建议、信号类论断仍用 `Evidence`。

**`SecurityHit`**：`{security_code, name, type: security_type, exchange: "SH"|"SZ"|"BJ", board: board | null（指数、ETF 为 null）, listing_status: listing_status | null, risk_flag: security_risk_flag | null, match_kind: security_match_kind, matched_text: string | null（命中的是曾用名、旧代码或拼音首字母时，给出命中的原文；其余为 null；v0.2.9 内 T-A04：曾用名的拼音首字母命中时 `match_kind=former_name`，`matched_text` 为该曾用名原文）, quote_missing: boolean | null（该代码在公开主数据中有、在本人证书的麦蕊代码集中没有时为 true；尚未比对时为 null。v0.2.9 内 T-A04 写明：以本人当前证书最近一次成功对账为准（plan 4.6.4，麦蕊代码集 = `/hslt/list` ∪ `/bj/list/all` ∪ `/kc/list/all`）——该证券有未关闭的 `quote_missing` 差异 → `true`；已对账且没有 → `false`；本人未设置证书、证书不可用或该证书尚未完成过对账 → `null`；指数、ETF 不参与此比对，恒为 `null`）}`。

**`SecurityProfile`**：
```text
{security_code, name, type: security_type, exchange, board: board | null,
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
- **`data_as_of: string(datetime) | null`（A-12 终裁，2026-11-11）**：取实际参与本响应的公开主数据时点与本人证书各字段时点之并集中的最早非空值；仅整个并集为空时为 `null`。公开部分仍有可信时点时，不能仅因本人证书部分为空而返回 `null`；`master_as_of: string(date)` 仍必填。公开侧使用该快照日对应的原始带时区时间戳（现存 `securities.master_as_of`），证书侧使用各参与字段有据可查的数据时点（仅有采集时点时用对应 `fetched_at`）；只有 date 而缺原始时间戳时不拼造零点/当前时刻，保留日期并通过 gaps 披露时点缺口。`data_status` 继续只按证书部分判定，证书部分从未取得仍为 `partial`，两字段独立表达状态与时点。
- 第一行到 `attribution` 是**证券公开主数据**（全站一份，范围见 v0.2.7 #19：代码、简称、拼音、曾用名、交易所、板块、上市日、状态、风险警示；`type`、`code_history` 属“代码”，`list_date_basis` 属“上市日”，`delist_date` 属“状态”；拼音只用于搜索，不在本对象中返回）。来源（v0.2.9 内，T-A04 定）：交易所公开列表（`provider=exchange`，plan 4.6.1）；巨潮只在交易所列表缺字段时补缺、不覆盖交易所值，AKShare 只作交叉核对；不得用任何人的证书；能否展示与再分发仍待 plan 第 9 节问题 52（合规）。`list_date_basis="neeq_select"` 表示北交所平移股取的是精选层挂牌日；`attribution` 是固定的来源说明文字（如“证券列表来自上交所、深交所、北交所公开信息”），前端原样展示。**不提供公司全称**（不在公开主数据范围内）。
- `industry` 之后的字段来自本人证书（`provider=mairui`）；从未取到时为 `null` 或 `[]`，规则见 §1.1 混合来源响应。
- 指数：`board`、`list_date_basis`、股本、`industry` 为 `null`，`concepts` 为 `[]`。
- ETF（v0.2.8）：`board`、`list_date_basis`、`risk_flag`、股本（`total_shares`、`float_shares`）、`industry` 为 `null`，`concepts` 为 `[]`；这些字段对 ETF 不适用，不计入 `data_status` 的缺失判断，也不出 gap；`suspended` 照常来自本人证书。ETF 名单属于证券公开主数据，只用交易所公开的基金列表（v0.2.9 内，T-A04：具体端点由 plan T-B51 补测；补测完成前 ETF 不建档，按 ETF 代码或简称搜不到）。可转债不收录。

**`FinancialPeriod`**：
```text
{period_end: string(date), report_period: report_period, announce_date: string(date) | null,
 available_from: string(date) | null, is_restated: boolean,
 revenue, revenue_yoy_pct, net_profit, net_profit_yoy_pct, deducted_net_profit,
 eps, bvps, roe_pct, gross_margin_pct, debt_ratio_pct, operating_cash_flow}
```
从 `revenue` 起全部为 `string(decimal) | null`。金额单位元，`eps`/`bvps` 单位元/股，`*_pct` 为百分数（`12.3` 表示 12.3%）。利润表和现金流量表科目按报告期**累计**口径（Q3 = 1–9 月），不做单季拆分。`available_from` 为公告日的下一个交易日（时点视图用），未知时为 `null`。

**`FundFlowDay`**：`{trade_date, amount: string(decimal) | null（当日成交额）, main_net, super_large_net, large_net, medium_net, small_net, main_net_pct, is_final: boolean}`。除 `trade_date`、`is_final` 外均为 `string(decimal) | null`，单位元（`main_net_pct` 为百分数）。口径：主力 = 特大单 + 大单；净额 = 主动买入额 − 主动卖出额；分档阈值以麦蕊为准【待 T003 补测：分档阈值与 `main_net_pct` 的分母】。

**`FactorValue`**：`{factor_id: string（麦蕊原始因子 id）, feature_key: string | null（已登记进 feature_catalog 的为其键，否则为 null）, name: string, category: factor_category, value: string(decimal) | null, unit: string | null【待 T003 补测】, market_rank: int | null, market_rank_pct: string(decimal) | null【待 T003 补测：排名方向与样本数 N】}`。

**`Announcement`**：`{id, published_at: string(datetime), title: string, category: announcement_category, category_raw: string | null, level_raw: string | null, url: string | null, url_host: string | null, file_format: "pdf" | "html" | "other" | null, first_seen_at: string(datetime)}`。`url` 只有在 `https` 且主机在白名单（交易所、巨潮等，配置 `announcements.url_host_allowlist`，plan 6.1）内时才给出，否则为 `null`；`url_host` 始终是原始链接的主机名（无链接时为 `null`）。**不提供正文、摘要或任何由系统改写的内容。**

**`SectorFlow`**：`{sector_code: string, name: string, change_pct, main_net, amount: string(decimal) | null, up_count: int | null, down_count: int | null, leader: {security_code, name, change_pct} | null}`。`change_pct`、`main_net` 为 `string(decimal) | null`；金额单位元。`leader` 是当日该板块涨幅最大的成分股（客观行情事实，不构成任何建议）。

**`StrategyInstance`**：
```text
{id, strategy_id, strategy_key, strategy_name, strategy_version_id, version_no: int, lifecycle: lifecycle,
 derived_strategy_version_id: uuid | null, risk_level: card_risk_level,
 status: instance_status, origin: instance_origin,
 scope: "account" | "security" | "watch_group", account_id: uuid | null,
 security_code: string | null, name: string | null,
 horizon: horizon, param_overrides: object | null, budget_amount: string(decimal) | null, auto_downweight: boolean,
 paused_by: "user" | "system" | null, pause_reason_code: reason_code | null, paused_until: string(datetime) | null,
 created_at, confirmed_at: string(datetime) | null, updated_at, archived_at: string(datetime) | null}
```
- `name` 是证券简称；`security_code` 为 `null` 时 `name` 也为 `null`（§1 “证券简称”规则的例外）。
- `strategy_version_id`、`version_no`、`lifecycle`、`risk_level` 指实例实际运行的版本：有派生版本时就是派生版本。
- `status != "paused"` 时，`paused_by`、`pause_reason_code`、`paused_until` 都为 `null`。用户暂停时 `pause_reason_code=null`、`paused_until=null`；系统因连续亏损暂停时 `pause_reason_code="LOSS_STREAK_PAUSE"`，`paused_until` 为自动恢复的时间。

**`TodayAlert`、`TodayPlanTrigger`、`TodayDataGap`**：见 §7.3 `/today` 补充；**`RiskEvent`**：见 §7.5 `/risk-controls/events`。

**可解释性强制规则（P1）**：在任何返回 `CandidateSignal`、`Suggestion` 中策略结论的响应里，`rule_refs`、`evidence`、`counter_evidence`、`invalidation` 都是**非空数组**；`model_refs[*].role == "auxiliary"`。服务端写入时校验，不满足的不写入（内部记 `SIGNAL_NOT_EXPLAINABLE`）；契约测试检查所有示例和响应（T-T17）。

### 5.2 建议（`Suggestion`，plan.md 2.5.5 的 JSON 视图，内容不可变）
| 字段 | 类型 | 说明 |
|---|---|---|
| `id`, `security_code`, `name`, `created_at` | | |
| `status` | `suggestion_status` | 唯一可变字段（另有 `superseded_by_id`）；被取代、失效、过期时由系统更新 |
| `origin` | `suggestion_origin` | |
| `snapshot_id`, `feature_set_version` | string | 证据快照与特征集版本 |
| `candidate_signal_ids` | uuid[] | 本次生成的候选信号（hold/wait 不生成） |
| `executability` | `{status: executability_status, reason_ids: uuid[], executable_signal_ids: uuid[], blocked_signal_ids: uuid[]}` | 取值规则见 §3 |
| `plan_draft_ids` | uuid[] | |
| `horizon_assessment` | `{suitable: horizon[], user_overridden: boolean}` | |
| `consensus` | `{status: consensus_status, actions: {[action]: int}}` | 各动作的策略数 |
| `strategies` | `StrategyConclusion[]` | 见下表 |
| `dimension_matrix` | `[{dimension, divergent: boolean, cells: DimensionCell[]}]` | 由服务端从 `strategies[].dimension_views` 派生；契约测试检查一致 |
| `divergence` | `[{dimensions: dimension[], summary: string, resolving_info: [{description: string, subscribable: boolean}]}]` | |
| `risk_flags` | `RiskFlag[]` | |
| `evidence` | `Evidence[]` | 本建议引用的全部证据 |
| `explanation` | `{source: "template" \| "llm", text: string, llm_call_id: string \| null}` | LLM 只改写证据，见 plan 0B P1a |
| `supersedes_id`, `superseded_by_id` | uuid \| null | 取代链 |
| `engine_policy` | `{version_no: int, content_sha256: string} \| null` | T-A16：生成时所用的 engine_policy 版本；只有非引擎产物（如手工合成建议）为 `null` |
| `data_status`, `data_as_of`, `gaps` | DataStatusBlock | |

`StrategyConclusion`（`strategies[]` 的元素）：`{strategy_version_id, strategy_key, strategy_name: string, version_no: int, instance_id: uuid \| null, horizon, lifecycle, state: strategy_eval_state, action, t_leg: t_leg \| null, candidate_signal_id: uuid \| null（hold/wait 时为 null）, score: int(0–100) \| null, confidence: {level: confidence_level, value: number(0–1), components: ConfidenceComponents（T-A16）}, rule_refs: RuleRef[], model_refs: ModelRef[], priority_weight: string(decimal), priority_downweighted: boolean, dimension_views: [{dimension, view: dimension_view, score: int(0–100) \| null, rules: RuleRef[]}], stops: Stops, reasons: TextWithEvidence[], counter_evidence: TextWithEvidence[], invalidation: TextWithEvidence[], valid_until: string(datetime) \| null}`

`DimensionCell`：`{strategy_key, strategy_version_id, view: dimension_view, score: int(0–100) \| null, key_evidence_ids: string[]（≤ 3，取该维度 role ∈ {entry, filter, hold} 且 passed = true 的规则引用的前 3 个证据）, rules_passed: int, rules_total: int, exit_hits: int, exit_total: int}`（`rules_passed/rules_total` 只统计 role ∈ {entry, filter, hold}，v0.2.2；`exit_*` v0.2.3；v0.2.4 修正括号笔误）（v0.2.3：`exit_total` = 该维度 role ∈ {weakening, exit} 且已求值（`passed` 非 null）的规则数，`exit_hits` = 其中 `passed = true` 的条数；没有这类规则时均为 0）。行级 `divergent=true` 当且仅当该维度单元格中**同时存在** `bullish` 与 `bearish`（`neutral`、`unknown` 不参与，v0.2.3）。

**纯离场策略（exit-only，如 H-01 持仓风险监控；v0.2.3）**：规则只含 role ∈ {weakening, exit}（可另有 counter/invalidation）。① 只对**持有中**的证券求值；未持有时不出现在 `strategies[]`、`dimension_matrix`、`consensus` 中。② `state` ∈ {`hold_ok`, `weakening`, `exit_signal`, `insufficient_data`}，`action` ∈ {`hold`, `reduce`, `sell`}，从不出现 `entry_ok`/`buy`/`add`。③ 单元格 `rules_passed/rules_total` 为 0/0、`score` 为 `null`，展示改用 `exit_hits/exit_total`（前端显示“离场 x/y”）；`view`：任一命中 → `bearish`，全部已求值且未命中 → `neutral`，全部无法求值 → `unknown`。④ 计入行级 `divergent` 与 `consensus`（与 catalog 第 4 节第 4 点“冲突时并列展示”一致）。⑤ 计划草案 P1b 由 weakening/exit 命中满足。

`consensus.status`（v0.2.3）：0 个策略 → `none`；1 个 → `single`；≥ 2 个且各策略 `(action, t_leg)` 全部相同 → `unanimous`；否则 `divergent`。

`ConfidenceComponents`（T-A16，公式见 plan 2.5.4 后的 T-A16 第 2 条）：`{data_completeness: number(0–1), dimension_agreement: number(0–1) \| null, condition_margin: number(0–1) \| null, margin_rules: [{rule_id: string, value: string(decimal), threshold: string(decimal), scale: string(decimal), scale_kind: "declared" \| "atr14" \| "abs_threshold", margin: number(0–1), weight: string(decimal)}]}`。`value` = 0.5×D + 0.3×A + 0.2×M，A 或 M 为 `null` 时按 0 计入、不重新归一化；两位小数；high ≥ 0.70、medium ≥ 0.40、其余 low。`margin_rules` 只列计入余量的规则，可为 `[]`。`CandidateSignal.confidence` 结构不变。

### 5.3 日报（`DailyReport`，不可变）
`{date: string(date), generated_at, account_id: uuid \| null, market: {regime: market_regime \| null, regime_position_range: {min_pct: string(decimal), max_pct: string(decimal)} \| null, breadth: {up: int, down: int, limit_up: int, limit_down: int} \| null, summary: TextWithEvidence[]}, account: {total_assets, cash, position_pct: string(decimal) | null, pnl_day: string(decimal) | null, position_vs_regime: "below" \| "within" \| "above" \| null} \| null, reconciliation: {status: reconciliation_status, as_of: string(datetime) \| null, diff_count: int, important_count: int}, stocks: [{security_code, name, close: string(decimal) \| null, change_pct: string(decimal) \| null, data_status: data_status, max_risk_level: risk_level \| null, suggestion_id: uuid \| null, suggestion: SuggestionSummary \| null, change_from_previous: "new" \| "changed" \| "unchanged" \| "removed" \| null（T-A16）, change_fields: ("actions" \| "confidence_level" \| "executability" \| "max_risk_level")[]（T-A16）, highlights: TextWithEvidence[], invalidation: TextWithEvidence[], next_watch: TextWithEvidence[]}], pending: {plan_drafts: int, active_reasons: int}, explanation: {source: "template" \| "llm", text: string, llm_call_id: string \| null}, evidence: Evidence[], DataStatusBlock}`。
- `regime_position_range` 是该 regime 下的**参考仓位区间**（模板参数，取自风控 RC3 的 `regime_ranges`（plan 2.5.6、6.1 `config/risk_controls.yaml`：上行 60–90%、震荡 40–60%、下行 0–30%，用户可调）），不是指令；`position_vs_regime` 由当前仓位与区间比较得出。
- 没有账户或未导入时 `account=null`、`reconciliation.status="not_imported"`。
- `stocks[].close`/`change_pct` 为日报所属交易日的收盘价与涨跌幅（停牌或缺数据为 `null`）；`max_risk_level` 取该证券建议卡 `risk_flags` 的最高级别，无则 `null`（v0.2.3）。
- `account.cash` 与全文其他 `cash`（如 `PlanDraft.user_context_snapshot.cash`）同义：由交割单与资金流水重建的现金余额；与 `/terminal` 的 `cash_available`（可用资金）不同（v0.2.3）。
- **T-A16 裁定（架构师 2026-11-07）**，详见 plan 2.5.4 后的 T-A16：
  - `reconciliation`：取该账户生成时刻之前最新一次对账；`diff_count` = 未被忽略（`resolution` 为空）的条目数；`important_count` = 其中 `kind` ∈ {`quantity_mismatch`, `missing_in_broker`, `missing_in_ours`} 的条数。非空对账不返回 503。
  - `change_from_previous`：基准是严格早于本日的最近开市日的最新完成版日报，同日新 revision 也和它比。比较 `actions`、`confidence_level`、`executability`、`max_risk_level` 四项，变化项列在 `change_fields`（`new`/`unchanged`/`removed` 时为 `[]`）。昨有今无追加 `removed` 行（建议相关字段为 null、文字为 `[]`，不计入列表 `stock_count`）。没有基准时全部为 `null`，不出 `removed` 行，`gaps` 记 `{key:"stocks.change_from_previous", reason:"no_source"}`。
  - 范围与内容：`account_id` 按 T-A12 默认账户；`stocks` = 该账户持仓 ∪ 本人自选（持仓按权重降序在前，其余按代码升序）；`evidence[].id` 改写为 `{security_code}:{原 id}` 并同步行内 `evidence_ids`；`highlights` = 各策略 `reasons` 去重前 3 条，`invalidation` = 各策略 `invalidation` 去重，`next_watch` 在 MVP 恒为 `[]`（T-B79）。

---

### 5.4 T-A11：Phase 2 离线最小闭环的默认口径（v0.2.9 内）

- 回放仅限隔离本地模拟环境：全合成输入、禁止外呼、按用户隔离快照与实例；无真实证书时快照 `licence_id=null`，不得伪造 active 证书或写入生产证书内共享信号状态。证据用既有 `provider=system`、`epistemic_type=hypothesis/estimate`，解释明确“模拟回放”；不新增 provider 枚举，不把虚构行情当 mairui 实测事实。生产证书不可用时仍按 §1.1 降级。仅管理员/自愿用户可使用 simulating 模板，永不生成计划草案。
- 以 §7.7 为准：无原因的候选先为 open，解除后为 released；均只有用户显式 `POST /plan-drafts` 才进入 drafted，不自动生草案。hold/wait 不生成候选。此条优先于旧 plan §2.5.4 的自动草案描述。
- 日报按 `(user_id, trade_date, revision)` 保存不可变版本；`GET /daily-reports/{date}` 取该日最新 ready/partial 完成版，列表每日期一条。构建中的新版不遮掉旧完成版；无完成版的日期详情返回 `404 NOT_FOUND`，由 `/today.daily_report` 表示 generating/not_yet。partial完成版在today映射 ready，缺口保留在日报/今日的相应结构，不能表示数据完整。
- **可空性补充**：`DailyReport.account.pnl_day` 与 `/terminal.account.pnl_day` 明确为 `string(decimal) | null`（缺上日估值/当日资金流等计算基准时）；两者 `position_pct` 明确为 `string(decimal) | null`（资产分母不可用或≤0时）。缺值在已有 gaps 或今日 data_gaps 中按适用原因列出，不填伪0；`regime` 无来源时为 null，不默认为 range。其余字段沿用原定义，不以 account=null 隐藏已存在账户。
- MVP聚合仍返回 §7.3 的全部必填字段；草案/提醒/计划未有记录时是空集合，unread_notifications 为实际通知表未读计数。尚未交付的全量 /plans、/notifications、/signals、/stream 留后续，不能用空壳200宣称对应业务已实现。

---

## 6. 状态机与原因码

### 6.0 状态机（非法跃迁 → `409 INVALID_STATE_TRANSITION`，`details: {from, to, allowed: []}`）
| 对象 | 状态 | 允许的跃迁（触发方） |
|---|---|---|
| 卡片 `card_completeness` | `draft` `documented` `runnable_candidate` `promoted` `retired` | 系统自动计算，客户端不可写 |
| 模板版本 `lifecycle` | `draft` `simulating` `published` `observing` `retired` | draft→simulating（管理员，G1–G7 通过）；simulating→published（管理员，满足 2.5.13 条件）；published⇄observing（健康度状态机，系统）；任意→retired（管理员） |
| 实例 `instance_status` | `proposed` `active` `paused` `archived` | proposed→active（用户确认）；active→paused（用户；或系统因 `LOSS_STREAK_PAUSE`）；paused→active（用户；或系统暂停到期后由系统恢复）；proposed/active/paused→archived（用户；`origin=system` 的实例只能由系统归档；分类结果变化后过时的 `proposed` 由系统归档）；archived 为终态。操作细则见 §6.0A（v0.2.7） |
| 候选信号 `candidate_signal_state` | `open` `drafted` `blocked` `released` `confirmed` `dismissed` `expired` `invalidated` `superseded` | open→drafted/blocked（系统）；blocked→released（系统或手动解除）→drafted/blocked；drafted→confirmed（确认草案）；非终止态→dismissed（用户）/expired/invalidated/superseded（系统）。v0.2.9 #30、#37：→`drafted` 由用户拟定草案触发（`cause=user`）；`open`、`released`、`drafted` 都可调用 `POST /plan-drafts`，`blocked` 返回 `409 SIGNAL_NOT_EXECUTABLE`，终态返回 `409 INVALID_STATE_TRANSITION` |
| 原因 `reason_status` | `active` `released` `obsolete` | active→released（系统，或 `machine_checkable=false` 时由用户手动）；active→obsolete（所属信号终止） |
| 计划草案 `plan_draft_status` | `pending` `confirmed` `discarded` `expired` `stale` | pending→confirmed/discarded（用户）；pending→expired/stale（系统） |
| 研究候选 `research_candidate_status`（v0.2.9 T-A11） | `researching` `watching` `dropped` `planned` | 新建为 researching；researching⇄watching（用户，新版本 `decision=continue/watch`）；researching/watching→dropped（用户，`decision=drop`）；researching/watching→planned（系统：本人创建了 `candidate_id` 指向该候选的操作计划；本版没有入口，§7.7A）；`dropped`、`planned` 为终态，不再接受新版本（`allowed: []`）；不带 `decision` 或决定与当前状态相同的新版本不改变状态 |
| 导入批次 `import_status` | `uploaded` `parsing` `previewed` `committed` `failed` `discarded` `reverted` | uploaded→parsing（系统）；parsing→previewed/failed（系统）；previewed/failed→parsing（`PUT options`）；previewed→committed（确认）；previewed/failed→discarded（用户）；committed→reverted（用户） |
| 健康度 `health_state` | `published` `observing` | 见 2.8.2；`proposed_action: none \| review \| retire` 只用于提示 |

### 6.0A 策略实例操作（v0.2.7）
| 操作 | 请求体 | 合法转换 | 幂等（当前已是目标态） | 非法时 |
|---|---|---|---|---|
| `POST /strategy-instances/{id}/confirm` | 无 | proposed→active | active → `200`，不变 | paused/archived → `409 INVALID_STATE_TRANSITION` |
| `POST /strategy-instances/{id}/pause` | `{note: string(≤200) \| null}`（可省略请求体） | active→paused（`paused_by="user"`） | paused → `200`，不变（**系统暂停不会被改写成用户暂停**） | proposed/archived → 409 |
| `POST /strategy-instances/{id}/resume` | `{note: string(≤200) \| null}` | paused→active | active → `200`，不变 | proposed/archived → 409 |
| `POST /strategy-instances/{id}/archive` | `{note: string(≤200) \| null}` | proposed/active/paused→archived | archived → `200`，不变 | `origin=system` → 409（`allowed` 不含 `archived`） |

1. 成功时一律返回 `200 StrategyInstance`（完整对象）。幂等的空操作也返回 `200` 和当前对象，**不写事件**、不改 `updated_at`。
2. 发生状态转换时写一条 `/events`，`actor` 为 `user` 或 `system`。服务端对实例加行锁，并发请求串行执行；先完成的一方转换状态，后到的一方按幂等或非法规则处理。
3. `allowed` 示例：从 `proposed` 出发为 `["active","archived"]`；从 `active` 出发为 `["paused","archived"]`；从 `paused` 出发为 `["active","archived"]`；从 `archived` 出发为 `[]`；`origin=system` 的实例去掉 `archived`。
4. confirm 或 resume 时，如果实际运行的版本 `lifecycle` 不可运行（如 `retired`、`simulating`），返回 `409 STRATEGY_VERSION_NOT_RUNNABLE{lifecycle}`，状态不变。
5. resume 一个系统暂停（`pause_reason_code="LOSS_STREAK_PAUSE"`）的实例，视为“用户确认恢复”：清空暂停字段，并在事件 `detail` 中记 `{released_reason_code: "LOSS_STREAK_PAUSE"}`。用户暂停的实例不会被系统自动恢复。
6. 暂停期间该实例不生成新的候选信号；已存在的候选信号状态不变。归档时如何处理仍开放的候选信号，见 v0.2.7 未决 Q5。
7. 对 archived 实例 `PATCH` → `409 IMMUTABLE_RESOURCE`。
8. `POST /strategy-instances` 创建的实例 `origin="user"`、直接为 `active`（与 v0.2.6 一致）；`proposed` 只由周期分类器产生（`origin="classifier"`）；`origin="system"` 只由系统挂载（如 H-01）。v0.2.8：**ETF 不能创建实例**——`scope="security"` 且证券为 ETF → `422 INSTANCE_SCOPE_INVALID{scope, security_code, security_type:"etf", issue:"security_type_not_supported"}`；`scope="account"`/`"watch_group"` 的实例运行时跳过其中的 ETF（不报错，不产生候选信号和建议）；周期分类器对 ETF 各周期判 0 分（HG1，规则不变），不产生 `proposed` 实例；H-01 不挂到 ETF 持仓。v0.2.8 补充（架构师裁定）：`scope="security"` 且 `security_code` 不在证券主数据中 → `422 INSTANCE_SCOPE_INVALID{scope, security_code, issue:"unknown_security"}`（不带 `security_type`）。
9. **自愿模拟授权（T-B73 裁定，架构师 2026-11-07）**：本 MVP 不开放用户自愿参与模拟。
   - 实际运行版本为 `simulating` 时：普通用户创建或 confirm/resume → `409 STRATEGY_VERSION_NOT_RUNNABLE{lifecycle:"simulating"}`；管理员可以创建，实例只做模拟跟踪，不生成计划草案。
   - 系统挂载（`origin="system"`）对普通用户只挂 `published`/`observing` 版本。T-A14 修订：管理员账户可以挂 `simulating` 版本，实例只做模拟跟踪，建议带“模拟中”标记，不生成计划草案。
   - 以后开放自愿参与时，授权放在用户设置的 `simulation_opt_in`（布尔值，带 `opted_in_at`，用户本人开关，并写审计），列为 T-B79 后续项；本版不加字段，不加接口。
10. **`watch_group` 选择器（T-B73 裁定）**：
   - 选择器字段是 `watch_group_name: string | null`，对应 `watchlist_items.group_name`，按原样精确匹配。`scope="watch_group"` 时必填，其他 scope 必须为 `null`。
   - 成员在每次求值时动态解析为本人 `removed_at is null` 的条目，ETF 自动跳过。组为空时允许创建，只是不产生候选。
   - 本 MVP 不交付 watch_group 实例：`POST` 时 `scope="watch_group"` → `422 INSTANCE_SCOPE_INVALID{scope, issue:"scope_deferred"}`。实现、`StrategyInstance` 加 `watch_group_name`，以及迁移，都列入 T-B79。

### 6.1 不可执行原因码（`reason_code`，与 plan.md 2.5.9 一致；`GET /meta/enums` 下发，含默认解除条件）
| code | 默认 `release_condition.kind` | `check_on` | 可手动解除 |
|---|---|---|---|
| `DATA_STALE` | expr | tick | 否 |
| `KEY_DATA_MISSING` | expr | tick, daily_close | 否 |
| `LOW_CONFIDENCE` | expr | tick, daily_close | 否 |
| `NON_TRADING_TIME` | time | schedule | 否 |
| `SUSPENDED` | event | tick, daily_close | 否 |
| `LIMIT_LOCKED` | expr | tick | 否 |
| `ST_OR_DELISTING` | event | daily_close | 否 |
| `NEW_LISTING` | expr | daily_close | 否 |
| `INSUFFICIENT_CASH` | expr | cash_update, import | 否 |
| `T1_NOT_SELLABLE` | time / expr | schedule, holding_change | 否 |
| `NO_POSITION` | expr | holding_change, import | 否 |
| `POSITION_CAP_REACHED` | expr | tick, holding_change | 否 |
| `STRATEGY_BUDGET_EXHAUSTED` | expr | holding_change | 否 |
| `SECTOR_EXPOSURE_EXCEEDED` | expr | holding_change, tick | 否 |
| `REGIME_MISMATCH` | expr | daily_close | 否 |
| `SAME_DIRECTION_PLAN_EXISTS` | event | plan_change | 否 |
| `CONFLICTS_CONFIRMED_PLAN` | user_action | user_action | 是 |
| `BLOCKLISTED` | user_action | user_action | 是（通过 `/restrictions`；`machine_checkable=true`，对其调用 `/release` → `409 REASON_NOT_MANUALLY_RELEASABLE`，v0.2.9） |
| `COOLING_OFF` | time | schedule | 否 |
| `LOSS_STREAK_PAUSE` | user_action / time | user_action, schedule | 是 |
| `STRATEGY_CONFLICT` | user_action / expr | user_action, tick | 是（`evidence` 中写明对方候选信号的 id，v0.2.9；#30 写明：每个对方信号一条 `Evidence`，`key="signal.conflict_signal_id"`（保留键，不进 feature_catalog）、`value` 为对方信号的 uuid、`unit=null`、`provider="system"`、`endpoint=null`、`epistemic_type="fact"`，`data_as_of`、`fetched_at` 为检测时刻；不另设字段） |
| `USER_MUTED` | user_action / time | user_action, schedule | 是（通过 `/restrictions`；`machine_checkable=true`，对其调用 `/release` → `409 REASON_NOT_MANUALLY_RELEASABLE`，v0.2.9） |

### 6.2 周 K 口径（`freq=w`，v0.2.7）
1. **聚合方式**：由日 K 按自然周（周一到周日，北京时间）聚合，复权方式与同一请求的日 K 完全相同（`qfq` 与 `hfq` 都先对日线复权再聚合；`adjust` 默认 `qfq`）。不直接使用麦蕊的周线。
2. **`t`**：该周最后一个**有成交**的交易日（停牌日不算）。当周还没有结束时，`t` 为截至目前最新的有成交交易日。
3. **字段**：`open` 为该周第一个有成交日的开盘价；`close` 为 `t` 当日的收盘价；`high`/`low` 为周内最高和最低；`volume`、`amount` 为求和；`avg_price` 与日线相同为 `null`（§5.1 `Bar`）。
4. **`pre_close`**：上一根周 K 的 `close`；第一根取该周首个有成交日的日线 `pre_close`，没有则为 `null`。
5. **不完整周**（节假日、部分停牌）照常聚合，不补齐；整周停牌或休市的那一周**不出 bar**；麦蕊停牌占位行（`sf=1`）不参与聚合。
6. **`is_final`**：该周最后一个交易日已收盘、且当日日线已入库时为 `true`；否则为 `false`（包括盘中和收盘后日线尚未入库的时段）。
7. **复权映射**：`qfq` 对应麦蕊 `f`，`hfq` 对应 `b`，`none` 对应 `n`【待 T003 补测：`f` 与 `fr` 的差别、前复权基准日如何取得（填 `adjust_as_of`）】。
8. `limit`、`before`、`next_before` 按周 K 根数计算，规则与日 K 相同。

---

## 7. 端点
约定：标 🔒 的需要登录且账号已批准；标 🛡 的需要 `role=admin`；标 ⚖ 的为建议类输出，前端须展示固定免责提示（1.3，v0.2.5 起无服务端门槛）；列表接口均按 1.2 分页，除非注明。请求体字段未注明可空的都必填。

### 7.1 认证与账号
| 方法 | 路径 | 说明 | 请求 → 响应 |
|---|---|---|---|
| GET | `/meta/registration` | 注册模式（不需登录），前端据此隐藏注册入口 | → `200 {mode: registration_mode}`（v0.2.5：不再有文书版本） |
| POST | `/auth/register` | 注册，状态为 `pending`。**V1 默认 `registration_mode=closed`**，一律返回 `503 REGISTRATION_CLOSED`；本人账号由 CLI 创建 | `{username: string(4–32，^[a-z0-9_]+$，服务端转小写；保留词 admin/root/system 等 → 400 VALIDATION_ERROR), password: string(10–128，须含字母与数字，不得等于用户名，不得在弱口令表中), display_name: string(1–32), invite_code: string \| null（V1 不用）, apply_note: string(≤200) \| null, website: string \| null（v0.2.8 蜜罐，可选）, form_started_at: int \| null（v0.2.8，可选）}`；提交注册即视为已知悉固定免责提示（注册页展示），不记录同意；旧客户端发来的 `agreements` 字段被忽略（v0.2.5） → `201 {id, username, status:"pending"}`；`invite` 模式下 `invite_code`、`apply_note` 必填，邀请码无效（不存在/过期/已用/已吊销/绑定的用户名不符）一律 `400 VALIDATION_ERROR {fields:[{field:"invite_code", issue:"invalid"}]}`；可能返回 `409 CONFLICT`、`503 REGISTRATION_CLOSED`（含邀请功能未上线时的 `invite` 模式）、`429 RATE_LIMITED`。**蜜罐与最短填写时间（v0.2.8，架构师裁定）**：`website` 是前端隐藏的输入框（不可见、`tabindex=-1`、`autocomplete=off`），正常提交为空串或不传；`form_started_at` 是注册表单首次渲染时的毫秒时间戳（Unix epoch ms），前端应按服务端时钟校正（用 `GET /meta/registration` 响应头 `Date` 与本地时钟的差值），不传则不做此项检查。两字段是注册体的正式字段，**不触发** `extra=forbid` 的 `400 VALIDATION_ERROR`（其他未知字段仍 400）；`website` 不校验内容与长度；`form_started_at` 不是整数 → `400 VALIDATION_ERROR`。**命中条件**：`website` 去首尾空白后非空；或 `form_started_at` 存在且“服务端当前毫秒时间 − `form_started_at` < 3000”（含未来时间）。**判定顺序**：请求体超过全局上限 → `413 PAYLOAD_TOO_LARGE`（中间件，全局规则，v0.2.9 内评审裁定，先于注册模式）→ 注册模式（`closed` → 503；v0.2.9 写明：`closed` 时**不论请求体格式是否正确**——非法 JSON、缺字段、类型错误、未知字段——一律先返回 `503 REGISTRATION_CLOSED`，请求体解析与校验不得先于模式判断；只有请求体超过全局上限的 `413` 在它之前）→ IP 限速（命中的请求同样计数）→ 字段与邀请码校验（400）→ 用户名冲突（409）→ 待审核数上限（全站 `pending` 账户数 ≥ `pending_cap`，默认 200 → `503 REGISTRATION_CLOSED`，与关闭注册同码同体）→ 蜜罐。**命中时**返回与正常注册相同的状态码和响应体（`201 {id: 随机 uuid, username: 归一化后的用户名, status:"pending"}`），但不创建用户、不消耗邀请码、不进入待审核列表；写审计 `auth.register_honeypot`（`actor_id=null`，`detail` 只含 `{trigger: "website"\|"too_fast"\|"both"}`，**不记录用户名、口令、申请说明等任何表单内容**，`ip_hash` 照常）。3000 毫秒是固定规则，不进配置 |
| POST | `/auth/login` | 登录 | `{username, password}` → `200 {user: Me, csrf_token}` + Set-Cookie；可能返回 `401 INVALID_CREDENTIALS`、`403 ACCOUNT_NOT_APPROVED{status, reason?}`、`403 ACCOUNT_LOCKED{retry_after_s}` |
| POST | `/auth/logout` 🔒 | 注销 | → `204` |
| POST | `/auth/password` 🔒 | 修改密码，同时注销其他会话并轮换当前会话 | `{old_password, new_password}` → `204` + Set-Cookie（新 `sid`、新 `csrf_token`；前端从 Cookie 重读 CSRF 令牌）；旧密码错误 → `400 VALIDATION_ERROR`（`field: old_password`），计入 T-B03a 限速 |
| GET | `/me` 🔒 | 当前用户 | → `Me {id, username, display_name, role, status, entitlements: {key: value}, data_licence_status: data_licence_status}`（v0.2.5 删 `consents`、`risk_assessment`；v0.2.6 加 `data_licence_status`） |
| GET/PUT | `/me/profile` 🔒 | 投资画像（版本化，PUT 生成新版本；全部由用户自报） | `{horizon_pref: horizon[], effort: "low"\|"medium"\|"high" \| null, risk_tolerance: int(1–5) \| null, experience: "novice"\|"intermediate"\|"advanced" \| null, max_single_position_pct: string(decimal，5–50，最多 2 位小数；pattern `^(?:(?:[5-9]\|[1-4]\d)(?:\.\d{1,2})?\|50(?:\.0{1,2})?)$`，只接受字符串，v0.2.9 内 T-B47 裁定)}` → `{version_no, ...}`；无画像时 GET → `404 NOT_FOUND`（分类器按未填写处理）。三个自报字段为 null 表示未填写：分类器不封顶、不提示（plan 2.5.3、2.5.14）。v0.2.5 删 `assessment_id`、`questionnaire_version` 与 `exceeds_assessment` 校验 |
| GET | `/me/data-licence` 🔒 | 本人数据证书状态（v0.2.6，plan 2.1B） | → `200 DataLicenceStatus`；**永不返回证书值**；证书设置开关关闭时照常可用（v0.2.8 补充） |
| PUT | `/me/data-licence` 🔒 | 设置或替换本人麦蕊证书：服务端用 `ingest` 公钥加密后存库，并投递一次验证 | `{licence: string（去首尾空白后 16–64 位，`^[A-Za-z0-9-]+$`，【待核实 T-B05】；v0.2.9 内 T-B47 裁定：OpenAPI 写明 `minLength: 16`、`maxLength: 64`、pattern `^[A-Za-z0-9-]{16,64}$`，首尾空白由服务端去除后再校验）, tier: data_licence_tier, has_quant_pro: boolean, expires_on: string(date) \| null}` → `202 DataLicenceStatus`（`status: "pending_verification"`）；同一证书已绑定其他账号 → `409 DATA_LICENCE_IN_USE`；格式不符 → `400 VALIDATION_ERROR`（`field: "licence"`，消息不含输入值）；10 次/小时 → `429 RATE_LIMITED`。**管理员暂停期间（v0.2.8，架构师裁定）**：暂停**按用户记录**，不随证书行的替换或删除而消失。暂停期间 PUT（新证书或同一证书）照常校验（400/409/429 同上），通过后保存密文和元数据，返回 `202 DataLicenceStatus`，其中 `status` 仍为 `"paused_by_admin"`；**不投递验证**，`ingest` 不使用该证书；DELETE 后再 PUT 同样不解除暂停。只有管理员 resume 能解除（§7.9）。**重复 PUT 同一证书**（与当前证书相同，按服务端 HMAC 判定）：`paused_until` 未到期时保留；状态为 `quota_exceeded` 或 `ip_limited` 时保持该状态；这两种情况返回 `202` 与当前状态，不投递验证，只更新 `tier`、`has_quant_pro`、`expires_on`。其余情况照常转为 `pending_verification` 并验证。**删除后重新提交（v0.2.8 补充，架构师裁定）**：状态为 `quota_exceeded`、`ip_limited`，或 `active` 但 `paused_until` 未到期时 DELETE，之后在 `paused_until` 到期前重新 PUT **同一证书**（服务端用带密钥的证书指纹（HMAC）判定，不存明文，指纹不出现在任何响应中）→ 恢复删除前的 `status` 与 `paused_until`，返回 `202 DataLicenceStatus`，到期前不投递验证；换成不同证书照常转为 `pending_verification` 并验证；`paused_until` 到期后再 PUT 按新提交处理。**证书设置开关（v0.2.8 补充）**：`DATA_LICENCE_SETTINGS_ENABLED=false`（生产默认）时 → `503 MAINTENANCE`（在请求体格式校验之后、限速与其他判断之前：请求体格式错误先返回 `400 VALIDATION_ERROR`），前端显示“设置暂未开放”。与注册接口顺序不同的原因（v0.2.9 写明）：注册是公开端点，关闭时整体不可用，所以模式判断最先；证书设置是登录后的局部开关，格式错误照常提示 |
| PATCH | `/me/data-licence` 🔒 | 只改元数据（不改证书） | `{tier?: data_licence_tier, has_quant_pro?: boolean, expires_on?: string(date) \| null}` → `200 DataLicenceStatus`；省略的字段不变；`tier`、`has_quant_pro` 不可为 null（传 null → `400 VALIDATION_ERROR`，OpenAPI 不标 nullable），`expires_on: null` 表示清除到期日（v0.2.9 内 T-B47 裁定）；未设置 → `409 DATA_LICENCE_NOT_SET`；证书设置开关关闭时 → `503 MAINTENANCE`（v0.2.8 补充，同 PUT：请求体格式校验 `400` 先于 503，之后才是 `409 DATA_LICENCE_NOT_SET` 等判断，v0.2.9 写明） |
| DELETE | `/me/data-licence` 🔒 | 删除本人证书（密文清除，`ingest` 15 秒内停止使用；该证书名下的行情数据按保留策略清理） | → `204`；未设置也 `204`（幂等）；管理员暂停期间 DELETE 照常清除密文，之后 `GET` 仍返回 `status:"paused_by_admin"`（证书相关字段为 null），暂停记录保留（v0.2.8）；证书设置开关关闭时照常可用（用户随时能删除自己的证书）；删除时如处于冷却（见 PUT 行），服务端保留该证书的指纹与删除前的 `status`、`paused_until`，到 `paused_until` 为止，只用于判定同一证书重新提交，不保留明文和密文（v0.2.8 补充）。**冷却记录保留期（v0.2.9 内，评审 be607b3/f72b8c7/8fd9502 裁定）**：`paused_until` 为 null（删除时没有处于冷却，如 `ip_limited` 未定恢复时间）的记录最多保留到删除后 24 小时，有 `paused_until` 的保留到 `paused_until`，两者以先到者为准；契约其他地方规定更短期限的以更短者为准。周期任务物理删除过期记录；读取时过期记录一律视为不存在（未清理也不得用于恢复状态）。**到期边界（v0.2.9 内，T-T25 裁定）**：到期时刻 = `paused_until`（非 null 时）或删除时刻 + 24 小时（`paused_until` 为 null 时），上文“两者以先到者为准”即按此取值；记录仅在当前时间早于到期时刻时有效，等于到期时刻即已过期；PUT 行的“`paused_until` 未到期”同样指当前时间早于 `paused_until`，恰好等于时按到期后的新提交处理；时间用数据库服务器 UTC 时间比较（plan 7.3） |
| POST | `/me/data-licence/test` 🔒 | 让 `ingest` 用本人证书调用一次轻量接口 | → `202 {verification_id: uuid}`，结果经 SSE `data_licence` 与 `GET /me/data-licence` 获取；未设置 → `409 DATA_LICENCE_NOT_SET`；5 次/小时 → `429 RATE_LIMITED`；采集暂停 → `503 INGEST_PAUSED`；管理员暂停期间 → `409 DATA_LICENCE_UNAVAILABLE{status:"paused_by_admin"}`（v0.2.8）；证书设置开关关闭时 → `503 MAINTENANCE`，先于上述各项判断（v0.2.8 补充；本接口无请求体，所以 503 最先，v0.2.9 写明） |
| GET/PATCH | `/admin/users` 🛡 · `/admin/users/{id}` 🛡 | 审核和停用账号 | GET 列表分页（§1.2）`?status=&q=`，元素 `AdminUser {id, username, display_name, status: account_status, role, apply_note: string \| null, created_at, register_ip_region: string \| null（粗粒度）, same_ip_registrations: int, same_ip_flag: boolean（超过 plan 6.1 `admin.same_ip_highlight_threshold`，只作提示）, review_reason: string \| null, reviewed_at: string(datetime) \| null, last_login_at: string(datetime) \| null}`；PATCH `{status: "approved"\|"rejected"\|"disabled", reason: string(≤200) \| null}`：`rejected`、`disabled`，以及从 `disabled` 恢复为 `approved` 时 `reason` 必填，否则 `400 VALIDATION_ERROR`（v0.2.4 #12） |

### 7.2 账户、成交与导入（只返回掩码字段）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/accounts` 🔒 | 券商账户：`{id, broker_name, alias, shareholder_code_masked, fund_account_masked, created_at}`；POST 只接受 `alias` 和 `broker_name`：`{broker_name: string(1–32), alias: string(1–32) \| null}`（v0.2.9 内 T-B46 裁定：去首尾空白后计长度） |
| POST | `/imports` 🔒 | `multipart/form-data`：`file`、`account_id`、`kind: "trades"\|"positions"`、`snapshot_as_of: string(datetime) \| null`（持仓快照时间，可后补；multipart 中缺省或空串都按 null，v0.2.9 内 T-B46 裁定）。文件类型按扩展名与内容判定（`.csv`/`.txt`/`.xls`/`.xlsx`），schema 无法表达，类型不符 → `422 IMPORT_FILE_ERRORS`（`IMPORT_UNSUPPORTED_FILE_TYPE`）。原始文件存放在仓库外、加密并做访问控制的存储中（plan.md 3.5A）→ `201 {batch_id, status: "uploaded", file_findings: ImportFinding[]}`，随后后台解析。上传阶段的文件级 error（空文件、过大、类型不符、行数超限）→ `422 IMPORT_FILE_ERRORS{findings}`，**不创建批次**。同一文件再次上传**不报错**，在 `file_findings` 中给出 warning `IMPORT_DUPLICATE_FILE{batch_id}`。v0.2.8：交割单与持仓文件中的 ETF 按证券主数据识别，照常导入并重建持仓；可转债不在主数据中，仍按 `IMPORT_UNKNOWN_SECURITY` 处理（`import_as_is` / `skip_row`） |
| GET | `/imports` 🔒 | 批次列表（分页，`?account_id=&status=`；`account_id` 不是本人账户 → `404 NOT_FOUND`，v0.2.9 内 T-B46 裁定）：元素 `ImportBatchSummary {batch_id, account_id, kind, status: import_status, parser_id: string \| null, stats, created_at, committed_at: string(datetime) \| null, reverted_at: string(datetime) \| null}`（v0.2.4 #12） |
| GET | `/imports/{batch_id}` 🔒 | `{batch_id, account_id, kind, status: import_status, parser_id: string \| null, parser_version: string \| null, detected_encoding: string \| null, encoding_override: string \| null, encoding_confidence: number \| null, format_score: number \| null, detected_columns: string[], mapping: {[column]: field} \| null, snapshot_as_of: string(datetime) \| null, file_findings: ImportFinding[], stats: {rows, ok, warning, error, skipped, new, duplicate_in_db, duplicate_in_file, possible_duplicate_of_manual, needs_action_open: int}, created_at, committed_at: string \| null, reverted_at: string \| null}`。`parser_id` 取 `tdx_trades_v1` / `tdx_positions_v1`（旧名 `fmt_a_*` 作为别名接受）。轮询间隔 ≥ 1 秒，或等 SSE `notification(kind=import)` |
| GET | `/imports/{batch_id}/rows` 🔒 | 预览行（分页，`?status=&code=&dedup_status=`）：`{row_no, status: import_row_status, kind: "trade" \| "event" \| "ignored", dedup_status: dedup_status \| null, findings: ImportFinding[], raw_masked: string, normalized: {trade_date, trade_time: string \| null, security_code, name, side: trade_side \| null, qty, price, amount, fee_total: string \| null, net_amount: string \| null, biz_type_raw: string} \| null}`。`raw_masked` 是掩码后的原始行；**不返回原始股东代码或资金账号**。**v0.2.9 内，T-live-83a031c §8 裁定**：批次为 `discarded` 或 `failed` 时预览行已删除，返回 `200`、`items: []`、`next_cursor: null`（不返回 410）；批次状态与计数以 `GET /imports/{batch_id}` 的 `status`、`stats` 为准（批次头保留） |
| PUT | `/imports/{batch_id}/options` 🔒 | 改编码、解析器、列映射或快照时间并重新解析：`{encoding_override: "utf-8"\|"utf-8-sig"\|"gbk"\|"gb18030" \| null, parser_id: "tdx_trades_v1"\|"tdx_positions_v1"\|"fmt_a_trades_v1"\|"fmt_a_positions_v1" \| null, mapping: object \| null, snapshot_as_of: string(datetime) \| null}`（v0.2.9 内 T-B46 裁定：两个字段为内联取值，不进 §3；`utf8`、`gb2312`、`cp936` 等别名不再接受；`fmt_a_*` 是旧名别名；解析器与批次 `kind` 不符 → `400 VALIDATION_ERROR`（`field: "parser_id"`）） → `202 {status: "parsing"}`；只允许 `previewed`/`failed`，否则 `409 INVALID_STATE_TRANSITION` |
| POST | `/imports/{batch_id}/findings/{finding_id}/resolve` 🔒 | 处理一条提示：`{choice: string, reason: string \| null}` → `200 ImportFinding`；`choice` 须在该提示的 `resolution_choices` 中（非空即可处理，不限 `needs_action`，§4.1“处理选项”）；覆盖类选项 `reason` 必填（≤200），否则 `400 VALIDATION_ERROR`；写审计（v0.2.4 #11） |
| POST | `/imports/{batch_id}/confirm` 🔒 | 两步提交的第二步，支持 `Idempotency-Key`：`{mode: "all" \| "valid_rows_only", acknowledge_warnings: boolean}` → `200 {status: "committed", written: {trades: int, events: int, snapshot_positions: int}, reconciliation: {status: reconciliation_status, diff_count: int} \| null}`。可能返回 `422 IMPORT_FILE_ERRORS`、`422 IMPORT_ROW_ERRORS`（`mode=all` 且有 error 行）、`422 IMPORT_WARNINGS_UNACKNOWLEDGED`、`422 IMPORT_NOTHING_TO_COMMIT`、`409 INVALID_STATE_TRANSITION`。`valid_rows_only` 只写 `ok`/`warning` 且 `dedup_status=new` 的行 |
| POST | `/imports/{batch_id}/discard` 🔒 | 放弃未提交的批次 → `{status: "discarded"}`（只允许 `previewed`/`failed`）。**v0.2.9 内，T-live-83a031c §8 裁定**：同一事务删除该批次的全部预览行与解析出的未提交行级数据；批次头（`stats`、`file_findings` 等）保留；原始文件按现有留存策略处理（plan 3.5 ①）；之后对该批次 resolve 提示 → `409 INVALID_STATE_TRANSITION` |
| POST | `/imports/{batch_id}/revert` 🔒 | 回滚已提交批次 → `{status: "reverted"}` |
| GET | `/imports/{batch_id}/errors.csv` 🔒 | `text/csv; charset=utf-8`（带 BOM）：列 `row_no, code, severity, field, message, raw_masked`；只含**掩码后**的原始行；`discarded`/`failed` 批次只有表头（v0.2.9 内，T-live-83a031c §8 裁定） |
| GET/POST | `/trades` 🔒 · `/trades/{id}` 🔒 | 成交列表和手工录入；原记录不可修改，更正时写更正记录。GET `?account_id=&security_code=&from=&to=&include_voided=`（分页；`account_id` 不是本人账户 → `404 NOT_FOUND`，v0.2.9 内 T-B46 裁定），元素 `Trade {id, account_id, trade_date, trade_time: string \| null, security_code, name, side: trade_side, qty: string(decimal), price: string(decimal), amount: string(decimal), fee_total: string(decimal) \| null, net_amount: string(decimal) \| null, source: "import"\|"manual", batch_id: uuid \| null, voided: boolean, void_reason: string \| null, voided_at: string(datetime) \| null, corrects_trade_id: uuid \| null, created_at}`。POST `TradeCreate {account_id, trade_date, trade_time: string \| null, security_code, side, qty: string(decimal，pattern `^(?!0+(?:\.0+)?$)\d{1,16}(?:\.\d{1,4})?$`), price: string(decimal，pattern `^(?!0+(?:\.0+)?$)\d{1,16}(?:\.\d{1,8})?$`), fee_total: string(decimal，pattern `^\d{1,16}(?:\.\d{1,4})?$`) \| null, corrects_trade_id: uuid \| null, reason: string \| null（corrects_trade_id 非空时必填）}` → `201 Trade`，支持 `Idempotency-Key`；带 `corrects_trade_id` 时在同一事务中作废原记录并写入新记录（v0.2.4 #12；v0.2.5 删除同意要求）。v0.2.9 内 T-B46/T-B47 裁定：decimal 字段只接受字符串（JSON 数字与空串 → `400 VALIDATION_ERROR`）；`security_code`（查询参数与请求体）pattern `^(?:(?:SH\|SZ\|BJ\|sh\|sz\|bj)[0-9]{6}\|[0-9]{6}(?:\.(?:SH\|SZ\|BJ\|sh\|sz\|bj))?)$`，服务端去空白、转大写后规范为 `600001.SH` 形式；格式合法但推断不出市场 → `400 VALIDATION_ERROR`（`field: "security_code"`） |
| POST | `/trades/{id}/void` 🔒 | 作废一条成交（v0.2.4 #12）：`{reason: string(1–200)}` → `200 Trade`；已作废 → `409 INVALID_STATE_TRANSITION`；导入批次回滚造成的作废，`void_reason` 为 `"batch_reverted:{batch_id}"`；写审计 |
| GET | `/snapshots` 🔒 | 持仓快照 |
| GET | `/reconciliation?account_id=` 🔒 | 对账结果：`{status: reconciliation_status, as_of: string(datetime) \| null, items: [{kind: reconciliation_item_kind, security_code: string \| null, name: string \| null, ours: string(decimal) \| null, broker: string(decimal) \| null, diff: string(decimal) \| null, important: boolean, note: string}]}`。成本按**摊薄成本**比较（我方重建值计入分红：现金红利冲减、股息红利税补缴计入，与通达信一致，v0.2.2），容差 `max(0.01 元, 0.1%)`（plan 3.5A）；每次导入确认后重算。T-A16：`important` 只由 `kind` 决定，`quantity_mismatch`、`missing_in_broker`、`missing_in_ours` 为 `true`，其余为 `false` |
| GET | `/portfolio?account_id=` 🔒 | 持仓汇总（`account_id` 可选，不传时合并全部账户；v0.2.4 #14）：`{cash, total_assets, positions: [{security_code, name, security_type: security_type \| null, qty, sellable_qty, cost_price, market_value: string(decimal) \| null, pnl: string(decimal) \| null, pnl_pct: string(decimal) \| null, weight_pct, estimated: boolean}], exposure: {sector: [{name, pct}]}, DataStatusBlock}`。v0.2.8：持仓可含 ETF，`sellable_qty` 一律按 T+1 计算【待研究员核对：T+0 的 ETF 品种，v0.2.8 未决 U1】。**无行情的持仓行（v0.2.9，U3 已定）**：`security_type` 为 `null` 表示不在证券主数据中（本版主要是按 `import_as_is` 导入的可转债）；这类行 `estimated=true`，`market_value`、`pnl`、`pnl_pct` 为 `null`（不是 0），`weight_pct` 按成本 `qty × cost_price` 估算，`total_assets` 与 `exposure` 同样计入成本估算值，顶层 `data_status` 为 `partial`；不跑策略、不出信号、不进入风控止损计算。有现价（来源见下文 ②）的行 `estimated=false`；在证券主数据中但缺现价的行同样 `estimated=true`（v0.2.9 #31：本句原写“其他行 `estimated=false`”，与 T-B46 裁定 ② 矛盾，以裁定 ② 为准）。**v0.2.9 内 T-B46 裁定**：① 字段名以本行为准（`security_type`，不是 `instrument_kind`；顶层没有 `estimated`）；② 现价来源依次为（只适用于 `security_type` 非 null、即在证券主数据中的行；v0.2.9 内 T-T25 裁定：`security_type=null` 的行即使最近一次持仓快照中有参考价也**不**采用，一律按成本估算，`estimated=true`、`market_value`/`pnl`/`pnl_pct` 为 null，因为无法对照主数据核实其价格口径与单位，如可转债每张面值 100 元）：该证券最近一个交易日的日线收盘价（只读库内已有数据，不触发拉取）→ 最近一次持仓快照中的参考价 → 都没有时该行按成本估算，`estimated=true`，`market_value`、`pnl`、`pnl_pct` 为 null（与可转债行相同，问题 79）；③ `cash`、`total_assets`、`qty`、`sellable_qty`、`cost_price`、`weight_pct` 不为 null（没有现金记录时 `cash="0.00"`，并在 `gaps` 中列 `{key:"cash", reason:"user_input_missing"}`）；④ 行业数据未接入时 `exposure.sector=[]`、`gaps` 含 `{key:"exposure.sector", reason:"no_source"}`，这一项不单独把 `data_status` 降为 `partial`。**v0.2.9 #30**：行业数据已接入时，没有行业归属的持仓行（可转债等 `security_type=null` 的行，以及主数据中没有行业的证券）按成本估算值合并为一项 `{name:"未分类", pct}` 计入 `exposure.sector`，使各项合计等于全部持仓；`未分类` 不是行业，不参与 RC4 行业集中度判断（plan 第 9 节问题 85）。**v0.2.9 #31（T-B46-47 前端待定）**：① 顶层**没有** `estimated`，是否估算只看持仓行上的 `estimated`；② 任一行 `estimated=true`（不论 `security_type` 是否为 `null`）时顶层 `data_status` 为 `partial`；除 `exposure.sector` 外的任一缺口（含 `cash`）同样使其为 `partial`；没有这些缺口时按现价时点取 `fresh`/`stale`；③ 估算行在 `gaps` 中按原因各列一项（同一原因只列一项）：不在主数据中且代码属可转债段 `{key:"positions.convertible_bond", reason:"no_source"}`；其他不在主数据中的 `{key:"positions.unknown_security", reason:"no_source"}`；在主数据中但既无日线收盘价也无快照参考价 `{key:"positions.price", reason:"no_source"}`；④ 估算行不加原因字段：前端对 `security_type=null` 的行标“不在主数据·估算”，其余估算行只标“估算”，原因在页面说明中按 `gaps`/`security_type` 分开写（plan 第 9 节问题 87） |

**T-A12 裁定（架构师 2026-11-07，T-B77 MVP 最小方案）**：
1. **多账户时默认用哪个账户**：`/terminal` 和 `/today` 用同一规则。
   - 传了 `account_id` 时：本人账户直接用；他人账户或不存在的账户返回 `404`。
   - 没传时：取本人未归档账户中 `created_at` 最早的一个，相同时按 `id` 升序，结果在响应的 `account_id` 字段里回显。
   - 没有账户时返回 `200`：`account_id=null`，持仓相关列表为空，不返回 `503`。
   - 本 MVP 不加“默认账户”字段，也不做跨账户合并；用户可设的默认账户，以及多账户合并，都列入 T-B79。
2. **受审交易日历**：唯一读取来源是表 `market.trading_calendar`，导入流水线已经在用这张表，求交易日和 `market_session` 的时钟也读它。
   - 数据靠种子文件写入：后端新增 `config/trading_calendar.json`，格式沿用 `financial_basis.TradingCalendar`，即 `{coverage_start, coverage_end, open_days[], source}`。
   - 种子文件登记进 `REFERENCE_FILES`，并提供一个幂等的种子命令，把覆盖范围内每一天按 `is_open` 写入表。
   - 内容由研究员按交易所官方发布的年度休市安排整理，写明来源公告的 URL 和发布日期，并逐日核对；A 股周末调休日不开市。只覆盖已经公布的年份，不外推。
   - 本 MVP 不调麦蕊 `/tcalendar`。以后接入时用来对账，结果不一致只告警，不覆盖种子数据。
   - 日期不在覆盖范围内时返回 `503 CALENDAR_NOT_COVERED{date, coverage_start, coverage_end}`，继续不猜工作日。

**T-A16 裁定（架构师 2026-11-07，T-B77 收口）**：
1. `/today.focus`：从本人全部行中取，不受 `/terminal` 300 行截断影响；范围是持仓 ∪ 重点关注，持仓按 `weight_pct` 降序在前，重点关注按加入时间；最多 50 条，超出 `more=true`。
2. `/terminal`、`/today` 不再用 `503` 表示“未接线”：没有记录就是空集合；有建议、草案、原因、风控事件、提醒、计划时按本节既有定义聚合；非空对账按 §5.3 T-A16 计数。保留的 503 只有上一条的 `CALENDAR_NOT_COVERED`。
3. `reconciliation.diff_count`、`important_count` 与 §5.3 同一口径。


### 7.3 自选、行情与证券
| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST/PATCH/DELETE | `/watchlist` 🔒 · `/watchlist/{security_code}` 🔒 | GET（不分页）→ `{items: WatchlistItem[], caps: {watchlist: int, focus: int}}`；POST `{security_code, group: string \| null, note: string \| null}` → `201 WatchlistItem`；PATCH `{group?, note?}`。超出上限返回 `403 ENTITLEMENT_LIMIT_REACHED{key:"watchlist.per_user_cap"}`（上限数值 **待 T003 验证**） |
| PUT | `/watchlist/{security_code}/focus` 🔒 | 设为重点关注 `{focus: boolean}` |
| GET | `/securities/search` 🔒 | v0.2.7。`?q=`（必填，归一化后长度 1–20）`&types=`（逗号分隔 `security_type`，默认 `stock,cdr,etf`；v0.2.8 加 `etf`）`&include_delisted=false&limit=`（默认 20，最大 50），**不分页** → `{items: SecurityHit[], master_as_of: string(date)}`。**归一化**：NFKC、去空白、字母转大写；`600000.SH`、`SH600000`、`sh600000`、`600000` 都按代码处理。**匹配范围**：6 位代码、简称、拼音首字母（例如 `PFYH`）、曾用名、北交所旧代码（经 `security_code_history` 解析到新代码，`match_kind=former_code`）、模糊匹配（`pg_trgm` 相似度 ≥ `search.similarity_threshold`，默认 0.3；查询中至少有 2 个汉字才启用）。**排序**：先按 `security_match_kind` 层级（`code_exact` > `name_exact` > `initials_exact` > `code_prefix` > `name_prefix` > `initials_prefix` > `name_contains` > `former_name` = `former_code` > `fuzzy`）；同层依次比较：`listing_status`（`listed` 优先，其次 `delisting_period`，其余靠后）→ `type`（`stock` > `cdr` > `etf` > `index`；v0.2.8）→ 命中位置（越靠前越优先）→ 简称长度（短的优先）→ trgm 相似度（降序）→ `security_code`（升序）。同一证券只出现一次，取最高层的命中。**拼音首字母**：用 pypinyin 生成，多音字的组合最多 16 个（`search.initials_max_variants`）；另外生成去掉 `ST`/`*ST` 前缀的版本；巨潮提供的拼音只用于交叉校验。`include_delisted=false` 时排除 `delisted`，`missing_from_list` 仍返回。默认不含指数（v0.2.7 未决 Q6）；默认含 ETF（v0.2.8），只要股票时传 `types=stock,cdr`；可转债不收录，搜不到。**v0.2.9 内，T-A04 补充**：① 检索走 `market.security_search_terms`（plan 4.6.3），词条分 5 类：当前简称、当前简称的拼音首字母、曾用名、曾用名的拼音首字母、北交所旧代码；6 位代码直接按 `securities.code` 匹配；曾用名首字母命中归入 `former_name`（与曾用名同层），`matched_text` 为曾用名原文；首字母词条只含大写字母与数字（`*` 等符号去掉），简称中原有的字母、数字原样保留；② 只返回主数据中的证券：麦蕊有、交易所没有的代码（`vendor_unknown`）进隔离区，搜不到（plan 第 9 节问题 91）；`missing_from_list` 照常返回；③ `master_as_of` = 三家交易所列表最近一次成功合并的快照日期中最早的一个（某所整份拒收时沿用前一日，日期不前进）；④ `type`、`listing_status`、`risk_flag`、`match_kind` 的取值以 `/meta/enums` 的 `security_type`、`listing_status`、`security_risk_flag`、`security_match_kind` 为准（§3），本接口不另设取值；前端显示名由前端维护；⑤ 最多返回 `limit` 条（默认 20，最大 50，plan 6.1 `search.limit_default`/`limit_max`）；⑥ 错误码：`400 VALIDATION_ERROR`（`fields[].field` 为 `q`、`types`、`limit`、`include_delisted`；`types` 含未知值也属此类）、`401 AUTH_REQUIRED`、`403 ACCOUNT_NOT_APPROVED`、`429 RATE_LIMITED`（全站限速，及本接口单独限额，#41）；查询串过长由网关返回 `414 URI_TOO_LONG`；本接口不返回 `503`（部署时先完成首次主数据导入，plan 4.6.6）；首导未完成（任一交易所从未有成功合并快照）→ `500 INTERNAL_ERROR{issue:"security_master_bootstrap_required"}`，某所曾成功而当日整份拒收 → 按上文 ③ 沿用旧日、`200` 正常返回（v0.2.9 内，T-B94 裁定，docs/reviews/T-B94-master-as-of-ruling.md）。缓存：`Cache-Control: private, no-store`（v0.2.9 #41，原为 `private, max-age=60`）；网关对本接口单独限流（每客户端 5 r/s、burst 20，超限 `429 RATE_LIMITED`，#41）。q 为空或归一化后超长、`limit` 越界 → `400 VALIDATION_ERROR`。只查证券公开主数据，不触发麦蕊拉取，也不受证书影响（`quote_missing` 除外） |
| GET | `/securities?q=` 🔒 | 证券搜索（不分页，最多 20 条）：`[{security_code, name}]`。**v0.2.7 起为 `/securities/search` 的别名**，`types` 和 `limit` 取默认值，返回结构保持不变；新代码请改用 `/securities/search` |
| GET | `/securities/{code}` 🔒 | v0.2.7。`SecurityProfile`（§5.1），弱 ETag。不存在 → `404 NOT_FOUND`；北交所旧代码 → `404 NOT_FOUND{superseded_by}`。公开主数据每日 18:00 更新、次日 07:30 补拉（北京时间，周一至周五；T007 §6；v0.2.9 内 T-A04：来源为交易所公开列表，plan 4.6.5）；行业、概念、股本按本人证书每日盘后更新；`suspended` 每个交易日 09:15 前按本人证书刷新【待 T003 补测：停牌标记的来源端点】 |
| GET | `/securities/{code}/financials` 🔒 | v0.2.7。`?report_period=`（可多值，默认全部）`&limit=`（默认 8，最大 40）`&as_of=`（日期，可选：只返回 `available_from ≤ as_of` 的报告期，时点视图）→ `{security_code, name, items: FinancialPeriod[]（period_end 降序）, sources: ProviderRef[], data_status, data_as_of, gaps}`，**不分页**。同一报告期有更正时只返回最新一版，`is_restated=true`。指数或无财务数据的证券：`200`，`items: []`，`data_status:"unavailable"`，`gaps:[{key:"financials", reason:"no_source"}]`。ETF（v0.2.8）：同样 `200`、`items: []`、`data_status:"unavailable"`，但 `gaps:[{key:"financials", reason:"not_applicable"}]`；指数保持 `no_source`。更新：每日盘后按本人证书增量拉取【待 T003 补测：财报端点与 `announce_date` 字段是否可得】 |
| GET | `/securities/{code}/fund-flows` 🔒 | v0.2.7。`?days=`（默认 60，最大 250）或 `?from=&to=`（日期，区间不超过 250 个交易日；两种方式同时给出 → `400 VALIDATION_ERROR`）→ `{security_code, name, items: FundFlowDay[]（trade_date 升序）, sources, data_status, data_as_of, gaps}`，不分页。停牌日不出行。当日数据在盘后更新（15:40 后）【待 T003 补测：更新时刻】，入库前不出当日行；更新后还会再次校准的日期 `is_final=false`。指数 → `200` 空 `items` + `no_source` gap；ETF（v0.2.8）→ `200`、空 `items`、`data_status:"unavailable"`、`gaps:[{key:"fund_flows", reason:"not_applicable"}]` |
| GET | `/securities/{code}/factors` 🔒 | v0.2.7。`?trade_date=`（可选，默认最新）`&category=`（可多值）→ `{security_code, name, trade_date, factor_set_version: string, counts: {total: int, by_category: object<factor_category, int>}, items: FactorValue[], sources, data_status, data_as_of, gaps}`，不分页。因子数量为 85 个（77 个日频 + 8 个日内）【待 T003 补测：最终数量与单位】。北向资金类因子取不到时 `value` 为 `null`，并带 `gaps[{key:"factor.<id>", reason:"no_source"}]`。**不提供行业内分位**（v0.2.7 未决 Q4）。每日盘后按本人证书更新。ETF（v0.2.8）→ `200`，`items: []`，`counts.total: 0`，`data_status:"unavailable"`，`gaps:[{key:"factors", reason:"not_applicable"}]` |
| GET | `/securities/{code}/announcements` 🔒 | v0.2.7。§1.2 游标分页（默认 `published_at desc, id desc`）；`?from=&to=&category=` → `Paged<Announcement> & {disclaimer: string, sources, data_status, data_as_of, gaps}`。`disclaimer` 为固定文案：“公告内容以交易所及上市公司披露原文为准，本系统仅提供标题与原文链接。” 每日盘后按本人证书更新，盘中不刷新【待 T003 补测】。ETF（v0.2.8）：本版不收录基金公告 → `items: []`，`data_status:"unavailable"`，`gaps:[{key:"announcements", reason:"not_applicable"}]` |
| GET | `/market/sector-flows` 🔒 | v0.2.7。`?kind=industry\|concept`（必填）`&sort=`（`sector_sort`，默认 `main_net_desc`）`&limit=`（默认 20，最大 100），不分页 → `{kind, taxonomy: industry_taxonomy \| null（concept 时为 null）, trade_date, items: SectorFlow[], sources, data_status, data_as_of, gaps}`。**盘后数据**：每个交易日 15:40 后按本人证书更新一次，盘中返回上一交易日的数据；不提供盘中实时数据，前端不必轮询（响应带弱 ETag）。**`data_as_of` 可空（A-12）**：本人证书从未取到资金流时 `data_status=unavailable`、`data_as_of=null` |
| GET | `/quotes?codes=600000.SH,000001.SZ` 🔒 | 只读缓存，**从不触发上游调用**：`{items: [{security_code, name, price, change_pct, volume, amount, t, DataStatusBlock}]}`；`codes` 最多 200 个；ETF 与股票同口径（v0.2.8；价格保留 3 位小数）【待 T003 补测：麦蕊 ETF 实时行情是否可用】 |
| GET | `/securities/{code}/bars` 🔒 | 参数 `freq: bar_freq`（必填）、`adjust: bar_adjust`（日/周默认 `qfq`，`1m` 只能 `none`）、`from`/`to`（`string(date)`）或 `before` + `limit`（向前翻页，`limit` 默认 500、最大 2,000）。响应 `{security_code, name, freq, adjust, pre_close: string(decimal) \| null（1m 时为所请求首个交易日的前收，作分时基准）, items: Bar[]（按 t 升序）, next_before: string \| null, DataStatusBlock}`。缓存里没有时返回 `data_status:"pending"` 并按本人证书加入回补队列，**不同步等待**。v0.2.7：增加 `freq=w` 的口径（§6.2）；`Bar` 加 `is_final`；响应顶层加 `adjust_as_of: string(date) \| null`（前复权的基准日；`adjust=none` 时为 `null`），客户端发现 `adjust_as_of` 变化时，必须丢弃已缓存的同证券、同复权方式的 bar 并重新加载。ETF（v0.2.8）照常提供，价格保留 3 位小数；ETF 的复权口径【待 T003 补测】 |
| GET | `/market/overview` 🔒 | 大盘、宽度、regime、涨跌停统计（v0.2.3 最小结构，只读缓存）：`{trade_date: string(date), session: market_session, indices: [{security_code, name, price: string(decimal) \| null, change_pct: string(decimal) \| null, amount: string(decimal) \| null, t: string(datetime) \| null}], breadth: {up: int, down: int, flat: int, limit_up: int, limit_down: int} \| null, regime: market_regime \| null, regime_position_range: {min_pct, max_pct} \| null, turnover_total: string(decimal) \| null, DataStatusBlock}`。指数清单由后端配置，不在契约中写死。**`data_as_of` 可空（A-12，T-A53 第 4 条的直接推论）**：全部输入从未取到（indices 各 `t` 全 null）时 `data_status=unavailable`、`data_as_of=null` |
| GET | `/terminal` 🔒 ⚖ | **终端一屏聚合**（ETag）：`?scope=all\|watchlist\|holdings`（默认 `all`）`&account_id=`（默认用户的默认账户）。→ `{server_time, trade_date: string(date), session: market_session, account: {account_id, total_assets, cash_available, position_pct, pnl_day, regime: market_regime \| null, regime_position_range: {min_pct, max_pct} \| null, data_status} \| null, rows: TerminalRow[], truncated: boolean, unread_notifications: int}`。不分页，`rows` 最多 300 行（持仓在前按 `weight_pct` 降序，其次重点关注、其余自选按加入时间），超出时 `truncated=true`。`trade_date` 为行情所属交易日（非交易日为最近一个交易日）；`account.cash_available` = 可用资金：最近一次券商资金快照的“可用”，没有快照时等于重建的现金余额 `cash`（v0.2.3 定义）。服务端**固定次数查询**完成（无 N+1，T-B44 测试查询数）；只读缓存，不触发上游。客户端以 SSE `quote`/`suggestion`/`candidate_signal` 增量更新；SSE 断开时才轮询，间隔 ≥ 15 秒并带 `If-None-Match`。ETF 行（v0.2.8）照常显示行情，不显示策略建议和候选信号 |
| GET | `/today` 🔒 ⚖ | 首页聚合（ETag；前端首页为 `/today`，`/` 重定向到 `/today`，v0.2.8）：`{server_time, trade_date, session: market_session, market: {regime, regime_position_range, data_status}, focus: {items: TerminalRow[], more: boolean}, pending_plan_drafts: {items: [{id, security_code, name, action, valid_until, status: plan_draft_status}], more}, released_reasons: {items: [{reason_id, signal_id, code: reason_code, security_code, name, released_at}], more}, risk_flags: {items: [RiskFlag & {security_code: string \| null, name: string \| null, risk_event_id: uuid \| null（v0.2.7）}], more}, invalidations_today: {items: [{suggestion_id, security_code, name, strategy_key, text, at}], more}, daily_report: {date, status: "ready" \| "generating" \| "not_yet"}, reconciliation: {status: reconciliation_status, as_of, diff_count, important_count}, unread_notifications: int}`；v0.2.7 新增 `alerts`、`plan_triggers`、`data_gaps`、`evidence` 四个顶层字段，见下方 `/today` 补充。每个列表最多 50 条，`more=true` 时的去向见下方“查看全部”去向表（v0.2.7） |

`/securities/*` 全部响应（含 `304`、错误）带 `Cache-Control: private, no-store`（v0.2.9 #41）。所有 v0.2.7 新增的个股读接口：`{code}` 不存在 → `404 NOT_FOUND`；用北交所旧代码 → `404{superseded_by}`；参数越界 → `400 VALIDATION_ERROR`；限流 → `429 RATE_LIMITED{retry_after_s}`。**不返回** `409 DATA_LICENCE_UNAVAILABLE`（§1.1）。弱 ETag 与 §1 相同。

#### `/today` 补充（v0.2.7，在原响应结构上新增字段）
新增顶层字段（都必须出现）：
```text
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
- `gap_reason` 即 §1.1 `gaps[].reason` 的取值集合。
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
| `risk_flags` | `/risk-controls?tab=events` | `GET /risk-controls/events?status=active` |
| `invalidations_today` | `/suggestions?status=invalidated` | `GET /suggestions?status=invalidated` |
| `alerts` | `/alerts` | `GET /alerts?status=new,read` |
| `plan_triggers` | `/plans?status=triggered` | `GET /plans?status=triggered` |
| `data_gaps` | 无（`more` 恒为 false） | — |

### 7.4 策略：L1 卡片、特征白名单、L2 模板与生命周期
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/strategy-cards` 🔒 | `?completeness=&horizon=&category=`；元素 `{id, key, name, category, horizons, completeness, current_version_no, source_kind, performance: {win_rate_5d: Stat, avg_excess_5d: Stat} \| null}` |
| GET | `/strategy-cards/{id}` 🔒 | 卡片当前版本：2.5.14 B 节的全部字段，加 `field_epistemic`、`narrative`、`gates_missing: string[]`（例如 `["G1:stop_loss_to_quantify"]`）、`refs: [{ref: string, title: string, url: string \| null}]`（研究员文档的出处编号，如 `R12`；**不是**列表项中引用规则的 `ref: <rule_id>`）、`validation_summary: {type: string, window: string \| null, benchmark: string \| null, cost_model: string \| null, oos_result: string \| null, trade_log_ref: string \| null} \| null`（研究员文档中的**外部**验证信息，产品不做回测）、`risk_level: card_risk_level` |
| GET | `/strategy-cards/{id}/versions` 🔒 · `/strategy-cards/{id}/versions/{no}` 🔒 | 版本历史，内容不可变 |
| POST | `/strategy-cards` 🔒 | 用户私有卡片（字段同 2.5.14 B 节）→ `201`；可能返回 `422 STRATEGY_INVALID_CONFIG` |
| POST | `/strategy-cards/{id}/versions` 🔒 | 新版本（`base_version_no` 乐观锁）；可能返回 `409 VERSION_CONFLICT` |
| POST | `/strategy-cards/{id}/promotion-requests` 🔒 | 申请晋级，后台跑 G1–G6 → `202 {review_id}`。**T-A18**：请求体 `{version_id}`；审核绑定 `(card_id, version_id, content_sha256)`（取该版本当前内容哈希）。同一绑定已有 `pending` 且非 stale 的审核时返回 `202` 与该 `review_id`（幂等，不重跑）；版本不是 `draft` → `409 INVALID_STATE_TRANSITION` |
| GET | `/promotion-requests/{review_id}` 🔒 | `{review_id, card_id, version_id, version_no, content_sha256, stale: boolean, submitted_by, submitted_at, reviewer_id: string \| null, decided_at: string(datetime) \| null, decision: "pending"\|"approved"\|"rejected"\|"changes_requested", gate_results: [{gate: "G1".."G7", result: "pass"\|"fail"\|"warn"\|"skipped", detail}], fixture_runs: [{fixture_id, passed, diff}], g6_report: {trigger_rate: Stat, coverage: Stat, max_jaccard: string(decimal) \| null, max_jaccard_null_reason: "no_history" \| "no_comparable_set" \| null, quota_delta_per_min: int | null}}`。**T-A21**：卡片有尚未落地的 `feature_requests` 时 `quota_delta_per_min` 为 `null`（不填 0），G6 `detail` 写明“含待落地特征，配额增量未知”，只让 G6 至多 `warn`；前端显示“—”。**T-A17**：`max_jaccard` 无值时为 `null`，不填 0；`max_jaccard_null_reason` 在有值时为 `null`、无值时必填：`no_history` 为本卡近 120 日历史不足或未体检，`no_comparable_set` 为没有可比较的其他模板命中集合（无其他模板，或对方/本方命中集合为空）。无值只让 G6 的 `result` 至多为 `warn`、`detail` 写明原因码，**不单独导致 `fail`**，也不算 `pass` 重合度检查 |
| GET | `/admin/promotions` 🛡 | **T-A18**：§1.2 分页，排序 `submitted_at desc, review_id desc`。`?decision=`（逗号分隔多值）`&card_id=&version_id=&stale=true\|false`（默认 `false`）。非法筛选值 → `400 VALIDATION_ERROR`。stale 定义：审核绑定的 `version_id` 已不是该卡最新版本，或该版本当前 `content_sha256` 与绑定值不同；**T-A20**：T-A18 之前没有绑定的历史审核一律 stale，`version_id`、`content_sha256` 可为 null，不按现内容补算哈希，正常返回 `200`（不返回 503）；元素加 `stale_reason: "new_version"\|"content_changed"\|"legacy_unbound" \| null`（非 stale 为 null）；历史审核只读展示，要晋级须重新申请；stale 审核保留原 `decision` 只读展示，不可再决定或用于晋级。元素 `PromotionSummary {review_id, card_id, card_key, version_id, version_no, content_sha256, lifecycle（版本当前生命周期）, stale: boolean, decision, gates: [{gate: "G1".."G6", result: "pass"\|"fail"\|"warn"\|"skipped"}]（G1–G6 各一条，按序；未跑完的为 `skipped`）, g7: "pending"\|"approved"\|"rejected"\|"changes_requested", submitted_by, submitted_at, reviewer_id: string \| null, decided_at: string(datetime) \| null}`；详情仍走 `GET /promotion-requests/{review_id}` |
| POST | `/admin/promotions/{review_id}/decision` 🛡 | 审核决定 `{decision: "approved"\|"rejected"\|"changes_requested", comment: string(1–500), ack_warn_gates: ("G1".."G6")[], password: string}` → `200 PromotionSummary`。G7 文案需通过禁用词校验，否则返回 `422 COMPLIANCE_LINT_FAILED{terms}`。**T-A18**：① `approved` 要求 G1–G6 无 `fail`（否则 `422 PROMOTION_GATES_NOT_MET{gates}`），且每个 `warn` 门禁都列在 `ack_warn_gates` 中（否则 `422 PROMOTION_WARN_UNACKNOWLEDGED{gates}`）；`rejected`/`changes_requested` 不校验门禁。② stale 审核不能做任何决定 → `409 PROMOTION_STALE{current_version_id}`；已决定的审核再次决定 → `409 INVALID_STATE_TRANSITION`。③ **G7 须经管理员可信交互会话批准（T-A18/T-A20；代批程序见 T-A109）**：只接受浏览器交互登录会话（cookie 会话 + CSRF），API token、服务账号、脚本或代理凭据一律 `403 HUMAN_SESSION_REQUIRED`；**T-A20 可信交互会话**：服务端会话须带 `origin: "password_login"`（只由 `POST /auth/login`、`POST /auth/password` 写入；任何令牌签发或其他途径建立的会话没有此值），没有则 `403 HUMAN_SESSION_REQUIRED`；且每次请求须**重新输入本人密码**（`password`），服务端按会话用户核对，错误 → `401 REAUTH_FAILED`，计入登录失败锁定（同 `ACCOUNT_LOCKED`）；密码只用于本次核对，不落库、不进日志或审计。不设最近登录时间窗口。前端密码框 `autocomplete="new-password"`（T-A21：Chromium 常不理会 off），不放进可被浏览器记住的表单，不预填；脚本与未获授权的代理不得代填密码或用非交互方式提交；按 T-A109，编排者可在用户本人授权覆盖的卡片上、于本款所述可信交互会话中代批，批注与审计须引用该授权（用户原话、日期、覆盖的策略卡），且缺证据项为 0、G1–G6 结论齐备；用户私有模板仍由该用户本人确认（细则见 `docs/reviews/T-A109-g7-delegation.md`）；`reviewer_id` 取自会话用户，请求体传入一律忽略；MVP 单管理员时允许本人既提交又审核。④ 每次决定写审计日志（review_id、reviewer_id、decision、ack_warn_gates、comment、时间、来源 IP 粗粒度） |
| GET | `/feature-catalog` 🔒 | 只读，不分页：`[{feature_key, description, dimension, frequency, adjust, unit, warmup_bars, available_at, status: "declared"\|"verified_doc"\|"verified_live"\|"gap"\|"deprecated", epistemic_type}]`；T-A13：`description`、`dimension`、`warmup_bars`、`available_at`、`epistemic_type` 都可以为 `null`（研究员未提供时） |
| GET | `/strategies` 🔒 | L2 模板：`?horizon=&lifecycle=&security_code=`（反查适用的模板）`&risk_level=`（v0.2.7），§1.2 分页；元素 `{id, key, name（即其他对象中的 strategy_name）, horizons, risk_level: card_risk_level, current_version: {id, version_no, lifecycle}, health: {state, weight: string(decimal), n: int} | null（T-A13：无健康记录时为 null）}`。`risk_level` 取当前版本关联的 L1 卡片版本的值；未关联卡片时为 `normal`；派生版本继承母版本的值（v0.2.7） |
| GET | `/strategies/{id}/versions/{vid}` 🔒 | 不可变配置（2.5.14 C 节），加 `lifecycle`、`card_version_id`、`risk_level: card_risk_level`（v0.2.7，取该版本自身关联的卡片版本；未关联为 `normal`）、`param_hash`、`parent_version_id`、`internal_check: {done: boolean, method_types: ("factor_ic" \| "event_study" \| "param_robustness")[], checked_on: string(date) \| null}`（方案 A：用户只看到是否做过内部检验、方法类型和日期，**不含任何数值或通过与否**） |
| POST | `/strategies/{id}/versions/{vid}/derive` 🔒 | 改参派生私有版本 `{param_overrides: object}` → `201 {version_id}`；可能返回 `422 STRATEGY_PARAM_OUT_OF_RANGE{param, min, max}` |
| GET | `/strategies/{id}/versions/{vid}/tracking` 🔒 | `?scope=mine\|site`（默认 `mine`，v0.2.9）。`site` 为全站匿名汇总：只含策略级聚合数字，不含任何用户或个股持仓信息，只对登录用户在策略页展示（plan 第 9 节问题 14）。跟踪统计：`{scope: "mine"\|"site", by_horizon: [{horizon_days: 1\|5\|20, win_rate: Stat, avg_return_pct: Stat, avg_excess_pct: Stat, profit_loss_ratio: Stat, max_loss_streak: int}]}` |
| GET | `/strategies/{id}/versions/{vid}/lifecycle-events` 🔒 | 生命周期历史 |
| POST | `/admin/strategies/{id}/versions/{vid}/lifecycle` 🛡 | `{to: lifecycle, reason: string, review_id: string \| null, password: string \| null}` → `200 {from, to}`；可能返回 `409 INVALID_STATE_TRANSITION` 或 `422 PROMOTION_GATES_NOT_MET{gates}`。**T-A18**：审核与晋级保持两步。`draft→simulating` 必须带 `review_id`，该审核须 `approved`、非 stale，且绑定的 `version_id`、`content_sha256` 与本版本当前值一致；缺失或未批准 → `422 PROMOTION_GATES_NOT_MET`，stale 或哈希不一致 → `409 PROMOTION_STALE{current_version_id}`。鉴权同 decision（浏览器交互会话，否则 `403 HUMAN_SESSION_REQUIRED`；所有 lifecycle 转换都须带 `password` 重新验证（T-A21 收紧，原 T-A20 只要求 `draft→simulating`）；`password` 缺失或为 null → `400 VALIDATION_ERROR`，**不计入**登录失败锁定，只有密码错误才 `401 REAUTH_FAILED` 并计数），写审计日志。`simulating→published` 另按 plan 2.5.13 条件，本条不变 |
| GET | `/horizon-assessments?security_code=` 🔒 | 周期分类结果（版本化）：`{suitable: horizon[], scores: {intraday_t: int, short: int, swing: int, long: int}（四个都有，0–100，不为 null）, reasons: [TextWithEvidence & {horizon: horizon, polarity: "for" \| "against"}]（每个周期 2–4 条，`reasons_per_horizon`）, inputs_missing: string[], caps: HorizonCap[], hints: HorizonHint[], classifier_version: string, snapshot_id: string, evidence: Evidence[]}`（v0.2.2；v0.2.3 加 `caps`、`snapshot_id`、`evidence`；规则见 plan 6.1 `horizon_classifier.yaml`）。`reasons[].evidence_ids` 只在本响应的 `evidence[]` 中解析。`classifier_version` 匹配 `^(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)$`（如 `"1.2.0"`）。`inputs_missing`：所有周期合计缺失的 feature_catalog 键（`f.*`），去重、升序，永不为 `null`，无缺失为 `[]`；画像未填（`profile.*`）不进此数组，也不封顶、不提示；画像已填写且不满足画像类规则时只进 `hints[]`（v0.2.5，永不为 null）。用户可自由为任何周期创建实例，不需要确认（plan 2.5.3）。**v0.2.9 内 T-B47 裁定**：`security_code` pattern `^(?:(?:SH\|SZ\|BJ\|sh\|sz\|bj)[0-9]{6}\|[0-9]{6}(?:\.(?:SH\|SZ\|BJ\|sh\|sz\|bj))?)$`（不符 → `400 VALIDATION_ERROR`）；格式合法但推断不出市场或不在证券主数据中 → `404 NOT_FOUND`。结果**落库**：读本人、该证券、当前 `classifier_version` 的最新一条 `symbol_horizon_assessments`（plan 3.3），若没有，或其输入快照的 `data_as_of` 早于库中该证券最新一根日线的日期，则同步计算一次并写入（`trigger=on_demand`）后返回；`snapshot_id` 是这条记录对应的 `data_snapshots.id`（`purpose='horizon'`，带本人 `user_id`，用到证书数据时带 `licence_id`），在库中可查到。同一输入重复请求返回同一条记录。**v0.2.9 #31（T-B46-47 前端待定，前端显示口径）**：某周期不在 `suitable` 中、`caps` 中有该周期 `kind="data_missing"` 的封顶、且**没有**该周期 `kind="gate"` 的封顶时，该周期显示“数据不足”（gate 优先：硬门槛已排除的周期不显示“数据不足”）；`suitable=[]` 且至少一个周期显示“数据不足”时整体显示“数据不足”，否则整体显示“—”；界面不出现“都不适合”。判定只用本响应的 `suitable` 与 `caps`，不用分数与阈值（plan 第 9 节问题 89） |

**T-A13 裁定（架构师 2026-11-07，T-B71 MVP 最小方案）**：
1. **`/strategies` 的 `health`** 类型改为 `{state, weight, n} | null`。版本还没有健康记录时（例如 draft，或刚进入 simulating）返回 `null`，不返回 `503`，也不造一个默认的 `published` 状态。前端显示“暂无健康度”。`/strategies/{id}` 等其他带 health 的地方同样处理。
2. **feature 元数据放在哪**：放在 `feature_catalog` 表，增加三个可空列：`dimension`（2.5 节的六维枚举）、`warmup_bars int`、`epistemic_type`（§3 枚举）。
   - `available_at` 直接序列化表里已有的 `pit_rule`，不另加列。
   - `description` 复用已有列。
   - 迁移由后端做，只加列，不回填猜测值。
3. **缺省规则**：
   - 研究员没有提供的字段，API 一律返回 `null`；`description` 缺失时返回 `null`，不拿 `feature_key` 代替。
   - 不按工作日、数据源或频率去推断类型和预热长度，`503` 取消。
   - 缺元数据不影响 G2 判定：G2 只看 `status` 和白名单。
4. **内容来源**：研究员新增 `docs/strategies/feature_catalog_meta.yaml`，由 cards-import 写入上面这几列。MVP 只需覆盖 H-01、W-01，以及系统组件 G-01、G-02、N-01 用到的全部 `f.*`。每个键一条：
   - `feature_key`
   - `description`：中文一句话
   - `dimension`：technical/capital/fundamental/sentiment/sector_market/news 之一
   - `warmup_bars`：需要的历史根数，没有回看就填 0
   - `available_at`：可得时点，例如“T 日 15:05 收盘定版后”或“公告日 plrq 次日”，与 feature_spec 的 PIT 口径一致
   - `epistemic_type`：fact/estimate/hypothesis/execution 之一
   - `spec_ref`：feature_spec 中的条目号，例如 F49


### 7.5 L3 实例、限制与风控
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/strategy-instances` 🔒 | v0.2.7。`?status=`（可多值，默认 `proposed,active,paused`；要包含已归档需显式传 `archived`）`&strategy_id=&strategy_version_id=&horizon=&scope=&account_id=&security_code=&origin=&risk_level=&order=`（`instance_sort`，默认 `created_at_desc`；同值时按 `id` 同向排序），§1.2 游标分页 → `Paged<StrategyInstance>`。游标与本次的筛选或排序不一致 → `400 INVALID_CURSOR` |
| POST | `/strategy-instances` 🔒 | POST `{strategy_version_id, scope: "account"\|"security"\|"watch_group", account_id, security_code: string \| null, horizon, param_overrides: object \| null, budget_amount: string(decimal) \| null}` → `201 {id, status:"active", derived_strategy_version_id: uuid \| null, warnings: string[]}`。按 I1–I7 校验，可能返回 `STRATEGY_VERSION_NOT_RUNNABLE`、`STRATEGY_HORIZON_MISMATCH`、`STRATEGY_PARAM_OUT_OF_RANGE`、`ENTITLEMENT_LIMIT_REACHED`、`INSTANCE_SCOPE_INVALID`。周期分类判定不适合或画像低于卡片 `fit` 下限时正常 201，`warnings[]` 给出中文说明（v0.2.5：`fit_ack` 作废）；画像相关字段未填写时不给画像提示；画像不匹配不降低后续建议的 `confidence`（v0.2.6，T006e）；`risk_level: high` 的模板也无需确认字段。创建的实例 `origin="user"`（v0.2.7）。v0.2.8：`scope="security"` 且证券为 ETF → `422 INSTANCE_SCOPE_INVALID{scope, security_code, security_type:"etf", issue:"security_type_not_supported"}`；代码不在证券主数据中 → `422 INSTANCE_SCOPE_INVALID{scope, security_code, issue:"unknown_security"}`（v0.2.8 补充；§6.0A 第 8 条） |
| GET/PATCH | `/strategy-instances/{id}` 🔒 | GET → `StrategyInstance`（§5.1，v0.2.7）；他人或不存在的 → `404 NOT_FOUND`。PATCH `{param_overrides?, budget_amount?}`；改参会生成新的派生版本；archived 实例 → `409 IMMUTABLE_RESOURCE`（v0.2.7） |
| POST | `/strategy-instances/{id}/confirm` · `/pause` · `/resume` · `/archive` 🔒 | 见 §6.0A（v0.2.7）：→ `200 StrategyInstance`；目标态即当前态时返回 200（幂等）；非法 → `409 INVALID_STATE_TRANSITION{from, to, allowed}`；版本不可运行 → `409 STRATEGY_VERSION_NOT_RUNNABLE{lifecycle}` |
| GET | `/strategy-instances/{id}/events` 🔒 | §1.2 分页，`at desc, id desc` → 元素 `{id, kind: instance_event_kind, from_status: instance_status \| null, to_status: instance_status \| null, actor: "user" \| "system", reason_code: reason_code \| null, note: string \| null, detail: object \| null, at: string(datetime)}`（v0.2.7）。`created` 的 `from_status` 为 `null`；`params_changed` 两个状态都为 `null`，`detail` 中给出 `{derived_strategy_version_id}` |
| GET/POST/DELETE | `/restrictions` 🔒 · `/restrictions/{id}` 🔒 | `{kind: "blocklist"\|"cooling_off"\|"mute", target_type: "security"\|"strategy"\|"instance", target_id: string, until: string(datetime) \| null, reason: string \| null}`。删除后会触发相关原因（`BLOCKLISTED`/`USER_MUTED`）重新检查 |
| GET/PUT | `/risk-controls` 🔒 | `[{control: risk_control, enabled: boolean, params: object, source: "system"\|"user"}]`；可能返回 `422 RISK_CONTROL_INVALID_PARAMS` |
| DELETE | `/risk-controls/{control}` 🔒 | **新增（v0.2.9 内，T-A52）**。清除**本人**该 control 的用户覆盖，恢复继承（`scope='user'` 行置 `override_active=false`；不是删除配置本身，六项控制恒存在）；返回 `200 list[RiskSetting]`（六项，与 PUT 同形）。幂等：无本人覆盖时重复清除 → 200、状态不变、不追加历史/审计。未知 `control` → `404 NOT_FOUND`；以任何变体形状（`?scope=`、body 目标等）试图触达 system 行 → `404`（本接口只寻址本人 user 行，不提供 403 探测面）。语义、存储、审计、负例与 T63 验收见 §7.11.2 T-A52 裁定 |
| GET | `/risk-controls/events` 🔒 | 风控事件（v0.2.7 定义）。`?status=active\|cleared&control=&security_code=&since=`，§1.2 分页（`triggered_at desc, id desc`）→ 元素 `RiskEvent = RiskFlag & {id: uuid, security_code: string \| null, name: string \| null, status: "active" \| "cleared", triggered_at: string(datetime), cleared_at: string(datetime) \| null, suggestion_id: uuid \| null, evidence: Evidence[]}`。`/today.risk_flags` 中的每一条都对应一条 `status=active` 的风控事件（由 `risk_event_id` 关联） |

### 7.6 候选信号、不可执行原因（没有"转计划"接口）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/candidate-signals` 🔒 ⚖ | `?state=&security_code=&instance_id=&horizon=`，排序为 `created_at desc`。列表元素即完整的 `CandidateSignal`（与详情相同，P1 校验同样适用），§1.2 分页；“自动重评状态”由该信号 `reason_ids` 对应的 `/non-executable-reasons` 的 `status`、`released_at`、`released_by` 表示，信号本身的 `state` 随之在 `blocked`/`released` 之间变化（v0.2.7） |
| GET | `/candidate-signals/{id}` 🔒 ⚖ | `CandidateSignal`（结构见下方定义与示例）。`gate_results[].gate` 是**运行时闸门名**（如 `gate_tradability`、`gate_data_fresh`），与晋级门禁枚举 `gate`（G1–G7）无关 |
| GET | `/candidate-signals/{id}/events` 🔒 ⚖ | 状态历史（v0.2.9 改为分页包装）：§1.2 分页 `{items, next_cursor}`，排序 `at desc, id desc`，元素 `{id, from: candidate_signal_state \| null, to: candidate_signal_state, cause: candidate_signal_event_cause, at: string(datetime)}`；信号创建时 `from` 为 `null`、`cause` 为 `executability_check`（创建时即完成首次可执行性检查，`to` 为 `open` 或 `blocked`，v0.2.9 #30）；拟定草案（→`drafted`，#30 补）、确认草案与用户忽略的 `cause` 为 `user`；**不返回** `detail` |
| POST | `/candidate-signals/{id}/dismiss` 🔒 | `{note: string \| null}` → `state:"dismissed"` |
| GET | `/non-executable-reasons` 🔒 | `?status=&signal_id=&code=`；`status` 可选 `active` `released` `all`，**默认 `active`**（`all` = 不按状态过滤，含 `obsolete`；带 `signal_ids=` 或 `suggestion_id=` 时同样默认 `active`；需要展示已解除原因时传 `status=all`，v0.2.9）；元素 `NonExecutableReason`（结构同详情）；v0.2.7 加 `released_since=`（datetime，只返回 `released_at ≥ released_since` 的原因，排序 `released_at desc, id desc`）；v0.2.3 加 `signal_ids=`（逗号分隔，≤ 100，超出 `400 VALIDATION_ERROR`）与 `suggestion_id=`（该建议卡 `candidate_signal_ids` 的全部原因）；带这两个参数之一时**不分页**，返回 `{items: [...]}` |
| GET | `/non-executable-reasons/{id}` 🔒 | `NonExecutableReason {id, signal_id, security_code, name（v0.2.9，服务端按信号联查，只读）, code: reason_code, description, evidence: Evidence[], release_condition: ReleaseCondition, status, detected_at, released_at: string \| null, release_evidence: object \| null, released_by: "system" \| "user"}` |
| POST | `/non-executable-reasons/{id}/release` 🔒 | **手动解除**，只允许 `machine_checkable=false` 的原因：`{confirm: true, note: string \| null}`；可机器判断的原因返回 `409 REASON_NOT_MANUALLY_RELEASABLE`；`BLOCKLISTED`、`USER_MUTED` 属于此类，只能通过删除 `/restrictions` 解除（v0.2.9） |

`CandidateSignal` 结构（v0.2.3 正式定义）：`{id: uuid, instance_id: uuid, strategy_version_id: uuid, strategy_key: string, strategy_name: string, lifecycle: lifecycle, security_code, name, horizon: horizon, state: candidate_signal_state, proposed_action: action, t_leg: t_leg \| null, score: int(0–100) \| null, confidence: {level: confidence_level, value: number(0–1)}, stops: Stops, rule_refs: RuleRef[]（非空）, evidence: Evidence[]（非空）, counter_evidence: TextWithEvidence[]（非空）, invalidation: TextWithEvidence[]（非空）, model_refs: ModelRef[], risk_flags: RiskFlag[], gate_results: [{gate: string, passed: boolean}], reason_ids: uuid[], plan_draft_ids: uuid[], valid_until: string(datetime) \| null, snapshot_id: string, feature_set_version: string, created_at: string(datetime), data_status, data_as_of, gaps}`。`data_status`、`data_as_of`、`gaps` 构成 DataStatusBlock，沿用 §1.1、§5.1 定义（`data_as_of` 键必须出现，值允许 `null`）；其余字段除标 `\| null` 外均不为 null；数组无元素时为 `[]`。纯离场策略（§5.2）的 `proposed_action` 只能是 `reduce`/`sell`。

`CandidateSignal` 示例（数值全部虚构）：
```json
{"id": "00000000-0000-4000-8000-000000000031", "instance_id": "00000000-0000-4000-8000-000000000021",
 "strategy_version_id": "00000000-0000-4000-8000-000000000011", "strategy_key": "demo_trend", "strategy_name": "示例趋势策略", "lifecycle": "published",
 "security_code": "600000.SH", "name": "示例银行", "horizon": "swing", "state": "blocked", "proposed_action": "buy", "t_leg": null,
 "score": 70, "confidence": {"level": "medium", "value": 0.55},
 "stops": {"stop_loss": "9.00", "take_profit": null, "time_stop_days": 10},
 "rule_refs": [{"rule_id": "R1", "snippet_id": null, "snippet_version": null, "role": "entry", "dimension": "technical", "passed": true, "value": "10.10", "threshold": "9.90", "evidence_ids": ["E1"]}],
 "evidence": [{"id": "E1", "key": "close", "value": "10.10", "unit": "CNY", "provider": "mairui", "endpoint": "/hsstock/history", "data_as_of": "2026-11-02T15:00:00+08:00", "fetched_at": "2026-11-02T16:40:00+08:00", "epistemic_type": "fact"}],
 "counter_evidence": [{"text": "量比偏低（示例）", "expr": "volume_ratio < 0.5", "evidence_ids": ["E1"]}],
 "invalidation": [{"text": "连续 2 日收于均线下方（示例）", "expr": "close < ma(close, ma_fast) for 2 days", "evidence_ids": ["E1"]}],
 "model_refs": [], "risk_flags": [], "gate_results": [{"gate": "gate_tradability", "passed": true}],
 "reason_ids": ["00000000-0000-4000-8000-000000000041"], "plan_draft_ids": [],
 "valid_until": "2026-11-09T15:00:00+08:00", "snapshot_id": "00000000-0000-4000-8000-000000000051",
 "feature_set_version": "fs_1", "created_at": "2026-11-02T16:45:00+08:00",
 "data_status": "fresh", "data_as_of": "2026-11-02T15:00:00+08:00", "gaps": []}
```

### 7.7 计划草案与计划（确认草案是生成计划的唯一入口）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/plan-drafts` 🔒 ⚖ | 生成草案 `{signal_ids: uuid[](≥1)}` → `201 PlanDraft`。**多个信号（v0.2.9）**：必须全部属于本人、同一 `security_code`、同一 `proposed_action`（有 `t_leg` 时 `t_leg` 也相同），否则 `400 VALIDATION_ERROR{field:"signal_ids"}`；方向相反的信号带 `STRATEGY_CONFLICT`，按下文返回 `409 SIGNAL_NOT_EXECUTABLE`；（原“来自多个实例时 `instance_id` 为 `null`”一句 v0.2.9 #30 作废：`PlanDraft` 没有 `instance_id` 字段，策略与实例经 `signal_ids` 对应的信号取得，不新增字段）；**判定顺序（#30）**：`signal_ids` 的格式与归属、同一证券、同一动作方向的校验（`400`）先于全部 `409`/`422`——请求中的信号方向不同一律 `400`；请求中的信号方向相同、但其中有信号因 `STRATEGY_CONFLICT`（对方信号不在本次请求中）处于 `blocked` 时是 `409 SIGNAL_NOT_EXECUTABLE`（#37：其他原因造成的 `blocked` 同样是 `SIGNAL_NOT_EXECUTABLE`，`STRATEGY_CONFLICT` 不是特例）；不做跨策略合成结论（plan P4）。**完整判定顺序（v0.2.9 #37，取代原“信号状态不是 `drafted`/`released` → `INVALID_STATE_TRANSITION`”一句）**：每一步对请求中的全部信号检查完，再进入下一步，返回第一个不通过的步骤：① 请求体格式（`signal_ids` 为非空 uuid 数组）→ `400 VALIDATION_ERROR{field:"signal_ids"}`；② 任一信号不存在或不属于本人 → `400 VALIDATION_ERROR{fields:[{field:"signal_ids", issue:"not_found"}]}`（不返回 `404`，不区分两种情况）；③ 同一证券、同一 `proposed_action`、同一 `t_leg` → 否则 `400 VALIDATION_ERROR{field:"signal_ids"}`；④ 任一信号属于 `simulating` 模板 → `409 STRATEGY_VERSION_NOT_RUNNABLE`；⑤ 任一信号处于终态（`confirmed` `dismissed` `expired` `invalidated` `superseded`）→ `409 INVALID_STATE_TRANSITION{from, to:"drafted", allowed:[]}`；⑥ 任一信号为 `blocked`，或仍有 `active` 原因（**不论原因码**，以请求时库中的原因为准，不在请求内重新做可执行性检查）→ `409 SIGNAL_NOT_EXECUTABLE{reason_ids}`，`reason_ids` 为请求中全部信号的 `active` 原因 id（去重，按 id 升序）；⑦ 没有 role ∈ {entry, exit, weakening} 且 passed = true 的规则引用（例如只有 model_refs）→ `422 PLAN_REQUIRES_EXPLAINABLE_SIGNAL`。可以拟定草案的信号状态为 `open`、`released`、`drafted`（`drafted` 即“重新生成”） |
| GET | `/plan-drafts` 🔒 · `/plan-drafts/{id}` 🔒 | `PlanDraft {id, status: plan_draft_status, signal_ids, security_code, name, action, qty_range: {min, max, lot}, price_range: {low, high}, stops: Stops, max_loss_amount, max_loss_pct, fee_estimate: {amount, epistemic_type}, user_context_snapshot: {holding_qty, sellable_qty, cash, sector_pct}, risk_flags: RiskFlag[], judgment_checklist: [{id, question, required: boolean}], valid_until, market_rule_version_id, created_at: string(datetime)（v0.2.7）}`，其中金额都是 `string(decimal)`。`qty_range`（v0.2.9 写明）：`lot` 为买入递增单位（主板、创业板、ETF 100；科创板 1），`min` 不低于起买量（科创板 200），取值来自草案的 `market_rule_version_id`（plan 2.5.8）。列表 `?status=`（可多值，默认全部）`&security_code=&signal_id=`，§1.2 分页（`created_at desc, id desc`）。`stale` 或 `expired` 的草案不能修改；“重新生成”就是用原草案的 `signal_ids` 再调 `POST /plan-drafts`，生成一份新草案，原草案保持不变，两者之间不建关联（v0.2.7） |
| POST | `/plan-drafts/{id}/confirm` 🔒 ⚖ | `{checklist_answers: [{id, answer: "yes"\|"no"\|"unsure", note?}], risk_ack: true, chosen_qty: string(decimal), chosen_price: string(decimal), deviation_ack: boolean}` → `201 {plan_id, plan_version_no: 1}`。可能返回：必答项缺失 → `422 CHECKLIST_INCOMPLETE{missing}`；`risk_ack` 不为 true → `422 RISK_ACK_REQUIRED`；数量或价格超出区间且未确认偏离 → `422 DEVIATION_ACK_REQUIRED{fields}`；草案状态为 stale/expired → `409 PLAN_DRAFT_STALE`。**整手校验（v0.2.9）**：按草案的 `market_rule_version_id`，买入/加仓要求 `chosen_qty ≥ 起买量` 且符合递增单位；卖出/减仓要求 `chosen_qty ≤ sellable_qty`，不足一手的零股只能连同全部余量一次卖出【以交易所规则为准】；不满足 → `400 VALIDATION_ERROR{fields:[{field:"chosen_qty", issue:"lot_rule", min_buy, step}]}`（v0.2.9 #30：`min_buy`、`step` 放在 `fields[]` 元素中，与 §4 通用结构一致，`details` 顶层不重复；卖出方向的 `min_buy` 表示最小卖出申报量。卖出合法当且仅当 `chosen_qty = sellable_qty`，或 `chosen_qty ≤ sellable_qty`、`chosen_qty ≥ min_buy` 且 `chosen_qty − min_buy` 是 `step` 的整数倍；主板、创业板、ETF 为 `min_buy=100, step=100`，科创板为 `min_buy=200, step=1`，即科创板可卖余量不足 200 股时只能一次全部卖出【以交易所规则为准；T-R10 已核对，与规则一致（v0.2.9 内，T-T25），plan 2.13 交易单位行、第 9 节问题 86】），`deviation_ack` 不能绕过 |
| POST | `/plan-drafts/{id}/discard` 🔒 | `{}` → `status:"discarded"`（v0.2.9 删除 `note`：草案正文不可变、无处存放，隐私从严；旧客户端发来的 `note` 被忽略，不报 400） |
| GET | `/plans` 🔒 · `/plans/{id}` 🔒 | 操作计划（结构见 §7.7B，v0.2.9 #30 定稿）：列表 `?status=`（可多值，取 `plan_status`；**默认 `active,triggered`**；`all` = 不按状态过滤）`&security_code=&origin=&account_id=`，§1.2 分页，排序 `created_at desc, id desc`，元素 `PlanSummary`；详情 `Plan`；他人的或不存在 → `404` |
| POST | `/plans` 🔒 | 用户**手工**创建（`origin` 由服务端写为 `"manual"`），不能引用候选信号；请求体与校验见 §7.7B → `201 Plan`；支持 `Idempotency-Key` |
| GET | `/plans/{id}/versions` 🔒 · `/plans/{id}/versions/{version_no}` 🔒 | 版本历史（§1.2 分页，排序 `version_no desc`，元素 `PlanVersion`）与单个版本，只读（v0.2.9 #30） |
| POST | `/plans/{id}/versions` 🔒 | 修改计划，生成新版本（`base_version_no` 乐观锁，`change_reason` 必填）→ `201 Plan`；支持 `Idempotency-Key`；见 §7.7B |
| POST | `/plans/{id}/close` 🔒 | `{status: "done"\|"cancelled", note: string(≤200) \| null}` → `200 Plan`（#30）；会触发 `SAME_DIRECTION_PLAN_EXISTS` 的解除检查；已是终态 → `409 INVALID_STATE_TRANSITION{from, to, allowed:[]}` |
| PUT/PATCH/DELETE | `/plans/{id}`、`/plans/{id}/versions/{version_no}` | 不提供 → `405`，带 `Allow` 头（计划与版本不可删除、不可原地修改，#30） |

### 7.7A 研究候选（v0.2.9 内，T-A11；plan 2.4 能力 2“研究候选卡”、3.1、3.3）
约定：只返回本人的候选（他人的或不存在的 id 一律 `404 NOT_FOUND`）；头表只有 `status` 与当前版本会变，版本（`CandidateVersion`）不可变，修改即新建版本；**没有删除接口**（放弃用 `decision=drop`，物理删除只随账号数据删除，plan 7.3），也没有 `PUT`/`PATCH`/`DELETE`（→ `405 METHOD_NOT_ALLOWED`）；本版不开放独立的 `/claims` 接口；研究候选没有通知与 SSE 事件（前端在本人写操作后自行刷新）；所有端点标 ⚖（输出含系统规则结果，§1.3）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/candidates` 🔒 ⚖ | `?status=`（可多值，逗号分隔；默认 `researching,watching,planned`，即不含 `dropped`；`status=all` 不按状态过滤）`&security_code=&origin=&suggestion_id=`；§1.2 分页，排序 `created_at desc, id desc`；元素 `ResearchCandidateSummary`；枚举值非法 → `400 VALIDATION_ERROR` |
| POST | `/candidates` 🔒 ⚖ | 新建候选并生成第 1 版（支持 `Idempotency-Key`）：`{origin: "manual" \| "from_stock" \| "suggestion", security_code: string \| null, suggestion_id: uuid \| null, thesis: string \| null, conditions_to_hold: CandidateConditionInput[]}`（可为 `[]`）→ `201 ResearchCandidate`，`status="researching"`，第 1 版 `decision=null`。校验见下 |
| GET | `/candidates/{id}` 🔒 ⚖ | `ResearchCandidate`（含完整的当前版本） |
| GET | `/candidates/{id}/versions` 🔒 ⚖ | 版本历史：§1.2 分页，排序 `version_no desc`，元素为完整的 `CandidateVersion` |
| GET | `/candidates/{id}/versions/{version_no}` 🔒 ⚖ | 单个版本，内容是该版本创建时的快照（回看不读最新数据）；`version_no` 不存在 → `404 NOT_FOUND` |
| POST | `/candidates/{id}/versions` 🔒 ⚖ | 新建版本（修改研究内容、做决定，或二者同时）：`{base_version_no: int, thesis: string \| null, conditions_to_hold: CandidateConditionInput[], decision: candidate_decision \| null, decision_reason: string \| null}` → `201 ResearchCandidate`。整体替换：未改的内容也要带上；支持 `Idempotency-Key` |

**`POST /candidates` 的校验（按顺序）**：
1. 请求体 → `400 VALIDATION_ERROR{fields:[{field, issue}]}`：`origin="strategy_screen"` → `issue:"not_supported"`（`/factor/screen` 本版未定义，plan 第 9 节问题 69）；`manual`、`from_stock` 时 `security_code` 必填、`suggestion_id` 必须为 `null`；`suggestion` 时 `suggestion_id` 必填，`security_code` 可为 `null`（取建议的证券），非 `null` 时须与建议一致，否则 `issue:"mismatch"`；`thesis` 去首尾空白后 1–2000 字（空串按 `null`）；`conditions_to_hold` 至多 10 条，每条规则见 `CandidateConditionInput`。
2. 证券：代码不在证券主数据中 → `400{field:"security_code", issue:"unknown_security"}`；`security_type` 为 `etf` 或 `index` → `400{field:"security_code", issue:"security_type_not_supported"}`（plan 第 9 节问题 70）。
3. 来源建议不存在或不属于本人 → `400{field:"suggestion_id", issue:"not_found"}`（两种情况响应相同，不泄露他人数据）；任何状态的本人建议都可引用。
4. 重复：本人同一证券已有 `researching` 或 `watching` 的候选 → `409 CONFLICT{field:"security_code", existing_id}`（库中部分唯一索引保证并发时只有一个成功；`dropped`、`planned` 的不算；plan 第 9 节问题 66）。

**`POST /candidates/{id}/versions` 的校验（按顺序）**：① 请求体 → `400`：`decision` 非 `null` 时 `decision_reason` 必填（去首尾空白后 1–200 字，自由文本，plan 第 9 节问题 68），`decision` 为 `null` 时 `decision_reason` 必须为 `null`（否则 `issue:"not_allowed"`）；② 候选不属于本人 → `404`；③ 状态为 `dropped` 或 `planned` → `409 INVALID_STATE_TRANSITION{from, to, allowed: []}`（`to` 为 `decision` 对应的状态，`decision=null` 时等于 `from`）；④ `base_version_no` 不是当前版本号 → `409 VERSION_CONFLICT{current_version_no}`。决定与当前状态相同（如 `watching` 时 `decision=watch`）→ `201`，只新增版本、状态不变。

**结构**：
- `CandidateConditionInput`：`{text: string（1–200 字）, verify_by: string(date) \| null, verify_method: string（1–200 字） \| null, confidence: confidence_level \| null}`；`verify_by` 与 `verify_method` 至少填一个（plan 3.1：假设须有验证方式或验证日期），否则 `400{field:"conditions_to_hold[i]", issue:"verification_required"}`。
- `CandidateCondition` = `CandidateConditionInput & {epistemic_type: "hypothesis"}`（固定为 `hypothesis`，用户不能选）。
- `CandidateFact` = `TextWithEvidence & {epistemic_type: "fact" \| "estimate", source_kind: source_kind}`。
- `FitAssessment`：`{profile_filled: boolean, holdings_available: boolean, hints: HorizonHint[], warnings: TextWithEvidence[]}`。只读**本人**画像、本人持仓与本人风控设置：`hints` 与 `/horizon-assessments` 同规则（画像已填写且不满足才出）；`warnings` 是本人已持有该证券或同行业证券时，对照本人风控上限（RC2 `position_cap`、RC4 `sector_concentration`）的提示。画像未填写 → `profile_filled=false`、`hints=[]`；未导入持仓 → `holdings_available=false`，不出持仓类提示。只作提示，不阻止任何操作、不影响状态。
- `CandidateVersion`：`{id: uuid, candidate_id: uuid, version_no: int（从 1 起）, security_code, name（生成时的简称）, thesis: string \| null（用户填写）, reasons: CandidateFact[]（系统生成：满足了哪些规则）, conditions_to_hold: CandidateCondition[]（用户填写）, counter_evidence: CandidateFact[]（系统生成：不满足的规则与风险因子）, fit_assessment: FitAssessment, decision: candidate_decision \| null, decision_reason: string \| null, snapshot_id: string, evidence: Evidence[], data_status, data_as_of, gaps（DataStatusBlock）, created_at}`。`reasons`、`counter_evidence` 的 `evidence_ids` 都能在本版本的 `evidence[]` 中找到。
- `ResearchCandidate`：`{id: uuid, security_code, name（当前简称）, security_type: security_type, origin: research_candidate_origin, strategy_run_id: uuid \| null（本版恒为 null）, suggestion_id: uuid \| null, status: research_candidate_status, plan_ids: uuid[]（本人 `candidate_id` 指向本候选的操作计划；本版恒为 []）, version_count: int, current_version: CandidateVersion, created_at}`。
- `ResearchCandidateSummary`：`{id, security_code, name, origin: research_candidate_origin, status: research_candidate_status, suggestion_id: uuid \| null, current_version_no: int, decision: candidate_decision \| null（当前版本的决定）, last_version_at: string(datetime)（当前版本的创建时间；头表没有 updated_at）, created_at}`。

**系统生成的内容**（`reasons`、`counter_evidence`、`fit_assessment`）：
- 每次新建版本时由服务端按当时数据生成一次，写入该版本的快照（`data_snapshots.purpose='candidate'`，带本人 `user_id` 和所用证书的 `licence_id`），之后不刷新；要看最新情况就新建版本。
- `origin=suggestion`：`reasons` 取来源建议各策略结论（`strategies[]`）的 `reasons`，`counter_evidence` 取各策略结论的 `counter_evidence` 与建议的 `risk_flags`，原文与证据照抄（与 `CandidateSignal.counter_evidence` 同构）。`manual`、`from_stock`：`reasons=[]`，`counter_evidence` 只列证券风险因子（`risk_flag`、停牌、退市整理）。两者都可以为 `[]`，为空时前端显示固定文字“系统未列出反证，不代表没有风险”。
- 只用本人证书取得的数据和证券公开主数据；本人证书不可用时按 §1.1 降级（`data_status`），**不用他人证书的数据补齐**。
- 这些内容若以 `claims` + `claim_links`（`target_type=candidate_version`，`role` 为 `reason`/`counter`/`risk`）存储，`claims.user_id` 一律为本人（不用 `user_id=null` 的“系统 claim”），是否系统生成看 `source_kind`；随账号数据删除（plan 3.3、7.3）。

**关联**：入口——建议详情 → `origin=suggestion`；个股页 → `from_stock`；候选信号详情 → `from_stock`（不记录来源信号，plan 第 9 节问题 69）；研究候选页手工新建 → `manual`；本版没有策略筛选入口。反查——建议详情用 `GET /candidates?suggestion_id=`，个股页与候选信号详情用 `?security_code=`；`Suggestion`、`CandidateSignal` 不加字段。计划——研究候选**不能**直接生成计划草案（`POST /plan-drafts` 仍只收 `signal_ids`）；`planned` 由系统在本人创建 `candidate_id` 指向该候选的操作计划时写入，`/plans` 结构未定（plan 第 9 节问题 59），本版实际不会出现 `planned`，前端仍要能显示。

**v0.2.9 #30 补充（T-F23 待定 1–7 裁定）**：① `origin=suggestion`：建议不存在或不属于本人 → `400 VALIDATION_ERROR{fields:[{field:"suggestion_id", issue:"not_found"}]}`；建议本人可见但 `security_code` 不同 → `{field:"security_code", issue:"mismatch"}`；② 从建议复制的 `reasons`、`counter_evidence` 每条 `epistemic_type="fact"`、`source_kind="system_calc"`，按 `(text, expr)` 去重，保留首次出现的位置，`evidence_ids` 取并集；③ `fit_assessment.hints` 由服务端生成（规则同 `/horizon-assessments`），mock 可简化但不得由前端拼接；④ 本版状态仍不会出现 `planned`，`plan_ids=[]`（§7.7B 不改变此条）；⑤ `POST /candidates/{id}/versions` 同样支持 `Idempotency-Key`，语义与创建相同（24 小时内同键同体返回首次结果，同键异体 → `409 IDEMPOTENCY_CONFLICT`）；⑥ 本人证书不可用（含被管理员暂停、冷却）时照常按缓存生成，`data_status="stale"`，`gaps` 含 `{key:"data_licence", reason:"data_licence_unavailable"}`，不报错；⑦ 入口反查（建议详情、个股页）用默认状态（不含 `dropped`），放弃后同一证券可以再次加入。

### 7.7B 操作计划与提醒的结构（v0.2.9 内，#30 前端待定裁定；plan 第 9 节问题 59、80–83）

**计划状态机**（`plan_status`）：`POST /plans` 与确认草案生成的计划为 `active`；当前版本的任一条件（`trigger` 或 `invalidation`）被判定满足 → `triggered`（系统写入，同时生成 `origin=plan_condition` 的提醒，并发 SSE `plan_triggered`）；`triggered` 时新建版本 → 回到 `active`（新版本的条件重新布防）；`active`/`triggered` 经 `close` → `done` 或 `cancelled`（终态）。系统**不会**自动关闭计划，失效条件满足也只置 `triggered`，由用户决定（问题 80）。终态计划不能再建版本或关闭。

- **`PlanSummary`**：`{id: uuid, security_code, name, account_id: uuid | null, origin: plan_origin, status: plan_status, action: action, current_version_no: int, plan_draft_id: uuid | null（`origin=plan_draft` 时为来源草案）, candidate_id: uuid | null（本版恒为 null，§7.7A）, triggered_at: string(datetime) | null（最近一次进入 `triggered` 的时刻；回到 `active` 后为 null）, created_at, updated_at}`
- **`Plan`** = `PlanSummary` + `{current_version: PlanVersion, version_count: int, pending_triggers: [{condition_id: uuid, condition_kind: plan_condition_kind, condition_text: string, triggered_at, alert_id: uuid | null, evidence_ids: string[]}], evidence: Evidence[]}`；`pending_triggers` 为当前版本中已满足、尚未因新建版本或关闭而清空的条件（与 `/today` 的 `TodayPlanTrigger` 同源，字段同名同义），`evidence_ids` 指向本对象的 `evidence`。
- **`PlanVersion`**（不可变）：`{plan_id, version_no: int, action: action, qty: string(decimal) | null, price: string(decimal) | null, size_pct_of_assets: string(decimal) | null, max_loss_amount: string(decimal) | null, stops: Stops | null, rationale: string, risks: string | null, review_date: string(date) | null, conditions: PlanCondition[], change_reason: string | null（第 1 版为 null）, checklist_answers: [{id, question, answer, note}]（确认草案时的回答；手工计划为 []）, snapshot_id: string | null, created_at}`
- **`PlanCondition`**：`{id: uuid, kind: plan_condition_kind, type: plan_condition_type, params: object, description: string(1–200), epistemic_type: "hypothesis"}`；`params`：`price_above`/`price_below` → `{price: string(decimal)}`；`pct_change` → `{pct: string(decimal)（带符号，相对前收盘）}`；`date` → `{on: string(date)}`；`custom` → `{}`（只作文字记录，不自动判定）。`description` 是 `TodayPlanTrigger.condition_text` 的来源。
- **条件判定口径（T-A29，P2N-07）**：
  1. 价格一律用不复权最新价，须在 `stale_threshold_s` 内；缺价、过期、停牌 → 本次不判，记 unknown + gap，不触发。
  2. `price_above`：`last ≥ price` 触发；`price_below`：`last ≤ price` 触发（**等于阈值算触发**）。
  3. `pct_change`：`chg = (last / prev_close − 1) × 100`，Decimal 计算，ROUND_HALF_UP 保留 4 位后再比较；`pct > 0` 时 `chg ≥ pct` 触发，`pct < 0` 时 `chg ≤ pct` 触发（等号算触发）；`prev_close` 取行情自带的昨收（不复权），缺失 → unknown + gap `prev_close`。`pct = 0` 方向不明 → 写入时 `400 invalid`。
  4. 每个条件在同一计划版本内**只触发一次**（边沿触发），之后不再判；新版本重新布防。价格类条件**不补判**：worker 停机或缺价期间错过的穿越不回看历史价，恢复后只按当时价格判定。
  5. `date`：`on` 须 ≥ 写入当日（北京时间），否则 `400 invalid`；`on` 为交易日则当日 09:00（北京时间）触发，非交易日顺延到其后第一个交易日 09:00；交易日历缺失 → unknown + gap，不触发。**错过要补**：worker 恢复后发现已过触发时刻且未触发，立即补触发一次，`triggered_at` 记实际时刻，提醒 evidence 记 `scheduled_for`（原定时刻），不重复补发。
- **`POST /plans` 请求体**：`{security_code, account_id: uuid | null, action: action, qty?, price?, size_pct_of_assets?, max_loss_amount?, stops?, rationale: string(1–2000), risks: string(≤2000) | null, review_date: string(date) | null, conditions: [{kind, type, params, description}]（0–20 条）, candidate_id?: null}`。校验（均为 `400 VALIDATION_ERROR` 的 `fields[]`）：证券不存在 → `unknown_security`，指数 → `not_allowed`；`type` 为 `indicator`/`event` → `not_supported`；`params` 与 `type` 不符 → `invalid`；`candidate_id` 非 null → `not_supported`（本版研究候选不转计划）。同一用户同一证券已有 `active`/`triggered` 且 `action` 相同的计划 → `409 CONFLICT{field:"security_code", existing_id}`（问题 81）。
- **`POST /plans/{id}/versions` 请求体**：`{base_version_no: int, change_reason: string(1–200), …}`，其余字段同 `POST /plans`，整体替换（省略视为 null 或 []）；`security_code`、`account_id`、`origin` 不可改（带不同值 → `400 not_allowed`）。顺序：`400` → 他人或不存在 `404` → 终态 `409 INVALID_STATE_TRANSITION{from, to: from, allowed:[]}` → `base_version_no` 不是当前版本 `409 VERSION_CONFLICT{current_version_no}`。
- **`Alert`** = `TodayAlert` 的全部字段 + `{checklist: string[], snapshot_id: string | null, handled_at: string(datetime) | null（最近一次状态变更时刻）, evidence: Evidence[]}`；`evidence_ids` 指向本元素的 `evidence`。与 `/today` 不同，`/alerts` 包含 `origin=plan_condition` 的提醒（`plan_id` 非 null）。
- **`GET /alerts`**：`?status=`（可多值，取 `alert_status`；**默认 `new,read`**；`all` = 不按状态过滤）`&origin=&severity=&security_code=&plan_id=`；§1.2 分页，排序 `triggered_at desc, id desc`。`GET /alerts/{id}` → `Alert`；读取详情**不会**自动改状态。
- **`PATCH /alerts/{id}`** `{status: "read"|"checked"|"acted"|"dismissed"}` → `200 Alert`。允许的转换：`new` → `read`/`checked`/`acted`/`dismissed`；`read` → `checked`/`acted`/`dismissed`；`checked` → `acted`/`dismissed`；`acted`、`dismissed` 为终态（问题 82）。目标与当前状态相同 → `200`，不变（幂等）；其余（含回到 `new`）→ `409 INVALID_STATE_TRANSITION{from, to, allowed}`。把提醒标为 `acted` 不会生成交易或改计划。

### 7.8 建议卡、日报、提醒、复盘、通知
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/suggestions` 🔒 ⚖ · `/suggestions/{id}` 🔒 ⚖ | 列表 `?security_code=&status=`（`status=active` 即当前卡，同一用户同一证券至多 1 张；没有 `current`，v0.2.3）元素为 `SuggestionSummary` 加 `security_code`、`name`；详情为 `Suggestion`（§5.2，内容不可变）；`/suggestions/{id}/chain` 返回取代链 |
| POST | `/suggestions/{id}/actions` 🔒 | `{kind: "viewed"\|"dismissed"\|"acted_trade_linked", trade_id: uuid \| null, note}`。**没有 `converted_to_plan`**；`draft_requested`、`draft_confirmed`、`reason_manually_released` 由服务端在相应接口里自动写入 |
| POST | `/suggestions/refresh` 🔒 ⚖ | `{security_code}`，只读缓存重算；可能返回 `409 SUGGESTION_REFRESH_TOO_FREQUENT`。**v0.2.9 内，架构师裁定（review-05d8a16 m2）**：**同步处理**，在请求内只用缓存重算，不做外部拉取，完成后再响应 → `200 {suggestion: Suggestion \| null, changed: boolean, superseded_id: string \| null, data_as_of: string(datetime)}`：新建 → `changed=true`、`superseded_id=null`；取代旧建议 → `changed=true`、`superseded_id` 为被取代那条的 id；无变化 → `changed=false`，`suggestion` 为当前有效的那条，只有当前没有任何建议时才为 `null`。错误码沿用：`409 SUGGESTION_REFRESH_TOO_FREQUENT{retry_after_s}`、`409 DATA_LICENCE_UNAVAILABLE{status}`、`503 FRESH_DATA_REQUIRED{data_as_of}`。前端以响应体为准；刷新后再 `GET /suggestions` 也允许，结果一致 |
| GET | `/suggestions/{id}/tracking` 🔒 | `{t1: Stat, t5: Stat, t20: Stat}`，并附各期的价格依据 |
| GET | `/daily-reports` 🔒 ⚖ · `/daily-reports/{date}` 🔒 ⚖ | 盘后日报（不可变）：列表元素 `{date, generated_at, regime, reconciliation_status, stock_count}`，列表按 `date` 倒序（最新在前）；详情 `DailyReport`（§5.3） |
| GET | `/signals` 🔒 ⚖ | 盘中事件流 `?security_code=&kind=&since=`：元素 `SignalEvent`（规则事件，不含动作建议）。图表标记不设专用端点（v0.2.3）：分时标记用本接口、日 K 标记用 `/candidate-signals`，两者都**须带 `security_code`** |
| GET/POST/PATCH/DELETE | `/alert-rules` 🔒 | 提醒规则（结构另定，不在 v0.2.9 #30 范围；前端本版不做规则页） |
| GET | `/alerts` 🔒 · `/alerts/{id}` 🔒 | 提醒触发记录（含 `origin=plan_condition`），结构、筛选与排序见 §7.7B（v0.2.9 #30） |
| PATCH | `/alerts/{id}` 🔒 | `{status}` 改处理状态，状态机见 §7.7B → `200 Alert`；`POST /alerts`、`PUT`/`DELETE /alerts/{id}` → `405`（提醒由系统生成，不可删除，#30） |
| GET/POST | `/reviews` 🔒 · `/reviews/{id}` 🔒 | 复盘 |
| GET | `/notifications` 🔒 · `/notifications/unread-count` 🔒 · POST `/notifications/{id}/read` 🔒 · POST `/notifications/read-all` 🔒 | 通知中心：列表 `?unread=&kind=` 元素为 `Notification`；`unread-count` → `{count: int}`；`read` 与 `read-all` 均返回 `204 No Content`，幂等（已读再标不改 `read_at`，v0.2.3） |
| GET/PUT | `/notification-preferences` 🔒 · `/channels` 🔒 | 渠道与免打扰设置 |

### 7.9 管理端（🛡；非管理员（含未登录）访问任何 `/admin/*` 一律返回 404，不暴露其存在，见 §1.3）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/ingest/status` 🛡 | 只读：`{heartbeat: ingest_health（v0.2.9 #38，不为 null；判定同 §7.10 ingest 心跳与 `/health/ready.ingest`）, leader: {instance_id, egress_ip_masked: string \| null（如 "203.0.113.x"）, lease_expires_at} \| null（v0.2.9 内 T-B47 裁定：没有未过期的租约时为 null，不返回各字段为 null 的对象）, budget: {per_minute_limit: int, used_last_minute: int}（v0.2.6：全进程合计；按证书的明细见 `/admin/data-licences`）, queues: [{priority: "p0_intraday"\|"p1_daily"\|"p2_backfill", depth: int, oldest_age_s: int}], errors_24h: [{upstream_code: string, count: int}], ip_limit_alerts_24h: int, freshness: [{dataset, data_as_of, data_status}], licences: IngestLicenceStatus[], licences_truncated: boolean, alerts: [{level: "warning"\|"critical", key: string, message: string}]}`。**v0.2.9 内 T-B47 裁定**：① `budget.per_minute_limit` 是全部状态为 `active` 的证书每分钟上限之和（不受 `licences[]` 500 行截断影响），`used_last_minute` 是最近 60 秒 `ops.ingest_request_log` 中全部证书的请求数；`ip_limit_alerts_24h` 是最近 24 小时 `ip_limited` 事件数；`queues[].oldest_age_s` 按队列中最早一条计算，不限回看时间，空队列为 0；② `freshness` 固定为 6 行，顺序为 `quotes`、`minute_bars`、`daily_bars`、`financials`、`announcements`、`security_master`，每行取全部证书中最新的 `data_as_of`；`data_status` 只取 `fresh`/`stale`/`pending`/`unavailable`：从未取到为 `unavailable`；本时段应有数据但还没到发布时间为 `pending`；超过下列阈值为 `stale`：`quotes` 盘中超过 `stale_threshold_s`（plan 0A.7，默认 30 秒）、`minute_bars` 盘中超过 180 秒、`daily_bars` 交易日 17:00 后仍不是当日、`announcements` 交易日 20:00 后仍不是当日、`security_master` 超过 1 个交易日、`financials` 超过 120 天（初值，问题 78）；非交易时段按上一交易时段收盘判断；③ `alerts`（永不为 null，无告警为 `[]`）按固定口径生成，`key` 取 `leader`、`heartbeat`、`queue.<priority>`、`budget`、`ip_limit`、`errors.<upstream_code>`、`freshness.<dataset>`、`licence.<status>`、`licence.expiring`（v0.2.9 #31）；口径：没有 leader 或心跳 stale → `critical`；盘中 `p0_intraday` 最早任务超过 60 秒 → `warning`、超过 300 秒 → `critical`；`p1_daily` 超过 3600 秒 → `warning`；`used_last_minute ≥ 90%` 上限 → `warning`；`ip_limit_alerts_24h ≥ 1` → `critical`；单个上游错误码 24 小时 ≥ 20 次 → `warning`；`quotes` 盘中 `stale`/`unavailable` → `critical`，其他数据集 `stale` → `warning`；有 `invalid`/`ip_limited` 证书 → `critical`，有 `expired`/`quota_exceeded` 证书或 `days_left ≤ 14` → `warning`（阈值为初值，plan 6.1，问题 78）。`message` 为固定中文文案，不含证书值、IP 全文或管理员理由。**v0.2.9 #31（T-B46-47 前端待定）**：① **每个 `key` 最多一条**，按证书聚合，不按证书拆分；同一 `key` 同时满足两级时只出 `critical`；② `key`、`level` 与 `message` 固定如下（`message` 不带数值、阈值、证书数量或用户名，只允许 `{upstream_code}` 与 `{dataset_name}` 两个占位）：`leader` critical“没有采集主实例（无未过期的租约）”；`heartbeat` critical“采集主实例心跳超时”（leader 不为 null 且 §8 ingest 心跳判定为 `stale` 或 `unknown` 时；leader 为 null 时只出 `leader`）；`queue.p0_intraday` warning/critical“盘中队列（P0）等待过久”；`queue.p1_daily` warning“日频队列（P1）等待过久”；`budget` warning“近 1 分钟调用量接近上限”；`ip_limit` critical“24 小时内出现 IP 受限”；`errors.<upstream_code>` warning“上游错误码 {upstream_code} 24 小时内次数过多”；`freshness.quotes` critical“实时行情过期或不可用”；`freshness.<dataset>`（其余 5 个）warning“{dataset_name}已过期”；`licence.invalid` critical“有证书无效”；`licence.ip_limited` critical“有证书 IP 受限”；`licence.expired` warning“有证书已过期”；`licence.quota_exceeded` warning“有证书今日额度已用完”；`licence.expiring` warning“有证书即将到期”（状态不是 `expired` 且 `0 ≤ days_left ≤ licence_days_left_warning` 的证书，不再用 `licence.<status>`）；③ `dataset_name`（前端显示名也用这一组，不是接口字段）：`quotes` 实时行情、`minute_bars` 分钟线、`daily_bars` 日线、`financials` 财务数据、`announcements` 公告、`security_master` 证券主数据；④ 排序由服务端决定：`critical` 在前、`warning` 在后；同级按上面 ② 的 `key` 顺序，`errors.*` 按 `upstream_code` 升序，`freshness.*` 按 `freshness` 的固定顺序；前端保持服务端顺序，级别显示为“严重”/“警告”；⑤ 响应不新增心跳时间字段（plan 第 9 节问题 88；#38 新增的 `heartbeat` 是状态，不是时间，仍不返回 `ts` 或已过秒数）；⑥ **v0.2.9 内，T-A04**：另加 5 个证券主数据键，排在 ② 所列全部键之后（仍是 `critical` 在前）：`master.snapshot_rejected` critical“证券名单更新失败，暂时沿用上一版”（#39 改文案，下同）（任一交易所列表 18:00 与次日 07:30 两次都被整份拒收），只有一次被拒收时为 warning、文案相同；`master.vendor_stale_listed` warning“行情源仍列着已退市的证券”（任一差异连续超过 5 个工作日）；`master.vendor_unknown` warning“行情源出现交易所名单里没有的证券，暂不收录”；`master.quote_missing` warning“部分证券在行情源中暂时没有数据”；`master.field_mismatch` warning“部分证券的名称或上市信息与其他来源不一致，待核对”（未关闭差异 ≥ 10 条）；阈值见 plan 6.1 `master.*`（初值）；按证书聚合，每个键最多一条；`message` 不带代码、数量或用户名；明细看 `/admin/securities/reconciliation`；`quote_conflict` 不出告警。**v0.2.9 #38–#40**：⑦ `heartbeat` 字段见上，`heartbeat` 告警只由服务端生成，前端不按该字段自行出告警；⑧ 全部 `alerts[].message`（含 `master.*`）都由服务端按固定表生成，前端原样显示、不按 `key` 映射，不认识的 `key` 也照样显示；同级排序：#31 ② 的键在前，`master.*` 在后，5 个 `master.*` 键之间按 ⑥ 所列顺序；⑨ `licences[].days_left` 为 null（未填写到期日）时不出 `licence.expiring`，也不出其他到期类告警（plan 第 9 节问题 94）。**v0.2.8 不兼容变更**：删除原全站 `licence: {expires_on, days_left}`（它来自已停用的全站证书），改为按证书的 `licences[]`（§5.1 `IngestLicenceStatus`，与 `/admin/data-licences` 同名字段同义）：每张已设置的证书一行，`not_set` 的用户不列出；不分页，最多 500 行，超出时 `licences_truncated=true`，完整列表看 `/admin/data-licences`；排序：`status` 依次为 `invalid`、`ip_limited`、`quota_exceeded`、`expired`、`paused_by_admin`、`pending_verification`、`active`，同状态按 `days_left` 升序（null 在后），再按 `username`。顶层 `budget`、`queues`、`errors_24h` 仍是全部证书的合计。**不返回任何证书值、密文、HMAC 或其片段**；`per_minute_limit` 等数值 **待 T003 验证** |
| GET | `/admin/securities/reconciliation` 🛡 | v0.2.9 内，T-A04。证券主数据对账差异，只读，§1.2 分页，排序 `last_seen_on desc, id desc`。`?status=open\|resolved\|all`（默认 `open`）`&kind=`（`security_reconciliation_kind`，逗号分隔多值）`&source=`（`security_reconciliation_source`）→ `{items: [{id, kind: security_reconciliation_kind, source: security_reconciliation_source, security_code, name: string \| null（主数据简称；`vendor_unknown` 为 null）, source_name: string \| null（对方给出的简称）, field: "name"\|"list_date"\|"delist_date"\|"exchange"\|"board" \| null（只有 `field_mismatch` 有）, master_value: string \| null, source_value: string \| null, licence_owner: {user_id, username} \| null（只有 `mairui_*` 有）, first_seen_on: string(date), last_seen_on: string(date), seen_days: int（出现过的工作日数）, status: "open"\|"resolved", resolved_on: string(date) \| null}], next_cursor}`。非法筛选值 → `400 VALIDATION_ERROR`。不返回证书值、行情数值或原始快照内容；`quote_conflict` 只给代码与天数，不给冲突的价格 |
| POST | `/admin/ingest/pause` · `/admin/ingest/resume` 🛡 | 暂停或恢复外呼（迁移和冷备切换时使用，写审计） |
| GET | `/admin/data-licences` 🛡 | 全部用户的数据证书状态（v0.2.6，分页）→ `AdminDataLicence[]`；**不返回证书值或任何片段**。**排序与筛选（v0.2.9，T-F22 遗留 2）**：按用户 `created_at desc, id desc`；V1 没有服务端筛选参数，未定义的查询参数忽略，前端只在已加载的行上筛选（`?status=`、`?q=` 留待后续版本，plan 第 9 节问题 72）。**冷却（T-F22 遗留 4）**：不另设字段，冷却状态从 `status`（`quota_exceeded`/`ip_limited`）与 `paused_until` 看出；这两个字段 `AdminDataLicence`（经 `DataLicenceStatus`）与 `IngestLicenceStatus` 都已包含 |
| POST | `/admin/data-licences/{user_id}/pause` · `/admin/data-licences/{user_id}/resume` 🛡 | `{reason: string(1–200)}` → `204`；暂停后状态为 `paused_by_admin`，恢复后为 `pending_verification` 并重新验证；写审计；未设置 → `409 DATA_LICENCE_NOT_SET`。v0.2.8：暂停**按用户记录**，暂停期间用户 PUT 或 DELETE 证书都不解除（§7.1）；resume 时证书已在暂停期间被删除 → `204`，状态为 `not_set`。**重复暂停幂等（v0.2.8 补充，架构师裁定）**：用户已处于管理员暂停时再次 pause，不论证书是否已删除，都返回 `204`，暂停记录与状态不变，不返回 409；未暂停且未设置证书时 pause 仍为 `409 DATA_LICENCE_NOT_SET`。**resume 幂等（v0.2.9，T-F22 遗留 1）**：已设置证书但未被管理员暂停时 resume → `204`，状态不变，不写审计、不写证书事件、不发通知（与重复暂停一致，重复暂停同样不写审计）；未暂停且未设置证书时 resume 仍为 `409 DATA_LICENCE_NOT_SET`。**理由与操作人（T-F22 遗留 3）**：本版不在任何接口返回暂停理由、操作人；管理员在 `GET /admin/audit-logs` 查看（审计 `action` 为 `data_licence.paused`/`data_licence.resumed`，`actor_id` 为操作人，`detail.reason` 为理由）；该接口的查询参数与元素结构尚未定义（plan 第 9 节问题 73）。**通知（T-F22 遗留 5，默认执行，plan 第 9 节问题 74）**：pause 或 resume 成功且该用户证书状态确实变化时（含暂停期间证书已删除、resume 后为 `not_set`），给该用户发一条站内通知：`kind="data_licence"`，`target.type="none"`，`severity` 暂停为 `attention`、恢复为 `info`，标题固定为“数据证书已被管理员暂停”或“数据证书已被管理员恢复”，正文为固定说明，**不含管理员填写的理由和管理员身份**；幂等的重复调用不发 |
| GET/POST | `/admin/invites` 🛡 | 邀请码（v0.2.3 #27，T-B03c）：POST `{ttl_h: int \| null（默认 168，≤ 720）, bound_username: string \| null, note: string(≤200) \| null}` → `201 {id, code, expires_at, bound_username, note}`，**`code` 明文只在此响应出现一次**；GET 列表（分页）`{id, status: "active"\|"used"\|"expired"\|"revoked", created_by, created_at, expires_at, used_at, used_by, bound_username, note}`，不含明文或摘要；均写审计 |
| DELETE | `/admin/invites/{id}` 🛡 | 吊销邀请码 → `204`；已用或已吊销 → `409 INVALID_STATE_TRANSITION`；只改状态，不物理删除 |
| GET/PUT | `/admin/realtime-settings` 🛡 | 刷新间隔、分层上限（默认值 **待 T003 验证**） |
| GET/POST/PATCH | `/admin/llm/providers` · `/admin/llm/models` · `/admin/llm/routes` · `/admin/llm/prompts` 🛡；POST `/admin/llm/test`；GET `/admin/llm/usage` | API key 只写不读：响应只返回 `api_key_source: "env"\|"db"` 与 `api_key_set: bool`，不返回 key 或任何片段；`env` 来源（DeepSeek：`DEEPSEEK_API_KEY`，plan 2.7.1）不可经接口写入，PATCH 带 `api_key` → `422 VALIDATION_ERROR` |
| GET/POST/PATCH | `/admin/plans` · `/admin/subscriptions` 🛡 | 套餐与权益（不接支付） |
| GET/POST | `/admin/evaluation/runs` 🛡 · GET `/admin/evaluation/runs/{id}` 🛡 | 第三阶段启用（plan 第 9 节问题 26 已定），启用前返回 `404`。用户侧只通过模板版本的 `internal_check` 看到元信息（方案 A）。POST `{kind: "factor_ic"\|"event_study"\|"param_robustness"\|"daily_revalidation", target: {strategy_version_id? , feature_key?}, data_range: {from, to}, params: object}` → `202 {run_id}`；结果中 `metrics` 的每一项都是 `Stat` |
| GET | `/admin/audit-logs` 🛡 | 审计 |

### 7.10 元数据与健康
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/meta/enums` | 不需要登录、不分页；`Cache-Control: public, max-age=300` + 强 ETag，支持 `If-None-Match` → 304。结构见下 |
| GET | `/health/live` | 存活检查：进程能处理请求即 **200** `{status: "ok"}`，不访问任何依赖。用于容器健康检查（依赖故障时不应重启 api） |
| GET | `/health/ready` | 就绪检查：`{status: health_status, db: component_health, redis: component_health, ingest: ingest_health, checked_at, version}`。db、redis 都为 `ok` → **200**（ingest 非 `ok` 时 `status: "degraded"`，因为读接口仍可用缓存并通过 `data_status` 告知陈旧）；db 或 redis 为 `error` → **503**，`status: "down"`。用于 nginx/监控。不需要登录、不含错误细节（异常只进日志）；每个依赖检查超时 1 秒，并行执行 |
| GET | `/health` | `/health/ready` 的别名（兼容） |

- `/health*` 的响应体**不用** §2 错误外壳（503 时也返回上面的健康结构）。
- **ingest 心跳**（ingest 写、api 读）：leader 每 15 秒 `SET ingest:heartbeat <json> EX 600`，JSON 为 `{"ts": int(Unix 秒), "instance_id": string, "leader": true, "version": string, "budget_used_last_minute": int, "queue_depth": {"p0": int, "p1": int, "p2": int}}`；api 只依赖 `ts`，其余字段供 `/admin/ingest/status` 展示。判定顺序：Redis 不可用 → `unknown`；`ingest:paused` 存在（值为 JSON `{"by", "at", "reason"}`，管理员暂停时写入）→ `paused`；心跳缺失、无法解析或 `now - ts > 120` → `stale`；否则 `ok`。键名与阈值可配置（plan 6.1 `config/ingest.yaml`，环境变量 `INGEST_HEARTBEAT_KEY`、`INGEST_PAUSED_KEY`、`INGEST_STALE_AFTER_S`）。
- **`/meta/enums` 结构**（取值全部来自后端的集中定义，路由里不写死）：
```json
{"version": "v0.2.9",
 "enums": {"horizon": ["intraday_t", "short", "swing", "long"], "...": []},
 "reason_codes": [{"code": "T1_NOT_SELLABLE", "release_kinds": ["time"], "check_on": ["daily_close"], "manually_releasable": false, "note": "…"}],
 "error_codes": [{"code": "NOT_FOUND", "http_status": 404, "scope": "http"}],
 "import_codes": [{"code": "IMPORT_DUPLICATE_FILE", "severity": "warning", "scope": "file", "needs_action": "…"}],
 "risk_control_labels": {"stop_take": "RC1", "position_cap": "RC2", "total_exposure": "RC3", "sector_concentration": "RC4", "loss_streak_drawdown": "RC5", "plan_violation": "RC6"}}
```
  - `enums` 的键集合 == 第 3 节表名（不含 `reason_code`，它在 `reason_codes` 里展开）；取值为字符串数组（中文标签由前端维护，不在此下发）。
  - `error_codes[].scope`：`http`（§4 的 HTTP 错误码）或 `internal`（只在服务端内部用，如 `SIGNAL_NOT_EXPLAINABLE`）。§4.1 的 `IMPORT_*` 提示码只出现在 `import_codes`，**不**出现在 `error_codes`（v0.2 起 `IMPORT_ROW_COLUMN_MISMATCH` 等是提示码）。
  - `version` 为契约版本；ETag 由内容哈希得出。

---

### 7.11 Phase 2 后续最小补充（T-A24；status: draft）

本节是待派单的设计契约，**status: draft** 是文档状态，不是响应字段或新增生命周期枚举。仅新增一个读端点，其余补足既有接口的字段/行为。实施任务须同步 OpenAPI、客户端类型和对应定点测试后再认定交付；没有实现时不得以空壳 200 冒称可用。既有 §1.3 鉴权/CSRF、§5.4 模拟隔离和 G1–G7 均不变；本节不授权任何外部调用。

#### 7.11.1 六维日报（status: draft；P2N-01/04/05）

在 §5.3 `DailyReport.stocks[]` 增加：

| 字段 | 类型 | 说明 |
|---|---|---|
| `analysis_snapshot_id` | `string(uuid) \| null` | 该股六维事实的不可变快照；无快照或旧版日报为 null |
| `dimensions` | `DailyDimensionAnalysis[] \| null` | 新生成的非 removed 行恰好六项，按 §3 dimension 顺序；旧版日报、removed 行为 null，不伪装成已完成六维分析 |

**日报顶层时点与账户金额（T-A29，P2N-05d）**：
- 顶层 `data_as_of` = 本份日报实际用到的各部分（`market`、`account` 计价、各 `stocks[]` 与其 `dimensions[]`）中**非 null `data_as_of` 的最早值**（取最旧，保守）；全部为 null 时为 null，`data_status=unavailable`。不取生成时刻 `generated_at` 代替。
- `account` 为 null：未指定账户且用户没有任何账户/持仓/现金记录，或账户数据整体无法计算（此时 `gaps` 含 `{key:"account", reason}`）。
- `account` 非 null 时：`total_assets`、`cash` **不为 null**，口径与 §7.2 `/portfolio` 相同（无现金记录 `cash="0.00"` + gap `cash`；无现价按成本估算并使 `data_status=partial`）；`position_pct` 仅在 `total_assets=0` 时为 null；`pnl_day` 在缺上一交易日持仓快照或任一持仓缺昨收时为 null 并记 gap `account.pnl_day`，不填 0。
- 旧版日报读取投影不回写；旧记录缺顶层 `data_as_of` 时投影为 null。

`DailyDimensionAnalysis`：`{dimension: dimension, facts: TextWithEvidence[], feature_refs: [{feature_key: string, status: "declared"|"verified_doc"|"verified_live"|"gap"|"deprecated"|null, evidence_ids: string[]}], data_status, data_as_of: string(datetime)|null, gaps}`；`data_status`/`gaps` 用 §1.1。

- `facts` 只描述快照中已知的事实，引用本份日报顶层 `evidence`；同股证据沿用 §5.3 的代码前缀，不能悬空。未知指标的 `Evidence.value=null`，并记对应 gap；完全无来源时 `facts=[]`、`data_status=unavailable`、`data_as_of=null`，不补 0、不判 neutral。`feature_refs.status=null` 表示未登记，不能视为 verified_doc。
- 六维是**事实覆盖**，不是六个新交易策略：技术/资金/基本面/情绪/板块与大盘/消息各列已知事实或缺口；不为凑满维度发明阈值、分数、看多看空结论。规则观点继续读 §5.2 的 `dimension_matrix`，只含实际启用策略；不把无规则的事实行塞入矩阵或置信度公式。
- 字段等级与取数完整性独立：有 declared 数据不代表通过 G2；verified_doc 最多支持 simulating。F23 标题展示不等于风险识别验收，公告仍仅标题与原文链接（§5.1），不新增正文/摘要资讯能力。
- `analysis_snapshot_id` 对应生成时刻的本人数据。历史日报只在读取投影中补 null，不更新旧正文；新输入产生新 revision。一个维度失败不阻断其他维度或整份日报，顶层汇总对应 gaps。

#### 7.11.2 风控设置与可判定性（status: draft；P2N-02/08）

沿用 §7.5 `GET/PUT /risk-controls`（不分页）。GET 返回六项有效设置；PUT 请求项 `{control, enabled: boolean, params: object}`，只覆盖所提交的 control，未提交项保持原值；返回完整六项有效设置（含只读 `source`）。同一 control 重复、未知键或参数类型错误 → `400 VALIDATION_ERROR`；合法类型但超出配置 min/max、区间 min > max → `422 RISK_CONTROL_INVALID_PARAMS`。整次更新原子提交，不部分写入；默认值以 plan §6.1 配置为准，允许范围见下表（T-A25）。

| control | params 的键（类型） |
|---|---|
| `stop_take` | `long_horizon_default_stop_pct: string(decimal)`、`clamp_to_price_limit: boolean` |
| `position_cap` | `single_position_max_pct: string(decimal)` |
| `total_exposure` | `regime_ranges: {uptrend: [string(decimal), string(decimal)], range: 同上, downtrend: 同上}`、`regime_confirm_days: int` |
| `sector_concentration` | `sw_l1_max_pct: string(decimal)`、`concept_max_pct: string(decimal)` |
| `loss_streak_drawdown` | `closed_loss_streak: int`、`drawdown_from_peak_pct: string(decimal)`、`strategy_sim_fail_streak: int`、`pause_on_trigger: boolean`、`pause_days: int` |
| `plan_violation` | `checks: string[]`（只取 plan §6.1 已列的五种检查，不接受自定义表达式） |

**参数范围（T-A25 裁定，status: draft；前端表单与后端校验共用）**：闭区间；百分比为 string(decimal)，最多 2 位小数；int 必须为整数；boolean 无范围。超出 → `422 RISK_CONTROL_INVALID_PARAMS`（`fields[]` 指明键）。

| control | 键 | 默认 | min | max | 说明 |
|---|---|---|---|---|---|
| `stop_take`(RC1) | `long_horizon_default_stop_pct` | -20 | -50 | -5 | 必须为负；关闭 RC1 用 `enabled=false`，不用 0 |
| `stop_take`(RC1) | `clamp_to_price_limit` | true | — | — | boolean |
| `position_cap`(RC2) | `single_position_max_pct` | 20 | 5 | 50 | 沿用 plan §6.1 ◇ 5–50 |
| `total_exposure`(RC3) | `regime_ranges.uptrend` | [60, 90] | 0 | 100 | 每个区间 `0 ≤ 下限 ≤ 上限 ≤ 100`；下限 > 上限 → 422；三档之间不强制单调 |
| `total_exposure`(RC3) | `regime_ranges.range` | [40, 60] | 0 | 100 | 同上 |
| `total_exposure`(RC3) | `regime_ranges.downtrend` | [0, 30] | 0 | 100 | 同上 |
| `total_exposure`(RC3) | `regime_confirm_days` | 2 | 1 | 5 | 交易日；须与 F25 计算一致，改动只影响提示口径 |
| `sector_concentration`(RC4) | `sw_l1_max_pct` | 40 | 10 | 100 | 100 等于不预警，但仍为 enabled |
| `sector_concentration`(RC4) | `concept_max_pct` | 50 | 10 | 100 | 概念数据未接入时该项 unknown + gap |
| `loss_streak_drawdown`(RC5) | `closed_loss_streak` | 3 | 2 | 10 | 已平仓笔数 |
| `loss_streak_drawdown`(RC5) | `drawdown_from_peak_pct` | 10 | 3 | 50 | 正数，表示自高点回撤幅度 |
| `loss_streak_drawdown`(RC5) | `strategy_sim_fail_streak` | 5 | 3 | 20 | 模拟跟踪次数 |
| `loss_streak_drawdown`(RC5) | `pause_on_trigger` | true | — | — | boolean |
| `loss_streak_drawdown`(RC5) | `pause_days` | 5 | 1 | 20 | 交易日；仅 `pause_on_trigger=true` 时生效 |

- 范围放在后端常量/配置校验中（与 `config/risk_controls.yaml` 默认值同源），不放进用户可改项；系统默认值本身必须落在范围内（启动校验）。
- 前端输入控件按本表设 min/max/step（百分比 step 1，可输 2 位小数）；“恢复默认”取各项的 `default`（见下）。

**T-A26 裁定（status: draft；P2N-02 缺口）**：

1. **GET/PUT 响应的 `default`**：每个 control 元素为 `{control, enabled, params, source, default: object}`。`default` 与 `params` 同形（同键、同值类型），值取系统默认（plan §6.1 / `config/risk_controls.yaml`），用户覆盖不改变它；只读，PUT 提交时带 `default` → `400 VALIDATION_ERROR`（未知键）。`enabled` 的系统默认六项均为 `true`，不单独返回。
2. **RC1 价格触发（MVP）**：价格一律用**不复权**实际成交价，与 `stops` 同口径；不用 qfq（F16–F18）比较。
   - 盘中：只用新鲜的最新价（未超 `realtime.yaml` 的 `stale_threshold_s`）；`last ≤ stop_loss` 触发止损，`last ≥ take_profit` 触发止盈；最新价缺失或过期 → 该项 `unknown` + gap，不判定。
   - 收盘后（日线入库后）补判：当日 `low ≤ stop_loss` 记止损触发，`high ≥ take_profit` 记止盈触发；同一日两者都满足按**止损**记（保守）。事件时点 = 盘中为该价格时间戳，收盘补判为当日 15:00（北京时间）。
   - 持有期间发生除权除息后，原 `stops` 不自动换算，该项 `unknown` + gap（`stops_ex_rights`），直到重新生成 `stops`。
   - 触发只产生风控事件与提醒，不改动作、不下单、不阻止 sell/reduce。
3. **时间止损 `time_stop_days`**：按**交易日**（交易所日历，个股停牌日照常计数）。起点 = 第 0 天：持仓取当前这段持仓的首笔买入成交日（清仓后重开重新起算），尚无成交的建议/计划取其生成日（as_of 所在交易日）。第 N 个交易日**收盘后**仍持有即触发（边界当天算，计入第 N 天），事件时点为该日 15:00（北京时间）。起点或成交缺失 → `unknown` + gap，不推断。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/risk-controls/evaluation` 🔒 | **新增**。`?security_code=` 必填，`&account_id=` 可选（默认账户同 T-A12）。只读本人已有缓存/持仓/设置，不拉取、不写事件或建议 → `200 RiskEvaluation`。参数错误 400，证券不存在或账户不存在/他人账户 404。 |

`RiskEvaluation`：`{account_id: uuid|null, security_code, name, snapshot_id: uuid|null, evaluated_at: string(datetime), controls: [{control: risk_control, enabled: boolean, state: "ok"|"triggered"|"unknown"|"disabled", flags: RiskFlag[], gaps}], evidence: Evidence[], DataStatusBlock}`。

- controls 恰好六项，按 RC1–RC6 排列；就所选证券评估单股项并附适用的账户/策略项。`flags[].evidence_ids` 指向本响应 evidence；snapshot_id 是读取依据的快照，完全无数据为 null。
- enabled=false → disabled，可保留 RC1 关闭警示但不施加该项门控；已知触发 → triggered（仍可带部分输入 gap）；所需输入齐全且未触发才 ok；否则 unknown + gap，flags 可为 []。未接通 RC5/RC6 时是 unknown，不冒充 ok 或 disabled。
- RC3 沿用 F25，不用卡片的 F50 代替；F25 null → “大盘环境未知”、partial、无 RC3 门控。RC2/RC4 缺分母/归属时额度未知（quantity_cap=null），不是无限额度或零额度；不得因此消除其他可执行性原因。未分类不触发 RC4。RC1–RC4 阈值、取整及 buy/add 门控仍按 plan §2.5.6/T-A15/T-R21，绝不改动作或阻止 sell/reduce。
- 当前评价不能回写历史建议；建议仍读取生成时的风控标记与 gap。实际风控事件由业务作业幂等写入，复用 §7.5 的 RiskEvent，不增加第二套事件状态机。
- **T-A33（R4）**：`RiskEvaluation` 的 `DataStatusBlock.data_as_of` 取参与判定各输入时点中**最早**的非空值，全空为 null（同 T-A29 日报口径，不取最新、不取 evaluated_at）。

**T-A52 裁定（status: 生效（T-A69，隔离 PG 复验 T-O54 与 tb95 22/22 T-T36b 通过后）；「清除覆盖」接口，v0.2.9 内；docs/reviews/T-A52-risk-control-reset-ruling.md）**：

1. **语义**：`DELETE /risk-controls/{control}` 删除**操作者本人**该 control 的 `scope='user'` 覆盖、恢复继承（文件默认 → system 行 → 本人 user 行链回退），不是删除配置本身。**权限边界（用户裁定）**：只能删除本人 user 行；system 行与文件默认一律不可经本接口删除或改动；普通用户对 system 行无任何写/删路径（变体形状一律 `404 NOT_FOUND`，隐藏存在性，不提供 403 探测面）；不设管理员跨用户重置；system 行管理入口属独立管理员功能，不在本契约范围。
2. **响应与幂等**：`200 list[RiskSetting]`（六项，与 GET/PUT 同形，删除即刷新）。无本人覆盖时重复清除 → 200、状态不变、无新增副作用（幂等终点「本人无覆盖」），不追加历史与审计。
3. **鉴权/CSRF/顺序**：沿 §1.3——未登录 401、非 approved 403 ACCOUNT_NOT_APPROVED、缺/错 CSRF 403 CSRF_FAILED、未知 control 404；判定顺序按 §1.3 v0.2.9 #30，解析不先于认证与 CSRF。
4. **存储（迁移 0028）**：`risk_control_settings` 加 `override_active boolean NOT NULL DEFAULT true`；清除置 false，user 行读取（effective_config/entries）一律加 `override_active=true` 过滤；历史与 FK 不动，`risk_control_settings_history` 追加一行 `enabled=null, params=null` 表「清除」；PUT 再覆盖时置回 true。不物理删行（append-only 与 FK 完整）。
5. **审计**：`risk_control.reset`，`actor_id=操作者本人`、`target_type=risk_control_setting`、`target_id=被清 user 行 id`（幂等重放 target_id=null 且不写审计）、`detail={control, history_id, had_override}`；actor 与行属主必须一致（「只有本人动本人」核对口径）。
6. **position_cap 终点**：清除后若 profile `max_single_position_pct` 非 null 则生效、`source=user`，否则文件默认、`source=system`——「回到继承」而非「回到文件默认」，前端按返回值展示。
7. **并发**：与 PUT 共用既有 advisory lock（同 owner 串行）；只删指定 control，不批量。
8. **T63 验收**：PUT 改值 → DELETE → GET 回继承值且 `source` 相应变化；幂等重放零副作用；清除后求值链路立即用继承值，无需重启；每两次真实清除间幂等重放不产生新 history/审计。负例集（401/403 CSRF/404 未知 control/404 变体/幂等 200/并发串行等）见裁定文档 §D9，随 T-B95 定点用例。
9. **回滚指引（T-A72 修订，取代 T-A69 版「保持 0028」；依据 docs/reviews/T-A70-tb99e-0029-review.md 与 0029 源码）**：
   - **代码下限**：不得回退到 T-B98b 之前（team-b 原提交 f20fd83，主线拣入后为 2442b9d）。更早的代码不认 `override_active`，会把已清除的覆盖重新当作有效；旧代码 PUT 也不会把它置回 true，新代码会静默忽略用户的新值。此外，部署到用户库的代码**必须包含 0029 迁移文件**（`src/backend/migrations/versions/0029_tb99e_gate_bindings.py`，blob 05774fe，T-B109 只入链此一个文件，不带门控应用代码），否则启动检查因库版本不在代码迁移链内而拒启。M6 部署后（T-A77），还必须包含 0030（`0030_ta73_purge_gate_facts.py`，`down_revision=0029`）。
   - **库版本**：M6 合入前库保持 0029；M6 部署时升到 0030（T-A77）。迁移链为 …→0028→0029→0030 线性单 head。0030 只新建两个 `ops` 函数，不改表、不动数据；降回 0029 只删这两个函数，但不得降到 0029 以下（见下条）。
   - **0029 不可降级（作废 T-A67 §10 第 4c 步「降到 0028」）**：0029 downgrade 在 `ingest_private.mairui_gate_scopes` 或 `mairui_gate_bindings` 任一非空时直接抛出 `mairui_gate_facts_require_authorized_archive` 并拒绝（0029:85-92）；scope 行没有删除路径（aia_ingest 对 scopes 只有 SELECT/INSERT/UPDATE，0029:78）。用户库已有绑定（T-O45），所以 0029 按单向迁移处理。不得为了能降级而删除或改写绑定行、scope 行；错误信息中的「authorized archive」目前不存在，另立 0030 待办（docs/reviews/T-A72-0030-backlog.md）。0028 层的规则不变：有 `override_active=false` 行时 0028 downgrade 拒绝，不得为降级删除或改写 false 行（历史不可变，改写等于捏造用户没设过的值）。
   - **部署顺序**：先停全部 api/worker/ingest 进程，再迁移，再启动新代码；不得让未重启的旧进程连新库。任何操作前先执行 `deploy/scripts/db-backup.sh` 并做恢复演练；不 `alembic stamp`，绝不 `down -v`。修正只能写在 0030（以 0029 为 `down_revision`），不得改动 0029 文件本身。
   - **用户电脑上未跟踪的 0029 文件**（已核对 blob 与入库版一致，05774fe）：经用户批准后由运维执行：① 停 api/worker/ingest（`docker compose stop`）；② db-backup.sh 备份并对 dump 做恢复演练，记录 sha256；③ 把未跟踪副本移到仓库外的备份目录（部署验证通过后再删）；④ 清掉 `__pycache__` 中 0029 的 pyc；⑤ ff 更新到含 M6 的提交，确认 `git status` 干净、0029 blob 仍为 05774fe；⑥ 用 up.sh 启动（T-A77 修订，取代原「不执行 upgrade」）：compose 按 migrate（0029→0030）→ timescale-apply → db-roles（单事务）→ 应用服务的顺序启动，前一步失败则应用服务不启动；⑦ 启动后立即在 db-roles 容器里跑 verify-roles，并核对 `alembic current` 与 `alembic heads` 均为 0030。verify-roles 非 0 时立即停全部应用服务、保留备份、报架构师。迁移前不得对 0029 库跑新版 verify-roles（缺 gate 函数必判 FAIL，不是故障）。若比对或库内对象（schema/触发器/函数定义）与入库版不一致，则冻结不更新，按 T-A70 评审第 6 节由架构师写收敛的 0030。
   - **grants 口径（以 T-O57 为准）**：`deploy/db/roles/grants.sql` 的通配授权排除 `ingest_private`，只给 aia_ingest 最小权限（与 0029 一致）；**aia_api、aia_maint 不得获授 `ingest_private` 的任何权限**，verify-roles 对二者做 permission denied 反例。RLS（0029:30-35）只是第二道屏障，不能替代授权排除。0030 的 `ops.gate_user_refs`、`ops.purge_user_gate_facts` 只授 aia_maint EXECUTE，aia_api、aia_ingest、PUBLIC 一律不授（T-O60/T-O61）。

#### 7.11.3 模拟跟踪结果（status: draft；P2N-03/05/08）

细化 §7.8 `GET /suggestions/{id}/tracking`：他人/不存在的建议返回 404；本人的建议返回 `200 {t1: Stat, t5: Stat, t20: Stat, results: TrackingResult[], DataStatusBlock}`。无结果 results=[] 并列 gap；GET 不触发行情拉取或补算。

`TrackingResult`：`{strategy_version_id: uuid, instance_id: uuid|null, action: action, horizon_days: 1|5|20, state: "pending"|"complete"|"untradable"|"excluded"|"unavailable", entry_at: datetime|null, entry_price: string(decimal)|null, exit_at: datetime|null, exit_price: string(decimal)|null, benchmark_code: string, benchmark_entry_price: string(decimal)|null, benchmark_exit_price: string(decimal)|null, return_pct: string(decimal)|null, benchmark_return_pct: string(decimal)|null, excess_pct: string(decimal)|null, max_drawdown_pct: string(decimal)|null, max_runup_pct: string(decimal)|null, direction_correct: boolean|null, invalidation_triggered_at: datetime|null, exclusion_reason: string|null, price_basis: "qfq", cost_applied: boolean, evidence: Evidence[], evidence_ids: string[], gaps}`。

- 每策略版本/建议/跟踪期唯一；停牌、一字板、forced_hold、wait 的排除与方向定义按 plan §2.8，不把 sell/reduce 的标的区间收益强行取反；缺基准只把相关结果置 null + gap。pending 表示尚未到期；unavailable 表示到期但缺计算所需数据；untradable/excluded 必有 exclusion_reason，不进入有效样本 n。价格依据列入本条 result 的 evidence，evidence_ids 必须能解析；可成交性使用不复权实际价格，收益及 entry/exit_price 使用同一 as-of 的 qfq 序列，原价与复权价分开留证。分钟线若无可核实的复权衔接依据，该项 unavailable + gap，不混用 raw/qfq 或生成时参考价与模拟入场价。
- `results` 是**单条观测**，其十进制结果是 §5.1“统计收益使用 Stat”的明确草案例外，不是胜率/业绩聚合；界面必须写“模拟，不代表实际收益”。旧 t1/t5/t20 保留 Stat 约束，不能把 n 虚增到 5 来显示单样本；新前端读 results。策略聚合继续只用 Stat，n<5 为 null、n<30 标 small_sample。
- §7.4 版本跟踪统计 `by_horizon[]` 追加 `pending_count: int`、`untradable_count: int`、`excluded_count: int`，均非负；有效 n 仍见各 Stat，不以总记录数替代。scope=site 只能返回策略级匿名聚合，results 只走本人建议端点，不随 site 暴露。

**T-A27 裁定（status: draft；P2N-03 缺口）**：百分数沿 §3（12 = 12%），存 4 位小数、ROUND_HALF_UP，展示 2 位。

1. **单条观测的 `max_drawdown_pct` / `max_runup_pct`**：路径 = 入场价 + 持有期内各交易日 qfq **收盘价**（最后一点为 exit_price；T+1 只有入场与退出两点），按证券本身价格计算，不随 action 取反，不用盘中高低价。
   - `max_drawdown_pct` = min_t(P_t / max_{s≤t} P_s − 1) × 100，≤ 0（峰谷回撤，起始峰为入场价）。
   - `max_runup_pct` = max(0, max_t P_t / entry_price − 1) × 100，≥ 0（相对入场的最大有利幅度）。
   - 路径中任一交易日缺 qfq 收盘（停牌日沿用无行，不补价）只跳过该日；入场或退出价缺失 → 两项 null + gap。
2. **聚合 `profit_loss_ratio`**：仅取有效样本中 action ∈ {buy, add, hold} 的 `return_pct`（毛收益）；盈利 = return_pct > 0，亏损 < 0，等于 0 不计。比值 = 盈利样本平均 return_pct ÷ |亏损样本平均 return_pct|。n = 盈利 + 亏损样本数，沿 Stat 规则（n<5 null，n<30 small_sample）；无亏损样本 → null + gap（`no_losing_samples`），有亏损无盈利 → 0。sell/reduce/wait 不进入盈亏比（仍按 plan §2.8 进入 win_rate/方向统计）。
3. **同一策略版本多个实例**：观测唯一键为 (suggestion_id, strategy_version_id, horizon_days)，一条建议同版本只算一个样本，不按实例重复计数。`instance_id` 取产生该建议的实例；若同版本多个实例同时对应该建议，取 `created_at` 最早者（并列取 id 最小），其余实例不另建观测，在 evidence 中列出其 id。版本统计 `by_horizon` 按此去重；本版不提供实例级统计。

**T-A33 裁定（status: draft；P2N-R08 歧义 084–092 + T-A32 R5）**：交易日一律按交易日历、北京时间；日历缺失时不推进计数、不解除暂停，记 gap。

1. **跟踪结果冻结（R5）**：complete/untradable/excluded 一经写入即冻结；`unavailable` 由盘后作业在到期后 5 个交易日内每日重算，数据补齐即改写为相应状态（版本统计同步重算），满 5 个交易日仍缺则冻结为 unavailable。
2. **模拟失败（084）**：失败 ⇔ `state=complete` 且 `direction_correct=false`；`true` 为成功并清零计数。范围：**本人**建议 × 策略版本；跟踪期按**策略自身周期**取（T-A36，用户已定选项 B）：`intraday_t`→1、`short`→5、`swing`→20、`long`→20（T-A37 修正：取不短于典型持有期的最长可用跟踪期，跟踪期只有 1/5/20；RC5 此项只是早期预警，终评见 plan §2.5.7/§2.8.2），周期取该观测所属建议中该版本结论的 `horizon`，缺失时取策略版本声明的周期；仍不清楚 → 该观测跳过（不计失败、不清零）并记 gap `sim_fail_horizon_unknown`，不默认 5 日。TB-A48 裁定：多周期版本（`horizons` 长度 > 1，如 H-01 v1/v2）无唯一声明周期，该级回退终局不可解析——结论缺 horizon 的观测保持跳过 + gap，不得回填挂载周期 swing、不得取数组首元素；`simulated_failures(version_horizon=…)` 生产者对多周期版本必须传 `None`。H-01 系统实例挂载周期 = `swing`（新挂载传 `horizon="swing"`，已存实例不回溯）。详见 `docs/reviews/TB-A48-horizon-ruling.md`。映射配置键 `rc5_loss_streak_drawdown.sim_fail_horizon_by_horizon`（取代 `sim_fail_horizon_days`）；观测按 T-A27 第 3 点去重。序列按 `exit_at` 升序（并列按 suggestion_id），pending/unavailable/untradable/excluded 跳过，既不计失败也不清零。连续失败数 = 序列尾部连续失败条数。
3. **已平仓一笔（085）**：账户 × 证券的一个持仓段：持仓数从 0 变正起，到回到 0 的那笔成交止（部分减仓不结束）。盈亏 = 段内卖出金额 − 买入金额 − 全部费用税（含费用）；< 0 为亏损，> 0 为盈利并清零，= 0（平本）跳过、不清零。按结束成交 `executed_at` 升序，并列按成交 id。段起点早于导入数据（无开仓成交）→ 该段不计入并记 gap。
4. **暂停期（086/091）**：第 0 天 = 触发时刻所在交易日（非交易日或 15:00 后触发 → 下一交易日）；暂停覆盖第 1..N 个交易日，`paused_until` = 第 N 个交易日 15:00；系统在 `paused_until` 及之后的首次作业恢复（幂等，晚跑不补偿）。触发为**边沿**：亏损笔数/失败数增至 ≥ 阈值的那次、回撤从阈值下方越过阈值的那次；暂停中再次边沿触发 → `paused_until` 取 max(现值, 新计算值)，不叠加。期满时条件仍满足但无新边沿 → 不重新暂停，只保留 RC5 `triggered` 标记。
5. **系统期满恢复（092）**：期满恢复与用户 resume 做同一检查（§6.0A 第 4 点）；版本不可运行 → 不改为 active，实例保持 paused、`pause_reason_code` 不变、`paused_until` 置 null（不再自动恢复），写 `actor=system` 事件 `detail={expiry_blocked: "STRATEGY_VERSION_NOT_RUNNABLE", lifecycle}` 并发站内通知；用户可归档。不得借期满恢复退役策略。
6. **RC6 数量超计划（088）**：按同一计划版本**累计**：该版本有效期内同账户、同证券、与计划同方向成交数量之和（被冲正/撤销的成交剔除，冲正后重算），累计 **>** 计划数量才触发（等于不触发）；每计划版本只触发一次。
7. **RC6 计划边界（089）**：计划版本有效期为半开区间 `[生效时刻, 被替代/关闭时刻)`，与成交 `executed_at` 比较；同刻成交归新版本，关闭同刻已无效。仅有日期的成交以当日 15:00 比较，当日版本有变更 → 该成交 RC6 unknown + gap、不出 flag。同证券多个有效计划：先取与成交同方向的计划判数量；无同方向计划时才判 `opposite_side`；仍多条按生效时刻最新、并列 id 最小取一条。
8. **健康度缺日（090）**：某交易日缺 `strategy_health_daily` 时，`weight<0.8 连续 5 日` 与 `weight≥0.9 连续 10 日` 两个计数都清零（不跃迁，保守），记 gap；不跳过、不暂停计数。
9. **内部复验恢复（087）**：内部评估在第三阶段启用（问题 26）；未启用时该条件不参与，`observing→published` 只看权重条件。启用后：恢复 ⇔ 稳健度 ≥ 基线 × `health.internal_recover_ratio`（默认 0.8，可配置）且与权重条件同时连续 10 个交易日成立；0.8 高于降级线 0.7 形成迟滞。

#### 7.11.4 站内提醒与解释（status: draft；P2N-05/06/07/09）

- `/signals`、`/notifications`、`/alerts` 列表沿用 §1.2 游标；signals 排序 `at desc, signal_event_id desc`，通知 `created_at desc, id desc`；其他筛选/结构沿用 §7.7B/7.8。所有读取和 SSE 只允许本人证书或本人用户层事件，事件重放不重复生成建议、提醒或通知。
- 细化现有 `GET/PUT /notification-preferences`（不分页）：本轮补 `intraday_cadence: "realtime"|"1min"|"3min"|"5min"`，默认 1min；PUT `{intraday_cadence}` 仅更新此键，返回生效值；非法值 400 VALIDATION_ERROR。只影响推送合并节奏，不降低采集/求值频率。免打扰/外部 channels 不在本切片改契约或开放发送。
- SSE 仍用 §8 既有事件；在保留窗口内按 Last-Event-ID 续传；重连后客户端同时重读本人列表/聚合，补偿超过十分钟的缺口并按事件 id 去重，不把保留窗口当完整历史。断线退回既定十五秒轮询，不新增 WebSocket 或第二套动作事件。
- §5.2 Suggestion 与 §5.3 DailyReport 的既有 `explanation` 追加 `paragraphs: TextWithEvidence[]`、`prompt_version: string|null`、`validation_status: "passed"|"fallback"`；旧存档读投影可缺这些新增键，前端退回既有 text。新记录 paragraphs 中的引用只指本对象 evidence；text 为各段 text 按顺序换行拼接。LLM 成功时 source=llm、validation_status=passed；模板兜底为 source=template、validation_status=fallback（未调用时 llm_call_id=null），模板不标 AI 生成。
- **T-A36 裁定（P2N-05i 待定 ①–③，与 P2N-09 对齐）**：
  1. **逐股/分歧绑定**：`DailyReport.stocks[]` 每项追加 `explanation: Explanation | null`（llm_task `daily_report_stock`），`Suggestion.divergence[]` 每项追加 `explanation: Explanation | null`（llm_task `strategy_divergence`）；结构同上（含 paragraphs/prompt_version/validation_status/fallback_reason）。引用只指本项对象：逐股只引该证券代码前缀的日报证据，分歧只引本建议证据且限于该项 `dimensions` 相关证据。为 null 或键缺失 → 该位置**不显示解释**，前端不再复用或筛选顶层整体解释，不按证据推断归属。
  2. **回退原因**：`explanation` 追加 `fallback_reason: explanation_fallback_reason | null`，枚举（进 `/meta/enums`）= `not_enabled`（未启用/未配置路由，未调用）| `budget_exceeded` | `timeout` | `provider_error` | `validation_failed`（守卫拒绝）。`validation_status=passed` 时必为 null，`fallback` 时必非空；`not_enabled`/`budget_exceeded` 时 `llm_call_id=null`，其余有调用记录则非空。旧存档缺键 → 前端只显示“模板兜底”，不猜原因。
  3. **调用记录深链**：`llm_call_id` 只对管理员有意义；`GET /admin/llm/usage` 🛡 追加 `?call_id=` 过滤，返回该条记录（不含原始 prompt 中的个人信息、不含 key）。前端：仅管理员且已有 `/admin/llm/usage` 页时显示链接 `/admin/llm/usage?call_id={id}`，否则管理员只读显示 id；非管理员不显示 `llm_call_id`。
  4. **数字约定（P2N-R09-065）**：解释中的数字 N 写成 d 位小数时，须等于证据值按 ROUND_HALF_UP 取 d 位的结果，单位一致；百分数/价格 d ≥ min(证据小数位, 2)，计数类须与证据精确相等；只允许 万/亿 的精确换算（÷10⁴/÷10⁸ 后按同一规则）。“约/近/超过”等字样**不放宽容差**。配置键 `explain_guard.min_decimals`（默认 2）。不满足 → `validation_failed`。
  5. **动作转述（066）**：**无白名单**。LLM 文本中出现任何动作词（含对规则动作的事实性转述，如“规则给出买入”）一律拒绝回落模板；动作只由界面从 `action` 等规则字段展示。
  6. **否定/引用中的禁用词（067）**：**无例外**。LLM 文本出现禁用词即拒绝，不论否定式、引号或免责语境；固定免责由系统在 LLM 文本之外追加（不经 LLM、不计入守卫），LLM 不得自写免责声明。
- 解释在不可变正文提交**之前**生成/回退；提交后不异步改正文，必要时生成新建议/日报 revision。任何缺引用、新数字、越权信息、动作词或承诺违规均回退模板；超时/预算/模型故障不影响规则结论。action/score/confidence 与解释路径无关。不得发送密钥、账户/成交标识、个人信息或原始交割单；本切片只用公开/纯合成结构化证据联调，真实私有输入另核隐私门槛。
- **证书外键（T-A28）**：本切片所有 `source_licence_id` 均 FK → `app.user_data_licences.id`（plan §0A.3 第 5 条旧称 `ops.data_licences` 已更正）；不新建证书表，不按其他标识猜映射。
- **通知合并与推送节奏（T-A28，最简方案）**：
  1. **事件不合并**：每条 `signal_events`/建议变化照常逐条持久化，`/signals` 能查到全部；合并只作用于站内 `notifications` 记录与推送。
  2. **合并窗口**：只合并 `security_code` 非空的盘中通知；键 `dedup_key = "{security_code}|{notification_kind}|{bucket}"`，`bucket` = 北京时间按 10 分钟取整的窗口起点（`[hh:m0, hh:m0+10min)`，左闭右开，固定对齐，不随首条滑动）；`(user_id, dedup_key)` 唯一，写入用 upsert，并发安全。日报、导入、系统等无证券通知不合并。
  3. **持久化**：首条事件建通知（`created_at`=首条时间）；窗口内后续事件 upsert 同一行：`merged_count += 1`、`updated_at`=最新事件时间、`title/body/severity` 取最新（severity 取窗口内最高）、`target` 指最新对象；每个被合并的引用写子表 `notification_refs(notification_id, ref_type, ref_id, at)`，唯一 `(notification_id, ref_type, ref_id)` 保证重放幂等。`Notification` 追加 `merged_count: int`（≥1）、`updated_at: datetime`、`refs: [{type, id, at}]`（按 `at desc` 最多 20 条，全部见子表与 `/signals`）；旧记录投影 `merged_count=1`、`refs=[]`、`updated_at=created_at`。
  4. **已读**：一行一个未读单位，`unread-count` = 本人 `read_at IS NULL` 行数；标已读即整行（含全部 refs）已读。已读后同一窗口又来新事件：同行 `read_at` 置回 `null`（重新未读）并更新计数，不新建行；下一窗口另建新行。
  5. **推送节奏**（`intraday_cadence`，只作用于 SSE `notification` 事件；`signal`、`quote` 等不受影响）：`realtime` 每次 upsert 立即推；`1min/3min/5min` 按北京时间整 N 分钟对齐分桶，桶结束时对桶内变化过的每个通知 id 只推一次最新完整 `Notification`。`severity=important` 一律立即推。待推缓冲只在内存/Redis，丢失不补推——通知行是唯一事实来源。
  6. **断线补读**：SSE 事件进 §8 的 600 秒续传缓冲；重连带 `Last-Event-ID` 补发窗口内事件；超窗或无 ID 时客户端重读 `/notifications?unread=true` 与 `unread-count`。客户端按通知 `id` 去重，取 `updated_at` 较新者覆盖，不重复计未读。
- **提醒流细则（T-A31，补 T-A28；P2N-05f/06）**：
  1. **重连与超时**：服务端每次建流先发 `retry: 3000`。客户端断线后按 3s 起、每次失败翻倍、上限 60s 退避，每次 ±20% 抖动；连接保持 ≥ 60s 后退避归零。45s（3 个心跳周期）没收到任何字节视为断线，主动关闭重连。连续 3 次建流失败即开始 §8 的 15s 轮询（T-A32：一次尝试只要在连上后不满 60s 就结束，都算一次失败，含非 200、网络错误、HTTP 200 后 EOF、45s 读超时；保持 ≥ 60s 后失败计数与退避一起归零），同时继续按上限退避尝试 SSE，连上后停止轮询。
  2. **去重容量与持久化**：客户端在内存里保留最近 1024 个事件 id（先进先出）和每个通知 id 的最新 `version`；**不跨刷新持久化**（不写 localStorage/IndexedDB）。页面加载或首次建流不带 `Last-Event-ID`，一律重读未读列表与 `unread-count`。
  3. **`refs[].type`**：新增枚举 `notification_ref_type` = `signal`（`id` = `signal_events.id`）、`plan_condition`（`id` = `plan_conditions.id`），进 `/meta/enums`；`id` 一律小写带连字符的 uuid 字符串；新类型须先改契约。每个 ref 加 `route: string | null`，由服务端生成：`plan_condition` → `/plans/{plan_id}`；`signal` → `null`（V1 无单事件页）。`route=null` 一律**不跳转**，该 ref 只展示类型与 `at`；不要求前端按 `at` 定位，通知详情保留既有的 `/signals` 总入口即可（T-A32 更正）。前端不得自拼路由。
  4. **版本冲突**：`Notification` 追加 `version: int`（≥1），通知行每次变化（合并、改正文、标已读、全部已读、重新未读）都在同一事务内 `+1`。客户端只保留 `version` 大者；`version` 相同视为同一内容，直接丢弃后到者，不比较 `updated_at` 或正文。旧记录投影 `version=1`。
  5. **超窗/未知 `Last-Event-ID`**：事件 id 为每用户单调递增的十进制字符串。带了 `Last-Event-ID` 但它不是十进制、大于当前序号、或早于 600s 保留窗时，服务端在流开头先发控制事件 `event: reset`，`data: {reason: "expired" | "unknown", latest_event_id: string | null}`，随后照常推实时事件；客户端收到后清空事件 id 缓存并全量重读。不带 `Last-Event-ID` 不发 `reset`。HTTP 状态仍为 200。
- 计划/草案/提醒状态机已在 §7.7/7.7B，P2N-07 直接实现，**不新增候选直接转计划入口**；simulating 禁生草案，G7 按 T-A109 条款审核（可在授权范围内由编排者代批）。

**T-A34 裁定（status: draft；P2N-06 多实例）**：一条 `signal_events` 行按（策略版本 × params_hash × 证券 × 快照）共享，可扇出到同一用户的多个实例；以下口径按“本人投影”写入时**冻结**，读取时不重算。

1. **匹配实例集合**：本人下同时满足 P2N-06 现有绑定检查的实例（运行版本 = 事件版本、scope/证券匹配、账户匹配且未归档、版本可运行、params_hash 一致），排序 `created_at asc, id asc`（同 T-A27 第 3 点）。
2. **`SignalEvent.instance_id`**：取集合中**已由该事件生成候选**（`intraday_candidate_refs` 有行）的第一个；都未生成候选（如 stale/resume 类事件）时取集合第一个；集合为空才为 null。`candidate_signal_id` 取所选实例由该事件生成的候选，没有则 null。不得随实例后续暂停/归档改写。
3. **新增字段** `SignalEvent.instance_ids: string(uuid)[]`：集合全部实例，同序，最多 20 个，空集合为 `[]`（加性字段，旧客户端可忽略）。
4. **建议归档**：同一用户同一事件只归档**一条**建议：先收集全部匹配实例的结论再一次调用归档；未受事件影响的实例结论沿用该证券最新建议中的原结论（不重算、不丢弃）。通知 `target` 指这条建议。
5. **通知与 refs**：一个事件对同一用户只 append **一次**通知（不按实例重复）；ref 按事件计：`{type: "signal", id: signal_events.id}`，与实例数无关。`merged_count` 只在子表**新插入**一行 ref 时 +1，重复 ref（含多实例扇出、重放）不增 `merged_count` 也不增 `version`。同一事件的多个候选不另写 ref，从 `/signals` 的 `instance_ids`/`candidate_signal_id` 取得。
6. **严重度**：invalidation → important，其余 → attention，按事件定，不因实例数提高。


**T-A40 裁定（计划草案数量与实例预算）**：

1. Phase 2 不新增“单笔最大亏损上限”配置；模板 risk_suggestions 仅展示，不作约束。该项未配置时跳过，不报 gap、不拒绝，也不以现金/资产比例自造上限；数量仍取其余现金含费用缓冲、单只上限、实例预算、ST 限额等约束的最小值。草案仍输出 `max_loss_amount = qty_range.max × (price_range.high − stop_loss) + 买卖费用估算`，`max_loss_pct = max_loss_amount / 总资产 × 100`（百分数）。总资产未知时 pct=null 加 gap；没有 stop_loss 且 RC1 关闭时两值均 null 并警示。RC1 关闭但已有有效止损时保留计算值，仅警示不主动监测。
2. budget_amount=null 时预算不约束、不报 gap、不触发 STRATEGY_BUDGET_EXHAUSTED。非空时，已用额度为本人 active/triggered、buy/add 计划最新版本金额之和：优先 qty×price，缺其一用 size_amount，均缺则 unknown。归属按 plan_versions v1 冻结 candidate_signal_ids→候选 instance_id；多实例计划全额计入每个来源实例，不按持仓/成交反推。结果标 estimate，用户上下文冻结 budget_used、budget_amount、参与 plan_ids；多来源草案取各实例剩余最小值。任一参与金额 unknown 时拒绝 buy/add 并给 gap，不影响 sell/reduce；剩余≤0 触发 STRATEGY_BUDGET_EXHAUSTED，不生成买入/加仓草案。确认须重验预算，偏离确认不能绕过。

**T-A43 裁定（P2N-06 五表角色最小权限与旧事件迁移）**：S/I/U/D 分别为 SELECT/INSERT/UPDATE/DELETE，表均在 app schema；业务 worker 使用 aia_api，采集使用 aia_ingest，注销使用 aia_maint。

| 表 | aia_ingest | aia_api（含 worker） | aia_maint |
|---|---|---|---|
| notification_refs | 无 SIUD | S、I；无 U/D | S(notification_id)、D；无 I/U |
| intraday_candidate_refs | 无 SIUD | S、I；无 U/D | S(instance_id)、D；无 I/U |
| signal_states | 无 SIUD | S、I、U(last_tick_id,rule_states,state,changed_at)；无 D | S(source_licence_id,id)、D；无 I/U |
| intraday_universe | 无 SIUD | I、U(computed_at)，S(trade_date,source_licence_id,security_code,computed_at) 仅 UPSERT 所需列；无 D | S(source_licence_id)、D；无 I/U |
| signal_events | 无 SIUD | S、I；无 U/D | S(id,user_id,source_licence_id)、D；无 I/U，仍受归属保护 |

这是对 T-A38 Part 0 的正式收口；signal_states 维护 SELECT 增加 id，用于删除链依赖，T-A43 逐列差异条件由本裁定解除。未列操作/列不授予，不以表级 SELECT 替代维护谓词列；撤清遗留表级/列级权限及 PUBLIC/继承影响，禁止借此授 DDL/TRUNCATE/REFERENCES/TRIGGER。关联子查询仍依赖既定最小授权。共享事件删除按 source_licence_id→user_data_licences.user_id 判本人，user scope 同时核对 user_id，一致才允许经既有维护注销保护删除；不得撤触发器或改用属主绕过。

旧事件迁移遵守四条：
1. 仅凭可证明的历史证据（原始快照、明确外键、已核导入映射）回填；不猜归属、不清表。证据不足继续拒迁，由运维先受控隔离 legacy 存档，不擅自改方案。
2. instance_id/instance_ids 按 T-A34 排序后冻结；缺历史绑定为 unknown，不把 null/[] 当“已证实为空”，不进入新投影，不重跑规则补历史候选。
3. 通知 refs 只按显式历史关系建立；不补通知、不重置已读、不虚增 merged_count/version。
4. 降级必须完全可逆；0025 不得固定抛错冒充回滚，0026 降级前保留完整 refs，再升恢复；旧键冲突条件拒绝并保持事务/事实，不静默合并或丢数据。0027 维护窗口升降级复验仍为发布门槛。

#### 7.11.5 ingest 麦蕊统一出口（内部接口，status: draft；T-A87 / M-1，T-A89 修订 M-2，T-A91 修订 M-a/M-b/M-c 与两层守卫，T-A92 补运行时层缺口与验收口径；风控，须异源复核 R12/R14–R19）

不是 HTTP 接口，是 ingest 进程内的 Python 契约，实现见 plan.md「T-A87 M-1 IngestCore 外呼接线」。T-A89 修订第④条（证书状态以库为准、lease 不可伪造）并补 B-1(a)/B-2 契约要求。T-A91 修订：①拆成静态层（有限清单 S1–S6）与运行时层（`sys.addaudithook`，方案 A）两层并写明各自不负责的写法；②lease 改为 HMAC＋线程绑定＋`pg_locks` 核验（M-a）；④补准入 3s 时限与超时对齐（M-b）、状态写库失败同时写 HALT 与退出码 74（M-c）。

1. **唯一出口（含 B-2；T-A91 改为两层防护，见 ①a–①c）**：`src/backend/app` 下，只有 `app/ingest/egress.py` 可以打开连到麦蕊的连接。新增任何麦蕊外呼（包括将来的 `verify_licence`）都必须调用 `mairui_get`。不得有绕过出口的公开函数（例如已删除的 `daily_lists.wire`）；`process` 默认使用 egress 提供的 transport，不另暴露旁路入口。**T-A91 原则：静态层只守一份有限、明确列出的模式清单，不再逐轮追加绕过写法；动态写法一律由运行时层兜底（R16/R19）。** 清单外的写法不在静态层报红，不算静态层缺陷，但必须被①b 拦下。
   - **①a 静态层（A1s，AST 全量解析；只管下列 S1–S6，清单的增删须架构师改本条）**：
     - **S1 probes 冻结清单**：`src/backend/probes/` 下的 `.py` 文件以 41e517a 的 24 个文件为冻结清单（由守卫内常量逐一列出），清单外出现任何 `.py`（含子目录）即红。其中只有 `probes/common.py`、`probes/tb81.py`、`probes/tb86_history.py` 3 个文件允许同时含麦蕊域名与 HTTP 客户端导入；其余 21 个出现两者同现即红。（订正：T-A89 文案「恰好 3 个白名单文件、新增即红」指能外呼的 3 个文件；若按「3 个之外任何 .py 即红」，现存 21 个探针会全部误红，故改为冻结清单。）`app/` 不得导入 `probes`；dockerignore 白名单不含 probes。
     - **S2 egress 私有名**：egress 外（`app/`、`probes/`、`selfchecks/` 中的非测试代码）以任何静态形式——绝对导入、相对导入（`from .egress import …`）、别名（`import app.ingest.egress as E` 后 `E.X`）、`from … import *`、任意表达式上的 `.attr`——引用 `_https_get`、`HOST`、`_ISSUED_LEASES`、`_LEASE_LOCK_CONN`、`_lease_key`/签发闭包，或 egress 中任何下划线开头的名字，即红。测试文件（`tests/**`、`selfchecks/test_*`）可 monkeypatch `transport`，但不得读写上述私有名（A28 的反例夹具除外，须带 `# A28-negative` 标记且只在子进程中运行）。
     - **S2b netguard 窗口 API（T-A92）**：egress 外（同上范围）以任何静态形式引用 `app.ingest.netguard` 的 `egress_window`、`_egress_window`、`register_resolved_ip` 或 netguard 中任何下划线名即红；`app/workers/ingest.py` 只许 `install`，egress 只许上述窗口 API 与 `EgressBlocked`。测试文件只能在子进程中使用（A1r 正向）。
     - **S3 网络库导入**：`app/` 内除 `app/ingest/egress.py` 外，静态导入（`import x` / `from x import y` / 相对导入解析后）下列模块即红：`http.client`（含 `from http import client`）、`urllib.request`（含 `from urllib import request`）、`urllib3`、`requests`、`httpx`、`aiohttp`、`socket`、`ssl`。**登记例外（穷举）**：`app/master/sources.py` 只许 `urllib.request`/`urllib.error`/`urllib.parse`（交易所，worker 侧）；`app/workers/ingest.py` 只许 `import socket` 且只用 `socket.gethostname`（AST 断言除 `.gethostname` 外无其他 `socket.` 属性）；`app/ingest/netguard.py`（①b 新建）只许 `socket`、`ipaddress`。数据库/Redis 客户端库（psycopg、redis）不在本清单内。
     - **S4 麦蕊域名字面量**：`app/` 内除 egress（及 netguard 的域名常量）外，任何字符串常量（含 f-string 片段、bytes）匹配 `mairuiapi`（大小写不敏感）即红；`app/master/sources.py` 同样不得出现。
     - **S5 transport 注入**：`app/` 内（egress 之外）向 `mairui_get` 注入 transport（`transport=` 关键字，或经 `**kwargs` 字典的 `"transport"` 键）即红。**登记例外（唯一）**：`app/ingest/daily_lists.py` 的 `process(upstream=…)` 测试缝（41e517a `:273-289`，`get_kwargs["transport"] = upstream`）；同时 `app/` 内任何调用 `process(...)` 时传 `upstream` 即红（只有 `tests/**`、`selfchecks/test_*` 可传）。生产只用默认 `_https_get`。
     - **S6 动态导入登记**：`app/` 内出现 `__import__`、`importlib`（任意子模块）、内置 `exec`/`eval`/`compile`（AST 中的 Name 调用；`re.compile` 等属性调用不算）即红（41e517a 上 app/ 无此类用法）；`probes/`、`selfchecks/` 中现有的合法用法须显式登记在守卫常量中（文件:行，按 41e517a）：`probes/p10_stability.py:4`（`os`）、`probes/p11_replay.py:49`（`requests`，用于**屏蔽**网络）、`probes/run_all.py:25/59`（按模块名加载 p01–p13）、`probes/run_all.py:240`（`re`）；selfchecks 的 `importlib.util` 加载（tb49/tb49b/tb49c/tb81_safety）与 `__import__` 字面量（tb71/tb72 的 DSL 拒绝样例、t_tb116 两处）为测试代码，登记但不报红。登记外新增即红。S6 只是**登记**，不判断动态目标——那属①b。
   - **①b 运行时层（A1r；ingest 进程内，T-A91 选定方案 A 为主）**：新建 `app/ingest/netguard.py`，在 `app/workers/ingest.py` 的 `main()` **第一行**（`legacy_licence_present()` 之前、导入 `app.config`/sqlalchemy 连接之前）调用 `netguard.install()`，用 `sys.addaudithook` 安装一次（重复调用为 no-op；钩子不可卸载）。钩子的状态（域名集合、放行窗口、已批准 IP）只保存在 `install()` 的闭包里，不设模块级可写全局。判定规则：
     - `socket.getaddrinfo` / `socket.gethostbyname(_ex)`：主机名（去尾点、小写、IDNA 解码后）等于 `mairuiapi.com` 或以 `.mairuiapi.com` 结尾 → 仅当**当前线程**处于 egress 放行窗口时允许，否则拒绝。
     - `socket.connect` / `socket.connect_ex`（`socket.create_connection`、http.client、urllib3、requests、httpx 都经过它）：`AF_UNIX`、回环、RFC1918/ULA 私网地址（compose 内 postgres/redis）直接允许；**公网地址一律默认拒绝**，除非当前线程处于放行窗口且该 IP 是本窗口内由 egress 解析麦蕊域名得到、并已登记进窗口的地址。这样 IP 字面量直连、拆串域名解析后直连都被拒。
     - **（T-A92 补）** 同一规则适用于 `socket.sendto` / `socket.sendmsg` 中带目的地址的调用（UDP、TCP Fast Open 不经 connect）。`connect`/`sendto` 的地址若不是 IP 字面量（主机名，由 C 层自行解析、**不**触发 `socket.getaddrinfo` 审计事件）→ 一律拒绝（窗口内亦然；egress 只按 IP 建连，redis/http.client 经 `create_connection` 先解析再按 IP 连接，不受影响）。T-A92 实测 ab7ec5b：`s.connect(("<解析到公网的任意主机名>", 443))` 越过钩子直达内核 connect。
     - `subprocess.Popen`、`os.system`、`os.exec`、`os.posix_spawn`、`os.spawn`、`os.fork`（及 `os.forkpty`）：ingest 进程安装钩子后一律拒绝（ingest 无合法子进程需求，41e517a 上 `app/ingest`、`app/workers/ingest.py` 无 subprocess 调用）。
     - `ctypes.dlopen`：安装后默认拒绝（psycopg 为 `[binary]` C 扩展，不经 ctypes）；如后端实测有合法加载，须在 netguard 中按库名穷举登记并经 R19 复核。
     - **（T-A92 补）** `install()` 在 `sys.addaudithook` 之前先 `import ctypes`（让 `pythonapi` 的 `dlopen(None)` 在钩子前完成）；安装后 `ctypes.dlopen` **含 `None`** 一律拒绝（`CDLL(None)` 可取到已加载 libc 的 `connect`）；`ctypes.dlsym` 只放行 `Py`/`_Py` 前缀符号（挡 `pythonapi.connect` 一类）。T-A92 实测 ab7ec5b：`ctypes.CDLL(None).connect` 可取得。
     - **放行窗口**：只有 egress 能开，形式为 `with _egress_window(lease):`，只包住第⑦步 transport 调用；窗口绑定 `threading.get_ident()` 与 lease 的签发线程，进入时再核一次 lease（②），退出（含异常）即关闭并清空已批准 IP。`_https_get` 在窗口内先自行 `getaddrinfo(HOST)` 并把结果登记进窗口，再按 IP 建连（SNI/Host 仍用域名）。
     - **（T-A92 补）窗口不得默认放行**：`egress_window(lease, validate)` 的 `validate` 为必填，缺失或返回假即 `EgressBlocked`，不设 `lambda: True` 一类默认值；`register_resolved_ip` 只在本线程已开窗口时生效。T-A92 实测 ab7ec5b：`egress_window(None)` 无核验即开窗，再登记任意公网 IP 即可连接。
     - **拒绝**：钩子抛 `EgressBlocked(RuntimeError)`（新异常类，定义在 netguard，不属于 §7.11.5③ 的 `EgressDenied` code 集合）。同时写一行审计日志（logger `app.ingest.netguard`，WARNING，字段只有：事件名、目标类别 `mairui_dns`/`public_ip`/`hostname`/`subprocess`/`ctypes`/`lease`（T-A93：`hostname` 为非 IP 字面量的 connect/sendto/sendmsg，`lease` 为开窗核验不过；类别集合封闭，新增须改本条）、线程是否持窗口；**不写** URL、路径、证书、完整 IP 或调用栈原文），并计数到心跳的 `netguard_blocks`（可选，键名由后端定）。拒绝不写 HALT（不是上游限流），但调用方按 transport 失败处理（`core.complete(NETWORK)`，本批失败）。
     - **测试方式**：钩子不可卸载，所以 A1r 每个用例在**子进程**（`python -c`，或 `-X importtime` 无关）里先 `netguard.install()` 再执行绕过写法；整套在 `unshare -n` 无网命名空间 + conftest 屏蔽 DNS 下运行。被拦 ⇒ 子进程看到 `EgressBlocked`；被放行 ⇒ 看到 `gaierror`/`OSError`（无网），以此区分，**全程不可能真实连到麦蕊**。性能：钩子对每个审计事件都会调用，本机实测空钩子约 0.16µs/事件，判定只对上述事件做字符串/IP 比较，可忽略。
     - **（T-A92 澄清）测试安全网不得遮蔽钩子**：子进程中的防误连措施**不得**在 Python 层替换 `socket.getaddrinfo`、`socket.socket.connect` 等函数（替换后 C 层审计事件不再触发，测到的是测试自己的拦截）；改为在 `netguard.install()` **之后**再 `sys.addaudithook` 追加测试钩子（审计钩子按注册顺序执行，产品钩子先判，放行后才轮到测试钩子抛 OSError），或用 `unshare -n` / `--network none`。正向窗口用例必须经 `_https_get` 的解析登记或显式 `register_resolved_ip` 后再连，并传入 `validate`。
   - **①c 静态层与运行时层都不负责（明确排除；A1r 只覆盖其中可由钩子拦截的部分）**：
     - 静态层**不负责**：`importlib.import_module`/`__import__`/`getattr`/`vars()`/`globals()` 取名、`exec`/`eval` 构造代码（app/ 内只由 S6 登记报红，目标不判断）、拼接或拆开的域名字符串、`sys.modules` 反射、pickle/codecs 等间接执行、C 扩展、`ctypes`、子进程（`subprocess` 起 curl/wget/python）、socket 直连 IP 字面量、第三方库内部发起的连接。这些由①b 在运行时拦截，A1r 逐项给出反例。
     - 运行时层**也拦不住**（残余，归 R19，由评审与威胁模型说明兜底）：C 扩展或已加载的共享库直接调用 libc `connect`/`getaddrinfo`（不触发 Python 审计事件）；安装钩子之前已经建立的连接或已加载的扩展（故必须在 `main()` 第一行安装）；钩子闭包被同进程代码通过 `gc`/`__closure__` 篡改；ingest 之外的进程（worker、api、用户电脑上的 probes）。容器间纵深防御见①b 之外的方案 B（运维，plan §T-A87 第 6 节）。
2. **lease（不可伪造；T-A91 修订 M-a）**：`single_egress(engine) -> ContextManager[EgressLease | None]`。它用一条独立会话执行 `pg_try_advisory_lock(hashtext('ingest:single-egress'))`，拿不到就 yield None（调用方返回 `busy`）。退出时解锁。
   - `EgressLease` **只能**由 `single_egress` 签发。**核验不得只看「在不在注册表里」或对象身份**（T-A90 M-a：往 `_ISSUED_LEASES`/`_LEASE_LOCK_CONN` 塞假项即可放行）。T-A91 要求：
     - 签发方持有进程内随机密钥（`secrets.token_bytes(32)`，进程启动时生成，只保存在签发/核验函数共享的闭包里，不落盘、不出现在模块级名字、不进日志）。lease 携带 `nonce`、`thread_id`（签发线程 `threading.get_ident()`）、`lock_pid`（锁会话的 `pg_backend_pid()`）和 `mac = HMAC-SHA256(key, nonce‖thread_id‖lock_pid)`。
     - `mairui_get` 核验全部满足才放行：① mac 用 `hmac.compare_digest` 校验通过；② 当前线程 == `thread_id`（**lease 绑定线程**，跨线程复用即拒）；③ 签发方内部记录中该 nonce 仍未释放；④ 在锁会话上查询 `pg_locks`（`locktype='advisory' AND pid=pg_backend_pid() AND granted`，objid 对应 `hashtext('ingest:single-egress')`），确认锁仍由本会话持有；该查询受④的同一 3s 预算约束，超时按不通过处理。任一不通过 → `single_egress_not_held`（沿用既有 5 个 code，不新增）。
     - **（T-A92 补）** ④ 的 `pg_locks` 查询在锁会话上以短事务执行：先 `SET LOCAL statement_timeout = 剩余预算`，查完立即提交/回滚，锁会话在 transport 期间不得处于 idle in transaction（§4「不在任何事务内发 HTTP」）。
     - **（T-A93 澄清）预算边界**：④ 的 3s 上限截止于准入决定（⑤ `next_call` 返回）。⑦ 进入窗口时的 lease 再核**不**沿用准入 deadline，用独立的 0.5s 预算（`SET LOCAL statement_timeout = 500ms`，超时或查询失败按不通过处理）；否则准入合法地在 2.6–2.8s 完成时，再核因剩余预算 <0.2s 必然失败，合法调用被误拒（T-A93 在 9435ad0 实测）。
     - 公开字段可以保留 `held: bool`，但**不得**仅凭 `held` 放行。
   - **威胁模型边界（不承诺达不到的保证）**：本条防的是仓库内代码（包括误写、偷懒的旁路）自造、复制、跨线程复用或往注册表塞项来绕过 single-egress。**同进程任意代码执行**（读取闭包密钥、`gc` 遍历对象、ctypes 改内存、替换 egress 函数）属于威胁模型之外，HMAC 只抬高门槛，不构成对它的保证；这一类由①b 运行时层（网络/子进程拦截）与代码评审兜底（R18/R19）。
3. **出口函数**：`mairui_get(*, lease: EgressLease, core: IngestCore | None, engine: Engine, licence_id: UUID, user_id: UUID, path: str, secret: str, priority: Priority, clock: Callable[[], datetime], stop: Path, halt: Path, transport: Callable[[str, str], tuple[int, object]] = _https_get) -> EgressResult`。
   - `EgressResult(status: int, body: object, signal: Signal, transitions: list[Transition])`
   - 拒绝时抛 `EgressDenied(code)`。`code` 只能取以下固定值：`halt_present`、`single_egress_not_held`、`core_unavailable`、`licence_unavailable`、`core_denied`，并且不含 URL、证书或上游原文。INVALID / 102 后的拒绝用 `licence_unavailable`（证书已不可用，与「非 active」同码，不新增 code）。
   - transport 失败抛 `DailyHaltError("transport_or_response_failed_no_retry")`，抛出前已经 `core.complete(NETWORK)`。
4. **调用顺序（不得调换；T-A89 修订，T-A91 补 M-b/M-c）**：① STOP/HALT 存在则 `halt_present`；② 核验 lease（见上）不通过则 `single_egress_not_held`；③ core 为 None 则 `core_unavailable`；④ **证书准入（以库为准，B-1(a)）**：
   - **准入时限（M-b，T-A91）**：从进入 `mairui_get` 到给出拒绝或放行（即第⑦步 transport 之前），**墙钟上限 ≤3s，有没有 pending 都一样**。实现要求：
     - 准入只用**一条连接、一个事务、一轮取锁**：`with engine.connect() as conn, conn.begin():` 内依次 `SET LOCAL` 超时 → `acquire_ip_limit_lock`（阻塞式加 `lock_timeout`，保留 L-7 公平性）→ 读 `user_data_licence_status`（并入同一事务，不再另开连接）→ `ipl.rehydrate` 读事件 →（有 pending 时）`with conn.begin_nested():` 在 **SAVEPOINT** 内 `flush_pending_escalation` → 外层提交。SAVEPOINT 失败只回滚到保存点：pending 保留、本次按已升级拒绝 `core_denied`；**只有外层事务提交成功后才清 pending**（L-6/L9 语义不变）。禁止在准入路径上再调用独立的 `_try_flush_pending`（那会形成第二轮取锁，T-A90 实测 3.71s）；`tick` 路径仍可用独立 `_try_flush_pending`。
     - **超时对齐**：准入以 `deadline = t0 + 2.8s`（留 0.2s 余量）驱动。ingest profile 的 `connect_timeout` 由 3 改为 **2**（libpq 最小有效值 2s）；建连后计算剩余 `r = deadline − now`，`r < 0.2s` 直接拒绝 `core_denied`、不发语句；否则 `SET LOCAL lock_timeout = min(1000ms, r)`、`SET LOCAL statement_timeout = r`（向下取整到 ms）。引擎级 `options` 里的 `statement_timeout=5000`、`lock_timeout=2000` 只作 tick/批处理的兜底，**准入路径必须用 `SET LOCAL` 覆盖**（T-A90 低级问题：rehydrate 的 `statement_timeout` 仍是 5s，会把上限撑到 5s 以上）。② 里的 `pg_locks` 核验也计入同一 deadline。最坏情况：建连 2s + 锁/语句 ≤0.8s ≈ 2.8s，加调度抖动仍 ≤3s。
     - 任一超时或库错误 → 记为已升级（fail-closed），拒绝 `core_denied`，transport 0 次。
     - **无法保证上限的残余（归 R15）**：库进程被冻结但内核照常 ACK（`statement_timeout` 在服务端执行，`tcp_user_timeout`/keepalive 都不触发），语句中途挂起时客户端会一直阻塞；DNS 解析 PG 主机名卡住（解析阶段可能不受 libpq `connect_timeout` 约束）；Python 进程自身被 GC/调度长时间暂停。这些情况下上限不成立，但**准入未完成就不会放行**，不出现多发外呼，只表现为本批卡住；由 tick 心跳超时与健康检查告警。
   - 读库中的 `user_data_licence_status`。**证书状态以库为准**：只有库里为 active、未删除、且不在暂停期，才允许进入后续外呼。
   - 终态 / 暂停态集合：`INVALID`、`PAUSED_BY_ADMIN`、`EXPIRED`（以及契约既有的 `invalid` / `ip_limited` 等非 active 取值）。`core.upsert` 与 `core.rehydrate` **不得**把这些状态降回 active；若内存状态与库不一致，取更严的一方（任一为终态/暂停 → 按不可用处理）。
   - 上游返回 **102**，或本地判定进入 `INVALID` / `PAUSED_BY_ADMIN` / `EXPIRED`：状态变化必须**先写库，再处理后续调用**；写库成功后本调用照常 `core.complete`，以后每次拒绝 `licence_unavailable`。
   - **状态写库失败（M-c，T-A91）**：102 或终态的状态写库失败时，必须**同时写 HALT 标志**（`/run/aia/state/halt/` 下的停机标志，内容固定为 `licence_status_persist_failed`，O_EXCL、0600、fsync；已存在视为成功），内存标记 INVALID，并拒绝本调用 `core_denied`，transport 不再增加。
     - 同进程的下一次调用与重启后，HALT 都仍在（ingest 独占具名卷 `ingest_state`），第①步即 `halt_present`（T-A92 澄清：A26 的后续期望值即 `halt_present`，不是 `licence_unavailable`/`core_denied`），所以库里仍是 active 也不会再放行（T-A90 实测 41e517a 重启后第 2 次 transport 的缺口由此关闭）。
     - **HALT 也写失败**：写一行固定文案（`ingest 致命：证书状态与停机标志均无法持久化`，不含路径、证书、异常原文）到 stderr，随即 `os._exit(74)`（sysexits `EX_IOERR`）。不用 `sys.exit`/异常，因为 transport 外层有 `except BaseException`（L-c），异常可能被吞。退出码约定核对（41e517a）：`78`（EX_CONFIG）已用于启动拒绝（`MAIRUI_LICENCE`/`APP_MASTER_KEY`/Settings/engine 不可用，`workers/ingest.py:40`），`74` 未被占用，专用于「运行中安全状态无法持久化」，与启动拒绝区分。
     - 配套启动检查：`bootstrap_ingest_core` 在 engine 探测之后，对停机标志目录做一次可写探测（O_EXCL 创建 `.probe-<pid>` 再删除，不触碰任何 HALT 文件），不可写 → 退出码 78 拒绝启动。因此「HALT 不可写」的容器在 `restart: unless-stopped` 下只会反复 78，不会外呼。
     - 残余（R18）：库写入失败与 HALT 写入失败同时发生、且重启时两者都已恢复，库仍为 active、HALT 不存在 → 重启后最多再发 1 次外呼（上游会再回 102，此时按正常路径落库）。
     - 解除：沿用 `deploy/runbooks/ingest-halt.md`「解除停机标志（必须由用户本人确认）」——先人工核对库内证书状态（并按需由管理员或用户本人重新添加/启用证书），经用户本人确认后再删 HALT；egress、core、重启都不自动清除。
   - 证书一旦变为 `INVALID`，或本会话已收到 102 并完成落库：以后每一次 `mairui_get` 都必须拒绝 `licence_unavailable`，transport 0 次。**解除**：必须由管理员或用户本人重新添加 / 启用证书；不得因重启、user_reset、换同值证书、或内存 rehydrate 自动恢复。
   - 库行不存在、已删除或非 active → `licence_unavailable`。
   ⑤ `core.submit` 加 `core.next_call`，返回 None 或不是本次 Call 时 `core_denied`，并丢弃本次排队项；⑥ 再判一次 STOP/HALT；⑦ 在 `_egress_window(lease)` 内调 transport（超时 20s，不重试、不跟随跳转；窗口只包这一步，①b）；⑧ 若为 102 → 先按上款落库为 `INVALID` 再拒绝后续（写库失败按 M-c：同时写 HALT，HALT 也失败则退出码 74）；若为限流（`limited()` 或 classify 结果为 IP_LIMITED），先写 HALT 文件；⑨ `core.complete(d, signal, now)`，IP_LIMITED 时写 `ops.data_licence_events`。
5. **调用方义务**：调用时不得有未提交的事务；在 `upstream_halted` 检查（`eligible`）之后调用；限流时由调用方把 `upstream_halted` 写入 master_runs；TEMP 的创建和清理（R13）仍由调用方在 lease 内完成；不得自行构造 `EgressLease`，不得在 egress 外持有或转发 `_https_get` / `HOST`；不得把 lease 交给其他线程使用（T-A91）；生产代码不得向 `mairui_get` 传 `transport=`（S5）。
6. **优先级**：HALT 文件和库内 `upstream_halted` 高于 IngestCore 的任何状态。egress 和 core 都不清除这两者，user_reset、换证书、重启也不行。库内证书终态（`INVALID` 等）同样不被 upsert/rehydrate/重启自动清除。M-c 写入的 HALT（`licence_status_persist_failed`）与限流 HALT 同级，同样只能按 runbook 由用户本人确认后解除。netguard 拒绝（①b）不写 HALT、不改证书状态，只让本次外呼失败。
7. **ingest 启动（L-1/L-2）**：`engine_for(url, profile="ingest")` 使用 NullPool，并设 `connect_timeout=2`（T-A91 由 3 改 2，配合④的 3s 准入上限；libpq 最小有效值 2）、keepalives、`tcp_user_timeout=5000`、`statement_timeout=5000`、`lock_timeout=2000`（后两者是 tick/批处理兜底，准入路径按④用 `SET LOCAL` 覆盖）。`main()` 第一行先 `netguard.install()`（①b）。拿不到 DATABASE_URL、URL 格式错、Settings 校验失败、连接探测失败、停机标志目录不可写（④ M-c）都以退出码 78 拒绝启动，stderr 只有固定文案加异常类型名，不出现 traceback 和口令。

## 8. SSE `GET /stream` 🔒
- `text/event-stream`；每 15 秒发一次 `heartbeat`；支持 `Last-Event-ID` 续传，服务端保留最近 10 分钟的事件；断线时客户端退回到轮询 `/notifications/unread-count`，终端与首页改为每 ≥ 15 秒带 `If-None-Match` 轮询 `/terminal`、`/today`。
- 每个事件：`id: <单调递增字符串>`，`event: <type>`，`data: <JSON>`。

| event | data | 说明 |
|---|---|---|
| `heartbeat` | `{at}` | |
| `quote` | `{items: [{security_code, name, price, change_pct, amount, t}], data_as_of: string(datetime)}` | 只推送用户自选或持仓的证券，来自缓存。**A-12 终裁规定**：无 quote 变化不发布新的 quote 事件；发布时 `items` 必须含至少一条有可信行情时点的变化项，`data_as_of` 必须出现且非空，取本块实际行情时点最早值；不得用发布/心跳时刻填充。生产发布方须落实此前提，通用 transport 当前不代做 quote 校验；合法历史事件仍按原续传规则重放 |
| `signal` | `SignalEvent`（§5.1，`kind: signal_kind`） | 盘中规则事件 |
| `candidate_signal` | `{id, security_code, name, state, proposed_action, strategy_key, strategy_name}` | ⚖ 候选信号新建或状态变化 |
| `reason_released` | `{reason_id, signal_id, code, released_at}` | ⚖ 原因已解除，系统正在重新检查 |
| `plan_draft_ready` | `{plan_draft_id, signal_ids, security_code, name, valid_until}` | ⚖ 生成了新的草案，等待确认 |
| `plan_triggered` | `{plan_id, condition, at}` | 提示"您的计划条件已满足"，**不下单** |
| `suggestion` | `{id, security_code, name, supersedes_id, summary: SuggestionSummary}` | ⚖ 终端用 `summary` 直接更新行 |
| `notification` | `Notification`（§5.1） | |
| `report` | `{date}` | 日报已生成 |
| `data_status` | `{dataset, data_status, data_as_of}` | 数据变旧或恢复（例如采集暂停） |
| `reset` | `{reason: "expired" \| "unknown", latest_event_id: string \| null}` | 续传点超窗或无法识别，客户端须全量重读（T-A31，§7.11.4） |
| `data_licence` | `{status: data_licence_status, verification_id: uuid \| null, last_error_code: string \| null, at: datetime}` | 本人证书状态变化或验证完成（v0.2.6；不含证书值） |

研究候选（v0.2.9 T-A11，§7.7A）没有 SSE 事件。

---

## 9. 契约测试要点（T-T17 等）
- 所有非 `/admin/*` 的响应示例都能用 OpenAPI schema 校验通过（`/admin/*` 不在 `openapi.json` 中，按本契约 §5.1、§7.9 的结构逐接口断言，v0.2.8）；所有统计字段都带 `n`，缺少即失败。
- 候选信号和建议的响应中，P1 要求的四个数组都非空，`model_refs[*].role == "auxiliary"`。
- 不存在任何 `POST /candidate-signals/{id}/convert` 一类的接口；只有 `/plan-drafts/{id}/confirm` 能创建 `origin=plan_draft` 的计划。
- 未登录、普通用户、非 `approved` 账号访问任何 `/admin/*`（含 `/admin/evaluation/*`、不存在的子路径、用错方法、缺 CSRF）一律 404，响应体与不存在的普通路径逐字节相同（`request_id` 除外），不带 `Allow` 头；全文不得再出现“`/admin/*` 返回 403”。
- 任何响应、日志和错误信息中都不出现 licence、原始股东代码或资金账号（用虚构 fixture 做扫描）。
- 行情类接口在采集服务暂停时返回 `data_status:"stale"`，而不是 5xx，也不会触发上游调用。
- **命名（v0.2）**：OpenAPI schema 与所有示例中不得出现字段名 `evidence_id`、`pass`（规则结果）、平铺的 `stop_loss`/`take_profit`（必须在 `stops` 内）；所有 `score` 字段为 0–100 整数或 `null`；凡含 `security_code` 的对象都有 `name`。
- `Suggestion.dimension_matrix` 与 `strategies[].dimension_views` 一致（单元格的 `score`、`view`、`key_evidence_ids` 可由后者推出）；`executability.status` 与候选信号的原因状态一致。
- **导入提示码**：§4.1 与 plan.md 3.5A-1 的表逐行一致；共 46 个、21 error / 25 warning；夹具 `expected.json`（测试维护，唯一期望来源）中出现的 code 都在 §4.1 内。
- `/terminal`、`/today`：查询次数与行数无关（无 N+1）；`rows ≤ 300`、各列表 ≤ 50；带 `If-None-Match` 且未变时返回 304。
- **前端依赖**：`package.json` 与 lockfile 中不得出现 `ag-grid-enterprise` 或 `@ag-grid-enterprise/*`（终端表格只用 AG Grid Community，MIT）；CI 失败即阻断合并。
- 密钥与敏感信息扫描规则见 plan.md 7.4A（S1–S9）。
- 命名空间：`error_codes`、`reason_codes`、`import_codes` 三者没有重名；码类取值全部匹配 `^[A-Z][A-Z0-9_]*$`，其他枚举取值匹配 `^[a-z0-9][a-z0-9_]*$`。
- `/meta/enums`：`enums` 的键集合与第 3 节表名一致，每个取值与本文逐项一致（从 markdown 解析做快照对比）。
- 健康检查：停 db 或 redis → `/health/ready` 返回 503、`status: "down"`；只停 ingest 心跳 → 200、`degraded`、`ingest: "stale"`；写入 `ingest:paused` → `paused` 优先；`/health/live` 在依赖全停时仍 200。
- 405：`DELETE /api/v1/health` → `405 METHOD_NOT_ALLOWED` + `Allow` 头；非管理员（含未登录）对 `/admin/*` 用错方法 → 404，无 `Allow` 头。
- **v0.2.3**：
  - `/horizon-assessments`：每条 `reasons[].evidence_ids` 都能在同一响应的 `evidence[]` 中找到；`classifier_version` 匹配语义化版本正则；`inputs_missing` 非 null、去重、升序、每项以 `f.` 开头；每个分数 ≤ 对应周期 `caps[].cap` 的最小值；~~novice 夹具 `caps` 含 `kind: "requires"` 的 SH0C/IT0C~~（v0.2.5/v0.2.6 作废：画像类规则只进 `hints[]`，`kind` 只有 `gate`、`data_missing`，见 v0.2.6 验收）；`SH0C`/`IT0C` 不出现在 `/meta/enums.reason_codes`（#23）。
  - 认证（#24–#27）：用户名 3 位 → 400；~~consents 两项~~（v0.2.5 作废）；改密后旧 `sid` 401、响应带新 `sid`；超过绝对过期的会话 401；邀请码各类无效情形返回完全相同的响应体。
  - 纯离场策略：未持有的证券不出现 H-01 类结论；持有时其 `state`/`action` 只在 §5.2 允许的集合内；其单元格 `rules_total == 0`、`score == null`、`exit_hits ≤ exit_total`。
  - `consensus.status` 与行级 `divergent` 按 §5.2 的定义可由 `strategies[]` 重算得出。
  - OpenAPI schema 与所有响应示例中不得出现 provider 值 `local`；`Evidence.provider` ∈ `data_provider`；`cash_available` 只出现在 `/terminal.account`。
  - 所有 `RuleRef.dimension` 非空。
  - `POST /notifications/{id}/read`、`/notifications/read-all` 返回 204 且无响应体。
- **v0.2.6**：
  - 任何响应（含 `/me/data-licence`、`/admin/data-licences`、错误体、SSE、通知）、日志与 `ops.ingest_request_log` 中都找不到测试证书字符串及其任意 ≥ 4 位的子串（测试证书为运行时生成的虚构值）；`DataLicenceStatus` 无 `licence`、`masked`、`last4` 类键。
  - `api` 进程环境中没有 `DATA_LICENCE_SEAL_PRIVATE_KEYS`；仅凭 `api` 的配置无法解密库中密文；`api` 数据库角色 SELECT `ciphertext` 被拒。
  - 两个用户 PUT 同一证书 → 第二个 `409 DATA_LICENCE_IN_USE`；第一个 DELETE 后第二个可设置。PUT 含 `/`、`?`、空白的值 → 400，消息不含输入值。
  - 回放模式：上游 102 → `invalid`，之后该证书外呼次数为 0，其他证书不受影响；101 → `quota_exceeded`，`paused_until` 为次日 00:01（北京时间）；103 → `ip_limited`，暂停 120 秒，1 小时内第 3 次 → 暂停 1 小时并产生 `data_licence` 通知。
  - **草案（T-A75，风控，需另一个模型复核）**：上条“1 小时内第 3 次”按**用户**累计，不按证书行 id；DELETE 后再 PUT（同一或不同证书）、点“测试”、`ingest` 重启都不清零；计数与升级暂停以 `ops.data_licence_events` 中 `actor=ingest` 的 `ip_limited` 事件及升级标记（`event=paused`、`actor=ingest`、`to_status=ip_limited`）为准，按数据库 UTC 时间计算；升级暂停期内该用户任何证书都不外呼、不验证（#13“换成不同证书照常验证”顺延到暂停结束）；记录写不进库时按已升级处理。方案见 `docs/reviews/T-A75-ratelimit-escalation-fix.md`
  - 用户 B 证书 `invalid` 时：B 的行情接口 `data_status ∈ {stale, unavailable}` 且 `gaps` 含 `data_licence_unavailable`；`manual_refresh` → `409 DATA_LICENCE_UNAVAILABLE`；`ingest` 没有用 A 或管理员的证书为 B 发出任何请求。
  - `per_licence` 模式下，A 读到的所有行情行的 `source_licence_id` 都是 A 的证书。
  - 公平：A 积压 10,000 个 P1、B 有 1 个 P0 → B 的 P0 在下一个调度轮发出；A、B 各有 P1 时交替发出；每证书每分钟调用数不超过其上限。
  - 分类器：无底仓时 `intraday_t` 分数为 0 且 `caps` 中没有 `IT0`；同时 `experience=novice` → `hints` 仍含 `IT0C`；`caps[].kind` 只出现 `gate`、`data_missing`；ST 股 → `caps` 含 `{kind: "gate", rule_id: "HG4", cap: 59}`；财报不足 12 期 → 含 `{kind: "data_missing", rule_id: "LG0", cap: 59}`。
  - 画像不匹配时建议卡的 `confidence` 与画像匹配时相同；画像相关字段未填写时 `warnings` 中没有画像提示。
  - 创建 `risk_level: high` 模板的实例不需要任何确认字段 → 201。
  - `/meta/enums.version == "v0.2.6"`（v0.2.7 起为 `"v0.2.7"`，v0.2.8 起为 `"v0.2.8"`，见 v0.2.8 验收 1），含 `data_licence_status`、`data_licence_tier`；`error_codes` 含三个 `DATA_LICENCE_*`。
- **v0.2.5**：
  - `/meta/consent-docs`、`/legal/terms`、`POST /me/consents`、`/me/risk-assessment*` → 404；`/meta/enums` 不含 `consent_key`、`legal_doc_key`、`consent_presentation`、`assessment_status`，`reason_codes` 为 22 个且不含 `PROFILE_OR_CONSENT_MISSING`，`error_codes` 不含 `CONSENT_REQUIRED`、`STRATEGY_FIT_ACK_REQUIRED`。
  - 注册带或不带 `agreements` 都 201，库中不产生同意记录；`Me` 无 `consents`、`risk_assessment` 键。
  - 无画像、或画像不满足任何条件时，⚖ 接口、`POST /imports`、`POST /trades` 均不返回 403。
  - 分类器 1.2.0：画像全空时 `short`/`intraday_t` 分数与“画像全满足”时相比只差加分项（不出现 59 封顶）、`hints=[]`；`experience=novice` 时 `hints` 含 `SH0C`、`IT0C`，`caps` 不含二者，`suitable` 与 novice 前相同（其他条件不变）；`risk_tolerance=2` → `hints` 含 `SH0`；`effort=low` → 含 `SH0B`、`IT0B`。~~`IT0`（无底仓）仍为 `caps` 中 `kind=requires`~~（v0.2.6 作废：`IT0` 判 0 分不进 `caps`，见 v0.2.6）。
  - `POST /strategy-instances` 对不适合的周期 → 201 且 `warnings` 非空；请求带 `fit_ack` 被忽略。
- **v0.2.4**：
  - `apply_note` 201 字 → 400。（`agreements` 相关用例 v0.2.5 作废）
  - CSRF：头与 Cookie 一致但与会话内令牌不符 → 403 `CSRF_FAILED`。
  - §4.1“处理选项”表中每个码的 `resolution_choices` 与实际返回一致；`force_import` 不带理由 → 400；`POST /trades/{id}/void` 两次 → 第二次 409。

- **v0.2.7 验收**（T-A08）：
  1. `/meta/enums.version == "v0.2.7"`（v0.2.8 起为 `"v0.2.8"`）；`enums` 的键集合等于 §3 表名集合（包括新增的 18 个枚举与 `data_provider.exchange`）。
  2. `/strategies` 每个元素都有 `risk_level ∈ card_risk_level`；`?risk_level=high` 只返回 high；未关联卡片的模板为 `normal`；派生版本与母版本一致。
  3. `GET /strategy-instances`：默认不含 `archived`；`?status=archived` 只返回 archived；各 `order` 下翻页不重复、不遗漏（插入并发数据后再翻页）；改变筛选后沿用旧游标 → `400 INVALID_CURSOR`。
  4. 状态机：对 4 种状态 × 4 种操作的 16 种组合，结果全部符合 §6.0A（200 转换 / 200 幂等 / 409 + `allowed` 正确）；幂等的空操作不写事件、不改 `updated_at`；`origin=system` 的实例 archive → 409 且 `allowed` 不含 `archived`；对同一实例并发 10 次 pause，只产生 1 条 `paused` 事件。
  5. 系统暂停 → 用户 resume：`paused_by`、`pause_reason_code`、`paused_until` 全部清空，事件 `actor="user"`，`detail.released_reason_code="LOSS_STREAK_PAUSE"`；用户暂停的实例到期后不会被系统恢复。
  6. 搜索：夹具中 `600000`、`600000.SH`、`SH600000`、`示例银行`、`SLYH`（拼音首字母）、曾用名、北交所旧代码各自命中，`match_kind` 正确；排序符合层级与平手规则（固定夹具做快照测试）；`limit=51` → 400；默认不含 `delisted` 和 `index`。
  7. **pg_trgm 中文可用**：迁移中执行 `CREATE EXTENSION IF NOT EXISTS pg_trgm`；部署检查 `SELECT show_trgm('示例银行')` 返回非空数组。数据库为 C locale 而返回空数组时，模糊匹配回退为 `ILIKE '%q%'`，并在启动日志告警。
  8. `/securities?q=` 别名返回 `[{security_code, name}]`、最多 20 条，前 20 条与 `/securities/search` 的结果一致。
  9. 个股读接口：本人证书不可用时返回 `200`，`data_status ∈ {stale, unavailable, partial}`，带 `data_licence_unavailable` gap，**从不返回** 409；用户 A 的证书取到的数据不会出现在用户 B 的响应里（两个用户、两张证书的夹具，证书值运行时生成）；在 Q2 / T-A04 确认前，公开主数据的任何字段都不来自他人（含管理员）证书。
  10. `SecurityProfile`：证书不可用时公开主数据字段（v0.2.7 #19 所列）仍然齐全，`data_status="partial"`；响应中没有 `full_name`；北交所旧代码 → `404` 且 `details.superseded_by` 为新代码。
  11. 财务：`limit=41` → 400；`as_of` 早于某期的 `available_from` 时不返回该期；指数返回空 `items` + `no_source`。
  12. 公告：任何 `url` 都是 https 且主机在白名单内；响应中没有正文或摘要字段；`disclaimer` 与固定文案逐字一致。
  13. 周 K：用固定日线夹具（含节假日周、整周停牌周、`sf=1` 占位行、盘中当日 bar）验证 `t`、OHLC、`pre_close`、`is_final`、整周停牌不出 bar；`qfq` 周 K 的 `close` 等于同一请求下 `qfq` 日 K 在 `t` 日的 `close`。
  14. `/today`：新增的 4 个顶层字段都存在；`alerts` 不含 `origin=plan_condition`；`alerts` 和 `plan_triggers` 的每个 `evidence_ids` 都能在 `evidence[]` 中找到；三块的排序符合 §7.3 补充；`data_gaps.more` 恒为 false；每条 `risk_flags` 的 `risk_event_id` 都能在 `/risk-controls/events?status=active` 中找到。
  15. 禁用词：`alerts[].title`、`plan_triggers[].condition_text` 的服务端拼接部分、`data_gaps[].message`、`SectorFlow`、`Announcement.disclaimer` 都通过合规禁用词校验。
- **v0.2.8 验收**（T-A09）：
  1. `/meta/enums.version == "v0.2.8"`（v0.2.9 起为 `"v0.2.9"`，见 v0.2.9 验收 1）；`security_type` 含 `etf`，`gap_reason` 含 `not_applicable`；前端 `CONTRACT_VERSION` 同步。
  2. `/admin/ingest/status`：没有 `licence` 键，有 `licences` 与 `licences_truncated`；设置两张测试证书（A `active`、B `quota_exceeded`）时各一行，键集合等于 `IngestLicenceStatus`，B 排在 A 前；`not_set` 用户不出现；`queue_depth`、`calls_today` 与 `/admin/data-licences` 同一证书的值一致。
  3. 证书不泄露：`/admin/ingest/status`、`/admin/data-licences` 的响应全文不含任一测试证书值的长度 ≥ 4 的子串，也不含密文或 HMAC（测试证书值只在测试进程内随机生成，不写入仓库）。
  4. `/admin/data-licences` 元素含 `licence_id`，与 `/admin/ingest/status` 中同一证书的 `licence_id` 相等；未设置证书的用户为 `null`。
  5. `openapi.json` 的 `paths` 中没有任何 `/admin` 前缀的路径；§7.9 的每个管理端接口都有按本契约结构断言的契约测试。
  6. ETF 搜索：不传 `types` 时按 ETF 代码或简称能搜到，`type="etf"`、`board=null`；`types=stock,cdr` 时搜不到；同层排序 `stock` > `cdr` > `etf` > `index`；可转债代码搜不到。
  7. ETF 资料与数据：`/securities/{etf}` 的 `board`、`risk_flag`、股本、`industry` 为 `null`，`concepts=[]`，且不因此出现 gap；financials、fund-flows、factors、announcements 均为 `200`、空 `items`、`data_status="unavailable"`、`gaps[0].reason="not_applicable"`；指数的 financials 仍为 `no_source`。
  8. ETF 行情与持仓：`/quotes`、`/bars`、`/terminal` 对 ETF 与股票同口径，价格为 3 位小数字符串；含 ETF 成交的交割单可导入并重建出 ETF 持仓；可转债行给出 `IMPORT_UNKNOWN_SECURITY`。
  9. ETF 策略：`POST /strategy-instances` 以 `scope="security"` + ETF → `422 INSTANCE_SCOPE_INVALID`，`details` 含 `security_type="etf"`、`issue="security_type_not_supported"`；`scope="account"` 的实例在账户含 ETF 持仓时正常 `201`，运行后不对 ETF 产生候选信号或建议；分类器对 ETF 四个周期都是 0 分且不产生 `proposed` 实例；H-01 不挂到 ETF 持仓。`scope="security"` + 不在证券主数据中的代码 → `422 INSTANCE_SCOPE_INVALID`，`details` 为 `{scope, security_code, issue:"unknown_security"}`（v0.2.8 补充）。
  10. 注册蜜罐（在 `registration_mode=open` 的测试环境中）：`website` 非空 → `201`，响应键集合与正常注册相同，`users` 无新增、邀请码未消耗，审计有一条 `auth.register_honeypot` 且 `detail` 中没有用户名、口令、申请说明；`form_started_at` 为 1 秒前或未来时间 → 同样命中；5 秒前或不传 → 正常创建；带这两个字段不报 400，带其他未知字段仍报 400；命中的请求计入 IP 限速（同一 IP 第 6 次 → `429`）；`closed` 模式下命中也返回 `503 REGISTRATION_CLOSED`。
  11. 暂停期 PUT：管理员 pause 后，用户 PUT 新证书 → `202` 且 `status="paused_by_admin"`，没有验证任务入队，`ingest` 不用该证书发出任何请求；DELETE 后 GET 仍为 `paused_by_admin`，再 PUT 仍为 `paused_by_admin`；`POST /me/data-licence/test` → `409 DATA_LICENCE_UNAVAILABLE{status:"paused_by_admin"}`；管理员 resume 后为 `pending_verification` 并投递验证；暂停期间删除证书后 resume → `not_set`。重复暂停（v0.2.8 补充）：已暂停时再次 pause → `204`；暂停后用户删除证书，再次 pause → `204`（不是 409），GET 仍为 `paused_by_admin`；未暂停且未设置证书时 pause → `409 DATA_LICENCE_NOT_SET`。
  12. 重复 PUT 同一证书：`quota_exceeded`、`ip_limited` 状态下 → `202`，状态与 `paused_until` 不变，没有验证任务入队；`active` 但熔断中（`paused_until` 未到）→ `paused_until` 保留；`invalid` 状态下 → `pending_verification` 并验证。删除后重新提交（v0.2.8 补充，T-B04a-x）：`quota_exceeded`、`ip_limited`、`active` 且 `paused_until` 未到期三种情况下，DELETE 后在 `paused_until` 到期前 PUT 同一证书 → `202`，`status` 与 `paused_until` 恢复为删除前的值，没有验证任务入队；PUT 不同证书 → `pending_verification` 并验证；`paused_until` 到期后 PUT 同一证书 → `pending_verification` 并验证；库中和响应中都没有证书明文，响应中也没有指纹。
  13. 前端路由：访问 `/` 重定向到 `/today`。
  14. 证书设置开关（v0.2.8 补充）：`DATA_LICENCE_SETTINGS_ENABLED=false` 时，`PUT`、`PATCH /me/data-licence` 和 `POST /me/data-licence/test` → `503 MAINTENANCE`，库中没有写入、没有验证任务入队；`GET` → `200`，`DELETE` → `204`；`APP_ENV=production` 且未设置该变量时同样为关闭；前端收到该 503 时显示“设置暂未开放”。
- **v0.2.9 验收**（T-A10）：
  1. `/meta/enums.version == "v0.2.9"`；`enums` 的键集合等于 §3 表名集合（比 v0.2.8 多 4 个：T-A11 的 3 个见下方“v0.2.9 验收（T-A11）”第 1 条；`candidate_signal_event_cause` 取值与顺序为 `executability_check` `reason_released` `user` `expiry` `invalidation` `supersede`）；前端 `CONTRACT_VERSION` 同步。
  2. 可转债持仓：导入含可转债行的交割单（`import_as_is`）后，`/portfolio` 中该行 `security_type=null`、`estimated=true`、`market_value`/`pnl`/`pnl_pct` 为 `null`、`weight_pct` 等于成本估算值，顶层 `data_status="partial"`；有现价的股票与 ETF 行 `estimated=false` 且 `security_type` 非空（在主数据中但缺现价的行 `estimated=true`、`data_status="partial"`，v0.2.9 #31）；`/terminal` 同一持仓的 `holding` 字段一致；该行不产生候选信号、建议与风控止损事件。
  3. 候选信号事件：`/candidate-signals/{id}/events` 返回 `{items, next_cursor}`，按 `at desc, id desc`，翻页不重不漏；每个 `cause` 都在 `candidate_signal_event_cause` 内；确认草案后最新一条为 `{from:"drafted", to:"confirmed", cause:"user"}`；元素没有 `detail` 键。
  4. `NonExecutableReason` 列表与详情都有 `security_code`、`name`，与所属信号一致；不带 `status` 时只返回 `active`；`status=released` 只返回已解除；`status=all` 含 `active`、`released`、`obsolete`；带 `signal_ids=` 不带 `status` 时同样只返回 `active`。
  5. `BLOCKLISTED`、`USER_MUTED` 原因调用 `/release` → `409 REASON_NOT_MANUALLY_RELEASABLE`，原因保持 `active`；删除对应 `/restrictions` 后由系统重新检查并解除（`released_by="system"`）。`STRATEGY_CONFLICT` 的 `evidence` 中含对方信号 id。
  6. 跟踪统计：不传 `scope` 时为 `mine`；`scope=site` 的响应不含任何用户 id、用户名或个股持仓字段；`scope=other` → `400 VALIDATION_ERROR`。
  7. 多信号草案：同一证券、同一动作的两个信号 → `201`，`signal_ids` 两个都在；跨证券或动作不同 → `400 VALIDATION_ERROR{field:"signal_ids"}`；方向相反且带 `STRATEGY_CONFLICT` → `409 SIGNAL_NOT_EXECUTABLE`。
  8. 整手：科创板买入草案 `qty_range.min ≥ 200`、`lot=1`；科创板 `chosen_qty=150`（低于起买量）或主板 `chosen_qty=150`（不是 100 的整数倍）→ `400 VALIDATION_ERROR{field:"chosen_qty", issue:"lot_rule"}`，即使带 `deviation_ack=true`；主板 `chosen_qty=300` 在区间外且 `deviation_ack=true` → `201`；卖出全部可卖数量（含零股）→ `201`。
  9. 放弃草案：`POST /plan-drafts/{id}/discard` 请求体 `{}` → `200`、`status="discarded"`；请求体 `{"note": "示例"}` 同样成功，库中、审计和响应中都没有该备注；非 `pending` 草案 → `409 INVALID_STATE_TRANSITION`。
  10. 关闭注册（T-T23）：`registration_mode=closed` 时，正常请求体、非法 JSON、缺 `username`、`password` 为数字、带未知字段、命中蜜罐的请求体，一律 `503 REGISTRATION_CLOSED`，响应体相同，都不返回 400；`users` 无新增，不写蜜罐审计。
  11. 证书设置开关（T-T23）：`DATA_LICENCE_SETTINGS_ENABLED=false` 时，`PUT /me/data-licence` 格式错误（如 `licence` 含空白）→ `400 VALIDATION_ERROR`，格式正确 → `503 MAINTENANCE`；`PATCH` 带错误类型的 `tier` → `400`，格式正确 → `503`（未设置证书时也是 503，不是 409）；`POST /me/data-licence/test` → `503`；`GET` → `200`，`DELETE` → `204`。
- **v0.2.9 验收**（T-A11 研究候选，§7.7A）：
  1. 枚举：`/meta/enums` 含 `research_candidate_status`（`researching` `watching` `dropped` `planned`）、`research_candidate_origin`（`strategy_screen` `suggestion` `manual` `from_stock`）、`candidate_decision`（`continue` `watch` `drop`），取值与顺序同 §3，且与库表 CHECK 一致。
  2. 只看本人：用户 A 的候选，用户 B 调 `GET /candidates/{id}`、`/versions`、`/versions/1`、`POST /candidates/{id}/versions` 都是 `404`；B 的 `GET /candidates`（含 `status=all`）不含 A 的候选；B 用 A 的建议 id 查 `?suggestion_id=` 得空列表；B 以 `origin=suggestion` 引用 A 的建议 → `400{field:"suggestion_id", issue:"not_found"}`，响应与引用不存在的 id 完全相同。
  3. 新建：`manual` → `201`，`status="researching"`，`current_version.version_no=1`、`decision=null`，`conditions_to_hold` 每条 `epistemic_type="hypothesis"`；同一 `Idempotency-Key` 同体重放返回同一候选、不新增行；`origin=strategy_screen` → `400{issue:"not_supported"}`；ETF、指数 → `400{issue:"security_type_not_supported"}`；未知代码 → `400{issue:"unknown_security"}`；条件既无 `verify_by` 也无 `verify_method` → `400{issue:"verification_required"}`；`origin=suggestion` 带不一致的 `security_code` → `400{issue:"mismatch"}`。
  4. 重复：同一用户同一证券已有 `researching` 或 `watching` 的候选 → `409 CONFLICT{field:"security_code", existing_id}`，`existing_id` 为该候选；并发两个 `POST` 只有一个 `201`；该候选 `drop` 后再建 → `201`；不同用户的同一证券互不影响。
  5. 版本与决定：正确的 `base_version_no` + `decision=watch` + 理由 → `201`，`status="watching"`、`version_no` 加 1，旧版本内容逐字不变；过期的 `base_version_no` → `409 VERSION_CONFLICT{current_version_no}`；`decision` 非 null 而无理由、或 `decision=null` 带理由 → `400`；不带 `decision` 的新版本状态不变；`drop` 后再建版本 → `409 INVALID_STATE_TRANSITION`，`from="dropped"`、`allowed=[]`。
  6. 不可变：对 `/candidates/{id}`、`/candidates/{id}/versions/{n}` 调 `PUT`、`PATCH`、`DELETE` → `405` 且带 `Allow` 头；直接在库中 `UPDATE`/`DELETE` `candidate_versions` 被触发器拒绝。
  7. 回看：建第 1 版后改变数据（如证券 `risk_flag`、本人持仓变化），`GET /versions/1` 的 `reasons`、`counter_evidence`、`fit_assessment`、`evidence` 与创建时逐字相同；新建第 2 版才反映新数据。
  8. 系统内容：`origin=suggestion` 的 `reasons`、`counter_evidence` 每条都能在来源建议的 `strategies[].reasons`、`strategies[].counter_evidence` 或 `risk_flags` 中找到同文，`evidence_ids` 都能在本版本 `evidence[]` 中解析；`manual` 的 `reasons=[]`；画像未填写 → `profile_filled=false`、`hints=[]`；未导入持仓 → `holdings_available=false`，`warnings` 中没有持仓类提示。
  9. 隐私与删除：候选版本对应的 `data_snapshots` 行 `user_id` 为本人；关联的 `claims` 行 `user_id` 为本人（不为 null）；本人证书不可用时 `data_status` 降级，内容中没有任何来自他人证书的数据；对该用户运行账号数据删除后，`research_candidates`、`candidate_versions`、对应的 `claim_links` 与 `claims` 都为 0 行。
  10. 列表：不带 `status` 时不含 `dropped`；`status=dropped` 只含 `dropped`；`status=all` 全部；非法值 → `400`；§1.2 分页按 `created_at desc, id desc` 翻页不重不漏；`origin=`、`security_code=`、`suggestion_id=` 过滤生效。
  11. 无通知、无草案：新建候选、新建版本、`drop` 都不产生 `notifications` 行，也没有 SSE 事件；研究候选的状态在本版不会变为 `planned`，`plan_ids=[]`、`strategy_run_id=null`。
- **v0.2.9 验收**（T-F22 管理端证书遗留，§7.9）：
  1. resume 幂等：用户已设置证书且未被管理员暂停（如 `active`）时 resume → `204`，`status`、`paused_until` 不变，`audit_logs`、证书事件表、`notifications` 都没有新增行；未暂停且未设置证书时 resume → `409 DATA_LICENCE_NOT_SET`。
  2. 列表排序：多个用户 `created_at` 不同时按 `created_at desc`，相同时按 `id desc`；带 `?status=paused_by_admin&q=示例` 的结果与不带参数时相同。
  3. 理由不外露：以虚构理由“示例理由”pause 后，`/admin/data-licences`、`/admin/ingest/status`、`/me/data-licence`、该用户的通知与 SSE 的响应全文都不含该理由与管理员用户名；`audit_logs` 中有一条 `action="data_licence.paused"`、`detail.reason` 为该理由的记录。
  4. 冷却：回放上游 101 后，同一证书在 `/admin/data-licences` 与 `/admin/ingest/status` 中都是 `status="quota_exceeded"`，`paused_until` 非 null 且两处相等。
  5. 通知：`active` 时 pause → 该用户新增 1 条通知，`kind="data_licence"`、标题“数据证书已被管理员暂停”、`target.type="none"`，正文不含理由；再次 pause → 不新增；resume → 新增 1 条“数据证书已被管理员恢复”；再次 resume → 不新增；暂停期间删除证书后 resume → 状态为 `not_set`，新增 1 条恢复通知；其他用户没有任何新增通知。
- **v0.2.9 验收**（#30 前端待定裁定，§1.3、§7.6、§7.7、§7.7B）：
  1. CSRF 白名单：`POST /auth/login`、`/auth/register` 不带 `X-CSRF-Token` 照常处理；带外站 `Origin` 的 login → `403 CSRF_FAILED`，不带 `Origin` → 照常；已登录但不带头的 `/auth/logout`、`/auth/password`、`POST /imports`（multipart）→ `403 CSRF_FAILED`；无会话的其他写请求 → `401 AUTH_REQUIRED`。
  2. 判定顺序：未登录发超过上限的请求体 → `413`；未登录发非法 JSON → `401`（不是 `400`）；已登录、缺 CSRF、发非法 JSON → `403 CSRF_FAILED`；非管理员不带 CSRF 写 `/admin/*` → `404`；`closed` 时带外站 `Origin` 的注册 → `503 REGISTRATION_CLOSED`。
  3. 候选信号事件：新信号的第一条事件 `from=null`、`cause="executability_check"`；拟定草案后有一条 `to="drafted"`、`cause="user"`。
  4. `STRATEGY_CONFLICT`：两个对方信号时 `evidence` 恰有两条 `key="signal.conflict_signal_id"`，`value` 分别为两个对方信号的 id。
  5. `POST /plan-drafts`：方向不同的两个信号 → `400`（不是 `409`）；同向但其中一个带 `STRATEGY_CONFLICT` → `409 SIGNAL_NOT_EXECUTABLE`；确认时数量不合手数 → `400`，`details.fields[0]` 含 `issue="lot_rule"`、`min_buy`、`step`；科创板可卖 350 股时卖 150 → `400`，卖 250 或 350 → 通过。
  6. `/plans`：默认列表不含 `done`、`cancelled`；`candidate_id` 非 null → `400`；同证券同动作重复创建 → `409 CONFLICT{existing_id}`；`triggered` 时新建版本 → `active`；关闭后再关闭或建版本 → `409 INVALID_STATE_TRANSITION`，`allowed=[]`；`PUT`/`PATCH`/`DELETE` → `405`。
  7. `/alerts`：默认只含 `new`、`read`；`dismissed` → `read` → `409`，`allowed=[]`；同状态 PATCH → `200` 不变；`origin=plan_condition` 的提醒出现在 `/alerts`，不出现在 `/today` 的 `alerts`；`POST /alerts` → `405`。
  8. `/meta/enums` 含 `plan_status`、`plan_condition_type`，值与 §3 一致；持仓含可转债且行业数据已接入时 `exposure.sector` 有 `name="未分类"` 一项，RC4 不因其触发。
- **v0.2.9 验收**（T-A04 证券主数据与搜索；T-T 复测补 414；#35 预览行；#36 刷新响应）：
  1. 枚举与错误码：`/meta/enums` 的 `enums` 比上一节多 `security_reconciliation_kind`、`security_reconciliation_source`（§3 共 86 个），取值与 §3 一致；`error_codes` 含 `URI_TOO_LONG`，HTTP 414。
  2. 414：经 nginx 发请求行超过 8192 字节的 GET（未登录、已登录、`/admin/*`、不存在的路径各一次）→ 都是 `414`，`error.code="URI_TOO_LONG"`、`message="请求地址过长"`、`details.max_bytes=8192`，`error.request_id` 与 `X-Request-Id` 相等，`Cache-Control: no-store`。
  3. 曾用名首字母：虚构夹具证券“示例银行”的曾用名“示例发展”，搜 `SLFZ` → 命中，`match_kind="former_name"`、`matched_text="示例发展"`；搜“示例发展”同层同结果。
  4. 多音字与去 ST：简称含多音字时，每种读音组合的首字母都命中 `initials_exact`（组合不超过 16 个时）；超过 16 个时默认读音那一组一定保留；`*ST示例` 用 `SL`、`STSL` 都能命中。
  5. 隔离：对账夹具中的 `vendor_unknown` 代码搜不到，`/securities/{code}` → `404`；`/admin/securities/reconciliation?kind=vendor_unknown` 能看到该行。
  6. 退市判定：交易所当前列表中消失、但不在终止上市名单中的代码 → `missing_from_list`，不是 `delisted`；简称带“退”且仍在当前列表中 → `delisting_period`；只有进入终止上市名单后才是 `delisted`。
  7. `quote_missing`：本人证书对账缺失的代码为 `true`，其余为 `false`；未设置证书的用户全部为 `null`；ETF、指数恒为 `null`。
  8. 管理端：`/admin/securities/reconciliation` 非管理员 → `404`；响应全文不含测试证书值长度 ≥ 4 的子串；`master.*` 告警每个键最多一条。
  9. 预览行（#35）：`previewed` 批次 discard 后 `import_rows` 中该批次为 0 行，批次头仍在且 `stats` 不变；`GET /rows` → `200`、`items=[]`；`errors.csv` 只有表头；对该批次 resolve → `409 INVALID_STATE_TRANSITION`；人为留下残留行后，每小时清理任务运行一次即清空。
  10. 刷新（#36）：首次刷新 → `200`、`changed=true`、`superseded_id=null`；结论变化后刷新 → `superseded_id` 为旧 id；无变化 → `changed=false` 且 `suggestion.id` 等于当前有效的那条；刷新后立即 `GET /suggestions?security_code=&status=active&limit=1` 与响应体的 `suggestion` 相同；刷新期间 `ingest` 没有收到拉取请求。
- **v0.2.9 验收**（#37–#40，T-F23 待定 9、T-F24 缺失项 1–3）：
  1. `POST /plan-drafts`（#37）：因 `T1_NOT_SELLABLE` 等任一原因处于 `blocked` 的信号 → `409 SIGNAL_NOT_EXECUTABLE`，`reason_ids` 含该原因；`STRATEGY_CONFLICT` 同样；`dismissed`/`expired` 信号 → `409 INVALID_STATE_TRANSITION`，`allowed=[]`；`open` 信号 → `201`，信号变为 `drafted`；他人或不存在的信号 id → `400`，`issue="not_found"`（不是 `404`）；同时有 `simulating` 模板信号和 `blocked` 信号 → `409 STRATEGY_VERSION_NOT_RUNNABLE`。
  2. 心跳字段（#38）：停 ingest 心跳 → `/admin/ingest/status.heartbeat="stale"` 且与 `/health/ready.ingest` 相同，leader 不为 null 时 `alerts` 有一条 `heartbeat`；写入 `ingest:paused` → `heartbeat="paused"`，不出 `heartbeat` 告警；响应中没有心跳时间字段。
  3. `master.*` 文案（#39）：5 个键的 `message` 与 §7.9 ⑥ 逐字一致，不含代码、数字或用户名；同时有 `licence.expired` 与 `master.vendor_unknown` 时，前者排在前面。
  4. `days_left` 为 null（#40）：未填写到期日的证书 `days_left=null`，`alerts` 中没有 `licence.expiring`；在 `licences[]` 中排在同状态有 `days_left` 的行之后。
- **T-A16 验收（T-B78）**：
  1. 每个 `StrategyConclusion.confidence` 可由 `components` 按 §5.2 公式重算出 `value` 与 `level`；`margin_rules[].rule_id` 都在该结论的 `rule_refs` 中。
  2. 引擎产出的建议 `engine_policy` 非空，`version_no`、`content_sha256` 与库中 `engine_policies` 一致。
  3. 日报与 `/today` 的 `important_count` 等于 `/reconciliation` 中未忽略且 `important=true` 的条数；有差异时不返回 503。
  4. 跨日 `change_from_previous`：`new`、`changed`（含 `change_fields`）、`unchanged`、`removed` 与无基准时的 `null` + gap 各至少一例。
  5. `simulating` 策略的建议在 `SuggestionSummary.actions[].lifecycle` 中可见。
