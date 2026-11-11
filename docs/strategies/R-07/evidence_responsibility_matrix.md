# R-07｜r2正式判读的分工与证据矩阵

> 2026-11-11 北京时间；交接文档。本文的责任与顺序归纳既有Chief派单，不新增实现任务、统计阈值或审批权限。当前不读取r2在写产物；所有“待交付”均不是已完成。

**共同前置是同一份已冻结正式三件套及执行证据。** 后端交付实际身份与输入；复核终算和测试R1—R5给出各自范围的独立结论；研究员T-R66据冻结方案作正式判读并交Chief统一发布。R-03负责呈现，T-R67工具负责结构/已列来源检查，RV清单覆盖独立复算和证据强度，三者不能互相冒充验收。

## 1. 固定依据与版本

| 代号 | 依据 | 冻结版本/摘要 | 使用范围 |
|---|---|---|---|
| M | [R-03说明与呈现槽](https://github.com/codeman840425-del/ashare-invest-assistant/blob/c31acc95cb56fc424895532aca8b5495ae4a5a55/docs/strategies/R-03/README.md) | commit=c31acc95cb56fc424895532aca8b5495ae4a5a55；README SHA256=`a35752347279929955fab7fa83d56ea1691fb3ed7a4445bdab25ec0c7d075c90` | §3填充顺序、windows/criteria/flags/annex槽；工具不计算判定 |
| K | [T-R67核验清单](https://github.com/codeman840425-del/ashare-invest-assistant/blob/a4c6fbdf4aec694e8dba898cd315d7127bed2b6f/docs/runbook/T-R67-r2-verification-checklist.md) | SHA256=`c7c72fd1ef1e3f3888b28e49510a8a11d67081a152148a4069a96f95a3ee99db` | §1—§6：冻结、结构、R证据、coverage、工具边界 |
| V | [池RV-01终算清单](<F:/workspace/team/reports/POOL-RV-01-r2-result-checklist-20261111.md>) | SHA256=`483186199966c804e69066bd9cdd4fcf90496db827cbe575fad45d09cf7178d2` | §3 C01—C13；§6是已完成checkpoint子集，终算仍待正式三件套 |
| F | [T-R68字段映射](https://github.com/codeman840425-del/ashare-invest-assistant/blob/a1776a139ad99903bbaf243652667dd6bec2459c/docs/strategies/T-R59/p1_p10_field_map.md) | SHA256=`bdd74d0609dc4c0c7c0739fa03380192e93e13666c1c76f7c29764bbfc66adc3` | 字段入口与预筛自动/人工边界；下文限定其索引、配对与分母的解释 |
| A | [A-08勘误后自描述文档](https://github.com/codeman840425-del/ashare-invest-assistant/blob/4a1fba1a76775e8faee0daca7e4747cff7d46679/docs/handover/team/reports/A-08.md) | SHA256=`43a8c53ed6378cbe0f99c64c160f400bc2d9a4a03ec12e8b802eeba9722e801a` | summary键集与reason两处已由架构师勘误；其余解释点见§5，实际冻结writer仍为结构依据 |
| R | [R-02呈现口径与RV-01佣金勘误](https://github.com/codeman840425-del/ashare-invest-assistant/blob/3ea69b65a31d7c8488c0bb6babdec6e6312d2863/docs/strategies/T-R58/judging_framework.md) | commit=3ea69b65a31d7c8488c0bb6babdec6e6312d2863 | §2、§7；框架推导不是实测或新增门槛 |

静态代码参照为已知r2基线`a782a1ef5b6a404488c603b49bd2a6ee90112047`，只读其已归档副本并逐文件比对Git blob；**这不证明最终r2执行SHA或未提交adapter已经核验**，实际值须由后端随正式发布补齐。代码路径下文均相对`src/backend/retest/t_r58/`。

## 2. 共用证据包与交接顺序

`<bundle>`、`<run-evidence>`、`<rv-final-report>`、`<test-final-report>`和`<research-report>`均为**待正式交付时登记的逻辑锚点**，当前不宣称这些新报告已存在，不猜新run名/目录。

| 顺序 | 谁负责原始交付/结论 | 最低交接内容 | 证据到位前怎么标 |
|---|---|---|---|
| 0 正式冻结通知 | 后端交付，运维按令协助持久归档 | 实际发布目录与run_id、退出/完成记录、summary/trials/legs各SHA256、成功/failed区分、执行代码及dirty/adapter摘要、完整配置/方案/依赖、HF与ST/listing/termination实际输入SHA；运行侧留保留集冻结/占用/历史证据 | 待冻结；不能用心跳、ETA、完成的分区或子集报告替代 |
| 1 入件一致性 | 复核核接收身份；测试T-R67结构工具提供独立检查；研究员核自己的读取范围 | 三件套同run，读前/后SHA不变；用实际执行代码的CSV列序校验，数量/引用/输入摘要一致；缓存、adapter和summary自述分开 | 不完整、变化中或身份失配即阻塞；原件不改写 |
| 2 全量终算 | 复核（V:C01—C13） | 每项实际输入SHA、方法/范围、观察值、通过/失败/阻塞/已知局限；撮合、数据门禁、正式入口、训练/保留集隔离四结论分开 | 子集预演不得升级全量；R控制缺证不以汇总替代 |
| 3 R1—R5核验 | 测试按既有任务单定义执行，报告冻结SHA与负例证据 | 结构脚本结果、定点门禁/父版负控、运行外呼台账/工具门禁等原单要求；明确哪些未执行 | T-R67脚本只做其已有检查，不能自行宣称R1—R5全部通过；本文不另给R1—R5重编号 |
| 4 正式判读与发布 | 研究员T-R66→Chief统一发布 | 10分钟只读红旗预筛按原授权做；正式结论需接收复核与测试证据后按方案判P1—P10，填M/R的原值与缺口 | 预筛可形成疑点/缺证快照，不能提前放行；生命周期/G7/部署仍另行授权 |

共同证据索引每条至少登记：`run_id`、全量或子集范围、实际执行SHA、输入文件SHA、JSON路径或CSV筛选条件、原观察值与单位、原状态、执行/复核者、报告/日志位置、未完成项及归属。以上是交接记录要求，不是强加给summary的新原生键；执行sidecar名称与格式沿实际交付，不为补证重开保留集。

## 3. P1—P10责任与证据主表

本表“原件/生产者”指运行产物由后端交付；“独立核验”与“研究判读”分别签自己的范围。所有统计量只用合法冻结数据，判据/倍率/费用口径沿冻结方案及已生效裁定；表中不标任何一项已通过。

| 判据 | 证据类型与原件路径锚点（后端交付） | 独立核验责任与来源锚 | 研究员如何填R-03 | 缺证后的交接 |
|---|---|---|---|---|
| P1 | `<bundle>/summary.json:criteria.P1.{status,windows}`；`trials.csv`的evaluation_1…4/holdout、candidate=selected_A；`legs.csv`同trial计数、entry_date；运行配置的最小腿/覆盖天数 | 测试按K:§3做结构/n对账；复核V:C03/C04/C10复核五窗、每窗有腿日数和统计范围 | `windows.<phase>.{candidate,direction,n,days,mean_bp,low_bp,high_bp,status,evidence}`，`criteria.P1`；phase身份确认后才绑定数组 | 后端补准确窗口/候选；缺窗或n缺失不补0，零腿统计不可估，未执行单列 |
| P2 | S:`criteria.P2.{status,robustness}`及P1各窗mean/low/high；T同phase主候选均值/CI；L同腿pnl_bp；入场日块及bootstrap配置 | 复核V:C10复算四折、robustness、保留集区间；测试的因果性/隔离证据见K:§2/§3与V:C06/C07 | `criteria.P2`＋五窗；研究员读取均值/区间/同号情况，原精度保留，不自行以框架量级改门 | 统计值或源范围不一致交后端/复核；保留集/输入不足则不可判，不能按显示舍入值判断 |
| P3 | S:`criteria.P3.{status,average_cost_bp}`；L筛`trial_id=holdout/selected_A`的commission/stamp/transfer/slippage/impact/notional与pnl_bp；执行费率与日期分段 | 复核V:C08/C10核实际双边金额/最低佣金/分段费用与bp换算；后端补未落盘的冻结输入，测试给成本负例日志 | `criteria.P3`、`windows.holdout.cost_bp`、`annex.cost_components`；元、bp分开，同一候选/同范围 | 无上根量/冻结参数等不能说费用全量复算；成本null不填0或约30bp锚，1bp推导不当观测 |
| P4 | S:`criteria.P4.{status,share}`；L同holdout主候选的reason，原分母为该候选全部rows；冻结判读代码用time、deferred或unvaluable_*的并集 | 复核V:C08/C10核逐腿原因及分母，测试按K:§3核n/引用；原因枚举须对执行版本 | `criteria.P4`记录并集分子/分母，`flags.R9/R12`按证据填写 | A-08原因枚举已勘误，仍按实际执行版本筛选；0分母不写0%，不丢未了结/不可估值腿，不重复相加 |
| P5 | S:`criteria.P5.{status,paired.{n,days,mean,low,high}}`；L同trial身份/实际持有期；`<run-evidence>`的逐腿controls或等价可独立核验轨迹（若实际交付） | 复核V:C09/C10负责完整配对/20抽样/同日期方向持有期/成本及配对统计；测试按K:§4核同一实际执行范围 | `criteria.P5`、`annex.r_control`、`flags.R2/R13`；原汇总与可独立复算性分开 | 当前writer无control列；数量相等仅汇总一致，P5独立复算缺轨迹记阻塞，后端补已有证据，不重开保留集或借B-01新列 |
| P6 | S:`criteria.P6.{status,neighbors}`；T:`phase=training_final`的实际参数网格与候选mean_bp；训练冻结配方 | 复核V:C06/C10核A*身份、完整邻域与参数平原；后端给完整training_final行，测试核训练/评估隔离证据 | `criteria.P6`写网格坐标、原邻域值及来源，不按保留集另找更好参数 | 邻域缺行/候选不明交后端；空neighbors不能当全通过，不以新阈值修剪 |
| P7 | S:`criteria.P7.{status,labels,scores.{up,down}.{n,days,mean,low,high}}`；L的evaluation_*加holdout同主候选入场日；实际指数标签输入 | 复核V:C05/C10核标签来源/日期与合并分母；测试给输入/覆盖证据；研究员解释两环境范围 | `criteria.P7`和覆盖附表；标签存在与样本可评估分开，记录每组n/days/均值/区间 | 缺标签或某组无样本交后端/研究员保留不可判；不能只按保留集统计冒充源实现的环境范围 |
| P8 | S:`criteria.P8.{status,sensitivities,training_brackets,boundary}`；T:`sensitivity_train`与holdout中p8_notional_10000/p8_commission_0.0003等实际候选；训练X/Y和冻结配置 | 复核V:C06/C10核训练求边界/保留集只验证、佣金与名义档实际可比性；后端交付敏感性是否执行及同腿输入 | `criteria.P8`、`annex.sensitivity`；保持适用范围/观察用途，标实跑或条件推导 | X/Y未定不向保留集求解；不将P8自动升级额外硬门；未执行敏感性留空而非套+2/−1bp |
| P9 | S:`criteria.P9`与根`delisting`两处细节；`data.termination_list_sha256`、实际名单/listing/expected_end_date/last_bar与停牌证据；R-06/T-R66b公告补证 | 复核V:C05/C10核退市尾段/四分类/缺失；测试按K:§5核coverage及输入SHA；研究员核正文与名单语义 | `criteria.P9`、`annex.p9_crosscheck/coverage`、`flags.R11`；源status/state和residual_risk原样保留 | 输入/日期/范围/末日不同须重新对照；12只正文一致不等于运行时P9通过，不自动改evidence_only/by_rule |
| P10 | S:`criteria.P10.{status,directions}`；T:training_final参数及训练选择记录；L实际direction；冻结配方/保留集锁历史 | 复核V:C06/C10核方向只由训练决定，测试提供隔离及负控证据；后端交付冻结记录 | `criteria.P10`，各窗口direction和来源；研究员报告启用范围，不重挑方向 | 空directions记录原fail及无候选原因，不反推方向收益为负；禁止按保留集方向收益反选 |

S/T/L在主表中分别指同一`<bundle>`的summary/trials/legs，K:§n指T-R67清单。实际证据登记时应使用完整文件名与SHA，不能仅留下别名。

## 4. 三方的最小相互交付

| 来源方→使用方 | 要交什么 | 对应锚点 | 不能替代什么 |
|---|---|---|---|
| 后端/运维→复核、测试、研究员 | 同一正式bundle与逐文件SHA、执行sidecar、输入SHA和范围、锁/日志身份 | K:§1/§2；V:C01/C02/C06/C12；M.artifacts/run | 一份summary自述不能代替执行层/锁历史 |
| 测试→复核、研究员 | 绑定最终SHA的结构/n对账、coverage实际核对和原任务R1—R5结果、明确负例及未跑项 | K:§3/§5/§6；V:C03/C05/C07 | T-R67只读脚本通过不代表完整R1—R5或统计/费用正确 |
| 复核→研究员/Chief | 全量C01—C13结果，P5独立复算能力、费用/时序/统计与四道结论、未完成缺口 | V:§3/§6.3；M.review/flags/annex.remaining | checkpoint的1008股/542289腿不代表全量，也不能用训练控制证明保留集P5 |
| 研究员→Chief | 红旗预筛、P1—P10逐项原值/原状态及判断、五窗/成本/敏感性/覆盖/P9/R缺证、所用复核/测试报告SHA | M.windows/criteria/flags/annex；R:§7 | 文案或renderer不能生成放行、生命周期、G7结论 |

阶段顺序由Chief执行；测试与复核可以提供各自已授权的只读证据，但本文不另外启动并行任务。研究员的10分钟预筛是在正式冻结通知后识别疑点的时间要求，不是10分钟内必须给策略通过的时限。

## 5. 本次对齐发现的解释差异及处置

| 事项 | 当前准确口径与证据 | 谁处理/正式判读如何使用 |
|---|---|---|
| 列数与summary键集 | 参照a782a1e的outputs常量为TRIAL_FIELDS=16、LEG_FIELDS=41、SUMMARY_FIELDS最少10键；publish_run用keys>=最小集，允许coverage/multiplicity/holdout_by_source等额外键。A-08两处已勘误（4a1fba1），其中九键/全集表述已改正；看板摘要47列仍不能当冻结契约 | 此两处采用架构师勘误版本；后端正式交付实际执行版本，测试按该版列序校验。本文不改writer或A-08 |
| n与P4原因 | runner._stat的n=len(trial.rows)，不是仅已了结腿；judgement P4以同候选全部held为分母，reason使用time/deferred/unvaluable_*并集。sim的time_stop/last_fill是参数，不可直接当输出原因名；reason枚举已在4a1fba1改正，A-08的n仍写“（了结）腿数” | 需架构师澄清n为全部trial.rows；复核/研究严格筛原reason，不因未了结/不可估值而缩分母；此处是补文档建议，不新增数据通过条件 |
| 五窗身份 | evaluation_1…4绑定fold2…5；P1数组是evaluations再holdout。F文档“fold1–4”不能按segment字面用，R-05已用冻结控制流确认 | 研究员核实际代码/phase/candidate，不能仅按数组序号猜保留集；缺身份先缺证 |
| R独立复算能力 | F早期“paired.n等于腿数可判1:1”应限定汇总计数；V:C09要求保留集逐腿控制轨迹。后续B-01新增控制列不属于冻结a782a1e | 复核签其可独立核验范围；后端补现有sidecar。缺P5明细继续阻塞，不把推算R均值当独立配对复算 |
| 原生conclusion与呈现器 | writer判读原状态包括data_insufficient/not_passed/scope_unresolved/eligible_for_review；R-03的source_conclusion.status展示枚举不直接接受这些原值 | 暂按R-02/R-05样张直接列原生状态与理由，原件不改；如需自动呈现由Chief另派适配，不能硬改unknown/pass |
| 历史发现的时点 | V中首轮原件未找回与−2bp说明是当时记录；R-05后来重读首轮三SHA相符，R-02已改高佣金净差为−1bp；这些后续事实未代替V的独立终算 | 研究员引用准确版本；首轮可读不冒充已获RV当前复验，佣金差逐腿按实际额/最低值核 |

代码定位：[outputs常量与CSV校验](https://github.com/codeman840425-del/ashare-invest-assistant/blob/a782a1ef5b6a404488c603b49bd2a6ee90112047/src/backend/retest/t_r58/outputs.py#L22)、[summary最小键校验](https://github.com/codeman840425-del/ashare-invest-assistant/blob/a782a1ef5b6a404488c603b49bd2a6ee90112047/src/backend/retest/t_r58/outputs.py#L248)、[runner计数及输出](https://github.com/codeman840425-del/ashare-invest-assistant/blob/a782a1ef5b6a404488c603b49bd2a6ee90112047/src/backend/retest/t_r58/runner.py#L212)、[judgement P1—P10](https://github.com/codeman840425-del/ashare-invest-assistant/blob/a782a1ef5b6a404488c603b49bd2a6ee90112047/src/backend/retest/t_r58/judgement.py#L241)。

## 6. 到件后登记模板（当前全部待交付）

| 登记项 | 当前槽 | 到件后责任 |
|---|---|---|
| 正式run_id/路径/截止北京时间/退出状态 | 待后端冻结通知 | 后端给值，运维按令归档，三方各核身份 |
| 执行代码/方案/配置/adapter/依赖与输入SHA | 待完整执行证据 | 后端给实际值，复核核对应关系 |
| summary/trials/legs三SHA与列序 | 待正式三件套 | 测试结构/n核对，复核接收身份，研究填写证据索引 |
| RV全量终算报告/摘要与阻塞 | 待全量终算 | 复核出具，不能使用子集预演替代 |
| 测试R1—R5报告/摘要与未执行项 | 待测试执行 | 测试出具，不能仅用T-R67工具输出替代 |
| P5逐腿/等价控制证据及适用范围 | 待补证核实 | 后端交已有证据，复核判能否独立复算 |
| 正式判读报告/原生状态/缺证及反证 | 待研究判读 | 研究员交Chief；核心缺证未齐保持不可判/待复核 |

本单只核对文档锚点和冻结静态字段，没有执行策略、bootstrap、T-R67审包、T-R68预筛、RV终算、业务门禁或ACL负例；没有读取在写r2、连接数据库或采集网络数据。本表完成不代表任何生产或研究门槛已通过。

DeepSeek：未用，环境无可用凭据；责任、证据强度和判读边界由研究员核对，不外包。

申请新任务：请Chief转架构师补A-08的n定义说明；r2正式冻结后保留原预筛、复核/测试接件及T-R66判读优先。
