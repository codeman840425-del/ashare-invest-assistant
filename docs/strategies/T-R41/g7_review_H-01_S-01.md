# G7 人工核对稿｜H-01 / S-01（代理准备，不构成批准）

> **文首声明（必读）**：本报告由**策略研究员代理**按 plan.md:996「代理只准备报告，不代为批准」准备，供**用户本人**以管理员身份逐条核对卡片原文与规则对应关系后决定是否批准。**本文件不构成批准、不构成晋级、不构成荐股**。用语一律「候选信号 / 计划条件」。
>
> 依据原文：
> - plan.md:996 —「G7：由用户本人以管理员身份逐条核对卡片原文与规则的对应关系后批准。代理只准备报告，不代为批准。」
> - plan.md:3628（T-B80）—「G7 只能由用户本人以管理员身份审核并点击，任何代理不得代为批准或伪造。」
>
> 勾选列默认**未勾**。代理初核仅填「一致 / 不一致 / 缺证据」，**不是**最终结论。

---

## 0. 使用方式

1. 用户本人以管理员登录（浏览器交互会话，`password_login`），打开本表对应卡片与 `strategy-spec` / `validation` 块对照。
2. 逐行核验「卡片原文 ↔ 规格规则 ↔ 证据」；在「用户勾选」列勾选是否同意代理初核。
3. 全部拟批项勾选完成后，再在系统 `/admin/promotions/{review_id}/decision` 由**本人**点击批准（见 §3、§4）。本 Markdown **不能**代替该点击。

**对象卡**：
| card_id | 文件 | key | version_no | 说明 |
|---|---|---|---|---|
| H-01 | `docs/strategies/cards/hold_risk_monitor.md` | hold_risk_monitor | 2 | 纯离场系统组件（`mount_policy: system_only`） |
| S-01 | `docs/strategies/cards/st_pullback_ma.md` | st_pullback_ma | 1 | 短线候选信号卡（正式化自 T-R16 草稿） |

**公共证据（本工作树当前 HEAD，代理本地跑通；非库内 promotion 报告）**：
| 检查 | 命令/路径 | 结果（代理观测） |
|---|---|---|
| 格式+fixtures 虚构标 | `docs/strategies/golden/check_T-R15.py` | PASS（含 H-01 11 fixtures、S-01 8 fixtures） |
| horizon census | `docs/strategies/P2N-R10/check_horizons.py` | PASS identity=43 / scope=112（本单登记后将 +1 非身份文件） |
| 相关提交 | `fe2afa5`（T-R40 S-01 FX 标虚构）、`055105a`（T-R25 S-01 正式化）、`e3daf66`/`b752487`（H-01 v2/v1） | 仅文档史；**不是** G7 批准记录 |

---

## 1. H-01｜hold_risk_monitor v2 逐条核对

