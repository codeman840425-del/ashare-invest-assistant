#!/bin/sh
# T-O28：无 Docker、无 bridge 的网关静态根冒烟。不读密钥、不访问麦蕊。
# 本机 nginx 用 -p 把默认 html 指到空目录，用来观察“没有 root”时的内部重定向循环。
# 这只说明本机二进制在 -p 下的默认目录，不是镜像编译 prefix 的测量（镜像 prefix 未在此实测）。
# 临时配置只改：监听端口、limits 的 include 路径、上游地址、无特权临时目录，
# 以及把 root 指到本次的临时目录（不写 /usr/share/nginx/html）。
# 仓库 nginx.conf 里的 root 指令必须保持 /usr/share/nginx/html，跑完后核对文件未被替换。
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
CONF_SRC=$ROOT/deploy/nginx/nginx.conf
LIMITS_SRC=$ROOT/deploy/nginx/limits.conf
command -v nginx >/dev/null 2>&1 || { echo "没有 nginx 二进制，不能做无 bridge 冒烟" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "没有 python3" >&2; exit 2; }
work=$(mktemp -d)
prefix=$work/prefix
api_pid=
gw_pid=
cleanup() {
  if [ -n "$gw_pid" ] && kill -0 "$gw_pid" 2>/dev/null; then kill "$gw_pid" 2>/dev/null || true; wait "$gw_pid" 2>/dev/null || true; fi
  if [ -n "$api_pid" ] && kill -0 "$api_pid" 2>/dev/null; then kill "$api_pid" 2>/dev/null || true; wait "$api_pid" 2>/dev/null || true; fi
  rm -rf "$work"
}
trap cleanup EXIT
mkdir -p "$prefix/html" "$work/body" "$work/proxy" "$work/fastcgi" "$work/scgi" "$work/uwsgi" "$work/dist/assets" "$work/saved"
printf '%s\n' '<!doctype html><html lang="zh-CN"><title>probe</title><body><div id="root"></div></body></html>' > "$work/dist/index.html"
printf '%s\n' 'console.log("asset")' > "$work/dist/assets/probe.js"
conf_sum=$(sha256sum "$CONF_SRC" | awk '{print $1}')
html_stamp=$(find /usr/share/nginx/html -printf '%p %T@ %s\n' 2>/dev/null | sort | sha256sum | awk '{print $1}')
awk 'index($0, "#") == 0 && $1 == "root" { print $2; exit }' "$CONF_SRC" | grep -qx '/usr/share/nginx/html;' \
  || { echo "仓库 root 不是 /usr/share/nginx/html" >&2; exit 2; }

python3 - "$work/api.port" << 'PY' &
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
portfile = sys.argv[1]
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/v1/health/live":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()
    def log_message(self, fmt, *args):
        return
httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
with open(portfile, "w", encoding="ascii") as fh:
    fh.write(str(httpd.server_address[1]))
httpd.serve_forever()
PY
api_pid=$!
i=0
while [ ! -s "$work/api.port" ]; do
  i=$((i + 1))
  [ "$i" -lt 30 ] || { echo "假上游没起来" >&2; exit 2; }
  sleep 0.1
done
api_port=$(cat "$work/api.port")

render() {
  sed \
    -e "s#include /etc/nginx/aia-limits.conf;#include $LIMITS_SRC;#" \
    -e "s#listen 80;#listen 127.0.0.1:$2;#" \
    -e "s#resolver 127.0.0.11 valid=10s ipv6=off;#resolver 127.0.0.1 valid=10s ipv6=off;#" \
    -e "s#default \"api:8000\";#default \"127.0.0.1:$api_port\";#" \
    -e "s#access_log /dev/stdout aia;#access_log $work/access.log aia;#" \
    -e "s#root /usr/share/nginx/html;#root $work/dist;#" \
    -e "/include \/etc\/nginx\/mime.types;/a\\
  client_body_temp_path $work/body;\\
  proxy_temp_path $work/proxy;\\
  fastcgi_temp_path $work/fastcgi;\\
  scgi_temp_path $work/scgi;\\
  uwsgi_temp_path $work/uwsgi;" \
    "$1" > "$work/nginx.conf"
}

