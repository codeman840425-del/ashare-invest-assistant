# T-B03c：邀请码（契约 v0.2.3 #27、§7.9；plan §3.3 / §6.1 invite.*）

**结果：已完成。提交 `3834925`，只在本地，未 push。**

本任务从停车区 `/tmp/park/T-B03c` 恢复，迁移改号为 **0008**（down_revision 0007）。管理员鉴权直接复用 T-B45 已提交的 `current_admin` / `AdminDep`：停车区里那段完全相同的代码没有再合进来。

## 内容
- **`app.invite_codes` 表**
  - 只存 `HMAC-SHA256(APP_MASTER_KEY, 归一化码)`，明文不入库。
  - V1 每个码只能用一次（`max_uses=1`，有 CHECK 约束）。
  - active / used / expired / revoked 四种状态由字段推导，不物理删除。
- **`POST /auth/register`**
  - `closed` 模式仍然一律返回 503。
  - `invite` 模式下 `invite_code` 和 `apply_note` 必填。邀请码不存在、过期、已用、已吊销、绑定的用户名不符，统一返回 `400 VALIDATION_ERROR invite_code invalid`。
  - 先占用邀请码再查重名：没有有效邀请码的人无法借此探测用户名是否存在。占码用条件 UPDATE 防并发重复使用；之后任何失败都会让整个事务回滚、撤销占用。
  - 写审计 `user.registered`（带 invite_id）和 `invite.redeemed`。
- **`/admin/invites`**
  - `GET` 分页列表，不含明文或摘要。
  - `POST` 只在 201 响应里出现一次明文 `code`；`ttl_h` 默认 168、最大 720。
  - `DELETE /admin/invites/{id}` 吊销邀请码；已用或已吊销的返回 409 `INVALID_STATE_TRANSITION`。
  - 非管理员一律 404，所有操作写审计。
  - 与其他管理员路由一样设了 `include_in_schema=False`，不出现在公开的 openapi.json 里，避免 schemathesis `--checks all` 失败（原因见 T-B04a 报告）。

## 验证
- 隔离库上迁移 0008 升级 → 降级 → 再升级都正常。
- 自测：`selftest_tb03c` 57/57。旧的“OpenAPI 含 /admin/invites”检查已改成“OpenAPI 不含”。
- `selftest_tb16` 123/123：去掉了“invite 模式 → 503”这条，因为该功能已经实现。
- 其他自测全部通过。
- tester 套件：531 passed / 240 skipped / 0 failed。
- ruff 和 mypy 都没有报错。

## 需要别人做的
- **运维**：部署前执行 `alembic upgrade head`（迁移 0008）。是否把 `registration_mode` 切到 `invite` 由产品决定，V1 默认仍是 `closed`。
- **前端**：注册页在 invite 模式下要求填写申请说明；管理端新增邀请码页，明文只展示一次。
- **架构/文档**：`/admin/*` 不在公开 OpenAPI 里，契约 §7.9 需要保持为管理端接口的唯一说明。
- **tester**：邀请码的并发使用、绑定用户名不符、吊销后不能再用，这几种情况可以补用例。