| # | 核对主题 | 卡片原文（文件:行） | 规格/规则（文件:行） | 当前证据 | 代理初核 | 用户勾选 |
|---|---|---|---|---|---|---|
| H1 | 身份 key/version/card_id | hold_risk_monitor.md:31-36 `key`/`version_no:2`/`card_id:H-01` | strategy-spec:94-95 同 key/version | check_T-R15 key 一致检查；R10 正式身份 record | 一致 | ☐ |
| H2 | 多周期 horizons | :35 `[intraday_t, short, swing, long]` | spec:97 同列表 | check_T-R15 horizons 枚举；R10 `explicit_multi` | 一致 | ☐ |
| H3 | 纯离场 / 无开仓 | 文首:3 `mount_policy: system_only`；无 entry 列表 | spec:106-114 仅 exit/weakening/counter/invalidation；action_map 无 buy/add | check_T-R15 纯离场分支；文首自称 G1 豁免依据 | 一致 | ☐ |
| H4 | 假设 hypothesis | card:39-43 | （叙述性；无独立 DSL） | 仅文档存在；无独立语义 checker | 缺证据 | ☐ |
| H5 | 维度 dimensions | card:44-46 technical + sector_market | 规则 dimension 字段 :106-113 | check_T-R15 dimension 枚举 | 一致 | ☐ |
| H6 | 离场 exit X1/X2 | 正文:8；card exit:52-56 | spec:106-107 expr | check_T-R15 ref↔role；fixtures H01-FX3/FX4 | 一致 | ☐ |
| H7 | 转弱 weakening W1–W3 | 正文:9；由 exit/weakening 角色体现 | spec:108-110 | fixtures H01-FX2/FX5/FX6 | 一致 | ☐ |
| H8 | 反证 counter C1/C2 | card:47-49；正文:10 | spec:111-112 | fixtures H01-FX9；C1 用 `f.market_regime_idx` | 一致 | ☐ |
| H9 | 失效 invalidation I1 | card:50-51 | spec:113 | fixtures H01-FX9 | 一致 | ☐ |
| H10 | 参数 schema | — | spec:98-104 ma_long/ma_break_days/… | check_T-R15 param 类型/范围 | 一致 | ☐ |
| H11 | 数据 data_needs | card:58-72（含 qfq、limit、suspended、market_regime_idx 等） | 规则 required_features 引用同键 | check_T-R15 data_needs∈feature_spec catalog | 一致 | ☐ |
| H12 | 标的 universe | card:74-77 持仓范围；北交所不含见 a_share | screen:null :118 | 文档层一致；**运行时挂载策略未在本报告核实** | 缺证据 | ☐ |
| H13 | A 股约束 | card:89；正文:17 T+1/涨跌停/零股 | fixtures FX4/FX6/FX7/FX10 | check_T-R15 reason_codes/lot_rule | 一致 | ☐ |
| H14 | 成本滑点 | card:82-88；正文:20 离场不因成本放弃卖出 | validation 成本叙述 | 无独立成本数值回放证据 | 缺证据 | ☐ |
| H15 | 验证/fixtures | validation 块 fixtures H01-FX1..11（:136+）均 `【虚构】` | expect state/action | check_T-R15 PASS（11 fixtures） | 一致 | ☐ |
| H16 | 合规/禁用词文案 | 卡内无收益承诺句（代理目视） | G7 decision 另有 compliance_lint（契约 api-contract.md:953） | **未跑**禁用词服务端校验 | 缺证据 | ☐ |
| H17 | **horizon 多值风险** | horizons 四周期 :35 | 实例/跟踪若缺 horizon → gap（T-R35 README:89/97；T-A74 B2） | 文档裁定有；**后端定点用例 T-A74 称未实现**（T-R35:108） | 缺证据（运行缺口） | ☐ |
| H18 | null/gap / insufficient_data | 正文:16 预热不足 `passed=null`；FX8 limit null | fixtures H01-FX8 | check_T-R15 含该例；实盘 null 传播**未在本报告实测** | 缺证据 | ☐ |
| H19 | 不可执行原因码 | FX4 T1_NOT_SELLABLE；FX7 LIMIT_LOCKED；FX10 SUSPENDED | expect.reason_codes | check_T-R15 与 api-contract 原因码表交叉 | 一致 | ☐ |
| H20 | 选股/入场 | **无**（纯离场，设计如此） | action_map 无 buy | check_T-R15 允许 exitonly | 一致 | ☐ |

**H-01 代理小结**：格式与 fixtures 代理初核多为「一致」；**阻塞/风险**为 H17（多 horizon + 缺 horizon 运行处理仅有文档裁定）、H18（null 实盘）、H14/H16（成本与合规 lint 缺本机服务证据）。**不得**据此视为已过 G7。

---

## 2. S-01｜st_pullback_ma v1 逐条核对

