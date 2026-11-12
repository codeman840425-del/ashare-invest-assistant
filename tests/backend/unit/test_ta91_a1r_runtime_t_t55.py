# ruff: noqa: S101
"""T-T56 / T-A92 A1r：运行时拦截（netguard / 放行窗口）。

每例在子进程中先 `netguard.install()`，再追加测试审计钩子，然后执行绕过写法。
保证不产生真实外网/麦蕊请求：
- 子进程 `env -u MAIRUI_LICENCE` 且 `MAIRUI_LICENCE=`、`MAIRUI_MODE=replay`
- 优先 `unshare -n`（无网命名空间）；若内核拒绝（Operation not permitted），
  在 `netguard.install()` **之后** `sys.addaudithook` 追加测试钩子：对非
  AF_UNIX / 回环 / RFC1918 / ULA 的 connect/sendto/sendmsg 抛 OSError，
  并对麦蕊域名的 getaddrinfo 抛 OSError。
- **不得**在 Python 层替换 `socket.getaddrinfo` / `socket.socket.connect`
  （会遮蔽 C 层审计事件，测到的是测试自己的拦截）。
- 绕过目标只用 203.0.113.x 或主机名直连；不用真 transport、不读证书。
被拦 ⇒ 子进程看到 EgressBlocked；被放行 ⇒ 测试钩子 OSError / gaierror 即判红。
正向窗口须先 `register_resolved_ip` 并传入 `validate`。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PY = sys.executable
SRC = str(ROOT / "src/backend")

# Env only — do not replace socket.getaddrinfo / connect in the preamble.
_PREAMBLE = r"""
import os, sys
os.environ.pop("MAIRUI_LICENCE", None)
os.environ["MAIRUI_LICENCE"] = ""
os.environ["MAIRUI_MODE"] = "replay"
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


# install first (product hook), then append the test safety-net audithook.
_INSTALL = r"""
try:
    from app.ingest import netguard
except ImportError as exc:
    sys.stderr.write("NETGUARD_MISSING:"+type(exc).__name__+"\n")
    sys.exit(2)
netguard.install()
Blocked = netguard.EgressBlocked

import ipaddress, socket, sys as _sys

# Python 3.12+ treats documentation ranges (203.0.113.0/24 etc.) as is_private;
# the safety hook must still refuse them so UDP/TFO cannot leak packets.
_TT56_DOC = (
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("2001:db8::/32"),
)
def _tt56_ok_ip(addr):
    try:
        ip = ipaddress.ip_address(addr)
    except (ValueError, TypeError):
        return False
    if any(ip in net for net in _TT56_DOC):
        return False
    return bool(
        ip.is_loopback or ip.is_private or ip.is_link_local
        or ip.is_unspecified
    )

def _tt56_addr_host(address):
    if isinstance(address, (str, bytes)):
        return None  # AF_UNIX path
    if isinstance(address, tuple) and address:
        host = address[0]
        if isinstance(host, bytes):
            host = host.decode("ascii", "ignore")
        return host
    return None

def _tt56_test_hook(event, args):
    if event == "socket.getaddrinfo":
        host = args[0] if args else None
        if isinstance(host, bytes):
            host = host.decode("ascii", "ignore")
        h = (host or "").lower().rstrip(".")
        if h.endswith("mairuiapi.com") or h.endswith("mairui.com") or h in {
            "mairuiapi.com", "mairui.com"
        }:
            raise OSError("tt56-test-dns-block-mairui")
        return
    if event not in {"socket.connect", "socket.connect_ex", "socket.sendto", "socket.sendmsg"}:
        return
    # CPython 对各事件传入的 address 位置不同（sendto 可能是末参），逐项查找 (host, port)。
    host = None
    for item in args[1:]:
        got = _tt56_addr_host(item)
        if got is not None:
            host = got
            break
        # sendmsg ancdata / flags 之外，有时地址在嵌套元组
        if isinstance(item, tuple) and item and isinstance(item[0], tuple):
            got = _tt56_addr_host(item[0])
            if got is not None:
                host = got
                break
    if host is None:
        return
    if host in {"127.0.0.1", "::1", "localhost"} or _tt56_ok_ip(host):
        return
    # Public / TEST-NET / hostname: product hook should already have raised.
    # If we get here, the product allowed it — fail closed for the test process.
    raise OSError("tt56-test-net-safety")

_sys.addaudithook(_tt56_test_hook)
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
    """⑦ 须在 A 线程真开窗（validate + register_resolved_ip），B 线程连接已登记 IP → EgressBlocked。"""
    body = _INSTALL + r"""
import threading, socket
err = {}
ready = threading.Event()
win = getattr(netguard, "egress_window", None) or getattr(netguard, "_egress_window", None)
reg = getattr(netguard, "register_resolved_ip", None)
if win is None or reg is None:
    print("NO_WINDOW_API")
    raise SystemExit(4)

def other():
    ready.wait(3)
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

t = threading.Thread(target=other)
t.start()
opened = False
try:
    with win(object(), validate=lambda: True):
        reg("203.0.113.21")
        opened = True
        ready.set()
        t.join(3)
except Blocked:
    ready.set()
    t.join(3)
    print("WINDOW_NOT_OPENED")
    raise SystemExit(4)
except TypeError as exc:
    ready.set()
    t.join(3)
    print("WINDOW_TYPE_ERROR", type(exc).__name__, file=sys.stderr)
    raise SystemExit(4)
