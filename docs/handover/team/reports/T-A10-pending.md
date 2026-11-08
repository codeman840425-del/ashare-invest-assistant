# T-A10 契约待定项整理与建议裁定

- 来源报告：`T-A09-frontend.md`（遗留 1–6）、`T-F17.md`（遗留 1–5）、`T-F18.md`（遗留 1–7 及“放弃接口”说明）、`review-fixes-frontend.md`（m1、m4、未处理项）
- 核对依据：`docs/api-contract.md`（HEAD 53468a5，v0.2.8，含补充裁定 #17）、`docs/plan.md`（HEAD），以及 HEAD 上 `src/backend`、`config/market_rules.yaml` 的实际实现
- 方法：只读（`git show HEAD:` 导出），没有改代码，没有提交
- 裁定原则（用户定）：
  - 优先与后端已有实现和契约现有写法一致，改动最小；
  - 安全和隐私从严；
  - 不新增细节的产品功能。
- 后端现状：HEAD 上只有 auth、me、data-licence、admin invites/data-licences pause·resume、health、meta 路由。**portfolio、candidate-signals、plan-drafts、tracking 都还没有接口**，只有表结构和枚举，所以下列“后端行为”多数指表约束和枚举。

## 结论速览

| 编号 | 问题 | 结论类型 | 要改契约 | 需用户做产品决定 |
|---|---|---|---|---|
| P01 | U3 与问题 63 不一致；可转债行的取值口径 | 契约漏同步 | 是 | 否（编排者已定） |
| P02 | 持仓行没有证券类型/估值标志 | 小幅加字段 | 是 | 否 |
| P03 | ETF `volume` 单位“手/份” | 已有答案（待 T003） | 否（只改说明） | 否 |
| P04 | `AdminDataLicence.licence_id` 两页互跳 | 前端排期 | 否 | 否 |
| P05 | `licences_truncated` 链接 | 前端排期 | 否 | 否 |
| P06 | 管理员暂停/恢复 UI | 契约与 plan 已有要求，前端欠账 | 否 | 否 |
| P07 | 候选信号事件的结构与 `cause` 枚举 | 契约没写清 | 是 | 否 |
| P08 | 列表冲突是否加 `conflict_signal_ids` | 不加字段 | 可选（一句说明） | 否 |
| P09 | 不可执行原因缺 `security_code`/`name` | 小幅加字段 | 是 | 否 |
| P10 | `BLOCKLISTED` 能否手动解除 | 已有答案，补一句 | 是（一句） | 否 |
| P11 | 跟踪统计是否显示全站 | plan 已定 | 是（补查询参数） | 否 |
| P12 | 多个 `signal_ids` 如何合并 | 契约没写清 | 是 | 否 |
| P13 | `chosen_qty` 整手规则 | 契约没写清 | 是 | 否 |
| P14 | expired 草案能否重新生成、是否关联 | 已有答案 | 否 | 否 |
| P15 | 放弃备注 `note` 不回显 | 契约与表结构不一致 | 是 | 否（默认删除） |
| P16 | 草案缺策略名和建议链接 | 不改 | 否 | 否 |
| P17 | `/plans/{id}` 是占位页 | 前端排期（依赖计划接口任务） | 否 | 否 |
| P18 | `INVALID_STATE_TRANSITION` 文案太笼统 | 已有答案 | 否 | 否 |
| P19 | 只有 pending 能放弃，其余 409 | 已有答案 | 否 | 否 |
| P20 | 不传 `form_started_at` | 已有答案 | 否 | 否 |
| P21 | review-8249d6e m2/m3、review-7afbc06 m1/m2/m3/m5 未排期 | 不是契约问题 | 否 | 否 |

---

