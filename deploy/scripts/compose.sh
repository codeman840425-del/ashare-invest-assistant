#!/usr/bin/env bash
# docker compose 包装：固定项目名、env 文件与叠加层。其余参数原样传给 docker compose。
#   deploy/scripts/compose.sh ps
#   deploy/scripts/compose.sh logs -f ingest
#   deploy/scripts/compose.sh down -v
# AIA_PROFILE=dev（默认，叠加 docker-compose.dev.yml = 麦蕊回放模式）| live（只用基础文件）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$ROOT/deploy/env/.env"
ENV_EXAMPLE="$ROOT/deploy/env/.env.example"
PROFILE="${AIA_PROFILE:-dev}"

if [ ! -f "$ENV_FILE" ]; then
  echo "未找到 deploy/env/.env，从 .env.example 生成（仅占位值，请按需修改）。" >&2
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

# daemon 没起来（机器重启后）或 docker.sock ACL 丢失（dockerd 被别处重启）时，自动修复一次（T-O08）。
if ! docker info >/dev/null 2>&1 && [ "$(cat /proc/1/comm 2>/dev/null)" != "systemd" ] \
   && command -v dockerd >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
  "$ROOT/deploy/scripts/start-dockerd.sh" >&2 || true
fi

if docker info >/dev/null 2>&1; then
  DOCKER=(docker)
elif sudo -n docker info >/dev/null 2>&1; then
  DOCKER=(sudo -n docker)
else
  echo "无法访问 Docker daemon：请先运行 deploy/scripts/start-dockerd.sh，或把当前用户加入 docker 组。" >&2
  exit 1
fi

FILES=(-f "$ROOT/deploy/compose/docker-compose.yml")
case "$PROFILE" in
  dev)  FILES+=(-f "$ROOT/deploy/compose/docker-compose.dev.yml") ;;
  live) ;;
  *) echo "未知 AIA_PROFILE=$PROFILE（可选 dev|live）" >&2; exit 2 ;;
esac

exec "${DOCKER[@]}" compose --project-directory "$ROOT/deploy/compose" --env-file "$ENV_FILE" "${FILES[@]}" "$@"
