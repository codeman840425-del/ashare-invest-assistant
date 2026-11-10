#!/usr/bin/env bash
# shellcheck disable=SC1091
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
  wrapup_log "compose up $*"
  "$COMPOSE" up -d --wait --wait-timeout "${UP_WAIT_TIMEOUT:-300}" "$@"
}

if ! wrapup_need_apply "按顺序启动/重建栈（保留数据卷，不 down -v）"; then
  wrapup_log "dry-run 将依次执行："
  wrapup_log "  1. $COMPOSE up -d --wait --no-deps postgres redis"
  wrapup_log "  2. $COMPOSE up --wait --no-deps migrate"
  wrapup_log "  3. $COMPOSE up --wait --no-deps timescale-apply"
  wrapup_log "  4. $COMPOSE up --wait --no-deps db-roles"
  wrapup_log "  5. $COMPOSE up -d --wait --no-deps api worker beat ingest signal-rt nginx"
  wrapup_log "失败即停。migrate 前请先只读核对 alembic current 是否在目标链上；库已在 0029 且与入链文件不一致则停手（T-A70），不 stamp、不 downgrade。"
  exit 0
fi

"$AIA_ROOT/deploy/scripts/compose.sh" --resolve | wrapup_redact || true

# 先停应用（postgres/redis 可留），避免热重载读到半截代码
for svc in api worker beat ingest signal-rt nginx; do
  "$COMPOSE" stop "$svc" >/dev/null 2>&1 || true
done

up_one --no-deps postgres redis
up_one --no-deps migrate
up_one --no-deps timescale-apply
up_one --no-deps db-roles
up_one --no-deps api worker beat ingest signal-rt nginx
"$COMPOSE" ps -a | wrapup_redact
wrapup_log "栈已按顺序起来。若需要主数据首导：deploy/scripts/master-bootstrap.sh --check，再 --run --confirm-network-fetch。"