## P01 U3 与 plan 问题 63 不一致；可转债持仓行如何取值
- **来源**：T-A09 遗留 1。
- **问题**：契约 U3（第 41 行）的默认仍写“本版不变：按原代码显示，无行情”，但 plan 第 9 节问题 63（第 3218 行）已由编排者在 2026-11-02 定下。另外，契约没有规定可转债行的 `market_value`、`pnl`、`weight_pct` 怎么取值。mock 假设按成本估算、`pnl=0`。
- **契约/plan 现有答案**：
  - plan 问题 63 已定：保留原代码，标注“可转债·无行情”；现价、市值显示“—”；总仓位与集中度按成本估算并标“估算”；不跑策略、不出信号，也不进入风控止损计算。
  - 契约 `/portfolio`（第 759 行）的 positions 字段没有可空说明。`TerminalRow.holding`（第 546 行）中 `weight_pct`/`pnl`/`pnl_pct` 都不可空。
- **后端行为**：`app/marketdata/security_types.py` 文件头写明可转债“本版不收录（仍按 `IMPORT_UNKNOWN_SECURITY`）；其持仓展示（问题 63）**未定，不实现**”。
- **建议裁定**：
  1. U3 改为【已定 2026-11-02】，内容引用问题 63。
  2. 对没有行情的持仓行（本版即可转债，以及其他未收录代码）：
     - `market_value`、`pnl`、`pnl_pct` 返回 `null`，**不返回 0**。mock 的 `pnl=0` 会被当成“不赚不亏”，属于误导，需要改。
     - `weight_pct` 按成本（`qty × cost_price`）估算。
     - `total_assets` 与 `exposure` 同样计入成本估算值。
     - 顶层 `data_status` 记为 `partial`。
  3. `TerminalRow.holding` 中 `pnl`、`pnl_pct` 改为 `string(decimal) | null`，口径同上。
- **要改契约**：
  - 第 41 行 U3；
  - §7.2 `/portfolio`（第 759 行）的 positions 可空说明；
  - §5 `TerminalRow`（第 546 行）`holding.pnl`/`pnl_pct` 的可空性；
  - 版本记录加一条（v0.2.9）。
- **谁跟着改**：
  - 架构师：改契约。
  - 后端：持仓汇总实现，同时把 `security_types.py` 的“未定，不实现”改为按裁定实现。
  - 前端：mock 的 `pnl=0` 改为 `null`。
  - 测试：契约测试加入“无行情行”用例。
- **需用户决定**：否（编排者已定）。

## P02 持仓行没有证券类型和估值标志
- **来源**：T-A09 遗留 2。
- **问题**：`PortfolioPosition` 没有 `security_type`，前端只能按代码前缀（沪 110/111/113/118，深 123/127/128）识别可转债。
- **契约现有答案**：没有。`security_type` 枚举（第 375 行）只有 `stock cdr etf index`，并写明“可转债本版不收录”。
- **后端行为**：没有可转债主数据，导入时报 `IMPORT_UNKNOWN_SECURITY` 后按 `import_as_is` 保留原代码；后端也不识别可转债。
- **建议裁定**：兼容地给 positions 元素和 `TerminalRow.holding` 各加两个字段：
  - `security_type: security_type | null`：`null` 表示主数据未收录，本版主要是可转债；
  - `estimated: boolean`：`true` 表示无行情，`market_value`/`pnl` 为 null，`weight_pct` 按成本估算。

  前端的展示和计算行为改为**只读这两个字段**。“可转债”这几个字的标签可以继续用前端代码前缀推断，但只用于展示文案，不能据此决定计算口径。**不新增** `convertible_bond` 枚举值，因为本版不收录可转债。
- **要改契约**：§7.2 `/portfolio` positions 结构；§5 `TerminalRow.holding`。
- **谁跟着改**：架构师；后端（持仓汇总）；前端（`lib/securityKind.ts` 只保留文案用途，逻辑改读字段）。
- **需用户决定**：否。

