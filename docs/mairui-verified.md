# T-R12 / T-R12a / T-R12b 实测材料（后端）——`docs/mairui-verified.md` 模板

后端 · 2026-11-01 MST。依据：plan 2.12.1 与 T-B05 行（6efedef、de86b99、1c62952），`T-R12-rulings.md`（含 T-R12a、T-R12b 节），feature_spec v1.1.2 §7A、§11（V5b–V5h）。
**本文件是模板**：T-B05 窗口里跑 `py -3 run_all.py p13`（28 次）之后，把 `p13_analysis.json` 的结果填进每节的“实测”栏，由架构师提交为 `docs/mairui-verified.md`。本次只写了探针和 dry-run，**没有调用麦蕊**，下文“实测”栏都是待填。“已知”栏只引用 run-20261101-190106（T003 已有结果，0 次新调用）。

- 探针：`src/backend/probes/p13_fin_pit.py`（调用与原始响应保存）、`p13_analyze.py`（纯离线分析，可重算）；只点名运行。
- 离线重算：`python3 p13_analyze.py results/run-<…> --stdout`；自检：`env -u MAIRUI_LICENCE python3 selfchecks/tr12_fin.py results/run-<…>`。
- 调用次数与运行方式见 `T-B05-recheck.md` §8。

**L-01 切换硬条件（S1，T-R12b 第 4、6 条）**：⑦（V5g）、⑧（V5d）、⑨（V5h）必须都有结论才能关闭；①②⑤ 对应的 V5c、V5b、V5e 也在 S1 关闭项里。下文这三节都标了 **[S1]**。

---

## ① 经营现金流字段（V5c）

| 项 | 分析键（`p13_analysis.json`） | 实测 |
|---|---|---|
| 公司 | `1_cashflow.<code>`：600519（一般）、000001、600000（银行）、601318（保险）、300750（一般）、600525（更正样例） | 待填 |
| jyhdcsdxjlxj / jyhdcsdxjlje 非空率（'-'、'--'、空串计为空） | `nonnull`（全部、2015 年起、按季） | 待填 |
| xj = jyhdxjlrxj − jyhdxjlcxj | `identity_xj_eq_lr_minus_lc`：equal / unequal / not_checkable / `subtotals_zero_placeholder`（流入流出小计都是 0、xj 非 0 的早期占位行，单列，不计为不等） | 待填 |
| xj 与 je 同时有值时是否相等 | `xj_vs_je` | 待填 |
| 是否 YTD 累计 | `ytd`：FY/Q1 ≥ 2.5 → `ytd_cumulative`，≤ 1.8 → `single_quarter`（用流入小计；没有时用销售商品收到的现金） | 待填 |
| 最新期实际用了哪个字段 | `ocf_field_used_latest` | 待填 |
| TTM 示例 | `ttm_example`：TTM = YTD(y,q) + FY(y−1) − YTD(y−1,q)；每个分量 coalesce(xj, je)，记入 `basis.ocf_field`；三个分量里只要有一个两字段都空 → null（`ocf_missing`），**不补 0** | 待填 |

已知：600519 2026H1 xj = 70,690,750,119.06 = 流入 − 流出，je = '-'（feature_spec §7A.0）。
结论模板：“主 `jyhdcsdxjlxj`、备 `jyhdcsdxjlje` 维持 / 需对调（银行、保险 …）；累计口径 已确认 / 不是。”

## ② 银行、保险资产负债（V5b）

| 项 | 分析键 | 实测 |
|---|---|---|
| gsmgdqsyhj、fzhj、zczj 非空率 | `2_balance.<code>.nonnull` | 待填 |
| 单位 | `magnitude_hint_not_for_conversion`：只是数量级提示（银行、保险 zczj ≥ 1e11 才像“元”），**不据此换算**（T-R12a 边界 5） | 待填 |
| 资产 = 负债 + 所有者权益 | `assets_identity_since_2015`（zczj 对 fzhgdqyzj） | 待填 |
| 归母权益 ≤0 的行 | `parent_equity_le0_rows`（PB → null，`non_positive_equity`） | 待填 |
| 数量级跳变（≥50 倍） | `magnitude_jumps` → `unit_mismatch` 候选 | 待填 |

关闭条件：银行 000001、600000 和保险 601318 的三个字段都有值、单位是元，就清除行级 `verify_pending` 里的 `bank_balance`、`insurance_balance`。

## ③ 多版本与差错更正（V5f）

