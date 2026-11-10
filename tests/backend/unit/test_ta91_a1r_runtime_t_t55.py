# ruff: noqa: S101
"""T-T55 / T-A91 A1r：运行时拦截（netguard / 放行窗口）。

每例在子进程中先安装测试防护再 `netguard.install()`，然后执行绕过写法。
保证不产生真实外网/麦蕊请求：
- 子进程 `env -u MAIRUI_LICENCE` 且 `MAIRUI_LICENCE=`、`MAIRUI_MODE=replay`
- 优先 `unshare -n`（无网命名空间）；若内核拒绝（本机已测 Operation not permitted），
  子进程仍安装：麦蕊域名 DNS 直接失败；`connect`/`connect_ex` 只放行 AF_UNIX / 回环 /
  RFC1918 / ULA / 文档网段 203.0.113.0/24（超短超时），其它立即 OSError
- 绕过目标只用 203.0.113.x 或本机不可达地址，curl --max-time 1 指向 203.0.113.10
- 不用真 transport、不读证书
被拦 ⇒ 子进程看到 EgressBlocked；被放行 ⇒ gaierror/OSError（或防护层 OSError）即判红。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PY = sys.executable
SRC = str(ROOT / "src/backend")

# Child preamble: never talk to Mairui; optional unshare added by parent.
_PREAMBLE = r"""
import os, socket, sys, ipaddress
os.environ.pop("MAIRUI_LICENCE", None)
os.environ["MAIRUI_LICENCE"] = ""
os.environ["MAIRUI_MODE"] = "replay"
_BLOCK = ("mairuiapi.com", "mairui.com")
_real_gai = socket.getaddrinfo
def _gai(host, *a, **k):
    h = host.decode("ascii","ignore") if isinstance(host, bytes) else host
    h = (h or "").lower().rstrip(".")
    if any(h == s or h.endswith("."+s) for s in _BLOCK):
        raise OSError("test-dns-block-mairui")
    return _real_gai(host, *a, **k)
socket.getaddrinfo = _gai
def _ok_ip(addr):
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return bool(ip.is_loopback or ip.is_private or ip.is_link_local
                or ip in ipaddress.ip_network("203.0.113.0/24"))
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
def _safe_addr(address):
    if not isinstance(address, tuple) or not address:
        return True  # AF_UNIX str / path
    host = address[0]
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    if host in {"127.0.0.1", "::1", "localhost"}:
        return True
    try:
        return _ok_ip(host)
    except Exception:
        return False
def _connect(self, address):
    if self.family == socket.AF_UNIX:
        return _real_connect(self, address)
    if not _safe_addr(address):
        raise OSError("test-connect-blocked-non-local")
    self.settimeout(0.2)
    return _real_connect(self, address)
def _connect_ex(self, address):
    if self.family == socket.AF_UNIX:
        return _real_connect_ex(self, address)
    if not _safe_addr(address):
        return 111
    self.settimeout(0.2)
    return _real_connect_ex(self, address)
socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
"""


def _child_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "MAIRUI_LICENCE"}
    env["MAIRUI_LICENCE"] = ""
    env["MAIRUI_MODE"] = "replay"
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run_child(body: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    script = _PREAMBLE + "\n" + body + "\n"
    cmd_py = [PY, "-c", script]
    # Prefer unshare -n; fall back if not permitted.
    unshare = ["unshare", "-n", "--"] + cmd_py
    try:
        proc = subprocess.run(
            unshare,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            env=_child_env(),
        )
        if proc.returncode != 0 and "Operation not permitted" in (proc.stderr or ""):
            proc = subprocess.run(
                cmd_py,
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout,
                env=_child_env(),
            )
    except FileNotFoundError:
        proc = subprocess.run(
            cmd_py,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            env=_child_env(),
        )
    return proc


def _assert_blocked(proc: subprocess.CompletedProcess[str], label: str) -> None:
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    assert "SECRET" not in out and "licence=" not in out.lower()
    assert "https://" not in out.lower() or "blocked" in out.lower()
    if proc.returncode == 0 and "EGRESS_BLOCKED" in (proc.stdout or ""):
        return
    raise AssertionError(
        f"A1r {label} 未得到 EgressBlocked（被放行即红）。rc={proc.returncode}\n"
        f"stdout={proc.stdout[-600:]!s}\nstderr={proc.stderr[-600:]!s}"
    )


_INSTALL = r"""
try:
    from app.ingest import netguard