## P03 ETF 成交量显示“手”还是“份”
- **来源**：T-A09 遗留 3。
- **契约现有答案**：
  - 第 169 行补充裁定 #8：`Bar.t` 与 `volume` 单位“维持【待 T003/T-B05】，不阻塞；口径定后只改说明不改字段”。
  - 第 774 行：`/quotes` 中“ETF 与股票同口径”。
- **后端行为**：行情接口未实现，单位取决于 T003 对麦蕊数据的补测。
- **建议裁定**：字段不变。本版 ETF 与股票一样显示“手”（ETF 1 手 = 100 份，数值一致），不单独改成“份”。T003 定出 `volume` 原始单位后，只改契约说明。如果原始单位是“股/份”，前端再统一 ÷100。
- **要改契约**：本版不改。T003 出结论后改第 169 行和 §5 `Bar` 的说明。
- **谁跟着改**：T003（定单位）；前端在单位定后核对换算。
- **需用户决定**：否。

## P04 `AdminDataLicence.licence_id` 两页互跳
- **来源**：T-A09 遗留 4。
- **契约现有答案**：契约把互跳标为“可选”。`/admin/data-licences` 已在 §7.9（第 920 行）定义；第 93 行（v0.2.6）要求前端做“管理端证书列表（只有状态）”。
- **后端行为**：`GET /admin/data-licences` 已实现（`data_licence.py`）。
- **建议裁定**：契约不改。前端欠“管理端证书列表页”，应排期补上，做完后再按可选项接互跳。列表页**不显示证书值或任何片段**，与契约第 920 行一致。
- **要改契约**：无。
- **谁跟着改**：编排者（排期）；前端。
- **需用户决定**：否。

## P05 `licences_truncated` 的“完整列表”链接
- **来源**：T-A09 遗留 5。
- **建议裁定**：同 P04。证书列表页做好后，把文字提示改成链接；在此之前保持纯文字。契约不改。
- **谁跟着改**：前端（随 P04 一起做）。
- **需用户决定**：否。

## P06 管理员暂停/恢复 UI
- **来源**：T-A09 遗留 6。
- **契约/plan 现有答案**：
  - plan 第 368 行：管理端证书列表“可暂停/恢复（写审计）”。
  - 契约 §7.9 第 921 行定义了 `POST /admin/data-licences/{user_id}/pause`·`/resume`，请求体 `{reason: string(1–200)}` 必填。
- **后端行为**：两个接口已实现（`data_licence.py` 约第 380/401 行），会写审计，并且是幂等的。
- **建议裁定**：契约已经要求有这个功能，不是新增功能。前端随 P04 的列表页一起补“暂停/恢复”按钮，并按契约必填 reason。按钮只对 `role=admin` 可见；`/admin/*` 的 404 规则不变。
- **要改契约**：无。
- **谁跟着改**：编排者（排期）；前端。
- **需用户决定**：否。

## P07 `/candidate-signals/{id}/events` 的结构与 `cause` 枚举
- **来源**：T-F17 遗留 1。
- **问题**：契约第 864 行只写了 `[{from, to, cause, at}]`：没写是否用 `{items}` 包装，没写是否分页，`cause` 也没有枚举。前端 mock 用了 `plan_confirmed`，后端不允许这个值。
- **契约现有答案**：
  - 同类接口 `/strategy-instances/{id}/events`（第 854 行）用 §1.2 分页，按 `at desc, id desc` 排序，元素带 `id`。
  - §1.2 规定，只有“少量小集合”才可以直接返回数组。
- **后端行为**：表 `candidate_signal_events`（`db/tables/signals.py` 第 159–177 行）：
  - 列：`id, signal_id, from_state(可空), to_state, cause, detail(jsonb), at`，只追加；
  - `cause` 的 CHECK 只允许 `executability_check` `reason_released` `user` `expiry` `invalidation` `supersede` 六个值。
