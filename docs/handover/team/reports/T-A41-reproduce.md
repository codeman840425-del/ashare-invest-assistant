# T-A41 后端隔离复验与环境说明

时间：2026-11-08，北京时间（Asia/Shanghai）；仅虚构用户、四标的合成持仓/报价与卡。
前轮T-B91在38fc560交付后按要求删除tb91-close-pg/redis及匿名卷，T-B91.md第16行已有记录；复审引用旧socket出现Connection refused属于环境失败，不算通过。
本轮新建ta41-owned-pg/redis，独立socket，不接旧库/共享库，不读取真实凭据。专用Postgres不监听TCP，容器network=none；实际业务连接为aia_api，迁移建库与原样grants仅由测试setup在这个隔离集群执行。

## 可复现启动、迁移、测试、清理
以下只在本机、名称/目录未被他人占用时执行；若同名容器或socket已被使用则停止，不能删他人的资源。镜像必须已在本机，禁止为此联网。
```bash
set -euo pipefail
cd /workspace/ashare-invest-assistant/src/backend
PGDIR=/tmp/tb70-ta41-owned-socket
RDIR=/tmp/ta41-owned-redis
# 仅允许空/自己已清理目录；存在socket或同名容器时先停下核验。
test ! -S "$PGDIR/.s.PGSQL.5432"
test ! -S "$RDIR/redis.sock"
mkdir -p "$PGDIR" "$RDIR"
chmod 777 "$PGDIR" "$RDIR"
PG_ID= R_ID=
cleanup() {
  for id in "$PG_ID" "$R_ID"; do
    if test -n "$id"; then
      docker stop --time 10 "$id"
      docker rm -v "$id"
    fi
  done
}
trap cleanup EXIT
PG_ID=$(docker run --pull=never -d --name ta41-owned-pg --network none \
  -e POSTGRES_HOST_AUTH_METHOD=trust -v "$PGDIR":/var/run/postgresql \
  timescale/timescaledb:2.31.0-pg16 -c listen_addresses='')
R_ID=$(docker run --pull=never -d --name ta41-owned-redis --network none \
  -v "$RDIR":/sock redis:7.4.12-alpine \
  redis-server --port 0 --unixsocket /sock/redis.sock --unixsocketperm 777)
# 有界等初始化完成，避免把临时初始化server误认为最终服务；仅新合成容器。
PG_ID="$PG_ID" R_ID="$R_ID" /tmp/rv7-backend-venv/bin/python - <<'READY'
import os, subprocess, threading, time
pg, rd = os.environ['PG_ID'], os.environ['R_ID']
deadline = time.monotonic() + 60
while time.monotonic() < deadline:
    logs = subprocess.run(['docker', 'logs', pg], capture_output=True, text=True)
    initialized = 'PostgreSQL init process complete; ready for start up.' in logs.stdout + logs.stderr
    p = subprocess.run(['docker', 'exec', pg, 'pg_isready', '-h', '/var/run/postgresql', '-U', 'postgres'], capture_output=True)
    r = subprocess.run(['docker', 'exec', rd, 'redis-cli', '-s', '/sock/redis.sock', 'ping'], capture_output=True)
    if initialized and p.returncode == 0 and r.returncode == 0 and r.stdout.strip() == b'PONG':
        break
    threading.Event().wait(0.25)
else:
    raise SystemExit('isolated startup not ready within 60s; no tests passed')
READY
PYTHONPATH=. /tmp/rv7-backend-venv/bin/python - <<'PYTEST'
import pytest
from selfchecks import test_tb91_fixes as fixtures
fixtures.SOCKET='/tmp/tb70-ta41-owned-socket'
fixtures.REDIS='uni<path>'
raise SystemExit(pytest.main(['-q',
 'selfchecks/test_tb91_closing.py::test_actual_buy_add_null_budget_to_confirmation_and_number',
 'selfchecks/test_tb91_closing.py::test_budget_exhausted_reason_commit_and_recheck',
 'selfchecks/test_tb91_closing.py::test_budget_multi_full_allocation_latest_unknown_and_stale',
 'selfchecks/test_tb91_closing.py::test_rc1_disabled_null_loss_and_positive_below_lot_budget',
 'selfchecks/test_tb91_closing.py::test_rc1_disabled_with_stop_keeps_loss_and_valid_warning',
 'selfchecks/test_tb91_fixes.py::test_reviewed_synthetic_operands_only']))
PYTEST
```
迁移不是省略：上述database fixture复用`test_p2n02_risk_controls.database`，先检查`SHOW listen_addresses=''`，创建`tb70_p2n02_<随机UUID>`库；以Config.script_location指向本机src/backend/migrations，`cfg.cmd_opts=Namespace(x=['url='+专用Unix URL])`，实际执行`alembic.command.upgrade(cfg,'head')`（本批活动head0026），原样部署grants并种4个合成标的，业务URL切换为aia_api。结束finally删除仅该临时库。该过程每个涉及database的模块自有一次，不借用现有库或mock迁移。
首次PG初始化的pg_isready可能短暂返回非0；等Docker日志明确初始化完成，再运行ready/测试步骤。没有改其他服务/生产权限。

## 本轮证据与准确计数
- `/tmp/ta41-targeted.log`：首轮5 passed/3 failed。两个新增退出夹具触发既有反向计划拦截；另一个新断言错误假定金额仅两位。均是本轮新测试夹具/断言问题，未改业务门禁或金额精度以迁就测试。
- `/tmp/ta41-repaired-3.log`：一次导入收集错误，不能算通过。
- `/tmp/ta41-repaired-final.log`：修正为追加688073合成持仓/可信报价、account范围且沿原金额精度后，3 passed；buy/add分别验证unknown实际POST503+budget_plan_amount且8类事实完全不变，sell/reduce同样未知预算实际POST201（另一标的规避无关反向计划冲突，未删/放行任何门禁）。
- 合计8个唯一节点分组最终通过：原4个PG失败参数节点均已进入真实API/DB断言并通过；另加multi/add、RC1有止损、无止损、机械操作数核验。不把重复运行计作新节点；无全量/coverage。
- N-I1共享RiskFlag完整验证覆盖实际POST响应；N-S2有止损仍保留数值、不再提示无法计算或挂假max_loss gap；无止损保留null+gap/警示。
- ruff两个改动文件通过；mypy两个改动文件通过（明确fixture导入、inspect.unwrap，不靠忽略类型错误）。
- DeepSeek复用已核验24条纯合成操作数，首条用于已有止损夹具；本轮无外部调用、未发送源码/秘密/真实行情，元数据reports/deepseek/T-A41/metadata.json。
- B2生产采集完成→owned_quote调用仍是T-A41已列原阻断，本批未扩做；0真实采集/正式G7/真实提醒。
- B92自身8文件WIP完整留在`/workspace/tb92-wip-preserved-20261108/`，manifest记录基线与每文件SHA256；恢复前须核对相应基线文件未被别人改，不能覆盖他人新变更。

本轮完成后核验临时测试库数0，按完整ID优雅停止并删除T-A41两容器及匿名卷；B92原暂停资源、tb58/tb61服务未动。暂存两文件秘密扫描阻断0/警告0，本地0289388d811db051931fa0db08cdb516d1204cb0。
