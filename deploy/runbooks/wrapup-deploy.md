# 收口部署（T-O69 / T-O69c）

把 `/workspace/team/reports/T-O57-deploy-plan.md` 更新到当前主线后的可执行方案。脚本在 `deploy/scripts/wrapup/`。默认**干跑**；会写入或有破坏性的步骤必须加 `--apply`。失败即停，并打印回滚提示。不要打印密钥、DSN、证书。

**Windows：下列命令在 WSL 或 Git Bash 里执行**（不要用 cmd.exe）。`${NGINX_HTTP_PORT:-8080}` 是 bash 写法。

依据 `/workspace/team/rules/standing-auth-2026-11-08.md`：用户已长期授权收口时部署到其电脑（先备份，失败回滚，绝不 `down -v`），主数据拉取也在 11-08 授权过。`--apply` 不再需要用户逐步确认，改为收口时由编排者下令。本工作树任务本身仍只写文档和脚本，不直接在用户电脑上执行。

## 红线

不要 `down -v`，不要 `prune`，不要 `git reset` / `--force` / rebase，不要删别人的卷，不要动受保护实例（o53 / o55 / o57 / o60 / o61）或收口用的空匿名卷。不要调麦蕊。不要 stamp / downgrade 来「对齐」0029 分叉（T-A70）。主数据首次导入**只许**走 `deploy/scripts/master-bootstrap.sh`（保留 `--check`、flock、`--confirm-network-fetch`、CI 拒绝），不要 `compose.sh --profile master-bootstrap run …`（会绕过上述入口，T-A98 B2）。rc=0 时的离线词表只许用本文「主数据首次导入与词表」里的 worker 命令，不要用 maint-cli。

## 已知环境与出处

- 用户电脑（2026-11-09 memory / T-O57 方案）：WIN-SPD6GD4H42E，`F:\ashare-invest-assistant`，compose 项目 `aia-local`，经 WSL。当时 HEAD 为 team-b 的 `f82a83b1817ed2c2388a09602f213a34aa0b93f9`，有未跟踪 `src/backend/migrations/versions/0029_*.py`，`git hash-object` 应为 `05774fed18ab70e4ff506c3178107d03b854d31c`（T-O58 已核）。
- **停机目录不可写退出 78**：`docs/api-contract.md`（T-A91 M-c：bootstrap 对停机目录 O_EXCL 探测，不可写则 78）；实现 `src/backend/app/workers/ingest.py` 中 `_probe_halt_directory` / `main`；报告 T-A91、T-B116d、T-T56、T-T57。目录为 `/run/aia/state/halt/`，卷 `<前缀>_ingest_state`，属主 10001、权限 700。文案含「停机标志目录不可写」，不碰已有 HALT 文件。
- **仓库太旧时 dry-run 退出 1**：`src/backend/probes/run_all.py --dry-run` 在当前基线上应为退出 0（T-B05-run-howto、T-T61）。T-B117 记录过退出码 1：当时运行树/环境与已合入基线不一致，两条 p13 mock 失败；在当前基线复跑为 0。用户机若仍停在 `f82a83b`，直接跑 dry-run 可能得到退出码 1，须先按第 2 步更新代码，不能 reset。

收口头哈希由编排者在合入后批准，脚本用 `--target <完整哈希>`，不要用活的分支名代替。

## 脚本一览

```bash
deploy/scripts/wrapup/wrapup.sh preflight
deploy/scripts/wrapup/backup.sh --apply --backup-dir <仓库外父目录>
# 标准输出最后一行是本轮 DEST，例如 /data/aia-wrapup-backup/20261110T061858Z
# 后续 --apply 必须把 --backup-dir 指到这个时间戳目录，不能指父目录或兄弟旧轮。
deploy/scripts/wrapup/update-repo.sh --apply --target <批准哈希> --backup-dir <本轮 DEST 时间戳目录>
deploy/scripts/wrapup/start-stack.sh --apply --backup-dir <本轮 DEST 时间戳目录>
deploy/scripts/wrapup/halt-check.sh --apply          # 不可写则 rc=78；修复加 --repair（不删已有 HALT）
deploy/scripts/wrapup/net-verify.sh --apply          # 只打 1.1.1.1 / example.com
deploy/scripts/wrapup/verify.sh --apply
deploy/scripts/wrapup/rollback.sh --apply --backup-dir <本轮 DEST 时间戳目录>   # 由编排者下令；失败须停下来问编排者
```

