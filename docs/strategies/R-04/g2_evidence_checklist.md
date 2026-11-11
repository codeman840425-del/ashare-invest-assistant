# R-04｜W-01 / H-01 的 G2 补证与重跑触发清单

> 2026-11-11 北京时间；研究文档，基线 `origin/main=465e02046fa8d971897603742497444f884e89a2`。本地 `main=bbcbf66` 落后主线 374 笔，按当前主线建立 `ds/R-04`。本单未连库、未读 r2 产物、未采集、未执行门禁；下述现场行数/运行时等级/新版本审核均须由后端补只读证据。

**现有证据不支持“两卡当前都 G2 失败”**：W-01 v2 在 T-B100 的 G2 fail 只指 F21；H-01 v2 的 G2 已 pass。主线 H-01 已是 v3，7 个数据依赖未变，但旧 v2 审核不能沿用到 v3。本清单同时列来源等级阻断、运行时缺值及新审核缺证，分别说明处理条件。

## 1. 先固定卡版本与证据范围

| 对象 | 仓库可核对状态 | 本次不能据此推出什么 | 下一份证据 / 负责人 |
|---|---|---|---|
| W-01 v2 | [T-B100:8](../../handover/team/reports/T-B100.md#L8)：G2 fail，F21 未 verified_doc/live；[现行卡](../cards/sw_ma_trend_pullback.md)为 v2、13 个直接键 | 未查库，不能把历史 factor_values 零行写成当前行数；不能说只有补入行就会 pass | 后端给目标 version_id/content_sha256 与 G2.detail.issues 的只读摘要 |
| H-01 v2 | [T-B84:10](../../handover/team/reports/T-B84.md#L10)、[T-B100:7](../../handover/team/reports/T-B100.md#L7)：G2 pass、无剩余直接键；G6 warn | 不继续引用 T-B80 的早期 fail；不把 G6 no_history 算成 G2 失败 | 历史记录只用于定位差异 |
| H-01 v3 | [现行卡:58](../cards/hold_risk_monitor.md#L58)仍为 7 键；v3 只改假设/证伪，数据依赖未改 | 不把 v2 pass 或文件中的 verified_doc 当成目标库新审核已通过 | [T-R54:42](../T-R54/g1_g6_transcript_H-01_S-01.md#L42)：导入当前版本并重跑；新 gate_results/绑定由后端补，正式导入按当次授权 |

来源等级以 [feature_spec 的版本化 YAML](../feature_spec.md#L1029)为准，G2 实际读取**目标库**的 feature_catalog。`verified_doc` 只足够本链路的 `simulating` 目标，不能据此推为 published/observing；已有 reviewed_document 的生命周期上限也须保留。

## 2. G2 真正检查什么

[required_features/source_issues](../../../src/backend/app/strategy/cards/source_reviews.py#L194)取 `strategy-spec.rules[].required_features` 与卡 `data_needs[].feature_key` 的并集，检查是否至少 verified_doc、是否有相符的来源审查和生命周期上限；[prepare](../../../src/backend/app/strategy/promotions.py#L94)读取库内目录并进行 preflight。当前这段 G2 不读取行情行数，不会因为 fund_flows/factor_values/feature_bars_daily 新增行而自动通过。

直接来源阻断的返回项包括 `feature_not_verified_doc_or_live`、`reviewed_source_missing_or_status_conflict`；未知键由 preflight 产生 `unknown_feature`。adjust/DSL 不一致在当前分类中可能进入 G3，不应统记为 G2。元数据空值、预热不足与事实值缺失须留 gap/insufficient_data，不能一律新设为 G2 fail；反之也不能因 G2 pass 宣称运行时数据齐备。

当前直接依赖去重 14 键：H-01 v3 为 7、W-01 v2 为 13；13 键 verified_doc、仅 F21 declared。下表状态是**本基线规格**，未复查目标库。

## 3. 每个直接键的补证路径与触发依据

路径“本地”指用已获准、可追溯数据按现行 feature_spec 派生并由授权管线落地；“麦蕊”指未来另有明确授权的执行方补证，本团队已停止复跑，不新增任何调用、日期或次数。“r2”只指已冻结、许可明确产物可提供索引/校验材料，不表示本单读取或可以直接入生产特征库。

| 特征键 | 直接使用卡 | 规格状态 | 缺什么 / 补齐内容 | 获取路径与到位信号 |
|---|---|---|---|---|
| `f.close_qfq` | H/W | verified_doc | as_of 当次 qfq 序列、单位/锚点/PIT 留证；H 默认62、W默认65根有效K，按实际参数调整 | 本地合格日线+已知权息；r2 manifest 仅辅助定位原料，summary/legs 不是快照；同 as_of 特征快照刷新 |
| `f.high_qfq` | H/W | verified_doc | 与 close 同锚、同窗高价；ATR14 至少15根输入，缺值不补 | 本地同一日线/权息批次；同 feature_set_version 派生完成 |
| `f.low_qfq` | H/W | verified_doc | 与 close 同锚、同窗低价，含 ref/结构止损所需历史 | 本地同上；同批证据完整，不用成交腿极值补日线 |
| `f.amount` | W | verified_doc | 元单位与源尺度核对、有效日均额/冲击输入；跨源不能照搬量额单位 | 本地获准日线；麦蕊既有单位证据有限定；r2 的成本/交易额统计不能代替日线金额来源复核 |
| `f.list_days` | W | verified_doc | 主数据 list_date 与覆盖到上市日的交易日历；覆盖不到则 null | 本地主数据+日历；r2 listing 索引仅可作对照，需代码/日期/来源一致 |
| `f.is_suspended` | H/W | verified_doc | 日线 sf 与采集可见时点；无行/sf空不能推成不停牌或停牌 | 本地保留源字段，或授权方补麦蕊 sf 正例；r2 停牌排除计数不是 sf 正例 |
| `f.limit_up_price` | W | verified_doc | 有效规则段、主板历史ST、唯一参考价pc及除权交叉核对；无涨跌幅日合法null | 本地主数据/日线/权息派生；r2 ST/退市材料仅作有边界的历史证据，不能直接升来源等级 |
| `f.limit_down_price` | H/W | verified_doc | 同上，pc缺失/无效或与已确认权息冲突时null；不猜ST比例 | 本地同上；规则/参考价/历史身份三项共同刷新 |
| `f.limit_locked_up` | W | verified_doc | 不复权四价、量与涨停价齐；四价相等且v>0，依赖缺失先null | 本地从上行依赖派生，继承其缺口；不把收盘涨停当全天一字 |
| `f.limit_locked_down` | H | verified_doc | 不复权四价、量与跌停价齐；缺依赖null，v=0不判一字 | 本地派生；同版跌停价/日线到位，不增实采 |
| `f.rsi14` | W | verified_doc | Wilder固定起点、qfq@as_of全序列重算；预热28；全平盘null | 本地确定性派生；r2 参数/收益/分钟sigma不能代替日线RSI |
| `f.main_net_20d` | W | declared | 四字段口径、金额单位、大单/特大单阈值、定稿时刻、完整窗口与审批等级；见§4 | 麦蕊授权方的脱敏配对证据+本地四字段派生；r2 OHLCVA/三件套不含该资金字段 |
| `f.np_yoy_latest` | W | verified_doc | 归母累计同期净利、基期>0、plrq次交易日09:30及首次观测/更正版本；缺财报不得填0 | 本地已有合格报表或授权方补报表，落 financial_reports 的 as_of 可见版本；r2 三件套不能补财报 |
| `f.market_regime_idx` | H/W | verified_doc | 000300.SH日线与落库时点、MA20/60和2日防抖；完整预热61，最低45+1且当日有值 | 本地合格指数日线；r2 按自然年的环境标签不是F50；不可用含宽度F25替代 |

规则/窗口/缺值来源：[两卡](../cards/)、[feature_spec F16–F23/F50](../feature_spec.md#L265)、[六维映射](../phase2_daily_dimensions.md#L26)。这些预热条件用于事实求值与覆盖报告，不另加为来源等级的通过阈值。

## 4. F21：零行之外还有哪些未闭合项

| 编号 | 应补的证据 / 验收内容 | 获取路径 | 何时足够请求刷新 / 还不能做什么 |
|---|---|---|---|
| F21-A | 四字段 `zmbtdcje+zmbddcje−zmstdcje−zmsddcje`、买正卖负；保留原精度、不擅自换算单位 | [F21规格](../feature_spec.md#L291)、[T-B81摘要](../../handover/team/reports/T-B81.md#L7)；未来授权方给脱敏复算摘要 | 公式一致仅是已知前提；内置 factor_id=`main_20d_net` 不等价，其行数/非空不能替代F21 |
| F21-B | 金额绝对单位、特大单/大单阈值的可追溯来源与样本对照；不能只凭名称/数量级猜单位 | 已有可引用文档+授权实测方补证，由研究/架构验收 | 只有单位或公式证据仍不足；未闭合维持 declared，不按F19单位自动继承 |
| F21-C | 同一交易日/证券在盘后与次交易日开盘前的成对快照、取数时间与差异；15:40只是待证时点 | [数据验证交接§1.1](../../handover/data-validation-handoff.md#L40)的历史验收意图；取用由Chief向老团队索取脱敏结论和hash | 历史过窗不补、不重建触点；仅拿 d 日五份或 HTTP200 不能证明定稿稳定，缺原件/配对则缺证 |
| F21-D | 每个F21日值自身回看20交易日，≥15有效日；有成交日资金缺失则整值null；停牌/缺采要区分 | 本地 calendar+fund_flows 源字段与日线对齐、按 as_of 派生 | 15条原始资金日不等于15个日级F21输出；按待生成输出日期反推原料范围，不另创更短窗口 |
| F21-E | 可消费的日级F21在 `market.feature_bars_daily.values` 中，绑定 code/trade_date/feature_set_version/computed_at；值类型、PIT与来源批次均可核对 | 授权后端管线落地、只读覆盖摘要；[表结构](../../../src/backend/app/db/tables/market.py#L564) | 单有键、null值、重复版本或未来记录不算有效覆盖；`factor_values`只作内置因子对照 |
| F21-F | 审批后的等级与限定同步到 feature_spec、矩阵、运行时 feature_catalog，reviewed_document.status一致；来源载入策略接受正式新裁定 | [load_reviews:93](../../../src/backend/app/strategy/cards/source_reviews.py#L93)现硬核F21=declared，[persist_reviews](../../../src/backend/app/strategy/cards/source_reviews.py#L156)保留受审路径 | 不能只改一个YAML或手写SQL升库；后端需按架构裁定同步审查策略，不能为过G2关闭冲突检查；完成后才可能消除本基线F21等级阻断 |

旧验收文件的日期/次数是历史记录，本清单不给本团队新的采集授权，也不保证老团队已完成。原始响应、证书和账户材料留在受控渠道；本目录只接脱敏结论/摘要hash。

### 4.1 T-R28 / T-R31 检测器的可用边界

[旧报告](../../handover/team/reports/T-R28.md)写“阈值可覆盖”，已被[现行脚本](../check_f21_ready.py#L42)与[锁文件](../T-R28/f21_ready_thresholds.json)覆盖：5股×近20交易日每股≥15日，禁止CLI/环境变量改阈值，canonical SHA256 为 `5ff63fe24ee3327ad85ab1022a5ae41357fc279a358db9bd73360675379608c8`。这是**申请重跑的既有覆盖提示**，不是G2来源验收、更不是策略启用许可。

当前SQL按 JSON 键存在及 `COUNT(*)` 统计，并未核对值非null/有限数、`COUNT(DISTINCT trade_date)`、feature_set_version/computed_at、上界 as_of 与精确交易日集合。日历查询也未按 as_of 截止，异常时退到自然日。[表主键](../../../src/backend/app/db/tables/market.py#L572)允许同日多个版本，因此物理行数可高于有效日期数。未来触发器必须补这些核验，日历/DB异常保持不可判，不沿用自然日退化结果发就绪信号；SQLAlchemy参数绑定/隔离库只读执行还须后端定点验证。本单不改旧脚本、不运行SQL，不称它已有实库就绪证据。

## 5. 间接依赖与其他门的缺口

| 项 | 实际影响 | 补证路径 / 触发动作 |
|---|---|---|
| F14/F15 历史ST/退市状态 | G-01可交易性、主板涨跌停基准；未在两卡直接键并集中。未知继续向下传null/不可执行 | 本地主数据历史快照；r2 ST/退市来源可作范围限定的对照，不能填成当日实时状态；未来实采归老团队/另授权；不伪列为两卡新的直接G2失败 |
| F23 公告风险 | N-01买入草案的 source/freshness 缺口；H卡不凭公告直接卖出 | 主线规格仍declared；待审词表v3线的 verified_doc 也不替代 live 新鲜度/完整性；须逐项绑定冻结版本，不等于本次运行时已升级 |
| F25 / F27 | 当前卡已改F50、W v2删除F27；F25继续服务RC3 | 不恢复成两卡直接G2依赖，不因F50有值就宣布RC3完整 |
| H上下文/计划/行业 | 成本价qfq、仓位、计划绑定、行业权重可见性；行业缺失W3=null | 用合成/获准快照验证消费链；真实持仓不入本清单，数据缺失不自行卖出；不让研究报告读取账户材料 |
| G6 120日/可比集合 | 历史两卡均warn；[现行prepare](../../../src/backend/app/strategy/promotions.py#L208)仍调用 compare(None,...)，单独导入历史不会自动启用统计链 | 后端另补历史统计接线，缺值仍null；r2 做T样本/收益不能冒充这两卡的120日体检；不把G6 warn混写为G2 fail |
| H-01 v3 / policy3 / 新审核 | 当前文件版本与旧库审核不一定一致；旧v2审核不能晋级v3 | 后端按授权导入、核对版本和policy，再跑绑定新内容的G1–G6；不能让数据监控器自行 --apply/seed/改生命周期 |

## 6. 交给触发脚本的最小需求（建议，尚未实现）

触发事件只读接收“获准来源证据/目录同步完成、合格特征快照完成、卡/策略版本变更”摘要。r2 完成事件本身不触发两卡来源升级；没有相关依赖变化时不重复排队。区分以下两条动作，避免“有行=可晋级”：

- **覆盖诊断重跑**：F21覆盖首次达到锁阈值或有效覆盖摘要改变，可报告给Chief；若仍declared，明确预计G2仍fail，不声称已解除来源阻断。H-01不等待F21。
- **G1–G6刷新请求**：当前卡版本/内容已在目标环境、来源审查及运行时目录对齐、所需刷新能力可用，且当次派单授权执行，才向现有审核工作流交付请求；覆盖不足/缺值仍按各门真实规则报告。未授权时只生成建议派单文案。

内部证据记录至少绑定：卡key/版本及实际 version_id、content_sha256、feature_set_version、代码/规则配置摘要、依赖来源状态/审查摘要、数据as_of/可见截止与有效覆盖摘要、旧review_id及执行状态、这次授权/处置结果。上述为内部需求清单，不新增公开API字段；不得写入账户、证书或原始响应。幂等键需包含依赖证据变化，不能只用card_id或“r2已完成”；相同证据只通知/排队一次，失败留诊断，不循环重试或补采。

**刷新能力是后端前置，不能靠重复POST完成。** [request_review:165–174](../../../src/backend/app/strategy/reviews.py#L165)遇同内容、同版本、未stale的pending审核会返回旧id与created=false；[API:103](../../../src/backend/app/api/v1/promotions.py#L103)只在created=true时排执行；[execute_review:225](../../../src/backend/app/strategy/reviews.py#L225)对已非execution_pending的记录直接返回。[content_sha256](../../../src/backend/app/strategy/reviews.py#L35)不包含feature_catalog的实时状态，目录更新本身不自动触发stale。

需Chief安排后端/架构确定“来源证据变化后的内部刷新/失效与审计”路径；在该契约补齐前，脚本应报“需要刷新但现流程不会重算”并给建议派单。不得自动删审核、伪造content哈希、复制旧pass、做G7决定或回退生命周期；draft之外版本不得硬走只接受draft的请求入口。结果回收只读检查 gate_results、version/content绑定与stale，再报Chief，G7保持独立授权边界。

## 7. 触发实现的定点验收清单（确定性预期，非已跑测试）

| 场景 | 必须观察到的结果 |
|---|---|
| 只有内置main_20d_net有行，F21派生无值 | 覆盖不就绪；不替代F21，不升级来源 |
| 5股每股15条，但JSON值全null或非有限数 | 不计有效覆盖；与真实数值0区分 |
| 同日多feature_set_version凑15物理行 | 按同版/时间可见约束与不同交易日去重，不达标不ready |
| 未来日历、未来computed_at或不同截止窗 | 不计入当前as_of；无可靠日历时缺证，不用自然日凑数 |
| 数据到位但F21仍declared | 只能提示诊断重跑；不得预测G2 pass |
| spec已改doc但矩阵/库内reviewed_document仍旧 | 来源冲突仍阻断；不手改库，不放宽载入策略 |
| G2来源已齐，MA/RSI预热不足 | G2按来源规则判断，事实求值insufficient_data；不造新G2失败阈值 |
| W的F21阻断，H的7键已齐 | 只影响W；H按自身当前版本申请核验，不跨卡联锁 |
| H v3只拿到v2旧pass | 新版审核缺证；不复用旧结果 |
| 同版本旧pending已完成，目录证据变化后重复POST | 暴露刷新能力缺口；不能把旧review返回当作新检查完成 |
| 同证据事件重复到达，或执行中断 | 至多一次通知/排队，保留原状态与诊断，不自动采集/批准 |
| G2 pass但G6 warn、G7未执行 | 如实分列；不生成可启用/已发布结论，不改生命周期 |

本单验收只核卡/源码/规格引用与上述清单完整性，不执行这些门禁或业务负例。DeepSeek：未用，来源等级与重跑权限/确定性预期属于规则判读；本会话亦无可用凭据，未发起调用。

申请新任务：由Chief安排后端的来源刷新契约与只读覆盖检测修订单；正式r2判读仍由私聊T-R66第一顺位执行。
