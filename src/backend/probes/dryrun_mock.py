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


# --------------------------------------------------------------------------- p11_gaps 用的伪造响应
def _bj_now_str(minus_s: float = 0.0) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone(timedelta(hours=8))) - timedelta(seconds=minus_s)).strftime("%Y-%m-%d %H:%M:%S")


# 量纲按 T003 实测样例伪造：real/time v=手、cje=元；ssjy v=万手；日线 v=手、a=元
_MOCK_FIN = [  # (jzrq, plrq)；含 1 个同期两行（修订）与早期 plrq 空值
    ("2001-06-30", None), ("2001-12-31", "2002-03-28"), ("2024-12-31", "2025-04-03"),
    ("2025-03-31", "2025-04-29"), ("2025-06-30", "2025-08-13"), ("2025-09-30", "2025-10-25"),
    ("2025-12-31", "2026-04-02"), ("2026-03-31", "2026-04-28"), ("2026-06-30", "2026-08-12"),
    ("2026-06-30", "2026-09-01"), ("2026-09-30", "2026-10-28")]
_MOCK_FACTORS = ["pe_ttm", "pb", "roe_ttm", "profit_yoy", "momentum_20d", "north_5d_net", "north_20d_net",
                 "north_holding_ratio", "attention_score", "intraday_vol_20d", "mock_extra_factor"]


# --------------------------------------------------------------------------- p13_fin_pit 用的伪造响应
# 量纲按真实样例：元、股；jzrq/plrq/jlr 与 p11 GAP3 依赖的 _MOCK_FIN 完全一致（只追加字段）
_BANKS, _INSURERS = ("000001.SZ", "600000.SH"), ("601318.SH",)


def _scale(code: str) -> float:
    return 5.8e12 if code in _BANKS else 1.3e13 if code in _INSURERS else 1.5e10 if code.startswith("689") else 3e11


def _fin_rows(table: str, code: str) -> list:
    fin = list(_MOCK_FIN)
    if code == "600525.SH":   # 差错更正样例：2024Q3 原版 + 2025-04-29 更正版
        fin += [("2024-09-30", "2024-10-30"), ("2024-09-30", "2025-04-29")]
    out = []
    for i, (j, p) in enumerate(fin):
        r = {"jzrq": j, "plrq": p, "jlr": 100.0 + i}
        k = {"03-31": 1, "06-30": 2, "09-30": 3, "12-31": 4}[j[5:]]
        bump = 1.01 if (p or "") in ("2026-09-01", "2025-04-29") else 1.0   # 修订版数值不同
        sc = _scale(code)
        if table == "cashflow":
            lr = round(sc * 0.01 * k * bump, 2)
            lc = round(lr * 0.6, 2)
            xj = round(lr - lc, 2)
            if j < "2002" or code in _BANKS:      # 早期/银行样例：净额只在 je 字段
                r.update({"jyhdxjlrxj": lr, "jyhdxjlcxj": lc, "jyhdcsdxjlxj": "-", "jyhdcsdxjlje": xj})
            else:
                r.update({"jyhdxjlrxj": lr, "jyhdxjlcxj": lc, "jyhdcsdxjlxj": xj, "jyhdcsdxjlje": "-"})
        elif table == "balance":
            za = round(sc * (1 + i * 0.01) * bump, 2)
            eq = round(za * 0.085, 2) if (code in _BANKS or code in _INSURERS) else round(za * 0.6, 2)
            if code == "300750.SZ" and j == "2001-12-31":
                eq = -1000000.0
            fz = round(za - eq - 1000.0, 2)
            r.update({"zczj": za, "fzhj": fz, "gsmgdqsyhj": eq, "syzqyhj": round(eq + 1000.0, 2),
                      "fzhgdqyzj": za})
        else:
            r.update({"yysr": round(sc * 0.02 * k * bump, 2)})
        out.append(r)
    return out