公共选项：`--volume-prefix`、`--container`、`--db`、`--volume`、`--rollback-head`（默认即上面的 f82a83b）。

## 当天只读确认（先做；--apply 由编排者在收口时下令）

在用户机仓库（WSL 路径）里：

1. `git rev-parse HEAD`、`git status`。是否仍有未跟踪 `0029_*.py`；`git hash-object` 是否等于 `05774fe…`。其它脏文件先停手。
2. 只读看库 `alembic_version`、`ingest_private` 是否存在（只计数）。若库已在 0029 而定义与将要合入的链不一致 → **停手**（T-A70），不 stamp、不 downgrade、不 down -v。
3. 记录卷前缀、镜像 tag、磁盘空间；不要改 `.env`，不要把 `.env` 贴进工单。
4. 跑一遍脚本 **不带** `--apply`，确认打印的计划正确。

## 1. 备份与回滚

```bash
# 建议 --backup-dir 放在仓库外（deploy/backups/ 已 gitignore，但仍以仓库外为佳）
deploy/scripts/wrapup/backup.sh --apply --backup-dir /data/aia-wrapup-backup
```

会做：`db-backup.sh` 的 `pg_dump -Fc` + `.meta.json`；具名卷快照（`ingest_state`、`aia_receipts`、`imports`、`master`、`redisdata`，**不对运行中的 pgdata 打原始包**）；记录当前提交、`git status`、镜像 tag，以及主密钥 **sha256 摘要**（密钥本身不进备份目录，见 `database.md` §4）。

回滚（由编排者在收口时下令；若回滚失败必须停下来问编排者）：

```bash
deploy/scripts/wrapup/rollback.sh --apply --backup-dir /data/aia-wrapup-backup/<时间戳>
```

完整步骤：dump 恢复到**新库名**（绝不 `--drop-existing` 主库）；卷恢复到**新卷名**（不 `volume rm` 现网卷、不 down -v）；在新 worktree 检出 `f82a83b1817ed2c2388a09602f213a34aa0b93f9`（或备份当时的 HEAD），把 0029 未跟踪副本放回工作区（不丢失、不 reset 原树）。然后由编排者下令把服务切回旧工作树 / 新库名，只重启必要服务。若要删除数据或卷，必须先停下来问编排者。0029 有绑定行时降级会被永久拒绝（T-A70），不能指望 downgrade 回滚。

## 2. 仓库太旧（dry-run 退出 1）时如何更新

先停 api / worker / ingest（热重载），postgres / redis 可留。再：

```bash
deploy/scripts/wrapup/update-repo.sh --apply --target <批准的完整哈希> --backup-dir /data/aia-wrapup-backup/<backup.sh 本轮打印的时间戳>
```

脚本会：未跟踪 0029 若 hash 等于已知 blob，先**复制到仓库外**再从工作区移走（不删除唯一副本、不 reset）；其它脏文件停手；`git fetch` 后若可快进则 `merge --ff-only`，否则**新建 worktree** 检出目标哈希，原工作树不动。新工作树必须沿用原来的 `COMPOSE_PROJECT_NAME` / `AIA_VOLUME_PREFIX`（只看 `deploy/env/.env`，不要把含密钥的文件贴进工单）。

更新后再跑 `python run_all.py --dry-run`（`env -u MAIRUI_LICENCE`）应为退出 0。这不是收口必跑，但可解释「太旧 → 退出 1」。

## 3. 新网络层在 Windows Docker Desktop 上的启动顺序

`internal` / `egress` / `edge` 在 `compose up` 时创建，不要为「换网」而 `down -v`。

```bash
deploy/scripts/wrapup/start-stack.sh --apply --backup-dir /data/aia-wrapup-backup/<backup.sh 本轮打印的时间戳>
```

顺序由 `start-stack.sh --apply` 执行（与 `up.sh` / compose `depends_on` 一致，并在启动 worker 之前插入 engine_policy seed）：

1. postgres、redis（等到 healthy）
2. **migrate**（`alembic upgrade head`）
3. timescale-apply
4. **db-roles**（`apply-roles.sh`）
5. **engine_policy seed**（脚本执行，见「engine_policy seed」节；不要再手动跑一遍）
6. 再启 api / worker / beat / ingest / signal-rt / nginx

