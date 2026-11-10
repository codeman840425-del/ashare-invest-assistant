#!/usr/bin/env bash
# shellcheck disable=SC2034,SC2016
# wrapup 子脚本共用：默认干跑，--apply 才写入；失败即停并打印回滚提示；不打印密钥。
# 被 source，不要直接执行。Windows 上在 WSL 或 Git Bash 里跑（不要用 cmd.exe）。

{ set +x; } 2>/dev/null
set -euo pipefail

WRAPUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AIA_ROOT="$(cd "$WRAPUP_DIR/../../.." && pwd)"
COMPOSE="${COMPOSE:-$AIA_ROOT/deploy/scripts/compose.sh}"

# 编排者 / memory（2026-11-09）：用户电脑仍停在 team-b，有未跟踪 0029。
WRAPUP_KNOWN_OLD_HEAD="f82a83b1817ed2c2388a09602f213a34aa0b93f9"
WRAPUP_BLOB_0029="05774fed18ab70e4ff506c3178107d03b854d31c"
WRAPUP_0029_REL="src/backend/migrations/versions/0029_tb99e_gate_bindings.py"
WRAPUP_HALT_DIR="/run/aia/state/halt"
WRAPUP_STATE_UID="10001"
WRAPUP_STATE_MODE="700"
# 具名卷后缀（与 compose 顶层 volumes 一致）；pgdata 用 pg_dump，不打运行中的原始卷包。
WRAPUP_VOL_SUFFIXES=(ingest_state aia_receipts imports master redisdata)

WRAPUP_APPLY=0
WRAPUP_BACKUP_DIR="${AIA_WRAPUP_BACKUP_DIR:-$AIA_ROOT/deploy/backups/wrapup}"
WRAPUP_TARGET="${AIA_WRAPUP_TARGET:-}"
WRAPUP_ROLLBACK_HEAD="${AIA_WRAPUP_ROLLBACK_HEAD:-$WRAPUP_KNOWN_OLD_HEAD}"
WRAPUP_VOLUME_PREFIX="${AIA_WRAPUP_VOLUME_PREFIX:-}"
WRAPUP_PG_CONTAINER="${AIA_PG_CONTAINER:-}"
WRAPUP_PG_DB="${AIA_WRAPUP_DB:-}"
WRAPUP_VOLUME="${AIA_WRAPUP_VOLUME:-}"
WRAPUP_REPAIR=0
WRAPUP_PRECHECK_ONLY=0
WRAPUP_ARGS=()

wrapup_log() { printf '[%s] %s\n' "$(date +'%Y-%m-%d %H:%M:%S %Z')" "$*" >&2; }

wrapup_rollback_hint() {
  cat >&2 <<'HINT'
失败。不要 down -v，不要 prune，不要 git reset / --force / rebase，不要删别人的卷或受保护实例。
收口部署已由 2026-11-08 长期授权覆盖（先备份，失败回滚，绝不 down -v），--apply 由编排者在收口时下令，不必逐步再问用户。
若遇到 0029 分叉、任何删除数据或卷的操作、或回滚失败：必须停下来问编排者后再继续。
回滚见 deploy/runbooks/wrapup-deploy.md「回滚」：
  deploy/scripts/wrapup/rollback.sh --apply --backup-dir <本轮备份目录>
HINT
}

wrapup_die() {
  wrapup_log "ERROR: $*"
  wrapup_rollback_hint
  exit 1
}

# 过滤可能含口令的行；只用于展示 docker/compose 摘要，不得拿来「解密」。
wrapup_redact() {
  sed -E \
    -e 's/([Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd]|SECRET|LICENCE|LICENSE|API_KEY|MASTER_KEY|TOKEN|AKIA)[^=[:space:]]*[:=][[:space:]]*[^[:space:]]+/\1=***/g' \
    -e 's#(postgres(ql)?(\+psycopg)?://[^:/@]+:)[^@[:space:]]+@#\1***@#g'
}

wrapup_parse_common() {
  WRAPUP_ARGS=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --apply) WRAPUP_APPLY=1; shift ;;
      --backup-dir) WRAPUP_BACKUP_DIR="$2"; shift 2 ;;
      --target) WRAPUP_TARGET="$2"; shift 2 ;;
      --rollback-head) WRAPUP_ROLLBACK_HEAD="$2"; shift 2 ;;
      --volume-prefix) WRAPUP_VOLUME_PREFIX="$2"; shift 2 ;;
      --container) WRAPUP_PG_CONTAINER="$2"; shift 2 ;;
      --db) WRAPUP_PG_DB="$2"; shift 2 ;;
      --volume) WRAPUP_VOLUME="$2"; shift 2 ;;
      --repair) WRAPUP_REPAIR=1; shift ;;
      --precheck-only) WRAPUP_PRECHECK_ONLY=1; shift ;;
      --out-dir) WRAPUP_BACKUP_DIR="$2"; shift 2 ;;
      -h|--help) return 99 ;;
      --) shift; WRAPUP_ARGS+=("$@"); break ;;
      -*) wrapup_die "未知参数：$1（先看 deploy/runbooks/wrapup-deploy.md）" ;;
      *) WRAPUP_ARGS+=("$1"); shift ;;
    esac
  done
}

