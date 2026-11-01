状态：已停用（用户 2026-11-02 决定）

# 用户协议、隐私政策、风险揭示、免责声明与风险测评问卷：版本号方案

> 研究员 T-B15 草案，2026-11-01。本文只定**版本与同意记录的机制**。协议、免责声明等文本本身不由研究员起草，§7 只列要点清单，**全部需法律专业人士审阅**。
> 涉及契约 v0.2.3 的缺口列在 §8，本任务不改契约。

## 1. 管理对象（doc_key）

| doc_key（建议） | 内容 | 是否需要用户主动同意 | 当前契约是否有 |
|---|---|---|---|
| terms | 用户协议（含免责声明章节） | 是 | 有 |
| privacy | 隐私政策 | 是 | 有 |
| sensitive_financial_info | 敏感个人信息（持仓、成交）单独同意（plan 7.3） | 是，单独勾选 | 无（plan 有） |
| signal_risk_disclosure | 规则信号（候选信号）风险揭示书 | 是，启用建议类功能前 | 有 |
| site_risk_notice | 全站页脚风险提示文案（plan 7.2 第 8 项） | 否，只展示 | 无 |
| risk_questionnaire | 风险测评问卷（`risk_questionnaire.yaml`） | 否（作答即留档） | 无 |

免责声明作为用户协议的一个章节随 terms 一起版本化；若法务要求单独成文，再增加 doc_key `disclaimer`，规则相同。

## 2. 版本格式

- 所有 doc_key 统一使用**语义化版本 `MAJOR.MINOR.PATCH`**（如 `1.0.0`），正则与契约中 classifier_version 相同；另记一个单调递增的整数 `version_no` 作为内部主键顺序，以及独立的 `effective_at`（生效时间）。
- 选择理由：
  1. 与 classifier_version / version_no 的做法一致，后端只需一套解析与比较逻辑；
  2. “是否需要重新同意 / 重测”可以直接由 MAJOR 是否变化判定，规则确定、可自动化（§3）；
  3. 日期型版本（如 2026-11-01）无法表达变更级别，同一天两次修订也要另加后缀，所以只把日期放在 `effective_at` 字段。
- 契约 `POST /me/consents` 的 `version` 字段传完整语义化版本字符串。

## 3. 何时需要重新同意或重测（确定性规则表）

### 3.1 法律文档（terms / privacy / sensitive_financial_info / signal_risk_disclosure）

发布新版本时，编辑者逐项回答下表；**任一 MAJOR 行为“是”就必须升 MAJOR**，否则任一 MINOR 行为“是”升 MINOR，否则升 PATCH。级别不允许人工下调。

| # | 变更内容 | 级别 | 已同意旧版本的用户 | 依据或理由 |
|---|---|---|---|---|
| L1 | 个人信息的处理目的、处理方式或种类变化（含新增采集字段） | MAJOR | 必须重新同意 | 《个人信息保护法》第十四条第二款 |
| L2 | 新增向其他个人信息处理者提供，或新增/更换受托处理方（如更换大模型服务商） | MAJOR | 必须重新同意 | 第二十三条（提供给其他处理者需单独同意）；受托处理是否必须重新同意**需法务确认**，研究员按保守口径列为 MAJOR |
| L3 | 保存期限延长或删除规则放宽 | MAJOR | 必须重新同意 | 研究员保守口径，需法务确认 |
| L4 | 用户权利义务、责任限制、免责范围、争议解决条款变化 | MAJOR | 必须重新同意 | 需法务确认 |
| L5 | 服务范围或性质变化：从仅本人自用到邀请制他人使用、开始收费、新增建议类功能 | MAJOR | 必须重新同意 | plan Q1：对他人开放前需律师书面意见 |
| L6 | 风险揭示书新增风险类型或改变已揭示风险的含义 | MAJOR | 必须重新同意，期间建议类接口 403 CONSENT_REQUIRED | 契约 ⚖ 接口规则 |
| L7 | 表述澄清但不改变含义、联系方式变更、新增可选功能的说明 | MINOR | 只需告知（站内提示 + 版本说明），无需重新同意 | 第十七条第二款：告知事项变更应告知变更部分 |
| L8 | 错别字、排版、链接修复 | PATCH | 不提示 | — |

自动校验（CI / 发布脚本）：
- 正文 `content_sha256` 变化但版本号未变 → 拒绝发布；
- 版本号变化但 `content_sha256` 未变 → 拒绝发布；
- 新版本号必须大于当前已发布版本；MAJOR 必须附 `change_checklist`（L1–L8 逐项是/否）和 `legal_review_ref`。

