#!/usr/bin/env bash
# shellcheck disable=SC1091
# shellcheck source=lib.sh
{ set +x; } 2>/dev/null
set -euo pipefail
WRAPUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
# shellcheck disable=SC1091
. "$WRAPUP_DIR/lib.sh"

usage() { echo "用法：update-repo.sh [--apply] --target <完整哈希> [--backup-dir DIR]"; }
wrapup_parse_common "$@" || { [ $? -eq 99 ] && usage && exit 0; exit 1; }

[ -n "$WRAPUP_TARGET" ] || wrapup_die "必须用 --target 指定批准的收口头完整哈希（不要用 branch tip 的活标签代替）"
git -C "$AIA_ROOT" cat-file -t "$WRAPUP_TARGET" >/dev/null 2>&1 \
  || wrapup_log "WARN: 本地还没有对象 $WRAPUP_TARGET；--apply 时会 git fetch（dry-run 不 fetch）"

wrapup_log "模式=$(wrapup_mode)。目标 $WRAPUP_TARGET。当前 HEAD=$(git -C "$AIA_ROOT" rev-parse HEAD)"
wrapup_log "出处：用户机若仍停在 $WRAPUP_KNOWN_OLD_HEAD，run_all.py --dry-run 可能以退出码 1 失败（T-B117：运行树与当前基线不一致；T-B05-run-howto 要求 dry-run 必须 rc=0）。"

# 收集未跟踪 0029（可能不止一个匹配）
mapfile -t UNTRACKED_0029 < <(git -C "$AIA_ROOT" ls-files --others --exclude-standard -- 'src/backend/migrations/versions/0029_*.py' || true)

other_dirty="$(git -C "$AIA_ROOT" status --porcelain | awk '$2 !~ /(^|\/)__pycache__(\/|$)/ && $2 !~ /\.pyc$/ && $2 !~ /0029_.*\.py$/ {print}' || true)"
if [ -n "$other_dirty" ]; then
  wrapup_log "除 0029 / __pycache__ 外还有改动或未跟踪文件："
  printf '%s\n' "$other_dirty" | awk '{print "  " $0}' >&2
  if [ "$WRAPUP_APPLY" -eq 1 ]; then
    wrapup_die "先处理这些文件再更新，不能 reset"
  else
    wrapup_log "dry-run：--apply 时将拒绝，直到这些文件被处理（不能 reset）"
  fi
fi

for rel in "${UNTRACKED_0029[@]+"${UNTRACKED_0029[@]}"}"; do
  [ -n "$rel" ] || continue
  hash="$(git -C "$AIA_ROOT" hash-object "$AIA_ROOT/$rel")"
  wrapup_log "未跟踪 $rel hash=$hash"
  if [ "$hash" != "$WRAPUP_BLOB_0029" ]; then
    wrapup_die "未跟踪 0029 与已知 blob $WRAPUP_BLOB_0029 不一致；冻结（T-A70）。不删除该文件。"
  fi
done

plan_move() {
  wrapup_log "将把未跟踪 0029 移到 $WRAPUP_BACKUP_DIR/0029-untracked/（复制+保留，不用 git reset，不删除唯一副本直到确认已迁走）"
}
plan_update() {
  wrapup_log "然后 git fetch（只取批准对象），若 HEAD 是目标祖先则 merge --ff-only；否则在仓库外新 worktree 检出目标哈希，不 rebase、不 force、不改原工作区 HEAD（除非 ff 成功）。"
  wrapup_log "新 worktree 必须沿用原 COMPOSE_PROJECT_NAME / AIA_VOLUME_PREFIX（看 deploy/env/.env，不要把整份含密钥的文件贴进工单）。"
}

if ! wrapup_need_apply "迁出未跟踪 0029 并更新到 $WRAPUP_TARGET"; then
  plan_move
  plan_update
  exit 0
fi