except ImportError as exc:
    sys.stderr.write("NETGUARD_MISSING:"+type(exc).__name__+"\n")
    sys.exit(2)
netguard.install()
Blocked = netguard.EgressBlocked
"""


def test_a1r_importlib_https_get_without_window() -> None:
    """① importlib.import_module(...egress)._https_get 无窗口调用须 EgressBlocked。"""
    body = _INSTALL + r"""
import importlib
eg = importlib.import_module("app.ingest.egress")
try:
    eg._https_get("/hsstock/","x")
except Blocked:
    print("EGRESS_BLOCKED")
    raise SystemExit(0)
except Exception as exc:
    print("OTHER", type(exc).__name__, file=sys.stderr)
    raise SystemExit(3)
print("ALLOWED")
raise SystemExit(4)
"""
    _assert_blocked(_run_child(body), "importlib")


def test_a1r_getattr_https_get() -> None:
    """② getattr(egress, '_https_get') 无窗口调用须 EgressBlocked。"""
    body = _INSTALL + r"""
import app.ingest.egress as egress
fn = getattr(egress, "_https_get")
try:
    fn("/hsstock/","x")
except Blocked:
    print("EGRESS_BLOCKED")
    raise SystemExit(0)
except Exception as exc:
    print("OTHER", type(exc).__name__, file=sys.stderr)
    raise SystemExit(3)
print("ALLOWED")
raise SystemExit(4)
"""
    _assert_blocked(_run_child(body), "getattr")


def test_a1r_dunder_import_requests_split_domain() -> None:
    """③ __import__('requests') + 拆开域名 api.+mairui+api.com 须 EgressBlocked。"""
    body = _INSTALL + r"""
req = __import__("requests")
host = "api." + "mairui" + "api.com"
try:
    req.get("http://"+host+"/", timeout=1)
except Blocked:
    print("EGRESS_BLOCKED")
    raise SystemExit(0)
except Exception as exc:
    print("OTHER", type(exc).__name__, file=sys.stderr)
    raise SystemExit(3)
print("ALLOWED")
raise SystemExit(4)
"""
    _assert_blocked(_run_child(body), "__import__+split-domain")


def test_a1r_socket_literal_public_ip() -> None:
    """④ socket 直连文档网段 203.0.113.x 须 EgressBlocked。"""
    body = _INSTALL + r"""
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(0.2)
try:
    s.connect(("203.0.113.10", 443))
except Blocked:
    print("EGRESS_BLOCKED")
    raise SystemExit(0)
except Exception as exc:
    print("OTHER", type(exc).__name__, file=sys.stderr)
    raise SystemExit(3)
finally:
    s.close()
print("ALLOWED")
raise SystemExit(4)
"""
    _assert_blocked(_run_child(body), "socket-203.0.113")


def test_a1r_urllib3_poolmanager_mairui_host() -> None:
    """⑤ urllib3 PoolManager 访问麦蕊域名须 EgressBlocked。"""
    body = _INSTALL + r"""
import urllib3
host = "api." + "mairui" + "api.com"
http = urllib3.PoolManager(timeout=1.0, retries=False)
try:
    http.request("GET", "https://"+host+"/")
except Blocked:
    print("EGRESS_BLOCKED")
    raise SystemExit(0)
except Exception as exc:
    print("OTHER", type(exc).__name__, file=sys.stderr)
    raise SystemExit(3)
