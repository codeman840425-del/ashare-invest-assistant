# 前端待定项架构裁定（v0.2.9 内，契约变更表 #30）

- 依据：`T-A10-frontend.md` 待定 1–9、`T-F23.md` 待定 1–7、`csrf-frontend.md` 遗留、plan 第 9 节问题 59 / 72
- 文档提交：**66f0c79**（只本地提交，未推送；pathspec 只含 `docs/api-contract.md`、`docs/plan.md`）
- 契约版本号不变（v0.2.9）。**变更表行号是 #30，不是 #29**：写入前 T-O11 评审裁定提交 e56462c 已占用 #29（“风险标记含义与 ETF 回转”）。
- plan 第 9 节：59、72 改为已定；新增问题 80–86（T-O11 没有新增编号，接在 79 后面）。
- 检查：`check_contract.py` 通过；`check_code_namespaces.py` 通过（error 59 / reason 22 / import 46 / gate 7）；`contract_md.enums()` 共 84 个，相对 HEAD~ 只多了 `plan_status`、`plan_condition_type`，其他枚举没变；gitleaks 8.30.1 扫描范围 `HEAD~1..HEAD` 命中 0（gitleaks_report.py：命中 0）。提交前对两份文件做的 dir 扫描有 10 条 S7 命中，全部来自原有文字，与 HEAD 版本逐条相同。
- 注意：带 `--meta-json` 的 `check_contract.py` 要等后端把两个新枚举加进 `/meta/enums` 才能通过（见后端待办 B1）。

## 1. 问题 59：`/plans`、`/alerts` 结构（契约 §7.7B、§7.7、§7.8、§3）
**结论**：结构已定，并新增两个枚举。
- 计划状态 `plan_status` 为 `active`/`triggered`/`done`/`cancelled`。任一条件（含失效条件）满足 → `triggered`；新建版本 → 回到 `active`；关闭 → `done`/`cancelled`，二者是终态；系统不自动关闭计划（问题 80）。
- `plan_condition_type` 沿用 plan 3.3 的 7 个值，本版只开放 price_above、price_below、pct_change、date、custom。indicator、event → `400 not_supported`；custom 不自动判定（问题 83）。
- 对象：`PlanSummary`、`Plan`（含 `current_version`、`version_count`、`pending_triggers`、`evidence`）、`PlanVersion`（不可变）、`PlanCondition`。`TodayPlanTrigger` 是 `pending_triggers` 的同源子集。
- 列表默认 `active,triggered`，可传 `all`，排序 `created_at desc, id desc`。
- 手工创建支持 Idempotency-Key：指数 → 400；`candidate_id` 非 null → 400；同证券、同动作已有 active/triggered 计划 → `409 CONFLICT{existing_id}`（问题 81）。
- 新建版本：需带 `base_version_no` 和 `change_reason`（1–200）。终态 → `409 INVALID_STATE_TRANSITION{allowed:[]}`；版本过期 → `VERSION_CONFLICT`。
- close → `200 Plan`；终态再关闭 → 409。PUT/PATCH/DELETE → 405。
- `Alert` = TodayAlert 加上 checklist、snapshot_id、handled_at、evidence，并且包含 origin=plan_condition 的提醒。
- `GET /alerts` 默认 `new,read`，排序 `triggered_at desc, id desc`。
- `PATCH /alerts/{id}`：状态只能前进，`acted`/`dismissed` 是终态；改成当前状态 → 200；其余（含回到 new）→ 409。读详情不自动标为已读。POST/DELETE → 405（问题 82）。
- `/alert-rules` 结构不在本次范围。
- plan 3.3 `action_plans.status` 已同步为这 4 个值。
- 前端：新建计划列表/详情/新建/改版/关闭页和提醒列表/详情页；“查看全部”接到这两个页；提醒在点开后显式 PATCH `read`；按 §7.7B 写 mock，405 带 Allow 头。
- 后端：实现 §7.7B 全部端点和两个状态机；两个新枚举加进 `/meta/enums`；迁移 action_plans.status 的取值；条件满足时置 triggered、写 `origin=plan_condition` 提醒、发 SSE `plan_triggered`；新建版本清空 pending_triggers。

