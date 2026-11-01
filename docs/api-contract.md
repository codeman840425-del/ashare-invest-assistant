# A股个人投资研究与决策助手 · REST 接口契约（MVP v1）

- 作者：架构师；日期：2026-11-01；版本：**v0.2.4**；状态：**已评审修订（T-A01，2026-11-01；v0.2.1 同日小修；v0.2.2 为 T-A02 合入研究员 T006a；v0.2.3 为 T-A03 处理前端 T-F01 遗留 21 条并同步研究员 T006b；v0.2.4 为 T-A05 合入研究员 T-B15 合规文书与问卷、前端 T-F02 评审 D1–D7）；本契约是唯一事实来源**——plan.md、原型、后端 schema、测试夹具与本文不一致时，以本文为准并修改对方
- 配套：[`plan.md`](./plan.md)（架构方案）。本契约优先于代码：FastAPI 生成的 `openapi.json` 与本文不一致时**改代码**。
- **示例值全部虚构**：代码用 `600000.SH / 000001.SZ`，ID 用 `00000000-0000-4000-8000-0000000000xx`，金额为随意整数；不含任何真实账户、股东代码、姓名、金额或委托/成交编号。证券简称一律用“示例银行”“演示电子”这类虚构名称。

---

## 0. 变更记录

### v0.2.4（2026-11-01，T-A05；合入研究员 T-B15 的 `docs/strategies/compliance/`（问卷、文书版本规则）与前端评审 T-F02 §4 D1–D7；**含不兼容变更**：注册 `agreements` 的 `risk_disclosure` 改为 `signal_risk_disclosure`，`POST /me/consents` 必须带 `content_sha256`，`/meta/registration` 不再返回 `doc_versions`，`Me.risk_assessment` 结构改变，`POST /me/risk-assessment` 响应改为 `RiskAssessment` 且返回 201）
> 为什么单独升版本而不并入 v0.2.3：后端尚未同步 v0.2.3，但本次新增 3 张表、8 个端点并改了已发布字段的取值与必填项，不是“只加可选字段”，并入会让 v0.2.3 失去意义。
| # | 项 | 决定 | 后端改动 | 前端改动 |
|---|---|---|---|---|
| 1 | 同意项键名（RQ 待办 1、V 待办 1） | 新枚举 `consent_key` = `terms` `privacy` `signal_risk_disclosure` `sensitive_financial_info`；`legal_doc_key` = `consent_key` + `site_risk_notice`（只展示，不需同意）。免责声明并入 `terms`，不单列。`email_notification` 只在库里，不出现在契约 | 新迁移改 `consents.kind` CHECK 并改写旧值（plan 3.3） | 用 `consent_key` |
| 2 | 注册 `agreements`（D2） | 必须包含 `terms`、`privacy`、`signal_risk_disclosure`（原 `risk_disclosure` 作废，T-B03 现实现需改），可另含 `sensitive_financial_info`；其他值 → 400。`apply_note` ≤ 200（原 ≤ 500）；`display_name` 1–32；保留用户名 → 400 | 改校验 | 注册页勾选项 |
| 3 | 文书版本来源（V 待办 4） | 当前版本来自新表 `legal_documents`（只插入），取代 v0.2.3 #26 的 `config/auth.yaml consents.doc_versions`；无已发布版本时为 `"unversioned"`，只允许 `closed` 模式。新增 `GET /meta/consent-docs`、`GET /legal/{doc_key}`、`GET /legal/{doc_key}/versions`、`GET /legal/{doc_key}/{version}`（D4） | 建表 + 触发器 + 发布脚本 + 端点；删 auth.yaml 的 `consents` 段 | 同意弹窗从 `/meta/consent-docs` 取版本和链接 |
| 4 | `POST /me/consents`（V 待办 2） | 请求体加 `content_sha256`、`action`（`grant`/`withdraw`，默认 grant）、`ui_surface`、`presentation: consent_presentation`；`version`、`content_sha256` 与当前版本不符 → 400；服务端记录 channel、IP/UA 哈希、时间 | consents 扩列（plan 3.3） | 提交时带哈希 |
| 5 | `Me.consents`（V 待办 3） | 每个 `consent_key` 都有一项：`{version \| null, accepted_at \| null, current_version, needs_reconsent}`；`needs_reconsent` 按 versioning.md §2 判定（MAJOR 变化或已撤回；`"unversioned"` 视为 MAJOR 0） | 计算 | 据此弹出重新同意 |
| 6 | 风险测评端点（RQ 待办 2、3、6、7、8，D2、D4） | 新增 `GET /me/risk-assessment/questionnaire`（不含分值）、`GET /me/risk-assessment`（最近一次 + 状态）、`GET /me/risk-assessments`（历史）；`POST /me/risk-assessment` 请求体加 `questionnaire_version`（不符 → 409 `VERSION_CONFLICT`）、可选 `started_at`、`client_duration_s`；`choice` 暂为 string（以后有多选再改数组）；K4 答错 → 400 `details.reason="understanding_required"`；24 小时内超过 3 次 → 429；响应 `201 RiskAssessment`。`trade_count_12m` 由服务端从成交记录算，不由客户端提交 | 按 `risk_questionnaire.yaml` 实现计分；新表 `questionnaires`、`risk_assessments`（只插入） | `/onboarding` 测评页 |
| 7 | 画像与测评（RQ 待办 5） | 测评只给出建议值，用户确认后 `PUT /me/profile`（带 `assessment_id`）写入新画像版本；`risk_tolerance`、`experience`、`effort` 可为 null（未测评）；**【待用户确认】** 超过测评上限 → 400 `issue: exceeds_assessment`、`max_allowed`（plan 第 9 节问题 38）。无画像 → `GET` 404；`max_single_position_pct` 5–50、最多 2 位小数（D2） | 校验 | 画像页显示上限 |
| 8 | `CONSENT_REQUIRED.required`（RQ 待办 4） | 取值为 `consent_key` 或 `"risk_assessment"`（没有有效测评，含过期超过宽限期） | 门槛判定 | 按 `required` 跳转 `/onboarding` |
| 9 | `STRATEGY_FIT_ACK_REQUIRED.details` | 加 `ack_allowed: boolean`、`blocking_rule_ids: string[]`；**【待用户确认】**（问题 39）`no_loss_tolerance` 用户的 short/intraday_t、HG1–HG6 与 `data_missing` 封顶 `ack_allowed=false` | 判定 | 不可确认时不显示确认按钮 |
| 10 | `DimensionCell` 笔误（D1） | `exit_hits`、`exit_total` 与 `rules_*` 属于同一对象（v0.2.3 文字中多了一个 `}`），结构不变 | — | 按同一对象解析 |
| 11 | 导入提示的处理选项（D3） | §4.1 新增“处理选项”表，逐码给出 `resolution_choices`（第一个为默认）与覆盖类选项；resolve 只要求 `resolution_choices` 非空，不限 `needs_action`；覆盖类 `reason` 必填（≤ 200） | 按表生成 | 按表渲染 |
| 12 | 管理端用户与成交结构（D5） | 定义 `AdminUser`、`Trade`、`TradeCreate`、`ImportBatchSummary`；新增 `POST /trades/{id}/void`；PATCH `/admin/users/{id}` 在 `rejected`、`disabled`、`disabled→approved` 时 `reason` 必填 | 按结构返回 | 按结构渲染 |
| 13 | CSRF 与敏感信息门槛（D6） | CSRF 为双提交，以 Cookie 为准；`sensitive_financial_info` 门槛改为 `POST /imports`、`POST /trades`（`POST /accounts` 不再要求，修正 v0.2.3 #26） | 改门槛范围 | — |
| 14 | `/portfolio?account_id=`（D7） | `account_id` 可选，不传时合并全部账户 | 加参数 | 账户切换 |
| 15 | 文书与问卷发布（V 待办 4–6） | 发布脚本校验哈希、版本号递增、变更级别与清单一致、MAJOR 需 `review_ref`；接口不提供发布或修改文书的写接口 | CLI（T-B15） | — |
| — | `/meta/enums.version` | `"v0.2.3"` → `"v0.2.4"`；新增枚举 `consent_key`、`legal_doc_key`、`consent_presentation`、`assessment_status` | 改常量 | `CONTRACT_VERSION`、契约测试 |

### v0.2.3（2026-11-01，T-A03；处理前端 T-F01 §9 遗留 21 条，同步研究员 T006b 与用户拍板；**含一处不兼容类型变更**：`Evidence.provider` 改用 `data_provider`，删除 `local`）
| # | 项 | 决定 | 后端改动 | 前端改动 |
|---|---|---|---|---|
| 19 | `/horizon-assessments` 证据 | 响应加 `snapshot_id` 与 `evidence: Evidence[]`；`reasons[].evidence_ids` **只在本响应的 `evidence[]` 内解析**（同 `Suggestion` 的信封规则），不得借用建议卡的证据 | 加字段；契约测试检查可解析 | 改为从本响应解析，删除借用 `sg.evidence` 的逻辑 |
| 20 | 纯离场策略（exit-only）在矩阵中的口径 | 见 §5.2「纯离场策略」：只对**持有中**证券求值；`DimensionCell` 加 `exit_hits`/`exit_total`（只统计 role ∈ {weakening, exit}），`rules_passed/rules_total` 定义不变（仍为 0/0）；单元格 `view` 由离场规则派生；计入行级 `divergent`；从不给出 `entry_ok`/`buy`/`add` | 派生逻辑与校验 | 单元格显示“离场 x/y”，不再显示“—” |
| 21 | `classifier_version` 与 `inputs_missing` | `classifier_version` 为语义化版本字符串，匹配 `^(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)$`（如 `"1.1.0"`）；`inputs_missing` 为 **feature_catalog 键**（`f.*`）数组，去重、升序，**永不为 null**，无缺失时为 `[]`；新增 `caps[]` 给出“哪个周期因什么被封顶” | 加 `caps`；分类器 v1.1.0（问题 37 方案 A） | 按 `caps[]` 逐周期提示 |
| 1 | `Evidence.provider` | 统一为 `data_provider` 枚举（`mairui` `user_import` `user_input` `system`）；**删除 `local`** | 用枚举 | 已按 §3 实现；展示层对未知值兜底 |
| 2 | 日报路径 | API 只有 `/daily-reports`、`/daily-reports/{date}`；前端页面路由同名，`/reports`、`/reports/:date` 仅作重定向（plan 2.4 已改） | 无 | 无（已实现） |
| 3 | `DailyReport.stocks[]` | 加 `close`、`change_pct`、`data_status`、`max_risk_level`（均可为 null，`data_status` 除外） | 加字段 | 加列 |
| 4 | 现金字段 | **两个名字、两个含义，都保留**：`cash` = 由交割单与资金流水重建的**现金余额**（对应 plan 3.5A `cash_balance`），用于日报、草案上下文；`cash_available` = **可用资金**，取最近一次导入的券商资金快照的“可用”（`broker_position_snapshots.cash_available`），没有快照时等于 `cash`，只出现在 `/terminal.account` | 按定义计算 | 标签区分“现金余额”“可用资金” |
| 5 | `TerminalRow` 时效 | 加 `data_as_of: string(datetime) \| null`（该行行情与建议中较旧者的数据时点；完全无数据为 null） | 加字段 | `DataStatusTag` 改读此字段 |
| 6 | 图表标记 | V1 **不设专用端点**：日 K 标记取 `/candidate-signals?security_code=`（时点 = `data_as_of` 所在交易日），分时标记取 `/signals?security_code=&since=`；**必须带 `security_code`** | 两个接口支持该过滤 | 带 `security_code` 请求 |
| 7 | plan 前端版本 | 已按问题 34 定为 React 19 + antd 6；plan 中已无 React 18 / AntD 5 的残留（只剩问题 34 的历史说明） | 无 | 无 |
| 8 | `Bar.t` 与 `volume` 单位 | 维持【待 T003/T-B05】，不阻塞；口径定后只改说明不改字段 | T003 | 无 |
| 9 | `/market/overview` | 定义最小结构，见 §7.3 | 实现 | 可接入 |
| 10 | `CandidateSignal` | 给出正式结构与可空性，见 §7.6 | 按结构实现 | 对齐类型 |
| 11 | `divergent` 口径 | 行级：该维度单元格中**同时存在** `bullish` 与 `bearish`（`neutral`/`unknown` 不参与）；整体 `consensus.status`：0 个策略 `none`，1 个 `single`，≥ 2 个且 `(action, t_leg)` 全部相同 `unanimous`，否则 `divergent` | 实现 | 对齐 |
| 12 | `/today` mock | 契约无改动；前端补 mock | 无 | 补 mock |
| 13 | 通知路由 | `target.route` 由服务端生成，前端直接跳转；格式表见 §5.1 `Notification` | 实现 | 用 `route` |
| 14 | 标记已读 | `POST /notifications/{id}/read` 与 `POST /notifications/read-all` 均返回 **`204 No Content`**，幂等（已读再标不改 `read_at`）；客户端随后刷新 `unread-count` | 实现 | 无（mock 已是 204） |
| 15 | `RuleRef.dimension` | 所有 role（含 filter/veto/counter/invalidation）**必填、非空**；取规则规格中的 `dimension`（_template.md §2）；系统组件按 catalog 第 2 节归属（G-01 → `technical`，G-02 → `sector_market`，N-01 → `news`，H-01 → 规则自身声明） | 导入校验 | 无 |
| 16 | `/terminal.trade_date` | 加 `trade_date: string(date)`（行情所属交易日；非交易日为最近一个交易日） | 加字段 | 用它代替从行情时间截取 |
| 17 | 批量查不可执行原因 | `GET /non-executable-reasons` 加 `signal_ids=`（逗号分隔，≤ 100）与 `suggestion_id=` 过滤；带这两个参数时不分页 | 实现 | 按卡批量取，删除“取全部再过滤” |
| 18 | 建议卡“当前” | 不新增 `current`；`status=active` 即当前卡，同一用户同一证券**至多 1 张** `active` | 加唯一约束 | 无 |
| — | T006b 交易规则（plan 2.13、6.1） | 风险警示 50 万股/日买入上限只适用主板与创业板，不适用科创板；“只能限价申报”只适用沪市；沪 3.3.17、深 3.3.19 涨跌停价舍入已核实（含两条边界规则）；2023-04-10 之前不建模【已定】 | 改 `config/market_rules.yaml`（后端负责） | 草案/通知文案按交易所区分 |
| — | 问题 37【已定 A】 | novice（或画像未填）用户的 `short` 分数封顶 59，用户可用 `fit_ack` 覆盖；`intraday_t` 同样封顶 59（规则 IT0C，编排者默认，用户可否决） | `horizon_classifier.yaml` 发 1.1.0 | `caps[]` 展示 |
| 22 | 请求体过大（同日补充，回应 review-T-B02） | 应用层超限（导入文件超过 `imports.max_file_bytes` 等，键见 plan 6.1 `config/imports.yaml`；T-A05 统一键名）仍按 `422 IMPORT_FILE_ERRORS` + `IMPORT_*` 码返回、不创建批次；新增 `413 PAYLOAD_TOO_LARGE` 只用于**请求体超过网关/框架上限**（nginx `client_max_body_size`，须略大于应用上限），响应仍是 §4 错误信封（nginx 用 `error_page 413` 返回 JSON，`request_id` 照常） | 框架层兜底映射；运维配 nginx JSON 错误页 | 按通用错误处理，提示“文件过大” |
| 23 | `IT0C` 与原因码（同日补充，T-A05） | `SH0C`/`IT0C` 是周期分类器规则 ID，只出现在 `HorizonCap.rule_id`（`kind: "requires"`），**不是** `reason_code`，不进 `/meta/enums`；§6.1 原因码不变（仍 23 个） | 无（现实现即如此） | 按 `rule_id` 展示封顶说明，不查原因码文案 |
| 24 | 用户名长度（同日补充，T-A05） | `username` 由 3–32 改为 **4–32**，`^[a-z0-9_]{4,32}$`（输入转小写），保留名 → `400 VALIDATION_ERROR`；与 plan 3.3/3.6 一致 | 无（T-B03 已按 4–32） | 注册表单校验改 4 |
| 25 | 会话（同日补充，T-A05） | 空闲 7 天滑动 + 绝对 30 天；无“记住我”；登录与改密轮换 `sid` 和 CSRF 令牌（§1.3）；键见 plan 6.1 `config/auth.yaml` | 加绝对过期与改密轮换 | 改密 204 后从 `csrf_token` Cookie 重读令牌 |
| 26 | 同意书（同日补充，T-A05） | `POST /me/consents` 的 `key` 增加 `sensitive_financial_info`；`version` 必须等于服务端当前版本（`GET /meta/registration` 返回 `doc_versions`），否则 `400 VALIDATION_ERROR`；`POST /accounts`、`POST /imports` 及手工录入成交/持仓的写接口要求已同意 `sensitive_financial_info`（plan 7.3，个保法第 28 条单独同意），否则 `403 CONSENT_REQUIRED` | 校验版本、加 key 与门槛 | 导入前弹单独同意；提交 `doc_versions` 中的版本 （**v0.2.4 改**：版本来源改为 `legal_documents` 与 `/meta/consent-docs`，门槛范围改为 `POST /imports`、`POST /trades`）|
| 27 | 邀请码（同日补充，T-A05） | 注册体增加 `apply_note`（`invite` 模式必填）；邀请码错误/过期/已用/已吊销统一为 `400 VALIDATION_ERROR {fields:[{field:"invite_code", issue:"invalid"}]}`；新增 `/admin/invites`（§7.9）。邀请功能（T-B03c）完成前 `invite` 模式按 `closed` 处理，返回 `503 REGISTRATION_CLOSED` | T-B03c 实现 | 注册页加申请说明；管理端邀请码页 |
| — | `/meta/enums.version` | `"v0.2.2"` → `"v0.2.3"` | 改常量 | `CONTRACT_VERSION`、契约测试 |