| # | 核对主题 | 卡片原文（文件:行） | 规格/规则（文件:行） | 当前证据 | 代理初核 | 用户勾选 |
|---|---|---|---|---|---|---|
| S1 | 身份 key/version/card_id | st_pullback_ma.md:28-33 | spec:91-92 | check_T-R15；R10 正式身份 `st_pullback_ma@1:current_formal…` | 一致 | ☐ |
| S2 | horizon=[short] | card:32；spec:94 | RC5 short→5（inventory rc5_boundary） | R10；T-R35 B4 主口径 T+5 | 一致 | ☐ |
| S3 | 假设 hypothesis | card:35-40 | 叙述性 | 无独立语义审核器 | 缺证据 | ☐ |
| S4 | 维度 | card:41-43 technical + sector_market | 规则 dimension | check_T-R15 | 一致 | ☐ |
| S5 | 入场 E1–E4 | 正文:9；card entry:44-48 | spec rules E1–E4（约:105+） | fixtures S01-FX1；check_T-R15 ref | 一致 | ☐ |
| S6 | 过滤/否决（正文 F1/F2/V1） | 正文:10 | spec 对应 filter/veto 规则行 | FX1/FX4；V1→vetoed | 一致 | ☐ |
| S7 | 反证 C1/C2 | card:49-51 | spec counter 规则 | FX 覆盖有限；结构检查通过 | 一致 | ☐ |
| S8 | 失效 I1 | card:52-53 | spec invalidation | check_T-R15 | 一致 | ☐ |
| S9 | 退出 X1–X3 | 正文:12；card exit:54-57 | spec exit + stops:137（硬止损公式、time_stop_days:5） | FX7/FX8 | 一致 | ☐ |
| S10 | 参数 schema | — | spec:95-104 rs_min/touch_pct/… | check_T-R15 | 一致 | ☐ |
| S11 | 数据 data_needs | card:58-76 | required_features | check_T-R15∈catalog | 一致 | ☐ |
| S12 | 标的 universe | card:78-81 全市场优先持仓/自选；bse:false | screen:null | 文档一致；**选股执行链未跑** | 缺证据 | ☐ |
| S13 | A 股约束 | card:86；正文:19 | FX5 涨停锁、FX 科创板等 | check_T-R15 | 一致 | ☐ |
| S14 | 成本滑点 | 正文:21–22（estimate） | validation_summary:87 含 cost_model | 无独立回放数值证据 | 缺证据 | ☐ |
| S15 | 验证/fixtures | validation S01-FX1..8，desc 均以 `【虚构】` 开头（T-R40 fe2afa5） | expect | check_T-R15 PASS；**改前** d75b0ec/d2e7d51 曾因未标虚构失败 | 一致 | ☐ |
| S16 | 合规文案 | 卡头:5「结论只由规则决定；AI 只做中文解释」 | G7 compliance_lint 服务端 | **未跑** lint API | 缺证据 | ☐ |
| S17 | 与草稿关系 | 卡头:3 由 T-R16 草稿正式化；草稿 `T-R16/S-01_…` 已非「知识卡 vN」身份 | R10：草稿 role=`research_draft_superseded_by_formal_card` | R10 census | 一致 | ☐ |
| S18 | 正式化差异 E1/X4 | 卡头:6 E1 改绝对涨幅；X4 未进 v1 | 规则无 rank_pct / 无 X4 | 文档自述；需用户确认是否接受缺口 | 缺证据（产品接受度） | ☐ |
| S19 | 不可执行原因 | FX5 LIMIT_LOCKED；FX6 SUSPENDED；FX7 T1_NOT_SELLABLE | expect.reason_codes | check_T-R15 | 一致 | ☐ |
| S20 | 仓位/选股 screen | screen:null :140 | 无自动筛股 DSL | 设计为 null；实例侧如何选股**缺证据** | 缺证据 | ☐ |

**S-01 代理小结**：机器可读块与虚构 fixtures 代理初核多为「一致」；**风险**为 S12/S14/S16/S18/S20（执行链、成本、合规 lint、正式化取舍、选股）。**不得**视为已过 G7。

---

## 3. 「13:12:55 管理员审批」与 G7 的关系（只读证据）