重新同意的执行：MAJOR 版本到 `effective_at` 后，`GET /me` 的 `consents[key].version` 的 MAJOR 小于当前 MAJOR 即视为“未同意”。signal_risk_disclosure 未同意 → 建议类接口 403 CONSENT_REQUIRED；terms / privacy 未同意时哪些功能仍可用（至少查看文档、导出数据、注销账户），**需法务确认**（第十六条：不得因个人不同意而拒绝提供服务，提供服务所必需的除外）。

### 3.2 风险测评问卷（risk_questionnaire）

| # | 变更内容 | 级别 | 已有测评结果 |
|---|---|---|---|
| Q1 | `scoring_fingerprint` 变化（题号、选项 id、分值、档位边界、否决、封顶、映射规则、K 题正确答案、一致性校验中 action 不为 flag_only 的规则任一变化） | MAJOR，`forces_retest` 默认 true | 新版本 `effective_at` + 宽限期（yaml validity.grace_days_after_expiry）后失效，需重测 |
| Q2 | 选项文字的含义变化（即使分值不变） | MAJOR | 同 Q1 |
| Q3 | 题干或选项措辞调整但含义不变、提示文案、有效期参数调整 | MINOR | 继续有效；有效期参数只对新测评生效 |
| Q4 | 错别字、排版 | PATCH | 继续有效 |

`scoring_fingerprint` = 对 yaml 中 questions[].id、questions[].options[].id/points/self_report、questions[].correct/must_answer_correctly、scoring 全部、consistency_checks 中 action ≠ flag_only 的条目，按键名排序序列化为 JSON（UTF-8，无多余空白）后取 SHA-256。由发布脚本计算，不手写进 yaml。

`forces_retest` 只有在回放测试证明“全部历史答卷用新旧规则算出的三个字段完全相同”时才能设为 false。

### 3.3 与分类器版本的关系

- 分类器（classifier_version / version_no）和问卷各自独立版本化；分类器只读取画像字段，不读取问卷。
- 问卷 MAJOR 变化不要求分类器升版本；分类器若改变对画像字段的使用（如 SH0 阈值从 3 改成 4），按 horizon_classifier 自己的版本规则升级，不触发重测。
- 追溯链：建议卡片 → 当时的画像版本（user_profiles 一行）→ 该画像引用的 assessment_id → 该次答卷的 questionnaire_version 与 scoring_fingerprint；同时卡片记录 classifier_version。任何一条历史建议都能还原“用的是哪版问卷、哪版分类器”。

## 4. 同意记录字段（consents）

每次同意或撤回都**新增一行**，不更新旧行。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 主键 |
| user_id | uuid | 用户 |
| doc_key | text | §1 中的枚举 |
| doc_version | text | 语义化版本，如 `1.0.0` |
| doc_version_no | int | 对应 legal_documents.version_no |
| content_sha256 | text | 用户当时看到的正文哈希，必须等于 legal_documents 中该版本的哈希，否则拒绝写入 |
| locale | text | 如 zh-CN |
| action | enum | grant / withdraw（撤回不影响撤回前基于同意的处理，第十五条） |
| at | timestamptz | 服务端时间，不信任客户端时间 |
| channel | enum | web / cli / api / admin_bootstrap（站长首个账号初始化） |
| ui_surface | text | 展示位置，如 `/onboarding/consent`、`/advice/enable` |
| presentation | enum | checkbox_unticked / scroll_and_confirm / modal（用于证明是主动勾选而不是默认勾选） |
| ip_hash | text | plan 已有字段，加盐哈希 |
| user_agent_hash | text | 加盐哈希 |
| supersedes_id | uuid null | 被本条取代的上一条同 doc_key 记录 |

测评留档（risk_assessments，只追加）：id、user_id、questionnaire_version、questionnaire_version_no、scoring_fingerprint、answers（原样）、subscores、derived（三个字段与命中规则 id）、flags、started_at（可空）、submitted_at、client_duration_s（可空）、expires_at、status（valid / expired / superseded，由查询时计算或追加状态事件，不改原行）、profile_version_id（用户确认后写入的画像版本，可空）、channel。

## 5. 旧版本不可变归档

