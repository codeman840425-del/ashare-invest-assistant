# T-R12 后续裁定（架构师）

架构师 · 2026-11-01。只改了 docs/；未推送；未调用麦蕊，未读取证书。依据：`/workspace/team/reports/T-R12.md`、`docs/strategies/feature_spec.md` v1.1.0 §7A/§7B/§7C/§11/§13、`/workspace/team/reports/L-01-basis-ruling.md`、探针样本 `src/backend/probes/samples/run-20261101-190106/p05_fin_cashflow.json`（只读）。

## 提交
- `ad79ced`：代研究员提交（T-R12）——`docs/strategies/feature_spec.md` v1.1.0、`docs/strategies/catalog.md` v0.3.2（提交前已核对两份文件头的版本号，内容未改）。
- plan 提交：6efedef（只含 docs/plan.md）。

## ② 经营现金流字段
**裁定**：主字段 `jyhdcsdxjlxj`，备用 `jyhdcsdxjlje`；每个 YTD 分量取 `coalesce(xj, je)`，按分量在 `basis.ocf_field` 记录实际所用字段；两者都空 → 缺失（TTM 现金流 null，现金流比 null），不用 0 补。非空率由 T-B05 实测确认。
**理由**：
- 实测：600519 2026-06-30、2026-03-31 两行 `jyhdcsdxjlxj` 有值，`jyhdcsdxjlje` 均为 `'-'`（样本文件中 2/2 对 0/2）。
- 字段含义：`jyhdcsdxjlxj` = 流入小计 `jyhdxjlrxj` − 流出小计 `jyhdxjlcxj`（逐分相等），即主表“经营活动产生的现金流量净额”；`jyhdcsdxjlje` 推测是补充资料（间接法）里的同名净额，季报常不披露（推测，未核实）。两者会计含义相同，用 coalesce 合并不改变口径。
- 与研究员 feature_spec §7A.0 的暂行做法一致，因此不需要研究员改文档。
- plan 改动位置：2.12.1“财务按时点自算”、3.3 `market.financial_derived.basis`、T-B55。plan 中原来只有 2.12.1 一处写了 `jyhdcsdxjlje`，现在只在主备字段说明中出现。

## ③ PB 口径（G3）
**裁定**：PB = d 日总市值（不复权收盘 `c` × `zgb`，取法同 `pe_ttm`）÷ 按 `plrq` 时点规则在 T 时可见的最新一期归母权益 `gsmgdqsyhj`（时点值，不做 TTM，15 个月回退下限）。归母权益 ≤ 0 或缺失 → null，不参与行业分位排序。行业分位与 PE 分位规则相同（申万一级、因子池排除、N < 5 → null）。银行、保险照常计算，但需由 T-B05 核对资产负债表字段，核对前标待核实。`financial_derived.metric` 新增 `pb`。
**理由**：T-R12 G3 本身建议按 F42 同一套规则计算；没有更好的依据，因此采用保守默认。总市值不用快照或因子里的市值字段，这样和 PE 的分子一致，也满足时点要求。
**位置说明**：任务要求写进 §7A 或 §7C。但 §7A、§7C 都在 `docs/strategies/feature_spec.md` 中，该目录归研究员所有，我只做提交、不改内容。所以口径写进了 plan 2.12.1，与 PE、ROE 等其他口径放在同一处；特征键请研究员在 feature_spec §7A 登记（建议 `f.pb_pit`、`f.pb_pit_ind_pct`），并关闭 G3/C10。

## ④ 4 条补充规则与切换阈值
**裁定**：4 条补充规则（回填行只按 `plrq` 计算；同一 `available_from` 冲突 → 取较晚的 `first_seen_at`，仍无法区分则 null 并告警 `data_conflict`；E(P−4) ≤ 0 视为缺失；现金流比用同一个 P）没有技术问题，**已确认**。§7C S1–S6 的阈值（95% / 99%、30 只 30/30、3 个月度截面且其中一个在披露截止日后）也**已确认**。plan 2.12.1 已标【已确认】，并入 T-B55。
两点补充说明，不需要研究员改文档：
1. P 按“该键所需的分量都可见且非空”逐期回退，所以同一 T 下不同键的 P 可以不同，各自记入 `basis.period`。
2. V5e（保险识别）：如果 T-B05 确认麦蕊没有申万二级，就用配置中的保险证券名单识别（注明来源）来关闭 V5e，避免 S1 永远无法满足。

产品取舍：切换至少需要 3 个月；等待期间线上仍用麦蕊因子；旧信号不重算。已作为 §9 **问题 93** 写入，标“默认执行，用户可改”。

