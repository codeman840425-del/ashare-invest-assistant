# R-06｜T-R66b与终止名单的P9输入一致性备忘录

> 2026-11-11 北京时间；只读归档预演。依据#29既有公告正文交叉核、其上游公告JSONL和冻结终止名单；未读取在写r2的checkpoint或结果，未执行P9、策略或采集。

**12/12样本在身份、名称、终止日、标题证据标签和公告URL上完全对应；本地12份PDF的SHA也与T-R66b登记相同。** 这份备忘录可作为正式P9的公告补证入口。正文证据与冻结输入标签分别留存：本单没有将12只自动改成by_rule，没有重算或改写r2的state/residual_risk。

## 1. 冻结来源与格式

[逐股对照证据](join_evidence.json)记录完整来源SHA、字节数、每只的CSV行/JSON索引/JSONL行及公告索引、URL、PDF SHA和字段核对结果；本表别名用于后文定位。

| 别名 | 来源与格式 | 本次SHA256 | 作用 |
|---|---|---|---|
| T | `termination_list.csv`；带表头CSV，7列/337数据行 | `9f7818373f562cffb055293859afc0adce4ade3dbc3c92b0f254d3ca97cf856d` | 已登记的runner终止名单输入；归档副本逐字节相同 |
| M | [#29正文核对清单](https://github.com/codeman840425-del/ashare-invest-assistant/blob/35dfe61e2258006c543b0fbe98135207ae2884d8/docs/strategies/T-R66b/manifests/evidence_only_crosscheck.json)；单个JSON对象，含stocks数组 | `afffa502ceb593210a17bfd224d82657e77439fc31423fe18202deb299d7174a` | 12只既有正文裁决、命中片段、PDF URL/SHA |
| J | 上游`per_stock.jsonl`；每行一个证券公告集合 | `1ba4a0f742cb382c6c44afb7125744c1aaa4d3a53580ab7bd7b1de6be5833ea9` | 通过exchange/symbol连接，核对公告选择与标题，不是正文核对结果 |

T/M/J均在读前及读后核SHA一致。T的33,618字节归档到仓库外状态目录；原输入保持不变。J是已有公开公告索引，本次没有联网更新；M及其上游代码的冻结入口为`35dfe61e2258006c543b0fbe98135207ae2884d8`。派单的“#29公告JSONL”在使用时须区分J与M，不能把M逐行当JSONL解析。

本次预演窗口为 **2022-01-04—2026-08-06，含首尾**，沿M.window与原目标筛法。T窗口内188行且188行都有URL；其中`no_period_evidence=no_title_evidence`恰为12只（SH3/SZ9），与M身份集合双向相等，无漏项、重复或额外项。**正式r2按其实际运行窗口另核分母**；不能未经核对就把337行全表、188行窗口名单和12只样本当成同一个范围。

## 2. 字段对应与不能互换的含义

| 输入字段 | 对应证据 | 本次结果与使用要求 |
|---|---|---|
| T.exchange + T.symbol | M.exchange/symbol，J.exchange/symbol | 12只一对一；exchange为SH/SZ，symbol保留六位字符串及前导0。名称只作显示，不能代替连接键 |
| T.delisting_date | M.delisting_date | 12/12一致，为终止上市/摘牌日期；不替换成公告发布时间、最后交易日或HF应有末日 |
| T.name | M.name | 12/12一致；不把历史简称当当前状态或推断ST历史 |
| T.no_period_evidence | M.title_evidence | 12只均为no_title_evidence；这是标题层证据标签，不是“没有公告”或“正文无证据” |
| T.source_url | M.announcement_url；J.announcements[index].adjunctUrl加既有公开站点前缀 | 12/12相同；URL存在只说明已登记来源，不能证明PDF内容或尾段完整性 |
| M.announcement_title | J所选announcements[index].title | 12/12相同；沿T-R66b规则，在同股“终止上市”标题中按time排序取最后一条，不临时换公告 |
| J.announcements[index].time | 原公告发布时间戳 | 保留原值和索引；不能当delisting_date或expected_end_date，也不拿该值推保留集时序 |
| M.pdf_sha256 | 仓库外同名PDF字节摘要 | 12/12相同；本次只复核文件摘要，未重新下载或重新抽取全文 |
| M.matches / M.verdict | T-R66b既有正文核对 | 12只均留存否定整理期与交易类退市片段，stored verdict均为no_delisting_period_confirmed；不是runner原生枚举 |
| T.source | 名单日期的来源链 | SH为db_securities_exchange_delist_list，SZ为szse_delist_xlsx；巨潮URL是公告证据，不将公司公告标题冒充交易所终止名单 |

[冻结runner_data._termination_list](https://github.com/codeman840425-del/ashare-invest-assistant/blob/a782a1ef5b6a404488c603b49bd2a6ee90112047/src/backend/retest/t_r58/runner_data.py#L117)实际要求exchange/symbol/delisting_date三键，按传入start/end过滤、重复身份拒绝，另外原样读取非空no_period_evidence。当前T有7列，不意味着7列都由解析器列为必需。name/source/source_url用于本次来源追溯，不直接驱动该函数的运行时分类。

## 3. 十二只逐股对照

T行号包含表头，从1起；M为`stocks[i]`的0起索引；J记“行号 / announcements[i]”，行号从1起、数组索引从0起。每行的“同”均表示名称/日期/标签/三方URL及本地PDF SHA核对一致，完整PDF SHA和布尔检查见[逐股证据](join_evidence.json)。

| 证券 | 终止日 | T行号 | M索引 | J行/公告索引 | 对照 | 已登记公告 |
|---|---|---|---|---|---|---|
| SH:600260 *ST凯乐 | 2023-02-15 | 39 | 0 | 20/1 | 同 | [正文PDF](http://static.cninfo.com.cn/finalpage/2023-02-09/1215803248.PDF) |
| SH:600290 *ST华仪 | 2024-01-16 | 45 | 1 | 23/2 | 同 | [正文PDF](http://static.cninfo.com.cn/finalpage/2024-01-10/1218837789.PDF) |
| SH:600297 广汇汽车 | 2024-08-28 | 48 | 2 | 25/1 | 同 | [正文PDF](http://static.cninfo.com.cn/finalpage/2024-08-22/1220939004.PDF) |
| SZ:000023 *ST深天 | 2024-09-02 | 157 | 3 | 81/0 | 同 | [正文PDF](http://static.cninfo.com.cn/finalpage/2024-09-02/1221092726.PDF) |
| SZ:000616 *ST海投 | 2023-08-23 | 195 | 4 | 96/0 | 同 | [正文PDF](http://static.cninfo.com.cn/finalpage/2023-08-22/1217597521.PDF) |
| SZ:000836 ST富通 | 2024-08-12 | 229 | 5 | 109/0 | 同 | [正文PDF](http://static.cninfo.com.cn/finalpage/2024-08-12/1220835453.PDF) |
| SZ:000861 海印股份 | 2024-09-18 | 231 | 6 | 111/0 | 同 | [正文PDF](http://static.cninfo.com.cn/finalpage/2024-09-18/1221225221.PDF) |
| SZ:002325 *ST洪涛 | 2024-08-15 | 260 | 7 | 130/0 | 同 | [正文PDF](http://static.cninfo.com.cn/finalpage/2024-08-15/1220873231.PDF) |
| SZ:002503 *ST搜特 | 2023-08-11 | 275 | 8 | 142/0 | 同 | [正文PDF](http://static.cninfo.com.cn/finalpage/2023-08-10/1217499511.PDF) |
| SZ:002505 鹏都农牧 | 2024-08-30 | 277 | 9 | 144/1 | 同 | [正文PDF](http://static.cninfo.com.cn/finalpage/2024-08-30/1221053558.PDF) |
| SZ:002619 *ST艾格 | 2022-04-28 | 282 | 10 | 147/0 | 同 | [正文PDF](http://static.cninfo.com.cn/finalpage/2022-04-28/1213158664.PDF) |
| SZ:300495 *ST美尚 | 2024-09-20 | 333 | 11 | 187/0 | 同 | [正文PDF](http://static.cninfo.com.cn/finalpage/2024-09-19/1221246075.PDF) |

M中002619用“不设退市整理期”，其余11只用“不进入退市整理期”。M的`delisting_period_mentioned`收录的是“进入退市整理期”子串；本次所见11只该字段的片段均落在“不进入……”否定句内，002619没有该正向子串字段。**不得把该键存在直接当作进入整理期的矛盾证据**。这里复核的是M留存片段与既有裁决的一致性，不宣称已重新完成PDF全文语义审查。

## 4. 正文补证与冻结P9四分类分别留存

参考代码冻结为`a782a1e`，即已落实T-A155的[判读函数](https://github.com/codeman840425-del/ashare-invest-assistant/blob/a782a1ef5b6a404488c603b49bd2a6ee90112047/src/backend/retest/t_r58/judgement.py#L161)。本次只读文件与该提交blob一致：runner_data=`18cba31b7a07872963e7f3c5aed04a564cab1d4d`，judgement=`afef92d17b7816e2161f3bd43fb101203da8069c`；没有导入或执行函数。

| 运行时字段/分类 | 与本单证据的关系 | 正式判读还需什么 |
|---|---|---|
| pass_with_period | 整理期区间及最后bar核验；不能只由标题/正文“有整理期”决定 | 实际listing区间、最后bar、范围匹配 |
| no_delisting_period_by_rule | 依冻结规则与expected_end_date判等路径分类；本次12只不自动并入 | 当轮原始分类、时点输入、应有末日与实际末日证据 |
| no_delisting_period_evidence_only | T仍为no_title_evidence，M补足既有正文交叉核；本单提供附加说明 | 当轮12只是否确实落入该数组、是否存在缺失或尾段问题；不能先写全pass |
| suspended_until_delisting | 与本次正文样本不是可互换标签；历史2例为600355/000638 | 真实停牌/缺口交易日证据及当轮分类 |
| residual_risk | M可作为“已有正文交叉核材料”的证据入口 | 原summary文案原样保留，研究附注另列；不得直接清空或改成null |

冻结函数对无整理期先比较最后bar与HF expected_end_date；不等时仅缺口交易日全部确认停牌才走停牌类，否则尾段缺失。代码中的5自然日常量仅用于区分“停牌到摘牌”展示形态，**不是通过阈值或允许尾段缺口**；本单不重订这个口径。T-A155的类别与后续正式生效裁定优先于研究建议。

历史T-R65曾用输入做过105/69/12/2合计188的模拟分类，那不是r2正式结果。本单没有读取末日行情/coverage/listing区间、没有复跑该模拟，故不对任何一只给出当前P9通过结论。CSV中标题证据的71行也不能直接当成by_rule=71：实际分类还受整理期与停牌路径影响。

## 5. 正式P9接续与反证条件

三件套正式冻结后，由原判读会话登记实际代码/方案/输入及summary SHA，先核`data.termination_list_sha256`及运行sidecar中的真实输入是否等于T；再核当轮日期范围、official_count、missing/tail_missing/period_unknown与四分类的身份集合。参考实现的`criteria.P9`携带status及delisting细节，根`delisting`另留同源信息，须核两处一致，不能只看一个status。

以下任一项发生时，当前“静态一致”不能直接沿用，记录差异并交Chief/对应负责人：

- 输入SHA变化、身份或终止日不一致、符号前导0丢失、重复键、范围不再相同：后端补冻结输入与内容对应，不覆盖在跑输入。
- URL/标题/本地PDF摘要变化，或正文存在实际肯定进入整理期的矛盾：研究员核来源/否定语境；本单不重新外抓或自动选其他公告凑一致。
- expected_end_date或last_bar缺失/不等，出现未解释的尾段缺失或停牌缺证：后端/复核处理运行时数据，公告无整理期不能替代末日证据。
- 原summary仍有evidence_only/residual_risk：原始字段保持，正文核对作为独立研究附注；升级输入标签/分类须等正式裁定及新版本，不借本文改冻结产物。
- 三件套/执行证据/独立复核仍不齐：保持不可判或待复核，不以12只静态一致代替P9、P1—P10、R1—R5或G7。

正式报告可引用：“本轮输入若与冻结T同源且范围一致，T-R66b的12只公告补证在身份/日期/标签/URL上与输入相符，本地PDF摘要也一致；当前补证支持正文层解释，运行时尾段、分类与原残余风险仍按本轮冻结summary及独立核验分别报告。”

## 6. 核验范围

142/142项离线来源/字段核对通过。日志与原样CSV归档在仓库外`F:/workspace/team/status/R-06/`，脚本`audit_inputs.py`、逐项结果`input-check.json`和`inputs/termination_list.csv`；仓库仅放本文、逐股公共证据投影与短报告。未执行原带联网功能的T-R66b交叉核脚本，未运行策略/门禁/ACL负例，未联网采集、连库或改r2。

DeepSeek：未用；环境DEEPSEEK_API_KEY不可用，原公开记录由本地确定性代码连接和复核；规则语义与最终P9判读不外包。

申请新任务：按池顺序接R-07判读分工与证据矩阵；r2冻结后的原预筛/正式判读优先级保留。
