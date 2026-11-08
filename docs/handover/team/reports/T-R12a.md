# T-R12a：PB 时点键 + 现金流主备字段（策略研究员）

研究员 · 2026-11-02 11:00（Asia/Shanghai）。依据：`/workspace/team/reports/T-R12-rulings.md`（②③④）、`docs/plan.md` 2.12.1“财务按时点自算”（第 1178–1189 行，其中经营现金流字段为第 1184 行、PB 为第 1185 行；plan 提交 6efedef）、plan 第 1495 行 `market.financial_derived`、T-B55 行。
未调用麦蕊接口；未读取证书；未改 src/tests/deploy/config/CI/plan；未 git commit（待架构师代提交）。

## 1. 改动清单

| 文件 | 版本 | 章节 | 改动 |
|---|---|---|---|
| `docs/strategies/feature_spec.md` | v1.1.0 → **v1.1.1** | 文件头 | 版本、键总数 46 → 48，依据加 T-R12 裁定 |
| 同上 | | §1.1 | 财务行的 plan 行号改为 1175、1178–1189；规则 4 加“PB 改用 F47/F48” |
| 同上 | | §7A 前言 | 键与 `financial_derived.metric` 的对应加 `f.pb_pit`↔`pb`（plan 第 1495 行）；范围改为 7 个键；麦蕊因子 `pb` 只作对照 |
| 同上 | | §7A.0 | 现金流行改为“已裁定”的主备规则（删去“在架构师确认前……”）；C2 注明 F44/F47 共用；C3 写明按分量 coalesce 并记 `basis.ocf_field`；金融类说明加 F47/F48；时点总结加 F47/F48 |
| 同上 | | §7A F45 | 来源字段改写为已裁定的主备字段；边界“都空 → null，不用 0 补”；新增 basis 行（含 `ocf_field`） |
| 同上 | | §7A **新增 F47、F48** | `f.pb_pit`、`f.pb_pit_ind_pct`（见第 2 节） |
| 同上 | | §7B R5 | F42–F46 → F42–F48 |
| 同上 | | §7C | S1、S5、结尾一句话的键范围改为 F42–F48；S2 增补 PB 覆盖率**建议值**（待确认，见第 5 节） |
| 同上 | | §8 | 非正式键计数 46 → 48；注明 `f.pb` 与 `f.pb_pit` 近名 |
| 同上 | | §11 | V5/V5b/V5d/V5f/V9 加涉及的 F47/F48；V5c 改为“字段已裁定、只剩实测”；**G3 标已解决**（引 plan 2.12.1 第 1185 行与 T-R12-rulings.md ③） |
| 同上 | | §12 | 表加 F47、F48 行，F45 来源改为 coalesce；合计改为 **48 个，P0 47 个**（分类器 15 + 策略 25 + L-01 时点财务 7），P1 1 个；YAML `feature_spec_version: "1.1.1"`，F45 加 `field_rule`，新增 F47、F48 两条 |
| 同上 | | §13 | A5、C9、C11 标已处理；C10 标已解决 |
| 同上 | | 版本记录 | 新增 1.1.1 行 |
| `docs/strategies/catalog.md` | v0.3.2 → **v0.3.3** | 标题、变更记录、L-01 | 加 v0.3.3 变更行；L-01 的“调度与接口”“特征键”加 `f.pb_pit_ind_pct`/`f.pb_pit`，删除“PB 分位没有正式键，待架构师裁定”；写入 PB ≤ 0 与现金流主备规则；线上切换条件 ① 的键清单加入两个 PB 键，② 注明 PB 覆盖率为建议值 |

## 2. PB 公式摘要（F47、F48）

- **F47 `f.pb_pit`** = `close_raw(d) × zgb(d) ÷ E(P)`，单位“倍”，2 位小数。
  - 分子与 F42 取法相同：d 日不复权收盘 `c` × `zgb`（capital 中 `bdrq ≤ d` 且 `next_trading_day(plrq) ≤ d` 的最新一行）；不用快照或因子里的市值。
  - 分母是 balance 中的 `gsmgdqsyhj`，取 T 时可见的最新报告期 P；时点值，不做 TTM；最多回退 15 个月。
  - 时点规则：从 `next_trading_day(plrq)` 09:30 起取最新可见版本；`plrq ≤ jzrq` 的占位行丢弃；重述不回写；回填行只按 `plrq` 计算。
  - 以下情况为 null：E(P) ≤ 0 或缺失（plan 原文）；回退耗尽；d 日停牌或 `zgb` 缺失（沿用 F42）；`delisted`/`missing_from_list`（§1.7）。
  - 银行和保险照常计算，但在 V5b 核对前标待核实（保持 `declared`）。
  - 结果落 `financial_derived`，`metric = pb`，按交易日存。
- **F48 `f.pb_pit_ind_pct`** = `rank_pct_in(f.pb_pit, f.sw_l1)`。规则同 F43：
  - 股票池为 §1.4 池再叠加因子池排除，且 `f.pb_pit` 必须非 null，因此 E ≤ 0 的证券不进入分母。
  - 按申万一级分组；组内 N < 5 → null；`f.sw_l1` 为 null → null。
  - L-01 写成“≤ 0.3”。
  - 这是截面派生值，不落 `financial_derived`。

## 3. 现金流主备规则（落地位置）

规则：每个 YTD 分量取 `coalesce(jyhdcsdxjlxj, jyhdcsdxjlje)`。主字段为空（`'-'` 或缺失）时才用备用字段。按分量把实际所用字段记入 `basis.ocf_field`。两个字段都空时该分量缺失，TTM 现金流和现金流比都为 null，不用 0 补。

落地位置：
- feature_spec §7A.0 来源字段表的现金流行
- §7A.0 分量 C3
- §7A F45：来源字段、边界、basis
- §11 V5c：改为只剩实测项
- §12 汇总表 F45 行
- YAML F45：`derivation` 与 `field_rule`
- §13 C9
- catalog L-01“特征键”