| 线索 | 内容摘要 | 来源 | 性质 |
|---|---|---|---|
| 代办授权记录 | 称用户私聊原话授权编排者代办 G7；写「2026-11-09 13:12:55（丹佛）H-01、S-01 以管理员密码登录会话批准，ack_warn_gates=["G6"]」 | `/workspace/team/rules/g7-delegation-2026-11-09.md` | **编排者维护的记录**；本代理只读打开文字，**未独立核验用户本人授权** |
| T-R35 立场 | 「编排者称已过 G7…由编排者代办，尚未经用户本人在架构师处确认，**当前不视为已批**」；plan:996 列为未关闭项 | `docs/strategies/T-R35/README.md:3-4` | 研究员文档转述 |
| plan 现行条文 | 用户本人逐条核对后批准；代理不代批；T-B80 同旨 | plan.md:996、:3628 | 仓库权威条文（**未因代办文件而修订**） |
| 系统门禁 | `human_admin`：拒 `Authorization` Bearer；要求会话 `origin=="password_login"`，否则 `403 HUMAN_SESSION_REQUIRED` | `src/backend/app/api/v1/promotions.py:56-71` | 代码 |

**代理结论（供用户审）**：

1. **有证据的**：仓库内存在「编排者称已用管理员密码会话做过 decision」的**文字记录**；代码层 G7 decision **可以**强制「人类密码登录会话、拒 Bearer」。
2. **没有证据的（本代理未见到）**：用户本人对 H-01/S-01 **逐条**核对卡片原文↔规则的可追溯勾选/批注；架构师对 plan:996/3628「禁止代批」的条文修订。
3. 因此对照 plan.md:996「由用户本人以管理员身份**逐条核对**…后批准」——在**缺少用户本人逐条核对证据**的前提下，代理初核为：**不满足**将该 13:12:55 记录等同为已完成的 G7。
4. **系统能证明 / 不能证明**：`password_login` 人类会话只能证明「当时请求来自密码登录的管理员会话」（promotions.py:56-71），**不能**证明「已逐条完成原文↔规则核对」。人类会话 ≠ 逐条核对。

---

## 4. 改到 `simulating` 还缺哪一步

按 plan 2.5.13 / 2.5.0B / T-B80（:958-960 契约、:996、:3628、api-contract.md:953/:960）：

| 步骤 | 要求 | 当前（代理只读） |
|---|---|---|
| A | G1–G6 自动门禁无 `fail`；warn 须 ack | **缺证据**：本报告未查询库内 `strategy_promotion_reviews.gate_results`（红线不读库敏感内容） |
| B | **用户本人**基于本报告（或等价门禁报告）逐条核对并在 UI 批准 G7；可追溯审计 | **未满足**（见 §3） |
| C | `POST .../lifecycle` `{to:simulating, review_id, password}`；审核须 approved、非 stale、哈希一致；同人类会话+密码 | **未执行**（红线：本单不改 lifecycle） |
| D | 晋级后仅模拟候选信号、标「模拟中」、不生成计划草案 | 取决于 C |

**剩余关键路径（引文）**：用户本人完成 B → 后端/管理员会话走 api-contract.md:953 decision 与 :960 lifecycle（T-B80 plan:3628）。代理与脚本不得代填密码、不得代点批准（plan:996/3628；团队规则）。

其他前置：若 G2/G6 对某字段仍为 declared/警告，以当时门禁报告为准（本文件不臆测库内状态）→ 标「缺证据」。

---

## 5. 计数（代理初核，供报告汇总）

| 卡 | 项数 | 一致 | 不一致 | 缺证据 |
|---|---|---|---|---|
| H-01 | 20 | 14 | 0 | 6 |
| S-01 | 20 | 13 | 0 | 7 |
| 合计 | 40 | 27 | 0 | 13 |

（用户勾选全部默认未勾；最终以用户勾选与系统审计为准。）

---

*文件路径：`docs/strategies/T-R41/g7_review_H-01_S-01.md`｜任务 T-R41｜代理准备*
