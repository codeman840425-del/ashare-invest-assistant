# 风险测评问卷：设计说明

> 研究员 T-B15 草案，2026-11-01。可配置版本见同目录 `risk_questionnaire.yaml`（questionnaire_version 1.0.0，status: draft）。
> 题目、分值、档位边界、有效期都是**研究员初值**，没有统计依据，标“用户可否决”的条目需要用户拍板；涉及法律效力的条目需要法律专业人士审阅。
> 本文所有答卷和结果都是**示例**，不是真实用户数据。

## 1. 定位声明

- 本工具是个人投资研究辅助工具，**不是持牌证券投资咨询机构，也不是证券经营机构**；不代客下单，不接触用户资金，交易由用户在自己的券商完成。
- 本问卷用于**个人适配和风险提示**：决定画像里的 `risk_tolerance`、`experience`、`effort`，进而影响周期适配分类器对 short / intraday_t 的封顶和风险提示的强度。它**不是**《证券期货投资者适当性管理办法》规定的法定适当性评估，结果也不对应经营机构的 C1–C5 评级。因此档位名称用“保守/稳健/平衡/积极/进取”，不用 C1–C5。
- 问卷结果不代表对任何股票、策略或规则信号（候选信号）的风险收益判断。产品文案不得出现推荐个股、承诺或暗示收益的措辞（例如“适合您买入”“稳健获利”）。结果页只说明“画像如何影响周期适配和风险提示”。
- 我们参考官方适当性文件，只是借用其中成熟的问卷结构（了解哪些信息、最低档怎样处理、记录怎样保存），不代表本工具承担或满足经营机构的法定义务。

## 2. 设计依据（只引用官方来源，附链接）

| 依据 | 来源 | 本问卷借用的内容 |
|---|---|---|
| 《证券期货投资者适当性管理办法》（证监会令第 130 号，2020 年修正文本） | http://www.csrc.gov.cn/csrc/c106256/c1653849/content.shtml | 第六条：需了解投资经验，投资期限、品种、期望收益，风险偏好及可承受的损失（对应本问卷 R/E/F 组）；第十条：普通投资者的风险承受能力综合考虑收入、资产、负债、投资知识和经验、风险偏好等（对应 F 组和 K 组参与封顶）；第十三条：信息变化时更新评估（对应重测）；第十九条：投资者坚持购买时可以特别书面警示，但最低类别除外（对应 §5 第 2 项）；第二十二条：不得对不确定事项作确定性判断（对应 K4 和文案约束）；第三十三条：投资者应提供真实信息（对应开场说明） |
| 同一办法 2022 年修正（证监会令第 202 号） | https://neris.csrc.gov.cn/falvfagui/rdqsHeader/mainbody?body=&navbarId=3&secFutrsLawId=b139ee3b6fea460a818840e0a982cb98 | 该页面为脚本渲染，本次没有取到正文。**2022 修正是否改动上列条文编号：未核实** |
| 中证协《证券经营机构投资者适当性管理实施指引（试行）》（中证协发〔2017〕153号） | https://www.sac.net.cn/flfg/zlgz/201706/t20170629_14339.html | 第八条：用问卷评估风险承受能力；第九条：普通投资者至少分五级，结果书面确认并留存；第十条：问卷由投资者本人填写，不得诱导；第十一条：保存每次问卷的内容、时间和结果（对应答卷不可变留档）；第十二条：没有风险容忍度或不愿承受任何投资损失的，列为最低类别（对应 R1=A 一票否决）；第三十二条：书面形式包括电子形式 |
| 同一指引附件 4《普通投资者风险承受能力评估问卷》（参考模板） | https://www.sac.net.cn/flfg/zlgz/201706/P020230711373465947023.docx | 题型结构（财务状况、投资知识、投资经验、投资目标、风险偏好）；“两种投资方案怎样分配”和“最多能承受多少损失”两类题的思路（本问卷 R3、R1 为自写措辞）。模板**不含分值**，说明里写明分值、权重和分档由各机构自定，所以本问卷的分值全部是自定初值 |
| 《个人信息保护法》 | http://www.npc.gov.cn/npc/c2/c30834/202108/t20210820_313088.html | 第二十八条：金融账户等属于敏感个人信息（plan 7.3 已引用）。问卷不收集年龄、职业、收入金额、身份证号，资金只问比例和期限（最小必要） |

未核实事项：
- 官方文件中**没有找到测评有效期或重测间隔的规定**。本问卷的 365 天有效期是研究员初值，不是任何监管口径。
- 业内常见的“12 个月重新评估”做法本次没有找到官方出处，不作为依据。

## 3. 问卷结构与计分（摘要，以 yaml 为准）

