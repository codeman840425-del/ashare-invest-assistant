# T-O49 0029 解除演练预案（待「合并就绪」通知执行）

时序：T-B102f+RV-15f 合回 team-b 后执行，须在 11-10 16:00 T-B103 切锁前完成。用户定调：先备份、失败回滚、绝不 down -v。
背景：库=0029（T-O45 已升），team-b 代码 head=0028 → require_database_mainline 拒绝启动，api/worker 重启禁令自 T-O45 起生效。演练=验证代码对齐后禁令可解除。

## 前置确认（步骤 0，全满足才动手）
- [ ] 编排者「合并就绪」通知到手；team-b 最新含 0029 迁移文件（`src/backend/migrations/versions/0029_*.py`），工作树干净、与 origin 记录一致。
- [ ] 依赖核对：合并区间 pyproject/uv.lock/前端锁文件是否有变动——有则对应镜像须先重建（bind 只覆盖代码，不覆盖 venv/dist）；无则零重建。
- [ ] 8 容器当前状态记录（作回滚对照）。

## 演练步骤与检查点
| 步 | 动作 | 检查点（不过即停） |
|---|---|---|
| 1 | `db-backup.sh --container aia-local-postgres-1` | dump+meta 生成、sha256 记录、文件非空 |
| 2 | 代码对齐：team-b 含 0029；`compose.sh run --no-deps migrate alembic current` 先只读 | current=0029，mainline 校验无 MULTIHEAD/NOT_MAINLINE |
| 3 | `compose.sh restart api`（仅 api） | api healthy；`/api/v1/health/live`、`/health/ready` 200；日志无 DATABASE_REVISION 错误 |
| 4 | `compose.sh restart worker`（仅 worker） | worker healthy（健康文件 45s 内更新） |
| 5 | `compose.sh run --no-deps migrate alembic upgrade head` | 输出「0029→0029 无迁移动作」级日志、RC=0（幂等校验） |
| 6 | 8 服务全绿 + 冒烟 | `compose ps` 全 healthy；`/`、`/login`、`/healthz`、`/api/v1/health/live`、`/terminal`、`/today`、`/market/overview` 均 200 |

范围边界：本单仅 api/worker 重启；ingest/beat/signal-rt 的重启与 T-B99e 功能启用归 T-B103 切锁派单，本演练不动。MAIRUI_MODE=replay 不变，全程零外呼。

## 回滚点
- R1（步 1 备份失败）：停止，不动任何容器，报编排者。
- R2（步 2 mainline 仍拒绝）：停止=代码未对齐，不重启，报编排者（T-B102 合并内容核查）。
- R3（步 3/4 重启 unhealthy）：停止后续步；最小诊断（logs --tail 50，不打印密钥）；恢复目标容器运行（同镜像 start）；报编排者裁定：继续修复 or 库侧按备份 db-restore.sh 到新校验库核对版本/用户数/表数后切换 + team-b 回退合并前基线。任何库回滚动作须编排者明确放行。
- R4（步 5/6 校验失败）：服务已在跑但校验未过，报编排者，不擅自扩大重启面。

## 耗时与结果记录（执行时填）
| 步 | 结果 | 耗时 | 备注 |
|---|---|---|---|
| 备份 | | | |
| 只读校验 | | | |
| api 重启 | | | |
| worker 重启 | | | |
| migrate 幂等 | | | |
| 全绿+冒烟 | | | |
