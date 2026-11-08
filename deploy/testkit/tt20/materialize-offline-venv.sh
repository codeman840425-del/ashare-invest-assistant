#!/bin/sh
# 用只读 uv 缓存在容器可写目录物化 venv。失败即停，不回落到联网安装。
set -eu
cache="${UV_CACHE_DIR:-/cache}"
py="${TT20_PYTHON:-/hostpy/bin/python3.12}"
venv="${TT20_VENV:-/tmp/tt20-venv}"
project="${TT20_PROJECT:-/code/src/backend}"
if [ ! -d "$cache" ]; then
  echo "tt20-python: 只读 uv 缓存不存在：$cache" >&2
  exit 2
fi
if [ -w "$cache" ]; then
  echo "tt20-python: uv 缓存必须只读挂载：$cache" >&2
  exit 2
fi
if [ -w "$project" ]; then
  echo "tt20-python: 源码目录必须只读：$project" >&2
  exit 2
fi
command -v uv >/dev/null 2>&1 || { echo "tt20-python: 缺少 uv，无法从离线缓存物化依赖" >&2; exit 2; }
[ -x "$py" ] || { echo "tt20-python: 缺少解释器 $py" >&2; exit 2; }
export UV_CACHE_DIR="$cache" UV_OFFLINE=1 UV_NO_PROGRESS=1 UV_PROJECT_ENVIRONMENT="$venv"
uv sync --offline --frozen --no-dev --no-install-project --project "$project" --python "$py"
echo "$venv"
