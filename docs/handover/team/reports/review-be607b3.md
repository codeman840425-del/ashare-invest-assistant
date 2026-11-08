# 评审报告：be607b3（T-B03e，#17：管理员暂停/恢复幂等、删除后重提冷却保持、迁移 0012）

- 评审对象：`be607b3`（父提交 `85e9b70`，2026-11-02 07:41 UTC+8，仅本地）
- 依据：docs/api-contract.md v0.2.9 第 42 行（#26 ① resume 幂等、⑤ 通知）、第 61 行（#13 删除后重提不能跳过冷却）、第 776 行（DELETE：指纹只保留到 paused_until 为止）、第 997 行（未暂停且未设置 → 409 NOT_SET）；本次评审裁定（重复 pause 幂等 204 不写审计；冷却期内删后重提同一证书恢复 status/paused_until 并 202；resume 写 from=to 审计记“需后端改”，不据此判不通过；0012 只能存不可逆指纹）
- 方式：`git archive be607b3` 导出到 /tmp/rv3-be607b3，`uv sync --frozen`；临时容器 timescale pg16（rv3-pg，库 aia_be 升到 0012）+ redis（rv3-redis）；用脚本直接调用 `app.licences.service` 与 `app.api.v1.data_licence._admin_transition` 实测；测完容器和临时目录已删除。未改代码、未提交、未推送，未打印任何密钥

## 结论：有条件通过

四项裁定中三项实测符合：重复 pause / 证书已删除后 pause 都是 204 且不写审计；冷却期内删除后重提同一证书恢复删除前的 status、paused_until、last_error_*、consecutive_failures，不投递验证（202），换证照常验证；0012 只存 32 字节 HMAC 指纹（不含明文，也不等于去重用的 licence_hmac）。第四项按裁定记为“需后端改”：未暂停时 resume 返回 204 但仍写一条 from=to 的审计；同时契约 #26 ⑤ 要求的暂停/恢复通知尚未实现。另有 1 个 M（冷却记录不会按 paused_until 到期清理，与契约第 776 行不符）。条件：后端完成下面“需后端改”与 M1（可与 #26 一起在下一个提交里做）。

## 问题表

| 级别 | 位置 | 问题原因 | 修复建议 | 归属 |
|---|---|---|---|---|
| 需后端改（v0.2.9 #26 ①） | src/backend/app/api/v1/data_licence.py:343–376（一般分支），审计写在 361–375 | resume 遇到未被管理员暂停（row.status≠paused_by_admin、无 hold）的证书时，状态不变却仍写 `data_licence.resumed` 审计，detail 为 `from_status=active, to_status=active`。实测审计 +1、事件 +0。契约 #26 ① 要求：204、状态不变、不写审计/事件/通知 | 在 `_admin_transition` 中，resume 且 `not released and row.status != PAUSED_BY_ADMIN` 时直接 `return row.id, None`（与 pause 幂等分支 316–322 对称）；补自测 | 后端 |
| 需后端改（v0.2.9 #26 ⑤） | data_licence.py:294–376 全段 | 暂停、恢复成功且状态确实变化时，应给该用户发 `notification_kind=data_licence` 通知（正文不含理由），幂等调用不发。目前 app/api/v1/data_licence.py 与 app/licences/service.py 中没有任何通知写入 | 在状态真正变化的分支（pause 首次、resume 解除 hold 或 paused_by_admin→pending_verification）写 app.notifications；不带 reason；补自测 | 后端 |
| **M1** | src/backend/app/licences/service.py:263–280（`_take_cooldown`）、239–260（`_remember_cooldown`）；没有任何定时清理 | 冷却记录只在同一用户下一次 PUT/DELETE 时才被取出或覆盖；用户删除后不再提交，指纹就一直留在 app.user_data_licence_cooldowns。实测上一轮运行留下的记录一直存在。另外 quota_exceeded/ip_limited 且 paused_until 为 NULL 的记录按设计“不按时间到期”，会永久保留。契约第 776 行写的是“保留该证书的指纹……到 paused_until 为止” | ① ingest 周期任务（或现有清理任务）`DELETE FROM app.user_data_licence_cooldowns WHERE paused_until <= now()`；② paused_until 为 NULL 的记录定一个上限（如 deleted_at + 24h 或配置项），或请架构师在契约中明确“无 paused_until 时保留到换证/删号”；③ 补自测 | 后端；架构师（② 口径） |
| m1 | src/backend/migrations/versions/0012_t_b03e_licence_cooldowns.py:41 | 列注释写 `HMAC(K_cooldown, user_id\|\|licence)`，实际输入是 user_id 与 licence_hmac（app/licences/seal.py:93–98 `cooldown_fingerprint`） | 注释改成与实现一致（下个迁移里 `COMMENT ON COLUMN` 即可，不必改 0012） | 后端 |
| m2 | data_licence.py:316–322 | 有 hold 记录但证书行状态不是 paused_by_admin（例如暂停后数据被其他路径改过）时，pause 直接 204 返回，不把行状态修正回 paused_by_admin。正常路径下不会出现，属防御性问题 | held 且行状态不符时顺手修正（不写审计） | 后端（可选） |
| m3 | app/licences/seal.py:93–98 + config | 开发/测试环境若未配置 K_cooldown，用进程内临时密钥，重启后旧指纹全部失配（冷却等于失效）。生产强制配置，所以只是开发体验问题 | 在 .env.example / 部署文档写明生产必须配置；dev 日志提示一次 | 后端/运维 |
| m4 | src/backend/tests 不存在（既有） | 本提交的行为（幂等、冷却恢复、换证验证、409 NOT_SET）没有自动化测试 | 测试员按下面“测试方法”第 2–4 步写集成用例 | 测试员 |