### v0.2.2（2026-11-01，T-A02；合入研究员 T006a：周期分类器 v1、规则语义、交易规则核实；不改字段名，只放宽一处类型、补两处字段与说明）
| 项 | 决定 | 后端改动 |
|---|---|---|
| `RuleRef.passed` | 类型 `boolean` → **`boolean \| null`**。语义统一为“**该规则表达式求值为真**”：entry/filter/hold 为真 = 条件满足；veto/counter/invalidation/weakening/exit 为真 = **命中**。数据缺失无法求值 → `null`；未持有时 `ctx.*`/`plan.*` 规则不求值、**不出现在** `rule_refs`/`dimension_views[].rules` 中（plan 2.5.14 H⑮） | 求值器输出三值；Pydantic 类型改 `bool \| None`；前端渲染三态（满足/命中、不满足、无法判断） |
| `rule_ids_passed`（夹具 `expected.json`）与 P1b | `rule_ids_passed` = `passed == true` 的规则 ID（按 `rules[]` 顺序），`null` 不列入。`POST /plan-drafts` 的 `PLAN_REQUIRES_EXPLAINABLE_SIGNAL` 判定改为：信号中**没有任何 role ∈ {entry, exit, weakening} 且 passed = true 的 RuleRef** | 改判定条件；契约测试补“只有 veto 命中 / 只有 null”两例 |
| `DimensionCell.rules_passed/rules_total`、`key_evidence_ids` | 只统计 role ∈ {entry, filter, hold} 的规则（命中的 veto/counter 是反向信息，另见 `counter_evidence`、`gate_results`） | 改派生逻辑与一致性测试 |
| `/horizon-assessments` | `scores` **必含四个周期**，每个都是 int 0–100、**不为 null**（数据缺失按封顶处理，见 plan 6.1 `horizon_classifier.yaml` `data_missing_cap`）；`reasons[]` 元素为 `TextWithEvidence & {horizon: horizon, polarity: "for" \| "against"}`；新增 `inputs_missing: string[]`（缺失的 `f.*` 输入键，用来区分“真 0 分”与“缺数据被封顶”，回应 horizon_classifier.md §8 缺口 2；不再为此让 `scores` 允许 null）。重算触发新增 `position_open_close` | 改响应模型；分类器按规则 v1 输出 |
| 卡片 `refs[]` 与列表项 `ref` | 澄清：`/strategy-cards/{id}` 的 `refs[].ref` 是**出处编号**（如 `R12`），与卡片 `entry[]` 等列表项中引用规则的 `ref: <rule_id>` 不同义；两者都保留，不改名（plan 2.5.14 H⑬） | 导入器按位置区分；无接口字段变化 |
| `validation_summary.oos_result` | 确认 `string \| null`（plan 原写的结构化对象作废，以本契约为准） | 无 |
| G-01 与原因码 `LIMIT_LOCKED` 等 | 运行时 `gate_tradability` 中有对应原因码的检查项（停牌、一字涨停、ST/退市整理、新股）只写入 `gate_results` 并产出不可执行原因，**不把 `state` 改为 `vetoed`**；低价股仍为 veto（plan 2.5.11、2.5.14 H⑯） | 改闸门落点；T-T17 补“一字涨停 → `entry_ok` + `LIMIT_LOCKED`，打开后自动重评” |
| `/reconciliation` 成本口径 | 我方摊薄成本**计入分红**（现金红利冲减、股息红利税补缴计入，与通达信一致，plan 第 9 节问题 19 已定）；每次导入确认后与券商“成本价”对账 | 成本重建纳入 `account_events` 的红利与税费 |
| `/meta/enums.version` | `"v0.2.1"` → `"v0.2.2"` | 改常量 |

### v0.2.1（2026-11-01，T-A01 小修；不改任何字段名和枚举）
| 项 | 决定 | 后端改动 |
|---|---|---|
| `/admin/*` 访问控制自相矛盾（v0.2 的 §1.3、§9 写 403，§4、§7.9、变更记录写 404） | **统一为 404**（隐藏存在性）：凡不是“已登录且 `role=admin`”的请求（含未登录、普通用户、账号非 `approved`）访问任何 `/admin/*` 路径（含不存在的子路径、用错方法），一律 `404 NOT_FOUND`，响应体与普通不存在路径相同，不带 `Allow` 头。该判断先于 CSRF、同意、405、422 等其他校验。`403 FORBIDDEN` 保留在错误码表中，但 `/admin/*` 不再使用 | 管理端依赖从 403 改为 404；未登录访问 `/admin/*` 从 401 改为 404 |
| LLM 供应商 key 来源（配合 plan 2.7.1 DeepSeek 核实） | `/admin/llm/providers` 响应增加 `api_key_source: "env" \| "db"`；DeepSeek 的 key 只从环境变量 `DEEPSEEK_API_KEY` 读取（`api_key_source:"env"`），接口不可写入，PATCH 带 `api_key` → `422 VALIDATION_ERROR`；`api_key_set` 只表示进程内该值非空，任何接口都不返回 key 或其片段 | providers 序列化加字段 |
| `/meta/enums.version` | `"v0.2"` → `"v0.2.1"` | 改常量 |

### v0.2（2026-11-01，T-A01；处理前端原型评审 T-F00 §6 的 12 项与 T006 契约问题）
**改名 / 改口径**（客户端和后端须同步修改；原型 `src/types/contract.ts` 按此调整）
| 旧 | 新 | 说明 |
|---|---|---|
| 规则结果 `pass` | `passed` | 所有规则结果（`RuleRef`、`dimension_views[].rules[]`）统一 |
| `evidence_id`（单数） | `evidence_ids: string[]`；证据主键 `id` | 全文禁止出现 `evidence_id`；证据 `id` 在所属文档内唯一，全局用 `(snapshot_id, id)` 定位 |
| `invalidation: [{expr, evidence_id}]` | `TextWithEvidence{text, expr, evidence_ids}` | `reasons`、`counter_evidence`、`invalidation` 同构 |
| Suggestion 维度分 `score: 0.83` | `score: 0–100 整数`（未知为 `null`） | 对外所有 `score` 都是 0–100 整数；引擎内部 0–1 不外露；`confidence.value` 仍为 0–1 |
| `strategies[].stop_loss` / `take_profit`（平铺） | `strategies[].stops: Stops{stop_loss, take_profit, time_stop_days}` | 与 `CandidateSignal.stops`、`PlanDraft.stops` 统一 |
| `dimension_matrix[].cells[]{view}` | `DimensionCell{strategy_key, strategy_version_id, view, score, key_evidence_ids, rules_passed, rules_total}`，行上加 `divergent`（v0.2.3 起同一对象另有 `exit_hits, exit_total`，见 v0.2.3 #20） | §5.2 |
| `import_status`: `preview_ready` / `confirmed` | `previewed` / `committed`；新增 `discarded` | 6.0 状态机已更新 |
| 导入预览行 `status: ok\|error\|duplicate`、`error_code` | `status: import_row_status`、`findings: ImportFinding[]`、`dedup_status` | §4.1、§7.2 |
| `409 IMPORT_DUPLICATE_FILE` | 文件级 **warning** `IMPORT_DUPLICATE_FILE`（不再是 HTTP 错误） | 同一文件可重新预览，确认时按行去重 |
| `422 IMPORT_UNRECOGNIZED_FORMAT`、`422 IMPORT_ROW_COLUMN_MISMATCH` | `422 IMPORT_FILE_ERRORS{findings}`；`IMPORT_UNRECOGNIZED_FORMAT`、`IMPORT_ROW_COLUMN_MISMATCH` 改为提示码（名称不变） | 提示码全表见 §4.1 |
| `/imports/{id}` 的 `parser` | `parser_id`（`tdx_trades_v1` / `tdx_positions_v1`；旧名 `fmt_a_*` 作为别名接受） | plan 3.5A |
| `Stat`：n < 20 标 `small_sample` | n < 30 标 `small_sample`；n < 5 `value=null` | 展示阈值；降权门槛 n ≥ 20 不变 |
| SSE `signal{signal_event_id, security_code, kind, at}`（`kind` 未定义） | `SignalEvent`（§5.1），`kind: signal_kind`，加 `name`、`message` | 原型的 `quote_flip` → `rule_flip`，`text` → `message` |
| SSE `notification{id, kind, severity, title}` | 完整 `Notification`（§5.1） | 通知带 `created_at`、`read_at`、跳转目标 `target` |
| 原型中的 `/reports/daily/{date}` | 以 `/daily-reports/{date}` 为准 | 路径不变，补了结构 |
| `CandidateSignal.gate_results[].gate` | 说明：这是**运行时闸门名**（如 `gate_tradability`），不是 `gate` 枚举（G1–G7 晋级门禁） | 字段不改，只澄清 |

**新增**
- 枚举：`strategy_eval_state`、`executability_status`、`signal_kind`、`reconciliation_status`、`reconciliation_item_kind`、`card_risk_level`、`import_severity`、`import_scope`、`import_row_status`、`dedup_status`、`registration_mode`、`market_session`、`notification_target_type`、`bar_freq`、`bar_adjust`。
- 共享对象：`Stops`、`DimensionCell`、`StrategyConclusion`、`Suggestion`、`SuggestionSummary`、`Bar`、`WatchlistItem`、`Notification`、`SignalEvent`、`ImportFinding`、`DailyReport`、`TerminalRow`。
- 约定：凡含 `security_code` 的对象都同时带 `name`（证券简称）。
- 端点：`GET /terminal`（终端一屏聚合）、`GET /today` 的完整结构（两者都支持弱 ETag / 304）、`GET /meta/registration`、`PUT /imports/{id}/options`、`POST /imports/{id}/findings/{finding_id}/resolve`、`POST /imports/{id}/discard`、`GET /imports/{id}/errors.csv`、`PATCH /watchlist/{security_code}`；`/securities/{code}/bars` 补参数 `adjust`、`before`、`limit` 与响应结构；`/strategy-cards/{id}` 补 `ref`、`validation_summary`、`risk_level`；模板版本补 `internal_check`。
- 错误码：`422 IMPORT_FILE_ERRORS`、`422 IMPORT_NOTHING_TO_COMMIT`、`422 IMPORT_WARNINGS_UNACKNOWLEDGED`；§4.1 导入提示码全表（46 个）。
- 前端约束：终端实时表格只用 AG Grid **Community**（MIT），禁止依赖 `ag-grid-enterprise`（CI 检查，§9）。

**v0.2 补充（同日，处理后端骨架报告 T-B01 §4 的问题）**
| 项 | 决定 | 后端改动 |
|---|---|---|
| 大小写冲突 | §1 新增“大小写”规则：JSON 键与普通枚举值 `snake_case`；**码类取值**（`error.code`、`reason_code`、`IMPORT_*` 提示码、`gate` 的 `G1`–`G7`）用 `UPPER_SNAKE`/大写。`/meta/enums` 现状即符合 | 无 |
| `DATA_STALE` 同名 | 原因码保留 `DATA_STALE`；HTTP 错误码 `503 DATA_STALE` **改名为 `503 FRESH_DATA_REQUIRED`**。三类码（错误码、原因码、导入提示码）命名空间互不重名，CI 检查 | 改 `ErrorCode` |
| 405 | 新增 `405 METHOD_NOT_ALLOWED`（带 `Allow` 头，`details: {allowed: [...]}`）；例外：非管理员访问 `/admin/*` 时仍返回 `404 NOT_FOUND` | 改 405 映射（原为 404） |
| `/health` | 拆为 `GET /health/live`（存活，恒 200）与 `GET /health/ready`（就绪）；`GET /health` = `ready` 的别名。db 或 redis 失败 → **503** + `status: "down"`；只有 ingest 异常 → **200** + `status: "degraded"`。字段见 §7.10 | 加 live、503、`checked_at`、`version` |
| ingest 健康来源 | **确认** Redis 心跳 + 120 秒判 stale；键 `ingest:heartbeat`，值改为 JSON（含 `ts`），`ingest:paused` 存在即暂停。见 §7.10 | 心跳解析从“Unix 秒”改为 JSON 的 `ts` |
| `/meta/enums` 外层结构 | 采用后端实现并补 `version`、`import_codes`：见 §7.10 | 加两个键 |
| `PENDING_T_A01` 的 21 个枚举 | 逐项核对：`epistemic_type` `horizon` `dimension` `dimension_view` `rule_role` `action` `t_leg` `confidence_level` `consensus_status` `suggestion_origin` `suggestion_status` `risk_control` `risk_level` `lifecycle` `candidate_signal_state` `reason_code` `reason_status` `check_on` `release_kind` `plan_draft_status` `suggestion_user_action` 的**取值 v0.2 均不变**，可以解除 PENDING 标记。v0.2 真正改值的只有 `import_status` | 解除标记；按上表新增枚举 |
| §3 未收录的枚举 | 新增 `health_status`、`component_health`、`ingest_health`、`gap_reason`、`data_provider`、`source_kind`；`data_status` 与 `gate` 改为列出全部取值 | 加入 `CONTRACT_ENUMS` |

### v0.1（2026-11-01）
- 初稿。

---

## 1. 通用约定
| 项 | 约定 |
|---|---|
| 基础路径 | `/api/v1`；JSON，`Content-Type: application/json; charset=utf-8`（文件上传为 `multipart/form-data`；SSE 为 `text/event-stream`） |
| 命名与大小写 | **JSON 键**一律 `snake_case`。**枚举取值**分两类：① 普通枚举值小写 `snake_case`（如 `entry_ok`、`uptrend`），少数取值本身是固定记号的除外（`bar_freq` 的 `1m`/`d`/`w`）；② **码类取值**用大写 `UPPER_SNAKE`：`error.code`（§4）、`reason_code`（§6.1）、导入提示码 `IMPORT_*`（§4.1）、晋级门禁 `gate`（`G1`–`G7`），以及仅用于展示的风控编号 `RC1`–`RC6`。判断方法：取值是“码”（会出现在日志、文档、CI 检查里被检索）则大写，是“状态/类别”则小写。错误码、原因码、导入提示码三个命名空间**不得重名**（CI 检查，§9） |
| ID | UUID v4 字符串（`string(uuid)`） |
| 时间 | `string(datetime)`：ISO 8601 含时区，服务端统一输出 `+08:00`；日期 `string(date)` = `YYYY-MM-DD`（交易日按北京时间） |
| 金额/价格/数量/比例 | **十进制字符串** `string(decimal)`，如 `"10.25"`、`"0.1530"`；不用 JSON number，避免浮点误差。百分比字段名以 `_pct` 结尾，值为百分数（`"3.20"` = 3.20%） |
| 分数/置信度数值 | `number`。**所有名为 `score` 的字段都是 0–100 整数**（四舍五入；观点未知时为 `null`）；引擎内部的 0–1 小数不对外。`confidence.value` 为 0–1、两位小数。这些是规则计算结果，不是金额 |
| 证券代码 | `string`：`{6位代码}.{SH\|SZ\|BJ}`；指数同格式（如 `000300.SH`） |
| 证券简称 | **凡含 `security_code` 的对象都同时带 `name: string`**（证券简称）。不可变对象（建议、日报、信号）里的 `name` 是生成当时的简称，可能与当前简称不同；代码查不到简称时为代码本身，不为 `null` |
| 条件请求 | 标注“ETag”的 `GET` 返回弱 ETag（`W/"…"`）；客户端带 `If-None-Match` 且内容未变 → `304`（无响应体）。头 `Cache-Control: private, no-cache` |
| 可空 | 标记为 `T \| null` 的字段总是出现，值可为 `null`；未标记的字段必有值 |
| 版本 | 破坏性变更走 `/api/v2`；新增字段不算破坏性，客户端须忽略未知字段 |
| 请求追踪 | 响应头 `X-Request-Id`；客户端可传入同名头 |
| 幂等 | 创建类 `POST` 支持 `Idempotency-Key` 头（24 小时内同键同体返回首次结果，同键异体 → `409 IDEMPOTENCY_CONFLICT`） |

### 1.1 数据状态（凡含行情/因子/建议的响应都带）
```json
{"data_status": "fresh", "data_as_of": "2026-11-02T10:31:00+08:00", "gaps": [{"key": "news", "reason": "no_source", "message": "本产品不提供新闻资讯"}]}
```
- `data_status: "fresh" | "stale" | "pending" | "partial" | "unavailable"`：`stale`=超过刷新间隔 ×2 未更新（0A.3）；`pending`=已投递按需拉取任务；`partial`=部分维度缺数据；`unavailable`=上游不可用。
- `gaps[]: {key: string, reason: "no_source"|"not_yet_published"|"upstream_error"|"quota_deferred"|"user_input_missing", message: string}`。

### 1.2 分页（游标）
- 请求：`?limit=`（默认 50，最大 200）`&cursor=`（不透明字符串）。
- 响应：`{"items": [...], "next_cursor": "string | null"}`；`next_cursor=null` 表示最后一页。排序固定且稳定（默认 `created_at desc, id desc`），各接口另注明。
- 少量小集合接口（枚举、设置）直接返回数组或对象，不分页（注明"不分页"）。

