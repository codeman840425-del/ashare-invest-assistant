#!/usr/bin/env bash
# 包装：优先用后端 venv 的 psycopg（CI 在 uv sync 之后调用）。
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
py="${root}/src/backend/.venv/bin/python"
if [ ! -x "$py" ]; then
  echo "::error title=tt50-template::找不到 src/backend/.venv，须先 uv sync" >&2
  exit 1
fi
exec "$py" "$root/scripts/ci/prepare_tt50_template.py" "$@"
