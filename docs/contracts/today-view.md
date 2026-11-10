# today 页空态与缺口展示契约（T-A139，draft）

- 依据：
  - 现状代码以 be/T-B130=817c0ce 为准：
    - 后端：`aggregates/service.today`、`aggregates/models.Today`、`reports/service.build`、`workers/daily`（analyze）、`marketdata/daily_snapshot.daily_bars_ready` 与 `build_owned_snapshot`；
    - 前端：`pages/today/TodayPage`、`api/queries.useToday` 与 `useDailyReport`。
  - 日 K 口径见 `docs/contracts/daily-snapshot-from-bars.md`（docs/T-A128=f8aeef0）。
- 范围：P2N 闭环第 3 环。只规定前端展示；**后端不加接口、不改字段**。

## 1. 数据来源（裁定）

| 来源 | 用途 | 现状 |
| --- | --- | --- |
| `GET /today`（`useToday`，已有，带轮询） | 持仓与重点关注行、候选信号、对账状态、日报状态、账户级数据缺口 | `today` 中 `data_gaps` 只含 user_input_missing 的账户级缺口（去向为导入页）；`alerts`、`plan_triggers` 固定为空块 |
| `GET /daily-reports/{date}`（`useDailyReport`，已有） | 盘后分析缺口（`gaps` 中 key 以 `pipeline.` 开头的项）、`account` 是否为 null、各股缺口 | 只有日报生成后才有；未生成时返回 404 |
| `/alerts` | **本单不用** | 把 `/today` 的 `alerts` 接到 `/alerts` 是 T-A127 补缺第 4 项（后端），与空态无关，另行排期 |

- **裁定**：today 页 = `/today` + 当日日报详情。
  - 只有当 `/today` 的 `daily_report.status` 为 ready 时，才以 `daily_report.date` 请求 `/daily-reports/{date}`；其他状态不请求，避免 404。
  - 后端 `today` 的状态口径：日报 partial 也算 ready。
- **理由**：
  - 分析产生的 issue 已由 `reports/service.build` 以 `pipeline.<issue>` 写进日报 `gaps`，无需新接口。
  - 取数侧的 issue（`daily_bars_source_off`、`daily_bars_http_budget_unset`、`data_licence_unavailable`、`daily_bars_upstream_halted`、`daily_bars_quota_deferred`）只写在取数运行记录里，不进日报。analyze 把它们统一折算成 `daily_bars_not_ready`（见 `daily_bars_ready`：运行状态不是 ok/partial 即不就绪），所以前端只需展示「日 K 未就绪」，不区分原因。
- **解析规则**：
  - 日报 `gaps[].key` 去掉前缀 `pipeline.` 后，在第一个冒号处切开：前半段是 code，后半段是参数（证券代码、实例 id 或路径，可能为空）。
  - 前端按 code 查本文 §2.3 的文案表；未知 code 统一显示兜底文案「部分数据暂不可用」，不显示原始 code。

## 2. 状态清单

**时间**：一律用 `/today.server_time` 换算到 Asia/Shanghai 判断，用 `Intl.DateTimeFormat` 并显式指定 `timeZone`；不用浏览器本地时区（用户在 Windows 上，系统时区不是北京时间）。

**展示位置**：
- 顶部状态条只显示优先级最高的一条全局状态；
- 「数据缺口」区列出全部缺口，按证券合并，每只证券一行，最多 10 只，其余显示「等 N 只」；
- 「重点关注」表照旧。

### 2.1 全局状态（顶部状态条，按优先级从高到低，只取第一条命中的）