### 1.3 认证与安全
- **会话 Cookie** `sid`：`HttpOnly; Secure; SameSite=Lax; Path=/`；服务端会话存 Redis，空闲 7 天滑动过期、自登录起 30 天绝对过期（均可配置，plan 6.1 `config/auth.yaml` `session.*`）；V1 不提供“记住我”。登录与修改密码时轮换会话（新 `sid` 与新 `csrf_token`，旧会话作废）；改角色、禁用、驳回、管理员重置密码时吊销该用户全部会话。
- **CSRF**：登录成功后响应体与 Cookie `csrf_token`（非 HttpOnly）给出令牌；所有 `POST/PUT/PATCH/DELETE` 必须带头 `X-CSRF-Token`，缺失或不符 → `403 CSRF_FAILED`。响应体 `csrf_token` 与 Cookie 值相同，以 Cookie 为准（双提交：服务端用常数时间比较请求头、Cookie 与会话内令牌，三者须一致）；响应体值只供读不到 Cookie 的客户端兜底（v0.2.4 #13）。
- **权限**：未登录 → `401 AUTH_REQUIRED`；账号非 `approved` → `403 ACCOUNT_NOT_APPROVED`（以上两条均不适用于 `/admin/*`）；`/admin/*`：不是已登录的 `role=admin` 时（含未登录）一律 `404 NOT_FOUND`，与不存在的路径无法区分（不泄露管理端存在性；先于本节其他校验，v0.2.1）。用户只能访问自己的资源，访问他人资源一律 `404 NOT_FOUND`（不泄露存在性）。
- **合规门槛**：建议类接口（标 ⚖：`/today`、`/suggestions*`、`/daily-reports*`、`/signals*`、`/candidate-signals*`、`/plan-drafts*` 的生成与确认、`/stream` 中标 ⚖ 的事件）要求用户有**有效**风险测评（`assessment_status` ∈ {`valid`, `expiring`, `grace`}）且已同意 `signal_risk_disclosure` 的当前版本（`needs_reconsent=false`），否则 `403 CONSENT_REQUIRED`（`details.required` 列出所有缺项，取值为 `consent_key` 或 `"risk_assessment"`，如 `["signal_risk_disclosure", "risk_assessment"]`）。导入和手工录入成交（`POST /imports`、`POST /trades`）要求已单独同意 `sensitive_financial_info`（《个保法》第 28 条，plan 7.3），否则 `403 CONSENT_REQUIRED{required:["sensitive_financial_info"]}`（v0.2.4 #8、#13；`POST /accounts` 不要求）。
- **限速**：超限 `429 RATE_LIMITED`，头 `Retry-After`（秒）。
- 敏感字段一律掩码输出（如 `shareholder_code_masked: "A00****000"` 为格式示意），任何接口都不返回原始股东代码、资金账号或原始上传文件内容。

---

## 2. 统一错误格式
```json
{"error": {"code": "VALIDATION_ERROR", "message": "参数校验失败", "details": {"fields": [{"field": "limit", "issue": "must be <= 200"}]}, "request_id": "req_9f8e7d"}}
```
| 字段 | 类型 | 说明 |
|---|---|---|
| `error.code` | string | 机器可读错误码（第 4 节），稳定 |
| `error.message` | string | 中文可读信息，可变，客户端不得据此判断逻辑 |
| `error.details` | object \| null | 结构化细节，按错误码约定 |
| `error.request_id` | string | 与响应头 `X-Request-Id` 一致 |

---

## 3. 枚举（`GET /meta/enums` 返回同一份，不分页）
| 枚举 | 取值 |
|---|---|
| `account_status` | `pending` `approved` `rejected` `disabled` |
| `role` | `user` `admin` |
| `consent_key` | `terms` `privacy` `signal_risk_disclosure` `sensitive_financial_info`（需用户同意的文书；v0.2.4） |
| `legal_doc_key` | `terms` `privacy` `signal_risk_disclosure` `sensitive_financial_info` `site_risk_notice`（`site_risk_notice` = 全站固定风险揭示，只展示不需同意；v0.2.4） |
| `consent_presentation` | `checkbox_unticked` `scroll_and_confirm` `modal`（同意时的呈现方式，记入 consents；v0.2.4） |
| `assessment_status` | `valid` `expiring`（距到期 ≤ `remind_before_days`）`grace`（已过 `expires_at`、仍在宽限期内）`expired` `superseded`（有更新的一次测评）；服务端按时间计算，不存库（v0.2.4） |
| `epistemic_type` | `fact` `estimate` `hypothesis` `execution` |
| `horizon` | `intraday_t` `short` `swing` `long` |
| `dimension` | `technical` `capital` `fundamental` `sentiment` `sector_market` `news` |
| `dimension_view` | `bullish` `bearish` `neutral` `unknown` |
| `rule_role` | `entry` `hold` `weakening` `exit` `filter` `veto` `counter` `invalidation` |
| `action` | `buy` `add` `hold` `reduce` `sell` `wait` |
| `t_leg` | `sell_first` `buy_first` （仅 `intraday_t`） |
| `confidence_level` | `high` `medium` `low` |
| `consensus_status` | `unanimous` `divergent` `single` `none` |
| `strategy_eval_state` | `entry_ok` `not_triggered` `hold_ok` `weakening` `exit_signal` `vetoed` `insufficient_data`（单个模板对单只证券的评估结果；`not_triggered`=数据完整、无否决、核心入场条件未全部满足 → 映射为 `wait`，不生成候选信号） |
| `executability_status` | `executable` `blocked` `not_applicable`（至少一个候选信号无未解除原因 → `executable`；全部被阻断 → `blocked`；没有候选信号 → `not_applicable`） |
| `suggestion_origin` | `daily_batch` `intraday_event` `manual_refresh` |
| `suggestion_status` | `active` `superseded` `invalidated` `expired` |
| `risk_control` | `stop_take`(RC1) `position_cap`(RC2) `total_exposure`(RC3) `sector_concentration`(RC4) `loss_streak_drawdown`(RC5) `plan_violation`(RC6) |
| `risk_level` | `info` `warning` `critical`（只用于 `RiskFlag.level`） |
| `card_risk_level` | `normal` `high`（L1 卡片的策略风险等级，与 `risk_level` 无关；`high` 的卡片在晋级和展示时附加风险提示） |
| `market_regime` | `uptrend` `range` `downtrend` |
| `signal_kind` | `rule_flip`（某条规则由不满足变满足或反之） `breakout`（突破区间上沿） `breakdown`（跌破区间下沿） `vwap_deviation`（偏离分时均价） `volume_spike`（放量） `limit_up_touch` `limit_down_touch` `limit_open`（涨跌停打开） `invalidation_near`（接近失效条件或止损位） `stop_hit`（触及止损/止盈价位，只提示） `suspended`（停牌/复牌） `data_stale`（行情变旧） |
| `market_session` | `non_trading_day` `pre_open` `call_auction` `morning` `lunch_break` `afternoon` `closing_auction` `closed`（北京时间；按交易日历与板块规则计算） |
| `bar_freq` | `1m` `d` `w` |
| `bar_adjust` | `none` `qfq` `hfq`（`1m` 只支持 `none`） |
| `registration_mode` | `closed`（V1 默认）`invite` `open`（保留，V1 不用） |
| `notification_target_type` | `suggestion` `candidate_signal` `plan_draft` `plan` `daily_report` `import_batch` `reconciliation` `strategy_version` `none` |
| `notification_kind` | `suggestion_change` `invalidation` `daily_report` `alert` `import` `system` `reason_released` `plan_draft_ready` `plan_triggered` `strategy_health` |
| `severity` | `info` `attention` `important` |
| `channel` | `in_app` `email` `wecom_app`（预留） |
| `data_status` | `fresh` `stale` `pending` `partial` `unavailable`（含义见 1.1） |
| `gap_reason` | `no_source` `not_yet_published` `upstream_error` `quota_deferred` `user_input_missing`（`gaps[].reason`，1.1） |
| `data_provider` | `mairui` `user_import` `user_input` `system`（`Evidence.provider`；`system` = 系统计算；v0.2.3 起 `Evidence.provider` 只用此枚举，没有 `local`） |
| `source_kind` | `market_data` `disclosure` `user_input` `system_calc`（证据来源类别，plan 3.1） |
| `trade_side` | `buy` `sell` |
| `import_status` | `uploaded` `parsing` `previewed` `committed` `failed` `discarded` `reverted`（v0.2：`preview_ready`→`previewed`，`confirmed`→`committed`） |
| `import_severity` | `error` `warning` |
| `import_scope` | `file` `row` `field` |
| `import_row_status` | `ok` `warning` `error` `skipped` |
| `dedup_status` | `new` `duplicate_in_db` `duplicate_in_file` `possible_duplicate_of_manual` |
| `reconciliation_status` | `matched` `diff` `not_imported` |
| `reconciliation_item_kind` | `quantity_mismatch` `missing_in_broker` `missing_in_ours` `cost_differs` `cash_gap` `cash_chain_break` |
| `card_completeness` | `draft` `documented` `runnable_candidate` `promoted` `retired` |
| `lifecycle` | `draft` `simulating` `published` `observing` `retired` |
| `instance_status` | `proposed` `active` `paused` `archived` |
| `candidate_signal_state` | `open` `drafted` `blocked` `released` `confirmed` `dismissed` `expired` `invalidated` `superseded` |
| `reason_code` | 见 6.1（23 个） |
| `reason_status` | `active` `released` `obsolete` |
| `check_on` | `tick` `daily_close` `schedule` `holding_change` `cash_update` `import` `plan_change` `user_action` |
| `release_kind` | `expr` `time` `event` `user_action` |
| `plan_draft_status` | `pending` `confirmed` `discarded` `expired` `stale` |
| `plan_origin` | `manual` `plan_draft` |
| `restriction_kind` | `blocklist` `cooling_off` `mute` |
| `suggestion_user_action` | `viewed` `dismissed` `draft_requested` `draft_confirmed` `reason_manually_released` `acted_trade_linked`（没有 `converted_to_plan`） |
| `feature_status` | `declared` `verified_doc` `verified_live` `gap` `deprecated` |
| `gate` | `G1` `G2` `G3` `G4` `G5` `G6` `G7`（plan.md 2.5.13 的晋级门禁；**不同于** `CandidateSignal.gate_results[].gate` 中的运行时闸门名） |
| `llm_task` | `suggestion_rationale` `daily_report_stock` `daily_report_summary` `strategy_divergence` `announcement_title_digest` |
| `health_status` | `ok` `degraded` `down`（`/health/ready` 的 `status`） |
| `component_health` | `ok` `error`（`/health/ready` 的 `db`、`redis`） |
| `ingest_health` | `ok` `stale` `paused` `unknown`（`unknown` = Redis 不可用，无法判断） |

---

## 4. 错误码表
| HTTP | code | 场景 | `details` |
|---|---|---|---|
| 400 | `VALIDATION_ERROR` | 参数/请求体校验失败 | `{fields:[{field, issue}]}` |
| 400 | `INVALID_CURSOR` | 游标无效或过期 | — |
| 401 | `AUTH_REQUIRED` | 未登录或会话过期 | — |
| 401 | `INVALID_CREDENTIALS` | 用户名或密码错误（不区分哪一项） | — |
| 403 | `ACCOUNT_NOT_APPROVED` | 账号待审核/已驳回/已禁用 | `{status}` |
| 403 | `ACCOUNT_LOCKED` | 连续失败临时锁定 | `{retry_after_s}` |
| 403 | `CSRF_FAILED` | CSRF 令牌缺失/不符 | — |
| 403 | `FORBIDDEN` | 角色不足（保留；`/admin/*` 不使用，一律 404，见 §1.3） | — |
| 403 | `CONSENT_REQUIRED` | 缺少必要同意（含需重新同意）或有效风险测评 | `{required:[string]}`（`consent_key` 或 `"risk_assessment"`，v0.2.4） |
| 403 | `ENTITLEMENT_LIMIT_REACHED` | 超出套餐权益上限（自选数、重点关注数、导入次数、LLM 解释次数等） | `{key, limit, current}` |
| 404 | `NOT_FOUND` | 资源不存在或不属于当前用户 | — |
| 405 | `METHOD_NOT_ALLOWED` | 路径存在但方法不支持；响应头 `Allow`。非管理员（含未登录）访问 `/admin/*` 一律按 `404 NOT_FOUND` 返回，不带 `Allow` 头 | `{allowed: string[]}` |
| 413 | `PAYLOAD_TOO_LARGE` | 请求体超过网关/框架上限（v0.2.3 补充）；应用层文件超限仍用 `422 IMPORT_FILE_ERRORS` | `{max_bytes}`（= plan 6.1 `imports.max_request_bytes`；nginx 返回时可省略） |
| 409 | `CONFLICT` | 唯一约束冲突（如用户名已存在） | `{field}` |
| 409 | `IDEMPOTENCY_CONFLICT` | 同一幂等键、不同请求体 | — |
| 409 | `VERSION_CONFLICT` | 乐观锁版本号不符（`If-Match`/`base_version_no`）；或提交测评时 `questionnaire_version` 不是当前问卷（v0.2.4） | `{current_version_no}`；测评时为 `{current_version: string}` |
| 409 | `IMMUTABLE_RESOURCE` | 试图修改不可变对象（建议、已发布策略版本、日报、成交原记录） | — |
| 422 | `IMPORT_FILE_ERRORS` | 文件级 error：上传阶段（空文件、过大、类型不符、行数超限，此时**不创建批次**），或确认时批次仍有文件级 error | `{findings: ImportFinding[]}`（code 见 §4.1） |
| 422 | `IMPORT_ROW_ERRORS` | `mode=all` 确认时仍有 error 行 | `{error_rows: int}` |
| 422 | `IMPORT_WARNINGS_UNACKNOWLEDGED` | 有未处理的 `needs_action` warning，且 `acknowledge_warnings≠true` | `{codes: string[], count: int}` |
| 422 | `IMPORT_NOTHING_TO_COMMIT` | 确认时没有可写入的行（只有表头、全部重复、全部错误等） | — |
| 422 | `STRATEGY_INVALID_CONFIG` | 策略配置校验失败（未知因子、表达式语法、参数越界） | `{errors:[{path, issue}]}` |
| 422 | `STRATEGY_EXPR_FORBIDDEN` | 规则表达式含非白名单字段或运算 | `{rule_id, token}` |
| 409 | `STRATEGY_VERSION_PUBLISHED` | 已发布版本不可修改 | `{version_no}` |
| 403 | `STRATEGY_NOT_OWNED` | 修改内置策略或他人策略（须先复制） | — |
| 422 | `STRATEGY_HORIZON_MISMATCH` | 给股票绑定的策略不支持所选周期 | `{strategy_key, horizons}` |
| 422 | `RISK_CONTROL_INVALID_PARAMS` | 风控阈值越界 | `{control, fields}` |
| 409 | `SUGGESTION_SUPERSEDED` | 对已被取代的建议执行动作 | `{current_id}` |
| 409 | `SUGGESTION_REFRESH_TOO_FREQUENT` | 手动刷新过于频繁（受权益 `realtime.min_notify_interval_s` 约束） | `{retry_after_s}` |
| 422 | `SUGGESTION_INSUFFICIENT_DATA` | 必备字段缺失，未生成建议（0A.2 缺一不可） | `{missing:[string]}` |
| 409 | `INVALID_STATE_TRANSITION` | 状态机不允许的跃迁（第 6.0 节） | `{from, to, allowed}` |
| 409 | `STRATEGY_VERSION_NOT_RUNNABLE` | 模板版本不是 `published`/`observing`（例如 simulating、retired） | `{lifecycle}` |
| 422 | `STRATEGY_FIT_ACK_REQUIRED` | 周期分类器判定不适合，需要用户确认 `fit_ack`；`ack_allowed=false` 时带 `fit_ack` 也不能启用（v0.2.4，plan 第 9 节问题 39【待用户确认】） | `{horizon, suitable, ack_allowed: boolean, blocking_rule_ids: string[]}` |
| 422 | `STRATEGY_PARAM_OUT_OF_RANGE` | 参数覆盖超出 param_schema 的 min/max/choices | `{param, min, max, choices}` |
| 422 | `INSTANCE_SCOPE_INVALID` | 实例作用范围不合法（例如 security 范围缺少代码，或代码不在账户/自选中） | `{scope}` |
| 422 | `PROMOTION_GATES_NOT_MET` | 晋级或上线时门禁未通过 | `{gates:[{gate, result}]}` |
| 422 | `CARD_IMPORT_INVALID` | 导入器校验研究员文档失败（plan.md 2.5.14，只在管理端/CI 出现） | `{file, block, errors:[{path, issue}]}` |
| 422 | `COMPLIANCE_LINT_FAILED` | 用户可见文案含禁用词 | `{terms}` |
| 500 | `SIGNAL_NOT_EXPLAINABLE` | 内部：信号缺少可解释字段，已拒绝写入（只出现在日志和管理端，不返回给普通用户） | `{missing}` |
| 422 | `PLAN_REQUIRES_EXPLAINABLE_SIGNAL` | 草案引用的信号没有通过的规则引用（只有模型输出） | `{signal_ids}` |
| 409 | `SIGNAL_NOT_EXECUTABLE` | 信号仍有生效的不可执行原因 | `{reason_ids}` |
| 409 | `PLAN_DRAFT_STALE` | 草案已过期，或依据的数据/持仓已变化 | `{status}` |
| 422 | `CHECKLIST_INCOMPLETE` | 判断清单必答项未答 | `{missing}` |
| 422 | `RISK_ACK_REQUIRED` | 未确认风险提示 | — |
| 422 | `DEVIATION_ACK_REQUIRED` | 数量或价格超出草案区间，且未确认偏离 | `{fields}` |
| 409 | `REASON_NOT_MANUALLY_RELEASABLE` | 该原因可由系统判断，不能手动解除 | `{code}` |
| 503 | `REGISTRATION_CLOSED` | 注册已关闭（`registration_mode=closed`，V1 默认） | — |
| 503 | `FRESH_DATA_REQUIRED` | （v0.1 名为 `DATA_STALE`）只用于**明确要求最新数据**的操作（例如手动刷新建议 `manual_refresh`），而行情已陈旧；读接口一律返回 200 加 `data_status`，不报此错。与原因码 `DATA_STALE` 的区别：原因码挂在候选信号上、表示“这个信号因数据陈旧暂不可执行”，随数据恢复自动解除；本错误码表示“这次请求没有执行” | `{data_as_of}` |
| 503 | `INGEST_PAUSED` | 采集服务被管理员暂停或冷备切换中（只用于需要触发拉取的操作） | — |
| 503 | `LLM_UNAVAILABLE` | 所有 LLM 路由失败（只在显式请求 LLM 时返回；建议本身回落模板，不报错） | `{task}` |
| 429 | `LLM_BUDGET_EXCEEDED` | LLM 日预算用尽 | `{task, budget}` |
| 422 | `LLM_PROVIDER_TEST_FAILED` | 管理员测试连接失败 | `{provider_id, status, message}` |
| 502 | `UPSTREAM_ERROR` | 麦蕊返回错误（已映射，不含 licence） | `{provider:"mairui", upstream_code}` |
| 503 | `UPSTREAM_RATE_LIMITED` | `ingest` 令牌桶耗尽或上游限流，请求已排队（Web 进程不直连麦蕊） | `{retry_after_s}` |
| 503 | `UPSTREAM_UNAVAILABLE` | 上游不可用或证书过期，降级中 | — |
| 429 | `RATE_LIMITED` | 本站限速 | `{retry_after_s}` |
| 500 | `INTERNAL_ERROR` | 未预期错误 | — |
| 503 | `MAINTENANCE` | 维护模式 | — |

