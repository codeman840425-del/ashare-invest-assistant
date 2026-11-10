# ruff: noqa: S101
"""T-T58 / T-A93 B-4：准入 2.65s 后仍应调用 transport；开窗被拒须写 lease 审计日志。

假 transport；env -u MAIRUI_LICENCE；不打印 DSN/密钥。临时库用完删除。
-O 用例在子进程运行。
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests" / "backend" / "unit"))

from test_ta87_m1_a1_a24_t_t50 import (  # noqa: E402
    FakeTransport,
    _call_mairui,
    _import_egress,
    _make_core,
    _seed_licence,
    _temp_db,
)

PY = sys.executable
DELAY_S = 2.65


def _child_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "MAIRUI_LICENCE"}
    env["MAIRUI_LICENCE"] = ""
    env["MAIRUI_MODE"] = "replay"
    env["PYTHONPATH"] = (
        str(ROOT)
        + os.pathsep
        + str(ROOT / "src/backend")
        + os.pathsep
        + env.get("PYTHONPATH", "")
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _admit_delay_reaches_transport(tmp_path: Path, *, delay: float = DELAY_S) -> None:
    """准入路径注入 delay 秒（契约允许的 2.6–2.8s 内完成）后 transport 须仍被调用 1 次。"""
    eg = _import_egress()
    from app.ingest import ip_limit as ipl
    from app.ingest.daily_lists import DailyHaltError

    with _temp_db("a58d") as (eng, _n, _u):
        uid, lid = uuid.uuid4(), uuid.uuid4()
        _seed_licence(eng, uid, lid)
        core = _make_core(eng)
        orig = ipl.acquire_ip_limit_lock

        def _slow(conn: object, user_id: object) -> object:
            time.sleep(delay)
            return orig(conn, user_id)

        ipl.acquire_ip_limit_lock = _slow  # type: ignore[assignment]
        tr = FakeTransport(responses=[(200, {"ok": True})])
        try:
            try:
                _call_mairui(
                    eg,
                    engine=eng,
                    core=core,
                    lid=lid,
                    uid=uid,
                    transport=tr,
                    tmp_path=tmp_path,
                )
            except (DailyHaltError, eg.EgressDenied) as exc:
                raise AssertionError(
                    f"准入耗时 {delay}s 后合法调用被拒："
                    f"{type(exc).__name__} {getattr(exc, 'code', exc)}；"
                    f"transport 调用 {len(tr.calls)} 次（须为 1）。"
                    "T-A93 B-4：⑦ 再核不得沿用准入 deadline。"
                ) from exc
        finally:
            ipl.acquire_ip_limit_lock = orig  # type: ignore[assignment]
        assert len(tr.calls) == 1, f"transport 须调用 1 次，实际 {len(tr.calls)}"


def test_admit_delay_2_65s_still_calls_transport(tmp_path: Path) -> None:
    """准入注入 2.65s（仍在 2.8s 预算内）后须调用 transport。普通模式。"""
    _admit_delay_reaches_transport(tmp_path, delay=DELAY_S)


def test_admit_delay_2_65s_still_calls_transport_dash_o(tmp_path: Path) -> None:
    """同上，python -O 子进程。"""
    env = _child_env()
    env["A58_TMP"] = str(tmp_path)
    code = r"""
import os
from pathlib import Path
from tests.backend.unit.test_ta93_b4_admit_lease_audit_t_t58 import (
    DELAY_S,
    _admit_delay_reaches_transport,
)
_admit_delay_reaches_transport(Path(os.environ["A58_TMP"]), delay=DELAY_S)
print("A58_O_OK")
"""
    proc = subprocess.run(
        [PY, "-O", "-c", code],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
        env=env,
    )
    if proc.returncode != 0 or "A58_O_OK" not in (proc.stdout or ""):
        raise AssertionError(
            f"准入 2.65s -O 未通过。rc={proc.returncode}\n"
            f"stdout={proc.stdout[-800:]}\nstderr={proc.stderr[-800:]}"
        )


def test_window_denied_writes_lease_audit_log(tmp_path: Path) -> None:
    """开窗被拒（无 lease / 无 validate / validate 为假）须写 lease 审计日志。

    logger=`app.ingest.netguard`，WARNING，字段含 event=、category=lease、window=；
    不得含 URL、路径、证书、完整 IP 或 Traceback。子进程运行以免钩子留在本进程。
    """
    env = _child_env()
    code = r"""
import logging, io, sys
from app.ingest import netguard

netguard.install()
buf = io.StringIO()
handler = logging.StreamHandler(buf)
handler.setLevel(logging.WARNING)
log = logging.getLogger("app.ingest.netguard")
log.addHandler(handler)
log.setLevel(logging.WARNING)

blocked = 0
cases = [
    ("none_lease", lambda: netguard.egress_window(None, validate=lambda: True)),
    ("no_validate", lambda: netguard.egress_window(object())),
    ("validate_false", lambda: netguard.egress_window(object(), validate=lambda: False)),
]
for label, opener in cases:
    try:
        with opener():
            print("OPENED", label, file=sys.stderr)
            raise SystemExit(4)
    except netguard.EgressBlocked as exc:
        if "lease" not in str(exc).lower() and getattr(exc, "args", (None,))[0] != "lease":
            print("WRONG_CODE", label, exc, file=sys.stderr)
            raise SystemExit(4)
        blocked += 1

text = buf.getvalue()
print("LOG_TEXT_BEGIN")
print(text)
print("LOG_TEXT_END")
lease_lines = [ln for ln in text.splitlines() if "category=lease" in ln]
if blocked != 3:
    print("BLOCKED_COUNT", blocked, file=sys.stderr)
    raise SystemExit(4)
if len(lease_lines) < 3:
    print("MISSING_LEASE_AUDIT", "lines", len(lease_lines), file=sys.stderr)
    raise SystemExit(4)
blob = "\n".join(lease_lines)
if "event=" not in blob or "window=" not in blob:
    print("MISSING_FIELDS", blob, file=sys.stderr)
    raise SystemExit(4)
lower = blob.lower()
if "https://" in lower or "traceback" in lower or "licence=" in lower:
    print("LEAK", blob, file=sys.stderr)
    raise SystemExit(4)
print("A58_LEASE_AUDIT_OK", len(lease_lines))
raise SystemExit(0)
"""
    proc = subprocess.run(
        [PY, "-c", code],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
        env=env,
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    assert "SECRET" not in out and "licence=" not in out.lower()
    if proc.returncode != 0 or "A58_LEASE_AUDIT_OK" not in (proc.stdout or ""):
        raise AssertionError(
            f"开窗被拒未写 lease 审计日志（T-A93：netguard.py:172 应补）。"
            f" rc={proc.returncode}\nstdout={proc.stdout[-800:]}\nstderr={proc.stderr[-800:]}"
        )
