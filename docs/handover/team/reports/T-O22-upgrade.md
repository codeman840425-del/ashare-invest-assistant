# T-O22 用户本地升级准备：934648b → dcf734d（摘自现有 runbook 和已批准脚本；没有执行）
依据：docs/runbook/windows-local.md、deploy/runbooks/database.md、deploy/scripts/up.sh 和 compose.sh 的头部注释（都按 dcf734d 版本）。
真实迁移链（dcf734d 的 versions/）：0019 → 0020 → 0022（0022 的 down_revision 是 0020）。0021 在 migrations/paused/，不在迁移链里，不会执行；以迁移链为准，不能按编号推断。
## 0. 停手红线
- 禁止 down -v、删卷、alembic downgrade、改 AIA_VOLUME_PREFIX、项目名或工作树目录名（卷名和密钥目录都由它们推导）。
- 下面任何一步失败都先停下，保留日志，报给编排者；不要重试其他写法，不要手工改库。
## 1. 升级前只读确认（在用户 WSL、仓库根目录执行）
1. `git rev-parse HEAD` 应该是 934648b；`bash deploy/scripts/compose.sh --resolve`：记下项目名、卷前缀和 AIA_SECRETS_DIR（以用户原部署的 --resolve 实际输出为准，不假定是 /root；默认值按运行用户的 HOME 和卷前缀推导），升级后必须完全一样。
2. `bash deploy/scripts/compose.sh ps -a`：确认 postgres 是 healthy。
3. 查当前库版本：`bash deploy/scripts/compose.sh exec postgres psql -U <POSTGRES_USER> -d <POSTGRES_DB> -tAc 'select version_num from alembic_version'`。按 934648b 推断应是 0019（未实测）。如果不是 0019 或 0020，就停下报告；如果已经是 0021，也停下（0021 已 paused）。
4. 确认密钥目录里已有 app_master_key、证书封装密钥和 db_password_* 文件（只看是否存在，不打印值）。缺任何一项都停下，不要让脚本生成新密钥。
## 2. 备份（要放在仓库外）
5. `deploy/scripts/db-backup.sh --out-dir /data/backup`：生成 .dump 和 .meta.json（权限 600）；`/data/backup` 目录权限 700。
<redacted:sensitive-value-or-command>
7. 可选：`db-restore.sh <dump> --db aia_restore_check` 演练恢复（恢复到新库名，不覆盖 aia）。
## 3. 升级
8. `git fetch` 后切到目标 commit（以推送后的 origin/main 为准；见 T-O22.md，dcf734d 目前和远端分叉）。这一步之后 .env 和密钥目录都不要动。
9. `bash deploy/scripts/compose.sh --resolve`：和第 1 步对比，项目名、卷前缀、AIA_SECRETS_DIR 要完全一致。
10. `bash deploy/scripts/up.sh`：默认 --build（后端和前端网关镜像都重建）→ postgres/redis → migrate（alembic upgrade head，会依次执行 0020、0022；当前是 0019 时不会跳过 0020）→ timescale-apply → db-roles（apply-roles）→ 各服务 → nginx。up.sh 默认叠加 dev 覆盖（麦蕊回放）；live 模式按 runbook 另行确认。新的 <前缀>_master 卷会自动创建。
11. 失败处理：`compose.sh logs migrate timescale-apply db-roles` 看原因，然后停下。迁移已经部分执行时，不要降级，不要 down -v；由编排者转 cloud 或后端判断。真要回退，只能用第 5 步的 dump，通过 db-restore.sh 恢复到新库名验证后再决定。
## 4. 升级后检查
12. 再查一次 alembic_version，应为 0022；`compose.sh ps -a` 全部 healthy，一次性服务（migrate、timescale-apply、db-roles）都是 Exited (0)。
13. 浏览器打开网关登录页能登录；app-master-key-backup.sh fingerprint 和台账一致。
14. 可选：verify-roles.sh 做权限验收。
