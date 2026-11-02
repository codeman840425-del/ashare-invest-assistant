#!/usr/bin/env bash
# 生成分库角色口令文件（T-O10 / T-O11）：<目录>/db_password_aia_api、db_password_aia_ingest、db_password_aia_maint。
# - 目录默认取 compose.sh 解析的 AIA_SECRETS_DIR（仓库外，~/.config/aia/secrets/<卷前缀>）；
# - 已存在的文件从不覆盖（改口令 = 手工删文件后重跑本脚本 + up，db-roles 会 ALTER ROLE 同步）；
# - 权限 600，口令 48 位十六进制（只含 [0-9a-f]，可直接放进连接串，无需转义）；不打印口令。
# - aia_maint（删除用户数据 CLI 专用，T-O11）：设置 AIA_MAINT_PW_OWNER=<uid> 时（compose.sh 传容器用户 10001），
#   新生成的 db_password_aia_maint 属主改成该 uid，供以该用户运行的 maint-cli 容器读取（db-roles 以 root 读）；
#   不设置时（CI / 手工）保持当前用户。api / ingest 的口令文件属主不变（compose.sh 在宿主上读它们做插值）。
# 用法：deploy/scripts/db-role-passwords.sh [目录]
# 评审 8cf9771 m3：先关掉继承来的 xtrace（bash -x / SHELLOPTS=xtrace），免得密钥或口令值被打到 stderr。
{ set +x; } 2>/dev/null
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dir="${1:-}"
if [ -z "$dir" ]; then dir="$("$ROOT/deploy/scripts/compose.sh" --get AIA_SECRETS_DIR)"; fi
case "$dir" in /*) ;; *) echo "目录必须是绝对路径：$dir" >&2; exit 2 ;; esac
maint_owner="${AIA_MAINT_PW_OWNER:-}"
case "$maint_owner" in ''|[0-9]*) ;; *) echo "AIA_MAINT_PW_OWNER 必须是数字 uid：$maint_owner" >&2; exit 2 ;; esac
umask 077
mkdir -p "$dir"
for role in aia_api aia_ingest aia_maint; do
  f="$dir/db_password_$role"
  if [ -e "$f" ]; then
    echo "已存在，不覆盖：$f"
    continue
  fi
  tmp="$(mktemp "$dir/.db_password_$role.XXXXXX")"
  od -An -tx1 -N24 /dev/urandom | tr -d ' \n' > "$tmp"
  chmod 600 "$tmp"
  if [ "$role" = aia_maint ] && [ -n "$maint_owner" ] && [ "$(stat -c %u "$tmp")" != "$maint_owner" ]; then
    if [ "$(id -u)" = 0 ]; then chown "$maint_owner:$maint_owner" "$tmp"
    elif sudo -n true 2>/dev/null; then sudo -n chown "$maint_owner:$maint_owner" "$tmp"
    else echo "警告：无法把 $f 属主改成 $maint_owner（无 sudo），maint-cli 读不到它；请让管理员执行 chown $maint_owner:$maint_owner $f" >&2
    fi
  fi
  mv -n "$tmp" "$f" 2>/dev/null || sudo -n mv -n "$tmp" "$f"
  [ -e "$tmp" ] && { rm -f "$tmp" 2>/dev/null || sudo -n rm -f "$tmp"; }
  echo "已生成：$f（600）"
done
