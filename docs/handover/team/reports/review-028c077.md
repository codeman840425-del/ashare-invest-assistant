# 复审 028c077：删除 cooldown-purge 服务及 CI 规则 7 登记（运维）

架构师，2026-11-01（America/Denver）。范围：docker-compose.yml / dev.yml、deploy/docker/cooldown-purge.py（删除）、
scripts/ci/check_secret_boundary.py、相关测试。

## 结论

**可以推送，但只能与 6670b10 同批或更晚。** 已核对：6670b10 是 028c077 的祖先，且两者都还没推送（origin/main = 0cb78ad），
所以推送 028c077 时 6670b10 必然一起推上去，满足要求。不要把 028c077 单独 cherry-pick 到不含 6670b10 的分支或部署上。
无 B。M1、M2 不阻塞这次推送，但要列为运维待办。

## 核对项

| 要求 | 结果 |
|---|---|
| 替代实现存在 | 通过。6670b10 起 beat（app.workers.beat）按 `cooldown_purge_interval_s`（默认 3600，最小 60）排 `licences.purge_expired_cooldowns`，worker 执行；compose 的 beat/worker 服务都在。 |
| CI 规则 7 一致 | 通过。MASTER_KEY_ALLOC、DB_ROLE_OF、NO_SECRET_SVCS 都去掉了 cooldown-purge；check_secret_boundary.py 退出 0；加回服务会因“未在白名单登记”失败（有测试）。 |
| 残留 | compose / deploy 里已无该服务；后端还有残留（m2）。 |
| 测试 | 全量 scripts/ci/tests：582 passed，5 failed 均为 test_secret_scan 已知环境问题。 |

## 问题

- **M1 worker 仍用库属主连接（与新裁定冲突）**：提交信息写“worker DSN 不变（按用户决定）”。架构师新裁定（plan §7.3）：
  worker 改用 aia_api，只给 worker 任务实际用到的表补 DML，不给 DDL。冷却清理由 worker 执行后，属主权限范围更大了。
  不阻塞本提交（本提交没改变 worker 的角色），但须作为运维待办尽快做（见下方待办）。
- **M2（附带发现，3e5e288 引入）worker 没挂原始导入文件卷，到期清理会“假删除”**：`imports.purge_raw_files` 在 worker 执行
  （jobs.py PURGE_RAW_FILES → pipeline.purge_expired_raw_files），而 docker-compose.yml:52–54 明确说 imports 卷只挂给 api 和 maint-cli。
  在 worker 里 `storage.delete_raw` 的 `unlink(missing_ok=True)` 找不到文件也算成功，于是把 import_files 标成 deleted_at、清空 storage_path，
  **真实的加密原始文件留在卷上永远不会被删**，与留存承诺不符。
  修复（运维 + 后端）：给 worker 挂 imports 卷（读写，属主 10001）并更新 compose 注释和 CI 守卫；后端让 delete_raw 在存储根目录不存在时报错，
  而不是当成已删。部署 3e5e288 及之后版本到有真实导入数据的环境前必须修好。
- m1 升级时旧容器残留：up.sh 不带 `--remove-orphans`，已部署过 cooldown-purge 的主机升级后旧容器会继续用属主 DSN 跑旧镜像。
  在 runbook 写一次性清理：`deploy/scripts/compose.sh up -d --remove-orphans`（或 `compose.sh rm -sf cooldown-purge`）。
- m2 后端残留：src/backend/app/config.py:62 的 SERVICE_NAME 允许列表、selfchecks/tb49.py:76 仍有 "cooldown-purge"，请后端顺手删掉。
- n1 部署 .env 里若设过 `AIA_COOLDOWN_PURGE_INTERVAL_S`，现在不再生效（beat 读 `COOLDOWN_PURGE_INTERVAL_S`，默认同为 3600）；runbook 提一句。
