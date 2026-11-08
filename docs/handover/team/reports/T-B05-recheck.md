> 最新非盘中结论（2026-11-07 MST）：见 [T-B05-20261107.md](T-B05-20261107.md)。两遍 p13 共同样本一致、四只退市股仍在供应商列表；V5h/名单及链路待验收，盘中未验收，非 T-B05 全部通过。

# T-B05 复测清单（来自 T003 §16 / T007 §6 / security_master v0.2 §8）

- 作者：后端；日期：2026-11-01（MST）
- 用途：合并进 T-B05。本文只列复测方法、调用次数和运行条件。**本次没有调用麦蕊**，所有数字都来自已有的 `run-20261101-190106`。
- 时间写法：交易时段按北京时间（BJT，UTC+8）写，括号里是 MST（UTC−7，比北京时间晚 15 小时，即前一天）。

## 0. 所有复测共用的运行条件

1. 用户按 probes README §5 删除 `src/backend/probes/results/STOP`。STOP 是 2026-11-01 12:08:35 MST 的 103 熔断写入的，后端不动它。
2. 只从一台机器、一个出口 IP 跑，先过 `run_all.py --check-egress`。同一张证书不能同时在别的 IP 上用（103：60 秒内最多 2 个不同 IP）。
3. 沿用 `run_all.py` 现有的约束：单连接、串行、不重试；遇到 429/103 立即熔断并写 STOP；批量接口 `/hsrl/ssjy/all`、`/hsrl/real/all` 每个每分钟最多 1 次。
4. 先跑 `--dry-run` 全部通过，再跑真实调用；跑完对结果目录运行 `scan_licence.py`（结果只会显示“命中/未命中”）。
5. 下面的“调用次数”只计麦蕊调用。NTP 和交易所官网不算。

## 1. 快照延迟：多只股票、多个时段，并记录 NTP 偏差

**原结果**（GAP1）：只有 000001 一只，只有一个时段（BJT 2026-11-02 10:07:44 起，约 30 秒）。`real/time` 采 6 次，延迟中位 7.23 s，最大 9.24 s。`hsrl/ssjy/{code}` 采 6 次，中位 12.53 s，最大 21.86 s，`t` 只变了 2 次。本机与服务端 HTTP Date 头的差值约 +1.6～1.7 s（本机快）。`ntp_offset=unknown`。

**方法**
- 股票（5 只，覆盖各板块）：000001（深主板）、600519（沪主板）、300750（创业板）、688981（科创板）、920000（北交所，取自 `/bj/list/all`）。
- 时段（同一交易日，3 个）：
  - 开盘后：BJT 09:35–09:45（MST 前一天 18:35–18:45）
  - 午后：BJT 13:05–13:15（MST 22:05–22:15）
  - 尾盘：BJT 14:45–14:55（MST 23:45–23:55）
- 每个时段，对 `/hsstock/real/time/{code}` 和 `/hsrl/ssjy/{code}` 轮流各采 6 轮，每轮间隔 5 s。延迟 = 本机收到时刻 − 快照 `t`。同时记录 HTTP Date 头和 RTT。
- NTP：每个时段开始前和结束后，各在 Windows 执行一次 `w32tm /stripchart /computer:ntp.aliyun.com /samples:3 /dataonly`。这条命令只读，不改系统时间。结果写进运行目录。延迟按 NTP 偏差修正后再出分位数。
- 产出：每个 源×股票×时段 的 min/p50/max、`t` 变化次数，以及修正前后两套数字。据此给出 `stale_threshold_s` 建议，由用户确认（T003-gaps-catalog 第 27 行）。

**调用次数**：每个时段 5 只 × 2 个源 × 6 次 = 60 次，加 1 次 `tcalendar`，共 61 次；3 个时段共 **183 次**。每轮 10 次调用之后停 5 s，所以每个时段大约 1.5 分钟。