- **建议裁定**：
  1. 返回值改为 §1.2 分页 `{items, next_cursor}`，排序 `at desc, id desc`，与实例事件一致。
  2. 元素为 `{id, from: candidate_signal_state | null, to: candidate_signal_state, cause: candidate_signal_event_cause, at}`。信号创建时 `from` 为 `null`。
  3. 新增枚举 `candidate_signal_event_cause`，取值与后端 CHECK 完全一致（上面六个），并在 `/meta/enums` 中输出。
  4. drafted→confirmed（确认草案）、dismissed 都用 `user`。不增加 `plan_confirmed` 这类值。
  5. **不返回 `detail`**（隐私从严：其中可能有用户备注或内部求值），以后需要时再单独定义。
- **要改契约**：
  - §7.6 第 864 行；
  - §5 枚举表加 `candidate_signal_event_cause`；
  - `/meta/enums` 的输出清单。
- **谁跟着改**：架构师；后端（接口、枚举输出）；前端（mock 改用六个值，解析 `{items}`，翻译这六个值）。
- **需用户决定**：否。

## P08 列表页的方向冲突只在已加载行之间比较
- **来源**：T-F17 遗留 2，建议加 `conflict_signal_ids`。
- **契约/plan 现有答案**：
  - §6.1 已有原因码 `STRATEGY_CONFLICT`（第 706 行）。
  - plan 2.5.9 第 750 行的定义是“本人启用的其他策略对同一证券给出相反方向的候选信号”。
  - 后端枚举 `ReasonCodeSpec` 中已有该原因码。
- **建议裁定**：不加字段。冲突由系统在服务端对全部信号计算，并作为 `STRATEGY_CONFLICT` 原因挂在各信号的 `reason_ids` 上。列表页改为通过 `GET /non-executable-reasons?signal_ids=`（已有，≤100，不分页）读取原因，判断是否冲突，结果天然完整，不受分页影响。可选补一句契约说明：`STRATEGY_CONFLICT` 的 `evidence` 中写明对方信号的 id。不新增 `CandidateSignal` 字段。
- **要改契约**：可选：§6.1 `STRATEGY_CONFLICT` 行补“evidence 含对方 signal_id”。
- **谁跟着改**：前端（改为按原因码判断）；后端（生成该原因时写 evidence）。
- **需用户决定**：否。

## P09 不可执行原因缺 `security_code`/`name`
- **来源**：T-F17 遗留 3。目前前端按 `signal_id` 逐个请求信号（N+1）。
- **契约现有答案**：`/today.released_reasons`（第 778 行）的元素**已经包含** `security_code`、`name`。`NonExecutableReason`（第 867 行）没有这两个字段。
- **后端行为**：表 `non_executable_reasons` 只有 `signal_id` 和 `user_id`，没有证券列，需要联查 `candidate_signals` 取得。接口还没有实现。
- **建议裁定**：给 `NonExecutableReason`（列表与详情）兼容地加只读字段 `security_code`、`name`。这样口径与 `/today.released_reasons` 一致，由服务端联查，不加表列。数据只属于用户本人，没有隐私问题。
- **要改契约**：§7.6 第 866–867 行。
- **谁跟着改**：架构师；后端；前端（去掉逐个请求）。
- **需用户决定**：否。

## P10 `BLOCKLISTED` 能否手动解除
- **来源**：T-F17 遗留 4。
- **契约现有答案**：
  - §6.1 第 703、707 行：`BLOCKLISTED`、`USER_MUTED` 的“可手动解除”是“是（通过 `/restrictions`）”。
  - 第 855 行：删除限制后，系统会重新检查相关原因。
  - 第 868 行：`/release` 只允许 `<host>=false` 的原因。