- 每个 `financial/*` 原始响应全量保存在 `p13_fin_pit/raw_*.json`，同一 jzrq 的所有 plrq 版本都在里面（不截断）。`3_multi_version.by_response` 列出每个期的版本和字段差异。
- **更正样例：600525 长园集团**。公告 2025-030《关于前期会计差错更正的公告》，2025-04-29 披露，更正 2023Q3、2023FY、2024Q1、2024H1、2024Q3 三张表；归母权益影响：2023FY +206.92 万，2024Q3 +1,216.51 万。来源：证券日报 2025-04-29 D904 版 http://epaper.zqrb.cn/images/2025-04/29/D904/zqrb20250429D904.pdf
  - 备选 1：600590 泰豪科技，2024-11-09，https://paper.cnstock.com/html/2024-11/09/content_1992016.htm（`--p13-restated 600590.SH --p13-announce 2024-11-09 --p13-periods 2023-12-31,2024-06-30`）
  - 备选 2：000981 山子高科，http://static.cninfo.com.cn/finalpage/2026-04-28/1225219949.PDF
- 分析键 `3_multi_version.restated.match.<income|balance|cashflow>`：每个更正期在公告日 ±3 天内有没有出现新版本，新版本的 plrq 是多少。

| 问题 | 实测 |
|---|---|
| 更正后是新增行，还是覆盖原行？ | 待填 |
| 新行 plrq = 更正公告日（2025-04-29），还是别的日期？ | 待填 |
| 新旧版本 gsmgdqsyhj 差值与公告的 206.92 万、1,216.51 万是否一致 | 待填（用巨潮核对清单第 3 条） |

## ④ capital 的 plrq 语义（V5d 前半）

- 600519 2011 年度利润分配：10 送 1 派 23 元（含税），公告 2011-06-26，股权登记日 2011-06-30，**除权除息日 2011-07-01**，红股上市日 2011-07-04；总股本 943,800,000 → 1,038,180,000。来源：全景网 https://www.p5w.net/stock/ssgsyj/hsgg/201106/t3680283.htm；巨潮年报 http://static.cninfo.com.cn/finalpage/2011-03-21/59148907.PDF、http://static.cninfo.com.cn/finalpage/2013-03-29/62296687.PDF
- 分析键：`4_capital.<code>`（`plrq − bdrq` 天数分布、`plrq == bdrq` 占比），`4_capital.600519_bonus_2011`（2011-07-01 前后的股本行）。
- **已知（需架构师注意）**：600519 capital（run-20261101-190106 p05 样本）里有两种行：
  - `bdrq 20260630, plrq 2026-08-15`：plrq 是半年报披露日；
  - `bdrq 20260930, plrq 2026-09-30`：plrq = bdrq，而三季报那时还没披露。
  - 如果 plrq = bdrq 的行是事后补录的，按 `next_trading_day(plrq) ≤ d` 判可见会**提前看到股本**（look-ahead）。这要靠 ④ 的分布和 ⑧ 的除权日比对来定。如果确认是这样，建议对 plrq = bdrq 的行改用 `max(plrq, first_seen_at)`，或者接入送转数据；**这需要架构师裁定**，本探针不改规则。

| 问题 | 实测 |
|---|---|
| plrq == bdrq 的行占比；plrq > bdrq 的行是不是定期报告日 | 待填 |
| 2011-07-01 有没有股本行，zgb 是否 = 1,038,180,000 | 待填 |

## ⑤ `/hszg` 申万行业（V5e / V9）

- 分析键 `5_sw`：申万一级代码格式（list 中 pcode = swhy 的节点）、银行、保险节点、`has_sw_l2`，`hszg/zg/000001`、`hszg/zg/601318` 的行业归属。
- 没有申万二级时，保险用**引用的名单**：申万二级“保险Ⅱ”（801194.SI / SW2021 490201）成分 **601318 中国平安、601628 中国人寿、601601 中国太保、601336 新华保险、601319 中国人保**（000627 天茂集团 2025-09-30 调出）。来源：https://legulegu.com/stockdata/index-composition?industryCode=801194.SI ；https://www.lixinger.com/equity/industry/detail/sw_2021/490201/490201/constituents/change-history

| 问题 | 实测 |
|---|---|
| sw_l1 代码格式（如 `sw_yx`） | 待填 |
| 银行节点代码、保险节点代码 | 待填 |
| 有没有申万二级 | 待填 |

## ⑥ PB 分量（G3 抽样，plan 2.12.1 PB 条）

- PB(d) = 不复权 `c(d)` × `zgb(d)` ÷ `gsmgdqsyhj(P)`。
  - zgb：capital 中 `bdrq ≤ d` 且 `next_trading_day(plrq) ≤ d` 的最新行；离线近似为 `plrq < d`。
  - 权益：15 个月内 `plrq < d` 的最新报告，丢弃 `plrq ≤ jzrq` 的占位行。
  - `mcap_basis=a_price_total_shares`。
