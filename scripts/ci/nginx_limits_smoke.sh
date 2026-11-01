#!/usr/bin/env bash
# nginx 限流运行时冒烟（T-O10）：临时网络 + 桩上游（别名 api:8000，恒 200）+ 仓库 nginx.conf 与指定 limits 文件，
# 正例：登录/注册、导入（写）、全局 /api/ 超限 → 429 RATE_LIMITED 信封 + Retry-After = details.retry_after_s；
# 反例：GET /api/v1/imports（列表）不进导入桶；dev 限流文件（limit_req_dry_run）下连发不触发 429、只记日志；超大请求体仍是 413（不被 429 盖住）。
# 不连真实后端、不读任何密钥；容器/网络结束即删。用法：scripts/ci/nginx_limits_smoke.sh [prod|dev|both]（默认 both）
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMG="$(sed -n 's/^ *image: *\(nginx:[^ ]*\).*/\1/p' "$ROOT/deploy/compose/docker-compose.yml" | head -1)"
[ -n "$IMG" ] || { echo "找不到 nginx 镜像" >&2; exit 2; }
id="o10smoke-$$"; net="$id-net"; work="$(mktemp -d)"; fail=0
cleanup() { docker rm -f "$id-gw" "$id-api" >/dev/null 2>&1 || true; docker network rm "$net" >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT
cat > "$work/stub.conf" <<'CONF'
events {}
http { server { listen 8000; client_max_body_size 100m;
  location / { default_type application/json; return 200 '{"ok":true}'; } } }
CONF
docker network create "$net" >/dev/null
docker run -d --name "$id-api" --network "$net" --network-alias api -v "$work/stub.conf:/etc/nginx/nginx.conf:ro" "$IMG" >/dev/null

ok()  { echo "OK   $*"; }
bad() { echo "FAIL $*"; fail=1; }
start_gw() {  # $1 = limits 文件
  docker rm -f "$id-gw" >/dev/null 2>&1 || true
  docker run -d --name "$id-gw" --network "$net" -p 127.0.0.1::80 \
    -v "$ROOT/deploy/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" -v "$1:/etc/nginx/aia-limits.conf:ro" "$IMG" >/dev/null
  for _ in $(seq 1 30); do
    port="$(docker port "$id-gw" 80/tcp 2>/dev/null | head -1 | sed 's/.*://')"
    [ -n "$port" ] && curl -fsS -o /dev/null "http://127.0.0.1:$port/healthz" 2>/dev/null && return 0
    sleep 0.5
  done
  docker logs "$id-gw" | tail -5; echo "网关没起来" >&2; exit 2
}
# n 次请求，输出各状态码计数（一个 curl 进程顺序发，速度足够触发 20r/s 的全局桶）
burst() {  # $1 方法 $2 路径 $3 次数
  local cfg="$work/curl.cfg"; : > "$cfg"
  for _ in $(seq 1 "$3"); do printf 'url = "http://127.0.0.1:%s%s"\noutput = "/dev/null"\nwrite-out = "%%{http_code}\\n"\n' "$port" "$2" >> "$cfg"; done
  curl -s -X "$1" -K "$cfg" | sort | uniq -c | awk '{printf "%s×%s ", $2, $1}'
}
check_429() {  # $1 方法 $2 路径 $3 期望 retry [$4 = 全局桶：不是 429 就先连发 150 次再试，最多 5 次，避免令牌回补造成的偶发]
  local h="$work/h" b t
  for t in 1 2 3 4 5; do
    b="$(curl -s -X "$1" -D "$h" "http://127.0.0.1:$port$2")"
    grep -q '^HTTP/1.1 429' "$h" && break
    [ -n "${4:-}" ] || break
    burst "$1" "$2" 150 >/dev/null
  done
  grep -q '^HTTP/1.1 429' "$h" || { bad "$1 $2 预期 429，实际 $(head -1 "$h")"; return; }
  grep -qi "^Retry-After: $3"$'\r'"\?$" "$h" || bad "$1 $2 Retry-After 应为 $3：$(grep -i retry-after "$h" || echo 无)"
  grep -qi '^Content-Type: application/json' "$h" || bad "$1 $2 429 不是 JSON"
  grep -qi '^X-Request-Id: .' "$h" || bad "$1 $2 429 缺 X-Request-Id"
  python3 - "$b" "$3" <<'PY' && ok "$1 $2 → 429 RATE_LIMITED，Retry-After = retry_after_s = $3" || bad "$1 $2 信封不对：$b"
import json, sys
e = json.loads(sys.argv[1])["error"]
assert e["code"] == "RATE_LIMITED" and e["details"]["retry_after_s"] == int(sys.argv[2]) and e["request_id"] and e["message"], e
PY
}

run_prod() {
  echo "== prod（deploy/nginx/limits.conf）"
  start_gw "$ROOT/deploy/nginx/limits.conf"
  r="$(burst POST /api/v1/auth/login 11)"; [[ "$r" == "200×11 " ]] && ok "登录 11 次（burst 10 + 1）全部放行" || bad "登录前 11 次应全放行：$r"
  check_429 POST /api/v1/auth/login 3
  r="$(burst POST /api/v1/auth/register 3)"; [[ "$r" == "429×3 " ]] && ok "注册与登录同桶（按 IP），已超限 → 429" || bad "注册应同样 429：$r"
  r="$(burst GET /api/v1/imports 40)"; [[ "$r" == "200×40 " ]] && ok "反例：GET /api/v1/imports 40 次不进导入桶" || bad "GET 导入列表被限：$r"
  r="$(burst POST /api/v1/imports 6)"; [[ "$r" == "200×6 " ]] && ok "导入写 6 次（burst 5 + 1）放行" || bad "导入前 6 次应放行：$r"
  check_429 POST /api/v1/imports 10
  sleep 6   # 让全局桶回满（20r/s × 6s ≥ burst 100）
  r="$(burst GET /api/v1/meta/enums 400)"
  [[ "$r" == *"429×"* && "$r" == *"200×"* ]] && ok "全局 /api/ 400 次连发：$r" || bad "全局 /api/ 应部分 429：$r"
  check_429 GET /api/v1/meta/enums 1 refill
  r="$(burst GET /healthz 50)"; [[ "$r" == "200×50 " ]] && ok "反例：/healthz 不限流" || bad "/healthz 被限：$r"
  sleep 6
  head -c 30000000 /dev/zero > "$work/big"
  code="$(curl -s -o /dev/null -w '%{http_code}' -X POST --data-binary @"$work/big" "http://127.0.0.1:$port/api/v1/imports")"
  [ "$code" = 413 ] && ok "超大请求体 → 413（未被 429 盖住）" || bad "超大请求体应 413，实际 $code"
}
run_dev() {
  echo "== dev（deploy/nginx/limits.dev.conf）"
  start_gw "$ROOT/deploy/nginx/limits.dev.conf"
  r="$(burst POST /api/v1/auth/login 60)"; [[ "$r" == "200×60 " ]] && ok "反例：dev 下登录 60 次不触发 429" || bad "dev 登录被限：$r"
  r="$(burst GET /api/v1/meta/enums 600)"; [[ "$r" == "200×600 " ]] && ok "反例：dev 下 /api/ 600 次连发不触发 429" || bad "dev 全局被限：$r"
  docker logs "$id-gw" > "$work/gw.log" 2>&1 || true   # 先落文件再 grep：管道里 grep -q 提前退出会让 docker logs 吃 SIGPIPE，pipefail 下误判
  grep -q 'limiting requests, dry run' "$work/gw.log" && ok "dev 限流 zone 生效（dry run 只记日志）" || bad "dev 日志里没有 dry run 记录"
}
case "${1:-both}" in
  prod) run_prod ;; dev) run_dev ;; both) run_prod; run_dev ;;
  *) echo "用法：$0 [prod|dev|both]" >&2; exit 2 ;;
esac
[ "$fail" = 0 ] && echo "nginx_limits_smoke: 全部通过" || echo "nginx_limits_smoke: 有失败"
exit "$fail"