wrapup_mode() { if [ "$WRAPUP_APPLY" -eq 1 ]; then printf 'apply'; else printf 'dry-run'; fi; }

# 干跑：打印将要做的写入并返回 1（调用方跳过写入）。--apply 返回 0。
wrapup_need_apply() {
  if [ "$WRAPUP_APPLY" -eq 0 ]; then
    wrapup_log "dry-run: 将要执行（未写入）：$*"
    return 1
  fi
  wrapup_log "apply: $*"
  return 0
}

wrapup_prefix() {
  if [ -n "$WRAPUP_VOLUME_PREFIX" ]; then
    printf '%s\n' "$WRAPUP_VOLUME_PREFIX"
    return 0
  fi
  "$COMPOSE" --get AIA_VOLUME_PREFIX
}

wrapup_docker() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
  elif sudo -n docker info >/dev/null 2>&1; then
    sudo -n docker "$@"
  else
    wrapup_die "无法访问 Docker daemon（不要在本脚本里启动无关容器；用户电脑请先自行确认 Docker Desktop 已开）"
  fi
}

# 禁止把受保护实例或共享模板库当作本单临时目标。
wrapup_assert_temp_db_name() {
  local db="$1"
  case "$db" in
    o69_*) ;;
    *) wrapup_die "本机模拟库名必须以 o69_ 开头（拒绝 $db）。受保护实例与 o61_tmp_0030 / tt51_tpl 等一律不许动。" ;;
  esac
}

wrapup_assert_temp_volume() {
  local vol="$1"
  case "$vol" in
    o69_*) ;;
    *) wrapup_die "本机模拟卷名必须以 o69_ 开头（拒绝 $vol）" ;;
  esac
}


# 探测容器内 postgres 的 unix socket 端口（o61-pg 等宿主网络实例不是 5432）。
wrapup_pg_port() {
  local c="$1" p=""
  p="$(wrapup_docker exec "$c" sh -c 'ls /var/run/postgresql/.s.PGSQL.[0-9]* 2>/dev/null' \
      | sed -n 's/.*\.s\.PGSQL\.//p' | head -1 || true)"
  printf '%s\n' "${p:-5432}"
}

# 在容器内以探测到的端口做 pg_dump -Fc，写到宿主 dest。
wrapup_pg_dump_to() {
  local c="$1" db="$2" dest="$3" port
  port="$(wrapup_pg_port "$c")"
  local err
  err="$(mktemp)"
  if ! wrapup_docker exec -e PGPORT="$port" -e PGHOST=/var/run/postgresql -e AIA_TARGET_DB="$db" "$c" \
    sh -c 'exec pg_dump -U "${POSTGRES_USER:-postgres}" -d "$AIA_TARGET_DB" -Fc -Z 6' >"$dest" 2>"$err"; then
    cat "$err" >&2
    rm -f "$err" "$dest"
    wrapup_die "pg_dump 失败"
  fi
  # Timescale 目录表循环外键警告与 db-backup.sh 同样过滤
  grep -vE 'circular foreign-key constraints|hypertable|chunk|You might not be able to restore|Consider using a full dump|^pg_dump: detail: |^pg_dump: hint: ' "$err" >&2 || true
  rm -f "$err"
}

# 在容器内把 dump 恢复到新库名。不 --drop-existing，不覆盖 postgres/template。
wrapup_pg_restore_to() {
  local c="$1" dump="$2" newdb="$3" port tmp
  port="$(wrapup_pg_port "$c")"
  case "$newdb" in
    postgres|template0|template1) wrapup_die "拒绝恢复到系统库 $newdb" ;;
  esac
  case "$newdb" in
    *[!a-z0-9_]*) wrapup_die "库名不合法：$newdb" ;;
  esac
  exists="$(wrapup_docker exec -e PGPORT="$port" -e PGHOST=/var/run/postgresql "$c"     psql -X -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-postgres}" -d postgres -Atc     "SELECT 1 FROM pg_database WHERE datname='${newdb}'")"
  [ -z "$exists" ] || wrapup_die "目标库 $newdb 已存在，拒绝覆盖"
  wrapup_docker exec -e PGPORT="$port" -e PGHOST=/var/run/postgresql "$c"     psql -X -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-postgres}" -d postgres     -c "CREATE DATABASE ${newdb};"
  tmp="/tmp/aia-wrapup-restore-$$.dump"
  wrapup_docker cp "$dump" "$c:$tmp"
  if ! wrapup_docker exec -e PGPORT="$port" -e PGHOST=/var/run/postgresql "$c" \
       pg_restore -U "${POSTGRES_USER:-postgres}" -d "$newdb" --no-owner --no-privileges "$tmp"; then
    wrapup_docker exec "$c" rm -f "$tmp" >/dev/null 2>&1 || true
    wrapup_die "pg_restore 失败（目标库 $newdb 可能不完整，不要改其它库）"
  fi
  wrapup_docker exec "$c" rm -f "$tmp" >/dev/null 2>&1 || true
}

