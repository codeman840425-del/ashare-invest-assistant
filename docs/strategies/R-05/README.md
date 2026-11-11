# R-05｜首轮空跑的判读呈现样张

本单将[R-02/T-R59 §7 发布格式](https://github.com/codeman840425-del/ashare-invest-assistant/blob/3ea69b65a31d7c8488c0bb6babdec6e6312d2863/docs/strategies/T-R58/judging_framework.md#L147)实例化为可读的首轮样张。使用首轮公开行情研究跑的聚合观察值，无真实用户账户或持仓样本。分支从 `origin/main@465e020` 独立建立，只新增本文、样张、聚合JSON及短报告；不引入其他待审分支的代码。

- [first_run_sample.md](first_run_sample.md)：首页、五窗口、P1—P10、R0—R14、覆盖/拼接/成本/敏感性/R/P9附表和补证责任。
- [first_run_observations.json](first_run_observations.json)：从首轮三件套直接提取的原生状态/空值及确定性计数；只保留聚合，不复制原始行情和逐股拼接明细。可用于逐项核对样张，不能充当原三件套。
- [R-05报告](../../handover/team/reports/R-05.md)：定点核对、扫描和交付边界；原始核对日志保留在仓库外状态目录。

## 首轮原件与历史文档的关系

本次可只读访问首轮三件套，读前/读后三个SHA均与既有T-R64/T-R67记录相符；因此样张的计数来自原件重读。这个事实不等于首轮完整输入、启动环境、配置及依赖证据已经全部找回，更不等于r2已落盘。此单未读取r2在写产物。

首轮原件采用执行目录标签 `T-B136-official`。代码SHA及结果起止时间来自执行记录E，该记录单独登记SHA；summary不含原生run_id、执行代码SHA或结束时间。聚合JSON不保存机器上的旧worktree绝对路径，也不把该旧路径写成工具默认参数或待执行配置。

[R-03](https://github.com/codeman840425-del/ashare-invest-assistant/blob/c31acc95cb56fc424895532aca8b5495ae4a5a55/docs/strategies/R-03/README.md)已完成合成填充演练，本单不重复编写渲染器。R-03现有渲染器的 `source_conclusion.status` 只接受其预定义展示枚举；首轮原值 `data_insufficient` 不在其中。因此本单直接按R-02实例化Markdown，原结论单独原样列出；不能为适配工具把它改成unknown/pass，也不在本单擅改R-03工具契约。

[T-R64空态判读](https://github.com/codeman840425-del/ashare-invest-assistant/blob/ab21ffa3e545913e2850d63174910807f5db6487/docs/strategies/T-R58/T-R64_official_run_judgement.md)表格中的“n、mean全空”须以原件为准：**n单元格为字符串`0`，mean/CI为空**。样张已据本次重读准确区分；未顺带修改历史判读文档。`n=0`与 `n=null/缺字段`的语义不同。

## 五窗口绑定依据

本轮P1数组没有phase键，不能仅从数组位置或相同数值自行推定身份。核对了冻结 `d4405a8` 的[experiments.walk_forward](https://github.com/codeman840425-del/ashare-invest-assistant/blob/d4405a8d64420acba2ffb880bc977cfe5059dd45/src/backend/retest/t_r58/experiments.py#L406)与[judgement.evaluate](https://github.com/codeman840425-del/ashare-invest-assistant/blob/d4405a8d64420acba2ffb880bc977cfe5059dd45/src/backend/retest/t_r58/judgement.py#L184)：代码先按count=1…4创建evaluation，再以 `[*folds, held_score]` 组P1五窗。未选出候选时各evaluation无trial；主候选None时直接返回，不执行敏感性与holdout。

| 首轮P1索引 | 明确phase | 预设segment | 本轮CSV实际记录 |
|---|---|---|---|
| 0 | evaluation_1 | fold2 | 无该phase，n/days仅来自summary空态 |
| 1 | evaluation_2 | fold3 | 同上 |
| 2 | evaluation_3 | fold4 | 同上 |
| 3 | evaluation_4 | fold5 | 同上 |
| 4 | holdout | holdout | 无该phase，L7.holdout_runs=0且E确认未执行 |

冻结代码核对的Git blob：experiments=`818cfd8f7383dfd5efd78d1b4be01e6374f5db61`，judgement=`daec17d928addb7840baccac42ab0ceb4dd1db8e`。此绑定只适用本轮；正式r2须核对实际执行版本，不能把原顺序或首轮170行固定为新跑契约。新版本若无法绑定phase/候选，保留缺证。

## 正式结果到位后的替换对应

由原判读执行会话另建正式报告和新观察值快照，保留本目录作为首轮样张。下表是换数入口；换数包括身份、状态、缺证和执行范围，不能只把均值或n替换后沿用首轮归因。

| 呈现位置 | 正式输入与定位 | 替换时必须核实 |
|---|---|---|
| 首页范围/证据 | 后端冻结通知、执行sidecar、summary计划信息、三件套SHA | 已停止写入；实际run_id、代码/方案/配置、输入内容SHA、依赖、结果截止时间；复核报告独立登记 |
| 五窗口 | summary.criteria.P1.windows，trials的phase/candidate/trial_id，legs同trial | 按实际源码和显式phase关联；有腿交易日与计划交易日分列；缺值不补0，零腿不可估 |
| P1—P4 | 各criteria原status及窗口值；P3.average_cost_bp、P4.share、legs费用/reason | status原样保留；费用与净收益同一名义/同腿，问题了结用并集及同范围分母 |
| P5/R组 | criteria.P5.paired、实际A*与控制轨迹/sidecar | 聚合计数、净均值、20抽样完成数与逐腿1:1分开；缺控制证据继续缺证，不借后续B-01两列 |
| P6/P7 | 训练final邻域、环境标签和各标签的n/days/均值/CI | 标签存在不等于统计可评估；不以保留集反选参数 |
| P8/敏感性 | 实际执行各档、训练brackets/boundary、对应trial和名义金额/佣金 | 观察用途保持原方案；最低佣金逐边核；RV-01的1bp/+2bp只是条件推导 |
| P9 | 当轮delisting、名单SHA、尾段证据、当轮生效裁定 | 首轮177与后轮188的对象范围不混；公告正文证据不替代运行时检查 |
| P10 | 训练决定的directions与实际入选记录 | 空列表不能反推某方向收益为负；不按保留集重选方向 |
| R0—R14 | T-R68预筛、原checks和人工复核的独立证据 | 已测范围才可标未发现；零腿、固定文案或无已确认缺陷不能呈全绿 |
| 覆盖/剔除/拼接 | 实际数据coverage、by_exchange_year、exclusions、splice、输入SHA | 先加计数再除；各剔除可重叠；覆盖股票日不当触发率分母；重做零腿归因 |
| 发布措辞 | 全量复核、测试R1—R5和研究判读结果 | 核心缺证仍在则不可判；只由编排者统一发布，不自动晋级/G7/部署 |

接续顺序依Chief冻结令：独立复核终算→测试R1—R5→研究员T-R66正式判读；T-R68的只读预筛按原授权执行，但预筛结果不越过复核/测试门槛。与架构师正在编写的A-08自描述文档如有不符，应按实际冻结输出核对，不能默改schema或结果。

## 本单核对的范围

只做聚合提取与文档核对：三件套SHA稳定性，16/41列与170/0行，训练phase/status/n/空值，P1—P10原状态与原conclusion，五窗身份，100%未知分母、R/保留集未执行及文案边界。没有运行策略、bootstrap、测试业务门禁、ACL负例、数据库或网络请求；文档核对通过不等于P1—P10、R1—R5或策略通过。

DeepSeek：未用；本会话DEEPSEEK_API_KEY不可用，未请求新凭据、未调用外部模型。原始观察值由本地确定性脚本提取并逐项核对；研究判读与缺证结论不外包。

申请新任务：r2冻结后由原执行会话完成正式预筛和判读，交编排者统一发布。