start_gw() {
  gw_port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
  render "$1" "$gw_port"
  : > "$work/gw.err"
  nginx -p "$prefix" -c "$work/nginx.conf" -g "daemon off; pid $work/nginx.pid; error_log $work/gw.err warn;" >>"$work/gw.out" 2>&1 &
  gw_pid=$!
  i=0
  while ! python3 -c 'import sys,urllib.request; urllib.request.urlopen("http://127.0.0.1:%s/healthz"%sys.argv[1], timeout=1).read()' "$gw_port" >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge 30 ] || ! kill -0 "$gw_pid" 2>/dev/null; then
      echo "网关没起来" >&2
      cat "$work/gw.err" "$work/gw.out" >&2 || true
      exit 2
    fi
    sleep 0.1
  done
}

stop_gw() {
  if [ -n "$gw_pid" ] && kill -0 "$gw_pid" 2>/dev/null; then
    kill "$gw_pid" 2>/dev/null || true
    wait "$gw_pid" 2>/dev/null || true
  fi
  gw_pid=
}

fail=0
sed '/^[[:space:]]*root \/usr\/share\/nginx\/html;/d' "$CONF_SRC" > "$work/noroot.conf"
start_gw "$work/noroot.conf"
code=$(python3 -c 'import sys,urllib.request,urllib.error
try:
    urllib.request.urlopen("http://127.0.0.1:%s/"%sys.argv[1], timeout=2); print(200)
except urllib.error.HTTPError as e:
    print(e.code)' "$gw_port")
if [ "$code" = 500 ] && grep -q 'internal redirection cycle' "$work/gw.err" "$work/gw.out"; then
  echo "OK   缺 root 时 / 为 500 且日志是内部重定向循环"
else
  echo "FAIL 缺 root 时期望 500 循环，实际 HTTP $code"
  fail=1
fi
stop_gw

: > "$work/gw.err"
start_gw "$CONF_SRC"
python3 - "$gw_port" << 'PY' || fail=1
import sys, urllib.request, urllib.error
port = sys.argv[1]
base = "http://127.0.0.1:%s" % port
fail = 0
def fetch(path):
    try:
        with urllib.request.urlopen(base + path, timeout=2) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()
def check(name, cond):
    global fail
    print("OK  " if cond else "FAIL", name)
    if not cond:
        fail = 1
st, hdrs, body = fetch("/")
check("/ 200 且是探针页", st == 200 and b'id="root"' in body and b"frontend not built yet" not in body)
st, hdrs, body = fetch("/login")
check("/login 200 且回退同一页", st == 200 and b'id="root"' in body)
st, hdrs, body = fetch("/research/notes")
check("深链 /research/notes 200", st == 200 and b'id="root"' in body)
st, hdrs, body = fetch("/assets/probe.js")
check("已有 asset 200 且长期缓存", st == 200 and body == b'console.log("asset")\n' and "immutable" in hdrs.get("Cache-Control", ""))
st, hdrs, body = fetch("/assets/no-such-asset.js")
server = hdrs.get("Server", "")
check(
    "缺失 asset 404 短正文且无 nginx 默认页",
    st == 404 and body == b"not found\n" and b"<html" not in body.lower() and b"nginx" not in body.lower() and b'id="root"' not in body,
)
check("Server 头不含版本号（标识本身仍可能是 nginx）: %s" % server, "nginx/" not in server.lower())
st, hdrs, body = fetch("/health/live")
check("/health/live 反代到假上游", st == 200 and body == b'{"status":"ok"}')
st, hdrs, body = fetch("/healthz")
check("/healthz 仍由 nginx 自答", st == 200 and body == b"ok\n")
sys.exit(fail)
PY
stop_gw
after_sum=$(sha256sum "$CONF_SRC" | awk '{print $1}')
after_html=$(find /usr/share/nginx/html -printf '%p %T@ %s\n' 2>/dev/null | sort | sha256sum | awk '{print $1}')
if [ "$after_sum" != "$conf_sum" ]; then
  echo "FAIL 仓库 nginx.conf 被改写"
  fail=1
fi
if [ "$after_html" != "$html_stamp" ]; then
  echo "FAIL /usr/share/nginx/html 被冒烟改动"
  fail=1
else
  echo "OK   仓库 root 仍是 /usr/share/nginx/html，共享目录未改"
fi
[ "$fail" = 0 ] && echo "frontend_root_smoke: 全部通过" || echo "frontend_root_smoke: 有失败"
exit "$fail"