**运行条件**：必须是交易日（先用 `tcalendar` 判定），时段落在连续竞价内。
- **已实现**（f065f8d，见 probes/README §6A）：`py -3 run_all.py p11 --p11-only gap1 --gap1-codes 000001,600519,300750,688981,920000 --ntp-file <时段前 w32tm 输出> --ntp-file <时段后 w32tm 输出>`。NTP 偏差写进 `GAP1.conclusion.ntp_offset`（原文在 evidence）；未修正和修正后两套 p50/p95/max 都输出（按源、按 源×股票）；`stale_threshold.ref_p95_s` 取修正后 p95。w32tm 输出按“正值 = 本机比 NTP 快”读入，另与 HTTP Date 钟差比对符号（`ntp_sign_check`），符号不一致时先核对再用。dry-run 实测 61 次/时段，盘外 0 次。

## 2. 空值因子复测

**原结果**（GAP6，已经 T-B48 离线重放确认）：
- 600519、300750、000001 都为 null 的有 north_5d_net、north_20d_net、limit_up_streak、seal_ratio、seal_to_float。
- 000001 还有 current_ratio、peg 为 null。
- 文档（factordata 第 58 行）说 north_5d_net、north_20d_net、north_holding_ratio “按设计返回空”。但实测 north_holding_ratio 有值，与文档不一致。
- 文档第 2294 行写“涨跌停每日批算”。

**方法**
- 当天先调 `/hslt/ztgc/{日期}`（涨停股池）取 2 只当日涨停股。再加原来 3 只、688981、920000，共 7 只，逐只调 `factor/all`。
- 盘中跑一次（与原 run 相同，约 BJT 10:00），收盘后再跑一次（BJT 15:30 以后），对比空值集合。
- 判定：
  - limit_up_streak、seal_ratio、seal_to_float 在涨停股上有值 → 属于“非涨停为空”，不是缺数据。
  - current_ratio、peg 只在 000001 上为空 → 可能是银行股不适用。需要对照文档字段说明后再定。

**调用次数**：每次 1 + 7 = 8 次，两次共 **16 次**。

- **已实现**（f065f8d）：盘中 `py -3 run_all.py p11 --p11-only gap6-nulls`，结果里 `conclusion.zt_sampled_at_bjt` 记取样时刻，只选首次封板时间 `fbt` ≤ 取样时刻的股票（研究员要求），按封板先后取 2 只。收盘后用 `--zt-codes <盘中选出的 2 只>` 复跑同一批，仍取 1 次涨停池核对是否仍在池中。dry-run 实测每次 8 次。

**运行条件**：交易日，当天有涨停股。`factor/*` 需要因子包或 Quant Pro 权益，否则返回 403。

## 3. 因子历史 ≥1 周后复取（检查回填）

**原结果**：600519 的 profit_yoy、roe_ttm，`factor/history` 区间 20250501–20261031，limit 400，各 369 个点，各 7 个跳变点（2 个是小数截断）。在 2026-01-30 上，batch 与 history 相等。**原 run 没有保存完整序列**，只保存了跳变点。

**方法**
- 基线：第 4 项的 p11 复跑。代码已在 82b612b 改为把完整序列（≤400 行）存成 `samples/p11_pit_history_{fid}_600519.json`。
- 复取：基线之后至少 7 个自然日。最早是基线 +7 天；如果基线就是 BJT 2026-11-02，那么最早 BJT 2026-11-09。用同样的参数再取一次，逐日比对 `(trade_date, value)`。
- 判定：
  - 已有日期的值发生变化（截断差异除外，用 `p11_gaps.precision_only` 判断） → **回填/改写**。
  - 只在末尾新增日期 → 正常。
- 另外，先拿原 run 的 7 个跳变点和 2026-01-30 的值做一次粗比对。

**调用次数**：每次 2 次（2 个因子 × 1 只）。基线已经含在第 4 项里，复取 **2 次**。如果要扩到 000001、300750，每次 6 次。

**运行条件**：不需要交易时段。复取只需要 p11 的 GAP6 history 部分。**已实现**（f065f8d）：`py -3 run_all.py p11 --p11-only gap6-history --history-baseline <基线 run_id>`，只调 2 次，完整序列另存 `samples/<run_id>/p11_pit_history_*.json`，与基线离线逐日比对（`rewritten` / `no_rewrite`）。注意：基线 run 必须存了完整序列（82b612b 以后的 p11，或 gap6-history）；原 run-20261101-190106 没有存这两个序列，不能当基线。