## 2. 问题 72：管理端证书列表服务端筛选
**结论**：V1 不加；`?status=&q=` 仍被忽略（与 §9 T-F22 第 2 条一致），前端保留“继续加载 + 40 页上限”。注册用户超过 200 或碰到 40 页上限时，再开后续任务。
- 前端：不改。
- 后端：不改。

## 3A. T-A10 前端待定 1–9
1. **事件 cause**：信号创建事件 `from=null`、`cause=executability_check`；→drafted、确认、忽略都是 `user`。前端：mock 和时间线文案按此改。后端：创建事件写 executability_check，→drafted 写 user。
2. **STRATEGY_CONFLICT 证据**：每个对方信号一条 Evidence，`key="signal.conflict_signal_id"`（保留键，不进 feature_catalog）、value 为对方信号 uuid、provider=system、epistemic_type=fact。前端：Conflicts 改为读这些 evidence，不再按方向推测（评审 7a3e9cb m4）。后端：照此写入。
3. **可转债/无行业持仓**：行业数据接入后合并为 `exposure.sector` 的 `{name:"未分类", pct}`，不参与 RC4（问题 85）；接入前仍按 T-O11 处理，sector 为未知/空。前端：分布图显示“未分类”。后端：聚合时补这一桶，RC4 跳过它。
4. **instance_id 一句作废**：PlanDraft 没有 instance_id，策略经 signal_ids 取得。前端：删掉相关字段/文案。后端：无。
5. **lot_rule 结构**：`400 VALIDATION_ERROR{fields:[{field:"chosen_qty", issue:"lot_rule", min_buy, step}]}`，min_buy、step 放在 fields 元素里（修正 #14 的写法）。前端：从 `details.fields[i]` 读。后端：改响应结构。
6. **400 先于 409**：`POST /plan-drafts` 方向不同 → 400；信号同向但带 STRATEGY_CONFLICT → `409 SIGNAL_NOT_EXECUTABLE`。前端：mock 先判 400。后端：校验顺序按此。
7. **卖出零股规则**：卖全部可卖余量，或数量 ≥ min_buy 且 (数量 − min_buy) 是 step 的整数倍。主板、创业板、ETF 是 100/100，科创板是 200/1。【以交易所规则为准，研究员核对；问题 86】前端：lotWarning 加科创板（评审 7a3e9cb m3）。后端：校验照公式；研究员核对规则。
8. **问题 73（审计日志查询）**：仍未决，不在本次范围。
9. **#26⑤ 通知 mock**：前端补管理员暂停证书的通知 mock（kind=data_licence、target none、正文不含理由）。

## 3B. T-F23 待定 1–7（研究候选，契约 §7.7A“v0.2.9 #30 补充”）
1. 建议不存在或不属于本人 → `suggestion_id not_found`；可见但证券不符 → `security_code mismatch`。前端/后端：按此区分。
2. 从建议复制的条目 epistemic_type=fact、source_kind=system_calc，按 (text, expr) 去重，保留首次出现的位置，evidence_ids 取并集。后端实现，前端 mock 跟上。
3. `fit_assessment.hints` 由服务端生成（规则同 /horizon-assessments），前端不拼接。
4. 本版仍不会出现 `planned`，`plan_ids=[]`。
5. `POST /candidates/{id}/versions` 也支持 Idempotency-Key（同键同体回放，同键异体 → 409 IDEMPOTENCY_CONFLICT）。前端：改版时带幂等键。后端：实现。
6. 证书不可用时照常生成：`data_status=stale`，gaps 带 `{key:"data_licence", reason:"data_licence_unavailable"}`，不报错。
7. 入口反查用默认状态（不含 dropped），放弃后可以重新加入。

