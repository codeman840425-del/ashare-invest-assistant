#!/usr/bin/env bash
# 一键启动：deploy/scripts/up.sh
# - 没有 deploy/env/.env 时自动从 .env.example 生成
# - 非 systemd 主机上 Docker daemon 未运行时，自动调用 start-dockerd.sh
# - 默认叠加 docker-compose.dev.yml（麦蕊回放模式），等待全部服务 healthy 后返回
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! docker info >/dev/null 2>&1 && ! sudo -n docker info >/dev/null 2>&1; then
  if command -v dockerd >/dev/null 2>&1 && [ "$(cat /proc/1/comm 2>/dev/null)" != "systemd" ]; then
    "$HERE/start-dockerd.sh"
  fi
fi

"$HERE/compose.sh" up -d --wait --wait-timeout "${UP_WAIT_TIMEOUT:-300}" "$@"
"$HERE/compose.sh" ps
