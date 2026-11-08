#!/bin/sh
# 只读 Git 包装（T-O23）。测试固定调用 /usr/bin/git show <rev>:path。
# 共享对象库只读挂在 TT20_GIT_RO（默认 /git-ro）；包装在本容器 /tmp 建私有 GIT_DIR，
# 用 alternates 读对象。不在共享 .git 里写 lock、ref 或新对象。
set -eu
RO="${TT20_GIT_RO:-/git-ro}"
PRIV="${TT20_GIT_PRIV:-/tmp/tt20-gitdir}"
WORK="${TT20_GIT_WORK_TREE:-/code}"
if [ -n "${TT20_GIT_REAL:-}" ]; then
  GIT_REAL=$TT20_GIT_REAL
elif [ -x /usr/lib/git-core/git ]; then
  GIT_REAL=/usr/lib/git-core/git
elif [ -x /usr/libexec/git-core/git ]; then
  GIT_REAL=/usr/libexec/git-core/git
else
  echo "tt20-git: 找不到 git 本体（/usr/lib/git-core/git）" >&2
  exit 127
fi
if [ ! -d "$RO/objects" ]; then
  echo "tt20-git: 只读对象库不存在：$RO/objects" >&2
  exit 2
fi
ro_ok=0
if [ -r /proc/mounts ] && awk -v p="$RO" '$2==p { if ($4 ~ /(^|,)ro(,|$)/) ok=1 } END{ exit !ok }' /proc/mounts; then
  ro_ok=1
fi
if [ "$ro_ok" != 1 ] && { [ -w "$RO" ] || [ -w "$RO/objects" ]; }; then
  echo "tt20-git: $RO 不是只读挂载且对象库可写，拒绝执行（不能改共享 .git）" >&2
  exit 2
fi
if [ ! -f "$PRIV/objects/info/alternates" ]; then
  mkdir -p "$PRIV/refs" "$PRIV/objects/info"
  printf 'ref: refs/heads/main\n' > "$PRIV/HEAD"
  printf '%s\n' "$RO/objects" > "$PRIV/objects/info/alternates"
  chmod 700 "$PRIV"
fi
export GIT_DIR="$PRIV"
export GIT_WORK_TREE="$WORK"
export GIT_OPTIONAL_LOCKS=0
unset GIT_OBJECT_DIRECTORY || true
exec "$GIT_REAL" "$@"