| 组 | 题目 | 作用 |
|---|---|---|
| 风险承受 | R1 可接受最大亏损、R2 下跌 20% 的反应、R3 甲乙分配、R4 投资目标 | 计入 risk_points；R1 同时触发否决和封顶 |
| 资金与期限 | F1 占家庭金融资产比例、F2 资金闲置期限、F3 资金来源 | F1/F2 计入 risk_points；F2、F3 触发封顶（F3 不计分） |
| 投资经验 | E0 自评（不计分）、E1 交易年限、E2 最复杂品种、E3 近 12 个月笔数、E4 止损执行 | 计入 experience_points；E0 只用于一致性提示 |
| 可投入精力 | T1 盘中看盘、T2 每周研究时间 | 按规则直接映射 effort |
| 产品认知 | K1 T+1、K2 创业板涨跌幅 20%、K3 先跌 10% 再涨 10%、K4 规则信号能否保证收益 | 答对题数计入 experience_points；≤ 1 题时风险承受封顶 3；K4 必须答对 |

**风险承受（risk_tolerance）**：
1. R1 选“不能接受任何本金亏损” → 直接为 1，并标记 `no_loss_tolerance`。
2. 否则 risk_points（0–36）按 0–8 / 9–15 / 16–22 / 23–29 / 30–36 映射为 1–5。
3. 再取所有命中封顶的最小值：R1 ≤5% → 2，≤15% → 3，≤30% → 4；资金 3 个月内要用 → 2；1 年内有确定大额支出 → 3；含借款 → 2；认知题答对 ≤ 1 → 3。

**投资经验（experience）**，按顺序取第一条命中：
1. 自己买卖 A 股不足 1 年 → novice；
2. experience_points ≥ 12、交易 3 年以上、认知题答对 ≥ 3 → advanced；
3. experience_points ≥ 7、认知题答对 ≥ 2 → intermediate；
4. 其余 → novice。

**可投入精力（effort）**：大部分交易时段可看盘且每周研究 ≥ 3 小时 → high；盘中累计看盘 ≥ 1 小时，或午休/收盘后看盘且每周研究 ≥ 3 小时 → medium；其余 → low。

`horizon_pref` 和 `max_single_position_pct` 不由问卷推导，由用户在画像页直接选择。

**缺答**：任一必答题缺答、选项不存在或 K4 答错 → 422 VALIDATION_ERROR，列出题号，不出结果、不补默认值、不改画像。

**一致性校验**（CC1–CC6）只产生标记和提示，映射本身已取保守口径：自评高于结果时按结果填写（CC1，例如自称“经验丰富”但交易 0 年）；“从未买卖过”但有交易（CC2）；可接受亏损小却选激进分配（CC3）；目标保本却下跌加仓（CC4）；导入成交与作答不符（CC5，不覆盖答案）；作答少于 60 秒（CC6）。

**有效期与重测**：有效期 365 天，到期前 30 天提醒，过期后还有 30 天宽限期；宽限期后视为未测评。问卷 MAJOR 版本发布（计分规则变化）时强制重测；用户可随时重测，但 24 小时内最多提交 3 次；每次答卷都留档。

## 4. 档位如何驱动分类器（horizon_classifier 1.1.0）

| 画像字段与取值 | 触发的分类器规则 | 效果 |
|---|---|---|
| risk_tolerance ≤ 2 | SH0（requires risk_tolerance ≥ 3）不满足 | short 封顶 59（低于 suitable_threshold 60），HorizonCap.kind = requires，rule_id = SH0 |
| risk_tolerance ≥ 3 | SH0 满足 | 无封顶 |
| effort = low | SH0B、IT0B 不满足 | short 和 intraday_t 都封顶 59 |
| effort = medium / high | SH0B、IT0B 满足；同时影响计分项 IT3、SH7 | 无封顶，high 加分更多 |
| experience = novice | SH0C、IT0C 不满足 | short 和 intraday_t 都封顶 59 |
| experience = intermediate / advanced | SH0C、IT0C 满足；同时影响计分项 IT5 | 无封顶 |
| 从未测评或测评失效 | 三个字段按未填写处理，SH0/SH0B/SH0C、IT0B/IT0C 全不满足 | short、intraday_t 封顶 59；建议类接口 403 CONSENT_REQUIRED |
| 风险承受、经验低于卡片的适配下限 | plan 实例校验 I3 | 422 STRATEGY_FIT_ACK_REQUIRED，用户确认后才能启用 |
| 否决档（risk_tolerance = 1 且 no_loss_tolerance） | 同 risk_tolerance ≤ 2；另见 §5 第 2 项 | short 封顶 59 |

问卷**不影响**：IT0（是否持仓）、LG0/LG0B（财报数据是否足够）、HG1–HG6 数据闸门、swing（无画像 requires）。horizon_pref 只影响 SH6/SW6/LG6 计分，由用户自选。

## 5. 需拍板的设计选择

