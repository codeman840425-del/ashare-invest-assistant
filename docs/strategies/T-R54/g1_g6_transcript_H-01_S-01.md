# G1–G6 抄录表｜H-01 / S-01（T-R54，G7 前置步骤 A 的仓库内部分；只读，不构成批准）

> **用途与边界**：把仓库里已存的 G1–G6 结果逐条抄录，并判断在 H-01 v3（engine_policy 3）下哪些必须重跑。本表**只抄仓库内文字记录**：未跑回测、未连库、未调麦蕊、未读凭据或私有样本。仓库里没有库内 `strategy_promotion_reviews.gate_results` 原件（导出或截图），所以下面每条结论都只是**后端报告的转述**，不能代替步骤 A 要求的库内只读抄录（T-A109 §5；g7_review §4 A 行）。本表不写批准，不改 lifecycle。用语为「候选信号 / 计划条件」。
>
> 基线：main `00538a1760d704eab6c36789ae36a0784a9566b9`。g7_review 最新稿在未合入的 strat/T-R53@281f524（`docs/strategies/T-R41/g7_review_H-01_S-01.md`）；本表不改它。

## 1. G1–G6 定义（出处）

| 门 | 定义（摘要） | 出处 |
|---|---|---|
| G1 | 规则完整且可解释；纯离场组件按 T-A03 豁免入场/止损 | `card_promotion_gates.md:95-104` |
| G2 | 数据可得：data_needs 在 feature_catalog 内、状态至少 verified_doc，以 feature_spec 为准 | `card_promotion_gates.md:106-114` |
| G3 | DSL 语法安全、白名单、eval_time、无未来函数、价格口径不混用 | `card_promotion_gates.md:116-124` |
| G4 | 参数 schema 完整、default 在范围内、引用参数均已定义 | `card_promotion_gates.md:126-131` |
| G5 | 可交易性与 A 股约束（gate_tradability、涨跌停、T+1、停牌、北交所、交易单位） | `card_promotion_gates.md:133-141` |
| G6 | fixtures 全过（失败即 fail）；120 日历史体检只出警告；max_jaccard 为 null 时最多 warn | `card_promotion_gates.md:143-151`；plan.md:999 |

实现位置（00538a1）：`src/backend/app/strategy/promotions.py:40` `prepare`。
- :94-102 从**库内** feature_catalog 读取状态，作为 G2 输入。
- :115-134 由 preflight 错误分出 G1–G4。
- :137 跑 fixtures。
- :195-206 是 G5。
- :208-212 是 G6：当前 `compare(None, …)` 恒无历史，所以 G6 恒为 warn。

审核绑定在 `version_id` 和 `content_sha256` 上。版本变化（`new_version`）或内容变化（`content_changed`）都会让审核变成 stale（`src/backend/app/strategy/reviews.py:107-114`）；契约见 `docs/api-contract.md:951`。

## 2. 逐条抄录

版本依据：
- H-01 v2 = e3daf66 卡（2026-11-07 19:17 America/Denver），原文冻结在 `cards/history/hold_risk_monitor.v2.md`；v3 = 464edfc（2026-11-10 03:10）。
- policy 2 = T-B84 授权写入的 `config/engine_policy.yaml` 顶层与 hold_risk_monitor 组件版本号（T-B84.md:9）；policy 3 = T-B121 = 17a7c10（main 00538a1 上 :2/:18 为 3）。
- S-01 v1：T-B100 导入的是 055105a 卡（2026-11-09 13:07，8 个 fixture，desc 未标【虚构】）。此后同为 version_no 1 的卡又被 fe2afa5（16:05，desc 标【虚构】）和 4c00ae7（16:36，增 S01-FX9/FX10、改卡头 :6）改过，现行文件有 10 个 fixture。

来源记号：
- **A** = `docs/handover/team/reports/T-B100.md:6-11`：用户库正式导入，原 request_review + execute_review，绑定内容哈希。H-01 review 31605278…，S-01 review ceac5164…。日期 2026-11-09 北京时间，报告提交于 13:16 America/Denver。
- **B** = `docs/handover/team/reports/T-B84.md:8-13`：network=none 隔离库，2026-11-07 19:31 MST，验证行事务回滚，**不是用户库记录**。
- 两份都是后端报告；原始日志与 JSON 不在仓库内，本表未核。

