# T-F23-24 契约缺口裁定（架构师）

- 提交：`0edb298`（仅 docs/api-contract.md、docs/plan.md；本地提交，未推送）
- 契约版本仍为 v0.2.9；变更表新增 #37–#40；**未新增枚举，enums 仍为 86**，CI 脚本无需改。
- 检查：check_contract.py rc=0；check_code_namespaces.py rc=0；gitleaks dir docs：no leaks found。
- plan §9 新增：问题 94（默认执行，用户可改）。

## 裁定

1. **#37 plan-drafts 的 blocked 信号**：矛盾在 §7.7：#30 写的是“因 STRATEGY_CONFLICT 处于 blocked 时**才是** SIGNAL_NOT_EXECUTABLE”，而同一格旧句“状态不是 drafted/released → INVALID_STATE_TRANSITION”把全部 blocked 都归为 INVALID_STATE_TRANSITION。前端第 9 项取了两者之间的折中。裁定以 #30 为准，并推广到所有情况：只要是 blocked 或有 active 原因（不论原因码）→ `409 SIGNAL_NOT_EXECUTABLE`；`INVALID_STATE_TRANSITION` 只用于终态。open、released、drafted 都可以拟定草案。七步判定顺序见 §7.7：格式 400 → 归属 400 not_found（不返回 404）→ 同证券同动作 400 → STRATEGY_VERSION_NOT_RUNNABLE → 终态 INVALID_STATE_TRANSITION → SIGNAL_NOT_EXECUTABLE → 422。§6.0 状态机格已加注。
2. **#38 心跳**：`/admin/ingest/status` 顶层新增 `heartbeat: ingest_health`，复用已有枚举，不为 null，判定与 `/health/ready.ingest` 相同。仍不返回心跳时间（#31 ⑤ 不变）。字段缺失或取值无法识别时，前端按 unknown 显示“无法判断”。heartbeat 告警只由服务端生成。
3. **#39 master.\***：message 由服务端按固定表生成，前端原样显示，不按 key 映射。5 条文案已改为面向普通用户的说法。排序：critical 在前；同级内 #31 ② 的键排在前，master.* 排在后，5 个键之间按 ⑥ 所列顺序。
4. **#40 days_left 为 null**：null 表示用户没有填写到期日，不表示永不过期。此时不出 licence.expiring，也不出其他到期类告警，排序排在后面。显示规则：null 显示“未填写到期日”，负数显示“已过填写的到期日”，0 显示“今天到期”，正数显示“还剩 N 天”。产品层面的取舍记为 plan §9 问题 94。

## 前端待办（可直接转发）

按契约 v0.2.9 #37–#40 修改：
1. plan-drafts mock（planHandlers.ts）：删掉“只有 STRATEGY_CONFLICT 返回 SIGNAL_NOT_EXECUTABLE”的分支，任何 blocked 信号或有 active 原因 → 409 SIGNAL_NOT_EXECUTABLE，reason_ids 为请求中全部信号的 active 原因（去重，按 id 升序）；只有终态信号（confirmed/dismissed/expired/invalidated/superseded）返回 INVALID_STATE_TRANSITION（allowed:[]）；open 信号允许拟定草案（返回 201，信号变为 drafted）；不存在或不属于本人的 id 返回 400 VALIDATION_ERROR fields[{field:"signal_ids",issue:"not_found"}]，不返回 404；判定顺序按 §7.7 七步执行。同步修改 review-b23401a、T-F23 的相关用例。
2. 管理端采集状态：读取 `heartbeat`（ok/stale/paused/unknown），分别显示“正常/心跳超时/已暂停/无法判断”；字段缺失或取值无法识别时按 unknown 显示；不要根据它自己生成告警。setMockIngestHeartbeat 改为写这个字段。
3. 告警：所有 alerts[].message（含 master.*）原样显示，不按 key 映射，key 不认识也照样显示。mock 使用 §7.9 ⑥ 的 5 条新文案，并按 #39 排序。
4. 证书 days_left / days_to_expiry：null 显示“未填写到期日”，负数显示“已过填写的到期日”，0 显示“今天到期”，正数显示“还剩 N 天”；null 不告警，这一点保持现状。

## 后端待办（可直接转发）

按契约 v0.2.9 #37–#40 实现：
1. POST /plan-drafts 按 §7.7 七步顺序判定，每一步检查完全部信号再进入下一步：格式 400 → 不存在或非本人 400 not_found（不返回 404）→ 同证券同动作同 t_leg 400 → simulating 模板 409 STRATEGY_VERSION_NOT_RUNNABLE → 终态 409 INVALID_STATE_TRANSITION{from,to:"drafted",allowed:[]} → blocked 或有 active 原因 409 SIGNAL_NOT_EXECUTABLE{reason_ids}（不论原因码，以库中原因为准，去重后按 id 升序）→ 422 PLAN_REQUIRES_EXPLAINABLE_SIGNAL。open、released、drafted 可以拟定草案（cause=user）。
2. /admin/ingest/status 顶层加 `heartbeat: ingest_health`，不为 null，与 /health/ready 共用同一个判定函数；不返回心跳时间字段。
3. master.* 的 5 条 message 改用 §7.9 ⑥ 的新文案（T-B53）；同级排序为 #31 ② 的键在前、master.* 在后，master.* 之间按 ⑥ 所列顺序。
4. days_left 为 null 时不出 licence.expiring，也不出其他到期类告警，并补测试。验收按 §9 “v0.2.9 验收（#37–#40）”第 1–4 条执行。

## 附注（未改，供编排者知悉）
- plan §2.5.8（约第 709 行）仍写着“open 经检查后进入 drafted 或 blocked”，与 #30（→drafted 由用户触发）不一致。另一个会话可能正在改 plan.md，这次只新增了问题 94，没有改动那里，建议由负责 plan 的会话统一修改。
