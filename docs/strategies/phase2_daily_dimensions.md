# Phase 2 每日六维事实映射（P2N-01）

状态：文档交付，非功能上线/来源晋级/生产验收。依据 `../plan-phase2-next.md` P2N-01（派单基线264f570）、`../api-contract.md` §1.1/§5.3/§7.11.1、`feature_spec.md` v1.1.14 §7D/§12。后续实现由 P2N-04 消费，测试角色另建指定测试；本文不修改 H/W 动作、G2/N-01 或 T-R23 冻结规则。

## 1. 快照与输出约束

- 每个新生成的非 removed `DailyReport.stocks[]` 恰好六组，顺序 technical、capital、fundamental、sentiment、sector_market、news；旧日报/removed 行 `dimensions=null`，不回写历史正文。新输入产生新 revision，`analysis_snapshot_id` 指向生成时本人不可变快照。
- 每组沿契约 `DailyDimensionAnalysis`：`dimension/facts/feature_refs/data_status/data_as_of/gaps`。facts 为 TextWithEvidence，证据引用本日报顶层 evidence，同股代码前缀遵循 §5.3；不得悬空。feature_refs 的 feature_key/status/evidence_ids 不另造字段；未登记键 status=null，不虚构 f.*。
- Evidence 沿契约 id/key/value/unit/provider/endpoint/data_as_of/fetched_at/epistemic_type。字段等级与取数完整性分开；verified_doc 最多 simulating，不能用数值存在或两股样本改成 verified_live。表中“declared”含计划明确保留项；“null（等级未明）”指已有键但规格未明确其等级，不当 verified_doc。
- 未知指标 Evidence.value=null、unit 无证据则 null，并带 gap；完全无来源 facts=[]、data_status=unavailable、data_as_of=null。部分缺失 partial；stale/pending 沿 §1.1，不能静默前值、插值、0、range 或 neutral 补齐。真实零值仅在输入完整、口径可复算时允许。
- gaps.reason 只用契约 no_source/not_yet_published/upstream_error/quota_deferred/user_input_missing/data_licence_unavailable/not_applicable。单位/PIT/版本冲突等细节写 message，内部 null_reason/verify_pending 不新增成 API reason。上游失败用 upstream_error；来源/单位无证用 no_source；尚未可见用 not_yet_published；不适用用 not_applicable。
- 六维是事实覆盖，不是六个策略结论。规则观点仍来自实际启用策略的 dimension_matrix；同股不同卡观点并列，不合并动作、不生成综合分数/中性结论、不改变置信度公式。一个维度失败不阻断整份日报，顶层汇总 gaps。

## 2. 时间与单位词典

所有时间为北京时间 Asia/Shanghai（UTC+8），T 为求值时刻、d 为基准交易日。known_at 是“已知且可使用时点”的语义，不是本任务新增 API 字段；data_as_of 是数据时点、fetched_at 是取得时点，二者不能互代 PIT。源记录 available_at/available_from、first_seen_at/observed_at、版本与时区保留在既有来源快照/证据关联中；若无法追溯，值 null + gap，而不是凭日报生成时间倒推已知。

| 代号 | 可见性与窗口规则 |
|---|---|
| D | 日线完成且实际落库后才可用；spec §1.1 的约17:00不能取代T-R18文档≥17:10更新完成限定及实际入库证据。d日盘中不读d日日线。有效K无插值，qfq只用qfq@as_of当次快照；历史回写不能当历史PIT证据。 |
| F | 财报取 next_trading_day(plrq) 09:30 与 first_seen_at/observed_at 的较晚者；仅选T时可见版本，丢弃plrq≤jzrq占位行。F22按§7D首次观测/更正新观测，不回写旧快照；财务自算各分量同样可见，保留report_period/jzrq、plrq、版本、basis。 |
| V | F42/F47还需d日有效不复权日线与可见capital；bdrq≤d、股本披露可见。季末可疑行及首次回填沿spec §7A.0/V5i法定截止日规则，记capital_deadline；非季末行沿原plrq规则。最终可用时点为全部必需输入可见/落库时点的最大值。 |
| S | 行业从落库起保存周快照，快照之前为null；不以今日归属回填历史。主数据F14/F15为d日18:00快照d+1可见，首快照前/失败日null。 |
| N | 公告沿T-R22 README §2.7–8及T-R23现行冻结：分别规整t与first_seen_at，再取已知者的max；交易日盘前<09:30当日09:30，否则（含恰09:30、盘中、只有日期、非交易日）次交易日09:30。F23冻结D09:30，as_of早于该时刻null；只计生效日在[D−9,D]且≤D09:30的可见公告。只知t标PIT局限，不伪造首次观测。 |

单位：CNY=元；CNY_per_share=元/股；pct 中12=12%；ratio中0.12=12%；times=倍；count=次数；bool/code/enum按类型展示；RSI是0–100指数，不是收益百分比。虚构schema单位不是证据。F16–18元/股仍带“推断待核实”gap；F19单位按既有样本限定，不能推广全源；F21单位未知不换算。表中单位均由对应spec条目复核。

