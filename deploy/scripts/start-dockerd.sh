#!/usr/bin/env bash
# 在非 systemd 主机上启动 dockerd（幂等：已在运行则只补 socket ACL 后退出）。
# 用法：deploy/scripts/start-dockerd.sh
# 环境变量：DOCKERD_LOG（默认 /var/log/dockerd.log）、DOCKERD_WAIT（等待秒数，默认 60）、
#           AIA_DOCKER_ACL_USERS（空格分隔，默认 box；设为 "-" 关闭 ACL）
#
# docker.sock ACL（T-O08）：box 虽在 docker 组，但组成员关系只对"加入之后新登录"的会话生效，
# 各角色已开着的 shell 仍拿不到 docker 组。dockerd 每次启动都会重建 /var/run/docker.sock，
# 所以这里在每次启动（以及发现已在运行）后给指定用户补一条 ACL：setfacl -m u:box:rw。
# 不用 chmod 666。回滚：sudo setfacl -x u:box /var/run/docker.sock（或重启 dockerd 后不再调用本脚本）。
set -euo pipefail

LOG="${DOCKERD_LOG:-/var/log/dockerd.log}"
WAIT="${DOCKERD_WAIT:-60}"
SOCK="${DOCKER_SOCK:-/var/run/docker.sock}"
ACL_USERS="${AIA_DOCKER_ACL_USERS:-box}"
SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo -n"

daemon_ok() { $SUDO docker info >/dev/null 2>&1; }

ensure_sock_acl() {
  [ "$ACL_USERS" != "-" ] || return 0
  command -v setfacl >/dev/null 2>&1 || { echo "未安装 setfacl（apt-get install acl），跳过 docker.sock ACL" >&2; return 0; }
  [ -S "$SOCK" ] || return 0
  local u
  for u in $ACL_USERS; do
    id "$u" >/dev/null 2>&1 || continue
    if ! $SUDO getfacl -cp "$SOCK" 2>/dev/null | grep -qx "user:$u:rw-"; then
      $SUDO setfacl -m "u:$u:rw" "$SOCK" && echo "已为用户 $u 设置 $SOCK ACL（rw）"
    fi
  done
}

if daemon_ok; then
  ensure_sock_acl
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
    ensure_sock_acl
    echo "dockerd 就绪：$($SUDO docker version --format '{{.Server.Version}}')"
    exit 0
  fi
  sleep 1
done

echo "dockerd 在 ${WAIT}s 内未就绪，最近日志：" >&2
$SUDO tail -n 30 "$LOG" >&2 || true
exit 1
