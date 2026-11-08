#!/usr/bin/env bash
# T-O19：用临时网络验证 nginx.conf 的 SPA / 静态资源 / /api 反代。不读密钥、不访问麦蕊。
#   frontend_gateway_smoke.sh config   官方 nginx + 夹具页面（不需要 vite 构建）
#   frontend_gateway_smoke.sh image    已构建的前端镜像（默认 aia-frontend:ci），页面来自镜像内 dist
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mode="${1:-config}"
NGINX_IMG="$(sed -n 's/^FROM nginx:\([^ ]*\).*/nginx:\1/p' "$ROOT/deploy/docker/frontend.Dockerfile" | head -1)"
[ -n "$NGINX_IMG" ] || { echo "找不到 frontend.Dockerfile 里的 nginx FROM" >&2; exit 2; }
command -v docker >/dev/null 2>&1 || { echo "没有 docker，跳过 frontend_gateway_smoke（$mode）" >&2; exit 2; }
id="o19web-$$"; net="$id-net"; work="$(mktemp -d)"; fail=0
cleanup() { docker rm -f "$id-gw" "$id-api" >/dev/null 2>&1 || true; docker network rm "$net" >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT
cat > "$work/stub.conf" << 'CONF'
events {}
http { server { listen 8000;
  location = /api/v1/me { default_type application/json; add_header X-Stub 1 always; return 401 '{"error":{"code":"AUTH_REQUIRED"}}'; }
  location / { default_type application/json; add_header X-Stub 1 always; return 200 '{"ok":true}'; }
} }
CONF
if [ "$mode" = config ]; then
  img="$NGINX_IMG"
  mkdir -p "$work/html/assets"
  printf '%s\n' '<!doctype html><html lang="zh-CN"><head><title>A股投资研究与决策助手</title></head><body><div id="root"></div></body></html>' > "$work/html/index.html"
  printf '%s\n' 'console.log("asset")' > "$work/html/assets/probe.js"
  html_mount=(-v "$work/html:/usr/share/nginx/html:ro")
elif [ "$mode" = image ]; then
  img="${AIA_FRONTEND_IMAGE:-aia-frontend:ci}"
  html_mount=()
else
  echo "用法：$0 [config|image]" >&2; exit 2
fi
docker network create "$net" >/dev/null
docker run -d --name "$id-api" --network "$net" --network-alias api -v "$work/stub.conf:/etc/nginx/nginx.conf:ro" "$NGINX_IMG" >/dev/null
docker run -d --name "$id-gw" --network "$net" --dns 127.0.0.1 -p 127.0.0.1::80 \
  -v "$ROOT/deploy/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
  -v "$ROOT/deploy/nginx/limits.conf:/etc/nginx/aia-limits.conf:ro" \
  "${html_mount[@]}" "$img" >/dev/null
port=""
for _ in $(seq 1 30); do
  port="$(docker port "$id-gw" 80/tcp 2>/dev/null | head -1 | sed 's/.*://')"
  [ -n "$port" ] && curl -fsS -o /dev/null "http://127.0.0.1:$port/healthz" && break
  sleep 0.3
done
[ -n "$port" ] || { docker logs "$id-gw" | tail -20; echo "网关没起来" >&2; exit 2; }
ok() { echo "OK   $*"; }
bad() { echo "FAIL $*"; fail=1; }
body() { curl -sS -D "$work/h" -o "$work/b" "$1" || true; }
body "http://127.0.0.1:$port/"
grep -q 'id="root"' "$work/b" && ! grep -q 'frontend not built yet' "$work/b" && ok "/ 是前端页面" || bad "/ 不是前端页面：$(head -c 120 "$work/b")"
body "http://127.0.0.1:$port/research/notes"
grep -q '^HTTP/1.1 200' "$work/h" && grep -q 'id="root"' "$work/b" && ok "深链 /research/notes 回退 index.html" || bad "深链：$(head -1 "$work/h")"
code="$(curl -sS -D "$work/mh" -o "$work/miss" -w '%{http_code}' "http://127.0.0.1:$port/assets/no-such-asset.js")"
miss_cc="$(tr -d '\r' < "$work/mh" | tr 'A-Z' 'a-z')"
if [ "$code" = 404 ] && ! grep -qi 'id="root"\|<html\|nginx' "$work/miss" \
  && grep -q 'cache-control: no-store' <<<"$miss_cc" \
  && ! grep -q 'immutable\|31536000' <<<"$miss_cc"; then
  ok "缺失的 /assets 是 404，正文无默认页，且不长期缓存"
else
  bad "缺失资源 HTTP $code 缓存：$miss_cc 正文：$(head -c 120 "$work/miss")"
fi
if [ "$mode" = config ]; then
  cc="$(curl -sS -D - -o /dev/null "http://127.0.0.1:$port/assets/probe.js" | tr -d '\r' | tr 'A-Z' 'a-z')"
  grep -q 'cache-control: public, max-age=31536000, immutable' <<<"$cc" && ok "哈希资源长期缓存" || bad "Cache-Control：$cc"
else
  asset="$(grep -oE '/assets/[^" ]+\.js' "$work/b" | head -1 || true)"
  [ -n "$asset" ] && curl -fsS -o /dev/null "http://127.0.0.1:$port$asset" && ok "dist 资源 $asset" || bad "dist 里没有可取的 /assets js"
fi
body "http://127.0.0.1:$port/api/v1/me"
grep -q '^HTTP/1.1 401' "$work/h" && grep -q 'AUTH_REQUIRED' "$work/b" && ! grep -q 'id="root"' "$work/b" \
  && grep -qi '^X-Stub: 1' "$work/h" && ok "未登录 /api/v1/me 是后端 401，不是 SPA" || bad "/api/v1/me：$(head -1 "$work/h") $(head -c 80 "$work/b")"
body "http://127.0.0.1:$port/api/v1/health/live"
grep -q '^HTTP/1.1 200' "$work/h" && grep -q '"ok":true' "$work/b" && ok "/api 反代到上游" || bad "/api 反代：$(head -1 "$work/h")"
curl -fsS "http://127.0.0.1:$port/healthz" | grep -q '^ok$' && ok "/healthz 仍由 nginx 自答" || bad "/healthz"
[ "$fail" = 0 ] && echo "frontend_gateway_smoke ($mode): 全部通过" || echo "frontend_gateway_smoke ($mode): 有失败"
exit "$fail"
