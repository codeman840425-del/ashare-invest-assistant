# P2N-09 解释生产链金标准扩充集（草稿，T-R27）

> 版本 v1.0 draft｜任务 T-R27｜2026-11-09 北京时间｜维护：策略研究员
> 定位：**AI 解释金标准扩充用例草稿**，纯文档、纯虚构数据。不是可执行 golden（正式派单 P2N-09 时再落成 `P2N-09_golden.json` + `check_P2N-09.py`，届时把本文每例的 `input`/`candidate`/`expected` 三段迁入 JSON，并新增校验器）。
> 关系：R09（67 例，`golden/P2N-R09_golden.json`）测的是「六维证据→中文解释」的**文本正确性**（引用/数字/主体/动作/禁词/分歧/故障守卫）。**本扩充集测的是「解释生产链」的链路语义**——缓存命中、回退枚举、缺键 null 不显示、llm_call_id 鉴权边界、模板非 AI 边界、逐股/分歧绑定、以及免责的逐字渲染位置。两者互补，不重复。
> 依据：`docs/api-contract.md` §7.11.4（全文）；`reports/T-A36.md`（P2N-05i ①–③ + R09 065–067）；`reports/T-A37.md`（P2N-05i 评审 I1–I3）；`golden/P2N-R09_README.md`（schema 与五类回退/三档置信口径）；`cards/hold_risk_monitor.md` §规则摘要（反证不抵消、结论只由规则决定）；`compliance/disclaimer.md`。
> 边界：所有样例 `fictitious=true`，证券 `999001.SZ`/`999002.SZ` 为合成占位；不新增任何 API 字段、枚举、拒绝码；`fallback_reason` 五值、`Explanation` 结构、`llm_call_id` 鉴权均照抄契约既有，不创设。

---

## 0. 术语与权威口径（本扩充集复用，不新定义）

| 术语 | 契约出处 | 本扩充集怎么用 |
|---|---|---|
| `Explanation` 结构 | §7.11.4 第 1295 行 | `{source, text, paragraphs:[TextWithEvidence], prompt_version, validation_status, fallback_reason, llm_call_id}` |
| `TextWithEvidence` | §5.2/§7.11.4 | `{text, expr:null, evidence_ids[]}`；text 为各段换行拼接 |
| 五档回退 `explanation_fallback_reason` | §7.11.4 第 1298 行第 2 点 | `not_enabled` / `budget_exceeded` / `timeout` / `provider_error` / `validation_failed` |
| `llm_call_id` 鉴权 | §7.11.4 第 1299 行第 3 点 | 仅管理员显示；有 `/admin/llm/usage` 页才显示链接，否则管理员只读 id；非管理员不显示 |
| 缺键/键缺失 | §7.11.4 第 1297 行第 1 点 | `explanation` 为 `null` 或键缺失 → 该位置**不显示解释**，不复用顶层，不按证据推断归属 |
| 模板非 AI 边界 | §7.11.4 第 1295 行 | 模板兜底 `source=template`、`validation_status=fallback`、`llm_call_id=null`（未调用时）；"模板不标 AI 生成" |
| 数字约定 | §7.11.4 第 1300 行第 4 点 | ROUND_HALF_UP、`min_decimals`(默认2)、万/亿精确换算、"约/近/超过"不放宽 |
| 动作词无白名单 | §7.11.4 第 1301 行第 5 点 | 任何动作词（含对规则动作的转述）→ 拒绝回落模板 |
| 禁用词无例外 | §7.11.4 第 1302 行第 6 点 | 禁用词出现即拒绝，不论否定/引号/免责语境；固定免责由系统在 LLM 之外追加 |
| 三档置信 | plan §2.5.4 / phase2 | `confidence∈[0,1]`：high≥0.7、medium≥0.4、其余 low；本轮链路上 `confidence` 属 protected_result，解释不得改写 |

---

## 1. 扩充集覆盖矩阵（生产链验收点）

