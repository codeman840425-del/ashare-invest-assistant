# 收口预演（T-O32）

脚本：`deploy/scripts/closeout.sh`。清单：`deploy/closeout/accepted.manifest`。
默认 `plan` 只打印。不合并、不建库、不调用 docker。
脚本只认清单里原有的 BASE/MERGE 行，不要求新字段。

## 清单

每一行是精确 hash、角色、任务和验收证据。不扫描分支 tip，不把 `03df03b` 当作清单。
hash 只在本地 `git rev-parse`，对象不在本地就停止，不 fetch。
冲突时打印责任角色和文件，中止这一次临时分支上的 merge，不 reset 其他分支，不替该角色改文件。

## 隔离数据库

`rehearse-db` 使用 compose 里已有的 TimescaleDB PG16 镜像。`docker run --network none`，专属 unix socket，随机口令只放在权限 600 的文件里，不进数据库地址，不打印。
镜像不在本地则停止，不拉取。容器网络模式不是 none 则停止，不改宿主网络，不删除容器。
顺序：迁到 0023 → 合成数据 → `assert-0023.sql` → `pg_dump` → 非空旧事件门 → `alembic upgrade head` → 与 `alembic heads` 对照（必须是单一头）→ timescale → `apply-roles` 与 `verify-roles` 各两遍 → `assert-retained.sql`。
授权在 head 之后。不在 0023 上跑需要后续列的授权脚本。
`signal_events` 不是 0 就停止：不升级、不删行、不降级。
合成数据本身把 `signal_events` 留成 0，所以成功路径只覆盖空事件。
`rehearse-neg` 在另一库插入一条 user 和一条 shared 旧事件，期望升级失败、版本仍是 0023、计数仍是 2。确认拒迁后退出 2。退出 2 表示阻塞仍在，不是迁移成功。升级若返回成功，脚本失败。
失败不删除容器和日志。`cleanup-iso` 只接受 `aia-closeout-pg-` 加时间戳的容器名，并且工作目录必须在临时目录下；不使用 `-v`，留下日志和口令目录。

## 8 服务与真实部署

`rehearse` 直接退出 2，不启动 8 个服务，也不调用 docker。
`deploy` 只有 `AIA_CLOSEOUT_DEPLOY=1` 才继续。`self-check` 自己置位内部标记：即使环境里已经有 `AIA_CLOSEOUT_DEPLOY=1`，也不会调用 `db-backup.sh` 或 `up.sh`。
`up.sh` 已经包含迁移、timescale-apply、db-roles 和 `--wait`。其后的 `verify-roles` 用 `compose.sh run --no-deps --entrypoint bash db-roles` 在现有 db-roles 容器模式里执行。非 0 即停，不跑 nginx 或 HTTP。不重复迁移。

## 清单条件

编排者确认纳入的提交写在 MERGE 行。`373b680` 是交接草稿，不是已完成部署。`0289388` 只是代码层通过，7 个用例没有跑。
`d5a9a60` 与 0027 不是 MERGE。`afccd5e` 只是条件评审分支。正式收口要等父端在新的隔离 socket 上复验 ACL。

## 父端复验准备

不要改 tests，不要碰 `/tmp/tb70-tb91-owned-socket`。`test_tb91_closing.py` 经 `test_tb91_fixes.py` 把 PG socket 写成 `/tmp/tb70-tb91-owned-socket`，Redis 写成 `unix:///tmp/tb91-owned-redis/redis.sock`，并断言 socket 文件存在，不能用环境变量换。连接方式等编排者裁定。
ACL 复验另用新的 network none unix socket：库到当前 head，先跑 `apply-roles.sh` 再跑 `verify-roles.sh`。不需要真实用户、证书或外部 HTTP。投影表、五表和 `market.master_vendor_batches`（若库里有）必须已由迁移创建，脚本不建表。

## 本环境没有做的事

没有启动隔离容器，没有跑 0023 到 head，没有跑架构 7 个用例，没有 8 服务，没有真实 deploy。
`self-check` 在 `AIA_CLOSEOUT_DEPLOY=1` 下确认真实备份和启动没有被调用。
