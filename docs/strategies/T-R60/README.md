# T-R60：F23 词表与 N-01 组件规格（研究侧交付）

> 版本 v1.0｜任务 T-R60（GitHub issue #4 后继研究单；原申请号 T-R23 已由旧轮使用，本轮从 R60 起）｜2026-11-10 北京时间｜维护：策略研究员
> 定位：给 N-01 `veto_risk_announcement` 一套**可执行、可版本化、可评估**的规格与词表载荷，补齐 F23 在 N-01 一侧的研究缺口。
> 边界先说：**本单不解除 N-01 的 `KEY_DATA_MISSING`**，也不改变 F23 的 `declared` 状态（理由见 §5）。

---

## 1. 交付清单

| 文件 | 内容 | 校验 |
|---|---|---|
| `N-01_veto_risk_announcement.md` | N-01 **组件规格 v1**（规则、时点、缺失与否决、解除条件、优先级、最小证据、已知漏检、9 条验收样例） | `check_n01_spec.py` 第 4–6 项 |
| `f23_lexicon_export.yaml` | 词表 → `app.event_definitions` 载荷（**派生导出**，非第二真源） | 第 1–3 项；由 `export_lexicon.py --write` 生成 |
| `export_lexicon.py` | 派生导出器：校父哈希 → 逐类校验 → 写载荷 | 自校验，失败不写 |
| `sampling_plan.md` | 误判/召回抽样方案（抽样框、标注口径、盲评流程、判定线、统计功效、记录模板） | 第 6 项 |
| `check_n01_spec.py` | 上述全部一致性自检（离线确定性） | — |

自检命令：

```bash
uv run --no-project --with pyyaml==6.0.3 python docs/strategies/T-R60/check_n01_spec.py
```

本轮实测输出：`PASS：词表导出与父词表一致（12 类 / 57 关键词），N-01 规格非策略卡，验收样例 9 条，抽样方案要素齐备`。

## 2. 三个关键决定（附依据，勿被后续误读）

### 2.1 N-01 不写成策略卡

`system_components_T-R15.md` 第 3 行原文：「系统组件由 `engine_policy.system_components` 挂载（plan 2.5.11A），**不是策略卡、不经导入器**，本文无 `strategy-card` 块。」因此本单交付**组件规格文档**，不含 `strategy-card` / `strategy-spec` 块；`check_n01_spec.py` 第 4 项会拒绝任何把 N-01 写成卡片的改动。

> 若团队决定 N-01 改为策略卡（Q-5），当前导入器对 `mount_policy=system_only` 的角色集要求是 `⊆{exit,weakening,counter,invalidation}` 且必须含 `exit|weakening`（`src/backend/app/strategy/cards/preflight.py` 第 162–168 行），**veto 角色会被拒**——那需要先改 §2.5.14/导入器，属架构裁定，不在本单。

### 2.2 词表只有一份真源，本单只做派生导出

- 真源：`docs/strategies/T-R23/f23_lexicon_v2_1.yaml`，冻结 sha256 `15bc3fed…693a1c`；匹配器 `match_f23_v2_1.py` sha256 `68f4a533…0dfcbc0`（旧轮 plan「T-R22 裁定」派生、编排者保守否决裁定后冻结）。
- 本单**不复制第二份可编辑词表**：`f23_lexicon_export.yaml` 由脚本从父文件派生，写入 `parent_sha256`，并在生成与自检两处断言「逐类关键词、否定词、政策规则、去重、窗口」与父文件完全一致。改词表只能改父文件并出新 `version_no`，否则自检失败。
- 理由：两份可编辑词表必然漂移；F23 的计数一致性依赖唯一口径。

### 2.3 `event_definitions` 落地形状（给后端）

载荷六个顶层字段对应 `src/backend/app/db/tables/strategy.py:544` 的列：

| 载荷 | 列 | 值 |
|---|---|---|
| `key` | `key` | `f23_risk_announcement` |
| `version_no` | `version_no` | `1` |
| `source_rule` | `source_rule`(jsonb) | 词表全量（12 类 + 2 政策规则 + 否定/排除/去重/窗口） |
| `direction` | `direction` | `buy`（只阻断买入） |
| `severity` | `severity` | `veto` |
| `dedup_window` | `dedup_window` | `10trading_days` |

`(key, version_no)` 唯一且表有不可变触发器；词表换版必须递增 `version_no` 并递增 feature 的 `feature_set_version`（`feature_spec.md` F23 边界条）。

## 3. N-01 行为一页速览

