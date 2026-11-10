#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2016
# shellcheck source=lib.sh
{ set +x; } 2>/dev/null
set -euo pipefail
WRAPUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
# shellcheck disable=SC1091
. "$WRAPUP_DIR/lib.sh"

usage() { echo "用法：start-stack.sh [--apply] [--backup-dir 本轮DEST时间戳目录]"; echo "顺序：核对本轮 DEST（manifest+dump）→ postgres/redis → 只读 alembic_version → migrate → timescale-apply → db-roles → engine_policy seed → 其余服务（含 worker）。不启动 master-bootstrap profile。--apply 的 --backup-dir 必须是 backup.sh 本轮打印的 DEST，不能是父目录。"; }
wrapup_parse_common "$@" || { [ $? -eq 99 ] && usage && exit 0; exit 1; }

wrapup_log "模式=$(wrapup_mode)。新网络层（internal / egress / edge）随 compose up 创建，不要 down -v，不要 prune。"
wrapup_log "启动顺序：先 migrate，再 timescale-apply，再 db-roles，再 engine_policy seed，然后各应用服务与 nginx（seed 在启动 worker 之前）。"
wrapup_log "主数据首导不要在本脚本里跑；engine_policy seed 由本脚本在 db-roles 之后、worker 之前执行。栈起来且需要导入时再用 deploy/scripts/master-bootstrap.sh。"

up_one() {
  wrapup_log "compose up --build $*"
  "$COMPOSE" up -d --build --wait --wait-timeout "${UP_WAIT_TIMEOUT:-300}" "$@"
}

# migrate / db-roles 之后、启动 worker 之前。只认 stdout 整段为
# engine_policy_seed_inserted=0 或 1；写入本轮 DEST 收据。冲突、非 0、无法解析则不启 worker、不删行。
wrapup_seed_engine_policy() {
  local dest="${WRAPUP_BACKUP_DIR:-}" outf errf rc line val
  wrapup_log "engine_policy seed：保留默认 entrypoint，DSN 只在容器内从 \$DATABASE_URL 展开，不开 set -x，不打印 DSN"
  if [ "$WRAPUP_APPLY" -eq 0 ]; then
    wrapup_log "dry-run: 将要执行（未写入）：compose.sh run --rm --no-deps -T worker sh -c 'python -m app.engine_policies --database-url \"\$DATABASE_URL\"'"
    wrapup_log "dry-run：只认 engine_policy_seed_inserted=0 或 1，写入本轮 DEST；冲突、非 0 或无法解析则不启 worker、不删除旧行"
    return 0
  fi
  [ -n "$dest" ] || wrapup_die "没有本轮 DEST，无法写入 seed 收据；不启动 worker"
  outf="$(mktemp)"
  errf="$(mktemp)"
  { set +x; } 2>/dev/null
  set +e
  "$COMPOSE" run --rm --no-deps -T worker sh -c \
    'python -m app.engine_policies --database-url "$DATABASE_URL"' >"$outf" 2>"$errf"
  rc=$?
  set -e
  { set +x; } 2>/dev/null
  if [ -s "$errf" ]; then
    wrapup_redact <"$errf" >&2 || true
  fi
  if grep -q 'engine_policy_version_hash_conflict' "$outf" "$errf"; then
    rm -f "$outf" "$errf"
    wrapup_die "engine_policy_version_hash_conflict：立即停止，不启动 worker，不删除旧行"
  fi
  if [ "$rc" -ne 0 ]; then
    rm -f "$outf" "$errf"
    wrapup_die "engine_policy seed 退出码为 ${rc}：立即停止，不启动 worker，不删除旧行"
  fi
  line="$(tr -d '\r' <"$outf" | sed '/^[[:space:]]*$/d')"
  rm -f "$outf" "$errf"
  case "$line" in
    engine_policy_seed_inserted=0|engine_policy_seed_inserted=1) val="${line#engine_policy_seed_inserted=}" ;;
    *) wrapup_die "engine_policy seed 输出无法解析为 engine_policy_seed_inserted=0 或 1：立即停止，不启动 worker，不删除旧行" ;;
  esac
  printf 'engine_policy_seed_inserted=%s\n' "$val" >"$dest/engine_policy_seed.txt"
  chmod 600 "$dest/engine_policy_seed.txt"
  wrapup_log "已写入本轮收据 $dest/engine_policy_seed.txt：engine_policy_seed_inserted=$val"
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
  wrapup_log "  7. engine_policy seed（保留默认 entrypoint；只认 inserted=0 或 1，写入本轮 DEST）"
  wrapup_log "  8. $COMPOSE up -d --build --wait --no-deps api worker beat ingest signal-rt nginx"
  wrapup_seed_engine_policy
  wrapup_log "失败即停：seed 遇到 engine_policy_version_hash_conflict、非 0 或无法解析则不启 worker、不删旧行。库已在 0029 且对象与入链不一致则停手问编排者（T-A70），不 stamp、不 downgrade。"
  exit 0
fi

wrapup_require_round_backup "$WRAPUP_BACKUP_DIR"

"$COMPOSE" --resolve | wrapup_redact || true

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
"${WRAPUP_DB_PRECHECK:-$AIA_ROOT/deploy/scripts/db-precheck-0017.sh}" --container "$pgc" --db "$pgdb"

up_one --no-deps migrate
up_one --no-deps timescale-apply
up_one --no-deps db-roles
wrapup_seed_engine_policy
up_one --no-deps api worker beat ingest signal-rt nginx
"$COMPOSE" ps -a | wrapup_redact
wrapup_log "栈已按顺序起来（engine_policy seed 已在启动 worker 之前完成）。若需要主数据首导：由编排者在收口时下令后跑 deploy/scripts/master-bootstrap.sh --check，再 --run --confirm-network-fetch。"
