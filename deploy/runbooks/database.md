# 数据库运维手册（TimescaleDB / 备份恢复 / 容量）— T-O08

## 1. 版本固定

`deploy/compose/docker-compose.yml` 中所有镜像都写成 `tag@sha256:digest`。
postgres 镜像为 `timescale/timescaledb:2.31.0-pg16`，对应 PG 16.15 和 TimescaleDB 2.31.0。

升级步骤：
1. 在新 tag 上跑一遍 `deploy/scripts/db-restore-drill.sh`（加 `AIA_PG_IMAGE=<新镜像>`）。
2. 先 `db-backup.sh`，再改 compose 中的 tag 和 digest。
3. 扩展升级用 `ALTER EXTENSION timescaledb UPDATE`。

**备份和恢复要求两端的 TimescaleDB 版本相同。**

## 2. TimescaleDB 策略（hypertable / 压缩 / 保留 / 连续聚合）

- 参数只放在一个文件里：`deploy/db/timescale/policies.conf`。字段说明见文件头。
  - `-` 表示不管理。
  - `none` 表示确保不存在。
  - `a/b` 表示取第一个存在的列。
- SQL 都是幂等的，文件在 `deploy/db/timescale/sql/`；连续聚合的定义在 `caggs/*.sql`。
- 执行入口：

```bash
deploy/scripts/db-apply-timescale.sh --dry-run          # 只看会改什么
deploy/scripts/db-apply-timescale.sh                    # 对 compose 中的 postgres / aia 库执行
deploy/scripts/db-apply-timescale.sh --only market.minute_bars
AIA_TS_MIGRATE_DATA=1 deploy/scripts/db-apply-timescale.sh   # 允许把已有数据的普通表迁成 hypertable（会锁表）
```

- 对表的处理规则：
  - 表或时间列不存在：**SKIP 并给出 NOTICE**。部署侧不建业务表，表由后端迁移创建。
  - 空表会直接转成 hypertable。
  - 已有压缩 chunk 的表，不会改压缩 segmentby/orderby，只给出 WARNING。
  - 参数变化时，删除旧策略，再按新参数重建。
- 后端每次迁移后，要重跑一次 `db-apply-timescale.sh`。

## 3. Postgres 调优与 WAL

配置文件是 `deploy/postgres/conf/postgresql.conf`，以只读方式挂到 `/etc/postgresql/postgresql.conf`。
它按 16 GB 内存、8 核的机器设定。

- 内存：`shared_buffers 4GB`、`effective_cache_size 10GB`、`work_mem 16MB`、`maintenance_work_mem 1GB`。
- WAL：`wal_compression lz4`、`max_wal_size 8GB`、`min_wal_size 1GB`、`checkpoint_timeout 15min`。
- 后台进程：`timescaledb.max_background_workers 16`、`max_worker_processes 27`。

改了参数要 `deploy/scripts/compose.sh restart postgres`。
验证：

```sql
SHOW config_file; SHOW shared_buffers; SHOW max_wal_size; SHOW wal_compression;
```

## 4. 备份与恢复

```bash
deploy/scripts/db-backup.sh                         # aia 库 → deploy/backups/aia-<UTC>.dump + .meta.json（600 权限，不入库）
deploy/scripts/db-backup.sh --out-dir /data/backup  # 建议放到仓库外，并异地另存
deploy/scripts/db-restore.sh deploy/backups/aia-<UTC>.dump --db aia_restore_check
deploy/scripts/db-restore.sh <dump> --db aia_restore_check --drop-existing
```

**备份（db-backup.sh）**
- 格式是 `pg_dump -Fc`。
- 产物的 `.meta.json` 里记录 PG 和 TimescaleDB 的版本、镜像、sha256。

**恢复（db-restore.sh）的检查**
- 校验 sha256。
- PG 大版本必须一致，TimescaleDB 版本必须完全一致。

**恢复流程**
1. `CREATE DATABASE`。
2. `CREATE EXTENSION timescaledb VERSION <同版本>`。
3. `timescaledb_pre_restore()`。
4. `pg_restore`，默认串行。TimescaleDB 目录表之间有循环外键，演练实测 `-j 4` 会报外键错误。
5. `timescaledb_post_restore()`。
6. `ANALYZE`。

