"""dry-run 离线自检：本地 http.server 伪造麦蕊响应 + 禁止一切非回环网络访问。

只在 run_all.py --dry-run 中使用；不访问麦蕊、不读取/发送真实证书、不触碰 results/STOP。
"""
from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import common as c

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


# --------------------------------------------------------------------------- 出网拦截
class NetGuard:
    """替换 socket.getaddrinfo / socket.socket.connect：非回环目标一律拒绝并记录。"""

    def __init__(self):
        self.blocked: list = []
        self._orig = None

    def install(self):
        orig_gai, orig_connect, orig_connect_ex = socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex
        self._orig = (orig_gai, orig_connect, orig_connect_ex)
        guard = self

        def _host_of(addr):
            return addr[0] if isinstance(addr, tuple) else str(addr)

        def gai(host, *a, **k):
            h = host.decode() if isinstance(host, bytes) else host
            if h not in LOOPBACK:
                guard.blocked.append(f"dns:{h}")
                raise OSError(f"dry-run 禁止解析非回环地址：{h}")
            return orig_gai(host, *a, **k)

        def connect(self_sock, addr):
            if self_sock.family in (socket.AF_INET, socket.AF_INET6) and _host_of(addr) not in LOOPBACK:
                guard.blocked.append(f"connect:{_host_of(addr)}")
                raise OSError("dry-run 禁止连接非回环地址")
            return orig_connect(self_sock, addr)

        def connect_ex(self_sock, addr):
            if self_sock.family in (socket.AF_INET, socket.AF_INET6) and _host_of(addr) not in LOOPBACK:
                guard.blocked.append(f"connect_ex:{_host_of(addr)}")
                return 111
            return orig_connect_ex(self_sock, addr)

        socket.getaddrinfo = gai
        socket.socket.connect = connect
        socket.socket.connect_ex = connect_ex
        return self

    def uninstall(self):
        if self._orig:
            socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex = self._orig
            self._orig = None


# --------------------------------------------------------------------------- 伪造服务端
class MockState:
    def __init__(self, label: str):
        self.label = label
        self.lock = threading.Lock()
        self.connections = 0          # 每次 TCP accept 后 handler.setup() 计 1
        self.client_ports: set = set()
        self.requests = 0
        self.active = 0
        self.max_active = 0
        self.bad_licence = 0          # 路径里出现非假证书的次数（不记录具体值）
        self.saw_real_licence = False
        self.fail_after: int | None = None   # 第 N 个请求起返回 429/103，用于熔断测试


def _rows(n, **extra):
    return [{"t": f"2026-10-{(i % 28) + 1:02d} 15:00:00", "o": 10.0, "h": 10.5, "l": 9.8, "c": 10.2,
             "v": 1000 + i, **extra} for i in range(n)]


def route(state: MockState, method: str, raw_path: str, body: bytes):
    """返回 (status, content_type, bytes)。"""
    import os
    parts = urlsplit(raw_path)
    path, q = parts.path, parse_qs(parts.query)
    segs = [s for s in path.split("/") if s]
    lic_seg = segs[-1] if segs else ""
    real = os.environ.get("MAIRUI_LICENCE", "")
    if real and real in raw_path:
        state.saw_real_licence = True
    if state.fail_after is not None and state.requests >= state.fail_after:
        return 429, "text/plain; charset=utf-8", "103:同一Licence证书在60秒内最多允许2个不同IP访问".encode("utf-8")
    if lic_seg != c.DRY_RUN_LICENCE:
        state.bad_licence += 1
        return 200, "application/json", json.dumps({"error": "licence 无效（mock）"}, ensure_ascii=False).encode()
    js = lambda o, st=200: (st, "application/json; charset=utf-8", json.dumps(o, ensure_ascii=False).encode("utf-8"))
    if "notexist" in segs:
        return js({"detail": "Not Found"}, 404)
    if "/5/f/" in path:
        return 503, "text/plain", b"redis history unavailable (cold fallback disabled): redis history miss"
    if q.get("lt") == ["10"]:
        return js({"detail": {"msg": "lt 最大为 5（mock）"}}, 422)
    if "999999" in path:
        return js({"error": "股票代码不存在（mock）"})
    if "ssjy_more" in segs:
        codes = (q.get("stock_codes") or [""])[0].split(",")
        if len(codes) > 20:
            return js({"error": "最多 20 只（mock）"})
        return js([{"dm": cd, "p": 10.0, "t": "2026-10-30 15:00:00"} for cd in codes])
    if "all" in segs[:-1] and not path.startswith("/factor/"):
        return js([{"dm": f"{i:06d}", "p": 10.0, "t": "2026-10-30 15:00:00"} for i in range(1500)])
    if method == "POST":
        try:
            json.loads(body or b"{}")
        except ValueError:
            return js({"detail": "bad json"}, 400)
        return js({"code": 200, "data": {"list": [{"code": "600519", "pe_ttm": 25.1, "roe_ttm": None}]}})
    if path.startswith("/factor/"):
        return js({"code": "600519", "trade_date": "2026-10-30", "pe_ttm": 25.1, "pb": None, "roe_ttm": 30.2})
    if "real" in segs and "time" in segs:
        return js({"p": 10.2, "t": "2026-10-30 15:00:00", "v": 12345})
    return js(_rows(5))


def make_handler(state: MockState):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"   # 支持 keep-alive，长连接复用

        def setup(self):
            super().setup()
            with state.lock:
                state.connections += 1
                state.client_ports.add(self.client_address[1])

        def log_message(self, *a):   # 不打印访问日志（路径含假证书）
            pass

        def _handle(self, method):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else b""
            with state.lock:
                state.active += 1
                state.max_active = max(state.max_active, state.active)
            try:
                time.sleep(0.003)      # 拉长处理窗口，若客户端并发则 max_active 会 >1
                with state.lock:
                    status, ctype, data = route(state, method, self.path, body)
                    state.requests += 1
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            finally:
                with state.lock:
                    state.active -= 1

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

    return Handler


def start_server(label: str):
    state = MockState(label)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    srv.daemon_threads = True
    th = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    th.start()
    return srv, state, f"http://127.0.0.1:{srv.server_address[1]}"


# --------------------------------------------------------------------------- 模拟 myip.ipip.net
class EchoState:
    def __init__(self):
        self.lock = threading.Lock()
        self.connections = 0
        self.requests = 0
        self.rotate = False      # True 时每次返回不同 IP，用于测试“出口不固定 → 拒绝运行”


def start_ip_echo():
    st = EchoState()

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            with st.lock:
                st.connections += 1

        def log_message(self, *a):
            pass

        def do_GET(self):
            with st.lock:
                st.requests += 1
                last = 7 + (st.requests if st.rotate else 0)
            body = f"当前 IP：203.0.113.{last}  来自于：中国 测试 电信\n".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
    return srv, st, f"http://127.0.0.1:{srv.server_address[1]}/"


# --------------------------------------------------------------------------- 假代理：只记录收到的请求数
class ProxyState:
    def __init__(self):
        self.lock = threading.Lock()
        self.connections = 0
        self.requests = 0


def start_proxy_recorder():
    st = ProxyState()

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            with st.lock:
                st.connections += 1

        def log_message(self, *a):   # 不记录请求行（含假证书）
            pass

        def _reply(self):
            with st.lock:
                st.requests += 1
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                self.rfile.read(n)
            body = json.dumps({"via": "proxy-recorder"}).encode()
            self.send_response(200 if self.command != "CONNECT" else 502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = do_CONNECT = _reply

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
    return srv, st, f"http://127.0.0.1:{srv.server_address[1]}"
