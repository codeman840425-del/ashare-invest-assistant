# ruff: noqa: S101, S603, S607, E501, PT018
"""T-B116d A1r: netguard runtime hook. Every case runs in a subprocess (hook is sticky)."""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
WORKER = BACKEND / "app/workers/ingest.py"


def _unshare_prefix() -> list[str]:
    if shutil.which("unshare") is None:
        return []
    probe = subprocess.run(
        ["unshare", "-n", "true"],
        check=False,
        capture_output=True,
    )
    return ["unshare", "-n", "--"] if probe.returncode == 0 else []


def _run(script: str, timeout: float = 15) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("MAIRUI_LICENCE", None)
    env["MAIRUI_LICENCE"] = ""
    env["PYTHONPATH"] = str(BACKEND) + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    cmd = [*_unshare_prefix(), sys.executable, "-c", script]
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        cwd=str(BACKEND),
    )


PRELUDE = r"""
import logging, os, sys, socket, ctypes, subprocess
from io import StringIO
sys.path.insert(0, os.environ.get("PYTHONPATH", ".").split(os.pathsep)[0])
from app.ingest import netguard as ng
buf = StringIO()
h = logging.StreamHandler(buf)
h.setLevel(logging.WARNING)
logging.getLogger("app.ingest.netguard").addHandler(h)
logging.getLogger("app.ingest.netguard").setLevel(logging.WARNING)
ng.install()

def check_log():
    text = buf.getvalue()
    low = text.lower()
    assert "mairuiapi.com" not in low, text
    assert "http://" not in low and "https://" not in low, text
    # no full public IP
    assert "203.0.113." not in text, text
    return text
"""


