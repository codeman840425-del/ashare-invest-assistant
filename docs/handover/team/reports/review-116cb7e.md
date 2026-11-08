# 评审：116cb7e（T-B03d：契约 v0.2.8 #11–#14、#1/#2，旧 M1/M2/M5）

- 评审时间：2026-11-02（UTC+8）
- 方式：只读；git archive 导出 /tmp/rev3-116cb7e 和 /tmp/rev3-7afbc06
- 实测环境：临时 PG16 + Redis 容器，端到端脚本跑了 52 项检查
<redacted:sensitive-value-or-command>
- 收尾：容器已全部删除
- 自报：/workspace/team/reports/T-B03d.md

## 结论：**有条件通过**

功能和契约实测全部通过（52/52）。旧 M1、M2、M5 已修复。

条件：
1. CI contract 红的一行文档由架构师修掉。
2. 测试员补蜜罐、暂停记录（holds）、改密限速的用例，并修正 7 个滞后的用例。

## 父级加查：邀请码会不会被 409 / 蜜罐用掉 —— **不会（实测确认）**
- 代码顺序（app/api/v1/auth.py:186–208）确实是先占码后查重：
  1. 先 `invites.redeem`（app/auth/invites.py:121，条件 UPDATE used_count+1）；
  2. 再 `username_taken` 查重名；
  3. 再 `enforce_pending_cap`；
  4. 最后判断蜜罐。
- 但这几步都在同一个 `engine.begin()` 事务的保存点 `checks` 里：
  - 409 / 503 抛异常时，整个事务回滚，占码一起撤销；
  - 蜜罐命中时 `checks.rollback()` 只撤销保存点，外层事务只提交审计。
- 先占码再查重有个好处：没有有效邀请码的人探测不到用户名是否已存在。
- 实测（每项都直接查 `app.invite_codes.used_count`）：

| 场景 | 响应 | used_count |
|---|---|---|
| 正常注册 | 201 | 0 → 1 |
| 重名注册（有效新码） | 409 | 保持 0，未建用户 |
| 蜜罐 website 命中 | 201（键 id/status/username，与正常注册相同） | 保持 0，未建用户 |
| 蜜罐 + 重名 | 409（顺序与 §7.1 一致） | 保持 0 |
| 连续蜜罐直到第 6 次 429（命中计入 IP 限速） | 201×5、429 | 保持 0 |
| 蜜罐 + 无效码 | 400 | — |

结论：与契约 #11 的“不消耗邀请码”一致，不构成冲突。

## 问题表（无 B / M）

| 编号 | 位置 | 问题 | 原因 | 修复建议 | 负责 |
|---|---|---|---|---|---|
| m1 | app/licences/service.py:233–275（set_licence） | 冷却期绕过：处于 quota_exceeded / ip_limited / paused_until 未到期时，先 DELETE 再 PUT 同一证书会回到 pending_verification 并重新验证（实测 202 pending_verification） | 删除后没有活动行，`keeps_state` 无从判断；契约对此没有规定 | 架构师在契约里写明“DELETE 后再 PUT 同一 HMAC 是否继承冷却”；后端按 HMAC 保留冷却，或者在 ingest 侧做全局 IP 退避。现有缓解：生产默认关开关、PUT 10 次/小时、test 5 次/小时 | 架构师 / 后端（T-B04a-x） |
| m2 | app/api/v1/data_licence.py:105（_require_settings_enabled） | 开关关闭时 PUT / PATCH / test 返回 503 MAINTENANCE，契约这三个接口的错误表里没有 503 | 新开关没有同步到契约 | 架构师在 §7.9 补上 503 MAINTENANCE | 架构师 |
| m3 | app/licences/service.py:500（ingest_licences） | 函数已实现：键集合、排序、501 行上限都实测符合 §5.1；但还没接到 /admin/ingest/status 端点 | 端点属于后续任务 | T-B04a-x 接入时补端到端测试 | 后端（T-B04a-x） |
| m4 | app/api/v1/data_licence.py:300–316（_admin_transition） | 用户已在暂停中但删掉了证书，再次 pause 返回 409 NOT_SET，而不是幂等 204 | pause 分支只看活动行 | 已有 hold 时 pause 直接返回 204（幂等），或者在契约里写明 | 后端 / 架构师 |
| m5 | migrations/versions/0010_t_b03d_licence_holds.py:44 | 0010 之前就“暂停期间删除证书”的用户（只剩已删除的 paused 行），回填后不会有暂停记录 | 回填只看活动的 paused_by_admin 行 | 推送前在库里统计这类用户；有的话人工补 hold | 后端 / 运维 |
| m6 | 0010 文件头第 5 行 | Create Date 07:30 晚于提交时间 07:05 | 手写 | 顺手改掉 | 后端 |
| m7 | 测试分支 caa1f09 | 没有蜜罐、holds、ensure_not_limited 的用例；另有 7 个用例因预期滞后失败（head 0008、t_t22 多出 licence_id、meta_enums 5 个） | 测试滞后 | 补用例、更新预期 | 测试员 |
| m8 | openapi RegisterIn | 仍带 `agreements` 字段（之前就有） | — | 与架构师确认后保留或删除 | 后端 / 架构师 |