## ⑤ L-01 行
plan 2.5.11A 中 L-01 行的第 ⑤ 点已压缩，只引用 2.12.1、feature_spec §7A 和 **§7C**，不再重复口径细节（对应 C11）。

## ⑥ T-B05 新增实测项（已并入 plan T-B05 行）
1. cashflow：抽 ≥ 5 家（至少含 1 家银行、1 家保险），覆盖多个年份和季度。
   - 统计 `jyhdcsdxjlxj`、`jyhdcsdxjlje` 各自的非空率（`'-'` 计为空）。
   - 核对 `jyhdcsdxjlxj` 是否等于 `jyhdxjlrxj` − `jyhdxjlcxj`。
   - 两个字段同时有值时，核对是否相等。
   - 核对是否为年初至报告期末的累计口径。
2. 银行（000001、600000）和一家保险的 balance：核对 `gsmgdqsyhj`、`fzhj`、`zczj` 是否有值及单位，并检查有无归母权益 ≤ 0 的情况。
3. 多版本行：
   - 探针保存同一 `jzrq` 下多个 `plrq` 版本的完整数值。
   - 找一家发布过差错更正的公司对照巨潮，确认更正版本在麦蕊中如何成行，以及 `plrq` 是否取更正公告日。
4. capital：确认 `plrq` = `bdrq` 的含义，用 600519 2011-07-01 送股对照巨潮。
5. `sw_l1`：
   - 确认代码格式（`/hszg/list`）。
   - 确认“银行”“保险”在返回中的代码。
   - 确认是否有申万二级；没有时提供保险证券名单及来源。
6. PB 分量：抽样核对不复权 `c` × `zgb` 与巨潮或交易所披露的总股本、总市值。
结果写入 `docs/mairui-verified.md`，并说明现金流主备字段是否需要调整。

## 需要研究员跟进
- 在 feature_spec §7A 登记 `f.pb_pit`、`f.pb_pit_ind_pct`，关闭 G3/C10。
- 把 C9、A5、C11 改为“已处理”（plan 2.12.1 / L-01 行）。
- L-01 卡中 PB 分位改为引用新键。

## 校验
`python3 scripts/ci/check_contract.py` 通过；`gitleaks dir docs` 通过（no leaks found）。

---

## T-R12a

架构师 · 2026-11-01（America/Denver）。依据：`/workspace/team/reports/T-R12a.md`；`feature_spec.md` v1.1.1 的 §1.4、§1.7、§7A（F47/F48）、§7C（研究员 v1.1.1 在 38c257f 由代提交）。只改了 `docs/plan.md`，本地提交 `de86b99`，未推送。check_contract 与 gitleaks 都通过。

### 1. PB 覆盖率门槛（§7C S2）
**裁定**：
- 分母 D(d) = S2 的池 U（F43 的池，即 d 日可交易、非 ST、非退市整理、上市满 60 个交易日），再剔除两类：
  - T 时所选报告期的归母权益**已知且 ≤ 0** 的证券；
  - `verify_pending` 非空的证券。
- 归母权益**缺失**的证券留在分母中，算未覆盖。
- 全市场：D 中 `f.pb_pit` 非空 ≥ **99%**。
- 申万一级行业：组内 D ≥ 5 的行业，组内覆盖率 ≥ **95%**。D < 5 的行业不考核，但要列出。`sw_l1` 为空的证券只计入全市场口径，单列个数。
- F48 非空数只报告，不作门禁。

**理由**：
- PB 只需要价格、股本和一期权益，比 PE 少了 TTM 的三个分量，所以全市场门槛不应低于 PE 的 99%。
- 行业门槛取其他键通用的 95%，这样能发现某一行业整体缺数（例如银行 balance 字段），全市场比例会掩盖这种情况。
- 把“缺失”放在分母里，是为了让缺数直接体现为覆盖率下降。

### 2. plan 2.12.1 未覆盖的边界（已写入 2.12.1，适用于 pe_ttm、pb 和 roe 的权益部分）
总原则：留空，并在 `basis.null_reason` 写原因码；不用前值、0、插值或估算补数。
1. **停牌或无效日线**（无日线、`sf=1`、T-B05a 标为 `suspect`）→ null（`no_valid_bar`）。不用停牌前的收盘价。
2. **股本变动日**：
   - `zgb` 取 `bdrq ≤ d` 且已可见的最新一行，并记 `basis.zgb_bdrq`。
   - 已知送转除权日 ≤ d，但还没有 `bdrq ≥ 除权日` 的可见股本行时，判定为价格已除权、股本未更新，记 null（`share_change_pending`）。
   - 如果没有送转数据源，记 `share_change_check=unavailable`；是否必须接入这类数据，取决于 T-B05 对 V5d 的实测结果。