## 4. CSRF 登录前白名单（契约 §1.3）
**结论**：白名单只有 `POST /auth/login` 和 `POST /auth/register`。其他所有写请求都要校验，含 logout、password、multipart 上传和 /admin/*。白名单外的写请求如果没有会话 → `401 AUTH_REQUIRED`。白名单内的两个端点额外校验 Origin：外站 Origin → `403 CSRF_FAILED`，不带 Origin 的放行（问题 84）。收到 `403 CSRF_FAILED` 时提示刷新，不自动重试。
- 前端：mock 的豁免列表要和白名单完全一致，并断言其他无会话写请求返回 401（评审 0e31218 m1）；补 /auth/password 的 mock（m2）；加刷新提示（m3）。
- 后端：给 login 和 register 加 Origin 校验（站点源取自部署配置）；确认 logout 校验 CSRF。

## 5. 判定顺序（契约 §1.3）
**结论**：
1. 413（中间件）
2. 路由 404/405
3. `/admin/*` 不是管理员 → 404；没有会话 → 401；账号未批准 → 403 ACCOUNT_NOT_APPROVED
4. 403 CSRF_FAILED（白名单端点改为校验 Origin）
5. 503：register 的 REGISTRATION_CLOSED（先于 Origin 校验和请求体解析，#16 不变）；无请求体的 /me/data-licence/test 的 MAINTENANCE
6. 400 请求体（PUT/PATCH /me/data-licence 的 MAINTENANCE 在这之后，#18 不变）
7. 各端点自己的 404 归属 → 409 状态 → 业务错误

429 保持各端点原有规定。请求体解析不能先于第 3、4 步：未登录发非法 JSON → 401，已登录缺 CSRF 发非法 JSON → 403。
- 前端：mock 按这个顺序。
- 后端：**要核实** FastAPI 是否在依赖之前解析 JSON 体。若是，需要把认证和 CSRF 放到中间件或前置依赖，或者对请求体做延迟解析；并补 §9 #30 验收第 1、2 条的测试。

## plan.md 改动（已在 66f0c79 中）
- 3.3 action_plans.status 改为 active/triggered/done/cancelled
- 问题 59、72 标为已定，写明结论
- 新增问题 80–86：计划状态与不自动关闭、手工计划去重、计划与提醒不可删且提醒状态只进不退、条件类型只开放 5 种、登录与注册的 Origin 校验、“未分类”、卖出零股规则
- 更新汇总段

## 待办汇总
**前端**
1. 计划页、提醒页按 §7.7B 实现，同时写 mock。
2. 事件 cause 的 mock 和文案。
3. Conflicts 改为读 `signal.conflict_signal_id`。
4. 显示“未分类”。
5. 删去 instance_id。
6. lot_rule 改从 fields[] 读。
7. plan-drafts mock 先判 400。
8. 科创板 lotWarning。
9. #26⑤ 通知 mock。
10. 研究候选改版时带 Idempotency-Key，mock 处理 mismatch/not_found。
11. CSRF mock 的白名单和 401 断言，/auth/password 的 mock，403 时提示刷新。
12. 错误顺序的 mock。

**后端**
1. B1：`/meta/enums` 加 plan_status、plan_condition_type（加上后 `check_contract.py --meta-json` 才能通过）。
2. /plans、/alerts 全部端点和状态机；迁移 action_plans.status。
3. 条件满足时置 triggered，写提醒，发 SSE。
4. 事件 cause 的写法。
5. conflict evidence。
6. exposure 的“未分类”桶，RC4 跳过它。
7. lot_rule 响应结构和卖出公式。
8. plan-drafts 400 先于 409。
9. 研究候选：版本幂等、hints、去重、stale gap、not_found/mismatch。
10. login 和 register 的 Origin 校验。
11. 核实并保证认证和 CSRF 先于请求体解析，补测试。
12. 研究员核对卖出零股规则（问题 86）。