不要加 `--profile master-bootstrap`。默认 dev/live 不会启动该服务。正式卡 `--apply` 导入目前仍是「待补」，分两个阶段，见「正式卡 `--apply` 导入（待补）」节。

## 4. HALT 目录可写检查

卷 `<前缀>_ingest_state` 挂到 `/run/aia/state/`，`halt/` 须为 uid **10001**、模式 **700**。不可写时 ingest 启动退出 **78**。

```bash
deploy/scripts/wrapup/halt-check.sh                  # dry-run：只 stat
deploy/scripts/wrapup/halt-check.sh --apply          # uid 10001 探测（建完即删 .probe-*，不碰 HALT）
# 若 rc=78：
deploy/scripts/wrapup/halt-check.sh --apply --repair
```

修复用一次性 root 容器 `install -d -o 10001 -m 700`，**不删除**已有停机标志。解除停机标志（以及恢复出口）必须由用户本人确认后再做，见 `ingest-halt.md`、`receipts.md` 与契约（`docs/api-contract.md` 约 1406 / 1411 行）。只删收据文件或停机标志文件都不能恢复出口；编排者不能代替用户本人确认解除。

## 5. 网络实测

按 `deploy/runbooks/networks.md`（第 1–8 步）。可先：

```bash
deploy/scripts/wrapup/net-verify.sh --apply
```

脚本覆盖能自动跑的部分。其余（服务名 DNS、局域网 IP 不可达、Docker Desktop 伪装开关、WSL mirrored、`Get-NetTCPConnection`）以手册命令和判定为准。

只许探测 `http://1.1.1.1` 或 `https://example.com`。**绝不调麦蕊。** 无客户端时看输出是否含 `NO_HTTP_CLIENT`，不要只看 rc=2。

## 6. 验证清单

```bash
deploy/scripts/wrapup/verify.sh --apply
```

须同时满足：

- `verify-roles.sh`：有 OK 行，**FAIL 0、SKIP 0**，退出码 0
- `alembic heads` 只有一个 head，且 `current` 指向它
- `http://127.0.0.1:${NGINX_HTTP_PORT:-8080}/health/live` 为 200；抽查 `/`、`/login`
- 收据卷 `<前缀>_aia_receipts`：目录 `root:root 755`，文件 `root:root 644`，ingest/worker `:ro`。只删收据文件不能恢复出口（`receipts.md`）
- engine_policy / H-01 的只读 SQL 见「部署后只读 SQL 验证清单」：`app.engine_policies` 最新 `version_no=3`；H-01（库内 `app.strategy_cards.key='hold_risk_monitor'`）最新版=3；持仓实例按 `COALESCE(derived_strategy_version_id, strategy_version_id)` 指向 v3 行；`app.strategy_promotion_reviews` 中有 `decision='approved'` 且 `target_strategy_version_id` 指向 H-01 v3 的行

## 主数据首次导入与词表（只走指定入口）

顺序：先完成第 1 节备份、第 3 节启栈，再执行下面的 `--check`。不要在栈未起来时跑首导或词表重建。不调麦蕊、不把交易所探测以外的流量打出去。

```bash
deploy/scripts/master-bootstrap.sh --check; echo "rc=$?"
```

按退出码分支（**其它 rc 一律停止**，不要改库、不要出网；含义见 `master-data.md`）：

- **rc=10**（还没有 `status='ok'` 的 `market.master_runs`）：确认本机可访问上交所、深交所、北交所官网后，一次导入并在合并来源后重建词表（后端 `app.cli master-bootstrap` 默认不写词表，须显式 `--rebuild-search-terms`）：

  ```bash
  deploy/scripts/master-bootstrap.sh --run --confirm-network-fetch --rebuild-search-terms
  ```

  不要 `compose.sh --profile master-bootstrap run …`（会绕过 `--check`、flock、`--confirm-network-fetch` 和 CI 拒绝，T-A98 B2）。跑完应看到已有 `status='ok'` 的主数据同步记录，再做下面的只读验证。网关对外开放前须看到该记录。