| # | 状态 | 判定（字段） | 用户文案 | 显示字段 / 操作 |
| --- | --- | --- | --- | --- |
| S1 | 未导入持仓 | `/today.reconciliation.status` 为 not_imported，且 `focus.items` 中没有任何一行 `holding` 非空 | 还没有导入持仓，导入后才能生成你的日报。 | 按钮「导入交割单」，去向 /portfolio/import |
| S2 | 已导入但无持仓 | reconciliation 不是 not_imported，且 `focus.items` 中没有任何一行 `holding` 非空 | 当前没有持仓，日报只覆盖你的自选。 | 无 |
| S3 | 非交易日 | `session` 为 non_trading_day | 今天休市，没有新的日报。 | `trade_date` |
| S4 | 盘后数据准备中 | 交易日；`daily_report.status` 为 not_yet 或 generating；北京时间 ≥ 15:00（含收盘后的 closed 时段），且不满足 S5（§7 ①，T-A142 修订） | 盘后数据准备中，日报约 17:30 生成。 | 若已有 `focus` 行带候选信号，追加一句：「候选信号已更新。」 |
| S5 | 日报逾时未生成 | 交易日；北京时间已到 17:45（含）；`daily_report.status` 仍为 not_yet | 今日日报还没有生成，请稍后再看。 | 无 |
| S6 | 日 K 未就绪 | 日报已生成，且 `gaps` 中有 key 为 `pipeline.daily_bars_not_ready` 的项 | 今日行情数据未就绪，本日报未做策略分析。 | 日报链接 |
| S7 | 行情源未开通 | 日报 `gaps` 中有 key 为 `pipeline.owned_market_cache_adapter_missing` 的项 | 行情数据源尚未开通，本日报未做策略分析。 | 日报链接 |
| S8 | 盘后分析无记录 | 日报 `gaps` 中有 key 为 `pipeline.analysis` 的项 | 今日盘后分析没有完成记录。 | 日报链接 |
| S9 | 正常 | 以上都不命中 | 不显示状态条 | — |

### 2.2 账户与候选信号（与全局状态并列显示，不互斥）

| # | 状态 | 判定 | 用户文案 | 显示字段 |
| --- | --- | --- | --- | --- |
| A1 | 账户总览不可算 | 日报的 `account` 为 null | 暂时算不出账户总览（缺持仓价格或现金）。 | 若 `/today.data_gaps` 有去向为导入页的项，显示「去补录 ›」 |
| A2 | 账户总览可算 | `account` 非空 | 照常显示总资产、现金、仓位占比；`pnl_day` 为 null 时显示「—」，不显示 0 | `total_assets`、`cash`、`position_pct`、`pnl_day` |
| R1 | 有候选信号 | `focus.items` 中至少一行 `suggestion` 非空 | 沿用现有「候选信号」列（`ActionBadge` 与 `ACTION_FULL` 的「规则信号：…（候选）」）。不新增文案，`CardDisclaimer` 必须可见 | `suggestion.actions`、`executability_status` |
| R2 | 无候选信号 | 所有行的 `suggestion` 都为空，且全局状态为 S9 | 今天没有新的候选信号。 | 无 |

- R2 不与 S1、S3–S8 同时显示：那些状态已经说明了原因。
- 用词约束：不出现「买入」「卖出」「建议你」等诱导性措辞。动作名只经现有 `ACTION_FULL`、`ACTION_SHORT` 展示，并始终带「规则信号」「候选」字样。

### 2.3 缺口 code 文案表

下表的 code 全部来自现有代码，取自日报 `gaps` 的 `pipeline.<code>[:参数]`。「可操作」表示用户自己能处理，并给出去向。

