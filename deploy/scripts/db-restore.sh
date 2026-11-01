#!/usr/bin/env bash
# 从 db-backup.sh 的 dump 恢复到"新库"（TimescaleDB 官方流程：
#   CREATE DATABASE → CREATE EXTENSION timescaledb（同版本）→ timescaledb_pre_restore()
#   → pg_restore → timescaledb_post_restore() → ANALYZE）。
#   deploy/scripts/db-restore.sh <file.dump> --db aia_restore_check
#   deploy/scripts/db-restore.sh <file.dump> --db aia_restore_check --container <名字>
# 默认串行 pg_restore（-j 1）：TimescaleDB 目录表之间有循环外键，并行恢复会因 COPY 顺序触发外键错误（演练实测）。
# 安全限制：
#   * 目标库已存在 → 拒绝（加 --drop-existing 才会先删除；对容器的 POSTGRES_DB 主库永远拒绝删除，
#     要覆盖主库请先人工停应用、改名旧库，再恢复到新名字后切换）。
#   * dump 的 TimescaleDB 版本必须与目标容器已安装版本一致（读取同名 .meta.json；无 meta 时用 pg_restore -l 推断）。
set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

DUMP=""; DB=""; CONTAINER="${AIA_PG_CONTAINER:-}"; DROP=0; JOBS="${AIA_RESTORE_JOBS:-1}"
while [ $# -gt 0 ]; do
  case "$1" in
    --db) DB="$2"; shift 2 ;;
    --container) CONTAINER="$2"; shift 2 ;;
    --drop-existing) DROP=1; shift ;;
    --jobs) JOBS="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    -*) aia_die "未知参数：$1" ;;
    *) DUMP="$1"; shift ;;
  esac
done
[ -f "$DUMP" ] || aia_die "dump 文件不存在：${DUMP:-（未指定）}"
[ -n "$DB" ] || aia_die "必须用 --db 指定目标库名（建议新库名，如 aia_restore_YYYYMMDD）"
[[ "$DB" =~ ^[a-z_][a-z0-9_]{0,62}$ ]] || aia_die "库名只允许小写字母/数字/下划线：$DB"
[ -n "$CONTAINER" ] || CONTAINER="$(aia_pg_container)"
MAIN_DB="$(aia_docker exec "$CONTAINER" sh -c 'printf %s "${POSTGRES_DB:-postgres}"')"
q() { aia_psql "$CONTAINER" postgres -qtA -c "$1"; }

# 1) 版本检查
META="${DUMP%.dump}.meta.json"
if [ -f "$META" ]; then
  DUMP_TS="$(sed -n 's/.*"timescaledb_version": *"\([^"]*\)".*/\1/p' "$META")"
  DUMP_PG="$(sed -n 's/.*"postgres_version": *"\([^"]*\)".*/\1/p' "$META")"
  WANT_SHA="$(sed -n 's/.*"sha256": *"\([^"]*\)".*/\1/p' "$META")"
  [ "$(sha256sum "$DUMP" | cut -d' ' -f1)" = "$WANT_SHA" ] || aia_die "dump sha256 与 meta 不符，文件可能损坏"
else
  DUMP_PG="?"; DUMP_TS=""   # pg_restore -l 不含扩展版本；无 meta 时只能由操作者保证同版本
  aia_log "WARN: 未找到 $META，跳过 dump 版本校验"
fi
AVAIL_TS="$(q "select default_version from pg_available_extensions where name='timescaledb'")"
SRV_PG="$(q "show server_version")"
if [ -n "$DUMP_TS" ] && [ "$DUMP_TS" != "$AVAIL_TS" ]; then
  aia_die "TimescaleDB 版本不一致：dump=$DUMP_TS，目标容器=$AVAIL_TS（官方要求同版本恢复；请用对应版本镜像恢复后再 ALTER EXTENSION 升级）"
fi
[ "$DUMP_PG" = "?" ] || [ "${DUMP_PG%%.*}" = "${SRV_PG%%.*}" ] || aia_die "PostgreSQL 主版本不一致：dump=$DUMP_PG 目标=$SRV_PG"
aia_log "版本：dump PG ${DUMP_PG} / TS ${DUMP_TS:-?}；目标 PG $SRV_PG / TS $AVAIL_TS"

# 2) 目标库
if [ "$(q "select count(*) from pg_database where datname='$DB'")" != "0" ]; then
  [ "$DB" != "$MAIN_DB" ] || aia_die "目标库 $DB 是容器主库（POSTGRES_DB），拒绝覆盖"
  [ "$DROP" -eq 1 ] || aia_die "目标库 $DB 已存在（加 --drop-existing 才会删除重建）"
  aia_log "删除已存在的目标库 $DB"
  q "DROP DATABASE \"$DB\" WITH (FORCE)" >/dev/null
fi
q "CREATE DATABASE \"$DB\"" >/dev/null
aia_psql "$CONTAINER" "$DB" -qtA -c "SET client_min_messages = warning; CREATE EXTENSION IF NOT EXISTS timescaledb VERSION '$AVAIL_TS'" >/dev/null
aia_psql "$CONTAINER" "$DB" -qtA -c "SELECT timescaledb_pre_restore()" >/dev/null

# 3) pg_restore（拷入容器临时目录以便并行 -j；结束即删除）
TMP_IN="/tmp/aia-restore-$$.dump"
cleanup() { aia_docker exec "$CONTAINER" rm -f "$TMP_IN" >/dev/null 2>&1 || true; }
trap cleanup EXIT
aia_docker cp -q "$DUMP" "$CONTAINER:$TMP_IN"
aia_docker exec -u root "$CONTAINER" chmod 644 "$TMP_IN"
START=$(date +%s); RC=0
OUT="$(aia_docker exec -e AIA_TARGET_DB="$DB" -e AIA_IN="$TMP_IN" -e AIA_J="$JOBS" "$CONTAINER" \
  sh -c 'pg_restore -U "${POSTGRES_USER:-postgres}" -d "$AIA_TARGET_DB" -j "$AIA_J" --no-password "$AIA_IN"' 2>&1)" || RC=$?
# 已预先 CREATE EXTENSION，dump 里的同名扩展/注释报 "already exists" 属预期；其他错误视为失败。
BAD="$(printf '%s\n' "$OUT" | grep -E 'error:' | grep -vE 'extension "timescaledb" already exists|COMMENT ON EXTENSION|errors ignored on restore' || true)"
aia_psql "$CONTAINER" "$DB" -qtA -c "SELECT timescaledb_post_restore()" >/dev/null
aia_psql "$CONTAINER" "$DB" -q -c "ANALYZE" >/dev/null
SECS=$(( $(date +%s) - START ))
if [ -n "$BAD" ]; then
  printf '%s\n' "$OUT" >&2
  aia_die "pg_restore 有未预期的错误（rc=$RC），见上"
fi
aia_log "恢复完成：库 $DB，用时 ${SECS}s（pg_restore rc=$RC，仅预期内告警）"