### 4.1 导入提示码（`IMPORT_*`，出现在 `ImportFinding.code`，**不是** HTTP 错误码）
- 共 **46 个**：21 个 `error`（文件级 8、行/字段级 13）+ 25 个 `warning`（文件级 10、行/字段级 15）。`error` 阻止写入该文件或该行；`warning` 不阻止，`needs_action=true` 的需逐项处理或确认时统一接受默认处理。
- 对账差异**不是**提示码：6 种 `reconciliation_item_kind` 只出现在 `/reconciliation`。`IMPORT_CASH_CHAIN_BREAK`（单文件内逐行）与对账的 `cash_chain_break`（汇总结论）并存。
- 判定顺序、截断/“0 视为缺失”/撤单等规则见 plan.md 3.5A-1；本表与 plan.md 3.5A-1 的表由同一份数据生成，CI 比对两处逐行一致（§9）。消息模板中的 `{…}` 是 `params` 的键；股东代码、资金账号在 `params` 和 `message` 中一律先掩码。

| # | code | 级别 | 范围 | 消息模板 | 处理与是否可覆盖 | 测试夹具 / 提示 |
|---|---|---|---|---|---|---|
| 1 | `IMPORT_EMPTY_FILE` | error | file | 文件为空（0 字节或只有空白字符） | 不可覆盖；上传时即拒绝（`422 IMPORT_FILE_ERRORS`，不创建批次） | `empty.txt`；编码检测不得抛异常 |
| 2 | `IMPORT_FILE_TOO_LARGE` | error | file | 文件超过 {limit_mb} MB | 不可覆盖；上传时拒绝，不创建批次 | 生成器造 5 MB + 1 字节 |
| 3 | `IMPORT_UNSUPPORTED_FILE_TYPE` | error | file | 只支持 .txt / .csv 文本文件 | 不可覆盖；上传时拒绝（扩展名不符，或 NUL 字节占比 > 1% 视为二进制） | 生成器造含 NUL 的文件 |
| 4 | `IMPORT_TOO_MANY_ROWS` | error | file | 数据行超过 {limit} 行（默认 50,000） | 不可覆盖；请拆分文件 | 生成器 |
| 5 | `IMPORT_ENCODING_UNDETECTED` | error | file | 无法识别文件编码 | 可处理：用户在预览页手选编码后重新解析（`encoding_override`） | 生成器造随机字节文本 |
| 6 | `IMPORT_UNRECOGNIZED_FORMAT` | error | file | 无法识别文件格式，候选解析器：{candidates} | 可处理：用户手选解析器或手工列映射后重新解析 | 生成器造无表头文本 |
| 7 | `IMPORT_REQUIRED_COLUMN_MISSING` | error | file | 缺少必填列：{columns} | 可处理：只能把文件中**已存在**的列映射到缺失字段；**不得推算**（例如用金额 / 数量推价格） | `trades_missing_column.txt` |
| 8 | `IMPORT_ACCOUNT_MISMATCH` | error | file | 文件中的股东代码与所选账户已登记的不一致（按 HMAC 比较） | 可处理：改选账户，或确认“属于本账户的新股东代码”（写审计） | 生成器用两个不同的虚构股东代码 |
| 9 | `IMPORT_ROW_DECODE_ERROR` | error | row | 第 {row_no} 行无法按 {encoding} 解码 | 不可覆盖；**最先判定**。文件末尾不完整的多字节字符也归此码，不得因此整文件拒绝 | `trades_truncated_mid_char.txt` 行 5 |
| 10 | `IMPORT_ROW_TRUNCATED` | error | row | 第 {row_no} 行不完整（文件末行没有换行且列数不足） | 不可覆盖；**优先于** `ROW_COLUMN_MISMATCH`；残缺字段一律不入库 | `trades_truncated_last_line.txt` 行 7 |
| 11 | `IMPORT_ROW_COLUMN_MISMATCH` | error | row | 第 {row_no} 行的列数或列位置与表头不一致 | 不可覆盖（改文件或手动录入）；两种切分策略结果不一致也归此码 | `trades_column_mismatch.txt` 行 6、7 |
| 12 | `IMPORT_REQUIRED_FIELD_EMPTY` | error | field | 必填字段 {field} 为空 | 不可覆盖 | 生成器 |
| 13 | `IMPORT_INVALID_DATE` | error | field | 日期 {value} 无效 | 不可覆盖 | `trades_bad_formats.txt` 行 4 |
| 14 | `IMPORT_FUTURE_DATE` | error | field | 日期 {value} 晚于导入当天 | 不可覆盖 | 生成器 |
| 15 | `IMPORT_INVALID_TIME` | error | field | 时间 {value} 无效 | 不可覆盖；5 位左补零（`93005`→09:30:05）；**4 位及更短的非零值报错，不猜测**；`0` 或空视为缺失、不报错 | `trades_bad_formats.txt` 行 5、6 |
| 16 | `IMPORT_INVALID_NUMBER` | error | field | {field} 的值 {value} 不是有效数字 | 不可覆盖；先做全角转半角、去千分位 | 生成器 |
| 17 | `IMPORT_INVALID_SECURITY_CODE` | error | field | 证券代码 {value} 格式无效（应为 6 位数字） | 不可覆盖；格式有效但主数据中没有的见 `UNKNOWN_SECURITY` | 生成器 |
| 18 | `IMPORT_INVALID_QUANTITY` | error | field | 买卖类数量为 0（且不是撤单或废单） | 不可覆盖 | `trades_sign_and_value_errors.txt` 行 9 |
| 19 | `IMPORT_INVALID_PRICE` | error | field | 价格或成交金额 ≤ 0 | 不可覆盖 | `trades_sign_and_value_errors.txt` 行 7 |
| 20 | `IMPORT_SIDE_QTY_SIGN_MISMATCH` | error | row | 数量符号与买卖方向不一致 | 不可覆盖 | `trades_sign_and_value_errors.txt` 行 5、6 |
| 21 | `IMPORT_AMOUNT_MISMATCH` | error | row | 数量绝对值 × 价格 与成交金额相差 {diff} 元（容差 0.05 元） | 不可覆盖 | `trades_sign_and_value_errors.txt` 行 8 |
| 22 | `IMPORT_DUPLICATE_FILE` | warning | file | 同一文件已于 {imported_at} 导入（批次 {batch_id}） | 仅提示；仍可预览，重复行由去重挡住 | 同一账户重传 `trades_sample.txt` |
| 23 | `IMPORT_NO_DATA_ROWS` | warning | file | 只有表头，没有数据行 | 仅提示；批次照常创建，确认时返回 `422 IMPORT_NOTHING_TO_COMMIT` | `trades_header_only.txt` |
| 24 | `IMPORT_UNKNOWN_COLUMN` | warning | file | 已忽略未识别的列：{columns} | 仅提示；按表头名取列，不按固定列序 | `trades_extra_column.txt` |
| 25 | `IMPORT_FILE_POSSIBLY_TRUNCATED` | warning | file | 文件末尾不完整，可能没有导出完整 | 仅提示；与 `ROW_TRUNCATED` / 末行 `ROW_DECODE_ERROR` 同时出现 | `trades_truncated_last_line.txt`、`trades_truncated_mid_char.txt` |
| 26 | `IMPORT_ENCODING_LOW_CONFIDENCE` | warning | file | 编码判定为 {encoding}，置信度 {confidence} 较低 | 需确认：请核对预览中的中文；可改选编码 | 生成器 |
| 27 | `IMPORT_FORMAT_LOW_CONFIDENCE` | warning | file | 解析器 {parser} 的识别得分 {score} 低于 0.95 | 需确认：请核对列映射 | 生成器（缺少可选列） |
| 28 | `IMPORT_SNAPSHOT_AS_OF_ASSUMED` | warning | file | 快照没有日期，导出时间按 {as_of} 处理 | 需确认：确认或修改导出时间（问题 20） | `positions_sample.txt` |
| 29 | `IMPORT_SNAPSHOT_TOTALS_MISMATCH` | warning | file | 资金摘要与明细合计不一致（券商口径未知） | 仅展示，不判定、不阻止 | `positions_sample.txt` |
| 30 | `IMPORT_SNAPSHOT_SUPERSEDES` | warning | file | 该账户在 {as_of} 已有快照，确认后新版本覆盖旧版本（旧版本保留） | 仅提示 | 同一 as_of 重传 `positions_sample.txt` |
| 31 | `IMPORT_UNSUPPORTED_CURRENCY` | warning | file | 已忽略 {currency} 资金摘要行（只支持人民币） | 仅提示 | `positions_multi_currency.txt` |
| 32 | `IMPORT_NET_AMOUNT_MISMATCH` | warning | row | 发生金额与 ±成交金额 − 费用 相差 {diff} 元（容差 0.02 元） | 仅提示；照常导入，对账时参考 | `trades_sign_and_value_errors.txt` 行 10 |
| 33 | `IMPORT_UNKNOWN_SECURITY` | warning | row | 证券代码 {code} 不在证券主数据中（可能已退市或刚上市） | 需确认：确认后按原代码导入 | 生成器 |
| 34 | `IMPORT_MARKET_INFERRED_CONFLICT` | warning | row | 由代码段推断的市场与股东代码类型不一致 | 需确认；以证券主数据为准 | 生成器 |
| 35 | `IMPORT_NAME_MISMATCH` | warning | field | 证券名称 {name_raw} 与主数据 {name} 不同 | 仅提示；比较前去掉全部空白，名称内部有空格本身不报错 | `trades_column_mismatch.txt` 行 5 + 主数据夹具 |
| 36 | `IMPORT_UNKNOWN_BIZ_TYPE` | warning | row | 业务类型 {biz} 未识别，本行未导入 | 行状态 `skipped`；需确认（可改为手动录入），不猜测 | `trades_non_trade_events.txt` 行 7 |
| 37 | `IMPORT_ROW_CANCELLED` | warning | row | 撤单行，已忽略 | 行状态 `skipped`，无需处理；成交编号 `0` 不参与去重 | `trades_cancelled.txt` 行 5、6 |
| 38 | `IMPORT_ROW_REJECTED` | warning | row | 废单行，已忽略 | 行状态 `skipped`，无需处理 | `trades_cancelled.txt` 行 7 |
| 39 | `IMPORT_DUPLICATE_IN_DB` | warning | row | 与已导入的成交重复（批次 {batch_id}） | 默认 `skipped`；可覆盖：强制作为新成交，须填理由并写审计 | `trades_reimport_overlap.txt` 行 4–6 |
| 40 | `IMPORT_DUPLICATE_IN_FILE` | warning | row | 与本文件第 {other_row_no} 行重复 | 默认 `skipped`；可覆盖（同上）。去重规则 3（无编号）下完全相同的行**不报此码**，按 `#n` 保留为真实的多笔成交 | `trades_duplicates_in_file.txt` 行 7 |
| 41 | `IMPORT_POSSIBLE_DUPLICATE_OF_MANUAL` | warning | row | 可能与手动录入的成交 {trade_id} 是同一笔 | 需选择：跳过导入行（默认）/ 保留导入并作废手动记录 | 生成器 + 先手动录入同一笔 |
| 42 | `IMPORT_MISSING_OPENING_POSITION` | warning | row | 卖出数量超过重建后的持仓，可能缺期初持仓 | 仅提示；建议补录期初持仓 | 生成器 |
| 43 | `IMPORT_CASH_CHAIN_BREAK` | warning | row | 剩余金额链在本行断开，差额 {diff} 元 | 仅提示（日间可能有非成交资金流水） | `trades_duplicates_in_file.txt` 行 8；`trades_reimport_overlap.txt` |
| 44 | `IMPORT_NON_TRADING_DAY` | warning | row | 成交日期 {date} 不是交易日 | 仅提示 | 生成器 |
| 45 | `IMPORT_TIME_OUTSIDE_SESSION` | warning | row | 成交时间不在交易时段内 | 仅提示 | 生成器 |
| 46 | `IMPORT_LOT_SIZE_IRREGULAR` | warning | row | 买入数量不符合整手规则 | 仅提示（科创板 200 股起、按 1 股递增等规则按板块处理） | 生成器 |

**处理选项（v0.2.4 #11，T-F02 D3）**：`ImportFinding.resolution_choices` 按下表生成，第一个为 `default_resolution`；表中没有的提示码 `resolution_choices = []`、`default_resolution = null`。覆盖类选项提交时 `reason` 必填（1–200 字），并写审计。

| 提示码 | `resolution_choices`（第一个为默认） | 覆盖类（须填理由） |
|---|---|---|
| 8 `IMPORT_ACCOUNT_MISMATCH` | `[confirm_new_holder_code]`（不选则须改选账户） | `confirm_new_holder_code` |
| 26/27/28 `IMPORT_ENCODING_LOW_CONFIDENCE` / `IMPORT_FORMAT_LOW_CONFIDENCE` / `IMPORT_SNAPSHOT_AS_OF_ASSUMED` | `[confirm]`（要改编码、解析器或快照时间，用 `PUT /imports/{batch_id}/options`） | — |
| 33 `IMPORT_UNKNOWN_SECURITY` | `[import_as_is, skip_row]` | — |
| 34 `IMPORT_MARKET_INFERRED_CONFLICT` | `[use_master_data]` | — |
| 36 `IMPORT_UNKNOWN_BIZ_TYPE` | `[keep_skipped, manual_entry]` | — |
| 39/40 `IMPORT_DUPLICATE_IN_DB` / `IMPORT_DUPLICATE_IN_FILE` | `[keep_skipped, force_import]`（`needs_action=false`，但可覆盖） | `force_import` |
| 41 `IMPORT_POSSIBLE_DUPLICATE_OF_MANUAL` | `[skip_import_row, keep_import_void_manual]` | `keep_import_void_manual` |


---
## 5. 共享对象（各接口复用）

