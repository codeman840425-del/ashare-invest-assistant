# P2N-R10 策略库周期字段体检

## 枚举范围与结论

> **T-R49 刷新（T-A112）**：H-01 落 v3，`cards/hold_risk_monitor.md` 由 v2 改为 v3，v2 冻结为 `cards/history/hold_risk_monitor.v2.md`（新增历史身份）。现计 **44 个身份记录、22 个源文件**（historical_frozen 3、current_formal 3、多值 9），scope 124；`check_horizons.py` 身份常量 43→44，历史文件匹配由仅 `.v1` 改为任意 `.vN`。下文「43」「H-01 v2」等为 P2N-R10 当时记录。
>
> **T-R55 刷新（编排者裁定 S-01 升 v2）**：`cards/st_pullback_ma.md` 由 v1 改为 v2，v1（055105a 内容，即 T-B100 导入库内者）冻结为 `cards/history/st_pullback_ma.v1.md`（新增历史身份）。现计 **45 个身份记录、23 个源文件**（historical_frozen 4、current_formal 3、多值 9、explicit_single short 10）；`check_horizons.py` 身份常量 44→45。上文/下文「44」「43」为当时快照。

枚举docs/strategies下全部90个既有文件路径；不执行这些文件。按plan §2.5.14的正式strategy-card/spec围栏、知识卡标题/身份行、catalog §2目录表分别定位。**43个独立文档身份记录，21个源文件**，不等于43个生产策略：当前正式卡含L2规格2、冻结历史版本2、T-R16不可导入研究知识卡16、目录研究条目23。相同key的不同版本/不同文档分别保留；目录文档版本0.3.8不是策略version_no，策略版本未知写null。

当前两项：W-01 v2明确horizons=[swing]，审计唯一周期为swing；H-01 v2为system_only且明确支持四周期，**没有唯一版本周期，horizon=null**。文档中的L2规格不证明实际published/observing；未读数据库/真实账户，不声称可运行状态已经验证，生命周期均null。导入不等于启用，simulating也不是可创建普通可运行实例的published/observing。

字段沿现有契约：卡片/规格为horizons数组；建议中的某版本结论与实例为单数horizon。清单中的horizon仅为“源声明恰有一个值”的审计投影，不增加API/config/主周期字段，也不把多值数组第一个当默认。唯一声明35项：intraday_t 7、short 9、swing 11、long 8；多周期8项；周期字段缺失0。源卡字段修复0：没有可安全补写的缺失；不能为满足单值要求覆写H-01的四周期语义或擅增四个可运行版本。35个唯一审计投影不冒称35次源字段修复。

## 逐项清单（机器可读同目录horizon_inventory.json）

