# 特征口径规范 feature_spec（`f.*`）

| 项 | 内容 |
|---|---|
| 版本 | **v1.1.15（T-A153：F23 `f.ann_risk_count_10d` 升为 verified_doc——词表 v3 冻结，B 轮归档同题对照 v2.1→v3 命中 18→16（去掉的恰为 FP-1 300892 / FP-2 300598，新增 0、误伤 0），新样本 1,367 条命中 29、语义误报 1/29=3.45%（95% CI [0.61%,17.18%]）、漏报 0/100（CI [0%,3.70%]）；只到 simulating，不宣称 FP≤5%，FP-3（300550）与 Q-5 扩表并入 v4，样本两日非连续经裁定接受、v4 起连续日纪律；verified_live 仍需 T-A19 两项实测，N-01 KEY_DATA_MISSING 不解除；键数不变）**；此前 v1.1.14（T-R21：按 plan「T-R21 裁定」①–④（86d42f2）：F20、F35、F36、F39、F40、F49 升为 verified_doc（只到 simulating，带限定和缺口）；RSI 全平盘为 null、固定起点重算；一字板改为四价相等且 v>0；主板历史 ST 缺口为 null；键数不变，G2 不豁免）**；此前 v1.1.13（T-R20：按 plan「T-R19 裁定」①–④（78de694）：F19 `f.amount` 升为 verified_doc；F21 写明四字段派生口径，仍为 declared；新增 F50 `f.market_regime_idx`（verified_doc，最多到 simulating），合计 50 个，P0 49；F25、F27 不改）**；此前 v1.1.12（T-R18：按 plan T-A14「T-R18 裁定」（af94de3）新增 §7D 状态登记——F16–F18、F13、F22 改为 `verified_doc`（只到 simulating，附 PIT 限定），F19、F21、F25、F27 保持 `declared`；不是 verified_live，G2 仍阻塞；键数不变）**；此前 v1.1.11（T-R15 第二轮：按 plan 2.5.14 T-R15 第 7 条（f12ef24）新增 F49 `f.is_suspended`——日频布尔、来源日线 `sf`、P0；退市 / 不在列表为 null；分类器 null 按 true；合计 49 个、P0 48 个）**；此前 v1.1.10（T-R13：按 plan 2.12.1“T-R13 补充裁定”，847f41e 写入——V5h 可按“确认没有币种、单位字段”关闭及其抽样范围；`cdr_unit` 逐只清除，V5j 以 689009 的实测为准关闭；CDR 份数判定容差 0.1%，两条都不满足时保留标记并告警 `data_quality`；均为关闭条件，不代表已关闭）**；此前 v1.1.9（T-R12i：按 plan 2.12.1“T-R12h 补充裁定”4，d500474 写入——名单行不加可见时间字段，重算用最新版名单属于更正，回测报告写明 `share_class_list_version`；配对代码定名 `paired_code`（交易所原代码、不加后缀）并加 `paired_market`（`HK` / `SH` / `SZ`））；此前 v1.1.8（T-R12h：按 plan 2.12.1“T-R12h 补充裁定”（7ec6fad）写入 A+B、A+H 名单接入口径——名单放 `config/share_class_list.yaml`，按 `effective_from` / `effective_to` 生效区间取、不得前视；basis 新增 `share_class_list_version`；`verified=false` 的记录照常打 `non_a_share_capital`；V5g 关闭条件加“名单内所有记录 `verified=true`”与“211 对与 209 对的差异已查明”两项）；此前 v1.1.7（T-R12g：按 plan 2.12.1 T-R12f 节中标为 T-R12g 的三点确认（9ad51b8）收尾——截止日规则只用于首次全量回填的季末行，增量季末行取 `max(next_trading_day(plrq), first_seen_at)`；删除 `cdr_unit` 的 S2 剔除条款，`cdr_unit` 只是 F42、F47 值上的标记；CDR 清除条件分两种情况：按份数计 T-B05 确认后即清除，按基础股份计还需转换比例配置接入）；此前 v1.1.6（T-R12f：按 plan 2.12.1“T-R12f 补充裁定”（38d7888）落地 T-R12e 的 8 点——V5i 截止日按 `bdrq` 所属报告期、回填季末行可见时间取 `max(next_trading_day(plrq), next_trading_day(截止日))` 09:30；`basis.pit_basis` 改为字符串数组；`share_class_check` 取值改为 `unavailable` / `list` / `field`；CDR 以 `market.securities.type = cdr` 识别，F43、F48 不另设池剔除；CDR 按基础股份计时的总市值换算与转换比例配置；银行、保险标记照常排序）；此前 v1.1.5（T-R12e：按 plan 2.12.1“T-R12e 补充裁定”（fdd7fdd）落地——新增 V5i（capital 季末行按法定截止日保守可见，`basis.pit_basis = capital_deadline`）、V5j（CDR 股本单位，`verify_pending` 加 `cdr_unit`，不进 PE/PB 行业分位、S2 分子分母同时剔除）；V5g 改为按配置名单识别 B/H 股、新增 `share_class_check = list`、关闭条件重写；§7C S1 加关 V5i、V5j）；此前 v1.1.4（T-R12d：按 plan 2.12.1“T-R12c 补充裁定”（b85b564）收尾——F46 `zczj ≤ 0` 并入 `component_missing` 并发 `data_quality` 告警；`single_period_reason` 优先级改为 plan 已裁定；退市证券不写 null 行）**；此前 v1.1.3（T-R12c：按 plan 2.12.1“T-R12b 补充裁定”（1c62952）落地 `basis.null_reason` 封闭枚举 14 码及优先级、`single_period_reason`、`share_class_check`；`unit_mismatch` 扩到 F45、F46；§7C S1 加关 V5d、V5h）**；此前 v1.1.2（T-R12b：按 plan 2.12.1 T-R12a 裁定（de86b99）补 F42/F44/F47 边界规则与 `basis.null_reason` 原因码、行级待核实标记 `basis.verify_pending`；§7C S2 写入 PB 覆盖率门槛；§11 新增 V5g、V5h）**；此前 v1.1.1（T-R12a：§7A 新增 PB 时点键 F47 `f.pb_pit`、F48 `f.pb_pit_ind_pct`（口径按 plan 2.12.1 PB 裁定）；F45 经营现金流改为已裁定的主备字段；§11 G3 关闭）**；此前 v1.1.0（T-R12：新增 §7A L-01 时点财务特征 F42–F46、§7B plrq 多版本、§7C 线上切换条件；F08/F33/F34 对 L-01 降为对照用；§11 V5 改为部分实测）；v1.0.2（按 T003 探针 run-20261101-190106 p11 更新 §11 V1/V4/V7 状态与 §13 C7；v1.0.1 为 T-R11a/b 修订；v1.0 为 T-R11 首版，2026-11-01）**。本目录此前没有同类文件（已检索 `docs/strategies/`），本文为新建，不是更新 |
| 作者/维护 | 策略研究员（`docs/strategies/` 由研究员维护，架构师不改该目录，plan T-R11 行） |
| 覆盖范围 | 仓库 `docs/`、`config/` 中出现的全部正式特征键 `f.*`，共 **48 个**：分类器 15 个（T-B30a）+ P0 策略卡 25 个（T-B43 / `_template.md` / `catalog.md`）+ L-01 时点财务 7 个（v1.1.0 5 个 + v1.1.1 PB 2 个，§7A，T-B55）+ P1 1 个（`validation.md`）。另列前端 mock 中出现的 11 个**非正式**键（§8），不计入 48 |
| 消费方 | T-B30a（分类器 15 键数据层）、T-B43（P0 策略特征）、T-B35（特征底座 `feature_catalog` / `market.feature_bars_daily`）、T-B42（DSL 求值器） |
| 依据 | `docs/plan.md`（2.5.3、2.5.10/2.5.11、2.5.11A、2.12.1–2.12.2、2.13、3A、第 9 节问题 76/77）；`docs/strategies/horizon_classifier.md` v1.2.0；`_template.md`；`catalog.md`；`market_rules_check.md`；`security_master.md`；`validation.md`；`team/reports/T003-mairui-capability.md`（以下简称 T003）；`team/reports/T-B46-47-rulings.md`（以下简称“裁定”）；`docs/api-contract.md`；v1.1.1 另依据 `team/reports/T-R12-rulings.md`（以下简称“T-R12 裁定”）与 plan 2.12.1 第 1184–1185 行（经营现金流字段、PB，plan 提交 6efedef）；v1.1.2 依据 plan 2.12.1“财务按时点自算”第 1182–1237 行（plan 提交 de86b99，其中经营现金流字段第 1188 行、PB 第 1189 行、边界情况第 1190–1212 行、待核实标记第 1213–1225 行、PB 覆盖率门槛第 1226–1233 行）与 `team/reports/T-R12-rulings.md`「T-R12a」节。下文 v1.1.2 新写的 plan 行号均指 de86b99 版。v1.1.3 依据 plan 2.12.1“T-R12b 补充裁定”第 1237–1271 行（plan 提交 1c62952；原因码表第 1238–1257 行）、§9 问题 96（第 3530 行）与 `T-R12-rulings.md`「T-R12b」节；v1.1.3 新写的 plan 行号均指 1c62952 版。v1.1.4 依据 plan 2.12.1“T-R12c 补充裁定”（b85b564 版第 1272–1275 行）与 `T-R12-rulings.md`「T-R12c」节。v1.1.5 依据 plan 2.12.1“T-R12e 补充裁定”（fdd7fdd 版第 1276–1283 行：第 1 条 capital 可见时间第 1277–1281 行、第 2 条 B/H 股识别第 1282 行、第 3 条 CDR 股本单位第 1283 行）；`T-R12-rulings.md` 暂无「T-R12e」节；参考 `docs/mairui-verified.md` ⑦（V5g 样例公司与巨潮出处）。v1.1.6 依据 plan 2.12.1“T-R12f 补充裁定”（38d7888 版第 1284–1298 行）；`T-R12-rulings.md` 暂无「T-R12f」节。v1.1.7 依据同节中标为 T-R12g 的确认（9ad51b8 版第 1287、1297、1298 行）。v1.1.8 依据 plan 2.12.1“T-R12h 补充裁定”（7ec6fad 版第 1300–1307 行）。v1.1.9 依据同节第 4 条（d500474 版第 1308–1311 行）。v1.1.10 依据 plan 2.12.1“T-R13 补充裁定”，847f41e（847f41e 版第 1313 行起） |
| 不做的事 | 未调用麦蕊接口；未读取证书；未改 src/tests/deploy/config/plan。所有麦蕊接口与字段名**只引自上述文档**，文档未给出的一律标【待核实】。v1.1.0（T-R12）同样未调用麦蕊接口，只读仓库已有探针结果（run-20261101-190106）与巨潮公开原文；L-01 口径依据 `team/reports/L-01-basis-ruling.md` 与 plan 2.12.1。v1.1.1（T-R12a）同样未调用麦蕊接口、未读取证书，只依据 T-R12 裁定与 plan 2.12.1 改文档。v1.1.2（T-R12b）、v1.1.3（T-R12c）、v1.1.4（T-R12d）、v1.1.5（T-R12e）、v1.1.6（T-R12f）、v1.1.7（T-R12g）、v1.1.8（T-R12h）、v1.1.9（T-R12i）、v1.1.10（T-R13）同样只改文档 |

> 与裁定的位置差异：裁定 R9 / plan T-R11 行要求口径写在 `horizon_classifier.md` 附录。本次按任务要求主文写在本文件，`horizon_classifier.md` 末尾只加了“附录：15 个 `f.*` 特征口径与手算样例”指针节（见 §13 冲突 C1）。

---

## 0. 记号与约定

- **d**：特征的**基准交易日**（`feature_bars_daily.trade_date`）。“T−1 盘后落库”即 d = T−1。
- **交易日**：交易所交易日历（`market.trading_calendar`，plan 3A），**不是**“该股有成交的日子”。
- **有效 K 线**（valid bar）：该股在该交易日有日 K 且 `sf ≠ 1` 且 `v > 0`，并且不是 T-B05a 标出的“疑似伪停牌”（日线 `sf=1` 但同日快照有成交，plan 2.5.11A G-01 ②）。T003 已列出的日线字段：`t, o, h, l, c, v, a(成交额), pc(前收), sf(停牌标记)`。
- **null**：特征无法按口径算出时写 `null`（JSON null / SQL NULL）。**一律不得用 0、前值或插值填充**（`_template.md` §7.3“停牌期间不插值”）。0 只在“数据齐全且真实结果为 0”时出现（例如 20 日内确实没有涨停 → `f.limit_up_count_20d = 0`）。
- **取整**：除另有说明外一律 `ROUND_HALF_UP`（四舍五入，非银行家舍入），只在**落库最终值**时取整一次，中间计算保留全精度（Python `Decimal` 或 float64，见 §1.6）。
- **单位记号**（与 `feature_catalog.unit` 对应的建议值）：`CNY`（元）、`CNY_per_share`（元/股）、`pct`（百分数，12 表示 12%）、`ratio`（小数，0.12 表示 12%）、`count`、`years`、`trading_days`、`bool`、`enum`、`code`。`unit: sign` 已取消（C5 裁定），见 §1.5。
- **P0 / P1**：P0 = 分类器（T-B30a 的 15 键）或 P0 策略卡（`catalog.md` 的 9 项：G-01、G-02、H-01、N-01、T-01、S-01、W-01、W-02、L-01）必需；P1 = 只被 P1 卡或验证模块引用。
- 【待核实】= 仓库文档里找不到确证，需 T-B05（麦蕊实测）或架构师确认；【建议】= 研究员提出的口径，尚未经裁定。

---

## 1. 总则（所有特征共用）

### 1.1 可得时点与防未来函数

| 数据类 | 基准日 d 的值何时可得（北京时间） | 依据 | 用于哪次评估 |
|---|---|---|---|
| 日线派生（价、量、额、波动、均线、涨停计数） | d 日收盘快照 15:05 定版，日线落库后（`daily_bars` 新鲜度阈 17:00） | plan 第 146 行（15:05 收盘快照定版）、第 2276 行 `daily_bars_due` | d 日盘后及 d+1 日盘中。**d 日盘中不得使用 d 日的值** |
| 麦蕊因子（`/factor/...`） | d 日 16:30 后 | plan 第 1983 行；T003“因子全是日频，不能用于盘中” | 同上 |
| 资金流日数据 | d 日 15:40 后 | `_template.md` data_needs `f.main_net_20d`；T003 | 同上 |
| 财务报表 | 披露日 `plrq` 的**次一交易日 09:30**（只有日期、无时刻 → 按盘后处理）；`plrq ≤ jzrq` 占位行丢弃；同一报告期多版本取 T 时可见的最新版本（§7A.0、§7B） | plan 2.12.1 第 1179、1182–1237 行（de86b99 版）；`_template.md` `f.np_yoy_latest` | 次一交易日起 |
| 公告 | `max(公告时间戳, first_seen_at)`；盘后/只有日期 → 次一交易日开盘 | plan 2.5.11A ⑦、2.12.2 | 次一交易日开盘起 |
| 证券主数据（上市日期、简称、ST、上市状态） | 每日 18:00 拉取、07:30 补拉 | `security_master.md` §6-1（每个交易日 18:00 拉取、次日 07:30 补拉，均为建议值） | d+1 起（d 日 18:00 前的评估用 d−1 的快照） |
| 申万行业归属 | 每周更新，**无历史成分** | T003 `/hszg/*` | 只能从落库之日起按周快照做时点回看 |
| 盘中特征（VWAP 等） | 每次快照刷新后，只用**已完成**的 1 分钟 bar | catalog T-01；plan 2.5.11A T-01 | d 日盘中（目前 T-01 只做盘后统计，不产生盘中信号） |

规则：
1. 每个 `feature_bars_daily` 行除 `trade_date = d` 外，还应记录 `available_at`（该值最早可被使用的时刻）。求值器只能读 `available_at ≤ 评估时刻` 的行（plan 2.12.1）。
2. 分类器（`horizon_classifier.md` §1）读取“评估时刻前最近一个已完成盘后落库的 d”：交易时段内评估 → d = T−1；T 日日线已落库后（约 17:00 后）的评估 → d = T；周六重算 → d = 周五。快照 `snapshot_id` 记录 d。
3. 前复权序列在每次除权后整列重算（`_template.md` §7.3）。**回测**中任何“价格水平”比较（如低价股 < 2 元、与涨跌停价比较）必须用不复权价，前复权只用于比值类（收益、均线比、波动）。见 §1.3。
4. 历史回算：麦蕊因子是否为“当时口径”未核实（T003、catalog L-01 ④）。**在 T-B05 核实前，因子历史值只用于实时（当日值），回测/回算用本地按本文公式派生的值**，并在 `feature_catalog.pit_rule` 写明。L-01 的 PE、ROE、现金流比、负债率改用 §7A 时点自算键（v1.1.0），PB 改用 F47/F48（v1.1.1）。

### 1.2 窗口与有效 K 线

- 分类器的 “20 日 / 60 日” 特征：窗口 = 截至 d（含）的最近 **N 个交易日**（按交易日历，停牌日占位），只在其中的**有效 K 线**上计算统计量。
- **覆盖率门槛【建议，待架构师确认】**：窗口内有效 K 线数 `n_valid < ceil(0.75 × N)`（N=20 → 15；N=60 → 45；N=120 → 90）→ `null`。理由：`horizon_classifier.md` §6 已规定“20 日窗口的特征在有效 K 线不足时为 null”，但没写阈值；0.75 是研究员建议值，写入 `feature_catalog.pit_rule.min_valid` 以便调整。
- **d 当日本身无有效 K 线**（停牌或伪停牌）时：窗口类特征仍按上式计算（停牌期间值不变的口径与“停牌股不进截面”分开处理，见 §1.4）；但 d 被标为疑似伪停牌（数据错误而非真实停牌）时，d 的所有日线派生特征为 `null`（数据缺失），不得把错误数据当停牌。
- **与 DSL `ma(x,n)` 的区别**：`_template.md` 的 `ma(f.amount, 20)` 是“最近 20 根**有效**日 K”（停牌日不计，第 77、253 行）。分类器特征按“最近 20 个**交易日**”取窗。两者在停牌股上结果不同，属**有意区分**：分类器描述“近一段日历时间里的活跃度”，策略 DSL 描述“最近 n 次成交”。T-B30a 与 T-B42 不得互相复用实现而不加区分。
- **上市不足窗口**：上市首日之前的交易日不是有效 K 线；按覆盖率门槛自然得到 null。
- **注册制新股上市前 5 个交易日**（无涨跌幅限制，`market_rules_check.md` 深 3.3.15 / 沪 3.3.13；`_template.md` §7.3）：从**波动类**窗口（`f.volatility_20d`、`f.intraday_amplitude_20d`、`f.amihud_20d`）和**涨停计数**中剔除，不算有效 K 线；成交额类不剔除。重新上市首日、退市整理期首日同理（同样无涨跌幅限制）。
- **除权日**：比值类一律用前复权序列（qfq），除权日不产生虚假跳空；1 分钟线只有不复权（BarAdjust 注释“1m 只支持 none”），日内窗口跨除权日时截断到除权日开盘（`_template.md` §7.3）。

### 1.3 复权口径

| 类别 | 复权 | 理由 |
|---|---|---|
| 收益、动量、均线比、波动、振幅、RSI、布林带宽 | 前复权 `qfq`（麦蕊路径段 `f`，T003） | 比值不受基准影响；与 `_template.md` data_needs 一致 |
| 成交额、成交量、换手 | 不复权 `none`（`n`） | 量价金额不需复权 |
| 涨跌停价、是否封板、一字板、低价股判断、VWAP、日内偏离 | 不复权 `none` | 与交易所实际价格比较，必须同一价格口径（`market_rules_check.md` 沪 3.3.17 / 深 3.3.19 按“前收盘价”计算） |
| 回测收益归因 | 后复权 `hfq` | plan 2.12.1 第 1162 行；不属于本文特征 |

**一致性要求**：凡是“价格与价格比较”的规则（如 `f.close_qfq > ma(f.close_qfq,20)`）两侧必须同一复权口径；凡是“价格与涨跌停价比较”必须两侧都是不复权。不复权收盘价目前**没有正式键**（见 §11 缺口 G1）。

### 1.4 横截面 `rank_pct`

与 `horizon_classifier.md` §1 的 `rank_pct_universe` **逐字一致**：

> T−1 日盘后落库截面：沪深 A 股股票，剔除北交所、停牌、上市 < 20 个交易日；平均秩 / N，取值 [0, 1]。

