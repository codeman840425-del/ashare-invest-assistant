#!/usr/bin/env bash
# 在非 systemd 主机上启动 dockerd（幂等：已在运行则直接退出）。
# 用法：deploy/scripts/start-dockerd.sh
# 环境变量：DOCKERD_LOG（默认 /var/log/dockerd.log）、DOCKERD_WAIT（等待秒数，默认 60）
set -euo pipefail

LOG="${DOCKERD_LOG:-/var/log/dockerd.log}"
WAIT="${DOCKERD_WAIT:-60}"
SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"

daemon_ok() { $SUDO docker info >/dev/null 2>&1; }

if daemon_ok; then
  echo "dockerd 已在运行，跳过启动。"
  exit 0
fi

if pgrep -x dockerd >/dev/null 2>&1; then
  echo "dockerd 进程存在但尚未就绪，等待……"
else
  # containerd 由 dockerd 自动拉起（未单独运行时 dockerd 会启动托管的 containerd）。
  echo "启动 dockerd，日志：$LOG"
  $SUDO sh -c "nohup dockerd > '$LOG' 2>&1 &"
fi

for _ in $(seq 1 "$WAIT"); do
  if daemon_ok; then
    echo "dockerd 就绪：$($SUDO docker version --format '{{.Server.Version}}')"
    # 让 docker 组成员无需 sudo 即可访问（dockerd 默认 -G docker）。
    exit 0
  fi
  sleep 1
done

echo "dockerd 在 ${WAIT}s 内未就绪，最近日志：" >&2
$SUDO tail -n 30 "$LOG" >&2 || true
exit 1
