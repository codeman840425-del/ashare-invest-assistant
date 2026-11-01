#!/usr/bin/env bash
# 一键启动：deploy/scripts/up.sh
# - 没有 deploy/env/.env 时自动从 .env.example 生成
# - 非 systemd 主机上 Docker daemon 未运行时，自动调用 start-dockerd.sh
# - 默认叠加 docker-compose.dev.yml（麦蕊回放模式），等待全部服务 healthy 后返回
# - 默认带 --build：后端镜像（deploy/docker/backend.Dockerfile）有缓存时只需数秒，避免 live 模式跑旧镜像；
#   AIA_UP_BUILD=0 可跳过构建
# - 启动顺序：postgres/redis → migrate（alembic upgrade head）→ timescale-apply（策略）→ 应用服务 → nginx；
#   一次性服务失败时 --wait 返回非 0，用 `compose.sh logs migrate timescale-apply` 看原因
# - 项目名/卷名优先级见 compose.sh 头部注释：只认 deploy/env/.env（缺省按工作树目录名派生），
#   shell 里导出的 COMPOSE_PROJECT_NAME 不生效（T-O03）；启动前先打印解析结果
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! docker info >/dev/null 2>&1 && ! sudo -n docker info >/dev/null 2>&1; then
  if command -v dockerd >/dev/null 2>&1 && [ "$(cat /proc/1/comm 2>/dev/null)" != "systemd" ]; then
    "$HERE/start-dockerd.sh"
  fi
fi

"$HERE/compose.sh" --resolve

build_flag=()
[ "${AIA_UP_BUILD:-1}" = "1" ] && build_flag=(--build)

"$HERE/compose.sh" up -d "${build_flag[@]}" --wait --wait-timeout "${UP_WAIT_TIMEOUT:-300}" "$@"
"$HERE/compose.sh" ps -a