## 3. 六维最小事实组

以下表列 feature_refs；表达式/非feature展示项在各组补充中说明，不冒充正式键。每行规格定位均为 `feature_spec.md` 对应F编号；来源端点/字段引自该条及 `T-R18_source_matrix.yaml`，不表示已实调。

### technical

| feature_key | spec | unit | status | 窗口/PIT | 来源字段；缺失与边界 |
|---|---|---|---|---|---|
| f.close_qfq | F16 | CNY_per_share | verified_doc | 当日/D | 日线d/f:c；停牌无行、伪停牌null；单位推断与qfq锚点gap。 |
| f.high_qfq | F17 | CNY_per_share | verified_doc | 当日/D | 日线d/f:h；同F16，不能拿来比较不复权成本。 |
| f.low_qfq | F18 | CNY_per_share | verified_doc | 当日/D | 日线d/f:l；同F16。 |
| f.rsi14 | F20 | index_0_100 | verified_doc | Wilder14、预热28有效K/D | 本地close_qfq派生；全平盘null，不填50；每as_of固定起点全序列重算并留起点。 |

补充：MA20/MA60、atr(14) 是已有DSL表达式，不新增 f.ma/f.atr_pct 正式键。MA单位同价、窗口为最近N根有效K；ATR Wilder首14个TR均值、需15根，输入F16–18；缺输入/预热不足null。H-01 v2整体预热62有效K，W-01 v2默认65、参数上限139；对应规则passed=null/insufficient_data沿卡，不偷换为通过。展示已有规则id、表达式、passed、证据，不重算新动作；H-01成本价qfq@T与计划不复权止损分开，参见两卡“时点/单位/复权/预热”。

### capital

| feature_key | spec | unit | status | 窗口/PIT | 来源字段；缺失与边界 |
|---|---|---|---|---|---|
| f.amount | F19 | CNY | verified_doc | 当日；ma表达式20有效K/D | 日线d/n:a；停牌无行，不当0；T-B81仅两股25根样本，仍非verified_live。 |
| f.main_net_20d | F21 | null | declared | 20交易日、有效≥15；定稿时刻未证 | transaction四字段zmbtdcje+zmbddcje−zmstdcje−zmsddcje；某有成交日资金缺失则整体null。单位/大单阈值/定稿未闭合，不把15:40当已证明可见；不采用内置main_20d_net替代。 |

当日资金流：四字段单日算式仅作待办，未登记独立feature_key，当前不造正式引用/不输出可比金额；unit=null、value=null + gap。F01 amount_20d_avg是20交易日窗，与ma(f.amount,20)的20有效K不等价，本最小组不另引F01。成交额事实置本组不改变W-01的technical过滤/反证归属。

### fundamental

| feature_key | spec | unit | status | 窗口/PIT | 来源字段；缺失与边界 |
|---|---|---|---|---|---|
| f.np_yoy_latest | F22 | pct | verified_doc | 最新可见累计期同比/F | income:gsmgsyzzdjlr、jzrq、plrq；同比基期≤0/缺失null；更正不可回流。 |
| f.pe_ttm_pit | F42 | times | declared | TTM，回退≤15个月/F+V | 不复权c×zgb÷TTM归母净利；净利≤0、无效日线/股本、单位冲突null。 |
| f.roe_ttm_pit | F44 | pct | declared | TTM与P/P−4权益/F | gsmgsyzzdjlr、gsmgdqsyhj；P−4缺失/非正/上市前按既有single_period并记原因，P权益≤0 null，负利润ROE保留负值。 |
| f.ocf_to_np_ttm_pit | F45 | ratio | declared | 同P的TTM/F | 逐YTD分量主jyhdcsdxjlxj备jyhdcsdxjlje，basis.ocf_field留实际字段；两者都空null，净利≤0 null，不独立回退现金流。 |
| f.debt_ratio_pit | F46 | ratio | declared | 最新可见balance，不TTM/F | fzhj/zczj；银行/保险不适用null，识别未明留gap；分量缺失或资产≤0 null，保留data_quality提示。 |
| f.pb_pit | F47 | times | declared | 最新可见权益，不TTM/F+V | 不复权c×zgb/gsmgdqsyhj；权益≤0/上市前权益/股本/单位冲突null。 |

保留basis.period/versions/plrq/fallback/pit_basis/null_reason/verify_pending/calc_version及资本相关basis，不把报告期当known_at。L-01 §7C切换条件未关闭继续展示；V5b–j、银行保险/BH/CDR等标记按原规格保留，不因比值抵消就忽略跨期单位冲突。币种/单位冲突沿内部unit_mismatch；冲突按spec既有原因码优先级null，不选AI认为“较合理”的值；本任务不新增行业分位或替换L-01来源。

### sentiment

