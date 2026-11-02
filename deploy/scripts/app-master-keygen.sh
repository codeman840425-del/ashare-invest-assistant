#!/usr/bin/env bash
# 生成 APP_MASTER_KEY 密钥文件（T-O11）：<目录>/app_master_key。
# - 目录默认取 compose.sh 解析的 AIA_SECRETS_DIR（仓库外，~/.config/aia/secrets/<卷前缀>）；
# - 已存在则从不覆盖、直接退出 0 并说明（换主密钥会让既有 HMAC/加密数据失效，必须人工决定）；
# - 内容：64 位十六进制（32 字节随机，满足后端“至少 32 个字符”）；权限 600；
#   属主改成容器用户（AIA_APP_UID，默认 10001，api/worker 以它运行）；需要 root 或 sudo -n，否则告警。
# - 不打印密钥；不写 .env；compose 以 secret app_master_key 挂给 api/worker，
#   由 deploy/docker/secret-env.sh 在容器进程内转成 APP_MASTER_KEY（docker inspect 看不到）。
# 用法：deploy/scripts/app-master-keygen.sh [目录]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dir="${1:-}"
if [ -z "$dir" ]; then dir="$("$ROOT/deploy/scripts/compose.sh" --get AIA_SECRETS_DIR)"; fi
case "$dir" in /*) ;; *) echo "目录必须是绝对路径：$dir" >&2; exit 2 ;; esac
case "$dir/" in "$ROOT"/*) echo "密钥目录不能在仓库里（$dir）" >&2; exit 2 ;; esac
app_uid="${AIA_APP_UID:-10001}"
case "$app_uid" in [0-9]*) ;; *) echo "AIA_APP_UID 必须是数字：$app_uid" >&2; exit 2 ;; esac
f="$dir/app_master_key"
if [ -e "$f" ]; then
  echo "已存在，不覆盖：$f"
  exit 0
fi
umask 077
mkdir -p "$dir"
tmp="$(mktemp "$dir/.app_master_key.XXXXXX")"
trap '[ -e "$tmp" ] && { rm -f "$tmp" 2>/dev/null || sudo -n rm -f "$tmp"; }' EXIT
od -An -tx1 -N32 /dev/urandom | tr -d ' \n' > "$tmp"
chmod 600 "$tmp"
if [ "$(stat -c %u "$tmp")" != "$app_uid" ]; then
  if [ "$(id -u)" = 0 ]; then chown "$app_uid:$app_uid" "$tmp"
  elif sudo -n true 2>/dev/null; then sudo -n chown "$app_uid:$app_uid" "$tmp"
  else echo "警告：无法把属主改成 $app_uid（无 sudo），api/worker 读不到它；请让管理员执行 chown $app_uid:$app_uid $f" >&2
  fi
fi
mv -n "$tmp" "$f"
echo "已生成：$f（600，属主 $(stat -c %u "$f")）"
