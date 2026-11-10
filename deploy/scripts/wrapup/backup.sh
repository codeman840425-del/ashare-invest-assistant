#!/usr/bin/env bash
# shellcheck disable=SC1091
# shellcheck source=lib.sh
{ set +x; } 2>/dev/null
set -euo pipefail
WRAPUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
# shellcheck disable=SC1091
. "$WRAPUP_DIR/lib.sh"

usage() { sed -n '1,8p' "$0"; echo "用法：backup.sh [--apply] [--backup-dir DIR] [--container C] [--db NAME] [--volume-prefix P]"; }
wrapup_parse_common "$@" || { [ $? -eq 99 ] && usage && exit 0; exit 1; }

OUT="$WRAPUP_BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$OUT/$STAMP"
wrapup_log "模式=$(wrapup_mode)。备份目录 $DEST（默认不写入）"

record_images() {
  local f="$1"
  if [ -n "$WRAPUP_PG_CONTAINER" ]; then
    wrapup_docker inspect -f '{{.Name}} {{.Config.Image}}' "$WRAPUP_PG_CONTAINER" >>"$f" || true
    return 0
  fi
  if [ -x "$COMPOSE" ] && [ -f "$AIA_ROOT/deploy/env/.env" ]; then
    if "$COMPOSE" ps -q >/dev/null 2>&1; then
      "$COMPOSE" ps --format '{{.Name}} {{.Image}}' >>"$f" 2>/dev/null || true
    fi
  fi
}

write_manifest() {
  local dir="$1" dump="${2:-}"
  {
    echo "{"
    echo "  \"created_at_utc\": \"$STAMP\","
    echo "  \"git_head\": \"$(git -C "$AIA_ROOT" rev-parse HEAD)\","
    echo "  \"git_describe\": \"$(git -C "$AIA_ROOT" describe --always --dirty --abbrev=40)\","
    echo "  \"rollback_head\": \"$WRAPUP_ROLLBACK_HEAD\","
    echo "  \"blob_0029\": \"$WRAPUP_BLOB_0029\","
    echo "  \"volume_prefix\": \"${WRAPUP_VOLUME_PREFIX:-}\","
    echo "  \"pg_container\": \"${WRAPUP_PG_CONTAINER:-}\","
    echo "  \"pg_db\": \"${WRAPUP_PG_DB:-}\","
    echo "  \"dump_file\": \"$(basename "$dump")\""
    echo "}"
  } >"$dir/manifest.json"
  chmod 600 "$dir/manifest.json"
}

snapshot_vol() {
  local vol="$1" dest="$2"
  if ! wrapup_docker volume inspect "$vol" >/dev/null 2>&1; then
    wrapup_log "卷 $vol 不存在，跳过快照"
    echo "missing $vol" >>"$DEST/volumes.txt"
    return 0
  fi
  local base
  base="$(basename "$dest")"
  wrapup_docker run --rm --network none \
    -v "$vol:/v:ro" -v "$DEST:/out" \
    alpine:3.21 \
    sh -c "umask 077 && tar -C /v -czf /out/$base . && chown $(id -u):$(id -g) /out/$base && chmod 600 /out/$base"
  wrapup_log "已快照 $vol -> $base（$(stat -c %s "$dest") bytes, sha256 $(sha256sum "$dest" | awk '{print substr($1,1,16)}')…）"
  echo "$vol $base $(sha256sum "$dest" | awk '{print $1}')" >>"$DEST/volumes.txt"
}

if ! wrapup_need_apply "创建 $DEST 并写入 pg_dump、具名卷快照、提交与镜像记录"; then
  wrapup_log "dry-run 将备份到 $DEST"
  wrapup_log "  - pg_dump -Fc + .meta.json（不覆盖主库；格式与 db-backup.sh 同类）"
  wrapup_log "  - 快照具名卷：${WRAPUP_VOL_SUFFIXES[*]}（不含运行中的 pgdata 原始卷；库用 dump）"
  wrapup_log "  - 记录 git HEAD 与镜像 tag；不打印密钥、不 cat .env"
  wrapup_log "回滚依赖本目录，见 rollback.sh 与手册「回滚」"
  exit 0
fi

