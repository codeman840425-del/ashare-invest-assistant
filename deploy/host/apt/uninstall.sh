#!/usr/bin/env bash
# 删除 /etc/apt/apt.conf.d/99aia-proxy（仅当它是本项目安装的文件）。
set -euo pipefail
DST=/etc/apt/apt.conf.d/99aia-proxy
SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo -n"
[ -e "$DST" ] || { echo "未安装：$DST"; exit 0; }
grep -q 'ashare-invest-assistant' "$DST" || { echo "拒绝：$DST 不是本项目管理的文件" >&2; exit 1; }
$SUDO rm -f "$DST"
echo "已删除：$DST"