| code（参数） | 产生处（函数） | 用户文案（按证券行显示时前面加代码和名称） | 可操作 |
| --- | --- | --- | --- |
| daily_bars_not_ready | `workers/daily` analyze，取数未成功时（含数据源关闭、预算未开、回执无效、上游停止、额度顺延） | 见 S6 | 否 |
| owned_market_cache_adapter_missing | analyze，数据源为 off 的非测试环境 | 见 S7 | 否 |
| daily_bars_missing（证券） | `daily_bars_ready` 携带的取数缺口；`build_owned_snapshot` | 今日缺少日 K 数据，未参与分析。 | 否 |
| daily_bar_conflict（证券:日期） | `daily_bars_ready` 携带的写入冲突 | 日 K 数据有冲突，已沿用首次记录。 | 否 |
| daily_bars_after_asof（证券） | `build_owned_snapshot` | 日 K 晚于分析截止时间到达，今日未采用。 | 否 |
| daily_bars_not_final（证券） | `build_owned_snapshot` | 日 K 尚未确认为收盘数据，今日未采用。 | 否 |
| security_board_missing（证券） | `build_owned_snapshot` | 缺少板块信息，未参与分析。 | 否 |
| owned_snapshot_licence_unbound（证券） | `build_owned_snapshot` | 数据授权未绑定，结果仅供参考。 | 否 |
| owned_snapshot_hash_conflict | `build_owned_snapshot` | 今日数据快照异常，已保留首次结果。 | 否 |
| calendar_not_covered | `build_owned_snapshot` | 交易日历未覆盖今天，未做分析。 | 否 |
| owned_source_security_missing（证券） | analyze | 未进入今日数据快照，未参与分析。 | 否 |
| owned_source_or_card_missing | analyze | 数据快照或策略卡不可用，未做分析。 | 否 |
| security_not_eligible（证券） | analyze（非上市股票，如基金或已退市） | 该证券不在分析范围内（仅支持上市股票）。 | 否 |
| active_instances_missing | analyze | 还没有启用中的策略实例。 | 是，去向 /strategy-instances |
| version_unavailable | analyze | 策略版本暂不可用。 | 否 |
| runtime_lifecycle_blocked（实例 id） | analyze | 有策略实例当前状态不能运行。 | 是，去向 /strategy-instances |
| runtime_source_gate（路径:原因） | analyze | 策略所需的部分数据尚未验证，未做分析。 | 否 |
| engine_policy_seed_missing（证券） | analyze | 系统配置未就绪，未做分析。 | 否 |
| evaluated_input_gaps（证券） | analyze；求值输入缺口，例如 `features/pipeline` 的复权因子缺口 `adjust_factor_missing:<日期>`，它只出现在建议证据里，不单独进 gaps | 部分输入数据缺失，结果不完整。 | 否 |
| analysis（键为 `pipeline.analysis`） | `reports/service.build`：没有本人的分析记录 | 见 S8 | 否 |
| 其他未知 code | — | 部分数据暂不可用。 | 否 |

**日报中的非 pipeline 缺口**：
- `account`：即 A1；
- `account.<证券>.price`：文案「缺现价，按成本估算」；
- `account.pnl_day`：日盈亏显示「—」；
- `cash`：未录入现金，可操作，去向 /portfolio/import；
- `stocks.<证券>`：该股无候选信号；
- `stocks.<证券>.<维度>.<键>`：只在日报详情页展示，today 页不展开；
- `stocks.change_from_previous`、`market`：today 页不展示。

**`/today.data_gaps`**：现有渲染不变，只是标题合并进「数据缺口」区。

## 3. 时序（北京时间，交易日）

| 时段 | 后端在做什么 | today 显示 |
| --- | --- | --- |
| 开盘前到 15:00 | — | 盘中现有展示；日报区显示「收盘后生成」 |
| 15:00–17:15 | 等待日 K | S4 |
| 17:15–17:30 | `daily_bars_fetch`（17:15 槽） | S4 |
| 17:30 至日报就绪 | analyze（17:30，截止时刻 17:30），结束后立即生成日报（REPORT 紧跟 analyze，`daily-bars-source.md` §9.1） | S4；analyze 已写出候选信号而日报尚未就绪的短暂间隙里带「候选信号已更新」；**不显示分析缺口** |
| 日报就绪起 | — | 读日报，按 S6–S8、A1/A2、R1/R2 与 §2.3 显示 |
| 17:45 起仍为 not_yet | — | S5（generating 仍为 S4，§7 ①） |

- 自选（T-A129 / 契约 Q4）：analyze 的范围是持仓 ∪ 本人有效自选；today 的「重点关注」是持仓 ∪ 重点关注（focus_codes）。
  - 自选里不在重点关注中的证券，它的缺口只在「数据缺口」区出现，不在「重点关注」表里出现。
  - 17:15 之后才加入的自选，当日通常会出现 daily_bars_missing 或 owned_source_security_missing，属正常现象，文案不变。
  - T-A142：新加的持仓或自选会自动补 3 年历史（`daily-bars-source.md` §9.2），但开市日 17:00–17:45 加入的不补当日；补历史默认不出网（上限常量为 0），today 不为「待补」单独显示状态。

## 4. 前端验收（mock 直接测，G/W/T）

**mock 形状**（示例代码均为虚构）：