全文已经没有“待裁定”“在架构师确认前”的表述。

## 4. YAML 校验结果

用 `/tmp/yv/bin/python` 逐块提取 ```yaml 代码块，并用 `yaml.safe_load` 解析：
- `feature_spec.md`：1 块（第 879 行起），**解析通过**。共 48 个 `feature_key`，没有重复；P0 47 个、P1 1 个；`feature_spec_version = 1.1.1`。
- `catalog.md`：0 块，没有需要校验的内容。
- 另外运行了 `python3 scripts/ci/check_contract.py`，输出“契约文档对照通过（仅文档）”。本机没有安装 gitleaks，所以没有运行。

## 5. 需架构师确认

1. **§7C S2 的 PB 覆盖率阈值**：我按 PE 的做法补了一条**建议值**：在 `E(P) > 0` 的子集中，`f.pb_pit` 非 null 比例 ≥ 99%。这是新增门槛，已确认的 S1–S6 阈值里没有这一条，需要确认，或者改成“PB 不设覆盖率门槛”。
2. **plan 2.12.1 没有覆盖的 PB 边界情况**（feature_spec 中已按下列方式处理并注明，请确认）：
   - d 日停牌或 `zgb` 缺失时为 null，沿用 F42。
   - E(P) 为极小正数时 PB 会极大：不设上限，也不缩尾，按原值落库。分位排名不受影响，但展示和对照报告里可能出现离群值。
   - 不用每股净资产字段，原因与 §7B R5 相同。
3. **银行、保险的“待核实”标记方式**：做法与 F44 一致，在 V5b 核对前，这两类证券保持 `declared`。如果需要在 `basis` 中加专门的标志字段，请指定字段名。

## 6. 提交说明

- 本次只改了 `docs/strategies/feature_spec.md` 和 `docs/strategies/catalog.md`，另外新建本报告并改了状态文件。
- 工作区中还有其他角色未提交的改动，包括 deploy、scripts/ci、src/backend、src/frontend，这些不是本任务改的。代提交时请只暂存上面两个 docs 文件。
- 非阻塞备注：catalog L-01“逻辑”一句写的是“PE_TTM、PB 分位：行业内分位 ≤ 30%”，没有写明两者是“且”还是“或”。这由研究员在 L-01 正式卡中确定，本次没有改。

---

## T-R12b

<a id="T-R12b"></a>

**任务**：按 plan 2.12.1 的 T-R12a 裁定（提交 de86b99）和 `T-R12-rulings.md`「T-R12a」节修改 strategies 文档。执行人：量化策略研究员，日期 2026-11-01。只改了文档：没有提交 git，没有调用麦蕊，也没有读取证书。

### 改动文件与版本
- `docs/strategies/feature_spec.md`：v1.1.1 → **v1.1.2**。
- `docs/strategies/catalog.md`：v0.3.3 → **v0.3.4**。原 L-01 线上切换条件②写的是“PB 在归母权益 > 0 子集中 ≥ 99%，建议值待确认”，与裁定冲突，所以一并改了。

### feature_spec v1.1.2 改动
1. **§7A.0 新增两个小节。**
   - “边界情况与原因码”B1–B7，对应 plan 边界 1–7：
     - 原因码：`no_valid_bar`、`share_change_pending`、`no_visible_report`、`pre_listing_equity`、`unit_mismatch`。
     - basis 记录项：`share_change_check = unavailable`、`mcap_basis = a_price_total_shares`。
     - 第 6、7 条（不设上限，`pb > 100` 只做离群标记；不用每股字段）改标“plan 已裁定”。
   - “待核实标记 `basis.verify_pending`”：
     - 键级仍用 `feature_catalog.status`。
     - 行级取值 `bank_balance`、`insurance_balance`、`non_a_share_capital`，各自列出适用的 metric 和清除条件。
     - 分位键继承标记。
     - 带标记的值照常落库，并在报告中单列。
     - S2 计算覆盖率时，这些证券从分子和分母同时剔除。
   - basis 新增 5 个字段（plan 第 1543 行）。
2. **F42 / F44 / F47 边界与 basis 同步。**
   - F44 新增 `no_visible_report`、`pre_listing_equity`、`unit_mismatch`。银行、保险的键级状态为 `declared`，行级写 `bank_balance` / `insurance_balance`。
   - F42 新增 `non_a_share_capital`。上市前报告期的 PE 照常计算。
   - **F43 和 F48** 写明继承底层值的 `verify_pending`；F48 的非 null 数只报告，不作门禁。
3. **§7C**
   - S1 补写：V5b、V5c、V5e、V5g 已关闭，即所有 `verify_pending` 已由 T-B05 清除。
   - S2 前言补总则：所有键先剔除 `verify_pending` 非空的证券，分子和分母同时剔除，并单列个数。
   - S2 的 PB 条去掉“建议，待确认”，改成裁定口径：
     - D(d) 剔除权益已知且 ≤ 0 的证券；权益缺失的证券留在 D(d) 中，计为未覆盖。
     - 全市场 ≥ 99%。
     - 申万一级行业组内 D ≥ 5 时，组内 ≥ 95%；D < 5 的行业列出但不考核。
     - `sw_l1` 为空的证券单列。
4. **§11**
   - V5d 补“送转数据源与除权日的先后”（T-B05 ⑧）。
   - 新增 **V5g**（B/H 股股本，T-B05 ⑦）和 **V5h**（币种单位字段，T-B05 ⑨）。
   - V5b、V5e 补写与 `verify_pending` 的对应关系。
5. **§12 YAML**
   - 版本 1.1.2。
   - F42、F44、F47 的 `null_when` 改为带原因码，新增 `verify_pending`、`basis_fields`；F42、F47 新增 `mcap_basis`。
   - F47 新增 `no_cap` 和 `outlier_display`；F43、F48 继承 `verify_pending`；F48 新增 `coverage_gate: report_only`。
   - `pending` 补上 V5e、V5g、V5h。
   - 说明行登记了这些新增的仅说明字段。
6. **§13**：新增 C12、C13、C14，对应 T-R12a 的 3 个开放问题，均标“已裁定”。
7. **plan 行号**：本版新写的引用改用 de86b99 版（1182–1237、1188、1189、1190–1212、1213–1225、1226–1233、1234、1543、833）。旧引用保留，并在括号里注明新行号。

### catalog v0.3.4 改动
- 只改 L-01 线上切换条件 ①②，并补了变更记录：
  - ①：补写“所有 `basis.verify_pending` 已清除”。
  - ②：PB 覆盖率改为 §7C S2 的裁定口径。

### 校验
- `/tmp/yv/bin/python /tmp/tr12a/yv.py feature_spec.md catalog.md`：feature_spec 有 1 个 YAML 块，`safe_load` 通过；features=48，unique=48，P0 47，P1 1，version=1.1.2。catalog 中没有 YAML 块。
- 另做了重复键检查：无重复键。
- `python3 scripts/ci/check_contract.py`：契约文档对照通过（仅文档），rc=0。

### 与裁定冲突或仍不明确（都不阻塞）
1. plan 有两类 null 没给原因码，文中标了【待架构师指定】：
   - 边界 3：实测发现 `zgb` 只含 A 股时；
   - 边界 4：最新可见股本行 `bdrq` 早于上市日。

   原有的 `NP_TTM ≤ 0`、`E(P) ≤ 0`、`zgb` 缺失也没有原因码，本文没有自造。
2. `unit_mismatch`：plan 只写了告警名，本文同时把它用作 `null_reason`。请确认。
3. ROE 的 `pre_listing_equity` 只按所选报告期 P 判断。若 P−4 早于上市，现行做法是按 E(P−4) 正常参与平均；它是否应按缺失处理、改走 single_period，plan 没有写。
4. S1：plan 原文是“V5b、V5e 关闭”。由于 `non_a_share_capital` 也必须清除，本文同时写了 V5g（与 plan 的“所有 verify_pending 已清除”一致）。V5h 不产生标记，所以没有写进 S1。
5. 边界 5 只覆盖 pe/pb/roe 的权益部分。F45、F46 遇到 `unit_mismatch` 时怎么处理，裁定没有写；本文没有扩展。
6. B/H 股的识别字段和币种单位字段名都待 T-B05 实测（V5g、V5h），文中标了“待核实”。

### 提交提示
工作区里还有其他角色未提交的改动（deploy、scripts/ci、src、probes 等）。请只暂存 `docs/strategies/feature_spec.md`、`docs/strategies/catalog.md` 和本报告。

---

## T-R12c

<a id="T-R12c"></a>

**任务**：落地 plan 2.12.1“T-R12b 补充裁定”（提交 1c62952，第 1237–1271 行；§9 问题 96）和 `T-R12-rulings.md`「T-R12b」节。执行人：量化策略研究员，日期 2026-11-01。只改了文档：没有提交 git，没有调用麦蕊，也没有读取证书。

### 改动文件与版本
- `docs/strategies/feature_spec.md`：v1.1.2 → **v1.1.3**，已加版本记录行。
- `docs/strategies/catalog.md`：v0.3.4 → **v0.3.5**。只改 L-01 切换条件①，补 V5d、V5h，并写明 V5g 要求没有 `unavailable` 的行。

### feature_spec v1.1.3 改动
1. **§7A.0**
   - 补原因码：
     - B3：`a_share_only_capital`
     - B4c：`pre_listing_capital`
     - 原第 485 行一段改为：`non_positive_earnings`、`non_positive_equity`、`no_capital_row`、`data_conflict`
   - 新增“原因码总表”，与 plan 表的码、顺序和适用 metric 逐行一致，并写明以下规则：
     - 列表封闭，新增原因码先改 plan；
     - `value` 为 null 当且仅当写了 `null_reason`；
     - 同时命中多个原因时，取表中靠前的一个；
     - 分位键为 null 的原因 `group_too_small` / `input_null` 由 T-B35 记在特征元数据里，不进入 `null_reason` 表。
   - B5 扩到 F45、F46：比值任一分量（含 TTM 用到的任一期）命中 `unit_mismatch`，结果即为 null。
   - `non_a_share_capital` 只打在能识别出 B/H 股的公司上；识别不了的记 `share_class_check = unavailable`。
   - basis 字段新增 `single_period_reason`、`share_class_check`。
2. **F42 / F47**：补齐各边界的原因码，新增 `share_class_check = unavailable`，不按代码段或名称推断。F47 写明报告要单列 `unavailable` 证券数。
3. **F44**：新增 `single_period_reason`，取值 `p4_pre_listing`（P−4 早于上市日按缺失处理，不用招股书补）、`p4_missing`、`p4_non_positive`。原 `reason = prior_equity_nonpositive` 改为 `p4_non_positive`。
4. **F45**：新增 `non_positive_earnings`、`ocf_missing`、`component_missing`、`data_conflict`、`unit_mismatch`。basis 加入 `null_reason`。
5. **F46**：新增 `financial_sector_na`、`component_missing`、`no_visible_report`、`data_conflict`、`unit_mismatch`。basis 加入 `null_reason`。
6. **F43 / F48**：注明分位键为 null 的原因记在 T-B35 元数据，不属于 `null_reason`。
7. **§7C S1**：关闭项改为 V5b、V5c、V5d、V5e、V5g、V5h，并写明关闭条件：
   - V5d：要有结论；如果股本行普遍晚于除权日才可见，就必须接入送转数据，且切换时 `share_change_check` 不能再是 `unavailable`。
   - V5h：确认币种、单位字段名，或确认没有这两个字段；没有时，结论写明“只靠数量级检查”。
   - V5g：没有 `unavailable` 的行。
   - 引用 §9 问题 96。
8. **§11**：V5d、V5h 标为 S1 关闭项并写关闭条件；V5g 加“还有 unavailable 就不算关闭”和单列要求；V5h 的适用键扩到 F45、F46。
9. **§12 YAML**
   - 版本 1.1.3。
   - F42、F44–F47 的 `null_when` 改为只列原因码，并按总表优先级排序。
   - `basis_fields` 加 `share_class_check`（F42、F47）、`single_period_reason`（F44）、`null_reason`（F45、F46）。
   - F45、F46 的 `pending` 加 V5h。
   - F43、F48 加 `null_meta`。
   - 说明行登记了新增的仅说明字段。
10. **§13**：C13 两处“待指定”改为已裁定；新增 C15，记录 T-R12b 的 6 点。

### 校验
- `rg "待架构师指定"`：feature_spec.md、catalog.md 中都没有（rc=1）。
- `/tmp/yv/bin/python /tmp/tr12a/yv.py`：feature_spec 中 1 个 YAML 块，`safe_load` 通过；48 键无重复，P0 47、P1 1，version=1.1.3。catalog 中没有 YAML 块。
- 重复键检查（自定义 SafeLoader）：无重复键。
- `python3 scripts/ci/check_contract.py`：契约文档对照通过（仅文档），rc=0。
- 原因码比对脚本：
  - plan 表抽出 14 个码，总表与 plan 的码和顺序完全一致；
  - 文中 `null_reason = X` 与 YAML `null_when` 的取值都在 14 码内，没有多出来的码；
  - 14 个码在文中都有出现；
  - YAML 各键的 `null_when` 顺序符合优先级；
  - 旧的建议名（`prior_equity_nonpositive` 等）已全部清除。

  `group_too_small` / `input_null` 只作为 T-B35 元数据出现，`p4_*` 只作为 `single_period_reason` 出现。

### 与裁定冲突或仍不明确
1. **F46 `zczj ≤ 0`（资产合计 ≤ 0）在封闭的 14 码里没有对应码。** plan 表只给了 `zczj` 为空时用 `component_missing`。按“新增码先改 plan”的规则，本文没有自定码，只在 F46 和 C15 中注明；YAML 记为 `null_without_code`。这与“value 为 null 当且仅当写了 `null_reason`”矛盾。实际上几乎不会发生，但单元测试需要有个归类。请架构师在 plan 中决定：并入 `component_missing`，或者新增一个码。
2. **`single_period_reason` 同时命中多种时取哪个，plan 没有规定。** 例如 P−4 早于上市日且缺失。本文约定按 `p4_pre_listing` → `p4_missing` → `p4_non_positive` 的顺序取第一个，并标了【本文约定】。请确认。
3. 退市证券（`listing_status ∈ {delisted, missing_from_list}`）的 null 是特征层规则（§1.7）。本文写明它不对应 `financial_derived` 行，不在原因码表中。如果 T-B55 实际会为退市证券写 null 行，需要另行确定用哪个码（可能是 `no_visible_report`）。不阻塞。

### 提交提示
请只暂存 `docs/strategies/feature_spec.md`、`docs/strategies/catalog.md` 和本报告。工作区里其他角色的改动不要动。

---

## T-R12d

<a id="T-R12d"></a>

**任务**：落地 plan 2.12.1“T-R12c 补充裁定”（b85b564，第 1272–1275 行）和 `T-R12-rulings.md`「T-R12c」节。执行人：量化策略研究员，日期 2026-11-01。只改了文档：没有提交 git，没有调用麦蕊，也没有读取证书。

### 改动
`docs/strategies/feature_spec.md` 从 v1.1.3 升到 **v1.1.4**，已加版本记录行，YAML 的 `feature_spec_version` 同步为 1.1.4。`catalog.md` 不受影响，没有改。
1. **F46**：`zczj ≤ 0` 改记 `component_missing`，并注明 T-B55 同时发一条 `data_quality` 告警（不打断计算），供 T-B05 回查。§7A.0 原因码总表第 12 行同步补了这一情形。YAML 中删去 `null_without_code`，改为说明字段 `component_missing_includes`，YAML 说明行同步更新。
2. **F44**：`single_period_reason` 的优先级（`p4_pre_listing` → `p4_missing` → `p4_non_positive`）改标“plan 已裁定（b85b564）”，并附 plan 给出的理由。
3. **退市证券**：§7A.0 总表注和 F47 边界按裁定 ③ 改写：
   - T-B55 不为退市证券补写 null 行，也不新增原因码；
   - `pe_ttm`、`pb` 只在有日线的交易日写行；
   - 退市前的历史行照常计算，并按总表写码；
   - `listing_status` 为 delisted、missing_from_list 时 `f.*` 全为 null，这是特征层（T-B35）规则，与 `financial_derived` 无关。
4. **§13 C15**：删去遗留项和“需先改 plan”的待办，改为 3 点均已由 plan 裁定（b85b564）。
5. **头部**：版本、依据、“不做的事”三行补了 v1.1.4 说明。

### 校验
- `rg "null_without_code|本文约定|待 plan|不自定码|需先改 plan|待架构师指定|遗留|待定"`：在 feature_spec.md、catalog.md 中都没有结果（rc=1）。
- `/tmp/yv/bin/python /tmp/tr12a/yv.py`：feature_spec 中 1 个 YAML 块，`safe_load` 通过；48 键无重复，P0 47、P1 1，version=1.1.4。
- 重复键检查：无重复键。
- 原因码复核：总表仍与 plan 的 14 个码和顺序一致，`null_reason = X` 中没有表外码。
- `python3 scripts/ci/check_contract.py`：契约文档对照通过（仅文档），rc=0。

### 遗留问题
无。

请只暂存 `docs/strategies/feature_spec.md` 和本报告。

---

## T-R12e

<a id="T-R12e"></a>

**任务**：落地 plan 2.12.1「T-R12e 补充裁定」（fdd7fdd，第 1276–1283 行）。`reports/T-R12-rulings.md` 中没有 T-R12e 节，所以只依据 plan 原文，另参考 `docs/mairui-verified.md` ⑦（V5g 样例公司）。执行人为量化策略研究员，日期 2026-11-01。本次只改文档：没有提交 git，没有调用麦蕊，也没有读取证书。

### 改动
**`docs/strategies/feature_spec.md`：v1.1.4 → v1.1.5**（已加版本记录行，YAML `feature_spec_version` 改为 1.1.5）

- **§7A.0**
  - 新增“capital 行可见时间”节（对应 V5i）：
    - 季末行的可见时间取 `max(next_trading_day(plrq), first_seen_at)`。
    - 首次全量回填写入的季末行，按法定披露截止日（Q1 4-30 / H1 8-31 / Q3 10-31 / 年报次年 4-30）计算可见时间，并记 `pit_basis = capital_deadline`。
    - 非季末行照旧按 `plrq`。
    - T-B05 确认 `plrq` 是真实披露日后，取消这条保守规则。
  - B2 中 `zgb` 的取法改为“`bdrq ≤ d` 且可见时间 ≤ d”。
  - B3 和待核实标记表改为按名单识别：名单内打 `non_a_share_capital`，名单外记 `list`，名单接入前记 `unavailable`。
  - 待核实标记表新增 `cdr_unit` 行，并补写它的分位例外和 S2 剔除。
  - basis 字段说明补充 `capital_deadline`、`list`、`cdr_unit` 三个新取值。
- **F42、F47**
  - `zgb` 改按 V5i 规则取可见行。
  - B3 写入 `share_class_check` 的取值（`list` / `unavailable`）。
  - 新增 CDR 条目。
  - basis 列出 `pit_basis`（含 `capital_deadline`）、`share_class_check`、`verify_pending`（含 `cdr_unit`）。
  - F47 回填条目注明 capital 季末行的例外。
- **F43、F48**：池中剔除 `verify_pending` 含 `cdr_unit` 的证券，这些证券在本键上为 null。其他标记的证券照常参与排序。
- **§7C**
  - S1：关闭项增加 V5i、V5j；① 的标记列表加入 `cdr_unit`；V5g 的关闭条件按裁定改写为两项；新增 ④（V5i）、⑤（V5j）两条关闭条件。
  - S2 总则：注明剔除范围含 `cdr_unit`，并按标记分别单列剔除个数。
- **§11**：重写 V5g，新增 V5i、V5j，V5d 加指向 V5i 的说明。
- **§12 YAML**
  - F42、F47：新增 `capital_visibility`、`share_class_check`（替换 `share_class_check_when_unidentifiable`）和 `cdr_unit`；`verify_pending` 加入 `cdr_unit`；`pending` 加入 V5i、V5j；derivation 改为“capital row visible”。
  - F43、F48：新增 `pool_exclude_verify_pending: [cdr_unit]`。
  - 说明行同步更新。
- **§13**：新增 C16。
- **原因码表**：不变，仍为 14 个，与 plan 一致。

**`docs/strategies/catalog.md`：v0.3.5 → v0.3.6**：L-01 线上切换条件①的关闭项加入 V5i、V5j，V5g 的描述同步改写；已加变更说明。

### 校验
- 用 `rg` 检查“待定、待架构师指定、本文约定、null_without_code、遗留、待 plan”：在 feature_spec 和 catalog 中均无命中。只剩两处历史版本记录里的“待确认”，属于历史原文，没有改。
- 用 `/tmp/yv/bin/python` 做 YAML `safe_load`：通过，48 键无重复（P0 47 个、P1 1 个），version 为 1.1.5。重复键检查结果为 no dup。
- 原因码：总表 14 个码的内容和顺序与 plan 第 1237–1262 行逐一一致；全文没有表外码；`null_when` 的顺序符合优先级。
- `python3 scripts/ci/check_contract.py`：契约文档对照通过（仅文档），rc=0。

### 与裁定冲突或不明确的地方（请架构师确认）
1. **V5i 的适用范围**：裁定第一句写“`plrq = bdrq` 或 `plrq` 恰为季末日”，后面又写“非季末的 `bdrq` 照旧按 `plrq` 处理”。本文把两句合起来读，适用条件为：`bdrq` 是季末日，且 `plrq = bdrq` 或 `plrq` 是季末日。由此产生两个待确认点：
   - `plrq = bdrq` 但两者都不是季末日的行，本文按非季末行处理（照旧按 `plrq`）。
   - `bdrq`、`plrq` 是不同季末日时，本文按 `plrq` 所在季末取截止日。
2. **截止日的可见时刻**：裁定只说“按法定披露截止日保守处理”。本文类比第 3 条，取 `next_trading_day(截止日) 09:30`；如果裁定的本意是截止日当天，需要改正。
3. **`pit_basis` 只能写一个值**：同一行 PE/PB 可能同时出现财务分量 `plrq_only` 和 capital `capital_deadline`。plan 没有规定两者如何同时记录，本文没有自定写法。
4. **名单内公司的 `share_class_check` 取值**：裁定只规定名单外记 `list`，名单内只说打 `non_a_share_capital`，本文对名单内公司不写 `share_class_check`。另外，“名单接入前记 `unavailable`”是本文沿用 T-R12b 第 6 条得出的读法。
5. **CDR 与 `security_type` 的关系**：裁定说“`security_type` 目前没有 CDR 取值”，但 plan 的 `market.securities.type` 写有 `stock/cdr/etf/index`，feature_spec §1.4 第 79 行也写“CDR 的 `security_type = cdr`，不在池内”。如果主数据确实标了 `cdr`，F43/F48 的 §1.4 池本来就不含 CDR。本次没有改 §1.4。
6. **V5j 中 `zgb` 按基础股份计的情况**：裁定只写了按 CDR 份数计时的处理（市值 = c × CDR 份数，并清除标记）。按基础股份计时，价格（每份 CDR）× 基础股份是否需要按转换比例换算、何时清除标记，plan 都没有写。
7. **“规则同银行、保险的标记”**：这句话的字面意思像是银行、保险的标记也“不进行业分位”。但 T-R12a 裁定写的是继承标记、照常参与排序，所以本文只对 `cdr_unit` 做分位剔除，银行、保险标记保持原样。
8. **F43/F48 中 `cdr_unit` 证券为 null 的元数据原因**：plan 没有给出原因名（现有原因只有 `group_too_small` / `input_null`），本文没有新增。

请只暂存 `docs/strategies/feature_spec.md`、`docs/strategies/catalog.md` 和本报告。

---

## T-R12f

<a id="T-R12f"></a>

**任务**：落地 plan 2.12.1「T-R12f 补充裁定」（38d7888，第 1284–1298 行），即架构师对 T-R12e 遗留 8 个读法问题的裁定。`T-R12-rulings.md` 中没有 T-R12f 节。执行人为量化策略研究员，日期 2026-11-01。本次只改文档：没有提交 git，没有调用麦蕊，也没有读取证书。

### 改动
**`docs/strategies/feature_spec.md` 从 v1.1.5 升到 v1.1.6**，已加版本记录行，YAML 版本改为 1.1.6。按 8 条裁定逐条落地如下：

1. **V5i（§7A.0“capital 行可见时间”）**
   - 适用条件按裁定原文改写：`bdrq` 为季末日，且 `plrq = bdrq` 或 `plrq` 为季末日。
   - 不满足适用条件的行照旧按 `plrq` 处理，其中包括 `plrq = bdrq` 但两者都不是季末日的行。
   - 回填季末行的截止日改按 `bdrq` 所属报告期取，可见时间 = `max(next_trading_day(plrq) 09:30, next_trading_day(截止日) 09:30)`。
   - B2、F42、F47 和 §11 V5i 已同步。
2. **截止日的可见时刻**：取 `next_trading_day(截止日) 09:30`，写入 V5i 节。
3. **`basis.pit_basis` 改为字符串数组**
   - 可同时含 `plrq_only` 和 `capital_deadline`；没有特例时为空数组或不写。
   - 适用于所有写 `pit_basis` 的键。§7A.0 第 3 条、basis 字段说明、F42/F47 的 basis 和 YAML 都改成了“加入数组”的写法。
4. **`share_class_check` 取值改为 `unavailable` / `list` / `field`**
   - 名单接入前，所有行记 `unavailable`。
   - 名单接入后，所有行记 `list`；名单内的公司另打 `non_a_share_capital`。
   - 将来 capital 有了区分字段，改记 `field`。
   - B3、待核实标记表、F42、F47、§11 V5g、YAML 已同步。
5. **CDR 识别**：`cdr_unit` 改为以 `market.securities.type = cdr` 识别，删除“CDR 名单”和“`security_type` 无 CDR 取值”的说法，与 §1.4 保持一致。
6. **CDR 与分位池**
   - 删除 F43、F48 中“`cdr_unit` 不进池”的两条，以及 YAML 中的池剔除字段。
   - 不新增元数据原因；写明 `cdr_unit` 只影响 F42、F47 和 S2。
   - §11 V5j 的影响键改为 F42、F47。
7. **CDR 总市值**
   - 按 CDR 份数计：`c × zgb`。
   - 按基础股份计：`c × zgb × 每股基础股份对应的 CDR 份数`。转换比例按证券写入配置，并注明来源（招股书或上市公告）。
   - T-B05 确认单位、配置也接入后，清除 `cdr_unit`。
   - 待核实标记、§7C S1 ⑤、§11 V5j、YAML 已同步。
8. **银行、保险标记**：维持原规定，照常参与排序；F48 和待核实标记说明中写明此为 T-R12f 确认。

**§13**：C16 的后续改为“见 C17”，并新增 C17。原因码表不变（14 个）。

**`docs/strategies/catalog.md`**：没有改动，仍为 v0.3.6。L-01 切换条件①中，V5g 写的是“名单已接入、已核实”，V5j 写的是“`cdr_unit` 已清除”，这两项都不涉及 CDR 识别方式、`pit_basis` 或 `share_class_check` 的取值，与新规则不冲突。

### 校验
- **rg 检查**：搜索“待定、待架构师指定、本文约定、null_without_code、遗留、待 plan、pool_exclude_verify_pending”，在 feature_spec 和 catalog 中均无命中。
- **旧写法残留**：`pit_basis = capital_deadline` 只出现在 v1.1.5 的历史摘要、C16 和版本记录里，属于历史原文，不是现行规则。
- **YAML**：用 `/tmp/yv/bin/python` 做 `safe_load`，通过。共 48 键，无重复；P0 47 个、P1 1 个；version = 1.1.6。重复键检查结果为 no dup。
- **原因码**：总表 14 个码与 plan 第 1237–1262 行逐一一致，顺序相同；`null_when` 的顺序符合优先级。
- **`scripts/ci/check_contract.py`**：契约文档对照通过，rc=0。

### 与裁定冲突或不明确的地方（请架构师确认）
1. **“截止日规则”只用于回填季末行**：裁定第 1 条写“可见时间取 `max(next_trading_day(plrq), 截止日规则)`”，但没有说上线后新出现的季末行是否也要再和截止日取较晚者。本文的处理是：
   - 上线后新出现的季末行沿用 T-R12e 的 `max(next_trading_day(plrq), first_seen_at)`，不引入截止日；
   - 截止日规则只用于首次全量回填的季末行。
2. **S2 剔除 `cdr_unit` 实际不会发生**：S2 的池 U = F43 的池（§1.4 + 因子池排除），而 §1.4 要求 `sec.type = stock`，CDR 本来就不在 U 中。裁定第 6 条写“`cdr_unit` 影响 S2 覆盖率的剔除”，本文照写，但按现行池定义，这条剔除不会剔掉任何证券。
3. **CDR 按份数计时，是否也要等配置接入才清除标记**：裁定写“T-B05 确认单位、配置也接入后，清除 `cdr_unit`”。本文按字面写成两个条件都满足才清除。如果 `zgb` 按 CDR 份数计，换算用不到转换比例，此时是否仍要等配置接入，请确认。

请只暂存 `docs/strategies/feature_spec.md` 和本报告。工作区里有其他角色未提交的改动（config/、src/ 等），与本任务无关。

---

## T-R12g

<a id="T-R12g"></a>

**任务**：按 plan 2.12.1 T-R12f 节中标为 T-R12g 的三点确认（9ad51b8，第 1287、1297、1298 行）收尾。执行人为量化策略研究员，日期 2026-11-01。本次只改文档：没有提交 git，没有调用麦蕊，也没有读取证书。

### 改动
**`docs/strategies/feature_spec.md` 从 v1.1.6 升到 v1.1.7**：已加版本记录行，YAML 版本改为 1.1.7，§13 新增 C18。

1. **截止日规则的适用范围**：§7A.0 V5i 节写明，截止日规则只用于首次全量回填的季末行。增量采集的季末行取 `max(next_trading_day(plrq), first_seen_at)`，不套用截止日，并标注 plan 已裁定（9ad51b8，T-R12g）。
2. **删除 `cdr_unit` 的 S2 剔除条款**：
   - §7A.0 待核实标记的说明改为：`cdr_unit` 只是 F42、F47 值上的标记；S2 剔除只涉及银行、保险和 `non_a_share_capital` 三种标记。
   - F42、F47 的 CDR 条目已同步。
   - §7C S2 总则删除“含 `cdr_unit` 的 CDR”；计数列表改为只列上述三种标记，并注明 `cdr_unit` 不参与剔除和计数。
   - §11 V5j 已同步。
   - YAML 中 `cdr_unit.s2` 改为 not involved。
3. **CDR 清除条件分两种情况**：
   - 按 CDR 份数计：总市值 = `c × zgb`，不需要配置，T-B05 确认后即清除。
   - 按基础股份计：需要转换比例配置接入后才清除。
   - 已同步到 §7A.0、§7C S1 ⑤、§11 V5j（负责人列改为“T-B05（+ 架构师：仅按基础股份计时的转换比例配置）”），以及 YAML 中的 `cdr_unit.clear_when` 和 `conversion_ratio`。
4. **§13**：
   - C16 注明：CDR 的池剔除已由 C17 撤销，S2 剔除已由 C18 撤销。
   - C17 注明：⑥ 和 ⑦ 已由 C18 修订。
   - 新增 C18。
   - 原因码仍为 14 个。

**`docs/strategies/catalog.md` 未改，仍为 v0.3.6**：
- 条件 ① 写的是“`cdr_unit` 已清除”，不涉及清除需要哪些前提。
- 条件 ② 写的是“先剔除 `verify_pending` 非空的证券”，属于通则，没有单独写 CDR 剔除。

因此两处都与新规则不冲突。

### 校验
- **rg 检查**：
  - 现行规则中已经没有“S2 剔除 `cdr_unit`”的说法。剩下的命中只在第 5 行的 v1.1.5 历史摘要和 §13 C16、C17 的历史记录里，这两条已注明由 C17、C18 撤销或修订。
  - 待定类字样和 `pool_exclude_verify_pending` 均无命中。
- **YAML**：用 `/tmp/yv/bin/python` 做 `safe_load`，通过。共 48 键，没有重复（P0 47 个、P1 1 个），version 为 1.1.7。重复键检查结果为 no dup。
- **原因码**：总表 14 个码与 plan 一致，顺序也相同。
- **`scripts/ci/check_contract.py`**：通过，rc=0。

### 遗留问题
无。

请只暂存 `docs/strategies/feature_spec.md` 和本报告；工作区里其他角色的改动与本任务无关。

---

## T-R12h

<a id="T-R12h"></a>

**任务**：按 plan 2.12.1“T-R12h 补充裁定”（7ec6fad，第 1300–1307 行）写入 A+B / A+H 名单接入口径。量化策略研究员，2026-11-01。只改了文档，没有提交 git，没有调用麦蕊，也没有读取证书。

### 改动
**`docs/strategies/feature_spec.md` v1.1.7 → v1.1.8**（加版本记录行，YAML 版本改为 1.1.8，§13 新增 C19）

1. **名单接入（裁定 1）**：
   - 名单放在 `config/share_class_list.yaml`。
   - 文件头写 `list_version`、`as_of`、`sources`。
   - 每条记录写 `code`、`class`（`B` 或 `H`）、配对代码、`effective_from`、`effective_to`（可为空）、`source`、`verified`。
   - d 日只用满足 `effective_from ≤ d`、且 `effective_to` 为空或 `effective_to > d` 的记录，不得前视。
   - 名单更新时整版替换，`list_version` 加一，不改旧行；T-B55 重算时按新版本覆盖。
   - 已写入：
     - §7A.0 的 B3 行和 `non_a_share_capital` 行（“名单内”指 d 日生效的记录）；
     - F42、F47 的 B3 条目；
     - §11 V5g；
     - YAML `share_class_check`（新增说明字段 `list_file`、`list_header`、`effective_on_d`、`list_version_to`、`list_update`、`unverified_rows`，并在注释里登记为“只是说明”）。
2. **basis 新增 `share_class_list_version`**：已写入 basis 字段说明、F42 和 F47 的 basis 条目、YAML `basis_fields`（两处）。名单接入前（`share_class_check = unavailable`）不写这个字段。
3. **`verified=false` 照常打标（裁定 2、3）**：以下两类记录照常打 `non_a_share_capital`：
   - 手工对应的 45 对；
   - 211 对与 209 对两个来源取并集后多出来的记录。
4. **V5g 关闭条件从两项改为四项**：新增两项，§7C S1 和 §11 V5g 已同步：
   - ③ 名单内所有记录都已 `verified=true`，核对来源是巨潮或港交所披露；
   - ④ 211 对与 209 对的差异已查明，结论写入 `sources`；查明之前不关闭。

   S1 出处补了 9ad51b8 和 7ec6fad。
5. **§13**：新增 C19；原因码表不变，仍为 14 个。

**`docs/strategies/catalog.md` v0.3.6 → v0.3.7**：L-01 条件① 原来写了 V5g 的关闭项（名单已接入、对照巨潮核实），与新规则冲突。已补上“名单内所有记录 `verified=true`，211 对与 209 对两个来源的差异已查明”，并加了 v0.3.7 变更说明，标题版本也已改。

### 校验
- **rg 检查**：待定类字样和 `pool_exclude_verify_pending` 均无命中（rg rc=1）。
- **YAML**：用 `/tmp/yv/bin/python` 执行 `safe_load` 通过，48 个键无重复（P0 47 个、P1 1 个），version 为 1.1.8；重复键检查结果为 no dup。F42 和 F47 的 `basis_fields` 都含 `share_class_list_version`。
- **原因码**：14 个，与 plan 一致，顺序相同。
- **`scripts/ci/check_contract.py`**：通过，rc=0。

### 冲突或不明确
1. **“d 日可见”在 plan 里没有对应规则**：架构师摘要写的是“d 日生效且 d 日可见”，plan 原文只规定了生效区间（`effective_from` / `effective_to`），没有名单行的可见时间字段，而且明确说“T-B55 重算时按新版本覆盖”。本文按原文只写了生效区间。这样一来，历史重算会用后来才核实或补充的名单版本，但生效日期本身不会前视。如果要求名单行另有可见时间，比如记录写入日，需要 plan 补充字段名。
2. **配对代码的字段名**：plan 只写了“配对代码”，没有给出字段名，本文也没有自拟键名，需要由后端或 plan 确定。

另外，211 对和 209 对分别来自哪两个来源，plan 原文只写“两个来源”（见后端 `reports/T-R12ef-lists.md`）。本文没有点名来源，这一点不影响口径。

请只暂存 `docs/strategies/feature_spec.md`、`docs/strategies/catalog.md`、本报告和状态文件。

---

## T-R12i

<a id="T-R12i"></a>

**任务**：按 plan 2.12.1“T-R12h 补充裁定”第 4 条（d500474，第 1308–1311 行）写入名单的更正口径和配对字段。执行人为量化策略研究员，日期 2026-11-01。只改了文档：没有提交 git，没有调用麦蕊，也没有读证书。

### 改动
**`docs/strategies/feature_spec.md` v1.1.8 → v1.1.9**：加了版本记录行，YAML 版本改为 1.1.9，§13 新增 C20。

1. **配对字段定名**。§7A.0 B3 和 §11 V5g 的名单记录字段里，原来的“配对代码”换成两个字段：
   - `paired_code`：交易所代码按原样记录，不加市场后缀，例如 H 股 `00939`、B 股 `900901`。
   - `paired_market`：取值 `HK`、`SH`、`SZ`。

   YAML `share_class_check` 新增说明字段：
   - `list_record`：完整记录字段列表；
   - `paired_code`、`paired_market`。
2. **更正口径**。以下内容已写入 B3、§11 V5g、F42 和 F47 的 B3 条目、basis 字段说明，以及 YAML 的 `visible_time_field: none`、`recompute_with_latest_list`、`backtest_report`：
   - 名单行不加可见时间字段。A+B、A+H 的对应关系在 `effective_from`（B 股或 H 股上市日）当天已公开，按生效区间取用不构成前视。
   - 重算时用最新版名单，这属于更正历史，不是使用未来信息。
   - 回测报告要写明所用的 `share_class_list_version`。

   YAML 注释已把上述新增字段登记为“只是说明”，F47 的 `basis_ref` 已加 d500474。
3. **§13**：C19 注明“配对代码”已由 C20 定名补全。原因码表不变，仍是 14 个。

**`docs/strategies/catalog.md` 未改，仍为 v0.3.7**：L-01 条件① 没有写名单字段，也没有写更正口径，不冲突。

### 校验
- **rg 待定类字样**：待定类字样和 `pool_exclude_verify_pending` 均无命中（rc=1）。
- **rg “配对代码”**：剩余的命中都带有 `paired_code` / `paired_market` 定名，位置是第 5 行版本摘要、B3、V5g、C19、C20 和版本记录，没有未定名的用法。
- **YAML**：用 `/tmp/yv/bin/python` 执行 `safe_load` 通过，48 个键无重复，P0 47 个，version 为 1.1.9；重复键检查结果为 no dup。F42、F47 的 `list_record` 都包含 `paired_code`、`paired_market`。
- **原因码**：14 个，与 plan 一致，顺序相同。
- **`scripts/ci/check_contract.py`**：通过，rc=0。

### 冲突或不明确
无。

请只暂存 `docs/strategies/feature_spec.md`、本报告和状态文件。
