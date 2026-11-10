# 策略卡晋级门槛：L1 知识卡 → L2 可运行策略模板 验收清单

> 版本 v1.0｜任务 T-R24｜2026-11-09 北京时间｜维护：策略研究员
> 依据：`docs/handover/team/vision.md`《策略卡字段定稿》（用户 11:52，L56/L58/L60–65/L77）；`docs/plan.md` §2.5.0A、§2.5.0B、§2.5.13、§2.5.14；裁定 T-A03、T-R15、T-A13、T-R18、T-R19、T-R20、TB-A48、T-A14（plan §2.5.13 内）。
> 定位：**判定标准，不是回测报告，也不是 G7 批准**。研究员的勾选只算"文档预检"；能否晋级以后端 G1–G6 实跑结果 + G7 人工审核为准（T-R20 ②）。本清单不改变任何既有裁定；与既有裁定冲突或未定的口径集中列在 §7，提交架构师。
> 不适用范围：`kind: code` 的代码策略（须另走代码评审，本清单的 G3/G4 不适用）；`published` 发布门槛（见 S-04，属晋级之后的另一道关）。

---

## 0. 怎么用、怎么判

1. 每张待晋级卡复制 §8 的记录表，按 P → F → G → S/M 的顺序逐条勾选；**不允许跳项**。
2. 判定状态只有四种，必须写明依据：
   - `[x] 通过`：本项目满足，且证据可点开（文档行号、裁定条号、脚本输出、报告路径）。
   - `[ ] 不通过`：不满足；卡片留在 L1，系统 `gates_missing[]` 会显示缺哪一关（plan §2.5.0B，§2.5.14 G）。
   - `[ ] 未执行`：引擎尚未实跑或报告缺失；**未执行不等于通过**。
   - `[-] 不适用`：只允许两种情形——已登记的裁定豁免（§6 M / T-A03、T-R15 ②），或该关对本卡类型本就不适用（如择时卡的选股项）；**必须写豁免依据**。
3. 六段勾选全部通过（含"不适用"均有依据）后，才可提交 G7；G7：系统内置/共享模板按 T-A109 程序——策略研究员逐条核对 → 架构师复核 → 编排者在用户本人授权覆盖该卡前提下以管理员可信交互会话代批并留证（前提：缺证据项为 0 且 G1–G6 结论齐备；每次代批须引用一条覆盖该卡的用户本人授权）；用户私有模板仍由用户本人确认（plan §2.5.0B G7、§2.5.13 G7、`docs/reviews/T-A109-g7-delegation.md` §2）。
4. 晋级后的状态只有 `simulating` 一个去向（S-01）；**"晋级"不等于"发布"**。

---

## 1. 前置：文件与导入格式（P）

导入器只认机器可读块，解析失败不会部分导入（plan §2.5.14 A）。

- [ ] **P-01** 一张卡一个文件；有且只有一个 `yaml strategy-card` 块；`strategy-spec`、`validation` 各 0–1 个。
  - 证据：plan §2.5.14 A；`_template.md` §0.1。
- [ ] **P-02** 幂等键 `key + version_no` 合规；同一 `key` 改内容必须递增 `version_no`，已发布版本不可改。
  - 证据：plan §2.5.13 / §2.5.14 A。
- [ ] **P-03** 正文说明可自由写，作为 `narrative` 原样保存；机器判定只读三类块。
  - 证据：plan §2.5.14 A。
- [ ] **P-04** 文档内无真实账户、股东代码、真实持仓、金额或交割单；示例证券只用 `600000.SH` 一类虚构代码，夹具数值全部虚构。
  - 证据：plan §2.5.14 A；`_template.md` §0.1。
- [ ] **P-05** 字段名、枚举、结构以 plan §2.5.14 B 为准；vision 定稿多出的字段存入 `extra` 并在详情页展示，不因"模板没写"而丢字段。
  - 证据：vision L77；plan §2.5.14 G（"字段范围"行）。
- [ ] **P-06** `[SYS]` 字段（`completeness`、表现记录、运行态、复盘、`gates_missing[]`）不得在文档中填写，填了也被忽略。
  - 证据：plan §2.5.0A（系统字段）、§2.5.14 B、G。

---

## 2. 必填字段：10 项（F1–F10）