- **后端行为**：`schemas/enums.py` 第 850 行中，`BLOCKLISTED` 的 `manually_releasable=True`，并带 note“通过 /restrictions”，`/meta/enums` 会输出这条 note。表 `non_executable_reasons.<host>` 默认为 `true`。
- **建议裁定**：前端现在的做法正确：不显示“手动解除”，改为引导到禁投/屏蔽名单去移除。契约补一句明确说明：
  - 这两类原因的 `<host>=true`，只能通过删除 `/restrictions` 来解除；
  - 直接调用 `/release` 返回 `409 REASON_NOT_MANUALLY_RELEASABLE`。

  这样可以避免“名单仍在、原因却已解除”的不一致，安全从严。
- **要改契约**：§6.1 第 703、707 行的备注，或 §7.6 第 868 行。
- **谁跟着改**：架构师；后端（`/release` 校验）；测试。
- **需用户决定**：否。

## P11 跟踪统计是否显示全站
- **来源**：T-F17 遗留 5。
- **契约/plan 现有答案**：
  - plan 问题 14（第 3148 行）已定：全站匿名汇总**只对登录用户在策略页展示**；单用户期间全站等同本人。
  - plan 第 1079 行：全站汇总只含策略级聚合数字，不含任何用户或个股持仓信息，不做对外宣传与排名。
  - 契约第 842 行的响应带有 `scope: "mine" | "site"`，但**没有定义请求参数**。
- **后端行为**：只有 `strategy_tracking_stats` 表规划，接口还没有实现。
- **建议裁定**：
  - 信号详情页按现状只显示 `mine`。
  - 全站统计按 plan 在策略页展示，不新增展示位置。
  - 契约补请求参数 `?scope=mine|site`，默认 `mine`。`site` 只返回策略级聚合，样本不足时沿用 `Stat` 的“样本不足”标注。
  - 本版不加人数阈值等新规则。
- **要改契约**：§7.4 第 842 行补 `?scope=`。
- **谁跟着改**：架构师；后端（T-B27）；前端（策略页接入时使用）。
- **需用户决定**：否（plan 已定）。

## P12 多个 `signal_ids` 怎么合并
- **来源**：T-F18 遗留 1。
- **契约/plan 现有答案**：
  - §7.7 第 893 行只规定 `{signal_ids: uuid[](≥1)}`。
  - plan 第 628–629 行：建议卡的 `candidate_signal_ids` 与 `executable_signal_ids` 都属于同一证券。
  - plan 第 750、1139 行：方向冲突时“不自动拟定草案，由用户选择”（`STRATEGY_CONFLICT`）。
- **后端行为**：表 `plan_drafts`：
  - 单个 `security_code`（非空）、单个 `action`、单个可空的 `instance_id`；
  - `cardinality(signal_ids) >= 1`；
  - 正文不可变。

  也就是说，一份草案只能有一只证券、一个动作。
- **建议裁定**：
  1. `signal_ids` 必须全部属于本人、同一 `security_code`、同一 `proposed_action`（有 `t_leg` 时 `t_leg` 也须相同），否则返回 `400 VALIDATION_ERROR{field:"signal_ids"}`。
  2. 反向信号不能合并，它们本来就会带 `STRATEGY_CONFLICT`，所以返回已有的 `409 SIGNAL_NOT_EXECUTABLE{reason_ids}`。
  3. 来自多个实例时，`instance_id` 为 `null`。
  4. 不定义跨策略的“合成结论”（plan P4：不合并结论）。

  前端入口目前只传单个信号，可以保持现状。
- **要改契约**：§7.7 第 893 行 `POST /plan-drafts`。
- **谁跟着改**：架构师；后端；前端 mock（加同向校验）；测试。
- **需用户决定**：否。

## P13 `chosen_qty` 的整手规则
- **来源**：T-F18 遗留 2。契约只有 `qty_range.lot`。
- **契约/plan 现有答案**：
  - plan 2.5.8 第 700 行：数量“向下取整到交易单位（主板、创业板 100 股；科创板 ≥ 200 股后按 1 股递增【规则以交易所为准】）”。
  - 第 706 行：卖出上限为可卖数量。
