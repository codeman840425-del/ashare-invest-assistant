#!/usr/bin/env bash
# deploy/scripts 共用函数（被 source，不单独执行）。
# 提供：AIA_ROOT、aia_docker（docker / sudo -n docker）、aia_pg_container、aia_psql、aia_log/aia_die、aia_compose_image。

AIA_ROOT="${AIA_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"

aia_log() { printf '[%s] %s\n' "$(date -u +%H:%M:%SZ)" "$*" >&2; }
aia_die() { aia_log "ERROR: $*"; exit 1; }

# 选择 docker 调用方式；daemon 不可用时给出提示并失败。
aia_docker_init() {
  if [ -n "${AIA_DOCKER_CMD_SET:-}" ]; then return 0; fi
  if docker info >/dev/null 2>&1; then
    AIA_DOCKER=(docker)
  elif sudo -n docker info >/dev/null 2>&1; then
    AIA_DOCKER=(sudo -n docker)
  else
    aia_die "无法访问 Docker daemon：先运行 deploy/scripts/start-dockerd.sh（或 ensure-dockerd.sh），或把当前用户加入 docker 组。"
  fi
  AIA_DOCKER_CMD_SET=1
}
aia_docker() { aia_docker_init; "${AIA_DOCKER[@]}" "$@"; }

# 直连模式（T-O01b）：AIA_PSQL_MODE=direct 时不用 docker exec，直接用本进程的 psql 经网络连接，
# 连接参数取标准 libpq 环境变量（PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE）。
# 供 compose 一次性服务 timescale-apply 在 postgres 镜像内运行 db-apply-timescale.sh。
aia_psql_direct() { [ "${AIA_PSQL_MODE:-exec}" = "direct" ]; }

# 目标 postgres 容器：AIA_PG_CONTAINER 优先，否则取 compose 项目里的 postgres 服务。
aia_pg_container() {
  if aia_psql_direct; then printf '%s\n' "direct"; return 0; fi
  if [ -n "${AIA_PG_CONTAINER:-}" ]; then printf '%s\n' "$AIA_PG_CONTAINER"; return 0; fi
  local id
  id="$("$AIA_ROOT/deploy/scripts/compose.sh" ps -q postgres 2>/dev/null | head -n1 || true)"
  [ -n "$id" ] || aia_die "找不到运行中的 compose postgres 容器；请先 deploy/scripts/up.sh，或用 AIA_PG_CONTAINER / --container 指定。"
  printf '%s\n' "$id"
}

# 在容器内以容器自身的 POSTGRES_USER 跑 psql（本地 socket，不经网络、不暴露密码）。
# 用法：aia_psql <container> <db> [psql 参数...]   （SQL 从 stdin 或 -c 传入）
aia_psql() {
  local c="$1" db="$2"; shift 2
  if aia_psql_direct; then
    psql -X -v ON_ERROR_STOP=1 -d "$db" "$@"
    return
  fi
  aia_docker exec -i -e AIA_TARGET_DB="$db" "$c" \
    sh -c 'exec psql -X -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-postgres}" -d "$AIA_TARGET_DB" "$@"' sh "$@"
}

# 从基础 compose 文件读取 postgres 服务的镜像（含 digest）。
aia_compose_image() {
  local svc="${1:-postgres}"
  awk -v svc="  ${svc}:" '
    $0 == svc { insvc = 1; next }
    insvc && /^  [A-Za-z0-9_-]+:/ { insvc = 0 }
    insvc && $1 == "image:" { print $2; exit }
  ' "$AIA_ROOT/deploy/compose/docker-compose.yml"
}