def _ok(script: str, expect: str = "OK") -> None:
    result = _run(PRELUDE + "\n" + script)
    if expect not in result.stdout or result.returncode != 0:
        raise AssertionError(
            f"rc={result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )


def test_tb116d_a1r_importlib_https_get_without_window() -> None:
    _ok(
        r"""
import importlib
eg = importlib.import_module("app.ingest.egress")
try:
    eg._https_get("/x/", "secret-should-not-log")
except ng.EgressBlocked as exc:
    check_log()
    print("OK", type(exc).__name__)
else:
    sys.exit(2)
"""
    )


def test_tb116d_a1r_getattr_https_get() -> None:
    _ok(
        r"""
from app.ingest import egress as eg
fn = getattr(eg, "_https_get")
try:
    fn("/x/", "s")
except ng.EgressBlocked:
    check_log(); print("OK")
else:
    sys.exit(2)
"""
    )


def test_tb116d_a1r_requests_split_domain() -> None:
    _ok(
        r"""
host = "api." + "mairui" + "api.com"
try:
    requests = __import__("requests")
    requests.get("https://" + host + "/")
except ng.EgressBlocked:
    check_log(); print("OK")
except ImportError:
    # requests may be absent; still resolve the split name.
    try:
        socket.getaddrinfo(host, 443)
    except ng.EgressBlocked:
        check_log(); print("OK")
    else:
        sys.exit(2)
else:
    sys.exit(2)
"""
    )


def test_tb116d_a1r_socket_public_ip_literal() -> None:
    _ok(
        r"""
s = socket.socket(); s.settimeout(0.3)
try:
    s.connect(("203.0.113.10", 443))
except ng.EgressBlocked:
    check_log(); print("OK")
except OSError:
    sys.exit(2)
else:
    sys.exit(2)
"""
    )


def test_tb116d_a1r_urllib3_poolmanager() -> None:
    _ok(
        r"""
try:
    import urllib3
    urllib3.PoolManager().request("GET", "https://api.mairuiapi.com/")
except ng.EgressBlocked:
    check_log(); print("OK")
except ImportError:
    try:
        socket.getaddrinfo("api.mairuiapi.com", 443)
    except ng.EgressBlocked:
        check_log(); print("OK")
    else:
        sys.exit(2)
else:
    sys.exit(2)
"""
    )


def test_tb116d_a1r_lease_held_but_connect_outside_window() -> None:
    _ok(
        r"""
# window never opened
s = socket.socket(); s.settimeout(0.3)
try:
    s.connect(("203.0.113.11", 443))
except ng.EgressBlocked:
    check_log(); print("OK")
else:
    sys.exit(2)
"""
    )


def test_tb116d_a1r_cross_thread_window_or_connect() -> None:
    _ok(
        r"""
import threading
class L: pass
lease = L()
opened = {"b": False}
err = {"b": None}
def in_b():
    try:
        with ng.egress_window(lease, lambda: False):
            opened["b"] = True
    except ng.EgressBlocked as exc:
        err["b"] = type(exc).__name__
    s = socket.socket(); s.settimeout(0.3)
    try:
        s.connect(("203.0.113.12", 443))
        err["conn"] = "allowed"
    except ng.EgressBlocked:
        err["conn"] = "blocked"
    except OSError:
        err["conn"] = "oserror"
th = threading.Thread(target=in_b)
# A holds a window so only A is approved
with ng.egress_window(lease, lambda: True):
    th.start(); th.join()
assert opened["b"] is False, opened
assert err["b"] == "EgressBlocked", err
assert err["conn"] == "blocked", err
check_log(); print("OK")
"""
    )


def test_tb116d_a1r_subprocess_system_posix_spawn() -> None:
    _ok(
        r"""
import os
caught = []
for fn, args in (
    (lambda: subprocess.run(["curl", "https://example.com"]), ()),
    (lambda: os.system("true"), ()),
):
    try:
        fn()
    except ng.EgressBlocked:
        caught.append("blocked")
    else:
        sys.exit(2)
if hasattr(os, "posix_spawn"):
    try:
        os.posix_spawn("/bin/true", ["/bin/true"], os.environ)
    except ng.EgressBlocked:
        caught.append("spawn")
    else:
        sys.exit(2)
assert caught
check_log(); print("OK")
"""
    )


def test_tb116d_a1r_ctypes_dlopen() -> None:
    _ok(
        r"""
try:
    ctypes.CDLL("libc.so.6")
except ng.EgressBlocked:
    check_log(); print("OK")
else:
    sys.exit(2)
"""
    )


def test_tb116d_a1r_positive_window_private_and_unix() -> None:
    _ok(
        r"""
class L: pass
# public IP inside window after register → OSError (no net), not EgressBlocked
with ng.egress_window(L(), lambda: True):
    ng.register_resolved_ip("203.0.113.10")
    s = socket.socket(); s.settimeout(0.2)
    try:
        s.connect(("203.0.113.10", 443))
    except ng.EgressBlocked:
        sys.exit(3)
    except OSError:
        pass
    else:
        pass  # unexpected success still means not blocked
# loopback / unix allowed
s = socket.socket(); s.settimeout(0.2)
try:
    s.connect(("127.0.0.1", 1))
except ng.EgressBlocked:
    sys.exit(4)
except OSError:
    pass
s = socket.socket(socket.AF_UNIX)
try:
    s.connect("/tmp/tb116d-a1r-no-such.sock")
except ng.EgressBlocked:
    sys.exit(5)
except OSError:
    pass
print("OK")
"""
    )


def test_tb116d_a1r_main_installs_first_and_repeat_install_noop() -> None:
    src = WORKER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    body = [n for n in main.body if not isinstance(n, ast.Expr) or not isinstance(getattr(n, "value", None), ast.Constant)]
    first = body[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
    func = first.value.func
    assert (isinstance(func, ast.Attribute) and func.attr == "install") or (
        isinstance(func, ast.Name) and func.id == "install"
    )
    assert any("legacy_licence_present" in ast.dump(n) for n in body[1:6])
    _ok(
        r"""
# runtime: call main() after stubbing so it returns immediately after install
from app.workers import ingest as iw
iw.legacy_licence_present = lambda environ=None: True
rc = iw.main()
assert rc == iw.EXIT_LEGACY_LICENCE
s = socket.socket(); s.settimeout(0.2)
try:
    s.connect(("203.0.113.99", 443))
except ng.EgressBlocked:
    pass
else:
    sys.exit(2)
# repeat install is a no-op (must not raise, hook still active)
ng.install(); ng.install()
try:
    s2 = socket.socket(); s2.settimeout(0.2)
    s2.connect(("203.0.113.98", 443))
except ng.EgressBlocked:
    print("OK")
else:
    sys.exit(2)
"""
    )


def test_tb116e_a1r_hostname_connect_denied() -> None:
    # ⑩ non-IP literal (hostname) is always denied, even if C would resolve it.
    _ok(
        r"""
s = socket.socket(); s.settimeout(0.2)
try:
    s.connect(("example.com", 443))
except ng.EgressBlocked:
    check_log(); print("OK")
else:
    sys.exit(2)
"""
    )


def test_tb116e_a1r_cdll_none_and_pythonapi_connect_denied() -> None:
    # ⑪ CDLL(None) and pythonapi.connect (dlsym of a non-Py symbol) denied.
    _ok(
        r"""
caught = []
try:
    ctypes.CDLL(None)
except ng.EgressBlocked:
    caught.append("dlopen_none")
else:
    sys.exit(2)
try:
    ctypes.pythonapi.connect
except ng.EgressBlocked:
    caught.append("dlsym_connect")
else:
    sys.exit(2)
assert caught == ["dlopen_none", "dlsym_connect"]
check_log(); print("OK")
"""
    )


def test_tb116e_a1r_sendto_sendmsg_follow_connect_rules() -> None:
    # ⑫ sendto / sendmsg with a destination follow the same rules as connect.
    _ok(
        r"""
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setblocking(False)
try:
    s.sendto(b"x", ("203.0.113.10", 9))
except ng.EgressBlocked:
    pass
else:
    sys.exit(2)
s2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s2.setblocking(False)
try:
    s2.sendmsg([b"x"], [], 0, ("203.0.113.10", 9))
except ng.EgressBlocked:
    pass
else:
    sys.exit(3)
s3 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s3.setblocking(False)
try:
    s3.sendto(b"x", ("example.com", 9))
except ng.EgressBlocked:
    pass
else:
    sys.exit(4)
# loopback sendto is allowed (OSError/success, not EgressBlocked)
s4 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s4.setblocking(False)
try:
    s4.sendto(b"x", ("127.0.0.1", 9))
except ng.EgressBlocked:
    sys.exit(5)
except OSError:
    pass
check_log(); print("OK")
"""
    )


def test_tb116e_a1r_window_requires_validate() -> None:
    # ⑬ egress_window without validate, or validate=None, is EgressBlocked.
    _ok(
        r"""
try:
    with ng.egress_window(None):
        raise SystemExit(2)
except ng.EgressBlocked:
    pass
try:
    with ng.egress_window(object(), None):
        raise SystemExit(3)
except ng.EgressBlocked:
    pass
# None lease is refused even if validate returns True (T-A92 ⑬)
try:
    with ng.egress_window(None, lambda: True):
        raise SystemExit(5)
except ng.EgressBlocked:
    pass
# validate that returns False is also blocked
try:
    with ng.egress_window(object(), lambda: False):
        raise SystemExit(4)
except ng.EgressBlocked:
    check_log(); print("OK")
"""
    )
