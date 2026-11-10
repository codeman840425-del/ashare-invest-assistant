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

顺序（与 `up.sh` / compose `depends_on` 一致）：

1. postgres、redis（等到 healthy）
2. **migrate**（`alembic upgrade head`）
3. timescale-apply
4. **db-roles**（`apply-roles.sh`）
5. api / worker / beat / ingest / signal-rt / nginx

不要加 `--profile master-bootstrap`。默认 dev/live 不会启动该服务。

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

- **rc=0**（已有成功导入，从 `f82a83b` 升级时常见）。此时再跑 `--run --rebuild-search-terms` 会因脚本幂等在检查阶段跳过，到不了重建。改为在**不出网的 worker**（只挂 `aia_internal`，无 egress）上跑离线 CLI。模块是 `python -m app.cli.security_search_terms`（它不在 `python -m app.cli` 的子命令表里）。默认即 dry-run：校验配置后退出，不访问数据库、不写库；写入须加 `--apply`（依赖容器内已有 `DATABASE_URL`，worker 的 compose 环境已提供）。**不要用 maint-cli。** 先 dry-run，确认输出含 `dry-run` 且退出码 0，再 `--apply`：

  ```bash
  deploy/scripts/compose.sh run --rm --no-deps -T --entrypoint python worker -m app.cli.security_search_terms
  deploy/scripts/compose.sh run --rm --no-deps -T --entrypoint python worker -m app.cli.security_search_terms --apply
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

## 授权口径与必须停下来问编排者的情况

依据 `standing-auth-2026-11-08.md`：用户已长期授权收口时部署到其电脑（先备份，失败回滚，绝不 `down -v`），主数据首次导入（三所官网公开 HTTPS）也在 11-08 授权过。因此备份、迁 0029、更新代码、启停服务、halt 目录可写修复（不删已有 HALT）、网络探测、verify-roles、按手册执行的回滚，以及 `master-bootstrap.sh --check` / `--run --confirm-network-fetch`，都由编排者在收口时下令 `--apply`，不必逐步再问用户。解除停机标志或恢复出口不在此列：必须由用户本人确认（与 `ingest-halt.md`、`receipts.md`、契约 1406/1411 一致），编排者不能代为确认。

下列情况**仍然必须停下来问编排者**后再继续：

- 0029 分叉（库已在 0029 且 ingest_private / 触发器 / 函数与入链文件不一致，T-A70）
- 任何删除数据或卷的操作（包括把回滚产生的新库/新卷切成现网之前若涉及删除现网数据或卷；删除旧 `<前缀>_aia_run` 卷）
- 回滚失败

## 本机自检

```bash
deploy/scripts/wrapup/selftest-local.sh           # bash -n、shellcheck、各脚本 dry-run
deploy/scripts/wrapup/selftest-local.sh --apply   # 只在共享运维电脑上跑；不要在用户 Windows 上执行
```

`selftest-local.sh --apply` **只应在共享运维电脑上跑**，不要在用户 Windows 上执行。它只用 `o69_` 前缀的卷和库，以及已有的 `o61-pg`（`127.0.0.1:55461`）建临时库；不停止受保护容器，不 drop `o61_tmp_0030` / `tt51_tpl` 等，不删匿名卷。自检目录用独立 `mktemp`，trap 只删该目录。
