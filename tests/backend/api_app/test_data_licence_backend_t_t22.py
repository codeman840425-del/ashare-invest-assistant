"""T-T22：契约 v0.2.6 的后端静态对照（不连数据库、不发 HTTP、不联网）。

- 组 4：后端 ``HorizonCap.kind`` 取值（库内 caps CHECK 用的 ``HORIZON_CAP_KINDS``）只能是 ``gate``、``data_missing``；
- 组 1/3 相关：``ingest`` 遇 ``MAIRUI_LICENCE`` 非空拒绝启动（plan 2.1B-7），且不输出该值或其片段；
- ``config/ingest.yaml`` 的 ``data_sharing.allow_cross_licence_fallback`` 必须为 false（plan 2.1B-4 硬规则）。

分类器 caps 种类（T-B16b）与遗留证书拒绝启动（bc0b3d8）已在 origin/main 6908fc5，直接断言防回归；
仓库 ``config/ingest.yaml`` 尚无 data_sharing 段时 imperative xfail（后端 T-B04a 扩展）。

证书值一律运行时生成的虚构串（大写辅音字母，不含数字与十六进制字母），源码中没有证书字面量。
"""

from __future__ import annotations

import importlib
import os
import secrets
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

pytestmark = [pytest.mark.unit]

B04A_CFG = "后端 T-B04a 扩展（plan §6.1 v0.2.6：config/ingest.yaml 加 licences / data_sharing 段）"
FAKE_ALPHABET = "BCDFGJKMNQRVWXZ"  # 无元音、无 H/T/L/P/S/Y、无数字与十六进制字母：不会与 HTTP、错误码、uuid、时间戳偶然重合
REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = Path(os.environ.get("AIA_CONFIG_DIR") or REPO_ROOT / "config").resolve()  # 同 conftest.resolve_config_dir


def fake_licence(n: int = 32) -> str:
    return "".join(secrets.choice(FAKE_ALPHABET) for _ in range(n))


def windows(s: str, k: int = 4) -> set[str]:
    return {s[i : i + k] for i in range(len(s) - k + 1)}


def test_backend_horizon_cap_kinds_are_gate_and_data_missing(backend: SimpleNamespace) -> None:
    mod = importlib.import_module("app.db.tables.strategy")
    assert set(mod.HORIZON_CAP_KINDS) == {"gate", "data_missing"}
    assert "requires" not in mod.HORIZON_CAP_KINDS


def test_ingest_refuses_to_start_with_legacy_licence_env(backend: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
                                                         capfd: pytest.CaptureFixture[str]) -> None:
    ingest = importlib.import_module("app.workers.ingest")
    present = ingest.legacy_licence_present
    lic = fake_licence()
    assert present({"MAIRUI_LICENCE": lic}) is True
    assert present({"MAIRUI_LICENCE": ""}) is False and present({"MAIRUI_LICENCE": "  \t"}) is False and present({}) is False
    monkeypatch.setenv("MAIRUI_LICENCE", lic)
    monkeypatch.setenv("MAIRUI_MODE", "replay")
    assert present() is True  # 守卫先于任何连接；只有确认会走守卫分支才调用 main()
    # main() installs an irreversible process audit hook before rejecting the licence.
    # Run the real startup assertion in a fresh interpreter, keeping pytest unguarded.
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", "from app.workers import ingest\nassert ingest.main() == 78"],
        cwd=Path(ingest.__file__).resolve().parents[2],
        env=os.environ.copy(), capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert proc.returncode == 0, "isolated ingest startup assertion failed"
    out = capfd.readouterr()
    blob = out.out + out.err + proc.stdout + proc.stderr
    assert "MAIRUI_LICENCE" in blob
    assert not [w for w in windows(lic) if w in blob], "拒绝启动的提示含证书片段"


def test_repo_ingest_yaml_forbids_cross_licence_fallback() -> None:
    p = CONFIG_DIR / "ingest.yaml"
    if not p.is_file():
        pytest.skip(f"{CONFIG_DIR.name}/ingest.yaml 不存在")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if "data_sharing" not in data:
        pytest.xfail(B04A_CFG + "：仓库 ingest.yaml 尚无 data_sharing 段")
    ds = data["data_sharing"]
    assert ds["allow_cross_licence_fallback"] is False
    assert ds["mode"] in {"per_licence", "shared_cache"} and ds["mode"] == "per_licence"
