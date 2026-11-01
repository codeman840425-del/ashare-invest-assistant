#!/usr/bin/env bash
# 生成分库角色口令文件（T-O10）：<目录>/db_password_aia_api、db_password_aia_ingest。
# - 目录默认取 compose.sh 解析的 AIA_SECRETS_DIR（仓库外，~/.config/aia/secrets/<卷前缀>）；
# - 已存在的文件从不覆盖（改口令 = 手工删文件后重跑本脚本 + up，db-roles 会 ALTER ROLE 同步）；
# - 权限 600，口令 48 位十六进制（只含 [0-9a-f]，可直接放进连接串，无需转义）；不打印口令。
# 用法：deploy/scripts/db-role-passwords.sh [目录]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dir="${1:-}"
if [ -z "$dir" ]; then dir="$("$ROOT/deploy/scripts/compose.sh" --get AIA_SECRETS_DIR)"; fi
case "$dir" in /*) ;; *) echo "目录必须是绝对路径：$dir" >&2; exit 2 ;; esac
umask 077
mkdir -p "$dir"
for role in aia_api aia_ingest; do
  f="$dir/db_password_$role"
  if [ -e "$f" ]; then
    echo "已存在，不覆盖：$f"
    continue
  fi
  tmp="$(mktemp "$dir/.db_password_$role.XXXXXX")"
  od -An -tx1 -N24 /dev/urandom | tr -d ' \n' > "$tmp"
  chmod 600 "$tmp"
  mv -n "$tmp" "$f"
  [ -e "$tmp" ] && rm -f "$tmp"
  echo "已生成：$f（600）"
done