- 表 `legal_documents`：doc_key、version、version_no、title、content_md（全文）、content_sha256、locale、change_level、change_checklist、changelog、legal_review_ref、effective_at、published_at、published_by、status（draft / published / retired）。
- 状态为 published 后，正文和哈希**只允许插入不允许更新或删除**（数据库触发器拒绝 UPDATE/DELETE，与 plan 中 strategy_versions 的做法相同）；retired 只追加状态事件。
- 问卷同样入库：`questionnaires`（questionnaire_key、version、version_no、yaml 原文、yaml_sha256、scoring_fingerprint、forces_retest、effective_at、status），规则相同。
- 仓库中保留每个已发布版本的原文文件（如 `compliance/archive/risk_questionnaire-1.0.0.yaml`），发布脚本校验库内哈希与文件一致。
- 用户随时可以在设置页查看自己同意过的每个版本全文。
- 用户注销（`DELETE /me`，plan：30 天内物理删除，审计日志保留脱敏记录）后，consents 和 risk_assessments 是删除还是脱敏保留、保留多久，**需法务决定**。办法第三十二条“不少于 20 年”的保存义务针对证券期货经营机构，是否适用于本工具需法务判断。

## 6. 发布流程

1. 草稿（status draft）→ 填 change_checklist，脚本判定级别并计算哈希 / 指纹；
2. MAJOR 版本附法律审阅记录（legal_review_ref）后才能 published；
3. published 时写入 effective_at（MAJOR 建议至少提前 7 天公告，**初值，需用户/法务确认**）；
4. 到 effective_at 后按 §3 判定哪些用户需要重新同意或重测。

## 7. 用户协议、免责声明、风险揭示、隐私政策：要点清单（需法律专业人士审阅）

以下只是“文本里应当覆盖什么”的清单，**不是条文草稿，全部需法律专业人士审阅**。

**用户协议 / 免责声明**（需法律专业人士审阅）
- [ ] 服务性质：个人投资研究辅助工具，非持牌证券投资咨询机构，不代客下单，不接触资金，不提供个股推荐
- [ ] 服务范围：当前为邀请制、封闭、免费内测；在取得数据授权和律师书面意见前仅限站长本人使用（plan Q1、vision）
- [ ] 规则信号（候选信号）、模拟跟踪、回测的含义：基于用户启用的规则对公开数据计算，历史表现不代表未来，不构成投资建议
- [ ] 用户自主决策、自担风险；交易在用户自己的券商完成
- [ ] 数据来源与可能的延迟、错误、中断；第三方数据授权范围
- [ ] 大模型生成内容可能有误，只作辅助解读
- [ ] 账户安全、禁止转借、年满 18 周岁声明
- [ ] 责任限制范围与适用法律、争议解决
- [ ] 协议变更规则（与本文 §3.1 一致）与通知方式
- [ ] 终止、注销与数据处理

**规则信号风险揭示书**（需法律专业人士审阅）
- [ ] 股票投资可能亏损本金
- [ ] 规则可能失效；样本内外差异；过拟合
- [ ] T+1、涨跌停、停牌导致无法按信号成交
- [ ] 数据延迟或错误导致信号错误
- [ ] 风险测评结果只用于个人适配，不代表信号或股票适合用户
- [ ] 用户逐条确认的方式与留痕

**隐私政策 / 敏感个人信息单独同意**（需法律专业人士审阅）
- [ ] 收集的字段清单（含持仓、成交、风险测评答卷），以及不收集的字段（身份证号等）
- [ ] 处理目的、方式、保存期限（plan 7.3：llm_calls 90 天、原始文件 365 天等）
- [ ] 受托处理方（如大模型服务商）及发送的数据范围
- [ ] 敏感个人信息的必要性和对个人权益的影响
- [ ] 查阅、复制、更正、删除、撤回同意、注销的方式与时限
- [ ] 变更告知方式（与本文 §3.1 一致）
- [ ] 联系方式

**全站风险提示文案**：沿用 plan 7.2 第 8 项文本，修改按 §3.1 L7/L8 处理；措辞变化**需法律专业人士审阅**。

## 8. 给架构师的待办

1. 统一 consent key 枚举（契约 terms/privacy/signal_risk_disclosure 与 plan consents.kind 不一致），并决定是否增加 sensitive_financial_info、disclaimer。
2. consents 表增加 doc_version_no、content_sha256、action、channel、ui_surface、presentation、user_agent_hash、supersedes_id；`POST /me/consents` 请求体增加 content_sha256（服务端校验）。
3. `GET /me` 的 consents 需要能表达“已同意版本低于当前 MAJOR”（例如增加 `current_version` 与 `needs_reconsent`）。
4. 新增 legal_documents、questionnaires 表及只插入触发器；新增 `GET /legal/{doc_key}`（当前版本）和 `GET /legal/{doc_key}/{version}`（历史版本）。
5. risk_assessments 表字段见 §4；user_profiles 增加 assessment_id 引用。
6. 发布脚本：哈希 / 指纹计算与 §3 的自动校验。