**恢复的保护**
- 恢复脚本拒绝覆盖容器的 `POSTGRES_DB`（主库 aia）。
- 目标库已存在时，必须加 `--drop-existing`。
- 生产恢复请先恢复到新库名，验证后再切换。

**演练**
- 命令是 `deploy/scripts/db-restore-drill.sh`，全程只用临时容器，不连接 aia 主库。
- 演练内容：建 hypertable 和数据、压缩、刷新 CAGG、备份、在全新容器恢复，然后做以下校验：
  - 行数和逐行 md5。
  - 压缩 chunk 数。
  - CAGG 可查询，并且可以继续刷新。
  - 策略作业齐全，状态为 scheduled。
- 每次演练的结果写到 `deploy/drills/<UTC>-restore-drill.{md,json}`，这些记录入库。
- dump 只放在 /tmp，用完即删。
- 建议每月跑一次，升级镜像前也要跑一次。

## 5. 磁盘 / WAL 容量规划

**实测**（演练样例：numeric OHLC，主键加 (security_id, ts DESC) 两个索引）
- 未压缩时约 **200 B/行**（含索引）。
- 压缩后约 **35 B/行**，压缩比 **5.3–5.7×**。
- 样例数据随机性较高，真实行情的压缩比通常会更高。规划按 5× 保守估计。
- plan 中的假设是 110 B/行、压缩 10×。

**1 分钟 K 每年的量**
- 全市场：约 5,300 只 × 240 根 × 245 天 ≈ 3.14 亿行/年。
- Tier-1：1,500 只，约 0.87 亿行/年。

| 项目 | plan 假设（全市场/年） | 实测口径（全市场/年） | 实测口径（Tier-1/年） |
|---|---|---|---|
| minute_bars 原始 | 34.5 GB | 63 GB | 17.6 GB |
| minute_bars 压缩后（7 天后压缩） | 3.5 GB | 11–12.5 GB | 3.0–3.5 GB |
| 热窗口（最近 7 天未压缩） | — | ≈1.3 GB | ≈0.4 GB |
| bars_5m CAGG（30 天后压缩） | — | ≈2.5 GB | ≈0.7 GB |
| daily_bars / bars_daily | — | ≈1 GB | ≈0.3 GB |
| factor_values（假设 50 个因子，90 天后压缩） | — | ≈1–5 GB | ≈0.3–1.5 GB |
| realtime_quotes（保留 21 天） | — | 1–5 GB，常驻 | 0.3–1.5 GB，常驻 |

**3 年保留（minute_bars 保留 1095 天）**
- 全市场：业务数据约 **50–70 GB**，加索引膨胀和余量约 80 GB。
- Tier-1：约 **20–25 GB**。

**WAL**
- `max_wal_size 8GB` 是软上限，pg_wal 峰值约 10 GB。
- `wal_compression lz4` 可以减少整页写的体积。
- 归档目前关闭（`archive_mode off`）。如果开启 PITR，归档目录要再预留约每日 WAL 量 × 保留天数。

**备份**
- `pg_dump -Fc` 导出的压缩 chunk 仍是压缩形态。演练中 dump 大小约等于压缩后的数据大小。
- 本地保留 2 份，约 2 × 60 GB。

**建议磁盘**
- 全市场 3 年：**≥ 300 GB SSD**。计算：DB 80 + WAL 10 + 本地备份 120 + 30% 余量。
- 只做 Tier-1：≥ 120 GB。
- 当前 box 的 /var/lib/docker 为 128 GB（已用 11 GB），够 Tier-1，不够全市场 3 年。

## 6. 数据库角色与应用密钥文件（T-O10 / T-O11）

