# 证券主数据：首次导入（master_bootstrap）

依据 plan §4.6.6、reports/T-A04.md §6。CLI `python -m app.cli.master_bootstrap` 由后端 T-B52 交付；
本 runbook 只管“部署时什么时候、怎样跑它”。

## 1. 原则

- **手动、显式**：首次导入要联网拉上交所、深交所、北交所的公开名单（含深交所改名表、北交所代码对照）。
  `up.sh`、默认 compose 栈、CI 都**不会**触发它。不要 `compose.sh --profile master-bootstrap run …`（会绕过 `--check`、flock、`--confirm-network-fetch` 和 CI 拒绝，T-A98 B2）；只走下面的
  `master-bootstrap.sh`。rc=0 时的离线词表只用第 2 节给出的 worker 命令，**不要用 maint-cli**（与 `wrapup-deploy.md`「主数据首次导入与词表」相同，不得分歧）。
- **不调用麦蕊**：首次导入只用交易所公开列表；麦蕊对账由 beat 日常任务经 `ingest` 做，不属于本步骤。
- **幂等**：库里已有 `status='ok'` 的 `market.master_runs` 记录就跳过；脚本用 flock 防同一项目并发。此时若要补写词表，须走第 2 节 rc=0 的离线 CLI，不要再 `--run`。
- **完成前不开放服务**（plan §4.6.6）：网关对外开放前必须看到“完成”。

## 2. 步骤与两种走法

收口部署时的顺序见 `wrapup-deploy.md`（先备份、再启栈，再 `--check`）。日常按本手册则先把栈拉起来：

```bash
deploy/scripts/up.sh                                           # 正常部署（迁移到 T-B52 的版本）
deploy/scripts/master-bootstrap.sh --check; echo "rc=$?"
```

`--check` 不联网、不改库：查 `market.master_runs` 是否存在、是否已有成功记录，以及镜像里有没有 CLI 模块。按退出码分支（**其它 rc 一律停止**，不要改库、不要出网；与 `wrapup-deploy.md` 相同）：

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

`--run` 不带 `--confirm-network-fetch` 一律拒绝；`CI` / `GITHUB_ACTIONS` 非空时拒绝。`--run` 用 opt-in profile 跑 compose 服务 `master-bootstrap`（由脚本执行 `compose.sh --profile master-bootstrap run --rm --no-deps -T`，需要时在服务名后附加 `--rebuild-search-terms`；不走 worker、不启动 ingest），结束后再查一次：必须出现 `status='ok'` 的记录才算成功；失败可直接重跑。不要绕过本脚本直接对该 profile `compose run`。

## 3. 退出码与处理

| rc | 含义 | 处理 |
|---|---|---|
| 0 | 已有成功导入（仅 `--check`） | 按第 2 节在不出网 worker 上跑离线 CLI（先 dry-run 再 `--apply`）；不要再 `--run` |
| 10 | 需要首次导入（仅 `--check`） | 按第 2 节执行 `--run --confirm-network-fetch --rebuild-search-terms` |
| 2 | 用法错 | **停止**，更正参数后再从 `--check` 开始。`master-bootstrap.sh` 的 `die` 默认退出 2：未给 `--check`/`--run`（且不是单独的 `--rebuild-search-terms` dry-run）、同时给 `--check` 与 `--run`、或未知参数（见 `test_master_bootstrap.py::test_usage_errors`） |
| 3 | 未就绪：表不存在（迁移没到 T-B52）或镜像里没有 CLI | **停止**，等 T-B52 交付并重建镜像 |
| 4 | 缺 `--confirm-network-fetch`，或在 CI 中 | **停止**；手动在部署主机上带确认执行，不要在 CI 里跑 |
| 5 | 另一个实例在运行 | **停止**，等它结束 |
| 1 | 查询或 CLI 失败 | **停止**；看输出，修正后再从 `--check` 开始（幂等） |

## 4. 只读验证词表

在已启动的 postgres 上跑（只读事务）。词表行数通常大于证券行数（一只证券多条 term）；对齐看去重 `code`：`terms_distinct_codes` 应等于 `securities_distinct_codes`，缺词查询应为空。抽查 `term_kind` 须属于 `name` / `name_initials` / `former_name` / `former_initials` / `former_code`（不是每种都必然出现）。`generator_version` 必须全部为 1。命令与 SQL 与 `wrapup-deploy.md` 相同：

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

## 5. 数据与合规提示

- 原始名单文件落在 `data/master/`，保留 90 天；是否备份见 reports/T-A04-ops.md（建议不进异地备份）。
- 主数据能否展示、再分发（plan 问题 52）由用户确认许可条款；确认前只展示问题 51 字段并带 `attribution`。