| feature_key | spec | unit | status | 窗口/PIT | 来源字段；缺失与边界 |
|---|---|---|---|---|---|
| f.limit_up_count_20d | F11 | count | null（等级未明） | 20交易日、有效≥15/D | 日线不复权c与当日涨停价；无涨跌幅日剔除，任一有效日必要涨停价缺失则null。 |
| f.is_limit_up_close | F37 | bool | null（等级未明） | 当日/D | 不复权c==f.limit_up_price，依赖F35；必要价格缺失不能false。 |
| f.is_limit_down_close | F38 | bool | null（等级未明） | 当日/D | 不复权c==f.limit_down_price，依赖F36；必要价格缺失不能false。 |

不增情绪指数/neutral；活跃度无已核实最小项则只列gap，不编公式。F35/F36已有verified_doc仍须pc缺失/无效/与jnfh冲突null，历史主板ST缺口向下传；F37/F38/F11未因依赖有等级而自动晋级。RSI事实列technical，但W-01 V4仍是sentiment规则，不移动原矩阵归属。

### sector_market

| feature_key | spec | unit | status | 窗口/PIT | 来源字段；缺失与边界 |
|---|---|---|---|---|---|
| f.sw_l1 | F26 | code | null（等级未明） | 周快照/S | hszg/zg所属板块与list父节点；一级格式待核，无历史成分，不按名称猜身份。 |
| f.market_regime_idx | F50 | enum | verified_doc | MA20/60、2日防抖；盘后实际入库 | 000300.SH指数日线c、adjust none，不含F24；MA60有效<45/当日缺失null，完整预热61（最少45+1），入库时刻未证留gap。 |
| f.market_regime | F25 | enum | declared | 指数MA60+宽度20、2日防抖；输入到齐后 | 指数与F24；宽度有效<15/指数有效<45或任一缺失null；展示“大盘环境未知”，不填range。 |
| f.ind_rs20 | F27 | pct | declared | 20交易日（需两端价格）/盘后 | 申万一级行业与中证全指指数身份/序列未证，行业缺失null；不以板块名称、连通性或任意指数补齐。 |

F50只映射H-01 C1、W-01 V1/I2及适用环境；F25为账户RC3口径，不能由F50顶替，也不把RC3缺口强算成卡片直接G2依赖。W-01 v2已删除F27反证，不恢复旧卡依赖。

### news

| feature_key | spec | unit | status | 窗口/PIT | 来源字段；缺失与边界 |
|---|---|---|---|---|---|
| f.ann_risk_count_10d | F23 | count | declared | 含D的10交易日/N | announcement:t/zt/nr与first_seen_at，现行T-R23 v2.1标题词表；源缺失/过期/可见性未知null，不宣称“无风险公告”。 |

公告展示仅标题zt、原文链接nr、时间t及来源/取得时间；这是原有公告记录字段，不额外登记feature_key；日期无数值单位。原文标题与识别数分开，标题可展示不等于识别验收。只引用已有来源快照，不抓正文、不生成摘要、不扩展采集。归并/每实体计一次/冻结D09:30完全沿T-R22与T-R23，不修改词表。便利样本/一致性通过不是≥1000未筛样本效能验收，不提升等级。

## 4. 缺口责任与前置（不是本轮调用授权）

| 项 | 责任/前置 | 保持的状态与动作 |
|---|---|---|
| F14/F15 | 后端T-B90接线；编排者核实用户每日18:00调用授权，再另派研究员同日全ST/*ST/退市整理+20普通股人工0差异核对 | declared；d+1可见，首快照前/失败日null；只作G1等依赖缺口，不另造第七维。 |
| F21 | 现有T-B86范围由编排者排，后端补单位/阈值/定稿证据，研究复核 | declared；不升级、不换内置因子，不实调。 |
| F23 | 编排者另派合规效能验收；研究员复核，实时等级另需新鲜度/完整性 | declared；T-R23有限范围通过不关闭正式验收，本轮不补389条、不动冻结。 |
| F25/F27与财务/行业 | 沿T-B05/既有来源待办，架构师裁定新来源/产品取舍，用户批准调用或范围变化 | 原等级不变，缺失null+gap；不以本任务实现或样本代替核实。 |

## 5. 定点核验与DeepSeek边界

执行 `python3 docs/strategies/check_p2n01_dimension_mapping.py`，只检本文六组、键定位、单位/窗口PIT/缺失列、冻结等级、F25/F50区别及24条机械草稿保真；不跑全量/coverage/旧T-R23检查。结构PASS不代替源证据验收、后端实现测试或生产门禁。

DeepSeek：用于24条纯虚构schema的字段/单位保真排版与六维映射机械初稿（产出目录 reports/deepseek/P2N-01/，实际在team下）；一次调用deepseek-flash，2026-11-08 13:50:38北京时间开始，耗时3.559秒，usage=1979 tokens。草稿不提供来源等级/PIT结论。24条逐项保真核对通过；本地复核将虚构PE ratio改为F42 times、负债率pct改为F46 ratio、成交额事实移capital；活跃度只列gap。真实规格内容不外发，提示/输入/草稿/脱敏调用日志/逐项复核均留team目录，不入正式规则。