## 4. T-B48 之后重跑 p11

**方法**：`py -3 run_all.py p11`。核对点：
- GAP6、GAP7 的自动结论与 `p11_gaps.replay-T-B48.json` 一致：85 个因子；空值集合同第 2 项；两个因子 `consistent_with_pit`，`before_disclosure=0`。
- `pit_batch` 的 `equal=true`，`date` 等于 batch 返回的 `trade_date`。
- GAP1、GAP2 的结论与原 run 是同一量级。

**调用次数**：**44 次**（原 run：GAP1 13、GAP2 4、GAP3 5、GAP4 13、GAP5 2、GAP6/7 7）。

**运行条件**：交易日的连续竞价时段（GAP1 需要），且离收盘至少还有约 1 分钟。

## 5. 重跑 p12，看 4 只已退市股何时从列表中消失

**原结果**：`/hslt/list` 仍包含 000016（2026-10-23 终止上市）、301139（2026-10-28 终止上市）、601059、601198（都是 2026-10-19 终止上市），按到 2026-11-02 计已滞后 5–14 天。

**方法**
- 每个交易日收盘后（BJT 15:30 以后）跑一次 `py -3 run_all.py p12`，再离线跑 `compare_mairui_codes.py`。记录这 4 只第一次缺席的日期，以及当天新增的多出、缺失代码。
- 4 只全部消失，或者连续 10 个交易日都还在，就停止。
- 同时检查 security_master §8.4 第 2a 条的 5 个交易日阈值。

**调用次数**：单独跑 p12 每次 5 次（其中 2 次是批量接口），10 个交易日最多 **50 次**。其实只需要 `/hslt/list`（1 次/天）就能观察这 4 只。**已实现**（f065f8d）：`py -3 run_all.py p12 --p12-only hslt`，每天 1 次，10 天 **10 次**；与完整 p11 同次运行时复用 GAP4 的响应，0 次。

**运行条件**：不需要交易时段。两个批量接口之间至少间隔 1 分钟；p12 本身各调一次，已经满足。

## 6. 核实 001381 和 ssjy 多出的基金部分

- **001381 皇冠新材**：现在不在深交所 A 股在市列表里，也不在终止上市名单里，但巨潮已经收录。`ssjy/all` 现价 16.98、量 0；`real/all` 现价 0。
  - 方法：先查深交所和巨潮的上市公告（0 次麦蕊调用）。如果已经公告上市日，在上市日后跑第 5 项，看它是否出现在交易所在市列表中，再按 security_master §8.4 第 2b 条处理。
  - 可选：调一次 `/hsstock/instrument/001381.SZ`，看麦蕊的档案（1 次）。
- **ssjy 多出的 2315 只（15、16、18、50–58 开头）**：
  - 方法：下载上交所和深交所的基金列表（ETF、LOF、REITs 等），离线比对（0 次麦蕊调用）。
  - 或者调用麦蕊基金列表接口。更新日志第 57 行说 `/jj/*` 下开放了全部、ETF、LOF 列表，但我们没有抓这一节的文档，路径待查。估计 1–3 次。
  - 这一项也关系到 api-contract #4：ETF 的 `volume` 单位还没定。

**调用次数**：0～4 次。

## 7. 实现注意（给 T-B05 / 行情接入）

1. **单位**
   - `/hsstock/real/time` 快照的 `v` 单位是**手**（`pv/v=100`），`cje` 单位是元，所以 **VWAP = cje / (v × 100)**。日线 `v` 同样是手，`a` 是元。
   - `/hsrl/ssjy/{code}` 的 `v` 实测单位是**万手**（文档写“手”，与实测不符）。它的 VWAP = cje / (v × 1,000,000)。
   - 实测例子：BJT 10:07:58，600519 的 v=3.69、cje=5,267,908,265，得 VWAP ≈ 1427.6，落在当日高低价之间。
   - 两个源的 `v` 不能混用；入库前统一换算成“股”或“手”。