### 5.1 通用对象
| 对象 | 结构 |
|---|---|
| `Evidence` | 主键 `id` 在所属文档（一条建议、一个候选信号、一份日报）内唯一，全局用 `(snapshot_id, id)` 定位；其他对象一律用 `evidence_ids: string[]` 引用，**不存在 `evidence_id` 字段**。结构 `{id: string, key: string(feature_key), value: string \| number \| boolean \| null, unit: string \| null, provider: data_provider, endpoint: string \| null, data_as_of: string(datetime), fetched_at: string(datetime), epistemic_type}` |
| `RuleRef` | `{rule_id: string, snippet_id: string(uuid) \| null, snippet_version: int \| null, role: rule_role, dimension: dimension, passed: boolean \| null, value: string \| null, threshold: string \| null, evidence_ids: string[]}`。`passed` = 规则表达式求值为真（veto/counter/invalidation/weakening/exit 为真即“命中”）；无法求值为 `null`；未持有时 `ctx.*`/`plan.*` 规则不出现（v0.2.2）。`dimension` 对所有 `role` 必填、非空，取规则规格中声明的维度（v0.2.3） |
| `ModelRef` | `{model_key: string, version: string, role: "auxiliary", output: object, evidence_ids: string[]}` — `role` 只允许为 `auxiliary` |
| `TextWithEvidence` | `{text: string, expr: string \| null, evidence_ids: string[]}`，用于 `counter_evidence[]`、`invalidation[]`、`reasons[]` |
| `Stat` | `{value: string(decimal) \| null, n: int, window: string, small_sample: boolean}`。n < 30 时 `small_sample=true`；n < 5 时 `value=null`（plan 2.12.3；这是展示阈值，与降权门槛 n ≥ 20 无关）。**所有胜率、收益、IC、CAR 都用这个结构** |
| `ReleaseCondition` | `{kind: "expr" \| "time" \| "event" \| "user_action", expr: string \| null, at: string(datetime) \| null, event: string \| null, action: string \| null, check_on: check_on[], human_text: string, machine_checkable: boolean}` |
| `RiskFlag` | `{control: risk_control, level: risk_level, message: string, gated_actions: action[], quantity_cap: string(decimal) \| null, evidence_ids: string[]}` |
| `DataStatusBlock` | 1.1 节的 `{data_status, data_as_of, gaps[]}` |
| `Stops` | `{stop_loss: string(decimal) \| null, take_profit: string(decimal) \| null, time_stop_days: int \| null}`。所有止损、止盈、时间止损一律嵌套在 `stops` 中（`CandidateSignal`、`StrategyConclusion`、`PlanDraft`），不平铺 |
| `ImportFinding` | `{id: string, code: string(IMPORT_*，§4.1), severity: import_severity, scope: import_scope, row_no: int \| null, field: string \| null, message: string, params: object, needs_action: boolean, resolution_choices: string[]（按 §4.1“处理选项”表，v0.2.4）, default_resolution: string \| null（= `resolution_choices[0]`，为空时 null）, resolution: {choice: string, reason: string \| null, by: string(uuid), at: string(datetime)} \| null}`。`row_no` 为文件物理行号（从 1 起），文件级为 `null`；`params`/`message` 中的股东代码、资金账号先掩码 |
| `Bar` | `{t: string(date) \| string(datetime), open, high, low, close: string(decimal), pre_close: string(decimal) \| null, volume: string(decimal), amount: string(decimal), avg_price: string(decimal) \| null}`。`t`：日/周线为交易日（周线取该周最后交易日）；`1m` 为该分钟 bar 的**结束**时刻【口径待 T003/T-B05 实测上游后确认】。`volume` 单位为**股**、`amount` 单位为**元**（上游若以“手”返回，由 ingest 换算；上游单位【待 T003 核实】）。`avg_price` 只在 `1m` 给出（分时均价 = 当日累计成交额 / 累计成交量），日/周线为 `null` |
| `WatchlistItem` | `{security_code, name, focus: boolean, group: string \| null, note: string \| null, added_at: string(datetime), refresh_tier: "tier1" \| "tier2" \| null}`。`refresh_tier` 由系统按重点关注与配额分配（只读；分层规则见 plan 0A.3，数值【待 T003】） |
| `SignalEvent` | `{signal_event_id: string, security_code, name, kind: signal_kind, at: string(datetime), message: string, strategy_key: string \| null, instance_id: string(uuid) \| null, rule_id: string \| null, price: string(decimal) \| null, candidate_signal_id: string(uuid) \| null}`。规则事件，**不含动作建议**；`message` 须通过禁用词校验 |
| `Notification` | `{id, kind: notification_kind, severity, title: string, body: string \| null, created_at: string(datetime), read_at: string(datetime) \| null, security_code: string \| null, name: string \| null, target: {type: notification_target_type, id: string \| null, route: string \| null}}`。`target.route` 是前端路由（如 `/suggestions/{id}`、`/daily-reports/2026-11-02`），`type=none` 时 `id` 与 `route` 为 `null`。`route` 由服务端生成，前端直接跳转（v0.2.3）：`suggestion` → `/suggestions/{id}`；`candidate_signal` → `/candidate-signals/{id}`；`plan_draft` → `/plan-drafts/{id}`；`plan` → `/plans/{id}`；`daily_report` → `/daily-reports/{date}`（`id` 为日期）；`import_batch` → `/portfolio/import?batch={id}`；`reconciliation` → `/portfolio?tab=reconciliation&account_id={id}`；`strategy_version` → `/strategies/{strategy_id}?version={id}`（`id` 为版本 id） |
| `TerminalRow` | `{security_code, name, in_watchlist: boolean, focus: boolean, quote: {price, change_pct, amount: string(decimal), t: string(datetime)} \| null, holding: {qty: string(decimal), sellable_qty: string(decimal), cost_price: string(decimal), weight_pct: string(decimal), pnl: string(decimal), pnl_pct: string(decimal)} \| null, suggestion: SuggestionSummary \| null, active_reason_count: int, max_risk_level: risk_level \| null, data_status: data_status, data_as_of: string(datetime) \| null}`。`cost_price` 为摊薄成本（plan 3.5A）；`data_as_of` 为该行行情与建议中较旧者的数据时点，完全无数据时为 `null`（v0.2.3） |
| `SuggestionSummary` | `{id, created_at, status: suggestion_status, consensus: consensus_status, actions: [{strategy_key, strategy_name, action, t_leg: t_leg \| null}], executability_status: executability_status, divergent_dimensions: dimension[], top_score: int \| null}`。终端表格的动作徽标与分歧标记只读这里，不再逐只请求 `/suggestions/{id}` |
| `HorizonCap` | `{horizon: horizon, cap: int(0–100), kind: "data_missing" \| "requires", rule_id: string \| null, inputs_missing: string[]}`（v0.2.3）。`data_missing`：必需特征缺失导致封顶（`rule_id=null`，`inputs_missing` 为该周期缺失的 `f.*` 键）；`requires`：某条 `requires` 规则不满足导致封顶（`rule_id` 如 `SH0C`、`IT0C`，`inputs_missing` 可为 `[]`）。`rule_id` 是 `horizon_classifier.yaml` 的规则 ID，**不是** `reason_code`，不进 `/meta/enums`（v0.2.3 #23）。同一周期多个封顶都列出，生效值取最小 |

**可解释性强制规则（P1）**：在任何返回 `CandidateSignal`、`Suggestion` 中策略结论的响应里，`rule_refs`、`evidence`、`counter_evidence`、`invalidation` 都是**非空数组**；`model_refs[*].role == "auxiliary"`。服务端写入时校验，不满足的不写入（内部记 `SIGNAL_NOT_EXPLAINABLE`）；契约测试检查所有示例和响应（T-T17）。

### 5.2 建议（`Suggestion`，plan.md 2.5.5 的 JSON 视图，内容不可变）
| 字段 | 类型 | 说明 |
|---|---|---|
| `id`, `security_code`, `name`, `created_at` | | |
| `status` | `suggestion_status` | 唯一可变字段（另有 `superseded_by_id`）；被取代、失效、过期时由系统更新 |
| `origin` | `suggestion_origin` | |
| `snapshot_id`, `feature_set_version` | string | 证据快照与特征集版本 |
| `candidate_signal_ids` | uuid[] | 本次生成的候选信号（hold/wait 不生成） |
| `executability` | `{status: executability_status, reason_ids: uuid[], executable_signal_ids: uuid[], blocked_signal_ids: uuid[]}` | 取值规则见 §3 |
| `plan_draft_ids` | uuid[] | |
| `horizon_assessment` | `{suitable: horizon[], user_overridden: boolean}` | |
| `consensus` | `{status: consensus_status, actions: {[action]: int}}` | 各动作的策略数 |
| `strategies` | `StrategyConclusion[]` | 见下表 |
| `dimension_matrix` | `[{dimension, divergent: boolean, cells: DimensionCell[]}]` | 由服务端从 `strategies[].dimension_views` 派生；契约测试检查一致 |
| `divergence` | `[{dimensions: dimension[], summary: string, resolving_info: [{description: string, subscribable: boolean}]}]` | |
| `risk_flags` | `RiskFlag[]` | |
| `evidence` | `Evidence[]` | 本建议引用的全部证据 |
| `explanation` | `{source: "template" \| "llm", text: string, llm_call_id: string \| null}` | LLM 只改写证据，见 plan 0B P1a |
| `supersedes_id`, `superseded_by_id` | uuid \| null | 取代链 |
| `data_status`, `data_as_of`, `gaps` | DataStatusBlock | |

`StrategyConclusion`（`strategies[]` 的元素）：`{strategy_version_id, strategy_key, strategy_name: string, version_no: int, instance_id: uuid \| null, horizon, lifecycle, state: strategy_eval_state, action, t_leg: t_leg \| null, candidate_signal_id: uuid \| null（hold/wait 时为 null）, score: int(0–100) \| null, confidence: {level: confidence_level, value: number(0–1)}, rule_refs: RuleRef[], model_refs: ModelRef[], priority_weight: string(decimal), priority_downweighted: boolean, dimension_views: [{dimension, view: dimension_view, score: int(0–100) \| null, rules: RuleRef[]}], stops: Stops, reasons: TextWithEvidence[], counter_evidence: TextWithEvidence[], invalidation: TextWithEvidence[], valid_until: string(datetime) \| null}`

`DimensionCell`：`{strategy_key, strategy_version_id, view: dimension_view, score: int(0–100) \| null, key_evidence_ids: string[]（≤ 3，取该维度 role ∈ {entry, filter, hold} 且 passed = true 的规则引用的前 3 个证据）, rules_passed: int, rules_total: int, exit_hits: int, exit_total: int}`（`rules_passed/rules_total` 只统计 role ∈ {entry, filter, hold}，v0.2.2；`exit_*` v0.2.3；v0.2.4 修正括号笔误）（v0.2.3：`exit_total` = 该维度 role ∈ {weakening, exit} 且已求值（`passed` 非 null）的规则数，`exit_hits` = 其中 `passed = true` 的条数；没有这类规则时均为 0）。行级 `divergent=true` 当且仅当该维度单元格中**同时存在** `bullish` 与 `bearish`（`neutral`、`unknown` 不参与，v0.2.3）。

**纯离场策略（exit-only，如 H-01 持仓风险监控；v0.2.3）**：规则只含 role ∈ {weakening, exit}（可另有 counter/invalidation）。① 只对**持有中**的证券求值；未持有时不出现在 `strategies[]`、`dimension_matrix`、`consensus` 中。② `state` ∈ {`hold_ok`, `weakening`, `exit_signal`, `insufficient_data`}，`action` ∈ {`hold`, `reduce`, `sell`}，从不出现 `entry_ok`/`buy`/`add`。③ 单元格 `rules_passed/rules_total` 为 0/0、`score` 为 `null`，展示改用 `exit_hits/exit_total`（前端显示“离场 x/y”）；`view`：任一命中 → `bearish`，全部已求值且未命中 → `neutral`，全部无法求值 → `unknown`。④ 计入行级 `divergent` 与 `consensus`（与 catalog 第 4 节第 4 点“冲突时并列展示”一致）。⑤ 计划草案 P1b 由 weakening/exit 命中满足。

`consensus.status`（v0.2.3）：0 个策略 → `none`；1 个 → `single`；≥ 2 个且各策略 `(action, t_leg)` 全部相同 → `unanimous`；否则 `divergent`。

### 5.3 日报（`DailyReport`，不可变）
`{date: string(date), generated_at, account_id: uuid \| null, market: {regime: market_regime \| null, regime_position_range: {min_pct: string(decimal), max_pct: string(decimal)} \| null, breadth: {up: int, down: int, limit_up: int, limit_down: int} \| null, summary: TextWithEvidence[]}, account: {total_assets, cash, position_pct: string(decimal), pnl_day: string(decimal), position_vs_regime: "below" \| "within" \| "above" \| null} \| null, reconciliation: {status: reconciliation_status, as_of: string(datetime) \| null, diff_count: int, important_count: int}, stocks: [{security_code, name, close: string(decimal) \| null, change_pct: string(decimal) \| null, data_status: data_status, max_risk_level: risk_level \| null, suggestion_id: uuid \| null, suggestion: SuggestionSummary \| null, change_from_previous: "new" \| "changed" \| "unchanged" \| "removed", highlights: TextWithEvidence[], invalidation: TextWithEvidence[], next_watch: TextWithEvidence[]}], pending: {plan_drafts: int, active_reasons: int}, explanation: {source: "template" \| "llm", text: string, llm_call_id: string \| null}, evidence: Evidence[], DataStatusBlock}`。
- `regime_position_range` 是该 regime 下的**参考仓位区间**（模板参数，取自风控 RC3 的 `regime_ranges`（plan 2.5.6、6.1 `config/risk_controls.yaml`：上行 60–90%、震荡 40–60%、下行 0–30%，用户可调）），不是指令；`position_vs_regime` 由当前仓位与区间比较得出。
- 没有账户或未导入时 `account=null`、`reconciliation.status="not_imported"`。
- `stocks[].close`/`change_pct` 为日报所属交易日的收盘价与涨跌幅（停牌或缺数据为 `null`）；`max_risk_level` 取该证券建议卡 `risk_flags` 的最高级别，无则 `null`（v0.2.3）。
- `account.cash` 与全文其他 `cash`（如 `PlanDraft.user_context_snapshot.cash`）同义：由交割单与资金流水重建的现金余额；与 `/terminal` 的 `cash_available`（可用资金）不同（v0.2.3）。

---

## 6. 状态机与原因码

### 6.0 状态机（非法跃迁 → `409 INVALID_STATE_TRANSITION`，`details: {from, to, allowed: []}`）
| 对象 | 状态 | 允许的跃迁（触发方） |
|---|---|---|
| 卡片 `card_completeness` | `draft` `documented` `runnable_candidate` `promoted` `retired` | 系统自动计算，客户端不可写 |
| 模板版本 `lifecycle` | `draft` `simulating` `published` `observing` `retired` | draft→simulating（管理员，G1–G7 通过）；simulating→published（管理员，满足 2.5.13 条件）；published⇄observing（健康度状态机，系统）；任意→retired（管理员） |
| 实例 `instance_status` | `proposed` `active` `paused` `archived` | proposed→active（用户确认）；active⇄paused（用户，或 `LOSS_STREAK_PAUSE` 系统暂停）；任意→archived（用户） |
| 候选信号 `candidate_signal_state` | `open` `drafted` `blocked` `released` `confirmed` `dismissed` `expired` `invalidated` `superseded` | open→drafted/blocked（系统）；blocked→released（系统或手动解除）→drafted/blocked；drafted→confirmed（确认草案）；非终止态→dismissed（用户）/expired/invalidated/superseded（系统） |
| 原因 `reason_status` | `active` `released` `obsolete` | active→released（系统，或 `machine_checkable=false` 时由用户手动）；active→obsolete（所属信号终止） |
| 计划草案 `plan_draft_status` | `pending` `confirmed` `discarded` `expired` `stale` | pending→confirmed/discarded（用户）；pending→expired/stale（系统） |
| 导入批次 `import_status` | `uploaded` `parsing` `previewed` `committed` `failed` `discarded` `reverted` | uploaded→parsing（系统）；parsing→previewed/failed（系统）；previewed/failed→parsing（`PUT options`）；previewed→committed（确认）；previewed/failed→discarded（用户）；committed→reverted（用户） |
| 健康度 `health_state` | `published` `observing` | 见 2.8.2；`proposed_action: none \| review \| retire` 只用于提示 |

### 6.1 不可执行原因码（`reason_code`，与 plan.md 2.5.9 一致；`GET /meta/enums` 下发，含默认解除条件）
| code | 默认 `release_condition.kind` | `check_on` | 可手动解除 |
|---|---|---|---|
| `DATA_STALE` | expr | tick | 否 |
| `KEY_DATA_MISSING` | expr | tick, daily_close | 否 |
| `LOW_CONFIDENCE` | expr | tick, daily_close | 否 |
| `NON_TRADING_TIME` | time | schedule | 否 |
| `SUSPENDED` | event | tick, daily_close | 否 |
| `LIMIT_LOCKED` | expr | tick | 否 |
| `ST_OR_DELISTING` | event | daily_close | 否 |
| `NEW_LISTING` | expr | daily_close | 否 |
| `INSUFFICIENT_CASH` | expr | cash_update, import | 否 |
| `T1_NOT_SELLABLE` | time / expr | schedule, holding_change | 否 |
| `NO_POSITION` | expr | holding_change, import | 否 |
| `POSITION_CAP_REACHED` | expr | tick, holding_change | 否 |
| `STRATEGY_BUDGET_EXHAUSTED` | expr | holding_change | 否 |
| `SECTOR_EXPOSURE_EXCEEDED` | expr | holding_change, tick | 否 |
| `REGIME_MISMATCH` | expr | daily_close | 否 |
| `SAME_DIRECTION_PLAN_EXISTS` | event | plan_change | 否 |
| `CONFLICTS_CONFIRMED_PLAN` | user_action | user_action | 是 |
| `BLOCKLISTED` | user_action | user_action | 是（通过 `/restrictions`） |
| `COOLING_OFF` | time | schedule | 否 |
| `LOSS_STREAK_PAUSE` | user_action / time | user_action, schedule | 是 |
| `STRATEGY_CONFLICT` | user_action / expr | user_action, tick | 是 |
| `USER_MUTED` | user_action / time | user_action, schedule | 是（通过 `/restrictions`） |
| `PROFILE_OR_CONSENT_MISSING` | user_action | user_action | 否（完成相应步骤后系统解除） |

---

## 7. 端点
约定：标 🔒 的需要登录且账号已批准；标 🛡 的需要 `role=admin`；标 ⚖ 的还要满足 1.3 的合规门槛；列表接口均按 1.2 分页，除非注明。请求体字段未注明可空的都必填。