1. **问卷结果作为上限**【研究员默认，用户可否决】：用户可以把三个字段改得比问卷结果更保守，不能改得更激进（否则 422）。理由：horizon_classifier.md §9 第 2 项已指出，自填 intermediate 就能绕过 novice 封顶。代价：对用户的约束更强，需要契约支持（见 §7）。
2. **否决档不允许 fit_ack 越过**【研究员默认，用户可否决】：R1 选“不能接受任何本金亏损”的用户，启用 short / intraday_t 相关策略时不提供“我已知悉，仍然启用”的确认入口。参照办法第十九条“最低类别除外”的思路；本工具是否适用该条由法律专业人士判断，这里只是借鉴。
3. **有效期 365 天 + 宽限 30 天**【研究员初值，用户可否决】：没有官方依据。
4. **不问年龄**：只在注册时声明年满 18 周岁（plan 7.3），问卷不重复收集。

## 6. 示例答卷（示例，由脚本按 yaml 计算核对）

选项字母对应 yaml 中的选项 id。

| 示例 | 关键作答 | 子分 | 结果画像 | 分类器影响 |
|---|---|---|---|---|
| 示例 1：保守新手 | R1=B(≤5%) R2=A R3=B R4=A F1=E F2=B F3=A；E1=A(从未) E2=B E3=A E4=A；T1=A T2=A；K1 对、K2/K3 不确定、K4 对 | risk 9 → 档 2；RC1 封顶 2；经验 2；认知 2 | risk_tolerance 2 / novice / low | short 被 SH0、SH0B、SH0C 封顶；intraday_t 被 IT0B、IT0C 封顶 |
| 示例 2：自称“经验丰富”但从未交易 | E0=C(经验丰富) E1=A E2=D(股票)；R1=D R2=C R3=D R4=C F1=D F2=C F3=A；T1=C T2=B；认知对 3 题 | risk 26 → 档 4；RC3 封顶 4；经验 5 | 4 / novice / medium；标记 CC1 self_report_higher、CC2 answers_inconsistent | short 只被 SH0C 封顶；intraday_t 被 IT0C 封顶；结果页提示核对 |
| 示例 3：上班族中级 | R1=C R2=C R3=C R4=B F1=D F2=C F3=A；E1=C(1–3年) E2=D E3=C E4=B；T1=B T2=C；认知全对 | risk 20 → 档 3；RC2 封顶 3；经验 12 | 3 / intermediate / medium | short 的 requires 全部满足；intraday_t 的画像 requires 满足（IT0 仍看是否持仓） |
| 示例 4：资深但用借款投资 | R1=E R2=D R3=E R4=D F1=C F2=D **F3=C(含借款)**；E1=E E2=E E3=D E4=C；T1=D T2=D；认知全对 | risk 34 → 档 5；RC6 封顶 2；经验 16 | 2 / advanced / high | short 被 SH0 封顶；借款这一项把风险承受压到 2 |
| 示例 5：一票否决 | **R1=A(不能接受任何亏损)** R3=E 其余较积极；E1=D E2=D E3=C E4=C；T1=C T2=C；认知全对 | risk 25（不使用）；RV1 否决 → 1；经验 14 | 1 / advanced / medium；标记 no_loss_tolerance、CC3 | short 被 SH0 封顶；按 §5 第 2 项不提供 fit_ack 越过 |
| 示例 6：缺答 | 同示例 3，但未答 K3 | — | 422 VALIDATION_ERROR，details 列出 K3；不出结果，画像不变 | 不变 |

## 7. 给架构师的待办（契约 v0.2.3 缺口，本任务不改契约）

1. consent key 不一致：契约 `POST /me/consents` 只有 terms / privacy / signal_risk_disclosure；plan 的 consents.kind 是 privacy_policy / sensitive_financial_info / risk_disclosure / email_notification，7.2 又用 signal_risk_disclosure。需要统一一份枚举。
2. `POST /me/risk-assessment` 的响应只有 `{level, assessed_at}`：需要增加 assessment_id、questionnaire_version、三个字段各自的结果和理由（rule id）、flags、expires_at。
3. 需要 `GET /me/risk-assessment/questionnaire`（返回当前已发布问卷，不含分值）和 `GET /me/risk-assessment`（最近一次结果与有效期状态）。
4. `CONSENT_REQUIRED.details.required` 需要允许 `risk_assessment` 值（未测评或测评失效）。
5. `PUT /me/profile` 需要“超过问卷上限”的校验和错误细节（若用户采纳 §5 第 1 项）；画像三字段在未测评时需允许为 null。
6. 请求体需要可选的 `started_at` / `client_duration_s`（CC6），以及 `user.trade_count_12m` 的服务端统计（CC5）。
7. 当前所有题均为单选，`choice` 为字符串即可；若以后加多选题，需要把 choice 扩展为数组。
8. K4 答错的拒收用 VALIDATION_ERROR + `details.reason = "understanding_required"`，需要写进错误码说明。
9. 问卷、法律文档的版本留档表和 consents 字段扩展见 versioning.md §5、§6。
