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
- **主密钥要单独离线保存，不要和 dump 放在一起**（评审 1cf643e M2）：dump 里的邀请码 HMAC、证书去重指纹、
  导入文件密文都依赖 `$AIA_SECRETS_DIR/app_master_key`，丢了主密钥 dump 就恢复不出可用数据；但两者放在一起，
  拿到备份的人就同时拿到了解密能力。做法：主密钥按 600 拷到离线介质 / 密码管理器（与 dump 不同的位置、不同的权限），
  不打印、不入库、不进工单；dump 目录（`--out-dir`）里不放任何密钥文件。证书私钥（`data_licence_seal_*`）同理。
- **主密钥备份 / 核对 / 恢复脚本**（T-O12）：`deploy/scripts/app-master-key-backup.sh`
  - `backup --dest <离线目录>`：拷成 `app_master_key-<UTC>.key`（600）+ 同名 `.sha256`；目录在仓库里、是密钥目录本身、或里面有 `*.dump` 时拒绝。
  - `fingerprint`：打印 sha256（与下面手工命令同一口径）；`verify <备份>`：备份与当前主密钥是否同一把。
  - `restore <备份> --dir <密钥目录>`：目标已存在就拒绝（从不覆盖），先核对 `.sha256`，600、属主 10001。
  - `drill`：用假密钥在临时目录走一遍 备份→丢失→恢复→核对。
  - V1 不轮换主密钥（T-O11 裁定 ⑤）；轮换前提与方案见 reports/T-O12.md（需要后端先给加密数据加密钥编号）。
- **每次备份时记录主密钥的 sha256**（评审 8cf9771 n5；只记摘要，不记内容），写进备份记录（与 dump 同目录的
  `<dump>.keyhash.txt` 或运维台账），恢复 / 迁移时用它核对拷来的是不是同一把：
  ```bash
  sudo -n sha256sum "$AIA_SECRETS_DIR/app_master_key" | cut -d' ' -f1 > deploy/backups/aia-<UTC>.app_master_key.sha256
  ```
  只输出 64 位十六进制摘要；不要 `cat` / `xxd` / `od` 文件本身，也不要把命令加 `-x` 跑。
- **原始导入文件卷 `<卷前缀>_imports` 要和 dump 一起备份**（评审 8cf9771 n4）：`app.import_files` 只存元数据，
  文件本体（用主密钥派生密钥加密）在卷里；只恢复 dump 不恢复卷，导入记录会指向不存在的文件。
  ```bash
  docker run --rm --network none -v <卷前缀>_imports:/v:ro -v /data/backup:/out alpine:3.21 \
    tar -C /v -czf /out/imports-<UTC>.tgz .          # 产物 chmod 600；内容是密文，但仍与主密钥分开存放
  ```

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

**迁移到新主机 / 灾后恢复：先放主密钥，再 up**（评审 1cf643e M2）
1. 在新主机上**先**把原主机的 `$AIA_SECRETS_DIR/app_master_key` 从离线备份拷到同一路径（600、属主 10001）。
   主密钥只有这一份文件，api / worker 共用（plan e56462c 按服务分配：其余服务不挂）；以后若按服务拆分，就逐个拷各服务的密钥文件。
   证书私钥 / 公钥文件同理先拷（见 `data-licence-seal-keys.md`）。
   拷完先核对摘要：`sudo -n sha256sum … | cut -d' ' -f1` 与备份时记下的 `.app_master_key.sha256` 一致（只比对摘要，不打印值）。
2. **然后**才起服务，而且**先不启动 ingest**（评审 8cf9771 M1；plan §1.3）：
   `deploy/scripts/compose.sh up -d --wait --scale ingest=0`。
   麦蕊同一证书 60 秒内只认 2 个来源 IP，旧主机的 ingest 还在跑时新主机再起一个，就会触发 IP 超限（429 / 码 103）。
   **之后每一次 `up`（包括恢复后重建 api 等）都要带 `--scale ingest=0`**，直到第 5 步切换：不带的话 compose 会把 ingest 拉起来
   （ingest 的 `deploy.replicas: 1` 会生效，已实测）。
   主密钥这一步放在第 1 步之后的原因：新主机 up 时库是空的，`app-master-key-ensure.sh` 会合法地按“全新部署”生成一把新主密钥，
   restore 之后旧数据的 HMAC 与加密文件全部失效，而且不会报错。