### 7.1 认证与账号
| 方法 | 路径 | 说明 | 请求 → 响应 |
|---|---|---|---|
| GET | `/meta/registration` | 注册模式（不需登录），前端据此隐藏注册入口 | → `200 {mode: registration_mode}`（v0.2.4：`doc_versions` 移到 `GET /meta/consent-docs`） |
| GET | `/meta/consent-docs` | 各文书当前版本（不需登录；`Cache-Control: public, max-age=300`；v0.2.4 #3） | → `200 {items: [ConsentDoc]}`，每个 `legal_doc_key` 一项：`ConsentDoc {key: legal_doc_key, version: string（语义化版本或 "unversioned"）, version_no: int \| null, title: string, summary: string, effective_at: string(datetime) \| null, content_sha256: string \| null, url: string \| null（= `/api/v1/legal/{key}`；未定稿时 null）, required_for: ("register" \| "advice" \| "import" \| "display")[]}`。`terms`、`privacy` → `["register"]`；`signal_risk_disclosure` → `["register", "advice"]`；`sensitive_financial_info` → `["import"]`；`site_risk_notice` → `["display"]`。`"unversioned"` 只会在 `registration_mode=closed` 时出现 |
| GET | `/legal/{doc_key}` · `/legal/{doc_key}/versions` · `/legal/{doc_key}/{version}` | 文书正文（不需登录，v0.2.4 #3） | 当前版本 / 历史列表 / 指定版本：`LegalDocument {key: legal_doc_key, version, version_no, title, summary, content_md, content_sha256, locale, change_level: "major"\|"minor"\|"patch", changelog: string, effective_at, published_at}`；列表元素不含 `content_md`。未发布（`"unversioned"`）或版本不存在 → `404 NOT_FOUND`。已发布的版本永远可取（只插入，不删除） |
| POST | `/auth/register` | 注册，状态为 `pending`。**V1 默认 `registration_mode=closed`**，一律返回 `503 REGISTRATION_CLOSED`；本人账号由 CLI 创建 | `{username: string(4–32，^[a-z0-9_]+$，服务端转小写；保留词 admin/root/system 等 → 400 VALIDATION_ERROR), password: string(10–128，须含字母与数字，不得等于用户名，不得在弱口令表中), display_name: string(1–32), invite_code: string \| null（V1 不用）, apply_note: string(≤200) \| null, agreements: consent_key[]}`；`agreements` 必须包含 `terms`、`privacy`、`signal_risk_disclosure`，可另含 `sensitive_financial_info`（v0.2.4 #2：原 `risk_disclosure` 作废），按 `/meta/consent-docs` 的当前版本记录（`presentation=checkbox_unticked`） → `201 {id, username, status:"pending"}`；`invite` 模式下 `invite_code`、`apply_note` 必填，邀请码无效（不存在/过期/已用/已吊销/绑定的用户名不符）一律 `400 VALIDATION_ERROR {fields:[{field:"invite_code", issue:"invalid"}]}`；可能返回 `409 CONFLICT`、`503 REGISTRATION_CLOSED`（含邀请功能未上线时的 `invite` 模式）、`429 RATE_LIMITED` |
| POST | `/auth/login` | 登录 | `{username, password}` → `200 {user: Me, csrf_token}` + Set-Cookie；可能返回 `401 INVALID_CREDENTIALS`、`403 ACCOUNT_NOT_APPROVED{status, reason?}`、`403 ACCOUNT_LOCKED{retry_after_s}` |
| POST | `/auth/logout` 🔒 | 注销 | → `204` |
| POST | `/auth/password` 🔒 | 修改密码，同时注销其他会话并轮换当前会话 | `{old_password, new_password}` → `204` + Set-Cookie（新 `sid`、新 `csrf_token`；前端从 Cookie 重读 CSRF 令牌）；旧密码错误 → `400 VALIDATION_ERROR`（`field: old_password`），计入 T-B03a 限速 |
| GET | `/me` 🔒 | 当前用户 | → `Me {id, username, display_name, role, status, entitlements: {key: value}, consents: {[consent_key]: {version: string \| null, accepted_at: string(datetime) \| null, current_version: string, needs_reconsent: boolean}}（四个键都有；未同意或已撤回时 `version`/`accepted_at` 为 null，`needs_reconsent=true`）, risk_assessment: RiskAssessmentSummary \| null}`；`RiskAssessmentSummary {assessment_id, questionnaire_version, risk_tolerance: int(1–5), submitted_at, expires_at, status: assessment_status, needs_retest: boolean}`（v0.2.4 #5、#6） |
| GET/PUT | `/me/profile` 🔒 | 投资画像（版本化，PUT 生成新版本） | `{horizon_pref: horizon[], effort: "low"\|"medium"\|"high" \| null, risk_tolerance: int(1–5) \| null, experience: "novice"\|"intermediate"\|"advanced" \| null, max_single_position_pct: string(decimal，5–50，最多 2 位小数), assessment_id: uuid \| null}` → `{version_no, questionnaire_version: string \| null, ...}`；无画像时 GET → `404 NOT_FOUND`。三个测评字段为 null 表示未测评（分类器按未填写处理，plan 2.5.14）。**【待用户确认】（plan 第 9 节问题 38，研究员默认）**：这三个字段只能等于或比 `assessment_id`（省略时取最近一次有效测评）的 `derived` 更保守，更激进 → `400 VALIDATION_ERROR {fields:[{field, issue:"exceeds_assessment", max_allowed}]}`；没有有效测评时只能为 null。`assessment_id` 不是自己的或不是有效测评 → 400（v0.2.4 #7） |
| POST | `/me/consents` 🔒 | 同意或撤回条款（只追加记录） | `{key: consent_key, version: string, content_sha256: string \| null, action: "grant"\|"withdraw"（默认 grant）, ui_surface: string(≤64), presentation: consent_presentation}` → `201 {key, version, action, at}`；`version` 与 `content_sha256` 必须等于 `/meta/consent-docs` 的当前值（`"unversioned"` 时 `content_sha256` 为 null），否则 `400 VALIDATION_ERROR`（`field: version` 或 `content_sha256`）。`withdraw` 只接受 `signal_risk_disclosure`、`sensitive_financial_info`（撤回后相应门槛立即生效，已有数据的处理见 plan 7.3）；`terms`、`privacy` 不能单独撤回（走注销账户）→ 400（v0.2.4 #4） |
| GET | `/me/risk-assessment/questionnaire` 🔒 | 当前问卷（不含分值、正确答案和计分规则；v0.2.4 #6） | → `200 {questionnaire_key: "risk_profile", version, intro: string, groups: [{id, title}], questions: [{q_id, group, type: "single", required: boolean, title, choices: [{id, text}]}]}`；结构对应 `docs/strategies/compliance/risk_questionnaire.yaml`；没有已发布问卷 → `404 NOT_FOUND` |
| GET | `/me/risk-assessment` 🔒 · `/me/risk-assessments` 🔒 | 最近一次测评 / 历史（分页） | → `RiskAssessment`；从未测评 → `404 NOT_FOUND`；历史元素同结构，记录不可修改 |
| POST | `/me/risk-assessment` 🔒 | 提交风险测评（每次新增一条记录，不改画像） | `{questionnaire_version: string, answers: [{q_id: string, choice: string}], started_at: string(datetime) \| null, client_duration_s: int \| null}` → `201 RiskAssessment {assessment_id, questionnaire_version, submitted_at, expires_at, status: assessment_status, derived: {risk_tolerance: {value: int(1–5), rule_ids: string[]}, experience: {value, rule_ids}, effort: {value, rule_ids}}, flags: string[]（如 `no_loss_tolerance`、`self_report_higher`、`fast_completion`）, needs_retest: boolean}`。`questionnaire_version` 不是当前版本 → `409 VERSION_CONFLICT {current_version}`；缺题、未知 `q_id` 或选项 → `400 VALIDATION_ERROR {fields:[{field:"answers.<q_id>", issue}]}`；K4（理解确认）答错 → `400 VALIDATION_ERROR`，`details.reason = "understanding_required"`（不入库）；24 小时内超过 3 次 → `429 RATE_LIMITED`。`trade_count_12m` 等由服务端从成交记录计算，客户端不提交。用户确认后用 `PUT /me/profile` 带 `assessment_id` 写入画像。有效期 **【待用户确认】（问题 40）** 365 天、提前 30 天提醒、宽限 30 天 |
| GET/PATCH | `/admin/users` 🛡 · `/admin/users/{id}` 🛡 | 审核和停用账号 | GET 列表分页（§1.2）`?status=&q=`，元素 `AdminUser {id, username, display_name, status: account_status, role, apply_note: string \| null, created_at, register_ip_region: string \| null（粗粒度）, same_ip_registrations: int, same_ip_flag: boolean（超过 plan 6.1 `admin.same_ip_highlight_threshold`，只作提示）, review_reason: string \| null, reviewed_at: string(datetime) \| null, last_login_at: string(datetime) \| null}`；PATCH `{status: "approved"\|"rejected"\|"disabled", reason: string(≤200) \| null}`：`rejected`、`disabled`，以及从 `disabled` 恢复为 `approved` 时 `reason` 必填，否则 `400 VALIDATION_ERROR`（v0.2.4 #12） |

### 7.2 账户、成交与导入（只返回掩码字段）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/accounts` 🔒 | 券商账户：`{id, broker_name, alias, shareholder_code_masked, fund_account_masked, created_at}`；POST 只接受 `alias` 和 `broker_name` |
| POST | `/imports` 🔒 | `multipart/form-data`：`file`、`account_id`、`kind: "trades"\|"positions"`、`snapshot_as_of: string(datetime) \| null`（持仓快照时间，可后补）。原始文件存放在仓库外、加密并做访问控制的存储中（plan.md 3.5A）→ `201 {batch_id, status: "uploaded", file_findings: ImportFinding[]}`，随后后台解析。上传阶段的文件级 error（空文件、过大、类型不符、行数超限）→ `422 IMPORT_FILE_ERRORS{findings}`，**不创建批次**。同一文件再次上传**不报错**，在 `file_findings` 中给出 warning `IMPORT_DUPLICATE_FILE{batch_id}` |
| GET | `/imports` 🔒 | 批次列表（分页，`?account_id=&status=`）：元素 `ImportBatchSummary {batch_id, account_id, kind, status: import_status, parser_id: string \| null, stats, created_at, committed_at: string(datetime) \| null, reverted_at: string(datetime) \| null}`（v0.2.4 #12） |
| GET | `/imports/{batch_id}` 🔒 | `{batch_id, account_id, kind, status: import_status, parser_id: string \| null, parser_version: string \| null, detected_encoding: string \| null, encoding_override: string \| null, encoding_confidence: number \| null, format_score: number \| null, detected_columns: string[], mapping: {[column]: field} \| null, snapshot_as_of: string(datetime) \| null, file_findings: ImportFinding[], stats: {rows, ok, warning, error, skipped, new, duplicate_in_db, duplicate_in_file, possible_duplicate_of_manual, needs_action_open: int}, created_at, committed_at: string \| null, reverted_at: string \| null}`。`parser_id` 取 `tdx_trades_v1` / `tdx_positions_v1`（旧名 `fmt_a_*` 作为别名接受）。轮询间隔 ≥ 1 秒，或等 SSE `notification(kind=import)` |
| GET | `/imports/{batch_id}/rows` 🔒 | 预览行（分页，`?status=&code=&dedup_status=`）：`{row_no, status: import_row_status, kind: "trade" \| "event" \| "ignored", dedup_status: dedup_status \| null, findings: ImportFinding[], raw_masked: string, normalized: {trade_date, trade_time: string \| null, security_code, name, side: trade_side \| null, qty, price, amount, fee_total: string \| null, net_amount: string \| null, biz_type_raw: string} \| null}`。`raw_masked` 是掩码后的原始行；**不返回原始股东代码或资金账号** |
| PUT | `/imports/{batch_id}/options` 🔒 | 改编码、解析器、列映射或快照时间并重新解析：`{encoding_override: string \| null, parser_id: string \| null, mapping: object \| null, snapshot_as_of: string(datetime) \| null}` → `202 {status: "parsing"}`；只允许 `previewed`/`failed`，否则 `409 INVALID_STATE_TRANSITION` |
| POST | `/imports/{batch_id}/findings/{finding_id}/resolve` 🔒 | 处理一条提示：`{choice: string, reason: string \| null}` → `200 ImportFinding`；`choice` 须在该提示的 `resolution_choices` 中（非空即可处理，不限 `needs_action`，§4.1“处理选项”）；覆盖类选项 `reason` 必填（≤200），否则 `400 VALIDATION_ERROR`；写审计（v0.2.4 #11） |
| POST | `/imports/{batch_id}/confirm` 🔒 | 两步提交的第二步，支持 `Idempotency-Key`：`{mode: "all" \| "valid_rows_only", acknowledge_warnings: boolean}` → `200 {status: "committed", written: {trades: int, events: int, snapshot_positions: int}, reconciliation: {status: reconciliation_status, diff_count: int} \| null}`。可能返回 `422 IMPORT_FILE_ERRORS`、`422 IMPORT_ROW_ERRORS`（`mode=all` 且有 error 行）、`422 IMPORT_WARNINGS_UNACKNOWLEDGED`、`422 IMPORT_NOTHING_TO_COMMIT`、`409 INVALID_STATE_TRANSITION`。`valid_rows_only` 只写 `ok`/`warning` 且 `dedup_status=new` 的行 |
| POST | `/imports/{batch_id}/discard` 🔒 | 放弃未提交的批次 → `{status: "discarded"}`（只允许 `previewed`/`failed`） |
| POST | `/imports/{batch_id}/revert` 🔒 | 回滚已提交批次 → `{status: "reverted"}` |
| GET | `/imports/{batch_id}/errors.csv` 🔒 | `text/csv; charset=utf-8`（带 BOM）：列 `row_no, code, severity, field, message, raw_masked`；只含**掩码后**的原始行 |
| GET/POST | `/trades` 🔒 · `/trades/{id}` 🔒 | 成交列表和手工录入；原记录不可修改，更正时写更正记录。GET `?account_id=&security_code=&from=&to=&include_voided=`（分页），元素 `Trade {id, account_id, trade_date, trade_time: string \| null, security_code, name, side: trade_side, qty: string(decimal), price: string(decimal), amount: string(decimal), fee_total: string(decimal) \| null, net_amount: string(decimal) \| null, source: "import"\|"manual", batch_id: uuid \| null, voided: boolean, void_reason: string \| null, voided_at: string(datetime) \| null, corrects_trade_id: uuid \| null, created_at}`。POST `TradeCreate {account_id, trade_date, trade_time: string \| null, security_code, side, qty: string(decimal), price: string(decimal), fee_total: string(decimal) \| null, corrects_trade_id: uuid \| null, reason: string \| null（corrects_trade_id 非空时必填）}` → `201 Trade`，支持 `Idempotency-Key`；带 `corrects_trade_id` 时在同一事务中作废原记录并写入新记录；需已同意 `sensitive_financial_info`（§1.3）（v0.2.4 #12） |
| POST | `/trades/{id}/void` 🔒 | 作废一条成交（v0.2.4 #12） | `{reason: string(1–200)}` → `200 Trade`；已作废 → `409 INVALID_STATE_TRANSITION`；导入批次回滚造成的作废，`void_reason` 为 `"batch_reverted:{batch_id}"`；写审计 |
| GET | `/snapshots` 🔒 | 持仓快照 |
| GET | `/reconciliation?account_id=` 🔒 | 对账结果：`{status: reconciliation_status, as_of: string(datetime) \| null, items: [{kind: reconciliation_item_kind, security_code: string \| null, name: string \| null, ours: string(decimal) \| null, broker: string(decimal) \| null, diff: string(decimal) \| null, important: boolean, note: string}]}`。成本按**摊薄成本**比较（我方重建值计入分红：现金红利冲减、股息红利税补缴计入，与通达信一致，v0.2.2），容差 `max(0.01 元, 0.1%)`（plan 3.5A）；每次导入确认后重算 |
| GET | `/portfolio?account_id=` 🔒 | 持仓汇总（`account_id` 可选，不传时合并全部账户；v0.2.4 #14）：`{cash, total_assets, positions: [{security_code, name, qty, sellable_qty, cost_price, market_value, pnl, pnl_pct, weight_pct}], exposure: {sector: [{name, pct}]}, DataStatusBlock}` |