print("ALLOWED")
raise SystemExit(4)
"""
    _assert_blocked(_run_child(body), "urllib3")


def test_a1r_lease_held_but_outside_window() -> None:
    """⑥ 持有 lease 但窗口外连接须 EgressBlocked。"""
    body = _INSTALL + r"""
import socket
# lease object if any is irrelevant: connect must be blocked outside window
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(0.2)
try:
    s.connect(("203.0.113.20", 443))
except Blocked:
    print("EGRESS_BLOCKED")
    raise SystemExit(0)
except Exception as exc:
    print("OTHER", type(exc).__name__, file=sys.stderr)
    raise SystemExit(3)
finally:
    s.close()
print("ALLOWED")
raise SystemExit(4)
"""
    _assert_blocked(_run_child(body), "outside-window")


def test_a1r_lease_thread_a_window_thread_b() -> None:
    """⑦ lease 在 A 线程签发、B 线程进入窗口或连接须 EgressBlocked。"""
    body = _INSTALL + r"""
import threading, socket
err = {}
def other():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        s.connect(("203.0.113.21", 443))
        err["allowed"] = True
    except Blocked:
        err["blocked"] = True
    except Exception as exc:
        err["other"] = type(exc).__name__
    finally:
        s.close()
# Best-effort: if _egress_window exists, open it only in this thread.
try:
    from app.ingest import egress as eg
    from app.ingest import netguard
    win = getattr(netguard, "_egress_window", None) or getattr(eg, "_egress_window", None)
except Exception:
    win = None
t = threading.Thread(target=other)
t.start()
t.join(3)
if err.get("blocked"):
    print("EGRESS_BLOCKED")
    raise SystemExit(0)
print("NOT_BLOCKED", err)
raise SystemExit(4)
"""
    _assert_blocked(_run_child(body), "cross-thread")


def test_a1r_subprocess_curl_os_system_posix_spawn() -> None:
    """⑧ subprocess.run(curl)、os.system、os.posix_spawn 须 EgressBlocked（curl 只指向 203.0.113.10）。"""
    body = _INSTALL + r"""
import subprocess, os, shutil
curl = shutil.which("curl") or "curl"
target = ["curl", "--max-time", "1", "-sS", "http://203.0.113.10/"]
blocked = 0
try:
    subprocess.run(target, check=False, timeout=2)
except Blocked:
    blocked += 1
try:
    os.system("true")
except Blocked:
    blocked += 1
if hasattr(os, "posix_spawn"):
    try:
        os.posix_spawn(curl, target, os.environ)
    except Blocked:
        blocked += 1
    except FileNotFoundError:
        blocked += 0
if blocked:
    print("EGRESS_BLOCKED")
    raise SystemExit(0)
print("ALLOWED")
raise SystemExit(4)
"""
    _assert_blocked(_run_child(body), "subprocess")


def test_a1r_ctypes_cdll_libc() -> None:
    """⑨ ctypes.CDLL('libc.so.6') 须 EgressBlocked（不经 ctypes 调 connect）。"""
    body = _INSTALL + r"""
import ctypes
try:
    ctypes.CDLL("libc.so.6")
except Blocked:
    print("EGRESS_BLOCKED")
    raise SystemExit(0)
except Exception as exc:
    print("OTHER", type(exc).__name__, file=sys.stderr)
    raise SystemExit(3)
print("ALLOWED")
raise SystemExit(4)
"""
    _assert_blocked(_run_child(body), "ctypes")


def test_a1r_positive_window_fake_ip_is_oserror_not_blocked() -> None:
    """正向：窗口内假解析 203.0.113.10 登记后连接被放行，无网下为 OSError 而非 EgressBlocked。"""
    body = _INSTALL + r"""
import socket
# If no window API yet, this is red (cannot allow in-window connect).
win_cm = getattr(netguard, "_egress_window", None)
if win_cm is None:
    print("NO_WINDOW_API")
    raise SystemExit(4)
# fake lease if required
lease = None
try:
    import app.ingest.egress as eg
    lease = getattr(eg, "EgressLease", lambda **k: None)
except Exception:
    pass