_MOCK_CAPITAL = {   # (bdrq, plrq, zgb, ysltag, xsltgf)
    "600519.SH": [("20110630", "2011-06-30", 943800000, 943800000, 0),
                  ("20110701", "2011-07-01", 1038180000, 1038180000, 0),
                  ("20250630", "2025-08-13", 1_256_197_800, 1_256_197_800, 0),   # V5i：与同期报告首次披露对齐
                  ("20260630", "2026-06-30", 1250081601, 1250081601, 0),
                  ("20260930", "2026-09-30", 1250081601, 1250081601, 0)],
    "000001.SZ": [("20160331", "2016-03-31", 14_308_676_139, 11804054528, 2504621611),
                  ("20160616", "2016-08-12", 17_170_411_366, 14_164_865_433, 3005545933),
                  ("20260930", "2026-09-30", 19_405_918_198, 19_405_546_950, 371248)],
    "601318.SH": [("20250630", "2025-06-30", 18_210_234_607, 10762657695, 0),
                  ("20250903", "2025-09-03", 18_107_641_995, 10660065083, 0),
                  ("20260930", "2026-09-30", 18_107_641_995, 10660065083, 0)],
    "000550.SZ": [("20251231", "2026-03-28", 863214000, 518463160, 750840),   # V5g：巨潮 2025 年报期末
                  ("20260331", "2026-03-31", 863214000, 518463160, 750840)],
    # V5j：mock 里 zgb 按 CDR 份数（九号 2025 年报：2024-12-31 717,120,523 份、2025-12-17 后 720,335,578 份）
    "689009.SH": [("20201029", "2020-10-29", 704_091_670, 704_091_670, 0),
                  ("20241231", "2025-04-01", 717_120_523, 717_120_523, 0),
                  ("20251217", "2025-12-17", 720_335_578, 720_335_578, 0)],
}


def _capital_rows(code: str) -> list:
    rows = _MOCK_CAPITAL.get(code, [("20260930", "2026-09-30", 1000000000, 1000000000, 0)])
    return [{"bdrq": b, "plrq": p, "xsltgf": x, "ysltag": a, "zgb": z} for b, p, z, a, x in reversed(rows)]


def _jnfh_rows(code6: str) -> list:
    blank = {"give": "0", "change": "0", "hdate": "--"}
    if code6 == "600519":
        return [{"sdate": "2026-06-22", "rdate": "2025-12-31", **blank, "send": "280.2423", "line": "实施",
                 "cdate": "2026-06-26", "edate": "2026-06-25"},
                {"sdate": "2011-06-26", "rdate": "2010-12-31", "give": "1", "change": "0", "send": "23",
                 "line": "实施", "cdate": "2011-07-01", "edate": "2011-06-30", "hdate": "2011-07-04"}]
    if code6 == "000001":
        return [{"sdate": "2016-06-08", "rdate": "2015-12-31", "give": "0", "change": "2", "send": "1.53",
                 "line": "实施", "cdate": "2016-06-16", "edate": "2016-06-15", "hdate": "2016-06-16"}]
    return []


_MOCK_SW = [("申万行业", "swhy", 0, "", 0), ("申万行业-银行", "sw_yx", 1, "swhy", 0),
            ("申万行业-非银金融", "sw_fy", 1, "swhy", 0), ("申万行业-食品饮料", "sw_sp", 1, "swhy", 1),
            ("申万二级-股份制银行Ⅱ", "sw2_480300", 2, "sw_yx", 1), ("申万二级-保险Ⅱ", "sw2_490200", 2, "sw_fy", 1)]