2. **代码集合**
   - 麦蕊侧的代码集合只用 `lists`（`/hslt/list` ∪ `/bj/list/all` ∪ `/kc/list/all`）。`/hslt/list` 不包含北交所。
   - 合并、对账规则按 security_master §8.4：多出的代码按 a/b/c 判定，主数据 `status` 一律不改；缺失的记 `quote_missing`；全市场行情接口不参与代码对账。
   - `/hsrl/real/all` 的重复代码：重复行完全相同时保留一行；内容不同时整组作废，记 `quote_conflict`。现价为 0 的行视为无行情。
3. **退市状态**：`delisted` 只认交易所终止上市名单，不认麦蕊列表，也不认简称里有没有“退”（4 只里有 3 只简称没有“退”）。退市整理期按交易所在市列表加简称判断（如 002731 萃华退）。
4. **数据源叫法**：用接口路径称呼。麦蕊文档里，单股的 `/hsrl/ssjy/{code}` 标的是“网络数据源”，而全市场的 `/hsrl/ssjy/all` 标的是“券商数据源”（见 T003 §16）。
5. **503**
   - 本次观察到的 503 都是数据缺失型，返回体是 `{"error":"redis history unavailable (cold fallback disabled): redis history miss"}`。出现在 000001 5 分钟 `f` 和 4 只退市股的日线上。
   - FAQ 第 64 行说 503 表示频率过高。在 T-B04a-x 的规则定下来之前，按返回体区分：带 `redis history miss` 的按数据缺失处理，不退避也不重试；其余 503 按频率类处理。

## 研究员确认（2026-11-01 MST）

- 复测清单第 1–7 项确认，口径与 T003-gaps-catalog、T007 §6、security_master v0.2 §8.4、feature_spec 1.0.2 一致。
- 新增的 3 个探针参数确认：p11 的 GAP1 股票列表与只跑 GAP1 开关、只跑 GAP6 history 开关、p12 只取 hslt 开关。只跑必要部分，能减少调用。
- 两点要求：
  - 第 1 项的延迟分位数要同时给出“未修正”和“按 NTP 修正”两套，`stale_threshold_s` 以修正后的 p95 为参考。
  - 第 2 项要记录涨停股的取样时点，限于当时已在涨停池中的股票，避免事后选样。

## 8. T-R12 / T-R12a / T-R12b：财务时点自算实测（p13，2026-11-01 MST 新增）

依据：plan 2.12.1 与 T-B05 行（6efedef、de86b99、1c62952），`T-R12-rulings.md` 的 T-R12a、T-R12b 节。探针 `probes/p13_fin_pit.py` + 离线分析 `probes/p13_analyze.py`，只点名运行，缺省全量不含。
**运行**：`py -3 run_all.py p13`，共 **28 次**，串行、不重试，不需要交易时段；换差错更正样例用 `--p13-restated 600590.SH --p13-announce 2024-11-09 --p13-periods 2023-12-31,2024-06-30`（仍 28 次）。dry-run 阶段 6 已核对 28 次 = 服务端增量（缺省与换样例各一遍）。
结果：`results/run-<…>/p13_fin_pit/`（完整原始响应 + manifest），`p13_analysis.json`（离线分析，开发 box 上可重算：`python3 p13_analyze.py results/run-<…> --stdout`）。结论按 `/workspace/team/reports/T-R12-material.md` 的模板填写，架构师据此提交 `docs/mairui-verified.md`。

探针提交：af589c0（未推送）。dry-run：全量 142 PASS，只跑 p13 108 PASS，0 次麦蕊调用。