```ts
// GET /today
{ server_time: "2026-11-10T10:40:00Z", trade_date: "2026-11-10", session: "closed",
  reconciliation: { status: "matched", as_of: null, diff_count: 0, important_count: 0 },
  daily_report: { date: "2026-11-10", status: "ready" },
  focus: { items: [{ security_code: "000001.SZ", name: "示例甲", holding: { weight_pct: "12.5" }, suggestion: null }], more: false },
  data_gaps: { items: [], more: false }, gaps: [] /* 其余块为空块 */ }
// GET /daily-reports/2026-11-10
{ date: "2026-11-10", account: null,
  gaps: [{ key: "pipeline.daily_bars_missing:000002.SZ", reason: "no_source", message: "…" }] }
```

**用例**（共 16 条）：
1. Given `reconciliation.status` 为 not_imported，focus 中没有持仓 / When 渲染 / Then 状态条显示「还没有导入持仓…」，并有指向 /portfolio/import 的「导入交割单」，不请求日报。
2. Given reconciliation 为 matched、focus 中没有持仓 / Then 显示「当前没有持仓，日报只覆盖你的自选。」
3. Given session 为 non_trading_day / Then 显示「今天休市，没有新的日报。」，不请求日报。
4. Given server_time 为北京 17:20、status 为 not_yet / Then 显示 S4，不请求日报。
5. Given 北京 17:40、status 为 not_yet、focus 中一行 `suggestion` 非空 / Then 显示 S4 并带「候选信号已更新。」
6. Given 北京 18:50、status 为 not_yet / Then 显示 S5。
7. Given 浏览器时区为 America/Denver、server_time 为 2026-11-10T09:20:00Z（北京 17:20）/ Then 仍判定为 S4，用来验证不用本地时区。
8. Given status 为 ready、日报 gaps 含 `pipeline.daily_bars_not_ready` / Then 显示「今日行情数据未就绪…」，页面文本中不出现 daily_bars_not_ready。
9. Given 日报 gaps 含 `pipeline.owned_market_cache_adapter_missing` / Then 显示 S7。
10. Given 日报 gaps 同时含 `pipeline.daily_bars_missing:000002.SZ` 与 `pipeline.owned_source_security_missing:000002.SZ` / Then 「数据缺口」区 000002.SZ 只占一行，显示两句文案，页面不出现 pipeline 字样。
11. Given 日报 gaps 含 `pipeline.security_not_eligible:510000.SH` / Then 显示「该证券不在分析范围内…」，没有操作按钮。
12. Given 日报 gaps 含 `pipeline.active_instances_missing` / Then 显示「还没有启用中的策略实例。」，并有指向 /strategy-instances 的入口。
13. Given 日报 gaps 含 `pipeline.unknown_future_code:000001.SZ` / Then 显示兜底文案「部分数据暂不可用。」
14. Given 日报 `account` 为 null，`/today.data_gaps` 有一条去向为 /portfolio/import 的 cash 缺口 / Then 显示 A1 文案和「去补录 ›」。
15. Given 日报 `account` 非空、`pnl_day` 为 null / Then 日盈亏显示「—」，不显示 0。
16. Given 状态为 S9、所有 focus 行的 `suggestion` 都为空 / Then 显示「今天没有新的候选信号。」；页面文本不含「买入」「卖出」；`card-disclaimer` 可见。

另附通用断言：缺口区超过 10 只证券时显示「等 N 只」；status 不为 ready 时，网络 mock 记录到的 `/daily-reports/` 请求数为 0。

## 5. 后端最小改动

**无。** 可选项（非本闭环，需用户确认后另开单）：
- ~~让 `/today` 直接带出当日分析 issue 摘要，使 17:30–18:30 也能显示缺口~~（T-A142：日报紧跟 analyze 生成，该时段不复存在，撤销此项）；
- 把 `/today.alerts` 接到 `/alerts`（T-A127 第 4 项）。

## 6. 待用户确认（括号内为本契约的保守默认）

- ~~U1：17:30–18:30 是否需要提前显示分析缺口。~~ 结案（T-A142）：用户定「日报提前到17:30」，该时段不复存在。
- ~~U2：S5 的逾时阈值。~~ 结案（T-A142）：17:45，即 `REPORT_EXPECTED_AT` 17:30 加 15 分钟。
- U3：缺口区是否显示证券名称。（显示代码和名称，与「重点关注」一致）

## 7. 补充裁定（T-A140，评审 fe/T-F34=549ecdf 后定）