> 晋级勾选按 T-A69/Q-R31 计 F1–F10 共 10 项（含导入必填 F9 `epistemic`、条件必填 F10 `mount_policy`）。与 plan §2.5.0A「核心 8 项」及 vision 定稿的对应见 §2.1；字段名与格式仍以 plan §2.5.14 为准。

- [ ] **F1 身份**：`key`（`^[a-z][a-z0-9_]{2,40}$`，全站唯一）、`name`（≤30 字）、`category`、`version_no`（整数 ≥1）。
  - `category` 取值 `trend / momentum / reversal / breakout / value / quality / dividend / low_vol / event / intraday_t / risk`；纯离场/风控组件用 `risk`（T-R15 ②）。
  - 证据：plan §2.5.0A 必填 1；§2.5.14 B；T-R15 ②。
- [ ] **F2 适用周期**：`horizons[]` 非空，取值 `intraday_t / short / swing / long`。
  - 多周期卡允许写多个值；**不得把数组第一个元素当默认周期**；新多周期正式卡另见 M-07。
  - 证据：plan §2.5.0A 必填 2；P2N-R10；TB-A48 R6。
- [ ] **F3 假设**：`hypothesis.why_it_works`（一句可检验的机制陈述）+ `hypothesis.falsified_by[]`（≥1 条，可观测、可量化，写明哪种证据能否定该假设）。
  - 证据：plan §2.5.0A 必填 3；`_template.md` §3。
- [ ] **F4 维度与角色**：`dimensions[]` 每项 `{dimension, role}`；`dimension` 取六维之一，`role` 取 `core / auxiliary / veto`；不用的维度不写。
  - 证据：plan §2.5.0A 必填 4；§2.5.1 维度枚举。
- [ ] **F5 成立条件**：`entry[]` ≥1 条，每项 `{text, expr|null, status}`；L2 阶段 `status` 只能是 `quantified`。
  - 例外：`mount_policy=system_only` 且规则只含 weakening/exit/counter/invalidation 的纯离场组件（目前仅 H-01）可豁免 `entry[]`（T-A03、T-R15 ②）；**豁免不等于放宽其他字段**。
  - 证据：plan §2.5.0A 必填 5；§2.5.14 B/C；T-A03；T-R15 ②。
- [ ] **F6 反证与失效**：`counter_evidence[]` ≥1 条、`invalidation[]` ≥1 条，格式同 F5；卡片列表项用 `ref` 指向 `rules[]` 中角色相容的规则，两边 `expr` 去空白后必须一致。
  - 证据：plan §2.5.0A 必填 6；§2.5.14 B；§2.5.14 H①（`ref` 规则）。
- [ ] **F7 退出规则**：`exit[]` ≥1 条，且至少一条止损类；止损/止盈/时间止损/跟踪止盈写在 `stops{stop_loss, take_profit, time_stop_days}` 与 exit 规则中。做 T 卡必须有"当日回补或时间止损"。
  - 证据：plan §2.5.0A 必填 7；§2.5.14 B/C；G1。
- [ ] **F8 数据需求**：`data_needs[]` 每项 `{feature_key, frequency, adjust, available_at}`；`feature_key` 必须在 `feature_catalog` 内，未登记的先写 `validation.feature_requests[]`；`frequency ∈ 1m/daily/quarterly/event`、`adjust ∈ none/qfq/hfq`；分钟线只能 `none`。
  - 证据：plan §2.5.0A 必填 8；§2.5.14 B；`_template.md` §5。
- [ ] **F9（导入必填，计入 10 项）认识论标注**：`epistemic{field_path: fact|estimate|hypothesis}`，至少标出 `hypothesis` 与各条阈值参数的类型。
  - 证据：plan §2.5.14 B（`epistemic` 行）。
- [ ] **F10（条件必填，计入 10 项）挂载策略**：纯离场/风控组件写 `mount_policy: system_only`；普通模板 `user`（默认）；`system_only` 不得含 buy/add。
  - 证据：plan §2.5.14 C（T-R15 ②）；T-A03。

### 2.1 8 必填与 vision 定稿字段的对应

