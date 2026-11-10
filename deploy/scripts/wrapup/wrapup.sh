#!/usr/bin/env bash
# shellcheck disable=SC1091
# shellcheck source=lib.sh
{ set +x; } 2>/dev/null
set -euo pipefail
WRAPUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
# shellcheck disable=SC1091
. "$WRAPUP_DIR/lib.sh"

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \?//'
  cat <<'EOF'
用法：deploy/scripts/wrapup/wrapup.sh <命令> [选项]
命令：preflight | backup | update-repo | start | halt-check | net-verify | verify | rollback | all
公共选项：默认干跑；写入/破坏性步骤加 --apply。
  --backup-dir DIR   --target SHA   --rollback-head SHA
  --volume-prefix P  --container C  --db NAME  --volume VOL  --repair
详情见 deploy/runbooks/wrapup-deploy.md。Windows 上在 WSL 或 Git Bash 执行。
EOF
}

if [ $# -eq 0 ] || [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi
cmd="$1"; shift
case "$cmd" in
  preflight) ;;
  backup) exec "$WRAPUP_DIR/backup.sh" "$@" ;;
  update-repo) exec "$WRAPUP_DIR/update-repo.sh" "$@" ;;
  start) exec "$WRAPUP_DIR/start-stack.sh" "$@" ;;
  halt-check) exec "$WRAPUP_DIR/halt-check.sh" "$@" ;;
  net-verify) exec "$WRAPUP_DIR/net-verify.sh" "$@" ;;
  verify) exec "$WRAPUP_DIR/verify.sh" "$@" ;;
  rollback) exec "$WRAPUP_DIR/rollback.sh" "$@" ;;
  all) ;;
  *) wrapup_die "未知命令：$cmd" ;;
esac

wrapup_parse_common "$@" || { [ $? -eq 99 ] && usage && exit 0; exit 1; }

preflight() {
  wrapup_log "模式=$(wrapup_mode)。仓库 $AIA_ROOT"
  git -C "$AIA_ROOT" rev-parse --is-inside-work-tree >/dev/null \
    || wrapup_die "不是 git 仓库：$AIA_ROOT"
  local head status
  head="$(git -C "$AIA_ROOT" rev-parse HEAD)"
  wrapup_log "当前 HEAD=$head"
  status="$(git -C "$AIA_ROOT" status --porcelain)"
  if [ -n "$status" ]; then
    wrapup_log "工作区非空（摘要，不含文件内容）："
    printf '%s\n' "$status" | awk '{print "  " $1, $2}' >&2
  else
    wrapup_log "工作区干净"
  fi
  local f hash
  f="$AIA_ROOT/$WRAPUP_0029_REL"
  if [ -e "$f" ]; then
    hash="$(git -C "$AIA_ROOT" hash-object "$f")"
    wrapup_log "0029 路径存在：相对 $WRAPUP_0029_REL hash=${hash:0:12}…（期望 $WRAPUP_BLOB_0029）"
    if [ "$hash" != "$WRAPUP_BLOB_0029" ]; then
      wrapup_die "0029 内容与已知 blob $WRAPUP_BLOB_0029 不一致；停手，不 stamp、不 downgrade、不 down -v（T-A70）"
    fi
  elif git -C "$AIA_ROOT" status --porcelain -- "src/backend/migrations/versions/0029_*.py" | grep -q '^??'; then
    wrapup_log "发现未跟踪 0029，稍后由 update-repo.sh 迁出仓库外备份（不删除）"
  else
    wrapup_log "工作区未见 0029 文件（若目标树已跟踪该 blob，更新后应能对上）"
  fi
  wrapup_log "已知用户机部署前基线（2026-11-09 memory）：$WRAPUP_KNOWN_OLD_HEAD（team-b），未跟踪 0029=$WRAPUP_BLOB_0029"
  wrapup_log "红线：不要 down -v、不要 prune、不要 git reset/force/rebase、不要调麦蕊、不要打印密钥。"
  wrapup_log "主数据首导只许：deploy/scripts/master-bootstrap.sh --check / --run --confirm-network-fetch"
}

preflight
if [ "$cmd" = "all" ]; then
  wrapup_log "all：按手册顺序干跑/执行各步（本命令不会自动 rollback）"
  if [ "$WRAPUP_APPLY" -eq 1 ]; then
    dest="$("$WRAPUP_DIR/backup.sh" "$@")"
    dest="$(printf '%s\n' "$dest" | tail -n 1)"
    [ -n "$dest" ] || wrapup_die "backup.sh 未在标准输出打印本轮 DEST"
    wrapup_require_round_backup "$dest"
    wrapup_log "本轮 DEST=$dest；后续 --apply 一律指向该时间戳目录"
    "$WRAPUP_DIR/update-repo.sh" "$@" --backup-dir "$dest"
    "$WRAPUP_DIR/start-stack.sh" "$@" --backup-dir "$dest"
  else
    "$WRAPUP_DIR/backup.sh" "$@"
    "$WRAPUP_DIR/update-repo.sh" "$@"
    "$WRAPUP_DIR/start-stack.sh" "$@"
  fi
  "$WRAPUP_DIR/halt-check.sh" "$@"
  "$WRAPUP_DIR/net-verify.sh" "$@"
  "$WRAPUP_DIR/verify.sh" "$@"
  wrapup_log "all 结束。主数据首导如需要，再手动跑 master-bootstrap.sh（不要 compose run）。"
fi
