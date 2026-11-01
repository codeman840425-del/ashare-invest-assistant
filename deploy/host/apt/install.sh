#!/usr/bin/env bash
# 安装 /etc/apt/apt.conf.d/99aia-proxy（独立新增文件；不触碰已有 sources/配置）。幂等。
# 回滚：sudo deploy/host/apt/uninstall.sh
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/99aia-proxy"
DST=/etc/apt/apt.conf.d/99aia-proxy
SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo -n"
if [ -e "$DST" ] && ! grep -q 'ashare-invest-assistant' "$DST"; then
  echo "拒绝：$DST 已存在且不是本项目管理的文件" >&2; exit 1
fi
if cmp -s "$SRC" "$DST"; then echo "已是最新：$DST"; exit 0; fi
$SUDO install -m 0644 -o root -g root "$SRC" "$DST"
echo "已安装：$DST"
echo "验证：sudo apt-get update && sudo apt-get install --download-only -y <小包>"
