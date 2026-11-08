# 收口预演（T-O32）

脚本：`deploy/scripts/closeout.sh`。清单：`deploy/closeout/accepted.manifest`。
默认 `plan` 只打印。不合并、不建库、不调用 docker。

## 清单

每一行是精确 hash、角色、任务和验收证据。不扫描分支 tip，不把 `03df03b` 当作清单。
`462057c`（T-A33）没有通过记录，不要写进 MERGE。
hash 只在本地 `git rev-parse`，对象不在本地就停止，不 fetch。
冲突时打印责任角色和文件，中止这一次临时分支上的 merge，不 reset 其他分支，不替该角色改文件。

## 隔离数据库（本机稍后）

`rehearse-db` 用专属 unix socket 的 PG16（`listen_addresses` 为空，不创建 docker 网络）。
顺序：迁到 0023 → `synthetic-0023.sql`（旧通知，且 `signal_events` 为 0）→ `assert-0023.sql` → `pg_dump` → `alembic upgrade head` → `assert-retained.sql`。
head 取 `alembic heads`，不写死 0024/0026。失败停，不降级，不删除数据目录。
本树若缺 `0025`/`0026`、`app.db.base`、前端或 fixtures，脚本直接退出。

## 8 服务

`rehearse` 直接退出 2。网络预检被中断后禁止重试，本脚本不跑 `docker info` / `docker network`，也不宣称 8 个服务 healthy。
真实网页和 8 服务留到用户电脑。`deploy` 只有 `AIA_CLOSEOUT_DEPLOY=1` 才调用已有 `up.sh`，不删除数据卷，不覆盖已有密钥。

## 未在本环境完成

完整 0023→head 迁移、`verify-roles.sh` 全套、8 服务、首页/login。
ACL 定点只在临时库的相关表上跑过 `apply-roles` 两遍，不是全量迁移。
