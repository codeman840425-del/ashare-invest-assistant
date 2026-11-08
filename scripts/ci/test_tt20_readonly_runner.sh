#!/bin/sh
# T-O23 针对性自测：只读 git show，以及 PYTHONPATH 可被 sys.executable 子进程继承。不联网、不改共享仓库。
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GIT=$ROOT/deploy/testkit/tt20/git-ro.sh
EXP=$ROOT/deploy/testkit/tt20/export-pythonpath.sh
MAT=$ROOT/deploy/testkit/tt20/materialize-offline-venv.sh
GUARD=$ROOT/deploy/scripts/tb81-licence-tmp-guard.sh
fail=0
bad() { echo "FAIL $*"; fail=1; }
ok() { echo "OK   $*"; }

tmp=$(mktemp -d)
trap 'chmod -R u+w "$tmp" 2>/dev/null || true; rm -rf "$tmp"' EXIT
mkdir -p "$tmp/src/docs/strategies"
printf 'catalog-line\n' > "$tmp/src/docs/strategies/feature_spec.md"
git -C "$tmp/src" init -q
git -C "$tmp/src" config user.email t@example.com
git -C "$tmp/src" config user.name t
git -C "$tmp/src" add docs/strategies/feature_spec.md
git -C "$tmp/src" commit -q -m c
sha=$(git -C "$tmp/src" rev-parse HEAD)
short=$(printf '%s' "$sha" | cut -c1-7)
cp -a "$tmp/src/.git" "$tmp/ro"
chmod -R a-w "$tmp/ro"
before=$(find "$tmp/ro" -printf '%p %m\n' | sort | sha256sum)
priv=$tmp/priv
out=$(TT20_GIT_RO="$tmp/ro" TT20_GIT_PRIV="$priv" TT20_GIT_REAL=/usr/lib/git-core/git \
  TT20_GIT_WORK_TREE="$tmp/src" "$GIT" show "$short:docs/strategies/feature_spec.md")
[ "$out" = "catalog-line" ] && ok "只读对象库 git show 短哈希" || bad "git show 得到 [$out]"
after=$(find "$tmp/ro" -printf '%p %m\n' | sort | sha256sum)
[ "$before" = "$after" ] && ok "共享对象库未被修改" || bad "只读对象库发生变化"
# 可写对象库必须拒绝
mkdir -p "$tmp/rw/objects"
if TT20_GIT_RO="$tmp/rw" TT20_GIT_PRIV="$tmp/priv2" TT20_GIT_REAL=/usr/lib/git-core/git "$GIT" rev-parse HEAD >/dev/null 2>"$tmp/err"; then
  bad "可写对象库未被拒绝"
else
  ok "可写对象库被拒绝"
fi

site=$tmp/site
mkdir -p "$site/alembic"
printf '%s\n' '"""stub"""' > "$site/alembic/__init__.py"
printf '%s\n' 'print("0022 (head)")' > "$site/alembic/__main__.py"
if ! env TT20_SITE_PACKAGES="$site" sh -c '
  . "$1"
  python3 - << PY
import subprocess, sys
r = subprocess.run([sys.executable, "-m", "alembic"], capture_output=True, text=True, check=True)
assert r.stdout.startswith("0022 "), r.stdout
PY
' sh "$EXP"; then
  bad "子进程未能继承 PYTHONPATH 上的 alembic"
else
  ok "sys.executable -m alembic 继承 PYTHONPATH"
fi
if env TT20_SITE_PACKAGES="$tmp/missing" sh -c '. "$1"' sh "$EXP" >/dev/null 2>&1; then
  bad "缺少 site-packages 时应失败"
else
  ok "缺少 site-packages 时失败退出"
fi
if env UV_CACHE_DIR="$tmp/no-cache" TT20_PROJECT="$tmp/src" sh "$MAT" >/dev/null 2>&1; then
  bad "缺少 uv 缓存时应失败"
else
  ok "缺少只读 uv 缓存时物化脚本失败退出"
fi

# tb81 守卫：不碰真实路径。发现残留只停手，不打开、不删除。
secdir=$tmp/runtime
sec=$secdir/mairui-T-B81.tmp
"$GUARD" before "$sec"
[ ! -e "$sec" ] && [ "$(stat -c '%a' "$secdir")" = 700 ] && ok "before 创建 0700 且文件不存在" || bad "before 状态不对"
"$GUARD" after "$sec" >/dev/null
ok "after 在路径空着时通过"
marker=$tmp/marker
printf '%s\n' 'synthetic-marker-not-a-licence' > "$marker"
cp "$marker" "$sec"
chmod 600 "$sec"
sum=$(sha256sum "$sec" | awk '{print $1}')
set +e
err=$("$GUARD" after "$sec" 2>&1)
rc=$?
set -e
[ "$rc" = 4 ] && [ -f "$sec" ] && [ ! -L "$sec" ] && [ "$(sha256sum "$sec" | awk '{print $1}')" = "$sum" ] \
  && ! printf '%s' "$err" | grep -q 'synthetic-marker-not-a-licence' \
  && ok "普通残留被检出且原样保留、不输出内容" || bad "普通残留 rc=$rc"
rm -f "$sec"
target=$tmp/link-target
cp "$marker" "$target"
ln -s "$target" "$sec"
tsum=$(sha256sum "$target" | awk '{print $1}')
set +e
err=$("$GUARD" before "$sec" 2>&1)
rc=$?
set -e
[ "$rc" = 4 ] && [ -L "$sec" ] && [ "$(sha256sum "$target" | awk '{print $1}')" = "$tsum" ] \
  && ! printf '%s' "$err" | grep -q 'synthetic-marker-not-a-licence' \
  && ok "软链目标原样" || bad "软链 rc=$rc"
rm -f "$sec"
mkfifo "$sec"
fsum=$(stat -c '%i %F' "$sec")
set +e
err=$("$GUARD" after "$sec" 2>&1)
rc=$?
set -e
[ "$rc" = 4 ] && [ -p "$sec" ] && [ "$(stat -c '%i %F' "$sec")" = "$fsum" ] \
  && ok "特殊文件未被写入" || bad "fifo rc=$rc"

[ "$fail" = 0 ] && echo "test_tt20_readonly_runner: 全部通过" || echo "test_tt20_readonly_runner: 有失败"
exit "$fail"