| 角色 / 文件 | 用途 | 谁拿得到 |
|---|---|---|
| `aia_api` / `aia_ingest` | api / ingest 的 DATABASE_URL | compose.sh 插值（口令文件 `$AIA_SECRETS_DIR/db_password_aia_{api,ingest}`） |
| `aia_maint` | 只给删除用户数据 CLI（plan §7.3）；唯一能把 `app.users.status` 写成 purging 的角色 | secret `db_password_aia_maint`，只挂 `db-roles`、`maint-cli` |
| `app_master_key` | 后端 `APP_MASTER_KEY`（邀请码 / 证书 HMAC 等） | secret，只挂 `api`、`worker`；入口包装 `deploy/docker/secret-env.sh` 在容器内转成环境变量 |

- 口令 / 密钥文件都在仓库外 `$AIA_SECRETS_DIR`（默认 `~/.config/aia/secrets/<卷前缀>`），600；`compose.sh` 缺失时生成（主密钥例外，见下文“APP_MASTER_KEY 迁移”），**已存在从不覆盖**。
  `db_password_aia_maint`、`app_master_key` 属主是容器用户 10001（生成时 sudo -n chown）。
- **换 APP_MASTER_KEY 会让既有邀请码哈希、证书 HMAC 失效**：只能在确认无存量数据或有迁移方案时人工删文件重建。

### APP_MASTER_KEY 迁移（T-O11 评审 M1）

`compose.sh` 不再直接生成主密钥；`app_master_key` 文件缺失时由 `deploy/scripts/app-master-key-ensure.sh` 判定：

| 情况 | 行为 |
|---|---|
| `$AIA_SECRETS_DIR/app_master_key` 已存在 | 直接用（为空则拒绝，不覆盖） |
| 文件不存在，调用方环境或 `deploy/env/.env` 里有非占位的 `APP_MASTER_KEY` | 迁移进密钥文件（600，属主 10001，不打印），提示“已从 … 迁移”；**不删 .env 那一行**，由人确认后再删。两处值不一致、或短于 32 字符 → 拒绝 |
| 两边都没有，库已初始化（有任何业务表，含 `alembic_version`）或 `app.users` / `app.invite_codes` / `app.user_data_licences` / `app.import_files` 有行、或导入卷里有文件 | **拒绝启动**（退出 3），提示找回原密钥 |
| 两边都没有，数据卷存在但 postgres 没在跑 / 查不了 / docker 不可用 | 无法确认是空库 → 拒绝（fail-closed） |
| 两边都没有，数据卷不存在或库里没有业务表、导入卷为空 | 生成新主密钥（`app-master-keygen.sh`） |

占位值（空、含 `<` `>`、`changeme` / `example` 开头）视为没有。api / worker 另设 `AIA_REQUIRE_APP_MASTER_KEY=1`：
secret 没挂上时 `secret-env.sh` 拒绝启动，后端不会回落到临时随机主密钥。

升级旧部署（主密钥原来在 `.env`）：
1. 先备份库与 `.env`；`compose.sh up …` 时自动迁移，看到“已从 … 迁移”；
2. 验证：`stat -c '%a %u' $AIA_SECRETS_DIR/app_master_key` 为 `600 10001`；用既有邀请码 / 登录验证 HMAC 仍然一致；
3. 确认无误后，由人决定删除 `.env` 里的 `APP_MASTER_KEY` 行（compose 已不读它）。

被拒绝时：从备份 / 原部署机找回原主密钥，写入密钥文件（600、属主 10001）后重试。只有确认要放弃旧数据
（邀请码、证书去重、加密导入文件都将不可用）时，才由人工运行 `deploy/scripts/app-master-keygen.sh <密钥目录>`。
- `aia_api` / `aia_ingest` 对 `ops.pending_file_purges` 无任何权限；`verify-roles.sh` 断言 api/ingest 的
  “置 purging → 删不可变行 → 改回 → 提交”序列失败、aia_maint 不能改回 / 不删行提交、正规删除路径可提交。
- 删除用户数据（先 dry-run）：`deploy/scripts/compose.sh --profile maint run --rm --no-deps maint-cli --user-id <uuid> [--execute]`。
- 原始导入文件卷 `<卷前缀>_imports` 只挂给 api 与 maint-cli，挂载点跟随 `IMPORT_STORAGE_PATH`，卷根 10001:10001、700。