### 7.3 自选、行情与证券
| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST/PATCH/DELETE | `/watchlist` 🔒 · `/watchlist/{security_code}` 🔒 | GET（不分页）→ `{items: WatchlistItem[], caps: {watchlist: int, focus: int}}`；POST `{security_code, group: string \| null, note: string \| null}` → `201 WatchlistItem`；PATCH `{group?, note?}`。超出上限返回 `403 ENTITLEMENT_LIMIT_REACHED{key:"watchlist.per_user_cap"}`（上限数值 **待 T003 验证**） |
| PUT | `/watchlist/{security_code}/focus` 🔒 | 设为重点关注 `{focus: boolean}` |
| GET | `/securities?q=` 🔒 | 证券搜索（不分页，最多 20 条）：`[{security_code, name}]` |
| GET | `/quotes?codes=600000.SH,000001.SZ` 🔒 | 只读缓存，**从不触发上游调用**：`{items: [{security_code, name, price, change_pct, volume, amount, t, DataStatusBlock}]}`；`codes` 最多 200 个 |
| GET | `/securities/{code}/bars` 🔒 | 参数 `freq: bar_freq`（必填）、`adjust: bar_adjust`（日/周默认 `qfq`，`1m` 只能 `none`）、`from`/`to`（`string(date)`）或 `before` + `limit`（向前翻页，`limit` 默认 500、最大 2,000）。响应 `{security_code, name, freq, adjust, pre_close: string(decimal) \| null（1m 时为所请求首个交易日的前收，作分时基准）, items: Bar[]（按 t 升序）, next_before: string \| null, DataStatusBlock}`。缓存里没有时返回 `data_status:"pending"` 并加入回补队列，**不同步等待** |
| GET | `/market/overview` 🔒 | 大盘、宽度、regime、涨跌停统计（v0.2.3 最小结构，只读缓存）：`{trade_date: string(date), session: market_session, indices: [{security_code, name, price: string(decimal) \| null, change_pct: string(decimal) \| null, amount: string(decimal) \| null, t: string(datetime) \| null}], breadth: {up: int, down: int, flat: int, limit_up: int, limit_down: int} \| null, regime: market_regime \| null, regime_position_range: {min_pct, max_pct} \| null, turnover_total: string(decimal) \| null, DataStatusBlock}`。指数清单由后端配置，不在契约中写死 |
| GET | `/terminal` 🔒 ⚖ | **终端一屏聚合**（ETag）：`?scope=all\|watchlist\|holdings`（默认 `all`）`&account_id=`（默认用户的默认账户）。→ `{server_time, trade_date: string(date), session: market_session, account: {account_id, total_assets, cash_available, position_pct, pnl_day, regime: market_regime \| null, regime_position_range: {min_pct, max_pct} \| null, data_status} \| null, rows: TerminalRow[], truncated: boolean, unread_notifications: int}`。不分页，`rows` 最多 300 行（持仓在前按 `weight_pct` 降序，其次重点关注、其余自选按加入时间），超出时 `truncated=true`。`trade_date` 为行情所属交易日（非交易日为最近一个交易日）；`account.cash_available` = 可用资金：最近一次券商资金快照的“可用”，没有快照时等于重建的现金余额 `cash`（v0.2.3 定义）。服务端**固定次数查询**完成（无 N+1，T-B44 测试查询数）；只读缓存，不触发上游。客户端以 SSE `quote`/`suggestion`/`candidate_signal` 增量更新；SSE 断开时才轮询，间隔 ≥ 15 秒并带 `If-None-Match` |
| GET | `/today` 🔒 ⚖ | 首页聚合（ETag）：`{server_time, trade_date, session: market_session, market: {regime, regime_position_range, data_status}, focus: {items: TerminalRow[], more: boolean}, pending_plan_drafts: {items: [{id, security_code, name, action, valid_until, status: plan_draft_status}], more}, released_reasons: {items: [{reason_id, signal_id, code: reason_code, security_code, name, released_at}], more}, risk_flags: {items: [RiskFlag & {security_code: string \| null, name: string \| null}], more}, invalidations_today: {items: [{suggestion_id, security_code, name, strategy_key, text, at}], more}, daily_report: {date, status: "ready" \| "generating" \| "not_yet"}, reconciliation: {status: reconciliation_status, as_of, diff_count, important_count}, unread_notifications: int}`。每个列表最多 50 条，`more=true` 时到对应列表接口查看 |

### 7.4 策略：L1 卡片、特征白名单、L2 模板与生命周期
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/strategy-cards` 🔒 | `?completeness=&horizon=&category=`；元素 `{id, key, name, category, horizons, completeness, current_version_no, source_kind, performance: {win_rate_5d: Stat, avg_excess_5d: Stat} \| null}` |
| GET | `/strategy-cards/{id}` 🔒 | 卡片当前版本：2.5.14 B 节的全部字段，加 `field_epistemic`、`narrative`、`gates_missing: string[]`（例如 `["G1:stop_loss_to_quantify"]`）、`refs: [{ref: string, title: string, url: string \| null}]`（研究员文档的出处编号，如 `R12`；**不是**列表项中引用规则的 `ref: <rule_id>`）、`validation_summary: {type: string, window: string \| null, benchmark: string \| null, cost_model: string \| null, oos_result: string \| null, trade_log_ref: string \| null} \| null`（研究员文档中的**外部**验证信息，产品不做回测）、`risk_level: card_risk_level` |
| GET | `/strategy-cards/{id}/versions` 🔒 · `/strategy-cards/{id}/versions/{no}` 🔒 | 版本历史，内容不可变 |
| POST | `/strategy-cards` 🔒 | 用户私有卡片（字段同 2.5.14 B 节）→ `201`；可能返回 `422 STRATEGY_INVALID_CONFIG` |
| POST | `/strategy-cards/{id}/versions` 🔒 | 新版本（`base_version_no` 乐观锁）；可能返回 `409 VERSION_CONFLICT` |
| POST | `/strategy-cards/{id}/promotion-requests` 🔒 | 申请晋级，后台跑 G1–G6 → `202 {review_id}` |
| GET | `/promotion-requests/{review_id}` 🔒 | `{decision: "pending"\|"approved"\|"rejected"\|"changes_requested", gate_results: [{gate: "G1".."G7", result: "pass"\|"fail"\|"warn"\|"skipped", detail}], fixture_runs: [{fixture_id, passed, diff}], g6_report: {trigger_rate: Stat, coverage: Stat, max_jaccard: string(decimal), quota_delta_per_min: int}}` |
| GET | `/admin/promotions` 🛡 · POST `/admin/promotions/{review_id}/decision` 🛡 | 审核决定 `{decision, comment}`；G7 文案需通过禁用词校验，否则返回 `422 COMPLIANCE_LINT_FAILED{terms}` |
| GET | `/feature-catalog` 🔒 | 只读，不分页：`[{feature_key, description, dimension, frequency, adjust, unit, warmup_bars, available_at, status: "declared"\|"verified_doc"\|"verified_live"\|"gap"\|"deprecated", epistemic_type}]` |
| GET | `/strategies` 🔒 | L2 模板：`?horizon=&lifecycle=&security_code=`（反查适用的模板）；元素 `{id, key, name（即其他对象中的 strategy_name）, horizons, current_version: {id, version_no, lifecycle}, health: {state, weight: string(decimal), n: int}}` |
| GET | `/strategies/{id}/versions/{vid}` 🔒 | 不可变配置（2.5.14 C 节），加 `lifecycle`、`card_version_id`、`param_hash`、`parent_version_id`、`internal_check: {done: boolean, method_types: ("factor_ic" \| "event_study" \| "param_robustness")[], checked_on: string(date) \| null}`（方案 A：用户只看到是否做过内部检验、方法类型和日期，**不含任何数值或通过与否**） |
| POST | `/strategies/{id}/versions/{vid}/derive` 🔒 | 改参派生私有版本 `{param_overrides: object}` → `201 {version_id}`；可能返回 `422 STRATEGY_PARAM_OUT_OF_RANGE{param, min, max}` |
| GET | `/strategies/{id}/versions/{vid}/tracking` 🔒 | 跟踪统计：`{scope: "mine"\|"site", by_horizon: [{horizon_days: 1\|5\|20, win_rate: Stat, avg_return_pct: Stat, avg_excess_pct: Stat, profit_loss_ratio: Stat, max_loss_streak: int}]}` |
| GET | `/strategies/{id}/versions/{vid}/lifecycle-events` 🔒 | 生命周期历史 |
| POST | `/admin/strategies/{id}/versions/{vid}/lifecycle` 🛡 | `{to: lifecycle, reason: string}` → `200 {from, to}`；可能返回 `409 INVALID_STATE_TRANSITION` 或 `422 PROMOTION_GATES_NOT_MET{gates}` |
| GET | `/horizon-assessments?security_code=` 🔒 | 周期分类结果（版本化）：`{suitable: horizon[], scores: {intraday_t: int, short: int, swing: int, long: int}（四个都有，0–100，不为 null）, reasons: [TextWithEvidence & {horizon: horizon, polarity: "for" \| "against"}]（每个周期 2–4 条，`reasons_per_horizon`）, inputs_missing: string[], caps: HorizonCap[], classifier_version: string, snapshot_id: string, evidence: Evidence[]}`（v0.2.2；v0.2.3 加 `caps`、`snapshot_id`、`evidence`；规则见 plan 6.1 `horizon_classifier.yaml`）。`reasons[].evidence_ids` 只在本响应的 `evidence[]` 中解析。`classifier_version` 匹配 `^(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)$`（如 `"1.1.0"`）。`inputs_missing`：所有周期合计缺失的 feature_catalog 键（`f.*`），去重、升序，永不为 `null`，无缺失为 `[]`；画像未填（`profile.*`）不进此数组，而以 `caps[].kind="requires"` 与 `against` 理由体现。用户覆盖周期须带 `fit_ack`（plan 2.5.3） |

### 7.5 L3 实例、限制与风控
| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/strategy-instances` 🔒 | POST `{strategy_version_id, scope: "account"\|"security"\|"watch_group", account_id, security_code: string \| null, horizon, param_overrides: object \| null, fit_ack: {horizon, acknowledged: true} \| null, budget_amount: string(decimal) \| null}` → `201 {id, status:"active", derived_strategy_version_id: uuid \| null, warnings: string[]}`。按 I1–I7 校验，可能返回 `STRATEGY_VERSION_NOT_RUNNABLE`、`CONSENT_REQUIRED`、`STRATEGY_HORIZON_MISMATCH`、`STRATEGY_FIT_ACK_REQUIRED`、`STRATEGY_PARAM_OUT_OF_RANGE`、`ENTITLEMENT_LIMIT_REACHED`、`INSTANCE_SCOPE_INVALID` |
| GET/PATCH | `/strategy-instances/{id}` 🔒 | PATCH `{param_overrides?, budget_amount?}`；改参会生成新的派生版本 |
| POST | `/strategy-instances/{id}/confirm` 🔒 | `proposed → active` |
| POST | `/strategy-instances/{id}/pause` · `/resume` · `/archive` 🔒 | 状态跃迁 |
| GET | `/strategy-instances/{id}/events` 🔒 | 实例事件 |
| GET/POST/DELETE | `/restrictions` 🔒 · `/restrictions/{id}` 🔒 | `{kind: "blocklist"\|"cooling_off"\|"mute", target_type: "security"\|"strategy"\|"instance", target_id: string, until: string(datetime) \| null, reason: string \| null}`。删除后会触发相关原因（`BLOCKLISTED`/`USER_MUTED`）重新检查 |
| GET/PUT | `/risk-controls` 🔒 | `[{control: risk_control, enabled: boolean, params: object, source: "system"\|"user"}]`；可能返回 `422 RISK_CONTROL_INVALID_PARAMS` |
| GET | `/risk-controls/events` 🔒 | 风控事件 |

### 7.6 候选信号、不可执行原因（没有"转计划"接口）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/candidate-signals` 🔒 ⚖ | `?state=&security_code=&instance_id=&horizon=`，排序为 `created_at desc` |
| GET | `/candidate-signals/{id}` 🔒 ⚖ | `CandidateSignal`（结构见下方定义与示例）。`gate_results[].gate` 是**运行时闸门名**（如 `gate_tradability`、`gate_data_fresh`），与晋级门禁枚举 `gate`（G1–G7）无关 |
| GET | `/candidate-signals/{id}/events` 🔒 ⚖ | 状态历史 `[{from, to, cause, at}]` |
| POST | `/candidate-signals/{id}/dismiss` 🔒 | `{note: string \| null}` → `state:"dismissed"` |
| GET | `/non-executable-reasons` 🔒 | `?status=active&signal_id=&code=`；v0.2.3 加 `signal_ids=`（逗号分隔，≤ 100，超出 `400 VALIDATION_ERROR`）与 `suggestion_id=`（该建议卡 `candidate_signal_ids` 的全部原因）；带这两个参数之一时**不分页**，返回 `{items: [...]}` |
| GET | `/non-executable-reasons/{id}` 🔒 | `{id, signal_id, code: reason_code, description, evidence: Evidence[], release_condition: ReleaseCondition, status, detected_at, released_at: string \| null, release_evidence: object \| null, released_by: "system" \| "user"}` |
| POST | `/non-executable-reasons/{id}/release` 🔒 | **手动解除**，只允许 `machine_checkable=false` 的原因：`{confirm: true, note: string \| null}`；可机器判断的原因返回 `409 REASON_NOT_MANUALLY_RELEASABLE` |

`CandidateSignal` 结构（v0.2.3 正式定义）：`{id: uuid, instance_id: uuid, strategy_version_id: uuid, strategy_key: string, strategy_name: string, lifecycle: lifecycle, security_code, name, horizon: horizon, state: candidate_signal_state, proposed_action: action, t_leg: t_leg \| null, score: int(0–100) \| null, confidence: {level: confidence_level, value: number(0–1)}, stops: Stops, rule_refs: RuleRef[]（非空）, evidence: Evidence[]（非空）, counter_evidence: TextWithEvidence[]（非空）, invalidation: TextWithEvidence[]（非空）, model_refs: ModelRef[], risk_flags: RiskFlag[], gate_results: [{gate: string, passed: boolean}], reason_ids: uuid[], plan_draft_ids: uuid[], valid_until: string(datetime) \| null, snapshot_id: string, feature_set_version: string, created_at: string(datetime), data_status, data_as_of, gaps}`。除标 `\| null` 的字段外均不为 null；数组无元素时为 `[]`。纯离场策略（§5.2）的 `proposed_action` 只能是 `reduce`/`sell`。

`CandidateSignal` 示例（数值全部虚构）：
```json
{"id": "00000000-0000-4000-8000-000000000031", "instance_id": "00000000-0000-4000-8000-000000000021",
 "strategy_version_id": "00000000-0000-4000-8000-000000000011", "strategy_key": "demo_trend", "strategy_name": "示例趋势策略", "lifecycle": "published",
 "security_code": "600000.SH", "name": "示例银行", "horizon": "swing", "state": "blocked", "proposed_action": "buy", "t_leg": null,
 "score": 70, "confidence": {"level": "medium", "value": 0.55},
 "stops": {"stop_loss": "9.00", "take_profit": null, "time_stop_days": 10},
 "rule_refs": [{"rule_id": "R1", "snippet_id": null, "snippet_version": null, "role": "entry", "dimension": "technical", "passed": true, "value": "10.10", "threshold": "9.90", "evidence_ids": ["E1"]}],
 "evidence": [{"id": "E1", "key": "close", "value": "10.10", "unit": "CNY", "provider": "mairui", "endpoint": "/hsstock/history", "data_as_of": "2026-11-02T15:00:00+08:00", "fetched_at": "2026-11-02T16:40:00+08:00", "epistemic_type": "fact"}],
 "counter_evidence": [{"text": "量比偏低（示例）", "expr": "volume_ratio < 0.5", "evidence_ids": ["E1"]}],
 "invalidation": [{"text": "连续 2 日收于均线下方（示例）", "expr": "close < ma(close, ma_fast) for 2 days", "evidence_ids": ["E1"]}],
 "model_refs": [], "risk_flags": [], "gate_results": [{"gate": "gate_tradability", "passed": true}],
 "reason_ids": ["00000000-0000-4000-8000-000000000041"], "plan_draft_ids": [],
 "valid_until": "2026-11-09T15:00:00+08:00", "snapshot_id": "00000000-0000-4000-8000-000000000051",
 "feature_set_version": "fs_1", "created_at": "2026-11-02T16:45:00+08:00",
 "data_status": "fresh", "data_as_of": "2026-11-02T15:00:00+08:00", "gaps": []}
```

### 7.7 计划草案与计划（确认草案是生成计划的唯一入口）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/plan-drafts` 🔒 ⚖ | 生成草案 `{signal_ids: uuid[](≥1)}` → `201 PlanDraft`。可能返回：没有 role ∈ {entry, exit, weakening} 且 passed = true 的规则引用（例如只有 model_refs）→ `422 PLAN_REQUIRES_EXPLAINABLE_SIGNAL`；信号状态不是 `drafted`/`released` → `409 INVALID_STATE_TRANSITION`；仍有生效原因 → `409 SIGNAL_NOT_EXECUTABLE{reason_ids}`；信号属于 `simulating` 模板 → `409 STRATEGY_VERSION_NOT_RUNNABLE` |
| GET | `/plan-drafts` 🔒 · `/plan-drafts/{id}` 🔒 | `PlanDraft {id, status: plan_draft_status, signal_ids, security_code, name, action, qty_range: {min, max, lot}, price_range: {low, high}, stops: Stops, max_loss_amount, max_loss_pct, fee_estimate: {amount, epistemic_type}, user_context_snapshot: {holding_qty, sellable_qty, cash, sector_pct}, risk_flags: RiskFlag[], judgment_checklist: [{id, question, required: boolean}], valid_until, market_rule_version_id}`，其中金额都是 `string(decimal)` |
| POST | `/plan-drafts/{id}/confirm` 🔒 ⚖ | `{checklist_answers: [{id, answer: "yes"\|"no"\|"unsure", note?}], risk_ack: true, chosen_qty: string(decimal), chosen_price: string(decimal), deviation_ack: boolean}` → `201 {plan_id, plan_version_no: 1}`。可能返回：必答项缺失 → `422 CHECKLIST_INCOMPLETE{missing}`；`risk_ack` 不为 true → `422 RISK_ACK_REQUIRED`；数量或价格超出区间且未确认偏离 → `422 DEVIATION_ACK_REQUIRED{fields}`；草案状态为 stale/expired → `409 PLAN_DRAFT_STALE` |
| POST | `/plan-drafts/{id}/discard` 🔒 | `{note}` → `status:"discarded"` |
| GET/POST | `/plans` 🔒 · `/plans/{id}` 🔒 | 操作计划；POST 只用于用户**手工**创建（`origin:"manual"`），不能引用候选信号 |
| POST | `/plans/{id}/versions` 🔒 | 修改计划，生成新版本（`base_version_no` 乐观锁） |
| POST | `/plans/{id}/close` 🔒 | `{status: "done"\|"cancelled", note}`；会触发 `SAME_DIRECTION_PLAN_EXISTS` 的解除检查 |