- **后端行为**：`config/market_rules.yaml` 已有 `lot.buy_lot: 100`、`star_min_buy: 200`、`star_step: 1`、`bse_min_buy: 100`、`bse_step: 1`（科创板递增与北交所两项标【待核实】，北交所 V1 不扫描）。草案保存了 `market_rule_version_id`。
- **建议裁定**：不加字段，只写清语义：
  - `qty_range.lot` 是**买入递增单位**：主板、创业板、ETF 为 100；科创板为 1。
  - `qty_range.min` 不低于起买量（科创板 200）。
  - 确认时，服务端按草案的 `market_rule_version_id` 校验：
    - 买入/加仓：`chosen_qty ≥ 起买量`，且符合递增单位；
    - 卖出/减仓：`chosen_qty ≤ sellable_qty`，不足一手的零股只能连同全部余量一次卖出【以交易所为准】。
  - 不满足时返回 `400 VALIDATION_ERROR{field:"chosen_qty", min_buy, step}`。这一项与“超出区间需确认偏离”（`422 DEVIATION_ACK_REQUIRED`）分开：违反交易规则不能靠确认偏离绕过，安全从严。
  - 前端可以继续只做提示，以服务端校验为准。
- **要改契约**：§7.7 第 894 行 `PlanDraft.qty_range` 说明，以及第 895 行 confirm 的错误列表。
- **谁跟着改**：架构师；后端（确认校验）；研究员（核实科创板递增与零股规则）；前端（按 details 显示提示）。
- **需用户决定**：否。

## P14 expired 草案能否重新生成、新旧是否关联
- **来源**：T-F18 遗留 3。
- **契约现有答案**：
  - §7.7 第 894 行（v0.2.7）与补充裁定 #17（第 65 行）：“`stale` 或 `expired` 的草案不能修改；重新生成就是用原草案的 `signal_ids` 再调 `POST /plan-drafts`，原草案保持不变，两者之间不建关联”。
  - 第 893 行：信号状态不是 `drafted`/`released` 时返回 `409 INVALID_STATE_TRANSITION`。
- **建议裁定**：已有答案，不加 `superseded_by`。补一点说明：原信号已经过期或失效时，重新生成会按第 893 行返回 409，前端提示“信号已失效”即可。
- **要改契约**：无。
- **谁跟着改**：前端（处理 409 的文案）。
- **需用户决定**：否。

## P15 放弃草案的 `note` 不回显
- **来源**：T-F18 遗留 4。
- **契约现有答案**：第 896 行 `POST /plan-drafts/{id}/discard` 的请求体为 `{note}`，没有长度限制，也没写存在哪里。`PlanDraft` 中没有这个字段。
- **后端行为**：表 `plan_drafts` 没有 note 列，触发器只允许修改 `status`/`status_changed_at`，也没有草案事件表。**按现在的表结构，note 无处可存。**
- **建议裁定**（隐私从严、改动最小）：删除放弃接口的 `note`，请求体改为 `{}`；老客户端如果还发 `note`，服务端忽略，不报错。前端去掉备注输入框。

  如果以后确实需要记录放弃原因，再单独定义存储和长度（≤200），本版不做。`/candidate-signals/{id}/dismiss` 的 `{note}` 有同样问题，建议同时审视。
- **要改契约**：§7.7 第 896 行。
- **谁跟着改**：架构师；后端；前端（去掉输入框和 mock 中的 note）。
- **需用户决定**：否。按默认删除即可；只有用户明确想保留“放弃原因”时才需要决定。

## P16 草案没有策略名，也没有链接回建议
- **来源**：T-F18 遗留 5。
- **契约现有答案**：`PlanDraft` 有 `signal_ids`，`CandidateSignal` 带 `strategy_name`、`instance_id`，可以通过来源信号跳转。
- **建议裁定**：不改。前端在详情页通过来源信号显示策略名并跳转，不新增字段。
- **要改契约**：无。
- **谁跟着改**：无（前端保持现状）。
- **需用户决定**：否。

