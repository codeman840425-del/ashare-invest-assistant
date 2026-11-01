#!/usr/bin/env bash
# 逻辑备份：pg_dump -Fc（含 TimescaleDB hypertable / 压缩 chunk / 连续聚合 / 策略作业）。
#   deploy/scripts/db-backup.sh                       # 备份 compose postgres 的 POSTGRES_DB 到 deploy/backups/
#   deploy/scripts/db-backup.sh --db aia --out-dir /srv/backups --container <名字>
# 产物：<out-dir>/<db>-<UTC时间>.dump（权限 600）+ 同名 .meta.json（PG/TimescaleDB 版本、镜像、大小、sha256）。
# 恢复必须用同一 TimescaleDB 版本：deploy/scripts/db-restore.sh <dump> --db <新库名>
# deploy/backups/ 与 *.dump 已在 deploy/.gitignore 中排除，绝不入库。
set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

DB=""; CONTAINER="${AIA_PG_CONTAINER:-}"; OUT_DIR="${AIA_BACKUP_DIR:-$AIA_ROOT/deploy/backups}"; COMPRESS="${AIA_BACKUP_COMPRESS:-6}"
while [ $# -gt 0 ]; do
  case "$1" in
    --db) DB="$2"; shift 2 ;;
    --container) CONTAINER="$2"; shift 2 ;;
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) aia_die "未知参数：$1" ;;
  esac
done
[ -n "$CONTAINER" ] || CONTAINER="$(aia_pg_container)"
[ -n "$DB" ] || DB="$(aia_docker exec "$CONTAINER" sh -c 'printf %s "${POSTGRES_DB:-postgres}"')"

umask 077
mkdir -p "$OUT_DIR"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP="$OUT_DIR/$DB-$TS.dump"; META="$OUT_DIR/$DB-$TS.meta.json"; ERR="$(mktemp)"
trap 'rm -f "$ERR"' EXIT

read -r PG_VER TS_VER < <(aia_psql "$CONTAINER" "$DB" -qtA -F ' ' -c \
  "select current_setting('server_version'), coalesce((select extversion from pg_extension where extname='timescaledb'), 'none')")
IMAGE="$(aia_docker inspect -f '{{.Config.Image}}' "$CONTAINER")"
aia_log "备份 容器 ${CONTAINER:0:12} 库 $DB（PG $PG_VER / TimescaleDB $TS_VER）→ ${DUMP#$AIA_ROOT/}"

START=$(date +%s)
# pg_dump 输出走 stdout 直接落到宿主文件，容器内不留临时文件。
if ! aia_docker exec -e AIA_TARGET_DB="$DB" -e AIA_Z="$COMPRESS" "$CONTAINER" \
     sh -c 'exec pg_dump -U "${POSTGRES_USER:-postgres}" -d "$AIA_TARGET_DB" -Fc -Z "$AIA_Z"' >"$DUMP" 2>"$ERR"; then
  cat "$ERR" >&2; rm -f "$DUMP"; aia_die "pg_dump 失败"
fi
# TimescaleDB 目录表之间的循环外键会触发 pg_dump 警告，官方说明可忽略；其余输出照常显示。
grep -vE 'circular foreign-key constraints|hypertable|chunk|You might not be able to restore|Consider using a full dump|^pg_dump: detail: |^pg_dump: hint: ' "$ERR" >&2 || true
SECS=$(( $(date +%s) - START ))
SIZE=$(stat -c %s "$DUMP"); SHA=$(sha256sum "$DUMP" | cut -d' ' -f1)
chmod 600 "$DUMP"
cat >"$META" <<JSON
{
  "database": "$DB",
  "created_at_utc": "$TS",
  "format": "pg_dump -Fc -Z $COMPRESS",
  "postgres_version": "$PG_VER",
  "timescaledb_version": "$TS_VER",
  "image": "$IMAGE",
  "dump_file": "$(basename "$DUMP")",
  "size_bytes": $SIZE,
  "sha256": "$SHA",
  "duration_seconds": $SECS
}
JSON
chmod 600 "$META"
aia_log "完成：$(numfmt --to=iec "$SIZE") ，${SECS}s，sha256 ${SHA:0:16}…"
printf '%s\n' "$DUMP"
