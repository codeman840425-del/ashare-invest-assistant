# T-R21 H-01/W-01 v2 declared 键全依赖与派生升级路径（策略研究员，2026-11-07）

> **只是提案，待架构师一次裁定**：本文不改任何状态，不豁免 G2（遵守 e3daf66「T-R20 裁定」②）。没有调用麦蕊或 DeepSeek，没有读取凭证。本地证据只做只读复用。边界例检查见 `T-R21/check_T-R21.py`（数值全部虚构，20/20 PASS）。

## 0. 依赖图（卡片 data_needs/rules + 系统组件 + 派生输入，一次性列全）
| 键（F 号） | 状态 | H-01 v2 | W-01 v2 | 依赖路径 |
|---|---|---|---|---|
| f.is_suspended（F49） | declared | 直接 | 直接 | 卡片 data_needs；G-01 `SUSPENDED`（买卖两个方向） |
| f.limit_down_price（F36） | declared | 直接 | 直接 | 卡片；止损截断；F40 的输入 |
| f.limit_locked_down（F40） | declared | 直接 | — | H-01 卖出方向 `LIMIT_LOCKED` |
| f.limit_up_price（F35） | declared | — | 直接 | 卡片；G-01 一字涨停；F39 的输入 |
| f.limit_locked_up（F39） | declared | — | 直接 | G-01 `LIMIT_LOCKED`（买入方向） |
| f.rsi14（F20） | declared | — | 直接 | W-01 V4 |
| f.main_net_20d（F21） | declared | — | 直接 | W-01 A1/C2（T-R19②，等周一实测） |
| f.is_st（F14） | declared | 间接 | 间接 | G-01 `ST_OR_DELISTING`（W）；主板涨跌停比例的输入（H/W 的 F35/F36） |
| f.is_delisting_period（F15） | declared | 间接 | 间接 | G-01（W）；退市整理期首日无涨跌幅 → F35/F36 为 null |
| f.ann_risk_count_10d（F23） | declared | — | 间接 | N-01 挂在带买入动作的模板上（W）；**N-01 要求公告源为 verified_live** 才解除 `KEY_DATA_MISSING` |
| f.market_regime（F25） | declared | （非卡片） | （非卡片） | G-02 仍产出它，供 RC3 使用；v2 卡已经改用 F50，**不算卡片的 G2 依赖** |

计数：H-01 共 **5** 个（直接 3 + 间接 2）；W-01 共 **9** 个（直接 6 + 间接 3）；合计去重 **10** 个（不含 F25）。已是 verified_doc 的输入：close/high/low_qfq、amount、list_days、np_yoy_latest、F50。非特征输入：日线原始字段 o/h/l/c/v/pc/sf、证券板块、risk_flag 历史、listing_status、交易日历、`config/market_rules.yaml`（已核实条款）。另外，`config/engine_policy.yaml` 仍固定 `hold_risk_monitor version_no: 1`，v2 导入需要架构师或后端改 config（本角色不改）。