# 本轮备份必须同时有 manifest 和体积非空的 dump，否则拒绝后续写入（T-A102 B1）。
wrapup_require_round_backup() {
  local dir="${1:-$WRAPUP_BACKUP_DIR}" man="" cand d
  [ -n "$dir" ] || wrapup_die "没有备份目录：本轮没有 manifest 和 dump，拒绝后续写入步骤"
  if [ -f "$dir/manifest.json" ]; then
    man="$dir/manifest.json"
  else
    for cand in "$dir"/20*; do
      [ -f "$cand/manifest.json" ] || continue
      man="$cand/manifest.json"
    done
  fi
  [ -n "$man" ] || wrapup_die "本轮没有 manifest 和 dump，拒绝后续写入步骤"
  d="$(dirname "$man")"
  cand=""
  for cand in "$d"/*.dump; do
    [ -f "$cand" ] || continue
    [ -s "$cand" ] || continue
    wrapup_log "本轮备份已核到 manifest 与 dump：$(basename "$d")"
    return 0
  done
  wrapup_die "本轮没有可用的 pg dump，拒绝后续写入步骤"
}

wrapup_pg_query() {
  local c="$1" db="$2" sql="$3" port
  port="$(wrapup_pg_port "$c")"
  wrapup_docker exec -e PGPORT="$port" -e PGHOST=/var/run/postgresql "$c" \
    psql -X -q -At -U "${POSTGRES_USER:-postgres}" -d "$db" -v ON_ERROR_STOP=1 -c "$sql"
}

# 只读核对 alembic_version；已是 0029 则比对 ingest_private / 触发器 / 函数（T-A70 / T-A102 B2）。
wrapup_check_alembic_0029() {
  local c="$1" db="$2" ver schema tables funcs trig
  if [ -z "$c" ] || [ -z "$db" ]; then
    wrapup_die "0029 预检需要 postgres 容器和库名"
  fi
  case "$db" in
    postgres|template0|template1)
      wrapup_die "拒绝在系统库 $db 上做 0029 业务对象比对；请给出业务库名"
      ;;
  esac
  ver="$(wrapup_pg_query "$c" "$db" "SELECT version_num FROM alembic_version" 2>/dev/null || true)"
  if [ -z "$ver" ]; then
    wrapup_log "只读 alembic_version：空或不存在（可能是空库），继续"
    return 0
  fi
  wrapup_log "只读 alembic_version=$ver"
  if [ "$ver" != "0029" ]; then
    wrapup_log "当前不是 0029，不在此做 T-A70 对象比对"
    return 0
  fi
  wrapup_log "库已在 0029，开始只读比对 ingest_private / 触发器 / 函数（T-A70）"
  schema="$(wrapup_pg_query "$c" "$db" "SELECT 1 FROM information_schema.schemata WHERE schema_name='ingest_private'" || true)"
  tables="$(wrapup_pg_query "$c" "$db" "SELECT tablename FROM pg_tables WHERE schemaname='ingest_private' ORDER BY 1" || true)"
  funcs="$(wrapup_pg_query "$c" "$db" "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='ingest_private' ORDER BY 1" || true)"
  trig="$(wrapup_pg_query "$c" "$db" "SELECT t.tgname FROM pg_trigger t JOIN pg_class r ON r.oid=t.tgrelid JOIN pg_namespace n ON n.oid=r.relnamespace WHERE n.nspname='app' AND r.relname='user_data_licences' AND NOT t.tgisinternal AND t.tgname='mairui_gate_on_licence_deletion'" || true)"
  if [ "$schema" = "1" ] \
      && printf '%s\n' "$tables" | grep -qx 'mairui_gate_bindings' \
      && printf '%s\n' "$tables" | grep -qx 'mairui_gate_scopes' \
      && printf '%s\n' "$funcs" | grep -qx 'mairui_gate_licence_deleted' \
      && printf '%s\n' "$funcs" | grep -qx 'prune_mairui_gate_bindings' \
      && [ "$trig" = "mairui_gate_on_licence_deletion" ]; then
    wrapup_log "0029 对象与入链定义一致，可以继续（不 stamp、不 downgrade）"
    return 0
  fi
  wrapup_die "库已在 0029，但 ingest_private/触发器/函数与入链 0029 不一致；停手，不 stamp、不 downgrade、不 migrate（T-A70）。必须停下来问编排者。"
}