3. **B 股、H 股**：
   - 采用 A 股价格 × 全部股本（`mcap_basis=a_price_total_shares`），不用 B 股、H 股价格，也不做汇率换算。这样分子和分母（全公司归母权益）口径一致。
   - `zgb` 是否包含 B 股、H 股由 T-B05 实测；核实前加标记 `verify_pending: non_a_share_capital`。
   - 如果实测发现 `zgb` 只含 A 股，这类公司的 PE、PB 一律记 null。
4. **新股或报告空窗**：
   - 没有有效报告期 → null（`no_visible_report`）。
   - 所用报告期早于上市日（权益不含募集资金）→ PB 和 ROE 记 null（`pre_listing_equity`），PE 照常计算。
   - 股本行早于上市日 → PE、PB 记 null。
   - 不用招股书或募资额推算权益。
5. **币种或单位**：一律按人民币元处理。出现非人民币、非元的标识，或数量级不连续时，该期记 null，并告警 `unit_mismatch`。不按数量级猜单位。
6. **极小的正权益**：不设上限、不做缩尾，按原值落库（排序基于秩，不受影响）。展示时可把 `pb > 100` 标为离群，但不改值。确认 T-R12a 的做法。
7. **每股字段**：不使用。确认 T-R12a 的做法。

### 3. 银行、保险的待核实标记
**裁定**：
- 键级状态仍用 `feature_catalog.status`（`declared` → `verified_live`）。这是文档现有的约定，只能按键标记，不能按证券标记。
- 证券级的待核实写在 `market.financial_derived.basis.verify_pending`，类型为字符串数组，空数组表示无待核实项。目前有三个取值：
  - `bank_balance`
  - `insurance_balance`
  - `non_a_share_capital`
- 适用范围：
  - 前两项用于 `pb`、`roe_ttm`；
  - 第三项用于 `pe_ttm`、`pb`；
  - 截面分位键继承底层值的标记，由 T-B35 在特征元数据中保留。
- 带标记的值照常计算和落库，研究报告中要单列。
- §7C S2 计算时，带标记的证券**同时从分子和分母中剔除**，并单列个数。

**理由**：只剔除分子的话，银行加保险约占 1%，会直接把 PB 的 99% 门槛压到不达标。S1 已要求关闭 V5b、V5e，也就是切换时所有标记必须已被 T-B05 清除，因此剔除不会放松切换条件。

### 研究员需在 feature_spec 修改
- **§7C S2**：去掉 PB 条的“建议，待确认”，改为上面第 1 点的定义，包括分母、99%、行业 95%（D ≥ 5），以及 `verify_pending` 同时从分子和分母剔除。
  - 建议在 S2 的总述中写明：所有键都按同样方式剔除 `verify_pending`。
- **§7A F47**：
  - 边界中补充上面第 2 点的 1–5 条和对应的 `null_reason`；
  - 把“极值不截断”“不用每股字段”从“本文补充”改为“plan 2.12.1 已裁定”；
  - basis 中加入 `null_reason`、`zgb_bdrq`、`mcap_basis`、`share_change_check`、`verify_pending`；
  - 把银行、保险“保持 declared”改为“键级 declared + 行级 `verify_pending`”。
- **§7A F48**：写明继承 F47 的 `verify_pending`。
- **F42、F44 同步**：
  - F42 加入第 2 点的 1–5 条，以及 `non_a_share_capital`；
  - F44 加入 `pre_listing_equity`，以及 `bank_balance`、`insurance_balance`。
- **§11**：V5d 补充“送转数据源与除权日先后”；新增 B 股、H 股股本核对和币种、单位字段核对两项（对应 T-B05 ⑦⑨）。
- **§12 YAML**：F42、F44、F47 的 `null_when` 和 basis 字段同步更新；升版本号（建议 v1.1.2）。

### 后端（T-B05 / T-B55）新增
- **T-B05 ⑦**：`zgb` 是否包含 B 股、H 股。用一家 A+H、一家 A+B 公司对照巨潮，并确认 capital 中 A/B/H 股本的字段名。
- **T-B05 ⑧**：麦蕊有没有分红送转数据（送转比例、除权日），以及送转对应的 capital 行 `plrq` 相对除权日的先后（与 V5d 一起做）。
- **T-B05 ⑨**：财报响应中有没有币种、单位字段。抽一家 CDR 或有境外上市背景的公司。
- **T-B55**：
  - 实现 2.12.1 的 7 条边界规则和 `basis` 新字段（`null_reason`、`zgb_bdrq`、`mcap_basis`、`share_change_check`、`verify_pending`）；
  - 对照报告按 §7C S2 输出覆盖率，包括 PB 全市场和分行业，`verify_pending` 单列。