| # | 内容 | 调用 | 次数 | 关闭项（feature_spec §11） |
|---|---|---|---|---|
| ① | 现金流：jyhdcsdxjlxj / jyhdcsdxjlje 非空率（'-' 计为空，按年、按季、2015 年起）；xj = jyhdxjlrxj − jyhdxjlcxj；xj 与 je 同时有值时是否相等；是否 YTD 累计 | `financial/cashflow` 600519、000001（银行）、600000（银行）、601318（保险）、300750、600525（更正样例） | 6 | V5c |
| ② | 银行、保险资产负债：gsmgdqsyhj、fzhj、zczj 是否有值，单位（元），权益 ≤0 的行 | `financial/balance` 同 ① 6 只 | 6 | V5b |
| ③ | 同一 jzrq 多个 plrq 版本全量保存；600525 长园集团 2025-04-29 差错更正（2023Q3、2023FY、2024Q1、2024H1、2024Q3）对照巨潮 | `financial/income` 600525（cashflow、balance 复用 ①②） | 1 | V5f |
| ④ | capital 的 plrq 是否等于 bdrq（600519 2011-07-01 10 送 1） | `financial/capital` 600519、000001、601318、000550（与 ⑥⑦ 共用） | 4 | V5d |
| ⑤ | `/hszg/list` 申万一级代码格式；银行、保险节点；有没有申万二级（没有就用引用的保险名单） | `hszg/list` 1 + `hszg/gg` 银行、保险节点各 1（从 list 动态选，选不到就不调）+ `hszg/zg` 000001、601318 | 5 | V5e / V9 |
| ⑥ | PB 分量：不复权 c × zgb 与披露股本、市值对照 | `history/<code>/d/n` 600519、000001、601318（2026-09-01..10-31）；capital 复用 ④ | 3 | G3 抽样（T-B05 ⑥） |
| ⑦ | **zgb 是否包含 B 股、H 股**：601318（A+H）、000550（A+B）对照巨潮；capital 中有没有区分 A/B/H 的字段 | 复用 ④ 的 capital | 0 | **V5g，S1 硬条件** |
| ⑧ | **送转数据与除权日**：麦蕊 `hscp/jnfh` 的送、转、派与除权除息日；送转对应 capital 行的 plrq 相对除权日早还是晚（与 V5d 一起做） | `hscp/jnfh` 600519、000001 | 2 | **V5d，S1 硬条件** |
| ⑨ | **币种、单位字段**：财报响应中有没有这类字段；抽 CDR 689009 九号公司 | `financial/balance/689009.SH` | 1 | **V5h，S1 硬条件** |
| | 合计 | | **28** | |

**⑦⑧⑨ 是 L-01 切换的硬条件**（T-R12b 第 4、6 条，1c62952：S1 必须关闭 V5d、V5g、V5h；①② 对应的 V5b、V5c 以及 ⑤ 的 V5e 也在 S1 关闭项中）：
- ⑦：不猜字段名，也不按代码段或公司名推断。分析脚本只拿 zgb 和巨潮披露的总股本、A 股股本比对，得出 `includes_non_a` / `a_share_only` / `neither`；判定不了时记 `share_class_check=unavailable`。只要还有 `unavailable`，V5g 就不算关闭。实测 zgb 只含 A 股时，这类公司的 PE、PB 记 null（`a_share_only_capital`）。
- ⑧ 判定规则：**如果股本行普遍在除权日之后才可见，就必须接入送转数据**（`overall_decision=must_integrate_dividend_feed`），切换时 `share_change_check` 不能是 `unavailable`。脚本规则：任一公司过半送转事件的股本行 plrq 晚于除权日，就判 `must_integrate_dividend_feed`。
- ⑨：响应里没有币种、单位字段时，结论必须写明“**只靠数量级不连续检查**”（脚本 `9_currency_unit.conclusion`），出现标识或数量级不连续时记 `unit_mismatch`，不换算。

已知（run-20261101-190106 的 p05，0 次新调用）：
- capital 字段只有 `bdrq, plrq, xsltgf, ysltag, zgb`，没有 B/H 字段。`ysltag` 从字面看是“已上市流通 A 股”，待 ⑦ 实测。
- 600519 的 capital 两种行都出现了：`20260630 → plrq 2026-08-15`（半年报日），`20260930 → plrq 2026-09-30`（plrq = bdrq，三季报那时还没披露）。所以 plrq 不一定是披露日（见 material §④）。
- `fin_hm` 有 `agdhs/bgdhs/hgdhs`（A/B/H <account-field>户数），这是户数不是股本，不能用来拆分股本。
- jnfh 字段：`sdate, rdate, give, change, send, line, cdate, edate, hdate`，'--' 表示空。600519 2026 年的行 `edate 06-25 / cdate 06-26`，看起来是股权登记日和除权除息日，待 ⑧ 实测确认。