mkdir -p "$WRAPUP_BACKUP_DIR/0029-untracked"
chmod 700 "$WRAPUP_BACKUP_DIR" 2>/dev/null || true
for rel in "${UNTRACKED_0029[@]+"${UNTRACKED_0029[@]}"}"; do
  [ -n "$rel" ] || continue
  base="$(basename "$rel")"
  dest="$WRAPUP_BACKUP_DIR/0029-untracked/${base}.$WRAPUP_BLOB_0029"
  cp -a "$AIA_ROOT/$rel" "$dest"
  chmod 600 "$dest"
  git -C "$AIA_ROOT" hash-object "$dest" >"$dest.sha"
  # 确认副本后再从工作区移走（不是 rm 唯一一份）
  [ "$(cat "$dest.sha")" = "$WRAPUP_BLOB_0029" ] || wrapup_die "0029 副本校验失败，工作区文件未动"
  rm -f "$AIA_ROOT/$rel"
  wrapup_log "已把 $rel 移到 $dest（工作区已移走，备份仍在）"
done
# 清理 pycache（不碰其它脏文件）
find "$AIA_ROOT/src/backend/migrations" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true

# fetch：不改变工作区文件。远程名 origin 若不存在则报错。
if ! git -C "$AIA_ROOT" cat-file -t "$WRAPUP_TARGET" >/dev/null 2>&1; then
  wrapup_log "本地缺少 $WRAPUP_TARGET，执行 git fetch origin"
  git -C "$AIA_ROOT" fetch origin
  git -C "$AIA_ROOT" cat-file -t "$WRAPUP_TARGET" >/dev/null \
    || wrapup_die "fetch 后仍没有 $WRAPUP_TARGET；停手，不要用别的 tip 代替"
fi

HEAD_NOW="$(git -C "$AIA_ROOT" rev-parse HEAD)"
CHECK_ROOT="$AIA_ROOT"
if git -C "$AIA_ROOT" merge-base --is-ancestor "$HEAD_NOW" "$WRAPUP_TARGET"; then
  wrapup_log "可快进：$HEAD_NOW -> $WRAPUP_TARGET"
  git -C "$AIA_ROOT" merge --ff-only "$WRAPUP_TARGET"
  wrapup_log "快进完成：$(git -C "$AIA_ROOT" rev-parse HEAD)"
else
  parent="$(dirname "$AIA_ROOT")"
  base="$(basename "$AIA_ROOT")"
  wt="$parent/${base}-wrapup-$(date +%Y%m%d)"
  [ ! -e "$wt" ] || wt="$parent/${base}-wrapup-$(date +%Y%m%dT%H%M%S)"
  wrapup_log "无法快进（当前 HEAD 不是目标祖先，常见于 team-b $WRAPUP_KNOWN_OLD_HEAD 与 main 分叉）。新建 worktree：$wt"
  git -C "$AIA_ROOT" worktree add --detach "$wt" "$WRAPUP_TARGET"
  CHECK_ROOT="$wt"
  wrapup_log "新工作树已指向 $WRAPUP_TARGET。原工作树仍停在 $HEAD_NOW，未 reset。"
  wrapup_log "请在新工作树使用与现网相同的项目名和卷前缀后，再跑 start-stack.sh。旧树先停应用服务（postgres/redis 可留）。"
  printf '%s\n' "$wt"
fi

# 若目标树已跟踪 0029，核对 blob（新 worktree 时查新树，不查已迁走 0029 的旧树）
if [ -f "$CHECK_ROOT/$WRAPUP_0029_REL" ]; then
  hash="$(git -C "$CHECK_ROOT" hash-object "$CHECK_ROOT/$WRAPUP_0029_REL")"
  [ "$hash" = "$WRAPUP_BLOB_0029" ] || wrapup_die "目标树 0029 hash=$hash，与 $WRAPUP_BLOB_0029 不一致；冻结"
  wrapup_log "目标树已跟踪 0029，且 blob 一致"
fi