细化（不改变上述含义，只补足确定性）：
1. 截面日 = d（同一次评估的所有证券用同一个 d）。
2. 股票池 U(d)：`sec.type = stock` 且 `sec.board ≠ bse`（CDR 的 `security_type = cdr`，不在池内）；d 日有有效 K 线（停牌、疑似伪停牌剔除）；`f.list_days(d) ≥ 20`；**该特征值非 null**。ST/*ST、退市整理期股票**不剔除**（分类器口径；与 plan 2.12.1 “因子池排除 ST/退市整理/上市 < 60 日”不同，见 §13 冲突 C3）。
3. 升序排名（值越大分位越高），并列取**平均秩**；`rank_pct = 平均秩 / N`，N = U(d) 中非 null 的个数。最大值为 1，最小值为 1/N（文档写“[0,1]”是闭区间上界，实际下界 1/N）。
4. 比较时用全精度，不先取整（分档阈值 0.3/0.4/…/0.9，取整可能跨档）；展示时 `{v:pct}` 取 0 位小数。
5. 被评估证券本身不在 U(d)（例如上市 < 20 日、d 日停牌）→ 其 `rank_pct = null`（计入数据缺失）。
6. 多证书隔离（plan 2.1B `per_licence`）：截面按 `source_licence_id` 各算一份；同一证书内必须用同一批落库数据。
7. 【建议】T-B30a 在 d 日盘后把分位一并落库（例如 `values` 中 `f.volatility_20d__rank`），分类器直接读取，避免每次评估重算截面导致结果漂移；截面池版本写进 `feature_set_version`。

分组截面 `rank_pct_in(x, f.sw_l1)`（S-01、L-01）：池同上，再按 d 日有效的 `f.sw_l1` 分组；`f.sw_l1` 为 null 的证券不参与；组内非 null 样本 < 5 时 → null【建议】。

### 1.5 单位与 `unit: sign`

- **已定（C5 裁定，T-R11a）**：不设 `unit: sign`。分类器规则 `SH5/SW2`（`f.ma_trend`）、`SW3`（`f.momentum_60d`）改为 `unit: pct`，与 `feature_catalog.unit = pct` 一致；“只判符号”用阈值 0 表达（`op: gt, value: 0`），文本模板显示 `{v}%`。
- 判定语义不变（null 仍按缺失处理，0 不加分），导入器“拒收单位不一致的规则”的约束照常适用，无需特例。
- 只经 `rank_pct` 使用的特征（换手、波动、振幅）单位不影响分类结果，但仍须在 catalog 写明。

### 1.6 数值精度

- 金额、价格用 `Decimal`；涨跌停价按交易所规则四舍五入到 0.01 元（`market_rules_check.md` 沪 3.3.17、深 3.3.19，含两条边界条款）。
- 统计量（标准差、均值比）用 float64；标准差为**样本标准差（ddof=1）**，布林带宽按惯例用**总体标准差（ddof=0）**，两处分别写明。
- 落库取整位数见各特征“取整”行；比较、分档用落库值（已取整）还是全精度：**分档一律用落库值**（保证用户看到的数与判定一致），`rank_pct` 例外（见 §1.4-4）。

### 1.7 ST、退市整理、北交所

- 北交所：分类器 HG2 直接 0 分；北交所证券不进 `rank_pct` 池；本文的特征**仍可为北交所计算**（G-01 等系统组件可能需要），但不进入分类器截面。北交所涨跌幅 30%（`market_rules_check.md`）。
- ST/*ST：进入 `rank_pct` 池；涨跌停价按 `market_rules.yaml` 分段（沪深主板 ST/*ST 2026-07-06 起 10%、此前 5%；创业板/科创板 20%；北交所 30%）。
- 退市整理期：`f.is_delisting_period = true` → HG3 0 分；其首日无涨跌幅限制（`f.limit_*` 为 null）。
- `listing_status ∈ {delisted, missing_from_list}`：**全部 `f.*` 置为 null**（T-R11b，§10.2 第 4 条），包括 `f.is_st`、`f.is_delisting_period` 等布尔键与主数据派生键，不得返回 false 或 0。

---

## 2. 分类器特征（T-B30a，15 个，全部 P0）

每项字段：名称/含义；公式（窗口、复权、单位、取整）；数据来源；可得时点；边界；rank_pct；引用关系。
分类器读到 null → 按 `horizon_classifier.md` §1 计入数据缺失（`f.is_st` 缺失按 true、`f.is_delisting_period` 缺失按 false、`f.list_days` 缺失按 < 20，三者是该文档已定的默认，不由本文改变）。

**主口径选择**：价量类以“本地由日线派生”为主口径（日线字段 T003 已实测、公式可复算、可做回测），同名麦蕊因子只作**对照**；基本面与换手以“麦蕊因子”为主口径（本地派生所需的报表字段、流通股本历史在仓库文档中均未核实）。对照通过的标准【建议】：T-B05 用同一 d 的全市场截面，本地值与因子值的 Spearman 秩相关 ≥ 0.95 才允许互相替换；否则以主口径为准、因子仅展示。

### F01 `f.amount_20d_avg` — 近 20 日日均成交额
- **含义**：流动性（成交额）规模。
- **公式**：`mean(a_i)`，i ∈ 截至 d 最近 20 个交易日中的有效 K 线；`a` 为日线成交额，**不复权**。单位 `CNY`（元），取整到 1 元。
- **来源**：麦蕊日线 `a`（T003：`/hsstock/history/{code.市场}/d/n/...` 日线字段 t,o,h,l,c,v,a,pc,sf）。`a` 的单位按“元”处理【待核实：T-B05 用 1 只股票的日线 `a` 与同日收盘快照 `cje` 对比确认是“元”而非“万元”】。对照：无同名麦蕊因子。
- **可得时点**：d 日日线落库后（约 17:00）；用于 d+1 盘中评估。
- **边界**：有效 K 线 < 15 → null；停牌日不计入分母也不当 0；IPO 前 5 日计入（成交额类不剔除）；除权日无影响。
- **rank_pct**：不使用（规则按绝对金额分档）。
- **引用**：IT2、SH1、SW1（`horizon_classifier.md`）；P0。

### F02 `f.turnover_20d_avg` — 近 20 日平均换手率
- **含义**：交投活跃度，用于全市场分位。
- **公式（主口径）**：麦蕊因子 `turnover_20d_avg` 原值（规模流动性类 scale，T003 因子表）。因子自身的窗口、停牌处理、单位【待核实：仓库无公式文档】。
- **公式（备选，本地派生）**：`mean(tr_i)`，i ∈ 最近 20 个交易日中的有效 K 线；`tr` 为收盘快照换手（券商源 `tr` / 网络源 `hs`，T003 第 30、32 行）。单位【待核实：疑为 %】，取 4 位小数。只用于 T-B05 对照或因子缺失时的降级。
- **来源**：`/factor/scale/{code}`（T003 因子接口与分类）；备选来源为收盘快照定版（plan 第 146 行）。
- **可得时点**：因子 d 日 16:30 后；用于 d+1。
- **边界**：因子返回空 → null（不得用 0）；北交所不进截面；新股不足 20 日按因子返回为准，并由 HG5 封顶。
- **rank_pct**：使用，口径见 §1.4。
- **引用**：SH2；P0。

### F03 `f.amihud_20d` — Amihud 非流动性
- **含义**：单位成交额引起的价格变动；分类器 v1 只“保留”，**没有规则引用**（`horizon_classifier.md` §5）。
- **公式（主口径）**：麦蕊因子 `amihud_20d`（scale 类）原值，公式【待核实】。
- **公式（备选）**：`mean(|r_i| / a_i)`，`r_i = c_qfq,i / c_qfq,prev − 1`（prev = 上一根有效 K 线），`a_i` 元；有效 K 线同 F04（剔除无涨跌幅日）。单位 `1/CNY`，保留 6 位有效数字。
- **来源**：`/factor/scale/{code}`。
- **可得时点**：d 日 16:30 后。
- **边界**：同 F04；`a_i = 0` 不会出现（有效 K 线要求 v>0）。
- **rank_pct**：v1 不用。
- **引用**：无规则；在 T-B30a 产出清单中 → **P0（产出必需，规则未引用）**。

### F04 `f.volatility_20d` — 近 20 日波动率
- **含义**：价格波动程度，用于全市场分位。
- **公式**：`stdev(r_i, ddof=1)`，`r_i = c_qfq,i / c_qfq,prev(i) − 1`，i ∈ 最近 20 个交易日中的有效 K 线（剔除上市前 5 日、重新上市首日、退市整理期首日），prev(i) = i 之前最近一根有效 K 线（可在窗口外；跨停牌的那一笔收益计入，因为它是真实价格变化）。**前复权**。单位 `ratio`（日收益标准差，**不年化**；年化只是乘常数，不影响分位），保留 6 位小数。
- **来源**：日线 `c`（qfq，路径段 `f`）。对照：麦蕊因子 `volatility_20d`（风险 risk 类，T003）【公式待核实】。
- **可得时点**：d 日日线落库后。
- **边界**：收益个数 < 15 → null；prev 不存在（上市首日）→ 该日无收益；除权日用 qfq 无跳空。
- **rank_pct**：使用。
- **引用**：SH4、SW4、LG5；P0。

### F05 `f.intraday_amplitude_20d` — 近 20 日平均日内振幅
- **含义**：日内价格空间，做T 可行性的核心输入。
- **公式**：`mean(amp_i)`，`amp_i = (h_qfq,i − l_qfq,i) / c_qfq,prev(i)`；窗口、有效 K 线、剔除规则同 F04。前复权（同一序列内的比值，除权日不失真）。单位 `ratio`，保留 6 位小数。
- **来源**：日线 `h`、`l`、`c`（qfq）。对照：麦蕊因子 `intraday_amplitude_20d`（日内 intraday 类，T003 记“样本不足 → null”）；快照字段 `zf`（振幅）可作单日对照。
- **可得时点**：d 日日线落库后。
- **边界**：同 F04。一字板日振幅为 0，是真实值，计入。
- **rank_pct**：使用。
- **引用**：IT1；P0。

### F06 `f.ma_trend` — 均线趋势值
- **含义**：短期均线相对中期均线的位置；> 0 视为多头排列（`horizon_classifier.md` 文本“> 0 为多头排列”）。
- **公式【建议】**：`(MA20 / MA60 − 1) × 100`，`MA20` = 最近 20 个交易日有效 K 线的 `c_qfq` 均值，`MA60` = 最近 60 个交易日有效 K 线的 `c_qfq` 均值。前复权。单位 `pct`，取 2 位小数。规则只用符号。
- **来源**：日线 `c`（qfq）。对照：麦蕊因子 `ma_trend`（信号 signal 类）【公式待核实；若其定义不是 MA20/MA60，T-B05 只核对符号一致率】。
- **可得时点**：d 日日线落库后。
- **边界**：MA20 有效 K 线 < 15 或 MA60 有效 K 线 < 45 → null；上市 < 60 交易日通常为 null，由 HG6 对 swing/long 封顶，对 short 的 SH5 计入数据缺失。
- **rank_pct**：不使用。
- **引用**：SH5、SW2；P0。

### F07 `f.momentum_60d` — 近 60 日动量
- **含义**：中期涨跌方向。
- **公式【建议】**：`(c_qfq(d*) / c_qfq(b*) − 1) × 100`。`d*` = 截至 d 最近一根有效 K 线；`b` = d 往前第 60 个交易日（d 为第 0 个），`b*` = b 当日或之前最近一根有效 K 线。前复权。单位 `pct`，取 2 位小数。
- **来源**：日线 `c`（qfq）。对照：麦蕊因子 `momentum_60d`（动量 momentum 类，T003 因子表 `momentum_5d/20d/60d/120d`）【公式（是否跳过最近若干日、是否复权）待核实】。
- **可得时点**：d 日日线落库后。
- **边界**：`b*` 早于上市首日（上市不足 61 个交易日）→ null；`[b, d]` 内有效 K 线 < 45 → null；**必须用前复权**：不复权在送转股后会把上涨算成下跌（见样例 2）。
- **rank_pct**：不使用。
- **引用**：SW3；P0。

### F08 `f.roe_ttm` — ROE(TTM)
- **含义**：滚动 12 个月净资产收益率。
- **公式（主口径）**：麦蕊因子 `roe_ttm`（质量 quality 类）原值。分类器按 `pct` 使用（12 表示 12%，`horizon_classifier.md` 单位约定）。因子返回单位是 12 还是 0.12【待核实】；若为小数，入库时 ×100 并在 `feature_catalog.derivation` 写明。取 2 位小数。
- **公式（备选）**：v1.1.0 起即 F44 `f.roe_ttm_pit`（§7A，字段 `gsmgsyzzdjlr`、`gsmgdqsyhj` 已实测）。
- **v1.1.0 角色**：对 L-01 **降为对照用**（L-01 改读 F44，切换条件见 §7C）；分类器 SW5、LG0B、LG2 仍读本键（L-01 裁定“分类器不变”）。
- **来源**：`/factor/quality/{code}`；报表 `/hsstock/financial/{income|balance}/...`（T003）。
- **可得时点**：因子 d 日 16:30 后；底层财报遵循 `plrq` 次一交易日 09:30 规则（因子是否已按此对齐【待核实】，T-B05 核对一家在 d 日盘后披露年报的公司 d 与 d+1 的因子值）。
- **边界**：负 ROE 是真实值，保留负数；无财报/因子空 → null（LG0B 封顶）；金融股无特殊处理。
- **rank_pct**：不使用。
- **引用**：SW5、LG0B、LG2；L-01 对照（v1.1.0 前为 L-01 质量护栏）；P0。

### F09 `f.profit_cagr_3y` — 近 3 年净利润复合增速
- **含义**：成长性。
- **公式（主口径）**：麦蕊因子 `profit_cagr_3y`（成长 growth 类）原值。T003 记：基期 ≤ 0 时为 null（因子文档）。窗口是“年报对年报”还是“TTM 对 TTM”【待核实】。按 `pct` 入库，取 2 位小数，单位换算同 F08。
- **来源**：`/factor/growth/{code}`。
- **可得时点**：d 日 16:30 后。
- **边界**：基期 ≤ 0 → null（计入数据缺失，**不得**当 0 或负数）；上市不足 3 年 → null。
- **rank_pct**：不使用。
- **引用**：LG3；P0。

### F10 `f.dividend_continuous_years` — 连续分红年数
- **含义**：截至最近会计年度连续现金分红的年数。
- **公式（主口径）**：麦蕊因子 `dividend_continuous_years`（分红 dividend 类，T003/catalog 标“试用”）。“连续”的起算年度、是否只计现金分红、送转是否计入【待核实】。单位 `years`，整数。
- **来源**：`/factor/dividend/{code}`。
- **可得时点**：d 日 16:30 后。
- **边界**：**0 与 null 必须区分**：从未分红应为 0（真实值，LG4 不加分）；因子返回空才是 null（计入数据缺失）。若 T-B05 发现麦蕊对“从未分红”也返回空，则该键在 v1 中按 null 处理并在 catalog 标 `status=gap`，不得自行改成 0。
- **rank_pct**：不使用。
- **引用**：LG4；L-03（P1）；P0。

### F11 `f.limit_up_count_20d` — 近 20 日涨停次数
- **含义**：情绪活跃度。
- **公式**：`count(f.is_limit_up_close = true)`，i ∈ 最近 20 个交易日中的有效 K 线（剔除无涨跌幅限制日，见 §1.2）。“涨停”= **收盘价等于涨停价**（不复权 `c` 与 F37 `f.limit_up_price` 逐分比较），盘中触及后打开不算。单位 `count`，整数。
- **来源**：本地派生（日线 `c` + 涨跌停价）。对照：麦蕊因子 `limit_up_count_20d`（情绪 sentiment 类）【口径（收盘封板 or 盘中触板）待核实】；涨停股池 `/hslt/ztgc/{date}` 只有约 30 天历史（T003），只作近期对照。
- **可得时点**：d 日日线落库后。
- **边界**：有效 K 线 < 15 → null；窗口内任一有效日的 `f.limit_up_price` 为 null（例如前收缺失）→ 整个特征 null；停牌日不计；ST 按其当日涨跌幅比例（2026-07-06 前主板 5%）。
- **rank_pct**：不使用。
- **引用**：SH3；P0。

### F12 `f.fin_report_count` — 已披露财报期数
- **含义**：基本面历史完整度（≥ 12 期 ≈ 3 年季报）。
- **公式**：`count(distinct jzrq)`，计入条件：该报告期的利润表在 d 日收盘时已可得，即 `next_trading_day(plrq) ≤ d`（`plrq` 只有日期 → 按盘后，次一交易日 09:30 可得，plan 2.12.1）。一季报、半年报、三季报、年报各算 1 期；同一报告期的更正/补充/次年比较数不重复计；`plrq ≤ jzrq` 的占位行不计（v1.1.0，§7B R1）。单位 `count`，整数。
- **来源**：`/hsstock/financial/income/{code}`（T003）字段 `jzrq`（截止日期）、`plrq`（披露日期）【两字段名见 T003，返回内容未实测：待核实】。
- **可得时点**：随财报，次一交易日 09:30。
- **边界**：接口无数据 → null（不是 0）；`plrq` 为空的历史期【建议】按法定最晚披露日估计可得日（一季报/三季报次月末、半年报 8 月 31 日、年报次年 4 月 30 日，出处待补：仓库内未找到），并在 `pit_rule` 标 `estimated_available`；只统计上市后的报告期还是含招股书期【待核实】。
- **rank_pct**：不使用。
- **引用**：LG0、LG1；P0。

### F13 `f.list_days` — 上市交易日数
- **含义**：上市以来经过的交易日数（含停牌日）。
- **公式**：`count(交易日 t : list_date ≤ t ≤ d)`，上市首日计 1。按**交易所交易日历**计，停牌日照计（与“有效 K 线”无关）。单位 `trading_days`（`inputs.py` 已登记该单位），整数。
- **来源**：主数据 `list_date`（交易所列表为唯一权威，`security_master.md` §2）；交易日历 `market.trading_calendar`。`list_date_basis = neeq_select`（北交所平移股）不适用（北交所已被 HG2 排除）。
- **可得时点**：主数据 18:00 拉取后（上市日期本身事前已知，无未来函数风险）。
- **边界**：`list_date` 缺失 → null（分类器按 < 20 处理）；`list_date > d` → null（尚未上市）；转板/换码按 `security_code_history` 追溯到同一 `security_id`，上市日不重置【建议】。
- **rank_pct**：不使用；但它决定截面池（≥ 20）。
- **引用**：HG5、HG6；G-01（上市不满 30 个交易日，`catalog.md` / plan 2.5.11A ①）；T-B43；P0。

### F14 `f.is_st` — 是否风险警示
- **含义**：ST、*ST 或简称含“退”的证券。
- **公式**：`risk_flag ∈ {st, star_st, delisting}` → true；`risk_flag` 为空 → false；**证券主数据缺失**（找不到该证券或当日快照缺失）→ null（分类器按 true 处理）。与 `src/backend/app/strategy/horizon/inputs.py` 现有实现一致（裁定 R9、review-c9e1e73 m2）。
- **来源**：主数据 `security_risk_flag`（`security_master.md` §5-5：简称以 `*ST` 开头 → `*ST`；否则以 `ST` 开头 → `ST`；含“退” → `退`；同时命中取最高：`delisting > star_st > st`，契约 `security_risk_flag` 行）。历史用 `security_risk_flag_history`（valid_from/valid_to）。
- **可得时点**：d 日 18:00 主数据拉取后，用于 d+1；回测按 `valid_from ≤ t < valid_to` 取当日区间。
- **边界**：戴帽/摘帽生效日以简称变化日为准；沪/京无官方历史，只能从上线日起做每日差分（`security_master.md` §5、T007）。
- **rank_pct**：不使用；ST 股仍在截面池内。
- **引用**：HG4；G-01 `ST_OR_DELISTING`（plan 第 738 行）；P0。

### F49 `f.is_suspended` — 当日是否停牌（T-R15 第二轮，plan 2.5.14 T-R15 ④⑦，f12ef24）
- **公式**：**只认** d 日日线停牌标记 `sf`：`sf = 1` → true；`sf = 0` → false；当日日线缺失或 `sf` 为空 → null，G-01 按 `KEY_DATA_MISSING` 处理为不可执行；**不得用零成交量或缺 K 线推断停牌**（T-R21 裁定①）。伪停牌交叉校验（日线 `sf=1` 但同日快照有成交 → `suspect`，T-B05a）不改本键取值，由 G-01 按数据缺失处理。日频 `bool`，不复权。
- **来源**：麦蕊日线 `sf`（T003 已实测字段存在）。
- **可得时点**：d 日日线入库后（盘后），用于 d 日盘后求值与 d+1。
- **边界**：证券已退市（`delisted`）或不在列表中（`missing_from_list`）→ null，与 F14 相同（T-R11b `all_null_when`）；不得用前值或 false 填补。
- **分类器**：读到 null 时按 true 处理（保守，plan 2.5.14 T-R15 ⑦）。
- **引用**：G-01 `SUSPENDED`（买卖两个方向，`direction` 取 buy/sell，T-R15 ⑩）；W-01、H-01 夹具（`docs/strategies/cards/`）；P0。

### F15 `f.is_delisting_period` — 是否退市整理期
- **公式**：`listing_status = delisting_period` → true；`listing_status` 为其他非空值 → false；`listing_status` 为空 → null（分类器按 false 处理）。与 `inputs.py` 现有实现一致。
- **来源**：主数据 `listing_status`（契约枚举 `listed / delisting_period / delisted / missing_from_list`；`delisting_period` 靠简称含“退”识别，`security_master.md` §5-1）。
- **可得时点**：同 F14。
- **边界**：退市整理期首日无涨跌幅限制；`delisted / missing_from_list` 返回 null（与其他特征一致，T-R11b），见 §10.2 第 4 条。
- **引用**：HG3；G-01（退市整理期）；P0。

---

## 3. P0 策略特征：日线基础（T-B35 / `_template.md` data_needs）

### F16 `f.close_qfq` / F17 `f.high_qfq` / F18 `f.low_qfq` — 前复权收、高、低价
- **含义**：日 K 的前复权价格序列，DSL `ma`、`atr`、`highest`、`pct_change` 的输入。
- **公式**：麦蕊前复权日线 `c` / `h` / `l` 原值（路径段 `f`）。单位 `CNY_per_share`，2 位小数（前复权价可能出现 3 位以上小数，按麦蕊返回值原样落库，比较时不再取整【待核实：麦蕊前复权价的小数位】）。
- **来源**：`/hsstock/history/{code.市场}/d/f/...`（T003 URL 模式，`f` = 前复权）；`_template.md` data_needs。
- **可得时点**：d 日日线落库后；**每次除权后整列重算**，重算后 `feature_set_version` 不变、但必须让依赖它的派生缓存失效（`_template.md` §7.3）。回测中只能用于比值，不得与不复权价（涨跌停价、2 元门槛、成本价）直接比较。
- **边界**：停牌日无行（不插值、不前值填充）；伪停牌行按数据缺失；新股首日即有值。
- **引用**：W-01（`_template.md` 全部 entry/exit 规则）、S-01、W-02（突破 20 日最高收盘）、H-01（跌破 MA60）、`atr(14)`（需高低收三列）；G-02 的指数版本见 F27；P0。

### F19 `f.amount` — 当日成交额
- **公式**：日线 `a`，不复权，单位 `CNY`（单位待核实同 F01），取整到元。
- **来源**：日线 `a`；`_template.md` data_needs `adjust: none`。
- **可得时点**：d 日日线落库后。
- **边界**：停牌日无行；DSL `ma(f.amount,20)` 取最近 20 根有效 K（与 F01 的区别见 §1.2）。
- **引用**：W-01 `universe.liquidity` 与缩量规则、S-01（回踩日成交额 < 5 日均额 × 0.7）、W-02（≥ 20 日均额 × 1.5）、冲击成本 `ADV_N = ma(f.amount, N)`（`_template.md` 第 253 行）；P0。

### F20 `f.rsi14` — RSI(14)
- **公式**：Wilder RSI(14)，输入 `c_qfq`：首个平均涨幅/跌幅取前 14 个收益的简单平均，此后 `avg_t = (avg_{t−1}×13 + x_t)/14`；`RSI = 100 − 100/(1 + avg_gain/avg_loss)`；`avg_loss = 0` 且 `avg_gain > 0` 时 RSI = 100；**全平盘（avg_gain = avg_loss = 0）→ null**，不取 50（T-R21 裁定②）。只在有效 K 线上递推（停牌日跳过）。单位：0–100 的指数值，取 2 位小数。
- **来源**：本地派生（`_template.md` data_needs：Wilder、warmup 28）；对照：麦蕊因子 `rsi_14`（signal 类）。
- **可得时点**：d 日日线落库后。
- **边界**：有效 K 线 < 28（warmup）→ null；除权用 qfq；**每个 as_of 用完整 qfq@as_of 序列，从固定起点（可得序列首日，记入 pit 元数据）重新计算**，不沿用旧快照递推；回测与实盘必须用同一起点（T-R21 裁定②）。
- **引用**：W-01 `ex_overheat`（`f.rsi14 > p.rsi_overheat`）；P0。

---

## 4. P0 策略特征：资金、财务、公告（T-B43）

### F21 `f.main_net_20d` — 近 20 日主力净流入
- **公式（v1.1.13 按 plan「T-R19 裁定」②采纳四字段派生，不用内置因子）**：`Σ_{最近 20 个交易日} (zmbtdcje + zmbddcje − zmstdcje − zmsddcje)`，即主买特大单 + 主买大单 − 主卖特大单 − 主卖大单，买为正、卖为负。求和范围为最近 20 个交易日中有资金流记录的有效 K 线日。**单位与盘后定稿时间仍缺证**（T-B81 原始单位未核实），实测前不取整也不换算。麦蕊内置因子 `main_20d_net` 与四字段和不等价（T-B81：688018 内置 12807880，四字段和 1499643492），不得替代。T003：“主力净流入 = 特大+大单主买 − 主卖（与因子文档口径一致）”。
- **来源**：`/hsstock/history/transaction/{code}`（T003）；字段示例 `zmbtdcje`、`zmstdcje`（T003 原文“如 zmbtdcje、zmstdcje…”）；**大单对应的字段名、成交额单位【待核实】**。对照：麦蕊因子 `main_20d_net`（资金 capital 类）——注意因子 ID 是 `main_20d_net`，特征键是 `main_net_20d`，两者词序不同，T-B43 映射时不要写错。
- **可得时点**：d 日 15:40 后（`_template.md`）。
- **边界**：有效 K 线 < 15 → null；某日资金流缺失而当日有成交 → 整个特征 null（不得当 0）。
- **引用**：W-01 counter（缺失 → `dimension_unknown`）；W-03（P1）；P0。

### F22 `f.np_yoy_latest` — 最新一期归母净利润同比
- **公式**：取 `next_trading_day(plrq) ≤ d` 的最新一期报告（按 `jzrq` 最大，同 `jzrq` 取最晚披露版本），`(NP_本期 / NP_上年同期 − 1) × 100`；两期都是“年初至报告期末”累计口径。单位 `pct`，2 位小数。
- **来源**：`/hsstock/financial/income/{code}`；`jzrq`、`plrq` 见 T003；净利润字段 = `gsmgsyzzdjlr`（归母，v1.1.0 已实测，§7A.0）。版本选择按 §7B R1–R2（“同 `jzrq` 取最晚披露版本”指 T 时可见版本中最晚的）。对照：麦蕊因子 `profit_yoy`（growth 类，基期 ≤ 0 为 null）。
- **可得时点**：披露日次一交易日 09:30（`_template.md` data_needs，plan 2.12.1）。
- **边界**：上年同期 ≤ 0 → null；上年同期缺失 → null；更正公告覆盖原值时，回测必须按各版本的披露日取当时可见值（plan 2.12.1 第 1157 行“按当时可得”）。
- **引用**：W-01（`_template.md` 夹具 `f.np_yoy_latest: 12.0`；null 夹具 → 数据缺失分支）；W-05（P1）；P0。

### F23 `f.ann_risk_count_10d` — 近 10 个交易日风险公告数
- **公式**：评估日 D 的值 = 满足以下全部条件的公告条数：① 标题 `zt` 命中 `event_definitions` 中当前版本的风险关键词表（catalog N-01：立案调查、退市风险警示、重大违法、非标审计意见、控股股东大比例减持、交易所问询函等，具体词表由 T-B43 版本化）；② 可交易时刻 `available_from = max(t, first_seen_at)` 规整后（盘中 → 下一根 1 分钟 bar；盘后/只有日期 → 次一交易日开盘）`≤ D 09:30`；③ `available_from` 所在交易日位于 D 及其之前共 10 个交易日内。同一链接 `nr` 去重。单位 `count`，整数。
- **来源**：`/hsstock/announcement/{code}`（T003 第 106 行、plan 第 2041 行：字段 `t` 时间、`zt` 标题、`zy` 摘要、`gs` 格式、`nr` 链接、`jb` 级别、`lx` 0 其他/1 财报类；**交易日盘后更新**；接口已实测（V7，run-20261101-190106/p11；`t` 只到日），关键词表 v3 已实测并冻结）。
- **可得时点**：公告盘后更新（plan 2.5.11A ⑦），因此 D 日的值在 D−1 晚间拉取后即确定，D 日 09:30 生效。
- **边界**：公告数据源缺失或过期（新鲜度不达标）→ **null**（不是 0），买入方向草案被 `KEY_DATA_MISSING` 阻断（plan 2.5.11A N-01 ④）；数据新鲜且无命中 → 0。关键词表版本变化时 `feature_set_version` 递增。
- **状态**：verified_doc（v1.1.15，plan「T-A153 裁定」）。证据：词表 v3 冻结（`T-R62/rules_freeze_v3.yaml`，lexicon `8a545da8…`、matcher `d3e930a8…`）；B 轮归档 1,490 条同题对照 v2.1→v3 命中 18→16，去掉的恰为 FP-1（300892「参与他方破产重整投资」）/FP-2（300598「承诺不通过二级市场主动减持」），新增 0、误伤 0；新样本 1,367 条命中 29、语义误报 1/29=3.45%（95% CI [0.61%,17.18%]）、漏报 0/100（CI [0%,3.70%]）；`check_f23_v3.py` PASS（20 例回归）。限定：最多到 simulating，**不宣称 FP≤5%**（区间上界 17.18%）；样本为两个非连续交易日（11-02、11-06，T-A153 接受，v4 起连续日纪律）；FP-3（300550 控制人内部协议转让）与 Q-5 扩表并入 v4，300550 为首验证用例；`verified_live` 仍需 T-A19 两项实测（新鲜度 ≥95%、完整性 10 条漏 0），N-01 的 `KEY_DATA_MISSING` 不因此解除。
- **引用**：N-01；W-01 veto；H-01（风险公告）；P0。

---

## 5. P0 策略特征：市场环境与行业（G-02、S-01、W-01、L-01）

### F24 `f.market_breadth` — 市场宽度（上涨家数占比）
- **公式【建议】**：`上涨家数 / 有效家数`。池 = d 日沪深 A 股股票（剔除北交所、`security_type ≠ stock`）且 d 日有成交；“上涨” = 收盘快照涨跌幅 `pc > 0`（T003 网络源/全市场快照字段 `pc` 为涨跌幅%）。单位 `ratio`，4 位小数。G-02 规则用其 20 日均值（`ma(f.market_breadth, 20)`，与 50% / 40% 比较时写成 0.5 / 0.4）。
- **来源**：收盘快照 `/hsrl/ssjy/all`（15:05 定版，plan 第 146 行；catalog G-02“约 7,970 只/次”，所以必须按主数据过滤出沪深 A 股，过滤规则同 §1.4）。历史需逐只日线回算（catalog G-02）：回算口径用日线 `c` 与 `pc`（前收）计算 `c > pc`，与快照口径在除权日可能不同【待核实：日线 `pc` 在除权日是否为除权参考价】。
- **可得时点**：d 日 15:05 后。
- **边界**：快照缺失 → null（G-02 产出 `f.market_regime = null`，RC3 按缺失处理）；平盘不算上涨；停牌股不进分母。
- **引用**：G-02；P0。

### F25 `f.market_regime` — 大盘状态
- **公式**：枚举 `uptrend / range / downtrend`（与 API 枚举 `market_regime` 一致，plan 2.5.14 H⑥）。按 catalog G-02 示例：`uptrend` = 沪深300 收盘 > MA60 且 MA20 > MA60 且 `ma(f.market_breadth,20) > 0.5`；`downtrend` = 收盘 < MA60 且 MA20 < MA60 且 宽度均值 < 0.4；其余 `range`；**连续 2 日**满足才切换（防抖）。阈值为示例，正式值在 G-02 卡中定。
- **来源**：沪深300 指数日线 `/hsindex/history/{code}/{级别}`（T003；指数代码写法与是否复权【待核实】）；F24。
- **可得时点**：d 日盘后（指数日线 + 宽度都到齐后）。
- **边界**：指数 MA60 不足 45 根有效 K → null；宽度 20 日均值有效值 < 15 → null；任一 null → `f.market_regime = null`（不得默认为 `range`）。情绪周期 6 阶段在涨停池积累前不输出。
- **引用**：G-02 产出；RC3；P0。RC3 继续读 F25，不改读 F50（plan.md:984 T-R21 裁定⑦、api-contract.md:1236；T-R51 按架构师 T-A116 ⑤ 更新本行）。F25 与 F50 不是同一量的新旧名：枚举相同，但 F25 含 F24 宽度条件，F50 只用指数，两者取值可能不同。F25 缺失时 RC3 只记 gap、显示「大盘环境未知」、不改门控。W-01 只在 v1 夹具用过 F25（冻结在 `cards/history/sw_ma_trend_pullback.v1.md`）；现行 W-01 v2（V1/I2）与 H-01 v2/v3（C1）已改用 F50。

### F50 `f.market_regime_idx` — 大盘状态（指数口径，不含宽度；v1.1.13，plan「T-R19 裁定」③）
- **公式**：枚举 `uptrend / range / downtrend`，判定方式与 F25 一致，只去掉宽度条件：`uptrend` = 000300.SH 收盘 > MA60 且 MA20 > MA60；`downtrend` = 收盘 < MA60 且 MA20 < MA60；其余为 `range`。须**连续 2 日**满足才切换（防抖）；切换之前保持上一个已确认状态，序列开头没有已确认状态时取当日原始判定。MA 为最近 N 根有效指数日 K 的收盘均值。阈值和防抖天数沿用 F25，没有另加条件。
- **来源**：沪深300 指数日线 `/hsindex/history/000300.SH/d`（hszsdata 文档；T-B81 实测：目录精确给出 dm=000300.SH、jys=SH，日线返回 64 根）；`adjust: none`（指数不做除权复权，按裁定③）。**不依赖 F24**。
- **可得时点**：d 日指数日线落库后（盘后）；具体落库时刻【待核实】。
- **边界**：MA60 的有效 K < 45 → null；当日指数日线缺失 → null；null 不默认为 `range`。预热：MA60 加防抖需要 61 根（最少 45+1 根）。
- **单位**：enum（没有数值单位）。
- **状态**：verified_doc（hszsdata 文档 + T-B81 日线实测，裁定③），最多到 simulating。原 F25 `f.market_regime` 不改，仍为 declared。
- **引用**：H-01 v2/v3（C1；v3 见 `cards/hold_risk_monitor.md:111` 规则、:63 data_needs、:129 证伪口径仅分组展示）、W-01 v2（V1、I2、applicability）；P0。

### F26 `f.sw_l1` — 申万一级行业
- **公式**：d 日有效的申万一级行业代码（字符串）。
- **来源**：`/hszg/zg/{code}`（个股所属板块，T003 示例 `sw2_650300` 为申万二级），一级代码由 `/hszg/list` 板块树向上取父节点【一级代码格式待核实】。
- **可得时点**：每周更新；**无历史成分**（T003）→ 从落库之日起每周快照存历史，回测在落库日之前一律 null（不得用今天的行业回填过去，防止前视偏差）。
- **边界**：未分类/新股 → null（不进 `rank_pct_in` 分组）；行业调整按快照生效日。
- **引用**：S-01（行业内排名分支）、L-01（`per_group_cap`、行业内分位）、W-04（P1）；P0。

### F27 `f.ind_rs20` — 行业 20 日相对强度
- **公式**：`(R20(申万一级行业指数) − R20(中证全指)) × 100`，`R20 = close(d)/close(d−20 个交易日) − 1`；单位 `pct`（百分点），2 位小数（`_template.md` 夹具 `f.ind_rs20: 1.5`）。
- **来源**：`_template.md` data_needs 定义；行业指数行情来源【待核实：T003 记板块接口只有成分与归属，“无板块实时行情”；若麦蕊 `/hsindex/history` 不支持申万指数，需由成分股日线自行合成，加权方式待研究员另定】；中证全指代码【待核实】。
- **可得时点**：d 日盘后。
- **边界**：任一指数缺失 → null；`f.sw_l1` 为 null → null。
- **引用**：W-01；W-04（P1）；P0。

---

## 6. P0 策略特征：日内（T-01，目前只做盘后统计）

### F28 `f.vwap_intraday` — 当日累计 VWAP
- **公式**：`vwap_t = 当日截至 t 的累计成交额 / 累计成交量（股）`；不复权；单位 `CNY_per_share`，保留 4 位小数。
- **来源**（catalog T-01）：实时快照累计成交额 `cje` 与成交量 `v`（T003 已实测字段存在）；或 1 分钟 K（Pro，不复权，【待 T003】）逐根累加。**`v` 是“手”还是“股”【待核实】**（catalog T-01“单位换算待核”）——若为手需 ×100，否则 VWAP 会差 100 倍。
- **可得时点**：d 日盘中，每次快照刷新；只用已完成的 bar；09:30 前（集合竞价）不计算。
- **边界**：累计成交量 0 → null；停牌 → null；跨除权日不跨日，不受影响。
- **引用**：T-01；P0（P0 卡，但 `scan.mode = post_close_stats`）。

### F29 `f.vwap_dev` — 价格相对 VWAP 偏离
- **公式**：`(p_t − vwap_t) / vwap_t`；`p_t` 为同一时刻快照最新价 `p`（不复权）。单位 `ratio`（0.012 = 1.2%；catalog 阈值“1.2%”写成 0.012）。保留 6 位小数。
- **可得时点 / 边界**：同 F28；`vwap_t` 为 null → null。
- **引用**：T-01；P0。

### F30 `f.intraday_sigma` — 日内累计波动
- **公式**（catalog T-01）：`σ_t = stdev(r_i, ddof=1) × sqrt(n)`，`r_i` 为当日**已完成** 1 分钟 bar 收盘价相对上一根的收益（当日第一根不计，不含隔夜跳空），n 为已完成收益个数。不复权（同日内无除权）。单位 `ratio`，6 位小数。
- **来源**：1 分钟 K 线 Pro `/hsstock/pro/history/{code}/1/n`【未实测】，或按快照重采样到 1 分钟。
- **可得时点**：d 日盘中；T-01 触发窗口 09:45 起。
- **边界**：n < 15 → null【建议，对应 09:45 前不触发】；午间休市不产生 bar。
- **引用**：T-01；P0。

---

## 7. P0 策略特征：形态、估值、涨跌停

### F31 `f.boll_bw20` — 20 日布林带宽
- **公式**：`bw = (上轨 − 下轨) / 中轨 = 4 × std_pop(c_qfq, 20) / MA20(c_qfq)`（k = 2；标准差为总体标准差 ddof=0，布林带惯例）。最近 20 根**有效** K 线（W-02 是策略 DSL 口径，按有效 K 线，§1.2）。前复权。单位 `ratio`，6 位小数。
- **来源**：本地派生（catalog W-02）；对照：麦蕊因子 `boll_squeeze`（signal 类）【口径待核实】。
- **可得时点**：d 日日线落库后。
- **边界**：有效 K 线 < 20 → null。
- **引用**：W-02；P0。

### F32 `f.boll_bw20_pct120` — 布林带宽在自身 120 日中的分位
- **公式**：`ts_pct_rank(f.boll_bw20, 120)` = 当前值在自身最近 120 个**非 null** 值（含当前）中的分位，平均秩 / n（与 §1.4 同一平均秩规则；plan 2.5.14 ⑤“当前值在自身最近 n 根中的分位 0–1”）。单位 `ratio`（0–1），4 位小数。W-02 条件“≤ 20%”写成 ≤ 0.2。
- **边界**：可用值 < 90 → null【建议，覆盖率 0.75】。
- **引用**：W-02；P0。

### F33 `f.pe_ttm` — 市盈率 TTM
- **公式**：麦蕊因子 `pe_ttm`（估值 valuation 类）原值；单位“倍”，2 位小数。亏损公司返回负数还是空【待核实】。
- **来源**：`/factor/valuation/{code}`；快照字段 `pe`（T003）只作对照（口径可能是动态 PE，不得混用）。
- **可得时点**：d 日 16:30 后。
- **边界**：空 → null；≤ 0 保留原值但不进入 F34 的分位计算。
- **v1.1.0 角色**：对 L-01 **降为对照用**，L-01 改读 F42 `f.pe_ttm_pit`（切换条件 §7C）。
- **引用**：L-01 对照（v1.1.0 前为 `rank_pct_in(f.pe_ttm, f.sw_l1)`）；P0。

### F34 `f.pe_ttm_ind_pct` — PE_TTM 行业内分位
- **公式**：`rank_pct_in(f.pe_ttm, f.sw_l1)`：池 = §1.4 股票池（L-01 另可叠加 plan 2.12.1 因子池排除，由卡决定）且 `f.pe_ttm > 0`；按 d 日 `f.sw_l1` 分组；组内升序平均秩 / 组内 N。单位 `ratio`（0–1），4 位小数。
- **边界**：`f.pe_ttm ≤ 0` 或 null → null；组内 N < 5 → null【建议】；`f.sw_l1` null → null。
- **可得时点**：d 日 16:30 后且行业快照已存在。
- **v1.1.0 角色**：对 L-01 **降为对照用**，L-01 改读 F43 `f.pe_ttm_pit_ind_pct`（§7C）。
- **引用**：L-01 对照；P0。

### F35 `f.limit_up_price` / F36 `f.limit_down_price` — 当日涨/跌停价
- **公式**：`round_half_up(基准价 × (1 ± 比例), 0.01)`，含沪 3.3.17、深 3.3.19 的两条舍入边界条款（`market_rules_check.md` 已核实）；比例按 `market_rules.yaml` 生效日分段（沪深主板 10%，ST/*ST 2026-07-06 起 10%、此前 5%，依据 config/market_rules.yaml 与 market_rules_check.md O1–O8 已核实的记录；主板证券在主数据上线日之前 is_st 为 null 时，F35/F36 记 null（T-R21 裁定④，接受此缺口）；创业板/科创板 20%（含风险警示）；北交所 30%）。**基准价 = 交易所当日“前收盘价”，除权除息日为除权（息）参考价**；数据上**只取日线 `pc` 作为基准价；jnfh（送、转、派）只用于交叉校验，不作为替代来源。pc 缺失或无效、或与 jnfh 交叉校验冲突 → F35/F36 记 null 并记 gap，不推断基准价**（T-R21 裁定①，保守执行）。交叉校验公式“参考价 =（前收 − 每股现金红利）/（1 + 每股送转），舍入到 0.01”只适用于已确认没有配股或其他复杂公司行为、且字段单位已明示的纯现金或送转案例；不满足条件时只记 gap。证据：麦蕊文档 pc =“前收盘价”；本地 p13_fin_pit 有 1 个深市纯现金除息样本，pc 等于参考价；**送转股和沪市样本缺**，记入 gaps，并向下传给 F39/F40。不复权。单位 `CNY_per_share`，2 位小数。
- **来源**：本地派生（plan 2.13 交易规则模块）；对照：涨跌停价接口 `/hsstock/stopprice/history/{code.市场}?st=&et=`（plan 第 1986 行，“每日 0 点”更新，字段名【待核实】）与 `/hsstock/lup/limit/{code}`（T003 列出该接口，字段 `t,su,eu,bu,ua,sd,ed,bd,…`；各字段含义【待核实】）。
- **可得时点**：d 日开盘前即可算（基准价为前一交易日收盘后确定），可用于 d 日盘中。
- **边界**：**无涨跌幅限制的日子 → null**（注册制新股上市前 5 日、重新上市首日、退市整理期首日；`market_rules_check.md` 深 3.3.15 / 沪 3.3.13），不得写 0 或极大值；停牌日 null。
- **引用**：G-01（一字涨停）、计划草案止损/止盈截断到涨跌停内（`_template.md` §7.3 G5）、F11；P0。

### F37 `f.is_limit_up_close` / F38 `f.is_limit_down_close` — 收盘封涨/跌停
- **公式**：不复权收盘 `c == f.limit_up_price`（跌停同理），按分精确比较（两者都是 2 位小数 Decimal）。`bool`。
- **可得时点**：d 日收盘后（15:00 后，快照定版 15:05）。盘中“当前封板”用快照 `p` 计算，但不得写入本键（本键只表示收盘状态）。
- **边界**：涨跌停价为 null（无涨跌幅限制日）→ null；停牌 → null。
- **引用**：F11 派生；H-01、G-01 的展示；P0。

### F39 `f.limit_locked_up` / F40 `f.limit_locked_down` — 全天一字涨/跌停
- **公式（T-R21 裁定③）**：不复权日线四价相等且有有效成交：`o == h == l == c == f.limit_up_price` 且 `v > 0`；跌停时四价都等于 `f.limit_down_price` 且 `v > 0`。**先检查依赖**：任一价、v 或涨跌停价为 null（含继承自 F35/F36 的 null）→ null；依赖都非 null 时，v = 0 → false；否则判断四价是否相等。**收盘触及涨跌停不等于全天一字。**`bool`。
- **可得时点**：日频值 d 日收盘后确定；G-01 盘中使用时，用截至当前快照的 `o/h/l/p` 判断“到目前为止一字”，作为临时值（盘中快照，不落 `feature_bars_daily`）。
- **边界**：同 F37。
- **引用**：G-01 `LIMIT_LOCKED`（plan 2.5.14 ⑯）；W-01 夹具 `f.limit_locked_up: true`；P0。

## 7A. L-01 时点财务特征（v1.1.0，T-R12；依据 L-01 口径裁定与 plan 2.12.1“财务按时点自算”）

本节登记 L-01 研究、回测（以及切换后的线上）使用的时点（point-in-time，PIT）特征键。数值由 T-B55 计算并写入 `market.financial_derived`，T-B35 读取。键名与 `financial_derived.metric` 的对应关系：`f.pe_ttm_pit`↔`pe_ttm`、`f.roe_ttm_pit`↔`roe_ttm`、`f.ocf_to_np_ttm_pit`↔`ocf_to_np_ttm`、`f.debt_ratio_pit`↔`debt_ratio`、`f.pb_pit`↔`pb`（v1.1.1；plan 第 1543 行（de86b99 版），`pb` 为 T-R12 裁定新增，与 `pe_ttm` 一样按交易日存）。`f.pe_ttm_pit_ind_pct`、`f.pb_pit_ind_pct` 是截面派生，不落 `financial_derived`。

**范围**：只登记裁定与 L-01 卡实际用到的键：v1.1.0 的 5 个（F42–F46），加 v1.1.1 的 PB 2 个（F47–F48，口径见 plan 2.12.1 PB 条、T-R12 裁定 ③），共 7 个。TTM 归母净利润、归母权益只是**分量**（§7A.0 的 C1–C3），不另设特征键。v1.0/v1.1.0 中“PB 分位没有正式键”的缺口（§11 G3）已在 v1.1.1 关闭。

**旧键降级**：F33 `f.pe_ttm`、F34 `f.pe_ttm_ind_pct`、F08 `f.roe_ttm` 对 L-01 降为“对照用”（只出截面对照报告，不进入 L-01 规则）。分类器 SW5、LG0B、LG2 仍读 F08（裁定“分类器不变”）。麦蕊因子 `pb`（`catalog.md` L-01“数据”行列出，口径【待核实】）同样只作 F47 的对照，不设正式键。L-01 线上何时改读新键，按 §7C 的切换条件执行。

### 7A.0 共用定义

**来源字段（只用已实测字段；实测出处：探针 run-20261101-190106 的 `samples/p05_fin_*.json`、`results/p05_fundamental.json` 和 `results/p11_gaps.json`，以及巨潮原文核对）**

| 分量 | 接口 | 字段 | 实测证据 | 状态 |
|---|---|---|---|---|
| 报告期、披露日 | 三张报表都有 | `jzrq`（截止日期）、`plrq`（披露日期） | p11 GAP3：三只样本 `plrq` 空值率 0 | 已实测 |
| 归母净利润（YTD） | `/hsstock/financial/income/{code.市场}` | `gsmgsyzzdjlr` | 600519 2026-06-30 行：`jlr` 46,033,330,566.78 − `ssgdsy` 1,516,450,144.92 = `gsmgsyzzdjlr` 44,516,880,421.86（逐分相等）。巨潮核对：600519 2001H1 = 223,407,942.67 元（《股票上市公告书暨2001年中期财务报告》，2001-08-22）；000001 2026Q3 = 39,186 百万元（《2026年三季度报告》，2026-10-24）。两处都与麦蕊值相同 | 已实测；单位为**元**（麦蕊已把百万元换算成元） |
| 累计口径 | 同上 | — | 600519 2026Q1 = 27,242,512,886.45，2026H1 = 44,516,880,421.86（年初至报告期末累计）；巨潮季报“年初至报告期末”列与之对应（§7B 样本 1、2） | 已实测（income） |
| 归母权益 | `/hsstock/financial/balance/{code.市场}` | `gsmgdqsyhj` | 600519：`gsmgdqsyhj` 251,253,594,419.50 + `ssgdqy` 10,842,757,754.86 = `syzqyhj` 262,096,352,174.36 | 600519 已实测；**银行、保险的 balance 未实测（pending，V5b）**。F44 与 F47 共用此分量 |
| 负债、资产合计 | 同上 | `fzhj`、`zczj` | 600519 样本中字段存在 | 字段存在已实测；数值关系未核（pending，V5b） |
| 经营活动现金流净额（YTD） | `/hsstock/financial/cashflow/{code.市场}` | 主字段 `jyhdcsdxjlxj`；备用字段 `jyhdcsdxjlje`（主字段为空时才用） | 600519 2026-06-30：`jyhdcsdxjlxj` = 70,690,750,119.06 = 流入 `jyhdxjlrxj` 109,245,728,301.02 − 流出 `jyhdxjlcxj` 38,554,978,181.96；同一行 `jyhdcsdxjlje` = `'-'`（2026-03-31 行也是 `'-'`）。plan 2.12.1 原写 `jyhdcsdxjlje`，已由 6efedef 改为主备字段 | **字段已裁定（T-R12 裁定 ②；plan 2.12.1 第 1188 行（de86b99 版）、T-B55）**：每个 YTD 分量取 `coalesce(jyhdcsdxjlxj, jyhdcsdxjlje)`，按分量在 `basis.ocf_field` 记录实际所用字段；两字段都为空（`'-'` 或缺失）→ 该分量缺失，**不用 0 补**。仍 pending 的只是实测（V5c）：两字段在其他公司、其他年份的非空率，以及 cashflow 是否为累计口径；若 T-B05 推翻主次，只改 plan 该条与 T-B55 配置，不改公式 |
| 总股本 | `/hsstock/financial/capital/{code.市场}`（探针 p05 实测路径） | `zgb`、`bdrq`（变动日期）、`plrq` | 600519：`bdrq` "20260930"、`plrq` "2026-09-30"、`zgb` 1,250,081,601（股） | 字段已实测；**`plrq` = `bdrq` 的含义未核实（V5d）**；核实前季末行按下文“capital 行可见时间”保守处理（v1.1.5，V5i） |
| 不复权收盘价 | `/hsstock/history/{code.市场}/d/n` | `c` | 探针样本 `p02_latest_d_n.json` 中有 `c` 字段；该接口的 `a`、`v` 单位已实测（V1） | 字段已实测（同 G1 `f.close_raw`） |

空值：麦蕊用字符串 `'-'` 表示空，一律视为 null，不得当 0。

**版本选择（裁定原文 + 本节补充；对所有分量相同）**

1. 版本 = `market.financial_reports` 中同一 (code, report_type, jzrq) 的一行。
2. **占位行丢弃**：`plrq ≤ jzrq` 的行不参与任何计算（裁定）。实例见 §7B 样本 5。
3. `available_from`：
   - 基本规则：`next_trading_day(plrq)` 09:30（只有日期 → 按盘后处理；裁定 / plan 2.12.1）。
   - 上线后新出现的版本：取 `max(next_trading_day(plrq) 09:30, first_seen_at 之后的下一个 09:30 开盘)`（裁定“与 `plrq` 不一致时以较晚者为准”）。
   - 【补充，避免历史全部失效】T-B55 首次全量回填时写入的行，`first_seen_at` 是回填时间，不代表当年的可见时间。这些行**只按 `plrq` 计算**，并在 `basis.pit_basis` 中记 `plrq_only`（v1.1.6 起 `pit_basis` 为字符串数组，见下文 basis 字段）。判定方法：`plrq < 首次全量回填日`。
   - 【补充】`available_from` 不早于该证券上市日（招股书期数据在上市前没有价格，无影响，只为避免排序歧义）。
4. **取当时可见的最新版本**：在评估时刻 T，对每个 (report_type, jzrq) 只取 `available_from ≤ T` 的行中 `available_from` 最大的一行。若 `available_from` 相同，取 `first_seen_at` 较晚的；仍相同且数值不同 → 该分量 null，并告警 `data_conflict`。
5. **重述不回写**：新版本只从它自己的 `available_from` 起生效。在它之前计算并落库的 `financial_derived` 行保持不变；新版本生效后另起新行（PK 中有 `version_available_from`）。
6. 同一个 TTM 可以混用不同版本的分量（例如本年 YTD 用首发版，上年同期 YTD 用次年报告中的比较数）。这正是 T 时市场可见的信息。各分量所用版本的 `plrq` 记入 `basis.versions`。
7. 不做版本间的数值精确相等比较：同一数值在次年报告中可能按千元或百万元列示，存在取整差（§7B 样本 3）。

**capital 行可见时间（v1.1.5；plan 2.12.1“T-R12e 补充裁定”1，fdd7fdd 版第 1277–1281 行；v1.1.6 按 plan 2.12.1“T-R12f 补充裁定”1–3 修订，38d7888 版第 1285–1287 行；V5i）**

capital 行的 `plrq` 不一定是真实披露日；按 `plrq` 放出会让回填数据提前用上股本（前视）。对 capital 行，上面第 3 条按下列规则替换：

1. **季末行**（适用条件，T-R12f 补充裁定 1：`bdrq` 为季末日 3-31、6-30、9-30、12-31，并且 `plrq = bdrq` 或 `plrq` 也是季末日）：
   - 上线后增量采集的行：可见时间 = `max(next_trading_day(plrq), first_seen_at)`（时刻写法同第 3 条：`next_trading_day(plrq) 09:30` 与 `first_seen_at` 之后的下一个 09:30 开盘取较晚者），**不套用截止日**（plan 已裁定（9ad51b8，T-R12g））。
   - 首次全量回填写入的行（判定同第 3 条：`plrq < 首次全量回填日`，没有可信的 `first_seen_at`）：按法定披露截止日保守处理；截止日规则只用于这类行（plan 已裁定（9ad51b8，T-R12g））。截止日按 **`bdrq` 所属的报告期**取（股本数属于该期，更保守；T-R12f 补充裁定 1）——Q1（3-31）→ 当年 4-30，H1（6-30）→ 当年 8-31，Q3（9-30）→ 当年 10-31，年报（12-31）→ 次年 4-30。可见时间 = `max(next_trading_day(plrq) 09:30, next_trading_day(截止日) 09:30)`（截止日的可见时刻取 `next_trading_day(截止日) 09:30`，与财务行一致；T-R12f 补充裁定 2），并在 `basis.pit_basis` 中加 `capital_deadline`。
2. **其余行**（不满足第 1 条适用条件：`bdrq` 不是季末日，即股本变动日；`plrq = bdrq` 但两者都不是季末日的行也在此列，T-R12f 补充裁定 1）：照旧按第 3 条（`next_trading_day(plrq) 09:30`；回填行 `pit_basis` 含 `plrq_only`）。
3. `zgb(d)` 的取法相应改为：capital 中 `bdrq ≤ d` 且**可见时间 ≤ d** 的行里 `bdrq` 最大的一行（F42、F47、B2）。“已可见 capital 行”在 B2、B4c、`no_capital_row` 中都按本条判定。
4. T-B05 用 600519 等样例确认麦蕊是否回填 capital 行。确认 `plrq` 是真实披露日时，取消本条保守规则，只改本条，不改原因码（plan 原文）。

**TTM 与报告期回退（裁定原文 + 本节补充）**

- `YTD(y,q)`：y 年第 q 季度的年初至报告期末累计值；`FY(y)` = `YTD(y,4)`。
- `TTM(y,q) = YTD(y,q) + FY(y−1) − YTD(y−1,q)`；q = 4 时 `TTM = FY(y)`。
- 报告期 P 的选法：从 T 时可见的最新 `jzrq` 开始往前逐期尝试，取第一个“所需分量在 T 时都可见且非 null”的 P。
- 回退下限：`jzrq(P) ≥ T 的日期往前推 15 个自然月的同一日`（该月没有这一日时取月末）。没有满足条件的 P → null，并标 `basis.fallback = exhausted`。只要 P 不是最新一期，就标 `basis.fallback = true`，并记录跳过的期数。
- 【补充】若有分量需要同时计算 TTM 归母净利润和 TTM 经营现金流（`f.ocf_to_np_ttm_pit`），两者必须用**同一个 P**，不得分子、分母各自回退。

**分量（不设特征键）**

- **C1 TTM 归母净利润** `NP_TTM(P)`：用 `gsmgsyzzdjlr` 按上式计算。单位为元。
- **C2 归母权益** `E(P)`：P 期 `gsmgdqsyhj`。这是时点值，不做 TTM。F44（分母）与 F47（分母）共用。
- **C3 TTM 经营现金流** `OCF_TTM(P)`：每个 YTD 分量（`YTD(y,q)`、`FY(y−1)`、`YTD(y−1,q)`）各自取 `coalesce(jyhdcsdxjlxj, jyhdcsdxjlje)`，再按 TTM 公式计算；三个分量的实际所用字段分别记入 `basis.ocf_field`（例：`{"YTD(y,q)": "jyhdcsdxjlxj", "FY(y-1)": "jyhdcsdxjlxj", "YTD(y-1,q)": "jyhdcsdxjlje"}`）。任一分量两字段都空 → C3 为 null（T-R12 裁定 ②）。cashflow 是否为累计口径：600519 2026Q1 = 26,909,891,269.13，2026H1 = 70,690,750,119.06，与累计口径一致，但只有一家公司的实测，**需 T-B05 复核（V5c）**。

**金融类处理**

- 银行（000001、600000 样本）的 income 中 `jlr`、`gsmgsyzzdjlr` 都有值，C1 照常计算。因此 F42–F45 对金融类**不做特殊处理**。F44、F47、F48 对银行、保险也照常计算，但其 `gsmgdqsyhj` 未实测（V5b），T-B05 核对前按下文“待核实标记”在行级写 `basis.verify_pending`（`bank_balance` / `insurance_balance`）。
- F46 资产负债率：银行、保险为 null（裁定）。银行 = `f.sw_l1` 为“银行”。保险 = 申万二级“保险”。**目前没有申万二级特征，`f.sw_l1` 代码格式也未核实（V9）→ 保险的识别是 pending（V5e）**。证券公司照常计算（裁定没有排除）。

**边界情况与原因码（v1.1.2；plan 2.12.1 边界情况第 1190–1212 行，T-R12a 裁定）**

适用范围：F42 `pe_ttm`、F47 `pb`，以及 F44 `roe_ttm` 中的权益部分；B5 自 v1.1.3 起适用于 `financial_derived` 全部 metric（含 F45、F46）。原则（plan 原文）：拿不准就留空（null），并在 `basis.null_reason` 写原因码；不用前值、0、插值、估算或别的数据源补数。

| # | 情况 | 处理 | `basis.null_reason` | 适用键 |
|---|---|---|---|---|
| B1 | d 日无日线、`sf = 1`，或日线被 T-B05a 标为 `suspect` | null；不用停牌前收盘价顶替 | `no_valid_bar` | F42、F47 |
| B2 | 股本：`zgb(d)` 取 capital 中 `bdrq ≤ d` 且可见时间 ≤ d 的行里 `bdrq` 最大的一行（可见时间见上文“capital 行可见时间”：季末行按 V5i 保守规则，回填季末行在 `basis.pit_basis` 中加 `capital_deadline`；v1.1.5，v1.1.6 修订），所用行的 `bdrq` 记 `basis.zgb_bdrq`。已披露但 `bdrq` 未到的行不提前用；`bdrq` 已到但未可见的行也不用。T 时已可知送转方案及除权日，且 d ≥ 除权日，但还没有 `bdrq ≥ 除权日` 的可见 capital 行（价格已除权、股本未更新） | null | `share_change_pending` | F42、F47 |
| B2a | 没有送转数据源（麦蕊是否提供分红送转数据待 T-B05 ⑧ / V5d） | 不做 B2 的送转检查，照常计算 | —（记 `basis.share_change_check = unavailable`） | F42、F47 |
| B3 | B 股、H 股：总市值 = A 股不复权收盘价 × `zgb`（全部股本，含 B、H 股），记 `basis.mcap_basis = a_price_total_shares`；不用 B/H 股价格、不换汇率 | 照常计算；核对前有非 A 股股本的公司加 `verify_pending: non_a_share_capital`。T-B05 若实测 `zgb` 只含 A 股，这类公司 PE、PB 一律 null，直到另行裁定 | 只含 A 股时：`a_share_only_capital`（T-R12b 补充裁定 1）。B/H 股识别（v1.1.5，plan 2.12.1“T-R12e 补充裁定”2）：capital 没有 B/H 字段，用配置中的 A+B、A+H 公司名单识别（名单注明来源和日期，做法同 V5e 保险名单）；`basis.share_class_check`（v1.1.6，plan 2.12.1“T-R12f 补充裁定”4）：名单接入前所有行记 `unavailable`（补充裁定 6）；名单接入后所有行记 `list`（按名单判定），名单内的公司另打 `non_a_share_capital`；将来 capital 有了区分字段，改记 `field`。均不按代码段或名称推断。v1.1.8：名单放在 `config/share_class_list.yaml`（plan 2.12.1“T-R12h 补充裁定”1，7ec6fad）：文件头写 `list_version`、`as_of`、`sources`（来源和取数日期）；每条记录写 `code`、`class`（`B` 或 `H`）、`paired_code`（配对代码，交易所代码按原样记录、不加市场后缀，例如 H 股 `00939`、B 股 `900901`）、`paired_market`（取值 `HK`、`SH`、`SZ`）、`effective_from`、`effective_to`（可为空）、`source`、`verified`（布尔值）。**按生效区间取，不得前视**：计算 d 日的值时，只用 `effective_from ≤ d` 且 `effective_to` 为空或 `effective_to > d` 的记录（历史回测不会用到之后才上市的 H 股）；所用名单版本记入 `basis.share_class_list_version`。名单更新时整版替换、`list_version` 加一、不改旧行，T-B55 重算时按新版本覆盖。名单行不加可见时间字段：A+B、A+H 的对应关系在 `effective_from`（B 股或 H 股上市日）当天已公开，按生效区间取用不构成前视；重算时用最新版名单属于更正历史，不是使用未来信息；回测报告写明所用的 `share_class_list_version`（v1.1.9，plan 2.12.1“T-R12h 补充裁定”4，d500474）。`verified=false` 的记录（手工对应的 45 对；211 对与 209 对两个来源取并集后差出来的记录）照常接入，照常打 `non_a_share_capital`（plan 2.12.1“T-R12h 补充裁定”2、3） | F42、F47 |
| B4a | 上市后还没有有效报告期（只有 `plrq ≤ jzrq` 占位行，或回退到 15 个月下限仍无可用期） | null | `no_visible_report`（同时 `basis.fallback = exhausted`） | F42、F44、F47 |
| B4b | 所选报告期 P 的 `jzrq` 早于上市日（权益不含募集资金） | PB、ROE 为 null；PE 照常计算 | `pre_listing_equity` | F44、F47 |
| B4c | 最新可见 capital 行的 `bdrq` 早于上市日（股本未含新发股份） | PE、PB 为 null | `pre_listing_capital`（T-R12b 补充裁定 1） | F42、F47 |
| B4d | 不用招股书或募资额推算上市后权益 | — | — | F44、F47 |
| B5 | 金额一律按人民币元处理。原始响应出现非人民币、非“元”标识（字段名待 T-B05 ⑨ / V5h；v1.1.10：按 plan 2.12.1“T-R13 补充裁定”，847f41e 第 1 条，若 V5h 按“没有币种、单位字段”关闭，本条只靠数量级不连续检查），或同一证券不同报告期数量级明显不连续 | 该期分量 null，并告警 `unit_mismatch`；不按数量级猜单位、不自动换算；不要求跨版本数值精确相等（§7B 样本 3）。**v1.1.3 扩到 `financial_derived` 全部 metric**：比值键（含 F45、F46）的分子、分母只要有一个分量命中（含 TTM 用到的任一期），该值就为 null（补充裁定 5） | `unit_mismatch`（既是告警名，也是原因码；补充裁定 2 已确认） | F42、F44、F45、F46、F47 |
| B6 | 归母权益是极小的正数 | `pb` 不设上限、不缩尾，原值落库；展示层与对照报告可把 `pb > 100` 标为离群，但不改值（plan 已裁定） | — | F47 |
| B7 | 每股字段（每股净资产、每股收益等） | 不用于推算 `pe_ttm`、`pb`（plan 已裁定；§7B R5） | — | F42、F47 |

其他已有的 null 情形，原因码按下表（T-R12b 补充裁定 1）：`NP_TTM ≤ 0` → `non_positive_earnings`；`E(P) ≤ 0` → `non_positive_equity`；`zgb` 缺失、为空或 ≤ 0（没有 `bdrq ≤ d` 且已可见的 capital 行）→ `no_capital_row`；版本冲突（§7B R6）→ `data_conflict`。

**原因码总表（v1.1.3；plan 2.12.1“T-R12b 补充裁定”1，1c62952 版第 1238–1257 行）**

- **列表封闭**：`basis.null_reason` 只能取下表 14 个码；要新增原因码，先改 plan 该条，再改本表。不得出现“other”或自拟码。
- **值与原因一一对应**：`financial_derived` 中 `value` 为 null 的行**必须**写 `basis.null_reason`；`value` 非空的行**不写**该字段。T-B55 单元测试断言这两条。
- **优先级**：一行同时命中多个原因时，只写表中**序号最小**的一个（表序即 plan 表序）。
- **分位键不在此表**：F43、F48 在组内 N < 5 或底层值为 null 时为 null，原因由 T-B35 记在特征值元数据（`group_too_small` / `input_null`），不写进 `financial_derived`，也不是 `null_reason` 的取值。

| 序 | `null_reason` | 情形 | 适用 metric（键） |
|---|---|---|---|
| 1 | `no_valid_bar` | B1：d 日无日线、`sf = 1` 或日线 `suspect` | `pe_ttm`（F42）、`pb`（F47） |
| 2 | `share_change_pending` | B2：除权日 ≤ d 但还没有 `bdrq ≥ 除权日` 的可见 capital 行 | `pe_ttm`、`pb` |
| 3 | `a_share_only_capital` | B3：实测 `zgb` 只含 A 股时，有 B、H 股的公司 | `pe_ttm`、`pb` |
| 4 | `no_visible_report` | B4a：没有有效报告期，或回退 15 个月仍取不到 | 全部 |
| 5 | `pre_listing_equity` | B4b：所选报告期 P 早于上市日 | `pb`、`roe_ttm`（F44） |
| 6 | `pre_listing_capital` | B4c：最新可见 capital 行 `bdrq` 早于上市日 | `pe_ttm`、`pb` |
| 7 | `unit_mismatch` | B5：币种、单位标识异常或数量级不连续（既是告警名，也是原因码） | 全部 |
| 8 | `non_positive_earnings` | `NP_TTM ≤ 0`（PE）；现金流比的分母 `NP_TTM ≤ 0` 也用此码 | `pe_ttm`、`ocf_to_np_ttm`（F45） |
| 9 | `non_positive_equity` | `E(P) ≤ 0` | `pb`、`roe_ttm` |
| 10 | `no_capital_row` | 没有 `bdrq ≤ d` 且已可见的 capital 行，或 `zgb` 为空、≤ 0 | `pe_ttm`、`pb` |
| 11 | `ocf_missing` | 经营现金流两个字段（`jyhdcsdxjlxj`、`jyhdcsdxjlje`）都为空 | `ocf_to_np_ttm` |
| 12 | `component_missing` | 回退选出的 P 中某个必需分量仍为空，且不属于以上任何一种（如 `zczj` 为空）；`debt_ratio` 的 `zczj ≤ 0` 也并入此码（T-R12c 补充裁定 1，另发 `data_quality` 告警） | 全部 |
| 13 | `data_conflict` | §7B R6 / plan 补充规则 ②：两个版本不可区分且数值不同（既是告警名，也是原因码） | 全部 |
| 14 | `financial_sector_na` | 银行、保险的资产负债率 | `debt_ratio`（F46） |

注：“全部”指 `financial_derived` 的 5 个 metric（`pe_ttm`、`pb`、`roe_ttm`、`ocf_to_np_ttm`、`debt_ratio`）。**退市证券**（plan 2.12.1“T-R12c 补充裁定”3，b85b564）：T-B55 只为有可见报告期的证券计算；`pe_ttm`、`pb` 只为有日线的交易日写行，退市后没有日线就没有行，**不补写 null 行**，因此不需要、也不新增原因码。退市前的历史行照常计算，按本表写码。`listing_status ∈ {delisted, missing_from_list}` 时 `f.*` 全部为 null（§1.7）是特征层规则（T-B35），与 `financial_derived` 无关。

**待核实标记 `basis.verify_pending`（v1.1.2；plan 2.12.1 待核实标记第 1213–1225 行，T-R12a 裁定）**

- **键级**：仍用 `feature_catalog.status`（`declared` → `verified_live`），不变。
- **行级**：`market.financial_derived.basis.verify_pending`，字符串数组，空数组表示没有待核实项。当前取值：

| 取值 | 识别 | 适用的 metric / 键 | 何时清除 |
|---|---|---|---|
| `bank_balance` | `f.sw_l1` = 银行（代码格式 V9） | `roe_ttm`（F44）、`pb`（F47） | V5b 关闭 |
| `insurance_balance` | 按 plan 2.12.1 线上切换条中的保险名单或申万二级识别（V5e） | `roe_ttm`（F44）、`pb`（F47） | V5b、V5e 关闭 |
| `non_a_share_capital` | 配置中 A+B、A+H 公司名单内的公司（capital 没有 B/H 字段；名单注明来源和日期；v1.1.5，plan 2.12.1“T-R12e 补充裁定”2）。名单接入前无法识别，不打此标记，记 `basis.share_class_check = unavailable`（v1.1.3）；接入后名单内、名单外的行都记 `share_class_check = list`（v1.1.6，T-R12f 补充裁定 4）。“名单内”指 d 日生效的记录（`effective_from ≤ d` 且 `effective_to` 为空或 `effective_to > d`），`verified=false` 的记录同样打此标记；所用名单版本记 `basis.share_class_list_version`（v1.1.8，plan 2.12.1“T-R12h 补充裁定”1、2） | `pe_ttm`（F42）、`pb`（F47） | V5g 关闭 |
| `cdr_unit` | `market.securities.type = cdr`（与 §1.4 一致，不另设名单、不按代码段推断；v1.1.5 新增标记，v1.1.6 按 plan 2.12.1“T-R12f 补充裁定”5 更正识别方式；V5j） | `pe_ttm`（F42）、`pb`（F47） | V5j 关闭 |

- `debt_ratio`（F46）对银行、保险本来就为 null，不加标记；F45 不用权益，也不加标记。
- 截面分位键（F43、F48）继承所用底层值的 `verify_pending`（T-B35 在特征值元数据里保留）。
- **`cdr_unit` 的影响范围（v1.1.6，plan 2.12.1“T-R12f 补充裁定”6）**：带 `cdr_unit` 的 `pe_ttm`、`pb` 照常计算和落库。`type = cdr` 的证券按 §1.4 本来就不在 F43、F48 的分位池内，因此不另设池剔除规则，也不新增元数据原因；`cdr_unit` 只是 F42、F47 值上的标记；§7C S2 的池 U 按 §1.4 本来就不含 CDR，因此不写 S2 剔除条款（plan 已裁定（9ad51b8，T-R12g））。`bank_balance`、`insurance_balance`、`non_a_share_capital` 维持 T-R12a 规定：继承标记，照常参与排序（T-R12f 补充裁定 8）。
- **CDR 总市值与清除条件（v1.1.6，plan 2.12.1“T-R12f 补充裁定”7，V5j）**：核实前照常按 `c × zgb` 计算并打 `cdr_unit`。T-B05 确认 `zgb` 的单位后：按 CDR 份数计 → 总市值 = `c × zgb`；按基础股份计 → 总市值 = `c`（每份 CDR 的价格）× `zgb` × 每股基础股份对应的 CDR 份数。清除条件分两种情况（plan 已裁定（9ad51b8，T-R12g））：① T-B05 确认按 CDR 份数计 → 总市值 = `c × zgb`，不需要配置，确认后即清除 `cdr_unit`；② T-B05 确认按基础股份计 → 转换比例写在配置里，按证券单列，并注明来源（招股书或上市公告），配置也接入后清除 `cdr_unit`。v1.1.10：`cdr_unit` **逐只清除**，不对全部 `type = cdr` 推广：只有对照过巨潮披露 CDR 份数的证券才清除，其他 CDR 保留标记；CDR 不进 S2 的池，保留的标记不阻塞切换（plan 2.12.1“T-R13 补充裁定”，847f41e 第 2 条）；判定容差（plan 2.12.1“T-R13 补充裁定”，847f41e 第 3 条）：|zgb − 披露的 CDR 份数| / 披露的 CDR 份数 ≤ 0.1% → 按 CDR 份数计；zgb 与“披露的 CDR 份数 ÷ 每股基础股份对应的 CDR 份数”相差同样不超过 0.1% → 按基础股份计；两条都不满足 → 保留 `cdr_unit` 并告警 `data_quality`。
- 带标记的值**照常计算和落库**；研究与回测报告必须单列这部分。
- §7C S2 计算覆盖率时，带标记的证券**同时从分子和分母剔除**，并单列个数（涉及 `bank_balance`、`insurance_balance`、`non_a_share_capital`；`cdr_unit` 不涉及 S2，见上）。
- T-B05 核实后，T-B55 重算时不再写该标记；§7C S1 要求切换时所有取值都已清除。

**basis 字段（v1.1.2 新增，plan 第 1543 行；v1.1.3 补充，1c62952 版第 1581 行）**：`null_reason`（封闭枚举，见上表）、`zgb_bdrq`、`mcap_basis`、`share_change_check`、`verify_pending`；v1.1.3 新增 `single_period_reason`（F44）、`share_class_check`（F42、F47）；v1.1.5 新增取值：`pit_basis = capital_deadline`（F42、F47，V5i）、`share_class_check = list`（V5g）、`verify_pending` 含 `cdr_unit`（F42、F47，V5j）。v1.1.6（plan 2.12.1“T-R12f 补充裁定”3、4）：`pit_basis` 改为**字符串数组**（与 `verify_pending` 相同），可同时含 `plrq_only` 和 `capital_deadline`，没有任何特例时为空数组或不写，T-B55 按数组实现，适用于所有写 `pit_basis` 的键；`share_class_check` 取值为 `unavailable` / `list` / `field`。v1.1.8（plan 2.12.1“T-R12h 补充裁定”1）新增 `share_class_list_version`（F42、F47）：记 d 日所用 `config/share_class_list.yaml` 的 `list_version`；名单接入前（`share_class_check = unavailable`）不写。回测报告写明所用的 `share_class_list_version`（v1.1.9，plan 2.12.1“T-R12h 补充裁定”4，d500474）。与原有的 `period`、`versions`、`roe_basis`、`ocf_field`、`fallback`、`pit_basis` 并存。

**时点总结**

财务类分量在 `next_trading_day(plrq) 09:30` 起可见（遵循上面第 3 条）；capital 行另按“capital 行可见时间”（V5i）。含价格的键（F42、F43、F47、F48）在 d 日日线落库后可得，适用于 d 日盘后和 d+1 日。

### F42 `f.pe_ttm_pit` — 市盈率 TTM（时点自算）
- **公式**：`pe = close_raw(d) × zgb(d) ÷ NP_TTM(P)`，单位“倍”，2 位小数。
- **市值口径**：d 日不复权收盘价 `c`（`/hsstock/history/{code.市场}/d/n`）× 总股本 `zgb(d)`，单位为元。
  - `zgb(d)` 取 capital 中 `bdrq ≤ d` 且可见时间 ≤ d 的行里 `bdrq` 最大的一行（裁定“`bdrq ≤ T` 且已披露”）。可见时间按 §7A.0“capital 行可见时间”（v1.1.5，V5i）：季末行取 `max(next_trading_day(plrq), first_seen_at)`，首次全量回填的季末行取 `max(next_trading_day(plrq), next_trading_day(截止日))` 09:30（截止日按 `bdrq` 所属报告期，v1.1.6），`basis.pit_basis` 加 `capital_deadline`；非季末行照旧按 `plrq`。
  - `bdrq` 相同时，按第 4 条版本规则处理。
  - 用总股本，不用流通股本（`ysltag`、`xsltgf` 不用）。
- **归母口径**：分母为 C1，即归母净利润 `gsmgsyzzdjlr`，不用 `jlr`（含少数股东损益）。
- **不用每股字段**：`jbmgsy`、`xsmgsy` 等会因送转被追溯重述（§7B 样本 2），不得用“价格 ÷ EPS”计算。
- **可得时点**：d 日日线落库后（约 17:00，`daily_bars_due`），且所用财报 `available_from ≤ d 09:30`。
- **边界**（v1.1.2 按 §7A.0 B1–B7 同步，plan 2.12.1 第 1190–1212 行）：
  - `NP_TTM ≤ 0` → null（裁定：不给负 PE；`null_reason = non_positive_earnings`）。
  - C1 缺期 → 按 §7A.0 回退；回退耗尽或没有有效报告期 → null（`null_reason = no_visible_report`）。回退选出的 P 中必需分量仍为空 → `component_missing`；版本冲突 → `data_conflict`。
  - B1：d 日无日线、`sf = 1` 或日线 `suspect` → null（`no_valid_bar`）；不用停牌前收盘价。
  - B2：`zgb` 取法见上，记 `basis.zgb_bdrq`；送转除权日 ≤ d 而股本未更新 → null（`share_change_pending`）；没有送转数据源 → `basis.share_change_check = unavailable`。没有可见 capital 行，或 `zgb` 为空、≤ 0 → null（`no_capital_row`）。
  - B3：总市值 = A 股价格 × 全部股本，`basis.mcap_basis = a_price_total_shares`。B/H 股按配置的 A+B、A+H 名单识别（v1.1.5，V5g）：`share_class_check` 取值（v1.1.6，T-R12f 补充裁定 4）——名单接入前所有行记 `unavailable`（不打 `non_a_share_capital`，v1.1.3 补充裁定 6）；接入后所有行记 `list`，名单内的公司另在 `verify_pending` 中加 `non_a_share_capital`；将来 capital 有区分字段时记 `field`。均不按代码段或名称推断；若 T-B05 实测 `zgb` 只含 A 股，有 B/H 股的公司 PE 为 null（`a_share_only_capital`）。名单取用（v1.1.8，plan 2.12.1“T-R12h 补充裁定”1）：只用 d 日生效的记录（`effective_from ≤ d` 且 `effective_to` 为空或 `effective_to > d`），不得前视；`verified=false` 的记录照常打 `non_a_share_capital`；名单版本记 `basis.share_class_list_version`；名单行不加可见时间字段，重算用最新版名单属于更正，回测报告写明所用版本（v1.1.9，plan 2.12.1“T-R12h 补充裁定”4，d500474）。
  - CDR（v1.1.5，V5j；v1.1.6 按 T-R12f 补充裁定 5–7 更正）：以 `market.securities.type = cdr` 识别，照常计算，`verify_pending` 含 `cdr_unit`（只是值上的标记）；CDR 按 §1.4 本来不在 F43 的池和 §7C S2 的池 U 内（plan 已裁定（9ad51b8，T-R12g））。总市值换算与清除条件见 §7A.0 待核实标记“CDR 总市值与清除条件”。
  - B4：P 的 `jzrq` 早于上市日时 PE **照常计算**（上市前利润是真实披露数）；最新可见 capital 行 `bdrq` 早于上市日 → null（`pre_listing_capital`）。
  - B5：非人民币、非元标识或数量级不连续 → 该期分量 null，告警 `unit_mismatch`。
  - 金融类照常计算（PE 不加 `bank_balance` / `insurance_balance`）。
  - 多个原因同时命中时按 §7A.0 原因码总表取序号最小的一个；`value` 非空的行不写 `null_reason`。
- **basis**：所用 P、各分量 `plrq`、`zgb_bdrq`、`mcap_basis`、`share_change_check`、`share_class_check`（`unavailable` / `list` / `field`）、`share_class_list_version`（v1.1.8）、`fallback`、`pit_basis`（字符串数组，可含 `plrq_only`、`capital_deadline`，v1.1.6）、`null_reason`、`verify_pending`（`non_a_share_capital`、`cdr_unit`）、`calc_version`。
- **引用**：L-01（替代 F33）；P0。

### F43 `f.pe_ttm_pit_ind_pct` — PE_TTM（时点）行业内分位
- **公式**：`rank_pct_in(f.pe_ttm_pit, f.sw_l1)`。池 = §1.4 股票池叠加 plan 2.12.1 因子池排除（停牌、ST/*ST、退市整理、上市 < 60 个交易日），并要求 `f.pe_ttm_pit` 非 null。按 d 日 `f.sw_l1` 分组，组内升序平均秩 / 组内 N。单位 `ratio`（0–1），4 位小数。L-01“PE 分位 ≤ 30%”写成 ≤ 0.3。
- **边界**：
  - `f.pe_ttm_pit` 为 null → null（因此亏损股不进入分母）。
  - 组内 N < 5 → null【建议，同 F34】。
  - `f.sw_l1` 为 null → null。
  - 继承 F42 的 `verify_pending`（T-B35 在特征值元数据里保留；v1.1.2）。
  - 本键为 null 的原因由 T-B35 记在特征值元数据（`group_too_small` / `input_null`），不是 `null_reason` 取值（v1.1.3，补充裁定 1）。
- **可得时点**：同 F42，且行业快照已存在。
- **引用**：L-01（替代 F34）；P0。

### F44 `f.roe_ttm_pit` — ROE TTM（时点自算）
- **公式**：`roe = NP_TTM(P) ÷ avg(E(P), E(P−4)) × 100`，单位 `pct`（12 = 12%），2 位小数。L-01“ROE_TTM ≥ 8%”写成 ≥ 8。P−4 是上年同期的报告期。
- **分母**：取期初、期末平均，即 `(E(P) + E(P−4)) / 2`（裁定）。E(P−4) 必须在 T 时可见。
  - E(P−4) 缺失 → 只用 E(P)，并标 `basis.roe_basis = single_period`（裁定），`basis.single_period_reason = p4_missing`。
  - E(P−4) ≤ 0 时同样按缺失处理（plan 补充规则 ③）：`single_period`，`single_period_reason = p4_non_positive`。
  - **P−4 的 `jzrq` 早于上市日**（E(P−4) 不含募集资金）→ 按 E(P−4) 缺失处理：`single_period`，`single_period_reason = p4_pre_listing`；不用招股书数据补 E(P−4)（v1.1.3，T-R12b 补充裁定 3）。
  - 同时命中多种时只记一个 `single_period_reason`：按 `p4_pre_listing` → `p4_missing` → `p4_non_positive` 的顺序取第一个（plan 已裁定（b85b564），“T-R12c 补充裁定”2：P−4 早于上市日时即使有值也不能用，先于“缺失”；缺失时无法判断正负）。`roe_basis` 不是 `single_period` 的行不写 `single_period_reason`。
- **归母口径**：分子用 C1，分母用 C2（`gsmgdqsyhj`，不含少数股东权益 `ssgdqy`）。
- **可得时点**：`next_trading_day(plrq) 09:30`（按版本规则）。日频读取时，取 T 时最新可算的 P。
- **边界**：
  - `E(P) ≤ 0` → null（`non_positive_equity`）；E(P) 为空按 §7A.0 回退，回退选出的 P 中仍为空 → `component_missing`。
  - C1 缺期或回退耗尽 → null（`no_visible_report`）。
  - `NP_TTM ≤ 0` 时**保留负值**。裁定只规定了 PE 和现金流比在净利润 ≤ 0 时为 null；这与 F08“负 ROE 是真实值”一致。对 L-01 来说，负值同样不满足 ≥ 8。
  - 没有有效报告期或回退耗尽 → null（`null_reason = no_visible_report`）。
  - P 的 `jzrq` 早于上市日（权益不含募集资金）→ null（`pre_listing_equity`）；不用招股书或募资额推算（§7A.0 B4）。
  - 权益或利润分量（含 TTM 用到的任一期、E(P−4)）出现非人民币、非元标识或数量级不连续 → null，告警并记 `unit_mismatch`（B5）。
  - 版本冲突 → `data_conflict`。多个原因同时命中时按 §7A.0 原因码总表取序号最小的一个。
  - 金融类照常计算。银行、保险的 `gsmgdqsyhj` 未实测（V5b）：键级保持 `declared`，行级 `verify_pending` 写 `bank_balance` / `insurance_balance`（v1.1.2，plan 2.12.1 待核实标记）。
- **basis**：所用 P、各分量 `plrq`、`roe_basis`、`single_period_reason`（`p4_pre_listing` / `p4_missing` / `p4_non_positive`，仅 `single_period` 时写）、`fallback`、`pit_basis`、`null_reason`、`verify_pending`、`calc_version`。
- **引用**：L-01 质量护栏（替代 F08）；P0。

### F45 `f.ocf_to_np_ttm_pit` — 经营现金流 / 归母净利润（TTM，时点）
- **公式**：`OCF_TTM(P) ÷ NP_TTM(P)`，同一个 P。单位 `ratio`，4 位小数。L-01“≥ 0.8”写成 ≥ 0.8。
- **口径说明**：
  - 分子是合并口径的经营现金流（报表没有归母现金流），分母是归母净利润。这是裁定原文的口径，本文不改。
  - 少数股东占比高的公司比值会偏高，需在 L-01 研究报告中说明。
- **来源字段（已裁定，T-R12 裁定 ②、plan 2.12.1 第 1188 行（de86b99 版））**：
  - 分子 C3：主字段 `jyhdcsdxjlxj`，备用字段 `jyhdcsdxjlje`。每个 YTD 分量单独判断：主字段非空就用主字段；主字段为空（`'-'` 或缺失）时才用备用字段。
  - 实际所用字段按分量记入 `basis.ocf_field`（plan 第 1543 行（de86b99 版）`financial_derived.basis` 已列此项）。
  - 两字段会计含义相同（主表“经营活动产生的现金流量净额”），合并使用不改变口径。
  - 仍待实测（V5c）：两字段在多家公司、多个年份的非空率，以及 cashflow 是否为累计口径。实测只可能改主备顺序（plan 该条与 T-B55 配置），不改本键公式。
  - 分母 C1：`gsmgsyzzdjlr`。
- **可得时点**：同 F44。
- **边界**：
  - `NP_TTM ≤ 0` → null（裁定；`null_reason = non_positive_earnings`，与 PE 同码）。
  - `OCF_TTM` 任一分量缺失（两字段都空）→ null（`ocf_missing`），**不用 0 补**（T-R12 裁定 ②），且不单独回退（§7A.0：分子、分母用同一个 P，整体回退）。
  - 没有有效报告期或回退耗尽 → `no_visible_report`；其他必需分量为空 → `component_missing`；版本冲突 → `data_conflict`。
  - **`unit_mismatch`（v1.1.3，补充裁定 5）**：分子或分母的任一分量（含 TTM 用到的任一期）命中 B5 → null（`unit_mismatch`）；同一期内的单位差在比值里虽可抵消，但 TTM 跨期拼接时不能抵消，所以不例外。
  - 多个原因同时命中时按 §7A.0 原因码总表取序号最小的一个。
  - 金融类照常计算。银行经营现金流受存贷款变动驱动，对 L-01 意义有限，是否排除由研究员在 L-01 卡中决定，本键不处理。
- **basis**：所用 P、各分量 `plrq`、`ocf_field`（按分量）、`fallback`、`pit_basis`、`null_reason`、`calc_version`。
- **引用**：L-01；P0。

### F46 `f.debt_ratio_pit` — 资产负债率（时点）
- **公式**：`fzhj(P) ÷ zczj(P)`，P 为 T 时可见的最新 balance 报告期，回退规则同 §7A.0（不做 TTM）。单位 `ratio`，4 位小数。
- **L-01 用法**：“不在行业前 10%”写成 `rank_pct_in(f.debt_ratio_pit, f.sw_l1) ≤ 0.9`。池同 F43，不另设分位键。
- **边界**：
  - 银行、保险 → null（裁定；`null_reason = financial_sector_na`）。识别方法 pending（V5e）。
  - `zczj` 或 `fzhj` 为空 → null（`component_missing`）。
  - `zczj ≤ 0` → null（`component_missing`；plan 已裁定（b85b564），“T-R12c 补充裁定”1：资产合计 ≤ 0 只能是源数据错误，与“分量取不到可用值”同样处理，不新增原因码）。T-B55 同时发一条 `data_quality` 告警（不打断计算），供 T-B05 回查。
  - 没有有效报告期或回退耗尽 → `no_visible_report`；版本冲突 → `data_conflict`。
  - **`unit_mismatch`（v1.1.3，补充裁定 5）**：`fzhj` 或 `zczj` 命中 B5 → null（`unit_mismatch`）。
  - 多个原因同时命中时按 §7A.0 原因码总表取序号最小的一个（例如银行同时没有有效报告期时写 `no_visible_report`）。
- **basis**：所用 P、各分量 `plrq`、`fallback`、`pit_basis`、`null_reason`、`calc_version`。
- **可得时点**：同 F44。
- **引用**：L-01；P0。

### F47 `f.pb_pit` — 市净率（时点自算）
- **口径依据**：plan 2.12.1“财务按时点自算”PB 条（de86b99 版第 1189 行，T-R12 裁定 ③，关闭 G3）与边界情况、待核实标记两条（第 1190–1225 行，T-R12a 裁定）。下文以这几条为准；标“沿用 F42”的是单位、取整等 plan 未写、按 F42 同一做法处理的地方。
- **公式**：`pb = close_raw(d) × zgb(d) ÷ E(P)`，单位“倍”，2 位小数（单位、取整沿用 F42）。
- **分子（总市值）**：与 F42 同一取法（plan 原文“与 `pe_ttm` 同一取法，不用快照或因子里的市值”）。
  - d 日不复权收盘价 `c`（`/hsstock/history/{code.市场}/d/n`）× 总股本 `zgb(d)`，单位为元。
  - `zgb(d)` 取 capital 中 `bdrq ≤ d` 且可见时间 ≤ d 的行里 `bdrq` 最大的一行；`bdrq` 相同时按 §7A.0 第 4 条版本规则处理。可见时间按 §7A.0“capital 行可见时间”（v1.1.5，V5i，同 F42）：季末行取 `max(next_trading_day(plrq), first_seen_at)`，首次全量回填的季末行取 `max(next_trading_day(plrq), next_trading_day(截止日))` 09:30（截止日按 `bdrq` 所属报告期，v1.1.6），`basis.pit_basis` 加 `capital_deadline`；非季末行照旧按 `plrq`。
  - 用总股本，不用流通股本（`ysltag`、`xsltgf` 不用）。
- **分母（归母权益）**：C2，即 balance 中的归母股东权益 `gsmgdqsyhj`（不含少数股东权益 `ssgdqy`）。
  - P = T 时可见的最新 balance 报告期；时点值，**不做 TTM**。
  - P 按 §7A.0 逐期回退，下限 15 个月（plan：“回退下限同 15 个月”）；回退耗尽 → null，并标 `basis.fallback = exhausted`。
  - PB 的 P 与同一 T 下 F42 的 P 可以不同，各自记入 `basis.period`（T-R12 裁定 ④ 说明 1）。
- **不用每股字段（plan 2.12.1 已裁定，边界第 7 条；同 F42）**：不用每股净资产类字段计算“价格 ÷ 每股净资产”（每股字段会因送转被追溯重述，§7B R5）。
- **时点可见性**（与 F42–F46 相同，§7A.0、§7B）：
  - 财报分量在 `next_trading_day(plrq) 09:30` 起可见，取 T 时可见的最新版本（R2）。
  - `plrq ≤ jzrq` 的占位行丢弃（R1）。
  - 重述**不回写**：新版本只从自己的 `available_from` 起生效，此前已落库的 `financial_derived` 行不改（R3）。
  - 首次全量回填写入的行只按 `plrq` 计算，`basis.pit_basis` 加 `plrq_only`；capital 季末行例外，按 V5i 截止日规则，`basis.pit_basis` 加 `capital_deadline`（两者可同时出现，v1.1.6）；同一 `available_from` 冲突按 R6 处理（plan 2.12.1 补充规则 ①②）。
  - 价格部分：d 日日线落库后（约 17:00）可得，适用于 d 日盘后和 d+1 日。
- **窗口与缺失**：无滚动窗口（价格取 d 日单日，权益取单期时点值）。任何缺失一律 null，不用 0、前值或插值填充（§0）。
- **边界**：
  - `E(P) ≤ 0` 或缺失 → null（plan 原文：“归母权益 ≤ 0 或缺失 → `pb = null`”）。因此不会出现负 PB，与 F42 对 `NP_TTM ≤ 0` 的处理一致。原因码：`E(P) ≤ 0` → `non_positive_equity`；E(P) 为空先按 §7A.0 回退，回退耗尽 → `no_visible_report`，回退选出的 P 中仍为空 → `component_missing`。
  - 回退耗尽 → null（`no_visible_report`）。版本冲突 → `data_conflict`。
  - 以下 B1–B5 见 §7A.0“边界情况与原因码”（plan 2.12.1 第 1190–1212 行）：
    - B1：d 日无日线、`sf = 1` 或日线 `suspect` → null（`null_reason = no_valid_bar`）；不用停牌前收盘价。
    - B2：`zgb` 取 `bdrq ≤ d` 且已可见（按 V5i 可见时间）的最新一行，记 `basis.zgb_bdrq`；已知送转除权日 ≤ d 但还没有 `bdrq ≥ 除权日` 的可见股本行 → null（`share_change_pending`）；没有送转数据源 → `basis.share_change_check = unavailable`。没有可见 capital 行，或 `zgb` 为空、≤ 0 → null（`no_capital_row`）。
    - B3：总市值 = A 股价格 × 全部股本（含 B、H 股），`basis.mcap_basis = a_price_total_shares`，不用 B/H 股价格、不换汇率。B/H 股按配置的 A+B、A+H 名单识别（v1.1.5，V5g，同 F42）：`share_class_check` 取值（v1.1.6，T-R12f 补充裁定 4）——名单接入前所有行记 `unavailable`（不打 `non_a_share_capital`，v1.1.3 补充裁定 6）；接入后所有行记 `list`，名单内的公司另在 `verify_pending` 中加 `non_a_share_capital`；将来 capital 有区分字段时记 `field`。均不按代码段或名称推断；若 T-B05 实测 `zgb` 只含 A 股，有 B/H 股的公司 PB 为 null（`a_share_only_capital`）。名单取用（v1.1.8，plan 2.12.1“T-R12h 补充裁定”1）：只用 d 日生效的记录（`effective_from ≤ d` 且 `effective_to` 为空或 `effective_to > d`），不得前视；`verified=false` 的记录照常打 `non_a_share_capital`；名单版本记 `basis.share_class_list_version`；名单行不加可见时间字段，重算用最新版名单属于更正，回测报告写明所用版本（v1.1.9，plan 2.12.1“T-R12h 补充裁定”4，d500474）。
    - CDR（v1.1.5，V5j；v1.1.6 更正，同 F42）：以 `market.securities.type = cdr` 识别，照常计算，`verify_pending` 含 `cdr_unit`（只是值上的标记）；CDR 按 §1.4 本来不在 F48 的池和 §7C S2 的池 U 内（plan 已裁定（9ad51b8，T-R12g））。总市值换算与清除条件见 §7A.0 待核实标记“CDR 总市值与清除条件”。
    - B4：没有有效报告期（含回退耗尽）→ null（`no_visible_report`）；P 的 `jzrq` 早于上市日 → null（`pre_listing_equity`）；最新可见 capital 行 `bdrq` 早于上市日 → null（`pre_listing_capital`）；不用招股书或募资额推算。
    - B5：金额按人民币元；非人民币、非元标识或数量级不连续 → 该期分量 null，告警 `unit_mismatch`，不猜单位。
  - `listing_status ∈ {delisted, missing_from_list}` → 特征层 null（§1.7，YAML 顶层 `all_null_when`，T-B35）；`financial_derived` 不为退市证券补写 null 行：只在有日线的交易日写 `pb` 行，退市前的历史行照常计算（plan 2.12.1“T-R12c 补充裁定”3）。回测报告带 `survivorship_bias = true`（plan 2.12.1）。
  - 金融类照常计算。银行、保险的 `gsmgdqsyhj` 未实测（V5b）：**键级** `feature_catalog.status` 保持 `declared`，**行级** `basis.verify_pending` 写 `bank_balance` / `insurance_balance`（plan 2.12.1 待核实标记）。带标记的值照常落库，报告单列。
  - B6（plan 2.12.1 已裁定）：`E(P)` 为很小的正数时 PB 会极大，本键**不设上限、不缩尾**，原值落库；展示层与对照报告可把 `pb > 100` 标为离群，但不改值。
  - 多个原因同时命中时按 §7A.0 原因码总表取序号最小的一个；`value` 非空的行不写 `null_reason`。研究与回测报告单列 `share_class_check = unavailable` 的证券数。
- **basis**：所用 P、`gsmgdqsyhj` 版本的 `plrq`、`zgb_bdrq`、`mcap_basis`、`share_change_check`、`share_class_check`（`unavailable` / `list` / `field`）、`share_class_list_version`（v1.1.8）、`fallback`、`pit_basis`（字符串数组，可含 `plrq_only`、`capital_deadline`，v1.1.6）、`null_reason`、`verify_pending`（`bank_balance`、`insurance_balance`、`non_a_share_capital`、`cdr_unit`）、`calc_version`。落 `market.financial_derived`，`metric = pb`，按交易日存（plan 第 1543 行，de86b99 版）。
- **对照**：麦蕊因子 `pb`（口径【待核实】）只出截面对照报告，Spearman 不作门禁（plan 2.12.1）。
- **引用**：L-01（经 F48）；P0。

### F48 `f.pb_pit_ind_pct` — PB（时点）行业内分位
- **口径依据**：plan 2.12.1 PB 条：“行业分位同 `pe_ttm` 的行业分位（申万一级、因子池排除、组内 N < 5 → `null`）”。下文规则与 F43 相同。
- **公式**：`rank_pct_in(f.pb_pit, f.sw_l1)`。池 = §1.4 股票池叠加 plan 2.12.1 因子池排除（停牌、ST/*ST、退市整理、上市 < 60 个交易日），并要求 `f.pb_pit` 非 null。按 d 日 `f.sw_l1` 分组，组内升序平均秩 / 组内 N。单位 `ratio`（0–1），4 位小数。L-01“PB 分位 ≤ 30%”写成 ≤ 0.3。
- **边界**：
  - `f.pb_pit` 为 null → null。因此归母权益 ≤ 0 或缺失的证券不进入分母（plan 原文“不参与行业分位排序”）。
  - 组内 N < 5 → null（同 F43；plan 2.12.1 PB 条已写明）。
  - `f.sw_l1` 为 null → null；`f.sw_l1` 无历史成分，落库日之前的回测截面一律 null（F26）。
  - `listing_status ∈ {delisted, missing_from_list}` → null（§1.7）。
  - **继承 F47 的 `verify_pending`**（`bank_balance`、`insurance_balance`、`non_a_share_capital`；T-B35 在特征值元数据里保留；plan 2.12.1 待核实标记）。带这三种标记的证券照常参与排序（T-R12f 补充裁定 8 确认）。
  - 非 null 数只在 §7C S2 中报告，不作门禁。
  - 本键为 null 的原因由 T-B35 记在特征值元数据（`group_too_small` / `input_null`），不是 `null_reason` 取值（v1.1.3）。
- **可得时点**：同 F47，且行业快照已存在。截面派生，不落 `financial_derived`。
- **引用**：L-01（PB 分位）；P0。

---

## 7B. 同一报告期多个 `plrq` 版本的含义与处理（T-R12）

**现象**：探针 p11 GAP3 发现 income 中同一 `jzrq` 有多行，`plrq` 不同，并列出了差异字段名，但**没有保存各版本的数值**。探针曾推测“披露日 − 报告期 > 400 天的行可能是被更正公告覆盖”。本节用巨潮原文核对这一推测。

**核对样本**（巨潮资讯网；PDF 文本对照，数值单位见各行）

| # | 证券、报告期 | 麦蕊 `plrq` 版本与差异字段（p11） | 原始报告 | 后一版本对应的公告 | 差异原因（原文核对结论） |
|---|---|---|---|---|---|
| 1 | 600519 2009-03-31 | 2009-04-21 / 2010-04-26；`gsssgdzhsyz`、`xsmgsy`、`zhsyz` | 《2009年第一季度报告》2009-04-21，https://static.cninfo.com.cn/finalpage/2009-04-21/51494501.PDF ：归母净利润 1,217,009,471.66 元；**没有**稀释每股收益和综合收益行 | 《2010年第一季度报告》2010-04-26，https://static.cninfo.com.cn/finalpage/2010-04-26/57870509.PDF ：上年同期列归母净利润同为 1,217,009,471.66；新增稀释 EPS 1.29、综合收益总额 1,278,840,567.82、归母综合收益 1,217,009,471.66 | **次年同期报告的比较数**，新增列报项目；利润额不变 |
| 2 | 600519 2010-09-30 | 2010-10-29 / 2011-10-18；`jbmgsy` 等每股字段 | 《2010年第三季度报告》2010-10-29，https://static.cninfo.com.cn/finalpage/2010-10-29/58594788.PDF ：年初至报告期末归母净利润 4,174,173,993.26，EPS 4.42 | 《2011年第三季度报告》2011-10-18，https://static.cninfo.com.cn/finalpage/2011-10-18/60069945.PDF ：上年同期归母净利润同为 4,174,173,993.26，EPS 重述为 4.02，注明“按照公司根据2010年度股东大会决议实施2010年度利润分配方案后的股本总数重新计算”。依据：《2010年度利润分配实施公告》2011-06-27，https://static.cninfo.com.cn/finalpage/2011-06-27/59599592.PDF （每 10 股送 1 股派 23 元，除权日 2011-07-01） | **送股导致每股指标追溯重述**；利润额不变 |
| 3 | 000001 2007-03-31 | 2007-04-26 / 2008-04-24；`jlr`、`gsmgsyzzdjlr`、`lrze`、`sdsfy`、`gyjzbdsy` 等 | 《2007年第一季度报告》2007-04-26，https://static.cninfo.com.cn/finalpage/2007-04-26/23091333.PDF （单位元）：净利润 535,083,658；公允价值变动收益 2,979,632；另列“投资性房地产公允价值变动” 534,080 | 《2008年第一季度报告》2008-04-24，https://static.cninfo.com.cn/finalpage/2008-04-24/39078279.PDF （**单位千元**）：上年同期净利润 535,084；公允价值变动收益 3,514（= 2,979,632 + 534,080 = 3,513,712，重分类后取整） | **列报重分类 + 单位变为千元导致取整差**。麦蕊 `jlr` 等字段出现差异，推测是千元取整造成的（麦蕊两版数值未保存在探针中：**未核实**） |
| 4 | 600000 2007-03-31 | 2007-04-28 / 2008-04-26；`jlr`、`gsmgsyzzdjlr`、`yysr` 等 | 《2007年第一季度报告》2007-04-28，https://static.cninfo.com.cn/finalpage/2007-04-28/23195982.PDF ：旧版银行报表格式，净利润 978,286,343.73 元 | 《2008年第一季度报告》2008-04-26，https://static.cninfo.com.cn/finalpage/2008-04-26/39207138.PDF ：上年同期净利润 981,189,275.46 元（+2,902,931.73） | **真实的数值重述**（比较数被追溯调整）。原文没有写原因；推测与 2007 年执行新会计准则有关（**未核实**） |
| 5 | 600000 1996-12-31 | `plrq` = 1996-12-31（= `jzrq`） | 1996 年数据最早公开于《上海浦东发展银行股份有限公司招股说明书概要》1999-09-20，https://static.cninfo.com.cn/finalpage/1999-09-20/171672.html （审计范围含 1996-12-31 资产负债表和 1996 年度利润表） | — | **占位行**：`plrq` 不是真实披露日。按 `plrq ≤ jzrq` 丢弃（裁定） |

另有两处直接数值核对（单版本）：600519 2001H1 `gsmgsyzzdjlr` 223,407,942.67 = 巨潮《股票上市公告书暨2001年中期财务报告》（2001-08-22，https://static.cninfo.com.cn/finalpage/2001-08-22/53299295.PDF ）的净利润，`plrq` 与公告日相同；000001 2026Q3 `gsmgsyzzdjlr` 39,186,000,000 = 巨潮《2026年三季度报告》（2026-10-24，https://static.cninfo.com.cn/finalpage/2026-10-24/1225620609.PDF ）的“归属于本行股东的净利润”年初至报告期末 39,186 百万元，`plrq` 与公告日相同。

**结论**

1. 样本中的后一版本都是**下一年同期定期报告里的“上年同期”比较数**。麦蕊把它作为同一 `jzrq` 的新一行保存，`plrq` 记为该定期报告的披露日。
2. 差异分三类：
   - (a) 新增列报项目，数值不变（样本 1）；
   - (b) 每股指标因送转追溯重述，或金额因单位或重分类出现取整差（样本 2、3）；
   - (c) 真实的金额追溯调整（样本 4）。
3. 探针“披露日 − 报告期 > 400 天 = 被更正公告覆盖”的推测，在样本中**不成立**：长滞后行来自次年报告的比较数。
4. 本次样本中**没有出现**“会计差错更正公告”“更正后的定期报告”类型。麦蕊如何记录这类版本（是否新增行、`plrq` 是否为更正公告日）**未核实**（V5f）。
5. 版本数值在次年的取值可能变化（样本 4），因此必须按版本的可见时间选用。若一律取最新版本，就是用了未来信息。

**确定性处理规则（写入 T-B55；与 §7A.0 版本选择一致）**

| # | 规则 |
|---|---|
| R1 | `plrq ≤ jzrq` → 丢弃（占位行）|
| R2 | 其余每一行都是独立版本，`available_from` 按 §7A.0 第 3 条计算；评估时刻 T 只取 `available_from ≤ T` 的最新版本 |
| R3 | 新版本不回写已落库的派生值；从自己的 `available_from` 起生效（这正是样本 4 应有的效果：2008-04-28 前用 978,286,343.73，之后用 981,189,275.46） |
| R4 | 版本类型只作为元数据记录（`basis.version_kind`），不影响计算。规则：同一 (code, report_type, jzrq) 中 `plrq` 最早的非占位行为 `original`；后续行的 `plrq` 等于该公司另一个 `jzrq′ > jzrq` 报告行的 `plrq` 时为 `comparative`；其余为 `other`（可能是更正或补充，待 V5f 核实） |
| R5 | 不用每股字段（`jbmgsy`、`xsmgsy` 等）参与 F42–F48；不做跨版本数值精确相等比较 |
| R6 | 同一 `available_from` 出现两行且数值不同 → 先取 `first_seen_at` 较晚的；仍无法区分 → 分量 null，并告警 `data_conflict` |
| R7 | F12 `f.fin_report_count`、F22 `f.np_yoy_latest` 同样适用 R1、R2（F12 只计 distinct `jzrq`，不受多版本影响） |

---

## 7C. L-01 线上从麦蕊因子切到自算口径的条件（T-R12）

裁定只规定研究与回测改为自算，**没有给出线上切换时点**（plan 第 829 行⑤：由研究员决定）。下列条件全部满足后才能切换。阈值除注明“裁定”的外，均为研究员设定的确定值，修改需要升 feature_spec 版本。

| # | 条件 | 检验方法（确定性） | 出处 |
|---|---|---|---|
| S1 | 新键已实现并落库 | T-B55 已交付并通过验收（属性测试“任一 T 只用 `available_from ≤ T` 的数据”、净利润 ≤ 0 时 PE 为 null、银行和保险负债率为 null、T-B35 能读取）；F42–F48（v1.1.1 起含 PB 两键）在 `feature_catalog.status` 中为 **`verified_live`**（L-01 published 的前提是“必需字段全部 verified_live”，plan 第 867 行）。**V5b、V5c、V5d、V5e、V5g、V5h、V5i、V5j 已关闭**（v1.1.3，plan 2.12.1“T-R12b 补充裁定”4，1c62952 版第 1260–1265 行；§9 问题 96 默认执行，用户可改；v1.1.5 加 V5i、V5j，plan 2.12.1“T-R12e 补充裁定”1、3）：① 所有 `basis.verify_pending` 取值（`bank_balance`、`insurance_balance`、`non_a_share_capital`、`cdr_unit`）都已由 T-B05 清除，T-B55 重算后不再写该标记；例外（v1.1.10，plan 2.12.1“T-R13 补充裁定”，847f41e 第 2 条）：`cdr_unit` 逐只清除，尚未对照巨潮披露 CDR 份数的 CDR 可保留该标记，不阻塞切换。**V5g 关闭条件（v1.1.5 重写，plan 2.12.1“T-R12e 补充裁定”2）**：A+B、A+H 公司名单已接入（注明来源和日期），因此不再有 `basis.share_class_check = unavailable` 的行；`zgb` 是否包含 B、H 股已用一家 A+H、一家 A+B 公司对照巨潮披露的总股本核实；（v1.1.8，plan 2.12.1“T-R12h 补充裁定”2、3）名单内所有记录都已 `verified=true`（核对来源为巨潮或港交所披露）；211 对与 209 对两个来源的差异已查明，结论写入名单的 `sources`。② **V5d 关闭条件**：T-B05 写出结论；如果 capital 行普遍晚于除权日才可见，则送转数据已经接入，且切换时 `basis.share_change_check` 不再为 `unavailable`。③ **V5h 关闭条件**：确认币种、单位字段的字段名，或确认没有这类字段；没有字段时，结论中写明“只靠 B5 的数量级不连续检查”。关闭条件（v1.1.10，plan 2.12.1“T-R13 补充裁定”，847f41e 第 1 条）：抽样的全部财报和 capital 响应里都没有字符串值，也没有任何以币种、单位为含义的字段，即可按“确认没有这类字段”关闭；抽样范围为 income、balance、cashflow、capital 四个接口，每个接口至少覆盖 600519（普通股）、000001（银行）、601318（保险）、000550（A+B）；CDR 不在 F43、F48 的池和 S2 的池 U 内，不要求 689009 的 income、cashflow；结论写“没有币种、单位字段，只靠数量级不连续检查”，不需要字段含义的文档依据；由 T-B05 写入 `docs/mairui-verified.md` ⑨ 后 V5h 关闭（在此之前未关闭）。④ **V5i 关闭条件**（v1.1.5）：T-B05 用 600519 等样例写出结论（麦蕊是否回填 capital 行的 `plrq`）；确认 `plrq` 是真实披露日 → 取消 §7A.0“capital 行可见时间”的保守规则；否则保守规则继续生效。⑤ **V5j 关闭条件**（v1.1.5；v1.1.6 按 T-R12f 补充裁定 5、7 更正）：CDR 以 `market.securities.type = cdr` 识别；T-B05 已确认 CDR 的 `zgb` 按基础股份还是按 CDR 份数计，并按两种情况清除 `cdr_unit`（v1.1.7，plan 已裁定（9ad51b8，T-R12g））——按 CDR 份数计：总市值 = `c × zgb`，不需要转换比例配置，T-B05 确认后即清除；按基础股份计：总市值 = `c × zgb × 转换比例`，每只 CDR 的转换比例（每股基础股份对应的 CDR 份数）已按证券写入配置并注明来源（招股书或上市公告）后清除。v1.1.10（plan 2.12.1“T-R13 补充裁定”，847f41e 第 2、3 条）：V5j 以 689009 的实测为准关闭（关闭须 T-B05 按下述容差确认并由后端清除 689009 的标记、验收）；`cdr_unit` **逐只清除**，不对全部 `type = cdr` 推广：只有对照过巨潮披露 CDR 份数的证券才清除，其他 CDR 保留标记；CDR 不进 S2 的池，保留的标记不阻塞切换（plan 2.12.1“T-R13 补充裁定”，847f41e 第 2 条）；判定容差（plan 2.12.1“T-R13 补充裁定”，847f41e 第 3 条）：|zgb − 披露的 CDR 份数| / 披露的 CDR 份数 ≤ 0.1% → 按 CDR 份数计；zgb 与“披露的 CDR 份数 ÷ 每股基础股份对应的 CDR 份数”相差同样不超过 0.1% → 按基础股份计；两条都不满足 → 保留 `cdr_unit` 并告警 `data_quality` | plan T-B55、第 867、1400 行；plan 2.12.1 待核实标记、T-R12b 补充裁定 4、T-R12e 补充裁定 1–3（fdd7fdd）、T-R12f 补充裁定（38d7888）、T-R12g（9ad51b8）、T-R12h 补充裁定（7ec6fad）；T-R13 补充裁定（847f41e）；§9 问题 96 |
| S2 | 全市场截面覆盖率 | 在对照期的每个 L-01 月度截面 d，池 U = F43 的池（§1.4 + 因子池排除，即 d 日可交易、非 ST、非退市整理、上市满 60 个交易日）。**总则（v1.1.2）**：所有键的覆盖率都先从 U 中剔除 `basis.verify_pending` 非空的证券，**分子、分母同时剔除**，并按标记（`bank_balance`、`insurance_balance`、`non_a_share_capital`）分别单列剔除个数（plan 2.12.1 待核实标记）。U 按 §1.4 本来不含 CDR，`cdr_unit` 不参与本条剔除与计数（v1.1.7，plan 已裁定（9ad51b8，T-R12g）；撤销 v1.1.5 的 CDR 剔除写法）。要求：`f.roe_ttm_pit` 非 null 比例 ≥ 95%；`f.debt_ratio_pit` 在 U 中剔除银行、保险后非 null 比例 ≥ 95%；在 `NP_TTM > 0` 的子集中，`f.pe_ttm_pit` 非 null 比例 ≥ 99%、`f.ocf_to_np_ttm_pit` 非 null 比例 ≥ 95%。另外，`f.pe_ttm_pit` 非 null 数不得少于同日 `f.pe_ttm`（麦蕊，> 0）非 null 数的 95%。**PB（v1.1.2，架构师裁定 T-R12a，plan 2.12.1 第 1226–1233 行）**：分母 D(d) = U 剔除①T 时所选报告期归母权益**已知且 ≤ 0** 的证券、②`verify_pending` 非空的证券；归母权益**缺失**的证券留在 D(d) 中，计为未覆盖。分子 = D(d) 中 `f.pb_pit` 非 null 的个数。全市场：分子 / D(d) ≥ **99%**。申万一级行业：组内 D ≥ 5 的行业，组内覆盖率 ≥ **95%**；组内 D < 5 的行业不考核，但要列出；`f.sw_l1` 为空的证券只计入全市场口径，单列个数。F48 `f.pb_pit_ind_pct` 非 null 数只报告，不作门禁 | 研究员设定；PB 条为架构师裁定（T-R12a） |
| S3 | 巨潮原文抽样核对 | 每次核对抽 30 只证券：5 只银行或非银金融、5 只历史上有多版本的、20 只按固定种子随机抽取（种子为核对日 YYYYMMDD）。每只取 T 时所用 P 的 `gsmgsyzzdjlr`（YTD）和 `gsmgdqsyhj`，与巨潮定期报告原文比较，误差 ≤ 原文报告单位的 0.5 倍（元、千元、百万元）。所用版本的 `plrq` 不得早于巨潮公告日（0 容忍，否则就是未来函数），也不得晚于公告日后 1 个交易日。**30/30 通过**才算通过；任一失败须查明原因并修复，然后用新种子重新抽 30 只 | 研究员设定 |
| S4 | 对照期长度 | 自算键与麦蕊因子在线上**并行**计算，至少覆盖**连续 3 个** L-01 月度截面，且其中至少一个截面在法定披露截止日（4-30、8-31、10-31）之后 10 个交易日内，以检验版本切换。每个截面输出对照报告：Spearman ρ、两侧前 30 名的重合数、覆盖率。**Spearman 只报告，不作为门禁（裁定）**。对照期内 L-01 线上信号仍用旧键 | 裁定（Spearman）；长度由研究员设定 |
| S5 | 切换时点与版本 | 在 S1–S4 全部满足后的第一个交易日**盘后**（日线落库后、当日 L-01 扫描之前）执行：L-01 卡的 `strategy_versions.version_no` +1，新版本引用 F42–F48；旧版本退役，不修改已发布内容。切换后的第一个 L-01 月度扫描起使用新键 | plan“发布后不可改，改内容即递增 version_no” |
| S6 | 旧信号标注 | 切换前产生的 L-01 候选和信号保留原值，不重算，元数据标 `basis = mairui_factor`、旧 `version_no`；切换后的标 `basis = pit_self_calc`。回测报告继续带 `survivorship_bias = true`（裁定） | 裁定（survivorship） |

一句话：**F42–F48 为 `verified_live`，连续 3 个月度截面覆盖率达标，巨潮 30 只抽样全部通过，满足以上条件后的第一个交易日盘后，L-01 递增版本号并切换到新键；旧信号标 `basis = mairui_factor`。**

---

## 8. P1 特征与非正式键

### F41 `f.excess_ret_std_60d` — 60 日超额收益标准差（P1）
- **出处**：`validation.md` 第 225 行（“需新增特征，例如 `f.excess_ret_std_60d`，当前 feature_catalog 没有”），用于 T+1 日内阈值 σ_ex。
- **公式【建议】**：`stdev(r_i − r_bench,i, ddof=1)`，r 用 qfq 收盘日收益，i ∈ 最近 60 个交易日中的有效 K 线；基准指数【待研究员在 validation 中定，建议中证全指】。单位 `ratio`，6 位小数。
- **边界**：有效 K 线 < 45 → null。
- **可得时点**：d 日盘后。
- **引用**：验证模块；P1。

### 前端 mock 中的非正式键（不登记、不计入 48）
`src/frontend/src/mocks/marketFixtures.ts` 第 328–339 行与 `fixtures.ts` 第 820–822 行除正式键 `f.pe_ttm`、`f.roe_ttm`、`f.ma_trend` 外，还用了 **11 个不在任何策略文档或 catalog 中的键**：`f.pb`、`f.dividend_yield`、`f.gross_margin`、`f.revenue_yoy`、`f.np_yoy`、`f.mom_20d`、`f.mom_60d`、`f.vol_60d`、`f.turnover_20d`、`f.amount_20d`、`f.atr_pct`。其中 4 个与正式键近名易混：`f.amount_20d`→`f.amount_20d_avg`、`f.turnover_20d`→`f.turnover_20d_avg`、`f.mom_60d`→`f.momentum_60d`、`f.np_yoy`→`f.np_yoy_latest`。v1.1.1 起 `f.pb` 与正式键 `f.pb_pit` 也近名易混。建议前端改用正式键，或在 mock 注明“展示用、非 catalog 键”；其余 7 个如需上线，先由研究员登记到本文。本文不修改前端。
---

## 9. 手算样例（3 组，**合成数据，不是真实行情**，只用于 T-B30a 单测对数）

### 样例 1：20 日价量类 + rank_pct（证券“样例甲”，沪市主板，非 ST，`list_days = 800`，窗口内无除权）
d = D20；D0 收盘 10.00；D8 停牌（`sf=1`、`v=0`）；D12 收盘涨停。成交额单位亿元（落库换算为元）。

| 日 | c | h | l | a(亿) | 涨停价=round(前收×1.1) | r = c/前有效收 − 1 | amp = (h−l)/前有效收 |
|---|---|---|---|---|---|---|---|
| D1 | 10.10 | 10.22 | 10.02 | 3.2 | 11.00 | 0.010000 | 0.020000 |
| D2 | 10.05 | 10.15 | 9.93 | 2.8 | 11.11 | −0.004950 | 0.021782 |
| D3 | 10.20 | 10.35 | 10.15 | 3.5 | 11.06 | 0.014925 | 0.019900 |
| D4 | 10.15 | 10.23 | 10.05 | 3.0 | 11.22 | −0.004902 | 0.017647 |
| D5 | 10.30 | 10.48 | 10.24 | 4.1 | 11.17 | 0.014778 | 0.023645 |
| D6 | 10.25 | 10.34 | 10.14 | 3.6 | 11.33 | −0.004854 | 0.019417 |
| D7 | 10.40 | 10.54 | 10.33 | 3.9 | 11.28 | 0.014634 | 0.020488 |
| D8 | 停牌 | — | — | — | — | 不计 | 不计 |
| D9 | 10.35 | 10.45 | 10.23 | 3.3 | 11.44 | −0.004808（相对 D7） | 0.021154 |
| D10 | 10.50 | 10.66 | 10.45 | 4.4 | 11.39 | 0.014493 | 0.020290 |
| D11 | 10.45 | 10.53 | 10.32 | 3.8 | 11.55 | −0.004762 | 0.020000 |
| D12 | **11.50** | 11.50 | 10.50 | 9.6 | **11.50**（10.45×1.1=11.495→11.50） | 0.100478 | 0.095694 |
| D13 | 11.00 | 11.00 | 10.70 | 5.2 | 12.65 | −0.043478 | 0.026087 |
| D14 | 10.90 | 11.02 | 10.80 | 4.7 | 12.10 | −0.009091 | 0.020000 |
| D15 | 10.80 | 10.90 | 10.66 | 4.0 | 11.99 | −0.009174 | 0.022018 |
| D16 | 10.95 | 11.08 | 10.87 | 4.5 | 11.88 | 0.013889 | 0.019444 |
| D17 | 11.05 | 11.17 | 10.95 | 5.0 | 12.05 | 0.009132 | 0.020091 |
| D18 | 10.98 | 11.07 | 10.86 | 4.2 | 12.16 | −0.006335 | 0.019005 |
| D19 | 11.10 | 11.24 | 11.04 | 4.8 | 12.08 | 0.010929 | 0.018215 |
| D20 | 11.20 | 11.35 | 11.12 | 5.5 | 12.21 | 0.009009 | 0.020721 |

计算：
- 有效 K 线 19 ≥ 15 → 可算。停牌日 D8 既不当 0、也不插值。
- `f.amount_20d_avg` = 83.1 亿 / 19 = 4.373684… 亿 → **437,368,421 元**（四舍五入到元）。IT2 档：≥ 2 亿 → 15 分；SH1：≥ 3 亿 → 20 分；SW1：≥ 1 亿 → 15 分。
- `f.volatility_20d` = stdev(19 个 r, ddof=1) = **0.026871**。
- `f.intraday_amplitude_20d` = mean(19 个 amp) = **0.024505**。
- `f.limit_up_count_20d` = **1**（只有 D12 收盘价 = 涨停价；D13 等日不触及）。
- 反例：若把 D8 当成 a=0 的有效日，均额会变成 4.155 亿（错）；若把 D8 的收益记 0，则波动被低估。

**rank_pct 样例**（同一 d，假设截面只有 8 只）：

| 证券 | 状态 | `f.volatility_20d` | 是否入池 | 平均秩 | rank_pct |
|---|---|---|---|---|---|
| A | 正常 | 0.010 | 是 | 1 | 0.2 |
| B | 正常 | 0.020 | 是 | 2.5 | 0.5 |
| C | ST | 0.020 | 是（ST 不剔除） | 2.5 | 0.5 |
| D | 正常 | 0.030 | 是 | 4 | 0.8 |
| E | 正常 | 0.050 | 是 | 5 | 1.0 |
| F | 正常 | null | 否（值为 null） | — | null |
| G | d 日停牌 | 0.040 | 否 | — | null |
| H | 北交所 | 0.060 | 否 | — | null |

N = 5。B、C 并列占第 2、3 位，平均秩 2.5，`2.5/5 = 0.5`。SH4 的“0.4–0.9 加分”对 B、C、D 成立。

### 样例 2：60 日趋势类 + 除权（“样例乙”，深市主板，`list_days = 300`）
d = D61，b = D1（d 往前第 60 个交易日）。全部有效 K 线。D41 为 10 转 10 除权日（无现金分红），前复权因子 = 0.5（D40 及以前）。
- 不复权收盘：D1–D40 为 `10.00 + 0.05×(k−1)`（D40 = 11.95）；D41–D61 为 `6.00 + 0.03×(k−41)`（D61 = 6.60）。
- 前复权收盘：D1–D40 为 `5.000 + 0.025×(k−1)`（D40 = 5.975）；D41 起与不复权相同。

计算：
- `f.momentum_60d` = (6.60 / 5.00 − 1) × 100 = **32.00**。若误用不复权：6.60/10.00 − 1 = −34.00%，符号相反，SW3 由 15 分变 0 分。
- MA20（D42–D61，qfq）= (6.03 + 6.60)/2 = 6.315；MA60（D2–D61，qfq）= (214.5 + 132.3)/60 = 5.780。
- `f.ma_trend` = (6.315 / 5.780 − 1) × 100 = 9.2561 → **9.26**（> 0，SH5 +10、SW2 +20）。误用不复权会得 −32.50。
- D41 的涨跌停价：基准价为除权参考价 11.95 / 2 = 5.975，`f.limit_up_price` = round_half_up(5.975 × 1.1 = 6.5725) = **6.57**；若误用不复权前收 11.95 会得到 13.15（错）。
- 上市天数分支：若同一证券 `list_days = 18`，HG5 封顶 59，且它不进 d 日 rank 池（`rank_pct = null`）；`list_days = 45` 时 HG6 只封顶 swing/long，`f.momentum_60d` 因上市不足 61 日为 null。

### 样例 3：基本面/状态 + `user.avg_holding_days`
**(a) `f.fin_report_count`**，d = 2026-04-30（周四），某股报告：

| jzrq | plrq | next_trading_day(plrq) | 计入？ |
|---|---|---|---|
| 2023-03-31 … 2025-09-30 共 11 期 | 均早于 2026-04-29 | ≤ d | 是（11） |
| 2025-12-31（年报） | 2026-04-29 | 2026-04-30 | 是 |
| 2026-03-31（一季报） | 2026-04-30 | 2026-05-06（示例假设劳动节休市后的首个交易日） | **否**（d 日盘后才披露，d+1 起可得） |

→ `f.fin_report_count(d) = 12`，LG0 通过；同一数据在 d−1 = 2026-04-29 只有 11 期 → LG0 封顶 59。（日期为示例，节假日安排以交易日历为准。）

**(b) 风险标记**（主数据简称 → 特征）：

| 简称 | risk_flag | listing_status | f.is_st | f.is_delisting_period | 分类器 |
|---|---|---|---|---|---|
| ST某某 | st | listed | true | false | HG4 封顶 59 |
| \*ST某某 | star_st | listed | true | false | HG4 封顶 59 |
| 某某退 | delisting | delisting_period | true | true | HG3 0 分（同时 HG4，0 分优先） |
| 某某 | null | listed | false | false | 无闸门 |
| （主数据缺失） | — | null | null→按 true | null→按 false | HG4 + 数据缺失 |

**(c) `user.avg_holding_days`**（按 §10 Q76 建议口径；单账户，单证券 X；trading day 序号 TDn 为交易日历序号）：

| 序 | 日 | 业务 | 数量 | 说明 |
|---|---|---|---|---|
| 1 | TD−5 | 买 L0 | 200 | |
| 2 | TD−2 | 卖 | 200 | 配 L0：200 股 × 3 天 |
| 3 | TD0 | 买 L1 | 1000 | |
| 4 | TD10 | 买 L2 | 500 | |
| 5 | TD15 | 10 送 5（`account_events.kind=bonus_share`） | +750 | L1 → 1500 股、L2 → 750 股，**继承原买入日** |
| 6 | TD20 | 卖 | 1200 | 配 L1：1200 × 20 天 |
| 7 | TD25 | 买 L3 | 300 | 做T买回 |
| 8 | TD26 | 卖 | 600 | 配 L1 余 300 × 26 天；L2 300 × 16 天 |
| 9 | TD30 | 卖（**作废成交**） | 100 | 不计 |
| 10 | TD40 | 卖 | 450 | 配 L2 余 450 × 30 天 |
| — | as_of | L3 300 股未平仓 | | 不计 |

加权：(200×3 + 1200×20 + 300×26 + 300×16 + 450×30) / (200+1200+300+300+450) = 50700 / 2450 = 20.69 → **21** 个交易日。有已平仓部分的买入批次 = L0、L1、L2 = 3 个 ≥ 3 → 非 null。SH8（≤ 5）不加分；SW7（5–60）+10；LG7（≥ 60）不加分。若没有第 1、2 行，批次只有 2 个 → **null**（按未填写，不封顶、不提示）。
---

## 10. plan 第 9 节问题 76、77 复核（研究员）

> 被复核文本：plan 第 3257 行（问题 76）、第 3258 行（问题 77）、2.5.3 第 2681 行“用户输入口径”、裁定 R9。下文只引仓库内已有出处；没有出处的写明“研究员建议”。

### 10.1 问题 76 `user.avg_holding_days`

**结论：同意（FIFO、365 日、数量加权、< 3 批次为 null 的方向都同意），但口径不完整，需补 8 条确定性规则；其中 1 条（统计维度）与文字表述存在歧义，需要确认。**

| # | 议题 | 现有文本 | 意见 | 理由（出处） | 建议的确定性口径 |
|---|---|---|---|---|---|
| 1 | 统计维度 | “本人全部账户……买入批次” | **有异议（歧义）** | 规则文本是“该股历史平均持有 {v} 个交易日”（SH8/SW7/LG7 text，`horizon_classifier.md`）；`horizon_classifier.md` §1 也按“该证券”评估；R9 未写“按证券” | 按（用户, 证券）计算：本人全部账户中**该证券**的成交。账户之间不合并库存（FIFO 在每个账户内独立进行），算出的配对片段再跨账户合并加权 |
| 2 | 配对方法 | FIFO | 同意 | A 股 T+1（`market_rules.yaml` `t_plus: 1`，`market_rules_T-R10.md`）：当日买入不能当日卖出，FIFO 下卖出总是先配最早的可卖批次，与交易制度一致；与成本口径（摊薄成本，问题 19）是两回事，互不影响 | 按成交时间（同时刻按成交编号）排序；每笔卖出依次消耗最早的未平仓批次，产生（买入批次、卖出、数量）片段 |
| 3 | 同日买卖 = 0 天 | 有 | 同意（防御性） | T+1 下股票同日买的不能同日卖；FIFO 配对时同日卖出只会配到更早的批次，所以 0 天片段对 A 股股票实际不会出现。保留规则以覆盖 ETF 当日回转（`market_rules_T-R10.md` ETF 规则）等情形，但分类器只覆盖股票（HG1） | 持有天数 = 卖出日交易日序号 − 买入日交易日序号（交易日历，**停牌日照计**） |
| 4 | 做T（有底仓先卖后买/先买后卖） | 未写 | 补充 | FIFO 会把做T 的卖出配给老底仓，得到长持有天数，这是“底仓持有多久”的真实描述；做T 行为另由 `user.has_t_trades`（IT4）表达，两者不重复计分 | 不对做T 特殊处理；不做“清仓周期”（round trip）口径 |
| 5 | 窗口 | 最近 365 个自然日 | 同意，补边界 | “已平仓”只有在卖出时才发生 | **按卖出日**筛选：`as_of − 365 自然日 < 卖出日 ≤ as_of`；但 FIFO 回放必须从该账户该证券**最早的成交**开始，否则窗口起点前买入、窗口内卖出的片段会配错 |
| 6 | 期初库存（快照导入、转托管转入 `transfer_in`、新股中签 `ipo_allot`） | 未写 | 补充 | `account_events.kind` 含 `transfer_in`、`ipo_allot`（plan 第 1308 行）；快照导入没有买入日期 | `ipo_allot` 视为买入批次，买入日 = 入账日（上市前的入账日【待核实：应取上市日还是中签缴款日，研究员建议取上市首日】）；`transfer_in` 与无法溯源的期初持仓：**配到它们的卖出片段整体剔除**，不得按 0 天或导入日计算 |
| 7 | 送转股、分红 | 未写 | 补充 | plan 第 1662 行“送转股只加数量”；`account_events.kind` 有 `bonus_share`、`rights` | `bonus_share`：按事件日前各未平仓批次的数量**等比例**分配新增股，新增部分**继承原批次买入日**；`rights`（配股）：作为新买入批次，买入日 = 配股上市日；现金分红不影响天数；送转事件缺失导致卖出数量超过库存 → 超出部分剔除并在评估快照 `inputs_missing` 外另记数据质量告警 |
| 8 | 作废成交 | 不计 | 同意 | 导入夹具有撤单/废单行（T004 TC-SIDE-03：撤单 → `IMPORT_ROW_CANCELLED`、废单 → `IMPORT_ROW_REJECTED`，均不入库） | 作废、撤单、未成交的记录不进入回放 |
| 9 | 加权与取整 | 数量加权、取整 | 同意，补规则 | — | 权重 = 配对片段的股数（送转后股数）；取整 `ROUND_HALF_UP`（20.5 → 21） |
| 10 | 样本门槛 | 已平仓批次 < 3 → null | 同意，需定义“批次” | R9 原文“已平仓的买入批次”；完全平仓与部分平仓未区分 | “批次” = 一笔买入成交（或 `ipo_allot`/`rights` 事件）；**在窗口内有至少一个已配对片段即计 1 个**（部分平仓的已平仓部分参与加权，未平仓部分不计）；去掉第 6 条剔除的片段后计数 < 3 → null。null 时按“未填写”处理：不封顶、不提示（裁定 R9 / plan 第 2681 行，不变） |

研究员补充：该口径会让“分批建仓、长期持有”的用户在批次少时得到 null，属于预期（宁缺毋滥）。样例见 §9 样例 3(c)。

### 10.2 问题 77 “退市风险警示按 ST 处理”

**结论：同意结果（`f.is_st = risk_flag ∈ {st, star_st, delisting}`，宁可少推荐），但对问题 77 的措辞与依据有异议：`risk_flag=delisting` 不是“退市风险警示”。**

| # | 议题 | 意见 | 理由（出处） | 建议的确定性口径 |
|---|---|---|---|---|
| 1 | 术语 | **有异议** | `security_master.md` §5-5：`*ST` 前缀 → `*ST`；简称含“退” → `退`（例：“\*ST萃华→萃华退”）。`*ST` 即“退市风险警示”，对应 `star_st`；`delisting` 对应简称含“退”，即**退市整理期/已退市**的证券。plan 第 3258 行、第 2681 行把 `delisting` 写成“退市风险警示”，`src/backend/app/research/content.py` 第 53 行 `_RISK_TEXT["delisting"]`的说明文字（“该证券处于退市风险警示状态”）同样有误 | 改称：`star_st` = 退市风险警示（\*ST）；`delisting` = 退市整理（简称含“退”）。plan 第 3258/2681 行与 content.py 第 53 行的措辞由架构师/后端修订（研究员无权改） |
| 2 | 计入 `f.is_st` 的实际影响 | 同意 | `star_st` 本来就在集合内（真正的“退市风险警示”已被覆盖）；`delisting` 证券绝大多数同时 `listing_status = delisting_period` → HG3 直接 0 分，HG4 的 59 封顶是冗余的、无害 | 保持 `inputs.py` 现状，不改代码 |
| 3 | ST 与 \*ST 同等处理的交易规则依据 | 同意 | `market_rules_check.md`：沪深主板 ST 与 \*ST 涨跌幅相同（2026-07-06 起 10%、此前 5%）；风险警示股票单只当日累计买入 ≤ 50 万股（沪 4.4.10；深交所同类条款“未逐字核对”，M5）、只能限价申报（沪 4.4.9，M6），条文对象是“风险警示股票”，不区分 ST 与 \*ST | v1 不新增 `f.is_delisting_risk`；如需在理由中区分 \*ST，用 `sec.risk_flag` 生成文本即可（P1 提示，不影响分数） |
| 4 | 一致性与边界 | 补充 | 契约 `listing_status` 另有 `delisted`、`missing_from_list` | ① `risk_flag = delisting` 而 `listing_status ≠ delisting_period`（或反之）→ 数据质量告警（主数据两字段都由简称派生，应一致）；② **【已定，T-R11b】`listing_status ∈ {delisted, missing_from_list}` 的证券，全部 `f.*` 置为 null**（含 `f.is_st`、`f.is_delisting_period`，不返回 false），T-B30a 不产出数值；判定以 d 日 18:00 主数据快照为准，回测取 t 当日有效区间。是否另由分类器入口拒绝属实现，由架构师定 |
| 5 | 时点 | 补充 | 主数据 18:00 拉取（`security_master.md` §6-1）；历史区间表 `security_risk_flag_history` | d 日的 `f.is_st` 用 d 日 18:00 快照，用于 d+1；回测取 t 当日有效区间；沪/京历史只从上线日起可得，之前的回测期 ST 状态缺失 → null（按 true 处理会把历史 ST 未知的股票都封顶，**回测时需注明此偏差**） |

---

## 7D. 文档依据状态登记（v1.1.12，plan T-A14「T-R18 裁定」，af94de3）

键级状态登记在 §12 机器可读草案的 `status` 与 `status_basis` 字段中（只改下表所列键；v1.1.15 起含 F23），证据见 `T-R18_source_matrix.yaml` 对应行（F23 见 `T-R62/README.md` 与 `T-R62/rules_freeze_v3.yaml`）。`verified_doc` 最多只能晋级到 simulating（plan 2.5.13 G2），**不是 `verified_live`，不代表可以实盘，也不代表 G2 整体通过**。

| 键 | 状态 | 裁定条 | 限定 |
|---|---|---|---|
| f.close_qfq / f.high_qfq / f.low_qfq（F16–F18） | verified_doc | ② | 只用 as_of 当次取数并存快照；历史回写值不作时点依据、不用于回测；单位“元/股”是推断，记入 gaps，待 T-B05 |
| f.list_days（F13） | verified_doc | ③ | list_date 早于交易日历覆盖起点时为 null，记 gap（insufficient_data），不估算 |
| f.np_yoy_latest（F22） | verified_doc | ④ | 可见时点沿用 F22 `next_trading_day(plrq) 09:30`；V5f 未结前以首次观测值为准，带 observed_at；更正作为新观测，不改写旧快照；V5f 随 T-B05 复核 |
| f.amount（F19） | verified_doc（v1.1.13，plan「T-R19 裁定」①，78de694） | T-R19① | T-B81 两只股票的样本只算样本级实测证据；verified_live 要等 T-B05 扩大覆盖 |
| f.market_regime_idx（F50，新增） | verified_doc（v1.1.13，T-R19③） | T-R19③ | 只用 000300.SH，adjust none，不含 F24；最多到 simulating |
| f.rsi14（F20）、f.limit_up_price / f.limit_down_price（F35/F36）、f.limit_locked_up / f.limit_locked_down（F39/F40）、f.is_suspended（F49） | verified_doc（v1.1.14，plan「T-R21 裁定」①–④，86d42f2） | T-R21 | 最多到 simulating，不是 verified_live；F35/F36 只用 pc，pc 缺失、无效或与 jnfh 冲突时为 null 并记 gap；送转、沪市样本缺口和主板历史 ST 为 null 的缺口向下传给 F39/F40；F49 只认 sf，缺失为 null 且不可执行；RSI 全平盘为 null |
| f.ann_risk_count_10d（F23） | verified_doc（v1.1.15，plan「T-A153 裁定」） | T-A153 | 词表 v3 冻结（lexicon `8a545da8…`、matcher `d3e930a8…`）；最多到 simulating，**不宣称 FP≤5%**（CI 上界 17.18%）；样本两日非连续（v4 起连续日纪律）；FP-3（300550）与 Q-5 扩表并入 v4；`verified_live` 仍需 T-A19 两项实测，N-01 `KEY_DATA_MISSING` 不解除 |
| f.main_net_20d、f.market_regime、f.ind_rs20 | declared | ⑤ / T-R19②③④ | 需要实测或补来源；H-01、W-01 的 G2 仍不通过 |

**裁定④已确认**：架构师明确“plrq”沿用 F22 的 `next_trading_day(plrq) 09:30`，不放宽原 `pit_rule`；首次观测与更正快照仍遵守上表限定。

## 11. 缺口与【待核实】清单

| # | 项 | 涉及特征 | 需要谁 | 怎么核 |
|---|---|---|---|---|
| V1 | 日线 `a` 单位（元/万元）；快照 `v` 单位（手/股） | F01、F19、F28 | 后端 T-B05 | **已实测（run-20261101-190106/p11 GAP2_cje_v_units）**：日线 `latest`：`a`=元、`v`=手；券商源 `/hsstock/real/time`：`cje`=元、`v`=手、`pv`=股（`pv/v`=100），F28 应为 `cje/(v×100)`；网络源 `/hsrl/ssjy`：`v`=万手（文档写"手"，不符）、`cje`=元。方法：VWAP 须落在当日高低价内；"股+元"与"万股+万元"同比例，按成交额量级取"元" |
| V2 | 日线 `pc` / 快照 `yc` 在除权日是否为除权参考价 | F24、F35–F40、F11 | T-B05 | 取一只近期除权股，对比除权日 `pc` 与前一日 `c` |
| V3 | 麦蕊因子公式与单位：`turnover_20d_avg`、`amihud_20d`、`volatility_20d`、`intraday_amplitude_20d`、`ma_trend`、`momentum_60d`、`roe_ttm`（12 还是 0.12）、`profit_cagr_3y`、`dividend_continuous_years`（从未分红返回 0 还是空）、`limit_up_count_20d`、`pe_ttm`（亏损返回负数还是空）、`boll_squeeze`、`rsi_14` | F02–F11、F20、F31、F33 | T-B05 + 研究员 | 全市场同日截面对照 §2 主口径，Spearman ≥ 0.95（建议） |
| V4 | 因子历史值是否“当时口径”（as-of） | F02、F03、F08–F10、F33 | T-B05 | **部分实测（run-20261101-190106/p11 GAP6_factor_nulls_pit）**：600519 `profit_yoy`、`roe_ttm` 历史（2025-05-06～2026-10-30，369 点）5 次真实跳变均在 `plrq` 当日或其后首个交易日；探针标的 2 处"披露前跳变"为 6 位小数截断差异，非前视。未覆盖：其他股票/因子（含 F02、F03、F09、F10、F33）、2025-05-06 前是否回填。仍待：间隔 ≥1 周重取比对；用 `plrq ≤ T` 报表自算逐点比对 |
| V5 | 财务报表除 `jzrq`、`plrq` 外的字段名（净利润、归母净资产） | F08 备选、F12、F22、F42–F48 | T-B05 | **部分实测（v1.1.0，探针 p05 样本 + 巨潮核对，§7A.0）**：归母净利润 `gsmgsyzzdjlr`（累计、元）、归母权益 `gsmgdqsyhj`、`fzhj`、`zczj`、`zgb`/`bdrq`/`plrq` 已见于样本；余项见 V5b–V5f |
| V5b | 银行、保险的 balance 字段（`gsmgdqsyhj`、`fzhj`、`zczj`）是否有值、单位；有无归母权益 ≤ 0 的情形（供 PB 判定）。关闭后清除行级 `verify_pending` 的 `bank_balance`、`insurance_balance` | F44、F46、F47、F48 | T-B05 | 对 000001、600000 及一家保险拉 balance 原始响应入探针 |
| V5c | 现金流字段非空率与累计口径。**字段主备已裁定（T-R12 裁定 ②，plan 2.12.1 第 1188 行（de86b99 版））**：主 `jyhdcsdxjlxj`、备 `jyhdcsdxjlje`，按分量 coalesce 并记 `basis.ocf_field`；仍待实测：两字段在多家公司、多年份的非空率，cashflow 是否累计口径（只有 600519 一家实测） | F45 | T-B05 实测 | 按 plan T-B05 ①：抽 ≥ 5 家（含银行、保险），统计两字段非空率（`'-'` 计为空），核对 `jyhdcsdxjlxj` = `jyhdxjlrxj` − `jyhdxjlcxj`、两字段同时有值时是否相等、是否累计口径 |
| V5d | capital 中 `plrq` 与 `bdrq` 相同（600519 2026-09-30 行）的含义；股本变动日与披露日的先后；**送转数据源与除权日的先后**（v1.1.2）：麦蕊是否提供分红送转数据（送转比例、除权日），送转对应的 capital 行 `plrq` 相对除权日的先后。决定 §7A.0 B2 的 `share_change_pending` 检查能否执行；若 capital 行普遍晚于除权日才可见，就必须接入送转数据（plan 2.12.1 边界第 2 条）。**属于 §7C S1 关闭项（v1.1.3）**：关闭条件为 T-B05 写出结论；若 capital 行普遍晚于除权日，送转数据已接入且切换时 `share_change_check` 不再为 `unavailable`（T-R12b 补充裁定 4；§9 问题 96） | F42、F47 | T-B05 + 研究员 | plan T-B05 ④⑧：对照巨潮一次送转（如 600519 除权日 2011-07-01）的 capital 行 `bdrq`/`plrq`。capital 行可见时间另见 V5i（v1.1.5） |
| V5e | 银行、保险的识别（`f.sw_l1` 代码格式 V9；没有申万二级特征）；也决定 `verify_pending` 的 `bank_balance`、`insurance_balance` 打在哪些证券上 | F44、F46、F47 | T-B05 + 架构师 | `/hszg` 返回中“银行”“保险”的代码 |
| V5f | 更正公告/更正后定期报告在麦蕊中如何成行（是否新增行、`plrq` 是否取更正公告日）；p11 多版本行的数值未保存 | F42–F48、§7B R4 | T-B05 | 探针保存多版本行的完整数值；选一家公开发布过差错更正的公司对照巨潮 |
| V5g | （v1.1.2；v1.1.5 按 plan 2.12.1“T-R12e 补充裁定”2 重写）`zgb` 是否包含 B 股、H 股，以及哪些公司有 B/H 股。capital 只有 `bdrq`、`plrq`、`xsltgf`、`ysltag`、`zgb`，没有区分 A/B/H 的字段（`docs/mairui-verified.md` ⑦），因此改用配置中的 A+B、A+H 公司名单识别（名单注明来源和日期，做法同 V5e 保险名单）：`basis.share_class_check`：名单接入前记 `unavailable`；接入后所有行记 `list`，名单内的公司另打 `non_a_share_capital`；将来 capital 有区分字段时记 `field`（v1.1.6，T-R12f 补充裁定 4）。不按代码段或名称推断。v1.1.8：名单放在 `config/share_class_list.yaml`（plan 2.12.1“T-R12h 补充裁定”1，7ec6fad）：文件头写 `list_version`、`as_of`、`sources`（来源和取数日期）；每条记录写 `code`、`class`（`B` 或 `H`）、`paired_code`（配对代码，交易所代码按原样记录、不加市场后缀，例如 H 股 `00939`、B 股 `900901`）、`paired_market`（取值 `HK`、`SH`、`SZ`）、`effective_from`、`effective_to`（可为空）、`source`、`verified`（布尔值）。**按生效区间取，不得前视**：计算 d 日的值时，只用 `effective_from ≤ d` 且 `effective_to` 为空或 `effective_to > d` 的记录（历史回测不会用到之后才上市的 H 股）；所用名单版本记入 `basis.share_class_list_version`。名单更新时整版替换、`list_version` 加一、不改旧行，T-B55 重算时按新版本覆盖。名单行不加可见时间字段：A+B、A+H 的对应关系在 `effective_from`（B 股或 H 股上市日）当天已公开，按生效区间取用不构成前视；重算时用最新版名单属于更正历史，不是使用未来信息；回测报告写明所用的 `share_class_list_version`（v1.1.9，plan 2.12.1“T-R12h 补充裁定”4，d500474）。`verified=false` 的记录（手工对应的 45 对；211 对与 209 对两个来源取并集后差出来的记录）照常接入，照常打 `non_a_share_capital`（plan 2.12.1“T-R12h 补充裁定”2、3）。**关闭条件（v1.1.8 起四项）**：① 名单已接入；② `zgb` 是否包含 B、H 股已用一家 A+H、一家 A+B 公司对照巨潮披露的总股本核实过；③ 名单内所有记录都 `verified=true`，核对来源是巨潮或港交所披露（plan 2.12.1“T-R12h 补充裁定”2）；④ 211 对与 209 对两个来源的差异已查明，结论写入名单的 `sources`，查明之前不关闭（plan 2.12.1“T-R12h 补充裁定”3）。核实结果：含 B/H → 清除 `non_a_share_capital`；只含 A 股 → 名单内公司 PE、PB 一律 null（`a_share_only_capital`），直到另行裁定。研究报告单列 `share_class_check = unavailable` 的证券数。**属于 §7C S1 关闭项** | F42、F43、F47、F48 | T-B05 + 架构师（名单） | plan T-B05 ⑦：A+H 例 601318 / 02318，A+B 例 000550 / 200550，对照巨潮披露的总股本（样例与出处见 `docs/mairui-verified.md` ⑦）；名单口径见 plan 2.12.1“T-R12h 补充裁定”（7ec6fad） |
| V5h | （v1.1.2）财报响应中有无币种、单位字段，字段名是什么（§7A.0 B5 `unit_mismatch` 判定依赖它）。**属于 §7C S1 关闭项（v1.1.3）**：关闭条件为确认字段名，或确认没有这类字段；没有时结论写明“只靠数量级不连续检查”（T-R12b 补充裁定 4；§9 问题 96）。关闭条件（v1.1.10，plan 2.12.1“T-R13 补充裁定”，847f41e 第 1 条）：抽样的全部财报和 capital 响应里都没有字符串值，也没有任何以币种、单位为含义的字段，即可按“确认没有这类字段”关闭；抽样范围为 income、balance、cashflow、capital 四个接口，每个接口至少覆盖 600519（普通股）、000001（银行）、601318（保险）、000550（A+B）；CDR 不在 F43、F48 的池和 S2 的池 U 内，不要求 689009 的 income、cashflow；结论写“没有币种、单位字段，只靠数量级不连续检查”，不需要字段含义的文档依据；由 T-B05 写入 `docs/mairui-verified.md` ⑨ 后 V5h 关闭（在此之前未关闭） | F42、F44、F45、F46、F47（`financial_derived` 全部 metric） | T-B05 | plan T-B05 ⑨：抽一家 CDR 或境外上市背景公司检查原始响应；抽样范围以 plan 2.12.1“T-R13 补充裁定”，847f41e 第 1 条为准 |
| V5i | （v1.1.5，plan 2.12.1“T-R12e 补充裁定”1）capital 行的 `plrq` 是否真实披露日：`plrq = bdrq` 或 `plrq` 为季末日的行可能是回填，按 `plrq` 放出会前视。核实前按 §7A.0“capital 行可见时间”保守处理（季末行取 `max(next_trading_day(plrq), first_seen_at)`；适用条件为 `bdrq` 为季末日且 `plrq = bdrq` 或 `plrq` 为季末日；首次全量回填的季末行按 `bdrq` 所属报告期的法定披露截止日 Q1 4-30、H1 8-31、Q3 10-31、年报次年 4-30，可见时间 = `max(next_trading_day(plrq), next_trading_day(截止日))` 09:30，`basis.pit_basis` 加 `capital_deadline`；v1.1.6 按 T-R12f 补充裁定 1–3 修订）。**属于 §7C S1 关闭项**：T-B05 写出结论；确认是真实披露日则取消保守规则（只改该条，不改原因码） | F42、F43、F47、F48 | T-B05 | 用 600519 等样例对照巨潮公告日，判断麦蕊是否回填 capital 行 |
| V5j | （v1.1.5，plan 2.12.1“T-R12e 补充裁定”3）CDR 的 `zgb` 按基础股份计还是按 CDR 份数计。核实前 CDR（以 `market.securities.type = cdr` 识别，与 §1.4 一致；v1.1.6 按 T-R12f 补充裁定 5 更正）的 `pe_ttm`、`pb` 照常计算，`verify_pending` 含 `cdr_unit`（只是 F42、F47 值上的标记，不涉及 S2：S2 的池 U 按 §1.4 本来不含 CDR，plan 已裁定（9ad51b8，T-R12g））；CDR 按 §1.4 本来不在 F43、F48 的分位池内（T-R12f 补充裁定 6）。**属于 §7C S1 关闭项**，清除分两种情况（plan 已裁定（9ad51b8，T-R12g））：按 CDR 份数计，总市值 = `c × zgb`，不需要配置，T-B05 确认后即清除标记；按基础股份计，总市值 = `c × zgb × 每股基础股份对应的 CDR 份数`，转换比例按证券写入配置并注明来源（招股书或上市公告），T-B05 确认、配置也接入后清除标记（T-R12f 补充裁定 7）。v1.1.10：V5j 以 689009 的实测为准关闭；`cdr_unit` **逐只清除**，不对全部 `type = cdr` 推广：只有对照过巨潮披露 CDR 份数的证券才清除，其他 CDR 保留标记；CDR 不进 S2 的池，保留的标记不阻塞切换（plan 2.12.1“T-R13 补充裁定”，847f41e 第 2 条）；判定容差（plan 2.12.1“T-R13 补充裁定”，847f41e 第 3 条）：|zgb − 披露的 CDR 份数| / 披露的 CDR 份数 ≤ 0.1% → 按 CDR 份数计；zgb 与“披露的 CDR 份数 ÷ 每股基础股份对应的 CDR 份数”相差同样不超过 0.1% → 按基础股份计；两条都不满足 → 保留 `cdr_unit` 并告警 `data_quality`；后端以后加证券级自动对照（`zgb` 与最近一期披露的 CDR 份数），通过后清除标记 | F42、F47 | T-B05（+ 架构师：仅按基础股份计时的转换比例配置） | 取 `type = cdr` 的证券（如 689009），对照巨潮披露的基础股份数与 CDR 份数 |
| V6 | 资金流大单字段名与单位 | F21 | T-B05 | `/hsstock/history/transaction` 原始响应 |
| V7 | 公告接口路径与字段 | F23 | T-B05 | **已实测（run-20261101-190106/p11 GAP5_announcement_time_precision）**：`/hsstock/announcement/{code}` 返回 `t`、`zt`、`gs`、`nr`、`jb`、`lx`；`t` 只到日（1,000 条全为纯日期），F23 的 `available_from` 一律按"只有日期 → 次一交易日开盘"；样本历史起点 2021-03 |
| V8 | 指数代码写法（沪深300、中证全指）、申万指数是否可取 | F25、F27 | T-B05 | `/hsindex/history` |
| V9 | 申万一级代码格式 | F26、F27、F34、F43、F48 | T-B05 | `/hszg/list` |
| V10 | `/hsstock/lup/limit` 字段含义 | F35–F36 对照 | T-B05 | — |
| V11 | 1 分钟 Pro 接口可用性 | F30 | T-B05 | T003 未实测 |
| V12 | 前复权价小数位 | F16–F18 | T-B05 | — |
| G1 | **缺口**：没有“不复权收盘价”正式键，G-01“价格 < 2 元”与回测中的价格水平比较无键可用 | G-01 | 研究员提、T-B43 实现 | 建议新增 `f.close_raw`（日线 `n`，不复权，P0） |
| G2 | 覆盖率门槛 0.75、组内 N ≥ 5、σ 的 n ≥ 15、fin_report 的法定披露日估计 | 多项 | 架构师确认 | 写入 `feature_catalog.pit_rule` |
| G3 | ~~缺口：L-01 卡“PB 分位 ≤ 30%”没有正式键，L-01 裁定也没有给出 PB 口径~~ **已解决（v1.1.1）**：口径见 plan 2.12.1 PB 条（6efedef 版第 1185 行，de86b99 版第 1189 行）与 `team/reports/T-R12-rulings.md` ③ | L-01 | — | 已登记 F47 `f.pb_pit`、F48 `f.pb_pit_ind_pct`（§7A）。银行、保险的 `gsmgdqsyhj` 仍待 V5b；PB 分量 `c` × `zgb` 与披露总市值的抽样核对见 plan T-B05 ⑥ |

---

## 12. 汇总表

| # | feature_key | 含义 | 来源（主口径） | 复权 | 单位 | 窗口 | 可得时点 | 优先级 | 引用 |
|---|---|---|---|---|---|---|---|---|---|
| F01 | f.amount_20d_avg | 20 日日均成交额 | 日线 a | none | CNY | 20 交易日，≥15 有效 | d 盘后→d+1 | P0 | IT2 SH1 SW1 |
| F02 | f.turnover_20d_avg | 20 日平均换手 | 因子 turnover_20d_avg | none | 待核实 | 因子定义 | d 16:30 后 | P0 | SH2 |
| F03 | f.amihud_20d | Amihud | 因子 amihud_20d | qfq/none | 1/CNY | 20 | d 16:30 后 | P0（未引用） | — |
| F04 | f.volatility_20d | 20 日波动率 | 本地日线 | qfq | ratio | 20，≥15 | d 盘后 | P0 | SH4 SW4 LG5 |
| F05 | f.intraday_amplitude_20d | 20 日平均振幅 | 本地日线 | qfq | ratio | 20，≥15 | d 盘后 | P0 | IT1 |
| F06 | f.ma_trend | MA20/MA60−1 | 本地日线 | qfq | pct | 20/60，≥15/45 | d 盘后 | P0 | SH5 SW2 |
| F07 | f.momentum_60d | 60 日动量 | 本地日线 | qfq | pct | 60，≥45 | d 盘后 | P0 | SW3 |
| F08 | f.roe_ttm | ROE TTM | 因子 roe_ttm | — | pct | TTM | d 16:30 后 | P0 | SW5 LG0B LG2；L-01 对照 |
| F09 | f.profit_cagr_3y | 3 年利润 CAGR | 因子 profit_cagr_3y | — | pct | 3 年 | d 16:30 后 | P0 | LG3 |
| F10 | f.dividend_continuous_years | 连续分红年数 | 因子（试用） | — | years | — | d 16:30 后 | P0 | LG4 L-03 |
| F11 | f.limit_up_count_20d | 20 日收盘涨停次数 | 本地 | none | count | 20，≥15 | d 盘后 | P0 | SH3 |
| F12 | f.fin_report_count | 已披露财报期数 | 报表 jzrq/plrq | — | count | 全部 | plrq 次日 09:30 | P0 | LG0 LG1 |
| F13 | f.list_days | 上市交易日数 | 主数据 list_date + 日历 | — | trading_days | — | 18:00 主数据 | P0 | HG5 HG6 G-01 |
| F14 | f.is_st | ST/*ST/退 | 主数据 risk_flag | — | bool | — | 18:00→d+1 | P0 | HG4 G-01 |
| F15 | f.is_delisting_period | 退市整理期 | 主数据 listing_status | — | bool | — | 18:00→d+1 | P0 | HG3 G-01 |
| F16 | f.close_qfq | 前复权收盘 | 日线 c(f) | qfq | CNY_per_share | — | d 盘后 | P0 | W-01 S-01 W-02 H-01 |
| F17 | f.high_qfq | 前复权最高 | 日线 h(f) | qfq | CNY_per_share | — | d 盘后 | P0 | W-01 atr |
| F18 | f.low_qfq | 前复权最低 | 日线 l(f) | qfq | CNY_per_share | — | d 盘后 | P0 | W-01 atr |
| F19 | f.amount | 成交额 | 日线 a | none | CNY | — | d 盘后 | P0 | W-01 S-01 W-02 冲击成本 |
| F20 | f.rsi14 | RSI(14) | 本地 | qfq | 指数 0–100 | warmup 28 | d 盘后 | P0 | W-01 |
| F21 | f.main_net_20d | 20 日主力净流入 | 资金流（四字段派生） | none | 待实测 | 20，≥15 | d 15:40 后 | P0 | W-01（W-03 P1） |
| F22 | f.np_yoy_latest | 最新净利同比 | 报表 | — | pct | 最新一期 | plrq 次日 09:30 | P0 | W-01（W-05 P1） |
| F23 | f.ann_risk_count_10d | 10 日风险公告数 | 公告 + 词表 | — | count | 10 交易日 | 次一交易日 09:30 | P0 | N-01 W-01 H-01 |
| F24 | f.market_breadth | 上涨家数占比 | 收盘快照 | none | ratio | 当日 | d 15:05 后 | P0 | G-02 |
| F25 | f.market_regime | 大盘状态 | 指数 + 宽度 | — | enum | MA60、2 日防抖 | d 盘后 | P0 | G-02 RC3 W-01 |
| F26 | f.sw_l1 | 申万一级 | /hszg | — | code | 周 | 周快照 | P0 | S-01 L-01（W-04 P1） |
| F27 | f.ind_rs20 | 行业相对强度 | 指数（待核实） | — | pct | 20 | d 盘后 | P0 | W-01（W-04 P1） |
| F28 | f.vwap_intraday | 日内 VWAP | 快照 cje/v 或 1m | none | CNY_per_share | 当日累计 | d 盘中 | P0 | T-01 |
| F29 | f.vwap_dev | VWAP 偏离 | 快照 | none | ratio | 当日 | d 盘中 | P0 | T-01 |
| F30 | f.intraday_sigma | 日内累计 σ | 1m | none | ratio | 当日，n≥15 | d 盘中 | P0 | T-01 |
| F31 | f.boll_bw20 | 布林带宽 | 本地 | qfq | ratio | 20 有效 K | d 盘后 | P0 | W-02 |
| F32 | f.boll_bw20_pct120 | 带宽 120 日分位 | 本地 | — | ratio | 120，≥90 | d 盘后 | P0 | W-02 |
| F33 | f.pe_ttm | PE TTM | 因子 pe_ttm | — | 倍 | TTM | d 16:30 后 | P0 | L-01 对照 |
| F34 | f.pe_ttm_ind_pct | PE 行业分位 | 本地截面 | — | ratio | 当日 | d 16:30 后 | P0 | L-01 对照 |
| F35 | f.limit_up_price | 涨停价 | 规则模块 | none | CNY_per_share | — | d 开盘前 | P0 | G-01 G5 F11 |
| F36 | f.limit_down_price | 跌停价 | 规则模块 | none | CNY_per_share | — | d 开盘前 | P0 | G5 |
| F37 | f.is_limit_up_close | 收盘涨停 | 本地 | none | bool | — | d 收盘后 | P0 | F11 H-01 |
| F38 | f.is_limit_down_close | 收盘跌停 | 本地 | none | bool | — | d 收盘后 | P0 | H-01 |
| F39 | f.limit_locked_up | 一字涨停 | 本地 | none | bool | — | d 收盘后（盘中临时） | P0 | G-01 W-01 夹具 |
| F40 | f.limit_locked_down | 一字跌停 | 本地 | none | bool | — | d 收盘后（盘中临时） | P0 | G-01 |
| F42 | f.pe_ttm_pit | PE TTM（时点自算） | 不复权 c × zgb ÷ TTM gsmgsyzzdjlr | none | 倍 | TTM | d 日线落库后；财报 next_trading_day(plrq) 09:30 | P0 | L-01 |
| F43 | f.pe_ttm_pit_ind_pct | PE（时点）行业分位 | 本地截面 | — | ratio | 当日 | 同 F42 + 行业快照 | P0 | L-01 |
| F44 | f.roe_ttm_pit | ROE TTM（时点自算） | TTM gsmgsyzzdjlr ÷ avg(gsmgdqsyhj P, P−4) | — | pct | TTM | next_trading_day(plrq) 09:30 | P0 | L-01 |
| F45 | f.ocf_to_np_ttm_pit | 经营现金流/归母净利润 | TTM coalesce(jyhdcsdxjlxj, jyhdcsdxjlje)（按分量记 basis.ocf_field）÷ TTM gsmgsyzzdjlr | — | ratio | TTM | next_trading_day(plrq) 09:30 | P0 | L-01 |
| F46 | f.debt_ratio_pit | 资产负债率（时点） | fzhj ÷ zczj；银行保险 null | — | ratio | 最新一期 | next_trading_day(plrq) 09:30 | P0 | L-01 |
| F47 | f.pb_pit | PB（时点自算） | 不复权 c × zgb ÷ T 时可见最新 gsmgdqsyhj；≤ 0 或缺失 null | none | 倍 | 最新一期（时点值） | d 日线落库后；财报 next_trading_day(plrq) 09:30 | P0 | L-01 |
| F48 | f.pb_pit_ind_pct | PB（时点）行业分位 | 本地截面 | — | ratio | 当日 | 同 F47 + 行业快照 | P0 | L-01 |
| F49 | f.is_suspended | 当日是否停牌 | 日线 sf | — | bool | 当日 | d 盘后 | P0 | G-01 W-01 H-01 |
| F50 | f.market_regime_idx | 大盘状态（指数口径，不含宽度） | 000300.SH 指数日线 | none | enum | MA60、2 日防抖 | d 盘后 | P0 | H-01 v2、W-01 v2 |
| F41 | f.excess_ret_std_60d | 60 日超额收益标准差 | 本地 | qfq | ratio | 60，≥45 | d 盘后 | P1 | validation |

**合计 50 个；P0 = 49（分类器 15 + 策略 27（含 v1.1.11 新增 F49 `f.is_suspended`、v1.1.13 新增 F50 `f.market_regime_idx`） + L-01 时点财务 7），P1 = 1。** F08、F33、F34 对 L-01 为对照用（F08 仍供分类器）。另建议新增 `f.close_raw`（G1，P0，未计入）；PB 两键 F47、F48 已于 v1.1.1 计入（G3 已解决）。

机器可读草案（供 T-B30a/T-B43 写 `feature_catalog`；`status` 一律从 `declared` 起步，T-B05 核实后再升级；字段名与表 `app.feature_catalog` 列一致）：

```yaml
feature_spec_version: "1.1.15"
rank_pct_universe: "T−1 日盘后落库截面：沪深 A 股股票，剔除北交所、停牌、上市 < 20 个交易日；平均秩 / N，取值 [0, 1]"
window_rule: {calendar: exchange_trading_days, min_valid_ratio: 0.75, null_fill: forbidden}   # 0.75 待架构师确认
all_null_when: {listing_status: [delisted, missing_from_list]}   # T-R11b：这两类证券全部 f.* 为 null
features:
  - {feature_key: f.amount_20d_avg, unit: CNY, adjust: none, frequency: daily, priority: P0, source: {provider: mairui, endpoint: "/hsstock/history/{code.市场}/d/n", field: a}, pit_rule: {window: 20, min_valid: 15, available_at: "d 日日线落库后"}}
  - {feature_key: f.turnover_20d_avg, unit: pending, adjust: none, frequency: daily, priority: P0, source: {provider: mairui, endpoint: "/factor/scale/{code}", field: turnover_20d_avg}, pit_rule: {available_at: "d 日 16:30 后", history: local_only_until_verified}}
  - {feature_key: f.amihud_20d, unit: per_CNY, adjust: qfq, frequency: daily, priority: P0, source: {provider: mairui, endpoint: "/factor/scale/{code}", field: amihud_20d}, pit_rule: {available_at: "d 日 16:30 后"}}
  - {feature_key: f.volatility_20d, unit: ratio, adjust: qfq, frequency: daily, priority: P0, derivation: "stdev(r, ddof=1) over valid bars", pit_rule: {window: 20, min_valid: 15, exclude: [ipo_first_5d, relist_day1, delisting_period_day1]}}
  - {feature_key: f.intraday_amplitude_20d, unit: ratio, adjust: qfq, frequency: daily, priority: P0, derivation: "mean((h-l)/prev_c)", pit_rule: {window: 20, min_valid: 15, exclude: [ipo_first_5d, relist_day1, delisting_period_day1]}}
  - {feature_key: f.ma_trend, unit: pct, adjust: qfq, frequency: daily, priority: P0, derivation: "(MA20/MA60-1)*100", pit_rule: {min_valid: [15, 45]}}
  - {feature_key: f.momentum_60d, unit: pct, adjust: qfq, frequency: daily, priority: P0, derivation: "(c(d*)/c(b*)-1)*100", pit_rule: {window: 60, min_valid: 45}}
  - {feature_key: f.roe_ttm, unit: pct, adjust: none, frequency: daily, priority: P0, l01_role: comparison, source: {provider: mairui, endpoint: "/factor/quality/{code}", field: roe_ttm}, pit_rule: {available_at: "d 日 16:30 后"}}
  - {feature_key: f.profit_cagr_3y, unit: pct, adjust: none, frequency: daily, priority: P0, source: {provider: mairui, endpoint: "/factor/growth/{code}", field: profit_cagr_3y}, pit_rule: {null_when: "base <= 0"}}
  - {feature_key: f.dividend_continuous_years, unit: years, adjust: none, frequency: daily, priority: P0, source: {provider: mairui, endpoint: "/factor/dividend/{code}", field: dividend_continuous_years}, pit_rule: {zero_vs_null: "0=从未分红, null=未知"}}
  - {feature_key: f.limit_up_count_20d, unit: count, adjust: none, frequency: daily, priority: P0, derivation: "count(c == limit_up_price)", pit_rule: {window: 20, min_valid: 15}}
  - {feature_key: f.fin_report_count, unit: count, adjust: none, frequency: daily, priority: P0, source: {provider: mairui, endpoint: "/hsstock/financial/income/{code}", field: [jzrq, plrq]}, pit_rule: {available_at: "next_trading_day(plrq) 09:30"}}
  - {feature_key: f.list_days, status: verified_doc, status_basis: {ruling: "plan T-A14 T-R18 裁定③（af94de3）", matrix: "T-R18_source_matrix.yaml#f.list_days", ceiling: simulating, null_when: "list_date 早于交易日历覆盖起点 → null，记 gap（insufficient_data），不估算"}, unit: trading_days, adjust: none, frequency: daily, priority: P0, source: {provider: exchange, field: list_date}}
  - {feature_key: f.is_st, unit: bool, adjust: none, frequency: daily, priority: P0, source: {provider: exchange, field: risk_flag}, pit_rule: {true_when: [st, star_st, delisting], available_at: "d 日 18:00 → d+1"}}
  - {feature_key: f.is_delisting_period, unit: bool, adjust: none, frequency: daily, priority: P0, source: {provider: exchange, field: listing_status}}
  - {feature_key: f.close_qfq, status: verified_doc, status_basis: {ruling: "plan T-A14 T-R18 裁定②（af94de3）", matrix: "T-R18_source_matrix.yaml#f.close_qfq", ceiling: simulating, pit_limit: "只用 as_of 当次取数并存快照；历史回写值不作时点依据、不用于回测", gaps: ["单位元/股为推断，待 T-B05 实测", "前复权锚点未写"]}, unit: CNY_per_share, adjust: qfq, frequency: daily, priority: P0, source: {provider: mairui, endpoint: "/hsstock/history/{code.市场}/d/f", field: c}}
  - {feature_key: f.high_qfq, status: verified_doc, status_basis: {ruling: "plan T-A14 T-R18 裁定②（af94de3）", matrix: "T-R18_source_matrix.yaml#f.high_qfq", ceiling: simulating, pit_limit: "同 f.close_qfq", gaps: ["单位元/股为推断，待 T-B05 实测", "前复权锚点未写"]}, unit: CNY_per_share, adjust: qfq, frequency: daily, priority: P0, source: {provider: mairui, endpoint: "/hsstock/history/{code.市场}/d/f", field: h}}
  - {feature_key: f.low_qfq, status: verified_doc, status_basis: {ruling: "plan T-A14 T-R18 裁定②（af94de3）", matrix: "T-R18_source_matrix.yaml#f.low_qfq", ceiling: simulating, pit_limit: "同 f.close_qfq", gaps: ["单位元/股为推断，待 T-B05 实测", "前复权锚点未写"]}, unit: CNY_per_share, adjust: qfq, frequency: daily, priority: P0, source: {provider: mairui, endpoint: "/hsstock/history/{code.市场}/d/f", field: l}}
  - {feature_key: f.amount, status: verified_doc, status_basis: {ruling: "plan「T-R19 裁定」①（78de694）", matrix: "T-R18_source_matrix.yaml#f.amount", ceiling: simulating, evidence: "T-B81 样本级实测：688018、300364 各 25 根，元单位依赖 V1 v=手；verified_live 待 T-B05 扩大覆盖"}, unit: CNY, adjust: none, frequency: daily, priority: P0, source: {provider: mairui, endpoint: "/hsstock/history/{code.市场}/d/n", field: a}}
  - {feature_key: f.rsi14, status: verified_doc, status_basis: {ruling: "plan「T-R21 裁定」①②（86d42f2）", ref: "T-R21_derived_features.md §1", ceiling: simulating, inherits: "c_qfq 为 verified_doc，限定照传"}, unit: index_0_100, adjust: qfq, frequency: daily, priority: P0, derivation: "Wilder RSI(14)；种子 = 前 14 个收益的涨、跌幅简单平均；L=0 且 G>0 → 100；G=L=0 → null", pit_rule: {warmup_bars: 28, recompute: "每个 as_of 用完整 qfq@as_of 序列从固定起点重算", seed_start: "可得序列首日（记入 pit 元数据；回测与实盘同一起点）"}}
  - {feature_key: f.main_net_20d, status: declared, status_basis: {ruling: "plan「T-R19 裁定」②（78de694）：采纳四字段派生；单位和定稿时间实测前保持 declared", matrix: "T-R18_source_matrix.yaml#f.main_net_20d"}, unit: pending, adjust: none, frequency: daily, priority: P0, source: {provider: mairui, endpoint: "/hsstock/history/transaction/{code}", field: [zmbtdcje, zmbddcje, zmstdcje, zmsddcje]}, derivation: "Σ20 有效日 (zmbtdcje + zmbddcje − zmstdcje − zmsddcje)；买为正；不得用内置 main_20d_net 替代", pit_rule: {available_at: "d 日 15:40 后（定稿时间待实测）", window: 20, min_valid: 15}}
  - {feature_key: f.np_yoy_latest, status: verified_doc, status_basis: {ruling: "plan T-A14 T-R18 裁定④（af94de3）", matrix: "T-R18_source_matrix.yaml#f.np_yoy_latest", ceiling: simulating, visible_at: "裁定原文：取 plrq（与本条 pit_rule next_trading_day(plrq) 09:30 的关系未裁定，见 §7D 歧义）", v5f_pending: "以首次观测值为准，入库带 observed_at；后续更正作为新观测，不改写旧快照，历史不能用后来的观测回推"}, unit: pct, adjust: none, frequency: quarterly, priority: P0, source: {provider: mairui, endpoint: "/hsstock/financial/income/{code}", field: gsmgsyzzdjlr}, pit_rule: {available_at: "next_trading_day(plrq) 09:30", drop_when: "plrq <= jzrq", version: latest_visible_at_T, null_when: "base <= 0"}}
  - {feature_key: f.ann_risk_count_10d, status: verified_doc, status_basis: {ruling: "plan「T-A153 裁定」：F23 词表 v3 升 verified_doc", ref: "docs/strategies/T-R62/README.md（PR #23：468ece2 + f2c8e08）", ceiling: simulating, evidence: "B 轮归档同题对照 v2.1→v3 命中 18→16（去掉的恰为 FP-1 300892 / FP-2 300598，新增 0、误伤 0）；新样本 1,367 条命中 29、FP 1/29=3.45%（95% CI [0.61%,17.18%]）、FN 0/100（CI [0%,3.70%]）；rules_freeze_v3.yaml（lexicon 8a545da8…、matcher d3e930a8…）；check_f23_v3.py PASS", limits: "不宣称 FP≤5%（区间上界 17.18%）；样本两日非连续（11-02、11-06；v4 起连续日纪律）；FP-3（300550 控制人内部协议转让）与 Q-5 扩表并入 v4；verified_live 仍需 T-A19 两项实测（新鲜度 ≥95%、完整性 10 条漏 0），N-01 KEY_DATA_MISSING 不解除"}, unit: count, adjust: none, frequency: event, priority: P0, source: {provider: mairui, endpoint: "/hsstock/announcement/{code}", field: [t, zt, nr]}, pit_rule: {window: 10, available_at: "次一交易日 09:30", null_when: "公告源缺失或过期"}}
  - {feature_key: f.market_breadth, unit: ratio, adjust: none, frequency: daily, priority: P0, source: {provider: mairui, endpoint: "/hsrl/ssjy/all", field: pc}, pit_rule: {available_at: "d 日 15:05 后"}}
  - {feature_key: f.market_regime, status: declared, status_basis: {ruling: "plan T-A14 T-R18 裁定⑤（af94de3）", matrix: "T-R18_source_matrix.yaml#f.market_regime"}, unit: enum, adjust: qfq, frequency: daily, priority: P0, derivation: "沪深300 MA20/MA60 + ma(f.market_breadth,20)，2 日防抖", pit_rule: {values: [uptrend, range, downtrend]}}
  - {feature_key: f.market_regime_idx, status: verified_doc, status_basis: {ruling: "plan「T-R19 裁定」③（78de694）", matrix: "T-R18_source_matrix.yaml#f.market_regime（T-B81 000300.SH 子项）", ceiling: simulating, gaps: ["指数日线落库时刻"]}, unit: enum, adjust: none, frequency: daily, priority: P0, source: {provider: mairui, endpoint: "/hsindex/history/000300.SH/d", field: c}, derivation: "000300.SH 收盘与 MA20/MA60；不含 F24；2 日防抖", pit_rule: {values: [uptrend, range, downtrend], window: 60, min_valid: 45, available_at: "d 日指数日线落库后"}}
  - {feature_key: f.sw_l1, unit: code, adjust: none, frequency: daily, priority: P0, source: {provider: mairui, endpoint: "/hszg/zg/{code}", field: pending}, pit_rule: {history: weekly_snapshots_from_ingest_start}}
  - {feature_key: f.ind_rs20, status: declared, status_basis: {ruling: "plan T-A14 T-R18 裁定⑤（af94de3）", matrix: "T-R18_source_matrix.yaml#f.ind_rs20"}, unit: pct, adjust: none, frequency: daily, priority: P0, source: {provider: pending, endpoint: pending, field: pending}}
  - {feature_key: f.vwap_intraday, unit: CNY_per_share, adjust: none, frequency: 1m, priority: P0, source: {provider: mairui, endpoint: "/hsstock/real/time/{code}", field: [cje, v]}}
  - {feature_key: f.vwap_dev, unit: ratio, adjust: none, frequency: 1m, priority: P0, derivation: "(p - vwap)/vwap"}
  - {feature_key: f.intraday_sigma, unit: ratio, adjust: none, frequency: 1m, priority: P0, source: {provider: mairui, endpoint: "/hsstock/pro/history/{code}/1/n", field: c}, pit_rule: {min_returns: 15}}
  - {feature_key: f.boll_bw20, unit: ratio, adjust: qfq, frequency: daily, priority: P0, derivation: "4*std_pop(c,20)/MA20"}
  - {feature_key: f.boll_bw20_pct120, unit: ratio, adjust: qfq, frequency: daily, priority: P0, derivation: "ts_pct_rank(f.boll_bw20,120)", pit_rule: {min_valid: 90}}
  - {feature_key: f.pe_ttm, unit: times, adjust: none, frequency: daily, priority: P0, l01_role: comparison, source: {provider: mairui, endpoint: "/factor/valuation/{code}", field: pe_ttm}}
  - {feature_key: f.pe_ttm_ind_pct, unit: ratio, adjust: none, frequency: daily, priority: P0, l01_role: comparison, derivation: "rank_pct_in(f.pe_ttm>0, f.sw_l1)", pit_rule: {min_group_n: 5}}
  - {feature_key: f.limit_up_price, status: verified_doc, status_basis: {ruling: "plan「T-R21 裁定」①④（86d42f2）", ref: "T-R21_derived_features.md §1", ceiling: simulating, gaps: ["送转股样本缺", "沪市除权样本缺（V2 只有 1 个深市纯现金样本）", "主板主数据上线前历史 is_st 缺 → 主板为 null"]}, unit: CNY_per_share, adjust: none, frequency: daily, priority: P0, derivation: "round_half_up(base*(1+pct),0.01)，加沪 3.3.17、深 3.3.19 边界条款；base = 日线 pc（唯一来源）；jnfh 只做交叉校验（仅限已确认的纯现金或送转、单位明示的案例）", pit_rule: {null_when: [no_price_limit_day, suspended, "main_board and is_st null", "pc missing or invalid", "pc vs jnfh cross-check conflict"]}}
  - {feature_key: f.limit_down_price, status: verified_doc, status_basis: {ruling: "plan「T-R21 裁定」①④（86d42f2）", ref: "T-R21_derived_features.md §1", ceiling: simulating, gaps: ["送转股样本缺", "沪市除权样本缺（V2 只有 1 个深市纯现金样本）", "主板主数据上线前历史 is_st 缺 → 主板为 null"]}, unit: CNY_per_share, adjust: none, frequency: daily, priority: P0, derivation: "round_half_up(base*(1-pct),0.01)，加沪 3.3.17、深 3.3.19 边界条款；base = 日线 pc（唯一来源）；jnfh 只做交叉校验（仅限已确认的纯现金或送转、单位明示的案例）", pit_rule: {null_when: [no_price_limit_day, suspended, "main_board and is_st null", "pc missing or invalid", "pc vs jnfh cross-check conflict"]}}
  - {feature_key: f.is_limit_up_close, unit: bool, adjust: none, frequency: daily, priority: P0, derivation: "c == f.limit_up_price"}
  - {feature_key: f.is_limit_down_close, unit: bool, adjust: none, frequency: daily, priority: P0, derivation: "c == f.limit_down_price"}
  - {feature_key: f.limit_locked_up, unit: bool, adjust: none, frequency: daily, priority: P0, status: verified_doc, status_basis: {ruling: "plan「T-R21 裁定」①③（86d42f2）", ref: "T-R21_derived_features.md §1", ceiling: simulating, gaps: "继承 F35 的 gaps"}, derivation: "o == h == l == c == f.limit_up_price and v > 0（不复权）；判定顺序：先查依赖，任一价、v 或涨停价为 null → null；然后 v = 0 → false；最后判断四价相等"}
  - {feature_key: f.limit_locked_down, unit: bool, adjust: none, frequency: daily, priority: P0, status: verified_doc, status_basis: {ruling: "plan「T-R21 裁定」①③（86d42f2）", ref: "T-R21_derived_features.md §1", ceiling: simulating, gaps: "继承 F36 的 gaps"}, derivation: "o == h == l == c == f.limit_down_price and v > 0（不复权）；判定顺序：先查依赖，任一价、v 或跌停价为 null → null；然后 v = 0 → false；最后判断四价相等"}
  - {feature_key: f.pe_ttm_pit, unit: times, adjust: none, frequency: daily, priority: P0, status: declared, l01_role: primary, source: {provider: mairui, endpoint: ["/hsstock/history/{code.市场}/d/n", "/hsstock/financial/capital/{code.市场}", "/hsstock/financial/income/{code.市场}"], field: [c, zgb, bdrq, plrq, jzrq, gsmgsyzzdjlr]}, derivation: "c_raw(d) * zgb(bdrq<=d and capital row visible<=d) / TTM(gsmgsyzzdjlr)", pit_rule: {available_at: "next_trading_day(plrq) 09:30", drop_when: "plrq <= jzrq", version: latest_visible_at_T, first_seen_rule: "max(plrq rule, first_seen_at); backfill rows plrq_only", ttm: "YTD(y,q)+FY(y-1)-YTD(y-1,q)", fallback_limit_months: 15, null_when: [no_valid_bar, share_change_pending, a_share_only_capital, no_visible_report, pre_listing_capital, unit_mismatch, non_positive_earnings, no_capital_row, component_missing, data_conflict], not_null_when: ["P jzrq < list_date (pe computed as usual)"], capital_visibility: {quarter_end_rows: "max(next_trading_day(plrq), first_seen_at)", applies_when: "bdrq quarter-end and (plrq == bdrq or plrq quarter-end)", backfill_quarter_end_rows: "max(next_trading_day(plrq), next_trading_day(statutory deadline of bdrq period: Q1 04-30, H1 08-31, Q3 10-31, FY next 04-30)) 09:30", backfill_pit_basis_add: capital_deadline, other_rows: "plrq rule"}, pit_basis: {type: string_array, values: [plrq_only, capital_deadline], empty_when: "no special case (empty array or omitted)"}, verify_pending: [non_a_share_capital, cdr_unit], share_class_check: {values: [unavailable, list, field], list_not_loaded: unavailable, list_loaded: list, list_source: "config A+B / A+H list (source and date)", in_list_also: "verify_pending non_a_share_capital", field_when: "capital gains a share-class field", list_file: "config/share_class_list.yaml", list_header: [list_version, as_of, sources], effective_on_d: "effective_from <= d and (effective_to is null or effective_to > d)", list_version_to: "basis.share_class_list_version", list_update: "full replacement, list_version +1, old rows unchanged; T-B55 recompute overwrites", unverified_rows: "verified=false still tagged non_a_share_capital", list_record: [code, class, paired_code, paired_market, effective_from, effective_to, source, verified], paired_code: "exchange code as-is, no market suffix (e.g. H 00939, B 900901)", paired_market: [HK, SH, SZ], visible_time_field: none, recompute_with_latest_list: "correction of history, not look-ahead", backtest_report: "state share_class_list_version used"}, cdr_unit: {identify_by: "market.securities.type = cdr", industry_pct: "not in §1.4 pool, no extra rule", s2: "not involved (U excludes CDR per §1.4)", mcap_if_zgb_in_cdr_units: "c * zgb", mcap_if_zgb_in_base_shares: "c * zgb * cdr_per_base_share", conversion_ratio: "config per security, only when zgb in base shares; source: prospectus or listing announcement", clear_when: {zgb_in_cdr_units: "T-B05 confirms (no config needed)", zgb_in_base_shares: "T-B05 confirms and ratio config loaded"}, clear_scope: "per security; uncompared CDRs keep cdr_unit, not blocking switch", tolerance: {cdr_units: "abs(zgb - disclosed_cdr_units) / disclosed_cdr_units <= 0.001", base_shares: "abs(zgb - disclosed_cdr_units / cdr_per_base_share) / (disclosed_cdr_units / cdr_per_base_share) <= 0.001", neither: "keep cdr_unit, alert data_quality"}, v5j_close_basis: "689009 measurement"}, basis_fields: [period, versions, zgb_bdrq, mcap_basis, share_change_check, share_class_check, share_class_list_version, fallback, pit_basis, null_reason, verify_pending, calc_version], mcap_basis: a_price_total_shares, store: "market.financial_derived metric=pe_ttm"}, pending: [V5d, V5g, V5h, V5i, V5j]}
  - {feature_key: f.pe_ttm_pit_ind_pct, unit: ratio, adjust: none, frequency: daily, priority: P0, status: declared, l01_role: primary, derivation: "rank_pct_in(f.pe_ttm_pit, f.sw_l1) over §1.4 pool + factor-pool exclusions", pit_rule: {min_group_n: 5, null_when: ["f.pe_ttm_pit null", "f.sw_l1 null"], verify_pending: inherit_from_f.pe_ttm_pit, null_meta: [group_too_small, input_null]}}
  - {feature_key: f.roe_ttm_pit, unit: pct, adjust: none, frequency: quarterly, priority: P0, status: declared, l01_role: primary, source: {provider: mairui, endpoint: ["/hsstock/financial/income/{code.市场}", "/hsstock/financial/balance/{code.市场}"], field: [gsmgsyzzdjlr, gsmgdqsyhj, jzrq, plrq]}, derivation: "TTM(np) / avg(E(P), E(P-4)) * 100; E(P-4) pre-listing, missing or <=0 -> E(P) only, roe_basis=single_period", pit_rule: {available_at: "next_trading_day(plrq) 09:30", drop_when: "plrq <= jzrq", version: latest_visible_at_T, first_seen_rule: "max(plrq rule, first_seen_at); backfill rows plrq_only", ttm: "YTD(y,q)+FY(y-1)-YTD(y-1,q)", fallback_limit_months: 15, null_when: [no_visible_report, pre_listing_equity, unit_mismatch, non_positive_equity, component_missing, data_conflict], keep_negative: true, single_period_reason: [p4_pre_listing, p4_missing, p4_non_positive], verify_pending: [bank_balance, insurance_balance], basis_fields: [period, versions, roe_basis, single_period_reason, fallback, pit_basis, null_reason, verify_pending, calc_version], pending: [V5b, V5e, V5h], store: "market.financial_derived metric=roe_ttm"}}
  - {feature_key: f.ocf_to_np_ttm_pit, unit: ratio, adjust: none, frequency: quarterly, priority: P0, status: declared, l01_role: primary, source: {provider: mairui, endpoint: ["/hsstock/financial/cashflow/{code.市场}", "/hsstock/financial/income/{code.市场}"], field: [jyhdcsdxjlxj, jyhdcsdxjlje, gsmgsyzzdjlr, jzrq, plrq]}, derivation: "TTM(ocf) / TTM(np), same P; each ocf YTD component = coalesce(jyhdcsdxjlxj, jyhdcsdxjlje)", field_rule: {primary: jyhdcsdxjlxj, fallback: jyhdcsdxjlje, fallback_when: "primary null or '-'", record: basis.ocf_field, both_null: "ocf_missing (no zero fill)"}, pit_rule: {available_at: "next_trading_day(plrq) 09:30", drop_when: "plrq <= jzrq", version: latest_visible_at_T, first_seen_rule: "max(plrq rule, first_seen_at); backfill rows plrq_only", ttm: "YTD(y,q)+FY(y-1)-YTD(y-1,q)", fallback_limit_months: 15, null_when: [no_visible_report, unit_mismatch, non_positive_earnings, ocf_missing, component_missing, data_conflict], basis_fields: [period, versions, ocf_field, fallback, pit_basis, null_reason, calc_version], pending: [V5c, V5h], store: "market.financial_derived metric=ocf_to_np_ttm"}}
  - {feature_key: f.debt_ratio_pit, unit: ratio, adjust: none, frequency: quarterly, priority: P0, status: declared, l01_role: primary, source: {provider: mairui, endpoint: "/hsstock/financial/balance/{code.市场}", field: [fzhj, zczj, jzrq, plrq]}, derivation: "fzhj / zczj at latest visible P", pit_rule: {available_at: "next_trading_day(plrq) 09:30", drop_when: "plrq <= jzrq", version: latest_visible_at_T, fallback_limit_months: 15, null_when: [no_visible_report, unit_mismatch, component_missing, data_conflict, financial_sector_na], component_missing_includes: ["zczj <= 0 (plus data_quality alert)"], basis_fields: [period, versions, fallback, pit_basis, null_reason, calc_version]}, pending: [V5b, V5e, V5h], store: "market.financial_derived metric=debt_ratio"}
  - {feature_key: f.pb_pit, unit: times, adjust: none, frequency: daily, priority: P0, status: declared, l01_role: primary, source: {provider: mairui, endpoint: ["/hsstock/history/{code.市场}/d/n", "/hsstock/financial/capital/{code.市场}", "/hsstock/financial/balance/{code.市场}"], field: [c, zgb, bdrq, plrq, jzrq, gsmgdqsyhj]}, derivation: "c_raw(d) * zgb(bdrq<=d and capital row visible<=d) / gsmgdqsyhj(latest visible P, point-in-time, no TTM)", pit_rule: {available_at: "next_trading_day(plrq) 09:30", drop_when: "plrq <= jzrq", version: latest_visible_at_T, restatement: no_backfill, first_seen_rule: "max(plrq rule, first_seen_at); backfill rows plrq_only", fallback_limit_months: 15, null_when: [no_valid_bar, share_change_pending, a_share_only_capital, no_visible_report, pre_listing_equity, pre_listing_capital, unit_mismatch, non_positive_equity, no_capital_row, component_missing, data_conflict], no_cap: true, outlier_display: "pb > 100 flagged, value unchanged", capital_visibility: {quarter_end_rows: "max(next_trading_day(plrq), first_seen_at)", applies_when: "bdrq quarter-end and (plrq == bdrq or plrq quarter-end)", backfill_quarter_end_rows: "max(next_trading_day(plrq), next_trading_day(statutory deadline of bdrq period: Q1 04-30, H1 08-31, Q3 10-31, FY next 04-30)) 09:30", backfill_pit_basis_add: capital_deadline, other_rows: "plrq rule"}, pit_basis: {type: string_array, values: [plrq_only, capital_deadline], empty_when: "no special case (empty array or omitted)"}, verify_pending: [bank_balance, insurance_balance, non_a_share_capital, cdr_unit], share_class_check: {values: [unavailable, list, field], list_not_loaded: unavailable, list_loaded: list, list_source: "config A+B / A+H list (source and date)", in_list_also: "verify_pending non_a_share_capital", field_when: "capital gains a share-class field", list_file: "config/share_class_list.yaml", list_header: [list_version, as_of, sources], effective_on_d: "effective_from <= d and (effective_to is null or effective_to > d)", list_version_to: "basis.share_class_list_version", list_update: "full replacement, list_version +1, old rows unchanged; T-B55 recompute overwrites", unverified_rows: "verified=false still tagged non_a_share_capital", list_record: [code, class, paired_code, paired_market, effective_from, effective_to, source, verified], paired_code: "exchange code as-is, no market suffix (e.g. H 00939, B 900901)", paired_market: [HK, SH, SZ], visible_time_field: none, recompute_with_latest_list: "correction of history, not look-ahead", backtest_report: "state share_class_list_version used"}, cdr_unit: {identify_by: "market.securities.type = cdr", industry_pct: "not in §1.4 pool, no extra rule", s2: "not involved (U excludes CDR per §1.4)", mcap_if_zgb_in_cdr_units: "c * zgb", mcap_if_zgb_in_base_shares: "c * zgb * cdr_per_base_share", conversion_ratio: "config per security, only when zgb in base shares; source: prospectus or listing announcement", clear_when: {zgb_in_cdr_units: "T-B05 confirms (no config needed)", zgb_in_base_shares: "T-B05 confirms and ratio config loaded"}, clear_scope: "per security; uncompared CDRs keep cdr_unit, not blocking switch", tolerance: {cdr_units: "abs(zgb - disclosed_cdr_units) / disclosed_cdr_units <= 0.001", base_shares: "abs(zgb - disclosed_cdr_units / cdr_per_base_share) / (disclosed_cdr_units / cdr_per_base_share) <= 0.001", neither: "keep cdr_unit, alert data_quality"}, v5j_close_basis: "689009 measurement"}, basis_fields: [period, versions, zgb_bdrq, mcap_basis, share_change_check, share_class_check, share_class_list_version, fallback, pit_basis, null_reason, verify_pending, calc_version], mcap_basis: a_price_total_shares}, pending: [V5b, V5d, V5e, V5g, V5h, V5i, V5j], store: "market.financial_derived metric=pb, per trade_date", basis_ref: "plan 2.12.1 PB + 边界情况 + 待核实标记 (de86b99) + T-R12b 补充裁定 (1c62952) + T-R12e 补充裁定 (fdd7fdd) + T-R12f 补充裁定 (38d7888) + T-R12g (9ad51b8) + T-R12h 补充裁定 (7ec6fad) + T-R12h 第 4 条 / T-R12i (d500474) + T-R13 补充裁定 (847f41e); T-R12-rulings ③, T-R12a, T-R12b"}
  - {feature_key: f.pb_pit_ind_pct, unit: ratio, adjust: none, frequency: daily, priority: P0, status: declared, l01_role: primary, derivation: "rank_pct_in(f.pb_pit, f.sw_l1) over §1.4 pool + factor-pool exclusions", pit_rule: {min_group_n: 5, null_when: ["f.pb_pit null", "f.sw_l1 null"], verify_pending: inherit_from_f.pb_pit, coverage_gate: report_only, null_meta: [group_too_small, input_null]}, basis_ref: "plan 2.12.1 PB; same as f.pe_ttm_pit_ind_pct"}
  - {feature_key: f.is_suspended, unit: bool, adjust: none, frequency: daily, priority: P0, status: verified_doc, status_basis: {ruling: "plan「T-R21 裁定」①（86d42f2）", ref: "T-R21_derived_features.md §1", ceiling: simulating, evidence: "麦蕊 hsdata 文档：sf 1 停牌，0 不停牌；本地 164 根都是 sf=0，没有观测到停牌正例", rule: "只认 sf；不得用零量或缺 K 推断停牌；null 时 G-01 KEY_DATA_MISSING 不可执行"}, source: {provider: mairui, endpoint: "/hsstock/history/{code.市场}/d/n", field: sf}, pit_rule: {available_at: "d 日日线落库后", null_when: [daily_bar_missing, sf_null, delisted, missing_from_list], classifier_null_as: true}}
  - {feature_key: f.excess_ret_std_60d, unit: ratio, adjust: qfq, frequency: daily, priority: P1, derivation: "stdev(r - r_bench)", pit_rule: {window: 60, min_valid: 45}}
```

注：`unit` 中 `pending`、`per_CNY`、`times`、`index_0_100`、`code`、`enum` 是本文建议的取值，`feature_catalog.unit` 目前没有枚举约束（`app.feature_catalog` 只约束 `adjust`、`frequency`、`status`），如架构师要约束，请以本文为初稿；`priority` 不是表的列，仅供任务拆分；`l01_role`（primary / comparison）、`pending`、`store`、`keep_negative`、`field_rule`、`basis_ref`，以及 v1.1.2 新增的 `verify_pending`、`basis_fields`、`mcap_basis`、`not_null_when`、`no_cap`、`outlier_display`、`coverage_gate`，v1.1.3 新增的 `single_period_reason`、`share_class_check_when_unidentifiable`、`null_meta`，v1.1.4 新增的 `component_missing_includes`，v1.1.5 新增的 `capital_visibility`、`share_class_check`、`cdr_unit`，v1.1.6 新增的 `pit_basis`（描述 basis 中的字符串数组）、`applies_when`、`backfill_pit_basis_add`，v1.1.8 在 `share_class_check` 内新增的 `list_file`、`list_header`、`effective_on_d`、`list_version_to`、`list_update`、`unverified_rows`，v1.1.9 新增的 `list_record`、`paired_code`、`paired_market`、`visible_time_field`、`recompute_with_latest_list`、`backtest_report`，v1.1.10 在 `cdr_unit` 内新增的 `clear_scope`、`tolerance`、`v5j_close_basis` 同样只是说明（v1.1.5 去掉 `share_class_check_when_unidentifiable`，并入 `share_class_check`；v1.1.6 去掉 v1.1.5 在 F43、F48 上加的池剔除字段，见 T-R12f 补充裁定 6；F42、F47 中这几项内容相同），不是表的列（`verify_pending`、`basis_fields`、`single_period_reason` 描述的是 `financial_derived.basis` 的内容；`null_meta` 是 T-B35 特征值元数据，不是 `null_reason`）。F42、F44–F47 的 `null_when` 自 v1.1.3 起只列 §7A.0 原因码总表中的码，**按总表优先级排序**，取值以 plan 2.12.1“T-R12b 补充裁定”1 为准（封闭）。F42–F48 的 `status` 写 `declared`，满足 §7C S1 后才升级到 `verified_live`。`f.market_regime` 的 `adjust: qfq` 指其指数均线输入。

---

## 13. 与 T-B46-47 裁定的对照/冲突

| # | 裁定 / 文档原文 | 本文做法 | 关系 | 需要谁处理 |
|---|---|---|---|---|
| A1 | R9：T-B30a 产出 15 个 `f.*` | §2 逐一给出口径，全部 P0；`f.amihud_20d` 规则未引用但仍产出 | 一致 | — |
| A2 | R9：`f.is_st = risk_flag ∈ {st, star_st, delisting}`；`f.is_delisting_period` 只看 `listing_status` | F14、F15 照抄，与 `inputs.py` 一致 | 一致 | — |
| A3 | R9：`avg_holding_days` = 365 自然日、FIFO、数量加权取整、同日 0 天、作废不计、< 3 批次 null | §10.1 同意并补 8 条 | 一致 + 补充 | 架构师把补充口径并入 T-B47 实现 |
| A4 | R9：分类器缺失键照常进 `inputs_missing`；T-B30a 之前都因 `data_missing` 封顶 | 本文所有 null 规则只会增加缺失，不会用 0 掩盖 | 一致 | — |
| C1 | R9 / plan T-R11 行：口径与 3 组样例写在 `horizon_classifier.md` **附录** | 主文写在本文件；`horizon_classifier.md` 只加附录指针 | **位置冲突（形式）** | 架构师确认以本文件为准，或研究员下一版把 §2 + §9 搬入附录 |
| C2 | plan 第 3258 / 2681 行：“`delisting` 即退市风险警示” | 本文：`delisting` = 退市整理（含“退”），退市风险警示 = `star_st` | **术语冲突**（结果不变） | 架构师改 plan 措辞；后端改 `content.py` 第 53 行 |
| C3 | `horizon_classifier.md` `rank_pct_universe`（ST 不剔除、上市 ≥ 20 日） vs plan 2.12.1 第 1161 行“因子池排除 ST/*ST、退市整理、上市不满 60 日” | 分类器沿用自身口径（§1.4）；L-01 等策略可另用因子池 | **口径冲突（已知、有意）** | 架构师在 plan 2.12.1 注明“分类器分位例外” |
| C4 | 裁定 R9：T-R11 依赖 T-B35；T-B30a 依赖 T-R11 | 本文已完成；但若干来源依赖 T-B05 实测，未核实项均标【待核实】（§11 V1–V12），主口径尽量用已实测的日线 | 依赖补充 | T-B05 核实后，T-B30a 才能把对应键从 `declared` 升级 |
| C5 | `horizon_classifier.md`：导入器拒收与 catalog 单位不一致的规则；SH5/SW2/SW3 写 `unit: sign` | 本文给 `f.ma_trend`、`f.momentum_60d` 定 `unit: pct` | **已解决（T-R11a）** | 规则改为 `unit: pct`、阈值 0；`unit: sign` 取消 |
| C6 | 分类器“20 日窗口”（交易日）vs DSL `ma(x,n)`（有效 K 线） | §1.2 明确两者不同 | 澄清 | T-B30a / T-B42 实现时区分 |
| C7 | 因子数 77（任务描述）/ 82（因子页）/ 85（plan 第 962 行） | 本文只引用在 T003 因子表中出现的 ID | **已实测：85 个**（run-20261101-190106/p11 GAP7：`factor/all` 3 只样本各 85 个，与 `factor/list` 一致；文档 `ev_ebitda` 实为 `ev_ebit`；p11 自动摘要"实返 2 个"为解析层级错误）。本文引用的因子 ID 均在其中 | 已解决 | 无（`ev_ebit` 名称差异如被引用需更正） |
| C8 | R9 未写统计维度；SH8/SW7/LG7 文本为“该股” | §10.1-1 建议按（用户, 证券） | 歧义 | 用户/架构师确认 |
| A5 | L-01 口径裁定 / plan 2.12.1 第 1178–1189 行（6efedef 版；de86b99 版为第 1182–1237 行）：版本选择、TTM、15 个月回退、pe/pb/roe/现金流比/负债率公式 | §7A F42–F48 照抄并补充：回填行只按 `plrq`、同 `available_from` 冲突处理、E(P−4) ≤ 0 视为缺失、现金流比同一 P | 一致 + 补充；**已处理**（4 条补充规则已确认并入 T-B55，plan 2.12.1 第 1186 行（de86b99 版第 1234 行）；T-R12 裁定 ④） | — |
| C9 | plan 2.12.1 原写经营现金流字段 `jyhdcsdxjlje` | F45 主字段 `jyhdcsdxjlxj`、备用 `jyhdcsdxjlje`，按分量记 `basis.ocf_field` | **已处理**：T-R12 裁定 ② 采纳同一主备规则，plan 2.12.1 第 1184 行（de86b99 版第 1188 行）与 T-B55 已改 | T-B05 实测非空率（V5c），只可能改主备顺序 |
| C10 | L-01 卡：PB 分位；L-01 裁定未给 PB 口径 | v1.1.1 登记 F47 `f.pb_pit`、F48 `f.pb_pit_ind_pct` | **已解决**（plan 2.12.1 第 1185 行，de86b99 版第 1189 行；T-R12 裁定 ③） | — |
| C11 | plan 第 829 行⑤（de86b99 版第 833 行）：线上切换时点由研究员决定 | §7C 给出 S1–S6 | 一致；**已处理**（plan L-01 行⑤已改为引用 §7C，S1–S6 阈值已确认，T-R12 裁定 ④⑤） | — |
| C12 | T-R12a 开放问题 1：§7C S2 的 PB 覆盖率门槛（v1.1.1 写为“建议，待确认”） | §7C S2 改为裁定的 D(d) 定义、全市场 99%、行业 95%（D ≥ 5）、F48 只报告 | **已裁定**（plan 2.12.1 第 1226–1233 行；T-R12-rulings.md「T-R12a」节 1） | — |
| C13 | T-R12a 开放问题 2：plan 未覆盖的 PB 边界（停牌、`zgb` 缺失、极小正权益、每股字段） | §7A.0 B1–B7 与 F42、F44、F47 边界；原因码写 `basis.null_reason` | **已裁定**（plan 2.12.1 边界情况第 1190–1212 行；T-R12-rulings.md「T-R12a」节 2）。原 2 处缺原因码已由 T-R12b 补充裁定 1 补齐：B3 → `a_share_only_capital`，B4c → `pre_listing_capital`（v1.1.3 已裁定） | — |
| C14 | T-R12a 开放问题 3：银行、保险“待核实”如何标 | 键级 `declared` + 行级 `basis.verify_pending`（`bank_balance`、`insurance_balance`、`non_a_share_capital`）；S2 分子分母同时剔除；S1 要求全部清除 | **已裁定**（plan 2.12.1 待核实标记第 1213–1225 行；T-R12-rulings.md「T-R12a」节 3） | — |
| C15 | T-R12b 的 6 个非阻塞点（v1.1.2 报告 T-R12a.md#T-R12b） | ① `null_reason` 封闭 14 码、优先级、“null ⇔ 有原因码”（§7A.0 原因码总表）；② `unit_mismatch` 兼作原因码；③ F44 P−4 早于上市 → `single_period`，`single_period_reason`；④ S1 关闭项 V5b、V5c、V5d、V5e、V5g、V5h 及 V5d、V5h 关闭条件；⑤ `unit_mismatch` 扩到 F45、F46，比值任一分量命中即 null；⑥ B/H 股无法识别记 `share_class_check = unavailable`，不推断，有 `unavailable` 则 V5g 不关闭 | **已裁定**（plan 2.12.1“T-R12b 补充裁定”第 1237–1271 行、§9 问题 96，提交 1c62952；T-R12-rulings.md「T-R12b」节），v1.1.3 落地。v1.1.3 留下的 3 点（F46 `zczj ≤ 0` 归类、`single_period_reason` 优先级、退市证券是否写 null 行）均为 plan 已裁定（b85b564，“T-R12c 补充裁定”1–3），v1.1.4 落地：`zczj ≤ 0` 并入 `component_missing` 并发 `data_quality` 告警；优先级 `p4_pre_listing` → `p4_missing` → `p4_non_positive`；退市证券不写 null 行、不新增原因码 | — |
| C16 | plan 2.12.1“T-R12e 补充裁定”（fdd7fdd，对应后端 af589c0 探针提出的 3 个口径问题） | ① capital 季末行按法定截止日保守可见（V5i，`pit_basis = capital_deadline`）；② B/H 股按配置名单识别，`share_class_check = list`，V5g 关闭条件改为“名单已接入 + A+H、A+B 各一家对照巨潮总股本”；③ CDR `verify_pending` 加 `cdr_unit`（V5j），不进 F43、F48 分位，S2 分子分母同时剔除；S1 加关 V5i、V5j | **已裁定**（plan 2.12.1“T-R12e 补充裁定”第 1276–1283 行，提交 fdd7fdd），v1.1.5 落地（§7A.0、F42、F43、F47、F48、§7C S1/S2、§11、§12）。原因码表不变（14 码；plan 写明 V5i 只改该条、不改原因码）。本文的读法与 plan 未写到的细节（季末行判定、截止日后的可见时刻、名单内公司的 `share_class_check`、`pit_basis` 单值、CDR 按基础股份计时的处理、与 §1.4 `security_type = cdr` 的关系）列在 T-R12a.md#T-R12e | 8 点已裁定，见 C17；③ 中 CDR 的 F43、F48 池剔除已由 C17 撤销，S2 剔除已由 C18 撤销 |
| C17 | T-R12e 留下的 8 个读法问题（T-R12a.md#T-R12e） | ① V5i 适用范围与截止日所属期；② 截止日的可见时刻；③ `pit_basis` 单值；④ 名单内公司的 `share_class_check`；⑤ CDR 识别与 §1.4 `type = cdr` 的冲突；⑥ CDR 与 F43、F48 分位池；⑦ `zgb` 按基础股份计时的 CDR 总市值；⑧ 银行、保险标记是否参与排序 | **已裁定**（plan 2.12.1“T-R12f 补充裁定”第 1284–1298 行，提交 38d7888），v1.1.6 落地：① `bdrq` 季末且 `plrq = bdrq` 或 `plrq` 季末才适用，截止日按 `bdrq` 所属报告期，回填季末行可见时间 `max(next_trading_day(plrq), next_trading_day(截止日))` 09:30；② `next_trading_day(截止日) 09:30`；③ `pit_basis` 改为字符串数组；④ 接入前 `unavailable`、接入后一律 `list`（名单内另打 `non_a_share_capital`），将来有字段记 `field`；⑤ 以 `market.securities.type = cdr` 识别，更正 T-R12e；⑥ F43、F48 不另设池剔除、不新增元数据原因，`cdr_unit` 只影响 F42、F47 和 S2；⑦ `c × zgb × 每股基础股份对应的 CDR 份数`，转换比例按证券配置并注明来源；⑧ 维持 T-R12a，照常排序。原因码表不变（14 码） | ⑥ 中“`cdr_unit` 影响 S2”与 ⑦ 的清除条件已由 C18 修订 |
| C18 | T-R12f 留下的 3 点（T-R12a.md#T-R12f） | ① 截止日规则是否用于增量采集的季末行；② S2 池 U 不含 CDR，`cdr_unit` 的 S2 剔除不会生效；③ CDR 按份数计时清除标记是否要等配置接入 | **已裁定**（plan 2.12.1 T-R12f 节中标为 T-R12g 的确认，提交 9ad51b8），v1.1.7 落地：① 截止日规则只用于首次全量回填的季末行，增量季末行取 `max(next_trading_day(plrq), first_seen_at)`；② 删除 `cdr_unit` 的 S2 剔除条款，`cdr_unit` 只是 F42、F47 值上的标记；③ 按份数计总市值 = `c × zgb`，不需要配置，T-B05 确认后即清除；按基础股份计需转换比例配置接入后清除。原因码表不变（14 码） | — |
| C19 | plan 2.12.1“T-R12h 补充裁定”（7ec6fad，对应后端 reports/T-R12ef-lists.md 的 3 点） | ① A+B、A+H 名单接入 `config/share_class_list.yaml`（`list_version`、`as_of`、`sources`；记录含 `code`、`class`、配对代码（v1.1.9 定名 `paired_code` + `paired_market`，见 C20）、`effective_from`、`effective_to`、`source`、`verified`），d 日只用生效区间内的记录，名单版本记 `basis.share_class_list_version`，整版替换、`list_version` 加一；② 手工对应的 45 对记 `verified=false` 接入，照常打 `non_a_share_capital`；③ 211 对与 209 对取并集，差出来的记 `verified=false` | **已裁定**，v1.1.8 落地：§7A.0 B3 与 `non_a_share_capital` 行、basis 字段说明、F42、F47、§7C S1（V5g 关闭条件加 `verified=true` 与差异查明两项）、§11 V5g、§12 YAML。原因码表不变（14 码） | 配对代码字段名与名单时点由 C20 补定 |
| C20 | T-R12h 留下的 2 点（T-R12a.md#T-R12h）：① 名单行是否需要可见时间字段；② 配对代码的字段名 | ① 名单行不加可见时间字段，A+B、A+H 对应关系在 `effective_from`（B 股或 H 股上市日）当天已公开，按生效区间取用不构成前视；重算用最新版名单属于更正历史，回测报告写明所用 `share_class_list_version`；② 配对代码定名 `paired_code`（交易所代码原样、不加市场后缀），另加 `paired_market`（`HK` / `SH` / `SZ`） | **已裁定**（plan 2.12.1“T-R12h 补充裁定”4，d500474），v1.1.9 落地：§7A.0 B3、basis 字段说明、F42、F47、§11 V5g、§12 YAML。原因码表不变（14 码） | — |
| C21 | 研究员 T-R13 报告的 3 个问题（`team/reports/T-R13.md`） | ① V5h“确认没有字段”的认定与抽样范围；② 单只 CDR 能否推广到全部 `type = cdr`；③ CDR 份数判定容差 | **已裁定**（plan 2.12.1“T-R13 补充裁定”，847f41e），v1.1.10 落地：§7A.0 B5 与 CDR 清除条件、§7C S1 ①③⑤、§11 V5h、V5j、§12 YAML `cdr_unit`。只写关闭条件，V5h、V5j 是否关闭以 T-B05 / 后端的后续交付为准。原因码表不变（14 码） | — |

---

## 版本记录

| 版本 | 日期 | 作者 | 说明 |
|---|---|---|---|
| 1.1.15 | 2026-11-11 | 研究员（T-R62） | 按 plan「T-A153 裁定」：F23 `f.ann_risk_count_10d` 升为 verified_doc（词表 v3 冻结 + B 轮归档同题对照 18→16 + 新样本 1,367 条：命中 29、FP 3.45%、CI [0.61%,17.18%]、FN 0/100）；§3 F23、§7D 表、§12 YAML 同步；只到 simulating，不宣称 FP≤5%；FP-3（300550）与 Q-5 扩表并入 v4，样本两日非连续经裁定接受、v4 起连续日纪律；verified_live 仍需 T-A19 两项实测，N-01 KEY_DATA_MISSING 不解除；键数不变 |
| 1.1.14 | 2026-11-07 | 研究员（T-R21） | 按 plan「T-R21 裁定」①–④（86d42f2）：6 个键（F20、F35、F36、F39、F40、F49）改为 verified_doc，并改写正文和 YAML（基准价只用 pc，jnfh 只做交叉校验，pc 缺失或冲突时为 null；一字板先查依赖为 null，再判 v=0；sf 唯一来源；四价一字；RSI 全平盘 null、固定起点重算；主板历史 ST 缺口 null）；只改文档 |
| 1.1.13 | 2026-11-07 | 研究员（T-R20） | 按 plan「T-R19 裁定」①–④（78de694）：amount 升为 verified_doc；main_net_20d 写明四字段派生公式（单位和定稿时间待实测，仍为 declared）；新增 F50 market_regime_idx（§2、§12 汇总表、YAML、§7D，合计 50 个，P0 49）；只改文档 |
| 1.1.12 | 2026-11-07 | 研究员（T-R18） | 按 plan T-A14「T-R18 裁定」①–⑤（af94de3）新增 §7D；YAML 中 9 键加 `status`/`status_basis`：F16–F18、F13、F22 改为 verified_doc（上限 simulating，附限定），F19、F21、F25、F27 保持 declared；引用 `T-R18_source_matrix.yaml`；只改文档 |
| 1.1.11 | 2026-11-07 | 研究员（T-R15） | 新增 F49 `f.is_suspended`（§2 F15 前、§12 汇总表、YAML、合计 49 / P0 48），依据 plan 2.5.14 T-R15 第 7 条（f12ef24）；只改文档 |
| 1.1.10 | 2026-11-07 | 研究员（T-R13） | 落地 plan 2.12.1“T-R13 补充裁定”，847f41e 第 1–3 条：V5h 可按“确认没有币种、单位字段”关闭的条件与抽样范围（四接口 × 600519/000001/601318/000550，不要求 689009 的 income、cashflow），写入 B5、§7C S1 ③、§11 V5h；`cdr_unit` 逐只清除、V5j 以 689009 的实测为准关闭、CDR 份数容差 0.1%、两条都不满足时保留标记并告警 `data_quality`，写入 §7A.0、§7C S1 ①⑤、§11 V5j 与 YAML `cdr_unit`（`clear_scope`、`tolerance`、`v5j_close_basis`）；YAML 版本 1.1.10；§13 新增 C21。只写条件，不记为已实测关闭。原因码仍 14 个；键数不变（48 个，P0 47 个） |
| 1.1.9 | 2026-11-01 | 研究员（T-R12i） | 落地 plan 2.12.1“T-R12h 补充裁定”4，d500474：§7A.0 B3 与 §11 V5g 的名单记录字段把“配对代码”换成 `paired_code`（交易所原代码、不加后缀）与 `paired_market`（`HK` / `SH` / `SZ`），并写明名单行不加可见时间字段、重算用最新版名单属于更正、回测报告写明 `share_class_list_version`；basis 字段说明与 F42、F47 同步；YAML `share_class_check` 加 `list_record`、`paired_code`、`paired_market` 等说明字段，版本 1.1.9；§13 C19 注明由 C20 补定、新增 C20。原因码仍 14 个；键数不变（48 个，P0 47 个） |
| 1.1.8 | 2026-11-01 | 研究员（T-R12h） | 落地 plan 2.12.1“T-R12h 补充裁定”（7ec6fad）：§7A.0 B3 与 `non_a_share_capital` 行写入名单文件、字段、生效区间取用规则（`effective_from ≤ d` 且 `effective_to` 为空或 `> d`）、整版替换与 `verified=false` 照常打标；basis 新增 `share_class_list_version`（basis 字段说明、F42、F47、YAML `basis_fields`）；§7C S1 与 §11 V5g 关闭条件加“名单内所有记录 `verified=true`（巨潮或港交所披露）”与“211/209 差异已查明并写入 `sources`”；YAML `share_class_check` 补名单说明字段，版本 1.1.8；§13 新增 C19。原因码仍 14 个；键数不变（48 个，P0 47 个） |
| 1.1.7 | 2026-11-01 | 研究员（T-R12g） | 落地 plan 2.12.1 T-R12f 节中标为 T-R12g 的三点确认（9ad51b8）：§7A.0 V5i 节注明截止日规则只用于首次全量回填的季末行、增量季末行取 `max(next_trading_day(plrq), first_seen_at)`；删除 `cdr_unit` 的 S2 剔除条款（§7A.0 待核实标记说明、F42、F47、§7C S2 总则与计数、§11 V5j、YAML `cdr_unit.s2`）；CDR 清除条件在 §7A.0、§7C S1 ⑤、§11 V5j、YAML 中分按份数计（确认即清除）与按基础股份计（另需转换比例配置）两种情况；§12 YAML 版本 1.1.7；§13 C17 注明由 C18 修订、新增 C18。原因码仍 14 个；键数不变（48 个，P0 47 个） |
| 1.1.6 | 2026-11-01 | 研究员（T-R12f） | 落地 plan 2.12.1“T-R12f 补充裁定”（38d7888）8 点：§7A.0 V5i 节改适用条件写法、截止日按 `bdrq` 所属报告期、回填季末行可见时间取 `max(next_trading_day(plrq), next_trading_day(截止日))` 09:30；`basis.pit_basis` 改为字符串数组（可同时含 `plrq_only`、`capital_deadline`）；B3、`non_a_share_capital` 行、F42、F47、§11 V5g 的 `share_class_check` 改为 `unavailable` / `list` / `field`；`cdr_unit` 以 `market.securities.type = cdr` 识别，删去 v1.1.5 的 CDR 名单写法；F43、F48 删去 CDR 池剔除条目及 YAML 对应字段，`cdr_unit` 只影响 F42、F47 与 S2；新增 CDR 总市值换算（按基础股份计乘转换比例，配置按证券注明来源）与清除条件，§7C S1 ⑤、§11 V5j 同步；F48 注明银行、保险标记照常排序；§12 YAML 版本 1.1.6；§13 C16 后续改指 C17、新增 C17。原因码仍 14 个；键数不变（48 个，P0 47 个） |
| 1.1.5 | 2026-11-01 | 研究员（T-R12e） | 落地 plan 2.12.1“T-R12e 补充裁定”（fdd7fdd）：§7A.0 新增“capital 行可见时间”（季末行 `max(next_trading_day(plrq), first_seen_at)`，回填季末行按法定截止日并记 `pit_basis = capital_deadline`），B2、F42、F47 的 `zgb` 取法改为“可见时间 ≤ d”；B/H 股改为按配置名单识别，新增 `share_class_check = list`（F42、F47、B3、待核实标记表）；`verify_pending` 加 `cdr_unit`（F42、F47），F43、F48 池剔除、S2 分子分母剔除；§7C S1 加 V5i、V5j 并重写 V5g 关闭条件，S2 总则注明 `cdr_unit`；§11 新增 V5i、V5j，重写 V5g；§12 YAML 同步 F42、F43、F47、F48；§13 新增 C16。原因码仍为 14 个，键数不变（48 个，P0 47 个） |
| 1.1.4 | 2026-11-01 | 研究员（T-R12d） | 落地 plan 2.12.1“T-R12c 补充裁定”（b85b564）：F46 `zczj ≤ 0` 并入 `component_missing`，注明 T-B55 发 `data_quality` 告警，YAML 中该项改记于 `component_missing_includes`；`single_period_reason` 优先级标注改为 plan 已裁定；§7A.0 原因码总表注与 F47 改写退市证券（不补写 null 行、不新增原因码，`pe_ttm`、`pb` 只在有日线的交易日写行，退市前历史行照常计算）；§13 C15 改为全部已裁定。原因码仍为 14 个，键数不变（48 个，P0 47 个） |
| 1.1.3 | 2026-11-01 | 研究员（T-R12c） | 落地 plan 2.12.1“T-R12b 补充裁定”（1c62952）：§7A.0 新增原因码总表（封闭 14 码、表序即优先级、`value` 为 null ⇔ 写 `null_reason`，分位键原因 `group_too_small` / `input_null` 归 T-B35 元数据），B3 → `a_share_only_capital`、B4c → `pre_listing_capital`，原无码情形补 `non_positive_earnings`、`non_positive_equity`、`no_capital_row`、`data_conflict`；B5 `unit_mismatch` 扩到 F45、F46，比值任一分量（含 TTM 任一期）命中即 null；F44 新增 `single_period_reason`（`p4_pre_listing` / `p4_missing` / `p4_non_positive`），P−4 早于上市按缺失处理；F42、F47 新增 `share_class_check = unavailable`；F45 新增 `ocf_missing`、`non_positive_earnings`；F46 新增 `financial_sector_na`、`component_missing`；§7C S1 关闭项改为 V5b、V5c、V5d、V5e、V5g、V5h 并写 V5d、V5h 关闭条件（§9 问题 96）；§11 V5d、V5h 标为 S1 关闭项，V5g 加“有 unavailable 不算关闭”；§12 YAML 版本 1.1.3，`null_when` 改为原因码；§13 C13 改已裁定、新增 C15。键数不变（48 个，P0 47 个） |
| 1.1.2 | 2026-11-01 | 研究员（T-R12b） | 落地 plan 2.12.1 T-R12a 裁定（de86b99）：§7A.0 新增“边界情况与原因码”B1–B7（`no_valid_bar`、`share_change_pending`、`no_visible_report`、`pre_listing_equity`、`unit_mismatch`；`share_change_check`、`mcap_basis = a_price_total_shares`）与“待核实标记 `basis.verify_pending`”（`bank_balance`、`insurance_balance`、`non_a_share_capital`）；F42、F44、F47 边界与 basis 同步，F43、F48 继承 `verify_pending`；F47 的极值不截断、不用每股字段改为“plan 已裁定”；§7C S1 写明切换时所有 `verify_pending` 已清除（加 V5g），S2 写入 PB 覆盖率裁定并规定所有键同时剔除 `verify_pending`；§11 V5d 补送转数据源与除权日先后，新增 V5g（B/H 股股本）、V5h（币种单位字段）；§12 YAML 版本 1.1.2，F42–F44、F47、F48 同步；§13 新增 C12–C14（已裁定）；本版引用的 plan 行号改为 de86b99 版。键数不变（48 个，P0 47 个） |
| 1.1.1 | 2026-11-01 | 研究员（T-R12a） | 按 plan 2.12.1 PB 条与 T-R12 裁定 ③ 新增 §7A F47 `f.pb_pit`、F48 `f.pb_pit_ind_pct`（合计 48 个、P0 47 个）；按 T-R12 裁定 ② 把 F45、§7A.0、C3、V5c 的经营现金流字段改为主 `jyhdcsdxjlxj`、备 `jyhdcsdxjlje`（按分量记 `basis.ocf_field`，都空为缺失）；§7C S1/S5 键范围改为 F42–F48，S2 增补 PB 覆盖率建议值（待确认）；§11 G3、§13 C10 关闭，A5、C9、C11 标已处理；YAML 版本 1.1.1 |
| 1.1.0 | 2026-11-01 | 研究员（T-R12） | 新增 §7A：L-01 时点财务键 F42 `f.pe_ttm_pit`、F43 `f.pe_ttm_pit_ind_pct`、F44 `f.roe_ttm_pit`、F45 `f.ocf_to_np_ttm_pit`、F46 `f.debt_ratio_pit`（合计 46）；新增 §7B：plrq 多版本含义（巨潮 5 个样本 + 2 处数值核对）与 R1–R7；新增 §7C：线上切换条件 S1–S6；F08/F33/F34 对 L-01 降为对照用；F12/F22 补占位行与字段名；§11 V5 改为部分实测，新增 V5b–V5f、G3；§13 新增 A5、C9–C11 |
| 1.0.2 | 2026-11-01 | 研究员（T003 GAP） | 依据 run-20261101-190106/p11：V1 已实测（GAP2）、V4 部分实测（GAP6）、V7 已实测（GAP5）；§13 C7 因子数定为 85（GAP7）。其余 V 项未动 |
| 1.0.1 | 2026-11-01 | 研究员（T-R11a/b） | C5：SH5/SW2/SW3 改 `unit: pct`；§10.2 第 4 条已定：`delisted`/`missing_from_list` 全部 `f.*` 为 null（F15 边界与 §1 同步）；V1–V12 待 T-B05 实测后补 |
| 1.0 | 2026-11-01 | 研究员（T-R11） | 首版：41 个正式键（P0 40、P1 1）口径、3 组手算样例、问题 76/77 复核、与 T-B46-47 裁定对照；`horizon_classifier.md` 末尾加附录指针 |