| 编号段 | 生产链验收点 | 用例数 | 关键断言 |
|---|---|---|---|
| C01–C06 | **逐股/分歧绑定**（§7.11.4 第1点） | 6 | stocks[]/divergence[] 各带本项 explanation；null/缺键不显示；不复用顶层；不跨对象引证据 |
| C07–C11 | **五档回退枚举**（§7.11.4 第2点） | 5 | fallback_reason 五值各一例；passed→null、fallback→非空；not_enabled/budget 时 llm_call_id=null；旧档缺键只显示模板兜底不猜原因 |
| C12–C14 | **llm_call_id 鉴权**（§7.11.4 第3点） | 3 | 仅管理员显示；有 usage 页才链接；非管理员不显示 id |
| C15–C17 | **缺键 null 不显示**（§7.11.4 第1点兜底） | 3 | explanation=null ／ 键缺失 → 位置空；不按 evidence 推断归属；不 fallback 到顶层 |
| C18–C20 | **模板非 AI 边界**（§1295） | 3 | source=template 必 fallback、llm_call_id=null、不标 AI；llm 成功必 source=llm/passed |
| C21–C23 | **缓存/回退一致性**（§7.11.4 第1303+本节扩展） | 3 | 解释在提交前定稿；fallback 不改规则结论；缓存命中复用、不重复 LLM 调用 |
| C24–C26 | **免责逐字渲染**（§1302 第6点 + disclaimer） | 3 | 免责由系统追加、不经 LLM、不计入守卫；自写免责 → fallback；固定文案逐字一致 |

> 26 例，全部虚构。R09 已有 65–67 覆盖纯文本动作词/禁词/数字守卫细节，本扩充集 C24–C26 只补「免责**渲染位置与逐字一致**」这一链路维度，不重复 R09 的守卫拒绝逻辑本身。

---

## 2. 通用输入形状（本扩充集所有用例共用）

以下为「解释生产链」的输入载体，与 R09 的 `input` 不同点在于——**本扩充集测的是 production 链路的 `Explanation` 对象本身**，所以：

- `production_link`（新增测试元数据，非 API）：描述链路上下文（`daily_report_stock` / `strategy_divergence` / `suggestion` / 缓存命中 / 未调用）。
- `request`：伪造的「要解释的对象」形状（逐股/分歧/顶层），标明该对象是否带 `explanation` 键、键值是否为 `null`、是否缺键。
- `rendered`（期望）：前端渲染结果的抽象投影（哪一层显示、显示什么、是否显示 llm_call_id）。
- 除 C12–C14 外，`viewer_role`（`admin`/`user`）固定为 `user`。

```yaml
# 模板：不落 JSON，仅示意本扩充集每例的字段形状
- id: Cnn
  desc: 【纯合成】……
  fictitious: true
  viewer_role: user | admin
  link: daily_report_stock | strategy_divergence | suggestion
  input:
    # 被解释对象的视图层形状（不含解释正文，正文由 LLM/template 产出后填入）
    evidence: [ {id, key, value, unit, provider: system, epistemic_type: hypothesis} ]
    protected_result: {action, score, confidence, stops}
    enabled_strategies: [ {strategy_key, card_version, lifecycle, state, action, score, confidence, rule_refs:[…]} ]
    # 生产链上下位：缓存命中？是否调用？调用是否失败？
    chain: { cache_hit: bool, invoked: bool, llm_call_id: string|null, budget_ok: bool, configured: bool }
  candidate: …      # LLM 产物（或 null，表示未调用）
  expected:
    explanation: …  # 生产 Explanation 对象投影
    render: …       # 前端渲染投影（哪层显示、显示与否、显示内容子集）
    verdict: accepted | rejected
```

> 说明：这里 `chain.cache_hit / invoked / configured / budget_ok` 都是**测试夹具字段**，用于表达"生产链状态"，不新增 API 字段；真实链路里这些由 `fallback_reason` + `llm_call_id` 反推。判定标准（§4）也只断言最终 `Explanation` 与渲染投影，不断言内部 cache 表结构。

---

## 3. 26 例（每例：输入形状 + 期望输出 + 判定标准）

### 3.1 C01–C06 逐股/分歧绑定

**C01｜逐股 explanation 独立存在，只引本证券证据**
- 输入：`DailyReport.stocks[0]`（`security_code=999001.SZ`）带 `explanation`（llm 成功）；`stocks[1]`（`999002.SZ`）无 explanation。顶层无 explanation。
- 期望：stocks[0].explanation.source=llm、paragraphs 内 evidence_ids 只含 `999001.SZ` 前缀的日报证据（如 `D1_1`）；stocks[1].explanation=null。
- 判定：stocks[0] 正常显示；stocks[1] 不显示；顶层无复用；（引用跨证券 → rejected，finding=`cross_object_citation`）。

**C02｜分歧项各自 explanation，不合并**
- 输入：`Suggestion.divergence[]` 两项，各带 explanation（H-01 减仓理由 + W-01 持有理由），引用各自维度证据。
- 期望：两项 explanation 各自 paragraphs 只引本项 `dimensions` 相关 evidence；text 各表一方，不含"综合/净"结论。
- 判定：两项分别显示；无 `strategy_merge`（合并→rejected）。