| vision 定稿字段组（L61） | 本清单落点 | 说明 |
|---|---|---|
| 身份 | F1 | 必填 |
| 来源 `sources[]` | 选填（plan §2.5.14 B） | 有来源必须写 `license_status`，CC BY-NC/AGPL/无许可证只能 `idea_only` |
| 假设 | F3 | 必填 |
| 标的范围 | 选填/L2 | 选股型在 `universe`/`screen` 写；不写不阻断 |
| 数据 | F8 | 必填 |
| 选股 | L2 `screen` | 择时卡写 `screen: null` |
| 入场 | F5 | 必填 |
| 退出 | F7 | 必填 |
| 仓位 | 选填/L2 `risk_suggestions`/`position` | 引用 RC1–RC6，取与用户设置更严者 |
| 验证（区间/基准/成本/样本外/交易明细） | `validation` 块（G6 输入）+ `validation_summary`（展示） | 产品不做回测，见 plan §2.11；没做写"未验证" |
| 运行 / 复盘 | SYS | 由系统回填，不填 |
| 表现记录 | SYS | 不填 |

> 说明：vision L77 已拍板"必填 8 项作为晋级门槛"；plan §2.11 把完整字段表简化为"8 必填 + 选填 + 系统字段"，两者不冲突。字段覆盖以 vision 为准，字段名与格式以 plan §2.5.14 为准（`_template.md` 开头）。

---

## 3. 晋级关卡 G1–G7（逐关可勾选）

> 方式：G1–G6 自动检查（引擎/worker），G7 人工。研究员的勾选是预检，**以引擎实跑结果为准**（T-R20 ②）。

### 3.1 G1 规则完整且可解释（自动）

- [ ] **G1-01** 入场、失效/退出、止损三类规则**全部已量化**，不存在 `status: to_quantify`；纯离场组件按 T-A03 豁免后，其余规则仍须全部量化。
- [ ] **G1-02** `horizons[]` 声明的每个周期至少有一条 exit 规则；多周期卡的勾选口径见 M-02。
- [ ] **G1-03** 做 T 卡有当日回补规则或时间止损。
- [ ] **G1-04** 至少 1 条 `counter`（反证）规则。
- [ ] **G1-05** 每条规则都能产出 `rule_refs` 和 `evidence`：`rule_id`、`role`、`dimension`、`passed`、`value`、`threshold`、`evidence_ids[]`；阈值有确定数值，不是"待定"。
- [ ] **G1-06** 卡片列表与规则规格一一对应：`ref` 存在且角色相容（entry→entry，counter→counter，invalidation→invalidation，exit→exit/hold/weakening）；两边 `expr` 一致；省略 `expr` 时由规则复制。
- [ ] **G1-07** 纯离场豁免仅当同时满足：`mount_policy=system_only`、规则角色只含 weakening/exit（可另有 counter/invalidation）、至少 1 条 exit 或 weakening、1 条 counter、1 条 invalidation、`action_map` 不含 buy/add；不满足即 `CARD_IMPORT_INVALID`。
  - 证据：plan §2.5.0B G1；§2.5.14 B/C；§2.5.14 H①；T-A03；T-R15 ②；T-A14 ③（G1 段）。

### 3.2 G2 数据可得（自动）

- [ ] **G2-01** 每个 `data_needs.feature_key` 都在 `feature_catalog` 白名单内；`required_features` 同。
- [ ] **G2-02** 每个字段的来源状态不是 `gap`；至少 `verified_doc`。只到 `verified_doc` 的卡最多晋级到 `simulating`；`verified_live` 是 `published` 的必要条件。
- [ ] **G2-03** 字段状态以 `feature_spec` 为唯一来源，`T-R18_source_matrix.yaml` 只是证据，`current_status` 必须与 feature_spec 一致（T-R19 ①）；`T-R18` 的 PIT 限定、单位缺口照记。
- [ ] **G2-04** feature 元数据里的 null 不单独阻断 G2（T-A13）；不得因"元数据没写"就降级或绕过。
- [ ] **G2-05** 预热窗口不足时输出 `insufficient_data`，**不算 G2 失败**；但要在 G6/G7 报告里如实记"未体检/覆盖不足"。
- [ ] **G2-06** 卡内特征 `adjust` 与 `feature_catalog` 一致；1m 特征只写 `none`；价格规则只用 `_qfq` 版本（T-R15 ⓪）。
  - 证据：plan §2.5.0B G2；§2.5.13 G2 段；T-R18/T-R19/T-A13/T-R20 ②；T-R15 ⓪。

### 3.3 G3 语法安全与 DSL 合规（自动）