3. `db-restore.sh` 恢复数据；**再恢复导入文件卷**（评审 8cf9771 n4；顺序：主密钥 → 库 → 导入卷）：
   ```bash
   docker run --rm --network none -v <卷前缀>_imports:/v -v /data/backup:/in:ro alpine:3.21 \
     sh -c 'tar -C /v -xzf /in/imports-<UTC>.tgz && chown -R 10001:10001 /v && chmod 700 /v'
   ```
   恢复前卷必须是空的（新主机上第 2 步起的空卷）；不要解压到已有文件的卷上。
4. 恢复后核对：`stat -c '%a %u'` 为 `600 10001`；主密钥摘要与备份记录一致；用既有邀请码 / 登录验证 HMAC 仍然一致；
   `app.import_files` 里的文件在卷里都能找到（抽查几条导入记录能打开原文件）。
5. **切换 ingest（按 plan §1.3 的顺序，不能并行）**：修改 `PUBLIC_BASE_URL` 与 DNS → **停止旧主机的 ingest**
   （旧主机 `compose.sh stop ingest`）→ **等待 ≥ 60 秒**（让旧 IP 滑出麦蕊的 60 秒窗口）→ 新主机 `compose.sh up -d --wait ingest`
   → 核对出口 IP（ingest 日志 / 麦蕊后台的来源 IP 只剩新主机）→ 从旧主机 `.env` 删除 licence。
   单台冷备切换的细节见 `deploy/runbooks/ingest-failover.md`（T-O07，尚未写好前以 plan §1.3 / §2.1A 为准）。
   迁移期间及之后，旧主机 / 开发机不得用同一证书做真实调用。
   **灾后恢复（旧主机已经没了、不会再有它的 ingest）**：可以跳过“停旧 ingest、等 60 秒”，第 2 步直接 `up -d --wait` 启动 ingest；
   但要先确认旧主机确实不再运行（关机 / 断网），拿不准就按迁移顺序做。
6. 已经误生成了新主密钥：停服务，用离线备份的原主密钥覆盖（先另存误生成的那份），再起服务；不要在新密钥下接受新数据。

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
| `app_master_key` | 后端 `APP_MASTER_KEY`（邀请码 / 证书 HMAC 等） | secret，**只挂 `api`、`worker`**（plan e56462c 按服务分配；两者共用同一把，worker 要解 api 写的密文）；入口包装 `deploy/docker/secret-env.sh` 在容器内转成环境变量。`ingest`（持证书私钥）设 `AIA_FORBID_APP_MASTER_KEY=1`，入口包装发现主密钥即拒绝启动；beat / signal-rt / maint-cli / migrate / 基础设施都不挂。CI 规则 7 用白名单 `MASTER_KEY_ALLOC` 校验，新增服务必须先登记 |

- 口令 / 密钥文件都在仓库外 `$AIA_SECRETS_DIR`（默认 `~/.config/aia/secrets/<卷前缀>`），600；`compose.sh` 缺失时生成（主密钥例外，见下文“APP_MASTER_KEY 迁移”），**已存在从不覆盖**。
  `db_password_aia_maint`、`app_master_key` 属主是容器用户 10001（生成时 sudo -n chown）。
- **换 APP_MASTER_KEY 会让既有邀请码哈希、证书 HMAC 失效**：只能在确认无存量数据或有迁移方案时人工删文件重建。

### APP_MASTER_KEY 迁移与升级约束（T-O11 评审 M1/M2，plan e56462c ①–⑤）

`compose.sh` 不直接生成主密钥；**每次调用**都先跑 `deploy/scripts/app-master-key-ensure.sh` 判定（文件已存在也要做④的比对）：

| 情况 | 行为 |
|---|---|
| ④ 文件已存在，旧来源（调用方环境或 `deploy/env/.env`）没有非占位值 | 直接用（为空则拒绝，不覆盖） |
| ④ 文件已存在，旧来源有值且一致 | 用文件，提示从 `.env` 删除那一行（不自动删） |
| ④ 文件已存在，旧来源有值但不一致（或读不到文件无法比对） | **拒绝启动**（退出 3），等人工确认用哪把；两边都不改、不打印 |
| ② 文件不存在，旧来源有非占位值 | 迁移进密钥文件（600，属主 10001，不打印），提示从 `.env` 删除该行（不自动删）。环境与 `.env` 两处不一致、或短于 32 字符 → 拒绝 |
| ③ 两边都没有，`app.users` / `app.invite_codes` / `app.user_data_licences` 任一有行（保守加查 `app.import_files`、`app.llm_providers` 里非空的 `api_key_ciphertext`、导入卷里的文件） | **拒绝启动**（退出 3），提示从备份恢复主密钥 |
| ③ 两边都没有，数据卷存在但 postgres 没在跑 / 查不了 / docker 不可用 | 无法确认是空库 → 拒绝（fail-closed） |
| ① 两边都没有，数据卷不存在，或上述表都不存在 / 都为空（`llm_providers` 没有密文），导入卷为空 | 全新部署：生成新主密钥（`app-master-keygen.sh`） |
| ⑤ 主密钥轮换 | 不在 V1 范围，脚本从不替换已有文件 |