mkdir -p "$DEST"
chmod 700 "$OUT" 2>/dev/null || true
chmod 700 "$DEST"
: >"$DEST/images.txt"
: >"$DEST/volumes.txt"
chmod 600 "$DEST/images.txt" "$DEST/volumes.txt"
git -C "$AIA_ROOT" rev-parse HEAD >"$DEST/git-head.txt"
git -C "$AIA_ROOT" status --porcelain >"$DEST/git-status.porcelain" || true
git -C "$AIA_ROOT" log -1 --format='%H %s' >"$DEST/git-log-tip.txt"
chmod 600 "$DEST/git-head.txt" "$DEST/git-status.porcelain" "$DEST/git-log-tip.txt"
record_images "$DEST/images.txt" || true
# 尝试只读记录 alembic（失败不阻断备份）
if [ -n "$WRAPUP_PG_CONTAINER" ] && [ -n "$WRAPUP_PG_DB" ]; then
  wrapup_docker exec "$WRAPUP_PG_CONTAINER" \
    psql -X -q -At -U "${POSTGRES_USER:-postgres}" -d "$WRAPUP_PG_DB" \
    -c 'select version_num from alembic_version' >"$DEST/alembic_version.txt" 2>/dev/null || true
fi

DUMP=""
if [ -n "$WRAPUP_PG_CONTAINER" ] && [ -n "$WRAPUP_PG_DB" ]; then
  case "$WRAPUP_PG_DB" in
    postgres|template0|template1) wrapup_die "拒绝以系统库 $WRAPUP_PG_DB 作为 dump 源之外的随意目标；请明确业务库名" ;;
  esac
  wrapup_log "pg_dump：容器 $WRAPUP_PG_CONTAINER 库 $WRAPUP_PG_DB"
  DUMP="$DEST/${WRAPUP_PG_DB}-$(date -u +%Y%m%dT%H%M%SZ).dump"
  wrapup_pg_dump_to "$WRAPUP_PG_CONTAINER" "$WRAPUP_PG_DB" "$DUMP"
  chmod 600 "$DUMP"
  # 与 db-backup.sh 类似的侧车元数据（不含密钥）
  {
    echo "{"
    echo "  \"database\": \"$WRAPUP_PG_DB\","
    echo "  \"created_at_utc\": \"$STAMP\","
    echo "  \"format\": \"pg_dump -Fc\","
    echo "  \"pg_port\": \"$(wrapup_pg_port "$WRAPUP_PG_CONTAINER")\","
    echo "  \"dump_file\": \"$(basename "$DUMP")\","
    echo "  \"size_bytes\": $(stat -c %s "$DUMP"),"
    echo "  \"sha256\": \"$(sha256sum "$DUMP" | awk '{print $1}')\""
    echo "}"
  } >"${DUMP%.dump}.meta.json"
  chmod 600 "${DUMP%.dump}.meta.json"
  wrapup_log "dump 完成：$(basename "$DUMP")"
else
  wrapup_log "未指定 --container 与 --db：尝试 compose 默认 postgres"
  if "$COMPOSE" ps -q postgres >/dev/null 2>&1 && [ -n "$("$COMPOSE" ps -q postgres 2>/dev/null || true)" ]; then
    DUMP="$("$AIA_ROOT/deploy/scripts/db-backup.sh" --out-dir "$DEST")"
    wrapup_log "dump 完成：$(basename "$DUMP")"
  else
    wrapup_die "没有可用的 postgres 容器，无法写出 pg dump。本轮没有 dump，拒绝继续写入（T-A102 B1）"
  fi
fi

if [ -z "${DUMP:-}" ] || [ ! -s "${DUMP:-/}" ]; then
  wrapup_die "本轮没有写出 pg dump，拒绝写 manifest 与后续步骤（T-A102 B1）"
fi

prefix="$(wrapup_prefix 2>/dev/null || true)"
if [ -z "$prefix" ]; then
  wrapup_die "未解析到卷前缀，拒绝跳过具名卷快照（可加 --volume-prefix）（T-A102 B1）"
fi
wrapup_log "卷前缀 $prefix"
echo "$prefix" >"$DEST/volume-prefix.txt"
for suf in "${WRAPUP_VOL_SUFFIXES[@]}"; do
  snapshot_vol "${prefix}_${suf}" "$DEST/${suf}.tgz"
done

write_manifest "$DEST" "$DUMP"
# 只记主密钥 sha256（若文件存在），不输出密钥本身
secrets_dir=""
if [ -x "$COMPOSE" ] && [ -f "$AIA_ROOT/deploy/env/.env" ]; then
  secrets_dir="$("$COMPOSE" --get AIA_SECRETS_DIR 2>/dev/null || true)"
fi
if [ -n "$secrets_dir" ] && [ -f "$secrets_dir/app_master_key" ]; then
  sha256sum "$secrets_dir/app_master_key" | awk '{print $1}' >"$DEST/app_master_key.sha256"
  chmod 600 "$DEST/app_master_key.sha256"
  wrapup_log "已记录 app_master_key 的 sha256（仅摘要，不把密钥放进本目录）"
fi
wrapup_log "备份完成：$DEST"
printf '%s\n' "$DEST"
