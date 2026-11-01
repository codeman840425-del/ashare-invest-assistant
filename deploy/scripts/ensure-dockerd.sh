#!/usr/bin/env bash
# 轻量、静默、幂等的 dockerd 自启入口（T-O08）。供登录钩子 /etc/profile.d/zz-aia-dockerd.sh 调用，
# 也可手动运行。dockerd 已就绪且 docker.sock ACL 已在 → 立即退出（<50ms）；否则后台调用
# start-dockerd.sh（启动 dockerd + 补 ACL），日志写 /tmp/aia-ensure-dockerd.log，不阻塞登录。
#   deploy/scripts/ensure-dockerd.sh            # 后台
#   deploy/scripts/ensure-dockerd.sh --wait     # 前台等待完成（排查用）
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="${AIA_ENSURE_DOCKERD_LOG:-/tmp/aia-ensure-dockerd.log}"
LOCK="${AIA_ENSURE_DOCKERD_LOCK:-/tmp/aia-ensure-dockerd.lock}"

[ "$(cat /proc/1/comm 2>/dev/null)" != "systemd" ] || exit 0   # systemd 主机交给 docker.service
command -v dockerd >/dev/null 2>&1 || exit 0

if pgrep -x dockerd >/dev/null 2>&1 && [ -S /var/run/docker.sock ]; then
  # 已运行：只检查当前用户能否直接访问（ACL 或 docker 组）；能访问就什么都不做。
  [ -r /var/run/docker.sock ] && [ -w /var/run/docker.sock ] && exit 0
fi
sudo -n true 2>/dev/null || exit 0   # 没有免密 sudo 时不打扰登录

run() {
  {
    flock -n 9 || exit 0
    echo "=== $(date -u +%FT%TZ) ensure-dockerd (uid $(id -u))"
    "$HERE/start-dockerd.sh"
  } 9>"$LOCK" >>"$LOG" 2>&1
}
if [ "${1:-}" = "--wait" ]; then run; else (run &) >/dev/null 2>&1; fi
exit 0
