# 复审 25cf460：迁移 0017 升级前违规行预检查（运维）

架构师，2026-11-01（America/Denver）。范围：deploy/scripts/db-precheck-0017.sh、deploy/scripts/up.sh、
deploy/runbooks/database.md §7、scripts/ci/tests/test_db_precheck_0017.py。

## 结论

**可以推送。无 B、无 M。**

## 核对项

| 要求 | 结果 |
|---|---|
| 只读 | 通过。三次查询都包在 `BEGIN READ ONLY; … ROLLBACK;` 里（:33、:40、:43）；test_all_queries_read_only 守着。 |
| SQL 与迁移一致 | 通过。与 0017 的 PRECHECK_SQL 完全相同（test_sql_matches_migration 守着；工作区里 0017 有未提交改动，PRECHECK_SQL 没变）。 |
| 有违规行就停 | 通过。退出 1；up.sh:45 失败即 `exit 1`，在 `compose.sh up` 之前（test_up_runs_precheck_before_compose_up）。 |
| 连不上库 / 查询失败 | 通过（fail-closed）。q() 失败退出 2，up.sh 同样停止。 |
| postgres 未运行 | 不预检，由 0017 迁移自身的预检查兜底（同一条 SQL，raise，不改数据）。可接受，runbook 已写。 |
| 不泄露 | 通过。只输出 purpose 和行数；不打印连接串、口令；在 postgres 容器内用属主经 socket 连接（只读事务）。 |
| 版本判断 | `alembic_version` 是 "0016" 这类纯数字，≥17 跳过；非数字时照样做检查（偏安全）。 |
| 测试 | 全量 scripts/ci/tests：593 passed，5 failed 均为 test_secret_scan 已知环境问题。 |
| shellcheck | 只有 info（SC1091 未跟随 lib/common.sh、SC2016 有意单引号）。 |

## 问题

- m1 预检查和 migrate 之间有时间窗：旧版 api 在这段时间仍可能写入违规行。0017 迁移自身的预检查会挡住（报错、不改数据），
  但 up 会以 migrate 失败结束。runbook §7 加一句：“迁移因预检查失败时，按 §7 处理后重跑 up”。
- n1 `max(version_num)` 假设单一 head、版本号补零到 4 位；以后出现分支 head 时这里要改。
