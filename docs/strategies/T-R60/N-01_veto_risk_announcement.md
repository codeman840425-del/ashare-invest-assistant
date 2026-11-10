# N-01 风险公告否决 `veto_risk_announcement` — 组件规格 v1（T-R60）

> 版本 v1.0｜任务 T-R60｜2026-11-10 北京时间｜维护：策略研究员
> **本文不是策略卡，不含 `strategy-card` 块，不经导入器。** 依据 `system_components_T-R15.md` 第 3 行：系统组件由 `engine_policy.system_components` 挂载（plan §2.5.11A），**不是策略卡、不经导入器**。本文是研究侧的组件规格，配合 `f23_lexicon_export.yaml`（词表派生载荷）与 `sampling_plan.md`（误判/召回抽样方案）使用。
> 权威：plan §2.5.11A（N-01 行，L920；组件表 L905）、§9 C(4)、§2.12.2；`system_components_T-R15.md` §N-01；`feature_spec.md` F23；plan「T-R22 裁定」（词表 v1 口径）；`docs/strategies/T-R23/`（v2.1 冻结词表）；契约 §6.1 原因码（22 个，不新增）。

---

## 1. 身份与挂载

| 项 | 值 | 出处 |
|---|---|---|
| key | `veto_risk_announcement` | plan L905 |
| 维度 | `news`（`RuleRef.dimension` 必填） | plan §2.5.14 H⑮、L1166 |
| 挂载 | `engine_policy.system_components`；**不经导入器、不是策略卡** | `system_components_T-R15.md` L3；plan §2.5.11A |
| 作用对象 | 所有带买入动作的模板（veto）；已持有证券（counter） | plan L905 |
| 方向 | **只阻断买入/加仓**；不阻断卖出，不触发卖出 | plan L905、C(4) |

## 2. 规则

- **唯一规则**：`f.ann_risk_count_10d > 0` → 买入方向 `vetoed`（state 由组件改变，plan §2.5.11A）。
- 持有中：同一条命中只作 **counter**（反证并列展示，不抵消离场、不触发卖出；与 H-01 结论并列）。
- 计数口径：近 **10 个交易日**内、满足 F23 可交易时刻（§4）的「命中条数」；**每条公告最多计 1**（命中多个类别也只计 1，类别列表并记）。
- 去重键：`nr`（公告链接）为主；次键 `(security_code, 归一化标题去版本后缀, 生效日)`。版本后缀正则见词表 `dedup.version_suffix`（更正后/修订稿/修订版/更新后/英文版/更正）。
- 词表：`f23_lexicon_v2_1`（12 个类别 + 2 条政策规则，57 个基础关键词 + 2 个组合类型），冻结 sha256 `15bc3fed…693a1c`；匹配器 `match_f23_v2_1.py` sha256 `68f4a533…0dfcbc0`。载荷见 `f23_lexicon_export.yaml`（派生自父词表，不新增第二真源）。

## 3. 与模板 state 的关系（优先级）

1. 模板 state 先由模板规则决定；N-01 命中且方向为买入 → 覆盖为 `vetoed`。
2. **N-01 命中优先于 N-01 缺失**：命中时直接 `vetoed`，不再报 `KEY_DATA_MISSING`。
3. 与其他组件原因并列：`reason_codes` 全部列出、不去重合并、不互相抵消，各自独立解除（`system_components_T-R15.md` §共同优先级 2）。
4. 卖出/减仓方向：N-01 不阻断、不触发；持仓只加 counter。

## 4. 时点（可用性）

- 公告源 `/hsstock/announcement/{code}` **只有日期**（`t`、`zt`、`nr`、`jb`、`lx`），交易日盘后更新（feature_spec F23 来源；V7 GAP5 实测）。
- **生效日规则（plan「T-R22 裁定」④，逐字执行）**：F23 每日冻结在 D 09:30。
  - 交易日 D 的公告时间 `t < 09:30`（含盘前）→ **D 09:30 生效**；
  - `t ≥ 09:30`（含盘中、午休、11:30/15:00 边界、盘后）或非交易日 → **次一交易日 09:30 生效**；
  - 只有 `t` 与 `first_seen_at` 都未知时才记 null（不猜）。
- 口径实现：`available_from = max(t, first_seen_at)` 规整到上述生效时刻；`first_seen_at` 取首次入库时刻。
- 无未来数据：评估日 D 只计 `available_from ≤ D 09:30` 的公告。

## 5. 缺失与否决（阻塞关系）

| 情形 | 结果 |
|---|---|
| `f.ann_risk_count_10d = 0` | 不命中；买入方向不被 N-01 阻断 |
| `f.ann_risk_count_10d > 0` | 买入方向 `vetoed`；持有中 counter |
| `f.ann_risk_count_10d = null`（公告缺失/过期/数据源不可用） | 模板 state 照常（可为 `entry_ok`），候选照常展示，但**买入方向计划草案被 `KEY_DATA_MISSING` 阻断**，`missing=["f.ann_risk_count_10d"]` |

- **解除条件（`kind=expr`，缺一不解除、不可手动解除）**：① 该字段在新快照中非空；**且** ② 公告数据源 `feature_catalog.status = verified_live`。
- 卖出方向不受影响（不因公告缺失而阻断卖出）。