- **规则**：`f.ann_risk_count_10d > 0` → 买入方向 `vetoed`；持有中只作 `counter`（不触发卖出）。
- **时点**：公告只有日期 → D 09:30 冻结；`t < 09:30` 当日生效，否则次一交易日 09:30（plan「T-R22 裁定」④）。
- **缺失**：`count=null` 或公告源未 `verified_live` → 模板 state 照常、候选照常展示，但买入方向计划草案 `KEY_DATA_MISSING`（`missing=["f.ann_risk_count_10d"]`）。
- **命中优先于缺失**：`count>0` 时直接 `vetoed`，不再报缺失。
- **解除**：字段新快照非空 **且** 公告源 `verified_live`，缺一不解除、不可手动。

## 4. §2.5.14 的适用范围（为什么不是「三个代码块」）

plan §2.5.14 是**策略卡**的导入契约（`strategy-card`/`strategy-spec`/`validation` 三块）。N-01 是系统组件（§2.1），不经导入器，因此：

- 本单**借用** §2.5.14 的机器可读精神（版本化、可校验、可复现、无手改），落地为：词表冻结哈希 + 派生载荷 + 自检脚本 + 规格文档；
- **不**产出 `strategy-card` 块（否则与 `system_components_T-R15.md` 冲突，且会被导入器的 system_only 角色集拒绝）。

若编排者的原意是「N-01 也走策略卡导入」，请按 Q-5 先裁定，再另开单改卡与导入器规则；本单不预判。

## 5. 状态边界（不得宣称已解除）

| 事项 | 本单后 | 还需什么 |
|---|---|---|
| F23 `feature_catalog.status` | 仍 `declared` | 架构师按词表质量证据 + 数据实测裁定升级 |
| N-01 `KEY_DATA_MISSING` | **仍会阻断买入草案** | 公告源达 `verified_live`（plan「T-A19 裁定」两项实测：新鲜度 ≥95%、完整性 10 条漏 0） |
| 复测 T-R58/T-B136 | **输入不变** | 复测方案 §2.3 的剔除口径不含公告，N-01 不进入复测；本单不改变任何复测参数或样本 |

> 说明：编排者提到「复测可执行面的真缺口」。按方案核对，T-R58 的剔除项是北交所/预热/停牌/新股/退市整理/ST 状态不明，**不含公告否决**；N-01 阻断的是**生产链买入方向**（plan §2.5.11A），不是复测输入。本单解决的是生产链的规则可计算性与词表可版本化。

## 6. 误判/召回抽样方案要点（详见 `sampling_plan.md`）

- 抽样框：巨潮公开页、**不按关键词筛选**的连续交易日全量 ≥1,000 条；避开开发样本（`holdout_exclusion_ids.txt`）。
- 两个口径分列：`policy_hit`（生产计数）vs `semantic_truth`（人工真风险），不得混用。
- 流程：命中全查（得 FP）+ 未命中固定种子盲抽 100（得 FN）+ Wilson 区间；单轮、失败即停。
- **统计功效（本单实算）**：1,000 条按 1.37% 命中率只有约 14 条命中；即使零误报，95% 上界约 21.5%，**不能宣称 FP ≤5%**（要 ≥60 条命中 → 约 ≥4,400 条标题）。漏报侧 100 条零漏报只能支撑上界约 3.7%，不能宣称「漏报 0%」。

## 7. 待裁定（请编排者转架构师）

| # | 问题 | 建议 |
|---|---|---|
| Q-1 | 误报判定线冲突：plan「T-R22 裁定」①「≤5%」vs T-R23 v2.1「如实报告不设上限」 | 改为「≥60 条命中样本下 ≤5%，否则如实报告点估计+区间」 |
| Q-2 | 1,000 条样本功功效不足（§6） | 若要 5% 硬线，样本加至 ≥4,400 条；否则按如实报告口径 |
| Q-3 | 问询函/关注函是否算语义真风险 | 按 T-R22 裁定② 计入（与生产口径一致），报告中单列占比供复核 |
| Q-4 | 标题不足（undetermined）处理 | 不计 FP/FN 但单列；占比 >10% 时结论加注 |
| Q-5 | N-01 是否改为策略卡 | 现状是系统组件（§2.1）；若改卡须先改导入器角色集/§2.5.14，另开单 |

## 8. 红线

只公开数据；不调麦蕊（0 次）；不读私有样本/账户/股东代码；不写库；不联网（本单全部离线，只有将来取公开页时才浏览，且逐页礼貌、单线程、间隔 ≥1s）；不提交任何密钥。
