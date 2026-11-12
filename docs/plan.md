# A股个人投资研究与决策助手 · MVP 架构方案（T001）

- 作者：架构师
- 日期：2026-11-01
- 状态：待编排者 / 用户评审
- 配套文档：[`docs/api-contract.md`](./api-contract.md)（REST 接口契约）
- 输入：`/workspace/team/vision.md`（含 11:24 账号审核、11:25 交割单导入、11:29 方法库、11:30 通知、11:32 主线、11:35 刷新/LLM/上限、11:37 部署/规模/质量/UI/会员、**11:42《策略库需求》（权威）**等补充）、`/workspace/team/tasks/T001.md`、麦蕊智数官网文档（2026-11-01 实际抓取）

> 阅读提示：标记 **【已核实】** 的内容来自 2026-11-01 实际抓取的麦蕊官网文档页（`/hsdata`、`/hszsdata`、`/hanalyse`、`/bjdata`、`/kcdata`、`/factordata`、`/getlicence`、`/packs`、`/faq`、`/help`、`/legal`、`/updatelog`）；**只是"文档写了"，尚未用真实证书实测**。标记 **【待核实】** 的内容是文档不一致、文档缺失或需要用真实 licence / 商务沟通确认的事项。本文不臆造任何接口名、配额或价格。
>
> **T003 报告已于 2026-11-01 12:10（MDT）收到，结果见 4.0**：只有实时快照与部分 K 线完成实测，其余仍未实测；下文的【待 T003 验证】标记对 4.0 中"已实测"的项视为已验证，对其余项读作"待 T003 补测"。
>
> **【待 T003 验证】（2026-11-01 12:05 起）**：后端正在用真实证书做实测（T003，报告路径 `/workspace/team/reports/T003-mairui-capability.md`）。在报告出来之前，**所有麦蕊数据可用性结论**都标为【待 T003 验证】，包括原标为【已核实-文档】的项，改写为【文档已列·待 T003 验证】，例如接口、字段、因子、限流、历史深度、刷新间隔和自选上限推算。报告出来后搜索"T003"即可逐项定稿。非麦蕊事项（法规、备案、渠道价格、开源许可证等）仍沿用【已核实】/【待核实】。

---

## 0. 结论摘要（一页看懂）

| 维度 | 结论 |
|---|---|
| 产品定位 | **MVP 主线（最高优先级，第 0A 节）**：对每位用户的持仓与自选股，每天**盘后分析** + **盘中实时操作建议**（买入/加仓/持有/减仓/卖出/等待）。每条建议都带理由、证据（时间戳、来源、认识论类型）、反证、失效条件、置信度和策略版本，**不可变存档**。建议由**确定性规则 + 因子**产生；LLM 只写解释。研究、计划、提醒、复盘等其他能力放在主线之后。 |
| 策略库 | 覆盖四种周期：日内做T、短线、波段、中长线。六个维度：技术、资金、基本面、情绪、板块与大盘、消息。策略由引擎的三层（L1 卡片 / L2 模板 / L3 实例）承载，具体策略见 `docs/strategies/`（由策略研究员维护）；每个策略的规则、所用特征和数据来源都对用户可见。导入后**自动判定每只股票适合的周期与策略**并给出理由，用户可改。**信号矛盾时不合并结论**，按"维度 × 策略"矩阵并列展示。**六项风控**逐项可开关。模拟跟踪统计各策略的胜率与盈亏，并可开关**自动降权**（只影响排序）。 |
| 技术栈 | 后端：**Python 3.12 + FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic**。任务：**Celery + 单实例 Beat + 唯一的行情采集服务 `ingest`（全站唯一调用麦蕊，2.1A）+ 盘中信号进程 `signal-rt`**。存储：**PostgreSQL 16 + TimescaleDB（行情时序 hypertable，3A）+ Redis 7**。前端：**React 19 + TS + Vite + TanStack Query + antd 6（暗色 + compact）+ AG Grid Community + TradingView Lightweight Charts**，深色交易终端风格，仅桌面。部署：**Docker Compose 单机**，配置全部走环境变量，不绑定任何云厂商。 |
| 规模与部署 | V1 面向 10–100 名用户：单机，**不用 k8s，不拆微服务**。先在本地测试，之后买服务器迁移（1.3 节附迁移手册）。域名**未备案**：对公网开放前必须解决（第 9 节问题 4）。 |
| 数据接入 | 只有**行情采集服务 `ingest`**（单副本、单活锁）能调用麦蕊；**每位用户用自己的麦蕊证书**（【用户已定 2026-11-02】，2.1B）：证书加密存库、只有 `ingest` 能解密、从不回显；固定出口 IP、**每张证书一个令牌桶**（默认每分钟 3,000，可配置）和各自的优先队列（盘中实时 > 日批 > 历史回补）、证书之间轮转调度；singleflight、原始响应留存；故障切换只做冷备；其他服务和用户只读缓存和数据库（2.1A）。**数据默认不跨用户共享**：每位用户看到的行情只来自用他本人证书拉取的数据（共享一份【待麦蕊书面确认】，7.1）。盘中按"该证书的去重证券池"分层刷新。 |
| 刷新与上限 | 由配额推导，参数全部可配置（0A.6、0A.7）：<br>• 多股快照默认 **15 秒**一轮（N ≤ 2,000）；<br>• Tier-1 **1,500 只每分钟**取 Pro 1 分钟 K，Tier-2 每 5 分钟；<br>• 系统 universe **硬上限 4,000**；<br>• 每用户自选 **100**、重点关注 **20**。<br>以上依据官网文档推导，**【待 T003 验证】**，实测后调到上限。 |
| LLM | 供应商无关的网关，**先接 DeepSeek**（OpenAI 兼容适配器，第 9 节问题 16）：base_url、模型、超时与重试写在 `config/llm.yaml`（6.1），DeepSeek 的 key 只从环境变量 `DEEPSEEK_API_KEY` 读取（2.7.1，已按官方文档核实），按任务路由，带超时、重试、备用链和预算，记录 token 与成本，提示词模板版本化。输入是证据，输出是带 `[E#]` 引用的解释；**不决定动作**，失败时回落到模板。 |
| 账号 | 用户名 + 密码（argon2id），**无验证码**。V1 **注册默认关闭**（`REGISTRATION_MODE=closed`，本人账号由 CLI 创建）；以后开放为邀请制，注册后为 `pending`，管理员批准后才能使用。防滥用靠限速和锁定（第 9 节问题 1）。 |
| 持仓来源 | 主要导入通达信（TDX）导出的交割单与持仓 .txt（插件化解析器、GBK/UTF-8 识别、46 个 `IMPORT_*` 提示码、预览确认、去重、以摊薄成本对账，3.5A），手动录入为辅。持仓一律由成交重建。**股东代码等敏感标识做 HMAC + 掩码，原始文件加密后存放在仓库外并做访问控制。** |
| 数据模型关键 | `epistemic_type ∈ {fact, estimate, hypothesis, execution}`。研究、计划、复盘、建议、策略版本、日报都是"头表 + 不可变版本"，并绑定 `data_snapshot`（`data_as_of` / `fetched_at`）。行情表带 `first_seen_at`，支持按原貌回看。 |
| 跟踪与会员 | **不做回测**：每条建议在 T+1、T+5、T+20 对比基准做模拟跟踪，结果用于复盘和策略降权。**会员模型只预留**（套餐、权益、订阅），不接支付。 |
| 质量 | 质量优先（8.0 节）：golden、回放、契约、E2E 测试；领域包覆盖率 ≥ 90%；CI 门禁和发布门禁；仓库密钥与敏感信息扫描（7.4A）。**接口字段以 `api-contract.md` 为唯一事实来源**。 |
| 最大风险（阻断级） | ① **证券投资咨询资质**：对具体股票给出买卖动作，属于法定许可业务。V1 已定为**仅本人使用**、注册关闭、免费，开放他人前再评估（7.2 节，**第 9 节问题 1**）。② **麦蕊条款禁止再分发**，需要书面授权（7.1 节）。③ **ICP 备案**（7.3 节）。④ 新闻、舆情缺口（4.5 节、2.5.2 节）。 |

---

## 0B. 设计原则（硬性，不做取舍）

> 下列原则高于本文其他条目；与之冲突的设计一律按本节修改。P1 是用户 11:56 确认的**硬性原则**，其余原则来自此前确认的需求。

| # | 原则 | 落地方式（数据模型 / 契约 / 质量门禁） |
|---|---|---|
| **P1** | **策略输出必须可解释。** 每条候选信号都能追溯到：触发它的规则（规则 ID + 策略版本）、所用数据（来源、证券、字段、时间戳）及当时的取值、反证、失效条件。 | `candidate_signals.rule_refs[]`（`{strategy_version_id, rule_id, role, expr, passed, value, threshold}`）、`evidence[]`（`{id, provider, endpoint, security_code, field, value, unit, data_as_of, fetched_at, epistemic_type}`，其他字段一律用 `evidence_ids[]` 引用）、`counter_evidence[]`、`invalidation[]` 全部**非空才能写入**（数据库 CHECK + 服务层校验，缺任一项写入失败并记 `SIGNAL_NOT_EXPLAINABLE`）。证据值随不可变快照保存，可按原貌回看。 |
| **P1a** | **LLM 只把结构化证据改写成文字，不得给出结论或动作。** | LLM 输出必须是 `{paragraphs:[{text, cites: string[]}]}`（`cites` 中是证据的 `id`）。守卫逐句校验：每个数字、每条事实性陈述都要引用存在的证据 `id`，数字须与证据值一致（允许按约定四舍五入）；出现动作词（买入/卖出/加仓等）、目标价、收益承诺或未引用的数字 → **拒绝**，回落模板，并在 `llm_calls.guard_result` 中记录原因（2.7）。LLM 文本只出现在 `explanation` 字段，任何业务逻辑都不读取它。 |
| **P1b** | **黑箱模型（机器学习、合成因子模型等）只能作为辅助参考维度，不能单独触发操作计划。** | 信号里的 `model_refs[]` 统一标 `role: "auxiliary"`、`epistemic_type: "estimate"`，不计入规则满足率，也不改变动作。**生成计划草案的前提**：至少有一条 `rule_refs[].passed = true` 的可解释规则信号；只有 `model_refs` 时返回 `PLAN_REQUIRES_EXPLAINABLE_SIGNAL`。 |
| P2 | **候选信号 ≠ 操作计划。** 系统从不直接输出"立即买入"。 | 分三步，详见 2.5.8：<br>① 扫描产生 `candidate_signals`；<br>② 结合真实持仓、现金、限制和风控，生成 `plan_drafts`，或写出 `non_executable_reasons`；<br>③ 用户确认后才成为 `action_plans`。 |
| P3 | **不可执行必须说明原因，并给出解除条件。** | 每条 `non_executable_reasons` 都带 `release_condition`（尽量是可机器判断的表达式），系统持续监控；条件解除后重新评估，并通知用户（2.5.9）。 |
| P4 | **冲突并列展示，不合并结论。** | 按"维度 × 策略"矩阵展示，`consensus` 只统计各方向的数量（2.5.4）。 |
| P5 | **先解释、后运行。** | L1 知识卡只用于解释；只有通过晋级门槛的卡才能成为 L2 可运行模板（2.5.0）。 |
| P6 | **不可变与可回看。** | 信号、建议、计划版本、策略版本、日报都只追加；回看时显示当时的快照。 |
| P7 | **诚实标注数据。** | 所有内容都带 `epistemic_type`；数据缺口通过 `gaps` 显式展示，不推断空值；未核实的内容标【待核实】。 |
| P8 | **~~共享数据~~按证书隔离数据、单一出口。** | 麦蕊只经唯一的行情采集服务 `ingest` 调用（单副本、固定出口 IP、licence 只在此容器，2.1A）；~~行情全站共享；用户增长不会线性放大外部调用~~（v0.2.6 起按证书隔离，见 2.1B；只有证券公开主数据全站一份，第 9 节问题 51）。 |

**P1 质量门禁**（T-T16，CI 必过）：
- **属性测试**：随机快照生成的每条候选信号都必须有非空的 `rule_refs`、`evidence`、`counter_evidence`、`invalidation`；每个 `evidence_ids` 中的引用都能在快照中解析，且值一致。
- **golden 测试**：逐字段比对追溯链。
- **LLM 守卫测试**（T-T12）：注入未引用的数字、动作词、错误数值，必须全部被拒绝。
- **计划门槛测试**：只有 `model_refs` 的信号无法生成计划草案。
- **契约测试**：响应中缺少追溯字段即判失败。

## 0A. MVP 主线（最高优先级）：持仓/自选的盘后分析 + 盘中实时信号与操作建议

> 2026-11-01 11:32 用户指示：**这是 MVP 的第一主线，先于其他能力交付**。它取代本文早先"不输出买卖建议"的产品边界：系统**要**基于规则与因子给出操作建议（买入/加仓/持有/减仓/卖出/等待），风险改由第 7.2 节的合规设计承接（对外开放前必须拍板，见第 9 节问题 1）。五种能力中，"看清处境（盘后日报）""在需要时得到帮助（盘中信号提醒）""形成行动计划（建议→计划）""复盘（建议不可变留档）"都围绕这条主线组织；"找机会（策略库筛选）"为其提供策略。

### 0A.1 用户看到什么
| 时点 | 产出 | 内容 |
|---|---|---|
| 每个交易日收盘后（约 17:30 起，因子 16:30/17:00 后可用） | **盘后日报**（每用户一份） | 对该用户**每只持仓与自选股**逐只给出：当日事实（涨跌、量能、资金流、公告/事件）→ 每个启用策略的判断（条件逐条通过/不通过、策略适配分）→ **次日操作建议**（动作 + 理由 + 依据数据 + 反证 + 失效条件 + 置信度 + 策略及版本）；账户层：仓位、集中度、对账状态、数据缺口。 |
| 交易时段 9:15–11:30、13:00–15:00（交易日历驱动） | **盘中信号与建议更新** | 实时行情刷新后增量评估；当某只股票的**信号状态翻转**（如跌破失效价、突破触发价、趋势条件由真变假）或**失效条件触发**时，生成新的建议版本并站内实时推送（SSE），说明发生了什么、影响哪份建议/计划、现在该核对什么。 |
| 任意时刻 | **建议详情 / 历史** | 每条建议**不可变**存档，绑定当时的数据快照（含时间戳与来源）；可按原貌回看，并与之后实际成交和结果连到复盘。 |

### 0A.2 建议（Suggestion）必备内容（缺一不可，否则不生成）
| 字段 | 说明 | epistemic_type |
|---|---|---|
| `strategies[].action` | **每个启用策略各自一个动作** `buy / add / hold / reduce / sell / wait`（中文展示见 7.2："规则信号：买入条件满足"等）；**不合成单一结论**，顶部 `consensus` 只报告"一致 / 分歧（各动作计数）"（2.5.4） | — |
| `strategies[].dimension_views[]` | 六维度（技术/资金/基本面/情绪/板块与大盘/消息）各自观点 bullish/bearish/neutral/unknown + 分数（`score`，0–100 整数，unknown 时为 null）+ 逐条规则结果（`passed`、`evidence_ids`）；另有 `dimension_matrix`（单元格含分数与 ≤ 3 个关键证据）与 `divergence[]` | fact / hypothesis |
| `strategies[].stops` | 风控 RC1：每个策略结论带 `stops{stop_loss, take_profit, time_stop_days}`（可关；契约共享对象 `Stops`） | estimate |
| `strategies[].state / strategy_name / candidate_signal_id / t_leg` | 该策略的评估状态（`strategy_eval_state`）、展示名、对应的候选信号（hold/wait 时为 null）、做T腿 | — |
| `executability.status` | `executable / blocked / not_applicable`（2.5.5） | — |
| `risk_flags[]` | 六项风控结果（2.5.6），可标记 `gated_actions`，但不改写策略动作 | fact / estimate |
| `strategies[].score` | 0–100，**该策略规则满足度**（规则透明权重加权，见 2.5）；不是"股票好坏评分"，不跨策略合成 | estimate |
| `confidence` | `high / medium / low` + 0–1 数值；每策略单独：数据完整度、策略内维度一致度、条件余量（离阈值多远）按固定公式算出 | estimate |
| `reasons[]` | 理由：满足的条件，每条引用证据 ID | fact（条件结果）/ hypothesis（策略逻辑） |
| `evidence[]` | 依据数据：`{id, key, value, unit, data_as_of, fetched_at, provider, endpoint, epistemic_type}`，全部来自 `data_snapshot`；`id` 在本条建议内唯一，其他字段用 `evidence_ids[]` 引用 | fact / estimate |
| `counter_evidence[]` | 反证：不满足的条件、风险因子偏高项、负面事件、其他策略的相反结论 | fact / hypothesis |
| `invalidation[]` | 失效条件：结构化（如 `price_below 9.50`、`ma_trend != up`、`roe_ttm < 8 at next report`），盘中自动监控 | hypothesis |
| `strategies[].strategy_version_id + version_no + horizon` | 产生各结论的策略版本与周期；`priority_weight`（2.5.7 自动降权结果，只影响排序） | — |
| `user_context` | 用于适配判断的画像版本、持仓数量/成本、该股占总资产比例 | fact |
| `snapshot_id` | 数据快照；`data_status`（fresh/stale）；`generated_by`（`rules_engine@版本`）；`explanation_text`（可选，LLM 或模板生成，见 0A.4） | — |
| `supersedes_id`、`status` | 同一股票前一条建议（形成建议链）；状态 `status ∈ active / superseded / invalidated / expired`（契约 `suggestion_status`）只在头表变化，正文不可变；API 返回时把头表状态并入建议对象 | — |

### 0A.3 盘中链路：行情刷新与信号计算（间隔由配额推导、配置驱动）
```
Celery Beat + 唯一 `ingest`（外呼）+ `signal-rt`（计算）（交易日历驱动，Asia/Shanghai）；下面 ②③ 的拉取都由 `ingest` 按 P0 队列执行
  09:15–09:25 集合竞价：麦蕊无盘中竞价数据（T003，见 4.0），不刷新、不改变建议，界面显示上一交易日收盘快照并标注
  09:30–11:30 / 13:00–15:00：连续刷新循环（间隔见 0A.6 推导，默认 15 秒，配置项 realtime.quote_interval_s）
     │
     ├─ ① universe 按证书分别计算：每张证书 = 该用户（持仓 ∪ 自选）− 停牌/退市（v0.2.6 起按证书隔离，2.1B；导入/自选变更时增量重算；Redis SET，键带 licence_id）
     │     分层（每张证书内）：Tier-1（上限见 0A.7，按证书计）= 持仓优先 + 重点关注 + 其余自选；超出部分为 Tier-2
     ├─ ② 快照层（按证书隔离：每张证书各自拉取，只服务该证书的用户，不跨证书共享，2.1B）
     │     a. /hsrl/ssjy_more（券商源，≤20 只/次）循环覆盖 Tier-1+Tier-2，每 quote_interval_s 一轮
     │     b. /hsrl/ssjy/all（券商源，全市场，1 次/分钟）每分钟一次：市场宽度/涨跌家数 + 校验 + a 失败时兜底
     │     c. /hsrl/real/all（网络源，全市场，1 次/分钟）仅作 b 的备用源
     │     写 Redis `quote:{licence_id}:{code}`（TTL 3 分钟）+ market.realtime_quotes（当日分区，按分钟降采样保存）
     ├─ ③ 分钟线层（Quant Pro /hsstock/pro/latest/{code}.{mkt}/1/n?lt≤5）
     │     Tier-1：每分钟 lt=2（覆盖 1 根漏取）；Tier-2：每 5 分钟 lt=5；盘后用 /hsstock/pro/history 补齐当日全部 1 分钟 K
     ├─ ④ 增量信号评估：只评估本轮价格/量有变化的股票；
     │     证书内共享层：按 (licence_id, code, strategy_version, 参数哈希) 计算市场类条件 → signal_states（同一证书内共享，不跨证书）
     │     用户层：用户计划/建议的个人条件（失效价、触发价、仓位阈值）→ user_signal_states
     ├─ ⑤ 翻转检测：与上一状态比较；只有"状态翻转"或"失效条件触发"才产生事件（去抖：连续 2 轮成立才确认；失效价类可配置为立即）
     └─ ⑥ 事件 → 生成新建议版本（规则引擎） → alerts → 通知分发（站内 SSE + 可选渠道）
```
- **配置驱动**（`config/realtime.yaml`，管理员可在后台修改并热加载，变更写审计日志）：`quote_interval_s`（默认 15，下限 5）、`all_market_interval_s`（默认 60）、`pro_tier1_interval_s`（默认 60）、`pro_tier2_interval_s`（默认 300）、`tier1_cap`（默认 1,500）、`universe_hard_cap`（默认 4,000）、`per_minute_budget`（全局自设上限，默认 3,000，实测后可调到 5,400 = 6,000 的 90%）、各层预算份额、`max_concurrency`（默认 1，实测后调整）、`stale_threshold_s`（默认 2×quote_interval_s，与契约 1.1 和原因码 `DATA_STALE` 一致；T-A01 由 3× 统一为 2×）。
- **自适应**：`ingest` 记录每轮实际耗时、429/503 次数、行情 `t` 字段（更新时间）的变化比例；若连续 N 轮发现多数股票 `t` 未变化（源头更新慢于拉取），自动把间隔放大到观测到的源头更新周期；出现 429/503 时指数退避并临时降低并发与预算（熔断 5 分钟后恢复）。
- **用户侧节奏**：用户在设置里选**通知节奏** `realtime / 1min / 3min / 5min`（默认 1min），只影响合并推送频率，不影响采集；页面通过 SSE 接收更新，SSE 不可用时 15 秒轮询 `/api/v1/quotes?codes=`（只读 Redis）。
- **陈旧数据处理**：quote 的更新时间落后当前 > `stale_threshold_s` → `stale`；`stale` 时**不生成新建议、不触发翻转**，页面显示"行情延迟 N 秒"；连续 5 分钟失败 → 全站横幅 + 运维告警；停牌股标注"停牌"并跳过；午间休市与收盘后不刷新；15:00 后取一次收盘快照定版。
  - **陈旧阈值的实测口径（T-B117 探针 GAP1，T-A96 补）**：
    - 延迟 = 本机收到时刻 − 快照 `t`。参与 p95 的只限同一自然日、同一连续竞价时段（9:30–11:30 或 13:00–15:00）内的样本，即快照 `t` 与收到时刻同段；停牌、隔夜、午休冻结的 `t` 只留在证据和全量分位数里。参考值 = 各源 NTP 修正后 p95 的最大值；建议值 = max(2×参考, 10s) 向上取整，是后端经验值。
    - 时钟符号：`local_ahead_s` = 本机 − NTP，正值表示本机快；对照字段 `rfc5905_offset_s` = −`local_ahead_s`（RFC 5905 offset = server − local）；修正后延迟 = lag − `local_ahead_s`。
    - 探针给出的建议值（如 2026-11-10 13:05 段的 29s，只基于券商源 24 个样本）只供参考。现行 `stale_threshold_s` 仍为 null，即 2×`quote_interval_s` = 30s。改成显式值须先改 §6.1 默认值，并经编排者 / 用户确认。
- **分钟线衍生指标**：MA、区间高低、量比等由日 K（盘后）+ 当日 1 分钟 K 增量计算；Pro 1 分钟技术指标接口 `/hsstock/pro/history/{macd|ma|boll|kdj}/{code}/1/{fq}` 【文档已列·待 T003 验证】可用于盘后校验，盘中不依赖。
- **幂等**：每轮有 `tick_id`（交易日+时间戳），唯一键 `user_id+code+trigger_kind+tick_id` 防重复生成建议/提醒。
- **T-B60 补充裁定：事件与状态交接、遗留数据的证书归属（v0.2.9 内，架构师；对应 reports/T-B60.md 第 15–16 行；与本节、3.3 表定义冲突时以此为准）**：
  1. **`market.updated` 报文**（Redis pub/sub 频道 `market.updated`，由 `ingest` 在写库提交后发布）：
     - 格式：`{v: 1, licence_id, tick_id, dataset: "quotes"|"minute_bars"|"daily_bars"|"financials"|"announcements"|"security_master", codes: [...], quote_ts_max, published_at}`。
     - `codes` 每条最多 500 个，超过就拆成多条，`tick_id` 相同。报文不带行情数值、证书值或用户信息，订阅方一律回库或缓存读数。
     - `tick_id` = 本轮采集开始的北京时间，格式 `YYYYMMDD'T'HHMMSS`，可按字典序比较先后；同一证书同一轮的所有报文共用一个 `tick_id`。
     - pub/sub 会丢消息：盘中超过 2 × `quote_interval_s` 没收到某证书的报文时，`signal-rt` 按该证书主动读一次最新的 `realtime_quotes`，`tick_id` 取库里最新行的那一轮。
  2. **状态与事件写入**：
     - 共享层按 `(source_licence_id, security_code, strategy_version_id, params_hash)` 维护 `signal_states`。`rule_states` 按规则记 `{rule_id: {value: true|false|unknown, pending_value, pending_count}}`；去抖“连续 2 轮成立才确认”就用 `pending_*` 实现，失效价类可配置为立即确认。
     - 规则确认翻转时，在**同一事务**里：先 `UPDATE signal_states … WHERE last_tick_id IS NULL OR last_tick_id < :tick_id`，影响 0 行就视为过期或重复轮次，整轮放弃；影响 1 行再 `INSERT signal_events`。两步一起提交，不允许只写其中一个。
     - `signal_events` 共享层唯一键 `(source_licence_id, security_code, strategy_version_id, params_hash, rule_id, tick_id)`，用户层唯一键沿用上一条的 `user_id+code+trigger_kind+tick_id`。为此 `signal_events` 新增列 `source_licence_id`（必填）、`strategy_version_id`、`params_hash`、`rule_id`（用户层可空）。
  3. **存储与契约的对应**：表里的 `trigger_kind` 仍只取 4 个值；契约 `SignalEvent.kind`（`signal_kind`）存在 `detail.kind`，必填，取值必须属于 `signal_kind`。
     - `flip`：取该规则在策略版本里声明的 `event_kind`（`breakout`、`breakdown`、`vwap_deviation`、`volume_spike`、`limit_up_touch`、`limit_down_touch`、`limit_open` 之一），没有声明的取 `rule_flip`。
     - `invalidation`：`invalidation_near` 或 `stop_hit`。
     - `stale`：行情变旧时取 `data_stale`；停牌时取 `suspended`，`detail.direction` 为 `suspended`。
     - `resume`：从变旧恢复时取 `data_stale`，`detail.direction` 为 `recovered`；复牌时取 `suspended`，`detail.direction` 为 `resumed`。
     - `detail` 的其他字段固定为 `{rule_id, strategy_key, price (decimal 字符串 | null), direction, candidate_signal_id | null}`。共享层的 `detail` 不得含用户 id、实例 id 或持仓信息。
     - `/signals` 和 SSE `signal` 在读取时拼装：`instance_id` 按当前用户的 `strategy_instances`（相同 `strategy_version_id` 和 `params_hash`）补上；`message` 由服务端按 `kind` 的固定模板生成，并过禁用词校验。用户只能看到 `source_licence_id` 是本人证书的共享事件，加上自己的用户层事件。
  4. **到候选信号的交接**：共享事件提交之后，另起事务按实例展开。对每个使用该 `(strategy_version_id, params_hash)`、且所属用户的证书就是 `source_licence_id` 的 `strategy_instance`，经过 T-B60 的主表保护（`run_with_master_guard`）和可执行性闸门后，写 `candidate_signals` 和 `candidate_signal_events`（`cause=executability_check`，`detail.signal_event_id` 指回事件）。`candidate_signals` 新增 `origin_signal_event_id`，唯一键 `(instance_id, origin_signal_event_id)`，保证重放幂等。单个实例失败只回滚这个实例，不回滚已提交的共享事件。
  5. **遗留数据的证书归属**：
     - `signal_states`、`signal_events`、`intraday_universe` 都加 `source_licence_id`（必填，FK → `app.user_data_licences.id`；T-A28：`ops.data_licences` 为旧称，主线不存在该表，一律映射到迁移 0007 的 `app.user_data_licences`，不新建 `ops` 表）。唯一键改为：`signal_states` 用 `(source_licence_id, security_code, strategy_version_id, params_hash)`；`intraday_universe` 主键用 `(trade_date, source_licence_id, security_code)`。
     - 遗留行不猜测归属，也不复制给每张证书：`signal_states`、`intraday_universe` 是可以重算的派生数据，迁移时记下行数后清空，下一个盘中时段按证书重建。
     - `signal_events` 是只追加的历史：迁移先统计没有归属的行，为 0 时才加 NOT NULL 列；不为 0 时迁移报错停止（报出行数），交架构师裁定，不能在迁移里删除或编造归属。目前 `signal-rt` 是占位实现，预期为 0。
     - `shared_cache` 模式（未获批，禁止启用）下同样写实际取数所用的证书，不写空值。
  6. **T-B60 的验收顺序**：上面第 1–5 条落地，并且 T-B20、T-B22、T-B23 的实际组件（特征增量、规则求值、`intraday_universe`）接上之后，才签收 T-B60 的验收 ①–④。主表保护（9059bfb）可以先合入，但不算 T-B60 验收通过。

### 0A.4 建议生成：确定性规则 + 因子；LLM 只写解释（可选）
1. **输入**：策略库中用户为该股票（或账户默认）启用的策略版本（见 2.5）+ 当时数据快照 + 用户画像版本 + 持仓状态 + 用户已有计划。
2. **每个策略**输出：`state ∈ {entry_ok, not_triggered, hold_ok, weakening, exit_signal, vetoed, insufficient_data}`（契约枚举 `strategy_eval_state`，`not_triggered` 的含义见 2.5.14 H④）、`score`（条件满足度，对外 0–100 整数）、逐条条件结果。
3. **动作映射（确定性、版本化的规则表 `action_policy`，可在策略版本中查看）**：

| 持仓状态 | 单个策略的状态 | 该策略的动作 |
|---|---|---|
| 未持有 | entry_ok 且无失效条件触发、适配性通过 | `buy` |
| 未持有 | not_triggered / vetoed / insufficient_data | `wait` |
| 已持有 | entry_ok（若超 RC2/RC3 上限，动作仍为 `add` 但标 `gated`，见 2.5.6） | `add` |
| 已持有 | hold_ok；或 not_triggered / vetoed（否决只阻断买入方向） | `hold` |
| 已持有 | weakening（如趋势条件失效但基本面仍成立） | `reduce` |
| 已持有 | exit_signal 或用户计划的失效条件触发 | `sell` |
| 任意 | 数据 stale / 关键数据缺失 | 维持上一建议并标注"数据不足，未更新"，不新出动作 |
   - **不合并（用户 11:41 确认）**：每个启用策略独立映射动作；多个策略/维度冲突时按 2.5.4 "维度 × 策略"矩阵并列展示观点、依据与分歧点，**不取保守动作、不设主策略、不输出合成结论**，由用户判断。日内做T策略的动作带 `t_leg`。
   - `score`、`confidence` 均按策略单独计算（2.5.4），公式写入 `engine_policies` 版本。
4. **LLM（用户有充足额度，默认开启"解释"能力，但只写解释）**：经 **LLM 网关**（第 2.7 节）调用，只把**结构化证据**改写成中文解释（建议理由、日报个股分析段落、策略分歧说明）；
   - 不决定动作、分数、置信度，不新增事实；输入只含证据 JSON（含证据 `id`），要求每句以 `[E12]` 形式引用证据；
   - **防幻觉校验**：输出中所有数字必须能在输入证据中找到（数值与单位精确匹配或按约定四舍五入），所有引用 ID 必须存在；出现未引用句子、新数字、新股票代码、禁用词（"保证/必涨/稳赚"等）→ 丢弃，按网关策略重试/切换备用模型，仍失败则回退到**模板解释**（模板始终可用，LLM 不可用不影响建议生成）；
   - 原始 prompt/输出/模型/token/成本存 `llm_calls`；用户可一键查看"原始结构化证据"；
   - **用量估算**：每条解释约 1.5k 输入 + 0.3k 输出 tokens；100 用户 × 平均 30 只股票 × 每日 1 次（盘后）≈ 3,000 次/日 ≈ 5.4M tokens/日；盘中只对翻转事件生成（估计 ≤ 盘后量的 30%）；同一 (code, method_version, snapshot) 的个股事实解读在**同一证书内**缓存复用（快照来自本人证书数据，不跨证书复用，2.1B），只有涉及个人持仓的段落按用户生成。按 2.7.1 的 `deepseek-flash` 官方价目（2026-11-01 核实）估算：每日约 4.5M 输入 + 0.9M 输出 tokens，全部按高峰价且缓存全未命中时 ≈ 4.5×2 + 0.9×8 ≈ 16.2 元/日，空闲时段减半，缓存命中部分更低；价目可能变动，以官方价目页和账单为准。网关按调用记录成本并设日预算上限。
5. **不可变存档**：`suggestions` 行写入后禁止 UPDATE/DELETE（触发器）；头表 `suggestion_threads`（每用户每股票一条）只保存当前指针与状态。

### 0A.5 盘后批处理流水线（交易日）
| 时间（北京时间） | 步骤 | 依赖 |
|---|---|---|
| 15:05 | 收盘快照定版（/hsrl/ssjy/all）、当日涨跌停池 | 交易日历 |
| 15:30–16:30 | 日 K（/hsstock/latest）、资金流、龙虎榜、今日交易提示 | 收盘 |
| 16:30–17:30 | 因子截面（/factor/batch 或 /factor/screen，只取策略库用到的因子）、公告/问董秘增量 | 因子更新时间【文档：交易日 16:30 后·待 T003 验证】 |
| 17:30–18:30 | 对 universe 逐股：策略评估 → 建议生成 → 快照；对账状态检查；数据缺口汇总 | 上述全部 |
| 18:30–19:00 | 每用户日报组装（`daily_reports`）→ 站内通知 + 可选渠道摘要 | 建议 |
| 19:00 后 | 失败重试、缺口补拉、统计（调用量、耗时、失败率） | — |
- 每步幂等（`run_date + step` 唯一）、可重跑；任一上游缺失 → 日报中对应部分标 `gaps` 而非延后整份日报；日报生成截止 20:00，超时告警。

### 0A.6 麦蕊实时/分钟接口核实结果与刷新间隔推导
> **【待 T003 验证】本节所有数据可用性结论**（接口、字段、因子、限流、历史深度、刷新间隔、上限推算）都来自文档推导，须以后端实测报告 `/workspace/team/reports/T003-mairui-capability.md` 为准；报告出来后逐项替换本节标记。

**接口清单（2026-11-01 抓取官网文档【文档已列·待 T003 验证】，未用真实证书实测）**

| 用途 | 接口（省略域名与 `/{licence}`） | 批量 | 文档频率/限制 | 数据更新 |
|---|---|---|---|---|
| 单股实时（券商源） | `/hsstock/real/time/{code}` | 否 | 钻石版 6,000 次/分钟 | 实时 |
| 单股实时（网络源） | `/hsrl/ssjy/{code}` | 否 | 钻石版 6,000 次/分钟 | 交易时段每 1 分钟 |
| 多股实时（券商源） | `/hsrl/ssjy_more?stock_codes=c1,…,c20` | **≤20 只/次** | 钻石版 6,000 次/分钟 | 实时 |
| 全市场实时（券商源） | `/hsrl/ssjy/all` | 全部股票 | **每分钟 1 次**（同页说明）；数据包页与更新日志写"bulk 独立限流约 3 次/分钟"→ 【待 T003 验证】 | 实时 |
| 全市场实时（网络源） | `/hsrl/real/all` | 全部股票 | 每分钟 1 次（同上，【待 T003 验证】） | 交易时段每 1 分钟 |
| 五档盘口 | `/hsstock/real/five/{code}` | 否 | 钻石版 6,000 次/分钟 | 实时 |
| 最新 1 分钟 K（Pro） | `/hsstock/pro/latest/{code}.{mkt}/1/n?lt=1..5` | 否（单股） | "限流同证书档位"→ 按 6,000 次/分钟理解 | 盘中增量（Redis 集群） |
| 历史 1 分钟 K（Pro） | `/hsstock/pro/history/{code}.{mkt}/1/n?st&et&lt`，深度约 5 年；全量 `pro.mairuiapi.com …/history/full/` | 否 | 全量接口 60 次/分钟（第 4.1 节） | 盘后补齐 |
| 最新 5/15/30/60 分钟、日 K | `/hsstock/latest/{code}.{mkt}/{5\|15\|30\|60\|d…}/{fq}?lt` | 否 | 钻石版 6,000 次/分钟；**普通路径已不提供 1 分钟** | 实时 |
| 企业专属分时 | `https://{专属子域}.mairuiapi.com/hsstock/vip/...` | — | **仅企业版**，我方不可用 | — |

**通用限流规则**：钻石版每分钟 6,000 次、**每日不限**、总量不限【文档已列·待 T003 验证】；证书到期后每日 20,000 次【文档已列·待 T003 验证】；同一证书 60 秒内最多 2 个来源 IP，超出 429 / 码 103【FAQ已列·待 T003 验证】；FAQ 一处说"当前无并发连接数限制"，另一处说"单 IP 发出多个线程的请求"会返回 503 → **并发上限【待 T003 验证】**；6,000 次/分钟是"每接口"还是"整张证书合计"文档未写明 → 按**证书合计**保守设计【待 T003 验证】；`ssjy_more` 一次是否只计 1 次、bulk 接口是否占用 6,000 预算【待 T003 验证】；Quant Pro 到期日与基础证是否同为 2027-09-11【待 T003 验证：以证书后台为准】。

**刷新间隔推导**（N = 去重后股票数，B_rt = 分给快照层的每分钟预算，c = 并发数，L = 单次请求耗时）：
- 预算约束：每轮调用 ⌈N/20⌉ 次 → 间隔 ≥ 60·⌈N/20⌉ / B_rt 秒；
- 时延约束：间隔 ≥ ⌈N/20⌉·L / c；
- 源头约束：间隔 ≥ 源头实际更新周期（网络源已知为 1 分钟；券商源"实时"，具体周期【待 T003 验证：上线前用 `t` 字段测】）。
- 取默认 B_rt = 800/分钟（全局 3,000 中快照层份额）、c = 1、L ≈ 0.15 秒【待 T003 验证：T-B05 实测】：

| N | 每轮调用 | 预算下限 | 时延下限（c=1） | **默认间隔** | 每日调用（255 分钟） |
|---|---|---|---|---|---|
| 100 | 5 | 0.4 s | 0.75 s | 5 s（配置下限） | 15,300 |
| 1,000 | 50 | 3.75 s | 7.5 s | 10 s | 76,500 |
| 2,000 | 100 | 7.5 s | 15 s | **15 s** | 102,000 |
| 5,000 | 250 | 18.75 s | 37.5 s | 40 s（c=4 时 ≈ 19 s） | 95,625 |

- **结论**：以快照层计，钻石版允许**秒级（5–15 秒）刷新数千只股票**，真正的上限来自源头更新周期与并发规则（均【待 T003 验证】），所以默认 15 秒、全部参数配置化，T-B05 实测后调整。若实测发现单接口真实更新只有 1 分钟，则自动退回 60 秒并只用 `/hsrl/ssjy/all`（1 次/分钟、与 N 无关）。
- **分钟线层**：Tier-1 每分钟每股 1 次（lt=2）→ N₁ 次/分钟；Tier-2 每 5 分钟 lt=5 → N₂/5 次/分钟。默认预算 2,000/分钟 → N₁ + N₂/5 ≤ 2,000，取 N₁ = 1,500、N₂ = 2,500（见 0A.7）。
- **全天调用量（默认配置、N = 4,000 = Tier-1 1,500 + Tier-2 2,500）**：快照（每轮 200 次、c=1 时约 30 秒一轮）≈ 10.2 万 + 分钟线 1,500×255 + 2,500×51 ≈ 51 万 + 全市场 255 + 盘后批 ≈ 2–3 万 ≈ **63–64 万次/日**，钻石版每日不限，可行；证书到期后（每日 20,000 次）只能保留全市场接口 + 小范围分钟线，需续费（第 7.5 节）。
- 1 分钟 K 的历史回补、盘后批量在 15:05 后使用全部预算。
- **T-A07（每用户证书）**：本节与 0A.7 的推导改为**对每张证书分别适用**（N 为该用户的去重证券数，预算为该证书的桶）；所有证书共用同一出口的串行时延（实测约 0.26 秒/次，T003），这才是总量瓶颈，见 2.1B 第 5 点。

### 0A.7 自选股上限（由配额推导）
> **【待 T003 验证】本节所有数据可用性结论**（接口、字段、因子、限流、历史深度、刷新间隔、上限推算）都来自文档推导，须以后端实测报告 `/workspace/team/reports/T003-mairui-capability.md` 为准；报告出来后逐项替换本节标记。

- **系统级去重股票池上限**：binding 约束是 Pro 1 分钟 K（只能单股调用）。全局自设上限 3,000/分钟 − 快照层 800 − 其他接口 200 = **2,000/分钟留给分钟线**；Tier-1 每股每分钟 1 次、Tier-2 每股每 5 分钟 1 次 → N₁ + N₂/5 ≤ 2,000。取 **Tier-1 = 1,500 只**（每分钟分钟线 + 快照）、**Tier-2 = 2,500 只**（每 5 分钟分钟线 + 快照）→ **系统去重池上限 4,000 只**；快照层 4,000 只 = 每轮 200 次，在 800/分钟预算下最快 15 秒一轮（c=1 时受时延约束约 30 秒）。实测确认可把全局上限提到 5,400/分钟后，分钟线预算约 4,400 → Tier-1 可到约 3,900，上限可放开到"全市场"。达到上限后，新加入自选的股票只由每分钟一次的全市场快照（`/hsrl/ssjy/all`）覆盖，界面提示"实时精度降级"。
- **每用户上限**：持仓不设上限（必须覆盖用户实际持有，导入时 > 200 只给出提示）；**自选默认 100 只/人**（配置 `watchlist.per_user_cap`）。推导：V1 用户 10–100 人（用户确认）；按最坏情形 100 人 × 每人（持仓 15 + 自选 100）= 11,500，用户间重合按 60% 估计【假设】→ 去重池 ≈ 4,600，略超系统上限 4,000；按自选平均实际使用 60 只估计 → 100 × 75 × 0.4 ≈ 3,000 ≤ 4,000。因此把**自选上限设 100、但 Tier-1（1,500）名额按"持仓 > 多人关注的自选 > 单人自选"分配**，并监控 `universe_size`，接近 Tier-1 上限 80% 时告警，由管理员调低 `per_user_cap` 或提升预算。另设每用户"盘中重点关注"≤ 20 只（保证进入 Tier-1，额度用尽时提示）。
- 所有数字均为配置项，T-B05 实测配额后在 `config/realtime.yaml` 调整，无需改代码。

---

## 1. 推荐技术栈及理由（验收项 1）

### 1.1 选型总表

| 层 | 选型 | 理由 | 备选 / 不选原因 |
|---|---|---|---|
| 后端语言/框架 | **Python 3.12 + FastAPI**（Pydantic v2 强类型模型、自动 OpenAPI） | ① 投资计算（收益、回撤、仓位、归因、指标）天然依赖 pandas/numpy 生态；② 麦蕊官方 Python SDK `mairui`【已核实存在，v1.2.0】可做参考（生产仍用自封装 HTTP 客户端以统一限流）；③ FastAPI 自动输出 OpenAPI，前端据此生成 TS 类型，契约可机器校验；④ 类型检查用 mypy（strict）。 | NestJS/TypeScript 全栈类型统一更好，但量化计算生态弱；Go 性能好但开发效率与数据处理库不如 Python。MVP 瓶颈不在 CPU。 |
| ORM / 迁移 | SQLAlchemy 2.x（async）+ Alembic | 成熟、支持 PostgreSQL 特性（JSONB、分区、部分索引）。 | — |
| 数据库 | **PostgreSQL 16 + TimescaleDB 扩展（推荐，同一实例）** | 事务一致性（交易、计划、版本），JSONB 存证据和快照，行级安全可选；行情时序（1 分钟 K、日 K、实时快照、因子、特征宽表）使用 hypertable，配合列式压缩、保留策略和连续聚合；一个库同时承载业务数据与行情（3A）。TimescaleDB 2.x 社区版可自托管免费，支持 PG16 及以上，镜像版本固定 | 纯 PG 分区（可行但需自己写压缩和保留，作为备选）；DuckDB（适合离线分析，不适合多用户在线并发写入，内部评估可选用它读 Parquet 导出）；ClickHouse（运维重，10–100 用户不需要）；**SQLite 不采用** |
| 缓存 / 队列 / 限流 | **Redis 7** | ① 热数据缓存（实时快照、榜单；键带 `licence_id`，按证书隔离，2.1B）；② Celery broker；③ 麦蕊每证书令牌桶（Lua 原子脚本，2.1B）；④ 会话存储。 | — |
| 任务调度 / 实时 | **Celery worker + 单实例 Celery Beat**（盘后批、提醒、跟踪、日报、健康度）+ **唯一的行情采集服务 `ingest`**（单副本、单活锁、令牌桶 + 优先队列，2.1A）+ **`signal-rt` 进程**（订阅 `market.updated`，盘中特征 → 规则 → 候选信号 → 可执行性 → 原因解除监控，0A.3） | Beat 只能单实例，避免重复触发。麦蕊"60 秒内最多 2 个 IP"是硬约束，外呼必须集中到一个进程、一个出口 IP。盘中计算与外呼分开，计算故障不影响采集。 | APScheduler（没有分布式队列）、Kafka 或流处理（规模用不上）、多节点直连麦蕊（违反 IP 限制） |
| 通知 / 推送 | **站内通知 + SSE 实时推送**（`GET /api/v1/stream`，轮询兜底）；渠道适配器可插拔：MVP 站内 + 可选邮件；企业微信自建应用列为第二步（2.6） | SSE 单向、走 HTTP、Nginx 易透传，100 用户规模单进程足够。 | WebSocket（双向不需要）、短信（需签名模板与费用）、个人微信（无官方接口，不做） |
| 前端 | **React 19 + TypeScript + Vite + React Router + TanStack Query + antd 6（Ant Design 6，暗色 + compact 算法）+ AG Grid Community（实时密集表格，禁止 Enterprise）+ TradingView Lightweight Charts（K 线/分时）+ ECharts（统计图）+ react-resizable-panels（分隔条调宽/折叠）**（**【已定 2026-11-01】React 19 + antd 6**，原型 T-F00 已验证，第 9 节问题 34） | 深色交易终端风格、仅桌面（2.10）；AG Grid Community（MIT）适合实时更新的密集表格，低频小表用 AntD Table（2.10 选型结论）；Lightweight Charts 体积小、金融图表专用（Apache-2.0，需保留署名）。 | Next.js（无 SSR 需求）、Vue（团队偏好待定，二者皆可） |
| 认证 | **用户名 + 密码**（argon2id），自助注册后待管理员审核；服务端会话（Redis）+ httpOnly Cookie + CSRF 头；不用短信/邮箱验证码 | 符合用户要求；会话可随时吊销（禁用账号即时生效）。 | JWT 无法即时吊销，不选。 |
| 部署 | **Docker Compose 单机**：nginx、api、worker、beat、**ingest（唯一调用麦蕊，replicas 1）**、signal-rt、postgres（+TimescaleDB）、redis；**先本地测试，后迁移服务器**（1.3）；每日 pg_dump + WAL 归档 | V1 10–100 用户单机足够；麦蕊同一证书 60 秒内仅 2 个 IP → 只能有一个真实调用出口。 | k8s / 微服务（规模不需要，徒增运维）；`ingest` 在 compose 中固定 `replicas: 1`，冷备只写手册、不常驻（2.1A） |
| CI/CD | GitHub Actions：lint + 类型检查 + 单测 + 契约测试 + 构建镜像；手动审批后 SSH 部署 | 仓库已在 GitHub 私有库。境内服务器拉 GHCR 可能慢 → 再加境内镜像仓库（已定：先用 GHCR，第 9 节问题 24）。 | — |
| 可观测性 | 结构化 JSON 日志 + `request_id`；**暂不接入 Sentry**（【已定 2026-11-01】，境内部署时再决定是否自托管，问题 35）；错误靠日志告警；Prometheus 指标（麦蕊调用次数/429/延迟、任务时延）可选 | 配额/限流是关键运维指标。 | — |
| LLM 网关 | 自研薄层 `llm` 模块：OpenAI 兼容协议适配器 + 可扩展 provider 适配器；管理员配置供应商/模型/加密密钥/任务路由/预算（2.7） | 供应商无关、可替换；只做解释，失败回落模板。 | LangChain 等重型框架（不需要 agent 编排） |
| 测试 | pytest + hypothesis、vitest、Playwright、schemathesis、locust（8.0） | 质量优先；golden/回放测试保证规则引擎确定性。 | — |

### 1.2 为什么不是"一个前后端都 TS 的全栈"
产品核心是**证据整理与计算**，不是高并发 IO；Python 的数据处理优势 > 前后端同语言的类型共享收益。类型共享通过 OpenAPI 生成解决。

### 1.3 部署形态：先本地测试，后迁移服务器（V1 用户 10–100 人）
- **规模定位**：10–100 个用户、单台主机、Docker Compose；**不用 k8s、不拆微服务、不引入消息中间件以外的分布式组件**。代码按模块化单体组织（第 2.2 节），API 与 worker 共用同一镜像、不同启动命令。
- **容器清单**（`deploy/compose/docker-compose.yml`）：`nginx`（静态前端、反向代理、SSE 透传）、`api`（uvicorn 2–4 workers）、`worker`（Celery，队列 `default/batch/llm/notify/evaluation`）、**`ingest`（行情采集服务，`replicas: 1`，全站唯一调用麦蕊，唯一能解密用户证书（只有它注入 `DATA_LICENCE_SEAL_PRIVATE_KEYS`），2.1A、2.1B）**、`signal-rt`（盘中信号计算，单实例，**无 licence**）、`beat`（唯一）、`postgres`（PG16 + TimescaleDB 镜像，版本固定）、`redis`。出口 IP 即主机的固定公网 IP；`ingest` 启动时自检。
- **资源估算**：4 vCPU / 8 GB 内存 / 100 GB SSD 足够（分钟线保留 90 天约 3–4 GB，见 3.3）；测试期用开发者本机（Docker Desktop 或 Linux）即可。
- **配置全部走环境变量**（pydantic-settings；`deploy/env/.env.example` 只有变量名与假值）：`DATABASE_URL`、`REDIS_URL`、`MAIRUI_BASE_URL`、`MAIRUI_PRO_BASE_URL`、`APP_MASTER_KEY`（加密 LLM key / 股东代码 HMAC / 原始文件）、`IMPORT_STORAGE_PATH`、`PUBLIC_BASE_URL`、`SESSION_COOKIE_SECURE`、`REGISTRATION_MODE`（默认 `closed`）、`SMTP_*`；运行参数（实时间隔、预算、上限）在数据库配置表 + `config/*.yaml` 默认值中，可在后台修改。 **T-A07 起生产不再使用 `MAIRUI_LICENCE`**（每用户证书加密存库，2.1B）：`DATA_LICENCE_SEAL_PUBLIC_KEYS`、`DATA_LICENCE_SEAL_KEY_VERSION` 注入 `api`；**`DATA_LICENCE_SEAL_PRIVATE_KEYS` 只注入 `ingest` 容器**，其他容器的 env 文件不含私钥，CI 会检查；`ingest` 发现 `MAIRUI_LICENCE` 非空即拒绝启动（只有本机实测脚本可在用户本人电脑的 shell 中临时设置它）。
- **`APP_MASTER_KEY` 按服务分配（v0.2.9 内，T-O11 评审裁定）**：主密钥只通过 compose secret 文件 `app_master_key` 提供，只有确实要用它的服务挂载；其余服务不挂载、启动也不要求它。依据是当前代码的实际用途（2026-11-01 核对 `src/backend/app`）：

  | 服务 | 用途（代码位置） | 需要主密钥 | secret 文件 | 启动检查（非 local/test） |
  |---|---|---|---|---|
  | `api` | 分页游标签名（`common/pagination.py`）、邀请码 HMAC（`auth/invites.py`）、登录 IP HMAC（`auth/deps.py`）、证书去重 HMAC 与冷却指纹（`licences/seal.py`，由 `licences/service.py` 调用）、导入文件加密密钥（`importing/keys.py`、`importing/storage.py`）、LLM 密钥密文 | 需要 | 挂载 | 缺失或少于 32 字符 → 拒绝启动 |
  | `worker` | 现为心跳占位；规划中的导入解析（读加密原始文件）与 LLM 网关（解密 `api_key_ciphertext`）要用 | 需要 | 挂载 | 同 `api` |
  | `ingest` | 只用证书私钥 `DATA_LICENCE_SEAL_PRIVATE_KEYS`（X25519，见 2.1B），不用主密钥 | 不需要 | **不得挂载** | 不要求；如检测到主密钥（环境变量或 secret 文件）→ 拒绝启动，避免同一容器同时持有私钥与主密钥 |
  | `beat` | 只调度；周期任务（含每小时清理证书冷却记录）在 `worker` 执行 | 不需要 | 不得挂载 | 不要求 |
  | `signal-rt` | 读库与缓存计算信号；SSE 与游标在 `api` | 不需要 | 不得挂载 | 不要求 |
  | `maint-cli` | 删除用户数据 CLI 按 `user_id` 删行、删文件、删 Redis 键，不计算 HMAC；连接串只读 `AIA_MAINT_DATABASE_URL_FILE` | 不需要 | 不得挂载 | 不要求 |
  | `migrate` | alembic 迁移不计算 HMAC；`migrations/env.py` 只在没给 `DATABASE_URL` 时才加载 Settings | 不需要 | 不得挂载 | 不要求 |
  | ~~`cooldown-purge`~~（**已删除**，028c077；review-6670b10 m5） | 冷却记录清理已改由 `beat` 调度、`worker` 执行 `licences.purge_expired_cooldowns`（6670b10）；本服务及 CI 规则 7 登记已删除。已部署过的主机升级后用 `compose.sh up -d --remove-orphans` 清掉残留容器 | — | — | — |
  | `nginx`、`postgres`、`redis` 及其他基础设施 | 无 | 不需要 | 不得挂载 | — |

  - **后端**：Settings 的“非 local/test 必须有 `APP_MASTER_KEY`”只对 `SERVICE_NAME ∈ {api, worker}` 生效；`SERVICE_NAME` 缺省仍按 `api` 处理，取到白名单外的未知值时在非 local/test 下拒绝启动（失败即关闭）。所有用主密钥派生子密钥的函数（游标、邀请码、登录 IP、证书去重与冷却指纹、导入文件密钥）在非 local/test 下取不到主密钥时必须抛错，不得退回进程内临时密钥。`ingest` 启动时发现主密钥即拒绝启动。
  - **CI 规则 7（`scripts/ci/check_secret_boundary.py`）改为显式白名单**：脚本内写死一张表，`api`、`worker` 必须挂载 `app_master_key`，表中列出的其余服务必须不挂载；compose 中出现表里没有的服务 → CI 失败，新增服务时必须先在表里登记“挂或不挂”。`.env.example` 仍只有变量名与假值。
  - **升级约束**（运维实现于 `deploy/scripts/`，runbook 同步）：① 升级流程的任何一步都**不得自动生成**主密钥；只有全新部署（secret 文件不存在、旧 `.env` 与环境里没有非占位值、数据库为空）才允许生成。② secret 文件缺失、但旧 `.env`（或环境变量）里有非占位值的 `APP_MASTER_KEY` → 把该值迁移进 secret 文件（权限 600，不打印、不写日志），提示从 `.env` 删除该行，不生成新值。③ 两者都没有、但数据库已有数据（`app.users`、`app.invite_codes`、`app.user_data_licences` 任一非空）→ **拒绝启动**，提示从备份恢复主密钥；连不上数据库时同样拒绝。④ secret 文件与旧 `.env` 都有且不一致 → 拒绝启动，等人工确认。⑤ 主密钥轮换不在 V1 范围。
  - **主密钥多版本是上线门槛（v0.2.9 内，评审 b195ca6 / T-O12 架构师裁定）**：上线前还没有真实用户数据，现在加密钥编号几乎没有成本；上线后再加就要对真实密文做回填迁移。门槛范围是最小集，由后端 **T-B57** 完成：所有加密列 / 密文带 `kek_id`（或版本前缀）、HMAC 索引列带 `key_id`；密钥环“当前钥加密、按 `kek_id` 选钥解密、HMAC 查询逐个有效版本比对”；主密钥 secret 文件支持多把带 id 的钥并标出当前钥；自检“加新钥后旧数据仍可读、新数据用新钥写”。**后台重加密 CLI 与运维轮换流程不是门槛**，属上线后 V2（运维在 T-O12 之后跟进，方案见团队报告 T-O12 §2）；V1 仍不执行轮换（⑤ 不变）。契约不变。第 9 节问题 95。
  - **主密钥备份 / 恢复（T-O12，`deploy/scripts/app-master-key-backup.sh`）**：恢复必须以运维台账记下的 sha256 为准核对（不能只信与备份放在一起的 `.sha256`），核对不过不写入；迁移流程第 1 步用该脚本恢复（评审 b195ca6）。
- **网关上游连接超时（v0.2.9 内，T-O13 演练架构师裁定 A，运维实现）**：nginx 在 server 级加 `proxy_connect_timeout 3s`（覆盖所有变量形式 `proxy_pass` 的 location，含健康检查探针）；内部网络连接应在毫秒级，`api` 停掉后、`resolver valid=10s` 缓存窗口内的请求挂起从最长 60 秒降到约 3 秒，返回 502/504，走部署层统一错误页（与全局维护页同类，不进契约错误码表）；`proxy_read_timeout` 不变（SSE 与长请求依赖它）。CI `check_gateway_limits.py` 规则 9 同步检查该值 ≤ 5s；正式目标宿主重做 T-O13 停机演练时复测“挂起 ≤ 约 3 秒”。（2026-11-01 复核：裁定不变，`proxy_connect_timeout 3s`、`proxy_read_timeout` 不变。）
- **证券接口：搜索单独限流与禁止共享缓存（v0.2.9 内，架构师裁定 2026-11-01；依据 reports/T-A04-ops.md；契约 v0.2.9 #41）**：
  - **搜索单独限流**：网关给 `/api/v1/securities/search` 与 `/api/v1/securities?q=` 单独设 `limit_req` zone，**每客户端（与全站 `aia_api` zone 同键，按客户端 IP）5 r/s、burst 20**，与全站 20 r/s 同时生效（取更严者）；超限走现有 `@rate_limited`，返回契约统一的 `429 RATE_LIMITED` 错误信封（`details.retry_after_s`）+ `Retry-After` 头。目的：抑制用代码前缀枚举全市场名单（事实上的批量导出，问题 52）。CI `check_gateway_limits.py` 同步检查 zone 存在、数值与两个 location 都引用。V1 本机自用阶段也启用（成本低）。
  - **`/securities/*` 一律 `Cache-Control: private, no-store`**：需登录、数据来自授权数据源（部分字段按本人证书取），不得被任何中间缓存或浏览器磁盘缓存保存。适用于 `/api/v1/securities` 下全部路径（含 `search`、`?q=`、`{code}` 及其子资源）的所有响应（含 `304` 与错误响应）；弱 ETag 照常返回、`If-None-Match` → `304` 照常支持。后端在路由层统一设置；网关继续不做 `proxy_cache`、不上 CDN；网关自己生成的错误（429/414/502/504）对该前缀同样带 `no-store`。后端如以后加响应缓存，只能按用户隔离。
- **无云厂商锁定**：只依赖 PostgreSQL、Redis、本地卷（或任意 S3 兼容存储，通过 `IMPORT_STORAGE_BACKEND=local|s3` 切换）；不用托管专有服务；镜像可在任意主机运行。
- **迁移流程（本地 → 服务器）**：`pg_dump` 加原始文件卷打包（加密）→ **把原主机 `$AIA_SECRETS_DIR/app_master_key` 拷到新主机同一路径（600、属主容器用户；否则新主机空库会按 1.3 升级约束①生成新主密钥，`pg_restore` 后既有 HMAC 与加密文件全部失效）；主密钥随备份单独离线保存，不与 `pg_dump` 放在一起（v0.2.9 内，评审 75c233b 裁定）** → 新主机 `docker compose up`（**先不启动 `ingest`**）→ `pg_restore` → 修改 `PUBLIC_BASE_URL` 与 DNS → **停止本地 `ingest` → 等待 ≥ 60 秒 → 启动服务器 `ingest` → 核对出口 IP → 从本地 `.env` 删除 licence**。迁移期间及之后，开发机不得用同一证书做真实调用（2.1A；第 9 节问题 27）。操作手册写在 `deploy/scripts/migrate.md` 和 `deploy/runbooks/ingest-failover.md`（T-O06、T-O07）。
- **测试期访问**：本地 `http://localhost`，不对公网开放；如需让少数测试用户访问，用内网/VPN（如自建 WireGuard）而非把未备案域名解析到境内主机。
- **域名未备案的影响**（第 9 节问题 4）：
  - 域名解析到**中国内地**服务器并提供网站访问，必须先完成 ICP 备案，否则接入商会阻断（《非经营性互联网信息服务备案管理办法》第五条；阿里云/华为云/腾讯云备案说明，2026-11-01 核实）。备案需境内服务器、按接入商流程办理，耗时【待核实，常见为数周】；收费经营可能还需 ICP 经营许可证【待核实】。
  - 解析到**中国香港/境外**服务器无需 ICP 备案（同上来源），但：① 用户个人信息（持仓、成交）存储在境外属于个人信息出境，需按《个人信息保护法》第三十八条及《促进和规范数据跨境流动规定》评估/标准合同备案；② 麦蕊服务条款 5.7 要求境内运营中收集的个人信息与重要数据境内存储，境外部署与之冲突；③ 境外主机访问麦蕊与境内用户访问的网络延迟与稳定性【待核实，需实测】。
  - **建议**：测试期本地运行（无需备案）；正式开放前购买**境内**服务器并完成 ICP 备案（个人主体也可备案，但"金融/证券类信息服务"类网站的前置审批要求【待核实】）；香港方案仅作为备案完成前的过渡，且只在不存储真实个人持仓数据的前提下考虑。

---

## 2. 系统架构与模块划分（验收项 2）

### 2.1 逻辑架构

```
                         ┌─────────── 只读：缓存 + 数据库（所有用户、所有服务）───────────┐
[浏览器 深色终端] --HTTPS/SSE--> [Nginx] --> [api (FastAPI)] --> PostgreSQL 16 + TimescaleDB
                                              |  \--> Redis（会话、缓存、pub/sub、Stream）
                                              |  \--> GET /stream（SSE，订阅 Redis pub/sub）
                                              |  \--> 缓存缺失 → XADD ingest:requests（拉取意图，P1）
                                              v
 [Celery Beat 单实例] --> [Celery worker：盘后流水线、日报、跟踪、健康度、通知、llm、evaluation*]
                              |  \--> [llm 网关] --> LLM 供应商（只写解释，带证据 ID 校验，失败回退模板）
                              |  \--> [notify] --> 站内 / 邮件 /（企业微信，第二阶段）
                              |  \--> 需要数据 → XADD ingest:requests（P1/P2）
                              v
 [signal-rt 单进程：盘中特征 → 规则求值 → 候选信号 → 可执行性 → 原因解除监控 → 通知]   ← 订阅 market.updated
                                                                                          │
 ════════════════ 唯一外呼边界（licence 只在此容器）══════════════════════════════════════╪═══
 [ingest 行情采集服务，replicas=1，单活锁 ingest:leader，固定出口 IP 自检]                  │
    令牌桶（per_minute_budget）+ 优先队列 P0 盘中实时 > P1 日批 / 按需 > P2 回补 / 评估      │
    → api.mairuiapi.com / pro.mairuiapi.com（同一证书 60 秒内最多 2 个 IP【待 T003 验证】）  │
    → 写 market.*（hypertable）+ Redis 热缓存 → PUBLISH market.updated ──────────────────┘
 [ingest 冷备：平时不运行；切换 = 停主 → 锁过期 → 等待 ≥ 60 秒 → 启备 → 核对出口 IP]
（*evaluation 在第三阶段启用，问题 26 已定）
```

- **`ingest`（行情采集服务）**：全系统**唯一**调用麦蕊、唯一持有 licence 的组件（详见 2.1A）。职责包括：URL 构造、令牌桶与优先队列、singleflight、重试（429/503 指数退避）、错误码映射（101/102/103）、原始响应落库（`raw_payloads`，供审计与快照使用）、IP 超限告警。原先设计中"datagw 作为库在 realtime/worker 内运行"的方案**作废**，因为多进程多主机外呼会违反 2-IP 限制。
- **API、worker、signal-rt 都不直接调用麦蕊**：用户请求只读本人证书名下的行情表和缓存（证券公开主数据全站一份）。缓存缺失时，向 `ingest:requests` 投递按需拉取意图，并返回 `data_status: "pending"`，避免用户行为放大外部调用；数据到达后通过 SSE 推送。

### 2.1A 行情采集服务 `ingest`：唯一调用麦蕊的服务（硬约束）
> 硬约束（2026-11-01 12:05）：同一证书 **60 秒内最多 2 个来源公网 IP**【文档/FAQ 已列，待 T003 验证】。因此全系统只有**一个**行情采集服务调用麦蕊，固定一个出口 IP；其他服务和所有用户只读我们的缓存和数据库。

- **唯一性**：
  - `ingest` 是独立容器，**`replicas: 1`**，也是**唯一**能解密用户证书的容器（只有它注入 `DATA_LICENCE_SEAL_PRIVATE_KEYS`；T-A07 起不再使用全站 `MAIRUI_LICENCE`，2.1B）。`api`、`worker`、`signal-rt`、`beat` 的环境中**没有**证书私钥，也不包含麦蕊 HTTP 客户端。CI 用 import-linter 规则检查：`app.ingest.mairui_client` 只能被 `app.ingest` 引用。
  - 进程启动时先获取 Redis 分布式**单活锁** `ingest:leader`（TTL 30 秒，每 10 秒续约，锁值含主机名、出口 IP 和启动时间）。拿不到锁就拒绝启动并告警。
  - 运行中如果续约失败，**立即停止所有外呼**，然后退出。
- **固定出口 IP**：
  - 生产环境由服务器的固定公网 IP 出网。启动时自检出口 IP，并与配置值 `MAIRUI_EGRESS_IP_EXPECTED` 比对；不一致时拒绝外呼并告警。
  - 不走代理池，不走多出口 NAT。
- **全局限流与请求队列**（全在 `ingest` 进程内，Redis 只作为状态持久化和监控）：
  - **令牌桶**（T-A07 起改为**每张证书一个桶**，本条与下表的份额规则对每张证书分别适用，见 2.1B）：`per_minute_budget`，默认每分钟 3,000，可热调；同时有并发上限 `max_concurrency`，默认 1。官网写钻石版每分钟 6,000 次，但计数口径和并发规则【待 T003 验证】。
  - **三级优先队列**，各级有预算份额，高优先级可借用低优先级的空闲额度：

    | 优先级 | 内容 | 预算份额 |
    |---|---|---|
    | **P0 盘中实时** | 快照和 1 分钟 K | ≥ 70% |
    | **P1 盘后与日批** | 日 K、因子、资金流、公告 | — |
    | **P2 历史回补、内部评估** | — | 盘中 0%，夜间可用满剩余额度 |
    | 按需拉取 | 用户首次查看冷门股时由 api 投递，归入 P1，并按"同证券、同接口"合并 | — |

  - singleflight 和请求去重：同一时刻同一个 URL 只调用一次。
  - **其他服务请求数据的方式**：只能往 Redis Stream `ingest:requests` 投递"拉取意图"（证券、数据集、优先级、截止时间），**不得直接外呼**。`ingest` 写库后，经 Redis pub/sub 发出 `market.updated` 事件；`signal-rt`、`worker` 和 SSE 只读库和缓存。
- **故障切换只做冷备**：
  - 备机（或备用容器）平时**不运行** `ingest`；证书私钥 `DATA_LICENCE_SEAL_PRIVATE_KEYS` 只在主机上（T-A07）。
  - 切换手册（`deploy/runbooks/ingest-failover.md`）：
    - ① 确认主机 `ingest` 已停止，并且锁已过期；
    - ② **等待 ≥ 60 秒**；
    - ③ 在备机注入证书私钥，启动 `ingest`（所有证书一起停、一起等 60 秒、一起恢复）；
    - ④ 核对出口 IP。
  - **任何时候都不允许两个活跃调用方。**
- **本地开发与测试，以及从本地迁移到服务器**：
  - 本地和 CI 默认 `MAIRUI_MODE=replay`，使用录制回放的 fixtures，**不持有真实 licence**。
  - **【已定 2026-11-01，问题 33】本地测试期：所有麦蕊调用都在用户本人的电脑上进行**（本机 `ingest` 或 T-B05 实测脚本，二者也不同时运行），这台电脑就是唯一调用方；其他机器（含共享开发机、CI、其他代理的环境）一律回放模式、不持有 licence。用户电脑的出口 IP 若变化，先停止调用并等待 ≥ 60 秒再继续；本地模式下出口 IP 自检只告警、不拒绝（`MAIRUI_EGRESS_IP_EXPECTED` 可不设）。
  - **上线后：只有服务器上的 `ingest` 调用**（单副本、单活锁、单一固定出口 IP）；用户电脑不再持有真实 licence。
  - **开发与生产任何时候都不能同时调用（硬规则）**：生产（或预发）`ingest` 在运行时，开发机**禁止**使用真实 licence；需要真实联调时，先按下面的迁移步骤停掉另一方。
  - 迁移步骤：
    - ① 停止本地 `ingest`；
    - ② 等待 60 秒；
    - ③ 启动服务器 `ingest`。

    本地的 `.env` 随后删除 licence。
  - 如需开发和生产并行，**申请第二张开发证书**（第 9 节问题 27）。
  - **T-A07**：本节“开发与生产不能同时调用”改为**按证书执行**；朋友的证书永远不离开生产 `ingest`，开发联调只允许用用户本人的证书，且须先在后台暂停该证书（2.1B 第 3 点）。
- **告警**：
  - **立即告警**（站内管理员通知 + 邮件）：麦蕊返回"IP 超限"（文档写码 103 / HTTP 429，具体返回【待 T003 验证】）、101/102 证书错误、单活锁丢失、出口 IP 不符、令牌桶连续 5 分钟耗尽。
  - **降级**（T-A07 起按证书处理，2.1B 第 6 点）：IP 超限时只暂停**该证书** 120 秒后再试，只把使用该证书的用户的 `data_status` 置为 `stale`；出口 IP 不符、单活锁丢失仍停止全部外呼。
- **可观测指标**：各优先级的队列长度和等待时延、每分钟调用数、按错误码统计的计数、每个数据集的新鲜度（`data_as_of` 落后多少）。

### 2.1B 每用户自用麦蕊证书（【用户已定 2026-11-02】，T-A07，契约 v0.2.6）

用户为每位朋友单独购买一张麦蕊证书（第 9 节问题 49）。每位用户在“设置 → 数据证书”录入**自己的**证书，`ingest` 只用该证书为该用户取数。2.1A 的单活、单出口、singleflight、原始响应留存规则不变；下列各点在其基础上改为“按证书”。

1. **存储与可见性**
   - 证书在 `user_data_licences.ciphertext` 中以 **HPKE（RFC 9180，Base 模式：DHKEM(X25519, HKDF-SHA256) + HKDF-SHA256 + AES-256-GCM）** 密文保存。`api` 只持有公钥（`DATA_LICENCE_SEAL_PUBLIC_KEYS`，按 `key_version` 编号；`DATA_LICENCE_SEAL_KEY_VERSION` 指定当前版本），**只能加密、不能解密**；私钥 `DATA_LICENCE_SEAL_PRIVATE_KEYS` **只注入 `ingest`**。AAD = `"mairui-licence|v1|" + user_id + "|" + row_id + "|" + key_version`，防止密文被挪到别的用户或行。
   - 不用 `APP_MASTER_KEY` 的原因：`api` 持有它，等于 `api` 能解密；证书明文也**不经过 Redis**（`ingest:requests` 只带 `licence_id`）。
   - 防一证多用：`api` 用 HKDF(`APP_MASTER_KEY`, info=`"data-licence-dedup-v1"`) 派生的键计算 `licence_hmac`，在未删除行上唯一；第二个用户绑定同一证书 → `409 DATA_LICENCE_IN_USE`。`licence_hmac` 不出接口、不进日志。
   - `api` 的数据库角色对 `ciphertext` 无 SELECT，只读视图 `user_data_licence_status`。**任何接口都不返回证书值或其任何片段**（没有末 4 位、没有指纹）；PUT 只返回状态。
   - 格式校验：去首尾空白后长度 16–64，只允许 `[A-Za-z0-9-]`（与 7.4A S1 一致，【待核实 T-B05：实际证书字符集与长度】）；拒绝 `/ ? # %` 与空白，防止拼进 URL 路径时注入。校验失败的消息不含输入值。
   - 脱敏：`ingest` 日志中 URL 的证书段替换为 `***`；`ingest` 另对已加载的全部证书明文做字符串替换（日志、异常、留存的上游响应）；`api` 请求体日志对 `licence` 字段脱敏；Sentry `before_send` 同样处理。
   - 密钥轮换：生成新密钥对 → `api` 切到新 `key_version` → `ingest` 后台逐行解密并用新公钥重新封装 → 旧私钥下线。私钥与数据库备份**分开保存**，开发环境恢复生产备份时无法解密证书（开发只能用用户本人证书，见第 3 点）。
   - 验证：PUT 或 `POST /me/data-licence/test` 后，`api` 向 `ingest:requests` 投递 `verify_licence`（只带 `licence_id`）；`ingest` 用一次轻量接口（如交易日历或单只实时行情）验证，结果写回状态表，经 SSE `data_licence` 与通知告知用户。

2. **调度（每证书令牌桶 + 证书间公平）**
   - **每张证书一个令牌桶**。默认取所填档位官方频率的**一半**（与 2.1A 留余量一致；官方档位见 T003 报告）：钻石 3,000/分钟（官方 6,000；过期后官方每天 2 万次）、包年 1,500（官方 3,000）、包月/体验 500（官方 1,000）、免费/未知 150（官方 300）。管理员可对单张证书覆盖（`per_minute_limit_override`）。全市场快照（1 次/分钟）、历史与全量接口（60 次/分钟）等**接口级限额也按证书计数**。
   - 每张证书有自己的 P0（盘中实时）> P1（日批/按需）> P2（历史回补）队列，份额规则同 2.1A。
   - **证书之间**：先比优先级（任何证书的 P0 先于其他证书的 P1），同一优先级内按**赤字轮转（DRR，quantum = 1 次调用）**依次出队，单个用户大量回补不会饿死别人的 P0。
   - 并发：`per_licence_max_concurrency` 默认 1；`global_max_concurrency` 默认 2，【待 T-B05 实测：同 IP 多证书并发是否触发限流】。
   - 熔断按证书；只有**所有**证书同时失败（多为出口或上游整体故障）才触发全局熔断。单活锁与 Stream 不变；`market.updated` 事件与缓存键都带 `licence_id`。

3. **网络**：所有证书都经同一固定出口 IP。2.1A 的“同一证书 60 秒内 ≤ 2 个 IP”规则**按证书执行**：朋友的证书永远不离开生产 `ingest`；开发或本机实测只允许用用户本人的证书，步骤为“后台暂停该证书 → 等 ≥ 60 秒 → 开发使用 → 停止 → 等 ≥ 60 秒 → 后台恢复”。

4. **共享与否**：`config/ingest.yaml` 的 `data_sharing.mode`：
   - `per_licence`（**默认，合规推荐**）：所有 `market.*` 行（证券公开主数据除外，见本条“例外”）、原始响应、Redis 缓存、特征都带 `source_licence_id`，每位用户只读本人证书取到的数据；麦蕊来源的参考数据（麦蕊证券列表与代码集、行业与概念、股本、交易日历）按证书各取一份。**例外（用户已定 2026-11-02，第 9 节问题 51；契约 v0.2.7 §1.1）**：证券公开主数据——代码、简称、拼音、曾用名、交易所、板块、上市日、状态、风险警示——全站一份；行业、概念、股本等仍按本人证书各取。公开主数据的确切来源（交易所公开列表，或用管理员本人证书拉取）【待问题 52 / T-A04 补测】；确认前只用交易所公开列表，**不得用他人（含管理员）的证书**为其他用户取数。
   - `shared_cache`：一份数据全站共用。用 A 的证书取到的数据给 B 看，按条款字面属于“再次分发/交由第三方使用”（7.1）。**【待麦蕊书面确认】（第 9 节问题 50），取得书面答复前禁止启用。**
   - **硬规则**：任何模式下都**不跨证书回退**——B 的证书不可用时，不用 A 或管理员的证书替 B 取数，也不把 A 的缓存给 B（`shared_cache` 获批后除外）。

5. **成本与容量**（每张证书分别计算，N 为该用户去重证券数）
   - 额度不是瓶颈：全市场快照 1 次/分钟；N = 1,000 只按 15 秒刷新约 200 次/分钟；分钟 K 约 `20 + (N − 20) / 5` 次/分钟；合计约 400 次/分钟，远低于钻石版的 3,000。
   - 瓶颈是**串行时延**：实测约 0.26 秒/次（T003），单连接约 230 次/分钟，两位重度用户就需要约 4 个并发连接。因此默认盘中配置为“全市场快照 60 秒 + 重点关注 ≤ 20 只 15 秒，其余用全市场快照”，每张证书约 5–30 次/分钟，10 位用户合计 50–300 次/分钟。
   - 盘后批量每张证书约 2–3.5 万次；10 张证书约 20–35 万次，串行需 10–15 小时。因此盘后批量**只取该用户自选与持仓范围**，加上批量日 K 接口。
   - `shared_cache` 只需取一份，成本约为 `per_licence` 的 1/用户数；这只是成本差异，在麦蕊书面确认前不作为启用理由。

6. **降级与状态**（麦蕊异常常以 HTTP 200 + `{"error": …}` 返回，`ingest` 必须解析响应体）

   | 上游信号 | 证书状态（`data_licence_status`） | 处理 |
   |---|---|---|
   | 102 证书无效 | `invalid` | 立即停止该证书的全部调用，不自动重试；通知用户与管理员；用户重新 PUT 或点“测试”后才恢复 |
   | 101 当日额度用完 | `quota_exceeded` | 暂停到北京时间次日 00:01 |
   | 103 / HTTP 429（IP 超限） | `ip_limited` | 暂停 120 秒；1 小时内 3 次 → 暂停 1 小时，并通知用户（“证书可能正在别处使用”）和管理员 |
   | 频率 503 | 不变（`active`） | 该证书退避 1 → 2 → 4 … 60 秒；连续 5 次 → 熔断 300 秒（`paused_until`） |
   | 数据缺失型 503 | 不变 | 不熔断，记缺失 |
   | 网络错误 / 5xx | 不变 | 按证书退避（同频率 503） |
   | 超过用户填的 `expires_on` | `expired` | 钻石版按过期后每日额度运行，只保留 P0 重点关注与全市场快照；其他档位停止；通知 |
   | 管理员暂停 | `paused_by_admin` | 停止，直到管理员恢复。暂停按用户记录：期间用户 PUT 新证书或同一证书 → `202`，状态仍为 `paused_by_admin`，不验证；DELETE 后再 PUT 也不解除（契约 v0.2.8） |

   - 用户看到：行情接口的 `data_status` 为 `stale`（有旧数据）或 `unavailable`（从未取到），`gaps[].reason = "data_licence_unavailable"`，前端显示横幅“你的数据证书不可用：{状态}，请到 设置 → 数据证书 处理”。需要触发拉取的写操作（如手动刷新）返回 `409 DATA_LICENCE_UNAVAILABLE`。
   - 通知：`notification_kind` 新增 `data_licence`（状态变化、验证结果、到期提醒）。**到期提醒**在用户填写的 `expires_on` 前 30、7、1 天各一次（麦蕊接口是否返回到期日【待核实】，所以由用户填写；可在 https://www.mairuiapi.com/query 自查）。
   - 管理端 `GET /admin/data-licences` 只列状态、档位、到期、调用量与队列长度，**不显示证书值**；可暂停/恢复（写审计）。重复 PUT 同一证书不清除 `quota_exceeded`、`ip_limited` 和 `paused_until`（契约 v0.2.8）。

7. **`MAIRUI_LICENCE` 的去留**：生产和预发**不再使用**；`ingest` 发现它非空即拒绝启动。用户本人的证书也和朋友一样，在网页中录入。只有 T-B05 等本机实测脚本可在用户本人电脑的 shell 中**临时**设置它，绝不写入 compose、`.env` 或仓库。

### 2.2 后端模块（与五种能力映射）

| 模块（包名） | 职责 | 服务的能力 |
|---|---|---|
| `identity` | 用户名注册、登录、会话、账号状态机（pending/approved/rejected/disabled）、防滥用（限速、锁定）、固定免责提示（无同意流程，T-A06）、~~数据导出~~（T-B16 移除）；账号删除由管理员手动处理（T-A06） | 全部 |
| `admin` | 管理员审核后台：待审核列表、批准、驳回（附理由）、禁用/恢复、重置密码、审计日志查看；管理员角色 | 平台运营 |
| `importing` | 交割单导入：文件接收与留存、编码识别、券商解析器插件、列映射、预览确认、去重幂等、错误行报告、导入批次 | 1、5 |
| `profile` | 投资画像：资金规模区间、投资期限、风险承受、可投入精力（小时/周）、关注方向；全部由用户确认，带 `confirmed_at` | 1/2/3 |
| `marketdata` | 证券主数据、交易日历、行情、财务、资金流、因子、公告、问董秘的存储与查询（麦蕊来源按证书隔离，证券公开主数据全站一份，2.1B）；数据完整性（gap）判断 | 全部 |
| `portfolio` | 账户、期初持仓、成交记录（只追加+冲正）、持仓计算（移动加权成本）、资产与暴露（行业/个股集中度） | 1、5 |
| `situation` | "今日关注"聚合：持仓相关事件、计划触发、提醒、数据缺口；市场概览 | 1、4 |
| `strategy` | **策略三层**（2.5.0、2.5.13）：L1 卡片、L2 模板（接口、注册表、生命周期、规则求值器）、L3 实例；候选信号、不可执行原因、计划草案；筛选；周期分类器 `horizon` 子模块 | 主线、2 |
| `research` | 研究候选、证据条目（claims）、反证、个人适配性检查、用户决定（继续研究/观察/放弃） | 2 |
| `planning` | 行动计划：动作、理由、触发条件、投入、风险、失效条件、复核日期；完整性检查；版本+快照 | 3 |
| `alerts` | 提醒规则（由计划条件、持仓事件、用户自定义派生）、评估引擎、提醒实例生命周期、投递 | 4 |
| `review` | 复盘：计划版本 ↔ 成交 ↔ 结果；判断/执行/市场环境三分归因；经验标签与策略边界统计 | 5 |
| `snapshot` | 数据快照生成与读取（as-of 回看） | 3、5 |
| `compliance` | 输出措辞校验（禁用词表）、固定免责提示（`docs/strategies/compliance/disclaimer.md` 1.0）、审计日志 | 全部 |
| `ingest` | **行情采集服务**（独立容器，全站唯一调用麦蕊）：客户端、令牌桶、优先队列、单活锁、出口 IP 自检、告警（2.1A） | 全部 |
| `jobs` | Celery 任务定义与调度表 | 全部 |
| `realtime` | universe 维护与分层、刷新计划（生成 P0 拉取计划交给 `ingest`）、stale 判定（0A.3）；**不外呼** | 主线 |
| `signal_rt` | `signal-rt` 进程入口：订阅 `market.updated` → 特征增量 → 规则求值 → 候选信号 → 可执行性 → 原因解除监控 | 主线 |
| `features` | 唯一的特征管线与 `feature_catalog`（2.5.10） | 主线 |
| `market_rules` | A 股交易规则（2.13） | 主线、5 |
| `evaluation` | 内部评估，仅管理员可用（2.12.4，问题 26） | 平台 |
| `signals` | 信号状态（证书内共享/用户）、翻转检测、信号事件 | 主线、4 |
| `advice` | 建议引擎：流水线、置信度、分歧分析、不可变建议与建议链（2.5.4） | 主线 |
| `risk` | 六项风控 RC1–RC6、风控设置与事件（2.5.6） | 主线、3 |
| `reports` | 盘后流水线与日报（0A.5） | 主线、1 |
| `tracking` | 模拟跟踪 T+1/5/20、策略统计、自动降权（2.5.7、2.8） | 主线、5 |
| `llm` | LLM 网关：供应商、路由、模板、守卫、用量（2.7） | 主线 |
| `notify` | 通知中心、SSE 广播、渠道适配器、偏好与频控（2.6） | 主线、4 |
| `billing` | 会员权益预留：套餐、权益、订阅、`EntitlementService`（2.9） | 平台 |

### 2.3 五种能力的 MVP 范围

#### 能力 1：看清当前处境
**做什么**
- **导入券商交易软件导出的交割单/成交单文件（通常 .txt）**建立成交与持仓（见 3.5 节导入层）；同时保留手动录入账户、期初持仓、成交；也接受我们提供的标准 CSV 模板（作为兜底格式）；持仓、成本、浮动盈亏、仓位占比、行业暴露（行业来自麦蕊板块/行业接口）、前五大集中度。
- 市场概览：主要指数（`/hsindex/real/time`）、涨跌家数（由全市场快照计算）、涨停/跌停池数量、行业/概念资金流（`/hibk/zjhhy`、`/hibk/gnbk`）。
- 与我相关的变化：持仓/观察股的公告（标题+原文链接）、业绩预告/快报、解禁、龙虎榜上榜、涨跌停、问董秘新回复、大幅波动。
- **数据完整性面板**：每个结论标明"已确认 / 有缺口 / 暂无法形成"，例如"未录入现金余额 → 无法计算总仓位比例"。
- "今日关注"首页：按与用户相关度排序（持仓权重 × 事件严重度 × 是否影响某份计划），不按"股票好坏"排序。
- "今日关注"的提醒、计划触发、数据缺口三块的结构、排序与“查看全部”去向见契约 v0.2.7 §7.3 `/today` 补充。

**不做什么**：券商账户直连/自动同步（不收集券商账号密码）、截图/PDF OCR、Excel(.xls/.xlsx) 交割单（MVP 只接受文本类 .txt/.csv，待范本确认后再定）、两融/期权/港美股/基金净值估值（基金仅作为证券代码存在）、Level-2/逐笔、实时推送流（WebSocket）。

#### 能力 2：找到值得投入精力的机会
**做什么**
- **策略库**（2.5，取代早先"方法库"）：内置策略（具体策略见 `docs/strategies/`（由策略研究员维护），经 2.5.14 导入）按四种周期 × 六个维度组织，规则、阈值、数据来源全部可见；用户可复制并改参（形成用户策略版本）。
- **策略筛选**：用某个策略在全市场因子截面上筛选（`/factor/screen` + 本地规则求值），结果可加入自选或研究候选。
- **从股票看策略**：对任一股票，逐个策略、逐条规则展示是否满足与当前值；**策略之间矛盾时不合并**，按"维度 × 策略"矩阵并列（2.5.4）。
- **研究候选卡**：研究理由（满足了哪些规则——`fact`）、成立条件（`hypothesis`，用户填写）、主要反证（系统列出不满足的规则与风险因子）、个人适配性检查、用户决定（继续研究 / 加入观察 / 放弃，必须选理由）。

**不做什么**：跨策略合成的"综合评分/综合结论"；"牛股/精选"榜单；**回测引擎**（以 T+1/5/20 模拟跟踪替代，2.8）；用户自写代码策略（MVP 只允许受限表达式改参）；**候选信号直接"转计划"**（候选信号 ≠ 计划，必须经过计划草案和用户确认，2.5.8）；内部评估结果对普通用户展示（2.12.4）。

#### 能力 3：形成行动计划
**做什么**
- 结构化计划：动作类型（买入/加仓/持有/减仓/退出/等待）、为什么（引用证据条目）、何时行动（价格/指标/事件/日期条件）、投入多少（金额与占总资产比例，**仓位计算器**：用户输入可承受最大亏损和失效价位 → 计算对应股数，仅为算术）、承担什么风险、什么情况下改变判断（失效条件，必填）、复核日期。
- 完整性检查：缺失失效条件、缺证据、投入超过画像风险上限、与现有持仓集中度冲突 → 警告（不阻止）。
- 每次保存生成新版本 + 数据快照；可对比版本差异。
- 计划条件自动生成提醒规则（能力 4）。

**不做什么**：下单/对接券商、目标价、"最优仓位"推荐、多计划组合优化。（规则化的买卖动作与止损/止盈价由主线候选信号给出，2.5；**计划只能从"计划草案 → 用户确认"生成**，草案必须引用至少 1 条可解释的规则信号，2.5.8 和 0B。用户也可以完全手动新建计划。）

#### 能力 4：在需要时得到帮助
**做什么**
- 规则来源：①计划中的触发/失效条件；②持仓与观察股事件（公告、业绩预告、解禁、涨跌停、龙虎榜、大幅波动）；③用户自定义价格/涨跌幅提醒。
- 评估频率：价格类盘中每 1 分钟（被跟踪证券池）；事件类盘后批处理；因子类收盘后。
- 提醒内容三段式：**发生了什么**（事实+来源+时间）→ **影响哪份判断/计划**（链接到计划版本、哪条条件）→ **现在需要核对什么**（从计划失效条件/风险项生成的核对清单）。
- 投递：站内通知中心 + 可选邮件（用户自愿填写邮箱后开启；即时/每日摘要可选），免打扰时段，去重与合并（同一证券同一类 30 分钟内合并）。
- 用户处理：已读 / 已核对（附备注）/ 据此修改计划（跳转新版本）/ 忽略。

**不做什么**：短信、个人微信、App 推送；逐笔触发（盘中最快为快照刷新间隔，0A.3）；LLM 生成任何结论（LLM 只按证据写解释，2.7）。渠道：站内 + SSE 实时 + 可选邮件，企业微信为二期（2.6）。

#### 能力 5：从真实经历中积累经验
**做什么**
- 自动把"计划版本 → 相关成交 → 后续结果"串成时间线；结果指标：持有期收益、同期基准（沪深300/所属行业指数）收益、超额、最大回撤。
- 三分归因（规则化，非精确归因）：
  - **市场环境**：同期基准/行业表现（`fact`）；
  - **执行**：成交价/数量/时间 vs 计划（偏离度，`fact` 计算）；是否在失效条件触发后按计划行动；
  - **判断**：计划中的成立条件后来是否兑现（由用户标注 + 可自动核对的数据项）。
- 复盘表单：用户结论、经验标签（如"追高""未设止损""方法适用边界：周期股估值法失效"），按标签和方法统计出现次数。
- **按原貌回看**：查看任一历史计划/候选时，默认显示当时版本 + 当时快照中的数据，并可切换"与现在对比"。

**不做什么**：Brinson 等专业业绩归因、自动挖掘行为模式、社区分享复盘。

### 2.4 前端信息架构（页面）
深色交易终端风格、仅桌面（2.10）。新增主线页面：`/terminal`（交易终端，**不是首页**——首页为 `/today`，`/` 重定向到 `/today`，契约 v0.2.8：自选/持仓实时表 + K 线/分时 + 建议卡 + 信号流；固定三栏 + 底部面板，分隔条可调宽、可折叠，见 2.10）· `/suggestions`（建议列表，按状态筛选，契约 v0.2.7）· `/suggestions/:id`（建议详情：维度×策略矩阵、证据、反证、失效条件、风控标记、建议链）· `/daily-reports`、`/daily-reports/:date`（盘后日报；旧路径 `/reports`、`/reports/:date` 只做重定向，契约 v0.2.3）· `/strategies`、`/strategies/:id`（策略库：规则清单、数据来源、版本、改参、胜率/盈亏、降权开关）· `/risk-controls`（六项风控开关与阈值；“事件”页签 `?tab=events` 列出生效中的风控事件，契约 v0.2.7）· `/notifications`（通知中心与偏好）· `/strategy-cards`（L1 卡片库，第二阶段）· `/strategy-instances`（我的策略实例：列表筛选、确认、暂停、恢复、归档、改参；状态机见契约 §6.0A）· `/candidate-signals`（候选信号列表，含“今日解除”页签 `?tab=released`，契约 v0.2.7）· `/candidate-signals/:id`（候选信号与不可执行原因）· `/plan-drafts`（草案列表，按状态筛选，契约 v0.2.7）· `/plan-drafts/:id`（计划草案确认页）· `/restrictions`（禁投、冷静期、屏蔽）· `/admin/llm`、`/admin/realtime`、`/admin/ingest`（采集状态）、`/admin/promotions`（模板审核与生命周期）、`/admin/evaluation`（内部评估，问题 26 获批后）、`/admin/plans`（管理端）。
原有页面保留：`/register`（注册，提交后显示"等待管理员审核"）· `/login` · `/account-status`（待审核、驳回、停用说明；T-A05 D9）·（`/onboarding` 已作废：没有同意与测评步骤，画像在 `/settings` 中选填，T-A06）· `/today`（今日关注，**首页**；`/` 重定向到此）· `/portfolio`（账户/持仓/成交）· `/market`（市场概览）· `/stocks/:code`（个股档案：行情、财务、资金流、因子、公告、问董秘、各策略适配与周期分类）· `/discover`（策略筛选，入口并入 `/strategies`）· `/candidates`（研究候选）· `/plans`（行动计划，含版本对比）· `/alerts`（提醒中心与规则）· `/reviews`（复盘）· `/settings`（画像、通知、隐私；~~数据导出/注销~~ T-B16 裁定移除导出，注销由管理员线下处理）· `/portfolio/import`（上传→预览→确认→结果）· `/admin/*`（管理员后台：注册审核、用户管理、审计日志，仅 admin 角色可见）。

所有页面固定位置展示免责提示（前端 `RiskDisclosure` 组件；页面底部、候选信号与行动计划卡片处）："本工具仅供个人研究参考，不构成投资建议。候选信号由规则自动生成，数据可能延迟或出错，盈亏自负。"——文案以 `docs/strategies/compliance/disclaimer.md`（1.0，2026-11-02 定稿）为准，代码与该文件逐字一致。**只展示，不需要用户勾选或确认，不记录同意**（T-A06，第 9 节问题 43）。

### 2.5 策略库（Strategy Library）与建议引擎 —— 以 vision.md《策略库需求》为准
> 本节取代早先的"方法库"设计（文中"方法"即"策略"）。用户确认：① 四种持有周期全部兼顾，持仓导入后自动判定每只标的适合的周期与策略并给出理由，用户可改；② 六个判断维度全部纳入、越细越好；③ 信号矛盾**不合并结论**，按维度并列展示观点、依据与分歧点；④ 六项风控全部实现、逐项可开关；⑤ 模拟跟踪展示各策略胜率与盈亏，并可开关"自动降低表现差策略的推荐优先级"。

#### 2.5.0 三层结构 + 共享指标底座
> 方向由用户 11:51 确定。结构采纳 [`strategy-references.md`](./strategy-references.md)（T002 开源调研）§3–§4 的建议，并按本文的输出协议和可解释原则（0B）做了调整，取舍说明见 2.11。

```
        ┌──────── 共享指标底座（不算一层，所有层共用，一个口径）────────┐
        │ ingest(麦蕊) → 库 →features/pipeline.py（唯一产出者）→ feature_bars_daily / │
        │ 盘中 1 分钟特征（Redis 环形缓存，收盘落库）；feature_catalog = 字段白名单 │
        │ data_snapshots 记录 feature_set_version，可按原貌回看                     │
        └───────────────────────────────────────────────────────────────────────────┘
L1 策略知识卡 strategy_cards / strategy_card_versions（解释用，可只有文字，规则可标"待量化"）
   │ 晋级门槛 G1–G7（2.5.0B：机器检查 + 人工审核）
   ▼
L2 可运行模板 strategies / strategy_versions（不可变配置版本；唯一的 RuleEvaluator 执行）
   │ 实例化要求 I1–I7（2.5.0C）
   ▼
L3 策略实例 strategy_instances → 扫描 → 候选信号 candidate_signals（不可变，可追溯，P1）
   │ 可执行性检查（持仓、现金、T+1、涨跌停/停牌、上限、风控 RiskHook、计划冲突、冷静期……）
   ├──► 不可执行原因 non_executable_reasons（每条带解除条件；系统监控，解除后重评并通知）
   ▼
   计划草案 plan_drafts（按真实持仓和现金拟定数量、价格区间，附人工判断清单）
   │ 用户确认
   ▼
   操作计划 action_plans / plan_versions（用户的计划；条件满足时提醒，不下单）
   └→ 模拟跟踪 → 表现回填 L1 卡片和 L2 版本 → 可开关的降权（只影响排序）
```
- **不设独立的"信号层"**。原子信号就是 L2 模板中的一条规则（`dimension + role + expr`），可复用的条件做成命名规则片段 `rule_snippets`，由模板引用。这样避免"信号定义"和"策略中的信号"出现两份口径。
- **L1 与 L2 共用一份卡片 schema，用完整度状态区分。** 卡片晋级后生成 L2 版本，卡片继续作为该模板的说明页。
- **表名约定**：L2 沿用 `strategies` / `strategy_versions`，即调研文档中的 `strategy_templates` / `template_versions`，以免与 0A、3.3 的既有命名冲突。
- **候选信号汇总卡 `suggestions`**：同一用户、同一证券在某一时刻的候选信号汇总视图，包含维度 × 策略矩阵、分歧、风控标记、可执行性和计划草案入口。它不是计划。表名和接口沿用 `suggestions`，界面称"**候选信号卡**"。
- **措辞**：候选信号写作"规则信号：买入条件满足（候选）"；草案写作"按您的持仓和资金拟定的计划草案"；确认后写作"您的计划"。**任何层都不出现"立即买入 / 立即卖出"。**
- **执行形态**：默认只用规则 DSL。少量 DSL 难以表达的逻辑（分时 VWAP 偏离带、碗口等形态识别、情绪周期阶段）用**经代码审查的内置 `FeaturePlugin`**（纯函数、无 IO、进程启动时注册），插件**只产出特征列**，不产出动作。这样动作映射、风控和跟踪都只有一条路径。**任何人和 LLM 都不能提交可执行代码。**

#### 2.5.0A L1 策略知识卡：字段
本节以 vision.md《策略卡字段定稿》为蓝本，按调研建议精简为"8 个必填 + 选填 + 系统字段"，以免新手读不完。完整对照见 2.11。卡片由头表 `strategy_cards` 和不可变的 `strategy_card_versions.content`（jsonb）组成，每个字段都标 `epistemic_type`。

| 类别 | 字段 | 说明 |
|---|---|---|
| 必填 1 | 身份：`key`、`name`、`category`、`version_no` | `category` 取值：trend / momentum / reversal / breakout / value / quality / dividend / low_vol / event / intraday_t / risk（T-R15） |
| 必填 2 | 适用周期 `horizons[]` | intraday_t / short / swing / long |
| 必填 3 | 一句话原理 `hypothesis.why_it_works`，以及否定它的证据 `hypothesis.falsified_by[]` | `hypothesis` |
| 必填 4 | 维度与角色 `dimensions[]`：`{dimension, role(core/auxiliary/veto)}` | 六个维度 |
| 必填 5 | 成立条件 `entry[]`：`{text, expr\|null, status(quantified/to_quantify)}` | |
| 必填 6 | 反证与失效条件：`counter_evidence[]`、`invalidation[]`，格式同上 | 0B P1 要求至少 1 条反证 |
| 必填 7 | 退出规则 `exit[]`：止损 / 止盈 / 时间止损 / 跟踪止盈，至少一种 | 做T策略须有"当日回补或时间止损" |
| 必填 8 | 数据需求 `data_needs[]`：`{feature_key, frequency, adjust(none/qfq/hfq), available_at}` | 引用 `feature_catalog`，由系统标出已核实、待核实、缺口 |
| 选填 | 适用市场环境与标的类型，以及不适用时的处理（暂停或只提示）；标的范围（股票池、排除项、流动性下限）；仓位与风控建议（单标的上限、策略预算、单笔最大亏损；引用 RC1–RC6）；常见误用与陷阱；个人适配（盯盘时间、波动承受 1–5、经验等级）；来源 `sources[]`：`{title, kind, url_or_ref, source_version, license, license_status}`；合规文案变体 | 来源若为 CC BY-NC、AGPL 或无许可证项目，只能作"思想引用"（7.6） |
| 系统 | 完整度 `completeness`：`draft / documented / runnable_candidate / promoted / retired`（自动计算，不可手填）；表现记录（只读，从 L2 跟踪回填）；最近复审提示 | |

**不放在卡片上的内容**：
- **运行态**（最近扫描时间、数据状态、信号与阻断原因）放在 L3 的实例、信号和原因表中。
- **复盘**（信号表现、实际操作差异、失效记录）放在能力 5。
- **验证区间、样本外、交易明细**：不做回测，以 T+1/5/20 模拟跟踪代替。
- **参数敏感性**：延后。
- **选股的筛选、排序、入选数量，以及冲突与互斥**：放在 L2 模板配置中。

#### 2.5.0B 晋级门槛 L1 → L2（G1–G7，按调研 §3.3 采纳并补充 P1）
| 关卡 | 检查内容 | 方式 |
|---|---|---|
| G1 规则完整且可解释 | 入场、失效/退出、止损三类规则**全部已量化**（无 `to_quantify`）；每个周期至少一条 exit（多周期卡按 T-R24 Q-01 裁定：exit 规则**声明即适用**于全部声明周期，机器判定 = exit 规则集非空且含止损类，不按周期拆分；schema 支持按规则标注适用周期前，不认部分适用）；做T 须有当日回补或时间止损；**至少 1 条反证规则**；每条规则都能产出 `rule_refs` 和 `evidence`（P1） | 自动 |
| G2 数据可得 | 每个字段都在 `feature_catalog` 白名单内，且来源状态不是"缺口"。只有文档依据（`verified_doc`）的字段只能晋级到 `simulating`（模拟中）；T-B05 实测确认（`verified_live`）后才可能 `published`。预热窗口不足时输出 `insufficient_data`，不算失败 | 自动 |
| G3 语法安全 | DSL 解析为 AST，只允许白名单字段、运算符和函数（比较、布尔、`cross_up/down`、`ma()`、`for N days`、`rank_pct`、`between`）；限制表达式长度和嵌套深度；**不执行任意代码** | 自动 |
| G4 参数 schema | 每个参数都有 `type/default/min/max/step/说明`，默认值在范围内；类型严格（不允许用字符串表示布尔值） | 自动 |
| G5 可交易性与 A 股约束 | 自动挂载通用闸门 `gate_tradability`（2.5.11）；止损止盈价限制在涨跌停价范围内；按 T+1 处理可卖数量 | 自动 |
| G6 历史体检（默认**不是回测**）+ fixtures + 配额 | 在最近 120 个交易日的指标宽表上**只统计**触发频率和数据覆盖率：触发率过高（> 30% 股票-日）或为 0 时警告；与已有模板命中集合的 Jaccard > 0.9 视为重复。**默认不计算收益、胜率、夏普**；若第 9 节问题 26 获批，再附一份**仅管理员可见**的内部评估报告（K 折样本外稳健度、IC、事件 CAR，均附 n，2.12.4），作为 G7 审核的参考，是否设硬门槛由管理员配置。另外，至少 6 个 golden fixtures 全部通过（满足、不满足、缺数据、维度分歧、涨跌停或停牌、做T 无底仓）；配额增量在 `per_minute_budget` 余量内 | 自动（worker 中用只读账号执行，设超时） |
| G7 人工审核 + 合规文案 | 全站内置或共享模板由管理员审核，用户私有模板由本人确认。审核页并排展示卡片文字与规则的逐条对应，以及 G1–G6 报告；文案须通过禁用词校验。全站内置/共享模板的代批程序见 2.5.13 G7（T-A109），不放松缺证据不得批 | 人工 |

- 不通过时卡片留在 L1，并显示缺哪一关（例如"止损规则待量化"）。这本身就是给新手的教育信息。
- 晋级后进入生命周期 `simulating`（2.5.13）：只做模拟跟踪，不生成计划草案；满足发布条件并经管理员批准后转为 `published`。退役 `retired` 需管理员确认，使用它的实例会收到提示，旧信号仍可回看。
- **用户改参**会生成**用户私有派生版本**，记录 `parent_version_id`、`param_hash` 和 diff。版本不可变；实例只引用具体版本，升级必须显式操作。
- **LLM 策略草稿**（第三阶段，2.7）只输出 JSON（卡片字段 + DSL + 参数 schema），自动跑 G1–G6，最多修正 3 轮；仍失败则降级保存为 L1 卡片。产物永远是 `draft`，必须经过 G7 人工审核。

#### 2.5.0C 实例化要求 L2 → L3
| 要求 | 内容 | 不满足时 |
|---|---|---|
| I1 | 模板版本状态为 `published` 或 `observing`（`simulating` 只允许管理员和自愿参与模拟的用户实例化，且不生成计划草案；**MVP 只允许管理员实例化，自愿参与列入 T-B79，见契约 §6.0A 第 9 条**） | `STRATEGY_VERSION_NOT_RUNNABLE` |
| I2 | 用户已批准（T-A06：不再要求风险测评或同意） | HTTP 层 `403 ACCOUNT_NOT_APPROVED` |
| I3 | 所选周期在模板 `horizons` 内。周期分类判定“不适合”、或画像低于卡片适配下限（`fit`）时**只在响应 `warnings[]` 中提示，不需要确认、不阻止**（T-A06：`fit_ack` 作废，用户可自由选择 short 与 intraday_t）；画像相关字段未填写时不提示；画像不匹配**不降低置信度**（T006e） | `STRATEGY_HORIZON_MISMATCH` |
| I4 | 参数覆盖都在 `min..max` 内；有覆盖时自动生成派生版本 | `STRATEGY_PARAM_OUT_OF_RANGE` |
| I5 | 范围（持仓 / 自选 / 指定证券 / 模板筛选结果）在权益上限内；做T 实例要求有底仓 | `ENTITLEMENT_LIMIT_REACHED` / `INSTANCE_SCOPE_INVALID` |
| I6 | 风控设置已解析，并快照到实例版本；若关闭了 RC1，实例和卡片持续显示警示 | 只警示 |
| I7 | 范围内证券的必需数据有覆盖（例如北交所部分数据【待 T003 验证】）；不覆盖的证券标为 `partial` | 只警示 |

- 周期分类器（2.5.3）生成的实例为 `status=proposed`，**用户确认后才变为 `active`**（第 9 节问题 15）。

#### 2.5.1 概念与数据结构
| 概念 | 说明 | 存储 |
|---|---|---|
| 周期 horizon | `intraday_t`（日内做T）、`short`（短线 1–5 天）、`swing`（波段 数周–数月）、`long`（中长线 半年以上） | 枚举 |
| 维度 dimension | `technical` 技术、`capital` 资金（主力资金流、龙虎榜）、`fundamental` 基本面（估值/财务/成长）、`sentiment` 情绪（涨跌停/竞价/热度）、`sector_market` 板块与大盘、`news` 消息（公告/新闻） | 枚举 + `dimension_definitions`（说明、数据源、覆盖缺口） |
| 规则 rule | 原子条件：`{id, dimension, expr, params, weight, role: entry/hold/weakening/exit/filter/veto/counter/invalidation, required_data[], description}`（`veto` 只阻断、不触发；`counter` 生成反证；`invalidation` 生成失效条件，2.5.13）；`expr` 为受限表达式（因子/行情字段/本地指标 + 比较 + 布尔），不执行任意代码 | `strategy_versions.config.rules[]` |
| 策略 strategy（= L2 模板，2.5.0） | 一组规则 + 适用周期 + 参数 + 动作映射 + 止损止盈规则 + 适用条件 + 失效模式 + 个人适配维度 | `strategies`（头）+ `strategy_versions`（不可变） |
| 参数 parameters | 规则阈值的命名参数（如 `rsi_low=30`），带默认值、取值范围；用户副本可改 | `config.parameters{}` |
| 风控配置 | 六项风控的开关与阈值（系统默认 → 用户覆盖） | `risk_control_settings` |
| 权重 weights | 规则权重（维度内评分）；策略优先级权重（由跟踪表现自动计算，可关） | `config.rules[].weight`；`user_strategy_weights`（2.8.2） |
| 跟踪统计 | 每策略版本 × 周期 × 范围（本人/全站）的胜率、盈亏、样本数、最大连续亏损 | `strategy_tracking_stats`（由 `suggestion_tracking` 汇总） |

**策略版本配置（`strategy_versions.config`）**：格式以 2.5.14 C 节为准（含**示例**）。具体策略的配置由策略研究员在 `docs/strategies/` 中给出，经导入器生成。

#### 2.5.2 维度数据底座（接口与因子）；具体策略不在本文
> **【待 T003 验证】本节所有数据可用性结论**（接口、字段、因子、限流、历史深度、刷新间隔、上限推算）都来自文档推导，须以后端实测报告 `/workspace/team/reports/T003-mairui-capability.md` 为准；报告出来后逐项替换本节标记。

接口路径省略前缀与 `/{licence}`；因子均来自因子文档（`/factor/{类别}/{code}`、`/factor/batch`、`/factor/screen`）。**状态**："已核实"= 2026-11-01 官网文档有此接口/因子（未实测）；"待核实"= 文档口径不清或需实测；"缺口"= 麦蕊无此数据。

**通用维度评估器（各策略共用的数据底座）**

| 维度 | 麦蕊可提供（已核实-文档） | 本地计算 | 缺口与补充方案 |
|---|---|---|---|
| 技术 | 实时：`/hsrl/ssjy_more`、`/hsrl/ssjy/all`、`/hsstock/real/five`（五档）；K 线：`/hsstock/latest`、`/hsstock/history`（5/15/30/60/d/w/m）、Pro 1 分钟 `/hsstock/pro/latest`、`/hsstock/pro/history`；指标接口 `/hsstock/history/{macd\|ma\|boll\|kdj}`；因子：`ma_trend`、`ma5_ma20_cross`、`ma20_ma60_cross`、`macd_signal`（golden_cross/death_cross/bull_divergence/bear_divergence/none）、`kdj_signal`、`rsi_14`、`boll_position`（upper/middle/lower/breakout_upper/breakout_lower）、`boll_squeeze`、`momentum_5d/20d/60d/120d`、`rs_20d`、`high52_distance`、`volume_ratio`、`volume_price_divergence`、`volatility_20d/60d`、`intraday_amplitude_20d`、`intraday_momentum_20d`、`vwap_deviation_20d`、`overnight_gap_20d` | 当日分时 VWAP（由 1 分钟 K 计算）、ATR14、前高/前低、日内偏离度 | 实时快照字段名与是否含量比/换手【待 T003 验证：T-B05】 |
| 资金 | 因子 `main_5d_net`、`main_20d_net`、`big_order_net_5d`、`flow_5d_ratio`、`flow_20d_ratio`；个股资金流 `/hsstock/history/transaction/{code}`（日频，文档写盘中约 30 分钟更新）；龙虎榜 `/hilh/mrxq`、`/hilh/ggsb/{n}`、因子 `dragontiger_count`；行业/概念资金 `/hibk/zjhhy`、`/hibk/gnbk`、`/hizj/zjh`、`/hizj/bk` | 资金流连续性（连续 N 日净流入） | 北向 `north_*` 因子按设计返回空（缺口，不用）；**盘中逐笔主力资金无实时接口**（缺口，盘中只用日频 + 30 分钟更新的资金流【待 T003 验证】） |
| 基本面 | 估值 `pe_ttm`(+`_rank`)、`pb`(+`_rank`)、`ps_ttm`、`pcf_ttm`、`peg`、`ev_ebitda`（可能为空）、`graham_value`、`price_vs_graham`；质量 `roe_ttm`、`roa_ttm`、`gross_margin`、`net_margin`、`debt_ratio`、`current_ratio`、`accrual_ratio`、`asset_turnover`；成长 `rev_yoy`、`profit_yoy`、`eps_yoy`、`rev_cagr_3y`、`profit_cagr_3y`、`eps_cagr_3y`、`rev_profit_scissors`；分红 `dividend_yield`（上线阶段标注不一【待 T003 验证】）、`dividend_continuous_years`、`dividend_growth_3y`、`dividend_avg_3y`、`payout_ratio`；财务三表 `/hsstock/financial/*`；业绩预告/快报 `/hicw/yjyg`、`/hicw/yjkb`、`/hscp/yjyg/{code}`；分红 `/hscp/jnfh/{code}` | 行业内分位（截面本地计算）、自身历史分位 `/factor/percentile` | 一致预期/盈利预测（缺口，MVP 不用） |
| 情绪 | 涨停/跌停/炸板池 `/hslt/ztgc/{date}`、`/hslt/dtgc/{date}`、`/hslt/zbgc/{date}`（盘中每 10 分钟）；因子（`/factor/sentiment`）`limit_up_streak`（连板）、`limit_up_break`（炸板）、`seal_ratio`（封成比）、`seal_to_float`（封流比）、`limit_up_count_20d`、`limit_down_count_20d`、`pre_auction_volume_ratio`（集合竞价量比）、`attention_score`/`attention_rank`（**文档说明基于问董秘近 60 日活跃度**，不是市场热度） | 市场宽度（全市场快照涨跌家数、涨停/跌停家数比）、炸板率、连板高度 | **市场热度/人气（股吧、搜索、社交讨论）麦蕊无**（缺口）；补充：MVP 用"涨停/炸板/连板/宽度"替代并在界面注明；后续评估持牌资讯商的舆情数据（授权【待 T003 验证】），不抓取社区网站 |
| 板块与大盘 | 指数实时 `/hsindex/real/time/{code}`、指数 K `/hsindex/history`；行业/概念归属 `/hszg/*`、`/hslt/primarylist`、`/hslt/sectors/{name}`、`/hslt/sectorslist`；板块资金流（同资金）；全市场快照 | 大盘环境（regime：上行/震荡/下行，用沪深300与中证全指的 `ma_trend` + 宽度 + 波动）；板块相对强弱（成分股快照加权）；个股相对板块强弱 | 板块实时指数是否有直接接口【待 T003 验证】，否则由成分股快照本地合成 |
| 消息 | 公告 `/hsstock/announcement/{code}`（标题/摘要/类型/原文链接，盘后更新）；问董秘 `/hsstock/interactiveqa/{code}`；今日交易提示 `/hitc/jrts`；解禁 `/hscp/jjxs/{code}`、`/hitc/jjxs`；业绩预告/快报（同上）；因子 `recent_event`、`event_impact`（-100~100）、`event_date` | 公告类型 → 规则化利好/利空标签（如减持、问询函、立案调查、回购、增持、业绩预增/预亏），**只基于类型与标题关键词** | **新闻资讯缺口**（第 4.5 节方案 A–F）；盘中公告时效：麦蕊公告盘后更新（缺口，盘中只能用交易所外链）；LLM 不读原文、不作判断 |

**具体策略**：具体策略见 `docs/strategies/`（由策略研究员维护）。本文不列策略清单、规则和阈值。引擎对策略数量没有任何假设；首批上线哪些策略，由研究员提交文档，经 2.5.14 导入并通过 G1–G7 后确定。下表的维度底座是所有策略共用的数据来源，研究员的 `data_needs` 只能引用 `feature_catalog` 中已登记的字段。

> **示例**（只说明一条规则怎样落到底座和 DSL，不是推荐策略）：技术维度的入场规则 `close > ma(close, ma_fast)`，所需特征 `close` 来自日 K（`feature_catalog.source = mairui:/hsstock/history`【待 T003 验证】），`ma_fast` 是参数 schema 中的整数参数。

- 因子总数 77/85 文档不一致【待 T003 验证】；以上因子 ID 均在因子文档出现（已核实），字段是否常为空需 T-B05 实测。

#### 2.5.3 周期与策略自动分类（导入后执行，可覆盖）
- 触发：导入确认、新增自选、某证券持仓由 0 变为 > 0 或清零（T-A02 新增）、每周六重算一次。输出写 `symbol_horizon_assessments`（版本化，带理由）。（v0.2.9 内，T-B46/T-B47 裁定）：`GET /horizon-assessments` 找不到本人、该证券、当前分类器版本的记录，或记录的输入快照早于库中该证券最新日线日期时，同步计算一次并落库（`trigger=on_demand`），不再“只算不存”；配置中重算键 `import_confirm` 对应表中 `trigger=import`（名称不同、含义相同，不改表值）。
- **特征**：流动性（日均成交额、`turnover_20d_avg`、`amihud_20d`）、波动（`volatility_20d`、`intraday_amplitude_20d`、ATR%）、趋势（`ma_trend`、`momentum_60d`）、基本面完整度与质量（`roe_ttm`、`profit_cagr_3y`、`dividend_continuous_years`、财报期数）、情绪活跃度（`limit_up_count_20d`）、**用户自身行为**（该股历史平均持有天数、是否有同日买卖的做T记录、交易频率——来自导入成交）、画像（投资期限、精力、风险承受）。
- **规则化打分**（分类器配置 `horizon_classifier_versions`，不可变）：每个周期 0–100 分，例如：`intraday_t` = 有底仓 × 日内振幅 ≥ 3% × 日成交额 ≥ 2 亿 × 用户精力 ≥ 中 × 历史有做T行为加分；`long` = 基本面完整（≥ 12 期财报）× ROE/分红稳定 × 用户期限 ≥ 长；`swing`、`short` 同理（**以上阈值均为示例**，正式规则与阈值由策略研究员在 `docs/strategies/` 中给出，写入不可变的 `horizon_classifier_versions`）（见 horizon_classifier.md v1）。≥ 60 分的周期列为"适合"，并给出每个周期 2–4 条理由（引用特征值与证据 ID）及不适合的理由。
- 每个"适合"周期下，按策略 `applicability` 与 `fit_dimensions` 匹配列出适用策略（`fit_score` 排序）。
- **画像类规则只提示、不封顶【用户已定 2026-11-02，T-A06，取代问题 37 方案 A】**：画像（`profile.*`）由用户自报、全部选填；分类器 1.2.0（`version_no: 3`）把画像类 `requires` 规则 `SH0`、`SH0B`、`SH0C`、`IT0B`、`IT0C` 都改为 `mode: hint`：**画像未填写时不封顶也不提示**；已填写且不满足时只在 `/horizon-assessments` 的 `hints[]` 中给出提示（如 `experience=novice` 时提示“短线需要盯盘与止损纪律”），**不降低分数、不影响 `suitable`**。用户可以自由为任何证券选择 short 与 intraday_t（实例校验 I3 只给 `warnings`）。非画像规则照旧生效（契约 v0.2.6，T006e 裁定）：hard gates HG1–HG6 判 0 分或封顶 59，记入 `caps[]`，`kind: gate`、`rule_id` 为 `HGn`（判 0 分的 HG1–HG3 记 `cap: 0`）；`IT0`（无底仓）的 `else_score: 0` 是**分数**，不是封顶，不进 `caps[]`，只在 `reasons[]` 中给出反向理由；`LG0`（财报期数不足）、`LG0B`（ROE 缺失）的 `else_cap: 59` 属于数据不足，记入 `caps[]` 时 `kind: data_missing`、`rule_id` 为规则 ID（架构师 T-A07 归类）。`caps[].kind` 不再有 `requires`。**提示与分数相互独立（T006e 裁定 1）**：某周期即使已被 `IT0` 判为 0 分，`experience=novice` 时仍给出 `IT0C` 提示。规则 ID 不是 `reason_code`（同 T-A05）。画像类加分项（`IT3`、`IT5`、`SH7` 等）不变：未填写只是不加分。horizon_classifier.md 由研究员同步（T-A06 报告）。
- **用户覆盖**：分类结果生成 `strategy_instances`（`status=proposed`，**用户确认后才变为 active**，2.5.0），替代原先的 `user_symbol_strategy_settings`；用户修改后系统不再自动改动，只在分类结果变化时提示"系统建议已变化"。

#### 2.5.4 引擎流水线（L2 求值 → L3 候选信号 → 可执行性 → 计划草案）
```
输入：证券 + 用户（画像版本、持仓与可卖数量、现金、计划、约束与禁投名单、风控设置、active 实例）+ 数据快照（含 feature_set_version）
 ① 数据装配：按实例所用模板版本的 required_data，从指标底座读取（只按列名读，不重算）→ data_snapshot（缺失项进 gaps）
 ② 通用闸门 gate_tradability：ST/*ST、停牌、上市不满 30 个交易日、退市整理期、一字涨跌停、低价股（默认 < 2 元，可配置）
    → 命中时，买入方向的候选信号不成立，并记录 gate 结果（卖出方向仍评估，例如持仓股被 ST 仍可产生 reduce/sell）
 ③ 维度评估（RuleEvaluator，唯一的求值器；盘后批和盘中增量调用同一实现）：
    逐条规则求值 → 每维度 {view, score, rules[{rule_id, role, passed, value, threshold, evidence_ids}], veto_reason?}
    veto 规则命中 → 该模板 state = vetoed（只影响本模板，不跨模板）
 ④ 模板结论 = 候选信号（L3 candidate_signals，不可变）：
    {state, proposed_action(+t_leg), score, confidence, stops, support/resistance,
     rule_refs[], evidence[], counter_evidence[], invalidation[], model_refs[](auxiliary), valid_until}
    P1 校验：rule_refs、evidence、counter_evidence、invalidation 缺任一 → 不写入，并记 SIGNAL_NOT_EXPLAINABLE
 ⑤ 风控 RiskHook（RC1–RC6，统一接口，只打标记、只限制数量，不改写候选动作）→ risk_flags[]、quantity_cap
 ⑥ 汇总为候选信号卡 suggestions：维度 × 策略矩阵、consensus（只计数）、divergence[]、优先级（score × 降权权重，只排序）
 ⑦ 可执行性检查（2.5.9 原因码）：对每个方向为 buy/add/reduce/sell 的候选信号逐项检查
    → 有任一原因：写 non_executable_reasons（附 release_condition），信号状态 = blocked
    → 无原因：生成 plan_drafts（数量区间、价格区间、止损止盈、有效期、费用估算、人工判断清单），信号状态 = drafted
    → 前提（P1b）：至少一条 role ∈ {entry, exit, weakening} 且 passed = true 的规则引用（语义见 2.5.14 H⑮）；只有 model_refs 时不生成草案；纯离场策略（H-01 类）由 weakening/exit 命中满足（契约 v0.2.3 §5.2）
 ⑧ 解释：模板解释必有；可选 LLM 改写（只引用证据 ID，经守卫校验，2.7）
 ⑨ 存档与后续：全部不可变；登记模拟跟踪（2.8）；登记原因监控（2.5.9）；按通知节奏推送
```
- 候选信号的 `hold` / `wait` 不进入可执行性检查，也不生成草案，只在卡片上展示。
- **原因解除**：解除监控发现某条原因的解除条件成立 → 该原因 `released` → 若该信号所有原因都已解除且仍在有效期内（未失效、未被取代）→ 回到 ⑦ 重新检查 → 生成草案并通知（`notification_kind = reason_released`）。
- **信号矛盾不合并**：建议卡呈现 **"维度 × 策略" 矩阵**（行：六个维度；列：启用的策略；格：观点 + 分数 + 关键依据），下方并列各策略的动作与止损止盈；顶部只有在所有启用策略动作一致时才显示"各策略一致：持有"，否则显示"**存在分歧（3 个策略：买入 / 等待 / 减仓）**"并列出分歧点。系统**不输出合成后的单一结论**。
- **置信度**：每个策略单独计算 = 0.5×数据完整度 + 0.3×维度一致度（该策略内部各维度观点是否同向）+ 0.2×条件余量（离阈值的标准化距离），映射 high ≥ 0.7 / medium ≥ 0.4 / low；公式随 `engine_policy` 版本记录。各分项、缺失处理和版本存放的精确定义见下方 T-A16 裁定。

#### T-A16 裁定（架构师 2026-11-07）
候选→建议装配口径，并收口 T-B77、T-B78 会碰到的未定义口径。原则：MVP 取最小方案；缺数据返回 null 并记 gap，不填伪值，不抬高置信度；不推翻 T-R15、T-A11–T-A15。
1. **engine_policy 版本**：
   - 唯一来源是 `config/engine_policy.yaml`，登记进 `REFERENCE_FILES`。顶层 `version_no` 为正整数，初始 `1`；其余是内容：`confidence`（第 2 条的权重、分级阈值、余量参数）和 `system_components`（2.5.11A 默认 4 项及各自版本）。
   - `content_sha256` = 去掉 `version_no` 后，按键排序、UTF-8 的 canonical JSON 的 SHA-256。
   - 幂等种子命令写已有表 `engine_policies`，不新增迁移：`version_no` 不存在就插入，`config` = 内容 + `content_sha256`；已存在且哈希相同就不动；哈希不同就拒绝启动并报错，改内容必须先递增 `version_no`。
   - 运行时只读库中 `version_no` 最大的一行；同一次盘后作业全程用同一版本。
   - 落点：引擎产出的建议必填 `suggestions.engine_policy_id`（已有列）；候选信号不加列，把 `{engine_policy_version_no, content_sha256}` 写进它 `snapshot_id` 指向的数据快照。这就是 2.5.11A“系统组件版本随 engine_policy 记录在每条信号上”的实现。
   - 契约 `Suggestion.engine_policy` 为 `{version_no, content_sha256} | null`，只有非引擎产物（如 T-B76 手工合成建议）为 null。
2. **置信度**（每个策略结论单独算）：
   - 数据完整度 D = 本结论 `rule_refs` 中 `passed` 非 null 的条数 ÷ `rule_refs` 总条数（P1 保证分母 > 0）。
   - 维度一致度 A：只看 `dimension_views` 中 `view` 为 bullish 或 bearish 的维度，A = max(看多数, 看空数) ÷ (看多数 + 看空数)。这类维度少于 2 个时 A = null，一个维度谈不上一致。
   - 条件余量 M 先逐条算：
     - 只计 role ∈ {entry, filter, hold, weakening, exit}、`passed` 非 null、`value` 与 `threshold` 都能解析成十进制数的单一比较规则。
     - 尺度 s 依次取：规则声明的 `margin_scale` 参数；左值在 `feature_catalog` 中单位为价格（元）且 ATR14 可得时取 ATR14；阈值非 0 时取 |阈值|。都没有就不计这一条。
     - m = min(1, |value − threshold| ÷ s)，只看离阈值多远，不论通过与否。
     - 布尔、枚举、交叉、复合 and/or 等没有单一数值阈值的规则不计入，既不记 1 也不记 0。
   - M = Σ(w·m) ÷ Σw，w 取卡片 `rule.weight`，没有就为 1；没有可计入的规则时 M = null。
   - 合成 value = 0.5·D + 0.3·A + 0.2·M。A 或 M 为 null 时这一项按 0 计入，不重新归一化：缺项只会压低置信度，不会抬高。value 保留两位小数，再按 high ≥ 0.70、medium ≥ 0.40、其余 low 分级。
   - 透明：契约 `confidence.components` 给出 D、A、M（A、M 可为 null）和逐条余量 `margin_rules[]`，权重写在里面。`LOW_CONFIDENCE` 仍用 value 与用户阈值（默认 0.4）比较。
3. **important_count**：
   - `important` 由差异类型固定决定：`quantity_mismatch`、`missing_in_broker`、`missing_in_ours` 为 true；`cost_differs`、`cash_gap`、`cash_chain_break` 为 false（3.5A 对账表）。`/reconciliation` 的 `items[].important` 同一口径。
   - 取该账户最新一次对账（`created_at` 降序、`id` 降序；日报只取生成时刻之前的那次）。`diff_count` = 其中未被用户忽略（`resolution` 为空）的条目数，`important_count` = 其中 important 的条数。
   - 没有账户或从未对账：`status="not_imported"`、`as_of=null`、两个计数为 0（沿用 §5.3）。
   - 日报与 `/today` 同一口径；非空对账不再返回 503。
4. **change_from_previous**：
   - 基准：同一用户在 `market.trading_calendar` 中严格早于本报告日期的最近开市日的最新完成版（ready/partial）日报。同日新 revision 也和这份比，不和同日旧 revision 比。
   - 比较四项：各策略 `(strategy_key, action, t_leg)` 集合（`actions`）；各策略置信度等级（`confidence_level`，从两边建议读取）；`executability_status`（`executability`）；`max_risk_level`。价格、涨跌幅、证据、文字、`suggestion_id` 不比。
   - 今有昨无为 `new`。两边都有时，任一项不同为 `changed`，并在 `change_fields` 列出变化项，一边有建议另一边没有算 `actions` 变化；都相同为 `unchanged`。
   - 昨有今无时追加一行 `removed`：`suggestion_id`、`suggestion`、`max_risk_level` 为 null，`close`、`change_pct` 取当日值或 null，三组文字为空数组。`removed` 行不计入列表的 `stock_count`。
   - 没有基准（首份日报、前一开市日没有完成版、前一开市日不在日历覆盖范围内）：所有行 `change_from_previous=null`、`change_fields=[]`，不出 `removed` 行，日报 `gaps` 记 `{key:"stocks.change_from_previous", reason:"no_source"}`。不返回 503，也不把全部标成 `new`。
5. **扫出并一并定掉的口径**（T-B76、T-B77、T-B78）：
   - 日报范围：`account_id` 按 T-A12 默认账户规则；`stocks` = 该账户持仓 ∪ 本人自选，持仓按权重降序在前，其余按代码升序。
   - 日报证据：`evidence[]` 汇集各行引用的建议证据，id 改写为 `{security_code}:{原 id}`，行内 `evidence_ids` 同步改写，保证文档内唯一。
   - 日报行文字：`highlights` = 当前建议各策略 `reasons` 去重后前 3 条；`invalidation` = 各策略 `invalidation` 去重；`next_watch` 在 MVP 恒为 `[]`，列入 T-B79。没有建议的行三项都是 `[]`，不写模板套话。
   - `SuggestionSummary`：`actions[]` 增加 `lifecycle`，`simulating` 时前端标“模拟中”（T-A14 第 4 条）；`top_score` = 各策略 `score` 的最大非 null 值，全为 null 时为 null。
   - `/today.focus`：从本人全部行中取（不受 `/terminal` 300 行截断影响）持仓 ∪ 重点关注，持仓按 `weight_pct` 降序在前，重点关注按加入时间；最多 50 条，超出时 `more=true`。终端被截断时不再 503。
   - `/terminal`、`/today` 不再用 503 表示“未接线”：没有记录就是空集合，有记录按契约 §7.3 既有定义聚合。保留的 503 只有 T-A12 的 `CALENDAR_NOT_COVERED`。另有一处配置缺失时的 503：`aggregates.calendar` 的 `market_clock` 在交易日找不到 market_rules 分段时返回 `503 MAINTENANCE`（details.issue=`market_rule_segment_missing`），属规则配置缺口，不是“未接线”，与产品有无无关（T-A149 核对 be/T-B133=7d161ad）。
   - 日历覆盖起点之前没有前一开市日：`change_from_previous` 按第 4 条处理；补 2025 年末前序开市日由研究员按 T-R16 同一受审流程补，不阻塞 MVP。
   - T-B78 增加断言：置信度可由 `components` 按本条公式重算；`engine_policy` 非空且与库中版本一致；`important_count` 与 `/reconciliation` 重算一致；跨日 `change_from_previous` 的 new/changed/unchanged/removed 与无基准 null 各一例；“模拟中”标记可见。
6. **需用户决定的产品问题**：无。权重 0.5/0.3/0.2 与分级阈值沿用本节已定公式，本裁定只补定义。
7. **后端**：T-B76 续接 P1 结论装配（置信度、`engine_policy`）与跨日比较；T-B77 去掉上述 503，按第 3 条与第 5 条聚合；T-B78 加第 5 条断言。全部不需要迁移。

#### 2.5.5 输出结构（`suggestions` 的 JSON 视图；**字段定义以 api-contract §5.2 `Suggestion` 为准**，本节只是示例，取值均为**虚构**）
```json
{
  "id": "sg_01J…", "security_code": "600000.SH", "name": "示例银行", "created_at": "2026-11-02T10:31:00+08:00",
  "status": "active", "origin": "intraday_event", "data_status": "fresh", "snapshot_id": "sn_…", "feature_set_version": "fs_3",
  "candidate_signal_ids": ["cs_…"],
  "executability": {"status": "blocked", "reason_ids": ["nr_…"], "executable_signal_ids": [], "blocked_signal_ids": ["cs_…"]},
  "plan_draft_ids": [],
  "horizon_assessment": {"suitable": ["swing","long"], "user_overridden": false},
  "consensus": {"status": "divergent", "actions": {"buy": 1, "wait": 1, "reduce": 1}},
  "strategies": [{
    "strategy_version_id": "sv_…", "strategy_key": "demo_trend", "strategy_name": "示例趋势策略", "version_no": 2,
    "instance_id": "si_…", "horizon": "swing", "lifecycle": "published",
    "state": "entry_ok", "action": "buy", "t_leg": null, "candidate_signal_id": "cs_…",
    "score": 78, "confidence": {"level": "medium", "value": 0.62},
    "rule_refs": [{"rule_id": "T1", "snippet_version": 1, "role": "entry", "passed": true, "evidence_ids": ["E3"]}], "model_refs": [],
    "priority_weight": "0.85", "priority_downweighted": true,
    "dimension_views": [{"dimension": "technical", "view": "bullish", "score": 83,
        "rules": [{"rule_id": "T1", "role": "entry", "passed": true, "value": "up", "threshold": "up", "evidence_ids": ["E3"]}]}],
    "stops": {"stop_loss": "9.50", "take_profit": "11.20", "time_stop_days": 20},
    "invalidation": [{"text": "收盘价连续 2 日低于 20 日均线", "expr": "close < ma20 for 2 days", "evidence_ids": ["E7"]}],
    "reasons": [{"text": "MA20 上穿 MA60", "expr": null, "evidence_ids": ["E4"]}],
    "counter_evidence": [{"text": "所属行业 20 日资金净流出", "expr": null, "evidence_ids": ["E9"]}],
    "valid_until": "2026-11-09T15:00:00+08:00"
  }],
  "dimension_matrix": [{"dimension": "technical", "divergent": false, "cells": [
      {"strategy_key": "demo_trend", "strategy_version_id": "sv_…", "view": "bullish", "score": 83,
       "key_evidence_ids": ["E3"], "rules_passed": 1, "rules_total": 1}]}],
  "divergence": [{"dimensions": ["fundamental","technical"], "summary": "估值分位偏高 vs 趋势向上",
                  "resolving_info": [{"description": "下一期季报 profit_yoy 是否转正", "subscribable": true}]}],
  "risk_flags": [{"control": "position_cap", "level": "warning", "message": "该股占总资产比例超过上限", "gated_actions": ["add"], "quantity_cap": null, "evidence_ids": ["E11"]}],
  "evidence": [{"id": "E3", "key": "factor.ma_trend", "value": "up", "unit": null, "data_as_of": "2026-10-30", "fetched_at": "…", "provider": "mairui", "endpoint": "/factor/momentum/{code}", "epistemic_type": "fact"}],
  "explanation": {"source": "template", "text": "…", "llm_call_id": null},
  "supersedes_id": "sg_…"
}
```
- **命名规则（与契约一致）**：规则结果一律 `passed`；引用证据一律 `evidence_ids: string[]`（禁止单数 `evidence_id`）；证据对象主键是 `id`，在所属文档内唯一，全局用 `(snapshot_id, id)` 定位；`reasons` / `counter_evidence` / `invalidation` 都是 `TextWithEvidence{text, expr|null, evidence_ids}`。
- **分数刻度**：引擎内部和策略规格中的阈值、权重用 0–1 小数；对外（API、存储、页面）所有名为 `score` 的字段都是 **0–100 整数**（四舍五入），观点为 `unknown` 时为 `null`；`confidence.value` 保持 0–1、两位小数。
- **矩阵单元格**由服务端按 `strategies[].dimension_views` 派生（`key_evidence_ids` ≤ 3 个，取该维度中 role ∈ {entry, filter, hold} 且 passed = true 的规则引用的前 3 个证据；`rules_passed/rules_total` 同样只统计这三种角色，2.5.14 H⑮），契约测试检查两者一致；行级 `divergent=true` 当且仅当该维度单元格中同时存在 `bullish` 与 `bearish`（`neutral`/`unknown` 不参与，契约 v0.2.3）。
- **纯离场策略（exit-only，H-01 类；契约 v0.2.3 §5.2）**：只对持有中证券求值，未持有时不出现在结论、矩阵与 consensus 中；单元格 `rules_passed/rules_total` 为 0/0、`score` 为 null，另给 `exit_hits/exit_total`（只统计 role ∈ {weakening, exit}），前端显示“离场 x/y”；`view`：任一命中 → bearish，全部未命中 → neutral，全部无法求值 → unknown；计入行级 `divergent` 与 consensus（与 catalog 第 4 节第 4 点“冲突时并列展示”一致）。state 只取 hold_ok/weakening/exit_signal/insufficient_data，action 只取 hold/reduce/sell。
- **consensus.status**（契约 v0.2.3）：0 个策略 none；1 个 single；≥ 2 个且 `(action, t_leg)` 全部相同 unanimous；否则 divergent。
- **可执行性** `executability.status`：至少一个候选信号没有未解除原因 → `executable`；全部候选信号都被阻断 → `blocked`；没有候选信号（全部 hold/wait）→ `not_applicable`。

#### 2.5.6 六项风控（逐项开关，`risk_control_settings`：系统默认 → 用户覆盖）
| ID | 风控 | 规则（默认参数） | 数据 | 输出 |
|---|---|---|---|---|
| RC1 | 每笔建议带止损/止盈价 | 由策略 `stops` 公式计算（ATR14、前低、突破位、基本面失效价）；限制在当日/次日涨跌停价范围内；中长线默认价格止损 −20% 可关 | 日 K、`/hsstock/stopprice/history` | 每个策略结论的 `stops`（`stop_loss`/`take_profit`/`time_stop_days`）；盘中触发 → 失效事件 |
| RC2 | 单只仓位上限提醒 | 单只市值 ≤ 总资产 20%（画像可调）；`add/buy` 会使其超限 → gated | 持仓、实时价 | risk_flag + 可加仓上限数量 |
| RC3 | 总仓位按大盘环境建议 | regime 上行 60–90%、震荡 40–60%、下行 0–30%（可调）；当前总仓位超出区间 → 提示 | 指数 K、宽度、持仓 | 账户级 risk_flag（日报与终端顶部） |
| RC4 | 板块集中度预警 | 单一申万一级行业 ≤ 40%、单一概念 ≤ 50% | 行业归属 `/hszg/*`、持仓 | risk_flag |
| RC5 | 连续亏损与回撤预警 | 已平仓交易连续亏损 ≥ 3 笔；账户净值自高点回撤 ≥ 10%；某策略模拟跟踪连续 5 次失败 | 成交、持仓估值、`suggestion_tracking` | 账户/策略级 risk_flag + 通知 |
| RC6 | 违反自己计划时提醒 | 导入/录入的成交与有效计划不符：方向相反、数量超计划、失效条件触发后仍持有、未设止损即买入、在"等待"计划期间买入 | 计划、成交（导入后即时检查） | 通知 + 复盘"执行"维度素材 |

- **T-A15 裁定（架构师 2026-11-07）RC3、RC4 的门控动作集合（MVP）**：与 RC2 同构，只限制会加大暴露的动作，不改写候选动作。
  - **RC3 总仓位**：
    - 门控动作为 `{buy, add}`：总仓位已经不低于当前 regime 区间的上限时，记原因码 `REGIME_MISMATCH`，`detail.cause="total_exposure_at_cap"`，解除条件是总仓位低于上限。
    - 没到上限但这一笔会超限：不 gated，给 `quantity_cap`，等于 `(上限 × 总资产 − 现有持仓市值) ÷ 价格`，按手数规则向下取整。取整后不到起买量时才 gated。
    - 总仓位低于区间下限：只出账户级提示，绝不因此生成或建议买入。
    - regime 缺失时不门控，记数据缺口（partial），不算干净通过。
  - **RC4 集中度**：
    - 门控动作为 `{buy, add}`，只针对属于超限申万一级行业或概念的证券，记 `SECTOR_EXPOSURE_EXCEEDED`，`detail` 写明行业或概念、当前占比和上限。
    - 未超限但这一笔会超限：按同样的方法给 `quantity_cap`。
    - 其他证券不受影响。“未分类”行业不触发。行业或概念数据缺失时，同样按缺口处理。
  - **两项都不拦的动作**：`sell`、`reduce`、`hold`、`wait`。做T 的两条腿 MVP 不门控，列入 T-B79。
  - **6.1 原因码的落点**：超出上限按上面写入不可执行原因（gated）；其余情况只是 §2.5.6 的提示或预警 risk_flag。
  - 契约 `gated_actions` 取值：RC3、RC4 为 `["buy", "add"]`。
- **T-A33 裁定（架构师 2026-11-08）RC5/RC6 判定口径**：模拟失败、已平仓一笔、暂停期起算与再触发、期满恢复、RC6 累计数量与计划边界的可实现口径以契约 §7.11.3 “T-A33 裁定”为准。
  - **产品项已定（用户 2026-11-08 选 B，T-A36）**：模拟失败按策略自身周期取跟踪期（T-A37 修正：`intraday_t` → T+1，`short` → 5 日，`swing`/`long` → 20 日；RC5 仅为早期预警，暂停可由用户恢复，策略终评由 §2.5.7 跟踪统计与 §2.8.2 健康度/管理员复审负责），只算本人建议；周期不清楚的观测跳过并记 gap。配置键 `rc5_loss_streak_drawdown.sim_fail_horizon_by_horizon`（取代原 `sim_fail_horizon_days`），细则见契约 §7.11.3 T-A33 第 2 点。

#### 2.5.7 模拟跟踪反馈与自动降权
> 本节公式保留；权重与"健康 / 观察 / 退役"状态合并为**一个机制**，以 2.8.2 为准。`strategy_priority_weights` 改为 `user_strategy_weights` 与 `strategy_health_daily`。

- 统计（`strategy_tracking_stats`，每日盘后汇总）：按 策略版本 × 周期 × 范围（本人 / 全站匿名汇总）× 跟踪期（1/5/20 日）：样本数 n、胜率、平均收益、平均超额、盈亏比、最大连续亏损、最近 20 次表现。
- **自动降权（开关：`user_prefs.auto_downweight`，默认开）**：
  - 平滑胜率 `w̃ = (wins + α·0.5) / (n + α)`，α = 10（小样本向 50% 收缩）；
  - 超额项 `e = tanh(avg_excess_pct / s)`，s = 5（%）；
  - 原始权重 `raw = 1 + β·(w̃ − 0.5)·2 + γ·e`，β = 0.6、γ = 0.4；
  - 最终 `weight = clamp(raw, 0.3, 1.2)`；n < 20 时 `weight = 1`（样本不足不调整）；
  - 每日重算，写 `user_strategy_weights`（含所用参数与样本区间，可回看）。
- **作用范围**：只影响**推荐优先级**（终端列表排序、日报中的展示顺序、默认展开哪个策略）和"表现差"标签（weight < 0.6），**不改变任何策略的动作、分数与止损**；用户可在策略页看到"已因近期表现降权 0.55，原因：近 30 次胜率 38%、平均超额 −2.1%"，并可一键关闭或手动停用该策略。

#### 2.5.8 L3：候选信号、不可执行原因、计划草案与确认
**候选信号 `candidate_signals`**（不可变正文 + 头表状态）
- 正文包括：实例与模板版本、证券、`state`、`proposed_action`、`t_leg`、分数、置信度、`stops`、`rule_refs[]`、`evidence[]`、`counter_evidence[]`、`invalidation[]`、`model_refs[]`（`role=auxiliary`）、`gate_results`、`risk_flags`、`snapshot_id`、`valid_until`（计划有效期，按周期默认：做T 为当日 14:50，短线为下一交易日收盘，波段为 5 个交易日，中长线为 20 个交易日，可在模板中配置）。
- 状态：
  - 初始 `open`；可执行性检查发现生效原因时进入 `blocked`，不会自动进入 `drafted`；
  - `blocked` 在原因解除后进入 `released`，重新检查后可能再次进入 `blocked`；
  - `open`、`released`、`drafted` 只有在用户拟草案（POST /plan-drafts，cause=user）时才进入或保持 `drafted`；判定顺序见契约 §7.7（v0.2.9 #30、#37）；
  - `drafted` 经用户确认后为 `confirmed`；
  - 终止状态：`dismissed`（用户）、`expired`、`invalidated`（失效条件触发）、`superseded`（同实例、同证券出现更新的信号）。
- 状态变化写入 `candidate_signal_events`（只追加）。
- **冷却**：同一模板加同一证券在 N 个交易日内（默认 3 个，可配置）不重复产生同向信号，只更新已有信号的证据，以免虚增样本。

**计划草案 `plan_drafts`**（系统拟定，不可变）
- **数量**按以下几项取最小值，再向下取整到交易单位（主板、创业板 100 股；科创板 ≥ 200 股后按 1 股递增【规则以交易所为准】）：
  - 可用现金（扣除费用缓冲）/ 参考价；
  - 单只上限剩余额度；
  - 策略预算剩余额度；
  - 单笔最大亏损 / (参考价 − 止损价)；
  - 沪深主板与创业板风险警示股票（科创板不适用；T006b 已核实沪 4.4.10、深 4.5.4）：当日累计买入上限 50 万股减去当日已知的已买入数量（`market_rules.yaml` `risk_warning.daily_buy_cap_shares`，2.13）。G-01 已阻断 ST 的买入方向，此项通常不触发，作为规则模块的防御性校验保留。
- **数量区间**为 [上述结果的 50%，100%]；卖出方向的上限为可卖数量（T+1）。
- **整手校验（契约 v0.2.9 #14）**：`qty_range.lot` 为买入递增单位（主板、创业板、ETF 100；科创板 1），`qty_range.min` 不低于起买量（科创板 200）；用户确认时按草案的 `market_rule_version_id` 校验：买入/加仓的数量不低于起买量且符合递增单位；卖出/减仓的数量不超过可卖数量，不足一手的零股只能连同全部余量一次卖出【以交易所规则为准，研究员核对】。不满足时返回 400，偏离确认不能绕过。
- **多个信号合成一份草案（契约 v0.2.9 #13）**：只允许同一用户、同一证券、同一动作（有 T 腿时 T 腿也相同）的信号；方向相反的信号由 `STRATEGY_CONFLICT` 阻断；来自多个实例时草案不归属单一实例；不做跨策略合成结论（P4）。
- **价格区间**：参考价 ± 模板滑点参数，限制在涨跌停价范围内。
- **其他内容**：止损、止盈、时间止损；最大亏损金额及其占总资产比例；费用估算（优先用用户导入成交反推的真实费率，否则用默认费率并标注 `estimate`）；用户上下文快照（持仓、可卖数量、成本、现金、行业暴露）；`risk_flags`；**人工判断清单** `judgment_checklist[]`。清单为固定问题加模板问题，例如"是否了解该股近期公告？""这笔投入是否会影响生活资金？""如果触发止损，你会执行吗？"。
- **草案状态**：`pending` → `confirmed` / `discarded` / `expired` / `stale`。持仓、现金或信号状态变化会使草案变为 `stale`，需要重新生成。
- **用户确认**：必须回答清单中的必答项，勾选风险确认；可以修改数量和价格（超出区间时记录偏离并二次确认）。确认后创建 `action_plans` 和 `plan_versions` v1（`origin=plan_draft`、`plan_draft_id`、`candidate_signal_ids`）。计划条件满足时只提醒"您的计划条件已满足"，**不下单**。

#### 2.5.9 不可执行原因与解除条件
**`non_executable_reasons` 的结构**：
- 字段：`code`、`description`、`evidence[]`（证据 ID 与当时的取值）、`epistemic_type`、`detected_at`、`snapshot_id`。
- `release_condition`：`{kind: expr|time|event|user_action, expr?, at?, event?, action?, check_on[], human_text, machine_checkable: bool}`。
- 状态：`active` → `released` / `obsolete`（所属信号已终止）。

**监控**：解除监控按 `check_on` 建立索引：
- `tick`（盘中每轮，含行情触发规则翻转的情况；契约 `check_on` 枚举不单列 `quote_flip`）
- `import` / `cash_update` / `holding_change`
- `daily_close`
- `schedule`（到点触发）
- `user_action`
- `plan_change`（计划进入终止状态或被修改）

解除时写入 `release_evidence` 和 `released_at`。不可机器判断的条件（`machine_checkable=false`）只能由用户手动标记"已解除"，并记录操作人。

| code | 含义 | 解除条件（默认） | 检查时机 |
|---|---|---|---|
| `DATA_STALE` | 关键数据超过刷新间隔 ×2 未更新 | `data_status == 'fresh'` | tick |
| `KEY_DATA_MISSING` | 必需字段缺失 | 该字段在新快照中非空 | tick / daily_close |
| `LOW_CONFIDENCE` | 置信度低于用户阈值（默认 0.4） | 重评后 `confidence >= 阈值` | tick / daily_close |
| `NON_TRADING_TIME` | 非交易时段（盘后信号） | 下一交易日 09:30（`time`） | schedule |
| `SUSPENDED` | 停牌 | 复牌：行情恢复成交（`event: security.resumed`） | tick / daily_close |
| `LIMIT_LOCKED` | 一字涨停买不进，或一字跌停卖不出 | 涨停时 `price < limit_up_price`（打开涨停），跌停时同理 | tick |
| `ST_OR_DELISTING` | ST、*ST 或退市整理（只阻断买入方向） | 摘帽事件（`event`）；退市整理期不可解除 | daily_close |
| `NEW_LISTING` | 上市不满 N 个交易日（只阻断买入方向） | `listed_days >= N` | daily_close |
| `INSUFFICIENT_CASH` | 可用现金不足一个交易单位 | `available_cash >= required_cash` | cash_update / import |
| `T1_NOT_SELLABLE` | 可卖数量不足（T+1） | 下一交易日 09:30，或 `sellable_qty >= 1 lot` | schedule / holding_change |
| `NO_POSITION` | 减仓、卖出或做T 时没有持仓 | `holding_qty > 0` | holding_change / import |
| `POSITION_CAP_REACHED` | 单只仓位达到上限（RC2） | `position_pct < cap` | tick / holding_change |
| `STRATEGY_BUDGET_EXHAUSTED` | 该策略实例的预算已用完 | `strategy_used < budget` | holding_change |
| `SECTOR_EXPOSURE_EXCEEDED` | 行业暴露超限（RC4） | `sector_pct < cap` | holding_change / tick |
| `REGIME_MISMATCH` | 大盘环境不符合模板适用条件，或总仓位已达到环境上限（RC3） | regime 变为适用值（带 confirm_days 防抖），或总仓位 < 上限 | daily_close |
| `SAME_DIRECTION_PLAN_EXISTS` | 已有同向的有效计划 | 该计划进入终止状态 | plan_change |
| `CONFLICTS_CONFIRMED_PLAN` | 与已确认的计划方向相反 | 用户修改或关闭该计划（`user_action`） | user_action |
| `BLOCKLISTED` | 在用户禁投名单中 | 用户将其移出名单 | user_action |
| `COOLING_OFF` | 冷静期（例如止损后 N 个交易日，或用户设置） | `now >= cooling_until` | schedule |
| `LOSS_STREAK_PAUSE` | 连续亏损或回撤触发暂停（RC5） | 用户确认恢复，或暂停期满 | user_action / schedule |
| `STRATEGY_CONFLICT` | 本人启用的其他策略对同一证券给出相反方向的候选信号（按 P4 并列展示，不自动拟定草案） | 用户选择采用某一方（`user_action`），或冲突消失（重评后方向一致） | user_action / tick |
| `USER_MUTED` | 用户手动屏蔽该证券或策略 | 取消屏蔽，或到达 `mute_until` | user_action / schedule |

- 原因码表由 `GET /meta/enums` 下发；新增原因码需同时定义默认解除条件（CI 校验）。
- 同一信号可以有多条原因，全部解除后才重新检查。界面展示格式为"不可执行：可用资金不足（解除条件：可用资金 ≥ 约 1 万元；导入或更新资金后自动重评）"。

#### 2.5.10 共享指标底座（一个口径）
- **唯一产出者**：所有派生列只能由 `app/features/pipeline.py` 产出。盘中建议、盘后日报、模拟跟踪的入场价判定、复盘回看都**按列名读取**，不得各自重算。插件（`FeaturePlugin`）也只能向底座写列。
- **`feature_catalog`**：每列记录 `feature_key`、维度、来源（麦蕊接口/因子、本地派生、补充源）、单位、频率、复权口径、`warmup_bars`、可得时点 `available_at`、核实状态（`verified_doc / verified_live / pending / gap`）、`epistemic_type`。**这张表就是规则 DSL 的字段白名单**，也是 L1 卡片"数据需求"的取值来源。
- **存储**（详见第 3A 节）：
  - 日频 `market.feature_bars_daily`：每只证券每日一行，常用列为类型化列，其余放 jsonb。按年存为 Timescale hypertable 并压缩。宽表还是"窄表 + jsonb"，由 T-B05 实测后定。
  - 盘中 1 分钟特征放 Redis 环形缓存（每只证券保留当日数据），收盘后落库。
- **版本**：`feature_set_version` 随派生公式变化而递增；`data_snapshots` 会记录该版本。

#### 2.5.11 通用闸门、风控接口与内置候选
- **`gate_tradability`**：所有模板自动挂载，规则为 veto 角色，只阻断买入方向。检查项包括：
  - ST / *ST（由证券名称和风险警示标记识别）；
  - 停牌；
  - 上市不满 30 个交易日；
  - 退市整理期；
  - 一字涨停（开盘即涨停且全日未打开）；
  - 低价股（默认 < 2 元）。
  阈值可配置。**结果落点（T-A02，2.5.14 H⑯）**：前五项都有对应原因码（`ST_OR_DELISTING`、`SUSPENDED`、`NEW_LISTING`、`LIMIT_LOCKED`），写入 `gate_results` 并由 2.5.9 产出可解除的不可执行原因，不把模板 state 改为 `vetoed`；只有低价股作为 veto 使 state = `vetoed`。
- **`regime` 插件**：用指数趋势、市场宽度和情绪周期（6 阶段）产出 `market_regime` 列，带 `confirm_days` 防抖（默认 2 天）。RC3 与各模板都引用这一列。ADX 仓位上限只作参考展示。
- **`RiskHook` 接口**：
  ```python
  class RiskHook(Protocol):
      control: RiskControl            # RC1–RC6
      def evaluate(self, ctx: RiskContext) -> list[RiskFlag]
      # RiskFlag = {control, level, message, gated_actions[], quantity_cap|None, evidence_ids[]}
  ```
  RiskHook 只打标记、只限制数量（`quantity_cap` 进入草案的数量计算），不改写候选动作。RC5 中按 VaR / EWMA 分级的部分后置。
- **候选策略**：哪些策略先只作为 L1 卡片展示、哪些进入 L2，具体策略见 `docs/strategies/`（由策略研究员维护）。引擎只负责把 `completeness` 不同的卡片区分展示。

#### 2.5.11A 首批 P0 策略与引擎接口覆盖核对（【编排者默认，用户可否决】，第 9 节 C(1)–C(5)、C(8)）
P0 = **G-01、G-02、H-01、N-01、T-01、S-01、W-01、W-02、L-01**（9 项，见 `docs/strategies/catalog.md` 第 2 节；本文只核对引擎能否承载，不改策略内容）。四个周期都有覆盖：做T（T-01，先只做盘后统计）、短线（S-01）、波段（W-01、W-02）、中长线（L-01）；G-01、G-02、H-01、N-01 是跨周期的系统组件。资金面和情绪面在 P0 中只作辅助（W-01 的资金辅助条件、G-02 的情绪周期）。

**系统组件的自动挂载（新增配置 `system_components`）**：原来只有 `gate_tradability` 自动挂载（2.5.11）。改为 `engine_policy.system_components` 列表，默认值：

| 组件 | 挂到哪里 | 角色 | 作用范围 |
|---|---|---|---|
| `gate_tradability`（G-01） | 所有模板 | veto | 只阻断买入方向 |
| `veto_risk_announcement`（N-01） | 所有带买入动作的模板；对已持有证券作为 counter | veto / counter | 阻断买入；持仓只加反证，不直接触发卖出 |
| `ctx_market_regime`（G-02） | 不挂规则，产出 `f.market_regime` 供 RC3 与模板引用 | 上下文 | — |
| `hold_risk_monitor`（H-01） | **每只持仓**一个系统实例：`strategy_instances.origin=system`、`status=active`、`horizon=swing`（TB-A48），用户可暂停单只或全部 | exit / weakening | 只产生 reduce/sell 候选，从不产生 buy/add |

H-01 是"周期分类只推荐、不自动启用"（问题 15）的**唯一例外**，因为它只做风险提示方向。系统组件的版本随 `engine_policy` 版本记录在每条信号上（版本编号、存放与落点见 2.5.4 后的 T-A16 第 1 条）。

TB-A48 裁定（H-01 多周期口径，详见 `docs/reviews/TB-A48-horizon-ruling.md`）：H-01 系统实例挂载周期 = `swing`（`attach_system` 及未来一切挂载调用方传 `horizon="swing"`；卡片 `horizons` 保持四值、不为此出 v3；已存实例不回溯改写）。多周期版本（`horizons` 长度 > 1，含 H-01 v1/v2）在 RC5 回退链第二级不可解析：结论缺 horizon 的观测保持跳过 + gap `sim_fail_horizon_unknown`，不得回填 swing、不得取数组首元素。

**逐项覆盖与缺口**

| ID | 运行方式 | 引擎是否已覆盖 | 缺口 → 处理（任务） |
|---|---|---|---|
| G-01 `gate_tradability` | 系统闸门，日线盘后 + 盘中快照 | 基本覆盖（2.5.11） | ① 新增特征 `f.list_days`（上市天数）；② 伪停牌交叉校验：日线 `sf=1` 且同日快照有成交 → `suspect`（T-B05a）；③ ST/退市整理状态的数据来源【待 T003】 → T-B43 |
| G-02 `ctx_market_regime` | 盘后计算，产出 `f.market_regime ∈ {uptrend, range, downtrend}` | 部分（regime 插件，2.5.11） | ① 指数日线接口未实测【待 T003】；② **市场宽度每日落库**（`f.market_breadth`：上涨家数占比等，由全市场快照收盘后计算），历史值需按限流分批回算；③ 情绪周期 6 阶段依赖涨停股池（约 30 天历史），积累前只输出 3 态 → T-B43 |
| H-01 `hold_risk_monitor` | 系统实例，日线盘后 + 盘中快照 | 部分 | ① 新增 ctx 字段 `ctx.cost_price`（我方重建的摊薄成本）、`ctx.position_weight`、`ctx.sector_weight`；② `origin=system` 实例与默认挂载（上表）；③ `atr(n)` 已有 → T-B42 |
| N-01 `veto_risk_announcement` | 盘后，次一交易日开盘生效（2.12.2） | 部分 | ① 特征 `f.ann_risk_count_10d`（近 10 个交易日风险公告数）；② 公告标题关键词表，版本化存入 `event_definitions`；③ 公告接口未实测【待 T003】；④ **数据缺失时**：买入方向草案被 `KEY_DATA_MISSING` 阻断，`missing=["f.ann_risk_count_10d"]`，解除条件 `kind=expr`：该字段在新快照中非空 **且** 公告数据源的 `feature_catalog.status = verified_live`；卖出方向不受影响 → T-B42、T-B43 |
| T-01 `t_vwap_revert` | **只做盘后统计**（C(5)） | 部分 | ① 盘中特征 `f.vwap_intraday`、`f.vwap_dev`、`f.intraday_sigma`（由快照成交额/成交量或 1 分钟 K 计算，单位与口径【待 T003】）；② 时间修饰 `for N bars`、时间 ctx `ctx.now_hhmm`；③ `t_leg` 已有；④ 1 分钟 Pro 未实测。**盘后统计模式**：模板 `scan.mode=post_close_stats`，盘后用当天 1 分钟数据重放规则，只写统计（触发次数、回补率、扣费后单腿结果，均为 `Stat`，标"模拟"），**不产生候选信号、草案或通知**。开放盘中的条件：T-B05 实测快照/1 分钟延迟满足 `stale_threshold_s`，且用户确认 → T-B42、T-B43 |
| S-01 `st_pullback_ma` | 日线盘后 | 基本覆盖（`ma`、`pct_change`、`rank_pct`） | 行业内排名分支需要分组截面函数 `rank_pct_in(x, group_key)` 和行业归属特征 `f.sw_l1`（申万一级，来源【待 T003】）→ T-B42、T-B43 |
| W-01 `sw_ma_trend_pullback` | 日线盘后 | 部分 | ① `ctx.highest_close_since_entry`（跟踪止盈）；② `max2(a,b)`；③ `for p.x days`（N 取参数）；④ 特征请求 `f.ind_rs20`、`f.main_net_20d`、`f.np_yoy_latest`、`f.ann_risk_count_10d`【待 T003】→ T-B42、T-B43 |
| W-02 `sw_breakout` | 日线盘后 | 部分 | 布林带宽及其自身 120 日分位：新增 `std(x,n)`、`ts_pct_rank(x,n)`，或登记派生特征 `f.boll_bw20`、`f.boll_bw20_pct120`（两种都支持，常用的登记为派生特征以便缓存）→ T-B42 |
| L-01 `lt_value` | 筛选型，**每月**首个交易日盘后 | 部分 | ① 调度 `scan.schedule=monthly_first_trading_day`；② 行业内分位 `rank_pct_in` 或派生特征（如 `f.pe_ttm_ind_pct`）；③ 筛选的单行业上限 `screen.per_group_cap`；④ 因子历史值是否按时点计算【待 T003】；⑤ **v0.2.9 内，架构师裁定（L-01 研究口径）**：研究与回测改为按 `plrq` 时点自算（口径见 2.12.1“财务按时点自算”；特征键见 `feature_spec.md` §7A），麦蕊历史因子只作对照；**P0 不受影响**；线上切换条件见 `feature_spec.md` **§7C** → T-B42、T-B43、T-B55 |

- **S-03**（`st_strong_momo`，高风险）：随附为模板，`risk_level: high`，默认不启用、不被分类器推荐（C(2)）；手动启用无需确认，开关旁固定展示风险说明（T006e）。
- **北交所**：V1 不扫描（`boards.bse=false`），持仓仍可导入和展示（C(8)）。
- **N-03**（新闻舆情）：无数据源，保持 L1 卡片、不可运行（C(8)）。

#### 2.5.12 参考资料与策略文档的归属
- 调研文档 [`docs/strategy-references.md`](./strategy-references.md)（T002）是本章**引擎结构**的依据之一，与本文输出协议冲突的地方如何处理见 2.11。
- **策略内容**（卡片、规则、阈值、验证方法、新的调研结论落到具体策略）全部写在 `docs/strategies/`，由策略研究员维护，本文不再收录。新增策略一律先以 L1 卡片进入，满足 G1–G7 后才能晋级。
- 只有当调研结论影响**引擎**（新的规则角色、DSL 函数、特征类型、门禁项、输出字段）时，才由架构师修改本章和 2.5.14。

#### 2.5.13 策略代码接口、注册与生命周期（综合用户 KHunter 式建议、编排者建议与 T002 调研）
```python
class BaseStrategy(ABC):                      # 公共基类：元数据 + 参数 schema + 特征依赖
    meta: StrategyMeta                        # key, name, horizons, dimensions[{dimension, role}], card_key
    params_schema: ParamsSchema               # 字段含 type/default/min/max/step/说明（G4）
    def required_features(self, params) -> set[FeatureKey]: ...   # 必须都在 feature_catalog 中（G2）
    def calculate_indicators(self) -> list[FeatureSpec]: ...
        # 只"声明或派生"特征，由 features/pipeline 统一计算，并注册进 feature_catalog；
        # 不允许私有数据通道或自行取数（保证只有一个口径）
class ScreenerStrategy(BaseStrategy):         # 选股：在 universe 截面上筛选、排序
    def select_stocks(self, frame: FeatureFrame, params) -> ScreenResult: ...
        # ScreenResult = 入选证券 + 每只的 rule_refs/evidence + 排序分；不产生动作
class TimingStrategy(BaseStrategy):           # 择时：对单只证券产出候选信号
    def generate_signals(self, frame: FeatureFrame, ctx: SignalContext, params) -> list[TemplateResult]: ...
        # TemplateResult 见调研 §3.4.3；必须带 rule_refs/evidence/counter_evidence/invalidation（P1）
class RuleTemplateStrategy(ScreenerStrategy, TimingStrategy):
    # 通用实现：读取不可变的 strategy_versions.config（DSL 规则），由唯一的 RuleEvaluator 求值。
    # 研究员导入的内置模板和所有用户派生版本都是它的实例 → 与代码策略共用同一接口、注册表和输出协议
```
- **注册表是显式的**：内置代码策略（极少，例如需要形态插件的）必须在 `app/strategy/registry.py` 中显式登记，且须经代码评审。**在目录中放入文件不会激活任何策略**；也不支持运行时加载第三方代码。
- **YAML 与数据库的分工**：`config/strategies/*.yaml` 是纳入版本控制的默认参数与规则文件，**由导入器根据 `docs/strategies/` 生成**（2.5.14），不手写，启动时以 `key + version` 为幂等键导入数据库，生成**不可变版本**。运行时只读数据库，不读 YAML。
- **生命周期**（`strategy_versions.lifecycle`，数据库状态，跃迁需管理员批准并写审计）：

| 状态 | 含义 | 进入条件 | 对用户的效果 |
|---|---|---|---|
| `draft` | 编辑中（L1 卡片或 L2 草稿） | 新建、派生、LLM 草稿 | 不运行 |
| `simulating` | 模拟中 | 通过 G1–G7 | 产生候选信号并做模拟跟踪；只对管理员和自愿参与的用户显示"模拟中"；**不生成计划草案** |
| `published` | 已发布（健康） | 模拟样本 n ≥ 20 或模拟满 20 个交易日；必需字段全部为 `verified_live`；管理员批准 | 正常运行 |
| `observing` | 观察中 | 健康度下降（2.8.1），自动进入 | 继续运行，带"观察中"标记；用户若开启自动降权则排序后移 |
| `retired` | 已退役 | 管理员确认（**从不自动退役**） | 停止产生新信号；历史可回看 |

#### T-A14 裁定（架构师 2026-11-07）
1. **迁移只保留一个 head**：后端负责，在 T-B80 之前完成。
   - 0021 是暂停中的 T-B61b 的 WIP，不属于主线，移出 `migrations/versions/`，放到 `src/backend/migrations/paused/`（alembic 不加载这个目录）。主线链为 `…→0020→0022`，head 是 0022。
   - T-B61b 恢复时，把 0021 重新编号为 0023，`down_revision="0022"`，验收后再放回 `versions/`。
   - 后端加一个自检：`alembic heads` 只能有一个。
   - 移动之前，先确认没有任何非隔离库的 `alembic_version` 是 0021；如果有，停下来报告编排者，不做降级或改写。
   - 部署一律 `upgrade head`，不再需要手动选 revision。
2. **H-01、W-01 用于 MVP 实测**：
   - 晋级到 `simulating`，这是 2.5.13 中通过 G1–G7 后唯一的去向。
   - 不晋级到 `published`：它要求模拟 n≥20 或满 20 个交易日，并且字段全部 `verified_live`，目前达不到。
   - 不用 `observing`：它只能由 published 版本健康度下降自动进入，不能手动设置。
3. **门禁：G1–G7 全部要通过，一项都不豁免或放宽**（T-R24 Q-02 澄清：指**关卡层面**——七道关卡一道不能整关跳过、不能放宽判定标准；关卡内**已登记的角色型豁免照常有效**，且豁免必须指向登记的裁定条号，如 G1 对纯离场组件免 entry（T-A03、T-R15 ②）、G2 的 `insufficient_data` 不算失败）：
   - G1：W-01 不能有 `to_quantify`（X5 已改用 `_qfq`）。H-01 按 `mount_policy=system_only` 和纯离场规则享受 G1 豁免（T-R15 第 2 条）。
   - G2：所需字段至少 `verified_doc`，不能是 gap。feature 元数据里的 null 不影响 G2（T-A13）。
   - **T-R18 裁定（架构师 2026-11-07）**：① 公开文档依据可写 `verified_doc`（只够到 simulating，见 2.5.13 G2），前提是公式、窗口、可见时点有文档依据；由研究员在 feature_spec 状态列改写并引用 `docs/strategies/T-R18_source_matrix.yaml` 对应行，架构师代提交；后端只按 feature_spec/catalog 导入，不凭报告或口头升级。② `f.close_qfq/f.high_qfq/f.low_qfq`：接受 PIT 限定——按 T-R15 规则 0 只用 as_of 当次取数并存快照，历史回写值不作时点正确依据、不用于回测；单位“元/股”属推断，记入 gaps，待 T-B05 实测。③ `f.list_days`：接受；上市日早于交易日历覆盖起点时值为 null 并记 gap（insufficient_data），不估算。④ `f.np_yoy_latest`：接受，可见时点取 `plrq`；V5f 未结前以首次观测值为准，入库带 observed_at，后续更正作为新观测、不改写旧快照，V5f 随 T-B05 复核。⑤ `f.amount/f.main_net_20d/f.market_regime/f.ind_rs20` 保持 declared，H-01、W-01 的 G2 仍不通过，需实测或补来源，不得放宽 G2。
   - **T-R19 裁定（架构师 2026-11-07）**：① 字段状态的唯一来源是 feature_spec；source_matrix 只是证据，`current_status` 必须与 feature_spec 一致。`f.amount` 的两只股 × 25 根样本只算样本级实测证据：全局状态升为 `verified_doc`（够到 simulating），`verified_live` 要等 T-B05 覆盖更广后再定。研究员同步 feature_spec，并把矩阵 `current_status` 改回与 feature_spec 一致。② `f.main_net_20d`：采纳四字段派生口径（不用内置因子），在 feature_spec 写明公式和符号（买为正、卖为负）；单位和盘后定稿时间由后端按 T-R19 覆盖测试实测前保持 declared。③ 新键 `f.market_regime_idx`：只用 000300.SH 指数日线，`adjust: none`（指数不做除权复权），去掉 F24 宽度；有 hszsdata 文档和日线实测后可记 `verified_doc`。原 `f.market_regime` 保持 declared，不改写。④ H-01、W-01 改用新键须出新版本；W-01 v2 可删 weight 0 的 C1（ind_rs20 反证），写明前后差异，F27 不改。新版本重跑 G1–G6，G7 按 T-A109 条款审核（可在授权范围内由编排者代批）。
   - **T-R20 裁定（架构师 2026-11-07）**：① `applicability.market_regime` 保留为 schema 字段名，v2 卡由 F50 `f.market_regime_idx` 求值成立；条件是卡的 `data_needs`/`required_features` 只列 F50、不再引用 `f.market_regime`，导入器按卡版本取求值源，v1 冻结版不受影响。F50 为 null 时 applicability 判为未知（不默认通过）。② 研究员的 G1–G6 只算文档预检，晋级以后端引擎实跑为准；停牌、涨跌停、rsi14 等 declared 派生键不豁免 G2，由后端实跑如实报告。③ v2 卡在后端更新三个 selfcheck 后导入，走 T-A18 审核流程。
   - **T-R21 裁定（架构师 2026-11-07，依据 docs/strategies/T-R21_derived_features.md）**：① F20、F35、F36、F39、F40、F49 可升 `verified_doc`（只到 simulating），由研究员改 feature_spec：F35/F36 基准价只用 pc；pc 缺失或与 jnfh 自算参考价冲突 → null 并记 gap，jnfh 只作校验（仅纯现金或送转且单位明确时；配股不覆盖）（T-R21 v1.1.14 复核收紧），送转、沪市样本缺口记 gaps 并向下传给 F39/F40；F49 只认 `sf`，行缺失或 sf 为空记 null，G-01 按 `KEY_DATA_MISSING` 不可执行，不得用零量或缺 K 推断停牌。② RSI 全平盘（G=L=0）记 **null**，不取 50；接受“每个 as_of 用完整序列从固定起点重算”，起点取可得序列首日，记入 pit 元数据，回测与实盘同一起点。③ F39/F40 改为四价相等且 v>0 的写法。④ 主板历史 ST 缺口：主数据上线日之前 is_st 为 null 时主板 F35/F36 为 null，接受此缺口（MVP 不做回测，G6 只统计）；ST 比例分段（2026-07-06 前 5%、之后 10%）与 config/market_rules.yaml 已核实记录一致。⑤ F23 关键词表 v1 同意由研究员起草、架构师裁定，排期由编排者定；未落地前 W-01 买入按设计被 `KEY_DATA_MISSING` 阻断。⑥ `config/engine_policy.yaml` 中 `hold_risk_monitor` 的 version_no 改 2（并升顶层 version_no）由后端在 v2 导入时执行，按 T-A16 规则改内容必须升版本。 ⑦ RC3 继续用 F25（含 F24 宽度）且缺失不门控，与卡片 v2 的 F50 并存：RC3 只是账户级提示，F25 为 null 时显示“大盘环境未知”，不改 gated_actions；F25 保持 declared，不影响卡片 G2。
   - **T-A19 裁定（架构师 2026-11-07，G2 缺口收口）**：
     - **F14/F15（MVP 用“当前状态 + 上线日起每日差分”）**：来源只用交易所公开证券列表（T-A04 主数据同步，不调麦蕊）。每个交易日 18:00 拉一次快照，按简称规则（security_master §5）算 `risk_flag`、`listing_status`，与上一快照比较，变化即关闭旧区间、开新区间。必需字段：`security_code, name, board, risk_flag, listing_status, snapshot_date, source, fetched_at`；历史表 `security_risk_flag_history(security_code, risk_flag, listing_status, valid_from, valid_to, source)`。H-01/W-01 只在评估日 d 用到 is_st/is_delisting_period，不回看历史，所以不需要回填。d 日盘后求值取 d 日 18:00 快照，快照没到就等，超时记 null。**失效条件**（任一成立时该值为 null，不猜）：① 评估日早于上线日；② 当日快照缺失或拉取失败（同时告警）；③ 列表格式变化导致解析失败；④ 某条规则需要 d 日之前的 is_st（如回测、跨日窗口），且那天在上线日之前或历史有缺口。主数据同步连续跑满 1 个交易日、历史表有数据后，可记 `verified_doc`；verified_live 等 T-B05。
     - **T-A22 裁定（架构师 2026-11-07，T-B85 官方导出被拒后）**：
       - **来源（MVP）**：交易所官方导出接口返回 `success=false`，不再直连、不补请求头、不换路径；T-B85 的“来源未验证即拒绝”门槛保留。MVP 期间 F14/F15 改用麦蕊证券列表（`/hslt/list`、`/bj/list/all`、`/kc/list/all`）的简称字段，按 security_master §5 同一套前缀规则推出 `risk_flag` 和“简称带‘退’→ `delisting_period`”；快照 `master_snapshots.source = mairui_list`，`field_sources` 记 `mairui_list`。麦蕊仍不得新建证券、不得写 `delisted` 或 `missing_from_list`（4.6.1 不变）；代码不在麦蕊列表中 → F14/F15 为 null。每个交易日 18:00（北京时间）取 1 次，计入麦蕊调用预算，须编排者找用户本人授权后才能实调。
       - **verified_doc 验收**：① 麦蕊文档写明简称字段含义；② 研究员用交易所公开网页（正常浏览，不调接口）人工核对一个交易日：当日全部 ST、*ST、退市整理期证券，加 20 只非风险证券抽样，与推导结果 0 不一致。通过后 F14/F15 可写 verified_doc（只到 simulating）。
       - **回切**：以后研究员找到有文档、可正常下载的官方名单，或用户本人在官网手动导出文件放进 `data/master/inbox/`，按 4.6.1 恢复交易所为权威来源；麦蕊转回对账方，历史区间不改写，只从切换日起开新区间。
       - **PIT 兼容**：不建 T-A19 文中的合并表，沿用 4.6.2 已有的 `security_risk_flag_history`（F14）和 `security_listing_status_history`（F15）两张半开区间表，`snapshot_id` 指向带 `source` 的快照。d 日 F14/F15 = 区间覆盖 d 的那一行，且该行快照 `fetched_at` 不晚于求值时刻（d 日 18:00 快照，d+1 起可见）。首个成功快照日之前没有行 → null，不回填；某日快照失败 → 该日 null 并告警，旧区间不延长也不关闭，下次成功快照再比较。旧表结构不改，不需要新迁移；只在 `master_snapshots.source` 的取值里加 `mairui_list`（文档/代码常量，不动已用迁移）。
     - **F23 验收口径**：词表 v1 由研究员写在 `docs/strategies/` 下（版本号；每个关键词写类别、匹配方式即标题子串，以及排除词如“撤销”“解除”“澄清”）。
       - **verified_doc**：架构师审定词表。离线检查脚本用 V7 已有的 1,000 条标题做正反例，每个关键词至少 2 个正例、1 个反例，全部通过。
       - **verified_live 最少证据**：① 新鲜度：20 只股、连续 5 个交易日，d 日公告在 d+1 北京时间 09:00 前能从麦蕊取到，命中率 ≥ 95%，没达到的那天按 null 处理；② 完整性：从交易所或巨潮公开页面挑至少 10 条已知风险公告（立案调查、退市风险警示等），麦蕊全部能取到，且词表全部命中，漏 0 条；③ 证据存 reports/，不含证书值。
       - 两项都满足后，N-01 才解除 `KEY_DATA_MISSING`。
     - **实测清单**：见 reports/T-A19.md，由编排者拿去找用户一次授权。所有调用都走后端统一出口，不打印证书。
   - **T-R22 裁定（架构师 2026-11-07，F23 词表 v1，依据 docs/strategies/T-R22/README.md）**：① 1,026 条巨潮标题按关键词检索、有选择偏差，**不能替代** T-A19 的 1,000 条通用标题，只作回归快照。替代做法（不调麦蕊、不要求后端补 V7）：研究员从巨潮公开页取**不按关键词筛选**的连续若干交易日全量标题 ≥1,000 条，v1 跑一遍，命中条目逐条人工复核（误报率 ≤5%），未命中条目抽 100 条复核（漏报 0 条为过）；通过后 F23 可写 verified_doc。② N-01 语义不改：问询函、关注函及回复、控股股东或实控人减持（v1 无法判比例，一律计入）照计；只阻断买入/加仓，偏保守可接受；simulating 期间统计否决率记入 G6 观察项，v2 再议降级。③ 接受 v1 已知漏检：含“澄清”整条排除、中介机构名单不全，记为 gap，v2 再细化。④ F23 每日冻结在 D 09:30，故 available_from 只需判所属生效日：交易日 D 的 t < 09:30（含盘前）→ D 09:30 生效；t ≥ 09:30（含盘中、午休、11:30/15:00 边界、盘后）或非交易日 → 次一交易日 09:30 生效；不再为午休/边界记 null。只有 t 与 first_seen_at 都未知时才记 null。状态 verified_live 仍以 T-A19 两项实测为准。
   - G3、G4、G5：按现有规则自动检查。
   - G6：fixtures 必须全部通过（26 例 golden）。120 日历史体检只做统计，原本就只出警告：数据不足 120 日时如实记“未体检/覆盖不足”的警告，并显示在 G7 报告里，不编造统计结果。**T-A17**：重合度 `max_jaccard` 无值（历史不足，或没有可比较的命中集合）时报 `null` 加原因码 `no_history` / `no_comparable_set`（契约 §7.4），G6 记 `warn` 不记 `fail`；fixtures 失败仍是 `fail`。
   - G7（T-A109，2026-11-10）：策略研究员逐条核对卡片原文与规则的对应关系，架构师复核后，编排者依据用户本人授权、以管理员可信交互会话代批，并在决定批注与审计中留证（引用用户原话、日期、授权覆盖的策略卡）。代批前提：缺证据项为 0，且 G1–G6 结论齐备（无 fail；每个 warn 已在 ack_warn_gates）。不放松 G1–G6，不放松「缺证据不得批」。每次代批须引用一条覆盖该卡的用户本人授权；当前书面授权（2026-11-09，原话针对「在 /admin/strategy-gates 页面审批 H-01 和 S-01 两张策略卡（G7）」「第二条你自己去办，别总让我做」）覆盖 H-01、S-01。其他策略卡的代批须有用户本人的新授权，或用户确认将代办改为长期授权（此项未决，由编排者向用户确认）。技术门禁不变：浏览器交互登录会话 + CSRF，`origin=password_login`，每次重输管理员密码；API token、服务账号、脚本一律 `403 HUMAN_SESSION_REQUIRED`；脚本与未获授权的代理不得代填密码或代点批准。解除 HALT、恢复出网等其他须用户本人确认的条款不变。细则见 `docs/reviews/T-A109-g7-delegation.md`。
4. **simulating 在 MVP 中的效果**：
   - 产生候选信号和操作建议，显示“模拟中”标记，不生成计划草案。
   - 只有管理员账户能运行：实测用的隔离测试账户设为管理员（T-B64 前的替代）。
   - 修订 T-B73 裁定：系统挂载允许为管理员账户挂 `simulating` 的 H-01，普通用户仍只挂 published/observing 版本。
5. **任务**：新增 T-B80（见任务表），排在 T-B78 闭环验收之前。G7 按 T-A109 条款由编排者在授权范围内代批，不再默认要求用户亲自点击；细节见上款与 `docs/reviews/T-A109-g7-delegation.md`。

#### 2.5.14 策略研究员文档的对接契约（`docs/strategies/` → 引擎）
> **职责边界（2026-11-01 12:14 起）**：具体策略（知识卡、规则说明、阈值、验证方法、首批策略清单）由**策略研究员**在 `docs/strategies/` 中编写和维护，架构文档**不写也不改**该目录。本章只规定引擎和接口；凡出现具体规则或阈值的地方都标为**示例**，只用来说明接口。
> 本节是研究员文档能被引擎导入的**最低格式要求**。研究员可以在文档里自由写说明文字；导入器只读取下文规定的机器可读块。字段或格式需要调整时，由研究员和架构师一起改本节，不要各自改。

**A. 文件与机器可读块**
- 每张策略卡对应一个 Markdown 文件，文件名不限。文件中有且只有一个以 ` ```yaml strategy-card ` 开头的代码块（卡片，对应 L1），可以有 0–1 个 ` ```yaml strategy-spec ` 代码块（规则规格，对应 L2 草稿），还可以有 0–1 个 ` ```yaml validation ` 代码块（验证方法）。
- 导入器（T-B20d）只解析这三种代码块，正文文字作为卡片的说明（`narrative`）原样保存。解析失败时，导入报告逐项列出错误，**不会部分导入**。
- **幂等键**是 `key + version_no`。版本发布后不可修改；要改内容就递增 `version_no`。导入结果是数据库中的 `strategy_card_versions` 和处于 `draft` 状态的 `strategy_versions`。**导入不等于启用**：之后仍需通过 G1–G7（2.5.0B），再经生命周期流转（2.5.13）。
- 文档中禁止出现真实账户、股东代码、真实持仓或金额；示例证券只能用 `600000.SH` 一类的虚构示例。

**B. 卡片块 `strategy-card`（必填字段与 2.5.0A 一一对应）**

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `key` | string | ✓ | `^[a-z][a-z0-9_]{2,40}$`，全站唯一；建议用周期前缀（`t_`/`st_`/`sw_`/`lt_`） |
| `version_no` | int ≥ 1 | ✓ | 只增 |
| `name` | string ≤ 30 字 | ✓ | |
| `category` | enum | ✓ | `trend / momentum / reversal / breakout / value / quality / dividend / low_vol / event / intraday_t / risk`（T-R15）；需要新增取值时提给架构师 |
| `horizons[]` | enum[] | ✓ | `intraday_t / short / swing / long` |
| `hypothesis` | `{why_it_works: string, falsified_by: string[≥1]}` | ✓ | |
| `dimensions[]` | `{dimension, role: core\|auxiliary\|veto}[]` | ✓ | `dimension` 取六个维度之一 |
| `entry[]` / `counter_evidence[]` / `invalidation[]` / `exit[]` | `{text, expr: string\|null, status: quantified\|to_quantify}[]` | ✓ | 每类至少 1 条，`exit` 中至少一条是止损类；`expr` 非空时必须符合 C 节的 DSL。`origin=system` 的纯离场组件（H-01）豁免 `entry[]`（T-A03） |
| `data_needs[]` | `{feature_key, frequency: 1m\|daily\|quarterly\|event, adjust: none\|qfq\|hfq, available_at}[]` | ✓ | `feature_key` 必须在 `feature_catalog`（2.5.10）中；不在其中的字段先写成 `feature_request`（见 E 节） |
| `epistemic` | `{field_path: fact\|estimate\|hypothesis}` | ✓ | 至少要标出 `hypothesis` 和各条阈值的类型 |
| 选填 | `applicability`、`universe`、`risk_suggestions`（引用 RC1–RC6）、`pitfalls[]`、`fit`（`effort`、`risk_tolerance_min` 1–5、`experience_min`）、`sources[]{title, kind, url_or_ref, source_version, license, license_status}`、`refs[]{ref, title, url}`（研究员文档的出处编号，如 `R12`；API 7.4 `refs`，H⑬）、`validation_summary`（H②）、`risk_level`（H⑫）、`compliance_variants` | | 来源许可证规则见 7.6 |
| 系统字段 | `completeness`、表现记录 | ✗ | **不得在文档中填写**，由系统计算 |

**C. 规则规格块 `strategy-spec`（L2 草稿）**
```yaml
# 示例：只用于说明格式，不是推荐策略，阈值没有含义
key: demo_trend            # 与卡片 key 相同
version_no: 1
kind: rule_template        # 或 code（需要代码策略时只写 code_entry 名称，由后端经评审实现，见 2.5.13）
horizons: [swing]
params_schema:             # D 节格式
  ma_fast: {type: int, default: 20, min: 5, max: 60, step: 1, desc: 快线周期}
rules:                     # role ∈ entry/hold/weakening/exit/filter/veto/counter/invalidation
  - {id: R1, dimension: technical, role: entry, expr: "close > ma(close, ma_fast)", weight: 1, required_features: [close]}
  - {id: R2, dimension: technical, role: counter, expr: "volume_ratio < 0.5", weight: 0, required_features: [volume_ratio]}
  - {id: R3, dimension: technical, role: invalidation, expr: "close < ma(close, ma_fast) for 2 days", weight: 0, required_features: [close]}
action_map: {entry_all_core_pass: buy, held_hold: hold, exit: sell, else: wait}
stops: {stop_loss: "entry - 2 * atr(14)", take_profit: null, time_stop_days: 10}
dimension_view_thresholds: {bullish: 0.67, bearish: 0.33}
applicability: {market_regime: [uptrend, range]}
valid_until: {trading_days: 5}
screen: null               # 选股模板写 {universe, filters[], rank_by, top_n}
```
- **DSL 语法**（G3，引擎唯一求值器 `RuleEvaluator`，详见 T-B20）：
  - 操作数：`feature_catalog` 中的 `feature_key`、`params` 中的参数名、数字或字符串字面量。
  - 运算：比较 `< <= > >= == !=`；布尔 `and or not`；算术 `+ - * /`。
  - 函数白名单：`ma(x,n)`、`ema(x,n)`、`atr(n)`、`highest(x,n)`、`lowest(x,n)`、`ref(x,n)`、`cross_up(a,b)`、`cross_down(a,b)`、`between(x,lo,hi)`、`rank_pct(x)`（截面分位）、`pct_change(x,n)`；新增 `max2`、`min2`、`std`、`ts_pct_rank`、`rank_pct_in` 及 `for N bars` 见 H 节⑤。
  - 时间修饰：`<expr> for N days`、`within N days`。
  - 限制：表达式 ≤ 300 字符，嵌套深度 ≤ 6；不支持变量赋值、循环、属性访问或任何 IO。
  - 白名单只能由架构师和后端修改，研究员可以提出新增函数的需求。
- **硬性要求**（G1）：至少 1 条 `entry`、1 条 `counter`、1 条 `invalidation`，以及至少一种止损（`stops.stop_loss` 或 `time_stop_days`）。做T 模板必须有当日回补规则或时间止损。
- **G1 豁免（T-A03，契约 v0.2.3）**：只由系统挂载（`strategy_instances.origin=system`）、规则只含 weakening/exit（可另有 counter/invalidation）的**纯离场组件**（目前只有 H-01）不要求 `entry` 与止损类规则，但须至少 1 条 exit 或 weakening、1 条 counter、1 条 invalidation；不能被用户实例化为普通模板，`action_map` 不得含 buy/add。导入器按 `origin=system` + 规则角色集合判定，不满足即 `CARD_IMPORT_INVALID`。
- **T-R15 补充裁定（架构师 2026-11-07，对应研究员 reports/T-R15.md 第 11–17 行，一次定完）**：
  0. **价格基准统一，除权不得混用**（取代 W-01 模板 `max2` 止损里原来的混用写法）：
     - 记 `A(d)` 为 d 日累计后复权因子，满足 `close_hfq(d) = close(d) × A(d)`。DSL 求值时，`qfq` 序列的基准日是当次的 `as_of`（T）：`x_qfq(d) = x(d) × A(d) / A(T)`。`A(d)` 只取 T 日已可得的除权信息，回放和回测也一样，不用之后的除权信息。由此 T 日的 `qfq` 值就等于 T 日的不复权值。
     - 持久化的价格一律存不复权值，包括 `plan.entry_price`、`ctx.cost_price`、止损价和目标价。求值器派生出 `plan.entry_price_qfq` 和 `ctx.cost_price_qfq`：`P × A(e) / A(T)`，e 为成交或建仓日；摊薄成本按每笔成交分别折算后再加权。
     - 卡片里价格类表达式两边必须同一口径：`plan.*` 或 `ctx.*` 的不复权价格不能直接和 `*_qfq` 序列比较。导入器按 `feature_catalog.adjust` 做静态口径检查，口径不一致返回 `CARD_IMPORT_INVALID`（`issue=adjust_mismatch`）。
     - 用 `qfq@T` 算出来的止损价和目标价，就是 T 日的不复权价，可以直接展示，也可以写进计划。
     - 除权 golden 由研究员补，每类至少 1 个：W-01 至少 2 个（建仓后 20 日内发生送转和现金分红），H-01 至少 1 个（成本价跨除权日）。期望值按上面的公式算，并写明 `A(d)` 的序列。
  1. **`action_map` 的键**只能取 `entry_all_core_pass`、`held_hold`、`weakening`、`exit`、`else`。H-01 写成 `{exit: sell, weakening: reduce, held_hold: hold, else: hold}`。
     - `insufficient_data` 不是 `action_map` 的键：求值结果为 `insufficient_data` 时不产生候选，建议里显示 `hold`（纯离场组件）或 `wait`（入场策略），并带上缺口原因。
     - 数据缺失时一律不产生 sell 或 reduce。
  2. **category 增加 `risk`**，用于纯离场或风控组件，H-01 改用 `risk`。
     - 卡片加字段 `mount_policy: system_only | user`，默认 `user`。导入器判定 G1 豁免的依据是 `mount_policy=system_only`，且规则只含 weakening/exit（可另有 counter/invalidation）。
     - `origin` 仍然只是实例的属性，不写在卡片里。`system_only` 的策略，用户用 `POST /strategy-instances` 创建会返回 422，错误码 `STRATEGY_SYSTEM_ONLY`，登记到契约。
  3. **单位与指标口径**：
     - `ctx.position_weight` 和 `ctx.sector_weight` 是 0–1 之间的小数。
     - `atr(n)` 用 Wilder 平滑：TR 取 `max(h−l, |h−c₋₁|, |l−c₋₁|)`，用 qfq 序列；第一个值取前 n 个 TR 的简单平均，之后 `ATR_t = (ATR_{t−1}×(n−1) + TR_t)/n`；`warmup_bars = n+1`。
     - 实现之后，研究员补 1 个 golden 在 SMA 与 Wilder 结果不同的区间，用来锁定口径。
  4. **夹具 schema 扩展**：
     - 夹具增加顶层字段 `security: {code, board: main|chinext|star|bse, list_date}`，只用于测试，T-B71 导入器接受这个字段。
     - `feature_catalog` 增加 `f.is_suspended`（日频布尔值，来源是停牌标记 `sf`，P0），停牌场景用它表达。
     - `expect` 可以写 `lot_rule`（可选），写了就要逐项比对。
  5. **`LIMIT_LOCKED` 卖出方向也记这个码**（plan 2.5.9 已经包括“一字跌停卖不出”），`detail.direction` 取 `sell`。H01-FX7 要改成记 `LIMIT_LOCKED`。
  0a. **（T-R16 补）第 0 条推广到所有价格字段**：`plan.*` 和 `ctx.*` 里每个持久化的不复权价格字段，都按第 0 条的公式由求值器派生出 `<键>_qfq`，例如 `plan.stop_loss_qfq`、`plan.breakout_level_qfq`、`ctx.last_price_qfq`，不必逐个申请。
     - 规则里只能使用 `_qfq` 版本。
     - 实现随用到这些字段的卡片一起排期，本 MVP 只实现 H-01 和 W-01 用到的字段。
     - T-R16 的其余待裁定项不属于主线，按预算规则暂缓到 MVP 里程碑之后，期间这些卡一律不可导入：
       - 做T 的 t_leg 配对、ctx 在入场条件中的使用、时刻类参数的类型；
       - DSL 的 null 放行语义；
       - 组合层约束；
       - 新特征 `f.open_qfq`、布林带位置、股息率、封单量。
  6. **（T-R15 第二轮）跟踪止盈**：增加派生键 `ctx.highest_close_since_entry_qfq`，等于 e 日到 T 日之间 `close(d) × A(d) / A(T)` 的最大值，e 是建仓日。W-01 的 X5 改用这个键，恢复成可量化的 golden，至少 1 例跨越除权日。
     - 原来的不复权 `ctx.highest_close_since_entry` 只用于展示，不能出现在规则里，否则按第 0 条报 `adjust_mismatch`。
  7. **`f.is_suspended` 登记**：研究员在 `docs/strategies/feature_spec.md` 新增一个 F 条目，写明：
     - 日频布尔值，来源是停牌标记 `sf`，P0；
     - 证券已退市（`delisted`）或不在列表中（`missing_from_list`）时取 null，与 F14 相同；
     - 分类器读到 null 时按 true 处理。
     - 登记合入之前，校验器的临时放行不算验收通过。
  8. **夹具 expect 的原因明细**：增加可选字段 `expect.reason_details: {<原因码>: {direction: buy|sell}}`。期望原因码里有 `LIMIT_LOCKED` 或 `SUSPENDED` 时，这个字段必填并逐项比对，T-B71 导入器支持这个字段。
  9. **`expect.lot_rule` 的形状**：`{min_buy: int, step: int, odd_lot_sell_all: bool, sell_qty?: int}`，键名和契约中 `issue="lot_rule"` 错误的 `details` 一致（`min_buy`、`step`）。研究员拟定的形状采纳，T-B71 照此实现，不需要再确认。
  10. **停牌时卖出**：`SUSPENDED` 买卖两个方向都适用，`direction=sell`。
      - H/W 的状态照常输出 exit 或 weakening，原因码加上 `SUSPENDED`，信号标为不可执行。
      - 建议页显示“复牌后卖出”，不生成可确认的卖出草案。`LIMIT_LOCKED` 卖出方向同样这样处理。
- **代码策略**：只在 DSL 表达不了时使用。研究员写清楚输入特征、输出特征和伪代码，由后端实现成 `FeaturePlugin`（只产出特征列）或注册的 `TimingStrategy`/`ScreenerStrategy`。输出协议不变（2.5.13）。

**D. 参数 schema 格式**（G4）
- 每个参数写成 `{type: int|float|bool|enum, default, min, max, step, desc, unit?, choices?(enum 时必填)}`。
- `default` 必须在 `[min, max]` 范围内；类型严格，不能用字符串表示数字或布尔值。
- 用户改参只能在 `min..max` 范围内（I4）；越界时生成派生版本。

**E. 验证方法块 `validation`**（G6 的输入，对应内部评估 2.12.4）
| 字段 | 类型 | 说明 |
|---|---|---|
| `methods[]` | enum[] | `fixture`（必选）、`trigger_stats`（必选：触发率与覆盖率）、`tracking_sim`（T+1/5/20 模拟跟踪）；第三阶段（内部评估模块，问题 26 已定）可加 `factor_ic`、`event_study`、`param_robustness` |
| `fixtures[]` | `{id, desc, as_of, features: {feature_key: value}, holding?: {qty, sellable}, expect: {state, action?, rule_ids_passed[], reason_codes[]?}}` | ≥ 6 个，要覆盖：满足、不满足、缺数据、维度分歧、涨跌停或停牌、做T 无底仓（非做T卡可替代，见 H 节⑩）。键只能是 `feature_catalog` 的键（H 节③）。数值全部虚构 |
| `window` | `{lookback_trading_days: int, universe: string}` | 默认 120 日、全 A |
| `horizon_days[]` | int[] | 默认 `[1,5,20]` |
| `metrics[]` | enum[] | `trigger_rate`、`coverage`、`win_rate`、`avg_excess`、`ic`、`car` 等；**每个指标都按 `{value, n, window, small_sample}` 输出**（2.12.3） |
| `min_n` | int | 低于该样本数不下结论，默认 30（2.12.3；H 节⑧） |
| `pass_criteria` | `{metric: string, op: string, value: number}[]` | 作为 G7 审核的参考；是否设为硬门槛由管理员配置 |
| `feature_requests[]` | `{name, desc, source_hint, frequency}` | 引擎目前没有的特征，由后端评估能否接入（数据可得性 **待 T003 验证**） |

**F. 对接流程**：研究员提交文档 → 导入器校验（A–E 节）→ 生成 L1 卡片版本和 L2 草稿 → G1–G6 自动检查 → G7 管理员审核 → 进入 `simulating` → 满足条件后 `published`。每一步的结果会在 `/admin/promotions` 页面和导入报告中回显，研究员据此修改文档。

**G. 与研究员模板 `docs/strategies/_template.md`（v0.1 草案，2026-11-01 12:19 MDT 读取）的对齐**
研究员模板按 vision.md 定稿列出了全部字段，比 B 节的最低要求多；两者不冲突。为了不让研究员返工，导入器按下表**兼容**模板写法。以后如需调整，由双方一起修改本节。

| 项 | 研究员模板写法 | 引擎处理 |
|---|---|---|
| 代码块 | 附录 A 用单个 ` ```yaml ` 块，内含 `rules`、`params`、`validation` 等顶层键 | 两种都接受：①A 节的三个带标签块；②**单个** ` ```yaml strategy-card ` 块，其中的 `rules`/`params`/`stops` 等顶层键视为 spec，`validation` 视为验证块。正式卡片必须带 `strategy-card` 标签，否则导入器跳过（模板附录里的示例不会被误导入） |
| 字段范围 | 24 组字段，用 [L1]/[L2]/[SYS]/[OPT] 分层 | B 节是导入的**最低**要求；其余字段原样存入卡片版本的 `extra`（jsonb）并在详情页展示；标 [SYS] 的字段即使填写也会被忽略 |
| 特征与参数引用 | `f.<feature_key>`、`p.<param>` 前缀 | DSL 接受前缀写法（**推荐**），也接受不带前缀的写法；同名时以前缀为准 |
| 持仓与计划上下文 | `last_price`、`holding_days`、`plan.stop_loss`、`max_r_reached` | 新增只读上下文命名空间 `ctx.*`（`ctx.last_price`、`ctx.holding_days`、`ctx.sellable_qty`、`ctx.max_r_reached`）和 `plan.*`（`plan.stop_loss`、`plan.take_profit`、`plan.entry_price`）；**只允许在 `hold`/`weakening`/`exit` 规则中使用**，并且只在绑定实例与计划时求值；裸写 `last_price` 等按别名处理。**例外（H⑰）**：只依赖时钟、不依赖持仓的 `ctx.now_hhmm` 可用于任何角色的规则 |
| 滚动函数 | `min(x, n)`、`hhv_close60` | `min(x,n)`/`max(x,n)` 是 `lowest`/`highest` 的别名；`hhv_close60` 这类是派生特征，要么写成 `highest(close, 60)`，要么在 `feature_catalog` 登记 |
| 规则行 | `rule_id`（前缀 E/H/W/X/V/C/I/F）、`eval_time`（`daily_close`/`intraday_1m`/`event`）、`status`、`text`、`edge_cases`、`data`、`weight`、`core` | `rule_id` 是 `id` 的别名，前缀按模板约定；`eval_time` **采纳为必填**；`data` 是 `required_features` 的别名；`status: to_quantify` 的规则只进入 L1，不进入可运行模板 |
| 参数 | 列表形式 `{name, type, default, min, max, step, 说明, sensitivity, user_editable}` | 列表形式和 D 节的映射形式都接受；`说明` 是 `desc` 的别名；`user_editable=false` 的参数不允许在 L3 改参（I4） |
| 验证 | 卡内 `validation.type/window/benchmark/cost_model/oos_result/trade_log_ref` 摘要 + 独立的 validation.md | 卡内摘要作为 L1 展示字段保存；`oos_result` 为 `string \| null`（与 API 7.4 `validation_summary.oos_result` 一致，T-A02 统一；原"`{metric, value, n, window}` 对象"的写法作废），未执行就写"未验证"；E 节的验证块仍是 G6 的机器输入。validation.md 是方法说明，不被导入 |
| 卡片级不可运行原因（模板附录 B 第 6 项提问） | `blocked_gates` | **采纳为系统字段**，名称统一为 `gates_missing[]`（API 7.4 节已返回），由系统根据 G1–G7 结果计算，研究员不用填写。它**不进入** 22 个不可执行原因码表（T-A06 前为 23 个）——原因码只描述单个候选信号 |
| 冲突与互斥"优先级" | 只用作展示顺序 | 与 P4 一致，引擎不合并结论 |
| 冲击成本模型 | 研究侧估算 | **进入产品**（H 节⑨，2.13 冲击成本行），`epistemic_type=estimate` |

**H. 与研究员模板 v0.2 / catalog / validation 的对齐结论（2026-11-01，T-A01；回应 `_template.md` 附录 B 第 5、8–14 项）**

| 议题 | 结论（引擎侧，已定） |
|---|---|
| ① 卡片列表项的 `ref` | **采纳**。`entry[]`/`counter_evidence[]`/`invalidation[]`/`exit[]` 的列表项可写 `ref: <rule_id>`，必须指向同一文档 `rules[]` 中**角色相容**的规则（entry→entry，counter_evidence→counter，invalidation→invalidation，exit→exit/hold/weakening）。卡片项省略 `expr` 时导入器从规则复制；两边都写时，去除空白差异后必须完全一致，否则 `CARD_IMPORT_INVALID`（`issue=ref_expr_mismatch`）。`ref` 指向不存在或角色不相容的规则同样报错。 |
| ② `validation_summary` 与 `validation` | **分开**。`validation_summary`（`type, window, benchmark, cost_model, oos_result, trade_log_ref`）是 L1 卡片的**选填展示字段**，概括研究侧离线检验；没做写 `oos_result: "未验证"`。`validation` **只**指 E 节的机器块（G6 的输入）。如果在 `validation` 里出现摘要键，导入器报 `CARD_IMPORT_INVALID`（`issue=summary_key_in_validation`，提示改名为 `validation_summary`）。用户可见范围按方案 A（2.12.4）。 |
| ③ 夹具的特征键 | `fixtures[].features` 的键**只能是 `feature_catalog` 的键**（`f.*`），不能是表达式字符串（如 `"ma(f.close_qfq,20)"`），否则 `CARD_IMPORT_INVALID`（`issue=fixture_key_not_in_catalog`）。需要函数值时，夹具提供 `series: {f.key: [最早…最新]}`（长度 ≥ 该规则的 warmup），由求值器计算；常用的派生值通过 `feature_requests` 登记为命名派生特征。持仓与计划上下文用 `holding`/`ctx`/`plan` 子对象提供（`ctx.*`、`plan.*` 的值）。 |
| ④ 模板状态 `not_triggered`（新增） | 含义：**数据完整、没有否决，但核心入场条件未全部满足**。映射为 `wait`；不生成 `candidate_signals` 行，只记录在评估结果和触发统计中。与 `insufficient_data`（数据缺失）、`vetoed`（否决规则命中）、信号级 `blocked`（不可执行原因）都不同。完整枚举：`entry_ok / not_triggered / hold_ok / weakening / exit_signal / vetoed / insufficient_data`（0A.4、API `strategy_eval_state`）。研究员夹具中暂用 `insufficient_data` 表示"未满足"的，导入时提示改为 `not_triggered`。 |
| ⑤ DSL 新增 | `max2(a,b)`、`min2(a,b)`（两数取大/小；`greatest`/`least` 作为别名；区别于滚动的 `max(x,n)`/`min(x,n)`），因此"ATR 止损与结构止损取高者"可以写成一条规则；`std(x,n)`；`ts_pct_rank(x,n)`（当前值在自身最近 n 根中的分位 0–1）；`rank_pct_in(x, group_key)`（组内截面分位）。`for N days`/`within N days` 的 N 可写整数字面量或 `int` 参数 `p.xxx`（实例化时固定，须在 schema 范围内，上限 250）；日内规则用 `for N bars`/`within N bars`。新增 ctx 字段见 G 节"持仓与计划上下文"行。 |
| ⑥ 涨跌停与市场状态键名 | 统一为：`f.limit_up_price`、`f.limit_down_price`（当日涨跌停价，由 2.13 计算）；`f.is_limit_up_close`、`f.is_limit_down_close`（收盘封板）；`f.limit_locked_up`、`f.limit_locked_down`（全天一字板）。`f.market_regime ∈ {uptrend, range, downtrend}`（与 API 枚举 `market_regime` 一致）。 |
| ⑦ 公告的最早可交易时刻 | 按 2.12.2：取 `max(公告时间戳, first_seen_at)`；盘中 → 下一根 1 分钟 bar，盘后/开盘前 → 下一交易日开盘，只有日期 → 按盘后。麦蕊公告盘后更新，因此实际上一律次日开盘，与研究员"公告一律按盘后"的写法结果相同；与 2.8.1 模拟跟踪入场口径一致。 |
| ⑧ 样本量阈值 | 全站统一（2.12.3）：n < 5 不显示数值；5 ≤ n < 30 标"样本少"（`small_sample=true`）；n ≥ 30 正常。E 节 `min_n` 默认改为 30。降权门槛 n ≥ 20（2.5.7）和 `published` 的模拟样本门槛 n ≥ 20（2.5.13）不是展示阈值，保持不变。 |
| ⑨ 冲击成本 | **进入产品**，只放在"成本与滑点"（卡片 `costs.impact_*`）：按参与率分 5 档的确定性估算（2.13），计划草案（2.5.8）、模拟跟踪（2.8.1）和内部评估共用；`epistemic_type=estimate`，档位为初值待校准。 |
| ⑩ 非做T卡的"无底仓"夹具 | G6 的夹具覆盖要求中"做T 无底仓"一项，对非做T卡可用"持仓可卖数量为 0 时出现卖出信号"替代（研究员附录 B 第 14 项）。G6 其余覆盖要求不放宽。 |
| ⑪ 因子数量 | 文档写 85 个、因子页另有"82 个已上线"的说法（validation.md 第 7 项），以 T003 补测和 T-B05 实测后的 `feature_catalog` 为准；导入器只认 catalog 中的键，所有因子按日频处理，盘中只用 T−1 值。 |
| ⑫ `risk_level` | 卡片选填字段 `risk_level: normal \| high`（默认 normal）；`high` 默认不启用、不被分类器推荐（问题 11）。手动启用**不需要确认、不弹窗**；启用开关旁固定展示风险说明（T006e）：“高风险策略：短线情绪类规则，波动和回撤可能很大，规则可能很快失效。仅供研究参考，盈亏自负。”【编排者默认文案，可改】 |

**H（续）. T006a 对齐结论（2026-11-01，T-A02；回应 `_template.md` 附录 B 第 15–20 项）**

| 议题 | 结论（引擎侧，已定） |
|---|---|
| ⑬ 卡片级 `refs[]` 与列表项 `ref` | 两者**不同名不同义，均保留**：卡片级选填 `refs[]` 是出处列表 `{ref, title, url}`（`ref` 为研究员文档的出处编号，如 `R12`；API 7.4 已返回）；列表项的 `ref: <rule_id>`（H①）指向 `rules[]` 中的规则。导入器按位置区分：顶层 `refs` → 出处；`entry[]`/`counter_evidence[]`/`invalidation[]`/`exit[]` 元素内的 `ref` → 规则。不改名，以免研究员文档与契约返工。 |
| ⑭ `oos_result` 类型 | `string \| null`，以契约为准（G 节已改）；未做写 `"未验证"`。需要结构化数值的离线结果放在研究侧报告，不进卡片。 |
| ⑮ `RuleRef.passed` 与 `rule_ids_passed` 语义 | **`passed = 该规则表达式求值为真`**，对所有角色一致：entry/filter/hold 为真 = 条件满足；veto/counter/invalidation/weakening/exit 为真 = **命中**。数据缺失无法求值 → `passed = null`（契约 v0.2.2 放宽为 `boolean \| null`），不计入 `rule_ids_passed`；未持有时 `ctx.*`/`plan.*` 规则**不求值、不出现在 `rule_refs` 中**。`rule_ids_passed` = `passed == true` 的规则 ID，按 `rules[]` 原顺序。下游：计划草案的 P1b 门槛"至少一条 passed 的规则"指 **role ∈ {entry, exit, weakening} 且 passed = true**；`DimensionCell.rules_passed/rules_total` 只统计 role ∈ {entry, filter, hold} 的规则（命中的 veto/counter 另在 `counter_evidence` 与 `gate_results` 中显示）。纯离场策略的单元格另用 `exit_hits/exit_total`（契约 v0.2.3）。所有 role 的 `RuleRef.dimension` 必填、非空（系统组件：G-01 → technical，G-02 → sector_market，N-01 → news）。 |
| ⑯ 一字涨停夹具与 G-01 | **采纳研究员写法**：夹具只评估本模板、不挂系统组件，一字涨停时期望 `{state: entry_ok, …, reason_codes: [LIMIT_LOCKED]}`。运行时 G-01 也挂载：G-01 中**有对应原因码**的检查项（停牌 → `SUSPENDED`、一字涨停 → `LIMIT_LOCKED`、ST/*ST/退市整理 → `ST_OR_DELISTING`、上市不满 30 日 → `NEW_LISTING`）结果写入 `gate_results`，并由可执行性检查（2.5.9）产出原因码（可解除、可监控），**不把模板 state 改为 `vetoed`**；只有**无对应原因码**的检查项（低价股 < 2 元）作为 veto 使 state = `vetoed`。这样一字涨停打开后 `LIMIT_LOCKED` 可按解除条件自动重评。G-01 自身的行为另由系统组件测试覆盖（T-T 组）。 |
| ⑰ `ctx.now_hhmm` 用于入场规则 | **允许**（G 节 ctx 限制的唯一例外）：`ctx.now_hhmm`（北京时间 `HH:MM` 字符串，可与字面量比较）只依赖时钟、不依赖持仓，可用于任何角色的规则。求值取值：盘中 = 本轮扫描时刻；`post_close_stats` 重放 = 被重放 bar 的结束时刻；日线盘后规则中使用 → 导入时报 `CARD_IMPORT_INVALID`（`issue=intraday_ctx_in_daily_rule`）。T-01 目前为盘后统计，不阻塞。 |
| ⑱ ST/*ST 涨跌幅 | 已核实，2026-07-06 起 10%、此前 5%（2.11、2.13、`market_rules.yaml`）。风险警示股票的 50 万股买入上限（主板与创业板，科创板不适用）与限价申报约束（仅沪市）见 2.13（T006b 已核实）。 |

研究员侧原待回答的问题 19（分红是否计入摊薄成本）与 C(7) T+1 hold 阈值均已于 2026-11-01 定（第 9 节）。问题 37（novice 限制 short）已被问题 44 取代【用户已定 2026-11-02】：`SH0C`/`IT0C` 只在用户自报 novice 时提示，不封顶（2.5.3、6.1）。


### 2.6 通知渠道（站内为主，可插拔）
- **MVP 主渠道：站内提醒**——通知中心 + 未读数 + SSE 实时推送（`GET /api/v1/stream`，断线 15 秒轮询 `/notifications/unread-count`）。
- **可插拔接口**：
```python
class NotificationChannel(Protocol):
    key: str                                   # in_app / email / wecom_app / wecom_bot / mp_template / serverchan
    def validate_binding(self, binding: ChannelBinding) -> None: ...
    async def send(self, msg: RenderedMessage, binding: ChannelBinding) -> DeliveryResult  # 返回 ok / retryable / permanent
    def render(self, n: Notification, detail_level: Literal["full","summary","ping"]) -> RenderedMessage
```
  `notifications`（每用户一条通知）→ 按 `notification_preferences` 选择渠道 → `notification_deliveries`（每渠道一次投递：`queued/sent/failed/retrying/dropped`，`attempts`、`next_retry_at`、`error`）。重试：指数退避 3 次；permanent 错误（如绑定失效）自动停用绑定并站内提醒。
- **频控与免打扰**：每用户每渠道每分钟 / 每小时上限（配置，默认外部渠道 5/分钟、30/小时）；同一股票同一类事件 10 分钟内合并（站内语义见契约 §7.11.4「通知合并与推送节奏」，T-A28）；免打扰时段内外部渠道只累积，结束后发摘要（站内照常）；严重级别 `important`（如失效条件触发）可设置"免打扰期间仍发送"。
- **外部渠道内容最小化**：默认 `detail_level = summary`（"您关注的 1 只股票触发失效条件，请登录查看"），不在第三方渠道发送持仓数量、成本、金额。

**微信类渠道评估（2026-11-01 网页核实；未实测）**

| 方案 | 绑定流程 | 限制【已核实-官方文档】 | 成本 | 合规 / 风险 | 结论 |
|---|---|---|---|---|---|
| 企业微信 自建应用消息 | 用户加入我方企业微信（个人微信可通过"微信插件"关注企业后接收）→ 绑定 userid | 每应用每天发送人次 = 账号上限 × 200；未认证企业 100 人上限；每成员每分钟 ≤ 30、每小时 ≤ 1000，超出丢弃；2022-06 起需配置可信 IP | 企业微信认证 ¥300/次/年（中大型另计）【已核实】 | 需企业主体；用户需成为"企业成员"，对公众用户体验较重 | **推荐作为第二渠道**（10–100 人的封闭小组最合适） |
| 企业微信 群机器人 webhook | 用户在内部群添加机器人，把 webhook 填进设置 | 每机器人 20 条/分钟（errcode 45009）；text ≤ 2048 字节、markdown ≤ 4096 字节；**含个人微信用户的外部群不支持机器人** | 免费 | webhook key 泄露即可冒发，必须加密存储；群内他人可见内容 | 仅作管理员运维告警 |
| 公众号（服务号）模板消息 / 订阅通知 | 用户关注服务号并授权 → openid 绑定 | 模板消息需**认证服务号**（非个人主体），不得用于营销，默认 10 万/日、最多 25 个模板；订阅通知需用户订阅，一次性订阅一次只能发一条，长期订阅仅限政务民生/医疗等类目 | 微信认证 ¥300/年【已核实】 | 需公司主体；金融/证券类目能否开通【待核实】 | 有公司主体后再评估 |
| Server酱（Turbo） | 用户扫码绑定其 SendKey，填入设置 | 免费 5 条/日；会员 1000 次/日、50/分钟 | 会员 ¥8/月、¥39/年（促销价）【已核实-官网】 | **第三方中转**：内容在其服务器保留 1 天（免费）/ 3 天（会员）；依赖微信模板消息，可能停服；开源自建替代 WeCom酱 | 只允许 `ping` 级内容（不含股票与金额），默认不开放 |

**建议**：MVP 只做站内 + 可选邮件；第二步（有企业主体后）上 企业微信自建应用（10–100 人封闭小组足够）；服务号等公司主体与类目确认后再做；Server酱 不作为默认渠道。见第 9 节问题。

### 2.7 LLM 网关（可配置供应商；只写解释，不做决定）
- **定位**：用户有大量模型 API 额度，用于"分析段落与建议理由"的文字生成；**所有动作/分数/置信度由规则引擎决定**，LLM 不可改变。
- **接口（供应商无关）**：
```python
class LLMProvider(Protocol):
    key: str                                   # openai_compatible / anthropic / ...（适配器）
    async def complete(self, req: LLMRequest) -> LLMResponse   # messages, model, max_tokens, temperature, response_format({type: json_object})（DeepSeek 只支持 json_object，schema 由本地 pydantic 校验，2.7.1）, thinking, user_id, timeout
class LLMGateway:
    async def run(self, task: str, evidence: EvidencePack, *, user_id: int | None) -> ExplanationResult
    # task → 查 llm_task_routes（主模型、备用模型链、超时、重试、预算）→ 渲染 prompt_template（版本）→ 调用 → 校验 → 记录 llm_calls
```
- **配置来源**（v2026-11-01 修订）：默认值在 `config/llm.yaml`（6.1）；管理端运行时覆盖存数据库（`llm_task_routes`、`llm_models` 价目等，标“可热调”的键）。`llm_providers` 记录名称、类型、`base_url`、`api_key_source`（`env`/`db`）。**DeepSeek 的 key 只来自环境变量 `DEEPSEEK_API_KEY`**（`api_key_source=env`），不入库、不经接口写入、任何接口和日志都不返回 key 或其片段（契约 v0.2.1 §7.9 只返回 `api_key_set`）；以后接入的其他供应商若在后台录入 key，才用 AES-256-GCM 加密入库（`api_key_source=db`）。`env` 来源供应商的 `base_url` 不可热调，只能改 YAML 并重启，且必须是 https 且主机在白名单内（防止管理员误配把 key 发往他处）。`llm_models`（模型名、上下文长度、最大输出、每百万 tokens 的缓存命中/未命中输入价与输出价、空闲时段折扣）、`llm_task_routes`（任务 → 主模型 + 备用链、单次超时（默认 30 秒）、重试（默认 2 次，指数退避加抖动，只对网络错误/超时/429/500/503，见 2.7.2）、温度、最大输出、日预算）。保存配置时可“测试连接”。
- **任务类型**：`suggestion_rationale`（建议理由）、`daily_report_stock`（日报个股段落）、`daily_report_summary`（日报总览）、`strategy_divergence`（分歧说明）、`announcement_title_digest`（只基于公告标题的要点，不读原文）。
- **提示词模板版本化**：`prompt_templates(task, version, system_text, user_template, output_schema, status draft/active/retired)`；激活新版本不影响历史记录；每条生成记录 `prompt_template_id + version`。
- **输入/输出契约**：输入 = `EvidencePack{evidence[{id, key, value, unit, as_of, source}], action, score, confidence, reasons, counter_evidence, invalidation}`（不含用户名、股东代码、账户号；持仓只给比例与成本价）；输出 JSON `{paragraphs:[{text, cites: string[]}]}`；校验见 0A.4（数字/引用/禁用词），校验失败计入 `llm_calls.validation_status` 并回退模板。
- **记录与成本**：`llm_calls` 记录 task、provider、model、prompt 版本、输入/输出 tokens、耗时、状态、估算成本（tokens × 管理员填写单价）、关联对象（suggestion_id / report_id）；后台按日/任务/模型汇总，超日预算自动降级到模板。
- **合规与数据**：只发送去标识化的结构化证据；DeepSeek 的条款要点与我方义务见 2.7.1、7.3；境外供应商涉及个人信息出境，接入前另行评估（问题列表）；输出同样过禁用词校验。

- **守卫（0B P1a）**：LLM 输出中的每个数字、每个断言都必须引用证据 `id`，且数值与证据一致；不允许出现动作词、目标价或收益承诺；不允许引入证据之外的事实。任一项不通过就丢弃 LLM 输出、回退模板，并记录到 `llm_calls.validation_status`。`model_refs` 的输出只能写成"辅助参考"。
- **LLM 策略草稿（第三阶段，T-B39）**：LLM 根据用户描述只输出 JSON（卡片字段、DSL、参数 schema），自动跑 G1–G6，最多修正 3 轮；结果永远只是 `draft`，必须经过 G7 人工审核（2.5.0）。

#### 2.7.1 DeepSeek 接入事实（2026-11-01 按官方文档核实；T-B25 以此为准）
官方文档会更新，T-B25 开工和每次升级前重新核对本表；与文档不一致时以文档为准并回改本表。未在官方文档中找到的事项标【待核实】，不得自行假设。

| 项 | 核实结果 | 来源 |
|---|---|---|
| 协议与 base_url | OpenAI 兼容格式：`https://api.deepseek.com`（对话接口 `POST /chat/completions`）；另有 Anthropic 兼容格式 `https://api.deepseek.com/anthropic`（我们不用） | [首次调用 API](https://api-docs.deepseek.com/zh-cn/)、[模型 & 价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing) |
| 认证头 | HTTP Bearer：`Authorization: Bearer <key>`；官方示例从环境变量 `DEEPSEEK_API_KEY` 读取 key | [DeepSeek API（Authentication）](https://api-docs.deepseek.com/zh-cn/api/deepseek-api)、[首次调用 API](https://api-docs.deepseek.com/zh-cn/) |
| key 格式/前缀 | **官方文档未说明 key 的格式、长度或前缀**。因此配置校验只检查“非空”（去掉首尾空白后长度 > 0），**不做任何前缀/长度正则**；key 的有效性只靠“测试连接”（401 即无效）判断 | 同上（文档仅写“创建 API key”） |
| key 保管 | 服务协议 2.4：API key 是调用凭证，须妥善保管、不得共享或公开、不得暴露在浏览器或其他客户端代码中；泄露造成的费用由开发者承担 | [开放平台服务协议](https://cdn.deepseek.com/policies/zh-CN/deepseek-open-platform-terms-of-service.html)（更新 2026-04-22，生效 2026-04-29） |
| 当前模型名 | `deepseek-flash`（现为 DeepSeek-V4.1-Flash-1017）、`deepseek-v4-pro`（DeepSeek-V4-Pro-0813）。旧名 `deepseek-v4-flash`、`deepseek-v4-flash-vision-exp` 仍可调用，但由 Flash 新模型提供并按 Flash 计费——**配置中只写 `deepseek-flash` / `deepseek-v4-pro`** | [模型 & 价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing) |
| 上下文与最大输出 | 上下文长度 1M；输出长度最大 384K（价目表中两个模型共用同一单元格） | 同上 |
| 思考模式 | 两个模型都支持思考/非思考，**默认开启思考**（effort 默认 `high`）；OpenAI 格式用 `{"thinking": {"type": "enabled"\|"disabled"}}`（SDK 放 `extra_body`）。思考模式下 `temperature`、`presence_penalty`、`frequency_penalty` 不生效；思维链在 `reasoning_content` 返回。思维链 tokens 是否计入输出计费，文档未单独说明【待核实，以账单为准】 | [思考模式](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode) |
| JSON 输出 | `response_format: {"type": "json_object"}`（文档未提供 `json_schema` 类型）；system 或 user prompt 必须含 “json” 字样并给出输出样例；须合理设置 `max_tokens` 防截断；无法识别为 JSON 时，非 JSON 内容被替换为空格，`content` 可能只有空格而 `finish_reason` 仍为 `stop` → 需兜底（重试） | [JSON Output](https://api-docs.deepseek.com/zh-cn/guides/json_mode) |
| 工具调用 | 两个模型都支持 Tool Calls（思考与非思考模式均可）；思考模式下带 `tools` 的请求，后续请求必须完整回传 `reasoning_content`，否则返回 400；`strict` 模式（Beta）需改用 `https://api.deepseek.com/beta`。V1 的解释任务**不用工具调用**（T-B39 策略草稿如需再评估） | [Tool Calls](https://api-docs.deepseek.com/zh-cn/guides/tool_calls)、[思考模式](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode) |
| 价格（元 / 百万 tokens） | `deepseek-flash`：输入缓存命中 0.04、缓存未命中 2、输出 8（高峰）；空闲时段 0.02 / 1 / 4。`deepseek-v4-pro`：0.30 / 9.0 / 27.0（高峰）；空闲时段 0.15 / 4.5 / 13.5。费用 = token 数 × 单价，从充值或赠送余额扣减（优先扣赠送余额）；DeepSeek 保留调价权利 | [模型 & 价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing) |
| 空闲时段折扣 | 空闲时段价格为高峰价的一半。高峰 = 北京时间周一至周五（不含法定节假日）9:00–12:00、14:00–18:00；其余时段（含周末、法定节假日全天）为空闲时段 | 同上 |
| 价目不一致提示 | 官网营销页 [deepseek.com/platform](https://www.deepseek.com/platform/) 在核实时展示的价格与“预计 7 月中旬采用峰谷定价”的说法，与文档价目页不一致（例如 Flash 输出价、Pro 各项价格）。**以文档价目页为准**，实际单价【待核实，以首月账单对账】 | 两页对比 |
| 上下文缓存 | 默认对所有用户开启、无需改代码；只有完整匹配已落盘的前缀单元才算命中；`usage.prompt_cache_hit_tokens` / `usage.prompt_cache_miss_tokens` 给出命中情况；“尽力而为”，不保证命中；缓存不再使用后一般几小时到几天自动清空 | [上下文硬盘缓存](https://api-docs.deepseek.com/zh-cn/guides/kv_cache) |
| 限速 | **按账号计并发**（与 key 无关）：`deepseek-flash` 2500、`deepseek-v4-pro` 500；超过并发返回 HTTP 429；可提工单免费扩容。文档没有 RPM/TPM 配额，也没有说明 429 是否带 `Retry-After` 头【待核实】 | [限速与隔离](https://api-docs.deepseek.com/zh-cn/quick_start/rate_limit) |
| `user_id` 参数 | 可传字符串 `user_id`（建议只用字母、数字、`_`、`-`，UTF-8 ≤ 512 字节），用于内容安全隔离、KVCache 隔离（隐私管理）和调度隔离；文档明确要求**不要在 `user_id` 中包含用户隐私信息** | 同上 |
| 长连接保活 | 等待期间：非流式持续返回空行，流式返回 `: keep-alive` 注释；10 分钟后仍未开始推理则服务器关闭连接 | 同上 |
| 错误码 | 400 格式错误、401 认证失败（key 错误）、402 余额不足、422 参数错误、429 速率/并发达上限、500 服务器故障（“等待后重试”）、503 服务器繁忙（“稍后重试”） | [错误码](https://api-docs.deepseek.com/zh-cn/quick_start/error_codes) |
| 数据：我方角色 | 服务协议 3.5：开发者是数据处理者/个人信息处理者，须向终端用户告知个人信息处理规则，并就“委托我们（深度求索）处理个人信息”取得同意或其他合法性基础；3.6 须采取访问控制、加密等措施；3.4 须对输入输出做内容审查；3.7 须按《人工智能生成合成内容标识办法》对生成文本做标识；4.1 输入不得侵犯他人隐私和个人信息权益；5.5 终端用户的个人信息不在 DeepSeek 隐私政策范围内 | [开放平台服务协议](https://cdn.deepseek.com/policies/zh-CN/deepseek-open-platform-terms-of-service.html) |
| 数据：训练与存储地 | 隐私政策（更新/生效 2026-02-10，适用范围含 API）：在加密和去标识化前提下，可能把输入及对应输出用于模型训练和服务优化，可在“产品内”关闭“数据用于优化体验”退出；建议不要输入个人敏感信息。境内运营中收集的个人信息存储在中华人民共和国境内，目前不传输至境外。**API 调用是否也受该训练条款约束、API 账号在哪里关闭**【待核实，向 api-service@deepseek.com 书面确认】 | [隐私政策](https://cdn.deepseek.com/policies/zh-CN/deepseek-privacy-policy.html) |
| 数据：保留期 | 隐私政策只写“为提供服务所必需的期间”，网络日志按《网络安全法》不少于 6 个月；**API 请求/响应内容的具体保留期限未说明**【待核实】。是否提供单独的数据处理协议（DPA）【待核实】 | 同上 |
| 适用法律 | 中华人民共和国大陆地区法律；争议由深度求索住所地法院管辖 | [开放平台服务协议](https://cdn.deepseek.com/policies/zh-CN/deepseek-open-platform-terms-of-service.html) 第 9 条 |

#### 2.7.2 网关实现要求（T-B25 按此实现）
- **key**：进程启动时读取环境变量 `DEEPSEEK_API_KEY`；只检查非空，为空则 DeepSeek 供应商标记 `unconfigured`，所有任务回落模板，`/health/ready` 不因此失败（LLM 不是就绪依赖）。key 只注入运行 LLM 网关的 `api` 与 `worker` 容器，不注入 `ingest`、前端、nginx、数据库。不写入数据库、YAML、日志、异常信息、`llm_calls.request_body`；HTTP 客户端日志关闭请求头输出，`Authorization` 一律脱敏为 `***`。
- **请求**：`POST {base_url}/chat/completions`，`model` 取自 `config/llm.yaml`；解释类任务**显式关闭思考模式**（`thinking: {type: "disabled"}`，因为默认开启；关闭后 `temperature` 才生效，延迟和输出 tokens 更可控）◇；`response_format: {type: "json_object"}`，system prompt 含 “json” 字样和输出样例；`max_tokens` 按任务配置；`stream: false`。
- **user_id**：传 `"u_" + HMAC-SHA256(服务端密钥, 用户 UUID)` 的前 16 位十六进制（不可逆、不含任何个人信息）；同一证书内复用的个股事实段落传固定值 `"shared"`（不含证书或用户标识）。
- **缓存友好**：消息顺序固定为“版本化 system 模板 → 任务说明与输出样例 → 证据 JSON”，可变内容放最后，提高前缀命中；`llm_calls` 记录 `prompt_cache_hit_tokens`、`prompt_cache_miss_tokens`。
- **发送前守卫**：渲染后的 prompt 先跑 7.4A 的 S5、S6、S8、S9 规则和用户名/邮箱精确匹配；任一命中 → 不发送、记 `validation_status=blocked_pii`、回落模板并告警。只允许发送 `EvidencePack` 中的结构化证据（证券代码、指标、规则结果、持仓比例与成本价），**禁止**发送股东代码、资金账号/客户号、用户名、姓名、邮箱、成交编号/委托编号、持仓数量与金额、交割单原文。
- **超时**：连接超时 5 秒；单次读超时 = 任务 `timeout_s`（默认 30 秒，日报总览 60 秒）；单次调用总截止时间（含重试与退避）90 秒 ◇。响应体解析前去掉保活空行。
- **重试**（与 2.7.1 错误码一致）：

| 情况 | 处理 |
|---|---|
| 连接失败、读超时 | 重试，最多 2 次，指数退避 1 s、2 s（上限 8 s）加全抖动 |
| 429 | 同上；若响应带 `Retry-After` 则按其等待（是否提供【待核实】）；同时把网关并发信号量减半 5 分钟 ◇ |
| 500、503 | 同上；连续 5 次 5xx → 熔断该供应商 300 秒 ◇，期间直接回落模板 |
| JSON 模式返回空或全空格 `content`、JSON 解析失败 | 重试 1 次；再失败 → `validation_failed`、回落模板 |
| 400、422 | 不重试；记录错误信息（不含 prompt 原文）、回落模板；同一模板版本 1 小时内 ≥ 5 次 → 告警（多为模板或参数错误） |
| 401 | 不重试；供应商置 `auth_failed`、全部任务回落模板、管理员告警；“测试连接”成功后恢复 |
| 402 | 不重试；供应商置 `insufficient_balance`、全部任务回落模板、管理员告警（提示充值）；“测试连接”成功后恢复 |

- **并发**：网关进程内信号量，默认 8 ◇（远低于账号并发上限 2500），可热调。
- **成本**：`cost = hit_tokens × 命中价 + miss_tokens × 未命中价 + output_tokens × 输出价`，再按调用时刻是否处于空闲时段乘 0.5；空闲判断用北京时间与交易日历近似“法定节假日”（只用于估算，月底以账单对账）。
- **生成内容标识**：前端展示 LLM 文本时标注“AI 生成”（服务协议 3.7），模板文本不标。
- **测试**：用本地桩服务回放 400/401/402/422/429/500/503、保活空行、空 JSON 内容，CI 不访问真实 DeepSeek；真实联调只在本机用环境变量，不入库。

### 2.8 建议的模拟跟踪（替代回测）
- **不做回测**。每条 `buy/add/sell/reduce/hold/wait` 建议生成时记录**参考价**（生成时刻快照的最新价、`data_as_of`）与基准（默认沪深300，可选所属行业指数）。
- **两个价格口径分开（T-A02 已定）**：**参考价**只用于计划草案的数量/价格区间与界面展示；**模拟跟踪的起点**一律用 2.8.1 的**入场价**（盘后生成 → T+1 开盘价；盘中生成 → 下一根 1 分钟 bar 开盘价），T+1/T+5/T+20 的区间收益、基准收益与超额都从入场价对应时点算起（基准取同一时点的指数价）。隔夜跳空对 hold 与 sell 都无法规避，因此不计入。
- **跟踪规则**：`suggestion_tracking` 在 T+1、T+5、T+20 个交易日收盘后计算：区间收益（复权口径：用日 K 前复权【复权参数待 T003 验证】）、同期基准收益、超额收益、区间最大回撤/最大上涨、是否触发过失效条件及触发时间；"方向正确"的定义按动作：buy/add 看超额 > 0，sell/reduce 看超额 < 0，hold 看 |超额| 在阈值内（T+1 为 1.0%、T+5 为 2%、T+20 为 5%，第 9 节 C(7)；T+1 的 hold 方向正确率只展示、不进健康度），wait 只记录不计胜率。
- **口径**：纯模拟，**不代表用户实际收益**；若用户据此有实际成交（导入或手动），复盘页把"建议模拟结果"与"实际成交结果"并列，差异计入"执行"维度。
- **统计**：按策略版本、周期、动作、置信度分组的样本数（即 `strategy_tracking_stats`，并驱动 2.5.7 自动降权）、命中率、平均超额（样本少于 30 时标注"样本不足"）；**本人统计仅本人可见；全站匿名汇总（接口参数 `scope=site`，默认 `mine`，见契约 v0.2.9 #10；表中 `strategy_tracking_stats.scope` 记为 `global`；只有策略级聚合数字，不含任何用户/个股持仓信息）仅登录用户在策略页可见**，不做对外宣传与排名（避免"业绩展示"引发合规问题，见 7.2）。
- 喂给能力 5（复盘）：复盘时间线显示每条建议的跟踪结果；策略边界统计（某策略在某市场环境下的表现）。

#### 2.8.1 模拟跟踪口径（采纳调研 §3.6 的建议，使用 2.13 的交易规则模块）
- **入场价**：盘后信号按 T+1 开盘价入场；盘中信号按下一根 1 分钟 bar 的开盘价入场。
- **不可成交样本**：一字涨停买不进、一字跌停卖不出、停牌的样本记为"不可成交"，**不计入胜率**，但计数会显示出来。
- **hold 的被动样本**：T+1 停牌、T+1 一字跌停、当日买入当日不能卖的仓位（`forced_hold`）的 hold 样本不计入 n，只单独计数（validation.md §7.1A，T-A02 已定）。
- **成本**：可选扣除佣金（含最低收费）、过户费、卖出印花税和滑点（2.13）。
- **冷却**：同一模板加同一证券有冷却期，防止重复样本。
- **独立跟踪**：每个模板版本独立跟踪，退出只作用于自己。
- **表现回填**：结果回填 L1 卡片的"表现记录"和 L2 版本。所有统计都附样本数 n（2.12.3）。
- **执行偏差**：用户真实成交价对比草案参考价，记录滑点和完成度，作为复盘中"执行"维度的素材。

#### 2.8.2 健康度与自动降权：合并为一个机制
- **输入**：
  - ① 产品内的模拟跟踪统计（用户可见）；
  - ② 若第 9 节问题 26 获批，加上内部评估模块的每日复验结果（仅管理员可见）。
- **权重**：沿用 2.5.7 的公式，`weight = clamp(raw, 0.3, 1.2)`；n < 20 时 `weight = 1`，状态不变。
- **状态机**（策略版本级别，全站一份；只在 `published` 与 `observing` 之间自动切换）：

| 跃迁 | 条件（默认值，可配置） |
|---|---|
| `published` → `observing` | n ≥ 20，并且以下任一成立：<br>• 全站 `weight < 0.8` 连续 5 个交易日；<br>• 内部复验的稳健度低于发布基线的 70%（若已启用内部评估） |
| `observing` → `published` | `weight ≥ 0.9` 连续 10 个交易日，且内部复验恢复（迟滞，防止来回切换） |
| `observing` → 提示"建议复审 / 退役" | `weight < 0.6` 持续 20 个交易日，或内部稳健度低于基线的 50% 持续 20 个交易日 → 通知管理员 |
| → `retired` | **只能由管理员确认**，并写审计 |

- **用户开关 `auto_downweight`**（默认开）只控制"本人的排序是否乘以权重"。健康度状态和"观察中"标记对所有用户可见，并附 n。
- **发布基线**：版本发布时自动记录模拟跟踪的基线；若启用内部评估，同时记录 OOS 稳健度基线。基线写入 `strategy_health_baselines`。
- **T-A33 裁定（2026-11-08）**：缺日清零两个连续计数；内部复验恢复阈值 `health.internal_recover_ratio` 默认 0.8，未启用内部评估时不参与。细则见契约 §7.11.3 “T-A33 裁定”第 8–9 点。

### 2.9 会员体系预留（不实现支付）
- 表：`plans`（套餐：code、名称、状态、展示价格文案——**不接支付**）、`plan_entitlements`（plan_id、key、value，如 `watchlist.per_user_cap=100`、`realtime.min_notify_interval_s=60`、`intraday.focus_cap=20`、`llm.daily_explanations=200`、`channels.allowed=[in_app,email]`、`import.monthly_files=50`）、`user_subscriptions`（user_id、plan_id、status `active/expired/cancelled`、`starts_at`、`ends_at`、`source manual_admin/payment(预留)`、备注）、`entitlement_overrides`（管理员对个别用户的覆盖）。
- 读取：`EntitlementService.get(user, key)` = 覆盖 > 当前订阅套餐 > 默认 `free` 套餐；所有上限（自选数、通知节奏、LLM 次数）从这里取，不在代码里写死。超限返回 `ENTITLEMENT_LIMIT_REACHED`。
- MVP 只有 `free`（或 `beta`）一个套餐，管理员可手动给用户开通；**收费前**须先完成第 7.2 合规拍板（收费会显著提高"荐股软件"认定风险）。

### 2.10 前端：专业交易终端风格（仅桌面）
- 深色主题、数据密集、仅桌面（最低 1440×900，< 1280 宽显示"请使用电脑端"，不做移动适配）。
- 组件：**antd 6 暗色算法 + compact 算法**（表单、弹窗、后台页面）；**AG Grid Community**（MIT，虚拟滚动、列固定、条件着色、按单元格增量刷新，用于实时更新的密集表格）+ **AntD Table**（低频、少量行的管理与表单类表格）；**TradingView Lightweight Charts**（Apache-2.0，需按许可展示署名，K 线/分时/成交量）+ **ECharts**（资金流、因子分位、跟踪统计等其他图表）；**react-resizable-panels**（MIT）只用于分隔条调宽与折叠；键盘快捷键（代码搜索、切换面板）。
- 颜色约定：红涨绿跌（A 股习惯），可在设置切换；数字等宽字体、千分位、涨跌色与 `stale` 灰显。
- 终端主界面 `/terminal`：左 自选/持仓列表（实时价、涨跌、信号状态、当前各策略动作徽标（分歧时显示"分歧"徽标））→ 中 K 线 + 分时 + 信号标记 → 右 当前建议卡（动作、分数、置信度、理由、依据数据、反证、失效条件、策略版本、数据时间）→ 底部 通知流 / 日报。
- **T-F01 选型结论（2026-11-01，T-A01，回应 T-F00 §6 第 8 项；许可证当日核实）**：
  - **表格：两者并用，按场景分工。** AG Grid **只用 Community 版**（MIT；npm `ag-grid-community`）用于实时、高密度、行数多的表格：终端自选/持仓、成交流水、导入预览（最多 50,000 行）、候选信号列表。理由：行情每 15 秒一轮、按单元格增量刷新和涨跌闪烁不触发整行重渲染；内置行虚拟化、列固定、列宽拖动、键盘导航，质量优先下自己在 AntD Table 上补这些的成本和风险更高。AntD Table 用于管理端、设置页、日报中的小表（< 200 行、不实时刷新），与表单组件风格一致。前端统一封装 `DataGrid` 组件，业务代码不直接依赖 AG Grid 的 API，以后可替换。
  - **禁止 AG Grid Enterprise**（商业许可）。行分组、聚合、透视、剪贴板、Excel 导出、区域选择、右键/列菜单、集合筛选、工具面板、状态栏、主从表、树形数据、服务端行模型、迷你图都是 Enterprise 功能，设计中不得依赖；需要时用自研的简单替代（如导出走后端 CSV）。CI 依赖检查发现 `ag-grid-enterprise` 或 `@ag-grid-enterprise/*` 即失败（T-O02）。
  - **布局：固定三栏 + 底部面板**（左列表、中图表、右建议卡、底部通知/日报）。用 react-resizable-panels 只做**分隔条调宽和折叠**，尺寸存在浏览器 localStorage，提供"恢复默认布局"；**V1 不做面板自由拖拽、停靠或重排**。理由：10–100 名桌面用户、单一工作流，固定布局可预测、易上手，E2E 截图测试稳定，键盘焦点顺序固定；自由停靠增加状态管理和测试面，收益小。
  - 原型（T-F00）用 AntD Table 和固定三栏，布局与本结论一致；表格在 T-F01/T-F11 中替换为 `DataGrid`（AG Grid Community）。版本**已定为 React 19 + antd 6**（与原型一致，第 9 节问题 34），T-F01 直接沿用。

---

### 2.11 设计取舍说明（用户想法 → 采纳 / 简化 / 延后）
> 用户自述是新手。vision.md 中的分层与字段表是想法，不是硬性要求。以下按"能在 10–100 用户的单机 MVP 上高质量交付"做取舍。**核心意图全部保留**：先解释后运行、候选信号 ≠ 计划、不可执行原因带解除条件、冲突并列不合并、输出可解释（0B）。

| 用户 / 编排者的想法 | 处理 | 理由 |
|---|---|---|
| 三层：知识卡 → 可运行模板 → 实例与计划（11:51） | **采纳** | 把"讲清楚"和"能运行"分开，对新手最有价值；晋级门槛本身也是教育内容 |
| 五层草案（数据、信号、策略、匹配建议、跟踪，11:49） | **合并** | 数据与指标是共享底座，不算一层；信号层并入 L2 规则和 `rule_snippets`；匹配与跟踪是 L3 的流程。层数越多，口径越容易漂移（调研 §2） |
| 策略卡完整字段表（12 组用户字段 + 编排者补充） | **简化**为 8 个必填 + 选填 + 系统字段（2.5.0A） | 卡片太长新手读不完。运行、复盘、表现字段由系统维护，不让人填；选股与互斥放在 L2 配置 |
| 验证字段（区间、基准、成本、样本外、交易明细） | **延后** | 产品不做回测。上线后用 T+1/5/20 模拟跟踪；另设内部评估模块，第三阶段实施（问题 26 已定）；用户只看到是否做过检验、方法类型和日期（方案 A，第 9 节 C(6)）（2.12.4） |
| 参数敏感性 | **延后** | 需要历史验证支撑；MVP 只做参数范围和 G6 的触发率体检 |
| 不可执行原因：用户列出 4 条，编排者补充 10 条 | **采纳并结构化**为 23 个原因码（T-A06 删去 `PROFILE_OR_CONSENT_MISSING`，现为 22 个），每条带解除条件和检查时机（2.5.9） | 让"为什么现在不能做、什么时候能做"可以被监控和通知 |
| 六维度全部纳入、越细越好 | **采纳，但如实标注缺口** | 新闻和舆情热度麦蕊没有，不伪造维度观点（`unknown`） |
| 信号矛盾不合并 | **采纳**，并新增原因码 `STRATEGY_CONFLICT` | 冲突时不自动拟定草案，由用户选择 |
| 六项风控逐项可开关 | **采纳**，统一 `RiskHook`；RC5 的 VaR 分级后置 | 一条路径，便于测试 |
| 自动降权可开关 | **采纳**，并增加"表现差持续 20 个交易日提示复审，不自动退役" | 避免小样本误杀策略 |
| LLM 生成策略（编排者草案） | **延后到第三阶段**，只输出 JSON，必须人工审核 | 先把规则引擎和门槛做稳 |
| 多用户、支付、微信推送等 | 会员只预留；微信放到第二步 | 见 2.6、2.9 |
| SQLite（用户担心以后变慢） | **不用**（开发和测试也用 PostgreSQL 容器） | 单写者、并发差，与生产不一致；见第 3A 节 |
| KHunter 式 `BaseStrategy` + 注册表 + YAML 参数（用户 12:02） | **采纳并调整**：公共基类 `BaseStrategy`，下分 `ScreenerStrategy.select_stocks()` 和 `TimingStrategy.generate_signals()`；`calculate_indicators()` 只声明或派生特征，并注册进 `feature_catalog`；配置型模板由通用的 `RuleTemplateStrategy` 实现（2.5.13） | 代码策略与 YAML/DB 模板共用同一接口、注册表和输出协议，只有一个数据口径 |
| 选股与择时拆成两个接口（编排者） | **采纳** | 选股不产生动作，择时产出候选信号，职责清楚 |
| 生命周期 draft → simulated → published，放文件不等于激活 | **采纳并扩展**为 `draft / simulating / published / observing / retired`，由数据库状态加管理员批准控制；注册表显式登记 | 防止误上线；与健康度合并为一个状态机 |
| 按 A 股规则做内部评估（参考 OSkhQuant 思路） | **采纳**为共享模块 `app/market_rules`（2.13），模拟跟踪与内部评估共用；**不拷贝任何代码**（该项目为 CC BY-NC） | 口径统一；许可证合规 |
| 抗过拟合：K 折样本外稳健度 + 发布后每日复验 + 健康/观察/退役（参考 TSP） | **采纳为仅内部可见的评估模块**，与"内部历史验证"合并为一个模块（2.12.4），并与自动降权合并为一个健康度机制（2.8.2）；**是否启用待用户拍板**（第 9 节问题 26） | 与"产品内不做回测"相容：结果不展示给终端用户，只用于管理员审核和默认参数选择 |
| ST 股涨跌幅 5%（用户 12:02 的表述） | **更正**：沪深主板风险警示股票自 **2026-07-06** 起为 10%（交易所 2026-04-24 发布的新版交易规则）；规则按生效日期分段存储，历史回看仍用 5% | **【已定，已核实 2026-11-01】** 官方出处：上交所《关于发布〈上海证券交易所交易规则（2026 年修订）〉的通知》（上证发〔2026〕41 号）、深交所《关于发布〈深圳证券交易所交易规则（2026 年修订）〉的通知》（深证上〔2026〕551 号），2026-04-24 发布，**2026-07-06 起施行**（链接见 `docs/strategies/market_rules_check.md` O1–O8）；已写入 `market_rules.yaml`（2026-07-06 段 10%，此前一段 5%） |

### 2.12 多因子与事件驱动的质量保障

#### 2.12.1 多因子
- **严格按时点（point-in-time）**：
  - 财务数据**以披露日为准**，不以报告期为准。麦蕊财报接口带 `jzrq`（截止日期）和 `plrq`（披露日期）【文档已列·待 T003 验证】。入库时保存 `report_period`、`announce_date` 和 `available_from`：盘后披露的从下一交易日开盘可用，盘中披露的从披露时刻的下一根 1 分钟 bar 可用；时刻不详时按盘后处理。
  - 行情与因子保存 `first_seen_at`。
  - 因子接口返回 `trade_date`、`update_time`、`report_period`、`calc_version`【文档已列·待 T003 验证】。**历史截面是否按当时已知信息计算（是否回填、是否随 `calc_version` 重算）【待 T003 验证：T-B05】**。在核实之前，内部评估一律用我们自己按时点落库的截面，不用回溯拉取的历史因子。
- **财务按时点自算（v0.2.9 内，架构师裁定，L-01 研究口径；T-B55）**：
  - 可用时点：每个报告期取 `available_from ≤ T` 中最新的版本；`available_from` = `plrq` 的下一交易日（时刻不详，按盘后处理）；`plrq ≤ jzrq` 的占位行丢弃；重述作为新版本保存（`market.financial_reports` 已按数据变化新增行）；从上线起记录 `first_seen_at`，与 `plrq` 不一致时以较晚者为准。
  - TTM：`TTM(y,q) = YTD(y,q) + FY(y−1) − YTD(y−1,q)`（年报直接取 FY）；三个分量在 T 时都必须可见，否则退到上一个可计算的报告期，但不早于 T 前 15 个月，再不行为 `null`。字段是否为累计值及单位以 T-B05 实测为准。
  - `pe_ttm` = 当日不复权收盘价 × 总股本 `zgb`（取 `bdrq ≤ T` 且已披露的最新值）÷ TTM 归母净利润（`gsmgsyzzdjlr`）；净利润 ≤ 0 → `null`（不给负 PE）。
  - `roe_ttm` = TTM 归母净利润 ÷ 归母权益（`gsmgdqsyhj`）在 P 期与 P−4 期的平均；P−4 缺失时只用 P 期，并标 `roe_basis=single_period`。
  - 经营现金流/净利润 = TTM 经营现金流 ÷ TTM 归母净利润，分子、分母用同一个报告期 P（净利润 ≤ 0 → `null`）；资产负债率 = `fzhj` ÷ `zczj`，银行、保险不计算（`null`）。
  - **经营现金流字段（v0.2.9 内，架构师裁定 T-R12，取代原写法 `jyhdcsdxjlje`）**：主字段 `jyhdcsdxjlxj`（600519 实测有值，且等于经营活动现金流入小计 `jyhdxjlrxj` − 流出小计 `jyhdxjlcxj`，即主表“经营活动产生的现金流量净额”），备用字段 `jyhdcsdxjlje`（600519 两期均为 `'-'`）。每个 YTD 分量取 `coalesce(jyhdcsdxjlxj, jyhdcsdxjlje)`，并在 `basis.ocf_field` 按分量记录实际所用字段（来源字段）；两者都为空（`'-'` 或缺失）→ 该分量缺失，TTM 经营现金流为 `null`，**不用 0 补**。两字段的非空率与 cashflow 是否为累计口径由 T-B05 实测确认；若实测推翻主次，只改本条与 T-B55 配置，不改公式。
  - **PB（v0.2.9 内，架构师裁定 T-R12，G3）**：`pb` = d 日总市值 ÷ 归母股东权益 `gsmgdqsyhj`。总市值 = d 日不复权收盘价 × `zgb`（与 `pe_ttm` 同一取法，不用快照或因子里的市值）；归母权益取 balance 中按 `plrq` 时点规则（本节第一条）在 T 时可见的最新一期（时点值，不做 TTM，回退下限同 15 个月）。归母权益 ≤ 0 或缺失 → `pb = null`，不参与行业分位排序（不进入分母）。银行、保险同样计算，但其 balance 字段（`gsmgdqsyhj`）未实测，T-B05 核对前该类证券的 `pb` 标待核实。行业分位同 `pe_ttm` 的行业分位（申万一级、因子池排除、组内 N < 5 → `null`）。特征键由研究员在 `feature_spec.md` §7A 登记（建议 `f.pb_pit`、`f.pb_pit_ind_pct`）。
  - **边界情况（v0.2.9 内，架构师裁定 T-R12a；适用于 `pe_ttm`、`pb`，以及 `roe_ttm` 中的权益部分）**。原则：拿不准就留空（`null`），并在 `basis.null_reason` 写原因码；不用前值、0、插值、估算或别的数据源补数。
    1. **停牌和无效日线**：d 日没有日线、`sf=1`，或日线被 T-B05a 标为 `suspect` → 当日 `pe_ttm`、`pb` 为 `null`（`null_reason=no_valid_bar`）。不用停牌前的收盘价顶替。
    2. **股本变动日**：`zgb(d)` 取 capital 中 `bdrq ≤ d` 且 `next_trading_day(plrq) ≤ d` 的行里 `bdrq` 最大的一行（同 `pe_ttm`），并把所用行的 `bdrq` 记入 `basis.zgb_bdrq`。
       - 已披露但 `bdrq` 还没到的行不提前用；
       - `bdrq` 已到但还没披露的行也不用。
       - 如果 T 时已经可以知道送转方案及其除权日（数据来源需 T-B05 确认麦蕊是否提供分红送转数据），而 d ≥ 除权日时仍然没有 `bdrq ≥ 除权日` 的可见 capital 行，就按“价格已除权、股本未更新”处理：值为 `null`（`null_reason=share_change_pending`）。
       - 没有送转数据源时，不做这项检查，`basis.share_change_check=unavailable`。是否必须接入这类数据，按 T-B05 对 V5d 的实测结论决定：如果 capital 行普遍晚于除权日才可见，就必须接入。
    3. **B 股、H 股股本**：总市值 = A 股不复权收盘价 × `zgb`（全部股本，含 B 股、H 股），记 `basis.mcap_basis=a_price_total_shares`。不用 B 股或 H 股价格，也不做汇率换算。这是常用的“A 股口径总市值”，分母归母权益覆盖整个公司，两边口径一致。
       - `zgb` 是否包含 B 股和 H 股尚未实测。T-B05 用一家 A+H 公司和一家 A+B 公司核对。
       - 核对之前，有非 A 股股本的公司标 `basis.verify_pending` 含 `non_a_share_capital`（见下方“待核实标记”）。
       - 实测如果发现 `zgb` 只含 A 股，这类公司的 `pe_ttm`、`pb` 一律为 `null`，直到另行裁定。
    4. **新股和报告空窗**：
       - 上市后还没有有效报告期（只有 `plrq ≤ jzrq` 的占位行，或回退到 15 个月下限仍没有可用期）→ `null`（`null_reason=no_visible_report`）。
       - 所选报告期的 `jzrq` 早于上市日时，归母权益不含募集资金：这时 `pb` 以及 `roe_ttm` 为 `null`（`null_reason=pre_listing_equity`）；`pe_ttm` 照常计算，因为上市前的利润是真实披露数。
       - 最新可见的 capital 行 `bdrq` 早于上市日（股本未含新发股份）→ `pe_ttm`、`pb` 为 `null`。
       - 不用招股书或募资额推算上市后的权益。
       - 上市不满 60 个交易日的证券本来就在因子池之外，这条规则主要影响回测，以及上市 60 个交易日至第一份定期报告之间的空窗。
    5. **币种和单位**：金额一律按人民币“元”处理（600519、000001 已实测，麦蕊已经把百万元换算成元）。
       - 原始响应中出现非人民币币种、非“元”单位的标识（字段名由 T-B05 确认），或同一证券不同报告期的数量级明显不连续 → 该期分量为 `null`，并告警 `unit_mismatch`。
       - 不按数量级猜单位并自动换算。
       - 不要求跨版本数值精确相等（千元、百万元取整差，见 feature_spec §7B）。
    6. **归母权益是极小的正数**：`pb` 不设上限、不缩尾，按原值落库。分位排序和 Spearman 都基于秩，不受影响。展示层和对照报告可以把 `pb > 100` 标为离群，但不改值。
    7. **不用每股字段**：不用每股净资产、每股收益等每股字段推算 `pe_ttm`、`pb`（送转会追溯重述这些字段，见 feature_spec §7B R5）。
  - **待核实标记（v0.2.9 内，架构师裁定 T-R12a）**：
    - 键级状态沿用 `feature_catalog.status`（`declared` → `verified_live`），不变。
    - 证券级的“这类公司还没实测”写在每行 `market.financial_derived.basis.verify_pending`（字符串数组，空数组表示没有）。当前取值：
      - `bank_balance`：`f.sw_l1` = 银行；
      - `insurance_balance`：按 2.12.1 线上切换条中的保险名单或申万二级识别；
      - `non_a_share_capital`：见上方第 3 条。
    - 适用范围：
      - 前两项适用于 `pb`、`roe_ttm`（用到 `gsmgdqsyhj` 的行）；`debt_ratio` 对银行、保险本来就为 `null`，不加标记。
      - 第三项适用于 `pe_ttm`、`pb`。
      - 截面派生键（PB 分位、PE 分位）继承所用底层值的 `verify_pending`（T-B35 在特征值元数据里保留）。
    - 带标记的值照常计算和落库，研究与回测报告必须单列这部分。
    - 在 feature_spec §7C S2 覆盖率中，这部分**同时从分子和分母中剔除**，并单列它们的个数。只剔分子会让银行、保险（约 1% 的样本）直接把 PB 的 99% 门槛压到不达标。
    - S1 要求 V5b、V5e、V5g 关闭（T-R12b 补 V5g），含义是：切换时所有 `verify_pending` 取值都必须已由 T-B05 清除；T-B05 核实后，T-B55 重算时不再写这个标记。S1 另需关闭 V5d、V5h（见下方 T-R12b 补充裁定第 4 条）。
  - **PB 覆盖率门槛（feature_spec §7C S2 增补，v0.2.9 内，架构师裁定 T-R12a）**：
    - 分母 D(d) = S2 的池 U（F43 的池：§1.4 股票池 + 因子池排除，即 d 日可交易、非 ST、非退市整理、上市满 60 个交易日），再剔除两类：
      - T 时所选报告期的归母权益**已知且 ≤ 0** 的证券。归母权益缺失的证券留在分母里，计为未覆盖。
      - `verify_pending` 非空的证券。
    - 分子：D(d) 中 `f.pb_pit` 非 `null` 的个数。
    - 全市场门槛：分子 / D(d) ≥ 99%，与 PE 相同；PB 只需要价格、股本和一期权益，比 PE 少 TTM 的三个分量。
    - 行业门槛：在每个申万一级行业中，组内 D ≥ 5 时，组内覆盖率 ≥ 95%（与其他键的 95% 相同）。组内 D < 5 的行业不考核（这时 PB 分位本来就为 `null`），但要列出。`f.sw_l1` 为空的证券只计入全市场口径，单列个数。
    - 同时报告 PB 分位非 `null` 的个数，作为参考，不作门禁。
  - **T-R12b 补充裁定（v0.2.9 内，架构师；对应 feature_spec v1.1.2 的 6 个非阻塞点）**：
    1. **原因码补全，且列表封闭**：`market.financial_derived` 中 `value` 为 `null` 的行必须写 `basis.null_reason`，`value` 非空的行不写这个字段；T-B55 的单元测试要断言这两条。取值只能是下表所列，要新增原因码先改本条。

       | 原因码 | 情形 | 适用 metric |
       |---|---|---|
       | `no_valid_bar` | 边界 1 | `pe_ttm`、`pb` |
       | `share_change_pending` | 边界 2 | `pe_ttm`、`pb` |
       | `a_share_only_capital` | 边界 3：实测 `zgb` 只含 A 股时，有 B、H 股的公司 | `pe_ttm`、`pb` |
       | `no_visible_report` | 边界 4：没有有效报告期，或回退 15 个月仍取不到 | 全部 |
       | `pre_listing_equity` | 边界 4：所选报告期 P 早于上市日 | `pb`、`roe_ttm` |
       | `pre_listing_capital` | 边界 4：最新可见 capital 行的 `bdrq` 早于上市日 | `pe_ttm`、`pb` |
       | `unit_mismatch` | 边界 5（既是告警名，也是原因码） | 全部 |
       | `non_positive_earnings` | TTM 归母净利润 ≤ 0（PE）；现金流比的分母 `NP_TTM ≤ 0` 也用这个码 | `pe_ttm`、`ocf_to_np_ttm` |
       | `non_positive_equity` | E(P) ≤ 0 | `pb`、`roe_ttm` |
       | `no_capital_row` | 没有 `bdrq ≤ d` 且已可见的 capital 行，或 `zgb` 为空、≤ 0 | `pe_ttm`、`pb` |
       | `ocf_missing` | 经营现金流两个字段都为空 | `ocf_to_np_ttm` |
       | `component_missing` | 回退选出的 P 中某个必需分量仍为空或无效，且不属于上述任何一种（例如 `zczj` 为空或 ≤ 0，T-R12c 裁定 1） | 全部 |
       | `data_conflict` | 补充规则 ②：两个版本不可区分且数值不同（既是告警名，也是原因码） | 全部 |
       | `financial_sector_na` | 银行、保险的资产负债率 | `debt_ratio` |

       一行同时命中多个原因时，只写表中靠前的一个。分位键（PB 分位、PE 分位）在组内 N < 5 或底层值为 null 时为 null，原因由 T-B35 记在特征值元数据中（`group_too_small` / `input_null`），不写进 `financial_derived`。
    2. **`unit_mismatch` 同时作原因码**：确认 feature_spec v1.1.2 的做法，名称与告警相同。
    3. **ROE 中 P−4 早于上市日**：E(P−4) 不含募集资金，拿它和 E(P) 平均会压低分母、高估 ROE。这种情况按 E(P−4) 缺失处理，走 `roe_basis=single_period`，并记 `basis.single_period_reason=p4_pre_listing`。同时给已有的两种 single_period 情形补上记录：`p4_missing`、`p4_non_positive`（补充规则 ③）。不用招股书数据补 E(P−4)。
    4. **S1 的关闭项**：
       - 确认把 V5g 写进 S1。
       - V5d、V5h 虽然不产生 `verify_pending` 标记，但也要在 S1 里关闭（取保守默认）。不关闭的话，股本口径和单位口径就没有经过实测，自算值可能静默出错。
       - V5d 的关闭条件：T-B05 写出结论；如果 capital 行普遍晚于除权日才可见，送转数据已经接入，且切换时 `basis.share_change_check` 不再为 `unavailable`。
       - V5h 的关闭条件：确认币种、单位字段的字段名，或者确认没有这类字段。没有字段时，只靠边界 5 的数量级不连续检查，并把这一点写进 V5h 的结论。
       - 这一条会延长切换前的等待，见 §9 问题 96。
    5. **其他键的 `unit_mismatch`**：边界 5 扩展到 `market.financial_derived` 的全部 metric，包括 `ocf_to_np_ttm`、`debt_ratio`。比值键的分子、分母只要有一个分量（含 TTM 用到的任一期）命中，该值就为 null（`unit_mismatch`）。理由：比值只能抵消同一期内的单位差，抵消不了 TTM 跨期拼接时的单位差。
    6. **B、H 股识别字段待实测期间**：字段名由 T-B05 ⑦（V5g）确认，确认之前不猜。
       - capital 中能识别有 B、H 股本的公司，照常打 `non_a_share_capital`。
       - 无法识别时，记 `basis.share_class_check=unavailable`，不打 `non_a_share_capital`，也不按代码段或名称推断。
       - 只要还有 `unavailable` 的行，V5g 就没有关闭，S1 不通过，所以不会因此提前切换。
       - 研究和回测报告要单列 `share_class_check=unavailable` 的证券数。
  - **T-R12c 补充裁定（v0.2.9 内，架构师；对应 feature_spec v1.1.3 的 3 个待定点）**：
    1. **`debt_ratio` 的 `zczj ≤ 0`**：并入 `component_missing`，不新增原因码。资产合计 ≤ 0 只能是源数据错误，和“分量取不到可用值”处理方式相同，单独设码没有下游用途；“`value` 为 null ⇔ 有 `null_reason`”继续成立。T-B55 同时写一条 `data_quality` 告警（不打断计算），便于 T-B05 回查。
    2. **`single_period_reason` 多命中时的优先级**：确认 `p4_pre_listing` → `p4_missing` → `p4_non_positive`，只写第一个。理由：P−4 早于上市日时，即使有值也不能用，先于“缺失”；缺失时无法判断正负。
    3. **退市证券**：T-B55 不为退市证券补写 null 行，所以不需要新增原因码。规则：只为有可见报告期的证券计算；`pe_ttm`、`pb` 只为有日线的交易日写行，退市后没有日线就没有行，不写 null 行。退市前的历史行照常计算，按上表写码。`listing_status ∈ {delisted, missing_from_list}` 时 f.* 全为 null，这是特征层规则（feature_spec §1.7、T-B35），与 `financial_derived` 无关。
  - **T-R12e 补充裁定（v0.2.9 内，架构师；对应后端 af589c0 探针中提出的 3 个口径问题，实测结论写入 `docs/mairui-verified.md`）**：
    1. **capital 行可见时间（新增 V5i，S1 关闭项）**：`plrq = bdrq`，或 `plrq` 恰好是季末日时，不能当作真实披露日，否则回填数据会把股本提前放出（前视）。
       - 可见时间取 `max(next_trading_day(plrq), first_seen_at)`。
       - 首次全量回填的这类行没有可信的 `first_seen_at`，按法定披露截止日保守处理：Q1 → 4-30，H1 → 8-31，Q3 → 10-31，年报 → 次年 4-30；记 `basis.pit_basis=capital_deadline`。
       - 不是季末的 `bdrq`（股本变动日）照旧按 `plrq` 处理。
       - 由 T-B05 用 600519 等样例确认麦蕊是否回填。确认 `plrq` 是真实披露日时，取消这条保守规则（只改本条，不改原因码）。
    2. **B、H 股识别（V5g）**：capital 没有 B/H 字段，就用配置里的 A+B、A+H 公司名单识别，名单必须注明来源和日期，做法与 V5e 的保险名单一样。名单内的公司按第 6 条打 `non_a_share_capital`，名单外的记 `share_class_check=list`（不再是 `unavailable`）。V5g 的关闭条件改为两项：名单已接入；`zgb` 是否包含 B、H 股已用一家 A+H、一家 A+B 公司对照巨潮披露的总股本核实过。不按代码段或名称推断这一条不变。
    3. **CDR 股本单位（新增 V5j，S1 关闭项）**：在 T-B05 核实 CDR 的 `zgb` 是按基础股份还是按 CDR 份数计之前，CDR 证券的 `pe_ttm`、`pb` 照常计算，但打 `basis.verify_pending` 含 `cdr_unit`，不计入 S2 覆盖率的分子和分母；行业分位见 T-R12f 第 6 条。CDR 以 `market.securities.type = cdr` 识别（T-R12f 更正）。核实后：如果 `zgb` 按 CDR 份数计，就换算成 c × CDR 份数（不再乘转换比例），并清除这个标记。
  - **T-R12f 补充裁定（v0.2.9 内，架构师；对应 feature_spec v1.1.5 的 8 个待定点，并更正 T-R12e 的措辞）**：
    1. **V5i 适用范围**：适用条件是 `bdrq` 为季末日，并且 `plrq = bdrq` 或 `plrq` 也是季末日。`plrq = bdrq` 但两者都不是季末日的行，照旧按 `plrq` 处理。可见时间取 `max(next_trading_day(plrq), 截止日规则)`；截止日按 `bdrq` 所属的报告期取，因为股本数属于这个期间，而且这样取更保守。
    2. **截止日的可见时刻**：取 `next_trading_day(截止日) 09:30`，与财务行的规则一致。
       截止日规则只用于首次全量回填写入的季末行，因为这些行没有可信的 `first_seen_at`。增量采集的季末行取 `max(next_trading_day(plrq), first_seen_at)`，不套用截止日（T-R12g）。
    3. **`basis.pit_basis` 改为字符串数组**，与 `verify_pending` 一样，可以同时含 `plrq_only` 和 `capital_deadline`；没有任何特例时为空数组或不写。T-B55 按数组实现。
    4. **`share_class_check` 的取值**：
       - 名单接入前，所有行记 `unavailable`。
       - 名单接入后，所有行记 `list`，表示按名单判定。名单内的公司另外打 `non_a_share_capital`。
       - 将来如果 capital 有了区分字段，改记 `field`。
    5. **CDR 识别**：更正 T-R12e，CDR 以 `market.securities.type = cdr` 识别，不另设名单。
    6. **CDR 与分位**：按 feature_spec §1.4，`type = cdr` 的证券本来就不在 F43、F48 的分位池里，所以：
       - 不需要另设池剔除规则，YAML 去掉 `pool_exclude_verify_pending`；
       - 不需要新的元数据原因；
       - `cdr_unit` 只是 F42、F47 值上的标记。S2 池 U 按 §1.4 本来就不含 CDR，所以不再写 S2 剔除条款（T-R12g）。
    7. **V5j 中 `zgb` 按基础股份计的情况**：总市值 = c（每份 CDR 的价格）× `zgb` × 每股基础股份对应的 CDR 份数。转换比例写在配置里，按证券单列，并注明来源（招股书或上市公告）。T-B05 确认单位、配置也接入后，清除 `cdr_unit`。如果 `zgb` 按 CDR 份数计，总市值 = c × `zgb`，不需要配置，T-B05 确认后即清除 `cdr_unit`（T-R12g）。
    8. **银行、保险标记**：维持 T-R12a 的规定，继承标记，照常参与排序。T-R12e 原文中“规则同银行、保险的标记：不进入行业分位”这句措辞有误，已更正。
  - **T-R12h 补充裁定（v0.2.9 内，架构师；对应后端 reports/T-R12ef-lists.md 的 3 点）**：
    1. **A+B、A+H 名单接入配置**，放在 `config/share_class_list.yaml`。
       - 文件头写 `list_version`、`as_of`、`sources`（来源和取数日期）。
       - 每条记录写 `code`、`class`（`B` 或 `H`）、配对代码、`effective_from`、`effective_to`（可为空）、`source`、`verified`（布尔值）。
       - 计算 d 日的值时，只用 `effective_from ≤ d` 且 `effective_to` 为空或 `effective_to > d` 的记录，这样历史回测不会用到之后才上市的 H 股。
       - 用到的名单版本记在 `basis.share_class_list_version`。
       - 名单更新时整版替换，`list_version` 加一，不改旧行。T-B55 重算时按新版本覆盖。
    2. **手工对应的 45 对**：先记 `verified=false` 接入，照常打 `non_a_share_capital`。V5g 的关闭条件加一项：名单内所有记录都要 `verified=true`，核对来源是巨潮或港交所披露。
    3. **211 对与 209 对的差异**：先取两个来源的并集接入，差出来的记录记 `verified=false`。宁可多标待核实，也不漏标。差异查明之前 V5g 不关闭。查明后，在名单的 `sources` 里写明结论。
    4. **名单的时点与字段名（T-R12i）**：
       - 名单行不加可见时间字段。A+B、A+H 的对应关系在 `effective_from`（B 股或 H 股上市日）当天就已公开，按生效区间取用不构成前视。
       - 重算时用最新版名单，这是更正历史，不是使用未来信息；回测报告要写明所用的 `share_class_list_version`。
       - 配对代码的字段名定为 `paired_code`，交易所代码按原样记录（例如 H 股 `00939`，B 股 `900901`），不加市场后缀。另加 `paired_market`，取值 `HK` 或 `SH`、`SZ`。
  - **T-R13 补充裁定（v0.2.9 内，架构师；对应研究员 reports/T-R13.md 第 17–20 行的 3 个问题，以及 T-B05-20261107 的 p13 实测）**：
    1. **V5h 可以按“确认没有这类字段”关闭**。
       - 关闭条件：抽样的全部财报和 capital 响应里都没有字符串值，也没有任何以币种、单位为含义的字段。
       - 抽样范围：income、balance、cashflow、capital 四个接口，每个接口至少覆盖普通股 600519、银行 000001、保险 601318、A+B 公司 000550。
       - CDR 不在 F43、F48 的池和 S2 的池 U 内，所以不要求补 689009 的 income 和 cashflow；689009 的 balance、capital 已有，够用。
       - 后端更正探针结论：删掉 hbzj、yfbzj 等业务科目的误命中；逐个接口写出“检查了哪些字段、没有字符串值”；结论写“没有币种、单位字段，只靠数量级不连续检查”（B5 `unit_mismatch` 按此执行）。
       - 写结论不需要字段含义的文档依据，因为结论是“没有”，不是解释某个字段的含义。
       - 后端（T-B05）把结论写进 `docs/mairui-verified.md` ⑨（由架构师代为提交），V5h 随之关闭。
    2. **`cdr_unit` 逐只清除，不对全部 `type = cdr` 推广**。
       - 689009 已确认按 CDR 份数计：总市值 = `c × zgb`，可以清除它的 `cdr_unit`。
       - 其他 `type = cdr` 的证券保留 `cdr_unit`，直到同样对照过巨潮披露的 CDR 份数。
       - CDR 不进 S2 的池，保留的标记不阻塞切换。V5j 作为 S1 关闭项，以 689009 的实测为准关闭。
       - 后端以后加证券级的自动对照：`zgb` 与最近一期披露的 CDR 份数，通过后清除标记。
    3. **份数判定的容差由架构师规定**。
       - 判为“按 CDR 份数计”的条件：|zgb − 披露的 CDR 份数| / 披露的 CDR 份数 ≤ 0.1%。
       - 判为“按基础股份计”的条件：zgb 与“披露的 CDR 份数 ÷ 每股基础股份对应的 CDR 份数”同样相差不超过 0.1%。
       - 两条都不满足：保留 `cdr_unit`，并告警 `data_quality`。
       - 本次两个检查点相差 −3 份和 +2 份，约为 4×10⁻⁹ 和 3×10⁻⁹，满足第一条。
    4. **探针和名单的待办（后端）**：
       - p13 分析里 V5i 回填行的 `visible_from` 写成了休市日 2024-05-01，要改成 `next_trading_day(截止日)` 09:30 并定向验证。修好之前，只签收 V5i 的数据口径（季末行确实存在回填），不签收端到端的可见时间实现。
       - 000550 没有同期报告可以对照，由 T-B05 补上并记录局限，不阻塞上一条。
       - 探针里的 `v5g_close` 改成和 feature_spec 一致的四项条件。
       - 按 T-R12h、T-R12i 建 `config/share_class_list.yaml` 并接入。
       - 名单来源和 211/209 的处理不变（T-R12h 第 2、3 条）：先取并集并标 `verified=false`，逐条用巨潮或港交所披露核实；全部为 `verified=true` 且差异查明之后，V5g 才能关闭。
  - **T-R14 补充裁定（v0.2.9 内，架构师；对应研究员 reports/T-R14.md 第 9–16、20 行）**：
    1. **未核实的记录照样导入，从宽打标**。283 条全部导入，导入只看 `verified=true` 是不行的，这一点不变（T-R12h 第 2、3 条，宁可多标）。
       - `verified=false`、`effective_from` 为空的记录，从该证券最早有数据的日期起就打 `non_a_share_capital`。有 `candidate_date_unverified` 的，也不用它来缩短打标区间。
       - 名单增加字段 `candidate_date_unverified`，仅作说明，不参与计算。
    2. **H 股日期冲突以港交所为准**。巨潮公告的日期和港交所《市場資料》新上市表的日期不一致时，取港交所的日期，同时把两处证据都记下来。000513 取 2014-01-16，记 `verified=true`。
    3. **转板**：`effective_from` 取 H 股在香港首次挂牌的日期，创业板也算。转主板不重新计日期，原创业板代码写进 `evidence`。002672 补上创业板的首次上市日后，才能记 `verified=true`。
    4. **换码证券**：B 股或 H 股只要是同一只证券连续存续，只是换了代码，`effective_from` 就取这只 B 股或 H 股最早的上市日，不取换码日。
       - 001872/201872 要用巨潮的换码或吸收合并公告证明 201872 就是原 200022 连续存续，证明后 `effective_from` 取 1993-05-05，并记 `verified=true`。
       - A 股代码换码之前的那段历史，由证券主数据的代码映射（T-B52 renames 和代码映射）接上，名单不再为旧代码单独加行。
       - 如果公告表明是新发行，而不是连续存续，就取新代码的上市日。
    5. **`effective_to` 与“现时资料”的局限**。巨潮公司概况只能证明在 `as_of` 这一天配对仍然有效，所以：
       - 现有记录的 `effective_to` 为空，可以算核实过，前提是 `as_of` 当天的概况仍显示这一配对。名单文件头写明 `effective_to_basis=current_profile@as_of`。
       - 配对已经终止的公司在现时概况里查不到，必须另外补行并写上 `effective_to`。至少要覆盖三类：B 转 H（如万科、中集）、H 股私有化或退市、B 股退市或回购注销。来源用巨潮公告或港交所公告。
       - 这项覆盖没做完之前，回测报告里要写明“终止配对未覆盖”，`basis` 记 `share_class_history=partial`。
    6. **209 名单拿不到时，V5g 第 3 条“差异查明”改用一手全集扫描**。Wind 的 209 家和 204 家只是二手统计，口径和截止日都不一致，不作为关闭依据。要做的是：
       - 对 `as_of` 当天全部上市 A 股逐只拉巨潮公司概况，取出 HSECCODE 和 BSECCODE 不为空的集合；
       - 和名单做双向比对：扫描到但名单里没有的，补进名单；名单里有但扫描不到的，查明原因，比如已终止的就补 `effective_to`，误配对的就删掉，并在 `sources` 写明结论。
       - 211 对和 209 对的数量差，只在 `sources` 里记一句口径说明，不再要求逐项解释。
       - 600190/900952 等接口一直出错的证券，在扫描结论里单列，逐只人工核实。
       - 这次扫描只用巨潮的公开接口，不调用麦蕊，并且要限速。
    7. **V5g 关闭条件（修订后）**：
       - 名单已经接入；
       - `zgb` 的口径已对照巨潮核实（T-R12b）；
       - 名单内所有记录都是 `verified=true`；
       - 第 6 条的全集扫描和双向比对已完成；
       - 第 5 条的终止配对已覆盖。
       其中“终止配对已覆盖”这一项是切换门槛（S1）的条件，不影响后端先接入名单。
  - **补充规则（`feature_spec.md` §7A.0 / §13 A5，4 条）——【已确认 v0.2.9 内，架构师 T-R12】**，并入 T-B55：① 首次全量回填写入、`plrq` 早于回填日的行只按 `plrq` 计算，标 `basis.pit_basis=plrq_only`；② 同一 (code, report_type, jzrq) 的两行 `available_from` 相同 → 取 `first_seen_at` 较晚者，仍无法区分且数值不同 → 该分量 `null` 并告警 `data_conflict`；③ E(P−4) ≤ 0 按缺失处理（`roe_basis=single_period`）；④ 现金流比的分子、分母用同一个 P，不各自回退。说明：P 按“该键所需分量都可见且非空”逐期回退，所以同一 T 下不同键（如 `pe_ttm` 与 `ocf_to_np_ttm`）的 P 可以不同，各自记入 `basis.period`。
  - **线上切换**：条件与阈值以 `feature_spec.md` §7C（S1–S6）为准——【已确认 v0.2.9 内，架构师 T-R12】；本文不重复。保险识别（V5e）若 T-B05 确认麦蕊没有申万二级，按配置中的保险证券名单识别（名单注明来源），以此关闭 V5e，不因缺申万二级而阻塞切换。等待期的产品取舍见第 9 节问题 93。
  - 幸存者偏差：已退市证券的财报接口返回 404，历史截面缺这些证券；回测报告必须带 `survivorship_bias=true` 标记，不能当作无偏结果。
  - 麦蕊历史因子值只作对照：按截面报告与自算值的 Spearman ρ，不作为门禁。
- **因子池排除**：停牌、ST/*ST、退市整理、上市不满 60 个交易日的次新股（阈值可配置）不进入截面排名和分位计算。**例外**（v0.2.9 内，T-O11 评审裁定）：分类器特征的 `rank_pct_universe`（如 `f.volatility_20d` 的全市场分位）不排除 ST、*ST、退市整理股，只要求上市满 20 个交易日（并排除北交所与当日停牌）；定义以 `docs/strategies/feature_spec.md` §1.4 为准。
- **统一复权口径**：价格类特征统一用**前复权**（`qfq`，用于趋势和指标）。收益计算用**后复权或总收益口径**（`hfq`，避免除权缺口），并在 `feature_catalog.adjust` 中标明；1 分钟数据麦蕊只有不复权（`n`）【文档已列·待 T003 验证】，跨除权日的日内计算要截断。
- **单因子检验**（内部评估模块，2.12.4）：IC 和 RankIC（均值、IR、t 值）、分组单调性（5 组）、换手率、衰减（1/5/20 日 IC 曲线）。
- **去冗余**：同一模板内的因子两两 |Spearman ρ| > 0.8 时提示合并；G6 同时检查模板之间命中集合的重合度。
- **中性化**：横截面使用前做行业（申万一级）和市值（对数流通市值）中性化（回归取残差）；中性化前后的值都保存，`feature_catalog` 中标明。
- **滚动样本外验证**：时间序列 K 折，按时间切块，每块之间留出等于持有期的 embargo；按 2.13 的真实成本计算（内部评估）。
- **上线后监控**：每日计算滚动 60 日 RankIC。IC 衰减到发布基线的 50% 以下时进入 2.8.2 的健康度机制（观察 → 提示复审），不单独另建一套机制。

#### 2.12.2 事件驱动
- **事件定义**：用枚举加规则精确定义，存入 `event_definitions`，版本化。每个事件规定：数据源（公告类型 `lx`、标题关键词正则、业绩预告类型、龙虎榜、解禁、涨跌停池等）、方向（利好 / 利空 / 中性）、严重级别、去重窗口。
  - MVP 的事件类型：业绩预增、预减、扭亏、预亏；减持计划；增持或回购；问询函或关注函；立案调查；退市风险警示；限售解禁；重大资产重组（停复牌）；龙虎榜上榜；连板与炸板。
- **最早可交易时刻**：由公告时间戳决定，规则如下：
  - 交易时段内发布：下一根 1 分钟 bar；
  - 15:00 之后或开盘前发布：下一交易日开盘；
  - 9:15–9:25 集合竞价期间发布：当日开盘；
  - 公告时间只有日期时：按"盘后"处理（保守）。

  麦蕊公告字段 `t` 的精度【待 T003 验证：T-B05】。所有事件规则都按这一时刻对齐，不允许用公告当日收盘价作为入场价。
- **事件研究**（内部评估）：以沪深300或行业指数为基准，计算 1/5/20 日异常收益 AR 和 CAR（市场调整模型），报告均值、中位数、t 值、胜率和 **n**。
- **提前反应（拥挤）检查**：如果公告前 [-5, -1] 日的 CAR 超过阈值（默认 +8%），给该事件信号加 `crowding` 标记，表示"可能已提前反映"。这一检查也用于产品中的候选信号（作为反证）。
- **AI 抽取的事件**：LLM 只基于公告标题做分类（`announcement_title_digest`），输出事件类型加 `confidence`，并保存原标题和原文链接。
  - 属于 `estimate`，按 P1b 只能作为辅助参考，不能单独触发计划。
  - 高影响类型（立案、退市风险、重大重组）**全部**进入人工复核队列；其他类型按 10% 抽样复核。
  - 复核结果用于评估抽取准确率（附 n）。

#### 2.12.3 样本量必须随统计一起展示
- 任何胜率、IC、异常收益、盈亏比，在 API 和 UI 中都是统一结构 `{value, n, window, small_sample: bool}`：
  - 5 ≤ n < 30：显示"样本少"标记（`small_sample=true`）；
  - n < 5：不显示数值（`value=null`），只显示"样本不足（n=3）"。
  - 这是**展示阈值**；降权门槛 n ≥ 20（2.5.7）与 `published` 的模拟样本门槛 n ≥ 20（2.5.13）是另外的规则，不受影响（2.5.14 H⑧）。
- 契约测试和前端组件测试都会检查：缺少 `n` 判为失败（T-T17）。

#### 2.12.4 内部评估模块（仅管理员可见；含历史验证与抗过拟合；**已定：第三阶段实施，第 9 节问题 26；用户可见范围按方案 A，见 C(6)**）
- **定位**：在不违背"产品内不做回测"的前提下，为管理员提供因子、事件和模板参数的历史验证。**结果永不展示给终端用户**，也不出现在任何用户接口、通知或 LLM 输入中；只用于：
  - ① 晋级审核（G6 的附加报告）；
  - ② 默认参数的选择；
  - ③ 发布后的健康度复验（2.8.2）。
- **范围**：
  - 单因子检验（2.12.1）；
  - 事件研究（2.12.2）；
  - 模板的轻量历史模拟（使用 2.13 的交易规则：T+1、费用、涨跌停不可成交、跳过停牌）；
  - **参数稳健度排序**：时间序列 K 折（默认 K=5，带 embargo），每折计算样本外得分（扣除成本后的平均超额收益，或 RankIC）。`robustness = 0.6 × 各折中位数 + 0.4 × 最差一折`。只在参数 schema 的范围网格内搜索，候选组合不超过 50 个，以防数据挖掘。
  - **发布基线与每日复验**：发布时记录稳健度基线；之后每日盘后用滚动窗口复验，结果输入 2.8.2 的健康度状态机。
- **部署位置**：`src/backend/app/evaluation/`（同一代码库，复用 `features`、`market_rules`），作为独立的 Celery 队列 `evaluation`，在夜间低峰执行，单独限流（默认占 `per_minute_budget` 的 30%）。接口为 `/api/v1/admin/evaluation/*`，仅 admin；结果表放在 `evaluation` schema。
- **数据需求与配额**（依据官网文档；深度与口径以 T-B05 实测为准）：

| 数据 | 接口 | 深度 | 一次性拉取量 |
|---|---|---|---|
| 日 K | `/hsstock/history/{code}/d/{adj}` | "日线以上为上市以后所有数据"【文档已列·待 T003 验证】 | 约 5,400 次 |
| 1 分钟 K | Pro `/hsstock/history/full/{code}/1/n`（按年分片） | 普通历史分时说明为"分钟级最近 3 年以内"；Pro 完整历史的年份范围【待 T003 验证】 | 仅跟踪池 1,500 只 × 3 年 ≈ 4,500 次 |
| 因子截面 | `/factor/batch`（`trade_date` 可选，每次 50 股 × 20 因子，计 10 次） | 历史截面深度与是否按时点计算【待 T003 验证】。**`trade_date` 语义（v0.2.9 内，评审 66f1906 裁定）**：实测请求 20260417 返回的是 20260130 的截面，`trade_date` 不保证就是返回数据的日期；入库与按时点计算一律以响应里每条记录自带的数据日期为准，没有这个字段或与请求日期不一致时，记为 `as_of_mismatch` 告警，该批不用于回填；T-B05 要实测并写进 `docs/mairui-verified.md` | 全市场 85 因子约 5,400 计数/日 × 242 日 ≈ 131 万计数/年；在默认 3,000 计数/分钟、评估队列只占 30% 的条件下约 24 小时，分多个夜间完成；钻石版每日不限【文档已列·待 T003 验证】 |
| 财报 | `/hsstock/financial/*`，带 `plrq` | "全部数据"【文档已列·待 T003 验证】 | 约 5,400 × 4 次 |

- **与 G6 的关系**：
  - **默认（未获批）**：G6 只统计触发率、覆盖率和重合度，不算收益（2.5.0B）。
  - **获批后**：G6 增加一份**仅管理员可见**的内部评估报告（OOS 稳健度、单因子 IC、事件 CAR，均附 n），作为 G7 审核的参考。可设硬门槛，例如稳健度 ≤ 0 时不得进入 `simulating`；是否硬性由管理员配置。
  - 无论哪种情况，产品对用户展示的表现只来自上线后的模拟跟踪。
- **利弊**：
  - **利**：减少"上线才发现无效"的策略；默认参数有依据；能及早发现因子衰减；成本低（同库、同代码、夜间运行）。
  - **弊**：
    - 有过拟合和"回测美化"的风险（以 K 折加最差折权重、网格上限和 embargo 缓解）；
    - 历史因子是否按时点计算未核实，有前视偏差风险（先用自有落库数据）；
    - 增加实现与测试工作量（约 1.5–2 周）；
    - 合规上要防止内部结果被当作宣传（结果在接口层隔离，T-T18 测试保证用户端不可达）。
- **建议**：**同意启用，放在第三阶段（M2 之后），先只做单因子检验和事件研究，再做参数稳健度。**

### 2.13 A 股交易规则模块（共享，`app/market_rules`）
模拟跟踪（2.8）、计划草案的数量与价格计算（2.5.8）、可执行性检查（2.5.9）和内部评估（2.12.4）**共用同一个模块**。规则按**生效日期分段**存于 `config/market_rules.yaml` 并入库（`market_rule_versions`），回看历史时使用当时有效的规则。思路参考 OSkhQuant 的成本与整手规则，**不拷贝其代码**（该项目为 CC BY-NC）。

| 规则 | 内容（2026-11-01 网上核实；以交易所最新规则为准；规则只建模到 2023-04-10，更早的回看标“交易规则未建模”，见 `market_rules.yaml` `modeled_from`） |
|---|---|
| T+1 | 当日买入的股票下一交易日才可卖出；可卖数量 = 昨日持仓 − 今日已卖 |
| ETF 当日回转 | 交易所允许部分类别 ETF（债券、货币、黄金、商品期货、跨境等）当日回转，但需要可靠的 ETF 类别数据源。**在 `market_rules.yaml` 的 `t0_round_trip.data_source` 选定并接入前，所有 ETF 一律按 T+1**（v0.2.9 内，T-O11 评审裁定）；实现必须以 `data_source` 非空为前提：为 null 时即使调用方传入类别也按 T+1。来源：麦蕊优先，但麦蕊公开文档只有“基金-ETF基金行情/净值”等大类，未见 ETF 子类字段【待核实，T-B05 实测】；备选为交易所公开基金列表的分类字段【待核实】。选定后由架构师裁定、后端接入 |
| 涨跌幅 | 主板 10%；创业板、科创板 20%；北交所 30%；**沪深主板 ST/*ST 自 2026-07-06 起为 10%（此前为 5%）【已定，已核实：上证发〔2026〕41 号、深证上〔2026〕551 号，2026-07-06 施行】**；创业板、科创板风险警示股票 20%；北交所风险警示股票 30% |
| 无涨跌幅限制 | 沪深注册制新股上市前 5 个交易日；北交所新股上市首日；退市整理期首日（以交易所规则为准）。这些情形下有盘中临时停牌机制（较开盘价 ±30%、±60% 各停牌 10 分钟） |
| 涨跌停价计算 | 前收盘价 × (1 ± 比例)，按四舍五入取至价格最小变动单位（A 股 0.01 元）。**沪 3.3.17、深 3.3.19 已核实**（T006b），含两条边界规则：① 计算出的涨跌停价与前收盘价之差不足一个价格最小变动单位时，按前收盘价 ± 0.01 元；② 计算结果低于 0.01 元时取 0.01 元 |
| 交易单位 | （v0.2.9 内，T-T25 按 T-R10 同步；依据 `docs/strategies/market_rules_T-R10.md`，键见 6.1 `lot`）**买入**：沪深主板、创业板、ETF（含科创板 ETF，科创板 ETF 不适用 6.7 条）为 100 股（份）的整数倍（沪/深 3.3.8，已核实）；科创板股票/CDR 单笔 ≥ 200 股，买卖均适用（沪 2026 第 6.7 条、2023 第 6.1.7 条，已核实），超出部分按 1 股递增【部分核实：规则无明文，依沪 6.1/6.7 与上交所投教材料，T-R10】；北交所单笔不低于 100 股、按 1 股递增【未核实；V1 不扫描北交所，C(8)】。**零股卖出**：余额不足一个申报单位的部分须一次性申报卖出（已核实）；阈值科创板为 200（`star_odd_lot_threshold`），其他板块为 `buy_lot`。V1 判定（设可卖数量为 A）：主板/创业板/ETF 卖出数量 q 合规当且仅当 q ≤ A 且（q 为 100 的整数倍或 q = A）；科创板 A ≥ 200 时 200 ≤ q ≤ A，A < 200 时只能 q = A；用可卖数量而非持仓余额判定是实现约定（未核实），主板“整手连带零股”（如持有 250 卖 150）原文未写明，V1 不允许（第 9 节问题 86）。**单笔申报上限**（已核实）：竞价单笔 ≤ 100 万股（份）（沪/深 3.3.9）；科创板限价 ≤ 10 万股、市价 ≤ 5 万股、盘后固定价格 ≤ 100 万股（沪 2026 第 6.7 条；2023 段盘后为第 6.2.6 条）；创业板限价 ≤ 30 万股、市价 ≤ 15 万股（深 3.3.9）。计划草案数量超过适用上限时截断并提示（本产品不下单，按限价口径计算） |
| 交易时段 | 集合竞价 9:15–9:25；连续竞价 9:30–11:30、13:00–14:57；收盘集合竞价 14:57–15:00 |
| 费用 | 印花税：**仅卖出**，0.05%；过户费：双向 0.001%；佣金：双向，按用户费率，单笔最低 5 元（券商常见做法，以用户实际为准，可由导入的成交反推）；滑点：模板参数，默认 0.1% |
| 冲击成本 | 按参与率（**成交额口径**：拟成交额 = 计划数量 × 参考价，÷ 近 20 个**有效**交易日日成交额均值，停牌日不计；T-A02 已定，与 `_template.md` §18 一致）分 5 档的确定性估算：I1 ≤ 0.1% → 0 bp；I2 ≤ 0.5% → 5 bp；I3 ≤ 1% → 15 bp；I4 ≤ 2% → 30 bp；I5 > 2% → 60 bp。【编排者默认，初值待校准】（第 9 节 C(7)）；`epistemic_type=estimate`；计划草案（2.5.8）、模拟跟踪（2.8.1）、内部评估共用，结果写入卡片的 `costs.impact_*` 展示 |
| 不可成交 | 买入方向遇一字涨停（或开盘即涨停未打开）不可成交；卖出方向遇一字跌停不可成交；停牌日跳过 |
| 风险警示股票其他约束 | **单只当日累计买入 ≤ 50 万股：只适用主板与创业板**（沪第 4.4.10 条、深第 4.5.4 条均已核实，T006b）；**科创板不适用**（沪第 4.4.1、6.14 条）；北交所 V1 不扫描（C(8)）→ 计划草案数量上限截断到 50 万股并提示（G-01 已阻断 ST 买入方向，通常不触发，作防御性校验）。**只能限价申报：只适用沪市**（沪第 4.4.9 条；深交所 2026 规则未见同类条款）→ 本产品不下单，只在沪市证券的草案与通知文案提示“请使用限价委托”（`market_rules.yaml` `risk_warning`，T-A02/T-A03） |
| 时点 | 数据可用时刻精确到分钟（2.12.1），不允许使用未来数据 |

- `config/market_rules.yaml` 由**后端**按 6.1 创建和修改（6.1 通用规则）；本节与 6.1 是规则口径的唯一出处，T-A03 的改动由后端同步到该文件。
- 规则模块有独立的单元测试（T-T19），用交易所示例和边界值验证：涨跌停价（含 3.3.17/3.3.19 两条边界规则）、风险警示买入上限只作用于主板与创业板、限价提示只作用于沪市、整手、费用的最低收费、T+1 可卖数量、2026-07-06 前后 ST 比例的切换（2026-07-03 为 5%、2026-07-06 为 10%）、风险警示股票 50 万股买入上限截断、`modeled_from` 之前返回“规则未建模”；（v0.2.9 内，T-T25）另加：零股卖出（主板 150 股可卖 100 或 150、不可卖 50；科创板 A=250 可卖 200–250、A=199 只能卖 199）、科创板 ETF 按 100 份整数倍、单笔上限截断（全市场 100 万；科创板限价 10 万/市价 5 万；创业板限价 30 万/市价 15 万）、`t0_round_trip.data_source` 为 null 或空串时所有 ETF 返回 T+1。

---

## 3. 数据模型（验收项 3）

### 3.1 核心建模原则
1. **认识论类型字段**：所有"论断/证据/数值陈述"统一存为 `claims` 行，字段 `epistemic_type`：
   - `fact` 事实：来自数据源或用户确认的可核对信息（必须有 `source_ref`：数据源接口+时间，或"用户录入"）；
   - `estimate` 估算：基于事实的计算/推断，带方法与参数（如"按近 60 日波动率估算单日波动 ±3%"）；
   - `hypothesis` 假设：尚未验证的判断（"产能释放将带动毛利率回升"），需有验证方式/验证日期；
   - `execution` 实际成交：用户真实交易记录（只能来源于 `trades`）。
   另有 `source_kind ∈ {market_data, disclosure, user_input, system_calc}` 与 `confidence`（仅对 estimate/hypothesis，用户自填 low/medium/high）。
2. **只追加 + 版本**：`research_candidates`、`action_plans`、`reviews` 采用"头表（当前指针、状态）+ 版本表（不可变）"；版本表行禁止 UPDATE/DELETE（数据库触发器强制）。
3. **数据快照**：每个版本创建时生成 `data_snapshots`，记录当时引用的数据项的值、数据源、`data_as_of`（数据本身对应的时点）、`fetched_at`（我们拿到的时间）。回看时只读快照，不读最新行情。
4. **成交只追加**：`trades` 不允许修改；更正用 `void`（作废标记 + 原因）+ 新记录；持仓由成交推导。
5. **个人数据与行情数据分 schema**：`app`（用户数据，含 `user_id`，所有查询强制按用户过滤）与 `market`（~~全站共享~~ v0.2.6 起麦蕊来源的行带 `source_licence_id` 按证书隔离，2.1B；只有证券公开主数据全站一份，第 9 节问题 51）。
6. 时间：数据库统一 `timestamptz`（UTC）；交易日用 `date`（Asia/Shanghai 口径）；金额用 `numeric(20,4)`，API 中以字符串传输。

### 3.2 实体关系（概要）

```
users 1─1 user_profiles(版本化)
users 1─n accounts 1─n trades ; accounts 1─n opening_positions ; accounts 1─n cash_movements
users 1─n account_reviews(管理员审核历史) ; users 1─n login_attempts ; audit_logs(全站)
accounts 1─n import_batches 1─n import_files ; import_batches 1─n import_rows ─> trades / account_events
accounts 1─n account_events ; accounts 1─n holdings(由 opening_positions+trades+account_events 重建)
users 1─n watchlist_items ─> securities
strategies 1─n strategy_versions ─> dimension_definitions ; strategy_cards 1─n strategy_card_versions ─> strategy_versions(晋级) ; users 1─n strategy_instances ─> strategy_versions ; symbol_horizon_assessments ─> horizon_classifier_versions
strategy_instances 1─n candidate_signals(不可变正文) 1─n candidate_signal_events ; candidate_signals 1─n non_executable_reasons 1─n reason_status_events ; candidate_signals n─n plan_drafts 1─0..1 action_plans ; strategy_versions 1─n strategy_lifecycle_events / strategy_promotion_reviews / strategy_health_daily ; users 1─1 risk_control_settings ; users 1─n risk_events
users 1─n suggestion_threads 1─n suggestions(不可变) ─> data_snapshots / engine_policies ; suggestions 1─n suggestion_tracking ; suggestions 1─n suggestion_user_actions
users 1─n daily_reports 1─n daily_report_items ─> suggestions ; signal_states(证书内共享) / user_signal_states 1─n signal_events
strategy_tracking_stats / user_strategy_weights ─> strategy_versions ; feature_catalog ─> market.feature_bars_daily ; market_rule_versions ; event_definitions ─> market.market_events ; llm_providers 1─n llm_models ; llm_task_routes ─> prompt_templates ; llm_calls
users 1─n notifications 1─n notification_deliveries ; users 1─n notification_channel_bindings ; plans 1─n plan_entitlements ; users 1─n user_subscriptions
users 1─n research_candidates 1─n candidate_versions ─> data_snapshots
users 1─n action_plans 1─n plan_versions ─> data_snapshots ; plan_versions 1─n plan_conditions
claims(证据) n─n candidate_versions / plan_versions / reviews  (经 claim_links)
users 1─n alert_rules (可来源于 plan_condition) 1─n alerts ─> notifications
users 1─n reviews 1─n review_versions ─> plan_version / trades / data_snapshots
market.* (hypertable 标 *) : securities, trading_calendar, daily_bars*, minute_bars*, realtime_quotes*, financial_reports,
           fund_flows*, factor_values*, feature_bars_daily*, announcements, qa_items, market_events, raw_payloads ; ingest_request_log* ; evaluation.*（问题 26）
```

### 3.3 主要表定义（字段为契约级，DDL 由后端在 Alembic 中实现）

**用户与画像**
| 表 | 关键字段 |
|---|---|
| `users` | id(uuid), username(unique, 小写归一, 4–32 位 `[a-z0-9_]`), password_hash(argon2id), display_name, role(user/admin), status(pending/approved/rejected/disabled/deleted), apply_note(注册时可选填写的申请说明), email(可选, 仅用于通知), failed_login_count, locked_until, password_changed_at, created_at, reviewed_at, reviewed_by, deleted_at |
| `account_reviews` | id, user_id, action(approve/reject/disable/enable/reset_password), reason, admin_id, created_at — 只追加，审核历史 |
| `login_attempts` | id, username_tried, user_id(nullable), ip_hash, success, failure_reason, at — 用于限速、锁定与审计（保留 180 天） |
| `audit_logs` | id, actor_id, actor_role, action, target_type, target_id, detail(jsonb), ip_hash, at |
| `invite_codes` | id, code_hash(unique；`HMAC-SHA256(APP_MASTER_KEY, 归一化邀请码)`，明文不入库), created_by(admin), created_at, expires_at, max_uses(V1 恒 1), used_count, used_by(nullable), used_at, revoked_at, revoked_by, bound_username(nullable，绑定后只有该用户名可用), note — 状态由字段推导（active/used/expired/revoked），不物理删除；规则见 6.1 `config/auth.yaml`（T-A05） |
| ~~`consents`、`legal_documents`、`legal_document_events`、`questionnaires`、`risk_assessments`~~ | **T-A06 作废（用户 2026-11-02 决定：不做同意流程与风险测评）**：不建这些表；已建的 `consents` 由新迁移删除（契约 v0.2.5） |
| `user_profiles` | id, user_id, version_no, horizon_pref(text[]，取值为 `horizon` 枚举), effort(low/medium/high，nullable), risk_tolerance(1–5，nullable), experience(novice/intermediate/advanced，nullable)（三者均为用户自报、选填，未填不封顶；T-A06 删除 T-A05 加的 assessment_id、questionnaire_version）, max_single_position_pct(decimal), capital_range(enum: <10万/10–50万/50–200万/>200万，选填), max_drawdown_pct(选填), focus_areas(text[]，选填), confirmed_at, created_at — **只追加**，最新版本为当前画像。**前五个字段与契约 `/me/profile` 一一对应（契约为准，T-A02）**；原 `horizon(short/medium/long)` 改为 `horizon_pref`，原 `weekly_hours` 由 `effort` 取代；选填字段契约暂未暴露，只供内部使用 |

**账户/持仓/成交**
| 表 | 关键字段 |
|---|---|
| `accounts` | id, user_id, name, broker_label(自由文本，不存券商账号), base_currency('CNY'), created_at, archived_at |
| `opening_positions` | id, account_id, security_code, quantity, cost_price, as_of_date, epistemic_type='fact', source_kind='user_input' |
| `cash_movements` | id, account_id, kind(deposit/withdraw/dividend/fee/adjust), amount, occurred_at, note |
| `trades` | id, account_id, user_id, security_code, side(buy/sell), quantity, price, amount(成交金额), commission, stamp_tax, transfer_fee, other_fee, net_amount(发生金额), traded_at, trade_date, broker_trade_no(成交编号, 可空, 不透明字符串), order_no(委托编号, 可空), declare_no(申报序号, 可空), cash_balance_after(剩余金额, 可空), shareholder_code_hmac, shareholder_code_masked, plan_version_id(nullable), source(manual/import/csv_template), import_batch_id, import_row_no, dedup_key(unique per account), voided_at, void_reason, replaces_trade_id, created_at — `epistemic_type` 恒为 `execution`（手动与导入均是实际成交事实，来源不同由 `source` 区分） |
| `account_events` | id, account_id, kind(dividend/bonus_share/rights/transfer_in/transfer_out/ipo_allot/fee/interest/other), security_code, quantity, amount, occurred_on, import_batch_id, dedup_key — 交割单中非买卖的流水（分红、送转、新股中签、银证转账等），用于持仓与现金重建 |
| `holdings` | **由成交重建的派生表**（非用户直接编辑）：account_id, security_code, quantity, avg_cost(移动加权), realized_pnl, last_trade_at, rebuilt_at, rebuild_batch_id；每次导入确认/手动增删/作废后对受影响账户全量重放 `opening_positions + trades + account_events` 重建 |
| `import_batches` / `import_files` / `import_rows` | 见 3.5 节 |
| `broker_position_snapshots` | id, account_id, import_batch_id, as_of, currency, cash_balance, cash_available, cash_withdrawable, market_value_ref, total_assets_ref, pnl_ref, version_no, created_at — 券商口径快照，`epistemic_type=fact`，只追加 |
| `broker_position_snapshot_items` | id, snapshot_id, security_code, quantity, sellable_quantity, broker_cost_price, last_price_ref, market_value_ref, unrealized_pnl_ref, unrealized_pnl_pct_ref, shareholder_code_hmac, shareholder_code_masked |
| `reconciliation_runs` / `reconciliation_items` | run: id, account_id, snapshot_id, trigger, status(ok/has_diffs), created_at；item: id, run_id, kind(quantity_mismatch/missing_in_broker/missing_in_ours/cost_differs/cash_gap/cash_chain_break), security_code, ours(jsonb), broker(jsonb), diff, possible_causes(text[], hypothesis), suggested_actions(text[]), resolution(jsonb: {action, reason, by, at}) |

**观察与研究**
| 表 | 关键字段 |
|---|---|
| `watchlist_items` | id, user_id, security_code, group_name, note, added_at, removed_at |
| `strategy_runs` | 取代早先的 `methods`/`screen_runs`；扫描批次（触发时间、universe、feature_set_version、模板版本集合、耗时、产生的候选数）。逐股结果写入 `candidate_signals` |
| `research_candidates` | id, user_id, security_code, origin(strategy_screen/suggestion/manual/from_stock), strategy_run_id, suggestion_id, status(researching/watching/dropped/planned；`planned` 只在计划草案确认后由系统写入), current_version_id, created_at |
| `candidate_versions` | id, candidate_id, version_no, thesis(text), conditions_to_hold(jsonb), counter_evidence(jsonb), fit_assessment(jsonb), decision(continue/watch/drop/null), decision_reason, snapshot_id, created_at, created_by — **不可变** |

**证据**
| 表 | 关键字段 |
|---|---|
| `claims` | id, user_id(null=系统生成；T-A11 / 契约 v0.2.9：为某用户研究候选生成的、或用到某用户证书数据的 claim 一律写该用户 user_id，是否系统生成看 source_kind), security_code, statement(text), epistemic_type, source_kind, source_ref(jsonb: {provider, endpoint, params, fetched_at, url}), value(jsonb, 可选: {metric, number, unit, as_of}), method_note(估算方法), verify_by(date, 假设的验证日期), confidence, created_at — **不可变**（更正=新 claim + `supersedes_claim_id`） |
| `claim_links` | claim_id, target_type(candidate_version/plan_version/review_version/alert), target_id, role(reason/counter/risk/invalidation/outcome) |

**行动计划**
| 表 | 关键字段 |
|---|---|
| `action_plans` | id, user_id, security_code, account_id, candidate_id(nullable), status(active/triggered/done/cancelled；v0.2.9 内前端待定裁定，契约 §3 `plan_status`、§7.7B；原拟的 draft/executed/invalidated/closed 不用：草案另存 `plan_drafts`，执行与失效由用户关闭为 done/cancelled，问题 80), current_version_id, created_at |
| `plan_versions` | id, plan_id, version_no, action(buy/add/hold/reduce/exit/wait), rationale(text), size_amount, size_pct_of_assets, max_loss_amount, risks(text), review_date, change_reason(新版本原因), completeness(jsonb: 检查结果), snapshot_id, created_at — **不可变** |
| `plan_conditions` | id, plan_version_id, kind(trigger/invalidation), type(price_above/price_below/pct_change/indicator/event/date/custom), params(jsonb), description, epistemic_type(通常 hypothesis) |

**提醒**
| 表 | 关键字段 |
|---|---|
| `alert_rules` | id, user_id, origin(plan_condition/holding_event/user_custom), plan_condition_id, security_code, type, params, enabled, cooldown_minutes, created_at |
| `alerts` | id, user_id, rule_id, security_code, severity(info/attention/important), what_happened(jsonb: 事实+source_ref), affected(jsonb: [{plan_id, plan_version_id, condition_id}]), checklist(jsonb), status(new/read/checked/acted/dismissed), triggered_at, data_as_of, snapshot_id, dedup_key |


**策略库（版本化配置，2.5）**
| 表 | 关键字段 |
|---|---|
| `dimension_definitions` | key(technical/capital/fundamental/sentiment/sector_market/news) PK, name, description, sources(jsonb：接口/因子清单), coverage_gaps(jsonb), updated_at |
| `strategies` | id, key(unique), owner_user_id(null=内置), name, horizons(text[]：intraday_t/short/swing/long), copied_from_version_id, current_version_id, status(active/archived), created_at |
| `strategy_versions` | id, strategy_id, version_no, config(jsonb：parameters / rules[{id, dimension, role, expr, params, weight, required_data}] / dimension_view_thresholds / action_map / stops / applicability / failure_modes / fit_dimensions), config_hash, changelog, published_by, published_at — **发布后不可变（触发器）**；unique(strategy_id, version_no) |
| `strategy_rules`（物化视图） | strategy_version_id, rule_id, dimension, role, expr, weight, required_data — 由 config 展开，供检索"哪些策略用到某因子/某维度" |
| `engine_policies` | id, version_no, config(jsonb：动作映射通则、置信度公式、维度观点阈值、分歧检测规则), published_at — 不可变 |
| `horizon_classifier_versions` | id, version_no, semver(text，唯一，匹配 `^(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)$`，即契约 `classifier_version`；T-A03), config(jsonb：特征、各周期打分规则、阈值), published_at — 不可变 |
| `symbol_horizon_assessments` | id, user_id, security_code, classifier_version_id, snapshot_id, scores(jsonb：{intraday_t,short,swing,long: 0–100}), suitable_horizons(text[]), reasons(jsonb：[{horizon, text, evidence_ids, polarity: for/against}]), inputs_missing(text[] NOT NULL DEFAULT '{}'：缺失的 feature_catalog 键 `f.*`，去重升序，无缺失为空数组，CHECK 每项匹配 `^f\.[a-z0-9_]+$`；T-A03), hints(jsonb NOT NULL DEFAULT '[]'：`HorizonHint[]`，T-A06), caps(jsonb NOT NULL DEFAULT '[]'：[{horizon, cap, kind: gate/data_missing, rule_id, inputs_missing}]；T-A03；v0.2.6（T006e）删 `requires`、加 `gate`), evidence(jsonb：Evidence[]，理由引用的证据，契约 v0.2.3), recommended_strategy_version_ids(uuid[]), trigger(import/watchlist_add/weekly/position_open_close/on_demand；`on_demand` 为 v0.2.9 内 T-B47 裁定新增：GET 时没有可用记录而同步计算；库级 CHECK `ck_symbol_horizon_assessments_trigger` 的取值必须与此列表完全一致（v0.2.9 内，T-T25 裁定：现有迁移 0002 的 CHECK 为 `import/watchlist_add/weekly/position_open_close`，缺 `on_demand`；后端新增迁移补上 `on_demand`，downgrade 前须确认表中没有 `on_demand` 行，有则拒绝降级）), created_at — 只追加。（v0.2.9 内，T-B46/T-B47 裁定）：`user_id` NOT NULL（含 `user.*` 与画像派生内容）；`snapshot_id` NOT NULL，FK→`data_snapshots`（`purpose='horizon'`）；索引 `(user_id, security_code, classifier_version_id, created_at desc)`；保留期：每个（用户、证券、分类器版本）的最新一条长期保留，其余超过 180 天的由周期任务物理删除（问题 75）；删除用户时与对应快照一起物理删除（7.3） |
| ~~`user_symbol_strategy_settings`~~ | **已废弃**，由 `strategy_instances` 取代（见下方"策略三层"表组）。迁移时把旧行映射为 `status=active` 的实例 |
| `risk_control_settings` | id, scope(system/user), user_id(nullable), control(position_cap/total_exposure/sector_concentration/stop_take/loss_streak_drawdown/plan_violation), enabled(bool), params(jsonb), updated_at；变更写历史表 |
| `risk_events` | id, user_id, control, level(info/warning/critical), subject(account/security/strategy), security_code, detail(jsonb), suggestion_id(nullable), trade_id(nullable), created_at — 只追加 |
| `strategy_runs` | id, user_id, strategy_version_id, kind(screen), params(jsonb), trade_date, result_count, results(jsonb, 截断前 200), snapshot_id, created_at（取代旧 `screen_runs`） |
| ~~`strategy_evaluations`~~ | **已废弃**，由 `candidate_signals` 与 `candidate_signal_events` 取代；规则逐条结果放在 `candidate_signals.rule_refs` 中 |
| `strategy_tracking_stats` | strategy_version_id, horizon, scope(user/global), user_id(nullable), window_days(1/5/20), as_of_date, n, wins, win_rate, avg_return_pct, avg_excess_pct, profit_loss_ratio, max_loss_streak, recent(jsonb) — 每日盘后重算；global 只含匿名汇总 |
| `user_strategy_weights`（原 `strategy_priority_weights`） | user_id, strategy_version_id, horizon, as_of_date, weight, raw, n, params(jsonb：α/β/γ/s/n_min), sample_range(jsonb), enabled_at_calc(bool)；全站健康度见 `strategy_health_daily`（2.8.2） |

**策略三层、候选信号、不可执行原因与计划草案（2.5.0–2.5.13；取代 `user_symbol_strategy_settings` 与 `strategy_evaluations`）**

一级实体都遵循以下约定：
- 头表可变（状态、当前版本）；正文或版本**不可变**（更新触发器拒绝改写）。
- 带 `epistemic_type`。
- 绑定 `snapshot_id`。
- 状态变化写入只追加的事件表。

| 表 | 关键字段 |
|---|---|
| `strategy_cards`（L1 头表） | id, key(unique), title, current_version_id, completeness(draft/documented/runnable_candidate/promoted/retired), owner_user_id(null 表示系统), source_kind(builtin/admin/user/llm_draft/reference), created_at |
| `strategy_card_versions`（L1 版本，不可变） | id, card_id, version_no, parent_version_id, fields(jsonb：2.5.0A 的 8 个必填字段与选填字段), field_epistemic(jsonb：每个字段的 epistemic_type), references(jsonb：[{title, url, license}]), performance_log(jsonb：模拟跟踪的回填摘要，附 n), changelog, created_by, created_at |
| `rule_snippets` | id, key, version_no, role(entry/exit/filter/veto/counter/invalidation), expr(DSL), params_schema(jsonb), required_features(text[]), description, card_version_id(nullable), created_at — 不可变；是 L1 → L2 的规则积木 |
| `feature_catalog` | feature_key PK, description, source(provider, endpoint, field)/derivation(expr), unit, adjust(qfq/hfq/none), frequency(1m/daily/quarterly/event), pit_rule(available_from 规则), status(declared/verified_doc/verified_live/deprecated), pipeline_version, owner, updated_at — DSL 白名单（G2、G3） |
| `market.feature_bars_daily`（hypertable） | security_id, trade_date, feature_set_version, values(jsonb 或宽列), computed_at — 唯一特征管线的产出 |
| `strategies` / `strategy_versions`（L2，即 `strategy_templates` / `template_versions`） | 在原字段基础上增加：card_version_id（L1 来源）, kind(rule_template/code), code_entry(仅 kind=code：注册表键), parent_version_id, param_hash, params_schema(jsonb：type/default/min/max/step), rule_snippet_refs(jsonb：[{snippet_id, version, role}]), feature_set_version, lifecycle(draft/simulating/published/observing/retired), lifecycle_changed_by/at — **版本不可变**；生命周期的跃迁写入 `strategy_lifecycle_events` |
| `strategy_promotion_reviews` | id, card_version_id, target_strategy_version_id, gate_results(jsonb：G1–G7 逐项 pass/fail/detail), fixture_runs(jsonb：golden 用例结果), g6_report(jsonb：触发率、覆盖率、Jaccard、配额估算), internal_eval_report_id(nullable，仅当问题 26 获批), compliance_lint(jsonb), decision(pending/approved/rejected/changes_requested), reviewer_id, reviewed_at, note |
| `strategy_lifecycle_events` | id, strategy_version_id, from_state, to_state, reason, trigger(admin/health_machine), actor_id, at — 只追加 |
| `strategy_health_baselines` / `strategy_health_daily` | baseline：strategy_version_id, set_at, tracking_baseline(jsonb), oos_robustness_baseline(nullable)；daily：strategy_version_id, as_of_date, n, weight, raw, oos_robustness(nullable), state(published/observing), proposed_action(none/review/retire), detail(jsonb) |
| `strategy_instances`（L3 头表） | id, user_id, strategy_version_id, scope(account/security/watch_group), account_id, security_id(nullable), status(proposed/active/paused/archived), origin(classifier/user/system；`system` 为 H-01 一类系统挂载，契约 v0.2.7), horizon, param_overrides(jsonb), derived_strategy_version_id(nullable：越界参数会生成派生版本，I4), risk_settings_snapshot(jsonb), ~~fit_ack~~（T-A06 作废，不建此列）, budget_amount, auto_downweight(bool), paused_by(user/system, nullable), pause_reason_code(nullable), paused_until(nullable), created_at, confirmed_at, updated_at, archived_at(nullable)；索引 `(user_id, status, created_at desc, id desc)`；状态机见契约 §6.0A（v0.2.7） |
| `strategy_instance_events` | id, instance_id, kind(created/confirmed/paused/resumed/params_changed/archived), from_status(nullable), to_status(nullable), actor(user/system), actor_id(nullable), reason_code(nullable), note(nullable), detail(jsonb), at（契约 v0.2.7） |
| `candidate_signals` | **正文不可变**：id, user_id, instance_id, strategy_version_id, security_id, horizon, proposed_action, t_leg, score, confidence, stops(jsonb), **rule_refs**(jsonb：[{rule_id, snippet_id, version, role, passed, value, threshold}], 非空), **evidence**(jsonb：[{id, provider, endpoint, symbol, field, value, unit, data_as_of, fetched_at, epistemic_type}], 非空), **counter_evidence**(非空), **invalidation**(非空), **model_refs**(jsonb：[{model_id, version, output, role:'auxiliary'}]), gate_results(jsonb), risk_flags(jsonb), crowding_flag, feature_set_version, snapshot_id, valid_until, cooldown_key, created_at；**头表字段**：state(open/blocked/released/drafted/confirmed/dismissed/expired/invalidated/superseded), state_changed_at；按月分区；CHECK 约束：`jsonb_array_length(rule_refs) > 0 AND jsonb_array_length(evidence) > 0` |
| `candidate_signal_events` | id, signal_id, from_state, to_state, cause(executability_check/reason_released/user/expiry/invalidation/supersede), detail(jsonb), at — 只追加 |
| `non_executable_reasons` | id, signal_id, user_id, code(22 种之一，2.5.9), description, evidence(jsonb), epistemic_type, detected_at, snapshot_id, release_condition(jsonb), check_on(text[]), machine_checkable(bool), next_check_at, status(active/released/obsolete), released_at, release_evidence(jsonb), released_by(system/user_id) |
| `reason_status_events` | id, reason_id, from_status, to_status, evaluated_value(jsonb), at — 只追加；解除时发 `reason_released` 通知 |
| `plan_drafts` | **不可变**：id, user_id, signal_ids(uuid[]), instance_id, action, qty_range(jsonb：{min, max, lot}), price_range(jsonb), stops(jsonb), max_loss_amount, max_loss_pct, fee_estimate(jsonb，带 epistemic_type), user_context_snapshot(jsonb：持仓、可卖数量、现金、暴露), risk_flags(jsonb), judgment_checklist(jsonb：[{id, question, required}]), market_rule_version_id, snapshot_id, expires_at, created_at；**头表**：status(pending/confirmed/discarded/expired/stale), status_changed_at |
| `plan_draft_confirmations` | id, draft_id, user_id, checklist_answers(jsonb), risk_ack(bool), chosen_qty, chosen_price, deviation(jsonb：超出区间的部分与二次确认), plan_id, created_at |
| `user_restrictions` | id, user_id, kind(blocklist/cooling_off/mute), target_type(security/strategy/instance), target_id, until(nullable), reason, created_at, removed_at |
| `llm_strategy_drafts`（第三阶段） | id, requested_by, input_text_hash, output_json(jsonb：卡片或模板草稿，仅 JSON), correction_rounds(≤3), validation_errors(jsonb), status(draft/rejected/approved_to_card), reviewer_id, llm_call_ids(uuid[]), created_at |
| `market_rule_versions` | id, effective_from, rules(jsonb：2.13 的涨跌幅、无涨跌幅情形、整手单位、费用、时段), source_note, created_at — 按日期取当时有效的版本 |
| `event_definitions` | id, key, version_no, source_rule(jsonb), direction, severity, dedup_window, created_at — 不可变（2.12.2） |
| `evaluation.*`（仅管理员，第三阶段启用） | `eval_runs`(id, kind(factor_ic/event_study/param_robustness/daily_revalidation), target, params, data_range, status, cost_calls, started_at, finished_at)、`eval_results`(run_id, metrics(jsonb，全部附 n), folds(jsonb), robustness) |

**对已有表的修改**：
- `action_plans`：增加 origin(manual/plan_draft), plan_draft_id, candidate_signal_ids(uuid[])，status 增加 `pending_review`。
- `plan_versions`：增加 market_rule_version_id。
- `suggestions`（候选信号卡视图）：增加 candidate_signal_ids(uuid[]), executability(jsonb：{status: executable|blocked|drafted, reason_ids[]}), plan_draft_ids(uuid[])；每个策略条目增加 rule_refs 和 model_refs。
- `suggestion_user_actions.kind`：改为 viewed/dismissed/draft_requested/draft_confirmed/acted_trade_linked/reason_manually_released（删除"一键转计划"）。
- `data_snapshots`：增加 feature_set_version, market_rule_version_id。
- `market.financial_reports`：增加 report_period, announce_date(plrq), available_from。
- `market.market_events`：增加 event_definition_id, source(rule/llm), confidence, original_title, original_url, review_status(none/pending/confirmed/rejected)。
- `market.factor_values`：增加 available_from, first_seen_at；改为 hypertable。
- `strategy_priority_weights`：并入 `strategy_health_daily`（用户级权重仍按用户计算，存为 `user_strategy_weights`）。
- `notifications.kind`：增加 reason_released, plan_draft_ready, plan_draft_stale, strategy_observing, ingest_alert（仅管理员）。

**主线：实时行情、信号、建议、日报、跟踪**
| 表 | 关键字段 |
|---|---|
| `intraday_universe` | trade_date, security_code, tier(1/2/3=仅全市场快照), holders_count, watchers_count, focus_users_count, computed_at（每日一张、变更时更新） |
| `market.realtime_quotes` | code, ts(行情时间), price, open, high, low, pre_close, volume, amount, pct_change, source(ssjy_more/ssjy_all/real_all), fetched_at（按日分区；按分钟降采样保存，默认保留 10 个交易日，可配置）；**TimescaleDB hypertable**，chunk 1 天，7 天后压缩（3A） |
| `market.minute_bars` | code, ts, open, high, low, close, volume, amount, source('pro_latest'/'pro_history'), fetched_at（**hypertable**，chunk 1 天，7 天后压缩；保留期按 3A.2 与问题 28 修订；原方案只持久化 Tier-1：1,500 只 × 240 根 ≈ 36 万行/日，默认保留 90 天 ≈ 3,200 万行，约 3–4 GB【估算】；Tier-2 分钟线只放 Redis 当日） |
| `signal_states` | id, source_licence_id（2.1B）, security_code, strategy_version_id, params_hash, rule_states(jsonb), state, last_tick_id, changed_at — 同一证书内共享的当前状态（不跨证书） |
| `user_signal_states` | id, user_id, security_code, source(suggestion_invalidation/plan_condition/user_rule), source_id, condition(jsonb), state(true/false/unknown), last_tick_id, changed_at |
| `signal_events` | id, tick_id, scope(shared/user), user_id(nullable), security_code, from_state, to_state, trigger_kind(flip/invalidation/stale/resume), detail(jsonb), quote_ts, created_at — 只追加 |
| `suggestion_threads` | id, user_id, security_code, account_id(nullable), current_suggestion_id, status(active/superseded/invalidated/expired), user_decision(none/accepted/dismissed/acted), decided_at, updated_at — 头表 |
| `suggestions` | id, thread_id, user_id, security_code, name（生成时简称）, seq_no, status(suggestion_status，唯一可变列), origin(daily_batch/intraday_event/manual_refresh), evidence(jsonb), strategies(jsonb：每策略即契约 `StrategyConclusion` {strategy_version_id, strategy_key, strategy_name, version_no, instance_id, horizon, lifecycle, state, action, t_leg, candidate_signal_id, score(0–100), confidence, rule_refs, model_refs, dimension_views, stops, invalidation, reasons, counter_evidence, priority_weight, priority_downweighted, valid_until}), executability(jsonb), candidate_signal_ids(uuid[]), consensus(jsonb), dimension_matrix(jsonb), divergence(jsonb), risk_flags(jsonb), strategy_version_ids(uuid[]), engine_policy_id, horizon_assessment_id, profile_version_id, holding_context(jsonb), snapshot_id, data_status(fresh/stale/partial), reference_price, reference_ts, explanation_text, explanation_source(template/llm), llm_call_id, prompt_template_id, generated_by(rules_engine@ver), supersedes_id, superseded_by_id, created_at — 除 `status`、`superseded_by_id` 外**不可变** |
| `suggestion_user_actions` | id, suggestion_id, user_id, kind(viewed/dismissed/draft_requested/draft_confirmed/acted_trade_linked/reason_manually_released；**没有 converted_to_plan**), note, trade_id(nullable), at — 只追加 |
| `suggestion_tracking` | suggestion_id, horizon_days(1/5/20), due_date, status(pending/done/not_applicable), ref_price, close_price, return_pct, benchmark_code, benchmark_return_pct, excess_pct, max_drawdown_pct, max_runup_pct, invalidation_hit_at, direction_correct(bool/null), computed_at, snapshot_id |
| `daily_reports` | id, user_id, trade_date, status(building/ready/partial/failed), summary(jsonb：账户、市场、数据缺口), explanation_text, gaps(jsonb), generated_at；unique(user_id, trade_date) — 生成后不可变（重跑生成新 revision） |
| `daily_report_items` | id, report_id, security_code, relation(holding/watchlist), facts(jsonb), strategy_results(jsonb), suggestion_id, explanation_text |
| `pipeline_runs` | id, kind(daily_batch/intraday_session/tracking), run_date, step, status, started_at, finished_at, stats(jsonb), error |
| `realtime_settings` | id, version_no, config(jsonb：0A.3 所列配置项), changed_by, changed_at — 管理员配置历史 |
| `user_realtime_prefs` | user_id, notify_cadence(realtime/1m/3m/5m), focus_codes(text[], ≤ 权益上限), updated_at |

**LLM 网关**
| 表 | 关键字段 |
|---|---|
| `llm_providers` | id, name, kind(openai_compatible/anthropic/…), base_url, api_key_source(env/db), api_key_env(变量名，如 `DEEPSEEK_API_KEY`；source=env 时必填), api_key_ciphertext(source=db 时才有), key_version, status(ok/unconfigured/auth_failed/insufficient_balance/circuit_open), enabled, created_by, updated_at |
| `user_data_licences` | id, user_id(FK；未删除行唯一), provider('mairui'), ciphertext(bytea，HPKE 封装：封装公钥 + AES-256-GCM 密文与标签；删除后置 NULL), seal_key_version(int), licence_hmac(bytea，未删除行唯一；只用于防一证多用，不出接口、不进日志), tier(free/trial/monthly/annual/diamond/other，用户填写), has_quant_pro(bool，用户填写), expires_on(date，用户填写), status(`data_licence_status`), status_changed_at, last_verified_at, last_error_code, last_error_at, consecutive_failures, paused_until, per_minute_limit_override(int，管理员可设), created_at, updated_at, deleted_at — **证书值只以密文存在，没有末几位或指纹**；`api` 的数据库角色对 `ciphertext` 只有 INSERT/UPDATE、无 SELECT，读不含密文的视图 `user_data_licence_status`（2.1B，契约 v0.2.6） |
| `llm_models` | id, provider_id, model_name, context_window, max_output_tokens, thinking(enabled/disabled), price_input_cache_hit_per_1m, price_input_cache_miss_per_1m, price_output_per_1m（高峰价）, offpeak_multiplier, currency, price_checked_at, enabled |
| `llm_task_routes` | task(primary key), primary_model_id, fallback_model_ids(uuid[]), timeout_s, max_retries, temperature, max_output_tokens, daily_budget, enabled, prompt_template_id |
| `prompt_templates` | id, task, version_no, system_text, user_template, output_schema(jsonb), status(draft/active/retired), created_by, created_at — 激活后不可修改 |
| `llm_calls` | id, task, provider_id, model_id, prompt_template_id, input_tokens, cache_hit_tokens, cache_miss_tokens, output_tokens, latency_ms, http_status, retries, pricing_period(peak/offpeak), status(ok/timeout/error/validation_failed/blocked_pii/fallback_template), validation_errors(jsonb), cost_estimate, target_type, target_id, request_hash, request_body(加密/保留 90 天), response_body, created_at |

**通知**（取代旧 `alert_deliveries` / `notification_settings`）
| 表 | 关键字段 |
|---|---|
| `notifications` | id, user_id, kind(suggestion_change/invalidation/daily_report/alert/import/system), severity(info/attention/important), title, body, link, ref_type, ref_id, dedup_key, read_at, created_at |
| `notification_channel_bindings` | id, user_id, channel(email/wecom_app/wecom_bot/mp_template/serverchan), target_ciphertext, target_masked, status(pending_verify/active/disabled/failed), verified_at, created_at |
| `notification_preferences` | user_id, channel, kinds(text[]), min_severity, detail_level(full/summary/ping), quiet_hours(jsonb: {start, end, tz, allow_important}), rate_per_min, rate_per_hour, digest_time |
| `notification_deliveries` | id, notification_id, binding_id(nullable for in_app), channel, status(queued/sent/failed/retrying/dropped), attempts, next_retry_at, provider_msg_id, error_code, error, sent_at |

**会员预留（不含支付）**
| 表 | 关键字段 |
|---|---|
| `plans` | id, code(free/beta/pro…), name, status(active/hidden/retired), display_price_note, sort |
| `plan_entitlements` | plan_id, key, value(jsonb) — 例：`watchlist.per_user_cap`、`realtime.min_notify_interval_s`、`intraday.focus_cap`、`llm.daily_explanations`、`channels.allowed`、`import.monthly_files` |
| `user_subscriptions` | id, user_id, plan_id, status(active/expired/cancelled), starts_at, ends_at, source(manual_admin/payment_reserved), note, created_by |
| `entitlement_overrides` | user_id, key, value, reason, expires_at, created_by |

**复盘**
| 表 | 关键字段 |
|---|---|
| `reviews` | id, user_id, plan_id(nullable), security_code, period_start, period_end, current_version_id |
| `review_versions` | id, review_id, version_no, plan_version_ids(uuid[]), trade_ids(uuid[]), outcome_metrics(jsonb: 收益/基准/超额/回撤，均 fact+计算方法), attribution(jsonb: {market, execution, judgment}，每项含 epistemic_type), lessons(text), tags(text[]), snapshot_id, created_at — **不可变** |

**快照与行情**（麦蕊来源按证书隔离，见本节“数据归属”；只有证券公开主数据全站一份）
| 表 | 关键字段 |
|---|---|
| `data_snapshots` | id, created_at, purpose(candidate/plan/alert/review/screen/horizon；`horizon` 为 v0.2.9 内 T-B47 裁定新增，周期评估快照，`user_id` 必填), items(jsonb: [{key（如 quote.{symbol}.close）, value, unit, data_as_of, fetched_at, provider, endpoint, raw_payload_id}]), known_events(jsonb: 当时已知的公告/事件 id 列表), hash；**user_id**(FK→users，可空；含持仓、成交、账户或其派生内容时必填), **licence_id**(可空；用某用户证书取到的数据时填)（T-B16 裁定：带 user_id 的快照在删除用户时物理删除；user_id 为空的快照只允许存市场级内容，见 7.3）。**写入方验收（v0.2.9 内，评审 be607b3/f72b8c7/8fd9502 裁定）**：每个写 `data_snapshots` 的模块（候选、计划、提醒、复盘、筛选、周期评估及以后新增的写入方）上线前都要有一条验收用例：快照含个人内容（持仓、成交、账户、画像、`user.*`）或由其派生的内容时必须写 `user_id`；用到某用户证书取到的数据时还必须写 `licence_id`；两条任一不满足即拒写（应用层断言 + 表 CHECK：`purpose IN ('candidate','plan','horizon')` 时 `user_id IS NOT NULL`；v0.2.9 内，T-O11 评审裁定：`candidate` 也必填，因为研究候选快照含本人持仓派生的适配评估；后端用新迁移把 `horizon` 加进 `purpose` 的 CHECK 并加这条 CHECK，迁移前先查已有违规行）。测试员在 T-T16 中按写入方逐个覆盖 |
| `market.securities` | ~~code, name, exchange, board, list_date, status, industry_codes, updated_at~~ → v0.2.7：security_id, code("600000.SH"), type(stock/cdr/etf/index；契约 v0.2.8 加 etf), name, exchange(SH/SZ/BJ), board, list_date, list_date_basis, delist_date, listing_status, risk_flag, name_norm, name_initials(text[]), master_source, master_as_of, updated_at。**证券公开主数据，全站一份**（第 9 节问题 51：只含代码、简称、拼音、曾用名、交易所、板块、上市日、状态、风险警示；不存公司全称）；`master_source` 来源（v0.2.9 内，T-A04 定）：交易所公开列表（4.6.1；能否展示与再分发仍待问题 52）。行业、概念、股本移到按证书的表（带 `source_licence_id`，2.1B）。另建 `security_name_history`、`security_code_history`、`security_risk_flag_history`（T007 §5）；索引 `gin (name_norm gin_trgm_ops)`、`gin (name_initials)`（迁移中 `CREATE EXTENSION IF NOT EXISTS pg_trgm`）。**v0.2.9 内，T-A04**：列、约束与索引以 4.6.2 为准；V1 以 `code` 为主键（与已实现的迁移一致），**不另建代理键**，本表之外各表字段表中的 `security_id` 都指 `code`；搜索索引移到 `security_search_terms`（4.6.3） |
| `market.trading_calendar` | date, is_open |
| `market.daily_bars` | code, trade_date, open, high, low, close, volume, amount, adj_type, fetched_at（按年分区） |
| `market.quotes_snapshot` | code, ts, price, pct_change, … （只保留当日+近 5 日，热数据在 Redis） |
| `market.financial_derived` | v0.2.9 内（L-01 裁定，T-B55）：`code`、`period_end`、`version_available_from`、`metric`（`pe_ttm`/`pb`/`roe_ttm`/`ocf_to_np_ttm`/`debt_ratio`；`pe_ttm`、`pb` 按交易日存；`pb` 为 T-R12 裁定新增）、`trade_date null`、`value numeric null`、`basis jsonb`（所用报告期、各分量版本、`roe_basis`、`ocf_field`（经营现金流实际所用字段）、`pit_basis`（T-R12f 起为字符串数组）、回退标记；T-R12a 起加 `null_reason`（封闭枚举，见 2.12.1 T-R12b 补充裁定 1）、`zgb_bdrq`、`mcap_basis`、`share_change_check`、`verify_pending`（字符串数组，见 2.12.1）；T-R12b 起加 `single_period_reason`、`share_class_check`）、`calc_version`、`computed_at`。PK `(code, metric, period_end, version_available_from, coalesce(trade_date))` 以唯一索引实现；btree `(metric, trade_date)`。按证书数据计算时带 `source_licence_id`（2.1B） |
| `market.financial_reports` | code, report_type(balance/income/cashflow/pershareindex), period_end, payload(jsonb), first_seen_at, last_seen_at, payload_hash — **数据变化时新增行**，保留"重述"历史，支持 as-of；增加 announce_date(公告日 plrq【待 T003 验证】), available_from（按时点可用时间，2.12.1）。v0.2.9 内（L-01 裁定）：`plrq` 已由 T003 缺口目录第 3 项核实（空值率 0，三表都有）；同一报告期多行的含义待研究员对照巨潮原文；派生值另存 `market.financial_derived`（T-B55） |
| `market.fund_flows` | code, trade_date, payload(jsonb), fetched_at |
| `market.factor_values` | code, trade_date, factor_id, value, calc_version, fetched_at, available_from, first_seen_at — hypertable（chunk 1 个月） |
| `market.announcements` | id, code, published_at, title, summary, url, category(lx), level(jb), source('mairui'), first_seen_at |
| `market.qa_items` | id, code, question, answer, asked_at, answered_at, first_seen_at |
| `market.market_events` | id, code, type(limit_up/limit_down/lhb/unlock/forecast/express/…), event_date, payload, first_seen_at, event_definition_id, source(rule/llm), confidence, original_title, original_url, review_status |
| `ops.ingest_request_log`（hypertable，保留 30 天） | id, requested_at, licence_id（T-A07）, requester(service), priority(P0/P1/P2), dataset, endpoint_key, symbols_count, dedup_key, status(queued/done/failed/dropped), http_status, mairui_code, latency_ms, finished_at — 只记录元数据，不记录 licence 和完整 URL |
| `ops.data_licence_events`（只追加） | id, licence_id, user_id, event(set/replaced/deleted/verified/invalid/expired/quota_exceeded/ip_limited/paused/resumed/expiry_reminder), actor(user/admin/ingest), from_status, to_status, upstream_code, at — 不含证书值及其任何片段（T-A07） |
| `ops.ingest_leases` | id, holder_host, egress_ip, started_at, last_renewed_at, ended_at, end_reason — 单活锁历史（审计"任何时刻只有一个调用方"） |
| `market.raw_payloads` | id, source_licence_id（T-A07）, endpoint, params_hash, fetched_at, status, body(jsonb, 压缩), body_hash — 保留 90 天（快照引用的永久保留） |

> **因子读接口版本投影（O-CI1-PROFILE-CONTRACT，2026-11-12 Chief 裁定；契约 §7.3）**：`GET /securities/{code}/factors.factor_set_version` 为必出现的 `string | null`。明确无适用/可用且版本可核实的真实因子集时，只返回 `items=[]`、`counts={total:0, by_category:{}}`、`data_status=unavailable` 及实际 `factors` gap，版本为 `null`；本版 ETF 必为该空集与 `not_applicable`、版本必 `null`。无来源/本人证书不可用分别保 `no_source`/`data_licence_unavailable`，不得改成类型不适用。完全无数据时不补时点。
> 有真实因子集时返回其真实非空版本，筛选后无条目也不能抹掉已知版本；有数据却缺版本绑定须修复完整性，不能以 `null` 配正常数据状态、丢弃数据或吞 SQL/权限异常求绿。不使用空串、应用版本、示例版本或臆造来源；不改变 `calc_version`/`feature_set_version`，不新增注册表、迁移、读接口写入或外部抓取。后端响应/schema及契约测试、前端类型/mock/空版本显示须同批同步；旧必字符串假设不兼容，旧真实版本保持。详见 [裁定](reviews/O-CI1-PROFILE-CONTRACT.md)。

> **O-CI1-PROFILE 当前交付边界（候选 442554fd）**：financials、fund-flows、factors、announcements 四 GET 本轮仅 empty/unavailable 的适用性与缺口视图；正常证券的 owner-scoped provider/cache 未接，不以无属主全局行情补齐，不把空集 200 当正常数据完成。真实 provider 与版本绑定仍按契约 §7.3 目标继续，当前限制须随 PR 保留。

> **数据归属（T-A07，2.1B）**：`data_sharing.mode=per_licence`（默认）时，全部 `market.*` 表（`securities` 除外：它只存证券公开主数据，全站一份，第 9 节问题 51；`trading_calendar`、`daily_bars`、`quotes_snapshot`、`realtime_quotes`、`minute_bars`、`financial_reports`、`fund_flows`、`factor_values`、`announcements`、`qa_items`、`market_events`、`feature_bars_daily`）、`market.raw_payloads`、`intraday_universe` 与 Redis 行情缓存键都加 `source_licence_id`（uuid，FK `user_data_licences.id`），并进入唯一键和主要查询索引；`signal_states` 的 `scope=shared` 改为“同一证书内共享”。读取一律按当前用户的证书过滤，不读别人证书取到的数据。用户删除证书或账号时，该证书名下的行情数据按保留策略清理，不转给他人。`shared_cache` 模式下 `source_licence_id` 只记录实际取数的证书，供审计（启用前须取得麦蕊书面确认，第 9 节问题 50）。

> `first_seen_at` 是"我们何时知道"的依据，是按原貌回看与"当时已知信息"判断的关键：回看 T 时刻时，只使用 `first_seen_at <= T` 的公告/事件/财报版本。

### 3.4 回看（as-of）规则
- 查看历史版本 → 读该版本 `snapshot_id` 的值；页面顶部标注"以下为 2026-xx-xx 当时的数据与判断"。
- "与现在对比"→ 同一 key 取最新值并展示差异；事件列表区分"当时已知"与"之后发生"。
- 快照只存**被引用的数据项**（几十个 key），不复制整库，控制体积。

### 3.5 交割单导入层（可扩展解析）

> 下列框架不依赖任何具体券商。**已收到 1 种格式（格式 A：成交明细 + 资金持仓快照）的范本，分析见 3.5A**；其余券商/软件的格式仍【待用户提供范本】，届时只需新增解析器插件与合成测试样本。

**流程（先预览、后确认，两步提交）**
```
上传文件 ──> ① 留存原始文件(sha256) ──> ② 编码识别 ──> ③ 识别格式(选择解析器)
        ──> ④ 解析为标准行 + 列映射 ──> ⑤ 校验 & 去重判定 ──> 预览(状态 previewed)
用户确认 ──> ⑥ 事务内写入 trades/account_events ──> ⑦ 重建受影响账户 holdings ──> 状态 committed
用户放弃 ──> 状态 discarded（同一事务删除预览行；批次头保留；原始文件按留存策略保留）
```

**① 文件接收与留存**
- 允许 `.txt`/`.csv`（MVP），单文件 ≤ 5 MB，单次 ≤ 5 个文件；保存到本机加密卷或境内对象存储（私有桶），路径 `imports/{user_id}/{batch_id}/{sha256}`；记录原文件名、大小、sha256。
- 同一账户上传**同 sha256 文件**→ 文件级警告 `IMPORT_DUPLICATE_FILE`（不是 HTTP 错误；仍可预览，去重会挡住重复行）。
- 原始文件默认保留 **365 天**或至用户删除账户（已定，第 9 节问题 21），用于追溯与解析器升级后重新解析；用户可在导入记录中手动删除原始文件。
- **放弃或失败批次的预览行（v0.2.9 内，T-live-83a031c §8 裁定；契约 v0.2.9 #35）**：
  - 批次转为 `discarded` 时，在同一事务里删除它的全部预览行（`import_rows`）以及其他按 `batch_id` 暂存、尚未提交的行级数据（如持仓快照的预览明细）；批次头（`import_batches` 的 `stats`/`summary`、`file_findings`、状态与时间）保留，用于审计和计数。
  - 批次转为 `failed` 时同样处理；之后 `PUT options` 重新解析时从原始文件重新生成预览行。
  - 原始文件不因放弃或失败而提前删除，按上一条的留存规则（`retained_until`）与 7.3“交割单原始文件”的每日清理、`ops.pending_file_purges` 重试处理，规则不变。（T-live-83a031c §8.3 观察到当前实现在 discard 时删除了原始文件、保留了预览行，两点都要按本条改）
  - 已经处于 `discarded` 或 `failed`、仍有残留预览行的批次，由 beat 每小时调度、worker 执行的清理任务 `imports.purge_preview_rows` 删除（幂等，按批次分段提交，每次最多处理 10,000 行，剩余的下一小时继续）。
  - 预览过期：本方案没有定义预览的过期时限，本裁定**不新增**；以后若定义，过期批次按本条同样处理。

**② 编码识别**
- 依次尝试：BOM 检测 → 严格 `utf-8` 解码 → `gb18030`（GBK 超集）→ `charset-normalizer` 检测兜底；记录 `detected_encoding` 与置信度；用户可在预览页手动改选编码重新解析。
- 统一换行（`\r\n`/`\r`）、去除全角空格/不可见字符、全角数字转半角。

**③ 格式识别与解析器插件**
```python
class BrokerStatementParser(Protocol):
    parser_id: str            # 如 "generic_delimited", "broker_x_v1"（待范本）
    display_name: str
    version: str
    def sniff(self, text: str, filename: str) -> float: ...           # 0~1 置信度
    def parse(self, text: str, mapping: ColumnMapping | None) -> ParseResult: ...
# ParseResult: header_detected, column_mapping(建议值), rows: list[ParsedRow], warnings
# ParsedRow: row_no, raw_line, kind(trade/event/ignored), normalized(dict) | errors(list)
```
- 注册表 `PARSERS`：所有插件 `sniff` 打分，最高分 ≥ 0.6 自动选中，否则让用户在预览页手选；用户也可指定。
- 内置 **`generic_delimited` 通用解析器**：自动探测分隔符（Tab/多空格对齐/逗号/竖线），定位表头行（含"成交日期/证券代码/买卖标志/成交数量/成交价格"等同义词），跳过页眉页脚/合计行。
- 每个券商专用解析器 = 表头同义词表 + 业务标志映射（如"证券买入/证券卖出/红利入账/股息红利税补缴/新股入帐/银行转证券"→ 标准 kind/side）+ 特殊规则；随范本逐个添加（任务 T-B19）。

**④ 列映射（标准字段）**
| 标准字段 | 必填 | 常见原始列名（同义词，待范本扩充） |
|---|---|---|
| trade_date | 是 | 成交日期、发生日期、交收日期 |
| trade_time | 否 | 成交时间 |
| security_code | 是（买卖类） | 证券代码 |
| security_name | 否 | 证券名称 |
| biz_type / side | 是 | 业务名称、买卖标志、操作、摘要 |
| quantity | 是（买卖类） | 成交数量、成交股数 |
| price | 是（买卖类） | 成交价格、成交均价 |
| amount | 否 | 成交金额 |
| commission / stamp_tax / transfer_fee / other_fee | 否 | 佣金、手续费、印花税、过户费、其他费 |
| net_amount | 否 | 发生金额、清算金额 |
| broker_trade_no / order_no / declare_no | 否 | 成交编号 / 委托编号、合同编号 / 申报序号 |
| cash_balance_after | 否 | 剩余金额、资金余额 |
| shareholder_code | 否（**明文不入库**：只存 HMAC 与掩码，见 3.5A 隐私） | 股东代码、股东账户 |
- 自动映射结果在预览中可由用户修改，修改后的映射可保存为用户的"映射模板"（`import_mappings`），下次同券商自动套用。
- 证券代码补市场后缀（6/9 开头→SH，0/3 开头→SZ，4/8/920 开头→BJ，规则在 `marketdata` 中统一并以证券主数据校验）。

**⑤ 校验、去重与幂等**
- 行级校验：日期合法、代码存在于证券主数据、数量 > 0、价格 > 0、`amount ≈ |quantity|×price`（容差 0.05 元，`IMPORT_AMOUNT_MISMATCH`）、卖出数量不超过重建后的可用持仓（超出→警告 `IMPORT_MISSING_OPENING_POSITION`，不阻止，提示补录期初）。完整码表与判定顺序见 3.5A-1。
- `dedup_key`（通用规则如下；格式 A 的具体规则与"弱指纹"见 3.5A）：
  - 有成交编号：`sha256(account_id | trade_date | broker_trade_no)`；
  - 无编号：`sha256(account_id | trade_date | trade_time | code | side | quantity | price | amount)`，同文件内相同键出现多次时追加序号 `#n`（真实存在同价同量多笔成交）。
- 去重判定写入每行 `dedup_status ∈ {new, duplicate_in_db, duplicate_in_file, possible_duplicate_of_manual}`（error 行为 null）；确认时只写 `new` 行；数据库唯一索引 `(account_id, dedup_key)` 兜底，保证**重复确认/重复上传幂等**。
- 确认接口带 `Idempotency-Key` 头；同一批次重复确认返回同一结果。

**⑥⑦ 写入与重建**：单事务写入成交与流水 → 对受影响账户重放全部记录重建 `holdings` → 生成 `import_batches.summary`（新增 N 笔、重复 M 笔、错误 K 行、受影响证券列表）→ 触发能力 4 的"持仓变化"事件与能力 5 的"计划-成交关联建议"（按证券与时间匹配候选计划，**由用户确认关联**）。

**撤销**：对已确认批次可"整批撤销"→ 该批成交全部 `voided`（原因"撤销导入批次"）→ 重建持仓；不物理删除。

**表**
| 表 | 关键字段 |
|---|---|
| `import_batches` | id, user_id, account_id, status(uploaded/parsing/previewed/committed/discarded/failed/reverted；契约 `import_status`), parser_id, parser_version, detected_encoding, encoding_override, mapping(jsonb), snapshot_as_of, file_findings(jsonb), summary(jsonb), created_at, committed_at, reverted_at |
| `import_files` | id, batch_id, original_filename, size_bytes, sha256, storage_path, retained_until, deleted_at |
| `import_rows` | id, batch_id, file_id, row_no, raw_line(text，加密；对外只给掩码后的行), kind(trade/event/ignored), status(ok/warning/error/skipped), normalized(jsonb), findings(jsonb：`ImportFinding[]`，3.5A-1), dedup_key, dedup_status, committed_trade_id / committed_event_id。批次转为 `discarded`/`failed` 时同一事务删除该批次的行（v0.2.9 内，T-live-83a031c §8 裁定，3.5） |
| `import_mappings` | id, user_id, name, parser_id, mapping(jsonb), created_at |

**错误行报告**：预览与结果页逐行展示错误/警告（行号、掩码后的原始行、提示码、原因、建议修改）；可下载 `errors.csv`；错误行不阻止其他行确认（确认时 `mode=valid_rows_only`，见 3.5A-1）。

**手动录入**与导入共用同一成交模型、校验规则与重建逻辑；`source=manual`。

### 3.5A 已收到的范本：格式 A（成交明细 + 持仓快照）

> 2026-11-01 用户提供两份范本（成交明细、资金持仓快照），来自同一交易软件导出，**券商/软件名称待用户确认**。以下只记录**列头与结构特征**；文中所有示例值均为**虚构**（代码用 `600000/000001`、编号用 `9xxxx` 形式），**范本文件本身和其中任何真实值（股东代码、账号、证券名称与持仓组合、金额、委托/成交编号）都不进入仓库、文档、日志、测试或工单**。

**共同结构特征（实测）**
- 编码 **GBK**（非 UTF-8、无 BOM）；换行 **CRLF**；行尾有空格填充。
- **定宽、空格对齐的表格**：列起点按 **GBK 字节偏移**对齐（一个汉字占 2 字节 = 2 个显示宽度），例如证券名称 3 字与 4 字时下一列仍从同一字节偏移开始；列之间至少 2 个空格；字段内部不含空格（实测两份文件所有数据行切分后列数恒等于表头列数）。
- 表格之前可能有：一行键值摘要（持仓文件）、一行由 `-` 组成的分隔线、空行；文件末尾可能有空行或只含空格的行。
- 无"账户号/资金账号"列；含 **股东代码**（沪市以字母开头、深市纯数字——仅用于判断市场，见隐私规则）。

**文件 A1：成交明细（`kind=trades`）—— 20 列**

| 原始列头 | 标准字段 | 类型 | 单位/格式 | 必填 | 说明 |
|---|---|---|---|---|---|
| 成交日期 | `trade_date` | date | `YYYYMMDD` | 是 | |
| 成交时间 | `trade_time` | time | `HHMMSS`，**上午 10 点前会丢前导零（5 位，如 `93005`）**→ 左补零到 6 位 | 是 | 与日期合成 `traded_at`（Asia/Shanghai） |
| 证券代码 | `security_code` | string | 6 位 | 是 | 结合代码段 + 股东代码类型补后缀 `.SH/.SZ/.BJ`，再以证券主数据校验 |
| 证券名称 | `security_name_raw` | string | — | 否 | 仅用于与主数据核对，不作为主键 |
| 买卖标志 | `side` | enum | `买入`→buy，`卖出`→sell | 是 | 其他取值（如红利、配股、新股入账等）→ `account_events`，映射表待更多范本 |
| 成交数量 | `quantity` | decimal | 股；**卖出为负数** | 是 | 入库取绝对值，方向以 `side` 为准；符号与 side 不一致→错误行 |
| 成交价格 | `price` | decimal | 元，最多 8 位小数（**同一委托多笔成交合并后的均价**） | 是 | 不四舍五入，原样保存为 numeric(20,8) |
| 成交金额 | `amount` | decimal | 元，正数 | 是 | 校验 `数量绝对值 × price ≈ amount`（容差 0.05 元，实测全部满足） |
| 委托编号 | `order_no` | string | 数字串，**按交易日重新编号** | 否（强烈建议） | 只在"同账户+同日"内唯一 |
| 成交编号 | `broker_trade_no` | string | 数字串，**可能为负数**（疑似有符号整数溢出）——按**不透明字符串**处理，绝不转数值 | 否（强烈建议） | 见去重规则 |
| 发生金额 | `net_amount` | decimal | 元；**买入为负、卖出为正**（资金流向） | 是 | 校验 `net = ±amount − (净佣金+印花税+过户费+交易规费)`（买入取负，容差 0.02 元；实测全部满足） |
| 剩余金额 | `cash_balance_after` | decimal | 元 | 否 | 该笔成交后的资金余额，用于现金链对账（见对账） |
| 申报序号 | `declare_no` | string | — | 否 | 实测与委托编号相同；仅作辅助去重字段 |
| 股东代码 | `shareholder_code` | string | — | 否 | **敏感**：只用于判断市场与区分子账户，入库前做 HMAC 与掩码（见隐私） |
| 席位代码 | `seat_code` | string | — | 否 | 不入库（无业务用途，按最小化原则丢弃） |
| 净佣金 | `commission` | decimal | 元 | 否（缺省 0） | |
| 印花税 | `stamp_tax` | decimal | 元 | 否（缺省 0） | 实测仅卖出非 0 |
| 过户费 | `transfer_fee` | decimal | 元 | 否（缺省 0） | |
| 交易规费 | `other_fee` | decimal | 元 | 否（缺省 0） | 经手费+证管费合计 |
| 备注 | `biz_remark` | string | 如 `证券买入/证券卖出` | 否 | 与买卖标志交叉校验；业务类型细分的第二依据 |

> 虚构示例（UTF-8 显示，实际文件为 GBK 定宽）：
> `20260105  93005  600000  示例银行  买入  1000.00  10.00000000  10000.00  90001  90000001  -10005.20  89994.80  90001  A000000000  00000  5.00  0.00  0.10  0.10  证券买入`

**文件 A2：资金与持仓快照（`kind=positions_snapshot`）**

第 1 行为资金摘要，`键:值` 以空格分隔：

| 原始键 | 标准字段 | 类型 | 说明 |
|---|---|---|---|
| `人民币:`（前缀） | `currency`=CNY | enum | 币种行前缀；出现其他币种前缀→警告并忽略该行（MVP 只支持人民币） |
| 余额 | `cash_balance` | decimal 元 | 用于与成交明细末笔"剩余金额"对账 |
| 可用 | `cash_available` | decimal 元 | |
| 可取 | `cash_withdrawable` | decimal 元 | |
| 参考市值 | `market_value_ref` | decimal 元 | 券商口径市值 |
| 资产 | `total_assets_ref` | decimal 元 | 券商口径总资产 |
| 盈亏 | `pnl_ref` | decimal 元 | 券商口径浮动盈亏 |

随后是 11 列持仓表：

| 原始列头 | 标准字段 | 类型 | 单位 | 必填 | 说明 |
|---|---|---|---|---|---|
| 编号 | `row_seq` | int | — | 否 | 行序号，不入业务字段 |
| 证券代码 | `security_code` | string | 6 位 | 是 | 同上补后缀 |
| 证券名称 | `security_name_raw` | string | — | 否 | |
| 证券数量 | `quantity` | decimal | 股 | 是 | |
| 可卖数量 | `sellable_quantity` | decimal | 股 | 否 | 与 T+1 有关，仅展示 |
| 成本价 | `broker_cost_price` | decimal | 元，4 位小数 | 否 | **券商口径成本**：已确认为通达信的**摊薄成本**（含已实现盈亏与费用，第 9 节问题 20）；**分红计入摊薄成本**（现金红利冲减、股息红利税补缴增加，【已定 2026-11-01】问题 19）；导入后与我方重建值对账 |
| 当前价 | `last_price_ref` | decimal | 元 | 否 | 导出时刻价格，仅作对账参考，不覆盖行情 |
| 最新市值 | `market_value_ref` | decimal | 元 | 否 | |
| 浮动盈亏 | `unrealized_pnl_ref` | decimal | 元 | 否 | |
| 盈亏比例(%) | `unrealized_pnl_pct_ref` | decimal | % | 否 | |
| 股东代码 | `shareholder_code` | string | — | 否 | 敏感，同上处理 |

- 快照**没有日期列**：`as_of` 取用户在上传时确认的"导出时间"（默认上传时间，提示用户修改）；此值是对账的时间基准。
- 快照导入结果写入 `broker_position_snapshots` / `broker_position_snapshot_items`（`epistemic_type=fact`，`source_kind=user_input`，`source_ref` 指向导入批次）；**快照不直接改写持仓**，持仓仍只由成交重建；快照用于①对账，②当用户没有完整历史成交时，经用户确认后转为 `opening_positions`（期初持仓）。

**定宽解析方法（对 CJK 显示宽度稳健）**
1. 以**字节**读入 → 按编码识别结果（此格式为 GBK/GB18030）解码；保留原始字节用于定宽列切分。
2. 定位表头行：在前 30 行中找同时包含 ≥ 4 个已知列头同义词的行；表头之上的行交给"前导区解析器"（键值摘要、分隔线）。
3. 计算列边界（两种策略，结果一致才自动采用，否则进入"需人工确认"）：
   - **策略 a（显示宽度/字节偏移）**：在表头行的 GBK 字节序列上取每个列头 token 的起始偏移作为列起点；数据行同样在 GBK 字节上按"列起点 ±(该列宽度)"切片，每片 decode 后 strip。对 UTF-8 文件改用 `unicodedata.east_asian_width`（W/F 记 2，其他记 1）计算显示列位置，等价于 GBK 字节偏移。
   - **策略 b（空白分词）**：按 `\s{2,}`（以及制表符）切分，要求每个数据行 token 数 == 表头列数；这是格式 A 的主路径（字段内无空格）。
   - 任何行两种策略结果不一致或列数不符 → 记为错误行 `IMPORT_ROW_COLUMN_MISMATCH`，展示掩码后的原始行供用户确认，不猜测（判定顺序见 3.5A-1）。
4. 规范化：全角数字/符号转半角、去千分位逗号、去 `\x00` 与不可见字符、负号统一；数值一律 `Decimal`，不经过 float。
5. 跳过：分隔线（全 `-`/`=`）、空行、纯空格行、合计/小计行（首列含"合计"）。
6. 解析器以 `sniff()` 识别格式 A：表头集合包含 {成交日期, 成交时间, 证券代码, 买卖标志, 成交数量, 成交价格, 发生金额, 剩余金额} → 成交明细 0.95；首行以 `人民币:` 开头且表头含 {证券数量, 可卖数量, 成本价} → 持仓快照 0.95。解析器 ID：`tdx_trades_v1`、`tdx_positions_v1`（已确认来源为通达信导出，第 9 节问题 20；旧名 `fmt_a_trades_v1`、`fmt_a_positions_v1` 保留为别名，夹具目录名 `fmt_a/` 不改）。

**去重规则（格式 A）**
按优先级生成 `dedup_key`（全部带 `account_id` 前缀；字符串一律原样、不做数值转换）：
1. 有成交编号：`H(account_id | trade_date | market | broker_trade_no)`——成交编号可能跨日或跨市场重复，故加日期与市场；
2. 无成交编号但有委托编号：`H(account_id | trade_date | market | order_no | side | security_code)`——委托编号按日重置，故必须带日期；格式 A 中一个委托的多笔成交已合并为一行，因此"同日同委托"唯一（实测无重复）；若后续某券商按逐笔成交导出导致同一委托多行，则该解析器声明 `order_no_unique=false`，回落到规则 3；
3. 都没有：`H(account_id | traded_at | security_code | side | quantity | price | amount | net_amount)`，同一文件内完全相同的行追加序号 `#n` 以保留真实的重复成交；跨文件出现相同键时视为重复（并在预览中标出，用户可对单行"强制作为新成交"，需填写理由并记入审计）。
- 另存"弱指纹" `H(account_id | trade_date | security_code | side | quantity | price)`：当规则 1/2 的键不同但弱指纹相同（例如同一成交先手动录入、后导入）→ 标记 `possible_duplicate_of_manual`，预览中让用户选择"保留导入、作废手动"或"跳过导入行"。
- 文件级：同账户同 `sha256` 再次上传 → `IMPORT_DUPLICATE_FILE` 警告（不阻止预览）。
- 快照级：同账户同 `as_of` 的快照再次导入 → 新版本覆盖旧版本（旧版本保留，只追加）。

**对账：导入快照 vs 成交重建结果**
对账在以下时机运行：快照导入确认后、成交导入确认后（若存在快照）、手动点击"重新对账"。结果写 `reconciliation_runs` + `reconciliation_items`（只追加），并在持仓页与"今日关注"提示。

| 维度 | 我方计算 | 券商口径 | 判定 |
|---|---|---|---|
| 数量 | `opening_positions + trades + account_events` 截至快照 `as_of` 的持股数 | 快照 `证券数量` | 必须完全相等；不等→`quantity_mismatch`（重要） |
| 持仓存在性 | 我方有、券商无 / 券商有、我方无 | — | `missing_in_broker` / `missing_in_ours`（重要）——典型原因：缺期初持仓、缺分红送转/新股入账记录、导入的成交区间不完整 |
| 成本 | 我方按**摊薄成本**重建（主口径，与通达信一致：买入金额与费用计入，卖出回款冲减，**现金红利冲减、股息红利税补缴计入**，送转股只加数量；问题 19、20 已定）：摊薄成本价 =（累计买入金额 + 费用 − 累计卖出回款 − 现金红利 + 股息红利税补缴）÷ 当前持股数；另算移动加权成本只用于展示 | 快照 `成本价`（券商显示的成本价） | **每次导入确认后必做**。差额 ≤ max(0.01 元, 0.1%) → `ok`；否则 → `cost_differs`（提示性，不视为错误）。`note` 给出可能原因：缺红利入账或股息税流水（`account_events` 中该证券无 `dividend` 记录而券商成本更低）、缺期初持仓、成交区间不完整、税费行未细分（`kind=other`） |
| 现金 | 成交明细最后一笔的 `剩余金额`；以及"上一笔剩余金额 + 本笔发生金额 = 本笔剩余金额"的**连续性检查** | 快照 `余额` | 末笔剩余金额 vs 快照余额，差额 ≠ 0 → `cash_gap`；连续性断点 → `cash_chain_break`（附：断点所在日期、差额），提示"存在未包含在成交明细中的资金流水（如利息、银证转账、分红到账、费用扣收）"，建议导入资金流水或手动补录 `cash_movements` |
| 市值/总资产 | 我方数量 × 我方行情价 | `参考市值/资产` | 仅展示差异，不判定（价格时点不同） |

- 实测提示：格式 A 成交明细的"剩余金额"链在**跨交易日处**存在小额断点（数量级个位元），符合"日间有非成交资金流水"的特征——因此 `cash_chain_break` 设计为**提示 + 待补录**，而非错误。
- 展示方式：持仓页顶部"对账状态"徽标（一致/有差异/未对账）；差异列表逐项给出：差异类型、我方值、券商值、差额、**可能原因**（固定文案库，不做推断性结论）、**建议操作**（补录期初持仓 / 导入资金流水 / 补录分红送转 / 确认成本口径 / 忽略此差异并写理由）。所有差异都标注 `epistemic_type`：双方数值为 `fact`，"可能原因"为 `hypothesis`。
- 用户"忽略"某差异 → 写入 `reconciliation_items.resolution`（理由必填），不改动任何成交数据。

**隐私与敏感字段（适用于所有导入格式）**
- **股东代码**：解析时立即计算 `HMAC-SHA256(server_secret, 股东代码)` 存入 `shareholder_code_hmac`（用于识别同一子账户、区分沪深），另存掩码形式 `shareholder_code_masked`（只保留首字符类型 + `****`，如 `A****`）；**明文不入库、不进日志、不出现在 API 响应、导出与错误报告中**（错误报告中的 raw_line 也做同样掩码）。
- 席位代码、券商资金账号（若后续格式出现）：丢弃，不入库。
- `import_rows.raw_line`：入库前对已识别的敏感列做掩码；完整原始内容只存在于加密的原始文件中。
- **原始上传文件**：存放在**仓库之外**的专用存储（生产：服务器数据卷 `/srv/aia/imports/` 或境内对象存储私有桶；开发：`/var/lib/aia-dev/imports/`），**应用层 AES-256-GCM 加密（每文件独立数据密钥，主密钥来自环境变量/KMS）**，目录权限仅限应用服务账号；不经 Nginx 暴露、无公开 URL；只有文件所有者可通过 API 下载自己的原始文件；管理员无访问接口；访问与删除写审计日志；到期（默认 365 天，已定，问题 21）或用户删除/注销时物理删除。
- 仓库防护：`.gitignore` 忽略交割单常见存放目录与 `imports/`；CI 密钥与敏感信息扫描见 **7.4A**（规则 S1–S9、允许清单、夹具豁免）。`tests/fixtures/broker_statements/` 下只允许虚构文件：伴随的 `meta.json` 带 `"marker": "# SYNTHETIC"`，每个文件按 sha256 登记；`origin=generate.py` 的文件须可由脚本逐字节复现，`origin=desensitized_main` 的人工脱敏主样本须在允许清单中按 sha256 登记并经人工审核。
- 测试夹具：两份人工脱敏的主样本（`origin=desensitized_main`），其余由脚本 `tests/fixtures/broker_statements/fmt_a/generate.py` 生成**合成** GBK 定宽文件（虚构代码、虚构金额、虚构编号，刻意覆盖：5 位时间、负数成交编号、卖出负数量、3/4 字证券名称、末尾空格行、跨日现金链断点），**真实范本永不入库**。


#### 3.5A-1 导入提示码（`IMPORT_*`）完整表与判定规则（T-A01；契约 api-contract §4.1 为唯一事实来源，两处由同一份数据生成，CI 比对一致）

**口径**
- 共 **46 个码**：**21 个 error**（文件级 8、行/字段级 13）+ **25 个 warning**（文件级 10、行/字段级 15）。只有两级：`error` 阻止写入该文件或该行；`warning` 不阻止，其中 `needs_action=true` 的要用户逐项处理或在确认时统一接受默认处理。原先设想的"信息级"（如撤单行）并入 warning，用 `needs_action=false` 表示无需处理。
- `scope`：`file`（整个文件）/ `row`（一行）/ `field`（一行中的某个字段，带 `field`）。
- **对账差异不是导入提示码**：`quantity_mismatch`、`missing_in_broker`、`missing_in_ours`、`cost_differs`、`cash_gap`、`cash_chain_break` 共 **6 种**，写在 `reconciliation_items.kind`（3.5A 对账表），对账在导入确认之后运行。其中 `IMPORT_CASH_CHAIN_BREAK` 是导入时对单个文件内余额链的逐行提示，`cash_chain_break` 是对账时的汇总结论，两者并存。
- **提示对象 `ImportFinding`**（API 与 `import_rows.findings`、`import_batches.file_findings` 同构）：`{id, code, severity: "error"|"warning", scope: "file"|"row"|"field", row_no: int|null, field: string|null, message, params: object, needs_action: boolean, resolution_choices: string[], default_resolution: string|null, resolution: {choice, reason|null, by, at}|null}`。`message` 由模板和 `params` 渲染；`params` 和 `message` 中的原始值**先掩码**（股东代码、资金账号），金额等普通值照常显示给文件所有者。
- **行状态** `import_row_status`：`ok`（无提示）/ `warning`（只有 warning，照常写入）/ `error`（至少 1 个 error，不写入）/ `skipped`（撤单、废单、未识别业务、重复行：不写入，也不算错误）。`dedup_status ∈ {new, duplicate_in_db, duplicate_in_file, possible_duplicate_of_manual}`，error 行为 `null`。

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
| 46 | `IMPORT_LOT_SIZE_IRREGULAR` | warning | row | 买入数量不符合整手规则 | 仅提示（科创板 200 股起、按 1 股递增等规则按板块处理；ETF 按 100 份整数倍，v0.2.8） | 生成器 |

**判定顺序与规则（回应 T004 报告和夹具 README §8 的疑点）**
1. 文件级先判：大小、类型、空文件 → 编码 → 格式识别 → 必填列 → 账户匹配。任何文件级 error 都让整个文件进入 `failed`（上传阶段的前 4 个码直接 422、不建批次）。
2. 行级顺序：`ROW_DECODE_ERROR` → `ROW_TRUNCATED` → `ROW_COLUMN_MISMATCH`；命中其中一个就**不再做字段校验**（字段边界已不可靠）。否则**报告全部字段错误**（不只报第一个），再做跨字段校验（`SIDE_QTY_SIGN_MISMATCH`、`AMOUNT_MISMATCH`），最后是 warning 与去重。
3. **截断**：末行没有换行且列数不足 → `ROW_TRUNCATED` + 文件级 `FILE_POSSIBLY_TRUNCATED`；末行在多字节字符中间被截断 → 该行 `ROW_DECODE_ERROR` + `FILE_POSSIBLY_TRUNCATED`，其余行照常解析，**不得**因为一个坏字节把整个文件判为编码失败。
4. **"0" 视为缺失**：成交编号、委托编号、申报序号为 `0`，或成交时间为 `0`，一律视为"没有该值"（撤单行常见），不参与去重键、不报格式错误。
5. **负数成交编号**按不透明字符串处理，不报错（3.5A）。
6. **撤单、废单**：`ROW_CANCELLED` / `ROW_REJECTED`，`skipped`；这些行的数量、价格为 0 不另报 `INVALID_QUANTITY` / `INVALID_PRICE`。
7. **非成交业务**（红利入账、股息红利税补缴、新股入账、银证转账等）写入 `account_events`，不报提示码；**映射表【待范本，问题 19】**，在拿到真实写法前只识别夹具中出现的写法，股息红利税暂记 `account_events.kind=other` 并在对账说明中提示"税费类流水未细分"（摊薄成本重建时：`dividend` 冲减成本，股息红利税补缴计入成本，问题 19 已定；`kind=other` 的税费行按发生金额符号计入，真实写法待范本）；没见过的写法一律 `UNKNOWN_BIZ_TYPE`，不猜。
8. **GB18030 扩展字符**：严格按 GB18030 解码；定宽切分走 3.5A 的策略 b（空白分词）为主路径，不受字符字节宽度影响；策略 a 的显示宽度按 `east_asian_width` 计（W/F 记 2），两策略结果不一致时报 `ROW_COLUMN_MISMATCH`，不猜测。
9. **换行**：CRLF、LF、单独 CR 都接受（②已统一换行）。夹具目前没有纯 CR 文件，已请测试补一个（T-T09）。
10. 容差：`AMOUNT_MISMATCH` 0.05 元、`NET_AMOUNT_MISMATCH` 0.02 元（与 3.5A 字段表一致）；对账的成本容差见 3.5A 对账表。

**确认（两步提交）**：`POST /imports/{batch_id}/confirm {mode: "all"|"valid_rows_only", acknowledge_warnings: boolean}`
- 有文件级 error → `422 IMPORT_FILE_ERRORS{findings}`；
- `mode=all` 且有 error 行 → `422 IMPORT_ROW_ERRORS{error_rows}`；`mode=valid_rows_only` 跳过 error 行，只写 `ok`/`warning` 且 `dedup_status=new` 的行；
- 有未处理的 `needs_action` warning 且 `acknowledge_warnings≠true` → `422 IMPORT_WARNINGS_UNACKNOWLEDGED{codes}`；为 true 时对未处理项采用 `default_resolution` 并写审计；
- 最终没有可写的行 → `422 IMPORT_NOTHING_TO_COMMIT`（只有表头、全部重复、全部错误等情况）；
- 逐项处理：`POST /imports/{batch_id}/findings/{finding_id}/resolve {choice, reason}`；改编码、解析器、列映射或快照时间：`PUT /imports/{batch_id}/options`（触发重新解析，状态回到 `parsing`）。
- `errors.csv`（`GET /imports/{batch_id}/errors.csv`）只含行号、code、message、字段名和**掩码后的**原始行。

#### 3.5A-2 夹具期望结果 `expected.json`（唯一事实来源，由测试维护）
- **位置与归属**：每个夹具目录一份 `tests/fixtures/broker_statements/<dir>/expected.json`，由**测试**角色编写和维护；README §6 改为说明性文字，并注明"与 expected.json 冲突时以 expected.json 为准"。解析器测试只读 `expected.json`，不解析 README。
- **结构**（值均为占位示意）：
```json
{
  "schema_version": 1,
  "marker": "# SYNTHETIC",
  "contract": "api-contract v0.2",
  "files": {
    "<fixture>.txt": {
      "parser_id": "tdx_trades_v1",
      "encoding": "gbk",
      "batch_status_after_preview": "previewed",
      "file_findings": ["IMPORT_FILE_POSSIBLY_TRUNCATED"],
      "row_counts": {"ok": 0, "warning": 0, "error": 0, "skipped": 0},
      "rows": [
        {"row_no": 5, "status": "error", "codes": ["IMPORT_ROW_DECODE_ERROR"], "dedup_status": null},
        {"row_no": 7, "status": "skipped", "codes": ["IMPORT_DUPLICATE_IN_FILE"], "dedup_status": "duplicate_in_file", "of_row_no": 5}
      ],
      "normalized": [{"row_no": 3, "field": "trade_time", "equals": "09:30:05"}],
      "confirm": {"mode": "valid_rows_only", "result": "committed"},
      "reconciliation_kinds": []
    }
  }
}
```
- **规则**：`row_no` 为文件物理行号（从 1 起）；`file_findings` 与每行 `codes` 按**集合完全相等**比较（多报、少报都失败）；`rows` 只列有提示或被跳过的行，没列出的数据行必须是 `ok`；`normalized` 只做抽样字段断言，值一律为字符串；`confirm.result` 取 `committed` 或错误码（如 `IMPORT_NOTHING_TO_COMMIT`）。
- **CI 一致性检查**（T-O02a）：① `meta.json.files` 中每个 `.txt` 在 `expected.json.files` 中都有条目，反之亦然；② `expected.json` 中出现的每个 `IMPORT_*` 码都在契约 §4.1 表中；③ 契约表中每个码至少被一个夹具或生成器用例覆盖（标"生成器"的由 `tests/` 中的参数化用例覆盖，不要求有文件）。
- `expected.json` 不包含原始行，也不需要豁免；它照常接受密钥与敏感信息扫描（7.4A）。

### 3.6 账号与管理员审核

**状态机**
```
注册 ──> pending ──批准──> approved ──禁用──> disabled ──恢复──> approved
            └──驳回(附理由)──> rejected ──(用户可修改申请说明后重新提交, 至多 3 次)──> pending
任意状态 ──用户注销/管理员删除──> deleted
```
- **注册**：用户名（4–32 位，小写字母/数字/下划线，唯一，禁止保留词如 admin/root/system）、密码（≥ 10 位、至少含字母和数字、不得与用户名相同、不在常见弱口令表内）、可选申请说明；注册页显示固定免责提示（`disclaimer.md`），提交注册即视为已知悉；不设勾选项、不记录同意（T-A06）。无短信/邮箱验证码、无图形验证码。
- **未审核用户登录行为**：密码正确时返回 `403 ACCOUNT_NOT_APPROVED`（`details.status` 为 `pending` / `rejected`（附驳回理由）/ `disabled`），**不创建会话**；页面显示对应状态说明。为避免泄露用户名是否存在，只有在密码正确时才返回状态类错误，密码错误统一返回 `401 INVALID_CREDENTIALS`。
- **管理员**：`role=admin`；首个管理员由运维用命令行创建（`python -m app.cli create-admin`），不能通过网页注册获得；管理员接口全部在 `/api/v1/admin/*`，需 `role=admin` + 会话；所有管理操作写 `account_reviews` 与 `audit_logs`。禁用账号立即吊销其所有会话。
- **管理员能力（MVP）**：待审核列表（按申请时间）、查看申请信息（用户名、申请说明、注册时间、注册 IP 所属地粗粒度、同 IP 注册数；同 IP 注册数超过 6.1 `config/auth.yaml` 的 `admin.same_ip_highlight_threshold`（默认 3）时高亮，只作提示、不自动拦截，T-A05 D8）、批准、驳回（必填理由）、禁用/恢复（必填理由）、重置密码（生成一次性临时密码，用户下次登录强制修改）、查看审计日志。
- **管理员不可见**用户的持仓、成交、计划等个人数据（最小权限）；如需排障，须用户授权（后续）。
- **无验证码的防滥用**：
  - 注册：同一 IP 每小时 ≤ 5 次、每日 ≤ 20 次；全站 `pending` 账户数 ≥ 200 时暂停注册（返回 `503 REGISTRATION_CLOSED`）；蜜罐与最短填写时间（契约 v0.2.8 §7.1）：注册体有两个可选字段 `website`（隐藏输入，须为空或不传）和 `form_started_at`（int，表单首次渲染的毫秒时间戳，前端按服务端时钟校正）；`website` 非空或“当前时间 − `form_started_at` < 3000 毫秒”视为命中，返回与正常注册相同的状态码和响应体，但不创建用户、不消耗邀请码，写审计 `auth.register_honeypot`（不记录表单内容），仍计入 IP 限速；两字段不会触发 `extra=forbid` 的 400；3000 毫秒为固定规则，不进 `auth.yaml`。
  - 登录：同一 IP 每分钟 ≤ 10 次；同一用户名连续失败 5 次锁定 15 分钟，再失败递增（30/60 分钟，上限 24 小时）；锁定返回 `403 ACCOUNT_LOCKED` 及 `details.retry_after_s`。
  - 全局：Nginx `limit_req` + 应用层 Redis 滑动窗口；返回 `429 RATE_LIMITED` + `Retry-After`。
  - 密码哈希：argon2id（memory 64 MiB、time 3、parallelism 1，参数可配置并支持登录时透明升级）；键为 6.1 `config/auth.yaml` 的 `password_hash.*`，下限按 OWASP（m ≥ 19456 KiB、t ≥ 2、p ≥ 1），低于下限启动失败（T-A05）。
  - 修改密码/重置后吊销其他会话。
  - **会话（T-A05）**：空闲 7 天滑动过期 + 自登录起 30 天绝对过期（不续期），V1 不提供“记住我”；登录、修改密码时**轮换**会话（新 `sid` 与新 CSRF 令牌，旧会话作废）；改角色、禁用、驳回、管理员重置密码时吊销该用户全部会话。键见 6.1 `config/auth.yaml` `session.*`。
  - **邀请码（T-A05；`invite` 模式启用前由 T-B03c 实现，此前 `invite` 模式按 `closed` 处理，返回 `503 REGISTRATION_CLOSED`）**：只由管理员发放（`/admin/invites`）；128 位随机数，Crockford Base32 显示（26 字符，按 4 位分组加连字符，输入忽略大小写与连字符）；只存 HMAC 摘要，明文只在创建响应中出现一次；默认单次使用、7 天过期，可选绑定用户名，可吊销；核验与建用户在同一事务内（条件更新 `used_count`），核验失败一律返回同一种错误，不区分“不存在/过期/已用/已吊销”；发放、吊销、使用都写 `audit_logs`。不绑定邮箱（V1 无邮箱验证，绑定无法核实）。

---

## 3A. 存储与性能设计

### 3A.1 选型：业务数据与行情时序都放在 PostgreSQL 16 + TimescaleDB（同一实例）
| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| **PG16 + TimescaleDB（社区版）** | 与业务库同一实例，可做事务和 JOIN，备份恢复一套；hypertable 自动按时间分块；列式压缩（官方称 90–98%，我们保守按约 10 倍估算，**待实测**）；连续聚合（1 分钟 → 5 分钟 / 日）；保留策略自动删除旧块；Apache-2/Timescale License 社区版功能可**免费自托管** | 多一个扩展：升级需跟随扩展版本（2.29+ 支持 PG16–18）；Timescale License 禁止把它作为数据库服务对外提供（我们不涉及）；压缩块更新成本高（行情只追加，影响小） | **推荐** |
| DuckDB + Parquet | 分析查询极快，文件便宜，适合离线研究 | 单写者，不适合盘中持续写入和 100 用户并发读；与 PG 事务割裂，需要两套数据口径 | **只作可选**：内部评估模块（2.12.4）可导出 Parquet 做离线研究；不做线上存储 |
| ClickHouse / QuestDB / InfluxDB | 时序性能强 | 多一个系统要运维，不支持跨库事务；我们的数据量（几十 GB 级）用不上 | 不选 |
| 纯 PG 声明式分区 | 无扩展 | 需自写分区维护、压缩、聚合 | 作为 TimescaleDB 不可用时的回退（同一套表结构） |
| SQLite | — | 无并发写、无网络访问 | **生产禁用**；单元测试也用 PG（testcontainers） |

- **划分**：
  - `public`/业务 schema：用户、账户、成交、持仓、计划、策略、信号、建议、审计，都是普通 PG 表。
  - `market` schema：`minute_bars`、`realtime_quotes`、`daily_bars`、`factor_values`、`feature_bars_daily` 为 **hypertable**；`moneyflow`、`events` 等其余表为普通表或按月分区。
  - `evaluation` schema：内部评估结果。
- **镜像**：`timescale/timescaledb:2.x-pg16`，版本固定。避开已知有问题的小版本 PG 16.5 和 17.1（官方提示），上线前用 `pg_upgrade` 演练。

### 3A.2 数据量估算（假设已写明，**待 T003 与实测校准**）
**假设**：
- 全 A 约 5,400 只；每日 240 根 1 分钟 bar；每年 242 个交易日。
- 1 分钟 bar 一行约 110 B（含索引），日 K 一行约 100 B。
- 因子按宽表存，每行约 400 B（85 列）。
- 压缩比按 10 倍估。
- 候选信号每条约 1.5 KB（证据用"快照证据条目"去重引用后）。
- 100 用户：每人自选 100 只，去重后约 4,000 只，每日扫描产出约 3 万条候选信号（多数被冷却合并后不生成卡片）；建议卡每日约 2 万条，每条约 1 KB。

| 数据 | 1 年（未压缩 / 压缩后） | 3 年 | 5 年 | 说明 |
|---|---|---|---|---|
| 1 分钟 K：全市场 | 34.5 GB / 约 3.5 GB | 103 / 约 10 GB | 172 / 约 17 GB | 5,400 × 240 × 242 × 110 B |
| 1 分钟 K：跟踪池 1,500 只 | 9.6 / 约 1 GB | 29 / 约 3 GB | 48 / 约 5 GB | 推荐默认保留范围 |
| 1 分钟 K：universe 4,000 只 | 25.6 / 约 2.6 GB | 77 / 约 8 GB | 128 / 约 13 GB | |
| 日 K（全市场，含复权因子） | 0.13 GB | 0.4 | 0.65 | 不压缩也很小 |
| 因子（宽表，全市场每日） | 0.5 GB / 约 0.1 | 1.6 | 2.6 | 若存长表约 8.9 GB/年，不采用 |
| 实时快照（降采样为 1 分钟，仅保留 10 日） | 约 1 GB 常驻 | — | — | 保留策略滚动删除 |
| 候选信号 + 事件 | 约 11 GB（TOAST 压缩后约 4–5 GB） | 约 33 | 约 55 | 业务表，不压缩，不删除（审计）；超过 1 年的转存冷分区 |
| 建议卡与版本 | 约 7 GB | 约 21 | 约 35 | 同上 |
| 快照与证据条目 | 约 5 GB | 约 15 | 约 25 | 证据按 `(provider, endpoint, symbol, field, ts)` 去重 |

**结论**：
- 推荐方案：1 分钟 K 全市场保留 1 年、跟踪池保留 3 年，压缩后合计约 7 GB；业务数据 3 年约 70 GB。
- 加上索引、WAL 和备份余量，**服务器 SSD ≥ 300 GB**，内存 16 GB（PG `shared_buffers` 4 GB）。
- 保留期是第 9 节问题 28。

### 3A.3 预计算与缓存
- **预计算表**（盘后批与盘中增量）：
  - `market.feature_bars_daily`：唯一特征管线产出，每列登记在 `feature_catalog`。
  - 连续聚合 `market.bars_5m`、`market.bars_daily_from_1m`：用于校验日 K。
  - `portfolio_daily_snapshots`：持仓市值、收益、集中度。
  - `strategy_stats_daily`：胜率、n、权重。
  - `review_stats_monthly`。
- **Redis 键与 TTL**：

  | 键 | TTL | 写入方 | 失效 |
  |---|---|---|---|
  | `q:{symbol}` 最新快照 | 3 × `quote_interval_s` | `ingest` | 覆盖写 |
  | `bars1m:{symbol}:{date}` 当日分钟线 | 当日收盘 + 1 小时 | `ingest` | 追加写 |
  | `feat:{symbol}:{date}` 当日特征 | 24 小时 | `worker`/`signal-rt` | 管线版本变化时 `feature_set_version` 前缀整体切换 |
  | `dash:{user_id}` 仪表盘聚合 | 30 秒 | `api` | 收到 `portfolio.changed`、`signal.created`、`plan.changed` 时删除 |
  | `kline:{symbol}:{period}:{window}` | 日线 6 小时；分钟 60 秒 | `api` | 收到 `market.updated` 时按 symbol 删除 |
  | `stats:{strategy_version}` | 1 小时 | `worker` | 跟踪任务完成时删除 |

  失效机制统一走 Redis pub/sub 事件（写入方在**事务提交后**发布）。缓存只是加速层，缓存缺失时回源 PG，**不回源麦蕊**。

### 3A.4 前端：分页、虚拟化、K 线窗口加载
- **游标分页**（契约 §1.2）：所有列表默认 `limit=50`（最大 200），游标为 `(sort_key, id)` 的不透明编码；不用 offset。
- **虚拟化表格**：AG Grid 行虚拟化（DOM 中只保留可见行）。实时更新只推送变化行（`applyTransactionAsync`），每 250 ms 批量刷新一次。
- **K 线窗口加载**：首屏只取可视窗口，日线约 250 根、分钟约 1 日；左滑到边缘时按 `before=<ts>&limit=500` 取前一窗口。分钟数据超过 5 日时自动切换为 5 分钟聚合。图表实例复用，不重建。

### 3A.5 关键查询 P95 目标（服务端，含序列化；100 并发用户、数据为 3 年规模）
| 查询 | P95 目标 | 手段 |
|---|---|---|
| 仪表盘首屏 `/today` | ≤ 300 ms（命中缓存 ≤ 80 ms） | `dash:{user}` 缓存 + 预计算快照 |
| 持仓列表（≤ 200 行，带实时价） | ≤ 150 ms | 持仓表加 Redis `MGET` 快照 |
| 单股 K 线：日线 1 年 | ≤ 120 ms | `(security_id, ts DESC)` 索引 + 缓存 |
| 单股 K 线：1 分钟 5 日（约 1,200 根） | ≤ 200 ms | hypertable 按时间裁剪块 + 当日 Redis |
| 候选信号或建议列表（游标分页 50 条） | ≤ 150 ms | `(user_id, created_at DESC, id)` 索引 |
| 建议或信号详情（含证据，约 50 条） | ≤ 200 ms | 证据按主键批量取 |
| 复盘统计（策略 × 周期，附 n） | ≤ 500 ms | `strategy_stats_daily` 预聚合 |
| SSE：数据写入到推送到达 | ≤ 2 s | pub/sub 直推 |
| 证券搜索 `/securities/search`（`limit` 20；v0.2.9 内，T-A04） | ≤ 100 ms ◇ | `security_search_terms` 的 `text_pattern_ops` 前缀索引 + trgm 索引（4.6.2）；结果缓存 60 s |

### 3A.6 索引与分区
- **行情**：
  - hypertable 块间隔：1 分钟 K 为 1 天，日 K 和因子为 1 年。
  - 主键 `(security_id, ts)`，额外索引 `(security_id, ts DESC)`。
  - 压缩策略：`segmentby = security_id`、`orderby = ts DESC`，7 天后压缩。
- **业务**：
  - `candidate_signals (user_id, created_at DESC, id)`、`(strategy_instance_id, created_at DESC)`、`(security_id, created_at DESC)`；
  - `non_executable_reasons` 的部分索引 `(check_on, next_check_at) WHERE status = 'active'`（解除监控只扫活跃行）；
  - `plan_drafts (user_id, status, expires_at)`；
  - `suggestions (user_id, created_at DESC)`；
  - `notifications (user_id, read_at NULLS FIRST, created_at DESC)`。
  - JSONB 证据**不**建 GIN 索引（按 id 取），只在 `evidence_items(provider, symbol, field, ts)` 建 B-tree。
- **审计与大表**：`candidate_signals`、`suggestion_versions`、`audit_logs` 按月声明式分区，便于冷热分离和转存。

### 3A.7 性能验证
- **T-T08**（扩展）：
  - locust 模拟 100 用户的典型行为（仪表盘轮询、列表翻页、详情、K 线），同时 `ingest` 回放一整天的盘中数据；
  - pgbench 测试自定义查询；
  - 断言 3A.5 中的 P95 目标、SSE 延迟和 `ingest` 队列等待时延。
- **数据**：用合成数据生成器造出 3 年规模的数据（字段分布仿真，**不含任何真实用户数据**）。
- **门禁**：P95 任一项超标即阻断发布；每个版本保留基线并比较，回退超过 20% 时告警。

---

## 4. 麦蕊接口映射、配额估算、缓存与资讯缺口（验收项 4）

### 4.0 T003 实测结果摘要（报告 2026-11-01 12:10 MDT 收到，本节据此更新）
> 来源：`/workspace/team/reports/T003-mairui-capability.md`。T003 在第 26 次带证书调用后，因"同一证书 60 秒内超过 2 个不同 IP"被拒（HTTP 429，正文为纯文本 `103:…`），按规则停止了全部调用。**因此只有"实时快照"完整实测、"K 线"部分实测，其余仍是"文档有据、未实测"。**本文其他位置的【待 T003 验证】标记含义相应细分：下表"已实测"的项视为**已验证**；其余项改读作**【待 T003 补测】**（需在交易日、固定出口的唯一调用方上补测，即任务 T-B05）。

| 项 | T003 结论 | 对本方案的影响 |
|---|---|---|
| 实时快照（单股/五档/多股/全市场两套） | **已实测可用**。多股接口 ≤20 只/次（第 21 只返回 HTTP 200 + `{"error":…}`）；全市场券商源约 7,970 条、网络源约 5,923 条，约 1.2–1.3 s / 1.9 MB | 0A.6 的 a/b/c 三路方案成立；盘中延迟**未测**（周日），刷新间隔默认值仍待补测 |
| 日/周 K、5 种复权 | **已实测**：日线回溯至上市日；`lt` 只允许 1–5（`lt=10` → 422） | 回补用 `history` 接口带 `st/et`，不用 `latest` 的 `lt` 拉长窗口 |
| 分钟 K | 5 分钟实测可用但**不回溯到 2020**；分钟线传前复权 `f` → 503（数据缺失，不是限流）；1 分钟 Pro **未测** | 分钟线只存不复权（`n`），复权由本地按除权因子计算；`ingest` 必须按响应体区分"数据缺失 503"与"限流 503" |
| **错误返回格式** | 业务错误多为 **HTTP 200 + `{"error": "..."}`**；103 为 HTTP 429 + 纯文本；无任何限流响应头 | `ingest` 的响应解析：先检查 body 中的 `error`，再看状态码；103/101/频率类 503 → 熔断 ≥60 s 并告警（与 2.1A 一致） |
| 2 IP / 60 s 限制 | **已实测触发**。根因：开发 box 的出口 IP 随 TCP 连接变化 | 印证"唯一 `ingest` + 固定出口 + 单个 keep-alive 会话串行"的设计；**开发 box 不能作为调用方**，部署前要连续多次回显出口 IP 确认不变；切换冷备时新旧 IP 合计不超过 2 个且旧主先停 |
| 配额 | 文档：钻石版 6,000 次/分钟、每日不限；全市场 1 次/分钟（更新日志另称约 3 次/分钟）；因子按 1/3/5/10 计次 | 维持自设预算 3,000/分钟、并发 1；配额不是瓶颈，**瓶颈是串行延迟（约 0.25 s/次，复用连接）和全市场 1 次/分钟** |
| 延迟 | 26 次中小包 p50≈328 ms、p95≈1,069 ms；新连接首包约 1 s | 必须复用连接；按 0.26 s/次估算，每轮多股刷新 50 次约 13 s，与 0A.6 默认 15 s 一致 |
| 资金流、股池、龙虎榜、财务 `plrq`、因子空值、板块、公告、稳定性 | **均未实测**（文档有据） | 相关结论保持【待 T003 补测】；探针脚本已由后端准备 |
| 集合竞价 | 文档只有**盘后**竞价量；**无盘中 9:15–9:25 竞价撮合数据** | 0A.3 的竞价时段**不刷新展示**（改为显示上一交易日收盘快照并标注），日内做 T 不使用竞价信号 |
| 板块实时 | 未发现板块盘中实时涨幅接口 | 板块盘中涨幅由成分股快照**本地聚合**（成分周更，标注滞后） |
| 因子 | 全部日频；文档声明 north_* 三个为空，attention_score、ev_ebitda 可能为空；数量 77/82/85 说法不一 | feature_catalog 将上述因子标 `gap`，不允许被任何规则引用（G1 自动拒绝）；因子不用于盘中 |
| 新闻 | **文档无新闻/资讯/研报接口**；公告只有标题+链接、盘后更新 | 与 4.5 的新闻缺口方案一致 |
| **数据疑点** | 某只示例股票的日线出现 `sf=1, v=0, a=0, o=h=l=c` 的"伪停牌"占位行，而同期快照显示正常成交 | 新增数据质量检查：日线 `sf=1` 且当日快照有成交 → 标 `suspect`，不进入指标与跟踪计算，告警并在 T-B05 交叉核对（见 T-B05a） |

### 4.1 麦蕊通用事实
> **【待 T003 验证】本节所有数据可用性结论**（接口、字段、因子、限流、历史深度、刷新间隔、上限推算）都来自文档推导，须以后端实测报告 `/workspace/team/reports/T003-mairui-capability.md` 为准；报告出来后逐项替换本节标记。

| 事项 | 内容 | 状态 |
|---|---|---|
| 调用方式 | HTTP GET，`https://api.mairuiapi.com/{路径}/{licence}`（licence 放在 URL 路径末尾）；少数 POST（因子 batch/screen）；Pro 完整历史分钟线域名 `pro.mairuiapi.com` | 【文档已列·待 T003 验证】 |
| 钻石版配额 | ¥1088（原价 1888），每日请求不限、总请求量不限、期限 3 年；**过期后限制每日 20000 次** | 【价目页已列·待 T003 验证】 |
| 钻石版频率 | 常规接口"钻石版 1 分钟 6 千次"（免费 300、包月/体验 1000、包年 3000） | 【各接口页已列·待 T003 验证】 |
| 全市场实时快照 | `/hsrl/ssjy/all`（券商源）、`/hsrl/real/all`（网络源）：仅包年/钻石或 Quant Pro 可用；接口页写"限制每分钟请求 1 次"，增强包页/更新日志写"约 3 次/分钟" | 【待 T003 验证：设计按 1 次/分钟】 |
| IP 限制 | 同一证书 60 秒滑动窗口内最多 **2 个不同来源 IP**；超出 HTTP 429 / 错误码 103 | 【FAQ/帮助已列·待 T003 验证】 |
| 错误码 | 404 路径错误；503 请求过于频繁/单 IP 多线程/多 IP 同证书；101 当日超限；102 licence 无效；103 IP 超限(429)；因子接口未开通返回 403 | 【FAQ已列·待 T003 验证】 |
| Quant Pro | 1 分钟 K（`/pro/` 路径，lt 最大 5）、完整历史分钟 K（`pro.mairuiapi.com/.../history/full/...`，60 次/分钟）、全市场实时、因子包；Pro 期限独立于基础证 | 【文档已列·待 T003 验证】 |
| 因子数量 | 首页/增强包页写 77 因子、19 接口；因子文档页与 2026-09-02 更新日志写 85 因子（含 8 个日内因子）；`north_*` 3 个字段按设计返回空 | 【待 T003 验证：以 `/factor/list` 实测为准】 |
| 用户证书有效期 | 钻石版 + Quant Pro 至 2027-09-11 | **【已定 2026-11-01】用户确认有效期至 2027-09-11**（问题 5）；T-B05 仍用 `/query` 记录实测值备查 |
| 实测 | 未持有 licence，**没有做任何真实调用**；字段、延迟、空值情况均需 T0xx 联调任务验证 | 【待 T003 验证】 |

### 4.2 各能力使用的接口（路径均省略前缀 `https://api.mairuiapi.com` 与末尾 `/{licence}`）
> **【待 T003 验证】本节所有数据可用性结论**（接口、字段、因子、限流、历史深度、刷新间隔、上限推算）都来自文档推导，须以后端实测报告 `/workspace/team/reports/T003-mairui-capability.md` 为准；报告出来后逐项替换本节标记。

| 能力 | 用途 | 接口路径 | 文档标注更新时间 |
|---|---|---|---|
| 基础 | 沪深股票列表 | `/hslt/list` | 每日 06:20 |
| 基础 | 京市股票列表 / 科创列表 | `/bj/list/all`、`/kc/list/all` | — / 每日 16:20 |
| 基础 | 交易日历 | `/tcalendar/list/{year}` | 每交易日 |
| 基础 | 股票基础信息 | `/hsstock/instrument/{code.市场}` | 每日 01:00 |
| 1 | 指数列表 / 实时 | `/hsindex/list`、`/hsindex/real/time/{code}` | 每日 0 点 / 实时 |
| 1 | 全市场实时快照（估值持仓、涨跌家数） | `/hsrl/ssjy/all` | 实时（1 次/分钟） |
| 1 | 多股实时（≤20 只） | `/hsrl/ssjy_more?stock_codes=...` | 实时 |
| 1 | 单股实时（券商源）/ 五档 | `/hsstock/real/time/{code}`、`/hsstock/real/five/{code}` | 实时 |
| 1 | 日 K / 分钟 K（5/15/30/60/d/w/m/y） | `/hsstock/latest/{code.市场}/{级别}/{除权}?lt=`、`/hsstock/history/{code.市场}/{级别}/{除权}?st=&et=&lt=` | 日线 15:30–17:10 |
| 1 | 指数 K 线 | `/hsindex/history/{code.市场}/{级别}?st=&et=` | — |
| 1 | 行业/概念树、成分、股票所属 | `/hszg/list`、`/hszg/gg/{code}`、`/hszg/zg/{code}`；申万一级 `/hslt/primarylist`、`/hslt/sectors/{板块名}`；概念 `/hslt/sectorslist` | 每周六 / 每日 16:20 |
| 1 | 行业/概念资金流 | `/hibk/zjhhy`、`/hibk/gnbk`、`/hizj/zjh`、`/hizj/bk` | 每日 15:40 |
| 1/4 | 涨停/跌停/炸板池 | `/hslt/ztgc/{date}`、`/hslt/dtgc/{date}`、`/hslt/zbgc/{date}` | 盘中每 10 分钟 |
| 1/4 | 公告（标题/摘要/原文链接/类型） | `/hsstock/announcement/{code}?st=&et=&lt=` | 交易日盘后 |
| 1/4 | 问董秘 | `/hsstock/interactiveqa/{code}?st=&et=&lt=` | 交易日盘后 |
| 1/4 | 今日交易提示（停牌、股东大会、沪/深交所公告概览等） | `/hitc/jrts` | 每日 15:40 |
| 1/4 | 解禁（个股 / 全市场前后 15 天） | `/hscp/jjxs/{code}`、`/hitc/jjxs` | 03:30 / 15:40 |
| 1/4 | 业绩预告 / 快报（全市场按季度） | `/hicw/yjyg/{year}/{q}`、`/hicw/yjkb/{year}/{q}`；个股 `/hscp/yjyg/{code}` | 每日 20:10 / 03:30 |
| 1/4 | 龙虎榜 | `/hilh/mrxq`、`/hilh/ggsb/{n}` | 20:00 / 15:40 |
| 2 | 财务三表 / 主要指标 | `/hsstock/financial/{balance\|income\|cashflow\|pershareindex}/{code.市场}?st=&et=` | 每日 0 点 |
| 2 | 公司简介、分红、十大股东、股东户数 | `/hscp/gsjj/{code}`、`/hscp/jnfh/{code}`、`/hsstock/financial/topholder/{code}`、`/hsstock/financial/hm/{code}` | — |
| 2 | 个股资金流（日频，区间≤365 天） | `/hsstock/history/transaction/{code}?st=&et=` | 盘中约 30 分钟 |
| 2 | 行情指标（量比、换手等） | `/hsstock/indicators/{code.市场}?st=&et=` | 16:30–20:00 |
| 2 | 因子元数据 / 分类 | `/factor/list`、`/factor/categories` | 元数据变更时 |
| 2 | 多因子筛选（POST，计 10 次） | `/factor/screen` body: conditions/order_by/page/page_size/fields/trade_date | 最新截面 |
| 2 | 批量因子（POST，≤50 码×≤20 因子，计 10 次） | `/factor/batch` | 最新截面 |
| 2 | 单股全因子 / 主题因子 | `/factor/all/{code}`、`/factor/{valuation\|quality\|growth\|momentum\|capital\|signal\|risk\|dividend\|scale\|sentiment\|intraday}/{code}` | 交易日 16:30 后 |
| 2 | 因子分位 / 历史 / 排名 | `/factor/percentile/{factor_id}/{code}`、`/factor/history/{factor_id}/{code}`、`/factor/rank/{factor_id}`、`/factor/top/{factor_id}/{n}` | 日终 |
| 3/4 | 1 分钟 K（Pro） | `/hsstock/pro/latest/{code.市场}/1/n?lt=`（lt≤5）、`/hsstock/pro/history/{code.市场}/1/n?st=&et=&lt=` | 盘中增量 |
| 3 | 涨跌停价 | `/hsstock/stopprice/history/{code.市场}?st=&et=` | 每日 0 点 |
| 5 | 基准与行业指数历史 | `/hsindex/history/...`、行业成分 | — |
| 5 | 历史日 K（结果计算） | `/hsstock/history/...` | — |

京市（`/bj/...`）有对应的实时、历史分时、财务接口；**京市公告/问董秘接口文档未见**【待 T003 验证】。

**研究候选 RC4 的行业与停牌数据来源（v0.2.9 内，T-O11 评审裁定）**（只读麦蕊公开文档，未用任何证书调用；未实测的标【待核实】）：

| 数据 | 麦蕊接口（文档所载更新时间） | 落库 | 采集方 | 状态 |
|---|---|---|---|---|
| 申万一级行业归属 | 主：`/hszg/zg/{code}`（个股所属指数、行业、概念，每周六 11:00）；行业树 `/hszg/list`（每周六 03:05）；备选 `/hslt/primarylist`、`/hslt/sectors`（申万一级，每周六 / 每日 16:20） | 按证书的行业归属表（带 `source_licence_id`，与 3.3 `market.securities` 说明一致），表名与字段由后端在 T-B43 设计【待定】；一级行业代码格式【待核实】 | `ingest`（全站唯一调用麦蕊），周更 | 【待核实，T-B05 实测】 |
| 停牌 | 主：日 K 的 `sf` 字段（1 停牌，0 不停牌），随日 K 采集；补充：`/hitc/jrts` 今日交易提示的停牌列表 `tp`（每日 15:40） | 日 K 行上的停牌标记，或 `market.market_events`（新增 `suspension` 类型）；由后端在 T-B43 选定【待定】 | `ingest`，日更 | 【待核实，T-B05 实测】 |

接入前 RC4 对行业集中与停牌照常出 gap（不判定、不静默），`exposure.sector` 仍为未知。

### 4.3 调用频率与配额估算（钻石版，1 分钟上限 6000；我们自设上限 3000/分钟）
> **【待 T003 验证】本节所有数据可用性结论**（接口、字段、因子、限流、历史深度、刷新间隔、上限推算）都来自文档推导，须以后端实测报告 `/workspace/team/reports/T003-mairui-capability.md` 为准；报告出来后逐项替换本节标记。

假设：全市场约 5,500 只 A 股【待 T003 验证：以 `/hslt/list` + `/bj/list/all` 实测为准】；"被跟踪证券池" P = 所有用户持仓 ∪ 观察 ∪ 有效候选 ∪ 有效计划，MVP 估 P ≤ 1,000。

| 任务 | 时间（北京时间） | 调用量/日 | 说明 |
|---|---|---|---|
| 主数据：股票列表、交易日历、指数列表、板块列表 | 06:30 | ~10 | |
| 行业/概念成分 | 每周六 12:00 | ~600/周 | 树叶子节点数【待 T003 验证】 |
| 全市场实时快照 | 交易时段每 1 分钟 | ~240 | 1 次/分钟限制；供持仓估值、涨跌家数、价格类提醒 |
| 盘中实时（快照 + Pro 1 分钟 K） | 盘中持续 | 见 0A.6 | 已由主线实时链路取代，按 0A.3 分层与配额推导 |
| 涨跌停池 | 盘中每 10 分钟 + 收盘 | ~80 | |
| 日 K（全市场收盘后增量） | 17:30 | ~5,500 | `latest/{code}/d/n?lt=1`；或直接用 15:05 全市场快照落日线（1 次）并于次日校验 |
| 个股资金流（被跟踪池） | 17:30 | ~1,000 | |
| 因子截面（全市场） | 17:00 后 | ~110 次×计 10 = 1,100 计数 | `/factor/batch` 50 只/次；只取已启用模板 `data_needs` 中（2.5.14）用到的因子 |
| 公告 / 问董秘（被跟踪池） | 18:00、次日 07:30 | ~4,000 | 每只 2 接口 × 2 轮 |
| 财务三表+指标（被跟踪池，季报期加密） | 01:30 | ~4,000 | 平时每周一次全量，季报披露期每日 |
| 全市场榜单/事件（龙虎榜、业绩预告、解禁、资金流、jrts） | 15:45、20:15 | ~30 | |
| 按需拉取（用户打开冷门个股） | 随用户 | ~2,000（估） | 每只每日首次访问才触发，~~之后全站共享~~（v0.2.6 起按证书各取，2.1B） |
| **合计（仅盘后与按需部分）** | | **≈ 2.5–3.5 万次/日** | 盘中实时链路另计，见 0A.6：按 universe 4,000 只、15 秒快照、Tier-1 每分钟 1 分钟 K 推导，**全日约 63–64 万次**，峰值按 `per_minute_budget`（默认 3,000/分钟）控速；钻石版每日不限【文档已列·待 T003 验证】，瓶颈是**每分钟速率**与**2 个 IP** |

**风险提示**：若证书过期（2027-09-11 后）降为每日 20,000 次，上述量会超限 → 须续费或启用降级模式（只拉被跟踪池、关闭分钟级提醒）。网关内置"日计数器"与降级开关。

### 4.4 缓存策略

- ~~**共享**：所有行情/基本面/公告数据与用户无关，全站一份；用户数增长不增加外部调用（只增加被跟踪池 P）。~~
- **按证书隔离（v0.2.6 起；契约 v0.2.7 §1.1）**：麦蕊来源的行情、基本面、公告按 `source_licence_id` 各存一份，每位用户只读本人证书的数据（2.1B）；只有证券公开主数据（代码、简称、拼音、曾用名、交易所、板块、上市日、状态、风险警示，第 9 节问题 51）全站一份。用户数增长会增加外部调用（每张证书各自的被跟踪池）。
- **两级**：Redis 热缓存（实时/当日）+ PostgreSQL 持久（历史与快照依据）。
- **请求合并**：同一 `endpoint+params` 在途请求用 Redis 锁去重（singleflight）。

| 数据类型 | Redis TTL | 持久化 | 刷新方式 |
|---|---|---|---|
| 全市场实时快照 | 交易时段 60s；收盘后至次日开盘 | 收盘后落 `daily_bars`（当日） | Beat 每分钟 |
| 单股实时/五档 | 30s（仅按需） | 否 | 按需 |
| 1 分钟 K | 60s | 仅提醒触发时写入快照 | 按需/被跟踪池 |
| 日 K | 至下一交易日 17:30 | 是 | 盘后批量 |
| 指数实时 | 60s | 收盘落库 | Beat |
| 资金流（个股/板块） | 至下次更新（盘中 30 分钟，盘后至次日） | 是 | 盘后批量 |
| 涨跌停池 | 10 分钟 | 是（事件） | Beat |
| 因子截面 | 至下一交易日 17:00 | 是（策略库用到的因子） | 盘后批量 |
| 财务报表 | 24h | 是（变化留痕） | 夜间批量 |
| 公告/问董秘 | 6h | 是（`first_seen_at`） | 盘后+早盘两轮 |
| 股票列表/交易日历/板块树 | 24h / 7d | 是 | 每日 / 每周 |
| 公司简介等静态 | 7d | 是 | 按需 |

### 4.5 公告/新闻资讯缺口与补充方案
> **【待 T003 验证】本节所有数据可用性结论**（接口、字段、因子、限流、历史深度、刷新间隔、上限推算）都来自文档推导，须以后端实测报告 `/workspace/team/reports/T003-mairui-capability.md` 为准；报告出来后逐项替换本节标记。

**核实结论**：首页未展示，但麦蕊文档【文档已列·待 T003 验证】提供：
- `交易所公告数据` `/hsstock/announcement/{code}`：字段 `t`(时间)、`zq`(代码)、`zt`(主题)、`zy`(摘要)、`gs`(格式)、`nr`(公告链接，示例为 PDF URL)、`jb`(级别)、`lx`(0 其他/1 财报类)；交易日**盘后**更新；2026-07-18 上线（"冷盘静态分发"）。
- `问董秘数据` `/hsstock/interactiveqa/{code}`；`今日交易提示` `/hitc/jrts`（含 `shgg`/`szgg` 交易所公告概览、停牌、股东大会等）。

**仍存在的缺口**：
1. **无新闻/快讯/研报接口**（未在任何文档页找到）。
2. 公告为**盘后**批量，非实时；历史回溯深度、覆盖完整性、京市是否覆盖、`nr` 链接指向哪里（交易所/巨潮）均【待 T003 验证】。
3. 只有标题/摘要/链接，无正文结构化（如减持比例、问询函要点）。
4. 监管处罚、问询函、交易所监管措施没有单独分类。

**补充方案（按优先级）**：
| 方案 | 内容 | 授权/合规说明 | 建议 |
|---|---|---|---|
| A. 麦蕊公告 + 原文外链（MVP 采用） | 展示标题、时间、类型；正文一律**跳转原始链接**（交易所/巨潮 PDF），不在本站转存全文 | 仍受麦蕊再分发条款约束（见 7.1）；外链原文不涉及复制 | MVP |
| B. 巨潮资讯网（深圳证券信息有限公司） | 证监会指定信息披露网站，提供"巨潮公告"等授权产品及 webapi.cninfo.com.cn 数据服务 | 官网"信息授权"页写明：欲成为合法信息提供商须向其数据营销部申请（xxsq@cninfo.com.cn）。**未经授权的批量抓取后对公众展示不建议**；价格【待询价】 | Phase 3 评估 |
| C. 交易所官网（上交所/深交所/北交所披露页、上证 e 互动、深交所互动易） | 法定披露原始来源 | 仅建议**外链**；自动抓取的使用条款【待核实】 | 外链即可 |
| D. Tushare Pro | 有公告/新闻类接口，积分/付费制 | 对外商业再分发许可【待核实】，需书面确认 | 可选 |
| E. AKShare | 开源库，数据来自公开网站抓取 | 代码开源不代表数据可商用；**不建议用于对外多用户产品** | 仅内部研究 |
| F. 持牌资讯商（如财联社、Wind、同花顺 iFinD、东方财富 Choice、深圳证券信息"全景快讯"等） | 新闻快讯与结构化公告 | 需签商业授权，价格【待询价】 | 若做新闻能力再采购 |

**情绪面缺口**（与消息面同类）：麦蕊没有股吧/搜索/社交热度数据；`attention_score` 按文档基于问董秘活跃度，不代表市场热度【文档已列·待 T003 验证】。MVP 情绪维度只用涨跌停、炸板、连板、封单、竞价量比、龙虎榜与市场宽度（2.5.2）；舆情数据如需补充，只考虑**持牌资讯商的授权产品**（价格与条款【待询价】），**不爬取股吧/社区**。

MVP 明确写入产品：**"本产品不提供新闻资讯；公告信息为盘后更新，可能存在延迟与遗漏，请以交易所/巨潮原文为准。"**

---

### 4.6 证券主数据、对账与搜索（v0.2.9 内，T-A04）

依据 `docs/data-sources/security_master.md`（T007）与 2.1B。契约同步见 api-contract v0.2.9 #33。本节只定设计，不含任何证书值；交易所列表的拉取不用证书，也不经过 `ingest`。

#### 4.6.1 来源与优先级

| 优先级 | 来源 | 用途 | 能做什么 |
|---|---|---|---|
| 1（权威） | 上交所、深交所、北交所公开列表：当前上市名单、终止上市名单、暂停/退市整理期名单、深交所简称变更（SSGSGMXX）、北交所新旧代码对照 | 建档、简称、上市/退市日期、板块、状态、曾用名、旧代码 | 唯一可以新建证券、改状态、写 `delisted` 的来源 |
| 2（补缺） | 巨潮资讯 | 交易所列表缺上市日期等字段时补上 | 只填空值，`field_sources` 记 `cninfo`；与交易所值不同 → 只记 `field_mismatch`，不覆盖 |
| 3（核对） | AKShare | 每周交叉核对 | 只记差异，不写主数据 |
| 对账方 | 麦蕊 `/hslt/list`、`/bj/list/all`、`/kc/list/all`（代码集 = 三者并集）；`/hsrl/real/all`（只用于 `quote_conflict`）；`ssjy` 只做统计、不对账 | 按证书对账（2.1B） | 不新建、不删除、不改状态；结果只进 `security_reconciliation_diffs` |

- **退市判定只认交易所**：`delisted` 只来自交易所终止上市名单（带终止上市日期）；简称带“退”且仍在当前上市名单 → `delisting_period`；从当前上市名单消失、又不在终止上市名单 → 连续 `master.missing_after_snapshots`（默认 2）份成功快照都没有才置 `missing_from_list`，不推断退市；重新出现即恢复原状态。
- **风险警示**：`risk_flag` 由交易所简称前缀推出（`*ST`、`ST`、`退` 等，T007 §5），变化写入 `security_risk_flag_history`。
- **曾用名**：深交所用 SSGSGMXX 回填全部历史；上交所、北交所从上线日起按每日快照比对积累（上线前的曾用名不回填，问题 90）；北交所旧代码来自代码对照表（每月拉一次）。

#### 4.6.2 表（schema `market`；全站一份，不按证书）

| 表 | 列 | 主键、唯一约束与索引 |
|---|---|---|
| `securities` | 3.3 字段表 `market.securities` 已列的列，另加 `missing_since date null`（进入 `missing_from_list` 的快照日期）、`last_seen_on date`（最近一次出现在交易所当前名单的快照日期）、`field_sources jsonb`（字段 → `exchange`/`cninfo`，如 `{"list_date":"cninfo"}`） | PK `code`；`check (listing_status in 契约 §3 listing_status)`；btree `(exchange, listing_status)`；原 `name_norm`/`name_initials` 上的 gin 索引在迁移中删除（检索改走词条表） |
| `security_name_history` | `code`、`name`、`valid_from date`、`valid_until date null`（半开区间，null 表示至今）、`source`（`szse_ssgsgmxx`/`exchange_diff`）、`snapshot_id` | PK `(code, valid_from)`；排除约束 `exclude using gist (code with =, daterange(valid_from, valid_until, '[)') with &&)`（迁移中 `CREATE EXTENSION IF NOT EXISTS btree_gist`）；btree `(name)` |
| `security_code_history` | `code`（当前代码）、`old_code`、`valid_from`、`valid_until`、`source`（`bse_code_map`） | PK `(code, valid_from)`；唯一 `(old_code)`；排除约束同上 |
| `security_risk_flag_history` | `code`、`risk_flag`、`valid_from`、`valid_until`、`snapshot_id` | PK `(code, valid_from)`；排除约束同上 |
| `security_listing_status_history` | `code`、`listing_status`、`valid_from`、`valid_until`、`snapshot_id`、`reason`（`exchange_list`/`exchange_delist_list`/`missing_from_list`） | PK `(code, valid_from)`；排除约束同上 |
| `security_search_terms` | `id bigserial`、`code`、`term_kind`（`name`/`name_initials`/`former_name`/`former_initials`/`former_code`）、`term text`（已归一化：全角转半角、去空格；首字母为大写字母与数字）、`source_name text`（生成该词条的简称原文，用于 `matched_text`）、`is_st_stripped bool`、`variant_rank smallint`（0 = 词组词典的默认读音）、`generator_version smallint` | PK `id`；唯一 `(code, term_kind, term, source_name)`；btree `(term text_pattern_ops)`（精确与前缀）；gin `(term gin_trgm_ops)`（只用于 `name`/`former_name`，查询至少 2 个汉字才走）；btree `(code)` |
| `master_snapshots` | `id`、`source`（`sse_list`/`sse_delist`/`szse_list`/`szse_delist`/`szse_rename`/`bse_list`/`bse_delist`/`bse_code_map`/`cninfo`/`akshare`）、`url`、`fetched_at timestamptz`（UTC）、`trade_date date`（北京时间快照日）、`row_count`、`sha256`、`parse_status`（`ok`/`rejected`/`failed`）、`reject_reason`（`empty`/`drop_pct`/`key_missing`/`parse_error`）、`raw_path`（原始文件，保留 90 天） | PK `id`；唯一 `(source, sha256)`；btree `(source, fetched_at desc)` |
| `master_runs` | `id`、`started_at`、`finished_at`、`trigger`（`beat_1800`/`beat_0730`/`manual`/`bootstrap`）、`status`（`ok`/`partial`/`failed`）、`snapshot_ids bigint[]`、`stats jsonb`（新增、改名、改状态、拒收的计数） | PK `id`；btree `(started_at desc)` |
| `security_reconciliation_diffs` | `id`、`kind`（契约 §3 `security_reconciliation_kind`）、`source`（`security_reconciliation_source`）、`security_code`、`source_name`、`field`、`master_value`、`source_value`、`source_licence_id uuid null`（只有 `mairui_*` 有）、`first_seen_on`、`last_seen_on`、`seen_days`、`status`（`open`/`resolved`）、`resolved_on` | PK `id`；部分唯一 `(kind, source, security_code, field, source_licence_id) NULLS NOT DISTINCT where status='open'`；btree `(status, last_seen_on desc, id desc)`；**隔离区 = `kind='vendor_unknown' and status='open'` 的行**，这些代码不进 `securities`、不生成词条 |

- 本节各表只存公开主数据，不存证书值、行情数值或用户数据；`master_snapshots.raw_path` 指向 `data/master/` 下的原始文件（与导入文件目录分开），每日清理过期文件。
- 迁移只建表与扩展（`pg_trgm`、`btree_gist`），不灌数据；数据由 4.6.6 的首次导入写入。

#### 4.6.3 词条与拼音

- 词条生成用 `pypinyin`：先用词组词典得到默认读音（`variant_rank=0`），再用 `heteronym=True` 展开多音字组合，按组合数截到 `search.initials_max_variants`（16）个；超过时默认读音那一组一定保留。
- 带 `*ST`、`ST`、`S`、`退` 等前缀的简称，另生成一组去掉前缀后的词条（`is_st_stripped=true`），例如 `*ST示例` 可用 `SL` 与 `STSL` 搜到。
- 简称或曾用名改变时，该证券的词条在同一事务中整体重建；`generator_version` 升级时全量重建（worker 批任务）。
- 排序沿用契约 §7.3：`code_exact` > `code_prefix` > `name_exact` > `initials_exact` > `name_prefix` > `former_name` > `former_code` > `fuzzy`；同层内 `listed` 在前，再按 `code` 升序；曾用名的首字母命中归入 `former_name`。

#### 4.6.4 对账与阈值

- **快照校验**（每份交易所列表单独判定，失败则整份拒收、沿用上一份成功快照）：0 行；行数比该所上一份成功快照少 `master.reject_drop_pct`（2%）以上；代码、简称、上市日期任一缺失率超过 `master.reject_key_missing_pct`（0.5%）；解析失败。拒收写 `master_snapshots.parse_status='rejected'` 并出告警（契约 §7.9 `master.snapshot_rejected`）。
- **合并冲突**：同一字段，交易所值一律优先；交易所为空、巨潮有值 → 用巨潮值并在 `field_sources` 记来源；两者不同 → 保留交易所值，记 `field_mismatch`；同一代码在两个交易所名单同时出现 → 本次不合并该代码，记 `field_mismatch(field=exchange)` 并告警。
- **按证书对账（麦蕊，2.1B）**：每个可用证书各比一次，结果带 `source_licence_id`：
  - 麦蕊有、交易所列为终止上市 → `vendor_stale_listed`（T007 实测 4 个）；
  - 麦蕊有、交易所三类名单都没有 → `vendor_unknown`，进隔离区（T007 实测 1 个）；
  - 交易所有（`listed`/`delisting_period`）、该证书代码集没有 → `quote_missing`，契约 `SecurityHit.quote_missing` 据此给值；
  - `/hsrl/real/all` 中同一代码多行且数值冲突 → `quote_conflict`，只记录、不告警（实测 304 组，过于频繁）。
- **交叉核对**：巨潮、AKShare 每周六（`master.crosscheck_weekday`）各比一次简称、上市日期、退市日期、交易所、板块，不同即 `field_mismatch`。
- **关闭**：差异在下一次同类对账中消失即置 `resolved`；`seen_days` 按工作日累计。
- **告警阈值**：`vendor_stale_listed` 连续超过 `master.vendor_stale_alert_days`（5 个工作日）；`vendor_unknown`、`quote_missing` 出现即告警；`field_mismatch` 未关闭行 ≥ `master.field_mismatch_alert_rows`（10）；`snapshot_rejected` 一次 warning、18:00 与次日 07:30 都拒收 critical。只在管理端显示（问题 92）。

#### 4.6.5 调度与分工

| 任务 | 触发 | 执行 | 说明 |
|---|---|---|---|
| `master.sync_exchange_lists` | beat：周一至周五 18:00、次日 07:30（北京时间） | worker `batch` 队列 | 拉三所当前、终止上市、整理期名单与深交所改名表 → 校验 → 合并 → 历史表 → 词条；07:30 只补拉 18:00 未成功的来源 |
| `master.sync_bse_code_map` | beat：每月第一个工作日 18:30 | worker `batch` | 北交所新旧代码对照 |
| `master.reconcile_vendor` | `master.sync_exchange_lists` 成功后链式触发 | worker 生成对账请求 → `ingest` 以 P1 优先级按证书拉麦蕊三份列表 → worker 比对 | 只有 `ingest` 调麦蕊（2.1B）；证书不可用则跳过该证书，不跨证书回退 |
| `master.crosscheck` | beat：每周六 10:00 | worker `batch` | 巨潮、AKShare |
| `master.purge_snapshots` | beat：每日 03:30 | worker `batch` | 删除超过 90 天的原始快照文件 |

- 交易日门槛一律按工作日计（周一至周五，2.1B）。同一任务用 Redis 锁防重入；任务失败重试 3 次（间隔 10 分钟），仍失败即记 `master_runs.status='failed'`。

#### 4.6.5A 麦蕊对账批次的交接与重试（v0.2.9 内，架构师裁定 T-B61；内部契约，不改 api-contract）

链路：`master.sync_exchange_lists` 成功 → `master.reconcile_vendor`（worker，按证书建批次并投递拉取意图）→ `ingest` 按证书拉取并写入规范化列表 → `master.reconcile_vendor_apply`（worker，调用 `app/master/reconcile.py::reconcile_vendor_lists`，单事务提交差异）→ 管理端告警（读取时生成）。

1. **任务注册**：`jobs.TASKS` 注册 `master.reconcile_vendor`（`RECONCILE_VENDOR`）和新增的 `master.reconcile_vendor_apply`（`RECONCILE_VENDOR_APPLY`）。`RECONCILE_VENDOR` 只由 `SYNC_LISTS` 成功后链式触发（已有 `_push` 分支），也接受管理员手动触发（`trigger=manual`）。
2. **批次表 `master_vendor_batches`**（新迁移）：`id`；`master_run_id`（FK → `master_runs`）；`source_licence_id`（可空 UUID，只存 id，不存证书值；NULL 专指聚合的 `not_set` 作用域）；`status`（`requested`/`fetched`/`failed`/`skipped`/`reconciled`/`expired`/`superseded`）；`attempt int`（从 1 起）；`requested_at`、`deadline_at`、`fetched_at`、`reconciled_at`（timestamptz，UTC）；`datasets jsonb`（每项 `{dataset, status: ok|failed, row_count, raw_payload_id, error_code}`，不含行情数值）；`error_code text`。非空证书继续使用唯一约束 `(master_run_id, source_licence_id, attempt)`；补部分唯一索引 `(master_run_id, attempt) WHERE source_licence_id IS NULL`。加 CHECK：NULL 作用域只能是 `status=skipped AND attempt=1 AND error_code=licence_unavailable`。不造证书 UUID，不加 `scope_key`：现有证书表“无未删除行即 not_set”，代码按 UUID 查询，保留现有键并补一个空值索引最少改动，也沿用本仓库部分索引惯例；普通 UNIQUE 不能防止多个 NULL。
3. **规范化行表 `master_vendor_list_rows`**：`batch_id`（FK，级联删除）、`dataset`（`hslt_list`/`bj_list`/`kc_list`/`hsrl_real`）、`security_code`、`vendor_name`、`dup_conflict bool`（只对 `hsrl_real`：同一代码多行且数值不同时为 true；不存价格）。只存公开主数据。`master.purge_snapshots` 一并删除 14 天前的批次行。
4. **投递（worker → ingest）**：对每张 `status=active` 的证书，先在库里插入 `requested` 批次（按唯一约束幂等），提交后向 Redis Stream `ingest:requests` 投递意图 `{kind: "vendor_lists", batch_id, licence_id, datasets: [...], priority: "p1_daily", deadline_at}`。意图只带 id，不带证书值和用户信息。证书不可用（暂停、冷却、`ip_limited`、未设置）的批次直接写 `skipped` 并记 `error_code`，不投递，也不换用其他证书。**not_set 补充裁定**：本次运行发现存在没有未删除证书行的用户时，只建一条聚合 NULL 作用域批次（不逐用户存储；不保存 user_id、用户名或数量）；即使同时存在 active 证书也保留这一条。没有用户则不凭空建该批次；已删除的证书不复用旧 id，无当前行按 not_set 处理。插入与父运行锁/唯一约束共同保证重复和并发触发幂等。直接 `skipped`、`attempt=1`、`datasets=[]`、`error_code=licence_unavailable`，不发 ingest 意图、不调用 apply、不重试；beat 只扫 requested/fetched，必须排除该作用域。`deadline_at` = 下一次 `sync_exchange_lists` 的计划时间（18:00 批次为次日 07:30；07:30 批次为当日 18:00）。
5. **拉取与交接（ingest）**：`ingest` 用该批次自己的证书拉取，`/hslt/list`、`/bj/list/all`、`/kc/list/all`、`/hsrl/real/all` 每项各自重试，遵守令牌桶和 2.1A 的失败策略。完成后在一个事务里写入规范化行，并把批次改为 `fetched`（四项都成功，或三份列表成功、仅 `hsrl_real` 失败）或 `failed`（三份列表任一失败，写 `error_code`）。提交后 `LPUSH jobs:worker` `{"task": "master.reconcile_vendor_apply", "args": {"batch_id": …}}`。`ingest` 只能把 `requested` 改成 `fetched`/`failed`，不能改其他状态。超过 `deadline_at` 才拿到意图时直接写 `expired`，不拉取。
6. **比对与提交（worker，`RECONCILE_VENDOR_APPLY`）**：在单个事务里 `SELECT … FOR UPDATE` 锁住批次。状态不是 `fetched` 时什么都不做，按幂等处理，以便承受重复投递。同一证书已有 `fetched_at` 更晚的 `reconciled` 批次时，本批次改为 `superseded`，不调用核心，避免旧快照重开差异。否则调用 `reconcile_vendor_lists` 写入 `security_reconciliation_diffs`，再把批次改为 `reconciled`，一并提交。`hsrl_real` 失败的批次照常比对三份列表，但本次不开也不关 `quote_conflict`。
7. **重试**：任务级重试沿用 4.6.5（3 次，间隔 10 分钟）。批次级规则：`failed` 批次由 `RECONCILE_VENDOR` 在下一轮重试时新建 `attempt+1` 的批次，最多 3 次，此后在 `master_runs.stats.vendor` 里记 `{licence_id, final: failed, error_code}`。`skipped`、`expired`、`superseded` 不重试。beat 每 15 分钟扫一次兜底：已过 `deadline_at` 的 `requested` 批次改为 `expired`；`fetched` 超过 30 分钟仍未比对的，重新投递 `RECONCILE_VENDOR_APPLY`。
8. **管理端告警**：不另建告警表。`/admin/ingest/status.alerts` 的 5 个 `master.*` 键在读取时由 `security_reconciliation_diffs`（open 行按 4.6.4 阈值）和 `master_snapshots`（拒收）生成，文案按契约 #39。**not_set 展示**：缺少证书不等于主数据差异，不产生这 5 个 `master.*` 告警，不造差异记录；既有管理端 `licences[]` 仅列已设置证书的约定不变，不塞伪造的 licence 行。运维查看该运行批次时以“未设置证书，已跳过”解释 NULL 作用域及 `licence_unavailable`；如需网页批次摘要，展示位置/接口扩展待后端确认，不借用 master.* 告警。故对账类告警仍以提交差异为来源，`reconcile_vendor_lists` 返回的 `alert_ids` 只用于日志和测试断言。
9. **数据库权限（运维）**：`aia_ingest` 对 `master_vendor_batches` 只有 SELECT 以及 `status`、`fetched_at`、`datasets`、`error_code` 列的 UPDATE，对 `master_vendor_list_rows` 只有 INSERT；其余由 `aia_api`（worker）读写。`verify-roles.sh` 加对应的正例和负例断言。
10. **日志与安全**：队列消息、批次行、日志里只出现 `batch_id` 和 `licence_id`，不出现证书值、请求 URL 里的证书段或行情数值。NULL 作用域只记录 batch_id 与 source_licence_id=null，可用固定文字 not_set 解释，不附用户信息；not_set 不进入队列。**验收**：虚构两个无当前证书用户和一个 active 证书，重复及并发触发同一 master_run：恰有一条 NULL/skipped/attempt=1 批次和一条 active requested 批次，仅后者有意图；直接插入第二条 NULL 同 attempt 必须唯一冲突，NULL requested/attempt=2 必须 CHECK 拒绝；重试及推进超过 deadline 的 sweep 后 NULL 批次不变、无 apply、无差异/新增 master.* 告警；日志/批次/队列无用户信息或证书哨兵值。

##### T-B65 生产采集接线（后端；T-B61 离线闭环不等于生产可用）

- **消费与幂等**：在 `app/workers/ingest.py` 接入 `ingest:requests` 的 `kind=vendor_lists`，复用 `parse_intent` / `VendorIntent` / `process_vendor_intent`。使用 Redis Stream 消费组，处理新消息及重启后的 pending 认领；消费组名、consumer 标识、认领最小空闲时长、批量及配置入口均**待后端确认**（当前入口仅心跳，仓库没有现成消费组配置）。ACK 必须在数据库终态提交且 apply 通知成功或已有可靠恢复依据之后，不能收到即 ACK；无效消息不回显内容，隔离/ACK 策略待后端确认。以 batch_id 作跨 consumer 幂等：采集前获取独占处理权；不能仅在写入时锁行，因为会重复外呼扣额；重复已完成消息不重采集。
- **配额与优先级**：通过同一个 `IngestCore.submit` / `next_call` / `complete`、`Call` 和 `Priority.P1`，与行情共用该证书的 `TokenBucket`，不新建独立桶；意图使用已有 `p1_daily`。P0 实时 > P1 日批/按需 > P2 回补，同级证书间 DRR；遵守 `config/ingest.yaml` 的 `budget.per_minute_budget`、`budget.priority_min_share`、`licences.per_licence_max_concurrency` 与 `licences.global_max_concurrency`。重试每次都扣同一证书配额，不跨证书回退。
- **逐项重试**：四个数据集单独记结果；网络/5xx/频率限制按已有 `LicenceState` 及 `licences.breaker.backoff_s`（1/2/4/8/16/32/60 秒）、`consecutive_503`、`open_s` 与 §2.1B 执行。端点级重试次数上限和是否包含首调**待后端确认**（不是批次级最多 3 次）；在确认前不得声称已实现。认证/IP/额度错误遵守已有暂停/熔断，禁止盲重试；不得超过 deadline 继续采集。
- **状态与提交**：以 `DatasetResult` / `VendorRow` 交接规范化结果。四项全成功为 fetched；只有 hsrl_real 失败亦 fetched（该项 failed，禁止开关 quote_conflict）；三份列表任一失败，包括部分成功或四项全失败，整批 failed，逐项 datasets 保留成功/失败摘要，不用局部列表对账。批次级失败按第 7 条 10 分钟、最多 3 个 attempt；not_set/skipped/expired 不重试。
- **通知与恢复**：规范行和 fetched/failed 同事务提交后，`LPUSH jobs:worker`，task 为 `master.reconcile_vendor_apply`、args 仅 batch_id。提交前崩溃由 pending 认领重做；提交后、LPUSH 前崩溃，重投必须能补通知而不是仅 noop 后 ACK。已有 `master.vendor_batches_sweep` 能补超过 30 分钟的 fetched，不能恢复 failed 的重试调度；failed 通知 apply 会 noop，必须保证 `master.reconcile_vendor` 的重试任务仍可恢复，具体可靠恢复接线**待后端确认**，不得假称现有 sweep 已覆盖。
- **可观测性**：沿用 `ops.ingest_request_log` 的 priority/dataset/status/http_status/mairui_code/latency_ms，管理端 queues/budget/errors_24h/heartbeat，以及批次 requested_at/fetched_at/reconciled_at/datasets/error_code。须能诊断 pending 年龄及认领、重复 batch 抑制、逐项重试次数、超期和提交到 apply 的延迟；新增指标名/存储配置**待后端确认**，不编造现有名称，不记完整 URL、证书值或行情值。
- **验收**：离线模拟 Stream 消费组新消息/认领，双 consumer 同 batch 仅一次采集；模拟首项重试成功、三列表之一耗尽、仅 real 失败、全失败及到期，核对逐项与批次状态；P0 抢占与多证书公平且每次重试扣共享桶；在提交前/提交后但通知前/通知后但 ACK 前分别崩溃，重启后只一次规范行及比对、failed 可继续重试；模拟失锁/IP 不符拒绝外呼；权限负例和哨兵扫描；生产链路相关模块 pytest 覆盖率至少 90%。
- **出网边界**：符合 §2.1A/B：只有 ingest 解封装证书、持单活锁 `ingest:leader` 并外呼，启动按 `MAIRUI_EGRESS_IP_EXPECTED` 核验固定出口，失锁立即停外呼；worker/API 只送 id/读规范行，禁止旁路客户端、第二实例或额外出口。当前缺生产消费接线，因此这里只确认设计符合约束，不宣称运行验证通过；验收仅回放，不调用真实麦蕊。

#### 4.6.6 首次导入（上线前）

- 部署时由运维执行 `python -m app.cli.master_bootstrap`：拉三所全部名单与深交所改名表、北交所代码对照，写主数据、历史表与词条；完成前不开放服务（因此搜索接口不返回 503）。
- 首次导入不做“行数下降 2%”检查（没有上一份快照），其余校验照常；成功后写 `master_runs.trigger='bootstrap'`。

## 5. REST 接口契约摘要（验收项 5）

完整契约见 [`docs/api-contract.md`](./api-contract.md)。要点：
- **基础约定**
  - 基础路径 `/api/v1`，JSON，UTF-8。
  - 时间用 ISO 8601，带时区。
  - 金额和价格以**字符串十进制**传输。
  - 证券代码统一为 `600000.SH / 000001.SZ / 920000.BJ` 格式。
- **认证**：会话 Cookie `sid`（httpOnly、Secure、SameSite=Lax），所有写请求必须带 `X-CSRF-Token`。管理员接口 `/api/v1/admin/*` 要求 `role=admin`。
- **分页与错误**
  - 游标分页：`?limit=&cursor=`，响应 `{items, next_cursor}`。
  - 统一错误格式：`{"error":{"code","message","details","request_id"}}`，错误码表见契约第 4 节。
- **数据状态**：所有带数据的响应都有 `data_status`（`fresh/stale/pending/partial/unavailable`）和 `gaps`。
- **主线接口**
  - 建议：`/suggestions`，包括详情、建议链、用户动作和跟踪。
  - 盘后日报：`/daily-reports`。
  - 盘中信号与事件：`/signals`。
  - 实时行情：`/quotes`。
  - 实时推送：**SSE `GET /stream`**，事件类型包括 `quote`、`signal`、`suggestion`、`notification`、`report`、`heartbeat`，支持 `Last-Event-ID` 续传；SSE 不可用时轮询。
- **策略库接口**
  - 策略：`/strategies`，包括版本、规则清单、复制和改参、筛选、个股适配，以及跟踪统计与降权状态。
  - 周期分类：`/horizon-assessments`；个股×策略的设置统一走 L3 实例 `/strategy-instances`（旧 `/symbol-strategy-settings` 不再提供）。
  - 风控：`/risk-controls`（设置和事件）。
- **管理端**
  - LLM：`/admin/llm/*`，含供应商、模型、任务路由、提示词模板、测试调用和用量。
  - 实时参数：`/admin/realtime-settings`。
  - 采集状态：`/admin/ingest/status`（队列、预算、错误码、新鲜度、锁持有者，以及按证书的状态列表 `licences[]`：状态、档位、到期、今日调用量与上限、队列积压、熔断、最近错误码，不含证书值；只读，契约 v0.2.8）。
  - 模板审核与生命周期：`/admin/promotions`、`/admin/strategies/{id}/versions/{vid}/lifecycle`。
  - 套餐与订阅：`/admin/plans`、`/admin/subscriptions`。
- **其他资源分组**
  - auth、me/profile
  - today（含提醒、计划触发、数据缺口，契约 v0.2.7）、market（含 `/market/sector-flows`）、securities（`/securities/search`、资料、财务、资金流、因子、公告；周 K 口径见契约 §6.2）
  - accounts/trades/imports/snapshots/reconciliation、portfolio、watchlist
  - candidates、claims、plans、alert-rules/alerts、reviews
  - notifications/channels/preferences、meta/health
- **策略三层与候选信号接口**（2.5.0–2.5.13，详见契约 §6.20–§6.28）
  - L1 卡片：`/strategy-cards`（CRUD、版本、晋级申请 `/promotion-requests`、G1–G7 门禁报告）。
  - 特征白名单：`/feature-catalog`（只读）。
  - L2 模板：`/strategies`（列表、详情、版本、派生 `derive`）、`/admin/strategies/{id}/versions/{vid}/lifecycle`（生命周期跃迁，仅管理员）。
  - L3 实例：`/strategy-instances`（列表筛选与分页、确认、暂停、恢复、归档、改参；状态机见契约 §6.0A，v0.2.7）。
  - 候选信号：`/candidate-signals`（列表、详情、事件、忽略）。**候选信号没有"转计划"接口**。
  - 不可执行原因：`/non-executable-reasons`（列表、详情、手动解除，仅限不可机器判断的条件）。
  - 计划草案：`/plan-drafts`（生成、列表筛选、详情、确认、放弃）。**确认是生成计划的唯一入口**，必须带清单答案和风险确认。
  - 限制：`/restrictions`（禁投、冷静期、屏蔽）。
  - 枚举：`/meta/enums` 下发原因码表、各状态机与错误码。
- **可解释性在契约层强制执行**：任何候选信号或建议响应都必须带非空的 `rule_refs[]`、`evidence[]`、`counter_evidence[]`、`invalidation[]`，`model_refs[]` 中的每一项 `role` 都是 `auxiliary`。服务端写入时校验，不满足则返回 `SIGNAL_NOT_EXPLAINABLE`；生成计划草案时如果没有规则类信号，返回 `PLAN_REQUIRES_EXPLAINABLE_SIGNAL`。
- **统计必带样本量**：所有统计值都使用 `{value, n, window, small_sample}` 结构（2.12.3）。
- **内部评估**：`/admin/evaluation/*`，仅管理员可用；第三阶段启用；普通用户请求返回 404（方案 A 只向用户展示"是否做过内部检验、方法类型、检验日期"，见第 9 节 C(6)）。

- **契约优先级**：FastAPI 生成的 `openapi.json` 是机器可读的产物；两者不一致时**以本契约为准，改代码**。

---

## 6. 目录结构约定（验收项 6）

```
ashare-invest-assistant/
├── src/
│   ├── backend/                    # 后端（后端角色）
│   │   ├── pyproject.toml          # uv/poetry 管理；ruff、mypy 配置
│   │   ├── alembic.ini
│   │   ├── migrations/             # Alembic 迁移
│   │   └── app/
│   │       ├── main.py             # FastAPI 入口
│   │       ├── config.py           # pydantic-settings，读取环境变量
│   │       ├── api/v1/             # 路由（按资源分文件），只做参数校验与调用 service
│   │       ├── schemas/            # Pydantic 请求/响应模型（契约的代码形式）
│   │       ├── domain/             # 领域模块：identity, profile, portfolio, situation, research,
│   │       │                       #   planning, alerts, review, snapshot, compliance, admin, billing
│   │       ├── strategy/           # 策略三层（2.5.0、2.5.13）
│   │       │   ├── registry.py         #   显式注册表（不做目录扫描自动激活）
│   │       │   ├── base.py             #   BaseStrategy / ScreenerStrategy / TimingStrategy / RuleTemplateStrategy
│   │       │   ├── cards/              #   L1 卡片与版本
│   │       │   ├── templates/          #   L2：YAML → 不可变版本导入、生命周期
│   │       │   ├── dsl/                #   规则 DSL 解析（AST 白名单）
│   │       │   ├── evaluator/          #   RuleEvaluator、gate_tradability、RiskHook
│   │       │   ├── plugins/            #   代码型策略（kind=code，需要评审）
│   │       │   ├── promotion/          #   G1–G7 门禁、fixtures 运行器
│   │       │   ├── instances/          #   L3 实例、候选信号、不可执行原因与解除监控、计划草案
│   │       │   └── horizon/            #   周期分类器
│   │       ├── features/               # 唯一特征管线 pipeline.py + catalog.py（2.5.10）
│   │       ├── market_rules/           # A 股交易规则（2.13）
│   │       ├── evaluation/             # 内部评估（仅管理员，问题 26；2.12.4）
│   │       ├── ingest/                 # 行情采集服务（独立进程入口 ingest/main.py；mairui_client 只能被本包引用）
│   │       ├── signal_rt/              # 盘中信号进程入口
│   │       ├── advice/             # 建议引擎流水线、置信度、分歧分析、建议链
│   │       ├── risk/               # 六项风控 RC1–RC6
│   │       ├── signals/            # 信号状态与翻转
│   │       ├── realtime/           # universe 分层与刷新计划（不外呼）
│   │       ├── reports/            # 盘后流水线与日报
│   │       ├── tracking/           # 模拟跟踪与自动降权
│   │       ├── llm/                # LLM 网关：providers/、routing、guards、templates
│   │       ├── notify/             # 通知中心、SSE 广播、channels/（in_app、email、wecom 预留）
│   │       ├── importing/          # 交割单导入：encoding.py、registry.py、mapping.py、dedup.py、
│   │       │   └── parsers/        #   generic_delimited.py、csv_template.py、{broker}_v1.py（待范本）
│   │       ├── marketdata/         # 行情存取（按证书隔离）、gap 判断
│   │       ├── jobs/               # Celery app、beat 调度表、任务
│   │       ├── db/                 # SQLAlchemy models、session
│   │       └── common/             # 错误码、分页、时间、金额工具
│   └── frontend/                   # 前端（前端角色）
│       ├── package.json            # pnpm；vite、eslint、prettier
│       ├── src/
│       │   ├── api/                # openapi-typescript 生成的类型 + fetch 封装
│       │   ├── pages/              # 对应 2.4 的页面
│       │   ├── components/
│       │   ├── features/           # 按能力拆分的状态与组件
│       │   └── i18n/ (zh-CN 文案，含合规文案)
│       └── public/
├── tests/                          # 测试（测试角色）
│   ├── backend/{unit,integration,contract}/   # pytest；contract 用 schemathesis 对照 api-contract
│   ├── frontend/                   # vitest + testing-library
│   ├── backend/golden/             # 策略/建议 golden 用例（快照 JSON → 期望输出）
│   ├── replay/                     # 录制的盘中行情回放（脱敏）
│   ├── e2e/                        # Playwright
│   └── fixtures/
│       ├── mairui/                 # 麦蕊响应样本（脱敏，不含 licence）
│       └── broker_statements/{format}/  # **仅合成样本**（generate.py 生成，GBK 定宽，虚构值，配套 expected.json）；真实范本永不入库
├── config/                         # 版本化业务配置（入库前经校验，变更走 PR）
│   ├── realtime.yaml               # 刷新间隔、分层、预算、上限默认值（0A.7）
│   ├── strategies/*.yaml           # 内置 L2 模板定义（2.5.13；导入后成为不可变 DB 版本，放文件不会激活）
│   ├── market_rules.yaml           # 按生效日期分段的交易规则（2.13）
│   ├── ingest.yaml                 # 预算、优先级份额、并发（2.1A）
│   ├── risk_controls.yaml          # RC1–RC6 系统默认阈值
│   └── horizon_classifier.yaml     # 周期分类器阈值
├── deploy/                         # 运维
│   ├── docker/                     # backend.Dockerfile, frontend.Dockerfile
│   ├── compose/                    # docker-compose.yml, docker-compose.dev.yml
│   ├── nginx/                      # nginx.conf（TLS、静态资源、/api 反代）
│   ├── env/.env.example            # 只放变量名与示例值，绝不放真实 licence
│   ├── runbooks/                   # ingest-failover.md（冷备切换）、migrate.md
│   └── scripts/                    # backup.sh, restore.sh, deploy.sh
├── THIRD_PARTY_NOTICES.md          # 引用的开源项目与许可证（7.6）
├── .github/workflows/
│   ├── ci.yml                      # PR：backend lint/mypy/pytest，frontend lint/tsc/vitest，contract test，docker build
│   └── deploy.yml                  # main 合并后手动触发，构建镜像并部署
└── docs/
    ├── plan.md                     # 本文
    ├── api-contract.md             # REST 契约
    ├── strategy-references.md      # T002 开源调研（另一位作者维护）
    ├── strategies/                 # 策略知识卡、规则规格、验证方法（策略研究员维护；格式见 2.5.14；架构不改）
    └── adr/                        # 架构决策记录（后续）
```

约定：
- **秘密**：麦蕊 licence（**只注入 `ingest` 容器**）、DeepSeek key `DEEPSEEK_API_KEY`（只注入 `api`、`worker`，2.7.2）、数据库密码、SMTP 密码只经环境变量/服务器上的 `.env`（不入库、不进日志；网关日志中 URL 的 licence 段替换为 `***`）。
- 分支：`main` 受保护；功能分支 `feat/T0xx-*`；PR 必须 CI 通过。
- 后端 Python 包名 `app`，运行目录 `src/backend`；前端运行目录 `src/frontend`；测试从仓库根目录执行（`pytest tests/backend`、`pnpm -C src/frontend test` 指向 `tests/frontend`）。

### 6.1 业务配置文件（`config/*.yaml`）的键、类型与默认值（T-A01，回应 T-B01 报告 §2.1）
**通用规则**
- **`config/` 下全部 YAML 文件（含 `llm.yaml`、`market_rules.yaml`、`horizon_classifier.yaml`）一律由后端创建和维护**；架构师只在本节定义键、类型与默认值，不直接改 `config/*.yaml`（T-A03 明确）。
- 文件由**后端**按本节创建（T-B01 后续任务）；本节是默认值的唯一出处，数值与前文已定结论一致（0A.6/0A.7、2.1A、2.5.6、2.5.9、2.13、第 9 节）。改默认值先改本节，再改文件。
- 每个文件顶层必须有 `schema_version: 1`；未知键 → 启动失败（pydantic `extra="forbid"`），防止拼写错误被静默忽略。只放**非敏感**参数，licence、密码、密钥一律走环境变量。
- 优先级：环境变量（只限本节注明的少数键）> 管理端运行时覆盖（存数据库，写审计，只限标注“可热调”的键）> YAML 默认值。`config/strategies/` 由导入器生成（2.5.14），不在本节范围。
- **合并口径（T-A02 定，回应 T-T01a §7-3）**：三层按**深合并**（逐键递归），只覆盖叶子键时同级其余键保留；例如只设 `realtime.intervals.quote_interval_s` 时 `intervals` 下其余键仍取下层值。**列表与标量整体替换，不按元素合并**；值显式为 `null` 视为“未覆盖”，不能用来删除键。合并后的结果再整体走 pydantic 校验（`extra="forbid"`，未知键在任何一层出现都启动失败）。环境变量嵌套分隔符为双下划线 `__`（pydantic-settings `env_nested_delimiter`），仍只允许本节注明的键。
- **`*_env` 键约定（回应 review-T-B02 F4）**：键名以 `_env` 结尾（如 `llm.yaml` 的 `api_key_env`）的值是**环境变量名的引用**，不是秘密本身；值必须匹配 `^[A-Z][A-Z0-9_]*$`，加载器不得把这类键当密钥拒绝，也不得把对应环境变量的值读进配置对象或日志，只在使用处按名读取并校验非空。真实秘密值出现在任何 YAML 中仍按 S1–S9 阻断。
- 标【待 T003】的数值来自文档推导，T-B05 实测后只改 YAML，不改代码；标【编排者默认，用户可否决】的见第 9 节 C 部分。注释里带 **◇** 的数值是本节为补全配置新给的工程默认值（前文未定），同样属于【编排者默认，用户可否决】，可直接改 YAML。
- 每个文件在 CI 中用 pydantic 模型校验，并有一条测试检查“YAML 默认值 == 本节表格”（T-T 新增，归测试）。
- **参考数据名单不属于本节业务配置（架构师，回应 review-8e8525e M）**：`config/share_class_list.yaml`（A+B、A+H 名单，2.12.1 T-R12h、T-R12i、T-R14）是按 `list_version` 整版替换的参考数据，不是有默认值的参数，所以不进本节白名单，也不进后端 `BUSINESS_FILES`。“YAML 默认值 == 本节表格”这条检查不覆盖它。
  - 后端另设参考数据注册表，比如 `REFERENCE_FILES`，用自己的 pydantic 模型校验：`schema_version: 1`、文件头字段、记录字段、`extra="forbid"`。
  - 本节的业务配置仍是 9 个文件。以后新增同类名单，比如保险证券名单，也按这一条处理。

**`config/realtime.yaml`**（盘中实时链路，0A.6/0A.7；管理端 `/admin/realtime-settings` 可热调）
```yaml
schema_version: 1
intervals:
  quote_interval_s: 15          # int，多股快照一轮间隔；下限 5【待 T003】
  all_market_interval_s: 60     # int，全市场快照 /hsrl/ssjy/all 间隔【待 T003】
  pro_tier1_interval_s: 60      # int，Tier-1 的 Pro 1 分钟 K 间隔
  pro_tier2_interval_s: 300     # int，Tier-2 间隔
  stale_threshold_s: null       # int|null；null = 2 × quote_interval_s（data_status=stale 与原因码 DATA_STALE 共用此阈值）
boards:                         # V1 扫描范围（第 9 节问题 10、C(8)）；关闭的板块持仓仍可导入和展示
  main: true
  chinext: true
  star: true
  bse: false                    # V1 不含北交所【编排者默认，用户可否决】
  etf_cb_holdings_only: true    # ETF 只做搜索、行情与持仓展示，不进策略扫描；可转债本版不纳入主数据（问题 53，契约 v0.2.8）
universe:
  tier1_cap: 1500               # int，Tier-1 只数【待 T003】
  universe_hard_cap: 4000       # int，系统去重池硬上限
  tier1_alert_ratio: 0.8        # float，universe 达 Tier-1 上限的 80% 时告警
  tier1_priority: [holding, focus, multi_user_watch, single_user_watch]   # Tier-1 名额分配顺序
watchlist:
  per_user_cap: 100             # int，每人自选上限（默认值；实际上限取权益 watchlist.per_user_cap）
  focus_cap: 20                 # int，每人盘中重点关注上限（权益 intraday.focus_cap）
  holdings_import_warn: 200     # int，导入持仓超过此数给提示（持仓不设上限）
flip_detection:
  debounce_rounds: 2            # int，翻转需连续成立的轮数
  invalidation_immediate: true  # bool，失效价类条件立即确认
adaptive:
  enabled: true
  unchanged_ratio: 0.8          # ◇ float，“多数股票 t 未变”的比例阈值
  unchanged_rounds: 5           # ◇ int，连续 N 轮
  breaker_cooldown_s: 300       # int，429/503 熔断后 5 分钟恢复
notify:
  cadence_default: 1min         # realtime|1min|3min|5min，用户通知节奏默认值
  sse_heartbeat_s: 15           # int，SSE 心跳（契约 §8）
  sse_replay_window_s: 600      # int，Last-Event-ID 续传窗口 10 分钟（契约 §8）
  poll_fallback_s: 15           # int，SSE 断开时 /terminal、/today 轮询下限
degraded_profile:               # 证书到期降级档（7.x 风险表），管理员一键切换
  holdings_only: true
  quote_interval_s: 60
  tier2_enabled: false
admin_alerts:                   # v0.2.9 内 T-B47 裁定：/admin/ingest/status 的 freshness 与 alerts 口径（api 读取；初值，问题 78）
  queue_p0_warning_s: 60        # ◇ 盘中 p0_intraday 最早任务等待超过即 warning
  queue_p0_critical_s: 300      # ◇ 超过即 critical
  queue_p1_warning_s: 3600      # ◇ p1_daily
  budget_warning_ratio: 0.9     # ◇ used_last_minute / per_minute_limit
  ip_limit_critical_count: 1    # ◇ 24 小时 ip_limited 事件数
  upstream_error_warning_count: 20   # ◇ 单个上游错误码 24 小时次数
  licence_days_left_warning: 14      # ◇
  freshness:                    # 数据集固定 6 个，顺序即响应顺序；quotes 用 intervals.stale_threshold_s
    minute_bars_stale_s: 180    # ◇ 盘中
    daily_bars_due: "17:00"     # ◇ 交易日该时刻后仍不是当日 → stale
    announcements_due: "20:00"  # ◇
    security_master_stale_trading_days: 1
    financials_stale_days: 120  # ◇
```

**`config/ingest.yaml`**（采集服务 `ingest`，2.1A；只有 `ingest` 进程读取。交割单上传上限**不在本文件**，见 `config/imports.yaml`）
```yaml
schema_version: 1
# T-A07：budget.* 改为“每张证书”的默认值（证书档位未知且无管理员覆盖时使用）；全进程并发见 licences.global_max_concurrency
budget:
  per_minute_budget: 3000       # int，每证书令牌桶（原为全局）（钻石版文档 6000/分钟，自设一半）【待 T003】；可热调，上调上限 5400
  max_concurrency: 1            # int，并发上限【待 T003】
  shares:                       # 各层每分钟份额，合计 ≤ per_minute_budget；高优先级可借用低优先级空闲额度
    snapshot: 800               # 快照层
    minute_bars: 2000           # 分钟线
    other: 200                  # 其他接口
  priority_min_share:
    p0_intraday: 0.7            # 盘中 P0 至少 70%
    p2_backfill_intraday: 0.0   # 盘中 P2 份额为 0，夜间可用满剩余额度
backoff:
  base_s: 1                     # ◇ 指数退避起点
  max_s: 60                     # ◇ 退避上限
  breaker_open_s: 300           # 连续 429/503 熔断 5 分钟
leader:
  lock_key: "ingest:leader"     # Redis 单活锁
  lease_s: 30                   # ◇ 锁租期
  renew_every_s: 10             # ◇ 续租间隔
heartbeat:
  key: "ingest:heartbeat"       # 环境变量 INGEST_HEARTBEAT_KEY 可覆盖
  paused_key: "ingest:paused"   # 环境变量 INGEST_PAUSED_KEY 可覆盖
  interval_s: 15                # ◇ leader 每 15 秒写一次
  ttl_s: 600                    # ◇ 键过期时间（缺键也判 stale）
  stale_after_s: 120            # 超过 120 秒视为 stale；环境变量 INGEST_STALE_AFTER_S 可覆盖
egress:
  check_on_start: true          # 启动时自检出口 IP，与环境变量 MAIRUI_EGRESS_IP_EXPECTED 比对，不一致拒绝外呼
on_demand:
  coalesce_window_s: 5          # ◇ 按需拉取“同证券同接口”合并窗口
  priority: p1_daily
licences:                       # T-A07 每用户证书（2.1B）
  tier_per_minute:              # ◇ 各档位默认每证书每分钟上限（官方档位的一半，T003）
    diamond: 3000
    annual: 1500
    monthly: 500
    trial: 500
    free: 150
    other: 150
  diamond_after_expiry_per_day: 20000   # 钻石版过期后官方每日额度
  per_licence_max_concurrency: 1
  global_max_concurrency: 2     # 【待 T-B05 实测】同 IP 多证书并发
  cross_licence_scheduling: drr # 先比优先级，同级按证书赤字轮转
  drr_quantum: 1
  breaker:
    consecutive_503: 5
    open_s: 300
    backoff_s: [1, 2, 4, 8, 16, 32, 60]
  ip_limited_pause_s: 120
  ip_limited_escalate: {count: 3, window_s: 3600, pause_s: 3600}
  quota_resume_at: "00:01"      # 北京时间次日
  expiry_reminder_days: [30, 7, 1]
  verify_rate_limit_per_hour: 5
  live_profile:                 # ◇ 默认盘中配置（每证书）
    full_snapshot_interval_s: 60
    focus_max: 20
    focus_interval_s: 15
  eod_scope: user_universe      # 盘后批量只取该用户自选与持仓 + 批量日 K
data_sharing:
  mode: per_licence             # per_licence（默认）| shared_cache【待麦蕊书面确认，禁用】
  allow_cross_licence_fallback: false   # 硬规则：不可改为 true
```
心跳载荷与健康判定见 api-contract §7.10（键 `ingest:heartbeat`，JSON `{ts, instance_id, leader, version, budget_used_last_minute, queue_depth}`）。

**`config/securities.yaml`**（证券搜索与公告外链，契约 v0.2.7；由 `api` 读取；◇ 为本节新给的工程默认值）
```yaml
schema_version: 1
search:
  similarity_threshold: 0.3     # ◇ pg_trgm 相似度下限；查询中至少 2 个汉字才启用模糊匹配
  initials_max_variants: 16     # ◇ 多音字拼音首字母组合上限
  limit_default: 20             # ◇
  limit_max: 50                 # ◇
master:                         # v0.2.9 内，T-A04（4.6）；由 worker 读取；时间均为北京时间
  fetch_times: ["18:00", "07:30"]   # ◇ 周一至周五拉三所列表；07:30 是次日补拉
  reject_drop_pct: 2.0          # ◇ 行数比该所上一份成功快照少 2% 以上 → 整份拒收
  reject_key_missing_pct: 0.5   # ◇ 代码、简称、上市日期任一缺失率超过 0.5% → 整份拒收
  missing_after_snapshots: 2    # ◇ 连续 2 份成功快照都没有该代码（且不在终止上市名单）才置 missing_from_list
  vendor_stale_alert_days: 5    # ◇ vendor_stale_listed 连续超过 5 个工作日才告警
  field_mismatch_alert_rows: 10 # ◇ 未关闭的 field_mismatch ≥ 10 条才告警
  crosscheck_weekday: 6         # ◇ 巨潮/AKShare 交叉核对：每周六（1=周一）
announcements:
  url_host_allowlist:           # ◇ 只有 https 且主机在此列表内的原文链接才返回给前端
    - www.sse.com.cn
    - static.sse.com.cn
    - www.szse.cn
    - disc.szse.cn
    - www.bse.cn
    - www.cninfo.com.cn
    - static.cninfo.com.cn
```

**`config/market_rules.yaml`**（交易规则，2.13；按 `effective_from` 分段，导入为 `market_rule_versions`，回看用当时有效段）
```yaml
schema_version: 1
modeled_from: "2023-04-10"            # 【已定 2026-11-01】规则只建模到此日，更早的不建模；更早的行情回看时 market_rule_version = null，评估结果标“交易规则未建模”，不得作为晋级依据（T-A02，第 9 节问题 36）
segments:
  - effective_from: "2026-07-06"      # 【已定，已核实】沪深主板 ST/*ST 涨跌幅由 5% 改为 10% 的施行日（上证发〔2026〕41 号、深证上〔2026〕551 号）；此前一段为 5%
    price_limit_pct:                  # 前收 × (1 ± pct)，按四舍五入取至价格最小变动单位（A 股 0.01 元）：沪 3.3.17、深 3.3.19 已核实（含差值不足一价位取前收 ±0.01、结果低于 0.01 取 0.01 两条边界规则）
      main_board: 10
      main_board_st: 10               # 【已定，已核实】沪深主板 ST/*ST：10%（上证发〔2026〕41 号、深证上〔2026〕551 号，2026-04-24 发布，2026-07-06 起施行；出处见 docs/strategies/market_rules_check.md O1–O8）
      chinext: 20                     # 创业板（含风险警示）
      star: 20                        # 科创板（含风险警示）
      bse: 30                         # 北交所（含风险警示）
    no_limit:                         # 无涨跌幅限制的情形（以交易所规则为准）
      registered_ipo_first_days: 5    # 沪深注册制新股上市前 5 个交易日
      bse_ipo_first_days: 1
      delisting_period_first_day: true
    lot:
      buy_lot: 100                    # 沪/深主板、创业板、ETF 竞价买入为 100 股（份）或其整数倍（沪 3.3.8 / 深 3.3.8，已核实）
      star_min_buy: 200               # 科创板股票/CDR 单笔 ≥ 200 股，买卖均适用（沪 2026 第 6.7 条，已核实）
      star_step: 1                    # 200 股以上按 1 股递增【部分核实：规则无明文，依沪 6.1/6.7 + 上交所投教 O32–O34（T-R10）】
      bse_min_buy: 100                # 北交所 ≥ 100 股，按 1 股递增【未核实；V1 不扫描北交所】
      bse_step: 1                     # 【未核实】
      odd_lot_sell_all: true          # 卖出时余额不足一个申报单位的部分须一次性申报卖出（沪 3.3.8、6.7；深 3.3.8；已核实，T-R10）
      star_odd_lot_threshold: 200     # 科创板零股阈值 = 200（沪 2026 第 6.7 条末句；已核实）；其他板块阈值 = buy_lot
      max_order_qty: 1000000          # 竞价单笔上限 100 万股（份）（沪 3.3.9 / 深 3.3.9；已核实）
      star_max_limit_order: 100000    # 科创板限价单笔 ≤ 10 万股（沪 2026 第 6.7 条；已核实）
      star_max_market_order: 50000    # 科创板市价单笔 ≤ 5 万股（沪 2026 第 6.7 条；已核实）
      star_max_after_hours: 1000000   # 科创板盘后固定价格单笔 ≤ 100 万股（沪 2026 第 6.7 条；已核实）
      chinext_max_limit_order: 300000 # 创业板限价单笔 ≤ 30 万股（深 3.3.9；已核实）
      chinext_max_market_order: 150000  # 创业板市价单笔 ≤ 15 万股（深 3.3.9；已核实）
    sessions:                         # 北京时间
      call_auction: ["09:15", "09:25"]
      morning: ["09:30", "11:30"]
      afternoon: ["13:00", "14:57"]
      closing_auction: ["14:57", "15:00"]
    t_plus: 1
    t0_round_trip:                    # 实行当日回转交易的品种（沪 3.1.5 / 深 3.1.5；类别已核实，无官方代码清单；T-R10 §3）
      fund_categories: [bond_etf, money_etf, gold_etf, commodity_futures_etf, cross_border_etf, cross_border_lof]
      cross_border_requires_t0_constituents: true   # 跨境类仅限跟踪成份证券/投资标的实施当日回转者（沪/深 3.1.5 第 2 款）
      unknown_category_default_t_plus: 1            # 实现约定（非规则原文）：类别缺失按 T+1 保守处理
      data_source: null                             # 未接入：选定并接入前全部 ETF 按 T+1，实现以本键非空为前提（2.13 ETF 当日回转行，v0.2.9 内 T-O11 裁定）
    fees:
      stamp_duty_sell_pct: 0.05       # 印花税仅卖出
      transfer_fee_pct: 0.001         # 过户费双向
      commission_rate_default_pct: null   # 佣金按用户费率；null = 未设置时由导入成交反推，仍无则提示用户填写
      commission_min_yuan: 5          # 单笔最低 5 元：证监发〔2002〕21 号《关于调整证券交易佣金收取标准的通知》第一条（A 股每笔佣金不足 5 元按 5 元收取；证监会法规库 2026-11-10 查为现行有效）；费率由券商自定（同文第六条），以用户实际为准
      slippage_default_pct: 0.1       # 模板参数默认值
    impact_cost:                      # 【编排者默认，用户可否决；初值待校准】第 9 节 C(7)
      adv_basis: amount               # 【已定 T-A02】成交额口径：参与率 = 拟成交额（计划数量 × 参考价）÷ 近 N 个有效交易日日成交额均值（停牌日不计），与 _template.md §18 一致
      adv_window_days: 20             # N
      tiers:                          # 参与率上界（%，含） → 成本（bp）
        - {max_participation_pct: 0.1, bp: 0}    # I1
        - {max_participation_pct: 0.5, bp: 5}    # I2
        - {max_participation_pct: 1.0, bp: 15}   # I3
        - {max_participation_pct: 2.0, bp: 30}   # I4
        - {max_participation_pct: null, bp: 60}  # I5（> 2%）
    unfillable:
      one_price_limit_up_blocks_buy: true
      one_price_limit_down_blocks_sell: true
      skip_suspended: true
    risk_warning:                     # 风险警示股票（ST/*ST）的额外约束（T-A02 新增，market_rules_check.md M5/M6）
      daily_buy_cap_shares: 500000    # 单只当日累计买入 ≤ 50 万股：沪第 4.4.10 条、深第 4.5.4 条均已核实（T006b）；计划草案数量上限截断到此值并在草案中提示
      applies_to_boards: [main_board, chinext]  # 50 万股上限的适用板块；科创板不适用（沪第 4.4.1、6.14 条）；北交所 V1 不扫描（C(8)）
      limit_order_only: true          # 只能限价申报：仅沪 4.4.9；深交所 2026 规则未见同类条款
      limit_order_only_exchanges: [SH]  # T-A03 新增键：limit_order_only 只作用于沪市证券；本产品不下单，只用于草案与通知文案“请使用限价委托”
  - effective_from: "2023-08-28"      # 2023-08-28 ～ 2026-07-05：除 main_board_st: 5 外与上一段相同（文件中写全，不做继承）。起始日为证券交易印花税减半征收施行日（财政部 税务总局公告 2023 年第 39 号；T-A148 §二 B4 已核对财政部网站与国家税务总局法规库）
    price_limit_pct:                  # 同上一段
      main_board: 10
      main_board_st: 5                # 【已核实】2026-07-06 之前沪深主板 ST/*ST 为 5%（出处同上一段）
      chinext: 20                     # 创业板（含风险警示）
      star: 20                        # 科创板（含风险警示）
      bse: 30                         # 北交所（含风险警示）
    no_limit:                         # 无涨跌幅限制的情形（以交易所规则为准）
      registered_ipo_first_days: 5    # 沪深注册制新股上市前 5 个交易日
      bse_ipo_first_days: 1
      delisting_period_first_day: true
    lot:
      buy_lot: 100                    # 沪/深主板、创业板、ETF 竞价买入为 100 股（份）或其整数倍（沪 3.3.8 / 深 3.3.8，已核实）
      star_min_buy: 200               # 科创板股票/CDR 单笔 ≥ 200 股，买卖均适用（沪 2023 第 6.1.7 条，已核实）
      star_step: 1                    # 200 股以上按 1 股递增【部分核实：规则无明文，依沪 6.1/6.1.7 + 上交所投教 O32–O34（T-R10）】
      bse_min_buy: 100                # 北交所 ≥ 100 股，按 1 股递增【未核实；V1 不扫描北交所】
      bse_step: 1                     # 【未核实】
      odd_lot_sell_all: true          # 卖出时余额不足一个申报单位的部分须一次性申报卖出（沪 3.3.8、6.1.7；深 3.3.8；已核实，T-R10）
      star_odd_lot_threshold: 200     # 科创板零股阈值 = 200（沪 2023 第 6.1.7 条末句；已核实）；其他板块阈值 = buy_lot
      max_order_qty: 1000000          # 竞价单笔上限 100 万股（份）（沪 3.3.9 / 深 3.3.9；已核实）
      star_max_limit_order: 100000    # 科创板限价单笔 ≤ 10 万股（沪 2023 第 6.1.7 条；已核实）
      star_max_market_order: 50000    # 科创板市价单笔 ≤ 5 万股（沪 2023 第 6.1.7 条；已核实）
      star_max_after_hours: 1000000   # 科创板盘后固定价格单笔 ≤ 100 万股（沪 2023 第 6.2.6 条；已核实）
      chinext_max_limit_order: 300000 # 创业板限价单笔 ≤ 30 万股（深 3.3.9；已核实）
      chinext_max_market_order: 150000  # 创业板市价单笔 ≤ 15 万股（深 3.3.9；已核实）
    sessions:                         # 北京时间
      call_auction: ["09:15", "09:25"]
      morning: ["09:30", "11:30"]
      afternoon: ["13:00", "14:57"]
      closing_auction: ["14:57", "15:00"]
    t_plus: 1
    t0_round_trip:                    # 实行当日回转交易的品种（沪 3.1.5 / 深 3.1.5；类别已核实，无官方代码清单；T-R10 §3）
      fund_categories: [bond_etf, money_etf, gold_etf, commodity_futures_etf, cross_border_etf, cross_border_lof]
      cross_border_requires_t0_constituents: true   # 跨境类仅限跟踪成份证券/投资标的实施当日回转者（沪/深 3.1.5 第 2 款）
      unknown_category_default_t_plus: 1            # 实现约定（非规则原文）：类别缺失按 T+1 保守处理
      data_source: null                             # 未接入：选定并接入前全部 ETF 按 T+1，实现以本键非空为前提（2.13 ETF 当日回转行，v0.2.9 内 T-O11 裁定）
    fees:
      stamp_duty_sell_pct: 0.05       # 印花税仅卖出；2023-08-28 起减半征收为 0.05%（财政部 税务总局公告 2023 年第 39 号）
      transfer_fee_pct: 0.001         # 过户费双向
      commission_rate_default_pct: null   # 佣金按用户费率；null = 未设置时由导入成交反推，仍无则提示用户填写
      commission_min_yuan: 5          # 单笔最低 5 元：证监发〔2002〕21 号《关于调整证券交易佣金收取标准的通知》第一条（A 股每笔佣金不足 5 元按 5 元收取；证监会法规库 2026-11-10 查为现行有效）；费率由券商自定（同文第六条），以用户实际为准
      slippage_default_pct: 0.1       # 模板参数默认值
    impact_cost:                      # 【编排者默认，用户可否决；初值待校准】第 9 节 C(7)
      adv_basis: amount
      adv_window_days: 20
      tiers:                          # 参与率上界（%，含） → 成本（bp）
        - {max_participation_pct: 0.1, bp: 0}    # I1
        - {max_participation_pct: 0.5, bp: 5}    # I2
        - {max_participation_pct: 1.0, bp: 15}   # I3
        - {max_participation_pct: 2.0, bp: 30}   # I4
        - {max_participation_pct: null, bp: 60}  # I5（> 2%）
    unfillable:
      one_price_limit_up_blocks_buy: true
      one_price_limit_down_blocks_sell: true
      skip_suspended: true
    risk_warning:
      daily_buy_cap_shares: 500000    # 适用（沪 2023 第 4.4.12 条，仅竞价 + 大宗；深 2023 第 4.5.4 条）；只影响回看，不影响当前草案
      applies_to_boards: [main_board, chinext]  # 科创板不适用
      limit_order_only: true
      limit_order_only_exchanges: [SH]
  - effective_from: "2023-04-10"      # 2023-04-10 ～ 2023-08-27：除 stamp_duty_sell_pct: 0.1 外与上一段相同（文件中写全，不做继承）。起始日取沪深主板注册制新股首批上市日，依据 O9、O10 第 10.9 条（日历日期由政府网转载证监会信息确认，交易所原页未找到）；【已定 2026-11-01】更早的规则（创业板 2020-08-24 前为 10%、主板新股首日按发行价 144%/64% 等）不建模
    price_limit_pct:                  # 同上一段
      main_board: 10
      main_board_st: 5                # 【已核实】2026-07-06 之前沪深主板 ST/*ST 为 5%（出处同上一段）
      chinext: 20                     # 创业板（含风险警示）
      star: 20                        # 科创板（含风险警示）
      bse: 30                         # 北交所（含风险警示）
    no_limit:                         # 无涨跌幅限制的情形（以交易所规则为准）
      registered_ipo_first_days: 5    # 沪深注册制新股上市前 5 个交易日
      bse_ipo_first_days: 1
      delisting_period_first_day: true
    lot:
      buy_lot: 100                    # 沪/深主板、创业板、ETF 竞价买入为 100 股（份）或其整数倍（沪 3.3.8 / 深 3.3.8，已核实）
      star_min_buy: 200               # 科创板股票/CDR 单笔 ≥ 200 股，买卖均适用（沪 2023 第 6.1.7 条，已核实）
      star_step: 1                    # 200 股以上按 1 股递增【部分核实：规则无明文，依沪 6.1/6.1.7 + 上交所投教 O32–O34（T-R10）】
      bse_min_buy: 100                # 北交所 ≥ 100 股，按 1 股递增【未核实；V1 不扫描北交所】
      bse_step: 1                     # 【未核实】
      odd_lot_sell_all: true          # 卖出时余额不足一个申报单位的部分须一次性申报卖出（沪 3.3.8、6.1.7；深 3.3.8；已核实，T-R10）
      star_odd_lot_threshold: 200     # 科创板零股阈值 = 200（沪 2023 第 6.1.7 条末句；已核实）；其他板块阈值 = buy_lot
      max_order_qty: 1000000          # 竞价单笔上限 100 万股（份）（沪 3.3.9 / 深 3.3.9；已核实）
      star_max_limit_order: 100000    # 科创板限价单笔 ≤ 10 万股（沪 2023 第 6.1.7 条；已核实）
      star_max_market_order: 50000    # 科创板市价单笔 ≤ 5 万股（沪 2023 第 6.1.7 条；已核实）
      star_max_after_hours: 1000000   # 科创板盘后固定价格单笔 ≤ 100 万股（沪 2023 第 6.2.6 条；已核实）
      chinext_max_limit_order: 300000 # 创业板限价单笔 ≤ 30 万股（深 3.3.9；已核实）
      chinext_max_market_order: 150000  # 创业板市价单笔 ≤ 15 万股（深 3.3.9；已核实）
    sessions:                         # 北京时间
      call_auction: ["09:15", "09:25"]
      morning: ["09:30", "11:30"]
      afternoon: ["13:00", "14:57"]
      closing_auction: ["14:57", "15:00"]
    t_plus: 1
    t0_round_trip:                    # 实行当日回转交易的品种（沪 3.1.5 / 深 3.1.5；类别已核实，无官方代码清单；T-R10 §3）
      fund_categories: [bond_etf, money_etf, gold_etf, commodity_futures_etf, cross_border_etf, cross_border_lof]
      cross_border_requires_t0_constituents: true   # 跨境类仅限跟踪成份证券/投资标的实施当日回转者（沪/深 3.1.5 第 2 款）
      unknown_category_default_t_plus: 1            # 实现约定（非规则原文）：类别缺失按 T+1 保守处理
      data_source: null                             # 未接入：选定并接入前全部 ETF 按 T+1，实现以本键非空为前提（2.13 ETF 当日回转行，v0.2.9 内 T-O11 裁定）
    fees:
      stamp_duty_sell_pct: 0.1        # 印花税仅卖出；2023-08-28 减半前为 0.1%（《中华人民共和国印花税法》所附《印花税税目税率表》证券交易栏：成交金额的千分之一，2022-07-01 起施行；对出让方征收，见同法第三条；T-A148 复审 S9）；减半施行日见财政部 税务总局公告 2023 年第 39 号
      transfer_fee_pct: 0.001         # 过户费双向
      commission_rate_default_pct: null   # 佣金按用户费率；null = 未设置时由导入成交反推，仍无则提示用户填写
      commission_min_yuan: 5          # 单笔最低 5 元：证监发〔2002〕21 号《关于调整证券交易佣金收取标准的通知》第一条（A 股每笔佣金不足 5 元按 5 元收取；证监会法规库 2026-11-10 查为现行有效）；费率由券商自定（同文第六条），以用户实际为准
      slippage_default_pct: 0.1       # 模板参数默认值
    impact_cost:                      # 【编排者默认，用户可否决；初值待校准】第 9 节 C(7)
      adv_basis: amount
      adv_window_days: 20
      tiers:                          # 参与率上界（%，含） → 成本（bp）
        - {max_participation_pct: 0.1, bp: 0}    # I1
        - {max_participation_pct: 0.5, bp: 5}    # I2
        - {max_participation_pct: 1.0, bp: 15}   # I3
        - {max_participation_pct: 2.0, bp: 30}   # I4
        - {max_participation_pct: null, bp: 60}  # I5（> 2%）
    unfillable:
      one_price_limit_up_blocks_buy: true
      one_price_limit_down_blocks_sell: true
      skip_suspended: true
    risk_warning:
      daily_buy_cap_shares: 500000    # 适用（沪 2023 第 4.4.12 条，仅竞价 + 大宗；深 2023 第 4.5.4 条）；只影响回看，不影响当前草案
      applies_to_boards: [main_board, chinext]  # 科创板不适用
      limit_order_only: true
      limit_order_only_exchanges: [SH]
```

**`config/risk_controls.yaml`**（RC1–RC6 系统默认，2.5.6；用户可在 `/risk-controls` 覆盖，在 `min`/`max` 范围外返回 `422 RISK_CONTROL_INVALID_PARAMS`）
```yaml
schema_version: 1
rc1_stop_take:                  # 每笔建议带止损/止盈
  enabled: true
  long_horizon_default_stop_pct: -20   # 中长线默认价格止损，可关
  clamp_to_price_limit: true           # 止损/止盈价限制在当日/次日涨跌停价内
rc2_position_cap:
  enabled: true
  single_position_max_pct: 20   # 单只市值 ≤ 总资产 20%（画像可调；用户可调范围 ◇ 5–50）
rc3_total_exposure:             # 总仓位参考区间（%），按 market_regime；日报 regime_position_range 读这里
  enabled: true
  regime_ranges:
    uptrend: [60, 90]
    range: [40, 60]
    downtrend: [0, 30]
  regime_confirm_days: 2        # regime 防抖天数
rc4_sector_concentration:
  enabled: true
  sw_l1_max_pct: 40             # 单一申万一级行业
  concept_max_pct: 50           # 单一概念
rc5_loss_streak_drawdown:
  enabled: true
  closed_loss_streak: 3         # 已平仓连续亏损笔数
  drawdown_from_peak_pct: 10    # 账户净值自高点回撤
  strategy_sim_fail_streak: 5   # 某策略模拟跟踪连续失败次数
  pause_on_trigger: true        # 触发即挂 LOSS_STREAK_PAUSE（2.5.9），用户确认恢复或期满解除
  pause_days: 5                 # ◇ 暂停期（交易日）
  sim_fail_horizon_by_horizon:  # ◇ 模拟失败计数所用跟踪期（T-A36，用户选 B：按策略周期，仅本人）
    intraday_t: 1
    short: 5
    swing: 20
    long: 20
rc6_plan_violation:
  enabled: true
  checks: [opposite_side, qty_over_plan, held_after_invalidation, buy_without_stop, buy_during_wait]
executability:                  # 2.5.9 原因码的默认阈值
  low_confidence_threshold: 0.4 # LOW_CONFIDENCE
  new_listing_min_days: 30      # NEW_LISTING：上市不满 N 个交易日只阻断买入（与 2.5.11 gate_tradability 的 30 日一致）
  cooling_off_after_stop:       # COOLING_OFF：止损后冷静期（第 9 节问题 31：功能提供、默认关闭、N=3）
    enabled: false
    days: 3
  same_template_cooldown_days: 3  # 同模板同证券冷却 3 个交易日（问题 30）
  # DATA_STALE 的阈值不在此处，统一用 realtime.yaml 的 stale_threshold_s

health:
  internal_recover_ratio: 0.8   # 内部复验恢复阈值（T-A33 第 9 点；仅 Phase 3 内部评估启用时生效）
```

- **T-A25（架构师 2026-11-08）**：RC1–RC5 用户可调参数的 min/max 以 api-contract §7.11.2“参数范围”表为准；本 yaml 只存默认值，不改。

**`config/horizon_classifier.yaml`**（周期分类器的**框架参数**与种子版本，2.5.3；导入为不可变的 `horizon_classifier_versions`，规则正文由策略研究员给出）
```yaml
schema_version: 1
version_no: 3                    # T-A06：画像类 requires 改为 mode: hint（v1、v2 不可变，保留）；v2 = T-A03 新增 SH0C、IT0C
classifier_version: "1.2.0"     # v3 = "1.2.0"，v2 = "1.1.0"；T-A03 新增键：对外的语义化版本（契约 /horizon-assessments.classifier_version，正则见契约 §7.4 `/horizon-assessments`）；v1 = "1.0.0"
suitable_threshold: 60          # int，0–100 分 ≥ 60 列为“适合”
reasons_per_horizon: [2, 4]     # 每个周期给 2–4 条理由
recompute:
  "on": [import_confirm, watchlist_add, weekly, position_open_close]   # 键加引号（YAML 1.1 会把裸 on 读成 true）；position_open_close：某证券持仓由 0 变为 > 0 或清零时重算该证券（T-A02 采纳研究员建议，intraday_t 依赖 user.has_position）
  weekly_day: saturday
features:                       # 分类器输入（T-A02 统一前缀）：f.* 必须都在 feature_catalog 中，否则启动失败；sec.*（证券主数据）、user.*（导入成交/持仓统计）、profile.*（/me/profile）由系统提供，不进 feature_catalog
  - f.amount_20d_avg            # 新增：成交额 20 日均值（元）
  - f.turnover_20d_avg
  - f.amihud_20d                # v1 规则未用，保留
  - f.volatility_20d
  - f.intraday_amplitude_20d
  - f.ma_trend
  - f.momentum_60d
  - f.roe_ttm
  - f.profit_cagr_3y
  - f.dividend_continuous_years
  - f.limit_up_count_20d
  - f.fin_report_count          # 新增：已披露财报期数
  - f.list_days                 # 已用于 G-01
  - f.is_st                     # 新增或与 G-01 共用：风险警示状态
  - f.is_delisting_period       # 新增：退市整理期
  - sec.type                    # 新增：证券类型（主数据，不是时间序列特征）
  - sec.board                   # 新增：板块
  - user.has_position           # 新增：当前是否有持仓
  - user.avg_holding_days
  - user.has_t_trades
  - profile.horizon_pref
  - profile.effort
  - profile.risk_tolerance      # 新增（契约 /me/profile 已有）
  - profile.experience          # 新增（契约 /me/profile 已有）
rules:
  rule_schema: 1                     # 本规则块的结构版本（T-A02 已确认导入器按此结构解析）
  calibration: initial_values        # 全部阈值与分值为初值，待模拟跟踪/内部评估校准；不是统计结论
  rank_pct_universe: "T−1 日盘后落库截面：沪深 A 股股票，剔除北交所、停牌、上市 < 20 个交易日；平均秩 / N，取值 [0, 1]"
  data_missing_cap: {missing_points_ge: 40, cap: 59}   # 某周期中因 f.* 缺失而拿不到的满分合计 ≥ 40 → 该周期最高 59 分
  tie_order: [long, swing, short, intraday_t]          # suitable[] 同分时的排序
  gates:                             # 按顺序全部求值；score 取 0 优先，其次取最小 cap
    - {id: HG1, input: sec.type, op: ne, value: stock, horizons: all, score: 0,
       reason: "分类器只覆盖 A 股股票（ETF、可转债等不分类）"}
    - {id: HG2, input: sec.board, op: eq, value: bse, horizons: all, score: 0,
       reason: "首版不含北交所（plan 第 9 节 C(8)）"}
    - {id: HG3, input: f.is_delisting_period, op: eq, value: true, horizons: all, score: 0,
       reason: "退市整理期：不分类"}
    - {id: HG4, input: f.is_st, op: eq, value: true, horizons: all, cap: 59,
       reason: "风险警示股票（ST/*ST）：可交易性闸门阻断买入方向，不列为适合"}
    - {id: HG5, input: f.list_days, op: lt, value: 20, horizons: all, cap: 59,
       reason: "上市不足 20 个交易日：历史太短"}
    - {id: HG6, input: f.list_days, op: lt, value: 60, horizons: [swing, long], cap: 59,
       reason: "上市不足 60 个交易日：60 日趋势与动量无法计算"}
    # T006e（契约 v0.2.6）：gates 命中写入 caps[]，kind: gate、rule_id: HGn；判 0 分的 HG1–HG3 记 cap: 0
  horizons:
    intraday_t:
      requires:
        - {id: IT0, input: user.has_position, op: eq, value: true, else_score: 0,
           reason: "做T 需要已有底仓（T+1：当日买入不能当日卖出）"}
        # T006e（契约 v0.2.6）：IT0 的 else_score: 0 是分数，不进 caps[]，只写 reasons[]；hints[] 与分数无关，判 0 分的周期照样给 IT0C 提示
        # T-A06：requires 规则新增可选键 mode: cap（默认）| hint。hint 规则不得带 else_cap/else_score；输入未填写时跳过（不提示、不封顶）；
        #        不满足时只写入输出 hints[]（{horizon, rule_id, text}），不改分数、不进 caps[]。画像类规则全部为 hint（用户 2026-11-02 决定）
        - {id: IT0B, input: profile.effort, op: in, value: [medium, high], mode: hint,
           reason: "做T 需要盘中盯盘，您自报的精力为低"}
        - {id: IT0C, input: profile.experience, op: in, value: [intermediate, advanced], mode: hint,
           reason: "做T 需要盘中决断与纪律，您自报的经验为新手"}   # 【用户已定 2026-11-02】只在自报 novice 时提示
      components:
        - {id: IT1, input: f.intraday_amplitude_20d, transform: rank_pct,
           bands: [{op: ge, value: 0.7, pts: 30}, {op: ge, value: 0.5, pts: 20}, {op: ge, value: 0.3, pts: 10}],
           text: "近 20 日日内振幅位于全市场 {v:pct} 分位"}
        - {id: IT2, input: f.amount_20d_avg, unit: CNY,
           bands: [{op: ge, value: 500000000, pts: 25}, {op: ge, value: 200000000, pts: 15}, {op: ge, value: 100000000, pts: 5}],
           text: "近 20 日日均成交额 {v:yi} 亿元"}
        - {id: IT3, input: profile.effort,
           bands: [{op: eq, value: high, pts: 20}, {op: eq, value: medium, pts: 10}],
           text: "画像精力：{v}"}
        - {id: IT4, input: user.has_t_trades,
           bands: [{op: eq, value: true, pts: 15}],
           text: "该股导入成交中{v:has}同日买卖（做T）记录"}
        - {id: IT5, input: profile.experience,
           bands: [{op: eq, value: advanced, pts: 10}, {op: eq, value: intermediate, pts: 5}],
           text: "画像经验：{v}"}
    short:
      requires:
        - {id: SH0, input: profile.risk_tolerance, op: ge, value: 3, mode: hint,
           reason: "短线波动大，您自报的风险承受 < 3"}
        - {id: SH0B, input: profile.effort, op: in, value: [medium, high], mode: hint,
           reason: "短线需要每日跟踪，您自报的精力为低"}
        - {id: SH0C, input: profile.experience, op: in, value: [intermediate, advanced], mode: hint,
           reason: "短线需要盯盘与止损纪律，您自报的经验为新手"}   # 【用户已定 2026-11-02】只在自报 novice 时提示（取代问题 37 方案 A）
      components:
        - {id: SH1, input: f.amount_20d_avg, unit: CNY,
           bands: [{op: ge, value: 300000000, pts: 20}, {op: ge, value: 100000000, pts: 10}],
           text: "近 20 日日均成交额 {v:yi} 亿元"}
        - {id: SH2, input: f.turnover_20d_avg, transform: rank_pct,
           bands: [{op: ge, value: 0.6, pts: 15}, {op: ge, value: 0.4, pts: 8}],
           text: "近 20 日平均换手率位于全市场 {v:pct} 分位"}
        - {id: SH3, input: f.limit_up_count_20d, unit: count,
           bands: [{op: ge, value: 2, pts: 15}, {op: ge, value: 1, pts: 10}],
           text: "近 20 日涨停 {v} 次"}
        - {id: SH4, input: f.volatility_20d, transform: rank_pct,
           bands: [{op: between, value: [0.4, 0.9], pts: 10}],
           text: "近 20 日波动率位于全市场 {v:pct} 分位（0.4–0.9 加分，过低或过高不加）"}
        - {id: SH5, input: f.ma_trend, unit: pct,
           bands: [{op: gt, value: 0, pts: 10}],
           text: "均线趋势值 {v}（> 0 为多头排列）"}
        - {id: SH6, input: profile.horizon_pref,
           bands: [{op: contains, value: short, pts: 15}],
           text: "画像周期偏好：{v}"}
        - {id: SH7, input: profile.effort,
           bands: [{op: eq, value: high, pts: 10}, {op: eq, value: medium, pts: 5}],
           text: "画像精力：{v}"}
        - {id: SH8, input: user.avg_holding_days, unit: trading_days,
           bands: [{op: le, value: 5, pts: 5}],
           text: "该股历史平均持有 {v} 个交易日"}
    swing:
      requires: []
      components:
        - {id: SW1, input: f.amount_20d_avg, unit: CNY,
           bands: [{op: ge, value: 100000000, pts: 15}, {op: ge, value: 50000000, pts: 8}],
           text: "近 20 日日均成交额 {v:yi} 亿元"}
        - {id: SW2, input: f.ma_trend, unit: pct,
           bands: [{op: gt, value: 0, pts: 20}],
           text: "均线趋势值 {v}（> 0 为多头排列）"}
        - {id: SW3, input: f.momentum_60d, unit: pct,
           bands: [{op: gt, value: 0, pts: 15}],
           text: "近 60 日动量 {v}（> 0 为上涨）"}
        - {id: SW4, input: f.volatility_20d, transform: rank_pct,
           bands: [{op: le, value: 0.8, pts: 10}],
           text: "近 20 日波动率位于全市场 {v:pct} 分位（≤ 0.8 加分）"}
        - {id: SW5, input: f.roe_ttm, unit: pct,
           bands: [{op: gt, value: 0, pts: 10}],
           text: "ROE(TTM) {v}%"}
        - {id: SW6, input: profile.horizon_pref,
           bands: [{op: contains, value: swing, pts: 20}],
           text: "画像周期偏好：{v}"}
        - {id: SW7, input: user.avg_holding_days, unit: trading_days,
           bands: [{op: between, value: [5, 60], pts: 10}],
           text: "该股历史平均持有 {v} 个交易日"}
    long:
      requires:
        - {id: LG0, input: f.fin_report_count, op: ge, value: 12, else_cap: 59,
           reason: "已披露财报不足 12 期（或缺失）：基本面历史不完整"}
        - {id: LG0B, input: f.roe_ttm, op: not_null, else_cap: 59,
           reason: "ROE(TTM) 缺失：无法判断质量"}
        # T006e（契约 v0.2.6，架构师归类）：LG0/LG0B 的 else_cap 属于数据不足，写入 caps[] 时 kind: data_missing、rule_id: LG0/LG0B
      components:
        - {id: LG1, input: f.fin_report_count, unit: count,
           bands: [{op: ge, value: 12, pts: 15}],
           text: "已披露财报 {v} 期"}
        - {id: LG2, input: f.roe_ttm, unit: pct,
           bands: [{op: ge, value: 10, pts: 20}, {op: ge, value: 5, pts: 10}],
           text: "ROE(TTM) {v}%"}
        - {id: LG3, input: f.profit_cagr_3y, unit: pct,
           bands: [{op: gt, value: 0, pts: 15}],
           text: "近 3 年净利润复合增速 {v}%"}
        - {id: LG4, input: f.dividend_continuous_years, unit: years,
           bands: [{op: ge, value: 3, pts: 15}, {op: ge, value: 1, pts: 8}],
           text: "连续分红 {v} 年"}
        - {id: LG5, input: f.volatility_20d, transform: rank_pct,
           bands: [{op: le, value: 0.6, pts: 10}, {op: le, value: 0.8, pts: 5}],
           text: "近 20 日波动率位于全市场 {v:pct} 分位"}
        - {id: LG6, input: profile.horizon_pref,
           bands: [{op: contains, value: long, pts: 20}],
           text: "画像周期偏好：{v}"}
        - {id: LG7, input: user.avg_holding_days, unit: trading_days,
           bands: [{op: ge, value: 60, pts: 5}],
           text: "该股历史平均持有 {v} 个交易日"}
```
`rules` 为空时分类器不输出“适合”，前端显示“周期分类规则未配置”，用户可手动选择周期。规则见 `docs/strategies/horizon_classifier.md` v1（T006a；判定顺序见该文 §3，比较语义见 §4 末尾“边界与比较语义”）。

- **用户输入口径（v0.2.9 内，T-B46/T-B47 裁定）**：`user.avg_holding_days` **按证券计算**（v0.2.9 内，T-O11 评审裁定）：只统计本人在**该证券**上的已平仓买入批次（本人全部账户、最近 365 个自然日内），按 FIFO 配对卖出，持有交易日数（买入日到卖出日的交易日数，同日买卖为 0）按成交数量加权平均，四舍五入取整；作废成交不计；该证券的已平仓批次少于 3 个时为 null，按未填写处理（不封顶、不提示，问题 76）；逐条细则（各账户分别 FIFO 后合并、按卖出日落窗、转入与无法追溯的期初持仓不计等）见 `docs/strategies/feature_spec.md` §10.1。`f.is_st` = 主数据 `risk_flag ∈ {st, star_st, delisting}`（`st` = ST，`star_st` = *ST 即“退市风险警示”，`delisting` = 证券简称带“退”、处于退市整理期的标记；三者都按风险计入，问题 77；措辞更正（v0.2.9 内，T-O11 评审裁定））；`f.is_delisting_period` 只看 `listing_status = delisting_period`。
- **导入器（T-A02 已定）**：采用结构化 `rule_schema: 1`（`gates` / `requires` / `components` / `bands`），不改写为 DSL 字符串；导入时校验：`f.*` 的 `unit` 与 feature_catalog 一致（不一致拒绝导入，不静默换算）、所有 `id` 唯一、每个周期 components 满分合计 = 100。
- **输出（契约 v0.2.2）**：`scores` 四个周期都给 0–100 整数、不为 null（闸门/前提判 0 分时附不适合理由）；`reasons[]` 元素带 `horizon` 与 `polarity: for/against`，与 `symbol_horizon_assessments.reasons` 一致；另返回 `inputs_missing: string[]`（缺失的 `f.*` 键），用来区分“真 0 分”与“缺数据被封顶”（horizon_classifier.md §8 缺口 1、2 均由契约 v0.2.2 解决）。**契约 v0.2.3**：`inputs_missing` 只含 feature_catalog 键（`f.*`），去重、升序，永不为 null，无缺失为 `[]`；新增 `caps[]`（`{horizon, cap, kind, rule_id, inputs_missing}`，说明每个周期为何被封顶；`kind` 现为 `gate|data_missing`，见下）；响应带 `snapshot_id` 与 `evidence[]`，理由的 `evidence_ids` 只在本响应内解析；`classifier_version` 为语义化版本字符串（如 `"1.1.0"`），与 `horizon_classifier_versions.semver` 一致。**契约 v0.2.5（T-A06）**：新增 `hints[]`（`{horizon, rule_id, text}`，画像类 `mode: hint` 规则在画像已填写且不满足时的提示，永不为 null）；画像类规则不再进 `caps[]`；当前版本 `"1.2.0"`。**契约 v0.2.6（T006e）**：`caps[].kind` 改为 `gate | data_missing`（HG1–HG6 → `gate`；`LG0`/`LG0B` → `data_missing`）；`IT0` 判 0 分不进 `caps`；`hints[]` 与分数无关（已判 0 分的周期照样给提示）。
- `intraday_t` 列为“适合”只表示周期匹配；T-01 在 C(5) 下仍只出盘后统计，前端文案需说明。

**`config/llm.yaml`**（LLM 网关，2.7、2.7.1、2.7.2；`tasks.*`、`models.*.price_*`、`gateway.max_concurrency` 可热调，其余改 YAML 后重启）
```yaml
schema_version: 1
providers:
  deepseek:
    kind: openai_compatible
    base_url: "https://api.deepseek.com"   # 官方 OpenAI 格式 base_url；不可热调；必须 https 且主机在 allowed_hosts 内
    allowed_hosts: ["api.deepseek.com"]
    api_key_env: DEEPSEEK_API_KEY          # 只写变量名；值只在环境变量中，只校验非空（官方未公布 key 格式，不做前缀/长度正则）
    user_id_mode: hmac                     # 传 "u_" + HMAC 前 16 位十六进制；共享段落传 "shared"
models:
  deepseek-flash:
    provider: deepseek
    context_window_tokens: 1000000         # 官方：1M
    max_output_tokens_cap: 384000          # 官方：最大 384K
    thinking: disabled                     # ◇ 解释任务显式关闭（官方默认开启）
    json_output: true                      # response_format: {type: json_object}
    currency: CNY
    price_per_1m_peak: {input_cache_hit: "0.04", input_cache_miss: "2", output: "8"}       # 官方价目，2026-11-01 核实
    offpeak_multiplier: "0.5"              # 官方：空闲时段为高峰价一半
    price_checked_at: 2026-11-01
  deepseek-v4-pro:                         # V1 不路由到它；保留给 T-B39 策略草稿评估
    provider: deepseek
    context_window_tokens: 1000000
    max_output_tokens_cap: 384000
    thinking: disabled
    json_output: true
    currency: CNY
    price_per_1m_peak: {input_cache_hit: "0.30", input_cache_miss: "9.0", output: "27.0"}
    offpeak_multiplier: "0.5"
    price_checked_at: 2026-11-01
pricing_calendar:                          # 只用于成本估算；月底按账单对账
  timezone: Asia/Shanghai
  peak_weekdays: [mon, tue, wed, thu, fri] # 不含法定节假日（用交易日历近似）
  peak_windows: ["09:00-12:00", "14:00-18:00"]
gateway:
  connect_timeout_s: 5                     # ◇
  call_deadline_s: 90                      # ◇ 单次调用含重试与退避的总截止时间
  max_concurrency: 8                       # ◇ 远低于官方账号并发（flash 2500）
  retry:
    max_retries: 2                         # 与 2.7 已定默认一致
    backoff_base_s: 1
    backoff_max_s: 8
    jitter: full
    retry_on_status: [429, 500, 503]       # 官方错误码页：500“等待后重试”、503“稍后重试”；429 为速率/并发上限
    retry_on_network_error: true           # 连接失败、读超时
    retry_on_empty_json: 1                 # JSON 模式返回空/全空格 content 时重试 1 次
    no_retry_status: [400, 401, 402, 422]  # 401/402 另置供应商状态并告警（2.7.2）
  circuit_breaker:
    consecutive_5xx: 5                     # ◇
    open_s: 300                            # ◇
  on_429_halve_concurrency_s: 300          # ◇
tasks:                                     # 默认路由；管理端覆盖存 llm_task_routes
  suggestion_rationale:      {model: deepseek-flash, fallback_models: [], timeout_s: 30, max_output_tokens: 800,  temperature: 0.3}
  daily_report_stock:        {model: deepseek-flash, fallback_models: [], timeout_s: 30, max_output_tokens: 800,  temperature: 0.3}
  daily_report_summary:      {model: deepseek-flash, fallback_models: [], timeout_s: 60, max_output_tokens: 1500, temperature: 0.3}
  strategy_divergence:       {model: deepseek-flash, fallback_models: [], timeout_s: 30, max_output_tokens: 800,  temperature: 0.3}
  announcement_title_digest: {model: deepseek-flash, fallback_models: [], timeout_s: 30, max_output_tokens: 600,  temperature: 0.2}
budget:
  daily_budget_cny: null                   # 由管理员在后台设定（问题 16）；null = 不限，但仍记录成本
  prefer_offpeak_for_batch: false          # ◇ true 时盘后日报的 LLM 段落推迟到 18:00 后生成（半价，但日报晚约 30 分钟）
```
`max_output_tokens`、`temperature`（◇）是本节给的工程默认值；`timeout_s` 30 秒与 `max_retries` 2 次沿用 2.7。`fallback_models` 为空表示失败直接回落模板（同一供应商内切换模型不能应对供应商故障）。环境变量只有 `DEEPSEEK_API_KEY` 一项，不允许用环境变量改 `base_url`。


**`config/imports.yaml`**（交割单导入，3.5；`api` 与 `worker` 读取；T-A05 定，回应 T-B02a。**不可热调**，改后重启；`max_request_bytes` 须与 nginx `client_max_body_size` 同步修改）
```yaml
schema_version: 1
max_file_bytes: 5242880         # int，单文件上限 5 MiB（3.5 “≤ 5 MB”按 MiB 计）；超限 422 IMPORT_FILE_ERRORS + IMPORT_FILE_TOO_LARGE，不创建批次
max_files_per_upload: 5         # int，单次上传文件数上限（3.5）
max_request_bytes: 27262976     # int，框架层请求体上限 = nginx client_max_body_size 26m；必须 > max_file_bytes × max_files_per_upload（否则启动失败）；超限 413 PAYLOAD_TOO_LARGE {max_bytes}
max_rows_per_file: 50000        # int，数据行上限；超限 IMPORT_TOO_MANY_ROWS（导入码 #4）
allowed_extensions: [".txt", ".csv"]   # list[str]，小写比较（3.5 MVP）；其他 → IMPORT_UNSUPPORTED_FILE_TYPE
raw_file_retention_days: 365    # int，原始文件留存天数（第 9 节问题 21 已定）；账户注销时提前删除；用户可手动删除
```
- **键路径**：`imports.max_file_bytes` 等（`Settings.business.imports.*`）。T-B02a 暂放的 `ingest.imports.*` 作废：`ingest.yaml` 只由 `ingest` 进程读取、与持有 licence 的采集服务隔离，上传上限属于 `api`，不应混入。
- **存储路径不进 YAML**：原始文件目录只来自环境变量 `IMPORT_STORAGE_PATH`（部署相关，见 2 节环境变量表、3.5A 存储要求）；YAML 里不设路径键，也不设 `*_env` 引用键。
- 环境变量不能覆盖本文件的键。

**`config/auth.yaml`**（认证、会话、邀请码、审核提示，3.6；`api` 读取；T-A05 定，回应 T-B03。**不可热调**，改后重启；注册模式仍由环境变量 `REGISTRATION_MODE` 决定，不在本文件）
```yaml
schema_version: 1
password:
  min_len: 10                   # int，≥ 10（3.6 已定），模型校验下限 10
  max_len: 128                  # int ◇，上限防止超长输入
password_hash:                  # argon2id；改参数后新哈希用新参数，旧哈希在下次登录成功时透明升级
  memory_kib: 65536             # int，64 MiB（3.6）；下限 19456（OWASP 最低配置）
  time_cost: 3                  # int；下限 2
  parallelism: 1                # int；下限 1
  hash_len: 32                  # int ◇；下限 16
  salt_len: 16                  # int ◇；下限 16
session:
  idle_ttl_s: 604800            # int，空闲过期 7 天，每次有效请求续期（契约 §1.3）
  absolute_ttl_s: 2592000       # int ◇，自登录起 30 天绝对过期，不续期；必须 ≥ idle_ttl_s
  remember_me: false            # bool，V1 固定 false（模型只接受 false）；不提供“记住我”
invite:
  code_bytes: 16                # int，128 位随机（secrets）；下限 16
  default_ttl_h: 168            # int，默认 7 天过期
  max_ttl_h: 720                # int，管理员可设的最长有效期 30 天
  max_uses: 1                   # int，V1 只支持单次使用（模型只接受 1）
admin:
  same_ip_highlight_threshold: 3   # int ◇，审核列表中同 IP 注册数超过此值时高亮，只作提示（3.6，T-A05 D8）
```
- 固定规则（不是配置项）：哈希算法只用 argon2id；Cookie `sid` 为 `HttpOnly; SameSite=Lax; Path=/`，`Secure` 由环境变量 `SESSION_COOKIE_SECURE` 控制（默认 true；`APP_ENV` 不是 `local`/`test` 时设为 false → 启动失败）；Cookie `Max-Age` = `absolute_ttl_s`，服务端同时按 `idle_ttl_s` 与 `absolute_ttl_s` 判定；登录与改密轮换会话，改角色/禁用/驳回/重置吊销全部会话（3.6）。
- 邀请码：明文 = `code_bytes` 随机字节的 Crockford Base32（无填充），入库前去连字符、转大写后做 `HMAC-SHA256(APP_MASTER_KEY, code)`；只由管理员发放；可选 `bound_username`；可吊销；`invite.created` / `invite.revoked` / `invite.redeemed` 写审计（不记明文）。
- **没有同意书版本配置**（T-A06）：不做同意流程，7c62f59 的 `consents.doc_versions` 与 T-A05 的 `legal_documents` 方案均作废；本文件也没有风险测评相关键。`config/risk_controls.yaml` 不受影响（单只上限 `rc2_position_cap.single_position_max_pct` 在画像未填 `max_single_position_pct` 时作为默认）。
- 环境变量不能覆盖本文件的键。

---

## 7. 风险与合规（验收项 7）

### 7.1 数据再分发授权（阻断级）
- **事实**【已核实，麦蕊《服务条款》】：2.1(5)"……不得将接口产品所涉查询核验结果用于约定以外的应用场景或者再次分发、销售、许可、分许可、授权、转售、出租、租借……转授权或转让集成使用，也不得将接口产品以任何形式交由第三方使用"；2.1(4) 证书"仅限于申请账号自行使用"；6.2 非排他、不可转让许可；条款开头"与线下协议有冲突之处以线下协议为准"；2.2 提供定制服务。
- **判断**：多用户公开网站向他人展示麦蕊行情/财务/因子数据，按字面属于"交由第三方使用/再次分发"，**高度可能违约**（后果：终止服务、违约赔偿）。
- **应对**（需用户拍板）：
  1. **首选**：联系麦蕊（QQ 3826425416 / 企业顾问表单）取得**书面授权**（对外展示范围、是否允许展示原始数值、是否需企业版、费用）。
  2. 授权前：只做**封闭内测**（仅用户本人/少量明确告知的测试者），或技术上只对外展示"派生结果"（如是否满足用户条件、分位区间）——派生数据是否也受限仍【待核实】，不能视为合规方案。
  3. 备选数据源：交易所授权行情商、Tushare Pro 商用授权等，均需书面确认。
- **交易所行情授权**：在公开网站展示沪深实时行情，业内通常需要上交所/深交所下属信息公司的行情经营许可【待核实具体要求，是否允许延时行情免授权】。
- 架构配合：数据源抽象（`ingest` 内的 provider 适配接口），可替换/叠加供应商；所有展示数据带 `provider` 字段便于合规审查与下架。
- **T-A07 每用户自用证书的合规分析（2026-11-02；用户已定为每位朋友单独买一张证书，第 9 节问题 49）**：
  - 依据（2026-11-02 再次查阅）：《服务条款》https://www.mairuiapi.com/legal （同 https://mairui.club/legal ）2.1(4)“证书仅限于申请账号自行使用”、2.1(5)（见上）；FAQ https://www.mairui.club/faq （“证书可在您名下多套系统共用”、60 秒 2 个 IP、错误码 101/102/103）；帮助 https://mairui.club/help ；证书申请 https://www.mairuiapi.com/getlicence ；联系方式 https://www.mairuiapi.com/linkmeans ；证书查询 https://www.mairuiapi.com/query 。
  - **每人用自己的证书、只看自己证书取的数据（`per_licence`，默认）**：数据只给证书持有人本人用，最接近“申请账号自行使用”，按字面**基本合规**。前提与剩余风险：① 证书应以朋友本人账号申请、由朋友持有（用户可以代付费用）；若登记在用户名下再给朋友用，可能被认定为“交由第三方使用/转让”；② 用户作为运营方在自己服务器上代朋友调用其证书，条款没有明确允许或禁止【待麦蕊书面确认】；③ 一台服务器、一个出口 IP 同时跑多位不同持有人的证书，FAQ 未说明【待麦蕊书面确认】；④ 跨证券的派生统计（分位、排名）也须只用本人证书的数据计算。
  - **全站共用一份数据（`shared_cache`）**：A 的证书取到的数据给 B 看，即使 B 也买了证书，按 2.1(5) 字面仍属“再次分发/交由第三方使用”，**不合规风险高**。**结论：标【待麦蕊书面确认】，取得书面答复前不得启用。**
  - 建议用户书面询问麦蕊（问题清单见第 9 节问题 50），保留答复记录。
  - 每人自用证书**不解决**：交易所行情授权（上文）、证券投资咨询资质（7.2）、朋友的敏感个人信息（7.3）。

### 7.2 证券投资咨询资质（操作建议功能的合规设计）—— 第 9 节问题 1
**结论先行**：主线功能（对个股给出 买入/加仓/持有/减仓/卖出/等待）在形式上属于"买卖时机建议 / 品种选择建议"。**向公众提供并直接或间接获取经济利益**，基本可以认定为证券投资咨询业务，须证监会核准；而证监会目前**暂不受理**该项新设审批（CEPA 安排除外）。因此"自己申请牌照"在现阶段不可行，必须在产品形态上控制风险，并在收费/公开前拍板。

**法规与案例（已核实）**
- 《证券法》（2019 修订）第一百六十条：从事证券投资咨询服务业务，应当经国务院证券监督管理机构核准；未经核准，不得为证券的交易及相关活动提供服务。第二百一十三条：擅自从事的，没收违法所得并处违法所得 1–10 倍罚款，无违法所得或不足 50 万元的处 50–500 万元罚款；直接责任人员处 20–200 万元罚款。（来源：证监会网站《证券法(2019修订)》PDF、法律法规速查第 213 条）
- 证监会政务服务指南"从事证券投资咨询服务业务核准"：除 CEPA 补充协议安排外"我会暂不受理该项审批"。（来源：csrc.gov.cn/csrc/c101968/c4188211/content.shtml）
- 证监会公告〔2012〕40 号（《关于加强对利用"荐股软件"从事证券投资咨询业务监管的暂行规定》）：具备"证券投资分析意见/价格预测""品种选择建议""买卖时机建议"等功能、向投资者销售或提供并直接或间接获取经济利益的软件属"荐股软件"，属证券投资咨询业务；**仅有证券信息汇总或历史数据统计功能**的除外。
- 深圳证监局〔2023〕4 号处罚案：当事人"只是提醒用户哪些股票符合特定条件"的抗辩未被采纳（模型条件由公司设定并推送股票）。启示：**"条件由系统设定 + 推送具体股票"即使措辞中性也可能被认定**。
- 投资者适当性：《证券期货投资者适当性管理办法》约束的是经营机构，我方不是持牌机构，原计划把其"风险测评 + 匹配 + 揭示"做法作为最佳实践引入；**T-A06 用户决定不做风险测评与同意流程**（仅朋友间私下使用、非商业），只保留固定免责提示与画像不匹配提示。

**产品形态的风险控制（MVP 全部实现）**
1. **措辞**：界面不用"推荐/建议买入"，统一用"**规则信号 / 操作选项**"："按《高ROE稳定增长 v3》规则：买入条件满足（5/6 条）"，并始终同时展示反证与失效条件；禁用"保证、必涨、稳赚、牛股、金股、目标价"等词（`compliance` 词表 + CI 测试，LLM 输出同样过滤）。
2. **用户配置规则**：建议只来自**用户启用的策略版本**（内置策略默认不启用，用户逐个阅读规则、适用条件和失效模式后勾选启用；阈值可改）；系统**不向未自选/未持有的股票主动推送**建议（筛选结果只在用户主动运行时展示）。
3. **风险揭示（T-A06 改）**：不做风险测评、不弹同意书；全站固定展示免责提示（`docs/strategies/compliance/disclaimer.md`，2.4）；画像（自报、选填）与策略 `fit` 或周期不匹配时，建议卡与实例只显示“与您的画像不匹配”的提示（`warnings[]`/提示文字），**不降低置信度**（置信度只反映信号证据，T006e 裁定 3）、不阻止、不要求确认；相关画像字段未填写时不提示。
4. **用户确认**：建议卡只有"知道了 / 不采纳 / 转为我的计划"；**不下单、不对接券商、不提供一键交易**；转为计划需要用户自己填写或确认数量与价格。
5. **不承诺收益**：不展示"历史胜率"营销语；模拟跟踪（2.8）只对本人可见、标注"模拟、样本有限、不代表未来"，不做对外排行/晒单。
6. **不个性化招揽**：不向公众发送个股信号广告，不设"跟单/喊单"群；外部通知渠道默认只发提醒不发个股动作。
7. **留痕**：每条建议不可变存档（含规则版本、数据快照、用户决定），便于应对问询。
8. **全站声明**："本工具仅供个人研究参考，不构成投资建议。候选信号由规则自动生成，数据可能延迟或出错，盈亏自负。"（`docs/strategies/compliance/disclaimer.md` 1.0，T-A06）

**缓解方案（三选一或组合，第 9 节问题 1 拍板）**

| 方案 | 做法 | 剩余风险 | 适合阶段 |
|---|---|---|---|
| A. 自用 / 邀请制封闭小组（免费） | 不开放注册审核以外的公众访问（管理员审核 + 邀请码），用户 10–100 人，不收费、无广告、无推广 | 中低：仍是"向他人提供买卖时机建议"，但无经济利益、范围封闭；需用户协议明确为个人研究工具 | **V1 推荐** |
| B. 与持牌证券投资咨询机构合作 | 持牌机构作为服务提供方（内容/规则由其合规审核、以其名义提供），我方作为技术服务商 | 低（取决于合作协议）；成本与商务周期高 | **收费前必须** |
| C. 降级为"工具"形态 | 只输出"规则条件满足情况"，不出现动作词（买入/卖出），由用户自行解读 | 低；但偏离"给出操作建议"的主线目标 | 若 A 也不可接受时的退路 |

- 任何**收费**（含会员）开通前，必须取得律师书面意见并优先走方案 B；会员体系（2.9）只预留数据结构。

### 7.3 个人信息保护（《个人信息保护法》《网络安全法》《数据安全法》）
- 持仓、成交、资金规模属于**金融账户相关信息**，按《个保法》第 28 条属于**敏感个人信息**。T-A06 用户决定不做单独同意弹窗与 `sensitive_financial_info` 门槛（注册即视为同意）；仍坚持告知用途（导入页文字说明）与最小化收集（不收集身份证、券商账号/密码、银行卡）。**朋友是第三方**，这一处理是否足够见第 9 节问题 48【风险提示，未决】。
- **交割单原始文件**含股东代码、资金明细等，同属敏感信息：上传前单独提示用途（解析与追溯）、默认保留 365 天（已定，问题 21）后自动删除、用户可随时删除单个原始文件、注销时一并删除；解析时股东代码明文不入库（只存 HMAC 与掩码，3.5A），资金账号、席位代码直接丢弃；管理员无权查看。
- 注册只收集用户名、密码与可选申请说明；邮箱为可选（仅用于通知），不收集手机号。
- 用户权利：查阅、更正；~~导出（`GET /me/export`，JSON+CSV）~~（T-B16 裁定 2026-11-02：不是用户需求，本版不做，契约中没有此端点）；**删除账号由管理员手动处理**（用户线下提出，管理员用 CLI 删除该用户数据与原始文件，审计日志保留脱敏记录），**不设自动留存期、不提供 `DELETE /me`**（T-A06，第 9 节问题 45）。
- **删除用户数据 CLI 规则**（T-B16 裁定，架构师 2026-11-02）：
  - **不放行维护会话**：不得使用会话变量、`session_replication_role`、专用角色绕过禁删或不可变触发器。此条不变：下面的 `aia_maint` 只拥有写入 `purging` 的权限，触发器对它的判定与其他角色相同（同样只在 `purging` 时放行规定的 DELETE 与匿名化 UPDATE）。
  - **按数据状态放行**：迁移把相关触发器改为，仅当 `app.users.status = 'purging'` 时，允许对该用户的行执行 DELETE 或规定的匿名化 UPDATE；其他情况仍拒绝。`purging` 只在 CLI 的单个事务内出现：先设为 `purging`，处理全部子表，最后删除 `users` 行。另加一个延迟约束触发器，**按行检查**（见下条第 3 点），保证这个状态不会被提交、不会留下放行窗口。api 代码里没有任何设置 `purging` 的路径。
  - **`purging` 的写入权（架构师裁定 2026-11-02，评审 45589c2 B1；与上文冲突时以此为准）**：
    1. 新增专用数据库角色 `aia_maint`，只供删除用户数据 CLI 使用；`api`、`ingest` 进程不得持有它的凭据。
    2. `app.users` 加 BEFORE INSERT/UPDATE 触发器：写入 `status='purging'` 只允许 `current_user = 'aia_maint'`，且只能用 UPDATE；INSERT 直接写成 `purging` 一律拒绝。`status` 一旦是 `purging`，就不能再改成任何其他值，处于 `purging` 的用户行只能被 DELETE。
    3. 延迟约束触发器按行检查：某行只要在本事务中被置为过 `purging`，提交时这个 `id` 就必须已不存在于 `app.users`，否则拒绝提交（不再依赖“全表是否还有 `purging` 行”的检查）。
    4. “不得用维护会话或专用角色绕过触发器”不变；`aia_maint` 只是能写入 `purging`，不影响触发器对它的判定。
    5. 运维更新 `deploy/db/roles/grants.sql` 与 `verify-roles.sh`：`aia_maint` 只授予 CLI 必需的权限；`aia_api`、`aia_ingest` 对 `ops.pending_file_purges` 没有任何权限；`verify-roles.sh` 断言 `aia_api` 在一个事务里执行“置 `purging` → 删除 → 改回 → 提交”会失败。
    6. **`aia_maint` 角色细则（v0.2.9 内，评审 be607b3/f72b8c7/8fd9502 裁定）**：① `aia_maint` 是 LOGIN 角色，按最小权限只授予 CLI 用到的表与列；`aia_api`、`aia_ingest` 都不得是它的成员（反过来也不得）；② CLI 只从 `AIA_MAINT_DATABASE_URL_FILE` 指向的文件读取连接串（文件不在镜像和仓库中，`api`、`ingest` 容器不挂载）；③ `grants.sql` 中对 `ops` 的 schema 级 GRANT 之后，显式 `REVOKE ALL ON ops.pending_file_purges FROM aia_api, aia_ingest`（必须放在 schema 级 GRANT 与 `ALTER DEFAULT PRIVILEGES` 之后，避免被覆盖）；④ `verify-roles.sh` 增加断言：`aia_maint` 可登录；`aia_api`、`aia_ingest` 不是 `aia_maint` 的成员（`pg_has_role(..., 'MEMBER')` 为 false）；`aia_api`、`aia_ingest` 对 `ops.pending_file_purges` 的 SELECT/INSERT/UPDATE/DELETE 都为 false；⑤ dry-run 也用 `aia_maint` 连接，或用一个对相关表只读的连接，不得用 `aia_api` 的连接。运维改 `deploy/db/roles/`，后端改 CLI 的连接读取。
    7. **`aia_maint` 列级授权原则（v0.2.9 内，T-O11 评审裁定）**：① 不得 SELECT 任何密文列（`user_data_licences.ciphertext`、LLM `api_key_ciphertext` 等）与 `app.users.password_hash`；② 不得 UPDATE `app.users.role`；③ SELECT 与 UPDATE 都按列授予：只授 CLI 实际读的列（主键、`user_id` 类关联列、文件路径等）和实际写的列（`app.users.status` 与匿名化细则列出的列）；DELETE 只对 CLI 清单内的表授予（PostgreSQL 没有列级 DELETE）。**后端**在 CLI 代码中维护一份“表 → SELECT 列 / UPDATE 列 / DELETE”的清单并随 CLI 改动同步，交给运维；**运维**在 `grants.sql` 用列级 GRANT 实现，`verify-roles.sh` 用 `has_column_privilege` 断言 ①② 为 false。
    8. **后台服务的数据库角色：`worker` 改用 `aia_api`（v0.2.9 内，架构师裁定 2026-11-01，与 T-O10/T-O11 分库角色一致；review-028c077 M1）**：① `worker` 现用库属主连接，违反最小权限；改为 `DATABASE_URL: *db-api-url`（`aia_api`），不再持有属主凭据。② 只给 `worker` 任务**实际用到**的表补缺少的 **DML** 权限（SELECT/INSERT/UPDATE/DELETE，按需、能按列就按列），**不给任何 DDL**（CREATE/ALTER/DROP/TRUNCATE、属主、`SET ROLE` 到属主）；当前任务：冷却清理 `licences.purge_expired_cooldowns`（`app.user_data_licence_cooldowns`：SELECT、DELETE）、预览行每小时清理 `imports.purge_preview_rows`（`app.import_rows`：SELECT、DELETE；`app.import_batches`：SELECT）、原始文件到期清理 `imports.purge_expired_raw_files`（另须 worker 挂 imports 卷，见 review-028c077 M2）（`app.import_files`：SELECT，UPDATE `deleted_at`、`storage_path`，`FOR UPDATE` 所需权限）；T-B52 交付后的 `master.*` 同步与首次导入（`market` 下主数据、历史、词条、`master_runs`、`master_snapshots` 的 DML）。③ `aia_api` 仍不得读证书密文列（列级授权不变），新增授权不得放开它。④ 运维在 `deploy/db/roles/grants.sql` 补授权、`verify-roles.sh` 断言（worker 任务全部能跑；`aia_api` 无 DDL、读不到密文列），CI 规则 7 的 `DB_ROLE_OF` 把 `worker` 登记为 `aia_api`。⑤ 如有任务必须用属主或 `aia_maint` 才能跑，**不得自行放权**，报架构师裁定。⑥ `beat`（只调度，不应连库写数据）与 `signal-rt` 仍用属主，同样按本条原则另行收窄（运维核实各自实际用到的表后报架构师）。
     9. **`aia_ingest` 旧宽授权收窄（T-A30，T-O29 遗留 5 项）**：根因是 `$grants$` 对 `aia_api`、`aia_ingest` 的 `ALL TABLES IN SCHEMA` 表级 SIUD。不在本次全面收窄，沿用 `$purges$` 的做法：在 `$grants$` 之后加 `DO $ingest_narrow$`，每次部署都重新撤回（`ALL TABLES` 每次会重授），表不存在只 WARNING 跳过。逐项结论：
        - ① `market.master_runs` 上 `aia_ingest` 的表级 INSERT/UPDATE/DELETE → **收窄**为 `SELECT` + 列级 `UPDATE (stats)`（先 `REVOKE INSERT, UPDATE, DELETE, TRUNCATE`，再 `GRANT UPDATE (stats)`；`SELECT … FOR UPDATE` 有一列 UPDATE 即可）。ingest 只有 `daily_lists` 读、锁父行、改 `stats`；建行/改状态由 worker（`aia_api`）做。
        - ②③④ `app.action_plans`、`app.alert_rules`、`app.alerts` 上 `aia_ingest` 的 SIUD → **收窄**为无权限（`REVOKE ALL`）。计划条件作业 `plans.condition` 在 worker 服务里运行，用 `aia_api`（第 8 条）；ingest 没有代码读写这三张表。
        - ⑤ `aia_maint` 对上述 app 表的 `id/user_id` 列级 SELECT 与 DELETE → **保留，改测试预期**：这是第 6、7 条批准的删除用户数据 CLI 清单（`reports/aia_maint-grants.md` §3），不是宽授权。
        - **影响**：`aia_api`（api、worker、beat）与 `aia_maint` 有效权限不变；只有 `aia_ingest` 少了上述权限。不需要数据库迁移，只改 `grants.sql`、`verify-roles.sh`，重新跑 apply-roles（幂等）。部署顺序：先在隔离库跑 apply-roles 两遍，用 `has_table_privilege`/`has_column_privilege` 断言 ①–④ 的反例与 ingest 的 `SELECT`、`UPDATE (stats)` 正例，再跑 `daily_lists` 的定点用例（用 `aia_ingest` 连接）；生产随下一次 apply-roles 生效，无需停服。若将来 ingest 需要建 `master_runs` 行或读写计划表，由后端更新授权清单、架构师裁定后再加，不回退成表级。
  - **威胁模型与触发器自检（v0.2.9 内，T-T25 裁定）**：数据库属主、超级用户或能执行 DDL 的角色**不在**删除 CLI 的威胁模型内——这类角色本来就能直接读取或复制全部数据，CLI 无法防御，也不承诺防御（例如预先植入的 AFTER DELETE 触发器把行复制到别处）。作为防误配的完整性检查（不是安全保证）：CLI 在 dry-run 与 `--execute` 前，用只读查询（`pg_trigger` 中 `NOT tgisinternal` 的行）列出删除与匿名化清单内各表上的触发器，与 CLI 代码中维护的白名单（表名 + 触发器名 + 函数名，随迁移同步）比对；dry-run 输出差异，`--execute` 遇到白名单外的触发器拒绝执行并以非零码退出，不提供跳过参数。白名单由后端随迁移维护；不检查函数体内容，不检查清单外的表。
  - **物理删除**（个人财务数据和由它派生的数据）：持仓、成交（`app.trades`）、导入批次与解析行、证书（`app.user_data_licences`，含密文；T-A28 更正旧称）、画像（`app.user_profiles`）、自选、策略实例、候选信号（含各分区）、`signal_events`、`suggestions`、`suggestion_user_actions`、`plan_drafts`、`plan_draft_confirmations`、`risk_events`、风控设置及其历史、`claims` 与 `claim_links`、研究候选（`research_candidates`、`candidate_versions`；T-A11 同步，后端已删）、`symbol_horizon_assessments`、`daily_reports`、通知、会话。另外删除用该用户证书取到的 `market.*` 行（按 `source_licence_id`）以及对应的 Redis 键。
  - **匿名化保留**（有不可变要求的审计和日志表）：`app.audit_logs`、`app.account_reviews`、`ops.data_licence_events`、`ops.ingest_request_log`。
    - 断开关联：`user_id`、`actor_id`、`target_id` 中指向该用户的值置为 NULL，相关列由迁移改为可空。
    - 清空：用户名、显示名、申请说明、`user_agent`；IP 截断到 IPv4 /24、IPv6 /48。
    - `detail` 或 JSON 列删除以下键：`security_code`、`name`、金额与数量类、文件名或路径、证书掩码或后缀、`email`；以及下文「匿名化细则」中审计 `detail` 一条列出的键。
    - 保留：动作名、时间、结果码、行数，以及审计 `detail` 一条允许保留的字段。
    - 匿名化 UPDATE 由触发器校验：只允许上述列发生变化，并且只允许改成上述值。
  - **原始导入文件**：数据库事务提交后，再删除 `/srv/aia/imports/` 下该用户的文件。删除失败的，写入 `ops.pending_file_purges`（只含路径、尝试次数、最近错误，不含 user_id），下次运行 CLI 时先重试这些记录，并在 dry-run 中列出。
  - **执行方式**：默认 dry-run，按表列出行数，并标出删除或匿名化；加 `--execute` 后要求手动输入完整的 user-id 确认；全部在单个事务内完成；写一条 `admin.user_data_deleted` 审计，`detail` 只含各表行数。
  - **匿名化细则（架构师裁定，2026-11-02，契约 v0.2.8 补充）**：
    - **IP**：`app.audit_logs` 只有 `ip_hash`，没有明文 IP。`actor` 是被删除用户本人或为 NULL 的行，`ip_hash` 置 NULL；管理员操作行的 `ip_hash` 保留。有明文 IP 的表仍按上面的截断规则处理（IPv4 /24、IPv6 /48）。
    - **审计 `detail`（评审 45589c2 M2）**：匿名化时从 `detail` 中删除所有指向被删用户的键，包括 `user_id`、`target_user_id`、`username`、`licence_id`，以及用户自己填写的 `reason`、`note`、`comment` 一类自由文本；管理员填写的 `reason` 也清空（其中可能引用了用户的话）。只保留 `action`、时间、管理员本人的 `actor`、不含个人信息的枚举字段（状态、理由码）。
    - **ID 类键的清洗粒度（v0.2.9 内，评审 be607b3/f72b8c7/8fd9502 裁定），回应评审 8fd9502 m 级“审计过度清洗”；与上一条冲突时以此为准**：① 数组值或复数键（如 `user_ids`、`licence_ids`、`target_ids`、`affected_users`）只移除被删用户的 id 和该用户名下证书的 `licence_id`，其他用户的 id 保留；移除后为空数组的保留空数组；② 单值键（`user_id`、`target_user_id`、`licence_id`、`username` 等）的值是被删用户或其证书时删除该键，指向其他用户时保留；③ `reason`、`note`、`comment` 等自由文本字段仍整体删除（不做部分替换）。后端在删除用户数据 CLI 中实现，嵌套 JSON 递归处理，单元测试覆盖三类键。
    - **`app.account_reviews.reason`**：置 NULL（评审 45589c2 M1；取代上次“不可为空时写 `'[已清除]'`”的写法）。
    - **`data_snapshots`（评审 45589c2 B2；推翻上次“不按用户区分、删除时不处理”的写法）**：含持仓、成交、账户或由它们派生内容的快照，必须带 `user_id`，按需带 `licence_id`，删除用户时物理删除；只含市场级内容的快照可以保留，前提是不含任何个人内容。表结构见 3.3 `data_snapshots` 行。此条必须在快照写入方上线之前完成。
    - **Redis 会话（评审 45589c2 M3）**：先调用现有的 `SessionStore.revoke_user(uid)` 删除会话本体，再按键名删除会话索引和其他含该用户的键。
    - **`llm_calls`（评审 45589c2 M4）**：只要被该用户的任何行引用，就算与他相关；引用方包括 `suggestions`、`daily_reports`、`target_type`/`target_id` 关联、`llm_strategy_drafts`，以及以后新增的引用方，CLI 动态发现引用列，不写死清单。只被该用户引用的调用物理删除；同时被他人引用的调用保留元数据（模型、token、耗时、时间），`request_body`、`response_body` 置 NULL 或写 `'[已清除]'`；不被任何用户引用的市场级调用保留，写入方必须保证其中不含个人数据。
    - **`invite_codes`**：`bound_username` 置 NULL；`used_by` 一类指向该用户的列解除关联（置 NULL）。
    - **`ops.pending_file_purges`**：`path` 可以含 uid 目录名；重试删除文件成功后删除该行。
- **周期清理与保留期（v0.2.9 内，评审 be607b3/f72b8c7/8fd9502 裁定）；T-B46/T-B47 裁定同步**：
  - **证书冷却记录**（`DELETE /me/data-licence` 时保留的指纹与删除前的 `status`、`paused_until`，契约 §7.1 DELETE 行）：有 `paused_until` 的保留到 `paused_until`（不另加 24 小时上限，否则删除后重提可绕过较长的冷却）；`paused_until` 为 null（删除时没有处于冷却）的最多保留到删除后 24 小时（契约 v0.2.9 #28①）（v0.2.9 内，T-O11 评审裁定）。**到期边界（v0.2.9 内，T-T25 裁定）**：到期时刻 `expires_at` = `paused_until`（非 null 时）或删除时刻 + 24 小时（`paused_until` 为 null 时）；记录仅在 `now < expires_at` 时有效，`now = expires_at` 即已过期（半开区间，与“`paused_until` 未到期”= `now < paused_until` 同一口径）；时间一律用数据库服务器 UTC 时间比较，不用应用进程时钟。周期任务（每小时，由 `beat` 调度、`worker` 执行；`beat` 实现之前，由 compose 服务 `cooldown-purge`（`aia_api`、不挂主密钥）每小时调用一次，`beat` 落地后删除该服务；上线前必须有，在此之前只靠读取时视为不存在）物理删除过期记录；读取时过期记录一律视为不存在。删除用户时一并物理删除。
  - **周期评估**：`symbol_horizon_assessments` 每个（用户、证券、分类器版本）的最新一条保留，其余超过 180 天的物理删除，同时删除只被它们引用的 `purpose='horizon'` 快照（问题 75）。
  - **交割单原始文件**：按 `import_batches` 的 `retained_until`（上传时间 + 365 天，问题 21）每日删除到期文件；失败的写入 `ops.pending_file_purges`。
  - 三项都由后端实现为幂等的周期任务，结果只写行数审计。
    - **管理员账号**：被删除的账号是管理员，且被不可变列或 NOT NULL 列引用时，CLI 拒绝执行，由人工处理。
    - **迁移 0011**：已有匿名化数据时 `downgrade` 失败，这是有意为之。
    - **CLI 用法**：默认 dry-run；加 `--execute` 并手动输入完整的 user-id 确认后才执行。退出码：`0` 成功；`1` 拒绝执行或数据库错误；`2` 用法错误；`3` 已提交但有残留（例如文件删除失败已写入 `ops.pending_file_purges`）。
- **境内存储**：服务器与备份均在中国境内（同时满足麦蕊条款 5.7）；不向境外第三方服务传输个人信息（V1 不用 Sentry；以后如需错误追踪只考虑境内自托管；邮件服务选境内）。
- 不设隐私政策、用户协议等需同意的文书，也不做版本管理（T-A06）；只有固定免责提示 `disclaimer.md`。
- 未成年人：注册时声明已满 18 周岁。
- 网站运营：境内对外网站需 **ICP 备案**（用户域名**尚未备案**，第 9 节问题 4）；备案完成前只在本地/VPN 内测；如收费可能需 ICP 经营许可证；等保备案（建议二级）【待核实具体义务】。
- **LLM 数据**：发给 LLM 的只有证据摘要（证券代码、指标、规则结果），**不发送**用户名、账户、股东代码、成交编号、持仓数量与金额；持仓只以占总资产比例和成本价出现（与 2.7 一致）。更换 LLM 供应商时只发站内通知（`notification_kind=system`），不要求重新同意（T-A06，第 9 节问题 46）。发送前由网关做 PII 守卫（2.7.2）。**DeepSeek 条款要点（2026-11-01 核实，详见 2.7.1）**：我方是个人信息处理者，须在隐私政策中告知“委托深度求索处理（去标识化的）证据数据”并取得同意（纳入 `consents` 文案，由用户/法务定稿）；DeepSeek 声明境内收集的个人信息存储于中国境内、目前不出境；其隐私政策称输入输出可能在加密和去标识化后用于训练——API 是否适用及如何关闭【待核实，书面询问 api-service@deepseek.com】，API 请求数据的保留期限与是否提供 DPA【待核实】；在核实前我们按“发送内容可能被保留和用于训练”设计，因此只发结构化证据。LLM 生成文本在页面标注“AI 生成”（服务协议 3.7）。`llm_calls` 只存哈希与摘要，保留 90 天（已定，问题 16）。

### 7.4 数据安全
- 传输 TLS 1.2+；HSTS；Cookie Secure/HttpOnly/SameSite；CSRF；CSP。
- 存储：PostgreSQL 磁盘加密（云盘加密）；敏感列（成交、持仓、备注）应用层加密不在 MVP 做（已定，第 9 节问题 22：依赖磁盘加密 + 严格访问控制；股东代码 HMAC + 掩码，原始文件 AES-256-GCM）。
- 访问控制：所有 `app.*` 查询强制 `user_id` 过滤（仓储层统一封装 + 集成测试"越权访问"用例）；可选启用 PostgreSQL RLS 兜底。
- 密码：argon2id；注册/登录限速、渐进式锁定、蜜罐字段（无验证码，详见 3.6）；管理员账号仅由 CLI 创建，对其他人开放前管理员必须启用 TOTP 二次验证（已定，第 9 节问题 18）。
- 上传安全：仅文本类扩展名 + 内容嗅探（拒绝二进制）、大小上限、解析在 worker 中带超时与行数上限（≤ 50,000 行）、原始文件存私有存储且不可经 URL 直接访问、文件名不参与路径拼接。
- 秘密管理：用户证书以 HPKE 密文存库，解密私钥只在 `ingest` 容器（2.1B）；日志脱敏；仓库密钥与敏感信息扫描见 7.4A。
- 备份：每日全量 + WAL，保留 30 天，季度演练恢复。
- 审计：登录、导出、删除、计划/成交变更、导入确认/撤销、全部管理员操作写 `audit_logs`。
- 依赖安全：Dependabot + `pip-audit`/`pnpm audit` 进 CI。

### 7.4A 仓库密钥与敏感信息扫描（CI 规格，T-A01；实现任务 T-O02a）
**目标**：仓库中不出现任何真实密钥、真实账户标识或真实交割单；虚构夹具可以通过，但每个夹具文件都要逐个登记、按内容哈希固定。

**工具与时机**
- 扫描器：gitleaks（MIT）加本仓库自定义规则 `.gitleaks.toml`，另加一个夹具一致性脚本 `scripts/ci/check_fixtures.py`（由 T-O02a 实现）。同一份配置也用作本地 pre-commit 钩子。
- 每个 PR：扫描**本 PR 的全部提交**（`git log -p base..head`，不只看最终 diff，防止"先提交、再删除"）。`main` 分支每天全量扫描一次（含历史）。**【已定 2026-11-01】不依赖 GitHub 自带 secret scanning / push protection，只用 gitleaks**（CI + 本地 pre-commit，问题 35）。
- 任何命中都**阻断合并**。日志只输出 `路径:行号:规则号` 和掩码后的值（保留前 2 个字符，其余用 `*`），不在 CI 日志中打出完整命中值。

**规则（S1–S9）**

| # | 检测对象 | 规则（正则为 RE2 / Python 语法） | 级别 | 夹具豁免 |
|---|---|---|---|---|
| S1 | 麦蕊 licence | ① URL 末段：`(?i)mairuiapi\.com/\S+/[A-Za-z0-9-]{16,}`；② 赋值：`(?i)(mairui[_-]?)?licen[cs]e\s*[:=]\s*["']?[A-Za-z0-9-]{16,}`。licence 的实际长度与字符集【待核实】，T-B05 拿到真实 licence 后收紧长度并在本地钩子中增加"真实值精确匹配"（值只从本机环境变量读取，不入库） | 阻断 | 不豁免 |
| S2 | LLM / 第三方 API key | ① `\bsk-[A-Za-z0-9_-]{20,}\b`（OpenAI 风格的常见写法，只作扫描启发式；**DeepSeek 官方文档未公布 key 格式**（2.7.1），所以运行时配置只校验非空，不用此正则）；③ 本地 pre-commit 与手动检查：若本机设置了 `DEEPSEEK_API_KEY`，用不打印的精确比对 `git grep -qF -- "$DEEPSEEK_API_KEY"` 检查真实值未入库（值只从环境变量读取，命中只输出 FOUND）；② 通用赋值：`(?i)\b(api[_-]?key\|secret\|token\|passwd\|password)\b\s*[:=]\s*["'][^"'\s]{12,}["']` | 阻断 | 不豁免 |
| S3 | 私钥 | `-----BEGIN [A-Z ]*PRIVATE KEY-----` | 阻断 | 不豁免 |
| S4 | 环境变量文件 | 除 `.env.example` 外，任何 `.env*` 文件都不得入库；`.env.example` 中 `APP_MASTER_KEY`、`MAIRUI_LICENCE`、`DATA_LICENCE_SEAL_PRIVATE_KEYS`、`*_PASSWORD`、`*_API_KEY`、`DATABASE_URL` 的值只能为空或占位符（`changeme`、`<...>`、`example`） | 阻断 | 不豁免 |
| S5 | 沪市股东代码 | `\b[A-Z]\d{9}\b` | 阻断 | 见下方豁免 |
| S6 | 深市股东代码 | `\b0\d{9}\b`，且同一行或同一文件表头含"股东"（避免与时间戳、金额误报） | 阻断 | 见下方豁免 |
| S7 | 疑似真实交割单 | 文件中同时出现以下表头中的 ≥ 3 个：`成交日期`、`证券代码`、`股东代码`、`成交编号`、`委托编号`、`发生金额`、`剩余金额`；或文件是 GBK/GB18030 编码的文本 | 阻断 | 见下方豁免；`docs/*.md` 不适用 S7（见下方“docs 例外”） |
| S8 | 身份证号、手机号 | 身份证：`\b\d{17}[\dXx]\b` 且校验位正确；手机号：`\b1[3-9]\d{9}\b` | 身份证阻断；手机号警告 | 不豁免 |
| S9 | 银行卡号、资金账号 | 银行卡：`\b\d{16,19}\b` 且通过 Luhn 校验 → 警告；资金账号：`(资金账号\|资金帐号\|客户号)\s*[:：]?\s*\d{6,}` → 阻断 | 见左 | 不豁免 |

**允许清单 `.secretscan-allow.yaml`**（每条必须写 `rule`、`path` 或 `value_regex`、`reason`、`added_by`、`added_at`；`value_regex` 只能写虚构值）
- 全局固定允许：证券代码示例 `600000`、`000001`（6 位，不触发 S5/S6）；虚构沪市股东代码 `A00000000[0-9]`（`A` 加 8 个 0 再加 1 位数字，只在文档与测试中使用）；掩码写法 `A1****789` 一类（含 `*` 不触发）；占位符 `<licence>`、`{licence}`、`sk-xxxxxxxx…`（全是 `x`）；文档网段 `203.0.113.0/24`。
- 新增允许项需要架构师或测试负责人审核（CODEOWNERS 覆盖该文件）。

**夹具豁免（只针对 S5、S6、S7，严格模式）**
- 适用路径：`tests/fixtures/broker_statements/**`。其他路径中出现 S5–S7 一律阻断，唯一例外见下条。
- **docs 例外（2026-11-01 定，只针对 S7）**：S7 会命中文档里的列名和规则正文（例如本节的 S7 规则行、3.5A 的交割单列映射），并非真实交割单。因此 `docs/*.md`（只限 `docs/` 目录下直接的 `.md` 文件，不含子目录）**只豁免 S7**；S1–S6、S8、S9 照常对 `docs/*.md` 生效并阻断，所以文档中真实的股东代码、证件号、资金账号等仍会被拦下。文档示例值只能用 7.4A 允许清单中的虚构值。子目录（如 `docs/strategies/`）如需同样豁免，另行审核后再加。
- 条件全部满足才豁免，任何一条不满足都按普通文件扫描：
  1. 同目录有 `meta.json`，其 `"marker"` 为 `"# SYNTHETIC"`，`"synthetic": true`；
  2. 目录中每个 `.txt` 都在 `meta.json.files[]` 中按 `file` 登记，且**登记的 sha256 与文件实际内容一致**（改动任何字节都要同步更新 sha256，否则失败）；没登记的文件不豁免；
  3. `origin=generate.py` 的文件：CI 在临时目录重新运行 `generate.py`，生成结果必须与仓库中文件**逐字节相同**（证明完全由脚本生成）；
  4. `origin=desensitized_main` 的文件（人工脱敏的主样本）：`.secretscan-allow.yaml` 中要有对应条目，写明 `path`、`sha256`、审核人和日期；哈希不一致即失败，需重新人工审核后更新；
  5. 豁免文件中的 S5/S6 命中值必须**全部**属于 `meta.json.fake_identifiers` 列出的虚构值；出现列表外的值仍然阻断。`fake_identifiers` 是 `meta.json` 新增的顶层键（目前没有），由测试在 T-T09 中补上，同时由 `generate.py` 输出，CI 规则上线前必须补齐。
- `expected.json` 和 `README.md` 不在豁免范围内（它们不应包含股东代码等标识）。
- **T-A21 存量命中裁定（架构师 2026-11-07）**：去掉全部豁免后共 80 处，都是已登记的 4 个虚构字面量（fixtures 73、扫描配置自引用 6、本文示例 1），无需清理，保留现有允许清单。`expected.json`、`README.md` 中的虚构值只靠 `value_regex` 精确值放行，不做路径豁免；出现登记外的值照常阻断。白名单规则（运维、测试执行）：
  1. `value_regex` 只能写 `^虚构字面量$`，一条对应一条规则和一个值；禁止通配、整目录豁免、`rule: '*'`。
  2. 按路径豁免必须同时写精确文件 `path`、`rule`、`sha256`、`reviewer`、`reason`、`added_by`、`added_at`；文件一改哈希就失效，要重新审核。
  3. gitleaks 误报只用 `.gitleaksignore` 指纹（`提交sha:文件:规则ID:行号`）登记，不改规则、不加 `[allowlist] paths`。T-F28 tree 报告中 1 处 generic-api-key（疑似 `feature_key` 行）由运维用 `gitleaks_run.sh` 复跑定位后按指纹登记。
  4. 前端：`src/frontend/src/test/wording.test.ts` 只对禁用词检查豁免；`src/frontend/src/mocks/marketFixtures.ts:64` 的假成交额改成带小数的金额消除命中（前端），不登记。
  5. 新增白名单条目须由架构师或测试负责人评审（CODEOWNERS）；登记前在本机用 `check_real_secrets.sh` 与真实值精确比对为 0 才能登记，不输出取值。
- **T-A23 推送前历史命中裁定（架构师 2026-11-07）**：不改写历史、不 force-push，三处都按 `.gitleaksignore` 指纹登记放行，一处一行，注释写明确认方式，不加路径或规则豁免。
  1. `e31ed6c` 第 150、202 行 generic-api-key：在 `src/backend/selfchecks/test_ta13_feature_metadata.py` 中，这两行都是 `feature_key == "f.xxx"` 的特征键字面量，和 4f3ce14 是同一类误报。运维登记前先核对 gitleaks 报告里的文件名就是这个文件：如果是同一提交里其他文件的同行号（如 `persistence.py`），先报架构师复核，不登记。
  2. `3b2c8ec:tests/backend/milestone/tt21_mainline.json:generic-api-key:7`：值是 `src/backend/migrations/versions/0004_t_b03_auth.py` 在该提交时文件内容的 SHA256，架构师已重算一致，不是凭据，放行。今后这类迁移摘要清单由测试在文件头注明“sha256 of migration file”，并由自检重算；新增命中仍按指纹逐条登记。

**测试**：`tests/ci/secret_scan/` 下放正反例（全部虚构，且正例文件本身用 `.secretscan-allow.yaml` 按 sha256 登记），保证每条规则至少有一个命中用例和一个不误报用例；规则变更必须同时更新用例。

### 7.5 其他技术风险
| 风险 | 影响 | 缓解 |
|---|---|---|
| 麦蕊 2-IP 限制（同一证书 60 秒内最多 2 个来源公网 IP，**硬约束**） | 多机、多环境或开发机与生产同时调用 → IP 超限，全站行情中断 | 唯一的行情采集服务 `ingest`（单副本 + 单活锁 + 固定出口 IP 自检 + licence 只在该容器中，2.1A）；本地和 CI 用回放模式；故障切换只做冷备（停旧实例并等待 ≥ 60 秒）；IP 超限立即告警并暂停外呼；开发真实联调与生产互斥，或申请第二张证书（问题 27） |
| 证书归属、代运营与共享缓存未获麦蕊书面确认（T-A07） | 被认定违约 → 证书被停用 | 默认 `per_licence`、不跨证书共享；朋友以本人账号申请证书；书面询问麦蕊（第 9 节问题 50） |
| 某位用户的证书失效、到期或超额（T-A07） | 该用户行情中断 | 按证书降级与通知、到期前 30/7/1 天提醒；**不回退**到他人或管理员证书（2.1B 第 6 点） |
| 多证书共用一个出口的串行时延（T-A07） | 用户多时刷新变慢 | 默认“全市场快照 60 秒 + 重点关注 15 秒”；`global_max_concurrency` 待 T-B05 实测后调整（2.1B 第 5 点） |
| 单点：`ingest` 故障导致全站行情停滞 | 盘中建议暂停（stale） | 容器自动重启（重启间隔 ≥ 60 秒，并检查锁）；新鲜度监控和告警；冷备手册；P0 队列优先，确保实时数据先恢复 |
| 历史因子是否"按时点"未核实 | 内部评估有前视偏差 | 待 T003 验证；先用我们自己按时点落库的数据（2.12.1） |
| TimescaleDB 扩展升级与许可证 | 升级受阻 | 固定镜像版本；升级前在演练环境测试 `pg_upgrade`；社区版只自用，不对外提供数据库服务 |
| 存储增长超出预期 | 磁盘满，写入失败 | 3A.2 的估算 + 磁盘使用率达 70% 时告警 + 保留策略 + 冷分区转存 |
| 麦蕊接口变更/下线（更新日志显示接口曾"恢复开放""口径变更"） | 功能失效 | 网关层适配 + 字段校验 + 告警；关键数据双源预案 |
| 数据质量（空字段、北向因子为空） | 错误结论 | 入库校验、`gaps` 显式展示、不对空值做推断 |
| 证书到期 2027-09-11 | 降为每日 2 万次 / Pro 停用 | 到期前 60 天提醒运维；降级模式 |
| 公告盘后更新 | 提醒滞后 | 文案明示；评估巨潮授权 |
| Quant Pro / 钻石版到期（2027-09-11，用户已确认） | 无 1 分钟 K、每日 2 万次 → 实时链路无法维持 | 到期前 60 天提醒；`realtime.yaml` 预置降级档（只刷持仓、60 秒快照、关闭 Tier-2） |
| 配额规则与文档不一致（6000/分钟按接口还是按证书、`/hsrl/ssjy/all` 每分钟次数、并发是否限制） | 429 或刷新变慢 | T003 已实测触发 2 IP 限制，其余仍待补测（4.0；T-B05）；令牌桶预算可热调；429 自适应退避并告警 |
| LLM 供应商故障/超预算/余额不足 | 无解释文本 | 按 2.7.2 重试与熔断；401/402 立即告警管理员；模板兜底；**建议本身不受影响**（LLM 不决定动作） |
| 规则引擎错误导致错误建议 | 用户误判 | golden/回放测试、策略版本不可变、灰度发布新版本、一键停用策略 |

### 7.6 开源许可证（采纳 T002 调研 §0、§4）
- **禁止拷贝代码**：以下项目只能借鉴思路，代码一行都不能拷贝：
  - OSkhQuant：CC BY-NC，禁止商用；
  - QuantMind：AGPL，网络服务也须开源；
  - bondTrader、AlphaGPT_Tushare：没有许可证，默认保留全部权利。
- **可借鉴并在必要时少量引用（须保留署名）**：TSP、KHunter、a-share-quant-selector、CTBZStock、QMT-QuantLimit，这些项目为 MIT 或 Apache-2.0【以各仓库当前 LICENSE 为准】。引用时在仓库根目录 `THIRD_PARTY_NOTICES.md` 中登记项目、许可证、引用文件和修改说明。
- **前端依赖**：TradingView Lightweight Charts（Apache-2.0，需要展示署名）、AG Grid Community（MIT）、ECharts（Apache-2.0）。
- **CI 检查**：`pip-licenses` 和 `license-checker` 检查依赖许可证，发现 GPL、AGPL 或 NC 类许可证即阻断。
- **L1 卡片来源**：卡片的 `sources[].license_status` 为 `idea_only` 时，审核页会提示"只能借鉴思路"。

---

## 8. 分阶段任务拆分（验收项 8）

> 角色：**后端 / 前端 / 测试 / 运维**。"依赖"列为必须先完成的任务。**主线（0A：盘后分析 + 盘中建议）在 Phase 2 最先交付**，其他能力放到 Phase 3。质量优先，不压工期，每阶段都要过 8.0 的质量门禁。阶段工期是估算，不是承诺。

### 8.0 测试策略与质量门禁（质量优先，不赶工期）
**测试分层**
| 层 | 工具 | 重点 | 门槛 |
|---|---|---|---|
| 单元 | pytest、hypothesis（属性测试）、vitest | 规则引擎、动作映射、置信度公式、持仓重建、费用勾稽、定宽解析、配额/间隔推导函数、LLM 输出校验器 | 领域包（`domain/`、`importing/`、`signals/`、`advice/`、`llm/`）行覆盖 ≥ 90%，整体 ≥ 80% |
| 黄金样例（golden） | pytest + 固定快照 JSON | 给定"策略版本 + 数据快照 + 画像 + 持仓"→ 期望的动作/分数/置信度/理由/反证/失效条件，逐字段比较；规则改动必须更新黄金文件并在 PR 中解释 | 100% 通过；黄金文件变更需评审 |
| 回放（replay） | 录制的麦蕊响应（脱敏 fixtures）+ 时钟模拟 | 盘中一整天的行情回放：刷新循环、陈旧判定、翻转去抖、幂等 tick、通知合并、429/503 退避与预算 | 回放测试全过；无重复建议 |
| 集成 | pytest + docker（Postgres/Redis 测试容器） | 迁移、不可变触发器、as-of 查询、越权隔离、导入事务、SSE | 全过 |
| 契约 | schemathesis（对 OpenAPI）+ 契约文档对照脚本 | 字段、类型、错误码与 `api-contract.md` 一致。例外（v0.2.9 内，T-T25 裁定）：只允许 schema 无法表达的业务校验，每条写明 方法 + 路径 + 状态码 + 错误码 + `field`，不得按整个接口或整类状态码放行；登记表 `tests/backend/contract/r11_exceptions.py` 归**测试员**维护，是唯一清单；CI 读取的 `src/backend/schemathesis.toml` 位置不变、归**后端**维护，其中每条例外必须能在登记表中找到（测试员加一致性用例只读校验）；R11 #9（`POST /trades`，格式合法但推断不出市场 → `400 VALIDATION_ERROR`，`field: security_code`）与 #10（`PUT /imports/{batch_id}/options`，解析器与批次 kind 不符 → `400 VALIDATION_ERROR`，`field: parser_id`）按此登记；`qty`、`price`、`encoding_override` 的格式错误不得列为例外，由后端收紧 schema 解决 | 全过 |
| E2E | Playwright（桌面 1440×900，深色主题） | 注册→审核→登录→导入→启用策略→收到盘后日报→盘中信号翻转→建议卡→转计划→模拟跟踪结果 | 主流程全过 |
| 安全 | 越权用例、CSRF、限速、ZAP 基线扫描、`pip-audit`/`pnpm audit`、gitleaks 密钥扫描（S1–S9）、敏感样式扫描 | 无高危 | 0 高危 |
| 性能 | locust | 100 并发用户读接口 p95 < 300 ms；一轮实时刷新（4,000 只）端到端 < 刷新间隔 | 达标 |

**质量门禁（CI 必过，PR 才能合并）**：ruff + mypy --strict（后端）、eslint + tsc --noEmit（前端）、上述单元/黄金/集成/契约测试、覆盖率阈值、禁用词扫描（前端文案、后端模板、prompt 模板）、敏感数据样式扫描（股东代码样式、licence 样式、真实范本文件名）、Alembic 迁移可升可降、Docker 镜像构建；**main 分支保护 + 至少 1 名评审**。CI 永不访问真实麦蕊与真实 LLM（全部 fixtures/mock）；真实接口的冒烟测试单独手动触发。

**测试代码归属（v0.2.9 内，架构师裁定）**：与组件放在一起的前端测试（`src/frontend/src` 下的 `*.test.ts(x)`）归**前端**编写与维护；仓库根目录 `tests/` 下的测试归**测试角色**。

**发布门禁（每个里程碑）**：测试角色签字的验收清单、回放一整天行情无异常、备份恢复演练、合规文案人工复核。

### Phase 0：本地优先的基础设施与骨架（约 1–1.5 周）
| ID | 任务 | 角色 | 依赖 |
|---|---|---|---|
| T-O01 | 仓库骨架：按第 6 节建目录、`.editorconfig`、`.gitignore`、`deploy/env/.env.example`；`docker-compose.yml`（nginx/api/worker/ingest(replicas 1)/signal-rt/beat/postgres+timescaledb/redis）+ `docker-compose.dev.yml`（热重载、MSW、麦蕊回放模式）；**本地一条命令启动** | 运维 | — |
| T-O02 | CI：后端 ruff/mypy(strict)/pytest + 覆盖率、前端 eslint/tsc/vitest、契约测试、镜像构建、`pip-audit`/`pnpm audit`、依赖许可检查（禁止 `ag-grid-enterprise`）；8.0 门禁接入；密钥与敏感信息扫描见 T-O02a | 运维 | T-O01 |
| T-B01 | 后端骨架：FastAPI、pydantic-settings（全部配置走环境变量 + `config/*.yaml`）、统一错误格式与错误码、request_id、游标分页、`/health`、`/meta/enums` | 后端 | T-O01 |
| T-B02 | 数据库基线迁移：第 3 节全部表（含不可变触发器、`market` schema、分区） | 后端 | T-B01 |
| T-F01 | 前端骨架：Vite + React 19 + TS + antd 6（已定，问题 34）、antd 暗色+compact、`DataGrid` 封装（AG Grid **Community**，禁止 Enterprise）、Lightweight Charts、react-resizable-panels（固定三栏 + 底部面板，只调宽/折叠，localStorage 持久化 + 恢复默认）；路由、风险揭示组件、桌面最低分辨率检测；按 `api-contract.md` v0.2 的 MSW mock（字段以契约为准，原型按契约变更记录改名）；选型结论见 2.10 | 前端 | T-O01 |
| T-T01 | 测试框架：pytest（测试库容器）、vitest、Playwright（1440×900 深色）、schemathesis 契约测试、golden/replay 目录结构 | 测试 | T-O01 |

### Phase 1：身份、数据层、导入（约 2 周）
| ID | 任务 | 角色 | 依赖 |
|---|---|---|---|
| T-B03 | 认证：注册（pending）/登录（未批准拒绝且不建会话）/登出/会话/CSRF/改密；`/me`、画像（版本化，选填）。T-A06：删 consents 与风险测评 | 后端 | T-B02 |
| T-B03a | 防滥用：限速、渐进锁定、蜜罐、pending 上限、`login_attempts`；Nginx `limit_req` | 后端 | T-B03 |
| T-B03b | 管理员：`create-admin` CLI、用户审核/禁用/重置、`account_reviews`、`audit_logs`、禁用即吊销会话 | 后端 | T-B03 |
| T-B03c | 邀请码：`invite_codes` 表、`/admin/invites`、注册核验（同事务、统一错误）、审计；`invite` 模式启用前必须完成（T-A05） | 后端 | T-B03b |
| T-B04 | ~~麦蕊网关 `datagw`~~ **由 T-B04a（`ingest` 服务）取代**，以下功能全部移入 `ingest`：URL 构造、Redis Lua 令牌桶（`per_minute_budget` 可配置）、并发上限（`max_concurrency`）、singleflight、错误码映射（101/102/103/403/429/503）与自适应退避、licence 脱敏、`raw_payloads`、日计数器与降级开关、**录制/回放模式**（本地与 CI 不访问真实麦蕊） | 后端 | T-B02 |
| T-B05 | **麦蕊实测联调（真实证书，仅一台机器）**：逐一调用 0A.6 与 4.2 的接口，确认字段、空值、延迟、`/hsrl/ssjy/all` 每分钟次数、并发规则、6000/分钟是按接口还是按证书、因子数量（77/85）、`dividend_yield` 可用性、资金流盘中更新频率、板块实时；产出 `docs/mairui-verified.md` 与脱敏 fixtures；回填本文全部【待核实】与【待 T003 验证】；**与 T003 报告 `/workspace/team/reports/T003-mairui-capability.md` 对账**，只在当前唯一调用方上执行。**财务时点自算实测项（v0.2.9 内，T-R12 并入；对应 `feature_spec.md` §11 V5b–V5f、V9）**：① cashflow：抽 ≥ 5 家（含至少 1 家银行、1 家保险），多个年份与季度，统计 `jyhdcsdxjlxj`、`jyhdcsdxjlje` 各自非空率（`'-'` 计为空），核对 `jyhdcsdxjlxj` = `jyhdxjlrxj` − `jyhdxjlcxj`、两字段同时有值时是否相等、是否为年初至报告期末累计口径；② 银行（000001、600000）与一家保险的 balance：`gsmgdqsyhj`、`fzhj`、`zczj` 是否有值、单位，以及归母权益 ≤ 0 的情形（供 PB 判定）；③ 多版本行：探针保存同一 `jzrq` 多个 `plrq` 版本的完整数值，并选一家发布过差错更正的公司对照巨潮，确认更正版本如何成行、`plrq` 是否为更正公告日；④ capital：`plrq` = `bdrq` 的含义，用 600519 2011-07-01 送股对照巨潮；⑤ `sw_l1` 代码格式（`/hszg/list`），“银行”“保险”在返回中的代码，是否有申万二级；没有申万二级时提供保险证券名单及来源；⑥ PB 分量：`c`（不复权）× `zgb` 与巨潮/交易所披露的总股本、总市值抽样核对；⑦（T-R12a）`zgb` 是否含 B 股、H 股：各取一家 A+H、A+B 公司对照巨潮，并确认 capital 中区分 A/B/H 股本的字段名；⑧（T-R12a）麦蕊是否有分红送转数据（送转比例、除权日），以及 capital 送转行的 `plrq` 相对除权日的先后（与 V5d 一起做）；⑨（T-R12a）财报响应中有无币种、单位字段，抽一家 CDR 或境外上市背景公司检查。结果写入 `docs/mairui-verified.md`，并标出 2.12.1 的现金流主备字段是否需调整 | 后端 | T-B04a |
| T-B05a | **日线数据质量检查**（T003 发现的伪停牌占位行）：`sf=1` 且同日快照有成交 → 标 `suspect`，排除出指标、信号与跟踪计算，生成管理端告警；补测结果写入 T-B05 产出 | 后端 | T-B05 |
| T-B06 | 行情层（按证书隔离；证券公开主数据全站一份；契约 v0.2.8 起含 ETF）：主数据、日历、指数、日 K、全市场快照、板块与成分、涨跌停池、`marketdata` 查询 + `gaps`；`/securities/search`（pg_trgm + 拼音首字母）、`/securities/{code}`、周 K 聚合（契约 v0.2.7；公开主数据范围与来源见第 9 节问题 51–52） | 后端 | T-B05 |
| T-B07 | 盘后数据批：因子截面（2.5 所需因子）、资金流、龙虎榜、公告/问董秘/jrts/解禁/业绩预告、财务；`/securities/{code}/financials` `/fund-flows` `/factors` `/announcements`、`/market/sector-flows`（契约 v0.2.7） | 后端 | T-B06 |
| T-B08 | 账户、期初持仓、手动成交（只追加+冲正）、`account_events`、持仓由成交重建、`/portfolio/summary` | 后端 | T-B06 |
| T-B18 | 导入框架（编码识别、解析器注册表、列映射、预览/确认/撤销、去重、错误行报告、原始文件加密存仓库外） | 后端 | T-B08 |
| T-B19 | 格式 A 解析器 + 持仓快照 + 对账引擎；敏感字段 HMAC+掩码 | 后端 | T-B18 |
| T-B19b | 其他券商解析器（待范本） | 后端 | T-B18、用户范本 |
| T-B09 | 证据 `claims` + 快照服务（as-of） | 后端 | T-B07 |
| T-O05 | 导入文件与 LLM 密钥的存储：仓库外加密卷、主密钥注入、保留期清理、备份排除 | 运维 | T-O01 |
| T-F02 | 注册/登录/审核状态页、画像（T-A06：删同意与风险测评、`/onboarding`） | 前端 | T-F01→T-B03 |
| T-F02a | 管理员用户审核后台 | 前端 | T-B03b |
| T-F03 | 个股档案（深色 K 线、分时、财务、资金、因子、公告外链）与市场概览；按契约 v0.2.7 调整 mock 类型（T-A08 分歧表 1–16） | 前端 | T-B06/T-B07 |
| T-F04 | 账户/持仓/成交、导入向导（预览着色、映射、撤销）、对账结果 | 前端 | T-B08/T-B18/T-B19 |
| T-T02 | 网关测试：限流、退避、错误映射、licence 不入日志、回放 | 测试 | T-B04/T-B05 |
| T-T03 | 认证与越权测试（A 不能访问 B；非 admin（含未登录）访问 `/admin/*` 一律 404（契约 v0.2.1）；锁定；禁用即失效） | 测试 | T-B03* |
| T-T09 | 导入测试（**仅合成样本**，GBK/UTF-8/BOM、定宽 CJK 宽度、幂等、撤销、对账属性测试） | 测试 | T-B18/T-B19 |

**里程碑 M1**：本地一条命令启动；能登录、导入（合成样本）并看到由成交重建的持仓；行情与因子来自本人证书的缓存。

### Phase 2：主线优先——策略库、盘后分析、盘中建议（约 4–5 周）
| ID | 任务 | 角色 | 依赖 |
|---|---|---|---|
| T-B20 | **策略库**：`dimension_definitions`、`strategies`/`strategy_versions`（不可变）、规则表达式解析与安全求值器（白名单字段与运算符）、内置模板经导入器从 `docs/strategies/` 接入（2.5.14）、复制与参数覆盖、`/strategies*`、反查"某股适用哪些策略"、`/factor/screen` 筛选；`/strategies` 的 `risk_level` 与筛选（契约 v0.2.7） | 后端 | T-B07, T-B09 |
| T-B30 | **周期与策略自动分类**：`horizon_classifier_versions`、特征提取（含用户历史持有天数/做T记录）、`symbol_horizon_assessments`（理由+证据）、导入确认/加自选/每周触发、生成 `proposed` 的 `strategy_instances`（确认在 T-B32）。T-B47 已交付 GET 与计算；落库（`on_demand`）与真实输入依赖 T-B30a，T-B30 以 T-B30a 完成为验收前提（v0.2.9 内裁定） | 后端 | T-B20, T-B19, T-B30a |
| T-B21 | **建议引擎**：2.5.4 流水线（数据装配→维度评估→策略结论→风控门控→分歧分析→优先级→解释→不可变存档）、`engine_policies`、置信度公式、**不合并的维度×策略矩阵与 divergence**、`suggestions`/`suggestion_threads`（不可变、建议链）、`/suggestions*` | 后端 | T-B20, T-B09 |
| T-B31 | **六项风控** RC1–RC6：止损止盈计算（含涨跌停价约束）、单只仓位、总仓位 vs 大盘环境（regime 计算）、板块集中度、连续亏损与回撤、违反计划（导入后即时检查）；`risk_control_settings`（系统默认+用户开关）、`risk_events`、`/risk-controls*` | 后端 | T-B21, T-B08 |
| T-B22 | **盘中实时链路**：universe 与刷新计划（生成 P0 拉取计划交给 `ingest`）+ `signal-rt` 计算进程、`intraday_universe`（去重、Tier-1/2/3、硬上限 4,000）、`ssjy_more` 批量轮询、`/hsrl/ssjy/all` 每分钟、Pro 1 分钟 K（Tier-1 每分钟 lt=2、Tier-2 每 5 分钟 lt=5）、自适应间隔与退避、stale 判定、`config/realtime.yaml` + `realtime_settings` | 后端 | T-B05, T-B06 |
| T-B23 | 信号与翻转：证书内共享的 `signal_states`、用户 `user_signal_states`（失效条件/计划条件）、`signal_events`、翻转→新建议（盘中）、通知节奏合并 | 后端 | T-B22, T-B21 |
| T-B24 | **盘后流水线与日报**：0A.5 时间表、`pipeline_runs`（可重跑、幂等）、`daily_reports`/`daily_report_items`（不可变、revision）、数据缺口汇总 | 后端 | T-B21, T-B07 |
| T-B25 | **LLM 网关 + 管理后台接口**：供应商适配器（OpenAI 兼容 / 其他；先实现 DeepSeek，按 2.7.1/2.7.2 与 `config/llm.yaml`，key 只从 `DEEPSEEK_API_KEY` 读取并只校验非空）、AES-256-GCM 密钥（仅 `api_key_source=db` 的供应商）、任务路由、超时/重试/熔断（按官方错误码）、发送前 PII 守卫、预算、提示词模板版本、证据引用与数字校验、模板兜底、`llm_calls` 与用量统计、`/admin/llm/*` | 后端 | T-B01, T-O05 |
| T-B26 | 通知：`notifications`、SSE `/stream`（心跳、`Last-Event-ID` 续传）、轮询兜底、渠道适配器接口（站内 + 邮件）、偏好/免打扰/频控、投递日志与重试 | 后端 | T-B23, T-B24 |
| T-B27 | **模拟跟踪与自动降权**：`suggestion_tracking` T+1/5/20 vs 基准、`strategy_tracking_stats`（本人/全站匿名）、`user_strategy_weights`（2.5.7 公式，开关；与健康度合并见 T-B27a）、`/tracking*` | 后端 | T-B21, T-B06 |
| T-B28 | 会员权益预留：`plans`/`plan_entitlements`/`user_subscriptions`/`entitlement_overrides`、`EntitlementService`、所有上限改走权益、`/admin/plans*` | 后端 | T-B03 |
| T-B15 | 合规模块：措辞方案（"规则信号"）、禁用词校验、固定免责提示（`disclaimer.md`）、审计。T-A06：风险测评、同意门槛、文书版本、发布脚本全部作废 | 后端 | T-B03 |
| T-F11 | **交易终端主界面** `/terminal`：固定三栏 + 底部面板（分隔条可调宽）、一次请求 `GET /terminal`（ETag，SSE 断开时才轮询）、AG Grid Community 自选/持仓（实时价、各策略动作徽标、分歧徽标、stale 灰显）、K 线+分时+信号标记、SSE 接入 | 前端 | T-F01→T-B22/T-B26 |
| T-F12 | **建议卡**：维度×策略矩阵、并列动作、止损止盈、理由/反证/证据（时间、来源、类型）、失效条件、风控标记、置信度、策略版本、LLM 解释引用跳转、历史建议链 | 前端 | T-B21/T-B31 |
| T-F13 | 盘后日报页（账户概览、逐股卡片、缺口） | 前端 | T-B24 |
| T-F14 | 通知中心（未读、SSE、偏好、免打扰、渠道绑定） | 前端 | T-B26 |
| T-F16 | **策略库页**：策略列表（按周期/维度筛选）、规则清单与数据来源、版本差异、复制改参、胜率与盈亏统计、降权状态与开关；**周期分类结果与覆盖**；风控开关页 | 前端 | T-B20/T-B30/T-B27/T-B31 |
| T-F15 | 管理后台：LLM 供应商/模型/路由/提示词/用量、实时参数、套餐与订阅 | 前端 | T-B25/T-B22/T-B28 |
| T-T10 | **golden 测试**：每个内置策略 × 典型快照（满足/不满足/缺数据/分歧）→ 期望动作、维度观点、止损、风控标记，逐字段比对 | 测试 | T-B20/T-B21/T-B31 |
| T-T11 | **回放测试**：录制的一整个交易日行情回放 → 信号翻转、stale、退避、建议链与通知节奏符合预期；预算计数不超 | 测试 | T-B22/T-B23 |
| T-T12 | LLM 守卫测试：解释中的数字与证据一致、引用存在、禁用词、超时/失败回落模板、LLM 无法改变动作 | 测试 | T-B25 |
| T-T13 | 不可变性测试：建议、策略版本、日报、提示词模板、分类器版本的 UPDATE/DELETE 被拒 | 测试 | T-B21/T-B24 |
| T-T14 | 跟踪与降权测试：收益/超额/方向正确规则、平滑胜率与权重公式边界（n<20、clamp）、开关关闭时权重恒 1 | 测试 | T-B27 |
| T-T15 | 配额预算测试：模拟 4,000 只 universe 下每分钟调用 ≤ `per_minute_budget`、并发 ≤ 上限 | 测试 | T-B22 |
| T-T04 | 契约测试：主线接口对照 `api-contract.md` | 测试 | 上述后端任务 |
| T-T06a | E2E 主线：注册→批准→登录→导入（合成样本）→周期分类→启用策略→收到盘后日报→回放盘中翻转→收到通知→查看建议卡→T+N 跟踪统计 | 测试 | T-F11…T-F16 |
| T-B70 | **T-A11 拆分 · MVP：隔离回放与导入基线**。目标/接口：虚构持仓文件→预览/确认→重建；新增可重复的离线行情装载作业，禁止外网；快照按用户隔离。输入：§7.1/7.2、plan 3.5/2.1B；既有 imports/portfolio。验收：两用户越权404；重复导入不重复成交；≥80根虚构有效日K及停牌/退市/缺数据样本，零外呼/零真实凭据，回滚后持仓一致。DeepSeek：仅夹具生成可以，隔离与装载设计不可以 | 后端（T-B78 测试配合） | 现有登录/导入；T-B64或隔离测试替代 |
| T-B71 | **T-A11 拆分 · MVP：最小策略导入与查询**。目标/接口：交付策略卡/版本/feature-catalog及 /strategies、版本详情；复用已有表，不把目录草案当正式卡。输入：§7.4、plan 2.5.14；研究员H-01/W-01正式卡。验收：每卡≥6个golden；导入幂等、参数越界/非法DSL拒绝；G1–G7与simulating门槛不放宽。DeepSeek：仅模型/序列化样板可以，导入与晋级设计不可以 | 后端（T-B78 测试配合） | 研究员正式卡 |
| T-B72 | **T-A11 拆分 · MVP：特征底座与唯一规则求值**。目标/接口：补特征生产、MA/ATR等卡所需列、受限AST求值和证据；供盘后/后续signal-rt共用。输入：T-B70数据契约、T-B71卡规格；plan 2.5.4/2.5.10/2.5.14，契约§5.2/7.4。验收：未来行不影响as_of结果；预热不足为insufficient_data；未知字段/任意代码拒绝；复权/单位/停牌冲突有断言。DeepSeek：不可以（设计、特征与规则实现） | 后端（T-B78 测试配合） | T-B70数据契约, T-B71卡规格 |
| T-B73 | **T-A11 拆分 · MVP：实例创建与系统挂载**。目标/接口：/strategy-instances 列表/详情/创建/修改/状态操作/events；复用instances/state.py；持仓挂H-01，W-01显式启用。输入：T-B71；契约§6.0A/7.5，plan 2.5.0C/2.5.11A。验收：I1–I7、simulating权限、他人404；重复挂载一份，paused/archived不产新信号；ETF/未知证券拒绝。DeepSeek：仅模型/序列化样板可以，状态/权限不可以 | 后端（T-B78 测试配合） | T-B71 |
| T-B74 | **T-A11 拆分 · MVP：候选信号与可执行性**。目标/接口：候选写入、/candidate-signals及events/dismiss、/non-executable-reasons；接主表守卫与P1；盘后按用户分支，不依赖生产共享事件。输入：T-B72/T-B73；契约§5.2/6.1/7.6；plan 0A.3、2.5.4/2.5.9。验收：buy/reduce/sell路径有golden；hold/wait无候选；退市/停牌/ETF/universe边界及T+1/现金不足有负例；重复快照不重复信号；原因附解除条件。DeepSeek：不可以（状态机、规则和守卫） | 后端（T-B78 测试配合） | T-B72, T-B73 |
| T-B75 | **T-A11 拆分 · MVP：操作建议与风控**。目标/接口：/suggestions列表/详情/chain/actions/refresh；RiskHook六项按现有策略执行，模板解释、不可变建议与证据链。输入：T-B74；契约§5.2/7.5/7.8，plan 2.5.4–2.5.6。验收：每人每证券至多一active；相同输入不新增；变化连取代链；买卖分歧并列不合成；刷新零外呼；缺现金/行情不生成伪可执行结论，LLM关闭仍完整。DeepSeek：不可以（建议、风控与结论） | 后端（T-B78 测试配合） | T-B74 |
| T-B76 | **T-A11 拆分 · MVP：盘后调度与日报**。目标/接口：worker/beat注册盘后装配→特征/求值→候选/建议→日报作业及 /daily-reports、/{date}；复用pipeline_runs/daily_reports。输入：T-B70/T-B75；契约§5.3/7.8；plan 0A.5、T-B24。验收：交易日调度仅执行一次；同输入重跑幂等，输入变化新revision旧版不可变；中途失败重启可恢复；持仓逐股有结论或gap；API能查最新完成版。DeepSeek：仅日报序列化样板可以，调度/事务不可以 | 后端（T-B78 测试配合） | T-B70, T-B75 |
| T-B77 | **T-A11 拆分 · MVP：终端与今日只读聚合**。目标/接口：/terminal、/today、/market/overview；汇总本人持仓、最新建议、日报及缺口，未建设的草案/提醒集合空但字段齐全；开发可先用契约桩并行。输入：T-B70/T-B75/T-B76；契约§7.3、§5.1，复用对账。验收：真实产物可逐级跳转；ETag/304、300行上限、固定查询次数、账户越权404；无证书不触发采集；缺市场数据null+gap，未读数查实际表不是固定0。DeepSeek：仅模型/序列化与枚举清单可以，聚合/缓存设计不可以 | 后端（T-B78 测试配合） | T-B70, T-B75, T-B76 |
| T-B78 | **T-A11 拆分 · MVP：闭环验收与质量门禁**。目标/接口：回放端到端与契约/权限/不可变性测试，复用真实服务而非复制计算逻辑。输入：T-B70–77；契约§9、既有登录/导入；T-B64最小替代见下。验收：隔离库经真实登录→导入→实例→盘后作业→候选→建议→日报→terminal/today；买/卖/缺数据/分歧均覆盖；ruff/mypy及既有覆盖率门禁过，新主线模块≥90%；零外呼证据。DeepSeek：仅生成夹具/枚举清单可以，验收判定不可以 | 后端（T-B78 测试配合） | T-B70–T-B77 |
| T-B79 | **T-A11 拆分 · 后续：实时与完整交互**。目标/接口：恢复T-B60实时、T-B65生产接线，完善 /signals、/stream、notifications与偏好、plans/plan-drafts及确认、跟踪；不是本轮MVP空壳接口。输入：T-B70–78及暂停任务获重新派单后；契约§7.6–7.8/§8。验收：逐接口恢复契约/越权/断线续传/确认幂等验收；生产须通过出网与证书隔离，部署另获批准。DeepSeek：仅模型/序列化样板可以，实时/安全/业务规则不可以 | 后端（T-B78 测试配合） | MVP完成；另派单恢复暂停队列 |
| T-B80 | **T-A14 · MVP：正式卡晋级（H-01/W-01 → simulating）**。由后端完成：① G1–G6 自动检查执行器，以及 `POST /strategy-cards/{id}/promotion-requests` 和 `POST /admin/strategies/{id}/versions/{vid}/lifecycle`（draft→simulating），已有的复用；② 产出逐门禁报告，写明每条规则与卡片原文的对应关系、证据，以及缺口和警告；③ 系统挂载按契约 §6.0A 第 9 条修订版放行 simulating。G7 按 T-A109 条款：研究员逐条核对、架构师复核后，编排者可在用户本人授权覆盖的卡片上以管理员可信会话代批并留证；缺证据不得批；脚本与未获授权的代理不得代为批准或伪造。详见 2.5.13 G7 与 `docs/reviews/T-A109-g7-delegation.md`。输入：T-B71/T-B73/T-B74；验收：门禁报告逐项为真、晋级后能用 4 只测试股走完盘后闭环，建议标“模拟中”且不出计划草案。 |

#### T-A11 拆分的范围、并行与一次性默认裁定

- **先交付9项MVP（T-B70–78）**：最小闭环是“已导入持仓→按日求值→候选/建议→日报→终端与今日页”，不是承诺 Phase 2 全部实时能力已交付；原 M2 标准保留。T-B70数据/导入、T-B71卡导入、T-B73实例、T-B77读聚合契约桩与T-B78验收骨架可并行；生产集成依赖仍按表执行。关键路径：研究卡→T-B71→T-B72（并行T-B73）→T-B74→T-B75→T-B76→T-B77→T-B78；T-B70及登录入口是并行输入前置。原T-B20a/b/d、T-B35、T-B21/24/31/44由这些行切片交付，不另起重复引擎；T-B13的今日页最小读取前移本阶段。
- **实际盘点**：api/v1已挂auth/accounts/imports/trades/portfolio/horizon/candidates等；`candidates`是研究候选，不是candidate-signals。已有主数据/日线/特征/策略/实例/候选/建议/日报/通知等表定义，不代表生产服务已接线。`domain/portfolio.py`有账本回放与对账，`importing/pipeline.py`有确认/重建；`signals/admission.py`只提供主表守卫、不是G-01完整实现；实例纯状态机、分类器、eligibility可复用。`signal_rt.py`与runner仍是占位，jobs仅有清理和主数据作业，未见特征pipeline、RuleEvaluator、建议/日报服务或这些主线路由。探针`p11_replay.py`只重放GAP核实，不是产品盘后流水线；本次只读代码和路径，不读取敏感个人样本，不以用户实测404冒称本次HTTP实测。
- **研究前置**：目录`catalog.md`明确不是正式卡，`_template.md`是示例；现有文档足够实现协议但不够导入生产规则。研究员先交付H-01持仓风险体检（纯离场）和W-01均线趋势回踩两张正式卡：strategy-card/strategy-spec、参数default/min/max/step、所需特征/单位/复权/预热/时点、止损、反证/失效、成本滑点、每卡≥6个虚构golden与预期动作/原因。同时定G-01边界、G-02所需最小环境特征及N-01缺公告时否决买入的规则；不得把目录示例阈值当正式参数。回放先走simulating与管理员/自愿用户，不放松G1–G7或假称verified_live；T-01仅盘后统计且不出候选，不选为首个买卖卡。
- **暂停队列不自行恢复**：T-B60、T-B61b、T-B65、T-B64、T-B62均保持暂停。T-B60/T-B65是生产实时/采集前置，不是纯离线盘后前置；T-B61b是生产对账安全修复，恢复对账前必做，但离线MVP不运行该链。T-B62在plan无独立正式任务行，依据后端状态、T-O16及T-B61报告指CI业务测试/覆盖率实际缺口收敛，不是新主线接口任务；后移其历史补测，但本轮质量门禁不后移、不降阈值。
- **登录前置单列**：真实本人使用、注册closed且没有approved账号时，T-B64 create-admin是阻塞，需编排者另派最小CLI恢复，不擅自重启。最小替代仅供隔离回放验收：测试fixture用现有密码哈希与账号表建立虚构approved管理员，再走真实登录/CSRF；不创建真实账号、不关闭鉴权、不开放注册、不在报告存密码，不能把该测试替代宣称为本人已可登录。已有本人approved账号则复用现有登录，不再创建。
- **离线作用域默认**：全合成持仓/行情（不读`/workspace/team/samples/`，探针原样本只作结构参考，未经审查不直接复制）；回放禁网络，隔离数据库与Redis命名空间，固定交易时钟及manifest/hash，证据标“模拟回放”。按用户快照/实例的盘后分支落库，`licence_id=null`只指无真实证书的本地模拟；不伪造active证书、不写生产证书内共享signal_states/events、不改T-B60生产归属约束、不串用其他人数据。provider用system、虚构事实标hypothesis/estimate而非真实mairui fact；既有Evidence与解释字段标注模拟，不增加伪造枚举；生产读接口无证书仍按既有gap规则降级。
- **契约默认（同步api-contract §5.4）**：盘后先完成原因检查再提交候选/建议；hold/wait无候选。旧§2.5.4的自动生成草案服从较新的§7.7：本MVP不自动生成草案，必须用户显式POST /plan-drafts；原因解除只转released并通知，仍需用户请求，simulating永不生草案。日报同日多revision、按日期读取最新完成ready/partial版，不覆盖旧版；进行中的revision不遮掉已有完成版。缺上日估值/现金/市场环境时不填伪0或默认range，按契约补充nullable与gap；不把未建设模块的空集合当真实数据缺口已解决。
- **分工纪律**：DeepSeek只做经脱敏的夹具、契约模型/序列化样板、枚举错误码清单；不委派设计、规则求值、权限/风控、评审和验收结论。机械产物由负责人验证并过同一测试门禁。

**里程碑 M2（主线可用，本地内测）**：本地环境下，持仓与自选每天收盘后得到日报、盘中得到实时建议；全部 golden/回放/守卫测试通过。

### Phase 3：其他能力（约 3 周）
| ID | 任务 | 角色 | 依赖 |
|---|---|---|---|
| T-B10 | 研究候选（版本化）+ 用户决定；从策略筛选结果创建候选（契约 v0.2.9 T-A11：接口见契约 §7.7A；本版只开放 manual/from_stock/suggestion 三种来源，策略筛选来源待 `/factor/screen` 定义，问题 69） | 后端 | T-B20 |
| T-B11 | 行动计划（版本化、条件、完整性检查、仓位计算器）；计划只能由计划草案确认生成（T-B34）或手动新建；计划条件 → RC6 检查 | 后端 | T-B21 |
| T-B12 | 用户自定义提醒规则（价格/事件），接入信号引擎与通知 | 后端 | T-B23, T-B26 |
| T-B13 | 今日关注 `/today` 聚合（含契约 v0.2.7 的 alerts、plan_triggers、data_gaps、evidence 与 `risk_event_id`） | 后端 | T-B24 |
| T-B14 | 复盘：时间线（计划→建议→成交→跟踪结果）、三分归因、标签、策略边界统计 | 后端 | T-B11, T-B27 |
| T-B16 | 管理员删除用户数据的 CLI（规则见 7.3；~~导出~~ T-B16 裁定移除；T-A06：无自助注销、无撤回同意） | 后端 | T-B03 |
| T-F05–T-F10 | 候选、计划编辑器与版本对比、提醒规则、今日关注、复盘、隐私中心 | 前端 | 对应后端 |
| T-T05 | 领域测试（成本、冲正、as-of、归因） | 测试 | 对应后端 |
| T-T07 | 合规文案扫描（前端文案、模板、LLM 输出） | 测试 | T-B15 |

### Phase 4：上线准备（买服务器、备案后，约 1–1.5 周）
| ID | 任务 | 角色 | 依赖 |
|---|---|---|---|
| T-O06 | **迁移手册与演练**：本地 → 服务器（`pg_dump`/恢复、导入文件卷迁移、主密钥迁移、**停本地 `ingest` → 等待 ≥ 60 秒 → 启服务器 `ingest` → 核对出口 IP → 删除本地 licence**，以免同一证书 60 秒内超过 2 个 IP；T-A07：生产不用 `MAIRUI_LICENCE`，上线后用户本人的证书也在服务器网页“设置 → 数据证书”录入，私钥只放服务器 `ingest`）、回滚步骤 | 运维 | M2 |
| T-O03 | 服务器环境：主机、域名与 ICP 备案（或按第 9 节决定的方案）、TLS、单出口 IP、备份、监控（IP 超限告警、`ingest` 锁与新鲜度、429/503、预算使用率、SSE 连接数、任务延迟） | 运维 | 用户决策 |
| T-O04 | 生产部署流水线（手动审批）、备份恢复演练、证书/Pro 到期提醒 | 运维 | T-O03 |
| T-T08 | 安全测试（OWASP 基线、会话、CSRF、越权、SSRF——LLM base_url 白名单）、性能基线（100 用户、4,000 只 universe、SSE 100 连接） | 测试 | M2 |
| T-B17 | （条件触发）消息面补充源适配（巨潮或持牌资讯商授权后） | 后端 | 用户决策 |

**里程碑 M3**：技术上可对外开放；**是否开放取决于 7.1（数据授权）、7.2（投资咨询资质）与 ICP 备案的拍板结果。**

### 第二轮补充任务（策略三层、可解释性、行情采集、存储；依据 0B、2.1A、2.5.0–2.5.13、2.8.1–2.8.2、2.12–2.13、3A）
> 下表中的任务**替代或拆分**原表中的同名任务：T-B04 由 T-B04a 替代；T-B20 拆为 T-B20a/b/c；T-B30 中的 `user_symbol_strategy_settings` 改为 `strategy_instances`；T-B11 删除"从建议一键生成计划"，改为 T-B34。MVP 范围按 T002 建议划分：
> - **MVP（M2）**：底座、研究员首批内置策略（`docs/strategies/`）、门禁、计划草案、模拟跟踪、降权与健康度；
> - **第二阶段**：卡片库、晋级流程、用户派生版本；
> - **第三阶段**：LLM 策略草稿、内部评估模块（问题 26 已定）。

| ID | 任务 | 角色 | 阶段 | 依赖 |
|---|---|---|---|---|
| T-B04a | **行情采集服务 `ingest`**（2.1A）：独立容器单副本、证书私钥只在此注入（T-A07）、单活锁、出口 IP 自检、令牌桶 + 三级优先队列（P0 实时 / P1 日批 / P2 回补）、请求意图 Stream、singleflight、`market.updated` 事件、IP 超限告警与暂停、回放模式；import-linter 规则禁止其他包引用麦蕊客户端；**T-A07（2.1B）**：HPKE 解密、每证书令牌桶与三级队列、证书间 DRR 轮转、全局并发上限、按证书熔断与状态机、`verify_licence` 意图、`data_sharing.mode` 与 `source_licence_id`、到期提醒、`MAIRUI_LICENCE` 非空拒绝启动 | 后端 | 1 | T-B02 |
| T-O07 | `ingest` 运维：compose 中 `replicas: 1` 与重启策略、固定出口 IP、冷备切换手册 `deploy/runbooks/ingest-failover.md`、迁移手册中的"停旧 → 等待 60 秒 → 启新"、告警通道 | 运维 | 1 | T-B04a |
| T-O08 | **PG16 + TimescaleDB**：镜像版本固定、hypertable、压缩、保留策略、连续聚合；磁盘与 WAL 规划（≥ 300 GB）；备份恢复演练（含压缩块） | 运维 | 0 | T-O01 |
| T-B02a | 数据模型第二轮（3.3 新增表组）：三层表、`candidate_signals` 的 CHECK 约束、不可变触发器、按月分区、部分索引（3A.6）、`market_rule_versions`、`event_definitions` | 后端 | 1 | T-B02, T-O08 |
| T-B35 | **特征底座**：`app/features/pipeline.py`（唯一产出者）、`feature_catalog`（DSL 白名单与核实状态）、`feature_bars_daily`、`feature_set_version`；按时点规则（`available_from`）、复权口径、因子池排除（2.12.1） | 后端 | 2 | T-B07 |
| T-B36 | **A 股交易规则模块** `app/market_rules`（2.13）：按生效日期分段的涨跌幅、无涨跌幅情形、整手、费用（印花税仅卖出、过户费、佣金最低收费、滑点）、T+1、不可成交判定 | 后端 | 2 | T-B02a |
| T-B20a | 策略接口与注册表：`BaseStrategy` / `ScreenerStrategy` / `TimingStrategy` / `RuleTemplateStrategy`、显式注册表、YAML → DB 不可变版本导入、生命周期状态机与审计（2.5.13） | 后端 | 2 | T-B35 |
| T-B20b | **RuleEvaluator**：DSL 解析（AST 白名单，G3）、规则角色（entry/exit/filter/veto/counter/invalidation）、`rule_refs` 与证据组装、`gate_tradability`、RiskHook（只标记或限量） | 后端 | 2 | T-B20a |
| T-B20c | 接入研究员首批策略（由 T-B20d 从 `docs/strategies/` 导入的模板与 fixtures，每个 ≥ 6 个）、G1–G6 自动门禁、G7 审核页接口 | 后端 | 2 | T-B20b, T-B20d |
| T-B20d | **研究员文档导入器**：解析 `docs/strategies/` 中的 `strategy-card` / `strategy-spec` / `validation` 代码块（2.5.14 A–E），完成校验、按 `key + version_no` 幂等导入、生成导入报告和 `config/strategies/*.yaml`；CI 对该目录只读做格式检查 | 后端 | 2 | T-B20b |
| T-B32 | **策略实例**：`strategy_instances`（I1–I7 校验、`proposed` 需确认、派生版本、风控快照）与 `/strategy-instances*`（列表筛选与分页、§6.0A 状态机与幂等、`/events` 结构，契约 v0.2.7）；替代旧的 `user_symbol_strategy_settings` | 后端 | 2 | T-B20c, T-B30 |
| T-B33 | **候选信号、可执行性与解除监控**：`candidate_signals`（P1 校验，不通过即拒写）、事件表、冷却、22 种原因码及默认解除条件、按 `check_on` 的解除监控（盘中每轮或事件触发）、`reason_released` 通知 | 后端 | 2 | T-B32, T-B36, T-B23 |
| T-B34 | **计划草案与确认**：数量与价格区间计算（2.5.8，使用 T-B36）、人工判断清单、`stale` 判定、确认 → `action_plans` 与 `plan_versions`（origin=plan_draft）；`PLAN_REQUIRES_EXPLAINABLE_SIGNAL` | 后端 | 2 | T-B33 |
| T-B27a | **健康度与降权合并机制**（2.8.2）：`strategy_health_baselines` / `strategy_health_daily`、published ↔ observing 自动切换（带迟滞）、退役建议只通知管理员、用户 `auto_downweight` 开关；模拟跟踪口径（2.8.1：T+1 开盘或下一根 1 分钟 bar 入场、剔除不可成交样本、可选成本） | 后端 | 2 | T-B27, T-B36 |
| T-B37 | 事件定义与事件信号：`event_definitions`、最早可交易时刻对齐、提前反应（拥挤）检查、AI 抽取事件的置信度、原文链接与人工复核队列（2.12.2） | 后端 | 2 | T-B35, T-B25 |
| T-B38 | 卡片库与晋级：`strategy_cards` / `strategy_card_versions`、`rule_snippets`、晋级申请、G1–G7 报告、管理员审核、用户派生版本 | 后端 | 第二阶段 | T-B20c |
| T-B39 | LLM 策略草稿：只输出 JSON、最多修正 3 轮、自动跑 G1–G6、只能保存为 `draft` | 后端 | 第三阶段 | T-B38, T-B25 |
| T-B40 | **内部评估模块** `app/evaluation`（第三阶段，问题 26 已定）：单因子 IC / RankIC / 分组 / 衰减、事件研究 CAR、K 折稳健度（中位数 × 0.6 + 最差折 × 0.4）、发布基线与每日复验 → 2.8.2；`evaluation` 队列独立限流；`/admin/evaluation/*` | 后端 | 第三阶段 | T-B36, T-B27a |
| T-B41 | 存储与缓存：Redis 键与失效事件（3A.3）、预计算表、游标分页统一实现、K 线窗口接口（`before` / `limit`） | 后端 | 2 | T-B02a |
| T-B42 | **DSL 与上下文扩展**（2.5.11A、2.5.14 H）：`max2/min2`（及 `greatest/least` 别名）、`std`、`ts_pct_rank`、`rank_pct_in`、`for/within N bars`、`for p.x days`；`ctx.cost_price`、`ctx.position_weight`、`ctx.sector_weight`、`ctx.highest_close_since_entry`、`ctx.now_hhmm`；`ref` 校验、`validation_summary` 分离、夹具键校验；`system_components` 挂载与 H-01 系统实例；`scan.mode=post_close_stats`、`scan.schedule=monthly_first_trading_day`、`screen.per_group_cap` | 后端 | 2 | T-B20b, T-B20d |
| T-B43 | **P0 策略所需特征**（2.5.11A，数据可得性【待 T003】）：`f.list_days`、`f.market_breadth`（每日落库 + 分批回算）、`f.ann_risk_count_10d`（关键词表进 `event_definitions`）、`f.sw_l1`、`f.vwap_intraday`/`f.vwap_dev`/`f.intraday_sigma`、`f.boll_bw20`/`f.boll_bw20_pct120`、`f.ind_rs20`、`f.main_net_20d`、`f.np_yoy_latest`、`f.pe_ttm_ind_pct`；ST/退市整理状态来源 | 后端 | 2 | T-B35, T-B05 |
| T-B30a | **分类器所需 `f.*` 数据层（v0.2.9 内，T-B46/T-B47 裁定）**：在 T-B35 特征底座上产出 2.5.3 / 6.1 `horizon_classifier.yaml` `features` 列出的 15 个 `f.*`（`f.amount_20d_avg`、`f.turnover_20d_avg`、`f.amihud_20d`、`f.volatility_20d`、`f.intraday_amplitude_20d`、`f.ma_trend`、`f.momentum_60d`、`f.roe_ttm`、`f.profit_cagr_3y`、`f.dividend_continuous_years`、`f.limit_up_count_20d`、`f.fin_report_count`、`f.list_days`、`f.is_st`、`f.is_delisting_period`），写入 `feature_catalog`（单位、可得时点、核实状态）与 `feature_bars_daily`；与 T-B43 重叠的键只实现一次；分类器读取路径接上后，缺失的键照常进 `inputs_missing`；周期评估快照按 3.3 写 `user_id`/`licence_id`。验收：用回放数据为样例证券产出全部 15 个键，`/horizon-assessments` 对数据齐全的样例不再因 `data_missing` 封顶 | 后端 | 2 | T-B35, T-B07, T-R11 |
| T-R11 | **分类器特征口径**（v0.2.9 内，T-B46/T-B47 裁定）：为 T-B30a 的 15 个 `f.*` 写明定义（窗口、复权、单位、缺失与停牌处理、可得时点）、对应的麦蕊接口与字段（【待 T003】的标出）和 3 组手算样例，定义以 `docs/strategies/feature_spec.md` 为准，`horizon_classifier.md` 附录只保留指向它的说明（v0.2.9 内，T-O11 评审裁定）（研究员维护；架构师不改该目录） | 研究员 | 2 | T-B35 |
| T-B44 | **终端聚合接口与日报结构**（契约 v0.2）：`GET /terminal`、`GET /today`（一次查询、无 N+1，弱 ETag + 304）、`DailyReport` 结构（regime 建议仓位区间、对账状态）、`Bar`/`WatchlistItem`/`Notification` 结构、所有带 `security_code` 的对象带 `name`、SSE `signal_kind` | 后端 | 2 | T-B41, T-B24 |
| T-O02a | **密钥与敏感信息扫描**（7.4A）：`.gitleaks.toml`（S1–S9）、`.secretscan-allow.yaml` 与 CODEOWNERS、夹具豁免检查脚本（meta.json 标记、sha256 固定、`generate.py` 可复现、`fake_identifiers`）、`expected.json` 与契约码表一致性检查（3.5A-2）、PR 全提交扫描 + 每日全量扫描、pre-commit 钩子、正反例测试 | 运维 | 1 | T-O02 |
| T-F17 | 候选信号卡与不可执行原因（显示解除条件和自动重评状态；契约 v0.2.7 §7.6 已补列表与 `released_since`）、冲突并列展示、"模拟中 / 观察中"徽标、统计数字旁显示 n 和"样本少"标记 | 前端 | 2 | T-B33 |
| T-F18 | 计划草案确认页：数量与价格区间、人工判断清单（必答）、偏离二次确认、风险确认；`stale` 提示后重新生成（契约 v0.2.7 §7.7：用原 `signal_ids` 再 `POST /plan-drafts`） | 前端 | 2 | T-B34 |
| T-F19 | 策略实例管理（确认 `proposed`、改参越界生成派生版本、暂停、恢复、归档；按契约 v0.2.7 §6.0A 的 `allowed` 显示可用操作）；限制管理（禁投、冷静期、屏蔽） | 前端 | 2 | T-B32 |
| T-F20 | 管理端：模板生命周期与审核页（卡片对照规则、G1–G7 报告）、`ingest` 状态页（队列、预算、错误码、新鲜度）、内部评估页（第三阶段） | 前端 | 2/3 | T-B20c, T-B04a |
| T-F21 | 性能：AG Grid 虚拟化与批量事务更新、K 线窗口加载、游标翻页组件 | 前端 | 2 | T-B41 |
| T-T16 | **可解释性门禁**（0B）：属性测试（随机快照 → 每个信号的追溯字段非空，证据可解析到 `data_snapshots`）；只有 `model_refs` 时无法生成草案；LLM 输出中的每个数字或断言都引用证据 ID；契约中缺少追溯字段即失败。**CI 必过** | 测试 | 2 | T-B33, T-B25 |
| T-T17 | 原因与解除测试：22 种原因码各自的触发与解除（回放 + 时钟模拟）、手动解除只允许不可机器判断的条件、多条原因全部解除才重新检查；统计必带 n（缺少即失败） | 测试 | 2 | T-B33 |
| T-T18 | 计划草案测试：数量公式边界（整手、科创板规则、T+1 可卖、涨跌停价）、`stale` 与过期、没有确认就没有计划；内部评估接口对普通用户不可达 | 测试 | 2 | T-B34 |
| T-T19 | 交易规则模块测试：涨跌停价、无涨跌幅情形、费用最低收费、2026-07-06 前后 ST 比例切换（5% → 10%）、停牌跳过、风险警示股票 50 万股买入上限、`modeled_from` 之前返回“规则未建模”、冲击成本成交额口径 | 测试 | 2 | T-B36 |
| T-T20 | `ingest` 唯一性测试：第二个实例启动被拒、锁丢失即停止外呼、优先级抢占（P0 不被 P2 饿死）、IP 超限模拟 → 告警与暂停、非 `ingest` 容器中没有 licence 环境变量 | 测试 | 1 | T-B04a |
| T-B45 | **数据证书 API（契约 v0.2.6，2.1B）**：`/me/data-licence` GET/PUT/PATCH/DELETE 与 `/test`；`/admin/data-licences` 与 pause/resume；HPKE 公钥加密、`licence_hmac` 防重、`ciphertext` 列级授权与状态视图、请求体与日志脱敏、通知 `data_licence`、SSE `data_licence`、`gaps` 的 `data_licence_unavailable`；`Me.data_licence_status` | 后端 | 1 | T-B04a |
| T-F22 | **数据证书设置页与提示**：“设置 → 数据证书”（密码型输入、提交后清空、永不回显；档位、Quant Pro、到期日；状态徽标与“测试证书”按钮）；证书不可用时的全站横幅与 `gaps` 文案；管理端证书列表（只显示状态）；S-03 等 `risk_level: high` 模板启用开关旁的固定风险说明（T006e；`risk_level` 改为读 `/strategies` 列表字段，契约 v0.2.7） | 前端 | 1 | T-B45 |
| T-O09 | **证书密钥运维**：生成 X25519 密钥对与版本号、私钥只注入 `ingest`、公钥注入 `api`、轮换与重新封装手册、私钥与数据库备份分开保存、从 compose 与 `.env.example` 移除 `MAIRUI_LICENCE`、冷备切换包含私钥 | 运维 | 1 | T-B04a |
| T-T22 | **每用户证书测试**：值不出现在任何响应/日志/SSE/通知（含子串扫描）；`api` 无法解密；一证多用 409；按证书 101/102/103/503 的状态与暂停；不跨证书回退；DRR 公平与 P0 抢占；`per_licence` 下读取只命中本人证书的数据；分类器 `caps.kind` 与 `hints` 独立性（T006e） | 测试 | 1 | T-B45 |
| T-T21 | 2.5.14 契约测试：用测试目录中的虚构卡片验证导入器的通过、拒绝和幂等行为（缺必填字段、DSL 越权、参数 default 越界、fixtures 不足 6 个），不读取 `docs/strategies/` 的真实内容作为测试数据 | 测试 | 2 | T-B20d |
| T-T08（扩展） | 性能：3A.5 的 P95 目标、3 年规模合成数据、locust + pgbench、SSE 延迟、`ingest` 队列等待；回退超过 20% 时告警 | 测试 | 4（第 2 阶段起每阶段跑一次） | T-B41, T-O08 |

| T-B51 | **证券主数据表与迁移（v0.2.9 内，T-A04；plan 4.6.2）**：`securities` 加列、4 张历史表（含 `security_listing_status_history`，`btree_gist` 排除约束）、`security_search_terms`、`master_snapshots`、`master_runs`、`security_reconciliation_diffs`，删除旧 gin 索引；补测交易所 ETF 基金列表端点（只记录端点与字段，不灌数据）。交付：Alembic 迁移、表定义、补测记录。验收：迁移可升可降；重叠区间写入被拒；`/meta/enums` 加 `security_reconciliation_kind`、`security_reconciliation_source`（共 86 个）且 `check_contract` 通过 | 后端 | 1 | T-B04a |
| T-B52 | **交易所列表同步与首次导入（4.6.1、4.6.4、4.6.5、4.6.6）**：`master.sync_exchange_lists`、`master.sync_bse_code_map`、`master.purge_snapshots`（beat 调度、worker `batch` 执行）；快照校验与整份拒收、合并规则、`missing_from_list` 判定、历史表维护；`app.cli.master_bootstrap`；`config/securities.yaml` 的 `master:` 段。交付：任务、CLI、单元测试（用虚构夹具，不复制 `/workspace/team/samples/`）。验收：拒收四种情形各有测试；不在终止上市名单的消失代码只会变 `missing_from_list`；不调用麦蕊 | 后端 | 1 | T-B51 |
| T-B53 | **对账、交叉核对与告警（4.6.4、契约 §7.9）**：`master.reconcile_vendor`（`ingest` P1 按证书拉麦蕊 `/hslt/list`、`/bj/list/all`、`/kc/list/all`、`/hsrl/real/all`，worker 比对）、`master.crosscheck`（巨潮、AKShare）、差异开关闭、5 个 `master.*` 告警键、`GET /admin/securities/reconciliation`。交付：任务、接口、测试。验收：契约 §9 v0.2.9 验收 5–8；响应与日志不含证书值；证书不可用时跳过该证书且不跨证书回退 | 后端 | 1 | T-B52, T-B45 |
| T-B54 | **搜索词条与搜索接口（4.6.3、契约 §7.3）**：词条生成（多音字展开上限 16、默认读音保留、去 ST 变体、曾用名与曾用名首字母、北交所旧代码）、改名时同事务重建、`generator_version` 全量重建任务；`/securities/search` 改走词条表，`SecurityHit.quote_missing`、`master_as_of` 按契约 #33 给值。交付：词条模块、接口、测试。验收：契约 §9 v0.2.9 验收 3–4、7；P95 ≤ 100 ms（3A.5） | 后端 | 1 | T-B52, T-B53 |
| T-B56 | **放弃或失败批次的预览行清理（3.5，契约 #35）**：`discarded`/`failed` 状态变更同一事务删除预览行与未提交行级数据；discard 不再删除原始文件（改按留存策略）；`/rows` 返回空、`errors.csv` 只有表头、resolve 返回 409；beat 每小时调度的 `imports.purge_preview_rows`。交付：代码与测试。验收：契约 §9 v0.2.9 验收 9 | 后端 | 1 | T-B18 |
| T-B55 | **财务按时点自算（L-01 研究口径，2.12.1；v0.2.9 内，架构师裁定）**：从 `market.financial_reports` 按 `plrq` 选版本，计算 TTM、`pe_ttm`、`pb`、`roe_ttm`、经营现金流/净利润、资产负债率，写 `market.financial_derived`；占位行丢弃、重述新版本、15 个月回退、`survivorship_bias` 标记；经营现金流取 `coalesce(jyhdcsdxjlxj, jyhdcsdxjlje)` 并记 `basis.ocf_field`、都空为缺失；2.12.1 的 4 条补充规则（T-R12 已确认）；2.12.1 的 7 条边界规则与 `basis.verify_pending` 标记（T-R12a）；2.12.1 T-R12b 补充裁定 6 条（`null_reason` 封闭枚举，且单元测试断言“`value` 为 null ⇔ 有 `null_reason`”；`single_period_reason`；`unit_mismatch` 覆盖全部 metric；`share_class_check`）；对照报告输出 feature_spec §7C S2 覆盖率（含 PB 全市场与分行业口径、`verify_pending` 单列）；与麦蕊历史因子的截面 Spearman 对照报告。交付：模块、表迁移、虚构夹具单元测试、对照报告。验收：任一 T 的计算只用 `available_from ≤ T` 的数据（属性测试）；净利润 ≤ 0 时 PE 为 null；归母权益 ≤ 0 时 PB 为 null 且不进入行业分位；经营现金流两字段都空时现金流比为 null（不为 0）；银行、保险负债率为 null；T-B35 能读取 | 后端 | 2 | T-B05, T-B35 |
| T-B57 | **主密钥多版本（上线门槛；v0.2.9 内，评审 b195ca6 / T-O12 架构师裁定，1.3）**：① 所有用主密钥加密的列（导入文件头与 `raw_line`、LLM `api_key_ciphertext` 等）带 `kek_id`（旁列或密文版本前缀，如 `AIA2|kek_id|…`、`v2:<kek_id>:…`），HMAC 索引列（邀请码、登录 IP、证书去重与冷却指纹等）带 `key_id`；② 密钥环：用当前钥加密 / 签名，按 `kek_id` 选钥解密，HMAC 查询与签名校验（含游标）对每个有效版本都算一遍；③ 主密钥 secret 文件支持多把带 id 的钥并标出当前钥，`kek_id` 由钥单向派生（不泄露钥），旧的单钥格式视为只有一把；与 `deploy/scripts` 的 ensure / 备份脚本兼容（运维配合改格式校验）；④ 自检：加入新钥并切为当前后，旧数据仍可读、HMAC 仍能命中，新数据用新钥写。**不含**后台重加密 CLI 与运维轮换流程（上线后 V2，运维在 T-O12 之后跟进）。契约不变；第 9 节问题 95。交付：迁移、密钥环、测试 | 后端 | 4（上线门槛，M3 前） | T-B03, T-B45 |
| T-B60 | **接通 signal-rt 的实际信号流水线（v0.2.9 内，架构师；源于 reports/T-B58.md 第 15–16 行）**：`workers/signal_rt.py`、`runner.py` 目前只是存活占位。本任务按 3.x `signal_rt` 进程入口（第 416 行）接通：订阅 `market.updated`、增量计算特征、规则求值、生成候选信号、可执行性闸门（G-01 `gate_tradability`），写入 T-B23 的 `signal_states`、`signal_events`。不新造队列契约，复用 T-B23 和 T-B53 已定的接口。**验收标准**：① 用离线可注入的行情事件跑端到端：从一条 `market.updated` 到 `signal_events` 有落库记录；② **退市证券不出信号**：`securities` 里状态为已退市（含退市日早于等于当日）的证券，以及处于退市整理期的证券，都不生成新的候选信号；退市整理期只阻断买入方向，沿用 `ST_OR_DELISTING`。用例要覆盖已退市、退市整理期、正常三类，并断言没有信号写入，而不是“流水线没跑所以为空”；③ 停牌、非 universe 的证券同样不出信号；④ 进程能优雅退出，被 STOP 开关停止后不再写入。测试员在 T-T 系列中按 ①–④ 补用例 | 后端 | T-B23, T-B51, T-B53 |
| T-B61 | **麦蕊对账批次交接、比对提交与重试（4.6.5A；v0.2.9 内，架构师裁定，源于 reports/T-B58.md）**：注册 `master.reconcile_vendor` 和 `master.reconcile_vendor_apply`；新迁移 `master_vendor_batches`、`master_vendor_list_rows`；`ingest` 处理 `vendor_lists` 意图并写批次；worker 单事务比对提交；beat 兜底扫描；`/admin/ingest/status.alerts` 由差异表生成 5 个 `master.*` 键。**验收标准**：① 离线端到端用例：注入虚构的 ingest 结果，走完 `SYNC_LISTS` → `RECONCILE_VENDOR` → `requested` → `fetched` → `RECONCILE_VENDOR_APPLY` → 差异提交 → `/admin/ingest/status` 出现对应的 `master.*` 告警，`/admin/securities/reconciliation` 能查到；② 重复投递同一 `batch_id` 只比对一次；③ 三份列表任一失败时为 `failed`，按 `attempt` 重试到 3 次为止，不用局部列表比对；④ 证书不可用时为 `skipped`，不跨证书回退；⑤ 旧批次为 `superseded`，不重开已关闭的差异；⑥ 已过 `deadline_at` 的批次为 `expired`，beat 兜底能重新投递漏掉的 apply；⑦ 队列、表、日志不含证书值（用哨兵值断言）。运维同步 `grants.sql` 和 `verify-roles.sh`（4.6.5A 第 9 条） | 后端（运维配合权限） | T-B53, T-B58, T-B45 |
| T-F25 | **管理端证券主数据对账页（契约 §7.9）**：`/admin/securities/reconciliation` 列表（状态、类型、来源筛选，游标翻页）；`ingest` 状态页显示 5 个 `master.*` 告警文案。交付：页面、组件测试（`src/frontend/src`）。验收：不显示证书值；非管理员不可见入口；告警按 `critical` 在前 | 前端 | 1 | T-B53 |
| T-F26 | **搜索结果展示补充（契约 §7.3、§5.1）**：曾用名、旧代码命中时显示“曾用名：…”“旧代码：…”；`quote_missing=true` 显示“本人行情源暂无此证券”；`missing_from_list`、`delisting_period`、`delisted` 徽标；ETF 未建档时无结果的空态文案。交付：组件与组件测试。验收：`match_kind`、`listing_status` 的取值只从 `/meta/enums` 读，不写死 | 前端 | 1 | T-B54 |
| T-A10 | Windows 本地部署（WSL）：见 [runbook](runbook/windows-local.md)；前端构建与 nginx 待 T-O19 补齐 | 架构师 | — | T-O19, T-B64 |

缺口：`create-admin` 命令未实现，已排给后端 T-B64；管理员创建步骤实现后再验收。

### T-A87 M-1 IngestCore 外呼接线（status: draft；架构师 2026-11-09；基 integ/B3=a7ce362；T-A89 修订 M-2；T-A91 修订 M-a/M-b/M-c 与两层守卫；风控项须异源复核）

来源：T-A86 中 M-1（R12）。bootstrap 建出的 `IngestCore` 是空壳：没有 licence，生产代码里没有任何 submit/next_call/complete 调用。daily_lists 外呼只靠 STOP/HALT 文件、库内 `upstream_halted` 和 single-egress 锁，103/429 不写 `ops.data_licence_events`，所以契约 §9 v0.2.6「T-A75 按用户累计」在生产外呼路径上不成立。本节同时收 T-A86 的后端 L-1、L-2、L-4。开发和测试全程不得真实调用麦蕊，只用假 transport、mock 上游和一次性 PG。

**T-A89 修订理由（M-2，风控，R17）**：T-A88 评审 be/T-B116=2422107 时实测：① `core.upsert` 每次把库里的 active 写回内存，上游 102→INVALID 后下一次 `mairui_get` 仍放行（transport 共 2 次），违反 state「102 停止全部调用」；② `EgressLease(held=True)` 可被调用方自造绕过 single-egress；③ 另一会话持 `ip_limit` 锁且无 pending 时 rehydrate 不取锁即放行；④ 公开 `daily_lists.wire` 直接拿到 `_https_get`，静态守卫未挡住 4 种绕过。故修订 api-contract §7.11.5 第④条（证书状态以库为准、102/INVALID 后必拒、状态变化先写库、内存与库取更严、解除须人工）与 lease 不可伪造，并补 B-1(a)/B-2 契约；验收由 A1–A24 增至 28 条（A1–A5/A6a/A6b/A7–A27，见下表）。后端 M-2 实现等本契约合入后再接（T-B116b）。

**T-A91 修订理由（M-a/M-b/M-c 与守卫边界，风控，R15/R16/R18/R19）**：T-A90 评审 be/T-B116c=41e517a：B-2′ 静态守卫第三轮仍被 importlib/getattr/相对导入/别名/urllib3/`__import__`＋拆串域名/probes 新文件等变体绕过；M-a 往 `_ISSUED_LEASES`/`_LEASE_LOCK_CONN` 塞假项可放行；M-b 有 pending 且锁争用时准入两轮取锁 3.71s；M-c 102 写库失败后重启即再放行 1 次。静态扫描永远堵不完动态写法，故不再逐轮补绕过，改为**两层**：静态层只守 api-contract §7.11.5①a 的有限清单 S1–S6；动态写法由运行时层①b 兜底，并写明两层各自不负责的写法（①c）。同时修订②（HMAC＋线程绑定＋`pg_locks`）、④（准入单事务 SAVEPOINT、3s 超时对齐、写库失败同时写 HALT、退出码 74）。验收由 28 条增至 **34** 条（见第 5 节 T-A91 表）。

**运行时层方案比较（T-A91 定稿：A 为主、B 为辅）**：
- **(A) ingest 进程内 `sys.addaudithook`**：能拦住 B-2 真正的威胁——ingest 进程内绕过 egress 的 Python 代码，不论它怎么拿到名字（importlib/getattr/`__import__`/拆串域名/urllib3/requests/socket 直连 IP），因为最终都经过 `socket.getaddrinfo`/`socket.connect` 审计事件；也能拦 `subprocess.Popen`/`os.system`/`os.exec`/`os.posix_spawn`/`ctypes.dlopen`。钩子一经安装不可卸载（优点）。局限：C 扩展/libc 直调不触发事件；安装前已建立的连接不受管（故装在 `main()` 第一行）；同进程代码可篡改钩子闭包（威胁模型外）。DNS：按主机名后缀 `mairuiapi.com` 判定；IP 直连：公网地址默认拒绝，只放行窗口内由 egress 自己解析并登记的 IP（私网/回环/AF_UNIX 放行，供 postgres/redis）。性能：本机离线实测空钩子约 0.16µs/事件，可忽略。可在无网子进程里用假 socket/无网命名空间验证，开发全程不碰麦蕊。
- **(B) 容器网络只让 ingest 出网**：核对 41e517a 的 `deploy/compose/docker-compose.yml`：**没有任何 `networks:` 定义**，全部服务在默认 bridge 上、都能出网。worker 名义上有出网需求（主数据同步 `app/workers/jobs.py:192/224` → `app/master/sources.py:518` 访问交易所，及 SMTP），但主数据同步现为桩、SMTP 无功能；**编排者 2026-11-09 裁定**：worker、maint-cli 平时不出网；主数据同步解桩时优先放进 ingest；首导若需联网，用显式的一次性 compose profile 接 `aia_egress`；SMTP/LLM 无功能不开，日后新增出网须经 R19 登记。compose 层无法按域名放行。B **拦不住 ingest 进程内的旁路**（B-2 的威胁正在此）。worker/api 不持有证书私钥（`data_licence_seal_private_keys` 只挂 ingest），即使连上麦蕊也没有可用证书，风险较低。故 B 只作容器间纵深防御：postgres/redis/api/signal-rt/beat/migrate/timescale-apply/db-roles/maint-cli 进 `internal: true` 网络，只有 ingest 另加可出网网络，nginx 加边缘网络；各服务实际出网需求由运维逐一核实后定。B 归运维（T-O68），不阻塞 T-B116d 合入。

**1. 麦蕊 HTTP 外呼点（a7ce362 上 `rg` 全库扫描）**

| # | 位置 | 性质 | 经 IngestCore | STOP/HALT | single-egress | 库 upstream_halted |
|---|---|---|---|---|---|---|
| E1 | `src/backend/app/ingest/daily_lists.py:56`（`HTTPSConnection`）、`:59`（`request`），由 `process` `:285` 调用 | 服务内，在镜像里 | 否 | 是（:231/:258/:283） | 是（:202 会话锁） | 是（`eligible` :228/:271） |
| E2 | `src/backend/probes/common.py:309`（基址 :29-30；p01–p13、run_all 共用） | 本机探针，不在镜像里（`deploy/docker/backend.Dockerfile.dockerignore` 白名单不含 probes） | 否 | 自有 STOP | 否 | 否 |
| E3 | `src/backend/probes/tb81.py:195-196` | 同上 | 否 | 自有 STOP | 否 | 否 |
| E4 | `src/backend/probes/tb86_history.py:157`、`:251` | 同上 | 否 | 自有 STOP | 否 | 否 |

- 合计 4 处，4 处都不经过限流核心。服务内只有 E1 一处必须接入。E2–E4 是用户本人电脑上手动跑的探针，不属于 ingest，本单不改，但静态守卫要把它们列入白名单并断言不进镜像、不被 `app/` 导入。
- 已排除：`app/master/sources.py:541` 只连交易所，不连麦蕊；`selfchecks/test_tb90_*` 里都是 monkeypatch 的假连接；`vendor_lists.py` 只是注入边界；`verify_licence` 意图还没有消费者，将来接入时同样必须走统一出口。
- 现状说明：`live_budget_issue()`（daily_delivery.py:45-46，LISTS=3 > DAILY_HTTP_LIMIT=1）目前让 E1 永远到不了 socket，所以 M-1 没有实际泄漏。但预算一旦放开就会直接暴露，必须在放开之前完成本单。

**2. 最小改法**
- 新建 `app/ingest/egress.py`，作为唯一的麦蕊出口，接口契约见 api-contract §7.11.5（T-A89）。**删除** `daily_lists.wire`（不得保留公开旁路）；`process` 通过 `single_egress(engine)` 拿签发 lease，再调 `mairui_get(...)`，默认 transport 为 egress 私有 `_https_get`。daily_lists 不再直接 import `http.client`，egress 外不得引用 `_https_get`/`HOST`。
- licence 注册时机：采用懒注册，每次调 `mairui_get` 时在短事务内有界取 `ip_limit` 锁（壁钟 ≤3s，B-1(a)）后读 `user_data_licence_status`（tier/status/expires_on/paused_until/deleted_at），然后 `core.upsert(...)` + 至多一轮 `core.rehydrate(user_id, now)`。bootstrap 不预加载。行不存在、已删除或不是 active 时拒绝外呼。**upsert/rehydrate 不得把 INVALID/PAUSED_BY_ADMIN/EXPIRED 降回 active**；内存与库不一致取更严；102/终态须先写库再处理后续调用，写库失败 fail-closed（M-2 / R17）。
- 准入：复用 `core.submit` 加 `core.next_call`，不另写准入逻辑。返回 None，或返回的不是本次 Call，都拒绝外呼，并 `scheduler.drop_licence` 清掉本次排队项。完成后一律调 `core.complete(d, signal, now)`。signal 的判定：daily 的 `limited()` 为真时记为 IP_LIMITED，否则用 `upstream.classify`。
- 103/429 的处理：HALT 文件的写入从 daily 挪进 egress，顺序是先写 HALT，再 `core.complete`（内部 `record_hit` 写 `ops.data_licence_events`）。`upstream_halted` 仍由 daily 写进 master_runs。三步里后一步失败不撤销前一步。
- L-1：`engine_for` 增加 profile 参数。`profile="ingest"` 时用 NullPool，`connect_args` 设 `connect_timeout=3`、keepalives、`tcp_user_timeout=5000`、`options=-c statement_timeout=5000 -c lock_timeout=2000`。api 和 worker 默认 profile 不变。bootstrap 和 daily 共用 ingest profile。
- L-2：`main` 用 try 包住 `get_settings()` 和 `bootstrap_ingest_core()`，捕获全部 Exception（包括 ArgumentError 和 pydantic ValidationError），只打印固定文案加异常类型名，退出码 78。不打印 `str(exc)`，因为 ValidationError 会带出 input_value，可能含口令。bootstrap 内 `engine_for` 也要放进 try。
- L-4：保留阻塞式 `acquire_ip_limit_lock` 加 `lock_timeout` 2s（T-A84 L-7 的公平性，已验收），删除未被调用的 `ip_limit.py:164` `try_acquire_ip_limit_lock`，把 `core.py:103` 的 docstring 改为「有界等待（lock_timeout 2s），不是 try-lock」。
- **T-A91 补充（后端 T-B116d）**：① 新建 `app/ingest/netguard.py`（`install()`、`_egress_window`、`EgressBlocked`），`workers/ingest.py` `main()` 第一行安装；`_https_get` 在窗口内先解析 `HOST` 并登记 IP，再按 IP 建 TLS（SNI 用域名）。② lease 改为闭包密钥 HMAC（nonce‖thread_id‖lock_pid）＋线程绑定＋`pg_locks` 核验，`_ISSUED_LEASES` 只作释放记录、不再是放行依据。③ 准入合并为一条连接一个事务：取锁→读证书→rehydrate→pending 时 `begin_nested()` SAVEPOINT flush→外层提交后清 pending；deadline 2.8s 驱动 `SET LOCAL lock_timeout/statement_timeout`；ingest profile `connect_timeout` 3→2。④ 102/终态写库失败：写 HALT（`licence_status_persist_failed`）＋拒绝；HALT 也失败 `os._exit(74)`；bootstrap 增停机目录可写探测（不可写 78）。

**3. fail-closed 矩阵（每一行的结果都是 0 次 socket）**

| 情况 | 现在（E1） | 改后 |
|---|---|---|
| STOP/HALT 存在 | 拒绝 | 拒绝 `halt_present`，在取任何锁和读库之前判断 |
| 库 `upstream_halted` | 拒绝（eligible） | 不变，排在 core 之前判断 |
| 库不可用 | 连库异常，冒泡到 runner | 同样冒泡；如果走到 core，rehydrate 失败会记为已升级，拒绝 `core_denied`；连接最多等 3s（L-1） |
| 拿不到 single-egress | `busy` | 不变；egress 没有 lease / 核验失败时拒绝 `single_egress_not_held` |
| 自造或失效 lease | 不涉及 | 拒绝 `single_egress_not_held`（A6b）；不得仅凭 `held=True` 放行 |
| ip_limit 锁超时（无 pending） | 不涉及 | 取锁壁钟 ≤3s，超时记为已升级，拒绝 `core_denied`（A6a）；禁止双重 rehydrate |
| core 未接线 | 照常外呼（缺口） | 拒绝 `core_unavailable` |
| 没有 licence 或非 active / INVALID | eligible 拒绝 | 另外在 egress 里拒绝 `licence_unavailable`；upsert 不得降回 active |
| 上游 102 | 不统一落库 | 先写库为 INVALID，本调用后每一次与重启后都拒绝 `licence_unavailable`；transport 全程只 1 次 |
| 状态变化写库失败 | 不涉及 | 本调用拒绝 `core_denied`；同时写 HALT（M-c），同进程后续与重启后均 `halt_present`（T-A92 澄清，原「`licence_unavailable` 或 `core_denied`」作废） |
| 限流或升级暂停、令牌桶、日额度 | 不检查（缺口） | next_call 返回 None 时拒绝 `core_denied` |
| 计数写库失败 | 不写（缺口） | 内存 fail-closed 加 pending（L-2/L-6），本批失败，后续调用拒绝 |
| HTTP 超时或网络错 | 本批失败、不重试 | 同样失败，并 `core.complete(NETWORK)` 进入退避 |
| 状态写库失败（T-A91 M-c） | 不涉及 | 同时写 HALT（`licence_status_persist_failed`）并拒绝 `core_denied`；重启后 `halt_present`；HALT 也写失败 → `os._exit(74)`；停机目录不可写 → 启动 78 |
| 有 pending 且锁争用（T-A91 M-b） | 不涉及 | 单事务一轮取锁、SAVEPOINT flush，墙钟 ≤3s 拒绝 `core_denied` |
| 进程内绕过 egress 的动态写法 / 子进程（T-A91） | 不涉及 | netguard 审计钩子抛 `EgressBlocked`，按网络失败处理 |
| 伪造/跨线程 lease、注册表塞假项（T-A91 M-a） | 不涉及 | HMAC＋线程绑定＋`pg_locks` 核验不过 → `single_egress_not_held` |

**4. 与 single-egress 锁、停机标志的关系**
- 检查顺序：`live_budget_issue` → STOP/HALT 文件 → single-egress lease（非阻塞）→ batch 事务内 grant/eligible（含 `upstream_halted`）→ 读密钥、建 TEMP（R13）→ 每个数据集依次：STOP/HALT → 预约事务 eligible → `mairui_get`（HALT → lease → core 注册/rehydrate → next_call → 发 socket 前最后一次 HALT）→ socket → 若限流则 HALT → `core.complete` → `upstream_halted`。
- 锁的层级：single-egress 会话锁在最外层（lease 仅由 `single_egress` 签发，mairui_get 核验签发标识与锁仍被本会话持有）；`ingest:ip_limit:{user}` 事务锁在内层，准入全程（取锁＋读证书＋rehydrate＋SAVEPOINT flush）在一条连接一个事务内、墙钟 ≤3s（T-A91 M-b；准入路径用 `SET LOCAL` 覆盖引擎级超时，tick 路径仍用引擎级 `lock_timeout=2000`）；batches/master_runs 的 FOR UPDATE 在各自的短事务里。规则：不在持有 ip_limit 锁或任何未提交事务时取 single-egress；`mairui_get` 必须在调用方没有打开事务时调用；不在任何事务内发 HTTP。`tick_ingest_core` 只取 ip_limit 锁、不取 single-egress，所以没有环。worker 侧的 `mairui_daily_outbox`、`master.mairui_risk_snapshot` 锁不在 ingest 进程里，不嵌套。
- 停机标志（HALT 文件和库 `upstream_halted`）优先级最高：任何 core 状态（包括 user_reset、换证书）都不能越过它们。egress 和 core 都不清 HALT，解除仍按 runbook ingest-halt.md 由用户本人确认。
- R13：TEMP 只在拿到 lease 并通过 batch 检查之后创建，任何拒绝路径都由 `process` 的 finally `remove_owned` 清理。残留普通文件替换、非普通文件拒绝的语义不变。egress 不碰 TEMP。

**5. 验收用例（T-A91 修订后 34 条，见本节末 T-A91 表；T-A89 修订后 28 条 = 原 A1–A24 +4；都要先红后绿；普通模式和 `-O` 都跑；只用假 transport、一次性无网 PG，conftest 屏蔽麦蕊 DNS；自测不得有空断言，禁止 `or True` / `assert True` 一类 L-b）**

验收项增删表（相对 T-A87 初版 A1–A24）：

| 动作 | 编号 | 内容 |
|---|---|---|
| 扩 | A1 | 原静态守卫保留，**另增 4 种绕过反例**（任一放过即红）：① 从他处 `import _https_get`；② 导入 `egress.HOST` 再配 `http.client`；③ 直接调用 `wire` 一类公开旁路；④ 在 `probes/` 新增第 4 个文件 |
| 拆 | A6 → A6a、A6b | **A6a**：另一会话持 `ip_limit` 锁且无 pending → ≤3s 拒绝 `core_denied`，transport 0 次。**A6b**：调用方自造 lease，或 lease 已失效 / 锁已释放 → 拒绝 `single_egress_not_held`，transport 0 次 |
| 增 | A25 | **102 用例**：假 transport 首次返回 102 → 库状态为 INVALID；紧接着下一次与进程重启后再调用都必须拒绝 `licence_unavailable`；全程 transport 只被调 1 次；随后 `upsert`/`rehydrate` 不得把 INVALID 降回 active |
| 增 | A26 | **状态变化写库失败**：模拟 102/INVALID 落库失败（触发器拒绝或连接断开）→ 本调用拒绝且后续调用拒绝，transport 不增加 |
| 增 | A27 | **空断言禁令（L-b）**：egress/守卫相关自测与正式用例不得含 `or True`、恒真断言；原 T-A88 L-b 的 `mairui-zero.txt` 证明须改为真实断言 |
| 保 | A2–A5、A7–A24 | 语义同 T-A87；编号不变（A6 空号，改用 A6a/A6b） |

修订后编号清单（28）：A1（含 4 反例）、A2、A3、A4、A5、A6a、A6b、A7、A8、A9、A10、A11、A12、A13、A14、A15、A16、A17、A18、A19、A20、A21、A22、A23、A24、A25、A26、A27。

- A1 静态守卫（T-A91 起由 A1s/A1r 取代，以 T-A91 表为准）：AST 扫描 `src/backend/app/**`，HTTP 库只允许出现在 `app/ingest/egress.py`；`master/sources.py` 只许 urllib 且不得含麦蕊域名；egress 外禁止引用 `_https_get`/`HOST`；不得存在公开旁路（无 `wire`）；`app/` 不导入 probes；`probes/` 按恰好 3 文件白名单扫描；dockerignore 白名单不含 probes。基线红在 daily_lists.py:56；4 种绕过反例见上表。
- A2 core 未接线时拒绝；A3 库里已有 2 条 ip_limited 事件，第 3 次升级后拒绝，transport 0 次；A4 假 103 后写入 `actor=ingest` 的 ip_limited 事件，同时 HALT 和 `upstream_halted` 照常写；A5 rehydrate 时库不可用，拒绝；A6a / A6b 见上表；A7 licence 缺失、已删除、非 active 都拒绝；A8 计数写库失败（触发器拒绝 INSERT）时 pending 加暂停，下一次调用拒绝；A9 transport 超时，记 NETWORK、本批失败、TEMP 已清；A10 令牌桶 per_minute=1 时第 2 次拒绝；A11 HALT 存在时拒绝，并断言没有取锁、没有查库；A12 `upstream_halted` 时拒绝且没有调 rehydrate；A13 没有 lease 时调 `mairui_get` 拒绝；A14 R13：TEMP 时序、拒绝路径清理、HALT 不被清除；A15 tick 和 process 两线程并发 10 轮无死锁且有时间上界；A16 拒绝码和日志不含哨兵证书和 URL。
- L-1：A17 用只 accept 不应答的假 TCP 端口当库，`tick_ingest_core` 和 bootstrap ≤8s 返回，bootstrap rc=78（基线红：超过 20s）；A18 ingest profile 的 connect_args 和 NullPool 断言。
- L-2：A19 格式错误的 URL（含假口令）rc=78，stderr 没有 `Traceback` 和口令；A20 Settings 校验失败时同样 rc=78 且不泄露。
- L-4：A21 `try_acquire_ip_limit_lock` 已删除，docstring 与实际一致；锁被占时 `_try_flush_pending` ≤2.5s 返回且 pending 保留。
- A22 回归：tb90（含 [existing_temp] 新语义；夹具侧 patch `daily.live_budget_issue`，不改业务默认关闭）、T-T47、T41/T45/tb111–115 全部通过；A23 `-O` 全量；A24 每条用例断言假 transport 的调用计数（0 或预期值），并断言真实 `_https_get` 没有被调用。
- A25、A26、A27 见上表。

**T-A91 验收增删表（相对 T-A89 的 A1–A27，共 28 条 → 34 条）**：

| 动作 | 编号 | 内容 |
|---|---|---|
| 拆 | A1 → **A1s**、**A1r** | **A1s 静态**：只测 api-contract §7.11.5①a 的 S1–S6 清单，每项至少 1 正例（基线/现状应报红的写法报红）＋1 负例（登记例外不报红）：S1 probes 冻结清单外新增 `.py`（含子目录、仅 `import probes.common` 的文件）即红、21 个非外呼探针含「麦蕊域名＋HTTP 导入」即红；S2 绝对/相对/别名/`import *`/任意 `.attr` 引用 `_https_get`、`HOST`、`_ISSUED_LEASES`、`_LEASE_LOCK_CONN` 或其他 egress 下划线名即红；S3 `http.client`/`from http import client`/`urllib.request`/`from urllib import request`/`urllib3`/`requests`/`httpx`/`aiohttp`/`socket`/`ssl` 在 egress 外即红，sources 的 urllib、workers/ingest 的 `socket.gethostname`、netguard 的 socket 不红；S4 麦蕊域名字面量；S5 app 内传 `transport=`/`"transport"` 键或调 `process(upstream=…)` 即红、daily_lists `:289` 测试缝不红；S6 app 内 `__import__`/`importlib`/`exec`/`eval`/`compile` 即红，probes/selfchecks 登记项（含 `p11_replay.py:49`）不红、登记外新增即红。**不得**再为清单外的动态写法加静态反例。**A1r 运行时**：每例在子进程中 `netguard.install()` 后执行，`unshare -n` 无网＋conftest 屏蔽 DNS；断言 `EgressBlocked`（被放行会表现为 `gaierror`/`OSError`，即判红）且审计日志无 URL/证书：① `importlib.import_module("app.ingest.egress")._https_get` 无窗口调用；② `getattr(egress, "_https_get")`；③ `__import__("requests")`＋拆开的域名 `"api."+"mairui"+"api.com"`；④ socket 直连公网 IP 字面量（文档地址 203.0.113.x）；⑤ urllib3 `PoolManager` 访问麦蕊域名；⑥ 持有 lease 但窗口外连接；⑦ lease 在 A 线程签发、B 线程进入窗口或连接；⑧ `subprocess.run(["curl", …])`、`os.system`、`os.posix_spawn`；⑨ `ctypes.CDLL("libc.so.6")`。正向：窗口内假解析（monkeypatch 的 getaddrinfo 返回 203.0.113.10）登记后连接被放行（在无网命名空间里得到 `OSError`，而非 `EgressBlocked`）；postgres/redis 私网地址与 AF_UNIX 不受影响；`main()` 第一行已安装（AST＋运行时 `sys.audit` 探测）；重复 `install()` 为 no-op |
| 增 | A28 | **M-a**：持有一张真 lease 时，① 往 `_ISSUED_LEASES`/`_LEASE_LOCK_CONN` 塞假项（复制 nonce、伪造 conn 对象）；② 改 mac 或 thread_id 的 `dataclasses.replace` 副本；③ 另一线程使用真 lease；④ 锁会话已被 `pg_advisory_unlock` 但对象仍在（`pg_locks` 核验）→ 全部 `single_egress_not_held`，transport 0 次。反例夹具只在子进程运行并带 `# A28-negative` 标记（S2 例外） |
| 增 | A29 | **M-b**：有 pending 且另一会话反复持有 `ip_limit` 锁 → 从进入 `mairui_get` 到 `core_denied` 墙钟 ≤3.0s（普通/`-O` 各 10 轮取最大值）；断言整次准入只开 1 条连接、只发 1 次 `pg_advisory_xact_lock`；锁空闲时 pending 在 SAVEPOINT 内写入并在外层提交后清除；黑洞库（只 accept 不应答）时准入 ≤3.0s 拒绝 |
| 增 | A30 | **M-c**：① 102 后状态写库失败（触发器拒绝 UPDATE）→ 本调用 `core_denied`、HALT 文件存在且内容为 `licence_status_persist_failed`、transport 共 1 次；模拟重启（新 core、库仍 active）→ `halt_present`，transport 仍 1 次。② HALT 目录同时不可写 → 子进程退出码 74，stderr 只有固定文案。③ 停机目录不可写时 bootstrap 退出码 78，且未触碰任何已有 HALT 文件 |
| 改 | A31（原 A22 内 t_t41 L9） | **L9 改为在 flush 上注错**：在 SAVEPOINT 的 `flush_pending_escalation` 处注入失败（不再按连接数 `_BudgetEngine(ok=1)` 注错）→ pending 保留、事件 0 行、`allows=False`；flush 成功时外层提交后 pending 才清除 |
| 拆 | A32（原 A22 内 tb90 existing_temp 后半段） | existing_temp 后半段独立成例：改用**新交易日**触发第二次批次，不再用 owner 把 failed 改回 requested（生产不可达状态）；断言残留普通文件被替换为 0600 并清掉、非普通文件 `temp_path_not_regular` |
| 保 | A2–A5、A6a、A6b、A7–A27 | 语义同 T-A89；A22 回归集合去掉已拆出的 L9 与 existing_temp 后半段（改由 A31/A32 承担）；A17 的 bootstrap 上限不变（connect_timeout 改 2 后只会更快） |

修订后编号清单（34）：A1s、A1r、A2、A3、A4、A5、A6a、A6b、A7–A27（21 条）、A28、A29、A30、A31、A32。

**T-A92 验收口径裁定（编号不变，仍 34 条；只改子项与断言口径）**：

| 编号 | 裁定 | 内容 |
|---|---|---|
| A1s | 用例改 | S5 补 `mairui_get(**{"transport": …})` 字面量与 `**变量`（变量字典含 `"transport"` 键）两种正例（T-A92 实测 T-T55 两种都漏报）；增 S2b 正负例 |
| A1r | 用例改＋产品改 | 安全网改为 install 之后追加的审计钩子（见 api-contract ①b 测试方式），①②③⑤ 由此测到产品钩子；⑦ 须在 A 线程开窗、B 线程连已登记 IP；正向须登记 IP 且传 `validate`。新增子例：⑩ 非麦蕊主机名直连（`--add-host`/hosts 映射到 203.0.113.x）；⑪ `ctypes.CDLL(None)`、`pythonapi.connect`；⑫ `sendto` UDP/TCP Fast Open 到公网；⑬ `egress_window` 无 `validate` 或 `None` lease |
| A17/A19/A20 | 用例改 | 调 `main()` 的用例一律在子进程中运行（钩子不可卸，同进程会误伤后续 subprocess 用例）；产品不提供卸载或关闭开关 |
| A26 | 用例改 | 首次调用断言 `core_denied` 且 HALT 内容为 `licence_status_persist_failed`（不得 `except: pass`）；后续断言 `halt_present`；transport 不增加 |
| A28 | 用例改 | 字段名按契约为 `nonce`；不加 `_nonce` 别名；④ 取不到锁会话须报错而不是继续 |
| A29 | 用例改 | 连接数从进入 `mairui_get` 起算，必须 `== 1`；`single_egress` 锁会话不计入（它在调用方、最外层）；墙钟可从 `_call_mairui` 起算（更严） |
| A30③ | 用例改 | 不加环境变量入口（可把 HALT 改指到易失目录，削弱 M-c）；子进程内改 `app.ingest.daily_lists.HALT` 指向不可写目录，并给一次性库让 engine 探测通过，再断言 78、文案、已有 HALT 不变 |
| A31 | 接受＋补例 | 41e517a 上注入「失败也清 pending」可红；补「flush 成功但外层提交失败 → pending 保留」子例（T-A92 注入「提交前清 pending」现有两例均不红） |
| A32 | 接受＋补断言 | 41e517a 上注入去掉非普通文件检查、`remove_owned` 空操作、权限 0644 均红；补显式 0600 断言 |


**6. 工作包（按权限边界；T-A89 后）**
- 后端 T-B116b（只改 src，接本契约）：修 T-A88 的 B-1(a)(b)、B-2、B-3、L-a、L-c；实现 M-2（upsert/rehydrate 不降级终态、102 先写库、lease 不可伪造）；删 `wire`；rehydrate 前有界取锁 ≤3s 且每调用至多一轮；tb90 自检夹具改 setup（不改业务默认关闭 DAILY_HTTP_LIMIT）；去掉空断言。
- 测试 T-T50/T-T51（只改 tests）：按上表把 A1 扩 4 反例、A6 拆 A6a/A6b、补 A25–A27；先在修前 tip 上证明红，再在 T-B116b 上证明绿；普通与 `-O`。
- 运维 T-O67（只改 deploy/CI）：ci.yml 把新增目录和一次性 PG 服务纳入（沿用 ci-only 口令）；compose 不用改。如果要加 env 形式的超时参数，由后端先定键名。
- **T-A91 工作包**：
  - 后端 **T-B116d（只改 src）**：修 T-A90 B-2′ 的方式改为实现 api-contract §7.11.5①b（netguard、窗口、按 IP 建 TLS）并清理 app 内 S3/S6 违规（若有）；M-a（②）；M-b（④ 单事务 SAVEPOINT＋deadline，`connect_timeout` 3→2）；M-c（HALT＋74＋bootstrap 可写探测）；rehydrate 的 `SET LOCAL statement_timeout` 不再固定 5s。不改 tests、deploy。
  - 测试 **T-T55（只改 tests/selfchecks）**：守卫重写为 A1s 的有限清单（删除逐轮堆叠的变体反例，改为 S1–S6 正负例）；A1r 子进程运行时用例；A28–A32；A22 回归集合调整。先在 41e517a 证明红，再在 T-B116d 上证明绿；普通与 `-O`。
  - 运维 **T-O68（只改 deploy/CI；方案 B 纵深防御，不阻塞 T-B116d）**：compose 增 `internal: true` 网络与可出网网络，按逐服务核实的出网需求分配（编排者 2026-11-09 裁定：只有 ingest 可出网，worker、maint-cli 平时不出网，首导需联网时用显式一次性 compose profile 接 `aia_egress`；nginx 边缘＋内部，其余仅内部；实现见 ops/T-O68b=72d1f3a，已随第 5 批合入 main=b6ba5f9）；CI 增检查：非登记服务不得接入可出网网络。不在 compose 内做域名放行。
- 风控类，须异源复核：R12（本单整体）、R14 检查和锁的顺序及停机优先级、R15 L-1 超时上界与残余、R16 静态守卫白名单、**R17（M-2：证书状态以库为准、102/INVALID 后必拒、lease 不可伪造、状态写库失败 fail-closed）**；R7、R13 随之复核。
- **T-A91 R 项**：**R15 更新**——由「L-1 超时上界与残余」扩为「准入墙钟 ≤3s 的超时对齐（connect_timeout 2、deadline 2.8s 驱动的 `SET LOCAL lock_timeout/statement_timeout`、单事务 SAVEPOINT）及残余：库冻结而内核照常 ACK、PG 主机名解析阻塞、进程自身长暂停时上限不成立，但准入未完成不放行」。**R16 更新**——由「静态守卫白名单」改为「静态层边界：S1–S6 清单是否完整且无误报、登记例外（sources urllib、workers/ingest `socket.gethostname`、netguard、probes/selfchecks 动态导入登记含 `p11_replay.py:49`）是否最小、①c 排除项是否都有运行时兜底」。**新增 R18**（M-a＋M-c）：lease HMAC/线程绑定/`pg_locks` 核验是否可绕、威胁模型边界表述是否诚实；状态写库失败同时写 HALT、退出码 74、启动可写探测与「双失败后重启至多再 1 次」残余是否可接受。**新增 R19**（运行时层）：审计钩子安装时机与不可卸载性、DNS/公网 IP 默认拒绝规则、放行窗口的线程绑定、子进程与 ctypes 拦截、C 扩展/libc 直调残余、方案 B 的网络划分（随 T-O68）。
- **T-A92 R 项**：**R19 扩**——主机名直连、`sendto`/TCP Fast Open、`CDLL(None)`/`dlsym`、窗口默认放行四处缺口与修法；残余增「ctypes 由裸地址构造函数指针（`ctypes.cast`）」「钩子前已导入模块持有的 socket」。**R16 扩**——S2b netguard 窗口 API 与 S5 `**` 两种写法。**R15 扩**——lease `pg_locks` 核验受同一 deadline 且不留 idle in transaction。
- **T-A93 R 项**：**R19 登记残余（不阻塞，按编排者收敛口径，由运维 T-O68 容器网络层与异源复核兜底）**：ctypes 由裸地址构造函数指针（`ctypes.cast`）、`dlsym` 放行的 `Py*` 符号（如 `PyRun_SimpleString` 执行的代码仍受钩子约束）、钩子安装前已建立的 socket/已加载的扩展、C 扩展直调 libc、闭包篡改。**R15 扩**：⑦ 窗口再核用独立 0.5s 预算，不计入准入 3s。审计类别新增 `hostname`、`lease`（封闭集合）。

**未决**：① ip_limit 锁超时或库抖动按 T-A75 一律记为已升级，暂停 1h，代价偏大，是否改成短暂停，需要异源意见；② NullPool 加 `tcp_user_timeout` 防不住「库进程暂停但内核照常 ACK」时语句执行中途的挂起，A17 只覆盖建连阶段，残余风险记在 R15；③ 预算 `DAILY_HTTP_LIMIT` 何时放开、由谁批，不在本单范围。④（T-A91）运行时层的公网默认拒绝会同时挡住 ingest 未来其他合法公网出口（目前无），新增时须改 netguard 并经 R19；⑤ 若后端实测某依赖在钩子安装后需要 `ctypes.dlopen`，按库名登记，须 R19 同意；⑥ ~~方案 B 中 api、signal-rt、beat 是否确无出网需求（如 SMTP、外部回调），由运维 T-O68 逐一核实，核实前不改 compose。~~ **已裁定（编排者 2026-11-09）**：只有 ingest 出网；api、signal-rt、beat、worker、maint-cli 平时不出网；主数据同步解桩时优先放进 ingest；首导若需联网用显式一次性 compose profile 接 `aia_egress`；SMTP/LLM 无功能不开，日后新增出网须经 R19 登记。

### 关键路径
T-O01 → T-O08 → T-B01 → T-B02 → T-B02a → **T-B04a（`ingest`）** → **T-B05（真实证书实测，与 T003 对账）** → T-B06 → T-B07 → T-B35 特征底座 → T-B09 → **T-B20a → T-B20b → T-B20c → T-B32 → T-B33 → T-B34**（与 T-B21 建议引擎、T-B31 风控、T-B36 交易规则并行汇合） → T-B24 盘后日报 →（T-B22 → T-B23 盘中）→ T-B26 通知 → T-B27 跟踪 → M2。T-B08/T-B18/T-B19 导入与 T-B30 分类并行（T-B30 完成前须先完成 T-R11 → T-B30a 分类器特征，挂在 T-B35 之后，v0.2.9 内裁定）；T-B25 LLM 网关独立并行（主线不依赖它，模板兜底）。前端全程按契约 mock 并行。

---

## 9. 待用户拍板的问题（2026-11-01 已回填拍板结论）

> **状态说明**：用户已于 2026-11-01 12:24（MST）批准本方案并对第 9 节拍板（vision.md《方案拍板》）。下面每题标三种状态之一：
> - **【已定 2026-11-01】**：用户明确拍板，或用户明确授权"其余参数按架构师建议执行"。后者标注"（架构师默认）"，用户以后可以在设置里修改。
> - **【编排者默认，用户可否决】**：编排者在 12:32 给出的默认值，用户尚未逐项确认；按默认值开发，用户否决时只改配置或文档。
> - **【待定】**：仍需用户回答，不影响当前开发的写明"不阻塞"。
>
> 当前运行模式：**单用户自用**（用户本人一人）。注册与审核流程照常开发，但对外邀请由配置关闭（`REGISTRATION_MODE=closed`，3.6）。

**A. 合规与对外开放**
1. **操作建议功能的合规路径**（7.2）——**【已定 2026-11-01】方案 A：邀请制、封闭、免费**。由于暂不申请麦蕊授权（问题 2），**授权前只供用户本人使用**，即单用户运行：
   - `REGISTRATION_MODE` 取 `closed`（默认，注册接口返回 `503 REGISTRATION_CLOSED`）/ `invite`（需邀请码，进入 `pending` 待审核）/ `open`（保留，V1 不用）。用户本人账号由 `python -m app.cli create-admin` 创建，单用户期间本人同时是管理员。
   - 方案 B（持牌机构合作）仍是**收费前必须**；方案 C 作为退路保留。
   - 子问题——**【已定 2026-11-01】内测前只供用户本人使用，暂不请律师。** 但**对任何第三方开放（切到 `invite`）之前，必须先取得律师书面意见**（与 7.2 一致），这一前置条件不取消。
2. **麦蕊数据再分发授权**（7.1）——**【已定 2026-11-01】暂不申请**。后果：授权到手前系统只供用户本人使用；任何第三方访问（包括"少量知情测试者"）都要等授权。**T-A07 更新（2026-11-02）**：用户改为给每位朋友单独买证书、各用各的（问题 49），朋友使用不再依赖“再分发授权”；证书归属、代运营、同 IP 多证书与共享缓存仍【待麦蕊书面确认】（问题 50）。
3. **收费时机**——**【已定 2026-11-01】免费**。会员模型只预留数据结构，不接支付。
4. **运营主体、域名与备案**（1.3、7.3）——**【已定 2026-11-01】先本地测试，以后购买境内服务器并以个人名义 ICP 备案**；不采用香港/境外服务器。备案耗时与"金融/证券类信息服务"的前置审批要求仍【待核实】，在买服务器前查清。

**B. 数据与配额**
5. **证书有效期**——**【已定 2026-11-01】有效期至 2027-09-11**（用户确认）。到期前 60 天提醒；届时再决定是否续费，不续则启用降级档（每日 2 万次、无 1 分钟 K，6.1 `realtime.yaml` 的 `degraded_profile`）。
6. **开发/测试证书**——**【已定 2026-11-01】不另购**（与问题 27 合并；架构师默认）。全站只有 `ingest` 一个调用方，本地开发和 CI 用回放数据。
7. **刷新与上限默认值**——**【已定 2026-11-01】（架构师默认）**：快照间隔 15 秒（T-B05 实测后调到上限）；Tier-1 1,500 只每分钟 1 分钟 K；universe 硬上限 4,000；每用户自选 100、重点关注 20。数值仍【待 T003 验证】，可在后台修改。
8. **消息面缺口**——**【已定 2026-11-01】（架构师默认）**：先用"公告类型 + 事件因子"；暂不询价巨潮或持牌资讯商。**V1 没有新闻源**【编排者默认，见 C(8)】。
9. **情绪面缺口**——**【已定 2026-11-01】（架构师默认）**：用涨跌停、炸板、连板、竞价量比和市场宽度替代；暂不采购舆情数据。
10. **覆盖范围**——**【已定 2026-11-01】（架构师默认）**：沪深主板、创业板、科创板；ETF 只做搜索、行情与持仓展示（不运行策略），可转债本版不纳入（问题 53 取代原“ETF、可转债只做持仓展示”）。**V1 不含北交所**【编排者默认，见 C(8)】：北交所股票可以导入和展示持仓，但不进入策略扫描（模板 `universe.boards.bse=false`）。

**C. 策略库与建议引擎**
11. **内置策略**——**【已定 2026-11-01】高风险的短线情绪类策略默认不启用**。卡片新增选填字段 `risk_level: normal | high`（2.5.0A）；`high` 的模板不会被周期分类器推荐，~~用户必须在策略页逐项确认风险后手动启用~~ **（2026-11-02 编排者决定取代，T006e）**：手动启用**不需要逐项确认**，策略页启用开关旁固定展示一段风险说明文字（2.5.0A ⑫），与“不弹同意书、不做确认”一致。首批上线哪些策略：【编排者默认，见 C(1)】。
12. **风控默认值**——**【已定 2026-11-01】（架构师默认）**：单只 ≤ 20%；总仓位按大盘 上行 60–90% / 震荡 40–60% / 下行 0–30%；单一行业 ≤ 40%；连续亏损 3 笔或回撤 10% 预警；中长线默认止损 −20%；六项默认全开，可在设置里逐项关闭或调整。
13. **自动降权**——**【已定 2026-11-01】（架构师默认）**：默认开启；α=10、β=0.6、γ=0.4，权重 0.3–1.2；样本 n < 20 时不调整权重（这是降权门槛，与展示阈值无关，见 2.12.3）；统计窗口按 5 日跟踪期。
14. **模拟跟踪口径**——**【已定 2026-11-01】（架构师默认）**：基准沪深300（可选行业指数），跟踪 T+1/5/20；全站匿名汇总只对登录用户在策略页展示（单用户期间等同本人统计）。hold 的阈值见 C(7)。
15. **周期分类**——**【已定 2026-11-01】只推荐，由用户确认后启用**。唯一例外是系统组件 H-01（持仓风险监控）默认挂到全部持仓，见 C(3)；它只产生减仓/卖出方向的候选信号，不产生买入。

**D. LLM、通知、账号**
16. **LLM 供应商**——**【已定 2026-11-01】先接 DeepSeek**，经 LLM 网关的 `openai_compatible` 适配器接入（2.7）。base_url（`https://api.deepseek.com`）、模型名（`deepseek-flash`）、上下文/输出上限和单价已按官方文档核实（2026-11-01，2.7.1），写入 `config/llm.yaml`（6.1）；key 只从环境变量 `DEEPSEEK_API_KEY` 读取，官方未公布 key 格式，只校验非空。默认开启"解释"，失败回落模板；日预算由管理员设定；`llm_calls` 保留 90 天（架构师默认）。DeepSeek 服务协议与隐私政策已核实（2.7.1、7.3）；仍【待核实】：API 输入输出是否用于训练及关闭方式、API 数据保留期限、是否提供 DPA、思维链是否计费、429 是否带 `Retry-After`、官网营销页与文档价目页的价格差异（以账单为准）。发送内容已按 7.3 去标识化。
17. **通知渠道**——**【已定 2026-11-01】（架构师默认）**：MVP 只做站内 + 可选邮件；企业微信自建应用放第二步。
18. **账号审核细节**——**【已定 2026-11-01】（架构师默认）**：`invite` 模式下注册须填邀请码和申请说明；待审核只在管理端显示角标；被驳回的用户最多重新申请 3 次；**对其他人开放前**管理员必须启用 TOTP（单用户期间可不启用）。当前为 `closed` 模式，这些规则先实现、不生效。

**E. 导入与隐私**
19. **其他交割单范本**——**【已定 2026-11-01】目前只支持通达信格式**（`tdx_trades_v1` / `tdx_positions_v1`）；其他券商格式以后再加。仍需要（不阻塞）：另外需要一份含**撤单、红利入账、股息税、新股中签/入账、银证转账**真实写法的脱敏范本（股东代码、资金账号替换为 X，金额可改为虚构值）。用途：确定这些行的业务类型映射（目前按夹具推测，3.5A-1 标【待范本】）。
   - **分红与摊薄成本——【已定 2026-11-01】分红计入摊薄成本，与通达信一致**：已实现盈亏与分红都并入成本。我方摊薄成本价 =（累计买入金额 + 买卖费用 − 累计卖出回款 − 现金红利到账 + 股息红利税补缴）÷ 当前持股数；送转股只增加数量、不改变成本总额。导入后**必须与券商显示的“成本价”对账**（3.5A 对账表“成本”行），差额超容差记 `cost_differs` 并给出可能原因（缺红利/税费流水、缺期初持仓等）。红利、税费行的真实写法仍待上面的脱敏范本，不阻塞。
20. **格式 A 的待确认项**——**【已定 2026-11-01】**：(a) 来源为**通达信（TDX）导出**，解析器 ID 改为 `tdx_trades_v1`、`tdx_positions_v1`（旧名 `fmt_a_*` 保留为别名）；(b) 持仓快照"成本价"为**摊薄成本**，对账以摊薄成本为主口径（3.5A）；(c) 快照没有日期列，导出时间由用户在上传时确认（默认上传时间，产生 `IMPORT_SNAPSHOT_AS_OF_ASSUMED` 提示）。
21. **原始文件留存期**——**【已定 2026-11-01】（架构师默认）**：保留 365 天，用户可随时删除单个文件，注销时一并删除；可在设置里改。
22. **敏感数据加密**——**【已定 2026-11-01】（架构师默认）**：MVP 不做持仓/成交的应用层字段加密，依赖磁盘加密 + 访问控制；股东代码 HMAC + 掩码（明文不入库）、原始文件应用层 AES-256-GCM 加密并存放在仓库外，这两项照常执行。
23. **期初持仓**——**【已定 2026-11-01】（架构师默认）**：接受"手动录入或由持仓快照转换导入起点之前的期初持仓"。

**F. 运维**
24. **镜像仓库与服务器**——**【已定 2026-11-01】（架构师默认）**：先用 GHCR，境内拉取慢时再加境内镜像仓库；服务器 4C16G、SSD ≥ 300 GB；单用户期间**不设 VPN** 给他人访问。

**G. 策略分层、可解释性、存储、内部评估**
25. **策略卡字段**——**【已定 2026-11-01】vision.md 定稿的全部字段都保留**；8 项必填是晋级 L2 的门槛，其余为选填，原样保存并在详情页展示（2.5.0A、2.5.14 B/H）。
26. **内部评估模块**——**【已定 2026-11-01】要做，放在第三阶段**（T-B40）。先做单因子检验与事件研究，再做参数稳健度。用户可见部分按**方案 A**【编排者默认，见 C(6)】。
27. **开发证书**——**【已定 2026-11-01】（架构师默认）**：暂不购买，等需要并行开发时再定。T-A07：开发与生产的互斥改为按证书执行（2.1B 第 3 点）；朋友的证书不离开生产，开发联调只用用户本人的证书并先在后台暂停。
28. **行情保留期**——**【已定 2026-11-01】（架构师默认）**：1 分钟 K 全市场保留 1 年、跟踪池保留 3 年；日 K 和因子全部保留；业务数据永久保留；磁盘 ≥ 300 GB、内存 16 GB。
29. **计划确认的严格程度**——**【已定 2026-11-01】（架构师默认）**：人工判断清单必答 3 条；超出草案区间需二次确认。
30. **冷却与有效期**——**【已定 2026-11-01】（架构师默认）**：同模板同证券冷却 3 个交易日；候选信号有效期 做T 当日 14:50、短线 1 日、波段 5 日、中长线 20 日。
31. **止损后冷静期**——**【已定 2026-11-01】（架构师默认）**：功能提供，默认关闭，N=3。
32. **策略健康度阈值**——**【已定 2026-11-01】（架构师默认）**：weight < 0.8 持续 5 日 → 观察中；< 0.6 持续 20 日 → 提示复审；≥ 0.9 持续 10 日 → 恢复；退役须管理员确认。

**H. 新增问题**
33. **本地测试期的麦蕊固定出口**——**【已定 2026-11-01】本地测试期间，所有麦蕊调用都在用户本人电脑上进行（唯一调用方）；上线后统一由服务器上的 `ingest` 经单一固定出口调用。开发与生产任何时候都不能同时调用（规则见 2.1A）。** 下面是当初的分析，留作背景：共享电脑出口 IP 会变（T003 已触发错误 103），不能作为 `ingest` 出口（2.1A）。在买境内服务器之前，三个选项：
   - (a) 先买一台小规格**境内固定 IP 主机**只跑 `ingest`（之后并入正式服务器）。如果只做采集、不对外提供网站，是否也要备案【待核实】；
   - (b) 用户家庭或办公网络申请**固定公网 IP**，`ingest` 跑在该网络内的电脑上；
   - (c) **只用回放数据**开发（T-B04 录制/回放），真实联调推迟到买服务器后。
   - 架构师建议：先 (c) 推进开发；需要实测（T-B05）时选 (a)。

**H2. 2026-11-01 补充拍板**
34. **前端版本**——**【已定 2026-11-01】React 19 + antd 6**（原型 T-F00 已验证），全文替换原 React 18 + AntD 5（概览表、1.1、2.10、T-F01）。
35. **错误追踪与密钥扫描**——**【已定 2026-11-01】暂不接入 Sentry**（境内部署时再决定是否自托管）；**不依赖 GitHub secret scanning，只用 gitleaks**（7.4A）。
36. **交易规则与因子口径**——
   - **【已定 2026-11-01，已核实】沪深主板 ST/*ST 涨跌幅 2026-07-06 起由 5% 改为 10%**，此前为 5%。出处：上证发〔2026〕41 号、深证上〔2026〕551 号（2026-04-24 发布，2026-07-06 施行；链接见 `docs/strategies/market_rules_check.md` O1–O8）。已写入 2.11、2.13、`market_rules.yaml`（T-A02）。
   - **【已定 2026-11-01，用户拍板】2023-04-10 之前的规则不建模**（`modeled_from`）；起始日依据 O9、O10 第 10.9 条（政府网转载证监会信息确认日历日期，交易所原页未找到）；更早的回看标“交易规则未建模”。需要时再按 2020-08-24 分段。
   - **【已核实 T006b，T-A03 已同步】** 涨跌停价舍入：沪 3.3.17、深 3.3.19（含两条边界规则）；风险警示 50 万股买入上限：沪 4.4.10、深 4.5.4，**只适用主板与创业板，科创板不适用**（沪 4.4.1、6.14）；只能限价申报**只适用沪市**（沪 4.4.9）；科创板单笔 ≥ 200 股（沪 6.7）。
   - 仍待核实（不阻塞）：① 因子数量 77/82/85 的口径（2.5.14 H⑪，T003）；② 科创板“超出 200 股后按 1 股递增”与北交所交易单位（2.13；北交所 V1 不扫描）。
37. ~~**新手是否限制短线周期**~~——**【已被问题 44 取代，2026-11-02】** 原文：**【已定 2026-11-01，方案 A】**（horizon_classifier.md §9）：`profile.experience` 为 novice 或未填写时 `short` 封顶 59（不列为“适合”），用户可经 `fit_ack` 覆盖；实现为分类器新版本 1.1.0（`version_no: 2`）的 `requires` 规则 `SH0C`（6.1）。`intraday_t` 同样封顶 59，规则 `IT0C`【编排者默认，用户可否决，2026-11-01】。
38. **【已作废：用户 2026-11-02 决定，见问题 43–44】** ~~**问卷结果是否作为画像上限**~~——**【待用户确认】研究员默认：是**（`risk_questionnaire.yaml` `profile_write.derived_is_upper_bound: true`）：`risk_tolerance`、`experience`、`effort` 只能改得比最近一次有效测评**更保守**，改得更激进 → `400 VALIDATION_ERROR`（`issue: exceeds_assessment`，带 `max_allowed`）；没有有效测评时这三个字段只能为空（分类器按未填写处理）。理由：否则自填 intermediate 即可绕过 SH0C/IT0C。若用户否决：三个字段可自由填写，测评结果只作建议值。
39. **【已作废：用户 2026-11-02 决定，见问题 43–44】** ~~**`fit_ack` 能否越过封顶**~~——**【待用户确认】默认**：① 画像类封顶（SH0、SH0B、SH0C、IT0B、IT0C）与卡片适配下限（实例校验 I3）可以用 `fit_ack` 确认后启用（沿用问题 37 方案 A）；② **例外（研究员默认）**：测评命中 `no_loss_tolerance`（R1 选“不能接受任何本金亏损”）的用户，short / intraday_t 相关策略不提供 `fit_ack`；③ **（架构师默认）**证券级闸门 HG1–HG6 与 `data_missing` 类封顶不能用 `fit_ack` 越过（它们描述的是证券和数据，不是用户偏好）。契约：`422 STRATEGY_FIT_ACK_REQUIRED` 的 `details` 增加 `ack_allowed` 与 `blocking_rule_ids`。
40. **【已作废：用户 2026-11-02 决定，见问题 43–44】** ~~**测评有效期**~~——**【待用户确认】研究员初值**：有效 365 天，到期前 30 天提醒，过期后 30 天宽限期（只提示）；宽限期后视为未测评（⚖ 接口 `403 CONSENT_REQUIRED`，`required` 含 `risk_assessment`）；问卷 MAJOR 版本且 `forces_retest: true` 时强制重测；用户可随时重测，24 小时内最多提交 3 次。官方文件没有规定有效期，365 天没有监管依据。
41. **【已作废：用户 2026-11-02 决定，见问题 43–44】** ~~**风险测评的实现方式**~~——**【编排者定，2026-11-01】**：问卷已由研究员（T-B15）编写（`docs/strategies/compliance/risk_questionnaire.yaml`），后端直接按它实现并发布到 `questionnaires`；**不做**用 CLI 直接写测评记录的过渡方案（关闭 T-A05-decisions 待决问题 1）。
42. **【已作废：用户 2026-11-02 决定，见问题 43–44】** ~~**五类法律文书**~~——**【编排者定，2026-11-01】**：研究员起草各文书的版本（要点见 `docs/strategies/compliance/versioning.md` §7）；**用户审阅后**才能对第三方开放（并仍按问题 1 取得律师意见）；仅本人自用的 `closed` 阶段允许 `"unversioned"`（与 3.6 一致）。
43. **同意流程与法律文书**——**【用户已定 2026-11-02】**（定位：仅朋友间私下使用、非商业）：不弹同意书、不做同意记录；注册即视为同意；只保留固定免责提示（`docs/strategies/compliance/disclaimer.md` 1.0：“本工具仅供个人研究参考，不构成投资建议。候选信号由规则自动生成，数据可能延迟或出错，盈亏自负。”）。作废：`consents`、`legal_documents`（含停用表）、`questionnaires`、`/meta/consent-docs`、`/legal/*`、`POST /me/consents`、`CONSENT_REQUIRED` 与 `sensitive_financial_info` 门槛、`agreements`、`"unversioned"` 逻辑、`/onboarding`（契约 v0.2.5 作废清单）。
44. **风险测评与 fit_ack**——**【用户已定 2026-11-02】**：不做风险测评；删除问卷、`risk_assessments`、`fit_ack` 与 `STRATEGY_FIT_ACK_REQUIRED`。新手不再封顶，用户可自由选择 short 与 intraday_t；`SH0C`/`IT0C` 只在用户自报 `experience=novice` 时提示。**架构师据此统一裁定**：画像类规则 `SH0`、`SH0B`、`IT0B` 同样改为只提示（未填写不封顶、不提示），分类器 1.2.0（`version_no: 3`），见 2.5.3、6.1。
45. **账号删除**——**【用户已定 2026-11-02】**：管理员手动清理，不设自动留存期（7.3）。
46. **更换 LLM 供应商**——**【用户已定 2026-11-02】**：只发站内通知，不要求重新同意（7.3）。
47. **T-A05 合规部分**——**【用户已定 2026-11-02】**：35f4880 中的问卷、同意、文书版本设计全部作废（研究员文件保留，顶部标“已停用”）；T-F02 D1–D10 中与同意无关的部分（D1、D3、D5、D6 的 CSRF、D7、D8、D9 的 `/account-status`）保留。
48. **【风险提示，未决，供用户知悉，不阻断】朋友属于第三方**：① 麦蕊数据再分发——**【用户已定 2026-11-02】改由每人自用证书解决（问题 49）**：每位朋友用自己的证书、只看自己证书取到的数据；剩余风险（证书须以朋友本人名义申请、由用户服务器代为调用、同一 IP 多证书、共享缓存）均【待麦蕊书面确认】（问题 50，7.1）；② 朋友的交割单与持仓属于敏感个人信息，由本人代为保存与处理，取消单独同意后合规依据更弱（7.3）；③ 证券投资咨询资质（7.2）：免费、封闭可降低但不消除风险；④ 愿景与问题 1 原要求“对第三方开放前取得律师书面意见”。本项只记录风险，不作决定，由用户自行权衡。
49. **每用户自用麦蕊证书**——**【用户已定 2026-11-02】**：用户为每位朋友单独购买一张麦蕊证书；每位用户在“设置 → 数据证书”录入自己的证书，只用自己的证书取数（2.1B，契约 v0.2.6）。架构取舍（架构师，T-A07）：证书 HPKE 加密、只有 `ingest` 能解密、从不回显；每证书令牌桶与 P0>P1>P2 队列、证书之间轮转；默认 `data_sharing.mode=per_licence`；证书不可用时**不回退**到他人或管理员的证书；生产不再使用全站 `MAIRUI_LICENCE`。建议朋友买**钻石版 + Quant Pro**（全市场快照只限包年/钻石或 Quant Pro，1 分钟 K 需 Quant Pro），并以朋友本人账号申请。
50. **【待麦蕊书面确认，未决，不阻断开发】证书归属与共享**：请用户向麦蕊书面询问（QQ 3826425416 或 https://www.mairuiapi.com/linkmeans 的企业顾问表单，保留记录）：① 用户付费、以朋友本人账号申请的证书，由用户的服务器代朋友调用，是否允许；② 同一台服务器（同一出口 IP）同时使用多位不同持有人的证书是否允许，“60 秒 2 个 IP”是否按证书单独计算；③ 用 A 的证书取到的行情（含派生指标）缓存后展示给同样持有证书的 B，是否允许（即 `shared_cache`）；④ 如需书面授权或企业版，范围与费用。答复前一律 `per_licence`，`shared_cache` 禁用；答复存档后由用户拍板。
51. **证券公开主数据是否全站一份（T-A08 Q1）**——**【架构师已定 2026-11-02，T-A08】**：只有交易所公开信息全站共享：代码、简称、拼音、曾用名、交易所、板块、上市日、状态、风险警示；行业、概念、股本等仍按本人证书各取（2.1B 例外，契约 v0.2.7 §1.1、变更 #19）。公开信息的确切来源（交易所公开列表，或用管理员本人证书拉取）【待问题 52 / T-A04 补测】；**确认前不得用他人（含管理员）的证书**为其他用户取数，只用交易所公开列表。公司全称不在范围内，不收录。
52. **【默认执行，用户可改】（编排者 2026-11-01 按保守默认定下）交易所公开证券列表能否展示、能否再分发（T007 §4；T-A08 Q2；T-A04、reports/T-A04-ops.md）**：行情和数据**只对登录用户展示，不提供批量导出，不对外分发**。约束：① `/securities/*` 与一切行情、数据接口都需登录，不新增匿名（未登录）接口、公开下载文件或对外数据接口；② 不提供批量导出端点（CSV/Excel/整表下载等）；搜索不分页、每次最多 50 条，网关对搜索单独限流（每客户端 5 r/s、burst 20，1.3），抑制脚本枚举；③ `/securities/*` 一律 `Cache-Control: private, no-store`，网关不缓存、不上 CDN（1.3）；④ 只展示问题 51 所列公开字段，响应带 `attribution` 注明来源；来源确认前只用交易所公开列表，不用他人（含管理员）的证书为其他用户取数；⑤ 对账表中的麦蕊值只给管理员看，不进任何对外页面或报表；库备份只用于本系统恢复，不对外分享、不作数据集给他人；`data/master/` 原始名单不进异地备份、按 90 天清理；⑥ 日志不落整份名单或响应体。用户确认各来源许可条款（交易所、巨潮、AKShare 上游、麦蕊再分发条款）后可放宽或收紧。契约核对：现有导出类接口只有 `GET /imports/{batch_id}/errors.csv`（本人导入文件的掩码错误行，不含行情与主数据），与本条不冲突。需要谁定：用户（合规）。
53. **【编排者已定 2026-11-02】ETF、可转债是否纳入 `security_type` 和搜索（T-A08 Q3）**：ETF 纳入 `security_type`、搜索与持仓（交割单可能含 ETF 成交），策略不对 ETF 运行；可转债本版不纳入。枚举与接口同步在 T-A09 完成——**已在契约 v0.2.8 同步**：`security_type` 加 `etf`；搜索 `types=` 默认含 `etf`；资料、行情、持仓、导入照常；ETF 不能建策略实例（复用 `422 INSTANCE_SCOPE_INVALID`）；财务、因子、资金流、公告返回空数组与 `not_applicable` gap；HG1 不变。
54. **【编排者 2026-11-02 定为按默认】不提供，只给全市场排名】因子的行业内分位（T-A08 Q4）**：麦蕊没有直接提供，自行计算需要定义行业口径和最小样本数。需要谁定：研究员。
55. **【编排者 2026-11-02 定为按默认】暂不变更状态，信号自然过期】实例归档时其已开放的候选信号如何处理（T-A08 Q5）**：继续有效直到过期，还是置为 `invalidated`。需要谁定：架构师 + 研究员。
56. **【编排者 2026-11-02 定为按默认】不包含，需要时传 `types=`】证券搜索默认是否包含指数（T-A08 Q6）**。需要谁定：前端 + 产品。
57. **【编排者 2026-11-02 定为按默认】本版不加；如需加，在 confirm/resume 时检查】策略实例数量是否受权益上限约束（`ENTITLEMENT_LIMIT_REACHED`，T-A08 Q7）**。需要谁定：架构师（2.9 权益）。
58. **【暂按默认，补测后复核】先按 `f` 实现，`adjust_as_of` 来源待补测】复权 `f` 与 `fr` 的区别、前复权基准日如何取得（T-A08 Q8）**。需要谁定：T003 补测。
59. **【已定，v0.2.9 内前端待定裁定（契约 #30、§7.7B）；原为编排者 2026-11-02 定为按默认】`TodayAlert`、`TodayPlanTrigger` 先作为两接口元素的子集，结构定义时必须兼容】`/alerts`、`/plans` 的完整结构仍未定义（T-A08 Q9）**：T-F06/T-F07 卡在这里；`/today` 的“查看全部”指向这两个页面。需要谁定：架构师（下一轮 T-A09）。**已定**：契约 §7.7B 给出 `PlanSummary`/`Plan`/`PlanVersion`/`PlanCondition` 与 `Alert`、列表筛选与排序、计划状态机（新枚举 `plan_status`、`plan_condition_type`）、提醒状态机（`PATCH /alerts/{id}`）；`TodayAlert`、`TodayPlanTrigger` 保持为其子集；默认取舍见问题 80–83。
60. **【暂按默认，补测后复核】标【待 T003 补测】】板块资金的 `industry` 用哪套行业分类；资金流分档阈值、因子单位等（T-A08 Q10）**。需要谁定：T003 补测。
61. **【暂按默认，T-A09 新增，契约 v0.2.8 未决 U1】一律按 T+1 计算】T+0 的 ETF（跨境、债券、黄金、货币等）的 `sellable_qty` 与 `T1_NOT_SELLABLE`**。需要谁定：研究员核对品种清单。
62. **【暂按默认，补测后复核；U2】名单只用交易所公开基金列表，取不到行情时按契约 §1.1 降级】ETF 名单来源；麦蕊 ETF 实时、日 K、复权是否可用**。需要谁定：T003 / T-A04 补测。
63. **【编排者已定 2026-11-02】交割单中的可转债按 `import_as_is` 导入后，持仓如何展示**：导入时保留原代码；展示标注“可转债·无行情”，现价、市值显示“—”；总仓位与集中度按成本估算并标注“估算”；不跑策略、不出信号、不进入风控止损计算。契约 v0.2.9 已同步（U3 已定）：持仓行 `security_type=null`、`estimated=true`，`market_value`/`pnl`/`pnl_pct` 为 `null`，`weight_pct` 按成本估算。
64. **【暂按默认，补测后复核；U4】只有钻石版过期后有值，其余为 null】各档位麦蕊日额度（`/admin/ingest/status` 的 `daily_limit`）**。需要谁定：T003 补测。
65. **【暂按默认；U5】不改，保持 `no_source`】指数的财务、资金流是否也改用 `not_applicable`**。需要谁定：架构师。
66. **【默认执行，T-A11 新增，用户可改】同一证券同时只能有一个进行中的研究候选**：本人同一证券已有 `researching`/`watching` 的候选时再建 → `409 CONFLICT`，响应带已有候选的 id；放弃或已转计划的不算。需要谁定：用户（产品）。
67. **【默认执行，T-A11 新增，用户可改】“放弃”与“已转计划”的研究候选不能恢复，也不能删除**：要重新研究就新建候选，旧候选及其版本历史保留；物理删除只随账号数据删除。需要谁定：用户（产品）。
68. **【默认执行，T-A11 新增，用户可改】研究候选的决定理由为自由文本（1–200 字），没有预设选项**（2.4 写“必须选理由”，但未定义选项）。需要谁定：用户（产品）。
69. **【默认执行，T-A11 新增，用户可改】研究候选本版只开放手工、个股页、建议三种来源**：候选信号页的入口按“个股页”处理，不记录来源信号；策略筛选来源等 `/factor/screen` 接口定义后再开放；不开放独立的 claims 接口。需要谁定：用户（产品）；`/factor/screen` 由架构师另立任务。
70. **【默认执行，T-A11 新增，用户可改】ETF 与指数不能加入研究候选**（与 ETF 不进入策略的口径一致）。需要谁定：用户（产品）。
71. **【默认执行，T-A11 新增，用户可改】研究候选列表默认不显示已放弃的候选；研究候选没有通知与 SSE 事件**。需要谁定：用户（产品）。
72. **【已定：V1 不加（v0.2.9 内前端待定裁定，契约 #30）；后续版本再加，T-F22 遗留 2】管理端证书列表的服务端筛选**：V1 不加，前端只在已加载的行上筛选；用户多时再加 `?status=`（可多值）与 `?q=`（用户名）。需要谁定：架构师（后续版本）。**已定**：V1 服务端不筛选，`?status=&q=` 仍被忽略；前端保留“继续加载 + 40 页上限”的定位方式。启动后续任务的条件：注册用户超过 200，或前端继续加载触及 40 页上限。
73. **【未决，T-F22 遗留 3】`GET /admin/audit-logs` 的查询参数与元素结构未定义**：本版管理员通过审计查看证书暂停的理由与操作人（`data_licence.paused`/`data_licence.resumed`），不在证书接口中返回。需要谁定：架构师。
74. **【默认执行，T-F22 遗留 5，用户可改】管理员暂停或恢复数据证书时通知用户**：状态确实变化时发一条 `data_licence` 站内通知（标题“数据证书已被管理员暂停”或“…已恢复”），正文不含管理员填写的理由；幂等的重复调用不发。需要谁定：用户（产品）。
75. **【默认执行，T-B47 新增，用户可改】周期评估结果的保留期**：每个（用户、证券、分类器版本）的最新一条长期保留，其余超过 180 天的物理删除；删除用户时全部删除。需要谁定：用户（产品）。
76. **【默认执行，T-B47 新增，用户可改】“历史平均持有天数”的口径**：**按证券计算**，只统计本人在该证券上、最近 365 天已平仓的买入批次（v0.2.9 内，T-O11 评审裁定），FIFO 配对，按数量加权的持有交易日数；该证券少于 3 个已平仓批次视为未知（不封顶、不提示）；细则见 `feature_spec.md` §10.1。需要谁定：用户（产品）、研究员。
77. **【默认执行，T-B47 新增，用户可改】退市整理标记（`risk_flag=delisting`）与 *ST（`risk_flag=star_st`，即“退市风险警示”）都按 ST 处理**：计入 `f.is_st`（措辞更正（v0.2.9 内，T-O11 评审裁定）：原文把 `delisting` 写成“退市风险警示”；结论不变），分类器按风险警示股封顶，宁可少推荐。需要谁定：用户（产品）、研究员。
78. **【默认执行，T-B47 新增，补测后复核】管理端采集状态的告警阈值与数据新鲜度阈值**：见 6.1 `config/realtime.yaml` 的 `admin_alerts` 与契约 §7.9 `/admin/ingest/status`（如盘中实时行情超过 30 秒为 stale、P0 队列等待超过 60/300 秒告警、出现 1 次 IP 超限即严重告警）。需要谁定：运维、用户；T003 实测后调整。
79. **【默认执行，T-B46 新增，用户可改】非可转债持仓缺现价时的展示**：既没有日线收盘价也没有快照参考价时，与可转债行一样按成本估算并标“估算”，市值和盈亏显示“—”，不用其他价格推算。需要谁定：用户（产品）。
80. **【默认执行，前端待定裁定新增，用户可改】计划只有 4 个状态，系统不自动关闭计划**：`active`/`triggered`/`done`/`cancelled`（契约 §3 `plan_status`）；任一条件（含失效条件）满足只置 `triggered` 并提醒，由用户决定新建版本（回到 `active`）或关闭为 `done`/`cancelled`；成交不会自动把计划标为已执行。需要谁定：用户（产品）。
81. **【默认执行，前端待定裁定新增，用户可改】手工计划去重**：同一用户同一证券已有 `active`/`triggered` 且动作相同的计划时，`POST /plans` → `409 CONFLICT{existing_id}`，引导用户修改该计划或先关闭。需要谁定：用户（产品）。
82. **【默认执行，前端待定裁定新增，用户可改】计划与提醒不可删除，提醒状态只能前进**：计划与版本、提醒都没有 DELETE（`405`）；提醒状态 `new`→`read`→`checked`→`acted`/`dismissed` 只进不退，`acted`、`dismissed` 为终态；读取详情不自动标为已读（前端显式 PATCH）。需要谁定：用户（产品）。
83. **【默认执行，前端待定裁定新增，后续版本补充】计划条件类型本版只开放 5 种**：`price_above`、`price_below`、`pct_change`、`date`、`custom`；`indicator`、`event` 的参数与判定尚未定义，写入返回 `400 not_supported`；`custom` 只作文字记录，不自动判定。需要谁定：架构师（后续版本定义参数与判定）。
84. **【默认执行，前端待定裁定新增】登录与注册的 `Origin` 校验**：CSRF 白名单只有 `POST /auth/login`、`/auth/register`；这两个端点带了外站 `Origin` → `403 CSRF_FAILED`，不带 `Origin` 的非浏览器客户端放行（契约 §1.3）。需要谁定：架构师；若以后要支持第三方网页客户端再议。
85. **【默认执行，前端待定裁定新增，用户可改】持仓行业分布的“未分类”**：行业数据接入后，没有行业归属的持仓（可转债等）按成本估算值合并为“未分类”计入 `exposure.sector`，不参与 RC4 行业集中度判断。需要谁定：用户（产品）。
86. **【默认执行，前端待定裁定新增，补测后复核】卖出零股规则**：主板、创业板、ETF 起卖 100、步长 100，科创板起卖 200、步长 1；卖出数量须为全部可卖余量，或不少于起卖量且超出部分为步长的整数倍（科创板余量不足 200 股时只能一次卖完）（契约 §7.7 `lot_rule`）【以交易所规则为准；T-R10 已核对，与规则一致，“余额”按可卖数量判定、整手连带零股不允许属实现约定，见 2.13 交易单位行（v0.2.9 内，T-T25）】。需要谁定：策略研究员。
87. **【默认执行，T-B46-47 前端待定新增，用户可改】持仓估算行的标注与数据状态**：在证券主数据中、但既没有日线收盘价也没有快照参考价的持仓（问题 79），行上只标“估算”（不在主数据中的标“不在主数据·估算”），不细分原因标签，原因写在页面说明里；只要有一行估算，持仓页整体数据状态就显示为“部分缺失”（契约 §7.2 `/portfolio`，v0.2.9 #31）。需要谁定：用户（产品）。
88. **【默认执行，T-B46-47 前端待定新增，补测后复核】管理端采集告警的展示**：同类告警只出一条（不按证书逐张列出，逐张情况看证书列表）；文案固定、不带数值与证书数量；严重在前、警告在后；14 天内到期单列为“有证书即将到期”；不新增心跳时间字段（契约 §7.9，v0.2.9 #31）。需要谁定：运维、用户；T003 实测后与问题 78 一并复核。
89. **【默认执行，T-B46-47 前端待定新增，用户可改】周期评估“数据不足”的显示口径**：某周期因数据缺失被封顶、且没有被硬门槛排除时显示“数据不足”；没有适合周期且至少一个周期“数据不足”时整体显示“数据不足”，否则显示“—”；界面不说“都不适合”（契约 §7.3 `/horizon-assessments`，v0.2.9 #31）。需要谁定：用户（产品）。
90. **【默认执行，T-A04 新增，用户可改】上交所、北交所上线前的曾用名是否从巨潮或 AKShare 回填**：默认**不回填**——这两所的曾用名从上线日起按交易所每日快照比对积累，深交所用官方改名表回填全部历史；巨潮、AKShare 只核对、不写曾用名（4.6.1）。影响：上线前改过名的沪、北交所证券，按旧名搜不到。若改为回填，需标明来源并接受非交易所数据。
91. **【默认执行，T-A04 新增，用户可改】麦蕊有、交易所没有的代码（`vendor_unknown`）能否搜到**：默认**搜不到**——进隔离区，不建档、不生成词条，`/securities/{code}` 返回 404，只在管理端对账页可见（契约 #33）。若改为可搜，需在结果上标“交易所未收录”。
92. **【默认执行，T-A04 新增，用户可改】证券主数据告警发给谁**：默认**只在管理端显示**（`/admin/ingest/status.alerts` 的 `master.*` 键与对账页），不发站内通知、不发邮件，也不告知普通用户。若需要通知，另定渠道与频率上限。
93. **【默认执行，T-R12 新增，用户可改】L-01 线上从麦蕊因子切到自算口径要等多久**：默认按 `feature_spec.md` §7C 执行——自算键与麦蕊因子线上并行至少 3 个月度截面（其中一个在法定披露截止日后），巨潮抽样 30 只全部通过后才切换；等待期内 L-01 线上信号仍用麦蕊因子；切换前已产生的 L-01 信号不重算，只标 `basis=mairui_factor`。影响：切换至少要 3 个月；若用户希望更快切换或要求重算旧信号，需放宽 §7C 阈值（研究员升版本）。需要谁定：用户（产品）、研究员。
94. **【默认执行，架构师 T-F23-24 新增，用户可改】数据证书没填到期日怎么提醒**：用户登记证书时到期日可以不填。默认把“没填到期日”当作“不知道何时到期”，不当作“永不过期”：管理端和“我的数据证书”显示“未填写到期日”，不发“即将到期”提醒，排序排在有到期日的证书之后（契约 v0.2.9 #40）。已过了填写的到期日但证书状态还不是“已过期”时，也不单独提醒，以证书状态为准。影响：没填到期日的证书到期前不会收到提醒；若用户希望对这类证书也定期提醒（例如每月提醒一次“请补填到期日”），需要新增告警键（契约升版本）。需要谁定：用户（产品）。
95. **【默认执行，T-O12 / b195ca6 评审新增，用户可改】主密钥多版本是否作为上线门槛**：默认**是**——上线前由后端完成 T-B57（加密列与 HMAC 列带密钥编号、多钥密钥环、多钥 secret 文件、自检）。理由：上线前没有真实用户数据，现在加列几乎没有成本，上线后再加就要对真实密文做回填迁移；后台重加密 CLI 与轮换流程仍放上线后 V2。影响：**上线推迟约一个后端任务（T-B57）的工作量**。若用户选择不推迟，T-B57 改到上线后，届时要对真实数据做回填迁移。需要谁定：用户（产品）。
96. **【默认执行，架构师 T-R12b 新增，用户可改】L-01 切换到自算口径前，是否必须先核实送转时点（V5d）和财报币种单位（V5h）**：默认**必须**——feature_spec §7C S1 除 V5b、V5c、V5e、V5g 外，还要关闭 V5d、V5h（2.12.1 T-R12b 补充裁定 4）。如果 T-B05 发现 capital 股本行普遍晚于除权日才可见，还要先接入分红送转数据，才能切换。理由：不核实的话，送转后的几天内 PE、PB 会因为价格已除权而股本未更新被低估；个别公司金额单位不一致时，也只能靠数量级检查发现。影响：切换可能在问题 93 的至少 3 个月之外再推迟，推迟多久取决于 T-B05 的结论和接入送转数据的工作量；等待期间 L-01 线上继续用麦蕊因子。若用户接受风险、不等 V5d、V5h，可以从 S1 中去掉这两项，送转检查保持 `share_change_check=unavailable`，自算值在研究报告中单列标注。需要谁定：用户（产品）、研究员。

**I. 编排者默认（2026-11-01 12:32）——【编排者默认，用户可否决】**
- **C(1) 首批 P0 策略**：G-01、G-02、H-01、N-01、T-01、S-01、W-01、W-02、L-01（研究员 `docs/strategies/catalog.md` 第 2 节总表；取代早期方案中 2.5.10 的 ①–⑨ MVP 模板清单）。引擎接口覆盖核对与缺口见 2.5.11A。
- **C(2) S-03**（高风险短线情绪类）：以模板形式随附，但**默认不启用**、不被分类器推荐，`risk_level: high`；手动启用不需要确认，启用开关旁固定展示风险说明（T006e，取代问题 11 的逐项确认）。
- **C(3) H-01 持仓风险监控**：默认挂到**全部持仓**（`strategy_instances.origin=system`、`status=active`），用户可对单只或全部暂停；只产生 weakening/exit_signal（reduce/sell 候选），从不产生买入。
- **C(4) N-01 风险公告否决**：公告数据缺失或过期时，**阻断买入方向的计划草案**，原因码 `KEY_DATA_MISSING`（附缺失字段 `f.ann_risk_count_10d`），解除条件：该字段在新快照中非空**且**公告数据源状态为 `verified_live`（2.5.11A）。卖出方向不受影响。
- **C(5) T-01 做T**：在实测盘中延迟之前**只做盘后统计**：不产生盘中候选信号、草案或通知；盘后按规则统计"当日若执行会触发几次、回补率、扣费后单腿结果"，标为模拟（2.5.11A）。延迟实测达标并经用户确认后才开放盘中。
- **C(6) 内部评估结果的用户可见范围**：放在第三阶段；架构师选择**方案 A**（研究员 validation.md §9.3）：用户只看到"是否做过内部检验（是/否）、方法类型、检验日期"，**不显示任何数值、通过与否或曲线**；数值只在管理端可见。理由：① 告诉用户"这条规则有没有被检验过"符合可解释性原则 P1，方案 B 连这一点也隐藏了；② 不出现数值就不构成"历史业绩展示"，与 7.2 第 5 条一致；③ 与 2.12.4"结果数值永不展示"不矛盾。注意：单用户期间用户本人就是管理员，可以在管理端看到数值；对他人开放后此隔离才真正起作用。
- **C(7) 成本与阈值初值**：冲击成本分档 0/5/15/30/60 bp（2.13；参与率按成交额口径 = 拟成交额 ÷ 近 20 个有效交易日日成交额均值，T-A02 已定）；hold 的"方向正确"阈值 T+5 |超额| ≤ 2%、T+20 |超额| ≤ 5%（2.8）。全部标"初值，待校准"。**T+1 的 hold 阈值【已定 2026-11-01】|超额| ≤ 1.0%**（窗口：盘后生成 → T+1 开盘至 T+1 收盘；盘中生成 → 下一根 1 分钟 bar 开盘至 T+1 收盘；validation.md §7.1A 方案 2）。T+1 停牌、T+1 一字跌停、`forced_hold` 样本不计入 n；首版**只展示、不进健康度**，标“初值，待校准”；累计 n ≥ 30 后由管理员复核分布再决定是否调整。
- **C(8) 数据范围**：V1 不含北交所（`boards.bse=false`）、没有新闻源；N-03（新闻类）在 catalog 中保持**不可运行**（L1 卡片），解除条件按 catalog 第 5 节：用户拍板接入有授权的新闻源（问题 8/9），接入后仍须走 G1–G7。

**后端骨架反馈 T-B01 §4 的处理（2026-11-01，T-A01；契约 v0.2 变更记录“v0.2 补充”为准）**
- 大小写：JSON 键与普通枚举值 `snake_case`；码类取值（错误码、原因码、`IMPORT_*`、`G1`–`G7`）大写。三类码命名空间不重名，CI 检查。
- `DATA_STALE`：原因码保留；HTTP 错误码改名 `503 FRESH_DATA_REQUIRED`。
- 405：新增 `405 METHOD_NOT_ALLOWED`（`Allow` 头）；非管理员访问 `/admin/*` 仍为 404。
- 健康检查：`/health/live`（恒 200，用于容器健康检查）+ `/health/ready`（db/redis 失败 503 `down`；只有 ingest 异常 200 `degraded`）；`/health` 为 ready 的别名。
- ingest 心跳：确认 Redis 心跳 + 120 秒判 stale，键 `ingest:heartbeat`（JSON，含 `ts`）与 `ingest:paused`（契约 §7.10，plan 6.1）。
- `/meta/enums` 外层结构：`{version, enums, reason_codes, error_codes, import_codes, risk_control_labels}`。
- `PENDING_T_A01` 的 21 个枚举取值 v0.2 不变；§3 新增 `health_status`、`component_health`、`ingest_health`、`gap_reason`、`data_provider`、`source_kind`。
- `config/*.yaml` 的文件清单、键与默认值以 6.1 为准；文件由后端创建。（T-A09 更正：原文“五个文件”是 T-A01 时的数目——`realtime`、`ingest`、`market_rules`、`risk_controls`、`horizon_classifier`；之后 6.1 又加了 `llm`、`imports`、`auth`、`securities`（契约 v0.2.7），现共 9 个。）
- 仍需运维决定（不属于契约）：nginx `proxy_pass` 尾斜杠导致 `/api` 前缀被去掉（T-B01 §4.1），建议去掉尾斜杠，保持 `/api/v1`。

**仍待定的问题汇总**：T-A08 问题 51–60 中，51、53 已定（53 已在契约 v0.2.8 同步）；54–57 按默认执行，59 已定（契约 v0.2.9 #30、§7.7B）；52、58、60 暂按默认，补测后复核；T-A09 新增问题 61–65（契约 v0.2.8 未决 U1–U5，均有默认，62、64 补测后复核；63 已定并于契约 v0.2.9 同步）；T-A10 的前端遗留待定项 P01–P21 与测试 T-T23 的三项裁定已在契约 v0.2.9 同步，无新增待定问题；T-A11（研究候选接口）新增问题 66–71、T-F22 管理端证书遗留新增问题 72–74（66–71、74 默认执行，72 已定为 V1 不加（契约 v0.2.9 #30），73 未决；契约 v0.2.9 #19–#26）；T-B46/T-B47 裁定新增问题 75–79（均默认执行，78 补测后复核；契约 v0.2.9 #27）；前端待定裁定新增问题 80–86（均默认执行，86 待研究员核对；契约 v0.2.9 #30）；77/82/85 个因子的口径【待 T003 补测核实】、交易规则 2023-04-10 之前未建模及深交所条款逐字核对（问题 36）；【风险提示，未决】朋友属于第三方：朋友的敏感个人信息、咨询资质、律师书面意见（问题 48；麦蕊再分发改由每人自用证书解决，问题 49）；**麦蕊证书归属、代运营、同 IP 多证书与共享缓存【待麦蕊书面确认】（问题 50）**；（问题 38–42 已于 2026-11-02 作废，见问题 43–47）；DeepSeek：API 数据是否用于训练、保留期限、DPA、实际单价与账单对账【待核实】（问题 16、2.7.1；key 格式官方未公布，已定只校验非空）；麦蕊 licence 的长度与字符集【待核实】（7.4A S1）；到期后是否续费（问题 5，到期前 60 天再定）；交割单撤单/红利/新股行的真实写法（问题 19，待脱敏范本；分红计入摊薄成本已定）；另见 2.5.14 H（续）末尾列出的研究员侧未决项；T-A04（证券主数据与搜索）新增问题 90–92（均默认执行，契约 v0.2.9 #33）。（问题 1 子问题、5、19、33、前端版本、Sentry、GitHub secret scanning，以及 ST 10%、T+1 hold 阈值 1.0%、分红计入摊薄成本已于 2026-11-01 拍板。）