> **本单边界（重要）**：词表与组件规格到位只解决「规则可计算、词表可版本化」。**F23 当前仍为 `declared`，N-01 的 `KEY_DATA_MISSING` 不会因本单解除**——解除条件 ② 要求公告源 `verified_live`，须由 plan「T-A19 裁定」两项实测（新鲜度 ≥95%、完整性 10 条漏 0）达成后另行升级。本单不得宣称已解除。

## 6. 最小证据

| 项 | 要求 | 状态 |
|---|---|---|
| `f.ann_risk_count_10d` | 按日（D 09:30 冻结）的计数 | feature_spec F23 已定义；数据源 `declared` |
| 词表版本 | 冻结 + 哈希 | v2.1 已冻结（本单派生载荷） |
| 公告源新鲜度 | d 日公告 d+1 09:00 前可取 ≥95% | 待 T-A19 第 4 项实测（T-R26 协议在 tb 轮） |
| 公告完整性 | ≥10 条已知风险公告漏 0 | 待 T-A19 第 5 项实测 |
| 误判/召回 | 见 `sampling_plan.md` | 待执行（本单出方案） |

## 7. 已知漏检与预计误报（不作隐瞒；均来自 v2.1 冻结记录的披露）

**已知漏检（gap，v2 再细化）**：
1. 标题含「澄清」整条排除——真实风险公告若带「澄清」字样会被漏。
2. 中介机构名单不全——以机构名开头的公司公告可能被前缀排除误伤。
3. `title_insufficient.yaml` 的 5 条（标题不足以判控制人减持）在 v2.1 改为政策命中；但标题本身不可判的情形仍可能漏。
4. 依赖正文才能识别的风险（标题只写「关于某事项的公告」）一律漏——这是**标题级词表的结构性上限**，不是 bug。

**预计误报（政策保守否决，非事实判断）**：
1. `inquiry_transfer_policy`：含「询价转让」一律命中——撤销、终止、不实施、非控股股东主体的询价转让也命中。
2. `concert_change_policy`：控制人/一致行动人 + 协议到期/解除 + 权益变动——可能只是不再合并计算、并无减持。
3. 上述两类是**有意保守**（plan「T-R22 裁定」②：只阻断买入/加仓，偏保守可接受），误报率由 `sampling_plan.md` 如实量化，不设上限（v2.1 裁定）——与旧口径「误报率 ≤5%」冲突，见 `sampling_plan.md` §7 Q-1。

## 8. 验收样例（规格级，不是导入器 fixtures）

> 所有数值/证券为**虚构**或公开代码；用于验收组件行为，不导入 `strategy-card`。判定由规则确定性给出。

| # | 场景 | 输入 | 期望 |
|---|---|---|---|
| N01-E1 | 买入方向命中 | `count=1`，无持仓，模板 state=`entry_ok` | state 覆盖为 `vetoed`；`rule_refs` 含 N-01 的 veto 且 `passed=true` |
| N01-E2 | 买入方向未命中 | `count=0`，无持仓 | state 保持 `entry_ok`，N-01 不产出原因 |
| N01-E3 | 持有中命中 | `count=2`，持仓 1000 股 | 不触发卖出；`counter_evidence` 加一条 N-01 反证；state 由模板规则决定 |
| N01-E4 | 数据缺失（买入） | `count=null`，公告源未 verified_live | state 照常 `entry_ok`，候选展示；`KEY_DATA_MISSING`（`missing=["f.ann_risk_count_10d"]`），解除条件两条 |
| N01-E5 | 数据缺失（卖出） | `count=null`，持仓，模板 `exit_signal` | 卖出不受影响；**不报** `KEY_DATA_MISSING` |
| N01-E6 | 命中优先于缺失 | `count>0` 且源状态未 verified_live | 直接 `vetoed`；不报 `KEY_DATA_MISSING` |
| N01-E7 | 时点边界 | D 日 09:29 公告 / 09:30 公告 | 前者 D 09:30 计；后者次一交易日 09:30 计 |
| N01-E8 | 去重 | 同一 `nr` 重复入库 2 次 | 只计 1 条 |
| N01-E9 | 多类别 | 一条公告命中 2 个类别 | 计 1 条；类别列表并记 |

## 9. 与词表载荷的对应（给后端）

`f23_lexicon_export.yaml` 顶层即 `app.event_definitions` 一行（`T60` 版载荷）：

| 导出字段 | 表列（`strategy.py:544`） | 值 |
|---|---|---|
| `key` | `key` | `f23_risk_announcement` |
| `version_no` | `version_no` | `1` |
| `source_rule` | `source_rule` (jsonb) | 词表全量（类别/关键词/否定/排除/政策规则/去重/窗口） |
| `direction` | `direction` | `buy` |
| `severity` | `severity` | `veto` |
| `dedup_window` | `dedup_window` | `10trading_days` |

- `(key, version_no)` 唯一且不可变（表触发器）；改词表须出新 `version_no`。
- 后端只按 `source_rule` 计算，不自行改词；词表版本变化须递增 `feature_set_version`（feature_spec F23 边界条）。