- 分析键 `6_pb.<code>`：最近 5 个交易日的值，basis 含 `zgb`、`zgb_bdrq`、`close_raw`、`period`、`equity`、`mcap`、`verify_pending`、`share_change_check`、`share_class_check`。
- null 只用 plan 2.12.1 T-R12b 的**封闭 14 码**（`p13_analyze.NULL_REASONS`），多个同时命中时只写表中靠前的一个：`no_valid_bar`、`share_change_pending`、`a_share_only_capital`、`no_visible_report`、`pre_listing_equity`、`pre_listing_capital`、`unit_mismatch`、`non_positive_earnings`、`non_positive_equity`、`no_capital_row`、`ocf_missing`、`component_missing`、`data_conflict`、`financial_sector_na`。
- 核对：600519、000001、601318 的 `c × zgb` 与交易所、巨潮披露的总市值和总股本对照（巨潮清单第 5 条）。

| 代码 | c × zgb | 披露总股本 / 总市值 | 偏差 | 实测 |
|---|---|---|---|---|
| 600519 | | | | 待填 |
| 000001 | | | | 待填 |
| 601318 | | A+H 总股本 18,107,641,995 | | 待填 |

## ⑦ zgb 是否含 B 股、H 股（V5g）**[S1]**

- **A+H：601318 中国平安 / 02318**。2025-09-03 起总股本 18,107,641,995 = A 股 10,660,065,083 + H 股 7,447,576,912（此前 18,210,234,607，回购注销后变化）。来源：https://www.pingan.cn/ir/introduction-of-shares.shtml ；http://static.cninfo.com.cn/finalpage/2025-09-03/1224635197.PDF
- **A+B：000550 江铃汽车 / 200550**。总股本 863,214,000 = A 股 519,214,000（流通 518,463,160 + 限售 750,840）+ B 股 344,000,000。来源：http://static.cninfo.com.cn/finalpage/2026-03-28/1225043176.PDF 、http://static.cninfo.com.cn/finalpage/2026-03-28/1225043177.PDF 、https://basic.10jqka.com.cn/000550/equity.html
- 已知：capital 字段只有 `bdrq, plrq, xsltgf, ysltag, zgb`，**没有区分 A/B/H 的字段**。`ysltag` 从字面看是“已上市流通 A 股”，未核实。`fin_hm` 里的 `agdhs/bgdhs/hgdhs` 是股东户数，不是股本，不能用。
- 分析键 `7_share_class.<code>`：`verdict` 取 `includes_non_a`（zgb ≈ 披露总股本）、`a_share_only`（zgb ≈ A 股股本）或 `neither`；`share_class_field_guess` 只列出字段，不据此判定。
- **结论规则**（T-R12b 第 6 条）：不猜字段名，也不按代码段、公司名推断。
  - zgb 含 B/H：清除 `non_a_share_capital`。但识别“哪些公司有 B/H 股”仍然需要字段或外部名单；如果做不到，记 `share_class_check=unavailable`，V5g 不关闭。
  - zgb 只含 A 股：这类公司 PE、PB 记 null（`a_share_only_capital`）。

| 问题 | 实测 |
|---|---|
| 601318 zgb（2025-09-03 之后的行）= 18,107,641,995 还是 10,660,065,083 | 待填 |
| 000550 zgb = 863,214,000 还是 519,214,000 | 待填 |
| ysltag + xsltgf 与 A 股股本是否一致 | 待填 |
| 有无区分 A/B/H 的字段 | 待填（已知：没有） |

## ⑧ 送转数据与除权日（V5d 后半）**[S1]**

- 数据源：`/hscp/jnfh/<code>`，字段 `sdate, rdate, give, change, send, line, cdate, edate, hdate`，'--' 表示空。
  - 推测含义（**待实测确认**）：give = 每 10 股送，change = 每 10 股转，send = 每 10 股派（元），cdate = 除权除息日，edate = 股权登记日，line = 进度（实施、预披露）。
  - 依据：600519 2026 年的行 `edate 2026-06-25 / cdate 2026-06-26`，2002 年的行 `change 1, send 6, cdate 2002-07-25`。
- 样本：600519 2011-07-01 的 10 送 1；000001 平安银行 2016 年 10 转 2（除权日 2016-06-16，巨潮清单第 4 条核对）。
- 分析键：`8_dividend.visibility.<code>.events[*].row_plrq_minus_ex_days`（股本变化行的 plrq 减除权日，天数）、`decision`、`8_dividend.overall_decision`。
- **判定规则（T-R12b 第 4 条，写入结论）**：**如果股本行普遍在除权日之后才可见，就必须接入送转数据**（`must_integrate_dividend_feed`）。接入后，切换时 `share_change_check` 不能是 `unavailable`，T-B55 要按 plan 2.12.1 边界第 2 条执行 `share_change_pending`。脚本口径：任一公司超过半数的送转事件，其股本行 plrq 晚于除权日，就判 `must_integrate_dividend_feed`；都不晚时判 `capital_timely_enough`；没有事件时判 `inconclusive`，V5d 不关闭。
- 另外：如果 ④ 发现 plrq = bdrq 是补录的，即便 `capital_timely_enough` 也有 look-ahead 风险，要一起报给架构师。

