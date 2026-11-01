#!/usr/bin/env bash
# 本地运行 secret_scan.py（T-O03）：用 uv 按 PEP 723 头装固定版本的 pyyaml，不依赖本机 Python 里碰巧装了什么。
#   scripts/ci/secret_scan.sh tree | staged | range A..B | history | commit REV | files P...
# 没有 uv 时：python3 -m pip install pyyaml==6.0.3 后 python3 scripts/ci/secret_scan.py …（版本见 secret_scan.py 头部）。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v uv >/dev/null 2>&1 || { echo "secret_scan.sh 需要 uv（https://docs.astral.sh/uv/）" >&2; exit 2; }
exec uv run -q --no-project --script "$HERE/secret_scan.py" "$@"