## 1. 逐键路径
**F35/F36 涨跌停价**：`round_half_up(基准价 × (1 ± 比例), 0.01)` 加沪 3.3.17、深 3.3.19 的边界条款；**基准价 = 交易所前收盘价，除权除息日用除权（息）参考价**，不能直接用上一日收盘价。比例按 d 日所在的 market_rules 生效段：主板 10%；主板 ST/*ST 在 2026-07-06 前为 5%、之后为 10%；**创业板和科创板（含风险警示）20%**；北交所 30%（不扫描）。注册制新股前 5 日、重新上市首日、退市整理期首日无涨跌幅限制 → null；停牌日 → null；主板且 is_st 为 null → null（不猜比例）。不复权，单位 CNY_per_share。证据：麦蕊文档 pc =“前收盘价”。本地 run-20261107-130324/p13_fin_pit：000001 在 2026-09-24（jnfh 的 cdate，每 10 股派 2.49）当日的 pc，等于前一日收盘价减去每股红利、舍入到分，**这是 1 个深市纯现金分红样本**；601318 在 2026-09-10 的 pc 也不等于前一日收盘，但没有对应分红数据，所以不作为证据。T-B81 的 50 根和 p13 的 114 根里，其余的 pc 都等于前一日收盘。**路径**：采用“pc 优先，pc 缺失时用 jnfh 自算参考价并交叉校验”，可升 verified_doc；送转股、沪市和配股样本仍缺（V2 部分）。最少实测（估计）：沪市有现金分红的 1 只加有送转的 1 只，每只取除权日前后的日线 1 次，加 jnfh 1 次 ≈ 4 次；如果复用 p13 已有的 600519 jnfh（2026-06-25 除权）则 600519 只需补日线 1 次，所以估计为 2–4 次。

**F39/F40 一字涨/跌停**：用不复权日线，`o == h == l == c == 涨停价` 且 `v > 0`（跌停时四价都等于跌停价）。涨跌停价为 null、任一价缺失、停牌 → null；v = 0 → false（不当作一字）。**收盘触及涨停不等于全天一字**：本地 300364 在 2026-10-09 收盘等于按 pc×1.2 估算的涨停价，但四价不相等（虚构例同样在 check 中）。现行 spec 写的是 `o == l == 涨停价`，在 h ≤ 涨停价时与四价相等等价，建议改成四价写法以便校验。盘中用快照判断的临时值不落库。依赖 F35/F36，状态最多与它们相同，可升 verified_doc；实测不需要额外调用（复用涨跌停样本的日线）。

**F49 停牌**：麦蕊文档写明 `sf`：“1 停牌，0 不停牌”。本地 164 根日线全部是 sf = 0，**没有观测到 sf = 1 的正例**；文档也没说明停牌日是返回 sf = 1 的行还是不返回行。规则：sf = 1 → true；sf = 0 → false；行缺失或 sf 为空 → **null**（可能是数据缺失、未上市、退市或数据源故障），按保守处理为“不可执行”（G-01 用 `KEY_DATA_MISSING`），**不能凭成交量为 0 或缺 K 线断定停牌**。可凭文档升 verified_doc。最少实测（估计）：从交易所停复牌公告挑 1 只已确认停牌的股票，取停牌期前后的日线 1 次（加 1 只对照）≈ 1–2 次。

**F20 RSI14**：输入为 c_qfq@as_of 的有效日 K（停牌日跳过）。Wilder：种子 = 前 14 个收益的涨幅、跌幅分别取简单平均；之后 `avg = (avg×13 + x)/14`；RSI = 100 − 100/(1 + G/L)。L = 0 且 G > 0 → 100；**G = L = 0（全平盘）待裁定**（建议 50，可选 null）；有效 K 少于 28 → null；取 2 位小数。**qfq 每个 as_of 都会改写历史价差，所以必须在每个 as_of 用完整序列从同一起点（上市首日或可得序列首日）重新计算**，不能沿用旧快照递推（check 的反例已验证）。起点不同会造成差异，回测和实盘必须用同一起点。输入是 verified_doc，因此**最多到 verified_doc**，不会自动成为 verified_live。可凭文档和本地算术升级，不需要调用；麦蕊因子 rsi_14 只作对照（V3）。

**F14 is_st / F15 is_delisting_period**：来源是交易所主数据 risk_flag 和 listing_status（security_master §5），历史取 `security_risk_flag_history`；沪市和北交所没有官方历史，只能从上线日起每日做差分（T007）。null 时：is_st 按 true（保守），is_delisting_period 由 G-01 按缺失处理。路径：证券主数据接入并有历史区间（valid_from/valid_to）后可升 verified_doc；**上线日之前的历史 ST 区间没有来源**，回测中主板 ST 的涨跌停比例要么为 null，要么由架构师裁定接受这个缺口。不需要麦蕊调用（交易所公开列表由后端主数据任务负责）。

**F23 ann_risk_count_10d**：V7 已实测接口字段，t 只到日 → 次一交易日开盘可见。缺口：`event_definitions` 关键词表的版本还没有落地；N-01 要求 verified_live。路径：关键词表 v1 由研究员起草、架构师裁定后可升 verified_doc；verified_live 需要后端按新鲜度实测（复用 V7 的 1,000 条样本，可能 0 次调用）。在此之前，W-01 的买入草案按设计被 `KEY_DATA_MISSING` 阻断。

**F21 main_net_20d**：维持 T-R19②；周一后端覆盖测试（同一只股在 d 日 15:40 后与 d+1 各 1 次，共 2k 次，k 待定）。

## 2. 分类
- 可凭文档 + 本地确定性检查升 verified_doc（待裁定）：F20、F35、F36、F39、F40、F49（6 个；F35/F36 带“送转/沪市样本缺”的限定，限定向下传递到 F39/F40）。
- 依赖主数据或词表落地：F14、F15、F23。
- 必须实测：F21（单位、定稿时间）；verified_live 全部要等 T-B05。
- 最少新调用合计（估计，不保证精确）：F35/F36 2–4 次 + F49 1–2 次 + F21 2k 次；F39/F40、F20 为 0 次。

## 3. 待架构师一次裁定
1. 是否接受上述 6 个键升 verified_doc，以及各自的限定。
2. RSI 全平盘取 50 还是 null；是否接受“每个 as_of 全序列重算，固定起点”。
3. F39/F40 改为四价相等的写法（spec 补丁）。
4. 主板历史 ST 缺口在回测中按 null 处理，还是接受这个缺口。
5. F23 关键词表 v1 的起草授权。
6. engine_policy 中 H-01 的 version_no 改为 2 由谁执行。