def _hszg_route(segs: list):
    if segs[1] == "list":
        return [{"name": n, "code": cd, "type1": 0, "type2": 0, "level": lv, "pcode": pc, "pname": "",
                 "isleaf": leaf} for n, cd, lv, pc, leaf in _MOCK_SW] + [
                {"name": "概念-白酒", "code": "gn_bj", "type1": 1, "type2": 0, "level": 1, "pcode": "gn", "pname": "",
                 "isleaf": 1}]
    if segs[1] == "zg" and len(segs) > 3:
        m = {"000001": ["sw_yx", "sw2_480300"], "601318": ["sw_fy", "sw2_490200"]}.get(segs[2])
        if m:
            return [{"code": cd, "name": n} for n, cd, *_ in _MOCK_SW if cd in m]
    if segs[1] == "gg" and len(segs) > 3:
        m = {"sw_yx": ["000001", "600000", "601398", "601939", "600036"],
             "sw2_490200": ["601318", "601628", "601601", "601336", "601319"]}.get(segs[2])
        if m:
            return [{"dm": d, "mc": f"成分{d}", "jys": "sh" if d[0] == "6" else "sz"} for d in m]
    return None


def _daily_rows(code: str, q: dict) -> list:
    from datetime import date, timedelta
    px = {"600519.SH": 1450.0, "000001.SZ": 11.6, "601318.SH": 55.0}.get(code, 10.0)
    out, d = [], date(2026, 9, 1)
    while d <= date(2026, 10, 30):
        if d.weekday() < 5:
            out.append({"t": d.isoformat(), "o": px, "h": px, "l": px, "c": px, "v": 1000.0, "a": px * 1000,
                        "pc": px, "sf": 0})
        d += timedelta(days=1)
    return out


