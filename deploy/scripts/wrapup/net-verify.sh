#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2016
# shellcheck source=lib.sh
{ set +x; } 2>/dev/null
set -euo pipefail
WRAPUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
# shellcheck disable=SC1091
# shellcheck disable=SC2016
. "$WRAPUP_DIR/lib.sh"

usage() { echo "用法：net-verify.sh [--apply]"; echo "按 deploy/runbooks/networks.md 实测。只打 http://1.1.1.1 或 https://example.com，绝不调麦蕊。"; }
wrapup_parse_common "$@" || { [ $? -eq 99 ] && usage && exit 0; exit 1; }

wrapup_log "模式=$(wrapup_mode)。完整命令与判定标准以 deploy/runbooks/networks.md 为准。"
wrapup_log "覆盖：非 ingest 出网应失败；ingest 出网应成功（只打 1.1.1.1 / example.com，绝不调麦蕊）；服务名 DNS；端口只在 127.0.0.1；enable_ip_masquerade=false 的实际效果；WSL mirrored。"
wrapup_log "Windows：在 WSL 或 Git Bash 执行；宿主监听在 Docker Desktop 下用 PowerShell Get-NetTCPConnection，不要只看 WSL 里的 ss。"

if ! wrapup_need_apply "在已启动的栈上执行 networks.md 第 2–7 步探测"; then
  wrapup_log "dry-run 不发起任何出网探测。请打开 networks.md 按步执行；探测失败或无客户端时看 NO_HTTP_CLIENT / NO_TCP_CLIENT 文本，不要只看 rc=2。"
  exit 0
fi

# 最小可执行子集（函数与判定同手册；详细对照 networks.md）
probe_egress() {
  local svc="$1" url="${2:-http://1.1.1.1}"
  "$COMPOSE" exec -T "$svc" sh -c '
    url="$1"
    if command -v wget >/dev/null 2>&1; then wget -T 5 -q -O - "$url"
    elif command -v curl >/dev/null 2>&1; then curl -sS -m 5 --noproxy "*" -o - "$url"
    elif command -v python3 >/dev/null 2>&1; then python3 -c "import urllib.request,sys; urllib.request.urlopen(sys.argv[1], timeout=5).read()" "$url"
    elif command -v python >/dev/null 2>&1; then python -c "import urllib.request,sys; urllib.request.urlopen(sys.argv[1], timeout=5).read()" "$url"
    else echo NO_HTTP_CLIENT; exit 2
    fi
  ' sh "$url"
}

fail=0
for svc in api worker beat signal-rt nginx; do
  wrapup_log "探测非出网服务 $svc -> http://1.1.1.1（期望失败）"
  if out="$(probe_egress "$svc" "http://1.1.1.1" 2>&1)"; then
    if printf '%s' "$out" | grep -q 'NO_HTTP_CLIENT'; then
      wrapup_log "$svc 输出含 NO_HTTP_CLIENT，改用手册中的 sidecar，不判失败"
    else
      wrapup_log "ERROR: $svc 出网成功，本项不通过（记残余；Docker Desktop 可能无视 masquerade）"
      fail=1
    fi
  else
    if printf '%s' "$out" | grep -q 'NO_HTTP_CLIENT'; then
      wrapup_log "$svc 输出含 NO_HTTP_CLIENT，改用 sidecar"
    else
      wrapup_log "$svc 出网失败，通过"
    fi
  fi
done

wrapup_log "探测 ingest -> http://1.1.1.1（期望成功；禁止改成麦蕊地址）"
if probe_egress ingest "http://1.1.1.1" >/dev/null; then
  wrapup_log "ingest 出网成功，通过"
else
  wrapup_log "ERROR: ingest 出网失败"
  fail=1
fi

wrapup_log "端口：curl 127.0.0.1:${NGINX_HTTP_PORT:-8080}/health/live"
code="$(curl -sS -m 5 --noproxy '*' -o /dev/null -w '%{http_code}' "http://127.0.0.1:${NGINX_HTTP_PORT:-8080}/health/live" || true)"
wrapup_log "health/live HTTP $code"
[ "$code" = "200" ] || { wrapup_log "ERROR: 健康检查不是 200"; fail=1; }

if [ "$fail" -ne 0 ]; then
  wrapup_die "网络实测有失败项，见上面日志与 networks.md 判定（镜像/WSL 步骤请人工补做）"
fi
wrapup_log "脚本能自动跑的探测已通过。请再按手册核：服务名 DNS、局域网 IP 不可达、ss/Get-NetTCPConnection、masquerade、mirrored。"