占位值（空、含 `<` `>`、`changeme` / `example` 开头）视为没有；判断用的是按 compose 规则**解析后的值**，
行尾注释里的 `<` `>` 不算（评审 8cf9771 m1）。api / worker 另设 `AIA_REQUIRE_APP_MASTER_KEY=1`：
secret 没挂上时 `secret-env.sh` 拒绝启动，后端不会回落到临时随机主密钥。

升级旧部署：
1. 先备份库与 `.env`（`deploy/scripts/db-backup.sh`）；
2. 主密钥原来在 `.env`、文件不存在：`compose.sh up …` 时自动迁移，看到“已从 … 迁移”；
   主密钥文件已存在（如 aia-t01）：`.env` 里只有占位值时直接用；有真实值时必须与文件一致，否则拒绝；
3. 验证：`stat -c '%a %u' $AIA_SECRETS_DIR/app_master_key` 为 `600 10001`；用既有邀请码 / 登录验证 HMAC 仍然一致；
4. 确认无误后，从 `.env` 删除 `APP_MASTER_KEY` 行（compose 已不读它）。

排错时不要用 `bash -x` 跑 `compose.sh` / `app-master-key-ensure.sh` / `app-master-keygen.sh` / `db-role-passwords.sh`：
这些脚本开头都会强制 `set +x`（评审 8cf9771 m3），但别的包装脚本加了 `-x` 仍可能把口令打到终端；看判定过程读 stderr 的中文说明即可。
`compose.sh` 只对只读子命令（`ps` `logs` `config` `down` `stop` `exec` 等白名单）把主密钥检查降为告警，其余子命令（含认不出的）
检查不过即拒绝（评审 8cf9771 n1）。

被拒绝时：从备份 / 原部署机找回原主密钥，写入密钥文件（600、属主 10001）后重试。只有确认要放弃旧数据
（邀请码、证书去重、加密导入文件都将不可用）时，才由人工运行 `deploy/scripts/app-master-keygen.sh <密钥目录>`。
- `aia_api` / `aia_ingest` 对 `ops.pending_file_purges` 无任何权限；`verify-roles.sh` 断言 api/ingest 的
  “置 purging → 删不可变行 → 改回 → 提交”序列失败、aia_maint 不能改回 / 不删行提交、正规删除路径可提交。
- 删除用户数据（先 dry-run）：`deploy/scripts/compose.sh --profile maint run --rm --no-deps maint-cli --user-id <uuid> [--execute]`。
- 原始导入文件卷 `<卷前缀>_imports` 只挂给 api 与 maint-cli，挂载点跟随 `IMPORT_STORAGE_PATH`，卷根 10001:10001、700。

## 7. 迁移 0017 预检查（T-B49；review-6670b10）

0017 给 `app.data_snapshots` 加约束：`purpose IN ('candidate','plan','horizon')` 时 `user_id` 必须非空。
**任何共享库（含 aia-t01）升级到 0017 之前**，先只读查违规行；查到就停下，不跑 0017，交后端/架构师按报告 T-B49.md 人工处理。

```bash
deploy/scripts/db-precheck-0017.sh            # 0 可以升级 / 1 有违规行（停止）/ 2 出错
```

- SQL 与迁移里的 `PRECHECK_SQL` 相同，在只读事务里执行，只输出 purpose 和行数。
- 已在 0017 或之后、空库、没有 `app.data_snapshots` 时直接返回 0。
- `up.sh` 在仓库带 0017 迁移且 postgres 已在运行时自动先跑它，不通过就不执行 up；
  postgres 没在运行时由迁移自身的预检查兜底（报错退出、不改数据）。
- 不要主动升级到 0017：只有按发布计划部署新版本时才会经 `migrate` 升级。
