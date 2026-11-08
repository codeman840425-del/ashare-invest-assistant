# T-B46-47 前端待定项裁定（契约 v0.2.9 #31）

架构师 · 2026-11-01（America/Denver）
来源：`T-B46-47-frontend.md` 中的“待定”。第 1–7 条是待定项，第 8–9 条是说明，也一并给出结论。
docs 提交：**`1d02980`**，只在本地，未推送。只改了 `docs/api-contract.md` 和 `docs/plan.md`，用 pathspec 提交。
- 契约版本号不升。变更表追加第 #31 行，标注“v0.2.9 内，T-B46-47 前端待定；评审 5969886”。
- plan 第 9 节新增问题 87、88、89，接在当前最大号 86 之后。
- 提交前确认这两个文件没有别人未提交的改动。
- `check_contract.py` 通过；`check_code_namespaces.py` 通过；`contract_md.enums()` 共 84 项，与 HEAD 相同，没有新增枚举。
- gitleaks：`range HEAD~1..HEAD` 命中 0。另外对两个文件分别扫了改前和改后的全文，都是 10 条既有的 S7-statement-header，没有新增。
- 原则：字段名以后端现有实现（0f8129b，T-B48）为准，没有改字段，也没有改枚举。凡是产品取舍，都取最保守的做法，并登记到 plan 第 9 节。

## estimated 最终按哪一方
**按裁定 R6**，不按 §7.2 U3 原句。
- 顶层没有 `estimated`，是否估算只看持仓行上的 `estimated`。
- 非可转债持仓缺现价时按成本估算，行上 `estimated=true`，标“估算”。
- §7.2 原句“其他行 `estimated=false`”已改为：“有现价的行为 `estimated=false`；在主数据中但缺现价的行同样为 `estimated=true`”，并注明出处是 #31。plan 第 9 节测试第 2 条同步修改。
- 后端字段名（`security_type`、行级 `estimated`、无顶层字段）在 0f8129b 中已经与此一致。后端要改的是取价来源和 `data_status`，见第 1 条。

## 逐条裁定
| # | 一句话结论 | 前端 | 后端 |
|---|---|---|---|
| 1 | R6 与 U3 的矛盾按 R6 处理：有现价才是 `estimated=false`；任一估算行，或除 `exposure.sector` 外的任一缺口（含 `cash`），都使 `data_status=partial`；估算行的 gaps 键沿用后端现有的三个，reason 一律为 `no_source` | 只看行级 `estimated`（已做到）；mock 中无现金记录账户的 `data_status` 改为 `partial`（评审 m1） | ① 现价第 1 步读库内最近一个交易日的日线收盘价，只读不拉取；第 2 步读快照参考价；② 不再因为 `exposure.sector` 一项缺口就降为 `partial`；③ `cash`、`total_assets`、`cost_price`、`weight_pct` 不为 null，无现金记录时 `cash="0.00"`，并加 `cash`/`user_input_missing` 缺口；④ `positions.price` 的 reason 由 `user_input_missing` 改为 `no_source`；⑤ 更新“不读日线”的 docstring，补测试 |
| 2 | 在主数据中的估算行只标“估算”，不细分原因；原因写在页面说明中，按 gaps 和 `security_type` 区分；不加原因字段（问题 87） | 维持现状 | 无 |
| 3 | `alerts.message` 用固定文案表（契约 §7.9 #31 ②），不带数值、阈值、证书数量或用户名，只允许 `{upstream_code}`、`{dataset_name}` 两个占位 | 原样显示服务端文案（已做到）；mock 文案改用固定表 | 按固定表实现 `alerts[]` |
| 4 | 级别显示为“严重”/“警告”；排序由服务端决定：critical 在前，同级按固定 key 顺序，`errors.*` 按 `upstream_code` 升序，`freshness.*` 按数据集固定顺序（问题 88） | 维持现状（已保持服务端顺序） | 按上述规则排序，并补测试 |
| 5 | 14 天内到期用 `licence.expiring`，条件是证书状态不是 `expired` 且 `0 ≤ days_left ≤ licence_days_left_warning`；每个 key 最多一条，按证书聚合；同一 key 同时满足两级时只出 critical | mock 的 key 改为 `licence.expiring`，并去重（评审 m3）；React key 可改为 `` `${a.key}-${i}` ``（nit） | 按上述规则实现 |
| 6 | 不新增心跳时间字段。`heartbeat` 只在 leader 不为 null、且 §8 ingest 心跳判定为 stale 或 unknown 时出；leader 为 null 时只出 `leader` | 可补一个 mock 场景：含 `heartbeat` 告警（critical）；非必需 | 实现 `heartbeat` 告警 |
| 7 | 逐周期显示“数据不足”的条件：不在 `suitable` 中、有该周期的 `data_missing` 封顶、且**没有** gate 封顶（gate 优先）；整体显示“数据不足”的条件：`suitable=[]` 且至少一个周期显示“数据不足”，否则显示“—”；不出现“都不适合”（问题 89） | `horizonDataMissing` 排除有 gate 封顶的周期，`noSuitableForLackOfData` 改为基于它判定，补“同一周期同时有 gate 和 data_missing 封顶”的用例（评审 m2） | 无，契约字段不变 |
| 8 | 数据集中文显示名定为：`quotes` 实时行情、`minute_bars` 分钟线、`daily_bars` 日线、`financials` 财务数据、`announcements` 公告、`security_master` 证券主数据 | freshness 表格和 mock 文案改用这组中文名 | 告警文案中的 `{dataset_name}` 也用这组名称 |
| 9 | 认可：默认 mock 保留示例分布，“全部 data_missing”的情形用 `server.use` 测试覆盖 | 无 | 无 |

## 待办汇总
**前端**（小改，可以一次提交）
1. `mocks/handlers.ts`：其他账户 `data_status` 改为 `'partial'`，并改注释。
2. `i18n/horizonCaps.ts`：加 gate 优先判断；`noSuitableForLackOfData` 改为基于 `horizonDataMissing` 判定；补用例。
3. `mocks/ingestAlerts.ts`：
   - key 改用 `licence.expiring`；
   - 每个 key 只出一条，同时满足两级时 critical 优先；
   - 文案改用固定表；
   - 数据集名称改用中文名。
4. `AdminIngestPage`：freshness 行显示中文名；可选：React key 防御、补 heartbeat 场景。

**后端**
1. `/portfolio`（portfolio.py）：
   - 加日线收盘价作为第一个价格来源；
   - `exposure.sector` 一项缺口不再降为 partial；
   - R6 ③ 列出的字段不为 null，并加 `cash` 缺口；
   - `positions.price` 的 reason 改为 `no_source`；
   - 改 docstring，补测试。
2. `/admin/ingest/status`（目前尚未实现）：
   - 按 #31 固定表实现 `alerts[]`，包括 `heartbeat`、`licence.expiring`、每 key 一条、critical 优先、排序；
   - 实现 6 行 `freshness`。

**需要用户或运维确认**：问题 87、89 由用户（产品）确认，可修改；问题 88 由运维和用户确认，T003 实测后与问题 78 一并复核。