- **rc=0**（已有成功导入，从 `f82a83b` 升级时常见）。此时再跑 `--run --rebuild-search-terms` 会因脚本幂等在检查阶段跳过，到不了重建。改为在**不出网的 worker**（只挂 `aia_internal`，无 egress）上跑离线 CLI。模块是 `python -m app.cli.security_search_terms`（它不在 `python -m app.cli` 的子命令表里）。默认即 dry-run：校验配置后退出，不访问数据库、不写库；写入须加 `--apply`（依赖容器内已有 `DATABASE_URL`，worker 的 compose 环境已提供）。保留默认 entrypoint（不要加 `--entrypoint python`，以免绕过 `secret-env.sh`）。**不要用 maint-cli。** 先 dry-run，确认输出含 `dry-run` 且退出码 0，再 `--apply`：

  ```bash
  deploy/scripts/compose.sh run --rm --no-deps -T worker sh -c 'python -m app.cli.security_search_terms'
  deploy/scripts/compose.sh run --rm --no-deps -T worker sh -c 'python -m app.cli.security_search_terms --apply'
  ```

  `terms.rebuild` 只在调用方事务内写词表，幂等、不出网。升级本身不强制重建；本步骤用于补写默认首导未写的词表。

- **其它 rc**（例如 2 用法错、3 未就绪、1 查询失败）：停止，不要继续 `--run` 或离线 `--apply`。

### 只读验证词表

在已启动的 postgres 上跑（只读事务）。词表行数通常大于证券行数（一只证券多条 term）；对齐看去重 `code`：`terms_distinct_codes` 应等于 `securities_distinct_codes`，缺词查询应为空。抽查 `term_kind` 须属于 `name` / `name_initials` / `former_name` / `former_initials` / `former_code`（不是每种都必然出现）。`generator_version` 必须全部为 1。

```bash
deploy/scripts/compose.sh exec -T postgres \
  sh -c 'exec psql -X -q -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-postgres}"' <<'SQL'
BEGIN READ ONLY;

SELECT 'securities_rows' AS metric, count(*)::bigint AS n FROM market.securities
UNION ALL
SELECT 'securities_distinct_codes', count(DISTINCT code) FROM market.securities
UNION ALL
SELECT 'terms_rows', count(*) FROM market.security_search_terms
UNION ALL
SELECT 'terms_distinct_codes', count(DISTINCT code) FROM market.security_search_terms;

SELECT s.code
FROM market.securities s
LEFT JOIN market.security_search_terms t ON t.code = s.code
WHERE t.code IS NULL
ORDER BY 1
LIMIT 20;

SELECT term_kind, count(*) AS n
FROM market.security_search_terms
GROUP BY 1
ORDER BY 1;

SELECT generator_version, count(*) AS n
FROM market.security_search_terms
GROUP BY 1
ORDER BY 1;

ROLLBACK;
SQL
```

## engine_policy seed（由 start-stack.sh 在 migrate/db-roles 之后、worker 启动之前执行）

收口时用第 3 节的 `start-stack.sh --apply`：脚本在 db-roles 之后、启动常驻 worker 之前执行 seed，不要再手工先 seed 再单独 `compose.sh up` worker。seed **不会**在 migrate 或容器启动检查时自动执行（`migration_check` 只做同号守卫、缺行放行；`cards-import` 也不调 seed）。要写入的是镜像内现行 `config/engine_policy.yaml` 的 `version_no`（升 3 之后须在下次 `--apply` 启栈时由脚本重跑，插入 v3 新行；v1/v2 旧行保留不动，不可删除）。脚本用 `compose run --no-deps` 起一次性容器，不会把常驻 worker 提前拉起来。

入口（只读核对 `src/backend/app/engine_policies.py`）：`python -m app.engine_policies --database-url`（`--database-url` 为必填；模块不在 `python -m app.cli` 子命令表里）。CLI 从 `Settings.config_dir` 读取现行 yaml（容器内默认 `/app/config`，worker 已只读挂载）。成功时只打印一行 `engine_policy_seed_inserted=`，值为 `1`（本号不存在，已 INSERT）或 `0`（同号且 `config` 含相同 `content_sha256`，幂等、不写新行）。同号但内容/摘要不同会抛 `ValueError("engine_policy_version_hash_conflict")` 并以非 0 退出，**没有**名为 `hash_conflict` 的输出字段。

表是 `app.engine_policies`（迁移 0001 建表，无政策 INSERT）。列是 `id`、`version_no`、`config`、`published_at`、`created_at`。**没有**独立的 `content_sha256` 列；摘要在 `config->>'content_sha256'`。

### 1. 只读列出已有行

在已启动的 postgres 上跑（只读事务；不要打印连接串或密钥）：