## 契约逐项核对（实测）

| 契约项 | 检查 | 结果 |
|---|---|---|
| #11 蜜罐 | website 非空 / 1 秒前 / 未来时间 / 两者都中（trigger=both）→ 201，不建用户 | ✓ |
| #11 蜜罐 | website 全空白不算命中；5 秒前正常建用户 | ✓ |
| #11 蜜罐 | form_started_at 为字符串或小数 → 400；未知字段 → 400 | ✓ |
| #11 蜜罐 | 审计 auth.register_honeypot 1 条，actor 为空，detail 只有 {trigger} | ✓ |
| #11 蜜罐 | 命中计入 IP 限速 | ✓ |
| #11 蜜罐 | 不消耗邀请码 | ✓ |
| #12 暂停（M1） | pause 写 holds | ✓ |
| #12 暂停（M1） | 暂停期 PUT 新证书 → 202 paused_by_admin，不验证 | ✓ |
| #12 暂停（M1） | DELETE 后 GET 和 /me 仍为 paused_by_admin，证书字段为 null | ✓ |
| #12 暂停（M1） | DELETE 后再 PUT 仍为 paused_by_admin | ✓ |
| #12 暂停（M1） | resume → pending；证书已删时 resume → 204 not_set，holds 清空 | ✓ |
| #13 重复 PUT | 同一 HMAC 保持 quota_exceeded / ip_limited / 未到期的 paused_until（同 id，tier 更新） | ✓ |
| #13 重复 PUT | paused_until 已到期 → pending | ✓ |
| #14 test | 暂停或已删除时 → 409 DATA_LICENCE_UNAVAILABLE{status} | ✓ |
| #1 IngestLicenceStatus | 键集合 17 个，不含 not_set，不含密文 / HMAC | ✓（函数层面，见 m3） |
| #2 AdminDataLicence.licence_id | 是 uuid；未设置证书时为 null；列表里不含证书值任何 ≥8 字符的子串 | ✓ |
| #15 openapi | 13 个路径，没有 /admin | ✓ |
| M2 开关 | production 未设置 → 关；显式 true → 开 | ✓ |
| M2 开关 | 关闭时 PUT / PATCH / test 为 503，GET 200，DELETE 204 | ✓（503 见 m2） |
| M5 改密 | 先查限速：错误序列 400×5 后 429；超限后用正确旧密码也是 429 | ✓ |
| 0010 迁移 | upgrade / downgrade / upgrade；回填只给活动 paused 用户建 hold，paused_at = status_changed_at | ✓（见 m5） |
| 授权 | grants.sql 的 schema 级授权和默认权限覆盖新表 | ✓ |

## 迁移实测
- u1：活动行 paused → 建 hold；
- u2：有已删除的 paused 行，但活动行是 active → 不建；
- u3：active → 不建；
- u4：只有已删除的 paused 行 → 不建（m5）；
- downgrade 到 0009 删除表；再 upgrade 得到 1 行。

## CI contract 作业（HEAD 7afbc06）—— **仍然是红的**

| 步骤 | 结果 |
|---|---|
| 1 check_contract | ✗ 1 个错误：§4.1 与 plan 3.5A-1 第 46 行不一致（IMPORT_LOT_SIZE_IRREGULAR）。api-contract.md:510 加了“；ETF 按 100 份整数倍，v0.2.8”，docs/plan.md:1733 没有同步。负责：架构师，同步 plan.md:1733 即可 |
| 2 / 4 / 6 | rc=0 |
| 5 | 同一条错误；meta 和版本号其余部分一致 |
| 7 migrate | ✓ 新库 |
| schemathesis 4.33.0 | 17/17 个操作，780/780 通过；唯一警告是 10 个只带鉴权的操作 |

后端部分全绿，只差这一行文档。

## 其他
- ruff / mypy / uv sync --frozen：✓
- pytest（116cb7e 导出）：7 failed / 783 passed / 93 skipped / 14 xfailed，失败全是测试预期滞后（m7）。

## 推送前需要在库上跑的检查
1. 0009（c55a42e）：在 0008 上分别统计：
   - paused 且 paused_by 为空的行数；
   - archived 且 archived_at 为空的行数；
   - market.securities 是否为空（守卫触发器会拒绝未知代码的 INSERT 和 security_code 更新）。
2. 有没有环境已经跑过旧版 0009：查 alembic_version，以及 0009 新增的列是否存在。有的话需要单独回填。
3. 0010：统计活动 paused_by_admin 行数；统计只剩已删除 paused 行的用户（m5）。
4. 迁移后重跑 grants.sql（db-roles），再执行 verify-roles.sh。
5. 确认生产环境没有设置 DATA_LICENCE_SETTINGS_ENABLED，或者设置为 false。