**C03｜explanation=null → 位置空，不复用顶层**
- 输入：某股 `explanation: null`，但顶层存在别的 explanation。
- 期望：该股位置渲染空（无解释块）；前端不把顶层 explanation 复制到该股位置。
- 判定：渲染结果该位置无 text（rejected 若复用顶层）。

**C04｜键缺失 → 位置空，不按 evidence 推断归属**
- 输入：某分歧项**无** `explanation` 键（缺键，非 null），但有本项 evidence。
- 期望：该位置不显示；前端不得"因为它有 evidence 就自己生成/推断一段解释"。
- 判定：位置空（rejected 若推断现身）。

**C05｜逐股只引该证券，杜绝跨对象证据 ID**
- 输入：stocks[0] 的 explanation 引了 `999002.SZ` 的 evidence id。
- 期望：守卫拒绝 → 该股回落模板（source=template, fallback_reason=validation_failed）。
- 判定：finding=`cross_object_citation`，explanation 落模板。

**C06｜分歧引用限于该 dimensions，多引 → 拒绝**
- 输入：divergence[0]（技术维度）引用了 news 维度证据。
- 期望：拒绝回落模板，finding=`citation_fact_mismatch`（跨维度）。
- 判定：同 C05。

### 3.2 C07–C11 五档回退枚举

**C07｜not_enabled（未调用）**
- 输入：路由未配置，未调 LLM；无 candidate。
- 期望：`{source: template, validation_status: fallback, fallback_reason: not_enabled, llm_call_id: null}`；语义同无解释（位置可显示"模板兜底"或空，按前端 I2）。
- 判定：fallback_reason=not_enabled 且 llm_call_id=null。

**C08｜budget_exceeded（预算超限）**
- 输入：预算不足，未调用。
- 期望：`fallback_reason: budget_exceeded`, `llm_call_id: null`, template。
- 判定：同 C07，reason=budget_exceeded。

**C09｜timeout（超时，已调用）**
- 输入：已调用、有 llm_call_id 记录、超时无产物。
- 期望：`fallback_reason: timeout`, `llm_call_id` **非空**（有调用记录）。
- 判定：reason=timeout 且 llm_call_id≠null。

**C10｜provider_error（供应商错误，已调用）**
- 输入：已调用、供应商报错、无产物。
- 期望：`fallback_reason: provider_error`, `llm_call_id` 非空。
- 判定：同 C09。

**C11｜validation_failed（守卫拒绝，已调用）**
- 输入：已调用、有 candidate 但守卫拒绝（如出现动作词）。
- 期望：`fallback_reason: validation_failed`, `llm_call_id` 非空（有调用记录），template。
- 判定：reason=validation_failed；（passed 时 reason 必 null——反向用例可加 C11b：passed 却带非空 reason → rejected）。

### 3.3 C12–C14 llm_call_id 鉴权

**C12｜非管理员不显示 llm_call_id**
- 输入：`viewer_role=user`，explanation 带 `llm_call_id`（有值）。
- 期望：渲染不含 llm_call_id。
- 判定：投影渲染键集合不含 llm_call_id（出现 → rejected，finding=`llm_call_id_leak`）。

**C13｜管理员无 usage 页时只读显示 id**
- 输入：`viewer_role=admin`，无 `/admin/llm/usage` 页（MVP 未建）。
- 期望：渲染以**纯文本**显示 id，不生成链接 `/admin/llm/usage?call_id=`。
- 判定：显示 id 字符串、无 href（生成链接 → rejected，finding=`link_without_usage_page`）。

**C14｜管理员有 usage 页时显示深链**
- 输入：`viewer_role=admin`，有 usage 页。
- 期望：渲染链接 `/admin/llm/usage?call_id={id}`。
- 判定：href=该链接（错误路由/自拼 → rejected）。

### 3.4 C15–C17 缺键 null 不显示

> C15–C17 是 C03/C04 在「顶层 suggestion/daily_report」层级上的补充，聚焦"缺键 null 与 '0' 的区分"。

**C15｜explanation 键存在但值 null vs 键缺失，二者渲染一致**
- 输入：对象 A 带 `explanation: null`，对象 B 无该键。
- 期望：两者渲染一致（都不显示解释），前端不区分 null 与缺键。
- 判定：渲染结果一致（一处显示一处不显示 → rejected）。

