#!/bin/sh
# 被 source。把离线 site-packages 放进 PYTHONPATH，子进程（sys.executable -m alembic）能继承。
# 不修改 /hostpy，不写 /cache，不访问网络。
set -eu
sp="${TT20_SITE_PACKAGES:-}"
if [ -z "$sp" ]; then
  venv="${TT20_VENV:-/tmp/tt20-venv}"
  sp=$(find "$venv/lib" -type d -name site-packages 2>/dev/null | head -1 || true)
fi
if [ -z "$sp" ] || [ ! -d "$sp" ]; then
  echo "tt20-python: 没有可继承的 site-packages（先跑 materialize-offline-venv.sh，或设置 TT20_SITE_PACKAGES）" >&2
  exit 2
fi
case ":${PYTHONPATH:-}:" in
  *":$sp:"*) ;;
  *) PYTHONPATH="$sp${PYTHONPATH:+:$PYTHONPATH}" ;;
esac
export PYTHONPATH
export UV_OFFLINE=1