```bash
deploy/scripts/compose.sh exec -T postgres \
  sh -c 'exec psql -X -q -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-postgres}"' <<'SQL'
BEGIN READ ONLY;

SELECT version_no,
       config->>'content_sha256' AS content_sha256,
       created_at
FROM app.engine_policies
ORDER BY version_no;

ROLLBACK;
SQL
```

部署前先看现有几行、最大号是多少。不要改这些旧行。

### 2. 由 start-stack.sh 在 worker 容器内跑 seed

下面是脚本实际执行的命令，不要改写成加 `--entrypoint` 的版本，也不要在脚本之外再跑一遍。DSN 只在容器内从环境变量 `DATABASE_URL` 展开（worker 的 compose 环境已提供），**不要**在宿主机命令行写明文 DSN，不要 `echo` / 打印该变量或连接串，不要 `set -x`（默认入口 `deploy/docker/secret-env.sh` 开头也会关掉继承来的 xtrace，避免把密钥或 DSN 打到 stderr）。

保留 worker 默认 entrypoint（compose 为 `sh /aia/secret-env.sh`）。该脚本注入 `APP_MASTER_KEY` 后执行 `exec "$@"`，会把后面的参数作为命令原样执行。不要加 `--entrypoint sh`（会绕过 secret-env.sh；用户机若 `APP_ENV` 为 staging/production，Settings 会因缺 `APP_MASTER_KEY` 拒绝）。

```bash
deploy/scripts/compose.sh run --rm --no-deps -T worker sh -c \
  'python -m app.engine_policies --database-url "$DATABASE_URL"'
```

脚本只认标准输出整段为 `engine_policy_seed_inserted=0` 或 `engine_policy_seed_inserted=1`，并把该行写入本轮备份 DEST 的 `engine_policy_seed.txt`（与 manifest、git-head 等同一套本轮收据）。dry-run 只打印这一步，不执行、不写收据。

### 3. 判定

- 首跑（库中还没有现行 yaml 的 `version_no`）：标准输出为 `engine_policy_seed_inserted=1`，退出码 0。
- 重跑（同号同摘要）：`engine_policy_seed_inserted=0`，退出码 0。
- 出现 `engine_policy_version_hash_conflict`（同号异摘要）：脚本**立即停止，不启动 worker**，不要重试、不要改旧行、**不要删除旧行**、不要手工 INSERT，问编排者。
- 其它非 0 退出，或输出无法解析为 `engine_policy_seed_inserted=0` / `1`：同样停止，不启动 worker，不删行。

### 4. 确认最新号与首条建议

seed 成功后再只读复查：`app.engine_policies` 按 `version_no` 降序的第一行须为 **3**。下一轮作业之后，再核**新写出的**第一条建议：`app.suggestions.engine_policy_id` 对应的 `app.engine_policies.version_no` 须为 **3**（SQL 见下一节）。不要把历史建议的旧号当成失败。

漏做 seed 的后果（T-A119）：库中完全没有政策行时，全部标的会记 `engine_policy_seed_missing` gap、不出建议；库中只有 v2 时会静默按 v2 运行，与审批的 v3 不符。

### 正式卡 `--apply` 导入（待补）

正式卡的 `--apply` 导入步骤**目前还没有**，此处标为「待补」，不要在本手册里用临时命令凑一套写入路径。实际入口是 `python -m app.cli.cards_import`（`--card` / `--catalog` / `--market-rules` 等；`--apply` 才写库，且从环境变量读 `DATABASE_URL`，缺则拒绝）。镜像不含 `docs/`，导入须另挂正式卡目录。**这一步导入须用户本人授权，不在 `standing-auth-2026-11-08.md` 范围内**；编排者不得在未获用户本人授权时下令 `--apply`。

只读核对：`src/backend/app/strategy/cards/persistence.py` 在同卡同 `version_no` 且 `fields` 不等时抛 `ValueError("immutable_card_version_conflict")`（:118-120）；`cards_import.py` 的 `--apply` 在 `engine.begin()` 单事务里调用 `import_batch`（:64-71），一张卡冲突会让整批回滚。S-01（文件 `st_pullback_ma.md`）曾在 `version_no=1` 不变的情况下改过内容，再导 v1 会触发该冲突，H-01 v3 也会导不进。导入清单分两个阶段，**以部署树 / 即将部署的 main 上现行卡 `docs/strategies/cards/st_pullback_ma.md` 的 `version_no` 为准**（不要拣入未入 main 的研究分支）：