def _gap_routes(path, segs, q, js):
    from datetime import date, timedelta
    if path.startswith("/tcalendar/list/"):
        return js(["20260105", _bj_now_str()[:10].replace("-", ""), "20261231"])
    if len(segs) == 4 and segs[:2] == ["hsrl", "ssjy"]:
        return js({"t": _bj_now_str(30), "p": 11.64, "o": 11.53, "h": 11.67, "l": 11.4, "v": 186.42,
                   "cje": 2152393886.36})
    if "real" in segs and "time" in segs:
        return js({"p": 11.64, "o": 11.53, "h": 11.67, "l": 11.4, "cje": 2152393900, "v": 1864245,
                   "pv": 186424507, "tv": 33388, "t": _bj_now_str(3)})
    if path.startswith("/hsstock/latest/") and "/d/" in path:
        return js([{"t": "2026-10-30", "o": 11.53, "h": 11.67, "l": 11.4, "c": 11.64, "v": 1864245.0,
                    "a": 2152393900.0, "pc": 11.54, "sf": 0}])
    if path.startswith("/hsstock/financial/") and segs[2] in ("income", "balance", "cashflow"):
        return js(_fin_rows(segs[2], segs[3] if len(segs) > 4 else ""))
    if path.startswith("/hsstock/financial/capital/") and len(segs) > 4:
        return js(_capital_rows(segs[3]))
    if path.startswith("/hscp/jnfh/") and len(segs) > 3:
        return js(_jnfh_rows(segs[2]))
    if path.startswith("/hszg/"):
        r = _hszg_route(segs)
        if r is not None:
            return js(r)
    if path.startswith("/hsstock/history/") and "/d/n/" in path and q.get("st") == ["20260901"]:
        return js(_daily_rows(segs[2], q))
    if path.startswith("/hslt/ztgc/"):
        # 涨停池：fbt 用接近 00:00 的时刻，保证取样时刻（真实当前时间）之后几乎总在其后；
        # 另含 1 只 fbt=23:59:59（取样时刻之后封板 → 不选）、1 只无 fbt、1 只原样本（排除）
        return js([{"dm": "600519", "mc": "原样本", "p": 1500.0, "zf": 10.0, "fbt": "00:00:00", "lbt": "00:00:00",
                    "zbc": 0, "lbc": 1},
                   {"dm": "002001", "mc": "涨停A", "p": 11.0, "zf": 10.0, "fbt": "00:00:01", "lbt": "00:00:01",
                    "zbc": 0, "lbc": 2},
                   {"dm": "603001", "mc": "涨停B", "p": 22.0, "zf": 10.0, "fbt": "00:00:02", "lbt": "00:00:05",
                    "zbc": 1, "lbc": 1},
                   {"dm": "300001", "mc": "无封板时间", "p": 12.0, "zf": 20.0, "lbc": 1},
                   {"dm": "603002", "mc": "晚封板", "p": 33.0, "zf": 10.0, "fbt": "23:59:59", "lbt": "23:59:59",
                    "zbc": 0, "lbc": 1}])
    if path.startswith("/hslt/list/"):
        return js([{"dm": f"{i:06d}", "mc": f"股票{i}", "jys": "sz"} for i in range(1, 50)]
                  + [{"dm": "600519", "mc": "贵州茅台", "jys": "sh"}])
    if path.startswith("/hsstock/announcement/"):
        return js([{"t": "2026-10-30 00:00:00", "zt": "公告A", "nr": "http://example.invalid/a"},
                   {"t": "2026-10-29 00:00:00", "zt": "公告B", "nr": "http://example.invalid/b"}])
    if path.startswith("/factor/list/"):
        return js({"code": 200, "msg": "success", "data": {"list": [{"factor_id": f} for f in _MOCK_FACTORS]}})
    if path.startswith("/factor/all/"):
        d = {"code": segs[2], "name": "mock", "trade_date": "20261030", "update_time": "2026-10-30 17:00:00",
             "calc_version": "1.0"}
        for f in _MOCK_FACTORS:
            d[f] = None if f.startswith("north") or f == "attention_score" else 1.0
        for f in ("limit_up_streak", "seal_ratio", "seal_to_float"):   # 复测 2：涨停股有值，其他为空
            d[f] = 1.0 if segs[2] in ("002001", "603001") else None
            d[f + "_rank"] = None
        return js({"code": 200, "msg": "success", "data": d})
    if path.startswith("/factor/history/"):
        st = date(2025, 5, 6)
        out, v = [], 10.0
        for i in range(365):
            dd = st + timedelta(days=i)
            if dd.isoformat() in ("2025-08-14", "2025-10-27", "2026-04-03"):
                v += 1.0               # 在披露日之后跳变（模拟“按时点”）
            out.append({"trade_date": dd.strftime("%Y%m%d"), "value": v})
        return js({"code": 200, "msg": "success", "data": {"list": out}})
    return None


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
    if path.startswith("/bj/list/all/"):        # p12：京市列表（路径来自 plan.md；字段按 /hslt/list 伪造）
        return js([{"dm": f"920{i:03d}", "mc": f"京股{i}", "jys": "bj"} for i in range(30)]
                  + [{"dm": "832000", "mc": "旧码样例", "jys": "bj"}])
    if path.startswith("/kc/list/all/"):        # p12：科创板列表
        return js([{"dm": f"688{i:03d}", "mc": f"科创{i}", "jys": "sh"} for i in range(20)]
                  + [{"dm": "689009", "mc": "CDR样例", "jys": "sh"}])
    if "all" in segs[:-1] and not path.startswith("/factor/"):
        return js([{"dm": f"{i:06d}", "p": 10.0, "t": "2026-10-30 15:00:00"} for i in range(1500)])
    if method == "POST":
        try:
            jb = json.loads(body or b"{}")
        except ValueError:
            return js({"detail": "bad json"}, 400)
        if path.startswith("/factor/batch/") and isinstance(jb, dict) and jb.get("trade_date"):
            # p11 GAP7：按 T-B48 真实结构（data.items.{code} + 响应层 data.trade_date）回显请求日期
            td = str(jb["trade_date"])
            return js({"code": 200, "msg": "success", "data": {"trade_date": td, "items": {
                cd: {f: 11.0 for f in jb.get("factor_ids") or []} for cd in jb.get("codes") or []}}})
        return js({"code": 200, "data": {"list": [{"code": "600519", "pe_ttm": 25.1, "roe_ttm": None}]}})
    gap = _gap_routes(path, segs, q, js)        # p11_gaps 新增接口的伪造响应
    if gap is not None:
        return gap
    if path.startswith("/factor/"):
        return js({"code": "600519", "trade_date": "2026-10-30", "pe_ttm": 25.1, "pb": None, "roe_ttm": 30.2})
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
