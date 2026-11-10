# 证券主数据：首次导入（master_bootstrap）

依据 plan §4.6.6、reports/T-A04.md §6。CLI `python -m app.cli.master_bootstrap` 由后端 T-B52 交付；
本 runbook 只管“部署时什么时候、怎样跑它”。

## 1. 原则

- **手动、显式**：首次导入要联网拉上交所、深交所、北交所的公开名单（含深交所改名表、北交所代码对照）。
  `up.sh`、默认 compose 栈、CI 都**不会**触发它。不要直接 `compose.sh run`；只走下面的
  `master-bootstrap.sh`，以保留 `--check`、flock、`--confirm-network-fetch` 和 CI 拒绝（`scripts/ci/tests/test_master_bootstrap.py` 守着）。
- **不调用麦蕊**：首次导入只用交易所公开列表；麦蕊对账由 beat 日常任务经 `ingest` 做，不属于本步骤。
- **幂等**：库里已有 `status='ok'` 的 `market.master_runs` 记录就跳过；脚本用 flock 防同一项目并发。
- **完成前不开放服务**（plan §4.6.6）：网关对外开放前必须看到“完成”。

## 2. 步骤

```bash
deploy/scripts/up.sh                                           # 正常部署（迁移到 T-B52 的版本）
deploy/scripts/master-bootstrap.sh --check; echo "rc=$?"       # 只读：0 不需要 / 10 需要 / 3 未就绪
# rc=10 时，确认这台主机可以访问交易所网站后：
deploy/scripts/master-bootstrap.sh --run --confirm-network-fetch
```

- `--check` 不联网、不改库：查 `market.master_runs` 是否存在、是否已有成功记录，以及镜像里有没有 CLI 模块。
- `--run` 不带 `--confirm-network-fetch` 一律拒绝；`CI` / `GITHUB_ACTIONS` 非空时拒绝。
- `--run` 用 opt-in profile 跑 compose 服务 `master-bootstrap`（`compose.sh --profile master-bootstrap run --rm --no-deps -T`，不走 worker、不启动 ingest），
  结束后再查一次：必须出现 `status='ok'` 的记录才算成功；失败可直接重跑。不要绕过本脚本直接 `compose run`。

## 3. 退出码与处理

| rc | 含义 | 处理 |
|---|---|---|
| 0 | 不需要 / 已完成 | 无 |
| 10 | 需要（仅 `--check`） | 按第 2 节执行 `--run` |
| 3 | 未就绪：表不存在（迁移没到 T-B52）或镜像里没有 CLI | 等 T-B52 交付并重建镜像 |
| 4 | 缺 `--confirm-network-fetch`，或在 CI 中 | 手动在部署主机上执行 |
| 5 | 另一个实例在运行 | 等它结束 |
| 1 | 查询或 CLI 失败 | 看输出；修正后重跑（幂等） |

## 4. 数据与合规提示

- 原始名单文件落在 `data/master/`，保留 90 天；是否备份见 reports/T-A04-ops.md（建议不进异地备份）。
- 主数据能否展示、再分发（plan 问题 52）由用户确认许可条款；确认前只展示问题 51 字段并带 `attribution`。
