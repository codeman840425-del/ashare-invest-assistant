# 评审：535d9b4 feat(deploy): 定时清理到期证书冷却记录（cooldown-purge 服务）（含后续 bc0d5ba）

评审人：项目架构师；方式：/tmp/arv-535d9b4 干净导出，只读。

## 架构裁定
接受它作为 **beat 落地前的过渡方案**。beat 实现后改为 beat 调度、worker 执行，并删除 cooldown-purge 服务（由后端排期；删除服务以及从 CI 的 NO_SECRET_SVCS / DB_ROLE_OF 移除登记，由运维做）。

## 结论
**通过。可以推送，但必须和 bc0d5ba 一起推。** 单独的 535d9b4 在容器里会出现 `ModuleNotFoundError: app`（aia-t01 实测），bc0d5ba 修复了这个问题。顺带解决了 review-a8e055b M1（缺少每小时清理），属于过渡解法。

## 核对
| 项 | 结果 |
|---|---|
| 不挂主密钥 / 任何 secret | ✅ yaml 解析结果为 `secrets=[]`，没有 secret-env 入口，environment 里没有 APP_MASTER_KEY。CI 新增 NO_SECRET_SVCS 规则：挂任何 secret 都会失败 |
| DB 口令 | 沿用 api 的做法：`*db-api-url` 由 compose.sh 插值 AIA_DB_API_PASSWORD，**没有用口令文件**。与 api 同等暴露面（docker inspect 可见），不是新风险。将来 api 改为口令文件时一并改 |
| 最小权限 aia_api | ✅ DATABASE_URL 用 `*db-api-url`。CI 的 DB_ROLE_OF 规定它必须是 aia_api（不能用属主）。aia_api 本来就在证书 PUT/DELETE 时执行同一个 DELETE，不新增权限 |
| 保留期是否符合裁定 | ✅ 直接调用后端 `purge_expired_cooldowns`，不复制判定。`_cooldown_expired` = `paused_until <= now` 或者（`paused_until IS NULL` 且 `deleted_at <= now-24h`），与 plan §7.3 / 契约 #28① 一致（a8e055b 评审时已用 PG 验证过） |
| 不加载 Settings | ✅ import 链里没有模块级 get_settings()，所以不需要主密钥。后端 M2 落地后也不受影响 |
| 与 M2 白名单是否冲突 | 不冲突。它在 M2 表里属于“不挂”，而 NO_SECRET_SVCS 比“不挂主密钥”更严。今后规则 7 改成显式白名单时，要把 cooldown-purge 登记为“不挂”（运维） |
| check_secret_boundary 改动 | ✅ 合理：DB_ROLE_OF 加 cooldown-purge→aia_api，新增 NO_SECRET_SVCS |
| 其他 | 默认 3600s，最小 60s；replicas 1；异常只记类型名（不泄露连接串）；心跳健康检查阈值 2×间隔+60s；DB 故障时继续循环；dev override 设 APP_ENV=local 并挂源码。DELETE 是幂等的，和 api 的读取时清理并发也没问题 |

## 问题
- n1：bc0d5ba 用 cwd/AIA_BACKEND_DIR 补 sys.path，依赖镜像 WORKDIR。可以接受；beat 落地后整个服务都会删除。
- n2：plan 已登记（6d344e3）：§1.3 表新增 cooldown-purge 行，§7.3 补过渡说明。

## 测试
- 用 gitleaks 8.30.1：`scripts/ci/tests` **337 passed**（含 test_cooldown_purge_job.py、test_secret_boundary.py）。
- `check_secret_boundary.py`：OK。