### 8.1 T-R12e / T-R12f / T-R12g 更新（2026-11-01 20:40 MST）
提交（未推送）：M1 **9e90875**；其余 **d2553ec** + T-R12g 跟进 **076ad51**。p13 仍是 **28 次**调用：
cashflow 6 + balance 5（去掉 600000，`BALANCE_SKIP`）+ income 1 + capital 5（加 689009）+ hszg_list 1 + zg 2 + gg 2 + daily 3 + jnfh 2 + balance_689009 1。
上表 ② 改为 5 次、④ capital 改为 5 只（600519、000001、601318、000550、689009），不调 daily_689009。

- **V5i（capital 季末行可见时点）**：bdrq 为季末且（plrq=bdrq 或 plrq 为季末）时，首次全量回填写入的行可见 = max(next_trading_day(plrq), next_trading_day(bdrq 所属报告期截止日) 09:30)，`basis.pit_basis`（字符串数组）含 `capital_deadline`；增量采集的行取 max(next_trading_day(plrq), first_seen_at)，不套截止日（T-R12g）。探针拉的是全历史，按首次回填口径。
  `4_capital.v5i_backfill`：plrq 为季末的行数；每个季末 bdrq 行与同期 balance/cashflow 最早 plrq 的差天数分布（分位数 + 例子）；verdict ∈ backfilled / true_disclosure / inconclusive（有提前的行（diff<0）占可比行 ≥20% → backfilled；没有提前的行且 ≥80% 在 0–3 天内 → true_disclosure；其余或缺报告 → inconclusive）。每行带 first_seen_at = manifest fetched_at。000550 只出内部统计。
- **V5g（B/H 股）**：`share_class_check` 名单接入前 `unavailable`，接入后全部行 `list`，将来有字段时 `field`；名单成员的 `non_a_share_capital` 取自名单。601318、000550 核对值改为巨潮（带 not_before / at 窗口与来源，标“对照巨潮”）。名单草稿见 **reports/T-R12ef-lists.md**（A+H 211 对、A+B 72 对，带来源和日期；其中 45 对 A+H 是手工映射，须再确认）。不接入应用代码。
- **V5j（CDR 单位）**：CDR 按 `market.securities.type=cdr` 识别，不建名单。689009 的 capital 对照巨潮/上证公告：2024-12-31 717,120,523 份 = 71,712,052.3 股；2025-12-31 720,335,578 份 = 72,033,557.8 股（10 份 = 1 股）。输出 `v5j_cdr_unit` ∈ zgb≈基础股数 / zgb≈CDR份数 / neither。CDR 的 PB 照常算并带 `verify_pending: [cdr_unit]`；只是值上的标记，不写 S2 剔除条款（T-R12g）。zgb≈基础股数 → mcap = c × zgb × 10（按证券配置，草稿见 T-R12ef-lists.md §1）；zgb≈CDR份数 → mcap = c × zgb，无需配置，T-B05 确认后即清除标记。
- 银行、保险只继承标记（601318 的 verify_pending 只剩 `insurance_balance`），照常排名。
- opt-in 改为精确点名（`p13`/`p13_fin_pit`，不再前缀匹配）。
- **lookahead_suspected**：报告里凡出现都列出 date/from/to（见 T-B05-switches.md §1）。
- **tb05_switches 的离线回放**只在给了运行目录时执行（默认 results/run-20261101-190106），没有就 SKIP（README 已注明）。
- dry-run：全量 158 PASS，只跑 p13 123 PASS（d2553ec 时），tr12_fin 52 PASS（含 run-20261101-203803-dryrun-p13 离线回放重算一致），tb05_switches 39 PASS；0 次麦蕊调用，STOP sha256 未变；ruff、secret_scan、gitleaks 都干净。
- mock 的 V5i 判定（只验证脚本，不是实测）：600519、000001、601318、689009 = backfilled，000550 = inconclusive。