| 来源（相对docs/strategies/） | key | 版本 | 原horizons | 唯一horizon | 状态证据类别 |
|---|---|---|---|---|---|
| cards/history/hold_risk_monitor.v1.md | hold_risk_monitor | v1 | intraday_t,short,swing,long | null：不强选 | 冻结历史 |
| cards/history/sw_ma_trend_pullback.v1.md | sw_ma_trend_pullback | v1 | swing | swing | 冻结历史 |
| cards/history/hold_risk_monitor.v2.md | hold_risk_monitor | v2 | intraday_t,short,swing,long | null：不强选 | 冻结历史（T-R49） |
| cards/hold_risk_monitor.md | hold_risk_monitor | v3（T-R49；原 v2） | intraday_t,short,swing,long | null：不强选 | 当前正式卡+L2规格（上线未核实） |
| cards/sw_ma_trend_pullback.md | sw_ma_trend_pullback | v2 | swing | swing | 当前正式卡+L2规格（上线未核实） |
| cards/history/st_pullback_ma.v1.md | st_pullback_ma | v1（055105a） | short | short | 冻结历史（T-R55） |
| cards/st_pullback_ma.md | st_pullback_ma | v2（T-R55；原 v1） | short | short | 当前正式卡+L2规格（上线未核实） |
| T-R16/L-01_lt_value.md | lt_value | v1 | long | long | 研究知识卡/不可导入 |
| T-R16/L-02_lt_quality_growth.md | lt_quality_growth | v1 | long | long | 研究知识卡/不可导入 |
| T-R16/L-03_lt_dividend.md | lt_dividend | v1 | long | long | 研究知识卡/不可导入 |
| T-R16/L-04_lt_low_vol.md | lt_low_vol | v1 | long | long | 研究知识卡/不可导入 |
| T-R16/S-01_st_pullback_ma.md | st_pullback_ma | v1 | short | short | 研究知识卡/不可导入 |
| T-R16/S-02_st_oversold_rebound.md | st_oversold_rebound | v1 | short | short | 研究知识卡/不可导入 |
| T-R16/S-03_st_limitup_relay.md | st_limitup_relay | v1 | short | short | 研究知识卡/不可导入 |
| T-R16/S-04_st_broken_board.md | st_broken_board | v1 | short | short | 研究知识卡/不可导入 |
| T-R16/T-01_t_vwap_revert.md | t_vwap_revert | v1 | intraday_t | intraday_t | 研究知识卡/不可导入 |
| T-R16/T-02_t_spike_fade.md | t_spike_fade | v1 | intraday_t | intraday_t | 研究知识卡/不可导入 |
| T-R16/T-03_t_open_gap.md | t_open_gap | v1 | intraday_t | intraday_t | 研究知识卡/不可导入 |
| T-R16/T-04_t_boll_revert.md | t_boll_revert | v1 | intraday_t | intraday_t | 研究知识卡/不可导入 |
| T-R16/W-02_sw_breakout.md | sw_breakout | v1 | swing | swing | 研究知识卡/不可导入 |
| T-R16/W-03_sw_main_inflow.md | sw_main_inflow | v1 | swing | swing | 研究知识卡/不可导入 |
| T-R16/W-04_sw_ind_rotation.md | sw_ind_rotation | v1 | swing | swing | 研究知识卡/不可导入 |
| T-R16/W-05_sw_earnings_drift.md | sw_earnings_drift | v1 | swing | swing | 研究知识卡/不可导入 |
| catalog.md | gate_tradability | 无策略版本；目录0.3.8 | intraday_t,short,swing,long | null：不强选 | 目录研究条目/非正式版本 |
| catalog.md | ctx_market_regime | 无策略版本；目录0.3.8 | intraday_t,short,swing,long | null：不强选 | 目录研究条目/非正式版本 |
| catalog.md | hold_risk_monitor | 无策略版本；目录0.3.8 | intraday_t,short,swing,long | null：不强选 | 目录研究条目/非正式版本 |
| catalog.md | veto_risk_announcement | 无策略版本；目录0.3.8 | intraday_t,short,swing,long | null：不强选 | 目录研究条目/非正式版本 |
| catalog.md | t_vwap_revert | 无策略版本；目录0.3.8 | intraday_t | intraday_t | 目录研究条目/非正式版本 |
| catalog.md | t_intraday_surge | 无策略版本；目录0.3.8 | intraday_t | intraday_t | 目录研究条目/非正式版本 |
| catalog.md | t_open_gap | 无策略版本；目录0.3.8 | intraday_t | intraday_t | 目录研究条目/非正式版本 |
| catalog.md | st_pullback_ma | 无策略版本；目录0.3.8 | short | short | 目录研究条目/非正式版本 |
| catalog.md | st_oversold_rebound | 无策略版本；目录0.3.8 | short | short | 目录研究条目/非正式版本 |
| catalog.md | st_strong_momo | 无策略版本；目录0.3.8 | short | short | 目录研究条目/非正式版本 |
| catalog.md | st_broken_board_recovery | 无策略版本；目录0.3.8 | short | short | 目录研究条目/非正式版本 |
| catalog.md | st_lhb_inst_buy | 无策略版本；目录0.3.8 | short | short | 目录研究条目/非正式版本 |
| catalog.md | sw_ma_trend_pullback | 无策略版本；目录0.3.8 | swing | swing | 目录研究条目/非正式版本 |
| catalog.md | sw_breakout | 无策略版本；目录0.3.8 | swing | swing | 目录研究条目/非正式版本 |
| catalog.md | sw_capital_persist | 无策略版本；目录0.3.8 | swing | swing | 目录研究条目/非正式版本 |
| catalog.md | sw_sector_rs | 无策略版本；目录0.3.8 | swing | swing | 目录研究条目/非正式版本 |
| catalog.md | sw_earnings_preannounce | 无策略版本；目录0.3.8 | swing | swing | 目录研究条目/非正式版本 |
| catalog.md | lt_value | 无策略版本；目录0.3.8 | long | long | 目录研究条目/非正式版本 |
| catalog.md | lt_quality_growth | 无策略版本；目录0.3.8 | long | long | 目录研究条目/非正式版本 |
| catalog.md | lt_dividend | 无策略版本；目录0.3.8 | long | long | 目录研究条目/非正式版本 |
| catalog.md | lt_low_vol | 无策略版本；目录0.3.8 | long | long | 目录研究条目/非正式版本 |
| catalog.md | veto_unlock_soon | 无策略版本；目录0.3.8 | swing,long | null：不强选 | 目录研究条目/非正式版本 |
| catalog.md | news_sentiment | 无策略版本；目录0.3.8 | intraday_t,short,swing,long | null：不强选 | 目录研究条目/非正式版本 |