**C16｜不因 evidence 存在而推断归属**
- 输入：对象有 evidence 但无 explanation（键缺失）。
- 期望：不显示解释；前端不以 evidence 数量/维度生成占位解释。
- 判定：位置空。

**C17｜顶层 explanation 存在时，也不能当子对象兜底**
- 输入：`DailyReport.explanation`（顶层）有值，但某 `stocks[]` 项 explanation=null。
- 期望：该 stocks 项不显示；顶层解释独立显示在顶层位置。
- 判定：分层独立，无级联 fallback。

### 3.5 C18–C20 模板非 AI 边界

**C18｜模板兜底不得标 AI 生成**
- 输入：fallback（任意 reason）。
- 期望：`source=template`、`validation_status=fallback`；渲染不得出现"AI 生成/AI 分析"字样。
- 判定：source=template 且正文无"AI 生成"标签（出现 → rejected，finding=`template_claimed_as_ai`）。

**C19｜LLM 成功必 source=llm + passed + llm_call_id 非空**
- 输入：已调用成功、candidate 通过守卫。
- 期望：`{source: llm, validation_status: passed, fallback_reason: null, llm_call_id: 非空}`。
- 判定：四键同时成立（任一不满足 → rejected）。

**C20｜未调用时 llm_call_id 必 null（template/not_enabled）**
- 输入：not_enabled（未调用）。
- 期望：llm_call_id=null。
- 判定：null（伪造 UUID → rejected，finding=`fabricated_call_id`）。**注：R09 已用 llm_call_id=null 表预算/PII 未调用，此例把"未调用必 null"升为链路级断言。**

### 3.6 C21–C23 缓存/回退一致性

**C21｜缓存命中不重复调用，解释复用**
- 输入：同一对象（同 evidence/protected_result 哈希）第二次请求，`chain.cache_hit=true`、`invoked=false`。
- 期望：第二次 explanation 与首次逐字节相等（含 llm_call_id 复用原值）；不新产生 llm_call_id。
- 判定：两次 explanation 哈希相等；（新 llm_call_id → rejected，finding=`duplicate_llm_call`）。

**C22｜fallback 不改规则结论**
- 输入：LLM 超时回落模板，但规则结论（action/score/confidence/stops）已定。
- 期望：explanation=template，但 protected_result 与规则产出**逐字段不变**（与 R09 protected_result 不变量同源）。
- 判定：protected_result 不变（改 → rejected，finding=`protected_result_mutation`）。

**C23｜解释在提交前定稿，提交后不异步改**
- 输入：`committed=true`，且有人试图改写 interpretation 正文。
- 期望：拒绝改写，正文不可变；需改则生成新 revision。
- 判定：改写 → rejected，finding=`immutable_snapshot`（同 R09）。

### 3.7 C24–C26 免责逐字渲染

**C24｜固定免责由系统追加，LLM 文本之外、不计入守卫**
- 输入：LLM candidate 通过守卫（无禁词），系统把固定免责追加到其外。
- 期望：最终展示 = LLM 正文 + 系统固定免责；守卫只审 LLM 正文，不审系统免责。
- 判定：免责文案与 `compliance/disclaimer.md` **逐字一致**（差一字 → rejected，finding=`disclaimer_text_mismatch`）。

**C25｜LLM 自写免责 → 拒绝回落模板**
- 输入：candidate 段落里含"本工具仅供个人研究参考…"（LLM 自写免责）。
- 期望：守卫拒绝 → 回落模板（source=template, fallback_reason=validation_failed）；系统免责**仍**追加在模板外（不因 LLM 自写跳过追加）。
- 判定：fallback + 系统免责仍逐字追加。

**C26｜免责不经 LLM，模板兜底也带同款免责**
- 输入：fallback（模板兜底，未调用 LLM）。
- 期望：模板正文 + 系统固定免责逐字一致显示。
- 判定：免责文案逐字一致（与 C24 同一来源、同一渲染逻辑）。

---

## 4. 判定标准（每例通用，落 JSON 时做成校验器断言）

1. **结构判定**（确定性，可机器查）：`Explanation` 的 `source/validation_status/fallback_reason/llm_call_id` 四键组合是否落在合法集合内（见 §0 表）；`paragraphs[].evidence_ids` 是否只指本对象 evidence（逐股＝该证券前缀、分歧＝该 dimensions）。
2. **渲染判定**（抽象投影）：按 `viewer_role` 和"有无 usage 页"，断言 llm_call_id 是否显示/链接；断言 null/缺键位置是否空白。
3. **文本判定**（复用 R09 守卫 + 链路增生）：
   - 数字：ROUND_HALF_UP + min_decimals(2) + 万/亿精确换算，约字不放宽（§1300 第4点）。
   - 动作词：无白名单，转述也拒绝（§1301 第5点）。
   - 禁词：否定/引号/免责语境无例外（§1302 第6点）。
   - 免责：逐字比对 `compliance/disclaimer.md`，由系统追加、不计入守卫、模板兜底也追加。
