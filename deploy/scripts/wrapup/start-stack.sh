#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2016
# shellcheck source=lib.sh
{ set +x; } 2>/dev/null
set -euo pipefail
WRAPUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
# shellcheck disable=SC1091
. "$WRAPUP_DIR/lib.sh"

usage() { echo "用法：start-stack.sh [--apply]"; echo "顺序：postgres/redis → migrate → timescale-apply → db-roles → 其余服务。不启动 master-bootstrap profile。"; }
wrapup_parse_common "$@" || { [ $? -eq 99 ] && usage && exit 0; exit 1; }

wrapup_log "模式=$(wrapup_mode)。新网络层（internal / egress / edge）随 compose up 创建，不要 down -v，不要 prune。"
wrapup_log "启动顺序与 compose depends_on / up.sh 一致：先 migrate，再 timescale-apply，再 db-roles，然后各应用服务与 nginx。"
wrapup_log "主数据首导不要在本脚本里跑，更不要 compose run；栈起来且需要导入时再用 deploy/scripts/master-bootstrap.sh。"

up_one() {
  wrapup_log "compose up --build $*"
  "$COMPOSE" up -d --build --wait --wait-timeout "${UP_WAIT_TIMEOUT:-300}" "$@"
}

if [ "$WRAPUP_PRECHECK_ONLY" -eq 1 ]; then
  if [ -z "$WRAPUP_PG_CONTAINER" ] || [ -z "$WRAPUP_PG_DB" ]; then
    wrapup_die "--precheck-only 需要 --container 与 --db"
  fi
  wrapup_check_alembic_0029 "$WRAPUP_PG_CONTAINER" "$WRAPUP_PG_DB"
  wrapup_log "precheck-only 完成，未启动或迁移任何服务"
  exit 0
fi

if ! wrapup_need_apply "按顺序启动/重建栈（保留数据卷，不 down -v）"; then
  wrapup_log "dry-run 将依次执行："
  wrapup_log "  0. 核对本轮 manifest 与 dump；没有则拒绝 --apply"
  wrapup_log "  1. $COMPOSE up -d --build --wait --no-deps postgres redis"
  wrapup_log "  2. 只读 alembic_version；若已是 0029 则比对 ingest_private/触发器/函数（T-A70）"
  wrapup_log "  3. db-precheck-0017.sh（只读）"
  wrapup_log "  4. $COMPOSE up -d --build --wait --no-deps migrate"
  wrapup_log "  5. $COMPOSE up -d --build --wait --no-deps timescale-apply"
  wrapup_log "  6. $COMPOSE up -d --build --wait --no-deps db-roles"
  wrapup_log "  7. $COMPOSE up -d --build --wait --no-deps api worker beat ingest signal-rt nginx"
  wrapup_log "失败即停。库已在 0029 且对象与入链不一致则停手问编排者（T-A70），不 stamp、不 downgrade。"
  exit 0
fi

wrapup_require_round_backup "$WRAPUP_BACKUP_DIR"

"$AIA_ROOT/deploy/scripts/compose.sh" --resolve | wrapup_redact || true

# 先停应用（postgres/redis 可留），避免热重载读到半截代码
for svc in api worker beat ingest signal-rt nginx; do
  "$COMPOSE" stop "$svc" >/dev/null 2>&1 || true
done

up_one --no-deps postgres redis

pgc="${WRAPUP_PG_CONTAINER:-}"
if [ -z "$pgc" ]; then
  pgc="$("$COMPOSE" ps -q postgres | head -n1 || true)"
fi
[ -n "$pgc" ] || wrapup_die "postgres 起来后仍找不到容器，拒绝 migrate"
pgdb="${WRAPUP_PG_DB:-}"
if [ -z "$pgdb" ]; then
  pgdb="$(wrapup_docker exec "$pgc" sh -c 'printf %s "${POSTGRES_DB:-postgres}"')"
fi
wrapup_check_alembic_0029 "$pgc" "$pgdb"
"$AIA_ROOT/deploy/scripts/db-precheck-0017.sh" --container "$pgc" --db "$pgdb"

up_one --no-deps migrate
up_one --no-deps timescale-apply
up_one --no-deps db-roles
up_one --no-deps api worker beat ingest signal-rt nginx
"$COMPOSE" ps -a | wrapup_redact
wrapup_log "栈已按顺序起来。若需要主数据首导：由编排者在收口时下令后跑 deploy/scripts/master-bootstrap.sh --check，再 --run --confirm-network-fetch。"