- **阶段一（S-01 v2 尚未进入 main）**：现行 `st_pullback_ma.md` 仍是 `version_no: 1`。正式导入白名单**只能含** `hold_risk_monitor.md`（H-01）和 `sw_ma_trend_pullback.md`（W-01）。不得列入 `st_pullback_ma.md`，也不得导入 `docs/strategies/cards/history/` 下的冻结稿。
- **阶段二（S-01 v2 已进入 main）**：现行 `st_pullback_ma.md` 的 `version_no` 为 **2**（v1 冻结在 `docs/strategies/cards/history/st_pullback_ma.v1.md`，只作历史，**不要导入 history 文件**）。导入清单可以加上 `st_pullback_ma.md`（v2）。v2 是新版本行，不会与库内已有 v1 触发同号冲突。导入完成后用下一节「阶段二」只读 SQL 核验。

`deploy/` 下没有正式卡导入脚本入口，阶段切换只写在本手册，不靠脚本参数。

### 部署后只读 SQL 验证清单

在已启动的 postgres 上跑（只读事务）。表名、列名和 `decision` 状态值以 `src/backend/app/db/tables/strategy.py`、`realtime.py` 与迁移 0001 为准。正式卡对外编号是 **H-01** / **W-01** / **S-01**，库里头表键分别是 `hold_risk_monitor` / `sw_ma_trend_pullback` / `st_pullback_ma`（文档字段 `card_id` 在版本 `fields` 里，**不是** `strategy_card_versions.card_id` 列——该列是指向头表的 UUID）。H-01 各项在每次收口都核。S-01 的三项（`version_no=2`、`source_hash` 与 v2 文件一致、v1 审核不再作数）**只在阶段二、v2 已导入之后**再核；阶段一不要把「没有 S-01 v2 行」当成失败。