4. **不变量判定**（复用 R09）：`protected_result`（action/score/confidence/stops）不因解释路径改变；引用 ID 本对象存在；不新增 subject/维度/策略；分歧两方各自保留、不合成。
5. **语义判定**：与 R09 同，`semantic_review` 逐句人工式审阅并绑定文本哈希；结构化守卫抓不到的新语义（如"缓存命中却改了措辞"）必须重审。**机械通过不代表新文本语义合格。**

---

## 5. 哪些例需要真实数据（留 P2N-09 正式派单用）

> 本扩充集 26 例全部**纯虚构可离线测试**（缓存/回退/鉴权/绑定/模板边界都可用合成 evidence + 伪造链路状态表达，不依赖真实账户或麦蕊）。以下**链路字段**在正式派单时需真实环境才能验证其生产行为，标注如下，勿在草稿阶段假设已在生产成立：

| 例 | 需要真实数据的点 | 为什么草稿阶段不测 |
|---|---|---|
| C21 缓存复用 | 真实缓存键 = `(user, 对象哈希, prompt_version)` 的实际落库与命中；需真实 DB + ingestion | 当前只有合成回放，`chain.cache_hit` 是伪造字段 |
| C12–C14 llm_call_id | `/admin/llm/usage?call_id=` 真实端点 + 管理员会话 `origin=password_login` | 鉴权页面/usage 端点生产未接线（T-A18/T-A20 会话门槛） |
| C09/C10（timeout/provider_error） | 真实 LLM 供应商超时/报错路径（DeepSeek 真实调用） | 草稿只能用合成 `chain` 状态表达，不做真实外呼 |
| C23 提交前定稿 | 真实「解释生成→提交正文」时序与 revision 生成 | 依赖生产建议/日报不可变正文链路 |
| C24–C26 免责 | 真实前端渲染免责的位置与逐字（`disclaimer.md` 当前版本文本已在仓库，文本可比对，但"由系统追加、位置在 LLM 外"需真实渲染联调） | 文本可比对，渲染位置需前端联调 |

> 结论：**守卫逻辑（数字/动作/禁词/绑定/鉴权投影）可离线测**；**生产链时序（缓存命中、供应商超时、usage 深链、提交时序）须真实数据**，正式派单时单独圈出、不冒称离线通过。

---

## 6. 与 R09 的关系与边界（避免重复与冲突）

- **不重复**：R09 67 例已覆盖文本守卫细节（引用/数字/主体/动作词/禁词/六维/分歧/故障终态/065-067），本扩充集**不重写这些**，只新增 §1 表的链路维度。
- **不冲突**：本扩充集沿用 R09 的 `Explanation`/`TextWithEvidence` 投影、`protected_result` 不变量、`finding` 夹具字段（不新增 reject_reason 枚举）；`finding` 名沿用 R09 已有（`cross_object_citation` 等为校验器内部名，非 API）。
- **正式化路径**：P2N-09 派单时，把本文 §3 每例迁入 `P2N-09_golden.json`（补 `source_registry`/`finding_source_map`/`semantic_review`），新增 `check_P2N-09.py`（比照 `check_P2N-R09.py` 的确定性 guards + 链路投影）；届时 §5 的真实数据例标注 `blocked`，等生产链路可测再转 `ready`。
- **不越权**：不预判 P2N-09 后端实现的关键字/缓存表结构；`chain.*` 是测试夹具字段，不要求后端照搬；`llm_call_id 鉴权`、`usage 深链` 均照契约既有，不新增。

---

## 7. 自检与交付边界

- 本草案**纯文档**，无 JSON golden、无 checker、无网络、无麦蕊、无真实账户；`fictitious=true`，证券 `999001.SZ`/`999002.SZ` 合成占位。
- 术语、枚举、字段名逐条对照契约 §7.11.4 与 T-A36/T-A37 原文；无新创设字段（测试元数据 `chain.*`、`viewer_role`、`link`、`render` 均标注"非 API"）。
- 未完项留 P2N-09 正式派单：§3 每例的 `candidate` 逐字文本与 `semantic_review` 逐句审阅（需照 R09 绑定哈希）、`check_P2N-09.py` 确定性校验器。