函数名均指 `pages/today/todayView` 中的同名导出，用例名见 `pages/t-f34.test.tsx`。

**① S4 的时段。** S4 的判定改为：交易日；`daily_report.status` 为 not_yet 或 generating；北京时间 ≥ 15:00；并且不满足 S5。因此 17:30 到逾时阈值之间的 not_yet，以及逾时之后仍为 generating 的情况，都显示 S4。只有「已到逾时阈值且仍为 not_yet」才显示 S5。（T-A142：时刻由 18:30/18:45 改为 17:30/17:45。）
- Given 北京时间 17:40、not_yet / Then 显示 S4。
- Given 北京时间 18:40、not_yet / Then 显示 S5。
- Given 北京时间 19:10、generating / Then 显示 S4，不显示 S5。

**② S1、S3 不请求日报。** S1、S3 下即使 status 为 ready，也不请求 `/daily-reports/{date}`，因此不显示 A1/A2 和日报缺口（见 `reportDateToFetch`）。
- Given S3、status 为 ready / Then 日报请求数为 0，页面没有 today-account。

**③ R2 的显示条件。** R2 只在全局状态为 S9 时显示，其他状态（包括 S2）都不显示。
- 补充：S9 必须来自日报判定（`reportState`），也就是 status 为 ready 且日报读取成功。
- 交易日 15:00 之前，status 尚未 ready 时，前置状态都不命中，**不显示状态条，也不显示 R2**，因为当日盘后批次还没有跑。
- Given 北京时间 10:00、not_yet、所有行无候选信号 / Then 不显示「今天没有新的候选信号。」
- Given S2、无候选信号 / Then 不显示 R2。

**④ 未知 code 的归属。** 对未知 code，只有当参数的第一段**完全符合系统证券代码格式**（6 位数字，加 .SH、.SZ 或 .BJ，与后端 `trades.normalize_code` 的输出一致）时，才归到该证券行；否则作为通用行。两种情况都只显示兜底文案。
- 不接受宽松格式。例如特征路径 `f.pe` 不能被当成证券，也不能生成 /stocks 链接。
- 已知 code 的证券参数由后端生成，按 §2.3 表中「（证券）」的位置取值。
- Given `pipeline.future_x:000001.SZ` / Then 归到 000001.SZ 行，显示兜底文案。
- Given `pipeline.future_gate:f.pe:missing` / Then 是一条通用行，页面上没有 /stocks/f.pe 链接。

**⑤ 状态条与缺口区不重复。** S6、S7、S8 中已在状态条显示的那一条，不在缺口区重复；没有显示的（优先级较低，或者被 S1–S5 压住），仍进入缺口区的通用行（见 `buildReportGaps` 的 shownState 参数）。
- Given 日报 gaps 同时含 daily_bars_not_ready 与 analysis / Then 状态条显示 S6，缺口区有 S8 文案、没有 S6 文案。

**⑥ 日报读取失败。** status 为 ready，但 `/daily-reports/{date}` 返回 404 或出错时：
- 不判定 S6–S9，不显示状态条、R2、A1/A2；
- 缺口区显示「日报详情暂时读取失败，分析缺口稍后显示。」
- `/today` 自身的块照常显示。
- Given status 为 ready、日报 404 / Then 显示上述文案，页面没有 today-no-signals 和 today-account。

**⑦ 非 pipeline 缺口。** §2.3 没有列出的非 pipeline 日报缺口，today 页默认不显示，但有一个例外：reason 为 user_input_missing 的项必须显示为通用行「有信息待补录。」，并附「去处理 ›」，去向 /portfolio/import。这是为了不藏掉用户自己能处理的缺口。
- 与 `/today.data_gaps` 同 key 的项只显示一次，例如 cash 不能在同一区里出现两遍。
- 已列出的项仍按 §2.3 显示：
  - `cash`：「未录入现金。」，可操作；
  - `account.<证券>.price`：「缺现价，按成本估算。」；
  - `stocks.<证券>`：「该股无候选信号。」；
  - account、account.pnl_day 由 A1/A2 表达。
- Given 日报 gaps 含 key 为 `account.future_field`、reason 为 user_input_missing 的项 / Then 显示「有信息待补录。」并带去向 /portfolio/import。
- Given 日报 gaps 含 `market` / Then 不显示。
- Given `/today.data_gaps` 与日报 gaps 都含 cash / Then 「未录入现金」只出现一次。