- [ ] **G3-01** 所有 `expr` 能解析为 AST，只含白名单字段、运算符、函数：比较、`and/or/not`、`+ - * /`、`ma/ema/atr/highest/lowest/ref/cross_up/cross_down/between/rank_pct/pct_change`，含 H⑤ 新增 `max2/min2/std/ts_pct_rank/rank_pct_in`；`for N days`/`within N days`。
- [ ] **G3-02** 表达式 ≤300 字符、嵌套深度 ≤6；无变量赋值、循环、属性访问、IO、任意代码。
- [ ] **G3-03** 每个规则项有 `eval_time ∈ daily_close/intraday_1m/event`（§2.5.14 G 采纳为必填）。
- [ ] **G3-04** 无未来函数：规则在时点 t 只用 `available_at ≤ t` 的数据；日线信号最早 T+1 09:30 执行；盘中只用已收完的 1 分钟 bar；公告/财报/龙虎榜按次一交易日 09:30 起可见。
- [ ] **G3-05** 价格口径不混用：`plan.*`/`ctx.*` 的不复权价不得直接与 `*_qfq` 序列比较；止损/止盈用 qfq@T 算出的价格可直接展示。
- [ ] **G3-06** `ctx.*`/`plan.*` 只出现在 hold/weakening/exit 规则（例外：只依赖时钟的 `ctx.now_hhmm`）。
  - 证据：plan §2.5.0B G3；§2.5.14 C（DSL）；§2.5.14 H⑤/⑰；T-R15 ⓪；`_template.md` §7.2。

### 3.4 G4 参数 schema（自动）

- [ ] **G4-01** `params_schema` 每个参数有 `type/default/min/max/step/说明`；`default ∈ [min, max]`；类型严格（不得用字符串表示布尔/数字）；enum 有 `choices`。
- [ ] **G4-02** `user_editable=false` 的参数在 L3 不允许改参；L3 改参越界生成派生版本（I4）。
- [ ] **G4-03** 规则里引用的参数都已定义；`p.` 前缀与参数名一致。
  - 证据：plan §2.5.0B G4；§2.5.14 D；§2.5.0C I4。

### 3.5 G5 可交易性与 A 股约束（自动）

- [ ] **G5-01** 自动挂载通用闸门 `gate_tradability`。
- [ ] **G5-02** 止损/止盈价限制在当日涨跌停价范围内；涨跌停价按有效规则版本（主板 10%、创业板/科创板 20%、北交所 30%、ST 按 2026-07-06 分段）。
- [ ] **G5-03** 按 T+1 处理可卖数量：买入当日不可卖，最早下一交易日；做 T 需底仓，无底仓 `NO_POSITION`、可卖不足 `T1_NOT_SELLABLE`。
- [ ] **G5-04** 一字涨停不可买、一字跌停不可卖（`LIMIT_LOCKED`）；停牌 `SUSPENDED`；盘中数据缺失时一律不产生 sell/reduce。
- [ ] **G5-05** 首版不含北交所（plan §9 C(8)）；涉及北交所的卡记"暂不可执行"，不得默认纳入。
- [ ] **G5-06** 交易单位：买入 100 股整数倍；科创板 ≥200 股后 1 股递增；零股卖出一次性申报。
  - 证据：plan §2.5.0B G5；§2.5.11；`market_rules_check.md`；T-R15 ⑤/⑩；`_template.md` §17。

### 3.6 G6 历史体检 + fixtures + 配额（自动，只读）

- [ ] **G6-01** `validation.fixtures[]` ≥6 个，且覆盖六类场景：满足、不满足、缺数据、维度分歧、涨跌停或停牌、做 T 无底仓（非做 T 卡用"可卖为 0 时出现卖出信号"替代）。
- [ ] **G6-02** fixtures 全部通过（期望 `state/action/rule_ids_passed/reason_codes` 逐项比对）；任一失败 G6 记 `fail`，不是警告。
- [ ] **G6-03** 最近 120 个交易日指标宽表上只统计触发频率与覆盖率：触发率 >30% 股票-日或为 0 时警告；不计算收益、胜率、夏普。
- [ ] **G6-04** 与已有模板命中集合的 Jaccard >0.9 视为重复；`max_jaccard` 无值时按契约返回 `null` + 原因码 `no_history`/`no_comparable_set`，G6 至多 `warn`（T-A17）。
- [ ] **G6-05** 数据不足 120 日时如实记"未体检/覆盖不足"警告，不编造统计；不单独导致 `fail`。
- [ ] **G6-06** 配额增量在 `per_minute_budget` 余量内；含待落地特征时 `quota_delta_per_min` 为 `null`，G6 至多 `warn`（T-A21）。
  - 证据：plan §2.5.0B G6；§2.5.14 E；§2.5.13 G6 段；T-A17；T-A21。