```bash
deploy/scripts/compose.sh exec -T postgres \
  sh -c 'exec psql -X -q -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-postgres}"' <<'SQL'
BEGIN READ ONLY;

-- H-01 最新版=3（库内 key=hold_risk_monitor）
SELECT c.key,
       max(cv.version_no) AS latest_card_version_no,
       max(sv.version_no) AS latest_strategy_version_no
FROM app.strategy_cards c
JOIN app.strategy_card_versions cv ON cv.card_id = c.id
LEFT JOIN app.strategy_versions sv ON sv.card_version_id = cv.id
WHERE c.key = 'hold_risk_monitor'
GROUP BY c.key;

-- 持仓实例：运行时取 COALESCE(derived_strategy_version_id, strategy_version_id)
-- （与 src/backend/app/workers/daily.py:80、intraday/engine.py:293 一致）
SELECT i.id,
       i.status,
       i.strategy_version_id,
       i.derived_strategy_version_id,
       COALESCE(i.derived_strategy_version_id, i.strategy_version_id) AS effective_strategy_version_id,
       sv.version_no AS effective_version_no
FROM app.strategy_instances i
JOIN app.strategy_versions base ON base.id = i.strategy_version_id
JOIN app.strategies s ON s.id = base.strategy_id
JOIN app.strategy_versions sv
  ON sv.id = COALESCE(i.derived_strategy_version_id, i.strategy_version_id)
WHERE s.key = 'hold_risk_monitor'
ORDER BY sv.version_no, i.created_at;

-- G7：已批准且 target_strategy_version_id 指向 H-01 v3 的行
-- decision 取值以迁移 0001 CHECK / strategy.py:416 为准：pending、approved、rejected、changes_requested
SELECT r.id,
       r.decision,
       r.target_strategy_version_id,
       r.card_version_id,
       r.reviewed_at,
       sv.version_no,
       s.key
FROM app.strategy_promotion_reviews r
JOIN app.strategy_versions sv ON sv.id = r.target_strategy_version_id
JOIN app.strategies s ON s.id = sv.strategy_id
WHERE r.decision = 'approved'
  AND s.key = 'hold_risk_monitor'
  AND sv.version_no = 3
ORDER BY r.reviewed_at NULLS LAST, r.created_at;

-- engine_policies 最新=3
SELECT version_no,
       config->>'content_sha256' AS content_sha256,
       created_at
FROM app.engine_policies
ORDER BY version_no DESC
LIMIT 1;

-- 下一轮作业后核首条新建议的政策号（按 created_at 新到旧；期望新行 version_no=3）
SELECT s.id,
       s.created_at,
       ep.version_no AS engine_policy_version_no
FROM app.suggestions s
LEFT JOIN app.engine_policies ep ON ep.id = s.engine_policy_id
ORDER BY s.created_at DESC
LIMIT 5;

-- ----- 阶段二才跑：S-01 v2 -----
-- S-01 最新版须为 2（库内 key=st_pullback_ma）
SELECT c.key,
       max(cv.version_no) AS latest_card_version_no,
       max(sv.version_no) AS latest_strategy_version_no
FROM app.strategy_cards c
JOIN app.strategy_card_versions cv ON cv.card_id = c.id
LEFT JOIN app.strategy_versions sv ON sv.card_version_id = cv.id
WHERE c.key = 'st_pullback_ma'
GROUP BY c.key;

-- v2 行的 source_hash。导入器写法是
-- hashlib.sha256(Path.read_text(encoding="utf-8").encode()).hexdigest()
-- （cards_import.py:30，importing.py:103），存在 strategy_card_versions.fields->>'source_hash'。
-- 这与 reviews.py:35 的 content_sha256（卡字段+策略配置的 JSON 摘要）不是同一个值。
SELECT cv.version_no,
       cv.fields->>'source_hash' AS source_hash
FROM app.strategy_cards c
JOIN app.strategy_card_versions cv ON cv.card_id = c.id
WHERE c.key = 'st_pullback_ma'
  AND cv.version_no = 2;

-- v1 审核「不再作数」：strategy_promotion_reviews 没有 voided / 作废列，
-- decision 取值仍只有 pending、approved、rejected、changes_requested（strategy.py:416）。
-- 读时由 reviews.py:86-113 计算 stale：current_version 取该卡
-- version_no 降序的最新 strategy_versions.id；binding.version_id 与之不等则为
-- stale_reason='new_version'，require_approved 会拒绝用它晋级。
-- 阶段二导入 v2 后，指向 version_no=1 的行 is_current_target 必须为 false。
-- 不要 UPDATE / DELETE 这些旧行。指向 v2 的新 G7 是另一次审核，没有 approved 行
-- 只说明 v2 尚未批准，并不表示 v1 审核仍可作数。
SELECT r.id,
       r.decision,
       r.target_strategy_version_id,
       r.card_version_id,
       r.reviewed_at,
       sv.version_no AS target_version_no,
       r.compliance_lint->'binding'->>'version_id' AS bound_version_id,
       cur.id AS current_strategy_version_id,
       (r.target_strategy_version_id = cur.id) AS is_current_target
FROM app.strategy_promotion_reviews r
JOIN app.strategy_versions sv ON sv.id = r.target_strategy_version_id
JOIN app.strategies s ON s.id = sv.strategy_id
CROSS JOIN LATERAL (
  SELECT sv2.id
  FROM app.strategy_versions sv2
  JOIN app.strategy_card_versions cv2 ON cv2.id = sv2.card_version_id
  JOIN app.strategy_cards c2 ON c2.id = cv2.card_id
  WHERE c2.key = 'st_pullback_ma'
  ORDER BY cv2.version_no DESC, sv2.version_no DESC, sv2.id DESC
  LIMIT 1
) cur
WHERE s.key = 'st_pullback_ma'
ORDER BY sv.version_no, r.reviewed_at NULLS LAST, r.created_at;

ROLLBACK;
SQL
```

在同一台已挂出仓库树的机器上，用与导入器相同的方式算 v2 文件摘要，再和上面 `source_hash` 比对（只哈希现行 `docs/strategies/cards/st_pullback_ma.md`，不要用 `history/st_pullback_ma.v1.md`；先确认该文件 `version_no` 为 2）：

```bash
# WSL Ubuntu 默认没有 python 命令；优先 python3，没有再回落到 python（同 networks.md 出网探测写法）
if command -v python3 >/dev/null 2>&1; then
  python3 -c 'from pathlib import Path; import hashlib; p=Path("docs/strategies/cards/st_pullback_ma.md"); print(hashlib.sha256(p.read_text(encoding="utf-8").encode()).hexdigest())'
elif command -v python >/dev/null 2>&1; then
  python -c 'from pathlib import Path; import hashlib; p=Path("docs/strategies/cards/st_pullback_ma.md"); print(hashlib.sha256(p.read_text(encoding="utf-8").encode()).hexdigest())'
else
  echo "需要 python3 或 python" >&2
  exit 2
fi
```