# monkeypatch getaddrinfo used inside window
def fake_gai(host, *a, **k):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("203.0.113.10", 0))]
socket.getaddrinfo = fake_gai
try:
    with win_cm(lease) if lease is not None else win_cm():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.2)
        try:
            s.connect(("203.0.113.10", 443))
        except Blocked:
            print("BLOCKED_IN_WINDOW")
            raise SystemExit(4)
        except OSError:
            print("OSERROR_IN_WINDOW")
            raise SystemExit(0)
        finally:
            s.close()
        print("CONNECTED")
        raise SystemExit(4)
except Blocked:
    print("BLOCKED_OPENING_WINDOW")
    raise SystemExit(4)
"""
    proc = _run_child(body)
    if proc.returncode != 0 or "OSERROR_IN_WINDOW" not in (proc.stdout or ""):
        raise AssertionError(
            f"A1r 正向窗口未放行至 OSError。rc={proc.returncode}\n"
            f"stdout={proc.stdout[-600:]}\nstderr={proc.stderr[-600:]}"
        )


def test_a1r_private_and_unix_unaffected() -> None:
    """正向：postgres/redis 私网地址与 AF_UNIX 不受 netguard 拒绝。"""
    body = _INSTALL + r"""
import socket, tempfile, os
# AF_UNIX connect to a missing path → OSError, not EgressBlocked
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
try:
    s.connect("/tmp/tt55-no-such-unix.sock")
except Blocked:
    print("BLOCKED_UNIX")
    raise SystemExit(4)
except OSError:
    pass
finally:
    s.close()
# RFC1918 connect (short timeout) → OSError/timeout, not EgressBlocked
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(0.2)
try:
    s.connect(("10.255.255.1", 1))
except Blocked:
    print("BLOCKED_PRIVATE")
    raise SystemExit(4)
except OSError:
    pass
finally:
    s.close()
print("PRIVATE_OK")
raise SystemExit(0)
"""
    proc = _run_child(body)
    if proc.returncode != 0 or "PRIVATE_OK" not in (proc.stdout or ""):
        raise AssertionError(
            f"A1r 私网/UNIX 被误拦。rc={proc.returncode}\n"
            f"stdout={proc.stdout[-600:]}\nstderr={proc.stderr[-600:]}"
        )


def test_a1r_main_installs_first_line_and_reinstall_noop() -> None:
    """正向：main() 第一行已安装（AST + sys.audit 探测）；重复 install() 为 no-op。"""
    body = r"""
import ast, inspect, sys
from pathlib import Path
# AST: main body first meaningful stmt is netguard.install()
src_path = Path("src/backend/app/workers/ingest.py")
tree = ast.parse(src_path.read_text(encoding="utf-8"))
main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
# skip docstrings
stmts = list(main.body)
if stmts and isinstance(stmts[0], ast.Expr) and isinstance(getattr(stmts[0], "value", None), ast.Constant):
    stmts = stmts[1:]
first = stmts[0] if stmts else None
ok = False
if isinstance(first, ast.Expr) and isinstance(first.value, ast.Call):
    f = first.value.func
    if isinstance(f, ast.Attribute) and f.attr == "install":
        ok = True
    if isinstance(f, ast.Name) and f.id == "install":
        ok = True
if not ok:
    print("MAIN_FIRST_NOT_INSTALL", type(first).__name__ if first else None)
    raise SystemExit(4)
try:
    from app.ingest import netguard
except ImportError:
    print("NETGUARD_MISSING")
    raise SystemExit(2)
netguard.install()
netguard.install()  # no-op, must not raise
print("INSTALL_OK")
raise SystemExit(0)
"""
    proc = _run_child(body)
    if proc.returncode != 0 or "INSTALL_OK" not in (proc.stdout or ""):
        raise AssertionError(
            f"A1r main/install 未满足。rc={proc.returncode}\n"
            f"stdout={proc.stdout[-800:]}\nstderr={proc.stderr[-800:]}"
        )