## 多周期/未知与解除条件（保留原声明，不强制归类）

| 来源与版本 | 周期集合 | 原因/解除条件 |
|---|---|---|
| cards/history/hold_risk_monitor.v1.md / hold_risk_monitor / v1 | intraday_t,short,swing,long | 四周期通用持仓风控，无唯一版本周期；具体建议的该版本结论horizon缺失时不得猜；结论自带合法且该版本支持的horizon；否则架构师明确唯一周期/选择语义并遵从不可变版本规则 |
| cards/hold_risk_monitor.md / hold_risk_monitor / v3（T-R49；原 v2） | intraday_t,short,swing,long | 四周期通用持仓风控，无唯一版本周期；具体建议的该版本结论horizon缺失时不得猜；结论自带合法且该版本支持的horizon；否则架构师明确唯一周期/选择语义并遵从不可变版本规则 |
| cards/history/hold_risk_monitor.v2.md / hold_risk_monitor / v2（T-R49 冻结） | intraday_t,short,swing,long | 四周期通用持仓风控，无唯一版本周期；具体建议的该版本结论horizon缺失时不得猜；结论自带合法且该版本支持的horizon；否则架构师明确唯一周期/选择语义并遵从不可变版本规则 |
| catalog.md / gate_tradability / 0.3.8 | intraday_t,short,swing,long | 通用/跨周期研究条目，没有单一策略版本周期；不以标题、触发频率或观察窗替代；若另派制成正式卡，先由权威规格明确版本周期/结论绑定及生命周期；本轮不新建策略 |
| catalog.md / ctx_market_regime / 0.3.8 | intraday_t,short,swing,long | 通用/跨周期研究条目，没有单一策略版本周期；不以标题、触发频率或观察窗替代；若另派制成正式卡，先由权威规格明确版本周期/结论绑定及生命周期；本轮不新建策略 |
| catalog.md / hold_risk_monitor / 0.3.8 | intraday_t,short,swing,long | 通用/跨周期研究条目，没有单一策略版本周期；不以标题、触发频率或观察窗替代；若另派制成正式卡，先由权威规格明确版本周期/结论绑定及生命周期；本轮不新建策略 |
| catalog.md / veto_risk_announcement / 0.3.8 | intraday_t,short,swing,long | 通用/跨周期研究条目，没有单一策略版本周期；不以标题、触发频率或观察窗替代；若另派制成正式卡，先由权威规格明确版本周期/结论绑定及生命周期；本轮不新建策略 |
| catalog.md / veto_unlock_soon / 0.3.8 | swing,long | 通用/跨周期研究条目，没有单一策略版本周期；不以标题、触发频率或观察窗替代；若另派制成正式卡，先由权威规格明确版本周期/结论绑定及生命周期；本轮不新建策略 |
| catalog.md / news_sentiment / 0.3.8 | intraday_t,short,swing,long | 通用/跨周期研究条目，没有单一策略版本周期；不以标题、触发频率或观察窗替代；若另派制成正式卡，先由权威规格明确版本周期/结论绑定及生命周期；本轮不新建策略 |