**⑧ 逾时阈值由常量推导。** 「日报约 HH:MM 生成」的时刻只由常量 `REPORT_EXPECTED_AT` 定义（T-A142 起为 17:30，用户原话「日报提前到17:30」）。逾时阈值为该常量加 15 分钟（`overdueAt`，`REPORT_OVERDUE_GRACE_MIN` 仍为 15），即 17:45。S4 的文案随常量变化（`s4Text`）。
- Given 默认常量、北京时间 17:44 / Then S4，文案为「日报约 17:30 生成」；17:45 / Then S5（含边界）。
- Given 常量注入为 18:30（反向验证推导，不是默认值）/ Then 18:44 为 S4，18:45 为 S5，文案为「日报约 18:30 生成」。

**本节新增验收：** 共 12 条（①2、②1、③2、④2、⑤1、⑥1、⑦3），加上 ⑧ 的 2 条已在 t-f34 中实现。其中 ③ 的 15:00 前一条、④ 的 `f.pe` 一条、⑦ 的 user_input_missing 一条和 cash 去重一条，在 549ecdf 上尚未实现，由前端跟进。

## 8. 补充裁定 a–d（T-A140 续，复审 fe/T-F34=3ff17df 后定）

**a. 已知 code 的证券参数格式不符。** 已知 code 的证券参数如果不符合 §7 ④ 的严格格式（`SEC_RE`），按通用行显示该 code 原有的文案，不生成 /stocks 链接。
- Given `pipeline.daily_bars_missing:abc` / Then 是一条通用行，文案为「今日缺少日 K 数据，未参与分析。」，没有 /stocks/abc 链接。

**b. 同 key 去重与待补录合并。** §7 ⑦ 的「同 key 去重」按 key 完全相等判断。`/today.data_gaps` 的 key 与日报 gap 的 key 同源，例如 cash 由 `aggregates/service.today` 与 `reports/service.build` 用同一个键产生。多条「有信息待补录。」在同一个位置只显示一行，也只带一个「去处理 ›」（见 `buildReportGaps`）。
- Given 日报 gaps 含两条不同 key、reason 都为 user_input_missing 的未列出项 / Then 通用行中「有信息待补录。」只出现一次。

**c. §2.3 已列出、today 不展示的键遇到 user_input_missing。** 逐键判定。判定依据：用户能否在系统内补齐；today 页是否已经在别处表达。

| 键 | 用户能否补齐 | today 是否已在别处表达 | 结论 |
| --- | --- | --- | --- |
| account | 能（导入持仓、录入现金） | 能。`reports/service.build` 只在账户不可算时写这个键，此时 `account` 为 null，A1 显示，并在 `/today.data_gaps` 有导入去向时带「去补录 ›」（`TodayAccount`） | 不重复显示 |
| account.pnl_day | 不能（缺上日基准，系统自行补齐） | A2 显示「—」（`TodayAccount`） | 不显示 |
| market 及 market.* | 不能（市场数据不由用户录入） | 页头的大盘环境与数据状态标签 | 不显示 |
| stocks.<证券>.<维度>.<键> | 视 reason 而定。为 user_input_missing 时，通常是持仓成本之类，可经导入补齐 | 不一定。`/today.data_gaps` 只带 `aggregates/service.terminal` 产生的账户级缺口，不覆盖各维度 | **c 在这个键上不成立**：reason 为 user_input_missing 时，在该证券行（证券段符合 `SEC_RE`）显示「有信息待补录。」，并附去向 /portfolio/import；其他 reason 仍不显示 |
| stocks.change_from_previous | 不能 | — | 不显示 |

- 现状：`reports/dimensions.missing` 的 reason 默认为 no_source，`reports/service.build` 里只有 cash 一项是 user_input_missing。所以 stocks 维度键这一条目前不会触发，是面向以后的规则。
- Given 日报 gaps 含 `stocks.000001.SZ.technical.cost`、reason 为 user_input_missing / Then 000001.SZ 行显示「有信息待补录。」，并带去向 /portfolio/import。
- Given 同一个键、reason 为 no_source / Then 不显示。
- Given 日报 gaps 含 key 为 account、reason 为 user_input_missing，且 `account` 为 null / Then 只显示 A1，缺口区没有「有信息待补录。」