## 测试方法（实测 PG）

1. 静态检查（/tmp/rv3-ci.sh）：ruff check、ruff format --check（77 个文件）、mypy strict 通过；0012 单独 ruff 通过；scripts/ci 各检查通过；scripts/ci/tests 200 passed / 55 skipped；check_fixtures 失败为既有问题。`alembic upgrade head`（0012）成功，`alembic check` 无差异。
2. 冷却保持：PUT 证书 → 人为置为 quota_exceeded（paused_until=+3h，last_error_code=429，consecutive_failures=2）→ DELETE：冷却表写入 1 行，fingerprint 为 32 字节，列只有 user_id、fingerprint、status、paused_until、last_error_*、consecutive_failures、deleted_at，无明文、无密文，fingerprint ≠ licence_hmac ✔。再 PUT 同一证书：status=quota_exceeded、paused_until 与删除前一致、429/2 保留，未投递验证（202 语义），冷却记录被取出 ✔。PUT 另一证书：pending_verification 并投递验证 ✔。
3. pause/resume：首次 pause 审计 +1、事件 +1 ✔；重复 pause 204，审计 +0、事件 +0 ✔；证书删除后再 pause 204，审计 +0（事件 +1 来自 DELETE 本身）✔；暂停中 PUT 仍为 paused_by_admin、不验证 ✔；resume → pending_verification 并带 verification_id ✔。
4. 未暂停时 resume：204，状态不变，但审计 +1（from=active, to=active），事件 +0 ✘（需后端改，#26 ①）；未设置且未暂停 resume → 409 NOT_SET ✔（契约第 997 行）。全程无通知写入 ✘（#26 ⑤）。
5. 清理：rv3-pg、rv3-redis 已删除，/tmp/rv3-* 已删；未动 sleepy_sutherland、youthful_banach、aia-t01-*、be-b03a-* 等其他容器。

## 检查项

| 检查项 | 结果 |
|---|---|
| 重复 pause / 证书已删除后 pause → 204、不写审计 | ✔ |
| 冷却期内删后重提同一证书 → 恢复 status/paused_until、202、不验证 | ✔ |
| 换不同证书 → 照常验证 | ✔ |
| 0012 只存不可逆指纹 | ✔（注释与实现不一致，m1） |
| 指纹保留到 paused_until 为止 | ✘ 无到期清理（M1） |
| resume 幂等不写审计 | ✘ 写了 from=to 审计（需后端改，#26 ①） |
| 状态变化时发通知 | ✘ 未实现（需后端改，#26 ⑤） |
| 未设置且未暂停 resume → 409 NOT_SET | ✔ |

## 谁需要做什么

- 后端：① resume 幂等分支不写审计；② 暂停/恢复状态变化时发 data_licence 通知；③ M1 冷却记录到期清理；④ m1 注释修正（下个迁移）。
- 架构师：确认 paused_until 为 NULL 的冷却记录保留上限（M1 ②）。
- 测试员：补冷却保持、幂等、409 NOT_SET 集成用例（m4）。