| # | 卡 | 门 | 来源（文件:行） | 对应卡版本 / policy | 结论（转述） | v3 / policy 3 下 | 理由 |
|---|---|---|---|---|---|---|---|
| 1 | H-01 | G1 | A :7；B :10 | v2 / policy 2 | pass | 必须重跑 | v3 是新 strategy_version，旧审核因 `new_version` 而 stale（reviews.py:110-111），G7 只能对 v3 审核代批。实质上，v3 的规则、角色、horizons 与 v2 相同（g7_review H2/H3/H5–H9），预期仍为 pass，但这只是预期，不是证据 |
| 2 | H-01 | G2 | A :7；B :10（剩余键：无） | v2 / policy 2 | pass | 必须重跑 | 同上（stale）。G2 读的是运行时库内 feature_catalog 状态（promotions.py:94-102），状态随库变化；v3 的 data_needs 与 v2 相同（卡 :58-65） |
| 3 | H-01 | G3 | A :7；B :10 | v2 / policy 2 | pass | 必须重跑 | 同上。expr 未变（spec :106-113），但 preflight 在 T-B100 之后被 2e8039b（T-B119）改过，代码也不同 |
| 4 | H-01 | G4 | A :7；B :10 | v2 / policy 2 | pass | 必须重跑 | 同上。params_schema 未变（spec :98-104） |
| 5 | H-01 | G5 | A :7；B :10 | v2 / policy 2 | pass | 必须重跑 | 同上。G5 由 fixtures 与涨跌停截断探针决定（promotions.py:195-206），夹具期望未变 |
| 6 | H-01 | G6 | A :7（warn，no_history，fixtures 11/11）；B :10、:12 | v2 / policy 2 | warn（须 ack） | 必须重跑 | 同上。v3 的 11 个夹具与期望和 v2 相同（g7_review H15），现行代码 G6 恒无历史，预期仍为 warn；ack 须对 v3 审核重做 |
| 7 | S-01 | G1 | A :9 | v1（055105a 内容）/ 与 policy 无关 | pass | 必须重跑（与 H-01 v3 无关） | S-01 的现行卡内容已不同于导入时的内容（见版本依据）。用户库里的审核绑定的是 055105a 内容，与 g7_review 逐条核对的现行卡不是同一份内容。preflight 也在之后被 T-B119 改过 |
| 8 | S-01 | G2 | A :9 | 同上 | pass | 必须重跑（与 H-01 v3 无关） | 同上；而且 G2 读的是库内 feature_catalog 状态 |
| 9 | S-01 | G3 | A :9 | 同上 | pass | 必须重跑（与 H-01 v3 无关） | 同上 |
| 10 | S-01 | G4 | A :9 | 同上 | pass | 必须重跑（与 H-01 v3 无关） | 同上 |
| 11 | S-01 | G5 | A :9 | 同上 | pass | 必须重跑（与 H-01 v3 无关） | 同上；现行卡比导入时多了 FX9/FX10，G5 的夹具输入不同 |
| 12 | S-01 | G6 | A :9（warn，no_history，fixtures 8/8） | 同上 | warn（须 ack） | 必须重跑（与 H-01 v3 无关） | 同上；导入时 8 例，现行 10 例 |

不计入上表的记录：
- 2026-11-09 13:12:55 那次代批（`docs/reviews/T-A109-g7-delegation.md:27`，`ack_warn_gates` 为 G6）是 G7 决定，不是 G1–G6 结果；按 T-A109 §3 不作晋级依据。
- `docs/handover/team/board.md:348`（T-B84 摘要）与 B 是同一来源，不重复计。
- `first_batch_import.md:141-152` 是导入前的研究预判，已注明「以实跑 gate_results 为准」，也不计。

## 2A. S-01 v2 的 G1–G6 重跑占位（T-R55）

