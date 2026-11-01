#!/usr/bin/env bash
# 安装 dockerd 登录自启钩子：只新增一个文件 /etc/profile.d/zz-aia-dockerd.sh（T-O08）。
#   sudo deploy/host/dockerd-autostart/install.sh        # 或以 box 用户运行（内部用 sudo -n）
# 背景：本机 PID 1 是 tini/pod-daemon（非 systemd），无 cron、无 /etc/rc.local、/etc/init.d 不会被执行，
# 平台不提供可写的开机钩子；登录 shell 都会读 /etc/profile.d/*.sh，是现存机制里最小的挂载点。
# 非登录 shell 不触发，因此 up.sh / compose.sh 仍保留"daemon 不在就自动拉起"的兜底。
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DEST="${AIA_PROFILE_HOOK:-/etc/profile.d/zz-aia-dockerd.sh}"
SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo -n"
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
sed "s#@REPO@#$REPO#g" "$(dirname "${BASH_SOURCE[0]}")/zz-aia-dockerd.sh.in" >"$tmp"
if [ -f "$DEST" ] && cmp -s "$tmp" "$DEST"; then echo "已安装且内容一致：$DEST"; exit 0; fi
$SUDO install -m 0644 -o root -g root "$tmp" "$DEST"
echo "已安装 $DEST（指向 $REPO/deploy/scripts/ensure-dockerd.sh）"