判定：

- H-01：`latest_card_version_no` 与 `latest_strategy_version_no` 均为 **3**。若该 key 还没有行，说明正式卡尚未导入（见上文「待补」），不要把空结果当成已通过。
- 持仓实例：有效版本 `COALESCE(derived_strategy_version_id, strategy_version_id)` 应指向 `version_no=3` 的行。若仍有实例的有效版本为 v2，按 T-A119 会继续跑 v2；记下这些行，不要改 `strategy_version_id` / `derived_strategy_version_id`，问编排者是否接受。
- G7 审批：`app.strategy_promotion_reviews` 中至少有一行 `decision='approved'`，且 `target_strategy_version_id` 等于 H-01（`key='hold_risk_monitor'`）`version_no=3` 的 `app.strategy_versions.id`。没有这样的行则不要当成已通过（正式卡导入或审批可能尚未完成）。
- `app.engine_policies` 最大 `version_no` 须为 **3**。
- 首条**新**建议的 `engine_policy_version_no` 须为 **3**（在下一轮作业之后再核）。
- **阶段二 / S-01**：`latest_card_version_no` 与 `latest_strategy_version_no` 均为 **2**。v2 行的 `fields->>'source_hash'` 必须与上面这条 Python 命令对现行 `st_pullback_ma.md` 的输出一致。指向 `target_version_no=1` 的审核行 `is_current_target` 必须为 **false**（即已 stale，`stale_reason` 为 `new_version`），这就是库内「v1 审核不再作数」的表示——不是改 `decision`、也没有作废列。不要删改这些旧行。若还没有指向 v2 的 `decision='approved'` 行，只说明 v2 的 G7 尚未完成，不得把 v1 的已批准行当成现行审核。

## 授权口径与必须停下来问编排者的情况

依据：该文件（`standing-auth-2026-11-08.md`）原话与编排者 2026-11-10 裁定。该文件记载用户本人原话「给你们最高授权，以后类似操作都无需问询」，范围包括「部署到用户本地电脑（先备份数据库，失败回滚，绝不 down -v）」。engine_policy seed 是只插入、幂等的版本配置行，属于上述「部署到用户本地电脑」步骤，因此在该授权范围内，由编排者在收口时下令即可，不必逐步再问用户。出现 `engine_policy_version_hash_conflict` 立即停止，**不删除旧行**，问编排者。正式卡 v3 的 `--apply` 导入**不在**该范围内，仍须用户本人授权；步骤仍为「待补」，编排者不得在未获用户本人授权时下令 `--apply`。

主数据首次导入（三所官网公开 HTTPS）也在 11-08 授权过。因此备份、迁 0029、更新代码、启停服务、halt 目录可写修复（不删已有 HALT）、网络探测、verify-roles、按手册执行的回滚，以及 `master-bootstrap.sh --check` / `--run --confirm-network-fetch`，同样由编排者在收口时下令 `--apply`。解除停机标志或恢复出口不在此列：必须由用户本人确认（与 `ingest-halt.md`、`receipts.md`、契约 1406/1411 一致），编排者不能代为确认。

下列情况**仍然必须停下来问编排者**后再继续：

- 0029 分叉（库已在 0029 且 ingest_private / 触发器 / 函数与入链文件不一致，T-A70）
- 任何删除数据或卷的操作（包括把回滚产生的新库/新卷切成现网之前若涉及删除现网数据或卷；删除旧 `<前缀>_aia_run` 卷）
- 回滚失败
- `engine_policy_version_hash_conflict`（立即停止，不删旧行）或 seed / 只读核验未看到最新 `version_no=3` / 缺少已批准且指向 H-01 v3 的 `strategy_promotion_reviews` 行

## 本机自检

```bash
deploy/scripts/wrapup/selftest-local.sh           # bash -n、shellcheck、各脚本 dry-run
deploy/scripts/wrapup/selftest-local.sh --apply   # 只在共享运维电脑上跑；不要在用户 Windows 上执行
```

`selftest-local.sh --apply` **只应在共享运维电脑上跑**，不要在用户 Windows 上执行。它只用 `o69_` 前缀的卷和库，以及已有的 `o61-pg`（`127.0.0.1:55461`）建临时库；不停止受保护容器，不 drop `o61_tmp_0030` / `tt51_tpl` 等，不删匿名卷。自检目录用独立 `mktemp`，trap 只删该目录。
