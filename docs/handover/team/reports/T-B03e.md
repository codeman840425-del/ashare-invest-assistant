# T-B03e 报告（契约 67d123a v0.2.8 补充裁定 #17，验收 11/12；含 T-B16-core-r2）

提交（仅本地，未 push）：
- **be607b3**：T-B03e 本体（#11 重复暂停幂等、#12 冷却中删除后重提不跳过冷却，迁移 0012）
- **8fd9502**：T-B16-core-r2（评审 45589c2 修复，按 plan §7.3/§3.3 8a760d1），细节见 reports/T-B16-core.md「r2」一节

## 1 管理员重复暂停幂等（验收 #11）
- `_admin_transition`：用户已有暂停记录（即使证书行已删除）→ admin pause 返回 **204**，不再返回 409；不写新的审计记录，也不写新的 data_licence_events 事件。
- 证书行已是 paused_by_admin 但没有暂停记录（旧数据）→ 204，补写暂停记录，不写审计。
- 未暂停且未设置证书 → 仍为 409 NOT_SET。用户不存在 → 仍为 409。
- 已同步更新 selftest_tb45：重复暂停不再期望审计条目，期望审计 = `["data_licence.paused","data_licence.resumed"]`。

## 2 冷却期内删除后重提（验收 #12，T-B04a-x）
- 冷却状态（quota_exceeded / ip_limited / active 且 paused_until 未到期）下执行 DELETE 时，写入 `app.user_data_licence_cooldowns`（迁移 0012，新表；每个用户一行，删除用户时 CLI 会一并删除）。
- 写入内容：带密钥的指纹，以及删除前的 status、paused_until、错误码、失败次数。
- 指纹算法为 `HMAC(HKDF(APP_MASTER_KEY, info="data-licence-cooldown-fp-v1"), uid‖0x00‖licence_hmac)`：
  - 按用户区分，依赖主密钥，不等于去重 HMAC；
  - 指纹和响应里都不出现明文证书。
- 到期前 PUT 同一证书 → 返回 202，恢复删除前的状态和 paused_until，不入队验证，并取出删除这条冷却记录。
- PUT 不同证书或已过 paused_until → 照常 pending_verification 并验证，冷却记录作废。
- 非冷却状态下 DELETE 不留冷却记录。其他用户提交同一证书不继承冷却。

## 3 开关关闭时
GET 200、DELETE 204、PUT 503 MAINTENANCE，与原行为一致（自检已覆盖）。

## 4 T-B16-core 评审项（M1/M2/M4、data_snapshots）
已并入 r2（8fd9502），具体如下：
- account_reviews.reason 一律置 NULL；
- llm_calls 共享行清空 request_body、response_body、request_hash 和 validation_errors，独占行物理删除；
- data_snapshots 加 user_id 和 licence_id，按这两列物理删除；user_id 为空的快照如果提到该用户，执行前会被阻断。

证据见 T-B16-core.md 的 r2 一节。

## 自检（隔离库 be-b03a-pg / Redis be-b03a-redis；未调用麦蕊）
- selftest_tb03e **61/61 PASS**：覆盖 #11（含证书已删后再暂停、第三次暂停）、#12 的四种冷却状态（含无到期时间）、到期后重提、四种非冷却状态、跨用户、指纹带密钥且按用户区分、暂停优先、开关关闭时的行为，以及库内无测试证书明文。
- 全量回归（8fd9502 之后）：tb03c 57、tb45 67、api 205、tb16 123、xff 21、tb03a 39、t006e、env、tb04ax 114、tb02x 61、tb02y 86、tb03d 67、m1_0009 17、tb16core 93、tb03e 61，**全部 PASS**。
- tester 套件：579 passed，274 skipped，2 xfailed（均为前端项）。
- ruff、ruff format --check、mypy（77 个文件）通过。
- alembic upgrade head → check → downgrade 0012 → upgrade → check 全部干净（0012 的往返测试此前已做过）。

## 与 67d123a 的差异
无。补充说明：重复暂停时连 data_licence_events 事件也不写（裁定只要求不写审计），这样完全幂等。

## 谁要做什么
- 运维：在共享库执行迁移 0012、0013（0013 的角色和授权 SQL 见 T-B16-core.md 的 r2 一节）。
- 测试：alembic head 期望改为 0013；#11、#12 可按 selftest_tb03e 的场景转成正式测试。

## 追加 A（08:21，架构师裁定 T-T23 #1）——提交 f72b8c7
- `registration_mode=closed` 时 `POST /auth/register` 一律 `503 REGISTRATION_CLOSED`，先于请求体校验，任何请求体都一样（`{}`、畸形 JSON、数组、多余字段、空体、text/plain）。
- 实现：`app/api/v1/auth.py` 新增依赖 `require_registration_open`，挂在路由 `dependencies=[...]` 上，在请求体模型之前求值。FastAPI 在求值依赖之前就会解析 JSON，所以对无法解析的 JSON，单靠依赖仍然会先返回 400。为此 `/auth/register` 改用专门的 `register_router`（路由类 `_RegistrationGateRoute`），在解析请求体之前调用同一个判定。`app/api/v1/__init__.py` 挂载该 router。openapi 不变（requestBody 仍在）。
- open/invite 模式下行为不变：畸形请求体仍然先返回 400 VALIDATION_ERROR。
- 裁定 #2（证书设置开关关闭 → 503 MAINTENANCE）按裁定保持不变，未改动。
- 自检：`/tmp/tb02/selftest_tb03e_reg.py`，13/13 通过（closed 模式 6 种请求体都返回 503，响应带 charset；open 模式 6 种都返回 400；openapi 中仍有 requestBody）。selftest tb03e 61/0、tb03a 39/0、tb16core 93/0 均通过。selftest_api 只有 1 项失败：“meta version == contract v0.2.9”。原因是 docs/api-contract.md 已升到 v0.2.9，而后端仍是 v0.2.8，按指示不预先跟进。
- 测试：`test_auth_t_b03.py::test_register_closed_rejects_even_malformed_body_with_503` 带有 `xfail(strict=True)`。这次修复后它会 XPASS，严格模式下会判为失败，需要测试去掉这个 xfail。本地这条当前被 skip（需要 DB fixture），所以没有观察到。