### 3.7 G7 人工审核 + 合规文案（人工）

- [ ] **G7-01** 审核页并排展示卡片原文与规则的逐条对应，以及 G1–G6 报告。
- [ ] **G7-02** 系统内置/共享模板：策略研究员逐条核对 → 架构师复核 → 编排者在用户本人授权覆盖该卡前提下以管理员可信交互会话代批，并在决定批注与审计中留证（引用用户原话或指向 T-A109 与授权日期、日期、覆盖卡片）；代批前提为缺证据项为 0 且 G1–G6 结论齐备（无 fail，warn 均已 ack）。据 T-A109 §1 引用，当前书面授权字面仅覆盖 H-01、S-01；其他卡（含 W-01）须有覆盖该卡的用户本人新授权，或用户确认改为长期授权（未决）。用户私有模板仍由用户本人确认。2026-11-09 13:12:55 那次代批不作晋级依据（T-A109 §3）。脚本与未获授权代理不得代填密码或代点批准。
  - 历史：T-R24 时原文为「首批卡（H-01、W-01）由用户本人以管理员身份逐条核对后批准，代理不代批（T-A14 ③）」；T-A109 后现行条款见上。
- [ ] **G7-03** 合规文案通过禁用词校验："推荐、建议买入、立即买入/卖出、必涨、稳赚、保证、目标价、金股、牛股"等不得出现；同屏展示反证与失效条件与固定免责声明。
  - 证据：plan §2.5.0B G7；§2.5.13 G7（T-A109）；§7.2；§2.5.14；T-A14 ③；`docs/reviews/T-A109-g7-delegation.md`。

---

## 4. 晋级后的状态与限制（S）

- [ ] **S-01** 通过 G1–G7 后只进入 `simulating`；**不进入 `published`，不手动设 `observing`**（T-A14 ②③）。
- [ ] **S-02** 卡片继续作为该模板的说明页（L1）；版本不可变，实例只引用具体版本；用户改参生成私有派生版本。
- [ ] **S-03** `gates_missing[]` 由系统按 G1–G7 结果计算，研究员不填写；不通过时卡片留在 L1 并显示缺哪一关。
- [ ] **S-04** `published` 另需：模拟样本 n≥20 或满 20 个交易日、必需字段全部 `verified_live`、管理员批准；`observing` 只由 published 健康度下降自动进入，`retired` 只由管理员确认（plan §2.5.13）。
- [ ] **S-05** 旧版本信号按当时版本原样回看；退役卡历史不回写。
  - 证据：plan §2.5.0B / §2.5.13；T-A14 ②③。

---

## 5. 单卡记录表（复制到卡或报告）

| 项 | 状态（通过/不通过/未执行/不适用） | 证据与说明 |
|---|---|---|
| P-01 … P-06 |  |  |
| F1 … F10 |  |  |
| G1-01 … G1-07 |  |  |
| G2-01 … G2-06 |  |  |
| G3-01 … G3-06 |  |  |
| G4-01 … G4-03 |  |  |
| G5-01 … G5-06 |  |  |
| G6-01 … G6-06 |  |  |
| G7-01 … G7-03 |  |  |
| S-01 … S-05 |  |  |
| M-01 … M-08 |  |  |
| 结论 |  | 全部通过才可提交 G7 |

> 记录表之外的说明文字不参与判定；每格的证据必须能定位（文件行号/裁定条号/脚本输出/报告路径）。

---

## 6. 多周期卡专项（H-01 类，M）

