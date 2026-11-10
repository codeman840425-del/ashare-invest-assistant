#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2012
# shellcheck source=lib.sh
{ set +x; } 2>/dev/null
set -euo pipefail
WRAPUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
# shellcheck disable=SC1091
# shellcheck disable=SC2012
. "$WRAPUP_DIR/lib.sh"

usage() { echo "用法：rollback.sh --apply --backup-dir DIR [--container C] [--db 新库名] [--rollback-head SHA]"; echo "回滚到备份当时的提交（默认 $WRAPUP_KNOWN_OLD_HEAD）并恢复 0029 未跟踪副本。禁止 down -v / prune / 覆盖主库。"; }
wrapup_parse_common "$@" || { [ $? -eq 99 ] && usage && exit 0; exit 1; }

[ "$WRAPUP_APPLY" -eq 1 ] || wrapup_die "rollback 必须显式 --apply，并由编排者在收口时下令；若回滚失败必须停下来问编排者"
[ -d "$WRAPUP_BACKUP_DIR" ] || wrapup_die "找不到备份目录 $WRAPUP_BACKUP_DIR"
# 允许传入时间戳子目录或包含 manifest 的目录
MAN="$WRAPUP_BACKUP_DIR/manifest.json"
if [ ! -f "$MAN" ]; then
  # 若传入的是 wrapup 根目录，取最新一档
  latest="$(ls -1d "$WRAPUP_BACKUP_DIR"/20* 2>/dev/null | tail -1 || true)"
  if [ -z "$latest" ] || [ ! -f "$latest/manifest.json" ]; then
    wrapup_die "备份目录里没有 manifest.json"
  fi
  WRAPUP_BACKUP_DIR="$latest"
  MAN="$WRAPUP_BACKUP_DIR/manifest.json"
fi
wrapup_log "使用备份 $WRAPUP_BACKUP_DIR"
wrapup_log "回滚代码目标：$WRAPUP_ROLLBACK_HEAD（部署前 team-b 头，默认 $WRAPUP_KNOWN_OLD_HEAD）"

NEWDB="${WRAPUP_PG_DB:-}"
if [ -z "$NEWDB" ]; then
  NEWDB="aia_rollback_$(date -u +%Y%m%dT%H%M%S)"
  # 本机模拟必须 o69_
  case "${WRAPUP_PG_CONTAINER:-}" in
    o61-pg|o61-*) NEWDB="o69_rollback_dst" ;;
  esac
fi
wrapup_log "将把 dump 恢复到新库名 $NEWDB（不 --drop-existing 主库，不覆盖 POSTGRES_DB）"

dump="$(ls -1 "$WRAPUP_BACKUP_DIR"/*.dump 2>/dev/null | head -1 || true)"
[ -n "$dump" ] || wrapup_die "备份里没有 .dump"
if [ -z "$WRAPUP_PG_CONTAINER" ]; then
  wrapup_die "请用 --container 指定 postgres 容器（不要对受保护实例做覆盖）"
fi
wrapup_pg_restore_to "$WRAPUP_PG_CONTAINER" "$dump" "$NEWDB"
wrapup_log "库已恢复到 $NEWDB。切换主库连接须人工改配置后重启应用，不要 drop 现网主库。"

# 卷：恢复到新卷名，避免直接清空现网卷
prefix="$(cat "$WRAPUP_BACKUP_DIR/volume-prefix.txt" 2>/dev/null || true)"
if [ -z "$prefix" ]; then
  prefix="$(wrapup_prefix 2>/dev/null || true)"
fi
if [ -n "$prefix" ]; then
  for suf in "${WRAPUP_VOL_SUFFIXES[@]}"; do
    tgz="$WRAPUP_BACKUP_DIR/${suf}.tgz"
    [ -f "$tgz" ] || continue
    newvol="${prefix}_${suf}_rollback_$(date -u +%Y%m%dT%H%M%S)"
    case "$prefix" in
      o69) newvol="o69_${suf}_rollback" ;;
    esac
    wrapup_log "恢复 $suf 到新卷 $newvol（不 docker volume rm 原卷，不 down -v）"
    wrapup_docker volume create "$newvol" >/dev/null
    wrapup_docker run --rm --network none -v "$newvol:/v" -v "$WRAPUP_BACKUP_DIR:/in:ro" alpine:3.21 \
      sh -c "umask 077 && tar -C /v -xzf /in/$(basename "$tgz")"
  done
  wrapup_log "新卷已就绪。把 compose 卷名切过去或复制回原卷、以及任何删除数据或卷的操作，必须停下来问编排者。严禁 volume rm 现网卷。"
fi

# 代码：新 worktree 指向旧头，把 0029 未跟踪副本放回去
src0029=""
shopt -s nullglob
for cand in "$WRAPUP_BACKUP_DIR/0029-untracked/"*; do
  case "$cand" in *.sha) continue ;; esac
  src0029="$cand"
  break
done
shopt -u nullglob
parent="$(dirname "$AIA_ROOT")"
wt="$parent/$(basename "$AIA_ROOT")-rollback-$(date +%Y%m%dT%H%M%S)"
git -C "$AIA_ROOT" worktree add --detach "$wt" "$WRAPUP_ROLLBACK_HEAD"
wrapup_log "回滚工作树 $wt 指向 $WRAPUP_ROLLBACK_HEAD（原树未 reset）"
if [ -n "$src0029" ]; then
  dest="$wt/$WRAPUP_0029_REL"
  mkdir -p "$(dirname "$dest")"
  cp -a "$src0029" "$dest"
  hash="$(git -C "$wt" hash-object "$dest")"
  wrapup_log "已把 0029 以未跟踪文件放回，hash=$hash（期望 $WRAPUP_BLOB_0029）"
  [ "$hash" = "$WRAPUP_BLOB_0029" ] || wrapup_die "放回的 0029 与已知 blob 不一致"
fi
wrapup_log "回滚代码与数据副本次已就绪。切换服务与改库连接由编排者在收口时下令；若回滚失败或要删除数据/卷，必须停下来问编排者。不要 down -v。"