## P17 `/plans/{id}` 只有占位页
- **来源**：T-F18 遗留 6；review-fixes-frontend m4。
- **契约现有答案**：§5 `Notification.target.route` 规定 `plan → /plans/{id}`；§7.7 有 `GET /plans/{id}`。plan 问题 59 的记录是：`/plans` 的完整结构还没有定义，`TodayPlanTrigger` 先作为子集。
- **建议裁定**：契约本轮不改。占位页是正确的过渡做法。计划详情页等计划接口任务（定义 `/plans` 完整结构）完成后再接入。
- **要改契约**：本轮无，留给后续 `/plans` 结构任务。
- **谁跟着改**：编排者（排期）；架构师（后续定义 `Plan`）；前端。
- **需用户决定**：否。

## P18 `INVALID_STATE_TRANSITION` 只有通用文案
- **来源**：T-F18 遗留 7。
- **契约现有答案**：§6.0 第 654 行与 §4 第 431 行规定 details 为 `{from, to, allowed}`。
- **建议裁定**：已有答案。前端按 `details.from` 区分文案，例如 `from=confirmed` 时显示“该信号已被确认为计划”，不新增错误码。
- **要改契约**：无。
- **谁跟着改**：前端。
- **需用户决定**：否。

## P19 只有 pending 能放弃，其余返回 409
- **来源**：T-F18“需要谁做什么”中对 mock 的说明。
- **契约现有答案**：§6.0 第 662 行：`pending→confirmed/discarded（用户）`。其他状态放弃即为非法跃迁，返回 `409 INVALID_STATE_TRANSITION`。
- **建议裁定**：与契约一致，不改。
- **需用户决定**：否。

## P20 拿不到 Date 头时不传 `form_started_at`
- **来源**：review-fixes-frontend m1。
- **契约现有答案**：补充裁定 #11（第 25 行）：`form_started_at` 可选，不传就不做最短填写时间检查。
- **建议裁定**：前端做法与契约一致，不改。
- **需用户决定**：否。

## P21 未排期的评审项
- **来源**：review-fixes-frontend 的“未处理”：review-8249d6e m2/m3（mock 限速与待审核上限、`website` 非字符串），review-7afbc06 m1/m2/m3/m5。
- **结论**：这些是前端或 mock 的质量问题，不是契约待定项。由编排者排期，契约不改。
- **需用户决定**：否。

---

## 契约 v0.2.9 建议改动汇总（架构师）
1. 第 41 行 U3 改为已定；§7.2 `/portfolio` 规定无行情行的可空性，加 `security_type|null`、`estimated`；§5 `TerminalRow.holding` 同步（P01、P02）。
2. §7.6 events 改为 §1.2 分页 `{items}`，元素带 `id`，新增枚举 `candidate_signal_event_cause`（六个值，与后端 CHECK 一致），不返回 `detail`（P07）。
3. §7.6 `NonExecutableReason` 加 `security_code`、`name`（P09）。
4. §6.1 / §7.6：`BLOCKLISTED`、`USER_MUTED` 调用 `/release` 返回 409，只能通过 `/restrictions` 解除（P10）。
5. §7.4 tracking 加 `?scope=mine|site`，默认 `mine`（P11）。
6. §7.7 `POST /plan-drafts`：同一证券、同一动作（及 `t_leg`），否则返回 400（P12）。
7. §7.7 `qty_range.lot` 语义，以及 confirm 的整手校验 400（P13）。
8. §7.7 discard 去掉 `note`（P15）。
9. 可选：§6.1 `STRATEGY_CONFLICT` 的 evidence 写明对方 signal_id（P08）。

## 需要用户做产品决定的项
无硬性决定。P15 默认删除放弃备注；只有用户想保留“放弃原因”时才需要决定。