- [ ] **M-01** 多值 `horizons[]` 可进 L1/L2；已有 H-01 保持四值，**不因实例单值出 v3**，不把数组第一个当默认（TB-A48 R1/R6）。
- [ ] **M-02** G1-02"每个周期至少一条 exit"的勾选口径：按"每条 exit 规则对声明的每个周期都适用"判定；若某周期不适用，须逐条写理由与替代退出规则。该口径待架构师确认（§7 Q-01），确认前不得静默跳过。
- [ ] **M-03** 实例层 horizon 是单值：系统挂载 H-01 新实例传 `swing`（合法且与卡片 20 日证伪窗口一致）；不得改卡片周期、不得每周期建一个实例。
- [ ] **M-04** 多周期版本的 RC5 第二级回退不可解析：`version_horizon` 必须传 `None`；结论缺 horizon 时保持跳过 + `sim_fail_horizon_unknown`，**不得回填 swing、不得取数组首元素**（TB-A48 R3）。
- [ ] **M-05** `valid_until` 卡片显式配置优先：H-01 为 1 个交易日，不套用 swing 默认 5 日（TB-A48 R5）。
- [ ] **M-06** 已存在的系统实例不回溯改写 horizon；暂停/恢复不改实例 horizon（TB-A48 R2）。
- [ ] **M-07** 新写的多周期正式卡（H-01 以外）在晋级前必须先取得架构师裁定（唯一版本周期或结论绑定语义），不得沿用 TB-A48 R1 的 swing 例外；无裁定时本关记"未执行/阻塞"（TB-A48 R6）。
- [ ] **M-08** Phase 2 解释、前端展示、T+1/5/20 跟踪不因多周期改动：信号 horizon 取实例值，跟踪三窗口照常（TB-A48 R4）。

---

## 7. 与既有裁定的冲突 / 待架构师裁定（不自行改口径）

> 以下只登记，不改变现行实现；请编排者转架构师。确认前，本清单按"就高不就低、无裁定即阻塞"执行。

- **Q-01（G1 多周期 exit 语义）**：plan §2.5.0B G1 要求"每个周期至少一条 exit"，但 H-01 是四周期单套规则；TB-A48 未规定"按周期分别有 exit"还是"单条 exit 对多周期通用"。建议按 M-02 的"适用性"口径，请架构师确认。
- **Q-02（T-A14 内部表述）**：T-A14 ③ 写"G1–G7 全部要通过，一项都不豁免或放宽"，同条又承认 H-01 享受 G1 豁免（T-A03/T-R15 ②）。两者字面冲突，建议改为"除已登记的 T-A03/T-R15 角色型豁免外不额外放宽"。请架构师确认表述，不改豁免本身。
- **Q-03（新多周期卡可否晋级）**：plan §2.5.0B 允许多值 `horizons[]` 的模板；TB-A48 R6 要求未来正式卡先由权威规格定唯一版本周期或结论绑定语义。两者对"新多周期卡能否直接晋级"未合流。本清单按 M-07 阻塞，请架构师定口径。
- **Q-04（已知文档不一致，仅登记）**：`catalog.md` 的"可运行初判=可"（如 W-01）与 T-B80 实测"H-01/W-01 G2 继续 fail、仍 draft"不一致；catalog 是研究初判，**不是晋级证据**，以 G2/G6 实跑与 `gates_missing[]` 为准。建议后续同步 catalog 措辞，不影响本清单判定。

---

## 8. 证据来源索引

| 来源 | 覆盖内容 |
|---|---|
| vision.md L56/L58/L60–65/L77 | 三层结构、字段定稿、必填 8 项作为晋级门槛 |
| plan §2.5.0A | 8 个必填字段；系统字段不填 |
| plan §2.5.0B | G1–G7 定义与方式 |
| plan §2.5.0C | 实例化 I1–I7（晋级后的下游要求） |
| plan §2.5.13 | 生命周期 draft/simulating/published/observing/retired；T-A14 裁定 |
| plan §2.5.14 A–H | 文档格式、必填字段、DSL、参数 schema、验证块、对接流程、模板兼容、H 节细则 |
| plan §2.11 | 字段表简化为 8 必填的理由；验证延后 |
| T-A03 | 纯离场组件 G1 豁免（entry/止损） |
| T-R15 | 价格口径⓪、`action_map`、`category: risk`、`mount_policy`、夹具 schema、停牌/涨跌停等 |
| T-A13 | feature 元数据 null 不影响 G2 |
| T-R18 / T-R19 / T-R20 | 字段状态来源、`verified_doc`/`verified_live`、G2 不放宽、研究预检 vs 引擎实跑 |
| TB-A48 | 多周期挂载/回退/`valid_until`/新卡裁定要求 |
| T-B80 | G1–G6 执行现状：H-01/W-01 G2 未过、仍 draft、G7 未执行 |
| `_template.md` / `catalog.md` / `P2N-R10` | 字段写法、研究初判、多周期不默认口径 |
