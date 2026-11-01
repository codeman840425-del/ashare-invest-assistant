#!/usr/bin/env bash
# 卸载 dockerd 登录自启钩子（删除 /etc/profile.d/zz-aia-dockerd.sh）。可选 --remove-acl 同时去掉 docker.sock 上的 box ACL。
set -euo pipefail
DEST="${AIA_PROFILE_HOOK:-/etc/profile.d/zz-aia-dockerd.sh}"
SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo -n"
if [ -f "$DEST" ]; then
  grep -q 'ashare-invest-assistant' "$DEST" || { echo "$DEST 不是本项目安装的文件，拒绝删除" >&2; exit 1; }
  $SUDO rm -f "$DEST"; echo "已删除 $DEST"
else
  echo "未安装：$DEST"
fi
if [ "${1:-}" = "--remove-acl" ] && [ -S /var/run/docker.sock ]; then
  for u in ${AIA_DOCKER_ACL_USERS:-box}; do $SUDO setfacl -x "u:$u" /var/run/docker.sock 2>/dev/null || true; done
  echo "已移除 docker.sock 上的用户 ACL（${AIA_DOCKER_ACL_USERS:-box}）"
fi