| 问题 | 实测 |
|---|---|
| 麦蕊有没有送转数据（jnfh 能否给出送、转比例和除权日） | 待填（已知：有字段，含义待确认） |
| 600519 2011 事件：股本行 plrq − 除权日 = ? 天 | 待填 |
| 000001 2016 事件：股本行 plrq − 除权日 = ? 天 | 待填 |
| 总判定 | 待填（`must_integrate_dividend_feed` / `capital_timely_enough` / `inconclusive`） |

## ⑨ 币种、单位字段（V5h）**[S1]**

- **CDR 样例：689009 九号公司**。开曼群岛注册，10 份 CDR = 1 股基础股票，2020-10-29 在科创板上市，财报以人民币列示。来源：http://www.sse.com.cn/disclosure/announcement/listing/c/c_20201027_5242851.shtml ；https://static.cninfo.com.cn/finalpage/2026-03-31/1225063705.PDF
- 分析键 `9_currency_unit`：`by_response`（每个财报响应里像币种/单位的字段名，以及含“美元、港元、万元”等的字符串值）、`fields_found`、`conclusion`。
- 已知：run-20261101-190106 的 income、balance、cashflow、capital 字段表里都**没有**币种、单位字段。
- **结论规则（T-R12b 第 4 条）**：
  - 没有这类字段时，结论必须写“**只靠数量级不连续检查**”（脚本自动生成）。
  - 有字段时写明字段名；出现非人民币、非元的值 → `unit_mismatch`，不换算。
- 689009 还要核对：CDR 的 zgb 是按股还是按 CDR 份数计（1 股 = 10 份 CDR），这影响 `c × zgb`。

| 问题 | 实测 |
|---|---|
| 有无币种/单位字段（字段名） | 待填 |
| 结论 | 待填（无字段时：“财报响应无币种/单位字段：只靠数量级不连续检查”） |
| 689009 zgb 的单位（股还是 CDR 份） | 待填 |

---

## 巨潮 / 交易所核对清单（0 次麦蕊调用，T-B05 窗口前后都可以做）

1. **①**：600519、000001 的 2025 年报现金流量表，对照经营活动现金流量净额，确认 xj、je 哪个是“经营活动产生的现金流量净额”，以及是否累计口径。
2. **②**：000001、600000、601318 的 2025 年报资产负债表，对照归母权益、负债合计、资产总计，单位应为元。
3. **③**：600525 公告 2025-030（2025-04-29）的更正前后对照表，与麦蕊新旧版本的 gsmgdqsyhj 差值（206.92 万、1,216.51 万）以及新版本 plrq 比对。
4. **④⑧**：600519 2011 年 10 送 1（除权日 2011-07-01，943,800,000 → 1,038,180,000）；000001 2016 年 10 转 2（2015 年度分配实施公告，确认除权日 2016-06-16 和变动后总股本）。
5. **⑥**：2026-10-30 上交所、深交所披露的 600519、000001、601318 总股本和总市值，与 `c × zgb` 比对（偏差 > 0.5% 就记录）。
6. **⑦**：601318 2025-09-03 股本变动公告（A 10,660,065,083、H 7,447,576,912），000550 2025 年报股本结构（A 519,214,000、B 344,000,000）。
7. **⑨**：689009 2025 年报，确认记账本位币和报表单位，以及基础股票数与 CDR 份数的换算。
8. **⑤**：申万二级“保险Ⅱ”最新成分（上文 5 家），确认 2026-11 是否有调整。

## 给架构师的待裁定点

1. capital 中 plrq = bdrq 的行（④）：如果实测是补录的，`next_trading_day(plrq) ≤ d` 会提前看到股本，可能要改用 `max(plrq, first_seen_at)` 或强制接入送转数据。
2. ⑦ 即便 zgb 含 B/H 股，capital 里也没有字段能识别“哪些公司有 B/H 股”。要么接受外部名单（如交易所 B 股列表、A+H 名单），要么 V5g 一直是 `unavailable`。
3. ⑨ CDR 的 zgb 口径（股还是份）如果和日线价格（每份 CDR）不一致，PB、PE 要另加规则或记 null（现有 14 码里只有 `unit_mismatch`、`data_conflict` 可用）。
