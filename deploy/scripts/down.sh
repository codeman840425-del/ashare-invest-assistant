#!/usr/bin/env bash
# 停止并移除容器；加 -v 同时删除数据卷：deploy/scripts/down.sh -v
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/compose.sh" down "$@"