### 7.8 建议卡、日报、提醒、复盘、通知
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/suggestions` 🔒 ⚖ · `/suggestions/{id}` 🔒 ⚖ | 列表 `?security_code=&status=`（`status=active` 即当前卡，同一用户同一证券至多 1 张；没有 `current`，v0.2.3）元素为 `SuggestionSummary` 加 `security_code`、`name`；详情为 `Suggestion`（§5.2，内容不可变）；`/suggestions/{id}/chain` 返回取代链 |
| POST | `/suggestions/{id}/actions` 🔒 | `{kind: "viewed"\|"dismissed"\|"acted_trade_linked", trade_id: uuid \| null, note}`。**没有 `converted_to_plan`**；`draft_requested`、`draft_confirmed`、`reason_manually_released` 由服务端在相应接口里自动写入 |
| POST | `/suggestions/refresh` 🔒 ⚖ | `{security_code}`，只读缓存重算；可能返回 `409 SUGGESTION_REFRESH_TOO_FREQUENT` |
| GET | `/suggestions/{id}/tracking` 🔒 | `{t1: Stat, t5: Stat, t20: Stat}`，并附各期的价格依据 |
| GET | `/daily-reports` 🔒 ⚖ · `/daily-reports/{date}` 🔒 ⚖ | 盘后日报（不可变）：列表元素 `{date, generated_at, regime, reconciliation_status, stock_count}`；详情 `DailyReport`（§5.3） |
| GET | `/signals` 🔒 ⚖ | 盘中事件流 `?security_code=&kind=&since=`：元素 `SignalEvent`（规则事件，不含动作建议）。图表标记不设专用端点（v0.2.3）：分时标记用本接口、日 K 标记用 `/candidate-signals`，两者都**须带 `security_code`** |
| GET/POST/PATCH/DELETE | `/alert-rules` 🔒 · `/alerts` 🔒 | 提醒规则与触发记录 |
| GET/POST | `/reviews` 🔒 · `/reviews/{id}` 🔒 | 复盘 |
| GET | `/notifications` 🔒 · `/notifications/unread-count` 🔒 · POST `/notifications/{id}/read` 🔒 · POST `/notifications/read-all` 🔒 | 通知中心：列表 `?unread=&kind=` 元素为 `Notification`；`unread-count` → `{count: int}`；`read` 与 `read-all` 均返回 `204 No Content`，幂等（已读再标不改 `read_at`，v0.2.3） |
| GET/PUT | `/notification-preferences` 🔒 · `/channels` 🔒 | 渠道与免打扰设置 |

### 7.9 管理端（🛡；非管理员（含未登录）访问任何 `/admin/*` 一律返回 404，不暴露其存在，见 §1.3）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/ingest/status` 🛡 | 只读：`{leader: {instance_id, egress_ip_masked: "203.0.113.x", lease_expires_at}, budget: {per_minute_limit: int, used_last_minute: int}, queues: [{priority: "p0_intraday"\|"p1_daily"\|"p2_backfill", depth: int, oldest_age_s: int}], errors_24h: [{upstream_code: string, count: int}], ip_limit_alerts_24h: int, freshness: [{dataset, data_as_of, data_status}], licence: {expires_on: string(date), days_left: int}}`。**不返回 licence 内容**；`per_minute_limit` 等数值 **待 T003 验证** |
| POST | `/admin/ingest/pause` · `/admin/ingest/resume` 🛡 | 暂停或恢复外呼（迁移和冷备切换时使用，写审计） |
| GET/POST | `/admin/invites` 🛡 | 邀请码（v0.2.3 #27，T-B03c）：POST `{ttl_h: int \| null（默认 168，≤ 720）, bound_username: string \| null, note: string(≤200) \| null}` → `201 {id, code, expires_at, bound_username, note}`，**`code` 明文只在此响应出现一次**；GET 列表（分页）`{id, status: "active"\|"used"\|"expired"\|"revoked", created_by, created_at, expires_at, used_at, used_by, bound_username, note}`，不含明文或摘要；均写审计 |
| DELETE | `/admin/invites/{id}` 🛡 | 吊销邀请码 → `204`；已用或已吊销 → `409 INVALID_STATE_TRANSITION`；只改状态，不物理删除 |
| GET/PUT | `/admin/realtime-settings` 🛡 | 刷新间隔、分层上限（默认值 **待 T003 验证**） |
| GET/POST/PATCH | `/admin/llm/providers` · `/admin/llm/models` · `/admin/llm/routes` · `/admin/llm/prompts` 🛡；POST `/admin/llm/test`；GET `/admin/llm/usage` | API key 只写不读：响应只返回 `api_key_source: "env"\|"db"` 与 `api_key_set: bool`，不返回 key 或任何片段；`env` 来源（DeepSeek：`DEEPSEEK_API_KEY`，plan 2.7.1）不可经接口写入，PATCH 带 `api_key` → `422 VALIDATION_ERROR` |
| GET/POST/PATCH | `/admin/plans` · `/admin/subscriptions` 🛡 | 套餐与权益（不接支付） |
| GET/POST | `/admin/evaluation/runs` 🛡 · GET `/admin/evaluation/runs/{id}` 🛡 | 第三阶段启用（plan 第 9 节问题 26 已定），启用前返回 `404`。用户侧只通过模板版本的 `internal_check` 看到元信息（方案 A）。POST `{kind: "factor_ic"\|"event_study"\|"param_robustness"\|"daily_revalidation", target: {strategy_version_id? , feature_key?}, data_range: {from, to}, params: object}` → `202 {run_id}`；结果中 `metrics` 的每一项都是 `Stat` |
| GET | `/admin/audit-logs` 🛡 | 审计 |

### 7.10 元数据与健康
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/meta/enums` | 不需要登录、不分页；`Cache-Control: public, max-age=300` + 强 ETag，支持 `If-None-Match` → 304。结构见下 |
| GET | `/health/live` | 存活检查：进程能处理请求即 **200** `{status: "ok"}`，不访问任何依赖。用于容器健康检查（依赖故障时不应重启 api） |
| GET | `/health/ready` | 就绪检查：`{status: health_status, db: component_health, redis: component_health, ingest: ingest_health, checked_at, version}`。db、redis 都为 `ok` → **200**（ingest 非 `ok` 时 `status: "degraded"`，因为读接口仍可用缓存并通过 `data_status` 告知陈旧）；db 或 redis 为 `error` → **503**，`status: "down"`。用于 nginx/监控。不需要登录、不含错误细节（异常只进日志）；每个依赖检查超时 1 秒，并行执行 |
| GET | `/health` | `/health/ready` 的别名（兼容） |

- `/health*` 的响应体**不用** §2 错误外壳（503 时也返回上面的健康结构）。
- **ingest 心跳**（ingest 写、api 读）：leader 每 15 秒 `SET ingest:heartbeat <json> EX 600`，JSON 为 `{"ts": int(Unix 秒), "instance_id": string, "leader": true, "version": string, "budget_used_last_minute": int, "queue_depth": {"p0": int, "p1": int, "p2": int}}`；api 只依赖 `ts`，其余字段供 `/admin/ingest/status` 展示。判定顺序：Redis 不可用 → `unknown`；`ingest:paused` 存在（值为 JSON `{"by", "at", "reason"}`，管理员暂停时写入）→ `paused`；心跳缺失、无法解析或 `now - ts > 120` → `stale`；否则 `ok`。键名与阈值可配置（plan 6.1 `config/ingest.yaml`，环境变量 `INGEST_HEARTBEAT_KEY`、`INGEST_PAUSED_KEY`、`INGEST_STALE_AFTER_S`）。
- **`/meta/enums` 结构**（取值全部来自后端的集中定义，路由里不写死）：
```json
{"version": "v0.2.4",
 "enums": {"horizon": ["intraday_t", "short", "swing", "long"], "...": []},
 "reason_codes": [{"code": "T1_NOT_SELLABLE", "release_kinds": ["time"], "check_on": ["daily_close"], "manually_releasable": false, "note": "…"}],
 "error_codes": [{"code": "NOT_FOUND", "http_status": 404, "scope": "http"}],
 "import_codes": [{"code": "IMPORT_DUPLICATE_FILE", "severity": "warning", "scope": "file", "needs_action": "…"}],
 "risk_control_labels": {"stop_take": "RC1", "position_cap": "RC2", "total_exposure": "RC3", "sector_concentration": "RC4", "loss_streak_drawdown": "RC5", "plan_violation": "RC6"}}
```
  - `enums` 的键集合 == 第 3 节表名（不含 `reason_code`，它在 `reason_codes` 里展开）；取值为字符串数组（中文标签由前端维护，不在此下发）。
  - `error_codes[].scope`：`http`（§4 的 HTTP 错误码）或 `internal`（只在服务端内部用，如 `SIGNAL_NOT_EXPLAINABLE`）。§4.1 的 `IMPORT_*` 提示码只出现在 `import_codes`，**不**出现在 `error_codes`（v0.2 起 `IMPORT_ROW_COLUMN_MISMATCH` 等是提示码）。
  - `version` 为契约版本；ETag 由内容哈希得出。

---

## 8. SSE `GET /stream` 🔒
- `text/event-stream`；每 15 秒发一次 `heartbeat`；支持 `Last-Event-ID` 续传，服务端保留最近 10 分钟的事件；断线时客户端退回到轮询 `/notifications/unread-count`，终端与首页改为每 ≥ 15 秒带 `If-None-Match` 轮询 `/terminal`、`/today`。
- 每个事件：`id: <单调递增字符串>`，`event: <type>`，`data: <JSON>`。

| event | data | 说明 |
|---|---|---|
| `heartbeat` | `{at}` | |
| `quote` | `{items: [{security_code, name, price, change_pct, amount, t}], data_as_of}` | 只推送用户自选或持仓的证券，来自缓存 |
| `signal` | `SignalEvent`（§5.1，`kind: signal_kind`） | 盘中规则事件 |
| `candidate_signal` | `{id, security_code, name, state, proposed_action, strategy_key, strategy_name}` | ⚖ 候选信号新建或状态变化 |
| `reason_released` | `{reason_id, signal_id, code, released_at}` | ⚖ 原因已解除，系统正在重新检查 |
| `plan_draft_ready` | `{plan_draft_id, signal_ids, security_code, name, valid_until}` | ⚖ 生成了新的草案，等待确认 |
| `plan_triggered` | `{plan_id, condition, at}` | 提示"您的计划条件已满足"，**不下单** |
| `suggestion` | `{id, security_code, name, supersedes_id, summary: SuggestionSummary}` | ⚖ 终端用 `summary` 直接更新行 |
| `notification` | `Notification`（§5.1） | |
| `report` | `{date}` | 日报已生成 |
| `data_status` | `{dataset, data_status, data_as_of}` | 数据变旧或恢复（例如采集暂停） |

---

## 9. 契约测试要点（T-T17 等）
- 所有响应示例都能用 OpenAPI schema 校验通过；所有统计字段都带 `n`，缺少即失败。
- 候选信号和建议的响应中，P1 要求的四个数组都非空，`model_refs[*].role == "auxiliary"`。
- 不存在任何 `POST /candidate-signals/{id}/convert` 一类的接口；只有 `/plan-drafts/{id}/confirm` 能创建 `origin=plan_draft` 的计划。
- 未登录、普通用户、非 `approved` 账号访问任何 `/admin/*`（含 `/admin/evaluation/*`、不存在的子路径、用错方法、缺 CSRF）一律 404，响应体与不存在的普通路径逐字节相同（`request_id` 除外），不带 `Allow` 头；全文不得再出现“`/admin/*` 返回 403”。
- 任何响应、日志和错误信息中都不出现 licence、原始股东代码或资金账号（用虚构 fixture 做扫描）。
- 行情类接口在采集服务暂停时返回 `data_status:"stale"`，而不是 5xx，也不会触发上游调用。
- **命名（v0.2）**：OpenAPI schema 与所有示例中不得出现字段名 `evidence_id`、`pass`（规则结果）、平铺的 `stop_loss`/`take_profit`（必须在 `stops` 内）；所有 `score` 字段为 0–100 整数或 `null`；凡含 `security_code` 的对象都有 `name`。
- `Suggestion.dimension_matrix` 与 `strategies[].dimension_views` 一致（单元格的 `score`、`view`、`key_evidence_ids` 可由后者推出）；`executability.status` 与候选信号的原因状态一致。
- **导入提示码**：§4.1 与 plan.md 3.5A-1 的表逐行一致；共 46 个、21 error / 25 warning；夹具 `expected.json`（测试维护，唯一期望来源）中出现的 code 都在 §4.1 内。
- `/terminal`、`/today`：查询次数与行数无关（无 N+1）；`rows ≤ 300`、各列表 ≤ 50；带 `If-None-Match` 且未变时返回 304。
- **前端依赖**：`package.json` 与 lockfile 中不得出现 `ag-grid-enterprise` 或 `@ag-grid-enterprise/*`（终端表格只用 AG Grid Community，MIT）；CI 失败即阻断合并。
- 密钥与敏感信息扫描规则见 plan.md 7.4A（S1–S9）。
- 命名空间：`error_codes`、`reason_codes`、`import_codes` 三者没有重名；码类取值全部匹配 `^[A-Z][A-Z0-9_]*$`，其他枚举取值匹配 `^[a-z0-9][a-z0-9_]*$`。
- `/meta/enums`：`enums` 的键集合与第 3 节表名一致，每个取值与本文逐项一致（从 markdown 解析做快照对比）。
- 健康检查：停 db 或 redis → `/health/ready` 返回 503、`status: "down"`；只停 ingest 心跳 → 200、`degraded`、`ingest: "stale"`；写入 `ingest:paused` → `paused` 优先；`/health/live` 在依赖全停时仍 200。
- 405：`DELETE /api/v1/health` → `405 METHOD_NOT_ALLOWED` + `Allow` 头；非管理员（含未登录）对 `/admin/*` 用错方法 → 404，无 `Allow` 头。
- **v0.2.3**：
  - `/horizon-assessments`：每条 `reasons[].evidence_ids` 都能在同一响应的 `evidence[]` 中找到；`classifier_version` 匹配语义化版本正则；`inputs_missing` 非 null、去重、升序、每项以 `f.` 开头；每个分数 ≤ 对应周期 `caps[].cap` 的最小值；novice 夹具的 `short` ≤ 59 且 `caps` 含 `{horizon: "short", kind: "requires", rule_id: "SH0C"}`；同一夹具的 `intraday_t` ≤ 59 且 `caps` 含 `{horizon: "intraday_t", kind: "requires", rule_id: "IT0C"}`；`SH0C`/`IT0C` 不出现在 `/meta/enums.reason_codes`（#23）。
  - 认证（#24–#27）：用户名 3 位 → 400；`POST /me/consents` 版本不符 → 400；未同意 `sensitive_financial_info` 时 `POST /imports` → 403 `CONSENT_REQUIRED`；改密后旧 `sid` 401、响应带新 `sid`；超过绝对过期的会话 401；邀请码各类无效情形返回完全相同的响应体。
  - 纯离场策略：未持有的证券不出现 H-01 类结论；持有时其 `state`/`action` 只在 §5.2 允许的集合内；其单元格 `rules_total == 0`、`score == null`、`exit_hits ≤ exit_total`。
  - `consensus.status` 与行级 `divergent` 按 §5.2 的定义可由 `strategies[]` 重算得出。
  - OpenAPI schema 与所有响应示例中不得出现 provider 值 `local`；`Evidence.provider` ∈ `data_provider`；`cash_available` 只出现在 `/terminal.account`。
  - 所有 `RuleRef.dimension` 非空。
  - `POST /notifications/{id}/read`、`/notifications/read-all` 返回 204 且无响应体。
- **v0.2.4**：
  - 注册 `agreements` 含 `risk_disclosure` 或缺 `signal_risk_disclosure` → 400；`apply_note` 201 字 → 400。
  - `POST /me/consents`：`content_sha256` 与 `/meta/consent-docs` 不符 → 400；同一 key 先 grant 再 withdraw 后，`Me.consents[key].needs_reconsent=true`，库中两行都在；对 `consents`、`legal_documents`、`questionnaires`、`risk_assessments` 执行 UPDATE/DELETE/TRUNCATE 被触发器拒绝。
  - `REGISTRATION_MODE=invite` 且任一文书为 `"unversioned"` → 启动失败；`closed` 时 `/meta/consent-docs` 可返回 `"unversioned"`，`/legal/{key}` → 404。
  - 测评：`questionnaire_version` 旧 → 409；缺题 → 400 且 `fields` 列出缺的 `q_id`；K4 答错 → 400 `understanding_required` 且不入库；24 小时第 4 次 → 429；问卷响应中不出现 `points`、`score`、`correct`；同一答卷两次计分结果一致，`derived` 与 `risk_questionnaire.yaml` 的样例一致。
  - 没有有效测评时 ⚖ 接口 → 403，`required` 含 `"risk_assessment"`；测评过期超过宽限期后同样 403。
  - 未同意 `sensitive_financial_info`：`POST /imports`、`POST /trades` → 403；`POST /accounts` 不受影响。
  - CSRF：头与 Cookie 一致但与会话内令牌不符 → 403 `CSRF_FAILED`。
  - §4.1“处理选项”表中每个码的 `resolution_choices` 与实际返回一致；`force_import` 不带理由 → 400；`POST /trades/{id}/void` 两次 → 第二次 409。