**d. 15:00 前日报已为 ready。** 交易日 15:00 前，如果 status 已为 ready，S9 由日报判定，照常按 R2 规则显示。
- 核实：`aggregates/calendar.market_clock` 在交易日返回当天的 trade_date，在休市日返回前一开市日并标记 non_trading_day；`aggregates/service.today` 只查 `clock.trade_date` 那一天的日报。
- 所以交易日看到的 ready 一定是**当天**的日报，比如提前或手工生成的；不会出现「前一交易日的日报被当成今天」。前一交易日的日报只会在休市日出现，而休市日是 S3，不请求日报，也不显示 R2。
- Given 交易日北京时间 10:00、status 为 ready、日报 gaps 无 S6–S8、所有行无候选信号 / Then 显示 R2。
- Given 休市日、status 为 ready / Then 显示 S3，不请求日报，不显示 R2。

## 9. 日报时刻修订（T-A142）

依据用户答卡 t809s2732「日报提前到17:30」。本节逐条核对 §2–§8 受影响的位置。

- `REPORT_EXPECTED_AT` 改为 17:30，逾时阈值 17:45；`REPORT_OVERDUE_GRACE_MIN` 仍为 15，`overdueAt` 推导不变。S4 文案为「盘后数据准备中，日报约 17:30 生成。」
- §2.1 S4、S5，§3 时序表，§5 可选项，§6 U1/U2，§7 ①、⑧：已按上文改写。
- §7 ②–⑦：与时刻无关，不变。
- §8 a–c：不变。§8 d（15:00 前日报若已 ready）：不变。核实依据仍是 `aggregates/calendar.market_clock` 与 `aggregates/service.today` 只查当天；日报提前不会让前一交易日的日报出现在交易日。
- 新增注意：17:30 日报可能在取数未完成时生成，此时 gaps 带 `pipeline.daily_bars_not_ready`，显示 S6（文案不变）。17:30 之后才取到的标的不会在当天补进日报。
- 风险（非阻断）：analyze 若超过 15 分钟仍未结束，17:45 起 status 仍为 not_yet 时会显示 S5。保持 15 分钟，由运维观测 analyze 耗时；若常态超过，再提议调整宽限，不在本单改。

G/W/T（前端单，用例落在 `pages/t-f34.test.tsx`；测试单同步 `today-view.t-t74.test.tsx`）：
- Given 交易日北京时间 17:29、not_yet / Then S4，文案含「日报约 17:30 生成」。
- Given 17:40、not_yet、有候选信号 / Then S4 并带「候选信号已更新。」；日报请求数为 0。
- Given 17:44、not_yet / Then S4；17:45、not_yet / Then S5；18:40、not_yet / Then S5。
- Given 19:10、generating / Then S4。
- Given 17:31、status 为 ready、gaps 含 `pipeline.daily_bars_not_ready` / Then S6。
- Given 机器时区 America/Denver、server_time 2026-11-10T09:44:00Z（北京 17:44）/ Then S4；09:45:00Z / Then S5。

## 10. 做 T 视图 t_view 的状态显示（T-A145 交叉引用）

- 持仓行的 t_view 字段与状态以 `intraday-bars.md` §3.7 为准。它与本契约的 S1–S9 状态条互不影响：状态条仍只由 `/today` 与日报判定；t_view 的 stale、pending、partial、不适用只作用在该行的做 T 视图里。
- 显示复用既有的 `DataStatusTag` 与 `GapNote`，文案与本页其他数据状态一致（已过期、拉取中、部分缺失、不适用）。
- T-A146 补充：
  - 量比口径改为每分钟均量之比，见 `intraday-bars.md` §3.8。前端显示不变。
  - 不适用的判定只在 t_view 内用「任一 not_applicable」；全站 `isNotApplicable` 不变。
  - fresh 且 gaps 非空时照常显示 `GapNote`。
  - 时间显示：t_view 的数据时间与「截至 hh:mm」一律按北京时间换算，与机器时区无关。全站 `fmtTime` 的 Z 结尾问题另开前端单，见 `docs/reviews/T-F36b-review.md`。