---

## T-R12b

架构师 · 2026-11-01 晚（America/Denver）。依据：`T-R12a.md` 中「T-R12b」节列出的 6 个非阻塞点，以及 feature_spec v1.1.2（2038bd2）。只改 `docs/plan.md`，本地提交 `1c62952`，未推送；check_contract 和 gitleaks 均通过。条文在 plan 2.12.1 的“T-R12b 补充裁定”。

1. **原因码补全，列表封闭。** 共 14 个：
   - `no_valid_bar`、`share_change_pending`
   - `a_share_only_capital`：边界 3，`zgb` 只含 A 股
   - `no_visible_report`、`pre_listing_equity`
   - `pre_listing_capital`：边界 4，股本行早于上市日
   - `unit_mismatch`
   - `non_positive_earnings`：PE 的 TTM 净利润 ≤0；现金流比的分母 ≤0 也用这个码
   - `non_positive_equity`
   - `no_capital_row`：`zgb` 缺失、为空或 ≤0
   - `ocf_missing`、`component_missing`、`data_conflict`
   - `financial_sector_na`：银行、保险的负债率

   规则：
   - `value` 为 null 当且仅当 `null_reason` 非空，单元测试断言这一点。
   - 一行同时命中多个原因时，只写表中靠前的一个。
   - 新增原因码要先改 plan。
   - 分位键的 null 原因（`group_too_small` / `input_null`）由 T-B35 记在特征元数据中，不写进 `financial_derived`。

   理由：原因码不封闭的话，实现时会冒出“other”或各写各的，对照报告就没法统计。
2. **`unit_mismatch` 兼作原因码。** 确认，和告警同名。
3. **ROE 的 P−4 早于上市日。** 按 E(P−4) 缺失处理，走 `single_period`，并新增 `basis.single_period_reason`：
   - `p4_pre_listing`：P−4 早于上市日；
   - `p4_missing`：E(P−4) 缺失；
   - `p4_non_positive`：E(P−4) ≤0。

   理由：上市前的权益不含募集资金，和上市后的权益平均会压低分母、高估 ROE。`single_period` 是已有的回退口径，不是编出来的数。
4. **S1 的关闭项。**
   - 确认加入 V5g。
   - 另外还要关闭 V5d 和 V5h，这是保守默认：股本口径和单位口径没有实测时，自算值可能出错而不会报警。
     - V5d 关闭的条件：有结论；如果股本行普遍晚于除权日才可见，就要接入送转数据，并且切换时 `share_change_check` 不再是 `unavailable`。
     - V5h 关闭的条件：确认币种、单位的字段名，或者确认没有这类字段。没有字段时只能靠数量级检查，这一点要写进结论。
   - 这会延长切换等待，属于产品取舍，已列为 §9 问题 96（默认执行，用户可改）。
5. **其他键的 `unit_mismatch`。** 边界 5 扩展到 financial_derived 的全部 metric。比值键只要任一分量（包括 TTM 用到的任一期）命中，结果就为 null。理由：同一期内的单位差在比值里会抵消，但 TTM 跨期拼接时不会。
6. **B 股、H 股识别字段待实测。**
   - 不猜字段名，也不按代码段或公司名称推断。
   - 能识别时照常打 `non_a_share_capital`；不能识别时记 `basis.share_class_check=unavailable`。
   - 只要还有 `unavailable`，V5g 就不算关闭，S1 也就不能通过。
   - 研究报告要单列 `unavailable` 的数量。

另外：financial_derived 的 basis 说明加入 `single_period_reason` 和 `share_class_check`；T-B55 行补上这 6 条。

## T-R12c

已写入 plan 2.12.1「T-R12c 补充裁定」（b85b564）。代研究员提交了 feature_spec v1.1.3 和 catalog v0.3.5（a8b99b4）。

1. `zczj ≤ 0` 并入 `component_missing`，同时写 `data_quality` 告警，不新增原因码。
2. `single_period_reason` 多命中时，按 `p4_pre_listing` → `p4_missing` → `p4_non_positive` 的优先级取第一个，已确认。
3. 退市证券不写 null 行，也不新增原因码。只有有日线的交易日才写 pe_ttm 和 pb 行。退市前的历史行照常计算。

研究员待办：把 F46 的 YAML `null_without_code` 改成 `component_missing`，并删掉 C15 的待定标注。