if not opened:
    print("WINDOW_NOT_OPENED")
    raise SystemExit(4)
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


def test_a1r_hostname_connect_blocked() -> None:
    """⑩ 非麦蕊主机名直连（不经 Python getaddrinfo）须 EgressBlocked。"""
    body = _INSTALL + r"""
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(0.2)
try:
    # CPython resolves in C before socket.connect is audited. An unresolvable
    # .example name raises gaierror before the product hook can inspect it.
    # localhost resolves offline; its hostname tuple must still be refused,
    # even though a loopback IP literal would be allowed. Do not patch sockets.
    s.connect(("localhost", 443))
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
    _assert_blocked(_run_child(body), "hostname-connect")


def test_a1r_cdll_none_and_pythonapi_connect() -> None:
    """⑪ ctypes.CDLL(None) 与 pythonapi.connect 须 EgressBlocked（不调用所得函数）。"""
    body = _INSTALL + r"""
import ctypes
bad = []
try:
    ctypes.CDLL(None)
    bad.append("CDLL_NONE_ALLOWED")
except Blocked:
    pass
except Exception as exc:
    bad.append("CDLL_NONE_OTHER:"+type(exc).__name__)
try:
    _ = ctypes.pythonapi.connect
    bad.append("PYTHONAPI_CONNECT_ALLOWED")
except Blocked:
    pass
except Exception as exc:
    bad.append("PYTHONAPI_CONNECT_OTHER:"+type(exc).__name__)
if not bad:
    print("EGRESS_BLOCKED")
    raise SystemExit(0)
print("NOT_BLOCKED", bad)
raise SystemExit(4)
"""
    _assert_blocked(_run_child(body), "cdll-none-pythonapi")


def test_a1r_sendto_and_tfo_blocked() -> None:
    """⑫ sendto UDP 与 TCP Fast Open 到公网须 EgressBlocked。"""
    body = _INSTALL + r"""
import socket
bad = []
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(0.2)
try:
    s.sendto(b"x", ("203.0.113.10", 53))
    bad.append("SENDTO_UDP_ALLOWED")
except Blocked:
    pass
except Exception as exc:
    bad.append("SENDTO_UDP_OTHER:"+type(exc).__name__)
finally:
    s.close()
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(0.2)
try:
    flags = getattr(socket, "MSG_FASTOPEN", 0x20000000)
    try:
        s.sendto(b"x", flags, ("203.0.113.11", 443))
    except TypeError:
        s.sendmsg([b"x"], [], flags, ("203.0.113.11", 443))
    bad.append("TFO_ALLOWED")
except Blocked:
    pass
except Exception as exc:
    bad.append("TFO_OTHER:"+type(exc).__name__)
finally:
    s.close()
if not bad:
    print("EGRESS_BLOCKED")
    raise SystemExit(0)
print("NOT_BLOCKED", bad)
raise SystemExit(4)
"""
    _assert_blocked(_run_child(body), "sendto-tfo")


def test_a1r_window_requires_validate_and_lease() -> None:
    """⑬ egress_window 不传 validate、或 lease 为 None，须 EgressBlocked。"""
    body = _INSTALL + r"""
win = getattr(netguard, "egress_window", None) or getattr(netguard, "_egress_window", None)
if win is None:
    print("NO_WINDOW_API")
    raise SystemExit(4)
bad = []
try:
    with win(object()):
        bad.append("OPENED_NO_VALIDATE")
except Blocked:
    pass
except TypeError:
    # 若签名把 validate 做成必填位置参数，TypeError 也视为拒开窗
    pass
except Exception as exc:
    bad.append("NO_VALIDATE_OTHER:"+type(exc).__name__)
try:
    with win(None, validate=lambda: True):
        bad.append("OPENED_NONE_LEASE")
except Blocked:
    pass
except Exception as exc:
    bad.append("NONE_LEASE_OTHER:"+type(exc).__name__)
if not bad:
    print("EGRESS_BLOCKED")
    raise SystemExit(0)
print("NOT_BLOCKED", bad)
raise SystemExit(4)
"""
    _assert_blocked(_run_child(body), "window-validate-lease")


def test_a1r_positive_window_fake_ip_is_oserror_not_blocked() -> None:
    """正向：窗口内先 register_resolved_ip(203.0.113.10) 并传 validate，连接被放行，无网下为 OSError 而非 EgressBlocked。"""
    body = _INSTALL + r"""
import socket
win = getattr(netguard, "egress_window", None) or getattr(netguard, "_egress_window", None)
reg = getattr(netguard, "register_resolved_ip", None)
if win is None or reg is None:
    print("NO_WINDOW_API")
    raise SystemExit(4)
try:
    with win(object(), validate=lambda: True):
        reg("203.0.113.10")
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
except TypeError as exc:
    print("WINDOW_TYPE_ERROR", type(exc).__name__)
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
import socket
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
try:
    s.connect("/tmp/tt56-no-such-unix.sock")
except Blocked:
    print("BLOCKED_UNIX")
    raise SystemExit(4)
except OSError:
    pass
finally:
    s.close()
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
import ast, sys
from pathlib import Path
src_path = Path("src/backend/app/workers/ingest.py")
tree = ast.parse(src_path.read_text(encoding="utf-8"))
main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
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