编排者裁定：S-01 升 v2（`cards/st_pullback_ma.md` version_no 2；v1 即 055105a 冻结在 `cards/history/st_pullback_ma.v1.md`），重新导入并重跑 G1–G6，不按库内 v1 重核。下表只占位，结论栏留空；导入与重跑由后端/编排者在目标环境做，库内 gate_results 的只读抄录放到收口部署后的只读 SQL 里做，本角色不连库。

| # | 卡 | 门 | 来源 | 对应卡版本 / policy | 结论 | 状态 | 说明 |
|---|---|---|---|---|---|---|---|
| P1 | S-01 | G1 | 无（尚未导入） | v2（T-R55）/ 与 policy 无关 | — | 待导入后重跑；库内抄录待收口部署后只读 SQL | 编排者裁定 S-01 升 v2；库内 v1 审核（055105a）作废，上表第 7 条不得沿用 |
| P2 | S-01 | G2 | 无（尚未导入） | v2（T-R55）/ 与 policy 无关 | — | 待导入后重跑；库内抄录待收口部署后只读 SQL | 编排者裁定 S-01 升 v2；库内 v1 审核（055105a）作废，上表第 8 条不得沿用 |
| P3 | S-01 | G3 | 无（尚未导入） | v2（T-R55）/ 与 policy 无关 | — | 待导入后重跑；库内抄录待收口部署后只读 SQL | 编排者裁定 S-01 升 v2；库内 v1 审核（055105a）作废，上表第 9 条不得沿用 |
| P4 | S-01 | G4 | 无（尚未导入） | v2（T-R55）/ 与 policy 无关 | — | 待导入后重跑；库内抄录待收口部署后只读 SQL | 编排者裁定 S-01 升 v2；库内 v1 审核（055105a）作废，上表第 10 条不得沿用 |
| P5 | S-01 | G5 | 无（尚未导入） | v2（T-R55）/ 与 policy 无关 | — | 待导入后重跑；库内抄录待收口部署后只读 SQL | 编排者裁定 S-01 升 v2；库内 v1 审核（055105a）作废，上表第 11 条不得沿用 |
| P6 | S-01 | G6 | 无（尚未导入） | v2（T-R55）/ 与 policy 无关 | — | 待导入后重跑；库内抄录待收口部署后只读 SQL | 编排者裁定 S-01 升 v2；库内 v1 审核（055105a）作废，上表第 12 条不得沿用 |

## 3. 汇总

- 可沿用 **0**，必须重跑 **12**（H-01 6 条，S-01 6 条），仓库内完全无记录 **0**。
- 12 条都只有后端报告转述，仓库内没有库内原件，都需要库内只读抄录。
- **H-01**：v3 导入后会生成新的 strategy_version，旧审核因 `new_version` 而 stale。G1–G5 的输入（规则、参数、data_needs、夹具）与 v2 相同，预期结论不变；但 G2 还依赖库内特征状态，preflight 代码也已改过，所以只能作为预期。G6 在现行代码下预期仍为 warn，须对 v3 重新 ack。
- **S-01**：与 H-01 v3 和 policy 3 都没有实质关系。policy 3 只改了 hold_risk_monitor 的版本号，gate_tradability 仍为 1。但 S-01 自身有问题：卡在导入之后以同一个 version_no 1 改过内容。
  - 用户库里的审核对应 055105a 内容，与 g7_review 核对的现行卡不一致。
  - 如果把现行卡再导入，importer 会因 fields 不同报 `immutable_card_version_conflict`（`src/backend/app/strategy/cards/persistence.py:118-120`；fields 含 narrative 与 source_hash，:110）。
  - 需要编排者 / 架构师决定：S-01 升 v2 后重新导入并跑 G1–G6；或者按库内 v1 内容重核 g7_review 的 S 行。**T-R55 已裁定前者**：S-01 升 v2，占位见 §2A。
- 代批前仍需：在 v3 导入并跑 seed 之后，对 H-01 v3 和 S-01（按上一条的决定）发起新审核，并由编排者在目标环境只读抄录 `gate`、`result`、`stale`（不抄 detail、股东代码或持仓）。

*T-R54｜策略研究员只读抄录；不改其他文件；用户勾选列不适用。T-R55 补 §2A S-01 v2 重跑占位。*
