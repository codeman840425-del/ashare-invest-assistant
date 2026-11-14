#!/usr/bin/env bash
# 逻辑备份：pg_dump -Fc（含 TimescaleDB hypertable / 压缩 chunk / 连续聚合 / 策略作业）。
#   deploy/scripts/db-backup.sh                       # 备份 compose postgres 的 POSTGRES_DB 到 deploy/backups/
#   deploy/scripts/db-backup.sh --db aia --out-dir /srv/backups --container <名字>
# 产物：<out-dir>/<db>-<UTC时间>.dump（权限 600）+ 同名 .meta.json（PG/TimescaleDB 版本、镜像、大小、sha256）。
# 恢复必须用同一 TimescaleDB 版本：deploy/scripts/db-restore.sh <dump> --db <新库名>
# deploy/backups/ 与 *.dump 已在 deploy/.gitignore 中排除，绝不入库。
# 保留计划默认普通最新 2 份（--keep N / AIA_BACKUP_KEEP）；protection=true 不计入名额。
# 默认只 dry-run；经批准加 --rotate 才删除候选 dump+meta。--protect 标记本次为保护点。
set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

DB=""; CONTAINER="${AIA_PG_CONTAINER:-}"; OUT_DIR="${AIA_BACKUP_DIR:-$AIA_ROOT/deploy/backups}"; COMPRESS="${AIA_BACKUP_COMPRESS:-6}"
KEEP="${AIA_BACKUP_KEEP:-2}"; ROTATE=0; PROTECTION=false
while [ $# -gt 0 ]; do
  case "$1" in
    --db) DB="$2"; shift 2 ;;
    --container) CONTAINER="$2"; shift 2 ;;
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    --keep) KEEP="$2"; shift 2 ;;
    --rotate) ROTATE=1; shift ;;
    --protect) PROTECTION=true; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) aia_die "未知参数：$1" ;;
  esac
done
[[ "$KEEP" =~ ^[1-9][0-9]{0,5}$ ]] || aia_die "--keep / AIA_BACKUP_KEEP 必须为 1..999999"
command -v python3 >/dev/null || aia_die "备份保留检查需要 python3"
command -v flock >/dev/null || aia_die "并发备份守卫需要 flock"
[ -n "$CONTAINER" ] || CONTAINER="$(aia_pg_container)"
[ -n "$DB" ] || DB="$(aia_docker exec "$CONTAINER" sh -c 'printf %s "${POSTGRES_DB:-postgres}"')"
[[ "$DB" =~ ^[a-z_][a-z0-9_]{0,62}$ ]] || aia_die "库名只允许小写字母/数字/下划线"

umask 077
mkdir -p "$OUT_DIR"
# 同库从写入前到轮转结束持同一永久锁；不删除/替换锁文件。
LOCK="$OUT_DIR/.db-backup-$DB.lock"
[ ! -L "$OUT_DIR" ] && [ ! -L "$LOCK" ] || aia_die "备份目录/锁不允许软链"
exec 9>>"$LOCK"
flock -n 9 || aia_die "同库备份/轮转正在执行，本次停止"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP="$OUT_DIR/$DB-$TS.dump"; META="$OUT_DIR/$DB-$TS.meta.json"
[ ! -e "$DUMP" ] && [ ! -L "$DUMP" ] && [ ! -e "$META" ] && [ ! -L "$META" ] || aia_die "同秒备份已存在，拒绝覆盖"
ERR="$(mktemp)"
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
[ "$SIZE" -gt 0 ] || aia_die "dump 为空，不进行轮转"
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
  "duration_seconds": $SECS,
  "protection": $PROTECTION
}
JSON
chmod 600 "$META"
aia_log "完成：$(numfmt --to=iec "$SIZE") ，${SECS}s，sha256 ${SHA:0:16}…"
retention_args=(--directory "$OUT_DIR" --database "$DB" --keep "$KEEP" --lock-fd 9 --new-backup "$(basename "$DUMP")")
[ "$ROTATE" -eq 0 ] || retention_args+=(--apply)
# 轮转检查失败也保留已生成的新备份；不把异常当成功清理。
python3 "$AIA_ROOT/deploy/scripts/db-backup-retention.py" "${retention_args[@]}" >&2
printf '%s\n' "$DUMP"