8条中只有1条属于当前正式版本H-01 v2；1条是它的冻结v1；其余6条是catalog中的G-01/G-02/H-01/N-01/N-02/N-03研究条目，非新增运行实例，不把历史/研究项算作8个线上缺陷。G-01/G-02/N-01的系统组件说明另归政策组件，不是独立策略版本。H-01本来跨周期且不经分类器，不能凭盘后扫描、MA窗口或20日证伪指标把它改成swing/long；若建议自带该版本结论horizon即可按正式条款消费，否则保留gap并请架构师明确语义。

额外语义提示1项：T-R16/L-01知识卡虽显式声明long，却写持有≥3个月，可能覆盖plan典型long“半年以上”之外的区间。周期字段仍以显式long原样记录；不据这个下界猜新周期/持有期。该卡当前不可导入，未来解除前需作者/架构师澄清区间，不能凭本体检晋级。W-02的3–10日是观察窗，不以它替换显式swing。

catalog与T-R16存在同编号不同key（如T-02、S-03、S-04、W-03/04/05），本清单逐路径保留，不替团队裁定别名、合并或新建模板。16张T-R16均保持83a66cd不可导入；“未来可进入模板”不是当前启用。知识卡内规则阈值、来源等级及生命周期一律不改。

## 排除范围与RC5消费边界

scope_snapshot逐文件给出类别：golden合成快照/验证输入/脚本不计策略；两个*.card.tmpl是render_T-R15.py读取并写到cards的渲染源镜像，只校验key/version/horizons与正式卡相同，不重复计数；_template.md是教学示例，不含正式导入标记；catalog不是正式卡；历史与停用研究卡分别列出。特征、日历、公告词典、冻结T-R23、合规、周期分类器及辅助工具不算新增模板，不执行任何旧脚本/检查。

RC5只按正式T-A36 B及T-A37：intraday_t→1，short→5，swing/long→20交易日；优先建议中该版本结论horizon，缺失再取明确版本周期；仍不清楚跳过、不加失败、不清零，gap=sim_fail_horizon_unknown，不默认5日。只算本人×策略版本，沿契约既有去重/时序；本任务不实现RC5、不证明线上gap已减少，也不将周期分类器评分、信号有效期、扫描频率、验证horizon_days或典型持有期换算成策略周期。只有获得原本缺失的权威周期定义后，才可能减少真实gap。

## 定点自核与局限

运行`python3 docs/strategies/P2N-R10/check_horizons.py`。直接从实际围栏/身份行/目录表独立抽取，与清单比对；核对路径/版本/状态证据行、全部枚举、合法唯一周期、多周期不默认、排除项和镜像、T-A37映射及状态不晋级。8项篡改（漏项、强选、多值/非法值、历史改当前、版本改写、晋级、镜像冒充策略、旧映射）拒绝。只核文档声明，无业务导入/账户/网络/模型裁决，不运行R08/R09/T-R23/全量/coverage。不是自由中文通用周期分类器，也不证明生产数据库与文档一致。

DeepSeek：用于24个**纯虚构槽位**的raw_horizon/单值或null/复核标记排版初稿（产出目录reports/deepseek/P2N-R10/）。发送前明确实际库文档公开性未确认，因此不发任何真实名称/路径/原文/阈值/团队信息；不是让模型遍历真实库或判周期。官方deepseek-flash一次，1302tokens，2026-11-08 17:17:47北京时间开始、3.161秒，无重试。24行逐项确定性复核；真实43项由研究员本地对照权威条款，模型不提供真值。input/prompt/draft/call_log/review均留档，原稿仍标未核实产物，复核另记。

交付仅本目录三文件，本角色精确白名单扫描并本地提交，不推送；保全共享其他暂存，不改源卡、业务、计划/契约或其他golden。未知/多周期问题通过父级交编排者/架构师，不自行扩任务。
