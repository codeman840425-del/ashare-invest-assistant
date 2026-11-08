# T-B92 本机隔离复现入口
仅用于虚构数据；已存在同名容器/占用socket/非空目录时必须停下，不能清理他人的资源。使用已有本机镜像，不联网、不读密码或任何麦蕊环境变量。trust仅限network none与专用Unix socket的临时虚构数据库。启动模式复用已验证的T-A41默认socket挂载，避免PG初始化入口默认socket与自定义目录不一致。
```bash
set -euo pipefail
cd /workspace/ashare-invest-assistant/src/backend
PGDIR=/tmp/tb70-tb92-owned-pg
RDIR=/tmp/tb92-owned-redis
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
PG_ID=$(docker run --pull=never -d --name tb92-owned-pg --network none \
  -e POSTGRES_HOST_AUTH_METHOD=trust -v "$PGDIR":/var/run/postgresql \
  timescale/timescaledb:2.31.0-pg16 -c listen_addresses='')
R_ID=$(docker run --pull=never -d --name tb92-owned-redis --network none \
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
PYTHONPATH=. /tmp/rv7-backend-venv/bin/pytest -q selfchecks/test_tb92_repairs.py
```
模块仅10个唯一直接节点。fixture创建随机tb70_tb92_<UUID>库，实际Alembic Config/env：0023带旧事件通知→0024→0027；0027新事实→0024保留表→0027完整恢复；及原版0026增补路径。没有裸Operations.context、没有mock最终产物。旧键冲突必须回滚保留0027；不证明未知归属时拒迁保留0024与旧行。
测试读取现有deploy grants脚本但不修改，隔离追加grants()清单见T-B92-evidence.md；实际业务/维护连接分别为aia_api/aia_maint。每个测试库finally禁止新连接并精准清理该随机库；trap只停/删本次捕获ID及匿名卷，不接触其他容器。若失败须保留失败状态，不把环境错误当通过。
